"""统计面板视图：全局统计（管理员） + 个人工作台统计 + 多维趋势/分布/待办聚合
+ 今日卡片（到期/学习/日程/存储）+ 最近动态 + 卡片顺序同步（F657-F660、F666-F668）
#331-#349：卡片尺寸/分组、环比对比、活动筛选、提及/里程碑/项目健康卡片、逾期延期、每日简报推送
"""
import json
import logging
from datetime import datetime, timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Notification, OperationLog
from core.validators import as_int, parse_bool
from files.models import FileMeta, Folder
from im.models import ChatMessage, SessionMemberSetting
from notes.models import Note
from projects.models import Project, TaskCard

logger = logging.getLogger(__name__)

User = get_user_model()

# #331 卡片宽度只允许半宽/全宽（前端据此栅格渲染）
LAYOUT_SIZES = ("half", "full")
# #332 卡片分组：canonical key + 中文标签（校验时两者都接受，保存原样以支持 round-trip）
LAYOUT_GROUP_LABELS = {
    "work": "工作", "study": "学习", "system": "系统", "personal": "个人", "im": "消息",
}
LAYOUT_GROUPS = tuple(LAYOUT_GROUP_LABELS)
ALLOWED_GROUPS = set(LAYOUT_GROUPS) | set(LAYOUT_GROUP_LABELS.values())


def _group_options():
    return [{"key": k, "label": v} for k, v in LAYOUT_GROUP_LABELS.items()]



def endpoint(methods=("GET",)):
    """视图方法兜底：#349 每个卡片统一结构化错误，前端可单卡重试

    ValueError → 400（参数/业务错误，不可重试）；其余异常 → 422（可重试），
    两者都带可直接展示的 message 与 code/detail/retryable/card，
    前端不必再猜 422 的原始内容；DRF 自身异常（权限/校验）仍交给全局处理器。
    """

    def deco(fn):
        @wraps(fn)
        def impl(self, request, *args, **kwargs):
            card = type(self).__name__
            try:
                return fn(self, request, *args, **kwargs)
            except APIException:
                raise
            except ValueError as exc:
                return Response({
                    "ok": False, "code": 400, "error": str(exc), "message": str(exc),
                    "detail": str(exc), "retryable": False, "card": card,
                }, status=400)
            except Exception as exc:  # noqa: BLE001
                logger.exception("仪表盘卡片加载失败 card=%s", card)
                return Response({
                    "ok": False, "code": 422,
                    "error": f"{type(exc).__name__}: {exc}",
                    "message": "卡片数据加载失败，请稍后重试",
                    "detail": f"{type(exc).__name__}",
                    "retryable": True, "card": card,
                }, status=422)

        return impl

    return deco


def _guard(fn, default=None):
    """跨模块聚合的单模块兜底：出错只降级该模块，不影响整体"""
    try:
        return fn(), ""
    except Exception as exc:  # noqa: BLE001
        return default if default is not None else {}, f"{type(exc).__name__}: {exc}"


def _error_item(module, detail, label=""):
    """#349 单模块降级时的结构化错误项（保留 error 兼容旧字段）"""
    name = label or module
    return {
        "module": module, "error": detail, "detail": detail,
        "message": f"{name}数据加载失败", "retryable": True,
    }


_EPOCH = timezone.make_aware(datetime(1970, 1, 1))


def _unread_messages(user):
    """单条聚合查询统计未读消息（原来每个会话一次 COUNT）。

    #82：与 im._with_unread 口径一致——排除已删除、已撤回、以及当前用户
    deleted_for 的消息，否则这些消息永远无法被「已读」清零。
    """
    # deleted_for 是多对多：用子查询排除（直接 ~Q(...deleted_for=user) 会 LEFT JOIN
    # 出 NULL，把没有删除记录的消息也一起排除掉）
    deleted_for_me = (
        ChatMessage.deleted_for.through.objects.filter(user_id=user.id)
        .values("chatmessage_id")
    )
    rows = SessionMemberSetting.objects.filter(user=user).annotate(
        _unread=Count(
            "session__messages",
            filter=Q(session__messages__created_at__gt=Coalesce(F("last_read_at"), Value(_EPOCH)))
            & ~Q(session__messages__sender=user)
            & ~Q(session__messages__is_deleted=True)
            & ~Q(session__messages__is_recalled=True)
            & ~Q(session__messages__id__in=Subquery(deleted_for_me)),
        )
    )
    return rows.aggregate(total=Sum("_unread"))["total"] or 0


