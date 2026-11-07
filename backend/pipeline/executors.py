# -*- coding: utf-8 -*-
"""节点执行器：全部在内存中对行集做真实计算。

行集统一是 ``list[dict]``。选择这个形态而不是 pandas / numpy：
- 平台不允许新增依赖，标准库已经够用；
- 单次上限 5000 行，纯 Python 的吞吐完全够，字典行也最贴近 JSON；
- 出错时能精确到「第几行、哪个字段」，而不是一个 DataFrame 栈。

执行器只依赖一个 ``ctx``（运行上下文）协议：
``limit`` / ``check_timeout()`` / ``log()`` / ``mapping_rows()`` /
``write_outputs()`` / ``deliver_webhook()``，由 runner 注入；
这样节点逻辑可以脱离数据库单独测试。
"""
from __future__ import annotations

import json
import math
from functools import cmp_to_key

from pipeline.catalog import (AGG_FUNCS, DEDUPE_KEEP, JOIN_TYPES,
                              TRANSFORM_OPS)
from pipeline.expressions import (ExprError, cast_value, evaluate_condition,
                                  evaluate_expression, to_bool, to_number,
                                  to_text)
from pipeline.generators import source_rows

_MISSING = object()


# ---------------------------------------------------------------------------
# 行 / 字段工具
# ---------------------------------------------------------------------------


def get_path(row: dict, path: str, default=None):
    """按 ``a.b.c`` 取值；先尝试整键（字段名本身可能带点）。"""
    if not isinstance(row, dict) or not path:
        return default
    if path in row:
        return row[path]
    current = row
    for part in str(path).split("."):
        if isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return current


def set_path(row: dict, path: str, value) -> None:
    """按 ``a.b`` 写入；中间层不是对象时覆盖成对象，避免静默丢值。"""
    parts = str(path).split(".")
    current = row
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value


def delete_path(row: dict, path: str) -> None:
    """删除字段（支持点路径）；不存在时静默忽略。"""
    if path in row:
        row.pop(path, None)
        return
    parts = str(path).split(".")
    current = row
    for part in parts[:-1]:
        current = current.get(part) if isinstance(current, dict) else None
        if not isinstance(current, dict):
            return
    if isinstance(current, dict):
        current.pop(parts[-1], None)


def _norm_key(value) -> str:
    """把任意值折叠成可哈希的稳定键：1 与 "1" 视为同键，空值统一 ""。"""
    if value is None:
        return "\x00null"
    if isinstance(value, bool):
        return "b:1" if value else "b:0"
    if isinstance(value, (int, float)):
        num = float(value)
        if math.isnan(num):
            return "\x00nan"
        return f"n:{num:.12g}"
    if isinstance(value, (dict, list, tuple)):
        try:
            return "j:" + json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      default=str)
        except (TypeError, ValueError):
            return "s:" + str(value)
    text = str(value).strip()
    num = to_number(text)
    if num is not None and text not in ("", "-"):
        return f"n:{float(num):.12g}"
    return "s:" + text.lower()


def row_key(row: dict, keys: list[str]) -> tuple:
    """组合键：字段缺失等价于空值，避免 KeyError 中断整批。"""
    return tuple(_norm_key(get_path(row, key)) for key in keys)


def _keys(value, name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v).strip()]
    raise ValueError(f"参数 {name} 必须是字段名或字段数组")


def _limit(rows, ctx, label: str) -> list:
    """统一行数护栏：任何节点的输出都不能突破单次运行上限。"""
    limit = int(getattr(ctx, "limit", 5000) or 5000)
    if len(rows) > limit:
        raise ValueError(f"{label}输出 {len(rows)} 行，超过单次上限 {limit}")
    return rows


def _sample(rows, size: int = 3) -> list[dict]:
    return [dict(r) for r in rows[:size]]


def merge_inputs(inputs: dict, order: list[str] | None = None) -> list[dict]:
    """把多端口输入合并成一个行集；端口顺序决定合并顺序（确定性）。"""
    ports = order or sorted(inputs.keys())
    rows: list[dict] = []
    for port in ports:
        rows.extend(inputs.get(port) or [])
    return rows


