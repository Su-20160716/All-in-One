# -*- coding: utf-8 -*-
"""代码工坊视图（一）：工作区 / 文件 / 版本 / 运行 / 判题 / 片段。

全部接口走 `endpoint` 装饰器（ValueError→400、其余→422，绝不 500）。
"""
import csv
import difflib
import io
import json
import posixpath
import re
import time
import zipfile

from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone

from devtools.common import (
    endpoint, ok, fail, p, req, req_str, opt_str, req_num, opt_num, opt_bool, req_list,
)

from core.pagination import OptionalPageNumberPagination

from . import runtime as rt
from .models import (
    CodeComment, CodeFile, CodeJudgeTask, CodeRun, CodeRunPreset, CodeShare, CodeSnippet,
    CodeTestCaseSet, CodeVersion, CodeWorkspace,
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
    # B6：file_count/total_bytes 原是模型 property（每次访问 1-2 次查询），
    # 列表 200 条就是 400+ 次；annotate 同名属性覆盖 property，整批 1 次聚合
    qs = qs.annotate(file_count=Count("files"), total_bytes=Sum("files__size"))
    # B11：可选分页——不带 page 时仍返回全量（上限 200），items/total 结构不变
    pg = OptionalPageNumberPagination()
    page = pg.paginate_queryset(qs, request)
    if page is not None:
        return ok({
            "items": [ws_brief(o) for o in page],
            "total": pg.page.paginator.count,
            "page": pg.page.number,
        })
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


# ------------------------------------------------------------
# 第 263 条：多文件工作区模板（PyPI 包 / 前后端分离）
# ------------------------------------------------------------

WORKSPACE_TEMPLATES = {
    "python-package": {
        "name": "Python 包",
        "description": "带 src 布局、工具模块、测试与 README 的可发布工程",
        "language": "python",
        "files": [
            {"path": "README.md", "content": (
                "# 我的 Python 包\n\n## 安装\n\n```bash\npip install -e .\n```\n\n"
                "## 使用\n\n```bash\npython -m src.main\n```\n"
            )},
            {"path": "src/__init__.py", "content": '__version__ = "0.1.0"\n'},
            {"path": "src/main.py", "content": (
                "from utils.helpers import greet\n\n\n"
                "def main():\n    print(greet(\"世界\"))\n\n\n"
                "if __name__ == \"__main__\":\n    main()\n"
            )},
            {"path": "utils/helpers.py", "content": (
                "def greet(name: str) -> str:\n    \"\"\"返回问候语。\"\"\"\n"
                "    return f\"你好，{name}！\"\n"
            )},
            {"path": "tests/test_main.py", "content": (
                "import sys\nimport unittest\n\n"
                "sys.path.insert(0, \".\")\n\n"
                "from src.main import main\nfrom utils.helpers import greet\n\n\n"
                "class TestMain(unittest.TestCase):\n"
                "    def test_greet(self):\n"
                "        self.assertIn(\"你好\", greet(\"测试\"))\n\n"
                "    def test_main_runs(self):\n"
                "        main()\n\n\n"
                "if __name__ == \"__main__\":\n    unittest.main()\n"
            )},
        ],
    },
    "web-api": {
        "name": "Web API 服务",
        "description": "main 入口 + 工具模块 + README + 接口测试的轻量后端骨架",
        "language": "python",
        "files": [
            {"path": "README.md", "content": (
                "# Web API\n\n## 启动\n\n```bash\npython main.py\n```\n\n"
                "## 接口\n\n- `GET /health`：健康检查\n- `GET /items`：示例列表\n"
            )},
            {"path": "main.py", "content": (
                "import json\n\nfrom utils import resolve_path\n\n\n"
                "def app(environ, start_response):\n"
                "    path = resolve_path(environ.get(\"PATH_INFO\", \"/\"))\n"
                "    if path == \"/health\":\n"
                "        body = {\"status\": \"ok\"}\n"
                "    else:\n"
                "        body = {\"items\": [1, 2, 3]}\n"
                "    data = json.dumps(body, ensure_ascii=False).encode(\"utf-8\")\n"
                "    start_response(\"200 OK\", [(\"Content-Type\", \"application/json\")])\n"
                "    return [data]\n\n\n"
                "if __name__ == \"__main__\":\n"
                "    print(json.dumps({\"route\": \"/health\", \"status\": \"ok\"}, ensure_ascii=False))\n"
            )},
            {"path": "utils/__init__.py", "content": "from .resolve import resolve_path\n"},
            {"path": "utils/resolve.py", "content": (
                "def resolve_path(raw: str) -> str:\n"
                "    \"\"\"归一化请求路径：去掉查询串与结尾斜杠。\"\"\"\n"
                "    path = (raw or \"/\").split(\"?\")[0]\n"
                "    return path.rstrip(\"/\") or \"/\"\n"
            )},
            {"path": "tests/test_api.py", "content": (
                "import unittest\n\nfrom utils import resolve_path\n\n\n"
                "class TestResolve(unittest.TestCase):\n"
                "    def test_strip_slash(self):\n"
                "        self.assertEqual(resolve_path(\"/health/\"), \"/health\")\n\n"
                "    def test_query(self):\n"
                "        self.assertEqual(resolve_path(\"/items?x=1\"), \"/items\")\n\n\n"
                "if __name__ == \"__main__\":\n    unittest.main()\n"
            )},
        ],
    },
}


def _template_brief(key, spec):
    return {
        "key": key, "name": spec["name"], "description": spec["description"],
        "language": spec["language"],
        "file_count": len(spec["files"]),
        "files": [f["path"] for f in spec["files"]],
    }


@endpoint(("GET",))
def workspace_templates(request):
    """工作区模板清单（第 263 条）。"""
    return ok({
        "items": [_template_brief(k, v) for k, v in WORKSPACE_TEMPLATES.items()],
        "count": len(WORKSPACE_TEMPLATES),
    })


@endpoint(("POST",))
def workspace_from_template(request):
    """按模板批量创建目录与文件（第 263 条）。"""
    key = req_str(request, "template", "").strip()
    spec = WORKSPACE_TEMPLATES.get(key)
    if not spec:
        raise ValueError(f"模板不存在: {key}")
    name = req_str(request, "name", "").strip() or spec["name"]
    ws = CodeWorkspace.objects.create(
        name=name[:120],
        description=opt_str(request, "description", spec["description"]),
        owner=request.user,
        language=rt.normalize_language(opt_str(request, "language", spec["language"])),
        icon=opt_str(request, "icon", "📁")[:16] or "📁",
        color=opt_str(request, "color", "brand")[:16],
    )
    # 同一路径可能在模板里重复出现（如 utils/__init__.py），后者覆盖前者
    merged = {}
    for f in spec["files"]:
        merged[f["path"]] = f.get("content", "")
    created = []
    for path, content in merged.items():
        lang = rt.language_from_path(path)
        obj = CodeFile.objects.create(
            workspace=ws, owner=request.user, path=path,
            name=path.rsplit("/", 1)[-1], language=lang, content=content,
            is_entry=path in ("main.py", "src/main.py"),
        )
        created.append({"id": obj.id, "path": obj.path, "lines": obj.lines, "language": lang})
    if not any(c["path"] in ("main.py", "src/main.py") for c in created) and created:
        CodeFile.objects.filter(id=created[0]["id"]).update(is_entry=True)
    data = ws_detail(ws, include_files=True)
    data["template"] = key
    data["created"] = created
    return ok(data)


# 导入限制（第 266 条）：防路径穿越与 zip 炸弹
IMPORT_MAX_FILES = 200
IMPORT_MAX_BYTES = 20 * 1024 * 1024
IMPORT_SKIP_DIRS = {"__MACOSX", ".git", "node_modules", "__pycache__", ".idea", ".vscode"}


@endpoint(("POST",))
def workspace_import(request):
    """导入 zip 为工作区文件（第 266 条，multipart 字段名 file）。"""
    upload = request.FILES.get("file")
    if not upload:
        raise ValueError("缺少 zip 文件（multipart 字段名 file）")
    if upload.size > IMPORT_MAX_BYTES:
        raise ValueError(f"zip 文件超过 {IMPORT_MAX_BYTES // (1024 * 1024)}MB 上限")
    try:
        zf = zipfile.ZipFile(upload)
    except zipfile.BadZipFile:
        raise ValueError("不是有效的 zip 文件")

    ws_id = opt_num(request, "workspace", None, integer=True)
    if ws_id:
        ws = get_ws(request.user, ws_id, write=True)
    else:
        name = opt_str(request, "name", "").strip() or (upload.name or "导入工程").rsplit(".", 1)[0]
        ws = CodeWorkspace.objects.create(
            name=name[:120], owner=request.user,
            description=opt_str(request, "description", f"由 {upload.name} 导入"),
        )

    entries, total, unsafe = [], 0, []
    for info in zf.infolist():
        if info.is_dir():
            continue
        raw = (info.filename or "").replace("\\", "/")
        parts = [seg for seg in raw.split("/") if seg not in ("", ".")]
        if not parts or raw.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", raw):
            unsafe.append(info.filename)
            continue
        if any(seg in IMPORT_SKIP_DIRS for seg in parts[:-1]):
            continue
        if parts[-1].startswith("."):
            continue
        total += max(0, info.file_size)
        if len(entries) + 1 > IMPORT_MAX_FILES:
            raise ValueError(f"压缩包文件数超过 {IMPORT_MAX_FILES} 上限")
        if total > IMPORT_MAX_BYTES:
            raise ValueError(f"解压后体积超过 {IMPORT_MAX_BYTES // (1024 * 1024)}MB 上限")
        entries.append((info, "/".join(parts)))
    if unsafe:
        raise ValueError(f"压缩包包含非法路径（疑似路径穿越）：{unsafe[0]}")
    if not entries:
        raise ValueError("压缩包内没有可导入的文件")

    # 所有文件同处一个顶层目录时自动剥掉，避免多出一层嵌套
    prefixes = {p.split("/")[0] for _, p in entries if "/" in p}
    if len(prefixes) == 1 and all("/" in p for _, p in entries):
        prefix = prefixes.pop() + "/"
        entries = [(i, p[len(prefix):]) for i, p in entries]

    existing = set(ws.files.values_list("path", flat=True))
    created, skipped, truncated = [], 0, []
    for info, path in entries:
        if path in existing:
            skipped += 1
            continue
        try:
            raw = zf.read(info)
        except (zipfile.BadZipFile, RuntimeError):
            skipped += 1
            continue
        if len(raw) > 2 * 1024 * 1024:
            truncated.append(path)
            raw = raw[:2 * 1024 * 1024]
        content = raw.decode("utf-8", "replace")
        obj = CodeFile.objects.create(
            workspace=ws, owner=request.user, path=path,
            name=path.rsplit("/", 1)[-1], language=rt.language_from_path(path),
            content=content,
        )
        existing.add(path)
        created.append({"id": obj.id, "path": obj.path, "language": obj.language, "lines": obj.lines})
    if not ws.files.filter(is_entry=True).exists() and created:
        CodeFile.objects.filter(id=created[0]["id"]).update(is_entry=True)

    data = ws_detail(ws, include_files=True)
    data["imported"] = len(created)
    data["skipped"] = skipped
    data["truncated"] = truncated[:20]
    data["created"] = created
    return ok(data)



@endpoint(("POST",))
def workspace_replace(request, pk):
    """工作区全局搜索替换（第 264 条）：逐文件命中行 + 预览，确认后写回并快照。"""
    ws = get_ws(request.user, pk, write=True)
    q = req_str(request, "q", "", max_len=500)
    if not q:
        raise ValueError("搜索内容不能为空")
    replace = opt_str(request, "replace", "", max_len=5000)
    use_regex = opt_bool(request, "regex", False)
    dry_run = opt_bool(request, "dry_run", True)

    if use_regex:
        try:
            pattern = re.compile(q, re.MULTILINE)
        except re.error as e:
            raise ValueError(f"正则表达式非法：{e}")
    else:
        pattern = re.compile(re.escape(q), re.MULTILINE)
    # 替换串统一走函数，避免 \1 / \g 之类被 re.sub 当成分组引用
    substitute = lambda _m: replace  # noqa: E731

    files = ws.files.all()
    ids = p(request, "file_ids")
    if isinstance(ids, list) and ids:
        clean = [int(i) for i in ids[:200] if str(i).isdigit()]
        if not clean:
            raise ValueError("file_ids 必须是文件 ID 数组")
        files = files.filter(id__in=clean)

    results, total_hits, changed = [], 0, 0
    for f in files[:200]:
        content = f.content or ""
        if not content or not pattern.search(content):
            continue
        hits, lines = 0, []
        for no, line in enumerate(content.split("\n"), start=1):
            found = pattern.findall(line)
            if not found:
                continue
            hits += len(found)
            lines.append({
                "line": no,
                "before": line[:400],
                "after": pattern.sub(substitute, line)[:400],
                "count": len(found),
            })
        if not hits:
            continue
        new_content = pattern.sub(substitute, content)
        row = {
            "file": f.id, "path": f.path, "hits": hits,
            "lines": lines[:200], "line_count": len(lines),
            "changed": new_content != content,
        }
        total_hits += hits
        if not dry_run and new_content != content:
            CodeVersion.objects.create(
                file=f, content=content, message=f"替换前快照：{q[:40]}",
                size=len(content.encode("utf-8")), created_by=request.user,
            )
            f.content = new_content
            f.save()
            changed += 1
        results.append(row)

    return ok({
        "workspace": ws.id, "q": q, "replace": replace,
        "regex": use_regex, "dry_run": dry_run,
        "results": results, "file_count": len(results),
        "total_hits": total_hits, "changed_files": changed,
    })


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
    elif action == "move":
        # 第 262 条：批量移动到目标目录（空字符串 = 根目录）
        target = opt_str(request, "target", "", max_len=400).strip().replace("\\", "/").strip("/")
        if ".." in target.split("/"):
            raise ValueError("目标目录不能包含 ..")
        files = list(qs)
        if not files:
            raise ValueError("没有可移动的文件")
        ws_ids = {f.workspace_id for f in files}
        if len(ws_ids) > 1:
            raise ValueError("不支持跨工作区批量移动")
        ws_id = ws_ids.pop()
        moving_ids = [f.id for f in files]
        taken = set(
            CodeFile.objects.filter(workspace_id=ws_id).exclude(id__in=moving_ids)
            .values_list("path", flat=True)
        )
        plans, conflicts = [], []
        for f in files:
            name = f.name or f.path.rsplit("/", 1)[-1]
            new_path = f"{target}/{name}" if target else name
            if new_path in taken or any(p == new_path for p, _ in plans):
                conflicts.append(new_path)
                continue
            plans.append((new_path, f))
        if conflicts:
            raise ValueError("目标目录已存在同名文件：" + "、".join(conflicts[:10]))
        for new_path, f in plans:
            f.path = new_path
            f.name = new_path.rsplit("/", 1)[-1]
            f.language = rt.language_from_path(new_path)
            f.save()
        return ok({
            "affected": len(plans), "action": action, "target": target,
            "files": [file_brief(f, with_content=False) for _, f in plans],
        })
    else:
        raise ValueError(f"不支持的操作: {action}")
    return ok({"affected": n, "action": action})


@endpoint(("POST",))
def file_copy(request, pk):
    """同工作区复制文件为「name(副本).ext」（第 276 条）。"""
    obj = get_file(request.user, pk, write=True)
    directory = opt_str(request, "dir", "", max_len=400).strip().replace("\\", "/").strip("/")
    if ".." in directory.split("/"):
        raise ValueError("目标目录不能包含 ..")
    if not directory:
        directory = obj.path.rsplit("/", 1)[0] if "/" in obj.path else ""

    base = obj.name or obj.path.rsplit("/", 1)[-1]
    stem, dot, ext = base.rpartition(".")
    if not dot or not stem:
        stem, ext = base, ""
    suffix = f".{ext}" if ext else ""

    def _join(name):
        return f"{directory}/{name}" if directory else name

    new_name = f"{stem}(副本){suffix}"
    seq = 2
    while CodeFile.objects.filter(workspace_id=obj.workspace_id, path=_join(new_name)).exists():
        new_name = f"{stem}(副本{seq}){suffix}"
        seq += 1
        if seq > 200:
            raise ValueError("副本数量过多，请先清理同名文件")
    new = CodeFile.objects.create(
        workspace=obj.workspace, owner=request.user, path=_join(new_name),
        name=new_name, language=obj.language, content=obj.content,
        is_entry=False, order=obj.order,
    )
    return ok(file_brief(new))


# ------------------------------------------------------------
# 第 271/272 条：工作区内的 import / 相对路径引用扫描
# ------------------------------------------------------------

_PY_IMPORT_RE = re.compile(r"^[ \t]*(?:from[ \t]+([.\w]+)[ \t]+import|import[ \t]+([\w.,\t ]+))", re.M)
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s[^'"]*?from\s*|require\s*\(\s*|import\s*\(\s*)['"]([^'"]+)['"]""", re.M
)
_C_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
_PATH_REF_RE = re.compile(r"""['"]((?:\.{1,2}/)+[^'"\n]{1,120})['"]""")
_WEB_EXTS = (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs")


def _scan_refs(path, content, language):
    """扫描单个文件的引用：返回 [(原始引用, 类型)]，类型 import / relative。"""
    refs = []
    text = content or ""
    if language == "python":
        for m in _PY_IMPORT_RE.finditer(text):
            if m.group(1):
                refs.append((m.group(1), "import"))
            else:
                for part in (m.group(2) or "").split(","):
                    name = part.strip().split(" as ")[0].strip()
                    if name:
                        refs.append((name, "import"))
    elif language in ("javascript", "typescript"):
        refs.extend((m.group(1), "import") for m in _JS_IMPORT_RE.finditer(text))
    elif language in ("c", "cpp"):
        refs.extend((m.group(1), "import") for m in _C_INCLUDE_RE.finditer(text))
    # 通用：字符串里的相对路径（open("./data.txt") / fetch('../x.json')）
    refs.extend((m.group(1), "relative") for m in _PATH_REF_RE.finditer(text))
    seen, out = set(), []
    for raw, kind in refs:
        key = (raw, kind)
        if key in seen:
            continue
        seen.add(key)
        out.append((raw, kind))
    return out[:80]


def _resolve_ref(raw, kind, src_path, path_set):
    """把引用解析成工作区内的文件路径；解析不到返回 None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    base_dir = posixpath.dirname(src_path)

    def _norm(p):
        return posixpath.normpath(p).lstrip("/")

    def _exists(p):
        return p if p in path_set else None

    def _try(dirs, rel):
        for d in dirs:
            cand = _norm(posixpath.join(d, rel) if d else rel)
            hit = _exists(cand)
            if hit:
                return hit
            for ext in (".py", *_WEB_EXTS, ".h", ".hpp", ".c", ".cpp", ".json", ".txt", ".md"):
                hit = _exists(cand + ext)
                if hit:
                    return hit
            for idx in ("index.js", "index.ts", "__init__.py", "mod.rs", "main.py"):
                hit = _exists(posixpath.join(cand, idx))
                if hit:
                    return hit
        return None

    # Python 相对导入：.helpers / ..pkg.mod（不含斜杠，与 JS 的 ./x 区分）
    if kind == "import" and "/" not in raw and re.match(r"^\.+\w*$", raw):
        dots = len(raw) - len(raw.lstrip("."))
        rest = raw.lstrip(".").replace(".", "/")
        base = base_dir
        for _ in range(max(0, dots - 1)):
            base = base.rsplit("/", 1)[0] if "/" in base else ""
        if rest:
            return _try([base], rest)
        return _try([base], "__init__.py") or _try([base], "main.py") or _try([""], "__init__.py")

    if kind == "relative" or raw.startswith(("./", "../")):
        hit = _try([base_dir, ""], raw)
        if hit or raw.startswith("."):
            return hit

    if kind == "import":
        mod = raw.replace(".", "/")
        return _try([base_dir, ""], mod)
    return None


def _workspace_graph(ws):
    """构建工作区引用图：节点、边、未解析引用。"""
    files = list(ws.files.all())
    path_set = {f.path for f in files}
    by_path = {f.path: f for f in files}
    nodes = {f.id: {
        "id": f.id, "path": f.path, "name": f.name, "language": f.language,
        "is_entry": f.is_entry, "lines": f.lines, "in": 0, "out": 0,
    } for f in files}
    edges, unresolved = [], []
    for f in files:
        for raw, kind in _scan_refs(f.path, f.content, f.language):
            target = _resolve_ref(raw, kind, f.path, path_set)
            if not target:
                unresolved.append({
                    "file": f.id, "path": f.path, "ref": raw, "kind": kind,
                    "reason": "外部依赖或文件不存在",
                })
                continue
            tf = by_path[target]
            if tf.id == f.id:
                continue
            edges.append({
                "from": f.id, "to": tf.id, "from_path": f.path,
                "to_path": tf.path, "kind": kind, "raw": raw,
            })
            nodes[f.id]["out"] += 1
            nodes[tf.id]["in"] += 1
    return nodes, edges, unresolved


@endpoint(("GET",))
def dependency_graph(request):
    """工作区依赖图（第 271 条）：节点 / 边 / 未解析引用。"""
    ws = get_ws(request.user, opt_num(request, "workspace", integer=True))
    nodes, edges, unresolved = _workspace_graph(ws)
    node_list = sorted(nodes.values(), key=lambda n: (n["path"]))
    isolated = [n["path"] for n in node_list if not n["in"] and not n["out"] and not n["is_entry"]]
    return ok({
        "workspace": ws.id, "workspace_name": ws.name,
        "nodes": node_list, "edges": edges[:2000],
        "unresolved": unresolved[:200],
        "stats": {
            "files": len(node_list), "edges": len(edges),
            "unresolved": len(unresolved), "isolated": len(isolated),
        },
        "isolated": isolated[:100],
    })


@endpoint(("GET",))
def files_orphans(request):
    """未被引用文件（第 272 条）：从入口文件遍历引用，返回可达之外的孤儿文件。"""
    ws = get_ws(request.user, opt_num(request, "workspace", integer=True))
    nodes, edges, _unresolved = _workspace_graph(ws)
    files = {f.id: f for f in ws.files.all()}

    ref_count = {}
    for e in edges:
        ref_count[e["to"]] = ref_count.get(e["to"], 0) + 1
    outgoing = {}
    for e in edges:
        outgoing.setdefault(e["from"], set()).add(e["to"])

    entries = [n["id"] for n in nodes.values() if n["is_entry"]]
    if not entries:
        # 没有显式入口：退化为 main.* / index.* / app.* / __init__.*
        for n in nodes.values():
            low = n["name"].lower()
            if low.startswith(("main.", "index.", "app.", "__init__.")):
                entries.append(n["id"])
    if not entries and nodes:
        entries = [min(nodes.values(), key=lambda n: n["path"].count("/"))["id"]]

    reachable, queue = set(entries), list(entries)
    while queue:
        cur = queue.pop()
        for nxt in outgoing.get(cur, ()):
            if nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)

    items = []
    for fid, n in nodes.items():
        if fid in reachable:
            continue
        f = files.get(fid)
        items.append({
            "id": fid, "path": n["path"], "name": n["name"], "language": n["language"],
            "lines": n["lines"], "size": f.size if f else 0,
            "refs": ref_count.get(fid, 0), "is_entry": n["is_entry"],
            "updated_at": f.updated_at if f else None,
        })
    items.sort(key=lambda x: (x["refs"], x["path"]))
    return ok({
        "workspace": ws.id, "workspace_name": ws.name,
        "entries": [{"id": fid, "path": nodes[fid]["path"]} for fid in entries if fid in nodes],
        "items": items, "total": len(items), "scanned": len(nodes),
    })



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
def run_export(request):
    """运行历史导出 CSV（第 274 条），流式输出避免大结果集占内存。"""
    qs = CodeRun.objects.filter(owner=request.user)
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=rt.normalize_language(lang))
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    limit = opt_num(request, "limit", 5000, integer=True, minimum=1, maximum=20000)
    ids = list(qs.order_by("-created_at").values_list("id", flat=True)[:limit])
    rows = qs.filter(id__in=ids).order_by("-created_at")

    def _gen():
        buf = io.StringIO()
        writer = csv.writer(buf)

        def _flush():
            val = buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
            return val

        writer.writerow(["时间", "语言", "状态", "耗时(ms)", "内存(KB)", "退出码", "代码摘要"])
        yield "\ufeff" + _flush()
        for r in rows.iterator(chunk_size=500):
            summary = " ".join((r.source_code or "").split())[:120]
            writer.writerow([
                timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                r.language, r.status, r.duration_ms, r.memory_kb, r.exit_code, summary,
            ])
            yield _flush()

    resp = StreamingHttpResponse(_gen(), content_type="text/csv; charset=utf-8")
    from urllib.parse import quote
    fname = quote(f"运行历史_{timezone.localdate()}.csv")
    resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{fname}"
    return resp


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


@endpoint(("GET",))
def run_presets_export(request):
    """运行预设导出（第 279 条）：JSON，便于换设备/分享给同事。"""
    qs = CodeRunPreset.objects.filter(owner=request.user)
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=rt.normalize_language(lang))
    items = [{
        "language": o.language, "name": o.name, "stdin": o.stdin,
        "args": o.args or [], "timeout": o.timeout, "is_default": o.is_default,
    } for o in qs[:300]]
    return ok({"items": items, "count": len(items), "exported_at": timezone.now()})


@endpoint(("POST",))
def run_presets_import(request):
    """运行预设导入（第 279 条）：按「语言 + 名称」去重。"""
    items = p(request, "items")
    if not isinstance(items, list) or not items:
        raise ValueError("items 必须是非空数组")
    if len(items) > 300:
        raise ValueError("单次最多导入 300 条预设")
    existing = {(lang, name) for lang, name in
                CodeRunPreset.objects.filter(owner=request.user).values_list("language", "name")}
    created, skipped = [], 0
    for it in items:
        if not isinstance(it, dict):
            continue
        lang = rt.normalize_language(str(it.get("language") or "python"))
        name = str(it.get("name") or "导入预设").strip()[:120] or "默认预设"
        if (lang, name) in existing:
            skipped += 1
            continue
        existing.add((lang, name))
        stdin = str(it.get("stdin") or "")[:20000]
        try:
            timeout = float(it.get("timeout") or 5)
        except (TypeError, ValueError):
            timeout = 5.0
        obj = CodeRunPreset.objects.create(
            owner=request.user, language=lang, name=name, stdin=stdin,
            args=_clean_args(it.get("args")),
            timeout=min(30.0, max(0.5, timeout)),
            is_default=bool(it.get("is_default")),
        )
        created.append(_preset_brief(obj))
    return ok({"created": len(created), "skipped": skipped, "items": created})


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
    """多用例判题：逐个用例执行并比对输出。

    第 275 条：可选 set_id 叠加已保存的用例集。
    """
    language = rt.normalize_language(req_str(request, "language", "python"))
    code = req_str(request, "code", "")
    cases = p(request, "testcases")
    set_id = opt_num(request, "set_id", None, integer=True)
    merged = []
    if set_id:
        case_set = CodeTestCaseSet.objects.filter(id=set_id, owner=request.user).first()
        if not case_set:
            raise ValueError(f"用例集不存在或无权访问: {set_id}")
        merged.extend(c for c in (case_set.cases or []) if isinstance(c, dict))
    if isinstance(cases, list) and cases:
        merged.extend(cases)
    if not merged:
        raise ValueError("testcases 必须是非空数组")
    if len(merged) > 50:
        raise ValueError("单次最多 50 个测试用例")
    cases = merged

    # F672 批量启停：enabled === False 的用例判题时跳过（编号仍按原始序号）
    indexed = [
        (i, c) for i, c in enumerate(cases, start=1)
        if isinstance(c, dict) and c.get("enabled") is not False
    ]
    skipped = len(cases) - len(indexed)
    if not indexed:
        raise ValueError("所有测试用例均已停用，请至少启用一条")
    active_cases = [c for _, c in indexed]

    timeout = opt_num(request, "timeout", 5, minimum=0.5, maximum=5)
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
        "set_id": set_id,
    })


# ------------------------------------------------------------
# 第 275 条：判题用例集（保存 / 载入复用）
# ------------------------------------------------------------


def _case_set_brief(o):
    return {
        "id": o.id, "title": o.title, "language": o.language,
        "cases": o.cases or [], "case_count": len(o.cases or []),
        "created_at": o.created_at, "updated_at": o.updated_at,
    }


def _clean_cases(raw, limit=50):
    if not isinstance(raw, list) or not raw:
        raise ValueError("cases 必须是非空数组")
    out = []
    for c in raw[:limit]:
        if not isinstance(c, dict):
            continue
        row = {"stdin": str(c.get("stdin") or "")[:4000], "expected": str(c.get("expected") or "")[:8000]}
        if c.get("enabled") is False:
            row["enabled"] = False
        out.append(row)
    if not out:
        raise ValueError("cases 至少要有一条有效用例")
    return out


@endpoint(("GET", "POST"))
def judge_case_sets(request):
    """用例集列表 / 新建（第 275 条，仅本人）。"""
    if request.method == "POST":
        obj = CodeTestCaseSet.objects.create(
            owner=request.user,
            title=req_str(request, "title", "未命名用例集").strip()[:200] or "未命名用例集",
            language=rt.normalize_language(opt_str(request, "language", "python")),
            cases=_clean_cases(p(request, "cases")),
        )
        return ok(_case_set_brief(obj))

    qs = CodeTestCaseSet.objects.filter(owner=request.user)
    lang = opt_str(request, "language").strip()
    if lang:
        qs = qs.filter(language=rt.normalize_language(lang))
    limit = opt_num(request, "limit", 100, integer=True, minimum=1, maximum=300)
    return ok({"items": [_case_set_brief(o) for o in qs[:limit]]})


@endpoint(("POST", "DELETE"))
def judge_case_set_detail(request, pk):
    """更新 / 删除用例集（仅本人）。"""
    obj = CodeTestCaseSet.objects.filter(id=pk, owner=request.user).first()
    if not obj:
        raise ValueError(f"用例集不存在或无权访问: {pk}")
    if request.method == "DELETE":
        obj.delete()
        return ok({"deleted": pk})
    if p(request, "title") is not None:
        obj.title = str(p(request, "title")).strip()[:200] or obj.title
    if p(request, "language") is not None:
        obj.language = rt.normalize_language(str(p(request, "language")))
    if p(request, "cases") is not None:
        obj.cases = _clean_cases(p(request, "cases"))
    obj.save()
    return ok(_case_set_brief(obj))


_VERDICT_ORDER = ["accepted", "wrong_answer", "runtime_error", "time_limit", "compile_error", "unavailable"]


def run_judge(language, code, cases, timeout=5, ignore_ws=True, total_budget=20.0):
    """判题核心（抽出复用：普通判题 / 每日一题 / 挑战赛）。

    纯函数：只跑代码 + 比对，不落库。返回 (verdict, passed, results, total_ms)。
    单用例超时上限 5s，整批总预算 20s，超出后剩余用例标记为超时不再执行。
    """
    results = []
    passed = 0
    total_ms = 0
    verdict = "accepted"
    case_timeout = min(float(timeout), 5.0)
    deadline = time.monotonic() + max(1.0, float(total_budget))

    for idx, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            continue
        stdin = str(case.get("stdin", ""))
        expected = str(case.get("expected", ""))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results.append({
                "index": idx, "verdict": "time_limit",
                "stdin": stdin[:2000], "expected": expected[:4000],
                "actual": "", "stderr": "判题总时长超出预算，剩余用例未执行",
                "duration_ms": 0, "exit_code": None,
            })
            if _VERDICT_ORDER.index("time_limit") > _VERDICT_ORDER.index(verdict):
                verdict = "time_limit"
            continue
        r = rt.run_code(language, code, stdin=stdin, timeout=min(case_timeout, remaining))
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
            if _VERDICT_ORDER.index(case_verdict) > _VERDICT_ORDER.index(verdict):
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
    # 第 280 条：sort=popular 按「引用数 + 复制数」倒序，同分再按更新时间
    sort = opt_str(request, "sort", "").strip().lower()
    if sort == "popular":
        qs = qs.annotate(popularity=F("use_count") + F("copy_count")).order_by("-popularity", "-updated_at")
    elif sort == "created":
        qs = qs.order_by("-created_at")
    elif sort == "title":
        qs = qs.order_by("title")
    limit = opt_num(request, "limit", 50, integer=True, minimum=1, maximum=200)
    items = []
    for s in qs[:limit]:
        s._viewer_id = request.user.id
        items.append(_snippet_brief(s))
    return ok({"items": items, "sort": sort or "updated"})


# 第 268 条：片段占位符 ${name}
SNIPPET_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]{0,39})\}")


def snippet_variables(code):
    """解析 ${name} 占位符（按出现顺序去重，最多 30 个）。"""
    out = []
    for m in SNIPPET_VAR_RE.finditer(code or ""):
        name = m.group(1)
        if name not in out:
            out.append(name)
        if len(out) >= 30:
            break
    return out


def _snippet_brief(s):
    variables = snippet_variables(s.code)
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
        "variables": variables, "variable_count": len(variables),
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
        data = _snippet_brief(new)
        data["is_mine"] = True
        return ok(data)
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


@endpoint(("GET",))
def snippet_export(request):
    """片段库导出 JSON（第 267 条）：便于备份与跨账号迁移。"""
    qs = CodeSnippet.objects.filter(owner=request.user).order_by("-updated_at")
    items = [{
        "title": s.title, "description": s.description, "language": s.language,
        "code": s.code, "tags": s.tags or [], "folder": s.folder or "",
    } for s in qs[:1000]]
    return ok({
        "items": items, "count": len(items),
        "exported_at": timezone.now(), "version": 1,
    })


@endpoint(("POST",))
def snippet_import(request):
    """片段库导入 JSON（第 267 条）：按「标题 + 语言」去重。"""
    items = p(request, "items")
    if not isinstance(items, list) or not items:
        raise ValueError("items 必须是非空数组")
    if len(items) > 1000:
        raise ValueError("单次最多导入 1000 条片段")
    existing = {(t, l) for t, l in
                CodeSnippet.objects.filter(owner=request.user).values_list("title", "language")}
    created, skipped = [], 0
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()[:200]
        code = str(it.get("code") or "")
        if not title or not code.strip():
            skipped += 1
            continue
        raw_lang = str(it.get("language") or "").strip()
        lang = rt.normalize_language(raw_lang) if raw_lang else _guess_lang_from_code(code)
        if (title, lang) in existing:
            skipped += 1
            continue
        existing.add((title, lang))
        tags = it.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        s = CodeSnippet.objects.create(
            title=title, description=str(it.get("description") or ""),
            language=lang, code=code, tags=list(tags)[:20],
            folder=str(it.get("folder") or "").strip()[:60],
            owner=request.user, scope="private", source_url="import:json",
        )
        created.append(_snippet_brief(s))
    return ok({"created": len(created), "skipped": skipped, "items": created})


def _safe_filename(raw, ext):
    """把标题清洗成可用的文件名（保留中文，去掉路径分隔与非法字符）。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (raw or "").strip()).strip("._ ") or "snippet"
    if not name.lower().endswith(ext.lower()):
        name += ext
    return name[:120]


