"""core 视图：通知中心 / 通知偏好 / 系统公告 / 操作日志 / 全局搜索 / 全文搜索 / 健康检查 / 站点设置"""
import csv
import json
import re

from django.conf import settings
from django.db import connection
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import (
    Announcement,
    AnnouncementRead,
    Notification,
    NotificationSetting,
    OperationLog,
    SiteSetting,
)
from core.pagination import StandardPagination
from core.scoping import scope_queryset, visible_user_ids
from core.utils import format_size


# ---------------- 序列化器 ----------------

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "category", "level", "title", "content", "link", "is_read", "created_at"]


class OperationLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default="")

    class Meta:
        model = OperationLog
        fields = ["id", "username", "module", "action", "target", "detail", "ip", "created_at"]


class NotificationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationSetting
        fields = ["category", "enabled"]


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
        request = self.context.get("request")
        if not request:
            return False
        return AnnouncementRead.objects.filter(announcement=obj, user=request.user).exists()

    def get_read_count(self, obj):
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


# ---------------- 通知 ----------------

class NotificationListView(APIView):
    """我的通知（分页、可按已读/分类/级别筛选）"""

    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)
        unread = request.query_params.get("unread")
        if unread == "1":
            qs = qs.filter(is_read=False)
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        level = request.query_params.get("level")
        if level:
            qs = qs.filter(level=level)
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        data = NotificationSerializer(page, many=True).data
        return Response({"list": data, "total": qs.count(), "page": pg.page.number if pg.page else 1})


class NotificationMarkReadView(APIView):
    """标记已读：传 id 列表；不传则全部已读"""

    def post(self, request):
        ids = request.data.get("ids") or []
        if ids:
            Notification.objects.filter(recipient=request.user, id__in=ids).update(is_read=True)
        else:
            Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({"message": "已标记为已读"})


class NotificationUnreadCountView(APIView):
    """未读通知数（右上角红点），grouped=1 时按分类返回"""

    def get(self, request):
        base = Notification.objects.filter(recipient=request.user, is_read=False)
        count = base.count()
        data = {"count": count}
        if request.query_params.get("grouped") == "1":
            grouped = {}
            for row in base.values("category").annotate(c=Count("id")):
                grouped[row["category"]] = row["c"]
            data["grouped"] = grouped
        return Response(data)


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
    """读取 / 更新我的通知偏好"""

    CATEGORIES = ["system", "file", "note", "project", "message", "share"]

    def get(self, request):
        qs = NotificationSetting.objects.filter(user=request.user)
        disabled = {s.category: s.enabled for s in qs}
        return Response({"settings": {c: disabled.get(c, True) for c in self.CATEGORIES}})

    def post(self, request):
        settings_map = request.data.get("settings") or {}
        for category, enabled in settings_map.items():
            if category not in self.CATEGORIES:
                continue
            obj, _ = NotificationSetting.objects.get_or_create(user=request.user, category=category)
            obj.enabled = bool(enabled)
            obj.save(update_fields=["enabled"])
        return Response({"message": "通知偏好已保存"})


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
        data = AnnouncementSerializer(qs[:50], many=True, context={"request": request}).data
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
    """管理员：发布 / 列表 / 更新 / 删除公告"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = Announcement.objects.all()
        return Response({"list": AnnouncementSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "公告标题不能为空"}, status=400)
        ann = Announcement.objects.create(
            title=title,
            content=request.data.get("content", ""),
            level=request.data.get("level", "info"),
            is_pinned=bool(request.data.get("is_pinned", False)),
            is_published=bool(request.data.get("is_published", True)),
            scheduled_at=request.data.get("scheduled_at") or None,
            expires_at=request.data.get("expires_at") or None,
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
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
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
    """操作日志聚合统计（管理员）：按模块 / 动作 / 日期"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        qs = _filter_logs(request, OperationLog.objects.all())
        by_module = list(qs.values("module").annotate(c=Count("id")).order_by("-c"))
        by_action = list(qs.values("action").annotate(c=Count("id")).order_by("-c"))
        by_day = list(qs.extra({"d": "date(created_at)"}).values("d").annotate(c=Count("id")).order_by("d"))[-30:]
        return Response({"by_module": by_module, "by_action": by_action, "by_day": by_day, "total": qs.count()})


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
            .annotate(total_bytes=Sum("size"), file_count=Sum("id"))
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

