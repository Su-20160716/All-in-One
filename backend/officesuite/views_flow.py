# -*- coding: utf-8 -*-
"""officesuite · 审批流面接口：approval(11) seal(7) expense(8) travel(7) contract(8) = 41 个。

审批类统一状态机：pending → approved / rejected / cancelled，流转写入 data.events。
审批权 = 数据范围可见者（core.scoping），超管天然可见。
"""
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from core.scoping import scope_queryset

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req, req_num, req_str)
from officesuite.common import flow_event, get_obj, obj_dict
from officesuite.models import ApprovalRequest, Contract, ExpenseReport, SealApply, TravelApply

# =====================================================================
# approval 审批流（11）
# =====================================================================

APPROVAL_TEMPLATES = [
    {"key": "leave", "name": "请假申请", "fields": ["leave_type", "start_date", "end_date", "reason"]},
    {"key": "expense", "name": "费用报销", "fields": ["amount", "category", "reason"]},
    {"key": "purchase", "name": "采购申请", "fields": ["item", "qty", "budget", "reason"]},
    {"key": "overtime", "name": "加班申请", "fields": ["date", "hours", "reason"]},
    {"key": "seal", "name": "用印申请", "fields": ["doc_title", "seal_type", "copies"]},
    {"key": "travel", "name": "出差申请", "fields": ["destination", "start_date", "end_date", "reason"]},
]


@endpoint(("GET",))
def approval_templates(request):
    """审批模板目录（内置 6 类）。"""
    return ok({"templates": APPROVAL_TEMPLATES, "count": len(APPROVAL_TEMPLATES)})


@endpoint()
def approval_submit(request):
    """提交审批单。"""
    r = ApprovalRequest.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        status="pending",
        data={"type": opt_str(request, "type", "custom"),
              "detail": p(request, "detail") or {},
              "approver": opt_str(request, "approver"),
              "urgency": opt_str(request, "urgency", "normal"),
              "events": []},
        remark=opt_str(request, "remark"),
    )
    flow_event(r, "submit", request.user, "提交审批")
    r.save()
    return ok({"id": r.id, "status": r.status, "title": r.title})