class GlobalStatsView(APIView):
    """全局统计面板（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        total_storage = FileMeta.objects.filter(is_deleted=False).aggregate(s=Sum("size"))["s"] or 0
        recent_ops = list(
            OperationLog.objects.select_related("user")[:10].values_list("user__username", "module", "action", "target", "created_at")
        )
        today = timezone.localdate()
        return Response({
            "users": User.objects.count(),
            "user_signups_today": User.objects.filter(date_joined__date=today).count(),
            "active_users_7d": User.objects.filter(last_active_at__gte=timezone.now() - timedelta(days=7)).count(),
            "disabled_users": User.objects.filter(is_disabled=True).count(),
            "files": FileMeta.objects.filter(is_deleted=False).count(),
            "storage_bytes": total_storage,
            "storage_gb": round(total_storage / 1024 / 1024 / 1024, 2),
            "folders": Folder.objects.count(),
            "notes": Note.objects.filter(is_deleted=False).count(),
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


def _visible_unread_notifications(user):
    """未读通知数（#337 与通知列表口径一致：未到期的稍后提醒不计入）"""
    now = timezone.now()
    return Notification.objects.filter(recipient=user, is_read=False).filter(
        Q(snooze_until__isnull=True) | Q(snooze_until__lte=now)
    ).count()


class UserStatsView(APIView):
    """个人工作台统计"""

    @endpoint(("GET",))
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
            "unread_notifications": _visible_unread_notifications(user),
            "unread_messages": _unread_messages(user),
            "quota_mb": user.storage_quota_mb,
            "quota_used_pct": round(storage / (user.storage_quota_mb * 1024 * 1024) * 100, 1) if user.storage_quota_mb else 0,
        })


