# -*- coding: utf-8 -*-
"""devtools · 文本家族接口：text(6) str(6) markdown(6) json(6) log(5) encode(5) regex(6) = 40 个。

计数口径：每个 URL 记 1 个接口，全部为真实可用实现。
"""
import json
import quopri
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from django.utils.text import slugify

from .common import (as_lines, endpoint, fail, ok, opt_bool, opt_num, opt_str,
                     p, req, req_list, req_num, req_str)
from .data import REGEX_TOKENS

# =====================================================================
# text 文本处理（6）
# =====================================================================

_WORDS_RE = re.compile(r"[A-Za-z0-9]+")


def _case_convert(text, mode):
    words = [w.lower() for w in _WORDS_RE.findall(text)]
    if not words:
        return text
    if mode == "camel":
        return words[0] + "".join(w.capitalize() for w in words[1:])
    if mode == "pascal":
        return "".join(w.capitalize() for w in words)
    if mode == "snake":
        return "_".join(words)
    if mode == "kebab":
        return "-".join(words)
    if mode == "constant":
        return "_".join(w.upper() for w in words)
    if mode == "upper":
        return text.upper()
    if mode == "lower":
        return text.lower()
    if mode == "title":
        return text.title()
    if mode == "swap":
        return text.swapcase()
    raise ValueError(f"不支持的命名风格: {mode}（可选 camel/pascal/snake/kebab/constant/upper/lower/title/swap）")


@endpoint()
def text_case(request):
    """命名风格互转：camel/pascal/snake/kebab/constant/upper/lower/title/swap。"""
    text = req_str(request)
    return ok({"result": _case_convert(text, opt_str(request, "mode", "camel")), "mode": opt_str(request, "mode", "camel")})


@endpoint()
def text_wrap(request):
    """按宽度折行（中文按字符宽度 2 计）。"""
    text = req_str(request)
    width = int(req_num(request, "width", 40, minimum=4, maximum=500, integer=True))

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
    return ok({"lines": out, "width": width})


@endpoint()
def text_pad(request):
    """文本补齐/对齐：left/right/center。"""
    text = req_str(request)
    width = int(req_num(request, "width", 20, minimum=1, maximum=500, integer=True))
    fill = opt_str(request, "fill", " ")[:1] or " "
    align = opt_str(request, "align", "left")
    fn = {"left": str.ljust, "right": str.rjust, "center": str.center}.get(align)
    if not fn:
        raise ValueError("align 只支持 left/right/center")
    return ok({"result": fn(text, width, fill)})


@endpoint()
def text_replace(request):
    """字面量或正则替换，返回替换次数。"""
    text = req_str(request)
    find = req(request, "find")
    repl = opt_str(request, "replace", "")
    if opt_bool(request, "regex"):
        pattern, n = re.compile(str(find)), 0
        result, n = pattern.subn(repl, text)
    else:
        n = text.count(str(find))
        result = text.replace(str(find), repl)
    return ok({"result": result, "count": n})


_EXTRACTORS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "url": re.compile(r"https?://[^\s<>\"')\]]+"),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "mobile": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "landline": re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)"),
    "money": re.compile(r"[¥￥$]\s*\d+(?:,\d{3})*(?:\.\d+)?"),
    "number": re.compile(r"-?\d+(?:\.\d+)?"),
    "date": re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?"),
    "time": re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"),
    "hexcolor": re.compile(r"#[0-9a-fA-F]{6}\b"),
}


@endpoint()
def text_extract(request):
    """从文本抽取 email/URL/IP/手机号/座机/金额/数字/日期/时间/色值。"""
    text = req_str(request)
    kind = opt_str(request, "kind", "all")
    keys = list(_EXTRACTORS) if kind == "all" else [kind]
    unknown = [k for k in keys if k not in _EXTRACTORS]
    if unknown:
        raise ValueError(f"不支持的类型: {','.join(unknown)}")
    found = {k: sorted(set(_EXTRACTORS[k].findall(text))) for k in keys}
    if opt_bool(request, "dedupe") is False:
        found = {k: _EXTRACTORS[k].findall(text) for k in keys}
    total = sum(len(v) for v in found.values())
    return ok({"found": found, "total": total})


