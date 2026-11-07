# -*- coding: utf-8 -*-
"""minitools · 文本处理家族（30 个，编号 1-30）。纯函数，无状态。"""
import random
import re
import unicodedata
from collections import Counter

from .common import (as_lines, endpoint, ok, opt_bool, opt_num, opt_str,
                     req_list, req_num, req_str)


# 停用词表（中英文）
_STOPWORDS_EN = set("""a an the and or but if then else for of to in on at by with from is are was were be been being this that these those it its as not no so such too very can will just should now i you he she we they me him her us them my your his her our their what which who whom whose when where why how all any both each few more most other some only own same than too s t don didn doesn isn aren wasn weren""".split())
_STOPWORDS_CN = set("的 了 和 是 在 我 有 就 也 都 这 那 你 他 她 它 我们 你们 他们 一个 没有 为 之 以 及 与 或 而 等 被 把 让 向 从 到 对 于 上 下 中 里 后 前 着 过 吗 呢 吧 啊 呀 哦 嗯 不 人 之 大 小 上 下 多 少 来 去 说 要 去 会 着 看 好 自己 这 那 其 之 而 且 并 或 如 若 则 即 虽 但 还 又 再 已 曾 正 才 只 就 都 也 还 很 太 最 更 非常 比较 真 好 最 十分 特别 挺 蛮 超""".split())


@endpoint()
def case_title(request):
    """1. 标题大小写（每个单词首字母大写）。"""
    text = req_str(request)
    return ok({"result": text.title()})


@endpoint()
def case_sentence(request):
    """2. 句子大小写（句首大写）。"""
    text = req_str(request)
    return ok({"result": text.capitalize()})


@endpoint()
def case_alternating(request):
    """3. 交替大小写。"""
    text = req_str(request)
    out = []
    upper = True
    for ch in text:
        if ch.isalpha():
            out.append(ch.upper() if upper else ch.lower())
            upper = not upper
        else:
            out.append(ch)
    return ok({"result": "".join(out)})


@endpoint()
def case_invert(request):
    """4. 大小写翻转。"""
    text = req_str(request)
    return ok({"result": text.swapcase()})


@endpoint()
def fullwidth_halfwidth(request):
    """5. 全角半角互转。direction: half2full / full2half。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "half2full")
    if direction == "half2full":
        out = []
        for ch in text:
            code = ord(ch)
            if 0x21 <= code <= 0x7E:
                out.append(chr(code + 0xFEE0))
            elif ch == " ":
                out.append("\u3000")
            else:
                out.append(ch)
        return ok({"result": "".join(out)})
    if direction == "full2half":
        out = []
        for ch in text:
            code = ord(ch)
            if 0xFF01 <= code <= 0xFF5E:
                out.append(chr(code - 0xFEE0))
            elif ch == "\u3000":
                out.append(" ")
            else:
                out.append(ch)
        return ok({"result": "".join(out)})
    raise ValueError("direction 必须是 half2full 或 full2half")


@endpoint()
def dedup_lines(request):
    """6. 按行去重（保留顺序）。"""
    text = req_str(request)
    lines = as_lines(text)
    seen = set()
    out = []
    removed = 0
    for ln in lines:
        if ln in seen:
            removed += 1
            continue
        seen.add(ln)
        out.append(ln)
    return ok({"result": "\n".join(out), "removed": removed})


@endpoint()
def sort_lines(request):
    """7. 按行排序。mode: alpha/numeric/length；reverse: bool。"""
    text = req_str(request)
    mode = opt_str(request, "mode", "alpha")
    reverse = opt_bool(request, "reverse", False)
    lines = as_lines(text)
    if mode == "numeric":
        try:
            lines.sort(key=lambda x: float(x.strip()) if x.strip() else 0.0, reverse=reverse)
        except ValueError:
            raise ValueError("numeric 模式下存在非数字行")
    elif mode == "length":
        lines.sort(key=lambda x: len(x), reverse=reverse)
    elif mode == "alpha":
        lines.sort(key=lambda x: x.lower(), reverse=reverse)
    else:
        raise ValueError("mode 必须是 alpha/numeric/length")
    return ok({"result": "\n".join(lines)})


@endpoint()
def add_line_numbers(request):
    """8. 添加行号。start: 起始号；width: 宽度。"""
    text = req_str(request)
    start = int(opt_num(request, "start", 1, integer=True))
    width = int(opt_num(request, "width", 0, minimum=0, maximum=10, integer=True))
    lines = as_lines(text)
    out = []
    for i, ln in enumerate(lines):
        num = str(start + i).zfill(width) if width else str(start + i)
        out.append(f"{num}\t{ln}")
    return ok({"result": "\n".join(out)})


@endpoint()
def remove_blank_lines(request):
    """9. 删除空行。"""
    text = req_str(request)
    lines = as_lines(text)
    kept = [ln for ln in lines if ln.strip()]
    return ok({"result": "\n".join(kept), "removed": len(lines) - len(kept)})


@endpoint()
def trim_lines(request):
    """10. 清理每行首尾空白。"""
    text = req_str(request)
    lines = as_lines(text)
    return ok({"result": "\n".join(ln.strip() for ln in lines)})


@endpoint()
def collapse_spaces(request):
    """11. 合并多空格为单空格。"""
    text = req_str(request)
    return ok({"result": re.sub(r"[ \t]+", " ", text)})


@endpoint()
def line_ending_convert(request):
    """12. 换行符转换。target: crlf/lf/cr。"""
    text = req_str(request)
    target = opt_str(request, "target", "lf")
    # 统一为 \n
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    mapping = {"crlf": "\r\n", "lf": "\n", "cr": "\r"}
    if target not in mapping:
        raise ValueError("target 必须是 crlf/lf/cr")
    return ok({"result": norm.replace("\n", mapping[target])})


@endpoint()
def tab_space_convert(request):
    """13. 制表符空格互转。direction: tab2space / space2tab；size: 每tab空格数。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "tab2space")
    size = int(opt_num(request, "size", 4, minimum=1, maximum=16, integer=True))
    if direction == "tab2space":
        return ok({"result": text.replace("\t", " " * size)})
    if direction == "space2tab":
        return ok({"result": text.replace(" " * size, "\t")})
    raise ValueError("direction 必须是 tab2space 或 space2tab")


