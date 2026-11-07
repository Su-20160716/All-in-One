# -*- coding: utf-8 -*-
"""订阅计费 · 产品目录接口：计划(8) 价格(5) 功能(4) 计划功能(5) = 22 个。

目录是计费系统的「配置面」：计划、价格、功能上限先配置好，订阅与账单
才有依据。因此这里的写权限全部跟随计划 owner（管理员放行），状态流转
（发布/停用）单独给接口，避免 update 一把梭导致计划在售卖中被误改。

路由（挂在 /api/billing/ 下）：
    GET  plans/                    计划列表
    POST plans/create/             新建计划
    GET  plans/<pk>/               计划详情（含价格/功能/售卖概况）
    POST plans/<pk>/update/        更新计划
    POST plans/<pk>/delete/        删除计划（有订阅时拒绝）
    POST plans/<pk>/publish/       发布计划
    POST plans/<pk>/archive/       停用计划（连带停用价格）
    POST plans/<pk>/clone/         克隆计划（含价格与功能绑定）
    GET  plans/<pk>/features/      计划的功能绑定
    GET  prices/                   价格列表
    POST prices/create/            新建价格
    POST prices/<pk>/update/       更新价格
    POST prices/<pk>/delete/       删除价格
    GET  prices/resolve/           按币种/日期解析生效价格
    GET  features/                 功能列表
    POST features/create/          新建功能
    POST features/<pk>/update/     更新功能
    POST features/<pk>/delete/     删除功能
    GET  plan-features/            计划功能列表
    POST plan-features/create/     绑定功能到计划
    POST plan-features/<pk>/update/ 更新绑定（包含量/超量单价）
    POST plan-features/<pk>/delete/ 解绑
"""
import re

from django.db import transaction

from devtools.common import endpoint, ok, opt_str, req_str

from billing import serializers, services
from billing.models import (
    PLAN_PERIODS,
    PLAN_STATUS,
    Plan,
    PlanFeature,
    Price,
)
from billing.views_common import (
    apply_search,
    choice_param,
    date_param,
    dict_param,
    get_feature,
    get_plan,
    get_plan_feature,
    get_price,
    int_param,
    list_param,
    money_param,
    paginate,
    filter_by,
)

CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{1,59}$")


def _check_code(code, label="编码"):
    """编码只允许字母开头 + 字母数字下划线中划线。

    限制字符集是为了让编码能安全出现在 URL、事件幂等键与导出文件名里，
    避免中文/空格/斜杠在各处需要一遍遍转义。
    """
    if not CODE_PATTERN.match(code or ""):
        raise ValueError(f"{label}必须字母开头，仅含字母/数字/下划线/中划线（2-60 位）")
    return code


def _plan_has_subscriptions(plan):
    """计划是否已有订阅（含已取消的历史订阅，历史账单不能被删）。"""
    return plan.subscriptions.exists()


def _archive_prices(plan):
    """停用计划时连带停用价格：保留历史取价能力，但不再对外售卖。"""
    plan.prices.filter(status="active").update(status="archived")


# ===========================================================================
# 计划
# ===========================================================================


@endpoint(("GET",))
def plan_list(request):
    """计划列表（q/status/billing_period + 分页）。"""
    qs = services.visible(Plan.objects.all(), request.user)
    qs = apply_search(qs, request, ["code", "name", "description"])
    period = opt_str(request, "billing_period").strip()
    if period:
        if period not in PLAN_PERIODS:
            raise ValueError("计费周期必须是 monthly/yearly/one_time 之一")
        qs = qs.filter(billing_period=period)
    return paginate(qs.order_by("sort_order", "id"), request, serializers.plan_dict)


