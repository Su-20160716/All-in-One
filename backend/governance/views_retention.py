# -*- coding: utf-8 -*-
"""保留期与同意接口：保留规则 CRUD + 扫描 / 到期列表 / 执行 + 同意记录 CRUD。

保留期闭环：
1. 规则（RetentionRule）定义「某类资源保留多少天、到期做什么」；
2. 扫描（scan）把到期候选写入台账（RetentionAction），幂等；
3. 执行（execute）只允许 planned → executed 迁移一次，并同步数据资产状态。

同意闭环：
同意记录必须能回答「谁、为什么目的、什么时候同意/撤回、依据哪份证据」，
因此有效性判定同时校验状态、目的与有效期三项。
"""
from django.db import transaction
from django.utils import timezone

from devtools.common import endpoint, ok

from governance import services
from governance.models import (
    CONSENT_STATUS,
    RETENTION_ACTIONS,
    RETENTION_KINDS,
    RETENTION_RUN_STATUS,
    ConsentRecord,
    RetentionAction,
    RetentionRule,
)
from governance.views_common import (
    apply_search,
    filter_bool,
    filter_choice,
    filter_int,
    get_consent,
    get_retention_action,
    get_retention_rule,
    paginate,
    param_bool,
    param_choice,
    param_datetime,
    param_date,
    param_int,
    param_str,
    param_text,
    scoped,
)

CONSENT_SEARCH_FIELDS = ("data_subject", "purpose", "source", "evidence_ref")


# ---------------------------------------------------------------------------
# 保留规则
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def retention_rule_list(request):
    """保留规则列表（按资源类型/启用状态过滤）。"""
    qs = scoped(RetentionRule, request.user)
    qs = filter_choice(qs, request, "resource_kind", RETENTION_KINDS)
    qs = filter_choice(qs, request, "due_action", RETENTION_ACTIONS)
    qs = filter_bool(qs, request, "enabled")
    return paginate(qs.order_by("resource_kind"), request)


@endpoint()
def retention_rule_create(request):
    """新建保留规则（同用户同资源类型只允许一条）。"""
    resource_kind = param_choice(request, "resource_kind", RETENTION_KINDS,
                                 default="data_asset")
    if RetentionRule.objects.filter(owner=request.user, resource_kind=resource_kind).exists():
        raise ValueError("该资源类型的保留规则已存在，请直接更新")
    rule = RetentionRule.objects.create(
        owner=request.user,
        resource_kind=resource_kind,
        retention_days=param_int(request, "retention_days", default=365, minimum=1,
                                 maximum=36500),
        due_action=param_choice(request, "due_action", RETENTION_ACTIONS, default="archive"),
        condition=param_str(request, "condition", max_len=200),
        enabled=bool(param_bool(request, "enabled", True)),
    )
    return ok(rule.to_dict())


@endpoint(("GET",))
def retention_rule_detail(request, pk):
    """保留规则详情：附带该规则已产生的动作统计。"""
    rule = get_retention_rule(pk, request.user)
    data = rule.to_dict()
    actions = rule.actions.all()
    data["action_total"] = actions.count()
    data["planned"] = actions.filter(status="planned").count()
    data["executed"] = actions.filter(status="executed").count()
    return ok(data)


@endpoint()
def retention_rule_update(request, pk):
    """更新保留规则（天数/动作/条件/启停）。"""
    rule = get_retention_rule(pk, request.user, write=True)
    rule.retention_days = param_int(request, "retention_days", default=rule.retention_days,
                                    minimum=1, maximum=36500)
    rule.due_action = param_choice(request, "due_action", RETENTION_ACTIONS,
                                   default=rule.due_action)
    rule.condition = param_str(request, "condition", default=rule.condition, max_len=200)
    enabled = param_bool(request, "enabled", None)
    if enabled is not None:
        rule.enabled = enabled
    rule.save()
    return ok(rule.to_dict())


@endpoint()
def retention_rule_delete(request, pk):
    """删除保留规则（已产生的动作台账保留，rule 置空）。"""
    rule = get_retention_rule(pk, request.user, write=True)
    with transaction.atomic():
        rule.delete()
    return ok({"id": pk, "deleted": True})


@endpoint()
def retention_scan_view(request):
    """保留期扫描：生成/刷新到期台账（幂等，不产生重复记录）。"""
    at = param_date(request, "as_of")
    return ok(services.scan_retention(request.user, at=at))