@endpoint()
def text_normalize(request):
    """Unicode 规范化 + 全半角 + 压缩空白 + 去零宽字符。"""
    text = req_str(request)
    steps = {}
    cur = text
    zero_width = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
    steps["removed_zero_width"] = len(zero_width.findall(cur))
    cur = zero_width.sub("", cur)
    if opt_bool(request, "nfkc", True):
        cur = unicodedata.normalize("NFKC", cur)
        steps["nfkc"] = True
    if opt_bool(request, "width", True):
        cur = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else chr(0x20) if c == "\u3000" else c for c in cur)
        steps["halfwidth"] = True
    if opt_bool(request, "collapse_space", True):
        cur = re.sub(r"[ \t]+", " ", cur)
        steps["collapse_space"] = True
    if opt_bool(request, "strip_lines", True):
        cur = "\n".join(ln.strip() for ln in as_lines(cur))
        steps["strip_lines"] = True
    return ok({"result": cur, "steps": steps, "len_before": len(text), "len_after": len(cur)})


# =====================================================================
# str 字符串进阶（6）
# =====================================================================


@endpoint()
def str_dedent(request):
    """去除公共前导空白（Python textwrap.dedent 逻辑）。"""
    import textwrap

    text = req_str(request)
    return ok({"result": textwrap.dedent(text)})


