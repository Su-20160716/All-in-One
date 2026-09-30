"""[[双链]]（wiki link）解析与维护

支持的语法
----------
    [[笔记标题]]               → 链接到同名笔记，未创建时为「悬浮链接」
    [[笔记标题|显示文字]]       → 带别名
    [[笔记标题#小节]]           → 忽略小节，仍按标题解析

实现要点
--------
- 出链在笔记保存时重建（core.signals → rebuild_links_for_note）
- target 为空表示目标笔记尚不存在；一旦同名笔记被创建，
  通过 resolve_dangling_links 自动把等待中的链接接上（例如笔记改标题/新建）
- 反向链接查询直接从 NoteLink 表反查，无需扫描正文
"""
from __future__ import annotations

import re

from django.db.models import Q

# [[标题]] 或 [[标题|别名]]
LINK_RE = re.compile(r"\[\[([^\[\]]{1,200}?)(?:\|([^\[\]]{1,200}))?\]\]")


def parse_links(content: str):
    """从 Markdown 正文提取链接，返回 [{"title": str, "alias": str}]（按出现顺序去重）"""
    seen, out = set(), []
    for m in LINK_RE.finditer(content or ""):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        # 去掉 #小节 锚点
        title = raw.split("#", 1)[0].strip()
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title[:200], "alias": (m.group(2) or "").strip()[:200]})
    return out


def resolve_title(owner_id: int, title: str):
    """按标题（不区分大小写）解析目标笔记；找不到返回 None"""
    from notes.models import Note

    return (
        Note.objects.filter(owner_id=owner_id, is_deleted=False, title__iexact=title)
        .order_by("-updated_at")
        .first()
    )


def rebuild_links_for_note(note):
    """重建单篇笔记的出链（幂等），并顺带把指向它的悬浮链接接上"""
    from notes.models import NoteLink

    if note is None or not note.pk:
        return 0
    NoteLink.objects.filter(source=note).delete()
    links = parse_links(note.content)
    if not links:
        return 0

    # 一次查出所有可能的目标，避免 N 次查询
    titles = [l["title"].lower() for l in links]
    candidates = {}
    from notes.models import Note

    for n in Note.objects.filter(
        owner_id=note.owner_id, is_deleted=False,
        title__iregex=r"^(" + "|".join(re.escape(t) for t in titles[:200]) + r")$",
    ):
        candidates.setdefault(n.title.lower(), n.id)

    rows = []
    for link in links:
        rows.append(NoteLink(
            source=note, target_id=candidates.get(link["title"].lower()),
            owner_id=note.owner_id,
            target_title=link["title"], alias=link["alias"],
        ))
    NoteLink.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def resolve_dangling_links(owner_id: int, title: str):
    """把「指向某个标题、但当时目标不存在」的链接接上（笔记新建/改名后调用）"""
    from notes.models import Note, NoteLink

    note = (
        Note.objects.filter(owner_id=owner_id, is_deleted=False, title__iexact=title)
        .order_by("-updated_at")
        .first()
    )
    if not note:
        return 0
    return NoteLink.objects.filter(
        owner_id=owner_id, target__isnull=True, target_title__iexact=title
    ).update(target=note)


def backlinks(note):
    """反向链接：谁引用了本笔记（返回来源笔记摘要）"""
    from notes.models import NoteLink

    qs = NoteLink.objects.filter(target=note).select_related("source").order_by("-source__updated_at")
    return [
        {
            "link_id": l.id,
            "note_id": l.source_id,
            "title": l.source.title,
            "alias": l.alias,
            "excerpt": _mention_excerpt(l.source.content, note.title if not l.alias else l.target_title),
            "updated_at": l.source.updated_at,
        }
        for l in qs
        if not l.source.is_deleted
    ]


def outgoing_links(note):
    """出链：本笔记引用了谁（区分已解析 / 悬浮）"""
    from notes.models import NoteLink

    qs = NoteLink.objects.filter(source=note).order_by("id")
    out = []
    for l in qs:
        item = {
            "link_id": l.id,
            "title": l.target_title,
            "alias": l.alias,
            "resolved": l.resolved,
            "target_id": l.target_id,
        }
        if l.resolved and l.target:
            item["target_title"] = l.target.title
            item["target_deleted"] = l.target.is_deleted
        out.append(item)
    return out


def link_graph(owner_id: int, limit: int = 300):
    """整库双链图谱：nodes + edges（供关系图可视化）"""
    from notes.models import Note, NoteLink

    notes = Note.objects.filter(owner_id=owner_id, is_deleted=False).only(
        "id", "title", "is_favorite", "is_pinned", "updated_at"
    )[:limit]
    note_map = {n.id: n for n in notes}
    node_ids = set(note_map)

    links = NoteLink.objects.filter(owner_id=owner_id, target__in=node_ids).select_related("source")
    edges, degree = [], {}
    for l in links:
        if l.source_id not in node_ids or l.target_id not in node_ids:
            continue
        if l.source_id == l.target_id:
            continue
        edges.append({"source": l.source_id, "target": l.target_id, "label": l.target_title})
        degree[l.source_id] = degree.get(l.source_id, 0) + 1
        degree[l.target_id] = degree.get(l.target_id, 0) + 1

    nodes = [
        {
            "id": n.id,
            "title": n.title,
            "degree": degree.get(n.id, 0),
            "is_favorite": n.is_favorite,
            "is_orphan": degree.get(n.id, 0) == 0,
        }
        for n in note_map.values()
    ]
    nodes.sort(key=lambda x: x["degree"], reverse=True)
    return {"nodes": nodes, "edges": edges, "node_count": len(nodes), "edge_count": len(edges)}


def suggest_titles(owner_id: int, keyword: str, exclude_id: int = None, limit: int = 10):
    """[[ 输入时的标题联想"""
    from notes.models import Note

    qs = Note.objects.filter(owner_id=owner_id, is_deleted=False)
    if keyword:
        qs = qs.filter(title__icontains=keyword)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    qs = qs.order_by("-updated_at")[:limit]
    out = []
    for n in qs:
        excerpt = re.sub(r"[#>*`\-\[\]]", " ", n.content or "")
        excerpt = " ".join(excerpt.split())[:80]
        out.append({"id": n.id, "title": n.title, "words": n.words, "excerpt": excerpt})
    return out


def dangling_notes(owner_id: int, limit: int = 50):
    """悬浮链接汇总：被引用了但还不存在的笔记标题（可直接一键创建）"""
    from notes.models import NoteLink

    qs = (
        NoteLink.objects.filter(owner_id=owner_id, target__isnull=True)
        .values("target_title")
        .order_by("target_title")
    )
    counts = {}
    for row in qs:
        counts[row["target_title"]] = counts.get(row["target_title"], 0) + 1
    items = [{"title": t, "ref_count": c} for t, c in counts.items()]
    items.sort(key=lambda x: x["ref_count"], reverse=True)
    return items[:limit]


def _mention_excerpt(content: str, keyword: str, width: int = 120) -> str:
    """截取反向链接所在上下文"""
    if not content:
        return ""
    pos = content.find(keyword)
    if pos < 0:
        return content[:width]
    start = max(0, pos - width // 3)
    frag = content[start:start + width]
    return ("…" if start > 0 else "") + frag + ("…" if start + width < len(content) else "")


def all_backlink_ids(owner_id: int):
    """有反链的笔记 id 集合（列表页可显示反链角标）"""
    from notes.models import NoteLink

    return set(
        NoteLink.objects.filter(owner_id=owner_id, target__isnull=False)
        .values_list("target_id", flat=True)
    )
