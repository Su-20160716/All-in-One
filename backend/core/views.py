"""core 视图：通知中心 / 通知偏好 / 系统公告 / 操作日志 / 全局搜索 / 全文搜索 / 健康检查 / 站点设置"""
import logging

logger = logging.getLogger(__name__)

import csv
import json
import re
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Count, F, Max, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import (
    Announcement,
    AnnouncementRead,
    Notification,
    NotificationSetting,
    OperationLog,
    ScheduledJob,
    SiteSetting,
    WebhookDelivery,
    WebhookSubscription,
)
from core.net_guard import NO_REDIRECT_OPENER, is_safe_outbound_url
from core.pagination import StandardPagination
from core.scoping import scope_queryset, visible_user_ids
from core.utils import format_size, get_client_ip
from core.validators import as_date, as_int, parse_bool, sanitize_filename


def _parse_dt(value, field):
    """可空 ISO 时间入参：非法值 400，空值 None（历史上直接透传字符串 → 保存时 500）"""
    if value in (None, ""):
        return None
    from django.utils.dateparse import parse_datetime

    dt = parse_datetime(str(value).strip())
    if dt is None:
        raise ValidationError(f"{field} 必须是 ISO 时间（如 2026-01-01T09:00:00）")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


# ---------------- 序列化器 ----------------

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "category", "level", "title", "content", "link", "is_read",
                  "snooze_until", "created_at"]


class OperationLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default="")

    class Meta:
        model = OperationLog
        fields = ["id", "username", "module", "action", "target", "detail", "diff", "ip", "created_at"]


class NotificationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationSetting
        fields = ["category", "enabled", "channels", "webhook_url", "quiet_start", "quiet_end"]


class AnnouncementSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name", read_only=True, default="系统")
    is_read = serializers.SerializerMethodField()
    read_count = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = [
            "id", "title", "content", "level", "is_pinned", "is_published",
            "scheduled_at", "expires_at", "status",
            "author_name", "is_read", "read_count", "created_at", "updated_at",
        ]

    def get_is_read(self, obj):
        # #125：视图已 annotate(is_read=Exists(...)) 时直接用，避免逐行一次 EXISTS 查询
        cached = getattr(obj, "is_read", None)
        if cached is not None:
            return bool(cached)
        request = self.context.get("request")
        if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        return AnnouncementRead.objects.filter(announcement=obj, user=request.user).exists()

    def get_read_count(self, obj):
        # #125：annotate(read_count=Count("read_records")) 已算好则不再逐行 COUNT
        cached = getattr(obj, "read_count", None)
        if cached is not None:
            return int(cached)
        return obj.read_records.count()

    def get_status(self, obj):
        """计算公告状态：draft/scheduled/published/expired"""
        from django.utils import timezone
        now = timezone.now()
        if not obj.is_published:
            return "draft"
        if obj.scheduled_at and obj.scheduled_at > now:
            return "scheduled"
        if obj.expires_at and obj.expires_at < now:
            return "expired"
        return "published"


def _annotate_announcements(request, qs):
    """#125：公告查询统一带上已读数与「我是否已读」。

    一次 annotate 替代「每行 is_read / read_count 各发一次查询」的 N+1；
    未登录时不 annotate is_read（序列化器回退为 False，也不会查库）。
    """
    from django.db.models import Exists, OuterRef

    qs = qs.select_related("author").annotate(
        read_count=Count("read_records", distinct=True),
    )
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        qs = qs.annotate(
            is_read=Exists(AnnouncementRead.objects.filter(announcement=OuterRef("pk"), user=user)),
        )
    return qs


# ---------------- 通知 ----------------

def _category_labels():
    return dict(Notification.CATEGORY_CHOICES)


def _validate_category(value, field="category"):
    """分类入参校验：拼错的分类会让筛选静默返回空列表，这里直接 400"""
    text = str(value or "").strip()
    if not text:
        return ""
    if text not in _category_labels():
        raise ValidationError(f"{field} 取值不合法，可选：{'/'.join(_category_labels())}")
    return text


def _visible_qs(qs, now=None):
    """隐藏未到期的稍后提醒（#337）：到期后自动重新可见并置顶"""
    now = now or timezone.now()
    return qs.filter(Q(snooze_until__isnull=True) | Q(snooze_until__lte=now))


def _unread_remaining(user):
    """剩余未读数（口径与列表一致：不含未到期的稍后提醒）"""
    return _visible_qs(Notification.objects.filter(recipient=user, is_read=False)).count()


class NotificationListView(APIView):
    """我的通知（分页、可按已读/分类/级别筛选；#335 返回过滤后的总数）

    - category / level：分类与级别筛选
    - unread=1：仅未读
    - include_snoozed=1：连未到期的稍后提醒一起返回（#337 默认隐藏）
    """

    def get(self, request):
        now = timezone.now()
        qs = Notification.objects.filter(recipient=request.user)
        category = _validate_category(request.query_params.get("category"))
        if category:
            qs = qs.filter(category=category)
        level = str(request.query_params.get("level") or "").strip()
        if level:
            if level not in dict(Notification.LEVEL_CHOICES):
                raise ValidationError("level 取值不合法")
            qs = qs.filter(level=level)
        only_unread = parse_bool(request.query_params.get("unread"), default=False, field="unread")
        if only_unread:
            qs = qs.filter(is_read=False)

        include_snoozed = parse_bool(
            request.query_params.get("include_snoozed"), default=False, field="include_snoozed"
        )
        snoozed_hidden = 0
        if not include_snoozed:
            snoozed_hidden = qs.filter(snooze_until__gt=now).count()
            qs = _visible_qs(qs, now)

        unread_total = qs.filter(is_read=False).count()
        total = qs.count()
        # 到期的稍后提醒排在前面（snooze_until 非空的已到期项 > 其余按时间）
        qs = qs.order_by(F("snooze_until").desc(nulls_last=True), "-created_at")
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        data = NotificationSerializer(page, many=True).data
        return Response({
            "list": data,
            "total": total,
            "unread_total": unread_total,
            "snoozed_hidden": snoozed_hidden,
            "page": pg.page.number if pg.page else 1,
            "filters": {"category": category or None, "level": level or None,
                        "unread": only_unread, "include_snoozed": include_snoozed},
        })


class NotificationMarkReadView(APIView):
    """标记已读：传 ids 标记指定；传 category 整类已读（#336）；都不传则全部已读

    返回剩余未读数，前端直接刷新角标，无需再发一次 unread-count。
    """

    def post(self, request):
        ids = request.data.get("ids") or []
        category = _validate_category(request.data.get("category"))
        qs = Notification.objects.filter(recipient=request.user, is_read=False)
        if ids:
            if not isinstance(ids, list):
                raise ValidationError("ids 需为数组")
            marked = qs.filter(id__in=ids).update(is_read=True)
        elif category:
            marked = qs.filter(category=category).update(is_read=True)
        else:
            marked = qs.update(is_read=True)
        return Response({
            "message": f"已标记 {marked} 条为已读",
            "marked": marked,
            "category": category or None,
            "unread": _unread_remaining(request.user),
        })


class NotificationUnreadCountView(APIView):
    """未读通知数（右上角红点），grouped=1 时按分类返回（#334 带中文标签）"""

    def get(self, request):
        now = timezone.now()
        base = _visible_qs(
            Notification.objects.filter(recipient=request.user, is_read=False), now
        )
        count = base.count()
        labels = _category_labels()
        data = {"count": count}
        if parse_bool(request.query_params.get("grouped"), default=False, field="grouped"):
            counts = {row["category"]: row["c"] for row in base.values("category").annotate(c=Count("id"))}
            # 固定顺序 + 中文标签，未知分类追加在后面
            order = list(labels) + [c for c in counts if c not in labels]
            data["grouped"] = counts
            data["groups"] = [
                {"category": c, "label": labels.get(c, c), "count": int(counts.get(c, 0))}
                for c in order
            ]
            data["labels"] = labels
        return Response(data)


class NotificationSnoozeView(APIView):
    """#337 稍后提醒：ids + minutes（默认 60 分钟，0 表示取消提醒）

    到点后通知重新出现在列表顶部（见 NotificationListView 的排序）。
    """

    def post(self, request):
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not ids:
            raise ValidationError("ids 需为非空数组")
        minutes = as_int(request.data.get("minutes"), default=60, field="minutes",
                         minimum=0, maximum=7 * 24 * 60)
        qs = Notification.objects.filter(recipient=request.user, id__in=ids[:200])
        if not qs.exists():
            return Response({"message": "通知不存在"}, status=404)
        until = None if minutes == 0 else timezone.now() + timedelta(minutes=minutes)
        updated = qs.update(snooze_until=until)
        return Response({
            "message": "已取消稍后提醒" if until is None else f"已推迟 {minutes} 分钟提醒",
            "snoozed": updated,
            "minutes": minutes,
            "snooze_until": until,
            "unread": _unread_remaining(request.user),
        })


class NotificationDeleteView(APIView):
    """删除通知：传 ids 删除指定；clear=read 清空已读；all 清空全部"""

    def post(self, request):
        ids = request.data.get("ids") or []
        scope = request.data.get("scope")
        qs = Notification.objects.filter(recipient=request.user)
        if scope == "all":
            n = qs.delete()[0]
        elif scope == "read":
            n = qs.filter(is_read=True).delete()[0]
        elif ids:
            n = qs.filter(id__in=ids).delete()[0]
        else:
            n = 0
        return Response({"message": f"已删除 {n} 条通知", "deleted": n})


class NotificationSettingView(APIView):
    """读取 / 更新我的通知偏好（分类开关 + 渠道 + 静默时段）"""

    CATEGORIES = ["system", "file", "note", "project", "message", "share"]
    CHANNELS = ("inapp", "email", "webhook")

    def get(self, request):
        rows = list(NotificationSetting.objects.filter(user=request.user))
        by_cat = {s.category: s for s in rows}
        cfg = by_cat.get("system")
        # #338 按 dispatch 的静默规则实时算出「当前静默中 / 下次可打扰时间」
        from core.notify import quiet_state

        return Response({
            "settings": {c: (by_cat[c].enabled if c in by_cat else True) for c in self.CATEGORIES},
            "channels": (cfg.channels if cfg and cfg.channels else ["inapp"]),
            "webhook_url": cfg.webhook_url if cfg else "",
            "quiet_start": cfg.quiet_start.strftime("%H:%M") if cfg and cfg.quiet_start else "",
            "quiet_end": cfg.quiet_end.strftime("%H:%M") if cfg and cfg.quiet_end else "",
            **quiet_state(request.user),
            # #347 每日简报推送时间（前端设置页与仪表盘卡片共用）
            "daily_push_enabled": bool(cfg.daily_push_enabled) if cfg else False,
            "daily_push_time": cfg.daily_push_time.strftime("%H:%M") if cfg and cfg.daily_push_time else "",
        })

    @staticmethod
    def _parse_time(value, field):
        from datetime import datetime as _dt

        if value in (None, ""):
            return None
        try:
            return _dt.strptime(str(value).strip(), "%H:%M").time()
        except ValueError:
            raise ValidationError(f"{field} 需为 HH:MM 格式")

    def post(self, request):
        settings_map = request.data.get("settings") or {}
        if not isinstance(settings_map, dict):
            raise ValidationError("settings 必须是对象")
        for category, enabled in settings_map.items():
            if category not in self.CATEGORIES:
                continue
            obj, _ = NotificationSetting.objects.get_or_create(user=request.user, category=category)
            obj.enabled = parse_bool(enabled, field="enabled", default=True)
            obj.save(update_fields=["enabled"])

        channels = request.data.get("channels")
        webhook_url = request.data.get("webhook_url")
        quiet_start = request.data.get("quiet_start")
        quiet_end = request.data.get("quiet_end")
        daily_enabled = request.data.get("daily_push_enabled")
        daily_time = request.data.get("daily_push_time")
        if any(v is not None for v in (channels, webhook_url, quiet_start, quiet_end,
                                       daily_enabled, daily_time)):
            cfg, _ = NotificationSetting.objects.get_or_create(user=request.user, category="system")
            if channels is not None:
                if not isinstance(channels, list) or any(c not in self.CHANNELS for c in channels):
                    raise ValidationError(f"channels 只能包含 {'/'.join(self.CHANNELS)}")
                cfg.channels = channels
            if webhook_url is not None:
                url = str(webhook_url).strip()[:500]
                if url and not is_safe_outbound_url(url):
                    raise ValidationError("webhook_url 必须是公网可访问的 http(s) 地址")
                cfg.webhook_url = url
            if quiet_start is not None:
                cfg.quiet_start = self._parse_time(quiet_start, "quiet_start")
            if quiet_end is not None:
                cfg.quiet_end = self._parse_time(quiet_end, "quiet_end")
            if daily_enabled is not None:
                cfg.daily_push_enabled = parse_bool(
                    daily_enabled, field="daily_push_enabled", default=False
                )
            if daily_time is not None:
                cfg.daily_push_time = self._parse_time(daily_time, "daily_push_time")
            cfg.save()
        from core.notify import quiet_state

        cfg = NotificationSetting.objects.filter(user=request.user, category="system").first()
        return Response({
            "message": "通知偏好已保存",
            **quiet_state(request.user),
            "daily_push_enabled": bool(cfg.daily_push_enabled) if cfg else False,
            "daily_push_time": cfg.daily_push_time.strftime("%H:%M") if cfg and cfg.daily_push_time else "",
        })


