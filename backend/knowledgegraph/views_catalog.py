# -*- coding: utf-8 -*-
"""knowledgegraph 目录接口：应用元信息、枚举、规模上限与 DSL 语法说明。

前端「一次拉全」的入口：状态枚举、查询类型、遍历上限都从这里取，
避免各页面各写一份中文标签，改一处漏一处；接口明细由 urls.py 通过
endpoint_index 注入，和 officesuite / contracts 的做法保持一致。
"""
from django.apps import apps

from devtools.common import endpoint, ok
from knowledgegraph import services
from knowledgegraph.common import CATALOG_ENUMS, model_labels
from knowledgegraph.models import (CANDIDATE_KINDS, CANDIDATE_STATUSES,
                                   MERGE_STATUSES, QUERY_KINDS,
                                   MAX_GRAPH_NODES, MAX_TRAVERSAL_DEPTH,
                                   GraphQuery, Ontology, Entity, Relation,
                                   EntityType, RelationType, Source,
                                   ExtractionJob, GraphSnapshot,
                                   MergeRequest)

FEATURE_LIST = [
    {"key": "ontology", "name": "本体与类型建模", "endpoints": 18},
    {"key": "entities", "name": "实体管理与实体解析", "endpoints": 11},
    {"key": "aliases", "name": "别名维护", "endpoints": 5},
    {"key": "relations", "name": "关系维护", "endpoints": 6},
    {"key": "graph", "name": "图遍历与路径查询", "endpoints": 8},
    {"key": "queries", "name": "保存查询与执行历史", "endpoints": 8},
    {"key": "tags", "name": "实体标签", "endpoints": 4},
    {"key": "sources", "name": "知识来源", "endpoints": 5},
    {"key": "extraction", "name": "规则抽取与候选审核", "endpoints": 7},
    {"key": "merge", "name": "合并申请与日志", "endpoints": 5},
    {"key": "snapshots", "name": "快照与对比", "endpoints": 6},
    {"key": "stats", "name": "图谱统计", "endpoints": 13},
]


def _scoped_counts(user=None):
    """目录里的规模计数也必须按数据范围收口。

    目录接口虽只读，但把「全平台有多少实体」暴露给普通用户没有任何
    业务价值，反而泄露平台规模；这里统一走 scope_queryset。
    """
    from core.scoping import scope_queryset

    def count(qs):
        if user is None or not getattr(user, "is_authenticated", False):
            return 0
        return scope_queryset(qs, user).count()

    return {
        "ontologies": count(Ontology.objects.all()),
        "entity_types": count(EntityType.objects.all()),
        "relation_types": count(RelationType.objects.all()),
        "entities": count(Entity.objects.all()),
        "relations": count(Relation.objects.filter(status="active")),
        "sources": count(Source.objects.all()),
        "extraction_jobs": count(ExtractionJob.objects.all()),
        "saved_queries": count(GraphQuery.objects.all()),
        "snapshots": count(GraphSnapshot.objects.all()),
        "merge_requests": count(MergeRequest.objects.all()),
    }


def catalog_data(user=None):
    """组装目录数据（不含 endpoints，endpoints 由路由包装层注入）。"""
    entity_models = [m for m in apps.get_app_config("knowledgegraph").get_models()]
    return {
        "app": "knowledgegraph",
        "name": "知识图谱",
        "version": "1.0",
        "description": "本体建模 → 实体/关系维护 → 规则抽取 → 实体解析与合并 → 图查询与统计",
        "features": FEATURE_LIST,
        "views": [
            {"key": "modeling", "name": "本体建模"},
            {"key": "entities", "name": "实体与关系"},
            {"key": "explore", "name": "图谱探索"},
            {"key": "extraction", "name": "知识抽取"},
            {"key": "insights", "name": "图谱洞察"},
        ],
        "enums": CATALOG_ENUMS,
        "candidate_kinds": list(CANDIDATE_KINDS),
        "candidate_statuses": list(CANDIDATE_STATUSES),
        "merge_statuses": list(MERGE_STATUSES),
        "query_kinds": [
            {"value": kind, "label": {
                "neighbors": "邻居查询",
                "path": "路径查询",
                "subgraph": "子图查询",
                "search": "实体搜索",
                "cypher_like": "DSL 查询",
            }.get(kind, kind)}
            for kind in QUERY_KINDS
        ],
        "limits": {
            "traversal_depth": MAX_TRAVERSAL_DEPTH,
            "graph_nodes": MAX_GRAPH_NODES,
            "page_size": 200,
        },
        "dsl": services.describe_dsl(),
        "extraction_patterns": list(services.PATTERN_CATALOG),
        "models": model_labels(),
        "model_count": len(entity_models),
        "counts": _scoped_counts(user),
        "principles": [
            "本应用不接入任何外部模型，抽取为词典与正则驱动的本地规则",
            "实体合并在事务内完成，自环与重复边自动去重并写合并日志",
            "遍历深度上限 5、单次返回节点上限 500，超限直接 400",
            "路径不存在返回空数组，属于正常业务结果而非错误",
        ],
    }


@endpoint(("GET",))
def catalog(request):
    """知识图谱目录：应用元信息、枚举、规模上限与 DSL 语法说明。"""
    return ok(catalog_data(request.user))
