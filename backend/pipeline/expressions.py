# -*- coding: utf-8 -*-
"""管道表达式引擎：自写 tokenizer + 递归下降解析器 + 安全求值器。

为什么不用 Python ``eval``：
1. 表达式来自用户配置，``eval`` 等价于把服务端进程交给配置作者，
   一个 ``__import__('os').system(...)`` 就能打穿整个平台；
2. ``eval`` 的报错是 Python 语法错，前端无法据此定位到字符位置；
3. 我们需要「缺失字段 = None 而不是 KeyError」的宽容语义，
   这与 Python 原生求值天然冲突。

因此这里实现一个最小但完整的表达式子集：
- 字面量：数字 / 字符串 / true / false / null / 数组；
- 路径：``user.name``、``items[0]``、``payload['id']``；
- 运算：``+ - * / // % **``、比较、``and or not``、``in``、``like``、``matches``；
- 函数：白名单内的 40 个纯函数（字符串、数值、日期、哈希、空值处理）。

解析结果是元组 AST，可被缓存复用；所有错误统一抛 ``ExprError``（ValueError
子类），接口层会自然映射成 400。
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import date, datetime, timezone as dt_timezone
from functools import lru_cache

MAX_EXPR_LEN = 2000
MAX_DEPTH = 40
MAX_TOKENS = 500
MAX_LIST_ITEMS = 200
MAX_REGEX_LEN = 300

# 数字后允许的运算符，避免 "1.2.3" 被拆成两个数字后静默通过
_NUM_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_NAME_START = re.compile(r"[^\W\d]", re.UNICODE)
_NAME_BODY = re.compile(r"\w", re.UNICODE)

_MULTI_OPS = ("==", "!=", "<>", "<=", ">=", "&&", "||", "**", "//")
_SINGLE_OPS = "+-*/%<>!=(),.[]{}:"

_KEYWORDS = {
    "and", "or", "not", "in", "is", "null", "true", "false", "like", "matches",
}

_TOKEN_CACHE: dict[str, list] = {}


class ExprError(ValueError):
    """表达式语法 / 求值错误（中文消息，带位置）。"""


class Token:
    """词法单元：kind ∈ num / str / name / op / eof。"""

    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind: str, value, pos: int):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"Token({self.kind},{self.value!r}@{self.pos})"


# ---------------------------------------------------------------------------
# 词法分析
# ---------------------------------------------------------------------------


def _read_string(text: str, start: int) -> tuple[str, int]:
    """读取单 / 双引号字符串，支持常见转义；未闭合直接报错。"""
    quote = text[start]
    buf: list[str] = []
    i = start + 1
    length = len(text)
    escapes = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}
    while i < length:
        ch = text[i]
        if ch == "\\":
            if i + 1 >= length:
                raise ExprError(f"字符串在第 {i + 1} 个字符处转义不完整")
            nxt = text[i + 1]
            buf.append(escapes.get(nxt, nxt))
            i += 2
            continue
        if ch == quote:
            return "".join(buf), i + 1
        buf.append(ch)
        i += 1
    raise ExprError("字符串缺少结束引号")


def tokenize(expr: str) -> list[Token]:
    """把表达式切成 token 列表。

    缓存按「表达式原文」做，ETL 同一条件会在几千行上反复求值，
    每次重新分词是纯浪费；缓存上限 512 条，避免配置爆炸撑内存。
    """
    if expr in _TOKEN_CACHE:
        return _TOKEN_CACHE[expr]
    if not isinstance(expr, str) or not expr.strip():
        raise ExprError("表达式不能为空")
    if len(expr) > MAX_EXPR_LEN:
        raise ExprError(f"表达式超过最大长度 {MAX_EXPR_LEN} 字符")

    tokens: list[Token] = []
    i, n = 0, len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "'\"":
            value, i = _read_string(expr, i)
            tokens.append(Token("str", value, i))
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and expr[i + 1].isdigit()):
            m = _NUM_RE.match(expr, i)
            if not m:
                raise ExprError(f"第 {i + 1} 个字符处的数字格式不正确")
            raw = m.group(0)
            value = float(raw) if any(c in raw for c in ".eE") else int(raw)
            tokens.append(Token("num", value, i))
            i = m.end()
            continue
        if _NAME_START.match(ch):
            j = i + 1
            while j < n and _NAME_BODY.match(expr[j]):
                j += 1
            word = expr[i:j]
            low = word.lower()
            if low in ("true", "false"):
                tokens.append(Token("num", low == "true", i))
            elif low == "null":
                tokens.append(Token("num", None, i))
            elif low in _KEYWORDS:
                tokens.append(Token("op", low, i))
            else:
                tokens.append(Token("name", word, i))
            i = j
            continue
        two = expr[i:i + 2]
        if two in _MULTI_OPS:
            tokens.append(Token("op", "!=" if two == "<>" else two, i))
            i += 2
            continue
        if ch in _SINGLE_OPS:
            if ch == "=":
                # 单个 = 当等号用：用户从 SQL 迁移过来时最常犯的错
                tokens.append(Token("op", "==", i))
            else:
                tokens.append(Token("op", ch, i))
            i += 1
            continue
        raise ExprError(f"不支持的字符 {ch!r}（第 {i + 1} 个）")

    if len(tokens) > MAX_TOKENS:
        raise ExprError(f"表达式 token 数超过上限 {MAX_TOKENS}")
    tokens.append(Token("eof", None, n))
    if len(_TOKEN_CACHE) > 512:
        _TOKEN_CACHE.clear()
    _TOKEN_CACHE[expr] = tokens
    return tokens


# ---------------------------------------------------------------------------
# 递归下降解析
# ---------------------------------------------------------------------------


class Parser:
    """按优先级分层的递归下降解析器。

    分层顺序（从低到高）：or → and → not → 比较 → 加减 → 乘除 → 一元 →
    幂 → 后缀（. / []）→ 原子。每层只处理本层运算符，天然避免歧义。
    """

    def __init__(self, expr: str):
        self.expr = expr
        self.tokens = tokenize(expr)
        self.pos = 0
        self.depth = 0

    # ---- token 基础操作 ----

    @property
    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def at_op(self, *ops: str) -> bool:
        tok = self.current
        return tok.kind == "op" and tok.value in ops

    def accept(self, *ops: str) -> bool:
        if self.at_op(*ops):
            self.advance()
            return True
        return False

    def expect(self, op: str, hint: str = "") -> None:
        if not self.accept(op):
            raise ExprError(hint or f"第 {self.current.pos + 1} 个字符处缺少 {op!r}")

    def _guard(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError(f"表达式嵌套超过 {MAX_DEPTH} 层")

    # ---- 各优先级 ----

    def parse(self):
        node = self.parse_or()
        if self.current.kind != "eof":
            raise ExprError(f"第 {self.current.pos + 1} 个字符处有多余内容")
        return node

    def parse_or(self):
        node = self.parse_and()
        while self.accept("or", "||"):
            node = ("or", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.accept("and", "&&"):
            node = ("and", node, self.parse_not())
        return node

    def parse_not(self):
        if self.accept("not", "!"):
            self._guard()
            node = ("not", self.parse_not())
            self.depth -= 1
            return node
        return self.parse_comparison()

    def parse_comparison(self):
        node = self.parse_add()
        tok = self.current
        if tok.kind == "op" and tok.value in ("==", "!=", "<", "<=", ">", ">="):
            op = self.advance().value
            return ("bin", op, node, self.parse_add())
        if tok.kind == "op" and tok.value in ("in", "like", "matches"):
            op = self.advance().value
            return ("bin", op, node, self.parse_add())
        if tok.kind == "op" and tok.value == "not":
            # not in 视为一个整体比较运算符
            save = self.pos
            self.advance()
            if self.accept("in"):
                return ("bin", "not_in", node, self.parse_add())
            self.pos = save
        if tok.kind == "op" and tok.value == "is":
            self.advance()
            negate = self.accept("not")
            if not self.accept("null"):
                raise ExprError("is 之后只支持 null / not null")
            return ("is_not_null" if negate else "is_null", node)
        return node

    def parse_add(self):
        node = self.parse_mul()
        while self.at_op("+", "-"):
            op = self.advance().value
            node = ("bin", op, node, self.parse_mul())
        return node

    def parse_mul(self):
        node = self.parse_unary()
        while self.at_op("*", "/", "//", "%"):
            op = self.advance().value
            node = ("bin", op, node, self.parse_unary())
        return node

    def parse_unary(self):
        if self.at_op("-", "+"):
            op = self.advance().value
            self._guard()
            node = ("unary", op, self.parse_unary())
            self.depth -= 1
            return node
        return self.parse_power()

    def parse_power(self):
        node = self.parse_postfix()
        if self.accept("**"):
            # 幂右结合：2 ** 3 ** 2 = 2 ** 9
            self._guard()
            node = ("bin", "**", node, self.parse_unary())
            self.depth -= 1
        return node

    def parse_postfix(self):
        node = self.parse_atom()
        while True:
            if self.accept("."):
                tok = self.current
                if tok.kind != "name":
                    raise ExprError("点号之后必须是字段名")
                self.advance()
                node = ("attr", node, tok.value)
                continue
            if self.accept("["):
                index = self.parse_or()
                self.expect("]", "字段下标缺少 ]")
                node = ("index", node, index)
                continue
            return node

    def parse_atom(self):
        tok = self.current
        if tok.kind in ("num", "str"):
            self.advance()
            return ("lit", tok.value)
        if tok.kind == "name":
            self.advance()
            if self.accept("("):
                return self.parse_call(tok.value)
            return ("name", tok.value)
        if tok.kind == "op" and tok.value == "(":
            self.advance()
            self._guard()
            node = self.parse_or()
            self.depth -= 1
            self.expect(")", "括号未闭合")
            return node
        if tok.kind == "op" and tok.value == "[":
            return self.parse_list()
        raise ExprError(f"第 {tok.pos + 1} 个字符处出现意外的 {tok.value!r}")

    def parse_call(self, name: str):
        args = []
        if not self.accept(")"):
            while True:
                args.append(self.parse_or())
                if self.accept(")"):
                    break
                self.expect(",", "函数参数之间必须是逗号")
                if len(args) > 12:
                    raise ExprError("函数参数不能超过 12 个")
        return ("call", name, args)

    def parse_list(self):
        self.expect("[")
        items = []
        if not self.accept("]"):
            while True:
                items.append(self.parse_or())
                if len(items) > MAX_LIST_ITEMS:
                    raise ExprError(f"数组字面量不能超过 {MAX_LIST_ITEMS} 项")
                if self.accept("]"):
                    break
                self.expect(",", "数组元素之间必须是逗号")
        return ("list", items)


@lru_cache(maxsize=512)
def parse_expression(expr: str):
    """解析并缓存 AST；纯函数，可安全跨请求复用。"""
    if not isinstance(expr, str):
        raise ExprError("表达式必须是字符串")
    if len(expr) > MAX_EXPR_LEN:
        raise ExprError(f"表达式超过最大长度 {MAX_EXPR_LEN} 字符")
    return Parser(expr).parse()


# ---------------------------------------------------------------------------
# 函数库（白名单）
# ---------------------------------------------------------------------------


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _as_number(value, func: str = "to_num"):
    """宽松转数字；不可转返回 None（表达式中按「空值」处理）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip().replace(",", "")
        if text == "":
            return None
        num = float(text)
        return int(num) if num.is_integer() and "." not in text else num
    except (TypeError, ValueError):
        return None


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on", "是")