@endpoint(("GET",))
def retention_due_view(request):
    """到期台账列表（默认只含待执行项）。"""
    at = param_date(request, "as_of")
    include_executed = param_bool(request, "include_executed", False)
    data = services.retention_due_list(request.user, at=at,
                                       include_executed=bool(include_executed))
    return ok(data)


@endpoint()
def retention_execute_view(request):
    """执行到期动作：只改状态并记录，重复执行返回 already_executed。"""
    action_id = param_int(request, "action_id", required=True, minimum=1)
    action_obj = get_retention_action(action_id, request.user, write=True)
    note = param_str(request, "note", max_len=200)
    result = services.execute_retention(action_obj, note=note)
    return ok(result)


@endpoint(("GET",))
def retention_action_list(request):
    """动作台账列表（按状态/资源类型过滤）。"""
    qs = scoped(RetentionAction, request.user)
    qs = filter_choice(qs, request, "resource_kind", RETENTION_KINDS)
    qs = filter_choice(qs, request, "action", RETENTION_ACTIONS)
    qs = filter_choice(qs, request, "status", RETENTION_RUN_STATUS)
    qs = filter_int(qs, request, "resource_id", "resource_id")
    return paginate(qs.order_by("due_on", "id"), request)


# ---------------------------------------------------------------------------
# 同意记录
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def consent_list(request):
    """同意记录列表：按状态/数据主体/目的筛选。"""
    qs = scoped(ConsentRecord, request.user)
    qs = apply_search(qs, request, CONSENT_SEARCH_FIELDS)
    subject = param_str(request, "data_subject", max_len=120)
    if subject:
        qs = qs.filter(data_subject=subject)
    return paginate(qs.order_by("-created_at"), request)


@endpoint()
def consent_create(request):
    """登记同意（授予时间缺省为当前，状态默认 granted）。"""
    granted_at = param_datetime(request, "granted_at") or timezone.now()
    consent = ConsentRecord.objects.create(
        owner=request.user,
        data_subject=param_str(request, "data_subject", required=True, max_len=120),
        purpose=param_str(request, "purpose", required=True, max_len=200),
        status=param_choice(request, "status", CONSENT_STATUS, default="granted"),
        granted_at=granted_at,
        expires_on=param_date(request, "expires_on"),
        source=param_str(request, "source", max_len=80),
        evidence_ref=param_str(request, "evidence_ref", max_len=200),
        note=param_text(request, "note"),
    )
    return ok(consent.to_dict())


@endpoint(("GET",))
def consent_detail(request, pk):
    """同意详情：附带当前有效性判定。"""
    consent = get_consent(pk, request.user)
    data = consent.to_dict()
    data["validity"] = services.consent_validity(consent)
    return ok(data)


@endpoint()
def consent_update(request, pk):
    """更新同意记录（目的/来源/证据/有效期）。"""
    consent = get_consent(pk, request.user, write=True)
    if consent.status == "withdrawn":
        raise ValueError("已撤回的同意不可修改，请重新登记")
    consent.purpose = param_str(request, "purpose", default=consent.purpose, max_len=200)
    consent.source = param_str(request, "source", default=consent.source, max_len=80)
    consent.evidence_ref = param_str(request, "evidence_ref", default=consent.evidence_ref,
                                     max_len=200)
    consent.expires_on = param_date(request, "expires_on") or consent.expires_on
    consent.note = param_text(request, "note", default=consent.note)
    consent.granted_at = param_datetime(request, "granted_at", default=consent.granted_at)
    consent.save()
    return ok(consent.to_dict())


@endpoint()
def consent_withdraw(request, pk):
    """撤回同意：置 withdrawn 并记录撤回时间（重复撤回幂等）。"""
    consent = get_consent(pk, request.user, write=True)
    if consent.status == "withdrawn":
        return ok({"consent": consent.to_dict(), "already_withdrawn": True})
    consent.status = "withdrawn"
    consent.withdrawn_at = param_datetime(request, "withdrawn_at") or timezone.now()
    if param_text(request, "note"):
        consent.note = param_text(request, "note")
    consent.save(update_fields=["status", "withdrawn_at", "note", "updated_at"])
    return ok({"consent": consent.to_dict(), "already_withdrawn": False})


@endpoint(("GET",))
def consent_validity_view(request, pk):
    """校验同意有效性：可传 purpose 校验目的匹配。"""
    consent = get_consent(pk, request.user)
    purpose = param_str(request, "purpose", max_len=200)
    return ok(services.consent_validity(consent, purpose=purpose or None))


@endpoint(("GET",))
def consent_summary_view(request):
    """同意池概览：状态分布、目的分布与近 30 天撤回数。"""
    return ok(services.consent_summary(request.user))
