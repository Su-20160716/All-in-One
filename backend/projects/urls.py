"""projects 路由"""
from django.urls import path

from projects import views
from projects import extra_views

urlpatterns = [
    # 项目
    path("", views.ProjectListView.as_view(), name="project-list"),
    path("my-tasks/", views.MyTasksView.as_view(), name="my-tasks"),
    path("templates/", extra_views.BoardTemplateListView.as_view(), name="board-templates"),
    path("from-template/", extra_views.ProjectFromTemplateView.as_view(), name="project-from-template"),
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
    path("<int:project_id>/burndown/", extra_views.ProjectBurndownView.as_view(), name="project-burndown"),
    path("<int:project_id>/share/", extra_views.BoardShareCreateView.as_view(), name="board-share-create"),
    path("<int:project_id>/share/<str:token>/", extra_views.BoardShareRevokeView.as_view(), name="board-share-revoke"),
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
    # ===== 看板增强 F583–F598（新增路由，置于末尾） =====
    path("cards/<int:pk>/countdown/", views.CardCountdownView.as_view(), name="card-countdown"),
    path("cards/<int:pk>/checklist/", views.CardChecklistView.as_view(), name="card-checklist"),
    path("cards/<int:pk>/timeline/", views.CardTimelineView.as_view(), name="card-timeline"),
    path("cards/<int:pk>/dependencies/", views.CardDependencyView.as_view(), name="card-dependencies"),
    path("cards/<int:pk>/estimate/", views.CardEstimateView.as_view(), name="card-estimate"),
    path("cards/<int:pk>/save-template/", views.CardSaveTemplateView.as_view(), name="card-save-template"),
    path("cards/<int:pk>/dod/", views.CardDodView.as_view(), name="card-dod"),
    path("cards/<int:pk>/dod/<int:item_id>/", views.CardDodDetailView.as_view(), name="card-dod-detail"),
    path("cards/<int:pk>/archive/", views.CardArchiveView.as_view(), name="card-archive"),
    path("cards/batch-move/", views.CardBatchMoveView.as_view(), name="card-batch-move"),
    path("boards/<int:board_id>/wip-limit/", views.BoardWipView.as_view(), name="board-wip-limit"),
    path("card-templates/", views.CardTemplateListView.as_view(), name="card-template-list"),
    path("card-templates/<int:pk>/apply/", views.CardTemplateApplyView.as_view(), name="card-template-apply"),
    path("<int:project_id>/weekly-report/", views.ProjectWeeklyReportView.as_view(), name="project-weekly-report"),
    path("<int:project_id>/milestones/", views.ProjectMilestoneView.as_view(), name="project-milestones"),
    path("milestones/<int:pk>/", views.MilestoneDetailView.as_view(), name="milestone-detail"),
    path("<int:project_id>/workload/", views.ProjectWorkloadView.as_view(), name="project-workload"),
    path("<int:project_id>/cards/by-number/<int:number>/", views.CardByNumberView.as_view(), name="card-by-number"),
    path("<int:project_id>/resolve/", views.CardResolveView.as_view(), name="card-resolve"),
    path("<int:project_id>/standup/", views.ProjectStandupView.as_view(), name="project-standup"),
    path("<int:project_id>/archived-cards/", views.ProjectArchivedCardsView.as_view(), name="project-archived-cards"),
]

# 公开只读看板分享（免登录），挂在 /share/board/<token>/
board_share_urlpatterns = [
    path("share/board/<str:token>/", extra_views.BoardSharePublicView.as_view(), name="board-share-public"),
    # F3：/api/share/board/* 别名——前端不再代理 /share（那是 history 路由），
    # 公开 API 统一挪到 /api 前缀下；旧根级路由保留兼容已发布外链
    path("api/share/board/<str:token>/", extra_views.BoardSharePublicView.as_view(), name="board-share-public-api"),
]
