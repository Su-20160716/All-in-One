"""im 路由"""
from django.urls import path

from im import views

urlpatterns = [
    path("sessions/", views.SessionListView.as_view(), name="session-list"),
    path("sessions/create/", views.SessionListView.as_view(), name="session-create"),
    path("sessions/search-messages/", views.GlobalMessageSearchView.as_view(), name="message-global-search"),
    path("sessions/unread-summary/", views.UnreadSummaryView.as_view(), name="unread-summary"),
    path("unread-total/", views.UnreadSummaryView.as_view(), name="unread-total"),
    path("quick-replies/", views.QuickReplyListView.as_view(), name="quick-reply-list"),
    path("quick-replies/<int:pk>/", views.QuickReplyDetailView.as_view(), name="quick-reply-detail"),
    path("keyword-alert/", views.KeywordAlertView.as_view(), name="keyword-alert"),
    path("sessions/<int:pk>/", views.SessionDetailView.as_view(), name="session-detail"),
    path("sessions/<int:pk>/members/", views.SessionMemberView.as_view(), name="session-members"),
    path("sessions/<int:pk>/leave/", views.SessionLeaveView.as_view(), name="session-leave"),
    path("sessions/<int:pk>/transfer/", views.SessionTransferView.as_view(), name="session-transfer"),
    path("sessions/<int:pk>/setting/", views.SessionSettingView.as_view(), name="session-setting"),
    path("sessions/<int:pk>/messages/", views.MessageListView.as_view(), name="message-list"),
    path("sessions/<int:pk>/send/", views.MessageCreateView.as_view(), name="message-send"),
    path("messages/<int:pk>/recall/", views.MessageRecallView.as_view(), name="message-recall"),
    path("messages/<int:pk>/delete/", views.MessageDeleteView.as_view(), name="message-delete"),
    path("messages/<int:pk>/forward/", views.MessageForwardView.as_view(), name="message-forward"),
    path("messages/<int:pk>/pin/", views.MessagePinView.as_view(), name="message-pin"),
]
