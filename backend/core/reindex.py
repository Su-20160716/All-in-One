"""索引重建（供管理命令与 /api/core/search/reindex/ 复用）

设计：全量重建按模块遍历业务表，逐个调用 core.search.index_document，
因此不存在"漏词"问题；文件模块会抽取正文（pdf/docx/xlsx 需对应依赖）。
"""
from __future__ import annotations


def _index_notes(owner_id=None):
    from core.search import index_document
    from notes.models import Note

    qs = Note.objects.filter(is_deleted=False)
    if owner_id:
        qs = qs.filter(owner_id=owner_id)
    n = 0
    for note in qs.iterator():
        index_document("note", note.id, note.owner_id, note.title, note.content, summary=note.content)
        n += 1
    return n


def _index_files(owner_id=None):
    from pathlib import Path

    from django.conf import settings

    from core.search import can_index, extract_text, index_document
    from files.models import FileMeta

    limit = int(getattr(settings, "SEARCH_FILE_MAX_MB", 20)) * 1024 * 1024
    media = Path(settings.MEDIA_ROOT)
    qs = FileMeta.objects.filter(is_deleted=False)
    if owner_id:
        qs = qs.filter(owner_id=owner_id)

    n, skipped = 0, 0
    for fm in qs.iterator():
        if not can_index(fm.ext) or (fm.size and fm.size > limit):
            skipped += 1
            continue
        text = extract_text(str(media / fm.storage_path), fm.ext)
        if text:
            index_document("file", fm.id, fm.owner_id, fm.name, text, summary=text)
            n += 1
        else:
            skipped += 1
    return {"indexed": n, "skipped": skipped}


def _index_projects(owner_id=None):
    from core.search import index_document
    from projects.models import Project

    qs = Project.objects.all()
    if owner_id:
        qs = qs.filter(owner_id=owner_id)
    n = 0
    for p in qs.iterator():
        index_document("project", p.id, p.owner_id, p.name, p.description or "")
        n += 1
    return n


def _index_tasks(owner_id=None):
    from core.search import index_document
    from projects.models import TaskCard

    qs = TaskCard.objects.select_related("board__project")
    if owner_id:
        qs = qs.filter(board__project__owner_id=owner_id)
    n = 0
    for t in qs.iterator():
        index_document("task", t.id, t.board.project.owner_id, t.title, t.description or "")
        n += 1
    return n


HANDLERS = {
    "note": _index_notes,
    "file": _index_files,
    "project": _index_projects,
    "task": _index_tasks,
}


def reindex_user(user, modules=None):
    """重建某个用户自己数据的索引"""
    return _run(user.id, modules)


def reindex_all(modules=None):
    """重建全量索引（管理员）"""
    return _run(None, modules)


def _run(owner_id, modules):
    picked = modules or list(HANDLERS.keys())
    detail = {}
    for name in picked:
        handler = HANDLERS.get(name)
        if not handler:
            continue
        result = handler(owner_id)
        detail[name] = result if isinstance(result, dict) else {"indexed": result}
    total = sum(v.get("indexed", 0) for v in detail.values())
    return {"indexed": total, "detail": detail}
