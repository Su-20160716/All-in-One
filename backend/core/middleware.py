"""core 中间件：
- MaintenanceModeMiddleware（F639 维护模式守卫）：开启后非 superuser 的 /api/ 请求
  一律返回统一的 503 结构化提示；默认关闭，不影响任何现有接口。
- PAT 鉴权（F621）：`Authorization: Bearer pat_xxx` 或 `X-Api-Token: pat_xxx`
  校验长期访问令牌后，就地换成一个短期 JWT，交给 DRF 既有鉴权链路。

注册说明：`config/settings.py` 的 MIDDLEWARE 已注册 `core.middleware.OperationLogMiddleware`
（config/ 属于本次不可改动范围），因此维护模式与 PAT 鉴权以基类/前置钩子的形式挂在
该类上——它的 process_request 恰好在鉴权中间件之后、视图执行之前运行，效果等价于
独立中间件；两者默认均为「放行」，开启维护模式前行为完全不变。

- OperationLogMiddleware：统一操作日志（写请求记录到 OperationLog），原有行为保持不变。
"""
import logging

logger = logging.getLogger(__name__)

import hashlib
import json
import re

from django.http import JsonResponse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from core.models import OperationLog
from core.platform import MAINTENANCE_PUBLIC_PREFIXES, maintenance_enabled
from core.utils import get_client_ip

# 跳过路径（避免噪音）。口令类接口必须在内：OperationLog 会把 JSON body 落库，
# 而管理员可通过 /api/core/logs/ 读回，口令一旦入日志等于全站密码泄露。
SKIP_PREFIXES = (
    "/admin", "/static", "/media",
    "/api/auth/token", "/api/auth/refresh", "/api/auth/verify", "/api/auth/login",
    "/api/auth/profile/change-password",
    "/api/auth/profile/deactivate",
    "/api/auth/profile/2fa",
    "/api/auth/admin/users",  # 含 <pk>/reset-password/
)

# 键名命中即脱敏（双保险：即使将来新增口令接口忘了加白名单，也不会写进日志）
_SENSITIVE_KEY_HINTS = (
    "password", "passwd", "secret", "token", "credential",
    "totp", "otp_code", "verify_code", "captcha",
)


def _safe_detail(body: dict) -> str:
    """把请求体压成一行日志摘要，敏感键一律打码"""
    parts = []
    for k, v in list(body.items())[:8]:
        low = str(k).lower()
        if any(h in low for h in _SENSITIVE_KEY_HINTS):
            parts.append(f"{k}: ***")
        else:
            parts.append(f"{k}: {str(v)[:40]}")
    return "{" + ", ".join(parts) + "}"

PAT_PREFIX = "pat_"

# F01：字段级前后值对比只覆盖三类高频业务对象，避免全局序列化开销
DIFF_TARGETS = (
    (re.compile(r"^/api/notes/(\d+)/$"), "notes.Note",
     ("title", "content", "is_public", "is_archived", "folder_id")),
    (re.compile(r"^/api/files/(\d+)/$"), "files.FileMeta",
     ("name", "description", "folder_id", "is_star")),
    (re.compile(r"^/api/projects/(\d+)/$"), "projects.Project",
     ("name", "description", "status", "is_archived")),
)


def _diff_target(path):
    for pattern, model_path, fields in DIFF_TARGETS:
        m = pattern.match(path)
        if m:
            return model_path, m.group(1), fields
    return None


def _load_instance(model_path, pk):
    from django.apps import apps

    app_label, model_name = model_path.split(".")
    return apps.get_model(app_label, model_name).objects.filter(pk=pk).first()


def _snapshot(obj, fields):
    out = {}
    for field in fields:
        value = getattr(obj, field, None)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        out[field] = value
    return out


