"""笔记视图：CRUD、标签、搜索、版本历史/对比/回滚、分享、回收站、批量、导出、大纲、模板、统计、双链"""
import io
import re
import zipfile

from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core.scoping import is_visible, scope_queryset
from notes import links as link_lib
from notes.models import Note, NoteTag, NoteVersion
from notes.serializers import NoteSerializer, NoteTagSerializer, NoteVersionSerializer


def _note_qs(user):
    """按数据范围取可见笔记（管理员=全部、部门负责人=本部门、普通用户=本人）"""
    return scope_queryset(Note.objects.all(), user)


def _get_note(user, pk, include_deleted=False):
    """单篇可见性校验：详情/更新/导出统一入口"""
    note = _note_qs(user).filter(pk=pk).first()
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
        qs = _note_qs(request.user)
        if request.query_params.get("trash") == "1":
            qs = qs.filter(is_deleted=True).order_by("-deleted_at")
            return Response({"list": NoteSerializer(qs, many=True).data, "total": qs.count()})
        qs = qs.filter(is_deleted=False)
        parent = request.query_params.get("parent")
        if request.query_params.get("all") != "1":
            if parent in (None, "", "null", "0"):
                qs = qs.filter(parent__isnull=True)
            else:
                qs = qs.filter(parent_id=parent)
        tag = request.query_params.get("tag")
        if tag:
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
        data = NoteSerializer(qs, many=True).data
        backlinked = link_lib.all_backlink_ids(request.user.id)
        for item in data:
            item["has_backlink"] = item["id"] in backlinked
        return Response({"list": data, "total": qs.count()})

    def post(self, request):
        title = (request.data.get("title") or "未命名笔记").strip()
        parent_id = request.data.get("parent")
        parent = Note.objects.filter(pk=parent_id, owner=request.user).first() if parent_id else None
        content = request.data.get("content", "")
        note = Note.objects.create(
            title=title, content=content, parent=parent, owner=request.user, words=count_words(content)
        )
        self._tags = request.data.get("tags") or []
        _apply_tags(request.user, note, self._tags)
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)


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
        return Response(data)

    def patch(self, request, pk):
        note = self.get_object(request, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        changed = False
        if "title" in request.data and request.data["title"]:
            note.title = request.data["title"].strip()[:200]
            changed = True
        if "content" in request.data:
            if request.data["content"] != note.content:
                NoteVersion.objects.create(
                    note=note, version=note.version, title=note.title, content=note.content, created_by=request.user
                )
                note.version += 1
                note.content = request.data["content"]
                note.words = count_words(note.content)
                changed = True
        if "parent" in request.data:
            pid = request.data.get("parent")
            note.parent = Note.objects.filter(pk=pid, owner=request.user).first() if pid else None
            changed = True
        for flag in ("is_pinned", "is_favorite", "is_public"):
            if flag in request.data:
                setattr(note, flag, bool(request.data[flag]))
                changed = True
        if "tags" in request.data and isinstance(request.data["tags"], list):
            _apply_tags(request.user, note, request.data["tags"])
            changed = True
        if changed:
            note.save()
        return Response(NoteSerializer(note).data)

    def delete(self, request, pk):
        note = self.get_object(request, pk)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
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
        qs = _note_qs(request.user).filter(id__in=ids)
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
            parent = Note.objects.filter(pk=pid, owner=request.user).first() if pid else None
            n = qs.update(parent=parent)
            return Response({"message": f"已移动 {n} 篇"})
        return Response({"message": "未知操作"}, status=400)


class NoteTrashView(APIView):
    """回收站：列表 / 清空"""

    def get(self, request):
        qs = _note_qs(request.user).filter(is_deleted=True).order_by("-deleted_at")
        return Response({"list": NoteSerializer(qs, many=True).data, "total": qs.count()})

    def delete(self, request):
        n = _note_qs(request.user).filter(is_deleted=True).delete()[0]
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
        )
        copy.tags.set(note.tags.all())
        return Response(NoteSerializer(copy).data, status=201)


