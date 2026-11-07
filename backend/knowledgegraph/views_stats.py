# -*- coding: utf-8 -*-
"""knowledgegraph · 统计接口：概览 / 度 / 分量 / 社区 / 中心性 / 类型 / 增长 +
PageRank / 紧密度 / k-core / 聚类系数 / 密度 / 相似簇 = 13。

统计只读，但同样受数据范围约束：先把当前用户可见的实体与关系取出来，
再交给服务层的纯函数计算。规模保护：
- 图类统计先走 _load_graph（实体 ≤ 5000）；
- 社区 / 介数这类近似 O(V*E) 的算法再收紧到 2000 节点，超过要求按本体收窄。
"""
from django.db.models import Avg, Count
from django.utils import timezone

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_str
from knowledgegraph import analytics, services
from knowledgegraph.common import (float_arg, int_arg, page_args, page_payload,
                                   read_obj, slice_page)
from knowledgegraph.models import (ENTITY_STATUSES, Entity, EntityType,
                                   ExtractionCandidate, ExtractionJob,
                                   GraphSnapshot, MergeRequest, Ontology,
                                   Relation, RelationType, Source)
from knowledgegraph.views_graph import _load_graph

STAT_ALGORITHM_LIMIT = 2000


def _graph_or_fail(user, ontology_id):
    """统计入口统一构图；没有 ontology 参数时按全部可见本体。"""
    graph = _load_graph(user, ontology_id)
    return graph


def _type_names(ontology_ids, model=EntityType):
    """类型 id → 名称映射，供统计结果补中文名。"""
    return {row.id: row.name for row in
            model.objects.filter(ontology_id__in=ontology_ids)}


def _algorithm_guard(graph):
    """社区 / 介数算法的规模闸门：超过 2000 节点直接 400，避免请求超时。"""
    if len(graph["entities"]) > STAT_ALGORITHM_LIMIT:
        raise ValueError(
            f"当前图有 {len(graph['entities'])} 个实体，超过统计上限 "
            f"{STAT_ALGORITHM_LIMIT}，请指定 ontology_id 缩小范围")


@endpoint(("GET",))
def stats_overview(request):
    """图谱概览：规模、状态分布、平均度与平均置信度。"""
    entities = scope_queryset(Entity.objects.all(), request.user)
    relations = scope_queryset(Relation.objects.all(), request.user)
    active_entities = entities.filter(status="active")
    active_relations = relations.filter(status="active")
    ontologies = scope_queryset(Ontology.objects.all(), request.user)
    by_status = {status: entities.filter(status=status).count()
                 for status in ENTITY_STATUSES}
    by_type = list(active_entities.values("entity_type_id")
                   .annotate(count=Count("id")).order_by("-count")[:10])
    # 类型名一次性取全（当前用户可见范围内），避免按行查类型导致 N+1
    type_names = {t.id: t.name for t in
                  scope_queryset(EntityType.objects.all(), request.user)}
    type_rows = [{
        "entity_type_id": row["entity_type_id"],
        "name": type_names.get(row["entity_type_id"], ""),
        "count": row["count"],
    } for row in by_type]
    avg_confidence = active_entities.aggregate(
        value=Avg("confidence"))["value"] or 0.0
    return ok({
        "ontologies": ontologies.count(),
        "published_ontologies": ontologies.filter(status="published").count(),
        "entity_types": scope_queryset(EntityType.objects.all(),
                                       request.user).count(),
        "relation_types": scope_queryset(RelationType.objects.all(),
                                         request.user).count(),
        "entities": active_entities.count(),
        "entities_by_status": by_status,
        "relations": active_relations.count(),
        "deleted_relations": relations.filter(status="deleted").count(),
        "sources": scope_queryset(Source.objects.all(), request.user).count(),
        "extraction_jobs": scope_queryset(ExtractionJob.objects.all(),
                                          request.user).count(),
        "pending_candidates": scope_queryset(ExtractionCandidate.objects.all(),
                                             request.user).filter(
            status="pending").count(),
        "pending_merges": scope_queryset(MergeRequest.objects.all(),
                                         request.user).filter(
            status="pending").count(),
        "snapshots": scope_queryset(GraphSnapshot.objects.all(),
                                    request.user).count(),
        "avg_confidence": round(float(avg_confidence), 4),
        "entity_type_top": type_rows,
        "avg_degree": round(
            (2 * active_relations.count() / active_entities.count())
            if active_entities.count() else 0.0, 4),
        "generated_at": timezone.now().isoformat(),
    })


@endpoint(("GET",))
def stats_degree(request):
    """度分布（出入度 / 分桶 / TOP 节点）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    result = services.degree_distribution(
        graph["entities"], graph["relations"],
        top=int_arg(request, "top", 20, minimum=1, maximum=200))
    return ok(result)


@endpoint(("GET",))
def stats_components(request):
    """连通分量（数量 / 最大分量 / 规模分布）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    result = services.connected_components(
        graph["entities"], graph["relations"],
        top=int_arg(request, "top", 20, minimum=1, maximum=200))
    return ok(result)


