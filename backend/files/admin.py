from django.contrib import admin

from files.models import ChunkUpload, FileMeta, Folder, ShareLink


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "owner", "created_at"]


@admin.register(FileMeta)
class FileMetaAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "size", "kind", "is_deleted", "created_at"]
    search_fields = ["name", "sha1"]


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ["token", "file", "created_by", "permission", "download_count"]


@admin.register(ChunkUpload)
class ChunkUploadAdmin(admin.ModelAdmin):
    list_display = ["filename", "user", "total_chunks", "status", "created_at"]