class NotificationTestWebhookView(APIView):
    """#339 Webhook 自检：向入参或已保存的地址发样例载荷

    返回状态码、耗时与响应前 200 字，失败也返回结构化结果（ok=False + error），
    便于设置页直接展示原因；地址复用核心 SSRF 校验。
    """

    def post(self, request):
        from core.notify import SAMPLE_WEBHOOK_PAYLOAD, send_test_webhook

        url = str(request.data.get("webhook_url") or "").strip()[:500]
        if not url:
            cfg = NotificationSetting.objects.filter(user=request.user, category="system").first()
            url = (cfg.webhook_url if cfg else "") or ""
        if not url:
            return Response({"ok": False, "message": "未配置 Webhook 地址", "detail": None}, status=400)
        result = send_test_webhook(url, SAMPLE_WEBHOOK_PAYLOAD, timeout=5)
        if result.get("blocked_reason") == "unsafe_url":
            return Response(
                {"ok": False, "message": result["error"], "detail": result}, status=400
            )
        return Response({
            **result,
            "message": "自检成功" if result["ok"] else (result["error"] or "自检失败"),
            "sample": SAMPLE_WEBHOOK_PAYLOAD,
            "checked_at": timezone.now(),
        })



# ---------------- 系统公告 ----------------

class AnnouncementListView(APIView):
    """公告列表（全员，仅已发布且未到期/未定时）+ 未读数"""

    def get(self, request):
        from django.utils import timezone
        now = timezone.now()
        qs = Announcement.objects.filter(
            is_published=True,
        ).filter(
            Q(scheduled_at__isnull=True) | Q(scheduled_at__lte=now)
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        level = request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)
        ann_qs = _annotate_announcements(request, qs)
        data = AnnouncementSerializer(ann_qs[:50], many=True, context={"request": request}).data
        unread = qs.exclude(readers=request.user).count()
        return Response({"list": data, "total": qs.count(), "unread": unread})


class AnnouncementDetailView(APIView):
    def get(self, request, pk):
        ann = Announcement.objects.filter(pk=pk, is_published=True).first()
        if not ann:
            return Response({"message": "公告不存在"}, status=404)
        return Response(AnnouncementSerializer(ann, context={"request": request}).data)


class AnnouncementReadView(APIView):
    """标记公告已读"""

    def post(self, request, pk):
        ann = Announcement.objects.filter(pk=pk).first()
        if not ann:
            return Response({"message": "公告不存在"}, status=404)
        AnnouncementRead.objects.get_or_create(announcement=ann, user=request.user)
        return Response({"message": "已读"})


class AdminAnnouncementView(APIView):
    """管理员：发布 / 列表 / 更新 / 删除公告

    #125：列表带可选分页（不传 page 时与旧行为一致，返回 list/total，最多 500 条），
    已读状态与已读数由一次 annotate 批量算出，不再逐行 SerializerMethodField 查询。
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        from core.pagination import OptionalPageNumberPagination

        qs = Announcement.objects.all().order_by("-is_pinned", "-created_at")
        keyword = (request.query_params.get("q") or "").strip()
        if keyword:
            qs = qs.filter(Q(title__icontains=keyword) | Q(content__icontains=keyword))
        level = request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)
        qs = _annotate_announcements(request, qs)
        pg = OptionalPageNumberPagination()
        page = pg.paginate_queryset(qs, request)
        ctx = {"request": request}
        if page is None:
            data = AnnouncementSerializer(pg.cap(qs), many=True, context=ctx).data
            return Response({"list": data, "total": qs.count(), "page": 1})
        return Response({
            "list": AnnouncementSerializer(page, many=True, context=ctx).data,
            "total": pg.page.paginator.count,
            "page": pg.page.number,
            "page_size": pg.page_size,
            "pages": pg.page.paginator.num_pages,
        })

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "公告标题不能为空"}, status=400)
        ann = Announcement.objects.create(
            title=title,
            content=request.data.get("content", ""),
            level=request.data.get("level", "info"),
            is_pinned=parse_bool(request.data.get("is_pinned"), field="is_pinned"),
            is_published=parse_bool(request.data.get("is_published"), default=True, field="is_published"),
            scheduled_at=_parse_dt(request.data.get("scheduled_at"), "scheduled_at"),
            expires_at=_parse_dt(request.data.get("expires_at"), "expires_at"),
            author=request.user,
        )
        return Response(AnnouncementSerializer(ann).data, status=201)


class AdminAnnouncementDetailView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        ann = Announcement.objects.filter(pk=pk).first()
        if not ann:
            return Response({"message": "公告不存在"}, status=404)
        for f in ("title", "content", "level", "is_pinned", "is_published", "scheduled_at", "expires_at"):
            if f in request.data:
                setattr(ann, f, request.data[f] or None)
        ann.save()
        return Response(AnnouncementSerializer(ann).data)

    def delete(self, request, pk):
        ann = Announcement.objects.filter(pk=pk).first()
        if not ann:
            return Response({"message": "公告不存在"}, status=404)
        ann.delete()
        return Response({"message": "公告已删除"})


# ---------------- 操作日志 ----------------

def _filter_logs(request, qs):
    username = request.query_params.get("username")
    module = request.query_params.get("module")
    action = request.query_params.get("action")
    ip = request.query_params.get("ip")
    start = request.query_params.get("start")
    end = request.query_params.get("end")
    result = request.query_params.get("result")  # #69: success/fail
    target = request.query_params.get("target")   # #69: 对象类型/关键词
    if username:
        qs = qs.filter(user__username__icontains=username)
    if module:
        qs = qs.filter(module=module)
    if action:
        qs = qs.filter(action=action)
    if ip:
        qs = qs.filter(ip__icontains=ip)
    if start:
        qs = qs.filter(created_at__date__gte=as_date(start, field="start"))
    if end:
        qs = qs.filter(created_at__date__lte=as_date(end, field="end"))
    if target:
        qs = qs.filter(target__icontains=target)
    if result == "fail":
        qs = qs.exclude(user__isnull=True)
    return qs


class OperationLogListView(APIView):
    """操作日志查询（仅管理员）：支持按用户/模块/动作/IP/时间范围筛选"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = _filter_logs(request, OperationLog.objects.select_related("user"))
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        data = OperationLogSerializer(page, many=True).data
        return Response({"list": data, "total": qs.count(), "page": pg.page.number if pg.page else 1})


class MyOperationLogView(APIView):
    """普通用户查看自己的操作日志"""

    def get(self, request):
        qs = OperationLog.objects.filter(user=request.user)
        qs = _filter_logs(request, qs)
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        return Response({"list": OperationLogSerializer(page, many=True).data, "total": qs.count()})


class OperationLogStatsView(APIView):
    """操作日志聚合统计（管理员）：按模块 / 动作 / 日期

    #103：按天统计改用 TruncDate + 限定时间窗（默认近 30 天，days 可调 1–365），
    不再用 ``extra(date(created_at))`` 做全表表达式分组。
    """

    permission_classes = [IsAdminUser]

    def get(self, request):
        from datetime import timedelta

        from django.db.models.functions import TruncDate

        days = as_int(request.query_params.get("days"), default=30, field="days", minimum=1, maximum=365)
        since = timezone.now() - timedelta(days=days)
        qs = _filter_logs(request, OperationLog.objects.all())
        window = qs.filter(created_at__gte=since)
        by_module = list(qs.values("module").annotate(c=Count("id")).order_by("-c"))
        by_action = list(qs.values("action").annotate(c=Count("id")).order_by("-c"))
        by_day = list(
            window.annotate(d=TruncDate("created_at")).values("d")
            .annotate(c=Count("id")).order_by("d")
        )
        return Response({
            "by_module": by_module,
            "by_action": by_action,
            "by_day": by_day,
            "total": qs.count(),
            "window_days": days,
        })


class OperationLogExportView(APIView):
    """导出操作日志为 CSV（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = _filter_logs(request, OperationLog.objects.select_related("user"))[:10000]
        resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        resp["Content-Disposition"] = "attachment; filename=operation_logs.csv"
        writer = csv.writer(resp)
        writer.writerow(["时间", "用户", "模块", "动作", "对象", "IP", "详情"])
        for log in qs:
            writer.writerow([
                log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                log.user.username if log.user else "",
                log.module, log.action, log.target, log.ip or "", log.detail,
            ])
        return resp


# ---------------- #73 公告已读统计导出 ----------------

class AnnouncementReadExportView(APIView):
    """导出公告已读名单为 CSV（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        ann = Announcement.objects.filter(pk=pk).first()
        if not ann:
            return Response({"message": "公告不存在"}, status=404)
        resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        resp["Content-Disposition"] = f"attachment; filename=announcement_{pk}_readers.csv"
        writer = csv.writer(resp)
        writer.writerow(["用户名", "昵称", "邮箱", "已读时间"])
        for r in ann.read_records.select_related("user").order_by("created_at"):
            writer.writerow([
                r.user.username if r.user else "",
                r.user.nickname if r.user else "",
                r.user.email if r.user else "",
                r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ])
        return resp


# ---------------- #72 存储使用 TOP 用户 ----------------