@endpoint()
def quote_straight_smart(request):
    """14. 直引号弯引号互转。direction: straight2smart / smart2straight。"""
    text = req_str(request)
    direction = opt_str(request, "direction", "straight2smart")
    if direction == "straight2smart":
        out = []
        open_d = True
        for ch in text:
            if ch == '"':
                out.append("\u201c" if open_d else "\u201d")
                open_d = not open_d
            else:
                out.append(ch)
        return ok({"result": "".join(out)})
    if direction == "smart2straight":
        return ok({"result": text.replace("\u201c", '"').replace("\u201d", '"')})
    raise ValueError("direction 必须是 straight2smart 或 smart2straight")


@endpoint()
def repeat_generator(request):
    """15. 文本重复生成。count: 次数；separator: 分隔符。"""
    text = req_str(request)
    count = int(req_num(request, "count", minimum=1, maximum=10000, integer=True))
    sep = opt_str(request, "separator", "")
    if len(text) * count > 5 * 1024 * 1024:
        raise ValueError("生成结果过大（上限 5MB），请减少文本长度或重复次数")
    return ok({"result": sep.join([text] * count)})


@endpoint()
def char_frequency(request):
    """16. 字符频率统计。"""
    text = req_str(request)
    cnt = Counter(ch for ch in text if not ch.isspace())
    top = cnt.most_common(10)
    return ok({
        "top_chars": [{"char": c, "count": n} for c, n in top],
        "total": sum(cnt.values()),
    })


@endpoint()
def palindrome_check(request):
    """17. 回文检测。"""
    text = req_str(request)
    normalized = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", text).lower()
    return ok({"is_palindrome": normalized == normalized[::-1], "normalized": normalized})


@endpoint()
def anagram_check(request):
    """18. 字谜检测（两词字母相同）。"""
    a = req_str(request, "text_a")
    b = req_str(request, "text_b")
    na = sorted(re.sub(r"\s+", "", a.lower()))
    nb = sorted(re.sub(r"\s+", "", b.lower()))
    return ok({"is_anagram": na == nb})


@endpoint()
def vowel_consonant_count(request):
    """19. 元音辅音统计。"""
    text = req_str(request).lower()
    vowels = sum(1 for ch in text if ch in "aeiou")
    consonants = sum(1 for ch in text if ch.isalpha() and ch not in "aeiou")
    digits = sum(1 for ch in text if ch.isdigit())
    return ok({"vowels": vowels, "consonants": consonants, "digits": digits})


def _levenshtein(a, b):
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[lb]


@endpoint()
def similarity(request):
    """20. 文本相似度（Jaccard + Levenshtein）。"""
    from difflib import SequenceMatcher

    a = req_str(request, "text_a")
    b = req_str(request, "text_b")
    if len(a) > 2000 or len(b) > 2000:
        ratio = SequenceMatcher(None, a, b).quick_ratio()
        sa, sb = set(a.lower()), set(b.lower())
        j = len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0
        return ok({"jaccard": round(j, 4), "levenshtein": None,
                   "ratio": round(ratio, 4), "approximate": True})
    sa, sb = set(a.lower()), set(b.lower())
    j = len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0
    lev = _levenshtein(a, b)
    ratio = 1.0 - lev / max(len(a), len(b)) if max(len(a), len(b)) else 1.0
    return ok({"jaccard": round(j, 4), "levenshtein": lev, "ratio": round(ratio, 4), "approximate": False})


