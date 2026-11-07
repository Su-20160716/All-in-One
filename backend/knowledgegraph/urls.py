# -*- coding: utf-8 -*-
"""knowledgegraph 路由：知识图谱 101 个接口。

家族划分（与 views_*.py 的 *_FAMILY_COUNT 对应）：
- 本体与类型   本体 8 + 实体类型 5 + 关系类型 5 + 审计 1 = 19
- 实体与别名   实体 11 + 别名 5 = 16
- 关系         创建 / 列表 / 批量 / 详情 / 更新 / 软删除 = 6
- 图查询       邻居 / 路径 / 子图 / 搜索 / DSL 预览 / DSL 执行 / 环路 / K 短路 = 8
- 保存查询     查询 8 + 标签 4 = 12
- 知识生产     来源 5 + 抽取 10 + 合并申请 5 + 快照 6 = 26
- 统计         概览 / 度 / 分量 / 社区 / 中心性 / 类型 / 增长 +
               PageRank / 紧密度 / k-core / 聚类系数 / 密度 / 相似簇 = 13
- 目录         1
合计 = 19 + 16 + 6 + 8 + 12 + 26 + 13 + 1 = 101

另：catalog 视图会把 endpoint_index(urlpatterns) 注入 data，前端不再手写
接口清单；端点顺序遵循「具体路径在 <int:pk> 之前」，避免批量接口被主键
路由抢先匹配。
"""
from django.urls import path

from devtools.common import endpoint_index
from knowledgegraph import views_catalog as cat
from knowledgegraph import views_entity as ent
from knowledgegraph import views_graph as graph
from knowledgegraph import views_knowledge as know
from knowledgegraph import views_ontology as ont
from knowledgegraph import views_query as qry
from knowledgegraph import views_relation as rel
from knowledgegraph import views_stats as stats


def _catalog(request):
    """目录 + 接口明细（endpoints 注入 data 层，保持既有响应结构）。"""
    response = cat.catalog(request)
    try:
        inner = response.data.get("data")
        if isinstance(inner, dict):
            inner["endpoints"] = endpoint_index(urlpatterns)
    except Exception:  # noqa: BLE001 —— 目录增强失败不影响主响应
        import logging

        logging.getLogger("knowledgegraph").warning(
            "knowledgegraph catalog endpoints 导出失败", exc_info=True)
    return response


