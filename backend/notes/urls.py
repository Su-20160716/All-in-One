"""notes 路由"""
from django.urls import path

from notes import views

urlpatterns = [
    path("", views.NoteListView.as_view(), name="note-list"),
    path("batch/", views.NoteBatchView.as_view(), name="note-batch"),
    path("trash/", views.NoteTrashView.as_view(), name="note-trash"),
    path("tree/", views.NoteTreeView.as_view(), name="note-tree"),
    path("tags/", views.NoteTagListView.as_view(), name="note-tags"),
    path("tags/<int:pk>/", views.NoteTagDetailView.as_view(), name="note-tag-detail"),
    path("recent/", views.NoteRecentView.as_view(), name="note-recent"),
    path("stats/", views.NoteStatsView.as_view(), name="note-stats"),
    path("templates/", views.NoteTemplateListView.as_view(), name="note-templates"),
    path("from-template/", views.NoteFromTemplateView.as_view(), name="note-from-template"),
    path("export-all/", views.NoteExportAllView.as_view(), name="note-export-all"),
    path("public/<str:token>/", views.NoteShareView.as_view(), name="note-public"),
    # 双链
    path("graph/", views.NoteLinkGraphView.as_view(), name="note-link-graph"),
    path("link-suggest/", views.NoteLinkSuggestView.as_view(), name="note-link-suggest"),
    path("dangling/", views.NoteDanglingView.as_view(), name="note-dangling"),
    path("from-title/", views.NoteFromTitleView.as_view(), name="note-from-title"),
    path("links/rebuild/", views.NoteLinkRebuildView.as_view(), name="note-link-rebuild"),
    path("<int:pk>/", views.NoteDetailView.as_view(), name="note-detail"),
    path("<int:pk>/copy/", views.NoteCopyView.as_view(), name="note-copy"),
    path("<int:pk>/backlinks/", views.NoteBacklinkView.as_view(), name="note-backlinks"),
    path("<int:pk>/outline/", views.NoteOutlineView.as_view(), name="note-outline"),
    path("<int:pk>/export/", views.NoteExportView.as_view(), name="note-export"),
    path("<int:pk>/versions/", views.NoteVersionListView.as_view(), name="note-versions"),
    path("<int:pk>/versions/diff/", views.NoteVersionDiffView.as_view(), name="note-version-diff"),
    path("<int:pk>/rollback/<int:version>/", views.NoteRollbackView.as_view(), name="note-rollback"),
]
