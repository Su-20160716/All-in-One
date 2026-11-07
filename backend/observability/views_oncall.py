# -*- coding: utf-8 -*-
"""可观测性 · 值班面：值班表(4) + 当前/未来排班(2) + 换班(1) = 7 个接口。

再叠加升级策略（5）：团队 + 层级 + 延迟 + 目标人 + 渠道，以及「检查触发」。

排班推导全部走 observability.oncall 的纯函数（当前班次、未来 N 班、换班），
这里只做参数校验、权限与落库，保证「当前值班」与「未来排班」两个接口
不会各算一套。
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p, req_str

from observability import oncall, services
from observability.common import (
    datetime_param,
    enum_param,
    get_escalation,
    get_schedule,
    int_param,
    list_param,
    paginate,
    escalation_dict,
    schedule_dict,
    str_param,
)
from observability.models import (
    ONCALL_ROTATIONS,
    OnCallSchedule,
    EscalationPolicy,
    Incident,
    Service,
)

User = get_user_model()


# =====================================================================
# 值班表（7）
# =====================================================================


@endpoint(("GET",))
def schedule_list(request):
    """值班表列表：按团队/状态过滤，附带当前值班人。"""
    qs = services.visible(OnCallSchedule.objects.all(), request.user)
    team = opt_str(request, "team").strip()
    if team:
        qs = qs.filter(team=team)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(team__icontains=keyword))
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    return paginate(qs.order_by("team", "name"), request, schedule_dict)


@endpoint()
def schedule_create(request):
    """创建值班表：轮换周期与成员顺序决定后续所有班次。"""
    # 空白团队名要报「团队名称不能为空」，而不是通用的「缺少必填参数」
    team = opt_str(request, "team", max_len=80).strip()
    if not team:
        raise ValueError("团队名称不能为空")
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("轮值名称不能为空")
    rotation = opt_str(request, "rotation", "weekly").strip()
    if rotation not in ONCALL_ROTATIONS:
        raise ValueError(f"轮换周期必须是 {'/'.join(ONCALL_ROTATIONS)} 之一")
    members = list_param(request, "members", max_len=50)
    members = [str(m).strip() for m in members if str(m).strip()]
    start_at = datetime_param(request, "start_at") or timezone.now()
    active_from = datetime_param(request, "active_from")
    active_until = datetime_param(request, "active_until")
    if active_until and active_until <= start_at:
        raise ValueError("生效结束时间必须晚于开始时间")
    obj = OnCallSchedule.objects.create(
        owner=request.user,
        team=team,
        name=name,
        timezone_name=str_param(request, "timezone_name", "Asia/Shanghai", max_len=40),
        rotation=rotation,
        start_at=start_at,
        members=members,
        active_from=active_from or start_at,
        active_until=active_until,
        status=opt_str(request, "status", "active")[:20],
    )
    return ok(schedule_dict(obj))


@endpoint()
def schedule_update(request, pk=None):
    """更新值班表：团队/名称/周期/开始时间/成员/生效区间。"""
    schedule = get_schedule(pk or int_param(request, "id", required=True),
                            request.user, write=True)
    if p(request, "team") is not None:
        team = opt_str(request, "team").strip()
        if not team:
            raise ValueError("团队名称不能为空")
        schedule.team = team[:80]
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("轮值名称不能为空")
        schedule.name = name[:120]
    if p(request, "rotation") is not None:
        rotation = opt_str(request, "rotation", schedule.rotation).strip()
        if rotation not in ONCALL_ROTATIONS:
            raise ValueError(f"轮换周期必须是 {'/'.join(ONCALL_ROTATIONS)} 之一")
        schedule.rotation = rotation
    if p(request, "start_at") is not None:
        schedule.start_at = datetime_param(request, "start_at")
    if p(request, "members") is not None:
        members = list_param(request, "members", max_len=50)
        schedule.members = [str(m).strip() for m in members if str(m).strip()]
    if p(request, "timezone_name") is not None:
        schedule.timezone_name = opt_str(request, "timezone_name",
                                         schedule.timezone_name)[:40]
    if p(request, "active_from") is not None:
        schedule.active_from = datetime_param(request, "active_from")
    if p(request, "active_until") is not None:
        schedule.active_until = datetime_param(request, "active_until")
    if p(request, "status") is not None:
        schedule.status = opt_str(request, "status", schedule.status)[:20]
    if schedule.active_until and schedule.active_until <= schedule.start_at:
        raise ValueError("生效结束时间必须晚于开始时间")
    schedule.save()
    return ok(schedule_dict(schedule))


@endpoint()
def schedule_delete(request, pk):
    """删除值班表。"""
    schedule = get_schedule(pk, request.user, write=True)
    schedule.delete()
    return ok({"deleted": True, "id": pk})


@endpoint(("GET",))
def oncall_current(request):
    """当前值班：按团队或指定值班表返回此刻的班次与人员。"""
    now = datetime_param(request, "at") or timezone.now()
    schedule_id = int_param(request, "schedule_id")
    team = opt_str(request, "team").strip()
    if schedule_id:
        schedule = get_schedule(schedule_id, request.user)
        shift = oncall.current_shift(schedule, now=now)
        return ok({"at": services.iso(now), "items": [shift] if shift else [],
                   "count": 1 if shift else 0, "schedule_id": schedule.id,
                   "team": schedule.team})
    qs = services.visible(OnCallSchedule.objects.all(), request.user)
    if team:
        qs = qs.filter(team=team)
    items = []
    for schedule in qs.order_by("team", "name"):
        shift = oncall.current_shift(schedule, now=now)
        if shift:
            items.append(shift)
    by_team = {}
    for item in items:
        by_team.setdefault(item["team"], []).append(item["member"])
    return ok({"at": services.iso(now), "items": items, "count": len(items),
               "by_team": by_team})


@endpoint(("GET",))
def oncall_upcoming(request):
    """未来排班：未来 N 个班次（含当前班次），支持按团队汇总。"""
    count = int_param(request, "count", oncall.DEFAULT_UPCOMING, minimum=1, maximum=50)
    schedule_id = int_param(request, "schedule_id")
    team = opt_str(request, "team").strip()
    now = datetime_param(request, "at") or timezone.now()
    qs = services.visible(OnCallSchedule.objects.all(), request.user)
    if schedule_id:
        qs = qs.filter(pk=schedule_id)
    elif team:
        qs = qs.filter(team=team)
    shifts = []
    for schedule in qs.order_by("team", "name"):
        shifts.extend(oncall.next_shifts(schedule, count=count, now=now))
    shifts.sort(key=lambda row: row["shift_start"])
    return ok({"since": services.iso(now), "items": shifts, "count": len(shifts)})


@endpoint()
def oncall_swap(request):
    """换班：把指定时刻的班次换成他人，写回 members 并记录变更前后。"""
    schedule = get_schedule(int_param(request, "schedule_id", required=True),
                            request.user, write=True)
    at = datetime_param(request, "at") or timezone.now()
    to_member = req_str(request, "to_member", max_len=80).strip()
    with transaction.atomic():
        result = oncall.swap_shift(schedule, at, to_member)
    result["schedule_id"] = schedule.id
    result["schedule_name"] = schedule.name
    result["members"] = schedule.members
    return ok(result)


# =====================================================================
# 升级策略（5）
# =====================================================================


@endpoint(("GET",))
def escalation_list(request):
    """升级策略列表：按团队过滤，按 level 升序（升级顺序即阅读顺序）。"""
    qs = services.visible(EscalationPolicy.objects.select_related("target_user").all(),
                          request.user)
    team = opt_str(request, "team").strip()
    if team:
        qs = qs.filter(team=team)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(team__icontains=keyword) | Q(target_name__icontains=keyword))
    return paginate(qs.order_by("team", "level", "order"), request, escalation_dict)


@endpoint()
def escalation_create(request):
    """创建升级层级：同团队同层级唯一，目标人支持姓名或账号 id。"""
    team = req_str(request, "team", max_len=80).strip()
    if not team:
        raise ValueError("团队名称不能为空")
    level = int_param(request, "level", 1, minimum=1, maximum=20)
    if EscalationPolicy.objects.filter(team=team, level=level).exists():
        raise ValueError(f"团队 {team} 的第 {level} 级升级策略已存在")
    target_user = None
    target_user_id = int_param(request, "target_user_id")
    if target_user_id:
        target_user = User.objects.filter(pk=target_user_id).first()
        if target_user is None:
            raise ValueError("目标账号不存在")
    obj = EscalationPolicy.objects.create(
        owner=request.user,
        team=team,
        level=level,
        delay_minutes=int_param(request, "delay_minutes", 5, minimum=0, maximum=1440),
        target_name=(opt_str(request, "target_name").strip()
                     or (getattr(target_user, "nickname", "") if target_user else ""))[:80],
        target_user=target_user,
        channels=list_param(request, "channels", max_len=20),
        order=int_param(request, "order", level, minimum=0, maximum=1000),
        status=opt_str(request, "status", "active")[:20],
    )
    return ok(escalation_dict(obj))


@endpoint()
def escalation_update(request, pk=None):
    """更新升级层级：延迟/目标人/渠道/排序/状态。"""
    obj = get_escalation(pk or int_param(request, "id", required=True),
                         request.user, write=True)
    if p(request, "team") is not None:
        team = opt_str(request, "team").strip()
        if not team:
            raise ValueError("团队名称不能为空")
        obj.team = team[:80]
    if p(request, "level") is not None:
        obj.level = int_param(request, "level", obj.level, minimum=1, maximum=20)
    if p(request, "delay_minutes") is not None:
        obj.delay_minutes = int_param(request, "delay_minutes", obj.delay_minutes,
                                      minimum=0, maximum=1440)
    if p(request, "target_name") is not None:
        obj.target_name = opt_str(request, "target_name")[:80]
    if p(request, "target_user_id") is not None:
        target_user_id = int_param(request, "target_user_id")
        if target_user_id:
            target_user = User.objects.filter(pk=target_user_id).first()
            if target_user is None:
                raise ValueError("目标账号不存在")
            obj.target_user = target_user
        else:
            obj.target_user = None
    if p(request, "channels") is not None:
        obj.channels = list_param(request, "channels", max_len=20)
    if p(request, "order") is not None:
        obj.order = int_param(request, "order", obj.order, minimum=0, maximum=1000)
    if p(request, "status") is not None:
        obj.status = opt_str(request, "status", obj.status)[:20]
    if EscalationPolicy.objects.filter(team=obj.team, level=obj.level).exclude(
            pk=obj.pk).exists():
        raise ValueError(f"团队 {obj.team} 的第 {obj.level} 级升级策略已存在")
    obj.save()
    return ok(escalation_dict(obj))


@endpoint()
def escalation_delete(request, pk):
    """删除升级层级。"""
    obj = get_escalation(pk, request.user, write=True)
    obj.delete()
    return ok({"deleted": True, "id": pk})


@endpoint(("GET", "POST"))
def escalation_check(request):
    """检查升级触发：按已过分钟数推算现在应通知到第几级。

    纯查询不动状态，因此同时允许 GET（排障/巡检脚本直接查）与 POST
    （前端表单提交），避免把只读检查做成 405。
    支持直接给 incident_id：用事故开始到现在的时间差作为已过分钟数，
    这样「事故升级到谁」不需要值班同学手动算。
    """
    team = opt_str(request, "team").strip()
    incident_id = int_param(request, "incident_id")
    if incident_id:
        incident = services.get_visible(Incident, incident_id, request.user, "事故不存在")
        if not team:
            # 事故本身没有团队字段，用涉及服务的团队兜底
            service_ids = [int(i) for i in (incident.services or []) if str(i).isdigit()]
            team = (services.visible(Service.objects.filter(pk__in=service_ids),
                                     request.user)
                    .values_list("team", flat=True).first() or "")
        elapsed = int((timezone.now() - incident.started_at).total_seconds() // 60)
    else:
        elapsed = int_param(request, "elapsed_minutes", 0, minimum=0, maximum=60 * 24 * 30)
    if not team:
        raise ValueError("请指定 team 或 incident_id")
    policies = list(services.visible(EscalationPolicy.objects.filter(team=team, status="active"),
                                     request.user))
    if not policies:
        return ok({"team": team, "levels": [], "current_level": None,
                   "escalate": False, "message": "该团队未配置升级策略"})
    result = oncall.escalation_timeline(policies, elapsed)
    result["team"] = team
    result["incident_id"] = incident_id
    result["targets"] = [{"level": item["level"], "target_name": item["target_name"],
                          "channels": item["channels"]}
                         for item in result["levels"] if item["status"] == "notified"]
    return ok(result)
