# -*- coding: utf-8 -*-
"""dataintel · 文本面接口：nlp(8) textmine(5) vector(5) = 18 个。

中文分词/关键词/摘要复用 core.search 与 assistant.llm 的既有实现（可降级）。
"""
import math
import re
from collections import Counter

from assistant.llm import extractive_summary, keywords as llm_keywords
from core.search import term_freq, tokenize

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p, req, req_list, req_num, req_str

# =====================================================================
# nlp 中文/通用 NLP（8）
# =====================================================================


@endpoint()
def nlp_tokenize(request):
    """中文分词（bigram+整词混合，复用全文搜索引擎的分词器）。"""
    text = req_str(request)
    mode = opt_str(request, "mode", "default")
    tokens = tokenize(text)
    if mode == "english":
        tokens = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text.lower())
    return ok({"tokens": tokens, "count": len(tokens), "unique": len(set(tokens)), "mode": mode})


_ZH_SENTIMENT_POS = ["好", "优秀", "棒", "喜欢", "满意", "推荐", "顺利", "高效", "清晰", "稳定",
                     "出色", "完美", "贴心", "热情", "专业", "靠谱", "省心", "超值", "惊艳", "感动",
                     "good", "great", "excellent", "love", "perfect", "happy", "best", "awesome"]
_ZH_SENTIMENT_NEG = ["差", "糟糕", "失望", "投诉", "慢", "贵", "难用", "bug", "崩溃", "卡顿",
                     "不满", "讨厌", "坑", "敷衍", "态度差", "退货", "维修", "破损", "误差", "骗子",
                     "bad", "terrible", "hate", "worst", "awful", "broken", "slow", "poor"]


@endpoint()
def nlp_sentiment(request):
    """情感倾向（词典打分法，正负词命中 + 归一化得分）。"""
    text = req_str(request)
    low = text.lower()
    pos = [w for w in _ZH_SENTIMENT_POS if w in low]
    neg = [w for w in _ZH_SENTIMENT_NEG if w in low]
    score = (len(pos) - len(neg)) / max(len(pos) + len(neg), 1)
    label = "正面" if score > 0.2 else "负面" if score < -0.2 else "中性"
    return ok({"label": label, "score": round(score, 4), "positive_hits": pos[:10],
               "negative_hits": neg[:10], "method": "lexicon", "length": len(text)})


@endpoint()
def nlp_keywords(request):
    """关键词提取（词频加权 + 去重叠，复用 AI 模块的实现）。"""
    text = req_str(request)
    top = int(opt_num(request, "top", 10, minimum=1, maximum=50) or 10)
    kws = llm_keywords(text, top=top)
    freq = term_freq(text)
    return ok({"keywords": kws, "with_freq": [{"term": k, "count": freq.get(k, 0)} for k in kws],
               "total_terms": sum(freq.values())})


@endpoint()
def nlp_summarize(request):
    """抽取式摘要（按句权重选摘，无 Key 也可用）。"""
    text = req_str(request)
    max_sentences = int(opt_num(request, "max_sentences", 3, minimum=1, maximum=10) or 3)
    summary = extractive_summary(text, max_sentences=max_sentences)
    return ok({"summary": summary, "original_chars": len(text),
               "summary_chars": len(summary), "compression": round(len(summary) / max(len(text), 1), 3)})


