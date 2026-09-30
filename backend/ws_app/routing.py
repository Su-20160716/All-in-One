"""WebSocket 路由"""
from django.urls import path

from ws_app.consumers import CollabConsumer, NotifyConsumer


def _code_consumer():
    """延迟导入，避免 code app 未就绪时影响既有 WebSocket 路由加载。"""
    from code.consumers import CodeCollabConsumer

    return CodeCollabConsumer.as_asgi()


# 注意：本列表必须在 _code_consumer 定义之后，否则模块级调用会 NameError
websocket_urlpatterns = [
    path("ws/notify/", NotifyConsumer.as_asgi()),
    # 笔记实时协同（Yjs）
    path("ws/notes/<int:note_id>/", CollabConsumer.as_asgi()),
    # 代码文件实时协同（v6，与笔记协同同构）
    path("ws/code/<int:file_id>/", _code_consumer()),
]
