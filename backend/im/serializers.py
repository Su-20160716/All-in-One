"""IM 序列化"""
from django.utils import timezone
from rest_framework import serializers

from im.models import ChatMessage, ChatSession, MessageFavorite, QuickReply, SessionMemberSetting, TodoItem


def _has_prefetch(obj, name):
    """B6：判断 related manager 是否已被 prefetch_related 预取"""
    cache = getattr(obj, "_prefetched_objects_cache", None)
    return bool(cache) and name in cache


def _materialize(instance):
    """many=True 时 DRF 传入的是 QuerySet；先物化，预取逻辑才拿得到每条记录"""
    if instance is None:
        return []
    if isinstance(instance, (list, tuple)):
        return list(instance)
    if hasattr(instance, "__iter__") and not isinstance(instance, (str, bytes, dict)):
        try:
            return list(instance)
        except TypeError:
            return [instance]
    return [instance]


class QuickReplySerializer(serializers.ModelSerializer):
    class Meta:
        model = QuickReply
        fields = ["id", "title", "content", "sort_order", "group", "created_at"]
        read_only_fields = ["owner"]


class TodoItemSerializer(serializers.ModelSerializer):
    session_name = serializers.SerializerMethodField()

    class Meta:
        model = TodoItem
        fields = ["id", "session", "session_name", "message", "content", "is_done", "remind_at", "created_at"]
        read_only_fields = ["owner"]

    def get_session_name(self, obj):
        return obj.session.name if obj.session else ""


class MessageFavoriteSerializer(serializers.ModelSerializer):
    message_info = serializers.SerializerMethodField()

    class Meta:
        model = MessageFavorite
        fields = ["id", "message", "message_info", "note", "created_at"]
        read_only_fields = ["owner"]

    def get_message_info(self, obj):
        m = obj.message
        if not m:
            return None
        return {
            "id": m.id, "session_id": m.session_id, "msg_type": m.msg_type,
            "content": "消息已撤回" if m.is_recalled else m.content,
            "sender_name": m.sender.display_name if m.sender else "系统",
            "created_at": m.created_at,
        }


class ReplyToSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True, default="系统")

    class Meta:
        model = ChatMessage
        fields = ["id", "sender", "sender_name", "msg_type", "content", "is_recalled"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_recalled:
            data["content"] = "消息已撤回"
        return data


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True, default="系统")
    sender_avatar = serializers.SerializerMethodField()
    reply_to_info = serializers.SerializerMethodField()
    read_by_count = serializers.SerializerMethodField()
    read_by_me = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id", "session", "sender", "sender_name", "sender_avatar", "msg_type",
            "content", "attachments", "forward_from", "reply_to", "reply_to_info",
            "is_pinned", "is_recalled", "is_deleted", "edited", "edited_at",
            "can_edit", "read_by_count", "read_by_me", "created_at",
        ]
        read_only_fields = ["sender"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # B6：消息列表场景按 session 批量取成员与已读设置，
        # 原来每条消息 3 次查询（members / settings / my-setting），
        # 50 条消息 = 150+ 次，现在整批 2 次
        self._session_members = {}
        self._session_settings = {}
        instances = _materialize(self.instance)
        sids = list({m.session_id for m in instances if getattr(m, "session_id", None)})
        if sids:
            for sid, uid in ChatSession.objects.filter(id__in=sids).values_list("id", "members__id"):
                self._session_members.setdefault(sid, []).append(uid)
            for s in SessionMemberSetting.objects.filter(session_id__in=sids):
                self._session_settings.setdefault(s.session_id, {})[s.user_id] = s.last_read_at

    def get_sender_avatar(self, obj):
        if obj.sender and obj.sender.avatar:
            return obj.sender.avatar.url
        return ""

    def get_reply_to_info(self, obj):
        r = obj.reply_to
        if not r:
            return None
        return {
            "id": r.id,
            "sender_name": r.sender.display_name if r.sender else "系统",
            # #42：引用消息已撤回时也不能泄露原文
            "content": "消息已撤回" if r.is_recalled else (r.content or "")[:120],
            "is_recalled": r.is_recalled,
        }

    def _read_count(self, obj):
        members = self._session_members.get(obj.session_id)
        if members is None:
            members = list(obj.session.members.values_list("id", flat=True))
        settings = self._session_settings.get(obj.session_id)
        if settings is None:
            settings = {
                s.user_id: s.last_read_at
                for s in SessionMemberSetting.objects.filter(session=obj.session)
            }
        total = 0
        for uid in members:
            if uid == obj.sender_id:
                continue
            lr = settings.get(uid)
            if lr and lr >= obj.created_at:
                total += 1
        return total

    def get_read_by_count(self, obj):
        return self._read_count(obj)

    def get_read_by_me(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        settings = self._session_settings.get(obj.session_id)
        if settings is None:
            s = SessionMemberSetting.objects.filter(session=obj.session, user=request.user).first()
            return bool(s and s.last_read_at and s.last_read_at >= obj.created_at)
        lr = settings.get(request.user.id)
        return bool(lr and lr >= obj.created_at)

    def get_can_edit(self, obj):
        # #306：编辑入口的可用性（本人 + 10 分钟内 + 未撤回未删除），口径与 MessageEditView 一致
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if not user or not user.is_authenticated or obj.sender_id != user.id:
            return False
        if obj.is_recalled or obj.is_deleted:
            return False
        return timezone.now() - obj.created_at <= timezone.timedelta(minutes=10)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # #42：撤回消息保留 is_recalled 标记，但绝不输出原始内容/附件
        if instance.is_recalled:
            data["content"] = "消息已撤回"
            data["attachments"] = []
        return data


class SessionSerializer(serializers.ModelSerializer):
    members_info = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()
    is_muted = serializers.SerializerMethodField()
    mute_until = serializers.SerializerMethodField()
    is_pinned = serializers.SerializerMethodField()
    pin_order = serializers.SerializerMethodField()
    is_archived = serializers.SerializerMethodField()
    draft = serializers.SerializerMethodField()
    draft_summary = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    announcement_unread = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = [
            "id", "name", "type", "members", "members_info", "owner", "announcement",
            "avatar", "member_count", "last_message", "unread", "is_muted", "mute_until",
            "is_pinned", "pin_order", "is_archived", "draft", "draft_summary", "tags",
            "announcement_unread", "created_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # B6：原来 is_muted/is_pinned/is_archived/draft/unread 五个字段各查一次
        # 同一行 SessionMemberSetting（每会话 5 次），列表场景一次性批量取出
        self._settings_map = None
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user is not None and user.is_authenticated:
            instances = _materialize(self.instance)
            ids = [s.id for s in instances if getattr(s, "id", None)]
            if ids:
                self._settings_map = {
                    s.session_id: s
                    for s in SessionMemberSetting.objects.filter(user=user, session_id__in=ids)
                }

    def _setting(self, obj):
        if self._settings_map is not None:
            return self._settings_map.get(obj.id)
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
        if _has_prefetch(obj, "members"):
            return len(obj.members.all())
        return obj.members.count()

    def get_last_message(self, obj):
        # B6：视图可用 Prefetch(..., to_attr="_last_messages") 预取最后一条；
        # 无预取时保持原查询行为
        cached = getattr(obj, "_last_messages", None)
        if cached is not None:
            msg = cached[0] if cached else None
        else:
            msg = obj.messages.exclude(is_recalled=True).order_by("-created_at").first()
        if not msg:
            return None
        if msg.is_recalled:
            return None
        return {"id": msg.id, "content": msg.content, "msg_type": msg.msg_type, "created_at": msg.created_at,
                "sender_name": msg.sender.display_name if msg.sender else "系统"}

    def get_unread(self, obj):
        # 列表场景由视图注解 unread_count（单条 SQL），无需逐会话 COUNT
        cached = getattr(obj, "unread_count", None)
        if cached is not None:
            return cached
        request = self.context.get("request")
        if not request:
            return 0
        setting = self._setting(obj)
        qs = (
            obj.messages.exclude(sender=request.user)
            .exclude(is_deleted=True)
            .exclude(is_recalled=True)
            .exclude(deleted_for=request.user)
        )
        if setting and setting.last_read_at:
            return qs.filter(created_at__gt=setting.last_read_at).count()
        return qs.count()

    def get_is_muted(self, obj):
        # #326：mute_until 到期后按未静音处理（免打扰自动恢复）
        s = self._setting(obj)
        if not s or not s.is_muted:
            return False
        return not s.mute_until or s.mute_until > timezone.now()

    def get_mute_until(self, obj):
        s = self._setting(obj)
        return s.mute_until if s else None

    def get_is_pinned(self, obj):
        s = self._setting(obj)
        return s.is_pinned if s else False

    def get_pin_order(self, obj):
        s = self._setting(obj)
        return s.pin_order if s else 0

    def get_is_archived(self, obj):
        s = self._setting(obj)
        return s.is_archived if s else False

    def get_draft(self, obj):
        s = self._setting(obj)
        return s.draft if s else ""

    def get_draft_summary(self, obj):
        # #316：列表项草稿摘要（截断 50 字、换行折叠为空格），取自已批量查询的设置行
        s = self._setting(obj)
        if not s or not s.draft:
            return ""
        return " ".join(s.draft.split())[:50]

    def get_announcement_unread(self, obj):
        # #317：公告未读 = 公告有更新时间且本人已读时间早于它
        if not obj.announcement_updated_at:
            return False
        s = self._setting(obj)
        return not s or not s.announcement_read_at or s.announcement_read_at < obj.announcement_updated_at

    def get_tags(self, obj):
        s = self._setting(obj)
        return list(s.tags or []) if s else []