_NER_PATTERNS = [
    ("mobile", "手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ("id_card", "身份证", r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ("email", "邮箱", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("url", "网址", r"https?://[^\s<>\"')\]]+"),
    ("money", "金额", r"[¥￥$]\s*\d+(?:,\d{3})*(?:\.\d+)?"),
    ("date", "日期", r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"),
    ("ipv4", "IP地址", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
]


@endpoint()
def nlp_entities(request):
    """实体识别（规则版）：手机号/身份证/邮箱/网址/金额/日期/IP。"""
    text = req_str(request)
    want = p(request, "types")
    found = {}
    for key, name, pat in _NER_PATTERNS:
        if want and key not in want:
            continue
        hits = sorted(set(re.findall(pat, text)))
        if hits:
            found[key] = {"label": name, "values": hits, "count": len(hits)}
    return ok({"entities": found, "total": sum(v["count"] for v in found.values()),
               "method": "regex-rules", "supported": [k for k, _, _ in _NER_PATTERNS]})


@endpoint()
def nlp_similarity(request):
    """文本相似度：词集 Jaccard + 词频余弦。"""
    a, b = req_str(request, "a"), req_str(request, "b")
    ta, tb = tokenize(a), tokenize(b)
    sa, sb = set(ta), set(tb)
    jac = len(sa & sb) / len(sa | sb) if sa | sb else 1.0
    fa, fb = Counter(ta), Counter(tb)
    common = set(fa) & set(fb)
    dot = sum(fa[t] * fb[t] for t in common)
    na = math.sqrt(sum(v * v for v in fa.values())) or 1
    nb = math.sqrt(sum(v * v for v in fb.values())) or 1
    return ok({"jaccard": round(jac, 4), "cosine": round(dot / (na * nb), 4),
               "shared_terms": sorted(common)[:20], "tokens_a": len(ta), "tokens_b": len(tb)})


@endpoint()
def nlp_readability(request):
    """可读性：中文（句长/难词比）与英文（Flesch）双引擎。"""
    text = req_str(request)
    hanzi = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    latin_words = re.findall(r"[A-Za-z]+", text)
    sents = [s for s in re.split(r"[。！？!?；;.\n]", text) if s.strip()]
    avg_sent_len = (hanzi + len(latin_words)) / max(len(sents), 1)
    hard_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" and c in "邃矗髋魍魉龘爨饕餮霾彝彝")
    if hanzi > len("".join(latin_words)):
        score = max(0, min(100, 100 - avg_sent_len * 4 - hanzi / max(len(sents), 1) * 0.5))
        lang = "zh"
        level = "通俗" if score >= 70 else "中等" if score >= 40 else "偏学术"
    else:
        syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in latin_words)
        words = max(len(latin_words), 1)
        flesch = 206.835 - 1.015 * (words / max(len(sents), 1)) - 84.6 * (syllables / words)
        score = max(0, min(100, flesch))
        lang = "en"
        level = "easy" if score >= 60 else "medium" if score >= 30 else "hard"
    return ok({"language": lang, "score": round(score, 1), "level": level,
               "sentences": len(sents), "hanzi": hanzi, "latin_words": len(latin_words),
               "avg_sentence_len": round(avg_sent_len, 2), "long_sentence_count": sum(1 for s in sents if len(s) > 60)})


_STOPWORDS_ZH = ("的 了 和 是 就 都 而 及 与 著 或 一个 没有 我们 你们 他们 它 这 那 也 在 上 下 中 里 对 为 到 说 "
                 "要 会 能 有 被 把 从 以 但 并 等 很 更 最 之 其 这个 那个 这样 那样 因此 所以 因为 但是 如果 虽然 "
                 "可以 已经 还是 只是 一些 一些 什么 怎么 如何 以及 通过 对于 而且 并且 不仅 不但").split()
_STOPWORDS_EN = "the a an and or but if of to in on at for with by is are was were be been being it its this that these those as from".split()


@endpoint()
def nlp_stopwords(request):
    """停用词过滤：中文+英文内置词表，支持自定义补充。"""
    text = req_str(request)
    extra = p(request, "extra") or []
    stops = set(_STOPWORDS_ZH) | set(_STOPWORDS_EN) | set(extra)
    tokens = tokenize(text)
    kept = [t for t in tokens if t not in stops]
    removed = [t for t in tokens if t in stops]
    return ok({"tokens": kept, "removed": removed,
               "kept": len(kept), "removed_count": len(removed),
               "stopword_count": len(stops), "extra_added": len(extra)})


# =====================================================================
# textmine 文本挖掘（5）
# =====================================================================


@endpoint()
def textmine_wordfreq(request):
    """词频统计（去停用词可选，TOP 表 + 覆盖率）。"""
    text = req_str(request)
    top = int(opt_num(request, "top", 30, minimum=1, maximum=200) or 30)
    drop_stops = opt_bool(request, "drop_stopwords", True)
    tokens = tokenize(text)
    if drop_stops:
        stops = set(_STOPWORDS_ZH) | set(_STOPWORDS_EN)
        tokens = [t for t in tokens if t not in stops]
    freq = Counter(tokens)
    total = sum(freq.values()) or 1
    items = freq.most_common(top)
    return ok({"items": [{"term": t, "count": c, "pct": round(c / total * 100, 3)} for t, c in items],
               "unique": len(freq), "total_tokens": total,
               "top_coverage_pct": round(sum(c for _, c in items) / total * 100, 2)})


@endpoint()
def textmine_cooccurrence(request):
    """共现分析：窗口内词对计数，返回 TOP 词对。"""
    text = req_str(request)
    window = int(opt_num(request, "window", 5, minimum=2, maximum=20) or 5)
    top = int(opt_num(request, "top", 15, minimum=1, maximum=50) or 15)
    tokens = [t for t in tokenize(text) if len(t) >= 2]
    pairs = Counter()
    for i in range(len(tokens)):
        for j in range(i + 1, min(i + window, len(tokens))):
            a, b = sorted((tokens[i], tokens[j]))
            pairs[(a, b)] += 1
    return ok({"pairs": [{"a": a, "b": b, "count": c} for (a, b), c in pairs.most_common(top)],
               "unique_pairs": len(pairs), "window": window})


@endpoint()
def textmine_bigram(request):
    """BIGRAM 相邻词对统计。"""
    text = req_str(request)
    top = int(opt_num(request, "top", 15, minimum=1, maximum=50) or 15)
    tokens = [t for t in tokenize(text) if t]
    grams = Counter(zip(tokens, tokens[1:]))
    return ok({"bigrams": [{"a": a, "b": b, "count": c} for (a, b), c in grams.most_common(top)],
               "unique": len(grams), "token_count": len(tokens)})


@endpoint()
def textmine_classify(request):
    """规则分类：按类别关键词打分（零训练成本）。"""
    text = req_str(request)
    categories = req_list(request, "categories")
    low = text.lower()
    scores = []
    for c in categories:
        if not isinstance(c, dict) or "name" not in c:
            raise ValueError('categories 每项需为 {name, keywords}')
        kws = c.get("keywords") or []
        hits = [k for k in kws if str(k).lower() in low]
        scores.append({"category": c["name"], "score": len(hits), "hits": hits})
    scores.sort(key=lambda x: -x["score"])
    winner = scores[0] if scores and scores[0]["score"] > 0 else None
    return ok({"scores": scores, "predicted": winner["category"] if winner else None,
               "confident": bool(winner and winner["score"] >= 2), "method": "keyword-rules"})


def _simhash(text):
    tokens = tokenize(text) or [text[:8] or "empty"]
    v = [0] * 64
    for t in tokens:
        h = int.from_bytes(abs(hash(t)).to_bytes(8, "little", signed=True), "little")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    return sum(1 << i for i in range(64) if v[i] > 0)


@endpoint()
def textmine_simhash(request):
    """SimHash 指纹与两两汉明距离（近似查重）。"""
    docs = req_list(request, "docs")
    if len(docs) < 2:
        raise ValueError("至少 2 篇文档")
    fps = [_simhash(str(d)) for d in docs]
    def hamming(a, b):
        return bin(a ^ b).count("1")
    pairs = [{"a": i, "b": j, "hamming": hamming(fps[i], fps[j]),
              "similar": hamming(fps[i], fps[j]) <= 12}
             for i in range(len(docs)) for j in range(i + 1, len(docs))]
    dup = [pr for pr in pairs if pr["similar"]]
    return ok({"fingerprints": [f"{f:016x}" for f in fps], "pairs": pairs,
               "duplicate_pairs": len(dup), "threshold": 12,
               "verdict": "存在疑似重复/高度相似文档" if dup else "未见高度相似文档对"})


# =====================================================================
# vector 向量运算（5）
# =====================================================================


def _vec(request, key):
    values = req_list(request, key)
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        raise ValueError(f"{key} 必须是数字数组")


@endpoint()
def vector_cosine(request):
    """向量余弦相似度（附点积与模长）。"""
    a, b = _vec(request, "a"), _vec(request, "b")
    if len(a) != len(b) or not a:
        raise ValueError("a/b 等长且非空")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(y * y for y in b)) or 1e-12
    return ok({"cosine": round(dot / (na * nb), 6), "dot": round(dot, 6),
               "norm_a": round(na, 6), "norm_b": round(nb, 6), "dim": len(a)})


@endpoint()
def vector_distance(request):
    """向量距离：欧氏/曼哈顿/切比雪夫。"""
    a, b = _vec(request, "a"), _vec(request, "b")
    if len(a) != len(b) or not a:
        raise ValueError("a/b 等长且非空")
    return ok({"euclidean": round(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))), 6),
               "manhattan": round(sum(abs(x - y) for x, y in zip(a, b)), 6),
               "chebyshev": round(max(abs(x - y) for x, y in zip(a, b)), 6), "dim": len(a)})


