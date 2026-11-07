# -*- coding: utf-8 -*-
"""流程引擎 · 服务层。

本模块承载全部「跨表、跨状态」的逻辑，视图层不直接改状态字段：

1. 定义校验：唯一 start/end、可达性、孤立节点、网关配比、条件表达式语法、指派规则；
2. 图算法：DFS 环检测、Kahn 拓扑排序、正向/反向可达、关键路径（SLA 估算）；
3. 条件表达式：自研 tokenizer + 递归下降解析器，**不使用 eval/exec**；
4. 执行引擎：令牌推进、并行拆分/汇聚、任务生成、决策分支、完成判定；
5. 指派解析：user / role / dept / manager / expression + 委托扩展 + 兜底；
6. SLA：逾期标记、到期提醒、定时器触发，全部幂等；
7. 指标：完成率、平均耗时、节点瓶颈（含 P90）、状态/分类分布、趋势；
8. 版本：发布快照、回滚、对比、克隆、导入导出；
9. 通知/Webhook：站内落库 + 投递状态模拟（不联网）。

为什么表达式不用 ``eval``：流程条件来自用户输入，``eval`` 可直接执行任意代码
（``__import__('os').system(...)``）。这里用白名单词法 + 递归下降，只支持比较、
布尔、算术、列表与变量路径，且限制长度/ token 数/嵌套深度，杜绝注入。
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from accounts.models import Department
from core.scoping import can_write, is_visible, scope_queryset

from workflow.models import (
    ASSIGNEE_TYPE_VALUES,
    DEFINITION_EDITABLE_STATUS,
    INSTANCE_FINAL_STATUS,
    NODE_TYPE_VALUES,
    TASK_OPEN_STATUS,
    VARIABLE_TYPE_CHOICES,
    WorkflowAttachment,
    WorkflowAuditLog,
    WorkflowComment,
    WorkflowDefinition,
    WorkflowDelegation,
    WorkflowInstance,
    WorkflowMetric,
    WorkflowNode,
    WorkflowNotification,
    WorkflowSlaPolicy,
    WorkflowSnapshot,
    WorkflowTask,
    WorkflowTimer,
    WorkflowToken,
    WorkflowTransition,
    WorkflowVariable,
    WorkflowVersion,
    WorkflowWebhook,
)

User = get_user_model()

# 表达式与引擎的安全上限：防止恶意/错误输入把单次请求拖死
MAX_EXPR_LENGTH = 4000
MAX_EXPR_TOKENS = 600
MAX_PARSE_DEPTH = 64
MAX_ADVANCE_STEPS = 400
MAX_NAME_LENGTH = 200
TASK_OPEN = TASK_OPEN_STATUS
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,63}$")
VARIABLE_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,99}$")
REMIND_WINDOW_MINUTES = 120

EVENT_INSTANCE_STARTED = "instance.started"
EVENT_INSTANCE_COMPLETED = "instance.completed"
EVENT_INSTANCE_REJECTED = "instance.rejected"
EVENT_INSTANCE_CANCELLED = "instance.cancelled"
EVENT_TASK_CREATED = "task.created"
EVENT_TASK_COMPLETED = "task.completed"
EVENT_TASK_OVERDUE = "task.overdue"


# ===========================================================================
# 一、条件表达式：tokenizer + 递归下降解析 + 求值
# ===========================================================================


class _Token:
    """词法单元：kind ∈ num/str/ident/op/lparen/rparen/lbracket/rbracket/comma/dot/eof。"""

    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.kind},{self.value!r},{self.pos})"


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"'}


def _tokenize(text):
    """把表达式切成词法单元；遇到非法字符立即报错并给位置。"""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (text[j].isdigit() or (text[j] == "." and not seen_dot)):
                if text[j] == ".":
                    seen_dot = True
                j += 1
            if j < n and text[j] in "eE":
                k = j + 1
                if k < n and text[k] in "+-":
                    k += 1
                if k < n and text[k].isdigit():
                    j = k
                    while j < n and text[j].isdigit():
                        j += 1
            raw = text[i:j]
            try:
                value = float(raw) if any(c in raw for c in ".eE") else int(raw)
            except ValueError:
                raise ValueError(f"条件表达式中的数字 {raw!r} 不合法（位置 {i}）")
            tokens.append(_Token("num", value, i))
            i = j
            continue
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            buf = []
            closed = False
            while j < n:
                c = text[j]
                if c == "\\" and j + 1 < n:
                    buf.append(_ESCAPES.get(text[j + 1], text[j + 1]))
                    j += 2
                    continue
                if c == quote:
                    closed = True
                    break
                buf.append(c)
                j += 1
            if not closed:
                raise ValueError(f"条件表达式的字符串缺少结束引号（位置 {i}）")
            tokens.append(_Token("str", "".join(buf), i))
            i = j + 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(_Token("ident", text[i:j], i))
            i = j
            continue
        pair = text[i:i + 2]
        if pair in ("==", "!=", ">=", "<="):
            tokens.append(_Token("op", pair, i))
            i += 2
            continue
        if ch in "><+-*/%":
            tokens.append(_Token("op", ch, i))
            i += 1
            continue
        if ch == "=":
            raise ValueError(f"条件表达式请使用 == 进行比较（位置 {i}）")
        simple = {"(": "lparen", ")": "rparen", "[": "lbracket", "]": "rbracket",
                  ",": "comma", ".": "dot"}
        if ch in simple:
            tokens.append(_Token(simple[ch], ch, i))
            i += 1
            continue
        raise ValueError(f"条件表达式包含不支持的字符 {ch!r}（位置 {i}）")
    tokens.append(_Token("eof", "", n))
    if len(tokens) > MAX_EXPR_TOKENS:
        raise ValueError(f"条件表达式过于复杂（超过 {MAX_EXPR_TOKENS} 个词法单元）")
    return tokens


class _ConditionParser:
    """递归下降解析器。

    文法（优先级从低到高）：
        expr       := or_expr
        or_expr    := and_expr (OR and_expr)*
        and_expr   := not_expr (AND not_expr)*
        not_expr   := NOT not_expr | comparison
        comparison := additive ((==|!=|>|>=|<|<=|IN|NOT IN) additive)?
        additive   := multiplicative ((+|-) multiplicative)*
        multiplicative := unary ((*|/|%) unary)*
        unary      := (+|-|NOT) unary | primary
        primary    := NUMBER | STRING | TRUE | FALSE | NULL
                    | IDENT ('.' IDENT | '[' (NUMBER|STRING) ']')*
                    | '(' expr ')' | '[' expr (',' expr)* ']'
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.depth = 0

    # ---- 基础操作 ----

    @property
    def current(self):
        return self.tokens[self.pos]

    def peek(self, offset=1):
        idx = self.pos + offset
        return self.tokens[idx] if idx < len(self.tokens) else self.tokens[-1]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != "eof":
            self.pos += 1
        return tok

    def expect(self, kind, message):
        if self.current.kind != kind:
            raise ValueError(f"{message}（位置 {self.current.pos}）")
        return self.advance()

    def keyword(self, word):
        tok = self.current
        return tok.kind == "ident" and str(tok.value).lower() == word

    def consume_keyword(self, word):
        if self.keyword(word):
            self.advance()
            return True
        return False

    def enter(self):
        self.depth += 1
        if self.depth > MAX_PARSE_DEPTH:
            raise ValueError(f"条件表达式嵌套过深（超过 {MAX_PARSE_DEPTH} 层）")

    def leave(self):
        self.depth = max(self.depth - 1, 0)

    # ---- 入口 ----

    def parse(self):
        if self.current.kind == "eof":
            raise ValueError("条件表达式不能为空")
        node = self.parse_or()
        if self.current.kind != "eof":
            raise ValueError(f"条件表达式存在多余内容 {self.current.value!r}（位置 {self.current.pos}）")
        return node

    # ---- 各级文法 ----

    def parse_or(self):
        node = self.parse_and()
        while self.consume_keyword("or"):
            right = self.parse_and()
            node = ("bin", "or", node, right)
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.consume_keyword("and"):
            right = self.parse_not()
            node = ("bin", "and", node, right)
        return node

    def parse_not(self):
        if self.consume_keyword("not"):
            self.enter()
            node = ("unary", "not", self.parse_not())
            self.leave()
            return node
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_add()
        tok = self.current
        if tok.kind == "op" and tok.value in ("==", "!=", ">", ">=", "<", "<="):
            self.advance()
            right = self.parse_add()
            node = ("bin", tok.value, left, right)
        elif tok.kind == "ident" and str(tok.value).lower() == "in":
            self.advance()
            right = self.parse_add()
            node = ("bin", "in", left, right)
        elif tok.kind == "ident" and str(tok.value).lower() == "not" \
                and self.peek().kind == "ident" and str(self.peek().value).lower() == "in":
            self.advance()
            self.advance()
            right = self.parse_add()
            node = ("bin", "not in", left, right)
        else:
            return left
        # 不支持链式比较：a < b < c 在流程条件里容易写出非预期语义，直接拒绝
        nxt = self.current
        if (nxt.kind == "op" and nxt.value in ("==", "!=", ">", ">=", "<", "<=")) \
                or (nxt.kind == "ident" and str(nxt.value).lower() in ("in", "not")):
            raise ValueError(f"条件表达式不支持链式比较（位置 {nxt.pos}），请用 and 连接")
        return node

    def parse_add(self):
        node = self.parse_mul()
        while self.current.kind == "op" and self.current.value in ("+", "-"):
            op = self.advance().value
            node = ("bin", op, node, self.parse_mul())
        return node

    def parse_mul(self):
        node = self.parse_unary()
        while self.current.kind == "op" and self.current.value in ("*", "/", "%"):
            op = self.advance().value
            node = ("bin", op, node, self.parse_unary())
        return node

    def parse_unary(self):
        if self.current.kind == "op" and self.current.value in ("+", "-"):
            op = self.advance().value
            self.enter()
            node = ("unary", op, self.parse_unary())
            self.leave()
            return node
        return self.parse_primary()

    def parse_primary(self):
        tok = self.current
        if tok.kind == "num":
            self.advance()
            return ("lit", tok.value)
        if tok.kind == "str":
            self.advance()
            return ("lit", tok.value)
        if tok.kind == "ident":
            lower = str(tok.value).lower()
            if lower in ("true", "false", "null", "none"):
                self.advance()
                if lower == "true":
                    return ("lit", True)
                if lower == "false":
                    return ("lit", False)
                return ("lit", None)
            self.advance()
            segments = [("key", tok.value)]
            while True:
                if self.current.kind == "dot":
                    self.advance()
                    if self.current.kind != "ident":
                        raise ValueError(f"变量路径的 . 后必须是名称（位置 {self.current.pos}）")
                    segments.append(("key", self.advance().value))
                elif self.current.kind == "lbracket":
                    self.advance()
                    index_tok = self.current
                    if index_tok.kind not in ("num", "str"):
                        raise ValueError(f"变量下标只支持数字或字符串（位置 {index_tok.pos}）")
                    segments.append(("index", self.advance().value))
                    self.expect("rbracket", "变量下标缺少 ]")
                else:
                    break
            return ("var", segments)
        if tok.kind == "lparen":
            self.advance()
            self.enter()
            node = self.parse_or()
            self.leave()
            self.expect("rparen", "条件表达式缺少右括号")
            return node
        if tok.kind == "lbracket":
            self.advance()
            self.enter()
            items = []
            if self.current.kind != "rbracket":
                while True:
                    items.append(self.parse_or())
                    if self.current.kind == "comma":
                        self.advance()
                        continue
                    break
            self.leave()
            self.expect("rbracket", "条件表达式的列表缺少 ]")
            return ("list", items)
        raise ValueError(f"条件表达式在位置 {tok.pos} 缺少可求值的操作数")


@lru_cache(maxsize=512)
def _compile_cached(text):
    """编译并缓存 AST：条件表达式在每次流转都会求值，缓存可省掉重复解析。"""
    if len(text) > MAX_EXPR_LENGTH:
        raise ValueError(f"条件表达式过长（上限 {MAX_EXPR_LENGTH} 字符）")
    tokens = _tokenize(text)
    return _ConditionParser(tokens).parse()


def compile_condition(text):
    """对外暴露的编译入口（异常信息为中文，可直接回给前端）。"""
    if text is None:
        raise ValueError("条件表达式不能为空")
    return _compile_cached(str(text).strip())


def _truthy(value):
    """统一的真值判定：None / 0 / 空串 / 空容器为假。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (str, list, tuple, dict, set)):
        return len(value) > 0
    return True


def _is_number(value):
    """是否数字（bool 是 int 子类，但不按数字处理，避免 True > 0 这类歧义）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_like(value):
    """转数字；无法转换返回 None。数字字符串（表单常见）也按数字处理。"""
    if _is_number(value):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text) if ("." in text or "e" in text.lower()) else int(text)
        except ValueError:
            return None
    return None


def _to_number(value):
    """强转数字，失败抛中文错误（算术运算用）。"""
    number = _numeric_like(value)
    if number is None:
        raise ValueError(f"值 {value!r} 不是数字，不能参与算术运算")
    return number


def _resolve_var(segments, context):
    """按路径取值：字典键、列表下标、字符串按下标取字符；缺失一律 None。"""
    cur = context
    for kind, key in segments:
        if kind == "key":
            if isinstance(cur, dict):
                if key not in cur:
                    return None
                cur = cur[key]
            elif isinstance(cur, (list, tuple)) and str(key).isdigit():
                idx = int(key)
                if idx >= len(cur):
                    return None
                cur = cur[idx]
            else:
                return None
        else:
            if isinstance(cur, dict):
                cur = cur.get(key)
            elif isinstance(cur, (list, tuple)):
                try:
                    idx = int(key)
                except (TypeError, ValueError):
                    return None
                if idx < 0 or idx >= len(cur):
                    return None
                cur = cur[idx]
            elif isinstance(cur, str):
                try:
                    idx = int(key)
                except (TypeError, ValueError):
                    return None
                cur = cur[idx] if -len(cur) <= idx < len(cur) else None
            else:
                return None
    return cur


def _equality(left, right):
    """相等比较：数字/数字字符串按数值比较，其余按 Python 相等。"""
    ln, rn = _numeric_like(left), _numeric_like(right)
    if ln is not None and rn is not None:
        return ln == rn
    return left == right


def _ordered_compare(op, left, right):
    """大小比较：同类型直接比；数字字符串转数字；日期 ISO 字符串按字典序。"""
    if left is None or right is None:
        return False
    ln, rn = _numeric_like(left), _numeric_like(right)
    if ln is not None and rn is not None:
        a, b = ln, rn
    elif isinstance(left, str) and isinstance(right, str):
        a, b = left, right
    else:
        a, b = str(left), str(right)
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "<":
        return a < b
    return a <= b


def _contains(container, item):
    """in 运算：支持列表/元组/集合/字典键/字符串子串。"""
    if container is None:
        return False
    if isinstance(container, str):
        return str(item) in container
    if isinstance(container, dict):
        return item in container
    if isinstance(container, (list, tuple, set)):
        return item in container
    return False


def _eval_node(node, context):
    """对 AST 求值。"""
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "var":
        return _resolve_var(node[1], context)
    if kind == "list":
        return [_eval_node(item, context) for item in node[1]]
    if kind == "unary":
        op, child = node[1], node[2]
        value = _eval_node(child, context)
        if op == "not":
            return not _truthy(value)
        if op == "-":
            return -_to_number(value)
        return _to_number(value)
    if kind == "bin":
        op = node[1]
        if op == "and":
            left = _eval_node(node[2], context)
            return _truthy(left) and _truthy(_eval_node(node[3], context))
        if op == "or":
            left = _eval_node(node[2], context)
            return _truthy(left) or _truthy(_eval_node(node[3], context))
        left = _eval_node(node[2], context)
        right = _eval_node(node[3], context)
        if op == "==":
            return _equality(left, right)
        if op == "!=":
            return not _equality(left, right)
        if op in (">", ">=", "<", "<="):
            return _ordered_compare(op, left, right)
        if op == "in":
            return _contains(right, left)
        if op == "not in":
            return not _contains(right, left)
        if op == "+":
            if isinstance(left, str) or isinstance(right, str):
                return f"{left}{right}"
            return _to_number(left) + _to_number(right)
        if op == "-":
            return _to_number(left) - _to_number(right)
        if op == "*":
            return _to_number(left) * _to_number(right)
        if op == "/":
            divisor = _to_number(right)
            if divisor == 0:
                raise ValueError("条件表达式出现除零")
            return _to_number(left) / divisor
        if op == "%":
            divisor = _to_number(right)
            if divisor == 0:
                raise ValueError("条件表达式出现取模除零")
            return _to_number(left) % divisor
    raise ValueError("条件表达式包含无法求值的节点")


