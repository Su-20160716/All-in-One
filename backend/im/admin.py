from django.contrib import admin

from im.models import ChatMessage, ChatSession, SessionMemberSetting, UnreadCounter


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "type", "owner", "created_at"]
    filter_horizontal = ["members"]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ["session", "sender", "msg_type", "is_recalled", "created_at"]


@admin.register(SessionMemberSetting)
class SessionMemberSettingAdmin(admin.ModelAdmin):
    list_display = ["session", "user", "is_muted", "is_pinned", "last_read_at"]


@admin.register(UnreadCounter)
class UnreadCounterAdmin(admin.ModelAdmin):
    list_display = ["user", "session", "count"]
