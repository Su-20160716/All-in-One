# -*- coding: utf-8 -*-
"""officesuite · 人员协作面接口：duty(13) timesheet(9) training(10) recognition(6)
standup(7) okr(10) decision(7) todobox(11) = 73 个。

排班/工时/培训围绕日常执行；表彰/站会/OKR/决策/待办围绕目标与复盘。
"""
from datetime import timedelta

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

from core.scoping import is_visible, scope_queryset

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req, req_list, req_num, req_str)
from officesuite.common import flow_event, get_obj, obj_dict, parse_day, parse_dt
from officesuite.models import (DecisionRecord, DutySchedule, DutyShift,
                                DutySwapRequest, KeyResult, Objective,
                                RecognitionRecord, StandupEntry, TimesheetEntry,
                                TodoItem, TrainingEnrollment, TrainingSession)

# =====================================================================
# duty 排班（9）
# =====================================================================


@endpoint()
def duty_schedule_create(request):
    """新建排班表。"""
    s = DutySchedule.objects.create(
        owner=request.user,
        name=req_str(request, "name")[:120],
        start_date=parse_day(opt_str(request, "start_date"), "start_date"))
    return ok({"id": s.id, "name": s.name, "start_date": str(s.start_date or "")})


@endpoint(("GET",))
def duty_schedule_list(request):
    """排班表列表（含各表班次数）。"""
    qs = DutySchedule.objects.all().order_by("-id")
    items = []
    for s in qs[:100]:
        items.append({"id": s.id, "name": s.name, "start_date": str(s.start_date or ""),
                      "owner": s.owner.username, "shift_count": s.shifts.count()})
    return ok({"items": items, "count": qs.count()})


@endpoint()
def duty_schedule_delete(request, pk):
    """删除排班表（连带班次）。"""
    s = get_obj(DutySchedule, pk, request.user, write=True)
    s.delete()
    return ok({"deleted": pk})


@endpoint()
def duty_shift_add(request):
    """添加班次（同一人同日同表去重）。"""
    schedule = get_obj(DutySchedule, int(req_num(request, "schedule_id", minimum=1)), request.user)
    duty_date = parse_day(req_str(request, "duty_date"), "duty_date", allow_empty=False)
    member = req_str(request, "member_name")[:60]
    if DutyShift.objects.filter(schedule=schedule, member_name=member, duty_date=duty_date).exists():
        raise ValueError(f"{member} 在 {duty_date} 已有班次")
    sh = DutyShift.objects.create(
        owner=request.user, schedule=schedule, member_name=member,
        duty_date=duty_date, shift_name=opt_str(request, "shift_name", "白班"))
    return ok({"id": sh.id, "member": sh.member_name, "duty_date": str(sh.duty_date),
               "shift": sh.shift_name})


@endpoint(("GET",))
def duty_shift_list(request):
    """班次查询：按排班表 / 日期区间 / 成员名。"""
    qs = DutyShift.objects.all().order_by("duty_date")
    schedule_id = opt_num(request, "schedule_id")
    if schedule_id:
        qs = qs.filter(schedule_id=schedule_id)
    start = parse_day(opt_str(request, "start"), "start")
    end = parse_day(opt_str(request, "end"), "end")
    if start:
        qs = qs.filter(duty_date__gte=start)
    if end:
        qs = qs.filter(duty_date__lte=end)
    member = opt_str(request, "member")
    if member:
        qs = qs.filter(member_name__icontains=member)
    return ok({"items": [{"id": s.id, "schedule": s.schedule.name,
                          "member": s.member_name, "duty_date": str(s.duty_date),
                          "shift": s.shift_name, "swapped_to": s.swapped_to}
                         for s in qs[:200]], "count": qs.count()})


@endpoint()
def duty_shift_swap(request, pk):
    """换班：把自己的班让给他人。"""
    sh = get_obj(DutyShift, pk, request.user, write=True)
    if sh.swapped_to:
        raise ValueError("该班次已换出")
    to = req_str(request, "swap_to")[:60]
    sh.swapped_to = to
    flow_event_obj = {"schedule": sh.schedule.name, "duty_date": str(sh.duty_date),
                      "from": sh.member_name, "to": to}
    sh.save()
    return ok({"id": sh.id, "swapped_to": to, "detail": flow_event_obj})


@endpoint()
def duty_shift_delete(request, pk):
    """删除班次。"""
    sh = get_obj(DutyShift, pk, request.user, write=True)
    sh.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def duty_week(request):
    """某一周排班总览（默认本周）：7 天 x 成员。"""
    ref = parse_day(opt_str(request, "date"), "date", allow_empty=True)
    base = ref or timezone.localdate()
    monday = base - timedelta(days=base.weekday())
    qs = DutyShift.objects.filter(duty_date__gte=monday, duty_date__lt=monday + timedelta(days=7))
    grid = {}
    for sh in qs:
        grid.setdefault(str(sh.duty_date), []).append(
            {"member": sh.member_name, "shift": sh.shift_name,
             "swapped_to": sh.swapped_to or None})
    return ok({"week_start": str(monday),
               "days": [{"date": str(monday + timedelta(days=i)),
                         "weekday": "一二三四五六日"[i],
                         "shifts": grid.get(str(monday + timedelta(days=i)), [])}
                        for i in range(7)]})


@endpoint(("GET",))
def duty_my_shifts(request):
    """我的班次（按 member_name = 当前用户名匹配，含换入的班）。"""
    name = request.user.username
    qs = DutyShift.objects.filter(
        Q(member_name=name) | Q(swapped_to=name)).order_by("duty_date")
    upcoming = qs.filter(duty_date__gte=timezone.localdate())
    return ok({"items": [{"id": s.id, "duty_date": str(s.duty_date),
                          "shift": s.shift_name, "schedule": s.schedule.name,
                          "is_swapped_in": bool(s.swapped_to)} for s in qs[:100]],
               "upcoming_count": upcoming.count()})


# =====================================================================
# F683 值班换班申请（发起 → 对方确认 → 记录）
# =====================================================================


