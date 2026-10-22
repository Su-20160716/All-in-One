# -*- coding: utf-8 -*-
"""代码工坊视图（一）：工作区 / 文件 / 版本 / 运行 / 判题 / 片段。

全部接口走 `endpoint` 装饰器（ValueError→400、其余→422，绝不 500）。
"""
import difflib
import io
import json
import re
import time
import zipfile

from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone

from devtools.common import (
    endpoint, ok, fail, p, req, req_str, opt_str, req_num, opt_num, opt_bool, req_list,
)

from . import runtime as rt
from .models import (
    CodeComment, CodeFile, CodeJudgeTask, CodeRun, CodeRunPreset, CodeShare, CodeSnippet,
    CodeVersion, CodeWorkspace,
)
from .serializers import (
    build_tree, file_brief, file_qs, file_write_qs, get_file, get_ws,
    ws_brief, ws_detail, ws_qs,
)

# ============================================================
# 一、元信息 / 目录
# ============================================================


@endpoint(("GET",))
def code_catalog(request):
    """代码工坊目录：供前端渲染能力清单。"""
    return ok({
        "domain": "code",
        "domain_name": "代码工坊",
        "version": "6.0.0",
        "capabilities": [
            {"key": "editor", "name": "在线编辑器", "desc": "多标签、高亮、折叠、查找替换、自动保存"},
            {"key": "runner", "name": "安全执行", "desc": "超时/输出截断/危险拦截/结构化诊断"},
            {"key": "version", "name": "版本历史", "desc": "快照、diff、回滚"},
            {"key": "collab", "name": "实时协同", "desc": "Yjs CRDT 中继 + 在线光标"},
            {"key": "ai", "name": "智能辅助", "desc": "生成/解释/找 bug/重构/测试/复杂度"},
            {"key": "judge", "name": "判题", "desc": "多用例判定 + 排行榜"},
            {"key": "snippet", "name": "片段库", "desc": "可复用代码片段 + 检索"},
            {"key": "share", "name": "分享", "desc": "只读/可运行分享链接"},
        ],
    })


@endpoint(("GET",))
def runtimes(request):
    """运行时可用性探测（第 41 条）。

    这是「可降级适配器」约定的直接体现：探测不到的语言照常列出，
    只是 available=false，前端据此置灰而不是报错。
    """
    force = opt_bool(request, "force", False)
    table = rt.detect_all(force=force)
    items = sorted(table.values(), key=lambda x: (not x["available"], x["name"]))
    return ok({
        "runtimes": items,
        "available_count": sum(1 for i in items if i["available"]),
        "total_count": len(items),
        "platform": rt.platform.platform(),
        "is_windows": rt.IS_WINDOWS,
        "limits": {
            "default_timeout": rt.DEFAULT_TIMEOUT,
            "max_timeout": rt.MAX_TIMEOUT,
            "output_limit": rt.OUTPUT_LIMIT,
            "memory_limit_mb": rt.MEMORY_LIMIT_MB,
            "memory_enforced": not rt.IS_WINDOWS,
            "max_source_bytes": rt.MAX_SOURCE_BYTES,
        },
    })


@endpoint(("GET",))
def languages(request):
    """语言清单 + 模板。"""
    table = rt.detect_all()
    out = []
    for key, meta in rt.LANGUAGES.items():
        item = rt.language_meta(key)
        item["available"] = table.get(key, {}).get("available", False)
        item["version"] = table.get(key, {}).get("version", "")
        out.append(item)
    return ok({"languages": out})


@endpoint(("GET",))
def templates(request):
    """全部代码模板（第 17 条）。"""
    return ok({
        "templates": [
            {"key": k, "name": rt.LANGUAGES.get(k, {}).get("name", k), "code": v}
            for k, v in rt.TEMPLATES.items()
        ]
    })


# ============================================================
# 二、工作区
# ============================================================


@endpoint(("GET",))
def workspace_list(request):
    qs = ws_qs(request.user)
    q = opt_str(request, "q").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=lang)
    if opt_bool(request, "starred", False):
        qs = qs.filter(is_starred=True)
    if not opt_bool(request, "include_archived", False):
        qs = qs.filter(is_archived=False)
    return ok({"items": [ws_brief(o) for o in qs[:200]]})


@endpoint(("POST",))
def workspace_create(request):
    name = req_str(request, "name", "").strip()
    if not name:
        raise ValueError("工作区名不能为空")
    lang = rt.normalize_language(opt_str(request, "language", "python"))
    ws = CodeWorkspace.objects.create(
        name=name[:120],
        description=opt_str(request, "description", ""),
        owner=request.user,
        language=lang,
        icon=opt_str(request, "icon", "📁")[:16] or "📁",
        color=opt_str(request, "color", "brand")[:16],
    )
    # 可选：自动建一个入口文件（第 18 条模板）
    if opt_bool(request, "with_entry", True):
        meta = rt.language_meta(lang)
        CodeFile.objects.create(
            workspace=ws,
            owner=request.user,
            path=f"main{meta['ext']}",
            name=f"main{meta['ext']}",
            language=lang,
            content=meta.get("template", ""),
            is_entry=True,
        )
    return ok(ws_detail(ws, include_files=True))


@endpoint(("GET",))
def workspace_detail(request, pk):
    ws = get_ws(request.user, pk)
    data = ws_detail(ws)
    data["tree"] = build_tree(list(ws.files.all()))
    data["stats"] = _ws_stats(ws)
    return ok(data)


