"""看板模块序列化"""
from rest_framework import serializers

from projects.models import Board, CardComment, Project, ProjectActivity, Subtask, TaskCard, WorkLog


class BoardSerializer(serializers.ModelSerializer):
    card_count = serializers.SerializerMethodField()

    class Meta:
        model = Board
        fields = ["id", "project", "name", "sort_order", "created_at", "card_count"]

    def get_card_count(self, obj):
        return obj.cards.count()


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

    class Meta:
        model = TaskCard
        fields = [
            "id", "board", "board_name", "title", "description", "priority", "status",
            "assignees", "assignee_ids", "assignee_names", "labels", "due_date", "story_points",
            "sort_order", "started_at", "completed_at", "created_by",
            "comment_count", "is_overdue", "subtask_total", "subtask_done", "progress",
            "spent_minutes", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by", "created_at", "updated_at", "started_at", "completed_at"]

    def get_assignee_ids(self, obj):
        return list(obj.assignees.values_list("id", flat=True))

    def get_assignee_names(self, obj):
        return [u.display_name for u in obj.assignees.all()]

    def get_comment_count(self, obj):
        return obj.comments.count()

    def get_is_overdue(self, obj):
        from datetime import date
        return bool(obj.due_date and obj.due_date < date.today() and obj.status != "done")

    def get_subtask_total(self, obj):
        return obj.subtasks.count()

    def get_subtask_done(self, obj):
        return obj.subtasks.filter(is_done=True).count()

    def get_progress(self, obj):
        total = obj.subtasks.count()
        if not total:
            return 100 if obj.status == "done" else 0
        return round(obj.subtasks.filter(is_done=True).count() / total * 100)

    def get_spent_minutes(self, obj):
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
        return list(obj.members.values_list("id", flat=True))

    def get_member_names(self, obj):
        return [u.display_name for u in obj.members.all()]

    def get_board_count(self, obj):
        return obj.boards.count()

    def get_card_total(self, obj):
        return TaskCard.objects.filter(board__project=obj).count()

    def get_done_total(self, obj):
        return TaskCard.objects.filter(board__project=obj, status="done").count()


class ProjectActivitySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.display_name", read_only=True, default="系统")

    class Meta:
        model = ProjectActivity
        fields = ["id", "user", "user_name", "action", "target", "created_at"]