def _build_diff(request, response, path):
    if not (200 <= response.status_code < 300):
        return None
    before = getattr(request, "_audit_before", None)
    target = _diff_target(path)
    if not before or target is None:
        return None
    obj = _load_instance(target[0], target[1])
    if obj is None:
        return None
    after = _snapshot(obj, target[2])
    changed = {
        k: {"before": before.get(k), "after": after.get(k)}
        for k in target[2]
        if before.get(k) != after.get(k)
    }
    return changed or None


# ---------------------------------------------------------------------------
# F621 长期访问令牌（PAT）→ 短期 JWT 换发
# ---------------------------------------------------------------------------
def _pat_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def pat_authenticate(request):
    """把合法的 PAT 换成一次性 JWT；返回 JsonResponse 表示直接拒绝，None 表示放行。"""
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    raw = ""
    if auth[:7].lower() == "bearer ":
        candidate = auth[7:].strip()
        if candidate.startswith(PAT_PREFIX):
            raw = candidate
    if not raw:
        raw = (request.headers.get("X-Api-Token") or "").strip()
    if not raw or not raw.startswith(PAT_PREFIX):
        return None  # 普通 JWT / 无令牌：交给 DRF
    try:
        from accounts.models import PersonalAccessToken
        from rest_framework_simplejwt.tokens import AccessToken

        pat = (
            PersonalAccessToken.objects.filter(token_hash=_pat_hash(raw))
            .select_related("user")
            .first()
        )
        if pat is None or not pat.is_valid:
            return JsonResponse(
                {"ok": False, "code": 401, "error": "invalid_token",
                 "message": "访问令牌无效、已过期或已被吊销"},
                status=401,
            )
        user = pat.user
        if not user.is_active or getattr(user, "is_disabled", False):
            return JsonResponse(
                {"ok": False, "code": 401, "error": "account_disabled",
                 "message": "账号不可用，令牌无法使用"},
                status=401,
            )
        # 换发短期 JWT（DRF 默认 JWTAuthentication 直接可用）。
        # 必须写入 tv claim：鉴权端是 TokenVersionJWTAuthentication，缺 tv 一律判失效，
        # 否则 PAT 换出来的 token 每个请求都会 401。
        access = AccessToken.for_user(user)
        access["tv"] = user.token_version
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {access}"
        now = timezone.now()
        if not pat.last_used_at or (now - pat.last_used_at).total_seconds() > 60:
            PersonalAccessToken.objects.filter(pk=pat.pk).update(last_used_at=now)
        return None
    except Exception:
        # 降级：不拦截，交给 DRF 正常鉴权（会得到标准 401）
        return None


# ---------------------------------------------------------------------------
# F639 维护模式守卫
# ---------------------------------------------------------------------------
def _is_superuser_request(request) -> bool:
    """会话用户（Django admin）或 JWT 用户是否为 superuser；任何异常都按「非超管」处理"""
    try:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_superuser:
            return True
    except Exception:
        logger.exception("B23：静默兜底已登记（core/middleware.py:93 原为 pass）——review 是否应收窄异常类型")
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth[:7].lower() == "bearer " and not auth[7:].strip().startswith(PAT_PREFIX):
        try:
            from rest_framework_simplejwt.authentication import JWTAuthentication

            result = JWTAuthentication().authenticate(request)
            if result and result[0] is not None and result[0].is_superuser:
                return True
        except Exception:
            return False
    return False


def maintenance_response(request):
    """维护模式开启时，非 superuser 的 /api/ 请求 → 统一 503 结构化提示"""
    try:
        if request.method == "OPTIONS":
            return None
        path = request.path
        if not path.startswith("/api/"):
            return None
        if any(path.startswith(p) for p in MAINTENANCE_PUBLIC_PREFIXES):
            return None
        if not maintenance_enabled():
            return None
        if _is_superuser_request(request):
            return None
        return JsonResponse(
            {
                "ok": False,
                "code": 503,
                "error": "maintenance",
                "message": "系统维护中，请稍后再试（超级管理员不受影响）",
                "detail": {"maintenance": True, "retry_after": 60},
            },
            status=503,
        )
    except Exception:
        return None  # 守卫自身异常必须放行，绝不影响现有接口


