# -*- coding: utf-8 -*-
"""contracts 通用助手：入参解析、分页、对象渲染与权限入口。

分层约定：
- 视图层只做「取参 → 调服务 → 渲染」，所有可复用的取参与渲染逻辑放这里；
- 权限一律走 core.scoping：读用 is_visible/scope_queryset，写用 can_write，
  管理员例外只在 accounts 的角色里配，不在业务层开后门；
- 金额统一 Decimal、日期统一 date、时间统一 aware datetime，
  渲染时统一转 ISO 字符串，避免 DRF 对 Decimal 的序列化形态前后不一致。
"""
from datetime import date, datetime, time
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.scoping import can_write, is_visible, owner_qs, scope_queryset

from contracts.models import (APPROVAL_DECISION_LABELS, ATTACHMENT_KIND_LABELS,
                              AMENDMENT_STATUS_LABELS, AMENDMENT_TYPE_LABELS,
                              CONTRACT_STATUS_LABELS, CONTRACT_TYPE_LABELS,
                              CURRENCY_LABELS, MILESTONE_STATUS_LABELS,
                              OBLIGATION_CYCLE_LABELS, OBLIGATION_EVENT_ACTION_LABELS,
                              OBLIGATION_STATUS_LABELS, PARTY_ROLE_LABELS,
                              PARTY_TYPE_LABELS, PAYMENT_STATUS_LABELS,
                              REMINDER_CHANNEL_LABELS, REMINDER_KIND_LABELS,
                              RENEWAL_MODES, RENEWAL_MODE_LABELS, RENEWAL_STATUS_LABELS,
                              RENEWAL_TYPE_LABELS, RISK_LEVEL_LABELS,
                              RISK_STATUS_LABELS, SIGNATURE_METHOD_LABELS,
                              SIGNATURE_STATUS_LABELS, TEMPLATE_STATUS_LABELS,
                              Contract, to_decimal)

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# 入参解析
# ---------------------------------------------------------------------------


def dec(value, field="金额", minimum=None, maximum=None, allow_zero=True):
    """入参 → Decimal（两位小数），并做区间校验。

    拒绝 float 直接入库：调用方无论传 "12.5"、12.5 还是 Decimal，都在这里
    统一成 Decimal("12.50")，保证金额字段不会出现 12.499999999 这种值。
    """
    amount = to_decimal(value, field)
    if not allow_zero and amount == 0:
        raise ValueError(f"{field} 必须大于 0")
    if minimum is not None and amount < Decimal(str(minimum)):
        raise ValueError(f"{field} 不能小于 {minimum}")
    if maximum is not None and amount > Decimal(str(maximum)):
        raise ValueError(f"{field} 不能大于 {maximum}")
    return amount


def parse_day(value, field="日期", required=False, default=None):
    """字符串 → date；空值按 required 决定报错还是回落默认。"""
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {field}")
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_date(str(value).strip())
    if parsed is None:
        raise ValueError(f"{field} 需为 YYYY-MM-DD")
    return parsed