@endpoint()
def approval_my_submitted(request):
    """我提交的审批单。"""
    qs = ApprovalRequest.objects.filter(owner=request.user).order_by("-created_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    return ok({"items": [obj_dict(o) for o in qs[:100]], "count": qs.count()})


@endpoint()
def approval_my_pending(request):
    """待我处理的审批单（数据范围可见 + pending）。"""
    qs = scope_queryset(ApprovalRequest.objects.filter(status="pending"), request.user).exclude(owner=request.user)
    return ok({"items": [obj_dict(o) for o in qs[:100]], "count": qs.count()})


@endpoint()
def approval_detail(request, pk):
    """审批单详情（含流转记录）。已批准单全员可见（审批透明），其余仅 owner/超管。"""
    try:
        r = ApprovalRequest.objects.get(pk=pk)
    except ApprovalRequest.DoesNotExist:
        raise ValueError("审批单不存在")
    if r.status != "approved":
        if r.owner_id != request.user.id and not request.user.is_superuser:
            raise ValueError("无权查看该审批单")
    d = obj_dict(r)
    d["events"] = (r.data or {}).get("events", [])
    return ok(d)


@endpoint()
def approval_approve(request, pk):
    """通过审批。"""
    r = get_obj(ApprovalRequest, pk, request.user, write=True)
    if r.status != "pending":
        raise ValueError(f"当前状态 {r.status} 不可审批")
    r.status = "approved"
    flow_event(r, "approve", request.user, opt_str(request, "note"))
    r.save()
    return ok({"id": r.id, "status": r.status})


@endpoint()
def approval_reject(request, pk):
    """驳回审批（必须给理由）。"""
    r = get_obj(ApprovalRequest, pk, request.user, write=True)
    if r.status != "pending":
        raise ValueError(f"当前状态 {r.status} 不可审批")
    reason = req_str(request, "reason")
    r.status = "rejected"
    flow_event(r, "reject", request.user, reason)
    r.save()
    return ok({"id": r.id, "status": r.status, "reason": reason})


@endpoint()
def approval_cancel(request, pk):
    """撤回自己的审批单。"""
    r = get_obj(ApprovalRequest, pk, request.user, write=True)
    if r.owner_id != request.user.id:
        raise ValueError("只能撤回自己提交的审批")
    if r.status != "pending":
        raise ValueError("仅待审状态可撤回")
    r.status = "cancelled"
    flow_event(r, "cancel", request.user, opt_str(request, "note"))
    r.save()
    return ok({"id": r.id, "status": r.status})


@endpoint()
def approval_comment(request, pk):
    """给审批单追加评论（不动状态）。"""
    r = get_obj(ApprovalRequest, pk, request.user, write=True)
    text = req_str(request, "text")
    flow_event(r, "comment", request.user, text)
    r.save()
    return ok({"id": r.id, "comments": len((r.data or {}).get("events", []))})


@endpoint()
def approval_events(request, pk):
    """审批流转历史。"""
    r = get_obj(ApprovalRequest, pk, request.user)
    return ok({"events": (r.data or {}).get("events", []), "count": len((r.data or {}).get("events", []))})


@endpoint()
def approval_urge(request, pk):
    """催办：给审批单打上催办标记并计数。"""
    r = get_obj(ApprovalRequest, pk, request.user, write=True)
    if r.status != "pending":
        raise ValueError("只有待审单可以催办")
    urges = int((r.data or {}).get("urge_count", 0)) + 1
    r.data = {**(r.data or {}), "urge_count": urges, "last_urge_at": timezone.now().isoformat()}
    flow_event(r, "urge", request.user, opt_str(request, "note", "请尽快处理"))
    r.save()
    return ok({"id": r.id, "urge_count": urges})


@endpoint()
def approval_stats(request):
    """审批统计：按状态/类型聚合（数据范围内）。"""
    qs = scope_queryset(ApprovalRequest.objects.all(), request.user)
    by_status = dict(qs.values_list("status").annotate(c=Count("id")))
    types = {}
    for o in qs[:500]:
        t = (o.data or {}).get("type", "custom")
        types[t] = types.get(t, 0) + 1
    return ok({"total": qs.count(), "by_status": by_status, "by_type": types,
               "pending": by_status.get("pending", 0),
               "approval_rate_pct": round((by_status.get("approved", 0) / max(sum(by_status.values()), 1)) * 100, 1)})


# =====================================================================
# seal 用印（7）
# =====================================================================


@endpoint()
def seal_apply(request):
    """提交用印申请。"""
    s = SealApply.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        seal_type=opt_str(request, "seal_type", "公章"),
        copies=int(req_num(request, "copies", 1, minimum=1, maximum=100, integer=True)),
        status="pending",
        data={"doc_type": opt_str(request, "doc_type", "合同"), "events": []},
        remark=opt_str(request, "reason"),
    )
    flow_event(s, "submit", request.user)
    s.save()
    return ok({"id": s.id, "status": s.status})


@endpoint()
def seal_mine(request):
    """我的用印申请。"""
    qs = SealApply.objects.filter(owner=request.user).order_by("-created_at")
    return ok({"items": [obj_dict(s, extra=("seal_type", "copies")) for s in qs[:100]], "count": qs.count()})


@endpoint()
def seal_approve(request, pk):
    """审批用印（通过/驳回）。"""
    s = get_obj(SealApply, pk, request.user, write=True)
    action = opt_str(request, "action", "approve")
    if s.status != "pending":
        raise ValueError("该申请已处理")
    s.status = "approved" if action == "approve" else "rejected"
    flow_event(s, s.status, request.user, opt_str(request, "note"))
    s.save()
    return ok({"id": s.id, "status": s.status})


@endpoint()
def seal_detail(request, pk):
    """用印详情。"""
    s = get_obj(SealApply, pk, request.user)
    d = obj_dict(s, extra=("seal_type", "copies"))
    d["events"] = (s.data or {}).get("events", [])
    return ok(d)


@endpoint()
def seal_log(request):
    """用印台账（数据范围内全部记录）。"""
    qs = scope_queryset(SealApply.objects.filter(status="approved"), request.user)
    return ok({"items": [obj_dict(s, extra=("seal_type", "copies")) for s in qs[:200]],
               "count": qs.count(),
               "total_copies": qs.aggregate(t=Sum("copies"))["t"] or 0})


