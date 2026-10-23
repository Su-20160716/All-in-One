"""看板模块序列化"""
from rest_framework import serializers

from projects.models import (
    AcceptanceItem,
    Board,
    CardComment,
    CardTemplate,
    Milestone,
    Project,
    ProjectActivity,
    Subtask,
    TaskCard,
    WorkLog,
)


def _has_prefetch(obj, name):
    """B6：判断 related manager 是否已被 prefetch_related 预取
    （命中缓存的访问零查询，用于把逐卡 N+1 压成常量查询）"""
    cache = getattr(obj, "_prefetched_objects_cache", None)
    return bool(cache) and name in cache


class BoardSerializer(serializers.ModelSerializer):
    card_count = serializers.SerializerMethodField()

    class Meta:
        model = Board
        fields = ["id", "project", "name", "sort_order", "wip_limit", "created_at", "card_count"]

    def get_card_count(self, obj):
        # B6：BoardListView 用 annotate(card_count_total=...) 预计算，零查询；
        # 无 annotate 时退回原行为
        cnt = getattr(obj, "card_count_total", None)
        if cnt is not None:
            return cnt
        return obj.cards.count()


class MilestoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Milestone
        fields = ["id", "project", "name", "description", "due_date", "status", "created_at", "updated_at"]


class CardTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CardTemplate
        fields = ["id", "name", "title", "description", "priority", "labels", "story_points",
                  "estimated_minutes", "created_at"]
        read_only_fields = ["created_at"]


class AcceptanceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcceptanceItem
        fields = ["id", "card", "content", "is_done", "sort_order", "created_at"]


class SubtaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.CharField(source="assignee.display_name", read_only=True, default="")

    class Meta:
        model = Subtask
        fields = ["id", "card", "title", "is_done", "assignee", "assignee_name", "sort_order", "created_at"]


class WorkLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.display_name", read_only=True)

    class Meta:
        model = WorkLog
        fields = ["id", "card", "user", "user_name", "minutes", "note", "created_at"]
        read_only_fields = ["user"]


class CardCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name", read_only=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = CardComment
        fields = ["id", "card", "author", "author_name", "content", "can_delete", "created_at", "updated_at"]
        read_only_fields = ["author"]

    def get_can_delete(self, obj):
        request = self.context.get("request")
        return bool(request and (request.user.id == obj.author_id or request.user.id == obj.card.board.project.owner_id))