class NoteTreeView(APIView):
    def get(self, request):
        def build(parent_id):
            qs = _note_qs(request.user).filter(parent_id=parent_id, is_deleted=False).order_by("-is_pinned", "updated_at")
            return [
                {"id": n.id, "title": n.title, "is_public": n.is_public, "is_favorite": n.is_favorite,
                 "is_pinned": n.is_pinned, "children": build(n.id)}
                for n in qs
            ]
        return Response({"tree": build(None)})


class NoteTagListView(APIView):
    """标签列表（含用量）/ 新建标签"""

    def get(self, request):
        qs = NoteTag.objects.filter(owner=request.user).annotate(c=Count("notes")).order_by("-c", "name")
        data = NoteTagSerializer(qs, many=True).data
        return Response({"list": data, "total": qs.count()})

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
        if "name" in request.data and request.data["name"].strip():
            tag.name = request.data["name"].strip()[:50]
        if "color" in request.data:
            tag.color = request.data["color"]
        tag.save()
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
        v1 = request.query_params.get("from")
        v2 = request.query_params.get("to")
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
        note = _get_note(request.user, pk, include_deleted=True)
        if not note:
            return Response({"message": "笔记不存在"}, status=404)
        snap = NoteVersion.objects.filter(note=note, version=version).first()
        if not snap:
            return Response({"message": "版本不存在"}, status=404)
        NoteVersion.objects.create(
            note=note, version=note.version, title=note.title, content=note.content, created_by=request.user
        )
        note.title, note.content = snap.title, snap.content
        note.words = count_words(note.content)
        note.version += 1
        note.save()
        return Response({"message": f"已回滚到 v{version}", "note": NoteSerializer(note).data})


class NoteShareView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        note = Note.objects.filter(share_token=token, is_public=True, is_deleted=False).first()
        if not note:
            return Response({"message": "笔记不存在或未公开"}, status=404)
        return Response({"title": note.title, "content": note.content, "updated_at": note.updated_at,
                         "version": note.version, "outline": extract_outline(note.content)})


class NoteRecentView(APIView):
    def get(self, request):
        qs = _note_qs(request.user).filter(is_deleted=False).order_by("-updated_at")[:10]
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
        filename = re.sub(r'[\\/:*?"<>|]', "_", note.title)
        resp["Content-Disposition"] = f"attachment; filename={filename}.md"
        return resp


class NoteExportAllView(APIView):
    """导出全部笔记为 zip"""

    def get(self, request):
        notes = _note_qs(request.user).filter(is_deleted=False)
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
        resp["Content-Disposition"] = "attachment; filename=notes.zip"
        return resp


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
        limit = min(int(request.query_params.get("limit", 300)), 1000)
        return Response(link_lib.link_graph(request.user.id, limit=limit))


class NoteLinkSuggestView(APIView):
    """[[ 输入时的标题联想

    GET /api/notes/link-suggest/?q=架构&exclude=12
    """

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        exclude = request.query_params.get("exclude")
        limit = min(int(request.query_params.get("limit", 10)), 30)
        return Response({"list": link_lib.suggest_titles(
            request.user.id, q, exclude_id=int(exclude) if exclude else None, limit=limit
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
        note = Note.objects.create(title=title[:200], content="", owner=request.user)
        return Response(NoteSerializer(note).data, status=201)


class NoteLinkRebuildView(APIView):
    """重建当前用户的全部双链关系（正文被外部改动或索引异常时使用）

    POST /api/notes/links/rebuild/
    """

    def post(self, request):
        qs = _note_qs(request.user).filter(is_deleted=False)
        total = 0
        for note in qs.iterator():
            total += link_lib.rebuild_links_for_note(note) or 0
        dangling = link_lib.dangling_notes(request.user.id)
        return Response({"message": "双链已重建", "notes": qs.count(), "links": total,
                         "dangling": len(dangling)})
