# -*- coding: utf-8 -*-
"""冒烟脚本共享的进程内传输层：不起 8000 端口，直接走 DRF 路由栈。

用法（在各 *_smoke_test.py 里）：

    from smoke_inproc import init, request_json
    CLIENT, TOKEN = init("rules", token_env="RULES_SMOKE_TOKEN",
                         session_env="RULES_SMOKE_SESSION")
    status, body = request_json(CLIENT, "GET", "/api/rules/", params={"page": 1})

约定：
- init() 负责 django.setup()、本进程内放宽限流、准备认证：
  优先用环境变量给的 JWT / 会话 Cookie，其次用户名密码登录
  （默认 admin/admin123），最后回退注册带时间戳的新账号。
- request_json() 返回 (状态码, 解析后的 JSON)，HTTP 错误也解析响应体；
  传 auth=False 时用匿名客户端（负路径测试）。
- 只改本进程内存里的限流配置，不影响开发服务器/线上配置。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse

_CLIENT = None
_ANON = None


def init(label: str, token_env: str | None = None,
         session_env: str | None = None,
         username_env: str | None = None,
         password_env: str | None = None):
    """初始化 Django 与认证，返回 (已认证 APIClient, JWT 或空串)。"""
    global _CLIENT, _ANON
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()

    from django.conf import settings as dj_settings
    from rest_framework.settings import api_settings
    dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
        {"user": "1000000/min", "anon": "1000000/min"})
    api_settings.DEFAULT_THROTTLE_RATES.update(
        dj_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])

    from rest_framework.test import APIClient
    _ANON = APIClient()
    client = APIClient()
    token = os.environ.get(token_env, "").strip() if token_env else ""
    session = os.environ.get(session_env, "").strip() if session_env else ""

    if token:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    elif session:
        client.cookies.load(session)
    else:
        username = os.environ.get(username_env, "") if username_env else ""
        password = os.environ.get(password_env, "") if password_env else ""
        if not username or not password:
            username, password = "admin", "admin123"
        resp = client.post("/api/auth/login/",
                           {"username": username, "password": password},
                           format="json")
        token = (getattr(resp, "data", None) or {}).get("access") or ""
        if not token:
            suffix = f"{int(time.time())}{os.getpid() % 1000:03d}"
            username = f"{label}_smoke_{suffix}"
            resp = client.post("/api/auth/register/", {
                "username": username,
                "password": "Qm7-tR4il-92",
                "nickname": f"{label}冒烟",
                "email": f"{username}@smoke.test",
            }, format="json")
            token = (getattr(resp, "data", None) or {}).get("access") or ""
        if token:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        else:
            raise SystemExit(f"[{label}] 无法获取认证（登录/注册均失败），冒烟中止")
    _CLIENT = client
    return client, token


def request_json(client, method: str, url: str, payload=None, params=None,
                 auth: bool = True):
    """进程内发一次请求，返回 (状态码, 解析后的 JSON)。"""
    if url.startswith("http"):
        url = urllib.parse.urlsplit(url).path
    if params:
        query = urllib.parse.urlencode(
            {key: str(value) for key, value in params.items()})
        url = f"{url}?{query}"
    target = client if auth else (_ANON or client)
    kwargs = {}
    if payload is not None:
        kwargs["data"] = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        kwargs["content_type"] = "application/json"
    resp = target.generic(method.upper(), url, **kwargs)
    raw = resp.content.decode("utf-8", errors="replace") if resp.content else ""
    try:
        body = json.loads(raw or "{}")
    except json.JSONDecodeError:
        body = {"raw": raw[:500]}
    return resp.status_code, body