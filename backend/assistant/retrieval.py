"""检索增强（RAG-lite）：把笔记切成块并按问题相关度排序

不引入向量库：复用 core.search 的分词器做词项重合度打分，
对「个人笔记问答」这个量级（几百篇）足够快且完全离线可用。
"""
from __future__ import annotations

from core.search import tokenize
from django.db.models import Q

CHUNK_SIZE = 600
CHUNK_OVERLAP = 100


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """按段落优先、字符兜底切块，保留少量重叠避免切断语义"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 <= size:
            buf = f"{buf}\n{para}" if buf else para
            continue
        if buf:
            chunks.append(buf)
        if len(para) > size:
            start = 0
            while start < len(para):
                chunks.append(para[start:start + size])
                start += size - overlap
            buf = ""
        else:
            buf = para
    if buf:
        chunks.append(buf)
    return chunks


def note_chunks(user, note_ids=None, extra_filter=None, max_notes: int = 50):
    """取用户可见笔记并切块。

    :return: [{"title": str, "text": str, "ref": {"note_id": int}}]
    """
    from core.scoping import scope_queryset
    from notes.models import Note

    qs = scope_queryset(Note.objects.filter(is_deleted=False), user)
    if note_ids:
        qs = qs.filter(id__in=note_ids)
    if extra_filter:
        qs = qs.filter(extra_filter)
    qs = qs.order_by("-updated_at")[:max_notes]

    out = []
    for note in qs:
        for chunk in chunk_text(note.content):
            out.append({
                "title": note.title,
                "text": f"# {note.title}\n{chunk}",
                "ref": {"note_id": note.id, "title": note.title, "updated_at": note.updated_at},
            })
    return out


def search_notes(user, keyword: str, limit: int = 20):
    """关键词粗召回（标题或正文命中），供问答前的候选筛选"""
    from core.scoping import scope_queryset
    from notes.models import Note

    if not keyword:
        return scope_queryset(Note.objects.filter(is_deleted=False), user).order_by("-updated_at")[:limit]
    terms = [t for t in tokenize(keyword) if len(t) >= 2][:6]
    cond = Q(title__icontains=keyword) | Q(content__icontains=keyword)
    for t in terms:
        cond |= Q(title__icontains=t) | Q(content__icontains=t)
    return scope_queryset(Note.objects.filter(is_deleted=False), user).filter(cond).distinct()[:limit]


def rank_chunks(question: str, chunks, top_k: int = 4):
    """按与问题的词项重合度排序，返回 top_k 个块"""
    q_terms = set(tokenize(question))
    if not q_terms:
        return []
    scored = []
    for chunk in chunks:
        text = chunk.get("text") or ""
        tokens = tokenize(text)
        if not tokens:
            continue
        hits = sum(1 for t in tokens if t in q_terms)
        if not hits:
            continue
        distinct = len({t for t in tokens if t in q_terms})
        score = (hits / (len(tokens) ** 0.5)) + distinct * 0.5
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)

    # 同一篇笔记最多取 2 块，保证引用来源多样
    picked, per_note = [], {}
    for score, chunk in scored:
        nid = (chunk.get("ref") or {}).get("note_id")
        if per_note.get(nid, 0) >= 2:
            continue
        per_note[nid] = per_note.get(nid, 0) + 1
        picked.append(chunk)
        if len(picked) >= top_k:
            break
    return picked


def build_context(chunks, max_chars: int = 6000) -> str:
    """把检索到的块拼成提示词上下文"""
    parts, total = [], 0
    for i, chunk in enumerate(chunks, start=1):
        body = chunk.get("text", "")
        if total + len(body) > max_chars:
            body = body[: max(0, max_chars - total)]
        if not body:
            break
        parts.append(f"[片段{i}] 来源：《{chunk.get('title', '')}》\n{body}")
        total += len(body)
    return "\n\n".join(parts)
