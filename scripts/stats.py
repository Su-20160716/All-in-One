#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""项目规模统计脚本（文档数字的唯一来源）。

为什么要有这个脚本：FEATURES.md 与 docs/01~12 里的「177 项 / 143 接口 / 34 工具」
这类数字过去是手写的，改代码不回头改文档，几个月后全对不上。现在所有文档数字
统一引用本脚本输出，改完代码重跑一次即可。

用法（Windows，venv 已损坏，用托管 Python + PYTHONPATH）：
    set PYTHONPATH=backend\\venv\\Lib\\site-packages
    python scripts/stats.py           # 人类可读表格
    python scripts/stats.py --json    # 机器可读，便于 CI 比对

统计口径：
- 应用数：backend/ 下自带 apps.py 且已在 INSTALLED_APPS 注册的本地 app
- 接口数：路由树叶子数（排除 django admin），按 app 分组
- 模型数：Django app registry 里 app_label 属于本地 app 的模型
- 页面数：frontend/src/views/**/*.vue 文件数
- 路由数：frontend/src/router/index.js 里 path: 声明数
- 代码行：按后缀统计，排除 venv/node_modules/dist/migrations/构建产物
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

# 统计代码行时整体跳过的目录名
SKIP_DIRS = {
    "venv", ".venv", "node_modules", "dist", "build", ".git", "__pycache__",
    "migrations", ".workbuddy", ".idea", ".esbuild-tmp", "media", "staticfiles",
}


def _iter_files(base: Path, suffixes: tuple[str, ...]):
    """遍历目录，跳过第三方/构建产物目录。"""
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(suffixes):
                yield Path(dirpath) / fn


def count_lines(paths, skip_blank: bool = True) -> int:
    total = 0
    for p in paths:
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if skip_blank and not line.strip():
                        continue
                    total += 1
        except OSError:
            continue
    return total


# ---------------------------------------------------------------------------
# Django 侧统计：应用 / 接口 / 模型
# ---------------------------------------------------------------------------

def django_stats() -> dict:
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()

    from django.apps import apps as django_apps
    from django.conf import settings
    from django.urls import URLPattern, URLResolver, get_resolver

    # 本地 app = INSTALLED_APPS 里在 backend/ 下有目录的那些
    local_apps = []
    for entry in settings.INSTALLED_APPS:
        label = entry.rsplit(".", 1)[-1]
        if entry.startswith("django.") or entry.startswith("rest_framework"):
            continue
        if (BACKEND / label).is_dir():
            local_apps.append(entry)
    local_labels = {e.rsplit(".", 1)[-1] for e in local_apps}

    # 模型数
    models = [m for m in django_apps.get_models() if m._meta.app_label in local_labels]
    models_by_app: dict[str, int] = {}
    for m in models:
        models_by_app[m._meta.app_label] = models_by_app.get(m._meta.app_label, 0) + 1

    # 接口数：递归展开路由，排除 admin（它有几百条自动路由，不是本项目接口）
    # 归属判定：include 段形如 "api/files/" → 取最后一段，再按别名表映射到 app 名
    app_alias = {
        "auth": "accounts", "files": "files", "notes": "notes", "projects": "projects",
        "im": "im", "tools": "tools", "dashboard": "dashboard", "core": "core",
        "learning": "learning", "assistant": "assistant", "devtools": "devtools",
        "minitools": "minitools", "dataintel": "dataintel", "officesuite": "officesuite",
        "code": "code", "share": "public", "biz": "bizhub",
        "workflow": "workflow", "formstudio": "formstudio", "reporting": "reporting",
        "rules": "rules", "contracts": "contracts", "pipeline": "pipeline",
        "billing": "billing", "marketplace": "marketplace", "flags": "flags",
        "observability": "observability", "knowledgegraph": "knowledgegraph",
        "governance": "governance",
    }
    endpoints_by_app: dict[str, int] = {}

    def walk(patterns, app_hint=None):
        for p in patterns:
            if isinstance(p, URLResolver):
                seg = str(p.pattern).strip("/").split("/")[-1]
                if seg == "admin":
                    continue
                hint = app_alias.get(seg) or app_hint
                walk(p.url_patterns, hint)
            elif isinstance(p, URLPattern):
                key = app_hint or "root"
                endpoints_by_app[key] = endpoints_by_app.get(key, 0) + 1

    walk(get_resolver().url_patterns)

    return {
        "apps": len(local_apps),
        "app_list": sorted(local_labels),
        "endpoints": sum(endpoints_by_app.values()),
        "endpoints_by_app": dict(sorted(endpoints_by_app.items(), key=lambda kv: -kv[1])),
        "models": len(models),
        "models_by_app": dict(sorted(models_by_app.items(), key=lambda kv: -kv[1])),
    }


