"""IM 视图：会话管理、成员、成员设置、消息收发、撤回、删除、转发、搜索、未读汇总"""
from datetime import datetime

from django.db import transaction
from django.db.models import Count, DateTimeField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from core.validators import as_date, as_datetime, as_int, parse_bool
from im.models import ChatMessage, ChatSession, KeywordAlert, MessageFavorite, QuickReply, SessionMemberSetting, TodoItem
from im.serializers import (
    ChatMessageSerializer,
    MessageFavoriteSerializer,
    QuickReplySerializer,
    SessionSerializer,
    TodoItemSerializer,
)
from ws_app.events import broadcast_session, send_to_session


def _member_sessions(user):
    return ChatSession.objects.filter(members=user).distinct()


_EPOCH = timezone.make_aware(datetime(1970, 1, 1))


def _with_unread(qs, user):
    """给会话 queryset 标注 unread_count（单条 SQL，替代每个会话一次 COUNT）。

    阈值取该用户在该会话的 last_read_at；没有设置记录时回落到 1970 年，
    等价于「全部未读」。
    """
    last_read = Subquery(
        SessionMemberSetting.objects.filter(session=OuterRef("pk"), user=user)
        .values("last_read_at")[:1]
    )
    threshold = Coalesce(last_read, Value(_EPOCH), output_field=DateTimeField())
    unread = Subquery(
        ChatMessage.objects.filter(session=OuterRef("pk"))
        .exclude(sender=user)
        .filter(created_at__gt=threshold)
        .values("session").annotate(c=Count("id")).values("c")[:1]
    )
    return qs.annotate(unread_count=Coalesce(unread, 0))


def _get_setting(session, user):
    obj, _ = SessionMemberSetting.objects.get_or_create(session=session, user=user)
    return obj


class SessionListView(APIView):
    """会话列表（置顶优先）/ 创建单聊或群聊"""

    def get(self, request):
        archived = request.query_params.get("archived")
        # B6：prefetch members（members_info/member_count 共用）+ 最后一条消息
        # （to_attr 预取，避免每会话一次 order by 查询）
        # 每条会话只取「最后一条消息」：旧实现把每个会话的全部消息都预取进内存。
        # 先用相关子查询拿 last_message_id，再批量取这些消息（共 2 条 SQL）。
        last_msg_id = (
            ChatMessage.objects.filter(session=OuterRef("pk"))
            .exclude(is_recalled=True)
            .order_by("-created_at")
            .values("id")[:1]
        )
        sessions = list(
            _with_unread(_member_sessions(request.user), request.user)
            .annotate(last_message_id=Subquery(last_msg_id))
            .prefetch_related("members")
        )
        msg_ids = [s.last_message_id for s in sessions if s.last_message_id]
        last_msgs = {
            m.id: m
            for m in ChatMessage.objects.filter(id__in=msg_ids).select_related("sender")
        } if msg_ids else {}
        for s in sessions:
            msg = last_msgs.get(s.last_message_id)
            s._last_messages = [msg] if msg else []
        data = SessionSerializer(sessions, many=True, context={"request": request}).data
        # 归档过滤：archived=1 仅归档；默认仅未归档
        if archived == "1":
            data = [d for d in data if d["is_archived"]]
        elif archived == "all":
            pass
        else:
            data = [d for d in data if not d["is_archived"]]
        # 标签过滤（会话设置里的自定义分组标签）
        tag = (request.query_params.get("tag") or "").strip()
        if tag:
            data = [d for d in data if tag in (d.get("tags") or [])]
        # 关键字过滤（会话名 / 对方名）
        kw = (request.query_params.get("search") or "").strip()
        if kw:
            data = [d for d in data if kw in d.get("name", "") or kw in (d.get("last_message", {}) or {}).get("content", "")]
        # 置顶在前，再按最后消息时间
        def sort_key(item):
            last = item["last_message"]["created_at"] if item["last_message"] else item["created_at"]
            return (0 if item["is_pinned"] else 1, -last.timestamp() if hasattr(last, "timestamp") else 0)
        data.sort(key=sort_key)
        return Response({"list": data, "total": len(data)})

    def post(self, request):
        stype = request.data.get("type", "single")
        if stype == "direct":
            stype = "single"
        raw_ids = request.data.get("member_ids") or []
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "member_ids 必须是数组"}, status=400)
        if len(raw_ids) > 200:
            return Response({"message": "单次最多选择 200 人"}, status=400)
        try:
            member_ids = [as_int(x, field="member_ids", minimum=1) for x in raw_ids]
        except ValidationError:
            return Response({"message": "member_ids 必须全部为整数"}, status=400)
        if stype == "single":
            other_id = member_ids[0] if member_ids else None
            other = User.objects.filter(id=other_id).first()
            if not other:
                return Response({"message": "对方不存在"}, status=400)
            exist = ChatSession.objects.filter(type="single", members=request.user).filter(members=other).first()
            if exist:
                # 对方可能「退出」过单聊（= 归档），重新发起时恢复显示
                setting = _get_setting(exist, request.user)
                if setting.is_archived:
                    setting.is_archived = False
                    setting.save(update_fields=["is_archived"])
                return Response(SessionSerializer(exist, context={"request": request}).data)
            session = ChatSession.objects.create(type="single", owner=request.user)
            session.members.add(request.user, other)
        else:
            name = str(request.data.get("name") or "未命名群聊").strip()
            session = ChatSession.objects.create(type="group", name=name, owner=request.user,
                                                 announcement=request.data.get("announcement", ""))
            session.members.add(request.user)
            users = User.objects.filter(id__in=member_ids)
            session.members.add(*users)
            send_to_session(session.id, {
                "type": "group.system",
                "data": {"content": f"{request.user.display_name} 创建了群聊「{name}」", "session_id": session.id},
            })
        return Response(SessionSerializer(session, context={"request": request}).data, status=201)