def evaluate_expression(text, context=None):
    """求值并返回原始结果（指派表达式需要拿到用户名/ID，而不是布尔）。"""
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    ast = compile_condition(text)
    return _eval_node(ast, context or {})


def evaluate_condition(text, context=None):
    """求值条件并返回布尔；空条件视为通过。"""
    if text is None:
        return True
    text = str(text).strip()
    if not text:
        return True
    try:
        ast = compile_condition(text)
        return _truthy(_eval_node(ast, context or {}))
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 兜底成 400，不暴露内部栈
        raise ValueError(f"条件表达式求值失败：{exc}")


def explain_condition(text, context=None):
    """诊断接口：返回是否合法、求值结果与错误信息（设计器实时预览用）。"""
    result = {"expression": str(text or ""), "valid": False, "result": None, "error": ""}
    try:
        ast = compile_condition(text)
        result["valid"] = True
        result["result"] = _truthy(_eval_node(ast, context or {}))
    except ValueError as exc:
        result["error"] = str(exc)
    return result


# ===========================================================================
# 二、图算法
# ===========================================================================


def build_adjacency(nodes, transitions):
    """构建邻接表：key -> 按优先级排序的出边列表。

    ``nodes`` / ``transitions`` 既可以是模型实例，也可以是导入用的字典，
    统一用 _get 取值，校验器与运行时共用同一份图结构。
    """
    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    node_keys = [str(_get(n, "key")) for n in nodes]
    adjacency = {key: [] for key in node_keys}
    for edge in transitions:
        if isinstance(edge, dict):
            source = edge.get("from") or edge.get("from_key")
            target = edge.get("to") or edge.get("to_key")
        else:
            source = edge.from_node.key
            target = edge.to_node.key
        source, target = str(source), str(target)
        adjacency.setdefault(source, []).append({
            "to": target,
            "condition": _get(edge, "condition", "") or "",
            "priority": int(_get(edge, "priority", 100) or 100),
            "is_default": bool(_get(edge, "is_default", False)),
            "label": _get(edge, "label", "") or "",
        })
    for key in adjacency:
        adjacency[key].sort(key=lambda e: (e["priority"], e["to"]))
    return adjacency


def reverse_adjacency(adjacency):
    """反向邻接表（判断「能否到达终点」用）。"""
    rev = {key: [] for key in adjacency}
    for source, edges in adjacency.items():
        for edge in edges:
            rev.setdefault(edge["to"], []).append(source)
    return rev


def reachable_from(adjacency, start_key):
    """从 start 出发的 BFS 可达集合（含自身）。"""
    if start_key not in adjacency:
        return set()
    seen = {start_key}
    queue = [start_key]
    while queue:
        cur = queue.pop(0)
        for edge in adjacency.get(cur, []):
            nxt = edge["to"]
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def reachable_ends(adjacency, start_key, end_keys):
    """从当前节点出发可达的结束节点（运行态「还能到哪些终点」）。"""
    ends = set(end_keys)
    return reachable_from(adjacency, start_key) & ends


def detect_cycles(adjacency):
    """DFS 三色标记找环，返回去重后的环路径列表。

    环在流程里可能是合法的「退回重办」，所以这里只报告不直接判错；
    校验器再判断「环里有没有人工任务/决策节点」——纯网关环没有任何
    等待点，会让引擎在单次请求内死循环。
    """
    white, gray, black = 0, 1, 2
    state = {key: white for key in adjacency}
    cycles, seen = [], set()
    path = []

    def dfs(node):
        state[node] = gray
        path.append(node)
        for edge in adjacency.get(node, []):
            nxt = edge["to"]
            if nxt not in state:
                continue
            if state[nxt] == gray:
                idx = path.index(nxt) if nxt in path else 0
                cycle = path[idx:]
                canonical = tuple(sorted(set(cycle)))
                if canonical not in seen:
                    seen.add(canonical)
                    cycles.append(list(cycle))
            elif state[nxt] == white:
                dfs(nxt)
        path.pop()
        state[node] = black

    for key in adjacency:
        if state[key] == white:
            dfs(key)
        if len(cycles) >= 50:
            break
    return cycles


def topological_order(adjacency):
    """Kahn 拓扑排序；返回 (顺序列表, 是否存在环)。

    用最小堆式的排序（按 key 字典序）保证同一张图输出的顺序稳定，
    版本对比与测试断言才能得到确定结果。
    """
    indegree = {key: 0 for key in adjacency}
    for key, edges in adjacency.items():
        for edge in edges:
            if edge["to"] in indegree:
                indegree[edge["to"]] += 1
    queue = sorted([k for k, v in indegree.items() if v == 0])
    order = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for edge in adjacency.get(cur, []):
            nxt = edge["to"]
            if nxt not in indegree:
                continue
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
        queue.sort()
    return order, len(order) != len(adjacency)


def longest_sla_path(adjacency, node_minutes):
    """DAG 上的关键路径（按节点 SLA 分钟数累加），用于估算流程最长处理时间。

    有环时退化为 0：环上可以无限重办，最长路径没有意义。
    """
    order, has_cycle = topological_order(adjacency)
    if has_cycle:
        return 0, []
    best = {key: (node_minutes.get(key, 0) or 0, [key]) for key in adjacency}
    for key in order:
        minutes, path = best[key]
        for edge in adjacency.get(key, []):
            nxt = edge["to"]
            if nxt not in best:
                continue
            candidate = minutes + (node_minutes.get(nxt, 0) or 0)
            # 等长时保留更长的链路：开始/结束节点 SLA 常为 0，若严格大于就
            # 永远选不到「s -> a」这种零耗时前缀，前端展示的关键路径会缺头。
            if candidate > best[nxt][0] or (
                    candidate == best[nxt][0] and len(path) + 1 > len(best[nxt][1])):
                best[nxt] = (candidate, path + [nxt])
    if not best:
        return 0, []
    key = max(best, key=lambda k: best[k][0])
    return best[key]


# ===========================================================================
# 三、定义校验
# ===========================================================================


def _issue(code, message, node="", transition=""):
    """构造一条校验问题；node/transition 用于前端高亮画布元素。"""
    return {"code": code, "message": message, "node": node, "transition": transition}


def _get(obj, key, default=None):
    """同时兼容模型实例与字典的取值助手。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _validate_assignee_rule(node):
    """校验指派规则结构，返回问题列表。"""
    issues = []
    key = str(_get(node, "key", ""))
    assignee_type = _get(node, "assignee_type", "user") or "user"
    rule = _get(node, "assignee_rule", {}) or {}
    if not isinstance(rule, dict):
        return [_issue("assignee_rule_type", f"节点 {key} 的指派规则必须是对象", node=key)]
    if assignee_type not in ASSIGNEE_TYPE_VALUES:
        return [_issue("assignee_type", f"节点 {key} 的办理人类型 {assignee_type} 不受支持", node=key)]
    if assignee_type == "none":
        return [_issue("assignee_none", f"人工任务节点 {key} 必须配置办理人", node=key)]
    if assignee_type == "user":
        if not (rule.get("user_ids") or rule.get("usernames")):
            issues.append(_issue("assignee_user", f"节点 {key} 需指定用户ID或用户名", node=key))
    elif assignee_type == "role":
        if not (rule.get("roles") or []):
            issues.append(_issue("assignee_role", f"节点 {key} 需指定角色编码", node=key))
    elif assignee_type == "dept":
        if not (rule.get("dept_ids") or []):
            issues.append(_issue("assignee_dept", f"节点 {key} 需指定部门ID", node=key))
    elif assignee_type == "manager":
        level = rule.get("level", 1)
        try:
            level = int(level)
        except (TypeError, ValueError):
            issues.append(_issue("assignee_manager", f"节点 {key} 的主管层级必须是整数", node=key))
        else:
            if level < 1 or level > 10:
                issues.append(_issue("assignee_manager", f"节点 {key} 的主管层级需在 1-10 之间", node=key))
    elif assignee_type == "expression":
        expr = str(rule.get("expression") or "").strip()
        if not expr:
            issues.append(_issue("assignee_expr", f"节点 {key} 的指派表达式不能为空", node=key))
        else:
            try:
                compile_condition(expr)
            except ValueError as exc:
                issues.append(_issue("assignee_expr", f"节点 {key} 的指派表达式不合法：{exc}", node=key))
    return issues


def _validate_graph(nodes, transitions, default_sla=0):
    """核心校验：对「节点 + 连线」的结构做静态分析。

    返回 {valid, errors, warnings, stats}，导入、发布、批量保存三处共用。
    这样任何入口都不能把非法图写进库，避免运行期才炸。
    """
    errors, warnings = [], []
    nodes = list(nodes or [])
    transitions = list(transitions or [])

    if not nodes:
        return {
            "valid": False,
            "errors": [_issue("empty", "流程至少需要一个开始节点和一个结束节点")],
            "warnings": [],
            "stats": {"node_count": 0, "transition_count": 0},
        }

    by_key = {}
    for node in nodes:
        key = str(_get(node, "key", "") or "").strip()
        if not key:
            errors.append(_issue("node_key", "存在缺少标识的节点"))
            continue
        if not KEY_PATTERN.match(key):
            errors.append(_issue("node_key", f"节点标识 {key!r} 只能包含字母、数字、下划线、点与中划线", node=key))
        if key in by_key:
            errors.append(_issue("node_dup", f"节点标识 {key} 重复", node=key))
            continue
        node_type = _get(node, "node_type", "task") or "task"
        if node_type not in NODE_TYPE_VALUES:
            errors.append(_issue("node_type", f"节点 {key} 的类型 {node_type} 不受支持", node=key))
        by_key[key] = node

    start_keys = [k for k, n in by_key.items() if (_get(n, "node_type") == "start")]
    end_keys = [k for k, n in by_key.items() if (_get(n, "node_type") == "end")]
    if len(start_keys) != 1:
        errors.append(_issue("start_count", f"流程必须有且仅有一个开始节点（当前 {len(start_keys)} 个）"))
    if not end_keys:
        errors.append(_issue("end_missing", "流程至少需要一个结束节点"))

    # 连线引用与唯一性
    seen_edges = set()
    edge_pairs = []
    for edge in transitions:
        source = str(_get(edge, "from", _get(edge, "from_key", "")) or "")
        target = str(_get(edge, "to", _get(edge, "to_key", "")) or "")
        if source not in by_key:
            errors.append(_issue("edge_from", f"连线源节点 {source} 不存在", transition=f"{source}->{target}"))
            continue
        if target not in by_key:
            errors.append(_issue("edge_to", f"连线目标节点 {target} 不存在", transition=f"{source}->{target}"))
            continue
        if source == target:
            errors.append(_issue("edge_self", f"连线不能指向自身：{source}", node=source,
                                 transition=f"{source}->{target}"))
            continue
        priority = int(_get(edge, "priority", 100) or 100)
        marker = (source, target, priority)
        if marker in seen_edges:
            errors.append(_issue("edge_dup", f"连线 {source}->{target} 的优先级 {priority} 重复",
                                 transition=f"{source}->{target}"))
            continue
        seen_edges.add(marker)
        condition = str(_get(edge, "condition", "") or "").strip()
        if condition:
            try:
                compile_condition(condition)
            except ValueError as exc:
                errors.append(_issue("edge_expr", f"连线 {source}->{target} 的条件不合法：{exc}",
                                     transition=f"{source}->{target}"))
        edge_pairs.append({"from": source, "to": target, "priority": priority,
                           "is_default": bool(_get(edge, "is_default", False)),
                           "condition": condition, "label": _get(edge, "label", "") or ""})

    adjacency = build_adjacency(list(by_key.values()), edge_pairs)
    reverse = reverse_adjacency(adjacency)

    # 孤立节点：既无入边也无出边（单节点流程除外）
    for key, node in by_key.items():
        in_count = len(reverse.get(key, []))
        out_count = len(adjacency.get(key, []))
        node_type = _get(node, "node_type")
        if len(by_key) > 1 and in_count == 0 and out_count == 0:
            errors.append(_issue("isolated", f"节点 {key} 是孤立节点（没有任何连线）", node=key))
        if node_type == "start" and in_count > 0:
            warnings.append(_issue("start_incoming", f"开始节点 {key} 存在入边（可能形成回环）", node=key))
        if node_type == "end" and out_count > 0:
            warnings.append(_issue("end_outgoing", f"结束节点 {key} 存在出边", node=key))

    start_key = start_keys[0] if start_keys else None
    reachable = reachable_from(adjacency, start_key) if start_key else set()
    for key in by_key:
        if start_key and key not in reachable:
            errors.append(_issue("unreachable", f"节点 {key} 从开始节点不可达", node=key))

    # 反向可达：每个节点都必须能走到某个结束节点，否则流程会「卡死」
    if end_keys:
        can_reach_end = set()
        queue = list(end_keys)
        can_reach_end.update(end_keys)
        while queue:
            cur = queue.pop(0)
            for prev in reverse.get(cur, []):
                if prev not in can_reach_end:
                    can_reach_end.add(prev)
                    queue.append(prev)
        for key in by_key:
            if key not in can_reach_end:
                errors.append(_issue("dead_end", f"节点 {key} 无法到达任何结束节点", node=key))

    # 节点级检查
    task_sla_total = 0
    for key, node in by_key.items():
        node_type = _get(node, "node_type", "task")
        out_edges = adjacency.get(key, [])
        in_edges = reverse.get(key, [])
        sla = _get(node, "sla_minutes", 0) or 0
        try:
            sla = int(sla)
        except (TypeError, ValueError):
            errors.append(_issue("sla_type", f"节点 {key} 的处理时限必须是整数", node=key))
            sla = 0
        if sla < 0:
            errors.append(_issue("sla_negative", f"节点 {key} 的处理时限不能为负数", node=key))
        if node_type == "task":
            task_sla_total += max(sla, 0)
            if _get(node, "assignee_type", "user") == "none":
                errors.append(_issue("assignee_none", f"人工任务节点 {key} 必须配置办理人", node=key))
            else:
                errors.extend(_validate_assignee_rule(node))
            if not out_edges and end_keys:
                errors.append(_issue("task_no_out", f"任务节点 {key} 没有出边", node=key))
        elif node_type == "decision":
            if len(out_edges) < 2:
                errors.append(_issue("decision_arity", f"条件分支 {key} 至少需要两条出边", node=key))
            if out_edges and all(not e["condition"] and not e["is_default"] for e in out_edges):
                errors.append(_issue("decision_none", f"条件分支 {key} 的所有出边都没有条件或默认分支", node=key))
        elif node_type == "parallel_split":
            if len(out_edges) < 2:
                errors.append(_issue("split_arity", f"并行拆分 {key} 至少需要两条出边", node=key))
        elif node_type == "parallel_join":
            if len(in_edges) < 2:
                errors.append(_issue("join_arity", f"并行汇聚 {key} 至少需要两条入边", node=key))
        elif node_type == "start":
            if not out_edges:
                errors.append(_issue("start_no_out", f"开始节点 {key} 没有出边", node=key))
        elif node_type == "end" and in_edges == [] and len(by_key) > 1:
            warnings.append(_issue("end_no_in", f"结束节点 {key} 没有入边", node=key))

        # 同一节点最多一个默认分支
        defaults = [e for e in out_edges if e["is_default"]]
        if len(defaults) > 1:
            errors.append(_issue("default_dup", f"节点 {key} 存在多个默认分支", node=key))

    start_edges = adjacency.get(start_key, []) if start_key else []
    if len(start_edges) > 1 and all(not e["condition"] for e in start_edges):
        warnings.append(_issue("start_multi", f"开始节点 {start_key} 有多条无条件出边，运行时只会走优先级最高的一条",
                              node=start_key or ""))

    cycles = detect_cycles(adjacency)
    for cycle in cycles:
        has_wait = any((_get(by_key.get(k), "node_type") in ("task", "decision")) for k in cycle)
        if not has_wait:
            errors.append(_issue("pure_cycle", "存在没有人工任务/决策节点的环：" + " → ".join(cycle + [cycle[0]])))
        else:
            warnings.append(_issue("cycle", "存在可回退的环：" + " → ".join(cycle + [cycle[0]])))

    order, has_cycle = topological_order(adjacency)
    node_minutes = {k: max(int(_get(n, "sla_minutes", 0) or 0), 0) for k, n in by_key.items()}
    longest_minutes, longest_path = longest_sla_path(adjacency, node_minutes)

    if default_sla and task_sla_total == 0:
        warnings.append(_issue("sla_missing", "所有任务节点都未设置 SLA，将使用流程默认时限"))

    stats = {
        "node_count": len(by_key),
        "transition_count": len(edge_pairs),
        "start_key": start_key or "",
        "end_keys": end_keys,
        "reachable_count": len(reachable),
        "unreachable": sorted(set(by_key) - reachable) if start_key else sorted(by_key),
        "cycles": cycles,
        "has_cycle": has_cycle,
        "topological_order": order,
        "task_sla_total_minutes": task_sla_total,
        "longest_path_minutes": longest_minutes,
        "longest_path": longest_path,
        "default_sla_minutes": int(default_sla or 0),
        "max_depth": len(longest_path),
        "task_node_count": len([k for k, n in by_key.items() if _get(n, "node_type") == "task"]),
    }
    stats["by_type"] = {
        node_type: len([k for k, n in by_key.items() if _get(n, "node_type") == node_type])
        for node_type in NODE_TYPE_VALUES
    }
    return {"valid": not errors, "errors": errors, "warnings": warnings, "stats": stats}


def _definition_graph(definition):
    """把入库的图转成校验器需要的字典结构（一次查询取全，避免 N+1）。"""
    nodes = [
        {
            "key": n.key,
            "name": n.name,
            "node_type": n.node_type,
            "assignee_type": n.assignee_type,
            "assignee_rule": n.assignee_rule or {},
            "sla_minutes": n.sla_minutes,
            "config": n.config or {},
            "form_fields": n.form_fields or [],
        }
        for n in definition.nodes.all().order_by("order", "id")
    ]
    transitions = [
        {
            "from": t.from_node.key,
            "to": t.to_node.key,
            "condition": t.condition,
            "priority": t.priority,
            "is_default": t.is_default,
            "label": t.label,
        }
        for t in definition.transitions.select_related("from_node", "to_node").order_by("priority", "id")
    ]
    return nodes, transitions


def validate_definition(definition, persist=False):
    """校验流程定义，可选把结果写回 settings.last_validation（设计器保存即校验）。"""
    nodes, transitions = _definition_graph(definition)
    result = _validate_graph(nodes, transitions, definition.default_sla_minutes())
    result["definition_id"] = definition.id
    result["checked_at"] = timezone.now().isoformat()
    if persist:
        settings = definition.settings if isinstance(definition.settings, dict) else {}
        settings = {
            **settings,
            "last_validation": {
                "valid": result["valid"],
                "checked_at": result["checked_at"],
                "error_count": len(result["errors"]),
                "warning_count": len(result["warnings"]),
            },
        }
        definition.settings = settings
        definition.save(update_fields=["settings", "updated_at"])
    return result


def validate_payload(payload):
    """对导入/批量保存的原始 payload 做同样的结构校验（不落库）。"""
    nodes = payload.get("nodes") if isinstance(payload, dict) else None
    transitions = payload.get("transitions") if isinstance(payload, dict) else None
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes 必须是非空数组")
    if transitions is None:
        transitions = []
    if not isinstance(transitions, list):
        raise ValueError("transitions 必须是数组")
    return _validate_graph(nodes, transitions, int(payload.get("default_sla_minutes", 0) or 0))


def ensure_publishable(definition):
    """发布前强校验：把前三条错误拼成一句可直接展示的中文。"""
    result = validate_definition(definition)
    if not result["valid"]:
        messages = [e["message"] for e in result["errors"][:3]]
        raise ValueError("流程校验未通过：" + "；".join(messages))
    return result


# ===========================================================================
# 四、权限与可见性
# ===========================================================================


def is_staff_user(user):
    """管理员判定：超管或 staff（数据范围再大也不等于写权限）。"""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def can_start_definition(definition, user):
    """发起权限：管理员 / 所有者 / allow_all / 角色 / 用户 / 部门（含下级）。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if is_staff_user(user) or definition.owner_id == user.id:
        return True
    perm = definition.permission_payload()
    if perm["allow_all"]:
        return True
    if not (perm["roles"] or perm["user_ids"] or perm["dept_ids"]):
        return True
    uid = getattr(user, "id", None)
    if uid and uid in perm["user_ids"]:
        return True
    if perm["roles"]:
        codes = set(user.roles.values_list("code", flat=True))
        if codes & set(perm["roles"]):
            return True
    if perm["dept_ids"]:
        dept_id = getattr(user, "department_id", None)
        if dept_id:
            expanded = set(perm["dept_ids"])
            for did in perm["dept_ids"]:
                dept = Department.objects.filter(pk=did).first()
                if dept:
                    expanded |= set(dept.descendant_ids())
            if int(dept_id) in expanded:
                return True
    return False


