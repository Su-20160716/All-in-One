# -*- coding: utf-8 -*-
"""officesuite · 文档增强面（F45–F47）：批注 / 表格公式 / 演示大纲。

三个能力都不依赖外部服务：
- 批注只落库；
- 公式求值走自写的词法 + 递归下降解析（AST 白名单，绝无 eval）；
- 大纲生成在无 LLM 时按「标题=页、列表项=要点」规则降级。
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db.models import Q

from core.scoping import scope_queryset
from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_str)
from officesuite.models import DocAnnotation

# =====================================================================
# F45 文档批注
# =====================================================================


def _visible_file(user, pk):
    from files.models import FileMeta

    try:
        fid = int(pk)
    except (TypeError, ValueError):
        raise ValueError("file 必须是整数")
    f = scope_queryset(FileMeta.objects.filter(is_deleted=False), user).filter(pk=fid).first()
    if not f:
        raise ValueError("文件不存在或无权访问")
    return f


def _annotation_dict(a, replies=None):
    d = {
        "id": a.pk,
        "file": a.file_id,
        "page": a.page,
        "rect": a.rect or {},
        "body": a.body,
        "parent": a.parent_id,
        "resolved": a.resolved,
        "owner": a.owner.username,
        "owner_name": getattr(a.owner, "display_name", "") or a.owner.username,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
    if replies is not None:
        d["replies"] = replies
    return d


def _clean_rect(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k in ("x", "y", "w", "h"):
        if raw.get(k) is None:
            continue
        try:
            v = float(raw[k])
        except (TypeError, ValueError):
            raise ValueError(f"rect.{k} 必须是数字")
        out[k] = round(min(max(v, 0.0), 1.0), 4)
    return out


@endpoint(("GET", "POST"))
def annotations(request):
    """GET：按文件（可加 page）列批注，主批注带 replies 子列表。

    POST：新增批注或回复（传 parent）。rect 用页宽高百分比，缩放安全。
    """
    if request.method == "GET":
        f = _visible_file(request.user, p(request, "file"))
        qs = DocAnnotation.objects.filter(file=f).select_related("owner")
        page = opt_num(request, "page", integer=True)
        if page:
            qs = qs.filter(page=int(page))
        if opt_bool(request, "unresolved"):
            qs = qs.filter(resolved=False)
        items = list(qs.order_by("page", "created_at")[:1000])
        root_map = {}
        roots = []
        for a in items:
            if a.parent_id is None:
                node = _annotation_dict(a, replies=[])
                root_map[a.pk] = node
                roots.append(node)
        for a in items:
            if a.parent_id is not None:
                parent = root_map.get(a.parent_id)
                if parent is not None:
                    parent["replies"].append(_annotation_dict(a))
        return ok({"file": {"id": f.pk, "name": f.name},
                   "items": roots, "count": len(items)})

    f = _visible_file(request.user, p(request, "file"))
    body = req_str(request, "body").strip()
    if not body:
        raise ValueError("批注内容不能为空")
    if len(body) > 2000:
        raise ValueError("批注内容不能超过 2000 字")
    page = int(opt_num(request, "page", 1, integer=True, minimum=1))
    parent = None
    raw_parent = p(request, "parent")
    if raw_parent not in (None, "", 0, "0"):
        parent = DocAnnotation.objects.filter(pk=int(raw_parent), file=f).first()
        if not parent:
            raise ValueError("父批注不存在或不属于该文件")
        if parent.parent_id:
            parent = parent.parent  # 回复只挂两级，避免无限套娃
    obj = DocAnnotation.objects.create(
        file=f, owner=request.user, page=page,
        rect=_clean_rect(p(request, "rect")), body=body, parent=parent,
    )
    return ok(_annotation_dict(obj))


# =====================================================================
# F46 表格公式求值（AST 白名单，无 eval）
# =====================================================================

MAX_FORMULA_LEN = 500
MAX_RANGE_CELLS = 10000
MAX_DEPTH = 60

_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]{1,6})$")
_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


class FormulaError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class RangeValue:
    __slots__ = ("cells",)

    def __init__(self, cells):
        self.cells = cells  # [(ref, raw_value)]


def _col_to_idx(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _idx_to_col(n):
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _cell_ref(letters, digits):
    return f"{letters.upper()}{int(digits)}"


def _tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUM_RE.match(text, i)
            if not m:
                raise FormulaError("#ERROR!", f"无法识别的数字：{text[i:i + 8]}")
            tokens.append(("num", float(m.group(0))))
            i = m.end()
            continue
        if ch.isalpha() or ch == "$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$."):
                j += 1
            word = text[i:j]
            tokens.append(("word", word))
            i = j
            continue
        two = text[i:i + 2]
        if two in ("<=", ">=", "<>", "!="):
            tokens.append(("op", two))
            i += 2
            continue
        if ch in "+-*/%^(),:=<>":
            tokens.append(("op", "=" if ch == "=" else ch))
            i += 1
            continue
        raise FormulaError("#ERROR!", f"非法字符：{ch}")
    tokens.append(("eof", None))
    return tokens


class _Parser:
    """递归下降：比较 < 加减 < 乘除 < 幂 < 一元 < 原子。

    只认数字、单元格、区间、函数与运算符；任何标识符都必须命中函数白名单。
    """

    def __init__(self, tokens, get_cell):
        self.tokens = tokens
        self.pos = 0
        self.get_cell = get_cell
        self.deps = []
        self.depth = 0

    def cell(self, ref):
        self.deps.append(ref)
        return self.get_cell(ref)

    # ---- 词法辅助 ----
    def peek(self):
        return self.tokens[self.pos]

    def take(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, value):
        kind, val = self.take()
        if kind != "op" or val != value:
            raise FormulaError("#ERROR!", f"缺少 '{value}'")

    # ---- 语法 ----
    def parse(self):
        val = self.comparison()
        if self.peek()[0] != "eof":
            raise FormulaError("#ERROR!", f"多余内容：{self.peek()[1]}")
        return val

    def _enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("#ERROR!", "公式嵌套过深")

    def comparison(self):
        left = self.additive()
        while True:
            kind, val = self.peek()
            if kind != "op" or val not in ("=", "<>", "!=", "<", ">", "<=", ">="):
                return left
            self.take()
            right = self.additive()
            a, b = _num(left), _num(right)
            res = {
                "=": a == b, "<>": a != b, "!=": a != b,
                "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b,
            }[val]
            left = 1.0 if res else 0.0

    def additive(self):
        left = self.multiplicative()
        while True:
            kind, val = self.peek()
            if kind != "op" or val not in ("+", "-"):
                return left
            self.take()
            right = self.multiplicative()
            left = _num(left) + _num(right)

    def multiplicative(self):
        left = self.unary()
        while True:
            kind, val = self.peek()
            if kind != "op" or val not in ("*", "/", "%"):
                return left
            self.take()
            right = self.unary()
            a, b = _num(left), _num(right)
            if val == "*":
                left = a * b
            elif val == "/":
                if b == 0:
                    raise FormulaError("#DIV/0!", "除数为 0")
                left = a / b
            else:
                if b == 0:
                    raise FormulaError("#DIV/0!", "取模的除数为 0")
                left = a % b

    def unary(self):
        kind, val = self.peek()
        if kind == "op" and val in ("+", "-"):
            self.take()
            v = _num(self.unary())
            return -v if val == "-" else v
        return self.power()

    def power(self):
        left = self.atom()
        kind, val = self.peek()
        if kind == "op" and val == "^":
            self.take()
            right = _num(self.unary())
            try:
                left = _num(left) ** right
            except OverflowError:
                raise FormulaError("#NUM!", "幂运算结果过大")
        return left

    def atom(self):
        self._enter()
        try:
            kind, val = self.take()
            if kind == "num":
                return val
            if kind == "op" and val == "(":
                inner = self.comparison()
                self.expect(")")
                return inner
            if kind == "word":
                # 函数名后必须紧跟 '('
                if self.peek() == ("op", "("):
                    return self.call(val.upper())
                m = _CELL_RE.match(val)
                if not m:
                    raise FormulaError("#NAME?", f"未知名称：{val}")
                first = _cell_ref(m.group(1), m.group(2))
                if self.peek() == ("op", ":"):
                    self.take()
                    kind2, val2 = self.take()
                    m2 = _CELL_RE.match(val2) if kind2 == "word" else None
                    if not m2:
                        raise FormulaError("#REF!", "区间右端不是单元格")
                    return self.range(first, _cell_ref(m2.group(1), m2.group(2)))
                return self.cell(first)
            raise FormulaError("#ERROR!", "公式不完整")
        finally:
            self.depth -= 1

    def range(self, a, b):
        from_c, from_r = _split_ref(a)
        to_c, to_r = _split_ref(b)
        if from_c > to_c:
            from_c, to_c = to_c, from_c
        if from_r > to_r:
            from_r, to_r = to_r, from_r
        size = (to_c - from_c + 1) * (to_r - from_r + 1)
        if size > MAX_RANGE_CELLS:
            raise FormulaError("#REF!", f"区间过大（>{MAX_RANGE_CELLS} 格）")
        cells = []
        for c in range(from_c, to_c + 1):
            for r in range(from_r, to_r + 1):
                ref = f"{_idx_to_col(c)}{r}"
                cells.append((ref, self.cell(ref)))
        return RangeValue(cells)

    def call(self, name):
        self.expect("(")
        args = []
        if self.peek() != ("op", ")"):
            while True:
                args.append(self.comparison())
                if self.peek() == ("op", ","):
                    self.take()
                    continue
                break
        self.expect(")")
        return _apply(name, args)


def _split_ref(ref):
    m = _CELL_RE.match(ref)
    return _col_to_idx(m.group(1)), int(m.group(2))


def _num(v):
    if isinstance(v, RangeValue):
        raise FormulaError("#VALUE!", "区间不能直接参与运算")
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        raise FormulaError("#VALUE!", f"「{v}」不是数字")


def _flat(args):
    """把参数摊平成 (值列表, 是否全部为区间)。"""
    out = []
    for a in args:
        if isinstance(a, RangeValue):
            out.extend(v for _, v in a.cells)
        else:
            out.append(a)
    return out


def _numerics(args, skip_text=True):
    vals = []
    for v in _flat(args):
        if v is None or v == "":
            continue
        try:
            vals.append(_num(v))
        except FormulaError:
            if not skip_text:
                raise
    return vals


def _apply(name, args):
    if name in ("SUM", "AVG", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA"):
        if name == "COUNTA":
            return float(len([v for v in _flat(args) if v not in (None, "")]))
        vals = _numerics(args)
        if name == "SUM":
            return float(sum(vals))
        if name == "COUNT":
            return float(len(vals))
        if not vals:
            if name in ("AVG", "AVERAGE"):
                raise FormulaError("#DIV/0!", "AVG 没有可计算的数值")
            return 0.0
        if name in ("AVG", "AVERAGE"):
            return sum(vals) / len(vals)
        return float(min(vals) if name == "MIN" else max(vals))
    if name == "ROUND":
        if not args:
            raise FormulaError("#VALUE!", "ROUND 需要至少 1 个参数")
        x = _num(args[0])
        digits = int(_num(args[1])) if len(args) > 1 else 0
        digits = max(-6, min(digits, 10))
        try:
            q = Decimal(1).scaleb(-digits)
            return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError):
            raise FormulaError("#NUM!", "ROUND 参数非法")
    if name == "ABS":
        if len(args) != 1:
            raise FormulaError("#VALUE!", "ABS 只接受 1 个参数")
        return abs(_num(args[0]))
    if name == "IF":
        if len(args) < 2:
            raise FormulaError("#VALUE!", "IF 至少需要 2 个参数")
        cond = _num(args[0])
        return args[1] if cond else (args[2] if len(args) > 2 else 0.0)
    raise FormulaError("#NAME?", f"不支持的函数：{name}")


def _sheet_cells(request):
    cells = {}
    raw = p(request, "cells")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("cells 必须是 JSON 对象")
    if isinstance(raw, dict):
        for k, v in raw.items():
            m = _CELL_RE.match(str(k).strip())
            if not m:
                raise ValueError(f"非法单元格：{k}")
            cells[_cell_ref(m.group(1), m.group(2))] = v
    data = p(request, "data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            raise ValueError("data 必须是二维数组")
    if isinstance(data, list):
        if len(data) > 5000:
            raise ValueError("data 最多 5000 行")
        for ri, row in enumerate(data, start=1):
            if not isinstance(row, list):
                raise ValueError("data 每行必须是数组")
            for ci, val in enumerate(row, start=1):
                cells[_idx_to_col(ci) + str(ri)] = val
    if not cells:
        raise ValueError("cells / data 至少提供一项")
    return cells


def _display(value):
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


@endpoint()
def formula_eval(request):
    """计算单条公式。

    入参：formula（可带前导 =）+ cells（{"A1": 1}）或 data（[[1,2],[3,4]]）。
    返回 value/display/deps/errors；公式错误以 #DIV/0! 等 Excel 口径返回，不抛 400。
    """
    formula = req_str(request, "formula").strip()
    if formula.startswith("="):
        formula = formula[1:]
    if not formula:
        raise ValueError("公式不能为空")
    if len(formula) > MAX_FORMULA_LEN:
        raise ValueError(f"公式不能超过 {MAX_FORMULA_LEN} 字符")
    sheet = _sheet_cells(request)
    parser = _Parser(_tokenize(formula), lambda ref: sheet.get(ref))
    try:
        value = parser.parse()
        if isinstance(value, RangeValue):
            raise FormulaError("#VALUE!", "公式结果不能是区间")
        return ok({"formula": formula, "value": value, "display": _display(value),
                   "deps": sorted(set(parser.deps)), "errors": []})
    except FormulaError as exc:
        return ok({"formula": formula, "value": None, "display": exc.code,
                   "deps": sorted(set(parser.deps)),
                   "errors": [{"code": exc.code, "message": exc.message}]})


# =====================================================================
# F47 演示文稿大纲
# =====================================================================

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(.*)$")
MAX_SLIDES = 30
MAX_BULLETS = 6


def _strip_inline(text):
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_>#]", "", text)
    return text.strip()


def _rules_outline(markdown, title):
    deck_title = title or ""
    slides = []
    current = None
    for line in markdown.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        m = _HEADING_RE.match(s)
        if m:
            level, text = len(m.group(1)), _strip_inline(m.group(2))
            if not text:
                continue
            if level == 1 and not slides and not deck_title:
                deck_title = text
                continue
            if level <= 4:
                current = {"title": text, "bullets": [], "level": level}
                slides.append(current)
                continue
        m = _LIST_RE.match(s)
        if m:
            text = _strip_inline(m.group(1))
            if not text:
                continue
            if current is None:
                current = {"title": "概述", "bullets": [], "level": 1}
                slides.append(current)
            if len(current["bullets"]) < MAX_BULLETS:
                current["bullets"].append(text[:200])
            continue
        text = _strip_inline(s)
        if not text:
            continue
        if current is None:
            current = {"title": "概述", "bullets": [], "level": 1}
            slides.append(current)
        if len(text) <= 160 and len(current["bullets"]) < MAX_BULLETS:
            current["bullets"].append(text)
    if not slides:
        sentences = [t.strip() for t in re.split(r"[。！？.!?\n]", markdown) if t.strip()]
        bullets = [t[:200] for t in sentences[:MAX_BULLETS]]
        slides = [{"title": deck_title or "要点", "bullets": bullets, "level": 1}]
    slides = slides[:MAX_SLIDES]
    return deck_title or (slides[0]["title"] if slides else "演示大纲"), slides


def _outline_markdown(title, slides):
    lines = [f"# {title}", ""]
    for i, s in enumerate(slides, 1):
        lines.append(f"## {i}. {s['title']}")
        if s["bullets"]:
            lines.extend(f"- {b}" for b in s["bullets"])
        else:
            lines.append("- （要点待补充）")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


@endpoint()
def outline_from_note(request):
    """把笔记/文档转成 PPT 大纲：标题页 + 分节页 + 要点。

    有 LLM_API_KEY 时请求一次模型做要点凝练；失败或未配置时按规则输出。
    """
    note_id = p(request, "note_id")
    markdown = opt_str(request, "markdown") or opt_str(request, "content")
    title = opt_str(request, "title")
    source = "markdown"
    if note_id not in (None, "", 0, "0"):
        from notes.models import Note

        try:
            nid = int(note_id)
        except (TypeError, ValueError):
            raise ValueError("note_id 必须是整数")
        note = Note.objects.filter(pk=nid, is_deleted=False).filter(
            Q(owner=request.user) | Q(is_public=True)
        ).first()
        if not note:
            raise ValueError("笔记不存在或无权访问")
        markdown = note.content or ""
        title = title or note.title
        source = "note"
    if not markdown.strip():
        raise ValueError("笔记正文为空，无法生成大纲")

    deck_title, slides = _rules_outline(markdown, title)
    mode = "rule"
    if opt_bool(request, "use_llm", True):
        try:
            from assistant import llm

            if llm.is_configured():
                skeleton = {
                    "title": deck_title,
                    "slides": [{"title": s["title"], "bullets": s["bullets"]} for s in slides],
                }
                parsed, res = llm.chat_json([
                    {"role": "system", "content": "你是演示文稿结构编辑，只输出 JSON。"},
                    {"role": "user", "content": (
                        "把下面的大纲凝练成演示文稿：每页 3-5 条要点，每条不超过 30 字，"
                        "不要新增事实。输出 {\"title\": str, \"slides\": [{\"title\": str, \"bullets\": [str]}]}。\n"
                        + json.dumps(skeleton, ensure_ascii=False)
                    )},
                ], fallback=None, temperature=0.3, max_tokens=1200)
                if parsed and isinstance(parsed.get("slides"), list) and parsed["slides"]:
                    cleaned = []
                    for s in parsed["slides"][:MAX_SLIDES]:
                        if not isinstance(s, dict):
                            continue
                        bullets = [str(b)[:200] for b in (s.get("bullets") or []) if str(b).strip()]
                        cleaned.append({"title": str(s.get("title") or "未命名")[:120],
                                        "bullets": bullets[:MAX_BULLETS],
                                        "level": 1})
                    if cleaned:
                        slides = cleaned
                        deck_title = str(parsed.get("title") or deck_title)[:120]
                        mode = "llm"
                if not res.get("ok"):
                    mode = "rule"
        except Exception:  # noqa: BLE001 —— 生成属增强能力，失败必须降级
            mode = "rule"

    return ok({
        "title": deck_title,
        "slides": slides,
        "slide_count": len(slides),
        "bullet_count": sum(len(s["bullets"]) for s in slides),
        "markdown": _outline_markdown(deck_title, slides),
        "mode": mode,
        "source": source,
        "chars": len(markdown),
    })


DOC_FAMILY_COUNT = 3  # = 3（F45 批注 / F46 公式 / F47 大纲）
