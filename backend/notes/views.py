"""笔记视图：CRUD、标签、搜索、版本历史/对比/回滚、分享、回收站、批量、导出、大纲、模板、统计、双链
+ F565–F582：字数目标/日记/未链接提及/随机回顾/健康度/置顶/颜色/来源/片段库/合并/拆分/
  生词联动/周回顾/待办抽取/引用格式/分组文件夹"""
import logging

logger = logging.getLogger(__name__)

import calendar
import io
import random
import re
import tempfile
import uuid
import zipfile
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q, Sum
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import OptionalPageNumberPagination
from core.scoping import is_visible, owner_qs, scope_queryset
from core.validators import as_datetime, as_int, parse_bool
from notes import links as link_lib
from notes.models import (
    Note, NoteAttachment, NoteComment, NoteFolder, NoteLink, NoteSnippet, NoteTag, NoteTemplate,
    NoteVersion, WordActivity, WritingGoal,
)
from notes.serializers import (
    NoteAttachmentSerializer, NoteCommentSerializer, NoteSerializer, NoteTagSerializer,
    NoteTemplateSerializer, NoteVersionSerializer,
)

# F572 六色标记（名称固定，前端按同名渲染）
NOTE_COLORS = {
    "red": "红", "orange": "橙", "yellow": "黄",
    "green": "绿", "blue": "蓝", "purple": "紫",
}

# F573 笔记来源标签
SOURCE_LABELS = {
    "manual": "手动创建", "template": "模板创建", "import": "批量导入",
    "copy": "复制副本", "link": "双链创建", "split": "拆分生成", "merge": "合并生成",
    # F246 快速记录
    "quick": "速记",
}

# #51 单篇笔记最多保留的版本快照数（超出按 version 升序删最旧的）
NOTE_VERSION_KEEP = 50


def _prune_note_versions(note, keep=NOTE_VERSION_KEEP):
    """#51：版本快照只留最近 N 条，避免每次保存都 +1 导致无限增长。"""
    qs = NoteVersion.objects.filter(note=note).order_by("version")
    total = qs.count()
    if total <= keep:
        return 0
    stale_ids = list(qs.values_list("id", flat=True)[: total - keep])
    return NoteVersion.objects.filter(id__in=stale_ids).delete()[0]


def _note_qs(user):
    """按数据范围取可见笔记（管理员=全部、部门负责人=本部门、普通用户=本人）

    注意：只用于**读**。写操作请用 `_note_write_qs`，否则部门/全平台范围
    会连带把他人笔记变成可改可删。
    F18：未到 publish_at 的定时笔记只对作者本人可见。
    """
    qs = scope_queryset(Note.objects.all(), user)
    now = timezone.now()
    return qs.filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now) | Q(owner=user))


def _note_write_qs(user):
    """写操作范围：仅本人笔记（owner 收口）。"""
    return owner_qs(Note.objects.all(), user)


def _get_note(user, pk, include_deleted=False, write=False):
    """单篇笔记取用：详情/更新/导出统一入口。

    :param write: True 表示用于修改/删除，按 owner 限定，不看读范围
    """
    qs = _note_write_qs(user) if write else _note_qs(user)
    note = qs.filter(pk=pk).first()
    if note is None:
        return None
    if not include_deleted and note.is_deleted and note.owner_id != getattr(user, "id", None):
        return None
    return note


def count_words(text: str) -> int:
    """中文字符按字计，英文按空白分词"""
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    return cjk + words


def bump_words_activity(user, delta: int):
    """F565 累计当日写作增量（只记正向新增，异常不阻断保存）

    #53：原来「读 row.delta → 加 → 写回」在并发保存下互相覆盖、累计偏小。
    改为数据库端 `delta = delta + %s` 原子更新（WordActivity 只存当日 delta，
    跨日总量由 SUM(delta) 得出，因此无需再同步 total 字段）。
    """
    if not user or not getattr(user, "is_authenticated", False) or delta <= 0:
        return
    try:
        today = timezone.localdate()
        WordActivity.objects.get_or_create(owner=user, date=today)
        WordActivity.objects.filter(owner=user, date=today).update(delta=F("delta") + int(delta))
    except Exception:
        logger.exception("B23：静默兜底已登记（notes/views.py:86 原为 pass）——review 是否应收窄异常类型")


def _folder_of(user, folder_id):
    """F582 取本人的笔记文件夹；0/空 → None；非法 id → None（避免 500）"""
    if folder_id in (None, "", "null", "0", 0):
        return None
    try:
        folder_id = int(folder_id)
    except (TypeError, ValueError):
        return None
    return NoteFolder.objects.filter(pk=folder_id, owner=user).first()


def _file_of(user, file_id):
    """F237/F239 取本人的文件（附件/封面共用）；0/空 → None；非本人或已删 → None"""
    if file_id in (None, "", "null", "0", 0):
        return None
    try:
        file_id = int(file_id)
    except (TypeError, ValueError):
        return None
    from files.models import FileMeta

    return FileMeta.objects.filter(pk=file_id, owner=user, is_deleted=False).first()


def _would_create_cycle(node, new_parent):
    """把 node 挂到 new_parent 下是否会形成环：沿 new_parent 祖先链上溯，遇到 node 即成环。
    node / new_parent 均需为同一模型（Note 或 NoteFolder）的实例。"""
    cursor = new_parent
    guard = 0
    while cursor is not None and guard < 100:
        if cursor.pk == node.pk:
            return True
        cursor = cursor.parent
        guard += 1
    return False


def extract_outline(text: str):
    """从 Markdown 提取标题目录"""
    outline = []
    for line in (text or "").splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if m:
            outline.append({"level": len(m.group(1)), "title": m.group(2).strip()})
    return outline


# 内置笔记模板
NOTE_TEMPLATES = [
    {"key": "blank", "name": "空白笔记", "title": "未命名笔记", "content": ""},
    {"key": "meeting", "name": "会议纪要", "title": "会议纪要",
     "content": "# 会议纪要\n\n**时间**：\n**参会人**：\n\n## 议题\n\n## 讨论要点\n\n## 行动项\n- [ ] \n"},
    {"key": "todo", "name": "待办清单", "title": "待办清单",
     "content": "# 待办清单\n\n## 今日\n- [ ] \n\n## 本周\n- [ ] \n"},
    {"key": "plan", "name": "项目计划", "title": "项目计划",
     "content": "# 项目计划\n\n## 目标\n\n## 里程碑\n1. \n\n## 风险\n\n"},
    {"key": "summary", "name": "周报", "title": "工作周报",
     "content": "# 工作周报\n\n## 本周完成\n\n## 进行中\n\n## 下周计划\n\n## 需要协助\n"},
    {"key": "doc", "name": "技术文档", "title": "技术文档",
     "content": "# 标题\n\n## 背景\n\n## 方案设计\n\n## 接口说明\n\n## 测试\n"},
]


def _apply_tags(user, note, tag_names):
    tags = []
    for name in tag_names or []:
        name = str(name).strip()
        if not name:
            continue
        tag, _ = NoteTag.objects.get_or_create(name=name[:50], owner=user)
        tags.append(tag)
    note.tags.set(tags)


class NoteListView(APIView):
    """笔记列表：?parent= / ?tag= / ?search= / ?favorite=1 / ?trash=1 / ?all=1"""

    def get(self, request):
        # B6：列表页统一预取——tags（tag_names/tag_ids 共用）、folder FK、
        # child_count 一次聚合算出，避免每篇 4 次附加查询
        qs = _note_qs(request.user).select_related("folder", "parent", "cover_file").prefetch_related("tags")
        if request.query_params.get("trash") == "1":
            qs = qs.filter(is_deleted=True).order_by("-deleted_at")
            qs = qs.annotate(child_count=Count("children", filter=Q(children__is_deleted=False)))
            # B11：可选分页——不带 page 时结构与原来一致
            pg = OptionalPageNumberPagination()
            page = pg.paginate_queryset(qs, request)
            if page is not None:
                return pg.get_paginated_response(NoteSerializer(page, many=True).data)
            total = qs.count()
            rows = list(pg.cap(qs))
            return Response({"list": NoteSerializer(rows, many=True).data, "total": total,
                             "truncated": total > len(rows)})
        qs = qs.filter(is_deleted=False)
        archived = request.query_params.get("archived")
        if archived == "1":
            qs = qs.filter(is_archived=True)
        elif archived != "include":
            qs = qs.filter(is_archived=False)
        parent = request.query_params.get("parent")
        if request.query_params.get("all") != "1":
            if parent in (None, "", "null", "0"):
                qs = qs.filter(parent__isnull=True)
            else:
                try:
                    qs = qs.filter(parent_id=int(parent))
                except (TypeError, ValueError):
                    return Response({"message": "parent 必须是整数"}, status=400)
        # F582 按分组文件夹过滤
        folder = request.query_params.get("folder")
        if folder not in (None, ""):
            if folder in ("none", "unfiled"):
                qs = qs.filter(folder__isnull=True)
            else:
                try:
                    qs = qs.filter(folder_id=int(folder))
                except (TypeError, ValueError):
                    return Response({"message": "folder 必须是整数或 none"}, status=400)
        tag = request.query_params.get("tag")
        # F249 多标签筛选：tags=a,b&mode=all|any（all 用链式 filter 求交集）
        tags_raw = request.query_params.get("tags")
        if tags_raw:
            names = [t.strip()[:50] for t in tags_raw.split(",") if t.strip()]
            mode = request.query_params.get("mode", "any")
            if names and mode == "all":
                for name in names:
                    qs = qs.filter(tags__name=name)
            elif names:
                qs = qs.filter(tags__name__in=names)
        elif tag:
            qs = qs.filter(tags__name=tag)
        search = request.query_params.get("search")
        if search:
            terms = [t for t in re.split(r"\s+", search.strip()) if t]
            cond = Q()
            for t in terms:
                cond &= (Q(title__icontains=t) | Q(content__icontains=t))
            qs = qs.filter(cond) if terms else qs
        if request.query_params.get("favorite") == "1":
            qs = qs.filter(is_favorite=True)
        if request.query_params.get("pinned") == "1":
            qs = qs.filter(is_pinned=True)
        qs = qs.distinct()
        # B6：distinct 下 annotate 同样安全（Count 按主键聚合，不受 join 膨胀影响）
        qs = qs.annotate(child_count=Count("children", filter=Q(children__is_deleted=False)))
        # B11：可选分页——不带 page 时结构与原来一致
        pg = OptionalPageNumberPagination()
        page = pg.paginate_queryset(qs, request)
        if page is not None:
            data = NoteSerializer(page, many=True).data
            backlinked = link_lib.backlink_ids_for(request.user.id, [n.id for n in page])
            for item in data:
                item["has_backlink"] = item["id"] in backlinked
            return pg.get_paginated_response(data)
        total = qs.count()
        rows = list(pg.cap(qs))
        data = NoteSerializer(rows, many=True).data
        backlinked = link_lib.backlink_ids_for(request.user.id, [n.id for n in rows])
        for item in data:
            item["has_backlink"] = item["id"] in backlinked
        return Response({"list": data, "total": total, "truncated": total > len(rows)})

    def post(self, request):
        title = (request.data.get("title") or "未命名笔记").strip()
        # F259 同名检测：同 owner 同标题（未删除）先记下来，随响应返回供前端提示
        dupes = list(
            Note.objects.filter(owner=request.user, title__iexact=title[:200], is_deleted=False)
            .values("id", "title")[:5]
        )
        parent_id = request.data.get("parent")
        if parent_id:
            try:
                parent = Note.objects.filter(pk=int(parent_id), owner=request.user).first()
            except (TypeError, ValueError):
                return Response({"message": "parent 必须是整数"}, status=400)
        else:
            parent = None
        content = request.data.get("content", "")
        note = Note.objects.create(
            title=title, content=content, parent=parent, owner=request.user, words=count_words(content),
            # F573 来源 / F582 分组文件夹
            source=request.data.get("source") or "manual",
            folder=_folder_of(request.user, request.data.get("folder")),
        )
        if note.source not in SOURCE_LABELS:
            note.source = "manual"
            note.save(update_fields=["source"])
        color = str(request.data.get("color") or "")
        if color in NOTE_COLORS:
            note.color = color
            note.save(update_fields=["color"])
        # F18 定时发布 / 到期时间
        sched = {}
        try:
            for field in ("publish_at", "expire_at"):
                raw = request.data.get(field)
                if raw not in (None, ""):
                    sched[field] = as_datetime(raw, field=field)
        except ValidationError:
            return Response({"message": "publish_at / expire_at 必须是合法日期时间"}, status=400)
        if sched:
            for field, val in sched.items():
                setattr(note, field, val)
            note.save(update_fields=list(sched.keys()))
        self._tags = request.data.get("tags") or []
        _apply_tags(request.user, note, self._tags)
        # F238 图标 / F239 封面（创建时也接受，便于模板与速记直接带样式）
        extra = {}
        raw_icon = request.data.get("icon")
        if raw_icon not in (None, ""):
            note.icon = str(raw_icon).strip()[:8]
            extra["icon"] = note.icon
        cover = _file_of(request.user, request.data.get("cover_file_id"))
        if cover is not None:
            note.cover_file = cover
            extra["cover_file"] = note.cover_file
        if extra:
            note.save(update_fields=list(extra.keys()))
        data = NoteSerializer(note).data
        if dupes:
            # 仅新增字段，旧客户端忽略即可
            data["duplicate_titles"] = dupes
        return Response(data, status=status.HTTP_201_CREATED)