@endpoint()
def str_truncate(request):
    """智能截断：中文按 1 长度、英文单词按词边界，可加省略号。"""
    text = req_str(request)
    limit = int(req_num(request, "limit", 30, minimum=1, maximum=10000, integer=True))
    suffix = opt_str(request, "suffix", "…")
    n = len(suffix)
    if len(text) <= limit:
        return ok({"result": text, "truncated": False})
    cut = text[: max(limit - n, 0)]
    m = re.match(r"^(.*?)[\s，。,.\]]*$", cut)
    return ok({"result": (m.group(1) if m and len(m.group(1)) > limit // 2 else cut) + suffix, "truncated": True, "limit": limit})


@endpoint()
def str_char_stats(request):
    """字符构成统计：中文/字母/数字/标点/空白/Emoji 等。"""
    text = req_str(request)
    cats = Counter()
    for ch in text:
        if re.match(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", ch):
            cats["emoji"] += 1
        elif "\u4e00" <= ch <= "\u9fff":
            cats["hanzi"] += 1
        elif ch.isalpha():
            cats["alpha"] += 1
        elif ch.isdigit():
            cats["digit"] += 1
        elif ch.isspace():
            cats["space"] += 1
        elif unicodedata.category(ch).startswith("P"):
            cats["punct"] += 1
        else:
            cats["other"] += 1
    return ok({"total": len(text), "counts": dict(cats), "unique": len(set(text)),
               "without_spaces": len(text.replace(" ", ""))})


@endpoint()
def str_initials(request):
    """取中文首字母（降级：无拼音库时仅处理拉丁字符）。"""
    text = req_str(request)
    data = None
    try:
        from learning.pinyin_data import PINYIN_MAP  # 可降级适配：学习中心的拼音库

        data = PINYIN_MAP
    except Exception:
        data = None
    out = []
    hit = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if data and ch in data:
                out.append(data[ch][0].upper())
                hit += 1
            else:
                out.append(ch)
        elif ch.isascii() and ch.isalpha():
            out.append(ch.upper())
    return ok({"result": "".join(out), "hanzi_total": sum(1 for c in text if "\u4e00" <= c <= "\u9fff"),
               "resolved": hit, "provider": "learning.pinyin_data" if data else "latin-only"})


@endpoint()
def str_abbr(request):
    """缩写生成：每个词取首字符（支持中英混排）。"""
    text = req_str(request)
    max_len = int(opt_num(request, "max_len", 8, minimum=1, maximum=32) or 8)
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text)
    abbr = "".join(w[0].upper() if w[0].isascii() else w for w in words)
    return ok({"abbr": abbr[:max_len], "words": words})


@endpoint()
def str_reverse_words(request):
    """按词反转 / 按行反转。"""
    text = req_str(request)
    by_line = opt_bool(request, "by_line")
    if by_line:
        result = "\n".join(ln[::-1] for ln in as_lines(text))
    else:
        result = " ".join(_WORDS_RE.findall(text)[::-1]) or text
    return ok({"result": result})


# =====================================================================
# markdown（6）
# =====================================================================

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_MD_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_LIST_MARK_RE = re.compile(r"^(\s*)([-*+])\s+")
_QUOTE_MARK_RE = re.compile(r"^\s*>\s?")


def _inline_html(s):
    s = _MD_IMG.sub(r'<img src="\2" alt="\1">', s)
    s = _MD_LINK.sub(r'<a href="\2">\1</a>', s)
    s = _MD_BOLD.sub(r"<strong>\1</strong>", s)
    s = _MD_ITALIC.sub(r"<em>\1</em>", s)
    s = _MD_CODE.sub(r"<code>\1</code>", s)
    return s


def _md_to_html(md):
    lines, out, in_code, code_buf = as_lines(md), [], False, []
    in_list = False
    for ln in lines:
        if ln.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + "\n".join(code_buf) + "</code></pre>")
                code_buf, in_code = [], False
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(ln)
            continue
        m = _HEADING_RE.match(ln)
        if m:
            level = len(m.group(1))
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h{level}>{_inline_html(m.group(2))}</h{level}>")
            continue
        if _LIST_MARK_RE.match(ln):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + _inline_html(_LIST_MARK_RE.sub("", ln)) + "</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if _QUOTE_MARK_RE.match(ln):
            out.append("<blockquote>" + _inline_html(_QUOTE_MARK_RE.sub("", ln)) + "</blockquote>")
            continue
        if re.match(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", ln):
            out.append("<hr>")
            continue
        if ln.strip():
            out.append(f"<p>{_inline_html(ln.strip())}</p>")
    if in_code:
        out.append("<pre><code>" + "\n".join(code_buf) + "</code></pre>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


@endpoint()
def md_to_html(request):
    """Markdown → HTML（自研迷你渲染器：标题/粗斜体/行内码/链接/图片/列表/引用/分隔线/代码块）。"""
    return ok({"html": _md_to_html(req_str(request))})


@endpoint()
def md_headings(request):
    """提取标题结构（带层级与行号）。"""
    out = []
    for i, ln in enumerate(as_lines(req_str(request)), 1):
        m = _HEADING_RE.match(ln)
        if m:
            out.append({"level": len(m.group(1)), "text": m.group(2), "line": i, "slug": slugify(m.group(2)) or f"h-{i}"})
    return ok({"headings": out, "count": len(out)})


@endpoint()
def md_toc(request):
    """生成 Markdown 目录（缩进树 + 锚点）。"""
    items = []
    for ln in as_lines(req_str(request)):
        m = _HEADING_RE.match(ln)
        if m:
            t = m.group(2)
            anchor = re.sub(r"[^\w\u4e00-\u9fff-]", "", t.lower().replace(" ", "-")) or "sec"
            items.append({"level": len(m.group(1)), "text": t, "anchor": anchor})
    toc = "\n".join("  " * (i["level"] - 1) + f"- [{i['text']}](#{i['anchor']})" for i in items)
    return ok({"toc": toc, "count": len(items)})


@endpoint()
def md_strip(request):
    """剥离 Markdown 标记为纯文本。"""
    text = req_str(request)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = _MD_IMG.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _HEADING_RE.sub(r"\2", text)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "", text, flags=re.M)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_ITALIC.sub(r"\1", text)
    text = _MD_CODE.sub(r"\1", text)
    return ok({"text": re.sub(r"\n{3,}", "\n\n", text).strip()})


@endpoint()
def md_table(request):
    """对齐 Markdown 表格（按显示宽度计算列宽）。"""
    rows = [ln for ln in as_lines(req_str(request)) if ln.strip().startswith("|")]
    if len(rows) < 2:
        raise ValueError("至少需要表头 + 分隔行两行以 | 开头的表格")
    parsed = []
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        parsed.append(cells)
    sep = parsed[1]
    is_sep = all(re.fullmatch(r":?-{2,}:?", c) for c in sep if c) if sep else False

    def w(ch):
        return 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1

    def disp(s):
        return sum(w(c) for c in s)

    if is_sep:
        body, aligns = [parsed[0]], []
        for c in sep:
            if c.startswith(":") and c.endswith(":"):
                aligns.append("center")
            elif c.endswith(":"):
                aligns.append("right")
            else:
                aligns.append("left")
    else:
        body, aligns = parsed, ["left"] * max(len(r) for r in parsed)
    ncol = max(len(r) for r in body)
    widths = [max(disp(r[i]) if i < len(r) else 0 for r in body) for i in range(ncol)]

    def render(row):
        cells = []
        for i in range(ncol):
            v = row[i] if i < len(row) else ""
            pad = widths[i] - disp(v)
            a = aligns[i] if i < len(aligns) else "left"
            if a == "right":
                cells.append(" " * pad + v)
            elif a == "center":
                cells.append(" " * (pad // 2) + v + " " * (pad - pad // 2))
            else:
                cells.append(v + " " * pad)
        return "| " + " | ".join(cells) + " |"

    out = [render(body[0])]
    out.append("|" + "|".join("-" * (wd + 2) for wd in widths) + "|")
    out.extend(render(r) for r in body[1:])
    return ok({"table": "\n".join(out), "rows": len(body) - 1, "cols": ncol})


_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.S)


@endpoint()
def md_frontmatter(request):
    """解析/生成 YAML-lite frontmatter（key: value 与 key: [a, b]）。"""
    mode = opt_str(request, "mode", "parse")
    if mode == "build":
        meta = p(request, "meta") or {}
        body = opt_str(request, "body")
        if not isinstance(meta, dict):
            raise ValueError("meta 必须是对象")
        fm = "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" if isinstance(v, (list, dict)) else f"{k}: {v}" for k, v in meta.items()) + "\n---\n"
        return ok({"document": fm + body})
    m = _FRONT_RE.match(req_str(request))
    if not m:
        return ok({"has_frontmatter": False, "meta": {}, "body": p(request, "text")})
    meta = {}
    for ln in m.group(1).split("\n"):
        if ":" in ln:
            k, v = ln.split(":", 1)
            k, v = k.strip(), v.strip()
            try:
                meta[k] = json.loads(v)
            except ValueError:
                meta[k] = v
    return ok({"has_frontmatter": True, "meta": meta, "body": m.group(2)})


# =====================================================================
# json（6）
# =====================================================================


def _flatten(obj, prefix="", sep="."):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{sep}{k}" if prefix else str(k)
            out.update(_flatten(v, key, sep))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}{sep}{i}" if prefix else str(i), sep))
    else:
        out[prefix] = obj
    return out


@endpoint()
def json_flatten(request):
    """嵌套 JSON 拍平为 a.b.0 形式。"""
    data = req(request, "data")
    if isinstance(data, str):
        data = json.loads(data)
    return ok({"flat": _flatten(data, sep=opt_str(request, "sep", "."))})


@endpoint()
def json_unflatten(request):
    """拍平 JSON 还原为嵌套结构。"""
    flat = req(request, "flat")
    if isinstance(flat, str):
        flat = json.loads(flat)
    if not isinstance(flat, dict):
        raise ValueError("flat 必须是对象")
    sep = opt_str(request, "sep", ".")
    root = {}
    for k, v in flat.items():
        parts = k.split(sep)
        cur = root
        for i, part in enumerate(parts):
            nxt_is_idx = i + 1 < len(parts) and parts[i + 1].isdigit()
            if nxt_is_idx:
                cur = cur.setdefault(part, [])
                nxt = parts[i + 1]
                while len(cur) <= int(nxt):
                    cur.append(None)
                cur = cur[int(nxt)]
            elif i + 1 < len(parts):
                cur = cur.setdefault(part, {})
            else:
                if isinstance(cur, list):
                    cur.append(v)
                else:
                    cur[part] = v
    return ok({"tree": root})


@endpoint()
def json_merge(request):
    """深度合并多个对象；strategy=overwrite/keep-first/arrays-union。"""
    items = req_list(request, "objects")
    strategy = opt_str(request, "strategy", "overwrite")
    objs = []
    for it in items:
        if isinstance(it, str):
            it = json.loads(it)
        if not isinstance(it, dict):
            raise ValueError("objects 内每一项都必须是对象")
        objs.append(it)

    def merge(a, b):
        for k, v in b.items():
            if k in a and isinstance(a[k], dict) and isinstance(v, dict):
                merge(a[k], v)
            elif k in a and strategy == "keep-first":
                continue
            elif k in a and strategy == "arrays-union" and isinstance(a[k], list) and isinstance(v, list):
                a[k] = a[k] + [x for x in v if x not in a[k]]
            else:
                a[k] = v
        return a

    out = {}
    for o in objs:
        out = merge(out, json.loads(json.dumps(o, ensure_ascii=False)))
    return ok({"merged": out, "strategy": strategy})


@endpoint()
def json_ndjson(request):
    """NDJSON ↔ JSON 数组 双向转换。"""
    direction = opt_str(request, "direction", "to-ndjson")
    if direction == "to-ndjson":
        data = req(request, "data")
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
            raise ValueError("data 必须是数组")
        return ok({"ndjson": "\n".join(json.dumps(x, ensure_ascii=False) for x in data)})
    text = req_str(request)
    items = [json.loads(ln) for ln in as_lines(text.strip()) if ln.strip()]
    return ok({"array": items, "count": len(items)})


@endpoint()
def json_stats(request):
    """JSON 结构统计：节点数/深度/类型分布/最大数组。"""
    data = req(request, "data")
    if isinstance(data, str):
        data = json.loads(data)
    types, max_depth, nodes, max_arr = Counter(), 0, 0, [0, ""]

    def walk(o, d, path="$"):
        nonlocal max_depth, nodes
        nodes += 1
        max_depth = max(max_depth, d)
        if isinstance(o, dict):
            types["object"] += 1
            for k, v in o.items():
                walk(v, d + 1, f"{path}.{k}")
        elif isinstance(o, list):
            types["array"] += 1
            if len(o) > max_arr[0]:
                max_arr[0], max_arr[1] = len(o), path
            for i, v in enumerate(o):
                walk(v, d + 1, f"{path}[{i}]")
        elif isinstance(o, bool):
            types["boolean"] += 1
        elif isinstance(o, (int, float)):
            types["number"] += 1
        elif isinstance(o, str):
            types["string"] += 1
        elif o is None:
            types["null"] += 1

    walk(data, 1)
    return ok({"types": dict(types), "depth": max_depth, "max_array": {"path": max_arr[1], "len": max_arr[0]}})


@endpoint()
def json_pick(request):
    """字段挑选/剔除：include 优先，否则 exclude。"""
    data = req(request, "data")
    if isinstance(data, str):
        data = json.loads(data)
    include = p(request, "include")
    exclude = p(request, "exclude") or []
    if not isinstance(data, (dict, list)):
        raise ValueError("data 必须是对象或数组")
    items = data if isinstance(data, list) else [data]

    def pick(o):
        if include:
            return {k: o[k] for k in include if k in o}
        return {k: v for k, v in o.items() if k not in exclude}

    out = [pick(i) if isinstance(i, dict) else i for i in items]
    return ok({"result": out if isinstance(data, list) else out[0], "count": len(items)})


# =====================================================================
# log 日志分析（5）
# =====================================================================

_LOG_RE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>\S+) (?P<path>\S+) (?P<proto>[^"]+)" '
    r"(?P<status>\d{3}) (?P<size>\S+)(?: \"(?P<ref>[^\"]*)\" \"(?P<ua>[^\"]*)\")?"
)


@endpoint()
def log_parse(request):
    """Nginx/Apache common+combined 日志解析。"""
    text = req_str(request)
    rows, bad = [], 0
    for ln in as_lines(text):
        ln = ln.strip()
        if not ln:
            continue
        m = _LOG_RE.match(ln)
        if m:
            d = m.groupdict()
            d["status"] = int(d["status"])
            d["size"] = None if d["size"] == "-" else int(d["size"])
            rows.append(d)
        else:
            bad += 1
    return ok({"rows": rows, "parsed": len(rows), "unparsed": bad, "total": len(rows) + bad})


def _iter_log(text, pattern=_LOG_RE):
    for ln in as_lines(text):
        m = pattern.match(ln.strip())
        if m:
            yield m.groupdict()


@endpoint()
def log_level_stat(request):
    """应用日志级别统计（INFO/WARN/ERROR/DEBUG…）。"""
    text = req_str(request)
    levels = Counter()
    samples = {}
    for ln in as_lines(text):
        m = re.search(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL)\b", ln, re.I)
        if m:
            lv = m.group(1).upper()
            lv = "WARN" if lv == "WARNING" else lv
            levels[lv] += 1
            samples.setdefault(lv, ln.strip()[:200])
    total = sum(levels.values())
    return ok({"levels": dict(levels), "total": total, "samples": samples,
               "error_rate": round(levels.get("ERROR", 0) / total, 4) if total else 0})


@endpoint()
def log_timeframe(request):
    """按时间粒度聚合日志量（支持 ISO 时间戳与 nginx 括号时间）。"""
    text = req_str(request)
    unit = opt_str(request, "unit", "hour")
    buckets = Counter()
    for d in _iter_log(text):
        t = d.get("time", "")
        mm = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})", t)
        if not mm:
            mm = re.match(r"\d{2}/(\w{3})/\d{4}:(\d{2}):(\d{2})", t)
            if not mm:
                continue
            months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                      "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
            key = f"{mm.group(2)}:{mm.group(3)}" if unit == "hour" else f"{mm.group(2)}:{mm.group(2)}-{months.get(mm.group(1), '?')}"
            buckets[key] += 1
            continue
        day, hh, mi = mm.groups()
        key = {"day": day, "hour": f"{day} {hh}:00", "minute": f"{day} {hh}:{mi}"}[unit]
        buckets[key] += 1
    return ok({"series": [{"bucket": k, "count": v} for k, v in sorted(buckets.items())], "unit": unit})


