"""WebSocket 路由"""
from django.urls import path

from ws_app.consumers import CollabConsumer, NotifyConsumer

websocket_urlpatterns = [
    path("ws/notify/", NotifyConsumer.as_asgi()),
    # 笔记实时协同（Yjs）
    path("ws/notes/<int:note_id>/", CollabConsumer.as_asgi()),
]
