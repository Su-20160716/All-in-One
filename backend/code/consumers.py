# -*- coding: utf-8 -*-
"""代码文件协同编辑消费者（v6）。

与 `CollabConsumer`（笔记）完全同构，只是把 Note 换成 CodeFile：
- 服务端**不做 CRDT 合并**，只做「快照 + 增量日志」持久化中继；
- 快照落库时把纯文本镜像回写到 `CodeFile.content`，从而
  自动触发全文索引（core.signals）与行号/统计刷新。

协议与笔记协同逐字一致，前端可直接复用 `utils/collab.js`。
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

MAX_CODE_UPDATE_LOG = 200


class CodeCollabConsumer(AsyncJsonWebsocketConsumer):
    """协议（客户端 → 服务端）
      {"type": "ping"}
      {"type": "yjs.update", "update": "<base64>"}
      {"type": "yjs.snapshot", "snapshot": "<base64>", "text": "<纯文本>"}
      {"type": "awareness", "state": {...}}
      {"type": "presence", "action": "join"|"leave"}

    协议（服务端 → 客户端）
      {"type": "collab.init",    "data": {file_id, path, language, content, snapshot, updates, revision, participants}}
      {"type": "yjs.update",     "data": {...}}
      {"type": "yjs.snapshot",   "data": {...}}
      {"type": "awareness",      "data": {...}}
      {"type": "presence",       "data": {...}}
      {"type": "collab.compact", "data": {reason}}
      {"type": "pong"}
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.user = user
        self.file_id = int(self.scope["url_route"]["kwargs"]["file_id"])
        if not await self._can_edit():
            await self.close(code=4003)
            return

        self.group_name = f"collab_code_{self.file_id}"
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
                 "data": {"update": update, "sender": self.user.id,
                          "sender_name": self.user.display_name}},
            )
            if size >= MAX_CODE_UPDATE_LOG:
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
            return
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

    # ---- 数据库操作 ----
    @database_sync_to_async
    def _can_edit(self):
        from core.scoping import can_write
        from code.models import CodeFile

        obj = CodeFile.objects.filter(pk=self.file_id).first()
        if obj is None:
            return False
        return can_write(self.user, obj)

    @database_sync_to_async
    def _load_state(self):
        from code.models import CodeCollabState, CodeFile

        f = CodeFile.objects.filter(pk=self.file_id).first()
        state = CodeCollabState.objects.filter(file_id=self.file_id).first()
        snapshot = ""
        if state and state.snapshot is not None:
            raw = state.snapshot
            snapshot = bytes(raw).decode("utf-8", errors="ignore") \
                if isinstance(raw, (bytes, memoryview)) else str(raw)
        return {
            "file_id": self.file_id,
            "path": f.path if f else "",
            "language": f.language if f else "",
            "content": f.content if f else "",
            "snapshot": snapshot,
            "updates": (state.update_log if state else []) or [],
            "revision": state.revision if state else 0,
        }

    @database_sync_to_async
    def _append_update(self, update: str, user_id: int) -> int:
        """#62：行锁内取号后追加增量，避免并发 append 丢更新。

        与笔记侧（NoteCollabUpdate 独立表）同一套语义；code app 的 update 表
        本次未建，故仍在 JSON 列内追加，但「读-改-写」整段收进行锁事务内，
        并发写入不再互相覆盖 revision / update_log。
        """
        from django.db import transaction

        from code.models import CodeCollabState

        with transaction.atomic():
            state, _ = CodeCollabState.objects.select_for_update().get_or_create(file_id=self.file_id)
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
        from code.models import CodeCollabState, CodeFile, CodeVersion

        state, _ = CodeCollabState.objects.get_or_create(file_id=self.file_id)
        state.snapshot = snapshot.encode("utf-8")
        state.update_log = []
        state.revision += 1
        state.text_mirror = text[:400000]
        state.save(update_fields=["snapshot", "update_log", "revision", "text_mirror", "updated_at"])

        # 回写正文：触发全文索引（core.signals）与行数统计
        if text:
            f = CodeFile.objects.filter(pk=self.file_id).first()
            if f and f.content != text:
                # 协同落盘前留一份版本快照，避免历史被碾平
                if f.content:
                    CodeVersion.objects.create(
                        file=f, content=f.content, message="协同编辑前快照",
                        size=len(f.content.encode("utf-8")),
                    )
                f.content = text[:400000]
                # #63：落库前按最终正文重算字节数与行数，避免 size/lines 与正文不一致
                f.size = len(f.content.encode("utf-8"))
                f.lines = f.content.count("\n") + 1 if f.content else 0
                f.save(update_fields=["content", "size", "lines", "updated_at"])
        return state.revision

    @database_sync_to_async
    def _join_roster(self):
        from code.models import CodeCollabState

        state, _ = CodeCollabState.objects.get_or_create(file_id=self.file_id)
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
