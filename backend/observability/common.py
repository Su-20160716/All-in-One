# -*- coding: utf-8 -*-
"""可观测性中心 · 视图公共助手（分页 / 入参 / 序列化 / 取对象鉴权）。

为什么集中在这里
----------------
100 个接口如果各写一遍分页与取值，最容易出现三类偏差：分页参数上限
不一致、非法时间格式报 500、读接口误用写权限。集中之后：
1. 列表响应形状只有一处实现，永远是 {items,count,page,page_size}；
2. 时间/枚举/数字参数只有一处校验，错误信息统一是中文；
3. 对象的读/写权限只有 get_visible / get_writable 两个入口。

序列化函数刻意返回 dict 而不是 DRF Serializer：可观测性的读模型是
「模型字段 + 实时派生字段（健康分、达成率）」，用 Serializer 反而要写
大量 SerializerMethodField，且派生字段的入参（如 data window）无法优雅
传递。
"""
from django.db.models import Q
from django.utils import timezone

from devtools.common import ok, opt_bool, opt_num, opt_str, p
from core.scoping import is_visible, visible_user_ids

from observability import services
from observability.models import (
    ALERT_SEVERITIES,
    AlertEvent,
    AlertRule,
    Dependency,
    DashboardPanel,
    Endpoint,
    ErrorBudget,
    EscalationPolicy,
    HealthCheck,
    HealthCheckRun,
    Incident,
    IncidentUpdate,
    MetricDef,
    MetricPoint,
    OnCallSchedule,
    Runbook,
    RunbookExecution,
    Service,
    Silence,
    Slo,
    SloWindow,
)

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 200


# ---------------------------------------------------------------------------
# 分页与检索
# ---------------------------------------------------------------------------


def page_params(request):
    """分页参数：page>=1，page_size 1..200（默认 20，与全平台一致）。"""
    page = int(opt_num(request, "page", 1, integer=True, minimum=1) or 1)
    size = int(opt_num(request, "page_size", PAGE_SIZE_DEFAULT, integer=True,
                       minimum=1, maximum=PAGE_SIZE_MAX) or PAGE_SIZE_DEFAULT)
    return page, size


def paginate(qs, request, render):
    """标准列表响应：总数 + 当前页切片 + 回显分页参数。"""
    page, size = page_params(request)
    total = qs.count()
    start = (page - 1) * size
    rows = [render(obj) for obj in qs[start:start + size]]
    return ok({"items": rows, "count": total, "page": page, "page_size": size})


def apply_search(qs, request, fields, status_field="status"):
    """q 模糊搜索 + status 精确过滤（空串表示不过滤，便于「全部」）。"""
    keyword = opt_str(request, "q").strip()
    if keyword:
        cond = Q()
        for field in fields:
            cond |= Q(**{f"{field}__icontains": keyword})
        qs = qs.filter(cond)
    status = opt_str(request, "status").strip()
    if status and status_field:
        qs = qs.filter(**{status_field: status})
    return qs


def filter_int(qs, request, key, field=None, label=None):
    """按可选整型外键过滤；非法值直接中文报错。"""
    value = p(request, key)
    if value in (None, ""):
        return qs
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {label or key} 必须是整数")
    return qs.filter(**{field or key: number})


def order_param(request, allowed, default):
    """排序参数白名单：只允许真实列名，避免任意字段排序引发 500。"""
    value = opt_str(request, "order_by", default).strip() or default
    if value.lstrip("-") not in allowed:
        raise ValueError(f"排序字段必须是 {'/'.join(allowed)} 之一")
    return value


# ---------------------------------------------------------------------------
# 入参归一化
# ---------------------------------------------------------------------------


def int_param(request, key, default=None, minimum=None, maximum=None, required=False):
    """整型参数（NaN/超界统一中文提示）。"""
    if required and p(request, key) is None:
        raise ValueError(f"缺少必填参数: {key}")
    if p(request, key) is None:
        return default
    return int(opt_num(request, key, default, integer=True,
                       minimum=minimum, maximum=maximum))


