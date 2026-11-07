# -*- coding: utf-8 -*-
"""contracts · 履约执行接口（21 个）：义务 / 事件 / 排期 / 里程碑 / 变更单 / 审批节点。

履约是合同生命周期里唯一「高频写入」的部分，因此：
- 义务状态只允许 pending/doing/done/overdue/waived，人工动作必须写 ObligationEvent；
- 逾期由服务层扫描（系统判定）而不是人工点，人工点只会得到「没人点就永远不逾期」；
- 排期生成幂等，前端重复点击不会产生重复期次（唯一约束兜底）。
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.scoping import can_write, is_visible, scope_queryset
from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)
from contracts import services, state
from contracts.common import (amendment_dict, approval_dict, dec,
                              get_contract, has, iso, milestone_dict,
                              obligation_dict, obligation_event_dict,
                              page_args, page_payload, parse_day)
from contracts.models import (AMENDMENT_TYPES, MILESTONE_STATUS,
                              OBLIGATION_CYCLES, OBLIGATION_STATUS,
                              Contract, ContractAmendment, ContractApproval,
                              ContractMilestone, ContractObligation,
                              ContractParty, ObligationEvent, to_decimal)


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------


def _obligation(user, pk, write=False):
    """取义务并校验所属合同权限；写操作要求合同 owner。"""
    row = ContractObligation.objects.select_related("contract", "party").filter(pk=pk).first()
    if row is None:
        raise ValueError("履约义务不存在")
    if not is_visible(row.contract, user):
        raise ValueError("无权访问该合同")
    if write and not can_write(user, row.contract):
        raise ValueError("无权修改该合同")
    return row


def _resolve_party(contract, value):
    """按 party_id 解析义务方：必须属于本合同，防止跨合同引用主体。"""
    if value in (None, ""):
        return None
    try:
        party_id = int(value)
    except (TypeError, ValueError):
        raise ValueError("party_id 必须是整数")
    party = ContractParty.objects.filter(pk=party_id, contract=contract).first()
    if party is None:
        raise ValueError("义务方不存在或不属于该合同")
    return party


def _event(row, action, user, note="", evidence="", from_due=None, to_due=None):
    """写履约事件：所有人工动作都必须留痕，否则「谁在什么时候改的」无从回溯。"""
    return ObligationEvent.objects.create(
        owner=user if getattr(user, "pk", None) else row.owner,
        obligation=row,
        action=action,
        note=note or "",
        evidence=evidence or "",
        actor=user if getattr(user, "pk", None) else None,
        from_due_date=from_due,
        to_due_date=to_due,
    )


# ---------------------------------------------------------------------------
# 义务
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def obligations_list(request, pk):
    """某合同的义务列表（可选 status / cycle / 仅逾期）。"""
    contract = get_contract(request.user, pk)
    rows = contract.obligations.select_related("party", "responsible").all()
    status = opt_str(request, "status")
    if status:
        rows = rows.filter(status=status)
    cycle = opt_str(request, "cycle")
    if cycle:
        rows = rows.filter(cycle=cycle)
    only_overdue = opt_bool(request, "overdue", False)
    today = timezone.localdate()
    data = [obligation_dict(row, today) for row in rows]
    if only_overdue:
        data = [row for row in data if row["is_overdue"]]
    return ok({"items": data, "count": len(data),
               "summary": _obligation_summary(contract, today)})


def _obligation_summary(contract, today=None):
    """义务汇总：按状态计数 + 未来 7/30 天到期数，工作台角标直接取。"""
    today = today or timezone.localdate()
    rows = list(contract.obligations.all())
    by_status = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
    due_7 = sum(1 for row in rows if row.due_date and
                0 <= (row.due_date - today).days <= 7
                and row.status not in ("done", "waived"))
    due_30 = sum(1 for row in rows if row.due_date and
                 0 <= (row.due_date - today).days <= 30
                 and row.status not in ("done", "waived"))
    overdue = sum(1 for row in rows if row.is_overdue(today))
    return {"total": len(rows), "by_status": by_status, "due_in_7_days": due_7,
            "due_in_30_days": due_30, "overdue": overdue}


@endpoint(("GET",))
def obligations_all(request):
    """跨合同义务清单（数据范围内，支持 status/cycle/负责人/到期区间）。"""
    contracts = scope_queryset(Contract.objects.all(), request.user)
    qs = ContractObligation.objects.filter(contract__in=contracts).select_related(
        "contract", "party", "responsible")
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    cycle = opt_str(request, "cycle")
    if cycle:
        qs = qs.filter(cycle=cycle)
    contract_id = opt_num(request, "contract_id", None, integer=True, minimum=1)
    if contract_id:
        qs = qs.filter(contract_id=int(contract_id))
    responsible_id = opt_num(request, "responsible_id", None, integer=True, minimum=1)
    if responsible_id:
        qs = qs.filter(responsible_id=int(responsible_id))
    q = opt_str(request, "q")
    if q:
        qs = qs.filter(Q(content__icontains=q) | Q(party_name__icontains=q))
    due_before = parse_day(p(request, "due_before"))
    if due_before:
        qs = qs.filter(due_date__lte=due_before)
    due_after = parse_day(p(request, "due_after"))
    if due_after:
        qs = qs.filter(due_date__gte=due_after)
    if opt_bool(request, "overdue", False):
        qs = qs.filter(due_date__lt=timezone.localdate(),
                       status__in=("pending", "doing"))
    qs = qs.order_by("due_date", "id")
    page, size = page_args(request)
    total = qs.count()
    start = (page - 1) * size
    rows = list(qs[start:start + size])
    today = timezone.localdate()
    return ok(page_payload([{**obligation_dict(row, today),
                             "contract_number": row.contract.number,
                             "contract_name": row.contract.name}
                            for row in rows], total, page, size))


@endpoint()
def obligation_create(request, pk):
    """新增履约义务（周期义务自动生成 series_uid，供后续幂等展开）。"""
    contract = get_contract(request.user, pk, write=True)
    cycle = opt_str(request, "cycle", "once")
    if cycle not in OBLIGATION_CYCLES:
        raise ValueError(f"履约周期不支持: {cycle}")
    party = _resolve_party(contract, p(request, "party_id"))
    due_date = parse_day(p(request, "due_date"))
    if cycle != "once" and not due_date:
        raise ValueError("周期义务必须填写首个截止日")
    row = ContractObligation.objects.create(
        owner=request.user,
        contract=contract,
        party=party,
        party_name=opt_str(request, "party_name",
                           party.name if party else "", max_len=200),
        content=req_str(request, "content", max_len=0),
        trigger=opt_str(request, "trigger", max_len=200),
        cycle=cycle,
        due_date=due_date,
        responsible_id=(int(req_num(request, "responsible_id", None, integer=True,
                                    minimum=1))
                        if has(request, "responsible_id") else None),
        responsible_name=opt_str(request, "responsible_name", max_len=60),
        status="pending",
        priority=opt_str(request, "priority", "normal", max_len=16),
        series_uid=services.gen_series_uid("series"),
        remark=opt_str(request, "remark", max_len=0),
    )
    state.log_transition(contract, "obligation", request.user,
                         f"新增义务 #{row.id}", contract.status, contract.status,
                         {"obligation_id": row.id})
    return ok(obligation_dict(row))


@endpoint()
def obligation_update(request, pk):
    """更新义务内容/截止日/责任人（已完成/已豁免的义务不可改）。"""
    row = _obligation(request.user, pk, write=True)
    if row.status in ("done", "waived"):
        raise ValueError("已完成或已豁免的义务不可修改")
    if has(request, "content"):
        row.content = req_str(request, "content", max_len=0)
    if has(request, "trigger"):
        row.trigger = opt_str(request, "trigger", max_len=200)
    if has(request, "cycle"):
        cycle = opt_str(request, "cycle", row.cycle)
        if cycle not in OBLIGATION_CYCLES:
            raise ValueError(f"履约周期不支持: {cycle}")
        row.cycle = cycle
    if has(request, "due_date"):
        row.due_date = parse_day(p(request, "due_date"))
    if has(request, "party_id"):
        party = _resolve_party(row.contract, p(request, "party_id"))
        row.party = party
        row.party_name = party.name if party else row.party_name
    if has(request, "responsible_id"):
        row.responsible_id = int(req_num(request, "responsible_id", None,
                                         integer=True, minimum=1))
    if has(request, "priority"):
        row.priority = opt_str(request, "priority", row.priority, max_len=16)
    if has(request, "remark"):
        row.remark = opt_str(request, "remark", max_len=0)
    if has(request, "status"):
        status = opt_str(request, "status", row.status)
        if status not in OBLIGATION_STATUS:
            raise ValueError(f"义务状态不支持: {status}")
        # 状态变更走人工动作接口（complete/postpone/waive），这里只允许 pending/doing 互转
        if status not in ("pending", "doing"):
            raise ValueError("请使用完成/延期/豁免接口变更该状态")
        row.status = status
    row.touch()
    row.save()
    return ok(obligation_dict(row))


@endpoint()
def obligation_delete(request, pk):
    """删除义务（仅未开始/履行中可删；已完成义务是履约证据，不允许删）。"""
    row = _obligation(request.user, pk, write=True)
    if row.status in ("done", "overdue"):
        raise ValueError("已完成或已逾期的义务不能删除")
    if row.generated.exists():
        raise ValueError("该义务已生成后续排期，请先删除子期次")
    row_id = row.id
    with transaction.atomic():
        row.delete()
    return ok({"deleted": True, "id": row_id})


@endpoint()
def obligation_complete(request, pk):
    """完成义务：写完成事件（证据/说明），状态置为 done。"""
    with transaction.atomic():
        row = _obligation(request.user, pk, write=True)
        if row.status == "done":
            raise ValueError("该义务已完成")
        if row.status == "waived":
            raise ValueError("该义务已豁免，不能标记完成")
        note = opt_str(request, "note", "已完成", max_len=0)
        evidence = opt_str(request, "evidence", max_len=300)
        row.mark_status("done")
        _event(row, "complete", request.user, note, evidence,
               from_due=row.due_date, to_due=row.due_date)
        state.log_transition(row.contract, "obligation", request.user,
                             f"完成义务 #{row.id}", row.contract.status,
                             row.contract.status, {"obligation_id": row.id})
    return ok(obligation_dict(row))


@endpoint()
def obligation_postpone(request, pk):
    """延期义务：新截止日必须晚于原截止日，状态回到 pending 并留延期事件。"""
    new_due = parse_day(p(request, "due_date") or p(request, "new_due_date"),
                        "新截止日", required=True)
    with transaction.atomic():
        row = _obligation(request.user, pk, write=True)
        if row.status in ("done", "waived"):
            raise ValueError("已完成或已豁免的义务不能延期")
        if row.due_date and new_due <= row.due_date:
            raise ValueError("新截止日必须晚于原截止日")
        old_due = row.due_date
        row.due_date = new_due
        row.status = "pending"
        row.touch()
        row.save(update_fields=["due_date", "status", "updated_at"])
        _event(row, "postpone", request.user,
               opt_str(request, "note", "延期", max_len=0),
               opt_str(request, "evidence", max_len=300),
               from_due=old_due, to_due=new_due)
    return ok(obligation_dict(row))


@endpoint()
def obligation_waive(request, pk):
    """豁免义务（必须给原因；豁免后不再计入逾期与健康度扣分）。"""
    reason = req_str(request, "reason", max_len=0)
    with transaction.atomic():
        row = _obligation(request.user, pk, write=True)
        if row.status == "waived":
            raise ValueError("该义务已豁免")
        if row.status == "done":
            raise ValueError("已完成的义务无需豁免")
        row.mark_status("waived")
        _event(row, "waive", request.user, reason,
               opt_str(request, "evidence", max_len=300))
    return ok(obligation_dict(row))


@endpoint()
def obligation_schedule(request, pk):
    """为周期义务生成未来 N 期排期（幂等：重复调用只新增缺失期次）。"""
    row = _obligation(request.user, pk, write=True)
    if row.cycle == "once":
        raise ValueError("一次性义务不能生成排期")
    periods = int(opt_num(request, "periods", 4, minimum=1, maximum=60, integer=True))
    start = parse_day(p(request, "start_date"))
    with transaction.atomic():
        created, skipped = services.generate_obligation_schedule(
            row.contract, periods=periods, start_date=start or row.due_date,
            user=request.user)
    mine = [item for item in created if item.recurring_from_id == row.id]
    return ok({
        "obligation_id": row.id,
        "periods": periods,
        "created": len(mine),
        "created_all": len(created),
        "skipped": skipped,
        "items": [obligation_dict(item) for item in mine],
    })


@endpoint(("GET",))
def obligations_overdue(request):
    """逾期义务清单（先扫描置逾期再返回，保证列表与真实状态一致）。"""
    contracts = scope_queryset(Contract.objects.all(), request.user)
    changed = 0
    today = timezone.localdate()
    for contract in contracts.exclude(status__in=("archived", "terminated",
                                                  "completed", "draft")):
        changed += len(services.sweep_overdue_obligations(contract, request.user,
                                                          today))
    rows = (ContractObligation.objects
            .filter(contract__in=contracts, status="overdue")
            .select_related("contract", "party", "responsible")
            .order_by("due_date"))
    items = []
    for row in rows[:500]:
        data = obligation_dict(row, today)
        data["contract_number"] = row.contract.number
        data["contract_name"] = row.contract.name
        data["overdue_days"] = (today - row.due_date).days if row.due_date else 0
        items.append(data)
    items.sort(key=lambda item: -item["overdue_days"])
    return ok({"items": items, "count": len(items), "swept": changed})


@endpoint(("GET",))
def obligation_events(request, pk):
    """义务事件时间线（完成/延期/豁免/重开）。"""
    row = _obligation(request.user, pk)
    items = [obligation_event_dict(event) for event in
             row.events.select_related("actor").all()[:200]]
    return ok({"obligation_id": row.id, "items": items, "count": len(items)})


# ---------------------------------------------------------------------------
# 里程碑
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def milestones_list(request, pk):
    """里程碑列表（含达成率与延期标记）。"""
    contract = get_contract(request.user, pk)
    rows = contract.milestones.all()
    items = [milestone_dict(row) for row in rows]
    achieved = sum(1 for row in rows if row.status == "achieved")
    return ok({"items": items, "count": len(items), "achieved": achieved,
               "achievement_rate": round(achieved * 100.0 / len(items), 1)
               if items else 0.0})


@endpoint()
def milestone_create(request, pk):
    """新增里程碑（计划日期必填，金额可空）。"""
    contract = get_contract(request.user, pk, write=True)
    plan_date = parse_day(p(request, "plan_date"), "计划日期", required=True)
    if contract.effective_date and plan_date < contract.effective_date:
        raise ValueError("里程碑计划日期不能早于合同生效日")
    row = ContractMilestone.objects.create(
        owner=request.user,
        contract=contract,
        name=req_str(request, "name", max_len=200),
        plan_date=plan_date,
        status="planned",
        amount=dec(p(request, "amount"), "里程碑金额", minimum="0"),
        remark=opt_str(request, "remark", max_len=0),
    )
    return ok(milestone_dict(row))


@endpoint()
def milestone_update(request, pk):
    """更新里程碑（达成后不允许再改计划日期，防止事后修改考核口径）。"""
    row = ContractMilestone.objects.select_related("contract").filter(pk=pk).first()
    if row is None:
        raise ValueError("里程碑不存在")
    if not can_write(request.user, row.contract):
        raise ValueError("无权修改该合同")
    if has(request, "name"):
        row.name = req_str(request, "name", max_len=200)
    if has(request, "plan_date"):
        if row.status == "achieved":
            raise ValueError("已达成里程碑不能修改计划日期")
        row.plan_date = parse_day(p(request, "plan_date"))
    if has(request, "amount"):
        row.amount = dec(p(request, "amount"), "里程碑金额", minimum="0")
    if has(request, "remark"):
        row.remark = opt_str(request, "remark", max_len=0)
    if has(request, "status"):
        status = opt_str(request, "status", row.status)
        if status not in MILESTONE_STATUS:
            raise ValueError(f"里程碑状态不支持: {status}")
        if status == "achieved" and not row.actual_date:
            row.actual_date = timezone.localdate()
        row.status = status
    row.touch()
    row.save()
    return ok(milestone_dict(row))


@endpoint()
def milestone_complete(request, pk):
    """完成里程碑（实际日期缺省今天；晚于计划日自动标记延期）。"""
    with transaction.atomic():
        row = ContractMilestone.objects.select_related("contract").filter(pk=pk).first()
        if row is None:
            raise ValueError("里程碑不存在")
        if not can_write(request.user, row.contract):
            raise ValueError("无权修改该合同")
        if row.status == "achieved":
            raise ValueError("该里程碑已达成")
        actual = parse_day(p(request, "actual_date")) or timezone.localdate()
        row.actual_date = actual
        row.status = "achieved"
        row.remark = opt_str(request, "remark", row.remark, max_len=0)
        row.touch()
        row.save(update_fields=["actual_date", "status", "remark", "updated_at"])
        state.log_transition(row.contract, "obligation", request.user,
                             f"里程碑达成：{row.name}", row.contract.status,
                             row.contract.status, {"milestone_id": row.id})
    return ok({**milestone_dict(row),
               "on_time": not row.is_late(),
               "delay_days": ((row.actual_date - row.plan_date).days
                              if row.actual_date and row.plan_date else 0)})


# ---------------------------------------------------------------------------
# 变更单
# ---------------------------------------------------------------------------


def _amendment(user, pk, write=False):
    """取变更单并校验合同权限。"""
    row = ContractAmendment.objects.select_related("contract").filter(pk=pk).first()
    if row is None:
        raise ValueError("变更单不存在")
    if not is_visible(row.contract, user):
        raise ValueError("无权访问该合同")
    if write and not can_write(user, row.contract):
        raise ValueError("无权修改该合同")
    return row


def _next_amendment_code(contract):
    """变更单号：BG + 合同 id + 序号，同合同内唯一。"""
    used = set(contract.amendments.values_list("code", flat=True))
    for index in range(1, 1000):
        code = f"BG{contract.id}-{index:03d}"
        if code not in used:
            return code
    raise ValueError("变更单号已用尽")


@endpoint(("GET",))
def amendments_list(request, pk):
    """变更单列表（按创建时间倒序，可选审批状态）。"""
    contract = get_contract(request.user, pk)
    rows = contract.amendments.all()
    status = opt_str(request, "status")
    if status:
        rows = rows.filter(approval_status=status)
    items = [amendment_dict(row) for row in rows]
    return ok({"items": items, "count": len(items),
               "effective": sum(1 for row in rows if row.approval_status == "effective")})


@endpoint()
def amendment_create(request, pk):
    """新建变更单（记录变更前后文本与原因，从草稿开始）。"""
    contract = get_contract(request.user, pk, write=True)
    if contract.status == "archived":
        raise ValueError("已归档合同不能发起变更")
    change_type = opt_str(request, "change_type", "clause")
    if change_type not in AMENDMENT_TYPES:
        raise ValueError(f"变更类型不支持: {change_type}")
    code = opt_str(request, "code", "", max_len=60).strip() or _next_amendment_code(contract)
    if contract.amendments.filter(code=code).exists():
        raise ValueError(f"变更单号已存在: {code}")
    row = ContractAmendment.objects.create(
        owner=request.user,
        contract=contract,
        code=code,
        change_type=change_type,
        before_text=opt_str(request, "before_text", max_len=0),
        after_text=opt_str(request, "after_text", max_len=0),
        effective_date=parse_day(p(request, "effective_date")),
        approval_status="draft",
        reason=opt_str(request, "reason", max_len=0),
    )
    return ok(amendment_dict(row))


@endpoint()
def amendment_update(request, pk):
    """更新变更单（仅草稿/已驳回可改）。"""
    row = _amendment(request.user, pk, write=True)
    if row.approval_status not in ("draft", "rejected"):
        raise ValueError("仅草稿或已驳回的变更单可修改")
    if has(request, "change_type"):
        value = opt_str(request, "change_type", row.change_type)
        if value not in AMENDMENT_TYPES:
            raise ValueError(f"变更类型不支持: {value}")
        row.change_type = value
    if has(request, "before_text"):
        row.before_text = opt_str(request, "before_text", max_len=0)
    if has(request, "after_text"):
        row.after_text = opt_str(request, "after_text", max_len=0)
    if has(request, "effective_date"):
        row.effective_date = parse_day(p(request, "effective_date"))
    if has(request, "reason"):
        row.reason = opt_str(request, "reason", max_len=0)
    if row.approval_status == "rejected":
        row.approval_status = "draft"
    row.touch()
    row.save()
    return ok(amendment_dict(row))


@endpoint()
def amendment_submit(request, pk):
    """提交变更审批（draft → submitted）。"""
    with transaction.atomic():
        row = _amendment(request.user, pk, write=True)
        state.assert_amendment_transition(row, "submitted")
        if not (row.after_text or "").strip() and row.change_type == "clause":
            raise ValueError("条款变更必须填写变更后内容")
        row.approval_status = "submitted"
        row.touch()
        row.save(update_fields=["approval_status", "updated_at"])
    return ok(amendment_dict(row))


@endpoint()
def amendment_approve(request, pk):
    """审批变更单：通过后可立即生效（回写合同字段并生成版本）。"""
    action = opt_str(request, "action", "approve")
    if action not in ("approve", "reject"):
        raise ValueError("action 仅支持 approve / reject")
    with transaction.atomic():
        row = _amendment(request.user, pk, write=True)
        state.assert_amendment_transition(row, "approved" if action == "approve"
                                          else "rejected")
        row.approval_status = "approved" if action == "approve" else "rejected"
        row.approved_by = request.user if getattr(request.user, "pk", None) else None
        row.decided_at = timezone.now()
        row.reason = opt_str(request, "reason", row.reason, max_len=0)
        row.touch()
        row.save(update_fields=["approval_status", "approved_by", "decided_at",
                                "reason", "updated_at"])
        applied = False
        if action == "approve" and opt_bool(request, "apply", True):
            if row.change_type == "amount":
                if has(request, "new_amount"):
                    row._new_amount = dec(p(request, "new_amount"), "变更后金额",
                                          minimum="0")
                elif (row.after_text or "").strip():
                    row._new_amount = dec(row.after_text, "变更后金额", minimum="0")
                else:
                    raise ValueError("金额变更需要提供 new_amount 或变更后金额文本")
            elif row.change_type == "date":
                new_date = parse_day(p(request, "new_expire_date"))
                if new_date is None:
                    raise ValueError("期限变更需要提供 new_expire_date")
                row._new_expire_date = new_date
            services.apply_amendment(row, request.user)
            applied = True
    return ok({**amendment_dict(row), "applied": applied})


# ---------------------------------------------------------------------------
# 审批节点
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def approvals_list(request, pk):
    """某合同的审批节点（按节点序号，附整体进度）。"""
    contract = get_contract(request.user, pk)
    items = [approval_dict(row) for row in
             contract.approvals.select_related("approver").all()]
    return ok({"items": items, "count": len(items),
               "summary": state.approvals_summary(contract)})


@endpoint(("GET",))
def approvals_pending(request):
    """待我处理的审批节点：数据范围内审批中的合同，按等待时长倒序。"""
    contracts = scope_queryset(Contract.objects.all(), request.user)
    qs = (ContractApproval.objects
          .filter(contract__in=contracts, decision="pending",
                  contract__status="reviewing")
          .select_related("contract", "approver"))
    mine_only = opt_bool(request, "mine", False)
    if mine_only:
        qs = qs.filter(Q(approver=request.user) | Q(approver__isnull=True,
                                                    contract__owner=request.user))
    rows = list(qs.order_by("contract_id", "node")[:300])
    now = timezone.now()
    items = []
    for row in rows:
        waiting_hours = round((now - row.contract.updated_at).total_seconds() / 3600, 1)
        items.append({**approval_dict(row),
                      "contract_number": row.contract.number,
                      "contract_name": row.contract.name,
                      "contract_amount": f"{to_decimal(row.contract.amount):.2f}",
                      "waiting_hours": waiting_hours})
    items.sort(key=lambda item: -item["waiting_hours"])
    return ok({"items": items, "count": len(items),
               "contracts": len({item["contract_id"] for item in items})})


# ---------------------------------------------------------------------------
# 履约日历
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def obligations_calendar(request):
    """履约日历：按截止月份聚合可见合同的义务（待办/完成/逾期 + 前 5 条明细）。"""
    contracts = scope_queryset(Contract.objects.all(), request.user)
    qs = (ContractObligation.objects.filter(contract__in=contracts)
          .select_related("contract").order_by("due_date", "id"))
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    contract_id = opt_num(request, "contract_id", None, integer=True, minimum=1)
    if contract_id:
        qs = qs.filter(contract_id=int(contract_id))
    months = int(opt_num(request, "months", 6, minimum=1, maximum=24,
                         integer=True))
    rows = list(qs[:2000])
    result = services.obligation_calendar(rows, timezone.localdate(), months)
    for bucket in result["months"]:
        for item in bucket["items"]:
            item["due_date"] = iso(item["due_date"])
    result["generated_at"] = iso(result["generated_at"])
    result["months_ahead"] = months
    return ok(result)