class TaskCardSerializer(serializers.ModelSerializer):
    assignee_ids = serializers.SerializerMethodField()
    assignee_names = serializers.SerializerMethodField()
    board_name = serializers.CharField(source="board.name", read_only=True)
    comment_count = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    subtask_total = serializers.SerializerMethodField()
    subtask_done = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    spent_minutes = serializers.SerializerMethodField()
    code = serializers.SerializerMethodField()
    is_blocked = serializers.SerializerMethodField()
    dod_total = serializers.SerializerMethodField()
    dod_done = serializers.SerializerMethodField()

    class Meta:
        model = TaskCard
        fields = [
            "id", "board", "board_name", "number", "code", "title", "description", "priority", "status",
            "assignees", "assignee_ids", "assignee_names", "labels", "due_date", "story_points",
            "estimated_minutes", "is_archived", "is_blocked",
            "sort_order", "started_at", "completed_at", "created_by",
            "comment_count", "is_overdue", "subtask_total", "subtask_done", "progress",
            "dod_total", "dod_done", "spent_minutes", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at", "started_at", "completed_at"]

    def get_code(self, obj):
        return f"C-{obj.number}" if obj.number else ""

    def get_is_blocked(self, obj):
        # B6：优先用预取缓存（配合 Prefetch(select_related("blocked_by"))），
        # 无预取时保持原有查询行为
        if _has_prefetch(obj, "dependencies"):
            return any(
                d.blocked_by is not None and d.blocked_by.status in ("todo", "doing")
                for d in obj.dependencies.all()
            )
        return obj.dependencies.filter(blocked_by__status__in=["todo", "doing"]).exists()

    def get_dod_total(self, obj):
        if _has_prefetch(obj, "acceptance_items"):
            return len(obj.acceptance_items.all())
        return obj.acceptance_items.count()

    def get_dod_done(self, obj):
        if _has_prefetch(obj, "acceptance_items"):
            return len([a for a in obj.acceptance_items.all() if a.is_done])
        return obj.acceptance_items.filter(is_done=True).count()

    def get_assignee_ids(self, obj):
        if _has_prefetch(obj, "assignees"):
            return [u.id for u in obj.assignees.all()]
        return list(obj.assignees.values_list("id", flat=True))

    def get_assignee_names(self, obj):
        return [u.display_name for u in obj.assignees.all()]

    def get_comment_count(self, obj):
        if _has_prefetch(obj, "comments"):
            return len(obj.comments.all())
        return obj.comments.count()

    def get_is_overdue(self, obj):
        from datetime import date
        return bool(obj.due_date and obj.due_date < date.today() and obj.status != "done")

    def get_subtask_total(self, obj):
        if _has_prefetch(obj, "subtasks"):
            return len(obj.subtasks.all())
        return obj.subtasks.count()

    def get_subtask_done(self, obj):
        if _has_prefetch(obj, "subtasks"):
            return len([s for s in obj.subtasks.all() if s.is_done])
        return obj.subtasks.filter(is_done=True).count()

    def get_progress(self, obj):
        if _has_prefetch(obj, "subtasks"):
            total = len(obj.subtasks.all())
            if not total:
                return 100 if obj.status == "done" else 0
            done = len([s for s in obj.subtasks.all() if s.is_done])
            return round(done / total * 100)
        total = obj.subtasks.count()
        if not total:
            return 100 if obj.status == "done" else 0
        return round(obj.subtasks.filter(is_done=True).count() / total * 100)

    def get_spent_minutes(self, obj):
        if _has_prefetch(obj, "worklogs"):
            return sum(w.minutes or 0 for w in obj.worklogs.all())
        from django.db.models import Sum
        return obj.worklogs.aggregate(s=Sum("minutes"))["s"] or 0


class ProjectSerializer(serializers.ModelSerializer):
    member_ids = serializers.SerializerMethodField()
    member_names = serializers.SerializerMethodField()
    board_count = serializers.SerializerMethodField()
    card_total = serializers.SerializerMethodField()
    done_total = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id", "name", "description", "color", "owner", "is_star", "member_ids", "member_names",
            "is_archived", "board_count", "card_total", "done_total", "created_at", "updated_at",
        ]
        read_only_fields = ["owner", "created_at", "updated_at"]

    def get_member_ids(self, obj):
        if _has_prefetch(obj, "members"):
            return [u.id for u in obj.members.all()]
        return list(obj.members.values_list("id", flat=True))

    def get_member_names(self, obj):
        return [u.display_name for u in obj.members.all()]

    def get_board_count(self, obj):
        # B6：ProjectListView 用 annotate(board_count=Count(..., distinct=True)) 预计算
        cnt = getattr(obj, "board_count", None)
        if cnt is not None:
            return cnt
        return obj.boards.count()

    def get_card_total(self, obj):
        # B6：同上，annotate(card_total=...) 命中后零查询
        cnt = getattr(obj, "card_total", None)
        if cnt is not None:
            return cnt
        return TaskCard.objects.filter(board__project=obj).count()

    def get_done_total(self, obj):
        cnt = getattr(obj, "done_total", None)
        if cnt is not None:
            return cnt
        return TaskCard.objects.filter(board__project=obj, status="done").count()


class ProjectActivitySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.display_name", read_only=True, default="系统")

    class Meta:
        model = ProjectActivity
        fields = ["id", "user", "user_name", "action", "target", "created_at"]
