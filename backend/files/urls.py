"""files 路由"""
from django.urls import path

from files import views

urlpatterns = [
    # 文件夹
    path("folders/", views.FolderListView.as_view(), name="folder-list"),
    path("folders/tree/", views.FolderTreeView.as_view(), name="folder-tree"),
    path("folders/<int:pk>/", views.FolderDetailView.as_view(), name="folder-detail"),
    path("folders/<int:pk>/breadcrumb/", views.FolderBreadcrumbView.as_view(), name="folder-breadcrumb"),
    # 文件
    path("", views.FileListView.as_view(), name="file-list"),
    path("search/", views.FileSearchView.as_view(), name="file-search"),
    path("recent/", views.RecentFileView.as_view(), name="recent-file"),
    path("starred/", views.StarredFileView.as_view(), name="starred-file"),
    path("analysis/", views.StorageAnalysisView.as_view(), name="storage-analysis"),
    path("batch/", views.FileBatchView.as_view(), name="file-batch"),
    path("batch-tag/", views.FileBatchTagView.as_view(), name="file-batch-tag"),
    path("batch-rename/", views.FileBatchRenameView.as_view(), name="file-batch-rename"),
    path("batch-download/", views.FileBatchDownloadView.as_view(), name="file-batch-download"),
    path("tags/", views.FileTagListView.as_view(), name="file-tag-list"),
    path("tags/<int:pk>/", views.FileTagDetailView.as_view(), name="file-tag-detail"),
    path("folder-templates/", views.FolderTemplatesView.as_view(), name="folder-templates"),
    path("folders/from-template/", views.FolderFromTemplateView.as_view(), name="folder-from-template"),
    path("clean-config/", views.FileCleanConfigView.as_view(), name="file-clean-config"),
    path("create-text/", views.FileCreateTextView.as_view(), name="file-create-text"),
    path("office-capability/", views.OfficeCapabilityView.as_view(), name="file-office-capability"),
    # ---- F547–F564 文件中心新增能力 ----
    path("duplicates/", views.DuplicatesView.as_view(), name="file-duplicates"),
    path("storage-trend/", views.StorageTrendView.as_view(), name="file-storage-trend"),
    path("large-files/", views.LargeFilesView.as_view(), name="file-large-files"),
    path("export-csv/", views.FileExportCsvView.as_view(), name="file-export-csv"),
    path("trash/stats/", views.TrashStatsView.as_view(), name="file-trash-stats"),
    path("image-dims/", views.ImageDimsView.as_view(), name="file-image-dims"),
    path("starred/order/", views.StarredOrderView.as_view(), name="file-starred-order"),
    path("folder-hits/", views.FolderHitsView.as_view(), name="file-folder-hits"),
    path("operations/", views.FileOperationListView.as_view(), name="file-operations"),
    path("shares/expiring/", views.ShareExpiringView.as_view(), name="file-shares-expiring"),
    path("tags/stats/", views.FileTagStatsView.as_view(), name="file-tag-stats"),
    path("favorites/export/", views.FavoritesExportView.as_view(), name="file-favorites-export"),
    path("favorites/import/", views.FavoritesImportView.as_view(), name="file-favorites-import"),
    path("upload/init/", views.UploadInitView.as_view(), name="upload-init"),
    path("upload/status/", views.UploadStatusView.as_view(), name="upload-status"),
    path("upload/abort/", views.UploadAbortView.as_view(), name="upload-abort"),
    path("upload/chunk/", views.UploadChunkView.as_view(), name="upload-chunk"),
    path("upload/complete/", views.UploadCompleteView.as_view(), name="upload-complete"),
    path("<int:pk>/", views.FileDetailView.as_view(), name="file-detail"),
    path("<int:pk>/star/", views.FileStarView.as_view(), name="file-star"),
    path("<int:pk>/copy/", views.FileCopyView.as_view(), name="file-copy"),
    path("<int:pk>/save-text/", views.FileSaveTextView.as_view(), name="file-save-text"),
    path("<int:pk>/download/", views.FileDownloadView.as_view(), name="file-download"),
    path("<int:pk>/preview/", views.FilePreviewView.as_view(), name="file-preview"),
    # 多类型在线预览（Range 流式）与 Office 转 PDF
    path("<int:pk>/raw/", views.FileRawView.as_view(), name="file-raw"),
    path("<int:pk>/to-pdf/", views.FileToPdfView.as_view(), name="file-to-pdf"),
    path("<int:pk>/pdf/", views.FilePdfView.as_view(), name="file-pdf"),
    # F561 可见性快照
    path("<int:pk>/visibility/", views.FileVisibilityView.as_view(), name="file-visibility"),
    # 回收站
    path("trash/", views.TrashListView.as_view(), name="trash-list"),
    path("trash/action/", views.TrashActionView.as_view(), name="trash-action"),
    path("trash/auto-clean/", views.TrashAutoCleanView.as_view(), name="trash-auto-clean"),
    # 共享
    path("shares/", views.ShareLinkListView.as_view(), name="share-list"),
    path("shares/create/", views.ShareLinkCreateView.as_view(), name="share-create"),
    path("shares/<str:token>/", views.ShareLinkDetailView.as_view(), name="share-detail"),
]

# 公开共享路径挂在 /share/ 下
share_urlpatterns = [
    # 旧路由保留（向后兼容，已发布的外链继续有效）
    path("share/<str:token>/", views.ShareAccessView.as_view(), name="share-access"),
    path("share/<str:token>/download/<int:pk>/", views.ShareDownloadView.as_view(), name="share-download"),
    # F3：/api/share/* 别名。前端分享页是 history 路由 /share/:token，
    # 与旧根级 /share/ 混在一起会导致「打开分享链接看到的是 JSON 而不是页面」，
    # 故 API 统一挪到 /api/share/ 前缀，根级路由仅作兼容保留
    path("api/share/<str:token>/", views.ShareAccessView.as_view(), name="share-access-api"),
    path("api/share/<str:token>/download/<int:pk>/", views.ShareDownloadView.as_view(), name="share-download-api"),
]