def ensure_definition_visible(definition, user):
    """定义可见性：数据范围可见或管理员。"""
    if is_staff_user(user) or is_visible(definition, user):
        return definition
    raise ValueError("无权查看该流程定义")


def ensure_definition_writable(definition, user):
    """定义写权限：所有者或管理员（严格 owner，不放开数据范围）。"""
    if is_staff_user(user) or can_write(user, definition):
        return definition
    raise ValueError("无权修改该流程定义")


def candidate_index_q(user, prefix=""):
    """候选池 SQL 条件：候选索引命中用户的任一 token 且任务未结。

    ``prefix`` 让我们既能在任务表上用（""），也能从实例表反查（"tasks__"）。
    索引是候选集的去规范化副本，最终仍由 ``is_candidate`` 做一次精确校验，
    因此这里宁可放宽（角色/部门可能重复命中），也不能漏掉可办理任务。
    """
    tokens = WorkflowTask.candidate_tokens_for(user)
    if not tokens:
        return Q(pk__in=[])
    field = f"{prefix}candidate_index__contains"
    status_field = f"{prefix}status__in"
    condition = Q()
    for token in tokens:
        condition |= Q(**{field: f",{token},", status_field: TASK_OPEN})
    return condition


def instance_queryset_for(user, queryset=None):
    """实例可见集合：数据范围 + 我发起的 + 指派给我的任务所在实例。

    「指派给我」单独放行是因为发起人可能不在我的数据范围内（跨部门协作），
    但我既然有任务就必须能看到实例详情，否则待办点开就是 403。候选池任务
    同理走 candidate_index 放行，否则候选人看得到待办却打不开详情。
    """
    qs = queryset if queryset is not None else WorkflowInstance.objects.all()
    if user is None or not getattr(user, "is_authenticated", False):
        return qs.none()
    if is_staff_user(user):
        return qs
    visible = scope_queryset(qs, user)
    return qs.filter(
        Q(id__in=visible.values("id"))
        | Q(starter=user)
        | Q(owner=user)
        | Q(tasks__assignee=user)
        | candidate_index_q(user, prefix="tasks__")
    ).distinct()


def is_participant(instance, user):
    """是否参与过实例：有任务（含候选）或发过评论。"""
    if user is None:
        return False
    uid = getattr(user, "id", None)
    if not uid:
        return False
    if instance.tasks.filter(Q(assignee=user) | Q(owner=user)).exists():
        return True
    if instance.comments.filter(owner=user).exists():
        return True
    for task in instance.tasks.filter(status__in=TASK_OPEN)[:50]:
        if task.is_candidate(user):
            return True
    return False


def ensure_instance_visible(instance, user):
    """实例读权限：数据范围 / 发起人 / 所有者 / 参与人 / 管理员。"""
    if is_staff_user(user) or is_visible(instance, user):
        return instance
    if user is not None and user.id in (instance.starter_id, instance.owner_id):
        return instance
    if is_participant(instance, user):
        return instance
    raise ValueError("无权查看该流程实例")


# ===========================================================================
# 五、版本、克隆、导入导出
# ===========================================================================


def node_payload(node):
    """节点 → 可入快照/可导出的纯数据。"""
    return {
        "key": node.key,
        "name": node.name,
        "node_type": node.node_type,
        "assignee_type": node.assignee_type,
        "assignee_rule": node.assignee_rule or {},
        "sla_minutes": node.sla_minutes,
        "form_fields": node.form_fields or [],
        "config": node.config or {},
        "position_x": node.position_x,
        "position_y": node.position_y,
        "order": node.order,
        "allow_reject": node.allow_reject,
        "allow_return": node.allow_return,
        "allow_add_sign": node.allow_add_sign,
        "allow_transfer": node.allow_transfer,
        "require_comment": node.require_comment,
    }


def transition_payload(transition):
    """连线 → 纯数据（用 key 引用节点）。"""
    return {
        "from": transition.from_node.key,
        "to": transition.to_node.key,
        "condition": transition.condition,
        "priority": transition.priority,
        "is_default": transition.is_default,
        "label": transition.label,
    }


def definition_graph_payload(definition):
    """完整定义导出结构：定义元信息 + 节点 + 连线。"""
    return {
        "definition": {
            "code": definition.code,
            "name": definition.name,
            "category": definition.category,
            "description": definition.description,
            "form_key": definition.form_key,
            "icon": definition.icon,
            "tags": definition.tags or [],
            "settings": definition.settings or {},
            "start_permission": definition.permission_payload(),
            "version_no": definition.version_no,
            "status": definition.status,
            "sla_policy_id": definition.sla_policy_id,
            "default_sla_minutes": definition.default_sla_minutes(),
        },
        "nodes": [node_payload(n) for n in definition.nodes.order_by("order", "id")],
        "transitions": [
            transition_payload(t)
            for t in definition.transitions.select_related("from_node", "to_node").order_by("priority", "id")
        ],
    }


def checksum_payload(payload):
    """规范化 JSON 后取 sha256，作为版本/快照指纹。"""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def publish_definition(definition, publisher, note=""):
    """发布：校验 → 生成不可变版本快照 → 旧版本标记 superseded → 定义指向新版本。

    整个操作在一个事务里：版本号、状态、快照必须同进同退，否则会出现
    「版本表有 v3 但定义还停在 v2」的脏数据。
    """
    ensure_publishable(definition)
    with transaction.atomic():
        definition = WorkflowDefinition.objects.select_for_update().get(pk=definition.pk)
        payload = definition_graph_payload(definition)
        version_no = definition.next_version_no()
        checksum = checksum_payload(payload)
        definition.versions.exclude(status="rolled_back").update(status="superseded")
        version = WorkflowVersion.objects.create(
            definition=definition,
            owner=definition.owner,
            version_no=version_no,
            snapshot=payload,
            publisher=publisher,
            published_at=timezone.now(),
            change_note=(note or "")[:2000],
            status="published",
            node_count=len(payload["nodes"]),
            transition_count=len(payload["transitions"]),
            checksum=checksum,
        )
        definition.version_no = version_no
        definition.status = "published"
        definition.published_at = timezone.now()
        definition.save(update_fields=["version_no", "status", "published_at", "updated_at"])
        log_audit(
            "definition.published",
            definition=definition,
            actor=publisher,
            from_status="draft",
            to_status="published",
            detail={"version_no": version_no, "checksum": checksum, "note": note[:200]},
        )
        emit_definition_event(definition, "definition.published",
                              {"version_no": version_no, "publisher_id": getattr(publisher, "id", None)})
    return version


def _node_from_payload(definition, owner, item, order_index):
    """把快照/导入里的节点字典还原成模型实例（不保存）。"""
    key = str(item.get("key") or "").strip()
    return WorkflowNode(
        definition=definition,
        owner=owner,
        key=key,
        name=str(item.get("name") or key)[:MAX_NAME_LENGTH],
        node_type=item.get("node_type") or "task",
        assignee_type=item.get("assignee_type") or "user",
        assignee_rule=item.get("assignee_rule") or {},
        sla_minutes=int(item.get("sla_minutes") or 0),
        form_fields=item.get("form_fields") or [],
        config=item.get("config") or {},
        position_x=int(item.get("position_x") or 0),
        position_y=int(item.get("position_y") or 0),
        order=int(item.get("order") or order_index),
        allow_reject=bool(item.get("allow_reject", True)),
        allow_return=bool(item.get("allow_return", True)),
        allow_add_sign=bool(item.get("allow_add_sign", True)),
        allow_transfer=bool(item.get("allow_transfer", True)),
        require_comment=bool(item.get("require_comment", False)),
    )


def rollback_version(definition, version, actor, note=""):
    """回滚到历史版本：用快照整图替换当前节点/连线，并生成一条 rolled_back 版本。

    为什么要禁止有运行中实例时回滚：令牌指向的是当前节点行，整图替换会把
    旧节点删掉（FK SET_NULL），在途实例会瞬间失去当前节点。安全做法是先
    让在途实例跑完或终止，再回滚。
    """
    if version.definition_id != definition.id:
        raise ValueError("该版本不属于此流程定义")
    running = definition.instances.filter(status="running").count()
    if running:
        raise ValueError(f"存在 {running} 个运行中的实例，暂不能回滚，请先完成或终止")
    snapshot = version.snapshot if isinstance(version.snapshot, dict) else {}
    nodes_payload = snapshot.get("nodes") or []
    transitions_payload = snapshot.get("transitions") or []
    if not nodes_payload:
        raise ValueError("该版本快照缺少节点数据，无法回滚")
    result = _validate_graph(nodes_payload, transitions_payload, definition.default_sla_minutes())
    if not result["valid"]:
        raise ValueError("版本快照校验未通过：" + "；".join(e["message"] for e in result["errors"][:3]))

    with transaction.atomic():
        definition = WorkflowDefinition.objects.select_for_update().get(pk=definition.pk)
        definition.transitions.all().delete()
        definition.nodes.all().delete()
        created = {}
        for idx, item in enumerate(nodes_payload):
            node = _node_from_payload(definition, definition.owner, item, idx)
            node.save()
            created[node.key] = node
        for item in transitions_payload:
            source = created.get(str(item.get("from") or ""))
            target = created.get(str(item.get("to") or ""))
            if source is None or target is None:
                raise ValueError("版本快照中的连线引用了不存在的节点")
            WorkflowTransition.objects.create(
                definition=definition,
                owner=definition.owner,
                from_node=source,
                to_node=target,
                condition=str(item.get("condition") or ""),
                priority=int(item.get("priority") or 100),
                is_default=bool(item.get("is_default", False)),
                label=str(item.get("label") or "")[:100],
            )
        version_no = definition.next_version_no()
        snapshot_payload = definition_graph_payload(definition)
        new_version = WorkflowVersion.objects.create(
            definition=definition,
            owner=definition.owner,
            version_no=version_no,
            snapshot=snapshot_payload,
            publisher=actor,
            published_at=timezone.now(),
            change_note=(note or f"回滚到 v{version.version_no}")[:2000],
            status="rolled_back",
            node_count=len(snapshot_payload["nodes"]),
            transition_count=len(snapshot_payload["transitions"]),
            checksum=checksum_payload(snapshot_payload),
        )
        definition.versions.exclude(pk=new_version.pk).exclude(status="rolled_back").update(status="superseded")
        definition.version_no = version_no
        definition.status = "published"
        definition.published_at = timezone.now()
        definition.save(update_fields=["version_no", "status", "published_at", "updated_at"])
        log_audit(
            "definition.rolled_back",
            definition=definition,
            actor=actor,
            detail={"from_version": version.version_no, "new_version": version_no},
        )
    return new_version