def _primary_rows(inputs: dict, preferred=("in", "pass", "out")) -> list[dict]:
    """取主输入：优先 in / pass / out，找不到再合并全部端口。"""
    for port in preferred:
        if port in inputs and inputs[port] is not None:
            return list(inputs[port])
    return merge_inputs(inputs)


# ---------------------------------------------------------------------------
# source
# ---------------------------------------------------------------------------


def _resolve_source_config(node, ctx) -> tuple[dict, str]:
    """合并连接配置与节点配置：节点级覆盖连接级，便于临时改样例行数。"""
    config = dict(node.config or {})
    kind = str(config.get("connector_kind") or "generator")
    connection_id = config.get("connection_id")
    if connection_id:
        connection = ctx.get_connection(connection_id)
        if connection is None:
            raise ValueError(f"连接 {connection_id} 不存在或无权访问")
        kind = connection.connector.kind
        merged = dict(connection.config or {})
        merged.update({k: v for k, v in config.items() if k != "connection_id"})
        config = merged
    config["connector_kind"] = kind
    return config, kind


def _compare_watermark(value, watermark: str) -> bool:
    """判断值是否大于水位：数字按数值，日期按时间，其余按文本。"""
    if value is None:
        return False
    if watermark in (None, ""):
        return True
    vnum, wnum = to_number(value), to_number(watermark)
    if vnum is not None and wnum is not None:
        return vnum > wnum
    vtext, wtext = to_text(value), str(watermark)
    return vtext > wtext


def execute_source(node, inputs, ctx):
    """取数：模拟 HTTP / SQL / 文件 / 生成器，并按水位做增量过滤。"""
    config, kind = _resolve_source_config(node, ctx)
    result = source_rows(config, limit=ctx.limit)
    rows = result.get("rows") or []
    meta = dict(result.get("meta") or {})

    watermark_field = getattr(ctx, "watermark_field", "")
    watermark_value = getattr(ctx, "watermark_before", "")
    incremental = config.get("incremental", True)
    skipped = 0
    if watermark_field and watermark_value and incremental:
        kept = []
        for row in rows:
            if _compare_watermark(get_path(row, watermark_field), watermark_value):
                kept.append(row)
            else:
                skipped += 1
        rows = kept
        meta["watermark_field"] = watermark_field
        meta["watermark_before"] = watermark_value
        meta["watermark_skipped"] = skipped

    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("数据源返回的行集格式不正确")
    _limit(rows, ctx, "数据源")
    ctx.log("info", f"数据源 {node.node_key}（{kind}）产出 {len(rows)} 行",
            node_key=node.node_key, context={"meta": meta, "skipped": skipped})
    return {"out": rows}, {"kind": kind, "row_count": len(rows), **meta}


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------


def execute_filter(node, inputs, ctx):
    """按表达式分流：命中走 pass，未命中走 fail，两个端口都可接下游。"""
    config = node.config or {}
    condition = str(config.get("condition") or "").strip()
    if not condition:
        raise ValueError("过滤节点必须配置 condition 表达式")
    rows = _primary_rows(inputs)
    passed: list[dict] = []
    failed: list[dict] = []
    for index, row in enumerate(rows):
        ctx.check_timeout()
        try:
            ok = evaluate_condition(condition, row)
        except ExprError as exc:
            raise ValueError(f"过滤条件在第 {index + 1} 行求值失败：{exc}")
        (passed if ok else failed).append(row)
    _limit(passed, ctx, "过滤命中行")
    _limit(failed, ctx, "过滤未命中行")
    ctx.log("info", f"过滤 {len(rows)} 行：命中 {len(passed)}，未命中 {len(failed)}",
            node_key=node.node_key,
            context={"condition": condition, "passed": len(passed), "failed": len(failed)})
    return {"pass": passed, "fail": failed}, {
        "row_count": len(rows), "passed": len(passed), "failed": len(failed),
    }


