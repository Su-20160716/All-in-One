"""文件管理视图：文件夹树、分片上传、断点续传、秒传、回收站、共享链接、
批量操作、在线新建/编辑、复制、收藏备注、存储分析、重复检测、最近访问、打包下载、
多类型在线预览（含 HTTP Range 流式播放）、Office 转 PDF。"""
import logging

logger = logging.getLogger(__name__)

import csv
import io
import json
import mimetypes
import os
import re
import shutil
import uuid
import zipfile
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Notification, notify
from core.pagination import OptionalPageNumberPagination
from core.quota import check_quota
from core.scoping import is_visible, scope_queryset
from core.utils import file_kind, format_size, sha1_file
from core.validators import as_int, parse_bool
from files import office
from files.models import (
    ChunkUpload,
    FileMeta,
    FileOperationLog,
    FileTag,
    FileVisibilitySnapshot,
    Folder,
    RecentFile,
    ShareLink,
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
        qs = Folder.objects.filter(owner=request.user, parent_id=parent)
        return Response({"list": FolderSerializer(qs, many=True).data, "total": qs.count()})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
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
            folder.name = request.data["name"].strip() or folder.name
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
        # B6：批量删除（一条 DELETE + 级联），替代每文件一次 delete 循环
        folder.files.all().delete()
        folder.delete()
        return Response({"message": "文件夹已删除"})


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
        # B20：序列化结果已包含全部行，len 即总数——省掉一次多余的 COUNT 查询
        # （原来 FileMetaSerializer(qs).data 与 qs.count() 是两条独立 SQL）
        data = FileMetaSerializer(qs, many=True).data
        return Response({"list": data, "total": len(data)})


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
        upload_id = request.query_params.get("upload_id")
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
        upload_id = request.data.get("upload_id")
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
        upload_id = request.data.get("upload_id")
        try:
            index = int(request.data.get("index", -1))
        except (TypeError, ValueError):
            return Response({"message": "index 必须是整数"}, status=status.HTTP_400_BAD_REQUEST)
        chunk_file = request.FILES.get("chunk")
        chunk = ChunkUpload.objects.filter(upload_id=upload_id, user=request.user).first()
        if not chunk:
            return Response({"message": "上传任务不存在"}, status=status.HTTP_404_NOT_FOUND)
        if index < 0 or index >= chunk.total_chunks:
            return Response({"message": "分块索引非法"}, status=status.HTTP_400_BAD_REQUEST)
        if index in chunk.uploaded_chunks:
            return Response({"uploaded": chunk.uploaded_chunks, "message": "该分片已上传"})
        if not chunk_file:
            return Response({"message": "缺少分片内容"}, status=status.HTTP_400_BAD_REQUEST)
        part_path = _safe_join(MEDIA, chunk.temp_dir, f"part_{index:06d}")
        with open(part_path, "wb+") as f:
            for buf in chunk_file.chunks():
                f.write(buf)
        chunk.uploaded_chunks.append(index)
        chunk.save(update_fields=["uploaded_chunks", "updated_at"])
        return Response({"uploaded": chunk.uploaded_chunks})


class UploadCompleteView(APIView):
    """合并分片 → 生成 FileMeta → 清理临时文件"""

    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        upload_id = request.data.get("upload_id")
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

        year_month = timezone.now().strftime("%Y%m")
        rel_dir = os.path.join("files", str(chunk.user_id), year_month)
        abs_dir = _safe_join(MEDIA, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        folder = Folder.objects.filter(pk=chunk.folder_id, owner=request.user).first() if chunk.folder_id else None
        base, ext = os.path.splitext(chunk.filename)
        final_rel = os.path.join(rel_dir, chunk.filename)
        final_abs = _safe_join(MEDIA, final_rel)

        def _name_taken(rel):
            """F557 重名判定：磁盘已存在 或 同目录下已有同名 FileMeta"""
            if os.path.exists(_safe_join(MEDIA, rel)):
                return True
            return FileMeta.objects.filter(
                owner=request.user, folder=folder, is_deleted=False,
                name=os.path.basename(rel),
            ).exists()

        i = 1
        while _name_taken(final_rel):
            final_rel = os.path.join(rel_dir, f"{base}({i}){ext}")
            final_abs = _safe_join(MEDIA, final_rel)
            i += 1

        with open(final_abs, "wb") as out:
            for idx in range(chunk.total_chunks):
                part = _safe_join(MEDIA, chunk.temp_dir, f"part_{idx:06d}")
                with open(part, "rb") as p:
                    shutil.copyfileobj(p, out, 1024 * 1024)

        sha1 = sha1_file(final_abs) if chunk.total_chunks > 1 else (chunk.sha1 or sha1_file(final_abs))
        storage_rel = final_rel.replace("\\", "/")
        exist = FileMeta.objects.filter(
            owner=request.user, sha1=sha1, size=chunk.file_size, is_deleted=False
        ).exclude(storage_path=storage_rel).first()
        if exist:
            os.remove(final_abs)
            storage_rel = exist.storage_path

        ext = os.path.splitext(chunk.filename)[1].lower().lstrip(".")
        thumb_rel = ""
        if file_kind(chunk.filename) == "image":
            thumb_rel = _make_thumbnail(_safe_join(MEDIA, storage_rel), ext)

        # B5：FileMeta 建档 + 任务状态置完成 + 操作流水入同一事务；
        # 临时分片目录的物理清理放 on_commit，提交后才删，避免「库回滚了、
        # 临时文件没了」导致分片无法重传
        with transaction.atomic():
            fm = FileMeta.objects.create(
                name=os.path.basename(storage_rel),
                folder=folder,
                owner=request.user,
                storage_path=storage_rel,
                size=chunk.file_size,
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
        if "name" in request.data:
            new_name = request.data["name"].strip()
            if not new_name:
                return Response({"message": "文件名不能为空"}, status=status.HTTP_400_BAD_REQUEST)
            old_name = fm.name
            fm.name = new_name
            fields.append("name")
            if old_name != new_name:
                _log_op(request.user, fm, "rename", detail=f"{old_name} → {new_name}",
                        from_folder=from_folder_old, to_folder=from_folder_old)
        if "folder" in request.data:
            new_folder_id = request.data.get("folder")
            if new_folder_id in (None, "", "null"):
                fm.folder = None
            else:
                new_folder = Folder.objects.filter(pk=new_folder_id, owner=request.user).first()
                if not new_folder:
                    return Response({"message": "目标文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
                fm.folder = new_folder
            fields.append("folder")
            _log_op(request.user, fm, "move", from_folder=from_folder_old,
                    to_folder=_folder_label(fm.folder))
        if "is_star" in request.data:
            fm.is_star = parse_bool(request.data["is_star"], field="is_star")
            fields.append("is_star")
        if "description" in request.data:
            fm.description = request.data["description"][:500]
            fields.append("description")
        if fields:
            fields.append("updated_at")
            fm.save(update_fields=fields)
        return Response(FileMetaSerializer(fm).data)

    def delete(self, request, pk):
        fm = self.get_object(request, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        fm.is_deleted = True
        fm.deleted_at = timezone.now()
        fm.origin_folder_id = fm.folder_id
        fm.save(update_fields=["is_deleted", "deleted_at", "origin_folder_id"])
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
    """批量操作：move / trash / restore / star / unstar / delete_forever / copy"""

    def post(self, request):
        action = request.data.get("action")
        ids = request.data.get("file_ids") or []
        if not ids:
            return Response({"message": "未选择文件"}, status=400)
        qs = FileMeta.objects.filter(owner=request.user, id__in=ids)
        if action == "trash":
            n = 0
            for fm in qs:
                fm.is_deleted = True
                fm.deleted_at = timezone.now()
                fm.origin_folder_id = fm.folder_id
                fm.save(update_fields=["is_deleted", "deleted_at", "origin_folder_id"])
                n += 1
            return Response({"message": f"已将 {n} 个文件移入回收站"})
        if action == "move":
            folder = _owner_folder(request.user, request.data.get("folder"))
            if request.data.get("folder") not in (None, "", "null", "0", 0) and not folder:
                return Response({"message": "目标文件夹不存在"}, status=404)
            n = 0
            for fm in qs:
                src = _folder_label(fm.folder)
                fm.folder = folder
                fm.save(update_fields=["folder", "updated_at"])
                _log_op(request.user, fm, "move", from_folder=src, to_folder=_folder_label(folder))
                n += 1
            return Response({"message": f"已移动 {n} 个文件"})
        if action == "star":
            n = qs.update(is_star=True)
            return Response({"message": f"已收藏 {n} 个文件"})
        if action == "unstar":
            n = qs.update(is_star=False)
            return Response({"message": f"已取消收藏 {n} 个文件"})
        if action == "delete_forever":
            n = 0
            for fm in qs:
                self._remove_physical(fm)
                fm.delete()
                n += 1
            return Response({"message": f"已彻底删除 {n} 个文件"})
        return Response({"message": "未知操作"}, status=400)

    @staticmethod
    def _remove_physical(fm):
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if os.path.exists(abs_path):
            # 仅当没有其它元数据引用同一物理文件时才删除
            if FileMeta.objects.filter(storage_path=fm.storage_path).exclude(pk=fm.pk).count() == 0:
                try:
                    os.remove(abs_path)
                except OSError:
                    pass


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


class FileCreateTextView(APIView):
    """在线新建文本文件"""

    def post(self, request):
        name = (request.data.get("name") or "新建文本.txt").strip()
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
        content = request.data.get("content", "")
        abs_path = _safe_join(MEDIA, fm.storage_path)
        data = content.encode("utf-8")
        with open(abs_path, "wb") as f:
            f.write(data)
        import hashlib
        fm.size = len(data)
        fm.sha1 = hashlib.sha1(data).hexdigest()
        fm.save(update_fields=["size", "sha1", "updated_at"])
        return Response({"message": "已保存", "file": FileMetaSerializer(fm).data})


class FileBatchDownloadView(APIView):
    """多个文件打包成 zip 下载"""

    def post(self, request):
        ids = request.data.get("file_ids") or []
        files = FileMeta.objects.filter(owner=request.user, id__in=ids, is_deleted=False)
        if not files:
            return Response({"message": "没有可下载的文件"}, status=400)
        buf = io.BytesIO()
        used = set()
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
        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = "attachment; filename=files.zip"
        return resp


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
        if fm.owner_id != request.user.id:
            token = request.query_params.get("share") or request.query_params.get("token")
            if not token:
                return Response(
                    # 1016 是登录锁定专用码（accounts LoginView），
                    # 分享下载场景复用会污染前端锁定提示，这里用 1011 无操作权限。
                    {"message": "非本人文件，需通过共享链接下载", "code": 1011},
                    status=status.HTTP_403_FORBIDDEN,
                )
            link = find_link(token, file_id=fm.pk)
            try:
                validate_link(link, request.query_params.get("password", ""), for_download=True)
            except ShareAccessError as exc:
                return exc.as_response()
            if not bump_download(link):
                return Response({"message": "下载次数已达上限"}, status=status.HTTP_403_FORBIDDEN)
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
        fm = _get_file(request.user, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(abs_path):
            return Response({"message": "物理文件缺失"}, status=status.HTTP_404_NOT_FOUND)

        total = os.path.getsize(abs_path)
        content_type = self._content_type(fm, abs_path)
        range_header = request.headers.get("Range") or request.META.get("HTTP_RANGE", "")

        # 仅对可预览类型开放内联，其他类型强制下载，避免把可执行文件当页面渲染
        disposition = "inline" if fm.preview_type != "none" else "attachment"
        filename = re.sub(r'[\\/:*?"<>|\r\n]', "_", fm.name)

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
        resp["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{filename}"
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
        fm = _get_file(request.user, pk)
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)

        rel = fm.pdf_path if fm.preview_type == "office" else fm.storage_path
        if not rel:
            return Response({"message": "尚未生成 PDF，请先调用转换接口", "code": "NOT_CONVERTED"},
                            status=status.HTTP_409_CONFLICT)
        abs_path = _safe_join(MEDIA, rel)
        if not os.path.exists(abs_path):
            return Response({"message": "PDF 文件缺失，请重新转换", "code": "FILE_MISSING"}, status=404)

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
        qs = RecentFile.objects.filter(owner=request.user).select_related("file").filter(file__is_deleted=False)[:30]
        data = [FileMetaSerializer(r.file).data for r in qs]
        return Response({"list": data, "total": len(data)})

    def delete(self, request):
        RecentFile.objects.filter(owner=request.user).delete()
        return Response({"message": "已清空最近访问"})


class StarredFileView(APIView):
    """收藏的文件：支持 ?group= 按收藏分组筛选，并返回分组聚合；按 favorite_order 自定义排序"""

    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=False, is_star=True)
        group = request.query_params.get("group")
        if group is not None and group != "":
            qs = qs.filter(favorite_group=group)
        qs = qs.order_by("favorite_order", "-updated_at", "-created_at")
        groups = list(_file_qs(request.user).filter(is_deleted=False, is_star=True)
                      .values("favorite_group").annotate(c=Count("id")))
        return Response({"list": FileMetaSerializer(qs, many=True).data,
                         "total": qs.count(), "groups": groups})


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


# ============ 回收站 ============

class TrashListView(APIView):
    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=True).order_by("-deleted_at")
        return Response({"list": FileMetaSerializer(qs, many=True).data, "total": qs.count()})


class TrashActionView(APIView):
    """回收站：restore 恢复（还原到删除前目录）/ delete 彻底删除 / empty 清空"""

    def post(self, request):
        action = request.data.get("action", "restore")
        ids = request.data.get("file_ids") or []
        qs = FileMeta.objects.filter(owner=request.user, is_deleted=True)
        if ids:
            qs = qs.filter(id__in=ids)
        if action == "restore":
            count = 0
            for fm in qs:
                # 原目录已被删除则回到根目录
                if fm.origin_folder_id and not Folder.objects.filter(pk=fm.origin_folder_id, owner=request.user).exists():
                    fm.folder = None
                else:
                    fm.folder_id = fm.origin_folder_id
                fm.is_deleted = False
                fm.deleted_at = None
                fm.save(update_fields=["folder", "is_deleted", "deleted_at"])
                count += 1
            return Response({"message": f"已恢复 {count} 个文件"})
        if action in ("delete", "empty"):
            count = 0
            for fm in qs:
                FileBatchView._remove_physical(fm)
                if fm.thumbnail_path and os.path.exists(_safe_join(MEDIA, fm.thumbnail_path)):
                    try:
                        os.remove(_safe_join(MEDIA, fm.thumbnail_path))
                    except OSError:
                        pass
                fm.delete()
                count += 1
            word = "彻底删除" if action == "delete" else "清空"
            return Response({"message": f"已{word} {count} 个文件"})
        return Response({"message": "未知操作"}, status=status.HTTP_400_BAD_REQUEST)


class TrashAutoCleanView(APIView):
    """清理超过保留期的回收站文件（按 TRASH_KEEP_DAYS，可传 days 覆盖）"""

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
        count = 0
        for fm in qs:
            FileBatchView._remove_physical(fm)
            fm.delete()
            count += 1
        return Response({"message": f"已清理 {count} 个过期回收文件", "cleaned": count, "days": days})

    def get(self, request):
        """返回当前清理配置"""
        from django.conf import settings as s
        return Response({"trash_keep_days": getattr(s, "TRASH_KEEP_DAYS", 30)})


# ============ 共享链接 ============

class ShareLinkCreateView(APIView):
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
            hours = int(expire_hours) if expire_hours not in (None, "") else None
            mlimit = int(max_downloads) if max_downloads not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            return Response({"message": "expire_hours / max_downloads 必须是整数"}, status=400)

        target = None
        if file_id:
            target = FileMeta.objects.filter(pk=file_id, owner=request.user).first()
            if not target:
                return Response({"message": "文件不存在"}, status=404)
        elif folder_id:
            target = Folder.objects.filter(pk=folder_id, owner=request.user).first()
            if not target:
                return Response({"message": "文件夹不存在"}, status=404)
        else:
            return Response({"message": "请指定文件或文件夹"}, status=400)

        token = uuid.uuid4().hex[:16]
        expire_at = timezone.now() + timedelta(hours=hours) if hours else None
        link = ShareLink.objects.create(
            token=token,
            file=target if isinstance(target, FileMeta) else None,
            folder=target if isinstance(target, Folder) else None,
            created_by=request.user,
            permission=permission,
            expire_at=expire_at,
            password=password[:64],
            max_downloads=mlimit,
        )
        if link.file:
            _record_visibility(link.file, request.user, note="创建共享链接", action="share_create")
        return Response(ShareLinkSerializer(link).data, status=201)


class ShareLinkListView(APIView):
    """我创建的共享链接，支持类型 / 状态筛选"""

    def get(self, request):
        qs = ShareLink.objects.filter(created_by=request.user).order_by("-created_at")
        st = request.query_params.get("status")
        if st == "expired":
            qs = [l for l in qs if l.is_expired]
        elif st == "active":
            qs = [l for l in qs if not l.is_expired]
        ttype = request.query_params.get("type")
        if ttype == "file":
            qs = [l for l in qs if l.file_id]
        elif ttype == "folder":
            qs = [l for l in qs if l.folder_id]
        data = ShareLinkSerializer(qs, many=True).data
        return Response({"list": data, "total": len(data)})


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
            link.password = request.data["password"] or ""
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
            validate_link(link, request.query_params.get("password", ""))
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
                info["url"] = fm.url
                info["thumbnail"] = fm.thumbnail_url
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
            files = link.folder.files.filter(is_deleted=False)
            return Response({
                "type": "folder", "name": link.folder.name, "permission": link.permission,
                "files": FileMetaSerializer(files, many=True).data,
            })
        return Response({"message": "链接异常"}, status=404)


class ShareDownloadView(APIView):
    """通过共享链接下载（计数 + 上限 + 密码）"""

    permission_classes = [AllowAny]

    def get(self, request, token, pk):
        link = find_link(token, file_id=pk)
        try:
            validate_link(link, request.query_params.get("password", ""), for_download=True)
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
        return FileResponse(open(abs_path, "rb"), as_attachment=True, filename=fm.name)


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
        if "name" in request.data and request.data["name"].strip():
            tag.name = request.data["name"].strip()[:50]
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


class FileBatchTagView(APIView):
    """给一批文件打标签 / 移除标签（add / remove / set）"""

    def post(self, request):
        action = request.data.get("action", "set")
        ids = request.data.get("file_ids") or []
        names = request.data.get("tags") or []
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
        ids = request.data.get("file_ids") or []
        mode = request.data.get("mode", "prefix")
        if not ids:
            return Response({"message": "未选择文件"}, status=status.HTTP_400_BAD_REQUEST)
        qs = list(FileMeta.objects.filter(owner=request.user, id__in=ids, is_deleted=False))
        if not qs:
            return Response({"message": "没有可重命名的文件"}, status=400)
        try:
            start = int(request.data.get("start", 1))
            pad = int(request.data.get("pad", 2))
        except (TypeError, ValueError):
            return Response({"message": "start / pad 必须是整数"}, status=400)
        prefix = request.data.get("prefix", "") or ""
        find = request.data.get("find", "") or ""
        repl = request.data.get("replace", "") or ""
        results = []
        for idx, fm in enumerate(qs):
            base, ext = os.path.splitext(fm.name)
            if mode == "replace":
                new_base = base.replace(find, repl) if find else base
                new_name = f"{new_base}{ext}"
            else:
                new_name = f"{prefix}{str(start + idx).zfill(pad)}_{fm.name}"
            new_name = new_name[:255]
            if new_name and new_name != fm.name:
                fm.name = new_name
                fm.save(update_fields=["name", "updated_at"])
            results.append({"id": fm.id, "name": fm.name})
        return Response({"message": f"已重命名 {len(results)} 个文件", "renamed": results})


class FolderTemplatesView(APIView):
    """内置文件夹模板清单"""

    def get(self, request):
        return Response({"list": FOLDER_TEMPLATES, "total": len(FOLDER_TEMPLATES)})


class FolderFromTemplateView(APIView):
    """从模板一键递归创建文件夹。

    入参：{"key": "project-docs"} 或 {"structure": {"子目录": ["孙目录", ...]}, "parent": 0}
    """

    def post(self, request):
        parent = _owner_folder(request.user, request.data.get("parent"))
        structure = request.data.get("structure")
        if not structure:
            key = request.data.get("key")
            tpl = next((t for t in FOLDER_TEMPLATES if t["key"] == key), None)
            if not tpl:
                return Response({"message": "模板不存在"}, status=404)
            structure = tpl["structure"]
        created = []

        def walk(node_structure, parent_node):
            if isinstance(node_structure, dict):
                for name, children in node_structure.items():
                    folder = Folder.objects.create(
                        name=str(name), parent=parent_node, owner=request.user
                    )
                    created.append(folder.name)
                    walk(children, folder)
            elif isinstance(node_structure, list):
                for item in node_structure:
                    if isinstance(item, dict):
                        walk(item, parent_node)
                    else:
                        folder = Folder.objects.create(
                            name=str(item), parent=parent_node, owner=request.user
                        )
                        created.append(folder.name)

        walk(structure, parent)
        return Response({"message": f"已创建 {len(created)} 个文件夹", "created": created, "count": len(created)})


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
    """F547 重复文件检测：按 sha1 分组，返回每组文件明细与可释放空间"""

    def get(self, request):
        try:
            limit = _int_param(request, "limit", 100, lo=1, hi=500)
        except ValueError as e:
            return _bad(str(e))
        active = _file_qs(request.user).filter(is_deleted=False).exclude(sha1="").exclude(size=0)
        dup = (active.values("sha1").annotate(c=Count("id")).filter(c__gt=1)
               .order_by("-c")[:limit])
        groups, wasted, file_count = [], 0, 0
        for g in dup:
            files = list(active.filter(sha1=g["sha1"]).order_by("-created_at"))
            size = files[0].size if files else 0
            w = size * (g["c"] - 1)
            wasted += w
            file_count += g["c"]
            groups.append({
                "sha1": g["sha1"], "count": g["c"], "size": size,
                "size_text": format_size(size), "wasted": w, "wasted_text": format_size(w),
                "files": FileMetaSerializer(files, many=True).data,
            })
        return Response({
            "groups": groups, "group_count": len(groups), "file_count": file_count,
            "wasted_bytes": wasted, "wasted_text": format_size(wasted),
        })


class StorageTrendView(APIView):
    """F548 存储体积 30 天趋势：由文件创建/删除时间重建逐日曲线（前端渲染 SVG）"""

    def get(self, request):
        try:
            days = _int_param(request, "days", 30, lo=7, hi=90)
        except ValueError as e:
            return _bad(str(e))
        rows = _file_qs(request.user).values_list("created_at", "size", "deleted_at")
        events = {}
        for created, size, deleted in rows:
            if not created:
                continue
            size = size or 0
            cd = timezone.localtime(created).date()
            events[cd] = events.get(cd, 0) + size
            if deleted:
                dd = timezone.localtime(deleted).date()
                events[dd] = events.get(dd, 0) - size
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
        qs = qs.order_by("-created_at")
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["ID", "文件名", "文件夹", "类型", "扩展名", "大小(字节)", "大小",
                         "SHA1", "标签", "备注", "收藏", "创建时间", "更新时间"])
        for fm in qs.iterator():
            try:
                tag_names = ",".join(fm.tags.values_list("name", flat=True))
            except Exception:
                tag_names = ""
            writer.writerow([
                fm.id, fm.name, _folder_label(fm.folder), fm.kind, fm.ext, fm.size,
                format_size(fm.size), fm.sha1, tag_names, fm.description,
                "是" if fm.is_star else "",
                timezone.localtime(fm.created_at).strftime("%Y-%m-%d %H:%M") if fm.created_at else "",
                timezone.localtime(fm.updated_at).strftime("%Y-%m-%d %H:%M") if fm.updated_at else "",
            ])
        resp = HttpResponse("\ufeff" + buf.getvalue(), content_type="text/csv; charset=utf-8")
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
    """F555 收藏夹自定义排序：按传入顺序写入 favorite_order"""

    def post(self, request):
        ids = request.data.get("file_ids")
        if not isinstance(ids, list) or not ids:
            return _bad("file_ids 必须是非空数组")
        n = 0
        for idx, fid in enumerate(ids, start=1):
            try:
                fid = int(fid)
            except (TypeError, ValueError):
                continue
            n += FileMeta.objects.filter(pk=fid, owner=request.user, is_star=True) \
                .update(favorite_order=idx)
        return Response({"message": f"已更新 {n} 个收藏的排序", "updated": n})


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


class ShareExpiringView(APIView):
    """F560 分享链接到期前提醒（默认 3 天窗口），同时推送站内通知（去重）"""

    def get(self, request):
        try:
            days = _int_param(request, "days", 3, lo=1, hi=60)
        except ValueError as e:
            return _bad(str(e))
        now = timezone.now()
        horizon = now + timedelta(days=days)
        links = ShareLink.objects.filter(
            created_by=request.user, is_revoked=False,
            expire_at__isnull=False, expire_at__gte=now, expire_at__lte=horizon,
        ).select_related("file", "folder").order_by("expire_at")
        items, notified = [], 0
        for link in links:
            hours = (link.expire_at - now).total_seconds() / 3600
            name = link.file.name if link.file else (link.folder.name if link.folder else "")
            items.append({
                "token": link.token, "url": f"/share/{link.token}",
                "target": name, "target_type": "file" if link.file else "folder",
                "permission": link.permission, "expire_at": link.expire_at,
                "hours_left": round(hours, 1), "days_left": max(1, int((hours + 23) // 24)),
            })
            # 同一到期窗口内只提醒一次
            already = Notification.objects.filter(
                recipient=request.user, content__contains=link.token,
                created_at__gte=link.expire_at - timedelta(days=days + 2),
            ).exists()
            if not already:
                notify(
                    request.user,
                    f"分享链接「{name}」即将过期",
                    content=f"链接 /share/{link.token} 将于 {link.expire_at:%Y-%m-%d %H:%M} 过期（{int(hours)} 小时后）。",
                    category="files", level="warning", link="/files/shares",
                )
                notified += 1
        return Response({"days": days, "list": items, "total": len(items), "notified": notified})


class FileVisibilityView(APIView):
    """F561 文件可见性快照：GET 当前状态 + 历史快照；POST 手动补记一条"""

    def _get(self, request, pk):
        return _get_file(request.user, pk, include_deleted=True)

    def get(self, request, pk):
        fm = self._get(request, pk)
        if not fm:
            return _bad("文件不存在", 404)
        state = _visibility_state(fm)
        labels = dict(FileVisibilitySnapshot.VISIBILITY_CHOICES)
        history = [{
            "id": s.id, "visibility": s.visibility,
            "visibility_label": labels.get(s.visibility, s.visibility),
            "data_scope": s.data_scope, "share_token": s.share_token,
            "permission": s.permission, "expire_at": s.expire_at,
            "note": s.note, "created_at": s.created_at,
            "recorded_by": (getattr(s.created_by, "display_name", "")
                            or getattr(s.created_by, "username", "")) if s.created_by else "",
        } for s in FileVisibilitySnapshot.objects.filter(file=fm)[:50]]
        state["history"] = history
        state["history_count"] = len(history)
        state["can_write"] = fm.owner_id == request.user.id
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
    """F563 标签统计与点击过滤（过滤由 /files/?tag= 承接）"""

    def get(self, request):
        base = _file_qs(request.user).filter(is_deleted=False)
        total_bytes = base.aggregate(s=Sum("size"))["s"] or 0
        total_count = base.count()
        items = []
        for t in FileTag.objects.filter(owner=request.user).annotate(
                c=Count("files", filter=Q(files__is_deleted=False))).order_by("-c", "name"):
            files = base.filter(tags=t)
            b = files.aggregate(s=Sum("size"))["s"] or 0
            cnt = t.c or 0
            items.append({
                "id": t.id, "name": t.name, "color": t.color, "count": cnt,
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
    """F564 收藏/标签导出 JSON（浏览器直接下载）"""

    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=False, is_star=True) \
            .order_by("favorite_order", "-created_at")
        files = [{
            "id": f.id, "name": f.name, "folder": _folder_label(f.folder),
            "group": f.favorite_group, "star": True,
            "tags": list(f.tags.values_list("name", flat=True)),
            "size": f.size, "sha1": f.sha1,
            "created_at": f.created_at.isoformat() if f.created_at else "",
        } for f in qs]
        tags = [{"name": t.name, "color": t.color} for t in FileTag.objects.filter(owner=request.user)]
        payload = {
            "type": "files-favorites", "version": 1,
            "exported_at": timezone.now().isoformat(),
            "file_count": len(files), "tag_count": len(tags),
            "files": files, "tags": tags,
        }
        resp = HttpResponse(json.dumps(payload, ensure_ascii=False, indent=2),
                            content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = "attachment; filename=file_favorites.json"
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

        existing = list(_file_qs(request.user).filter(is_deleted=False))
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