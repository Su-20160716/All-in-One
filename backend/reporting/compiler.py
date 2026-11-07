# -*- coding: utf-8 -*-
"""数据集编译器：结构化过滤 JSON → ORM Q，字段/聚合 → 安全 SELECT。

安全边界
--------
- 输入的 field 一律走 ``whitelist.resolve_path``（真实字段/关系/JSON 键校验）；
- 操作符是固定白名单（``OPERATORS``），拼 lookup 时用 ``f"{path}__{lookup}"``，
  路径本身已被限定为字母数字下划线，不存在注入面；
- 值按字段类型做强制转换（日期/数字/布尔），IN 列表长度上限 200；
- 不执行任何裸 SQL，聚合只用 Django 内置聚合函数。

能力
----
1. 过滤：eq/neq/gt/gte/lt/lte/in/notin/contains/startswith/isnull/between/relative；
   支持 and/or 嵌套、``$参数`` 占位、日期相对区间（today/last_7d/last_month…），
   以及「整体时间平移」（KPI 同比/环比复算上一个周期）。
2. 分组聚合：维度 values + 指标 annotate（count/sum/avg/min/max/count_distinct），
   median 用「取原始值 + Python 中位数」模拟（ORM 无 median 聚合）。
3. 时间分桶：TruncHour/Day/Week/Month/Quarter/Year，并支持补零序列。
4. having：对聚合别名再过滤（前端「只看 TOP N 分组」）。
5. 关联：DatasetJoin 校验关系真实指向目标模型，inner 用 isnull=False 收窄。
6. 排序与分页：排序列必须是输出列，limit 上限 2000，offset 非负。
"""
import math
from datetime import date, datetime, time as dtime, timedelta

from django.db.models import (
    Avg, Count, F, Max, Min, Q, Sum,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from reporting.whitelist import (
    get_whitelisted_model, group_expression, numeric_expression, resolve_path,
    same_relation_target, value_expression,
)

MAX_LIMIT = 2000
DEFAULT_LIMIT = 200
MAX_IN_VALUES = 200
MAX_HAVING = 50
MAX_MEDIAN_SCAN = 20000
MAX_GROUPS = 5000

# 操作符 → ORM lookup（None 表示特殊处理）
OPERATORS = {
    "eq": "",
    "neq": "",
    "gt": "gt",
    "gte": "gte",
    "lt": "lt",
    "lte": "lte",
    "in": "in",
    "notin": "",
    "contains": "icontains",
    "startswith": "istartswith",
    "isnull": "isnull",
    "between": "",
    "relative": "",
}

# 支持相对日期的快捷关键字：(单位, 偏移量, 是否对齐到周期起点, 是否含今天)
RELATIVE_KEYWORDS = {
    "today": ("day", 0, True, True),
    "yesterday": ("day", -1, True, True),
    "tomorrow": ("day", 1, True, True),
    "this_week": ("week", 0, True, True),
    "last_week": ("week", -1, True, True),
    "this_month": ("month", 0, True, True),
    "last_month": ("month", -1, True, True),
    "this_quarter": ("quarter", 0, True, True),
    "last_quarter": ("quarter", -1, True, True),
    "this_year": ("year", 0, True, True),
    "last_year": ("year", -1, True, True),
    "ytd": ("year", 0, True, True),
    "last_7d": ("day", -7, False, True),
    "last_14d": ("day", -14, False, True),
    "last_30d": ("day", -30, False, True),
    "last_90d": ("day", -90, False, True),
    "last_180d": ("day", -180, False, True),
    "last_365d": ("day", -365, False, True),
    "last_12m": ("month", -12, False, True),
    "next_7d": ("day", 7, False, False),
    "next_30d": ("day", 30, False, False),
}

AGG_FUNCS = {
    "sum": Sum,
    "avg": Avg,
    "min": Min,
    "max": Max,
}


# ---------------------------------------------------------------------------
# 值归一化
# ---------------------------------------------------------------------------


def _coerce_number(raw, label="值"):
    try:
        num = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} 必须是数字：{raw}")
    if not math.isfinite(num):
        raise ValueError(f"{label} 必须是有限数字")
    return num


def _coerce_bool(raw):
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ("1", "true", "yes", "on")


def _parse_date(raw, label="日期"):
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{label} 不能为空")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise ValueError(f"{label} 需为 YYYY-MM-DD：{text}")


def _parse_datetime(raw, label="时间"):
    text = str(raw or "").strip()
    if not text:
        raise ValueError(f"{label} 不能为空")
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError(f"{label} 需为 ISO 格式：{text}")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def coerce_value(resolved, raw):
    """按字段类型强转值（前端传字符串也能正确比较）。"""
    ftype = resolved.get("type")
    if raw is None:
        return None
    if ftype == "integer":
        return int(round(_coerce_number(raw, "字段值")))
    if ftype in ("number", "decimal"):
        return _coerce_number(raw, "字段值")
    if ftype == "bool":
        return _coerce_bool(raw)
    if ftype == "date":
        return _parse_date(raw)
    if ftype == "datetime":
        return _parse_datetime(raw)
    if isinstance(raw, (dict, list)):
        raise ValueError("文本字段的取值不能是对象/数组")
    return str(raw)


# ---------------------------------------------------------------------------
# 相对日期
# ---------------------------------------------------------------------------


def _month_start(d):
    return d.replace(day=1)


