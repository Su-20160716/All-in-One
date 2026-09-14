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
    path("batch-download/", views.FileBatchDownloadView.as_view(), name="file-batch-download"),
    path("create-text/", views.FileCreateTextView.as_view(), name="file-create-text"),
    path("office-capability/", views.OfficeCapabilityView.as_view(), name="file-office-capability"),
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
    path("share/<str:token>/", views.ShareAccessView.as_view(), name="share-access"),
    path("share/<str:token>/download/<int:pk>/", views.ShareDownloadView.as_view(), name="share-download"),
]