# ---------------------------------------------------------------------------
# 前端侧统计：页面 / 路由 / 代码行
# ---------------------------------------------------------------------------

def frontend_stats() -> dict:
    views = FRONTEND / "src" / "views"
    pages = sorted(views.rglob("*.vue")) if views.exists() else []
    router_file = FRONTEND / "src" / "router" / "index.js"
    routes = 0
    if router_file.exists():
        text = router_file.read_text(encoding="utf-8", errors="ignore")
        # 路由对象常写成 "{ path: '/login', ... }"，所以不能锚定行首
        routes = len(re.findall(r"\bpath:\s*['\"]", text))
    return {
        "pages": len(pages),
        "routes": routes,
        "page_list": sorted(str(p.relative_to(views)).replace("\\", "/") for p in pages),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="统计项目规模，输出文档引用的数字")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    try:
        dj = django_stats()
    except Exception as e:  # 降级：没有 Django 环境也能出文档数字（接口/模型记为 -1）
        print(f"[warn] Django 统计失败，接口/模型数不可用：{e}", file=sys.stderr)
        dj = {"apps": len([p for p in BACKEND.iterdir() if (p / "apps.py").exists()]) if BACKEND.exists() else 0,
              "app_list": [], "endpoints": -1, "endpoints_by_app": {}, "models": -1, "models_by_app": {}}

    fe = frontend_stats()

    py_files = list(_iter_files(BACKEND, (".py",)))
    fe_files = list(_iter_files(FRONTEND / "src", (".vue", ".js", ".css")))
    doc_files = list(_iter_files(ROOT / "docs", (".md",))) + ([ROOT / "FEATURES.md"] if (ROOT / "FEATURES.md").exists() else [])

    data = {
        "apps": dj["apps"],
        "endpoints": dj["endpoints"],
        "models": dj["models"],
        "pages": fe["pages"],
        "routes": fe["routes"],
        "lines": {
            "backend_py": count_lines(py_files),
            "frontend_src": count_lines(fe_files),
            "docs_md": count_lines(doc_files),
            "total": count_lines(py_files) + count_lines(fe_files),
        },
        "detail": {
            "app_list": dj["app_list"],
            "endpoints_by_app": dj["endpoints_by_app"],
            "models_by_app": dj["models_by_app"],
        },
    }

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("=" * 62)
    print("全能协作平台 · 项目规模")
    print("=" * 62)
    print(f"  应用（Django app） : {data['apps']}")
    print(f"  接口（路由叶子）   : {data['endpoints']}")
    print(f"  模型（Django ORM） : {data['models']}")
    print(f"  页面（.vue）       : {data['pages']}")
    print(f"  前端路由           : {data['routes']}")
    print(f"  后端 Python 行     : {data['lines']['backend_py']:,}")
    print(f"  前端 src 行        : {data['lines']['frontend_src']:,}")
    print(f"  文档行             : {data['lines']['docs_md']:,}")
    print(f"  代码合计           : {data['lines']['total']:,}")
    print("-" * 62)
    print("  接口分布：", " ".join(f"{k}={v}" for k, v in data["detail"]["endpoints_by_app"].items()))
    print("  模型分布：", " ".join(f"{k}={v}" for k, v in data["detail"]["models_by_app"].items()))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