class NoteDetailView(APIView):
    """笔记详情 / 更新（自动版本快照）/ 软删除"""

    def get_object(self, request, pk):
        return _get_note(request.user, pk, include_deleted=True)

    def get(self, request, pk):
        note = self.get_object(request, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        data = NoteSerializer(note).data
        data["outline"] = extract_outline(note.content)
        # 双链信息随详情一起返回，前端右侧面板直接渲染
        data["backlinks"] = link_lib.backlinks(note)
        data["outgoing_links"] = link_lib.outgoing_links(note)
        data["is_owner"] = note.owner_id == request.user.id
        data["reading_minutes"] = max(1, round((note.words or 0) / 300)) if note.words else 0
        # F242 待办进度（复用待办抽取）+ F236 未解决评论数
        todos = _scan_todos(note)
        data["todo_total"] = len(todos)
        data["todo_done"] = sum(1 for t in todos if t["done"])
        data["comment_count"] = note.comments.filter(resolved=False).count()
        return Response(data)

    def patch(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True, write=True)
        if not note:
            return Response({"message": "笔记不存在或无权修改"}, status=404)
        changed = False
        snapshot_added = False
        # B5：版本快照 / 笔记本体 / 字数活动 / 标签关联多表写入同一事务，
        # 中途失败整体回滚，杜绝「版本号 +1 但内容没存上」的错位快照
        with transaction.atomic():
            if "title" in request.data and request.data["title"]:
                note.title = request.data["title"].strip()[:200]
                changed = True
            if "content" in request.data:
                if request.data["content"] != note.content:
                    NoteVersion.objects.create(
                        note=note, version=note.version, title=note.title, content=note.content, created_by=request.user
                    )
                    snapshot_added = True
                    note.version += 1
                    old_words = note.words or count_words(note.content)
                    note.content = request.data["content"]
                    note.words = count_words(note.content)
                    # F565 记录当日写作增量（供字数目标 / 周回顾）
                    bump_words_activity(request.user, (note.words or 0) - old_words)
                    changed = True
            if "parent" in request.data:
                pid = request.data.get("parent")
                try:
                    note.parent = Note.objects.filter(pk=int(pid), owner=request.user).first() if pid else None
                except (TypeError, ValueError):
                    raise ValidationError("parent 必须是整数")
                # 环检测：不能把笔记移动到自己的子笔记下
                if note.parent and _would_create_cycle(note, note.parent):
                    raise ValidationError("不能移动到自身的子笔记下")
                changed = True
            # F572 六色标记
            if "color" in request.data:
                color = str(request.data.get("color") or "")
                if color and color not in NOTE_COLORS:
                    raise ValidationError(f"颜色只能是：{','.join(NOTE_COLORS)}")
                note.color = color
                changed = True
            # F582 移动到分组文件夹
            if "folder" in request.data:
                fid = request.data.get("folder")
                folder = _folder_of(request.user, fid)
                if fid not in (None, "", "null", "0", 0) and folder is None:
                    raise ValidationError("文件夹不存在")
                note.folder = folder
                changed = True
            # F238 自定义图标
            if "icon" in request.data:
                note.icon = str(request.data.get("icon") or "").strip()[:8]
                changed = True
            # F239 封面图（校验文件归属）
            if "cover_file_id" in request.data:
                cid = request.data.get("cover_file_id")
                cover = _file_of(request.user, cid)
                if cid not in (None, "", "null", "0", 0) and cover is None:
                    raise ValidationError("封面文件不存在或无权使用")
                note.cover_file = cover
                changed = True
            # F240 回看提醒（改时间后重置已提醒标记，到点会再次提醒）
            if "remind_at" in request.data:
                raw = request.data.get("remind_at")
                if raw in (None, ""):
                    note.remind_at = None
                    note.reminded_at = None
                else:
                    note.remind_at = as_datetime(raw, field="remind_at")
                    note.reminded_at = None
                changed = True
            # #25：取消公开时轮换 share_token——之后再公开是一枚新链接，
            # 旧链接（可能已被转发/缓存）立即失效，不再「一次公开=永久公开」
            was_public = note.is_public
            for flag in ("is_pinned", "is_favorite", "is_public"):
                if flag in request.data:
                    setattr(note, flag, parse_bool(request.data[flag], field=flag))
                    changed = True
            if was_public and not note.is_public:
                note.share_token = uuid.uuid4().hex[:16]
            for field in ("publish_at", "expire_at"):
                if field in request.data:
                    raw = request.data.get(field)
                    setattr(note, field, None if raw in (None, "") else as_datetime(raw, field=field))
                    changed = True
            if "tags" in request.data and isinstance(request.data["tags"], list):
                _apply_tags(request.user, note, request.data["tags"])
                changed = True
            if changed:
                note.save()
            # #51：有新快照才裁剪，单篇最多保留最近 50 条（同一事务内）
            if snapshot_added:
                _prune_note_versions(note)
        return Response(NoteSerializer(note).data)

    def delete(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True, write=True)
        if not note:
            return Response({"message": "笔记不存在或无权删除"}, status=404)
        note.is_deleted = True
        note.deleted_at = timezone.now()
        note.save(update_fields=["is_deleted", "deleted_at"])
        return Response({"message": "已移入回收站"})


class NoteBatchView(APIView):
    """批量：move / trash / restore / destroy / favorite / pin / tags"""

    def post(self, request):
        action = request.data.get("action")
        ids = request.data.get("note_ids") or []
        if not ids:
            return Response({"message": "未选择笔记"}, status=400)
        qs = _note_write_qs(request.user).filter(id__in=ids)
        if action == "trash":
            n = qs.update(is_deleted=True, deleted_at=timezone.now())
            return Response({"message": f"已移入回收站 {n} 篇"})
        if action == "restore":
            n = qs.update(is_deleted=False, deleted_at=None)
            return Response({"message": f"已恢复 {n} 篇"})
        if action == "destroy":
            n = qs.delete()[0]
            return Response({"message": f"已彻底删除 {n} 篇"})
        if action == "favorite":
            n = qs.update(is_favorite=True)
            return Response({"message": f"已收藏 {n} 篇"})
        if action == "unfavorite":
            n = qs.update(is_favorite=False)
            return Response({"message": f"已取消收藏 {n} 篇"})
        if action == "pin":
            n = qs.update(is_pinned=True)
            return Response({"message": f"已置顶 {n} 篇"})
        if action == "move":
            pid = request.data.get("parent")
            try:
                parent = Note.objects.filter(pk=int(pid), owner=request.user).first() if pid else None
            except (TypeError, ValueError):
                return Response({"message": "parent 必须是整数"}, status=400)
            # 环检测：目标 parent 不能是被移动笔记中任何一篇的后代（含其自身）
            if parent is not None:
                for n in qs:
                    if _would_create_cycle(n, parent):
                        return Response({"message": "不能移动到自身的子笔记下"}, status=400)
            n = qs.update(parent=parent)
            return Response({"message": f"已移动 {n} 篇"})
        if action == "archive":
            n = qs.update(is_archived=True)
            return Response({"message": f"已归档 {n} 篇"})
        if action == "unarchive":
            n = qs.update(is_archived=False)
            return Response({"message": f"已取消归档 {n} 篇"})
        # F247 批量移动到分组文件夹
        if action == "folder":
            fid = request.data.get("folder")
            folder = _folder_of(request.user, fid)
            if fid not in (None, "", "null", "0", 0) and folder is None:
                return _nb("文件夹不存在")
            n = qs.update(folder=folder)
            label = folder.name if folder else "未分组"
            return Response({"message": f"已移动到「{label}」（{n} 篇）", "moved": n, "folder": folder.id if folder else None})
        # F248 批量打标签 / 移除标签（按名称 get_or_create）
        if action in ("tag", "untag"):
            raw = request.data.get("tags") or request.data.get("tag") or []
            if isinstance(raw, str):
                raw = raw.split(",")
            names = []
            for x in raw:
                nm = str(x).strip()[:50]
                if nm and nm not in names:
                    names.append(nm)
            if not names:
                return _nb("请提供标签名")
            note_ids = list(qs.values_list("id", flat=True))
            if not note_ids:
                return Response({"message": "没有可操作的笔记", "count": 0})
            if action == "tag":
                tags = [NoteTag.objects.get_or_create(name=nm, owner=request.user)[0] for nm in names]
                for nid in note_ids:
                    Note.tags.through.objects.bulk_create(
                        [Note.tags.through(note_id=nid, notetag_id=t.id) for t in tags],
                        ignore_conflicts=True,
                    )
                return Response({"message": f"已为 {len(note_ids)} 篇添加标签", "count": len(note_ids),
                                 "tags": names})
            tags = NoteTag.objects.filter(owner=request.user, name__in=names)
            Note.tags.through.objects.filter(
                note_id__in=note_ids, notetag_id__in=[t.id for t in tags]
            ).delete()
            return Response({"message": f"已为 {len(note_ids)} 篇移除标签", "count": len(note_ids),
                             "tags": names})
        # F251 批量颜色标记
        if action == "color":
            color = str(request.data.get("color") or "")
            if color and color not in NOTE_COLORS:
                return _nb(f"颜色只能是：{','.join(NOTE_COLORS)}")
            n = qs.update(color=color)
            return Response({"message": f"已标记 {n} 篇", "count": n, "color": color})
        return Response({"message": "未知操作"}, status=400)


class NoteTrashView(APIView):
    """回收站：列表 / 清空"""

    def get(self, request):
        qs = _note_write_qs(request.user).filter(is_deleted=True).order_by("-deleted_at")
        return Response({"list": NoteSerializer(qs, many=True).data, "total": qs.count()})

    def delete(self, request):
        n = _note_write_qs(request.user).filter(is_deleted=True).delete()[0]
        return Response({"message": f"已清空回收站（{n} 篇）"})


class NoteCopyView(APIView):
    """复制笔记为副本"""

    def post(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        copy = Note.objects.create(
            title=f"{note.title}（副本）", content=note.content, owner=request.user,
            parent=note.parent, words=note.words,
            source="copy", folder=note.folder, color=note.color,
        )
        copy.tags.set(note.tags.all())
        return Response(NoteSerializer(copy).data, status=201)


class NoteTreeView(APIView):
    def get(self, request):
        def node(n, children):
            # F238 图标 / F239 封面缩略图 / F572 颜色随树一起返回，前端列表直接渲染
            cover = n.cover_file
            return {"id": n.id, "title": n.title, "is_public": n.is_public,
                    "is_favorite": n.is_favorite, "is_pinned": n.is_pinned,
                    "icon": n.icon, "color": n.color, "pin_order": n.pin_order,
                    "cover_thumb": (cover.thumbnail_url or cover.url) if cover else "",
                    "children": children}

        def build(parent_id, visited):
            # F260：与列表一致，置顶之间按 pin_order 排序
            qs = _note_qs(request.user).filter(parent_id=parent_id, is_deleted=False).select_related(
                "cover_file"
            ).order_by("-is_pinned", "pin_order", "updated_at")
            nodes = []
            for n in qs:
                # 防递归：历史脏数据可能成环，已展开过的 id 不再下钻
                if n.id in visited:
                    nodes.append(node(n, []))
                    continue
                visited.add(n.id)
                nodes.append(node(n, build(n.id, visited)))
            return nodes

        return Response({"tree": build(None, set())})


class NoteTagListView(APIView):
    """标签列表（含用量）/ 新建标签"""

    def get(self, request):
        qs = NoteTag.objects.filter(owner=request.user).annotate(c=Count("notes")).order_by("-c", "name")
        data = NoteTagSerializer(qs, many=True).data
        # 序列化已取全量，len 即总数；annotate 后再 count() 会多一条聚合查询
        return Response({"list": data, "total": len(data)})

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"message": "标签名不能为空"}, status=400)
        tag, created = NoteTag.objects.get_or_create(
            name=name[:50], owner=request.user, defaults={"color": request.data.get("color", "default")}
        )
        if not created:
            return Response({"message": "标签已存在"}, status=400)
        return Response(NoteTagSerializer(tag).data, status=201)


