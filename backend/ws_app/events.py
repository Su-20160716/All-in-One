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


def _session_member_ids(session_id: int):
    """惰性导入，避免循环依赖"""
    from im.models import ChatSession

    session = ChatSession.objects.filter(pk=session_id).first()
    return list(session.members.values_list("id", flat=True)) if session else []


def send_to_session(session_id: int, event: dict):
    """向会话全体成员的个人频道投递事件（event 形如 {"type": "chat.message", "data": {...}}）"""
    event_type = str(event.get("type") or "")
    handler = event_type.replace(".", "_")
    if handler not in _KNOWN_HANDLERS:
        logger.warning("send_to_session 收到未注册事件类型 %r，已跳过（session=%s）", event_type, session_id)
        return
    for uid in _session_member_ids(session_id):
        # type 中的点号对应 consumer handler 名（点→下划线）
        push_to_user(uid, handler, event.get("data", {}))


def broadcast_session(session_id: int, event: dict):
    """send_to_session 的语义化别名"""
    send_to_session(session_id, event)
