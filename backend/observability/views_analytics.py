# -*- coding: utf-8 -*-
"""可观测性 · 分析面（7 个接口）：异常检测 / 容量预测 / 噪音排行 / 预算策略 /
服务关键度 / 相似事故 / 检查趋势。

这些接口全部是「只读推导」：输入是已有的指标点、告警事件、事故记录与依赖边，
不写库，也不引入外部依赖。这样分析结果可以随时重算，不会与事实数据产生
第二份真相。
"""
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p

from observability import analytics, services
from observability.common import (
    get_incident,
    get_service,
    int_param,
    window_params,
)
from observability.models import (
    AlertEvent,
    Dependency,
    HealthCheck,
    Incident,
    Service,
    Slo,
)
from observability.views_metric import _resolve_metric


@endpoint(("GET",))
def point_anomalies(request):
    """指标异常检测：滑动中位数 + MAD 稳健 z 分数，标出尖峰与骤降。"""
    metric = _resolve_metric(request)
    since, until = window_params(request, default_hours=24)
    rows, _ = services.metric_series(metric.service, metric.name, since, until)
    detection = analytics.detect_anomalies(
        rows,
        window=int_param(request, "window", 20, minimum=analytics.MIN_BASELINE,
                         maximum=500),
        threshold=services.to_float(p(request, "threshold", analytics.DEFAULT_Z_THRESHOLD),
                                    "threshold"),
        max_items=int_param(request, "max_items", 100, minimum=1, maximum=1000),
    )
    detection.update({
        "metric_id": metric.id,
        "metric": metric.name,
        "unit": metric.unit,
        "since": services.iso(since),
        "until": services.iso(until),
        "summary": analytics.anomaly_summary(detection),
        "method": "median_mad_robust_z",
    })
    return ok(detection)


@endpoint(("GET",))
def stats_capacity_forecast(request):
    """容量预测：按线性趋势外推指标首次触及阈值的时间（含 R² 置信度）。"""
    metric = _resolve_metric(request)
    threshold = services.to_float(p(request, "threshold"), "threshold")
    since, until = window_params(request, default_hours=24 * 7)
    rows, _ = services.metric_series(metric.service, metric.name, since, until)
    result = analytics.capacity_burn_forecast(
        rows, threshold,
        horizon_days=int_param(request, "horizon_days", 30, minimum=1, maximum=365),
    )
    result.update({
        "metric_id": metric.id,
        "metric": metric.name,
        "unit": metric.unit,
        "since": services.iso(since),
        "until": services.iso(until),
        "digest": analytics.trend_digest(rows),
    })
    return ok(result)


@endpoint(("GET",))
def stats_noise_ranking(request):
    """告警噪音排行：按重复率/未处置率/静默率给规则打分并给出治理建议。"""
    days = int_param(request, "days", 7, minimum=1, maximum=90)
    since = timezone.now() - timedelta(days=days)
    events = services.visible(
        AlertEvent.objects.select_related("rule", "service").filter(started_at__gte=since),
        request.user)
    grouped = {}
    for event in events:
        rule_key = event.rule_id
        row = grouped.setdefault(rule_key, {
            "rule_id": rule_key,
            "rule_name": event.rule.name if event.rule_id else "",
            "service_id": event.service_id,
            "service_name": event.service.name if event.service_id else "",
            "severity": event.rule.severity if event.rule_id else "",
            "total": 0,
            "firing": 0,
            "resolved": 0,
            "suppressed": 0,
            "days": set(),
        })
        row["total"] += 1
        if event.status == "firing":
            row["firing"] += 1
        elif event.status == "resolved":
            row["resolved"] += 1
        elif event.status == "suppressed":
            row["suppressed"] += 1
        if event.started_at:
            row["days"].add(event.started_at.date().isoformat())
    rows = []
    for row in grouped.values():
        row["distinct_days"] = len(row.pop("days")) or 1
        rows.append(row)
    limit = int_param(request, "limit", 10, minimum=1, maximum=50)
    ranked = analytics.noise_ranking(rows, limit=limit)
    return ok({"days": days, "since": services.iso(since), "items": ranked,
               "count": len(ranked),
               "advice": "噪音分越高，越应该合并规则 / 延长持续时间 / 调整阈值"})


@endpoint(("GET",))
def slo_policy(request, pk):
    """SLO 预算策略：燃烧率 + 预算状态 → 发布决策（normal/watch/slow_down/freeze）。"""
    slo = services.get_visible(Slo, pk, request.user, "SLO 不存在")
    burn = services.burn_rate_report(slo)
    budget = services.budget_snapshot(slo)
    policy = analytics.error_budget_policy(burn, budget)
    policy.update({
        "slo_id": slo.id,
        "slo_name": slo.name,
        "target_pct": services.round4(slo.target_pct),
        "burn": burn,
    })
    return ok(policy)


@endpoint(("GET",))
def service_criticality(request, pk):
    """服务关键度：直接依赖方等级权重 + 传递影响面，归一化到 0-100。"""
    service = get_service(pk, request.user)
    qs = services.visible(Service.objects.all(), request.user)
    services_list = list(qs)
    edges = list(Dependency.objects.filter(upstream__in=qs, downstream__in=qs))
    data = analytics.service_criticality(service, services_list, edges)
    data["ranking"] = analytics.criticality_ranking(services_list, edges, limit=10)
    return ok(data)


@endpoint(("GET",))
def incident_similar(request, pk):
    """相似事故：服务重合度 + 文本 Jaccard，帮助快速判断「是不是老问题」。"""
    incident = get_incident(pk, request.user)
    days = int_param(request, "days", 180, minimum=1, maximum=730)
    since = timezone.now() - timedelta(days=days)
    qs = services.visible(Incident.objects.filter(started_at__gte=since), request.user)
    limit = int_param(request, "limit", 5, minimum=1, maximum=20)
    rows = analytics.incident_similarity(incident, list(qs.exclude(pk=incident.pk)),
                                         limit=limit)
    return ok({"incident_id": incident.id, "items": rows, "count": len(rows),
               "since": services.iso(since)})


@endpoint(("GET",))
def health_check_trend(request):
    """检查健康趋势：按桶统计可用率、平均延迟与连续失败段（排障入口）。"""
    check_id = int_param(request, "check_id", required=True)
    check = services.get_visible(HealthCheck, check_id, request.user, "健康检查不存在")
    since, until = window_params(request, default_hours=24 * 7)
    runs = list(check.runs.filter(checked_at__gte=since, checked_at__lt=until)
                .order_by("checked_at")[:5000])
    trend = analytics.health_trend(
        runs, bucket_hours=int_param(request, "bucket_hours", 1, minimum=1, maximum=168))
    trend.update({"check_id": check.id, "service_id": check.service_id,
                  "since": services.iso(since), "until": services.iso(until)})
    return ok(trend)