class NoteTagDetailView(APIView):
    """标签重命名 / 改色 / 删除"""

    def get_object(self, request, pk):
        return NoteTag.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        tag = self.get_object(request, pk)
        if not tag:
            return Response({"message": "标签不存在"}, status=404)
        if "name" in request.data and (request.data["name"] or "").strip():
            new_name = request.data["name"].strip()[:50]
            # #52：unique_together(owner, name) 冲突必须在写入前拦下，否则 IntegrityError → 500
            if new_name != tag.name and NoteTag.objects.filter(
                owner=request.user, name=new_name
            ).exclude(pk=tag.pk).exists():
                return Response({"message": "同名标签已存在", "ok": False, "error": "同名标签已存在"}, status=400)
            tag.name = new_name
        if "color" in request.data:
            tag.color = request.data["color"]
        try:
            tag.save()
        except IntegrityError:
            return Response({"message": "同名标签已存在", "ok": False, "error": "同名标签已存在"}, status=400)
        return Response(NoteTagSerializer(tag).data)

    def delete(self, request, pk):
        tag = self.get_object(request, pk)
        if not tag:
            return Response({"message": "标签不存在"}, status=404)
        tag.delete()
        return Response({"message": "标签已删除"})


class NoteOutlineView(APIView):
    """提取单篇笔记 Markdown 大纲"""

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        return Response({"outline": extract_outline(note.content)})


class NoteStatsView(APIView):
    """笔记统计：篇数、总字数、标签数、收藏/置顶数、近 7 天更新"""

    def get(self, request):
        qs = _note_qs(request.user).filter(is_deleted=False)
        week_ago = timezone.now() - timezone.timedelta(days=7)
        return Response({
            "total": qs.count(),
            "total_words": qs.aggregate(s=Sum("words"))["s"] or 0,
            "favorite": qs.filter(is_favorite=True).count(),
            "pinned": qs.filter(is_pinned=True).count(),
            "public": qs.filter(is_public=True).count(),
            "tags": NoteTag.objects.filter(owner=request.user).count(),
            "trash": _note_qs(request.user).filter(is_deleted=True).count(),
            "updated_7d": qs.filter(updated_at__gte=week_ago).count(),
        })


class NoteVersionListView(APIView):
    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        qs = NoteVersion.objects.filter(note=note)
        return Response({"list": NoteVersionSerializer(qs, many=True).data, "total": qs.count()})


class NoteVersionDiffView(APIView):
    """对比两个版本：返回各自内容与行级增删（基于 difflib）"""

    def get(self, request, pk):
        import difflib
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        # #50：from/to 先用 as_int 校验，垃圾参数走 400 而不是 ORM 500
        v1 = as_int(request.query_params.get("from"), field="from")
        v2 = as_int(request.query_params.get("to"), field="to")
        a = NoteVersion.objects.filter(note=note, version=v1).first()
        b = NoteVersion.objects.filter(note=note, version=v2).first()
        if not a or not b:
            return Response({"message": "版本不存在"}, status=404)
        diff = list(difflib.unified_diff(
            a.content.splitlines(), b.content.splitlines(), lineterm="", n=1
        ))
        return Response({"from_version": a.version, "to_version": b.version, "from_content": a.content,
                         "to_content": b.content, "diff": diff})


class NoteRollbackView(APIView):
    def post(self, request, pk, version):
        # #54：整段回滚收进单事务并对笔记加行锁，避免并发回滚时 next_version 撞唯一键、
        # 以及「正文已改但版本号没跟上」的不一致。
        with transaction.atomic():
            note = _note_write_qs(request.user).select_for_update().filter(pk=pk).first()
            if not note:
                return Response({"message": "笔记不存在"}, status=404)
            snap = NoteVersion.objects.filter(note=note, version=version).first()
            if not snap:
                return Response({"message": "版本不存在"}, status=404)
            last = NoteVersion.objects.filter(note=note).aggregate(m=Max("version"))["m"] or 0
            next_version = max(int(note.version or 1), last + 1)
            snapshot = dict(note=note, title=note.title, content=note.content, created_by=request.user)
            try:
                # 内层 atomic 建立 savepoint，唯一冲突后外层事务仍可用
                with transaction.atomic():
                    NoteVersion.objects.create(version=next_version, **snapshot)
            except IntegrityError:
                last = NoteVersion.objects.filter(note=note).aggregate(m=Max("version"))["m"] or 0
                next_version = max(next_version, last) + 1
                with transaction.atomic():
                    NoteVersion.objects.create(version=next_version, **snapshot)
            note.title, note.content = snap.title, snap.content
            note.words = count_words(note.content)
            note.version = next_version + 1
            note.save()
        return Response({"message": f"已回滚到 v{version}", "note": NoteSerializer(note).data})


class NoteShareView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        # #25：公开读取要落在 publish_at ~ expire_at 时间窗内；
        # 未到发布时间 / 已过到期时间都按「未公开」处理（404，不泄露存在性）
        now = timezone.now()
        note = (
            Note.objects.filter(share_token=token, is_public=True, is_deleted=False)
            .filter(
                Q(publish_at__isnull=True) | Q(publish_at__lte=now),
                Q(expire_at__isnull=True) | Q(expire_at__gt=now),
            )
            .first()
        )
        if not note:
            return Response({"message": "笔记不存在或未公开"}, status=404)
        return Response({"title": note.title, "content": note.content, "updated_at": note.updated_at,
                         "version": note.version, "outline": extract_outline(note.content)})


class NoteRecentView(APIView):
    def get(self, request):
        qs = _note_qs(request.user).filter(is_deleted=False).select_related("cover_file").order_by("-updated_at")[:10]
        return Response({"list": NoteSerializer(qs, many=True).data})


class NoteTemplateListView(APIView):
    """内置模板清单"""

    def get(self, request):
        return Response({"list": NOTE_TEMPLATES})


class NoteFromTemplateView(APIView):
    """从模板创建笔记"""

    def post(self, request):
        key = request.data.get("key", "blank")
        tpl = next((t for t in NOTE_TEMPLATES if t["key"] == key), NOTE_TEMPLATES[0])
        note = Note.objects.create(
            title=request.data.get("title") or tpl["title"], content=tpl["content"],
            owner=request.user, words=count_words(tpl["content"]),
            source="template", folder=_folder_of(request.user, request.data.get("folder")),
        )
        return Response(NoteSerializer(note).data, status=201)


class NoteExportView(APIView):
    """导出单篇笔记为 Markdown 文件"""

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        body = f"# {note.title}\n\n> 导出于 {timezone.now():%Y-%m-%d %H:%M}\n\n{note.content}\n"
        resp = HttpResponse(body.encode("utf-8"), content_type="text/markdown; charset=utf-8")
        # #28：中文/换行标题统一交给 Django 生成 filename*（RFC5987），不再手拼
        filename = re.sub(r'[\\/:*?"<>|\r\n]', "_", note.title).strip() or "note"
        resp["Content-Disposition"] = content_disposition_header(True, f"{filename}.md")
        return resp


class NoteExportAllView(APIView):
    """导出全部笔记为 zip"""

    def get(self, request):
        notes = _note_qs(request.user).filter(is_deleted=False).only("id", "title", "content")
        # 写临时文件后流式返回，避免把整库笔记一次性堆在内存里
        tmp = tempfile.TemporaryFile()
        used = set()
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for n in notes.iterator(chunk_size=200):
                base = re.sub(r'[\\/:*?"<>|]', "_", n.title) or "note"
                arc, i = f"{base}.md", 1
                while arc in used:
                    arc = f"{base}({i}).md"
                    i += 1
                used.add(arc)
                zf.writestr(arc, f"# {n.title}\n\n{n.content}\n")
        tmp.seek(0)
        return FileResponse(tmp, as_attachment=True, filename="notes.zip", content_type="application/zip")


# ---------------- 双链（[[wiki link]]） ----------------

class NoteBacklinkView(APIView):
    """某篇笔记的反向链接 + 出链 + 悬浮链接

    GET /api/notes/<pk>/backlinks/
    """

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        back = link_lib.backlinks(note)
        out = link_lib.outgoing_links(note)
        return Response({
            "note_id": note.id,
            "title": note.title,
            "backlinks": back,
            "outgoing_links": out,
            "backlink_count": len(back),
            "outgoing_count": len(out),
            "dangling_count": len([o for o in out if not o["resolved"]]),
        })


class NoteLinkGraphView(APIView):
    """整库双链图谱（nodes + edges），供关系图渲染

    GET /api/notes/graph/?limit=300
    """

    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 300)), 1000)
        except (TypeError, ValueError):
            return Response({"message": "limit 必须是整数"}, status=400)
        return Response(link_lib.link_graph(request.user.id, limit=limit))


class NoteLinkSuggestView(APIView):
    """[[ 输入时的标题联想

    GET /api/notes/link-suggest/?q=架构&exclude=12
    """

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        exclude = request.query_params.get("exclude")
        try:
            limit = min(int(request.query_params.get("limit", 10)), 30)
        except (TypeError, ValueError):
            return Response({"message": "limit 必须是整数"}, status=400)
        if exclude:
            try:
                exclude = int(exclude)
            except (TypeError, ValueError):
                return Response({"message": "exclude 必须是整数"}, status=400)
        else:
            exclude = None
        return Response({"list": link_lib.suggest_titles(
            request.user.id, q, exclude_id=exclude, limit=limit
        )})


class NoteDanglingView(APIView):
    """悬浮链接汇总：被引用但尚未创建的笔记标题

    GET /api/notes/dangling/
    """

    def get(self, request):
        items = link_lib.dangling_notes(request.user.id)
        return Response({"list": items, "total": len(items)})


class NoteFromTitleView(APIView):
    """按标题直接创建笔记（用于一键消除悬浮链接），创建后原悬浮链接自动接上

    POST /api/notes/from-title/  {"title": "系统架构"}
    """

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"message": "标题不能为空"}, status=400)
        existing = Note.objects.filter(owner=request.user, title__iexact=title, is_deleted=False).first()
        if existing:
            return Response({"message": "同名笔记已存在", "note": NoteSerializer(existing).data})
        note = Note.objects.create(title=title[:200], content="", owner=request.user, source="link")
        return Response(NoteSerializer(note).data, status=201)


class NoteLinkRebuildView(APIView):
    """重建当前用户的全部双链关系（正文被外部改动或索引异常时使用）

    POST /api/notes/links/rebuild/

    #113：单次最多重建 500 篇（可用 limit / offset 分批翻页），
    全量重建交给 `manage.py reindex_search` 管理命令，避免长请求占满 worker。
    """

    MAX_NOTES = 500

    def post(self, request):
        try:
            limit = _qp_int(request.data, "limit", self.MAX_NOTES, lo=1, hi=self.MAX_NOTES)
            offset = _qp_int(request.data, "offset", 0, lo=0)
        except ValueError as e:
            return _nb(str(e))
        qs = _note_qs(request.user).filter(is_deleted=False).order_by("id")
        total_notes = qs.count()
        batch = list(qs[offset:offset + limit])
        links = 0
        for note in batch:
            links += link_lib.rebuild_links_for_note(note) or 0
        processed = len(batch)
        done = min(offset + processed, total_notes)
        remaining = max(0, total_notes - done)
        dangling = link_lib.dangling_notes(request.user.id)
        return Response({
            "message": "双链已重建" if not remaining else "双链已分批重建，请继续下一批",
            "notes": total_notes, "links": links, "dangling": len(dangling),
            "processed": processed, "offset": offset, "limit": limit,
            "next_offset": done if remaining else None,
            "remaining": remaining, "truncated": remaining > 0,
            "hint": "全量重建请执行 manage.py reindex_search",
        })