# ---------------------------------------------------------------------------
# map
# ---------------------------------------------------------------------------


def _mapping_items(node, ctx) -> list[dict]:
    """合并节点内映射与 Mapping 表：表里的映射排在前面（可视化逐条维护）。"""
    items: list[dict] = []
    for mapping in ctx.mapping_rows(node.node_key):
        items.append({
            "source": mapping.source_field,
            "target": mapping.target_field,
            "cast": mapping.cast,
            "default": mapping.default_value,
            "expression": mapping.expression,
            "required": mapping.required,
        })
    for item in (node.config or {}).get("mappings") or []:
        if isinstance(item, dict):
            items.append(item)
    if not items and (node.config or {}).get("rename"):
        # 兼容简写：{"rename": {"old": "new"}}
        for src, dst in ((node.config or {}).get("rename") or {}).items():
            items.append({"source": src, "target": dst})
    return items


def execute_map(node, inputs, ctx):
    """字段映射：source / expression 取值 → cast → default，支持点路径写入。"""
    config = node.config or {}
    rows = _primary_rows(inputs)
    items = _mapping_items(node, ctx)
    if not items:
        raise ValueError("映射节点没有可执行的映射规则")
    keep_only = bool(config.get("keep_only") or config.get("drop_unmapped"))
    strict = bool(config.get("strict"))
    out: list[dict] = []
    for index, row in enumerate(rows):
        ctx.check_timeout()
        target_row = {} if keep_only else dict(row)
        for item in items:
            target = str(item.get("target") or item.get("to") or "").strip()
            if not target:
                raise ValueError("映射规则缺少目标字段")
            expr = str(item.get("expression") or "").strip()
            try:
                if expr:
                    value = evaluate_expression(expr, row)
                else:
                    value = get_path(row, str(item.get("source") or item.get("field") or ""))
            except ExprError as exc:
                raise ValueError(f"字段 {target} 在第 {index + 1} 行求值失败：{exc}")
            if value is None:
                value = item.get("default")
            if value is not None and item.get("cast"):
                value = cast_value(value, item["cast"], default=item.get("default"))
            if value is None and item.get("required"):
                if strict:
                    raise ValueError(f"字段 {target} 为必填，但第 {index + 1} 行为空")
                ctx.log("warning", f"第 {index + 1} 行必填字段 {target} 为空",
                        node_key=node.node_key)
            set_path(target_row, target, value)
        out.append(target_row)
    _limit(out, ctx, "映射")
    ctx.log("info", f"映射 {len(out)} 行 / {len(items)} 条规则", node_key=node.node_key,
            context={"targets": [str(i.get("target") or i.get("to")) for i in items[:20]]})
    return {"out": out}, {"row_count": len(out), "mapping_count": len(items)}


# ---------------------------------------------------------------------------
# transform
# ---------------------------------------------------------------------------


def _field_set(op: dict) -> list[str]:
    value = op.get("fields", op.get("field"))
    return _keys(value, "fields")


