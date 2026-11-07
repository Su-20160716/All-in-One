# -*- coding: utf-8 -*-
"""knowledgegraph · 图查询接口：邻居 / 路径 / 子图 / 搜索 / DSL 预览 / DSL 执行 / 环路 / K 短路 = 8。

统一口径：
- 只读生效实体与生效关系（status='active'）；
- 数据范围由 scope_queryset 决定，DSL 里的实体 id 也必须先过存在性校验，
  否则用户可以借 DSL 探测他人图谱里有哪些 id；
- 深度上限 5、单次节点上限 500，超限 400；
- 路径不存在返回 {"path": [], "found": false}，不是错误。
"""
import time

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_str, p, req_num, req_str
from knowledgegraph import analytics, services
from knowledgegraph.common import (bool_arg, float_arg, ids_arg, int_arg,
                                   read_obj, record_audit,
                                   search_entities_for_user)
from knowledgegraph.models import (MAX_GRAPH_NODES, MAX_TRAVERSAL_DEPTH, Entity,
                                   Ontology, Relation, RelationType)

# 图加载上限：超过后一次性构图会把请求内存打满；要求先按本体收窄。
GRAPH_ENTITY_LIMIT = 5000
GRAPH_RELATION_LIMIT = 20000


def _load_graph(user, ontology_id=None):
    """按数据范围加载图数据并构建邻接表。

    返回的 entity_map 同时用于「节点是否存在」校验，避免遍历到不可见节点；
    relation 查询预取 relation_type，directed 标志直接决定邻接表是否加反向边。
    """
    entities_qs = scope_queryset(
        Entity.objects.filter(status="active").select_related("entity_type"),
        user,
    )
    if ontology_id:
        ontology = read_obj(Ontology, ontology_id, user, "本体")
        entities_qs = entities_qs.filter(ontology=ontology)
    entity_count = entities_qs.count()
    if entity_count > GRAPH_ENTITY_LIMIT:
        raise ValueError(
            f"图谱实体数 {entity_count} 超过上限 {GRAPH_ENTITY_LIMIT}，"
            "请指定 ontology_id 缩小范围")
    entity_rows = list(entities_qs[:GRAPH_ENTITY_LIMIT])
    entity_map = {e["id"]: e for e in (services.entity_lite(row) for row in entity_rows)}
    ontology_ids = sorted({e["ontology_id"] for e in entity_map.values()})
    relations_qs = scope_queryset(
        Relation.objects.filter(status="active", ontology_id__in=ontology_ids)
        .select_related("relation_type"),
        user,
    )
    relation_count = relations_qs.count()
    if relation_count > GRAPH_RELATION_LIMIT:
        raise ValueError(
            f"图谱关系数 {relation_count} 超过上限 {GRAPH_RELATION_LIMIT}，"
            "请指定 ontology_id 或按类型收窄")
    relation_rows = [services.relation_lite(r) for r in
                     relations_qs[:GRAPH_RELATION_LIMIT]]
    # 只保留两端都可见的关系，避免出现「边在但端点不可见」的畸形子图
    relation_rows = [r for r in relation_rows
                     if r["src"] in entity_map and r["dst"] in entity_map]
    return {
        "entities": list(entity_map.values()),
        "entity_map": entity_map,
        "relations": relation_rows,
        "adjacency": services.build_adjacency(relation_rows),
        "entity_objects": {row.id: row for row in entity_rows},
        "type_names": {t.id: t.name for t in
                       RelationType.objects.filter(ontology_id__in=ontology_ids)},
        "ontology_ids": ontology_ids,
    }


def _node_payload(graph, node_id):
    """节点展示信息：名称 / 类型 / 类型颜色；找不到时只回 id。"""
    entity = graph["entity_map"].get(node_id)
    if entity is None:
        return {"id": node_id, "name": "", "entity_type_id": None,
                "entity_type": "", "color": ""}
    etype = graph["entity_objects"][node_id].entity_type
    return {
        "id": node_id,
        "name": entity["name"],
        "canonical_name": entity["canonical_name"],
        "entity_type_id": entity["entity_type_id"],
        "entity_type": etype.name,
        "color": etype.color,
        "confidence": entity["confidence"],
    }