# ---------------- 批量导入 / 标签云 / 选篇导出 / 闪卡 / AI大纲 ----------------

def _split_markdown_into_notes(md: str):
    """按顶级 # 标题把一段 Markdown 切分成多篇笔记。
    没有顶级标题的内容作为一篇（标题取首行或'导入片段'）。"""
    md = md.replace("\r\n", "\n")
    parts = re.split(r"(?m)^#\s+", md)
    notes = []
    for i, part in enumerate(parts):
        part = part.strip("\n")
        if not part.strip():
            continue
        if i == 0 and not part.startswith("#"):
            # 第一段没有 # 前缀
            first_nl = part.find("\n")
            if first_nl < 0:
                title = part.strip()[:200] or "导入片段"
                body = ""
            else:
                title = part[:first_nl].strip()[:200] or "导入片段"
                body = part[first_nl + 1:].strip()
        else:
            first_nl = part.find("\n")
            if first_nl < 0:
                title = part.strip()[:200] or "未命名"
                body = ""
            else:
                title = part[:first_nl].strip()[:200] or "未命名"
                body = part[first_nl + 1:].strip()
        notes.append({"title": title, "content": body})
    return notes


class NoteBatchImportView(APIView):
    """批量导入 Markdown 为多篇笔记。

    入参二选一：
    - {"markdown": "# 标题A\n正文...\n# 标题B\n..."}  按 # 切分
    - {"notes": [{"title": "...", "content": "..."}]}    直接给结构
    """

    def post(self, request):
        items = request.data.get("notes")
        if isinstance(items, list) and items:
            payload = items
        else:
            md = request.data.get("markdown") or ""
            if not md.strip():
                return Response({"message": "请提供 markdown 或 notes"}, status=status.HTTP_400_BAD_REQUEST)
            payload = _split_markdown_into_notes(md)
        created = []
        for it in payload[:200]:
            title = (it.get("title") or "导入片段").strip()[:200] or "导入片段"
            content = it.get("content", "") or ""
            note = Note.objects.create(
                title=title, content=content, owner=request.user, words=count_words(content),
                source="import",
            )
            created.append(NoteSerializer(note).data)
        return Response({"message": f"已导入 {len(created)} 篇笔记", "created": created, "count": len(created)},
                        status=status.HTTP_201_CREATED)


class NoteTagCloudView(APIView):
    """标签云：聚合每个标签的使用次数，供前端按频次渲染字号。"""

    def get(self, request):
        qs = NoteTag.objects.filter(owner=request.user).annotate(c=Count("notes"))
        items = [{"id": t.id, "name": t.name, "color": t.color, "count": t.c} for t in qs]
        items.sort(key=lambda x: x["count"], reverse=True)
        max_c = max([x["count"] for x in items], default=1) or 1
        for x in items:
            x["weight"] = round(0.7 + 0.6 * (x["count"] / max_c), 2)
        return Response({"list": items, "total": len(items)})


class NoteExportSelectedView(APIView):
    """勾选多篇笔记打包导出：format=zip（默认）或 format=md（合并为单个 Markdown）。"""

    def post(self, request):
        ids = request.data.get("note_ids") or []
        if not ids:
            return Response({"message": "未选择笔记"}, status=status.HTTP_400_BAD_REQUEST)
        notes = list(_note_qs(request.user).filter(is_deleted=False, id__in=ids))
        if not notes:
            return Response({"message": "没有可导出的笔记"}, status=400)
        fmt = request.data.get("format", "zip")
        if fmt == "md":
            body = "\n\n---\n\n".join(
                f"# {n.title}\n\n> 导出于 {timezone.now():%Y-%m-%d %H:%M}\n\n{n.content}\n" for n in notes
            )
            resp = HttpResponse(body.encode("utf-8"), content_type="text/markdown; charset=utf-8")
            resp["Content-Disposition"] = "attachment; filename=notes.md"
            return resp
        buf = io.BytesIO()
        used = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for n in notes:
                base = re.sub(r'[\\/:*?"<>|]', "_", n.title) or "note"
                arc, i = f"{base}.md", 1
                while arc in used:
                    arc = f"{base}({i}).md"
                    i += 1
                used.add(arc)
                zf.writestr(arc, f"# {n.title}\n\n{n.content}\n")
        resp = HttpResponse(buf.getvalue(), content_type="application/zip")
        resp["Content-Disposition"] = "attachment; filename=notes_selected.zip"
        return resp


class NoteFlashcardsView(APIView):
    """从笔记正文抽取问答闪卡：每个 ## 小节作为一个问题，正文作为答案（本地抽取式）。"""

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        cards = []
        sections = re.split(r"(?m)^(##+\s+.*)$", note.content or "")
        # sections: [前缀, 标题1, 正文1, 标题2, 正文2, ...]
        for i in range(1, len(sections) - 1, 2):
            q = re.sub(r"^#+\s+", "", sections[i]).strip()
            a = sections[i + 1].strip()
            if q and a:
                cards.append({"front": q, "back": a[:500]})
        if not cards and note.content:
            cards.append({"front": note.title, "back": note.content[:500]})
        return Response({"note_id": note.id, "cards": cards, "total": len(cards)})