@endpoint(("POST",))
def snippet_to_file(request, pk):
    """片段生成代码文件（第 265 条）：按片段语言建 CodeFile 并记快照。"""
    s = _get_snippet(request.user, pk)
    ws = get_ws(request.user, req(request, "workspace"), write=True)
    ext = rt.language_meta(s.language).get("ext", ".txt")
    path = opt_str(request, "path", "", max_len=400).strip().replace("\\", "/").lstrip("/")
    if not path:
        path = _safe_filename(s.title, ext)
    if ".." in path.split("/") or path.endswith("/"):
        raise ValueError("文件路径不合法")
    if CodeFile.objects.filter(workspace=ws, path=path).exists():
        raise ValueError(f"目标路径已存在文件: {path}")
    obj = CodeFile.objects.create(
        workspace=ws, owner=request.user, path=path,
        name=path.rsplit("/", 1)[-1], language=s.language, content=s.code,
        is_entry=not ws.files.exists(),
    )
    # 操作记录：新文件落一条初始快照，溯源到片段
    CodeVersion.objects.create(
        file=obj, content=obj.content, message=f"由片段「{s.title}」生成",
        size=len(obj.content.encode("utf-8")), created_by=request.user,
    )
    CodeSnippet.objects.filter(id=s.id).update(use_count=F("use_count") + 1)
    return ok({"file": file_brief(obj), "snippet": s.id, "path": obj.path})