class ActivityTrendView(APIView):
    """近 14 天操作趋势（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        days = 14
        start = timezone.localdate() - timedelta(days=days - 1)
        rows = (
            OperationLog.objects.filter(created_at__date__gte=start)
            .values("created_at__date").annotate(c=Count("id")).order_by("created_at__date")
        )
        by_date = {str(r["created_at__date"]): r["c"] for r in rows}
        labels = [(start + timedelta(days=i)).strftime("%m-%d") for i in range(days)]
        return Response({"labels": labels, "values": [by_date.get(f"{start + timedelta(days=i)}", 0) for i in range(days)]})


class PersonalTrendView(APIView):
    """个人近 14 天产出趋势（笔记/文件/完成任务）

    #342 compare=1 时额外返回上一周期（前 14 天）序列，按 index 对齐供折线虚线叠加，
    并给出每个序列的增减百分比（previous=0 时 percent=null，前端显示「新增」）。
    """

    @endpoint(("GET",))
    def get(self, request):
        days = 14
        today = timezone.localdate()
        start = today - timedelta(days=days - 1)
        prev_start = start - timedelta(days=days)
        labels = [(start + timedelta(days=i)).strftime("%m-%d") for i in range(days)]

        def series(qs, field, begin):
            rows = (qs.filter(**{f"{field}__gte": begin})
                    .values(field).annotate(c=Count("id")))
            mp = {str(r[field]): r["c"] for r in rows}
            return [mp.get(str(begin + timedelta(days=i)), 0) for i in range(days)]

        sources = {
            "notes": (Note.objects.filter(owner=request.user), "created_at__date"),
            "files": (FileMeta.objects.filter(owner=request.user), "created_at__date"),
            "tasks_done": (
                TaskCard.objects.filter(assignees=request.user, status="done"), "completed_at__date"
            ),
        }
        current, previous = {}, {}
        for key, (qs, field) in sources.items():
            current[key] = series(qs, field, start)
            previous[key] = series(qs, field, prev_start)

        payload = {"labels": labels, **current, "range": {"start": start.isoformat(),
                                                          "end": today.isoformat()}}
        if parse_bool(request.query_params.get("compare"), default=False, field="compare"):
            change = {}
            for key, values in current.items():
                cur, prev = sum(values), sum(previous[key])
                change[key] = {
                    "current": cur, "previous": prev, "diff": cur - prev,
                    "percent": (round((cur - prev) / prev * 100, 1) if prev else None),
                }
            payload["compare"] = {
                "labels": [(prev_start + timedelta(days=i)).strftime("%m-%d") for i in range(days)],
                "range": {"start": prev_start.isoformat(),
                          "end": (start - timedelta(days=1)).isoformat()},
                **previous,
                "change": change,
            }
        return Response(payload)


class MyTaskDistributionView(APIView):
    """我的任务分布（按状态 / 优先级）"""

    @endpoint(("GET",))
    def get(self, request):
        qs = TaskCard.objects.filter(assignees=request.user)
        return Response({
            "by_status": list(qs.values("status").annotate(c=Count("id"))),
            "by_priority": list(qs.values("priority").annotate(c=Count("id"))),
        })


class FileTypeDistributionView(APIView):
    """我的文件类型分布"""

    @endpoint(("GET",))
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
        start = timezone.localdate() - timedelta(days=days - 1)
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

    @endpoint(("GET",))
    def get(self, request):
        user = request.user
        today = timezone.localdate()
        base = TaskCard.objects.filter(assignees=user).exclude(status="done")
        return Response({
            "overdue": base.filter(due_date__lt=today).count(),
            "today": base.filter(due_date=today).count(),
            "week": base.filter(due_date__gte=today, due_date__lte=today + timedelta(days=7)).count(),
            "no_date": base.filter(due_date__isnull=True).count(),
            "unread_notifications": _visible_unread_notifications(user),
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

    #348 include_overdue=1：每组额外返回 overdue_items（含一键延期一天的 action），
    调用 POST /api/dashboard/postpone-due/ {kind,id,days} 即可，也可直接走既有
    项目任务 PATCH /api/projects/cards/<id>/ 或待办 PATCH /api/officesuite/todo/<id>/update/。
    """

    @endpoint(("GET",))
    def get(self, request):
        user = request.user
        today = timezone.localdate()
        include_overdue = parse_bool(
            request.query_params.get("include_overdue"), default=False, field="include_overdue"
        )

        def _postpone(kind, pk, due_date):
            """一键延期的 action 描述（前端按 method/url/body 直接调用）"""
            return {
                "method": "POST",
                "url": "/api/dashboard/postpone-due/",
                "body": {"kind": kind, "id": pk, "days": 1},
                "next_due_date": (due_date + timedelta(days=1)).isoformat(),
            }

        def _todo():
            from officesuite.models import TodoItem

            qs = TodoItem.objects.filter(owner=user, done=False, due_date=today)
            late = TodoItem.objects.filter(owner=user, done=False, due_date__lt=today)
            data = {
                "count": qs.count(), "overdue": late.count(),
                "items": [{"id": t.id, "title": t.title or "未命名待办", "priority": t.priority}
                          for t in qs.order_by("priority")[:5]],
                "overdue_items": [],
            }
            if include_overdue:
                data["overdue_items"] = [
                    {
                        "id": t.id, "title": t.title or "未命名待办", "priority": t.priority,
                        "due_date": t.due_date.isoformat(),
                        "days_overdue": (today - t.due_date).days,
                        "postpone": _postpone("todo", t.id, t.due_date),
                    }
                    for t in late.order_by("due_date")[:10]
                ]
            return data

        def _task():
            qs = TaskCard.objects.filter(assignees=user).exclude(status="done").filter(due_date=today)
            late = (TaskCard.objects.filter(assignees=user).exclude(status="done")
                    .filter(due_date__lt=today))
            data = {
                "count": qs.count(), "overdue": late.count(),
                "items": [{"id": t.id, "title": t.title, "priority": t.priority, "status": t.status}
                          for t in qs[:5]],
                "overdue_items": [],
            }
            if include_overdue:
                data["overdue_items"] = [
                    {
                        "id": t.id, "title": t.title, "priority": t.priority, "status": t.status,
                        "due_date": t.due_date.isoformat(),
                        "days_overdue": (today - t.due_date).days,
                        "postpone": _postpone("task", t.id, t.due_date),
                    }
                    for t in late.order_by("due_date")[:10]
                ]
            return data

        def _announcement():
            from core.models import Announcement

            qs = Announcement.objects.filter(is_published=True, expires_at__date=today)
            return {
                "count": qs.count(), "overdue": 0,
                "items": [{"id": a.id, "title": a.title, "level": a.level} for a in qs[:5]],
                "overdue_items": [],
            }

        spec = [
            ("todo", "轻待办", _todo, "/toolbox/office"),
            ("task", "项目任务", _task, "/projects/my-tasks"),
            ("announcement", "今日到期公告", _announcement, "/announcements"),
        ]
        groups, errors = [], []
        for key, label, fn, link in spec:
            data, err = _guard(fn, {"count": 0, "overdue": 0, "items": [], "overdue_items": []})
            groups.append({
                "key": key, "label": label, "count": data.get("count", 0),
                "overdue": data.get("overdue", 0), "items": data.get("items", []),
                "overdue_items": data.get("overdue_items", []),
                "link": link, "error": err,
            })
            if err:
                errors.append(_error_item(key, err, label))

        return Response({
            "ok": True,
            "date": today.isoformat(),
            "total": sum(g["count"] for g in groups),
            "overdue_total": sum(g["overdue"] for g in groups),
            "include_overdue": include_overdue,
            "groups": groups,
            "errors": errors,
            "fetched_at": timezone.now(),
        })


# ---------------------------------------------------------------------------
# F658 今日学习卡（只读调用 learning）
# ---------------------------------------------------------------------------