def diff_versions(left, right):
    """版本对比：按节点 key / 连线 from->to 计算新增、删除与字段变化。"""
    if left.definition_id != right.definition_id:
        raise ValueError("只能对比同一流程定义下的版本")
    left_nodes = {str(n.get("key")): n for n in left.nodes_payload if n.get("key")}
    right_nodes = {str(n.get("key")): n for n in right.nodes_payload if n.get("key")}
    watched = ("name", "node_type", "assignee_type", "assignee_rule", "sla_minutes",
               "form_fields", "config", "allow_reject", "allow_return", "require_comment")
    added_nodes = sorted(set(right_nodes) - set(left_nodes))
    removed_nodes = sorted(set(left_nodes) - set(right_nodes))
    changed_nodes = []
    for key in sorted(set(left_nodes) & set(right_nodes)):
        changes = {}
        for field in watched:
            if left_nodes[key].get(field) != right_nodes[key].get(field):
                changes[field] = {"before": left_nodes[key].get(field), "after": right_nodes[key].get(field)}
        if changes:
            changed_nodes.append({"key": key, "changes": changes})

    def _edge_key(item):
        return f"{item.get('from')}->{item.get('to')}"

    left_edges = {_edge_key(t): t for t in left.transitions_payload}
    right_edges = {_edge_key(t): t for t in right.transitions_payload}
    added_edges = sorted(set(right_edges) - set(left_edges))
    removed_edges = sorted(set(left_edges) - set(right_edges))
    changed_edges = []
    for marker in sorted(set(left_edges) & set(right_edges)):
        changes = {}
        for field in ("condition", "priority", "is_default", "label"):
            if left_edges[marker].get(field) != right_edges[marker].get(field):
                changes[field] = {"before": left_edges[marker].get(field), "after": right_edges[marker].get(field)}
        if changes:
            changed_edges.append({"edge": marker, "changes": changes})
    return {
        "left": {"id": left.id, "version_no": left.version_no},
        "right": {"id": right.id, "version_no": right.version_no},
        "nodes": {
            "added": added_nodes,
            "removed": removed_nodes,
            "changed": changed_nodes,
            "same_count": len(set(left_nodes) & set(right_nodes)) - len(changed_nodes),
        },
        "transitions": {
            "added": added_edges,
            "removed": removed_edges,
            "changed": changed_edges,
        },
        "summary": {
            "node_delta": len(added_nodes) - len(removed_nodes),
            "transition_delta": len(added_edges) - len(removed_edges),
            "changed": len(changed_nodes) + len(changed_edges),
        },
    }


def clone_definition(definition, actor, code="", name=""):
    """克隆：深拷贝图结构（含指派规则/SLA/配置），新流程从草稿开始。"""
    base_code = (code or f"{definition.code}-copy").strip()[:64]
    candidate = base_code
    suffix = 2
    while WorkflowDefinition.objects.filter(owner=actor, code=candidate).exists():
        candidate = f"{base_code[:58]}-{suffix}"
        suffix += 1
    payload = definition_graph_payload(definition)
    with transaction.atomic():
        clone = WorkflowDefinition.objects.create(
            owner=actor,
            code=candidate,
            name=(name or f"{definition.name}（副本）")[:MAX_NAME_LENGTH],
            category=definition.category,
            description=definition.description,
            version_no=1,
            status="draft",
            start_permission=payload["definition"]["start_permission"],
            form_key=definition.form_key,
            icon=definition.icon,
            tags=definition.tags or [],
            settings={k: v for k, v in (definition.settings or {}).items() if k != "last_validation"},
            sla_policy=definition.sla_policy,
        )
        key_map = {}
        for idx, item in enumerate(payload["nodes"]):
            node = _node_from_payload(clone, actor, item, idx)
            node.save()
            key_map[node.key] = node
        for item in payload["transitions"]:
            source = key_map.get(item["from"])
            target = key_map.get(item["to"])
            if source is None or target is None:
                continue
            WorkflowTransition.objects.create(
                definition=clone,
                owner=actor,
                from_node=source,
                to_node=target,
                condition=item["condition"],
                priority=item["priority"],
                is_default=item["is_default"],
                label=item["label"],
            )
        log_audit("definition.cloned", definition=clone, actor=actor,
                  detail={"source_id": definition.id, "source_code": definition.code})
    return clone


def export_definition(definition):
    """导出定义：附带校验结果，导入方可在落地前先看健康度。"""
    payload = definition_graph_payload(definition)
    payload["validation"] = validate_definition(definition)
    payload["exported_at"] = timezone.now().isoformat()
    payload["source"] = {"id": definition.id, "code": definition.code, "version_no": definition.version_no}
    return payload


def import_definition(owner, payload, dry_run=False, code="", name=""):
    """导入定义：先做纯内存校验，dry_run 只返回报告，否则事务内落地。"""
    if not isinstance(payload, dict):
        raise ValueError("导入内容必须是 JSON 对象")
    definition_data = payload.get("definition") if isinstance(payload.get("definition"), dict) else payload
    nodes = payload.get("nodes")
    transitions = payload.get("transitions") or []
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("导入内容缺少 nodes 数组")
    if not isinstance(transitions, list):
        raise ValueError("transitions 必须是数组")
    result = _validate_graph(nodes, transitions, int(definition_data.get("default_sla_minutes", 0) or 0))
    report = {
        "dry_run": bool(dry_run),
        "valid": result["valid"],
        "errors": result["errors"],
        "warnings": result["warnings"],
        "stats": result["stats"],
        "definition_code": (code or definition_data.get("code") or "").strip(),
    }
    if dry_run or not result["valid"]:
        if not result["valid"]:
            raise ValueError("导入校验未通过：" + "；".join(e["message"] for e in result["errors"][:3]))
        return report
    target_code = (code or definition_data.get("code") or "").strip()
    if not target_code:
        raise ValueError("导入内容缺少流程编码")
    if WorkflowDefinition.objects.filter(owner=owner, code=target_code).exists():
        raise ValueError(f"流程编码 {target_code} 已存在")
    with transaction.atomic():
        definition = WorkflowDefinition.objects.create(
            owner=owner,
            code=target_code[:64],
            name=(name or definition_data.get("name") or target_code)[:MAX_NAME_LENGTH],
            category=(definition_data.get("category") or "通用")[:40],
            description=str(definition_data.get("description") or ""),
            version_no=int(definition_data.get("version_no") or 1),
            status="draft",
            start_permission=definition_data.get("start_permission") or {"allow_all": True},
            form_key=str(definition_data.get("form_key") or "")[:64],
            icon=str(definition_data.get("icon") or "")[:40],
            tags=definition_data.get("tags") or [],
            settings=definition_data.get("settings") or {},
        )
        key_map = {}
        for idx, item in enumerate(nodes):
            node = _node_from_payload(definition, owner, item, idx)
            node.save()
            key_map[node.key] = node
        for item in transitions:
            source = key_map.get(str(item.get("from") or ""))
            target = key_map.get(str(item.get("to") or ""))
            if source is None or target is None:
                raise ValueError("连线引用了不存在的节点")
            WorkflowTransition.objects.create(
                definition=definition,
                owner=owner,
                from_node=source,
                to_node=target,
                condition=str(item.get("condition") or ""),
                priority=int(item.get("priority") or 100),
                is_default=bool(item.get("is_default", False)),
                label=str(item.get("label") or "")[:100],
            )
        log_audit("definition.imported", definition=definition, actor=owner,
                  detail={"node_count": len(nodes), "transition_count": len(transitions)})
    report["definition_id"] = definition.id
    report["imported"] = True
    return report


# ===========================================================================
# 六、指派解析
# ===========================================================================


def resolve_user(identifier):
    """按 id / 用户名 / 昵称解析用户；找不到抛中文错误。"""
    if identifier is None or identifier == "":
        raise ValueError("缺少用户标识")
    user = None
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
        user = User.objects.filter(pk=int(identifier)).first()
    if user is None:
        text = str(identifier).strip()
        user = User.objects.filter(Q(username=text) | Q(nickname=text)).first()
    if user is None:
        raise ValueError(f"用户 {identifier} 不存在")
    return user


def _users_from_value(value):
    """把表达式返回值解析成用户列表：支持 int/str/list/dict。"""
    users = []
    if value is None:
        return users
    if isinstance(value, dict):
        value = value.get("users") or value.get("user_ids") or value.get("usernames")
    if isinstance(value, (list, tuple, set)):
        for item in value:
            try:
                users.append(resolve_user(item))
            except ValueError:
                continue
        return users
    try:
        users.append(resolve_user(value))
    except ValueError:
        return users
    return users


def _active_delegations(from_user_ids, definition):
    """取覆盖指定流程的生效委托：from_user_id -> [to_user_id]。

    先按 from_user/status 收窄，再在 Python 侧判窗口与范围（窗口判定含时区，
    放 SQL 里要写一堆数据库函数，收益不大）。
    """
    mapping = {}
    if not from_user_ids:
        return mapping
    rows = WorkflowDelegation.objects.filter(
        status="active", from_user_id__in=list(from_user_ids)
    ).select_related("definition")[:200]
    for row in rows:
        if not row.is_active or not row.covers(definition):
            continue
        mapping.setdefault(row.from_user_id, []).append(row.to_user_id)
    return mapping


def resolve_assignees(node, instance):
    """解析节点办理人。

    返回：
    - users：User 对象列表（已去重、过滤停用、合并委托）
    - user_ids / roles / depts：写入任务的候选快照
    - source：解析来源（user/role/dept/manager/expression/fallback）
    - warning：兜底说明（为空表示正常）
    """
    rule = node.assignee_rule if isinstance(node.assignee_rule, dict) else {}
    users = []
    roles = [str(x) for x in (rule.get("roles") or [])]
    depts = []
    source = node.assignee_type
    warning = ""

    def _add(queryset):
        for user in queryset:
            users.append(user)

    if node.assignee_type == "user":
        ids = []
        for raw in (rule.get("user_ids") or []):
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        if ids:
            _add(User.objects.filter(pk__in=ids))
        names = [str(x) for x in (rule.get("usernames") or []) if str(x).strip()]
        if names:
            _add(User.objects.filter(Q(username__in=names) | Q(nickname__in=names)))
    elif node.assignee_type == "role":
        if roles:
            _add(User.objects.filter(roles__code__in=roles).distinct())
    elif node.assignee_type == "dept":
        expanded = set()
        include_children = bool(rule.get("include_children", True))
        for raw in (rule.get("dept_ids") or []):
            try:
                dept_id = int(raw)
            except (TypeError, ValueError):
                continue
            dept = Department.objects.filter(pk=dept_id).first()
            if dept is None:
                continue
            if include_children:
                expanded |= set(dept.descendant_ids())
            else:
                expanded.add(dept.id)
        depts = sorted(expanded)
        if depts:
            _add(User.objects.filter(department_id__in=depts))
    elif node.assignee_type == "manager":
        try:
            level = int(rule.get("level", 1) or 1)
        except (TypeError, ValueError):
            level = 1
        dept = getattr(instance.starter, "department", None)
        for _ in range(max(level - 1, 0)):
            dept = dept.parent if dept is not None else None
        guard = 0
        while dept is not None and guard < 10:
            if dept.leader_id:
                _add(User.objects.filter(pk=dept.leader_id))
                break
            dept = dept.parent
            guard += 1
    elif node.assignee_type == "expression":
        expression = str(rule.get("expression") or "").strip()
        if expression:
            try:
                value = evaluate_expression(expression, build_context(instance))
            except ValueError:
                value = None
            for user in _users_from_value(value):
                users.append(user)
    else:
        warning = "节点未配置办理人类型"

    # 停用用户不接收新任务
    filtered = []
    seen = set()
    for user in users:
        if user is None or user.id in seen:
            continue
        if not getattr(user, "is_active", True) or getattr(user, "is_disabled", False):
            continue
        seen.add(user.id)
        filtered.append(user)

    # 委托扩展：原办理人生效中的委托，把受托人一并加入候选
    delegation_map = _active_delegations(seen, instance.definition)
    if delegation_map:
        delegated_ids = {uid for ids in delegation_map.values() for uid in ids}
        for user in User.objects.filter(pk__in=delegated_ids):
            if user.id not in seen and getattr(user, "is_active", True):
                seen.add(user.id)
                filtered.append(user)
                warning = warning or "已按委托增加受托人"

    if not filtered:
        fallback_ids = []
        for raw in (rule.get("fallback_user_ids") or []):
            try:
                fallback_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        fallback = list(User.objects.filter(pk__in=fallback_ids)) if fallback_ids else []
        if not fallback and instance.starter_id:
            fallback = [instance.starter]
        filtered = fallback
        source = "fallback"
        warning = warning or "未解析到办理人，已回退给发起人"

    return {
        "users": filtered,
        "user_ids": [u.id for u in filtered],
        "roles": roles,
        "depts": depts,
        "source": source,
        "warning": warning,
    }


# ===========================================================================
# 七、上下文、审计、通知、指标
# ===========================================================================


def build_context(instance, task=None, extra=None):
    """合并条件求值上下文：实例上下文 → 变量 → 任务载荷 → 系统字段。

    变量优先于 context：变量是显式声明的强类型值，context 是发起时透传的
    原始表单（可能是字符串）。后两者以系统字段兜底，方便条件里直接写
    ``priority == "high"`` 而不必自己塞进 context。
    """
    context = dict(instance.context) if isinstance(instance.context, dict) else {}
    try:
        for variable in instance.variables.all():
            context[variable.key] = variable.typed_value
    except Exception:  # noqa: BLE001 —— 变量表异常不应该阻断流转
        pass
    if task is not None:
        payload = task.payload if isinstance(task.payload, dict) else {}
        context.setdefault("payload", payload)
        context["action"] = task.action
        context["task_comment"] = task.comment
    if isinstance(extra, dict):
        context.update(extra)
    context.setdefault("priority", instance.priority)
    context.setdefault("category", instance.category)
    context.setdefault("title", instance.title)
    context.setdefault("business_no", instance.business_no)
    context.setdefault("definition_code", instance.definition.code if instance.definition_id else "")
    starter = instance.starter
    if starter is not None:
        context.setdefault("starter", getattr(starter, "username", ""))
        context.setdefault("starter_id", starter.id)
        context.setdefault("starter_dept_id", getattr(starter, "department_id", None))
    today = timezone.localdate()
    context.setdefault("today", today.isoformat())
    context.setdefault("weekday", today.isoweekday())
    context.setdefault("now_hour", timezone.localtime().hour)
    return context


def log_audit(action, instance=None, task=None, definition=None, actor=None,
              from_status="", to_status="", detail=None, duration_ms=0, ip=""):
    """写审计日志。owner 取实例/定义/操作者，保证外键永远有值。"""
    owner = None
    if instance is not None:
        owner = instance.owner
    elif definition is not None:
        owner = definition.owner
    elif actor is not None:
        owner = actor
    if owner is None:
        return None
    return WorkflowAuditLog.objects.create(
        owner=owner,
        instance=instance,
        task=task,
        definition=definition,
        actor=actor if getattr(actor, "pk", None) else None,
        action=str(action)[:40],
        from_status=str(from_status or "")[:20],
        to_status=str(to_status or "")[:20],
        detail=detail or {},
        duration_ms=int(duration_ms or 0),
        ip=str(ip or "")[:45],
    )


def push_notification(recipient, title, content="", owner=None, instance=None, task=None,
                      level="info", channel="inapp", dedup_key="", payload=None):
    """站内通知落库；dedup_key 命中已有记录时直接复用（扫描类通知幂等）。"""
    if recipient is None:
        return None
    if dedup_key:
        existing = WorkflowNotification.objects.filter(
            recipient=recipient, dedup_key=dedup_key
        ).first()
        if existing is not None:
            return existing
    creator = owner or recipient
    return WorkflowNotification.objects.create(
        owner=creator,
        recipient=recipient,
        instance=instance,
        task=task,
        title=str(title)[:200],
        content=str(content or ""),
        level=level if level in ("info", "success", "warning", "danger") else "info",
        channel=channel,
        status="sent",
        dedup_key=str(dedup_key or "")[:120],
        payload=payload or {},
        sent_at=timezone.now(),
    )


def emit_definition_event(definition, event, payload):
    """定义级事件（发布/停用）投递给订阅了该定义的 Webhook。"""
    if definition is None:
        return []
    rows = WorkflowWebhook.objects.filter(active=True).filter(
        Q(definition_id=definition.id) | Q(definition_id__isnull=True)
    ).select_related("owner")[:50]
    delivered = []
    for webhook in rows:
        if not webhook.matches(event):
            continue
        WorkflowNotification.objects.create(
            owner=definition.owner,
            recipient=webhook.owner,
            title=f"Webhook 投递：{event}"[:200],
            content=f"{webhook.url} ← {event}",
            channel="webhook",
            status="sent",
            payload={"event": event, "url": webhook.url, "data": payload or {}},
            sent_at=timezone.now(),
        )
        webhook.last_status = "simulated_success"
        webhook.last_delivery_at = timezone.now()
        webhook.failure_count = 0
        webhook.save(update_fields=["last_status", "last_delivery_at", "failure_count", "updated_at"])
        delivered.append(webhook.id)
    return delivered