@endpoint(("PATCH", "POST"))
def workspace_update(request, pk):
    ws = get_ws(request.user, pk, write=True)
    for field in ("name", "description", "language", "icon", "color"):
        if p(request, field) is not None:
            val = p(request, field)
            if field == "language":
                val = rt.normalize_language(val)
            setattr(ws, field, val)
    for field in ("is_starred", "is_archived"):
        if p(request, field) is not None:
            setattr(ws, field, opt_bool(request, field))
    if p(request, "run_config") is not None:
        cfg = p(request, "run_config")
        if not isinstance(cfg, dict):
            raise ValueError("run_config 必须是对象")
        ws.run_config = cfg
    ws.save()
    return ok(ws_brief(ws))


@endpoint(("DELETE", "POST"))
def workspace_delete(request, pk):
    ws = get_ws(request.user, pk, write=True)
    ws.delete()
    return ok({"deleted": pk})


@endpoint(("POST",))
def workspace_star(request, pk):
    ws = get_ws(request.user, pk, write=True)
    ws.is_starred = not ws.is_starred
    ws.save(update_fields=["is_starred", "updated_at"])
    return ok({"is_starred": ws.is_starred})


@endpoint(("POST",))
def workspace_clone(request, pk):
    """克隆工作区（含全部文件）。"""
    src = get_ws(request.user, pk)
    new = CodeWorkspace.objects.create(
        name=f"{src.name} 副本",
        description=src.description,
        owner=request.user,
        language=src.language,
        icon=src.icon,
        color=src.color,
        run_config=src.run_config or {},
    )
    for f in src.files.all():
        CodeFile.objects.create(
            workspace=new, owner=request.user, path=f.path, name=f.name,
            language=f.language, content=f.content, is_entry=f.is_entry, order=f.order,
        )
    return ok(ws_detail(new, include_files=True))


def _ws_stats(ws):
    files = ws.files.all()
    agg = files.aggregate(total=models_sum("size"))
    langs = list(files.values("language").annotate(n=Count("id")).order_by("-n"))
    return {
        "file_count": files.count(),
        "total_bytes": agg["total"] or 0,
        "total_lines": sum(f.lines for f in files),
        "languages": langs,
        "run_count": ws.runs.count(),
    }


def models_sum(field):
    from django.db.models import Sum
    return Sum(field)


# ============================================================
# 三、代码文件
# ============================================================


@endpoint(("GET",))
def file_list(request):
    qs = file_qs(request.user)
    ws_id = opt_num(request, "workspace", integer=True)
    if ws_id:
        qs = qs.filter(workspace_id=ws_id)
    q = opt_str(request, "q").strip()
    if q:
        qs = qs.filter(Q(path__icontains=q) | Q(content__icontains=q))
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=lang)
    if opt_bool(request, "favorite", False):
        qs = qs.filter(is_favorite=True)
    limit = opt_num(request, "limit", 100, integer=True, minimum=1, maximum=500)
    return ok({"items": [file_brief(o, with_content=False) for o in qs[:limit]]})


@endpoint(("POST",))
def file_create(request):
    ws = get_ws(request.user, req(request, "workspace"), write=True)
    path = req_str(request, "path", "").strip().replace("\\", "/").lstrip("/")
    if not path:
        raise ValueError("文件路径不能为空")
    if ".." in path.split("/"):
        raise ValueError("路径不能包含 ..")
    if CodeFile.objects.filter(workspace=ws, path=path).exists():
        raise ValueError(f"文件已存在: {path}")
    lang = opt_str(request, "language", "").strip()
    lang = rt.normalize_language(lang) if lang else rt.language_from_path(path)
    name = path.rsplit("/", 1)[-1]
    content = p(request, "content")
    if content is None:
        content = rt.language_meta(lang).get("template", "")
    obj = CodeFile.objects.create(
        workspace=ws, owner=request.user, path=path, name=name,
        language=lang, content=str(content),
        is_entry=opt_bool(request, "is_entry", False),
    )
    # 首个文件自动设为入口
    if ws.files.count() == 1:
        obj.is_entry = True
        obj.save(update_fields=["is_entry"])
    return ok(file_brief(obj))


@endpoint(("GET",))
def file_detail(request, pk):
    obj = get_file(request.user, pk)
    data = file_brief(obj)
    data["versions_count"] = obj.versions.count()
    data["comments_count"] = obj.comments.count()
    data["metrics"] = rt.analyze_metrics(obj.content, obj.language)
    return ok(data)


@endpoint(("PATCH", "POST"))
def file_update(request, pk):
    """更新文件内容 / 属性。内容变更即落版本快照（可配）。"""
    obj = get_file(request.user, pk, write=True)
    old_content = obj.content
    content_changed = False

    if p(request, "content") is not None:
        new_content = p(request, "content")
        if not isinstance(new_content, str):
            raise ValueError("content 必须是字符串")
        content_changed = new_content != old_content
        obj.content = new_content

    if p(request, "path") is not None:
        new_path = str(p(request, "path")).strip().replace("\\", "/").lstrip("/")
        if ".." in new_path.split("/"):
            raise ValueError("路径不能包含 ..")
        dup = CodeFile.objects.filter(workspace_id=obj.workspace_id, path=new_path).exclude(pk=obj.pk)
        if dup.exists():
            raise ValueError(f"目标路径已存在同名文件: {new_path}")
        obj.path = new_path
        obj.name = new_path.rsplit("/", 1)[-1]
        if not p(request, "language"):
            obj.language = rt.language_from_path(new_path)

    for field in ("language", "is_entry", "is_favorite"):
        if p(request, field) is not None:
            val = p(request, field)
            if field == "language":
                val = rt.normalize_language(val)
            elif field in ("is_entry", "is_favorite"):
                val = opt_bool(request, field)
            setattr(obj, field, val)

    if p(request, "editor_state") is not None:
        st = p(request, "editor_state")
        if isinstance(st, dict):
            obj.editor_state = st

    obj.save()

    # 内容变更 → 落版本快照（第 65 条），并限制单文件版本数
    version_id = None
    if content_changed and opt_bool(request, "snapshot", True):
        v = CodeVersion.objects.create(
            file=obj, content=old_content,
            message=opt_str(request, "message", "自动快照"),
            size=len(old_content.encode("utf-8")),
            created_by=request.user,
        )
        version_id = v.id
        ids = list(obj.versions.values_list("id", flat=True)[:80])
        if len(ids) == 80:
            obj.versions.exclude(id__in=ids).delete()

    data = file_brief(obj)
    data["snapshot_id"] = version_id
    return ok(data)


