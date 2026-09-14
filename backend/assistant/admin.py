"""AI 助手后台"""
from django.contrib import admin

from assistant.models import AIConversation, AIGeneratedQuestion, AIMessage, AIUsageLog


class AIMessageInline(admin.TabularInline):
    model = AIMessage
    extra = 0


@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "owner", "scene", "model", "message_count", "updated_at")
    search_fields = ("title", "owner__username")
    inlines = [AIMessageInline]


@admin.register(AIGeneratedQuestion)
class AIGeneratedQuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "question_type", "difficulty", "source", "owner", "created_at")
    list_filter = ("question_type", "source", "difficulty")
    search_fields = ("topic", "stem")


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ("id", "feature", "provider", "model", "success", "duration_ms", "owner", "created_at")
    list_filter = ("feature", "provider", "success")