def emit_event(instance, event, payload, actor=None):
    """实例级事件投递（模拟）：命中订阅后落一条 webhook 渠道通知并更新状态。"""
    rows = WorkflowWebhook.objects.filter(active=True).filter(
        Q(definition_id=instance.definition_id) | Q(definition_id__isnull=True)
    ).select_related("owner")[:50]
    delivered = []
    for webhook in rows:
        if not webhook.matches(event):
            continue
        WorkflowNotification.objects.create(
            owner=instance.owner,
            recipient=webhook.owner,
            instance=instance,
            title=f"Webhook 投递：{event}"[:200],
            content=f"{webhook.url} ← {event} ({instance.business_no})",
            channel="webhook",
            status="sent",
            payload={
                "event": event,
                "url": webhook.url,
                "instance_id": instance.id,
                "business_no": instance.business_no,
                "actor_id": getattr(actor, "id", None),
                "data": payload or {},
                "timestamp": timezone.now().isoformat(),
            },
            sent_at=timezone.now(),
        )
        webhook.last_status = "simulated_success"
        webhook.last_delivery_at = timezone.now()
        webhook.failure_count = 0
        webhook.save(update_fields=["last_status", "last_delivery_at", "failure_count", "updated_at"])
        delivered.append(webhook.id)
    return delivered


METRIC_FIELDS = {
    "instances_started", "instances_completed", "instances_rejected",
    "tasks_created", "tasks_completed", "overdue_tasks",
}


def bump_metric(instance, field, day=None):
    """当日指标 +1（F 表达式原子自增，避免并发读改写丢失计数）。"""
    if field not in METRIC_FIELDS:
        return None
    metric_date = day or timezone.localdate()
    row, _ = WorkflowMetric.objects.get_or_create(
        owner=instance.definition.owner,
        definition=instance.definition,
        metric_date=metric_date,
    )
    WorkflowMetric.objects.filter(pk=row.pk).update(
        **{field: F(field) + 1}, updated_at=timezone.now()
    )
    return row


def refresh_metric_day(owner, definition, day):
    """按实例明细重算某日指标（补偿历史/修复漂移）。"""
    instances = WorkflowInstance.objects.filter(
        definition=definition, started_at__date=day
    )
    completed = WorkflowInstance.objects.filter(
        definition=definition, status="completed", finished_at__date=day
    )
    rejected = WorkflowInstance.objects.filter(
        definition=definition, status="rejected", finished_at__date=day
    )
    tasks_created = WorkflowTask.objects.filter(instance__definition=definition, created_at__date=day)
    tasks_completed = WorkflowTask.objects.filter(
        instance__definition=definition, status="completed", completed_at__date=day
    )
    durations = [i.duration_minutes for i in completed[:1000]]
    row, _ = WorkflowMetric.objects.get_or_create(
        owner=owner, definition=definition, metric_date=day
    )
    row.instances_started = instances.count()
    row.instances_completed = completed.count()
    row.instances_rejected = rejected.count()
    row.tasks_created = tasks_created.count()
    row.tasks_completed = tasks_completed.count()
    row.overdue_tasks = tasks_completed.filter(is_overdue=True).count()
    row.avg_duration_minutes = round(sum(durations) / len(durations), 2) if durations else 0.0
    row.save()
    return row


# ===========================================================================
# 八、执行引擎
# ===========================================================================


def generate_business_no(definition):
    """生成业务单号：WF-流程编码-日期-随机 6 位，撞号自动重试。"""
    import random

    for _ in range(12):
        suffix = f"{random.randint(0, 999999):06d}"
        candidate = f"WF-{definition.code[:20]}-{timezone.localdate():%Y%m%d}-{suffix}"
        if not WorkflowInstance.objects.filter(business_no=candidate).exists():
            return candidate
    raise ValueError("业务单号生成失败，请稍后重试")


def _pick_transition(node, instance, context=None):
    """按优先级选边：先看命中的条件分支，全部未命中再走默认分支。

    默认分支必须最后考虑——否则把默认边优先级设小就会「永远走默认」，
    这是设计器里最常见的坑。校验器只保证默认边最多一条，求值顺序在这里兜住。
    """
    edges = list(node.outgoing.select_related("to_node").order_by("priority", "id"))
    if not edges:
        raise ValueError(f"节点「{node.name}」没有可用出口")
    ctx = context if context is not None else build_context(instance)
    defaults = []
    for edge in edges:
        if edge.is_default:
            defaults.append(edge)
            continue
        if not edge.has_condition:
            return edge
        if edge.matches(ctx):
            return edge
    if defaults:
        return defaults[0]
    raise ValueError(f"节点「{node.name}」没有匹配的分支条件")


def _existing_open_task(instance, node, token):
    """同一令牌同一节点的未结任务（幂等：重复推进不会生成重复待办）。"""
    return instance.tasks.filter(
        node=node, token=token, status__in=TASK_OPEN
    ).order_by("id").first()


def create_task(instance, node, token, actor=None, parent_task=None,
                override_users=None, force_new=False, name_suffix=""):
    """在节点上创建人工任务：解析候选人 → 快照 → 定时器 → 通知 → 审计。

    单人候选人直接指派（claimed），多人留在待认领池；这符合「指定审批人」
    与「角色会签」两种常见诉求，也避免所有人都要点一次认领。
    """
    if not force_new:
        existing = _existing_open_task(instance, node, token)
        if existing is not None:
            return existing

    if override_users is not None:
        users = [u for u in override_users if u is not None]
        resolution = {
            "users": users,
            "user_ids": [u.id for u in users],
            "roles": [],
            "depts": [],
            "source": "manual",
            "warning": "",
        }
    else:
        resolution = resolve_assignees(node, instance)

    users = resolution["users"]
    assignee = users[0] if len(users) == 1 else None
    now = timezone.now()
    minutes = int(node.sla_minutes or 0) or instance.definition.default_sla_minutes()
    due_at = now + timedelta(minutes=minutes) if minutes > 0 else None
    name = f"{node.name}{name_suffix}"[:MAX_NAME_LENGTH]
    task = WorkflowTask.objects.create(
        instance=instance,
        node=node,
        token=token,
        owner=instance.owner,
        parent_task=parent_task,
        name=name,
        status="claimed" if assignee else "pending",
        assignee=assignee,
        candidate_users=resolution["user_ids"],
        candidate_roles=resolution["roles"],
        candidate_depts=resolution["depts"],
        assignee_source=resolution["source"],
        priority=instance.priority,
        due_at=due_at,
        claimed_at=now if assignee else None,
        payload={"assignee_warning": resolution["warning"]} if resolution["warning"] else {},
    )

    if due_at is not None and minutes >= 2:
        # 提醒点放在时限过半处，早于它扫到的任务还不该催
        remind_at = now + timedelta(minutes=max(int(minutes * 0.5), 1))
        WorkflowTimer.objects.create(
            instance=instance, task=task, owner=instance.owner,
            timer_type="remind", fire_at=remind_at, payload={"node_key": node.key},
        )
        WorkflowTimer.objects.create(
            instance=instance, task=task, owner=instance.owner,
            timer_type="timeout", fire_at=due_at, payload={"node_key": node.key},
        )

    instance.current_node = node
    instance.touch()
    instance.save(update_fields=["current_node", "last_activity_at", "updated_at"])

    log_audit(
        "task.created",
        instance=instance, task=task, actor=actor,
        to_status=task.status,
        detail={"node": node.key, "candidates": resolution["user_ids"],
                "source": resolution["source"], "due_at": due_at.isoformat() if due_at else ""},
    )
    title = f"新待办：{node.name}"
    content = f"流程「{instance.definition.name}」的 {instance.business_no} 已流转到 {node.name}"
    for user in users[:50]:
        push_notification(
            user, title, content, owner=instance.owner, instance=instance, task=task,
            dedup_key=f"task:{task.id}:created:{user.id}",
            payload={"link": f"/workflow/instances/{instance.id}"},
        )
    bump_metric(instance, "tasks_created")
    emit_event(instance, EVENT_TASK_CREATED,
               {"task_id": task.id, "node": node.key, "candidates": resolution["user_ids"]}, actor)
    return task


def snapshot_instance(instance, reason="manual", actor=None):
    """写实例快照：状态、令牌、任务、变量一次定格，供回放与排障。"""
    last_seq = instance.snapshots.aggregate(max_seq=Max("seq"))["max_seq"] or 0
    tokens = []
    for token in instance.tokens.order_by("id"):
        tokens.append({
            "id": token.id,
            "node_key": token.node.key if token.node_id else "",
            "status": token.status,
            "branch_label": token.branch_label,
            "generation": token.generation,
        })
    tasks = []
    for task in instance.tasks.order_by("id"):
        tasks.append({
            "id": task.id,
            "node_key": task.node.key if task.node_id else "",
            "name": task.name,
            "status": task.status,
            "assignee_id": task.assignee_id,
            "candidates": task.candidate_user_ids,
            "action": task.action,
            "comment": task.comment,
            "completed_at": task.completed_at.isoformat() if task.completed_at else "",
        })
    variables = {v.key: (v.typed_value if not v.is_secret else "******") for v in instance.variables.all()}
    state = {
        "instance": {
            "id": instance.id,
            "business_no": instance.business_no,
            "status": instance.status,
            "priority": instance.priority,
            "result": instance.result,
            "current_node_key": instance.current_node.key if instance.current_node_id else "",
            "context": instance.context or {},
            "due_at": instance.due_at.isoformat() if instance.due_at else "",
            "started_at": instance.started_at.isoformat() if instance.started_at else "",
            "finished_at": instance.finished_at.isoformat() if instance.finished_at else "",
        },
        "tokens": tokens,
        "tasks": tasks,
        "variables": variables,
        "stats": {
            "active_tokens": len([t for t in tokens if t["status"] == "active"]),
            "open_tasks": len([t for t in tasks if t["status"] in TASK_OPEN]),
        },
    }
    return WorkflowSnapshot.objects.create(
        instance=instance,
        owner=instance.owner,
        created_by=actor if getattr(actor, "pk", None) else None,
        seq=int(last_seq) + 1,
        reason=reason if reason in dict(WorkflowSnapshot._meta.get_field("reason").choices) else "manual",
        node_key=instance.current_node.key if instance.current_node_id else "",
        state=state,
        token_count=state["stats"]["active_tokens"],
        task_count=state["stats"]["open_tasks"],
        checksum=checksum_payload(state),
    )


def finalize_if_done(instance, actor=None):
    """完成判定：没有活跃令牌且没有未结任务 → 实例完成。

    并行汇聚等待中的令牌是 active，因此不会被误判为完成；这比「只看任务数」
    多一层保险（例如分支直接连到结束节点、没有任务的情况）。
    """
    if instance.status != "running":
        return False
    active_tokens = instance.tokens.filter(status="active").count()
    open_tasks = instance.tasks.filter(status__in=TASK_OPEN).count()
    if active_tokens or open_tasks:
        return False
    instance.finish("completed", "approved")
    instance.save(update_fields=["status", "result", "finished_at", "current_node",
                                 "last_activity_at", "updated_at"])
    log_audit(
        "instance.completed",
        instance=instance,
        actor=actor,
        from_status="running",
        to_status="completed",
        duration_ms=instance.duration_minutes * 60000,
        detail={"duration_minutes": instance.duration_minutes},
    )
    snapshot_instance(instance, "complete", actor)
    bump_metric(instance, "instances_completed")
    push_notification(
        instance.starter,
        "流程已完成",
        f"{instance.business_no}「{instance.title}」已完成",
        owner=instance.owner, instance=instance, level="success",
        dedup_key=f"instance:{instance.id}:completed",
        payload={"link": f"/workflow/instances/{instance.id}"},
    )
    emit_event(instance, EVENT_INSTANCE_COMPLETED,
               {"status": "completed", "duration_minutes": instance.duration_minutes}, actor)
    return True


def _move_forward(instance, token, node, actor=None, steps=0):
    """沿出边把令牌移动到下一节点，然后继续推进目标节点。"""
    context = build_context(instance)
    edge = _pick_transition(node, instance, context)
    source_key = node.key
    token.node = edge.to_node
    token.status = "active"
    token.consumed_at = None
    token.save(update_fields=["node", "status", "consumed_at", "updated_at"])
    instance.current_node = edge.to_node
    instance.touch()
    instance.save(update_fields=["current_node", "last_activity_at", "updated_at"])
    log_audit(
        "transition.taken",
        instance=instance,
        actor=actor,
        detail={"from": source_key, "to": edge.to_node.key,
                "label": edge.label, "condition": edge.condition[:200]},
    )
    return advance_token(instance, token, actor, steps + 1)


def _join_tokens(instance, token, node, actor=None, steps=0):
    """并行汇聚：等活跃令牌数达到入边数，再合并成一个令牌继续前进。"""
    active = list(instance.tokens.select_for_update().filter(node=node, status="active").order_by("id"))
    required = max(node.incoming.count(), 2)
    if len(active) < required:
        log_audit(
            "token.waiting",
            instance=instance,
            actor=actor,
            detail={"node": node.key, "arrived": len(active), "required": required},
        )
        return []
    survivor = active[0]
    for extra in active[1:]:
        extra.consume()
        extra.save(update_fields=["status", "consumed_at", "updated_at"])
    survivor.generation = int(survivor.generation or 0) + 1
    survivor.save(update_fields=["generation", "updated_at"])
    log_audit(
        "token.joined",
        instance=instance,
        actor=actor,
        detail={"node": node.key, "merged": len(active)},
    )
    return _move_forward(instance, survivor, node, actor, steps + 1)


def advance_token(instance, token, actor=None, steps=0):
    """推进令牌直到遇到等待点（任务/结束/并行汇聚未齐）。

    递归深度受 MAX_ADVANCE_STEPS 限制：纯网关环会让单次请求无限循环，
    校验器虽然会报错，运行期仍需兜底（例如运行中有人改了图）。
    """
    if steps > MAX_ADVANCE_STEPS:
        raise ValueError("流程推进步数过多，疑似存在没有等待点的环，请检查流程配置")
    node = token.node
    if node is None:
        token.consume()
        token.save(update_fields=["status", "consumed_at", "updated_at"])
        finalize_if_done(instance, actor)
        return []

    if node.node_type == "end":
        token.consume()
        token.save(update_fields=["status", "consumed_at", "updated_at"])
        instance.current_node = node
        instance.touch()
        instance.save(update_fields=["current_node", "last_activity_at", "updated_at"])
        log_audit("node.entered", instance=instance, actor=actor, to_status=node.key,
                  detail={"node": node.key, "name": node.name, "type": "end"})
        finalize_if_done(instance, actor)
        return []

    if node.node_type == "start":
        return _move_forward(instance, token, node, actor, steps)

    if node.node_type == "task":
        skip_if = str(node.config_value("skip_if") or "").strip()
        if skip_if:
            try:
                should_skip = evaluate_condition(skip_if, build_context(instance))
            except ValueError:
                should_skip = False
            if should_skip:
                log_audit("node.skipped", instance=instance, actor=actor, to_status=node.key,
                          detail={"node": node.key, "skip_if": skip_if})
                return _move_forward(instance, token, node, actor, steps)
        return [create_task(instance, node, token, actor)]

    if node.node_type == "decision":
        return _move_forward(instance, token, node, actor, steps)

    if node.node_type == "parallel_split":
        edges = list(node.outgoing.select_related("to_node").order_by("priority", "id"))
        if not edges:
            raise ValueError(f"并行拆分节点「{node.name}」没有出边")
        token.consume()
        token.save(update_fields=["status", "consumed_at", "updated_at"])
        children = []
        for index, edge in enumerate(edges):
            child = WorkflowToken.objects.create(
                instance=instance,
                node=edge.to_node,
                owner=instance.owner,
                status="active",
                parent=token,
                branch_label=(edge.label or edge.to_node.key)[:100],
                generation=int(token.generation or 0) + 1,
            )
            log_audit("token.forked", instance=instance, actor=actor,
                      detail={"from": node.key, "to": edge.to_node.key, "index": index})
            advance_token(instance, child, actor, steps + 1)
            children.append(child)
        return children

    if node.node_type == "parallel_join":
        return _join_tokens(instance, token, node, actor, steps)

    raise ValueError(f"未知节点类型：{node.node_type}")