def _add_months(d, months):
    """月加减：先把日压到 1 号再加，避免 1/31 +1 月溢出到 3/3。"""
    month_index = (d.year * 12 + d.month - 1) + int(months)
    year, month = divmod(month_index, 12)
    month += 1
    day = min(d.day, 28)
    while True:
        try:
            return d.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def _quarter_start(d):
    return d.replace(month=((d.month - 1) // 3) * 3 + 1, day=1)


def _period_start(d, unit):
    if unit == "hour":
        return d.replace(minute=0, second=0, microsecond=0)
    if unit == "day":
        return d
    if unit == "week":
        return d - timedelta(days=d.weekday())
    if unit == "month":
        return _month_start(d)
    if unit == "quarter":
        return _quarter_start(d)
    if unit == "year":
        return d.replace(month=1, day=1)
    raise ValueError(f"不支持的时间单位：{unit}")


def _period_end(start, unit):
    """周期的下一个起点（左闭右开区间的右端）。"""
    if unit == "hour":
        return start + timedelta(hours=1)
    if unit == "day":
        return start + timedelta(days=1)
    if unit == "week":
        return start + timedelta(days=7)
    if unit == "month":
        return _add_months(start + timedelta(days=1), 1)
    if unit == "quarter":
        return _add_months(start + timedelta(days=1), 3)
    if unit == "year":
        return start.replace(year=start.year + 1)
    raise ValueError(f"不支持的时间单位：{unit}")


def resolve_relative(raw, shift=None):
    """相对日期 → (start, end) 左闭右开区间（date 或 aware datetime）。

    支持三种写法：
    - 关键字字符串：``last_30d`` / ``this_month`` / ``ytd``
    - ``{"amount": -7, "unit": "day"}``（amount 为负表示过去）
    - ``{"start": "2024-01-01", "end": "2024-02-01"}`` 显式区间（便于前端回放）
    ``shift`` 用于同比/环比：{"months": -1} 或 {"days": -7}。
    """
    now = timezone.localtime()
    as_dt = False
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in RELATIVE_KEYWORDS:
            unit, amount, align, include_today = RELATIVE_KEYWORDS[key]
            base = now.date() if align or unit in ("week", "month", "quarter", "year") else now.date()
            if key in ("this_week", "this_month", "this_quarter", "this_year", "ytd"):
                start = _period_start(base, unit)
                end = _period_end(start, unit)
                if key == "ytd":
                    end = date(base.year + 1, 1, 1)
            else:
                if unit in ("week", "month", "quarter", "year"):
                    anchor = _period_start(base, unit)
                    start = _add_months(anchor, amount) if unit in ("month", "quarter", "year") else (
                        anchor + timedelta(days=amount * 7) if unit == "week" else anchor
                    )
                    end = _period_end(start, unit)
                else:
                    end_base = base + timedelta(days=1) if include_today else base
                    start = base + timedelta(days=amount)
                    end = end_base
            as_dt = isinstance(start, datetime)
        else:
            raise ValueError(f"不支持的相对日期关键字：{raw}")
    elif isinstance(raw, dict):
        if "start" in raw or "end" in raw:
            start = _parse_date(raw.get("start") or "1970-01-01")
            end = _parse_date(raw.get("end")) if raw.get("end") else (now.date() + timedelta(days=1))
            if end <= start:
                raise ValueError("相对日期的结束必须晚于开始")
        else:
            unit = str(raw.get("unit") or "day")
            if unit not in ("hour", "day", "week", "month", "quarter", "year"):
                raise ValueError(f"相对日期单位不支持：{unit}")
            try:
                amount = int(raw.get("amount", -7))
            except (TypeError, ValueError):
                raise ValueError("相对日期的 amount 必须是整数")
            direction = str(raw.get("direction") or "past")
            if direction == "future" and amount > 0:
                amount = -amount
            end_ref = now if unit == "hour" else now.date()
            start = _shift_time(end_ref, unit, amount)
            end = end_ref + timedelta(days=1) if unit != "hour" else end_ref + timedelta(hours=1)
            as_dt = unit == "hour"
    else:
        raise ValueError("relative 的取值必须是关键字或对象")

    # 同比/环比平移：区间整体挪动，而不是重算「现在」，否则跨周期边界会漂
    if shift:
        months = int(shift.get("months") or 0)
        days = int(shift.get("days") or 0)
        if months:
            start = _add_months(start, months)
            end = _add_months(end, months)
        if days:
            start = start + timedelta(days=days)
            end = end + timedelta(days=days)

    # 统一成 date（低精度字段）或 aware datetime（高精度字段）
    if as_dt:
        if not isinstance(start, datetime):
            start = timezone.make_aware(datetime.combine(start, dtime.min))
        if not isinstance(end, datetime):
            end = timezone.make_aware(datetime.combine(end, dtime.min))
        return start, end
    if isinstance(start, datetime):
        start = timezone.localtime(start).date()
    if isinstance(end, datetime):
        end = timezone.localtime(end).date()
    return start, end


def _shift_time(ref, unit, amount):
    if isinstance(ref, datetime):
        if unit == "hour":
            return ref + timedelta(hours=amount)
        if unit == "day":
            return ref + timedelta(days=amount)
        if unit == "week":
            return ref + timedelta(weeks=amount)
        if unit in ("month", "quarter", "year"):
            months = amount * {"month": 1, "quarter": 3, "year": 12}[unit]
            return _add_months(ref, months)
    if unit == "day":
        return ref + timedelta(days=amount)
    if unit == "week":
        return ref + timedelta(weeks=amount)
    if unit in ("month", "quarter", "year"):
        months = amount * {"month": 1, "quarter": 3, "year": 12}[unit]
        return _add_months(ref, months)
    raise ValueError(f"不支持的时间单位：{unit}")


def shift_for_comparison(comparison):
    """KPI 对照周期 → 区间平移量。

    同比按「上一个自然年」、环比按「上一个自然月」、周环比按 7 天；
    comparison 为空/``none`` 返回 None（不做二次执行）。
    """
    table = {
        "yoy": {"months": -12},
        "mom": {"months": -1},
        "qoq": {"months": -3},
        "wow": {"days": -7},
        "dod": {"days": -1},
    }
    if not comparison or comparison == "none":
        return None
    if comparison not in table:
        raise ValueError(f"不支持对照周期：{comparison}（yoy/mom/qoq/wow/dod）")
    return table[comparison]


# ---------------------------------------------------------------------------
# 参数占位
# ---------------------------------------------------------------------------


def _resolve_placeholder(raw, params):
    """``$name`` / ``{"$param": "name"}`` → 实际参数值；缺参即报错。"""
    if isinstance(raw, dict) and "$param" in raw:
        name = str(raw.get("$param") or "")
        if name not in params:
            raise ValueError(f"缺少数据集参数：{name}")
        return params[name]
    if isinstance(raw, str) and raw.startswith("$") and len(raw) > 1:
        name = raw[1:]
        if name not in params:
            raise ValueError(f"缺少数据集参数：{name}")
        return params[name]
    return raw


# ---------------------------------------------------------------------------
# 过滤编译
# ---------------------------------------------------------------------------


def compile_filter(model, spec, params=None, shift=None):
    """把结构化过滤 JSON 编译成 Q 对象（空配置 → 全量）。

    支持形态：
    - ``None`` / ``{}``：不过滤
    - ``{"field": "status", "op": "eq", "value": "active"}``
    - ``{"and": [...]}`` / ``{"or": [...]}``（可嵌套）
    - ``{"logic": "or", "filters": [...]}``
    - 列表：按 AND 处理
    """
    params = params or {}
    if spec in (None, {}, []):
        return Q()
    if isinstance(spec, list):
        return _combine([Q(_clause(model, c, params, shift)) for c in spec], "and")
    if not isinstance(spec, dict):
        raise ValueError("过滤条件必须是对象或数组")
    if "and" in spec or "or" in spec:
        if "and" in spec and "or" in spec:
            raise ValueError("and 与 or 不能同时出现在同一层")
        key = "and" if "and" in spec else "or"
        children = spec.get(key)
        if not isinstance(children, list):
            raise ValueError(f"{key} 的值必须是数组")
        if len(children) > 100:
            raise ValueError("单个逻辑组的条件不能超过 100 条")
        return _combine([Q(_clause(model, c, params, shift)) for c in children], key)
    if "filters" in spec:
        children = spec.get("filters")
        logic = str(spec.get("logic") or "and").lower()
        if logic not in ("and", "or"):
            raise ValueError("logic 只支持 and / or")
        if not isinstance(children, list):
            raise ValueError("filters 必须是数组")
        return _combine([Q(_clause(model, c, params, shift)) for c in children], logic)
    if "field" in spec:
        return Q(_clause(model, spec, params, shift))
    raise ValueError("过滤条件格式不支持：缺少 field / and / or / filters")


def _combine(qs, logic):
    out = Q()
    for q in qs:
        out = (out & q) if logic == "and" else (out | q)
    return out


def _clause(model, clause, params, shift):
    if not isinstance(clause, dict):
        raise ValueError("过滤条件项必须是对象")
    field = str(clause.get("field") or "").strip()
    if not field:
        raise ValueError("过滤条件缺少 field")
    op = str(clause.get("op") or clause.get("operator") or "eq").lower()
    if op not in OPERATORS:
        raise ValueError(f"不支持的操作符：{op}")
    resolved = resolve_path(model, field)
    if resolved.get("relation") and not resolved.get("is_json"):
        # 以关系字段结尾时比较的是外键值，类型按整数处理更直观
        if op not in ("eq", "neq", "in", "notin", "isnull"):
            raise ValueError(f"关系字段 {field} 只支持 eq/neq/in/notin/isnull")
    raw = _resolve_placeholder(clause.get("value"), params)
    path = resolved["orm_path"]

    if op == "isnull":
        if raw is None:
            raise ValueError("isnull 需要显式布尔值")
        return Q(**{f"{path}__isnull": _coerce_bool(raw)})

    if op == "relative":
        if raw in (None, ""):
            raise ValueError("relative 需要时间关键字或区间")
        start, end = resolve_relative(raw, shift)
        return Q(**{f"{path}__gte": start}) & Q(**{f"{path}__lt": end})

    if raw is None:
        # eq/neq 传 null 等价于 isnull
        if op == "eq":
            return Q(**{f"{path}__isnull": True})
        if op == "neq":
            return Q(**{f"{path}__isnull": False})
        raise ValueError(f"操作符 {op} 的值不能为空")

    if op == "between":
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ValueError("between 的值必须是长度为 2 的数组")
        low = coerce_value(resolved, _resolve_placeholder(raw[0], params))
        high = coerce_value(resolved, _resolve_placeholder(raw[1], params))
        if low is None or high is None:
            raise ValueError("between 的端点不能为空")
        if low > high:
            raise ValueError("between 的起始值不能大于结束值")
        return Q(**{f"{path}__gte": low}) & Q(**{f"{path}__lte": high})

    if op in ("in", "notin"):
        if not isinstance(raw, (list, tuple)):
            raise ValueError(f"{op} 的值必须是数组")
        if not raw:
            # 空集合语义明确：in 空 = 永假，notin 空 = 恒真
            return Q(pk__in=[]) if op == "in" else Q()
        if len(raw) > MAX_IN_VALUES:
            raise ValueError(f"{op} 的取值不能超过 {MAX_IN_VALUES} 个")
        values = [coerce_value(resolved, _resolve_placeholder(v, params)) for v in raw]
        values = [v for v in values if v is not None]
        if op == "in":
            return Q(**{f"{path}__in": values})
        return ~Q(**{f"{path}__in": values})

    value = coerce_value(resolved, raw)

    if op == "contains":
        if len(str(value)) > 200:
            raise ValueError("contains 的匹配串过长（上限 200）")
    if op == "startswith":
        if len(str(value)) > 200:
            raise ValueError("startswith 的匹配串过长（上限 200）")

    lookup = OPERATORS[op]
    key = f"{path}__{lookup}" if lookup else path
    if op == "neq":
        return ~Q(**{key: value})
    return Q(**{key: value})


def validate_filter(model, spec, params=None):
    """只编译不执行，用于保存数据集时的配置校验。"""
    compile_filter(model, spec, params)
    return True


# ---------------------------------------------------------------------------
# 数据集规格（spec）
# ---------------------------------------------------------------------------

FIELD_SPEC_KEYS = ("path", "alias", "ftype", "aggregate", "is_group", "bucket", "order", "fmt", "visible")


def _field_spec(row):
    out = {
        "path": str(row.get("path") or "").strip(),
        "alias": str(row.get("alias") or "").strip(),
        "ftype": str(row.get("ftype") or "string"),
        "aggregate": str(row.get("aggregate") or "none"),
        "is_group": bool(row.get("is_group")),
        "bucket": str(row.get("bucket") or ""),
        "order": int(row.get("order") or 0),
        "fmt": str(row.get("fmt") or ""),
        "visible": bool(row.get("visible", True)),
    }
    if not out["path"]:
        raise ValueError("字段路径不能为空")
    if out["aggregate"] not in ("none", "count", "sum", "avg", "min", "max",
                                "count_distinct", "median"):
        raise ValueError(f"不支持的聚合函数：{out['aggregate']}")
    if out["bucket"] and out["bucket"] not in ("hour", "day", "week", "month", "quarter", "year"):
        raise ValueError(f"不支持的时间分桶：{out['bucket']}")
    return out


def dataset_spec(dataset, overrides=None):
    """把 Dataset 及其子表转成编译器可消费的纯字典 spec。

    overrides 支持字段级覆盖：``fields`` / ``filter`` / ``distinct_fields`` /
    ``order`` / ``limit`` / ``offset`` —— 预览与组件可以用同一份数据集但
    临时换筛选，不必先落库。
    """
    fields = []
    for f in dataset.rep_dataset_fields.all().order_by("order", "id"):
        fields.append({
            "path": f.path,
            "alias": f.alias,
            "ftype": f.ftype,
            "aggregate": f.aggregate,
            "is_group": f.is_group,
            "bucket": f.bucket,
            "order": f.order,
            "fmt": f.fmt,
            "visible": f.visible,
        })
    joins = []
    for j in dataset.rep_dataset_joins.all().order_by("order", "id"):
        joins.append({
            "target_model": j.target_model,
            "via": j.via,
            "left_field": j.left_field,
            "right_field": j.right_field,
            "join_type": j.join_type,
            "order": j.order,
        })
    params = {}
    for p in dataset.rep_dataset_params.all():
        params[p.name] = {
            "type": p.ptype,
            "default": p.default,
            "required": p.required,
        }
    spec = {
        "model": dataset.primary_model,
        "filter": dataset.filter or {},
        "distinct_fields": dataset.distinct_fields or [],
        "fields": fields,
        "joins": joins,
        "params": params,
        "limit": int(dataset.default_limit or DEFAULT_LIMIT),
        "offset": 0,
        "order": [],
        "having": [],
        "shift": None,
    }
    if overrides:
        spec = merge_overrides(spec, overrides)
    return spec


def merge_overrides(spec, overrides):
    """合并预览/组件的临时覆盖（浅合并 + 字段整体替换）。"""
    out = dict(spec)
    if not isinstance(overrides, dict):
        return out
    if "fields" in overrides:
        raw_fields = overrides.get("fields")
        if not isinstance(raw_fields, list):
            raise ValueError("fields 必须是数组")
        if len(raw_fields) > 80:
            raise ValueError("字段数量不能超过 80")
        out["fields"] = [_field_spec(f) for f in raw_fields]
    if "filter" in overrides:
        out["filter"] = overrides.get("filter") or {}
    if "having" in overrides:
        out["having"] = normalize_having(overrides.get("having"))
    if "distinct_fields" in overrides:
        raw = overrides.get("distinct_fields") or []
        if not isinstance(raw, list) or len(raw) > 10:
            raise ValueError("distinct_fields 最多 10 个字段")
        out["distinct_fields"] = [str(x) for x in raw]
    if "limit" in overrides and overrides.get("limit") is not None:
        out["limit"] = clamp_limit(overrides.get("limit"))
    if "offset" in overrides and overrides.get("offset") is not None:
        out["offset"] = clamp_offset(overrides.get("offset"))
    if "order" in overrides and overrides.get("order"):
        out["order"] = normalize_order(overrides.get("order"))
    if "shift" in overrides:
        out["shift"] = overrides.get("shift")
    return out


def normalize_having(raw):
    """having 规整：``[{"key": "total", "op": "gt", "value": 10}]``。"""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError("having 必须是数组")
    if len(raw) > MAX_HAVING:
        raise ValueError(f"having 条件不能超过 {MAX_HAVING} 条")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("having 的每一项必须是对象")
        key = str(item.get("key") or item.get("field") or "").strip()
        op = str(item.get("op") or item.get("operator") or "gt").lower()
        if not key:
            raise ValueError("having 缺少 key")
        if op not in ("gt", "gte", "lt", "lte", "eq", "neq"):
            raise ValueError(f"having 不支持的操作符：{op}")
        value = _coerce_number(item.get("value"), "having 值")
        out.append({"key": key, "op": op, "value": value})
    return out


def normalize_order(raw):
    """排序规整：``"name"`` / ``"-total""`` / ``[{"key": "total", "desc": true}]``。"""
    out = []
    items = raw if isinstance(raw, list) else str(raw).split(",")
    for item in items:
        if isinstance(item, dict):
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            out.append(f"-{key}" if item.get("desc") or item.get("order") == "desc" else key)
            continue
        text = str(item or "").strip()
        if not text:
            continue
        out.append(text)
    if len(out) > 10:
        raise ValueError("排序字段不能超过 10 个")
    return out


def clamp_limit(value, default=DEFAULT_LIMIT, maximum=MAX_LIMIT):
    try:
        num = int(value)
    except (TypeError, ValueError):
        raise ValueError("limit 必须是整数")
    if num <= 0:
        raise ValueError("limit 必须大于 0")
    return min(num, maximum)


def clamp_offset(value):
    try:
        num = int(value)
    except (TypeError, ValueError):
        raise ValueError("offset 必须是整数")
    if num < 0:
        raise ValueError("offset 不能为负")
    return num


def resolve_params(spec, provided):
    """合并参数默认值并校验必填；未知参数忽略（前端可多传）。"""
    declared = spec.get("params") or {}
    merged = {}
    for name, meta in declared.items():
        if isinstance(meta, dict):
            if provided and name in provided:
                merged[name] = provided[name]
            elif meta.get("default") is not None:
                merged[name] = meta.get("default")
            elif meta.get("required"):
                raise ValueError(f"缺少必填参数：{name}")
        elif provided and name in provided:
            merged[name] = provided[name]
    for name, value in (provided or {}).items():
        merged.setdefault(name, value)
    return merged


# ---------------------------------------------------------------------------
# 聚合与执行
# ---------------------------------------------------------------------------


def _aggregate_expression(resolved, agg):
    if agg == "count":
        return Count(F(resolved["orm_path"]))
    if agg == "count_distinct":
        return Count(F(resolved["orm_path"]), distinct=True)
    if agg in ("sum", "avg"):
        return AGG_FUNCS[agg](numeric_expression(resolved))
    if agg in ("min", "max"):
        if resolved.get("type") in ("integer", "number", "decimal") or resolved.get("is_json"):
            return AGG_FUNCS[agg](numeric_expression(resolved))
        return AGG_FUNCS[agg](F(resolved["orm_path"]))
    raise ValueError(f"不支持的聚合函数：{agg}")


def _json_safe(value):
    from decimal import Decimal

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        local = timezone.localtime(value) if timezone.is_aware(value) else value
        return local.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    try:
        return str(value)
    except Exception:  # noqa: BLE001 —— 极端对象降级成字符串，不让序列化炸掉整张报表
        return None


def _prepare_joins(model, joins):
    """应用关联：返回 (qs 修饰函数, 关联明细)。inner join 用 isnull=False 实现。"""
    applied = []
    for j in joins:
        via = str(j.get("via") or "").strip()
        target = str(j.get("target_model") or "").strip()
        if not via or not target:
            raise ValueError("关联配置缺少 via / target_model")
        same_relation_target(model, via, target)
        join_type = str(j.get("join_type") or "left")
        if join_type not in ("left", "inner"):
            raise ValueError("join_type 只支持 left / inner")
        applied.append({"via": via, "target_model": target, "join_type": join_type,
                        "left_field": j.get("left_field", ""),
                        "right_field": j.get("right_field", "")})
    return applied


def compile_query(spec, params=None, shift=None):
    """编译 + 执行，返回 {columns, rows, meta}（前端可直接渲染）。

    这是「数据集执行」的唯一实现：预览、组件取数、报表执行、导出、质量检查
    全部复用，保证口径一致。
    """
    model_label = str(spec.get("model") or "")
    model = get_whitelisted_model(model_label)
    joins = _prepare_joins(model, spec.get("joins") or [])

    fields = []
    for raw in spec.get("fields") or []:
        item = _field_spec(raw)
        resolved = resolve_path(model, item["path"])
        item["_resolved"] = resolved
        item["key"] = item["alias"] or item["path"].replace(".", "_")
        fields.append(item)
    if len({f["key"] for f in fields}) != len(fields):
        raise ValueError("字段别名重复，请检查 alias")
    if len(fields) > 80:
        raise ValueError("字段数量不能超过 80")

    dims = [f for f in fields if f["aggregate"] == "none"]
    metrics = [f for f in fields if f["aggregate"] != "none"]
    median_metrics = [f for f in metrics if f["aggregate"] == "median"]
    plain_metrics = [f for f in metrics if f["aggregate"] != "median"]

    if not dims and not metrics:
        pk = model._meta.pk
        dims = [{
            "path": pk.name, "alias": pk.name, "ftype": "integer", "aggregate": "none",
            "is_group": True, "bucket": "", "order": 0, "fmt": "", "visible": True,
            "key": pk.name, "_resolved": resolve_path(model, pk.name),
        }]

    # 输出列名可能与模型字段重名（如 pk 直接当维度、别名写成 owner_id），
    # annotate(**{key: ...}) 会撞上「字段已存在」。这里给冲突列换一个安全的
    # 内部键，同时映射 order/having，保证查询语义不变、返回列名仍然稳定。
    reserved = set()
    for field in model._meta.concrete_fields:
        reserved.add(field.name)
        reserved.add(field.attname)
    alias_map = {}
    used_keys = set()
    for f in dims + metrics:
        key = str(f["key"])
        if key in reserved or key in used_keys or key == "pk":
            base = f"{key}_col"
            candidate = base
            idx = 2
            while candidate in reserved or candidate in used_keys:
                candidate = f"{base}{idx}"
                idx += 1
            alias_map[key] = candidate
            f["key"] = candidate
        used_keys.add(f["key"])
    if alias_map:
        spec = dict(spec)
        mapped_order = []
        for token in spec.get("order") or []:
            text = str(token)
            sign = "-" if text.startswith("-") else ""
            base = text.lstrip("-")
            mapped_order.append(sign + alias_map.get(base, base))
        spec["order"] = mapped_order
        raw_having = spec.get("having") or []
        if isinstance(raw_having, list):
            mapped_having = []
            for item in raw_having:
                if isinstance(item, dict):
                    item = dict(item)
                    key = item.get("key") if item.get("key") is not None else item.get("field")
                    if key is not None and str(key) in alias_map:
                        item["key"] = alias_map[str(key)]
                mapped_having.append(item)
            spec["having"] = mapped_having

    merged_params = resolve_params(spec, params)
    # shift 既可以显式传（KPI 对照复算），也可以放在 spec 里（预览/导出回放）
    shift = shift or spec.get("shift")
    q_filter = compile_filter(model, spec.get("filter") or {}, merged_params, shift)

    qs = model._default_manager.all()
    if joins:
        for j in joins:
            select_path = j["via"]
            try:
                qs = qs.select_related(select_path)
            except Exception:  # noqa: BLE001 —— 链式关系 select_related 失败不影响过滤
                pass
            if j["join_type"] == "inner":
                qs = qs.filter(**{f"{select_path}__isnull": False})
    if q_filter:
        qs = qs.filter(q_filter)

    distinct_fields = spec.get("distinct_fields") or []
    distinct_paths = []
    for path in distinct_fields:
        resolved = resolve_path(model, path)
        distinct_paths.append(resolved["orm_path"])

    limit = clamp_limit(spec.get("limit") or DEFAULT_LIMIT)
    offset = clamp_offset(spec.get("offset") or 0)

    # 维度注解：key → 表达式（时间字段可带分桶）
    dim_ann = {}
    for f in dims:
        dim_ann[f["key"]] = group_expression(f["_resolved"], f.get("bucket") or "")

    metric_ann = {}
    for f in plain_metrics:
        metric_ann[f["key"]] = _aggregate_expression(f["_resolved"], f["aggregate"])

    warnings = []
    rows = []
    total = 0
    median_scanned = 0
    dim_keys = [f["key"] for f in dims]

    # 分组查询骨架：维度注解 → values（GROUP BY）→ 指标注解 → having
    grouped_qs = None
    if dims:
        grouped_qs = qs.annotate(**dim_ann).values(*dim_keys)
        if metric_ann:
            grouped_qs = grouped_qs.annotate(**metric_ann)
        grouped_qs = _apply_having(grouped_qs, spec.get("having") or [])
        if distinct_paths:
            grouped_qs = grouped_qs.distinct()
        grouped_qs = _apply_ordering(model, grouped_qs, spec, dims, metrics)

    if dims:
        if metric_ann:
            total = _safe_count(grouped_qs)
            try:
                rows = [dict(r) for r in grouped_qs[offset:offset + limit]]
            except Exception as e:  # noqa: BLE001 —— 执行期异常统一转 400 可读信息
                raise ValueError(f"数据集执行失败：{type(e).__name__}: {e}")
        elif median_metrics:
            scan = _median_scan(model, grouped_qs, dims, median_metrics, q_filter, joins)
            median_scanned = scan.get("scanned", 0)
            rows = _rows_from_median_groups(scan.get("groups") or {}, dim_keys, offset, limit)
            total = len(scan.get("groups") or {})
            rows = _sort_median_rows(rows, spec, dim_keys, median_metrics)
        else:
            total = _safe_count(grouped_qs)
            try:
                rows = [dict(r) for r in grouped_qs[offset:offset + limit]]
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"数据集执行失败：{type(e).__name__}: {e}")
    else:
        if metric_ann:
            try:
                aggregate_row = qs.aggregate(**metric_ann)
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"数据集执行失败：{type(e).__name__}: {e}")
            rows = [{k: v for k, v in aggregate_row.items()}]
            total = 1
        if median_metrics:
            scan = _median_scan(model, qs, dims, median_metrics, q_filter, joins)
            median_scanned = scan.get("scanned", 0)
            row = rows[0] if rows else {}
            for value in (scan.get("groups") or {}).values():
                row.update(value)
            for metric in median_metrics:
                row.setdefault(metric["key"], None)
            rows = [row]
            total = max(total, 1)

    if metric_ann and dims and median_metrics:
        scan = _median_scan(model, grouped_qs, dims, median_metrics, q_filter, joins)
        median_scanned = scan.get("scanned", 0)
        rows = _merge_medians(rows, scan.get("groups") or {}, dim_keys, median_metrics)

    rows = [{k: _json_safe(v) for k, v in dict(r).items()} for r in rows]

    if total > MAX_GROUPS and metric_ann:
        warnings.append(f"分组数超过 {MAX_GROUPS}，建议收窄过滤条件")

    columns = []
    for f in dims:
        columns.append({
            "key": f["key"],
            "label": f["alias"] or f["path"],
            "path": f["path"],
            "type": f["ftype"],
            "role": "dimension",
            "bucket": f.get("bucket") or "",
            "format": f.get("fmt") or "",
        })
    for f in metrics:
        columns.append({
            "key": f["key"],
            "label": f["alias"] or f"{f['aggregate']}({f['path']})",
            "path": f["path"],
            "type": "number" if f["aggregate"] not in ("count", "count_distinct") else "integer",
            "role": "metric",
            "aggregate": f["aggregate"],
            "format": f.get("fmt") or "",
        })

    # 排序键校验放在执行后，避免空结果时误判
    valid_keys = {c["key"] for c in columns}
    for token in (spec.get("order") or []):
        key = str(token).lstrip("-")
        if key not in valid_keys:
            raise ValueError(f"排序字段 {key} 不在输出列内")

    meta = {
        "model": model_label,
        "verbose_model": str(model._meta.verbose_name),
        "joins": joins,
        "params": merged_params,
        "group_by": [f["path"] for f in dims],
        "metrics": [{"key": f["key"], "aggregate": f["aggregate"]} for f in metrics],
        "distinct": distinct_paths,
        "total": total,
        "returned": len(rows),
        "limit": limit,
        "offset": offset,
        "order": spec.get("order") or [],
        "having": spec.get("having") or [],
        "shift": shift,
        "median_scanned": median_scanned,
        "warnings": warnings,
        "executed_at": timezone.now().isoformat(),
    }
    return {"columns": columns, "rows": rows, "meta": meta}