@endpoint()
def extract_summary(request):
    """21. 提取式摘要（取首句+关键词句）。"""
    text = req_str(request)
    sentences = re.split(r"(?<=[。！？!?\.])\s+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    n = int(opt_num(request, "sentences", 2, minimum=1, maximum=10, integer=True))
    summary = "".join(sentences[:n])
    return ok({"summary": summary})


@endpoint()
def keyword_extract(request):
    """22. 关键词提取（词频 TF）。"""
    text = req_str(request)
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text.lower())
    words = [w for w in words if w not in _STOPWORDS_EN and w not in _STOPWORDS_CN and len(w) > 1]
    cnt = Counter(words)
    top_n = int(opt_num(request, "top_n", 10, minimum=1, maximum=50, integer=True))
    return ok({"keywords": [{"word": w, "count": c} for w, c in cnt.most_common(top_n)]})


@endpoint()
def stopword_filter(request):
    """23. 停用词过滤（中英文内置表）。"""
    text = req_str(request)
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|\s+|[^\sA-Za-z0-9\u4e00-\u9fff]", text)
    removed = 0
    out = []
    for w in words:
        if w.strip() and w.lower() in _STOPWORDS_EN:
            removed += 1
            continue
        if w in _STOPWORDS_CN:
            removed += 1
            continue
        out.append(w)
    return ok({"result": "".join(out), "removed_count": removed})


@endpoint()
def shuffle_words(request):
    """24. 单词内字母不变打乱（保留首尾字母）。"""
    text = req_str(request)

    def _shuffle_word(w):
        if len(w) <= 3:
            return w
        middle = list(w[1:-1])
        random.shuffle(middle)
        return w[0] + "".join(middle) + w[-1]

    tokens = re.findall(r"[A-Za-z]+|\S+|\s+", text)
    out = []
    for t in tokens:
        if t.isalpha() and len(t) > 3:
            out.append(_shuffle_word(t))
        else:
            out.append(t)
    return ok({"result": "".join(out)})


@endpoint()
def case_convert_naming(request):
    """25. 命名风格互转 snake/camel/kebab/pascal。"""
    text = req_str(request)
    to = opt_str(request, "to", "camel")
    # 先拆词
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    if not words:
        return ok({"result": text})
    if to == "snake":
        result = "_".join(words)
    elif to == "camel":
        result = words[0] + "".join(w.capitalize() for w in words[1:])
    elif to == "kebab":
        result = "-".join(words)
    elif to == "pascal":
        result = "".join(w.capitalize() for w in words)
    else:
        raise ValueError("to 必须是 snake/camel/kebab/pascal")
    return ok({"result": result})


@endpoint()
def md_table_generate(request):
    """26. Markdown 表格生成。headers: 数组；rows: 二维数组。"""
    headers = req_list(request, "headers")
    rows = req_list(request, "rows")
    header_line = "| " + " | ".join(str(h) for h in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
    body = []
    for row in rows:
        if isinstance(row, list):
            body.append("| " + " | ".join(str(c) for c in row) + " |")
        else:
            body.append("| " + str(row) + " |")
    return ok({"markdown": "\n".join([header_line, sep_line] + body)})


@endpoint()
def indent_block(request):
    """27. 文本块缩进/反缩进。level: 层数；char: 缩进字符。"""
    text = req_str(request)
    level = int(opt_num(request, "level", 1, minimum=-20, maximum=20, integer=True))
    char = opt_str(request, "char", "  ")
    lines = as_lines(text)
    out = []
    for ln in lines:
        if level >= 0:
            out.append(char * level + ln)
        else:
            stripped = ln
            for _ in range(-level):
                if stripped.startswith(char):
                    stripped = stripped[len(char):]
                else:
                    break
            out.append(stripped)
    return ok({"result": "\n".join(out)})


@endpoint()
def center_align(request):
    """28. 文本居中对齐。width: 宽度。"""
    text = req_str(request)
    width = int(req_num(request, "width", minimum=1, maximum=200, integer=True))
    lines = as_lines(text)
    out = [ln.center(width) for ln in lines]
    return ok({"result": "\n".join(out)})


@endpoint()
def word_wrap(request):
    """29. 按宽度自动换行。"""
    text = req_str(request)
    width = int(req_num(request, "width", minimum=4, maximum=200, integer=True))

    def w(ch):
        return 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1

    out = []
    for para in as_lines(text):
        line, cur = "", 0
        for ch in para:
            cw = w(ch)
            if cur + cw > width and line:
                out.append(line)
                line, cur = "", 0
            line += ch
            cur += cw
        out.append(line)
    return ok({"result": "\n".join(out)})


@endpoint()
def zero_width_remove(request):
    """30. 移除零宽字符。"""
    text = req_str(request)
    zw = "\u200b\u200c\u200d\u2060\ufeff"
    removed = sum(text.count(c) for c in zw)
    result = "".join(ch for ch in text if ch not in zw)
    return ok({"result": result, "removed": removed})