def start_instance(definition, starter, title="", business_no="", business_key="",
                   context=None, priority="normal", variables=None, ip=""):
    """发起流程：校验发布态与发起权限 → 建实例/变量/起始令牌 → 推进到首个等待点。"""
    if definition.status != "published":
        raise ValueError("流程未发布，不能发起")
    if not can_start_definition(definition, starter):
        raise ValueError("您没有该流程的发起权限")
    entry = definition.entry_node()
    if entry is None:
        raise ValueError("流程缺少开始节点，无法发起")
    if context is not None and not isinstance(context, dict):
        raise ValueError("context 必须是对象")
    if priority not in ("low", "normal", "high", "urgent"):
        raise ValueError("priority 支持 low/normal/high/urgent")
    title = (title or definition.name)[:MAX_NAME_LENGTH]
    business_no = (business_no or "").strip()
    if business_no and WorkflowInstance.objects.filter(business_no=business_no).exists():
        raise ValueError(f"业务单号 {business_no} 已存在")
    if not business_no:
        business_no = generate_business_no(definition)

    with transaction.atomic():
        latest = definition.latest_version
        resolve_minutes = 0
        policy = definition.sla_policy
        if policy is not None and policy.active:
            resolve_minutes = int(policy.resolve_minutes or 0)
        instance = WorkflowInstance.objects.create(
            definition=definition,
            version=latest,
            owner=starter,
            starter=starter,
            business_no=business_no,
            business_key=(business_key or "")[:128],
            title=title,
            category=definition.category,
            status="running",
            current_node=entry,
            context=context or {},
            priority=priority,
            due_at=timezone.now() + timedelta(minutes=resolve_minutes) if resolve_minutes > 0 else None,
            started_at=timezone.now(),
            last_activity_at=timezone.now(),
        )
        _write_variables(instance, starter, variables)
        token = WorkflowToken.objects.create(
            instance=instance,
            node=entry,
            owner=starter,
            status="active",
            generation=0,
        )
        log_audit(
            "instance.started",
            instance=instance,
            actor=starter,
            to_status="running",
            detail={"definition": definition.code, "business_no": business_no,
                    "priority": priority, "node": entry.key},
            ip=ip,
        )
        snapshot_instance(instance, "start", starter)
        bump_metric(instance, "instances_started")
        push_notification(
            starter, "流程已发起",
            f"{business_no}「{title}」已进入流程",
            owner=starter, instance=instance,
            dedup_key=f"instance:{instance.id}:started",
            payload={"link": f"/workflow/instances/{instance.id}"},
        )
        emit_event(instance, EVENT_INSTANCE_STARTED,
                   {"business_no": business_no, "definition": definition.code}, starter)
        advance_token(instance, token, starter)
        instance.refresh_from_db()
    return instance


def claim_task(task_id, user, ip=""):
    """认领任务：仅待认领，且必须是候选人或管理员。"""
    with transaction.atomic():
        task = WorkflowTask.objects.select_for_update().select_related(
            "instance", "node", "assignee"
        ).filter(pk=task_id).first()
        if task is None:
            raise ValueError("任务不存在")
        instance = task.instance
        ensure_instance_visible(instance, user)
        if not instance.is_running:
            raise ValueError("流程实例已结束，不能认领任务")
        if task.status != "pending":
            raise ValueError("只有待认领任务可以认领")
        if task.assignee_id and task.assignee_id != user.id:
            raise ValueError("任务已被他人认领")
        if not task.can_be_operated_by(user):
            raise ValueError("您不是该任务的候选人")
        task.claim(user)
        task.save(update_fields=["assignee", "status", "claimed_at", "updated_at"])
        log_audit("task.claimed", instance=instance, task=task, actor=user,
                  from_status="pending", to_status="claimed", ip=ip)
    return task


def _close_sibling_tasks(instance, token, node, actor, exclude_task=None):
    """关闭同一令牌/节点下其它未结任务（拒绝/退回/取消时避免僵尸待办）。"""
    qs = instance.tasks.filter(token=token, node=node, status__in=TASK_OPEN)
    if exclude_task is not None:
        qs = qs.exclude(pk=exclude_task.pk)
    count = 0
    for task in qs:
        task.status = "cancelled"
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at", "updated_at"])
        count += 1
    return count


def _finish_instance(instance, status, result, actor, node=None, reason="", ip=""):
    """把实例推到终态，并统一取消令牌/任务/定时器、写快照与通知。"""
    from_status = instance.status
    now = timezone.now()
    for token in instance.tokens.filter(status="active"):
        token.cancel()
        token.save(update_fields=["status", "consumed_at", "updated_at"])
    for task in instance.tasks.filter(status__in=TASK_OPEN):
        task.status = "cancelled"
        task.completed_at = now
        task.save(update_fields=["status", "completed_at", "updated_at"])
    for timer in instance.timers.filter(status="scheduled"):
        timer.cancel()
        timer.save(update_fields=["status", "updated_at"])
    instance.finish(status, result or reason, node)
    instance.save(update_fields=["status", "result", "finished_at", "current_node",
                                 "last_activity_at", "updated_at"])
    log_audit(
        f"instance.{status}",
        instance=instance,
        actor=actor,
        from_status=from_status,
        to_status=status,
        detail={"reason": reason, "result": result},
        ip=ip,
    )
    snapshot_instance(instance, "cancel" if status == "cancelled" else
                      ("complete" if status == "completed" else "terminate"), actor)
    level = "success" if status == "completed" else "warning"
    push_notification(
        instance.starter,
        f"流程{instance.get_status_display()}",
        f"{instance.business_no}「{instance.title}」{instance.get_status_display()}"
        + (f"：{reason}" if reason else ""),
        owner=instance.owner, instance=instance, level=level,
        dedup_key=f"instance:{instance.id}:{status}",
        payload={"link": f"/workflow/instances/{instance.id}"},
    )
    emit_event(instance, f"instance.{status}",
               {"status": status, "reason": reason, "result": result}, actor)
    return instance


def complete_task(task_id, user, action="approve", comment="", payload=None,
                  target_node_key="", add_sign_user_ids=None, ip=""):
    """办理任务：同意 / 拒绝 / 退回 / 加签。

    状态机拦截：
    - 实例必须 running；任务必须 pending/claimed；重复完成直接 400；
    - 只有指派人或候选人可办（管理员除外）；
    - 节点开关（allow_reject/allow_return/allow_add_sign）决定动作是否可用；
    - require_comment 节点必须填意见。
    """
    if action not in ("approve", "reject", "return", "add_sign", "complete"):
        raise ValueError("action 支持 approve/reject/return/add_sign/complete")
    engine_error = ""
    with transaction.atomic():
        task = WorkflowTask.objects.select_for_update().select_related(
            "instance", "node", "assignee", "token"
        ).filter(pk=task_id).first()
        if task is None:
            raise ValueError("任务不存在")
        instance = WorkflowInstance.objects.select_for_update().get(pk=task.instance_id)
        task.instance = instance
        ensure_instance_visible(instance, user)
        if not instance.is_running:
            raise ValueError("流程实例已结束，不能继续办理")
        if task.status not in TASK_OPEN:
            raise ValueError("该任务已完成或已取消，不能重复办理")
        if not task.can_be_operated_by(user):
            raise ValueError("您不是该任务的办理人")
        node = task.node
        if node is None:
            raise ValueError("任务缺少关联节点，无法办理")
        if node.require_comment and not str(comment or "").strip():
            raise ValueError("该节点要求填写办理意见")
        if action == "reject" and not node.allow_reject:
            raise ValueError("该节点不允许拒绝")
        if action == "return" and not node.allow_return:
            raise ValueError("该节点不允许退回")
        if action == "add_sign" and not node.allow_add_sign:
            raise ValueError("该节点不允许加签")

        from_status = task.status
        # 候选池任务可能没有 assignee：办理时把操作人补记为实际办理人，
        # 否则「我的已办」和耗时统计会丢失这条记录。
        if task.assignee_id is None:
            task.assignee = user
            task.assignee_source = task.assignee_source or "candidate"
        task.action = action
        task.comment = str(comment or "")
        task.payload = payload if isinstance(payload, dict) else {}
        task.completed_at = timezone.now()
        task.status = "completed"
        task.save(update_fields=["assignee", "assignee_source", "action", "comment", "payload",
                                 "completed_at", "status", "updated_at"])
        log_audit(
            f"task.{action}",
            instance=instance,
            task=task,
            actor=user,
            from_status=from_status,
            to_status="completed",
            detail={"action": action, "comment": task.comment[:500], "node": node.key},
            duration_ms=task.duration_minutes * 60000,
            ip=ip,
        )
        bump_metric(instance, "tasks_completed")
        emit_event(instance, EVENT_TASK_COMPLETED,
                   {"task_id": task.id, "action": action, "node": node.key}, user)

        if action == "reject":
            _close_sibling_tasks(instance, task.token, node, user, exclude_task=task)
            _finish_instance(instance, "rejected", "rejected", user, node=node,
                             reason=comment or "办理人拒绝", ip=ip)
            bump_metric(instance, "instances_rejected")
            return instance

        if action == "return":
            target = _resolve_return_target(instance, node, target_node_key)
            _close_sibling_tasks(instance, task.token, node, user, exclude_task=task)
            token = task.token
            if token is None:
                raise ValueError("任务缺少令牌，无法退回")
            token.node = target
            token.status = "active"
            token.consumed_at = None
            token.save(update_fields=["node", "status", "consumed_at", "updated_at"])
            instance.current_node = target
            instance.touch()
            instance.save(update_fields=["current_node", "last_activity_at", "updated_at"])
            log_audit("task.returned", instance=instance, task=task, actor=user,
                      detail={"from": node.key, "to": target.key}, ip=ip)
            create_task(instance, target, token, user, force_new=True)
            snapshot_instance(instance, "task", user)
            return instance

        if action == "add_sign":
            add_users = _resolve_add_sign_users(add_sign_user_ids)
            if not add_users:
                raise ValueError("加签必须指定至少一名用户")
            if task.token is None:
                raise ValueError("任务缺少令牌，无法加签")
            for extra_user in add_users:
                create_task(
                    instance, node, task.token, user,
                    parent_task=task, override_users=[extra_user], force_new=True,
                    name_suffix=f"（{extra_user.display_name or extra_user.username} 加签）",
                )
            log_audit("task.add_sign", instance=instance, task=task, actor=user,
                      detail={"users": [u.id for u in add_users], "node": node.key}, ip=ip)
            snapshot_instance(instance, "task", user)
            return instance

        token = task.token
        if token is None:
            raise ValueError("任务缺少令牌，无法推进")
        other_open = instance.tasks.filter(
            token=token, node=node, status__in=TASK_OPEN
        ).exists()
        if other_open:
            # 加签场景：同节点还有别人的任务未办，令牌原地等待
            snapshot_instance(instance, "task", user)
            return instance
        try:
            _move_forward(instance, token, node, user)
            instance.refresh_from_db()
        except ValueError as exc:
            engine_error = str(exc)
            token.cancel()
            token.save(update_fields=["status", "consumed_at", "updated_at"])
            _finish_instance(instance, "terminated", "engine_error", user, node=node,
                             reason=f"流程推进失败：{exc}", ip=ip)
    if engine_error:
        raise ValueError(f"流程推进失败，实例已终止：{engine_error}")
    return instance


def _resolve_return_target(instance, node, target_node_key):
    """退回目标：显式指定优先；否则回退到上一个已办任务节点。"""
    target = None
    if target_node_key:
        target = instance.definition.nodes.filter(key=str(target_node_key)).first()
        if target is None:
            raise ValueError(f"退回目标节点 {target_node_key} 不存在")
        if target.node_type not in ("task", "decision"):
            raise ValueError("只能退回到任务节点或条件分支节点")
    else:
        previous = instance.tasks.filter(
            status="completed", node__isnull=False
        ).exclude(node_id=node.id).order_by("-completed_at", "-id").first()
        if previous is not None:
            target = previous.node
    if target is None:
        raise ValueError("找不到可退回的上一节点，请显式指定 target_node_key")
    if target.id == node.id:
        raise ValueError("不能退回到当前节点")
    return target


def _resolve_add_sign_users(add_sign_user_ids):
    """加签用户解析：支持 id 数组或单个 id。"""
    if add_sign_user_ids is None:
        return []
    if not isinstance(add_sign_user_ids, (list, tuple)):
        add_sign_user_ids = [add_sign_user_ids]
    users, seen = [], set()
    for raw in add_sign_user_ids:
        try:
            user = resolve_user(raw)
        except ValueError:
            continue
        if user.id in seen:
            continue
        seen.add(user.id)
        users.append(user)
    return users


def transfer_task(task_id, user, target, comment="", ip=""):
    """转办：把任务整体交给目标用户，候选集替换为目标（原办理人不再可见）。"""
    with transaction.atomic():
        task = WorkflowTask.objects.select_for_update().select_related("instance", "node").filter(pk=task_id).first()
        if task is None:
            raise ValueError("任务不存在")
        instance = task.instance
        ensure_instance_visible(instance, user)
        if not instance.is_running:
            raise ValueError("流程实例已结束，不能转办")
        if task.status not in TASK_OPEN:
            raise ValueError("该任务已完成或已取消")
        if not task.can_be_operated_by(user):
            raise ValueError("您不是该任务的办理人")
        if task.node is not None and not task.node.allow_transfer:
            raise ValueError("该节点不允许转办")
        target_user = resolve_user(target)
        if not getattr(target_user, "is_active", True):
            raise ValueError("目标用户已停用")
        if target_user.id == user.id:
            raise ValueError("不能转办给自己")
        task.assignee = target_user
        task.candidate_users = [target_user.id]
        task.status = "claimed"
        task.claimed_at = timezone.now()
        if comment:
            task.comment = str(comment)
        task.save(update_fields=["assignee", "candidate_users", "status", "claimed_at",
                                 "comment", "updated_at"])
        log_audit("task.transferred", instance=instance, task=task, actor=user,
                  detail={"to_user": target_user.id, "comment": str(comment)[:200]}, ip=ip)
        push_notification(
            target_user, f"任务转办：{task.name}",
            f"{instance.business_no} 的任务已转办给您" + (f"：{comment}" if comment else ""),
            owner=instance.owner, instance=instance, task=task,
            dedup_key=f"task:{task.id}:transfer:{target_user.id}",
        )
    return task


def delegate_task(task_id, user, target, comment="", ip=""):
    """委派：把任务交给他人处理，但保留原候选集（原办理人仍可接管）。"""
    with transaction.atomic():
        task = WorkflowTask.objects.select_for_update().select_related("instance", "node").filter(pk=task_id).first()
        if task is None:
            raise ValueError("任务不存在")
        instance = task.instance
        ensure_instance_visible(instance, user)
        if not instance.is_running:
            raise ValueError("流程实例已结束，不能委派")
        if task.status not in TASK_OPEN:
            raise ValueError("该任务已完成或已取消")
        if not task.can_be_operated_by(user):
            raise ValueError("您不是该任务的办理人")
        target_user = resolve_user(target)
        if target_user.id == user.id:
            raise ValueError("不能委派给自己")
        candidates = [int(x) for x in (task.candidate_users or []) if str(x).isdigit()]
        if target_user.id not in candidates:
            candidates.append(target_user.id)
        if user.id not in candidates:
            candidates.append(user.id)
        task.assignee = target_user
        task.candidate_users = candidates
        task.status = "claimed"
        task.claimed_at = timezone.now()
        task.save(update_fields=["assignee", "candidate_users", "status", "claimed_at", "updated_at"])
        log_audit("task.delegated", instance=instance, task=task, actor=user,
                  detail={"to_user": target_user.id, "comment": str(comment)[:200]}, ip=ip)
        push_notification(
            target_user, f"任务委派：{task.name}",
            f"{instance.business_no} 的任务已委派给您" + (f"：{comment}" if comment else ""),
            owner=instance.owner, instance=instance, task=task,
            dedup_key=f"task:{task.id}:delegate:{target_user.id}",
        )
    return task