def _apply_transform_op(row: dict, op: dict, index: int, node_key: str) -> dict:
    """执行单个结构操作；返回新行（不原地修改，便于错误时保留现场）。"""
    name = str(op.get("op") or "").lower()
    out = dict(row)

    if name == "rename":
        mapping = op.get("mapping")
        if isinstance(mapping, dict):
            pairs = list(mapping.items())
        else:
            pairs = [(op.get("from"), op.get("to"))]
        for src, dst in pairs:
            if not src or not dst:
                raise ValueError("rename 操作必须提供 from / to")
            if src in out:
                out[dst] = out.pop(src)
            elif get_path(out, str(src), _MISSING) is not _MISSING:
                set_path(out, str(dst), get_path(out, str(src)))
                delete_path(out, str(src))

    elif name == "select":
        fields = _field_set(op)
        if not fields:
            raise ValueError("select 操作必须提供 fields")
        out = {f: get_path(out, f) for f in fields if get_path(out, f, _MISSING) is not _MISSING}

    elif name == "drop":
        for field in _field_set(op):
            delete_path(out, field)

    elif name == "fill":
        fields = _field_set(op)
        value = op.get("value", op.get("default"))
        if not fields:
            raise ValueError("fill 操作必须提供 fields")
        for field in fields:
            current = get_path(out, field, _MISSING)
            if current is _MISSING or current is None or current == "":
                set_path(out, field, value)

    elif name == "cast":
        casts = op.get("casts") or op.get("mapping")
        if isinstance(casts, dict):
            pairs = casts.items()
        else:
            fields = _field_set(op)
            cast = op.get("type") or op.get("cast")
            if not cast:
                raise ValueError("cast 操作必须提供 type")
            pairs = [(f, cast) for f in fields]
        for field, cast in pairs:
            if get_path(out, field, _MISSING) is not _MISSING:
                set_path(out, field, cast_value(get_path(out, field), cast,
                                               default=op.get("default")))

    elif name == "concat":
        target = op.get("target") or op.get("to")
        fields = _field_set(op)
        if not target or not fields:
            raise ValueError("concat 操作必须提供 fields 与 target")
        sep = str(op.get("separator", ""))
        parts = [to_text(get_path(out, f)) for f in fields]
        set_path(out, target, sep.join(p for p in parts if p != ""))

    elif name == "split":
        source = op.get("source") or op.get("field")
        target = op.get("target") or op.get("to")
        if not source or not target:
            raise ValueError("split 操作必须提供 source 与 target")
        sep = str(op.get("separator", ","))
        value = get_path(out, source)
        parts = to_text(value).split(sep) if value is not None else []
        pos = op.get("index")
        if pos is None:
            set_path(out, target, parts)
        else:
            try:
                set_path(out, target, parts[int(pos)])
            except (ValueError, IndexError):
                set_path(out, target, None)

    elif name == "replace":
        field = op.get("field")
        if not field:
            raise ValueError("replace 操作必须提供 field")
        old = to_text(op.get("old", ""))
        new = to_text(op.get("new", ""))
        value = to_text(get_path(out, field))
        if op.get("regex"):
            import re
            try:
                value = re.sub(old, new, value)
            except re.error as exc:
                raise ValueError(f"replace 正则不合法：{exc}")
        else:
            value = value.replace(old, new)
        set_path(out, field, value)

    elif name in ("lower", "upper", "trim"):
        for field in _field_set(op):
            value = get_path(out, field, _MISSING)
            if value is _MISSING:
                continue
            text = to_text(value)
            if name == "lower":
                text = text.lower()
            elif name == "upper":
                text = text.upper()
            else:
                text = text.strip()
            set_path(out, field, text)

    elif name == "prefix":
        field = op.get("field")
        prefix = to_text(op.get("prefix", ""))
        if not field:
            raise ValueError("prefix 操作必须提供 field")
        if get_path(out, field, _MISSING) is not _MISSING:
            set_path(out, field, prefix + to_text(get_path(out, field)))

    else:
        raise ValueError(f"不支持的转换操作：{name}")

    return out