class StorageTopUsersView(APIView):
    """存储使用量 TOP 10 用户排行（管理员）"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        from files.models import FileMeta
        from django.db.models import Sum
        rows = (
            FileMeta.objects.filter(is_deleted=False)
            .values("owner_id", "owner__username", "owner__nickname")
            .annotate(total_bytes=Sum("size"), file_count=Count("id"))
            .order_by("-total_bytes")[:10]
        )
        result = []
        for r in rows:
            result.append({
                "user_id": r["owner_id"],
                "username": r["owner__username"],
                "nickname": r["owner__nickname"] or "",
                "total_bytes": r["total_bytes"] or 0,
                "total_text": format_size(r["total_bytes"] or 0),
                "file_count": r["file_count"] or 0,
            })
        return Response({"list": result, "total": len(result)})


# ---------------- #68 数据备份 ----------------

# #13：每人每小时只允许触发 1 次（dumpdata 全量同步执行，重复点击会拖垮库与磁盘）
BACKUP_RATE_LIMIT_SECONDS = 3600
# #98：备份转后台执行——全局并发锁有效期与任务最长等待时间（秒）
BACKUP_JOB_TIMEOUT = 1800
BACKUP_LOCK_KEY = "core:backup:running"
BACKUP_EXCLUDES = ["contenttypes", "auth.Permission", "sessions", "admin.LogEntry"]


def _backup_dir():
    """备份落盘目录：**非静态目录**，绝不落在 media/static 这类会被公开直出的路径里。

    生产配了 DATA_DIR（持久卷）时写 ``<DATA_DIR>/backups``，随卷持久化；
    本地开发回落到 ``BASE_DIR/backups``（与 media/static 同级但彼此独立）。
    """
    import os
    from pathlib import Path

    data_dir = (os.environ.get("DATA_DIR") or os.environ.get("DJANGO_DATA_DIR") or "").strip()
    path = (Path(data_dir) if data_dir else Path(settings.BASE_DIR)) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    for public in (getattr(settings, "MEDIA_ROOT", None), getattr(settings, "STATIC_ROOT", None)):
        if not public:
            continue
        try:
            path.resolve().relative_to(Path(public).resolve())
        except ValueError:
            continue
        # 配错了（把备份目录指进公开目录）宁可报错，也不要把口令哈希暴露成可下载文件
        raise ValueError("备份目录不能位于 media/static 等公开目录内")
    return path


def _compress_backup(raw_path, out_path):
    """把 dumpdata 的明文 JSON 压成 gzip，并把权限收到仅服务账号可读。

    只依赖标准库（gzip 压缩 + 0600 权限 + 非公开目录），不引入加密库依赖；
    恢复时先 gunzip 再用 ``manage.py restore_data <file>``。
    返回 (字节数, 原文 sha256)。
    """
    import gzip
    import hashlib
    import os

    digest = hashlib.sha256()
    with open(raw_path, "rb") as src, gzip.open(out_path, "wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            dst.write(chunk)
    try:
        os.chmod(out_path, 0o600)  # 含口令哈希与 2FA 密钥，只允许服务账号读取
    except OSError:
        pass
    return os.path.getsize(out_path), digest.hexdigest()


def _perform_backup(user, ip=""):
    """同步执行一次备份：dumpdata → gzip → 审计。返回结果字典，失败抛异常。

    #131：落盘目录统一由 ``_backup_dir()`` 决定（DATA_DIR/backups → BASE_DIR/backups），
    不再直接写 ``settings.BASE_DIR``（容器里那是 /app，重建即丢）。
    """
    import os

    from django.core.management import call_command

    target_dir = _backup_dir()
    ts = timezone.localtime().strftime("%Y%m%d_%H%M%S")
    raw_path = target_dir / f".backup_{ts}.json.part"
    out_path = target_dir / f"backup_{ts}.json.gz"
    try:
        call_command(
            "dumpdata", "--indent", "2", "--output", str(raw_path),
            "--natural-foreign", "--natural-primary",
            *[f"--exclude={e}" for e in BACKUP_EXCLUDES],
        )
        size, digest = _compress_backup(raw_path, out_path)
    finally:
        try:
            os.remove(raw_path)  # 明文中间文件必须删掉
        except OSError:
            pass
    if user is not None:
        OperationLog.objects.create(
            user=user, module="core", action="export", target="数据备份",
            detail=f"{out_path.name} · {round(size / 1024, 1)} KB · sha256={digest[:16]}",
            ip=ip or "",
        )
    return {
        "file": out_path.name,
        "size": size,
        "size_kb": round(size / 1024, 1),
        "sha256": digest,
    }


def _run_backup_job(run_id, user_id, ip=""):
    """#98：后台线程执行备份，结果写回 AdminCommandRun（任务 ID = 该行 pk）。"""
    import time as _time

    from django.db import connections

    from core.models import AdminCommandRun

    t0 = _time.time()
    ok, output, error = True, "", ""
    try:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
        result = _perform_backup(user, ip)
        output = json.dumps(result, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 —— 后台任务失败只落记录，不影响请求
        ok = False
        error = f"{type(exc).__name__}: {exc}"[:2000]
        logger.exception("后台备份失败")
        try:
            from core.platform import record_exception

            record_exception(exc, "/api/core/admin/backup/", user_id=user_id)
        except Exception:
            pass
    finally:
        try:
            AdminCommandRun.objects.filter(pk=run_id).update(
                ok=ok, output=output[:4000], error=error,
                duration_ms=int((_time.time() - t0) * 1000), finished_at=timezone.now(),
            )
        except Exception:
            logger.exception("备份任务状态写回失败")
        try:
            from django.core.cache import cache

            cache.delete(BACKUP_LOCK_KEY)
        except Exception:
            pass
        try:
            connections.close_all()  # 线程结束前关闭本线程持有的连接
        except Exception:
            pass


class BackupView(APIView):
    """管理员：数据备份。

    #98：默认转后台执行并立即返回任务 ID（``?sync=1`` 保留同步执行，供小库/冒烟使用），
    #131：统一写入 DATA_DIR/backups；#13：非公开目录 + gzip 压缩 + 审计 + 每人每小时 1 次。
    """

    permission_classes = [IsAdminUser]

    @staticmethod
    def _result_payload(result):
        return {
            "message": "备份完成：已压缩并写入服务器非公开目录",
            "file": result["file"],
            "size_kb": result["size_kb"],
            "sha256": result["sha256"],
            "compressed": True,
            "note": "文件仅管理员在服务器上可见；恢复时先 gunzip，再执行 manage.py restore_data <file>",
        }

    def post(self, request):
        import threading

        from django.core.cache import cache

        from core.models import AdminCommandRun

        rate_key = f"core:backup:rate:{request.user.id}"
        if not cache.add(rate_key, 1, BACKUP_RATE_LIMIT_SECONDS):
            return Response(
                {"message": "备份过于频繁：每人每小时仅可触发 1 次，请稍后再试"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(BACKUP_RATE_LIMIT_SECONDS)},
            )
        try:
            _backup_dir()  # 目录/权限问题提前暴露，不占用配额
        except (OSError, ValueError) as exc:
            cache.delete(rate_key)
            return Response({"message": str(exc)}, status=400)

        ip = get_client_ip(request)

        def _sync_run():
            try:
                return self._result_payload(_perform_backup(request.user, ip)), None
            except Exception as exc:  # noqa: BLE001 —— 统一降级为 422，细节只进日志
                logger.exception("数据备份失败")
                cache.delete(rate_key)  # 失败允许立即重试
                try:
                    from core.platform import record_exception

                    record_exception(exc, request.path, **_request_context(request))
                except Exception:
                    logger.exception("数据备份异常上报失败")
                return None, Response(
                    {"message": f"备份失败（{type(exc).__name__}），详情见服务端日志"}, status=422
                )

        if request.query_params.get("sync") == "1":
            payload, failure = _sync_run()
            return failure if failure is not None else Response(payload)

        if not cache.add(BACKUP_LOCK_KEY, 1, BACKUP_JOB_TIMEOUT):
            return Response(
                {"message": "已有备份任务在后台执行，请用 ?job_id= 查询已有任务状态"},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        try:
            run = AdminCommandRun.objects.create(
                command="dump_data", args="backup", ok=False, ran_by=request.user
            )
        except Exception:
            cache.delete(BACKUP_LOCK_KEY)
            logger.exception("备份任务登记失败")
            return Response({"message": "备份任务登记失败，请稍后重试"}, status=422)
        try:
            threading.Thread(
                target=_run_backup_job, args=(run.id, request.user.id, ip),
                daemon=True, name=f"backup-{run.id}",
            ).start()
        except Exception:  # noqa: BLE001 —— 线程起不来就退回同步执行，不能让用户白点
            cache.delete(BACKUP_LOCK_KEY)
            payload, failure = _sync_run()
            if failure is not None:
                AdminCommandRun.objects.filter(pk=run.id).update(
                    ok=False, error="线程启动失败且同步重试失败", finished_at=timezone.now(),
                )
                return failure
            AdminCommandRun.objects.filter(pk=run.id).update(
                ok=True, output=json.dumps(payload, ensure_ascii=False)[:4000],
                finished_at=timezone.now(),
            )
            return Response(payload)
        return Response({
            "message": "备份任务已提交，正在后台执行；完成后凭 job_id 查询结果",
            "job_id": run.id,
            "status": "running",
            # 兼容旧响应结构：字段仍在，值等任务完成后再通过 GET 获取
            "file": "",
            "size_kb": 0,
            "sha256": "",
            "compressed": True,
            "poll": f"/api/core/admin/backup/?job_id={run.id}",
        }, status=status.HTTP_202_ACCEPTED)

    def get(self, request):
        """#98：查询后台备份任务状态（?job_id=N，仅管理员）"""
        from core.models import AdminCommandRun

        job_id = as_int(request.query_params.get("job_id"), field="job_id", minimum=1)
        run = AdminCommandRun.objects.filter(pk=job_id, command="dump_data").first()
        if run is None:
            return Response({"message": "备份任务不存在"}, status=404)
        if run.finished_at is None:
            # 进程重启/线程夭折会让记录停在 running，超出任务时限判为 stale
            stale = run.started_at and (
                timezone.now() - run.started_at
            ).total_seconds() > BACKUP_JOB_TIMEOUT
            state = "stale" if stale else "running"
        elif run.ok:
            state = "done"
        else:
            state = "failed"
        result = None
        if run.ok and run.output:
            try:
                result = json.loads(run.output)
            except (TypeError, ValueError):
                result = None
        return Response({
            "job_id": run.id,
            "status": state,
            "ok": bool(run.ok),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "duration_ms": run.duration_ms,
            "result": result,
            "error": run.error or "",
            "file": (result or {}).get("file", ""),
            "size_kb": (result or {}).get("size_kb", 0),
            "sha256": (result or {}).get("sha256", ""),
        })


# ---------------- 全局搜索 ----------------

# #95：q 长度上限——超长关键词会被直接拼进 4 个 icontains，既拖慢全表扫描也放大 SQL 长度
SEARCH_Q_MAX_LEN = 100


class GlobalSearchView(APIView):
    """跨模块全局搜索：文件 / 笔记 / 项目 / 任务，一次返回各模块命中"""

    def get(self, request):
        from files.models import FileMeta
        from notes.models import Note
        from projects.models import Project, TaskCard

        kw = (request.query_params.get("q") or "").strip()
        if len(kw) > SEARCH_Q_MAX_LEN:
            return Response(
                {"message": f"搜索词过长：最多 {SEARCH_Q_MAX_LEN} 个字符（当前 {len(kw)}）"},
                status=400,
            )
        if not kw:
            return Response({"keyword": "", "files": [], "notes": [], "projects": [], "tasks": [], "total": 0})
        # 统一走数据范围过滤：管理员看全部、部门负责人看本部门、普通用户看本人
        files = scope_queryset(
            FileMeta.objects.filter(is_deleted=False, name__icontains=kw), request.user
        )[:10]
        notes = scope_queryset(
            Note.objects.filter(Q(title__icontains=kw) | Q(content__icontains=kw)), request.user
        )[:10]
        projects = scope_queryset(
            Project.objects.filter(Q(name__icontains=kw)), request.user, co_member_field="members"
        )[:10]
        tasks = TaskCard.objects.filter(
            Q(title__icontains=kw) | Q(description__icontains=kw),
        ).filter(
            Q(board__project__owner=request.user) | Q(board__project__members=request.user)
        ).distinct()[:10]
        result = {
            "keyword": kw,
            "files": [{"id": f.id, "name": f.name, "kind": f.kind, "size_text": _size(f.size)} for f in files],
            "notes": [{"id": n.id, "title": n.title, "updated_at": n.updated_at} for n in notes],
            "projects": [{"id": p.id, "name": p.name, "color": p.color} for p in projects],
            "tasks": [{"id": t.id, "title": t.title, "status": t.status, "project_id": t.board.project_id} for t in tasks],
        }
        result["total"] = (
            len(result["files"]) + len(result["notes"]) + len(result["projects"]) + len(result["tasks"])
        )
        return Response(result)


def _size(num):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


# ---------------- 健康检查 / 站点设置 ----------------

class HealthView(APIView):
    permission_classes = [AllowAny]

    # #136：缓存探活的短 key（写入后立刻读回，Redis/locmem 故障都能暴露）
    CACHE_PROBE_KEY = "core:health:probe"
    PROBE_TTL = 30

    def get(self, request):
        import time as _time

        db_ok = True
        latency_ms = 0
        try:
            t0 = _time.time()
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            latency_ms = int((_time.time() - t0) * 1000)
        except Exception:
            db_ok = False
        # #136：缓存探活纳入 status 判定（此前缓存故障完全不可见）
        cache_ok = True
        cache_ms = 0
        try:
            from django.core.cache import cache

            probe = f"{_time.time():.6f}"
            t0 = _time.time()
            cache.set(self.CACHE_PROBE_KEY, probe, self.PROBE_TTL)
            cache_ok = cache.get(self.CACHE_PROBE_KEY) == probe
            cache_ms = int((_time.time() - t0) * 1000)
        except Exception:
            cache_ok = False
        healthy = db_ok and cache_ok
        data = {
            "status": "ok" if healthy else "degraded",
            "db": db_ok,
            "db_latency_ms": latency_ms,
            "cache": cache_ok,
            "cache_latency_ms": cache_ms,
            "version": getattr(settings, "PLATFORM_VERSION", "1.0.0"),
        }
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_staff:
            data["detail"] = self._detail()
        return Response(data)

    @staticmethod
    def _detail():
        """F02 管理员巡检面板：磁盘 / 慢接口 / WS / 后台任务，任一项失败只降级不 500"""
        import shutil

        out = {"media": {}, "slow_endpoints": [], "ws": None, "tasks": None}
        try:
            usage = shutil.disk_usage(settings.MEDIA_ROOT)
            out["media"] = {
                "path": str(settings.MEDIA_ROOT),
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "used_pct": round(usage.used / usage.total * 100, 1) if usage.total else 0,
            }
        except Exception:
            out["media"] = {"path": str(settings.MEDIA_ROOT), "error": "unavailable"}
        try:
            from core.models import SlowEndpoint

            out["slow_endpoints"] = [
                {"path": s.path, "avg_ms": s.avg_ms, "max_ms": s.max_ms, "samples": s.samples}
                for s in SlowEndpoint.objects.order_by("-max_ms")[:10]
            ]
        except Exception:
            pass
        try:
            from channels.layers import get_channel_layer

            layer = get_channel_layer()
            if layer is None:
                out["ws"] = {"connections": None, "note": "未配置 channel layer"}
            elif "Redis" in type(layer).__name__:
                out["ws"] = {"connections": None, "note": "Redis channel layer，连接数由 Redis 侧统计"}
            else:
                out["ws"] = {"connections": None, "note": "当前使用内存 channel layer，无法跨进程统计"}
        except Exception:
            out["ws"] = {"connections": None, "note": "channel layer 不可用"}
        try:
            from django.core.cache import cache

            backlog = cache.get("task_backlog")
            out["tasks"] = {"backlog": backlog} if backlog is not None else {
                "backlog": None, "note": "未接入异步任务队列（同步执行）",
            }
        except Exception:
            out["tasks"] = {"backlog": None}
        return out


class GenericExportView(APIView):
    """F03 通用导出：任意已声明模块 → CSV / JSON"""

    def get(self, request, app):
        from core.importer import export_response

        try:
            return export_response(app, request)
        except ValueError as exc:
            return Response({"message": str(exc)}, status=400)


class GenericImportView(APIView):
    """F03 通用导入：上传 CSV/JSON，返回逐行错误回执"""

    def post(self, request, app):
        from core.importer import import_response

        try:
            return Response(import_response(app, request))
        except ValidationError as exc:
            return Response({"message": exc.detail if isinstance(exc.detail, str) else str(exc.detail)}, status=400)
        except ValueError as exc:
            return Response({"message": str(exc)}, status=400)


class PublicSiteSettingView(APIView):
    """公开读取站点设置（白名单键）"""

    permission_classes = [AllowAny]
    PUBLIC_KEYS = [
        "site_name", "site_description", "register_enabled", "contact_email",
        "footer_text", "logo_url", "primary_color",
    ]

    def get(self, request):
        # S2-B1：公开设置走 300s 缓存（高频请求、低频变更），
        # 管理员保存后 AdminSiteSettingView.post 主动失效
        from core.site_cache import get_public_settings

        def _load():
            qs = SiteSetting.objects.filter(key__in=self.PUBLIC_KEYS)
            return {s.key: s.value for s in qs}

        return Response({"settings": get_public_settings(_load)})


class AdminSiteSettingView(APIView):
    """管理员读取 / 批量更新站点设置"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = SiteSetting.objects.all()
        return Response({"settings": {s.key: {"value": s.value, "label": s.label} for s in qs}})

    def post(self, request):
        items = request.data.get("settings") or {}
        for key, value in items.items():
            obj = SiteSetting.objects.filter(key=key).first()
            if obj:
                obj.value = str(value)
                obj.save(update_fields=["value", "updated_at"])
            else:
                SiteSetting.objects.create(key=key, value=str(value))
        # S2-B1：保存后立即失效公开设置缓存，下次读取回源（改完马上生效）
        from core.site_cache import invalidate_public_settings

        invalidate_public_settings()
        return Response({"message": "站点设置已保存"})


# ---------------- 全文搜索（倒排索引 + BM25） ----------------

class FullTextSearchView(APIView):
    """全文检索：GET /api/core/search/fulltext/?q=&module=note,file&limit=20&offset=0

    返回按 BM25 相关度排序的命中，含摘要高亮片段；只检索当前用户数据范围内的文档。

    F661 分组：响应带 ``by_module`` / ``group_counts``，前端按模块分 Tab 展示。
    F662 语法：支持 ``"精确短语"`` 与 ``-排除词``，``syntax`` 字段回显解析结果；
    片段已做 HTML 转义再高亮，``v-html`` 渲染也不会注入。
    """

    def get(self, request):
        from core.search import parse_syntax, search

        q = request.query_params.get("q") or request.query_params.get("keyword") or ""
        if not q.strip():
            return Response({"total": 0, "results": [], "terms": [], "took_ms": 0, "query": "",
                             "syntax": parse_syntax(""), "by_module": [], "group_counts": {}})
        modules = [m for m in (request.query_params.get("module") or "").split(",") if m]
        limit = as_int(request.query_params.get("limit"), default=20, field="limit", minimum=1, maximum=100)
        offset = as_int(request.query_params.get("offset"), default=0, field="offset", minimum=0)
        data = search(q, visible_user_ids(request.user), modules=modules or None, limit=limit, offset=offset)
        data["limit"] = limit
        data["offset"] = offset
        # 记录搜索词（#63）：失败不影响主流程；#17 顺带做到期清理（每人每天至多一次）
        try:
            from core.models import SearchQueryLog
            _purge_old_search_logs(request.user)
            SearchQueryLog.objects.create(
                owner=request.user, term=q[:200], result_count=data.get("total", 0))
        except Exception:
            logger.exception("B23：静默兜底已登记（core/views.py:564 原为 pass）——review 是否应收窄异常类型")
        return Response(data)


class SearchSuggestView(APIView):
    """检索词联想：GET /api/core/search/suggest/?q=文"""

    def get(self, request):
        from core.search import suggest

        q = request.query_params.get("q") or ""
        limit = as_int(request.query_params.get("limit"), default=10, field="limit", minimum=1, maximum=30)
        return Response({"list": suggest(q, visible_user_ids(request.user), limit=limit)})


class SearchIndexStatsView(APIView):
    """索引概况：文档数 / 词项数 / 各模块分布"""

    def get(self, request):
        from core.search import index_stats

        return Response(index_stats(visible_user_ids(request.user)))


class ReindexView(APIView):
    """重建索引。

    POST {"scope": "own"|"all", "module": "note"}  —— scope=all 仅管理员可用
    日常无需手动调用：笔记/文件保存时会自动增量索引。
    """

    def post(self, request):
        from core.reindex import reindex_all, reindex_user

        scope = request.data.get("scope") or "own"
        modules = request.data.get("modules")
        if scope == "all":
            if not request.user.is_staff and not request.user.is_superuser:
                return Response({"message": "仅管理员可重建全量索引"}, status=status.HTTP_403_FORBIDDEN)
            result = reindex_all(modules)
        else:
            result = reindex_user(request.user, modules)
        return Response({"message": "索引重建完成", **result})


# ---------------- 搜索历史 / 热词 / 导出（#63 #65 #14 #17） ----------------

# #17：搜索词默认保留 30 天（可用 settings.SEARCH_LOG_KEEP_DAYS 覆盖）
SEARCH_LOG_KEEP_DAYS = 30
# #14：热词最小出现次数阈值——只出现 1 次的孤立搜索不进榜，避免个体行为被放大
HOT_MIN_HITS = 2


def _search_log_keep_days():
    try:
        return max(1, int(getattr(settings, "SEARCH_LOG_KEEP_DAYS", SEARCH_LOG_KEEP_DAYS)))
    except (TypeError, ValueError):
        return SEARCH_LOG_KEEP_DAYS


def _purge_old_search_logs(owner):
    """#17 个人搜索词到期清理：每个用户每天最多执行一次，删掉超过保留期的记录。"""
    from django.core.cache import cache
    from core.models import SearchQueryLog

    if owner is None or not getattr(owner, "id", None):
        return 0
    if not cache.add(f"core:searchlog:purge:{owner.id}", 1, 86400):
        return 0
    cutoff = timezone.now() - timezone.timedelta(days=_search_log_keep_days())
    try:
        return SearchQueryLog.objects.filter(owner=owner, created_at__lt=cutoff).delete()[0]
    except Exception:
        logger.exception("搜索词到期清理失败")
        return 0


class SearchHistoryView(APIView):
    """我的搜索历史：GET /api/core/search/history/?limit=20

    #17：支持按条删除——``{"id": 12}`` 或 ``{"ids": [1,2]}`` 或 ``{"term": "关键词"}``；
    不带参数删除仍保持原语义（清空全部）。
    """

    def get(self, request):
        from core.models import SearchQueryLog
        limit = as_int(request.query_params.get("limit"), default=20, field="limit", minimum=1, maximum=100)
        _purge_old_search_logs(request.user)
        rows = SearchQueryLog.objects.filter(owner=request.user)[:limit]
        # 去重（保留最新一次）
        seen, items = set(), []
        for r in rows:
            if r.term in seen:
                continue
            seen.add(r.term)
            items.append({"id": r.id, "term": r.term, "result_count": r.result_count, "at": r.created_at})
        return Response({"list": items[:limit], "keep_days": _search_log_keep_days()})

    def delete(self, request):
        from core.models import SearchQueryLog
        qs = SearchQueryLog.objects.filter(owner=request.user)
        raw_ids = request.data.get("ids")
        if isinstance(raw_ids, str):
            raw_ids = [x for x in raw_ids.replace("，", ",").split(",") if x.strip()]
        ids = [as_int(x, field="ids") for x in (raw_ids or [])] if isinstance(raw_ids, (list, tuple)) else []
        item_id = request.data.get("id")
        term = request.data.get("term")
        if ids:
            n = qs.filter(id__in=ids).delete()[0]
        elif item_id not in (None, ""):
            n = qs.filter(id=as_int(item_id, field="id")).delete()[0]
        elif term not in (None, ""):
            n = qs.filter(term=str(term).strip()[:200]).delete()[0]
        else:
            n = qs.delete()[0]  # 不带参数：清空全部（历史行为）
        return Response({"message": f"已删除 {n} 条搜索历史", "deleted": n})


class SearchHotView(APIView):
    """全局热词：GET /api/core/search/hot/?limit=10  近7天高频搜索词

    #14：聚合前按 ``visible_user_ids`` 收敛，不再对全体用户做全局统计；
    并丢弃出现次数低于阈值的词，避免从热词反推他部门/他租户的业务。

    #105：本查询按 ``created_at >= since`` 过滤 + ``GROUP BY term``，但 SearchQueryLog
    目前只有 ``(owner, -created_at)`` 复合索引，本查询用不上，会退回按 term 索引扫描。
    需要的索引（**本次不建索引、不改模型**，随下次迁移/运维单独执行）：

        CREATE INDEX core_sql_created_idx ON core_searchquerylog (created_at);
        -- 或覆盖聚合的复合索引：
        CREATE INDEX core_sql_term_created_idx ON core_searchquerylog (term, created_at);

    对应的 models.Index 声明（待 models.py 改动时一并加入）：

        models.Index(fields=["created_at"], name="core_sql_created_idx"),
        models.Index(fields=["term", "created_at"], name="core_sql_term_created_idx"),
    """

    def get(self, request):
        from django.db.models import Count
        from core.models import SearchQueryLog
        limit = as_int(request.query_params.get("limit"), default=10, field="limit", minimum=1, maximum=50)
        min_hits = as_int(
            request.query_params.get("min_hits"), default=HOT_MIN_HITS, field="min_hits", minimum=1, maximum=100
        )
        since = timezone.now() - timezone.timedelta(days=7)
        qs = SearchQueryLog.objects.filter(created_at__gte=since)
        ids = visible_user_ids(request.user)
        if ids is not None:
            qs = qs.filter(owner_id__in=ids) if ids else qs.none()
        rows = (
            qs.values("term").annotate(c=Count("id")).filter(c__gte=min_hits)
            .order_by("-c", "term")[:limit]
        )
        return Response({
            "list": [{"term": r["term"], "count": r["c"]} for r in rows],
            "window_days": 7,
            "min_hits": min_hits,
        })


class SearchExportView(APIView):
    """导出搜索结果为 CSV：GET /api/core/search/export/?q=关键词"""

    def get(self, request):
        from core.search import search
        q = request.query_params.get("q") or request.query_params.get("keyword") or ""
        if not q.strip():
            return Response({"message": "缺少搜索词 q"}, status=400)
        modules = [m for m in (request.query_params.get("module") or "").split(",") if m]
        data = search(q, visible_user_ids(request.user), modules=modules or None, limit=200)
        resp = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        # 关键词进响应头：剔除引号/控制字符，非 ASCII 走 RFC 5987；
        # 直接拼接会被 " 或换行注入额外响应头
        filename = sanitize_filename(f"search_{q[:20]}.csv", fallback="search.csv", max_length=80)
        resp["Content-Disposition"] = content_disposition_header(True, filename)
        writer = csv.writer(resp)
        writer.writerow(["模块", "标题", "摘要", "相关度", "更新时间"])
        for r in data.get("results", []):
            writer.writerow([r.get("module", ""), r.get("title", ""),
                             r.get("snippet", "").replace("<em>", "").replace("</em>", ""),
                             r.get("score", ""),
                             r.get("updated_at", "")])
        return resp


# ===========================================================================
# v8 新增：管理与平台（F627–F642）
# ===========================================================================

def _request_context(request):
    """#135：抽出 user_id / request_id，供 record_exception 定位受影响用户与调用链。

    request_id 优先取 #134 的 RequestIdMiddleware 写入的 ``request.request_id``，
    其次网关/前端透传的 ``X-Request-ID``；都没有时为 None（不影响聚合）。
    """
    user = getattr(request, "user", None)
    user_id = getattr(user, "id", None) if getattr(user, "is_authenticated", False) else None
    meta = getattr(request, "META", None) or {}
    request_id = (
        getattr(request, "request_id", "")
        or meta.get("HTTP_X_REQUEST_ID")
        or ""
    )
    return {"user_id": user_id, "request_id": str(request_id)[:64] or None}


def _guard(fn):
    """新视图统一异常兜底：ValueError → 400，其余异常 → 422（结构化，绝不 500）"""

    from functools import wraps

    @wraps(fn)
    def inner(self, request, *args, **kwargs):
        try:
            return fn(self, request, *args, **kwargs)
        except ValidationError as exc:
            # core/validators 的 as_int/parse_bool 走 DRF ValidationError，
            # 与 ValueError 一样按 400 处理，避免变成 422
            detail = exc.detail[0] if isinstance(exc.detail, list) and exc.detail else exc.detail
            return Response({"ok": False, "error": str(detail), "code": 400}, status=400)
        except ValueError as exc:
            return Response({"ok": False, "error": str(exc), "code": 400}, status=400)
        except Exception as exc:  # noqa: BLE001 —— 结构化降级
            try:
                from core.platform import record_exception

                record_exception(exc, getattr(request, "path", ""), **_request_context(request))
            except Exception:
                logger.exception("B23：静默兜底已登记（core/views.py:694 原为 pass）——review 是否应收窄异常类型")
            return Response(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}", "code": 422},
                status=422,
            )

    return inner


# ---------------- F627 后端健康卡 ----------------

class AdminHealthCardView(APIView):
    """GET 后端健康卡：DB 连通 / 表数 / 最新迁移 / 存储占用 / 运行时

    #102：结果缓存 5 分钟；``?fresh=1`` 强制重新体检（管理端「刷新」）。
    """

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.platform import health_card

        fresh = (request.query_params.get("fresh") or "").strip() in ("1", "true", "yes")
        return Response(health_card(force=fresh))


# ---------------- #137 Prometheus 文本指标 ----------------

# 指标缓存秒数：Prometheus 默认 15–30s 抓一次，短缓存可挡住抓取风暴与重复 COUNT
METRICS_CACHE_SECONDS = 30
_METRICS_CACHE_KEY = "core:metrics:text:v1"


def _is_internal_ip(ip):
    """判断来源是否内网/环回（只认 REMOTE_ADDR，避免 X-Forwarded-For 伪造）"""
    import ipaddress

    try:
        addr = ipaddress.ip_address(str(ip or "").strip())
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def _metric_label(value):
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _metrics_internal_request(request):
    """#137：判定 metrics 抓取是否来自内网。

    直连（无代理）时只看 REMOTE_ADDR；经过反向代理时 REMOTE_ADDR 会是代理的
    环回地址，此时还要求 X-Forwarded-For 的首跳也是内网，避免公网请求借代理
    「看起来是本地」而拿到指标。反向代理未透传 XFF 时按内网直连处理。
    """
    meta = getattr(request, "META", {}) or {}
    remote = str(meta.get("REMOTE_ADDR", "")).strip()
    if not _is_internal_ip(remote):
        return False
    forwarded = str(meta.get("HTTP_X_FORWARDED_FOR", "") or "").split(",")[0].strip()
    if forwarded and not _is_internal_ip(forwarded):
        return False
    return True


class MetricsView(APIView):
    """#137 纯标准库输出 Prometheus 文本指标。

    访问控制：仅 staff 或内网来源（REMOTE_ADDR）可读，其余一律 403；
    指标口径来自已有聚合表，DB 异常时只降级为 0，绝不让抓取端 500。
    """

    permission_classes = [AllowAny]

    def get(self, request):
        user = getattr(request, "user", None)
        is_staff = bool(user is not None and getattr(user, "is_authenticated", False) and user.is_staff)
        if not (is_staff or _metrics_internal_request(request)):
            return Response({"message": "metrics 仅限内网来源或管理员访问"}, status=403)
        body = self._render()
        return HttpResponse(body, content_type="text/plain; version=0.0.4; charset=utf-8")

    @staticmethod
    def _collect():
        """采集一次指标（失败项回落 0，键固定便于缓存复用）"""
        import time as _time

        from core.platform import uptime_seconds

        out = {
            "uptime_seconds": uptime_seconds(),
            "generated_at": int(_time.time()),
            "db_up": 0,
            "db_latency_ms": 0,
            "cache_up": 0,
            "exceptions_total": 0,
            "exception_signatures": 0,
            "slow_endpoints": 0,
            "operation_logs_24h": 0,
            "announcements_published": 0,
            "version": str(getattr(settings, "PLATFORM_VERSION", "")),
            "django": "",
            "python": "",
        }
        try:
            import django
            import platform as _platform

            out["django"] = django.get_version()
            out["python"] = _platform.python_version()
        except Exception:
            pass
        try:
            import time as _time2

            from django.db.models import Sum

            from core.models import ExceptionRecord

            t0 = _time2.time()
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            out["db_up"] = 1
            out["db_latency_ms"] = int((_time2.time() - t0) * 1000)
            agg = ExceptionRecord.objects.aggregate(total=Sum("count"), n=Count("id"))
            out["exceptions_total"] = int(agg.get("total") or 0)
            out["exception_signatures"] = int(agg.get("n") or 0)
        except Exception:
            out["db_up"] = 0
        try:
            from django.core.cache import cache

            probe = f"metrics:{out['generated_at']}"
            cache.set("core:metrics:probe", probe, 30)
            out["cache_up"] = 1 if cache.get("core:metrics:probe") == probe else 0
        except Exception:
            out["cache_up"] = 0
        try:
            from datetime import timedelta

            from core.models import Announcement, OperationLog, SlowEndpoint

            out["slow_endpoints"] = int(SlowEndpoint.objects.count())
            since = timezone.now() - timedelta(hours=24)
            out["operation_logs_24h"] = int(OperationLog.objects.filter(created_at__gte=since).count())
            out["announcements_published"] = int(Announcement.objects.filter(is_published=True).count())
        except Exception:
            pass
        return out

    @classmethod
    def _render(cls):
        from django.core.cache import cache

        body = None
        try:
            body = cache.get(_METRICS_CACHE_KEY)
        except Exception:
            body = None
        if body:
            return body
        m = cls._collect()
        lines = [
            "# HELP platform_db_up 1 if the database probe succeeded",
            "# TYPE platform_db_up gauge",
            f"platform_db_up {m['db_up']}",
            "# HELP platform_db_latency_ms Database probe latency in milliseconds",
            "# TYPE platform_db_latency_ms gauge",
            f"platform_db_latency_ms {m['db_latency_ms']}",
            "# HELP platform_cache_up 1 if the cache set/get probe succeeded",
            "# TYPE platform_cache_up gauge",
            f"platform_cache_up {m['cache_up']}",
            "# HELP platform_uptime_seconds Process uptime in seconds",
            "# TYPE platform_uptime_seconds gauge",
            f"platform_uptime_seconds {m['uptime_seconds']}",
            "# HELP platform_build_info Build/runtime info as labels",
            "# TYPE platform_build_info gauge",
            'platform_build_info{version="%s",django="%s",python="%s"} 1' % (
                _metric_label(m["version"]), _metric_label(m["django"]), _metric_label(m["python"]),
            ),
            "# HELP platform_exceptions_total Aggregated exception occurrences",
            "# TYPE platform_exceptions_total counter",
            f"platform_exceptions_total {m['exceptions_total']}",
            "# HELP platform_exception_signatures Distinct aggregated exception signatures",
            "# TYPE platform_exception_signatures gauge",
            f"platform_exception_signatures {m['exception_signatures']}",
            "# HELP platform_slow_endpoints Tracked slow endpoint paths",
            "# TYPE platform_slow_endpoints gauge",
            f"platform_slow_endpoints {m['slow_endpoints']}",
            "# HELP platform_operation_logs_24h Operation logs written in the last 24h",
            "# TYPE platform_operation_logs_24h gauge",
            f"platform_operation_logs_24h {m['operation_logs_24h']}",
            "# HELP platform_announcements_published Published announcements",
            "# TYPE platform_announcements_published gauge",
            f"platform_announcements_published {m['announcements_published']}",
            "# HELP platform_metrics_generated_timestamp Unix time when metrics were collected",
            "# TYPE platform_metrics_generated_timestamp gauge",
            f"platform_metrics_generated_timestamp {m['generated_at']}",
        ]
        out = "\n".join(lines) + "\n"
        try:
            cache.set(_METRICS_CACHE_KEY, out, METRICS_CACHE_SECONDS)
        except Exception:
            pass
        return out



# ---------------- F628 日志导出 CSV ----------------

class AdminLogExportView(APIView):
    """GET 导出日志 CSV：?kind=operation|login|exception（三类日志统一导出入口）"""

    permission_classes = [IsAdminUser]
    KINDS = ("operation", "login", "exception")

    @_guard
    def get(self, request):
        from core.platform import export_logs_csv

        kind = (request.query_params.get("kind") or "operation").strip()
        if kind not in self.KINDS:
            raise ValueError(f"kind 只能是 {'/'.join(self.KINDS)}")
        return export_logs_csv(kind, request)


# ---------------- F629 管理命令面板（白名单） ----------------

SAFE_COMMANDS = {
    "dump_data": {"label": "备份数据", "help": "把业务数据导出为 JSON 备份文件"},
    "daily_digest": {"label": "生成每日摘要", "help": "汇总当日笔记/文件并写入通知中心"},
    "reindex_search": {"label": "重建搜索索引", "help": "全量重建全文检索倒排索引"},
    # #68：按保留天数分批清理操作日志 / 分享访问 / 过期令牌 / 旧通知 / 搜索词
    "purge_retention": {"label": "清理过期数据", "help": "按保留天数分批清理日志与审计类大表"},
    "check": {"label": "系统检查", "help": "执行 Django check，输出配置与模型问题"},
}


def execute_safe_command(name, user=None, run_args=""):
    """执行白名单命令并落一条 AdminCommandRun。

    #417：从 AdminCommandRunView 抽出，手动执行（面板）与定时执行（ScheduledJob）
    共用同一套白名单 + 输出截断 + 异常记录逻辑，避免两处实现漂移。
    返回 (ok, output, error, duration_ms, run)；命令名不在白名单时抛 ValueError。
    """
    import io
    import time as _time

    from core.models import AdminCommandRun

    name = str(name or "").strip()
    if name not in SAFE_COMMANDS:
        raise ValueError(f"命令不在白名单内，已拒绝执行（仅允许 {'/'.join(SAFE_COMMANDS)}）")
    out_buf, err_buf = io.StringIO(), io.StringIO()
    ok, error = True, ""
    t0 = _time.time()
    try:
        from django.core.management import call_command

        call_command(name, stdout=out_buf, stderr=err_buf)
    except SystemExit as exc:
        ok = exc.code in (0, None)
        error = "" if ok else f"命令以退出码 {exc.code} 结束"
    except Exception as exc:  # noqa: BLE001
        ok = False
        error = f"{type(exc).__name__}: {exc}"
        try:
            from core.platform import record_exception

            record_exception(exc, f"/api/core/admin/commands/run/{name}")
        except Exception:
            logger.exception("B23：静默兜底已登记（core/views.py:816 原为 pass）——review 是否应收窄异常类型")
    duration = int((_time.time() - t0) * 1000)
    output = out_buf.getvalue()
    if err_buf.getvalue():
        output += ("\n[stderr]\n" + err_buf.getvalue()) if output else err_buf.getvalue()
    output = output[-4000:]
    run = AdminCommandRun.objects.create(
        command=name, args=(run_args or "")[:200], ok=ok, output=output, error=error[:2000],
        duration_ms=duration, ran_by=user, finished_at=timezone.now(),
    )
    return ok, output, error, duration, run


class AdminCommandListView(APIView):
    """GET 白名单命令列表 + 每条命令的上次执行结果

    #101：一次 ``values("command").annotate(last_id=Max("id"))`` 取每条命令的最新
    记录 ID，再一次性取回明细，替代「在 for 循环里逐条 order_by().first()」的 N+1。
    """

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.models import AdminCommandRun

        names = list(SAFE_COMMANDS)
        last_ids = dict(
            AdminCommandRun.objects.filter(command__in=names)
            # 显式清空默认排序，避免 Meta.ordering 混进 GROUP BY 把聚合拆成多组
            .order_by().values("command").annotate(last_id=Max("id"))
            .values_list("command", "last_id")
        )
        lasts = {}
        if last_ids:
            lasts = {
                r.command: r
                for r in AdminCommandRun.objects.filter(pk__in=list(last_ids.values())).select_related("ran_by")
            }
        rows = []
        for name, meta in SAFE_COMMANDS.items():
            last = lasts.get(name)
            rows.append({
                "name": name,
                "label": meta["label"],
                "help": meta["help"],
                "whitelisted": True,
                "last_run": None if last is None else {
                    "id": last.id,
                    "ok": last.ok,
                    "started_at": last.started_at.isoformat(),
                    "duration_ms": last.duration_ms,
                    "ran_by": last.ran_by.username if last.ran_by else "",
                    "output_tail": (last.output or last.error or "")[-800:],
                },
            })
        history = [
            {
                "id": r.id, "command": r.command, "ok": r.ok, "duration_ms": r.duration_ms,
                "started_at": r.started_at.isoformat(),
                "ran_by": r.ran_by.username if r.ran_by else "",
                "output_tail": (r.output or r.error or "")[-400:],
            }
            for r in AdminCommandRun.objects.select_related("ran_by").order_by("-started_at")[:20]
        ]
        return Response({"list": rows, "history": history, "total": len(rows)})


class AdminCommandRunView(APIView):
    """POST 手动触发白名单命令（仅白名单，禁止任意命令执行）"""

    permission_classes = [IsAdminUser]

    @_guard
    def post(self, request):
        name = str(request.data.get("name") or "").strip()
        if name not in SAFE_COMMANDS:
            raise ValueError(f"命令不在白名单内，已拒绝执行（仅允许 {'/'.join(SAFE_COMMANDS)}）")
        ok, output, error, duration, run = execute_safe_command(name, user=request.user)
        return Response({
            "ok": ok,
            "command": name,
            "label": SAFE_COMMANDS[name]["label"],
            "output": output,
            "error": error,
            "duration_ms": duration,
            "run_id": run.id,
            "message": f"命令执行{'成功' if ok else '失败'}（{duration} ms）",
        }, status=200 if ok else 422)


# ---------------- F630 公告已读率趋势（7 天） ----------------

class AnnouncementReadTrendView(APIView):
    """GET 近 7 天「按发布日」的公告已读率趋势（手绘 SVG 用数据）"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from datetime import timedelta

        from django.contrib.auth import get_user_model

        UserModel = get_user_model()
        window = as_int(request.query_params.get("days"), default=7, field="days", minimum=1, maximum=30)
        active_users = UserModel.objects.filter(is_active=True).count() or 1
        today = timezone.localdate()
        start_day = today - timedelta(days=window - 1)
        start_at = timezone.make_aware(
            timezone.datetime.combine(start_day, timezone.datetime.min.time())
        )

        ann_by_day = {}
        for a in Announcement.objects.filter(created_at__gte=start_at):
            # 与 start_day / DB 侧 created_at__date 统一按本地时区归日，
            # 否则 00:00-08:00 发布的公告会落到前一天的桶里
            ann_by_day.setdefault(timezone.localtime(a.created_at).date(), []).append(a.id)
        reads_by_day = {
            row["created_at__date"]: row["c"]
            for row in AnnouncementRead.objects.filter(created_at__gte=start_at)
            .values("created_at__date").annotate(c=Count("id"))
        }

        days = []
        for i in range(window):
            d = start_day + timedelta(days=i)
            ann_ids = ann_by_day.get(d, [])
            readers = (
                AnnouncementRead.objects.filter(announcement_id__in=ann_ids).count()
                if ann_ids else 0
            )
            rate = (
                round(readers * 100.0 / (len(ann_ids) * active_users), 1)
                if ann_ids else None
            )
            days.append({
                "date": d.isoformat(),
                "announcements": len(ann_ids),
                "readers": readers,
                "daily_reads": reads_by_day.get(d, 0),
                "rate": rate,
            })
        rates = [d["rate"] for d in days if d["rate"] is not None]
        return Response({
            "days": days,
            "window_days": window,
            "active_users": active_users,
            "avg_rate": round(sum(rates) / len(rates), 1) if rates else 0,
            "published_total": sum(d["announcements"] for d in days),
            "reads_total": sum(d["daily_reads"] for d in days),
        })


# ---------------- F631 用户活跃分层 ----------------

class UserActivityTiersView(APIView):
    """GET 用户活跃分层：注册总数 / 7 日活跃 / 30 日活跃 / 沉睡 / 新注册"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from django.contrib.auth import get_user_model

        UserModel = get_user_model()
        now = timezone.now()
        total = UserModel.objects.count() or 0
        d7, d30 = now - timezone.timedelta(days=7), now - timezone.timedelta(days=30)

        def active_since(since):
            return UserModel.objects.filter(
                Q(last_active_at__gte=since) | Q(last_login__gte=since)
            ).distinct().count()

        active_7d = active_since(d7)
        active_30d = active_since(d30)
        new_7d = UserModel.objects.filter(date_joined__gte=d7).count()
        new_30d = UserModel.objects.filter(date_joined__gte=d30).count()
        disabled = UserModel.objects.filter(is_disabled=True).count()
        dormant = max(0, total - active_30d)
        never = UserModel.objects.filter(last_active_at__isnull=True, last_login__isnull=True).count()

        def pct(n):
            return round(n * 100.0 / total, 1) if total else 0.0

        tiers = [
            {"key": "registered", "label": "注册总数", "count": total, "pct": 100.0 if total else 0.0,
             "color": "#6366f1"},
            {"key": "active_7d", "label": "7 日活跃", "count": active_7d, "pct": pct(active_7d),
             "color": "#10b981"},
            {"key": "active_30d", "label": "30 日活跃", "count": active_30d, "pct": pct(active_30d),
             "color": "#0ea5e9"},
            {"key": "dormant", "label": "30 日未活跃", "count": dormant, "pct": pct(dormant),
             "color": "#f59e0b"},
            {"key": "new_7d", "label": "7 日新注册", "count": new_7d, "pct": pct(new_7d),
             "color": "#22c55e"},
            {"key": "disabled", "label": "已禁用", "count": disabled, "pct": pct(disabled),
             "color": "#ef4444"},
        ]
        sample = [
            {
                "username": u.username,
                "display_name": u.display_name,
                "last_active_at": u.last_active_at.isoformat() if u.last_active_at else None,
                "date_joined": u.date_joined.isoformat() if u.date_joined else None,
                "tier": (
                    "active_7d" if u.last_active_at and (now - u.last_active_at) < timezone.timedelta(days=7)
                    else "active_30d" if u.last_active_at and (now - u.last_active_at) < timezone.timedelta(days=30)
                    else "dormant"
                ),
            }
            for u in UserModel.objects.order_by("-last_active_at")[:15]
        ]
        return Response({
            "tiers": tiers, "total": total, "active_7d": active_7d, "active_30d": active_30d,
            "new_7d": new_7d, "new_30d": new_30d, "dormant": dormant, "never_active": never,
            "disabled": disabled, "sample": sample, "window_days": 7,
        })


# ---------------- F632 慢接口 TOP10 ----------------

class SlowEndpointReportView(APIView):
    """POST 接收前端上报的接口耗时样本（登录用户均可上报，聚合后只读给管理员）"""

    permission_classes = [IsAuthenticated]

    @_guard
    def post(self, request):
        from core.platform import report_latency

        samples = request.data.get("samples")
        return Response(report_latency(samples))


class AdminSlowEndpointView(APIView):
    """GET 慢接口 TOP10（按平均耗时排序）"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.platform import slow_endpoints

        limit = as_int(request.query_params.get("limit"), default=10, field="limit", minimum=1, maximum=50)
        return Response(slow_endpoints(limit=limit))


# ---------------- F633 异常聚合 ----------------

class AdminExceptionListView(APIView):
    """GET 异常聚合列表（按签名去重计数）"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.models import ExceptionRecord

        qs = ExceptionRecord.objects.all()
        kw = (request.query_params.get("q") or "").strip()
        if kw:
            qs = qs.filter(Q(etype__icontains=kw) | Q(message__icontains=kw)
                           | Q(location__icontains=kw) | Q(path__icontains=kw))
        limit = as_int(request.query_params.get("limit"), default=50, field="limit", minimum=1, maximum=200)
        return Response({
            "list": [
                {
                    "id": r.id, "signature": r.signature, "etype": r.etype, "message": r.message,
                    "location": r.location, "path": r.path, "count": r.count,
                    "first_at": r.first_at.isoformat(), "last_at": r.last_at.isoformat(),
                    "sample": (r.sample or "")[-1200:],
                }
                for r in qs.order_by("-count", "-last_at")[:limit]
            ],
            "total": qs.count(),
            "keyword": kw,
        })


class ExceptionReportView(APIView):
    """POST 上报前端运行时异常（与服务端 try/except 共用同一套签名聚合）"""

    permission_classes = [IsAuthenticated]

    @_guard
    def post(self, request):
        from core.platform import record_exception

        message = str(request.data.get("message") or "client error")[:400]
        etype = str(request.data.get("type") or "ClientError")[:60]
        path = str(request.data.get("path") or "")[:200]
        exc = type(re.sub(r"[^A-Za-z0-9_]", "", etype) or "ClientError", (Exception,), {})(message)
        record_exception(exc, path, **_request_context(request))
        return Response({"ok": True, "message": "已记录"})


# ---------------- F634 登录失败 TOP ----------------

class AdminLoginFailTopView(APIView):
    """GET 近 N 天登录失败 TOP（按账号 / 按 IP），并回显当前是否处于锁定"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from accounts.models import LoginLog
        from accounts.views import LOGIN_LOCK_THRESHOLD, login_lock_state

        days = as_int(request.query_params.get("days"), default=7, field="days", minimum=1, maximum=90)
        since = timezone.now() - timezone.timedelta(days=days)
        qs = LoginLog.objects.filter(is_success=False, created_at__gte=since)
        by_account = [
            {
                "username": row["username"] or "（未填账号）",
                "fails": row["c"],
                "last_at": row["last"].isoformat() if row["last"] else "",
                "locked_seconds": login_lock_state(row["username"]) or 0,
            }
            for row in qs.values("username").annotate(
                c=Count("id"), last=Max("created_at")
            ).order_by("-c")[:10]
        ]
        by_ip = [
            {"ip": row["ip"] or "未知", "fails": row["c"],
             "last_at": row["last"].isoformat() if row["last"] else ""}
            for row in qs.values("ip").annotate(
                c=Count("id"), last=Max("created_at")
            ).order_by("-c")[:10]
        ]
        return Response({
            "window_days": days,
            "total_fails": qs.count(),
            "threshold": LOGIN_LOCK_THRESHOLD,
            "by_account": by_account,
            "by_ip": by_ip,
        })


# ---------------- F635 数据表行数 / 体积统计 ----------------

class AdminTableStatsView(APIView):
    """GET 数据表行数与体积统计"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.platform import table_stats

        top = as_int(request.query_params.get("top"), default=60, field="top", minimum=1, maximum=300)
        return Response(table_stats(top=top))


# ---------------- F638 运行配置只读视图（脱敏） ----------------

def _runtime_config_sections():
    """运行配置只读视图：所有敏感键一律脱敏，绝不返回 SECRET_KEY 原文"""
    import django
    import platform as _plat

    from core.platform import mask_value

    def kv(key, value=None):
        if value is None:
            value = getattr(settings, key, None)
        masked = mask_value(key, value)
        return {"k": key, "v": masked if isinstance(masked, str) else json.dumps(masked, ensure_ascii=False),
                "sensitive": masked != value}

    jwt = getattr(settings, "SIMPLE_JWT", {})
    db = settings.DATABASES.get("default", {})
    sections = [
        {"title": "基础", "items": [
            kv("PLATFORM_VERSION"),
            {"k": "DEBUG", "v": str(bool(getattr(settings, "DEBUG", False))), "sensitive": False},
            {"k": "LANGUAGE_CODE", "v": str(getattr(settings, "LANGUAGE_CODE", "")), "sensitive": False},
            {"k": "TIME_ZONE", "v": str(getattr(settings, "TIME_ZONE", "")), "sensitive": False},
            {"k": "ALLOWED_HOSTS", "v": ",".join(getattr(settings, "ALLOWED_HOSTS", []) or []), "sensitive": False},
            {"k": "DJANGO", "v": django.get_version(), "sensitive": False},
            {"k": "PYTHON", "v": _plat.python_version(), "sensitive": False},
        ]},
        {"title": "安全 / 认证", "items": [
            {"k": "应用签名密钥", "v": "••••••（已脱敏，不回显）", "sensitive": True},
            {"k": "ACCESS_TOKEN_LIFETIME", "v": str(jwt.get("ACCESS_TOKEN_LIFETIME", "")), "sensitive": False},
            {"k": "REFRESH_TOKEN_LIFETIME", "v": str(jwt.get("REFRESH_TOKEN_LIFETIME", "")), "sensitive": False},
            {"k": "AUTH_HEADER_TYPES", "v": ",".join(jwt.get("AUTH_HEADER_TYPES", ())), "sensitive": False},
            {"k": "PASSWORD_VALIDATORS",
             "v": ",".join(v["NAME"].rsplit(".", 1)[-1]
                           for v in getattr(settings, "AUTH_PASSWORD_VALIDATORS", [])), "sensitive": False},
            {"k": "CORS_ALLOW_ALL_ORIGINS", "v": str(getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False)),
             "sensitive": False},
        ]},
        {"title": "数据库", "items": [
            {"k": "ENGINE", "v": str(db.get("ENGINE", "")).rsplit(".", 1)[-1], "sensitive": False},
            {"k": "NAME", "v": str(db.get("NAME", "")).rsplit("/", 1)[-1].rsplit("\\", 1)[-1], "sensitive": False},
            {"k": "HOST", "v": str(db.get("HOST", "") or "(本地)"), "sensitive": False},
            {"k": "PORT", "v": str(db.get("PORT", "") or "-"), "sensitive": False},
            {"k": "凭据", "v": "已隐藏（数据库账号 / 口令不在本视图回显）", "sensitive": True},
        ]},
        {"title": "存储 / 限制", "items": [
            {"k": "MEDIA_URL", "v": str(getattr(settings, "MEDIA_URL", "")), "sensitive": False},
            {"k": "MEDIA_ROOT", "v": str(getattr(settings, "MEDIA_ROOT", "")), "sensitive": False},
            {"k": "FILE_MAX_SIZE_MB", "v": str(getattr(settings, "FILE_MAX_SIZE_MB", "")), "sensitive": False},
            {"k": "FILE_CHUNK_SIZE_MB", "v": str(getattr(settings, "FILE_CHUNK_SIZE_MB", "")), "sensitive": False},
            {"k": "PAGE_SIZE", "v": str(getattr(settings, "PAGE_SIZE", "")), "sensitive": False},
            {"k": "TRASH_KEEP_DAYS", "v": str(getattr(settings, "TRASH_KEEP_DAYS", "")), "sensitive": False},
        ]},
        {"title": "功能开关", "items": [
            {"k": "SEARCH_ENABLED", "v": str(bool(getattr(settings, "SEARCH_ENABLED", True))), "sensitive": False},
            {"k": "TENANCY_ENABLED", "v": str(bool(getattr(settings, "TENANCY_ENABLED", False))), "sensitive": False},
            {"k": "大模型密钥", "v": "已配置（不回显）" if getattr(settings, "LLM_API_KEY", "") else "未配置",
             "sensitive": True},
            {"k": "LLM_BASE_URL", "v": str(getattr(settings, "LLM_BASE_URL", "")), "sensitive": False},
            {"k": "LLM_MODEL", "v": str(getattr(settings, "LLM_MODEL", "")), "sensitive": False},
            {"k": "缓存连接", "v": "已配置（不回显）" if getattr(settings, "REDIS_URL", "") else "未配置",
             "sensitive": True},
        ]},
        {"title": "应用与中间件", "items": [
            {"k": "INSTALLED_APPS", "v": ", ".join(getattr(settings, "INSTALLED_APPS", [])), "sensitive": False},
            {"k": "MIDDLEWARE", "v": " → ".join(getattr(settings, "MIDDLEWARE", [])), "sensitive": False},
        ]},
    ]
    return sections