def _swap_brief(r):
    sh = r.shift
    return {
        "id": r.id, "shift_id": sh.id, "duty_date": str(sh.duty_date),
        "shift": sh.shift_name, "schedule": sh.schedule.name,
        "member": sh.member_name, "from_name": r.from_name, "to_name": r.to_name,
        "status": r.status, "remark": r.remark,
        "swapped_to": sh.swapped_to,
        "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
        "events": (r.data or {}).get("events", []),
    }


def _get_swap_request(pk, user):
    """取换班申请：发起人 / 接收人 / 管理员可见（行级权限沿用 scope + 参与方）。"""
    from core.scoping import is_visible
    r = DutySwapRequest.objects.filter(pk=pk).first()
    if not r:
        raise ValueError(f"换班申请不存在: {pk}")
    name = getattr(user, "username", "")
    if is_visible(r, user) or name in (r.from_name, r.to_name) or user.is_superuser:
        return r
    raise ValueError("无权访问该对象")


@endpoint()
def duty_swap_request_create(request):
    """发起换班申请：把我的某个班次让给 to_name，等对方确认后才生效。"""
    sh = get_obj(DutyShift, int(req_num(request, "shift_id", minimum=1)), request.user, write=True)
    if sh.swapped_to:
        raise ValueError("该班次已换出")
    if sh.member_name != request.user.username and not request.user.is_superuser:
        raise ValueError("只能对自己的班次发起换班申请")
    to = opt_str(request, "to_name", "").strip()[:60]
    if not to:
        raise ValueError("缺少 to_name（接收人）")
    if to == sh.member_name:
        raise ValueError("不能申请换给自己")
    if DutySwapRequest.objects.filter(shift=sh, status="pending").exists():
        raise ValueError("该班次已有待处理的换班申请")
    r = DutySwapRequest.objects.create(
        owner=request.user, shift=sh, from_name=sh.member_name, to_name=to,
        title=f"换班申请 · {sh.duty_date} {sh.shift_name}",
        status="pending", remark=opt_str(request, "note", "")[:500],
        data={"events": []})
    flow_event(r, "create", request.user, opt_str(request, "note"))
    r.save()
    return ok(_swap_brief(r))


@endpoint(("GET",))
def duty_swap_request_list(request):
    """换班申请记录：scope=all（默认，我发起+发给我的）/ mine / incoming。"""
    name = request.user.username
    scope_ = opt_str(request, "scope", "all")
    qs = DutySwapRequest.objects.all().order_by("-created_at")
    if scope_ == "mine":
        qs = qs.filter(from_name=name)
    elif scope_ == "incoming":
        qs = qs.filter(to_name=name)
    else:
        qs = qs.filter(Q(from_name=name) | Q(to_name=name))
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    items = [_swap_brief(r) for r in qs[:100]]
    return ok({
        "items": items, "count": qs.count(),
        "pending_incoming": qs.filter(status="pending", to_name=name).count(),
        "pending_outgoing": qs.filter(status="pending", from_name=name).count(),
    })


@endpoint()
def duty_swap_request_confirm(request, pk):
    """对方确认（action=accept，默认）或拒绝（action=reject）换班申请。"""
    r = _get_swap_request(pk, request.user)
    if r.status != "pending":
        raise ValueError(f"申请已是 {r.status} 状态，不可重复处理")
    name = request.user.username
    if r.to_name != name and not request.user.is_superuser:
        raise ValueError("只有接收人（或管理员）可以处理该换班申请")
    action = opt_str(request, "action", "accept")
    if action not in ("accept", "reject"):
        raise ValueError("action 需为 accept 或 reject")
    sh = r.shift
    if action == "reject":
        r.status = "rejected"
        flow_event(r, "reject", request.user, opt_str(request, "note"))
        r.save()
        return ok(_swap_brief(r))
    if sh.swapped_to:
        raise ValueError("该班次已被换出")
    sh.swapped_to = r.to_name
    sh.save()
    r.status = "accepted"
    flow_event(r, "accept", request.user, f"班次已换给 {r.to_name}")
    r.save()
    out = _swap_brief(r)
    out["shift"] = {"duty_date": str(sh.duty_date), "member": sh.member_name,
                    "shift": sh.shift_name, "swapped_to": sh.swapped_to}
    return ok(out)


@endpoint()
def duty_swap_request_cancel(request, pk):
    """发起人撤回待处理的换班申请。"""
    r = _get_swap_request(pk, request.user)
    if r.status != "pending":
        raise ValueError(f"申请已是 {r.status} 状态，不可撤回")
    if r.from_name != request.user.username and not request.user.is_superuser:
        raise ValueError("只能撤回自己发起的换班申请")
    r.status = "cancelled"
    flow_event(r, "cancel", request.user, opt_str(request, "note"))
    r.save()
    return ok(_swap_brief(r))


# =====================================================================
# timesheet 工时（9）
# =====================================================================


@endpoint()
def timesheet_create(request):
    """登记工时。"""
    t = TimesheetEntry.objects.create(
        owner=request.user,
        title=opt_str(request, "title") or f"{req_str(request, 'project_name') or '工时'} 记录",
        work_date=parse_day(req_str(request, "work_date"), "work_date", allow_empty=False),
        hours=req_num(request, "hours", minimum=0.1, maximum=24),
        project_name=req_str(request, "project_name")[:120],
        status="submitted",
        data={"detail": opt_str(request, "detail"), "events": []})
    flow_event(t, "submit", request.user)
    t.save()
    return ok({"id": t.id, "hours": float(t.hours), "work_date": str(t.work_date)})


@endpoint(("GET",))
def timesheet_list(request):
    """我的工时列表（日期区间/项目过滤）。"""
    qs = TimesheetEntry.objects.filter(owner=request.user).order_by("-work_date")
    start = parse_day(opt_str(request, "start"), "start")
    end = parse_day(opt_str(request, "end"), "end")
    if start:
        qs = qs.filter(work_date__gte=start)
    if end:
        qs = qs.filter(work_date__lte=end)
    project = opt_str(request, "project")
    if project:
        qs = qs.filter(project_name__icontains=project)
    return ok({"items": [obj_dict(o, extra=("work_date", "hours", "project_name")) for o in qs[:200]],
               "count": qs.count()})