@endpoint()
def log_topn(request):
    """日志 TOP N：按 ip / path / status / ua 统计。"""
    text = req_str(request)
    key = opt_str(request, "key", "ip")
    n = int(opt_num(request, "n", 10, minimum=1, maximum=100) or 10)
    counter = Counter()
    for d in _iter_log(text):
        v = d.get(key) or d.get("ua") or "unknown"
        counter[v] += 1
    return ok({"top": [{"value": v, "count": c} for v, c in counter.most_common(n)], "unique": len(counter)})


@endpoint()
def log_filter(request):
    """日志过滤：级别 / 关键词 / 正则 / 取反。"""
    text = req_str(request)
    level = opt_str(request, "level", "").upper()
    keyword = opt_str(request, "keyword")
    regex = opt_str(request, "regex")
    invert = opt_bool(request, "invert")
    pat = re.compile(regex) if regex else None
    out = []
    for ln in as_lines(text):
        keep = True
        if level and level not in ln.upper():
            keep = False
        if keyword and keyword not in ln:
            keep = False
        if pat and not pat.search(ln):
            keep = False
        if invert:
            keep = not keep
        if keep and ln.strip():
            out.append(ln)
    return ok({"lines": out, "matched": len(out)})


# =====================================================================
# encode 编码（5）
# =====================================================================


