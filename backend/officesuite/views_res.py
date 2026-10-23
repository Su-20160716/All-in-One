# -*- coding: utf-8 -*-
"""officesuite · 资源面接口：meeting(11) asset(9) vehicle(7) supplies(7) visitor(7) mailroom(5) = 46 个。

资源类（会议室/车辆/办公用品）由管理员建立，全员预订/领用；
资产走「领用-归还」台账；访客与快递是登记簿模式。
"""
from datetime import datetime, timedelta

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from core.scoping import scope_queryset

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req, req_num, req_str)
from officesuite.common import flow_event, get_obj, obj_dict, parse_day, parse_dt
from officesuite.models import (Asset, MailParcel, MeetingRoom, RoomBooking,
                                SupplyApply, SupplyItem, Vehicle,
                                VehicleBooking, VisitorRecord)

# =====================================================================
# meeting 会议室（10）
# =====================================================================


@endpoint()
def meeting_room_create(request):
    """新建会议室。"""
    r = MeetingRoom.objects.create(
        owner=request.user,
        name=req_str(request, "name")[:100],
        capacity=int(req_num(request, "capacity", minimum=1, maximum=9999)),
        location=opt_str(request, "location"),
        facilities=p(request, "facilities") or [],
        active=True,
    )
    return ok({"id": r.id, "name": r.name, "capacity": r.capacity})


@endpoint(("GET",))
def meeting_room_list(request):
    """会议室列表（active 过滤 + 容量筛选）。"""
    qs = MeetingRoom.objects.all().order_by("id")
    if opt_bool(request, "only_active", True):
        qs = qs.filter(active=True)
    cap = opt_num(request, "capacity_gt")
    if cap:
        qs = qs.filter(capacity__gte=cap)
    return ok({"items": [{"id": r.id, "name": r.name, "capacity": r.capacity,
                          "location": r.location, "facilities": r.facilities,
                          "active": r.active, "owner": r.owner.username}
                         for r in qs[:200]], "count": qs.count()})


@endpoint()
def meeting_room_update(request, pk):
    """编辑会议室信息或启停。"""
    r = get_obj(MeetingRoom, pk, request.user, write=True)
    if p(request, "name") is not None:
        r.name = req_str(request, "name")[:100]
    if p(request, "capacity") is not None:
        r.capacity = int(req_num(request, "capacity", minimum=1, maximum=9999))
    if p(request, "location") is not None:
        r.location = opt_str(request, "location")
    if p(request, "facilities") is not None:
        r.facilities = p(request, "facilities") or []
    if p(request, "active") is not None:
        r.active = bool(p(request, "active"))
    r.save()
    return ok({"id": r.id, "name": r.name, "active": r.active})


@endpoint()
def meeting_room_delete(request, pk):
    """删除会议室（连带其预订）。"""
    r = get_obj(MeetingRoom, pk, request.user, write=True)
    r.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def meeting_room_availability(request, pk):
    """某日会议室占用表：列出已被预订的时段。"""
    room = get_obj(MeetingRoom, pk, request.user)
    day = parse_day(req_str(request, "date"), "date", allow_empty=False)
    lo = timezone.make_aware(datetime(day.year, day.month, day.day, 0, 0))
    hi = lo + timedelta(days=1)
    books = RoomBooking.objects.filter(room=room, start_at__lt=hi, end_at__gt=lo,
                                       status="booked").order_by("start_at")
    return ok({"room": room.name, "date": str(day),
               "occupied": [{"id": b.id, "start_at": b.start_at.isoformat(),
                             "end_at": b.end_at.isoformat(), "title": b.title}
                            for b in books],
               "occupied_count": books.count()})