def execute_transform(node, inputs, ctx):
    """结构转换：按 operations 顺序逐条应用（rename/select/drop/fill/cast/...）。"""
    config = node.config or {}
    operations = config.get("operations")
    if not isinstance(operations, list) or not operations:
        single = config.get("operation")
        operations = [single] if isinstance(single, dict) else []
    if not operations:
        raise ValueError("转换节点没有配置 operations")
    rows = _primary_rows(inputs)
    out: list[dict] = []
    for index, row in enumerate(rows):
        ctx.check_timeout()
        current = row
        for op in operations:
            if not isinstance(op, dict) or not op.get("op"):
                raise ValueError(f"第 {index + 1} 行遇到非法转换操作")
            current = _apply_transform_op(current, op, index, node.node_key)
        out.append(current)
    _limit(out, ctx, "转换")
    ctx.log("info", f"转换 {len(out)} 行，应用 {len(operations)} 个操作",
            node_key=node.node_key,
            context={"operations": [str(o.get("op")) for o in operations[:20]]})
    return {"out": out}, {"row_count": len(out), "operation_count": len(operations)}


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def _metric_value(rows: list[dict], metric: dict):
    func = str(metric.get("func") or "count").lower()
    field = metric.get("field")
    if func == "count":
        if not field:
            return len(rows)
        return sum(1 for r in rows if get_path(r, field) not in (None, ""))
    values = [get_path(r, field) for r in rows]
    values = [v for v in values if v is not None]
    if func == "count_distinct":
        return len({_norm_key(v) for v in values})
    if func == "first":
        return values[0] if values else None
    if func == "last":
        return values[-1] if values else None
    numbers = [to_number(v) for v in values]
    numbers = [n for n in numbers if n is not None]
    if func in ("sum", "avg") and not numbers:
        return None
    if func == "sum":
        return sum(numbers)
    if func == "avg":
        return sum(numbers) / len(numbers) if numbers else None
    if func == "min":
        if numbers:
            return min(numbers)
        return min(values, key=to_text) if values else None
    if func == "max":
        if numbers:
            return max(numbers)
        return max(values, key=to_text) if values else None
    raise ValueError(f"不支持的聚合函数：{func}")


def execute_aggregate(node, inputs, ctx):
    """分组聚合：group_by + count/sum/avg/min/max/count_distinct。"""
    config = node.config or {}
    metrics = config.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        metrics = [{"func": "count", "as": "count"}]
    for metric in metrics:
        if not isinstance(metric, dict):
            raise ValueError("聚合指标必须是对象")
        func = str(metric.get("func") or "count").lower()
        if func not in AGG_FUNCS:
            raise ValueError(f"不支持的聚合函数：{func}")
        if not (metric.get("as") or metric.get("alias")):
            raise ValueError(f"聚合函数 {func} 缺少输出名 as")
    group_by = _keys(config.get("group_by"), "group_by")
    rows = _primary_rows(inputs)

    buckets: dict[tuple, list[dict]] = {}
    group_values: dict[tuple, tuple] = {}
    for row in rows:
        ctx.check_timeout()
        key = tuple(_norm_key(get_path(row, f)) for f in group_by)
        if key not in buckets:
            buckets[key] = []
            group_values[key] = tuple(get_path(row, f) for f in group_by)
        buckets[key].append(row)

    out: list[dict] = []
    for key in sorted(buckets.keys()):
        group_rows = buckets[key]
        item: dict = {}
        for field, value in zip(group_by, group_values[key]):
            item[field] = value
        for metric in metrics:
            alias = str(metric.get("as") or metric.get("alias"))
            item[alias] = _metric_value(group_rows, metric)
        out.append(item)
    _limit(out, ctx, "聚合")
    ctx.log("info", f"聚合 {len(rows)} 行 → {len(out)} 组", node_key=node.node_key,
            context={"group_by": group_by, "metrics": [m.get("as") for m in metrics]})
    return {"out": out}, {"row_count": len(rows), "group_count": len(out)}


# ---------------------------------------------------------------------------
# sort
# ---------------------------------------------------------------------------


def _compare_values(left, right) -> int:
    """稳定比较：空值永远排最后；两侧都能转数字时按数值。"""
    if left is None and right is None:
        return 0
    if left is None:
        return 1
    if right is None:
        return -1
    lnum, rnum = to_number(left), to_number(right)
    if lnum is not None and rnum is not None:
        return (lnum > rnum) - (lnum < rnum)
    ltext, rtext = to_text(left), to_text(right)
    return (ltext > rtext) - (ltext < rtext)


def execute_sort(node, inputs, ctx):
    """多字段排序：keys 支持字符串或 {field, desc}。"""
    keys = (node.config or {}).get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("排序节点必须配置 keys")
    specs = []
    for item in keys:
        if isinstance(item, str):
            specs.append((item, False))
        elif isinstance(item, dict) and item.get("field"):
            specs.append((str(item["field"]), to_bool(item.get("desc"))))
        else:
            raise ValueError("排序键必须是字段名或 {field, desc} 对象")
    rows = list(_primary_rows(inputs))

    def comparator(left, right):
        for field, desc in specs:
            result = _compare_values(get_path(left, field), get_path(right, field))
            if result:
                return -result if desc else result
        return 0

    rows.sort(key=cmp_to_key(comparator))
    _limit(rows, ctx, "排序")
    ctx.log("info", f"排序 {len(rows)} 行", node_key=node.node_key,
            context={"keys": [f for f, _ in specs]})
    return {"out": rows}, {"row_count": len(rows)}


