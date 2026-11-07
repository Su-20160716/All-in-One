# -*- coding: utf-8 -*-
"""DAG 结构与拓扑排序。

管道执行前必须先回答三个问题：
1. 这张图合法吗（唯一入口 / 唯一出口、无环、端口存在、无孤立节点）？
2. 按什么顺序执行（拓扑序）？
3. 如果非法，错在哪个节点（前端要在画布上高亮）？

本模块只做纯结构计算，不碰数据库写入，便于在「保存草稿」阶段复用，
也便于单元测试直接构造内存对象验证。
"""
from __future__ import annotations

from collections import defaultdict

from pipeline.expressions import validate_expression
from pipeline.generators import DATASET_SCHEMAS, validate_connection_config
from pipeline.models import NODE_PORTS, NODE_TYPES, NODE_TYPE_LABELS

_STRUCTURAL_NODE_TYPES = set(NODE_TYPES)


def node_ports(node) -> dict:
    """节点端口定义：未知类型按单进单出处理，避免配置错误直接 500。"""
    return NODE_PORTS.get(getattr(node, "node_type", ""), {"in": ["in"], "out": ["out"]})


def _err(code: str, message: str, node_key: str = "", detail=None) -> dict:
    item = {"code": code, "message": message, "node_key": node_key}
    if detail is not None:
        item["detail"] = detail
    return item


def _warn(code: str, message: str, node_key: str = "") -> dict:
    return {"code": code, "message": message, "node_key": node_key}


