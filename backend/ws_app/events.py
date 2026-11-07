"""WS 事件接入：文件变动 / 看板变动 / 聊天消息 / 会话广播 实时推送

业务视图在关键写操作后调用这些函数；单机 InMemory 与多机 Redis ChannelLayer 均可。
"""
import logging

from ws_app.consumers import push_to_user

logger = logging.getLogger(__name__)

# NotifyConsumer 上已注册的 group_send handler（点号已转下划线）
_KNOWN_HANDLERS = frozenset({
    "notification", "file_event", "board_event", "chat_message", "chat_typing",
    "group_system", "session_updated", "session_typing", "message_recalled",
    "message_pinned", "message_edited", "message_deleted",
})


def notify_file_event(user_id: int, action: str, payload: dict):
    """文件新建/删除/重命名/共享 → 推送给文件所有者"""
    push_to_user(user_id, "file_event", {"action": action, **payload})


def notify_board_event(project_id: int, action: str, payload: dict):
    """看板变动 → 推送给项目全体成员（owner + members）。

    历史实现误把 project_id 当 user_id 传 push_to_user，消息发到
    user_<project_id> 组——没有任何用户会加入该组，广播等于静默丢弃。
    这里按项目成员逐个投递到各自的 user_<id> 个人频道。
    """
    from projects.models import Project

    project = Project.objects.filter(pk=project_id).first()
    if not project:
        return
    member_ids = set(project.members.values_list("id", flat=True))
    member_ids.add(project.owner_id)
    event = {"action": action, "project_id": project_id, **payload}
    for uid in member_ids:
        if uid:
            push_to_user(uid, "board_event", event)


def notify_chat_message(session_id: int, payload: dict):
    send_to_session(session_id, {"type": "chat.message", "data": payload})


def send_to_session(session_id: int, event: dict):
    """向会话组广播事件（event 形如 {"type": "chat.message", "data": {...}}）

    NotifyConsumer 连接时会加入其所有会话组，因此这里一次 group_send 即可
    覆盖全体在线成员；离线/刚入群尚未重连的成员由前端拉取兜底。
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    event_type = str(event.get("type") or "")
    handler = event_type.replace(".", "_")
    if handler not in _KNOWN_HANDLERS:
        logger.warning("send_to_session 收到未注册事件类型 %r，已跳过（session=%s）", event_type, session_id)
        return
    layer = get_channel_layer()
    if not layer:
        return
    async_to_sync(layer.group_send)(
        f"session_{session_id}", {"type": handler, "data": event.get("data", {})}
    )


def broadcast_session(session_id: int, event: dict):
    """send_to_session 的语义化别名"""
    send_to_session(session_id, event)
