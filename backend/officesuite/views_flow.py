# -*- coding: utf-8 -*-
"""officesuite · 审批流面接口：approval(13) seal(6) expense(8) travel(7) contract(8) = 42 个。

审批类统一状态机：pending → approved / rejected / cancelled，流转写入 data.events。
审批权 = 数据范围可见者（core.scoping），超管天然可见。
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from core.scoping import is_visible, scope_queryset

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req, req_num, req_str)
from officesuite.common import (can_write_obj, flow_event, get_obj, obj_dict,
                                parse_dt)
from officesuite.models import ApprovalRequest, Contract, ExpenseReport, SealApply, TravelApply


def _money(value, field="金额"):
    """把入参安全转成 Decimal，并要求为正数（#64）。"""
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} 必须是数字")
    if not d.is_finite() or d <= 0:
        raise ValueError(f"{field} 必须大于 0")
    return d


def _locked_obj(model, pk, user):
    """#64/#65：事务内取行锁对象，并做对象级写权限校验。

    必须在 `transaction.atomic()` 内调用，锁才会覆盖后续读改写；
    状态机校验（pending 才能流转）仍由各视图在锁内完成。
    写权限沿用 can_write_obj（含 #41 的 approver_id 身份判定），
    与 approval_approve 保持一致：指名审批人即便不在数据范围也可流转。
    """
    try:
        o = model.objects.select_for_update().get(pk=pk)
    except model.DoesNotExist:
        raise ValueError("对象不存在")
    if not can_write_obj(user, o):
        raise ValueError("无权修改该对象")
    return o


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
    from accounts.models import User

    approver_name = opt_str(request, "approver").strip()
    approver_id = opt_num(request, "approver_id")
    if not approver_id and approver_name:
        u = User.objects.filter(Q(username=approver_name) | Q(nickname=approver_name)).first()
        approver_id = u.id if u else None
    r = ApprovalRequest.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        status="pending",
        data={"type": opt_str(request, "type", "custom"),
              "detail": p(request, "detail") or {},
              "approver": approver_name,
              "approver_id": int(approver_id) if approver_id else None,
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
    """审批单详情（含流转记录）。

    #41：先做数据范围可见性判定，再放行审批人/所有者/管理员；
    已批准单不再对任意登录用户开放明细。
    """
    try:
        r = ApprovalRequest.objects.get(pk=pk)
    except ApprovalRequest.DoesNotExist:
        raise ValueError("审批单不存在")
    if not (is_visible(r, request.user) or can_write_obj(request.user, r)):
        raise ValueError("无权查看该审批单")
    d = obj_dict(r)
    d["events"] = (r.data or {}).get("events", [])
    return ok(d)


@endpoint()
def approval_approve(request, pk):
    """通过审批（#51：行锁 + 事务，状态与事件原子写入，防并发覆盖）。"""
    with transaction.atomic():
        try:
            r = ApprovalRequest.objects.select_for_update().get(pk=pk)
        except ApprovalRequest.DoesNotExist:
            raise ValueError("审批单不存在")
        if not can_write_obj(request.user, r):
            raise ValueError("无权修改该对象")
        if r.owner_id == request.user.id and not request.user.is_superuser:
            raise ValueError("不能审批自己提交的单据")
        if r.status != "pending":
            raise ValueError(f"当前状态 {r.status} 不可审批")
        r.status = "approved"
        flow_event(r, "approve", request.user, opt_str(request, "note"))
        r.save()
    return ok({"id": r.id, "status": r.status})


@endpoint()
def approval_reject(request, pk):
    """驳回审批（必须给理由；#64 行锁 + 事务，防与 approve 并发双写）。"""
    with transaction.atomic():
        r = _locked_obj(ApprovalRequest, pk, request.user)
        if r.owner_id == request.user.id and not request.user.is_superuser:
            raise ValueError("不能驳回自己提交的单据")
        if r.status != "pending":
            raise ValueError(f"当前状态 {r.status} 不可审批")
        reason = req_str(request, "reason")
        r.status = "rejected"
        flow_event(r, "reject", request.user, reason)
        r.save()
    return ok({"id": r.id, "status": r.status, "reason": reason})


@endpoint()
def approval_cancel(request, pk):
    """撤回自己的审批单（#64 行锁 + 事务）。"""
    with transaction.atomic():
        r = _locked_obj(ApprovalRequest, pk, request.user)
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
    """催办：给审批单打上催办标记并计数（#64 行锁 + 事务，防计数与事件丢失）。"""
    with transaction.atomic():
        r = _locked_obj(ApprovalRequest, pk, request.user)
        if r.status != "pending":
            raise ValueError("只有待审单可以催办")
        urges = int((r.data or {}).get("urge_count", 0)) + 1
        r.data = {**(r.data or {}), "urge_count": urges,
                  "last_urge_at": timezone.now().isoformat()}
        flow_event(r, "urge", request.user, opt_str(request, "note", "请尽快处理"))
        r.save()
    return ok({"id": r.id, "urge_count": urges})


@endpoint()
def approval_overdue_check(request):
    """S26-362 审批超时扫描：超时 pending 单通知当前审批人并写 flow_event("overdue")。

    hours 窗口内已写过 overdue 事件的单据跳过通知（重复扫描不轰炸）。
    """
    hours = int(opt_num(request, "hours", 24, integer=True, minimum=1,
                        maximum=24 * 30))
    cutoff = timezone.now() - timedelta(hours=hours)
    now = timezone.now()
    from accounts.models import User
    from core.notify import dispatch

    qs = scope_queryset(
        ApprovalRequest.objects.filter(status="pending", created_at__lt=cutoff),
        request.user,
    ).order_by("created_at")
    total = qs.count()
    overdue = notified = skipped = 0
    items = []
    for r in qs[:500]:
        data = r.data or {}
        target = None
        approver_id = data.get("approver_id")
        if approver_id:
            try:
                target = User.objects.filter(pk=int(approver_id)).first()
            except (TypeError, ValueError):
                target = None
        if target is None and data.get("approver"):
            target = User.objects.filter(
                Q(username=data["approver"]) | Q(nickname=data["approver"])).first()
        overdue += 1
        last = None
        for ev in reversed(data.get("events") or []):
            if ev.get("action") == "overdue":
                try:
                    last = parse_dt(ev.get("at"))
                except (TypeError, ValueError):
                    last = None
                break
        if last and (now - last) < timedelta(hours=hours):
            skipped += 1
            items.append({"id": r.id, "title": r.title,
                          "approver": target.username if target else data.get("approver", ""),
                          "hours_waiting": round((now - r.created_at).total_seconds() / 3600, 1),
                          "notified": False, "skipped": True})
            continue
        flow_event(r, "overdue", request.user, f"超时 {hours} 小时未处理")
        r.save(update_fields=["data", "updated_at"])
        sent = False
        if target is not None:
            sent = dispatch(
                target, f"审批超时提醒：{r.title}",
                f"该审批单已等待超过 {hours} 小时，请尽快处理。",
                category="system", level="warning", link="/officesuite/approvals",
            ) is not None
            notified += 1 if sent else 0
        items.append({"id": r.id, "title": r.title,
                      "approver": target.username if target else data.get("approver", ""),
                      "hours_waiting": round((now - r.created_at).total_seconds() / 3600, 1),
                      "notified": sent, "skipped": False})
    return ok({"hours": hours, "scanned": total, "overdue": overdue,
               "notified": notified, "skipped": skipped, "items": items})


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
    """审批用印（通过/驳回；#65 行锁 + 事务 + pending 校验，防重复流转）。"""
    action = opt_str(request, "action", "approve")
    with transaction.atomic():
        s = _locked_obj(SealApply, pk, request.user)
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
    """提交报销单（含明细 items；#64 金额用 Decimal 累加，逐笔校验 > 0）。"""
    items = p(request, "items") or []
    if not isinstance(items, list):
        raise ValueError("items 必须是数组")
    total = Decimal("0")
    for i in items:
        if not isinstance(i, dict):
            continue
        total += _money(i.get("amount"), "明细金额")
    e = ExpenseReport.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        status="pending",
        total=total,
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
    """报销统计：状态分布 + 类别金额（#87：数据库按类别聚合，不再截断 500 条）。"""
    qs = scope_queryset(ExpenseReport.objects.all(), request.user)
    by_status = dict(qs.values_list("status").annotate(c=Count("id")))
    by_cat = {}
    rows = (qs.values("data__category")
            .annotate(amount=Sum("total")).order_by())
    for row in rows:
        cat = row["data__category"] or "日常"
        by_cat[str(cat)] = round(float(row["amount"] or 0), 2)
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
    """登记合同（#64：金额 Decimal 存储，传了金额就必须 > 0）。"""
    from django.utils.dateparse import parse_date

    amount_raw = p(request, "amount")
    amount = Decimal("0") if amount_raw in (None, "") else _money(amount_raw, "amount")
    c = Contract.objects.create(
        owner=request.user,
        title=req_str(request, "title")[:200],
        party=opt_str(request, "party"),
        amount=amount,
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
    """回款计划维护（整体替换或追加；#64 金额 Decimal 累加并校验 > 0）。"""
    c = get_obj(Contract, pk, request.user, write=True)
    mode = opt_str(request, "mode", "append")
    incoming = p(request, "payments")
    if not isinstance(incoming, list):
        raise ValueError("payments 必须是数组")
    for x in incoming:
        if isinstance(x, dict):
            _money(x.get("amount"), "回款金额")
    payments = (c.data or {}).get("payments", [])
    payments = incoming if mode == "replace" else payments + incoming
    c.data = {**(c.data or {}), "payments": payments[-200:]}
    flow_event(c, "payments", request.user, f"{mode} {len(incoming)} 条")
    c.save()
    total_planned = Decimal("0")
    for x in payments:
        if isinstance(x, dict) and x.get("amount") not in (None, ""):
            try:
                total_planned += Decimal(str(x.get("amount")))
            except (InvalidOperation, TypeError, ValueError):
                continue
    return ok({"id": c.id, "payments": c.data["payments"], "count": len(payments),
               "total_planned": round(float(total_planned), 2)})


@endpoint()
def contract_delete(request, pk):
    """删除合同（仅所有者）。"""
    c = get_obj(Contract, pk, request.user, write=True)
    if c.owner_id != request.user.id:
        raise ValueError("仅合同创建人可删除")
    cid, title = c.id, c.title
    c.delete()
    return ok({"deleted": True, "id": cid, "title": title})


FLOW_FAMILY_COUNT = 13 + 6 + 8 + 7 + 8  # = 42（S26：approval +1 审批超时扫描）