def validate_node_config(node) -> list[dict]:
    """单节点配置校验：返回错误列表（不抛异常，便于一次报全）。

    这里只做结构与语法层面校验；数据层面（字段是否存在）留到运行期，
    因为字段依赖上游节点输出，保存草稿时还不存在。
    """
    node_type = getattr(node, "node_type", "")
    config = getattr(node, "config", None) or {}
    key = getattr(node, "node_key", "")
    errors: list[dict] = []

    if node_type not in _STRUCTURAL_NODE_TYPES:
        errors.append(_err("node_type", f"未知节点类型：{node_type}", key))
        return errors

    if node_type == "source":
        kind = str(config.get("connector_kind") or "generator")
        if kind not in ("http", "database", "file", "webhook", "generator"):
            errors.append(_err("source_kind", f"未知连接器类型：{kind}", key))
        elif not config.get("connection_id"):
            # 未绑定连接时要求配置自身完整，错误信息才能落到具体字段
            try:
                validate_connection_config(kind, config)
            except ValueError as exc:
                errors.append(_err("source_config", str(exc), key))
        if kind == "generator":
            dataset = config.get("dataset") or "orders"
            if dataset not in DATASET_SCHEMAS:
                errors.append(_err("source_dataset", f"未知内置数据集：{dataset}", key))

    elif node_type == "filter":
        condition = str(config.get("condition") or "").strip()
        if not condition:
            errors.append(_err("filter_condition", "过滤节点必须配置 condition 表达式", key))
        else:
            report = validate_expression(condition)
            if not report["valid"]:
                errors.append(_err("filter_expression", report["error"], key))
            if config.get("strict") and not report["fields"]:
                errors.append(_warn("filter_fields", "过滤条件未引用任何字段", key))

    elif node_type == "map":
        mappings = config.get("mappings")
        if not isinstance(mappings, list) or not mappings:
            errors.append(_err("map_mappings", "映射节点必须配置 mappings 数组", key))
        else:
            targets: set[str] = set()
            for index, mapping in enumerate(mappings[:200]):
                if not isinstance(mapping, dict):
                    errors.append(_err("map_item", f"第 {index + 1} 条映射不是对象", key))
                    continue
                target = str(mapping.get("target") or mapping.get("to") or "").strip()
                if not target:
                    errors.append(_err("map_target", f"第 {index + 1} 条映射缺少目标字段", key))
                elif target in targets:
                    errors.append(_err("map_dup", f"目标字段 {target} 重复映射", key))
                targets.add(target)
                expr = str(mapping.get("expression") or "").strip()
                if expr:
                    report = validate_expression(expr)
                    if not report["valid"]:
                        errors.append(_err("map_expression",
                                           f"字段 {target} 表达式错误：{report['error']}", key))
                source = str(mapping.get("source") or mapping.get("field") or "").strip()
                if not source and not expr:
                    errors.append(_err("map_source",
                                       f"字段 {target} 必须配置 source 或 expression", key))

    elif node_type == "transform":
        operations = config.get("operations")
        if not isinstance(operations, list) or not operations:
            errors.append(_err("transform_ops", "转换节点必须配置 operations 数组", key))
        else:
            for index, op in enumerate(operations[:100]):
                if not isinstance(op, dict) or not op.get("op"):
                    errors.append(_err("transform_op", f"第 {index + 1} 个操作缺少 op", key))
                    continue
                name = str(op["op"]).lower()
                if name not in ("rename", "select", "drop", "fill", "cast", "concat",
                                "split", "replace", "lower", "upper", "trim", "prefix"):
                    errors.append(_err("transform_op", f"第 {index + 1} 个操作类型不支持：{name}", key))

    elif node_type == "aggregate":
        metrics = config.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            errors.append(_err("agg_metrics", "聚合节点必须配置 metrics 数组", key))
        else:
            for index, metric in enumerate(metrics[:50]):
                if not isinstance(metric, dict):
                    errors.append(_err("agg_metric", f"第 {index + 1} 个指标不是对象", key))
                    continue
                func = str(metric.get("func") or "count").lower()
                if func not in ("count", "count_distinct", "sum", "avg", "min", "max", "first", "last"):
                    errors.append(_err("agg_func", f"不支持的聚合函数：{func}", key))
                if func != "count" and not metric.get("field"):
                    errors.append(_err("agg_field", f"聚合函数 {func} 必须指定 field", key))
                if not (metric.get("as") or metric.get("alias")):
                    errors.append(_err("agg_alias", f"第 {index + 1} 个指标缺少输出名 as", key))
        group_by = config.get("group_by")
        if group_by is not None and not isinstance(group_by, (str, list)):
            errors.append(_err("agg_group", "group_by 必须是字符串或数组", key))

    elif node_type == "join":
        left_on = config.get("left_on")
        right_on = config.get("right_on")
        left_keys = [left_on] if isinstance(left_on, str) else list(left_on or [])
        right_keys = [right_on] if isinstance(right_on, str) else list(right_on or [])
        if not left_keys or not right_keys:
            errors.append(_err("join_keys", "关联节点必须配置 left_on 与 right_on", key))
        elif len(left_keys) != len(right_keys):
            errors.append(_err("join_key_len", "left_on 与 right_on 字段数量必须一致", key))
        how = str(config.get("how") or "inner").lower()
        if how not in ("inner", "left", "right", "full"):
            errors.append(_err("join_how", f"不支持的连接方式：{how}", key))

    elif node_type == "sort":
        keys = config.get("keys")
        if not isinstance(keys, list) or not keys:
            errors.append(_err("sort_keys", "排序节点必须配置 keys 数组", key))

    elif node_type == "dedupe":
        keys = config.get("keys")
        if not isinstance(keys, list) or not keys:
            errors.append(_err("dedupe_keys", "去重节点必须配置 keys 数组", key))
        keep = str(config.get("keep") or "first").lower()
        if keep not in ("first", "last"):
            errors.append(_err("dedupe_keep", "keep 只支持 first / last", key))

    elif node_type == "sink":
        dataset = str(config.get("dataset") or "").strip()
        if not dataset:
            errors.append(_err("sink_dataset", "落地节点必须配置 dataset", key))
        elif len(dataset) > 120:
            errors.append(_err("sink_dataset", "dataset 名称不能超过 120 字符", key))
        mode = str(config.get("mode") or "append").lower()
        if mode not in ("append", "replace"):
            errors.append(_err("sink_mode", "落地模式只支持 append / replace", key))

    elif node_type == "webhook":
        url = str(config.get("url") or "").strip()
        if not url:
            errors.append(_err("webhook_url", "回调节点必须配置 url", key))
        elif not (url.startswith("http://") or url.startswith("https://")):
            errors.append(_err("webhook_url", "回调地址必须以 http:// 或 https:// 开头", key))

    return errors


