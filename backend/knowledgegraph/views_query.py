# -*- coding: utf-8 -*-
"""knowledgegraph · 保存查询与标签接口：查询 8 + 标签 4 = 12。

保存查询有两种形态：
- params 形态：kind + 结构化参数，前端可视化编辑器直接维护；
- DSL 形态：kind=cypher_like + dsl 文本，执行时以 DSL 解析出的真实
  kind 为准（neighbors/path/subgraph/search），保存的 kind 只作为分类标签。

每次执行都写 QueryRun（失败也写），失败记录先落库再抛 ValueError，
保证「历史里能看到失败原因」与「接口返回 400」两件事同时成立。
"""
import time

from django.db import transaction

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_str, p, req_num, req_str
from knowledgegraph import services
from knowledgegraph.common import (bool_arg, choice_arg, clamp, clamp_weight,
                                   entity_for_write,
                                   float_arg, int_arg, json_arg, list_queryset,
                                   page_args, page_payload, read_obj,
                                   record_audit, run_dict, slice_page, tag_dict,
                                   write_obj)
from knowledgegraph.models import (Entity, EntityTag, GraphQuery, Ontology,
                                   QueryRun)
from knowledgegraph.views_graph import (_enrich_edges, _enrich_nodes,
                                        _load_graph, _node_payload)

QUERY_KIND_VALUES = ("neighbors", "path", "subgraph", "search", "cypher_like")


def _visible_ontology(ontology_id, user):
    """本体可空：查询可以跨本体，也可以绑定某个本体。"""
    if not ontology_id:
        return None
    return read_obj(Ontology, ontology_id, user, "本体")


def _validate_query_payload(kind, dsl, params):
    """校验保存查询的参数：DSL 与 params 至少有一个可用。"""
    if kind not in QUERY_KIND_VALUES:
        raise ValueError(f"查询类型仅支持: {'/'.join(QUERY_KIND_VALUES)}")
    params = params if isinstance(params, dict) else {}
    if dsl:
        parsed = services.parse_dsl(dsl)
        services.validate_dsl_params(parsed["kind"], parsed["params"])
        return dsl, params
    if kind == "cypher_like":
        raise ValueError("DSL 查询必须提供 dsl 文本")
    normalized = services.validate_dsl_params(kind, params)
    return "", normalized


def _execute(user, kind, dsl, params, ontology_id=None):
    """执行一次查询并返回 (结果, 实际 kind, 规范化参数, 节点数, 边数)。"""
    if dsl:
        parsed = services.parse_dsl(dsl)
        actual_kind = parsed["kind"]
        actual_params = services.validate_dsl_params(actual_kind, parsed["params"])
    else:
        actual_kind = kind
        if actual_kind == "cypher_like":
            raise ValueError("DSL 查询必须提供 dsl 文本")
        actual_params = services.validate_dsl_params(actual_kind, params)

    graph = _load_graph(user, ontology_id)

    def exists(entity_id):
        return entity_id in graph["entity_map"]

    def search_fn(query, limit, type_ids):
        from knowledgegraph.common import search_entities_for_user

        return search_entities_for_user(user, query, ontology_id=ontology_id,
                                        type_ids=type_ids, limit=limit)

    result = services.run_dsl({"kind": actual_kind, "params": actual_params},
                              {"adjacency": graph["adjacency"], "exists": exists,
                               "search": search_fn})
    if actual_kind in ("neighbors", "subgraph"):
        result["nodes"] = _enrich_nodes(graph, result.get("nodes", []))
        result["edges"] = _enrich_edges(graph, result.get("edges", []))
        if result.get("center"):
            result["center"] = _node_payload(graph, result["center"])
    elif actual_kind == "path":
        result["nodes"] = [_node_payload(graph, node)
                           for node in result.get("path", [])]
        result["edges"] = _enrich_edges(
            graph, services.path_edges(result.get("path", []), graph["relations"]))
    node_count = len(result.get("nodes") or result.get("items") or [])
    edge_count = len(result.get("edges") or [])
    return result, actual_kind, actual_params, node_count, edge_count


