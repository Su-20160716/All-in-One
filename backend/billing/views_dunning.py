# -*- coding: utf-8 -*-
"""订阅计费 · 催收、税率与事件接口：催收(9) + 税率(4) + 事件(1) = 14 个。

催收是唯一会主动「停服务」的模块，因此把它设计成显式状态机：
策略（DunningPolicy）→ 步骤（DunningStep）→ 运行（DunningRun）。
推进只走 advance_dunning，重复调用/重复扫描都幂等，避免定时任务把
同一客户连续暂停两次或重复取消。

路由（挂在 /api/billing/ 下）：
    GET  dunning-policies/                 催收策略列表
    POST dunning-policies/create/          新建策略（含步骤）
    POST dunning-policies/<pk>/update/     更新策略/替换步骤
    POST dunning-policies/<pk>/delete/     删除策略（有运行记录时拒绝）
    POST dunning/start/                    对订阅启动催收
    GET  dunning/runs/                     催收记录列表
    GET  dunning/runs/<pk>/                催收记录详情
    POST dunning/runs/<pk>/advance/        推进下一步
    POST dunning/scan/                     批量推进到期催收
    GET  tax-rates/                        税率列表
    POST tax-rates/create/                 新建税率
    POST tax-rates/<pk>/update/            更新税率
    POST tax-rates/<pk>/delete/            删除税率
    GET  events/                           计费事件列表
"""
from django.db import transaction

from devtools.common import endpoint, ok, opt_str, req_str

from billing import serializers, services
from billing.models import (
    DUNNING_ACTIONS,
    DunningPolicy,
    DunningRun,
    DunningStep,
    TaxRate,
)
from billing.views_common import (
    apply_search,
    bool_param,
    choice_param,
    date_param,
    dict_param,
    filter_by,
    get_subscription,
    int_param,
    list_param,
    money_param,
    paginate,
)


