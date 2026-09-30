"""文件模块序列化"""
from django.db.models import Sum as ModelsSum
from rest_framework import serializers

from files.models import FileMeta, FileTag, Folder, ShareLink


class FolderSerializer(serializers.ModelSerializer):
    file_count = serializers.SerializerMethodField()
    folder_count = serializers.SerializerMethodField()
    total_size = serializers.SerializerMethodField()

    class Meta:
        model = Folder
        fields = ["id", "name", "parent", "owner", "color", "created_at", "updated_at", "file_count", "folder_count", "total_size"]
        read_only_fields = ["owner", "created_at", "updated_at"]

    def get_file_count(self, obj):
        return obj.files.filter(is_deleted=False).count()

    def get_folder_count(self, obj):
        return obj.children.count()

    def get_total_size(self, obj):
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
        return list(obj.tags.values_list("name", flat=True))

    def get_tag_ids(self, obj):
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
    total_chunks = serializers.IntegerField(min_value=1)
    sha1 = serializers.CharField(required=False, allow_blank=True, max_length=40)


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
            "password", "max_downloads", "download_count", "view_count", "is_revoked",
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