class NoteAiOutlineView(APIView):
    """AI 大纲 / 摘要（本地抽取式降级）：返回标题树 + 关键句摘要。
    未配置大模型时不报错，直接返回抽取式结果。"""

    def post(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        outline = extract_outline(note.content)
        # 抽取式摘要：取非标题、非空行的前若干句
        sentences = []
        for line in (note.content or "").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or s.startswith(">"):
                continue
            for seg in re.split(r"(?<=[。！？.!?])", s):
                seg = seg.strip()
                if len(seg) >= 8:
                    sentences.append(seg)
            if len(sentences) >= 6:
                break
        summary = " ".join(sentences[:3])
        return Response({
            "note_id": note.id,
            "outline": outline,
            "summary": summary[:500],
            "provider": "local-extractive",
            "heading_count": len(outline),
        })


# =====================================================================
# =========== F565–F582 笔记知识库新增能力（只增不改） ===================
# =====================================================================

def _qp_int(params, name, default, lo=None, hi=None):
    """安全取整数参数；非法时抛 ValueError（调用方统一转 400）"""
    raw = params.get(name)
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


def _nb(message, code=400):
    return Response({"message": message, "ok": False, "error": message}, status=code)


TODO_LINE_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s*(.*)$")


def _scan_todos(note):
    """扫描一篇笔记里的 `- [ ]` 待办行"""
    items = []
    for idx, line in enumerate((note.content or "").split("\n")):
        m = TODO_LINE_RE.match(line)
        if not m:
            continue
        items.append({"line_no": idx, "text": m.group(2).strip()[:300],
                      "done": m.group(1).lower() == "x"})
    return items


# ---------------- F565 写作字数目标 ----------------

class WritingGoalView(APIView):
    """F565 写作字数目标与完成度：GET 进度 / POST 新建"""

    def get(self, request):
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        def _sum(start, end):
            return WordActivity.objects.filter(
                owner=request.user, date__gte=start, date__lte=end
            ).aggregate(s=Sum("delta"))["s"] or 0

        sums = {"day": _sum(today, today), "week": _sum(week_start, today),
                "month": _sum(month_start, today)}
        labels = dict(WritingGoal.PERIOD_CHOICES)
        goals = []
        for g in WritingGoal.objects.filter(owner=request.user, active=True).select_related("note"):
            if g.period == "note":
                current = (g.note.words or 0) if g.note and not g.note.is_deleted else 0
            else:
                current = sums.get(g.period, 0)
            pct = min(100.0, round(current / g.target * 100, 1)) if g.target else 0.0
            goals.append({
                "id": g.id, "target": g.target, "period": g.period,
                "period_label": labels.get(g.period, g.period),
                "note_id": g.note_id, "note_title": g.note.title if g.note else "",
                "current": current, "pct": pct, "achieved": current >= g.target,
                "created_at": g.created_at,
            })
        return Response({
            "goals": goals, "goal_count": len(goals),
            "today_words": sums["day"], "week_words": sums["week"], "month_words": sums["month"],
        })

    def post(self, request):
        try:
            target = int(request.data.get("target", 0))
        except (TypeError, ValueError):
            return _nb("target 必须是整数")
        if target <= 0 or target > 1_000_000:
            return _nb("target 需在 1–1000000 之间")
        period = request.data.get("period", "day")
        if period not in ("day", "week", "month", "note"):
            return _nb("period 只能是 day/week/month/note")
        note = None
        if period == "note":
            note_id = request.data.get("note_id")
            if not note_id:
                return _nb("note 模式需要 note_id")
            try:
                note = _get_note(request.user, int(note_id), include_deleted=True)
            except (TypeError, ValueError):
                return _nb("note_id 必须是整数")
            if not note:
                return _nb("笔记不存在", 404)
        goal = WritingGoal.objects.create(owner=request.user, target=target, period=period, note=note)
        return Response({"message": "目标已创建", "id": goal.id, "target": target, "period": period},
                        status=status.HTTP_201_CREATED)


class WritingGoalDetailView(APIView):
    """F565 目标更新 / 删除"""

    def _get(self, request, pk):
        return WritingGoal.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        goal = self._get(request, pk)
        if not goal:
            return _nb("目标不存在", 404)
        if "target" in request.data:
            try:
                target = int(request.data["target"])
            except (TypeError, ValueError):
                return _nb("target 必须是整数")
            if target <= 0:
                return _nb("target 必须大于 0")
            goal.target = target
        if "active" in request.data:
            goal.active = parse_bool(request.data["active"], field="active")
        goal.save()
        return Response({"message": "已更新", "id": goal.id, "target": goal.target, "active": goal.active})

    def delete(self, request, pk):
        goal = self._get(request, pk)
        if not goal:
            return _nb("目标不存在", 404)
        goal.delete()
        return Response({"message": "目标已删除"})


# ---------------- F566 日记视图 ----------------

class DiaryView(APIView):
    """F566 日记视图：按日历聚合某月新建的笔记"""

    def get(self, request):
        today = timezone.localdate()
        try:
            year = _qp_int(request.query_params, "year", today.year, lo=2000, hi=2100)
            month = _qp_int(request.query_params, "month", today.month, lo=1, hi=12)
        except ValueError as e:
            return _nb(str(e))
        first = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        last = date(year, month, last_day)
        qs = _note_qs(request.user).filter(
            is_deleted=False, created_at__date__gte=first, created_at__date__lte=last
        ).order_by("created_at")
        by_day = {}
        for n in qs:
            d = timezone.localtime(n.created_at).date()
            by_day.setdefault(d, []).append(n)
        days = []
        for day_num in range(1, last_day + 1):
            d = date(year, month, day_num)
            notes = by_day.get(d, [])
            days.append({
                "date": d.isoformat(), "day": day_num, "weekday": d.weekday(),
                "count": len(notes), "words": sum(n.words or 0 for n in notes),
                "notes": [{"id": n.id, "title": n.title, "words": n.words,
                           "color": n.color, "is_pinned": n.is_pinned} for n in notes],
            })
        if month == 1:
            prev_m, prev_y = 12, year - 1
        else:
            prev_m, prev_y = month - 1, year
        next_m, next_y = (1, year + 1) if month == 12 else (month + 1, year)
        return Response({
            "year": year, "month": month, "days": days, "days_in_month": last_day,
            "first_weekday": first.weekday(),
            "total_notes": sum(d["count"] for d in days),
            "total_words": sum(d["words"] for d in days),
            "empty_days": sum(1 for d in days if d["count"] == 0),
            "prev": {"year": prev_y, "month": prev_m},
            "next": {"year": next_y, "month": next_m},
        })


# ---------------- F567 未链接提及 ----------------

class UnlinkedMentionsView(APIView):
    """F567 未链接提及清单：正文出现别的笔记标题，但没写成 [[标题]]

    #92：不再把上千个标题拼成超长交替正则（编译与回溯开销随标题数爆炸），
    改为「标题数限 200 + 逐标题 substring 判断」，行为与原来一致。
    """

    LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
    NOTE_SCAN_LIMIT = 2000
    TITLE_SCAN_LIMIT = 200

    def get(self, request):
        try:
            limit = _qp_int(request.query_params, "limit", 50, lo=1, hi=300)
        except ValueError as e:
            return _nb(str(e))
        notes = list(
            _note_qs(request.user).filter(is_deleted=False)
            .order_by("-updated_at")[:self.NOTE_SCAN_LIMIT]
        )
        if len(notes) < 2:
            return Response({"list": [], "total": 0, "note_count": len(notes),
                             "title_count": 0, "title_limit": self.TITLE_SCAN_LIMIT})
        canon = {}
        for n in notes:
            t = (n.title or "").strip()
            if len(t) >= 2:
                canon.setdefault(t.lower(), n)
            if len(canon) >= self.TITLE_SCAN_LIMIT:
                break
        if len(canon) < 2:
            return Response({"list": [], "total": 0, "note_count": len(notes),
                             "title_count": len(canon), "title_limit": self.TITLE_SCAN_LIMIT})
        # 长标题优先，避免「Django」先命中导致「Django ORM」漏统计
        title_items = sorted(canon.items(), key=lambda kv: -len(kv[0]))
        mentions = {}  # canonical lower title -> {"target": note, "sources": {note_id: {...}}, "total": int}
        for n in notes:
            content = self.LINK_RE.sub(lambda m: " " * len(m.group(0)), n.content or "")
            if len(content) < 2:
                continue
            low = content.lower()
            for key, target in title_items:
                if target.id == n.id:
                    continue
                pos, hits = low.find(key), 0
                first = pos
                while pos >= 0:
                    hits += 1
                    pos = low.find(key, pos + len(key))
                if not hits:
                    continue
                bucket = mentions.setdefault(key, {"target": target, "sources": {}, "total": 0})
                bucket["total"] += hits
                src = bucket["sources"].get(n.id)
                if src is None:
                    start = max(0, first - 40)
                    excerpt = content[start:first + len(key) + 40].replace("\n", " ").strip()
                    bucket["sources"][n.id] = {
                        "note_id": n.id, "note_title": n.title, "count": hits, "excerpt": excerpt,
                    }
                else:
                    src["count"] += hits
        result = []
        for bucket in mentions.values():
            sources = sorted(bucket["sources"].values(), key=lambda s: -s["count"])[:10]
            result.append({
                "target_id": bucket["target"].id,
                "target_title": bucket["target"].title,
                "count": bucket["total"], "sources": sources,
            })
        result.sort(key=lambda x: x["count"], reverse=True)
        return Response({"list": result[:limit], "total": len(result), "note_count": len(notes),
                         "title_count": len(canon), "title_limit": self.TITLE_SCAN_LIMIT})


# ---------------- F568 随机回顾 ----------------

class RandomNoteView(APIView):
    """F568 随机回顾 🎲：随机抽一篇笔记"""

    def get(self, request):
        qs = _note_qs(request.user).filter(is_deleted=False)
        exclude = request.query_params.get("exclude")
        if exclude:
            try:
                qs = qs.exclude(id=int(exclude))
            except (TypeError, ValueError):
                return _nb("exclude 必须是整数")
        tag = request.query_params.get("tag")
        if tag:
            qs = qs.filter(tags__name=tag).distinct()
        count = qs.count()
        if count == 0:
            return _nb("没有可回顾的笔记", 404)
        offset = random.randint(0, count - 1)
        picked = list(qs[offset:offset + 1])
        if not picked:  # count 与取行之间被并发删除
            return _nb("没有可回顾的笔记", 404)
        note = picked[0]
        data = NoteSerializer(note).data
        data["outline"] = extract_outline(note.content)
        data["pool_size"] = count
        return Response(data)


# ---------------- F569 笔记健康度报告 ----------------

HEALTH_ISSUES = {
    "short": "内容过短（不足 50 字）",
    "no_heading": "缺少标题结构",
    "orphan": "孤立笔记（没有任何双链）",
    "no_tag": "未打标签",
    "stale": "长期未更新",
}


class NoteHealthView(APIView):
    """F569 笔记健康度报告：单篇打分 + 问题聚合

    #100：扫描上限从 2000 降到 500，且按 200 篇一批分块统计后累加，
    避免单次请求把全库正文一次性载入内存；limit 只控制输出条数。
    """

    SCAN_LIMIT = 500
    BATCH_SIZE = 200

    def get(self, request):
        try:
            stale_days = _qp_int(request.query_params, "stale_days", 30, lo=1, hi=365)
            limit = _qp_int(request.query_params, "limit", 50, lo=1, hi=300)
        except ValueError as e:
            return _nb(str(e))
        qs = _note_qs(request.user).filter(is_deleted=False).order_by("-updated_at", "-id")
        total_notes = qs.count()
        if not total_notes:
            return Response({"note_count": 0, "avg_score": 0, "grade": "-",
                             "distribution": {}, "issues": [], "worst": [],
                             "scanned": 0, "scan_limit": self.SCAN_LIMIT,
                             "batch_size": self.BATCH_SIZE, "total_notes": 0,
                             "truncated": False})
        backlinked = link_lib.all_backlink_ids(request.user.id) or set()
        now = timezone.now()
        rows, counter = [], {}
        scanned = 0
        for start in range(0, self.SCAN_LIMIT, self.BATCH_SIZE):
            batch = list(
                qs.prefetch_related("tags")[start:start + self.BATCH_SIZE]
            )
            if not batch:
                break
            # 每批只查本批笔记的出链计数，避免一次性 IN 500 个 id
            outgoing = dict(
                NoteLink.objects.filter(source_id__in=[n.id for n in batch])
                .values("source_id").annotate(c=Count("id")).values_list("source_id", "c")
            )
            for n in batch:
                score = 100
                issues = []
                words = n.words or count_words(n.content)
                if words < 50:
                    score -= 25
                    issues.append("short")
                if words >= 50 and not re.search(r"(?m)^#{1,6}\s", n.content or ""):
                    score -= 10
                    issues.append("no_heading")
                if not outgoing.get(n.id) and n.id not in backlinked:
                    score -= 20
                    issues.append("orphan")
                if not n.tags.all():
                    score -= 10
                    issues.append("no_tag")
                if (now - n.updated_at).days > stale_days:
                    score -= 15
                    issues.append("stale")
                score = max(score, 0)
                grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"
                for i in issues:
                    counter[i] = counter.get(i, 0) + 1
                rows.append({
                    "id": n.id, "title": n.title, "words": words, "score": score, "grade": grade,
                    "issues": issues, "updated_at": n.updated_at, "color": n.color,
                    "backlinks": 1 if n.id in backlinked else 0, "outgoing": outgoing.get(n.id, 0),
                })
            scanned += len(batch)
            if len(batch) < self.BATCH_SIZE:
                break
        total = len(rows)
        avg = round(sum(r["score"] for r in rows) / total, 1)
        distribution = {g: sum(1 for r in rows if r["grade"] == g) for g in ("A", "B", "C", "D")}
        overall = "A" if avg >= 85 else "B" if avg >= 70 else "C" if avg >= 55 else "D"
        labels = dict(HEALTH_ISSUES)
        labels["stale"] = f"超过 {stale_days} 天未更新"
        issues = [{
            "type": k, "label": labels.get(k, k), "count": v,
            "pct": round(v / total * 100, 1),
        } for k, v in sorted(counter.items(), key=lambda x: -x[1])]
        rows.sort(key=lambda r: (r["score"], r["title"]))
        return Response({
            "note_count": total, "avg_score": avg, "grade": overall,
            "distribution": distribution, "issues": issues, "stale_days": stale_days,
            "worst": rows[:limit],
            "perfect": sum(1 for r in rows if r["score"] == 100),
            "scanned": scanned, "scan_limit": self.SCAN_LIMIT,
            "batch_size": self.BATCH_SIZE, "total_notes": total_notes,
            "truncated": total_notes > scanned,
        })


# ---------------- F573 笔记来源统计 ----------------

class NoteSourcesView(APIView):
    """F573 笔记来源统计（手动/模板/导入/复制/双链/拆分）"""

    def get(self, request):
        qs = _note_qs(request.user).filter(is_deleted=False)
        rows = list(qs.values("source").annotate(c=Count("id"), w=Sum("words")).order_by("-c"))
        total = sum(r["c"] for r in rows)
        total_words = sum(r["w"] or 0 for r in rows)
        items = [{
            "source": r["source"] or "manual",
            "label": SOURCE_LABELS.get(r["source"] or "manual", "其它"),
            "count": r["c"], "words": r["w"] or 0,
            "pct": round(r["c"] / total * 100, 1) if total else 0.0,
        } for r in rows]
        return Response({
            "list": items, "total": total, "total_words": total_words,
            "sources": [{"key": k, "label": v} for k, v in SOURCE_LABELS.items()],
        })


# ---------------- F574 个人片段库 ----------------

def _snippet_data(s):
    return {"id": s.id, "title": s.title, "content": s.content, "tag": s.tag,
            "use_count": s.use_count, "preview": (s.content or "")[:80],
            "created_at": s.created_at, "updated_at": s.updated_at}


class NoteSnippetView(APIView):
    """F574 个人片段库：列表 / 新建"""

    def get(self, request):
        qs = NoteSnippet.objects.filter(owner=request.user)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q))
        tag = request.query_params.get("tag")
        if tag:
            qs = qs.filter(tag=tag)
        try:
            limit = _qp_int(request.query_params, "limit", 100, lo=1, hi=500)
        except ValueError as e:
            return _nb(str(e))
        rows = list(qs[:limit])
        return Response({"list": [_snippet_data(s) for s in rows], "total": qs.count(),
                         "use_total": qs.aggregate(s=Sum("use_count"))["s"] or 0})

    def post(self, request):
        title = str(request.data.get("title") or "").strip()[:100]
        content = str(request.data.get("content") or "")
        if not title and not content.strip():
            return _nb("标题或内容不能为空")
        if not title:
            title = content.strip().replace("\n", " ")[:30]
        snippet = NoteSnippet.objects.create(
            owner=request.user, title=title, content=content,
            tag=str(request.data.get("tag") or "")[:50],
        )
        return Response(_snippet_data(snippet), status=status.HTTP_201_CREATED)


class NoteSnippetDetailView(APIView):
    """F574 片段改名 / 改内容 / 删除"""

    def _get(self, request, pk):
        return NoteSnippet.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        snippet = self._get(request, pk)
        if not snippet:
            return _nb("片段不存在", 404)
        if "title" in request.data and str(request.data["title"]).strip():
            snippet.title = str(request.data["title"]).strip()[:100]
        if "content" in request.data:
            snippet.content = str(request.data["content"])
        if "tag" in request.data:
            snippet.tag = str(request.data["tag"])[:50]
        snippet.save()
        return Response(_snippet_data(snippet))

    def delete(self, request, pk):
        snippet = self._get(request, pk)
        if not snippet:
            return _nb("片段不存在", 404)
        snippet.delete()
        return Response({"message": "片段已删除"})


class NoteSnippetUseView(APIView):
    """F574 一键插入：use_count +1"""

    def post(self, request, pk):
        snippet = NoteSnippet.objects.filter(pk=pk, owner=request.user).first()
        if not snippet:
            return _nb("片段不存在", 404)
        snippet.use_count += 1
        snippet.save(update_fields=["use_count"])
        return Response({"message": "已插入", "use_count": snippet.use_count,
                         "content": snippet.content})


# ---------------- F575 合并 / F576 拆分 ----------------

