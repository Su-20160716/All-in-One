# -*- coding: utf-8 -*-
"""assistant 路由：/api/assistant/"""
from django.urls import path

from assistant import views as v

urlpatterns = [
    path("status/", v.AIStatusView.as_view(), name="ai-status"),
    # 笔记 AI 问答 / 摘要
    path("notes/<int:pk>/summarize/", v.NoteSummarizeView.as_view(), name="ai-note-summarize"),
    path("notes/<int:pk>/ask/", v.NoteAskView.as_view(), name="ai-note-ask"),
    path("ask/", v.AssistantAskView.as_view(), name="ai-ask"),
    # 聊天助手
    path("chat/", v.ChatView.as_view(), name="ai-chat"),
    path("conversations/", v.ConversationListView.as_view(), name="ai-conversations"),
    path("conversations/<int:pk>/", v.ConversationDetailView.as_view(), name="ai-conversation-detail"),
    # 出题 / 批改
    path("questions/generate/", v.QuestionGenerateView.as_view(), name="ai-generate-questions"),
    path("questions/", v.GeneratedQuestionListView.as_view(), name="ai-question-list"),
    path("grade/", v.GradeView.as_view(), name="ai-grade"),
]