@endpoint()
def meeting_book(request):
    """预订会议室：校验时段冲突与结束晚于开始。

    F682：支持 duration_minutes（15/30/60 模板）——未传 end_at 时按它计算；
    F686：冲突时 ValueError → 400，同时带回同时段已有预约清单供提示。
    """
    room = get_obj(MeetingRoom, int(req_num(request, "room_id", minimum=1)), request.user, write=True)
    if not room.active:
        raise ValueError("该会议室已停用")
    start = parse_dt(req_str(request, "start_at"), "start_at")
    end = parse_dt(opt_str(request, "end_at"), "end_at", allow_empty=True)
    duration = opt_num(request, "duration_minutes", None, minimum=1, maximum=24 * 60)
    if end is None and duration:
        end = start + timedelta(minutes=int(duration))
    if end is None:
        raise ValueError("缺少 end_at（或传 duration_minutes 按时长模板计算）")
    if end <= start:
        raise ValueError("结束时间必须晚于开始时间")
    clash_qs = RoomBooking.objects.filter(room=room, status="booked",
                                          start_at__lt=end, end_at__gt=start).order_by("start_at")
    clash_list = [{
        "id": b.id, "title": b.title, "start_at": b.start_at.isoformat(),
        "end_at": b.end_at.isoformat() if b.end_at else None,
        "start_hm": timezone.localtime(b.start_at).strftime("%H:%M"),
        "end_hm": timezone.localtime(b.end_at).strftime("%H:%M") if b.end_at else "--:--",
        "owner": b.owner.username if b.owner_id else "",
    } for b in clash_qs[:10]]
    if clash_list:
        raise ValueError(
            f"该时段已被预订（{clash_list[0]['start_hm']}–{clash_list[0]['end_hm']}，"
            f"共 {len(clash_list)} 条冲突），请换时段或换会议室"
        )
    b = RoomBooking.objects.create(
        owner=request.user, room=room, start_at=start, end_at=end,
        title=req_str(request, "title")[:200], status="booked",
        data={"attendees": p(request, "attendees") or [],
              "duration_minutes": int(duration) if duration else None,
              "events": []})
    flow_event(b, "book", request.user)
    b.save()
    return ok({"id": b.id, "room": room.name, "start_at": start.isoformat(),
               "end_at": end.isoformat(),
               "duration_minutes": int(duration) if duration else None,
               "has_conflict": False, "conflicts": []})


@endpoint()
def meeting_booking_cancel(request, pk):
    """取消预订（本人或超管）。"""
    b = get_obj(RoomBooking, pk, request.user, write=True)
    if b.owner_id != request.user.id and not request.user.is_superuser:
        raise ValueError("只能取消自己的预订")
    if b.status != "booked":
        raise ValueError("该预订已不是有效状态")
    b.status = "cancelled"
    flow_event(b, "cancel", request.user, opt_str(request, "note"))
    b.save()
    return ok({"id": b.id, "status": b.status})


