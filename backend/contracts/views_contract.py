# -*- coding: utf-8 -*-
"""contracts · 合同主档接口（35 个）：台账、状态机动作、版本、参与方、签署、附件与标签。

状态机动作全部走 contracts.state：校验、落状态、写审计三件事只有一份实现。
并发口径：所有会改状态/多表写入的接口都在事务内 select_for_update 锁合同行，
避免「两个人同时审批同一节点」导致节点被双写（结论只能落一次）。
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.scoping import can_write, is_visible, scope_queryset
from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)
from contracts import services, state
from contracts.common import (attachment_dict, audit_dict, contract_dict, dec,
                              get_contract, has, int_list, iso, page_args,
                              page_payload, parse_day, party_dict, req_dict,
                              req_list_arg, money_str, payment_dict, signature_dict, tag_dict,
                              user_dict)
from contracts.models import (ATTACHMENT_KINDS, CONTRACT_TYPES, CURRENCIES,
                              PARTY_ROLES, PARTY_TYPES, RENEWAL_MODES,
                              SIGNATURE_METHODS, SIGNATURE_STATUS,
                              Contract, ContractApproval, ContractAttachment,
                              ContractObligation,
                              ContractParty, ContractSignature, ContractTag,
                              ContractTemplate, ContractVersion,
                              ObligationEvent, to_decimal)


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------


def _next_number(user):
    """自动生成合同编号：HT + 日期 + 4 位序号，撞号时顺延（不依赖数据库序列）。"""
    prefix = f"HT{timezone.localdate():%Y%m%d}"
    used = set(Contract.objects.filter(owner=user, number__startswith=prefix)
               .values_list("number", flat=True))
    for index in range(1, 10000):
        number = f"{prefix}-{index:04d}"
        if number not in used:
            return number
    raise ValueError("当日合同编号已用尽")


def _validate_type(value, field="contract_type"):
    if value not in CONTRACT_TYPES:
        raise ValueError(f"合同类型不支持: {value}")
    return value


def _validate_currency(value):
    if value not in CURRENCIES:
        raise ValueError(f"币种不支持: {value}")
    return value


def _validate_dates(contract, effective=None, expire=None):
    """生效日不得晚于到期日，且到期日不得早于签订日。"""
    effective = effective if effective is not None else contract.effective_date
    expire = expire if expire is not None else contract.expire_date
    if effective and expire and effective > expire:
        raise ValueError("生效日不能晚于到期日")
    if contract.sign_date and expire and expire < contract.sign_date:
        raise ValueError("到期日不能早于签订日")


def _lock_contract(pk, user):
    """事务内锁行 + 写权限校验：状态动作的唯一入口。"""
    try:
        contract = Contract.objects.select_for_update().get(pk=pk)
    except Contract.DoesNotExist:
        raise ValueError("合同不存在")
    if not is_visible(contract, user):
        raise ValueError("无权访问该合同")
    if not can_write(user, contract):
        raise ValueError("无权修改该合同")
    return contract


def _write_audit(contract, action, user, note, payload=None):
    """非状态动作的审计（创建/克隆/版本等）。"""
    return state.log_transition(contract, action, user, note,
                                contract.status, contract.status, payload)


def _set_current_version(contract, body, user, summary):
    """正文快照：内容与当前版本一致时跳过，避免同一正文刷出一堆空版本。"""
    if contract.current_version_id and contract.current_version.body_snapshot == body:
        return contract.current_version
    return services.create_version(contract, user, body, summary)


def _party_or_error(contract, pk):
    party = ContractParty.objects.filter(pk=pk, contract=contract).first()
    if party is None:
        raise ValueError("参与方不存在或不属于该合同")
    return party


def _contract_queryset(request):
    """台账查询：读范围 + 关键词 + 多条件筛选。"""
    qs = scope_queryset(Contract.objects.all(), request.user).select_related(
        "owner", "responsible", "current_version")
    q = opt_str(request, "q")
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(name__icontains=q)
                       | Q(counterparty_name__icontains=q))
    status = opt_str(request, "status")
    if status:
        qs = qs.filter(status=status)
    contract_type = opt_str(request, "contract_type") or opt_str(request, "type")
    if contract_type:
        qs = qs.filter(contract_type=contract_type)
    currency = opt_str(request, "currency")
    if currency:
        qs = qs.filter(currency=currency)
    owner_id = opt_num(request, "owner_id", None, integer=True, minimum=1)
    if owner_id:
        qs = qs.filter(Q(owner_id=int(owner_id)) | Q(responsible_id=int(owner_id)))
    tag_id = opt_num(request, "tag_id", None, integer=True, minimum=1)
    if tag_id:
        qs = qs.filter(tags__id=int(tag_id))
    expiring_days = opt_num(request, "expiring_days", None, integer=True, minimum=0,
                            maximum=3650)
    if expiring_days is not None:
        today = timezone.localdate()
        qs = qs.filter(expire_date__gte=today,
                       expire_date__lte=today + timedelta(days=int(expiring_days)))
    min_risk = opt_num(request, "min_risk", None, integer=True, minimum=0, maximum=100)
    if min_risk is not None:
        qs = qs.filter(risk_score__gte=int(min_risk))
    qs = qs.order_by("-created_at", "-id")
    return qs


# ---------------------------------------------------------------------------
# 台账 CRUD
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def contracts(request):
    """合同台账（读范围 + q/status/类型/币种/负责人/标签/临期/风险分筛选）。"""
    qs = _contract_queryset(request)
    page, size = page_args(request)
    total = qs.count()
    start = (page - 1) * size
    rows = list(qs[start:start + size])
    return ok(page_payload([contract_dict(row) for row in rows], total, page, size))


@endpoint(("GET",))
def contract_expiring(request):
    """临期合同清单（默认 30 天内到期，含剩余天数与提醒档位）。"""
    days = int(opt_num(request, "days", 30, minimum=0, maximum=3650, integer=True))
    today = timezone.localdate()
    qs = (scope_queryset(Contract.objects.all(), request.user)
          .filter(expire_date__gte=today,
                  expire_date__lte=today + timedelta(days=days))
          .exclude(status__in=("archived", "terminated", "completed", "draft"))
          .order_by("expire_date"))
    items = []
    for row in qs[:500]:
        data = contract_dict(row)
        data["days_to_expiry"] = row.days_to_expiry(today)
        data["expiry_bucket"] = row.expiry_bucket(today)
        data["stage"] = services.expiry_stage_for(data["days_to_expiry"])
        items.append(data)
    return ok({"items": items, "count": len(items), "within_days": days})


@endpoint()
def contract_create(request):
    """新建合同（可带参与方与模板正文，自动生成首版本并算风险分）。"""
    name = req_str(request, "name", max_len=200)
    contract_type = _validate_type(opt_str(request, "contract_type",
                                           opt_str(request, "type", "service")))
    currency = _validate_currency(opt_str(request, "currency", "CNY"))
    amount = dec(p(request, "amount"), "合同金额", minimum="0")
    if amount <= 0:
        raise ValueError("合同金额必须大于 0")
    if has(request, "effective_date") and has(request, "expire_date"):
        if parse_day(p(request, "effective_date")) > parse_day(p(request, "expire_date")):
            raise ValueError("生效日不能晚于到期日")

    template = None
    template_id = opt_num(request, "template_id", None, integer=True, minimum=1)
    if template_id:
        template = ContractTemplate.objects.filter(pk=int(template_id)).first()
        if template is None:
            raise ValueError("模板不存在")
        if template.status != "published":
            raise ValueError("仅已发布模板可用于起草合同")

    body = opt_str(request, "body", "", max_len=0)
    if not body and template is not None:
        body = services.build_contract_body(template, req_dict(request, "variables"))
    if not body and template is not None:
        body = template.body

    parties = req_list_arg(request, "parties", [], max_items=10)
    for index, item in enumerate(parties):
        if not isinstance(item, dict):
            raise ValueError(f"参与方第 {index + 1} 项格式不正确")
        if not str(item.get("name") or "").strip():
            raise ValueError(f"参与方第 {index + 1} 项缺少名称")
        role = str(item.get("role") or "party_b")
        if role not in PARTY_ROLES:
            raise ValueError(f"参与方角色不支持: {role}")

    number = opt_str(request, "number", "", max_len=60).strip() or _next_number(request.user)
    if Contract.objects.filter(owner=request.user, number=number).exists():
        raise ValueError(f"合同编号已存在: {number}")

    with transaction.atomic():
        contract = Contract.objects.create(
            owner=request.user,
            number=number,
            name=name,
            contract_type=contract_type,
            amount=amount,
            currency=currency,
            sign_date=parse_day(p(request, "sign_date")),
            effective_date=parse_day(p(request, "effective_date")),
            expire_date=parse_day(p(request, "expire_date")),
            renewal_mode=opt_str(request, "renewal_mode", "none"),
            status="draft",
            responsible_id=int(opt_num(request, "responsible_id", request.user.id,
                                        integer=True, minimum=1)),
            counterparty_name=opt_str(request, "counterparty_name", max_len=200),
            template=template,
            remark=opt_str(request, "remark", max_len=0),
            data=req_dict(request, "data"),
        )
        _validate_dates(contract)
        for index, item in enumerate(parties):
            ContractParty.objects.create(
                owner=request.user,
                contract=contract,
                name=str(item.get("name")).strip()[:200],
                party_type=str(item.get("party_type") or "company"),
                credit_code=str(item.get("credit_code") or "")[:40],
                contact=str(item.get("contact") or "")[:60],
                phone=str(item.get("phone") or "")[:40],
                address=str(item.get("address") or "")[:200],
                role=str(item.get("role") or "party_b"),
                sign_order=int(item.get("sign_order") or index + 1),
            )
        if body:
            services.create_version(contract, request.user, body, "起草")
        _write_audit(contract, "create", request.user, f"新建合同 {contract.number}")
        services.score_risk(contract, persist=True)
    return ok(contract_dict(contract, detail=True))


@endpoint(("GET",))
def contract_detail(request, pk):
    """合同详情（含金额派生、期限、参与方、审批进度与当前版本摘要）。"""
    contract = get_contract(request.user, pk)
    data = contract_dict(contract, detail=True)
    data["parties"] = [party_dict(row) for row in contract.parties.all()]
    data["approvals"] = [{"id": row.id, "node": row.node,
                          "node_name": row.node_name,
                          "decision": row.decision}
                         for row in contract.approvals.all()]
    data["approval_summary"] = state.approvals_summary(contract)
    if contract.current_version_id:
        data["current_version"] = {
            "id": contract.current_version.id,
            "version_no": contract.current_version.version_no,
            "summary": contract.current_version.change_summary,
            "length": len(contract.current_version.body_snapshot or ""),
        }
    return ok(data)


@endpoint()
def contract_update(request, pk):
    """更新合同基本字段（已归档不可改；正文变更落新版本；金额/类型变化重算风险分）。"""
    contract = get_contract(request.user, pk, write=True)
    if contract.status == "archived":
        raise ValueError("已归档合同不可修改")
    risk_dirty = False
    if has(request, "name"):
        contract.name = req_str(request, "name", max_len=200)
    if has(request, "contract_type"):
        contract.contract_type = _validate_type(opt_str(request, "contract_type"))
        risk_dirty = True
    if has(request, "amount"):
        contract.amount = dec(p(request, "amount"), "合同金额", minimum="0")
        risk_dirty = True
    if has(request, "currency"):
        contract.currency = _validate_currency(opt_str(request, "currency"))
    if has(request, "sign_date"):
        contract.sign_date = parse_day(p(request, "sign_date"))
    if has(request, "effective_date"):
        contract.effective_date = parse_day(p(request, "effective_date"))
    if has(request, "expire_date"):
        contract.expire_date = parse_day(p(request, "expire_date"))
    if has(request, "renewal_mode"):
        mode = opt_str(request, "renewal_mode", contract.renewal_mode)
        if mode not in RENEWAL_MODES:
            raise ValueError(f"续约方式不支持: {mode}")
        contract.renewal_mode = mode
    if has(request, "responsible_id"):
        contract.responsible_id = int(req_num(request, "responsible_id", None,
                                              integer=True, minimum=1))
    if has(request, "counterparty_name"):
        contract.counterparty_name = opt_str(request, "counterparty_name", max_len=200)
    if has(request, "remark"):
        contract.remark = opt_str(request, "remark", max_len=0)
    if has(request, "data"):
        contract.data = req_dict(request, "data")
    _validate_dates(contract)
    with transaction.atomic():
        contract.touch()
        contract.save()
        if has(request, "body"):
            body = opt_str(request, "body", max_len=0)
            _set_current_version(contract, body,
                                 request.user,
                                 opt_str(request, "change_summary", "正文更新",
                                         max_len=0))
        if risk_dirty:
            services.score_risk(contract, persist=True)
        _write_audit(contract, "update", request.user, "更新合同信息")
    return ok(contract_dict(contract, detail=True))


@endpoint()
def contract_delete(request, pk):
    """删除合同（仅草稿；其余状态请走终止/归档，否则历史履约与付款无主）。"""
    contract = get_contract(request.user, pk, write=True)
    if contract.status != "draft":
        raise ValueError("仅草稿状态的合同可以删除，请使用终止或归档")
    contract_id, number = contract.id, contract.number
    with transaction.atomic():
        contract.delete()
    return ok({"deleted": True, "id": contract_id, "number": number})


# ---------------------------------------------------------------------------
# 状态机动作
# ---------------------------------------------------------------------------


@endpoint()
def contract_submit(request, pk):
    """提交审批：draft → reviewing，并按金额阈值生成审批节点（旧节点先清空）。"""
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        if contract.status != "draft":
            raise ValueError("仅草稿合同可提交审批")
        if to_decimal(contract.amount) <= 0:
            raise ValueError("合同金额必须大于 0 才能提交审批")
        route = services.build_approval_route(contract.amount, contract.contract_type)
        contract.approvals.filter(decision="pending").delete()
        for node in route["nodes"]:
            ContractApproval.objects.update_or_create(
                contract=contract, node=node["node"],
                defaults={"owner": request.user, "node_name": node["name"],
                          "decision": "pending", "opinion": ""},
            )
        state.transition(contract, "submit", request.user,
                         f"提交审批（{route['band_label']}："
                         f"{' → '.join(item['name'] for item in route['nodes'])}）",
                         {"route": route})
    return ok({"id": contract.id, "status": contract.status,
               "nodes": [row.node_name for row in contract.approvals.all()],
               "band": route["band_label"]})


@endpoint()
def contract_approve(request, pk):
    """审批通过单个节点；全部节点通过后合同自动进入已批准。"""
    node_id = opt_num(request, "approval_id", None, integer=True, minimum=1)
    node_no = opt_num(request, "node", None, integer=True, minimum=1)
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        if contract.status != "reviewing":
            raise ValueError("仅审批中的合同可以审批")
        summary = state.approvals_summary(contract)
        if summary["rejected"]:
            raise ValueError("存在已驳回节点，请重新提交审批")
        if node_id:
            approval = ContractApproval.objects.filter(
                pk=int(node_id), contract=contract).first()
        elif node_no:
            approval = ContractApproval.objects.filter(
                contract=contract, node=int(node_no)).first()
        else:
            approval = state.next_pending_approval(contract)
        if approval is None:
            raise ValueError("没有待审批节点")
        if approval.decision != "pending":
            raise ValueError(f"节点「{approval.node_name}」已裁决，不能重复审批")
        approval.decision = "approved"
        approval.opinion = opt_str(request, "opinion", max_len=0)
        approval.decided_at = timezone.now()
        if getattr(request.user, "pk", None):
            approval.approver = request.user
        approval.touch()
        approval.save(update_fields=["decision", "opinion", "decided_at",
                                     "approver", "updated_at"])
        remaining = contract.approvals.filter(decision="pending").count()
        if remaining == 0:
            state.transition(contract, "approve", request.user,
                             f"全部 {summary['total']} 个节点通过",
                             {"approval_id": approval.id})
    return ok({"id": contract.id, "status": contract.status,
               "node": approval.node, "remaining": remaining,
               "summary": state.approvals_summary(contract)})


@endpoint()
def contract_reject(request, pk):
    """审批驳回：节点记驳回原因，合同退回草稿（必须给出理由）。"""
    reason = req_str(request, "reason", max_len=0)
    node_no = opt_num(request, "node", None, integer=True, minimum=1)
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        if contract.status != "reviewing":
            raise ValueError("仅审批中的合同可以驳回")
        approval = (ContractApproval.objects.filter(contract=contract, node=int(node_no))
                    .first() if node_no else state.next_pending_approval(contract))
        if approval is None:
            raise ValueError("没有待审批节点")
        if approval.decision != "pending":
            raise ValueError(f"节点「{approval.node_name}」已裁决")
        approval.decision = "rejected"
        approval.opinion = reason
        approval.decided_at = timezone.now()
        if getattr(request.user, "pk", None):
            approval.approver = request.user
        approval.touch()
        approval.save(update_fields=["decision", "opinion", "decided_at",
                                     "approver", "updated_at"])
        state.transition(contract, "reject", request.user, reason,
                         {"approval_id": approval.id})
    return ok({"id": contract.id, "status": contract.status,
               "node": approval.node, "reason": reason})


@endpoint()
def contract_sign(request, pk):
    """发起签署：approved → signing，为每个参与方生成签署记录与哈希指纹。"""
    method = opt_str(request, "method", "electronic")
    if method not in SIGNATURE_METHODS:
        raise ValueError(f"签署方式不支持: {method}")
    sign_now = opt_bool(request, "sign_now", False)
    signer_name = opt_str(request, "signer_name", "", max_len=60)
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        if has(request, "body") and opt_str(request, "body", max_len=0):
            _set_current_version(contract, opt_str(request, "body", max_len=0),
                                 request.user, "签署前定稿")
        if not contract.current_version_id:
            raise ValueError("合同还没有正文版本，请先补充正文再发起签署")
        state.transition(contract, "sign", request.user, f"发起签署（{method}）")
        created = []
        parties = list(contract.parties.all()) or [None]
        for party in parties:
            name = (signer_name or (party.contact if party else "")
                    or (party.name if party else request.user.username))
            signed_at = timezone.now() if sign_now else None
            signature = ContractSignature.objects.create(
                owner=request.user,
                contract=contract,
                party=party,
                signer_name=name[:60],
                signer=request.user if sign_now else None,
                method=method,
                signed_at=signed_at,
                status="signed" if sign_now else "pending",
                hash_fingerprint=(services.sign_fingerprint(contract, name[:60], signed_at)
                                  if sign_now else ""),
            )
            if party is not None and sign_now:
                party.signed = True
                party.touch()
                party.save(update_fields=["signed", "updated_at"])
            created.append(signature)
    return ok({"id": contract.id, "status": contract.status,
               "signatures": [signature_dict(row) for row in created],
               "pending": sum(1 for row in created if row.status == "pending")})


@endpoint()
def contract_activate(request, pk):
    """合同生效：signing → active；有参与方时必须全部签署完成。"""
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        if contract.status != "signing":
            raise ValueError("仅签署中的合同可以生效")
        parties = contract.parties.count()
        signed = contract.signatures.filter(status="signed").count()
        pending = contract.signatures.filter(status="pending").count()
        if parties and signed < parties:
            raise ValueError(f"还有 {parties - signed} 个参与方未签署，不能生效")
        if pending:
            raise ValueError(f"还有 {pending} 条签署记录未处理，不能生效")
        state.transition(contract, "activate", request.user,
                         opt_str(request, "note", "合同生效"))
    return ok({"id": contract.id, "status": contract.status,
               "effective_date": iso(contract.effective_date),
               "days_to_expiry": contract.days_to_expiry()})


@endpoint()
def contract_terminate(request, pk):
    """终止合同（必须给原因；签署中/履行中/临期可终止）。"""
    reason = req_str(request, "reason", max_len=0)
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        state.transition(contract, "terminate", request.user, reason,
                         {"reason": reason})
        # 终止后未完成的义务不再追究：统一豁免并留事件，避免逾期指标虚高
        open_rows = list(contract.obligations.exclude(status__in=("done", "waived")))
        for row in open_rows:
            row.status = "waived"
            row.touch()
            row.save(update_fields=["status", "updated_at"])
            ObligationEvent.objects.create(
                owner=request.user, obligation=row, action="waive",
                note=f"合同终止：{reason}", actor=request.user,
                from_due_date=row.due_date,
            )
    return ok({"id": contract.id, "status": contract.status,
               "waived_obligations": len(open_rows), "reason": reason})


@endpoint()
def contract_complete(request, pk):
    """完成合同：履行中/临期/已到期 → 已完成；存在未履行义务时拒绝。"""
    note = opt_str(request, "note", "合同履约完成", max_len=0)
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        if contract.status not in ("active", "expiring", "expired"):
            raise ValueError(f"当前状态 {state.status_label(contract.status)} 不能标记完成")
        open_count = contract.obligations.exclude(status__in=("done", "waived")).count()
        if open_count:
            raise ValueError(f"还有 {open_count} 条履约义务未完成，不能标记完成")
        state.transition(contract, "complete", request.user, note)
    return ok({"id": contract.id, "status": contract.status})


@endpoint()
def contract_archive(request, pk):
    """归档合同（草稿/已到期/已终止/已完成可归档，归档后只读）。"""
    note = opt_str(request, "note", "归档", max_len=0)
    with transaction.atomic():
        contract = _lock_contract(pk, request.user)
        state.transition(contract, "archive", request.user, note)
    return ok({"id": contract.id, "status": contract.status})


@endpoint()
def contract_clone(request, pk):
    """克隆合同（复制参与方/义务/里程碑/付款/风险，编号自动顺延，从草稿开始）。"""
    source = get_contract(request.user, pk)
    number = opt_str(request, "number", "", max_len=60).strip() or _next_number(request.user)
    if Contract.objects.filter(owner=request.user, number=number).exists():
        raise ValueError(f"合同编号已存在: {number}")
    with transaction.atomic():
        copy = Contract.objects.create(
            owner=request.user,
            number=number,
            name=opt_str(request, "name", f"{source.name}（副本）", max_len=200),
            contract_type=source.contract_type,
            amount=source.amount,
            currency=source.currency,
            sign_date=None,
            effective_date=source.effective_date,
            expire_date=source.expire_date,
            renewal_mode=source.renewal_mode,
            status="draft",
            responsible=request.user,
            counterparty_name=source.counterparty_name,
            template=source.template,
            remark=f"克隆自合同 #{source.id}",
            data=source.data or {},
        )
        for party in source.parties.all():
            party.pk = None
            party.id = None
            party.contract = copy
            party.owner = request.user
            party.signed = False
            party.save()
        for row in source.obligations.filter(recurring_from__isnull=True):
            row.pk = None
            row.id = None
            row.contract = copy
            row.owner = request.user
            row.status = "pending"
            row.series_uid = None
            row.save()
        for row in source.milestones.all():
            row.pk = None
            row.id = None
            row.contract = copy
            row.owner = request.user
            row.actual_date = None
            row.status = "planned"
            row.save()
        for row in source.payments.all():
            row.pk = None
            row.id = None
            row.contract = copy
            row.owner = request.user
            row.paid_amount = to_decimal(0)
            row.paid_date = None
            row.status = "planned"
            row.save()
        for row in source.risks.all():
            row.pk = None
            row.id = None
            row.contract = copy
            row.owner = request.user
            row.save()
        body = (source.current_version.body_snapshot
                if source.current_version_id else "")
        if body:
            services.create_version(copy, request.user, body, "克隆自原合同")
        _write_audit(copy, "clone", request.user, f"克隆自合同 #{source.id}",
                     {"source_id": source.id})
        services.score_risk(copy, persist=True)
    return ok({"id": copy.id, "number": copy.number, "status": copy.status,
               "source_id": source.id})


@endpoint(("GET",))
def contract_timeline(request, pk):
    """合同时间线（审计 / 审批 / 版本 / 义务事件合并按时间倒序）。"""
    contract = get_contract(request.user, pk)
    events = []
    for row in contract.audits.all()[:200]:
        events.append({"type": "audit", "at": iso(row.created_at),
                       "title": state.ACTION_LABELS.get(row.action, row.action),
                       "detail": row.note, "payload": row.payload or {}})
    for row in contract.approvals.all():
        if row.decided_at:
            events.append({"type": "approval", "at": iso(row.decided_at),
                           "title": f"审批：{row.node_name}",
                           "detail": row.opinion,
                           "payload": {"decision": row.decision}})
    for row in contract.versions.all()[:100]:
        events.append({"type": "version", "at": iso(row.created_at),
                       "title": f"版本 v{row.version_no}",
                       "detail": row.change_summary, "payload": {}})
    for row in ContractObligation.objects.filter(
            contract=contract).prefetch_related("events")[:200]:
        for event in row.events.all()[:50]:
            events.append({"type": "obligation", "at": iso(event.happened_at),
                           "title": f"履约：{event.action}",
                           "detail": event.note,
                           "payload": {"obligation_id": row.id}})
    events.sort(key=lambda item: item["at"] or "", reverse=True)
    return ok({"contract_id": contract.id, "items": events[:200],
               "count": len(events)})


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def versions_list(request, pk):
    """版本列表（新到旧，标注当前版本）。"""
    contract = get_contract(request.user, pk)
    rows = contract.versions.all().order_by("-version_no")
    items = [{
        "id": row.id,
        "version_no": row.version_no,
        "change_summary": row.change_summary,
        "is_current": row.is_current,
        "length": len(row.body_snapshot or ""),
        "created_by": user_dict(row.created_by or row.owner),
        "created_at": iso(row.created_at),
    } for row in rows]
    return ok({"items": items, "count": len(items)})


@endpoint()
def version_create(request, pk):
    """手动创建版本快照（用于线下改稿留痕）。"""
    contract = get_contract(request.user, pk, write=True)
    body = req_str(request, "body", max_len=0)
    summary = opt_str(request, "change_summary", "手动快照", max_len=0)
    with transaction.atomic():
        version = services.create_version(contract, request.user, body, summary)
        _write_audit(contract, "update", request.user,
                     f"创建版本 #{version.version_no}")
    return ok({"id": version.id, "version_no": version.version_no,
               "is_current": version.is_current})


@endpoint(("GET",))
def version_detail(request, pk):
    """版本详情（含正文快照与所属合同）。"""
    version = ContractVersion.objects.select_related("contract").filter(pk=pk).first()
    if version is None:
        raise ValueError("版本不存在")
    if not is_visible(version.contract, request.user):
        raise ValueError("无权访问该版本")
    return ok({
        "id": version.id,
        "contract_id": version.contract_id,
        "version_no": version.version_no,
        "body_snapshot": version.body_snapshot,
        "change_summary": version.change_summary,
        "is_current": version.is_current,
        "created_by": user_dict(version.created_by or version.owner),
        "created_at": iso(version.created_at),
    })


@endpoint(("GET",))
def versions_compare(request):
    """版本对比（条款级 diff；支持 id 或 version_no 指定两个版本）。"""
    left_id = opt_num(request, "left_id", None, integer=True, minimum=1)
    right_id = opt_num(request, "right_id", None, integer=True, minimum=1)
    if not left_id or not right_id:
        raise ValueError("需要同时提供 left_id 与 right_id")
    left = ContractVersion.objects.select_related("contract").filter(pk=int(left_id)).first()
    right = ContractVersion.objects.select_related("contract").filter(pk=int(right_id)).first()
    if left is None or right is None:
        raise ValueError("对比版本不存在")
    if left.contract_id != right.contract_id:
        raise ValueError("只能对比同一合同的两个版本")
    if not is_visible(left.contract, request.user):
        raise ValueError("无权访问该合同版本")
    diff = services.diff_versions(left.body_snapshot, right.body_snapshot)
    return ok({"left": {"id": left.id, "version_no": left.version_no},
               "right": {"id": right.id, "version_no": right.version_no},
               **diff})


@endpoint()
def version_rollback(request, pk):
    """回滚到指定版本（复制成新版本，不删历史）。"""
    version = ContractVersion.objects.select_related("contract").filter(pk=pk).first()
    if version is None:
        raise ValueError("版本不存在")
    contract = version.contract
    if not can_write(request.user, contract):
        raise ValueError("无权修改该合同")
    if contract.status == "archived":
        raise ValueError("已归档合同不能回滚版本")
    with transaction.atomic():
        new_version = services.rollback_version(
            contract, version, request.user, opt_str(request, "note", "", max_len=0))
    return ok({"contract_id": contract.id, "restored_from": version.version_no,
               "new_version": new_version.version_no, "id": new_version.id})


# ---------------------------------------------------------------------------
# 参与方
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def parties_list(request, pk):
    """参与方列表（按签署顺序）。"""
    contract = get_contract(request.user, pk)
    items = [party_dict(row) for row in contract.parties.all()]
    return ok({"items": items, "count": len(items)})


@endpoint()
def party_create(request, pk):
    """新增参与方（角色/主体类型校验，签署顺序缺省取当前最大值 +1）。"""
    contract = get_contract(request.user, pk, write=True)
    role = opt_str(request, "role", "party_b")
    if role not in PARTY_ROLES:
        raise ValueError(f"参与方角色不支持: {role}")
    party_type = opt_str(request, "party_type", "company")
    if party_type not in PARTY_TYPES:
        raise ValueError(f"主体类型不支持: {party_type}")
    sign_order = opt_num(request, "sign_order", None, integer=True, minimum=1)
    if sign_order is None:
        current = contract.parties.order_by("-sign_order").values_list(
            "sign_order", flat=True).first() or 0
        sign_order = current + 1
    row = ContractParty.objects.create(
        owner=request.user,
        contract=contract,
        name=req_str(request, "name", max_len=200),
        party_type=party_type,
        credit_code=opt_str(request, "credit_code", max_len=40),
        contact=opt_str(request, "contact", max_len=60),
        phone=opt_str(request, "phone", max_len=40),
        address=opt_str(request, "address", max_len=200),
        role=role,
        sign_order=int(sign_order),
        remark=opt_str(request, "remark", max_len=0),
    )
    if not contract.counterparty_name and role == "party_b":
        contract.counterparty_name = row.name
        contract.touch()
        contract.save(update_fields=["counterparty_name", "updated_at"])
    return ok(party_dict(row))


@endpoint()
def party_update(request, pk):
    """更新参与方信息（不允许改所属合同）。"""
    party = ContractParty.objects.select_related("contract").filter(pk=pk).first()
    if party is None:
        raise ValueError("参与方不存在")
    if not can_write(request.user, party.contract):
        raise ValueError("无权修改该合同")
    if has(request, "name"):
        party.name = req_str(request, "name", max_len=200)
    if has(request, "party_type"):
        value = opt_str(request, "party_type", party.party_type)
        if value not in PARTY_TYPES:
            raise ValueError(f"主体类型不支持: {value}")
        party.party_type = value
    if has(request, "role"):
        value = opt_str(request, "role", party.role)
        if value not in PARTY_ROLES:
            raise ValueError(f"参与方角色不支持: {value}")
        party.role = value
    if has(request, "credit_code"):
        party.credit_code = opt_str(request, "credit_code", max_len=40)
    if has(request, "contact"):
        party.contact = opt_str(request, "contact", max_len=60)
    if has(request, "phone"):
        party.phone = opt_str(request, "phone", max_len=40)
    if has(request, "address"):
        party.address = opt_str(request, "address", max_len=200)
    if has(request, "sign_order"):
        party.sign_order = int(req_num(request, "sign_order", party.sign_order,
                                       minimum=1, maximum=1000, integer=True))
    if has(request, "remark"):
        party.remark = opt_str(request, "remark", max_len=0)
    party.touch()
    party.save()
    return ok(party_dict(party))


@endpoint()
def party_delete(request, pk):
    """删除参与方（合同进入签署后不允许删，已签主体是法律事实）。"""
    party = ContractParty.objects.select_related("contract").filter(pk=pk).first()
    if party is None:
        raise ValueError("参与方不存在")
    contract = party.contract
    if not can_write(request.user, contract):
        raise ValueError("无权修改该合同")
    if contract.status in ("signing", "active", "expiring", "completed", "expired"):
        raise ValueError("合同已进入签署/履行阶段，不能删除参与方")
    party_id = party.id
    party.delete()
    return ok({"deleted": True, "id": party_id})


# ---------------------------------------------------------------------------
# 签署记录
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def signatures_list(request, pk):
    """签署记录列表（含指纹与状态）。"""
    contract = get_contract(request.user, pk)
    rows = contract.signatures.select_related("party", "signer")
    items = [signature_dict(row) for row in rows]
    signed = sum(1 for row in rows if row.status == "signed")
    return ok({"items": items, "count": len(items), "signed": signed,
               "parties": contract.parties.count()})


@endpoint()
def signature_create(request, pk):
    """创建签署记录并生成指纹（sign_now=True 时立即标记已签署）。"""
    contract = get_contract(request.user, pk, write=True)
    if contract.status not in ("approved", "signing"):
        raise ValueError("仅在已批准或签署中的合同可登记签署")
    method = opt_str(request, "method", "electronic")
    if method not in SIGNATURE_METHODS:
        raise ValueError(f"签署方式不支持: {method}")
    party = None
    party_id = opt_num(request, "party_id", None, integer=True, minimum=1)
    if party_id:
        party = _party_or_error(contract, int(party_id))
    signer_name = opt_str(request, "signer_name",
                          (party.contact or party.name) if party else "",
                          max_len=60)
    if not signer_name.strip():
        raise ValueError("缺少必填参数: signer_name")
    if not contract.current_version_id:
        raise ValueError("合同还没有正文版本，无法生成签署指纹")
    sign_now = opt_bool(request, "sign_now", True)
    signed_at = timezone.now() if sign_now else None
    with transaction.atomic():
        row = ContractSignature.objects.create(
            owner=request.user,
            contract=contract,
            party=party,
            signer_name=signer_name,
            signer=request.user if sign_now else None,
            method=method,
            signed_at=signed_at,
            status="signed" if sign_now else "pending",
            hash_fingerprint=(services.sign_fingerprint(contract, signer_name, signed_at)
                              if sign_now else ""),
            remark=opt_str(request, "remark", max_len=0),
        )
        if party and sign_now:
            party.signed = True
            party.touch()
            party.save(update_fields=["signed", "updated_at"])
        _write_audit(contract, "sign", request.user,
                     f"登记签署：{signer_name}（{method}）",
                     {"signature_id": row.id, "fingerprint": row.hash_fingerprint})
    return ok(signature_dict(row))


@endpoint()
def signature_status(request, pk):
    """更新签署状态（signed 时补指纹；拒签/撤销需原因）。"""
    row = ContractSignature.objects.select_related("contract").filter(pk=pk).first()
    if row is None:
        raise ValueError("签署记录不存在")
    if not can_write(request.user, row.contract):
        raise ValueError("无权修改该合同")
    target = opt_str(request, "status", "signed")
    if target not in SIGNATURE_STATUS:
        raise ValueError(f"签署状态不支持: {target}")
    if row.status == "revoked":
        raise ValueError("已撤销的签署记录不能再次变更")
    if target == "signed":
        if row.status == "signed":
            raise ValueError("该记录已签署")
        signed_at = timezone.now()
        row.signed_at = signed_at
        row.status = "signed"
        row.signer = request.user if getattr(request.user, "pk", None) else row.signer
        row.hash_fingerprint = services.sign_fingerprint(
            row.contract, row.signer_name, signed_at)
        if row.party_id:
            row.party.signed = True
            row.party.touch()
            row.party.save(update_fields=["signed", "updated_at"])
        note = "签署完成"
    elif target == "pending":
        row.status = "pending"
        row.signed_at = None
        row.hash_fingerprint = ""
        note = "重置为待签署"
    else:
        if not opt_str(request, "reason", "", max_len=0).strip():
            raise ValueError("拒签或撤销必须填写原因")
        row.status = target
        note = f"{target}: {opt_str(request, 'reason', '', max_len=0)}"
    row.touch()
    row.save()
    _write_audit(row.contract, "sign", request.user, note,
                 {"signature_id": row.id, "status": row.status})
    return ok({"id": row.id, "status": row.status,
               "hash_fingerprint": row.hash_fingerprint,
               "verified": services.verify_fingerprint(row) if row.status == "signed" else None})


# ---------------------------------------------------------------------------
# 附件与标签
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def attachments_list(request, pk):
    """附件元数据列表（不返回文件内容）。"""
    contract = get_contract(request.user, pk)
    items = [attachment_dict(row) for row in contract.attachments.all()]
    return ok({"items": items, "count": len(items),
               "total_size": sum(row.file_size for row in contract.attachments.all())})


@endpoint()
def attachment_create(request, pk):
    """登记附件元数据（文件名/大小/MIME/存储键/校验和）。"""
    contract = get_contract(request.user, pk, write=True)
    kind = opt_str(request, "kind", "attachment")
    if kind not in ATTACHMENT_KINDS:
        raise ValueError(f"资料类型不支持: {kind}")
    size = int(opt_num(request, "file_size", 0, minimum=0, maximum=2 ** 40, integer=True))
    row = ContractAttachment.objects.create(
        owner=request.user,
        contract=contract,
        file_name=req_str(request, "file_name", max_len=200),
        kind=kind,
        file_size=size,
        mime=opt_str(request, "mime", max_len=100),
        storage_key=opt_str(request, "storage_key", max_len=300),
        checksum=opt_str(request, "checksum", max_len=64),
        uploaded_by=request.user,
        remark=opt_str(request, "remark", max_len=0),
    )
    return ok(attachment_dict(row))


@endpoint()
def attachment_delete(request, pk):
    """删除附件元数据（仅元数据，文件由 files 应用自行治理）。"""
    row = ContractAttachment.objects.select_related("contract").filter(pk=pk).first()
    if row is None:
        raise ValueError("附件不存在")
    if not can_write(request.user, row.contract):
        raise ValueError("无权修改该合同")
    row_id = row.id
    row.delete()
    return ok({"deleted": True, "id": row_id})


@endpoint(("GET",))
def tags_list(request):
    """标签列表（本人标签，按使用次数倒序）。"""
    rows = ContractTag.objects.filter(owner=request.user).order_by("-usage_count", "name")
    items = [tag_dict(row) for row in rows]
    return ok({"items": items, "count": len(items)})


@endpoint()
def tag_create(request):
    """创建标签（同名幂等：已存在直接返回原标签）。"""
    name = req_str(request, "name", max_len=40).strip()
    existing = ContractTag.objects.filter(owner=request.user, name=name).first()
    if existing:
        return ok({**tag_dict(existing), "created": False})
    row = ContractTag.objects.create(
        owner=request.user,
        name=name,
        color=opt_str(request, "color", "#409EFF", max_len=20),
    )
    return ok({**tag_dict(row), "created": True})


@endpoint()
def tag_delete(request, pk):
    """删除标签（同时解除与合同的关联）。"""
    row = ContractTag.objects.filter(pk=pk, owner=request.user).first()
    if row is None:
        raise ValueError("标签不存在")
    row_id = row.id
    with transaction.atomic():
        row.contracts.clear()
        row.delete()
    return ok({"deleted": True, "id": row_id})


@endpoint()
def contract_tags(request, pk):
    """设置合同标签（整体替换；标签必须是本人创建的）。"""
    contract = get_contract(request.user, pk, write=True)
    ids = int_list(p(request, "tag_ids") or [], "tag_ids", max_items=30)
    tags = list(ContractTag.objects.filter(owner=request.user, id__in=ids))
    if len(tags) != len(ids):
        raise ValueError("存在不属于当前用户的标签")
    with transaction.atomic():
        contract.tags.set(tags)
        # 使用次数按「当前关联数」重算：比每次增减更耐得住并发与重复保存
        for tag in tags:
            tag.usage_count = tag.contracts.count()
            tag.save(update_fields=["usage_count"])
    return ok({"contract_id": contract.id,
               "tags": [tag_dict(tag) for tag in contract.tags.all()]})


# ---------------------------------------------------------------------------
# 审计与导出
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def contract_audit(request, pk):
    """合同审计流水（按动作筛选，追加型日志只读，不支持改删）。"""
    contract = get_contract(request.user, pk)
    qs = (contract.audits.select_related("actor", "owner")
          .order_by("-created_at", "-id"))
    action = opt_str(request, "action")
    if action:
        qs = qs.filter(action=action)
    page, size = page_args(request)
    total = qs.count()
    start = (page - 1) * size
    rows = list(qs[start:start + size])
    return ok(page_payload([audit_dict(row) for row in rows], total, page, size))


@endpoint(("GET",))
def contract_export(request, pk):
    """合同归档包：主档 + 参与方 + 义务 + 里程碑 + 付款 + 签署 + 版本摘要。

    导出刻意返回结构化 JSON 而不是拼一份 HTML：法务归档需要可机读，
    渲染成 PDF 属于前端/打印服务的事，后端只负责把「同一时点」的数据
    装进一个响应，避免调用方分七八次请求时读到互相矛盾的状态。
    """
    contract = get_contract(request.user, pk)
    today = timezone.localdate()
    obligations = contract.obligations.all().order_by("due_date", "id")
    milestones = contract.milestones.all().order_by("plan_date", "id")
    payments = contract.payments.all().order_by("period_no", "id")
    signatures = contract.signatures.select_related("party", "signer")
    versions = contract.versions.all().order_by("-version_no")
    return ok({
        "exported_at": iso(timezone.now()),
        "contract": contract_dict(contract, detail=True),
        "parties": [party_dict(row) for row in contract.parties.all()],
        "obligations": {
            "total": obligations.count(),
            "done": obligations.filter(status="done").count(),
            "overdue": sum(1 for row in obligations if row.is_overdue(today)),
            "items": [{
                "id": row.id,
                "content": row.content,
                "cycle": row.cycle,
                "due_date": iso(row.due_date),
                "status": row.status,
                "priority": row.priority,
                "party_name": row.party_name,
            } for row in obligations[:200]],
        },
        "milestones": [{
            "id": row.id,
            "name": row.name,
            "plan_date": iso(row.plan_date),
            "actual_date": iso(row.actual_date),
            "status": row.status,
            "amount": money_str(row.amount),
        } for row in milestones],
        "payments": [payment_dict(row) for row in payments],
        "signatures": [signature_dict(row) for row in signatures],
        "versions": [{
            "id": row.id,
            "version_no": row.version_no,
            "is_current": row.is_current,
            "change_summary": row.change_summary,
            "created_at": iso(row.created_at),
            "length": len(row.body_snapshot or ""),
        } for row in versions],
        "reminders": contract.reminders.count(),
        "risks": contract.risks.count(),
        "attachments": contract.attachments.count(),
    })


@endpoint(("GET",))
def contract_tags_detail(request, pk):
    """合同标签明细（含颜色与使用次数，供详情页只读展示）。"""
    contract = get_contract(request.user, pk)
    rows = contract.tags.all().order_by("-usage_count", "name")
    items = [tag_dict(row) for row in rows]
    return ok(page_payload(items, len(items), 1, 200,
                           contract_id=contract.id))