def batch_complete(task_ids, user, action="approve", comment="", ip=""):
    """批量办理：逐条独立事务，单条失败不影响其它（返回成功/失败明细）。"""
    if not isinstance(task_ids, (list, tuple)) or not task_ids:
        raise ValueError("task_ids 必须是非空数组")
    if len(task_ids) > 100:
        raise ValueError("单次批量办理不能超过 100 条")
    completed, failed = [], []
    for raw in task_ids:
        try:
            task_pk = int(raw)
        except (TypeError, ValueError):
            failed.append({"task_id": raw, "error": "任务ID必须是整数"})
            continue
        try:
            instance = complete_task(task_pk, user, action=action, comment=comment, ip=ip)
            completed.append({"task_id": task_pk, "instance_id": instance.id,
                              "instance_status": instance.status})
        except ValueError as exc:
            failed.append({"task_id": task_pk, "error": str(exc)})
    return {"completed": completed, "failed": failed,
            "success_count": len(completed), "failed_count": len(failed)}


def cancel_instance(instance_id, user, reason="", ip=""):
    """取消实例：仅运行中，且只有发起人/所有者/管理员可取消。"""
    with transaction.atomic():
        instance = WorkflowInstance.objects.select_for_update().select_related(
            "owner", "starter", "definition"
        ).filter(pk=instance_id).first()
        if instance is None:
            raise ValueError("流程实例不存在")
        ensure_instance_visible(instance, user)
        if not instance.is_running:
            raise ValueError("仅运行中的实例可以取消")
        if not instance.can_be_cancelled_by(user):
            raise ValueError("只有发起人或管理员可以取消该实例")
        _finish_instance(instance, "cancelled", "cancelled", user, reason=reason, ip=ip)
    return instance


def terminate_instance(instance_id, user, reason="", ip=""):
    """终止实例：管理动作，仅流程所有者或管理员可执行。"""
    with transaction.atomic():
        instance = WorkflowInstance.objects.select_for_update().select_related(
            "owner", "starter", "definition"
        ).filter(pk=instance_id).first()
        if instance is None:
            raise ValueError("流程实例不存在")
        ensure_instance_visible(instance, user)
        if not instance.is_running:
            raise ValueError("仅运行中的实例可以终止")
        if not (is_staff_user(user) or instance.definition.owner_id == user.id):
            raise ValueError("只有流程所有者或管理员可以终止实例")
        if not str(reason or "").strip():
            raise ValueError("终止实例必须填写原因")
        _finish_instance(instance, "terminated", "terminated", user, reason=reason, ip=ip)
    return instance


# ===========================================================================
# 九、变量、评论、附件
# ===========================================================================


def _infer_var_type(value):
    """按 Python 值推断变量类型（发起时自动建变量）。"""
    if isinstance(value, bool):
        return "boolean"
    if _is_number(value):
        return "number"
    if isinstance(value, (dict, list)):
        return "json"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    return "string"


def _coerce_var_value(key, var_type, value):
    """按声明类型校验/转换变量值；不合法直接 400，避免坏值进入条件求值。"""
    if var_type not in dict(VARIABLE_TYPE_CHOICES):
        raise ValueError(f"变量 {key} 的类型 {var_type} 不受支持")
    if value is None:
        return None
    try:
        if var_type == "number":
            number = _numeric_like(value)
            if number is None:
                raise ValueError
            return number
        if var_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if var_type == "json":
            if isinstance(value, (dict, list)):
                return value
            return json.loads(str(value))
        if var_type == "date":
            return str(value)[:10]
        if var_type == "datetime":
            return str(value)[:19]
        return str(value)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError(f"变量 {key} 的值与类型 {var_type} 不匹配")


def _write_variables(instance, actor, variables):
    """批量写入变量（发起时调用）：支持 dict 或 [{key,value,type}]。"""
    rows = []
    if variables is None:
        return rows
    if isinstance(variables, dict):
        items = [{"key": key, "value": value} for key, value in variables.items()]
    elif isinstance(variables, list):
        items = variables
    else:
        raise ValueError("variables 必须是对象或数组")
    for item in items[:200]:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            raise ValueError("变量缺少 key")
        if not VARIABLE_KEY_PATTERN.match(key):
            raise ValueError(f"变量名 {key} 只能包含字母、数字、下划线与点，且不能以数字开头")
        var_type = item.get("var_type") or _infer_var_type(item.get("value"))
        value = _coerce_var_value(key, var_type, item.get("value"))
        rows.append(WorkflowVariable.objects.create(
            instance=instance,
            owner=actor,
            key=key,
            value=value,
            var_type=var_type,
            is_secret=bool(item.get("is_secret", False)),
        ))
    return rows


def set_variables(instance, user, variables):
    """运行期读写变量：仅运行中实例，key 合法、类型强校验，事务内 upsert。"""
    ensure_instance_visible(instance, user)
    if not instance.is_running:
        raise ValueError("流程已结束，不能修改变量")
    if isinstance(variables, dict):
        items = [{"key": key, "value": value} for key, value in variables.items()]
    elif isinstance(variables, list):
        items = variables
    else:
        raise ValueError("variables 必须是对象或数组")
    if len(items) > 200:
        raise ValueError("单次最多写入 200 个变量")
    saved = []
    with transaction.atomic():
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("variables 数组元素必须是对象")
            key = str(item.get("key") or "").strip()
            if not VARIABLE_KEY_PATTERN.match(key):
                raise ValueError(f"变量名 {key} 不合法")
            var_type = item.get("var_type")
            existing = WorkflowVariable.objects.filter(instance=instance, key=key).first()
            if var_type is None:
                var_type = existing.var_type if existing else _infer_var_type(item.get("value"))
            value = _coerce_var_value(key, var_type, item.get("value"))
            if existing is None:
                existing = WorkflowVariable.objects.create(
                    instance=instance, owner=instance.owner, key=key,
                    value=value, var_type=var_type,
                    is_secret=bool(item.get("is_secret", False)),
                )
            else:
                existing.value = value
                existing.var_type = var_type
                if "is_secret" in item:
                    existing.is_secret = bool(item.get("is_secret"))
                existing.save(update_fields=["value", "var_type", "is_secret", "updated_at"])
            saved.append({"key": key, "var_type": var_type,
                          "value": "******" if existing.is_secret else existing.typed_value})
        log_audit("instance.variables_updated", instance=instance, actor=user,
                  detail={"keys": [item["key"] for item in saved]})
        snapshot_instance(instance, "manual", user)
    return saved


def add_comment(instance, user, content, kind="comment", is_internal=False, task=None):
    """添加评论：非参与人不能发内部评论；内容不能为空。"""
    ensure_instance_visible(instance, user)
    content = str(content or "").strip()
    if not content:
        raise ValueError("评论内容不能为空")
    if len(content) > 10000:
        raise ValueError("评论内容不能超过 10000 字")
    if is_internal and not (is_staff_user(user) or is_participant(instance, user)):
        raise ValueError("只有流程参与人可以发表内部评论")
    if task is not None and task.instance_id != instance.id:
        raise ValueError("任务不属于该流程实例")
    comment = WorkflowComment.objects.create(
        instance=instance, task=task, owner=user, content=content,
        kind=kind if kind in ("comment", "decision", "system") else "comment",
        is_internal=bool(is_internal),
    )
    log_audit("instance.comment", instance=instance, task=task, actor=user,
              detail={"kind": comment.kind, "length": len(content)})
    return comment


def add_attachment(instance, user, name, url="", size=0, mime="", checksum="", kind="file", task=None):
    """登记附件元数据：文件本体由 files 应用负责，这里只做流程侧引用。"""
    ensure_instance_visible(instance, user)
    name = str(name or "").strip()
    if not name:
        raise ValueError("附件名称不能为空")
    try:
        size = int(size or 0)
    except (TypeError, ValueError):
        raise ValueError("附件大小必须是整数")
    if size < 0:
        raise ValueError("附件大小不能为负数")
    attachment = WorkflowAttachment.objects.create(
        instance=instance, task=task, owner=user, name=name[:200],
        url=str(url or "")[:500], size=size, mime=str(mime or "")[:100],
        checksum=str(checksum or "")[:64], kind=str(kind or "file")[:20],
    )
    log_audit("instance.attachment", instance=instance, task=task, actor=user,
              detail={"name": attachment.name, "size": size})
    return attachment


# ===========================================================================
# 十、SLA 扫描
# ===========================================================================


def scan_sla(user=None, now=None, limit=500):
    """SLA 扫描：逾期标记、临期提醒、定时器触发、实例超期标记。

    幂等性来源：
    - 任务逾期只翻转一次 is_overdue（已是 True 不再计数）；
    - 提醒类通知用 dedup_key 去重；
    - 定时器 triggered 后状态改 fired；
    - 实例超期用 audit_logs 中是否已有 instance.overdue 判定。
    """
    now = now or timezone.now()
    counts = {
        "scanned_tasks": 0, "newly_overdue": 0, "reminders": 0,
        "timers_fired": 0, "instances_flagged": 0, "notified": 0,
    }
    base_instances = WorkflowInstance.objects.filter(status="running")
    if user is not None:
        base_instances = instance_queryset_for(user, base_instances)
    instance_ids = list(base_instances.values_list("id", flat=True)[:3000])
    if not instance_ids:
        return counts

    tasks = list(WorkflowTask.objects.filter(
        instance_id__in=instance_ids, status__in=TASK_OPEN
    ).select_related("instance", "node", "assignee").order_by("due_at")[:limit])
    for task in tasks:
        counts["scanned_tasks"] += 1
        if task.due_at is None:
            continue
        if task.due_at <= now and not task.is_overdue:
            task.is_overdue = True
            task.save(update_fields=["is_overdue", "updated_at"])
            counts["newly_overdue"] += 1
            recipient = task.assignee or task.instance.starter
            push_notification(
                recipient, f"任务已逾期：{task.name}",
                f"{task.instance.business_no} 的任务已超过办理时限",
                owner=task.instance.owner, instance=task.instance, task=task,
                level="warning", dedup_key=f"overdue:task:{task.id}",
            )
            counts["notified"] += 1
            log_audit("task.overdue", instance=task.instance, task=task,
                      detail={"due_at": task.due_at.isoformat(),
                              "overdue_minutes": task.overdue_minutes})
            bump_metric(task.instance, "overdue_tasks")
            emit_event(task.instance, EVENT_TASK_OVERDUE,
                       {"task_id": task.id, "node": task.node.key if task.node_id else ""})
        elif not task.is_overdue and (task.due_at - now) <= timedelta(minutes=REMIND_WINDOW_MINUTES):
            before = WorkflowNotification.objects.filter(
                recipient=task.assignee or task.instance.starter,
                dedup_key=f"remind:task:{task.id}",
            ).exists()
            if not before:
                push_notification(
                    task.assignee or task.instance.starter,
                    f"任务即将到期：{task.name}",
                    f"{task.instance.business_no} 的任务将在 {REMIND_WINDOW_MINUTES} 分钟内到期",
                    owner=task.instance.owner, instance=task.instance, task=task,
                    level="warning", dedup_key=f"remind:task:{task.id}",
                )
                counts["reminders"] += 1

    timers = list(WorkflowTimer.objects.filter(
        instance_id__in=instance_ids, status="scheduled", fire_at__lte=now
    ).select_related("instance", "task", "task__assignee").order_by("fire_at")[:limit])
    for timer in timers:
        timer.mark_fired()
        timer.save(update_fields=["status", "fired_at", "attempts", "updated_at"])
        counts["timers_fired"] += 1
        instance = timer.instance
        task = timer.task
        recipient = (task.assignee if task is not None and task.assignee_id else instance.starter)
        title = "流程定时提醒" if timer.timer_type == "remind" else "流程任务超时升级"
        content = f"{instance.business_no} 的「{task.name if task else instance.title}」" \
                  f"触发 {timer.timer_type}"
        push_notification(
            recipient, title, content, owner=instance.owner, instance=instance, task=task,
            level="warning", dedup_key=f"timer:{timer.id}",
        )
        counts["notified"] += 1
        if timer.timer_type in ("timeout", "escalate") and task is not None and task.is_open:
            if not task.is_overdue:
                task.is_overdue = True
                task.save(update_fields=["is_overdue", "updated_at"])
                counts["newly_overdue"] += 1
            push_notification(
                instance.starter, f"任务超时升级：{task.name}",
                f"{instance.business_no} 的任务已超时，请关注处理进度",
                owner=instance.owner, instance=instance, task=task, level="danger",
                dedup_key=f"escalate:task:{task.id}",
            )
        log_audit("timer.fired", instance=instance, task=task,
                  detail={"timer_id": timer.id, "type": timer.timer_type})

    overdue_instances = base_instances.filter(due_at__lt=now)[:200]
    for instance in overdue_instances:
        if instance.audit_logs.filter(action="instance.overdue").exists():
            continue
        counts["instances_flagged"] += 1
        log_audit("instance.overdue", instance=instance,
                  detail={"due_at": instance.due_at.isoformat() if instance.due_at else "",
                          "duration_minutes": instance.duration_minutes})
        push_notification(
            instance.starter, "流程已超期",
            f"{instance.business_no}「{instance.title}」已超过预计完成时间",
            owner=instance.owner, instance=instance, level="warning",
            dedup_key=f"instance:{instance.id}:overdue",
        )
    return counts


# ===========================================================================
# 十一、指标与时间线
# ===========================================================================


def metrics_overview(user=None, definition_id=None, days=30):
    """指标概览：实例状态、完成率、平均耗时、任务健康度、SLA 达成率。"""
    days = min(max(int(days or 30), 1), 365)
    since = timezone.now() - timedelta(days=days)
    instances = WorkflowInstance.objects.filter(started_at__gte=since)
    if definition_id:
        instances = instances.filter(definition_id=definition_id)
    if user is not None:
        instances = instance_queryset_for(user, instances)
    status_counts = {row["status"]: row["c"] for row in instances.values("status").annotate(c=Count("id"))}
    total = sum(status_counts.values())
    completed = status_counts.get("completed", 0)
    rejected = status_counts.get("rejected", 0)
    running = status_counts.get("running", 0)
    durations = [i.duration_minutes for i in instances.filter(status="completed")[:1000]]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0

    tasks = WorkflowTask.objects.filter(instance__in=instances)
    task_total = tasks.count()
    task_completed = tasks.filter(status="completed").count()
    task_open = tasks.filter(status__in=TASK_OPEN).count()
    task_overdue = tasks.filter(status__in=TASK_OPEN, is_overdue=True).count()
    sla_base = tasks.filter(status="completed")
    sla_total = sla_base.count()
    sla_ok = sla_base.filter(is_overdue=False).count()
    handling = [t.duration_minutes for t in sla_base.select_related("node")[:1000]]
    priority_counts = {row["priority"]: row["c"] for row in instances.values("priority").annotate(c=Count("id"))}
    return {
        "window_days": days,
        "instances": {
            "total": total,
            "running": running,
            "completed": completed,
            "rejected": rejected,
            "cancelled": status_counts.get("cancelled", 0),
            "terminated": status_counts.get("terminated", 0),
            "by_status": status_counts,
            "by_priority": priority_counts,
            "completion_rate_pct": round(completed * 100.0 / total, 1) if total else 0.0,
            "reject_rate_pct": round(rejected * 100.0 / total, 1) if total else 0.0,
            "avg_duration_minutes": avg_duration,
            "overdue_running": instances.filter(status="running", due_at__lt=timezone.now()).count(),
        },
        "tasks": {
            "total": task_total,
            "open": task_open,
            "completed": task_completed,
            "overdue": task_overdue,
            "completion_rate_pct": round(task_completed * 100.0 / task_total, 1) if task_total else 0.0,
            "avg_handling_minutes": round(sum(handling) / len(handling), 1) if handling else 0.0,
            "sla_compliance_pct": round(sla_ok * 100.0 / sla_total, 1) if sla_total else 100.0,
        },
    }


