# -*- coding: utf-8 -*-
"""officesuite · 日程面接口：calendar(14) + 领域目录 catalog(1) = 15 个。

日程是横切能力：审批、会议、培训都可往里放 SuiteEvent。
F681 冲突预检 / F682 时长模板入口 / F691 人员忙闲查询也挂在这里。
S26：会议临近提醒 / .ics 导出 / 今日聚焦。
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone

from core.scoping import scope_queryset
from core.validators import as_datetime

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p, req_str
from officesuite.common import flow_event, get_obj, obj_dict, parse_day, parse_dt
from officesuite.models import (ApprovalRequest, DutyShift, RoomBooking,
                                SuiteEvent, TodoItem, VehicleBooking)


def _event_conflicts(user, start, end, exclude_id=None, limit=10):
    """F681 日程冲突检测：与已有日程时间重叠的清单（行级 scope 沿用）。

    无结束时间的日程按 1 小时占位处理；仅做提示，不阻断创建。
    """
    if end is None:
        end = start + timedelta(hours=1)
    if end <= start:
        return []
    lo, hi = start - timedelta(hours=12), end + timedelta(hours=12)
    qs = scope_queryset(
        SuiteEvent.objects.filter(start_at__lt=hi, start_at__gte=lo), user
    ).order_by("start_at")
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    out = []
    for e in qs[:300]:
        e_end = e.end_at or (e.start_at + timedelta(hours=1))
        if e.start_at < end and e_end > start:
            out.append({
                "id": e.id, "title": e.title, "kind": e.kind,
                "start_at": timezone.localtime(e.start_at).isoformat(),
                "end_at": timezone.localtime(e.end_at).isoformat() if e.end_at else None,
                "owner": e.owner.username if e.owner_id else "",
            })
            if len(out) >= limit:
                break
    return out


def _resource_conflicts(resource, start, end, exclude_id=None, limit=10):
    """F686 资源预约冲突：同资源同时段的既有预约（会议室 / 车辆）。"""
    if end is None:
        end = start + timedelta(hours=1)
    if end <= start or not resource:
        return []
    kind, _, raw_id = str(resource).partition(":")
    out = []
    try:
        rid = int(raw_id)
    except (TypeError, ValueError):
        raise ValueError("resource 形如 room:3 或 vehicle:2")
    if kind == "room":
        qs = RoomBooking.objects.filter(status="booked", room_id=rid,
                                        start_at__lt=end, end_at__gt=start).order_by("start_at")
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        for b in qs[:limit]:
            out.append({"id": b.id, "type": "room", "resource": b.room.name,
                        "title": b.title, "start_at": b.start_at.isoformat(),
                        "end_at": b.end_at.isoformat() if b.end_at else None,
                        "owner": b.owner.username if b.owner_id else ""})
    elif kind == "vehicle":
        qs = VehicleBooking.objects.filter(
            status__in=("pending", "approved"), vehicle_id=rid,
        ).order_by("use_at")
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        for b in qs[:50]:
            b_end = b.return_at or b.use_at
            if b.use_at < end and b_end > start:
                out.append({"id": b.id, "type": "vehicle", "resource": b.vehicle.plate,
                            "title": b.title, "start_at": b.use_at.isoformat(),
                            "end_at": b.return_at.isoformat() if b.return_at else None,
                            "owner": b.owner.username if b.owner_id else ""})
                if len(out) >= limit:
                    break
    else:
        raise ValueError("resource 仅支持 room / vehicle")
    return out

# =====================================================================
# calendar 日程（11）
# =====================================================================


@endpoint()
def calendar_event_create(request):
    """创建日程（kind: event/meeting/review/other）。

    F681：返回 `conflicts` 时间重叠提示（仅提示不阻断）；
    F682：支持 `duration_minutes` 快速时长（15/30/60 模板），未传 end_at 时按它算结束时间。
    """
    start = as_datetime(req_str(request, "start_at"), "start_at")
    end_raw = opt_str(request, "end_at", "").strip()
    end = as_datetime(end_raw, "end_at") if end_raw else None
    duration = opt_num(request, "duration_minutes", None, minimum=1, maximum=24 * 60)
    if end is None and duration:
        end = start + timedelta(minutes=int(duration))
    # #73：先保证时间区间合法，再做冲突检测（倒置/零长度日程直接拒绝）
    if end is not None and end <= start:
        raise ValueError("结束时间必须晚于开始时间")

    conflicts = _event_conflicts(request.user, start, end)

    e = SuiteEvent.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        start_at=start,
        end_at=end,
        kind=opt_str(request, "kind", "event"),
        attendees=p(request, "attendees") or [],
        replies=[],
        data={"duration_minutes": int(duration) if duration else None},
    )
    return ok({"id": e.id, "title": e.title,
               "start_at": e.start_at.isoformat(),
               "end_at": e.end_at.isoformat() if e.end_at else None,
               "duration_minutes": int(duration) if duration else None,
               "has_conflict": bool(conflicts),
               "conflict_count": len(conflicts),
               "conflicts": conflicts})


@endpoint(("GET",))
def calendar_event_list(request):
    """日程列表（时间区间 + 类型过滤）。"""
    qs = scope_queryset(SuiteEvent.objects.all(), request.user).order_by("start_at")
    start = opt_str(request, "start")
    end = opt_str(request, "end")
    if start:
        qs = qs.filter(start_at__gte=parse_dt(start, "start"))
    if end:
        qs = qs.filter(start_at__lt=parse_dt(end, "end"))
    kind = opt_str(request, "kind")
    if kind:
        qs = qs.filter(kind=kind)
    return ok({"items": [obj_dict(o) | {"start_at": o.start_at.isoformat(),
                                         "end_at": o.end_at.isoformat() if o.end_at else None,
                                         "kind": o.kind,
                                         "attendees": o.attendees}
                         for o in qs[:200]],
               "count": qs.count()})


def _ics_utc(dt):
    """S26-359：ICS 时间统一用 UTC 的 20260101T100000Z 形式。"""
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_text(text):
    """ICS 文本转义：反斜杠 / 逗号 / 分号 / 换行，并按 75 字节折行。"""
    s = str(text or "").replace("\\", "\\\\").replace(";", "\\;")
    s = s.replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    out, buf = [], ""
    for ch in s:
        if len((buf + ch).encode("utf-8")) > 73:
            out.append(buf)
            buf = " " + ch
        else:
            buf += ch
    out.append(buf)
    return "\r\n".join(out)


@endpoint(("GET",))
def calendar_export_ics(request):
    """S26-359 日程导出 .ics：VCALENDAR 含 UID/DTSTART/DTEND/SUMMARY/LOCATION。"""
    start = parse_day(opt_str(request, "start"), "start", allow_empty=True)
    end = parse_day(opt_str(request, "end"), "end", allow_empty=True)
    qs = scope_queryset(SuiteEvent.objects.all(), request.user).order_by("start_at")
    if start:
        qs = qs.filter(start_at__gte=timezone.make_aware(
            datetime(start.year, start.month, start.day, 0, 0)))
    if end:
        qs = qs.filter(start_at__lt=timezone.make_aware(
            datetime(end.year, end.month, end.day, 0, 0)) + timedelta(days=1))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//QoderCN//Officesuite Calendar//ZH-CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    exported = 0
    for e in qs[:1000]:
        e_end = e.end_at or (e.start_at + timedelta(hours=1))
        location = str((e.data or {}).get("location") or "")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:event-{e.id}@officesuite",
            f"DTSTAMP:{_ics_utc(timezone.now())}",
            f"DTSTART:{_ics_utc(e.start_at)}",
            f"DTEND:{_ics_utc(e_end)}",
            f"SUMMARY:{_ics_text(e.title or '日程')}",
        ])
        if location:
            lines.append(f"LOCATION:{_ics_text(location)}")
        lines.extend(["STATUS:CONFIRMED", "END:VEVENT"])
        exported += 1
    lines.append("END:VCALENDAR")
    body = "\r\n".join(lines) + "\r\n"
    resp = HttpResponse(body.encode("utf-8"),
                        content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = "attachment; filename=calendar.ics"
    resp["X-Event-Count"] = str(exported)
    return resp


@endpoint()
def calendar_event_detail(request, pk):
    """日程详情（含 RSVP 汇总）。"""
    e = get_obj(SuiteEvent, pk, request.user)
    replies = e.replies or []
    yes = sum(1 for r in replies if r.get("answer") == "yes")
    return ok({"id": e.id, "title": e.title,
               "start_at": e.start_at.isoformat(),
               "end_at": e.end_at.isoformat() if e.end_at else None,
               "kind": e.kind, "attendees": e.attendees,
               "rsvp": {"yes": yes, "no": len(replies) - yes, "total": len(replies)},
               "owner": e.owner.username})


@endpoint()
def calendar_event_update(request, pk):
    """修改日程（F681：改完同样返回重叠提示）。"""
    e = get_obj(SuiteEvent, pk, request.user, write=True)
    if p(request, "title") is not None:
        e.title = req_str(request, "title")[:200]
    if p(request, "start_at") is not None:
        e.start_at = parse_dt(req_str(request, "start_at"), "start_at")
    if p(request, "end_at") is not None:
        e.end_at = parse_dt(opt_str(request, "end_at"), "end_at", allow_empty=True)
    if p(request, "kind") is not None:
        e.kind = opt_str(request, "kind", e.kind)
    if p(request, "attendees") is not None:
        e.attendees = p(request, "attendees") or []
    if p(request, "duration_minutes") is not None and e.end_at is None:
        e.end_at = e.start_at + timedelta(
            minutes=int(opt_num(request, "duration_minutes", 30, minimum=1, maximum=24 * 60)))
    e.save()
    conflicts = _event_conflicts(request.user, e.start_at, e.end_at, exclude_id=e.pk)
    return ok({"id": e.id, "title": e.title,
               "has_conflict": bool(conflicts),
               "conflict_count": len(conflicts),
               "conflicts": conflicts})


@endpoint()
def calendar_event_delete(request, pk):
    """删除日程。"""
    e = get_obj(SuiteEvent, pk, request.user, write=True)
    e.delete()
    return ok({"deleted": pk})


@endpoint()
def calendar_event_rsvp(request, pk):
    """回复是否参加（同一人覆盖上次回复）。"""
    e = get_obj(SuiteEvent, pk, request.user)
    answer = req_str(request, "answer")
    if answer not in ("yes", "no"):
        raise ValueError("answer 需为 yes 或 no")
    name = request.user.username
    replies = [r for r in (e.replies or []) if r.get("name") != name]
    replies.append({"name": name, "answer": answer,
                    "at": timezone.now().isoformat()})
    e.replies = replies
    e.save(update_fields=["replies"])
    return ok({"id": e.id, "answer": answer})


@endpoint(("GET",))
def calendar_event_attendees(request, pk):
    """日程参与回复名单。"""
    e = get_obj(SuiteEvent, pk, request.user)
    return ok({"title": e.title, "attendees": e.attendees,
               "replies": e.replies or []})


@endpoint(("GET",))
def agenda_today(request):
    """今日日程。"""
    now = timezone.localtime()
    lo = now.replace(hour=0, minute=0, second=0, microsecond=0)
    qs = scope_queryset(SuiteEvent.objects.filter(
        start_at__gte=lo, start_at__lt=lo + timedelta(days=1)), request.user).order_by("start_at")
    return ok({"date": str(lo.date()),
               "items": [{"id": e.id, "title": e.title, "kind": e.kind,
                          "start_at": e.start_at.isoformat()} for e in qs[:100]],
               "count": qs.count()})


@endpoint(("GET",))
def agenda_week(request):
    """本周日程（周一至周日，按天分组）。"""
    ref = timezone.localdate()
    if opt_str(request, "date"):
        from django.utils.dateparse import parse_date
        d = parse_date(opt_str(request, "date"))
        if d:
            ref = d
    monday = ref - timedelta(days=ref.weekday())
    qs = scope_queryset(SuiteEvent.objects.filter(
        start_at__gte=monday, start_at__lt=monday + timedelta(days=7)), request.user).order_by("start_at")
    by_day = {}
    for e in qs:
        key = str(timezone.localtime(e.start_at).date())
        by_day.setdefault(key, []).append(
            {"id": e.id, "title": e.title, "kind": e.kind,
             "start_at": e.start_at.isoformat()})
    return ok({"week_start": str(monday),
               "days": [{"date": str(monday + timedelta(days=i)),
                         "weekday": "一二三四五六日"[i],
                         "events": by_day.get(str(monday + timedelta(days=i)), [])}
                        for i in range(7)]})


@endpoint()
def meeting_reminders_due(request):
    """S26-356 会议临近提醒：扫窗口内开始的 room 资源事件 / 房间预订并通知参会人。

    通过 Notification（recipient + link）去重，避免反复扫描重复轰炸。
    """
    window = int(opt_num(request, "window", 15, integer=True, minimum=1, maximum=180))
    now = timezone.now()
    lo, hi = now, now + timedelta(minutes=window)
    from accounts.models import User
    from core.models import Notification
    from core.notify import dispatch

    def _targets(names):
        out = []
        for name in dict.fromkeys([str(n).strip() for n in names if str(n).strip()]):
            u = User.objects.filter(Q(username=name) | Q(nickname=name)).first()
            if u is not None:
                out.append(u)
        return out[:50]

    notified = skipped = 0
    items = []

    events = scope_queryset(
        SuiteEvent.objects.filter(start_at__gte=lo, start_at__lt=hi), request.user
    ).order_by("start_at")[:200]
    for e in events:
        resource = str((e.data or {}).get("resource") or "")
        if not resource.startswith("room:"):
            continue
        link = f"/officesuite/meeting?event={e.id}"
        title = f"会议即将开始：{e.title or '会议'}"
        people = _targets([e.owner.username] + list(e.attendees or []))
        hit = 0
        for u in people:
            if Notification.objects.filter(recipient=u, link=link,
                                           created_at__gte=now - timedelta(hours=2)).exists():
                skipped += 1
                continue
            if dispatch(u, title,
                        f"{timezone.localtime(e.start_at):%H:%M} 开始（{resource}），请准时参加。",
                        category="system", level="info", link=link) is not None:
                notified += 1
                hit += 1
        items.append({"kind": "event", "id": e.id, "title": e.title,
                      "resource": resource, "start_at": e.start_at.isoformat(),
                      "targets": len(people), "notified": hit})

    bookings = RoomBooking.objects.filter(status="booked", start_at__gte=lo,
                                          start_at__lt=hi).order_by("start_at")[:200]
    for b in bookings:
        link = f"/officesuite/meeting?booking={b.id}"
        title = f"会议即将开始：{b.title or b.room.name}"
        people = _targets([b.owner.username] + list((b.data or {}).get("attendees") or []))
        hit = 0
        for u in people:
            if Notification.objects.filter(recipient=u, link=link,
                                           created_at__gte=now - timedelta(hours=2)).exists():
                skipped += 1
                continue
            if dispatch(u, title,
                        f"{timezone.localtime(b.start_at):%H:%M} 在 {b.room.name} 开始，请准时参加。",
                        category="system", level="info", link=link) is not None:
                notified += 1
                hit += 1
        items.append({"kind": "booking", "id": b.id, "title": b.title,
                      "resource": f"room:{b.room_id}", "room": b.room.name,
                      "start_at": b.start_at.isoformat(),
                      "targets": len(people), "notified": hit})

    return ok({"window": window, "from": lo.isoformat(), "to": hi.isoformat(),
               "scanned": len(items), "notified": notified, "skipped": skipped,
               "items": items})


@endpoint(("GET",))
def focus_today(request):
    """S26-360 今日聚焦：当日日程 + 今日/逾期待办 + 待我审批，聚合一屏。"""
    now = timezone.localtime()
    lo = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hi = lo + timedelta(days=1)
    events = scope_queryset(
        SuiteEvent.objects.filter(start_at__gte=lo, start_at__lt=hi), request.user
    ).order_by("start_at")[:100]
    today = timezone.localdate()
    todos = (TodoItem.objects.filter(owner=request.user, done=False, due_date__lte=today)
             .order_by("due_date", "id")[:100])
    pending = (scope_queryset(ApprovalRequest.objects.filter(status="pending"), request.user)
               .exclude(owner=request.user).order_by("-created_at"))
    return ok({
        "date": str(today),
        "agenda": [{"id": e.id, "title": e.title, "kind": e.kind,
                    "start_at": e.start_at.isoformat(),
                    "end_at": e.end_at.isoformat() if e.end_at else None,
                    "location": (e.data or {}).get("location", "")} for e in events],
        "agenda_count": len(events),
        "todos": [{"id": t.id, "title": t.title, "priority": t.priority,
                   "due_date": t.due_date.isoformat() if t.due_date else None,
                   "overdue": bool(t.due_date and t.due_date < today),
                   "important": t.important} for t in todos],
        "todo_count": len(todos),
        "overdue_count": sum(1 for t in todos if t.due_date and t.due_date < today),
        "approvals": {"count": pending.count(),
                      "items": [{"id": r.id, "title": r.title,
                                 "owner": r.owner.username,
                                 "created_at": r.created_at.isoformat()}
                                for r in pending[:5]]},
    })


@endpoint(("GET", "POST"))
def calendar_conflict_check(request):
    """F681 + F686 冲突预检：创建日程/预约前先查时间重叠与同资源占用。

    参数：start_at（必填）、end_at 或 duration_minutes、
          resource（可选，"room:3" / "vehicle:1"）、exclude（排除自身 ID）。
    只查询不落库，前后端提交前都能拿到提示。
    """
    start = parse_dt(req_str(request, "start_at"), "start_at")
    end = parse_dt(opt_str(request, "end_at"), "end_at", allow_empty=True)
    duration = opt_num(request, "duration_minutes", None, minimum=1, maximum=24 * 60)
    if end is None:
        end = start + timedelta(minutes=int(duration)) if duration else start + timedelta(hours=1)
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    exclude = opt_num(request, "exclude", None, integer=True)
    resource = opt_str(request, "resource", "").strip()

    events = _event_conflicts(request.user, start, end, exclude_id=exclude, limit=20)
    res = _resource_conflicts(resource, start, end, exclude_id=exclude) if resource else []
    return ok({
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "conflicts": events,
        "conflict_count": len(events),
        "resource_conflicts": res,
        "resource_conflict_count": len(res),
        "has_conflict": bool(events or res),
    })


@endpoint(("GET",))
def calendar_free_busy(request):
    """F691 人员忙闲查询：选一天，返回成员的忙碌段与空闲段。

    忙碌来源：可见日程（创建人 + 参与人命中）与当日值班班次；
    空闲 = 工作时段（默认 09:00–18:00）减去忙碌段（自动合并重叠）。
    参数：date（默认今天）、names（逗号分隔，缺省取当日相关成员）、
          work_start / work_end（HH:MM）。
    """
    from datetime import datetime as _dt, time as _time

    ref = parse_day(opt_str(request, "date"), "date", allow_empty=True) or timezone.localdate()
    lo = timezone.make_aware(_dt(ref.year, ref.month, ref.day, 0, 0))
    hi = lo + timedelta(days=1)

    def _t(key, default):
        s = opt_str(request, key, default).strip()
        try:
            hh, mm = (int(x) for x in s.split(":")[:2])
            return _time(min(23, max(0, hh)), min(59, max(0, mm)))
        except (TypeError, ValueError):
            raise ValueError(f"{key} 需为 HH:MM 格式")

    work_start = _t("work_start", "09:00")
    work_end = _t("work_end", "18:00")
    if work_end <= work_start:
        raise ValueError("work_end 必须晚于 work_start")
    win_lo = timezone.make_aware(_dt(ref.year, ref.month, ref.day,
                                     work_start.hour, work_start.minute))
    win_hi = timezone.make_aware(_dt(ref.year, ref.month, ref.day,
                                     work_end.hour, work_end.minute))

    busy = {}  # name -> [{start,end,title,source}]

    def _mins(dt):
        """统一换算到本地时区再取分钟数（库里存 UTC，直取 .hour 会偏 8 小时）。"""
        lt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        return lt.hour * 60 + lt.minute

    def _add(name, s, e, title, source):
        if not name:
            return
        busy.setdefault(str(name), []).append(
            {"start": _fmt(s), "end": _fmt(e),
             "start_min": _mins(s), "end_min": _mins(e),
             "title": title, "source": source})

    def _fmt(dt):
        lt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        return lt.isoformat()

    events = scope_queryset(
        SuiteEvent.objects.filter(
            Q(start_at__lt=hi) & (Q(end_at__gt=lo) | Q(end_at__isnull=True, start_at__gte=lo))
        ), request.user)
    ev_count = 0
    for e in events[:300]:
        s = max(e.start_at, lo)
        en = min(e.end_at or (e.start_at + timedelta(hours=1)), hi)
        if en <= s:
            continue
        ev_count += 1
        _add(e.owner.username if e.owner_id else "", s, en, e.title or "日程", "event")
        for a in (e.attendees or [])[:50]:
            _add(str(a), s, en, e.title or "日程", "event")

    shifts = scope_queryset(DutyShift.objects.filter(duty_date=ref), request.user)
    for sh in shifts[:300]:
        _add(sh.member_name, win_lo, win_hi,
             f"值班 {sh.shift_name}（{sh.schedule.name}）", "duty")

    # 指定名单过滤（否则返回当日有记录的全部成员）
    names = opt_str(request, "names", "").strip()
    wanted = [n.strip() for n in names.split(",") if n.strip()] or sorted(busy.keys())
    self_names = {request.user.username,
                  getattr(request.user, "display_name", request.user.username)}
    self_names.discard("")

    def _merge(intervals):
        out = []
        for it in sorted(intervals, key=lambda x: x["start_min"]):
            if out and it["start_min"] <= out[-1]["end_min"]:
                out[-1]["end_min"] = max(out[-1]["end_min"], it["end_min"])
            else:
                out.append(dict(it))
        return out

    people = []
    win_total = (win_hi - win_lo).seconds // 60
    for name in wanted:
        merged = _merge(busy.get(name, []))
        free, cursor = [], work_start.hour * 60 + work_start.minute
        end_m = work_end.hour * 60 + work_end.minute
        for it in merged:
            s = max(it["start_min"], cursor)
            e = min(it["end_min"], end_m)
            if s > cursor:
                free.append({"start_min": cursor, "end_min": s,
                             "start": f"{cursor // 60:02d}:{cursor % 60:02d}",
                             "end": f"{s // 60:02d}:{s % 60:02d}"})
            cursor = max(cursor, e)
            if cursor >= end_m:
                break
        if cursor < end_m:
            free.append({"start_min": cursor, "end_min": end_m,
                         "start": f"{cursor // 60:02d}:{cursor % 60:02d}",
                         "end": f"{end_m // 60:02d}:{end_m % 60:02d}"})
        busy_min = sum(min(it["end_min"], end_m) - max(it["start_min"],
                       work_start.hour * 60 + work_start.minute)
                       for it in merged
                       if it["end_min"] > work_start.hour * 60 + work_start.minute
                       and it["start_min"] < end_m)
        busy_min = max(0, min(busy_min, win_total))
        # #40：他人只暴露忙/闲布尔（不返回时段与事件/值班标题）
        is_self = name in self_names
        busy_payload = [{"start": f"{it['start_min'] // 60:02d}:{it['start_min'] % 60:02d}",
                         "end": f"{it['end_min'] // 60:02d}:{it['end_min'] % 60:02d}",
                         "title": it["title"], "source": it["source"]} for it in merged] \
            if is_self else bool(merged)
        people.append({
            "name": name,
            "busy": busy_payload,
            "free": free if is_self else not merged,
            "busy_minutes": busy_min,
            "free_minutes": max(0, win_total - busy_min),
            "free_percent": round((win_total - busy_min) * 100 / win_total, 1) if win_total else 0,
            "status": "busy" if free == [] else ("free" if not merged else "partial"),
            "best_slot": (free[0] if free else None) if is_self else None,
        })
    return ok({
        "date": str(ref),
        "work_window": {"start": f"{work_start.hour:02d}:{work_start.minute:02d}",
                        "end": f"{work_end.hour:02d}:{work_end.minute:02d}",
                        "minutes": win_total},
        "people": people, "count": len(people),
        "events_scanned": ev_count, "shifts_scanned": shifts.count(),
    })


# =====================================================================
# catalog 领域目录（1）
# =====================================================================

# S3-B2/B17：提取为模块级常量——suite_catalog 与冒烟脚本共用同一事实源，
# 加接口只改这里，两边永远不会脱节。
OFFICE_SUBSYSTEMS = [
    ("approval", "通用审批", 13), ("seal", "用印管理", 6),
    ("expense", "报销管理", 8), ("travel", "差旅申请", 7),
    ("contract", "合同台账", 8),
    ("meeting", "会议室预订", 12), ("asset", "固定资产", 12),
    ("vehicle", "车辆管理", 8), ("supplies", "办公用品", 8),
    ("visitor", "访客登记", 8), ("mailroom", "快递代收", 6),
    ("duty", "值班排班", 13), ("timesheet", "工时填报", 9),
    ("training", "培训管理", 10), ("recognition", "表彰墙", 6),
    ("standup", "每日站会", 7), ("okr", "OKR 目标", 10),
    ("decision", "决策记录", 7), ("todobox", "轻待办", 11),
    ("faq", "FAQ 知识", 7), ("policy", "制度文档", 8),
    ("template", "文档模板", 7), ("wiki", "团队 Wiki", 12),
    ("minutes", "会议纪要", 12), ("formcollect", "收集表单", 9),
    ("announcement", "部门公告", 8), ("poll", "投票", 9),
    ("helpdesk", "工单", 11), ("calendar", "共享日程", 14),
    ("docenh", "文档增强", 3),
]


@endpoint(("GET",))
def suite_catalog(request):
    """officesuite 目录：30 个子系统 × 269 接口 + 目录 = 270（供前端动态渲染）。"""
    subsystems = OFFICE_SUBSYSTEMS
    return ok({
        "domain": "officesuite", "domain_name": "办公套件",
        "subsystems": [{"key": k, "name": n, "endpoints": c,
                        "url_prefix": f"/api/officesuite/{k}/"}
                       for k, n, c in subsystems],
        "subsystem_count": len(subsystems),
        "endpoint_count": sum(c for _, _, c in subsystems) + 1,
        "note": "endpoint_count 含本目录接口；F681–F692 新增冲突预检/时长模板/换班申请/"
                "满意度评分/轮询分配/点赞收藏/重复规则/四象限/忙闲与行动项统计；"
                "S26 新增会议提醒/常用会议室/.ics 导出/今日聚焦/审批超时/空闲车辆/"
                "低库存/资产盘点与折旧/邀请码/快递催领/Wiki 导出/制度催办/表单统计/行动项转日程；"
                "F45–F47 新增文档批注/表格公式/演示大纲（文档增强）",
    })


CAL_FAMILY_COUNT = 14 + 1  # = 15（calendar 14 + catalog 1）