class AdminRuntimeConfigView(APIView):
    """GET 运行配置只读视图（脱敏；SECRET_KEY 等只显示掩码与长度）"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        if not request.user.is_superuser:
            # 只读视图对管理员开放，但非超管看到的是裁剪后的版本
            sections = _runtime_config_sections()[:3]
        else:
            sections = _runtime_config_sections()
        return Response({
            "sections": sections,
            "read_only": True,
            "masked": True,
            "generated_at": timezone.now().isoformat(),
            "note": "本页为只读运行配置；签名密钥 / 数据库口令 / 令牌 / API 密钥等敏感项一律不回显，仅提示是否已配置。",
        })


# ---------------- F639 维护模式开关 ----------------

class MaintenanceModeView(APIView):
    """GET 查看维护模式 / POST 开关（仅 superuser 可切换，避免管理员把自己锁在门外）"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.platform import MAINTENANCE_PUBLIC_PREFIXES, maintenance_enabled

        return Response({
            "enabled": maintenance_enabled(force=True),
            "key": "maintenance_mode",
            "public_paths": list(MAINTENANCE_PUBLIC_PREFIXES),
            "note": "开启后非 superuser 的 /api/ 请求统一返回 503 结构化提示；登录/健康/关于等公开路径不受影响。",
        })

    @_guard
    def post(self, request):
        if not request.user.is_superuser:
            return Response(
                {"ok": False, "error": "仅超级管理员可切换维护模式", "code": 403}, status=403
            )
        from core.platform import set_maintenance

        raw = request.data.get("enabled")
        enabled = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
        set_maintenance(enabled)
        OperationLog.objects.create(
            user=request.user, module="core",
            action="update", target="维护模式开关",
            detail="开启" if enabled else "关闭", ip=request.META.get("REMOTE_ADDR"),
        )
        return Response({
            "enabled": enabled,
            "message": "维护模式已开启，非超管请求将收到 503" if enabled else "维护模式已关闭，服务恢复正常",
        })