class SessionDetailView(APIView):
    """会话详情 / 更新群信息"""

    def _get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        return s

    def get(self, request, pk):
        s = self._get(request, pk)
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        return Response(SessionSerializer(s, context={"request": request}).data)

    def patch(self, request, pk):
        s = self._get(request, pk)
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type == "group" and s.owner_id != request.user.id:
            return Response({"message": "仅群主可修改群信息"}, status=403)
        for f in ("name", "announcement", "avatar"):
            if f in request.data:
                setattr(s, f, request.data[f])
        s.save()
        broadcast_session(s.id, {"type": "session.updated", "data": {"session_id": s.id}})
        return Response(SessionSerializer(s, context={"request": request}).data)


class SessionMemberView(APIView):
    """添加 / 移除群成员"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type != "group":
            return Response({"message": "单聊不能添加成员"}, status=400)
        # 群主校验：仅群主可邀请成员（原来任意成员都能拉人）
        if s.owner_id != request.user.id:
            return Response({"message": "仅群主可邀请成员"}, status=403)
        raw_ids = request.data.get("member_ids") or []
        if not isinstance(raw_ids, (list, tuple)):
            return Response({"message": "member_ids 必须是数组"}, status=400)
        if len(raw_ids) > 50:
            return Response({"message": "单次最多邀请 50 人"}, status=400)
        try:
            ids = {as_int(x, field="member_ids") for x in raw_ids}
        except ValidationError as exc:
            return Response({"message": "member_ids 必须全部为整数"}, status=400)
        users = list(User.objects.filter(id__in=ids))
        # 去重：已在群内的不再重复添加（系统消息数量也才准确）
        existing = set(s.members.values_list("id", flat=True))
        fresh = [u for u in users if u.id not in existing]
        if not fresh:
            return Response({"message": "没有新成员可添加"})
        with transaction.atomic():
            s.members.add(*fresh)
            for u in fresh:
                _get_setting(s, u)
        send_to_session(s.id, {"type": "group.system",
                               "data": {"content": f"{request.user.display_name} 邀请 {len(fresh)} 人入群"}})
        return Response({"message": f"已添加 {len(fresh)} 名成员"})

    def delete(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        try:
            target_id = as_int(request.query_params.get("user_id"), field="user_id")
        except ValidationError:
            return Response({"message": "user_id 必须是整数"}, status=400)
        if s.owner_id != request.user.id and target_id != request.user.id:
            return Response({"message": "仅群主可移除成员"}, status=403)
        user = User.objects.filter(id=target_id).first()
        if user:
            s.members.remove(user)
            send_to_session(s.id, {"type": "group.system", "data": {"content": f"{user.display_name} 被移出群聊"}})
        return Response({"message": "成员已移除"})


class SessionLeaveView(APIView):
    """退出群聊；群主退出则解散群（或先转让）"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type == "single":
            # 单聊「删除」只对当前用户归档：直接删会话会级联删掉对方的历史消息
            setting = _get_setting(s, request.user)
            setting.is_archived = True
            setting.is_pinned = False
            setting.save(update_fields=["is_archived", "is_pinned"])
            return Response({"message": "会话已从列表移除"})
        if s.owner_id == request.user.id:
            # 群主退出 → 解散群
            send_to_session(s.id, {"type": "group.system", "data": {"content": "群主已解散该群聊"}})
            s.delete()
            return Response({"message": "群聊已解散"})
        s.members.remove(request.user)
        send_to_session(s.id, {"type": "group.system", "data": {"content": f"{request.user.display_name} 退出了群聊"}})
        return Response({"message": "已退出群聊"})


