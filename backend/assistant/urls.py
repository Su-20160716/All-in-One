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
    # F645 分支新会话 / F655 导出 Markdown
    path("conversations/<int:pk>/branch/", v.ConversationBranchView.as_view(), name="ai-conversation-branch"),
    path("conversations/<int:pk>/export/", v.ConversationExportView.as_view(), name="ai-conversation-export"),
    # F644 提示词库
    path("prompts/", v.PromptLibraryView.as_view(), name="ai-prompts"),
    path("prompts/<int:pk>/", v.PromptDetailView.as_view(), name="ai-prompt-detail"),
    # F647-F651、F653、F656 创作工具 / F654 快捷指令
    path("translate/", v.TranslateView.as_view(), name="ai-translate"),
    path("names/", v.NameGeneratorView.as_view(), name="ai-names"),
    path("weekly-report/", v.WeeklyReportView.as_view(), name="ai-weekly-report"),
    path("agenda/", v.AgendaView.as_view(), name="ai-agenda"),
    path("email-draft/", v.EmailDraftView.as_view(), name="ai-email-draft"),
    path("social-copy/", v.SocialCopyView.as_view(), name="ai-social-copy"),
    path("math-explain/", v.MathExplainView.as_view(), name="ai-math-explain"),
    path("commands/", v.CommandMenuView.as_view(), name="ai-commands"),
    # F646 输入即时反馈
    path("input-feedback/", v.InputFeedbackView.as_view(), name="ai-input-feedback"),
    # 出题 / 批改
    path("questions/generate/", v.QuestionGenerateView.as_view(), name="ai-generate-questions"),
    path("questions/", v.GeneratedQuestionListView.as_view(), name="ai-question-list"),
    path("grade/", v.GradeView.as_view(), name="ai-grade"),
    # 自动标签 / 写作润色 / 每日摘要（#59 #61 #60）
    path("auto-tag/", v.AutoTagView.as_view(), name="ai-auto-tag"),
    path("polish/", v.PolishView.as_view(), name="ai-polish"),
    path("daily-digest/", v.DailyDigestView.as_view(), name="ai-daily-digest"),
]