# ---------------- F640 跨模块审计检索 ----------------

class AdminAuditSearchView(APIView):
    """GET 跨模块审计检索：操作日志 / 登录日志 / 角色变更 / 管理命令 / 异常记录"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.platform import audit_search

        q = request.query_params.get("q") or ""
        kinds = [k for k in (request.query_params.get("kinds") or "").split(",") if k]
        limit = as_int(request.query_params.get("limit"), default=50, field="limit", minimum=1, maximum=200)
        return Response(audit_search(q=q, kinds=kinds or None, limit=limit))


# ---------------- F641 管理员群发通知 ----------------

class AdminBroadcastView(APIView):
    """GET 选人候选列表 / POST 群发通知（指定用户或全员）"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from django.contrib.auth import get_user_model

        UserModel = get_user_model()
        kw = (request.query_params.get("q") or "").strip()
        qs = UserModel.objects.all().order_by("username")
        if kw:
            qs = qs.filter(
                Q(username__icontains=kw) | Q(nickname__icontains=kw) | Q(email__icontains=kw)
            )
        rows = qs[:200]
        return Response({
            "list": [
                {
                    "id": u.id, "username": u.username, "display_name": u.display_name,
                    "avatar": u.avatar.url if u.avatar else "",
                    "email": u.email, "department": u.department.path_name() if u.department_id else "",
                    "is_disabled": u.is_disabled, "is_superuser": u.is_superuser,
                }
                for u in rows
            ],
            "total": qs.count(),
            "all_count": UserModel.objects.filter(is_active=True).count(),
        })

    @_guard
    def post(self, request):
        from django.contrib.auth import get_user_model

        UserModel = get_user_model()
        title = str(request.data.get("title") or "").strip()
        if not title:
            raise ValueError("通知标题不能为空")
        content = str(request.data.get("content") or "")[:4000]
        level = str(request.data.get("level") or "info")
        if level not in ("info", "success", "warning", "danger"):
            raise ValueError("level 只能是 info/success/warning/danger")
        link = str(request.data.get("link") or "")[:500]

        raw_ids = request.data.get("user_ids")
        target = str(request.data.get("target") or "").lower()
        if raw_ids in ("all", None) and target == "all":
            recipients = UserModel.objects.filter(is_active=True)
            scope = "全员"
        else:
            if isinstance(raw_ids, str):
                raw_ids = [x for x in raw_ids.replace("，", ",").split(",") if x.strip()]
            try:
                id_list = [int(x) for x in (raw_ids or [])]
            except (TypeError, ValueError):
                raise ValueError("user_ids 必须是用户 ID 数组")
            if not id_list:
                raise ValueError("请选择接收人（或 target=all 发送给全员）")
            recipients = UserModel.objects.filter(id__in=id_list, is_active=True)
            scope = f"{len(id_list)} 位指定用户"

        recipients = list(recipients[:5000])
        Notification.objects.bulk_create(
            [
                Notification(
                    recipient=u, title=title, content=content, level=level,
                    category="system", link=link,
                )
                for u in recipients
            ],
            batch_size=500,
        )
        sent = len(recipients)
        OperationLog.objects.create(
            user=request.user, module="core", action="create",
            target="群发通知", detail=f"{scope} · {title[:80]}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        return Response({"message": f"已发送给 {sent} 位用户", "sent": sent, "scope": scope},
                        status=201)


