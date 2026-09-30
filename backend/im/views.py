"""IM 视图：会话管理、成员、成员设置、消息收发、撤回、删除、转发、搜索、未读汇总"""
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from im.models import ChatMessage, ChatSession, KeywordAlert, QuickReply, SessionMemberSetting
from im.serializers import ChatMessageSerializer, QuickReplySerializer, SessionSerializer
from ws_app.events import broadcast_session, send_to_session


def _member_sessions(user):
    return ChatSession.objects.filter(members=user).distinct()


def _get_setting(session, user):
    obj, _ = SessionMemberSetting.objects.get_or_create(session=session, user=user)
    return obj


class SessionListView(APIView):
    """会话列表（置顶优先）/ 创建单聊或群聊"""

    def get(self, request):
        archived = request.query_params.get("archived")
        sessions = list(_member_sessions(request.user))
        data = SessionSerializer(sessions, many=True, context={"request": request}).data
        # 归档过滤：archived=1 仅归档；默认仅未归档
        if archived == "1":
            data = [d for d in data if d["is_archived"]]
        elif archived == "all":
            pass
        else:
            data = [d for d in data if not d["is_archived"]]
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
        member_ids = request.data.get("member_ids") or []
        if stype == "single":
            other_id = member_ids[0] if member_ids else None
            other = User.objects.filter(id=other_id).first()
            if not other:
                return Response({"message": "对方不存在"}, status=400)
            exist = ChatSession.objects.filter(type="single", members=request.user).filter(members=other).first()
            if exist:
                return Response(SessionSerializer(exist, context={"request": request}).data)
            session = ChatSession.objects.create(type="single", owner=request.user)
            session.members.add(request.user, other)
        else:
            name = (request.data.get("name") or "未命名群聊").strip()
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
        ids = request.data.get("member_ids") or []
        users = User.objects.filter(id__in=ids)
        s.members.add(*users)
        for u in users:
            _get_setting(s, u)
        send_to_session(s.id, {"type": "group.system",
                               "data": {"content": f"{request.user.display_name} 邀请 {users.count()} 人入群"}})
        return Response({"message": f"已添加 {users.count()} 名成员"})

    def delete(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        target_id = request.query_params.get("user_id")
        if s.owner_id != request.user.id and str(target_id) != str(request.user.id):
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
            s.delete()
            return Response({"message": "会话已删除"})
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
        new_owner = s.members.filter(id=request.data.get("user_id")).first()
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
                setattr(setting, f, bool(request.data[f]))
                changed.append(f)
        if "draft" in request.data:
            setting.draft = request.data["draft"]
            changed.append("draft")
        if request.data.get("mark_read"):
            setting.last_read_at = timezone.now()
            changed.append("last_read_at")
        setting.save()
        return Response({"message": "设置已更新", "is_muted": setting.is_muted, "is_pinned": setting.is_pinned,
                         "is_archived": setting.is_archived, "draft": setting.draft})


class MessageListView(APIView):
    """消息历史（对自己删除的不返回），支持会话内搜索 / 按发送者 / 时间范围过滤"""

    def get(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在"}, status=404)
        # 置顶消息区（与历史分开返回）
        pinned = list(s.messages.filter(is_pinned=True).exclude(deleted_for=request.user).exclude(is_recalled=True).order_by("-created_at"))
        qs = s.messages.exclude(deleted_for=request.user)
        kw = request.query_params.get("q")
        if kw:
            qs = qs.filter(content__icontains=kw)
        msg_type = request.query_params.get("msg_type")
        if msg_type:
            qs = qs.filter(msg_type=msg_type)
        sender = request.query_params.get("sender")
        if sender:
            qs = qs.filter(sender_id=sender)
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        before = request.query_params.get("before")
        if before:
            qs = qs.filter(id__lt=before)
        qs = qs.order_by("-id")[:50]
        data = ChatMessageSerializer(list(qs)[::-1], many=True, context={"request": request}).data
        pinned_data = ChatMessageSerializer(pinned, many=True, context={"request": request}).data
        return Response({"list": data, "total": len(data), "pinned": pinned_data})


class MessageCreateView(APIView):
    """发送消息（文本/图片/文件/系统），支持转发"""

    def post(self, request, pk):
        s = ChatSession.objects.filter(pk=pk, members=request.user).first()
        if not s:
            return Response({"message": "会话不存在或你不在会话中"}, status=404)
        content = request.data.get("content", "")
        msg_type = request.data.get("msg_type", "text")
        forward_id = request.data.get("forward_from")
        forward = ChatMessage.objects.filter(id=forward_id, session__members=request.user).first() if forward_id else None
        reply_id = request.data.get("reply_to")
        reply = ChatMessage.objects.filter(id=reply_id, session=s).first() if reply_id else None
        if not content and msg_type == "text" and not forward:
            return Response({"message": "消息内容不能为空"}, status=400)
        msg = ChatMessage.objects.create(
            session=s, sender=request.user, content=content, msg_type=msg_type,
            attachments=request.data.get("attachments", []) or [], forward_from=forward, reply_to=reply,
        )
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
            qs = qs.filter(sender_id=sender)
        date_from = request.query_params.get("date_from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        date_to = request.query_params.get("date_to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if not kw and not sender and not date_from and not date_to:
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
        sessions = _member_sessions(request.user)
        total, muted_total, per_session = 0, 0, {}
        for s in sessions:
            setting = SessionMemberSetting.objects.filter(session=s, user=request.user).first()
            qs = s.messages.exclude(sender=request.user)
            if setting and setting.last_read_at:
                qs = qs.filter(created_at__gt=setting.last_read_at)
            n = qs.count()
            per_session[s.id] = n
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
        content = (request.data.get("content") or "").strip()
        if not content:
            return Response({"message": "内容不能为空"}, status=400)
        qr = QuickReply.objects.create(
            owner=request.user, title=request.data.get("title", "")[:120], content=content
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
                setattr(qr, f, request.data[f])
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