def _node_sort_key(node):
    return (getattr(node, "order", 0) or 0, getattr(node, "node_key", "") or "")


def topological_sort(nodes: list, edges: list) -> list[str]:
    """Kahn 拓扑排序，返回 node_key 顺序。

    同层按 (order, node_key) 稳定排序：同一张图每次运行顺序完全一致，
    否则「同输入不同输出」会让排障变成玄学。
    """
    keys = [n.node_key for n in nodes]
    key_set = set(keys)
    indegree = {k: 0 for k in keys}
    children = defaultdict(list)
    for edge in edges:
        src = edge.source.node_key if hasattr(edge, "source_id") else edge["source"]
        dst = edge.target.node_key if hasattr(edge, "target_id") else edge["target"]
        if src not in key_set or dst not in key_set:
            continue
        indegree[dst] += 1
        children[src].append(dst)

    order_map = {n.node_key: n for n in nodes}
    ready = sorted([k for k, deg in indegree.items() if deg == 0],
                   key=lambda k: _node_sort_key(order_map[k]))
    result: list[str] = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for child in sorted(children[current], key=lambda k: _node_sort_key(order_map[k])):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
        ready.sort(key=lambda k: _node_sort_key(order_map[k]))

    if len(result) != len(keys):
        remaining = [k for k in keys if k not in result]
        raise ValueError(f"管道存在环，无法确定执行顺序：{', '.join(remaining[:8])}")
    return result


def _find_cycle(nodes: list, edges: list) -> list[str]:
    """DFS 找出一条环路径（返回节点序列），供错误提示直接展示。"""
    children = defaultdict(list)
    for edge in edges:
        children[edge.source.node_key].append(edge.target.node_key)
    color: dict[str, int] = {}   # 1=访问中 2=已完成
    stack: list[str] = []
    found: list[str] = []

    def dfs(key: str) -> bool:
        color[key] = 1
        stack.append(key)
        for child in children.get(key, []):
            if color.get(child) == 1:
                start = stack.index(child)
                found.extend(stack[start:] + [child])
                return True
            if color.get(child, 0) == 0 and dfs(child):
                return True
        stack.pop()
        color[key] = 2
        return False

    for node in sorted(nodes, key=_node_sort_key):
        if color.get(node.node_key, 0) == 0 and dfs(node.node_key):
            break
    return found