@endpoint()
def plan_create(request):
    """新建计划（默认草稿，发布后才可开通订阅）。"""
    code = _check_code(req_str(request, "code", max_len=60).strip(), "计划编码")
    if Plan.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("计划编码已存在")
    name = req_str(request, "name", max_len=120).strip()
    period = choice_param(request, "billing_period", PLAN_PERIODS, "monthly", "计费周期")
    status = choice_param(request, "status", ("draft", "active"), "draft", "计划状态")
    trial_days = int_param(request, "trial_days", 0, minimum=0, maximum=365)
    limits = dict_param(request, "limits")
    metadata = dict_param(request, "metadata")
    with transaction.atomic():
        plan = Plan.objects.create(
            owner=request.user,
            code=code,
            name=name,
            description=opt_str(request, "description", max_len=5000),
            billing_period=period,
            trial_days=trial_days,
            status=status,
            sort_order=int_param(request, "sort_order", 0, minimum=-100000, maximum=100000),
            limits=limits,
            metadata=metadata,
            published_at=services.now() if status == "active" else None,
        )
        services.emit_event(request.user, "plan.created", plan, {
            "code": code, "billing_period": period, "status": status,
        }, idempotency_key=f"plan:{plan.pk}:created")
    return ok(serializers.plan_dict(plan, detail=True))


@endpoint(("GET",))
def plan_detail(request, pk):
    """计划详情（价格、功能绑定、售卖概况）。"""
    plan = get_plan(pk, request.user)
    data = serializers.plan_dict(plan, detail=True)
    data["events"] = [serializers.event_dict(ev)
                      for ev in services.events_for(plan, limit=20)]
    return ok(data)


@endpoint()
def plan_update(request, pk):
    """更新计划（编码变更需保持唯一）。"""
    plan = get_plan(pk, request.user, write=True)
    fields = []
    if request.data.get("code") is not None:
        code = _check_code(req_str(request, "code", max_len=60).strip(), "计划编码")
        if Plan.objects.filter(owner=plan.owner_id, code=code).exclude(pk=plan.pk).exists():
            raise ValueError("计划编码已存在")
        plan.code = code
        fields.append("code")
    if request.data.get("name") is not None:
        plan.name = req_str(request, "name", max_len=120).strip()
        fields.append("name")
    if request.data.get("description") is not None:
        plan.description = opt_str(request, "description", max_len=5000)
        fields.append("description")
    if request.data.get("billing_period") is not None:
        plan.billing_period = choice_param(
            request, "billing_period", PLAN_PERIODS, "monthly", "计费周期")
        fields.append("billing_period")
    if request.data.get("trial_days") is not None:
        plan.trial_days = int_param(request, "trial_days", 0, minimum=0, maximum=365)
        fields.append("trial_days")
    if request.data.get("sort_order") is not None:
        plan.sort_order = int_param(request, "sort_order", 0, minimum=-100000, maximum=100000)
        fields.append("sort_order")
    if request.data.get("limits") is not None:
        plan.limits = dict_param(request, "limits")
        fields.append("limits")
    if request.data.get("metadata") is not None:
        plan.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    if request.data.get("status") is not None:
        new_status = choice_param(request, "status", PLAN_STATUS, plan.status, "计划状态")
        if new_status == "active" and not plan.published_at:
            plan.published_at = services.now()
            fields.append("published_at")
        if new_status == "archived":
            _archive_prices(plan)
        plan.status = new_status
        fields.append("status")
    if not fields:
        raise ValueError("没有需要更新的字段")
    plan.save(update_fields=fields + ["updated_at"])
    services.emit_event(request.user, "plan.updated", plan, {"fields": fields},
                        idempotency_key=f"plan:{plan.pk}:updated:{services.now().isoformat()}")
    return ok(serializers.plan_dict(plan, detail=True))


