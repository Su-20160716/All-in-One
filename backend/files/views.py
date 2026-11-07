"""文件管理视图：文件夹树、分片上传、断点续传、秒传、回收站、共享链接、
批量操作、在线新建/编辑、复制、收藏备注、存储分析、重复检测、最近访问、打包下载、
多类型在线预览（含 HTTP Range 流式播放）、Office 转 PDF。"""
import logging

logger = logging.getLogger(__name__)

import csv
import json
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncDate
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Notification, notify
from core.pagination import OptionalPageNumberPagination, StandardPagination
from core.quota import check_quota, used_bytes
from core.scoping import is_visible, scope_queryset
from core.utils import file_kind, format_size, sha1_file
from core.validators import as_int, parse_bool, sanitize_filename
from files import office, versioning
from files.models import (
    ChunkUpload,
    FileMeta,
    FileOperationLog,
    FileTag,
    FileVersion,
    FileVisibilitySnapshot,
    Folder,
    RecentFile,
    ShareLink,
    ShareVisit,
)
from files.serializers import (
    ChunkInitSerializer,
    FileMetaSerializer,
    FileTagSerializer,
    FolderSerializer,
    ShareLinkSerializer,
)
from files.share_access import (
    ShareAccessError,
    bump_download,
    bump_view,
    find_link,
    request_password,
    validate_link,
)

MEDIA = settings.MEDIA_ROOT


def _safe_join(base, *paths):
    """把用户可控的相对路径安全地拼到 base 下。

    旧实现用 `startswith(base)` 判断，`/media_evil` 这类同前缀兄弟目录能绕过
    `/media` 的判断。改用 commonpath，并处理 Windows 跨盘抛出的 ValueError。
    """
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base_real, *paths))
    try:
        inside = os.path.commonpath([base_real, target]) == base_real
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("非法路径")
    return target


def _parse_uuid(value):
    """把上传任务 id 收敛成 UUID；非法返回 None（调用方回 400）。

    `?upload_id=abc` 直接丢给 filter() 会抛 Django 字段校验异常 → 500。
    """
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _as_id_list(value, field="file_ids", max_items=1000):
    """把入参收敛成正整数列表；非数组或含非法项返回 None。

    直接把 "abc" 丢给 `id__in=` 会触发 Django 的字段校验异常 → 500。
    """
    if not isinstance(value, (list, tuple)) or len(value) > max_items:
        return None
    try:
        return [as_int(x, field=field, minimum=1) for x in value]
    except ValidationError:
        return None


def _index_file(fm):
    """F12：把文件写入全文索引（文本类抽取前 64KB，其余仅索引文件名/备注）。"""
    try:
        from core.search import can_index, extract_text, index_document

        ext = (fm.ext or "").lower()
        body = ""
        if can_index(ext):
            body = extract_text(_safe_join(MEDIA, fm.storage_path), ext)[:65536]
        index_document("file", fm.id, fm.owner_id, fm.name, body, fm.description)
    except Exception:
        logger.warning("文件全文索引失败：file=%s", fm.id)


def _file_qs(user):
    """按数据范围取可见文件"""
    return scope_queryset(FileMeta.objects.all(), user)


def _get_file(user, pk, include_deleted=False):
    fm = _file_qs(user).filter(pk=pk).first()
    if fm is None:
        return None
    if fm.is_deleted and not include_deleted:
        return None
    return fm


def _authorize_file_bytes(request, fm, *, consume_download=False):
    """原文件字节流输出（raw / pdf / download）的统一授权。

    口径与 `/download/` 完全一致：owner 直接放行；非 owner 必须携带
    指向**本文件**的分享 token，并完整通过撤销/过期/密码/权限/次数上限校验。
    数据范围（dept/all）不再能绕过分享限制直接读取原文件。

    :param consume_download: True 时原子占用一次下载额度（整包下载）；
        流式内联预览（Range 拖动、PDF 渲染）只校验不计数，避免播放器
        一次拖动就耗尽 max_downloads。
    :returns: None 表示放行；否则返回可直接 return 的 Response
    """
    if fm.owner_id == request.user.id:
        return None
    token = request.query_params.get("share") or request.query_params.get("token")
    if not token:
        return Response(
            # 1016 是登录锁定专用码（accounts LoginView），这里用 1011 无操作权限
            {"message": "非本人文件，需通过共享链接访问", "code": 1011},
            status=status.HTTP_403_FORBIDDEN,
        )
    link = find_link(token, file_id=fm.pk)
    try:
        validate_link(link, request_password(request),
                      for_download=True, request=request)
    except ShareAccessError as exc:
        return exc.as_response()
    if consume_download and not bump_download(link):
        return Response({"message": "下载次数已达上限"}, status=status.HTTP_403_FORBIDDEN)
    return None


def _touch_recent(user, fm):
    """记录最近访问"""
    try:
        rec, created = RecentFile.objects.get_or_create(owner=user, file=fm)
        if not created:
            rec.save(update_fields=["accessed_at"])
    except Exception:
        logger.exception("B23：静默兜底已登记（files/views.py:100 原为 pass）——review 是否应收窄异常类型")


def _owner_folder(user, folder_id):
    if folder_id in (None, "", "null", "0", 0):
        return None
    try:
        folder_id = int(folder_id)
    except (TypeError, ValueError):
        return None  # 非法 id 视为根目录，避免 500
    return Folder.objects.filter(pk=folder_id, owner=user).first()


def _would_create_cycle(folder, new_parent):
    """把 folder 移动到 new_parent 下是否会形成环：沿 new_parent 祖先链上溯，遇到 folder 即成环"""
    node = new_parent
    guard = 0
    while node is not None and guard < 100:
        if node.pk == folder.pk:
            return True
        node = node.parent
        guard += 1
    return False


# ============ F559 操作记录 / F561 可见性快照 辅助 ============

def _folder_label(folder):
    return folder.name if folder else "根目录"


def _log_op(user, fm, action, detail="", from_folder="", to_folder=""):
    """写一条文件操作流水；任何异常都不影响主流程"""
    try:
        FileOperationLog.objects.create(
            owner=user, file=fm, file_name=fm.name if fm else "", action=action,
            detail=str(detail or "")[:500], from_folder=str(from_folder or "")[:200],
            to_folder=str(to_folder or "")[:200],
        )
    except Exception:
        logger.exception("B23：静默兜底已登记（files/views.py:140 原为 pass）——review 是否应收窄异常类型")


def _restore_files(user, qs):
    """恢复回收站文件：原目录不存在回根目录，同目录同名自动改名「原名(已恢复)」"""
    restored, renamed = 0, 0
    now = timezone.now()
    for fm in qs:
        folder = None
        if fm.origin_folder_id:
            folder = Folder.objects.filter(pk=fm.origin_folder_id, owner=user).first()
        fm.folder = folder
        name = fm.name
        if FileMeta.objects.filter(
            owner=user, folder=folder, is_deleted=False, name=name,
        ).exclude(pk=fm.pk).exists():
            base, ext = os.path.splitext(name)
            candidate, i = f"{base}(已恢复){ext}", 2
            while FileMeta.objects.filter(
                owner=user, folder=folder, is_deleted=False, name=candidate,
            ).exclude(pk=fm.pk).exists():
                candidate = f"{base}(已恢复{i}){ext}"
                i += 1
            fm.name = candidate
            renamed += 1
        fm.is_deleted = False
        fm.deleted_at = None
        fm.updated_at = now
        fm.save(update_fields=["folder", "name", "is_deleted", "deleted_at", "updated_at"])
        _log_op(user, fm, "restore", detail="恢复自回收站", to_folder=_folder_label(folder))
        restored += 1
    return restored, renamed


def _notify_quota_cross(user, used_before, used_after):
    """S24-234：上传后按配额占用首次越过 80% / 90% 各发一次站内提醒（按日去重）"""
    try:
        quota_mb = getattr(user, "storage_quota_mb", 0) or 0
        if quota_mb <= 0:
            return
        limit = quota_mb * 1024 * 1024
        before = used_before / limit * 100
        after = used_after / limit * 100
        today = timezone.localdate()
        for threshold in (80, 90):
            if before < threshold <= after:
                title = f"存储空间已使用 {threshold}%"
                if Notification.objects.filter(
                    recipient=user, title=title, created_at__date=today,
                ).exists():
                    continue
                notify(
                    user, title,
                    content=(f"当前已用 {format_size(used_after)} / {format_size(limit)}"
                             f"（{after:.0f}%）。建议清理大文件、重复文件或回收站释放空间。"),
                    category="file", level="warning", link="/files/analysis",
                )
    except Exception:
        logger.exception("S24-234：配额预警通知失败")


def _active_file_shares(fm):
    """文件当前有效的共享链接（未撤销、未过期、未达下载上限）"""
    now = timezone.now()
    return [l for l in ShareLink.objects.filter(file=fm, is_revoked=False)
            if l.expire_at is None or l.expire_at > now]


def _visibility_state(fm):
    """计算文件当前可见性状态"""
    shares = list(ShareLink.objects.filter(file=fm).order_by("-created_at"))
    active = [l for l in shares if not l.is_expired]
    if not shares:
        vis = "private"
    elif active:
        vis = "shared"
    elif all(l.is_revoked for l in shares):
        vis = "revoked"
    else:
        vis = "expired"
    from core.scoping import describe_scope
    try:
        scope = describe_scope(fm.owner).get("scope", "self")
    except Exception:
        scope = "self"
    return {
        "file_id": fm.id,
        "file_name": fm.name,
        "visibility": vis,
        "visibility_label": {"private": "仅自己可见", "shared": "共享链接可见",
                             "expired": "链接已过期", "revoked": "链接已撤销"}[vis],
        "data_scope": scope,
        "owner": getattr(fm.owner, "display_name", "") or getattr(fm.owner, "username", ""),
        "active_shares": len(active),
        "shares": [{
            "token": l.token, "permission": l.permission, "is_revoked": l.is_revoked,
            "is_expired": l.is_expired,
            # B23 排障修复：expire_at 是 datetime，此 dict 会整包塞进
            # FileVisibilitySnapshot.snapshot（JSONField）——原来直接放 datetime
            # 对象，一旦文件有未过期分享就 TypeError 炸栈（被 except 静默吞掉，
            # 可见性快照从此missed）。isoformat 后存储/接口两端都安全。
            "expire_at": l.expire_at.isoformat() if l.expire_at else None,
            "password": bool(l.password), "view_count": l.view_count, "download_count": l.download_count,
            "url": f"/share/{l.token}",
        } for l in shares[:20]],
    }


def _push_file_event(user_id, action, **data):
    """S2-B1：文件变动 WS 广播（on_commit 延后到事务提交后，回滚不广播）。

    广播失败只记日志不影响主流程——WS 是增值通道，不是正确性依赖。
    前端 app store 订阅 file_event 后可在其它标签页同步文件列表。
    """
    def _emit():
        try:
            from ws_app.events import notify_file_event
            notify_file_event(user_id, action, data)
        except Exception:
            logger.exception("S2-B1：文件事件广播失败 action=%s", action)

    transaction.on_commit(_emit)


def _record_visibility(fm, user, note="", action=""):
    """落一条可见性快照（分享创建/修改/撤销时自动调用）"""
    try:
        state = _visibility_state(fm)
        active = _active_file_shares(fm)
        link = active[0] if active else None
        FileVisibilitySnapshot.objects.create(
            file=fm, created_by=user, visibility=state["visibility"],
            data_scope=state["data_scope"], share_token=link.token if link else "",
            permission=link.permission if link else "",
            expire_at=link.expire_at if link else None,
            snapshot=state, note=note or action,
        )
    except Exception:
        logger.exception("B23：静默兜底已登记（files/views.py:199 原为 pass）——review 是否应收窄异常类型")


# ============ 文件夹 ============

