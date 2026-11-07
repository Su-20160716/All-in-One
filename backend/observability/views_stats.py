# -*- coding: utf-8 -*-
"""可观测性 · 统计面（5 个接口）：总览 / MTTA-MTTR / 告警 TOP / 事故趋势 / SLO 排行。

统计口径全部复用 services 里的算法，不在视图里二次聚合。这样「首页总览
的 SLO 达成率」与「SLO 排行页的达成率」一定是同一份快照，不会出现两个
页面打架。
"""
from datetime import timedelta

from django.utils import timezone

from devtools.common import endpoint, ok, opt_str

from observability import services
from observability.common import (
    int_param,
    incident_dict,
    window_params,
)
from observability.models import (
    ALERT_SEVERITIES,
    AlertEvent,
    Incident,
    Service,
    Slo,
)


@endpoint(("GET",))
def stats_overview(request):
    """平台总览：服务健康分布、SLO 达成、告警数、事故数（一次算齐）。"""
    data = services.platform_overview(user=request.user)
    data["recent_incidents"] = services.recent_incidents_summary(
        user=request.user, days=int_param(request, "days", 30, minimum=1, maximum=365),
        limit=5)
    return ok(data)


@endpoint(("GET",))
def stats_mtta_mttr(request):
    """MTTA/MTTR：均值/中位数/最大值，按严重度分组。"""
    since, until = window_params(request, default_hours=24 * 30)
    qs = services.visible(Incident.objects.filter(started_at__gte=since,
                                                 started_at__lt=until), request.user)
    stats = services.mtta_mttr_stats(qs.order_by("started_at"))
    stats.update({
        "since": services.iso(since),
        "until": services.iso(until),
        "targets": {
            "mtta_seconds": 300,
            "mttr_seconds": 3600,
            "note": "默认目标：5 分钟确认、1 小时解决；仅作展示参照，不参与判定",
        },
    })
    stats["meets_mtta_target"] = (stats["mtta_seconds"] is not None
                                  and stats["mtta_seconds"] <= 300)
    stats["meets_mttr_target"] = (stats["mttr_seconds"] is not None
                                  and stats["mttr_seconds"] <= 3600)
    return ok(stats)


@endpoint(("GET",))
def stats_alerts_top(request):
    """告警 TOP：按规则聚合触发次数，用于定位「最吵的规则」。"""
    days = int_param(request, "days", 7, minimum=1, maximum=365)
    since = timezone.now() - timedelta(days=days)
    qs = services.visible(AlertEvent.objects.select_related("rule", "service")
                          .filter(started_at__gte=since), request.user)
    severity = opt_str(request, "severity").strip()
    if severity:
        if severity not in ALERT_SEVERITIES:
            raise ValueError(f"严重度必须是 {'/'.join(ALERT_SEVERITIES)} 之一")
        qs = qs.filter(rule__severity=severity)
    limit = int_param(request, "limit", 10, minimum=1, maximum=100)
    items = services.alert_top(qs.order_by("-started_at"), limit=limit)
    return ok({"days": days, "since": services.iso(since), "items": items,
               "count": len(items), "total_events": qs.count()})


@endpoint(("GET",))
def stats_incidents_trend(request):
    """事故趋势：按天统计新增/解决（连续日期补 0）。"""
    days = int_param(request, "days", 14, minimum=1, maximum=180)
    since = timezone.now() - timedelta(days=days + 1)
    qs = services.visible(Incident.objects.filter(started_at__gte=since), request.user)
    return ok(services.incident_trend(qs, days=days))


@endpoint(("GET",))
def stats_slo_ranking(request):
    """SLO 达成排行：未达成置顶，按达成率降序（风险优先展示）。"""
    qs = services.visible(Slo.objects.select_related("service").all(), request.user)
    service_id = int_param(request, "service_id")
    if service_id:
        services.get_visible(Service, service_id, request.user, "服务不存在")
        qs = qs.filter(service_id=service_id)
    status = opt_str(request, "status", "active").strip()
    if status:
        qs = qs.filter(status=status)
    limit = int_param(request, "limit", 20, minimum=1, maximum=200)
    result = services.slo_ranking(qs.order_by("service_id", "name")[:limit])
    return ok(result)


@endpoint(("GET",))
def stats_incidents_recent(request):
    """最近事故：解决时长与状态摘要（统计页侧栏用）。"""
    limit = int_param(request, "limit", 10, minimum=1, maximum=100)
    days = int_param(request, "days", 30, minimum=1, maximum=365)
    since = timezone.now() - timedelta(days=days)
    qs = services.visible(Incident.objects.filter(started_at__gte=since), request.user)
    rows = [incident_dict(obj) for obj in qs.order_by("-started_at")[:limit]]
    return ok({"items": rows, "count": len(rows), "since": services.iso(since)})
