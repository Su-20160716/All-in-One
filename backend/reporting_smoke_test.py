#!/usr/bin/env python
"""reporting 应用只读冒烟脚本（手工运行，不会被测试自动发现）。

用途：
    在开发库上快速确认 reporting 的目录、白名单、公式、cron、数据集、报表、
    仪表盘、计划、订阅、指标、运行记录等核心 GET 接口是否可用，并统一校验
    响应信封与列表分页结构。

用法：
    venv/Scripts/python.exe reporting_smoke_test.py
    venv/Scripts/python.exe reporting_smoke_test.py --user alice
    venv/Scripts/python.exe reporting_smoke_test.py --base /api/reporting --strict

说明：
    - 只发 GET 请求，不写任何业务数据，可安全重复执行。
    - 不修改 settings / urls，只负责引导 Django 环境并调用 APIClient。
    - 退出码：0 全部通过；1 存在失败项；2 环境或账号不可用。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    # 直接以脚本方式运行时，保证 config / reporting 等包可被导入
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402  (必须先设置 DJANGO_SETTINGS_MODULE)

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402


class SmokeCase:
    """单个冒烟用例：路径 + 期望校验器。"""

    def __init__(self, name, path, check=None, params=None):
        self.name = name
        self.path = path
        self.check = check
        self.params = params or {}


def _envelope(payload):
    """校验统一信封：必须含布尔 ok，成功时带 data。"""
    if not isinstance(payload, dict) or "ok" not in payload:
        return "响应不是统一信封"
    if not payload.get("ok"):
        return f"接口返回失败：{payload.get('error') or payload}"
    if "data" not in payload:
        return "成功响应缺少 data"
    return None


def _list_shape(payload):
    """校验列表结构：items/count/page/page_size 四件套齐全。"""
    data = payload.get("data") or {}
    missing = [k for k in ("items", "count", "page", "page_size") if k not in data]
    if missing:
        return f"列表缺少字段：{','.join(missing)}"
    if not isinstance(data["items"], list):
        return "items 不是数组"
    if data["count"] != len(data["items"]):
        return f"count({data['count']}) 与 items({len(data['items'])}) 不一致"
    if int(data.get("page_size") or 0) > 200:
        return "page_size 超过上限 200"
    return None


def _catalog_shape(payload):
    """目录接口必须给出模型/枚举/接口清单等元信息。"""
    data = payload.get("data") or {}
    for key in ("models", "enums", "endpoints"):
        if key not in data:
            return f"目录缺少 {key}"
    enums = data.get("enums") or {}
    for key in ("operators", "widget_types"):
        if key not in enums:
            return f"目录 enums 缺少 {key}"
    if not data.get("endpoints"):
        return "目录接口清单为空"
    return None


def _dict_shape(payload):
    """仅要求 data 是对象（详情类接口）。"""
    if not isinstance(payload.get("data"), dict):
        return "data 不是对象"
    return None


def build_cases(base):
    """构造只读用例清单；路径全部相对 base，便于不同挂载前缀复用。"""
    return [
        SmokeCase("接口目录", f"{base}/", _catalog_shape),
        SmokeCase("模型清单", f"{base}/models/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("枚举字典", f"{base}/meta/", _dict_shape),
        SmokeCase("公式校验", f"{base}/formula/validate/", _dict_shape,
                  {"formula": "1+2"}),
        SmokeCase("cron 预览", f"{base}/cron/preview/", _dict_shape,
                  {"cron": "0 9 * * 1"}),
        SmokeCase("路由自检", f"{base}/resolver/", _dict_shape),
        SmokeCase("组件注册表", f"{base}/registry/", _dict_shape),
        SmokeCase("数据集列表", f"{base}/datasets/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("报表列表", f"{base}/reports/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("仪表盘列表", f"{base}/dashboards/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("计划列表", f"{base}/schedules/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("订阅列表", f"{base}/subscriptions/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("运行记录", f"{base}/runs/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("导出任务", f"{base}/export-jobs/", _list_shape,
                  {"page": 1, "page_size": 10}),
        SmokeCase("指标总览", f"{base}/metrics/overview/", _dict_shape,
                  {"days": 7}),
        SmokeCase("质量检查", f"{base}/quality/check/", _dict_shape,
                  {"model": "bizhub.BizRecord"}),
    ]


def pick_user(username=None):
    """选定冒烟账号：显式指定优先，否则取最早创建的活动用户。"""
    model = get_user_model()
    qs = model.objects.filter(is_active=True).order_by("id")
    if username:
        return qs.filter(username=username).first()
    return qs.first()


def run_case(client, case):
    """执行单个用例并返回 (是否通过, 说明)。"""
    try:
        # 交给测试客户端编码查询串，避免空格、加号等字符手工拼接出错
        response = client.get(case.path, case.params or None)
    except Exception as exc:  # 网络/序列化等异常都归入失败项，不中断脚本
        return False, f"{type(exc).__name__}: {exc}"

    if response.status_code >= 500:
        return False, f"HTTP {response.status_code}"

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return False, f"HTTP {response.status_code} 响应不是 JSON"

    problem = _envelope(payload)
    if problem is None and case.check is not None:
        problem = case.check(payload)
    if problem is not None:
        return False, problem

    data = payload.get("data") or {}
    extra = f" count={data['count']}" if isinstance(data, dict) and "count" in data else ""
    return True, f"HTTP {response.status_code}{extra}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="reporting 只读冒烟")
    parser.add_argument("--base", default="/api/reporting",
                        help="接口挂载前缀，默认 /api/reporting")
    parser.add_argument("--user", default="", help="用于认证的用户名，默认取最早用户")
    parser.add_argument("--strict", action="store_true",
                        help="严格模式：任何非 2xx 亦记为失败")
    args = parser.parse_args(argv)

    base = args.base.rstrip("/")
    user = pick_user(args.user or None)
    if user is None:
        print("[SKIP] 数据库中没有可用用户，无法执行冒烟")
        return 2

    client = APIClient()
    client.force_authenticate(user=user)

    try:
        from reporting.urls import ENDPOINT_COUNT
    except Exception:  # 路由导入失败时仍继续跑用例，只是少一条统计
        ENDPOINT_COUNT = 0

    print(f"reporting 冒烟：用户={user.get_username()} base={base} 路由数={ENDPOINT_COUNT}")
    failed = 0
    for case in build_cases(base):
        ok, detail = run_case(client, case)
        if ok and args.strict and not detail.startswith("HTTP 2"):
            ok, detail = False, f"严格模式：{detail}"
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {case.name:<8} {case.path} -> {detail}")

    print(f"\n合计 {len(build_cases(base))} 项，失败 {failed} 项")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