class SessionTransferView(APIView):
    """转让群主"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk).first()
        if not s or s.owner_id != request.user.id:
            return Response({"message": "仅群主可转让"}, status=403)
        try:
            new_owner_id = as_int(request.data.get("user_id"), field="user_id", minimum=1)
        except ValidationError:
            return Response({"message": "user_id 必须是整数"}, status=400)
        new_owner = s.members.filter(id=new_owner_id).first()
        if not new_owner:
            return Response({"message": "新群主必须是群成员"}, status=400)
        s.owner = new_owner
        s.save(update_fields=["owner"])
        send_to_session(s.id, {"type": "group.system", "data": {"content": f"群主已转让给 {new_owner.display_name}"}})
        return Response({"message": "转让成功"})


class SessionSettingView(APIView):
    """成员会话设置：免打扰 / 置顶 / 草稿 / 标记已读"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        changed = []
        for f in ("is_muted", "is_pinned", "is_archived"):
            if f in request.data:
                setattr(setting, f, parse_bool(request.data[f], field=f))
                changed.append(f)
        if "draft" in request.data:
            setting.draft = request.data["draft"]
            changed.append("draft")
        if "tags" in request.data:
            raw = request.data["tags"]
            if not isinstance(raw, (list, tuple)):
                return Response({"message": "tags 必须是数组"}, status=400)
            tags = []
            for t in raw:
                val = str(t or "").strip()[:20]
                if val and val not in tags:
                    tags.append(val)
            setting.tags = tags[:10]
            changed.append("tags")
        if request.data.get("mark_read"):
            setting.last_read_at = timezone.now()
            changed.append("last_read_at")
        setting.save()
        return Response({"message": "设置已更新", "is_muted": setting.is_muted, "is_pinned": setting.is_pinned,
                         "is_archived": setting.is_archived, "draft": setting.draft,
                         "tags": list(setting.tags or [])})


class MessageListView(APIView):
    """消息历史（对自己删除的不返回），支持会话内搜索 / 按发送者 / 时间范围过滤"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        # 置顶消息区（与历史分开返回）
        pinned = list(
            s.messages.filter(is_pinned=True).exclude(deleted_for=request.user)
            .exclude(is_recalled=True).exclude(is_deleted=True).order_by("-created_at")
            .select_related("sender", "reply_to", "reply_to__sender")
        )
        qs = s.messages.exclude(deleted_for=request.user).exclude(is_deleted=True)
        kw = request.query_params.get("q")
        if kw:
            qs = qs.filter(content__icontains=kw)
        msg_type = request.query_params.get("msg_type")
        if msg_type:
            qs = qs.filter(msg_type=msg_type)
        sender = request.query_params.get("sender")
        if sender:
            qs = qs.filter(sender_id=as_int(sender, field="sender"))
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=as_date(date_from, field="date_from"))
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=as_date(date_to, field="date_to"))
        before = request.query_params.get("before")
        if before:
            qs = qs.filter(id__lt=as_int(before, field="before"))
        # B6：sender / reply_to / reply_to.sender 全部 select_related，
        # 避免每条消息 2-3 次 sender 查询
        # B19：total 取过滤后总量（切片前 count）——原来是 len(本页数据)，
        # 命中 50 条上限时恒等于 50，名不副实；前端未消费该字段，改语义零影响
        total = qs.count()
        qs = qs.select_related("sender", "reply_to", "reply_to__sender").order_by("-id")[:50]
        data = ChatMessageSerializer(list(qs)[::-1], many=True, context={"request": request}).data
        pinned_data = ChatMessageSerializer(pinned, many=True, context={"request": request}).data
        return Response({"list": data, "total": total, "pinned": pinned_data})


class MessageCreateView(APIView):
    """发送消息（文本/图片/文件/系统），支持转发"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在或你不在会话中"}, status=404)
        content = request.data.get("content", "")
        msg_type = request.data.get("msg_type", "text")
        # 类型白名单：自由字符串会写进库，前端按类型选渲染器，脏值会渲染异常
        if msg_type not in {t[0] for t in ChatMessage.TYPE_CHOICES}:
            return Response({"message": "msg_type 非法"}, status=400)
        if isinstance(content, str) and len(content) > 20000:
            return Response({"message": "消息内容不能超过 20000 字"}, status=400)
        forward_id = as_int(request.data.get("forward_from"), default=None, field="forward_from") if request.data.get("forward_from") else None
        forward = ChatMessage.objects.filter(id=forward_id, session__members=request.user).first() if forward_id else None
        reply_id = as_int(request.data.get("reply_to"), default=None, field="reply_to") if request.data.get("reply_to") else None
        reply = ChatMessage.objects.filter(id=reply_id, session=s).first() if reply_id else None
        if not content and msg_type == "text" and not forward:
            return Response({"message": "消息内容不能为空"}, status=400)
        msg = ChatMessage.objects.create(
            session=s, sender=request.user, content=content, msg_type=msg_type,
            attachments=request.data.get("attachments", []) or [], forward_from=forward, reply_to=reply,
        )
        # 给已归档会话发消息 = 主动恢复显示
        setting = _get_setting(s, request.user)
        if setting.is_archived:
            setting.is_archived = False
            setting.save(update_fields=["is_archived"])
        send_to_session(s.id, {"type": "chat.message", "data": ChatMessageSerializer(msg, context={"request": request}).data})
        # 非免打扰成员推送通知
        muted_ids = set(SessionMemberSetting.objects.filter(session=s, is_muted=True).values_list("user_id", flat=True))
        for u in s.members.exclude(id=request.user.id):
            if u.id not in muted_ids:
                from core.models import notify
                notify(u, f"新消息：{request.user.display_name}", content[:80], category="message", link=f"/im/{s.id}")
        # 关键词提醒：对命中关键词的成员额外推送一条醒目通知
        if msg_type == "text" and content:
            _fire_keyword_alerts(s, msg)
            _fire_mentions(s, msg)
        return Response(ChatMessageSerializer(msg, context={"request": request}).data, status=201)


