# -*- coding: utf-8 -*-
"""contracts · 财务与风险接口（17 个）：付款计划 / 续约 / 风险项 / 提醒 / 财务汇总。

金额口径：
- 计划金额与实付金额分列，逾期与未付全部由模型派生；
- 登记实付采用「累加」语义（支持部分收款），一次付清也只需一次调用；
- 所有金额入参走 common.dec（Decimal + 两位小数 + 非负校验），不接收 float 上限外的杂质。
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from core.scoping import can_write, is_visible, scope_queryset
from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)
from contracts import services, state
from contracts.common import (dec, get_contract, has, iso, money_str,
                              page_args, page_payload, parse_day, payment_dict,
                              reminder_dict, renewal_dict, req_list_arg, risk_dict)
from contracts.models import (REMINDER_CHANNELS, RENEWAL_TYPES, RISK_LEVELS,
                              RISK_LEVEL_WEIGHT, RISK_STATUS, Contract,
                              ContractPayment, ContractReminder,
                              ContractRenewal, ContractRisk, to_decimal)


# ---------------------------------------------------------------------------
# 付款计划
# ---------------------------------------------------------------------------


def _payment(user, pk, write=False):
    """取付款期次并校验合同权限。"""
    row = ContractPayment.objects.select_related("contract").filter(pk=pk).first()
    if row is None:
        raise ValueError("付款期次不存在")
    if not is_visible(row.contract, user):
        raise ValueError("无权访问该合同")
    if write and not can_write(user, row.contract):
        raise ValueError("无权修改该合同")
    return row


@endpoint(("GET",))
def payments_list(request, pk):
    """某合同的付款计划（含实付、剩余、逾期标记与合计）。"""
    contract = get_contract(request.user, pk)
    rows = list(contract.payments.all())
    items = [payment_dict(row) for row in rows]
    planned = sum(to_decimal(row.plan_amount) for row in rows
                  if row.status != "cancelled")
    paid = sum(to_decimal(row.paid_amount) for row in rows
               if row.status != "cancelled")
    return ok({"items": items, "count": len(items),
               "planned_total": money_str(planned), "paid_total": money_str(paid),
               "unpaid_total": money_str(max(planned - paid, to_decimal(0))),
               "currency": contract.currency})


@endpoint()
def payment_create(request, pk):
    """新增付款期次（期次号自动顺延；计划金额必须大于 0）。"""
    contract = get_contract(request.user, pk, write=True)
    if contract.status in ("archived",):
        raise ValueError("已归档合同不能新增付款计划")
    period_no = opt_num(request, "period_no", None, integer=True, minimum=1)
    if period_no is None:
        period_no = (contract.payments.order_by("-period_no")
                     .values_list("period_no", flat=True).first() or 0) + 1
    period_no = int(period_no)
    if contract.payments.filter(period_no=period_no).exists():
        raise ValueError(f"第 {period_no} 期已存在")
    plan_amount = dec(p(request, "plan_amount") or p(request, "amount"),
                      "计划金额", allow_zero=False)
    row = ContractPayment.objects.create(
        owner=request.user,
        contract=contract,
        period_no=period_no,
        plan_amount=plan_amount,
        plan_date=parse_day(p(request, "plan_date"), "计划日期", required=True),
        paid_amount=to_decimal(0),
        status="planned",
        remark=opt_str(request, "remark", max_len=0),
    )
    row.sync_status()
    row.save(update_fields=["status", "updated_at"])
    state.log_transition(contract, "payment", request.user,
                         f"新增第 {row.period_no} 期付款计划",
                         contract.status, contract.status,
                         {"payment_id": row.id, "plan_amount": money_str(plan_amount)})
    return ok(payment_dict(row))


@endpoint()
def payment_update(request, pk):
    """修改付款计划（已结清期次不可改；计划日/金额变更后重算状态）。"""
    row = _payment(request.user, pk, write=True)
    if row.status == "paid":
        raise ValueError("已结清的期次不能修改")
    if row.status == "cancelled":
        raise ValueError("已取消的期次不能修改")
    if has(request, "plan_amount"):
        row.plan_amount = dec(p(request, "plan_amount"), "计划金额", allow_zero=False)
    if has(request, "plan_date"):
        row.plan_date = parse_day(p(request, "plan_date"), "计划日期", required=True)
    if has(request, "remark"):
        row.remark = opt_str(request, "remark", max_len=0)
    row.sync_status()
    row.touch()
    row.save()
    return ok(payment_dict(row))


@endpoint()
def payment_pay(request, pk):
    """登记实付（累加语义，支持分次收款；付满自动结清）。"""
    amount = dec(p(request, "amount") if has(request, "amount") else p(request, "paid_amount"),
                 "实付金额", allow_zero=False)
    paid_date = parse_day(p(request, "paid_date")) or timezone.localdate()
    with transaction.atomic():
        row = _payment(request.user, pk, write=True)
        if row.status == "cancelled":
            raise ValueError("已取消的期次不能登记实付")
        if row.status == "paid":
            raise ValueError("该期次已结清")
        new_paid = to_decimal(row.paid_amount) + amount
        if new_paid > to_decimal(row.plan_amount):
            # 超付不静默吞掉：合同金额与计划可能不同步，业务上必须人工确认
            raise ValueError(f"实付金额超过计划金额（{money_str(row.plan_amount)}）")
        row.paid_amount = new_paid
        row.paid_date = paid_date
        row.sync_status()
        row.touch()
        row.save(update_fields=["paid_amount", "paid_date", "status", "updated_at"])
        state.log_transition(row.contract, "payment", request.user,
                             f"第 {row.period_no} 期实付 {money_str(amount)}",
                             row.contract.status, row.contract.status,
                             {"payment_id": row.id, "amount": money_str(amount),
                              "status": row.status})
    return ok(payment_dict(row))


@endpoint()
def payment_cancel(request, pk):
    """取消付款期次（已发生实付的期次不允许取消，必须先冲正）。"""
    with transaction.atomic():
        row = _payment(request.user, pk, write=True)
        if row.status == "paid":
            raise ValueError("已结清的期次不能取消")
        if to_decimal(row.paid_amount) > 0:
            raise ValueError("该期次已有实付，不能取消")
        row.status = "cancelled"
        row.touch()
        row.save(update_fields=["status", "updated_at"])
    return ok(payment_dict(row))


@endpoint(("GET",))
def payments_overdue(request):
    """逾期付款统计（数据范围内，按逾期天数倒序，附逾期总额）。"""
    contracts = scope_queryset(Contract.objects.all(), request.user)
    today = timezone.localdate()
    stats = services.payment_overdue_stats(contracts, today)
    stats["generated_at"] = iso(timezone.now())
    return ok(stats)


# ---------------------------------------------------------------------------
# 续约
# ---------------------------------------------------------------------------


def _renewal(user, pk, write=False):
    """取续约记录并校验合同权限。"""
    row = ContractRenewal.objects.select_related("contract").filter(pk=pk).first()
    if row is None:
        raise ValueError("续约记录不存在")
    if not is_visible(row.contract, user):
        raise ValueError("无权访问该合同")
    if write and not can_write(user, row.contract):
        raise ValueError("无权修改该合同")
    return row


@endpoint(("GET",))
def renewals_list(request, pk):
    """续约记录列表（含待处理数量与当前到期日）。"""
    contract = get_contract(request.user, pk)
    items = [renewal_dict(row) for row in contract.renewals.all()]
    return ok({"items": items, "count": len(items),
               "pending": sum(1 for row in items if row["status"] == "pending"),
               "expire_date": iso(contract.expire_date),
               "days_to_expiry": contract.days_to_expiry()})


@endpoint()
def renewal_create(request, pk):
    """新建续约跟进（新到期日必须晚于当前到期日）。"""
    contract = get_contract(request.user, pk, write=True)
    renewal_type = opt_str(request, "renewal_type", "manual")
    if renewal_type not in RENEWAL_TYPES:
        raise ValueError(f"续约类型不支持: {renewal_type}")
    new_expire = parse_day(p(request, "new_expire_date"), "新到期日")
    if renewal_type != "terminate":
        if new_expire is None:
            raise ValueError("续约必须填写新到期日")
        if contract.expire_date and new_expire <= contract.expire_date:
            raise ValueError("新到期日必须晚于当前到期日")
    remind_days = int(opt_num(request, "remind_days", 30, minimum=1, maximum=365,
                              integer=True))
    row = ContractRenewal.objects.create(
        owner=request.user,
        contract=contract,
        renewal_type=renewal_type,
        new_expire_date=new_expire,
        remind_days=remind_days,
        status="pending",
        note=opt_str(request, "note", max_len=0),
    )
    return ok(renewal_dict(row))


@endpoint()
def renewal_confirm(request, pk):
    """确认/放弃续约：确认后回写合同到期日，已到期合同自动恢复履行。"""
    action = opt_str(request, "action", "confirm")
    if action not in ("confirm", "decline"):
        raise ValueError("action 仅支持 confirm / decline")
    with transaction.atomic():
        row = _renewal(request.user, pk, write=True)
        if row.status != "pending":
            raise ValueError(f"该续约记录已是 {row.status} 状态")
        row.status = "confirmed" if action == "confirm" else "declined"
        row.decided_at = timezone.now()
        row.note = opt_str(request, "note", row.note, max_len=0)
        row.touch()
        row.save(update_fields=["status", "decided_at", "note", "updated_at"])
        contract = row.contract
        if action == "confirm" and row.renewal_type != "terminate":
            contract.expire_date = row.new_expire_date or contract.expire_date
            contract.renewal_mode = ("auto" if row.renewal_type == "auto" else "manual")
            contract.touch()
            contract.save(update_fields=["expire_date", "renewal_mode", "updated_at"])
            # 已到期合同续约确认后要恢复履行，否则到期日更新了状态仍是 expired
            if contract.status == "expired":
                state.transition(contract, "reactivate", request.user,
                                 "续约确认，恢复履行")
        state.log_transition(contract, "renewal", request.user,
                             f"续约{'确认' if action == 'confirm' else '放弃'}",
                             contract.status, contract.status,
                             {"renewal_id": row.id, "status": row.status})
    return ok({**renewal_dict(row), "contract_status": contract.status,
               "expire_date": iso(contract.expire_date)})


@endpoint(("GET",))
def renewals_upcoming(request):
    """待处理续约提醒（进入各自提醒窗口的续约记录，按剩余天数升序）。"""
    contracts = scope_queryset(Contract.objects.all(), request.user)
    rows = (ContractRenewal.objects
            .filter(contract__in=contracts, status="pending")
            .select_related("contract").order_by("contract__expire_date"))
    items = []
    today = timezone.localdate()
    for row in rows[:500]:
        days = ((row.contract.expire_date - today).days
                if row.contract.expire_date else None)
        if days is None or days > row.remind_days:
            continue
        items.append({**renewal_dict(row),
                      "contract_number": row.contract.number,
                      "contract_name": row.contract.name,
                      "days_to_expiry": days,
                      "due": days <= 7})
    items.sort(key=lambda item: item["days_to_expiry"])
    return ok({"items": items, "count": len(items)})


# ---------------------------------------------------------------------------
# 风险
# ---------------------------------------------------------------------------


def _risk(user, pk, write=False):
    """取风险项并校验合同权限。"""
    row = ContractRisk.objects.select_related("contract").filter(pk=pk).first()
    if row is None:
        raise ValueError("风险项不存在")
    if not is_visible(row.contract, user):
        raise ValueError("无权访问该合同")
    if write and not can_write(user, row.contract):
        raise ValueError("无权修改该合同")
    return row


@endpoint(("GET",))
def risks_list(request, pk):
    """某合同的风险项列表（按权重倒序，附风险分）。"""
    contract = get_contract(request.user, pk)
    rows = contract.risks.all()
    items = [risk_dict(row) for row in rows]
    open_rows = [row for row in rows if row.status not in ("closed", "accepted")]
    return ok({"items": items, "count": len(items),
               "open_count": len(open_rows),
               "open_weight": sum(row.weight() for row in open_rows),
               "risk_score": contract.risk_score})


@endpoint()
def risk_create(request, pk):
    """登记风险项（等级校验，登记后立即重算合同风险分）。"""
    contract = get_contract(request.user, pk, write=True)
    level = opt_str(request, "level", "medium")
    if level not in RISK_LEVELS:
        raise ValueError(f"风险等级不支持: {level}")
    row = ContractRisk.objects.create(
        owner=request.user,
        contract=contract,
        title=req_str(request, "title", max_len=200),
        level=level,
        description=opt_str(request, "description", max_len=0),
        mitigation=opt_str(request, "mitigation", max_len=0),
        status="open",
        score=RISK_LEVEL_WEIGHT.get(level, 8),
    )
    with transaction.atomic():
        score = services.score_risk(contract, persist=True)
        state.log_transition(contract, "risk", request.user,
                             f"新增风险：{row.title}",
                             contract.status, contract.status,
                             {"risk_id": row.id, "score": score["total"]})
    return ok({**risk_dict(row), "contract_risk_score": score["total"]})


@endpoint()
def risk_update(request, pk):
    """更新风险项（状态/等级/缓解措施；变化后重算合同风险分）。"""
    row = _risk(request.user, pk, write=True)
    if has(request, "title"):
        row.title = req_str(request, "title", max_len=200)
    if has(request, "level"):
        level = opt_str(request, "level", row.level)
        if level not in RISK_LEVELS:
            raise ValueError(f"风险等级不支持: {level}")
        row.level = level
        row.score = RISK_LEVEL_WEIGHT.get(level, 8)
    if has(request, "status"):
        status = opt_str(request, "status", row.status)
        if status not in RISK_STATUS:
            raise ValueError(f"风险状态不支持: {status}")
        row.status = status
    if has(request, "description"):
        row.description = opt_str(request, "description", max_len=0)
    if has(request, "mitigation"):
        row.mitigation = opt_str(request, "mitigation", max_len=0)
    with transaction.atomic():
        row.touch()
        row.save()
        score = services.score_risk(row.contract, persist=True)
    return ok({**risk_dict(row), "contract_risk_score": score["total"]})


@endpoint()
def risk_score(request, pk):
    """重新评估合同风险（输出五维分项明细，并回写风险分）。"""
    contract = get_contract(request.user, pk, write=True)
    with transaction.atomic():
        result = services.score_risk(contract, persist=True)
        state.log_transition(contract, "risk", request.user,
                             f"重新评分：{result['total']}",
                             contract.status, contract.status,
                             {"level": result["level"]})
    result["contract_id"] = contract.id
    result["risk_score"] = contract.risk_score
    return ok(result)


# ---------------------------------------------------------------------------
# 提醒
# ---------------------------------------------------------------------------


@endpoint()
def reminder_scan(request):
    """到期/续约扫描（幂等）：更新临期与到期状态，并按 30/15/7/1 天分段建提醒。"""
    days = int(opt_num(request, "days", 90, minimum=0, maximum=3650, integer=True))
    dry_run = opt_bool(request, "dry_run", False)
    channel = opt_str(request, "channel", "inapp")
    if channel not in REMINDER_CHANNELS:
        raise ValueError(f"提醒渠道不支持: {channel}")
    today = timezone.localdate()
    contracts = (scope_queryset(Contract.objects.all(), request.user)
                 .filter(expire_date__isnull=False,
                         expire_date__lte=today + timedelta(days=days))
                 .exclude(status__in=("archived", "completed", "terminated"))
                 .order_by("expire_date"))
    with transaction.atomic():
        result = services.scan_expiry(contracts, channel=channel,
                                      user=request.user, mark_status=not dry_run)
        renewal = (services.scan_renewal_reminders(contracts, request.user, channel)
                   if not dry_run else {"created": 0, "items": []})
        result["renewal_reminders"] = renewal["created"]
        result["dry_run"] = dry_run
        result["channel"] = channel
        result["within_days"] = days
    return ok(result)


@endpoint(("GET",))
def reminders_list(request):
    """提醒记录列表（按类型/状态/合同筛选，含合同编号）。"""
    contracts = scope_queryset(Contract.objects.all(), request.user)
    qs = (ContractReminder.objects.filter(contract__in=contracts)
          .select_related("contract").order_by("-created_at"))
    kind = opt_str(request, "kind")
    if kind:
        qs = qs.filter(kind=kind)
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    contract_id = opt_num(request, "contract_id", None, integer=True, minimum=1)
    if contract_id:
        qs = qs.filter(contract_id=int(contract_id))
    page, size = page_args(request)
    total = qs.count()
    start = (page - 1) * size
    rows = list(qs[start:start + size])
    by_kind = {row["kind"]: row["count"] for row in
               qs.values("kind").annotate(count=Count("id")).order_by()}
    return ok(page_payload([reminder_dict(row) for row in rows], total, page, size,
                           by_kind=by_kind))


# ---------------------------------------------------------------------------
# 财务汇总
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def finance_summary(request):
    """财务汇总（全部或指定合同；按币种拆分总额/已付/未付/逾期与回收率）。"""
    qs = scope_queryset(Contract.objects.all(), request.user)
    contract_id = opt_num(request, "contract_id", None, integer=True, minimum=1)
    if contract_id:
        qs = qs.filter(pk=int(contract_id))
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    contract_type = opt_str(request, "contract_type")
    if contract_type:
        qs = qs.filter(contract_type=contract_type)
    result = services.finance_summary(qs.prefetch_related("payments"))
    result["generated_at"] = iso(timezone.now())
    result["filter"] = {"contract_id": contract_id, "status": status,
                        "contract_type": contract_type}
    return ok(result)


# ---------------------------------------------------------------------------
# 付款计划生成与提醒确认
# ---------------------------------------------------------------------------


@endpoint()
def payment_plan(request, pk):
    """按金额/比例批量生成付款计划（期次幂等，已存在的期次跳过不覆盖）。"""
    contract = get_contract(request.user, pk, write=True)
    if contract.status in ("archived", "terminated", "completed"):
        raise ValueError("已归档/已终止/已完成的合同不能再生成付款计划")
    periods = int(req_num(request, "periods", minimum=1, maximum=60,
                          integer=True))
    ratios = req_list_arg(request, "ratios", [], max_items=60)
    first_date = opt_str(request, "first_date", "")
    interval_days = int(opt_num(request, "interval_days", 30, minimum=1,
                                maximum=365, integer=True))
    with transaction.atomic():
        result = services.build_payment_plan(
            contract, periods, ratios or None, first_date or None,
            interval_days, request.user)
    preview = result["preview"]
    return ok({
        "contract_id": contract.id,
        "created": result["created"],
        "skipped": result["skipped"],
        "periods": preview["periods"],
        "amount": money_str(preview["amount"]),
        "first_date": iso(preview["first_date"]),
        "interval_days": preview["interval_days"],
        "items": [payment_dict(row) for row in result["rows"]],
    })


@endpoint()
def reminder_ack(request, pk):
    """确认提醒（已读）：仅允许 sent/read 状态，失败记录保留人工排查。"""
    row = (ContractReminder.objects.select_related("contract")
           .filter(pk=pk).first())
    if row is None:
        raise ValueError("提醒记录不存在")
    if not is_visible(row.contract, request.user):
        raise ValueError("无权访问该提醒")
    if not can_write(request.user, row.contract):
        raise ValueError("无权修改该合同的提醒")
    if row.status == "failed":
        raise ValueError("发送失败的提醒不能标记已读，请先补发")
    changed = row.status != "read"
    if changed:
        row.status = "read"
        row.touch()
        row.save(update_fields=["status", "updated_at"])
    return ok({**reminder_dict(row), "changed": changed})