# ---------------------------------------------------------------------------
# dedupe
# ---------------------------------------------------------------------------


def execute_dedupe(node, inputs, ctx):
    """按键去重：keep=first 保留首条，keep=last 保留末条，顺序按原索引稳定。"""
    config = node.config or {}
    keys = _keys(config.get("keys"), "keys")
    if not keys:
        raise ValueError("去重节点必须配置 keys")
    keep = str(config.get("keep") or "first").lower()
    if keep not in DEDUPE_KEEP:
        raise ValueError("keep 只支持 first / last")
    rows = _primary_rows(inputs)
    chosen: dict[tuple, tuple[int, dict]] = {}
    for index, row in enumerate(rows):
        ctx.check_timeout()
        key = row_key(row, keys)
        if key not in chosen:
            chosen[key] = (index, row)
        elif keep == "last":
            chosen[key] = (index, row)
    ordered = sorted(chosen.values(), key=lambda pair: pair[0])
    out = [row for _, row in ordered]
    _limit(out, ctx, "去重")
    ctx.log("info", f"去重 {len(rows)} → {len(out)} 行（keep={keep}）",
            node_key=node.node_key, context={"keys": keys, "removed": len(rows) - len(out)})
    return {"out": out}, {"row_count": len(rows), "deduped": len(out),
                          "removed": len(rows) - len(out)}


# ---------------------------------------------------------------------------
# join
# ---------------------------------------------------------------------------


def execute_join(node, inputs, ctx):
    """内存关联：inner / left / right / full，复合键与空值不匹配语义。"""
    config = node.config or {}
    left_on = _keys(config.get("left_on"), "left_on")
    right_on = _keys(config.get("right_on"), "right_on")
    if not left_on or not right_on:
        raise ValueError("关联节点必须配置 left_on 与 right_on")
    if len(left_on) != len(right_on):
        raise ValueError("left_on 与 right_on 字段数量必须一致")
    how = str(config.get("how") or config.get("type") or "inner").lower()
    if how not in JOIN_TYPES:
        raise ValueError(f"不支持的连接方式：{how}")
    nulls_match = to_bool(config.get("nulls_match"))
    suffix = str(config.get("suffix") or "_right")

    left_rows = list(inputs.get("left") or [])
    right_rows = list(inputs.get("right") or [])
    if not left_rows and not right_rows:
        raise ValueError("关联节点的两路输入都为空")

    def key_of(row, fields):
        values = tuple(get_path(row, f) for f in fields)
        if not nulls_match and any(v is None for v in values):
            return None
        return tuple(_norm_key(v) for v in values)

    right_map: dict[tuple, list[dict]] = {}
    for row in right_rows:
        key = key_of(row, right_on)
        if key is None:
            continue
        right_map.setdefault(key, []).append(row)

    out: list[dict] = []
    matched_right_ids: set[int] = set()
    for row in left_rows:
        ctx.check_timeout()
        key = key_of(row, left_on)
        matches = right_map.get(key, []) if key is not None else []
        if matches:
            for right in matches:
                out.append(_merge_rows(row, right, suffix))
                matched_right_ids.add(id(right))
        elif how in ("left", "full"):
            out.append(_merge_rows(row, None, suffix))

    if how in ("right", "full"):
        for right in right_rows:
            if id(right) not in matched_right_ids:
                out.append(_merge_rows(None, right, suffix))

    _limit(out, ctx, "关联")
    ctx.log("info", f"关联 {len(left_rows)} × {len(right_rows)} → {len(out)} 行（{how}）",
            node_key=node.node_key,
            context={"how": how, "left": len(left_rows), "right": len(right_rows)})
    return {"out": out}, {"left_rows": len(left_rows), "right_rows": len(right_rows),
                          "row_count": len(out)}


