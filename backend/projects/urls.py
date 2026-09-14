"""projects 路由"""
from django.urls import path

from projects import views

urlpatterns = [
    # 项目
    path("", views.ProjectListView.as_view(), name="project-list"),
    path("my-tasks/", views.MyTasksView.as_view(), name="my-tasks"),
    path("<int:pk>/", views.ProjectDetailView.as_view(), name="project-detail"),
    path("<int:pk>/star/", views.ProjectStarView.as_view(), name="project-star"),
    path("<int:pk>/clone/", views.ProjectCloneView.as_view(), name="project-clone"),
    path("<int:pk>/members/", views.ProjectMemberView.as_view(), name="project-members"),
    path("<int:project_id>/boards/", views.BoardListView.as_view(), name="board-list"),
    path("<int:project_id>/boards/reorder/", views.BoardReorderView.as_view(), name="board-reorder"),
    path("<int:project_id>/search/", views.CardSearchView.as_view(), name="card-search"),
    path("<int:project_id>/activities/", views.ProjectActivityView.as_view(), name="project-activity"),
    path("<int:project_id>/stats/", views.ProjectStatsView.as_view(), name="project-stats"),
    path("<int:project_id>/calendar/", views.ProjectCalendarView.as_view(), name="project-calendar"),
    path("cards/batch/", views.CardBatchView.as_view(), name="card-batch"),
    # 看板列
    path("boards/<int:board_id>/", views.BoardDetailView.as_view(), name="board-detail"),
    path("boards/<int:board_id>/cards/", views.CardListView.as_view(), name="card-list"),
    # 卡片
    path("cards/<int:pk>/", views.CardDetailView.as_view(), name="card-detail"),
    path("cards/<int:pk>/copy/", views.CardCopyView.as_view(), name="card-copy"),
    path("cards/<int:pk>/move/", views.CardMoveView.as_view(), name="card-move"),
    path("cards/<int:pk>/subtasks/", views.SubtaskListView.as_view(), name="subtask-list"),
    path("cards/<int:pk>/subtasks/<int:sid>/", views.SubtaskDetailView.as_view(), name="subtask-detail"),
    path("cards/<int:pk>/worklogs/", views.WorkLogListView.as_view(), name="worklog-list"),
    path("cards/<int:pk>/worklogs/<int:wid>/", views.WorkLogDetailView.as_view(), name="worklog-detail"),
    path("cards/<int:pk>/comments/", views.CardCommentListView.as_view(), name="comment-list"),
    path("cards/<int:pk>/comments/<int:cid>/", views.CardCommentDetailView.as_view(), name="comment-detail"),
]
