# -*- coding: utf-8 -*-
"""可观测性中心 · 路由（113 个接口）。

分组（括号内为接口数，合计 113）：
- 目录 catalog(1)
- 服务 service(9) 端点 endpoint(4) 依赖 dependency(4) 面板 panel(6)  = 23
- 指标 metric(11)：定义 4 + 指标点 7
- SLO slo(11)：CRUD 5 + 计算 1 + 窗口/预算/燃烧率/预测/策略 5
- 告警 alert(18)：规则 6 + 批量求值 1 + 事件 5 + 静默 5 + 规则统计 1
- 事故 incident(14)：事故 11 + 更新记录 3
- 值班 oncall(7) 升级 escalation(5)                                   = 12
- 运行手册 runbook(7) 健康检查 health(8)                              = 15
- 统计 stats(8)

路径约定：
- 列表在集合根（`services/`），写操作在 `create/` / `<pk>/update/` /
  `<pk>/delete/`，避免同路径多方法带来的前端分支；
- 动作型接口统一 `<pk>/<动作>/`（acknowledge/mitigate/resolve/postmortem/
  compute/burn-rate/...），语义与事故状态机一一对应；
- 所有路径挂在 /api/observability/ 下，列表统一 {items,count,page,page_size}。
"""
from django.urls import path

from observability import (
    views_alert,
    views_analytics,
    views_catalog,
    views_health,
    views_incident,
    views_metric,
    views_oncall,
    views_service,
    views_slo,
    views_stats,
)

