# -*- coding: utf-8 -*-
"""功能开关与实验 · 服务层（唯一业务真相）。

视图只做「取参 → 权限 → 调用 → 渲染」，所有会出现在多个接口里的规则都在
这里实现：确定性分桶、条件求值、定向匹配、细分判定、灰度放量、实验入组、
曝光幂等、实验结果统计、依赖解析、护栏处置、评估缓存与审计。

章节
----
1. 基础工具        —— 键名、百分比、布尔、JSON、时间的安全解析
2. 确定性分桶      —— sha256(flag_key + user_key + salt) → 0..9999
3. 条件求值        —— 14 个操作符 + user./custom. 字段解析
4. 细分判定        —— Segment.rules 与 SegmentRule 行的 and/or 组合
5. 变体选择        —— 权重分桶，输入相同结果永远相同
6. 定向规则        —— 按优先级命中并返回变体
7. 灰度发布        —— 百分比 + 细分 + 时间窗口
8. 依赖解析        —— requires/forbids，带环检测与深度上限
9. 实验分配        —— 稳定入组 + 曝光幂等
10. 实验结果       —— 转化率、lift、卡方检验、样本量
11. 护栏            —— 阈值比较与动作处置
12. 开关评估       —— 完整链路、评估日志、缓存
13. 版本快照       —— 发布/回滚
14. 统计           —— 评估量、命中率、变体分布、趋势、看板

为什么强调「确定性」
--------------------
灰度与实验最怕同一个用户在两次请求里看到不同结果：用户会认为功能时好时坏，
实验数据也会被污染。因此所有分桶都只依赖 ``sha256`` 的哈希值，不做
``random()``、不依赖数据库自增顺序，也不把当前时间放进哈希输入。时间只用于
判断生效窗口，不影响桶值。
"""
import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.scoping import can_write, is_visible, scope_queryset

from flags.models import (
    DEFAULT_EXPERIMENT_VARIANTS,
    DEPENDENCY_RELATIONS,
    ENV_TYPES,
    EVALUATION_LOG_KEEP,
    EXPERIMENT_STATUS,
    FLAG_STATUS,
    FLAG_TYPES,
    GUARDRAIL_ACTIONS,
    LOGIC_OPS,
    METRIC_DIRECTIONS,
    METRIC_TYPES,
    OPERATORS,
    PROJECT_STATUS,
    ROLLOUT_STATUS,
    Assignment,
    AuditEvent,
    Audience,
    Environment,
    EvaluationLog,
    Experiment,
    ExperimentMetric,
    Exposure,
    Flag,
    FlagDependency,
    FlagVersion,
    Guardrail,
    Project,
    Rollout,
    Segment,
    SegmentRule,
    TargetingRule,
    Variant,
)

# ---------------------------------------------------------------------------
# 1. 基础工具
# ---------------------------------------------------------------------------

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,119}$")
BUCKET_SPACE = 10000
MAX_CONTEXT_BYTES = 64 * 1024
MAX_DEPENDENCY_DEPTH = 8
CACHE_TTL_SECONDS = 60
CACHE_LIMIT = 4096

_CACHE = {}
_LOG_WRITE_COUNTER = 0
_LOG_TRIM_EVERY = 50


def now():
    """当前时区时间：所有状态机判断都走这里，测试可用 timezone 冻结。"""
    return timezone.now()


def local_today():
    return timezone.localdate()


def parse_key(value, field="标识"):
    """校验并归一化键名（小写、字母数字与 ._-）。"""
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError(f"{field}不能为空")
    if not KEY_RE.match(text):
        raise ValueError(f"{field}只能包含小写字母、数字、点、下划线和短横线，且以字母或数字开头")
    return text


def parse_choice(value, allowed, field, default=None):
    """枚举校验：非法值直接中文报错，避免脏数据落入数据库。"""
    text = str(value if value is not None else (default or "")).strip()
    if text not in allowed:
        raise ValueError(f"{field}必须是 {'/'.join(allowed)} 之一")
    return text


