# -*- coding: utf-8 -*-
"""可观测性中心 · 目录接口（1 个）。

目录是前端的「能力说明书」：枚举、分页契约、健康评分口径、燃烧率口径、
接口清单一次返回，前端不硬编码任何状态码或路径，接入新枚举也不必改前端。
"""
from devtools.common import endpoint, ok

from observability import services
from observability.models import (
    ALERT_EVENT_STATUS,
    ALERT_EVENT_STATUS_LABELS,
    ALERT_RULE_STATUS,
    ALERT_RULE_STATUS_LABELS,
    ALERT_SEVERITIES,
    ALERT_SEVERITY_LABELS,
    CRITICALITIES,
    CRITICALITY_LABELS,
    DEPENDENCY_TYPES,
    DEPENDENCY_TYPE_LABELS,
    HEALTH_CHECK_TYPES,
    HEALTH_CHECK_TYPE_LABELS,
    HEALTH_STATUS,
    HEALTH_STATUS_LABELS,
    INCIDENT_SEVERITIES,
    INCIDENT_SEVERITY_LABELS,
    INCIDENT_STATUS,
    INCIDENT_STATUS_LABELS,
    METRIC_TYPES,
    METRIC_TYPE_LABELS,
    ONCALL_ROTATIONS,
    ONCALL_ROTATION_LABELS,
    PANEL_CHART_TYPES,
    PANEL_CHART_TYPE_LABELS,
    RUNBOOK_EXEC_STATUS,
    RUNBOOK_EXEC_STATUS_LABELS,
    RUNBOOK_STATUS,
    RUNBOOK_STATUS_LABELS,
    SERVICE_LEVELS,
    SERVICE_LEVEL_LABELS,
    SERVICE_STATUS,
    SERVICE_STATUS_LABELS,
    SILENCE_STATUS,
    SILENCE_STATUS_LABELS,
    SLO_STATUS,
    SLO_STATUS_LABELS,
    SLO_TYPES,
    SLO_TYPE_LABELS,
    ENDPOINT_STATUS,
    ENDPOINT_STATUS_LABELS,
)

# 能力清单：与 services 的 10 组真实能力一一对应
CAPABILITY_DOMAINS = [
    {"key": "service", "title": "服务目录", "items": [
        "服务 CRUD/等级/团队/标签", "端点登记与 P95 延迟", "依赖图与上下游影响分析"]},
    {"key": "metric", "title": "指标", "items": [
        "指标定义（gauge/counter/histogram）", "单条/批量上报（模拟 agent）",
        "时间范围查询 + 聚合 + 分桶降采样", "P50/P90/P95/P99 分位与最新值"]},
    {"key": "slo", "title": "SLO", "items": [
        "可用性/延迟/错误率三类目标", "窗口达成率与历史快照", "错误预算与燃尽预测",
        "多窗口燃烧率（1h/6h/3d）"]},
    {"key": "alert", "title": "告警", "items": [
        "表达式规则 + 持续时间 + 严重度", "规则启停与测试求值",
        "事件触发/恢复/去重/静默", "通知渠道与抑制间隔"]},
    {"key": "incident", "title": "事故", "items": [
        "open→ack→mitigated→resolved→postmortem 状态机", "时间线与更新记录",
        "MTTA/MTTR 统计", "根因与行动项"]},
    {"key": "oncall", "title": "值班", "items": [
        "按日/按周轮换推导当前值班", "未来排班与换班", "多级升级策略与触发检查"]},
    {"key": "runbook", "title": "运行手册", "items": [
        "步骤化处置手册", "执行记录与逐步结果", "关联告警/服务/事故"]},
    {"key": "health", "title": "健康检查", "items": [
        "http/tcp/db/custom 探活配置", "单次/批量执行", "执行历史与可用率"]},
    {"key": "dashboard", "title": "仪表盘", "items": [
        "面板 CRUD 与排序", "面板查询配置驱动取数"]},
    {"key": "stats", "title": "统计", "items": [
        "平台总览（服务/SLO/告警/事故）", "MTTA/MTTR", "告警 TOP 与事故趋势",
        "SLO 达成排行"]},
]

# 计算口径说明：页面直接展示，避免「为什么两个页面数字不一样」的争议
COMPUTE_RULES = {
    "percentile": "最近秩法：rank = ceil(p/100 * n)，取第 rank 个样本",
    "availability": "好请求 / 总请求，请求数来自 requests_total 与 errors_total",
    "latency": "延迟样本中 <= 阈值的比例",
    "error_rate": "坏请求 / 总请求；目标百分比视为可用率目标",
    "attainment": "实际达成率 >= target_pct 记为达标",
    "burn_rate": "当前错误率 / 允许错误率（100 - target_pct）",
    "burn_windows": [{"window": label, "threshold": threshold}
                     for label, _hours, threshold in services.BURN_WINDOWS],
    "budget": "总预算 = 总请求 * 允许错误率；预测按当前消耗速率线性外推",
    "health_score": "加权扣分：down=100%、degraded=35%、unknown=20%",
    "mtta": "确认时间 - 开始时间",
    "mttr": "解决时间 - 开始时间",
    "dedup": "同一规则在触发未恢复期间不重复建事件；cooldown 内不重复触发",
}