def _apply_having(qs, having):
    for item in normalize_having(having):
        key = item["key"]
        op = item["op"]
        if op == "neq":
            qs = qs.exclude(**{key: item["value"]})
        else:
            qs = qs.filter(**{f"{key}__{op}": item["value"]})
    return qs


def _apply_ordering(model, qs, spec, dims, metrics):
    tokens = list(spec.get("order") or [])
    if not tokens:
        # 默认：有指标按第一个指标倒序（TOP 视图最常用），否则维度正序
        if metrics:
            tokens = [f"-{metrics[0]['key']}"] + [f["key"] for f in dims]
        else:
            tokens = [f["key"] for f in dims]
    valid = {f["key"] for f in dims} | {f["key"] for f in metrics}
    cleaned = []
    for token in tokens:
        text = str(token)
        key = text.lstrip("-")
        if key not in valid:
            # 排序键非法时直接报错，静默忽略会让前端以为排序生效
            raise ValueError(f"排序字段 {key} 不在输出列内")
        cleaned.append(f"-{key}" if text.startswith("-") else key)
    if len(cleaned) > 10:
        raise ValueError("排序字段不能超过 10 个")
    return qs.order_by(*cleaned)


def _median_scan(model, qs, dims, median_metrics, q_filter, joins):
    """中位数模拟：取「维度 + 值」两列原始数据，按维度元组在 Python 里求中位数。

    ORM 没有 median 聚合；为了避免把全表拉进内存，扫描上限 20000 行，
    超出则在 meta.warnings 提示收窄过滤条件。
    """
    dim_keys = [f["key"] for f in dims]
    groups = {}
    scanned = 0
    for metric in median_metrics:
        resolved = metric["_resolved"]
        path = resolved["orm_path"]
        base = model._default_manager.all()
        for j in joins:
            if j["join_type"] == "inner":
                base = base.filter(**{f"{j['via']}__isnull": False})
        if q_filter:
            base = base.filter(q_filter)
        ann = {}
        for f in dims:
            ann[f["key"]] = group_expression(f["_resolved"], f.get("bucket") or "")
        if ann:
            base = base.annotate(**ann)
        values_qs = base.values(*dim_keys, path) if dim_keys else base.values(path)
        bucket_values = {}
        for row in values_qs.iterator(chunk_size=2000):
            scanned += 1
            if scanned > MAX_MEDIAN_SCAN:
                break
            group_key = tuple(row.get(k) for k in dim_keys) if dim_keys else ()
            raw = row.get(path)
            if raw is None:
                continue
            try:
                num = float(raw)
            except (TypeError, ValueError):
                continue
            bucket_values.setdefault(group_key, []).append(num)
        for group_key, numbers in bucket_values.items():
            numbers.sort()
            n = len(numbers)
            if not n:
                continue
            mid = n // 2
            median = numbers[mid] if n % 2 else (numbers[mid - 1] + numbers[mid]) / 2
            groups.setdefault(group_key, {})[metric["key"]] = round(median, 6)
    return {"groups": groups, "scanned": scanned}