@endpoint()
def vector_knn(request):
    """KNN：最近邻查询（可带标签投票）。"""
    pts = req_list(request, "points")
    query = _vec(request, "query")
    k = int(opt_num(request, "k", 3, minimum=1, maximum=len(pts) or 1) or 3)
    scored = []
    for i, item in enumerate(pts):
        if isinstance(item, dict):
            vec = [float(v) for v in item.get("vector", [])]
            label = item.get("label")
        elif isinstance(item, (list, tuple)):
            vec = [float(v) for v in item]
            label = None
        else:
            raise ValueError("points 每项需为 {vector, label} 或数组")
        if len(vec) != len(query):
            raise ValueError("向量维度与 query 不一致")
        d = math.sqrt(sum((x - y) ** 2 for x, y in zip(vec, query)))
        scored.append({"index": i, "distance": round(d, 6), "label": label})
    scored.sort(key=lambda x: x["distance"])
    top = scored[:k]
    vote = {}
    for t in top:
        if t["label"] is not None:
            vote[t["label"]] = vote.get(t["label"], 0) + 1
    predicted = max(vote.items(), key=lambda kv: kv[1])[0] if vote else None
    return ok({"neighbors": top, "k": k, "label_votes": vote, "predicted_label": predicted})


@endpoint()
def vector_centroid(request):
    """质心：全体或按标签分组。"""
    pts = req_list(request, "points")
    vectors = []
    labels = []
    for item in pts:
        if isinstance(item, dict):
            vectors.append([float(v) for v in item.get("vector", [])])
            labels.append(item.get("label"))
        elif isinstance(item, (list, tuple)):
            vectors.append([float(v) for v in item])
            labels.append(None)
        else:
            raise ValueError("points 每项需为 {vector, label} 或数组")
    if not vectors:
        raise ValueError("points 为空")
    dim = len(vectors[0])
    if any(len(v) != dim for v in vectors):
        raise ValueError("向量维度必须一致")
    def cent(vs):
        return [round(sum(v[d] for v in vs) / len(vs), 6) for d in range(dim)]
    result = {"overall_centroid": cent(vectors), "count": len(vectors), "dim": dim}
    if any(l is not None for l in labels):
        groups = {}
        for v, l in zip(vectors, labels):
            if l is not None:
                groups.setdefault(str(l), []).append(v)
        result["by_label"] = {k: {"centroid": cent(vs), "count": len(vs)} for k, vs in sorted(groups.items())}
    return ok(result)


@endpoint()
def vector_normalize(request):
    """向量归一化：L2 / L1 / minmax。"""
    a = _vec(request, "a")
    method = opt_str(request, "method", "l2")
    if method == "l2":
        norm = math.sqrt(sum(x * x for x in a)) or 1e-12
        out = [round(x / norm, 8) for x in a]
    elif method == "l1":
        norm = sum(abs(x) for x in a) or 1e-12
        out = [round(x / norm, 8) for x in a]
    elif method == "minmax":
        lo, hi = min(a), max(a)
        rng = (hi - lo) or 1e-12
        out = [round((x - lo) / rng, 8) for x in a]
    else:
        raise ValueError("method 支持 l2/l1/minmax")
    return ok({"normalized": out, "method": method, "norm_after": round(math.sqrt(sum(x * x for x in out)), 6)})


NLP_FAMILY_COUNT = 8 + 5 + 5  # = 18
