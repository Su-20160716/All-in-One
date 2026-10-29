"""
ASGI 入口：HTTP（Django）+ WebSocket（Channels）
WebSocket 路径：
  /ws/notify/          统一消费者（通知/文件/看板/聊天 消息分发）
  /ws/notes/<id>/      笔记实时协同（Yjs CRDT 更新中继 + 快照持久化）

认证：JWT 优先（?token=）、Session 兜底 —— 见 ws_app.middleware.JWTAuthMiddleware
"""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from ws_app.middleware import JWTAuthMiddleware  # noqa: E402
from ws_app.routing import websocket_urlpatterns  # noqa: E402


def _ws_allowed_origins():
    """WS 允许的 Origin 列表。

    AllowedHostsOriginValidator 只认 ALLOWED_HOSTS，而生产环境前端常独立部署
    （CF Pages）且不在后端 ALLOWED_HOSTS 里，会误杀正常连接。这里改为：
    - 开发（ALLOWED_HOSTS 含 *）→ 全放开，行为与改造前一致
    - 生产 → CORS / CSRF 白名单 + ALLOWED_HOSTS 推出的同源地址 + WS_ALLOWED_ORIGINS
    """
    if "*" in settings.ALLOWED_HOSTS:
        return ["*"]
    origins = set()
    for raw in list(getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []) + list(
        getattr(settings, "CSRF_TRUSTED_ORIGINS", []) or []
    ):
        if raw:
            origins.add(str(raw).rstrip("/"))
    for host in settings.ALLOWED_HOSTS:
        if not host or "*" in host:
            continue
        origins.add(f"https://{host}")
        origins.add(f"http://{host}")
    for raw in os.environ.get("WS_ALLOWED_ORIGINS", "").split(","):
        if raw.strip():
            origins.add(raw.strip().rstrip("/"))
    return sorted(origins)


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Origin 校验放在认证之前：阻止任意站点借用浏览器身份建立 WS
        "websocket": OriginValidator(
            JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
            _ws_allowed_origins(),
        ),
    }
)