def float_param(request, key, default=None, minimum=None, maximum=None, required=False):
    """浮点参数：0 与空串要区分，所以先判 None 再转。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    number = services.to_float(value, key)
    if minimum is not None and number < minimum:
        raise ValueError(f"参数 {key} 不能小于 {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"参数 {key} 不能大于 {maximum}")
    return number


def bool_param(request, key, default=False):
    """布尔参数（兼容 1/true/yes/on）。"""
    return opt_bool(request, key, default)


def str_param(request, key, default="", max_len=None, required=False):
    """字符串参数；required 时缺失报错，max_len 截断防御超长输入。"""
    value = opt_str(request, key, default or "")
    if required and not value.strip():
        raise ValueError(f"缺少必填参数: {key}")
    if max_len and len(value) > max_len:
        raise ValueError(f"参数 {key} 超过最大长度 {max_len} 字符")
    return value


def dict_param(request, key, required=False):
    """对象型参数（JSON）；空值按空字典处理，符合 PATCH 语义。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是对象")
    return value


def list_param(request, key, required=False, max_len=500):
    """数组型参数（JSON）；限制长度避免超大 JSON 拖垮请求。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return []
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    return value


def datetime_param(request, key, required=False, default=None):
    """ISO 8601 时间参数；非法格式抛中文错误。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    return services.parse_datetime(value, key)


def enum_param(request, key, allowed, default=None, label="取值"):
    """枚举参数校验：非法值直接报错，而不是把脏值写进库。"""
    value = opt_str(request, key, default or "").strip()
    if not value:
        if default is None:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    if value not in allowed:
        raise ValueError(f"{label}必须是 {'/'.join(allowed)} 之一")
    return value


def window_params(request, default_hours=24.0):
    """since/until 或 hours 的统一解析（非法格式 400）。"""
    return services.window_from(request, default_hours=default_hours)


