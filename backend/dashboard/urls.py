"""dashboard 路由"""
from django.urls import path

from dashboard import views

urlpatterns = [
    path("stats/", views.UserStatsView.as_view(), name="user-stats"),
    path("personal-trend/", views.PersonalTrendView.as_view(), name="personal-trend"),
    path("my-task-distribution/", views.MyTaskDistributionView.as_view(), name="my-task-distribution"),
    path("file-type-distribution/", views.FileTypeDistributionView.as_view(), name="file-type-distribution"),
    path("todo-aggregate/", views.TodoAggregateView.as_view(), name="todo-aggregate"),
    # F657-F660 / F666-F668 今日卡片、最近动态、卡片顺序
    path("today-due/", views.TodayDueView.as_view(), name="today-due"),
    path("today-learning/", views.TodayLearningView.as_view(), name="today-learning"),
    path("today-schedule/", views.TodayScheduleView.as_view(), name="today-schedule"),
    path("storage-usage/", views.StorageUsageView.as_view(), name="storage-usage"),
    path("recent-activity/", views.RecentActivityView.as_view(), name="recent-activity"),
    path("card-order/", views.CardOrderView.as_view(), name="card-order"),
    # F28/F29 布局持久化与卡片开关 / F30 每日摘要
    path("layout/", views.DashboardLayoutView.as_view(), name="dashboard-layout"),
    path("daily-summary/", views.DailySummaryView.as_view(), name="daily-summary"),
    # #347 每日简报定时推送（due=1 仅在设定时间且今日未推送时发送）
    path("daily-summary/push/", views.DailySummaryPushView.as_view(), name="daily-summary-push"),
    # #344 提到我 / #345 里程碑 / #346 项目健康
    path("mentions/", views.MentionsCardView.as_view(), name="dashboard-mentions"),
    path("milestones/", views.MilestonesCardView.as_view(), name="dashboard-milestones"),
    path("project-health/", views.ProjectHealthView.as_view(), name="dashboard-project-health"),
    # #348 逾期项一键延期一天
    path("postpone-due/", views.PostponeDueView.as_view(), name="dashboard-postpone-due"),
    path("admin/global/", views.GlobalStatsView.as_view(), name="global-stats"),
    path("admin/trend/", views.ActivityTrendView.as_view(), name="activity-trend"),
    path("admin/user-growth/", views.AdminUserGrowthView.as_view(), name="user-growth"),
    path("admin/module-usage/", views.AdminModuleUsageView.as_view(), name="module-usage"),
]
