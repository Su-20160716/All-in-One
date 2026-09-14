"""dashboard 路由"""
from django.urls import path

from dashboard import views

urlpatterns = [
    path("stats/", views.UserStatsView.as_view(), name="user-stats"),
    path("personal-trend/", views.PersonalTrendView.as_view(), name="personal-trend"),
    path("my-task-distribution/", views.MyTaskDistributionView.as_view(), name="my-task-distribution"),
    path("file-type-distribution/", views.FileTypeDistributionView.as_view(), name="file-type-distribution"),
    path("todo-aggregate/", views.TodoAggregateView.as_view(), name="todo-aggregate"),
    path("admin/global/", views.GlobalStatsView.as_view(), name="global-stats"),
    path("admin/trend/", views.ActivityTrendView.as_view(), name="activity-trend"),
    path("admin/user-growth/", views.AdminUserGrowthView.as_view(), name="user-growth"),
    path("admin/module-usage/", views.AdminModuleUsageView.as_view(), name="module-usage"),
]
