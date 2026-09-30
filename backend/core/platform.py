# -*- coding: utf-8 -*-
"""平台运维助手（支撑 F627–F642）。

集中放置「管理与平台」类能力的纯函数：健康卡、数据表统计、关于页、
维护模式开关、异常聚合、跨模块审计检索、日志 CSV 导出、慢接口采样。

铁律：
- 任何函数都不允许抛出未捕获异常（全部 try/except 降级）；
- 绝不返回 SECRET_KEY / 密码 / Token 等敏感原文（统一走 mask）；
- git、dbstat 等外部能力拿不到时返回结构化降级结果，而不是报错。
"""
import csv
import hashlib
import io
import os
import re
import subprocess
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

# 进程启动时间（模块首次导入时刻），用于「关于页」的运行时长
_BOOT_AT = time.time()

# ---------------------------------------------------------------------------
# 维护模式开关（F639）—— 带 5 秒进程内缓存，避免每个请求都查库
# ---------------------------------------------------------------------------
MAINTENANCE_KEY = "maintenance_mode"
_MAINT_CACHE = {"value": False, "at": 0.0}
_MAINT_TTL = 5.0

# 维护模式下仍允许访问的公开路径（保证超管能登录、前端能探活/看关于页）
MAINTENANCE_PUBLIC_PREFIXES = (
    "/api/auth/login/",
    "/api/auth/refresh/",
    "/api/auth/verify/",
    "/api/core/health/",
    "/api/core/about/",
    "/api/core/settings/public/",
)


def maintenance_enabled(force: bool = False) -> bool:
    """读取维护模式开关（查库失败时优雅降级为「关闭」，不影响服务）"""
    now = time.time()
    if not force and _MAINT_CACHE["value"] is not None and now - _MAINT_CACHE["at"] < _MAINT_TTL:
        return _MAINT_CACHE["value"]
    value = False
    try:
        from core.models import SiteSetting

        raw = SiteSetting.objects.filter(key=MAINTENANCE_KEY).values_list("value", flat=True).first()
        value = str(raw or "").strip().lower() in ("1", "true", "yes", "on")
    except Exception:
        value = False
    _MAINT_CACHE["value"] = value
    _MAINT_CACHE["at"] = now
    return value


def set_maintenance(enabled: bool) -> bool:
    """写入维护模式开关并立即刷新缓存"""
    from core.models import SiteSetting

    obj, _ = SiteSetting.objects.get_or_create(
        key=MAINTENANCE_KEY, defaults={"value": "1" if enabled else "0", "label": "维护模式开关"}
    )
    if obj.value != ("1" if enabled else "0"):
        obj.value = "1" if enabled else "0"
        obj.save(update_fields=["value", "updated_at"])
    _MAINT_CACHE["value"] = bool(enabled)
    _MAINT_CACHE["at"] = time.time()
    return bool(enabled)


# ---------------------------------------------------------------------------
# 敏感信息脱敏（F638）
# ---------------------------------------------------------------------------
_SENSITIVE_RE = re.compile(r"SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE|CREDENTIAL|REDIS|DSN$", re.I)


def mask_value(key: str, value):
    """敏感键一律脱敏，只回显长度/布尔；绝不返回 SECRET_KEY 原文"""
    text = "" if value is None else str(value)
    if _SENSITIVE_RE.search(key or ""):
        if not text:
            return "(空)"
        return f"••••••(已脱敏, 长度 {len(text)})"
    return value


# ---------------------------------------------------------------------------
# 异常聚合（F633）
# ---------------------------------------------------------------------------
_SKIP_EXC_NAMES = {
    "ValidationError", "ValueError", "Http404", "PermissionDenied", "MethodNotAllowed",
    "NotAuthenticated", "AuthenticationFailed", "NotFound", "ParseError", "Throttled",
    "APIException", "UnsupportedMediaType", "Duplicate",
}
_MSG_NOISE = re.compile(r"\b\d+\b")


def should_record_exception(exc) -> bool:
    """只聚合「非客户端输入类」异常，避免 4xx 噪音"""
    return type(exc).__name__ not in _SKIP_EXC_NAMES


