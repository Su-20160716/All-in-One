# -*- coding: utf-8 -*-
"""可观测性 · 事故面（13 个接口）：CRUD + 状态机 + 时间线 + 更新记录。

状态机严格按 open → acknowledged → mitigated → resolved → postmortem 前进
（由 services.ensure_transition_allowed 校验），非法流转返回 400 而不是
静默改写 —— 事故状态是复盘时的证据，「跳过确认直接解决」会让 MTTA 变成
一个永远统计不出来的指标。

状态变更与 root_cause/action_items 的写入放在同一个 transaction.atomic()
里：解决事故时顺手补充根因是常见操作，拆成两次写会出现「已解决但根因
丢失」的半成品记录。
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p, req_str

from observability import services
from observability.common import (
    datetime_param,
    enum_param,
    get_incident,
    get_incident_update,
    incident_dict,
    incident_update_dict,
    int_param,
    list_param,
    paginate,
    str_param,
)
from observability.models import (
    INCIDENT_SEVERITIES,
    INCIDENT_STATUS,
    Incident,
    IncidentUpdate,
)


def _filter_by_service(qs, request):
    """按涉及服务过滤：services 是 JSON 列表，SQLite 不支持 JSON contains，
    因此在内存里筛出 id 再回库过滤，保持分页总数准确。"""
    service_id = int_param(request, "service_id")
    if not service_id:
        return qs, None
    matched = [row.id for row in qs.only("id", "services")
               if service_id in (row.services or [])]
    return qs.filter(id__in=matched), service_id


def _update_incident_fields(incident, request):
    """更新事故的可编辑字段（不含 status：状态只能走状态机）。"""
    if p(request, "title") is not None:
        title = opt_str(request, "title").strip()
        if not title:
            raise ValueError("事故标题不能为空")
        incident.title = title[:200]
    if p(request, "severity") is not None:
        incident.severity = enum_param(request, "severity", INCIDENT_SEVERITIES,
                                       incident.severity, "事故严重度")
    if p(request, "services") is not None:
        services_list = list_param(request, "services", max_len=50)
        for item in services_list:
            try:
                int(item)
            except (TypeError, ValueError):
                raise ValueError("参数 services 必须是服务 id 数组")
        incident.services = [int(i) for i in services_list]
    if p(request, "impact") is not None:
        incident.impact = opt_str(request, "impact")
    if p(request, "owner_name") is not None:
        incident.owner_name = opt_str(request, "owner_name")[:80]
    if p(request, "commander") is not None:
        incident.commander = opt_str(request, "commander")[:80]
    if p(request, "root_cause") is not None:
        incident.root_cause = opt_str(request, "root_cause")
    if p(request, "action_items") is not None:
        items = list_param(request, "action_items", max_len=100)
        incident.action_items = items
    if p(request, "started_at") is not None:
        started = datetime_param(request, "started_at")
        if started >= timezone.now():
            raise ValueError("事故开始时间不能晚于当前时间")
        incident.started_at = started
    return incident


# =====================================================================
# 事故（10）
# =====================================================================


@endpoint(("GET",))
def incident_list(request):
    """事故列表：按状态/严重度/涉及服务/时间范围过滤。"""
    qs = services.visible(Incident.objects.all(), request.user)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    severity = opt_str(request, "severity").strip()
    if severity:
        if severity not in INCIDENT_SEVERITIES:
            raise ValueError(f"事故严重度必须是 {'/'.join(INCIDENT_SEVERITIES)} 之一")
        qs = qs.filter(severity=severity)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(title__icontains=keyword) | Q(impact__icontains=keyword)
                       | Q(root_cause__icontains=keyword))
    qs, _service_id = _filter_by_service(qs, request)
    since = datetime_param(request, "since")
    until = datetime_param(request, "until")
    if since:
        qs = qs.filter(started_at__gte=since)
    if until:
        qs = qs.filter(started_at__lt=until)
    return paginate(qs.order_by("-started_at"), request, incident_dict)


@endpoint()
def incident_create(request):
    """创建事故：标题/严重度/涉及服务；开始时间缺省为当前。"""
    # 用 opt_str 而不是 req_str：空标题要报「事故标题不能为空」这种可操作提示，
    # 而不是通用的「缺少必填参数」。
    title = opt_str(request, "title", max_len=200).strip()
    if not title:
        raise ValueError("事故标题不能为空")
    severity = opt_str(request, "severity", "sev3").strip()
    if severity not in INCIDENT_SEVERITIES:
        raise ValueError(f"事故严重度必须是 {'/'.join(INCIDENT_SEVERITIES)} 之一")
    services_list = list_param(request, "services", max_len=50)
    parsed = []
    for item in services_list:
        try:
            parsed.append(int(item))
        except (TypeError, ValueError):
            raise ValueError("参数 services 必须是服务 id 数组")
    started = datetime_param(request, "started_at") or timezone.now()
    if started > timezone.now():
        raise ValueError("事故开始时间不能晚于当前时间")
    incident = Incident.objects.create(
        owner=request.user,
        title=title,
        severity=severity,
        status="open",
        services=parsed,
        started_at=started,
        impact=opt_str(request, "impact"),
        owner_name=str_param(request, "owner_name", max_len=80)
        or (getattr(request.user, "nickname", "") or request.user.username),
        commander=opt_str(request, "commander")[:80],
        root_cause=opt_str(request, "root_cause"),
        action_items=list_param(request, "action_items", max_len=100),
    )
    with transaction.atomic():
        IncidentUpdate.objects.create(
            owner=request.user,
            incident=incident,
            author=request.user,
            content=f"事故登记：{incident.title}",
            status_change="->open",
            at=started,
        )
    return ok(incident_dict(incident))


@endpoint(("GET",))
def incident_detail(request, pk):
    """事故详情：字段 + MTTA/MTTR + 时间线 + 更新记录数。"""
    incident = get_incident(pk, request.user)
    data = incident_dict(incident)
    data["timeline"] = services.incident_timeline(incident, limit=50)
    data["updates_count"] = incident.updates.count()
    data["duration_seconds"] = services.seconds_between(
        incident.started_at, incident.resolved_at or incident.ended_at or timezone.now())
    return ok(data)


@endpoint()
def incident_update(request, pk=None):
    """更新事故信息（不含状态；状态请走确认/缓解/解决/复盘接口）。"""
    incident = get_incident(pk or int_param(request, "id", required=True),
                            request.user, write=True)
    with transaction.atomic():
        _update_incident_fields(incident, request)
        incident.save()
    return ok(incident_dict(incident))


@endpoint()
def incident_delete(request, pk):
    """删除事故（更新记录与手册执行关联一并清理）。"""
    incident = get_incident(pk, request.user, write=True)
    incident.delete()
    return ok({"deleted": True, "id": pk})


@endpoint()
def incident_acknowledge(request, pk):
    """确认事故：open → acknowledged，记录 MTTA 起点。"""
    incident = get_incident(pk, request.user, write=True)
    services.transition_incident(incident, "acknowledged", request.user,
                                 note=opt_str(request, "note")[:500])
    return ok(incident_dict(incident))


@endpoint()
def incident_mitigate(request, pk):
    """缓解事故：acknowledged → mitigated（影响已控制但未彻底修复）。"""
    incident = get_incident(pk, request.user, write=True)
    services.transition_incident(incident, "mitigated", request.user,
                                 note=opt_str(request, "note")[:500])
    return ok(incident_dict(incident))


@endpoint()
def incident_resolve(request, pk):
    """解决事故：mitigated → resolved，落 ended_at 并写 MTTR 终点。"""
    incident = get_incident(pk, request.user, write=True)
    with transaction.atomic():
        services.transition_incident(incident, "resolved", request.user,
                                     note=opt_str(request, "note")[:500])
        if p(request, "root_cause") is not None:
            incident.root_cause = opt_str(request, "root_cause")
        if p(request, "action_items") is not None:
            incident.action_items = list_param(request, "action_items", max_len=100)
        incident.save(update_fields=["root_cause", "action_items", "updated_at"])
    return ok(incident_dict(incident))


@endpoint()
def incident_postmortem(request, pk):
    """事故复盘：resolved → postmortem，可同时提交根因与行动项。"""
    incident = get_incident(pk, request.user, write=True)
    with transaction.atomic():
        services.transition_incident(incident, "postmortem", request.user,
                                     note=opt_str(request, "note")[:500])
        if p(request, "root_cause") is not None:
            incident.root_cause = opt_str(request, "root_cause")
        if p(request, "action_items") is not None:
            incident.action_items = list_param(request, "action_items", max_len=100)
        incident.save(update_fields=["root_cause", "action_items", "updated_at"])
    return ok(incident_dict(incident))


@endpoint(("GET",))
def incident_timeline(request, pk):
    """事故时间线：创建 + 全部更新记录，按时间升序。"""
    incident = get_incident(pk, request.user)
    events = services.incident_timeline(incident,
                                        limit=int_param(request, "limit", 200,
                                                        minimum=1, maximum=500))
    return ok({"incident_id": incident.id, "items": events, "count": len(events),
               "status": incident.status})


# =====================================================================
# 事故更新记录（3）
# =====================================================================


@endpoint(("GET",))
def incident_updates(request, pk):
    """事故更新记录列表：按时间正序分页（时间线阅读顺序）。"""
    incident = get_incident(pk, request.user)
    qs = IncidentUpdate.objects.select_related("author").filter(incident=incident) \
        .order_by("at", "id")
    return paginate(qs, request, incident_update_dict)


@endpoint()
def incident_update_create(request, pk):
    """追加事故更新：内容必填，可指定发生时间（补记）。"""
    incident = get_incident(pk, request.user, write=True)
    content = opt_str(request, "content", max_len=5000).strip()
    if not content:
        raise ValueError("更新内容不能为空")
    at = datetime_param(request, "at") or timezone.now()
    if at < incident.started_at:
        raise ValueError("更新时间不能早于事故开始时间")
    update = IncidentUpdate.objects.create(
        owner=request.user,
        incident=incident,
        author=request.user,
        content=content,
        status_change=opt_str(request, "status_change")[:40],
        at=at,
    )
    return ok(incident_update_dict(update))


@endpoint()
def incident_update_delete(request, pk):
    """删除事故更新（只允许记录人；状态变更记录不因删除而回滚状态）。"""
    update = get_incident_update(pk, request.user)
    incident_id = update.incident_id
    update.delete()
    return ok({"deleted": True, "id": pk, "incident_id": incident_id})