class TodayLearningView(APIView):
    """GET /api/dashboard/today-learning/?goal=60 —— 今日学习分钟 / 连续天数 / 目标"""

    @endpoint(("GET",))
    def get(self, request):
        try:
            goal = int(request.query_params.get("goal") or 60)
        except (TypeError, ValueError):
            goal = 60
        goal = max(0, min(goal, 24 * 60))

        def _learn():
            from learning.models import StudySession

            today = timezone.localdate()
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
            "ok": True,
            "goal_minutes": goal,
            "percent": percent,
            "reached": data["minutes"] >= goal if goal else True,
            "date": timezone.localdate().isoformat(),
            "error": err,
            "message": "学习数据加载失败" if err else "",
            "retryable": bool(err),
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

    @endpoint(("GET",))
    def get(self, request):
        user = request.user
        today = timezone.localdate()
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
            return {"count": len(mine_items), "mine_count": len(mine_items),
                    "items": mine_items[:6]}

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
            return {"count": len(mine_items), "mine_count": len(mine_items),
                    "items": mine_items[:6]}

        meetings, err_m = _guard(_meetings, {"count": 0, "mine_count": 0, "items": []})
        duty, err_d = _guard(_duty, {"count": 0, "mine_count": 0, "items": []})
        return Response({
            "ok": True,
            "date": today.isoformat(),
            "meetings": meetings,
            "duty": duty,
            "total": meetings["count"] + duty["count"],
            "errors": [_error_item(m, e, "日程" if m == "meetings" else "值班")
                       for m, e in (("meetings", err_m), ("duty", err_d)) if e],
            "fetched_at": timezone.now(),
        })


# ---------------------------------------------------------------------------
# F660 存储用量卡：总量 + 类型占比迷你条
# ---------------------------------------------------------------------------

class StorageUsageView(APIView):
    """GET /api/dashboard/storage-usage/ —— 我的存储总量与按类型占比"""

    @endpoint(("GET",))
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
        return Response({**data, "ok": True, "error": err,
                         "message": "存储用量加载失败" if err else "",
                         "retryable": bool(err), "fetched_at": timezone.now()})


# ---------------------------------------------------------------------------
# F666 最近动态时间线：跨模块最新 10 条
# ---------------------------------------------------------------------------