def validate_dag(pipeline) -> dict:
    """完整 DAG 校验：结构 + 端口 + 配置 + 环 + 可达性。

    返回结构：
    ``{valid, errors, warnings, order, node_count, edge_count, sources, sinks}``
    错误里带 ``node_key``，前端据此在画布上高亮。
    """
    nodes = list(pipeline.nodes.all())
    edges = list(pipeline.edges.select_related("source", "target").all())
    errors: list[dict] = []
    warnings: list[dict] = []

    if not nodes:
        errors.append(_err("no_nodes", "管道还没有任何节点"))
        return {"valid": False, "errors": errors, "warnings": warnings,
                "order": [], "node_count": 0, "edge_count": 0,
                "sources": [], "sinks": []}

    by_key = {n.node_key: n for n in nodes}
    enabled = {n.node_key: n for n in nodes if n.enabled}
    sources = [n for n in nodes if n.node_type == "source" and n.enabled]
    sinks = [n for n in nodes if n.node_type == "sink" and n.enabled]

    if not sources:
        errors.append(_err("no_source", "管道必须包含至少一个启用的数据源节点"))
    elif len(sources) > 1:
        errors.append(_err("multi_source", "管道只能有一个数据源节点",
                           sources[1].node_key if len(sources) > 1 else ""))
    if not sinks:
        errors.append(_err("no_sink", "管道必须包含至少一个启用的落地节点"))
    elif len(sinks) > 1:
        errors.append(_err("multi_sink", "管道只能有一个落地节点",
                           sinks[1].node_key if len(sinks) > 1 else ""))

    # ---- 节点配置 ----
    for node in nodes:
        if not node.enabled:
            warnings.append(_warn("disabled_node",
                                  f"节点 {node.node_key} 已禁用，运行时会被跳过", node.node_key))
            continue
        errors.extend(validate_node_config(node))

    # ---- 连线校验 ----
    seen_edges: set[tuple] = set()
    for edge in edges:
        src, dst = edge.source, edge.target
        if src.node_key not in by_key or dst.node_key not in by_key:
            errors.append(_err("edge_unknown", "连线引用了不存在的节点"))
            continue
        if src.node_key == dst.node_key:
            errors.append(_err("edge_self", "节点不能连到自己", src.node_key))
            continue
        if src.node_key not in enabled or dst.node_key not in enabled:
            warnings.append(_warn("edge_disabled", "连线的一端已禁用，运行时会失效",
                                  src.node_key if src.node_key not in enabled else dst.node_key))
            continue
        src_ports = node_ports(src)["out"]
        dst_ports = node_ports(dst)["in"]
        if src_ports and edge.source_port not in src_ports:
            errors.append(_err("edge_source_port",
                               f"上游节点 {src.node_key} 不存在输出端口 {edge.source_port}",
                               src.node_key))
        if dst_ports and edge.target_port not in dst_ports:
            errors.append(_err("edge_target_port",
                               f"下游节点 {dst.node_key} 不存在输入端口 {edge.target_port}",
                               dst.node_key))
        signature = (src.node_key, edge.source_port, dst.node_key, edge.target_port)
        if signature in seen_edges:
            errors.append(_err("edge_duplicate",
                               f"重复连线 {src.node_key}:{edge.source_port} → "
                               f"{dst.node_key}:{edge.target_port}", src.node_key))
        seen_edges.add(signature)

    # ---- 入度 / 出度语义 ----
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for edge in edges:
        incoming[edge.target.node_key].append(edge)
        outgoing[edge.source.node_key].append(edge)

    for node in enabled.values():
        ins = [e for e in incoming.get(node.node_key, [])
               if e.source.node_key in enabled]
        outs = [e for e in outgoing.get(node.node_key, [])
                if e.target.node_key in enabled]
        if node.node_type == "source":
            if ins:
                errors.append(_err("source_has_input", "数据源节点不能有输入连线", node.node_key))
        elif node.node_type in ("sink", "webhook"):
            if outs:
                errors.append(_err("sink_has_output",
                                   f"{NODE_TYPE_LABELS.get(node.node_type, node.node_type)}"
                                   "节点不能有输出连线", node.node_key))
            if not ins:
                errors.append(_err("sink_no_input", "落地 / 回调节点必须有输入连线", node.node_key))
        elif node.node_type == "join":
            ports = sorted({e.target_port for e in ins})
            if len(ins) != 2 or ports != ["left", "right"]:
                errors.append(_err("join_inputs",
                                   "关联节点必须且只能接收 left / right 两路输入", node.node_key))
        else:
            if not ins:
                errors.append(_err("node_no_input", "节点缺少输入连线", node.node_key))
            if not outs:
                errors.append(_err("node_no_output", "节点缺少输出连线", node.node_key))
            if len({e.target_port for e in ins}) > 1:
                errors.append(_err("node_multi_port",
                                   "非关联节点只能从一个输入端口接收数据", node.node_key))
            if len(ins) > 1:
                warnings.append(_warn("node_fan_in", "多路上游会按连线顺序合并为行集",
                                      node.node_key))

    # ---- 孤立节点 ----
    if len(nodes) > 1:
        for node in enabled.values():
            if not incoming.get(node.node_key) and not outgoing.get(node.node_key):
                errors.append(_err("isolated", "节点既无输入也无输出，成为孤岛", node.node_key))

    # ---- 环 ----
    cycle = _find_cycle([n for n in nodes if n.enabled],
                        [e for e in edges if e.source.node_key in enabled
                         and e.target.node_key in enabled])
    if cycle:
        errors.append(_err("cycle", f"检测到循环依赖：{' → '.join(cycle)}", cycle[0]))

    order: list[str] = []
    if not cycle:
        try:
            order = topological_sort([n for n in nodes if n.enabled],
                                     [e for e in edges if e.source.node_key in enabled
                                      and e.target.node_key in enabled])
        except ValueError as exc:
            errors.append(_err("topology", str(exc)))

    # ---- 可达性：从 source 出发必须能到 sink ----
    if sources and sinks and order:
        children = defaultdict(list)
        for edge in edges:
            children[edge.source.node_key].append(edge.target.node_key)
        reachable: set[str] = set()
        queue = [sources[0].node_key]
        while queue:
            key = queue.pop()
            if key in reachable:
                continue
            reachable.add(key)
            queue.extend(children.get(key, []))
        missing = [n.node_key for n in enabled.values() if n.node_key not in reachable]
        for key in missing:
            warnings.append(_warn("unreachable", f"节点 {key} 无法从数据源到达", key))
        if sinks[0].node_key not in reachable:
            errors.append(_err("sink_unreachable", "数据源无法到达落地节点", sinks[0].node_key))

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "order": order,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "sources": [n.node_key for n in sources],
        "sinks": [n.node_key for n in sinks],
    }