def _parse_steps(request, required=False):
    """解析催收步骤：序号唯一、动作白名单、延迟天数非负。"""
    rows = list_param(request, "steps", required=required, max_len=50)
    if required and not rows:
        raise ValueError("催收策略至少需要一个步骤")
    parsed = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 个步骤格式不正确")
        sequence = int(row.get("sequence", index))
        if sequence < 1 or sequence > 1000:
            raise ValueError(f"第 {index} 个步骤序号必须在 1-1000 之间")
        if sequence in seen:
            raise ValueError(f"步骤序号 {sequence} 重复")
        seen.add(sequence)
        delay_days = int(row.get("delay_days", 0))
        if delay_days < 0 or delay_days > 3650:
            raise ValueError(f"第 {index} 个步骤延迟天数必须在 0-3650 之间")
        action = str(row.get("action") or "notify")
        if action not in DUNNING_ACTIONS:
            raise ValueError(f"第 {index} 个步骤动作必须是 {'/'.join(DUNNING_ACTIONS)} 之一")
        parsed.append({
            "sequence": sequence,
            "delay_days": delay_days,
            "action": action,
            "template": str(row.get("template") or "")[:5000],
            "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        })
    parsed.sort(key=lambda item: item["sequence"])
    delay = -1
    for row in parsed:
        if row["delay_days"] < delay:
            raise ValueError("步骤延迟天数必须随序号递增")
        delay = row["delay_days"]
    return parsed


def _replace_steps(policy, rows, owner):
    """整体替换策略步骤（运行中的 run 只记录序号，不会悬空）。"""
    DunningStep.objects.filter(policy=policy).delete()
    for row in rows:
        DunningStep.objects.create(
            owner=owner, policy=policy, sequence=row["sequence"],
            delay_days=row["delay_days"], action=row["action"],
            template=row["template"], metadata=row["metadata"],
        )


def _run_summary(result):
    """推进结果渲染。"""
    run = result["run"]
    return {
        "executed": result.get("executed", False),
        "action": result.get("action"),
        "step": result.get("step"),
        "reason": result.get("reason", ""),
        "subscription_status": result.get("subscription_status"),
        "run": serializers.dunning_run_dict(run, detail=True),
    }


# ===========================================================================
# 催收策略
# ===========================================================================


@endpoint(("GET",))
def dunning_policy_list(request):
    """催收策略列表（q/status + 分页）。"""
    qs = services.visible(DunningPolicy.objects.all(), request.user)
    qs = apply_search(qs, request, ["code", "name", "description"])
    return paginate(qs.order_by("id"), request,
                    lambda obj: serializers.dunning_policy_dict(obj, detail=True))


@endpoint()
def dunning_policy_create(request):
    """新建催收策略及步骤（步骤延迟天数需递增）。"""
    code = req_str(request, "code", max_len=60).strip()
    if DunningPolicy.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("策略编码已存在")
    steps = _parse_steps(request, required=True)
    with transaction.atomic():
        policy = DunningPolicy.objects.create(
            owner=request.user,
            code=code,
            name=req_str(request, "name", max_len=120).strip(),
            description=opt_str(request, "description", max_len=5000),
            status=choice_param(request, "status", ("active", "archived"),
                                "active", "策略状态"),
            metadata=dict_param(request, "metadata"),
        )
        _replace_steps(policy, steps, request.user)
        services.emit_event(request.user, "dunning_policy.created", policy, {
            "code": code, "steps": len(steps),
        }, idempotency_key=f"dunning_policy:{policy.pk}:created")
    return ok(serializers.dunning_policy_dict(policy, detail=True))


@endpoint()
def dunning_policy_update(request, pk):
    """更新催收策略；传入 steps 时整体替换步骤。"""
    policy = services.get_writable(DunningPolicy,
                                   pk,
                                   request.user, "催收策略不存在")
    fields = []
    if request.data.get("code") is not None:
        code = req_str(request, "code", max_len=60).strip()
        if DunningPolicy.objects.filter(owner=policy.owner_id, code=code) \
                .exclude(pk=policy.pk).exists():
            raise ValueError("策略编码已存在")
        policy.code = code
        fields.append("code")
    if request.data.get("name") is not None:
        policy.name = req_str(request, "name", max_len=120).strip()
        fields.append("name")
    if request.data.get("description") is not None:
        policy.description = opt_str(request, "description", max_len=5000)
        fields.append("description")
    if request.data.get("status") is not None:
        policy.status = choice_param(request, "status", ("active", "archived"),
                                     policy.status, "策略状态")
        fields.append("status")
    if request.data.get("metadata") is not None:
        policy.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    steps = None
    if request.data.get("steps") is not None:
        steps = _parse_steps(request, required=True)
    with transaction.atomic():
        if steps is not None:
            _replace_steps(policy, steps, request.user)
        if fields:
            policy.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
    return ok(serializers.dunning_policy_dict(policy, detail=True))


@endpoint()
def dunning_policy_delete(request, pk):
    """删除催收策略（已有运行记录时拒绝，保证历史可追溯）。"""
    policy = services.get_writable(DunningPolicy,
                                   pk,
                                   request.user, "催收策略不存在")
    if policy.runs.exists():
        raise ValueError("策略已有催收记录，不能删除（请停用）")
    pk = policy.pk
    with transaction.atomic():
        policy.delete()
        services.emit_event(request.user, "dunning_policy.deleted", None,
                            {"policy_id": pk},
                            idempotency_key=f"dunning_policy:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


# ===========================================================================
# 催收运行
# ===========================================================================


@endpoint()
def dunning_start(request):
    """对订阅启动催收（标记逾期、按策略排期；同订阅只保留一个进行中流程）。"""
    subscription = get_subscription(
        int_param(request, "subscription_id", required=True, minimum=1),
        request.user, write=True)
    policy = None
    policy_id = int_param(request, "policy_id", minimum=1)
    if policy_id:
        policy = services.get_visible(DunningPolicy, policy_id, request.user,
                                      "催收策略不存在")
        if not policy.steps.exists():
            raise ValueError("催收策略没有配置步骤")
    run = services.start_dunning(request.user, subscription, policy=policy,
                                 reason=opt_str(request, "reason", max_len=200))
    return ok(serializers.dunning_run_dict(run, detail=True))


@endpoint(("GET",))
def dunning_run_list(request):
    """催收记录列表（q/status/订阅 + 分页）。"""
    qs = services.visible(
        DunningRun.objects.select_related("subscription", "policy"), request.user)
    qs = apply_search(qs, request, ["policy__code", "policy__name", "note"])
    qs = filter_by(qs, request, "subscription_id")
    qs = filter_by(qs, request, "policy_id")
    return paginate(qs.order_by("-started_at", "-id"), request,
                    serializers.dunning_run_dict)


@endpoint(("GET",))
def dunning_run_detail(request, pk):
    """催收记录详情（策略步骤 + 事件时间线）。"""
    run = services.get_visible(DunningRun, pk, request.user, "催收记录不存在")
    return ok(serializers.dunning_run_dict(run, detail=True))


@endpoint()
def dunning_advance(request):
    """推进催收一步（未到执行时间需 force=true；已结束返回 executed=false）。"""
    run = services.get_writable(DunningRun,
                                int_param(request, "id", required=True, minimum=1),
                                request.user, "催收记录不存在")
    result = services.advance_dunning(request.user, run,
                                      force=bool_param(request, "force", False))
    return ok(_run_summary(result))


@endpoint()
def dunning_scan(request):
    """批量推进到期催收（定时任务入口，幂等）。"""
    result = services.run_dunning_scan(request.user)
    items = []
    for row in result["items"]:
        row = dict(row)
        items.append(row)
    return ok({
        "scanned": result["scanned"],
        "executed": result["executed"],
        "failed": result["failed"],
        "items": items,
        "errors": result["errors"],
        "ran_at": serializers.iso(result["ran_at"]),
    })


# ===========================================================================
# 税率
# ===========================================================================


@endpoint(("GET",))
def tax_rate_list(request):
    """税率列表（q/国家/地区/启用状态 + 分页）。"""
    qs = services.visible(TaxRate.objects.all(), request.user)
    qs = apply_search(qs, request, ["name", "country", "region"], status_field="")
    country = opt_str(request, "country").strip().upper()
    if country:
        qs = qs.filter(country=country)
    enabled = opt_str(request, "enabled").strip()
    if enabled in ("0", "false", "no", "off"):
        qs = qs.filter(enabled=False)
    elif enabled in ("1", "true", "yes", "on"):
        qs = qs.filter(enabled=True)
    return paginate(qs.order_by("country", "region", "id"), request,
                    serializers.tax_rate_dict)


@endpoint()
def tax_rate_create(request):
    """新建税率（百分比 0-100；同国家地区名称唯一）。"""
    country = opt_str(request, "country", "CN", max_len=8).upper() or "CN"
    region = opt_str(request, "region", max_len=60)
    name = opt_str(request, "name", "增值税", max_len=120) or "增值税"
    if TaxRate.objects.filter(owner=request.user, country=country,
                              region=region, name=name).exists():
        raise ValueError("同国家/地区/名称的税率已存在")
    rate = money_param(request, "rate", required=True, minimum=0, maximum=100)
    effective_from = date_param(request, "effective_from")
    effective_to = date_param(request, "effective_to")
    if effective_from and effective_to and effective_to <= effective_from:
        raise ValueError("生效截止必须晚于生效起始")
    is_default = bool_param(request, "is_default", False)
    with transaction.atomic():
        tax = TaxRate.objects.create(
            owner=request.user,
            country=country,
            region=region,
            name=name,
            rate=services.quantize_percent(rate),
            effective_from=effective_from,
            effective_to=effective_to,
            enabled=bool_param(request, "enabled", True),
            is_default=is_default,
        )
        if is_default:
            # 同国家只保留一个默认税率，否则取税时会出现两个「默认」互相覆盖
            TaxRate.objects.filter(owner=request.user, country=country,
                                   is_default=True).exclude(pk=tax.pk) \
                .update(is_default=False)
        services.emit_event(request.user, "tax_rate.created", tax, {
            "country": country, "region": region, "rate": str(tax.rate),
        }, idempotency_key=f"tax_rate:{tax.pk}:created")
    return ok(serializers.tax_rate_dict(tax))


@endpoint()
def tax_rate_update(request, pk):
    """更新税率（生效期/启用/默认标记）。"""
    tax = services.get_writable(TaxRate,
                                pk,
                                request.user, "税率不存在")
    fields = []
    for key, attr in (("country", "country"), ("region", "region"), ("name", "name")):
        if request.data.get(key) is not None:
            value = opt_str(request, key, max_len=60)
            if attr == "country":
                value = value.upper() or "CN"
            setattr(tax, attr, value)
            fields.append(attr)
    if request.data.get("rate") is not None:
        tax.rate = services.quantize_percent(
            money_param(request, "rate", required=True, minimum=0, maximum=100))
        fields.append("rate")
    if request.data.get("effective_from") is not None:
        tax.effective_from = date_param(request, "effective_from")
        fields.append("effective_from")
    if request.data.get("effective_to") is not None:
        tax.effective_to = date_param(request, "effective_to")
        fields.append("effective_to")
    if tax.effective_from and tax.effective_to and tax.effective_to <= tax.effective_from:
        raise ValueError("生效截止必须晚于生效起始")
    if request.data.get("enabled") is not None:
        tax.enabled = bool_param(request, "enabled", tax.enabled)
        fields.append("enabled")
    if request.data.get("is_default") is not None:
        tax.is_default = bool_param(request, "is_default", tax.is_default)
        fields.append("is_default")
    if not fields:
        raise ValueError("没有需要更新的字段")
    with transaction.atomic():
        tax.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
        if tax.is_default:
            TaxRate.objects.filter(owner=tax.owner_id, country=tax.country,
                                   is_default=True).exclude(pk=tax.pk) \
                .update(is_default=False)
    return ok(serializers.tax_rate_dict(tax))


@endpoint()
def tax_rate_delete(request, pk):
    """删除税率（历史发票行项已固化税率快照，删除不影响旧账单）。"""
    tax = services.get_writable(TaxRate,
                                pk,
                                request.user, "税率不存在")
    pk = tax.pk
    with transaction.atomic():
        tax.delete()
        services.emit_event(request.user, "tax_rate.deleted", None, {"tax_rate_id": pk},
                            idempotency_key=f"tax_rate:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


# ===========================================================================
# 事件
# ===========================================================================


@endpoint(("GET",))
def events_list(request):
    """计费事件列表（q/status/类型/对象 + 分页），用于审计与排障。"""
    from billing.models import BillingEvent
    from devtools.common import p

    qs = services.visible(BillingEvent.objects.all(), request.user)
    qs = apply_search(qs, request, ["event_type", "object_type", "error"])
    event_type = opt_str(request, "event_type").strip()
    if event_type:
        qs = qs.filter(event_type=event_type)
    object_type = opt_str(request, "object_type").strip()
    if object_type:
        qs = qs.filter(object_type=object_type)
    object_id = p(request, "object_id")
    if object_id not in (None, ""):
        qs = qs.filter(object_id=int_param(request, "object_id", required=True, minimum=1))
    return paginate(qs.order_by("-created_at", "-id"), request, serializers.event_dict)
