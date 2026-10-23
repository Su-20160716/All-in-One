"""笔记模块序列化"""
from rest_framework import serializers

from notes.models import Note, NoteLink, NoteTag, NoteVersion


def _has_prefetch(obj, name):
    """B6：判断 related manager 是否已被 prefetch_related 预取"""
    cache = getattr(obj, "_prefetched_objects_cache", None)
    return bool(cache) and name in cache


class NoteTagSerializer(serializers.ModelSerializer):
    use_count = serializers.SerializerMethodField()

    class Meta:
        model = NoteTag
        fields = ["id", "name", "color", "use_count"]

    def get_use_count(self, obj):
        return obj.notes.filter(is_deleted=False).count()


class NoteSerializer(serializers.ModelSerializer):
    tag_names = serializers.SerializerMethodField()
    tag_ids = serializers.SerializerMethodField()
    child_count = serializers.SerializerMethodField()
    folder_name = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            "id", "title", "content", "parent", "tags", "tag_names", "tag_ids",
            "is_pinned", "is_favorite", "is_public", "is_archived", "share_token",
            "version", "is_deleted", "deleted_at", "words", "child_count",
            "ai_summary", "ai_summary_at", "created_at", "updated_at",
            # F572 颜色 / F573 来源 / F582 分组文件夹
            "color", "source", "folder", "folder_name",
        ]
        read_only_fields = ["share_token", "version", "words", "ai_summary", "ai_summary_at"]

    def get_tag_names(self, obj):
        if _has_prefetch(obj, "tags"):
            return [t.name for t in obj.tags.all()]
        return list(obj.tags.values_list("name", flat=True))

    def get_tag_ids(self, obj):
        if _has_prefetch(obj, "tags"):
            return [t.id for t in obj.tags.all()]
        return list(obj.tags.values_list("id", flat=True))

    def get_child_count(self, obj):
        # B6：列表页用 annotate(child_count=...) 预计算；无 annotate 保持原行为
        cnt = getattr(obj, "child_count", None)
        if cnt is not None:
            return cnt
        return obj.children.filter(is_deleted=False).count()

    def get_folder_name(self, obj):
        return obj.folder.name if obj.folder_id else ""


class NoteLinkSerializer(serializers.ModelSerializer):
    source_title = serializers.CharField(source="source.title", read_only=True)

    class Meta:
        model = NoteLink
        fields = ["id", "source", "source_title", "target", "target_title", "alias", "created_at"]


class NoteVersionSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True, default="")

    class Meta:
        model = NoteVersion
        fields = ["id", "version", "title", "content", "created_by_name", "created_at"]