class RecentActivityView(APIView):
    """GET /api/dashboard/recent-activity/ —— 笔记/文件/任务/公告/通知/会话 最新动态

    #343 module=notes|files|tasks|notifications|messages（可逗号分隔、也接受单数/announcement）
    只查指定模块，返回条数用 limit（默认 10，上限 30）。
    """

    MODULE_LABELS = {
        "note": "笔记", "file": "文件", "task": "任务", "announcement": "公告",
        "notification": "通知", "ai": "AI 会话", "message": "消息", "study": "学习",
    }
    MODULE_ALIASES = {
        "note": "note", "notes": "note",
        "file": "file", "files": "file",
        "task": "task", "tasks": "task",
        "notification": "notification", "notifications": "notification",
        "message": "message", "messages": "message",
        "announcement": "announcement", "announcements": "announcement",
    }

    def _parse_modules(self, request):
        raw = str(request.query_params.get("module") or "").strip().lower()
        if not raw:
            return None
        keys, unknown = [], []
        for token in raw.replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            key = self.MODULE_ALIASES.get(token)
            if key is None:
                unknown.append(token)
            elif key not in keys:
                keys.append(key)
        if unknown:
            raise ValueError(f"module 取值不合法：{'/'.join(unknown)}")
        return keys

    @endpoint(("GET",))
    def get(self, request):
        user = request.user
        rows, errors = [], []
        modules = self._parse_modules(request)
        limit = as_int(request.query_params.get("limit"), default=10, field="limit",
                       minimum=1, maximum=30)

        def _add(key, fn, per_limit=3):
            if modules is not None and key not in modules:
                return
            take = per_limit
            data, err = _guard(lambda: fn(take), [])
            for it in data[:take]:
                rows.append({**it, "module": key, "label": self.MODULE_LABELS.get(key, key)})
            if err:
                errors.append(_error_item(key, err, self.MODULE_LABELS.get(key, key)))

        def _notes(n=3):
            return [{"id": x.id, "title": x.title or "无标题笔记", "at": x.updated_at, "link": "/notes"}
                    for x in Note.objects.filter(owner=user, is_deleted=False).order_by("-updated_at")[:n]]

        def _files(n=3):
            return [{"id": x.id, "title": x.name, "at": x.updated_at, "link": "/files"}
                    for x in FileMeta.objects.filter(owner=user, is_deleted=False).order_by("-updated_at")[:n]]

        def _tasks(n=3):
            return [{"id": x.id, "title": x.title, "at": x.updated_at, "link": "/projects/my-tasks"}
                    for x in TaskCard.objects.filter(assignees=user).order_by("-updated_at")[:n]]

        def _announcements(n=2):
            from core.models import Announcement

            return [{"id": x.id, "title": x.title, "at": x.created_at, "link": "/announcements"}
                    for x in Announcement.objects.filter(is_published=True).order_by("-created_at")[:n]]

        def _notifications(n=3):
            return [{"id": x.id, "title": x.title, "at": x.created_at, "link": x.link or "/dashboard"}
                    for x in Notification.objects.filter(recipient=user).order_by("-created_at")[:n]]

        def _conversations(n=2):
            from assistant.models import AIConversation

            return [{"id": x.id, "title": x.title or "AI 对话", "at": x.updated_at, "link": "/ai"}
                    for x in AIConversation.objects.filter(owner=user).order_by("-updated_at")[:n]]

        def _messages(n=1):
            total = 0
            for setting in SessionMemberSetting.objects.filter(user=user).select_related("session"):
                qs = setting.session.messages.exclude(sender=user)
                if setting.last_read_at:
                    qs = qs.filter(created_at__gt=setting.last_read_at)
                total += qs.count()
            return [{"id": 0, "title": f"{total} 条未读消息", "at": timezone.now(), "link": "/im"}] if total else []

        # 未筛选时沿用原卡片密度；筛选单模块时给出更多条目
        _add("note", _notes, limit if modules is not None else 3)
        _add("file", _files, limit if modules is not None else 3)
        _add("task", _tasks, limit if modules is not None else 3)
        _add("announcement", _announcements, limit if modules is not None else 2)
        _add("notification", _notifications, limit if modules is not None else 3)
        _add("message", _messages, limit if modules is not None else 1)

        rows.sort(key=lambda r: r["at"], reverse=True)
        shown = rows[:limit]
        for r in shown:
            r["at_text"] = _rel_time(r["at"])
        return Response({
            "ok": True,
            "list": shown,
            "total": len(shown),
            "module": modules,
            "modules": [{"key": k, "label": self.MODULE_LABELS[k]}
                        for k in ("note", "file", "task", "notification", "message", "announcement")],
            "errors": errors,
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

def _normalize_card_entries(items, field="order"):
    """#331/#332 卡片条目校验：既支持纯字符串 key，也支持 {key,size,group} 对象

    只做校验与安全截断，其余字段原样保留（round-trip 不变）。
    """
    if not isinstance(items, list):
        raise ValueError(f"{field} 需为数组")
    out = []
    for raw in items[:60]:
        if isinstance(raw, str):
            out.append(raw[:64])
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"{field} 元素必须是字符串或对象")
        key = raw.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{field} 对象的 key 不能为空")
        size = raw.get("size")
        if size is not None and size not in LAYOUT_SIZES:
            raise ValueError(f"size 只能是 {'/'.join(LAYOUT_SIZES)}")
        group = raw.get("group")
        if group is not None and group not in ALLOWED_GROUPS:
            raise ValueError(f"group 只能是 {'/'.join(LAYOUT_GROUPS)} 或其中文标签")
        out.append({**raw, "key": key.strip()[:64]})
    return out


def _validate_layout_meta(node):
    """递归校验 layout 内任意层级的 size/group 取值（#331/#332）"""
    if isinstance(node, dict):
        size = node.get("size")
        if size is not None and size not in LAYOUT_SIZES:
            raise ValueError(f"卡片 size 只能是 {'/'.join(LAYOUT_SIZES)}")
        group = node.get("group")
        if group is not None and group not in ALLOWED_GROUPS:
            raise ValueError(f"卡片 group 只能是 {'/'.join(LAYOUT_GROUPS)} 或其中文标签")
        for value in node.values():
            _validate_layout_meta(value)
    elif isinstance(node, list):
        for value in node:
            _validate_layout_meta(value)


class CardOrderView(APIView):
    """GET 读取 / PUT(或 POST) 保存我的仪表盘卡片顺序

    #332：order 条目可带 group（work/study/system/personal/im），前端渲染分组标题。
    """

    @endpoint(("GET",))
    def get(self, request):
        from dashboard.models import DashboardCardOrder

        obj = DashboardCardOrder.objects.filter(owner=request.user).first()
        return Response({
            "order": (obj.order if obj else []) or [],
            "updated_at": obj.updated_at if obj else None,
            "groups": _group_options(),
            "fetched_at": timezone.now(),
        })

    @endpoint(("PUT", "POST", "PATCH"))
    def put(self, request):
        from dashboard.models import DashboardCardOrder

        payload = request.data if isinstance(request.data, dict) else {}
        order = _normalize_card_entries(payload.get("order"), field="order")
        obj, _ = DashboardCardOrder.objects.get_or_create(owner=request.user)
        obj.order = order
        obj.save()
        return Response({"order": obj.order, "updated_at": obj.updated_at, "saved": True})

    post = put
    patch = put


class DashboardLayoutView(APIView):
    """F28/F29 工作台布局与卡片开关：GET 读取 / PUT 保存

    #331：layout 内的卡片条目可带 size=half/full（校验非法值），随布局一起保存。
    """

    @endpoint(("GET",))
    def get(self, request):
        from dashboard.models import DashboardCardOrder

        obj = DashboardCardOrder.objects.filter(owner=request.user).first()
        return Response({
            "order": (obj.order if obj else []) or [],
            "enabled": (obj.enabled if obj else []) or [],
            "layout": (obj.layout if obj else {}) or {},
            "updated_at": obj.updated_at if obj else None,
            "allowed_sizes": list(LAYOUT_SIZES),
            "allowed_groups": _group_options(),
        })

    @endpoint(("PUT", "POST", "PATCH"))
    def put(self, request):
        from dashboard.models import DashboardCardOrder

        payload = request.data if isinstance(request.data, dict) else {}
        layout = payload.get("layout")
        if layout is not None and not isinstance(layout, dict):
            raise ValueError("layout 需为对象")
        if isinstance(layout, dict):
            _validate_layout_meta(layout)
        order = payload.get("order")
        if order is None and isinstance(layout, dict):
            order = layout.get("order")
        enabled = payload.get("enabled")
        if enabled is None and isinstance(layout, dict):
            enabled = layout.get("enabled")
        obj, _ = DashboardCardOrder.objects.get_or_create(owner=request.user)
        if order is not None:
            obj.order = _normalize_card_entries(order, field="order")
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


def _summary_payload(user):
    """今日工作摘要的计算部分（手动查看与定时推送共用）"""
    from datetime import datetime, time

    from learning.models import StudySession
    from notes.models import WordActivity

    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, time.min))
    notes_new = Note.objects.filter(owner=user, created_at__gte=start).count()
    cards_done = TaskCard.objects.filter(
        assignees=user, status="done", completed_at__gte=start
    ).distinct().count()
    files_new = FileMeta.objects.filter(
        owner=user, is_deleted=False, created_at__gte=start
    ).count()
    messages = ChatMessage.objects.filter(sender=user, created_at__gte=start).count()
    words = WordActivity.objects.filter(owner=user, date=today).values_list("delta", flat=True).first() or 0
    focus = StudySession.objects.filter(owner=user, study_date=today).aggregate(
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
    return {
        "date": today.isoformat(), "items": items, "active_kinds": active,
        "headline": f"今天有 {active} 类活动，写作 {words} 字，完成 {cards_done} 张卡片",
    }


def _daily_schedule(user):
    """#347 每日简报推送配置：enabled / time / next_push_at（下次触发时间）"""
    from core.models import NotificationSetting

    cfg = NotificationSetting.objects.filter(user=user, category="system").first()
    enabled = bool(cfg and cfg.daily_push_enabled and cfg.daily_push_time)
    result = {
        "enabled": enabled,
        "time": cfg.daily_push_time.strftime("%H:%M") if cfg and cfg.daily_push_time else "",
        "next_push_at": None,
    }
    if enabled:
        now = timezone.localtime()
        fire_at = timezone.make_aware(datetime.combine(now.date(), cfg.daily_push_time))
        if fire_at <= now:
            fire_at += timedelta(days=1)
        result["next_push_at"] = fire_at
    return result


class DailySummaryView(APIView):
    """F30 每日工作摘要 + #347 最近一期推送与定时配置

    GET 返回今日摘要，并附带 schedule（推送时间/下次触发）与 latest_push（最近一期简报），
    仪表盘卡片直接展示 latest_push；定时触发见 POST /api/dashboard/daily-summary/push/。
    """

    @endpoint(("GET",))
    def get(self, request):
        from dashboard.models import DailySummaryPush

        payload = _summary_payload(request.user)
        latest = (DailySummaryPush.objects.filter(owner=request.user)
                  .select_related("notification").first())
        return Response({
            **payload,
            "ok": True,
            "schedule": _daily_schedule(request.user),
            "latest_push": {
                "id": latest.id,
                "date": latest.push_date.isoformat(),
                "title": latest.title,
                "headline": latest.headline,
                "items": latest.items,
                "notification_id": latest.notification_id,
                "pushed_at": latest.created_at,
            } if latest else None,
        })


class DailySummaryPushView(APIView):
    """#347 发送每日简报：POST /api/dashboard/daily-summary/push/

    body（均可选）：
      due=1   仅当到达用户设定时间且今天还没推送过时发送（定时任务/前端心跳调用）
      force=1 忽略「今天已推送」去重，立即再发一条
    推送走 core.models.notify（category=system 站内信，自动尊重分类开关与免打扰）。
    """

    @endpoint(("POST",))
    def post(self, request):
        from core.models import notify
        from dashboard.models import DailySummaryPush

        payload = request.data if isinstance(request.data, dict) else {}
        due_only = parse_bool(payload.get("due"), default=False, field="due")
        force = parse_bool(payload.get("force"), default=False, field="force")
        user = request.user
        today = timezone.localdate()
        schedule = _daily_schedule(user)
        existing = DailySummaryPush.objects.filter(owner=user, push_date=today).first()
        if existing and not force:
            return Response({
                "ok": True, "pushed": False, "reason": "already_pushed",
                "schedule": schedule, "notification_id": existing.notification_id,
            })
        if due_only:
            if not schedule["enabled"]:
                return Response({"ok": True, "pushed": False, "reason": "disabled",
                                 "schedule": schedule})
            fire_at = datetime.strptime(schedule["time"], "%H:%M").time()
            if timezone.localtime().time() < fire_at:
                return Response({"ok": True, "pushed": False, "reason": "not_due",
                                 "schedule": schedule})

        data = _summary_payload(user)
        notif = notify(
            user,
            title=f"每日简报 · {data['date']}",
            content=data["headline"],
            category="system",
            level="info",
            link="/dashboard",
        )
        record, _ = DailySummaryPush.objects.update_or_create(
            owner=user, push_date=today,
            defaults={
                "title": f"每日简报 · {data['date']}",
                "headline": data["headline"],
                "items": data["items"],
                "notification": notif,
            },
        )
        return Response({
            "ok": True,
            "pushed": True,
            "reason": "forced" if existing else "ok",
            "suppressed": notif is None,
            "notification_id": notif.id if notif else None,
            "schedule": schedule,
            "item": {
                "id": record.id, "date": record.push_date.isoformat(),
                "title": record.title, "headline": record.headline, "items": record.items,
            },
        })


class PostponeDueView(APIView):
    """#348 逾期项一键延期：POST /api/dashboard/postpone-due/

    body: {kind: task|todo, id: <对象ID>, days: 1}（days 默认 1，1~30）
    只允许操作自己的任务（assignees）/待办（owner）；
    等价手动调用：PATCH /api/projects/cards/<id>/ 或 PATCH /api/officesuite/todo/<id>/update/。
    """

    @endpoint(("POST",))
    def post(self, request):
        kind = str(request.data.get("kind") or "").strip()
        pk = as_int(request.data.get("id"), field="id", minimum=1)
        days = as_int(request.data.get("days"), default=1, field="days", minimum=1, maximum=30)

        if kind == "task":
            card = TaskCard.objects.filter(pk=pk, assignees=request.user).first()
            if card is None:
                return Response({"ok": False, "code": 404, "message": "任务不存在或无权操作",
                                 "retryable": False, "detail": None}, status=404)
            if not card.due_date:
                raise ValueError("该任务没有截止日期，无法延期")
            card.due_date = card.due_date + timedelta(days=days)
            card.save(update_fields=["due_date", "updated_at"])
            return Response({"ok": True, "kind": kind, "id": card.id,
                             "due_date": card.due_date.isoformat(), "days": days})
        if kind == "todo":
            from officesuite.models import TodoItem

            todo = TodoItem.objects.filter(pk=pk, owner=request.user).first()
            if todo is None:
                return Response({"ok": False, "code": 404, "message": "待办不存在或无权操作",
                                 "retryable": False, "detail": None}, status=404)
            if not todo.due_date:
                raise ValueError("该待办没有截止日期，无法延期")
            todo.due_date = todo.due_date + timedelta(days=days)
            todo.save(update_fields=["due_date"])
            return Response({"ok": True, "kind": kind, "id": todo.id,
                             "due_date": todo.due_date.isoformat(), "days": days})
        raise ValueError("kind 只能是 task 或 todo")


# ---------------------------------------------------------------------------
# #344 提到我卡片：只读代理 IM 提及（不改 im，规范接口仍是 /api/im/mentions/）
# ---------------------------------------------------------------------------

class MentionsCardView(APIView):
    """GET /api/dashboard/mentions/?limit=5 —— 最近 @我 的消息

    数据来自 IM（ChatMessage + 会话成员），与 im.MentionsView 同口径，
    这里只做仪表盘卡片所需的裁剪；IM 端的 /api/im/mentions/ 仍为规范接口。
    """

    @endpoint(("GET",))
    def get(self, request):
        limit = as_int(request.query_params.get("limit"), default=5, field="limit",
                       minimum=1, maximum=20)
        name = getattr(request.user, "display_name", "") or request.user.username
        items = []
        if name:
            deleted_for_me = (
                ChatMessage.deleted_for.through.objects.filter(user_id=request.user.id)
                .values("chatmessage_id")
            )
            qs = (
                ChatMessage.objects
                .filter(session__members=request.user, content__icontains=f"@{name}")
                .exclude(sender=request.user)
                .exclude(is_deleted=True)
                .exclude(id__in=Subquery(deleted_for_me))
                .select_related("session", "sender")
                .order_by("-id")[:limit]
            )
            for m in qs:
                items.append({
                    "id": m.id,
                    "message_id": m.id,
                    "session_id": m.session_id,
                    "session_name": m.session.name or "单聊",
                    "sender": getattr(m.sender, "display_name", "") or (m.sender.get_username() if m.sender else "系统"),
                    "sender_id": m.sender_id,
                    "content": (m.content or "")[:200],
                    "created_at": m.created_at,
                    "link": f"/im/{m.session_id}",
                })
        return Response({
            "ok": True, "list": items, "total": len(items),
            "hint": "@提及取自 IM 会话，点击跳转对应会话", "fetched_at": timezone.now(),
        })


# ---------------------------------------------------------------------------
# #345 里程碑卡片：我参与项目 7 天内到期（只读 projects 模型）
# ---------------------------------------------------------------------------

class MilestonesCardView(APIView):
    """GET /api/dashboard/milestones/?days=7&include_overdue=1

    聚合我参与（owner 或成员）且未归档项目中 days 天内到期的未完成里程碑，
    按剩余天数升序（逾期在前）。projects 模型只读，不改动 projects 应用。
    """

    @endpoint(("GET",))
    def get(self, request):
        from projects.models import Milestone

        days = as_int(request.query_params.get("days"), default=7, field="days",
                      minimum=1, maximum=90)
        include_overdue = parse_bool(
            request.query_params.get("include_overdue"), default=True, field="include_overdue"
        )
        today = timezone.localdate()
        projects = (Project.objects
                    .filter(Q(owner=request.user) | Q(members=request.user), is_archived=False)
                    .distinct())
        qs = (Milestone.objects
              .filter(project__in=projects, due_date__isnull=False)
              .exclude(status="done")
              .filter(due_date__lte=today + timedelta(days=days))
              .select_related("project"))
        if not include_overdue:
            qs = qs.filter(due_date__gte=today)
        items = []
        for m in qs.order_by("due_date", "id")[:50]:
            left = (m.due_date - today).days
            items.append({
                "id": m.id, "name": m.name, "status": m.status,
                "project_id": m.project_id, "project_name": m.project.name,
                "due_date": m.due_date.isoformat(), "days_left": left,
                "overdue": left < 0, "link": f"/projects/{m.project_id}",
            })
        return Response({
            "ok": True, "list": items, "total": len(items),
            "days": days, "include_overdue": include_overdue,
            "overdue_total": sum(1 for i in items if i["overdue"]),
            "fetched_at": timezone.now(),
        })


# ---------------------------------------------------------------------------
# #346 项目健康卡片：未完成 / 逾期 / 本周完成 + 红黄绿标记
# ---------------------------------------------------------------------------

class ProjectHealthView(APIView):
    """GET /api/dashboard/project-health/?limit=20

    逐个汇总我参与（owner 或成员）且未归档项目的卡片情况：
    unfinished（未完成）/ overdue（已逾期）/ done_this_week（本周完成），
    level: red（有逾期）/ yellow（无逾期但有 3 天内到期）/ green（其余）。
    projects 模型只读，不改动 projects 应用。
    """

    @endpoint(("GET",))
    def get(self, request):
        limit = as_int(request.query_params.get("limit"), default=20, field="limit",
                       minimum=1, maximum=100)
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        week_start_dt = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
        projects = list(
            Project.objects
            .filter(Q(owner=request.user) | Q(members=request.user), is_archived=False)
            .distinct()
            .order_by("-updated_at")[:limit]
        )
        rows = {
            r["board__project"]: r
            for r in TaskCard.objects.filter(board__project__in=projects, is_archived=False)
            .values("board__project")
            .annotate(
                total=Count("id"),
                done=Count("id", filter=Q(status="done")),
                overdue=Count("id", filter=Q(
                    status__in=["todo", "doing"], due_date__lt=today)),
                done_week=Count("id", filter=Q(
                    status="done", completed_at__gte=week_start_dt)),
                due_soon=Count("id", filter=Q(
                    status__in=["todo", "doing"], due_date__gte=today,
                    due_date__lte=today + timedelta(days=3))),
            )
        }
        items = []
        for p in projects:
            r = rows.get(p.id) or {}
            total = int(r.get("total") or 0)
            done = int(r.get("done") or 0)
            unfinished = max(total - done, 0)
            overdue = int(r.get("overdue") or 0)
            due_soon = int(r.get("due_soon") or 0)
            if overdue:
                level, label = "red", "有逾期"
            elif due_soon:
                level, label = "yellow", "临期"
            else:
                level, label = "green", "健康"
            items.append({
                "project_id": p.id, "name": p.name,
                "unfinished": unfinished, "overdue": overdue,
                "done_this_week": int(r.get("done_week") or 0),
                "due_soon": due_soon, "total": total, "done": done,
                "level": level, "label": label,
                "percent": round(done / total * 100, 1) if total else 0.0,
                "link": f"/projects/{p.id}",
            })
        # 红色优先，其次按逾期/临期数量
        items.sort(key=lambda x: (x["level"] != "red", x["level"] != "yellow",
                                  -x["overdue"], -x["unfinished"]))
        summary = {
            "red": sum(1 for i in items if i["level"] == "red"),
            "yellow": sum(1 for i in items if i["level"] == "yellow"),
            "green": sum(1 for i in items if i["level"] == "green"),
        }
        return Response({
            "ok": True, "list": items, "total": len(items), "summary": summary,
            "week_start": week_start.isoformat(), "fetched_at": timezone.now(),
        })

