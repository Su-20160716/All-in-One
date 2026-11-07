# -*- coding: utf-8 -*-
"""公式求值器：自写 tokenizer + 递归下降解析，**绝不使用 eval**。

为什么要自己写
--------------
KPI 指标卡需要「同比 / 环比 / 占比 / 自定义四则运算」。如果用 ``eval``，
报表配置（用户可编辑）就等价于远程代码执行；ast.literal_eval 又不支持
四则运算。这里用极简文法把表达式编译成数值：

    expression  := comparison
    comparison  := additive (("=="|"!="|">="|"<="|">"|"<") additive)?
    additive    := multiplicative (("+"|"-") multiplicative)*
    multiplicative := unary (("*"|"/"|"%") unary)*
    unary       := ("+"|"-") unary | power
    power       := primary ("^" unary)?
    primary     := NUMBER | NAME | NAME "(" args ")" | "(" expression ")"

安全约束：表达式 ≤ 500 字符、token ≤ 500、嵌套深度 ≤ 32、
除数为 0 / 结果非有限数 / 未知变量 一律抛 ValueError（中文提示）。
"""
import math
import re

from reporting.compiler import _coerce_number

MAX_EXPR_LEN = 500
MAX_TOKENS = 500
MAX_DEPTH = 32

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
# 变量名允许中文（数据集别名可能是「销售额」）与点号（a.b）
NAME_RE = re.compile(r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_.\u4e00-\u9fff]*")

OPS = ("==", "!=", ">=", "<=", ">", "<", "+", "-", "*", "/", "%", "^", "(", ")", ",")

CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "true": 1.0,
    "false": 0.0,
}

# 函数白名单：名字 → (最少参数, 最多参数, 实现)
FUNCTIONS = {
    "abs": (1, 1, lambda a: abs(a)),
    "round": (1, 2, lambda a, n=0: round(a, int(n))),
    "floor": (1, 1, lambda a: math.floor(a)),
    "ceil": (1, 1, lambda a: math.ceil(a)),
    "sqrt": (1, 1, lambda a: math.sqrt(a)),
    "pow": (2, 2, lambda a, b: math.pow(a, b)),
    "min": (1, 8, lambda *a: min(a)),
    "max": (1, 8, lambda *a: max(a)),
    "coalesce": (1, 8, lambda *a: next((x for x in a if x is not None), 0.0)),
    "if": (3, 3, lambda cond, a, b: a if cond else b),
    "log": (1, 2, lambda a, base=math.e: math.log(a, base)),
    "exp": (1, 1, lambda a: math.exp(a)),
    "sign": (1, 1, lambda a: (a > 0) - (a < 0)),
    "safe_div": (2, 2, lambda a, b: (a / b) if b else 0.0),
    "percent": (1, 1, lambda a: a * 100.0),
}


class _Token:
    """极简 token：kind 取 num/name/op；value 是数值或字符串。"""

    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):  # pragma: no cover —— 排障用
        return f"{self.kind}:{self.value}@{self.pos}"


def tokenize(expr):
    """表达式 → token 列表；非法字符立刻报错（含位置，方便前端定位）。"""
    if not isinstance(expr, str):
        raise ValueError("公式必须是字符串")
    text = expr.strip()
    if not text:
        raise ValueError("公式不能为空")
    if len(text) > MAX_EXPR_LEN:
        raise ValueError(f"公式过长（上限 {MAX_EXPR_LEN} 字符）")
    tokens = []
    pos = 0
    while pos < len(text):
        ch = text[pos]
        if ch in " \t\r\n":
            pos += 1
            continue
        matched = False
        for op in OPS:
            if text.startswith(op, pos):
                tokens.append(_Token("op", op, pos))
                pos += len(op)
                matched = True
                break
        if matched:
            continue
        num = NUMBER_RE.match(text, pos)
        if num:
            tokens.append(_Token("num", float(num.group(0)), pos))
            pos = num.end()
            continue
        name = NAME_RE.match(text, pos)
        if name:
            tokens.append(_Token("name", name.group(0), pos))
            pos = name.end()
            continue
        raise ValueError(f"公式在位置 {pos} 处含非法字符：{ch!r}")
    if not tokens:
        raise ValueError("公式不能为空")
    if len(tokens) > MAX_TOKENS:
        raise ValueError(f"公式 token 过多（上限 {MAX_TOKENS}）")
    return tokens