def _as_datetime(value):
    """解析常见日期时间写法；失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)):
        # 秒级时间戳；毫秒级自动降级
        ts = float(value)
        if ts > 1e11:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=dt_timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            if fmt is None:
                return datetime.fromisoformat(text)
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _now():
    return datetime.now(dt_timezone.utc)


def _split_args(args, name: str, minimum: int, maximum: int | None = None):
    if len(args) < minimum or (maximum is not None and len(args) > maximum):
        upper = f"{minimum}" if maximum == minimum else f"{minimum}~{maximum or '∞'}"
        raise ExprError(f"函数 {name} 需要 {upper} 个参数，实际 {len(args)} 个")
    return args


def _fn_lower(args, ctx):
    _split_args(args, "lower", 1, 1)
    return _as_text(args[0]).lower()


def _fn_upper(args, ctx):
    _split_args(args, "upper", 1, 1)
    return _as_text(args[0]).upper()


def _fn_trim(args, ctx):
    _split_args(args, "trim", 1, 2)
    chars = _as_text(args[1]) if len(args) > 1 else None
    return _as_text(args[0]).strip(chars)


def _fn_len(args, ctx):
    _split_args(args, "len", 1, 1)
    value = args[0]
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return len(_as_text(value))


def _fn_concat(args, ctx):
    _split_args(args, "concat", 1, 12)
    return "".join(_as_text(a) for a in args)


def _fn_substr(args, ctx):
    _split_args(args, "substr", 2, 3)
    text = _as_text(args[0])
    start = int(_as_number(args[1], "substr") or 0)
    length = int(_as_number(args[2], "substr") or 0) if len(args) > 2 else None
    # 兼容 SQL 的 1 基下标：0 与 1 都表示开头
    start = max(start - 1, 0) if start >= 1 else 0
    return text[start:] if length is None else text[start:start + length]


def _fn_replace(args, ctx):
    _split_args(args, "replace", 3, 3)
    return _as_text(args[0]).replace(_as_text(args[1]), _as_text(args[2]))


def _fn_split(args, ctx):
    _split_args(args, "split", 1, 2)
    sep = _as_text(args[1]) if len(args) > 1 else ","
    if sep == "":
        return list(_as_text(args[0]))
    return _as_text(args[0]).split(sep)


def _fn_join(args, ctx):
    _split_args(args, "join", 1, 2)
    seq = args[0] if isinstance(args[0], list) else [args[0]]
    sep = _as_text(args[1]) if len(args) > 1 else ","
    return sep.join(_as_text(v) for v in seq)


def _fn_contains(args, ctx):
    _split_args(args, "contains", 2, 2)
    if isinstance(args[0], (list, tuple, set, dict)):
        return args[1] in args[0]
    return _as_text(args[1]) in _as_text(args[0])


def _fn_startswith(args, ctx):
    _split_args(args, "startswith", 2, 2)
    return _as_text(args[0]).startswith(_as_text(args[1]))


def _fn_endswith(args, ctx):
    _split_args(args, "endswith", 2, 2)
    return _as_text(args[0]).endswith(_as_text(args[1]))


def _fn_abs(args, ctx):
    _split_args(args, "abs", 1, 1)
    num = _as_number(args[0], "abs")
    return None if num is None else abs(num)


def _fn_round(args, ctx):
    _split_args(args, "round", 1, 2)
    num = _as_number(args[0], "round")
    if num is None:
        return None
    digits = int(_as_number(args[1], "round") or 0) if len(args) > 1 else 0
    digits = max(-6, min(6, digits))
    return round(num, digits)


def _fn_floor(args, ctx):
    _split_args(args, "floor", 1, 1)
    num = _as_number(args[0], "floor")
    return None if num is None else math.floor(num)


def _fn_ceil(args, ctx):
    _split_args(args, "ceil", 1, 1)
    num = _as_number(args[0], "ceil")
    return None if num is None else math.ceil(num)


def _flat_numbers(args):
    out = []
    for arg in args:
        if isinstance(arg, list):
            out.extend(v for v in (_as_number(x) for x in arg) if v is not None)
        else:
            num = _as_number(arg)
            if num is not None:
                out.append(num)
    return out


def _fn_min(args, ctx):
    nums = _flat_numbers(args)
    return min(nums) if nums else None


def _fn_max(args, ctx):
    nums = _flat_numbers(args)
    return max(nums) if nums else None


def _fn_sum(args, ctx):
    return sum(_flat_numbers(args)) or 0


def _fn_avg(args, ctx):
    nums = _flat_numbers(args)
    return sum(nums) / len(nums) if nums else None


def _fn_coalesce(args, ctx):
    _split_args(args, "coalesce", 1, 12)
    for value in args:
        if value is not None and value != "":
            return value
    return None


def _fn_if(args, ctx):
    _split_args(args, "if", 2, 3)
    if _as_bool(args[0]):
        return args[1]
    return args[2] if len(args) > 2 else None


def _fn_cast(args, ctx):
    _split_args(args, "cast", 2, 2)
    return cast_value(args[0], _as_text(args[1]))


def _fn_to_str(args, ctx):
    _split_args(args, "to_str", 1, 1)
    return _as_text(args[0])


def _fn_to_num(args, ctx):
    _split_args(args, "to_num", 1, 1)
    return _as_number(args[0])


def _fn_to_int(args, ctx):
    _split_args(args, "to_int", 1, 1)
    num = _as_number(args[0])
    return None if num is None else int(num)


def _fn_to_float(args, ctx):
    _split_args(args, "to_float", 1, 1)
    num = _as_number(args[0])
    return None if num is None else float(num)


def _fn_to_bool(args, ctx):
    _split_args(args, "to_bool", 1, 1)
    return _as_bool(args[0])


def _fn_isnull(args, ctx):
    _split_args(args, "isnull", 1, 1)
    return args[0] is None or (isinstance(args[0], str) and args[0].strip() == "")


def _fn_notnull(args, ctx):
    _split_args(args, "notnull", 1, 1)
    return not _fn_isnull(args[:1], ctx)


def _fn_now(args, ctx):
    _split_args(args, "now", 0, 0)
    return _now().isoformat()


def _fn_today(args, ctx):
    _split_args(args, "today", 0, 0)
    return _now().date().isoformat()


def _fn_date_part(args, ctx):
    _split_args(args, "date_part", 2, 2)
    dt = _as_datetime(args[1])
    if dt is None:
        return None
    part = _as_text(args[0]).lower()
    mapping = {
        "year": dt.year, "month": dt.month, "day": dt.day,
        "hour": dt.hour, "minute": dt.minute, "second": dt.second,
        "weekday": dt.isoweekday(), "yearday": dt.timetuple().tm_yday,
    }
    if part not in mapping:
        raise ExprError("date_part 第一个参数只支持 year/month/day/hour/minute/second/weekday/yearday")
    return mapping[part]


def _fn_datediff(args, ctx):
    _split_args(args, "datediff", 2, 3)
    left, right = _as_datetime(args[0]), _as_datetime(args[1])
    if left is None or right is None:
        return None
    unit = _as_text(args[2]).lower() if len(args) > 2 else "day"
    seconds = (left - right).total_seconds()
    divisors = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
    if unit not in divisors:
        raise ExprError("datediff 第三个参数只支持 second/minute/hour/day")
    return seconds / divisors[unit]


def _fn_regex_match(args, ctx):
    _split_args(args, "regex_match", 2, 2)
    pattern = _as_text(args[0])
    if len(pattern) > MAX_REGEX_LEN:
        raise ExprError(f"正则长度不能超过 {MAX_REGEX_LEN}")
    try:
        return re.search(pattern, _as_text(args[1])) is not None
    except re.error as exc:
        raise ExprError(f"正则表达式不合法：{exc}")


def _fn_regex_extract(args, ctx):
    _split_args(args, "regex_extract", 2, 3)
    pattern = _as_text(args[0])
    if len(pattern) > MAX_REGEX_LEN:
        raise ExprError(f"正则长度不能超过 {MAX_REGEX_LEN}")
    group = int(_as_number(args[2]) or 0) if len(args) > 2 else 0
    try:
        m = re.search(pattern, _as_text(args[1]))
    except re.error as exc:
        raise ExprError(f"正则表达式不合法：{exc}")
    if not m:
        return None
    try:
        return m.group(group)
    except IndexError:
        return None


def _fn_md5(args, ctx):
    _split_args(args, "md5", 1, 1)
    return hashlib.md5(_as_text(args[0]).encode("utf-8")).hexdigest()


def _fn_sha256(args, ctx):
    _split_args(args, "sha256", 1, 1)
    return hashlib.sha256(_as_text(args[0]).encode("utf-8")).hexdigest()


def _fn_default(args, ctx):
    _split_args(args, "default", 2, 2)
    return args[0] if args[0] not in (None, "") else args[1]


def _fn_empty(args, ctx):
    _split_args(args, "empty", 1, 1)
    return _fn_isnull(args[:1], ctx)


FUNCTIONS = {
    "lower": _fn_lower,
    "upper": _fn_upper,
    "trim": _fn_trim,
    "len": _fn_len,
    "length": _fn_len,
    "concat": _fn_concat,
    "substr": _fn_substr,
    "substring": _fn_substr,
    "replace": _fn_replace,
    "split": _fn_split,
    "join": _fn_join,
    "contains": _fn_contains,
    "startswith": _fn_startswith,
    "endswith": _fn_endswith,
    "abs": _fn_abs,
    "round": _fn_round,
    "floor": _fn_floor,
    "ceil": _fn_ceil,
    "min": _fn_min,
    "max": _fn_max,
    "sum": _fn_sum,
    "avg": _fn_avg,
    "coalesce": _fn_coalesce,
    "if": _fn_if,
    "iff": _fn_if,
    "cast": _fn_cast,
    "to_str": _fn_to_str,
    "to_num": _fn_to_num,
    "to_int": _fn_to_int,
    "to_float": _fn_to_float,
    "to_bool": _fn_to_bool,
    "isnull": _fn_isnull,
    "notnull": _fn_notnull,
    "now": _fn_now,
    "today": _fn_today,
    "date_part": _fn_date_part,
    "datediff": _fn_datediff,
    "regex_match": _fn_regex_match,
    "regex_extract": _fn_regex_extract,
    "md5": _fn_md5,
    "sha256": _fn_sha256,
    "default": _fn_default,
    "empty": _fn_empty,
}

FUNCTION_CATALOG = [
    {"name": "lower / upper / trim", "args": "1~2", "description": "字符串大小写与去空白"},
    {"name": "len", "args": "1", "description": "字符串 / 数组 / 对象长度"},
    {"name": "concat", "args": "1~12", "description": "顺序拼接为字符串"},
    {"name": "substr", "args": "2~3", "description": "截取子串，兼容 SQL 1 基下标"},
    {"name": "replace", "args": "3", "description": "字符串替换"},
    {"name": "split / join", "args": "1~2", "description": "按分隔符拆分 / 合并"},
    {"name": "contains / startswith / endswith", "args": "2", "description": "包含与前后缀判断"},
    {"name": "abs / round / floor / ceil", "args": "1~2", "description": "数值取整与取绝对值"},
    {"name": "min / max / sum / avg", "args": "1~12", "description": "多值或数组的聚合"},
    {"name": "coalesce / default", "args": "2~12", "description": "取第一个非空值"},
    {"name": "if", "args": "2~3", "description": "条件表达式（if(cond, a, b)）"},
    {"name": "cast", "args": "2", "description": "类型转换，支持 int/float/bool/date/json"},
    {"name": "isnull / notnull / empty", "args": "1", "description": "空值判断"},
    {"name": "now / today", "args": "0", "description": "当前时间 / 日期（ISO 文本）"},
    {"name": "date_part / datediff", "args": "2~3", "description": "日期分量与差值"},
    {"name": "regex_match / regex_extract", "args": "2~3", "description": "正则匹配与分组提取"},
    {"name": "md5 / sha256", "args": "1", "description": "哈希摘要（脱敏 / 生成主键）"},
]

OPERATOR_CATALOG = [
    {"op": "+ - * / // % **", "description": "算术运算，数字字符串会自动转数值"},
    {"op": "== != < <= > >=", "description": "比较运算，空值与任何值比较均为假"},
    {"op": "and or not", "description": "逻辑运算，短路求值"},
    {"op": "in / not_in", "description": "集合成员判断，右值可为数组或字符串"},
    {"op": "like / matches", "description": "SQL 通配符（% _）与正则匹配"},
    {"op": "is null / is not null", "description": "空值判断"},
]


# ---------------------------------------------------------------------------
# 求值
# ---------------------------------------------------------------------------


def _lookup(name: str, ctx: dict):
    """字段查找：精确命中优先，其次大小写不敏感，最后返回 None。

    ETL 上游字段大小写经常不稳定（API 是小驼峰、库里是下划线），
    严格区分大小写会让同一份配置在不同数据源上行为不一致。
    """
    if name in ctx:
        return ctx[name]
    lower = name.lower()
    for key, value in ctx.items():
        if isinstance(key, str) and key.lower() == lower:
            return value
    return None


def _numeric_pair(left, right):
    """把两侧都尝试转成数值；只要一侧不是数值就返回 None。"""
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left, right
    lnum, rnum = _as_number(left), _as_number(right)
    if lnum is None or rnum is None:
        return None
    return lnum, rnum


def _compare(op: str, left, right) -> bool:
    if op in ("==", "!="):
        if left is None or right is None:
            equal = left is None and right is None
        else:
            pair = _numeric_pair(left, right)
            if pair is not None:
                equal = pair[0] == pair[1]
            elif isinstance(left, bool) or isinstance(right, bool):
                equal = _as_bool(left) == _as_bool(right)
            elif isinstance(left, str) and isinstance(right, str):
                equal = left == right
            else:
                equal = left == right
        return equal if op == "==" else not equal

    if left is None or right is None:
        # SQL 语义：NULL 参与大小比较为假（显式 isnull 才是判断方式）
        return False

    pair = _numeric_pair(left, right)
    if pair is not None:
        lval, rval = pair
    elif isinstance(left, str) and isinstance(right, str):
        lval, rval = left, right
    else:
        lval, rval = _as_text(left), _as_text(right)
    try:
        if op == "<":
            return lval < rval
        if op == "<=":
            return lval <= rval
        if op == ">":
            return lval > rval
        if op == ">=":
            return lval >= rval
    except TypeError:
        return False
    return False


def _like(value, pattern) -> bool:
    """SQL LIKE → 正则：% 任意长度、_ 单字符，其余字符转义。"""
    text = _as_text(value)
    pattern = _as_text(pattern)
    if len(pattern) > MAX_REGEX_LEN:
        raise ExprError(f"LIKE 模式过长（上限 {MAX_REGEX_LEN}）")
    buf = []
    for ch in pattern:
        if ch == "%":
            buf.append(".*")
        elif ch == "_":
            buf.append(".")
        else:
            buf.append(re.escape(ch))
    try:
        return re.fullmatch("".join(buf), text, flags=re.DOTALL | re.IGNORECASE) is not None
    except re.error as exc:
        raise ExprError(f"LIKE 模式不合法：{exc}")


def _binop(op: str, left, right):
    if op == "and":
        return _as_bool(left) and _as_bool(right)
    if op == "or":
        return _as_bool(left) or _as_bool(right)
    if op == "in":
        if isinstance(right, dict):
            return left in right
        if isinstance(right, (list, tuple, set)):
            return any(_compare("==", left, item) for item in right)
        return _as_text(left) in _as_text(right)
    if op == "not_in":
        return not _binop("in", left, right)
    if op == "like":
        return _like(left, right)
    if op == "matches":
        return _fn_regex_match([right, left], {})
    if op in ("==", "!=", "<", "<=", ">", ">="):
        return _compare(op, left, right)

    # 以下为算术：任一侧为空直接返回空，避免 0 与空混淆
    if op == "+" and (isinstance(left, str) or isinstance(right, str)):
        if left is None or right is None:
            return None
        return _as_text(left) + _as_text(right)
    if left is None or right is None:
        return None
    pair = _numeric_pair(left, right)
    if pair is None:
        return None
    lval, rval = pair
    try:
        if op == "+":
            return lval + rval
        if op == "-":
            return lval - rval
        if op == "*":
            return lval * rval
        if op == "/":
            return None if rval == 0 else lval / rval
        if op == "//":
            return None if rval == 0 else lval // rval
        if op == "%":
            return None if rval == 0 else lval % rval
        if op == "**":
            # 指数爆炸护栏：底数或指数过大时拒绝，防止一次配置拖死进程
            if abs(rval) > 64 or abs(lval) > 1e6:
                raise ExprError("幂运算参数过大")
            return lval ** rval
    except (OverflowError, ZeroDivisionError):
        return None
    return None


def _eval(node, ctx: dict):
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "name":
        return _lookup(node[1], ctx)
    if kind == "list":
        return [_eval(item, ctx) for item in node[1]]
    if kind == "attr":
        base = _eval(node[1], ctx)
        if isinstance(base, dict):
            return _lookup(node[2], base)
        return None
    if kind == "index":
        base = _eval(node[1], ctx)
        idx = _eval(node[2], ctx)
        if isinstance(base, dict):
            return base.get(_as_text(idx)) if idx is not None else None
        if isinstance(base, (list, tuple, str)):
            try:
                pos = int(_as_number(idx) or 0)
                return base[pos]
            except (IndexError, TypeError, ValueError):
                return None
        return None
    if kind == "call":
        name = node[1]
        func = FUNCTIONS.get(name)
        if func is None:
            raise ExprError(f"未知函数 {name}，可用函数见目录")
        args = [_eval(arg, ctx) for arg in node[2]]
        try:
            return func(args, ctx)
        except ExprError:
            raise
        except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            raise ExprError(f"函数 {name} 执行失败：{exc}")
    if kind == "unary":
        value = _eval(node[2], ctx)
        if value is None:
            return None
        num = _as_number(value)
        if num is None:
            return None
        return -num if node[1] == "-" else num
    if kind == "not":
        return not _as_bool(_eval(node[1], ctx))
    if kind == "is_null":
        value = _eval(node[1], ctx)
        return value is None or (isinstance(value, str) and value.strip() == "")
    if kind == "is_not_null":
        value = _eval(node[1], ctx)
        return not (value is None or (isinstance(value, str) and value.strip() == ""))
    if kind == "and":
        # 短路：左侧为假就不再求右侧，避免无意义的高成本函数
        if not _as_bool(_eval(node[1], ctx)):
            return False
        return _as_bool(_eval(node[2], ctx))
    if kind == "or":
        if _as_bool(_eval(node[1], ctx)):
            return True
        return _as_bool(_eval(node[2], ctx))
    if kind == "bin":
        return _binop(node[1], _eval(node[2], ctx), _eval(node[3], ctx))
    raise ExprError(f"无法识别的表达式节点 {kind}")


def evaluate_expression(expr: str, context: dict | None = None):
    """求值入口：返回 Python 原生值（None 表示空 / 缺失）。"""
    if not expr or not str(expr).strip():
        return None
    ast = parse_expression(str(expr))
    return _eval(ast, context or {})


def evaluate_condition(expr: str, row: dict | None = None) -> bool:
    """条件求值：空表达式视为「全部通过」，其余按布尔语义解释。"""
    if not expr or not str(expr).strip():
        return True
    return _as_bool(evaluate_expression(expr, row or {}))


def _collect(node, names: set, funcs: set) -> None:
    """遍历 AST 收集字段名与函数名（用于校验提示）。"""
    if not isinstance(node, tuple):
        return
    kind = node[0]
    if kind == "name":
        names.add(node[1])
    elif kind == "call":
        funcs.add(node[1])
        for arg in node[2]:
            _collect(arg, names, funcs)
    elif kind == "list":
        for item in node[1]:
            _collect(item, names, funcs)
    elif kind in ("attr", "index", "unary", "not", "is_null", "is_not_null"):
        for part in node[1:]:
            _collect(part, names, funcs)
    elif kind in ("bin", "and", "or"):
        _collect(node[2], names, funcs)
        _collect(node[3], names, funcs)


def validate_expression(expr: str) -> dict:
    """校验表达式：语法 + 函数白名单 + 字段引用，返回结构化报告。"""
    result = {"expression": expr, "valid": True, "error": "", "fields": [], "functions": []}
    if not expr or not str(expr).strip():
        result["error"] = "表达式不能为空"
        result["valid"] = False
        return result
    try:
        ast = parse_expression(str(expr))
    except ExprError as exc:
        result["valid"] = False
        result["error"] = str(exc)
        return result
    names: set[str] = set()
    funcs: set[str] = set()
    _collect(ast, names, funcs)
    unknown = sorted(f for f in funcs if f not in FUNCTIONS)
    result["fields"] = sorted(names)
    result["functions"] = sorted(funcs)
    if unknown:
        result["valid"] = False
        result["error"] = f"未知函数：{', '.join(unknown)}"
    return result


def function_catalog() -> list[dict]:
    """函数目录：供目录接口与前端表达式编辑器补全。"""
    return [dict(item) for item in FUNCTION_CATALOG]


def operator_catalog() -> list[dict]:
    """运算符目录。"""
    return [dict(item) for item in OPERATOR_CATALOG]


# ---------------------------------------------------------------------------
# 类型转换（映射 / 转换节点共用）
# ---------------------------------------------------------------------------

CAST_TYPES = ("string", "int", "integer", "float", "number", "decimal",
              "bool", "boolean", "date", "datetime", "json")


def cast_value(value, cast: str, default=None):
    """把值转成目标类型；空值原样返回 None（由默认值另行兜底）。

    转换失败返回 ``default`` 而不是抛错：ETL 里一行脏数据不应该
    让整批运行失败，失败率交给质量规则统计。
    """
    if cast is None or cast == "":
        return value
    cast = str(cast).strip().lower()
    if cast not in CAST_TYPES:
        raise ExprError(f"不支持的目标类型 {cast}")
    if value is None:
        return None
    try:
        if cast == "string":
            return _as_text(value)
        if cast in ("int", "integer"):
            num = _as_number(value)
            return None if num is None else int(num)
        if cast in ("float", "number", "decimal"):
            num = _as_number(value)
            return None if num is None else float(num)
        if cast in ("bool", "boolean"):
            return _as_bool(value)
        if cast == "date":
            dt = _as_datetime(value)
            return dt.date().isoformat() if dt else default
        if cast == "datetime":
            dt = _as_datetime(value)
            return dt.isoformat() if dt else default
        if cast == "json":
            import json

            if isinstance(value, (dict, list)):
                return value
            return json.loads(_as_text(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return default


def parse_datetime_value(value):
    """对外暴露的日期解析（质量规则的 freshness 复用同一口径）。"""
    return _as_datetime(value)


def to_number(value):
    """对外暴露的宽松数值转换。"""
    return _as_number(value)


def to_bool(value) -> bool:
    """对外暴露的布尔转换。"""
    return _as_bool(value)


def to_text(value) -> str:
    """对外暴露的文本转换（None → 空串）。"""
    return _as_text(value)