# ============================================================
# 第 273 条：本地代码格式化（去行尾空格 / 统一缩进 / 结尾换行 / 压缩空行）
# ============================================================


@endpoint(("POST",))
def format_code(request):
    """无外部依赖的轻量格式化，纯文本变换，不触碰工作区数据。"""
    language = rt.normalize_language(opt_str(request, "language", "python"))
    source = opt_str(request, "code", "", max_len=0)
    if not source.strip():
        raise ValueError("代码不能为空")
    if len(source) > 400_000:
        raise ValueError("源码超过 400KB 上限")
    indent = opt_num(request, "indent", 4, integer=True, minimum=1, maximum=8)
    max_blank = opt_num(request, "max_blank", 2, integer=True, minimum=0, maximum=5)
    strip_trailing = opt_bool(request, "strip_trailing", True)
    unify_tabs = opt_bool(request, "unify_tabs", True)
    final_newline = opt_bool(request, "final_newline", True)

    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    changes = {"trailing_spaces": 0, "tabs": 0, "blank_lines": 0, "trailing_blank": 0,
               "final_newline": False, "total_lines": len(lines)}
    out = []
    blank_run = 0
    for line in lines:
        new_line = line
        if unify_tabs and "\t" in new_line:
            lead = len(new_line) - len(new_line.lstrip(" \t"))
            head = new_line[:lead].replace("\t", " " * indent)
            new_line = head + new_line[lead:]
            if new_line != line:
                changes["tabs"] += 1
        if strip_trailing:
            stripped = new_line.rstrip(" \t")
            if stripped != new_line:
                changes["trailing_spaces"] += 1
            new_line = stripped
        if not new_line:
            blank_run += 1
            if blank_run > max_blank:
                changes["blank_lines"] += 1
                continue
        else:
            blank_run = 0
        out.append(new_line)
    # 去掉结尾空行，按需补一个换行符
    tail = 0
    while out and not out[-1]:
        out.pop()
        tail += 1
    changes["trailing_blank"] = tail
    formatted = "\n".join(out)
    if final_newline:
        formatted += "\n"
        changes["final_newline"] = not source.endswith("\n")

    return ok({
        "language": language,
        "formatted": formatted,
        "changes": changes,
        "changed": formatted != source,
        "line_count": len(out),
        "options": {"indent": indent, "max_blank": max_blank,
                    "strip_trailing": strip_trailing, "unify_tabs": unify_tabs,
                    "final_newline": final_newline},
    })



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