class NoteMergeView(APIView):
    """F575 两篇笔记合并：源并入目标（可选保留源）"""

    def post(self, request):
        try:
            source_id = int(request.data.get("source_id"))
            target_id = int(request.data.get("target_id"))
        except (TypeError, ValueError):
            return _nb("source_id / target_id 必须是整数")
        # #55：keep_source 等参数必须在任何写入之前校验完，避免「已合并却报错」
        try:
            keep = parse_bool(request.data.get("keep_source"), default=False, field="keep_source")
        except ValidationError as exc:
            detail = exc.detail
            return _nb(str(detail[0]) if isinstance(detail, (list, tuple)) and detail else "keep_source 必须是布尔值")
        if source_id == target_id:
            return _nb("不能与自身合并")
        source = _get_note(request.user, source_id, include_deleted=True, write=True)
        target = _get_note(request.user, target_id, include_deleted=True, write=True)
        if not source:
            return _nb("源笔记不存在", 404)
        if not target:
            return _nb("目标笔记不存在", 404)
        if source.is_deleted or target.is_deleted:
            return _nb("回收站中的笔记不能合并")
        # #55：目标写入 + 源删除整体事务，任一步失败都不会留下半合并状态
        with transaction.atomic():
            NoteVersion.objects.create(
                note=target, version=target.version, title=target.title,
                content=target.content, created_by=request.user,
            )
            sep = f"\n\n---\n\n# {source.title}\n\n" if (source.title or "").strip() else "\n\n"
            target.content = ((target.content or "").rstrip() + sep + (source.content or "")).strip()
            target.words = count_words(target.content)
            target.version += 1
            target.tags.add(*source.tags.all())
            if not target.folder_id and source.folder_id:
                target.folder_id = source.folder_id
            if not target.color and source.color:
                target.color = source.color
            target.save()
            if not keep:
                source.outgoing_links.all().delete()
                source.is_deleted = True
                source.deleted_at = timezone.now()
                source.save(update_fields=["is_deleted", "deleted_at"])

        # 双链重建放在提交之后：即使解析异常也不会把合并事务拖进 rollback-only
        def _rebuild():
            try:
                link_lib.rebuild_links_for_note(target)
            except Exception:
                logger.exception("B23：静默兜底已登记（notes/views.py:1383 原为 pass）——review 是否应收窄异常类型")

        transaction.on_commit(_rebuild)
        if keep:
            message = f"已合并到「{target.title}」（源笔记保留）"
        else:
            message = f"已合并到「{target.title}」"
        return Response({
            "message": message, "source_deleted": not keep,
            "target": NoteSerializer(target).data,
        })


class NoteSplitView(APIView):
    """F576 按一级标题（# ）拆分笔记为多篇"""

    def post(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True, write=True)
        if not note:
            return _nb("笔记不存在", 404)
        if note.is_deleted:
            return _nb("回收站中的笔记不能拆分")
        keep_raw = request.data.get("keep_original", True)
        keep_original = str(keep_raw).lower() not in ("false", "0", "no")
        preview = str(request.data.get("preview", "")).lower() in ("1", "true")
        parts = _split_markdown_into_notes(note.content or "")
        if len(parts) < 2:
            return _nb("正文没有多个一级标题（# 开头），无法拆分")
        if preview:
            return Response({
                "preview": True, "count": len(parts),
                "sections": [{"title": p["title"], "words": count_words(p["content"])} for p in parts],
            })
        created = []
        for p in parts:
            n = Note.objects.create(
                title=p["title"][:200], content=p["content"], owner=note.owner,
                parent=note.parent, folder=note.folder, source="split",
                color=note.color, words=count_words(p["content"]),
            )
            n.tags.set(note.tags.all())
            created.append(n)
        original_deleted = False
        if not keep_original:
            note.is_deleted = True
            note.deleted_at = timezone.now()
            note.save(update_fields=["is_deleted", "deleted_at"])
            original_deleted = True
        return Response({
            "message": f"已拆分为 {len(created)} 篇", "count": len(created),
            "created": [NoteSerializer(n).data for n in created],
            "original_deleted": original_deleted,
        })


# ---------------- F579 每周回顾清单 ----------------

class WeeklyReviewView(APIView):
    """F579 每周回顾清单：本周新增/更新/字数/标签/待办/新链/陈旧笔记"""

    def get(self, request):
        today = timezone.localdate()
        week_str = request.query_params.get("week")
        try:
            if week_str:
                y_str, w_str = str(week_str).upper().split("-W")
                start = date.fromisocalendar(int(y_str), int(w_str), 1)
            else:
                iso = today.isocalendar()
                start = date.fromisocalendar(iso.year, iso.week, 1)
        except (ValueError, TypeError):
            return _nb("week 格式应为 YYYY-Www，如 2026-W39")
        end = start + timedelta(days=6)
        qs = _note_qs(request.user).filter(is_deleted=False)
        created = list(qs.filter(created_at__date__gte=start, created_at__date__lte=end)
                       .order_by("created_at"))
        created_ids = {n.id for n in created}
        updated = [n for n in qs.filter(updated_at__date__gte=start, updated_at__date__lte=end)
                   .order_by("-updated_at") if n.id not in created_ids]
        words_written = WordActivity.objects.filter(
            owner=request.user, date__gte=start, date__lte=end
        ).aggregate(s=Sum("delta"))["s"] or 0
        words_new = sum(n.words or 0 for n in created)
        tag_counts = {}
        open_todos = done_todos = 0
        for n in created + updated:
            for t in n.tags.values_list("name", flat=True):
                tag_counts[t] = tag_counts.get(t, 0) + 1
            for item in _scan_todos(n):
                if item["done"]:
                    done_todos += 1
                else:
                    open_todos += 1
        top_tags = sorted([{"name": k, "count": v} for k, v in tag_counts.items()],
                          key=lambda x: -x["count"])[:10]
        stale_cut = start - timedelta(days=28)
        stale = list(qs.filter(updated_at__date__lt=stale_cut).order_by("updated_at")[:20])
        from notes.models import NoteLink as _NL
        new_links = _NL.objects.filter(
            owner=request.user, created_at__date__gte=start, created_at__date__lte=end
        ).count()
        week_no = start.isocalendar().week
        iso_year = start.isocalendar().year

        def _mini(n):
            return {"id": n.id, "title": n.title, "words": n.words, "color": n.color,
                    "is_pinned": n.is_pinned, "updated_at": n.updated_at,
                    "created_at": n.created_at}

        return Response({
            "week": f"{iso_year}-W{week_no:02d}", "start": start, "end": end,
            "prev_week": f"{(start - timedelta(days=7)).isocalendar().year}-W{(start - timedelta(days=7)).isocalendar().week:02d}",
            "next_week": f"{(start + timedelta(days=7)).isocalendar().year}-W{(start + timedelta(days=7)).isocalendar().week:02d}",
            "stats": {
                "created": len(created), "updated": len(updated),
                "words_written": words_written, "words_new": words_new,
                "open_todos": open_todos, "done_todos": done_todos,
                "new_links": new_links, "stale": len(stale),
            },
            "top_tags": top_tags,
            "created_notes": [_mini(n) for n in created[:20]],
            "updated_notes": [_mini(n) for n in updated[:20]],
            "stale_notes": [_mini(n) for n in stale[:20]],
        })


# ---------------- F580 `- [ ]` 待办抽取清单 ----------------

class NoteTodosView(APIView):
    """F580 从笔记正文抽取 `- [ ]` 待办清单"""

    def get(self, request):
        qs = _note_qs(request.user).filter(is_deleted=False)
        note_id = request.query_params.get("note_id")
        if note_id:
            try:
                qs = qs.filter(id=int(note_id))
            except (TypeError, ValueError):
                return _nb("note_id 必须是整数")
        include_done = request.query_params.get("include_done", "1") != "0"
        try:
            limit = _qp_int(request.query_params, "limit", 500, lo=1, hi=2000)
        except ValueError as e:
            return _nb(str(e))
        # #145：先用 DB 条件把「正文里没有待办标记」的笔记挡掉，再 only() 只取必要列，
        # 避免每次轮询都拉 2000 篇完整正文 + 前缀字段。
        qs = qs.filter(
            Q(content__contains="[ ]") | Q(content__contains="[x]") | Q(content__contains="[X]")
        ).only("id", "title", "color", "content", "updated_at")
        items, open_c, done_c = [], 0, 0
        # #56：open/done 计数必须覆盖**全量**筛选结果，不能只统计 limit 截断前的部分；
        # 这里单趟 iterator 既完成全量计数，又攒够 limit 条就停止 append。
        for n in qs.iterator(chunk_size=200):
            for item in _scan_todos(n):
                if item["done"]:
                    done_c += 1
                else:
                    open_c += 1
                if len(items) >= limit:
                    continue
                if not include_done and item["done"]:
                    continue
                items.append({
                    "note_id": n.id, "note_title": n.title, "color": n.color,
                    "line_no": item["line_no"], "text": item["text"], "done": item["done"],
                    "updated_at": n.updated_at,
                })
        return Response({"list": items, "total": len(items),
                         "open_count": open_c, "done_count": done_c})


class NoteTodoToggleView(APIView):
    """F580 勾选 / 取消勾选某一行待办（写回正文并留版本）"""

    def post(self, request):
        try:
            note_id = int(request.data.get("note_id"))
            line_no = int(request.data.get("line_no"))
        except (TypeError, ValueError):
            return _nb("note_id / line_no 必须是整数")
        note = _get_note(request.user, note_id, include_deleted=True, write=True)
        if not note:
            return _nb("笔记不存在", 404)
        lines = (note.content or "").split("\n")
        if line_no < 0 or line_no >= len(lines):
            return _nb("行号不存在")
        m = TODO_LINE_RE.match(lines[line_no])
        if not m:
            return _nb("该行不是待办项")
        NoteVersion.objects.create(
            note=note, version=note.version, title=note.title,
            content=note.content, created_by=request.user,
        )
        pos = lines[line_no].find("[")
        new_state = " " if m.group(1).lower() == "x" else "x"
        lines[line_no] = lines[line_no][:pos + 1] + new_state + lines[line_no][pos + 2:]
        note.content = "\n".join(lines)
        note.words = count_words(note.content)
        note.version += 1
        note.save(update_fields=["content", "words", "version", "updated_at"])
        return Response({"message": "已更新待办", "done": new_state == "x",
                         "line_no": line_no, "text": m.group(2).strip()[:300]})


# ---------------- F581 参考文献引用格式 ----------------

class NoteCitationView(APIView):
    """F581 引用格式生成：GB/T 7714-2015 / APA 7th"""

    STYLES = [
        {"key": "gbt7714", "label": "GB/T 7714-2015"},
        {"key": "apa", "label": "APA 7th"},
    ]

    def get(self, request):
        style = (request.query_params.get("style") or "gbt7714").lower()
        if style not in ("gbt7714", "apa"):
            return _nb("style 只能是 gbt7714 或 apa")
        ids_raw = (request.query_params.get("ids") or "").strip()
        notes = []
        if ids_raw:
            try:
                ids = [int(x) for x in ids_raw.split(",") if str(x).strip()][:50]
            except ValueError:
                return _nb("ids 必须是逗号分隔的整数")
            found = {n.id: n for n in _note_qs(request.user).filter(id__in=ids, is_deleted=False)}
            notes = [found[i] for i in ids if i in found]
        else:
            notes = list(_note_qs(request.user).filter(is_deleted=False).order_by("-updated_at")[:10])
        items = [self._cite(n, style, request) for n in notes]
        labels = dict(self.STYLES)
        return Response({
            "style": style, "style_label": labels.get(style, style),
            "styles": self.STYLES, "items": items, "total": len(items),
        })

    @staticmethod
    def _cite(note, style, request):
        author = (getattr(note.owner, "display_name", "")
                  or getattr(note.owner, "username", "") or "佚名")
        created = timezone.localtime(note.created_at)
        today = timezone.localtime(timezone.now())
        url = ""
        if note.is_public and note.share_token:
            url = request.build_absolute_uri(f"/api/notes/public/{note.share_token}/")
        if style == "apa":
            base = f"{author}. ({created.year}, {created.month}月{created.day}日). {note.title}. 个人笔记知识库."
            text = f"{base} {url}" if url else base
        else:
            base = f"{author}. {note.title}[EB/OL]. ({created:%Y-%m-%d})[{today:%Y-%m-%d}]. "
            text = base + (url if url else "个人笔记知识库.")
        return {"id": note.id, "title": note.title, "author": author, "text": text,
                "is_public": note.is_public, "url": url}


