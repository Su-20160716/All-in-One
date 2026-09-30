"""IM 序列化"""
from rest_framework import serializers

from im.models import ChatMessage, ChatSession, QuickReply, SessionMemberSetting


class QuickReplySerializer(serializers.ModelSerializer):
    class Meta:
        model = QuickReply
        fields = ["id", "title", "content", "sort_order", "created_at"]
        read_only_fields = ["owner"]


class ReplyToSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True, default="系统")

    class Meta:
        model = ChatMessage
        fields = ["id", "sender", "sender_name", "msg_type", "content", "is_recalled"]


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True, default="系统")
    sender_avatar = serializers.SerializerMethodField()
    reply_to_info = serializers.SerializerMethodField()
    read_by_count = serializers.SerializerMethodField()
    read_by_me = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id", "session", "sender", "sender_name", "sender_avatar", "msg_type",
            "content", "attachments", "forward_from", "reply_to", "reply_to_info",
            "is_pinned", "is_recalled", "read_by_count", "read_by_me", "created_at",
        ]
        read_only_fields = ["sender"]

    def get_sender_avatar(self, obj):
        if obj.sender and obj.sender.avatar:
            return obj.sender.avatar.url
        return ""

    def get_reply_to_info(self, obj):
        r = obj.reply_to
        if not r:
            return None
        return {"id": r.id, "sender_name": r.sender.display_name if r.sender else "系统",
                "content": r.content[:120], "is_recalled": r.is_recalled}

    def _read_count(self, obj):
        members = list(obj.session.members.values("id", "username"))
        settings = {
            s.user_id: s.last_read_at
            for s in SessionMemberSetting.objects.filter(session=obj.session)
        }
        total = 0
        for m in members:
            if m["id"] == obj.sender_id:
                continue
            lr = settings.get(m["id"])
            if lr and lr >= obj.created_at:
                total += 1
        return total

    def get_read_by_count(self, obj):
        return self._read_count(obj)

    def get_read_by_me(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        s = SessionMemberSetting.objects.filter(session=obj.session, user=request.user).first()
        return bool(s and s.last_read_at and s.last_read_at >= obj.created_at)


class SessionSerializer(serializers.ModelSerializer):
    members_info = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()
    is_muted = serializers.SerializerMethodField()
    is_pinned = serializers.SerializerMethodField()
    is_archived = serializers.SerializerMethodField()
    draft = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            "id", "name", "type", "members", "members_info", "owner", "announcement",
            "avatar", "member_count", "last_message", "unread", "is_muted", "is_pinned",
            "is_archived", "draft", "created_at",
        ]

    def _setting(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        return SessionMemberSetting.objects.filter(session=obj, user=request.user).first()

    def get_members_info(self, obj):
        return [
            {"id": u.id, "username": u.username, "display_name": u.display_name,
             "avatar": u.avatar.url if u.avatar else ""}
            for u in obj.members.all()
        ]

    def get_member_count(self, obj):
        return obj.members.count()

    def get_last_message(self, obj):
        msg = obj.messages.exclude(is_recalled=True).order_by("-created_at").first()
        if not msg:
            return None
        if msg.is_recalled:
            return None
        return {"id": msg.id, "content": msg.content, "msg_type": msg.msg_type, "created_at": msg.created_at,
                "sender_name": msg.sender.display_name if msg.sender else "系统"}

    def get_unread(self, obj):
        request = self.context.get("request")
        if not request:
            return 0
        setting = SessionMemberSetting.objects.filter(session=obj, user=request.user).first()
        qs = obj.messages.exclude(sender=request.user)
        if setting and setting.last_read_at:
            return qs.filter(created_at__gt=setting.last_read_at).count()
        return qs.count()

    def get_is_muted(self, obj):
        s = self._setting(obj)
        return s.is_muted if s else False

    def get_is_pinned(self, obj):
        s = self._setting(obj)
        return s.is_pinned if s else False

    def get_is_archived(self, obj):
        s = self._setting(obj)
        return s.is_archived if s else False

    def get_draft(self, obj):
        s = self._setting(obj)
        return s.draft if s else ""