def _merge_medians(rows, groups, dim_keys, median_metrics):
    if not dim_keys:
        row = dict(rows[0]) if rows else {}
        for value in groups.values():
            row.update(value)
        for metric in median_metrics:
            row.setdefault(metric["key"], None)
        return [row]
    for row in rows:
        key = tuple(row.get(k) for k in dim_keys)
        for metric in median_metrics:
            value = (groups.get(key) or {}).get(metric["key"])
            row[metric["key"]] = value
    return rows


def _safe_count(qs):
    """分组查询的 count 在复杂注解下可能失败：失败就返回 0（行数据仍可用）。"""
    try:
        return qs.count()
    except Exception:  # noqa: BLE001
        return 0


def _rows_from_median_groups(groups, dim_keys, offset, limit):
    """中位数分组 → 行列表（组键排序保证分页稳定）。"""
    keys = sorted(groups.keys(), key=lambda k: tuple("" if v is None else str(v) for v in k))
    rows = []
    for key in keys[offset:offset + limit]:
        row = {dim_keys[i]: _json_safe(v) for i, v in enumerate(key)}
        row.update(groups[key])
        rows.append(row)
    return rows


def _sort_median_rows(rows, spec, dim_keys, median_metrics):
    """中位数结果是 Python 组装的，排序也在这里做（仅支持输出列）。"""
    tokens = list(spec.get("order") or [])
    if not tokens:
        return rows
    keys = list(dim_keys) + [m["key"] for m in median_metrics]
    for token in reversed(tokens[:10]):
        text = str(token)
        key = text.lstrip("-")
        if key not in keys:
            raise ValueError(f"排序字段 {key} 不在输出列内")
        rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=text.startswith("-"))
    return rows


