# -*- coding: utf-8 -*-
"""可观测性 · 告警面：规则(6) + 批量求值(1) + 事件(5) + 静默(5) = 17 个接口。

真实可用的告警链路：
1. 规则创建时就把表达式解析一次并校验指标存在 —— 避免「规则建好了但
   永远不会触发」这种最难排查的配置错误；
2. 求值由 evaluate_rule 完成：持续成立 → 触发；未恢复期间不重复建事件
   （去重）；cooldown 内不再触发（抑制）；命中静默窗口则不叫醒人；
3. 条件不再成立 → 自动把未恢复事件置为 resolved（告警必须能自愈）。

事件的确认/解决走「同数据范围可操作」：值班同学经常不是规则 owner，
但必须能确认告警；而「改规则」仍然只认 owner。
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p, req_str

from observability import services
from observability.common import (
    bool_param,
    datetime_param,
    enum_param,
    event_dict,
    filter_int,
    get_rule,
    int_param,
    list_param,
    paginate,
    rule_dict,
    silence_dict,
    str_param,
    get_alert_event,
    get_silence,
)
from observability.models import (
    ALERT_SEVERITIES,
    Silence,
    AlertEvent,
    AlertRule,
    MetricDef,
    Service,
)


def _validate_expression(service, expression):
    """解析并校验表达式：指标必须存在（伪指标除外），否则规则永远不触发。"""
    meta = services.parse_expression(expression)
    name = meta["metric"]
    if name not in services.PSEUDO_METRICS:
        if not MetricDef.objects.filter(service=service, name=name).exists():
            raise ValueError(f"告警表达式引用的指标不存在: {name}")
    return meta


def _rule_row(rule):
    """规则列表行：定义 + 未恢复事件数（列表页直接显示当前是否在响）。"""
    row = rule_dict(rule)
    row["open_events"] = rule.events.filter(status__in=("firing", "suppressed")).count()
    row["firing"] = rule.events.filter(status="firing").count()
    return row


# =====================================================================
# 告警规则（6）
# =====================================================================


@endpoint(("GET",))
def alert_rule_list(request):
    """告警规则列表：按服务/严重度/启停过滤，附带未恢复事件数。"""
    qs = services.visible(AlertRule.objects.select_related("service").all(), request.user)
    qs = filter_int(qs, request, "service_id")
    severity = opt_str(request, "severity").strip()
    if severity:
        if severity not in ALERT_SEVERITIES:
            raise ValueError(f"严重度必须是 {'/'.join(ALERT_SEVERITIES)} 之一")
        qs = qs.filter(severity=severity)
    enabled = opt_str(request, "enabled").strip()
    if enabled:
        qs = qs.filter(enabled=enabled.lower() in ("1", "true", "yes", "on"))
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(expression__icontains=keyword))
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    return paginate(qs.order_by("-created_at"), request, _rule_row)


@endpoint()
def alert_rule_create(request):
    """创建告警规则：表达式合法且引用指标存在，才能落库。"""
    service = services.get_visible(Service, int_param(request, "service_id", required=True),
                                   request.user, "服务不存在")
    services.ensure_writable(service, request.user)
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("规则名称不能为空")
    expression = req_str(request, "expression", max_len=300).strip()
    _validate_expression(service, expression)
    severity = opt_str(request, "severity", "warning").strip()
    if severity not in ALERT_SEVERITIES:
        raise ValueError(f"严重度必须是 {'/'.join(ALERT_SEVERITIES)} 之一")
    obj = AlertRule.objects.create(
        owner=request.user,
        service=service,
        name=name,
        expression=expression,
        duration_seconds=int_param(request, "duration_seconds", 300,
                                   minimum=0, maximum=86400),
        severity=severity,
        channels=list_param(request, "channels", max_len=20),
        enabled=bool_param(request, "enabled", True),
        status="active",
        cooldown_seconds=int_param(request, "cooldown_seconds", 600,
                                   minimum=0, maximum=86400),
        description=opt_str(request, "description")[:300],
    )
    return ok(_rule_row(obj))


@endpoint()
def alert_rule_update(request, pk=None):
    """更新告警规则：表达式/持续时间/严重度/渠道/抑制间隔。"""
    rule = get_rule(pk or int_param(request, "id", required=True),
                    request.user, write=True)
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("规则名称不能为空")
        rule.name = name[:120]
    if p(request, "expression") is not None:
        expression = opt_str(request, "expression").strip()
        _validate_expression(rule.service, expression)
        rule.expression = expression[:300]
    if p(request, "duration_seconds") is not None:
        rule.duration_seconds = int_param(request, "duration_seconds", rule.duration_seconds,
                                          minimum=0, maximum=86400)
    if p(request, "severity") is not None:
        severity = opt_str(request, "severity", rule.severity).strip()
        if severity not in ALERT_SEVERITIES:
            raise ValueError(f"严重度必须是 {'/'.join(ALERT_SEVERITIES)} 之一")
        rule.severity = severity
    if p(request, "channels") is not None:
        rule.channels = list_param(request, "channels", max_len=20)
    if p(request, "enabled") is not None:
        rule.enabled = bool_param(request, "enabled", rule.enabled)
        rule.status = "active" if rule.enabled else "disabled"
    if p(request, "cooldown_seconds") is not None:
        rule.cooldown_seconds = int_param(request, "cooldown_seconds",
                                          rule.cooldown_seconds, minimum=0, maximum=86400)
    if p(request, "description") is not None:
        rule.description = opt_str(request, "description")[:300]
    rule.save()
    return ok(_rule_row(rule))


@endpoint()
def alert_rule_delete(request, pk):
    """删除告警规则（其事件与静默一并级联删除）。"""
    rule = get_rule(pk, request.user, write=True)
    rule.delete()
    return ok({"deleted": True, "id": pk})


@endpoint()
def alert_rule_toggle(request, pk):
    """启停告警规则：显式 enabled 优先，否则按当前值取反。"""
    rule = get_rule(pk, request.user, write=True)
    if p(request, "enabled") is None:
        enabled = not rule.enabled
    else:
        enabled = bool_param(request, "enabled", rule.enabled)
    rule.enabled = enabled
    rule.status = "active" if enabled else "disabled"
    rule.save(update_fields=["enabled", "status", "updated_at"])
    return ok({"id": rule.id, "enabled": rule.enabled, "status": rule.status})


@endpoint()
def alert_rule_test(request, pk):
    """测试求值：只算不落库，返回是否成立与当前指标值（不会产生事件）。"""
    rule = get_rule(pk, request.user, write=True)
    result = services.evaluate_rule(rule, actor=request.user, persist=False)
    meta = services.parse_expression(rule.expression)
    result["meta"] = meta
    result["persisted"] = False
    return ok(result)


@endpoint()
def alert_evaluate(request):
    """批量求值：对可见规则跑一遍巡检，返回各状态计数与明细。"""
    service_id = int_param(request, "service_id")
    service = None
    if service_id:
        service = services.get_visible(Service, service_id, request.user, "服务不存在")
    result = services.evaluate_rules(user=request.user, service=service)
    result["service_id"] = service.id if service else None
    return ok(result)


# =====================================================================
# 告警事件（5）
# =====================================================================


@endpoint(("GET",))
def alert_event_list(request):
    """告警事件列表：按状态/严重度/服务/规则/时间范围过滤。"""
    qs = services.visible(AlertEvent.objects.select_related("rule", "service").all(),
                          request.user)
    qs = filter_int(qs, request, "service_id")
    qs = filter_int(qs, request, "rule_id")
    severity = opt_str(request, "severity").strip()
    if severity:
        if severity not in ALERT_SEVERITIES:
            raise ValueError(f"严重度必须是 {'/'.join(ALERT_SEVERITIES)} 之一")
        qs = qs.filter(rule__severity=severity)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(summary__icontains=keyword) | Q(rule__name__icontains=keyword))
    since = datetime_param(request, "since")
    until = datetime_param(request, "until")
    if since:
        qs = qs.filter(started_at__gte=since)
    if until:
        qs = qs.filter(started_at__lt=until)
    return paginate(qs.order_by("-started_at"), request, event_dict)


@endpoint(("GET",))
def alert_event_detail(request, pk):
    """告警事件详情：含规则表达式与触发窗口说明。"""
    event = get_alert_event(pk, request.user)
    data = event_dict(event)
    data["rule"] = rule_dict(event.rule)
    data["silence"] = next((silence_dict(s) for s in event.rule.silences.filter(
        status="active", end_at__gte=timezone.now()).order_by("-start_at")), None)
    return ok(data)


@endpoint()
def alert_event_ack(request, pk):
    """确认告警事件（同数据范围可操作），记录确认人/时间。"""
    event = get_alert_event(pk, request.user, write=True)
    note = opt_str(request, "note")[:200]
    services.acknowledge_alert_event(event, actor=request.user, note=note)
    return ok(event_dict(event))


@endpoint()
def alert_event_resolve(request, pk):
    """手动解决告警事件（指标已恢复但下一次求值还没到时使用）。"""
    event = get_alert_event(pk, request.user, write=True)
    services.resolve_alert_event(event, note=opt_str(request, "note")[:200])
    return ok(event_dict(event))


@endpoint()
def alert_event_silence(request, pk):
    """静默事件所属规则：给规则建静默窗口并把未恢复事件标记为已抑制。"""
    event = get_alert_event(pk, request.user, write=True)
    minutes = int_param(request, "minutes", 60, minimum=1, maximum=60 * 24 * 30)
    reason = opt_str(request, "reason")[:300]
    silence = services.silence_rule(event.rule, request.user, minutes=minutes, reason=reason)
    event.refresh_from_db()
    return ok({"silence": silence_dict(silence), "event": event_dict(event)})


# =====================================================================
# 静默（5）
# =====================================================================


@endpoint(("GET",))
def silence_list(request):
    """静默列表：过期静默会被自动标记，status 过滤按标记后的值生效。"""
    qs = services.visible(Silence.objects.select_related("rule").all(), request.user)
    qs = filter_int(qs, request, "rule_id")
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.filter(status__in=("active", "expired"))
    return paginate(qs.order_by("-start_at"), request, silence_dict)


@endpoint()
def silence_create(request):
    """创建静默窗口：规则必须可见；起始时间可预约（默认现在）。"""
    rule = get_rule(int_param(request, "rule_id", required=True), request.user)
    start_at = datetime_param(request, "start_at") or timezone.now()
    end_at = datetime_param(request, "end_at")
    if end_at is None:
        end_at = start_at + timedelta(minutes=int_param(
            request, "minutes", 60, minimum=1, maximum=60 * 24 * 30))
    if end_at <= start_at:
        raise ValueError("静默结束时间必须晚于开始时间")
    silence = Silence.objects.create(
        owner=request.user,
        rule=rule,
        start_at=start_at,
        end_at=end_at,
        reason=opt_str(request, "reason")[:300],
        created_by=request.user,
        status="active" if end_at >= timezone.now() else "expired",
    )
    return ok(silence_dict(silence))


@endpoint()
def silence_update(request, pk):
    """调整静默：延长/缩短结束时间或改原因（只允许创建人）。"""
    silence = get_silence(pk, request.user, write=True)
    if silence.status == "cancelled":
        raise ValueError("已取消的静默不能修改")
    end_at = datetime_param(request, "end_at")
    if end_at is not None:
        if end_at <= silence.start_at:
            raise ValueError("静默结束时间必须晚于开始时间")
        silence.end_at = end_at
    minutes = int_param(request, "minutes")
    if minutes is not None and end_at is None:
        silence.end_at = silence.start_at + timedelta(
            minutes=max(min(int(minutes), 60 * 24 * 30), 1))
    if p(request, "reason") is not None:
        silence.reason = opt_str(request, "reason")[:300]
    if silence.end_at <= timezone.now():
        silence.status = "expired"
    silence.save()
    return ok(silence_dict(silence))


@endpoint()
def silence_cancel(request, pk):
    """取消静默：状态置 cancelled，并把仅因该静默被抑制的事件恢复为 firing。"""
    silence = get_silence(pk, request.user, write=True)
    if silence.status != "active":
        raise ValueError("只有生效中的静默可以取消")
    silence.status = "cancelled"
    silence.save(update_fields=["status", "updated_at"])
    AlertEvent.objects.filter(rule=silence.rule, status="suppressed",
                              silenced_until=silence.end_at).update(
        status="firing", silenced_until=None)
    return ok({"id": silence.id, "status": silence.status})


@endpoint()
def silence_delete(request, pk):
    """删除静默记录（历史清理用；生效中的静默请走取消）。"""
    silence = get_silence(pk, request.user, write=True)
    silence.delete()
    return ok({"deleted": True, "id": pk})


@endpoint(("GET",))
def alert_stats_by_rule(request):
    """告警规则维度统计：按严重度与状态聚合事件数量（值班交接用）。"""
    qs = services.visible(AlertEvent.objects.select_related("rule", "service").all(),
                          request.user)
    since = datetime_param(request, "since")
    until = datetime_param(request, "until")
    if since:
        qs = qs.filter(started_at__gte=since)
    if until:
        qs = qs.filter(started_at__lt=until)
    rows = []
    for row in qs.values("rule_id", "rule__name", "rule__severity", "service_id").annotate(
            total=Count("id")).order_by("-total")[:50]:
        open_count = qs.filter(rule_id=row["rule_id"],
                               status__in=("firing", "suppressed")).count()
        rows.append({
            "rule_id": row["rule_id"],
            "rule_name": row["rule__name"],
            "severity": row["rule__severity"],
            "service_id": row["service_id"],
            "total": row["total"],
            "open": open_count,
        })
    return ok({"items": rows, "count": len(rows),
               "since": services.iso(since), "until": services.iso(until)})
