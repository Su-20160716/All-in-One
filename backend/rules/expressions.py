# -*- coding: utf-8 -*-
"""规则表达式引擎：自写 tokenizer + 递归下降解析器 + 白名单求值器。

为什么不复用 Python 的 eval / ast.literal_eval：
- eval 一旦执行用户输入就等于把服务器交给调用方，即便沙箱化也难以收口；
- literal_eval 只能解析字面量，无法表达 `amount > 100 and user.dept == 'sales'`；
- 业务表达式语言本身很小（比较 / 逻辑 / 算术 / in / between / like / is null），
  自写解析器可以把「允许什么」写死成白名单，同时在解析阶段就拒绝危险形态。

安全边界（全部在解析期生效，不依赖运行时兜底）：
1. 表达式总长度、token 数、AST 节点数、嵌套层数、变量数、字符串长度均有上限；
2. 标识符路径禁止任何以下划线开头的段（`_x` / `__class__`），杜绝属性穿透；
3. 只允许 10 个内置函数，函数名在解析期校验；
4. `matches` 的正则长度与输入长度设限，避免灾难性回溯拖垮线程；
5. 字段解析只沿 dict / list 下标行走，绝不 getattr 任意对象。

求值失败时抛 ExprError（中文消息），由服务层转成评估失败状态，不向调用方
泄漏 Python 栈信息。
"""
import json
import math
import re
from datetime import date, datetime
from functools import lru_cache

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

# ---------------------------------------------------------------------------
# 上限常量：视图层校验与解析器共用，改一处即可整体收紧
# ---------------------------------------------------------------------------

MAX_EXPR_LEN = 4000
MAX_DEPTH = 32
MAX_VARIABLES = 100
MAX_STEPS = 500
MAX_TOKENS = 2000
MAX_STRING_LEN = 2000
MAX_PATTERN_LEN = 500
MAX_MATCH_INPUT = 20000
MAX_NODES = 1000

FUNCTION_SPECS = {
    "len": (1, 1),
    "abs": (1, 1),
    "min": (1, 20),
    "max": (1, 20),
    "round": (1, 2),
    "lower": (1, 1),
    "upper": (1, 1),
    "coalesce": (1, 20),
    "now": (0, 0),
    "days_between": (2, 2),
}

FUNCTION_DESCRIPTIONS = {
    "len": "长度：字符串/数组/对象长度，空值为 0",
    "abs": "绝对值",
    "min": "最小值（可多参或单数组）",
    "max": "最大值（可多参或单数组）",
    "round": "四舍五入，第二参为小数位",
    "lower": "转小写",
    "upper": "转大写",
    "coalesce": "返回第一个非空参数",
    "now": "当前时间 ISO 字符串",
    "days_between": "两个日期相差天数（后者减前者）",
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_][A-Za-z0-9_.]*)\s*\}\}")


class ExprError(ValueError):
    """表达式语法或求值错误；消息为中文，可直接返回给调用方。"""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class Token:
    """词法单元：kind ∈ num/str/ident/kw/op/lparen/rparen/lbracket/rbracket/comma/eof。"""

    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):  # pragma: no cover - 调试辅助
        return f"Token({self.kind!r},{self.value!r}@{self.pos})"


_KW_WORDS = ("and", "or", "not", "in", "between", "like", "matches", "is")


def _scan_string(text, index):
    """读取带引号字符串，支持 \\n \\t \\" \\' \\uXXXX 等常用转义。"""
    quote = text[index]
    i = index + 1
    out = []
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == quote:
            return "".join(out), i + 1
        if ch == "\\":
            i += 1
            if i >= n:
                raise ExprError("字符串转义不完整")
            esc = text[i]
            if esc == "u":
                hex_part = text[i + 1:i + 5]
                if len(hex_part) != 4:
                    raise ExprError("\\u 转义需要 4 位十六进制")
                try:
                    out.append(chr(int(hex_part, 16)))
                except ValueError:
                    raise ExprError(f"非法 \\u 转义: {hex_part}")
                i += 5
                continue
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b",
                        "f": "\f", "\\": "\\", "'": "'", '"': '"'}.get(esc, esc))
            i += 1
            continue
        out.append(ch)
        if len(out) > MAX_STRING_LEN:
            raise ExprError(f"字符串字面量超过上限 {MAX_STRING_LEN} 字符")
        i += 1
    raise ExprError("字符串缺少结束引号")


def _scan_ident(text, index):
    """读取标识符/字段路径，路径段以点分隔，段内允许数字（数组下标）。"""
    i = index
    n = len(text)
    while i < n and (text[i].isalnum() or text[i] == "_"):
        i += 1
    while i < n and text[i] == ".":
        j = i + 1
        if j >= n or not (text[j].isalnum() or text[j] == "_"):
            raise ExprError(f"字段路径在位置 {i} 处缺少段名")
        i = j
        while i < n and (text[i].isalnum() or text[i] == "_"):
            i += 1
    return text[index:i], i