def _enum(values, labels):
    """枚举 + 中文名，前端 select 直接可用。"""
    return [{"value": value, "label": labels.get(value, value)} for value in values]


def _counts(user):
    """当前用户可见的规模统计（管理员看全量）。"""
    from observability.models import (
        AlertRule,
        DashboardPanel,
        Endpoint,
        HealthCheck,
        Incident,
        MetricDef,
        Runbook,
        Service,
        Slo,
    )

    services_qs = services.visible(Service.objects.all(), user)
    return {
        "services": services_qs.count(),
        "endpoints": services.visible(Endpoint.objects.all(), user).count(),
        "metrics": services.visible(MetricDef.objects.all(), user).count(),
        "slos": services.visible(Slo.objects.all(), user).count(),
        "alert_rules": services.visible(AlertRule.objects.all(), user).count(),
        "incidents": services.visible(Incident.objects.all(), user).count(),
        "health_checks": services.visible(HealthCheck.objects.all(), user).count(),
        "runbooks": services.visible(Runbook.objects.all(), user).count(),
        "panels": services.visible(DashboardPanel.objects.all(), user).count(),
    }


@endpoint(("GET",))
def catalog(request):
    """可观测性目录：枚举、计算口径、分页契约、接口清单与规模统计。"""
    # 延迟导入：urls 会 import 本模块，顶层导入形成循环依赖
    from devtools.common import endpoint_index
    from observability.urls import urlpatterns

    endpoints = endpoint_index(urlpatterns, exclude=("",))
    return ok({
        "app": "observability",
        "name": "可观测性中心",
        "version": "1.0",
        "description": "指标 / SLO / 告警 / 事故 / 值班 / 运行手册 / 健康检查的一体化可观测平台。",
        "capabilities": CAPABILITY_DOMAINS,
        "compute": COMPUTE_RULES,
        "pagination": {
            "page_size_default": 20,
            "page_size_max": 200,
            "response_shape": ["items", "count", "page", "page_size"],
            "filters": ["q", "status", "page", "page_size"],
        },
        "enums": {
            "service_levels": _enum(SERVICE_LEVELS, SERVICE_LEVEL_LABELS),
            "service_status": _enum(SERVICE_STATUS, SERVICE_STATUS_LABELS),
            "endpoint_status": _enum(ENDPOINT_STATUS, ENDPOINT_STATUS_LABELS),
            "metric_types": _enum(METRIC_TYPES, METRIC_TYPE_LABELS),
            "slo_types": _enum(SLO_TYPES, SLO_TYPE_LABELS),
            "slo_status": _enum(SLO_STATUS, SLO_STATUS_LABELS),
            "alert_severities": _enum(ALERT_SEVERITIES, ALERT_SEVERITY_LABELS),
            "alert_rule_status": _enum(ALERT_RULE_STATUS, ALERT_RULE_STATUS_LABELS),
            "alert_event_status": _enum(ALERT_EVENT_STATUS, ALERT_EVENT_STATUS_LABELS),
            "incident_status": _enum(INCIDENT_STATUS, INCIDENT_STATUS_LABELS),
            "incident_severities": _enum(INCIDENT_SEVERITIES, INCIDENT_SEVERITY_LABELS),
            "oncall_rotations": _enum(ONCALL_ROTATIONS, ONCALL_ROTATION_LABELS),
            "health_check_types": _enum(HEALTH_CHECK_TYPES, HEALTH_CHECK_TYPE_LABELS),
            "health_status": _enum(HEALTH_STATUS, HEALTH_STATUS_LABELS),
            "dependency_types": _enum(DEPENDENCY_TYPES, DEPENDENCY_TYPE_LABELS),
            "criticalities": _enum(CRITICALITIES, CRITICALITY_LABELS),
            "panel_chart_types": _enum(PANEL_CHART_TYPES, PANEL_CHART_TYPE_LABELS),
            "runbook_status": _enum(RUNBOOK_STATUS, RUNBOOK_STATUS_LABELS),
            "runbook_exec_status": _enum(RUNBOOK_EXEC_STATUS, RUNBOOK_EXEC_STATUS_LABELS),
            "silence_status": _enum(SILENCE_STATUS, SILENCE_STATUS_LABELS),
        },
        "counts": _counts(request.user),
        "endpoints": endpoints,
        "endpoint_count": len(endpoints),
    })
