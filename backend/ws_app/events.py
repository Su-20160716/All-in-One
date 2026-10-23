"""WS 事件接入：文件变动 / 看板变动 / 聊天消息 / 会话广播 实时推送

业务视图在关键写操作后调用这些函数；单机 InMemory 与多机 Redis ChannelLayer 均可。
"""
from ws_app.consumers import push_to_session, push_to_user


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
    push_to_session(session_id, "chat_message", payload)


def _session_member_ids(session_id: int):
    """惰性导入，避免循环依赖"""
    from im.models import ChatSession

    session = ChatSession.objects.filter(pk=session_id).first()
    return list(session.members.values_list("id", flat=True)) if session else []


def send_to_session(session_id: int, event: dict):
    """向会话全体成员的个人频道投递事件（event 形如 {"type": "chat.message", "data": {...}}）"""
    for uid in _session_member_ids(session_id):
        # type 中的点号对应 consumer handler 名（点→下划线）
        push_to_user(uid, event["type"].replace(".", "_"), event.get("data", {}))


def broadcast_session(session_id: int, event: dict):
    """send_to_session 的语义化别名"""
    send_to_session(session_id, event)
