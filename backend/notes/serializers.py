"""笔记模块序列化"""
from rest_framework import serializers

from notes.models import Note, NoteLink, NoteTag, NoteVersion


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

    class Meta:
        model = Note
        fields = [
            "id", "title", "content", "parent", "tags", "tag_names", "tag_ids",
            "is_pinned", "is_favorite", "is_public", "share_token",
            "version", "is_deleted", "deleted_at", "words", "child_count",
            "ai_summary", "ai_summary_at", "created_at", "updated_at",
        ]
        read_only_fields = ["share_token", "version", "words", "ai_summary", "ai_summary_at"]

    def get_tag_names(self, obj):
        return list(obj.tags.values_list("name", flat=True))

    def get_tag_ids(self, obj):
        return list(obj.tags.values_list("id", flat=True))

    def get_child_count(self, obj):
        return obj.children.filter(is_deleted=False).count()


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