class FolderListView(APIView):
    """文件夹列表：?parent= 根目录为 null；支持新建、颜色"""

    def get(self, request):
        parent = request.query_params.get("parent")
        if parent in (None, "", "null", "0"):
            parent = None
        else:
            try:
                parent = int(parent)
            except (TypeError, ValueError):
                return Response({"message": "parent 必须是整数"}, status=400)
        # B6：file_count / folder_count / total_size 用相关子查询一次算完，
        # 否则每个文件夹 3 次 COUNT/SUM
        file_count = Subquery(
            FileMeta.objects.filter(folder=OuterRef("pk"), is_deleted=False)
            .values("folder").annotate(c=Count("id")).values("c")[:1]
        )
        total_size = Subquery(
            FileMeta.objects.filter(folder=OuterRef("pk"), is_deleted=False)
            .values("folder").annotate(s=Sum("size")).values("s")[:1]
        )
        folder_count = Subquery(
            Folder.objects.filter(parent=OuterRef("pk"))
            .values("parent").annotate(c=Count("id")).values("c")[:1]
        )
        qs = Folder.objects.filter(owner=request.user, parent_id=parent).annotate(
            file_count_ann=file_count,
            folder_count_ann=folder_count,
            total_size_ann=total_size,
        )
        return Response({"list": FolderSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = sanitize_filename(str(request.data.get("name") or "").strip(), fallback="")
        if not name:
            return Response({"message": "文件夹名称不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        parent_id = request.data.get("parent")
        parent = _owner_folder(request.user, parent_id)
        if parent_id and not parent:
            return Response({"message": "父文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
        folder = Folder.objects.create(
            name=name, parent=parent, owner=request.user, color=request.data.get("color", "default")
        )
        return Response(FolderSerializer(folder).data, status=status.HTTP_201_CREATED)


class FolderTreeView(APIView):
    """完整文件夹嵌套树（移动/目录导航用）"""

    def get(self, request):
        def build(parent_id, visited):
            qs = Folder.objects.filter(owner=request.user, parent_id=parent_id).order_by("name")
            nodes = []
            for f in qs:
                # 防递归：历史脏数据可能成环，已访问过的 id 不再展开
                if f.id in visited:
                    nodes.append({"id": f.id, "name": f.name, "color": f.color, "parent": f.parent_id,
                                  "children": [], "cycle": True})
                    continue
                visited.add(f.id)
                nodes.append({
                    "id": f.id, "name": f.name, "color": f.color, "parent": f.parent_id,
                    "children": build(f.id, visited),
                })
            return nodes
        return Response({"tree": build(None, set())})


class FolderBreadcrumbView(APIView):
    """文件夹面包屑路径（从根到当前）"""

    def get(self, request, pk):
        folder = Folder.objects.filter(pk=pk, owner=request.user).first()
        if not folder:
            return Response({"message": "文件夹不存在"}, status=404)
        crumbs = []
        node = folder
        guard = 0
        while node and guard < 50:
            crumbs.append({"id": node.id, "name": node.name})
            node = node.parent
            guard += 1
        crumbs.reverse()
        return Response({"breadcrumbs": [{"id": 0, "name": "根目录"}] + crumbs})


class FolderDetailView(APIView):
    """文件夹重命名 / 移动 / 改色 / 删除（级联）"""

    def get_object(self, request, pk):
        return Folder.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        folder = self.get_object(request, pk)
        if not folder:
            return Response({"message": "文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
        if "name" in request.data:
            folder.name = sanitize_filename(str(request.data["name"] or "").strip(), fallback="") or folder.name
        if "color" in request.data:
            folder.color = request.data["color"]
        if "parent" in request.data:
            new_parent_id = request.data.get("parent")
            if new_parent_id in (None, "", "null", "0"):
                folder.parent = None
            else:
                try:
                    new_parent_id = as_int(new_parent_id, field="parent")
                except ValidationError:
                    return Response({"message": "parent 必须是整数"}, status=status.HTTP_400_BAD_REQUEST)
                new_parent = Folder.objects.filter(pk=new_parent_id, owner=request.user).first()
                if not new_parent:
                    return Response({"message": "目标文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
                if new_parent.pk == folder.pk:
                    return Response({"message": "不能移动到自身"}, status=status.HTTP_400_BAD_REQUEST)
                # 环检测：不能移动到自己的子孙目录下
                if _would_create_cycle(folder, new_parent):
                    return Response({"message": "不能移动到自身的子文件夹下"}, status=status.HTTP_400_BAD_REQUEST)
                folder.parent = new_parent
        folder.save()
        return Response(FolderSerializer(folder).data)

    def delete(self, request, pk):
        folder = self.get_object(request, pk)
        if not folder:
            return Response({"message": "文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
        # #26：删除文件夹时其中的文件必须进回收站，而不是被 CASCADE 硬删
        # （FileMeta.folder 是 on_delete=CASCADE，直接 folder.delete() 会把
        # 元数据连同物理文件引用一起抹掉，物理文件变孤儿）。
        # 先收集整棵子树（防历史脏数据成环），把文件软删并解绑 folder，
        # 再删除文件夹本身，回收站里仍能看到并还原。
        subtree_ids, stack, guard = [], [folder], 0
        while stack and guard < 5000:
            node = stack.pop()
            if node.pk in subtree_ids:
                continue
            subtree_ids.append(node.pk)
            stack.extend(list(node.children.all()))
            guard += 1
        affected = FileMeta.objects.filter(folder_id__in=subtree_ids)
        now = timezone.now()
        with transaction.atomic():
            # 首次删除：记录删除时间与原目录；已在回收站的保持原状
            affected.filter(is_deleted=False).update(
                is_deleted=True, deleted_at=now, origin_folder_id=F("folder_id"),
            )
            # 解绑目录引用，避免随文件夹级联删除
            affected.update(folder=None)
            folder.delete()
        return Response({"message": "文件夹已删除"})


class FolderDownloadView(APIView):
    """S24-212：整包下载文件夹（保留相对路径，限 200 文件 / 200MB）"""

    MAX_FILES = 200
    MAX_TOTAL_BYTES = 200 * 1024 * 1024
    MAX_DEPTH = 20
    SPOOL_MAX = 8 * 1024 * 1024

    def get(self, request, pk):
        folder = Folder.objects.filter(pk=pk, owner=request.user).first()
        if not folder:
            return Response({"message": "文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
        # 收集整棵子树（防历史脏数据成环/超深）
        subtree, visited, stack, guard = [], set(), [(folder, 0)], 0
        while stack and guard < 5000:
            node, depth = stack.pop()
            if node.pk in visited or depth > self.MAX_DEPTH:
                continue
            visited.add(node.pk)
            subtree.append(node)
            stack.extend([(c, depth + 1) for c in node.children.all()])
            guard += 1
        files = list(
            FileMeta.objects.filter(
                owner=request.user, is_deleted=False, folder_id__in=list(visited),
            ).select_related("folder").order_by("folder_id", "name")
        )
        if not files:
            return Response({"message": "文件夹内没有可下载的文件"}, status=status.HTTP_400_BAD_REQUEST)
        if len(files) > self.MAX_FILES:
            return Response(
                {"message": f"文件夹内文件过多（{len(files)} 个），请分批下载"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        total_size = sum(fm.size or 0 for fm in files)
        if total_size > self.MAX_TOTAL_BYTES:
            return Response(
                {"message": f"文件夹总大小 {format_size(total_size)} 超过 "
                            f"{format_size(self.MAX_TOTAL_BYTES)} 上限"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 目录名 → 相对路径分段（相对被下载文件夹，含自身名称）
        by_id = {f.pk: f for f in subtree}

        def _parts(node):
            parts, guard_n = [], 0
            while node is not None and guard_n < 60:
                parts.append(sanitize_filename(node.name, fallback=f"folder{node.pk}"))
                if node.pk == folder.pk:
                    break
                node = by_id.get(node.parent_id) or node.parent
                guard_n += 1
            parts.reverse()
            return parts

        folder_parts = {fid: _parts(node) for fid, node in by_id.items()}
        root_parts = _parts(folder)
        buf = tempfile.SpooledTemporaryFile(max_size=self.SPOOL_MAX, mode="w+b")
        used, added = set(), 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fm in files:
                abs_path = _safe_join(MEDIA, fm.storage_path)
                if not os.path.exists(abs_path):
                    continue
                parts = folder_parts.get(fm.folder_id) or root_parts
                arc = "/".join(parts + [sanitize_filename(fm.name, fallback=f"file{fm.id}")])
                k = 1
                while arc in used:
                    base, ext = os.path.splitext(arc)
                    arc = f"{base}({k}){ext}"
                    k += 1
                used.add(arc)
                zf.write(abs_path, arc)
                added += 1
        if not added:
            buf.close()
            return Response({"message": "文件内容缺失，无法打包"}, status=status.HTTP_404_NOT_FOUND)
        buf.seek(0)
        filename = f"{sanitize_filename(folder.name, fallback='folder')}.zip"
        return FileResponse(buf, as_attachment=True, filename=filename,
                            content_type="application/zip")


class EmptyFolderListView(APIView):
    """S24-218：列出既无文件也无子目录的空文件夹"""

    def get(self, request):
        folders = list(Folder.objects.filter(owner=request.user).only("id", "name", "parent_id"))
        parents = {f.parent_id for f in folders if f.parent_id}
        with_files = set(
            FileMeta.objects.filter(owner=request.user, folder__isnull=False)
            .values_list("folder_id", flat=True).distinct()
        )
        empty = [
            {"id": f.id, "name": f.name, "parent": f.parent_id}
            for f in folders if f.id not in with_files and f.id not in parents
        ]
        return Response({"list": empty, "total": len(empty)})


class EmptyFolderCleanupView(APIView):
    """S24-218：批量删除空文件夹（删除前再次校验仍为空）"""

    def post(self, request):
        raw = request.data.get("folder_ids")
        if raw in (None, "", []):
            folders = list(Folder.objects.filter(owner=request.user))
        else:
            ids = _as_id_list(raw, field="folder_ids")
            if ids is None:
                return Response({"message": "folder_ids 必须是整数数组"}, status=400)
            folders = list(Folder.objects.filter(owner=request.user, id__in=ids))
        deleted, skipped = [], []
        with transaction.atomic():
            for folder in folders:
                empty = (
                    not FileMeta.objects.filter(folder=folder).exists()
                    and not folder.children.exists()
                )
                if not empty:
                    skipped.append({"id": folder.id, "name": folder.name, "reason": "目录非空"})
                    continue
                deleted.append({"id": folder.id, "name": folder.name})
                folder.delete()
        return Response({
            "message": f"已删除 {len(deleted)} 个空文件夹",
            "deleted": len(deleted), "list": deleted, "skipped": skipped,
        })


# ============ 文件 ============

class FileListView(APIView):
    """文件列表（当前文件夹/根目录），支持搜索、类型筛选、收藏筛选、多维排序"""

    def get(self, request):
        keyword = request.query_params.get("keyword")
        folder_id = request.query_params.get("folder")
        qs = _file_qs(request.user).filter(is_deleted=False)
        if folder_id in (None, "", "null", "0"):
            qs = qs.filter(folder__isnull=True)
        else:
            try:
                qs = qs.filter(folder_id=int(folder_id))
            except (TypeError, ValueError):
                return Response({"message": "folder 必须是整数"}, status=400)
        if keyword:
            qs = qs.filter(Q(name__icontains=keyword) | Q(sha1__icontains=keyword) | Q(description__icontains=keyword))
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        if request.query_params.get("star") == "1":
            qs = qs.filter(is_star=True)
        ext = request.query_params.get("ext")
        if ext:
            qs = qs.filter(ext__iexact=ext)
        tag = request.query_params.get("tag")
        if tag:
            qs = qs.filter(tags__name=tag).distinct()
        group = request.query_params.get("group")
        if group is not None and group != "" :
            qs = qs.filter(favorite_group=group)
        sort = request.query_params.get("sort", "-created_at")
        allowed = {
            "name", "-name", "size", "-size", "created_at", "-created_at",
            "updated_at", "-updated_at", "kind", "-kind",
        }
        qs = qs.order_by("-is_star", sort if sort in allowed else "-created_at")
        # B6：folder_name 走 folder FK、tag_names/tag_ids 走 m2m，
        # 预取后每文件 0 次附加查询（原来 3 次/文件）
        qs = qs.select_related("folder", "owner").prefetch_related("tags")
        # B11：可选分页——不带 page 参数时响应结构与原来完全一致
        pg = OptionalPageNumberPagination()
        page = pg.paginate_queryset(qs, request)
        if page is not None:
            return pg.get_paginated_response(FileMetaSerializer(page, many=True).data)
        # 未分页时硬上限 1000 条，防止一次序列化整目录
        total = qs.count()
        rows = list(qs[:1000])
        data = FileMetaSerializer(rows, many=True).data
        return Response({"list": data, "total": total, "truncated": total > len(rows)})


class FileSearchView(APIView):
    """全盘文件搜索（不限目录），可限定类型"""

    def get(self, request):
        keyword = (request.query_params.get("q") or "").strip()
        if not keyword:
            return Response({"list": [], "total": 0})
        qs = _file_qs(request.user).filter(is_deleted=False).filter(
            Q(name__icontains=keyword) | Q(description__icontains=keyword)
        )
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        qs = qs[:100]
        # B6：同 FileListView，预取 folder/tags
        qs = qs.select_related("folder", "owner").prefetch_related("tags")
        return Response({"list": FileMetaSerializer(qs, many=True).data, "total": qs.count()})


def _make_thumbnail(src_path, ext):
    """生成图片缩略图，返回相对路径或空"""
    try:
        from PIL import Image
        if ext not in ("jpg", "jpeg", "png", "webp", "bmp"):
            return ""
        img = Image.open(src_path)
        img.thumbnail((400, 400))
        thumb_rel = os.path.join("thumbnails", f"{uuid.uuid4().hex}.jpg")
        thumb_abs = _safe_join(MEDIA, thumb_rel)
        os.makedirs(os.path.dirname(thumb_abs), exist_ok=True)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        img.save(thumb_abs, "JPEG", quality=80)
        return thumb_rel
    except Exception:
        return ""


class UploadInitView(APIView):
    """初始化分片上传；若 sha1 已存在 → 秒传直接返回已有文件；返回已上传分片用于断点续传"""

    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        ser = ChunkInitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        if data.get("sha1"):
            exist = FileMeta.objects.filter(
                owner=request.user, is_deleted=False, sha1=data["sha1"], size=data["file_size"]
            ).first()
            if exist:
                return Response({"sec_pass": True, "file": FileMetaSerializer(exist).data})

        if data["file_size"] > settings.FILE_MAX_SIZE_MB * 1024 * 1024:
            return Response({"message": f"文件超过大小限制 {settings.FILE_MAX_SIZE_MB}MB"}, status=status.HTTP_400_BAD_REQUEST)

        # B8：配额校验（初始化）——秒传不新增容量故不拦；超限直接拒，避免无效流量
        blocked = check_quota(request.user, data["file_size"])
        if blocked:
            return Response({"code": blocked[0], "message": blocked[1]}, status=status.HTTP_400_BAD_REQUEST)

        chunk = ChunkUpload.objects.create(
            user=request.user,
            filename=data["filename"],
            folder_id=data.get("folder_id"),
            file_size=data["file_size"],
            chunk_size=data["chunk_size"],
            total_chunks=data["total_chunks"],
            sha1=data.get("sha1", ""),
            temp_dir=os.path.join("_chunks", str(uuid.uuid4().hex)),
        )
        os.makedirs(_safe_join(MEDIA, chunk.temp_dir), exist_ok=True)
        return Response({"sec_pass": False, "upload_id": str(chunk.upload_id), "uploaded": chunk.uploaded_chunks})


class UploadStatusView(APIView):
    """查询分片上传进度（断点续传恢复）"""

    def get(self, request):
        upload_id = _parse_uuid(request.query_params.get("upload_id"))
        if upload_id is None:
            return Response({"message": "upload_id 格式非法"}, status=status.HTTP_400_BAD_REQUEST)
        chunk = ChunkUpload.objects.filter(upload_id=upload_id, user=request.user).first()
        if not chunk:
            return Response({"message": "上传任务不存在"}, status=404)
        return Response({
            "upload_id": str(chunk.upload_id), "filename": chunk.filename,
            "uploaded": chunk.uploaded_chunks, "total_chunks": chunk.total_chunks,
            "status": chunk.status,
        })


class UploadAbortView(APIView):
    """取消分片上传并清理临时分片"""

    def post(self, request):
        upload_id = _parse_uuid(request.data.get("upload_id"))
        if upload_id is None:
            return Response({"message": "upload_id 格式非法"}, status=status.HTTP_400_BAD_REQUEST)
        chunk = ChunkUpload.objects.filter(upload_id=upload_id, user=request.user, status="uploading").first()
        if not chunk:
            return Response({"message": "上传任务不存在"}, status=404)
        shutil.rmtree(_safe_join(MEDIA, chunk.temp_dir), ignore_errors=True)
        chunk.status = "aborted"
        chunk.save(update_fields=["status"])
        return Response({"message": "已取消上传"})


class UploadChunkView(APIView):
    """上传单个分片（支持断点续传：重复分片直接确认）"""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload_id = _parse_uuid(request.data.get("upload_id"))
        if upload_id is None:
            return Response({"message": "upload_id 格式非法"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            index = int(request.data.get("index", -1))
        except (TypeError, ValueError):
            return Response({"message": "index 必须是整数"}, status=status.HTTP_400_BAD_REQUEST)
        chunk_file = request.FILES.get("chunk")
        if not chunk_file:
            return Response({"message": "缺少分片内容"}, status=status.HTTP_400_BAD_REQUEST)
        # #74：uploaded_chunks 是 JSON 列表，读-改-写必须串行化。原先并发上传
        # 不同分片时后写覆盖先写，断点续传列表丢索引；这里锁住上传行，
        # 在锁内重新读取列表后再追加（不新增表）。
        with transaction.atomic():
            chunk = (ChunkUpload.objects.select_for_update()
                     .filter(upload_id=upload_id, user=request.user).first())
            if not chunk:
                return Response({"message": "上传任务不存在"}, status=status.HTTP_404_NOT_FOUND)
            if index < 0 or index >= chunk.total_chunks:
                return Response({"message": "分块索引非法"}, status=status.HTTP_400_BAD_REQUEST)
            uploaded = list(chunk.uploaded_chunks or [])
            if index in uploaded:
                return Response({"uploaded": uploaded, "message": "该分片已上传"})
            # 分片不能大于声明的 chunk_size：否则可以借 5MB 声明写入任意大文件，
            # 绕过 file_size 校验与配额
            if chunk_file.size > chunk.chunk_size:
                return Response(
                    {"message": f"分片体积 {chunk_file.size} 超过声明上限 {chunk.chunk_size}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            part_path = _safe_join(MEDIA, chunk.temp_dir, f"part_{index:06d}")
            with open(part_path, "wb+") as f:
                for buf in chunk_file.chunks():
                    f.write(buf)
            uploaded.append(index)
            uploaded.sort()
            chunk.uploaded_chunks = uploaded
            chunk.save(update_fields=["uploaded_chunks", "updated_at"])
        return Response({"uploaded": uploaded})


class UploadCompleteView(APIView):
    """合并分片 → 生成 FileMeta → 清理临时文件"""

    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        upload_id = _parse_uuid(request.data.get("upload_id"))
        if upload_id is None:
            return Response({"message": "upload_id 格式非法"}, status=status.HTTP_400_BAD_REQUEST)
        chunk = ChunkUpload.objects.filter(upload_id=upload_id, user=request.user).first()
        if not chunk:
            return Response({"message": "上传任务不存在"}, status=status.HTTP_404_NOT_FOUND)
        if chunk.status == "completed":
            return Response({"message": "任务已完成"})

        missing = [i for i in range(chunk.total_chunks) if i not in chunk.uploaded_chunks]
        if missing:
            return Response(
                {"message": f"缺少分片 {missing[:10]}", "uploaded": chunk.uploaded_chunks},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # B8：配额双校验（完成）——挡住绕过初始化直接调 complete 的路径；
        # 秒传命中（exist）不会新增容量，此处只需按本任务大小兜底
        blocked = check_quota(request.user, chunk.file_size)
        if blocked:
            return Response({"code": blocked[0], "message": blocked[1]}, status=status.HTTP_400_BAD_REQUEST)

        # S24-216：同名处理策略 rename（默认，自动改名）/ skip（跳过）/ overwrite（覆盖）
        on_conflict = str(request.data.get("on_conflict") or "rename").strip()
        if on_conflict not in ("rename", "skip", "overwrite"):
            return Response({"message": "on_conflict 只能是 rename / skip / overwrite"},
                            status=status.HTTP_400_BAD_REQUEST)

        year_month = timezone.now().strftime("%Y%m")
        rel_dir = os.path.join("files", str(chunk.user_id), year_month)
        abs_dir = _safe_join(MEDIA, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        folder = Folder.objects.filter(pk=chunk.folder_id, owner=request.user).first() if chunk.folder_id else None
        base, ext = os.path.splitext(chunk.filename)
        final_rel = os.path.join(rel_dir, chunk.filename)

        def _name_taken(rel):
            """F557 重名判定：磁盘已存在 或 同目录下已有同名 FileMeta"""
            if os.path.exists(_safe_join(MEDIA, rel)):
                return True
            return FileMeta.objects.filter(
                owner=request.user, folder=folder, is_deleted=False,
                name=os.path.basename(rel),
            ).exists()

        def _finish_chunk():
            """任务置完成并在提交后清理临时分片"""
            with transaction.atomic():
                chunk.status = "completed"
                chunk.save(update_fields=["status", "updated_at"])
            transaction.on_commit(
                lambda: shutil.rmtree(_safe_join(MEDIA, chunk.temp_dir), ignore_errors=True)
            )

        merge_rel = final_rel
        overwrite_target = None
        if _name_taken(final_rel):
            if on_conflict == "skip":
                _finish_chunk()
                return Response({
                    "message": "已跳过同名文件", "skipped": [{"name": chunk.filename}],
                    "count": 0,
                })
            if on_conflict == "overwrite":
                overwrite_target = FileMeta.objects.filter(
                    owner=request.user, folder=folder, is_deleted=False, name=chunk.filename,
                ).first()
            if overwrite_target is not None:
                # 覆盖时写独立物理路径，避免与秒传/复制共享的旧文件互相污染
                merge_rel = os.path.join(rel_dir, f"{uuid.uuid4().hex}{ext}").replace("\\", "/")
            else:
                i = 1
                while _name_taken(merge_rel):
                    merge_rel = os.path.join(rel_dir, f"{base}({i}){ext}")
                    i += 1
                merge_rel = merge_rel.replace("\\", "/")
        else:
            merge_rel = final_rel.replace("\\", "/")
        merge_abs = _safe_join(MEDIA, merge_rel)

        used_before = used_bytes(request.user)
        with open(merge_abs, "wb") as out:
            for idx in range(chunk.total_chunks):
                part = _safe_join(MEDIA, chunk.temp_dir, f"part_{idx:06d}")
                with open(part, "rb") as p:
                    shutil.copyfileobj(p, out, 1024 * 1024)

        # 以真实落盘大小为准：声明值与实际值不符说明分片被截断/替换过，整单拒绝
        actual_size = os.path.getsize(merge_abs)
        if actual_size != chunk.file_size:
            try:
                os.remove(merge_abs)
            except OSError:
                pass
            return Response(
                {"message": f"文件大小校验失败：声明 {chunk.file_size} 字节，实际 {actual_size} 字节"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # #25：sha1 一律以真实落盘内容重新计算，客户端声明值只用于初始化阶段的
        # 秒传提示，不能参与这里的秒传匹配——否则可以指向他人物理文件，
        # 造成「名称/内容错配」并可能在清理时误删他人文件
        sha1 = sha1_file(merge_abs)
        ext = os.path.splitext(chunk.filename)[1].lower().lstrip(".")

        if overwrite_target is not None:
            # S24-216：覆盖同名文件——先留历史版本，再换物理文件并刷新 size/sha1
            target = overwrite_target
            old_rel = target.storage_path
            versioning.snapshot(target, request.user)
            thumb_rel = _make_thumbnail(merge_abs, ext) if file_kind(chunk.filename) == "image" else ""
            with transaction.atomic():
                target.storage_path = merge_rel
                target.size = actual_size
                target.sha1 = sha1
                target.kind = file_kind(chunk.filename)
                target.ext = ext
                if thumb_rel:
                    target.thumbnail_path = thumb_rel
                target.save(update_fields=[
                    "storage_path", "size", "sha1", "kind", "ext", "thumbnail_path", "updated_at",
                ])
                chunk.status = "completed"
                chunk.save(update_fields=["status", "updated_at"])
                _log_op(request.user, target, "upload", detail="覆盖同名文件",
                        to_folder=_folder_label(folder))

            def _purge_old(rel=old_rel):
                try:
                    if not rel or FileMeta.objects.filter(storage_path=rel).exists():
                        return
                    path = _safe_join(MEDIA, rel)
                    if os.path.exists(path):
                        os.remove(path)
                except (OSError, ValueError):
                    logger.warning("S24：覆盖后旧物理文件清理失败 path=%s", rel)

            transaction.on_commit(_purge_old)
            transaction.on_commit(
                lambda: shutil.rmtree(_safe_join(MEDIA, chunk.temp_dir), ignore_errors=True)
            )
            transaction.on_commit(lambda: _index_file(target))
            _push_file_event(request.user.id, "updated", file_id=target.id, name=target.name)
            _notify_quota_cross(request.user, used_before, used_bytes(request.user))
            return Response({
                "message": "上传完成（已覆盖同名文件）",
                "file": FileMetaSerializer(target).data,
                "overwritten": True,
            })

        storage_rel = merge_rel
        # #75：秒传命中时保留用户上传的原始文件名（同名时是加过序号的最终名），
        # 只复用已有物理文件的 storage_path/sha1，不再拿物理文件名回写
        display_name = os.path.basename(merge_rel)
        exist = FileMeta.objects.filter(
            owner=request.user, sha1=sha1, size=actual_size, is_deleted=False
        ).exclude(storage_path=storage_rel).first()
        if exist:
            os.remove(merge_abs)
            storage_rel = exist.storage_path
            sha1 = exist.sha1

        thumb_rel = ""
        if file_kind(chunk.filename) == "image":
            thumb_rel = _make_thumbnail(_safe_join(MEDIA, storage_rel), ext)

        # B5：FileMeta 建档 + 任务状态置完成 + 操作流水入同一事务；
        # 临时分片目录的物理清理放 on_commit，提交后才删，避免「库回滚了、
        # 临时文件没了」导致分片无法重传
        with transaction.atomic():
            fm = FileMeta.objects.create(
                name=display_name,
                folder=folder,
                owner=request.user,
                storage_path=storage_rel,
                size=actual_size,
                sha1=sha1,
                kind=file_kind(chunk.filename),
                ext=ext,
                thumbnail_path=thumb_rel,
            )
            chunk.status = "completed"
            chunk.save(update_fields=["status", "updated_at"])
            _log_op(request.user, fm, "upload", detail="分片上传完成",
                    to_folder=_folder_label(folder))
        transaction.on_commit(
            lambda: shutil.rmtree(_safe_join(MEDIA, chunk.temp_dir), ignore_errors=True)
        )
        transaction.on_commit(lambda: _index_file(fm))
        # S2-B1：上传完成广播（多标签页/多端同步文件列表）
        _push_file_event(request.user.id, "uploaded", file_id=fm.id, name=fm.name)
        # S24-234：越过 80%/90% 配额阈值时提醒一次
        _notify_quota_cross(request.user, used_before, used_bytes(request.user))
        payload = {"message": "上传完成", "file": FileMetaSerializer(fm).data}
        # F557 重名自动改名：把最终名称回传给前端提示
        if fm.name != chunk.filename:
            payload["renamed"] = {"original": chunk.filename, "final": fm.name}
        return Response(payload)


class FileDetailView(APIView):
    """文件重命名 / 移动 / 收藏 / 备注 / 删除（进回收站，记录原目录）

    可见性与可写性分离：读取按「数据范围」放行（管理员可查看全部），
    改名/移动/删除等写操作仍要求本人是所有者。
    """

    def get_object(self, request, pk):
        return FileMeta.objects.filter(pk=pk, owner=request.user).first()

    def get_read_object(self, request, pk):
        return _get_file(request.user, pk, include_deleted=True)

    def get(self, request, pk):
        fm = self.get_read_object(request, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=404)
        return Response(FileMetaSerializer(fm).data)

    def patch(self, request, pk):
        fm = self.get_object(request, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        fields = []
        from_folder_old = _folder_label(fm.folder)
        new_name = fm.name
        new_folder = fm.folder
        if "name" in request.data:
            new_name = sanitize_filename(str(request.data["name"] or "").strip(), fallback="", max_length=255)
            if not new_name:
                return Response({"message": "文件名不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        if "folder" in request.data:
            new_folder_id = request.data.get("folder")
            if new_folder_id in (None, "", "null"):
                new_folder = None
            else:
                try:
                    new_folder_id = as_int(new_folder_id, field="folder", minimum=1)
                except ValidationError:
                    return Response({"message": "folder 必须是整数"}, status=status.HTTP_400_BAD_REQUEST)
                new_folder = Folder.objects.filter(pk=new_folder_id, owner=request.user).first()
                if not new_folder:
                    return Response({"message": "目标文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
        # #76：重命名/移动都要求「同目录不重名」，否则后续按名字查找/覆盖会取错文件
        folder_changed = (new_folder.pk if new_folder else None) != fm.folder_id
        if (new_name != fm.name or folder_changed) and FileMeta.objects.filter(
            owner=request.user, folder=new_folder, is_deleted=False, name=new_name,
        ).exclude(pk=fm.pk).exists():
            return Response(
                {"message": "同目录下已存在同名文件", "code": "NAME_CONFLICT"},
                status=status.HTTP_409_CONFLICT,
            )
        if "name" in request.data:
            old_name = fm.name
            fm.name = new_name
            fields.append("name")
            if old_name != new_name:
                _log_op(request.user, fm, "rename", detail=f"{old_name} → {new_name}",
                        from_folder=from_folder_old, to_folder=from_folder_old)
        if "folder" in request.data:
            fm.folder = new_folder
            fields.append("folder")
            _log_op(request.user, fm, "move", from_folder=from_folder_old,
                    to_folder=_folder_label(fm.folder))
        if "is_star" in request.data:
            fm.is_star = parse_bool(request.data["is_star"], field="is_star")
            fields.append("is_star")
        if "description" in request.data:
            fm.description = str(request.data["description"] or "")[:500]
            fields.append("description")
        if fields:
            fields.append("updated_at")
            fm.save(update_fields=fields)
        # S2-B1：重命名/移动/星标变更广播
        _push_file_event(request.user.id, "updated", file_id=fm.id, name=fm.name)
        return Response(FileMetaSerializer(fm).data)

    def delete(self, request, pk):
        fm = self.get_object(request, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        # #52：仅在首次删除时记录「删除前目录」；重复删除保持原值，
        # 否则会把恢复目录覆盖成回收站时所在目录（与批量路径 #77 同口径）
        if not fm.is_deleted:
            fm.is_deleted = True
            fm.deleted_at = timezone.now()
            fm.origin_folder_id = fm.folder_id
            fm.save(update_fields=["is_deleted", "deleted_at", "origin_folder_id"])
        # S2-B1：删除广播（移入回收站）
        _push_file_event(request.user.id, "deleted", file_id=fm.id)
        return Response({"message": "已移入回收站"})


class FileStarView(APIView):
    """切换收藏状态"""

    def post(self, request, pk):
        fm = FileMeta.objects.filter(pk=pk, owner=request.user).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=404)
        fm.is_star = not fm.is_star
        fm.save(update_fields=["is_star"])
        return Response({"message": "已收藏" if fm.is_star else "已取消收藏", "is_star": fm.is_star})


class FileBatchView(APIView):
    """批量操作：move / copy / group / trash / restore / star / unstar / delete_forever"""

    def post(self, request):
        action = request.data.get("action")
        ids = _as_id_list(request.data.get("file_ids"))
        if ids is None:
            return Response({"message": "file_ids 必须是整数数组"}, status=400)
        if not ids:
            return Response({"message": "未选择文件"}, status=400)
        qs = FileMeta.objects.filter(owner=request.user, id__in=ids)
        if action == "trash":
            # #77：只处理尚未删除的文件；已在回收站的保持 origin_folder/deleted_at，
            # 否则再次删除会把「删除前目录」覆盖成回收站时所在的目录
            targets = [fm for fm in qs if not fm.is_deleted]
            if targets:
                now = timezone.now()
                for fm in targets:
                    fm.is_deleted = True
                    fm.deleted_at = now
                    fm.origin_folder_id = fm.folder_id
                FileMeta.objects.bulk_update(
                    targets, ["is_deleted", "deleted_at", "origin_folder_id"], batch_size=500
                )
            return Response({"message": f"已将 {len(targets)} 个文件移入回收站"})
        if action == "restore":
            # S24-211：批量恢复，复用回收站的「回原目录 + 同名自动改名」逻辑
            targets = list(FileMeta.objects.filter(
                owner=request.user, is_deleted=True, id__in=ids,
            ).select_related("folder"))
            if not targets:
                return Response({"message": "没有可恢复的文件"}, status=400)
            with transaction.atomic():
                restored, renamed = _restore_files(request.user, targets)
            payload = {"message": f"已恢复 {restored} 个文件", "restored": restored, "renamed": renamed}
            if renamed:
                payload["message"] = f"已恢复 {restored} 个文件，其中 {renamed} 个已改名"
            return Response(payload)
        if action == "move":
            folder = _owner_folder(request.user, request.data.get("folder"))
            if request.data.get("folder") not in (None, "", "null", "0", 0) and not folder:
                return Response({"message": "目标文件夹不存在"}, status=404)
            on_conflict = str(request.data.get("on_conflict") or "").strip()
            if on_conflict not in ("skip", "rename"):
                on_conflict = ""
            targets = list(qs.select_related("folder"))
            try:
                dry_run = parse_bool(request.data.get("dry_run"), field="dry_run")
            except ValidationError:
                return Response({"message": "dry_run 必须是布尔值"}, status=400)
            folder_id = folder.pk if folder else None
            # S24-215：同目录重名预检（排除本次选中的文件，已在该目录的文件不算冲突）
            taken_names = set(
                FileMeta.objects.filter(owner=request.user, folder=folder, is_deleted=False)
                .exclude(id__in=ids).values_list("name", flat=True)
            )
            conflicts = [
                {"id": fm.id, "name": fm.name, "reason": "目标文件夹已存在同名文件"}
                for fm in targets if fm.folder_id != folder_id and fm.name in taken_names
            ]
            if dry_run:
                return Response({
                    "dry_run": True,
                    "target": {"id": folder_id or 0, "name": _folder_label(folder)},
                    "total": len(targets),
                    "ok_count": len(targets) - len(conflicts),
                    "conflict_count": len(conflicts),
                    "conflicts": conflicts,
                })
            # #54：整段移动收进单事务，元数据用 bulk_update 收敛写次数
            with transaction.atomic():
                now = timezone.now()
                moves, skipped, renamed = [], [], 0
                moving = []
                for fm in targets:
                    conflict = fm.folder_id != folder_id and fm.name in taken_names
                    if conflict and on_conflict == "skip":
                        skipped.append({"id": fm.id, "name": fm.name})
                        continue
                    if conflict and on_conflict == "rename":
                        base, ext = os.path.splitext(fm.name)
                        i = 1
                        candidate = f"{base}({i}){ext}"
                        while candidate in taken_names:
                            i += 1
                            candidate = f"{base}({i}){ext}"
                        fm.name = candidate
                        taken_names.add(candidate)
                        renamed += 1
                    moves.append((fm, _folder_label(fm.folder)))
                    fm.folder = folder
                    fm.updated_at = now
                    moving.append(fm)
                if moving:
                    FileMeta.objects.bulk_update(moving, ["folder", "name", "updated_at"], batch_size=500)
                for fm, src in moves:
                    _log_op(request.user, fm, "move", from_folder=src, to_folder=_folder_label(folder))
            payload = {
                "message": f"已移动 {len(moving)} 个文件",
                "moved": len(moving), "skipped": skipped, "renamed": renamed,
                "conflict_count": len(conflicts), "target": {"id": folder_id or 0, "name": _folder_label(folder)},
            }
            if skipped:
                payload["message"] = f"已移动 {len(moving)} 个文件，跳过 {len(skipped)} 个同名文件"
            elif renamed:
                payload["message"] = f"已移动 {len(moving)} 个文件，其中 {renamed} 个已改名"
            return Response(payload)
        if action == "copy":
            # S24-228：批量复制到目标目录（逐文件物理副本 + 操作流水）
            folder = _owner_folder(request.user, request.data.get("folder"))
            if request.data.get("folder") not in (None, "", "null", "0", 0) and not folder:
                return Response({"message": "目标文件夹不存在"}, status=404)
            targets = list(qs.filter(is_deleted=False).select_related("folder"))
            if not targets:
                return Response({"message": "没有可复制的文件"}, status=400)
            rel_dir = os.path.join("files", str(request.user.id), timezone.now().strftime("%Y%m"))
            os.makedirs(_safe_join(MEDIA, rel_dir), exist_ok=True)
            created, failed = [], []
            with transaction.atomic():
                taken_names = set(
                    FileMeta.objects.filter(owner=request.user, folder=folder, is_deleted=False)
                    .values_list("name", flat=True)
                )
                for fm in targets:
                    src_abs = _safe_join(MEDIA, fm.storage_path)
                    if not os.path.exists(src_abs):
                        failed.append({"id": fm.id, "name": fm.name, "reason": "物理文件缺失"})
                        continue
                    base, ext = os.path.splitext(fm.name)
                    new_name, i = f"{base}(副本){ext}", 2
                    while new_name in taken_names:
                        new_name = f"{base}(副本{i}){ext}"
                        i += 1
                    taken_names.add(new_name)
                    dst_rel = os.path.join(rel_dir, f"{uuid.uuid4().hex}{ext}").replace("\\", "/")
                    shutil.copy2(src_abs, _safe_join(MEDIA, dst_rel))
                    copy = FileMeta.objects.create(
                        name=new_name, folder=folder, owner=request.user, storage_path=dst_rel,
                        size=fm.size, sha1=fm.sha1, kind=fm.kind, ext=fm.ext,
                        description=fm.description,
                    )
                    created.append(copy.id)
                    _log_op(request.user, copy, "copy", detail=f"批量复制自 {fm.name}",
                            from_folder=_folder_label(fm.folder), to_folder=_folder_label(folder))
            return Response({
                "message": f"已复制 {len(created)} 个文件",
                "count": len(created), "ids": created, "failed": failed,
            })
        if action == "group":
            # S24-235：批量写入收藏分组（空值表示取消分组）
            group = str(request.data.get("group") or "").strip()[:50]
            n = qs.update(favorite_group=group)
            word = f"已归入分组「{group}」" if group else "已取消分组"
            return Response({"message": f"{word}（{n} 个文件）", "group": group, "count": n})
        if action == "star":
            n = qs.update(is_star=True)
            return Response({"message": f"已收藏 {n} 个文件"})
        if action == "unstar":
            n = qs.update(is_star=False)
            return Response({"message": f"已取消收藏 {n} 个文件"})
        if action == "delete_forever":
            # #54/#55：元数据删除在同一事务内完成，物理文件由 _remove_physical
            # 在提交后清理；中途失败整体回滚，元数据不会丢
            targets = list(qs)
            with transaction.atomic():
                for fm in targets:
                    self._remove_physical(fm)
            return Response({"message": f"已彻底删除 {len(targets)} 个文件"})
        return Response({"message": "未知操作"}, status=400)

    @staticmethod
    def _remove_physical(fm):
        """#55：事务内先删元数据，事务提交后再删磁盘文件。

        原实现先删磁盘再删元数据：元数据删除失败会留下指向缺失文件的记录。
        磁盘文件可能被多条 FileMeta 引用（秒传/复制共享 storage_path 或缩略图），
        因此提交后仍需确认没有其它记录引用才真正删除。
        """
        storage_path = fm.storage_path
        thumbnail_path = fm.thumbnail_path
        fm.delete()

        def _purge():
            for rel, field in ((storage_path, "storage_path"), (thumbnail_path, "thumbnail_path")):
                if not rel:
                    continue
                try:
                    # 还有记录引用同一物理文件时不删，避免兄弟记录指向缺失文件
                    if FileMeta.objects.filter(**{field: rel}).exists():
                        continue
                    abs_path = _safe_join(MEDIA, rel)
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                except (OSError, ValueError):
                    logger.warning("S21：物理文件清理失败 path=%s", rel)

        transaction.on_commit(_purge)


class FileCopyView(APIView):
    """复制文件（生成副本，物理另存）"""

    def post(self, request, pk):
        fm = FileMeta.objects.filter(pk=pk, owner=request.user, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=404)
        src = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(src):
            return Response({"message": "物理文件缺失"}, status=404)
        rel_dir = os.path.dirname(fm.storage_path)
        base, ext = os.path.splitext(fm.name)
        new_name, i = f"{base}(副本){ext}", 1
        dst_rel = os.path.join(rel_dir, new_name).replace("\\", "/")
        while os.path.exists(_safe_join(MEDIA, dst_rel)):
            new_name = f"{base}(副本{i}){ext}"
            dst_rel = os.path.join(rel_dir, new_name).replace("\\", "/")
            i += 1
        shutil.copy2(src, _safe_join(MEDIA, dst_rel))
        copy = FileMeta.objects.create(
            name=new_name, folder=fm.folder, owner=request.user, storage_path=dst_rel,
            size=fm.size, sha1=fm.sha1, kind=fm.kind, ext=fm.ext, thumbnail_path=fm.thumbnail_path,
            description=fm.description,
        )
        _log_op(request.user, copy, "copy", detail=f"复制自 {fm.name}",
                from_folder=_folder_label(fm.folder), to_folder=_folder_label(fm.folder))
        return Response(FileMetaSerializer(copy).data, status=201)


class FileToNoteView(APIView):
    """S24-224：把文本文件沉淀为笔记（≤200KB，source=import，标题取文件名）"""

    MAX_BYTES = 200 * 1024

    def post(self, request, pk):
        fm = FileMeta.objects.filter(pk=pk, owner=request.user, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        if fm.preview_type != "text":
            return Response({"message": "仅文本类文件可转为笔记", "code": "NOT_TEXT"},
                            status=status.HTTP_400_BAD_REQUEST)
        if fm.size > self.MAX_BYTES:
            return Response({"message": "文件超过 200KB，不支持转为笔记"}, status=status.HTTP_400_BAD_REQUEST)
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.isfile(abs_path):
            return Response({"message": "物理文件缺失"}, status=status.HTTP_404_NOT_FOUND)
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(self.MAX_BYTES)
        except OSError:
            return Response({"message": "文件读取失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        from notes.models import Note

        try:
            from notes.views import count_words
        except Exception:  # 计数失败不影响主流程
            count_words = None
        words = count_words(content) if count_words else len(content)
        note = Note.objects.create(
            title=fm.name[:200], content=content, owner=request.user,
            words=words or 0, source="import",
        )
        return Response({
            "message": "已转为笔记",
            "note_id": note.id, "title": note.title, "words": note.words,
        }, status=status.HTTP_201_CREATED)


class FileCreateTextView(APIView):
    """在线新建文本文件"""

    def post(self, request):
        name = sanitize_filename(str(request.data.get("name") or "新建文本.txt").strip(),
                                 fallback="新建文本.txt", max_length=255)
        if "." not in name:
            name += ".txt"
        content = request.data.get("content", "")
        folder = _owner_folder(request.user, request.data.get("folder"))
        ym = timezone.now().strftime("%Y%m")
        rel_dir = os.path.join("files", str(request.user.id), ym)
        os.makedirs(_safe_join(MEDIA, rel_dir), exist_ok=True)
        base, ext = os.path.splitext(name)
        rel = os.path.join(rel_dir, name).replace("\\", "/")
        i = 1
        # F557 重名自动改名：磁盘 + 同目录 FileMeta 双重判定
        while os.path.exists(_safe_join(MEDIA, rel)) or FileMeta.objects.filter(
                owner=request.user, folder=folder, is_deleted=False, name=os.path.basename(rel)).exists():
            rel = os.path.join(rel_dir, f"{base}({i}){ext}").replace("\\", "/")
            i += 1
        data = content.encode("utf-8")
        with open(_safe_join(MEDIA, rel), "wb") as f:
            f.write(data)
        import hashlib
        fm = FileMeta.objects.create(
            name=os.path.basename(rel), folder=folder, owner=request.user, storage_path=rel,
            size=len(data), sha1=hashlib.sha1(data).hexdigest(), kind="text",
            ext=os.path.splitext(rel)[1].lstrip(".").lower(),
        )
        return Response(FileMetaSerializer(fm).data, status=201)


class FileSaveTextView(APIView):
    """在线保存文本文件（写回物理文件并刷新大小/哈希）"""

    def post(self, request, pk):
        fm = FileMeta.objects.filter(pk=pk, owner=request.user, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=404)
        if fm.kind not in ("text", "other"):
            return Response({"message": "仅文本文件可在线编辑"}, status=400)
        if fm.size > 256 * 1024:
            return Response({"message": "文件超过 256KB，不支持在线编辑"}, status=400)
        content = request.data.get("content", "")
        if not isinstance(content, str):
            return Response({"message": "content 必须是字符串"}, status=400)
        data = content.encode("utf-8")
        if len(data) > 2 * 1024 * 1024:
            return Response({"message": "内容超过 2MB 上限"}, status=400)
        abs_path = _safe_join(MEDIA, fm.storage_path)
        # F11：覆盖前保留历史版本（版本文件写失败不影响本次保存）
        versioning.snapshot(fm, request.user)
        with open(abs_path, "wb") as f:
            f.write(data)
        import hashlib
        fm.size = len(data)
        fm.sha1 = hashlib.sha1(data).hexdigest()
        fm.save(update_fields=["size", "sha1", "updated_at"])
        _index_file(fm)
        return Response({"message": "已保存", "file": FileMetaSerializer(fm).data})


class FileBatchDownloadView(APIView):
    """多个文件打包成 zip 下载（总量与文件数双上限）"""

    MAX_FILES = 200
    MAX_TOTAL_BYTES = 200 * 1024 * 1024  # 200MB
    # 内存内最多保留 8MB，超过自动落临时文件，避免 zip 峰值占满内存
    SPOOL_MAX = 8 * 1024 * 1024

    def post(self, request):
        ids = _as_id_list(request.data.get("file_ids"))
        if ids is None:
            return Response({"message": "file_ids 必须是整数数组"}, status=400)
        files = list(FileMeta.objects.filter(owner=request.user, id__in=ids, is_deleted=False))
        if not files:
            return Response({"message": "没有可下载的文件"}, status=400)
        # #95：打包前先按元数据校验，避免 1000 个 1GB 文件把内存打满
        if len(files) > self.MAX_FILES:
            return Response(
                {"message": f"一次最多打包 {self.MAX_FILES} 个文件，当前 {len(files)} 个"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        total_size = sum(fm.size or 0 for fm in files)
        if total_size > self.MAX_TOTAL_BYTES:
            return Response(
                {"message": f"打包文件总大小 {format_size(total_size)} 超过 "
                            f"{format_size(self.MAX_TOTAL_BYTES)} 上限"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        buf = tempfile.SpooledTemporaryFile(max_size=self.SPOOL_MAX, mode="w+b")
        used = set()
        # S24-214：清单逐行记录 name / size / sha1 / folder / 导出时间
        exported_at = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
        manifest = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fm in files:
                abs_path = _safe_join(MEDIA, fm.storage_path)
                if not os.path.exists(abs_path):
                    continue
                arc = fm.name
                k = 1
                while arc in used:
                    base, ext = os.path.splitext(fm.name)
                    arc = f"{base}({k}){ext}"
                    k += 1
                used.add(arc)
                zf.write(abs_path, arc)
                manifest.append([arc, fm.size or 0, fm.sha1 or "", _folder_label(fm.folder), exported_at])
            lines = ["name\tsize\tsha1\tfolder\texported_at"]
            lines += ["\t".join(str(v) for v in row) for row in manifest]
            zf.writestr("_manifest.txt", "\n".join(lines) + "\n")
        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename="files.zip",
                            content_type="application/zip")


class FileDownloadView(APIView):
    """下载文件（记录日志与最近访问）

    权限规则（安全收口）：
    - owner：直接放行
    - 非 owner：必须带 `?share=<token>`，且该 token 必须指向**本文件**，
      并完整通过撤销/过期/密码/权限/次数上限校验。
    不能再用「存在任意一条分享链接」当作放行依据。
    """

    def get(self, request, pk):
        fm = FileMeta.objects.filter(pk=pk, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        denied = _authorize_file_bytes(request, fm, consume_download=True)
        if denied is not None:
            return denied
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(abs_path):
            return Response({"message": "物理文件缺失"}, status=status.HTTP_404_NOT_FOUND)
        if fm.owner_id == request.user.id:
            _touch_recent(request.user, fm)
        resp = FileResponse(open(abs_path, "rb"), as_attachment=True, filename=fm.name)
        return resp


class FilePreviewView(APIView):
    """文件在线预览入口。

    图片 / 视频 / 音频 / PDF 返回可直接喂给前端渲染器的 URL；
    文本类返回正文（前 256KB）；Office 返回转换状态与建议操作。
    """

    def get(self, request, pk):
        fm = _get_file(request.user, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)

        ptype = fm.preview_type
        base = {
            "id": fm.id,
            "name": fm.name,
            "ext": fm.ext,
            "kind": fm.kind,
            "size": fm.size,
            "size_text": format_size(fm.size),
            "preview_type": ptype,
            "thumbnail_url": fm.thumbnail_url,
        }

        if ptype == "none":
            _touch_recent(request.user, fm)
            return Response({**base, "previewable": False,
                             "message": "该格式暂不支持在线预览，请下载后查看"})

        if ptype == "office":
            # Office 文档：已转换好就直接给 PDF，否则给出转换入口
            ready = bool(fm.pdf_path) and os.path.exists(_safe_join(MEDIA, fm.pdf_path))
            _touch_recent(request.user, fm)
            return Response({
                **base,
                "previewable": True,
                "preview_url": f"/api/files/{fm.id}/pdf/" if ready else "",
                "pdf_status": fm.pdf_status or ("ready" if ready else "none"),
                "pdf_error": fm.pdf_error,
                "needs_convert": not ready,
                "convert_api": f"/api/files/{fm.id}/to-pdf/",
                "office_available": office.soffice_status()["available"],
                "office_hint": "" if office.soffice_status()["available"] else office.INSTALL_HINT,
            })

        if ptype == "text":
            abs_path = _safe_join(MEDIA, fm.storage_path)
            if not os.path.exists(abs_path):
                return Response({"message": "物理文件缺失"}, status=404)
            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(256 * 1024)
            except Exception:
                content = ""
            _touch_recent(request.user, fm)
            return Response({**base, "previewable": True, "content": content,
                             "truncated": fm.size > 256 * 1024,
                             "preview_url": f"/api/files/{fm.id}/raw/"})

        # image / video / audio / pdf：交给前端原生渲染器，走 /raw/ 流式接口
        _touch_recent(request.user, fm)
        return Response({
            **base,
            "previewable": True,
            "preview_url": f"/api/files/{fm.id}/raw/",
            "raw_url": f"/api/files/{fm.id}/raw/",
            "download_url": f"/api/files/{fm.id}/download/",
            "supports_range": ptype in ("video", "audio"),
        })


class FileRawView(APIView):
    """文件原样流式输出，支持 HTTP Range（视频拖动进度条的关键）。

    返回 200 全量 或 206 Partial Content，附 Accept-Ranges / Content-Range，
    浏览器 <video>/<audio>/<img> 与 PDF 内嵌阅读器可直接使用。
    """

    CHUNK = 1024 * 512  # 512KB 分片

    def get(self, request, pk):
        # #23：原文件输出与 /download/ 统一授权——非 owner（含 dept/all 数据范围）
        # 必须携带指向本文件的分享 token，不能再凭可见范围直接取原始字节
        fm = FileMeta.objects.filter(pk=pk, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        # 仅对可预览类型开放内联，其他类型强制下载，避免把可执行文件当页面渲染
        disposition = "inline" if fm.preview_type != "none" and (fm.ext or "").lower() not in (
            "svg", "svgz", "html", "htm", "xhtml"
        ) else "attachment"
        # 强制下载才占用一次下载额度；内联 Range 只校验不计数，避免拖动进度条耗尽上限
        denied = _authorize_file_bytes(request, fm, consume_download=(disposition == "attachment"))
        if denied is not None:
            return denied
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(abs_path):
            return Response({"message": "物理文件缺失"}, status=status.HTTP_404_NOT_FOUND)

        total = os.path.getsize(abs_path)
        content_type = self._content_type(fm, abs_path)
        range_header = request.headers.get("Range") or request.META.get("HTTP_RANGE", "")

        filename = re.sub(r'[\\/:*?"<>|\r\n]', "_", fm.name).strip() or "file"

        match = re.match(r"bytes=(\d*)-(\d*)$", (range_header or "").strip())
        if match:
            start_raw, end_raw = match.group(1), match.group(2)
            if start_raw == "" and end_raw == "":
                start, end = 0, total - 1
            elif start_raw == "":
                start, end = max(total - int(end_raw), 0), total - 1
            else:
                start = int(start_raw)
                end = int(end_raw) if end_raw else total - 1
            if start >= total:
                resp = HttpResponse(status=416)
                resp["Content-Range"] = f"bytes */{total}"
                return resp
            end = min(end, total - 1)
            length = end - start + 1

            def _iter(path, offset, remaining):
                with open(path, "rb") as f:
                    f.seek(offset)
                    left = remaining
                    while left > 0:
                        data = f.read(min(self.CHUNK, left))
                        if not data:
                            break
                        left -= len(data)
                        yield data

            resp = StreamingHttpResponse(
                _iter(abs_path, start, length), status=206, content_type=content_type
            )
            resp["Content-Range"] = f"bytes {start}-{end}/{total}"
            resp["Content-Length"] = str(length)
        else:
            resp = FileResponse(open(abs_path, "rb"), content_type=content_type)
            resp["Content-Length"] = str(total)

        resp["Accept-Ranges"] = "bytes"
        # #24：交给 Django 按 RFC5987 编码（非 ASCII 名走 filename*=utf-8''...，
        # 避免手拼导致的乱码/头部非法）；ASCII 名仍保留 filename=
        resp["Content-Disposition"] = content_disposition_header(disposition == "attachment", filename)
        resp["Cache-Control"] = "private, max-age=300"
        return resp

    @staticmethod
    def _content_type(fm, abs_path):
        ext = (fm.ext or "").lower()
        if ext in ("pdf",):
            return "application/pdf"
        if ext in FileMeta.VIDEO_EXTS:
            return {  # 保证浏览器 <video> 能识别
                "mp4": "video/mp4", "webm": "video/webm", "ogv": "video/ogg",
                "mov": "video/quicktime", "m4v": "video/x-m4v", "mkv": "video/x-matroska",
            }.get(ext, "application/octet-stream")
        if ext in FileMeta.AUDIO_EXTS:
            return {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg",
                    "flac": "audio/flac", "m4a": "audio/mp4", "aac": "audio/aac"}.get(
                ext, "application/octet-stream")
        if ext in FileMeta.IMAGE_EXTS:
            return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
                    "svg": "image/svg+xml", "ico": "image/x-icon", "avif": "image/avif"}.get(
                ext, "application/octet-stream")
        if ext in FileMeta.TEXT_EXTS:
            guessed = mimetypes.guess_type(abs_path)[0]
            if guessed and guessed.startswith("text/"):
                return f"{guessed}; charset=utf-8"
            return "text/plain; charset=utf-8"
        return mimetypes.guess_type(abs_path)[0] or "application/octet-stream"


class FileToPdfView(APIView):
    """把 Office 文档转成 PDF（LibreOffice）。

    - 已转换过且源文件未更新：直接返回已有结果（不重复调用外部进程）
    - 未安装 LibreOffice：返回 200 + code=LIBREOFFICE_NOT_FOUND + 安装指引
      （前端据此提示用户，而不是弹一个看不懂的 500）
    """

    def post(self, request, pk):
        return self._convert(request, pk, force=parse_bool(request.data.get("force"), field="force"))

    def get(self, request, pk):
        return self._convert(request, pk, force=request.query_params.get("force") == "1")

    def _convert(self, request, pk, force=False):
        fm = _get_file(request.user, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)

        if fm.preview_type != "office":
            return Response({"message": f".{fm.ext} 无需转换，可直接预览",
                             "code": "NOT_NEEDED", "preview_type": fm.preview_type})

        status_info = office.soffice_status()
        if not status_info["available"]:
            fm.pdf_status = "unavailable"
            fm.pdf_error = "未安装 LibreOffice"
            fm.save(update_fields=["pdf_status", "pdf_error"])
            return Response({
                "ok": False, "code": "LIBREOFFICE_NOT_FOUND",
                "message": status_info["hint"], "installed": False,
            })

        if not force and fm.pdf_path and os.path.exists(_safe_join(MEDIA, fm.pdf_path)):
            return Response({"ok": True, "code": "CACHED", "pdf_url": fm.pdf_url,
                             "pdf_status": "ready", "message": "已存在转换结果"})

        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(abs_path):
            return Response({"message": "物理文件缺失"}, status=404)

        result = office.convert_to_pdf(abs_path, fm.ext)
        if not result["ok"]:
            fm.pdf_status = "failed"
            fm.pdf_error = result["message"][:255]
            fm.save(update_fields=["pdf_status", "pdf_error"])
            http_status = 200 if result["code"] in ("LIBREOFFICE_NOT_FOUND", "UNSUPPORTED_FORMAT") else 500
            return Response({"ok": False, "code": result["code"], "message": result["message"]},
                            status=http_status)

        rel = office.relative_media_path(result["path"])
        fm.pdf_path = rel
        fm.pdf_status = "ready"
        fm.pdf_error = ""
        fm.pdf_updated_at = timezone.now()
        fm.save(update_fields=["pdf_path", "pdf_status", "pdf_error", "pdf_updated_at"])
        return Response({"ok": True, "code": "OK", "pdf_url": fm.pdf_url,
                         "pdf_status": "ready", "message": "转换完成"})


class FilePdfView(APIView):
    """输出 PDF 供内嵌预览：Office 走转换产物，原生 PDF 走原文件"""

    def get(self, request, pk):
        # #23：PDF 与原文件同源，非 owner 同样必须持有效分享 token
        fm = FileMeta.objects.filter(pk=pk, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        denied = _authorize_file_bytes(request, fm, consume_download=False)
        if denied is not None:
            return denied

        rel = fm.pdf_path if fm.preview_type == "office" else fm.storage_path
        if not rel:
            return Response({"message": "尚未生成 PDF，请先调用转换接口", "code": "NOT_CONVERTED"},
                            status=status.HTTP_409_CONFLICT)
        abs_path = _safe_join(MEDIA, rel)
        if not os.path.exists(abs_path):
            return Response({"message": "PDF 文件缺失，请重新转换", "code": "FILE_MISSING"}, status=404)

        if fm.owner_id == request.user.id:
            _touch_recent(request.user, fm)
        resp = FileResponse(open(abs_path, "rb"), content_type="application/pdf")
        resp["Content-Disposition"] = "inline"
        resp["Accept-Ranges"] = "bytes"
        return resp


class OfficeCapabilityView(APIView):
    """Office 转 PDF 能力探测（前端可据此提示安装）"""

    def get(self, request):
        info = office.soffice_status()
        return Response({
            "installed": info["available"],
            "soffice_path": info["path"],
            "hint": info["hint"],
            "convertible_exts": sorted(office.CONVERTIBLE_EXTS),
        })


class RecentFileView(APIView):
    """最近访问的文件"""

    def get(self, request):
        qs = (RecentFile.objects.filter(owner=request.user)
              .select_related("file", "file__folder", "file__owner")
              .prefetch_related("file__tags")
              .filter(file__is_deleted=False)[:30])
        data = [FileMetaSerializer(r.file).data for r in qs]
        return Response({"list": data, "total": len(data)})

    def delete(self, request):
        RecentFile.objects.filter(owner=request.user).delete()
        return Response({"message": "已清空最近访问"})


class RecentFileDetailView(APIView):
    """S24-226：移除单条最近访问记录"""

    def delete(self, request, file_id):
        rec = RecentFile.objects.filter(owner=request.user, file_id=file_id).first()
        if not rec:
            return Response({"message": "记录不存在"}, status=status.HTTP_404_NOT_FOUND)
        rec.delete()
        return Response({"message": "已移除最近访问记录"})



class StarredFileView(APIView):
    """收藏的文件：支持 ?group= 按收藏分组筛选，并返回分组聚合；按 favorite_order 自定义排序"""

    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=False, is_star=True)
        group = request.query_params.get("group")
        if group is not None and group != "":
            qs = qs.filter(favorite_group=group)
        qs = qs.order_by("favorite_order", "-updated_at", "-created_at") \
            .select_related("folder", "owner").prefetch_related("tags")
        groups = list(_file_qs(request.user).filter(is_deleted=False, is_star=True)
                      .values("favorite_group").annotate(c=Count("id")))
        pg = OptionalPageNumberPagination()
        page = pg.paginate_queryset(qs, request)
        if page is not None:
            return pg.get_paginated_response(FileMetaSerializer(page, many=True).data)
        data = FileMetaSerializer(qs, many=True).data
        return Response({"list": data, "total": len(data), "groups": groups})


class StorageAnalysisView(APIView):
    """存储分析：按类型聚合、大文件 Top、重复占用、收藏数、回收站占用、配额"""

    def get(self, request):
        qs = _file_qs(request.user)
        active = qs.filter(is_deleted=False)
        by_kind = list(active.values("kind").annotate(count=Count("id"), bytes_sum=Sum("size")).order_by("-bytes_sum"))
        for row in by_kind:
            row["size_text"] = format_size(row["bytes_sum"] or 0)
        big = active.order_by("-size")[:10]
        # 重复文件（同 sha1 出现多次）
        dup_groups = active.exclude(sha1="").values("sha1").annotate(c=Count("id")).filter(c__gt=1)
        duplicates = []
        wasted = 0
        for g in dup_groups:
            group = active.filter(sha1=g["sha1"])
            first = group.first()
            duplicates.append({
                "sha1": g["sha1"], "count": g["c"], "name": first.name,
                "size": first.size, "size_text": format_size(first.size),
            })
            wasted += first.size * (g["c"] - 1)
        trash_bytes = qs.filter(is_deleted=True).aggregate(s=Sum("size"))["s"] or 0
        used = active.aggregate(s=Sum("size"))["s"] or 0
        return Response({
            "used_bytes": used, "used_text": format_size(used),
            "trash_bytes": trash_bytes, "trash_text": format_size(trash_bytes),
            "quota_mb": request.user.storage_quota_mb,
            "quota_used_pct": round(used / (request.user.storage_quota_mb * 1024 * 1024) * 100, 1) if request.user.storage_quota_mb else 0,
            "by_kind": by_kind,
            "big_files": FileMetaSerializer(big, many=True).data,
            "duplicates": duplicates, "duplicate_wasted_text": format_size(wasted),
            "starred": active.filter(is_star=True).count(),
            "file_count": active.count(),
        })


class StorageFolderStatsView(APIView):
    """S24-219：按文件夹递归聚合体积与文件数，倒序取前 20"""

    def get(self, request):
        folders = list(Folder.objects.filter(owner=request.user).only("id", "name", "parent_id"))
        rows = (
            FileMeta.objects.filter(owner=request.user, is_deleted=False, folder__isnull=False)
            .values("folder_id").annotate(c=Count("id"), s=Sum("size"))
        )
        own = {r["folder_id"]: (r["c"] or 0, r["s"] or 0) for r in rows}
        children = {}
        for f in folders:
            children.setdefault(f.parent_id, []).append(f)
        memo = {}

        def _total(fid, guard):
            if fid in memo:
                return memo[fid]
            if fid in guard:
                return (0, 0)
            guard = guard | {fid}
            c, s = own.get(fid, (0, 0))
            for child in children.get(fid, []):
                cc, ss = _total(child.id, guard)
                c += cc
                s += ss
            memo[fid] = (c, s)
            return memo[fid]

        used = FileMeta.objects.filter(owner=request.user, is_deleted=False).aggregate(s=Sum("size"))["s"] or 0
        items = []
        for f in folders:
            c, s = _total(f.id, frozenset())
            if s <= 0 and c == 0:
                continue
            items.append({
                "id": f.id, "name": f.name, "parent": f.parent_id,
                "file_count": c, "size": s, "size_text": format_size(s),
                "pct": round(s / used * 100, 1) if used else 0.0,
            })
        items.sort(key=lambda x: (-x["size"], -x["file_count"]))
        items = items[:20]
        root = FileMeta.objects.filter(owner=request.user, is_deleted=False, folder__isnull=True) \
            .aggregate(c=Count("id"), s=Sum("size"))
        return Response({
            "list": items, "total": len(items),
            "used_bytes": used, "used_text": format_size(used),
            "root": {"file_count": root["c"] or 0, "size": root["s"] or 0,
                     "size_text": format_size(root["s"] or 0)},
        })


# ============ 回收站 ============

class TrashListView(APIView):
    """回收站列表：支持 q / kind / deleted_after / deleted_before 过滤，并给出剩余保留天数"""

    def _keep_days(self):
        return int(getattr(settings, "TRASH_KEEP_DAYS", 30) or 30)

    @staticmethod
    def _with_remaining_days(files, data, keep_days):
        """在序列化结果上补 remaining_days（距离自动清理的天数）"""
        now = timezone.now()
        for fm, row in zip(files, data):
            if fm.deleted_at:
                used = (now - fm.deleted_at).days
                row["remaining_days"] = max(0, keep_days - used)
            else:
                row["remaining_days"] = keep_days
        return data

    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=True)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        # S24-232：删除时间范围（date 字符串 YYYY-MM-DD）
        for key, lookup in (("deleted_after", "deleted_at__date__gte"),
                            ("deleted_before", "deleted_at__date__lte")):
            raw = (request.query_params.get(key) or "").strip()
            if not raw:
                continue
            try:
                value = date.fromisoformat(raw)
            except ValueError:
                return Response({"message": f"{key} 必须是 YYYY-MM-DD"}, status=400)
            qs = qs.filter(**{lookup: value})
        qs = qs.order_by("-deleted_at").select_related("folder", "owner").prefetch_related("tags")
        keep_days = self._keep_days()
        pg = OptionalPageNumberPagination()
        page = pg.paginate_queryset(qs, request)
        if page is not None:
            data = FileMetaSerializer(page, many=True).data
            self._with_remaining_days(page, data, keep_days)
            return pg.get_paginated_response(data)
        rows = list(qs)
        data = FileMetaSerializer(rows, many=True).data
        self._with_remaining_days(rows, data, keep_days)
        return Response({"list": data, "total": len(data), "keep_days": keep_days})


class TrashActionView(APIView):
    """回收站：restore 恢复（还原到删除前目录）/ delete 彻底删除 / empty 清空"""

    def post(self, request):
        action = request.data.get("action", "restore")
        raw_ids = request.data.get("file_ids")
        ids = _as_id_list(raw_ids) if raw_ids else []
        if ids is None:
            return Response({"message": "file_ids 必须是整数数组"}, status=400)
        if not ids:
            # 空数组不是「全选」：只有显式 all=true 才允许清空/全量还原
            if action in ("delete", "empty") and str(request.data.get("all", "")).lower() in ("1", "true", "yes"):
                pass
            else:
                return Response({"message": "未选择文件"}, status=400)
        qs = FileMeta.objects.filter(owner=request.user, is_deleted=True)
        if ids:
            qs = qs.filter(id__in=ids)
        if action == "restore":
            with transaction.atomic():
                count, renamed = _restore_files(request.user, qs)
            payload = {"message": f"已恢复 {count} 个文件", "restored": count, "renamed": renamed}
            if renamed:
                payload["message"] = f"已恢复 {count} 个文件，其中 {renamed} 个已改名"
            return Response(payload)
        if action in ("delete", "empty"):
            count = 0
            for fm in qs:
                # #55：元数据与缩略图/原文件的清理都由 _remove_physical 收口
                # （事务内删元数据，提交后再删磁盘），这里不再重复 delete
                FileBatchView._remove_physical(fm)
                count += 1
            word = "彻底删除" if action == "delete" else "清空"
            return Response({"message": f"已{word} {count} 个文件"})
        return Response({"message": "未知操作"}, status=status.HTTP_400_BAD_REQUEST)


class TrashAutoCleanView(APIView):
    """清理超过保留期的回收站文件（按 TRASH_KEEP_DAYS，可传 days 覆盖）"""

    # #22：单请求最多处理 200 条，超出部分分多次清理，避免一次请求遍历全库
    MAX_PER_RUN = 200

    def post(self, request):
        from django.conf import settings as s
        try:
            days = int(request.data.get("days") or s.TRASH_KEEP_DAYS)
        except (TypeError, ValueError):
            days = s.TRASH_KEEP_DAYS
        if days < 1:
            return Response({"message": "days 必须 >= 1"}, status=status.HTTP_400_BAD_REQUEST)
        threshold = timezone.now() - timedelta(days=days)
        qs = FileMeta.objects.filter(owner=request.user, is_deleted=True, deleted_at__lt=threshold)
        targets = list(qs.order_by("deleted_at")[: self.MAX_PER_RUN])
        with transaction.atomic():
            for fm in targets:
                FileBatchView._remove_physical(fm)
        # 事务提交后再统计剩余量（本次已删的不会计入）
        remaining = qs.count()
        return Response({
            "message": f"已清理 {len(targets)} 个过期回收文件",
            "cleaned": len(targets),
            "remaining": remaining,
            "days": days,
        })

    def get(self, request):
        """返回当前清理配置"""
        from django.conf import settings as s
        return Response({"trash_keep_days": getattr(s, "TRASH_KEEP_DAYS", 30)})


# ============ 共享链接 ============

class ShareLinkCreateView(APIView):
    # #21 配额与默认有效期：防止单用户/单文件无限建链，也避免「不填就永久有效」
    MAX_LINKS_PER_USER = 200
    MAX_LINKS_PER_TARGET = 20
    DEFAULT_EXPIRE_HOURS = 24 * 7
    # #93 有效期与次数上限：到期时间由 timedelta 计算，超大值会 OverflowError→500
    MIN_EXPIRE_HOURS = 1
    MAX_EXPIRE_HOURS = 8760  # 1 年
    MAX_DOWNLOADS_LIMIT = 1000000

    def post(self, request):
        file_id = request.data.get("file_id")
        folder_id = request.data.get("folder_id")
        permission = request.data.get("permission", "view")
        expire_hours = request.data.get("expire_hours")
        password = request.data.get("password", "") or ""
        max_downloads = request.data.get("max_downloads")
        if permission not in ("view", "download", "edit"):
            return Response({"message": "权限值非法"}, status=400)
        try:
            # 未指定时默认 7 天；显式传 0 表示永久有效（保留原有语义）
            hours = int(expire_hours) if expire_hours not in (None, "") else self.DEFAULT_EXPIRE_HOURS
            mlimit = int(max_downloads) if max_downloads not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            return Response({"message": "expire_hours / max_downloads 必须是整数"}, status=400)
        # #93：有效期限定 0（永久）或 1–8760 小时，次数上限必须在 1–1000000
        if hours and (hours < self.MIN_EXPIRE_HOURS or hours > self.MAX_EXPIRE_HOURS):
            return Response(
                {"message": f"expire_hours 必须在 {self.MIN_EXPIRE_HOURS}–{self.MAX_EXPIRE_HOURS} 小时之间（0 表示永久）",
                 "code": "SHARE_EXPIRE_RANGE"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if mlimit is not None and not (1 <= mlimit <= self.MAX_DOWNLOADS_LIMIT):
            return Response(
                {"message": f"max_downloads 必须在 1–{self.MAX_DOWNLOADS_LIMIT} 之间",
                 "code": "SHARE_MAX_DOWNLOADS_RANGE"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # S24-223：文件夹分享可开启访客上传（收集链接）
        try:
            allow_upload = parse_bool(request.data.get("allow_upload"), field="allow_upload")
        except ValidationError:
            return Response({"message": "allow_upload 必须是布尔值"}, status=400)

        target = None
        if file_id:
            try:
                file_id = as_int(file_id, field="file_id", minimum=1)
            except ValidationError:
                return Response({"message": "file_id 必须是整数"}, status=400)
            target = FileMeta.objects.filter(pk=file_id, owner=request.user).first()
            if not target:
                return Response({"message": "文件不存在"}, status=404)
        elif folder_id:
            try:
                folder_id = as_int(folder_id, field="folder_id", minimum=1)
            except ValidationError:
                return Response({"message": "folder_id 必须是整数"}, status=400)
            target = Folder.objects.filter(pk=folder_id, owner=request.user).first()
            if not target:
                return Response({"message": "文件夹不存在"}, status=404)
        else:
            return Response({"message": "请指定文件或文件夹"}, status=400)

        # #21：配额按「未撤销」链接统计，撤销后额度立即释放
        alive = ShareLink.objects.filter(created_by=request.user, is_revoked=False)
        if alive.count() >= self.MAX_LINKS_PER_USER:
            return Response(
                {"message": f"分享链接数量已达上限（{self.MAX_LINKS_PER_USER} 条），请先撤销不用的链接",
                 "code": "SHARE_LINK_QUOTA"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        same_target = alive.filter(
            file=target if isinstance(target, FileMeta) else None,
            folder=target if isinstance(target, Folder) else None,
        ).count()
        if same_target >= self.MAX_LINKS_PER_TARGET:
            return Response(
                {"message": f"该文件/文件夹的分享链接已达上限（{self.MAX_LINKS_PER_TARGET} 条）",
                 "code": "SHARE_LINK_TARGET_QUOTA"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = uuid.uuid4().hex[:16]
        expire_at = timezone.now() + timedelta(hours=hours) if hours else None
        link = ShareLink.objects.create(
            token=token,
            file=target if isinstance(target, FileMeta) else None,
            folder=target if isinstance(target, Folder) else None,
            created_by=request.user,
            permission=permission,
            expire_at=expire_at,
            # S2-B1：密码 hash 存储（make_password 自带盐值，同密码不同链接
            # 哈希也不同，撞库无法横向比对）；留空表示无密码
            password=make_password(password[:64]) if password else "",
            max_downloads=mlimit,
            allow_upload=allow_upload and isinstance(target, Folder),
        )
        if link.file:
            _record_visibility(link.file, request.user, note="创建共享链接", action="share_create")
        return Response(ShareLinkSerializer(link).data, status=201)


class ShareLinkListView(APIView):
    """我创建的共享链接，支持类型 / 状态筛选（#53：条件下推 + 标准分页）"""

    def get(self, request):
        qs = ShareLink.objects.filter(created_by=request.user).order_by("-created_at")
        now = timezone.now()
        # 与 ShareLink.is_expired 同口径：撤销 / 过期 / 下载次数达上限
        active_q = (
            Q(is_revoked=False)
            & (Q(expire_at__isnull=True) | Q(expire_at__gt=now))
            & (Q(max_downloads__isnull=True) | Q(download_count__lt=F("max_downloads")))
        )
        st = request.query_params.get("status")
        if st == "expired":
            qs = qs.exclude(active_q)
        elif st == "active":
            qs = qs.filter(active_q)
        ttype = request.query_params.get("type")
        if ttype == "file":
            qs = qs.filter(file__isnull=False)
        elif ttype == "folder":
            qs = qs.filter(folder__isnull=False)
        pg = StandardPagination()
        page = pg.paginate_queryset(qs, request)
        return pg.get_paginated_response(ShareLinkSerializer(page, many=True).data)


class ShareLinkDetailView(APIView):
    """撤销 / 更新共享链接"""

    def _get(self, request, token):
        return ShareLink.objects.filter(token=token, created_by=request.user).first()

    def patch(self, request, token):
        link = self._get(request, token)
        if not link:
            return Response({"message": "链接不存在"}, status=404)
        if "permission" in request.data:
            if request.data["permission"] not in ("view", "download", "edit"):
                return Response({"message": "权限值非法"}, status=400)
            link.permission = request.data["permission"]
        if "password" in request.data:
            # S2-B1：密码 hash 存储；留空/显式空串 = 清除密码
            pw = request.data["password"] or ""
            link.password = make_password(pw[:64]) if pw else ""
        if "max_downloads" in request.data:
            v = request.data["max_downloads"]
            try:
                link.max_downloads = int(v) if v not in (None, "", 0, "0") else None
            except (TypeError, ValueError):
                return Response({"message": "max_downloads 必须是整数"}, status=400)
        if "expire_hours" in request.data:
            eh = request.data["expire_hours"]
            if eh not in (None, ""):
                try:
                    link.expire_at = timezone.now() + timedelta(hours=int(eh))
                except (TypeError, ValueError):
                    return Response({"message": "expire_hours 必须是整数"}, status=400)
            else:
                link.expire_at = None
        if "is_revoked" in request.data:
            link.is_revoked = parse_bool(request.data["is_revoked"], field="is_revoked")
        if "allow_upload" in request.data:
            # 仅文件夹分享支持上传
            link.allow_upload = parse_bool(request.data["allow_upload"], field="allow_upload") and bool(link.folder_id)
        link.save()
        if link.file:
            _record_visibility(link.file, request.user, note="更新共享链接", action="share_update")
        return Response(ShareLinkSerializer(link).data)

    def delete(self, request, token):
        link = self._get(request, token)
        if not link:
            return Response({"message": "链接不存在"}, status=404)
        fm = link.file
        link.delete()
        if fm:
            _record_visibility(fm, request.user, note="撤销共享链接", action="share_revoke")
        return Response({"message": "链接已撤销"})


class ShareAccessView(APIView):
    """公开访问共享链接（AllowAny）：密码校验 + 浏览计数"""

    permission_classes = [AllowAny]

    def get(self, request, token):
        link = find_link(token)
        try:
            validate_link(link, request_password(request), request=request)
        except ShareAccessError as exc:
            return exc.as_response()
        bump_view(link)
        if link.file:
            fm = link.file
            info = {
                "type": "file", "id": fm.id, "name": fm.name, "size": fm.size, "kind": fm.kind,
                "permission": link.permission, "can_download": link.permission in ("download", "edit"),
            }
            if fm.kind == "image":
                # 不再回裸 /media/ 地址：那等于把「仅预览」分享变成可绕过 token 的直接下载。
                # 统一走带 token 校验的 /api/share/<token>/raw/<id>/
                info["url"] = f"/api/share/{token}/raw/{fm.id}/"
            if fm.kind in ("text", "other"):
                abs_path = _safe_join(MEDIA, fm.storage_path)
                if os.path.exists(abs_path):
                    try:
                        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                            info["preview"] = f.read(64 * 1024)
                    except Exception:
                        info["preview"] = ""
            return Response(info)
        if link.folder:
            files = link.folder.files.filter(is_deleted=False).only("id", "name", "size", "kind")
            return Response({
                "type": "folder", "name": link.folder.name, "permission": link.permission,
                # S24-223：开启允许上传时公开页展示投递入口
                "allow_upload": bool(link.allow_upload),
                "upload_url": f"/api/share/{token}/upload/" if link.allow_upload else "",
                "upload_max_mb": ShareUploadView.MAX_BYTES // (1024 * 1024),
                # 只回展示所需字段；文件序列化器会带出 /media/ 直链与内部路径
                "files": [
                    {"id": f.id, "name": f.name, "size": f.size, "kind": f.kind}
                    for f in files
                ],
            })
        return Response({"message": "链接异常"}, status=404)


class ShareDownloadView(APIView):
    """通过共享链接下载（计数 + 上限 + 密码）"""

    permission_classes = [AllowAny]

    def get(self, request, token, pk):
        link = find_link(token, file_id=pk)
        try:
            validate_link(link, request_password(request), for_download=True, request=request)
        except ShareAccessError as exc:
            return exc.as_response()
        fm = link.file
        if not fm:
            return Response({"message": "链接异常"}, status=404)
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(abs_path):
            return Response({"message": "物理文件缺失"}, status=404)
        # 原子占用一次下载额度，并发下不会突破 max_downloads
        if not bump_download(link):
            return Response({"message": "下载次数已达上限"}, status=403)
        return FileResponse(open(abs_path, "rb"), as_attachment=True,
                            filename=sanitize_filename(fm.name))


class ShareRawView(APIView):
    """共享链接内联预览（AllowAny）：图片等资源必须带有效 token 才能读取。

    历史实现把 `fm.url`（/media/<path>）直接返回给公开分享页，
    等于绕过 password / 过期 / 权限——拿到链接甚至只拿到文件名就能下载。
    """

    permission_classes = [AllowAny]

    def get(self, request, token, pk):
        link = find_link(token)
        try:
            validate_link(link, request_password(request), request=request)
        except ShareAccessError as exc:
            return exc.as_response()
        fm = FileMeta.objects.filter(pk=pk, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=404)
        if link.file_id and link.file_id != fm.id:
            return Response({"message": "文件不在分享范围内"}, status=404)
        if link.folder_id and fm.folder_id != link.folder_id:
            return Response({"message": "文件不在分享范围内"}, status=404)
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(abs_path):
            return Response({"message": "物理文件缺失"}, status=404)
        disposition = "inline" if fm.preview_type != "none" and (fm.ext or "").lower() not in (
            "svg", "svgz", "html", "htm", "xhtml"
        ) else "attachment"
        # view 权限只能内联预览；下载原始字节必须 download/edit 且消耗额度
        if disposition == "attachment":
            if link.permission not in ("download", "edit"):
                return Response({"message": "该分享链接仅允许预览"}, status=403)
            if not bump_download(link):
                return Response({"message": "下载次数已达上限"}, status=403)
        resp = FileResponse(open(abs_path, "rb"),
                            content_type=FileRawView._content_type(fm, abs_path))
        resp["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{sanitize_filename(fm.name)}"
        resp["Cache-Control"] = "private, max-age=300"
        return resp


# ============ 公开收集上传（S24-223） ============

class ShareUploadView(APIView):
    """S24-223：公开收集上传——把单个文件投递到开启 allow_upload 的文件夹分享"""

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]
    MAX_BYTES = 50 * 1024 * 1024
    # 可执行/脚本/可注入类型一律拒收，避免把收集链接变成投毒入口
    DENY_EXTS = {
        "exe", "bat", "cmd", "com", "cpl", "dll", "msi", "scr", "vbs", "vbe", "js", "jse",
        "wsf", "wsh", "ps1", "psm1", "jar", "php", "phtml", "jsp", "asp", "aspx", "cgi",
        "sh", "bash", "py", "rb", "pl", "svg", "html", "htm", "xhtml", "hta", "lnk", "reg",
    }

    def post(self, request, token):
        link = find_link(token)
        try:
            validate_link(link, request_password(request), request=request)
        except ShareAccessError as exc:
            return exc.as_response()
        if not link.allow_upload:
            return Response({"message": "该链接未开启上传", "code": "UPLOAD_DISABLED"}, status=403)
        if not link.folder_id:
            return Response({"message": "仅文件夹分享支持上传", "code": "NOT_FOLDER"},
                            status=status.HTTP_400_BAD_REQUEST)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"message": "缺少文件"}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size <= 0 or upload.size > self.MAX_BYTES:
            return Response(
                {"message": f"文件大小需在 1 字节到 {self.MAX_BYTES // (1024 * 1024)}MB 之间"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = sanitize_filename(os.path.basename(str(upload.name or "upload.bin")),
                                 fallback="upload.bin", max_length=255)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext in self.DENY_EXTS:
            return Response({"message": f".{ext} 类型不允许上传", "code": "EXT_DENIED"},
                            status=status.HTTP_400_BAD_REQUEST)
        owner = link.created_by
        folder = link.folder
        blocked = check_quota(owner, upload.size)
        if blocked:
            return Response({"code": blocked[0], "message": blocked[1]},
                            status=status.HTTP_400_BAD_REQUEST)
        # 同名自动加序号，绝不覆盖已有文件
        base, dot_ext = os.path.splitext(name)
        taken = set(
            FileMeta.objects.filter(owner=owner, folder=folder, is_deleted=False)
            .values_list("name", flat=True)
        )
        candidate, i = name, 1
        while candidate in taken:
            candidate = f"{base}({i}){dot_ext}"
            i += 1
        rel_dir = os.path.join("files", str(owner.id), timezone.now().strftime("%Y%m"))
        os.makedirs(_safe_join(MEDIA, rel_dir), exist_ok=True)
        rel = os.path.join(rel_dir, f"{uuid.uuid4().hex}{dot_ext}").replace("\\", "/")
        abs_path = _safe_join(MEDIA, rel)
        with open(abs_path, "wb+") as out:
            for buf in upload.chunks():
                out.write(buf)
        real_size = os.path.getsize(abs_path)
        if real_size <= 0 or real_size > self.MAX_BYTES:
            try:
                os.remove(abs_path)
            except OSError:
                pass
            return Response({"message": "文件大小校验失败"}, status=status.HTTP_400_BAD_REQUEST)
        sha1 = sha1_file(abs_path)
        thumb_rel = _make_thumbnail(abs_path, ext) if file_kind(candidate) == "image" else ""
        fm = FileMeta.objects.create(
            name=candidate, folder=folder, owner=owner, storage_path=rel,
            size=real_size, sha1=sha1, kind=file_kind(candidate), ext=ext,
            thumbnail_path=thumb_rel,
        )
        _log_op(owner, fm, "upload", detail="分享链接收集上传", to_folder=_folder_label(folder))
        transaction.on_commit(lambda: _index_file(fm))
        _push_file_event(owner.id, "uploaded", file_id=fm.id, name=fm.name)
        return Response({
            "message": "上传成功",
            "file": {"id": fm.id, "name": fm.name, "size": fm.size, "size_text": format_size(fm.size)},
        }, status=status.HTTP_201_CREATED)


# ============ 文件标签（多标签体系） ============

# 内置文件夹模板（一键递归建夹）
FOLDER_TEMPLATES = [
    {"key": "project-docs", "name": "项目文档", "structure": {
        "立项": [], "需求": [], "设计": [], "测试": [], "发布": []}},
    {"key": "product-rd", "name": "产品研发", "structure": {
        "产品文档": [], "技术方案": [], "迭代记录": [], "会议纪要": []}},
    {"key": "personal", "name": "个人资料", "structure": {
        "证件": [], "财务": [], "学习": [], "生活": []}},
    {"key": "marketing", "name": "市场营销", "structure": {
        "素材": [], "文案": [], "活动": [], "竞品": []}},
    {"key": "team", "name": "团队协作", "structure": {
        "周报": [], "月报": [], "培训": [], "制度": []}},
]


class FileTagListView(APIView):
    """文件标签列表（含用量）/ 新建标签"""

    def get(self, request):
        qs = FileTag.objects.filter(owner=request.user).order_by("name")
        return Response({"list": FileTagSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "标签名不能为空"}, status=status.HTTP_400_BAD_REQUEST)
        tag, created = FileTag.objects.get_or_create(
            name=name[:50], owner=request.user,
            defaults={"color": request.data.get("color", "default")},
        )
        if not created:
            return Response({"message": "标签已存在"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(FileTagSerializer(tag).data, status=status.HTTP_201_CREATED)


class FileTagDetailView(APIView):
    """文件标签重命名 / 改色 / 删除"""

    def get_object(self, request, pk):
        return FileTag.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        tag = self.get_object(request, pk)
        if not tag:
            return Response({"message": "标签不存在"}, status=404)
        new_name = str(request.data.get("name") or "").strip()
        if new_name:
            tag.name = new_name[:50]
        if "color" in request.data:
            tag.color = request.data["color"]
        tag.save()
        return Response(FileTagSerializer(tag).data)

    def delete(self, request, pk):
        tag = self.get_object(request, pk)
        if not tag:
            return Response({"message": "标签不存在"}, status=404)
        tag.delete()
        return Response({"message": "标签已删除"})


class FileTagMergeView(APIView):
    """S24-217：合并标签——from 的文件关系整体并入 to 后删除 from"""

    def post(self, request):
        try:
            from_id = as_int(request.data.get("from_id"), field="from_id", minimum=1)
            to_id = as_int(request.data.get("to_id"), field="to_id", minimum=1)
        except ValidationError:
            return Response({"message": "from_id / to_id 必须是整数"}, status=400)
        if from_id == to_id:
            return Response({"message": "不能合并到自身"}, status=400)
        src = FileTag.objects.filter(pk=from_id, owner=request.user).first()
        dst = FileTag.objects.filter(pk=to_id, owner=request.user).first()
        if not src or not dst:
            return Response({"message": "标签不存在"}, status=404)
        through = FileMeta.tags.through
        moved, merged = 0, 0
        with transaction.atomic():
            already = set(
                through.objects.filter(filetag_id=to_id).values_list("filemeta_id", flat=True)
            )
            for link in through.objects.filter(filetag_id=from_id):
                if link.filemeta_id in already:
                    # 目标标签已有该文件：直接删除这条冗余关系
                    link.delete()
                    merged += 1
                    continue
                link.filetag_id = to_id
                link.save(update_fields=["filetag_id"])
                moved += 1
            src.delete()
        return Response({
            "message": f"已合并标签，迁移 {moved} 个文件" + (f"，去重 {merged} 条" if merged else ""),
            "moved": moved, "merged": merged, "from_id": from_id, "to_id": to_id,
            "to": FileTagSerializer(dst).data,
        })


class FileBatchTagView(APIView):
    """给一批文件打标签 / 移除标签（add / remove / set）"""

    def post(self, request):
        action = request.data.get("action", "set")
        ids = _as_id_list(request.data.get("file_ids"))
        names = request.data.get("tags") or []
        if ids is None:
            return Response({"message": "file_ids 必须是整数数组"}, status=status.HTTP_400_BAD_REQUEST)
        if not ids:
            return Response({"message": "未选择文件"}, status=status.HTTP_400_BAD_REQUEST)
        qs = FileMeta.objects.filter(owner=request.user, id__in=ids)
        tags = []
        for n in names:
            n = str(n).strip()
            if not n:
                continue
            tag, _ = FileTag.objects.get_or_create(name=n[:50], owner=request.user)
            tags.append(tag)
        n = 0
        with transaction.atomic():
            for fm in qs:
                if action == "add":
                    fm.tags.add(*tags)
                elif action == "remove":
                    fm.tags.remove(*tags)
                else:
                    fm.tags.set(tags)
                n += 1
        return Response({"message": f"已为 {n} 个文件更新标签", "updated": n})


class FileBatchRenameView(APIView):
    """批量重命名：
    - mode=prefix  加序号前缀：{prefix}{i:02d}_原名
    - mode=replace 正则/字面替换：find -> replace
    """

    def post(self, request):
        ids = _as_id_list(request.data.get("file_ids"))
        mode = request.data.get("mode", "prefix")
        if ids is None:
            return Response({"message": "file_ids 必须是整数数组"}, status=status.HTTP_400_BAD_REQUEST)
        if not ids:
            return Response({"message": "未选择文件"}, status=status.HTTP_400_BAD_REQUEST)
        qs = list(FileMeta.objects.filter(owner=request.user, id__in=ids, is_deleted=False))
        if not qs:
            return Response({"message": "没有可重命名的文件"}, status=400)
        try:
            # #94：pad 过大会让 zfill 分配超大字符串（pad=1e9 ≈ 每文件 1GB）
            start = as_int(request.data.get("start", 1), default=1, field="start",
                           minimum=0, maximum=1_000_000_000)
            pad = as_int(request.data.get("pad", 2), default=2, field="pad", minimum=1, maximum=8)
        except ValidationError:
            return Response({"message": "start 需在 0..10^9，pad 需在 1..8"}, status=400)
        prefix = request.data.get("prefix", "") or ""
        find = request.data.get("find", "") or ""
        repl = request.data.get("replace", "") or ""
        results, renamed = [], 0
        with transaction.atomic():
            for idx, fm in enumerate(qs):
                # #78：每条结果在循环内登记，不能等循环结束只留最后一条
                row = {"id": fm.id, "name": fm.name, "ok": True}
                base, ext = os.path.splitext(fm.name)
                if mode == "replace":
                    new_base = base.replace(find, repl) if find else base
                    new_name = f"{new_base}{ext}"
                else:
                    new_name = f"{prefix}{str(start + idx).zfill(pad)}_{fm.name}"
                new_name = sanitize_filename(new_name, fallback="", max_length=255)
                if not new_name:
                    row.update(ok=False, error="文件名不能为空")
                    results.append(row)
                    continue
                if new_name == fm.name:
                    results.append(row)
                    continue
                # 同目录重名检查：已保存的前序文件也会被查到，批量内冲突同样能拦住
                if FileMeta.objects.filter(
                    owner=request.user, folder_id=fm.folder_id, is_deleted=False, name=new_name,
                ).exclude(pk=fm.pk).exists():
                    row.update(ok=False, name=new_name, error="同目录下已存在同名文件")
                    results.append(row)
                    continue
                fm.name = new_name
                fm.save(update_fields=["name", "updated_at"])
                row["name"] = new_name
                renamed += 1
                results.append(row)
        failed = sum(1 for r in results if not r["ok"])
        return Response({
            "message": f"已重命名 {renamed} 个文件",
            "renamed": results, "count": renamed, "failed": failed,
        })


class FolderTemplatesView(APIView):
    """内置文件夹模板清单"""

    def get(self, request):
        return Response({"list": FOLDER_TEMPLATES, "total": len(FOLDER_TEMPLATES)})


class FolderFromTemplateView(APIView):
    """从模板一键递归创建文件夹。

    入参：{"key": "project-docs"} 或 {"structure": {"子目录": ["孙目录", ...]}, "parent": 0}
    """

    MAX_NODES = 200
    MAX_DEPTH = 5

    def post(self, request):
        parent = _owner_folder(request.user, request.data.get("parent"))
        structure = request.data.get("structure")
        if not structure:
            key = request.data.get("key")
            tpl = next((t for t in FOLDER_TEMPLATES if t["key"] == key), None)
            if not tpl:
                return Response({"message": "模板不存在"}, status=404)
            structure = tpl["structure"]
        # #116：先整体校验（类型/深度/节点数），非法直接 400，不产生半成品目录树
        try:
            tree = self._parse(structure, 1, [0])
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        created = []

        def create_level(nodes, parent_folder):
            """按层 bulk_create：深度 ≤ 5，所以最多 5 条 INSERT 而不是 N 条"""
            if not nodes:
                return
            folders = [Folder(name=n["name"], parent=parent_folder, owner=request.user) for n in nodes]
            Folder.objects.bulk_create(folders, batch_size=self.MAX_NODES)
            created.extend(f.name for f in folders)
            for node, folder in zip(nodes, folders):
                create_level(node["children"], folder)

        with transaction.atomic():
            create_level(tree, parent)
        return Response({"message": f"已创建 {len(created)} 个文件夹", "created": created, "count": len(created)})

    def _parse(self, node, depth, counter):
        """把模板结构收敛成 [{name, children}]；类型/深度/节点数非法抛 ValueError"""
        if depth > self.MAX_DEPTH:
            raise ValueError(f"目录层级不能超过 {self.MAX_DEPTH} 层")
        result = []
        if isinstance(node, dict):
            for name, children in node.items():
                result.append(self._node(name, children, depth, counter))
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    result.extend(self._parse(item, depth, counter))
                elif isinstance(item, str):
                    result.append(self._node(item, [], depth, counter))
                else:
                    raise ValueError("structure 列表元素必须是字符串或对象")
        else:
            raise ValueError("structure 必须是对象或数组")
        return result

    def _node(self, name, children, depth, counter):
        if not isinstance(name, str):
            raise ValueError("文件夹名称必须是字符串")
        clean = sanitize_filename(name.strip(), fallback="", max_length=200)
        if not clean:
            raise ValueError("文件夹名称不能为空")
        counter[0] += 1
        if counter[0] > self.MAX_NODES:
            raise ValueError(f"模板目录节点不能超过 {self.MAX_NODES} 个")
        if children is None:
            child_nodes = []
        else:
            child_nodes = self._parse(children, depth + 1, counter)
        return {"name": clean, "children": child_nodes}


class FileCleanConfigView(APIView):
    """回收站自动清理配置（读取；days 仅作展示，实际清理由 auto-clean 与管理命令执行）"""

    def get(self, request):
        return Response({
            "trash_keep_days": getattr(settings, "TRASH_KEEP_DAYS", 30),
            "file_max_size_mb": getattr(settings, "FILE_MAX_SIZE_MB", 1024),
        })


# =====================================================================
# =========== F547–F564 文件中心新增能力（只增不改） ====================
# =====================================================================

def _int_param(request, name, default, lo=None, hi=None):
    """安全取整数查询参数；非法值抛 ValueError（调用方转 400）"""
    raw = request.query_params.get(name, request.data.get(name, None)) \
        if hasattr(request, "query_params") else request.data.get(name, None)
    if raw in (None, ""):
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name} 必须是整数")
    if lo is not None and val < lo:
        raise ValueError(f"参数 {name} 不能小于 {lo}")
    if hi is not None and val > hi:
        raise ValueError(f"参数 {name} 不能大于 {hi}")
    return val


def _bad(message, code=400):
    return Response({"message": message, "ok": False, "error": message}, status=code)


class DuplicatesView(APIView):
    """F547 重复文件检测：按 sha1 分组，返回每组文件明细与可释放空间

    #110：先按 sha1 分组拿到重复列表，再用一次 `sha1__in` 查询取回全部明细，
    不再「每组一次回查」（500 组 = 501 次查询）。
    """

    def get(self, request):
        try:
            limit = _int_param(request, "limit", 100, lo=1, hi=500)
        except ValueError as e:
            return _bad(str(e))
        active = _file_qs(request.user).filter(is_deleted=False).exclude(sha1="").exclude(size=0)
        dup = list(active.values("sha1").annotate(c=Count("id")).filter(c__gt=1)
                   .order_by("-c")[:limit])
        if not dup:
            return Response({
                "groups": [], "group_count": 0, "file_count": 0,
                "wasted_bytes": 0, "wasted_text": format_size(0),
            })
        sha1s = [g["sha1"] for g in dup]
        rows = list(
            active.filter(sha1__in=sha1s).select_related("folder")
            .prefetch_related("tags").order_by("-created_at")
        )
        by_sha1 = {}
        for fm in rows:
            by_sha1.setdefault(fm.sha1, []).append(fm)
        groups, wasted, file_count = [], 0, 0
        for g in dup:
            files = by_sha1.get(g["sha1"]) or []
            if len(files) < 2:  # 分组后被并发删除，不再算重复
                continue
            size = files[0].size or 0
            w = size * (len(files) - 1)
            wasted += w
            file_count += len(files)
            groups.append({
                "sha1": g["sha1"], "count": len(files), "size": size,
                "size_text": format_size(size), "wasted": w, "wasted_text": format_size(w),
                "files": FileMetaSerializer(files, many=True).data,
            })
        return Response({
            "groups": groups, "group_count": len(groups), "file_count": file_count,
            "wasted_bytes": wasted, "wasted_text": format_size(wasted),
        })


class DuplicateResolveView(APIView):
    """S24-231：重复文件闭环——保留一份，其余同 SHA1 文件移入回收站"""

    def post(self, request):
        sha1 = str(request.data.get("sha1") or "").strip().lower()
        if len(sha1) != 40:
            return Response({"message": "sha1 不合法"}, status=400)
        try:
            keep_id = as_int(request.data.get("keep_id"), field="keep_id", minimum=1)
        except ValidationError:
            return Response({"message": "keep_id 必须是整数"}, status=400)
        qs = FileMeta.objects.filter(owner=request.user, sha1=sha1, is_deleted=False)
        keep = qs.filter(pk=keep_id).first()
        if not keep:
            return Response({"message": "要保留的文件不在该重复组内"}, status=404)
        targets = [fm for fm in qs.exclude(pk=keep_id).select_related("folder")]
        now = timezone.now()
        with transaction.atomic():
            for fm in targets:
                fm.is_deleted = True
                fm.deleted_at = now
                fm.origin_folder_id = fm.folder_id
            if targets:
                FileMeta.objects.bulk_update(
                    targets, ["is_deleted", "deleted_at", "origin_folder_id"], batch_size=500
                )
                for fm in targets:
                    _log_op(request.user, fm, "trash", detail="重复文件清理",
                            from_folder=_folder_label(fm.folder))
        return Response({
            "message": f"已保留 1 份，其余 {len(targets)} 个移入回收站",
            "keep_id": keep_id, "trashed": len(targets),
            "trashed_ids": [fm.id for fm in targets],
        })


class FileIntegrityView(APIView):
    """S24-222：重算物理文件 SHA1 / 大小并与记录比对（ok / mismatch / missing）"""

    MAX_FILES = 200

    def post(self, request):
        raw = request.data.get("file_ids")
        if raw in (None, "", []):
            ids = list(
                FileMeta.objects.filter(owner=request.user, is_deleted=False)
                .order_by("-updated_at").values_list("id", flat=True)[: self.MAX_FILES]
            )
        else:
            ids = _as_id_list(raw)
            if ids is None:
                return Response({"message": "file_ids 必须是整数数组"}, status=400)
            ids = ids[: self.MAX_FILES]
        files = list(FileMeta.objects.filter(owner=request.user, id__in=ids, is_deleted=False))
        ok, mismatch, missing = [], [], []
        for fm in files:
            abs_path = _safe_join(MEDIA, fm.storage_path) if fm.storage_path else ""
            if not abs_path or not os.path.isfile(abs_path):
                missing.append({"id": fm.id, "name": fm.name, "storage_path": fm.storage_path})
                continue
            real_size = os.path.getsize(abs_path)
            real_sha1 = sha1_file(abs_path)
            if real_size == fm.size and (not fm.sha1 or real_sha1 == fm.sha1):
                ok.append(fm.id)
            else:
                mismatch.append({
                    "id": fm.id, "name": fm.name,
                    "record_size": fm.size, "real_size": real_size,
                    "record_sha1": fm.sha1, "real_sha1": real_sha1,
                })
        return Response({
            "checked": len(files),
            "ok": ok, "ok_count": len(ok),
            "mismatch": mismatch, "mismatch_count": len(mismatch),
            "missing": missing, "missing_count": len(missing),
        })


class StorageTrendView(APIView):
    """F548 存储体积 30 天趋势：由文件创建/删除时间重建逐日曲线（前端渲染 SVG）"""

    def get(self, request):
        try:
            days = _int_param(request, "days", 30, lo=7, hi=90)
        except ValueError as e:
            return _bad(str(e))
        qs = _file_qs(request.user)
        # #117：按日聚合下推到数据库（TruncDate + Sum），不再把用户全部文件行
        # 拉进 Python 逐条累加；返回行数最多等于「有增量的天数」
        events = {}
        created_rows = (qs.annotate(day=TruncDate("created_at"))
                        .values("day").annotate(total=Sum("size")).order_by("day"))
        for row in created_rows:
            if row["day"] is None:
                continue
            events[row["day"]] = events.get(row["day"], 0) + (row["total"] or 0)
        deleted_rows = (qs.filter(deleted_at__isnull=False)
                        .annotate(day=TruncDate("deleted_at"))
                        .values("day").annotate(total=Sum("size")).order_by("day"))
        for row in deleted_rows:
            if row["day"] is None:
                continue
            events[row["day"]] = events.get(row["day"], 0) - (row["total"] or 0)
        today = timezone.localdate()
        start = today - timedelta(days=days - 1)
        first = min(events) if events else start
        if first > start:
            first = start
        points, running, day = [], 0, first
        while day <= today:
            running += events.get(day, 0)
            if day >= start:
                val = max(running, 0)
                points.append({"date": day.isoformat(), "bytes": val, "text": format_size(val)})
            day += timedelta(days=1)
        latest = points[-1]["bytes"] if points else 0
        earliest = points[0]["bytes"] if points else 0
        peak = max([p["bytes"] for p in points], default=0)
        change = latest - earliest
        return Response({
            "days": days, "points": points,
            "latest_bytes": latest, "latest_text": format_size(latest),
            "peak_bytes": peak, "peak_text": format_size(peak),
            "change_bytes": change, "change_text": format_size(abs(change)),
            "change_pct": round(change / earliest * 100, 1) if earliest else (100.0 if latest else 0.0),
        })


class LargeFilesView(APIView):
    """F549 大文件清单：阈值可调（min_mb，默认 50MB）"""

    def get(self, request):
        try:
            min_mb = float(request.query_params.get("min_mb", 50))
            limit = _int_param(request, "limit", 200, lo=1, hi=1000)
        except (ValueError, TypeError) as e:
            return _bad(str(e) if str(e) else "min_mb 必须是数字")
        if min_mb < 0:
            return _bad("min_mb 不能为负")
        threshold = int(min_mb * 1024 * 1024)
        qs = _file_qs(request.user).filter(is_deleted=False, size__gte=threshold).order_by("-size")
        total_bytes = qs.aggregate(s=Sum("size"))["s"] or 0
        files = list(qs[:limit])
        return Response({
            "threshold_mb": min_mb, "count": qs.count(),
            "files": FileMetaSerializer(files, many=True).data,
            "total_bytes": total_bytes, "total_text": format_size(total_bytes),
        })


class FileExportCsvView(APIView):
    """F550 文件清单导出 CSV（支持 keyword/kind/tag/star 过滤，UTF-8 BOM）"""

    MAX_ROWS = 50000

    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=False)
        keyword = request.query_params.get("keyword") or request.query_params.get("q")
        if keyword:
            qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
        kind = request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        tag = request.query_params.get("tag")
        if tag:
            qs = qs.filter(tags__name=tag).distinct()
        if request.query_params.get("star") == "1":
            qs = qs.filter(is_star=True)
        # #118/#148：select_related + prefetch 消除逐行 N+1；硬上限 5 万行，
        # 并用流式响应边查边写，不再整表拼进内存 StringIO
        qs = qs.select_related("folder").prefetch_related("tags") \
            .order_by("-created_at")[:self.MAX_ROWS]

        def rows():
            class _Echo:
                def write(self, value):
                    return value

            writer = csv.writer(_Echo())
            yield "\ufeff"
            yield writer.writerow(["ID", "文件名", "文件夹", "类型", "扩展名", "大小(字节)", "大小",
                                   "SHA1", "标签", "备注", "收藏", "创建时间", "更新时间"])
            for fm in qs.iterator(chunk_size=1000):
                tag_names = ",".join(t.name for t in fm.tags.all())
                yield writer.writerow([
                    fm.id, fm.name, _folder_label(fm.folder), fm.kind, fm.ext, fm.size,
                    format_size(fm.size), fm.sha1, tag_names, fm.description,
                    "是" if fm.is_star else "",
                    timezone.localtime(fm.created_at).strftime("%Y-%m-%d %H:%M") if fm.created_at else "",
                    timezone.localtime(fm.updated_at).strftime("%Y-%m-%d %H:%M") if fm.updated_at else "",
                ])

        resp = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = "attachment; filename=files.csv"
        return resp


class TrashStatsView(APIView):
    """F551 回收站统计（一键清空沿用 /trash/action/ action=empty）"""

    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=True)
        agg = qs.aggregate(count=Count("id"), bytes=Sum("size"))
        total = agg["count"] or 0
        total_bytes = agg["bytes"] or 0
        by_kind = []
        for row in qs.values("kind").annotate(c=Count("id"), s=Sum("size")).order_by("-s"):
            by_kind.append({"kind": row["kind"], "count": row["c"],
                            "bytes": row["s"] or 0, "text": format_size(row["s"] or 0)})
        oldest = qs.order_by("deleted_at").values_list("deleted_at", flat=True).first()
        newest = qs.order_by("-deleted_at").values_list("deleted_at", flat=True).first()
        return Response({
            "count": total, "bytes": total_bytes, "text": format_size(total_bytes),
            "by_kind": by_kind,
            "oldest_at": oldest, "newest_at": newest,
            "keep_days": getattr(settings, "TRASH_KEEP_DAYS", 30),
            "avg_text": format_size(total_bytes // total) if total else "0 B",
            "empty_api": "/api/files/trash/action/",
        })


def _image_dimensions(path):
    """读取图片宽高；PIL 不可用或读取失败时返回 None（降级不报错）"""
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
            return int(w), int(h)
    except Exception:
        return None


class ImageDimsView(APIView):
    """F553 图片分辨率批量徽章：按需计算并缓存 width/height"""

    def get(self, request):
        raw = request.query_params.get("ids", "")
        qs = _file_qs(request.user).filter(is_deleted=False)
        if raw.strip():
            try:
                ids = [int(x) for x in raw.split(",") if str(x).strip()][:300]
            except ValueError:
                return _bad("ids 必须是逗号分隔的整数")
            qs = qs.filter(id__in=ids)
        else:
            qs = qs.filter(kind="image", width__isnull=True)[:100]
        items = []
        for fm in qs:
            if not (fm.width and fm.height):
                if fm.kind == "image" or fm.ext in FileMeta.IMAGE_EXTS:
                    dim = _image_dimensions(_safe_join(MEDIA, fm.storage_path))
                    if dim:
                        fm.width, fm.height = dim
                        fm.save(update_fields=["width", "height"])
            items.append({
                "id": fm.id, "name": fm.name,
                "width": fm.width, "height": fm.height,
                "label": f"{fm.width}×{fm.height}" if fm.width and fm.height else "",
            })
        return Response({"list": items, "total": len(items)})


class StarredOrderView(APIView):
    """F555 收藏夹自定义排序：按传入顺序写入 favorite_order

    #112：条数上限 1000；先一次取出目标行，再 bulk_update，避免逐个 UPDATE。
    """

    MAX_ITEMS = 1000

    def post(self, request):
        ids = request.data.get("file_ids")
        if not isinstance(ids, list) or not ids:
            return _bad("file_ids 必须是非空数组")
        if len(ids) > self.MAX_ITEMS:
            return _bad(f"单次最多排序 {self.MAX_ITEMS} 个收藏")
        order, seen = [], set()
        for fid in ids:
            try:
                fid = int(fid)
            except (TypeError, ValueError):
                continue
            if fid in seen:
                continue
            seen.add(fid)
            order.append(fid)
        if not order:
            return _bad("file_ids 中没有合法的文件 ID")
        rows = {
            fm.id: fm
            for fm in FileMeta.objects.filter(owner=request.user, is_star=True, id__in=order)
        }
        changed = []
        for idx, fid in enumerate(order, start=1):
            fm = rows.get(fid)
            if fm is None:
                continue
            fm.favorite_order = idx
            changed.append(fm)
        if changed:
            FileMeta.objects.bulk_update(changed, ["favorite_order"], batch_size=500)
        return Response({"message": f"已更新 {len(changed)} 个收藏的排序", "updated": len(changed)})


class FolderHitsView(APIView):
    """F556 文件夹搜索命中计数徽章：按文件夹聚合关键词命中数"""

    def get(self, request):
        q = (request.query_params.get("q") or request.query_params.get("keyword") or "").strip()
        if not q:
            return Response({"keyword": "", "hits": [], "total": 0})
        try:
            limit = _int_param(request, "limit", 500, lo=1, hi=2000)
        except ValueError as e:
            return _bad(str(e))
        qs = _file_qs(request.user).filter(is_deleted=False).filter(
            Q(name__icontains=q) | Q(description__icontains=q)
        )
        folder_names = {f.id: f.name for f in Folder.objects.filter(owner=request.user)}
        hits, total = [], 0
        for row in qs.values("folder_id").annotate(c=Count("id")).order_by("-c"):
            fid = row["folder_id"] or 0
            ids = list(qs.filter(folder_id=row["folder_id"]).values_list("id", flat=True)[:limit])
            total += row["c"]
            hits.append({
                "folder_id": fid,
                "folder_name": folder_names.get(fid, "根目录") if fid else "根目录",
                "count": row["c"], "ids": ids,
            })
        return Response({"keyword": q, "hits": hits, "total": total})


class FileOperationListView(APIView):
    """F559 移动/复制等文件操作记录"""

    def get(self, request):
        qs = FileOperationLog.objects.filter(owner=request.user)
        action = request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)
        file_id = request.query_params.get("file_id")
        if file_id:
            try:
                qs = qs.filter(file_id=int(file_id))
            except (TypeError, ValueError):
                return _bad("file_id 必须是整数")
        try:
            limit = _int_param(request, "limit", 50, lo=1, hi=500)
        except ValueError as e:
            return _bad(str(e))
        rows = list(qs[:limit])
        labels = dict(FileOperationLog.ACTION_CHOICES)
        data = [{
            "id": x.id, "file_id": x.file_id, "file_name": x.file_name,
            "action": x.action, "action_label": labels.get(x.action, x.action),
            "detail": x.detail, "from_folder": x.from_folder, "to_folder": x.to_folder,
            "created_at": x.created_at,
        } for x in rows]
        return Response({"list": data, "total": len(data)})


class FileOperationHeatmapView(APIView):
    """S24-220：操作记录按日期 × 动作聚合，供日历热力格渲染"""

    def get(self, request):
        try:
            days = _int_param(request, "days", 180, lo=7, hi=365)
        except ValueError as e:
            return _bad(str(e))
        today = timezone.localdate()
        start = today - timedelta(days=days - 1)
        rows = (
            FileOperationLog.objects.filter(owner=request.user, created_at__date__gte=start)
            .annotate(day=TruncDate("created_at"))
            .values("day", "action").annotate(count=Count("id")).order_by("day")
        )
        labels = dict(FileOperationLog.ACTION_CHOICES)
        cells, by_day, by_action = [], {}, {}
        for row in rows:
            day = row["day"]
            if day is None:
                continue
            key = day.isoformat()
            cells.append({
                "date": key, "action": row["action"],
                "action_label": labels.get(row["action"], row["action"]),
                "count": row["count"],
            })
            by_day[key] = by_day.get(key, 0) + row["count"]
            by_action[row["action"]] = by_action.get(row["action"], 0) + row["count"]
        days_list = []
        for i in range(days):
            key = (start + timedelta(days=i)).isoformat()
            days_list.append({"date": key, "count": by_day.get(key, 0)})
        return Response({
            "days": days, "start": start.isoformat(), "end": today.isoformat(),
            "cells": cells,
            "days_list": days_list,
            "by_action": [
                {"action": a, "label": labels.get(a, a), "count": c}
                for a, c in sorted(by_action.items(), key=lambda x: -x[1])
            ],
            "max": max(by_day.values(), default=0),
            "total": sum(by_day.values()),
        })


class ShareExpiringView(APIView):
    """F560 分享链接到期前提醒（默认 3 天窗口）

    #107：GET 只读——不再逐链接做 `content__contains` 全表扫描并写通知；
    「已提醒」状态用一次查询（本人近期文件类通知）在 Python 侧解析 token 得到。
    推送副作用移到 POST 同一地址（一次性推送待提醒项）。
    """

    TOKEN_RE = re.compile(r"/share/([0-9a-zA-Z_-]{4,64})")
    NOTIFY_MAX = 100

    def _parse_days(self, request):
        return _int_param(request, "days", 3, lo=1, hi=60)

    def _links(self, request, days):
        now = timezone.now()
        horizon = now + timedelta(days=days)
        links = list(ShareLink.objects.filter(
            created_by=request.user, is_revoked=False,
            expire_at__isnull=False, expire_at__gte=now, expire_at__lte=horizon,
        ).select_related("file", "folder").order_by("expire_at"))
        return now, links

    def _reminded_tokens(self, user, tokens, now, days):
        """一次查询取近窗口内本人「文件」通知，再在内存里解析出已提醒的分享 token"""
        wanted = {t for t in tokens if t}
        if not wanted:
            return set()
        rows = Notification.objects.filter(
            recipient=user, category="files",
            created_at__gte=now - timedelta(days=max(days, 1) + 2),
        ).order_by("-created_at").values_list("content", flat=True)[:2000]
        found = set()
        for content in rows:
            for tok in self.TOKEN_RE.findall(content or ""):
                if tok in wanted:
                    found.add(tok)
        return found

    def _item(self, link, now):
        hours = (link.expire_at - now).total_seconds() / 3600
        name = link.file.name if link.file else (link.folder.name if link.folder else "")
        return {
            "token": link.token, "url": f"/share/{link.token}",
            "target": name, "target_type": "file" if link.file else "folder",
            "permission": link.permission, "expire_at": link.expire_at,
            "hours_left": round(hours, 1), "days_left": max(1, int((hours + 23) // 24)),
        }

    def get(self, request):
        try:
            days = self._parse_days(request)
        except ValueError as e:
            return _bad(str(e))
        now, links = self._links(request, days)
        items = [self._item(link, now) for link in links]
        reminded = self._reminded_tokens(
            request.user, [i["token"] for i in items], now, days
        )
        pending = [i["token"] for i in items if i["token"] not in reminded]
        return Response({
            "days": days, "list": items, "total": len(items),
            "notified": len(items) - len(pending), "pending": len(pending),
            "pending_tokens": pending[:self.NOTIFY_MAX],
            "notify_method": "POST", "readonly": True,
        })

    def post(self, request):
        """按需推送到期提醒（GET 无副作用，前端在用户确认或定时任务里调用）"""
        try:
            days = self._parse_days(request)
        except ValueError as e:
            return _bad(str(e))
        now, links = self._links(request, days)
        reminded = self._reminded_tokens(request.user, [l.token for l in links], now, days)
        created = 0
        for link in links:
            if link.token in reminded:
                continue
            if created >= self.NOTIFY_MAX:
                break
            item = self._item(link, now)
            notify(
                request.user,
                f"分享链接「{item['target']}」即将过期",
                content=(f"链接 /share/{link.token} 将于 {link.expire_at:%Y-%m-%d %H:%M} "
                         f"过期（{int(item['hours_left'])} 小时后）。"),
                category="files", level="warning", link="/files/shares",
            )
            created += 1
        return Response({
            "days": days, "notified": created, "skipped": len(links) - created,
            "total": len(links), "readonly": False,
        })


class FileVisibilityView(APIView):
    """F561 文件可见性快照：GET 当前状态 + 历史快照；POST 手动补记一条"""

    def _get(self, request, pk):
        # #24：软删文件不再可查分享状态（include_deleted=False）
        return _get_file(request.user, pk)

    def get(self, request, pk):
        fm = self._get(request, pk)
        if not fm:
            return _bad("文件不存在", 404)
        is_owner = fm.owner_id == request.user.id
        state = _visibility_state(fm)
        if not is_owner:
            # #24：分享 token/URL 是访问凭证，只回给所有者；非 owner（dept/all 范围）
            # 只能看到可见性聚合，不能拿到可用的分享链接
            state["shares"] = []
        labels = dict(FileVisibilitySnapshot.VISIBILITY_CHOICES)
        history = [{
            "id": s.id, "visibility": s.visibility,
            "visibility_label": labels.get(s.visibility, s.visibility),
            "data_scope": s.data_scope,
            "share_token": s.share_token if is_owner else "",
            "permission": s.permission, "expire_at": s.expire_at,
            "note": s.note, "created_at": s.created_at,
            "recorded_by": (getattr(s.created_by, "display_name", "")
                            or getattr(s.created_by, "username", "")) if s.created_by else "",
        } for s in FileVisibilitySnapshot.objects.filter(file=fm)[:50]]
        state["history"] = history
        state["history_count"] = len(history)
        state["can_write"] = is_owner
        return Response(state)

    def post(self, request, pk):
        fm = self._get(request, pk)
        if not fm:
            return _bad("文件不存在", 404)
        if fm.owner_id != request.user.id:
            return _bad("仅文件所有者可以记录可见性快照", 403)
        note = str(request.data.get("note") or "手动记录快照")[:255]
        _record_visibility(fm, request.user, note=note, action="manual")
        return Response({"message": "已记录可见性快照", "state": _visibility_state(fm)},
                        status=status.HTTP_201_CREATED)


class FileTagStatsView(APIView):
    """F563 标签统计与点击过滤（过滤由 /files/?tag= 承接）

    #109：单个聚合查询算出每个标签的文件数与占用体积，不再「每标签 2 次查询」。
    """

    def get(self, request):
        base = _file_qs(request.user).filter(is_deleted=False)
        total_bytes = base.aggregate(s=Sum("size"))["s"] or 0
        total_count = base.count()
        not_deleted = Q(files__is_deleted=False)
        rows = (
            FileTag.objects.filter(owner=request.user)
            .annotate(
                c=Count("files", filter=not_deleted),
                b=Sum("files__size", filter=not_deleted),
            )
            .values("id", "name", "color", "c", "b")
            .order_by("-c", "name")
        )
        items = []
        for t in rows:
            cnt = t["c"] or 0
            b = t["b"] or 0
            items.append({
                "id": t["id"], "name": t["name"], "color": t["color"], "count": cnt,
                "bytes": b, "bytes_text": format_size(b),
                "pct": round(b / total_bytes * 100, 1) if total_bytes else 0.0,
                "count_pct": round(cnt / total_count * 100, 1) if total_count else 0.0,
            })
        return Response({
            "list": items, "total_tags": len(items), "total_files": total_count,
            "total_bytes": total_bytes, "total_text": format_size(total_bytes),
            "untagged": base.filter(tags__isnull=True).count(),
        })


class FavoritesExportView(APIView):
    """F564 收藏/标签导出 JSON（浏览器直接下载）

    #99/#108：分页导出（单页 ≤500 条，响应体带 page/page_size/has_more/next_page 游标），
    select_related("folder") + prefetch_related("tags")，避免逐条查父目录与逐条查标签。
    """

    PAGE_SIZE = 500

    def get(self, request):
        try:
            page = _int_param(request, "page", 1, lo=1)
            page_size = _int_param(request, "page_size", self.PAGE_SIZE, lo=1, hi=self.PAGE_SIZE)
        except ValueError as e:
            return _bad(str(e))
        qs = _file_qs(request.user).filter(is_deleted=False, is_star=True) \
            .select_related("folder").prefetch_related("tags") \
            .order_by("favorite_order", "-created_at", "id")
        total = qs.count()
        start = (page - 1) * page_size
        rows = list(qs[start:start + page_size]) if start < total else []
        files = [{
            "id": f.id, "name": f.name, "folder": _folder_label(f.folder),
            "group": f.favorite_group, "star": True,
            "tags": [t.name for t in f.tags.all()],
            "size": f.size, "sha1": f.sha1,
            "created_at": f.created_at.isoformat() if f.created_at else "",
        } for f in rows]
        tags = [{"name": t.name, "color": t.color} for t in FileTag.objects.filter(owner=request.user)]
        has_more = start + len(files) < total
        payload = {
            "type": "files-favorites", "version": 1,
            "exported_at": timezone.now().isoformat(),
            "file_count": len(files), "tag_count": len(tags),
            "files": files, "tags": tags,
            # #99 分页游标：下一页没有数据时 next_page 为 null
            "page": page, "page_size": page_size, "total_files": total,
            "has_more": has_more, "next_page": page + 1 if has_more else None,
        }
        resp = HttpResponse(json.dumps(payload, ensure_ascii=False, indent=2),
                            content_type="application/json; charset=utf-8")
        suffix = "" if page == 1 else f"_p{page}"
        resp["Content-Disposition"] = f"attachment; filename=file_favorites{suffix}.json"
        return resp


class FavoritesImportView(APIView):
    """F564 收藏/标签导入 JSON：按文件名（+目录）匹配，回填收藏/分组/标签"""

    def post(self, request):
        payload = request.data.get("payload")
        if payload is None:
            payload = request.data
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                return _bad("payload 不是合法 JSON")
        if not isinstance(payload, dict):
            return _bad("payload 必须是对象")
        if payload.get("type") not in (None, "files-favorites"):
            return _bad("不支持的导入类型")
        items = payload.get("files")
        if not isinstance(items, list):
            return _bad("files 必须是数组")
        if len(items) > 1000:
            return _bad("单次最多导入 1000 条")

        # 标签定义（带颜色）先落库
        tags_created = 0
        for t in payload.get("tags") or []:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name") or "").strip()[:50]
            if not name:
                continue
            _, created = FileTag.objects.get_or_create(
                name=name, owner=request.user,
                defaults={"color": str(t.get("color") or "default")[:16]},
            )
            if created:
                tags_created += 1

        # 导入只回填「本人」文件：数据范围（dept/all）能让管理员看见他人文件，
        # 但收藏/标签是个人数据，按名称匹配到别人文件上属于越权改名
        existing = list(FileMeta.objects.filter(owner=request.user, is_deleted=False))
        by_name = {}
        for fm in existing:
            by_name.setdefault(fm.name, []).append(fm)

        matched = starred = tag_links = skipped = 0
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            name = str(item.get("name") or "").strip()
            cands = by_name.get(name) or []
            if not cands:
                skipped += 1
                continue
            fm = cands[0]
            if len(cands) > 1 and item.get("folder"):
                for c in cands:
                    if _folder_label(c.folder) == str(item.get("folder")):
                        fm = c
                        break
            matched += 1
            if item.get("star", True) and not fm.is_star:
                fm.is_star = True
                fm.save(update_fields=["is_star", "updated_at"])
                starred += 1
            group = str(item.get("group") or "").strip()[:50]
            if group and fm.favorite_group != group:
                fm.favorite_group = group
                fm.save(update_fields=["favorite_group", "updated_at"])
            names = item.get("tags") or []
            if isinstance(names, list) and names:
                tags = []
                for n in names:
                    n = str(n).strip()[:50]
                    if not n:
                        continue
                    tag, _ = FileTag.objects.get_or_create(name=n, owner=request.user)
                    tags.append(tag)
                if tags:
                    fm.tags.add(*tags)
                    tag_links += len(tags)
        return Response({
            "message": f"导入完成：匹配 {matched} 个文件，新增收藏 {starred} 个",
            "matched": matched, "starred": starred, "tag_links": tag_links,
            "tags_created": tags_created, "skipped": skipped,
        })

# ============ F11 文件版本历史 ============

class FileVersionListView(APIView):
    """版本列表：当前版本 + 历史版本（回滚后当前内容也会先存为新版本）"""

    def get(self, request, pk):
        fm = FileMeta.objects.filter(pk=pk, owner=request.user, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=404)
        rows = [
            {"version": v.version, "size": v.size, "size_text": format_size(v.size),
             "sha1": v.sha1, "created_at": v.created_at}
            for v in fm.versions.all()
        ]
        return Response({
            "file_id": fm.id,
            "current": {"name": fm.name, "size": fm.size, "size_text": format_size(fm.size),
                        "sha1": fm.sha1, "updated_at": fm.updated_at},
            "list": rows,
            "total": len(rows),
            "keep": versioning.keep_limit(),
        })


class FileVersionRestoreView(APIView):
    """回滚到指定版本（回滚前先把当前内容存成新版本）"""

    def post(self, request, pk, version):
        fm = FileMeta.objects.filter(pk=pk, owner=request.user, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=404)
        try:
            versioning.restore(fm, int(version), request.user)
        except LookupError as exc:
            return Response({"message": str(exc)}, status=404)
        except FileNotFoundError as exc:
            return Response({"message": str(exc)}, status=410)
        _index_file(fm)
        return Response({"message": f"已回滚到 v{version}", "file": FileMetaSerializer(fm).data})


# ============ F13 配额预警与清理建议 ============

class StorageAdviceView(APIView):
    """只读建议：大文件 / 最久未改动 / 重复文件，不自动删除"""

    def get(self, request):
        active = _file_qs(request.user).filter(is_deleted=False)
        used = active.aggregate(s=Sum("size"))["s"] or 0
        quota_mb = request.user.storage_quota_mb or 0
        quota_bytes = quota_mb * 1024 * 1024
        pct = round(used / quota_bytes * 100, 1) if quota_bytes else 0

        big = [
            {"id": f.id, "name": f.name, "size": f.size, "size_text": format_size(f.size)}
            for f in active.order_by("-size")[:5] if f.size > 0
        ]
        stale = [
            {"id": f.id, "name": f.name, "size": f.size, "size_text": format_size(f.size),
             "updated_at": f.updated_at}
            for f in active.order_by("updated_at")[:5]
        ]
        dup_rows = (
            active.exclude(sha1="").values("sha1")
            .annotate(count=Count("id"), total=Sum("size")).filter(count__gt=1)
            .order_by("-total")[:5]
        )
        duplicates = [
            {"sha1": row["sha1"], "count": row["count"], "wasted": row["total"] - row["total"] // row["count"],
             "wasted_text": format_size(row["total"] - row["total"] // row["count"])}
            for row in dup_rows
        ]
        level = "danger" if pct >= 90 else ("warning" if pct >= 75 else "ok")
        return Response({
            "used_bytes": used, "used_text": format_size(used),
            "quota_mb": quota_mb, "used_pct": pct, "level": level,
            "trash_bytes": _file_qs(request.user).filter(is_deleted=True).aggregate(s=Sum("size"))["s"] or 0,
            "big_files": big, "stale_files": stale, "duplicates": duplicates,
        })


# ============ F14 分享访问分析 ============

class ShareAnalyticsView(APIView):
    """分享链接访问分析：总访问 / 独立访客（IP 哈希）/ 最近 30 天趋势"""

    def get(self, request, pk):
        link = ShareLink.objects.filter(pk=pk, created_by=request.user).first()
        if not link:
            return Response({"message": "分享不存在"}, status=404)
        qs = ShareVisit.objects.filter(link=link)
        last = qs.order_by("-created_at").values_list("created_at", flat=True).first()
        by_day = list(
            qs.extra({"d": "date(created_at)"}).values("d").annotate(c=Count("id")).order_by("-d")[:30]
        )
        return Response({
            "link_id": link.id,
            "token": link.token,
            "permission": link.permission,
            "view_count": link.view_count,
            "download_count": link.download_count,
            "total_visits": qs.count(),
            "unique_visitors": qs.values("ip_hash").distinct().count(),
            "last_visit_at": last,
            "by_day": by_day,
        })


# ============ F12 文件全文检索（BM25） ============

class FileFullTextSearchView(APIView):
    """在文件名 + 正文（文本类抽取）+ 备注中检索，按 BM25 排序"""

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"list": [], "total": 0})
        try:
            limit = as_int(request.query_params.get("limit", 20), field="limit", minimum=1, maximum=100)
        except ValidationError:
            return Response({"message": "limit 必须是 1~100 的整数"}, status=400)
        from core.search import search

        res = search(q, owner_ids=[request.user.id], modules=["file"], limit=limit)
        hits = res.get("results", [])
        ids = [h["id"] for h in hits]
        files = {f.id: f for f in FileMeta.objects.filter(id__in=ids, owner=request.user, is_deleted=False)
                 .select_related("folder").prefetch_related("tags")}
        data = []
        for hit in hits:
            fm = files.get(hit["id"])
            if fm is None:
                continue
            item = FileMetaSerializer(fm).data
            item["snippet"] = hit.get("snippet", "")
            item["score"] = hit.get("score", 0)
            data.append(item)
        return Response({"list": data, "total": res.get("total", len(data))})
