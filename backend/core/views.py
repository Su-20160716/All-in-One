"""core 视图：通知中心 / 通知偏好 / 系统公告 / 操作日志 / 全局搜索 / 全文搜索 / 健康检查 / 站点设置"""
import csv
import json

from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAdminUser
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

    class Meta:
        model = Announcement
        fields = [
            "id", "title", "content", "level", "is_pinned", "is_published",
            "author_name", "is_read", "read_count", "created_at", "updated_at",
        ]

    def get_is_read(self, obj):
        request = self.context.get("request")
        if not request:
            return False
        return AnnouncementRead.objects.filter(announcement=obj, user=request.user).exists()

    def get_read_count(self, obj):
        return obj.read_records.count()


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
    """公告列表（全员，仅已发布）+ 未读数"""

    def get(self, request):
        qs = Announcement.objects.filter(is_published=True)
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
            author=request.user,
        )
        return Response(AnnouncementSerializer(ann).data, status=201)


class AdminAnnouncementDetailView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, pk):
        ann = Announcement.objects.filter(pk=pk).first()
        if not ann:
            return Response({"message": "公告不存在"}, status=404)
        for f in ("title", "content", "level", "is_pinned", "is_published"):
            if f in request.data:
                setattr(ann, f, request.data[f])
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
    PUBLIC_KEYS = ["site_name", "site_description", "register_enabled", "contact_email", "footer_text"]

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
    """

    def get(self, request):
        from core.search import search

        q = request.query_params.get("q") or request.query_params.get("keyword") or ""
        if not q.strip():
            return Response({"total": 0, "results": [], "terms": [], "took_ms": 0, "query": ""})
        modules = [m for m in (request.query_params.get("module") or "").split(",") if m]
        limit = min(int(request.query_params.get("limit", 20)), 100)
        offset = max(int(request.query_params.get("offset", 0)), 0)
        data = search(q, visible_user_ids(request.user), modules=modules or None, limit=limit, offset=offset)
        data["limit"] = limit
        data["offset"] = offset
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