@endpoint()
def query_create(request):
    """保存查询（校验 DSL / 参数，可绑定本体）。"""
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("查询名称不能为空")
    kind = choice_arg(request, "kind", QUERY_KIND_VALUES, "neighbors")
    ontology = _visible_ontology(int_arg(request, "ontology_id"), request.user)
    dsl = opt_str(request, "dsl", "")[:2000]
    params = json_arg(request, "params", {})
    dsl, params = _validate_query_payload(kind, dsl, params)
    row = GraphQuery.objects.create(
        owner=request.user, ontology=ontology, name=name[:120], kind=kind,
        dsl=dsl, params=params,
        description=opt_str(request, "description")[:2000],
    )
    record_audit(request.user, "query.create", ontology.id if ontology else None,
                 "query", row.id, f"保存查询 {row.name}")
    from knowledgegraph.common import query_dict

    return ok(query_dict(row))


@endpoint(("GET",))
def query_list(request):
    """保存查询列表（支持类型 / 本体 / 关键字）。"""
    qs = scope_queryset(GraphQuery.objects.all(), request.user).order_by("-updated_at")
    rows, total, page, size = list_queryset(
        request, qs, ["name", "description", "dsl"], status_field=None,
        extra_filters={"kind": ("kind", str), "ontology_id": ("ontology_id", int)},
    )
    from knowledgegraph.common import query_dict

    return ok(page_payload([query_dict(q) for q in rows], total, page, size))


@endpoint(("GET",))
def query_detail(request, pk):
    """保存查询详情（附最近执行记录）。"""
    query = read_obj(GraphQuery, pk, request.user, "查询")
    from knowledgegraph.common import query_dict

    data = query_dict(query)
    data["recent_runs"] = [run_dict(r) for r in query.runs.all()[:10]]
    return ok(data)


@endpoint()
def query_update(request, pk):
    """更新保存查询（重新校验参数；类型变更时参数必须匹配）。"""
    query = write_obj(GraphQuery, pk, request.user, "查询")
    kind = query.kind
    if p(request, "kind") not in (None, ""):
        kind = choice_arg(request, "kind", QUERY_KIND_VALUES, query.kind)
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("查询名称不能为空")
        query.name = name[:120]
    if p(request, "description") is not None:
        query.description = opt_str(request, "description")[:2000]
    if p(request, "ontology_id") is not None:
        query.ontology = _visible_ontology(int_arg(request, "ontology_id"),
                                           request.user)
    dsl = opt_str(request, "dsl", query.dsl)[:2000]
    params = json_arg(request, "params", query.params or {})
    dsl, params = _validate_query_payload(kind, dsl, params)
    query.kind = kind
    query.dsl = dsl
    query.params = params
    query.save()
    return ok({"id": query.id, "kind": query.kind, "name": query.name})


@endpoint()
def query_delete(request, pk):
    """删除保存查询（执行历史保留，query 置空）。"""
    query = write_obj(GraphQuery, pk, request.user, "查询")
    query_id = query.id
    query.delete()
    return ok({"id": query_id, "deleted": True})


@endpoint()
def query_run(request, pk):
    """执行保存查询并记录 QueryRun（失败也落历史）。"""
    query = read_obj(GraphQuery, pk, request.user, "查询")
    override = json_arg(request, "params", {}) if p(request, "params") else {}
    params = {**(query.params or {}), **override}
    dsl = opt_str(request, "dsl", query.dsl)[:2000]
    started = time.perf_counter()
    try:
        result, actual_kind, actual_params, node_count, edge_count = _execute(
            request.user, query.kind, dsl, params,
            query.ontology_id)
    except ValueError as exc:
        QueryRun.objects.create(
            owner=request.user, query=query, kind=query.kind, params=params,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            node_count=0, edge_count=0, status="failed", error=str(exc)[:2000],
        )
        raise
    elapsed = int((time.perf_counter() - started) * 1000)
    run = QueryRun.objects.create(
        owner=request.user, query=query, kind=actual_kind, params=actual_params,
        elapsed_ms=elapsed, node_count=node_count, edge_count=edge_count,
        status="success",
    )
    result["run_id"] = run.id
    result["elapsed_ms"] = elapsed
    return ok(result)


