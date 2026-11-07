# -*- coding: utf-8 -*-
"""血缘与数据画像。

血缘用「实体 + 标识」而不是外键：上游可能是连接、外部表、文件甚至另一个
平台的管道，用外键会把不属于本应用的实体硬塞进模型。查询时做广度优先
遍历并记录访问集合，天然防环（血缘图里出现环并不罕见）。

画像是「字段级体检」：空值率、唯一值、最值、均值、长度分布、TOP 值。
只做采样（默认 1000 行），既能反映分布，又不会让接口变慢。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from django.db import transaction
from django.utils import timezone

from pipeline.catalog import DEFAULT_PROFILE_SAMPLE, MAX_RUN_ROWS
from pipeline.expressions import parse_datetime_value, to_number, to_text
from pipeline.models import (LINEAGE_ENTITY_TYPES, Connection, DatasetProfile,
                             LineageEdge, Pipeline, PipelineOutput)

MAX_DEPTH = 5


# ---------------------------------------------------------------------------
# 血缘
# ---------------------------------------------------------------------------


def _entity(entity_type: str, key: str) -> tuple[str, str]:
    if entity_type not in LINEAGE_ENTITY_TYPES:
        raise ValueError(f"不支持的实体类型：{entity_type}")
    key = str(key or "").strip()
    if not key:
        raise ValueError("实体标识不能为空")
    return entity_type, key[:200]


def _source_entities(pipeline) -> list[tuple[str, str, dict]]:
    """从 source 节点推导上游实体；连接优先，其次是表 / 文件 / 数据集。"""
    items: list[tuple[str, str, dict]] = []
    for node in pipeline.nodes.filter(node_type="source", enabled=True):
        config = node.config or {}
        connection_id = config.get("connection_id")
        if connection_id:
            conn = Connection.objects.filter(pk=connection_id,
                                             owner=pipeline.owner).first()
            if conn is not None:
                items.append(("connection", conn.name, {"node_key": node.node_key}))
                continue
        kind = str(config.get("connector_kind") or "generator")
        if kind == "database":
            table = str(config.get("table") or config.get("database") or "default")
            items.append(("table", table, {"node_key": node.node_key}))
        elif kind == "file":
            items.append(("file", str(config.get("path") or "inline"), {"node_key": node.node_key}))
        elif kind == "http":
            items.append(("dataset", str(config.get("url") or "http"), {"node_key": node.node_key}))
        elif kind == "webhook":
            items.append(("webhook", str(config.get("url") or node.node_key),
                          {"node_key": node.node_key}))
        else:
            items.append(("dataset", str(config.get("dataset") or "orders"),
                          {"node_key": node.node_key}))
    return items


def _sink_entities(pipeline) -> list[tuple[str, str]]:
    """从 sink / webhook 节点推导下游实体。"""
    items: list[tuple[str, str]] = []
    for node in pipeline.nodes.filter(enabled=True):
        if node.node_type == "sink":
            dataset = str((node.config or {}).get("dataset") or "default")
            items.append(("dataset", dataset))
        elif node.node_type == "webhook":
            url = str((node.config or {}).get("url") or node.node_key)
            items.append(("webhook", url))
    return items


def _field_map(pipeline) -> list[dict]:
    """字段级血缘：Mapping 表里 source → target 的对应关系。"""
    rows = []
    for mapping in pipeline.mappings.order_by("order", "id"):
        rows.append({
            "from": mapping.source_field,
            "to": mapping.target_field,
            "cast": mapping.cast,
            "expression": mapping.expression[:200] if mapping.expression else "",
        })
    return rows


@transaction.atomic
def record_lineage(pipeline, run=None) -> list[LineageEdge]:
    """把一次运行涉及的上下游关系写入血缘表。

    分两层记录：``上游 → 管道`` 与 ``管道 → 下游``，
    这样「某张表的改动会影响哪些管道」可以一次反向遍历得到。
    """
    field_map = _field_map(pipeline)
    pipeline_key = pipeline.code
    saved: list[LineageEdge] = []

    for entity_type, key, _ in _source_entities(pipeline):
        edge, _created = LineageEdge.objects.update_or_create(
            owner=pipeline.owner, pipeline=pipeline,
            upstream_type=entity_type, upstream_key=key,
            downstream_type="pipeline", downstream_key=pipeline_key,
            defaults={"run": run, "field_map": []},
        )
        saved.append(edge)

    for entity_type, key in _sink_entities(pipeline):
        edge, _created = LineageEdge.objects.update_or_create(
            owner=pipeline.owner, pipeline=pipeline,
            upstream_type="pipeline", upstream_key=pipeline_key,
            downstream_type=entity_type, downstream_key=key,
            defaults={"run": run, "field_map": field_map},
        )
        saved.append(edge)

    return saved


def _edge_dict(edge: LineageEdge) -> dict:
    return {
        "id": edge.id,
        "upstream_type": edge.upstream_type,
        "upstream_key": edge.upstream_key,
        "downstream_type": edge.downstream_type,
        "downstream_key": edge.downstream_key,
        "field_map": edge.field_map or [],
        "pipeline_id": edge.pipeline_id,
        "run_id": edge.run_id,
        "updated_at": edge.updated_at.isoformat() if edge.updated_at else None,
    }


def _bfs(user, entity_type: str, key: str, direction: str, depth: int) -> dict:
    """广度优先遍历：upstream 沿 downstream→upstream 反向走，反之亦然。"""
    entity_type, key = _entity(entity_type, key)
    depth = max(1, min(int(depth or 3), MAX_DEPTH))
    visited = {(entity_type, key)}
    frontier = [(entity_type, key, 0)]
    nodes: dict[tuple[str, str], int] = {(entity_type, key): 0}
    edges: list[dict] = []

    while frontier:
        current_type, current_key, level = frontier.pop(0)
        if level >= depth:
            continue
        if direction == "upstream":
            qs = LineageEdge.objects.filter(owner=user, downstream_type=current_type,
                                            downstream_key=current_key)
        else:
            qs = LineageEdge.objects.filter(owner=user, upstream_type=current_type,
                                            upstream_key=current_key)
        for edge in qs.order_by("id"):
            edges.append(_edge_dict(edge))
            nxt = ((edge.upstream_type, edge.upstream_key) if direction == "upstream"
                   else (edge.downstream_type, edge.downstream_key))
            if nxt not in visited:
                visited.add(nxt)
                nodes[nxt] = level + 1
                frontier.append((nxt[0], nxt[1], level + 1))

    items = [
        {"type": t, "key": k, "level": lv, "label": _label_for(t, k)}
        for (t, k), lv in sorted(nodes.items(), key=lambda pair: (pair[1], pair[0]))
    ]
    return {
        "root": {"type": entity_type, "key": key},
        "direction": direction,
        "depth": depth,
        "nodes": items,
        "edges": edges,
        "count": len(items) - 1,
    }


def _label_for(entity_type: str, key: str) -> str:
    """给前端展示用的可读名称：管道与连接可以查到中文名。"""
    if entity_type == "pipeline":
        pipeline = Pipeline.objects.filter(code=key).first()
        return pipeline.name if pipeline else key
    if entity_type == "connection":
        conn = Connection.objects.filter(name=key).first()
        return f"{conn.name}（{conn.connector.kind}）" if conn else key
    return key


def upstream_of(user, entity_type: str, key: str, depth: int = 3) -> dict:
    """查询上游：返回分层节点与边。"""
    return _bfs(user, entity_type, key, "upstream", depth)


def downstream_of(user, entity_type: str, key: str, depth: int = 3) -> dict:
    """查询下游：返回分层节点与边。"""
    return _bfs(user, entity_type, key, "downstream", depth)


def impact_analysis(user, entity_type: str, key: str, depth: int = 4) -> dict:
    """影响分析：某个实体变化会波及哪些管道 / 数据集 / Webhook。"""
    traversal = downstream_of(user, entity_type, key, depth)
    pipelines = [n for n in traversal["nodes"] if n["type"] == "pipeline"]
    datasets = [n for n in traversal["nodes"] if n["type"] == "dataset"]
    webhooks = [n for n in traversal["nodes"] if n["type"] == "webhook"]
    details = []
    for item in pipelines:
        pipeline = Pipeline.objects.filter(owner=user, code=item["key"]).first()
        if pipeline is None:
            continue
        details.append({
            "id": pipeline.id,
            "code": pipeline.code,
            "name": pipeline.name,
            "status": pipeline.status,
            "last_run_status": pipeline.last_run_status,
            "level": item["level"],
        })
    details.sort(key=lambda item: (item["level"], item["code"]))
    return {
        "root": traversal["root"],
        "depth": traversal["depth"],
        "affected_pipelines": len(details),
        "affected_datasets": len(datasets),
        "affected_webhooks": len(webhooks),
        "pipelines": details,
        "datasets": datasets,
        "webhooks": webhooks,
        "edges": traversal["edges"],
        "risk": "high" if len(details) >= 5 else ("medium" if details else "low"),
    }


def graph(user, pipeline=None, depth: int = 3) -> dict:
    """全图 / 单管道子图：节点去重后返回，前端用 dagre 类布局直接渲染。"""
    queryset = LineageEdge.objects.filter(owner=user)
    if pipeline is not None:
        one_way = queryset.filter(pipeline=pipeline)
        # 取出与该管道直接相连的实体，再各自向外扩一层
        keys = set()
        for edge in one_way:
            keys.add((edge.upstream_type, edge.upstream_key))
            keys.add((edge.downstream_type, edge.downstream_key))
        related = []
        for entity_type, key in keys:
            related.extend(upstream_of(user, entity_type, key, depth)["edges"])
            related.extend(downstream_of(user, entity_type, key, depth)["edges"])
        edge_ids = {item["id"] for item in related}
        edges = [e for e in queryset if e.id in edge_ids]
    else:
        edges = list(queryset.order_by("id")[:2000])

    node_map: dict[tuple[str, str], dict] = {}
    for edge in edges:
        for entity_type, key in ((edge.upstream_type, edge.upstream_key),
                                 (edge.downstream_type, edge.downstream_key)):
            node_map.setdefault((entity_type, key), {
                "id": f"{entity_type}:{key}",
                "type": entity_type,
                "key": key,
                "label": _label_for(entity_type, key),
            })
    return {
        "nodes": sorted(node_map.values(), key=lambda n: (n["type"], n["key"])),
        "edges": [_edge_dict(edge) for edge in edges],
        "node_count": len(node_map),
        "edge_count": len(edges),
    }


def lineage_for_pipeline(pipeline) -> dict:
    """单管道的血缘摘要：上游实体、下游实体与字段映射。"""
    pipeline_key = pipeline.code
    upstream = list(LineageEdge.objects.filter(
        owner=pipeline.owner, downstream_type="pipeline",
        downstream_key=pipeline_key).order_by("id"))
    downstream = list(LineageEdge.objects.filter(
        owner=pipeline.owner, upstream_type="pipeline",
        upstream_key=pipeline_key).order_by("id"))
    return {
        "pipeline_id": pipeline.id,
        "pipeline_code": pipeline.code,
        "upstream": [_edge_dict(e) for e in upstream],
        "downstream": [_edge_dict(e) for e in downstream],
        "upstream_count": len(upstream),
        "downstream_count": len(downstream),
    }


# ---------------------------------------------------------------------------
# 画像
# ---------------------------------------------------------------------------


def _infer_type(values: list) -> str:
    if not values:
        return "unknown"
    numeric = 0
    bools = 0
    datetimes = 0
    for value in values:
        if isinstance(value, bool):
            bools += 1
        elif to_number(value) is not None:
            numeric += 1
        if parse_datetime_value(value) is not None:
            datetimes += 1
    total = len(values)
    if numeric == total:
        return "number"
    if bools == total:
        return "boolean"
    if datetimes >= total * 0.8 and not isinstance(values[0], (int, float)):
        return "datetime"
    return "string"


def _length_distribution(values: list[str]) -> dict:
    buckets = {"empty": 0, "1-10": 0, "11-50": 0, "51-200": 0, "200+": 0}
    total_len = 0
    lengths = []
    for value in values:
        size = len(value)
        lengths.append(size)
        total_len += size
        if size == 0:
            buckets["empty"] += 1
        elif size <= 10:
            buckets["1-10"] += 1
        elif size <= 50:
            buckets["11-50"] += 1
        elif size <= 200:
            buckets["51-200"] += 1
        else:
            buckets["200+"] += 1
    return {
        "buckets": buckets,
        "min": min(lengths) if lengths else 0,
        "max": max(lengths) if lengths else 0,
        "avg": round(total_len / len(lengths), 2) if lengths else 0,
    }


def _column_profile(name: str, values: list, total_rows: int) -> dict:
    """单字段画像：空值、唯一值、最值、均值、长度分布、TOP 值。"""
    non_null = [v for v in values if v is not None and v != ""]
    null_count = total_rows - len(non_null)
    kind = _infer_type(non_null)
    profile = {
        "name": name,
        "type": kind,
        "count": len(non_null),
        "null_count": null_count,
        "null_rate": round(null_count / total_rows, 4) if total_rows else 0,
        "distinct_count": len({to_text(v) for v in non_null}),
        "unique_rate": round(len({to_text(v) for v in non_null}) / len(non_null), 4)
        if non_null else 0,
        "min": None,
        "max": None,
        "mean": None,
        "median": None,
        "stddev": None,
        "length": None,
        "top_values": [],
        "samples": [v if not isinstance(v, (dict, list)) else to_text(v)
                    for v in non_null[:3]],
    }
    if kind == "number":
        numbers = [to_number(v) for v in non_null]
        numbers = [n for n in numbers if n is not None]
        if numbers:
            avg = sum(numbers) / len(numbers)
            ordered = sorted(numbers)
            mid = len(ordered) // 2
            median = (ordered[mid] if len(ordered) % 2
                      else (ordered[mid - 1] + ordered[mid]) / 2)
            variance = sum((n - avg) ** 2 for n in numbers) / len(numbers)
            profile.update({
                "min": min(numbers), "max": max(numbers),
                "mean": round(avg, 4), "median": round(median, 4),
                "stddev": round(math.sqrt(variance), 4),
            })
    elif kind == "datetime":
        parsed = [parse_datetime_value(v) for v in non_null]
        parsed = [p for p in parsed if p is not None]
        if parsed:
            profile.update({"min": min(parsed).isoformat(),
                            "max": max(parsed).isoformat()})
    elif kind in ("string", "unknown"):
        texts = [to_text(v) for v in non_null]
        if texts:
            profile.update({"min": min(texts)[:120], "max": max(texts)[:120],
                            "length": _length_distribution(texts)})
    counter = Counter(to_text(v) for v in non_null)
    profile["top_values"] = [
        {"value": value, "count": count}
        for value, count in counter.most_common(5)
    ]
    return profile


def profile_rows(rows: list[dict], dataset: str = "default",
                 sample_size: int = DEFAULT_PROFILE_SAMPLE) -> dict:
    """对行集做字段级画像；按 sample_size 采样，字段取并集。"""
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    if not rows:
        raise ValueError("没有可画像的数据")
    sample = rows[:max(1, min(int(sample_size or DEFAULT_PROFILE_SAMPLE), MAX_RUN_ROWS))]
    names: list[str] = []
    for row in sample:
        for key in row.keys():
            if key not in names:
                names.append(key)
    columns = [_column_profile(name, [row.get(name) for row in sample], len(sample))
               for name in names]
    return {
        "dataset": dataset,
        "row_count": len(rows),
        "sample_size": len(sample),
        "column_count": len(columns),
        "columns": columns,
        "null_columns": [c["name"] for c in columns if c["null_count"] == len(sample)],
        "high_null_columns": [c["name"] for c in columns if c["null_rate"] >= 0.5],
        "constant_columns": [c["name"] for c in columns if c["distinct_count"] == 1],
    }


def _sink_dataset(pipeline) -> str:
    for node in pipeline.nodes.filter(node_type="sink").order_by("order", "id"):
        dataset = str((node.config or {}).get("dataset") or "").strip()
        if dataset:
            return dataset
    return "default"


@transaction.atomic
def generate_profile(user, pipeline, run=None, dataset: str = "",
                     rows: list[dict] | None = None,
                     sample_size: int = DEFAULT_PROFILE_SAMPLE) -> DatasetProfile:
    """生成画像：数据来源优先级 rows > run > 最近成功运行。"""
    if rows is None:
        if run is not None:
            rows = list(PipelineOutput.objects.filter(run=run)
                        .order_by("seq", "id")
                        .values_list("data", flat=True)[:MAX_RUN_ROWS])
        else:
            latest = pipeline.runs.filter(status="success").order_by("-started_at", "-id").first()
            if latest is not None:
                run = latest
                rows = list(PipelineOutput.objects.filter(run=latest)
                            .order_by("seq", "id")
                            .values_list("data", flat=True)[:MAX_RUN_ROWS])
            else:
                rows = []
    if not rows:
        raise ValueError("没有可画像的数据，请先运行管道或传入 rows")
    dataset = (dataset or _sink_dataset(pipeline) or "default")[:120]
    result = profile_rows(rows, dataset=dataset, sample_size=sample_size)
    profile = DatasetProfile.objects.create(
        owner=user,
        pipeline=pipeline,
        run=run,
        dataset=dataset,
        row_count=result["row_count"],
        sample_size=result["sample_size"],
        columns=result["columns"],
        sampled_at=timezone.now(),
        notes=(f"采样 {result['sample_size']} 行 / 共 {result['row_count']} 行"),
    )
    return profile


def profile_summary(profile: DatasetProfile) -> dict:
    """画像详情：把冗余字段（列数、高缺失列）一并回显，前端少算一次。"""
    columns = profile.columns or []
    return {
        "id": profile.id,
        "pipeline_id": profile.pipeline_id,
        "run_id": profile.run_id,
        "dataset": profile.dataset,
        "row_count": profile.row_count,
        "sample_size": profile.sample_size,
        "column_count": len(columns),
        "columns": columns,
        "high_null_columns": [c.get("name") for c in columns
                              if (c.get("null_rate") or 0) >= 0.5],
        "sampled_at": profile.sampled_at.isoformat() if profile.sampled_at else None,
        "notes": profile.notes,
    }


def compare_profiles(left: DatasetProfile, right: DatasetProfile) -> dict:
    """两次画像对比：行数变化 + 每列空值率 / 唯一值变化。"""
    left_cols = {c.get("name"): c for c in (left.columns or [])}
    right_cols = {c.get("name"): c for c in (right.columns or [])}
    names = sorted(set(left_cols) | set(right_cols))
    diffs = []
    for name in names:
        a, b = left_cols.get(name), right_cols.get(name)
        diffs.append({
            "name": name,
            "null_rate_a": (a or {}).get("null_rate", 0),
            "null_rate_b": (b or {}).get("null_rate", 0),
            "null_rate_delta": round((b or {}).get("null_rate", 0)
                                     - (a or {}).get("null_rate", 0), 4),
            "distinct_a": (a or {}).get("distinct_count", 0),
            "distinct_b": (b or {}).get("distinct_count", 0),
            "added": a is None,
            "removed": b is None,
        })
    return {
        "left": {"id": left.id, "row_count": left.row_count,
                 "sampled_at": left.sampled_at.isoformat() if left.sampled_at else None},
        "right": {"id": right.id, "row_count": right.row_count,
                  "sampled_at": right.sampled_at.isoformat() if right.sampled_at else None},
        "row_delta": right.row_count - left.row_count,
        "columns": diffs,
    }
