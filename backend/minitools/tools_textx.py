# -*- coding: utf-8 -*-
"""minitools · 文本进阶家族（10 个）。

去重：dataintel/nlp 有 tokenize/sentiment/readability/entities/keywords；
minitools/text 有 char-frequency/palindrome/anagram/similarity；
这里做规则语言检测、音节、缩写生成、哈希提取等不重叠工具。
"""
import re

from .common import endpoint, ok, opt_num, opt_str, p, req_list, req_num, req_str

_LEET = str.maketrans({"a": "4", "e": "3", "i": "1", "o": "0",
                       "s": "$", "t": "7", "l": "1", "g": "9"})


@endpoint()
def lang_detect(request):
    """T01. 规则语言检测（基于 Unicode 区块）。"""
    text = req_str(request, "text")
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    hira = len(re.findall(r"[\u3040-\u309f]", text))
    kata = len(re.findall(r"[\u30a0-\u30ff]", text))
    hangul = len(re.findall(r"[\uac00-\ud7af]", text))
    cyr = len(re.findall(r"[\u0400-\u04ff]", text))
    ar = len(re.findall(r"[\u0600-\u06ff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    votes = {
        "中文": cjk, "日文": hira + kata, "韩文": hangul,
        "俄语": cyr, "阿拉伯语": ar, "英文(拉丁)": latin,
    }
    lang = max(votes, key=votes.get)
    return ok({"detected": lang if votes[lang] else "未知", "scores": votes})


@endpoint()
def syllable_en(request):
    """T02. 英文音节数（元音字母组启发式）。"""
    word = req_str(request, "word").lower().strip()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and not word.endswith(("le", "ee", "ye")):
        count = max(1, count - 1)
    return ok({"word": word, "syllables": max(1, count)})


@endpoint()
def acronym(request):
    """T03. 从短语生成首字母缩写。"""
    text = req_str(request, "text")
    words = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text)
    upper = opt_str(request, "case", "upper") == "upper"
    out = "".join(w[0] for w in words)
    return ok({"acronym": out.upper() if upper else out.lower()})


@endpoint()
def palindrome_make(request):
    """T04. 用一个词生成回文（word + reverse(word[0:-1])）。"""
    word = req_str(request, "word").strip()
    p = word + word[-2::-1] if len(word) > 1 else word
    return ok({"palindrome": p})


@endpoint()
def leetspeak(request):
    """T05. Leet 语转换。"""
    text = req_str(request, "text")
    return ok({"leet": text.lower().translate(_LEET)})


@endpoint()
def word_goal(request):
    """T06. 字数目标进度。"""
    text = req_str(request, "text")
    target = int(req_num(request, "target", minimum=1))
    count = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text))
    return ok({"count": count, "target": target,
               "pct": round(count / target * 100, 1),
               "remaining": max(0, target - count)})


@endpoint()
def hashtag_extract(request):
    """T07. 提取 # 话题标签。"""
    text = req_str(request, "text")
    tags = re.findall(r"#([\w\u4e00-\u9fff]+)", text)
    return ok({"hashtags": tags, "count": len(tags)})


@endpoint()
def mention_extract(request):
    """T08. 提取 @提及 与邮箱。"""
    text = req_str(request, "text")
    mentions = re.findall(r"@([A-Za-z0-9_.]+)", text)
    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    return ok({"mentions": mentions, "emails": emails})


_EN_ORDINAL = {1: "st", 2: "nd", 3: "rd"}


@endpoint()
def ordinal(request):
    """T09. 数字英文序数 1 -> 1st。"""
    n = int(req_num(request, "number", minimum=0))
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = _EN_ORDINAL.get(n % 10, "th")
    return ok({"ordinal": f"{n}{suf}"})


@endpoint()
def sentence_split(request):
    """T10. 把文本切成句子（。！？.!? 后断句）。"""
    text = req_str(request, "text")
    parts = re.split(r"(?<=[。！？!?\.])\s+", text)
    return ok({"sentences": [p.strip() for p in parts if p.strip()],
               "count": len([p for p in parts if p.strip()])})


# =====================================================================
# 第三轮 S26（405）：敏感词检测与脱敏
# =====================================================================

# 默认内置词表：广告法极限词 / 医疗与金融违禁承诺 / 正常表述里极少出现的组合。
# 需要更多词时由调用方用 words[] 覆盖（不改默认表）。
_DEFAULT_SENSITIVE_WORDS = (
    "最佳", "最好", "最优", "最强", "最低", "最高", "第一品牌", "国家级", "世界级",
    "顶级", "极品", "唯一", "独家", "首创", "填补空白", "领导品牌", "销量第一",
    "绝对", "百分百", "100%有效", "永久", "彻底根治", "根治", "药到病除", "包治百病",
    "无副作用", "祖传秘方", "立竿见影", "保本", "稳赚不赔", "零风险", "内幕消息",
    "guaranteed", "best in the world", "no.1", "risk-free", "100% safe",
)


@endpoint()
def sensitive_words(request):
    """T11（S26/405）：敏感词检测 —— 返回命中词、位置与脱敏后文本。

    words[] 覆盖默认词表；英文大小写不敏感；长词优先匹配，命中区间不重叠。
    """
    text = req_str(request, "text")
    raw_words = p(request, "words")
    if isinstance(raw_words, str) and not raw_words.strip():
        raw_words = None
    if raw_words:
        words = req_list(request, "words", max_len=500)
        cleaned = []
        for w in words:
            token = str(w or "").strip()
            if token and token not in cleaned:
                cleaned.append(token)
        if not cleaned:
            raise ValueError("words 不能全为空字符串")
        if any(len(w) > 60 for w in cleaned):
            raise ValueError("单个敏感词不能超过 60 字符")
        source = "custom"
    else:
        cleaned, source = list(_DEFAULT_SENSITIVE_WORDS), "builtin"

    lowered = text.lower()
    occupied = [False] * len(text)
    hits = []
    for word in sorted(cleaned, key=len, reverse=True):
        needle = word.lower()
        start = 0
        while True:
            idx = lowered.find(needle, start)
            if idx < 0:
                break
            end = idx + len(needle)
            if not any(occupied[idx:end]):
                hits.append({"word": word, "start": idx, "end": end,
                             "line": text.count("\n", 0, idx) + 1,
                             "context": text[max(0, idx - 10):end + 10]})
                for i in range(idx, end):
                    occupied[i] = True
            start = idx + 1
            if len(hits) >= 2000:
                break
    hits.sort(key=lambda h: h["start"])

    masked = "".join("*" if occupied[i] else ch for i, ch in enumerate(text))
    by_word = {}
    for h in hits:
        by_word[h["word"]] = by_word.get(h["word"], 0) + 1
    return ok({
        "hits": hits,
        "count": len(hits),
        "unique": len(by_word),
        "by_word": [{"word": k, "count": v} for k, v in
                    sorted(by_word.items(), key=lambda kv: -kv[1])],
        "masked": masked,
        "clean": not hits,
        "source": source,
        "word_count": len(cleaned),
        "summary": (f"命中 {len(hits)} 处（{len(by_word)} 个词）" if hits else "未命中敏感词"),
    })