class MaintenanceModeMiddleware(MiddlewareMixin):
    """F639 维护模式中间件（默认关闭）"""

    def process_request(self, request):
        return maintenance_response(request)


class OperationLogMiddleware(MaintenanceModeMiddleware):
    """统一操作日志中间件 + 维护模式 / PAT 鉴权（继承其 process_request）"""

    # B7：只预读小体积 JSON / 表单 body（上限 1MB），大文件分片上传不碰
    _PREFETCH_MAX_BYTES = 1_000_000

    def process_request(self, request):
        denied = pat_authenticate(request)
        if denied is not None:
            return denied
        # B7：提前把 body 读进 _body 缓存。DRF 视图解析 request.data 时会消费
        # 底层流并标记 _read_started，之后在 process_response 里读 request.body
        # 会抛 RawPostDataException，导致操作日志 detail 恒为空；
        # 这里在读流前预读，视图与日志阶段共用同一份缓存
        self._prefetch_body(request)
        self._snapshot_before(request)
        return super().process_request(request)

    def _snapshot_before(self, request):
        """F01：PATCH/PUT 前快照白名单对象，供响应阶段计算字段级 diff"""
        try:
            if request.method not in ("PUT", "PATCH"):
                return
            target = _diff_target(request.path)
            if target is None:
                return
            obj = _load_instance(target[0], target[1])
            if obj is not None:
                request._audit_before = _snapshot(obj, target[2])
        except Exception:
            request._audit_before = None

    def _prefetch_body(self, request):
        try:
            ct = (request.content_type or "").lower()
            if "json" not in ct and "form-urlencoded" not in ct:
                return
            length = int(request.META.get("CONTENT_LENGTH") or 0)
            if length > self._PREFETCH_MAX_BYTES:
                return
            _ = request.body
        except Exception:
            logger.exception("B23：静默兜底已登记（core/middleware.py:169 原为 pass）——review 是否应收窄异常类型")

    def process_response(self, request, response):
        try:
            path = request.path
            if request.method == "GET" or request.method in ("HEAD", "OPTIONS"):
                return response
            if any(path.startswith(p) for p in SKIP_PREFIXES):
                return response
            if not request.user or not request.user.is_authenticated:
                return response

            # 只记录轻量信息，不读取 body
            detail = ""
            try:
                ct = request.content_type or ""
                if "json" in ct and request.body:
                    body = json.loads(request.body[:4096].decode("utf-8", "ignore"))
                    if isinstance(body, dict):
                        detail = _safe_detail(body)
            except Exception:
                logger.exception("B23：静默兜底已登记（core/middleware.py:190 原为 pass）——review 是否应收窄异常类型")

            # B7：/api/projects/1/boards/ 原来取 parts[0] 恒为 "api"，
            # 模块分组全是同一值；改为跳过 api 前缀取真实模块名
            parts = [p for p in path.strip("/").split("/") if p]
            if len(parts) >= 2 and parts[0] == "api":
                module = parts[1]
            elif parts:
                module = parts[0]
            else:
                module = "root"
            action_map = {
                "POST": "create",
                "PUT": "update",
                "PATCH": "update",
                "DELETE": "delete",
            }
            if "/upload" in path or "upload" in path:
                action = "upload"
            else:
                action = action_map.get(request.method, "other")

            diff = _build_diff(request, response, path)

            OperationLog.objects.create(
                user=request.user,
                module=module,
                action=action,
                target=path,
                detail=detail,
                diff=diff,
                ip=get_client_ip(request),
            )
        except Exception:
            logger.exception("B23：静默兜底已登记（core/middleware.py:221 原为 pass）——review 是否应收窄异常类型")
        return response