def record_exception(exc, path: str = "", extra: str = "") -> bool:
    """按签名聚合一条异常（类型 + 规范化消息 + 出错位置）。失败静默。"""
    try:
        if not should_record_exception(exc):
            return False
        from core.models import ExceptionRecord

        etype = type(exc).__name__
        message = _MSG_NOISE.sub("N", str(exc))[:400].strip()
        location = ""
        tb = getattr(exc, "__traceback__", None)
        if tb is not None:
            import traceback

            frames = traceback.extract_tb(tb)
            if frames:
                last = frames[-1]
                location = f"{os.path.basename(last.filename)}:{last.lineno} {last.name}"
        signature = hashlib.sha1(
            f"{etype}|{message}|{location}|{extra}".encode("utf-8", "ignore")
        ).hexdigest()[:40]
        sample = ""
        try:
            import traceback as _tb

            sample = _tb.format_exc()
            if not sample or sample.strip() == "NoneType: None":
                sample = f"{etype}: {message}"
            sample = sample[-3000:]
        except Exception:
            sample = f"{etype}: {exc}"
        obj, created = ExceptionRecord.objects.get_or_create(
            signature=signature,
            defaults={
                "etype": etype,
                "message": message,
                "location": location,
                "path": (path or "")[:200],
                "sample": sample,
            },
        )
        if not created:
            updates = {"count": obj.count + 1, "last_at": timezone.now()}
            if path:
                updates["path"] = path[:200]
            ExceptionRecord.objects.filter(pk=obj.pk).update(**updates)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 后端健康卡（F627）
# ---------------------------------------------------------------------------
def _dir_size(path, file_limit: int = 60000):
    total, n, truncated = 0, 0, False
    p = Path(path)
    if not p.exists():
        return 0, 0, False
    for root, _dirs, files in os.walk(str(p)):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            n += 1
            if n >= file_limit:
                return total, n, True
    return total, n, False