def parse_time(value, field="时间", required=False):
    """字符串 → aware datetime；日期串按当天零点处理，便于统一比较。"""
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {field}")
        return None
    parsed = parse_datetime(str(value).strip())
    if parsed is None:
        day = parse_date(str(value).strip())
        if day is None:
            raise ValueError(f"{field} 需为 YYYY-MM-DD[ HH:MM[:SS]]")
        parsed = datetime.combine(day, time.min)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def iso(value):
    """安全 ISO 化：date / datetime / None 统一处理，前端不用做类型判断。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def money_str(value):
    """金额统一输出两位小数字符串：JSON 里不放 float，防止前端二次求和失真。"""
    return f"{to_decimal(value):.2f}"


def has(request, key):
    """判断调用方是否显式传了某个字段。

    局部更新必须区分「没传」与「传了空字符串」：把空串当成清空是业务语义，
    而缺省当成清空会把用户没碰过的字段一起抹掉。
    """
    if request.method == "GET":
        return key in request.query_params
    return isinstance(request.data, dict) and key in request.data


def req_dict(request, key, default=None):
    """取 JSON 对象入参；字符串形态的 JSON 也接受（表单/网关常见），非法报中文错。"""
    import json

    from devtools.common import p

    value = p(request, key, default)
    if value is None:
        return {} if default is None else default
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 必须是 JSON 对象")
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是 JSON 对象")
    return value


def req_list_arg(request, key, default=None, max_items=200):
    """取数组入参：限制条数，防止一次提交上万条把事务拖死。"""
    from devtools.common import p

    value = p(request, key, default)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_items:
        raise ValueError(f"参数 {key} 最多 {max_items} 项")
    return list(value)


def int_list(value, field="ids", max_items=200):
    """入参 → 去重正整数列表（标签、参与方等批量接口共用）。"""
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]
    if len(value) > max_items:
        raise ValueError(f"参数 {field} 最多 {max_items} 项")
    out = []
    for item in value:
        try:
            num = int(item)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {field} 必须是整数数组")
        if num <= 0:
            raise ValueError(f"参数 {field} 必须是正整数")
        if num not in out:
            out.append(num)
    return out


# ---------------------------------------------------------------------------
# 查询：分页 / 关键字
# ---------------------------------------------------------------------------


def page_args(request):
    """统一取 page / page_size：page_size 上限 200，防止一次拉爆内存。"""
    from devtools.common import opt_num

    page = int(opt_num(request, "page", 1, minimum=1, maximum=100000, integer=True))
    size = int(opt_num(request, "page_size", DEFAULT_PAGE_SIZE, minimum=1,
                       maximum=MAX_PAGE_SIZE, integer=True))
    return page, size


def slice_page(qs, page, size):
    """按页切片；count 用 queryset 自身计数，供前端分页器使用。"""
    total = qs.count()
    start = (page - 1) * size
    return list(qs[start:start + size]), total


def page_payload(items, count, page, size, **extra):
    """统一列表响应体：所有列表接口都必须返回这四件套。

    extra 用于附加汇总字段（如 by_kind），保持四件套不变、扩展字段平行放置，
    前端分页逻辑只认这四个键，不会被额外字段干扰。
    """
    payload = {"items": items, "count": count, "page": page, "page_size": size}
    payload.update(extra)
    return payload


def apply_q(qs, q, fields):
    """关键字模糊搜索：字段为空串自动跳过，不做无意义的 __icontains。"""
    q = (q or "").strip()
    if not q:
        return qs
    cond = Q()
    for name in fields:
        cond |= Q(**{f"{name}__icontains": q})
    return qs.filter(cond)


def list_queryset(request, qs, fields, status_field="status", extra_filters=None):
    """列表通用流程：关键字 → 状态 → 附加过滤 → 分页。

    extra_filters 为 {参数名: (orm 字段, 转换函数)}，转换失败给中文提示。
    """
    from devtools.common import opt_str, p

    page, size = page_args(request)
    qs = apply_q(qs, opt_str(request, "q"), fields)
    status = opt_str(request, "status")
    if status and status_field:
        qs = qs.filter(**{status_field: status})
    for arg, (orm_field, caster) in (extra_filters or {}).items():
        raw = p(request, arg)
        if raw in (None, ""):
            continue
        try:
            value = caster(raw)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {arg} 格式不正确")
        qs = qs.filter(**{orm_field: value})
    rows, total = slice_page(qs, page, size)
    return rows, total, page, size


# ---------------------------------------------------------------------------
# 权限入口
# ---------------------------------------------------------------------------


def visible_contracts(user):
    """合同台账的读范围：统一走 core.scoping.scope_queryset。"""
    return scope_queryset(Contract.objects.all(), user)


def writable_contracts(user):
    """写范围：严格 owner 收口（core.scoping.owner_qs）。"""
    return owner_qs(Contract.objects.all(), user)


def get_contract(user, pk, write=False):
    """取合同并校验行级权限；写操作额外要求 can_write。

    读用 is_visible（数据范围可见即可），写用 can_write（owner-only），
    两者刻意区分，避免「部门可见」被当成「部门可改」。
    """
    try:
        contract = Contract.objects.get(pk=pk)
    except Contract.DoesNotExist:
        raise ValueError("合同不存在")
    if not is_visible(contract, user):
        raise ValueError("无权访问该合同")
    if write and not can_write(user, contract):
        raise ValueError("无权修改该合同")
    return contract


def get_child(model, contract, pk, label="对象"):
    """取合同的子对象：先限定 contract，再取主键，天然防止跨合同越权。"""
    try:
        return model.objects.get(pk=pk, contract=contract)
    except model.DoesNotExist:
        raise ValueError(f"{label}不存在或不属于该合同")


def can_write_contract(user, contract):
    """给批量操作复用的布尔判定（不抛异常）。"""
    return can_write(user, contract)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------


def user_dict(user):
    """用户最小画像：只给 id / username / 昵称，避免把账号敏感字段带出接口。"""
    if not user:
        return None
    return {
        "id": getattr(user, "id", None),
        "username": getattr(user, "username", ""),
        "nickname": getattr(user, "nickname", "") or getattr(user, "username", ""),
    }


def party_dict(party):
    """参与方渲染：含角色与主体类型中文名，前端直接展示。"""
    return {
        "id": party.id,
        "contract_id": party.contract_id,
        "name": party.name,
        "party_type": party.party_type,
        "party_type_label": PARTY_TYPE_LABELS.get(party.party_type, party.party_type),
        "credit_code": party.credit_code,
        "contact": party.contact,
        "phone": party.phone,
        "address": party.address,
        "role": party.role,
        "role_label": PARTY_ROLE_LABELS.get(party.role, party.role),
        "sign_order": party.sign_order,
        "signed": party.signed,
        "remark": party.remark,
        "created_at": iso(party.created_at),
        "updated_at": iso(party.updated_at),
    }


def contract_dict(contract, detail=False):
    """合同渲染：列表给轻量字段，详情额外带期限、金额派生与参与方摘要。"""
    data = {
        "id": contract.id,
        "number": contract.number,
        "name": contract.name,
        "contract_type": contract.contract_type,
        "contract_type_label": CONTRACT_TYPE_LABELS.get(contract.contract_type,
                                                       contract.contract_type),
        "amount": money_str(contract.amount),
        "currency": contract.currency,
        "currency_label": CURRENCY_LABELS.get(contract.currency, contract.currency),
        "sign_date": iso(contract.sign_date),
        "effective_date": iso(contract.effective_date),
        "expire_date": iso(contract.expire_date),
        "renewal_mode": contract.renewal_mode,
        "renewal_mode_label": RENEWAL_MODE_LABELS.get(contract.renewal_mode,
                                                     contract.renewal_mode),
        "risk_score": contract.risk_score,
        "status": contract.status,
        "status_label": CONTRACT_STATUS_LABELS.get(contract.status, contract.status),
        "owner": user_dict(contract.owner),
        "responsible": user_dict(contract.responsible),
        "counterparty_name": contract.counterparty_name,
        "template_id": contract.template_id,
        "current_version_id": contract.current_version_id,
        "remark": contract.remark,
        "created_at": iso(contract.created_at),
        "updated_at": iso(contract.updated_at),
    }
    if detail:
        payments = list(contract.payments.all())
        data["days_to_expiry"] = contract.days_to_expiry()
        data["expiry_bucket"] = contract.expiry_bucket()
        data["amount_paid"] = money_str(contract.paid_amount(payments))
        data["amount_planned"] = money_str(contract.planned_amount(payments))
        data["amount_unpaid"] = money_str(contract.unpaid_amount(payments))
        data["amount_overdue"] = money_str(contract.overdue_amount(payments))
        data["party_count"] = contract.parties.count()
        data["obligation_count"] = contract.obligations.count()
        data["milestone_count"] = contract.milestones.count()
        data["risk_count"] = contract.risks.count()
        data["tag_ids"] = list(contract.tags.values_list("id", flat=True))
        data["data"] = contract.data or {}
    return data


def obligation_dict(row, today=None):
    """义务渲染：附带是否逾期与剩余天数，前端不必再拿到期日自算。"""
    today = today or timezone.localdate()
    days = None
    if row.due_date:
        days = (row.due_date - today).days
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "party_id": row.party_id,
        "party_name": row.party_name or (row.party.name if row.party_id else ""),
        "content": row.content,
        "trigger": row.trigger,
        "cycle": row.cycle,
        "cycle_label": OBLIGATION_CYCLE_LABELS.get(row.cycle, row.cycle),
        "due_date": iso(row.due_date),
        "days_left": days,
        "responsible": user_dict(row.responsible),
        "responsible_name": row.responsible_name,
        "status": row.status,
        "status_label": OBLIGATION_STATUS_LABELS.get(row.status, row.status),
        "priority": row.priority,
        "series_uid": row.series_uid,
        "recurring_from_id": row.recurring_from_id,
        "is_overdue": row.is_overdue(today),
        "remark": row.remark,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def obligation_event_dict(event):
    """履约事件渲染：动作中文名 + 原/新截止日，便于审计时间线展示。"""
    return {
        "id": event.id,
        "obligation_id": event.obligation_id,
        "action": event.action,
        "action_label": OBLIGATION_EVENT_ACTION_LABELS.get(event.action, event.action),
        "note": event.note,
        "evidence": event.evidence,
        "actor": user_dict(event.actor),
        "happened_at": iso(event.happened_at),
        "from_due_date": iso(event.from_due_date),
        "to_due_date": iso(event.to_due_date),
    }


def milestone_dict(row):
    """里程碑渲染：延期标记与金额字符串。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "name": row.name,
        "plan_date": iso(row.plan_date),
        "actual_date": iso(row.actual_date),
        "status": row.status,
        "status_label": MILESTONE_STATUS_LABELS.get(row.status, row.status),
        "amount": money_str(row.amount),
        "is_late": row.is_late(),
        "remark": row.remark,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def amendment_dict(row):
    """变更单渲染。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "code": row.code,
        "change_type": row.change_type,
        "change_type_label": AMENDMENT_TYPE_LABELS.get(row.change_type,
                                                      row.change_type),
        "before_text": row.before_text,
        "after_text": row.after_text,
        "effective_date": iso(row.effective_date),
        "approval_status": row.approval_status,
        "approval_status_label": AMENDMENT_STATUS_LABELS.get(row.approval_status,
                                                            row.approval_status),
        "reason": row.reason,
        "approved_by": user_dict(row.approved_by),
        "decided_at": iso(row.decided_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def approval_dict(row):
    """审批节点渲染：含结论中文与审批人画像。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "node": row.node,
        "node_name": row.node_name,
        "approver": user_dict(row.approver),
        "decision": row.decision,
        "decision_label": APPROVAL_DECISION_LABELS.get(row.decision, row.decision),
        "opinion": row.opinion,
        "decided_at": iso(row.decided_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def signature_dict(row):
    """签署记录渲染。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "party_id": row.party_id,
        "party_name": row.party.name if row.party_id else "",
        "signer_name": row.signer_name,
        "signer": user_dict(row.signer),
        "method": row.method,
        "method_label": SIGNATURE_METHOD_LABELS.get(row.method, row.method),
        "hash_fingerprint": row.hash_fingerprint,
        "signed_at": iso(row.signed_at),
        "status": row.status,
        "status_label": SIGNATURE_STATUS_LABELS.get(row.status, row.status),
        "remark": row.remark,
        "created_at": iso(row.created_at),
    }


def payment_dict(row, today=None):
    """付款期次渲染：剩余额与逾期标记都由模型推导，接口不重复计算。"""
    today = today or timezone.localdate()
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "period_no": row.period_no,
        "plan_amount": money_str(row.plan_amount),
        "plan_date": iso(row.plan_date),
        "paid_amount": money_str(row.paid_amount),
        "paid_date": iso(row.paid_date),
        "remaining": money_str(row.remaining()),
        "status": row.status,
        "status_label": PAYMENT_STATUS_LABELS.get(row.status, row.status),
        "is_overdue": row.is_overdue(today),
        "remark": row.remark,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def renewal_dict(row):
    """续约记录渲染。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "renewal_type": row.renewal_type,
        "renewal_type_label": RENEWAL_TYPE_LABELS.get(row.renewal_type,
                                                     row.renewal_type),
        "new_expire_date": iso(row.new_expire_date),
        "remind_days": row.remind_days,
        "status": row.status,
        "status_label": RENEWAL_STATUS_LABELS.get(row.status, row.status),
        "note": row.note,
        "decided_at": iso(row.decided_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def risk_dict(row):
    """风险项渲染。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "title": row.title,
        "level": row.level,
        "level_label": RISK_LEVEL_LABELS.get(row.level, row.level),
        "description": row.description,
        "mitigation": row.mitigation,
        "status": row.status,
        "status_label": RISK_STATUS_LABELS.get(row.status, row.status),
        "score": row.score,
        "weight": row.weight(),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def attachment_dict(row):
    """附件元数据渲染：不含文件内容，只有指纹与存储键。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "file_name": row.file_name,
        "kind": row.kind,
        "kind_label": ATTACHMENT_KIND_LABELS.get(row.kind, row.kind),
        "file_size": row.file_size,
        "mime": row.mime,
        "storage_key": row.storage_key,
        "checksum": row.checksum,
        "uploaded_by": user_dict(row.uploaded_by),
        "remark": row.remark,
        "created_at": iso(row.created_at),
    }


def reminder_dict(row):
    """提醒记录渲染。"""
    return {
        "id": row.id,
        "contract_id": row.contract_id,
        "contract_number": row.contract.number if row.contract_id else "",
        "kind": row.kind,
        "kind_label": REMINDER_KIND_LABELS.get(row.kind, row.kind),
        "stage": row.stage,
        "channel": row.channel,
        "channel_label": REMINDER_CHANNEL_LABELS.get(row.channel, row.channel),
        "status": row.status,
        "message": row.message,
        "target_date": iso(row.target_date),
        "created_at": iso(row.created_at),
    }


def audit_dict(row):
    """审计渲染。"""
    return {
        "id": row.id,
        "action": row.action,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "note": row.note,
        "actor": user_dict(row.actor or row.owner),
        "payload": row.payload or {},
        "created_at": iso(row.created_at),
    }


def template_dict(row, with_body=False):
    """模板渲染：列表默认不带正文（正文可能很长），详情再带。"""
    data = {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "template_type": row.template_type,
        "template_type_label": CONTRACT_TYPE_LABELS.get(row.template_type,
                                                       row.template_type),
        "scene": row.scene,
        "version": row.version,
        "status": row.status,
        "status_label": TEMPLATE_STATUS_LABELS.get(row.status, row.status),
        "variables": row.variables or [],
        "variable_names": sorted(row.variable_names()),
        "clause_count": row.clauses.count(),
        "remark": row.remark,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
    if with_body:
        data["body"] = row.body
    return data


def clause_dict(row):
    """模板条款渲染。"""
    return {
        "id": row.id,
        "template_id": row.template_id,
        "library_id": row.library_id,
        "title": row.title,
        "body": row.body,
        "order": row.order,
        "optional": row.optional,
        "alt_group": row.alt_group,
        "risk_level": row.risk_level,
        "risk_level_label": RISK_LEVEL_LABELS.get(row.risk_level, row.risk_level),
        "variables": row.variables or [],
        "note": row.note,
        "updated_at": iso(row.updated_at),
    }


def library_clause_dict(row):
    """条款库条目渲染。"""
    return {
        "id": row.id,
        "category": row.category,
        "title": row.title,
        "body": row.body,
        "risk_level": row.risk_level,
        "risk_level_label": RISK_LEVEL_LABELS.get(row.risk_level, row.risk_level),
        "jurisdiction": row.jurisdiction,
        "tags": row.tags or [],
        "status": row.status,
        "usage_count": row.usage_count,
        "remark": row.remark,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def tag_dict(row):
    """标签渲染。"""
    return {
        "id": row.id,
        "name": row.name,
        "color": row.color,
        "usage_count": row.usage_count,
        "created_at": iso(row.created_at),
    }


# 目录用的枚举镜像：前端下拉一次取全，避免各页面自己硬编码
CATALOG_ENUMS = {
    "contract_status": CONTRACT_STATUS_LABELS,
    "contract_type": CONTRACT_TYPE_LABELS,
    "currency": CURRENCY_LABELS,
    "renewal_mode": RENEWAL_MODE_LABELS,
    "renewal_mode_keys": list(RENEWAL_MODES),
    "party_role": PARTY_ROLE_LABELS,
    "party_type": PARTY_TYPE_LABELS,
    "obligation_cycle": OBLIGATION_CYCLE_LABELS,
    "obligation_status": OBLIGATION_STATUS_LABELS,
    "milestone_status": MILESTONE_STATUS_LABELS,
    "amendment_type": AMENDMENT_TYPE_LABELS,
    "amendment_status": AMENDMENT_STATUS_LABELS,
    "signature_method": SIGNATURE_METHOD_LABELS,
    "payment_status": PAYMENT_STATUS_LABELS,
    "risk_level": RISK_LEVEL_LABELS,
    "risk_status": RISK_STATUS_LABELS,
    "reminder_kind": REMINDER_KIND_LABELS,
    "attachment_kind": ATTACHMENT_KIND_LABELS,
    "template_status": TEMPLATE_STATUS_LABELS,
}