@endpoint()
def encode_base32(request):
    """Base32 编码/解码。"""
    direction = opt_str(request, "direction", "encode")
    text = req_str(request)
    import base64

    if direction == "encode":
        return ok({"result": base64.b32encode(text.encode("utf-8")).decode("ascii")})
    return ok({"result": base64.b32decode(text.strip().encode("ascii")).decode("utf-8")})


@endpoint()
def encode_base85(request):
    """Base85（RFC1924/b85 与 ASCII85/a85）编码/解码。"""
    import base64

    direction = opt_str(request, "direction", "encode")
    variant = opt_str(request, "variant", "b85")
    text = req_str(request)
    enc = base64.b85encode if variant == "b85" else base64.a85encode
    dec = base64.b85decode if variant == "b85" else base64.a85decode
    if direction == "encode":
        return ok({"result": enc(text.encode("utf-8")).decode("ascii"), "variant": variant})
    return ok({"result": dec(text.strip().encode("ascii")).decode("utf-8"), "variant": variant})


@endpoint()
def encode_qp(request):
    """Quoted-Printable 编码/解码。"""
    direction = opt_str(request, "direction", "encode")
    text = req_str(request)
    if direction == "encode":
        return ok({"result": quopri.encodestring(text.encode("utf-8")).decode("ascii")})
    return ok({"result": quopri.decodestring(text.encode("ascii", errors="ignore")).decode("utf-8", errors="replace")})