def human_size(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


def health_card() -> dict:
    """DB / 表数 / 最新迁移 / 存储占用 健康卡"""
    out = {
        "status": "ok",
        "checked_at": timezone.now().isoformat(),
        "db": {"ok": False, "engine": "", "name": "", "latency_ms": 0},
        "tables": {"count": 0},
        "migration": {"count": 0, "latest": None},
        "storage": {"db_bytes": 0, "media_bytes": 0, "total_bytes": 0, "total_text": "0 B"},
        "runtime": {},
    }
    try:
        t0 = time.time()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        out["db"]["ok"] = True
        out["db"]["latency_ms"] = int((time.time() - t0) * 1000)
    except Exception as exc:
        out["status"] = "degraded"
        out["db"]["error"] = f"{type(exc).__name__}"
        return out

    try:
        eng = settings.DATABASES.get("default", {})
        out["db"]["engine"] = eng.get("ENGINE", "").rsplit(".", 1)[-1]
        out["db"]["name"] = os.path.basename(str(eng.get("NAME", "")))
    except Exception:
        pass

    try:
        tables = connection.introspection.table_names()
        out["tables"]["count"] = len(tables)
    except Exception:
        out["tables"]["count"] = 0

    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT app_label, name, applied_at FROM django_migrations ORDER BY applied_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                out["migration"]["latest"] = {
                    "app": row[0], "name": row[1],
                    "applied_at": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
                }
            cur.execute("SELECT COUNT(*) FROM django_migrations")
            out["migration"]["count"] = int(cur.fetchone()[0])
    except Exception:
        pass

    try:
        db_name = str(settings.DATABASES.get("default", {}).get("NAME", ""))
        db_bytes = os.path.getsize(db_name) if db_name and os.path.exists(db_name) else 0
        media_bytes, _n, _trunc = _dir_size(settings.MEDIA_ROOT)
        out["storage"] = {
            "db_bytes": db_bytes,
            "db_text": human_size(db_bytes),
            "media_bytes": media_bytes,
            "media_text": human_size(media_bytes),
            "total_bytes": db_bytes + media_bytes,
            "total_text": human_size(db_bytes + media_bytes),
        }
    except Exception:
        pass

    import django
    import platform as _platform

    out["runtime"] = {
        "django": django.get_version(),
        "python": _platform.python_version(),
        "platform": _platform.platform(),
        "debug": bool(getattr(settings, "DEBUG", False)),
        "version": getattr(settings, "PLATFORM_VERSION", ""),
        "uptime_seconds": int(time.time() - _BOOT_AT),
        "uptime_text": _uptime_text(int(time.time() - _BOOT_AT)),
    }
    return out


def _uptime_text(seconds: int) -> str:
    d, rem = divmod(max(0, seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d} 天")
    if h or d:
        parts.append(f"{h} 小时")
    parts.append(f"{m} 分")
    parts.append(f"{s} 秒")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 数据表行数 / 体积统计（F635）
# ---------------------------------------------------------------------------
def table_stats(top: int = 60) -> dict:
    """遍历已安装模型统计行数；体积优先用 SQLite dbstat，拿不到则按行数估算"""
    from django.apps import apps as _apps

    rows, total_rows, unknown = [], 0, 0
    sizes: dict = {}
    size_source = "dbstat"
    db_bytes = 0
    try:
        db_name = str(settings.DATABASES.get("default", {}).get("NAME", ""))
        if db_name and os.path.exists(db_name):
            db_bytes = os.path.getsize(db_name)
        with connection.cursor() as cur:
            cur.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name")
            for name, size in cur.fetchall():
                sizes[name] = int(size or 0)
    except Exception:
        size_source = "estimate" if db_bytes else "none"

    for model in _apps.get_models():
        try:
            if not model._meta.managed:
                continue
            table = model._meta.db_table
            count = model.objects.count()
        except Exception:
            unknown += 1
            continue
        total_rows += count
        rows.append({
            "app": model._meta.app_label,
            "model": model._meta.model_name,
            "table": table,
            "rows": count,
            "bytes": sizes.get(table, 0),
        })

    rows.sort(key=lambda r: (-r["rows"], r["table"]))
    if size_source == "estimate" and total_rows:
        for r in rows:
            r["bytes"] = int(db_bytes * (r["rows"] / total_rows)) if total_rows else 0
    if size_source == "none":
        for r in rows:
            r["bytes"] = 0
    for r in rows:
        r["bytes_text"] = human_size(r["bytes"])
        r["pct"] = round(r["bytes"] * 100.0 / db_bytes, 2) if db_bytes else 0.0

    return {
        "total_tables": len(rows),
        "total_rows": total_rows,
        "unknown_tables": unknown,
        "db_bytes": db_bytes,
        "db_text": human_size(db_bytes),
        "size_source": size_source,
        "tables": rows[:top],
        "truncated": len(rows) > top,
        "generated_at": timezone.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# 关于页（F642）
# ---------------------------------------------------------------------------
def _git_info() -> dict:
    """最近一次提交；git 不可用/非仓库时优雅降级（不抛异常）"""
    base = Path(settings.BASE_DIR).parent
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%H%n%h%n%ad%n%s", "--date=short"],
            cwd=str(base), capture_output=True, timeout=4, text=True,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            return {"available": False, "reason": (err[0][:160] if err else "GIT_UNAVAILABLE")}
        lines = (proc.stdout or "").strip().splitlines()
        if len(lines) < 4:
            return {"available": False, "reason": "NO_COMMITS"}
        return {
            "available": True,
            "hash": lines[1],
            "full_hash": lines[0][:12],
            "date": lines[2],
            "subject": lines[3][:160],
        }
    except FileNotFoundError:
        return {"available": False, "reason": "GIT_NOT_FOUND"}
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "GIT_TIMEOUT"}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": type(exc).__name__}


def about_info() -> dict:
    """版本 / 最近提交 / 运行时长 / 运行环境"""
    import django
    import platform as _platform

    up = int(time.time() - _BOOT_AT)
    try:
        from core.models import SiteSetting

        site_name = SiteSetting.objects.filter(key="site_name").values_list("value", flat=True).first()
    except Exception:
        site_name = ""
    return {
        "name": site_name or "全能协作平台",
        "version": getattr(settings, "PLATFORM_VERSION", ""),
        "git": _git_info(),
        "runtime": {
            "python": _platform.python_version(),
            "django": django.get_version(),
            "platform": _platform.platform(terse=True),
            "server_time": timezone.now().isoformat(),
            "started_at": timezone.datetime.fromtimestamp(
                _BOOT_AT, tz=timezone.get_current_timezone()
            ).isoformat(),
            "uptime_seconds": up,
            "uptime_text": _uptime_text(up),
        },
        "database": {
            "engine": settings.DATABASES.get("default", {}).get("ENGINE", "").rsplit(".", 1)[-1],
        },
        "flags": {
            "debug": bool(getattr(settings, "DEBUG", False)),
            "search_enabled": bool(getattr(settings, "SEARCH_ENABLED", True)),
            "tenancy_enabled": bool(getattr(settings, "TENANCY_ENABLED", False)),
            "llm_configured": bool(getattr(settings, "LLM_API_KEY", "")),
        },
    }


# ---------------------------------------------------------------------------
# 日志导出 CSV（F628）
# ---------------------------------------------------------------------------
def csv_response(filename: str, header, rows) -> "object":
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for r in rows:
        writer.writerow(r)
    from django.http import HttpResponse

    resp = HttpResponse("\ufeff" + buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f"attachment; filename={filename}"
    return resp


def export_logs_csv(kind: str, request) -> "object":
    """kind: operation（操作日志）| login（登录日志）| exception（异常聚合）"""
    from core.models import OperationLog

    if kind == "login":
        from accounts.models import LoginLog

        qs = LoginLog.objects.select_related("user").order_by("-created_at")[:20000]
        header = ["时间", "账号", "用户ID", "IP", "设备", "是否成功", "User-Agent"]
        rows = [
            [x.created_at.strftime("%Y-%m-%d %H:%M:%S"), x.username, x.user_id or "",
             x.ip or "", x.device or "", "成功" if x.is_success else "失败", (x.user_agent or "")[:120]]
            for x in qs
        ]
        return csv_response("login_logs.csv", header, rows)

    if kind == "exception":
        from core.models import ExceptionRecord

        qs = ExceptionRecord.objects.order_by("-last_at")[:20000]
        header = ["最近出现", "首次出现", "次数", "异常类型", "消息", "位置", "路径", "签名"]
        rows = [
            [x.last_at.strftime("%Y-%m-%d %H:%M:%S"), x.first_at.strftime("%Y-%m-%d %H:%M:%S"),
             x.count, x.etype, x.message, x.location, x.path, x.signature]
            for x in qs
        ]
        return csv_response("exceptions.csv", header, rows)

    # 默认：操作日志（支持既有筛选参数）
    from core.views import _filter_logs  # 惰性导入避免循环

    qs = _filter_logs(request, OperationLog.objects.select_related("user"))[:20000]
    header = ["时间", "用户", "模块", "动作", "对象", "IP", "详情"]
    rows = [
        [x.created_at.strftime("%Y-%m-%d %H:%M:%S"), x.user.username if x.user else "",
         x.module, x.action, x.target, x.ip or "", x.detail]
        for x in qs
    ]
    return csv_response("operation_logs.csv", header, rows)


# ---------------------------------------------------------------------------
# 跨模块审计检索（F640）
# ---------------------------------------------------------------------------
def audit_search(q: str = "", kinds=None, limit: int = 50) -> dict:
    """跨 操作日志 / 登录日志 / 角色变更 / 管理命令 / 异常记录 统一检索"""
    q = (q or "").strip()
    limit = min(max(int(limit or 50), 1), 200)
    kinds = set(kinds or ["operation", "login", "role", "command", "exception"])
    items = []

    def hit(*vals):
        if not q:
            return True
        return any(q.lower() in str(v or "").lower() for v in vals)

    try:
        if "operation" in kinds:
            from core.models import OperationLog

            qs = OperationLog.objects.select_related("user").order_by("-created_at")
            if q:
                qs = qs.filter(
                    target__icontains=q
                ) | qs.filter(detail__icontains=q) | qs.filter(user__username__icontains=q)
            for x in qs[:limit]:
                if hit(x.target, x.detail, x.user.username if x.user else "", x.module):
                    items.append({
                        "kind": "operation", "kind_label": "操作日志",
                        "time": x.created_at, "actor": x.user.username if x.user else "系统",
                        "action": x.action, "module": x.module,
                        "summary": f"{x.module}/{x.action} {x.target}"[:180],
                        "detail": (x.detail or "")[:240], "ip": x.ip or "",
                    })
    except Exception:
        pass

    try:
        if "login" in kinds:
            from accounts.models import LoginLog

            qs = LoginLog.objects.order_by("-created_at")
            if q:
                qs = qs.filter(username__icontains=q) | qs.filter(ip__icontains=q)
            for x in qs[:limit]:
                if hit(x.username, x.ip, x.device):
                    items.append({
                        "kind": "login", "kind_label": "登录日志",
                        "time": x.created_at, "actor": x.username,
                        "action": "login_ok" if x.is_success else "login_fail",
                        "module": "accounts",
                        "summary": f"{'登录成功' if x.is_success else '登录失败'} {x.username}",
                        "detail": f"{x.device} · {x.ip or '未知IP'}", "ip": x.ip or "",
                    })
    except Exception:
        pass

    try:
        if "role" in kinds:
            from accounts.models import RoleAuditLog

            qs = RoleAuditLog.objects.select_related("actor", "target").order_by("-created_at")
            if q:
                qs = qs.filter(target__username__icontains=q) | qs.filter(
                    actor__username__icontains=q
                )
            for x in qs[:limit]:
                if hit(
                    x.target.username if x.target else "",
                    x.actor.username if x.actor else "",
                    x.roles_from, x.roles_to, x.detail,
                ):
                    items.append({
                        "kind": "role", "kind_label": "角色变更",
                        "time": x.created_at, "actor": x.actor.username if x.actor else "系统",
                        "action": x.action, "module": "accounts",
                        "summary": (
                            f"{x.target.username if x.target else '?'} 角色 "
                            f"{','.join(x.roles_from) or '∅'} → {','.join(x.roles_to) or '∅'}"
                        )[:180],
                        "detail": x.detail, "ip": x.ip or "",
                    })
    except Exception:
        pass

    try:
        if "command" in kinds:
            from core.models import AdminCommandRun

            qs = AdminCommandRun.objects.select_related("ran_by").order_by("-started_at")
            if q:
                qs = qs.filter(command__icontains=q)
            for x in qs[:limit]:
                if hit(x.command, x.ran_by.username if x.ran_by else ""):
                    items.append({
                        "kind": "command", "kind_label": "管理命令",
                        "time": x.started_at, "actor": x.ran_by.username if x.ran_by else "系统",
                        "action": "run_ok" if x.ok else "run_fail", "module": "core",
                        "summary": f"执行命令 {x.command}（{'成功' if x.ok else '失败'}）",
                        "detail": (x.output or x.error or "")[:240], "ip": "",
                    })
    except Exception:
        pass

    try:
        if "exception" in kinds:
            from core.models import ExceptionRecord

            qs = ExceptionRecord.objects.order_by("-last_at")
            if q:
                qs = qs.filter(etype__icontains=q) | qs.filter(message__icontains=q)
            for x in qs[:limit]:
                if hit(x.etype, x.message, x.location, x.path):
                    items.append({
                        "kind": "exception", "kind_label": "异常聚合",
                        "time": x.last_at, "actor": "system", "action": "exception",
                        "module": "core",
                        "summary": f"{x.etype} ×{x.count}：{x.message}"[:180],
                        "detail": f"{x.location} {x.path}".strip(), "ip": "",
                    })
    except Exception:
        pass

    items.sort(key=lambda r: r["time"] or timezone.now(), reverse=True)
    return {"list": items[:limit], "total": len(items), "keyword": q,
            "kinds": sorted(kinds), "generated_at": timezone.now().isoformat()}


# ---------------------------------------------------------------------------
# 慢接口采样（F632）
# ---------------------------------------------------------------------------
SLOW_MS = 1000
MAX_PATHS = 400


def normalize_path(path: str) -> str:
    """去掉查询串、把数字段折成 :id，避免高基数路径把表撑爆"""
    path = (path or "").split("?")[0][:200]
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/\d+(?=/|$)", "/:id", path)
    return path


def report_latency(samples) -> dict:
    """接收前端上报的耗时样本并聚合；忽略非法样本"""
    from core.models import SlowEndpoint

    if not isinstance(samples, list):
        raise ValueError("samples 必须是数组")
    samples = samples[:200]
    accepted = ignored = 0
    existing = SlowEndpoint.objects.values_list("path", flat=True)
    known = set(existing)
    for s in samples:
        if not isinstance(s, dict):
            ignored += 1
            continue
        path = normalize_path(str(s.get("path", "")))
        try:
            dur = int(float(s.get("duration", 0)))
        except (TypeError, ValueError):
            ignored += 1
            continue
        if not path or path == "/" or dur < 0 or dur > 600000:
            ignored += 1
            continue
        if path not in known and len(known) >= MAX_PATHS:
            ignored += 1
            continue
        obj, created = SlowEndpoint.objects.get_or_create(path=path)
        SlowEndpoint.objects.filter(pk=obj.pk).update(
            samples=obj.samples + 1,
            total_ms=obj.total_ms + dur,
            slow_samples=obj.slow_samples + (1 if dur >= SLOW_MS else 0),
            max_ms=max(obj.max_ms, dur),
        )
        known.add(path)
        accepted += 1
    return {"accepted": accepted, "ignored": ignored, "threshold_ms": SLOW_MS}


def slow_endpoints(limit: int = 10) -> dict:
    from core.models import SlowEndpoint

    qs = SlowEndpoint.objects.all()
    rows = []
    for x in qs:
        if x.samples <= 0:
            continue
        rows.append({
            "path": x.path, "samples": x.samples, "slow_samples": x.slow_samples,
            "avg_ms": x.avg_ms, "max_ms": x.max_ms,
            "last_at": x.last_at.isoformat() if x.last_at else "",
        })
    rows.sort(key=lambda r: (-r["avg_ms"], -r["max_ms"]))
    return {
        "list": rows[:limit], "total": len(rows), "threshold_ms": SLOW_MS,
        "tracked_paths": len(rows),
    }