# ---------------- F642 关于页 ----------------

class AboutView(APIView):
    """GET 关于页：版本 / 最近提交（git 拿不到时优雅降级）/ 运行时长"""

    permission_classes = [AllowAny]

    @_guard
    def get(self, request):
        from core.platform import about_info

        return Response(about_info())


# ===========================================================================
# S26 平台能力（411–420）
# Webhook 订阅 / 投递记录 / 定时任务 / 接口报表 / 错误码目录 / 开发者门户
# ===========================================================================

# ---------------- 411 Webhook 订阅 ----------------

WEBHOOK_EVENT_SUGGESTIONS = (
    "*",
    "notification",
    "notification.system",
    "notification.file",
    "notification.note",
    "notification.project",
    "notification.message",
    "notification.share",
)
WEBHOOK_MAX_SUBSCRIPTIONS_PER_USER = 20
_EVENT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.*-]{1,64}$")


def _mask_secret(secret: str) -> str:
    secret = secret or ""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "…"
    return f"{secret[:6]}…{secret[-4:]}"


def _normalize_events(value) -> str:
    """events 入参：字符串（逗号分隔）或数组 → 规范化逗号串"""
    if value is None:
        items = []
    elif isinstance(value, str):
        items = list(value.replace("，", ",").split(","))
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValidationError("events 必须是字符串或数组")
    out = []
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        if not _EVENT_TOKEN_RE.match(token):
            raise ValidationError(f"事件名不合法：{token[:32]}")
        if token not in out:
            out.append(token)
    if len(out) > 20:
        raise ValidationError("事件最多 20 个")
    joined = ",".join(out)
    if len(joined) > 500:
        raise ValidationError("events 总长度不能超过 500")
    return joined