@endpoint()
def timesheet_update(request, pk):
    """修改自己的工时（仅 submitted 状态）。"""
    t = get_obj(TimesheetEntry, pk, request.user, write=True)
    if t.owner_id != request.user.id:
        raise ValueError("只能修改自己的工时")
    if t.status != "submitted":
        raise ValueError("已确认的工时不可修改")
    if p(request, "hours") is not None:
        t.hours = req_num(request, "hours", minimum=0.1, maximum=24)
    if p(request, "project_name") is not None:
        t.project_name = req_str(request, "project_name")[:120]
    if p(request, "work_date") is not None:
        t.work_date = parse_day(req_str(request, "work_date"), "work_date", allow_empty=False)
    if p(request, "title") is not None:
        t.title = req_str(request, "title")[:200]
    t.save()
    return ok(obj_dict(t, extra=("work_date", "hours", "project_name")))


@endpoint()
def timesheet_delete(request, pk):
    """删除自己的工时记录。"""
    t = get_obj(TimesheetEntry, pk, request.user, write=True)
    if t.owner_id != request.user.id:
        raise ValueError("只能删除自己的工时")
    t.delete()
    return ok({"deleted": pk})


@endpoint()
def timesheet_approve(request, pk):
    """主管确认工时（数据范围可见即可确认）。"""
    t = get_obj(TimesheetEntry, pk, request.user, write=True)
    if t.status != "submitted":
        raise ValueError("该记录不在待确认状态")
    action = req_str(request, "action")
    if action not in ("approve", "reject"):
        raise ValueError("action 需为 approve 或 reject")
    t.status = "approved" if action == "approve" else "rejected"
    flow_event(t, action, request.user, opt_str(request, "note"))
    t.save()
    return ok({"id": t.id, "status": t.status})


@endpoint(("GET",))
def timesheet_week(request):
    """本周工时视图：7 天分布 + 合计。默认当前用户，可看可见范围他人。"""
    user_id = opt_num(request, "user_id") or request.user.id
    ref = parse_day(opt_str(request, "date"), "date", allow_empty=True)
    monday = (ref or timezone.localdate()) - timedelta(days=(ref or timezone.localdate()).weekday())
    qs = TimesheetEntry.objects.filter(owner_id=user_id, work_date__gte=monday,
                                       work_date__lt=monday + timedelta(days=7))
    days = {str(monday + timedelta(days=i)): 0.0 for i in range(7)}
    for t in qs:
        days[str(t.work_date)] = round(days.get(str(t.work_date), 0) + float(t.hours), 2)
    total = round(sum(days.values()), 2)
    return ok({"week_start": str(monday), "days": days, "total": total,
               "over_40": total > 40, "entry_count": qs.count()})


@endpoint(("GET",))
def timesheet_summary(request):
    """按项目汇总工时（自己或可见范围）。"""
    qs = scope_queryset(TimesheetEntry.objects.exclude(status="rejected"), request.user)
    start = parse_day(opt_str(request, "start"), "start")
    end = parse_day(opt_str(request, "end"), "end")
    if start:
        qs = qs.filter(work_date__gte=start)
    if end:
        qs = qs.filter(work_date__lte=end)
    rows = (qs.values("project_name")
            .annotate(total=Sum("hours"), entries=Count("id"), members=Count("owner", distinct=True))
            .order_by("-total"))
    grand = round(sum(float(r["total"] or 0) for r in rows), 2)
    return ok({"projects": [{"project": r["project_name"] or "（未填）",
                             "hours": float(r["total"] or 0), "entries": r["entries"],
                             "people": r["members"]} for r in rows[:50]],
               "grand_total": grand})


@endpoint(("GET",))
def timesheet_stats(request):
    """工时统计：人均/日均/待确认数。"""
    qs = TimesheetEntry.objects.exclude(status="rejected")
    agg = qs.aggregate(total=Sum("hours"), entries=Count("id"), people=Count("owner", distinct=True))
    pending = TimesheetEntry.objects.filter(status="submitted").count()
    total = float(agg["total"] or 0)
    return ok({"total_hours": total, "entries": agg["entries"],
               "people": agg["people"],
               "avg_per_person": round(total / agg["people"], 1) if agg["people"] else 0,
               "pending_review": pending})


@endpoint(("GET",))
def timesheet_export(request):
    """导出工时 CSV 文本（自己或可见范围，区间过滤）。"""
    qs = scope_queryset(TimesheetEntry.objects.all(), request.user).order_by("work_date")
    start = parse_day(opt_str(request, "start"), "start")
    end = parse_day(opt_str(request, "end"), "end")
    if start:
        qs = qs.filter(work_date__gte=start)
    if end:
        qs = qs.filter(work_date__lte=end)
    lines = ["work_date,owner,project,hours,status"]
    for t in qs[:2000]:
        lines.append(f"{t.work_date},{t.owner.username},\"{t.project_name}\",{t.hours},{t.status}")
    return ok({"csv": "\n".join(lines), "rows": len(lines) - 1})


# =====================================================================
# training 培训（10）
# =====================================================================


@endpoint()
def training_create(request):
    """创建培训。"""
    s = TrainingSession.objects.create(
        owner=request.user,
        topic=req_str(request, "topic")[:200],
        trainer=opt_str(request, "trainer"),
        start_at=parse_dt(opt_str(request, "start_at"), "start_at", allow_empty=True),
        capacity=int(req_num(request, "capacity", minimum=1, maximum=9999, default=30)))
    return ok({"id": s.id, "topic": s.topic, "capacity": s.capacity})


