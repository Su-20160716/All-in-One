# -*- coding: utf-8 -*-
"""pipeline 冒烟脚本（默认不执行；由人工在联调环境手动运行）。

用法：
    venv/Scripts/python.exe pipeline_smoke_test.py

脚本只读为主：目录 + 列表 + 一个最小管道的创建。所有请求走 APIClient，
不启动 dev server，也不会发起任何外部网络请求。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

BASE = "/api/pipeline/"
User = get_user_model()


def show(label: str, response) -> dict:
    """打印状态码并返回 JSON，失败时把响应体完整打出来便于排障。"""
    body = response.json() if response.content else {}
    flag = "OK" if response.status_code == 200 and body.get("ok") else "FAIL"
    print(f"[{flag}] {label} -> {response.status_code}")
    if flag == "FAIL":
        print(json.dumps(body, ensure_ascii=False, indent=2)[:2000])
    return body


def main() -> int:
    user, created = User.objects.get_or_create(
        username="pipeline_smoke", defaults={"nickname": "冒烟账号"})
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    client = APIClient()
    client.force_authenticate(user)

    catalog = show("目录", client.get(BASE))
    if not catalog.get("ok"):
        return 1
    print("接口数量：", catalog["data"].get("endpoint_count"))

    show("连接器列表", client.get(BASE + "connectors/"))
    show("管道列表", client.get(BASE + "pipelines/"))
    show("运行列表", client.get(BASE + "runs/"))
    show("统计总览", client.get(BASE + "stats/overview/"))

    created_pipeline = show("新建管道", client.post(BASE + "pipelines/", {
        "code": "smoke_pipeline",
        "name": "冒烟管道",
        "description": "由 pipeline_smoke_test.py 创建，可在联调环境删除",
    }, format="json"))
    if created_pipeline.get("ok"):
        pid = created_pipeline["data"]["id"]
        show("管道详情", client.get(BASE + f"pipelines/{pid}/"))
        show("DAG 校验", client.post(BASE + f"pipelines/{pid}/validate/", {},
                                    format="json"))
        show("删除管道", client.post(BASE + f"pipelines/{pid}/delete/", {},
                                    format="json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