def parse_percent(value, field="百分比", default=0):
    """百分比：整数 0..100。允许传浮点但四舍五入，保持分桶边界可复现。"""
    if value in (None, ""):
        return int(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是数字")
    if not math.isfinite(number):
        raise ValueError(f"{field}必须是有限数字")
    if number < 0 or number > 100:
        raise ValueError(f"{field}必须在 0 到 100 之间")
    return int(round(number))


def parse_bool(value, field="布尔值", default=False):
    """宽松布尔解析，兼容 1/0/true/false/yes/no/on/off。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "y"):
        return True
    if text in ("0", "false", "no", "off", "n", ""):
        return False
    raise ValueError(f"{field}必须是布尔值")


def parse_int(value, field="数值", default=None, minimum=None, maximum=None):
    """安全整数解析：拒绝 NaN/Infinity，越界抛中文错误。"""
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field}必须是整数")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是整数")
    if not math.isfinite(number):
        raise ValueError(f"{field}必须是有限数字")
    number = int(round(number))
    if minimum is not None and number < minimum:
        raise ValueError(f"{field}不能小于 {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field}不能大于 {maximum}")
    return number


def parse_float(value, field="数值", default=None, minimum=None, maximum=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}必须是数字")
    if not math.isfinite(number):
        raise ValueError(f"{field}必须是有限数字")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field}不能小于 {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field}不能大于 {maximum}")
    return number


def parse_json(value, field="JSON", default=None):
    """JSON 参数：既接受已解析对象，也接受 JSON 字符串。"""
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(f"{field}不是合法 JSON")
    raise ValueError(f"{field}类型不支持")


def parse_datetime(value, field="时间", default=None):
    """ISO 8601 时间解析；空值返回默认值。"""
    if value in (None, ""):
        return default
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(f"{field}格式必须是 ISO 8601（如 2026-01-01T00:00:00）")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def clamp(value, low, high):
    return max(low, min(high, value))


def normalize_labels(value):
    """标签归一化为字符串列表，去重且保留顺序。"""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        raw = [part.strip() for part in value.replace("，", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(part).strip() for part in value]
    else:
        raise ValueError("标签必须是数组或逗号分隔字符串")
    out = []
    for item in raw:
        if item and item not in out:
            out.append(item[:60])
    if len(out) > 50:
        raise ValueError("标签最多 50 个")
    return out


def context_digest(context):
    """上下文指纹：排序键后序列化，保证同一上下文哈希稳定。"""
    try:
        raw = json.dumps(context or {}, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = repr(context)
    if len(raw.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("评估上下文过大（上限 64KB）")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def normalize_context(user_key, context=None):
    """把外部上下文补成求值器可直接使用的结构。

    约定 ``user.*`` 优先从 context["user"] 取，未提供时回退到扁平键；
    这里把 user_key 注入 user.id，调用方只需要传用户键就能命中 ``user.id``。
    """
    key = str(user_key or "").strip()
    if not key:
        raise ValueError("用户键不能为空")
    ctx = dict(context or {}) if isinstance(context, dict) else {}
    user = ctx.get("user")
    user = dict(user) if isinstance(user, dict) else {}
    user.setdefault("id", key)
    user.setdefault("key", key)
    ctx["user"] = user
    ctx.setdefault("user_key", key)
    return ctx


# ---------------------------------------------------------------------------
# 2. 确定性分桶
# ---------------------------------------------------------------------------


def stable_digest(*parts):
    """把若干片段拼成稳定摘要（分隔符避免 "ab"+"c" 与 "a"+"bc" 撞车）。"""
    text = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bucket_of(*parts):
    """映射到 0..9999 的桶。

    用 10000 而不是 100：百分比接口只暴露整数，但未来支持 0.1% 放量时
    不需要改哈希空间，也就不会让存量用户重新洗牌。
    """
    digest = stable_digest(*parts)
    return int(digest[:16], 16) % BUCKET_SPACE


def bucket_for_flag(flag_key, user_key, salt=""):
    return bucket_of("flag", flag_key, user_key, salt or "")


def percentage_hit(flag_key, user_key, salt, percentage):
    """百分比判定：桶值 < 百分比 × 100。0% 恒不命中，100% 恒命中。"""
    percent = clamp(int(percentage), 0, 100)
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return bucket_for_flag(flag_key, user_key, salt) < percent * 100


def bucket_ratio(flag_key, user_key, salt=""):
    """桶值对应的比例（0..1），解释接口用于展示「为什么没放量到你」。"""
    return round(bucket_for_flag(flag_key, user_key, salt) / float(BUCKET_SPACE), 4)


# ---------------------------------------------------------------------------
# 3. 条件求值
# ---------------------------------------------------------------------------


def parse_semver(value):
    """解析语义化版本为可比较元组；非法版本抛 ValueError。

    只比较主/次/修订三段，忽略预发布标签：开关平台用它判断 App 版本，
    不需要完整 semver 优先级（不同实现差异反而制造歧义）。
    """
    text = str(value or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    if not text:
        raise ValueError("版本号不能为空")
    parts = text.split(".")
    if len(parts) > 4:
        raise ValueError(f"版本号格式非法: {value}")
    numbers = []
    for part in parts[:3]:
        head = re.split(r"[+-]", part, maxsplit=1)[0]
        if not head.isdigit():
            raise ValueError(f"版本号格式非法: {value}")
        numbers.append(int(head))
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def coerce_number(value):
    """数值比较：字符串数字也允许比较；不可比较时返回 None。"""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def loose_equal(actual, expected):
    """宽松相等：布尔/数字/字符串跨类型也能比较，减少脏上下文造成的误判。"""
    if actual is None and expected is not None:
        # 缺失字段不等于 false/0：否则「未上报 country」会被误判成国家为空串
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        try:
            return parse_bool(actual, "取值", False) == parse_bool(expected, "期望值", False)
        except ValueError:
            return False
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, (int, float)) or isinstance(expected, (int, float)):
        a = coerce_number(actual)
        b = coerce_number(expected)
        if a is not None and b is not None:
            return abs(a - b) < 1e-9
    return str(actual) == str(expected)


def resolve_field(context, field):
    """按字段名从上下文取值。

    支持：
    - user.id / user.email / user.country / user.plan / user.任何属性
    - custom.* 自定义属性
    - 扁平字段或 a.b.c 点路径
    """
    name = str(field or "").strip()
    if not name:
        return None
    ctx = context or {}
    if name.startswith("user."):
        rest = name[5:]
        user = ctx.get("user")
        if isinstance(user, dict) and rest in user:
            return user.get(rest)
        # 兼容上层直接传 user_id 一类的扁平键
        for candidate in (rest, f"user_{rest}"):
            if candidate in ctx:
                return ctx.get(candidate)
        return None
    if name.startswith("custom."):
        rest = name[7:]
        custom = ctx.get("custom")
        if isinstance(custom, dict):
            return custom.get(rest)
        return None
    if name in ctx:
        return ctx.get(name)
    cursor = ctx
    for part in name.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor.get(part)
        else:
            return None
    return cursor


def evaluate_condition(condition, context):
    """求值单个条件；配置错误抛 ValueError，求值异常按「不命中」处理。"""
    if not isinstance(condition, dict):
        raise ValueError("条件必须是对象")
    field = str(condition.get("field") or "").strip()
    operator = str(condition.get("operator") or "eq").strip()
    if not field:
        raise ValueError("条件缺少字段 field")
    if operator not in OPERATORS:
        raise ValueError(f"不支持的操作符: {operator}")
    expected = condition.get("value")
    actual = resolve_field(context, field)

    if operator == "eq":
        return loose_equal(actual, expected)
    if operator == "neq":
        return not loose_equal(actual, expected)
    if operator in ("in", "not_in"):
        if not isinstance(expected, (list, tuple, set)):
            raise ValueError("in / not_in 的 value 必须是数组")
        hit = any(loose_equal(actual, item) for item in expected)
        return hit if operator == "in" else not hit
    if operator == "contains":
        if actual is None:
            return False
        if isinstance(actual, (list, tuple, set)):
            return any(loose_equal(item, expected) for item in actual)
        return str(expected) in str(actual)
    if operator == "starts_with":
        return actual is not None and str(actual).startswith(str(expected))
    if operator == "ends_with":
        return actual is not None and str(actual).endswith(str(expected))
    if operator in ("gt", "gte", "lt", "lte"):
        a = coerce_number(actual)
        b = coerce_number(expected)
        if a is None or b is None:
            return False
        if operator == "gt":
            return a > b
        if operator == "gte":
            return a >= b
        if operator == "lt":
            return a < b
        return a <= b
    if operator == "regex":
        if actual is None:
            return False
        try:
            return re.search(str(expected), str(actual)) is not None
        except re.error:
            return False
    if operator in ("semver_gte", "semver_lt"):
        try:
            left = parse_semver(actual)
            right = parse_semver(expected)
        except ValueError:
            return False
        return left >= right if operator == "semver_gte" else left < right
    return False


def validate_condition(condition):
    """配置期校验：把正则/数组/版本这类错误提前到保存时暴露。"""
    if not isinstance(condition, dict):
        raise ValueError("条件必须是对象")
    field = str(condition.get("field") or "").strip()
    operator = str(condition.get("operator") or "eq").strip()
    if not field:
        raise ValueError("条件缺少字段 field")
    if operator not in OPERATORS:
        raise ValueError(f"不支持的操作符: {operator}")
    value = condition.get("value")
    if operator in ("in", "not_in") and not isinstance(value, (list, tuple, set)):
        raise ValueError("in / not_in 的 value 必须是数组")
    if operator == "regex":
        try:
            re.compile(str(value))
        except re.error:
            raise ValueError("正则表达式非法")
    if operator in ("semver_gte", "semver_lt"):
        parse_semver(value)
    return condition


def normalize_conditions(raw, logic="and"):
    """把多种条件写法归一到 (logic, [condition])。

    支持 ``[cond]``、``{"all": [...]}``、``{"any": [...]}``、
    ``{"logic": "or", "conditions": [...]}`` 以及单个条件对象。
    """
    mode = str(logic or "and").strip().lower()
    if mode not in LOGIC_OPS:
        raise ValueError("条件组合必须是 and 或 or")
    if raw in (None, "", []):
        return mode, []
    if isinstance(raw, dict):
        if "conditions" in raw:
            mode = str(raw.get("logic") or mode).lower()
            if mode not in LOGIC_OPS:
                raise ValueError("条件组合必须是 and 或 or")
            return normalize_conditions(raw.get("conditions") or [], mode)
        if "all" in raw:
            return "and", list(raw.get("all") or [])
        if "any" in raw:
            return "or", list(raw.get("any") or [])
        return mode, [raw]
    if isinstance(raw, list):
        return mode, list(raw)
    raise ValueError("条件必须是数组或对象")


def evaluate_conditions(raw, context, logic="and"):
    """条件集合求值；空集合视为命中（没有限制就是全量）。"""
    mode, conditions = normalize_conditions(raw, logic)
    if not conditions:
        return True
    results = []
    for condition in conditions:
        try:
            results.append(evaluate_condition(condition, context))
        except ValueError:
            # 脏规则不该让整个评估接口 500：按不命中记录，排障时看解释接口。
            results.append(False)
    return all(results) if mode == "and" else any(results)


def explain_conditions(raw, context, logic="and"):
    """逐条返回条件命中情况，解释接口与细分预览共用。"""
    mode, conditions = normalize_conditions(raw, logic)
    rows = []
    for index, condition in enumerate(conditions):
        actual = resolve_field(context, condition.get("field") if isinstance(condition, dict) else None)
        try:
            matched = evaluate_condition(condition, context)
            error = ""
        except ValueError as exc:
            matched = False
            error = str(exc)
        rows.append({
            "index": index,
            "field": (condition or {}).get("field", "") if isinstance(condition, dict) else "",
            "operator": (condition or {}).get("operator", "") if isinstance(condition, dict) else "",
            "expected": (condition or {}).get("value") if isinstance(condition, dict) else None,
            "actual": actual,
            "matched": matched,
            "error": error,
        })
    return {"logic": mode, "matched": evaluate_conditions(raw, context, mode), "conditions": rows}


def condition_fields(raw):
    """提取条件里出现过的字段，目录/表单用于提示可用字段。"""
    _, conditions = normalize_conditions(raw)
    fields = []
    for condition in conditions:
        if isinstance(condition, dict):
            field = str(condition.get("field") or "").strip()
            if field and field not in fields:
                fields.append(field)
    return fields


# ---------------------------------------------------------------------------
# 4. 细分判定
# ---------------------------------------------------------------------------


def segment_rule_condition(rule):
    """把 SegmentRule 行转成与 JSON 条件同构的字典，供统一求值器复用。"""
    return {
        "field": rule.field,
        "operator": rule.operator,
        "value": rule.value,
    }


def segment_conditions(segment):
    """合并两种规则来源并返回 (logic, conditions)。

    Segment.rules 适合导入导出与快照，SegmentRule 表适合逐条编辑；
    两者同时存在时取并集，避免用户迁移后旧规则静默失效。
    """
    logic, conditions = normalize_conditions(segment.rules or [], segment.rule_match)
    rows = list(segment.segment_rules.all().order_by("sort_order", "id"))
    if not rows:
        return logic, conditions
    merged = list(conditions)
    if not merged:
        # 只有结构化规则时，以第一条规则的 logic 之外的 Segment.rule_match 为准
        for rule in rows:
            merged.append(segment_rule_condition(rule))
        return logic, merged
    for rule in rows:
        merged.append(segment_rule_condition(rule))
    return logic, merged


def segment_matches(segment, context):
    """细分命中判定。

    空细分返回 False：一个没有任何规则的细分若被当成「全量」，一旦被灰度
    误引用就会 100% 放量，属于不可接受的默认值；显式配一条恒真规则更安全。
    """
    if segment is None:
        return False
    logic, conditions = segment_conditions(segment)
    if not conditions:
        return False
    return evaluate_conditions(conditions, context, logic)


def preview_segment(segment, contexts):
    """批量预演细分命中并刷新成员数缓存（只在显式预览时写库）。"""
    rows = []
    hits = 0
    logic, conditions = segment_conditions(segment)
    for context in contexts:
        matched = segment_matches(segment, context)
        if matched:
            hits += 1
        rows.append({
            "user_key": context.get("user_key") or (context.get("user") or {}).get("id", ""),
            "matched": matched,
            "conditions": explain_conditions(conditions, context, logic)["conditions"],
        })
    segment.member_count = hits
    segment.save(update_fields=["member_count", "updated_at"])
    return {
        "segment_id": segment.id,
        "name": segment.name,
        "total": len(rows),
        "hits": hits,
        "misses": len(rows) - hits,
        "items": rows,
    }


# ---------------------------------------------------------------------------
# 5. 变体选择
# ---------------------------------------------------------------------------


def variant_list(flag):
    """取开关变体（按 id 稳定排序），避免每次查询顺序漂移影响分桶。"""
    return list(flag.variants.all().order_by("id"))


def variant_map(flag):
    return {item.key: item for item in variant_list(flag)}


def boolean_variant_key(value):
    return "true" if value else "false"


def variant_payload(flag, key):
    """取变体负载；布尔开关直接返回布尔值。"""
    if flag.flag_type == "boolean":
        return key == "true"
    item = variant_map(flag).get(key)
    return (item.payload if item else {})


def pick_weighted_variant(flag, user_key, salt="", variants=None):
    """按权重做确定性分桶。

    没有变体的多变量开关返回 None（由调用方退回到默认值），而不是随机造
    一个变体：配置缺失必须在结果里体现为「未生效」，否则会污染实验数据。
    """
    items = variants if variants is not None else variant_list(flag)
    items = [item for item in items if int(item.weight or 0) > 0]
    if not items:
        return None
    total = sum(int(item.weight) for item in items)
    point = bucket_of("variant", flag.key, user_key, salt or "", flag.id) % total
    cursor = 0
    for item in items:
        cursor += int(item.weight)
        if point < cursor:
            return item
    return items[-1]


def resolve_variant(flag, variant_key, user_key, salt=""):
    """把「变体键」解析成 {variant, payload, enabled}。

    布尔开关只认 true/false（兼容 on/off/1/0）；多变量开关优先按变体键
    取负载，未指定则按权重分桶。返回值中的 enabled 用来说明功能是否开启，
    与 payload 分离，前端不需要理解变体语义。
    """
    key = str(variant_key or "").strip()
    if flag.flag_type == "boolean":
        if not key:
            item = pick_weighted_variant(flag, user_key, salt)
            key = item.key if item else "false"
        lowered = key.lower()
        enabled = lowered in ("true", "on", "1", "yes")
        return {"variant": "true" if enabled else "false", "payload": enabled, "enabled": enabled}
    item = variant_map(flag).get(key) if key else None
    if item is None:
        item = pick_weighted_variant(flag, user_key, salt)
    if item is None:
        fallback = flag.default_variant or "control"
        return {"variant": fallback, "payload": {}, "enabled": False}
    enabled = item.key not in ("control", "off", "false")
    return {"variant": item.key, "payload": item.payload or {}, "enabled": enabled}


def default_variant_result(flag):
    """未命中任何规则时的默认结果。"""
    key = flag.default_variant or ("false" if flag.flag_type == "boolean" else "control")
    return resolve_variant(flag, key, "default", "default")


# ---------------------------------------------------------------------------
# 6. 定向规则
# ---------------------------------------------------------------------------


def active_targeting_rules(flag):
    return list(flag.targeting_rules.filter(enabled=True).order_by("priority", "id"))


def match_targeting_rule(flag, user_key, context):
    """按优先级匹配定向规则。

    命中条件后还要过 ``percentage``：定向规则本身也可以小流量验证，
    例如「内部员工 10% 先看到新版本」。未通过百分比时继续尝试下一条规则，
    而不是直接落到默认值，避免高优先级规则的实验阶段挡住低优先级兜底。
    """
    for rule in active_targeting_rules(flag):
        if not evaluate_conditions(rule.conditions or [], context, rule.condition_logic):
            continue
        if rule.percentage < 100:
            if not percentage_hit(flag.key, user_key, f"target:{rule.id}", rule.percentage):
                continue
        return rule
    return None


def explain_targeting(flag, user_key, context):
    """逐条输出定向规则的命中/跳过原因，解释接口使用。"""
    rows = []
    for rule in active_targeting_rules(flag):
        detail = explain_conditions(rule.conditions or [], context, rule.condition_logic)
        passed_percentage = rule.percentage >= 100 or percentage_hit(
            flag.key, user_key, f"target:{rule.id}", rule.percentage
        )
        rows.append({
            "rule_id": rule.id,
            "priority": rule.priority,
            "conditions": detail["conditions"],
            "conditions_matched": detail["matched"],
            "percentage": rule.percentage,
            "percentage_matched": passed_percentage,
            "matched": detail["matched"] and passed_percentage,
            "variant_key": rule.variant_key,
            "bucket_ratio": bucket_ratio(flag.key, user_key, f"target:{rule.id}"),
        })
    return rows


# ---------------------------------------------------------------------------
# 7. 灰度发布
# ---------------------------------------------------------------------------


def rollout_state(rollout, at=None):
    """计算灰度的实时状态（不写库）。

    数据库里的 status 是「人工意图」，时间窗口是「自动约束」：到了 end_at
    即使没人点完成，评估也必须停止放量，所以这里按时间再算一次。
    """
    moment = at or now()
    if rollout.status in ("paused", "completed"):
        return rollout.status
    if rollout.start_at and moment < rollout.start_at:
        return "scheduled"
    if rollout.end_at and moment >= rollout.end_at:
        return "completed"
    return "running"


def active_rollouts(flag):
    return list(flag.rollouts.all().order_by("-percentage", "id"))


def rollout_matches(rollout, flag, user_key, context):
    """灰度是否命中：先看分段，再看百分比。"""
    if rollout.segment_id and not segment_matches(rollout.segment, context):
        return False
    salt = rollout.salt or f"rollout:{rollout.id}"
    return percentage_hit(flag.key, user_key, salt, rollout.percentage)


def evaluate_rollouts(flag, user_key, context, at=None):
    """返回 (status, rollout, reason)。

    - 有 running 且命中 → ("hit", rollout, "segment:xx" / "rollout:N%")
    - 有 running 但未命中 → ("miss", rollout, "rollout:N%")
    - 只有 paused → ("paused", rollout, "rollout:paused")
    - 只有 scheduled → ("scheduled", rollout, "rollout:scheduled")
    - 已完成或没有 → ("none", None, "default")
    """
    moment = at or now()
    paused = None
    scheduled = None
    for rollout in active_rollouts(flag):
        state = rollout_state(rollout, moment)
        if state == "paused" and paused is None:
            paused = rollout
        if state == "scheduled" and scheduled is None:
            scheduled = rollout
        if state != "running":
            continue
        if rollout_matches(rollout, flag, user_key, context):
            if rollout.segment_id:
                reason = f"segment:{rollout.segment.name}"
            else:
                reason = f"rollout:{int(rollout.percentage)}%"
            return "hit", rollout, reason
        return "miss", rollout, f"rollout:{int(rollout.percentage)}%"
    if paused is not None:
        return "paused", paused, "rollout:paused"
    if scheduled is not None:
        return "scheduled", scheduled, "rollout:scheduled"
    return "none", None, "default"


def advance_rollout(rollout, delta=None, target=None):
    """推进灰度百分比。

    只允许前进（target 小于当前值视为回退，需要显式用 update 接口修改），
    避免「推进」按钮误操作把已经放量的用户收回去导致体验抖动。
    """
    current = int(rollout.percentage)
    if target is not None:
        new_value = parse_percent(target, "目标百分比")
    else:
        step = parse_int(delta, "推进步长", 10, minimum=1, maximum=100)
        new_value = current + step
    new_value = clamp(new_value, current, 100)
    rollout.percentage = new_value
    if new_value >= 100:
        rollout.status = "completed"
    rollout.save(update_fields=["percentage", "status", "updated_at"])
    return rollout


# ---------------------------------------------------------------------------
# 8. 依赖解析
# ---------------------------------------------------------------------------


def dependency_block(flag, user_key, context, stack=None, depth=0):
    """解析依赖链，返回 (blocked, reason, chain)。

    - requires：上游必须开启；expected_value 不为空时还要求值相等
    - forbids：上游必须关闭
    环检测用 stack（当前递归路径），重复出现视为环并跳过该分支；不抛错，
    因为评估是读路径，历史脏数据不能把线上评估打挂。
    """
    stack = set(stack or ())
    if depth > MAX_DEPENDENCY_DEPTH:
        return False, "", [{"depth_limit": True}]
    if flag.id in stack:
        return False, "", [{"cycle": True, "flag_id": flag.id}]
    stack = set(stack)
    stack.add(flag.id)
    chain = []
    for dep in flag.dependencies.select_related("depends_on").order_by("id"):
        upstream = dep.depends_on
        if upstream.id in stack:
            chain.append({
                "flag_id": upstream.id,
                "flag_key": upstream.key,
                "relation": dep.relation,
                "cycle": True,
            })
            continue
        upstream_result = evaluate_flag(
            upstream,
            user_key,
            context,
            write_log=False,
            use_cache=True,
            stack=stack,
            depth=depth + 1,
        )
        chain.append({
            "flag_id": upstream.id,
            "flag_key": upstream.key,
            "relation": dep.relation,
            "enabled": upstream_result.get("enabled"),
            "value": upstream_result.get("value"),
            "reason": upstream_result.get("reason"),
        })
        if dep.relation == "forbids":
            blocked = bool(upstream_result.get("enabled"))
            detail = "上游开关已开启，禁止本开关生效"
        else:
            blocked = not bool(upstream_result.get("enabled"))
            detail = "上游开关未开启，本开关跟随关闭"
        if dep.expected_value is not None and not blocked:
            if not loose_equal(upstream_result.get("value"), dep.expected_value):
                blocked = True
                detail = "上游开关取值与期望值不一致"
        if blocked:
            return True, f"dependency:{upstream.key}", chain + [{"detail": detail}]
    return False, "", chain


def dependency_graph(project):
    """项目内依赖图：节点 + 边，供前端可视化。"""
    flags = Flag.objects.filter(project=project).order_by("id")
    nodes = [
        {
            "id": flag.id,
            "key": flag.key,
            "name": flag.name,
            "environment_id": flag.environment_id,
            "status": flag.status,
        }
        for flag in flags
    ]
    edges = []
    for dep in FlagDependency.objects.filter(flag__project=project).select_related(
        "flag", "depends_on"
    ).order_by("id"):
        edges.append({
            "id": dep.id,
            "from": dep.flag_id,
            "from_key": dep.flag.key,
            "to": dep.depends_on_id,
            "to_key": dep.depends_on.key,
            "relation": dep.relation,
            "expected_value": dep.expected_value,
        })
    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "cycles": detect_cycles(project),
    }


def detect_cycles(project):
    """DFS 找环，返回 [[flag_id, ...], ...]；每个环只报一次。"""
    edges = {}
    for dep in FlagDependency.objects.filter(flag__project=project).values_list(
        "flag_id", "depends_on_id"
    ):
        edges.setdefault(dep[0], []).append(dep[1])
    cycles = []
    seen = set()
    visiting = []

    def walk(node):
        if node in visiting:
            index = visiting.index(node)
            cycle = visiting[index:]
            key = tuple(sorted(cycle))
            if key not in seen:
                seen.add(key)
                cycles.append(cycle)
            return
        visiting.append(node)
        for nxt in edges.get(node, []):
            walk(nxt)
        visiting.pop()

    for node in list(edges.keys()):
        walk(node)
    return cycles


def would_create_cycle(flag, depends_on):
    """新增依赖前判断是否成环：从 depends_on 出发能否回到 flag。"""
    if flag.id == depends_on.id:
        return True
    edges = {}
    for dep in FlagDependency.objects.filter(flag__project=flag.project).values_list(
        "flag_id", "depends_on_id"
    ):
        edges.setdefault(dep[0], []).append(dep[1])
    edges.setdefault(flag.id, []).append(depends_on.id)
    stack = [depends_on.id]
    visited = set()
    while stack:
        node = stack.pop()
        if node == flag.id:
            return True
        if node in visited:
            continue
        visited.add(node)
        stack.extend(edges.get(node, []))
    return False


# ---------------------------------------------------------------------------
# 9. 实验分配与曝光
# ---------------------------------------------------------------------------


def experiment_groups(experiment):
    """返回 (变体键列表, 权重列表)。

    多变量开关复用自身变体与权重；布尔开关没有变体时使用 control/treatment
    均分。权重全为 0 时退化为均分：配置漏填权重不该导致所有人进同一个组。
    """
    variants = variant_list(experiment.flag)
    if variants:
        keys = [item.key for item in variants]
        weights = [max(int(item.weight or 0), 0) for item in variants]
        if sum(weights) <= 0:
            weights = [1 for _ in keys]
        return keys, weights
    keys = list(DEFAULT_EXPERIMENT_VARIANTS)
    return keys, [1 for _ in keys]


def choose_group(keys, weights, point):
    """按累计权重选出分组；point 已对总权重取模。"""
    total = sum(weights)
    if total <= 0:
        return keys[0]
    cursor = 0
    value = point % total
    for key, weight in zip(keys, weights):
        cursor += weight
        if value < cursor:
            return key
    return keys[-1]


def experiment_bucket(experiment, user_key):
    """实验分桶：实验 id + 用户键，换开关键也不会改变已有实验的分组。"""
    return bucket_of("experiment", experiment.id, user_key) % BUCKET_SPACE


def assign_experiment(experiment, user_key, context=None, record=True):
    """稳定入组并（可选）记录曝光。

    先查后建 + 唯一约束兜底：并发下两个请求同时插入时，其中一个会撞
    唯一约束，捕获后重新读取即可，不会出现同用户两个变体。
    """
    key = str(user_key or "").strip()
    if not key:
        raise ValueError("用户键不能为空")
    existing = Assignment.objects.filter(experiment=experiment, user_key=key).first()
    if existing is None:
        keys, weights = experiment_groups(experiment)
        point = experiment_bucket(experiment, key)
        variant_key = choose_group(keys, weights, point)
        try:
            with transaction.atomic():
                existing, _created = Assignment.objects.get_or_create(
                    experiment=experiment,
                    user_key=key,
                    defaults={
                        "owner": experiment.owner,
                        "variant_key": variant_key,
                        "bucket": point,
                    },
                )
        except Exception:  # noqa: BLE001 —— 并发插入撞唯一约束时回读
            existing = Assignment.objects.filter(
                experiment=experiment, user_key=key
            ).first()
            if existing is None:
                raise
    if record and experiment.status == "running":
        record_exposure(experiment, key, existing.variant_key, context or {})
    return existing


def record_exposure(experiment, user_key, variant_key="", context=None):
    """曝光上报（幂等）。

    - 未指定变体：按稳定分组自动补全；
    - 已指定变体但与既有分组不一致：以分组为准，避免有人手工把用户塞进
      另一组导致结果不可复现；
    - 已存在曝光：只合并上下文，不刷新曝光时间（首次曝光才是实验起点）。
    """
    key = str(user_key or "").strip()
    if not key:
        raise ValueError("用户键不能为空")
    assignment = Assignment.objects.filter(experiment=experiment, user_key=key).first()
    requested = str(variant_key or "").strip()
    if assignment is None:
        keys, weights = experiment_groups(experiment)
        if requested and requested not in keys:
            raise ValueError(f"变体 {requested} 不属于该实验")
        if not requested:
            point = experiment_bucket(experiment, key)
            requested = choose_group(keys, weights, point)
        assignment, _ = Assignment.objects.get_or_create(
            experiment=experiment,
            user_key=key,
            defaults={
                "owner": experiment.owner,
                "variant_key": requested,
                "bucket": experiment_bucket(experiment, key),
            },
        )
    effective_key = assignment.variant_key
    context = dict(context or {}) if isinstance(context, dict) else {}
    exposure = Exposure.objects.filter(experiment=experiment, user_key=key).first()
    if exposure is None:
        try:
            with transaction.atomic():
                exposure = Exposure.objects.create(
                    owner=experiment.owner,
                    experiment=experiment,
                    user_key=key,
                    variant_key=effective_key,
                    exposed_at=now(),
                    context=context,
                )
            return exposure, True
        except Exception:  # noqa: BLE001 —— 并发重复插入，回读已有记录
            exposure = Exposure.objects.filter(
                experiment=experiment, user_key=key
            ).first()
            if exposure is None:
                raise
    # 已有曝光只做上下文合并：converted/value 可能在首次曝光之后才上报
    if context:
        merged = dict(exposure.context or {})
        merged.update(context)
        exposure.context = merged
        exposure.save(update_fields=["context", "updated_at"])
    return exposure, False


def find_running_experiment(flag, at=None):
    """取当前生效的实验：状态 running 且在开始/结束窗口内。"""
    moment = at or now()
    for experiment in flag.experiments.filter(status="running").order_by("-id"):
        if experiment.start_at and moment < experiment.start_at:
            continue
        if experiment.end_at and moment >= experiment.end_at:
            continue
        return experiment
    return None


# ---------------------------------------------------------------------------
# 10. 实验结果
# ---------------------------------------------------------------------------


def chi_square_2x2(a, b, c, d):
    """2×2 卡方检验（df=1），返回卡方值与 p 值。

    a=对照组转化, b=对照组未转化, c=实验组转化, d=实验组未转化。
    p 值用 erfc(sqrt(chi2/2))，这是 df=1 卡方分布的精确生存函数，
    不引入 scipy 依赖。
    """
    total = a + b + c + d
    denominator = (a + b) * (c + d) * (a + c) * (b + d)
    if total <= 0 or denominator <= 0:
        return {"chi_square": 0.0, "p_value": 1.0, "significant": False}
    statistic = total * (a * d - b * c) ** 2 / float(denominator)
    p_value = math.erfc(math.sqrt(statistic / 2.0))
    return {
        "chi_square": round(statistic, 4),
        "p_value": round(p_value, 6),
        "significant": p_value < 0.05,
    }


def _exposure_metrics(exposures):
    """把曝光上下文归并成转化/收入指标。"""
    conversions = 0
    revenue = 0.0
    for exposure in exposures:
        ctx = exposure.context or {}
        converted = ctx.get("converted", ctx.get("conversion", False))
        try:
            if isinstance(converted, str):
                converted = converted.strip().lower() in ("1", "true", "yes", "on")
            else:
                converted = bool(converted)
        except Exception:  # noqa: BLE001
            converted = False
        if converted:
            conversions += 1
        value = ctx.get("value", ctx.get("revenue", 0))
        number = coerce_number(value)
        if converted or (number is not None and number > 0):
            revenue += number or 0.0
    count = len(exposures)
    return {
        "exposures": count,
        "conversions": conversions,
        "conversion_rate": round(conversions / count, 6) if count else 0.0,
        "revenue": round(revenue, 4),
        "revenue_per_user": round(revenue / count, 6) if count else 0.0,
    }


def experiment_results(experiment):
    """实验结果：分组指标、提升度、显著性、样本量校验与胜出组。"""
    exposures = list(experiment.exposures.all().order_by("id"))
    groups = {}
    for exposure in exposures:
        groups.setdefault(exposure.variant_key, []).append(exposure)
    keys, weights = experiment_groups(experiment)
    for key in keys:
        groups.setdefault(key, [])
    control_key = "control" if "control" in groups else keys[0]
    control_rows = groups.get(control_key, [])
    control = _exposure_metrics(control_rows)

    metric_def = experiment.metrics.filter(name=experiment.primary_metric).first()
    metric_type = metric_def.metric_type if metric_def else "conversion"

    rows = []
    for key in keys:
        bucket_rows = groups.get(key, [])
        metrics = _exposure_metrics(bucket_rows)
        if metric_type == "revenue":
            primary = metrics["revenue_per_user"]
            control_primary = control["revenue_per_user"]
        elif metric_type == "count":
            primary = metrics["revenue"]
            control_primary = control["revenue"]
        else:
            primary = metrics["conversion_rate"]
            control_primary = control["conversion_rate"]
        lift = round(primary - control_primary, 6)
        relative = round(lift / control_primary, 6) if control_primary > 0 else None
        test = chi_square_2x2(
            control["conversions"],
            control["exposures"] - control["conversions"],
            metrics["conversions"],
            metrics["exposures"] - metrics["conversions"],
        )
        rows.append({
            "variant_key": key,
            "is_control": key == control_key,
            "weight": weights[keys.index(key)] if key in keys else 0,
            **metrics,
            "primary_value": round(primary, 6),
            "lift": lift,
            "relative_lift": relative,
            "chi_square": test["chi_square"],
            "p_value": test["p_value"],
            "significant": test["significant"],
        })

    eligible = [row for row in rows if row["exposures"] >= experiment.min_sample_size]
    pool = eligible or rows
    winner = max(pool, key=lambda row: row["primary_value"]) if pool else None
    sample_ready = bool(rows) and all(
        row["exposures"] >= experiment.min_sample_size for row in rows if row["exposures"] > 0
    )
    return {
        "experiment_id": experiment.id,
        "name": experiment.name,
        "status": experiment.status,
        "primary_metric": experiment.primary_metric,
        "metric_type": metric_type,
        "metric_direction": metric_def.direction if metric_def else "increase",
        "min_sample_size": experiment.min_sample_size,
        "total_exposures": len(exposures),
        "control_variant": control_key,
        "sample_ready": sample_ready,
        "variants": rows,
        "winner": winner["variant_key"] if winner else "",
        "any_significant": any(row["significant"] for row in rows if not row["is_control"]),
        "start_at": experiment.start_at,
        "end_at": experiment.end_at,
    }


def experiment_progress(experiment):
    """实验进度：曝光数 / 目标样本量，按组给出缺口。"""
    exposures = list(experiment.exposures.values("variant_key"))
    keys, _weights = experiment_groups(experiment)
    counts = {key: 0 for key in keys}
    for row in exposures:
        counts[row["variant_key"]] = counts.get(row["variant_key"], 0) + 1
    groups = len(keys) or 1
    target = max(int(experiment.min_sample_size), 0) * groups
    total = sum(counts.values())
    percent = round(min(100.0, total / target * 100.0), 2) if target else 100.0
    elapsed_days = 0
    if experiment.start_at:
        elapsed_days = max(0, (now() - experiment.start_at).days)
    return {
        "experiment_id": experiment.id,
        "name": experiment.name,
        "status": experiment.status,
        "total_exposures": total,
        "target": target,
        "target_per_variant": experiment.min_sample_size,
        "percent": percent,
        "groups": [
            {
                "variant_key": key,
                "exposures": counts.get(key, 0),
                "remaining": max(0, experiment.min_sample_size - counts.get(key, 0)),
            }
            for key in keys
        ],
        "elapsed_days": elapsed_days,
        "sample_ready": bool(keys) and all(
            counts.get(key, 0) >= experiment.min_sample_size for key in keys
        ),
    }


def exposure_stats(experiment):
    """曝光统计：分组数量、占比、首末曝光时间。"""
    exposures = list(experiment.exposures.all().order_by("exposed_at", "id"))
    counts = {}
    times = {}
    for exposure in exposures:
        counts[exposure.variant_key] = counts.get(exposure.variant_key, 0) + 1
        bucket = times.setdefault(exposure.variant_key, [None, None])
        moment = exposure.exposed_at
        if moment is not None:
            if bucket[0] is None or moment < bucket[0]:
                bucket[0] = moment
            if bucket[1] is None or moment > bucket[1]:
                bucket[1] = moment
    total = len(exposures)
    keys, _weights = experiment_groups(experiment)
    rows = []
    for key in keys:
        count = counts.get(key, 0)
        span = times.get(key, [None, None])
        rows.append({
            "variant_key": key,
            "exposures": count,
            "share": round(count / total, 6) if total else 0.0,
            "first_exposed_at": span[0],
            "last_exposed_at": span[1],
        })
    return {
        "experiment_id": experiment.id,
        "total": total,
        "variants": rows,
        "unique_users": total,
    }


# ---------------------------------------------------------------------------
# 11. 护栏
# ---------------------------------------------------------------------------


def compare_threshold(value, threshold, comparator="gte"):
    """阈值比较：支持 gte/lte/gt/lt 四种方向。"""
    left = coerce_number(value)
    right = coerce_number(threshold)
    if left is None or right is None:
        return False
    if comparator == "lte":
        return left <= right
    if comparator == "gt":
        return left > right
    if comparator == "lt":
        return left < right
    return left >= right


def _normalize_readings(readings):
    """护栏读数归一：接受 {metric: value} 或 [{metric, value}]。"""
    if isinstance(readings, dict):
        return {str(key): value for key, value in readings.items()}
    if isinstance(readings, list):
        out = {}
        for row in readings:
            if not isinstance(row, dict):
                raise ValueError("读数必须是对象或对象数组")
            metric = str(row.get("metric") or "").strip()
            if not metric:
                raise ValueError("读数缺少 metric")
            out[metric] = row.get("value")
        return out
    raise ValueError("读数必须是对象或对象数组")


def check_guardrails(flag, readings, actor=None):
    """护栏检查：超阈值即记录审计并按动作处置。

    - pause：把该开关进行中的灰度全部置为 paused
    - rollback：开关置为 inactive（等同紧急关停）
    - notify：只记录审计，不改状态
    所有处置都在事务里，避免「审计写了但状态没改」的半截操作。
    """
    values = _normalize_readings(readings)
    actor = actor or flag.owner
    triggered = []
    with transaction.atomic():
        for guardrail in flag.guardrails.all().order_by("id"):
            if guardrail.metric not in values:
                continue
            raw = values.get(guardrail.metric)
            number = coerce_number(raw)
            if number is None:
                continue
            guardrail.last_value = number
            guardrail.save(update_fields=["last_value", "updated_at"])
            if not compare_threshold(number, guardrail.threshold, guardrail.comparator):
                continue
            guardrail.triggered_at = now()
            guardrail.triggered_count += 1
            guardrail.save(update_fields=["triggered_at", "triggered_count", "updated_at"])
            effect = "recorded"
            if guardrail.action == "pause":
                updated = flag.rollouts.filter(status="running").update(
                    status="paused", updated_at=now()
                )
                effect = f"paused_rollouts:{updated}"
            elif guardrail.action == "rollback":
                flag.status = "inactive"
                flag.save(update_fields=["status", "updated_at"])
                effect = "flag_inactive"
            triggered.append({
                "guardrail_id": guardrail.id,
                "metric": guardrail.metric,
                "value": number,
                "threshold": guardrail.threshold,
                "comparator": guardrail.comparator,
                "action": guardrail.action,
                "effect": effect,
            })
            record_audit(
                actor,
                guardrail,
                f"guardrail:{guardrail.action}",
                before={"flag_status": "active"},
                after={"value": number, "threshold": guardrail.threshold, "effect": effect},
                project=flag.project,
                note=f"指标 {guardrail.metric} 触发阈值",
            )
    if triggered:
        invalidate_flag(flag.id)
    return {
        "flag_id": flag.id,
        "checked": len(flag.guardrails.all()),
        "triggered": triggered,
        "count": len(triggered),
    }


# ---------------------------------------------------------------------------
# 12. 开关评估
# ---------------------------------------------------------------------------


def _empty_result(flag, user_key, reason, choice=None):
    choice = choice or default_variant_result(flag)
    return {
        "flag_id": flag.id,
        "flag_key": flag.key,
        "flag_name": flag.name,
        "flag_type": flag.flag_type,
        "environment_id": flag.environment_id,
        "environment_key": getattr(flag.environment, "key", ""),
        "user_key": user_key,
        "enabled": bool(choice.get("enabled")),
        "value": choice.get("payload") if flag.flag_type != "boolean" else bool(choice.get("enabled")),
        "variant": choice.get("variant", ""),
        "payload": choice.get("payload"),
        "reason": reason,
    }


def _evaluate_core(flag, user_key, context, stack=None, depth=0, at=None):
    """评估主链路（不含日志/缓存），顺序：状态 → 依赖 → 定向 → 实验 → 灰度。"""
    moment = at or now()
    if flag.status == "archived":
        return _empty_result(flag, user_key, "flag-archived")
    if flag.status != "active":
        return _empty_result(flag, user_key, "flag-inactive")
    environment = flag.environment
    if environment is not None and not environment.enabled:
        return _empty_result(flag, user_key, "environment-disabled")

    blocked, reason, chain = dependency_block(flag, user_key, context, stack or set(), depth)
    if blocked:
        result = _empty_result(flag, user_key, reason)
        result["dependencies"] = chain
        return result

    rule = match_targeting_rule(flag, user_key, context)
    if rule is not None:
        salt = f"target:{rule.id}"
        if rule.variant_key:
            choice = resolve_variant(flag, rule.variant_key, user_key, salt)
        elif flag.flag_type == "boolean":
            choice = resolve_variant(flag, "true", user_key, salt)
        else:
            item = pick_weighted_variant(flag, user_key, salt)
            choice = resolve_variant(flag, item.key if item else "", user_key, salt)
        result = _empty_result(flag, user_key, f"targeting:{rule.id}", choice)
        result["targeting_rule_id"] = rule.id
        result["dependencies"] = chain
        return result

    experiment = find_running_experiment(flag, moment)
    if experiment is not None:
        assignment = assign_experiment(experiment, user_key, context, record=True)
        choice = resolve_variant(flag, assignment.variant_key, user_key, f"exp:{experiment.id}")
        result = _empty_result(flag, user_key, f"experiment:{experiment.name}", choice)
        result["experiment_id"] = experiment.id
        result["dependencies"] = chain
        return result

    status, rollout, reason = evaluate_rollouts(flag, user_key, context, moment)
    if status == "hit":
        if flag.flag_type == "boolean":
            choice = resolve_variant(flag, "true", user_key, f"rollout:{rollout.id}")
        else:
            item = pick_weighted_variant(flag, user_key, f"rollout:{rollout.id}")
            choice = resolve_variant(flag, item.key if item else "", user_key, f"rollout:{rollout.id}")
        result = _empty_result(flag, user_key, reason, choice)
        result["rollout_id"] = rollout.id
        result["rollout_percentage"] = rollout.percentage
        result["dependencies"] = chain
        return result
    if status in ("paused", "scheduled"):
        result = _empty_result(flag, user_key, reason)
        result["rollout_id"] = rollout.id if rollout else None
        result["dependencies"] = chain
        return result
    result = _empty_result(flag, user_key, reason or "default")
    result["dependencies"] = chain
    return result


def _cache_key(flag, user_key, context):
    return (
        flag.id,
        flag.updated_at.isoformat() if flag.updated_at else "",
        user_key,
        context_digest(context),
    )


def cache_get(flag, user_key, context):
    entry = _CACHE.get(_cache_key(flag, user_key, context))
    if not entry:
        return None
    stored_at, payload = entry
    if time.time() - stored_at > CACHE_TTL_SECONDS:
        _CACHE.pop(_cache_key(flag, user_key, context), None)
        return None
    return dict(payload)


def cache_set(flag, user_key, context, payload):
    if len(_CACHE) >= CACHE_LIMIT:
        # 简单 FIFO 清理：评估缓存只是加速，丢掉最老的一批不会影响正确性
        for key in list(_CACHE.keys())[: CACHE_LIMIT // 4]:
            _CACHE.pop(key, None)
    _CACHE[_cache_key(flag, user_key, context)] = (time.time(), dict(payload))


def invalidate_flag(flag_id):
    """精确失效某个开关的缓存；写接口与护栏处置后调用。"""
    for key in [item for item in _CACHE if item[0] == flag_id]:
        _CACHE.pop(key, None)


def clear_cache():
    """测试与排障用：清空全部评估缓存。"""
    _CACHE.clear()


def _maybe_trim_logs(flag):
    """按开关截断评估日志，保留最近 EVALUATION_LOG_KEEP 条。

    每 50 次写才检查一次计数，避免每次评估都做一次 COUNT；删除分批进行，
    防止一次性锁表太久。日志被截断属于预期行为，不能影响评估返回。
    """
    global _LOG_WRITE_COUNTER
    _LOG_WRITE_COUNTER += 1
    if _LOG_WRITE_COUNTER % _LOG_TRIM_EVERY != 0:
        return
    try:
        total = EvaluationLog.objects.filter(flag=flag).count()
        if total <= EVALUATION_LOG_KEEP + 200:
            return
        ids = list(
            EvaluationLog.objects.filter(flag=flag)
            .order_by("-evaluated_at", "-id")
            .values_list("id", flat=True)[EVALUATION_LOG_KEEP: EVALUATION_LOG_KEEP + 500]
        )
        if ids:
            EvaluationLog.objects.filter(id__in=ids).delete()
    except Exception:  # noqa: BLE001 —— 日志治理失败绝不影响评估主链路
        return


def write_evaluation_log(flag, user_key, result, latency_ms):
    """写评估日志并触发懒截断；任何异常都吞掉，保证评估可用性。"""
    try:
        log = EvaluationLog.objects.create(
            owner=flag.owner,
            flag=flag,
            environment=flag.environment,
            user_key=user_key,
            result={
                "enabled": result.get("enabled"),
                "variant": result.get("variant"),
                "value": result.get("value"),
            },
            matched_rule=result.get("reason", ""),
            latency_ms=round(float(latency_ms), 4),
        )
        _maybe_trim_logs(flag)
        return log
    except Exception:  # noqa: BLE001
        return None


def evaluate_flag(flag, user_key, context=None, write_log=True, use_cache=True,
                  stack=None, depth=0, at=None):
    """单用户单开关评估，返回完整结果并（默认）写日志。

    ``write_log=False`` 用于依赖解析/实验内部调用，避免一次用户请求产生
    多条内部日志把统计口径冲淡。
    """
    key = str(user_key or "").strip()
    if not key:
        raise ValueError("用户键不能为空")
    ctx = normalize_context(key, context)
    # 有依赖的开关不缓存：上游状态变化不会触发本开关 updated_at，
    # 缓存会返回过期结果；依赖链本身有内部缓存，性能仍然可控。
    if use_cache and flag.dependencies.exists():
        use_cache = False
    cached = cache_get(flag, key, ctx) if use_cache else None
    if cached is not None:
        cached["cached"] = True
        cached["latency_ms"] = 0.0
        if write_log:
            write_evaluation_log(flag, key, cached, 0.0)
            Flag.objects.filter(pk=flag.pk).update(last_evaluated_at=now())
        return cached
    started = time.perf_counter()
    result = _evaluate_core(flag, key, ctx, stack=stack, depth=depth, at=at)
    latency = (time.perf_counter() - started) * 1000.0
    result["evaluated_at"] = now()
    result["cached"] = False
    result["latency_ms"] = round(latency, 4)
    if use_cache:
        cache_set(flag, key, ctx, {k: v for k, v in result.items() if k != "latency_ms"})
    if write_log:
        write_evaluation_log(flag, key, result, latency)
        Flag.objects.filter(pk=flag.pk).update(last_evaluated_at=now())
    return result


def evaluate_batch(flag, user_keys, base_context=None, context_by_user=None):
    """批量评估：逐用户求值，返回命中数与明细。

    上下文按用户覆盖：同一个请求里既支持共享属性（国家/版本），也支持
    每个用户自己的 custom 属性。
    """
    keys = [str(item).strip() for item in (user_keys or [])]
    keys = [item for item in keys if item]
    if not keys:
        raise ValueError("用户键列表不能为空")
    if len(keys) > 500:
        raise ValueError("单次批量评估最多 500 个用户")
    context_by_user = context_by_user or {}
    rows = []
    hits = 0
    for key in keys:
        context = dict(base_context or {})
        extra = context_by_user.get(key)
        if isinstance(extra, dict):
            context.update(extra)
        result = evaluate_flag(flag, key, context, write_log=True)
        if result.get("enabled"):
            hits += 1
        rows.append(result)
    return {
        "flag_id": flag.id,
        "flag_key": flag.key,
        "count": len(rows),
        "hits": hits,
        "misses": len(rows) - hits,
        "hit_rate": round(hits / len(rows), 4) if rows else 0.0,
        "items": rows,
    }


def evaluate_boolean_map(flags, user_key, context=None):
    """只返回布尔值：给客户端 SDK 的轻量接口。"""
    ctx = normalize_context(user_key, context)
    values = {}
    reasons = {}
    for flag in flags:
        result = evaluate_flag(flag, user_key, ctx, write_log=True)
        values[flag.key] = bool(result.get("enabled"))
        reasons[flag.key] = result.get("reason", "")
    return {"user_key": str(user_key), "flags": values, "reasons": reasons, "count": len(values)}


def explain_flag(flag, user_key, context=None):
    """解释一次评估：状态、依赖、定向、实验、灰度逐段展开。"""
    key = str(user_key or "").strip()
    if not key:
        raise ValueError("用户键不能为空")
    ctx = normalize_context(key, context)
    result = evaluate_flag(
        flag, key, ctx, write_log=False, use_cache=False
    )
    blocked, dependency_reason, chain = dependency_block(flag, key, ctx)
    rollout_rows = []
    for rollout in active_rollouts(flag):
        rollout_rows.append({
            "rollout_id": rollout.id,
            "percentage": rollout.percentage,
            "state": rollout_state(rollout),
            "segment": rollout.segment.name if rollout.segment_id else "",
            "bucket_ratio": bucket_ratio(flag.key, key, rollout.salt or f"rollout:{rollout.id}"),
            "matched": rollout_state(rollout) == "running"
            and rollout_matches(rollout, flag, key, ctx),
        })
    experiment = find_running_experiment(flag)
    experiment_row = None
    if experiment is not None:
        assignment = assign_experiment(experiment, key, ctx, record=False)
        experiment_row = {
            "experiment_id": experiment.id,
            "name": experiment.name,
            "status": experiment.status,
            "assigned_variant": assignment.variant_key,
            "bucket": assignment.bucket,
        }
    steps = [
        {"step": "flag", "status": flag.status, "environment": getattr(flag.environment, "key", "")},
        {
            "step": "dependencies",
            "blocked": blocked,
            "reason": dependency_reason,
            "chain": chain,
        },
        {"step": "targeting", "rules": explain_targeting(flag, key, ctx)},
        {"step": "experiment", "experiment": experiment_row},
        {"step": "rollouts", "rollouts": rollout_rows},
        {"step": "result", "reason": result.get("reason"), "enabled": result.get("enabled"),
         "variant": result.get("variant")},
    ]
    return {
        "flag_id": flag.id,
        "flag_key": flag.key,
        "user_key": key,
        "context": ctx,
        "result": result,
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# 13. 版本快照 / 审计 / 权限
# ---------------------------------------------------------------------------


def is_admin(user):
    return bool(getattr(user, "is_superuser", False))


def visible(qs, user):
    """读范围：走 core.scoping，超级用户/数据范围 all 可以看全量。"""
    return scope_queryset(qs, user)


def ensure_visible(obj, user, message="无权查看该对象"):
    if obj is None:
        raise ValueError("对象不存在")
    if not (is_admin(user) or is_visible(obj, user)):
        raise ValueError(message)
    return obj


def ensure_writable(obj, user, message="无权修改该对象"):
    if obj is None:
        raise ValueError("对象不存在")
    if not (is_admin(user) or can_write(user, obj)):
        raise ValueError(message)
    return obj


def get_visible(model, pk, user, message="对象不存在"):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    ensure_visible(obj, user)
    return obj


def get_writable(model, pk, user, message="对象不存在"):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    ensure_writable(obj, user)
    return obj


def project_of(obj):
    """从任意子对象向上找到所属 Project，用于审计归档。"""
    cursor = obj
    for _ in range(6):
        if cursor is None:
            return None
        if isinstance(cursor, Project):
            return cursor
        if hasattr(cursor, "project_id"):
            project = getattr(cursor, "project", None)
            if project is not None:
                return project
        cursor = getattr(cursor, "flag", None) or getattr(cursor, "segment", None) \
            or getattr(cursor, "experiment", None)
    return None


def json_safe(value):
    """把模型字典转成 JSONField 可存储的结构（时间转 ISO 字符串）。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def audit_snapshot(obj, fields=None):
    """生成审计快照；fields 为空时取模型全量字段。"""
    if obj is None:
        return {}
    try:
        data = obj.as_dict()
    except Exception:  # noqa: BLE001 —— 审计不能因为序列化失败而阻断业务
        data = {"id": getattr(obj, "id", None)}
    if fields:
        data = {key: data.get(key) for key in fields if key in data}
    return json_safe(data)


def record_audit(actor, obj, action, before=None, after=None, project=None, note=""):
    """写审计事件（失败不阻断业务，但会留下静默缺口——日志里可见）。"""
    try:
        owner = actor if getattr(actor, "id", None) else getattr(obj, "owner", None)
        if owner is None:
            return None
        name = ""
        if actor is not None:
            name = getattr(actor, "nickname", "") or getattr(actor, "username", "") or ""
        return AuditEvent.objects.create(
            owner=owner,
            project=project or project_of(obj),
            actor=actor if getattr(actor, "id", None) else None,
            actor_name=name,
            object_type=getattr(getattr(obj, "_meta", None), "model_name", type(obj).__name__),
            object_id=int(getattr(obj, "id", 0) or 0),
            action=str(action)[:60],
            before=json_safe(before or {}),
            after=json_safe(after or {}),
            note=str(note or "")[:300],
        )
    except Exception:  # noqa: BLE001
        return None


def snapshot_flag(flag):
    """固化开关当前配置，供版本发布与回滚。

    快照包含「基础属性 + 变体 + 定向规则 + 灰度」四部分，刻意不包含实验
    与依赖：实验是独立生命周期，回滚开关配置不应悄悄结束正在跑的实验。
    """
    flag.refresh_from_db()
    return {
        "flag": {
            "name": flag.name,
            "description": flag.description,
            "flag_type": flag.flag_type,
            "status": flag.status,
            "temporary": flag.temporary,
            "permanent": flag.permanent,
            "labels": flag.labels or [],
            "assignee": flag.assignee,
            "default_variant": flag.default_variant,
        },
        "variants": [
            {
                "key": item.key,
                "name": item.name,
                "weight": item.weight,
                "payload": item.payload or {},
            }
            for item in flag.variants.all().order_by("id")
        ],
        "targeting_rules": [
            {
                "priority": rule.priority,
                "conditions": rule.conditions or [],
                "condition_logic": rule.condition_logic,
                "variant_key": rule.variant_key,
                "percentage": rule.percentage,
                "enabled": rule.enabled,
                "note": rule.note,
            }
            for rule in flag.targeting_rules.all().order_by("priority", "id")
        ],
        "rollouts": [
            {
                "percentage": rollout.percentage,
                "segment_id": rollout.segment_id,
                "salt": rollout.salt,
                "start_at": json_safe(rollout.start_at),
                "end_at": json_safe(rollout.end_at),
                "status": rollout.status,
            }
            for rollout in flag.rollouts.all().order_by("id")
        ],
    }


def next_version_number(flag):
    last = flag.versions.order_by("-version").values_list("version", flat=True).first()
    return int(last or 0) + 1


def publish_version(flag, publisher, note=""):
    """发布新版本：快照 + 版本号自增，同一开关版本号唯一。"""
    version = next_version_number(flag)
    record = FlagVersion.objects.create(
        owner=flag.owner,
        flag=flag,
        version=version,
        rules_snapshot=snapshot_flag(flag),
        change_note=str(note or "")[:2000],
        publisher=publisher,
    )
    record_audit(
        publisher,
        flag,
        "flag.publish",
        before={},
        after={"version": version, "note": note},
        project=flag.project,
    )
    return record


def restore_version(flag, version_record, operator):
    """回滚到指定版本：删除当前变体/定向/灰度后按快照重建。

    回滚不是「撤销版本文件」，而是把配置真正写回业务表，因此必须在事务里
    完成；回滚后自动发布一个新版本，保留「谁在什么时候回滚到哪一版」。
    """
    snapshot = version_record.rules_snapshot or {}
    if not snapshot.get("flag"):
        raise ValueError("版本快照为空，无法回滚")
    with transaction.atomic():
        base = snapshot.get("flag", {})
        flag.name = str(base.get("name") or flag.name)[:200]
        flag.description = str(base.get("description") or "")
        flag.flag_type = parse_choice(base.get("flag_type"), FLAG_TYPES, "开关类型", flag.flag_type)
        flag.status = parse_choice(base.get("status"), FLAG_STATUS, "开关状态", flag.status)
        flag.temporary = bool(base.get("temporary", flag.temporary))
        flag.permanent = bool(base.get("permanent", flag.permanent))
        flag.labels = normalize_labels(base.get("labels") or [])
        flag.assignee = str(base.get("assignee") or "")[:120]
        flag.default_variant = str(base.get("default_variant") or "")[:80]
        flag.save()
        flag.variants.all().delete()
        for row in snapshot.get("variants") or []:
            Variant.objects.create(
                owner=flag.owner,
                flag=flag,
                key=parse_key(row.get("key"), "变体键"),
                name=str(row.get("name") or row.get("key"))[:120],
                weight=parse_int(row.get("weight"), "权重", 0, minimum=0, maximum=100),
                payload=parse_json(row.get("payload"), "负载", {}) or {},
            )
        flag.targeting_rules.all().delete()
        for row in snapshot.get("targeting_rules") or []:
            conditions = row.get("conditions") or []
            for condition in conditions if isinstance(conditions, list) else []:
                validate_condition(condition)
            TargetingRule.objects.create(
                owner=flag.owner,
                flag=flag,
                priority=parse_int(row.get("priority"), "优先级", 100),
                conditions=conditions,
                condition_logic=parse_choice(
                    row.get("condition_logic"), LOGIC_OPS, "条件组合", "and"
                ),
                variant_key=str(row.get("variant_key") or "")[:80],
                percentage=parse_percent(row.get("percentage"), "百分比", 100),
                enabled=bool(row.get("enabled", True)),
                note=str(row.get("note") or "")[:200],
            )
        flag.rollouts.all().delete()
        for row in snapshot.get("rollouts") or []:
            Rollout.objects.create(
                owner=flag.owner,
                flag=flag,
                percentage=parse_percent(row.get("percentage"), "百分比", 0),
                segment_id=row.get("segment_id") or None,
                salt=str(row.get("salt") or "")[:120],
                start_at=parse_datetime(row.get("start_at"), "开始时间"),
                end_at=parse_datetime(row.get("end_at"), "结束时间"),
                status=parse_choice(row.get("status"), ROLLOUT_STATUS, "灰度状态", "running"),
            )
    invalidate_flag(flag.id)
    new_version = publish_version(flag, operator, f"回滚至 v{version_record.version}")
    record_audit(
        operator,
        flag,
        "flag.rollback",
        before={"version": version_record.version},
        after={"new_version": new_version.version},
        project=flag.project,
    )
    return new_version


# ---------------------------------------------------------------------------
# 14. 统计
# ---------------------------------------------------------------------------


def _recent_logs(user, days=None, limit=20000):
    qs = visible(EvaluationLog.objects.all(), user)
    if days:
        since = now() - timedelta(days=int(days))
        qs = qs.filter(evaluated_at__gte=since)
    return list(qs.order_by("-evaluated_at", "-id").values(
        "id", "flag_id", "environment_id", "user_key", "result",
        "matched_rule", "evaluated_at",
    )[:limit])


def _result_enabled(result):
    if not isinstance(result, dict):
        return False
    value = result.get("enabled")
    if isinstance(value, bool):
        return value
    return bool(value)


def evaluation_summary(user, days=7):
    """统计概览：规模 + 近 N 天评估量/命中率/原因分布。"""
    flags = visible(Flag.objects.all(), user)
    logs = _recent_logs(user, days)
    hits = sum(1 for row in logs if _result_enabled(row["result"]))
    reasons = {}
    for row in logs:
        reason = row.get("matched_rule") or "unknown"
        reasons[reason] = reasons.get(reason, 0) + 1
    top_reasons = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:10]
    return {
        "projects": visible(Project.objects.all(), user).count(),
        "environments": visible(Environment.objects.all(), user).count(),
        "flags": flags.count(),
        "active_flags": flags.filter(status="active").count(),
        "segments": visible(Segment.objects.all(), user).count(),
        "experiments": visible(Experiment.objects.all(), user).count(),
        "running_experiments": visible(Experiment.objects.all(), user).filter(
            status="running").count(),
        "evaluations": len(logs),
        "hits": hits,
        "hit_rate": round(hits / len(logs), 4) if logs else 0.0,
        "unique_users": len({row["user_key"] for row in logs}),
        "days": days,
        "top_reasons": [{"reason": reason, "count": count} for reason, count in top_reasons],
        "generated_at": now(),
    }