@endpoint(("DELETE", "POST"))
def file_delete(request, pk):
    obj = get_file(request.user, pk, write=True)
    obj.delete()
    return ok({"deleted": pk})


@endpoint(("POST",))
def file_favorite(request, pk):
    obj = get_file(request.user, pk, write=True)
    obj.is_favorite = not obj.is_favorite
    obj.save(update_fields=["is_favorite", "updated_at"])
    return ok({"is_favorite": obj.is_favorite})


@endpoint(("POST",))
def file_entry(request, pk):
    """把某文件设为工作区唯一入口。"""
    obj = get_file(request.user, pk, write=True)
    CodeFile.objects.filter(workspace_id=obj.workspace_id).update(is_entry=False)
    obj.is_entry = True
    obj.save(update_fields=["is_entry", "updated_at"])
    return ok({"entry": obj.id, "path": obj.path})


@endpoint(("POST",))
def file_move(request, pk):
    """移动文件到新路径（重命名 + 换目录）。"""
    obj = get_file(request.user, pk, write=True)
    new_path = req_str(request, "path", "").strip().replace("\\", "/").lstrip("/")
    if not new_path:
        raise ValueError("目标路径不能为空")
    if ".." in new_path.split("/"):
        raise ValueError("路径不能包含 ..")
    if CodeFile.objects.filter(workspace_id=obj.workspace_id, path=new_path).exclude(pk=obj.pk).exists():
        raise ValueError(f"目标路径已存在: {new_path}")
    obj.path = new_path
    obj.name = new_path.rsplit("/", 1)[-1]
    obj.language = rt.language_from_path(new_path)
    obj.save()
    return ok(file_brief(obj, with_content=False))


@endpoint(("POST",))
def file_batch(request):
    """批量操作：delete / favorite / unfavorite / move。"""
    ids = req_list(request, "ids")
    action = req_str(request, "action", "delete")
    qs = file_write_qs(request.user).filter(id__in=ids)
    n = qs.count()
    if action == "delete":
        qs.delete()
    elif action == "favorite":
        qs.update(is_favorite=True)
    elif action == "unfavorite":
        qs.update(is_favorite=False)
    else:
        raise ValueError(f"不支持的操作: {action}")
    return ok({"affected": n, "action": action})


@endpoint(("GET",))
def file_tree(request):
    """工作区文件树（第 77 条）。"""
    ws = get_ws(request.user, opt_num(request, "workspace", integer=True))
    return ok({"workspace": ws.id, "tree": build_tree(list(ws.files.all()))})


# ============================================================
# 四、版本历史 / diff / 回滚（第 65–67 条）
# ============================================================


@endpoint(("GET",))
def version_list(request, pk):
    obj = get_file(request.user, pk)
    items = []
    for v in obj.versions.all()[:100]:
        items.append({
            "id": v.id,
            "message": v.message,
            "size": v.size,
            "created_at": v.created_at,
            "author": v.created_by.username if v.created_by_id else "",
            "preview": (v.content or "").split("\n")[0][:80],
        })
    return ok({"items": items, "current": obj.content})


@endpoint(("POST",))
def version_create(request, pk):
    obj = get_file(request.user, pk, write=True)
    v = CodeVersion.objects.create(
        file=obj, content=obj.content,
        message=opt_str(request, "message", "手动快照"),
        size=len(obj.content.encode("utf-8")),
        created_by=request.user,
    )
    return ok({"id": v.id, "created_at": v.created_at})


@endpoint(("GET",))
def version_diff(request, pk):
    """两个版本之间的行级 diff（第 66 条）。"""
    obj = get_file(request.user, pk)
    from_id = opt_num(request, "from", integer=True)
    to_id = opt_num(request, "to", integer=True)

    def _content(vid):
        if not vid:
            return None
        v = obj.versions.filter(id=vid).first()
        if not v:
            raise ValueError(f"版本不存在: {vid}")
        return v.content

    if from_id:
        old = _content(from_id)
    else:
        old = opt_str(request, "from_text", "")
    new = _content(to_id) if to_id else obj.content

    hunks = []
    ops = {"add": 0, "del": 0, "keep": 0}
    for line in difflib.unified_diff(
        (old or "").split("\n"), (new or "").split("\n"),
        fromfile="旧版本", tofile="新版本", lineterm="", n=3,
    ):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            hunks.append({"type": "hunk", "text": line})
        elif line.startswith("+"):
            hunks.append({"type": "add", "text": line[1:]})
            ops["add"] += 1
        elif line.startswith("-"):
            hunks.append({"type": "del", "text": line[1:]})
            ops["del"] += 1
        else:
            hunks.append({"type": "keep", "text": line[1:] if line else ""})
            ops["keep"] += 1

    return ok({
        "diff": hunks,
        "stats": ops,
        "old_lines": len((old or "").split("\n")),
        "new_lines": len((new or "").split("\n")),
    })