def _merge_rows(left: dict | None, right: dict | None, suffix: str) -> dict:
    """合并两行：字段冲突时右侧加后缀，左侧字段保持原名。"""
    merged: dict = dict(left or {})
    if right:
        for key, value in right.items():
            if key in merged and merged[key] != value:
                merged[f"{key}{suffix}"] = value
            elif key not in merged:
                merged[key] = value
    return merged


# ---------------------------------------------------------------------------
# sink / webhook
# ---------------------------------------------------------------------------


def execute_sink(node, inputs, ctx):
    """落地：把行写入 PipelineOutput（真实入库），支持 append / replace。"""
    config = node.config or {}
    dataset = str(config.get("dataset") or "").strip()
    if not dataset:
        raise ValueError("落地节点必须配置 dataset")
    mode = str(config.get("mode") or "append").lower()
    if mode not in ("append", "replace"):
        raise ValueError("落地模式只支持 append / replace")
    rows = _primary_rows(inputs)
    if not rows:
        ctx.log("warning", "落地节点收到 0 行", node_key=node.node_key)
    _limit(rows, ctx, "落地")
    written = ctx.write_outputs(node, rows, dataset, mode)
    ctx.log("info", f"落地 {written} 行到 {dataset}（{mode}）", node_key=node.node_key,
            context={"dataset": dataset, "mode": mode, "row_count": written})
    return {}, {"dataset": dataset, "mode": mode, "written": written,
                "row_count": written}


def execute_webhook(node, inputs, ctx):
    """回调通知：模拟向外部 URL 投递摘要（不联网），并写入运行日志。"""
    config = node.config or {}
    url = str(config.get("url") or "").strip()
    if not url:
        raise ValueError("回调节点必须配置 url")
    rows = _primary_rows(inputs)
    payload = {
        "pipeline": getattr(ctx, "pipeline_code", ""),
        "run_id": getattr(ctx, "run_id", None),
        "node": node.node_key,
        "row_count": len(rows),
        "sample": _sample(rows, int(config.get("sample_size") or 3)),
        "summary": _summarize(rows),
    }
    result = ctx.deliver_webhook(url, payload,
                                 str(config.get("method") or "POST").upper())
    ctx.log("info", f"回调 {url} 模拟投递成功（状态码 {result.get('status_code')}）",
            node_key=node.node_key, context=result)
    return {}, {"url": url, "delivery": result, "row_count": len(rows)}


def _summarize(rows: list[dict]) -> dict:
    """行集摘要：行数与字段名，回调节点与日志都够用。"""
    fields: list[str] = []
    for row in rows[:10]:
        for key in row.keys():
            if key not in fields:
                fields.append(key)
    return {"rows": len(rows), "fields": fields[:30]}


NODE_EXECUTORS = {
    "source": execute_source,
    "filter": execute_filter,
    "map": execute_map,
    "transform": execute_transform,
    "aggregate": execute_aggregate,
    "sort": execute_sort,
    "dedupe": execute_dedupe,
    "join": execute_join,
    "sink": execute_sink,
    "webhook": execute_webhook,
}


def execute_node(node, inputs: dict, ctx) -> tuple[dict, dict]:
    """按节点类型分发。未知类型直接报错，绝不静默跳过。"""
    executor = NODE_EXECUTORS.get(node.node_type)
    if executor is None:
        raise ValueError(f"不支持的节点类型：{node.node_type}")
    return executor(node, inputs, ctx)


def output_rows_of(result: dict, port: str = "out") -> list[dict]:
    """从执行结果中取指定端口的行集（缺少时返回空列表）。"""
    return list((result or {}).get(port) or [])


def sample_json(rows: list[dict], size: int = 5) -> str:
    """把样例行转成 JSON 文本，用于运行摘要 / 日志上下文。"""
    try:
        return json.dumps(rows[:size], ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(rows[:size])