def _fire_keyword_alerts(session, msg):
    """对会话内配置了关键词提醒的成员，若消息内容命中其关键词则推送通知中心"""
    from core.models import notify

    content_lower = msg.content.lower()
    for setting in KeywordAlert.objects.filter(owner__in=session.members.all()):
        if setting.owner_id == msg.sender_id:
            continue
        hits = [kw for kw in (setting.keywords or []) if kw and kw.lower() in content_lower]
        if hits:
            notify(
                setting.owner,
                f"关键词提醒：{', '.join(hits[:3])}",
                f"来自 {msg.sender.display_name if msg.sender else '某人'}：{msg.content[:100]}",
                category="message",
                level="warning",
                link=f"/im/{session.id}",
            )


def _mentioned_users(session, content):
    """F607 解析消息中的 @提及：返回被提及的会话成员列表"""
    if not content or "@" not in content:
        return []
    mentioned = []
    for u in session.members.all():
        name = u.display_name
        if name and f"@{name}" in content:
            mentioned.append(u)
    return mentioned


def _fire_mentions(session, msg):
    """F607 对被 @提及的成员推送通知中心消息"""
    from core.models import notify

    content = msg.content or ""
    if "@所有人" in content or "@all" in content.lower():
        for u in session.members.exclude(id=msg.sender_id):
            notify(u, f"{msg.sender.display_name if msg.sender else '某人'} 在「{session.name or '会话'}」提到了所有人",
                   content[:100], category="message", level="warning", link=f"/im/{session.id}")
        return
    for u in _mentioned_users(session, content):
        if u.id == msg.sender_id:
            continue
        notify(u, f"{msg.sender.display_name if msg.sender else '某人'} 在「{session.name or '会话'}」提到了你",
               content[:100], category="message", level="warning", link=f"/im/{session.id}")


class MessageRecallView(APIView):
    """撤回消息（发送者，2 分钟内）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        if msg.sender_id != request.user.id:
            return Response({"message": "只能撤回自己的消息"}, status=403)
        if timezone.now() - msg.created_at > timezone.timedelta(minutes=2):
            return Response({"message": "超过 2 分钟不可撤回"}, status=400)
        msg.is_recalled = True
        msg.save(update_fields=["is_recalled"])
        send_to_session(msg.session_id, {"type": "message.recalled", "data": {"id": msg.id, "session_id": msg.session_id}})
        return Response({"message": "消息已撤回"})


class MessageDeleteView(APIView):
    """删除消息（仅对自己隐藏）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        msg.deleted_for.add(request.user)
        return Response({"message": "已删除"})


