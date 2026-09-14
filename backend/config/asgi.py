"""
ASGI 入口：HTTP（Django）+ WebSocket（Channels）
WebSocket 路径：
  /ws/notify/          统一消费者（通知/文件/看板/聊天 消息分发）
  /ws/notes/<id>/      笔记实时协同（Yjs CRDT 更新中继 + 快照持久化）

认证：JWT 优先（?token=）、Session 兜底 —— 见 ws_app.middleware.JWTAuthMiddleware
"""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from ws_app.middleware import JWTAuthMiddleware  # noqa: E402
from ws_app.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": JWTAuthMiddleware(URLRouter(websocket_urlpatterns)),
    }
)
