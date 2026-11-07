"""笔记模块序列化"""
from rest_framework import serializers

from notes.models import Note, NoteAttachment, NoteComment, NoteLink, NoteTag, NoteTemplate, NoteVersion


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
    cover_thumb = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            "id", "title", "content", "parent", "tags", "tag_names", "tag_ids",
            "is_pinned", "is_favorite", "is_public", "is_archived", "share_token",
            "version", "is_deleted", "deleted_at", "words", "child_count",
            "ai_summary", "ai_summary_at", "created_at", "updated_at",
            # F18 定时发布 / 到期归档
            "publish_at", "expire_at",
            # F572 颜色 / F573 来源 / F582 分组文件夹
            "color", "source", "folder", "folder_name",
            # F238 图标 / F239 封面 / F240 提醒 / F260 置顶排序
            "icon", "cover_file", "cover_thumb", "remind_at", "reminded_at", "pin_order",
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

    def get_cover_thumb(self, obj):
        # F239：优先缩略图，没有缩略图（非图片）时回落原文件 URL
        if not obj.cover_file_id or not obj.cover_file:
            return ""
        return obj.cover_file.thumbnail_url or obj.cover_file.url


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


class NoteCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    reply_count = serializers.SerializerMethodField()

    class Meta:
        model = NoteComment
        fields = ["id", "note", "author", "author_name", "quote", "content", "parent",
                  "resolved", "reply_count", "created_at", "updated_at"]

    def get_author_name(self, obj):
        return getattr(obj.author, "display_name", "") or getattr(obj.author, "username", "") or ""

    def get_reply_count(self, obj):
        return obj.replies.count()


class NoteAttachmentSerializer(serializers.ModelSerializer):
    file_id = serializers.IntegerField(source="file.id", read_only=True)
    url = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    kind = serializers.CharField(source="file.kind", read_only=True)

    class Meta:
        model = NoteAttachment
        fields = ["id", "note", "file_id", "name", "size", "kind", "url", "thumbnail", "created_at"]

    def _file(self, obj):
        return obj.file if obj.file_id else None

    def get_url(self, obj):
        # F237：正文插入的下载链接（带文件 id，文件删除后由前端提示失效）
        return f"/api/files/{obj.file_id}/download/" if obj.file_id else ""

    def get_thumbnail(self, obj):
        f = self._file(obj)
        if not f:
            return ""
        return f.thumbnail_url or f.url


class NoteTemplateSerializer(serializers.ModelSerializer):
    tag_list = serializers.SerializerMethodField()

    class Meta:
        model = NoteTemplate
        fields = ["id", "title", "content", "icon", "tags", "tag_list", "created_at", "updated_at"]

    def get_tag_list(self, obj):
        return obj.tag_list