# ===========================================================================
# F37 运行历史性能对比 / F38 依赖安全提示（纯新增）
# ===========================================================================

_DEP_RISK = {
    "pickle": ("high", "反序列化不可信数据可执行任意代码"),
    "marshal": ("high", "反序列化不可信数据可执行任意代码"),
    "shelve": ("medium", "底层依赖 pickle，注意数据来源"),
    "subprocess": ("medium", "命令注入风险，避免 shell=True 与拼接输入"),
    "os": ("low", "os.system / 拼接路径需谨慎"),
    "ctypes": ("medium", "直接调用内存，越界可能崩溃进程"),
    "requests": ("low", "外网请求需设置超时"),
    "urllib": ("low", "外网请求需设置超时"),
    "telnetlib": ("high", "Python 3.13 已移除，且明文传输"),
    "cgi": ("medium", "Python 3.13 已移除"),
    "crypt": ("medium", "Python 3.13 已移除"),
    "imghdr": ("low", "Python 3.13 已移除"),
    "distutils": ("low", "Python 3.12 起弃用"),
    "asynchat": ("low", "Python 3.12 起弃用"),
    "asyncore": ("low", "Python 3.12 起弃用"),
}


def _run_hash(source):
    import hashlib

    return hashlib.sha1((source or "").encode("utf-8", "ignore")).hexdigest()[:16]