@endpoint(("GET",))
def stats_communities(request):
    """社区检测（标签传播，确定性迭代）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    _algorithm_guard(graph)
    result = services.label_propagation(
        graph["entities"], graph["relations"],
        max_iter=int_arg(request, "max_iter", 20, minimum=1, maximum=100),
        top=int_arg(request, "top", 20, minimum=1, maximum=200))
    result["entity_count"] = len(graph["entities"])
    return ok(result)


@endpoint(("GET",))
def stats_centrality(request):
    """中心性 TOP（method=degree/betweenness/both）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    method = opt_str(request, "method", "both").strip() or "both"
    if method not in ("degree", "betweenness", "both"):
        raise ValueError("method 仅支持 degree/betweenness/both")
    top = int_arg(request, "top", 20, minimum=1, maximum=200)
    payload = {}
    if method in ("degree", "both"):
        payload["degree"] = services.degree_centrality(
            graph["entities"], graph["relations"], top=top)
    if method in ("betweenness", "both"):
        _algorithm_guard(graph)
        payload["betweenness"] = services.betweenness_approx(
            graph["entities"], graph["relations"],
            samples=int_arg(request, "samples", 32, minimum=1, maximum=200),
            seed=int_arg(request, "seed", 42, minimum=1, maximum=10 ** 9),
            top=top)
    payload["method"] = method
    payload["entity_count"] = len(graph["entities"])
    return ok(payload)


@endpoint(("GET",))
def stats_types(request):
    """类型分布（实体类型 + 关系类型）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    entity_names = _type_names(set(graph["ontology_ids"]), EntityType)
    relation_names = _type_names(set(graph["ontology_ids"]), RelationType)
    entity_distribution = services.type_distribution(graph["entities"],
                                                     entity_names)
    relation_counter = {}
    for rel in graph["relations"]:
        key = rel.get("type_id")
        relation_counter[key] = relation_counter.get(key, 0) + 1
    relation_rows = sorted(
        ({"relation_type_id": key, "name": relation_names.get(key, ""),
          "count": value} for key, value in relation_counter.items()),
        key=lambda row: (-row["count"], row["relation_type_id"]))
    return ok({
        "entity_types": entity_distribution,
        "relation_types": {"items": relation_rows,
                           "count": len(graph["relations"])},
        "entity_count": len(graph["entities"]),
        "relation_count": len(graph["relations"]),
    })


@endpoint(("GET",))
def stats_growth(request):
    """增长趋势（实体与关系的按日新增 / 累计）。"""
    days = int_arg(request, "days", 30, minimum=1, maximum=365)
    ontology_id = int_arg(request, "ontology_id")
    entities = scope_queryset(Entity.objects.all(), request.user)
    relations = scope_queryset(Relation.objects.filter(status="active"),
                               request.user)
    if ontology_id:
        read_obj(Ontology, ontology_id, request.user, "本体")
        entities = entities.filter(ontology_id=ontology_id)
        relations = relations.filter(ontology_id=ontology_id)
    entity_dates = list(entities.order_by("-created_at")
                        .values_list("created_at", flat=True)[:20000])
    relation_dates = list(relations.order_by("-created_at")
                          .values_list("created_at", flat=True)[:20000])
    return ok({
        "days": days,
        "entities": services.growth_trend(entity_dates, days),
        "relations": services.growth_trend(relation_dates, days),
    })


@endpoint(("GET",))
def stats_pagerank(request):
    """PageRank 重要性排序（有向加权，阻尼与迭代次数可调）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    _algorithm_guard(graph)
    result = analytics.pagerank(
        graph["entities"], graph["relations"],
        damping=float_arg(request, "damping", 0.85, minimum=0.0, maximum=1.0),
        iterations=int_arg(request, "iterations", 30, minimum=1, maximum=200),
        tolerance=float_arg(request, "tolerance", 1e-6, minimum=0.0,
                            maximum=1.0),
        top=int_arg(request, "top", 20, minimum=1, maximum=200))
    result["entity_count"] = len(graph["entities"])
    return ok(result)


@endpoint(("GET",))
def stats_closeness(request):
    """紧密度中心性（调和形式，孤立点不参与求和但仍计入分母）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    _algorithm_guard(graph)
    result = analytics.closeness_centrality(
        graph["entities"], graph["relations"],
        top=int_arg(request, "top", 20, minimum=1, maximum=200))
    result["entity_count"] = len(graph["entities"])
    return ok(result)


@endpoint(("GET",))
def stats_kcore(request):
    """k-core 分解（核数、核数分布与骨架节点）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    result = analytics.k_core(
        graph["entities"], graph["relations"],
        top=int_arg(request, "top", 20, minimum=1, maximum=200))
    result["entity_count"] = len(graph["entities"])
    return ok(result)


@endpoint(("GET",))
def stats_clustering(request):
    """聚类系数（局部系数 TOP、全局均值与三元闭包率）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    _algorithm_guard(graph)
    result = analytics.clustering_coefficient(
        graph["entities"], graph["relations"],
        top=int_arg(request, "top", 20, minimum=1, maximum=200))
    result["entity_count"] = len(graph["entities"])
    return ok(result)


@endpoint(("GET",))
def stats_density(request):
    """图密度 / 互惠率 / 自环（判断图谱疏密与单向关系占比）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    return ok(analytics.graph_density(graph["entities"], graph["relations"]))


@endpoint(("GET",))
def stats_similarity_clusters(request):
    """相似实体簇（阈值以上的实体聚成一簇，供批量合并使用）。"""
    graph = _graph_or_fail(request.user, int_arg(request, "ontology_id"))
    _algorithm_guard(graph)
    result = analytics.similarity_clusters(
        graph["entities"],
        threshold=float_arg(request, "threshold", 0.82, minimum=0.5,
                            maximum=1.0),
        limit=int_arg(request, "limit", 100, minimum=1, maximum=500))
    # names 只是聚类过程中的中间映射，不随响应返回，避免重复传输
    result.pop("names", None)
    return ok(result)


STATS_FAMILY_COUNT = 7 + 6