def actor_name(user):
    """展示用姓名：昵称优先，其次用户名。"""
    return getattr(user, "nickname", "") or getattr(user, "username", "")


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def service_dict(obj):
    """服务序列化（含派生字段：端点/指标/SLO 计数）。"""
    return {
        "id": obj.id,
        "name": obj.name,
        "slug": obj.slug,
        "owner_name": obj.owner_name,
        "team": obj.team,
        "level": obj.level,
        "status": obj.status,
        "description": obj.description,
        "dependency_count": obj.dependency_count,
        "labels": obj.labels or {},
        "repository": obj.repository,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def endpoint_dict(obj):
    """服务端点序列化。"""
    return {
        "id": obj.id,
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", ""),
        "path": obj.path,
        "method": obj.method,
        "status": obj.status,
        "description": obj.description,
        "timeout_ms": obj.timeout_ms,
        "p95_ms": obj.p95_ms,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def metric_def_dict(obj):
    """指标定义序列化。"""
    return {
        "id": obj.id,
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", ""),
        "name": obj.name,
        "metric_type": obj.metric_type,
        "unit": obj.unit,
        "labels": obj.labels or {},
        "description": obj.description,
        "retention_days": obj.retention_days,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def point_dict(obj):
    """指标点序列化。"""
    return {
        "id": obj.id,
        "metric_id": obj.metric_id,
        "metric": obj.metric.name if obj.metric_id else "",
        "value": services.round4(obj.value),
        "timestamp": services.iso(obj.timestamp),
        "labels": obj.labels or {},
        "source": obj.source,
    }


def slo_dict(obj):
    """SLO 序列化（不含实时计算，快照单独接口返回）。"""
    return {
        "id": obj.id,
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", ""),
        "name": obj.name,
        "slo_type": obj.slo_type,
        "target_pct": services.round4(obj.target_pct),
        "window_days": obj.window_days,
        "latency_threshold_ms": obj.latency_threshold_ms,
        "status": obj.status,
        "owner_name": obj.owner_name,
        "metrics": obj.metrics or {},
        "description": obj.description,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def slo_window_dict(obj):
    """SLO 窗口快照序列化。"""
    return {
        "id": obj.id,
        "slo_id": obj.slo_id,
        "start_at": services.iso(obj.start_at),
        "end_at": services.iso(obj.end_at),
        "attainment_pct": services.round4(obj.attainment_pct),
        "total_requests": obj.total_requests,
        "good_requests": obj.good_requests,
        "bad_requests": obj.bad_requests,
        "burn_rate": services.round4(obj.burn_rate),
        "met": obj.met,
        "created_at": services.iso(obj.created_at),
    }


def budget_dict(obj):
    """错误预算序列化。"""
    return {
        "id": obj.id,
        "slo_id": obj.slo_id,
        "period": obj.period,
        "total_allowed": services.round4(obj.total_allowed),
        "consumed": services.round4(obj.consumed),
        "remaining": services.round4(obj.remaining),
        "consumed_rate_per_day": services.round4(obj.consumed_rate_per_day),
        "projected_exhaustion": obj.projected_exhaustion.isoformat()
        if obj.projected_exhaustion else None,
        "status": obj.status,
        "updated_at": services.iso(obj.updated_at),
    }


def rule_dict(obj, with_events=False):
    """告警规则序列化；with_events 时附带未恢复事件 id。"""
    data = {
        "id": obj.id,
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", ""),
        "name": obj.name,
        "expression": obj.expression,
        "duration_seconds": obj.duration_seconds,
        "severity": obj.severity,
        "channels": obj.channels or [],
        "enabled": obj.enabled,
        "status": obj.status,
        "cooldown_seconds": obj.cooldown_seconds,
        "last_fired_at": services.iso(obj.last_fired_at),
        "description": obj.description,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }
    if with_events:
        data["open_events"] = list(obj.events.filter(
            status__in=("firing", "suppressed")).values_list("id", flat=True))
    return data


def event_dict(obj):
    """告警事件序列化。"""
    return {
        "id": obj.id,
        "rule_id": obj.rule_id,
        "rule_name": getattr(obj.rule, "name", ""),
        "severity": getattr(obj.rule, "severity", ""),
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", ""),
        "status": obj.status,
        "started_at": services.iso(obj.started_at),
        "ended_at": services.iso(obj.ended_at),
        "duration_seconds": services.seconds_between(obj.started_at,
                                                     obj.ended_at or timezone.now()),
        "value": services.round4(obj.value),
        "summary": obj.summary,
        "owner_name": obj.owner_name,
        "silenced_until": services.iso(obj.silenced_until),
        "acknowledged_at": services.iso(obj.acknowledged_at),
        "acknowledged_by": obj.acknowledged_by,
    }


def incident_dict(obj, with_metrics=True):
    """事故序列化；with_metrics 附带 MTTA/MTTR（前端列表直接显示）。"""
    data = {
        "id": obj.id,
        "title": obj.title,
        "severity": obj.severity,
        "status": obj.status,
        "services": obj.services or [],
        "started_at": services.iso(obj.started_at),
        "ended_at": services.iso(obj.ended_at),
        "impact": obj.impact,
        "owner_name": obj.owner_name,
        "commander": obj.commander,
        "root_cause": obj.root_cause,
        "action_items": obj.action_items or [],
        "acknowledged_at": services.iso(obj.acknowledged_at),
        "mitigated_at": services.iso(obj.mitigated_at),
        "resolved_at": services.iso(obj.resolved_at),
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }
    if with_metrics:
        data["mtta_seconds"] = services.incident_mtta_seconds(obj)
        data["mttr_seconds"] = services.incident_mttr_seconds(obj)
    return data


def incident_update_dict(obj):
    """事故更新序列化。"""
    return {
        "id": obj.id,
        "incident_id": obj.incident_id,
        "author": actor_name(obj.author) if obj.author_id else "",
        "content": obj.content,
        "status_change": obj.status_change,
        "at": services.iso(obj.at),
        "created_at": services.iso(obj.created_at),
    }


def schedule_dict(obj, now=None):
    """值班表序列化；附带当前值班人（由开始时间与轮换周期推导）。"""
    members = obj.members or []
    data = {
        "id": obj.id,
        "team": obj.team,
        "name": obj.name,
        "timezone_name": obj.timezone_name,
        "rotation": obj.rotation,
        "start_at": services.iso(obj.start_at),
        "members": members,
        "active_from": services.iso(obj.active_from),
        "active_until": services.iso(obj.active_until),
        "status": obj.status,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }
    current = services_oncall_member(obj, now=now)
    data["current_member"] = current["member"] if current else ""
    data["current_shift_start"] = current["shift_start"] if current else None
    data["current_shift_end"] = current["shift_end"] if current else None
    return data


def services_oncall_member(schedule, now=None):
    """推导某个值班表在 now 时刻的值班人（含本班起止）。"""
    from observability import oncall as _oncall  # 局部导入，避免循环

    return _oncall.current_shift(schedule, now=now)


def escalation_dict(obj):
    """升级策略序列化。"""
    return {
        "id": obj.id,
        "team": obj.team,
        "level": obj.level,
        "delay_minutes": obj.delay_minutes,
        "target_name": obj.target_name,
        "target_user_id": obj.target_user_id,
        "target_username": getattr(obj.target_user, "username", "") if obj.target_user_id else "",
        "channels": obj.channels or [],
        "order": obj.order,
        "status": obj.status,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def runbook_dict(obj):
    """运行手册序列化。"""
    return {
        "id": obj.id,
        "name": obj.name,
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", "") if obj.service_id else "",
        "alert_rule_id": obj.alert_rule_id,
        "steps": obj.steps or [],
        "step_count": len(obj.steps or []),
        "owner_name": obj.owner_name,
        "version": obj.version,
        "status": obj.status,
        "executions_count": obj.executions_count,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def execution_dict(obj, with_steps=True):
    """手册执行记录序列化。"""
    data = {
        "id": obj.id,
        "runbook_id": obj.runbook_id,
        "runbook_name": getattr(obj.runbook, "name", ""),
        "incident_id": obj.incident_id,
        "actor": actor_name(obj.actor) if obj.actor_id else "",
        "status": obj.status,
        "started_at": services.iso(obj.started_at),
        "finished_at": services.iso(obj.finished_at),
        "duration_seconds": services.seconds_between(obj.started_at, obj.finished_at),
        "note": obj.note,
    }
    if with_steps:
        data["steps"] = obj.steps or []
    return data


def check_dict(obj):
    """健康检查序列化。"""
    return {
        "id": obj.id,
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", ""),
        "check_type": obj.check_type,
        "config": obj.config or {},
        "interval_seconds": obj.interval_seconds,
        "timeout_seconds": obj.timeout_seconds,
        "status": obj.status,
        "last_checked_at": services.iso(obj.last_checked_at),
        "last_error": obj.last_error,
        "consecutive_failures": obj.consecutive_failures,
        "enabled": obj.enabled,
        "weight": obj.weight,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def check_run_dict(obj):
    """健康检查执行记录序列化。"""
    return {
        "id": obj.id,
        "check_id": obj.health_check_id,
        "status": obj.status,
        "latency_ms": services.round4(obj.latency_ms),
        "error": obj.error,
        "detail": obj.detail or {},
        "checked_at": services.iso(obj.checked_at),
    }


def dependency_dict(obj):
    """依赖边序列化。"""
    return {
        "id": obj.id,
        "upstream_id": obj.upstream_id,
        "upstream": getattr(obj.upstream, "name", ""),
        "downstream_id": obj.downstream_id,
        "downstream": getattr(obj.downstream, "name", ""),
        "dep_type": obj.dep_type,
        "criticality": obj.criticality,
        "timeout_ms": obj.timeout_ms,
        "description": obj.description,
        "created_at": services.iso(obj.created_at),
    }


def panel_dict(obj):
    """仪表盘面板序列化。"""
    return {
        "id": obj.id,
        "name": obj.name,
        "service_id": obj.service_id,
        "service_name": getattr(obj.service, "name", "") if obj.service_id else "",
        "chart_type": obj.chart_type,
        "query": obj.query or {},
        "order": obj.order,
        "width": obj.width,
        "height": obj.height,
        "description": obj.description,
        "created_at": services.iso(obj.created_at),
        "updated_at": services.iso(obj.updated_at),
    }


def silence_dict(obj):
    """静默窗口序列化。"""
    return {
        "id": obj.id,
        "rule_id": obj.rule_id,
        "rule_name": getattr(obj.rule, "name", ""),
        "start_at": services.iso(obj.start_at),
        "end_at": services.iso(obj.end_at),
        "reason": obj.reason,
        "created_by": actor_name(obj.created_by) if obj.created_by_id else "",
        "status": obj.status,
        "remaining_seconds": max(int((obj.end_at - timezone.now()).total_seconds()), 0)
        if obj.status == "active" else 0,
    }


# ---------------------------------------------------------------------------
# 取对象 + 鉴权（读/写分离）
# ---------------------------------------------------------------------------


def get_service(pk, user, write=False):
    """取服务并做读/写权限校验。"""
    obj = Service.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError("服务不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_endpoint(pk, user, write=False):
    """取端点；端点写权限跟随其所属服务。"""
    obj = Endpoint.objects.select_related("service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("端点不存在")
    if write:
        services.ensure_writable(obj.service, user)
    else:
        services.ensure_visible(obj, user)
    return obj


def get_metric_def(pk, user, write=False):
    """取指标定义；写权限跟随服务。"""
    obj = MetricDef.objects.select_related("service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("指标定义不存在")
    if write:
        services.ensure_writable(obj.service, user)
    else:
        services.ensure_visible(obj, user)
    return obj


def get_slo(pk, user, write=False):
    """取 SLO；写权限只认 SLO 的 owner（SLO 是承诺，不能靠数据范围改）。"""
    obj = Slo.objects.select_related("service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("SLO 不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_rule(pk, user, write=False):
    """取告警规则。"""
    obj = AlertRule.objects.select_related("service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("告警规则不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_incident(pk, user, write=False):
    """取事故。"""
    obj = Incident.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError("事故不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_schedule(pk, user, write=False):
    """取值班表。"""
    obj = OnCallSchedule.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError("值班表不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_runbook(pk, user, write=False):
    """取运行手册。"""
    obj = Runbook.objects.select_related("service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("运行手册不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_check(pk, user, write=False):
    """取健康检查。"""
    obj = HealthCheck.objects.select_related("service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("健康检查不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_panel(pk, user, write=False):
    """取仪表盘面板。"""
    obj = DashboardPanel.objects.select_related("service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("面板不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_dependency(pk, user):
    """取依赖边（写操作要求能改上游服务）。"""
    obj = Dependency.objects.select_related("upstream", "downstream").filter(pk=pk).first()
    if obj is None:
        raise ValueError("依赖关系不存在")
    services.ensure_writable(obj.upstream, user)
    return obj


def get_silence(pk, user, write=False):
    """取静默窗口；静默的创建人可取消。"""
    obj = Silence.objects.select_related("rule").filter(pk=pk).first()
    if obj is None:
        raise ValueError("静默记录不存在")
    if write:
        if obj.created_by_id != getattr(user, "id", None) and not services.is_admin(user):
            raise ValueError("只有静默创建人可以操作该静默")
        return obj
    return services.ensure_visible(obj, user)


def get_escalation(pk, user, write=False):
    """取升级策略。"""
    obj = EscalationPolicy.objects.select_related("target_user").filter(pk=pk).first()
    if obj is None:
        raise ValueError("升级策略不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_metric_point(pk, user):
    """取指标点（只读接口用）。"""
    obj = MetricPoint.objects.select_related("metric").filter(pk=pk).first()
    if obj is None:
        raise ValueError("指标点不存在")
    return services.ensure_visible(obj, user)


def get_error_budget(pk, user):
    """取错误预算。"""
    obj = ErrorBudget.objects.select_related("slo").filter(pk=pk).first()
    if obj is None:
        raise ValueError("错误预算不存在")
    return services.ensure_visible(obj, user)


def get_slo_window(pk, user):
    """取 SLO 窗口快照。"""
    obj = SloWindow.objects.select_related("slo").filter(pk=pk).first()
    if obj is None:
        raise ValueError("SLO 窗口不存在")
    return services.ensure_visible(obj, user)


def get_alert_event(pk, user, write=False):
    """取告警事件。

    确认/解决允许「同数据范围」的用户操作：值班同学经常不是事件的
    owner，但必须能确认；这与「改规则」的写权限刻意区分开。
    """
    obj = AlertEvent.objects.select_related("rule", "service").filter(pk=pk).first()
    if obj is None:
        raise ValueError("告警事件不存在")
    if write:
        ids = visible_user_ids(user)
        if ids is not None and obj.owner_id not in ids and not services.is_admin(user):
            raise ValueError("无权操作该告警事件")
        return obj
    return services.ensure_visible(obj, user)


def get_incident_update(pk, user):
    """取事故更新记录（只允许记录人删除）。"""
    obj = IncidentUpdate.objects.select_related("incident", "author").filter(pk=pk).first()
    if obj is None:
        raise ValueError("事故更新不存在")
    if obj.author_id != getattr(user, "id", None) and not services.is_admin(user):
        raise ValueError("只有记录人可以删除该更新")
    return obj


def get_runbook_execution(pk, user):
    """取手册执行记录。"""
    obj = RunbookExecution.objects.select_related("runbook").filter(pk=pk).first()
    if obj is None:
        raise ValueError("执行记录不存在")
    return services.ensure_visible(obj, user)


def is_visible_any(obj, user):
    """兼容工具：既返回布尔，也供需要「软判定」的场景使用。"""
    if services.is_admin(user):
        return True
    ids = visible_user_ids(user)
    return ids is None or getattr(obj, "owner_id", None) in ids


def is_visible_obj(obj, user):
    """is_visible 的薄封装（保持 core.scoping 为唯一判定源）。"""
    return is_visible(obj, user)