@endpoint(("GET",))
def meeting_my_bookings(request):
    """我的会议室预订（含历史，status 过滤）。"""
    qs = RoomBooking.objects.filter(owner=request.user).order_by("-start_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    return ok({"items": [obj_dict(o, extra=("room", "start_at", "end_at")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def meeting_booking_detail(request, pk):
    """预订详情。"""
    b = get_obj(RoomBooking, pk, request.user)
    d = obj_dict(b, extra=("room", "start_at", "end_at"))
    d["events"] = (b.data or {}).get("events", [])
    return ok(d)


@endpoint(("GET",))
def meeting_stats(request):
    """预订统计：总预订量、有效率、未来一周预订数。"""
    total = RoomBooking.objects.count()
    active = RoomBooking.objects.filter(status="booked").count()
    now = timezone.now()
    week = RoomBooking.objects.filter(status="booked", start_at__gte=now,
                                      start_at__lt=now + timedelta(days=7)).count()
    top_rooms = (RoomBooking.objects.filter(status="booked")
                 .values("room__name").annotate(c=Count("id")).order_by("-c")[:5])
    return ok({"total": total, "active": active, "cancelled": total - active,
               "next_7_days": week,
               "top_rooms": [{"room": t["room__name"], "bookings": t["c"]} for t in top_rooms]})


# =====================================================================
# F682 会议时长模板（15/30/60 快选）
# =====================================================================

DURATION_TEMPLATES = [
    {"minutes": 15, "label": "短会 15 分钟", "icon": "⚡"},
    {"minutes": 30, "label": "例会 30 分钟", "icon": "🕐"},
    {"minutes": 45, "label": "讨论 45 分钟", "icon": "💬"},
    {"minutes": 60, "label": "评审 60 分钟", "icon": "📌"},
    {"minutes": 90, "label": "工作坊 90 分钟", "icon": "🧩"},
]


@endpoint(("GET",))
def meeting_duration_templates(request):
    """F682 会议时长模板：返回 15/30/60 等快选时长。

    用法：创建日程 / 预订会议室时传 `duration_minutes=<minutes>`
    （calendar/event/create 与 meeting/book 均支持），后端自动算出结束时间。
    """
    return ok({
        "templates": DURATION_TEMPLATES,
        "quick_minutes": [t["minutes"] for t in DURATION_TEMPLATES],
        "default_minutes": 30,
        "max_minutes": 24 * 60,
        "usage": "提交时附带 duration_minutes 字段即可按时长模板自动计算 end_at",
    })


# =====================================================================
# asset 资产（9）
# =====================================================================


@endpoint()
def asset_create(request):
    """录入资产。"""
    a = Asset.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        code=opt_str(request, "code") or f"AST-{timezone.now().strftime('%Y%m%d')}-{Asset.objects.count() + 1:04d}",
        category=opt_str(request, "category", "设备"),
        value=req_num(request, "value", minimum=0, default=0),
        status="idle",
        data={"buy_date": opt_str(request, "buy_date"), "events": []},
        remark=opt_str(request, "remark"),
    )
    flow_event(a, "create", request.user)
    a.save()
    return ok({"id": a.id, "code": a.code, "title": a.title, "status": a.status})