class _Parser:
    """递归下降解析器：边解析边求值（不建 AST，省内存也够用）。"""

    def __init__(self, tokens, variables):
        self.tokens = tokens
        self.vars = variables
        self.pos = 0
        self.depth = 0

    # -- token 基础操作 --
    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self):
        tok = self.peek()
        if tok is None:
            raise ValueError("公式意外结束（可能缺少右括号）")
        self.pos += 1
        return tok

    def expect(self, op):
        tok = self.next()
        if tok.kind != "op" or tok.value != op:
            raise ValueError(f"公式在位置 {tok.pos} 处应为 {op!r}")
        return tok

    def accept(self, op):
        tok = self.peek()
        if tok is not None and tok.kind == "op" and tok.value == op:
            self.pos += 1
            return True
        return False

    def _enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ValueError(f"公式嵌套层级超过 {MAX_DEPTH}")

    def _leave(self):
        self.depth -= 1

    # -- 文法 --
    def parse(self):
        value = self.comparison()
        if self.peek() is not None:
            tok = self.peek()
            raise ValueError(f"公式在位置 {tok.pos} 处有多余内容")
        return value

    def comparison(self):
        self._enter()
        left = self.additive()
        tok = self.peek()
        if tok is not None and tok.kind == "op" and tok.value in ("==", "!=", ">=", "<=", ">", "<"):
            self.next()
            right = self.additive()
            left = _compare(tok.value, left, right)
        self._leave()
        return left

    def additive(self):
        self._enter()
        value = self.multiplicative()
        while True:
            tok = self.peek()
            if tok is None or tok.kind != "op" or tok.value not in ("+", "-"):
                break
            self.next()
            rhs = self.multiplicative()
            value = value + rhs if tok.value == "+" else value - rhs
        self._leave()
        return value

    def multiplicative(self):
        self._enter()
        value = self.unary()
        while True:
            tok = self.peek()
            if tok is None or tok.kind != "op" or tok.value not in ("*", "/", "%"):
                break
            self.next()
            rhs = self.unary()
            if tok.value == "*":
                value = value * rhs
            elif tok.value == "/":
                if rhs == 0:
                    raise ValueError("公式除数为 0")
                value = value / rhs
            else:
                if rhs == 0:
                    raise ValueError("公式取模的除数为 0")
                value = math.fmod(value, rhs)
        self._leave()
        return value

    def unary(self):
        self._enter()
        if self.accept("-"):
            value = -self.unary()
        elif self.accept("+"):
            value = self.unary()
        else:
            value = self.power()
        self._leave()
        return value

    def power(self):
        self._enter()
        base = self.primary()
        if self.accept("^"):
            exponent = self.unary()
            try:
                base = math.pow(base, exponent)
            except (ValueError, OverflowError) as e:
                raise ValueError(f"公式幂运算失败：{e}")
        self._leave()
        return base

    def primary(self):
        tok = self.next()
        if tok.kind == "num":
            return tok.value
        if tok.kind == "op" and tok.value == "(":
            value = self.comparison()
            self.expect(")")
            return value
        if tok.kind == "name":
            name = tok.value
            if self.accept("("):
                return self._call(name)
            lower = name.lower()
            if lower in CONSTANTS:
                return CONSTANTS[lower]
            if name in self.vars:
                return self.vars[name]
            # 大小写不敏感兜底（Excel 用户习惯 A1/b1 混写）
            for key, val in self.vars.items():
                if str(key).lower() == lower:
                    return val
            raise ValueError(f"公式中的变量 {name} 没有取值")
        raise ValueError(f"公式在位置 {tok.pos} 处出现了意外的符号：{tok.value!r}")

    def _call(self, name):
        key = name.lower()
        spec = FUNCTIONS.get(key)
        if spec is None:
            raise ValueError(f"公式函数 {name} 不在白名单内")
        args = []
        if not self.accept(")"):
            while True:
                args.append(self.comparison())
                if self.accept(","):
                    continue
                self.expect(")")
                break
        low, high, fn = spec
        if not (low <= len(args) <= high):
            raise ValueError(f"函数 {name} 需要 {low}~{high} 个参数，实际 {len(args)}")
        try:
            return float(fn(*args))
        except ValueError as e:
            raise ValueError(f"函数 {name} 计算失败：{e}")
        except (TypeError, OverflowError, ZeroDivisionError) as e:
            raise ValueError(f"函数 {name} 计算失败：{type(e).__name__}")


def _compare(op, left, right):
    if op == "==":
        return 1.0 if left == right else 0.0
    if op == "!=":
        return 1.0 if left != right else 0.0
    if op == ">":
        return 1.0 if left > right else 0.0
    if op == "<":
        return 1.0 if left < right else 0.0
    if op == ">=":
        return 1.0 if left >= right else 0.0
    return 1.0 if left <= right else 0.0