@endpoint(("POST",))
def version_rollback(request, pk, vid):
    """回滚到指定版本（先给当前内容打快照，避免不可逆）。"""
    obj = get_file(request.user, pk, write=True)
    v = obj.versions.filter(id=vid).first()
    if not v:
        raise ValueError(f"版本不存在: {vid}")
    CodeVersion.objects.create(
        file=obj, content=obj.content,
        message=f"回滚前快照（将回到 v{v.id}）",
        size=len(obj.content.encode("utf-8")),
        created_by=request.user,
    )
    obj.content = v.content
    obj.save()
    return ok(file_brief(obj))


@endpoint(("POST",))
def version_delete(request, pk, vid):
    obj = get_file(request.user, pk, write=True)
    n, _ = obj.versions.filter(id=vid).delete()
    return ok({"deleted": n})


# ============================================================
# 五、运行（第 23–42 条）
# ============================================================


@endpoint(("POST",))
def run(request):
    """执行代码。支持两种入参：
    - {file: <id>, stdin, timeout}          —— 跑工作区里的文件（含同工作区其它文件作为附件）
    - {language, code, stdin, timeout}      —— 直接跑一段代码
    """
    file_id = opt_num(request, "file", integer=True)
    files = None
    source_file = None
    ws = None

    if file_id:
        source_file = get_file(request.user, file_id)
        language = opt_str(request, "language") or source_file.language
        code = p(request, "code")
        code = source_file.content if code is None else str(code)
        ws = source_file.workspace
        # 把同工作区其它文件作为附加文件传入（多文件运行，第 78 条）
        others = ws.files.exclude(pk=source_file.pk)
        files = {f.path: f.content for f in others[:50]}
        entry_path = source_file.path
    else:
        language = req_str(request, "language", "python")
        code = req_str(request, "code", "")
        entry_path = ""
        raw_files = p(request, "files")
        if isinstance(raw_files, dict):
            files = raw_files

    language = rt.normalize_language(language)
    stdin = opt_str(request, "stdin", "")
    timeout = opt_num(request, "timeout", rt.DEFAULT_TIMEOUT, minimum=0.5, maximum=rt.MAX_TIMEOUT)
    args = p(request, "args")
    env = p(request, "env")
    if env is not None and not isinstance(env, dict):
        raise ValueError("env 必须是对象")
    # 安全：禁止任何来自 HTTP 的「危险操作放行」开关。
    # 早期版本读取 request 里的 allow_dangerous，等同于把 RCE 交给调用方；
    # 现由 runtime 的沙箱分层（code/sandbox.py）+ 高危扫描双重把关，
    # 命令行运维如确需放行，只能走本地管理命令，不走 HTTP。
    hits = rt.scan_dangerous(code)
    if hits:
        rec = CodeRun.objects.create(
            owner=request.user, file=source_file, workspace=ws,
            language=language, source_code=code[:20000], stdin=stdin,
            status="rejected", stderr="检测到高危操作，已拒绝执行",
            diagnostics=hits, exit_code=-1,
        )
        return ok({
            "run_id": rec.id, "status": "rejected", "rejected": True,
            "dangerous": hits,
            "stderr": "检测到高危操作，已拒绝执行：\n" + "\n".join(f"  · {h['reason']}" for h in hits),
            "stdout": "", "exit_code": -1, "duration_ms": 0,
        })

    t0 = time.perf_counter()
    result = rt.run_code(
        language, code, stdin=stdin, timeout=timeout, args=args, env=env,
        allow_dangerous=False, files=files,
    )
    elapsed = result.get("duration_ms") or int((time.perf_counter() - t0) * 1000)

    rec = CodeRun.objects.create(
        owner=request.user, file=source_file, workspace=ws,
        language=language,
        source_code=code[:20000],
        stdin=(stdin or "")[:10000],
        stdout=(result.get("stdout") or "")[:50000],
        stderr=(result.get("stderr") or "")[:50000],
        exit_code=result.get("exit_code") or 0,
        signal_name=result.get("signal_name", ""),
        status=_normalize_status(result.get("status")),
        duration_ms=elapsed,
        memory_kb=result.get("memory_kb") or 0,
        truncated=bool(result.get("truncated")),
        diagnostics=result.get("diagnostics") or [],
    )

    payload = dict(result)
    payload["run_id"] = rec.id
    payload["entry_path"] = entry_path
    payload["elapsed_ms"] = elapsed
    return ok(payload)


def _normalize_status(s):
    mapping = {
        "ok": "ok", "error": "error", "timeout": "timeout",
        "memory": "memory", "rejected": "rejected", "unavailable": "unavailable",
        "compile_error": "error",
    }
    return mapping.get(s or "ok", "ok")


@endpoint(("POST",))
def run_repl(request):
    """轻量 REPL（第 35 条）：把历史片段拼成完整程序执行。

    无状态设计——前端维护会话行，后端每次拼装执行；避免进程常驻的复杂度。
    """
    language = rt.normalize_language(req_str(request, "language", "python"))
    chunk = req_str(request, "code", "")
    history = p(request, "history")
    if history is not None and not isinstance(history, list):
        raise ValueError("history 必须是数组")
    history = [str(h) for h in (history or [])][-200:]
    joined = "\n".join(history + [chunk])
    if language == "python":
        # REPL 语义：表达式自动打印结果
        lines = joined.split("\n")
        out_lines = []
        for ln in lines:
            s = ln.strip()
            if s and not s.startswith("#") and not re.match(r"^(def |class |import |from |if |for |while |try|with |@|return|print|#)", s) \
                    and not s.endswith(":") and "=" not in s.split("#")[0][:60] and not s.startswith(" "):
                if re.match(r"^[\w\.\[\]\(\)\+\-\*/%\s'\",]+$", s):
                    out_lines.append(f"print(repr({s}))")
                    continue
            out_lines.append(ln)
        joined = "\n".join(out_lines)
    result = rt.run_code(language, joined, timeout=opt_num(request, "timeout", 5, minimum=0.5, maximum=15))
    result["echo"] = chunk
    return ok(result)