@endpoint(("GET",))
def training_list(request):
    """培训列表（含报名数/余位）。"""
    qs = TrainingSession.objects.all().order_by("-id")
    items = []
    for s in qs[:100]:
        enrolled = s.enrollments.count()
        items.append({"id": s.id, "topic": s.topic, "trainer": s.trainer,
                      "start_at": s.start_at.isoformat() if s.start_at else None,
                      "capacity": s.capacity, "enrolled": enrolled,
                      "left": max(s.capacity - enrolled, 0)})
    return ok({"items": items, "count": qs.count()})


@endpoint()
def training_detail(request, pk):
    """培训详情（含报名名单摘要）。"""
    s = get_obj(TrainingSession, pk, request.user)
    return ok({"id": s.id, "topic": s.topic, "trainer": s.trainer,
               "start_at": s.start_at.isoformat() if s.start_at else None,
               "capacity": s.capacity,
               "enrolled": s.enrollments.count(),
               "checked_in": s.enrollments.filter(checked_in=True).count(),
               "avg_rating": round(s.enrollments.aggregate(a=Avg("rating"))["a"] or 0, 2),
               "owner": s.owner.username})


@endpoint()
def training_update(request, pk):
    """编辑培训信息。"""
    s = get_obj(TrainingSession, pk, request.user, write=True)
    if p(request, "topic") is not None:
        s.topic = req_str(request, "topic")[:200]
    if p(request, "trainer") is not None:
        s.trainer = opt_str(request, "trainer")
    if p(request, "start_at") is not None:
        s.start_at = parse_dt(opt_str(request, "start_at"), "start_at", allow_empty=True)
    if p(request, "capacity") is not None:
        s.capacity = int(req_num(request, "capacity", minimum=1, maximum=9999))
    s.save()
    return ok({"id": s.id, "topic": s.topic, "capacity": s.capacity})


@endpoint()
def training_delete(request, pk):
    """删除培训（连带报名）。"""
    s = get_obj(TrainingSession, pk, request.user, write=True)
    s.delete()
    return ok({"deleted": pk})


@endpoint()
def training_enroll(request, pk):
    """报名培训（满员拒绝、重复拒绝；全员可报名，不受数据范围限制）。"""
    try:
        s = TrainingSession.objects.get(pk=pk)
    except TrainingSession.DoesNotExist:
        raise ValueError("培训不存在")
    if TrainingEnrollment.objects.filter(session=s, member_name=request.user.username).exists():
        raise ValueError("已报名过该培训")
    if s.enrollments.count() >= s.capacity:
        raise ValueError("名额已满")
    e = TrainingEnrollment.objects.create(session=s, member_name=request.user.username)
    return ok({"id": e.id, "session": s.topic, "member": e.member_name,
               "left": max(s.capacity - s.enrollments.count(), 0)})


@endpoint()
def training_enroll_cancel(request, pk):
    """取消报名（按报名记录 ID）。"""
    e = _get_enrollment(pk, request.user)
    session_topic = e.session.topic
    e.delete()
    return ok({"cancelled": pk, "session": session_topic})


@endpoint()
def training_checkin(request, pk):
    """签到（组织者操作某学员，或学员本人）。"""
    e = _get_enrollment(pk, request.user)
    e.checked_in = True
    e.save()
    return ok({"id": e.id, "member": e.member_name, "checked_in": True})


@endpoint()
def training_feedback(request, pk):
    """提交培训反馈与评分（1-5）。"""
    e = _get_enrollment(pk, request.user)
    if e.member_name != request.user.username:
        raise ValueError("只能提交自己的反馈")
    rating = int(req_num(request, "rating", minimum=1, maximum=5))
    e.rating = rating
    e.feedback = opt_str(request, "feedback")
    e.save()
    return ok({"id": e.id, "rating": rating})


@endpoint(("GET",))
def training_roster(request, pk):
    """培训名单：报名人、签到、评分。"""
    s = get_obj(TrainingSession, pk, request.user)
    rows = s.enrollments.order_by("created_at")
    return ok({"session": s.topic,
               "items": [{"id": e.id, "member": e.member_name, "checked_in": e.checked_in,
                          "rating": e.rating, "feedback": e.feedback} for e in rows],
               "count": rows.count()})


# =====================================================================
# recognition 表彰（6）
# =====================================================================


@endpoint()
def recognition_create(request):
    """发布表彰。"""
    r = RecognitionRecord.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        to_name=req_str(request, "to_name")[:60],
        level=opt_str(request, "level", "部门"),
        status="published",
        data={"reason": opt_str(request, "reason"), "events": []})
    flow_event(r, "publish", request.user)
    r.save()
    return ok({"id": r.id, "to_name": r.to_name, "level": r.level})