def normalize_variables(variables):
    """变量表归一：None → 0，数字字符串转 float，非数值变量直接跳过。

    None 按 0 处理是刻意的：SUM 在没有匹配行时返回 NULL，
    KPI 卡片应显示 0 而不是「公式错误」。
    维度列（如分组名）也会出现在行数据里，它们不是数字，跳过即可 ——
    真的在公式里引用到时会报「变量没有取值」，比在归一阶段统一报错更精确。
    """
    out = {}
    for key, value in (variables or {}).items():
        if value is None:
            out[key] = 0.0
            continue
        if isinstance(value, bool):
            out[key] = 1.0 if value else 0.0
            continue
        if isinstance(value, (int, float)):
            out[key] = float(value)
            continue
        try:
            out[key] = _coerce_number(value, f"变量 {key}")
        except ValueError:
            continue
    return out


def evaluate(expr, variables=None):
    """求值入口：返回 float；失败抛 ValueError（中文提示，含位置）。"""
    variables = normalize_variables(variables)
    tokens = tokenize(expr)
    parser = _Parser(tokens, variables)
    value = parser.parse()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("公式结果不是数值")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("公式结果不是有限数值")
    return result


def evaluate_round(expr, variables=None, digits=2):
    """求值并四舍五入（KPI 展示用，避免浮点尾巴）。"""
    return round(evaluate(expr, variables), int(digits))


def safe_pct_change(current, previous):
    """环比/同比变化率：上期为 0 或空时返回 None（前端显示「—」而不是 ∞）。"""
    try:
        cur = float(current or 0)
        prev = float(previous or 0)
    except (TypeError, ValueError):
        return None
    if prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 2)


def safe_share(part, total):
    """占比：分母为 0 返回 None。"""
    try:
        p = float(part or 0)
        t = float(total or 0)
    except (TypeError, ValueError):
        return None
    if t == 0:
        return None
    return round(p / t * 100, 2)


def kpi_from_rows(current_row, previous_row=None, formula="value", unit="", label=""):
    """KPI 卡片数据结构：当前值 + 上期值 + 变化量与变化率。

    formula 可用 ``a/b`` 这类跨列运算，current/previous 两张行字典各算一次。
    """
    current = evaluate(formula, current_row or {})
    previous = None
    if previous_row is not None:
        try:
            previous = evaluate(formula, previous_row or {})
        except ValueError:
            previous = None
    delta = round(current - previous, 4) if previous is not None else None
    return {
        "label": label,
        "value": round(current, 4),
        "previous": None if previous is None else round(previous, 4),
        "delta": delta,
        "delta_pct": safe_pct_change(current, previous) if previous is not None else None,
        "formula": formula,
        "unit": unit,
    }


def formula_variables(columns, row):
    """把一行数据转成变量表，同时提供：

    - 原名（列 key）
    - ``row.<key>`` 前缀形式（表达式里点号更接近表格习惯）
    - 全部数值列的合计 ``total``（占比公式常用）
    """
    variables = {}
    numeric_sum = 0.0
    for col in columns or []:
        key = col.get("key")
        if not key:
            continue
        value = (row or {}).get(key)
        if value is None:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            variables[key] = value
            continue
        variables[key] = num
        variables[f"row.{key}"] = num
        numeric_sum += num
    variables.setdefault("total", numeric_sum)
    return variables


def validate_formula(expr, sample_keys=None):
    """保存配置时的公式校验：语法 + 未知变量。

    sample_keys 提供时，用 1.0 填充这些变量试算一次；未提供的变量按 0 试算不了
    （会报「变量没有取值」），所以这里把 sample_keys 之外的变量先视作合法但
    无法试算 —— 只做语法校验（tokens 可解析）。
    """
    tokens = tokenize(expr)
    problem = _syntax_only(tokens)
    if problem:
        raise ValueError(problem)
    if sample_keys:
        variables = {key: 0.0 for key in sample_keys}
        evaluate(expr, variables)
        return True
    return True


def _syntax_only(tokens):
    """不依赖变量值的语法检查：把 name 替换成 0 后试算。"""
    safe_tokens = []
    for tok in tokens:
        if tok.kind == "name":
            lower = tok.value.lower()
            if lower in FUNCTIONS or lower in CONSTANTS:
                safe_tokens.append(tok)
            else:
                safe_tokens.append(_Token("num", 0.0, tok.pos))
        else:
            safe_tokens.append(tok)
    try:
        _Parser(safe_tokens, {}).parse()
    except ValueError as e:
        text = str(e)
        if "除数为 0" in text or "取模" in text:
            return None  # 0 做除数属试算副作用，不算语法错
        return text
    return None


def compare_with_previous(current_row, previous_row, formula, label="", unit=""):
    """同比/环比：两次求值 + 变化率，异常时降级为「无上期」。"""
    try:
        return kpi_from_rows(current_row, previous_row, formula, unit, label)
    except ValueError:
        return {
            "label": label,
            "value": None,
            "previous": None,
            "delta": None,
            "delta_pct": None,
            "formula": formula,
            "unit": unit,
            "error": "当前值与上期值无法用同一公式计算",
        }