def tokenize(text):
    """把表达式切成 token 列表；任何非法字符立即报错并给出行内位置。"""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()[],":
            kind = {"(": "lparen", ")": "rparen", "[": "lbracket",
                    "]": "rbracket", ",": "comma"}[ch]
            tokens.append(Token(kind, ch, i))
            i += 1
            continue
        if ch in "'\"":
            value, i = _scan_string(text, i)
            tokens.append(Token("str", value, i - len(value) - 2))
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUMBER_RE.match(text, i)
            if not m:
                raise ExprError(f"非法数字（位置 {i}）")
            raw = m.group(0)
            try:
                num = float(raw) if ("." in raw or "e" in raw.lower()) else int(raw)
            except ValueError:
                raise ExprError(f"非法数字: {raw}")
            tokens.append(Token("num", num, i))
            i = m.end()
            continue
        if ch.isalpha() or ch == "_":
            ident, i = _scan_ident(text, i)
            low = ident.lower()
            if low in ("true", "false"):
                tokens.append(Token("kw", low, i - len(ident)))
            elif low == "null":
                tokens.append(Token("kw", "null", i - len(ident)))
            elif low in _KW_WORDS:
                tokens.append(Token("kw", low, i - len(ident)))
            else:
                tokens.append(Token("ident", ident, i - len(ident)))
            continue
        two = text[i:i + 2]
        if two in ("==", "!=", ">=", "<=", "<>", "&&", "||"):
            mapping = {"==": ("op", "=="), "!=": ("op", "!="), ">=": ("op", ">="),
                       "<=": ("op", "<="), "<>": ("op", "!="),
                       "&&": ("kw", "and"), "||": ("kw", "or")}
            kind, value = mapping[two]
            tokens.append(Token(kind, value, i))
            i += 2
            continue
        if ch in "><+-*/%":
            tokens.append(Token("op", ch, i))
            i += 1
            continue
        if ch == "=":
            tokens.append(Token("op", "==", i))
            i += 1
            continue
        if ch == "!":
            tokens.append(Token("kw", "not", i))
            i += 1
            continue
        raise ExprError(f"表达式包含非法字符 {ch!r}（位置 {i}）")
        # 不会到达
        break
    if len(tokens) > MAX_TOKENS:
        raise ExprError(f"表达式 token 数超过上限 {MAX_TOKENS}")
    tokens.append(Token("eof", None, n))
    return tokens


# ---------------------------------------------------------------------------
# 取值与类型比较
# ---------------------------------------------------------------------------


def _jsonable(value):
    """把求值结果转成可 JSON 序列化的类型，供 trace / 决策结果持久化。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _as_number(value):
    """取数值：bool 不算数字（True == 1 在 Python 里成立，但业务上不应成立）。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _equal(a, b):
    """宽松相等：None 只等于 None；bool 与数字不互相穿透；数字按数值比较。"""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    na, nb = _as_number(a), _as_number(b)
    if na is not None and nb is not None:
        return na == nb
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        try:
            return list(a) == list(b)
        except TypeError:
            return False
    return a == b


def _order_ok(op, a, b):
    """有序比较：类型不兼容返回 False 而不是抛错，保证一条坏数据不中断整批评估。"""
    if a is None or b is None:
        return False
    na, nb = _as_number(a), _as_number(b)
    if na is not None and nb is not None:
        left, right = na, nb
    elif isinstance(a, str) and isinstance(b, str):
        left, right = a, b
    elif isinstance(a, (datetime, date)) and isinstance(b, (datetime, date)):
        left, right = a, b
    else:
        return False
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    return False


def _like_regex(pattern):
    """把 SQL LIKE 模式翻译成正则：% → .*，_ → .，其余转义。"""
    if not isinstance(pattern, str):
        return None
    out = ["^"]
    for ch in pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    out.append("$")
    return "".join(out)