@endpoint()
def encode_unicode_escape(request):
    """Unicode 转义（反斜杠 uXXXX 形式）与还原。"""
    direction = opt_str(request, "direction", "encode")
    text = req_str(request)
    if direction == "encode":
        return ok({"result": text.encode("unicode_escape").decode("ascii")})
    return ok({"result": text.encode("ascii", errors="ignore").decode("unicode_escape")})


@endpoint()
def encode_punycode(request):
    """Punycode / IDNA（xn--）编码与解码。"""
    direction = opt_str(request, "direction", "encode")
    text = req_str(request)
    if direction == "encode":
        return ok({"punycode": text.encode("punycode").decode("ascii"),
                   "idna": ("xn--" + text.encode("punycode").decode("ascii")) if not text.isascii() else text})
    raw = text.strip()
    if raw.lower().startswith("xn--"):
        raw = raw[4:]
    return ok({"result": raw.encode("ascii").decode("punycode")})


# =====================================================================
# regex 正则（6）
# =====================================================================


@endpoint()
def regex_replace(request):
    """正则替换（带次数与命名组支持）。"""
    text = req_str(request)
    pattern = req(request, "pattern")
    repl = opt_str(request, "replace", "")
    flags = re.I if opt_bool(request, "ignore_case") else 0
    flags |= re.M if opt_bool(request, "multiline") else 0
    compiled = re.compile(str(pattern), flags)
    result, n = compiled.subn(repl, text)
    return ok({"result": result, "count": n})