# ---------------------------------------------------------------------------
# 辅助能力：补零序列 / 枚举值 / 快速预览
# ---------------------------------------------------------------------------


def fill_bucket_gaps(rows, key, grain="month", limit=120):
    """折线图补零：缺失的时间桶补 0，避免「折线直连」造成误读。

    只对能解析成日期/时间的桶键生效；无法解析时原样返回。
    """
    if not rows or grain not in ("day", "week", "month", "quarter", "year"):
        return rows
    parsed = []
    for row in rows:
        raw = row.get(key)
        try:
            dt = _bucket_value(raw)
        except (TypeError, ValueError):
            return rows
        parsed.append((dt, row))
    parsed.sort(key=lambda pair: pair[0])
    if len(parsed) < 2:
        return rows
    start, end = parsed[0][0], parsed[-1][0]
    existing = {dt: row for dt, row in parsed}
    out = []
    cursor = start
    guard = 0
    while cursor <= end and guard < limit:
        row = existing.get(cursor)
        if row is None:
            row = {k: 0 for k in rows[0].keys() if k != key}
            row[key] = _serialize_bucket(cursor)
        out.append(row)
        cursor = _next_bucket(cursor, grain)
        guard += 1
    return out


def _bucket_value(raw):
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime.combine(raw, dtime.min)
    text = str(raw or "")
    if len(text) >= 19:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    if len(text) >= 10:
        return datetime.combine(date.fromisoformat(text[:10]), dtime.min)
    raise ValueError("不是时间桶")


