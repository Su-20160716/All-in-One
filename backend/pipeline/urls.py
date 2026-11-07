# -*- coding: utf-8 -*-
"""数据集成管道 · 路由：82 个接口，全部挂载在 /api/pipeline/ 下。

顺序约定：
- 静态段（import / templates / compare / scan / overview）写在 ``<int:pk>`` 之前，
  否则 "import" 会被当成主键解析；
- 列表用 ``/xxx/``，单对象动作用 ``/xxx/<pk>/动作/``，不引入 PUT/PATCH，
  与平台其它应用保持一致的「POST 动作」风格。
"""
from django.urls import path

from pipeline import views as v

urlpatterns = [
    # ---- 目录（1）----
    path("", v.catalog, name="pipeline-catalog"),

    # ---- 连接器（4）----
    path("connectors/", v.connectors, name="pipeline-connectors"),
    path("connectors/templates/", v.connector_templates, name="pipeline-connector-templates"),
    path("connectors/<int:pk>/update/", v.connector_update, name="pipeline-connector-update"),
    path("connectors/<int:pk>/delete/", v.connector_delete, name="pipeline-connector-delete"),

    # ---- 凭据引用（4）----
    path("credentials/", v.credentials, name="pipeline-credentials"),
    path("credentials/<int:pk>/update/", v.credential_update, name="pipeline-credential-update"),
    path("credentials/<int:pk>/delete/", v.credential_delete, name="pipeline-credential-delete"),
    path("credentials/<int:pk>/rotate/", v.credential_rotate, name="pipeline-credential-rotate"),

    # ---- 连接（6）----
    path("connections/", v.connections, name="pipeline-connections"),
    path("connections/<int:pk>/", v.connection_detail, name="pipeline-connection-detail"),
    path("connections/<int:pk>/update/", v.connection_update, name="pipeline-connection-update"),
    path("connections/<int:pk>/delete/", v.connection_delete, name="pipeline-connection-delete"),
    path("connections/<int:pk>/test/", v.connection_test, name="pipeline-connection-test"),
    path("connections/<int:pk>/toggle/", v.connection_toggle, name="pipeline-connection-toggle"),

    # ---- 管道（15）----
    path("pipelines/", v.pipelines, name="pipeline-pipelines"),
    path("pipelines/import/", v.pipeline_import, name="pipeline-import"),
    path("pipelines/<int:pk>/", v.pipeline_detail, name="pipeline-detail"),
    path("pipelines/<int:pk>/update/", v.pipeline_update, name="pipeline-update"),
    path("pipelines/<int:pk>/delete/", v.pipeline_delete, name="pipeline-delete"),
    path("pipelines/<int:pk>/clone/", v.pipeline_clone, name="pipeline-clone"),
    path("pipelines/<int:pk>/publish/", v.pipeline_publish, name="pipeline-publish"),
    path("pipelines/<int:pk>/pause/", v.pipeline_pause, name="pipeline-pause"),
    path("pipelines/<int:pk>/archive/", v.pipeline_archive, name="pipeline-archive"),
    path("pipelines/<int:pk>/validate/", v.pipeline_validate, name="pipeline-validate"),
    path("pipelines/<int:pk>/topology/", v.pipeline_topology, name="pipeline-topology"),
    path("pipelines/<int:pk>/export/", v.pipeline_export, name="pipeline-export"),
    path("pipelines/<int:pk>/versions/", v.pipeline_versions, name="pipeline-versions"),
    path("pipelines/<int:pk>/versions/<int:vid>/rollback/", v.pipeline_rollback,
         name="pipeline-rollback"),
    path("pipelines/<int:pk>/stats/", v.pipeline_stats, name="pipeline-stats"),

    # ---- 节点（5）----
    path("pipelines/<int:pk>/nodes/", v.pipeline_nodes, name="pipeline-nodes"),
    path("pipelines/<int:pk>/nodes/reorder/", v.pipeline_nodes_reorder,
         name="pipeline-nodes-reorder"),
    path("pipelines/<int:pk>/nodes/bulk/", v.pipeline_nodes_bulk, name="pipeline-nodes-bulk"),
    path("nodes/<int:pk>/update/", v.node_update, name="pipeline-node-update"),
    path("nodes/<int:pk>/delete/", v.node_delete, name="pipeline-node-delete"),

    # ---- 连线（3）----
    path("pipelines/<int:pk>/edges/", v.pipeline_edges, name="pipeline-edges"),
    path("pipelines/<int:pk>/edges/bulk/", v.pipeline_edges_bulk, name="pipeline-edges-bulk"),
    path("edges/<int:pk>/delete/", v.edge_delete, name="pipeline-edge-delete"),

    # ---- 字段映射（3）----
    path("pipelines/<int:pk>/mappings/", v.pipeline_mappings, name="pipeline-mappings"),
    path("mappings/<int:pk>/update/", v.mapping_update, name="pipeline-mapping-update"),
    path("mappings/<int:pk>/delete/", v.mapping_delete, name="pipeline-mapping-delete"),

    # ---- 变量（3）----
    path("pipelines/<int:pk>/variables/", v.pipeline_variables, name="pipeline-variables"),
    path("variables/<int:pk>/update/", v.variable_update, name="pipeline-variable-update"),
    path("variables/<int:pk>/delete/", v.variable_delete, name="pipeline-variable-delete"),

    # ---- 调度（6）----
    path("schedules/", v.schedules, name="pipeline-schedules"),
    path("schedules/scan/", v.schedules_scan, name="pipeline-schedules-scan"),
    path("schedules/<int:pk>/update/", v.schedule_update, name="pipeline-schedule-update"),
    path("schedules/<int:pk>/delete/", v.schedule_delete, name="pipeline-schedule-delete"),
    path("schedules/<int:pk>/toggle/", v.schedule_toggle, name="pipeline-schedule-toggle"),
    path("schedules/<int:pk>/next-run/", v.schedule_next_run, name="pipeline-schedule-next-run"),

    # ---- 运行（8）----
    path("pipelines/<int:pk>/run/", v.pipeline_run, name="pipeline-run"),
    path("runs/", v.runs, name="pipeline-runs"),
    path("runs/compare/", v.runs_compare, name="pipeline-runs-compare"),
    path("runs/<int:pk>/", v.run_detail, name="pipeline-run-detail"),
    path("runs/<int:pk>/steps/", v.run_steps, name="pipeline-run-steps"),
    path("runs/<int:pk>/logs/", v.run_logs, name="pipeline-run-logs"),
    path("runs/<int:pk>/cancel/", v.run_cancel, name="pipeline-run-cancel"),
    path("runs/<int:pk>/retry-failed/", v.run_retry_failed, name="pipeline-run-retry-failed"),

    # ---- 输出（1）----
    path("outputs/", v.outputs, name="pipeline-outputs"),

    # ---- 数据质量（5）----
    path("quality/rules/", v.quality_rules, name="pipeline-quality-rules"),
    path("quality/rules/<int:pk>/update/", v.quality_rule_update,
         name="pipeline-quality-rule-update"),
    path("quality/rules/<int:pk>/delete/", v.quality_rule_delete,
         name="pipeline-quality-rule-delete"),
    path("quality/rules/<int:pk>/test/", v.quality_rule_test,
         name="pipeline-quality-rule-test"),
    path("quality/results/", v.quality_results, name="pipeline-quality-results"),

    # ---- 血缘（4）----
    path("lineage/upstream/", v.lineage_upstream, name="pipeline-lineage-upstream"),
    path("lineage/downstream/", v.lineage_downstream, name="pipeline-lineage-downstream"),
    path("lineage/impact/", v.lineage_impact, name="pipeline-lineage-impact"),
    path("lineage/graph/", v.lineage_graph, name="pipeline-lineage-graph"),

    # ---- 数据画像（4）----
    path("profiles/", v.profiles, name="pipeline-profiles"),
    path("profiles/generate/", v.profile_generate, name="pipeline-profile-generate"),
    path("profiles/compare/", v.profiles_compare, name="pipeline-profiles-compare"),
    path("profiles/<int:pk>/", v.profile_detail, name="pipeline-profile-detail"),

    # ---- Webhook（5）----
    path("webhooks/", v.webhooks, name="pipeline-webhooks"),
    path("webhooks/<int:pk>/trigger/", v.webhook_trigger, name="pipeline-webhook-trigger"),
    path("webhooks/<int:pk>/toggle/", v.webhook_toggle, name="pipeline-webhook-toggle"),
    path("webhooks/<int:pk>/rotate/", v.webhook_rotate, name="pipeline-webhook-rotate"),
    path("webhooks/<int:pk>/delete/", v.webhook_delete, name="pipeline-webhook-delete"),

    # ---- 统计（5）----
    path("stats/overview/", v.stats_overview, name="pipeline-stats-overview"),
    path("stats/success-rate/", v.stats_success_rate, name="pipeline-stats-success-rate"),
    path("stats/latency/", v.stats_latency, name="pipeline-stats-latency"),
    path("stats/row-trend/", v.stats_row_trend, name="pipeline-stats-row-trend"),
    path("stats/failed-nodes/", v.stats_failed_nodes, name="pipeline-stats-failed-nodes"),
]

# 路由数量是契约的一部分：新增接口必须同步更新目录与前端，避免悄悄漂移
assert len(urlpatterns) == 82, f"pipeline 路由数量应为 82，当前 {len(urlpatterns)}"
