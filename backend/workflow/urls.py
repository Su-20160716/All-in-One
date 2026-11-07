# -*- coding: utf-8 -*-
"""流程引擎 · 路由（path 平铺，共 77 个接口）。

路由分六组：目录、定义与版本、设计器、运行态、任务、监控与协作。
所有路径都以名词为根、动作为后缀，方便前端按前缀做权限与埋点分组。
catalog 接口在返回时动态注入 endpoint_index(urlpatterns)，这样目录里的
端点清单永远与真实路由一致，不需要手工维护第二份列表。
"""
from django.urls import path

from devtools.common import endpoint, endpoint_index, ok
from workflow import (views_collab, views_definition,
                      views_design, views_monitor, views_runtime)
from workflow.views_catalog import build_catalog


@endpoint(("GET",))
def catalog_with_index(request):
    """流程目录：在基础目录上动态附加真实端点清单与总数。"""
    data = build_catalog(request.user)
    endpoints = endpoint_index(urlpatterns, exclude=("catalog/",))
    data["endpoints"] = endpoints
    data["endpoint_count"] = len(endpoints)
    return ok(data)


urlpatterns = [
    # 目录
    path("catalog/", catalog_with_index, name="wf_catalog"),

    # 流程定义
    path("definitions/", views_definition.definition_list, name="wf_definition_list"),
    path("definitions/create/", views_definition.definition_create, name="wf_definition_create"),
    path("definitions/import/", views_definition.definition_import, name="wf_definition_import"),
    path("definitions/<int:pk>/", views_definition.definition_detail, name="wf_definition_detail"),
    path("definitions/<int:pk>/update/", views_definition.definition_update,
         name="wf_definition_update"),
    path("definitions/<int:pk>/delete/", views_definition.definition_delete,
         name="wf_definition_delete"),
    path("definitions/<int:pk>/publish/", views_definition.definition_publish,
         name="wf_definition_publish"),
    path("definitions/<int:pk>/disable/", views_definition.definition_disable,
         name="wf_definition_disable"),
    path("definitions/<int:pk>/validate/", views_definition.definition_validate,
         name="wf_definition_validate"),
    path("definitions/<int:pk>/clone/", views_definition.definition_clone,
         name="wf_definition_clone"),
    path("definitions/<int:pk>/export/", views_definition.definition_export,
         name="wf_definition_export"),
    path("definitions/<int:pk>/stats/", views_definition.definition_stats,
         name="wf_definition_stats"),

    # 版本
    path("definitions/<int:pk>/versions/", views_definition.version_list, name="wf_version_list"),
    path("versions/<int:pk>/", views_definition.version_detail, name="wf_version_detail"),
    path("versions/<int:pk>/rollback/", views_definition.version_rollback,
         name="wf_version_rollback"),
    path("versions/diff/", views_definition.version_diff, name="wf_version_diff"),

    # 设计器：节点
    path("definitions/<int:pk>/nodes/", views_design.node_list, name="wf_node_list"),
    path("definitions/<int:pk>/nodes/create/", views_design.node_create, name="wf_node_create"),
    path("nodes/<int:pk>/update/", views_design.node_update, name="wf_node_update"),
    path("nodes/<int:pk>/delete/", views_design.node_delete, name="wf_node_delete"),

    # 设计器：连线
    path("definitions/<int:pk>/transitions/", views_design.transition_list,
         name="wf_transition_list"),
    path("definitions/<int:pk>/transitions/create/", views_design.transition_create,
         name="wf_transition_create"),
    path("transitions/<int:pk>/update/", views_design.transition_update,
         name="wf_transition_update"),
    path("transitions/<int:pk>/delete/", views_design.transition_delete,
         name="wf_transition_delete"),

    # 设计器：整图与选项
    path("definitions/<int:pk>/graph/", views_design.graph_detail, name="wf_graph_detail"),
    path("definitions/<int:pk>/graph/save/", views_design.graph_save, name="wf_graph_save"),
    path("definitions/<int:pk>/node-options/", views_design.node_options,
         name="wf_node_options"),

    # 实例
    path("instances/", views_runtime.instance_list, name="wf_instance_list"),
    path("instances/start/", views_runtime.instance_start, name="wf_instance_start"),
    path("instances/<int:pk>/", views_runtime.instance_detail, name="wf_instance_detail"),
    path("instances/<int:pk>/timeline/", views_runtime.instance_timeline,
         name="wf_instance_timeline"),
    path("instances/<int:pk>/variables/", views_runtime.instance_variables,
         name="wf_instance_variables"),
    path("instances/<int:pk>/variables/set/", views_runtime.instance_variables_set,
         name="wf_instance_variables_set"),
    path("instances/<int:pk>/cancel/", views_runtime.instance_cancel,
         name="wf_instance_cancel"),
    path("instances/<int:pk>/terminate/", views_runtime.instance_terminate,
         name="wf_instance_terminate"),
    path("instances/<int:pk>/replay/", views_runtime.instance_replay,
         name="wf_instance_replay"),
    path("instances/<int:pk>/snapshots/", views_runtime.instance_snapshots,
         name="wf_instance_snapshots"),
    path("instances/<int:pk>/snapshots/create/", views_runtime.instance_snapshot_create,
         name="wf_instance_snapshot_create"),
    path("instances/<int:pk>/comments/", views_runtime.instance_comments,
         name="wf_instance_comments"),
    path("instances/<int:pk>/comments/create/", views_runtime.instance_comment_create,
         name="wf_instance_comment_create"),
    path("instances/<int:pk>/attachments/", views_runtime.instance_attachments,
         name="wf_instance_attachments"),
    path("instances/<int:pk>/attachments/create/", views_runtime.instance_attachment_create,
         name="wf_instance_attachment_create"),
    path("instances/<int:pk>/audit/", views_collab.audit_instance, name="wf_instance_audit"),

    # 任务
    path("tasks/", views_runtime.task_list, name="wf_task_list"),
    path("tasks/my-pending/", views_runtime.task_my_pending, name="wf_task_my_pending"),
    path("tasks/my-done/", views_runtime.task_my_done, name="wf_task_my_done"),
    path("tasks/overdue/", views_runtime.task_overdue, name="wf_task_overdue"),
    path("tasks/batch-complete/", views_runtime.task_batch_complete,
         name="wf_task_batch_complete"),
    path("tasks/<int:pk>/", views_runtime.task_detail, name="wf_task_detail"),
    path("tasks/<int:pk>/claim/", views_runtime.task_claim, name="wf_task_claim"),
    path("tasks/<int:pk>/complete/", views_runtime.task_complete, name="wf_task_complete"),
    path("tasks/<int:pk>/delegate/", views_runtime.task_delegate, name="wf_task_delegate"),
    path("tasks/<int:pk>/transfer/", views_runtime.task_transfer, name="wf_task_transfer"),

    # 监控
    path("monitor/running/", views_monitor.running_instances, name="wf_monitor_running"),
    path("monitor/sla-scan/", views_monitor.sla_scan, name="wf_monitor_sla_scan"),
    path("monitor/metrics/", views_monitor.metrics, name="wf_monitor_metrics"),
    path("monitor/status-distribution/", views_monitor.status_distribution,
         name="wf_monitor_status_distribution"),
    path("monitor/category-distribution/", views_monitor.category_distribution,
         name="wf_monitor_category_distribution"),
    path("monitor/bottlenecks/", views_monitor.bottlenecks, name="wf_monitor_bottlenecks"),
    path("monitor/trend/", views_monitor.trend, name="wf_monitor_trend"),
    path("monitor/dashboard/", views_monitor.dashboard, name="wf_monitor_dashboard"),

    # 协作：委托
    path("delegations/", views_collab.delegation_list, name="wf_delegation_list"),
    path("delegations/create/", views_collab.delegation_create, name="wf_delegation_create"),
    path("delegations/<int:pk>/revoke/", views_collab.delegation_revoke,
         name="wf_delegation_revoke"),

    # 协作：通知
    path("notifications/", views_collab.notification_list, name="wf_notification_list"),
    path("notifications/summary/", views_collab.notification_summary,
         name="wf_notification_summary"),
    path("notifications/read/", views_collab.notification_read, name="wf_notification_read"),
    path("notifications/<int:pk>/read/", views_collab.notification_read_one,
         name="wf_notification_read_one"),

    # 协作：审计与 Webhook
    path("audit/", views_collab.audit_global, name="wf_audit_global"),
    path("webhooks/", views_collab.webhook_list, name="wf_webhook_list"),
    path("webhooks/create/", views_collab.webhook_create, name="wf_webhook_create"),
    path("webhooks/<int:pk>/update/", views_collab.webhook_update, name="wf_webhook_update"),
    path("webhooks/<int:pk>/delete/", views_collab.webhook_delete, name="wf_webhook_delete"),

    # 协作：SLA 策略与表达式
    path("sla-policies/", views_collab.sla_policy_list, name="wf_sla_policy_list"),
    path("sla-policies/create/", views_collab.sla_policy_create, name="wf_sla_policy_create"),
    path("expressions/eval/", views_collab.expression_eval, name="wf_expression_eval"),
]