@endpoint()
def seal_stats(request):
    """用印统计：按印章类型聚合。"""
    qs = scope_queryset(SealApply.objects.all(), request.user)
    by_type = {}
    for s in qs[:500]:
        by_type[s.seal_type] = by_type.get(s.seal_type, 0) + 1
    return ok({"total": qs.count(), "by_seal_type": by_type,
               "pending": qs.filter(status="pending").count()})


# =====================================================================
# expense 报销（8）
# =====================================================================


@endpoint()
def expense_submit(request):
    """提交报销单（含明细 items）。"""
    items = p(request, "items") or []
    if not isinstance(items, list):
        raise ValueError("items 必须是数组")
    total = sum(float(i.get("amount", 0)) for i in items if isinstance(i, dict))
    e = ExpenseReport.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        status="pending",
        total=round(total, 2),
        invoice_count=len(items),
        data={"items": items, "category": opt_str(request, "category", "日常"),
              "events": []},
        remark=opt_str(request, "remark"),
    )
    flow_event(e, "submit", request.user, f"共 {len(items)} 笔，合计 ¥{total:.2f}")
    e.save()
    return ok({"id": e.id, "total": str(e.total), "status": e.status, "items": len(items)})


@endpoint()
def expense_mine(request):
    """我的报销单。"""
    qs = ExpenseReport.objects.filter(owner=request.user).order_by("-created_at")
    return ok({"items": [obj_dict(e, extra=("total", "invoice_count")) for e in qs[:100]],
               "count": qs.count(),
               "sum_total": str(qs.aggregate(t=Sum("total"))["t"] or 0)})


@endpoint()
def expense_detail(request, pk):
    """报销单详情（含明细与流转）。"""
    e = get_obj(ExpenseReport, pk, request.user)
    d = obj_dict(e, extra=("total", "invoice_count"))
    d["items"] = (e.data or {}).get("items", [])
    d["events"] = (e.data or {}).get("events", [])
    return ok(d)


@endpoint()
def expense_approve(request, pk):
    """审批通过（主管环节）。"""
    e = get_obj(ExpenseReport, pk, request.user, write=True)
    if e.status != "pending":
        raise ValueError("该报销单不在待审状态")
    e.status = "approved"
    flow_event(e, "approve", request.user, opt_str(request, "note"))
    e.save()
    return ok({"id": e.id, "status": e.status})


@endpoint()
def expense_reject(request, pk):
    """驳回报销（必填理由）。"""
    e = get_obj(ExpenseReport, pk, request.user, write=True)
    if e.status != "pending":
        raise ValueError("该报销单不在待审状态")
    reason = req_str(request, "reason")
    e.status = "rejected"
    flow_event(e, "reject", request.user, reason)
    e.save()
    return ok({"id": e.id, "status": e.status})


@endpoint()
def expense_pay(request, pk):
    """财务打款（approved → paid）。"""
    e = get_obj(ExpenseReport, pk, request.user, write=True)
    if e.status != "approved":
        raise ValueError("仅审批通过的报销单可打款")
    e.status = "paid"
    flow_event(e, "pay", request.user, f"打款 ¥{e.total}")
    e.save()
    return ok({"id": e.id, "status": e.status, "amount": str(e.total)})


@endpoint()
def expense_stats(request):
    """报销统计：状态分布 + 类别金额。"""
    qs = scope_queryset(ExpenseReport.objects.all(), request.user)
    by_status = dict(qs.values_list("status").annotate(c=Count("id")))
    by_cat = {}
    for e in qs[:500]:
        cat = (e.data or {}).get("category", "日常")
        by_cat[cat] = round(by_cat.get(cat, 0) + float(e.total), 2)
    return ok({"total_count": qs.count(), "by_status": by_status, "amount_by_category": by_cat,
               "total_amount": str(qs.aggregate(t=Sum("total"))["t"] or 0),
               "pending_amount": str(qs.filter(status="pending").aggregate(t=Sum("total"))["t"] or 0)})