def _serialize_bucket(dt):
    return dt.replace(microsecond=0).isoformat()


def _next_bucket(dt, grain):
    if grain == "day":
        return dt + timedelta(days=1)
    if grain == "week":
        return dt + timedelta(days=7)
    if grain == "month":
        return _add_months(dt, 1)
    if grain == "quarter":
        return _add_months(dt, 3)
    return dt.replace(year=dt.year + 1)


def distinct_values(model_label, path, filter_spec=None, limit=100, params=None):
    """字段取值枚举：给筛选器下拉用（带命中次数，按次数倒序）。"""
    model = get_whitelisted_model(model_label)
    resolved = resolve_path(model, path)
    limit = clamp_limit(limit, maximum=500)
    qs = model._default_manager.all()
    q = compile_filter(model, filter_spec or {}, params or {})
    if q:
        qs = qs.filter(q)
    values_qs = (
        qs.values(**{"v": F(resolved["orm_path"])})
        .annotate(c=Count("pk"))
        .order_by("-c")[:limit]
    )
    items = []
    for row in values_qs:
        items.append({"value": _json_safe(row.get("v")), "count": row.get("c", 0)})
    return {"field": path, "type": resolved["type"], "items": items, "count": len(items)}


def quick_preview(model_label, filter_spec=None, fields=None, limit=20, params=None,
                  order=None, group_by=None, aggregates=None):
    """无需先建数据集的即时预览（给「选模型 → 试一下」场景）。

    fields: [{"path","alias","aggregate","is_group","bucket"}]，为空则取模型前 8 个字段。
    """
    model = get_whitelisted_model(model_label)
    if not fields:
        picked = []
        for field in model._meta.concrete_fields[:8]:
            picked.append({"path": field.name, "alias": field.name, "ftype": "string"})
        fields = picked
    spec = {
        "model": model_label,
        "filter": filter_spec or {},
        "fields": fields,
        "joins": [],
        "params": {},
        "limit": clamp_limit(limit, maximum=500),
        "offset": 0,
        "order": normalize_order(order) if order else [],
        "having": [],
        "distinct_fields": [],
        "shift": None,
    }
    return compile_query(spec, params or {})


def preview_count(model_label, filter_spec=None, params=None):
    """命中行数（编辑数据集时实时展示「这个条件能选多少行」）。"""
    model = get_whitelisted_model(model_label)
    q = compile_filter(model, filter_spec or {}, params or {})
    qs = model._default_manager.all()
    if q:
        qs = qs.filter(q)
    return qs.count()


def coalesce_zero(expr):
    """数值列补 0：图表里 SUM 为 NULL 的组应显示 0 而不是空。"""
    return Coalesce(expr, 0.0)