class MessageForwardView(APIView):
    """转发消息到其它会话"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        target_ids = request.data.get("session_ids") or []
        created = []
        for sid in target_ids:
            target = ChatSession.objects.filter(id=sid, members=request.user).first()
            if not target:
                continue
            new_msg = ChatMessage.objects.create(
                session=target, sender=request.user, content=msg.content, msg_type=msg.msg_type,
                attachments=msg.attachments, forward_from=msg,
            )
            send_to_session(target.id, {"type": "chat.message", "data": ChatMessageSerializer(new_msg).data})
            created.append(new_msg.id)
        return Response({"message": f"已转发到 {len(created)} 个会话", "message_ids": created})


class GlobalMessageSearchView(APIView):
    """跨全部会话搜索消息，支持按发送者 / 时间范围过滤"""

    def get(self, request):
        kw = (request.query_params.get("q") or "").strip()
        qs = ChatMessage.objects.filter(session__members=request.user).exclude(deleted_for=request.user)
        if kw:
            qs = qs.filter(content__icontains=kw)
        sender = request.query_params.get("sender")
        if sender:
            qs = qs.filter(sender_id=as_int(sender, field="sender"))
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=as_date(date_from, field="date_from"))
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=as_date(date_to, field="date_to"))
        msg_type = (request.query_params.get("msg_type") or "").strip()
        if msg_type:
            qs = qs.filter(msg_type=msg_type)
        has_attachment = request.query_params.get("has_attachment")
        if has_attachment not in (None, ""):
            if parse_bool(has_attachment, field="has_attachment"):
                qs = qs.exclude(attachments=[])
            else:
                qs = qs.filter(attachments=[])
        if not kw and not sender and not date_from and not date_to and not msg_type \
                and has_attachment in (None, ""):
            return Response({"list": [], "total": 0})
        qs = qs.order_by("-id")[:100]
        data = []
        for m in qs:
            d = ChatMessageSerializer(m, context={"request": request}).data
            d["session_name"] = m.session.name or "单聊"
            data.append(d)
        return Response({"list": data, "total": len(data)})


class UnreadSummaryView(APIView):
    """未读消息汇总（免打扰会话单独计数）"""

    def get(self, request):
        # B6：原来每个会话 2 次查询（setting + COUNT）；现在未读数由一条
        # 带相关子查询的注解算出，设置一次批量取出
        sessions = _with_unread(_member_sessions(request.user), request.user)
        settings = {
            s.session_id: s for s in SessionMemberSetting.objects.filter(user=request.user)
        }
        total, muted_total, per_session = 0, 0, {}
        for s in sessions:
            n = s.unread_count or 0
            per_session[s.id] = n
            setting = settings.get(s.id)
            if setting and setting.is_muted:
                muted_total += n
            else:
                total += n
        return Response({"unread": total, "muted_unread": muted_total, "per_session": per_session})


# ============ 消息置顶 ============

class MessagePinView(APIView):
    """置顶 / 取消置顶一条消息（会话成员均可操作）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        msg.is_pinned = not msg.is_pinned
        msg.save(update_fields=["is_pinned"])
        send_to_session(msg.session_id, {
            "type": "message.pinned",
            "data": {"id": msg.id, "session_id": msg.session_id, "is_pinned": msg.is_pinned},
        })
        return Response({"message": "已置顶" if msg.is_pinned else "已取消置顶", "is_pinned": msg.is_pinned})


# ============ 快捷回复模板 ============