def _enrich_nodes(graph, nodes):
    """给算法输出的 id 节点补展示字段，保持距离 / 深度字段不丢。"""
    enriched = []
    for node in nodes:
        payload = _node_payload(graph, node["id"])
        payload.update({k: v for k, v in node.items() if k != "id"})
        enriched.append(payload)
    return enriched


def _enrich_edges(graph, edges):
    """给边补关系类型中文名与端点名称，前端无需二次请求。"""
    out = []
    for edge in edges:
        row = dict(edge)
        row["relation_type"] = graph["type_names"].get(edge.get("type_id"), "")
        row["source_name"] = graph["entity_map"].get(edge.get("source"), {}).get("name", "")
        row["target_name"] = graph["entity_map"].get(edge.get("target"), {}).get("name", "")
        out.append(row)
    return out


def _missing_entity(entity_id, graph):
    """端点校验：不可见 / 已归档 / 不在当前图里都按「不存在」处理。"""
    if entity_id not in graph["entity_map"]:
        raise ValueError("实体不存在或无权访问")


@endpoint(("GET",))
def graph_neighbors(request):
    """邻居查询（深度 1–5，支持方向 / 类型 / 权重 / 置信度过滤）。"""
    entity_id = int_arg(request, "entity_id") or int_arg(request, "start_id")
    if not entity_id:
        raise ValueError("缺少必填参数: entity_id")
    depth = int_arg(request, "depth", 1, minimum=1, maximum=MAX_TRAVERSAL_DEPTH)
    direction = opt_str(request, "direction", "both").strip() or "both"
    type_ids = ids_arg(request, "type_ids")
    ontology_id = int_arg(request, "ontology_id")
    entity = read_obj(Entity, entity_id, request.user, "实体")
    graph = _load_graph(request.user, ontology_id or entity.ontology_id)
    _missing_entity(entity_id, graph)
    result = services.neighbors(
        entity_id, graph["adjacency"], direction=direction, depth=depth,
        type_ids=type_ids,
        min_weight=float_arg(request, "min_weight"),
        min_confidence=float_arg(request, "min_confidence"),
        limit=int_arg(request, "limit", 200, minimum=1, maximum=MAX_GRAPH_NODES),
    )
    result["nodes"] = _enrich_nodes(graph, result["nodes"])
    result["edges"] = _enrich_edges(graph, result["edges"])
    result["center"] = _node_payload(graph, entity_id)
    return ok(result)