@endpoint(("GET",))
def recognition_list(request):
    """表彰列表（级别过滤）。"""
    qs = scope_queryset(RecognitionRecord.objects.all(), request.user).order_by("-created_at")
    level = opt_str(request, "level")
    if level:
        qs = qs.filter(level=level)
    return ok({"items": [obj_dict(o, extra=("to_name", "level", "likes")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def recognition_like(request, pk):
    """点赞表彰（重复点赞由前端控制，后端幂等自增）。"""
    r = get_obj(RecognitionRecord, pk, request.user)
    RecognitionRecord.objects.filter(pk=r.pk).update(likes=F("likes") + 1)
    r.refresh_from_db()
    return ok({"id": r.id, "likes": r.likes})


@endpoint()
def recognition_delete(request, pk):
    """删除表彰（发布者或超管）。"""
    r = get_obj(RecognitionRecord, pk, request.user, write=True)
    if r.owner_id != request.user.id and not request.user.is_superuser:
        raise ValueError("仅发布者可删除")
    r.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def recognition_ranking(request):
    """表彰榜：按被表彰次数与点赞加权。"""
    rows = (RecognitionRecord.objects
            .values("to_name")
            .annotate(times=Count("id"), likes=Sum("likes"))
            .order_by("-times", "-likes")[:20])
    return ok({"ranking": [{"name": r["to_name"], "times": r["times"],
                            "likes": r["likes"] or 0,
                            "score": r["times"] * 10 + (r["likes"] or 0)} for r in rows]})


@endpoint(("GET",))
def recognition_stats(request):
    """表彰统计：级别分布、本月数量。"""
    by_level = RecognitionRecord.objects.values("level").annotate(c=Count("id"))
    now = timezone.localdate()
    month_start = now.replace(day=1)
    month = RecognitionRecord.objects.filter(created_at__gte=month_start).count()
    return ok({"by_level": [{"level": b["level"], "count": b["c"]} for b in by_level],
               "this_month": month, "total": RecognitionRecord.objects.count()})


# =====================================================================
# standup 站会（7）
# =====================================================================


@endpoint()
def standup_create(request):
    """提交今日站会汇报（同人同日唯一，重复提交被拒）。"""
    day = parse_day(opt_str(request, "standup_date"), "standup_date",
                    allow_empty=True, default=timezone.localdate())
    if StandupEntry.objects.filter(owner=request.user, standup_date=day).exists():
        raise ValueError(f"{day} 的站会已提交，请走更新接口")
    s = StandupEntry.objects.create(
        owner=request.user, title=f"站会 {day}",
        standup_date=day,
        yesterday=opt_str(request, "yesterday"),
        today=opt_str(request, "today"),
        blockers=opt_str(request, "blockers"),
        status="submitted", data={"events": []})
    flow_event(s, "submit", request.user)
    s.save()
    return ok({"id": s.id, "date": str(day)})


@endpoint(("GET",))
def standup_list(request):
    """站会列表：可见范围，按日期倒序。"""
    qs = scope_queryset(StandupEntry.objects.all(), request.user).order_by("-standup_date", "-created_at")
    start = parse_day(opt_str(request, "start"), "start")
    end = parse_day(opt_str(request, "end"), "end")
    if start:
        qs = qs.filter(standup_date__gte=start)
    if end:
        qs = qs.filter(standup_date__lte=end)
    return ok({"items": [obj_dict(o, extra=("standup_date", "yesterday", "today", "blockers")) for o in qs[:100]],
               "count": qs.count()})


@endpoint(("GET",))
def standup_today(request):
    """今日站会一览：谁交了、谁没交（可见范围内）。"""
    from accounts.models import User
    today = timezone.localdate()
    entries = StandupEntry.objects.filter(standup_date=today)
    visible_ids = set(scope_queryset(StandupEntry.objects.all(), request.user)
                      .values_list("owner_id", flat=True))
    submitted = list(visible_ids & set(entries.values_list("owner_id", flat=True)))
    missing = visible_ids - set(submitted)
    missing_names = list(User.objects.filter(id__in=missing).values_list("username", flat=True)[:50])
    return ok({"date": str(today),
               "submitted_count": len(submitted),
               "missing_count": len(missing),
               "missing": missing_names,
               "items": [obj_dict(o, extra=("yesterday", "today", "blockers")) for o in entries[:100]]})


@endpoint()
def standup_update(request, pk):
    """更新自己的站会内容。"""
    s = get_obj(StandupEntry, pk, request.user, write=True)
    if s.owner_id != request.user.id:
        raise ValueError("只能更新自己的站会")
    if p(request, "yesterday") is not None:
        s.yesterday = opt_str(request, "yesterday")
    if p(request, "today") is not None:
        s.today = opt_str(request, "today")
    if p(request, "blockers") is not None:
        s.blockers = opt_str(request, "blockers")
    s.save()
    return ok(obj_dict(s, extra=("standup_date",)))


@endpoint()
def standup_delete(request, pk):
    """删除站会记录（本人或超管）。"""
    s = get_obj(StandupEntry, pk, request.user, write=True)
    if s.owner_id != request.user.id and not request.user.is_superuser:
        raise ValueError("仅本人可删除")
    s.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def standup_summary(request):
    """近 7 天站会统计：提交率与阻碍关键词。"""
    week_ago = timezone.localdate() - timedelta(days=7)
    qs = scope_queryset(StandupEntry.objects.filter(standup_date__gte=week_ago), request.user)
    days = qs.values("standup_date").annotate(c=Count("id")).order_by("standup_date")
    blockers = qs.exclude(blockers="").values_list("blockers", flat=True)
    kw = {}
    for b in blockers:
        for token in b.replace("，", " ").replace(",", " ").split():
            kw[token[:12]] = kw.get(token[:12], 0) + 1
    top_kw = sorted(kw.items(), key=lambda kv: -kv[1])[:8]
    return ok({"by_day": [{"date": str(d["standup_date"]), "count": d["c"]} for d in days],
               "blocker_keywords": [{"word": w, "count": c} for w, c in top_kw],
               "total_entries": qs.count()})


@endpoint(("GET",))
def standup_export(request):
    """导出近 7 天站会 CSV。"""
    week_ago = timezone.localdate() - timedelta(days=7)
    qs = scope_queryset(StandupEntry.objects.filter(standup_date__gte=week_ago), request.user)
    lines = ["date,owner,yesterday,today,blockers"]
    for s in qs.order_by("standup_date")[:1000]:
        esc = lambda x: '"' + (x or "").replace('"', "'") + '"'
        lines.append(f"{s.standup_date},{s.owner.username},{esc(s.yesterday)},{esc(s.today)},{esc(s.blockers)}")
    return ok({"csv": "\n".join(lines), "rows": len(lines) - 1})


# =====================================================================
# okr 目标管理（10）
# =====================================================================


def _sync_objective_progress(obj_: Objective):
    """按 KR 权重联动 O 总进度。"""
    krs = list(obj_.krs.all())
    if krs:
        weight_sum = sum(k.weight for k in krs) or 1
        obj_.progress = round(sum(k.progress * k.weight for k in krs) / weight_sum)
        obj_.save(update_fields=["progress", "updated_at"])


@endpoint()
def okr_objective_create(request):
    """创建 OKR 目标。"""
    o = Objective.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        period=opt_str(request, "period", "Q4"),
        progress=0,
        data={"description": opt_str(request, "description"), "events": []})
    return ok({"id": o.id, "title": o.title, "period": o.period})


@endpoint(("GET",))
def okr_objective_list(request):
    """目标列表（周期过滤，含 KR 数与进度）。"""
    qs = scope_queryset(Objective.objects.all(), request.user).order_by("-created_at")
    period = opt_str(request, "period")
    if period:
        qs = qs.filter(period=period)
    items = []
    for o in qs[:100]:
        d = obj_dict(o, extra=("period", "progress"))
        d["kr_count"] = o.krs.count()
        items.append(d)
    return ok({"items": items, "count": qs.count()})


@endpoint()
def okr_objective_detail(request, pk):
    """目标详情（含全部 KR）。"""
    o = get_obj(Objective, pk, request.user)
    d = obj_dict(o, extra=("period", "progress"))
    d["krs"] = [{"id": k.id, "content": k.content, "progress": k.progress,
                 "weight": k.weight} for k in o.krs.all()]
    return ok(d)


@endpoint()
def okr_objective_update(request, pk):
    """编辑目标标题/周期/描述。"""
    o = get_obj(Objective, pk, request.user, write=True)
    if p(request, "title") is not None:
        o.title = req_str(request, "title")[:200]
    if p(request, "period") is not None:
        o.period = opt_str(request, "period", o.period)
    if p(request, "description") is not None:
        o.data = {**(o.data or {}), "description": opt_str(request, "description")}
    o.save()
    return ok({"id": o.id, "title": o.title, "period": o.period})


@endpoint()
def okr_objective_delete(request, pk):
    """删除目标（连带 KR）。"""
    o = get_obj(Objective, pk, request.user, write=True)
    o.delete()
    return ok({"deleted": pk})


def _get_kr(pk, user):
    """KR 读取 + 权限：沿 Objective 的 owner 校验（KR 本身无 owner 字段）。"""
    try:
        k = KeyResult.objects.select_related("objective").get(pk=pk)
    except KeyResult.DoesNotExist:
        raise ValueError("KR 不存在")
    if not is_visible(k.objective, user):
        raise ValueError("无权操作该 KR")
    return k


def _get_enrollment(pk, user, action_label="该报名记录"):
    """报名记录读取 + 权限：本人 / 培训组织者 / 超管（Enrollment 无 owner 字段）。"""
    try:
        e = TrainingEnrollment.objects.select_related("session").get(pk=pk)
    except TrainingEnrollment.DoesNotExist:
        raise ValueError(action_label + "不存在")
    if e.member_name == user.username or e.session.owner_id == user.id or user.is_superuser:
        return e
    raise ValueError("无权操作" + action_label)


@endpoint()
def okr_kr_add(request, pk):
    """为目标添加关键结果。"""
    o = get_obj(Objective, pk, request.user)
    k = KeyResult.objects.create(
        objective=o,
        content=req_str(request, "content")[:300],
        progress=int(req_num(request, "progress", minimum=0, maximum=100, default=0)),
        weight=int(req_num(request, "weight", minimum=1, maximum=10, default=1)))
    _sync_objective_progress(o)
    return ok({"id": k.id, "content": k.content, "objective_progress": o.progress})


@endpoint()
def okr_kr_progress(request, pk):
    """更新 KR 进度并联动 O 总进度。"""
    k = _get_kr(pk, request.user)
    progress = int(req_num(request, "progress", minimum=0, maximum=100))
    k.progress = progress
    k.save(update_fields=["progress"])
    _sync_objective_progress(k.objective)
    return ok({"id": k.id, "progress": k.progress, "objective_progress": k.objective.progress})


@endpoint()
def okr_kr_delete(request, pk):
    """删除 KR。"""
    k = _get_kr(pk, request.user)
    o = k.objective
    k.delete()
    _sync_objective_progress(o)
    return ok({"deleted": pk, "objective_progress": o.progress})


@endpoint(("GET",))
def okr_overview(request):
    """周期总览：各目标进度条排行、落后目标提醒。"""
    period = opt_str(request, "period")
    qs = scope_queryset(Objective.objects.all(), request.user)
    if period:
        qs = qs.filter(period=period)
    items = [{"id": o.id, "title": o.title, "period": o.period,
              "progress": o.progress, "kr_count": o.krs.count()} for o in qs[:100]]
    items.sort(key=lambda x: x["progress"])
    return ok({"objectives": items,
               "avg_progress": round(sum(i["progress"] for i in items) / len(items)) if items else 0,
               "lagging": [i["title"] for i in items if i["progress"] < 30]})


@endpoint(("GET",))
def okr_history(request):
    """KR 变更热度：进度已 100 的 KR 列表（沿 Objective 做数据范围收口）。"""
    vis_obj = scope_queryset(Objective.objects.all(), request.user)
    done = (KeyResult.objects.filter(progress=100, objective__in=vis_obj)
            .select_related("objective").order_by("objective__period")[:100])
    return ok({"completed_krs": [{"id": k.id, "content": k.content,
                                  "objective": k.objective.title,
                                  "period": k.objective.period} for k in done],
               "count": len(done)})


# =====================================================================
# decision 决策记录（7）
# =====================================================================


@endpoint()
def decision_create(request):
    """登记决策议题。"""
    d = DecisionRecord.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        context=opt_str(request, "context"),
        options=p(request, "options") or [],
        status="open", data={"events": []})
    flow_event(d, "open", request.user)
    d.save()
    return ok({"id": d.id, "title": d.title, "status": d.status})


@endpoint(("GET",))
def decision_list(request):
    """决策列表（状态过滤）。"""
    qs = scope_queryset(DecisionRecord.objects.all(), request.user).order_by("-created_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    return ok({"items": [obj_dict(o, extra=("choice",)) | {"options": o.options} for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def decision_detail(request, pk):
    """决策详情。"""
    d = get_obj(DecisionRecord, pk, request.user)
    out = obj_dict(d, extra=("choice",))
    out["context"] = d.context
    out["options"] = d.options
    out["events"] = (d.data or {}).get("events", [])
    return ok(out)


@endpoint()
def decision_update(request, pk):
    """更新议题背景与候选方案（未定论前）。"""
    d = get_obj(DecisionRecord, pk, request.user, write=True)
    if d.status == "decided":
        raise ValueError("已定论的决策不可修改背景")
    if p(request, "context") is not None:
        d.context = opt_str(request, "context")
    if p(request, "options") is not None:
        d.options = p(request, "options") or []
    if p(request, "title") is not None:
        d.title = req_str(request, "title")[:200]
    d.save()
    return ok({"id": d.id, "title": d.title})


@endpoint()
def decision_decide(request, pk):
    """定论：从候选中选择并记录理由。"""
    d = get_obj(DecisionRecord, pk, request.user, write=True)
    if d.status != "open":
        raise ValueError("该决策已定论或关闭")
    choice = req_str(request, "choice")[:200]
    if d.options and choice not in d.options:
        raise ValueError(f"choice 需从候选中选：{d.options}")
    d.choice = choice
    d.status = "decided"
    flow_event(d, "decide", request.user, opt_str(request, "rationale"))
    d.save()
    return ok({"id": d.id, "choice": d.choice, "status": d.status})


@endpoint()
def decision_delete(request, pk):
    """删除决策记录。"""
    d = get_obj(DecisionRecord, pk, request.user, write=True)
    d.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def decision_archive(request):
    """决策档案：已定论的记录（复盘用）。"""
    qs = scope_queryset(DecisionRecord.objects.filter(status="decided"), request.user).order_by("-updated_at")
    return ok({"items": [obj_dict(o, extra=("choice",)) for o in qs[:100]], "count": qs.count()})


# =====================================================================
# todobox 轻待办（8）
# =====================================================================


REPEAT_RULES = ("none", "daily", "weekly", "workday")


def _clean_repeat(val):
    rule = (val or "none").strip().lower()
    if rule not in REPEAT_RULES:
        raise ValueError(f"repeat_rule 仅支持 {'/'.join(REPEAT_RULES)}")
    return rule


@endpoint()
def todo_create(request):
    """新建待办（F689 支持重复规则，F690 支持重要标记）。"""
    t = TodoItem.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        priority=opt_str(request, "priority", "normal"),
        due_date=parse_day(opt_str(request, "due_date"), "due_date", allow_empty=True),
        important=opt_bool(request, "important", False),
        repeat_rule=_clean_repeat(opt_str(request, "repeat_rule", "none")),
        repeat_until=parse_day(opt_str(request, "repeat_until"), "repeat_until", allow_empty=True),
        status="open", data={"events": []})
    return ok({"id": t.id, "title": t.title, "priority": t.priority,
               "important": t.important, "repeat_rule": t.repeat_rule})


@endpoint(("GET",))
def todo_list(request):
    """待办列表（完成态/优先级/逾期过滤）。"""
    qs = TodoItem.objects.filter(owner=request.user).order_by("done", "due_date", "-created_at")
    done = opt_bool(request, "done", None)
    if done is not None and p(request, "done") is not None:
        qs = qs.filter(done=bool(p(request, "done")))
    priority = opt_str(request, "priority")
    if priority:
        qs = qs.filter(priority=priority)
    overdue_only = opt_bool(request, "overdue_only")
    if overdue_only:
        qs = qs.filter(done=False, due_date__lt=timezone.localdate())
    return ok({"items": [obj_dict(o, extra=("priority", "due_date")) | {
        "done": o.done, "important": o.important,
        "repeat_rule": o.repeat_rule,
        "repeat_until": o.repeat_until.isoformat() if o.repeat_until else None,
    } for o in qs[:200]],
               "count": qs.count()})


@endpoint()
def todo_update(request, pk):
    """编辑待办。"""
    t = get_obj(TodoItem, pk, request.user, write=True)
    if p(request, "title") is not None:
        t.title = req_str(request, "title")[:200]
    if p(request, "priority") is not None:
        t.priority = opt_str(request, "priority", t.priority)
    if p(request, "due_date") is not None:
        t.due_date = parse_day(opt_str(request, "due_date"), "due_date", allow_empty=True)
    if p(request, "remark") is not None:
        t.remark = opt_str(request, "remark")
    if p(request, "important") is not None:
        t.important = opt_bool(request, "important")
    if p(request, "repeat_rule") is not None:
        t.repeat_rule = _clean_repeat(opt_str(request, "repeat_rule", t.repeat_rule))
    if p(request, "repeat_until") is not None:
        t.repeat_until = parse_day(opt_str(request, "repeat_until"), "repeat_until", allow_empty=True)
    t.save()
    return ok({"id": t.id, "title": t.title, "priority": t.priority,
               "important": t.important, "repeat_rule": t.repeat_rule})


@endpoint()
def todo_complete(request, pk):
    """完成待办。"""
    t = get_obj(TodoItem, pk, request.user)
    t.done = True
    t.status = "done"
    t.save(update_fields=["done", "status", "updated_at"])
    return ok({"id": t.id, "done": True})


@endpoint()
def todo_reopen(request, pk):
    """重开待办。"""
    t = get_obj(TodoItem, pk, request.user)
    t.done = False
    t.status = "open"
    t.save(update_fields=["done", "status", "updated_at"])
    return ok({"id": t.id, "done": False})


@endpoint()
def todo_delete(request, pk):
    """删除待办。"""
    t = get_obj(TodoItem, pk, request.user, write=True)
    t.delete()
    return ok({"deleted": pk})


@endpoint()
def todo_batch_complete(request):
    """批量完成（最多 50 条，须全部属于自己）。"""
    ids = req_list(request, "ids", max_len=50)
    if not ids:
        raise ValueError("ids 不能为空")
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise ValueError("ids 需为整数数组")
    updated = TodoItem.objects.filter(pk__in=ids, owner=request.user).update(done=True, status="done")
    return ok({"requested": len(ids), "updated": updated})


@endpoint(("GET",))
def todo_stats(request):
    """待办统计：各优先级未完成数、逾期数、本周完成数。"""
    base = TodoItem.objects.filter(owner=request.user)
    open_by_prio = (base.filter(done=False).values("priority")
                    .annotate(c=Count("id")).order_by("-c"))
    overdue = base.filter(done=False, due_date__lt=timezone.localdate()).count()
    week_ago = timezone.localdate() - timedelta(days=7)
    done_week = base.filter(done=True, updated_at__gte=week_ago).count()
    return ok({"open_by_priority": [{"priority": r["priority"], "count": r["c"]} for r in open_by_prio],
               "overdue": overdue, "done_this_week": done_week,
               "open_total": base.filter(done=False).count()})


PEOPLE_FAMILY_COUNT = 13 + 9 + 10 + 6 + 7 + 10 + 7 + 11  # = 73（F683 换班申请 +4，F689/F690 待办 +2）


@endpoint()
def todo_due_check(request):
    """待办到期检查（#90）：扫描我的逾期/今日到期待办，生成提醒通知。

    可由定时任务调用，也可手动触发。返回本次提醒条数。
    """
    from core.models import notify
    today = timezone.localdate()
    overdue = TodoItem.objects.filter(
        owner=request.user, done=False, due_date__lt=today)
    due_today = TodoItem.objects.filter(
        owner=request.user, done=False, due_date=today)

    n = 0
    for t in overdue:
        notify(request.user, title=f"待办已逾期：{t.title}",
               content=f"截止日期 {t.due_date} 已过，请尽快处理。",
               category="system", level="warning", link="/officesuite")
        n += 1
    for t in due_today:
        notify(request.user, title=f"待办今日到期：{t.title}",
               content="今天是截止日，别忘了完成。",
               category="system", level="info", link="/officesuite")
        n += 1
    return ok({"overdue": overdue.count(), "due_today": due_today.count(), "notified": n})


# =====================================================================
# F690 待办四象限（重要 × 紧急矩阵）
# =====================================================================


def _is_urgent(t, today):
    """紧急：高/紧急优先级，或截止日 ≤ 今天（今天到期/已逾期）。"""
    if t.priority in ("high", "urgent"):
        return True
    return bool(t.due_date and t.due_date <= today)


def _quadrant_item(t, today):
    return {
        "id": t.id, "title": t.title, "priority": t.priority,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "important": t.important, "remark": t.remark,
        "overdue": bool(t.due_date and t.due_date < today),
        "repeat_rule": t.repeat_rule,
        "created_at": t.created_at.isoformat(),
    }


_QUADRANTS = [
    ("q1", "重要且紧急", "立刻做", "rose"),
    ("q2", "重要不紧急", "计划做", "brand"),
    ("q3", "紧急不重要", "委托/快速处理", "amber"),
    ("q4", "不重要不紧急", "有空再做", "slate"),
]


@endpoint(("GET",))
def todo_quadrant(request):
    """F690 四象限视图：按 重要 × 紧急 把未完成待办分进四个象限。"""
    today = timezone.localdate()
    qs = TodoItem.objects.filter(owner=request.user, done=False).order_by("due_date", "-created_at")
    buckets = {k: [] for k, *_ in _QUADRANTS}
    for t in qs[:500]:
        imp, urg = t.important, _is_urgent(t, today)
        key = "q1" if (imp and urg) else "q2" if imp else "q3" if urg else "q4"
        buckets[key].append(_quadrant_item(t, today))
    quads = [{
        "key": k, "name": name, "hint": hint, "accent": accent,
        "count": len(buckets[k]), "items": buckets[k][:50],
    } for k, name, hint, accent in _QUADRANTS]
    return ok({
        "date": str(today),
        "quadrants": quads,
        "counts": {k: len(buckets[k]) for k, *_ in _QUADRANTS},
        "total": sum(len(v) for v in buckets.values()),
        "legend": "紧急 = 高/紧急优先级，或截止 ≤ 今天；重要 = important 标记",
    })


# =====================================================================
# F689 待办重复规则（daily / weekly / workday 自动生成今日实例）
# =====================================================================


def _repeat_due_today(t, today):
    """判断重复待办今天是否该生成实例。"""
    if t.repeat_rule == "daily":
        return True
    if t.repeat_rule == "workday":
        return today.weekday() < 5
    if t.repeat_rule == "weekly":
        anchor = t.due_date or t.created_at.date()
        return today.weekday() == anchor.weekday()
    return False


def repeat_scan_for_user(user, today=None):
    """给单个用户按重复规则生成今日待办实例（端点与管理命令共用）。

    幂等：以 data.repeat_parent + data.repeat_date 去重，每天最多生成一次。
    返回 {"scanned", "created", "items"}。
    """
    today = today or timezone.localdate()
    created = []
    scanned = 0
    qs = (TodoItem.objects.filter(owner=user)
          .exclude(repeat_rule="none").filter(done=False).order_by("-created_at")[:500])
    for t in qs:
        scanned += 1
        if t.repeat_until and today > t.repeat_until:
            continue
        if t.last_generated == today:
            continue
        if not _repeat_due_today(t, today):
            # 今天不是重复日，只推进标记避免反复评估
            continue
        dup = TodoItem.objects.filter(
            owner=user, data__repeat_parent=t.id, data__repeat_date=str(today)
        ).exists()
        if not dup:
            child = TodoItem.objects.create(
                owner=user, title=t.title, priority=t.priority,
                due_date=today, important=t.important,
                repeat_rule="none", status="open", remark=t.remark,
                data={"repeat_parent": t.id, "repeat_date": str(today),
                      "source": "repeat", "events": []},
            )
            created.append({"id": child.id, "title": child.title, "parent": t.id})
        t.last_generated = today
        t.save(update_fields=["last_generated", "updated_at"])
    return {"date": str(today), "scanned": scanned,
            "created": len(created), "items": created[:50]}


@endpoint(("POST",))
def todo_repeat_scan(request):
    """F689 扫描我的重复待办，生成今日实例（管理命令 scan_todo_repeat 全员版）。"""
    out = repeat_scan_for_user(request.user)
    return ok(out)
