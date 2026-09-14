"""文件管理视图：文件夹树、分片上传、断点续传、秒传、回收站、共享链接、
批量操作、在线新建/编辑、复制、收藏备注、存储分析、重复检测、最近访问、打包下载、
多类型在线预览（含 HTTP Range 流式播放）、Office 转 PDF。"""
import io
import mimetypes
import os
import re
import shutil
import uuid
import zipfile
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.http import FileResponse, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import notify
from core.scoping import is_visible, scope_queryset
from core.utils import file_kind, format_size, sha1_file
from files import office
from files.models import ChunkUpload, FileMeta, Folder, RecentFile, ShareLink
from files.serializers import (
    ChunkInitSerializer,
    FileMetaSerializer,
    FolderSerializer,
    ShareLinkSerializer,
)

MEDIA = settings.MEDIA_ROOT


def _safe_join(base, *paths):
    target = os.path.realpath(os.path.join(base, *paths))
    if not target.startswith(os.path.realpath(base)):
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
        pass


def _owner_folder(user, folder_id):
    if folder_id in (None, "", "null", "0", 0):
        return None
    return Folder.objects.filter(pk=folder_id, owner=user).first()


# ============ 文件夹 ============

class FolderListView(APIView):
    """文件夹列表：?parent= 根目录为 null；支持新建、颜色"""

    def get(self, request):
        parent = request.query_params.get("parent")
        parent = None if parent in (None, "", "null", "0") else int(parent)
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
        def build(parent_id):
            qs = Folder.objects.filter(owner=request.user, parent_id=parent_id).order_by("name")
            return [{
                "id": f.id, "name": f.name, "color": f.color, "parent": f.parent_id,
                "children": build(f.id),
            } for f in qs]
        return Response({"tree": build(None)})


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
            if new_parent_id in (None, "", "null"):
                folder.parent = None
            else:
                new_parent = Folder.objects.filter(pk=new_parent_id, owner=request.user).first()
                if not new_parent:
                    return Response({"message": "目标文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
                if new_parent.pk == folder.pk:
                    return Response({"message": "不能移动到自身"}, status=status.HTTP_400_BAD_REQUEST)
                folder.parent = new_parent
        folder.save()
        return Response(FolderSerializer(folder).data)

    def delete(self, request, pk):
        folder = self.get_object(request, pk)
        if not folder:
            return Response({"message": "文件夹不存在"}, status=status.HTTP_404_NOT_FOUND)
        # 物理删除文件与目录
        for f in folder.files.all():
            f.delete()
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
            qs = qs.filter(folder_id=folder_id)
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
        sort = request.query_params.get("sort", "-created_at")
        allowed = {
            "name", "-name", "size", "-size", "created_at", "-created_at",
            "updated_at", "-updated_at", "kind", "-kind",
        }
        qs = qs.order_by("-is_star", sort if sort in allowed else "-created_at")
        return Response({"list": FileMetaSerializer(qs, many=True).data, "total": qs.count()})


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
        index = int(request.data.get("index", -1))
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

        year_month = timezone.now().strftime("%Y%m")
        rel_dir = os.path.join("files", str(chunk.user_id), year_month)
        abs_dir = _safe_join(MEDIA, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        base, ext = os.path.splitext(chunk.filename)
        final_rel = os.path.join(rel_dir, chunk.filename)
        final_abs = _safe_join(MEDIA, final_rel)
        i = 1
        while os.path.exists(final_abs):
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

        folder = Folder.objects.filter(pk=chunk.folder_id, owner=request.user).first() if chunk.folder_id else None
        ext = os.path.splitext(chunk.filename)[1].lower().lstrip(".")
        thumb_rel = ""
        if file_kind(chunk.filename) == "image":
            thumb_rel = _make_thumbnail(_safe_join(MEDIA, storage_rel), ext)

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
        shutil.rmtree(_safe_join(MEDIA, chunk.temp_dir), ignore_errors=True)
        return Response({"message": "上传完成", "file": FileMetaSerializer(fm).data})


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
        if "name" in request.data:
            new_name = request.data["name"].strip()
            if not new_name:
                return Response({"message": "文件名不能为空"}, status=status.HTTP_400_BAD_REQUEST)
            fm.name = new_name
            fields.append("name")
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
        if "is_star" in request.data:
            fm.is_star = bool(request.data["is_star"])
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
            n = qs.update(folder=folder)
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
        while os.path.exists(_safe_join(MEDIA, rel)):
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
    """下载文件（记录日志与最近访问，支持共享链接内网访问）"""

    def get(self, request, pk):
        fm = FileMeta.objects.filter(pk=pk, is_deleted=False).first()
        if not fm:
            return Response({"message": "文件不存在"}, status=status.HTTP_404_NOT_FOUND)
        if fm.owner_id != request.user.id:
            allowed = ShareLink.objects.filter(file=fm, permission__in=["download", "edit"], is_revoked=False).filter(
                Q(expire_at__isnull=True) | Q(expire_at__gt=timezone.now())
            ).exists()
            if not allowed:
                return Response({"message": "无权下载"}, status=status.HTTP_403_FORBIDDEN)
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
        return self._convert(request, pk, force=bool(request.data.get("force")))

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
    """收藏的文件"""

    def get(self, request):
        qs = _file_qs(request.user).filter(is_deleted=False, is_star=True)
        return Response({"list": FileMetaSerializer(qs, many=True).data, "total": qs.count()})


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
    """清理超过保留期的回收站文件（按 TRASH_KEEP_DAYS）"""

    def post(self, request):
        from django.conf import settings as s
        days = s.TRASH_KEEP_DAYS
        threshold = timezone.now() - timedelta(days=days)
        qs = FileMeta.objects.filter(owner=request.user, is_deleted=True, deleted_at__lt=threshold)
        count = 0
        for fm in qs:
            FileBatchView._remove_physical(fm)
            fm.delete()
            count += 1
        return Response({"message": f"已清理 {count} 个过期回收文件", "cleaned": count})


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
        expire_at = timezone.now() + timedelta(hours=int(expire_hours)) if expire_hours else None
        link = ShareLink.objects.create(
            token=token,
            file=target if isinstance(target, FileMeta) else None,
            folder=target if isinstance(target, Folder) else None,
            created_by=request.user,
            permission=permission,
            expire_at=expire_at,
            password=password[:64],
            max_downloads=int(max_downloads) if max_downloads not in (None, "", 0, "0") else None,
        )
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
            link.permission = request.data["permission"]
        if "password" in request.data:
            link.password = request.data["password"] or ""
        if "max_downloads" in request.data:
            v = request.data["max_downloads"]
            link.max_downloads = int(v) if v not in (None, "", 0, "0") else None
        if "expire_hours" in request.data:
            eh = request.data["expire_hours"]
            link.expire_at = timezone.now() + timedelta(hours=int(eh)) if eh else None
        if "is_revoked" in request.data:
            link.is_revoked = bool(request.data["is_revoked"])
        link.save()
        return Response(ShareLinkSerializer(link).data)

    def delete(self, request, token):
        link = self._get(request, token)
        if not link:
            return Response({"message": "链接不存在"}, status=404)
        link.delete()
        return Response({"message": "链接已撤销"})


class ShareAccessView(APIView):
    """公开访问共享链接（AllowAny）：密码校验 + 浏览计数"""

    permission_classes = [AllowAny]

    def get(self, request, token):
        link = ShareLink.objects.filter(token=token).first()
        if not link or link.is_revoked:
            return Response({"message": "链接不存在或已失效"}, status=404)
        if link.expire_at and link.expire_at < timezone.now():
            return Response({"message": "链接已过期"}, status=410)
        if link.password and request.query_params.get("password", "") != link.password:
            return Response({"need_password": True, "message": "请输入访问密码"}, status=401)
        link.view_count += 1
        link.save(update_fields=["view_count"])
        if link.file:
            fm = link.file
            info = {
                "type": "file", "name": fm.name, "size": fm.size, "kind": fm.kind,
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
        link = ShareLink.objects.filter(token=token, file_id=pk).first()
        if not link or link.is_revoked:
            return Response({"message": "链接不存在"}, status=404)
        if link.expire_at and link.expire_at < timezone.now():
            return Response({"message": "链接已过期"}, status=410)
        if link.password and request.query_params.get("password", "") != link.password:
            return Response({"need_password": True, "message": "请输入访问密码"}, status=401)
        if link.permission not in ("download", "edit"):
            return Response({"message": "当前链接不允许下载"}, status=403)
        if link.max_downloads is not None and link.download_count >= link.max_downloads:
            return Response({"message": "下载次数已达上限"}, status=403)
        fm = link.file
        abs_path = _safe_join(MEDIA, fm.storage_path)
        if not os.path.exists(abs_path):
            return Response({"message": "物理文件缺失"}, status=404)
        link.download_count += 1
        link.save(update_fields=["download_count"])
        return FileResponse(open(abs_path, "rb"), as_attachment=True, filename=fm.name)