def status_distribution(user=None, definition_id=None):
    """实例状态分布（含百分比）。"""
    qs = WorkflowInstance.objects.all()
    if definition_id:
        qs = qs.filter(definition_id=definition_id)
    if user is not None:
        qs = instance_queryset_for(user, qs)
    rows = list(qs.values("status").annotate(c=Count("id")).order_by())
    total = sum(r["c"] for r in rows) or 1
    return {
        "total": sum(r["c"] for r in rows),
        "items": [
            {"status": r["status"], "count": r["c"],
             "pct": round(r["c"] * 100.0 / total, 1)}
            for r in rows
        ],
    }


def category_distribution(user=None):
    """按流程分类统计实例数与完成率（监控大盘用）。"""
    qs = WorkflowInstance.objects.all()
    if user is not None:
        qs = instance_queryset_for(user, qs)
    rows = list(qs.values("category").annotate(
        total=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
        running=Count("id", filter=Q(status="running")),
    ).order_by("-total")[:50])
    return {
        "items": [
            {"category": r["category"] or "未分类", "total": r["total"],
             "completed": r["completed"], "running": r["running"],
             "completion_rate_pct": round(r["completed"] * 100.0 / r["total"], 1) if r["total"] else 0.0}
            for r in rows
        ],
        "count": len(rows),
    }


def node_bottlenecks(user=None, definition_id=None, days=90, limit=10):
    """节点瓶颈 TOP N：按平均办理时长排序，附带 P90、积压与逾期。

    为什么用 Python 聚合：SQLite/MySQL 对「完成时间-创建时间」的跨库聚合不一致，
    节点数量有限（单流程几十个），拉最近 5000 条任务在内存里算反而更稳、更准。
    """
    days = min(max(int(days or 90), 1), 365)
    since = timezone.now() - timedelta(days=days)
    tasks = WorkflowTask.objects.filter(
        status="completed", completed_at__gte=since, node__isnull=False
    ).select_related("node", "instance")
    if definition_id:
        tasks = tasks.filter(instance__definition_id=definition_id)
    if user is not None:
        tasks = tasks.filter(instance__in=instance_queryset_for(user))

    stats = {}
    for task in tasks[:5000]:
        key = task.node_id
        row = stats.setdefault(key, {
            "node_id": key,
            "node_key": task.node.key,
            "node_name": task.node.name,
            "node_type": task.node.node_type,
            "completed": 0,
            "durations": [],
            "overdue": 0,
        })
        row["completed"] += 1
        row["durations"].append(task.duration_minutes)
        if task.is_overdue:
            row["overdue"] += 1

    open_qs = WorkflowTask.objects.filter(status__in=TASK_OPEN, node__isnull=False)
    if definition_id:
        open_qs = open_qs.filter(instance__definition_id=definition_id)
    if user is not None:
        open_qs = open_qs.filter(instance__in=instance_queryset_for(user))
    for row in open_qs.values("node_id").annotate(
        backlog=Count("id"),
        overdue=Count("id", filter=Q(is_overdue=True)),
    ):
        target = stats.setdefault(row["node_id"], {
            "node_id": row["node_id"], "node_key": "", "node_name": "",
            "node_type": "", "completed": 0, "durations": [], "overdue": 0,
        })
        target["backlog"] = row["backlog"]
        target["open_overdue"] = row["overdue"]
        if not target["node_key"]:
            node = WorkflowNode.objects.filter(pk=row["node_id"]).first()
            if node is not None:
                target["node_key"] = node.key
                target["node_name"] = node.name
                target["node_type"] = node.node_type

    items = []
    for row in stats.values():
        durations = sorted(row["durations"])
        count = len(durations)
        total = sum(durations)
        p90 = durations[int(count * 0.9) - 1] if count else 0
        items.append({
            "node_id": row["node_id"],
            "node_key": row["node_key"],
            "node_name": row["node_name"],
            "node_type": row["node_type"],
            "completed": count,
            "backlog": row.get("backlog", 0),
            "overdue": row["overdue"],
            "open_overdue": row.get("open_overdue", 0),
            "avg_duration_minutes": round(total / count, 1) if count else 0,
            "p90_duration_minutes": p90,
            "max_duration_minutes": durations[-1] if durations else 0,
        })
    items.sort(key=lambda x: (x["avg_duration_minutes"], x["backlog"]), reverse=True)
    return {"window_days": days, "items": items[:min(max(int(limit or 10), 1), 50)],
            "count": len(items)}


def trend(user=None, definition_id=None, days=14):
    """趋势：逐日的发起/完成/拒绝/任务完成量（天数上限 90，避免 N+1 太多）。"""
    days = min(max(int(days or 14), 1), 90)
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    instances = WorkflowInstance.objects.filter(started_at__date__gte=start)
    if definition_id:
        instances = instances.filter(definition_id=definition_id)
    if user is not None:
        instances = instance_queryset_for(user, instances)
    items = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        started = instances.filter(started_at__date=day).count()
        completed = instances.filter(status="completed", finished_at__date=day).count()
        rejected = instances.filter(status="rejected", finished_at__date=day).count()
        tasks_done = WorkflowTask.objects.filter(
            instance__in=instances, status="completed", completed_at__date=day
        ).count()
        items.append({
            "date": day.isoformat(),
            "started": started,
            "completed": completed,
            "rejected": rejected,
            "tasks_completed": tasks_done,
        })
    return {"window_days": days, "items": items, "count": len(items)}


def build_timeline(instance, limit=300):
    """实例时间线：审计日志为主干，叠加评论、通知与快照。

    审计已经记录任务创建/完成/流转，所以不再重复拼任务事件；
    评论与通知是审计之外的「人」与「消息」维度，必须单独补上。
    """
    events = []
    for log in instance.audit_logs.select_related("actor", "task")[:limit]:
        events.append({
            "at": log.created_at.isoformat(),
            "kind": "audit",
            "action": log.action,
            "title": _audit_title(log),
            "actor": log.actor_name,
            "from_status": log.from_status,
            "to_status": log.to_status,
            "detail": log.detail or {},
            "task_id": log.task_id,
            "duration_ms": log.duration_ms,
        })
    for comment in instance.comments.select_related("owner")[:100]:
        events.append({
            "at": comment.created_at.isoformat(),
            "kind": "comment",
            "action": "comment",
            "title": f"{comment.author_name}：{comment.content[:80]}",
            "actor": comment.author_name,
            "detail": {"content": comment.content, "internal": comment.is_internal,
                       "comment_kind": comment.kind},
        })
    for notification in instance.notifications.select_related("recipient")[:100]:
        events.append({
            "at": (notification.sent_at or notification.created_at).isoformat(),
            "kind": "notification",
            "action": "notification",
            "title": notification.title,
            "actor": getattr(notification.recipient, "display_name", "") or "",
            "detail": {"channel": notification.channel, "status": notification.status,
                       "level": notification.level},
        })
    for snapshot in instance.snapshots.all()[:50]:
        events.append({
            "at": snapshot.created_at.isoformat(),
            "kind": "snapshot",
            "action": "snapshot",
            "title": f"快照 #{snapshot.seq}（{snapshot.get_reason_display()}）",
            "actor": getattr(snapshot.created_by, "display_name", "") if snapshot.created_by_id else "系统",
            "detail": {"seq": snapshot.seq, "node_key": snapshot.node_key,
                       "checksum": snapshot.checksum},
        })
    events.sort(key=lambda e: e["at"], reverse=True)
    return {"items": events[:limit], "count": len(events[:limit]), "instance_id": instance.id}


def _audit_title(log):
    """把审计动作翻成一句人话（时间线展示用）。"""
    mapping = {
        "instance.started": "发起流程",
        "instance.completed": "流程完成",
        "instance.rejected": "流程被拒绝",
        "instance.cancelled": "流程已取消",
        "instance.terminated": "流程已终止",
        "instance.overdue": "流程超期",
        "instance.comment": "新增评论",
        "instance.attachment": "新增附件",
        "instance.variables_updated": "更新变量",
        "task.created": "生成待办",
        "task.claimed": "认领任务",
        "task.approve": "同意",
        "task.complete": "完成",
        "task.reject": "拒绝",
        "task.return": "退回",
        "task.add_sign": "加签",
        "task.transferred": "转办",
        "task.delegated": "委派",
        "task.overdue": "任务逾期",
        "task.returned": "任务已退回",
        "token.forked": "并行分支",
        "token.joined": "并行汇聚",
        "token.waiting": "等待并行分支",
        "transition.taken": "节点流转",
        "node.entered": "到达节点",
        "node.skipped": "跳过节点",
        "timer.fired": "定时器触发",
        "definition.published": "发布版本",
        "definition.rolled_back": "回滚版本",
        "definition.cloned": "克隆流程",
        "definition.imported": "导入流程",
    }
    detail = log.detail or {}
    base = mapping.get(log.action, log.action)
    if log.action == "transition.taken":
        return f"{base}：{detail.get('from', '')} → {detail.get('to', '')}"
    if log.action in ("task.approve", "task.reject", "task.return", "task.add_sign"):
        return f"{base}（{detail.get('node', '')}）"
    return base


def replay_instance(instance):
    """回放：按 seq 升序返回快照帧，最后一帧即当前（近似）状态。"""
    frames = []
    for snapshot in instance.snapshots.order_by("seq", "id"):
        frames.append({
            "seq": snapshot.seq,
            "reason": snapshot.reason,
            "node_key": snapshot.node_key,
            "checksum": snapshot.checksum,
            "created_at": snapshot.created_at.isoformat(),
            "state": snapshot.state or {},
        })
    return {
        "instance_id": instance.id,
        "business_no": instance.business_no,
        "status": instance.status,
        "frames": frames,
        "count": len(frames),
        "first_at": frames[0]["created_at"] if frames else "",
        "last_at": frames[-1]["created_at"] if frames else "",
    }


# ===========================================================================
# 十二、委托、通知、Webhook、SLA 策略
# ===========================================================================


def create_delegation(owner, to_user, start_at=None, end_at=None, definition=None,
                      scope="all", reason=""):
    """创建委托：窗口合法、不能委托给自己、同一受托人不允许重复生效中。"""
    if to_user.id == owner.id:
        raise ValueError("不能委托给自己")
    if not getattr(to_user, "is_active", True):
        raise ValueError("受托人已停用")
    start_at = start_at or timezone.now()
    if end_at is None:
        raise ValueError("委托必须有结束时间")
    if end_at <= start_at:
        raise ValueError("委托结束时间必须晚于开始时间")
    if scope not in ("all", "definition", "tasks"):
        raise ValueError("scope 支持 all/definition/tasks")
    if scope == "definition" and definition is None:
        raise ValueError("按流程委托时必须指定 definition_id")
    existing = WorkflowDelegation.objects.filter(
        owner=owner, to_user=to_user, status="active"
    )
    for row in existing:
        if row.is_active and row.covers(definition):
            raise ValueError("已存在生效中的委托，请先撤销")
    delegation = WorkflowDelegation.objects.create(
        owner=owner, from_user=owner, to_user=to_user, definition=definition,
        scope=scope, start_at=start_at, end_at=end_at, status="active",
        reason=str(reason or "")[:2000],
    )
    log_audit("delegation.created", actor=owner,
              detail={"to_user": to_user.id, "scope": scope,
                      "definition_id": definition.id if definition else None})
    push_notification(
        to_user, "您收到一条任务委托",
        f"{getattr(owner, 'display_name', owner.username)} 将任务委托给您（至 {end_at:%Y-%m-%d %H:%M}）",
        owner=owner, dedup_key=f"delegation:{delegation.id}:created",
    )
    return delegation


def revoke_delegation(delegation, user):
    """撤销委托：仅委托人本人或管理员。"""
    if delegation.from_user_id != user.id and not is_staff_user(user):
        raise ValueError("只有委托人本人可以撤销委托")
    if delegation.status != "active":
        raise ValueError("该委托已撤销或已过期")
    delegation.status = "revoked"
    delegation.save(update_fields=["status", "updated_at"])
    log_audit("delegation.revoked", actor=user,
              detail={"delegation_id": delegation.id, "to_user": delegation.to_user_id})
    push_notification(
        delegation.to_user, "任务委托已撤销",
        f"{getattr(user, 'display_name', user.username)} 撤销了委托",
        owner=user, dedup_key=f"delegation:{delegation.id}:revoked",
    )
    return delegation


def create_webhook(owner, name, url, events=None, definition=None, secret=""):
    """创建 Webhook 订阅：仅接受 http(s) 地址，事件白名单不限制（支持通配）。"""
    name = str(name or "").strip()
    url = str(url or "").strip()
    if not name:
        raise ValueError("Webhook 名称不能为空")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("Webhook 地址必须是 http(s) 链接")
    if len(url) > 500:
        raise ValueError("Webhook 地址过长")
    if events is not None and not isinstance(events, list):
        raise ValueError("events 必须是数组")
    return WorkflowWebhook.objects.create(
        owner=owner, definition=definition, name=name[:120], url=url,
        events=[str(x) for x in (events or [])][:50], secret=str(secret or "")[:64],
        active=True,
    )


def create_sla_policy(owner, code, name, priority="normal", response_minutes=240,
                      resolve_minutes=1440, business_hours=True, escalate_to="manager",
                      description=""):
    """创建 SLA 策略：编码唯一、时限为正、优先级在白名单内。"""
    code = str(code or "").strip()
    name = str(name or "").strip()
    if not code:
        raise ValueError("策略编码不能为空")
    if not name:
        raise ValueError("策略名称不能为空")
    if priority not in ("low", "normal", "high", "urgent"):
        raise ValueError("priority 支持 low/normal/high/urgent")
    if WorkflowSlaPolicy.objects.filter(owner=owner, code=code).exists():
        raise ValueError(f"策略编码 {code} 已存在")
    try:
        response_minutes = int(response_minutes)
        resolve_minutes = int(resolve_minutes)
    except (TypeError, ValueError):
        raise ValueError("时限必须是整数分钟")
    if response_minutes <= 0 or resolve_minutes <= 0:
        raise ValueError("时限必须大于 0")
    if resolve_minutes < response_minutes:
        raise ValueError("解决时限不能早于响应时限")
    return WorkflowSlaPolicy.objects.create(
        owner=owner, code=code[:40], name=name[:120], priority=priority,
        response_minutes=response_minutes, resolve_minutes=resolve_minutes,
        business_hours=bool(business_hours), escalate_to=str(escalate_to or "manager")[:20],
        description=str(description or ""),
    )


def mark_notifications_read(recipient, ids=None):
    """批量标记已读：不传 ids 时把该用户全部未读置为已读，返回受影响条数。"""
    qs = WorkflowNotification.objects.filter(recipient=recipient).exclude(status="read")
    if ids:
        try:
            id_list = [int(x) for x in ids]
        except (TypeError, ValueError):
            raise ValueError("ids 必须是整数数组")
        qs = qs.filter(pk__in=id_list)
    count = 0
    for notification in qs[:500]:
        notification.mark_read()
        notification.save(update_fields=["status", "read_at", "updated_at"])
        count += 1
    return count


def definition_stats(definition):
    """单个流程的运行统计：状态分布、耗时、积压、近 30 天发起量。"""
    instances = definition.instances.all()
    status_counts = {row["status"]: row["c"] for row in instances.values("status").annotate(c=Count("id"))}
    completed = instances.filter(status="completed")
    durations = [i.duration_minutes for i in completed[:1000]]
    since = timezone.now() - timedelta(days=30)
    tasks = WorkflowTask.objects.filter(instance__definition=definition)
    node_rows = list(tasks.filter(status__in=TASK_OPEN, node__isnull=False).values(
        "node__key", "node__name").annotate(backlog=Count("id")).order_by("-backlog")[:10])
    return {
        "definition_id": definition.id,
        "total": sum(status_counts.values()),
        "by_status": status_counts,
        "running": status_counts.get("running", 0),
        "completion_rate_pct": round(status_counts.get("completed", 0) * 100.0 /
                                     max(sum(status_counts.values()), 1), 1),
        "avg_duration_minutes": round(sum(durations) / len(durations), 1) if durations else 0,
        "last_30d_started": instances.filter(started_at__gte=since).count(),
        "open_tasks": tasks.filter(status__in=TASK_OPEN).count(),
        "overdue_tasks": tasks.filter(status__in=TASK_OPEN, is_overdue=True).count(),
        "backlog_by_node": [
            {"node_key": r["node__key"], "node_name": r["node__name"], "backlog": r["backlog"]}
            for r in node_rows
        ],
        "validation": validate_definition(definition)["stats"],
    }