class BackupView(APIView):
    """管理员：触发数据备份"""

    permission_classes = [IsAdminUser]

    def post(self, request):
        import os
        from datetime import datetime
        from django.core.management import call_command
        from django.conf import settings
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = str(settings.BASE_DIR / f"backup_{ts}.json")
        excludes = ["contenttypes", "auth.Permission", "sessions", "admin.LogEntry"]
        call_command("dumpdata", "--indent", "2", "--output", out,
                     "--natural-foreign", "--natural-primary",
                     *[f"--exclude={e}" for e in excludes])
        size = os.path.getsize(out)
        return Response({"message": "备份完成", "file": os.path.basename(out), "size_kb": round(size / 1024, 1)})


# ---------------- 全局搜索 ----------------

class GlobalSearchView(APIView):
    """跨模块全局搜索：文件 / 笔记 / 项目 / 任务，一次返回各模块命中"""

    def get(self, request):
        from files.models import FileMeta
        from notes.models import Note
        from projects.models import Project, TaskCard

        kw = (request.query_params.get("q") or "").strip()
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

    def get(self, request):
        db_ok = True
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        except Exception:
            db_ok = False
        return Response({
            "status": "ok" if db_ok else "degraded",
            "db": db_ok,
            "version": getattr(settings, "PLATFORM_VERSION", "1.0.0"),
        })


class PublicSiteSettingView(APIView):
    """公开读取站点设置（白名单键）"""

    permission_classes = [AllowAny]
    PUBLIC_KEYS = [
        "site_name", "site_description", "register_enabled", "contact_email",
        "footer_text", "logo_url", "primary_color",
    ]

    def get(self, request):
        qs = SiteSetting.objects.filter(key__in=self.PUBLIC_KEYS)
        return Response({"settings": {s.key: s.value for s in qs}})


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
        try:
            limit = min(int(request.query_params.get("limit", 20)), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return Response({"ok": False, "error": "limit / offset 需为整数"}, status=400)
        data = search(q, visible_user_ids(request.user), modules=modules or None, limit=limit, offset=offset)
        data["limit"] = limit
        data["offset"] = offset
        # 记录搜索词（#63）：失败不影响主流程
        try:
            from core.models import SearchQueryLog
            SearchQueryLog.objects.create(
                owner=request.user, term=q[:200], result_count=data.get("total", 0))
        except Exception:
            pass
        return Response(data)


class SearchSuggestView(APIView):
    """检索词联想：GET /api/core/search/suggest/?q=文"""

    def get(self, request):
        from core.search import suggest

        q = request.query_params.get("q") or ""
        limit = min(int(request.query_params.get("limit", 10)), 30)
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


# ---------------- 搜索历史 / 热词 / 导出（#63 #65） ----------------

class SearchHistoryView(APIView):
    """我的搜索历史：GET /api/core/search/history/?limit=20"""

    def get(self, request):
        from core.models import SearchQueryLog
        limit = min(int(request.query_params.get("limit", 20)), 100)
        rows = SearchQueryLog.objects.filter(owner=request.user)[:limit]
        # 去重（保留最新一次）
        seen, items = set(), []
        for r in rows:
            if r.term in seen:
                continue
            seen.add(r.term)
            items.append({"term": r.term, "result_count": r.result_count, "at": r.created_at})
        return Response({"list": items[:limit]})

    def delete(self, request):
        from core.models import SearchQueryLog
        n = SearchQueryLog.objects.filter(owner=request.user).delete()[0]
        return Response({"message": f"已清空 {n} 条搜索历史"})


class SearchHotView(APIView):
    """全局热词：GET /api/core/search/hot/?limit=10  近7天高频搜索词"""

    def get(self, request):
        from django.db.models import Count
        from django.utils import timezone
        from core.models import SearchQueryLog
        since = timezone.now() - timezone.timedelta(days=7)
        rows = (SearchQueryLog.objects.filter(created_at__gte=since)
                .values("term").annotate(c=Count("id")).order_by("-c", "term")[:20])
        return Response({"list": [{"term": r["term"], "count": r["c"]} for r in rows]})


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
        resp["Content-Disposition"] = f"attachment; filename=search_{q[:20]}.csv"
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

def _guard(fn):
    """新视图统一异常兜底：ValueError → 400，其余异常 → 422（结构化，绝不 500）"""

    from functools import wraps

    @wraps(fn)
    def inner(self, request, *args, **kwargs):
        try:
            return fn(self, request, *args, **kwargs)
        except ValueError as exc:
            return Response({"ok": False, "error": str(exc), "code": 400}, status=400)
        except Exception as exc:  # noqa: BLE001 —— 结构化降级
            try:
                from core.platform import record_exception

                record_exception(exc, getattr(request, "path", ""))
            except Exception:
                pass
            return Response(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}", "code": 422},
                status=422,
            )

    return inner