def top_flags(user, limit=10, days=7):
    """评估量 TOP 开关，同时给出命中率。"""
    logs = _recent_logs(user, days)
    grouped = {}
    for row in logs:
        bucket = grouped.setdefault(
            row["flag_id"], {"flag_id": row["flag_id"], "total": 0, "hits": 0}
        )
        bucket["total"] += 1
        if _result_enabled(row["result"]):
            bucket["hits"] += 1
    flags = Flag.objects.in_bulk(list(grouped.keys()))
    rows = []
    for flag_id, bucket in grouped.items():
        flag = flags.get(flag_id)
        bucket["flag_key"] = flag.key if flag else ""
        bucket["flag_name"] = flag.name if flag else ""
        bucket["hit_rate"] = round(bucket["hits"] / bucket["total"], 4) if bucket["total"] else 0.0
        rows.append(bucket)
    rows.sort(key=lambda row: (-row["total"], row["flag_key"]))
    limit = clamp(int(limit or 10), 1, 100)
    return {"items": rows[:limit], "count": min(len(rows), limit), "total_flags": len(rows)}


def variant_distribution(user, flag=None, days=7):
    """变体分布：按开关 + 变体聚合评估结果。"""
    logs = _recent_logs(user, days)
    if flag is not None:
        logs = [row for row in logs if row["flag_id"] == flag.id]
    grouped = {}
    for row in logs:
        result = row["result"] or {}
        variant = str(result.get("variant") or "unknown")
        key = (row["flag_id"], variant)
        bucket = grouped.setdefault(
            key, {"flag_id": row["flag_id"], "variant": variant, "count": 0, "hits": 0}
        )
        bucket["count"] += 1
        if _result_enabled(result):
            bucket["hits"] += 1
    flags = Flag.objects.in_bulk([key[0] for key in grouped.keys()])
    rows = []
    for (flag_id, _variant), bucket in grouped.items():
        item = flags.get(flag_id)
        bucket["flag_key"] = item.key if item else ""
        rows.append(bucket)
    rows.sort(key=lambda row: (-row["count"], row["flag_key"], row["variant"]))
    return {"items": rows[:100], "count": min(len(rows), 100)}