@endpoint(("GET", "POST"))
def run_compare(request):
    """F37 同一段代码的多次运行对比（按源码 sha1 分组）"""
    from django.db.models import Avg, Max, Min

    qs = CodeRun.objects.filter(owner=request.user)
    file_id = opt_num(request, "file", None, integer=True)
    if file_id:
        qs = qs.filter(file_id=int(file_id))
    want = opt_str(request, "code_hash", "").strip()
    rows = list(qs.order_by("-id")[:1000])
    groups = {}
    for r in rows:
        h = _run_hash(r.source_code)
        if want and h != want:
            continue
        groups.setdefault(h, []).append(r)
    out = []
    for h, runs in groups.items():
        runs.sort(key=lambda x: x.created_at)
        durations = [x.duration_ms for x in runs]
        out.append({
            "code_hash": h,
            "runs": len(runs),
            "languages": sorted({x.language for x in runs}),
            "duration_ms": {"avg": int(sum(durations) / len(durations)), "min": min(durations),
                            "max": max(durations)},
            "memory_kb": {"avg": int(sum(x.memory_kb for x in runs) / len(runs)),
                          "max": max(x.memory_kb for x in runs)},
            "statuses": {s: sum(1 for x in runs if x.status == s)
                         for s in {x.status for x in runs}},
            "first_at": runs[0].created_at, "last_at": runs[-1].created_at,
            "source_preview": (runs[-1].source_code or "")[:200],
            "latest": {"id": runs[-1].id, "duration_ms": runs[-1].duration_ms,
                       "memory_kb": runs[-1].memory_kb, "status": runs[-1].status,
                       "stdout_preview": (runs[-1].stdout or "")[:200]},
        })
    out.sort(key=lambda g: -g["runs"])
    if want:
        for g in out:
            g["timeline"] = [
                {"id": r.id, "duration_ms": r.duration_ms, "memory_kb": r.memory_kb,
                 "status": r.status, "created_at": r.created_at}
                for r in groups.get(want, [])
            ]
    return ok({"groups": out, "count": len(out), "scanned": len(rows)})