# ---------------- F582 笔记分组文件夹 ----------------

class NoteFolderView(APIView):
    """F582 笔记分组文件夹：列表（含计数）/ 新建"""

    def get(self, request):
        rows = []
        for f in NoteFolder.objects.filter(owner=request.user).prefetch_related("notes"):
            rows.append({
                "id": f.id, "name": f.name, "parent": f.parent_id,
                "note_count": f.notes.filter(is_deleted=False).count(),
            })
        return Response({"list": rows, "total": len(rows)})

    def post(self, request):
        name = str(request.data.get("name") or "").strip()[:100]
        if not name:
            return _nb("文件夹名称不能为空")
        if NoteFolder.objects.filter(owner=request.user, name=name).exists():
            return _nb("同名文件夹已存在")
        parent = _folder_of(request.user, request.data.get("parent"))
        folder = NoteFolder.objects.create(name=name, owner=request.user, parent=parent)
        return Response({"id": folder.id, "name": folder.name, "parent": folder.parent_id,
                         "note_count": 0}, status=status.HTTP_201_CREATED)


class NoteFolderDetailView(APIView):
    """F582 文件夹重命名 / 移动 / 删除（笔记自动脱离）"""

    def _get(self, request, pk):
        return NoteFolder.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        folder = self._get(request, pk)
        if not folder:
            return _nb("文件夹不存在", 404)
        if "name" in request.data:
            name = str(request.data["name"]).strip()[:100]
            if not name:
                return _nb("名称不能为空")
            if NoteFolder.objects.filter(owner=request.user, name=name).exclude(pk=folder.pk).exists():
                return _nb("同名文件夹已存在")
            folder.name = name
        if "parent" in request.data:
            pid = request.data.get("parent")
            parent = _folder_of(request.user, pid)
            if pid not in (None, "", "null", "0", 0) and parent is None:
                return _nb("父文件夹不存在")
            if parent and parent.pk == folder.pk:
                return _nb("不能移动到自身")
            # 环检测：不能移动到自身的子文件夹下
            if parent and _would_create_cycle(folder, parent):
                return _nb("不能移动到自身的子文件夹下")
            folder.parent = parent
        folder.save()
        return Response({"id": folder.id, "name": folder.name, "parent": folder.parent_id})

    def delete(self, request, pk):
        folder = self._get(request, pk)
        if not folder:
            return _nb("文件夹不存在", 404)
        moved = folder.notes.filter(is_deleted=False).count()
        folder.delete()
        return Response({"message": f"文件夹已删除（{moved} 篇笔记回到未分组）", "notes_moved": moved})


# =====================================================================
# ===== 以下为 F570 / F571 / F577 / F578 的补充实现（只增不改） =========
# 说明：既有 NoteOutlineView（无行号）/ PATCH 置顶 / 详情阅读分钟数保持不变，
#      这里新增独立端点，避免改动任何既有接口的响应结构。
# =====================================================================


def _anchor_for(title: str, index: int) -> str:
    """为标题生成稳定锚点 id（供阅读模式目录跳转）"""
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (title or "").strip().lower()).strip("-")
    return f"h{index}-{s}" if s else f"h{index}"


def extract_outline_with_lines(text: str):
    """F570 提取带行号的大纲（行号从 0 开始，对应正文 split('\\n') 下标）"""
    outline = []
    for idx, line in enumerate((text or "").split("\n")):
        m = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if not m:
            continue
        outline.append({
            "level": len(m.group(1)),
            "title": m.group(2).strip(),
            "line_no": idx,
            "anchor": _anchor_for(m.group(2).strip(), len(outline)),
        })
    return outline


class NoteOutlineLinesView(APIView):
    """F570 大纲目录点击跳转：返回带行号的标题目录

    GET /api/notes/<pk>/outline-lines/
    前端可据 line_no 精确定位到正文对应行（旧 /outline/ 保持不变）
    """

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return _nb("笔记不存在", 404)
        outline = extract_outline_with_lines(note.content)
        return Response({
            "note_id": note.id, "title": note.title,
            "outline": outline, "total": len(outline),
            "line_count": len((note.content or "").split("\n")),
        })


class NotePinView(APIView):
    """F571 笔记置顶：显式置顶 / 取消置顶（不改动既有 PATCH 行为）

    POST /api/notes/<pk>/pin/        切换置顶
    POST /api/notes/<pk>/pin/  {"pinned": true|false}  显式指定
    """

    def post(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True, write=True)
        if not note:
            return _nb("笔记不存在", 404)
        if "pinned" in request.data:
            note.is_pinned = parse_bool(request.data["pinned"], field="pinned")
        else:
            note.is_pinned = not note.is_pinned
        note.save(update_fields=["is_pinned", "updated_at"])
        return Response({"message": "已置顶" if note.is_pinned else "已取消置顶",
                         "id": note.id, "is_pinned": note.is_pinned})


def _parse_reading_blocks(text: str):
    """F577 把 Markdown 正文解析为阅读态区块（标题/段落/列表/引用/代码/分割线）"""
    lines = (text or "").split("\n")
    blocks = []
    toc = []
    in_code = False
    code_buf = []
    para_buf = []
    para_start = 0

    def flush_para():
        if para_buf:
            blocks.append({"type": "paragraph", "line_no": para_start,
                           "text": "\n".join(para_buf).strip()})
            para_buf.clear()

    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_code:
                blocks.append({"type": "code", "line_no": idx - len(code_buf),
                               "text": "\n".join(code_buf), "lang": ""})
                code_buf = []
                in_code = False
            else:
                flush_para()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue
        if not stripped:
            flush_para()
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if h:
            flush_para()
            title = h.group(2).strip()
            anchor = _anchor_for(title, len(toc))
            blocks.append({"type": "heading", "level": len(h.group(1)),
                           "text": title, "line_no": idx, "anchor": anchor})
            toc.append({"level": len(h.group(1)), "title": title,
                        "line_no": idx, "anchor": anchor})
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            blocks.append({"type": "hr", "line_no": idx})
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", stripped):
            flush_para()
            ordered = bool(re.match(r"^\d+[.)]\s+", stripped))
            body = re.sub(r"^([-*+]|\d+[.)])\s+", "", stripped)
            blocks.append({"type": "list_item", "line_no": idx,
                           "text": body, "ordered": ordered,
                           "checked": None})
            continue
        if stripped.startswith(">"):
            flush_para()
            blocks.append({"type": "quote", "line_no": idx,
                           "text": stripped.lstrip(">").strip()})
            continue
        if not para_buf:
            para_start = idx
        para_buf.append(stripped)
    if in_code and code_buf:
        blocks.append({"type": "code", "line_no": len(lines) - len(code_buf),
                       "text": "\n".join(code_buf), "lang": ""})
    flush_para()
    return blocks, toc


class NoteReadingView(APIView):
    """F577 阅读模式：返回排版态所需数据（区块 + 目录 + 阅读时长）

    GET /api/notes/<pk>/reading/
    """

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return _nb("笔记不存在", 404)
        content = note.content or ""
        blocks, toc = _parse_reading_blocks(content)
        words = note.words or count_words(content)
        images = len(re.findall(r"!\[[^\]]*\]\([^)]*\)", content))
        links = len(re.findall(r"(?<!!)\[[^\]]+\]\([^)]*\)", content))
        return Response({
            "note_id": note.id, "title": note.title, "content": content,
            "words": words, "char_count": len(content),
            "reading_minutes": max(1, round(words / 300)) if words else 0,
            "paragraph_count": sum(1 for b in blocks if b["type"] == "paragraph"),
            "heading_count": len(toc), "image_count": images, "link_count": links,
            "block_count": len(blocks), "blocks": blocks, "toc": toc,
        })


def _word_data(item):
    return {"id": item.id, "word": item.word, "phonetic": item.phonetic,
            "meaning": item.meaning, "mastered": item.mastered,
            "source": item.source, "created_at": item.created_at}