def _sub_item(sub, reveal=False) -> dict:
    return {
        "id": sub.id,
        "url": sub.url,
        "events": sub.event_list(),
        "events_raw": sub.events,
        "active": sub.active,
        "has_secret": bool(sub.secret),
        "secret": sub.secret if reveal else "",
        "secret_preview": _mask_secret(sub.secret),
        "created_at": sub.created_at.isoformat() if sub.created_at else "",
        "updated_at": sub.updated_at.isoformat() if sub.updated_at else "",
    }


def _delivery_item_view(delivery) -> dict:
    """投递记录对外结构（与 core.notify._delivery_item 字段保持一致）"""
    return {
        "id": delivery.id,
        "subscription_id": delivery.subscription_id,
        "url": getattr(delivery.subscription, "url", "") or "",
        "event": delivery.event,
        "status": delivery.status,
        "attempts": delivery.attempts,
        "response_code": delivery.response_code,
        "latency_ms": delivery.latency_ms,
        "error": delivery.error,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else "",
    }


class WebhookSubscriptionListView(APIView):
    """#411 GET 我的订阅列表 / POST 新建订阅"""

    @_guard
    def get(self, request):
        rows = list(
            WebhookSubscription.objects.filter(owner=request.user).order_by("-created_at")
        )
        return Response({
            "list": [_sub_item(s) for s in rows],
            "total": len(rows),
            "events": list(WEBHOOK_EVENT_SUGGESTIONS),
            "max": WEBHOOK_MAX_SUBSCRIPTIONS_PER_USER,
            "signature": "X-Webhook-Signature: sha256=hex(hmac_sha256(secret, timestamp + body))",
        })

    @_guard
    def post(self, request):
        import secrets as _secrets

        url = str(request.data.get("url") or "").strip()[:500]
        if not url:
            raise ValueError("请填写回调地址")
        if not is_safe_outbound_url(url):
            raise ValueError("回调地址必须是公网可访问的 http(s) 地址")
        if (
            WebhookSubscription.objects.filter(owner=request.user).count()
            >= WEBHOOK_MAX_SUBSCRIPTIONS_PER_USER
        ):
            raise ValueError(f"订阅数量已达上限（{WEBHOOK_MAX_SUBSCRIPTIONS_PER_USER}）")
        events = _normalize_events(request.data.get("events"))
        secret = str(request.data.get("secret") or "").strip()[:128]
        if not secret:
            secret = "whsec_" + _secrets.token_urlsafe(24)
        active = parse_bool(request.data.get("active"), field="active", default=True)
        sub = WebhookSubscription.objects.create(
            owner=request.user, url=url, events=events, secret=secret, active=active
        )
        return Response({
            "message": "订阅已创建，签名密钥仅本次完整返回，请立即保存",
            "subscription": _sub_item(sub, reveal=True),
        }, status=201)


def _owned_subscription(request, pk):
    return WebhookSubscription.objects.filter(pk=pk, owner=request.user).first()


class WebhookSubscriptionDetailView(APIView):
    """#411 GET / PATCH / DELETE 单个订阅"""

    @_guard
    def get(self, request, pk):
        sub = _owned_subscription(request, pk)
        if sub is None:
            return Response({"ok": False, "code": 404, "error": "订阅不存在"}, status=404)
        return Response({"subscription": _sub_item(sub)})

    @_guard
    def patch(self, request, pk):
        sub = _owned_subscription(request, pk)
        if sub is None:
            return Response({"ok": False, "code": 404, "error": "订阅不存在"}, status=404)
        if "url" in request.data:
            url = str(request.data.get("url") or "").strip()[:500]
            if not url:
                raise ValueError("回调地址不能为空")
            if not is_safe_outbound_url(url):
                raise ValueError("回调地址必须是公网可访问的 http(s) 地址")
            sub.url = url
        if "events" in request.data:
            sub.events = _normalize_events(request.data.get("events"))
        if "secret" in request.data:
            secret = str(request.data.get("secret") or "").strip()[:128]
            if not secret:
                raise ValueError("签名密钥不能为空（如需轮换请填写新密钥）")
            sub.secret = secret
        if "active" in request.data:
            sub.active = parse_bool(request.data.get("active"), field="active", default=sub.active)
        sub.save()
        return Response({"message": "订阅已更新", "subscription": _sub_item(sub)})

    @_guard
    def delete(self, request, pk):
        sub = _owned_subscription(request, pk)
        if sub is None:
            return Response({"ok": False, "code": 404, "error": "订阅不存在"}, status=404)
        sub.delete()
        return Response({"message": "订阅已删除", "deleted": pk})


# ---------------- 412 Webhook 投递记录 ----------------

class WebhookDeliveryListView(APIView):
    """#412 GET 我的投递记录（可按 status / subscription 过滤）"""

    @_guard
    def get(self, request):
        qs = WebhookDelivery.objects.filter(
            subscription__owner=request.user
        ).select_related("subscription")
        status_filter = (request.query_params.get("status") or "").strip()
        if status_filter:
            if status_filter not in ("pending", "success", "failed"):
                raise ValueError("status 只能是 pending/success/failed")
            qs = qs.filter(status=status_filter)
        sub_id = request.query_params.get("subscription")
        if sub_id:
            qs = qs.filter(subscription_id=as_int(sub_id, field="subscription", minimum=1))
        limit = as_int(request.query_params.get("limit"), default=50, field="limit",
                       minimum=1, maximum=200)
        rows = list(qs[:limit])
        return Response({
            "list": [_delivery_item_view(d) for d in rows],
            "total": qs.count(),
            "limit": limit,
            "status": status_filter,
        })


class WebhookDeliveryRetryView(APIView):
    """#412 POST 重试某条投递（复用已存载荷，指数退避 3 次）"""

    @_guard
    def post(self, request, pk):
        from core.notify import run_delivery

        delivery = (
            WebhookDelivery.objects.filter(pk=pk, subscription__owner=request.user)
            .select_related("subscription")
            .first()
        )
        if delivery is None:
            return Response({"ok": False, "code": 404, "error": "投递记录不存在"}, status=404)
        if delivery.subscription is None:
            return Response({"ok": False, "code": 404, "error": "订阅已删除"}, status=404)
        item = run_delivery(delivery)
        return Response({
            "message": "重试成功" if item["status"] == "success" else "重试仍失败，可稍后再试",
            "delivery": item,
        })


# ---------------- 413 Webhook 签名自测 ----------------

class WebhookVerifyView(APIView):
    """#413 POST 自测签名：生成签名头 / 校验收到的签名 / 发一条带签名的测试投递

    三种用法（按入参自动切换）：
    - ``{subscription_id}`` 或 ``{secret}`` → 返回样例载荷与签名头
    - 再带 ``url``（公网地址）→ 同时真实投递一次并回执行结果
    - 带 ``signature + timestamp + body`` → 校验该签名是否正确（valid）
    """

    @_guard
    def post(self, request):
        import time as _time

        from core.notify import (
            SAMPLE_WEBHOOK_PAYLOAD,
            WEBHOOK_SIGNATURE_HEADER,
            send_signed_webhook,
            sign_payload,
        )

        data = request.data
        secret = str(data.get("secret") or "").strip()
        sub_id = data.get("subscription_id")
        if not secret and sub_id:
            sub = _owned_subscription(request, as_int(sub_id, field="subscription_id", minimum=1))
            if sub is None:
                return Response({"ok": False, "code": 404, "error": "订阅不存在"}, status=404)
            secret = sub.secret
        if not secret:
            raise ValueError("请提供 secret 或 subscription_id")

        # 模式三：校验调用方收到的签名
        if data.get("signature") is not None:
            import hmac as _hmac

            timestamp = str(data.get("timestamp") or "").strip()
            raw_body = data.get("body")
            raw_body = (
                json.dumps(raw_body, ensure_ascii=False)
                if isinstance(raw_body, (dict, list)) else str(raw_body or "")
            )
            if not timestamp:
                raise ValueError("校验签名需要 timestamp")
            expected = sign_payload(secret, timestamp, raw_body)
            provided = str(data.get("signature") or "").strip()
            valid = bool(provided) and _hmac.compare_digest(expected, provided)
            return Response({
                "valid": valid,
                "expected": expected,
                "provided": provided,
                "header_name": WEBHOOK_SIGNATURE_HEADER,
                "message": "签名校验通过" if valid else "签名不匹配（检查 secret 与原始 body 字节）",
            })

        payload = (
            data.get("body") if isinstance(data.get("body"), dict)
            else dict(SAMPLE_WEBHOOK_PAYLOAD)
        )
        timestamp = int(_time.time())
        raw = json.dumps(payload, ensure_ascii=False)
        signature = sign_payload(secret, timestamp, raw)
        headers = {
            WEBHOOK_SIGNATURE_HEADER: signature,
            "X-Webhook-Timestamp": str(timestamp),
            "X-Webhook-Id": f"test_{timestamp}",
        }
        result = None
        url = str(data.get("url") or "").strip()[:500]
        if url:
            if not is_safe_outbound_url(url):
                raise ValueError("回调地址必须是公网可访问的 http(s) 地址")
            result = send_signed_webhook(url, payload, secret=secret, timeout=5)
        return Response({
            "ok": True if result is None else bool(result.get("ok")),
            "header_name": WEBHOOK_SIGNATURE_HEADER,
            "signature": signature,
            "timestamp": timestamp,
            "headers": headers,
            "body": raw,
            "payload": payload,
            "formula": "sha256=hex(hmac_sha256(secret, str(timestamp) + raw_body))",
            "delivery": result,
            "message": "签名已生成" + ("，测试载荷已投递" if url else "（用返回的 headers/body 校验接收端）"),
        })