@endpoint(("GET",))
def query_history(request):
    """查询执行历史（支持查询 id / 状态 / 类型）。"""
    qs = scope_queryset(QueryRun.objects.all(), request.user).order_by("-created_at")
    rows, total, page, size = list_queryset(
        request, qs, ["error"], "status",
        extra_filters={"query_id": ("query_id", int), "kind": ("kind", str)},
    )
    return ok(page_payload([run_dict(r) for r in rows], total, page, size,
                           success=QueryRun.objects.filter(
                               owner=request.user, status="success").count()))


@endpoint(("GET",))
def query_runs(request, pk):
    """某个保存查询的执行历史。"""
    query = read_obj(GraphQuery, pk, request.user, "查询")
    page, size = page_args(request)
    qs = query.runs.all().order_by("-created_at")
    rows, total = slice_page(qs, page, size)
    return ok(page_payload([run_dict(r) for r in rows], total, page, size,
                           query_id=query.id))


# ---------------------------------------------------------------------------
# 标签
# ---------------------------------------------------------------------------


@endpoint()
def tag_create(request):
    """给实体打标签（同一实体同标签唯一，重复时累加权重）。"""
    entity_id = req_num(request, "entity_id")
    entity = entity_for_write(entity_id, request.user)
    tag = req_str(request, "tag", max_len=60).strip()
    if not tag:
        raise ValueError("标签不能为空")
    weight = clamp_weight(float_arg(request, "weight", 1.0, minimum=0.01,
                                    maximum=100), 1.0)
    row, created = EntityTag.objects.get_or_create(
        entity=entity, tag=tag[:60],
        defaults={"owner": request.user, "weight": weight})
    if not created:
        row.weight = round(min(100.0, row.weight + weight), 4)
        row.save(update_fields=["weight", "updated_at"])
    return ok({**tag_dict(row), "created": created})


@endpoint(("GET",))
def tag_list(request):
    """标签列表（支持实体 / 标签关键字 / 权重下限）。"""
    qs = scope_queryset(EntityTag.objects.all(), request.user).order_by("-weight", "id")
    entity_id = int_arg(request, "entity_id")
    if entity_id:
        qs = qs.filter(entity_id=entity_id)
    rows, total, page, size = list_queryset(
        request, qs, ["tag"], status_field=None,
        extra_filters={"min_weight": ("weight__gte", float)},
    )
    return ok(page_payload([tag_dict(t) for t in rows], total, page, size))


@endpoint()
def tag_update(request, pk):
    """更新标签（文本 / 权重）。"""
    row = write_obj(EntityTag, pk, request.user, "标签")
    if p(request, "tag") is not None:
        tag = opt_str(request, "tag").strip()
        if not tag:
            raise ValueError("标签不能为空")
        conflict = EntityTag.objects.filter(entity_id=row.entity_id,
                                             tag=tag).exclude(pk=row.pk).exists()
        if conflict:
            raise ValueError("该实体已存在同名标签")
        row.tag = tag[:60]
    if p(request, "weight") is not None:
        row.weight = clamp_weight(float_arg(request, "weight", minimum=0.01,
                                          maximum=100), row.weight)
    row.save()
    return ok(tag_dict(row))


@endpoint()
def tag_delete(request, pk):
    """删除标签。"""
    row = write_obj(EntityTag, pk, request.user, "标签")
    row_id = row.id
    row.delete()
    return ok({"id": row_id, "deleted": True})


QUERY_FAMILY_COUNT = 8 + 4