def evaluation_trend(user, days=7):
    """评估趋势：按自然日聚合评估量与命中量。"""
    days = clamp(int(days or 7), 1, 90)
    logs = _recent_logs(user, days)
    start = local_today() - timedelta(days=days - 1)
    buckets = {}
    for offset in range(days):
        day = start + timedelta(days=offset)
        buckets[day.isoformat()] = {"date": day.isoformat(), "total": 0, "hits": 0}
    for row in logs:
        moment = row.get("evaluated_at")
        if moment is None:
            continue
        key = timezone.localtime(moment).date().isoformat() if timezone.is_aware(moment) \
            else moment.date().isoformat()
        bucket = buckets.get(key)
        if bucket is None:
            continue
        bucket["total"] += 1
        if _result_enabled(row["result"]):
            bucket["hits"] += 1
    items = []
    for key in sorted(buckets.keys()):
        bucket = buckets[key]
        bucket["misses"] = bucket["total"] - bucket["hits"]
        bucket["hit_rate"] = round(bucket["hits"] / bucket["total"], 4) if bucket["total"] else 0.0
        items.append(bucket)
    total = sum(item["total"] for item in items)
    return {
        "days": days,
        "total": total,
        "hits": sum(item["hits"] for item in items),
        "items": items,
    }


def flag_stats(flag):
    """单开关统计：评估量、命中率、原因与变体分布。"""
    logs = list(
        EvaluationLog.objects.filter(flag=flag)
        .order_by("-evaluated_at", "-id")
        .values("result", "matched_rule", "user_key", "evaluated_at")[:2000]
    )
    hits = sum(1 for row in logs if _result_enabled(row["result"]))
    reasons = {}
    variants = {}
    for row in logs:
        reasons[row["matched_rule"]] = reasons.get(row["matched_rule"], 0) + 1
        variant = str((row["result"] or {}).get("variant") or "unknown")
        variants[variant] = variants.get(variant, 0) + 1
    return {
        "flag_id": flag.id,
        "flag_key": flag.key,
        "evaluations": len(logs),
        "hits": hits,
        "hit_rate": round(hits / len(logs), 4) if logs else 0.0,
        "unique_users": len({row["user_key"] for row in logs}),
        "reasons": [
            {"reason": key, "count": value}
            for key, value in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
        ],
        "variants": [
            {"variant": key, "count": value}
            for key, value in sorted(variants.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def project_stats(project):
    """项目统计：环境/开关/细分/实验/灰度与近 7 天评估。"""
    flags = Flag.objects.filter(project=project)
    rollouts = Rollout.objects.filter(flag__project=project)
    logs = EvaluationLog.objects.filter(flag__project=project)
    since = now() - timedelta(days=7)
    recent = logs.filter(evaluated_at__gte=since)
    total = recent.count()
    hits = 0
    for result in recent.values_list("result", flat=True)[:5000]:
        if _result_enabled(result):
            hits += 1
    return {
        "project_id": project.id,
        "environments": project.environments.count(),
        "flags": flags.count(),
        "active_flags": flags.filter(status="active").count(),
        "archived_flags": flags.filter(status="archived").count(),
        "segments": project.segments.count(),
        "audiences": project.audiences.count(),
        "experiments": Experiment.objects.filter(flag__project=project).count(),
        "running_experiments": Experiment.objects.filter(
            flag__project=project, status="running").count(),
        "rollouts": rollouts.count(),
        "running_rollouts": rollouts.filter(status="running").count(),
        "evaluations_7d": total,
        "hit_rate_7d": round(hits / total, 4) if total else 0.0,
    }


def experiment_board(user, limit=20):
    """实验看板：状态分布 + 每个实验的进度。"""
    experiments = list(visible(Experiment.objects.select_related("flag"), user)
                       .order_by("-created_at", "-id")[:500])
    status_count = {key: 0 for key in EXPERIMENT_STATUS}
    rows = []
    for experiment in experiments:
        status_count[experiment.status] = status_count.get(experiment.status, 0) + 1
        if len(rows) >= clamp(int(limit or 20), 1, 100):
            continue
        progress = experiment_progress(experiment)
        rows.append({
            "experiment_id": experiment.id,
            "name": experiment.name,
            "flag_id": experiment.flag_id,
            "flag_key": experiment.flag.key,
            "status": experiment.status,
            "total_exposures": progress["total_exposures"],
            "target": progress["target"],
            "percent": progress["percent"],
            "sample_ready": progress["sample_ready"],
            "start_at": experiment.start_at,
        })
    return {
        "experiments": len(experiments),
        "status": status_count,
        "items": rows,
        "count": len(rows),
    }