@endpoint(("GET",))
def run_history(request):
    """运行历史（第 33 条）。"""
    qs = CodeRun.objects.filter(owner=request.user)
    file_id = opt_num(request, "file", integer=True)
    if file_id:
        qs = qs.filter(file_id=file_id)
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=lang)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    limit = opt_num(request, "limit", 30, integer=True, minimum=1, maximum=200)
    items = [{
        "id": r.id,
        "language": r.language,
        "status": r.status,
        "exit_code": r.exit_code,
        "duration_ms": r.duration_ms,
        "file": r.file_id,
        "file_path": r.file.path if r.file_id else "",
        "stdout_preview": (r.stdout or "")[:200],
        "stderr_preview": (r.stderr or "")[:200],
        "created_at": r.created_at,
    } for r in qs[:limit]]
    return ok({"items": items})


@endpoint(("GET",))
def run_detail(request, pk):
    r = CodeRun.objects.filter(owner=request.user, id=pk).first()
    if not r:
        raise ValueError(f"运行记录不存在: {pk}")
    return ok({
        "id": r.id, "language": r.language, "status": r.status,
        "source_code": r.source_code, "stdin": r.stdin,
        "stdout": r.stdout, "stderr": r.stderr,
        "exit_code": r.exit_code, "signal_name": r.signal_name,
        "duration_ms": r.duration_ms, "memory_kb": r.memory_kb,
        "truncated": r.truncated, "diagnostics": r.diagnostics,
        "created_at": r.created_at,
    })


@endpoint(("POST",))
def run_delete(request, pk):
    n, _ = CodeRun.objects.filter(owner=request.user, id=pk).delete()
    return ok({"deleted": n})


@endpoint(("POST",))
def run_clear(request):
    """清空运行历史（可指定语言）。"""
    qs = CodeRun.objects.filter(owner=request.user)
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=lang)
    n, _ = qs.delete()
    return ok({"deleted": n})


@endpoint(("GET",))
def run_stats(request):
    """运行统计（第 100 条热力图的数据源）。"""
    qs = CodeRun.objects.filter(owner=request.user)
    total = qs.count()
    by_status = list(qs.values("status").annotate(n=Count("id")).order_by("-n"))
    by_lang = list(qs.values("language").annotate(n=Count("id")).order_by("-n"))
    avg = qs.aggregate(avg=models_avg("duration_ms"))["avg"] or 0

    # 近 365 天每日运行次数（热力图）
    from datetime import timedelta
    today = timezone.localdate()
    start = today - timedelta(days=364)
    rows = (qs.filter(created_at__date__gte=start)
              .extra(select={"d": "date(created_at)"})
              .values("d").annotate(n=Count("id")))
    daily = {str(r["d"]): r["n"] for r in rows}

    # 连续打卡天数
    streak = 0
    cursor = today
    while True:
        key = str(cursor)
        if daily.get(key):
            streak += 1
            cursor -= timedelta(days=1)
        else:
            break

    cells = []
    d = start
    while d <= today:
        cells.append({"date": str(d), "count": daily.get(str(d), 0)})
        d += timedelta(days=1)

    return ok({
        "total": total,
        "by_status": by_status,
        "by_language": by_lang,
        "avg_duration_ms": int(avg),
        "streak_days": streak,
        "heatmap": cells,
        "active_days": sum(1 for c in cells if c["count"] > 0),
    })


def models_avg(field):
    from django.db.models import Avg
    return Avg(field)


# ------------------------------------------------------------
# F676 运行参数预设：按语言保存 stdin / 命令行参数 / 超时
# ------------------------------------------------------------


def _preset_brief(o):
    return {
        "id": o.id, "language": o.language, "name": o.name,
        "stdin": o.stdin, "args": o.args or [], "timeout": o.timeout,
        "is_default": o.is_default,
        "created_at": o.created_at, "updated_at": o.updated_at,
    }