@endpoint()
def expense_export(request):
    """报销单导出 CSV（数据范围内，内存导出）。"""
    qs = scope_queryset(ExpenseReport.objects.all(), request.user).order_by("-created_at")[:500]
    lines = ["id,title,owner,total,status,created_at"]
    for e in qs:
        title = f'"{e.title}"' if ("," in e.title or '"' in e.title) else e.title
        lines.append(f"{e.id},{title},{e.owner.username},{e.total},{e.status},{e.created_at:%Y-%m-%d %H:%M}")
    return ok({"csv": "\n".join(lines), "rows": len(lines) - 1})


# =====================================================================
# travel 差旅（7）
# =====================================================================


@endpoint()
def travel_apply(request):
    """提交差旅申请。"""
    from django.utils.dateparse import parse_date

    t = TravelApply.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        destination=opt_str(request, "destination"),
        start_date=parse_date(opt_str(request, "start_date")) if opt_str(request, "start_date") else None,
        end_date=parse_date(opt_str(request, "end_date")) if opt_str(request, "end_date") else None,
        estimate=round(float(opt_num(request, "estimate", 0) or 0), 2),
        status="pending",
        data={"companions": p(request, "companions") or [], "events": []},
        remark=opt_str(request, "reason"),
    )
    flow_event(t, "submit", request.user)
    t.save()
    return ok({"id": t.id, "status": t.status})


@endpoint()
def travel_mine(request):
    """我的差旅申请。"""
    qs = TravelApply.objects.filter(owner=request.user).order_by("-created_at")
    return ok({"items": [obj_dict(t, extra=("destination", "start_date", "end_date", "estimate")) for t in qs[:100]],
               "count": qs.count()})


@endpoint()
def travel_detail(request, pk):
    """差旅详情。"""
    t = get_obj(TravelApply, pk, request.user)
    d = obj_dict(t, extra=("destination", "start_date", "end_date", "estimate"))
    d["events"] = (t.data or {}).get("events", [])
    return ok(d)


@endpoint()
def travel_approve(request, pk):
    """审批差旅（通过/驳回）。"""
    t = get_obj(TravelApply, pk, request.user, write=True)
    action = opt_str(request, "action", "approve")
    if t.status != "pending":
        raise ValueError("该申请已处理")
    t.status = "approved" if action == "approve" else "rejected"
    flow_event(t, t.status, request.user, opt_str(request, "note"))
    t.save()
    return ok({"id": t.id, "status": t.status})


@endpoint()
def travel_cancel(request, pk):
    """取消自己的差旅申请。"""
    t = get_obj(TravelApply, pk, request.user, write=True)
    if t.owner_id != request.user.id:
        raise ValueError("只能取消自己的申请")
    if t.status not in ("pending", "approved"):
        raise ValueError("当前状态不可取消")
    t.status = "cancelled"
    flow_event(t, "cancel", request.user, opt_str(request, "note"))
    t.save()
    return ok({"id": t.id, "status": t.status})


@endpoint()
def travel_list_all(request):
    """团队差旅台账（数据范围）。"""
    qs = scope_queryset(TravelApply.objects.all(), request.user).order_by("-created_at")
    return ok({"items": [obj_dict(t, extra=("destination", "start_date", "end_date", "estimate")) for t in qs[:200]],
               "count": qs.count()})


@endpoint()
def travel_stats(request):
    """差旅统计：目的地 TOP + 预算汇总。"""
    qs = scope_queryset(TravelApply.objects.all(), request.user)
    dests = {}
    for t in qs[:500]:
        if t.destination:
            dests[t.destination] = dests.get(t.destination, 0) + 1
    top = sorted(dests.items(), key=lambda kv: -kv[1])[:10]
    return ok({"total": qs.count(), "pending": qs.filter(status="pending").count(),
               "top_destinations": [{"destination": d, "count": c} for d, c in top],
               "total_estimate": str(qs.aggregate(t=Sum("estimate"))["t"] or 0)})


# =====================================================================
# contract 合同（8）
# =====================================================================