# ---------------- F627 后端健康卡 ----------------

class AdminHealthCardView(APIView):
    """GET 后端健康卡：DB 连通 / 表数 / 最新迁移 / 存储占用 / 运行时"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.platform import health_card

        return Response(health_card())


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
    "check": {"label": "系统检查", "help": "执行 Django check，输出配置与模型问题"},
}


class AdminCommandListView(APIView):
    """GET 白名单命令列表 + 每条命令的上次执行结果"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from core.models import AdminCommandRun

        rows = []
        for name, meta in SAFE_COMMANDS.items():
            last = AdminCommandRun.objects.filter(command=name).order_by("-started_at").first()
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
        import io
        import time as _time

        from core.models import AdminCommandRun

        name = str(request.data.get("name") or "").strip()
        if name not in SAFE_COMMANDS:
            raise ValueError("命令不在白名单内，已拒绝执行（仅允许 dump_data/daily_digest/reindex_search/check）")
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

                record_exception(exc, request.path)
            except Exception:
                pass
        duration = int((_time.time() - t0) * 1000)
        output = out_buf.getvalue()
        if err_buf.getvalue():
            output += ("\n[stderr]\n" + err_buf.getvalue()) if output else err_buf.getvalue()
        output = output[-4000:]
        run = AdminCommandRun.objects.create(
            command=name, ok=ok, output=output, error=error[:2000], duration_ms=duration,
            ran_by=request.user, finished_at=timezone.now(),
        )
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
        window = min(max(int(request.query_params.get("days", 7) or 7), 1), 30)
        active_users = UserModel.objects.filter(is_active=True).count() or 1
        today = timezone.localdate()
        start_day = today - timedelta(days=window - 1)
        start_at = timezone.make_aware(
            timezone.datetime.combine(start_day, timezone.datetime.min.time())
        )

        ann_by_day = {}
        for a in Announcement.objects.filter(created_at__gte=start_at):
            ann_by_day.setdefault(a.created_at.date(), []).append(a.id)
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

        limit = min(max(int(request.query_params.get("limit", 10) or 10), 1), 50)
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
        limit = min(max(int(request.query_params.get("limit", 50) or 50), 1), 200)
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
        record_exception(exc, path)
        return Response({"ok": True, "message": "已记录"})


# ---------------- F634 登录失败 TOP ----------------

class AdminLoginFailTopView(APIView):
    """GET 近 N 天登录失败 TOP（按账号 / 按 IP），并回显当前是否处于锁定"""

    permission_classes = [IsAdminUser]

    @_guard
    def get(self, request):
        from accounts.models import LoginLog
        from accounts.views import LOGIN_LOCK_THRESHOLD, login_lock_state

        days = min(max(int(request.query_params.get("days", 7) or 7), 1), 90)
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

        top = min(max(int(request.query_params.get("top", 60) or 60), 1), 300)
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
            kv("SECRET_KEY"),
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
            {"k": "凭据", "v": "已隐藏（USER/PASSWORD 不在本视图回显）", "sensitive": True},
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
            kv("LLM_API_KEY"),
            {"k": "LLM_BASE_URL", "v": str(getattr(settings, "LLM_BASE_URL", "")), "sensitive": False},
            {"k": "LLM_MODEL", "v": str(getattr(settings, "LLM_MODEL", "")), "sensitive": False},
            kv("REDIS_URL"),
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
            "note": "本页为只读运行配置，敏感键（SECRET_KEY / 密码 / Token / 密钥）已脱敏，绝不回显原文。",
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
        limit = request.query_params.get("limit") or 50
        return Response(audit_search(q=q, kinds=kinds or None, limit=int(limit)))


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

        sent = 0
        for u in recipients[:5000]:
            Notification.objects.create(
                recipient=u, title=title, content=content, level=level,
                category="system", link=link,
            )
            sent += 1
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