@endpoint(("GET",))
def asset_list(request):
    """资产列表：状态/类别过滤 + 关键词。"""
    qs = scope_queryset(Asset.objects.all(), request.user).order_by("-created_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    category = opt_str(request, "category")
    if category:
        qs = qs.filter(category=category)
    kw = opt_str(request, "keyword")
    if kw:
        qs = qs.filter(Q(title__icontains=kw) | Q(code__icontains=kw))
    return ok({"items": [obj_dict(o, extra=("code", "category", "holder_name", "value")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def asset_update(request, pk):
    """编辑资产基础信息。"""
    a = get_obj(Asset, pk, request.user, write=True)
    if p(request, "title") is not None:
        a.title = req_str(request, "title")[:200]
    if p(request, "category") is not None:
        a.category = opt_str(request, "category", a.category)
    if p(request, "value") is not None:
        a.value = req_num(request, "value", minimum=0)
    if p(request, "remark") is not None:
        a.remark = opt_str(request, "remark")
    a.save()
    return ok(obj_dict(a, extra=("code", "category", "holder_name", "value")))


@endpoint()
def asset_delete(request, pk):
    """报废/删除资产（仅 idle 可删）。"""
    a = get_obj(Asset, pk, request.user, write=True)
    if a.status == "held":
        raise ValueError("资产在持有人手中，请先归还再删除")
    a.delete()
    return ok({"deleted": pk})


@endpoint()
def asset_assign(request, pk):
    """领用/分配资产给某人。"""
    a = get_obj(Asset, pk, request.user, write=True)
    if a.status == "held":
        raise ValueError(f"资产当前在 {a.holder_name or '他人'} 手中")
    holder_name = req_str(request, "holder_name")
    a.status = "held"
    a.holder_name = holder_name
    a.holder_id = opt_num(request, "holder_id")
    flow_event(a, "assign", request.user, f"分配给 {holder_name}")
    a.save()
    return ok({"id": a.id, "status": a.status, "holder_name": a.holder_name})


@endpoint()
def asset_return(request, pk):
    """归还资产。"""
    a = get_obj(Asset, pk, request.user, write=True)
    if a.status != "held":
        raise ValueError("资产未在借出状态")
    a.status = "idle"
    a.holder_name = ""
    a.holder_id = None
    flow_event(a, "return", request.user, opt_str(request, "note"))
    a.save()
    return ok({"id": a.id, "status": a.status})


@endpoint(("GET",))
def asset_my_held(request):
    """我持有的资产（按持有人用户 ID 匹配）。"""
    qs = Asset.objects.filter(holder_id=request.user.id, status="held").order_by("-updated_at")
    return ok({"items": [obj_dict(o, extra=("code", "category", "value")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def asset_detail(request, pk):
    """资产详情（含台账事件）。"""
    a = get_obj(Asset, pk, request.user)
    d = obj_dict(a, extra=("code", "category", "holder_name", "holder_id", "value"))
    d["events"] = (a.data or {}).get("events", [])
    return ok(d)


@endpoint(("GET",))
def asset_stats(request):
    """资产统计：按状态与类别汇总，总价值。"""
    by_status = (scope_queryset(Asset.objects.all(), request.user)
                 .values("status").annotate(c=Count("id")).order_by("-c"))
    by_cat = (scope_queryset(Asset.objects.all(), request.user)
              .values("category").annotate(c=Count("id"), v=Sum("value")).order_by("-c"))
    total_value = scope_queryset(Asset.objects.all(), request.user).aggregate(v=Sum("value"))["v"] or 0
    return ok({"by_status": [{"status": s["status"], "count": s["c"]} for s in by_status],
               "by_category": [{"category": s["category"], "count": s["c"], "value": float(s["v"] or 0)} for s in by_cat],
               "total_value": float(total_value)})


# =====================================================================
# vehicle 用车（7）
# =====================================================================


@endpoint()
def vehicle_create(request):
    """登记车辆。"""
    v = Vehicle.objects.create(
        owner=request.user,
        plate=req_str(request, "plate")[:20],
        model_name=opt_str(request, "model_name"),
        seats=int(req_num(request, "seats", minimum=1, maximum=99, default=5)),
        active=True,
    )
    return ok({"id": v.id, "plate": v.plate, "seats": v.seats})


@endpoint(("GET",))
def vehicle_list(request):
    """车辆列表（含可用过滤）。"""
    qs = Vehicle.objects.all().order_by("id")
    if opt_bool(request, "only_active", True):
        qs = qs.filter(active=True)
    return ok({"items": [{"id": v.id, "plate": v.plate, "model_name": v.model_name,
                          "seats": v.seats, "active": v.active} for v in qs[:100]],
               "count": qs.count()})


@endpoint()
def vehicle_update(request, pk):
    """编辑车辆 / 停用启用。"""
    v = get_obj(Vehicle, pk, request.user, write=True)
    if p(request, "plate") is not None:
        v.plate = req_str(request, "plate")[:20]
    if p(request, "model_name") is not None:
        v.model_name = opt_str(request, "model_name")
    if p(request, "seats") is not None:
        v.seats = int(req_num(request, "seats", minimum=1, maximum=99))
    if p(request, "active") is not None:
        v.active = bool(p(request, "active"))
    v.save()
    return ok({"id": v.id, "plate": v.plate, "active": v.active})


@endpoint()
def vehicle_book(request):
    """提交用车申请（pending，等待审批）。

    F686：返回同车辆同时段的已有申请作为冲突提示（不阻断，等审批裁决）。
    """
    v = get_obj(Vehicle, int(req_num(request, "vehicle_id", minimum=1)), request.user, write=True)
    if not v.active:
        raise ValueError("该车辆已停用")
    use_at = parse_dt(req_str(request, "use_at"), "use_at")
    return_at = parse_dt(opt_str(request, "return_at"), "return_at", allow_empty=True)
    conflicts = []
    if return_at and return_at > use_at:
        for other in VehicleBooking.objects.filter(
            vehicle=v, status__in=("pending", "approved")
        ).order_by("use_at")[:50]:
            other_end = other.return_at or other.use_at
            if other.use_at < return_at and other_end > use_at:
                conflicts.append({
                    "id": other.id, "title": other.title,
                    "start_at": other.use_at.isoformat(),
                    "end_at": other.return_at.isoformat() if other.return_at else None,
                    "owner": other.owner.username if other.owner_id else "",
                })
    b = VehicleBooking.objects.create(
        owner=request.user, vehicle=v,
        use_at=use_at,
        return_at=return_at,
        destination=req_str(request, "destination")[:120],
        title=f"用车申请 · {v.plate}", status="pending",
        data={"passengers": p(request, "passengers") or [],
              "conflicts": conflicts, "events": []},
        remark=opt_str(request, "remark"))
    flow_event(b, "submit", request.user)
    b.save()
    return ok({"id": b.id, "status": b.status, "plate": v.plate,
               "has_conflict": bool(conflicts), "conflicts": conflicts[:10],
               "conflict_count": len(conflicts)})


@endpoint()
def vehicle_booking_approve(request, pk):
    """审批用车（通过/驳回由 action 决定）。"""
    b = get_obj(VehicleBooking, pk, request.user, write=True)
    if b.status != "pending":
        raise ValueError(f"当前状态 {b.status} 不可审批")
    action = req_str(request, "action")
    if action not in ("approve", "reject"):
        raise ValueError("action 需为 approve 或 reject")
    b.status = "approved" if action == "approve" else "rejected"
    flow_event(b, action, request.user, opt_str(request, "note"))
    b.save()
    return ok({"id": b.id, "status": b.status})


@endpoint()
def vehicle_booking_cancel(request, pk):
    """取消自己的用车申请。"""
    b = get_obj(VehicleBooking, pk, request.user, write=True)
    if b.owner_id != request.user.id:
        raise ValueError("只能取消自己的申请")
    if b.status not in ("pending", "approved"):
        raise ValueError("当前状态不可取消")
    b.status = "cancelled"
    flow_event(b, "cancel", request.user)
    b.save()
    return ok({"id": b.id, "status": b.status})


@endpoint(("GET",))
def vehicle_my_bookings(request):
    """我的用车记录。"""
    qs = VehicleBooking.objects.filter(owner=request.user).order_by("-created_at")
    return ok({"items": [obj_dict(o, extra=("vehicle", "use_at", "return_at", "destination")) for o in qs[:100]],
               "count": qs.count()})


# =====================================================================
# supplies 办公用品（7）
# =====================================================================


@endpoint()
def supplies_item_create(request):
    """录入办公用品。"""
    it = SupplyItem.objects.create(
        owner=request.user,
        name=req_str(request, "name")[:100],
        stock=int(req_num(request, "stock", minimum=0, default=0)),
        unit=opt_str(request, "unit", "件"))
    return ok({"id": it.id, "name": it.name, "stock": it.stock, "unit": it.unit})


@endpoint(("GET",))
def supplies_item_list(request):
    """物品库存列表（低库存告警可选）。"""
    qs = SupplyItem.objects.all().order_by("id")
    if opt_bool(request, "low_stock"):
        qs = qs.filter(stock__lte=10)
    return ok({"items": [{"id": it.id, "name": it.name, "stock": it.stock,
                          "unit": it.unit} for it in qs[:200]],
               "count": qs.count()})


@endpoint()
def supplies_item_restock(request, pk):
    """补货（负数可作损耗修正）。"""
    it = get_obj(SupplyItem, pk, request.user)
    delta = int(req_num(request, "delta"))
    if it.stock + delta < 0:
        raise ValueError("调整后库存不能为负")
    SupplyItem.objects.filter(pk=it.pk).update(stock=F("stock") + delta)
    it.refresh_from_db()
    return ok({"id": it.id, "stock": it.stock, "delta": delta})


@endpoint()
def supplies_apply(request):
    """领用物品（库存不足直接拒绝）。"""
    it = get_obj(SupplyItem, int(req_num(request, "item_id", minimum=1)), request.user, write=True)
    qty = int(req_num(request, "qty", minimum=1, maximum=9999))
    if it.stock < qty:
        raise ValueError(f"库存不足：当前 {it.stock}，需 {qty}")
    SupplyItem.objects.filter(pk=it.pk).update(stock=F("stock") - qty)
    a = SupplyApply.objects.create(
        owner=request.user, item=it, qty=qty,
        title=f"领用 {it.name} x{qty}", status="done",
        data={"purpose": opt_str(request, "purpose"), "events": []})
    flow_event(a, "apply", request.user)
    a.save()
    it.refresh_from_db()
    return ok({"id": a.id, "item": it.name, "qty": qty, "stock_left": it.stock})


@endpoint()
def supplies_apply_cancel(request, pk):
    """取消领用（回滚库存）。"""
    a = get_obj(SupplyApply, pk, request.user, write=True)
    if a.status != "done":
        raise ValueError("该领用已处理过")
    a.status = "cancelled"
    SupplyItem.objects.filter(pk=a.item_id).update(stock=F("stock") + a.qty)
    flow_event(a, "cancel", request.user)
    a.save()
    return ok({"id": a.id, "status": a.status, "stock_restored": a.qty})


@endpoint(("GET",))
def supplies_my_applies(request):
    """我的领用记录。"""
    qs = SupplyApply.objects.filter(owner=request.user).order_by("-created_at")
    return ok({"items": [obj_dict(o, extra=("item", "qty")) for o in qs[:100]],
               "count": qs.count()})


@endpoint(("GET",))
def supplies_stats(request):
    """领用统计：按物品汇总领用量、库存总值（按件数）。"""
    top = (SupplyApply.objects.exclude(status="cancelled")
           .values("item__name").annotate(q=Sum("qty"), c=Count("id")).order_by("-q")[:10])
    total_stock = SupplyItem.objects.aggregate(s=Sum("stock"))["s"] or 0
    return ok({"top_items": [{"item": t["item__name"], "qty": t["q"], "times": t["c"]} for t in top],
               "total_stock": total_stock})


# =====================================================================
# visitor 访客（7）
# =====================================================================


@endpoint()
def visitor_create(request):
    """访客登记。"""
    v = VisitorRecord.objects.create(
        owner=request.user,
        visitor_name=req_str(request, "visitor_name")[:60],
        company=opt_str(request, "company"),
        host_name=opt_str(request, "host_name") or request.user.username,
        visit_at=parse_dt(opt_str(request, "visit_at"), "visit_at", allow_empty=True,
                          default=timezone.now()),
        title=f"访客 {req_str(request, 'visitor_name')[:60]}",
        status="registered", data={"events": []})
    flow_event(v, "register", request.user)
    v.save()
    return ok({"id": v.id, "visitor_name": v.visitor_name, "status": v.status})


@endpoint(("GET",))
def visitor_list(request):
    """访客列表（状态过滤 + 姓名/单位搜索）。"""
    qs = scope_queryset(VisitorRecord.objects.all(), request.user).order_by("-created_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    kw = opt_str(request, "keyword")
    if kw:
        qs = qs.filter(Q(visitor_name__icontains=kw) | Q(company__icontains=kw))
    return ok({"items": [obj_dict(o, extra=("visitor_name", "company", "host_name", "visit_at")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def visitor_update(request, pk):
    """修改访客信息。"""
    v = get_obj(VisitorRecord, pk, request.user, write=True)
    if p(request, "visitor_name") is not None:
        v.visitor_name = req_str(request, "visitor_name")[:60]
    if p(request, "company") is not None:
        v.company = opt_str(request, "company")
    if p(request, "host_name") is not None:
        v.host_name = opt_str(request, "host_name")
    if p(request, "visit_at") is not None:
        v.visit_at = parse_dt(opt_str(request, "visit_at"), "visit_at", allow_empty=True)
    v.save()
    return ok(obj_dict(v, extra=("visitor_name", "company", "host_name", "visit_at")))


@endpoint()
def visitor_checkin(request, pk):
    """访客到访确认。"""
    v = get_obj(VisitorRecord, pk, request.user, write=True)
    if v.status not in ("registered",):
        raise ValueError("仅已登记状态可签到")
    v.status = "checked_in"
    v.visit_at = v.visit_at or timezone.now()
    flow_event(v, "checkin", request.user)
    v.save()
    return ok({"id": v.id, "status": v.status})


@endpoint()
def visitor_checkout(request, pk):
    """访客离开。"""
    v = get_obj(VisitorRecord, pk, request.user, write=True)
    if v.status != "checked_in":
        raise ValueError("仅已签到状态可签退")
    v.status = "left"
    flow_event(v, "checkout", request.user)
    v.save()
    return ok({"id": v.id, "status": v.status})


@endpoint()
def visitor_delete(request, pk):
    """删除访客记录。"""
    v = get_obj(VisitorRecord, pk, request.user, write=True)
    v.delete()
    return ok({"deleted": pk})


@endpoint(("GET",))
def visitor_today(request):
    """今日访客一览。"""
    now = timezone.localtime()
    lo = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hi = lo + timedelta(days=1)
    qs = VisitorRecord.objects.filter(visit_at__gte=lo, visit_at__lt=hi).order_by("visit_at")
    return ok({"date": str(lo.date()),
               "items": [obj_dict(o, extra=("visitor_name", "company", "host_name", "status")) for o in qs[:100]],
               "count": qs.count(),
               "on_site": qs.filter(status="checked_in").count()})


# =====================================================================
# mailroom 快递代收（5）
# =====================================================================


@endpoint()
def mailroom_create(request):
    """快递入柜登记。"""
    m = MailParcel.objects.create(
        owner=request.user,
        receiver_name=req_str(request, "receiver_name")[:60],
        sender_info=opt_str(request, "sender_info"),
        title=f"包裹 · {req_str(request, 'receiver_name')[:60]}",
        status="pending", data={"kind": opt_str(request, "kind", "快递"), "events": []})
    flow_event(m, "receive", request.user)
    m.save()
    return ok({"id": m.id, "receiver_name": m.receiver_name, "status": m.status})


@endpoint(("GET",))
def mailroom_list(request):
    """包裹列表（状态过滤 + 收件人搜索）。"""
    qs = MailParcel.objects.all().order_by("-created_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    kw = opt_str(request, "keyword")
    if kw:
        qs = qs.filter(Q(receiver_name__icontains=kw) | Q(sender_info__icontains=kw))
    return ok({"items": [obj_dict(o, extra=("receiver_name", "sender_info", "picked_at")) for o in qs[:100]],
               "count": qs.count()})


@endpoint()
def mailroom_pickup(request, pk):
    """领取包裹。"""
    m = get_obj(MailParcel, pk, request.user, write=True)
    if m.status != "pending":
        raise ValueError("该包裹已领取或取消")
    m.status = "picked"
    m.picked_at = timezone.now()
    flow_event(m, "pickup", request.user, opt_str(request, "by") or m.receiver_name)
    m.save()
    return ok({"id": m.id, "status": m.status, "picked_at": m.picked_at.isoformat()})


@endpoint(("GET",))
def mailroom_pending(request):
    """待领取包裹（超过 3 天的标记滞留提醒）。"""
    qs = MailParcel.objects.filter(status="pending").order_by("created_at")
    threshold = timezone.now() - timedelta(days=3)
    items = []
    for o in qs[:100]:
        d = obj_dict(o, extra=("receiver_name", "sender_info"))
        d["stale"] = o.created_at < threshold
        items.append(d)
    return ok({"items": items, "count": qs.count(),
               "stale_count": sum(1 for i in items if i["stale"])})


@endpoint(("GET",))
def mailroom_stats(request):
    """快递统计：待取/已取/滞留。"""
    pending = MailParcel.objects.filter(status="pending").count()
    picked = MailParcel.objects.filter(status="picked").count()
    stale = MailParcel.objects.filter(status="pending", created_at__lt=timezone.now() - timedelta(days=3)).count()
    return ok({"pending": pending, "picked": picked, "stale": stale})


RES_FAMILY_COUNT = 11 + 9 + 7 + 7 + 7 + 5  # = 46（meeting 含 F682 时长模板）