@endpoint()
def contract_create(request):
    """登记合同。"""
    from django.utils.dateparse import parse_date

    c = Contract.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        party=opt_str(request, "party"),
        amount=round(float(opt_num(request, "amount", 0) or 0), 2),
        sign_date=parse_date(opt_str(request, "sign_date")) if opt_str(request, "sign_date") else None,
        expire_date=parse_date(opt_str(request, "expire_date")) if opt_str(request, "expire_date") else None,
        status="active",
        data={"type": opt_str(request, "type", "采购"), "owner_contact": opt_str(request, "contact"),
              "payments": p(request, "payments") or []},
        remark=opt_str(request, "remark"),
    )
    return ok({"id": c.id, "status": c.status})


@endpoint()
def contract_list(request):
    """合同列表（数据范围 + 状态筛选）。"""
    qs = scope_queryset(Contract.objects.all(), request.user).order_by("-created_at")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    return ok({"items": [obj_dict(c, extra=("party", "amount", "sign_date", "expire_date")) for c in qs[:200]],
               "count": qs.count()})


@endpoint()
def contract_detail(request, pk):
    """合同详情（含回款计划）。"""
    c = get_obj(Contract, pk, request.user)
    d = obj_dict(c, extra=("party", "amount", "sign_date", "expire_date"))
    d["payments"] = (c.data or {}).get("payments", [])
    d["type"] = (c.data or {}).get("type", "采购")
    return ok(d)


@endpoint()
def contract_update_status(request, pk):
    """更新合同状态（active/fulfilled/terminated/expired）。"""
    c = get_obj(Contract, pk, request.user, write=True)
    status = req_str(request, "status")
    if status not in ("active", "fulfilled", "terminated", "expired"):
        raise ValueError("status 支持 active/fulfilled/terminated/expired")
    c.status = status
    flow_event(c, "status", request.user, f"→ {status}")
    c.save()
    return ok({"id": c.id, "status": c.status})


@endpoint()
def contract_expiring(request):
    """临期合同提醒：N 天内到期列表。"""
    days = int(opt_num(request, "days", 30, minimum=1, maximum=365) or 30)
    qs = scope_queryset(Contract.objects.filter(status="active"), request.user)
    now = timezone.now().date()
    expiring = []
    for c in qs:
        if c.expire_date:
            left = (c.expire_date - now).days
            if 0 <= left <= days:
                expiring.append({**obj_dict(c, extra=("party", "expire_date")), "days_left": left})
    expiring.sort(key=lambda x: x["days_left"])
    return ok({"items": expiring, "count": len(expiring), "within_days": days})


@endpoint()
def contract_stats(request):
    """合同统计：金额/状态/年度分布。"""
    qs = scope_queryset(Contract.objects.all(), request.user)
    by_status = dict(qs.values_list("status").annotate(c=Count("id")))
    years = {}
    for c in qs:
        y = c.sign_date.year if c.sign_date else None
        if y:
            years[str(y)] = round(years.get(str(y), 0) + float(c.amount), 2)
    return ok({"count": qs.count(), "by_status": by_status,
               "amount_by_year": years,
               "total_amount": str(qs.aggregate(t=Sum("amount"))["t"] or 0)})


@endpoint()
def contract_payments(request, pk):
    """回款计划维护（整体替换或追加）。"""
    c = get_obj(Contract, pk, request.user, write=True)
    mode = opt_str(request, "mode", "append")
    incoming = p(request, "payments")
    if not isinstance(incoming, list):
        raise ValueError("payments 必须是数组")
    payments = (c.data or {}).get("payments", [])
    payments = incoming if mode == "replace" else payments + incoming
    c.data = {**(c.data or {}), "payments": payments[-200:]}
    flow_event(c, "payments", request.user, f"{mode} {len(incoming)} 条")
    c.save()
    total_planned = sum(float(x.get("amount", 0)) for x in payments if isinstance(x, dict))
    return ok({"id": c.id, "payments": c.data["payments"], "count": len(payments),
               "total_planned": round(total_planned, 2)})


@endpoint()
def contract_delete(request, pk):
    """删除合同（仅所有者）。"""
    c = get_obj(Contract, pk, request.user, write=True)
    if c.owner_id != request.user.id:
        raise ValueError("仅合同创建人可删除")
    cid, title = c.id, c.title
    c.delete()
    return ok({"deleted": True, "id": cid, "title": title})


FLOW_FAMILY_COUNT = 11 + 7 + 8 + 7 + 8  # = 41