@endpoint()
def plan_delete(request, pk):
    """删除计划（已有订阅时拒绝，建议改为停用）。"""
    plan = get_plan(pk,
                    request.user, write=True)
    if _plan_has_subscriptions(plan):
        raise ValueError("计划已有订阅，不能删除（请改为停用）")
    pk = plan.pk
    with transaction.atomic():
        plan.delete()
        services.emit_event(request.user, "plan.deleted", None, {"plan_id": pk, "code": plan.code},
                            idempotency_key=f"plan:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


@endpoint()
def plan_publish(request, pk):
    """发布计划（草稿/停用 → 已发布，生成售卖入口）。"""
    plan = get_plan(pk,
                    request.user, write=True)
    if plan.status == "active":
        return ok(serializers.plan_dict(plan, detail=True))
    if not plan.prices.filter(status="active").exists():
        raise ValueError("计划没有生效价格，不能发布")
    with transaction.atomic():
        plan.status = "active"
        plan.published_at = plan.published_at or services.now()
        plan.save(update_fields=["status", "published_at", "updated_at"])
        services.emit_event(request.user, "plan.published", plan, {},
                            idempotency_key=f"plan:{plan.pk}:published:{services.today()}")
    return ok(serializers.plan_dict(plan, detail=True))


@endpoint()
def plan_archive(request, pk):
    """停用计划（不再可售，已有订阅继续按原价计费）。"""
    plan = get_plan(pk,
                    request.user, write=True)
    if plan.status == "archived":
        return ok(serializers.plan_dict(plan, detail=True))
    with transaction.atomic():
        plan.status = "archived"
        plan.save(update_fields=["status", "updated_at"])
        _archive_prices(plan)
        services.emit_event(request.user, "plan.archived", plan, {},
                            idempotency_key=f"plan:{plan.pk}:archived")
    return ok(serializers.plan_dict(plan, detail=True))


@endpoint()
def plan_clone(request, pk):
    """克隆计划（复制价格与功能绑定，副本为草稿，编码自动去重）。"""
    source = get_plan(pk,
                      request.user, write=True)
    raw_code = opt_str(request, "code").strip()
    if raw_code:
        code = _check_code(raw_code, "计划编码")
        if Plan.objects.filter(owner=request.user, code=code).exists():
            raise ValueError("计划编码已存在")
    else:
        base = f"{source.code}_copy"
        code = base
        index = 1
        while Plan.objects.filter(owner=request.user, code=code).exists():
            index += 1
            code = f"{base}{index}"
        code = _check_code(code, "计划编码")
    name = opt_str(request, "name", f"{source.name}（副本）", max_len=120)
    with transaction.atomic():
        plan = Plan.objects.create(
            owner=request.user,
            code=code,
            name=name,
            description=source.description,
            billing_period=source.billing_period,
            trial_days=source.trial_days,
            status="draft",
            sort_order=source.sort_order,
            limits=dict(source.limits or {}),
            metadata=dict(source.metadata or {}),
        )
        for price in source.prices.all():
            Price.objects.create(
                owner=request.user,
                plan=plan,
                currency=price.currency,
                amount=price.amount,
                billing_mode=price.billing_mode,
                tiers=list(price.tiers or []),
                effective_from=price.effective_from,
                effective_to=price.effective_to,
                status=price.status,
                nickname=price.nickname,
            )
        for binding in source.plan_features.all():
            PlanFeature.objects.create(
                owner=request.user,
                plan=plan,
                feature=binding.feature,
                included_qty=binding.included_qty,
                unit=binding.unit,
                overage_unit_amount=binding.overage_unit_amount,
                metadata=dict(binding.metadata or {}),
            )
        services.emit_event(request.user, "plan.cloned", plan, {
            "source_plan_id": source.pk, "code": code,
        }, idempotency_key=f"plan:{plan.pk}:cloned")
    return ok(serializers.plan_dict(plan, detail=True))


@endpoint(("GET",))
def plan_features(request, pk):
    """计划的功能绑定清单（按计划 id 查询）。"""
    plan = get_plan(pk, request.user)
    rows = plan.plan_features.select_related("feature").order_by("id")
    return ok({
        "plan_id": plan.pk,
        "plan_code": plan.code,
        "items": [serializers.plan_feature_dict(b) for b in rows],
        "count": rows.count(),
    })


# ===========================================================================
# 价格
# ===========================================================================


@endpoint(("GET",))
def price_list(request):
    """价格列表（按计划/币种过滤 + 搜索 + 分页）。"""
    qs = services.visible(Price.objects.select_related("plan"), request.user)
    qs = apply_search(qs, request, ["nickname", "currency", "plan__code", "plan__name"])
    qs = filter_by(qs, request, "plan_id")
    currency = opt_str(request, "currency").strip().upper()
    if currency:
        qs = qs.filter(currency=currency)
    return paginate(qs.order_by("plan_id", "currency", "-effective_from", "-id"),
                    request, serializers.price_dict)


@endpoint()
def price_create(request):
    """新建价格（同计划同币种同生效日只允许一条）。"""
    plan = get_plan(int_param(request, "plan_id", required=True, minimum=1),
                    request.user, write=True)
    currency = opt_str(request, "currency", "CNY").strip().upper() or "CNY"
    if len(currency) < 3 or len(currency) > 8:
        raise ValueError("币种必须是 3-8 位字母代码")
    mode = choice_param(request, "billing_mode",
                        ("flat", "per_unit", "tiered"), "flat", "计费模式")
    amount = money_param(request, "amount", required=mode != "tiered", default=0, minimum=0)
    tiers = services.normalize_tiers(list_param(request, "tiers")) if mode == "tiered" else []
    if mode == "tiered" and not tiers:
        raise ValueError("阶梯计费必须提供阶梯配置")
    effective_from = date_param(request, "effective_from")
    effective_to = date_param(request, "effective_to")
    if effective_from and effective_to and effective_to <= effective_from:
        raise ValueError("生效截止必须晚于生效起始")
    if Price.objects.filter(plan=plan, currency=currency,
                            effective_from=effective_from).exists():
        raise ValueError("同计划同币种同生效日已存在价格")
    with transaction.atomic():
        price = Price.objects.create(
            owner=request.user,
            plan=plan,
            currency=currency,
            amount=services.quantize_unit(amount),
            billing_mode=mode,
            tiers=tiers,
            effective_from=effective_from,
            effective_to=effective_to,
            status=choice_param(request, "status", ("active", "archived"),
                                "active", "价格状态"),
            nickname=opt_str(request, "nickname", max_len=120),
        )
        services.emit_event(request.user, "price.created", price, {
            "plan_id": plan.pk, "currency": currency, "amount": str(price.amount),
            "billing_mode": mode,
        }, idempotency_key=f"price:{price.pk}:created")
    return ok(serializers.price_dict(price))


@endpoint()
def price_update(request, pk):
    """更新价格（金额/模式/阶梯/生效窗口）。"""
    price = get_price(pk,
                      request.user, write=True)
    updated = []
    if request.data.get("currency") is not None:
        currency = opt_str(request, "currency").strip().upper()
        if not (3 <= len(currency) <= 8):
            raise ValueError("币种必须是 3-8 位字母代码")
        price.currency = currency
        updated.append("currency")
    if request.data.get("billing_mode") is not None:
        price.billing_mode = choice_param(request, "billing_mode",
                                          ("flat", "per_unit", "tiered"),
                                          price.billing_mode, "计费模式")
        updated.append("billing_mode")
    if request.data.get("tiers") is not None:
        price.tiers = services.normalize_tiers(list_param(request, "tiers"))
        updated.append("tiers")
    if price.billing_mode == "tiered" and not price.tiers:
        raise ValueError("阶梯计费必须提供阶梯配置")
    if request.data.get("amount") is not None:
        price.amount = services.quantize_unit(
            money_param(request, "amount", required=True, minimum=0))
        updated.append("amount")
    if request.data.get("effective_from") is not None:
        price.effective_from = date_param(request, "effective_from")
        updated.append("effective_from")
    if request.data.get("effective_to") is not None:
        price.effective_to = date_param(request, "effective_to")
        updated.append("effective_to")
    if price.effective_from and price.effective_to \
            and price.effective_to <= price.effective_from:
        raise ValueError("生效截止必须晚于生效起始")
    if request.data.get("status") is not None:
        price.status = choice_param(request, "status", ("active", "archived"),
                                    price.status, "价格状态")
        updated.append("status")
    if request.data.get("nickname") is not None:
        price.nickname = opt_str(request, "nickname", max_len=120)
        updated.append("nickname")
    if not updated:
        raise ValueError("没有需要更新的字段")
    if Price.objects.filter(plan_id=price.plan_id, currency=price.currency,
                            effective_from=price.effective_from).exclude(pk=price.pk).exists():
        raise ValueError("同计划同币种同生效日已存在价格")
    price.save(update_fields=updated + ["updated_at"])
    services.emit_event(request.user, "price.updated", price, {"fields": updated},
                        idempotency_key=f"price:{price.pk}:updated:{services.now().isoformat()}")
    return ok(serializers.price_dict(price))


@endpoint()
def price_delete(request, pk):
    """删除价格（已被订阅明细引用时拒绝，改为停用）。"""
    price = get_price(pk,
                      request.user, write=True)
    if price.subscription_items.exists():
        raise ValueError("价格已被订阅使用，不能删除（请停用）")
    pk = price.pk
    with transaction.atomic():
        price.delete()
        services.emit_event(request.user, "price.deleted", None,
                            {"price_id": pk, "plan_id": price.plan_id},
                            idempotency_key=f"price:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


@endpoint(("GET",))
def price_resolve(request):
    """解析计划在某币种/日期下的生效价格（下单前校验用）。"""
    plan = get_plan(int_param(request, "plan_id", required=True, minimum=1), request.user)
    currency = opt_str(request, "currency", "CNY").strip().upper() or "CNY"
    at = date_param(request, "at") or services.today()
    price = services.applicable_price(plan, currency, at)
    if price is None:
        raise ValueError(f"计划 {plan.name} 在 {currency} 下没有生效价格")
    return ok({"plan_id": plan.pk, "at": at,
               "price": serializers.price_dict(price), "resolved": True})


# ===========================================================================
# 功能项
# ===========================================================================


@endpoint(("GET",))
def feature_list(request):
    """功能项列表（q/status + 分页）。"""
    from billing.models import Feature

    qs = services.visible(Feature.objects.all(), request.user)
    qs = apply_search(qs, request, ["code", "name", "description"])
    return paginate(qs.order_by("id"), request, serializers.feature_dict)


@endpoint()
def feature_create(request):
    """新建功能项（编码在 owner 内唯一）。"""
    from billing.models import Feature

    code = _check_code(req_str(request, "code", max_len=60).strip(), "功能编码")
    if Feature.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("功能编码已存在")
    feature = Feature.objects.create(
        owner=request.user,
        code=code,
        name=req_str(request, "name", max_len=120).strip(),
        feature_type=choice_param(request, "feature_type",
                                  ("boolean", "quota", "metered"), "boolean", "功能类型"),
        description=opt_str(request, "description", max_len=5000),
        unit=opt_str(request, "unit", max_len=20),
        status=choice_param(request, "status", ("active", "archived"),
                            "active", "功能状态"),
    )
    services.emit_event(request.user, "feature.created", feature, {"code": code},
                        idempotency_key=f"feature:{feature.pk}:created")
    return ok(serializers.feature_dict(feature))


@endpoint()
def feature_update(request, pk):
    """更新功能项。"""
    from billing.models import Feature

    feature = get_feature(pk,
                          request.user, write=True)
    fields = []
    if request.data.get("code") is not None:
        code = _check_code(req_str(request, "code", max_len=60).strip(), "功能编码")
        if Feature.objects.filter(owner=feature.owner_id, code=code) \
                .exclude(pk=feature.pk).exists():
            raise ValueError("功能编码已存在")
        feature.code = code
        fields.append("code")
    if request.data.get("name") is not None:
        feature.name = req_str(request, "name", max_len=120).strip()
        fields.append("name")
    if request.data.get("feature_type") is not None:
        feature.feature_type = choice_param(request, "feature_type",
                                            ("boolean", "quota", "metered"),
                                            feature.feature_type, "功能类型")
        fields.append("feature_type")
    if request.data.get("description") is not None:
        feature.description = opt_str(request, "description", max_len=5000)
        fields.append("description")
    if request.data.get("unit") is not None:
        feature.unit = opt_str(request, "unit", max_len=20)
        fields.append("unit")
    if request.data.get("status") is not None:
        feature.status = choice_param(request, "status", ("active", "archived"),
                                      feature.status, "功能状态")
        fields.append("status")
    if not fields:
        raise ValueError("没有需要更新的字段")
    feature.save(update_fields=fields + ["updated_at"])
    return ok(serializers.feature_dict(feature))


@endpoint()
def feature_delete(request, pk):
    """删除功能项（已被计划绑定时拒绝）。"""
    feature = get_feature(pk,
                          request.user, write=True)
    if feature.plan_features.exists():
        raise ValueError("功能已绑定到计划，不能删除（请先解绑或停用）")
    pk = feature.pk
    with transaction.atomic():
        feature.delete()
        services.emit_event(request.user, "feature.deleted", None, {"feature_id": pk},
                            idempotency_key=f"feature:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


# ===========================================================================
# 计划功能
# ===========================================================================


@endpoint(("GET",))
def plan_feature_list(request):
    """计划功能绑定列表（按计划/功能过滤 + 分页）。"""
    qs = services.visible(PlanFeature.objects.select_related("plan", "feature"), request.user)
    qs = filter_by(qs, request, "plan_id")
    qs = filter_by(qs, request, "feature_id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        from django.db.models import Q

        qs = qs.filter(Q(feature__code__icontains=keyword) | Q(feature__name__icontains=keyword)
                       | Q(plan__code__icontains=keyword) | Q(plan__name__icontains=keyword))
    return paginate(qs.order_by("plan_id", "id"), request, serializers.plan_feature_dict)


@endpoint()
def plan_feature_create(request):
    """绑定功能到计划（包含量/单位/超量单价）。"""
    plan = get_plan(int_param(request, "plan_id", required=True, minimum=1),
                    request.user, write=True)
    feature = get_feature(int_param(request, "feature_id", required=True, minimum=1),
                          request.user)
    if PlanFeature.objects.filter(plan=plan, feature=feature).exists():
        raise ValueError("该计划已绑定此功能")
    included = money_param(request, "included_qty", default=0, minimum=0) or services.ZERO
    overage = money_param(request, "overage_unit_amount", default=0, minimum=0) or services.ZERO
    with transaction.atomic():
        binding = PlanFeature.objects.create(
            owner=request.user,
            plan=plan,
            feature=feature,
            included_qty=services.quantize_unit(included),
            unit=opt_str(request, "unit", feature.unit, max_len=20),
            overage_unit_amount=services.quantize_unit(overage),
            metadata=dict_param(request, "metadata"),
        )
        services.emit_event(request.user, "plan_feature.created", binding, {
            "plan_id": plan.pk, "feature": feature.code,
            "included": str(binding.included_qty), "overage": str(overage),
        }, idempotency_key=f"plan_feature:{binding.pk}:created")
    return ok(serializers.plan_feature_dict(binding))


@endpoint()
def plan_feature_update(request, pk):
    """更新计划功能（包含量/超量单价/单位）。"""
    binding = get_plan_feature(pk,
                              request.user, write=True)
    fields = []
    if request.data.get("included_qty") is not None:
        binding.included_qty = services.quantize_unit(
            money_param(request, "included_qty", default=0, minimum=0))
        fields.append("included_qty")
    if request.data.get("overage_unit_amount") is not None:
        binding.overage_unit_amount = services.quantize_unit(
            money_param(request, "overage_unit_amount", default=0, minimum=0))
        fields.append("overage_unit_amount")
    if request.data.get("unit") is not None:
        binding.unit = opt_str(request, "unit", max_len=20)
        fields.append("unit")
    if request.data.get("metadata") is not None:
        binding.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    if not fields:
        raise ValueError("没有需要更新的字段")
    binding.save(update_fields=fields + ["updated_at"])
    return ok(serializers.plan_feature_dict(binding))


@endpoint()
def plan_feature_delete(request, pk):
    """解绑计划功能。"""
    binding = get_plan_feature(pk,
                              request.user, write=True)
    pk = binding.pk
    with transaction.atomic():
        binding.delete()
        services.emit_event(request.user, "plan_feature.deleted", None, {"binding_id": pk},
                            idempotency_key=f"plan_feature:{pk}:deleted")
    return ok({"deleted": True, "id": pk})
