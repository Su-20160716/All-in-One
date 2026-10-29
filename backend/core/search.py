"""全文搜索引擎（纯 Python + Django ORM 实现，不依赖外部服务）

能力
----
1. 中文分词：CJK 逐字 + bigram 双字组合（无第三方分词库也能命中"全文搜索"这类词）
2. 倒排索引：SearchDoc（文档）+ SearchTerm（词项）两级表，跨 SQLite/PostgreSQL 通用
3. BM25 排序：标题字段加权，支持摘要高亮片段
4. 文本抽取：txt/md/csv/json/pdf/docx/xlsx 等常见格式
5. 权限对齐：复用 core.scoping，只返回当前用户数据范围内的文档

注意：倒排表按「文档」重建（重建前先删旧词项），因此索引是幂等的。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

import html
import math
import os
import re
from collections import Counter

from django.conf import settings

# ---------------------------------------------------------------------------
# 分词
# ---------------------------------------------------------------------------

CJK = r"\u4e00-\u9fff\u3400-\u4dbf"
_LATIN_RE = re.compile(r"[a-zA-Z0-9_]+")
_CJK_RUN_RE = re.compile(f"[{CJK}]+")
_TOKEN_SPLIT_RE = re.compile(f"[^a-zA-Z0-9_{CJK}]+")

# 中英文停用词（中文以单字为主，命中即丢弃）
CJK_STOP = set("的了是在和与及或有个我你他她它们这那就都很也还被把从对向以及之其而且但如果因为所以可以这个那个我们你们什么怎么这样那样一个一些没有不是不能")
EN_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "and", "or", "is", "are", "was", "were",
    "be", "been", "it", "this", "that", "with", "as", "by", "from", "we", "you", "they", "he", "she",
    "but", "if", "then", "so", "not", "no", "yes", "do", "does", "did", "has", "have", "had", "will",
    "would", "can", "could", "should", "may", "might", "there", "here", "when", "where", "which", "who",
}

MAX_TERMS_PER_DOC = 20000


def normalize(text: str) -> str:
    """全角转半角 + 小写（便于中英混排检索）"""
    if not text:
        return ""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out).lower()


def tokenize(text: str) -> list[str]:
    """中英混排分词。

    - 英文/数字：按非字母数字切分，长度 >= 2（纯数字保留）
    - 中文：每个连续中文串产出「单字」+「相邻双字(bigram)」，长度 2~4 的整串也整体保留
    """
    text = normalize(text)
    if not text:
        return []
    tokens: list[str] = []

    for run in _CJK_RUN_RE.findall(text):
        chars = list(run)
        for ch in chars:
            if ch not in CJK_STOP:
                tokens.append(ch)
        for i in range(len(chars) - 1):
            bg = chars[i] + chars[i + 1]
            if chars[i] in CJK_STOP and chars[i + 1] in CJK_STOP:
                continue
            tokens.append(bg)
        if 2 <= len(chars) <= 4:
            tokens.append(run)

    for word in _LATIN_RE.findall(text):
        if word in EN_STOP:
            continue
        if len(word) >= 2 or word.isdigit():
            tokens.append(word)

    return tokens


def term_freq(text: str) -> Counter:
    return Counter(tokenize(text))


# ---------------------------------------------------------------------------
# 文本抽取（供文件索引使用）
# ---------------------------------------------------------------------------

TEXT_EXTS = {
    "txt", "md", "markdown", "csv", "tsv", "json", "xml", "yml", "yaml", "log", "ini", "conf",
    "py", "js", "ts", "vue", "java", "c", "cpp", "h", "go", "rs", "rb", "php", "sql", "sh",
    "html", "htm", "css", "scss", "bat", "ps1",
}
OFFICE_EXTS = {"doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp"}
INDEXABLE_EXTS = TEXT_EXTS | OFFICE_EXTS | {"pdf"}

_TAG_RE = re.compile(r"<[^>]+>")


def _max_chars() -> int:
    return int(getattr(settings, "SEARCH_MAX_TEXT_CHARS", 200000))


def _read_plain(path: str, cap: int) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        data = f.read(cap)
    if path.lower().endswith((".html", ".htm", ".xml")):
        data = _TAG_RE.sub(" ", data)
    return data


def _read_pdf(path: str, cap: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - 依赖缺失时优雅降级
        return ""
    try:
        reader = PdfReader(path)
        parts, total = [], 0
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            if not txt:
                continue
            parts.append(txt)
            total += len(txt)
            if total >= cap:
                break
        return "\n".join(parts)[:cap]
    except Exception:
        return ""


def _read_docx(path: str, cap: int) -> str:
    try:
        import docx  # python-docx
    except ImportError:  # pragma: no cover
        return ""
    try:
        doc = docx.Document(path)
        parts = [p.text for p in doc.paragraphs if p.text]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)[:cap]
    except Exception:
        return ""


def _read_xlsx(path: str, cap: int) -> str:
    try:
        import openpyxl
    except ImportError:  # pragma: no cover
        return ""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        parts, total = [], 0
        for ws in wb.worksheets:
            parts.append(ws.title)
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if not cells:
                    continue
                line = " | ".join(cells)
                parts.append(line)
                total += len(line)
                if total >= cap:
                    break
            if total >= cap:
                break
        try:
            wb.close()
        except Exception:
            logger.exception("B23：静默兜底已登记（core/search.py:190 原为 pass）——review 是否应收窄异常类型")
        return "\n".join(parts)[:cap]
    except Exception:
        return ""


def extract_text(abs_path: str, ext: str = "") -> str:
    """从磁盘文件抽取纯文本；不支持的格式返回空串（不抛异常）"""
    if not abs_path or not os.path.exists(abs_path):
        return ""
    cap = _max_chars()
    ext = (ext or os.path.splitext(abs_path)[1].lstrip(".")).lower()
    if ext in TEXT_EXTS:
        return _read_plain(abs_path, cap)
    if ext == "pdf":
        return _read_pdf(abs_path, cap)
    if ext == "docx":
        return _read_docx(abs_path, cap)
    if ext in ("xlsx", "xlsm"):
        return _read_xlsx(abs_path, cap)
    # doc / xls / ppt 等老格式需要 LibreOffice，先转 PDF 再抽
    try:
        from files.office import convert_to_pdf, find_soffice

        if find_soffice():
            ok, result = convert_to_pdf(abs_path, ext)
            if ok and result.lower().endswith(".pdf"):
                return _read_pdf(result, cap)
    except Exception:
        logger.exception("B23：静默兜底已登记（core/search.py:219 原为 pass）——review 是否应收窄异常类型")
    return ""


def can_index(ext: str) -> bool:
    return (ext or "").lower().lstrip(".") in INDEXABLE_EXTS


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------

def _build_terms(title: str, body: str):
    """返回 (词项统计, 正文长度, 词项总数)"""
    t_counter = Counter({t: c * 3 for t, c in term_freq(title).items()})  # 标题权重 3x
    b_counter = term_freq(body)
    merged = Counter(t_counter)
    merged.update(b_counter)

    if len(merged) > MAX_TERMS_PER_DOC:
        merged = Counter(dict(merged.most_common(MAX_TERMS_PER_DOC)))

    title_terms = set(t_counter)
    total = sum(merged.values())
    return merged, title_terms, total


def index_document(module: str, object_id: int, owner_id, title: str, body: str, summary: str = ""):
    """建立/更新单篇文档索引（幂等）"""
    from core.models import SearchDoc, SearchTerm

    if not getattr(settings, "SEARCH_ENABLED", True):
        return None

    title = (title or "")[:500]
    body = (body or "")[: _max_chars()]
    merged, title_terms, total = _build_terms(title, body)

    doc, _ = SearchDoc.objects.update_or_create(
        module=module,
        object_id=object_id,
        defaults={
            "owner_id": owner_id,
            "title": title,
            "summary": (summary or body)[:300],
            "length": max(total, 1),
        },
    )
    doc.terms.all().delete()
    rows = [
        SearchTerm(doc=doc, term=term[:64], freq=freq, in_title=term in title_terms)
        for term, freq in merged.items()
    ]
    if rows:
        SearchTerm.objects.bulk_create(rows, batch_size=2000)
    return doc


def remove_document(module: str, object_id: int):
    from core.models import SearchDoc

    SearchDoc.objects.filter(module=module, object_id=object_id).delete()


# ---------------------------------------------------------------------------
# 检索（BM25-lite）
# ---------------------------------------------------------------------------

def _snippet(body: str, query_terms: set, width: int = 160) -> str:
    """截取包含查询词的片段并高亮（F662）。

    先按命中词切分、再对每段做 HTML 转义，最后才包 ``<em>`` 标记，
    因此正文里即便含 ``<script>`` 也不会被注入（防 XSS）。
    """
    if not body:
        return ""
    plain = normalize(body)
    terms = sorted({t for t in query_terms if t}, key=len, reverse=True)
    pos = -1
    for term in terms:
        pos = plain.find(term)
        if pos >= 0:
            break
    if pos < 0:
        frag = body[:width]
        return _escape(frag) + ("…" if len(body) > width else "")

    start = max(0, pos - width // 3)
    frag = body[start:start + width]
    pattern = None
    if terms:
        pattern = re.compile("(" + "|".join(re.escape(t) for t in terms) + ")", re.IGNORECASE)

    parts = pattern.split(frag) if pattern else [frag]
    chunks = []
    for i, part in enumerate(parts):
        esc = _escape(part)
        if pattern and i % 2 == 1:
            chunks.append(f"<em>{esc}</em>")
        else:
            chunks.append(esc)
    return ("…" if start > 0 else "") + "".join(chunks) + ("…" if start + width < len(body) else "")


def _escape(text: str) -> str:
    """HTML 转义（不转义引号，避免破坏既有展示）"""
    return html.escape(text or "", quote=False)


# ---------------------------------------------------------------------------
# 搜索语法（F662）："精确短语" 与 -排除词
# ---------------------------------------------------------------------------

_QUOTE_RE = re.compile(r'"([^"]+)"|“([^”]+)”|「([^」]+)」')


def parse_syntax(query: str) -> dict:
    """解析搜索语法，返回剩余关键词、精确短语列表与排除词列表。

    支持：``"精确短语"``（英文双引号 / 中文双引号 / 直角引号）、``-排除词``。
    """
    raw = query or ""
    phrases = [next(g for g in tup if g) for tup in _QUOTE_RE.findall(raw)]
    rest = _QUOTE_RE.sub(" ", raw)
    excludes, keep = [], []
    for token in rest.split():
        if token.startswith("-") and len(token) > 1 and not token[1].isdigit():
            excludes.append(token[1:])
        elif token != "-":
            keep.append(token)
    phrases = [p.strip() for p in phrases if p.strip()]
    excludes = [e.strip() for e in excludes if e.strip()]
    return {
        "raw": raw,
        "phrases": list(dict.fromkeys(phrases))[:8],
        "excludes": list(dict.fromkeys(excludes))[:8],
        "terms_text": " ".join(keep),
    }


def search(query: str, owner_ids, modules=None, limit: int = 20, offset: int = 0,
           phrases=None, excludes=None):
    """全文检索。

    :param owner_ids: 可见 owner id 集合；None 表示不限
    :param phrases: 精确短语列表（缺省时按搜索语法从 query 解析）
    :param excludes: 排除词列表（同上）
    :return: {"total": n, "results": [...], "terms": [...], "took_ms": x,
              "syntax": {...}, "by_module": [{module, count}]}
    """
    import time

    from django.db.models import Avg, Count
    from core.models import SearchDoc, SearchTerm

    started = time.time()
    syntax = parse_syntax(query)
    phrases = list(syntax["phrases"] if phrases is None else phrases)
    excludes = list(syntax["excludes"] if excludes is None else excludes)
    base_text = (syntax["terms_text"] + " " + " ".join(phrases)).strip()

    terms = [t for t in dict.fromkeys(tokenize(base_text)) if t]
    if not terms:
        empty = {"total": 0, "results": [], "terms": [], "took_ms": 0, "query": query,
                 "syntax": syntax, "by_module": [], "group_counts": {}}
        return empty

    qs = SearchDoc.objects.all()
    if modules:
        qs = qs.filter(module__in=modules)
    if owner_ids is not None:
        if not owner_ids:
            return {"total": 0, "results": [], "terms": terms, "took_ms": 0, "query": query,
                    "syntax": syntax, "by_module": [], "group_counts": {}}
        qs = qs.filter(owner_id__in=owner_ids)
    visible_ids = set(qs.values_list("id", flat=True))
    total_docs = len(visible_ids) or 1

    avg_len = qs.aggregate(a=Avg("length"))["a"] or 1.0
    k1, b = 1.2, 0.75

    df_map = dict(
        SearchTerm.objects.filter(term__in=terms, doc_id__in=visible_ids)
        .values("term")
        .annotate(c=Count("doc_id", distinct=True))
        .values_list("term", "c")
    )

    scores: dict[int, float] = {}
    matched: dict[int, set] = {}
    rows = (
        SearchTerm.objects.filter(term__in=terms, doc_id__in=visible_ids)
        .values_list("doc_id", "term", "freq", "in_title")
    )
    for doc_id, term, freq, in_title in rows:
        df = df_map.get(term, 1)
        idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
        weight = 3.0 if in_title else 1.0
        scores[doc_id] = scores.get(doc_id, 0.0) + idf * freq * weight
        matched.setdefault(doc_id, set()).add(term)

    # 覆盖率加成：命中不同词项越多越相关
    for doc_id, hits in matched.items():
        scores[doc_id] *= 1 + 0.25 * (len(hits) - 1)

    # S2-B1：同分 tiebreaker——更新时间新的排前。
    # BM25 对「多篇内容相同的文档」会给出完全相同的分数（典型场景：
    # 协同回写/模板生成的同文笔记），原先同分顺序取决于 DB 返回顺序
    # 不可控，新写入的文档可能被历史同分文档挤出首页。加 recency
    # tiebreaker 后同分文档新的在前，检索结果更符合直觉。
    # 用 epoch 秒做 tiebreaker，避免 naive 的 datetime.min 与 aware 的
    # updated_at（USE_TZ=True）比较时抛 TypeError
    ts_map = {
        doc_id: ts.timestamp() if ts else 0.0
        for doc_id, ts in SearchDoc.objects.filter(id__in=list(scores)[:5000])
        .values_list("id", "updated_at")
    }
    ranked = sorted(
        scores.items(),
        key=lambda kv: (kv[1], ts_map.get(kv[0], 0.0)),
        reverse=True,
    )

    # ---------------- 语法过滤：精确短语 / 排除词（F662） ----------------
    phrase_fallback = False
    docs_cache: dict = {}
    if (phrases or excludes) and ranked:
        docs_cache = {
            d.id: d for d in SearchDoc.objects.filter(id__in=[i for i, _ in ranked[:5000]])
        }

        def _hay(doc):
            return normalize(f"{doc.title or ''} {doc.summary or ''}")

        def _keep_excludes(pair):
            doc = docs_cache.get(pair[0])
            if not doc:
                return False
            hay = _hay(doc)
            return not any(normalize(x) and normalize(x) in hay for x in excludes)

        filtered = [p for p in ranked if _keep_excludes(p)]
        if phrases:
            np = len(filtered)
            strict = []
            for pair in filtered:
                doc = docs_cache.get(pair[0])
                if not doc:
                    continue
                hay = _hay(doc)
                if all(normalize(p) in hay for p in phrases):
                    strict.append(pair)
            if strict:
                filtered = strict
            elif np:
                # 精确短语只出现在正文（索引摘要仅存前 300 字）→ 退化为词项命中
                phrase_fallback = True
        ranked = filtered

    total = len(ranked)

    # ---------------- 分组计数（F661 按模块分组） ----------------
    group_counts: dict = {}
    if ranked:
        ids = [i for i, _ in ranked[:5000]]
        if docs_cache and set(ids) == set(docs_cache):
            for doc in docs_cache.values():
                group_counts[doc.module] = group_counts.get(doc.module, 0) + 1
        else:
            for _id, _module in SearchDoc.objects.filter(id__in=ids).values_list("id", "module"):
                group_counts[_module] = group_counts.get(_module, 0) + 1
    by_module = [{"module": k, "count": v} for k, v in
                 sorted(group_counts.items(), key=lambda kv: -kv[1])]

    page = ranked[offset: offset + limit]
    docs = {d.id: d for d in SearchDoc.objects.filter(id__in=[i for i, _ in page])}

    results = []
    for doc_id, score in page:
        doc = docs.get(doc_id)
        if not doc:
            continue
        hl_terms = set(matched.get(doc_id, set())) | {normalize(p) for p in phrases}
        results.append({
            "id": doc.object_id,
            "doc_id": doc.id,
            "module": doc.module,
            "title": doc.title,
            "snippet": _snippet(doc.summary or "", hl_terms),
            "score": round(score, 4),
            "owner_id": doc.owner_id,
            "updated_at": doc.updated_at,
            "matched_terms": sorted(matched.get(doc_id, set()))[:8],
        })
    return {
        "total": total,
        "results": results,
        "terms": terms,
        "took_ms": int((time.time() - started) * 1000),
        "query": query,
        "syntax": {**syntax, "phrase_fallback": phrase_fallback},
        "by_module": by_module,
        "group_counts": group_counts,
    }


def suggest(prefix: str, owner_ids=None, limit: int = 10):
    """词项联想：按倒排词表前缀匹配，按出现文档数排序"""
    from django.db.models import Count
    from core.models import SearchTerm

    prefix = normalize((prefix or "").strip())
    if not prefix:
        return []
    qs = SearchTerm.objects.filter(term__startswith=prefix[:32])
    if owner_ids is not None:
        qs = qs.filter(doc__owner_id__in=list(owner_ids) or [-1])
    rows = qs.values("term").annotate(c=Count("doc_id", distinct=True)).order_by("-c", "term")[:limit]
    return [{"term": r["term"], "count": r["c"]} for r in rows]


def index_stats(owner_ids=None):
    from django.db.models import Count, Sum
    from core.models import SearchDoc, SearchTerm

    qs = SearchDoc.objects.all()
    if owner_ids is not None:
        qs = qs.filter(owner_id__in=list(owner_ids) or [-1])
    by_module = list(qs.values("module").annotate(c=Count("id")).order_by("-c"))
    return {
        "documents": qs.count(),
        "terms": SearchTerm.objects.filter(doc__in=qs).count(),
        "vocabulary": SearchTerm.objects.filter(doc__in=qs).values("term").distinct().count(),
        "by_module": by_module,
        "total_length": qs.aggregate(s=Sum("length"))["s"] or 0,
    }