class NoteWordbookView(APIView):
    """F578 选词存生词：把笔记中选中的词存入学习区生词本

    只读引用 learning.models.WordbookItem，不改动 learning app。
    POST /api/notes/wordbook/  {"word": "...", "meaning": "", "phonetic": "", "note_id": 1}
    GET  /api/notes/wordbook/?q= 列出本人已存生词
    """

    def get(self, request):
        try:
            from learning.models import WordbookItem
        except Exception:
            return _nb("学习区生词本不可用", 503)
        qs = WordbookItem.objects.filter(owner=request.user)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(word__icontains=q) | Q(meaning__icontains=q))
        try:
            limit = _qp_int(request.query_params, "limit", 200, lo=1, hi=1000)
        except ValueError as e:
            return _nb(str(e))
        rows = list(qs[:limit])
        return Response({"list": [_word_data(w) for w in rows], "total": qs.count()})

    def post(self, request):
        try:
            from learning.models import WordbookItem
        except Exception:
            return _nb("学习区生词本不可用", 503)
        word = str(request.data.get("word") or "").strip()
        if not word:
            return _nb("word 不能为空")
        if len(word) > 64:
            return _nb("word 过长（最多 64 字符）")
        meaning = str(request.data.get("meaning") or "")[:255]
        phonetic = str(request.data.get("phonetic") or "")[:48]
        note_id = request.data.get("note_id")
        if note_id not in (None, "", "null"):
            try:
                note_id = int(note_id)
            except (TypeError, ValueError):
                return _nb("note_id 必须是整数")
            if not _get_note(request.user, note_id, include_deleted=True):
                return _nb("笔记不存在", 404)
        item, created = WordbookItem.objects.get_or_create(
            owner=request.user, word=word,
            defaults={"meaning": meaning, "phonetic": phonetic, "source": "note"},
        )
        if not created and (meaning or phonetic):
            if meaning:
                item.meaning = meaning
            if phonetic:
                item.phonetic = phonetic
            item.save(update_fields=["meaning", "phonetic"])
        return Response({
            "message": "已存入生词本" if created else "生词已存在",
            "created": created, "item": _word_data(item),
            "total": WordbookItem.objects.filter(owner=request.user).count(),
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


# =====================================================================
# ============ F236–F260 笔记协作 / 素材 / 模板 / 推荐（只增不改） =======
# =====================================================================


def _comment_tree_data(note):
    """按创建时间返回评论（顶层按 replies 归组，前端仍拿到扁平 parent 关系）"""
    qs = note.comments.select_related("author").order_by("created_at")
    return NoteCommentSerializer(qs, many=True).data


class NoteCommentView(APIView):
    """F236 段落讨论：列表 / 新建（支持回复）"""

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return _nb("笔记不存在", 404)
        data = _comment_tree_data(note)
        return Response({"list": data, "total": len(data),
                         "open_count": sum(1 for d in data if not d["resolved"])})

    def post(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True, write=True)
        if not note:
            return _nb("笔记不存在或无权评论", 404)
        content = str(request.data.get("content") or "").strip()
        if not content:
            return _nb("评论内容不能为空")
        parent = None
        pid = request.data.get("parent")
        if pid not in (None, "", "null"):
            try:
                parent = NoteComment.objects.filter(pk=int(pid), note=note).first()
            except (TypeError, ValueError):
                return _nb("parent 必须是整数")
            if parent is None:
                return _nb("父评论不存在", 404)
        comment = NoteComment.objects.create(
            note=note, author=request.user, parent=parent,
            quote=str(request.data.get("quote") or "")[:500],
            content=content[:5000],
        )
        return Response(NoteCommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class NoteCommentDetailView(APIView):
    """F236 评论标记解决 / 修改内容 / 删除（作者或笔记所有者可操作）"""

    def _get(self, request, pk, cid):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return None, None
        comment = NoteComment.objects.filter(pk=cid, note=note).first()
        if comment is None:
            return note, None
        if comment.author_id != request.user.id and note.owner_id != request.user.id:
            return note, None
        return note, comment

    def patch(self, request, pk, cid):
        note, comment = self._get(request, pk, cid)
        if not note:
            return _nb("笔记不存在", 404)
        if not comment:
            return _nb("评论不存在或无权修改", 404)
        if "resolved" in request.data:
            comment.resolved = parse_bool(request.data["resolved"], field="resolved")
            # 顶层评论标记解决时，回复一并解决，避免残留悬挂讨论
            if comment.resolved and comment.parent_id is None:
                comment.replies.update(resolved=True)
        if "content" in request.data and str(request.data["content"]).strip():
            comment.content = str(request.data["content"]).strip()[:5000]
        comment.save()
        return Response(NoteCommentSerializer(comment).data)

    def delete(self, request, pk, cid):
        note, comment = self._get(request, pk, cid)
        if not note:
            return _nb("笔记不存在", 404)
        if not comment:
            return _nb("评论不存在或无权删除", 404)
        comment.delete()
        return Response({"message": "评论已删除"})


class NoteAttachmentView(APIView):
    """F237 笔记附件：列表 / 绑定文件中心已有文件"""

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return _nb("笔记不存在", 404)
        qs = note.attachments.select_related("file").order_by("id")
        data = NoteAttachmentSerializer(qs, many=True).data
        return Response({"list": data, "total": len(data)})

    def post(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True, write=True)
        if not note:
            return _nb("笔记不存在或无权修改", 404)
        file = _file_of(request.user, request.data.get("file_id"))
        if file is None:
            return _nb("文件不存在或无权使用", 404)
        att, created = NoteAttachment.objects.get_or_create(
            note=note, file=file,
            defaults={"name": str(request.data.get("name") or file.name)[:255], "size": file.size},
        )
        return Response(
            NoteAttachmentSerializer(att).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class NoteAttachmentDetailView(APIView):
    """F237 移除附件（只解绑，不删文件中心文件）"""

    def delete(self, request, pk, aid):
        note = _get_note(request.user, pk, include_deleted=True, write=True)
        if not note:
            return _nb("笔记不存在或无权修改", 404)
        att = NoteAttachment.objects.filter(pk=aid, note=note).first()
        if not att:
            return _nb("附件不存在", 404)
        att.delete()
        return Response({"message": "附件已移除"})


class NoteFilePickerView(APIView):
    """F237/F239 选文件用的轻量清单（仅本人未删除文件，供封面/附件选择）"""

    def get(self, request):
        try:
            limit = _qp_int(request.query_params, "limit", 30, lo=1, hi=100)
        except ValueError as e:
            return _nb(str(e))
        from files.models import FileMeta

        kind = request.query_params.get("kind")
        qs = FileMeta.objects.filter(owner=request.user, is_deleted=False)
        if kind:
            qs = qs.filter(kind=kind)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
        rows = list(qs.order_by("-created_at")[:limit])
        return Response({"list": [{
            "id": f.id, "name": f.name, "size": f.size, "kind": f.kind, "ext": f.ext,
            "url": f.url, "thumbnail": f.thumbnail_url or f.url,
        } for f in rows], "total": len(rows)})


def _template_data(tpl):
    return NoteTemplateSerializer(tpl).data


def _split_tag_field(raw):
    """模板标签统一存成逗号分隔字符串（列表/字符串/None 均可）"""
    if isinstance(raw, (list, tuple)):
        names = [str(x).strip()[:50] for x in raw if str(x).strip()]
    else:
        names = [x.strip()[:50] for x in str(raw or "").split(",") if x.strip()]
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return ",".join(out)[:200]


class NoteTemplateMineView(APIView):
    """F243 我的模板：列表 / 新建（把当前笔记存为模板）"""

    def get(self, request):
        qs = NoteTemplate.objects.filter(owner=request.user)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q))
        rows = list(qs[:200])
        return Response({"list": [_template_data(t) for t in rows], "total": len(rows)})

    def post(self, request):
        title = str(request.data.get("title") or "").strip()[:200]
        content = str(request.data.get("content") or "")
        if not title and not content.strip():
            return _nb("模板标题或内容不能为空")
        if not title:
            title = content.strip().split("\n", 1)[0][:60] or "未命名模板"
        tpl = NoteTemplate.objects.create(
            owner=request.user, title=title, content=content,
            icon=str(request.data.get("icon") or "").strip()[:8],
            tags=_split_tag_field(request.data.get("tags")),
        )
        return Response(_template_data(tpl), status=status.HTTP_201_CREATED)


class NoteTemplateMineDetailView(APIView):
    """F243 我的模板：修改 / 删除"""

    def _get(self, request, pk):
        return NoteTemplate.objects.filter(pk=pk, owner=request.user).first()

    def patch(self, request, pk):
        tpl = self._get(request, pk)
        if not tpl:
            return _nb("模板不存在", 404)
        if "title" in request.data and str(request.data["title"]).strip():
            tpl.title = str(request.data["title"]).strip()[:200]
        if "content" in request.data:
            tpl.content = str(request.data["content"])
        if "icon" in request.data:
            tpl.icon = str(request.data["icon"] or "").strip()[:8]
        if "tags" in request.data:
            tpl.tags = _split_tag_field(request.data["tags"])
        tpl.save()
        return Response(_template_data(tpl))

    def delete(self, request, pk):
        tpl = self._get(request, pk)
        if not tpl:
            return _nb("模板不存在", 404)
        tpl.delete()
        return Response({"message": "模板已删除"})


class NoteFromMyTemplateView(APIView):
    """F243 从我的模板创建笔记"""

    def post(self, request, pk):
        tpl = NoteTemplate.objects.filter(pk=pk, owner=request.user).first()
        if not tpl:
            return _nb("模板不存在", 404)
        title = str(request.data.get("title") or tpl.title).strip()[:200] or "未命名笔记"
        note = Note.objects.create(
            title=title, content=tpl.content, owner=request.user,
            words=count_words(tpl.content), source="template", icon=tpl.icon,
            folder=_folder_of(request.user, request.data.get("folder")),
        )
        _apply_tags(request.user, note, tpl.tag_list)
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)


TITLE_WORD_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def _title_tokens(title):
    return set(TITLE_WORD_RE.findall((title or "").lower()))


class NoteRelatedView(APIView):
    """F245 相关笔记：共同标签数 × 3 + 标题词重合度打分，排除自身与已双链"""

    LIMIT = 10
    CANDIDATES = 500

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return _nb("笔记不存在", 404)
        # 只在本人笔记内推荐，避免把他人笔记标题/摘要暴露给当前用户
        exclude_ids = {note.id}
        outgoing = set(
            NoteLink.objects.filter(owner_id=note.owner_id, source=note, target__isnull=False)
            .values_list("target_id", flat=True)
        )
        incoming = set(
            NoteLink.objects.filter(owner_id=note.owner_id, target=note)
            .values_list("source_id", flat=True)
        )
        exclude_ids |= outgoing | incoming
        my_tags = set(note.tags.values_list("name", flat=True))
        my_tokens = _title_tokens(note.title)
        candidates = list(
            Note.objects.filter(owner_id=note.owner_id, is_deleted=False)
            .exclude(id__in=exclude_ids)
            .prefetch_related("tags")
            .order_by("-updated_at")[:self.CANDIDATES]
        )
        rows = []
        for c in candidates:
            shared = my_tags & {t.name for t in c.tags.all()}
            overlap = my_tokens & _title_tokens(c.title)
            score = len(shared) * 3 + len(overlap) * 2
            if score <= 0:
                continue
            rows.append({
                "id": c.id, "title": c.title, "icon": c.icon, "color": c.color,
                "words": c.words, "updated_at": c.updated_at,
                "tags": [t.name for t in c.tags.all()],
                "shared_tags": sorted(shared), "score": score,
                "reason": "共同标签 " + "、".join(sorted(shared)) if shared else "标题相似",
            })
        rows.sort(key=lambda r: (-r["score"], r["title"]))
        return Response({"note_id": note.id, "list": rows[:self.LIMIT],
                         "total": len(rows), "limit": self.LIMIT})


class NoteQuickView(APIView):
    """F246 快速记录：只收正文，标题取首行，缺省用「速记 月-日 时:分」"""

    def post(self, request):
        content = str(request.data.get("content") or "")
        if not content.strip():
            return _nb("内容不能为空")
        first = ""
        for line in content.splitlines():
            s = re.sub(r"^\s*(#{1,6}\s+|[-*+]\s+)", "", line).strip()
            if s:
                first = s
                break
        title = first[:200] if first else f"速记 {timezone.localtime():%m-%d %H:%M}"
        note = Note.objects.create(
            title=title, content=content, owner=request.user,
            words=count_words(content), source="quick",
        )
        if isinstance(request.data.get("tags"), list):
            _apply_tags(request.user, note, request.data["tags"])
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)


class NoteTagMergeView(APIView):
    """F256 合并标签：事务内把 from 的笔记关联迁到 to 后删除 from"""

    def post(self, request):
        try:
            from_id = int(request.data.get("from_id"))
            to_id = int(request.data.get("to_id"))
        except (TypeError, ValueError):
            return _nb("from_id / to_id 必须是整数")
        if from_id == to_id:
            return _nb("不能与自身合并")
        with transaction.atomic():
            src = NoteTag.objects.select_for_update().filter(pk=from_id, owner=request.user).first()
            dst = NoteTag.objects.select_for_update().filter(pk=to_id, owner=request.user).first()
            if not src:
                return _nb("源标签不存在", 404)
            if not dst:
                return _nb("目标标签不存在", 404)
            through = Note.tags.through
            exist = set(
                through.objects.filter(notetag_id=dst.id).values_list("note_id", flat=True)
            )
            moved = 0
            for row in through.objects.filter(notetag_id=src.id).only("id", "note_id"):
                if row.note_id in exist:
                    continue
                through.objects.filter(pk=row.pk).update(notetag_id=dst.id)
                moved += 1
            src.delete()
        return Response({
            "message": f"已把「{src.name}」合并到「{dst.name}」（迁移 {moved} 篇）",
            "from_id": from_id, "to_id": dst.id, "moved": moved,
            "use_count": NoteTagSerializer(dst).data.get("use_count", 0),
        })


def _preview_payload(note, request=None):
    """F257 双链悬停预览：标题 + 前 160 字 + 标签 + 更新时间"""
    text = re.sub(r"```[\s\S]*?```", " ", note.content or "")
    text = re.sub(r"[#>*`\[\]!|_-]+", " ", text)
    text = " ".join(text.split())
    return {
        "id": note.id, "title": note.title, "icon": note.icon, "color": note.color,
        "excerpt": text[:160], "words": note.words,
        "tags": list(note.tags.values_list("name", flat=True)[:10]),
        "updated_at": note.updated_at, "is_public": note.is_public,
    }


class NotePreviewView(APIView):
    """F257 单篇笔记预览摘要：GET /api/notes/<pk>/preview/"""

    def get(self, request, pk):
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return _nb("笔记不存在", 404)
        return Response(_preview_payload(note, request))


class NotePreviewByTitleView(APIView):
    """F257 按标题取预览（双链 [[标题]] 悬停时用）：GET /api/notes/preview/?title=xxx"""

    def get(self, request):
        title = (request.query_params.get("title") or "").strip()
        if not title:
            return _nb("title 不能为空")
        qs = _note_qs(request.user).filter(is_deleted=False, title__iexact=title[:200])
        exclude = request.query_params.get("exclude")
        if exclude:
            try:
                qs = qs.exclude(id=int(exclude))
            except (TypeError, ValueError):
                return _nb("exclude 必须是整数")
        note = qs.order_by("-updated_at").first()
        if note is None:
            return _nb("未找到同名笔记", 404)
        return Response(_preview_payload(note, request))


class NotePinOrderView(APIView):
    """F260 置顶区拖拽排序：POST /api/notes/pin-order/ {"note_ids": [3, 1, 2]}"""

    def post(self, request):
        ids = request.data.get("note_ids") or []
        if not isinstance(ids, list) or not ids:
            return _nb("note_ids 不能为空")
        clean = []
        for raw in ids:
            try:
                nid = int(raw)
            except (TypeError, ValueError):
                return _nb("note_ids 必须是整数数组")
            if nid not in clean:
                clean.append(nid)
        owned = set(
            _note_write_qs(request.user).filter(id__in=clean).values_list("id", flat=True)
        )
        with transaction.atomic():
            for idx, nid in enumerate(clean, start=1):
                if nid in owned:
                    Note.objects.filter(pk=nid, owner=request.user).update(pin_order=idx)
        return Response({"message": f"已保存置顶顺序（{len(owned)} 篇）", "count": len(owned)})
