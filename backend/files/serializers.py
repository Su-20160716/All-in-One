"""文件模块序列化"""
import math

from django.conf import settings
from django.db.models import Sum as ModelsSum
from rest_framework import serializers

from core.validators import sanitize_filename
from files.models import FileMeta, FileTag, Folder, ShareLink


def _has_prefetch(obj, name):
    """B6：判断 related manager 是否已被 prefetch_related 预取"""
    cache = getattr(obj, "_prefetched_objects_cache", None)
    return bool(cache) and name in cache


class FolderSerializer(serializers.ModelSerializer):
    file_count = serializers.SerializerMethodField()
    folder_count = serializers.SerializerMethodField()
    total_size = serializers.SerializerMethodField()

    class Meta:
        model = Folder
        fields = ["id", "name", "parent", "owner", "color", "created_at", "updated_at", "file_count", "folder_count", "total_size"]
        read_only_fields = ["owner", "created_at", "updated_at"]

    def get_file_count(self, obj):
        cached = getattr(obj, "file_count_ann", None)
        return obj.files.filter(is_deleted=False).count() if cached is None else cached

    def get_folder_count(self, obj):
        cached = getattr(obj, "folder_count_ann", None)
        return obj.children.count() if cached is None else cached

    def get_total_size(self, obj):
        cached = getattr(obj, "total_size_ann", None)
        if cached is not None:
            return cached
        return obj.files.filter(is_deleted=False).aggregate(s=ModelsSum("size"))["s"] or 0


class FileMetaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    size_text = serializers.SerializerMethodField()
    folder_name = serializers.SerializerMethodField()
    preview_type = serializers.SerializerMethodField()
    previewable = serializers.SerializerMethodField()
    raw_url = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    tag_names = serializers.SerializerMethodField()
    tag_ids = serializers.SerializerMethodField()

    class Meta:
        model = FileMeta
        fields = [
            "id", "name", "folder", "folder_name", "size", "size_text", "sha1", "kind", "ext",
            "url", "thumbnail_url", "is_star", "favorite_group", "description",
            "preview_type", "previewable", "raw_url", "pdf_url", "pdf_status",
            "is_deleted", "deleted_at", "origin_folder_id", "created_at", "updated_at",
            "tag_names", "tag_ids",
            # F553 图片分辨率徽章 / F555 收藏排序
            "width", "height", "favorite_order",
        ]

    def get_url(self, obj):
        return obj.url

    def get_thumbnail_url(self, obj):
        return obj.thumbnail_url

    def get_size_text(self, obj):
        from core.utils import format_size
        return format_size(obj.size)

    def get_folder_name(self, obj):
        return obj.folder.name if obj.folder else "根目录"

    def get_preview_type(self, obj):
        return obj.preview_type

    def get_previewable(self, obj):
        return obj.previewable

    def get_raw_url(self, obj):
        return f"/api/files/{obj.id}/raw/"

    def get_pdf_url(self, obj):
        return obj.pdf_url

    def get_tag_names(self, obj):
        if _has_prefetch(obj, "tags"):
            return [t.name for t in obj.tags.all()]
        return list(obj.tags.values_list("name", flat=True))

    def get_tag_ids(self, obj):
        if _has_prefetch(obj, "tags"):
            return [t.id for t in obj.tags.all()]
        return list(obj.tags.values_list("id", flat=True))


class FileTagSerializer(serializers.ModelSerializer):
    use_count = serializers.SerializerMethodField()

    class Meta:
        model = FileTag
        fields = ["id", "name", "color", "use_count"]

    def get_use_count(self, obj):
        return obj.use_count


class ChunkInitSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    folder_id = serializers.IntegerField(required=False, allow_null=True)
    file_size = serializers.IntegerField(min_value=0)
    chunk_size = serializers.IntegerField(min_value=1, max_value=100 * 1024 * 1024)
    total_chunks = serializers.IntegerField(min_value=1, max_value=20000)
    sha1 = serializers.CharField(required=False, allow_blank=True, max_length=40)

    def validate_filename(self, value):
        return sanitize_filename(value)

    def validate(self, attrs):
        max_bytes = int(getattr(settings, "FILE_MAX_SIZE_MB", 1024)) * 1024 * 1024
        if attrs["file_size"] > max_bytes:
            raise serializers.ValidationError(
                {"file_size": f"文件超过大小限制 {settings.FILE_MAX_SIZE_MB}MB"}
            )
        # total_chunks 必须与 file_size/chunk_size 自洽：否则完成时按声明值逐片拼接，
        # 可以凭空放大读写量（声明 1 片但 file_size 巨大 / 声明 2 万片）
        expected = max(1, math.ceil(attrs["file_size"] / attrs["chunk_size"]))
        if attrs["total_chunks"] != expected:
            raise serializers.ValidationError(
                {"total_chunks": f"应为 {expected}（file_size / chunk_size 向上取整）"}
            )
        return attrs


class ShareLinkSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    target_type = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = ShareLink
        fields = [
            "id", "token", "file", "file_name", "folder", "target_type", "permission",
            "max_downloads", "download_count", "view_count", "is_revoked",
            "is_expired", "has_password", "expire_at", "created_at", "url",
        ]
        read_only_fields = ["token", "download_count", "view_count", "created_at"]

    def get_url(self, obj):
        return f"/share/{obj.token}"

    def get_file_name(self, obj):
        return obj.file.name if obj.file else (obj.folder.name if obj.folder else "")

    def get_target_type(self, obj):
        return "file" if obj.file else "folder"

    def get_is_expired(self, obj):
        return obj.is_expired

    def get_has_password(self, obj):
        return bool(obj.password)


class TrashSerializer(serializers.Serializer):
    file_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    action = serializers.ChoiceField(choices=["restore", "delete", "empty"], required=False, default="restore")