urlpatterns = [
    path("", _catalog, name="knowledgegraph-catalog"),

    # ---- 本体（8）----
    path("ontologies/create/", ont.ontology_create),
    path("ontologies/", ont.ontology_list),
    path("ontologies/<int:pk>/", ont.ontology_detail),
    path("ontologies/<int:pk>/update/", ont.ontology_update),
    path("ontologies/<int:pk>/delete/", ont.ontology_delete),
    path("ontologies/<int:pk>/publish/", ont.ontology_publish),
    path("ontologies/<int:pk>/archive/", ont.ontology_archive),
    path("ontologies/<int:pk>/versions/", ont.ontology_versions),

    # ---- 实体类型（5）----
    path("entity-types/create/", ont.entity_type_create),
    path("entity-types/", ont.entity_type_list),
    path("entity-types/<int:pk>/", ont.entity_type_detail),
    path("entity-types/<int:pk>/update/", ont.entity_type_update),
    path("entity-types/<int:pk>/delete/", ont.entity_type_delete),

    # ---- 关系类型（5）----
    path("relation-types/create/", ont.relation_type_create),
    path("relation-types/", ont.relation_type_list),
    path("relation-types/<int:pk>/", ont.relation_type_detail),
    path("relation-types/<int:pk>/update/", ont.relation_type_update),
    path("relation-types/<int:pk>/delete/", ont.relation_type_delete),

    # ---- 实体（11）----
    path("entities/create/", ent.entity_create),
    path("entities/", ent.entity_list),
    path("entities/bulk-import/", ent.entity_bulk_import),
    path("entities/merge/", ent.entity_merge),
    path("entities/search/", ent.entity_search),
    path("entities/duplicates/", ent.entity_duplicates),
    path("entities/<int:pk>/", ent.entity_detail),
    path("entities/<int:pk>/update/", ent.entity_update),
    path("entities/<int:pk>/delete/", ent.entity_delete),
    path("entities/<int:pk>/archive/", ent.entity_archive),
    path("entities/<int:pk>/split/", ent.entity_split),

    # ---- 别名（5）----
    path("aliases/create/", ent.alias_create),
    path("aliases/", ent.alias_list),
    path("aliases/batch/", ent.alias_batch),
    path("aliases/<int:pk>/update/", ent.alias_update),
    path("aliases/<int:pk>/delete/", ent.alias_delete),

    # ---- 关系（6）----
    path("relations/create/", rel.relation_create),
    path("relations/", rel.relation_list),
    path("relations/batch/", rel.relation_batch),
    path("relations/<int:pk>/", rel.relation_detail),
    path("relations/<int:pk>/update/", rel.relation_update),
    path("relations/<int:pk>/delete/", rel.relation_delete),

    # ---- 图查询（6）----
    path("graph/neighbors/", graph.graph_neighbors),
    path("graph/path/", graph.graph_path),
    path("graph/subgraph/", graph.graph_subgraph),
    path("graph/search/", graph.graph_search),
    path("graph/dsl/preview/", graph.graph_dsl_preview),
    path("graph/dsl/execute/", graph.graph_dsl_execute),
    path("graph/cycles/", graph.graph_cycles),
    path("graph/k-paths/", graph.graph_k_paths),

    # ---- 保存查询（8）----
    path("queries/create/", qry.query_create),
    path("queries/", qry.query_list),
    path("queries/history/", qry.query_history),
    path("queries/<int:pk>/", qry.query_detail),
    path("queries/<int:pk>/update/", qry.query_update),
    path("queries/<int:pk>/delete/", qry.query_delete),
    path("queries/<int:pk>/run/", qry.query_run),
    path("queries/<int:pk>/runs/", qry.query_runs),

    # ---- 标签（4）----
    path("tags/create/", qry.tag_create),
    path("tags/", qry.tag_list),
    path("tags/<int:pk>/update/", qry.tag_update),
    path("tags/<int:pk>/delete/", qry.tag_delete),

    # ---- 来源（5）----
    path("sources/create/", know.source_create),
    path("sources/", know.source_list),
    path("sources/<int:pk>/", know.source_detail),
    path("sources/<int:pk>/update/", know.source_update),
    path("sources/<int:pk>/delete/", know.source_delete),

    # ---- 抽取（10）----
    path("extraction/jobs/create/", know.extraction_job_create),
    path("extraction/jobs/", know.extraction_job_list),
    path("extraction/jobs/<int:pk>/", know.extraction_job_detail),
    path("extraction/jobs/<int:pk>/update/", know.extraction_job_update),
    path("extraction/jobs/<int:pk>/delete/", know.extraction_job_delete),
    path("extraction/jobs/<int:pk>/run/", know.extraction_job_run),
    path("extraction/jobs/<int:pk>/candidates/", know.extraction_job_candidates),
    path("extraction/candidates/", know.extraction_candidates),
    path("extraction/candidates/<int:pk>/accept/", know.extraction_candidate_accept),
    path("extraction/candidates/<int:pk>/reject/", know.extraction_candidate_reject),

    # ---- 合并申请（5）----
    path("merge-requests/create/", know.merge_request_create),
    path("merge-requests/", know.merge_request_list),
    path("merge-requests/<int:pk>/", know.merge_request_detail),
    path("merge-requests/<int:pk>/approve/", know.merge_request_approve),
    path("merge-requests/<int:pk>/reject/", know.merge_request_reject),

    # ---- 快照（6）----
    path("snapshots/create/", know.snapshot_create),
    path("snapshots/generate/", know.snapshot_generate),
    path("snapshots/", know.snapshot_list),
    path("snapshots/diff/", know.snapshot_diff),
    path("snapshots/<int:pk>/", know.snapshot_detail),
    path("snapshots/<int:pk>/delete/", know.snapshot_delete),

    # ---- 统计（7）----
    path("stats/overview/", stats.stats_overview),
    path("stats/degree/", stats.stats_degree),
    path("stats/components/", stats.stats_components),
    path("stats/communities/", stats.stats_communities),
    path("stats/centrality/", stats.stats_centrality),
    path("stats/types/", stats.stats_types),
    path("stats/growth/", stats.stats_growth),
    path("stats/pagerank/", stats.stats_pagerank),
    path("stats/closeness/", stats.stats_closeness),
    path("stats/kcore/", stats.stats_kcore),
    path("stats/clustering/", stats.stats_clustering),
    path("stats/density/", stats.stats_density),
    path("stats/similarity-clusters/", stats.stats_similarity_clusters),

    # ---- 审计（1）----
    path("audit/", ont.audit_list),
]

_count = 1 + 19 + 16 + 6 + 8 + 12 + 26 + 13
assert len(urlpatterns) == _count, \
    f"knowledgegraph 接口数应为 {_count}，实际 {len(urlpatterns)}"
