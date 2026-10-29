"""统一 WebSocket 消费者：认证后加入个人频道组，接收/广播多业务消息

消息协议：
  客户端 → 服务端: {"type": "ping"} | {"type": "typing", "session_id": 1}
  服务端 → 客户端:
    {"type": "notification", "data": {...}}    通知推送
    {"type": "file.event", "data": {...}}      文件变动
    {"type": "board.event", "data": {...}}     看板变动
    {"type": "chat.message", "data": {...}}    新聊天消息
    {"type": "group.system", "data": {...}}    群系统消息
    {"type": "session.updated", "data": {...}} 会话更新
    {"type": "message.recalled", "data": {...}} 消息撤回
    {"type": "pong"}                           心跳应答

另有 CollabConsumer（/ws/notes/<id>/）负责笔记实时协同，见文件后半部分。
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


class NotifyConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        self.group_name = f"user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "ping":
            await self.send_json({"type": "pong", "ts": str(__import__("django.utils.timezone", fromlist=["now"]).now())})
        elif msg_type == "typing":
            session_id = content.get("session_id")
            try:
                session_id = int(session_id)
            except (TypeError, ValueError):
                return
            member_ids = await self._session_member_ids(session_id)
            if not member_ids:
                return  # 非会话成员不允许向该会话广播输入状态
            payload = {"user": self.user.display_name, "user_id": self.user.id, "session_id": session_id}
            for uid in member_ids:
                if uid == self.user.id:
                    continue
                await self.channel_layer.group_send(
                    f"user_{uid}", {"type": "chat_typing", "data": payload},
                )

    @database_sync_to_async
    def _session_member_ids(self, session_id):
        """会话成员 id；调用者不在会话内时返回空列表"""
        from im.models import ChatSession

        session = ChatSession.objects.filter(pk=session_id, members=self.user).first()
        if session is None:
            return []
        return list(session.members.values_list("id", flat=True))

    # ---- 以下 handler 供 channel_layer.group_send 调用 ----
    async def notification(self, event):
        await self.send_json({"type": "notification", "data": event["data"]})

    async def file_event(self, event):
        await self.send_json({"type": "file.event", "data": event["data"]})

    async def board_event(self, event):
        await self.send_json({"type": "board.event", "data": event["data"]})

    async def chat_message(self, event):
        await self.send_json({"type": "chat.message", "data": event["data"]})

    async def chat_typing(self, event):
        await self.send_json({"type": "chat.typing", "data": event["data"]})

    async def group_system(self, event):
        await self.send_json({"type": "group.system", "data": event["data"]})

    async def session_updated(self, event):
        await self.send_json({"type": "session.updated", "data": event["data"]})

    async def session_typing(self, event):
        await self.send_json({"type": "session.typing", "data": event["data"]})

    async def message_recalled(self, event):
        await self.send_json({"type": "message.recalled", "data": event["data"]})

    async def message_pinned(self, event):
        await self.send_json({"type": "message.pinned", "data": event["data"]})

    async def message_edited(self, event):
        await self.send_json({"type": "message.edited", "data": event["data"]})

    async def message_deleted(self, event):
        await self.send_json({"type": "message.deleted", "data": event["data"]})


def push_to_user(user_id: int, event_type: str, data: dict):
    """业务侧向用户个人频道推送（同步上下文调用）"""
    layer = get_channel_layer()
    if not layer:
        return
    async_to_sync(layer.group_send)(f"user_{user_id}", {"type": event_type, "data": data})


# ---------------------------------------------------------------------------
# 笔记实时协同（Yjs / CRDT）
# ---------------------------------------------------------------------------

MAX_UPDATE_LOG = 200  # 增量日志上限，超过则请求客户端压缩为快照


class CollabConsumer(AsyncJsonWebsocketConsumer):
    """笔记协同编辑消费者。

    协议（客户端 → 服务端）
      {"type": "ping"}
      {"type": "yjs.update", "update": "<base64 增量更新>"}
      {"type": "yjs.snapshot", "snapshot": "<base64 全量状态>", "text": "<纯文本镜像>"}
      {"type": "awareness", "state": {...}}          光标/选区/在线状态
      {"type": "presence", "action": "join"|"leave"}

    协议（服务端 → 客户端）
      {"type": "collab.init",  "data": {snapshot, updates, revision, participants}}
      {"type": "yjs.update",   "data": {update, sender}}
      {"type": "yjs.snapshot", "data": {snapshot, revision, sender}}
      {"type": "awareness",    "data": {...}}
      {"type": "presence",     "data": {action, sender, participants}}
      {"type": "collab.compact", "data": {reason}}
      {"type": "pong"}

    关键设计：服务端**不做 CRDT 合并**（无需 Python 端 Yjs 实现）。
    Yjs 的 update 满足交换律与幂等性，因此「快照 + 增量日志」这一组合
    可以让任何新客户端完整还原文档；日志过长时请客户端重新压缩为快照。
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        self.note_id = int(self.scope["url_route"]["kwargs"]["note_id"])
        if not await self._can_edit():
            await self.close(code=4003)
            return

        self.group_name = f"collab_note_{self.note_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        state = await self._load_state()
        state["participants"] = await self._join_roster()
        await self.send_json({"type": "collab.init", "data": state})
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "collab_presence",
             "data": {"action": "join", "sender": self.user.display_name, "user_id": self.user.id}},
        )

    async def disconnect(self, code):
        if not hasattr(self, "group_name"):
            return
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await self._leave_roster()
        await self.channel_layer.group_send(
            self.group_name,
            {"type": "collab_presence",
             "data": {"action": "leave", "sender": self.user.display_name, "user_id": self.user.id}},
        )

    async def receive_json(self, content, **kwargs):
        msg_type = content.get("type")
        if msg_type == "ping":
            from django.utils import timezone

            await self.send_json({"type": "pong", "ts": timezone.now().isoformat()})
            return

        if msg_type == "yjs.update":
            update = content.get("update")
            if not isinstance(update, str) or not update:
                return
            size = await self._append_update(update, self.user.id)
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "collab_update",
                 "data": {"update": update, "sender": self.user.id, "sender_name": self.user.display_name}},
            )
            if size >= MAX_UPDATE_LOG:
                await self.send_json({"type": "collab.compact", "data": {"reason": "update_log_full"}})
            return

        if msg_type == "yjs.snapshot":
            snapshot = content.get("snapshot")
            if not isinstance(snapshot, str) or not snapshot:
                return
            text = content.get("text") or ""
            revision = await self._save_snapshot(snapshot, text, self.user.id)
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "collab_snapshot",
                 "data": {"snapshot": snapshot, "revision": revision,
                          "sender": self.user.id, "sender_name": self.user.display_name}},
            )
            return

        if msg_type == "awareness":
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "collab_awareness",
                 "data": {"state": content.get("state"), "sender": self.user.id,
                          "sender_name": self.user.display_name}},
            )
            return

        if msg_type == "presence":
            await self.channel_layer.group_send(
                self.group_name,
                {"type": "collab_presence",
                 "data": {"action": content.get("action", "join"),
                          "sender": self.user.display_name, "user_id": self.user.id}},
            )

    # ---- group_send handlers ----
    async def collab_update(self, event):
        data = dict(event["data"])
        if data.get("sender") == self.user.id:
            return  # 自己发出的更新无需回显
        await self.send_json({"type": "yjs.update", "data": data})

    async def collab_snapshot(self, event):
        data = dict(event["data"])
        await self.send_json({"type": "yjs.snapshot", "data": data})

    async def collab_awareness(self, event):
        data = dict(event["data"])
        if data.get("sender") == self.user.id:
            return
        await self.send_json({"type": "awareness", "data": data})

    async def collab_presence(self, event):
        data = dict(event["data"])
        if data.get("user_id") == self.user.id and data.get("action") == "join":
            return
        await self.send_json({"type": "presence", "data": data})

    # ---- 数据库操作（同步上下文包装） ----
    @database_sync_to_async
    def _can_edit(self):
        from core.scoping import can_write
        from notes.models import Note

        note = Note.objects.filter(pk=self.note_id, is_deleted=False).first()
        if note is None:
            return False
        # 协同会写回正文（_save_snapshot → note.save），必须按「写权限」判定；
        # 数据范围（dept/all）只决定能不能看，不能拿来看他人笔记后改内容。
        return can_write(self.user, note)

    @database_sync_to_async
    def _load_state(self):
        from notes.models import Note, NoteCollabState

        note = Note.objects.filter(pk=self.note_id).first()
        state = NoteCollabState.objects.filter(note_id=self.note_id).first()
        snapshot = ""
        if state and state.snapshot is not None:
            raw = state.snapshot
            snapshot = bytes(raw).decode("utf-8", errors="ignore") if isinstance(raw, (bytes, memoryview)) else str(raw)
        return {
            "note_id": self.note_id,
            "title": note.title if note else "",
            "content": note.content if note else "",
            "snapshot": snapshot,
            "updates": (state.update_log if state else []) or [],
            "revision": state.revision if state else 0,
        }

    @database_sync_to_async
    def _append_update(self, update: str, user_id: int) -> int:
        from notes.models import NoteCollabState

        state, _ = NoteCollabState.objects.get_or_create(note_id=self.note_id)
        log = list(state.update_log or [])
        log.append(update)
        state.update_log = log
        state.revision += 1
        contributors = [c for c in (state.contributors or []) if c != user_id]
        contributors.insert(0, user_id)
        state.contributors = contributors[:10]
        state.save(update_fields=["update_log", "revision", "contributors", "updated_at"])
        return len(log)

    @database_sync_to_async
    def _save_snapshot(self, snapshot: str, text: str, user_id: int) -> int:
        from notes.models import Note, NoteCollabState

        state, _ = NoteCollabState.objects.get_or_create(note_id=self.note_id)
        state.snapshot = snapshot.encode("utf-8")
        state.update_log = []
        state.revision += 1
        state.text_mirror = text[:200000]
        state.save(update_fields=["snapshot", "update_log", "revision", "text_mirror", "updated_at"])

        # 把协同结果回写到笔记正文（触发全文索引与双链重建）
        if text:
            note = Note.objects.filter(pk=self.note_id).first()
            if note and note.content != text:
                note.content = text[:200000]
                note.save(update_fields=["content", "updated_at"])
        return state.revision

    @database_sync_to_async
    def _join_roster(self):
        from notes.models import NoteCollabState

        state, _ = NoteCollabState.objects.get_or_create(note_id=self.note_id)
        contributors = list(state.contributors or [])
        if self.user.id in contributors:
            contributors.remove(self.user.id)
        contributors.insert(0, self.user.id)
        state.contributors = contributors[:10]
        state.save(update_fields=["contributors", "updated_at"])
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return [
            {"id": u.id, "name": u.display_name}
            for u in User.objects.filter(id__in=state.contributors)
        ]

    @database_sync_to_async
    def _leave_roster(self):
        return None