class QuickReplyListView(APIView):
    def get(self, request):
        qs = QuickReply.objects.filter(owner=request.user)
        return Response({"list": QuickReplySerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        content = str(request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "内容不能为空"}, status=400)
        qr = QuickReply.objects.create(
            owner=request.user, title=str(request.data.get("title") or "")[:120], content=content
        )
        return Response(QuickReplySerializer(qr).data, status=201)


class QuickReplyDetailView(APIView):
    def _get(self, request, pk):
        return QuickReply.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        qr = self._get(request, pk)
        if not qr:
            return Response({"message": "模板不存在"}, status=404)
        for f in ("title", "content"):
            if f in request.data:
                setattr(qr, f, str(request.data[f] or ""))
        qr.save()
        return Response(QuickReplySerializer(qr).data)

    def delete(self, request, pk):
        qr = self._get(request, pk)
        if not qr:
            return Response({"message": "模板不存在"}, status=404)
        qr.delete()
        return Response({"message": "已删除"})


# ============ 关键词提醒 ============

class KeywordAlertView(APIView):
    """读取 / 保存我的关键词提醒列表（整体覆盖）"""

    def get(self, request):
        obj = KeywordAlert.objects.filter(owner=request.user).first()
        return Response({"keywords": obj.keywords if obj else []})

    def post(self, request):
        keywords = request.data.get("keywords")
        if not isinstance(keywords, list):
            return Response({"message": "keywords 必须是数组"}, status=400)
        cleaned = [str(k).strip()[:32] for k in keywords if str(k).strip()][:50]
        obj, _ = KeywordAlert.objects.update_or_create(owner=request.user, defaults={"keywords": cleaned})
        return Response({"keywords": obj.keywords})


# ===========================================================================
# IM 增强 F599–F612（纯新增，不改动上方既有接口）
# ===========================================================================

class MessageEditView(APIView):
    """F599 消息编辑：发送者 10 分钟内可编辑，标记 edited"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        if msg.sender_id != request.user.id:
            return Response({"message": "只能编辑自己的消息"}, status=403)
        if msg.is_recalled or msg.is_deleted:
            return Response({"message": "该消息不可编辑"}, status=400)
        if timezone.now() - msg.created_at > timezone.timedelta(minutes=10):
            return Response({"message": "超过 10 分钟不可编辑"}, status=400)
        content = str(request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "消息内容不能为空"}, status=400)
        msg.content = content
        msg.edited = True
        msg.edited_at = timezone.now()
        msg.save(update_fields=["content", "edited", "edited_at"])
        data = ChatMessageSerializer(msg, context={"request": request}).data
        send_to_session(msg.session_id, {"type": "message.edited", "data": data})
        return Response(data)


class MessageDeleteForAllView(APIView):
    """F600 消息删除并双端同步（发送者或群主）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        is_owner = msg.session.type == "group" and msg.session.owner_id == request.user.id
        if msg.sender_id != request.user.id and not is_owner:
            return Response({"message": "只能删除自己发送的消息"}, status=403)
        msg.is_deleted = True
        msg.save(update_fields=["is_deleted"])
        send_to_session(msg.session_id, {
            "type": "message.deleted",
            "data": {"id": msg.id, "session_id": msg.session_id, "deleted_for_all": True},
        })
        return Response({"message": "消息已删除", "id": msg.id, "is_deleted": True})


class SessionDraftView(APIView):
    """F601 按会话保存草稿"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        return Response({"session_id": s.id, "draft": setting.draft or "",
                         "updated_at": setting.draft_updated_at})

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        setting.draft = request.data.get("draft", "")
        setting.draft_updated_at = timezone.now()
        setting.save(update_fields=["draft", "draft_updated_at"])
        return Response({"message": "草稿已保存", "session_id": s.id, "draft": setting.draft,
                         "updated_at": setting.draft_updated_at})

    def delete(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        setting.draft = ""
        setting.draft_updated_at = None
        setting.save(update_fields=["draft", "draft_updated_at"])
        return Response({"message": "草稿已清空", "session_id": s.id, "draft": ""})


class TodoListView(APIView):
    """F602 稍后处理清单：列表 / 新增"""

    def get(self, request):
        qs = TodoItem.objects.filter(owner=request.user)
        if request.query_params.get("status") == "open":
            qs = qs.filter(is_done=False)
        return Response({"list": TodoItemSerializer(qs, many=True).data,
                         "total": qs.count(),
                         "open": qs.filter(is_done=False).count()})

    def post(self, request):
        try:
            message_id = as_int(request.data.get("message_id"), default=None, field="message_id", minimum=1)
        except ValidationError:
            return Response({"message": "message_id 必须是整数"}, status=400)
        msg = ChatMessage.objects.filter(id=message_id, session__members=request.user).first() if message_id else None
        content = str(request.data.get("content") or (msg.content if msg else "") or "").strip()
        if not content:
            return Response({"message": "内容不能为空"}, status=400)
        try:
            remind_at = as_datetime(request.data.get("remind_at"), field="remind_at") if request.data.get("remind_at") else None
        except ValidationError:
            return Response({"message": "remind_at 必须是合法日期时间"}, status=400)
        item = TodoItem.objects.create(
            owner=request.user,
            session=msg.session if msg else None,
            message=msg,
            content=content[:500],
            remind_at=remind_at,
        )
        return Response(TodoItemSerializer(item).data, status=201)


class TodoDetailView(APIView):
    """F602 稍后处理清单：完成 / 删除"""

    def _get(self, request, pk):
        return TodoItem.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        item = self._get(request, pk)
        if not item:
            return Response({"message": "条目不存在"}, status=404)
        if "is_done" in request.data:
            item.is_done = parse_bool(request.data["is_done"], field="is_done")
        if "content" in request.data and str(request.data["content"] or "").strip():
            item.content = str(request.data["content"]).strip()[:500]
        if "remind_at" in request.data:
            raw = request.data["remind_at"]
            if not raw:
                item.remind_at = None
            else:
                try:
                    item.remind_at = as_datetime(raw, field="remind_at")
                except ValidationError:
                    return Response({"message": "remind_at 必须是合法日期时间"}, status=400)
        item.save()
        return Response(TodoItemSerializer(item).data)

    def delete(self, request, pk):
        item = self._get(request, pk)
        if not item:
            return Response({"message": "条目不存在"}, status=404)
        item.delete()
        return Response({"message": "已删除"})


class SessionMuteView(APIView):
    """F603 单会话免打扰开关"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        if "is_muted" in request.data:
            setting.is_muted = parse_bool(request.data["is_muted"], field="is_muted")
        else:
            setting.is_muted = not setting.is_muted
        setting.save(update_fields=["is_muted"])
        return Response({"message": "已开启免打扰" if setting.is_muted else "已关闭免打扰",
                         "session_id": s.id, "is_muted": setting.is_muted})


class SessionTypingView(APIView):
    """F604 正在输入状态：上报 / 查询（8 秒内有效）"""

    WINDOW_SECONDS = 8

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = _get_setting(s, request.user)
        setting.typing_at = timezone.now()
        setting.save(update_fields=["typing_at"])
        broadcast_session(s.id, {"type": "session.typing", "data": {
            "session_id": s.id, "user_id": request.user.id,
            "display_name": request.user.display_name,
        }})
        return Response({"message": "ok", "session_id": s.id})

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        since = timezone.now() - timezone.timedelta(seconds=self.WINDOW_SECONDS)
        typing = SessionMemberSetting.objects.filter(
            session=s, typing_at__gte=since
        ).exclude(user=request.user).select_related("user")
        return Response({"session_id": s.id, "typing": [
            {"user_id": t.user_id, "display_name": t.user.display_name} for t in typing
        ]})


class SessionPinnedView(APIView):
    """F605 置顶消息管理：列表 / 取消置顶"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        qs = s.messages.filter(is_pinned=True).exclude(is_deleted=True)
        return Response({"session_id": s.id,
                         "list": ChatMessageSerializer(qs, many=True, context={"request": request}).data,
                         "total": qs.count()})


class SessionPinnedDetailView(APIView):
    """F605 取消某条消息置顶"""

    def delete(self, request, pk, msg_id):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        msg = s.messages.filter(id=msg_id, is_pinned=True).first()
        if not msg:
            return Response({"message": "置顶消息不存在"}, status=404)
        msg.is_pinned = False
        msg.save(update_fields=["is_pinned"])
        send_to_session(s.id, {"type": "message.pinned",
                               "data": {"id": msg.id, "session_id": s.id, "is_pinned": False}})
        return Response({"message": "已取消置顶", "id": msg.id, "is_pinned": False})


class SessionAnnouncementView(APIView):
    """F606 群公告：读取 / 设置（仅群主可设置）"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        return Response({"session_id": s.id, "announcement": s.announcement or ""})

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        if s.type != "group":
            return Response({"message": "单聊没有群公告"}, status=400)
        if s.owner_id != request.user.id:
            return Response({"message": "仅群主可发布公告"}, status=403)
        s.announcement = str(request.data.get("announcement") or "")[:500]
        s.save(update_fields=["announcement"])
        broadcast_session(s.id, {"type": "session.updated", "data": {"session_id": s.id}})
        return Response({"message": "公告已更新", "session_id": s.id, "announcement": s.announcement})


class MentionsView(APIView):
    """F607 我收到的 @提及消息列表"""

    def get(self, request):
        name = request.user.display_name
        result = []
        if name:
            qs = ChatMessage.objects.filter(
                session__members=request.user, content__icontains=f"@{name}"
            ).exclude(sender=request.user).exclude(is_deleted=True).order_by("-id")[:100]
            for m in qs:
                d = ChatMessageSerializer(m, context={"request": request}).data
                d["session_name"] = m.session.name or "单聊"
                result.append(d)
        return Response({"list": result, "total": len(result)})


class FavoriteListView(APIView):
    """F608 消息收藏夹：列表 / 收藏或取消收藏"""

    def get(self, request):
        qs = MessageFavorite.objects.filter(owner=request.user).select_related("message")
        return Response({"list": MessageFavoriteSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        try:
            message_id = as_int(request.data.get("message_id"), field="message_id", minimum=1)
        except ValidationError:
            return Response({"message": "message_id 必须是整数"}, status=400)
        msg = ChatMessage.objects.filter(id=message_id, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        fav = MessageFavorite.objects.filter(owner=request.user, message=msg).first()
        if fav:
            fav.delete()
            return Response({"message": "已取消收藏", "favorited": False})
        fav = MessageFavorite.objects.create(owner=request.user, message=msg,
                                             note=str(request.data.get("note") or "")[:200])
        return Response({"message": "已收藏", "favorited": True,
                         "item": MessageFavoriteSerializer(fav).data}, status=201)


class FavoriteDetailView(APIView):
    """F608 删除收藏"""

    def delete(self, request, pk):
        fav = MessageFavorite.objects.filter(pk=pk, owner=request.user).first()
        if not fav:
            return Response({"message": "收藏不存在"}, status=404)
        fav.delete()
        return Response({"message": "已删除收藏"})


# F609 本地词典（无外部密钥即可降级运行）
_TRANS_DICT_ZH_EN = {
    "你好": "hello", "谢谢": "thank you", "再见": "goodbye", "好的": "ok", "收到": "received",
    "项目": "project", "任务": "task", "看板": "board", "卡片": "card", "会议": "meeting",
    "今天": "today", "明天": "tomorrow", "昨天": "yesterday", "完成": "done", "进行中": "in progress",
    "待办": "todo", "负责人": "assignee", "截止日期": "due date", "优先级": "priority",
    "问题": "issue", "需求": "requirement", "文档": "document", "测试": "test", "上线": "release",
    "请": "please", "尽快": "as soon as possible", "确认": "confirm", "安排": "schedule",
}
_TRANS_DICT_EN_ZH = {v: k for k, v in _TRANS_DICT_ZH_EN.items()}


def _local_translate(text, target_lang):
    """本地词典降级翻译：按词/短语替换，未命中保留原文"""
    text = text or ""
    if target_lang.startswith("en"):
        table = _TRANS_DICT_ZH_EN
    else:
        table = _TRANS_DICT_EN_ZH
    matched = 0
    out = text
    for src in sorted(table.keys(), key=len, reverse=True):
        if src in out:
            out = out.replace(src, table[src])
            matched += 1
    return out, matched


class MessageTranslateView(APIView):
    """F609 消息翻译（本地词典降级，无密钥也能出结果）"""

    def post(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        target = (request.data.get("target_lang") or "en").lower()
        original = msg.content or ""
        translated, matched = _local_translate(original, target)
        source = "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in original) else "en"
        return Response({
            "message_id": msg.id, "source_lang": source, "target_lang": target,
            "original": original, "translated": translated,
            "engine": "local-dict", "matched": matched, "fallback": matched == 0,
        })


class SessionStatsView(APIView):
    """F610 会话统计：发言数 / 时段分布 / 类型分布"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        msgs = list(s.messages.exclude(is_deleted=True))
        total = len(msgs)
        by_member = {}
        hour_dist = [0] * 24
        by_type = {}
        days = set()
        for m in msgs:
            key = m.sender.display_name if m.sender else "系统"
            by_member[key] = by_member.get(key, 0) + 1
            local = timezone.localtime(m.created_at)
            hour_dist[local.hour] += 1
            by_type[m.msg_type] = by_type.get(m.msg_type, 0) + 1
            days.add(local.date())
        members_sorted = sorted(by_member.items(), key=lambda kv: kv[1], reverse=True)
        first = msgs[0].created_at if msgs else None
        last = msgs[-1].created_at if msgs else None
        return Response({
            "session_id": s.id, "total": total,
            "member_count": s.members.count(),
            "by_member": [{"name": n, "count": c} for n, c in members_sorted],
            "by_type": by_type, "hour_distribution": hour_dist,
            "active_days": len(days),
            "first_message_at": first, "last_message_at": last,
        })


class SessionExportView(APIView):
    """F611 会话导出 Markdown"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        msgs = s.messages.exclude(is_deleted=True).exclude(deleted_for=request.user).order_by("created_at")
        lines = [f"# {s.name or '单聊会话'}", ""]
        lines.append(f"> 导出时间：{timezone.localtime(timezone.now()):%Y-%m-%d %H:%M}")
        lines.append(f"> 成员：{'、'.join(u.display_name for u in s.members.all())}")
        if s.announcement:
            lines.append(f"> 群公告：{s.announcement}")
        lines.append("")
        lines.append("---")
        lines.append("")
        count = 0
        for m in msgs:
            ts = timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M")
            who = m.sender.display_name if m.sender else "系统"
            body = "[图片]" if m.msg_type == "image" else ("[文件]" if m.msg_type == "file" else m.content)
            if m.is_recalled:
                body = "[已撤回]"
            suffix = "（已编辑）" if m.edited else ""
            lines.append(f"**{who}** · {ts}{suffix}")
            lines.append("")
            lines.append(body or "")
            lines.append("")
            count += 1
        markdown = "\n".join(lines)
        return Response({
            "session_id": s.id, "name": s.name or "单聊",
            "filename": f"chat-{s.id}.md", "count": count,
            "markdown": markdown, "length": len(markdown),
        })


class SessionUnreadLineView(APIView):
    """F612 未读分隔线与跳转：返回首条未读消息及上下文"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        setting = SessionMemberSetting.objects.filter(session=s, user=request.user).first()
        qs = s.messages.exclude(deleted_for=request.user).exclude(is_deleted=True).exclude(sender=request.user)
        if setting and setting.last_read_at:
            unread = qs.filter(created_at__gt=setting.last_read_at)
        else:
            unread = qs
        first_unread = unread.order_by("id").first()
        if not first_unread:
            return Response({"session_id": s.id, "has_unread": False, "unread_count": 0,
                             "first_unread_id": None, "context": []})
        context = list(s.messages.filter(id__gte=first_unread.id).exclude(deleted_for=request.user)
                       .exclude(is_deleted=True).order_by("id")[:20])
        return Response({
            "session_id": s.id, "has_unread": True, "unread_count": unread.count(),
            "first_unread_id": first_unread.id,
            "context": ChatMessageSerializer(context, many=True, context={"request": request}).data,
        })


class MessageReadersView(APIView):
    """F26 已读回执详情：发送者 / 群主可查看谁已读、谁未读"""

    def get(self, request, pk):
        msg = ChatMessage.objects.filter(id=pk, session__members=request.user).first()
        if not msg:
            return Response({"message": "消息不存在"}, status=404)
        session = msg.session
        can_view = (
            msg.sender_id == request.user.id
            or (session.type == "group" and session.owner_id == request.user.id)
        )
        if not can_view:
            return Response({"message": "仅发送者或群主可查看已读详情"}, status=403)
        settings = {
            s.user_id: s.last_read_at
            for s in SessionMemberSetting.objects.filter(session=session)
        }
        readers, unreaders = [], []
        for u in session.members.exclude(id=msg.sender_id):
            last_read = settings.get(u.id)
            row = {"id": u.id, "display_name": u.display_name,
                   "avatar": u.avatar.url if u.avatar else ""}
            if last_read and last_read >= msg.created_at:
                readers.append(row)
            else:
                unreaders.append(row)
        return Response({
            "message_id": msg.id, "session_id": session.id,
            "read": len(readers), "unread": len(unreaders),
            "readers": readers, "unreaders": unreaders,
        })