@endpoint(("POST",))
def dependency_check(request):
    """F38 静态扫描 import：区分标准库/第三方并匹配本地风险清单（不联网）"""
    import ast
    import sys

    source = opt_str(request, "code", "")
    file_id = opt_num(request, "file", None, integer=True)
    if not source and file_id:
        f = CodeFile.objects.filter(owner=request.user, id=int(file_id)).first()
        if not f:
            raise ValueError("代码文件不存在")
        source = f.content or ""
    if not source.strip():
        raise ValueError("请传 code 或 file")
    if len(source) > 200_000:
        raise ValueError("源码超过 200KB 上限")
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"语法错误：第 {e.lineno} 行 {e.msg}")
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    stdlib = set(getattr(sys, "stdlib_module_names", set())) | set(sys.builtin_module_names)
    rows, risky = [], []
    for name in sorted(names, key=str.lower):
        kind = "stdlib" if name in stdlib else "third_party"
        level, note = _DEP_RISK.get(name, ("", ""))
        row = {"name": name, "kind": kind, "risk": level, "note": note}
        rows.append(row)
        if level:
            risky.append(row)
    return ok({
        "imports": rows, "total": len(rows),
        "stdlib": sum(1 for r in rows if r["kind"] == "stdlib"),
        "third_party": sum(1 for r in rows if r["kind"] == "third_party"),
        "risky": risky, "risk_count": len(risky),
    })


# ---------------------------------------------------------------------------
# #47 重资源接口限流：只给代码执行 / REPL / 判题入口挂 ScopedRateThrottle，
# scope 与速率见 config.settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]。
# ---------------------------------------------------------------------------
from rest_framework.throttling import ScopedRateThrottle as _ScopedRateThrottle  # noqa: E402

for _view_fn, _scope in ((run, "code_run"), (run_repl, "code_run"), (judge, "code_judge")):
    _view_fn.cls.throttle_classes = [_ScopedRateThrottle]
    _view_fn.cls.throttle_scope = _scope