# ---------------- 417 定时任务（调度中心） ----------------

MAX_SCHEDULES = 50
MAX_DUE_RUNS_PER_CALL = 10


def _schedule_item(job, now=None) -> dict:
    from core.platform import next_cron_time

    now = now or timezone.localtime()
    return {
        "id": job.id,
        "name": job.name,
        "command": job.command,
        "label": SAFE_COMMANDS.get(job.command, {}).get("label", ""),
        "cron": job.cron,
        "enabled": job.enabled,
        "last_run": job.last_run.isoformat() if job.last_run else None,
        "last_status": job.last_status,
        "last_output": job.last_output,
        "next_run": next_cron_time(job.cron, now),
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "updated_at": job.updated_at.isoformat() if job.updated_at else "",
    }


class AdminScheduledJobListView(APIView):
    """#417 GET 定时任务列表 / POST 新建（命令必须在白名单内）"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        now = timezone.localtime()
        rows = list(ScheduledJob.objects.all())
        return Response({
            "list": [_schedule_item(j, now) for j in rows],
            "total": len(rows),
            "commands": [{"name": k, **v} for k, v in SAFE_COMMANDS.items()],
            "max": MAX_SCHEDULES,
        })

    @_guard
    def post(self, request):
        from core.platform import parse_cron

        command = str(request.data.get("command") or "").strip()
        if command not in SAFE_COMMANDS:
            raise ValueError(f"命令不在白名单内（仅允许 {'/'.join(SAFE_COMMANDS)}）")
        cron = str(request.data.get("cron") or "").strip() or "*/30 * * * *"
        parse_cron(cron)  # 非法表达式抛 ValueError → 400
        if ScheduledJob.objects.count() >= MAX_SCHEDULES:
            raise ValueError(f"定时任务数量已达上限（{MAX_SCHEDULES}）")
        job = ScheduledJob.objects.create(
            name=str(request.data.get("name") or "").strip()[:80],
            command=command,
            cron=cron[:64],
            enabled=parse_bool(request.data.get("enabled"), field="enabled", default=True),
            created_by=request.user,
        )
        return Response({"message": "定时任务已创建", "job": _schedule_item(job)}, status=201)


class AdminScheduledJobDetailView(APIView):
    """#417 GET / PATCH / DELETE 单个定时任务"""

    permission_classes = [IsAdminUser]

    @staticmethod
    def _get(pk):
        return ScheduledJob.objects.filter(pk=pk).first()

    @_guard
    def get(self, request, pk):
        job = self._get(pk)
        if job is None:
            return Response({"ok": False, "code": 404, "error": "定时任务不存在"}, status=404)
        return Response({"job": _schedule_item(job)})

    @_guard
    def patch(self, request, pk):
        from core.platform import parse_cron

        job = self._get(pk)
        if job is None:
            return Response({"ok": False, "code": 404, "error": "定时任务不存在"}, status=404)
        if "command" in request.data:
            command = str(request.data.get("command") or "").strip()
            if command not in SAFE_COMMANDS:
                raise ValueError(f"命令不在白名单内（仅允许 {'/'.join(SAFE_COMMANDS)}）")
            job.command = command
        if "cron" in request.data:
            cron = str(request.data.get("cron") or "").strip()
            parse_cron(cron)
            job.cron = cron[:64]
        if "name" in request.data:
            job.name = str(request.data.get("name") or "").strip()[:80]
        if "enabled" in request.data:
            job.enabled = parse_bool(request.data.get("enabled"), field="enabled", default=job.enabled)
        job.save()
        return Response({"message": "定时任务已更新", "job": _schedule_item(job)})

    @_guard
    def delete(self, request, pk):
        job = self._get(pk)
        if job is None:
            return Response({"ok": False, "code": 404, "error": "定时任务不存在"}, status=404)
        job.delete()
        return Response({"message": "定时任务已删除", "deleted": pk})


class AdminScheduledJobDueView(APIView):
    """#417 POST 执行「当前分钟到期」的任务（外部 cron 每分钟调用一次）

    - 只执行 enabled 且 cron 命中当前分钟的任务；
    - 同一任务在同一分钟内只执行一次（接口被重复调用也不会重复跑）；
    - 单次调用最多执行 MAX_DUE_RUNS_PER_CALL 个任务，避免请求被拖死；
    - 每次执行都落一条 AdminCommandRun（与手动执行共用白名单逻辑）。
    """

    permission_classes = [IsAdminUser]

    @_guard
    def post(self, request):
        from core.platform import cron_matches

        now = timezone.localtime()
        minute_start = now.replace(second=0, microsecond=0)
        ran, skipped = [], []
        for job in ScheduledJob.objects.filter(enabled=True).order_by("id"):
            if not cron_matches(job.cron, now):
                continue
            if job.last_run and timezone.localtime(job.last_run) >= minute_start:
                skipped.append({"id": job.id, "command": job.command, "reason": "本分钟已执行"})
                continue
            if len(ran) >= MAX_DUE_RUNS_PER_CALL:
                skipped.append({"id": job.id, "command": job.command, "reason": "本次执行配额已满"})
                continue
            try:
                ok, output, error, duration, run = execute_safe_command(
                    job.command, user=None, run_args=f"schedule:{job.id}"
                )
            except Exception as exc:  # noqa: BLE001 —— 单任务异常不中断其它任务
                logger.exception("定时任务执行异常 job=%s", job.id)
                ok, output, error, duration, run = False, "", f"{type(exc).__name__}: {exc}", 0, None
            job.last_run = timezone.now()
            job.last_status = "success" if ok else "failed"
            job.last_output = ((output or "") + ("\n" + error if error else ""))[-2000:]
            job.save(update_fields=["last_run", "last_status", "last_output", "updated_at"])
            ran.append({
                "id": job.id,
                "command": job.command,
                "ok": ok,
                "duration_ms": duration,
                "run_id": getattr(run, "id", None),
                "error": error,
            })
        return Response({
            "checked_at": now.isoformat(),
            "due": len(ran) + len(skipped),
            "ran": ran,
            "skipped": skipped,
            "message": f"到期任务 {len(ran)} 个已执行" if ran else "当前没有到期任务",
        })


# ---------------- 418 接口报表 ----------------

class AdminApiUsageView(APIView):
    """#418 GET 按应用前缀聚合的调用量 / 慢调用 / 异常数

    数据源：OperationLog（写操作，按 module 归 app）、ApiTokenUsage（PAT 调用，
    按 last_path 归 app）、SlowEndpoint（慢接口采样，按路径归 app）、
    ExceptionRecord（近窗口异常，按 path 归 app）。
    """

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from accounts.models import ApiTokenUsage
        from core.platform import app_from_path

        days = as_int(request.query_params.get("days"), default=7, field="days",
                      minimum=1, maximum=90)
        start_day = timezone.localdate() - timedelta(days=days - 1)
        start_at = timezone.make_aware(
            timezone.datetime.combine(start_day, timezone.datetime.min.time())
        )

        buckets = {}

        def bucket(app):
            return buckets.setdefault(app, {
                "app": app, "ops": 0, "pat_calls": 0, "slow": 0, "slow_samples": 0,
                "errors": 0, "samples": 0, "total_ms": 0,
            })

        # 1) 写操作量（OperationLog.module 本身就是 app 名）
        for row in (
            OperationLog.objects.filter(created_at__gte=start_at)
            # 显式清空默认排序，避免 Meta.ordering 混进 GROUP BY 把聚合拆成多组
            .order_by().values("module").annotate(c=Count("id"))
        ):
            app = (row["module"] or "root").strip() or "root"
            bucket(app)["ops"] = row["c"]

        # 2) PAT 调用量（last_path 决定归属 app）
        for row in ApiTokenUsage.objects.filter(date__gte=start_day).values(
            "last_path", "count"
        ):
            bucket(app_from_path(row["last_path"]))["pat_calls"] += int(row["count"] or 0)

        # 3) 慢接口采样（表最多 400 行，全量参与，不受 days 限制）
        from core.models import ExceptionRecord, SlowEndpoint

        for row in SlowEndpoint.objects.values("path", "samples", "total_ms", "slow_samples"):
            app = app_from_path(row["path"])
            b = bucket(app)
            b["samples"] += int(row["samples"] or 0)
            b["total_ms"] += int(row["total_ms"] or 0)
            b["slow"] += int(row["slow_samples"] or 0)

        # 4) 异常数（按最近出现时间过滤）
        for row in (
            ExceptionRecord.objects.filter(last_at__gte=start_at)
            .order_by().values("path").annotate(n=Sum("count"))
        ):
            bucket(app_from_path(row["path"]))["errors"] += int(row["n"] or 0)

        rows = []
        for b in buckets.values():
            calls = b["ops"] + b["pat_calls"]
            rows.append({
                "app": b["app"],
                "calls": calls,
                "ops": b["ops"],
                "pat_calls": b["pat_calls"],
                "slow": b["slow"],
                "slow_samples": b["slow_samples"],
                "errors": b["errors"],
                "samples": b["samples"],
                "avg_ms": int(b["total_ms"] / b["samples"]) if b["samples"] else 0,
                "error_rate": (round(b["errors"] * 100.0 / calls, 1) if calls else 0),
            })
        rows.sort(key=lambda r: (-r["calls"], -r["errors"], r["app"]))
        totals = {
            "calls": sum(r["calls"] for r in rows),
            "ops": sum(r["ops"] for r in rows),
            "pat_calls": sum(r["pat_calls"] for r in rows),
            "slow": sum(r["slow"] for r in rows),
            "errors": sum(r["errors"] for r in rows),
            "apps": len(rows),
        }
        return Response({
            "window_days": days,
            "start": start_day.isoformat(),
            "end": timezone.localdate().isoformat(),
            "list": rows,
            "totals": totals,
            "note": "慢接口与异常为采样/聚合数据，按路径前缀归 app；days 只作用于操作日志、PAT 用量与异常。",
        })


# ---------------- 419 错误码目录 ----------------

class ErrorCatalogView(APIView):
    """#419 GET 反射 core.errors.ERR_* → [{code, name, message, hint}]"""

    permission_classes = [AllowAny]

    @_guard
    def get(self, request):
        from core.errors import error_catalog

        rows = error_catalog()
        return Response({
            "list": rows,
            "total": len(rows),
            "generated_at": timezone.now().isoformat(),
            "usage": "前端启动时拉取并与本地映射合并：优先按 code 命中，未命中时显示 message / hint。",
        })


# ---------------- 420 开发者门户汇总 ----------------

class DeveloperSummaryView(APIView):
    """#420 GET 开发者门户四卡片：令牌 / 近 7 天调用 / 订阅 / 失败投递"""

    @_guard
    def get(self, request):
        from accounts.models import ApiTokenUsage, PersonalAccessToken

        now = timezone.now()
        start_day = timezone.localdate() - timedelta(days=6)
        tokens = PersonalAccessToken.objects.filter(user=request.user)
        active_tokens = tokens.filter(revoked_at__isnull=True).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
        calls_7d = (
            ApiTokenUsage.objects.filter(token__user=request.user, date__gte=start_day)
            .aggregate(n=Sum("count")).get("n") or 0
        )
        subs = WebhookSubscription.objects.filter(owner=request.user)
        deliveries = WebhookDelivery.objects.filter(subscription__owner=request.user)
        failed = deliveries.filter(status="failed")
        total_deliveries = deliveries.count()
        failed_count = failed.count()
        return Response({
            "tokens": {
                "total": tokens.count(),
                "active": active_tokens.count(),
                "last_used_at": (
                    tokens.exclude(last_used_at__isnull=True)
                    .order_by("-last_used_at").values_list("last_used_at", flat=True).first()
                ),
            },
            "calls_7d": int(calls_7d),
            "window_days": 7,
            "subscriptions": {"total": subs.count(), "active": subs.filter(active=True).count()},
            "deliveries": {
                "total": total_deliveries,
                "failed": failed_count,
                "failed_7d": failed.filter(created_at__gte=now - timedelta(days=7)).count(),
                "success_rate": (
                    round((total_deliveries - failed_count) * 100.0 / total_deliveries, 1)
                    if total_deliveries else 100.0
                ),
            },
            "links": {
                "tokens": "/api/accounts/profile/tokens/",
                "webhooks": "/api/core/webhooks/subscriptions/",
                "openapi": "/api/docs/",
                "api_usage": "/api/core/admin/api-usage/?days=7",
                "errors": "/api/core/errors/catalog/",
            },
            "generated_at": now.isoformat(),
        })