@endpoint()
def regex_extract(request):
    """正则提取全部匹配（含命名组/位置）。"""
    text = req_str(request)
    pattern = req(request, "pattern")
    flags = re.I if opt_bool(request, "ignore_case") else 0
    compiled = re.compile(str(pattern), flags)
    matches = []
    for m in compiled.finditer(text):
        item = {"match": m.group(0), "start": m.start(), "end": m.end()}
        if m.groups():
            item["groups"] = list(m.groups())
        if m.groupdict():
            item["named"] = {k: v for k, v in m.groupdict().items()}
        matches.append(item)
        if len(matches) >= 1000:
            break
    return ok({"matches": matches, "count": len(matches)})


@endpoint()
def regex_split(request):
    """正则切分。"""
    text = req_str(request)
    pattern = req(request, "pattern")
    parts = re.split(str(pattern), text)
    if opt_bool(request, "drop_empty"):
        parts = [x for x in parts if x]
    return ok({"parts": parts, "count": len(parts)})


@endpoint()
def regex_explain(request):
    """正则成分解释（常见 token 中文说明）。"""
    pattern = req_str(request, "pattern")
    found = [t for t in REGEX_TOKENS if all(tok in pattern for tok in t[:1])]
    explained = [{"token": t[0], "meaning": t[1]} for t in found]
    try:
        re.compile(pattern)
        valid = True
        err = ""
    except re.error as e:
        valid, err = False, str(e)
    return ok({"valid": valid, "error": err, "tokens": explained, "length": len(pattern)})


@endpoint()
def regex_grep(request):
    """按正则过滤行（支持 -v 反选与高亮标记）。"""
    text = req_str(request)
    pattern = req(request, "pattern")
    pat = re.compile(str(pattern))
    invert = opt_bool(request, "invert")
    keep, drop = [], 0
    for ln in as_lines(text):
        hit = bool(pat.search(ln))
        if invert:
            hit = not hit
        if hit and ln.strip():
            keep.append(re.sub(f"({pattern})", r"【\1】", ln) if not invert and opt_bool(request, "highlight") else ln)
        else:
            drop += 1
    return ok({"lines": keep, "matched": len(keep), "skipped": drop})


@endpoint()
def regex_template(request):
    """{{var}} 模板渲染（支持点路径取值与缺省值）。"""
    template = req_str(request)
    context = p(request, "context") or {}
    if not isinstance(context, dict):
        raise ValueError("context 必须是对象")

    def lookup(path):
        cur = context
        for part in path.split("."):
            if isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)] if int(part) < len(cur) else None
            elif isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = None
            if cur is None:
                break
        return cur

    def repl(m):
        expr = m.group(1).strip()
        if "|" in expr:
            path, default = expr.split("|", 1)
            v = lookup(path.strip())
            return str(v) if v is not None else default.strip()
        v = lookup(expr)
        return "" if v is None else str(v)

    result = re.sub(r"\{\{\s*(.+?)\s*\}\}", repl, template)
    unresolved = [m.group(1) for m in re.finditer(r"\{\{\s*(.+?)\s*\}\}", result)]
    return ok({"result": result, "unresolved": unresolved})


# =====================================================================
# 差值：text 总数自检（模块内计数）
# =====================================================================
TEXT_FAMILY_COUNT = 6 + 6 + 6 + 6 + 5 + 5 + 6  # = 40