def _parse_date_value(value):
    """把字符串/日期转成 date；失败返回 None（days_between 用）。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        dt = parse_datetime(text)
        if dt is not None:
            return dt.date()
        return parse_date(text)
    return None


# ---------------------------------------------------------------------------
# 内置函数（白名单）
# ---------------------------------------------------------------------------


def _flatten_args(args):
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        return list(args[0])
    return list(args)


def _fn_len(args):
    value = args[0]
    if value is None:
        return 0
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value)
    return len(str(value))


def _fn_abs(args):
    num = _as_number(args[0])
    if num is None:
        raise ExprError("abs 需要数字参数")
    return abs(num)


def _fn_min(args):
    values = [v for v in _flatten_args(args) if v is not None]
    if not values:
        return None
    numbers = [_as_number(v) for v in values]
    if all(n is not None for n in numbers):
        return min(numbers)
    return min(str(v) for v in values)


def _fn_max(args):
    values = [v for v in _flatten_args(args) if v is not None]
    if not values:
        return None
    numbers = [_as_number(v) for v in values]
    if all(n is not None for n in numbers):
        return max(numbers)
    return max(str(v) for v in values)


def _fn_round(args):
    num = _as_number(args[0])
    if num is None:
        raise ExprError("round 需要数字参数")
    digits = 0
    if len(args) == 2:
        d = _as_number(args[1])
        if d is None:
            raise ExprError("round 的第二个参数必须是整数")
        digits = int(d)
        if digits < 0 or digits > 10:
            raise ExprError("round 的小数位必须在 0~10 之间")
    return round(num, digits)


def _fn_lower(args):
    value = args[0]
    return "" if value is None else str(value).lower()


def _fn_upper(args):
    value = args[0]
    return "" if value is None else str(value).upper()


def _fn_coalesce(args):
    for value in args:
        if value is not None and value != "":
            return value
    return None


def _fn_now(args):
    return timezone.now().isoformat()


def _fn_days_between(args):
    left = _parse_date_value(args[0])
    right = _parse_date_value(args[1])
    if left is None or right is None:
        raise ExprError("days_between 需要两个可解析的日期")
    return (right - left).days


_FUNCTIONS = {
    "len": _fn_len,
    "abs": _fn_abs,
    "min": _fn_min,
    "max": _fn_max,
    "round": _fn_round,
    "lower": _fn_lower,
    "upper": _fn_upper,
    "coalesce": _fn_coalesce,
    "now": _fn_now,
    "days_between": _fn_days_between,
}


# ---------------------------------------------------------------------------
# 求值上下文
# ---------------------------------------------------------------------------


class EvalContext:
    """一次求值的上下文：事实、变量、可选的逐节点追踪记录。

    steps 只保留前 MAX_STEPS 条：超长表达式的完整追踪对前端没有价值，
    反而会让 RuleEvaluation.trace 字段无限膨胀。
    """

    __slots__ = ("facts", "variables", "trace", "steps", "truncated")

    def __init__(self, facts=None, variables=None, trace=False):
        self.facts = facts if isinstance(facts, dict) else {}
        self.variables = variables if isinstance(variables, dict) else {}
        self.trace = bool(trace)
        self.steps = []
        self.truncated = False

    def record(self, node, value):
        if not self.trace:
            return
        if len(self.steps) >= MAX_STEPS:
            self.truncated = True
            return
        self.steps.append({
            "seq": len(self.steps) + 1,
            "kind": node.kind,
            "expr": node.describe(),
            "value": _jsonable(value),
            "bool": bool(value) if node.boolean else None,
        })


def validate_path(path):
    """校验字段路径：拒绝空段与下划线开头的段（防 `__class__` 属性穿透）。"""
    if not isinstance(path, str) or not path.strip():
        raise ExprError("字段路径不能为空")
    if len(path) > 200:
        raise ExprError("字段路径超过 200 字符")
    for part in path.split("."):
        if not part:
            raise ExprError(f"字段路径 {path} 含空段")
        if part.startswith("_"):
            raise ExprError(f"字段路径 {path} 不允许下划线开头的段")
        if "__" in part:
            raise ExprError(f"字段路径 {path} 不允许双下划线")
    return path


def resolve_path(path, facts, variables=None):
    """沿 dict/list 解析字段路径；路径不存在返回 None，绝不 getattr。"""
    validate_path(path)
    variables = variables or {}
    parts = path.split(".")
    if parts[0] == "facts":
        root = facts if isinstance(facts, dict) else {}
        parts = parts[1:]
    elif parts[0] == "vars":
        root = variables
        parts = parts[1:]
    elif path in variables:
        return variables[path]
    else:
        root = facts if isinstance(facts, dict) else {}
    for part in parts:
        if root is None:
            return None
        if isinstance(root, dict):
            root = root.get(part)
        elif isinstance(root, (list, tuple)):
            if not part.isdigit():
                return None
            index = int(part)
            root = root[index] if 0 <= index < len(root) else None
        else:
            return None
    return root


# ---------------------------------------------------------------------------
# AST 节点
# ---------------------------------------------------------------------------


class Node:
    """AST 基类：evaluate 负责求值，to_dict 提供结构树，describe 提供可读文本。"""

    kind = "node"
    boolean = False

    def evaluate(self, ctx):  # pragma: no cover - 抽象
        raise NotImplementedError

    def describe(self):
        return self.kind

    def to_dict(self):
        return {"type": self.kind}

    def children(self):
        return ()

    def walk(self):
        yield self
        for child in self.children():
            yield from child.walk()

    def signature(self):
        """规范化签名：用于冲突检测中的深比较（键排序后序列化）。"""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False,
                          default=str)


def literal_text(value):
    """把字面量渲染回表达式文本，供条件可视化拼装与测试断言使用。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "null"
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(literal_text(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


class LiteralNode(Node):
    kind = "literal"

    def __init__(self, value):
        self.value = value

    def evaluate(self, ctx):
        ctx.record(self, self.value)
        return self.value

    def describe(self):
        return literal_text(self.value)

    def to_dict(self):
        return {"type": "literal", "value": _jsonable(self.value)}


class VarNode(Node):
    kind = "var"

    def __init__(self, path):
        self.path = validate_path(path)

    def evaluate(self, ctx):
        value = resolve_path(self.path, ctx.facts, ctx.variables)
        ctx.record(self, value)
        return value

    def describe(self):
        return self.path

    def to_dict(self):
        return {"type": "var", "name": self.path}


class ListNode(Node):
    kind = "list"

    def __init__(self, items):
        self.items = items

    def evaluate(self, ctx):
        value = [item.evaluate(ctx) for item in self.items]
        ctx.record(self, value)
        return value

    def describe(self):
        return "[" + ", ".join(item.describe() for item in self.items) + "]"

    def to_dict(self):
        return {"type": "list", "items": [i.to_dict() for i in self.items]}

    def children(self):
        return tuple(self.items)


class FuncNode(Node):
    kind = "func"

    def __init__(self, name, args):
        self.name = name
        self.args = args

    def evaluate(self, ctx):
        values = [arg.evaluate(ctx) for arg in self.args]
        fn = _FUNCTIONS[self.name]
        try:
            result = fn(values)
        except ExprError:
            raise
        except (TypeError, ValueError, ArithmeticError) as e:
            raise ExprError(f"函数 {self.name} 求值失败: {e}")
        ctx.record(self, result)
        return result

    def describe(self):
        return f"{self.name}(" + ", ".join(a.describe() for a in self.args) + ")"

    def to_dict(self):
        return {"type": "func", "name": self.name,
                "args": [a.to_dict() for a in self.args]}

    def children(self):
        return tuple(self.args)


class UnaryNode(Node):
    kind = "unary"

    def __init__(self, op, operand):
        self.op = op
        self.operand = operand

    def evaluate(self, ctx):
        value = self.operand.evaluate(ctx)
        if self.op == "not":
            result = not bool(value)
        elif self.op == "-":
            num = _as_number(value)
            if num is None:
                raise ExprError("取负运算需要数字")
            result = -num
        else:
            num = _as_number(value)
            if num is None:
                raise ExprError("取正运算需要数字")
            result = num
        ctx.record(self, result)
        return result

    def describe(self):
        if self.op == "not":
            return f"(not {self.operand.describe()})"
        return f"({self.op}{self.operand.describe()})"

    def to_dict(self):
        return {"type": "unary", "op": self.op, "operand": self.operand.to_dict()}

    def children(self):
        return (self.operand,)


class ArithmeticNode(Node):
    kind = "arithmetic"

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def evaluate(self, ctx):
        left = self.left.evaluate(ctx)
        right = self.right.evaluate(ctx)
        na, nb = _as_number(left), _as_number(right)
        if self.op == "+" and isinstance(left, str) and isinstance(right, str):
            result = left + right
        elif na is None or nb is None:
            raise ExprError(f"算术运算 {self.op} 需要数字")
        elif self.op == "+":
            result = na + nb
        elif self.op == "-":
            result = na - nb
        elif self.op == "*":
            result = na * nb
        elif self.op == "/":
            if nb == 0:
                raise ExprError("除数为 0")
            result = na / nb
        elif self.op == "%":
            if nb == 0:
                raise ExprError("取模的除数为 0")
            result = na % nb
        else:
            raise ExprError(f"未知算术运算符 {self.op}")
        ctx.record(self, result)
        return result

    def describe(self):
        return f"({self.left.describe()} {self.op} {self.right.describe()})"

    def to_dict(self):
        return {"type": "arithmetic", "op": self.op,
                "left": self.left.to_dict(), "right": self.right.to_dict()}

    def children(self):
        return (self.left, self.right)


class LogicalNode(Node):
    kind = "logical"
    boolean = True

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def evaluate(self, ctx):
        left = bool(self.left.evaluate(ctx))
        if self.op == "and" and not left:
            ctx.record(self, False)
            return False
        if self.op == "or" and left:
            ctx.record(self, True)
            return True
        right = bool(self.right.evaluate(ctx))
        result = (left and right) if self.op == "and" else (left or right)
        ctx.record(self, result)
        return result

    def describe(self):
        return f"({self.left.describe()} {self.op} {self.right.describe()})"

    def to_dict(self):
        return {"type": "logical", "op": self.op,
                "left": self.left.to_dict(), "right": self.right.to_dict()}

    def children(self):
        return (self.left, self.right)


class CompareNode(Node):
    kind = "compare"
    boolean = True

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right

    def evaluate(self, ctx):
        left = self.left.evaluate(ctx)
        right = self.right.evaluate(ctx)
        if self.op == "==":
            result = _equal(left, right)
        elif self.op == "!=":
            result = not _equal(left, right)
        else:
            result = _order_ok(self.op, left, right)
        ctx.record(self, result)
        return result

    def describe(self):
        return f"({self.left.describe()} {self.op} {self.right.describe()})"

    def to_dict(self):
        return {"type": "compare", "op": self.op,
                "left": self.left.to_dict(), "right": self.right.to_dict()}

    def children(self):
        return (self.left, self.right)


class InNode(Node):
    kind = "in"
    boolean = True

    def __init__(self, left, right, negate=False):
        self.left = left
        self.right = right
        self.negate = negate

    def evaluate(self, ctx):
        left = self.left.evaluate(ctx)
        right = self.right.evaluate(ctx)
        found = _contains_value(left, right)
        result = (not found) if self.negate else found
        ctx.record(self, result)
        return result

    def describe(self):
        op = "not in" if self.negate else "in"
        return f"({self.left.describe()} {op} {self.right.describe()})"

    def to_dict(self):
        return {"type": "in", "negate": self.negate,
                "left": self.left.to_dict(), "right": self.right.to_dict()}

    def children(self):
        return (self.left, self.right)


class BetweenNode(Node):
    kind = "between"
    boolean = True

    def __init__(self, value, low, high, negate=False):
        self.value = value
        self.low = low
        self.high = high
        self.negate = negate

    def evaluate(self, ctx):
        value = self.value.evaluate(ctx)
        low = self.low.evaluate(ctx)
        high = self.high.evaluate(ctx)
        result = _order_ok(">=", value, low) and _order_ok("<=", value, high)
        # 边界为 None 时视为无法比较，直接不命中，避免把缺失事实算成区间内
        if value is None or low is None or high is None:
            result = False
        if self.negate:
            result = not result
        ctx.record(self, result)
        return result

    def describe(self):
        op = "not between" if self.negate else "between"
        return (f"({self.value.describe()} {op} {self.low.describe()} "
                f"and {self.high.describe()})")

    def to_dict(self):
        return {"type": "between", "negate": self.negate,
                "value": self.value.to_dict(), "low": self.low.to_dict(),
                "high": self.high.to_dict()}

    def children(self):
        return (self.value, self.low, self.high)


class IsNullNode(Node):
    kind = "is_null"
    boolean = True

    def __init__(self, operand, negate=False):
        self.operand = operand
        self.negate = negate

    def evaluate(self, ctx):
        value = self.operand.evaluate(ctx)
        result = value is None
        if self.negate:
            result = not result
        ctx.record(self, result)
        return result

    def describe(self):
        return f"({self.operand.describe()} is {'not ' if self.negate else ''}null)"

    def to_dict(self):
        return {"type": "is_null", "negate": self.negate,
                "operand": self.operand.to_dict()}

    def children(self):
        return (self.operand,)


class MatchNode(Node):
    kind = "match"
    boolean = True

    def __init__(self, mode, left, right, negate=False):
        self.mode = mode
        self.left = left
        self.right = right
        self.negate = negate

    def evaluate(self, ctx):
        left = self.left.evaluate(ctx)
        pattern = self.right.evaluate(ctx)
        result = self._match(left, pattern)
        if self.negate:
            result = not result
        ctx.record(self, result)
        return result

    def _match(self, left, pattern):
        if left is None or not isinstance(pattern, str):
            return False
        if self.mode == "matches":
            if len(pattern) > MAX_PATTERN_LEN:
                raise ExprError(f"正则长度超过上限 {MAX_PATTERN_LEN}")
            text = str(left)
            if len(text) > MAX_MATCH_INPUT:
                raise ExprError(f"正则匹配输入超过上限 {MAX_MATCH_INPUT} 字符")
            try:
                return re.fullmatch(pattern, text, flags=re.S | re.I) is not None
            except re.error as e:
                raise ExprError(f"正则表达式非法: {e}")
        regex = _like_regex(pattern)
        if regex is None:
            return False
        text = str(left)
        if len(text) > MAX_MATCH_INPUT:
            raise ExprError(f"模糊匹配输入超过上限 {MAX_MATCH_INPUT} 字符")
        return re.fullmatch(regex, text, flags=re.S | re.I) is not None

    def describe(self):
        op = self.mode
        if self.negate:
            op = "not " + op
        return f"({self.left.describe()} {op} {self.right.describe()})"

    def to_dict(self):
        return {"type": "match", "mode": self.mode, "negate": self.negate,
                "left": self.left.to_dict(), "right": self.right.to_dict()}

    def children(self):
        return (self.left, self.right)


def _contains_value(left, right):
    """in 语义：右侧字符串时做子串判断，集合/数组时逐项宽松相等比较。"""
    if right is None:
        return False
    if isinstance(right, str):
        return isinstance(left, str) and left in right
    if isinstance(right, dict):
        return isinstance(left, str) and left in right
    if isinstance(right, (list, tuple, set)):
        return any(_equal(left, item) for item in right)
    return _equal(left, right)


# ---------------------------------------------------------------------------
# 递归下降解析器
# ---------------------------------------------------------------------------


class Parser:
    """优先级（低 → 高）：or → and → not → 比较 → 加减 → 乘除 → 一元 → 原子。"""

    def __init__(self, tokens, text):
        self.tokens = tokens
        self.text = text
        self.index = 0
        self.depth = 0
        self.node_count = 0
        self.variables = set()
        self.functions = set()

    # ---- token 游标 ----

    def peek(self, offset=0):
        pos = self.index + offset
        if pos >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[pos]

    def advance(self):
        token = self.tokens[self.index]
        if token.kind != "eof":
            self.index += 1
        return token

    def check_kw(self, *names):
        token = self.peek()
        return token.kind == "kw" and token.value in names

    def match_kw(self, *names):
        if self.check_kw(*names):
            return self.advance()
        return None

    def expect(self, kind, message, value=None):
        token = self.peek()
        if token.kind != kind or (value is not None and token.value != value):
            raise ExprError(f"{message}（位置 {token.pos}）")
        return self.advance()

    # ---- 节点工厂：统一做节点计数，防止超长表达式把内存打满 ----

    def make(self, node):
        self.node_count += 1
        if self.node_count > MAX_NODES:
            raise ExprError(f"表达式节点数超过上限 {MAX_NODES}")
        return node

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError(f"表达式嵌套超过上限 {MAX_DEPTH} 层")

    def leave(self):
        self.depth -= 1

    # ---- 语法入口 ----

    def parse(self):
        node = self.parse_or()
        token = self.peek()
        if token.kind != "eof":
            raise ExprError(f"表达式在位置 {token.pos} 存在多余内容")
        return node

    def parse_or(self):
        node = self.parse_and()
        while True:
            if not self.match_kw("or"):
                break
            right = self.parse_and()
            node = self.make(LogicalNode("or", node, right))
        return node

    def parse_and(self):
        node = self.parse_not()
        while True:
            if not self.match_kw("and"):
                break
            right = self.parse_not()
            node = self.make(LogicalNode("and", node, right))
        return node

    def parse_not(self):
        if self.match_kw("not"):
            self.enter()
            try:
                operand = self.parse_not()
            finally:
                self.leave()
            return self.make(UnaryNode("not", operand))
        return self.parse_comparison()

    def parse_comparison(self):
        node = self.parse_additive()
        while True:
            token = self.peek()
            if token.kind == "op" and token.value in ("==", "!=", ">", ">=", "<", "<="):
                op = self.advance().value
                right = self.parse_additive()
                node = self.make(CompareNode(op, node, right))
                continue
            if self.check_kw("is"):
                self.advance()
                negate = bool(self.match_kw("not"))
                if not self.match_kw("null"):
                    raise ExprError(f"is 之后必须是 null（位置 {self.peek().pos}）")
                node = self.make(IsNullNode(node, negate=negate))
                continue
            # not in / not like / not matches / not between：作为整体比较运算符
            if self.check_kw("not") and self.peek(1).kind == "kw" and \
                    self.peek(1).value in ("in", "like", "matches", "between"):
                self.advance()
                keyword = self.advance().value
                node = self._build_keyword(keyword, node, negate=True)
                continue
            if self.check_kw("in", "like", "matches", "between"):
                keyword = self.advance().value
                node = self._build_keyword(keyword, node, negate=False)
                continue
            break
        return node

    def _build_keyword(self, keyword, left, negate):
        if keyword == "between":
            low = self.parse_additive()
            if not self.match_kw("and"):
                raise ExprError(f"between 需要用 and 连接上下界（位置 {self.peek().pos}）")
            high = self.parse_additive()
            return self.make(BetweenNode(left, low, high, negate=negate))
        if keyword == "in":
            right = self.parse_in_rhs()
            return self.make(InNode(left, right, negate=negate))
        right = self.parse_additive()
        return self.make(MatchNode(keyword, left, right, negate=negate))

    def parse_in_rhs(self):
        """in 右侧：括号列表（推荐）或单个表达式（可为变量/字符串）。"""
        if self.peek().kind == "lparen":
            self.advance()
            self.enter()
            items = []
            try:
                if self.peek().kind != "rparen":
                    items.append(self.parse_or())
                    while self.peek().kind == "comma":
                        self.advance()
                        items.append(self.parse_or())
                self.expect("rparen", "in 列表缺少右括号")
            finally:
                self.leave()
            return self.make(ListNode(items))
        return self.parse_additive()

    def parse_additive(self):
        node = self.parse_multiplicative()
        while True:
            token = self.peek()
            if token.kind != "op" or token.value not in ("+", "-"):
                break
            op = self.advance().value
            right = self.parse_multiplicative()
            node = self.make(ArithmeticNode(op, node, right))
        return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while True:
            token = self.peek()
            if token.kind != "op" or token.value not in ("*", "/", "%"):
                break
            op = self.advance().value
            right = self.parse_unary()
            node = self.make(ArithmeticNode(op, node, right))
        return node

    def parse_unary(self):
        token = self.peek()
        if token.kind == "op" and token.value in ("+", "-"):
            op = self.advance().value
            self.enter()
            try:
                operand = self.parse_unary()
            finally:
                self.leave()
            return self.make(UnaryNode(op, operand))
        return self.parse_primary()

    def parse_primary(self):
        token = self.peek()
        if token.kind == "num":
            self.advance()
            return self.make(LiteralNode(token.value))
        if token.kind == "str":
            self.advance()
            return self.make(LiteralNode(token.value))
        if token.kind == "kw" and token.value in ("true", "false"):
            self.advance()
            return self.make(LiteralNode(token.value == "true"))
        if token.kind == "kw" and token.value == "null":
            self.advance()
            return self.make(LiteralNode(None))
        if token.kind == "ident":
            name = self.advance().value
            if self.peek().kind == "lparen":
                return self.parse_call(name)
            self.variables.add(name)
            return self.make(VarNode(name))
        if token.kind == "lparen":
            self.advance()
            self.enter()
            try:
                node = self.parse_or()
                self.expect("rparen", "表达式缺少右括号")
            finally:
                self.leave()
            return node
        if token.kind == "lbracket":
            self.advance()
            self.enter()
            items = []
            try:
                if self.peek().kind != "rbracket":
                    items.append(self.parse_or())
                    while self.peek().kind == "comma":
                        self.advance()
                        items.append(self.parse_or())
                self.expect("rbracket", "列表缺少右方括号")
            finally:
                self.leave()
            return self.make(ListNode(items))
        raise ExprError(f"表达式在位置 {token.pos} 缺少操作数")

    def parse_call(self, name):
        low = name.lower()
        if low not in FUNCTION_SPECS:
            raise ExprError(f"不支持的函数: {name}")
        self.expect("lparen", "函数调用缺少左括号")
        self.enter()
        args = []
        try:
            if self.peek().kind != "rparen":
                args.append(self.parse_or())
                while self.peek().kind == "comma":
                    self.advance()
                    args.append(self.parse_or())
            self.expect("rparen", "函数调用缺少右括号")
        finally:
            self.leave()
        low_args, high_args = FUNCTION_SPECS[low]
        if not (low_args <= len(args) <= high_args):
            raise ExprError(
                f"函数 {low} 需要 {low_args}~{high_args} 个参数（当前 {len(args)}）")
        self.functions.add(low)
        return self.make(FuncNode(low, args))


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


@lru_cache(maxsize=512)
def parse_expression(text):
    """解析表达式为 AST；同一表达式重复出现时走缓存（规则集热路径）。"""
    if not isinstance(text, str):
        raise ExprError("表达式必须是字符串")
    stripped = text.strip()
    if not stripped:
        raise ExprError("表达式不能为空")
    if len(stripped) > MAX_EXPR_LEN:
        raise ExprError(f"表达式长度超过上限 {MAX_EXPR_LEN} 字符")
    tokens = tokenize(stripped)
    parser = Parser(tokens, stripped)
    node = parser.parse()
    if len(parser.variables) > MAX_VARIABLES:
        raise ExprError(f"表达式变量数超过上限 {MAX_VARIABLES}")
    return node


def collect_usage(node):
    """收集表达式里出现的变量与函数，供校验与文档展示。"""
    variables, functions = set(), set()
    for item in node.walk():
        if isinstance(item, VarNode):
            variables.add(item.path)
        elif isinstance(item, FuncNode):
            functions.add(item.name)
    return sorted(variables), sorted(functions)


def ast_depth(node):
    depth = 0
    for item in node.walk():
        if not item.children():
            continue
        depth = max(depth, _node_depth(item))
    return depth


def _node_depth(node):
    if not node.children():
        return 1
    return 1 + max(_node_depth(child) for child in node.children())


def node_count(node):
    return sum(1 for _ in node.walk())


def validate_expression(text):
    """校验表达式并返回结构化报告（不执行求值）。"""
    report = {
        "valid": False,
        "error": "",
        "length": len(text) if isinstance(text, str) else 0,
        "variables": [],
        "functions": [],
        "depth": 0,
        "nodes": 0,
        "limits": {
            "max_length": MAX_EXPR_LEN,
            "max_depth": MAX_DEPTH,
            "max_variables": MAX_VARIABLES,
            "max_nodes": MAX_NODES,
        },
    }
    try:
        node = parse_expression(text)
    except ExprError as e:
        report["error"] = str(e)
        return report
    # 解析通过不等于安全：字段路径要到求值才解析，这里提前拒绝下划线段/双下划线，
    # 避免把 `__class__` 这类路径存进规则、直到线上求值才炸。
    for item in node.walk():
        if isinstance(item, VarNode):
            try:
                validate_path(item.path)
            except ExprError as e:
                report["error"] = str(e)
                return report
    variables, functions = collect_usage(node)
    report.update({
        "valid": True,
        "variables": variables,
        "functions": functions,
        "depth": _node_depth(node),
        "nodes": node_count(node),
    })
    return report


def evaluate_expression(text, facts, variables=None):
    """执行表达式，返回原始 Python 值；错误统一抛 ExprError。"""
    node = parse_expression(text)
    ctx = EvalContext(facts, variables)
    return node.evaluate(ctx)


def explain_expression(text, facts, variables=None):
    """执行表达式并返回「值 + 条件树 + 逐节点布尔值」，评估接口的 explain 来源。"""
    node = parse_expression(text)
    ctx = EvalContext(facts, variables, trace=True)
    value = node.evaluate(ctx)
    return {
        "value": _jsonable(value),
        "trace": {
            "expression": text,
            "steps": ctx.steps,
            "truncated": ctx.truncated,
            "tree": node.to_dict(),
        },
    }


def expression_result(text, facts, variables=None):
    """把表达式结果强制转布尔：规则命中判定统一口径。"""
    return bool(evaluate_expression(text, facts, variables))


# ---------------------------------------------------------------------------
# 条件可视化 → 表达式
# ---------------------------------------------------------------------------


_CONDITION_TEMPLATES = {
    "==": lambda f, v: f"({f} == {literal_text(v)})",
    "!=": lambda f, v: f"({f} != {literal_text(v)})",
    ">": lambda f, v: f"({f} > {literal_text(v)})",
    ">=": lambda f, v: f"({f} >= {literal_text(v)})",
    "<": lambda f, v: f"({f} < {literal_text(v)})",
    "<=": lambda f, v: f"({f} <= {literal_text(v)})",
    "is_null": lambda f, v: f"({f} is null)",
    "is_not_null": lambda f, v: f"({f} is not null)",
}


def condition_expression(field, operator, value, logic_group="and"):
    """把一行可视化条件翻译成表达式；操作符未知时抛错，避免静默错配。"""
    validate_path(field)
    field = field.strip()
    op = (operator or "==").strip()
    alias = {
        "eq": "==", "=": "==", "ne": "!=", "<>": "!=",
        "gt": ">", "gte": ">=", "ge": ">=",
        "lt": "<", "lte": "<=", "le": "<=",
        "notin": "not_in", "notcontains": "not_contains",
        "isnull": "is_null", "notnull": "is_not_null",
    }
    op = alias.get(op, op)
    if op in _CONDITION_TEMPLATES:
        return _CONDITION_TEMPLATES[op](field, value)
    if op in ("in", "not_in"):
        keyword = "not in" if op == "not_in" else "in"
        values = value if isinstance(value, (list, tuple)) else [value]
        if len(values) > 100:
            raise ExprError("in 条件最多 100 个取值")
        return f"({field} {keyword} {literal_text(list(values))})"
    if op in ("contains", "not_contains"):
        keyword = "not like" if op == "not_contains" else "like"
        if value is None:
            raise ExprError("包含条件必须有比较值")
        return f"({field} {keyword} {literal_text('%' + str(value) + '%')})"
    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ExprError("between 条件需要长度为 2 的数组")
        return f"({field} between {literal_text(value[0])} and {literal_text(value[1])})"
    if op in ("like", "matches"):
        return f"({field} {op} {literal_text(value)})"
    raise ExprError(f"不支持的条件操作符: {operator}")


def combine_conditions(items):
    """按每行的 logic_group 串起多行条件；空列表返回 'true'（恒命中）。

    每段都加括号：避免 and/or 混用时优先级把用户预期改掉。
    """
    parts = []
    for index, item in enumerate(items):
        text = condition_expression(
            item.get("field", ""), item.get("operator", "=="),
            item.get("value"), item.get("logic_group", "and"),
        )
        if index == 0:
            parts.append(text)
            continue
        group = (item.get("logic_group") or "and").lower()
        if group not in ("and", "or"):
            raise ExprError(f"逻辑组只能是 and/or（当前 {group}）")
        parts.append(f"{group} {text}")
    if not parts:
        return "true"
    return "(" + " ".join(parts) + ")"


def render_template(text, facts, variables=None):
    """渲染动作参数里的 {{path}} 占位符；失败保留原文，避免动作整体不可用。"""
    if not isinstance(text, str) or "{{" not in text:
        return text

    def repl(match):
        path = match.group(1)
        try:
            value = resolve_path(path, facts, variables)
        except ExprError:
            return match.group(0)
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(_jsonable(value), ensure_ascii=False)
        return str(value)

    return _TEMPLATE_RE.sub(repl, text)


def operator_catalog():
    """给前端目录的操作符说明（顺序固定，便于下拉框稳定渲染）。"""
    from rules.models import CONDITION_OPERATOR_LABELS

    return [
        {"value": op, "label": CONDITION_OPERATOR_LABELS.get(op, op)}
        for op in CONDITION_OPERATOR_LABELS
    ]


def function_catalog():
    """给前端目录的函数说明。"""
    return [
        {"name": name, "description": FUNCTION_DESCRIPTIONS.get(name, ""),
         "min_args": spec[0], "max_args": spec[1]}
        for name, spec in FUNCTION_SPECS.items()
    ]
