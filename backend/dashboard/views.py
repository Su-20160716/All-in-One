"""统计面板视图：全局统计（管理员） + 个人工作台统计 + 多维趋势/分布/待办聚合
+ 今日卡片（到期/学习/日程/存储）+ 最近动态 + 卡片顺序同步（F657-F660、F666-F668）
"""
import json
from datetime import timedelta
from functools import wraps

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


def endpoint(methods=("GET",)):
    """视图方法兜底：ValueError → 400，其余异常 → 422，绝不 500"""

    def deco(fn):
        @wraps(fn)
        def impl(self, request, *args, **kwargs):
            try:
                return fn(self, request, *args, **kwargs)
            except ValueError as exc:
                return Response({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:  # noqa: BLE001
                return Response({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status=422)

        return impl

    return deco


def _guard(fn, default=None):
    """跨模块聚合的单模块兜底：出错只降级该模块，不影响整体"""
    try:
        return fn(), ""
    except Exception as exc:  # noqa: BLE001
        return default if default is not None else {}, f"{type(exc).__name__}: {exc}"


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


# ---------------------------------------------------------------------------
# F657 今日到期聚合卡：待办 / 任务 / 公告 跨模块（逐模块兜底）
# ---------------------------------------------------------------------------

class TodayDueView(APIView):
    """GET /api/dashboard/today-due/

    能取多少取多少：每个模块单独 try/except，失败只在该组标记 error，
    其余模块照常返回，整体绝不 500。
    """

    def get(self, request):
        user = request.user
        today = timezone.now().date()

        def _todo():
            from officesuite.models import TodoItem

            qs = TodoItem.objects.filter(owner=user, done=False, due_date=today)
            overdue = TodoItem.objects.filter(owner=user, done=False, due_date__lt=today).count()
            return {
                "count": qs.count(), "overdue": overdue,
                "items": [{"id": t.id, "title": t.title or "未命名待办", "priority": t.priority}
                          for t in qs.order_by("priority")[:5]],
            }

        def _task():
            qs = TaskCard.objects.filter(assignees=user).exclude(status="done").filter(due_date=today)
            overdue = (TaskCard.objects.filter(assignees=user).exclude(status="done")
                       .filter(due_date__lt=today).count())
            return {
                "count": qs.count(), "overdue": overdue,
                "items": [{"id": t.id, "title": t.title, "priority": t.priority, "status": t.status}
                          for t in qs[:5]],
            }

        def _announcement():
            from core.models import Announcement

            qs = Announcement.objects.filter(is_published=True, expires_at__date=today)
            return {
                "count": qs.count(), "overdue": 0,
                "items": [{"id": a.id, "title": a.title, "level": a.level} for a in qs[:5]],
            }

        spec = [
            ("todo", "轻待办", _todo, "/toolbox/office"),
            ("task", "项目任务", _task, "/projects/my-tasks"),
            ("announcement", "今日到期公告", _announcement, "/announcements"),
        ]
        groups, errors = [], []
        for key, label, fn, link in spec:
            data, err = _guard(fn, {"count": 0, "overdue": 0, "items": []})
            groups.append({
                "key": key, "label": label, "count": data.get("count", 0),
                "overdue": data.get("overdue", 0), "items": data.get("items", []),
                "link": link, "error": err,
            })
            if err:
                errors.append({"module": key, "error": err})

        return Response({
            "date": today.isoformat(),
            "total": sum(g["count"] for g in groups),
            "overdue_total": sum(g["overdue"] for g in groups),
            "groups": groups,
            "errors": errors,
            "fetched_at": timezone.now(),
        })


# ---------------------------------------------------------------------------
# F658 今日学习卡（只读调用 learning）
# ---------------------------------------------------------------------------

class TodayLearningView(APIView):
    """GET /api/dashboard/today-learning/?goal=60 —— 今日学习分钟 / 连续天数 / 目标"""

    def get(self, request):
        try:
            goal = int(request.query_params.get("goal") or 60)
        except (TypeError, ValueError):
            goal = 60
        goal = max(0, min(goal, 24 * 60))

        def _learn():
            from learning.models import StudySession

            today = timezone.now().date()
            today_qs = StudySession.objects.filter(owner=request.user, study_date=today)
            minutes = sum(int(s.minutes or 0) for s in today_qs)
            days = set(StudySession.objects.filter(owner=request.user)
                       .values_list("study_date", flat=True))
            # 今天还没学不打断「截至昨天」的连续记录
            cursor = today if today in days else today - timedelta(days=1)
            streak = 0
            while cursor in days:
                streak += 1
                cursor -= timedelta(days=1)
            total_minutes = sum(int(s.minutes or 0) for s in
                                StudySession.objects.filter(owner=request.user))
            return {
                "minutes": minutes,
                "sessions": today_qs.count(),
                "subjects": sorted({s.subject for s in today_qs[:10] if s.subject}),
                "streak": streak,
                "total_minutes": total_minutes,
                "active_days": len(days),
            }

        data, err = _guard(_learn, {
            "minutes": 0, "sessions": 0, "subjects": [], "streak": 0,
            "total_minutes": 0, "active_days": 0,
        })
        percent = round(min(100, data["minutes"] / goal * 100), 1) if goal else 0.0
        return Response({
            **data,
            "goal_minutes": goal,
            "percent": percent,
            "reached": data["minutes"] >= goal if goal else True,
            "date": timezone.now().date().isoformat(),
            "error": err,
            "fetched_at": timezone.now(),
        })


# ---------------------------------------------------------------------------
# F659 今日日程卡：会议 + 值班
# ---------------------------------------------------------------------------

def _display_names(user):
    names = {user.username}
    for attr in ("nickname", "display_name", "first_name"):
        val = getattr(user, attr, "") or ""
        if val:
            names.add(str(val))
    return {n for n in names if n}


def _attendee_hit(attendees, names):
    for item in attendees or []:
        if isinstance(item, str):
            if item in names:
                return True
        elif isinstance(item, dict):
            vals = {str(item.get(k, "")) for k in ("username", "name", "nickname", "label", "display_name")}
            if vals & names:
                return True
    return False


class TodayScheduleView(APIView):
    """GET /api/dashboard/today-schedule/ —— 今日会议与值班（跨模块逐个兜底）"""

    def get(self, request):
        user = request.user
        today = timezone.now().date()
        names = _display_names(user)

        def _meetings():
            from officesuite.models import SuiteEvent

            qs = SuiteEvent.objects.filter(start_at__date=today).order_by("start_at")[:30]
            items = []
            for e in qs:
                mine = e.owner_id == user.id or _attendee_hit(e.attendees, names)
                items.append({
                    "id": e.id, "title": e.title or "未命名日程", "kind": e.kind,
                    "start_at": e.start_at, "end_at": e.end_at, "status": e.status,
                    "mine": mine,
                })
            mine_items = [i for i in items if i["mine"]]
            return {"count": len(mine_items) or len(items), "mine_count": len(mine_items),
                    "items": (mine_items or items)[:6]}

        def _duty():
            from officesuite.models import DutyShift

            qs = DutyShift.objects.filter(duty_date=today).order_by("shift_name")[:30]
            items = []
            for s in qs:
                mine = s.owner_id == user.id or s.member_name in names
                items.append({
                    "id": s.id, "member": s.member_name, "shift": s.shift_name,
                    "date": s.duty_date.isoformat(), "mine": mine,
                    "swapped": bool(s.swapped_to),
                })
            mine_items = [i for i in items if i["mine"]]
            return {"count": len(mine_items) or len(items), "mine_count": len(mine_items),
                    "items": (mine_items or items)[:6]}

        meetings, err_m = _guard(_meetings, {"count": 0, "mine_count": 0, "items": []})
        duty, err_d = _guard(_duty, {"count": 0, "mine_count": 0, "items": []})
        return Response({
            "date": today.isoformat(),
            "meetings": meetings,
            "duty": duty,
            "total": meetings["count"] + duty["count"],
            "errors": [{"module": m, "error": e} for m, e in
                       (("meetings", err_m), ("duty", err_d)) if e],
            "fetched_at": timezone.now(),
        })


# ---------------------------------------------------------------------------
# F660 存储用量卡：总量 + 类型占比迷你条
# ---------------------------------------------------------------------------

class StorageUsageView(APIView):
    """GET /api/dashboard/storage-usage/ —— 我的存储总量与按类型占比"""

    def get(self, request):
        from core.utils import format_size

        def _storage():
            rows = (FileMeta.objects.filter(owner=request.user, is_deleted=False)
                    .values("kind").annotate(c=Count("id"), b=Sum("size")).order_by("-b"))
            by_kind, total, count = [], 0, 0
            for r in rows:
                b = int(r["b"] or 0)
                total += b
                count += int(r["c"] or 0)
                by_kind.append({"kind": r["kind"] or "other", "count": r["c"],
                                "bytes": b, "text": format_size(b), "percent": 0.0})
            for item in by_kind:
                item["percent"] = round(item["bytes"] / total * 100, 1) if total else 0.0
            quota_mb = getattr(request.user, "storage_quota_mb", 0) or 0
            return {
                "total_bytes": total,
                "total_text": format_size(total),
                "file_count": count,
                "quota_mb": quota_mb,
                "quota_text": format_size(quota_mb * 1024 * 1024) if quota_mb else "不限",
                "percent": round(total / (quota_mb * 1024 * 1024) * 100, 1) if quota_mb else 0.0,
                "by_kind": by_kind[:8],
            }

        data, err = _guard(_storage, {
            "total_bytes": 0, "total_text": "0 B", "file_count": 0, "quota_mb": 0,
            "quota_text": "-", "percent": 0.0, "by_kind": [],
        })
        return Response({**data, "error": err, "fetched_at": timezone.now()})


# ---------------------------------------------------------------------------
# F666 最近动态时间线：跨模块最新 10 条
# ---------------------------------------------------------------------------

class RecentActivityView(APIView):
    """GET /api/dashboard/recent-activity/ —— 笔记/文件/任务/公告/通知/会话 最新 10 条"""

    MODULE_LABELS = {
        "note": "笔记", "file": "文件", "task": "任务", "announcement": "公告",
        "notification": "通知", "ai": "AI 会话", "message": "消息", "study": "学习",
    }

    def get(self, request):
        user = request.user
        rows, errors = [], []

        def _add(key, fn, limit=3):
            data, err = _guard(fn, [])
            for it in data[:limit]:
                rows.append({**it, "module": key, "label": self.MODULE_LABELS.get(key, key)})
            if err:
                errors.append({"module": key, "error": err})

        def _notes():
            return [{"id": n.id, "title": n.title or "无标题笔记", "at": n.updated_at, "link": "/notes"}
                    for n in Note.objects.filter(owner=user, is_deleted=False).order_by("-updated_at")[:3]]

        def _files():
            return [{"id": f.id, "title": f.name, "at": f.updated_at, "link": "/files"}
                    for f in FileMeta.objects.filter(owner=user, is_deleted=False).order_by("-updated_at")[:3]]

        def _tasks():
            return [{"id": t.id, "title": t.title, "at": t.updated_at, "link": "/projects/my-tasks"}
                    for t in TaskCard.objects.filter(assignees=user).order_by("-updated_at")[:3]]

        def _announcements():
            from core.models import Announcement

            return [{"id": a.id, "title": a.title, "at": a.created_at, "link": "/announcements"}
                    for a in Announcement.objects.filter(is_published=True).order_by("-created_at")[:2]]

        def _notifications():
            return [{"id": n.id, "title": n.title, "at": n.created_at, "link": "/dashboard"}
                    for n in Notification.objects.filter(recipient=user).order_by("-created_at")[:3]]

        def _conversations():
            from assistant.models import AIConversation

            return [{"id": c.id, "title": c.title or "AI 对话", "at": c.updated_at, "link": "/ai"}
                    for c in AIConversation.objects.filter(owner=user).order_by("-updated_at")[:2]]

        def _messages():
            total = 0
            for setting in SessionMemberSetting.objects.filter(user=user).select_related("session"):
                qs = setting.session.messages.exclude(sender=user)
                if setting.last_read_at:
                    qs = qs.filter(created_at__gt=setting.last_read_at)
                total += qs.count()
            return [{"id": 0, "title": f"{total} 条未读消息", "at": timezone.now(), "link": "/im"}] if total else []

        _add("note", _notes)
        _add("file", _files)
        _add("task", _tasks)
        _add("announcement", _announcements, limit=2)
        _add("notification", _notifications)
        _add("message", _messages, limit=1)

        rows.sort(key=lambda r: r["at"], reverse=True)
        for r in rows[:10]:
            r["at_text"] = _rel_time(r["at"])
        return Response({
            "list": rows[:10], "total": len(rows[:10]), "errors": errors,
            "fetched_at": timezone.now(),
        })


def _rel_time(dt):
    if not dt:
        return ""
    diff = timezone.now() - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    if seconds < 86400 * 30:
        return f"{seconds // 86400} 天前"
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# F668 卡片顺序跨浏览器同步到服务端
# ---------------------------------------------------------------------------

class CardOrderView(APIView):
    """GET 读取 / PUT(或 POST) 保存我的仪表盘卡片顺序"""

    @endpoint(("GET",))
    def get(self, request):
        from dashboard.models import DashboardCardOrder

        obj = DashboardCardOrder.objects.filter(owner=request.user).first()
        return Response({
            "order": (obj.order if obj else []) or [],
            "updated_at": obj.updated_at if obj else None,
            "fetched_at": timezone.now(),
        })

    @endpoint(("PUT", "POST", "PATCH"))
    def put(self, request):
        from dashboard.models import DashboardCardOrder

        order = request.data.get("order")
        if not isinstance(order, list):
            raise ValueError("order 需为字符串数组")
        if not all(isinstance(x, str) for x in order):
            raise ValueError("order 数组元素必须是字符串")
        order = [x[:64] for x in order[:60]]
        obj, _ = DashboardCardOrder.objects.get_or_create(owner=request.user)
        obj.order = order
        obj.save()
        return Response({"order": obj.order, "updated_at": obj.updated_at, "saved": True})

    post = put
    patch = put


class DashboardLayoutView(APIView):
    """F28/F29 工作台布局与卡片开关：GET 读取 / PUT 保存"""

    @endpoint(("GET",))
    def get(self, request):
        from dashboard.models import DashboardCardOrder

        obj = DashboardCardOrder.objects.filter(owner=request.user).first()
        return Response({
            "order": (obj.order if obj else []) or [],
            "enabled": (obj.enabled if obj else []) or [],
            "layout": (obj.layout if obj else {}) or {},
            "updated_at": obj.updated_at if obj else None,
        })

    @endpoint(("PUT", "POST", "PATCH"))
    def put(self, request):
        from dashboard.models import DashboardCardOrder

        payload = request.data if isinstance(request.data, dict) else {}
        layout = payload.get("layout")
        if layout is not None and not isinstance(layout, dict):
            raise ValueError("layout 需为对象")
        order = payload.get("order")
        if order is None and isinstance(layout, dict):
            order = layout.get("order")
        enabled = payload.get("enabled")
        if enabled is None and isinstance(layout, dict):
            enabled = layout.get("enabled")
        obj, _ = DashboardCardOrder.objects.get_or_create(owner=request.user)
        if order is not None:
            if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
                raise ValueError("order 需为字符串数组")
            obj.order = [x[:64] for x in order[:60]]
        if enabled is not None:
            if not isinstance(enabled, list) or not all(isinstance(x, str) for x in enabled):
                raise ValueError("enabled 需为字符串数组")
            obj.enabled = [x[:64] for x in enabled[:60]]
        if layout is not None:
            if len(json.dumps(layout, ensure_ascii=False)) > 20000:
                raise ValueError("layout 过大（上限 20KB）")
            obj.layout = layout
        obj.save()
        return Response({
            "saved": True, "order": obj.order, "enabled": obj.enabled,
            "layout": obj.layout, "updated_at": obj.updated_at,
        })


class DailySummaryView(APIView):
    """F30 每日工作摘要：今天新增/完成、写作、上传、消息、专注"""

    @endpoint(("GET",))
    def get(self, request):
        from datetime import datetime, time

        from learning.models import StudySession
        from notes.models import WordActivity
        from projects.models import TaskCard

        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, time.min))
        notes_new = Note.objects.filter(owner=request.user, created_at__gte=start).count()
        cards_done = TaskCard.objects.filter(
            assignees=request.user, status="done", completed_at__gte=start
        ).distinct().count()
        files_new = FileMeta.objects.filter(
            owner=request.user, is_deleted=False, created_at__gte=start
        ).count()
        messages = ChatMessage.objects.filter(sender=request.user, created_at__gte=start).count()
        words = WordActivity.objects.filter(owner=request.user, date=today).values_list("delta", flat=True).first() or 0
        focus = StudySession.objects.filter(owner=request.user, study_date=today).aggregate(
            m=Sum("minutes"))["m"] or 0
        items = [
            {"key": "notes", "label": "新增笔记", "value": notes_new, "unit": "篇"},
            {"key": "cards", "label": "完成卡片", "value": cards_done, "unit": "张"},
            {"key": "words", "label": "写作字数", "value": words, "unit": "字"},
            {"key": "files", "label": "上传文件", "value": files_new, "unit": "个"},
            {"key": "messages", "label": "发送消息", "value": messages, "unit": "条"},
            {"key": "focus", "label": "专注时长", "value": focus, "unit": "分钟"},
        ]
        active = sum(1 for i in items if i["value"])
        return Response({
            "date": today.isoformat(), "items": items, "active_kinds": active,
            "headline": f"今天有 {active} 类活动，写作 {words} 字，完成 {cards_done} 张卡片",
        })
