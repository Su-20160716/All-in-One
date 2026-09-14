"""core 路由：通知 / 公告 / 日志 / 搜索 / 设置 / 健康检查"""
from django.urls import path

from core import views

urlpatterns = [
    # 通知
    path("notifications/", views.NotificationListView.as_view(), name="notification-list"),
    path("notifications/read/", views.NotificationMarkReadView.as_view(), name="notification-read"),
    path("notifications/unread-count/", views.NotificationUnreadCountView.as_view(), name="notification-unread-count"),
    path("notifications/delete/", views.NotificationDeleteView.as_view(), name="notification-delete"),
    path("notifications/settings/", views.NotificationSettingView.as_view(), name="notification-settings"),
    # 公告
    path("announcements/", views.AnnouncementListView.as_view(), name="announcement-list"),
    path("announcements/<int:pk>/", views.AnnouncementDetailView.as_view(), name="announcement-detail"),
    path("announcements/<int:pk>/read/", views.AnnouncementReadView.as_view(), name="announcement-read"),
    path("admin/announcements/", views.AdminAnnouncementView.as_view(), name="admin-announcement-list"),
    path("admin/announcements/<int:pk>/", views.AdminAnnouncementDetailView.as_view(), name="admin-announcement-detail"),
    # 操作日志
    path("logs/", views.OperationLogListView.as_view(), name="operation-log-list"),
    path("my-logs/", views.MyOperationLogView.as_view(), name="my-operation-log"),
    path("logs/stats/", views.OperationLogStatsView.as_view(), name="operation-log-stats"),
    path("logs/export/", views.OperationLogExportView.as_view(), name="operation-log-export"),
    # 全局搜索
    path("search/", views.GlobalSearchView.as_view(), name="global-search"),
    # 全文搜索（倒排索引 + BM25）
    path("search/fulltext/", views.FullTextSearchView.as_view(), name="fulltext-search"),
    path("search/suggest/", views.SearchSuggestView.as_view(), name="search-suggest"),
    path("search/stats/", views.SearchIndexStatsView.as_view(), name="search-stats"),
    path("search/reindex/", views.ReindexView.as_view(), name="search-reindex"),
    # 站点设置
    path("settings/public/", views.PublicSiteSettingView.as_view(), name="public-settings"),
    path("admin/settings/", views.AdminSiteSettingView.as_view(), name="admin-settings"),
    # 健康检查
    path("health/", views.HealthView.as_view(), name="health"),
]