def _clean_args(raw):
    """参数既接受数组也接受空格分隔字符串，统一成字符串数组。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [a for a in raw.split(" ") if a.strip()]
    if not isinstance(raw, list):
        raise ValueError("args 必须是数组或空格分隔的字符串")
    out = [str(a)[:200] for a in raw[:50]]
    return out


@endpoint(("GET", "POST"))
def run_presets(request):
    """运行参数预设：GET 按语言列出，POST 新建。"""
    if request.method == "POST":
        lang = rt.normalize_language(opt_str(request, "language", "python"))
        stdin = opt_str(request, "stdin", "")
        if len(stdin) > 20000:
            raise ValueError("stdin 过长（上限 20000 字符）")
        timeout = opt_num(request, "timeout", 5, minimum=0.5, maximum=30)
        obj = CodeRunPreset.objects.create(
            owner=request.user,
            language=lang,
            name=opt_str(request, "name", "默认预设").strip()[:120] or "默认预设",
            stdin=stdin,
            args=_clean_args(p(request, "args")),
            timeout=timeout,
            is_default=opt_bool(request, "is_default", False),
        )
        if obj.is_default:
            CodeRunPreset.objects.filter(
                owner=request.user, language=lang
            ).exclude(pk=obj.pk).update(is_default=False)
        data = _preset_brief(obj)
        data["is_mine"] = True
        return ok(data)

    qs = CodeRunPreset.objects.filter(owner=request.user)
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=rt.normalize_language(lang))
    limit = opt_num(request, "limit", 100, integer=True, minimum=1, maximum=300)
    return ok({"items": [_preset_brief(o) for o in qs[:limit]]})


@endpoint(("POST", "DELETE"))
def run_preset_detail(request, pk):
    """更新 / 删除一条运行参数预设（仅本人）。"""
    obj = CodeRunPreset.objects.filter(owner=request.user, id=pk).first()
    if not obj:
        raise ValueError(f"运行预设不存在: {pk}")
    if request.method == "DELETE":
        obj.delete()
        return ok({"deleted": pk})

    if p(request, "name") is not None:
        obj.name = str(p(request, "name")).strip()[:120] or obj.name
    if p(request, "language") is not None:
        obj.language = rt.normalize_language(str(p(request, "language")))
    if p(request, "stdin") is not None:
        stdin = str(p(request, "stdin"))
        if len(stdin) > 20000:
            raise ValueError("stdin 过长（上限 20000 字符）")
        obj.stdin = stdin
    if p(request, "args") is not None:
        obj.args = _clean_args(p(request, "args"))
    if p(request, "timeout") is not None:
        obj.timeout = opt_num(request, "timeout", obj.timeout, minimum=0.5, maximum=30)
    if p(request, "is_default") is not None:
        obj.is_default = opt_bool(request, "is_default")
        if obj.is_default:
            CodeRunPreset.objects.filter(
                owner=request.user, language=obj.language
            ).exclude(pk=obj.pk).update(is_default=False)
    obj.save()
    return ok(_preset_brief(obj))


# ============================================================
# 六、判题（第 87–90 条）
# ============================================================


@endpoint(("POST",))
def judge(request):
    """多用例判题：逐个用例执行并比对输出。"""
    language = rt.normalize_language(req_str(request, "language", "python"))
    code = req_str(request, "code", "")
    cases = p(request, "testcases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("testcases 必须是非空数组")
    if len(cases) > 50:
        raise ValueError("单次最多 50 个测试用例")

    # F672 批量启停：enabled === False 的用例判题时跳过（编号仍按原始序号）
    indexed = [
        (i, c) for i, c in enumerate(cases, start=1)
        if isinstance(c, dict) and c.get("enabled") is not False
    ]
    skipped = len(cases) - len(indexed)
    if not indexed:
        raise ValueError("所有测试用例均已停用，请至少启用一条")
    active_cases = [c for _, c in indexed]

    timeout = opt_num(request, "timeout", 5, minimum=0.5, maximum=15)
    ignore_ws = opt_bool(request, "ignore_whitespace", True)

    verdict, passed, results, total_ms = run_judge(
        language, code, active_cases, timeout=timeout, ignore_ws=ignore_ws
    )
    for r in results:
        # results 的 index 是「启用用例内」的序号 → 还原为提交时的原始序号
        pos = r.get("index", 1) - 1
        if 0 <= pos < len(indexed):
            r["index"] = indexed[pos][0]

    task = CodeJudgeTask.objects.create(
        owner=request.user,
        title=opt_str(request, "title", "未命名题目")[:200],
        language=language, source_code=code[:20000],
        testcases=cases[:50], results=results,
        verdict=verdict, passed=passed, total=len(results),
        duration_ms=total_ms,
    )
    return ok({
        "task_id": task.id, "verdict": verdict,
        "passed": passed, "total": len(results),
        "results": results, "duration_ms": total_ms,
        "accepted": verdict == "accepted",
        "skipped": skipped,
        "disabled_cases": skipped,
    })


def run_judge(language, code, cases, timeout=5, ignore_ws=True):
    """判题核心（抽出复用：普通判题 / 每日一题 / 挑战赛）。

    纯函数：只跑代码 + 比对，不落库。返回 (verdict, passed, results, total_ms)。
    """
    results = []
    passed = 0
    total_ms = 0
    verdict = "accepted"

    for idx, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            continue
        stdin = str(case.get("stdin", ""))
        expected = str(case.get("expected", ""))
        r = rt.run_code(language, code, stdin=stdin, timeout=timeout)
        total_ms += r.get("duration_ms") or 0
        actual = r.get("stdout") or ""
        st = r.get("status")

        if st == "unavailable":
            verdict = "unavailable"
            results.append({
                "index": idx, "verdict": "unavailable", "stdin": stdin,
                "expected": expected, "actual": "", "stderr": r.get("stderr", ""),
            })
            continue
        if st == "timeout":
            ok_case, case_verdict = False, "time_limit"
        elif st in ("error", "memory"):
            ok_case, case_verdict = False, ("compile_error" if st == "error" and not actual else "runtime_error")
        else:
            if ignore_ws:
                a_cmp = "\n".join(ln.rstrip() for ln in actual.strip().split("\n"))
                e_cmp = "\n".join(ln.rstrip() for ln in expected.strip().split("\n"))
            else:
                a_cmp, e_cmp = actual.strip(), expected.strip()
            ok_case = a_cmp == e_cmp
            case_verdict = "accepted" if ok_case else "wrong_answer"

        if ok_case:
            passed += 1
        else:
            # 取「最严重」的判定作为总判定
            order = ["accepted", "wrong_answer", "runtime_error", "time_limit", "compile_error", "unavailable"]
            if order.index(case_verdict) > order.index(verdict):
                verdict = case_verdict

        results.append({
            "index": idx,
            "verdict": case_verdict,
            "stdin": stdin[:2000],
            "expected": expected[:4000],
            "actual": actual[:4000],
            "stderr": (r.get("stderr") or "")[:2000],
            "duration_ms": r.get("duration_ms", 0),
            "exit_code": r.get("exit_code", 0),
        })

    return verdict, passed, results, total_ms


@endpoint(("GET",))
def judge_history(request):
    qs = CodeJudgeTask.objects.filter(owner=request.user)
    limit = opt_num(request, "limit", 30, integer=True, minimum=1, maximum=200)
    items = [{
        "id": t.id, "title": t.title, "language": t.language,
        "verdict": t.verdict, "passed": t.passed, "total": t.total,
        "duration_ms": t.duration_ms, "created_at": t.created_at,
    } for t in qs[:limit]]
    return ok({"items": items})


@endpoint(("GET",))
def judge_detail(request, pk):
    t = CodeJudgeTask.objects.filter(owner=request.user, id=pk).first()
    if not t:
        raise ValueError(f"判题记录不存在: {pk}")
    return ok({
        "id": t.id, "title": t.title, "language": t.language,
        "source_code": t.source_code, "testcases": t.testcases,
        "results": t.results, "verdict": t.verdict,
        "passed": t.passed, "total": t.total,
        "duration_ms": t.duration_ms, "created_at": t.created_at,
    })


@endpoint(("GET",))
def leaderboard(request):
    """排行榜（第 90 条）：按判题通过数与运行数综合排。"""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    limit = opt_num(request, "limit", 20, integer=True, minimum=1, maximum=100)

    rows = (CodeJudgeTask.objects.values("owner")
            .annotate(
                solved=Count("id", filter=Q(verdict="accepted")),
                attempts=Count("id"),
                total_passed=Count("id", filter=Q(verdict="accepted")),
            ).order_by("-solved", "-attempts")[:limit])

    names = dict(User.objects.filter(id__in=[r["owner"] for r in rows]).values_list("id", "username"))
    out = []
    for i, r in enumerate(rows, start=1):
        runs = CodeRun.objects.filter(owner_id=r["owner"]).count()
        out.append({
            "rank": i,
            "user": names.get(r["owner"], f"用户{r['owner']}"),
            "solved": r["solved"],
            "attempts": r["attempts"],
            "runs": runs,
            "score": r["solved"] * 10 + r["attempts"],
        })
    return ok({"items": out, "scope": "global"})


# ============================================================
# 七、代码片段库（第 75 条）
# ============================================================


@endpoint(("GET",))
def snippet_list(request):
    from core.scoping import scope_queryset
    qs = scope_queryset(CodeSnippet.objects.all(), request.user, "owner")
    # 团队/公开片段对登录用户可见
    qs = CodeSnippet.objects.filter(
        Q(owner=request.user) | Q(scope="public") | Q(scope="team")
    ).distinct() if True else qs
    q = opt_str(request, "q").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=rt.normalize_language(lang))
    tag = opt_str(request, "tag").strip()
    if tag:
        qs = qs.filter(tags__contains=[tag])
    # F669 收藏夹分组筛选：folder=__none 表示未分组，favorite=1 只看收藏
    folder = opt_str(request, "folder").strip()
    if folder == "__none__":
        qs = qs.filter(folder="")
    elif folder:
        qs = qs.filter(folder=folder)
    if opt_bool(request, "favorite", False):
        qs = qs.filter(is_favorite=True)
    limit = opt_num(request, "limit", 50, integer=True, minimum=1, maximum=200)
    return ok({"items": [_snippet_brief(s) for s in qs[:limit]]})


def _snippet_brief(s):
    return {
        "id": s.id, "title": s.title, "description": s.description,
        "language": s.language, "tags": s.tags or [],
        "scope": s.scope, "owner": s.owner.username if s.owner_id else "",
        "is_mine": s.owner_id == getattr(s, "_viewer_id", None),
        "folder": getattr(s, "folder", "") or "",
        "is_favorite": bool(getattr(s, "is_favorite", False)),
        "copy_count": s.copy_count, "use_count": s.use_count,
        "lines": (s.code or "").count("\n") + 1,
        "code": s.code,
        "created_at": s.created_at, "updated_at": s.updated_at,
    }


@endpoint(("POST",))
def snippet_create(request):
    title = req_str(request, "title", "").strip()
    code = req_str(request, "code", "")
    if not title:
        raise ValueError("标题不能为空")
    lang = opt_str(request, "language", "").strip()
    if not lang:
        # 从代码内容猜
        lang = _guess_lang_from_code(code)
    tags = p(request, "tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    scope = opt_str(request, "scope", "private")
    if scope not in ("private", "team", "public"):
        raise ValueError("scope 只能是 private/team/public")
    s = CodeSnippet.objects.create(
        title=title[:200],
        description=opt_str(request, "description", ""),
        language=rt.normalize_language(lang),
        code=code,
        tags=list(tags)[:20],
        owner=request.user, scope=scope,
        folder=opt_str(request, "folder", "").strip()[:60],
        is_favorite=opt_bool(request, "is_favorite", False),
        source_url=opt_str(request, "source_url", "")[:500],
    )
    data = _snippet_brief(s)
    data["is_mine"] = True
    return ok(data)


def _guess_lang_from_code(code):
    c = code or ""
    if re.search(r"^\s*(?:def |import |from )\w", c, re.M) or "print(" in c and ":" in c:
        return "python"
    if re.search(r"\bconsole\.log\b|\bconst \b|\blet \b|=>", c):
        return "javascript"
    if re.search(r"#include\s*<", c):
        return "cpp" if "std::" in c else "c"
    if re.search(r"\bfunc \w+\(", c) and "package" in c:
        return "go"
    if re.search(r"\bfn \w+\(", c) or "let mut " in c:
        return "rust"
    if re.search(r"\bpublic\s+(?:class|static)\b", c):
        return "java"
    if re.search(r"^\s*<\?php", c):
        return "php"
    if re.search(r"\bSELECT\b.+\bFROM\b", c, re.I):
        return "sql"
    return "plaintext"


@endpoint(("GET",))
def snippet_detail(request, pk):
    s = _get_snippet(request.user, pk)
    data = _snippet_brief(s)
    data["is_mine"] = s.owner_id == request.user.id
    return ok(data)


def _get_snippet(user, pk):
    s = CodeSnippet.objects.filter(id=pk).filter(
        Q(owner=user) | Q(scope="public") | Q(scope="team")
    ).first()
    if not s:
        raise ValueError(f"代码片段不存在或无权访问: {pk}")
    return s


@endpoint(("PATCH", "POST"))
def snippet_update(request, pk):
    s = _get_snippet(request.user, pk)
    if s.owner_id != request.user.id:
        raise ValueError("只能修改自己创建的片段")
    for field in ("title", "description", "code", "source_url", "folder"):
        if p(request, field) is not None:
            val = str(p(request, field))
            setattr(s, field, val[:60] if field == "folder" else val)
    if p(request, "is_favorite") is not None:
        s.is_favorite = opt_bool(request, "is_favorite")
    if p(request, "language") is not None:
        s.language = rt.normalize_language(str(p(request, "language")))
    if p(request, "tags") is not None:
        tags = p(request, "tags")
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        s.tags = list(tags)[:20]
    if p(request, "scope") is not None:
        scope = str(p(request, "scope"))
        if scope not in ("private", "team", "public"):
            raise ValueError("scope 只能是 private/team/public")
        s.scope = scope
    s.save()
    return ok(_snippet_brief(s))


@endpoint(("DELETE", "POST"))
def snippet_delete(request, pk):
    s = _get_snippet(request.user, pk)
    if s.owner_id != request.user.id:
        raise ValueError("只能删除自己创建的片段")
    s.delete()
    return ok({"deleted": pk})


@endpoint(("POST",))
def snippet_copy(request, pk):
    """复制片段到自己的库（或直接计数）。"""
    s = _get_snippet(request.user, pk)
    if opt_bool(request, "into_mine", False):
        new = CodeSnippet.objects.create(
            title=f"{s.title}（副本）", description=s.description,
            language=s.language, code=s.code, tags=s.tags or [],
            owner=request.user, scope="private", source_url=f"snippet:{s.id}",
        )
        CodeSnippet.objects.filter(id=s.id).update(copy_count=s.copy_count + 1)
        return ok(_snippet_brief(new))
    CodeSnippet.objects.filter(id=s.id).update(copy_count=s.copy_count + 1, use_count=s.use_count + 1)
    return ok({"id": s.id, "code": s.code, "copy_count": s.copy_count + 1})


@endpoint(("GET",))
def snippet_tags(request):
    """片段标签聚合。"""
    from collections import Counter
    counter = Counter()
    for s in CodeSnippet.objects.filter(Q(owner=request.user) | Q(scope__in=["public", "team"])):
        for t in (s.tags or []):
            counter[t] += 1
    return ok({"tags": [{"name": k, "count": v} for k, v in counter.most_common(60)]})


@endpoint(("GET",))
def snippet_folders(request):
    """F669 片段收藏夹分组：把收藏的片段归入分组，返回分组列表与计数。

    分组即 `CodeSnippet.folder`；空串视为「未分组」，对外用 key=`__none__` 表示。
    """
    from collections import Counter
    qs = CodeSnippet.objects.filter(owner=request.user)
    counter = Counter()
    fav = 0
    for s in qs.iterator():
        counter[(s.folder or "").strip()] += 1
        if s.is_favorite:
            fav += 1
    items = [
        {"key": name or "__none__", "name": name, "label": name or "未分组", "count": n}
        for name, n in counter.most_common(80)
    ]
    return ok({
        "folders": items,
        "total": qs.count(),
        "favorite_count": fav,
        "foldered_count": sum(n for name, n in counter.items() if name),
    })


@endpoint(("POST",))
def snippet_from_file(request):
    """把某个代码文件存成片段。"""
    f = get_file(request.user, req(request, "file"))
    s = CodeSnippet.objects.create(
        title=opt_str(request, "title", f.name)[:200],
        description=opt_str(request, "description", f"来自 {f.workspace.name}/{f.path}"),
        language=f.language, code=f.content,
        tags=[f.language], owner=request.user,
        source_url=f"file:{f.id}",
    )
    return ok(_snippet_brief(s))


# ============================================================
# 八、导出（第 86 条）
# ============================================================


@endpoint(("POST",))
def export_zip(request):
    """把工作区（或选中文件）打包成 zip 下载。"""
    ws_id = opt_num(request, "workspace", integer=True)
    if not ws_id:
        raise ValueError("缺少 workspace")
    ws = get_ws(request.user, ws_id)
    ids = p(request, "files")
    qs = ws.files.all()
    if isinstance(ids, list) and ids:
        qs = qs.filter(id__in=ids)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in qs:
            zf.writestr(f.path, f.content or "")
        readme = _ws_readme(ws, list(qs))
        zf.writestr("README.md", readme)

    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    from urllib.parse import quote
    fname = quote(f"{ws.name}.zip")
    resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{fname}"
    return resp


def _ws_readme(ws, files):
    lines = [f"# {ws.name}", "", ws.description or "", "",
             f"- 语言：{ws.language}", f"- 文件数：{len(files)}", "",
             "## 文件清单", ""]
    for f in files:
        lines.append(f"- `{f.path}`（{f.lines} 行 / {f.size} 字节）")
    lines += ["", "---", "", "_由「全能协作平台 · 代码工坊」导出_"]
    return "\n".join(lines)


@endpoint(("GET",))
def export_file(request, pk):
    """导出单个文件（带正确扩展名）。"""
    f = get_file(request.user, pk)
    resp = HttpResponse(f.content or "", content_type="text/plain; charset=utf-8")
    from urllib.parse import quote
    resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(f.name)}"
    return resp