@endpoint(("GET",))
def graph_path(request):
    """最短路径（默认 BFS，weighted=true 时用 Dijkstra；不可达返回空数组）。"""
    start_id = int_arg(request, "start_id") or int_arg(request, "start")
    end_id = int_arg(request, "end_id") or int_arg(request, "end")
    if not start_id or not end_id:
        raise ValueError("缺少必填参数: start_id / end_id")
    max_depth = int_arg(request, "max_depth", MAX_TRAVERSAL_DEPTH, minimum=1,
                        maximum=MAX_TRAVERSAL_DEPTH)
    weighted = bool_arg(request, "weighted", False)
    direction = opt_str(request, "direction", "both").strip() or "both"
    type_ids = ids_arg(request, "type_ids")
    start = read_obj(Entity, start_id, request.user, "起点实体")
    end = read_obj(Entity, end_id, request.user, "终点实体")
    if start.ontology_id != end.ontology_id:
        return ok({"path": [], "nodes": [], "edges": [], "found": False,
                   "cost": None, "cached": False,
                   "reason": "起点与终点不在同一本体"})
    graph = _load_graph(request.user, start.ontology_id)
    _missing_entity(start_id, graph)
    _missing_entity(end_id, graph)

    started = time.perf_counter()
    cached = services.path_cache_lookup(
        start.ontology_id, start_id, end_id, max_depth, weighted,
        owner=request.user)
    if cached is not None:
        path, cost = list(cached.path or []), cached.cost
        cache_hit = True
    elif weighted:
        path, cost = services.shortest_path_weighted(
            start_id, end_id, graph["adjacency"], direction=direction,
            type_ids=type_ids, weight_mode="inverse")
        cache_hit = False
    else:
        path = services.shortest_path(
            start_id, end_id, graph["adjacency"], direction=direction,
            type_ids=type_ids)
        cost = None
        cache_hit = False
    if not cache_hit:
        services.store_path_cache(start.ontology_id, start_id, end_id,
                                  max_depth, path, cost or 0, weighted,
                                  owner=request.user)
    nodes = [_node_payload(graph, node) for node in path]
    result = {
        "path": path,
        "nodes": nodes,
        "edges": _enrich_edges(graph, services.path_edges(path, graph["relations"])),
        "found": bool(path),
        "cost": cost,
        "cached": cache_hit,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    record_audit(request.user, "graph.path", start.ontology_id, "entity",
                 start_id, f"路径查询 {start_id}→{end_id}",
                 {"found": bool(path), "length": len(path)})
    return ok(result)


@endpoint(("GET",))
def graph_subgraph(request):
    """K 跳子图（深度 ≤ 5、节点 ≤ 500）。"""
    entity_id = int_arg(request, "entity_id") or int_arg(request, "start_id")
    if not entity_id:
        raise ValueError("缺少必填参数: entity_id")
    depth = int_arg(request, "depth", 2)
    # 显式中文提示：遍历深度超限是最常见的误用，报错里必须出现「深度」
    if depth < 1 or depth > MAX_TRAVERSAL_DEPTH:
        raise ValueError(f"遍历深度 depth 必须在 1–{MAX_TRAVERSAL_DEPTH} 之间")
    direction = opt_str(request, "direction", "both").strip() or "both"
    entity = read_obj(Entity, entity_id, request.user, "实体")
    graph = _load_graph(request.user, int_arg(request, "ontology_id") or entity.ontology_id)
    _missing_entity(entity_id, graph)
    result = services.subgraph(
        entity_id, graph["adjacency"], depth=depth, direction=direction,
        type_ids=ids_arg(request, "type_ids"),
        min_weight=float_arg(request, "min_weight"),
        min_confidence=float_arg(request, "min_confidence"),
        limit=int_arg(request, "limit", 200, minimum=1, maximum=MAX_GRAPH_NODES),
    )
    result["nodes"] = _enrich_nodes(graph, result["nodes"])
    result["edges"] = _enrich_edges(graph, result["edges"])
    result["center"] = _node_payload(graph, entity_id)
    return ok(result)


@endpoint(("GET",))
def graph_search(request):
    """图内实体搜索（名称 / 别名 / 描述 / 属性加权）。"""
    q = req_str(request, "q", max_len=200).strip()
    result = search_entities_for_user(
        request.user, q,
        ontology_id=int_arg(request, "ontology_id"),
        type_ids=ids_arg(request, "type_ids"),
        limit=int_arg(request, "limit", 20, minimum=1, maximum=MAX_GRAPH_NODES),
    )
    return ok(result)


@endpoint()
def graph_dsl_preview(request):
    """DSL 解析预览：只做语法与参数校验，不查库、不返回数据。"""
    text = req_str(request, "dsl", max_len=2000)
    parsed = services.parse_dsl(text)
    normalized = services.validate_dsl_params(parsed["kind"], parsed["params"])
    return ok({
        "kind": parsed["kind"],
        "params": normalized,
        "raw": parsed["raw"],
        "grammar": "func(key=value, ...)",
        "allowed": sorted(services.DSL_ALLOWED_KEYS[parsed["kind"]]),
        "required": sorted(services.DSL_REQUIRED_KEYS[parsed["kind"]]),
    })


@endpoint()
def graph_dsl_execute(request):
    """执行 DSL（neighbors/path/subgraph/search），结果做节点与边补全。"""
    text = req_str(request, "dsl", max_len=2000)
    parsed = services.parse_dsl(text)
    ontology_id = int_arg(request, "ontology_id")
    graph = _load_graph(request.user, ontology_id)
    started = time.perf_counter()

    def exists(entity_id):
        return entity_id in graph["entity_map"]

    def search_fn(query, limit, type_ids):
        return search_entities_for_user(request.user, query,
                                        ontology_id=ontology_id,
                                        type_ids=type_ids, limit=limit)

    result = services.run_dsl(parsed, {
        "adjacency": graph["adjacency"],
        "exists": exists,
        "search": search_fn,
    })
    elapsed = int((time.perf_counter() - started) * 1000)
    kind = parsed["kind"]
    if kind in ("neighbors", "subgraph"):
        result["nodes"] = _enrich_nodes(graph, result.get("nodes", []))
        result["edges"] = _enrich_edges(graph, result.get("edges", []))
        if result.get("center"):
            result["center"] = _node_payload(graph, result["center"])
    elif kind == "path":
        result["nodes"] = [_node_payload(graph, node)
                           for node in result.get("path", [])]
        result["edges"] = _enrich_edges(
            graph, services.path_edges(result.get("path", []), graph["relations"]))
    result["kind"] = kind
    result["elapsed_ms"] = elapsed
    record_audit(request.user, "graph.dsl", ontology_id, "query", None,
                 f"执行 DSL {kind}", {"dsl": parsed["raw"][:500],
                                      "elapsed_ms": elapsed})
    return ok(result)


@endpoint(("GET",))
def graph_cycles(request):
    """环路检测（长度 ≤ max_length 的简单环，用于发现互为上下级等脏数据）。"""
    ontology_id = int_arg(request, "ontology_id")
    graph = _load_graph(request.user, ontology_id)
    directed = bool_arg(request, "directed", True)
    result = analytics.find_cycles(
        graph["entities"], graph["relations"],
        max_cycles=int_arg(request, "max_cycles", 20, minimum=1, maximum=200),
        max_length=int_arg(request, "max_length", 5, minimum=2, maximum=10),
        directed=directed)
    # 补充节点展示信息：前端拿到环后可以直接高亮，不必再逐点查询
    for cycle in result["items"]:
        cycle["nodes_detail"] = [_node_payload(graph, node)
                                 for node in cycle["nodes"]]
    return ok(result)


@endpoint(("GET",))
def graph_k_paths(request):
    """K 条备选最短路径（Yen 算法，按代价升序，最多 10 条）。"""
    start_id = int_arg(request, "start_id") or int_arg(request, "start")
    end_id = int_arg(request, "end_id") or int_arg(request, "end")
    if not start_id or not end_id:
        raise ValueError("缺少必填参数: start_id / end_id")
    start = read_obj(Entity, start_id, request.user, "起点实体")
    end = read_obj(Entity, end_id, request.user, "终点实体")
    if start.ontology_id != end.ontology_id:
        return ok({"items": [], "count": 0, "k": 1,
                   "reason": "起点与终点不在同一本体"})
    max_depth = int_arg(request, "max_depth", MAX_TRAVERSAL_DEPTH)
    if max_depth < 1 or max_depth > MAX_TRAVERSAL_DEPTH:
        raise ValueError(f"遍历深度 depth 必须在 1–{MAX_TRAVERSAL_DEPTH} 之间")
    graph = _load_graph(request.user, start.ontology_id)
    _missing_entity(start_id, graph)
    _missing_entity(end_id, graph)
    direction = opt_str(request, "direction", "both").strip() or "both"
    if direction not in ("out", "in", "both"):
        raise ValueError("direction 仅支持 out/in/both")
    result = analytics.k_shortest_paths(
        graph["adjacency"], start_id, end_id,
        k=int_arg(request, "k", 3, minimum=1, maximum=10),
        direction=direction,
        type_ids=ids_arg(request, "type_ids"),
        weighted=bool_arg(request, "weighted", True),
    )
    # Yen 会返回任意长度的路径，超过 max_depth 的备选按业务上限过滤掉
    result["items"] = [row for row in result["items"]
                       if row["length"] <= max_depth]
    result["count"] = len(result["items"])
    for row in result["items"]:
        row["nodes"] = [_node_payload(graph, node) for node in row["path"]]
        row["edges"] = _enrich_edges(
            graph, services.path_edges(row["path"], graph["relations"]))
    return ok(result)


GRAPH_FAMILY_COUNT = 6 + 2
