"""统计面板视图：全局统计（管理员） + 个人工作台统计 + 多维趋势/分布/待办聚合"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Notification, OperationLog
from files.models import FileMeta, Folder
from im.models import ChatMessage, SessionMemberSetting
from notes.models import Note
from projects.models import Project, TaskCard

User = get_user_model()


def _unread_messages(user):
    total = 0
    for setting in SessionMemberSetting.objects.filter(user=user).select_related("session"):
        qs = setting.session.messages.exclude(sender=user)
        if setting.last_read_at:
            qs = qs.filter(created_at__gt=setting.last_read_at)
        total += qs.count()
    return total


class GlobalStatsView(APIView):
    """全局统计面板（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        total_storage = FileMeta.objects.filter(is_deleted=False).aggregate(s=Sum("size"))["s"] or 0
        recent_ops = list(
            OperationLog.objects.select_related("user")[:10].values_list("user__username", "module", "action", "target", "created_at")
        )
        today = timezone.now().date()
        return Response({
            "users": User.objects.count(),
            "user_signups_today": User.objects.filter(date_joined__date=today).count(),
            "active_users_7d": User.objects.filter(last_active_at__gte=timezone.now() - timedelta(days=7)).count(),
            "disabled_users": User.objects.filter(is_disabled=True).count(),
            "files": FileMeta.objects.filter(is_deleted=False).count(),
            "storage_bytes": total_storage,
            "storage_gb": round(total_storage / 1024 / 1024 / 1024, 2),
            "folders": Folder.objects.count(),
            "notes": Note.objects.count(),
            "projects": Project.objects.count(),
            "tasks": TaskCard.objects.count(),
            "tasks_done": TaskCard.objects.filter(status="done").count(),
            "messages": ChatMessage.objects.count(),
            "ops_total": OperationLog.objects.count(),
            "ops_today": OperationLog.objects.filter(created_at__date=today).count(),
            "recent_ops": [
                {"username": r[0] or "?", "module": r[1], "action": r[2], "target": r[3], "time": r[4]} for r in recent_ops
            ],
        })


class UserStatsView(APIView):
    """个人工作台统计"""

    def get(self, request):
        user = request.user
        my_files = FileMeta.objects.filter(owner=user, is_deleted=False)
        storage = my_files.aggregate(s=Sum("size"))["s"] or 0
        my_projects = (Project.objects.filter(owner=user) | Project.objects.filter(members=user)).distinct()
        my_open_tasks = TaskCard.objects.filter(assignees=user, status__in=["todo", "doing"])
        return Response({
            "files": my_files.count(),
            "storage_bytes": storage,
            "storage_gb": round(storage / 1024 / 1024 / 1024, 2),
            "folders": Folder.objects.filter(owner=user).count(),
            "notes": Note.objects.filter(owner=user, is_deleted=False).count(),
            "projects": my_projects.count(),
            "my_tasks": my_open_tasks.count(),
            "tasks_done": TaskCard.objects.filter(assignees=user, status="done").count(),
            "unread_notifications": Notification.objects.filter(recipient=user, is_read=False).count(),
            "unread_messages": _unread_messages(user),
            "quota_mb": user.storage_quota_mb,
            "quota_used_pct": round(storage / (user.storage_quota_mb * 1024 * 1024) * 100, 1) if user.storage_quota_mb else 0,
        })


class ActivityTrendView(APIView):
    """近 14 天操作趋势（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        days = 14
        start = timezone.now().date() - timedelta(days=days - 1)
        rows = (
            OperationLog.objects.filter(created_at__date__gte=start)
            .values("created_at__date").annotate(c=Count("id")).order_by("created_at__date")
        )
        by_date = {str(r["created_at__date"]): r["c"] for r in rows}
        labels = [(start + timedelta(days=i)).strftime("%m-%d") for i in range(days)]
        return Response({"labels": labels, "values": [by_date.get(f"{start + timedelta(days=i)}", 0) for i in range(days)]})


class PersonalTrendView(APIView):
    """个人近 14 天产出趋势（笔记/文件/完成任务）"""

    def get(self, request):
        days = 14
        start = timezone.now().date() - timedelta(days=days - 1)
        labels = [(start + timedelta(days=i)).strftime("%m-%d") for i in range(days)]

        def series(qs, field="created_at__date"):
            rows = qs.filter(**{f"{field}__gte": start}).values(field).annotate(c=Count("id"))
            mp = {str(r[field]): r["c"] for r in rows}
            return [mp.get(f"{start + timedelta(days=i)}", 0) for i in range(days)]

        return Response({
            "labels": labels,
            "notes": series(Note.objects.filter(owner=request.user)),
            "files": series(FileMeta.objects.filter(owner=request.user)),
            "tasks_done": series(TaskCard.objects.filter(assignees=request.user, status="done"), "completed_at__date"),
        })


class MyTaskDistributionView(APIView):
    """我的任务分布（按状态 / 优先级）"""

    def get(self, request):
        qs = TaskCard.objects.filter(assignees=request.user)
        return Response({
            "by_status": list(qs.values("status").annotate(c=Count("id"))),
            "by_priority": list(qs.values("priority").annotate(c=Count("id"))),
        })


class FileTypeDistributionView(APIView):
    """我的文件类型分布"""

    def get(self, request):
        rows = (
            FileMeta.objects.filter(owner=request.user, is_deleted=False)
            .values("kind").annotate(c=Count("id"), bytes_sum=Sum("size")).order_by("-bytes_sum")
        )
        return Response({"list": list(rows)})


class AdminUserGrowthView(APIView):
    """近 30 天用户增长（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        days = 30
        start = timezone.now().date() - timedelta(days=days - 1)
        rows = User.objects.filter(date_joined__date__gte=start).values("date_joined__date").annotate(c=Count("id"))
        mp = {str(r["date_joined__date"]): r["c"] for r in rows}
        labels, values, cumulative, total = [], [], [], User.objects.filter(date_joined__date__lt=start).count()
        for i in range(days):
            d = start + timedelta(days=i)
            labels.append(d.strftime("%m-%d"))
            add = mp.get(f"{d}", 0)
            values.append(add)
            total += add
            cumulative.append(total)
        return Response({"labels": labels, "new": values, "cumulative": cumulative})


class AdminModuleUsageView(APIView):
    """模块使用排行（管理员，按操作量）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        by_module = list(OperationLog.objects.values("module").annotate(c=Count("id")).order_by("-c"))
        by_action = list(OperationLog.objects.values("action").annotate(c=Count("id")).order_by("-c"))
        top_users = list(
            OperationLog.objects.values("user__username").annotate(c=Count("id")).order_by("-c")[:10]
        )
        return Response({"by_module": by_module, "by_action": by_action, "top_users": top_users})


class TodoAggregateView(APIView):
    """首页待办聚合：今日到期 / 逾期 / 本周到期 / 未读"""

    def get(self, request):
        user = request.user
        today = timezone.now().date()
        base = TaskCard.objects.filter(assignees=user).exclude(status="done")
        return Response({
            "overdue": base.filter(due_date__lt=today).count(),
            "today": base.filter(due_date=today).count(),
            "week": base.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7)).count(),
            "no_date": base.filter(due_date__isnull=True).count(),
            "unread_notifications": Notification.objects.filter(recipient=user, is_read=False).count(),
            "unread_messages": _unread_messages(user),
            "pinned_notes": Note.objects.filter(owner=user, is_deleted=False, is_pinned=True).count(),
            "starred_files": FileMeta.objects.filter(owner=user, is_deleted=False, is_star=True).count(),
        })