def topology_preview(pipeline) -> dict:
    """拓扑预览：返回分层结果，前端按层渲染执行顺序。"""
    report = validate_dag(pipeline)
    order = report["order"]
    nodes = {n.node_key: n for n in pipeline.nodes.all()}
    indegree = {key: 0 for key in order}
    children: dict[str, list[str]] = defaultdict(list)
    for edge in pipeline.edges.select_related("source", "target").all():
        src, dst = edge.source.node_key, edge.target.node_key
        if src in indegree and dst in indegree:
            indegree[dst] += 1
            children[src].append(dst)
    levels: list[list[str]] = []
    current = [k for k, deg in indegree.items() if deg == 0]
    current.sort(key=lambda k: (nodes[k].order, k))
    while current:
        levels.append(current)
        nxt: list[str] = []
        for key in current:
            for child in children.get(key, []):
                indegree[child] -= 1
                if indegree[child] == 0:
                    nxt.append(child)
        nxt.sort(key=lambda k: (nodes[k].order, k))
        current = nxt
    return {
        "valid": report["valid"],
        "errors": report["errors"],
        "warnings": report["warnings"],
        "order": order,
        "levels": levels,
        "levels_detail": [
            [{"node_key": k, "name": nodes[k].name, "node_type": nodes[k].node_type}
             for k in level]
            for level in levels
        ],
        "node_count": report["node_count"],
        "edge_count": report["edge_count"],
    }


def upstream_keys(pipeline) -> dict[str, set[str]]:
    """节点 → 直接上游集合（运行器取输入时复用）。"""
    mapping: dict[str, set[str]] = defaultdict(set)
    for edge in pipeline.edges.all():
        mapping[edge.target.node_key].add(edge.source.node_key)
    return mapping


def find_orphan_nodes(pipeline) -> list[str]:
    """孤立节点清单（画布提示用，不重复跑完整校验）。"""
    connected: set[str] = set()
    for edge in pipeline.edges.all():
        connected.add(edge.source.node_key)
        connected.add(edge.target.node_key)
    return [n.node_key for n in pipeline.nodes.all() if n.node_key not in connected]
