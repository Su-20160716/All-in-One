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
    path("admin/announcements/<int:pk>/readers/export/", views.AnnouncementReadExportView.as_view(), name="announcement-read-export"),
    # 操作日志
    path("logs/", views.OperationLogListView.as_view(), name="operation-log-list"),
    path("my-logs/", views.MyOperationLogView.as_view(), name="my-operation-log"),
    path("logs/stats/", views.OperationLogStatsView.as_view(), name="operation-log-stats"),
    path("logs/export/", views.OperationLogExportView.as_view(), name="operation-log-export"),
    # #72 存储使用 TOP 用户
    path("admin/storage/top-users/", views.StorageTopUsersView.as_view(), name="storage-top-users"),
    # #68 数据备份
    path("admin/backup/", views.BackupView.as_view(), name="admin-backup"),
    # 全局搜索
    path("search/", views.GlobalSearchView.as_view(), name="global-search"),
    # 全文搜索（倒排索引 + BM25）
    path("search/fulltext/", views.FullTextSearchView.as_view(), name="fulltext-search"),
    path("search/suggest/", views.SearchSuggestView.as_view(), name="search-suggest"),
    path("search/stats/", views.SearchIndexStatsView.as_view(), name="search-stats"),
    path("search/reindex/", views.ReindexView.as_view(), name="search-reindex"),
    # 搜索历史 / 热词 / 导出（#63 #65）
    path("search/history/", views.SearchHistoryView.as_view(), name="search-history"),
    path("search/hot/", views.SearchHotView.as_view(), name="search-hot"),
    path("search/export/", views.SearchExportView.as_view(), name="search-export"),
    # 站点设置
    path("settings/public/", views.PublicSiteSettingView.as_view(), name="public-settings"),
    path("admin/settings/", views.AdminSiteSettingView.as_view(), name="admin-settings"),
    # 健康检查
    path("health/", views.HealthView.as_view(), name="health"),
    # ---------------- v8 新增：管理与平台（F627–F642） ----------------
    # F627 后端健康卡
    path("admin/health-card/", views.AdminHealthCardView.as_view(), name="admin-health-card"),
    # F628 日志导出 CSV（operation/login/exception）
    path("admin/logs/export/", views.AdminLogExportView.as_view(), name="admin-log-export"),
    # F629 管理命令面板（白名单）
    path("admin/commands/", views.AdminCommandListView.as_view(), name="admin-commands"),
    path("admin/commands/run/", views.AdminCommandRunView.as_view(), name="admin-commands-run"),
    # F630 公告已读率趋势（7 天）
    path("admin/announcement-read-trend/", views.AnnouncementReadTrendView.as_view(),
         name="admin-announcement-read-trend"),
    # F631 用户活跃分层
    path("admin/user-activity-tiers/", views.UserActivityTiersView.as_view(),
         name="admin-user-activity-tiers"),
    # F632 慢接口 TOP10 + 前端采样上报
    path("admin/slow-endpoints/", views.AdminSlowEndpointView.as_view(), name="admin-slow-endpoints"),
    path("admin/slow-endpoints/report/", views.SlowEndpointReportView.as_view(),
         name="slow-endpoints-report"),
    # F633 异常聚合
    path("admin/exceptions/", views.AdminExceptionListView.as_view(), name="admin-exceptions"),
    path("admin/exceptions/report/", views.ExceptionReportView.as_view(), name="exception-report"),
    # F634 登录失败 TOP
    path("admin/login-fail-top/", views.AdminLoginFailTopView.as_view(), name="admin-login-fail-top"),
    # F635 数据表行数 / 体积统计
    path("admin/table-stats/", views.AdminTableStatsView.as_view(), name="admin-table-stats"),
    # F638 运行配置只读视图（脱敏）
    path("admin/runtime-config/", views.AdminRuntimeConfigView.as_view(), name="admin-runtime-config"),
    # F639 维护模式开关
    path("admin/maintenance/", views.MaintenanceModeView.as_view(), name="admin-maintenance"),
    # F640 跨模块审计检索
    path("admin/audit/search/", views.AdminAuditSearchView.as_view(), name="admin-audit-search"),
    # F641 管理员群发通知
    path("admin/broadcast/", views.AdminBroadcastView.as_view(), name="admin-broadcast"),
    # F642 关于页（版本 / 最近提交 / 运行时长，git 不可用时优雅降级）
    path("about/", views.AboutView.as_view(), name="about"),
]