urlpatterns = [
    # ---- 目录（1）----
    path("", views_catalog.catalog, name="observability-catalog"),

    # ---- 服务（9）----
    path("services/", views_service.service_list),
    path("services/create/", views_service.service_create),
    path("services/overview/", views_service.service_overview),
    path("services/graph/", views_service.service_graph),
    path("services/<int:pk>/", views_service.service_detail),
    path("services/<int:pk>/update/", views_service.service_update),
    path("services/<int:pk>/delete/", views_service.service_delete),
    path("services/<int:pk>/health/", views_service.service_health),
    path("services/<int:pk>/criticality/", views_analytics.service_criticality),

    # ---- 端点（4）----
    path("endpoints/", views_service.endpoint_list),
    path("endpoints/create/", views_service.endpoint_create),
    path("endpoints/<int:pk>/update/", views_service.endpoint_update),
    path("endpoints/<int:pk>/delete/", views_service.endpoint_delete),

    # ---- 依赖（4）----
    path("dependencies/", views_service.dependency_list),
    path("dependencies/create/", views_service.dependency_create),
    path("dependencies/impact/", views_service.dependency_impact),
    path("dependencies/<int:pk>/delete/", views_service.dependency_delete),

    # ---- 仪表盘面板（6）----
    path("panels/", views_service.panel_list),
    path("panels/create/", views_service.panel_create),
    path("panels/reorder/", views_service.panel_reorder),
    path("panels/<int:pk>/update/", views_service.panel_update),
    path("panels/<int:pk>/delete/", views_service.panel_delete),
    path("panels/<int:pk>/data/", views_service.panel_data),

    # ---- 指标定义（4）----
    path("metrics/defs/", views_metric.metric_list),
    path("metrics/defs/create/", views_metric.metric_create),
    path("metrics/defs/<int:pk>/update/", views_metric.metric_update),
    path("metrics/defs/<int:pk>/delete/", views_metric.metric_delete),

    # ---- 指标点（7）----
    path("metrics/points/report/", views_metric.point_report),
    path("metrics/points/batch/", views_metric.point_batch),
    path("metrics/points/query/", views_metric.point_query),
    path("metrics/points/percentiles/", views_metric.point_percentiles),
    path("metrics/points/latest/", views_metric.point_latest),
    path("metrics/points/labels/", views_metric.point_labels),
    path("metrics/points/anomalies/", views_analytics.point_anomalies),

    # ---- SLO（11）----
    path("slos/", views_slo.slo_list),
    path("slos/create/", views_slo.slo_create),
    path("slos/<int:pk>/", views_slo.slo_detail),
    path("slos/<int:pk>/update/", views_slo.slo_update),
    path("slos/<int:pk>/delete/", views_slo.slo_delete),
    path("slos/<int:pk>/compute/", views_slo.slo_compute),
    path("slos/<int:pk>/windows/", views_slo.slo_windows),
    path("slos/<int:pk>/budget/", views_slo.slo_budget),
    path("slos/<int:pk>/burn-rate/", views_slo.slo_burn_rate),
    path("slos/<int:pk>/forecast/", views_slo.slo_forecast),
    path("slos/<int:pk>/policy/", views_analytics.slo_policy),

    # ---- 告警规则（6）----
    path("alerts/rules/", views_alert.alert_rule_list),
    path("alerts/rules/create/", views_alert.alert_rule_create),
    path("alerts/rules/<int:pk>/update/", views_alert.alert_rule_update),
    path("alerts/rules/<int:pk>/delete/", views_alert.alert_rule_delete),
    path("alerts/rules/<int:pk>/toggle/", views_alert.alert_rule_toggle),
    path("alerts/rules/<int:pk>/test/", views_alert.alert_rule_test),
    path("alerts/evaluate/", views_alert.alert_evaluate),
    path("alerts/stats/by-rule/", views_alert.alert_stats_by_rule),

    # ---- 告警事件（5）----
    path("alerts/events/", views_alert.alert_event_list),
    path("alerts/events/<int:pk>/", views_alert.alert_event_detail),
    path("alerts/events/<int:pk>/ack/", views_alert.alert_event_ack),
    path("alerts/events/<int:pk>/resolve/", views_alert.alert_event_resolve),
    path("alerts/events/<int:pk>/silence/", views_alert.alert_event_silence),

    # ---- 静默（5）----
    path("alerts/silences/", views_alert.silence_list),
    path("alerts/silences/create/", views_alert.silence_create),
    path("alerts/silences/<int:pk>/update/", views_alert.silence_update),
    path("alerts/silences/<int:pk>/cancel/", views_alert.silence_cancel),
    path("alerts/silences/<int:pk>/delete/", views_alert.silence_delete),

    # ---- 事故（10）----
    path("incidents/", views_incident.incident_list),
    path("incidents/create/", views_incident.incident_create),
    path("incidents/<int:pk>/", views_incident.incident_detail),
    path("incidents/<int:pk>/update/", views_incident.incident_update),
    path("incidents/<int:pk>/delete/", views_incident.incident_delete),
    path("incidents/<int:pk>/acknowledge/", views_incident.incident_acknowledge),
    path("incidents/<int:pk>/mitigate/", views_incident.incident_mitigate),
    path("incidents/<int:pk>/resolve/", views_incident.incident_resolve),
    path("incidents/<int:pk>/postmortem/", views_incident.incident_postmortem),
    path("incidents/<int:pk>/timeline/", views_incident.incident_timeline),
    path("incidents/<int:pk>/similar/", views_analytics.incident_similar),

    # ---- 事故更新记录（3）----
    path("incidents/<int:pk>/updates/", views_incident.incident_updates),
    path("incidents/<int:pk>/updates/create/", views_incident.incident_update_create),
    path("incident-updates/<int:pk>/delete/", views_incident.incident_update_delete),

    # ---- 值班表（7）----
    path("oncall/schedules/", views_oncall.schedule_list),
    path("oncall/schedules/create/", views_oncall.schedule_create),
    path("oncall/schedules/<int:pk>/update/", views_oncall.schedule_update),
    path("oncall/schedules/<int:pk>/delete/", views_oncall.schedule_delete),
    path("oncall/current/", views_oncall.oncall_current),
    path("oncall/upcoming/", views_oncall.oncall_upcoming),
    path("oncall/swap/", views_oncall.oncall_swap),

    # ---- 升级策略（5）----
    path("escalations/", views_oncall.escalation_list),
    path("escalations/create/", views_oncall.escalation_create),
    path("escalations/<int:pk>/update/", views_oncall.escalation_update),
    path("escalations/<int:pk>/delete/", views_oncall.escalation_delete),
    path("escalations/check/", views_oncall.escalation_check),

    # ---- 运行手册（7）----
    path("runbooks/", views_health.runbook_list),
    path("runbooks/create/", views_health.runbook_create),
    path("runbooks/<int:pk>/update/", views_health.runbook_update),
    path("runbooks/<int:pk>/delete/", views_health.runbook_delete),
    path("runbooks/<int:pk>/execute/", views_health.runbook_execute),
    path("runbooks/<int:pk>/executions/", views_health.runbook_executions),
    path("runbook-executions/<int:pk>/", views_health.runbook_execution_detail),

    # ---- 健康检查（8）----
    path("health-checks/", views_health.health_check_list),
    path("health-checks/create/", views_health.health_check_create),
    path("health-checks/run-all/", views_health.health_check_run_all),
    path("health-checks/trend/", views_analytics.health_check_trend),
    path("health-checks/<int:pk>/update/", views_health.health_check_update),
    path("health-checks/<int:pk>/delete/", views_health.health_check_delete),
    path("health-checks/<int:pk>/run/", views_health.health_check_run),
    path("health-checks/<int:pk>/history/", views_health.health_check_history),

    # ---- 统计（8）----
    path("stats/overview/", views_stats.stats_overview),
    path("stats/mtta-mttr/", views_stats.stats_mtta_mttr),
    path("stats/alerts-top/", views_stats.stats_alerts_top),
    path("stats/incidents-trend/", views_stats.stats_incidents_trend),
    path("stats/slo-ranking/", views_stats.stats_slo_ranking),
    path("stats/incidents-recent/", views_stats.stats_incidents_recent),
    path("stats/capacity-forecast/", views_analytics.stats_capacity_forecast),
    path("stats/noise-ranking/", views_analytics.stats_noise_ranking),
]

_count = 1 + 9 + 4 + 4 + 6 + 4 + 7 + 11 + 18 + 14 + 7 + 5 + 7 + 8 + 8
assert len(urlpatterns) == 113 == _count, \
    f"observability 接口数应为 113，实际 {len(urlpatterns)}"
