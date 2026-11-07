# -*- coding: utf-8 -*-
"""订阅计费 · 客户与订阅接口：客户(6) + 订阅(17) = 23 个。

客户是账单的归属主体，订阅是计费的发动机：开通、试用转正、升降级折算、
暂停/恢复、期末取消/立即取消、续费都在这里完成。所有生命周期动作都委托
给 services 层的状态机函数（锁行 + 事务 + 事件），视图只做取参与渲染，
保证「同一动作在接口与定时任务里行为一致」。

路由（挂在 /api/billing/ 下）：
    GET  customers/                        客户列表
    POST customers/create/                 新建客户
    GET  customers/<pk>/                   客户详情
    POST customers/<pk>/update/            更新客户
    POST customers/<pk>/delete/            删除客户（有订阅时拒绝）
    GET  customers/<pk>/overview/          客户概览（订阅/发票/余额）
    GET  subscriptions/                    订阅列表
    POST subscriptions/create/             新建订阅
    GET  subscriptions/<pk>/               订阅详情（含明细/用量/发票/事件）
    POST subscriptions/<pk>/update/        更新订阅（席位/自动续费）
    POST subscriptions/<pk>/delete/        删除订阅（仅已取消）
    POST subscriptions/<pk>/activate/      开通/恢复
    POST subscriptions/<pk>/trial-convert/ 试用转正
    POST subscriptions/<pk>/change-preview/ 变更预览（不落账）
    POST subscriptions/<pk>/change-plan/   升级/降级（生成折算账单）
    POST subscriptions/<pk>/pause/         暂停
    POST subscriptions/<pk>/resume/        恢复
    POST subscriptions/<pk>/cancel/        期末取消
    POST subscriptions/<pk>/cancel-now/    立即取消
    POST subscriptions/<pk>/renew/         续费
    GET  subscriptions/<pk>/items/         订阅明细
    POST subscriptions/<pk>/items/add/     添加明细（加购）
    POST subscriptions/<pk>/items/remove/  移除明细（期末失效）
"""
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from devtools.common import endpoint, ok, opt_str, req_str

from billing import serializers, services
from billing.models import CUSTOMER_STATUS, Customer, Subscription, SubscriptionItem
from billing.views_common import (
    apply_search,
    bool_param,
    choice_param,
    date_param,
    dict_param,
    datetime_param,
    filter_by,
    get_customer,
    get_plan,
    get_price,
    get_subscription,
    int_param,
    money_param,
    paginate,
    visible_or_404,
)


def _check_email(value):
    """邮箱校验：空串允许（个人客户可能不填），非空必须合法。"""
    email = str(value or "").strip()
    if not email:
        return ""
    try:
        validate_email(email)
    except ValidationError:
        raise ValueError("邮箱格式不正确")
    return email


def _proration_dict(preview):
    """折算结果渲染：金额转字符串、日期转 ISO，避免前端做精度换算。"""
    return {
        "from_plan_id": preview["from_plan_id"],
        "to_plan_id": preview["to_plan_id"],
        "from_plan": preview["from_plan"],
        "to_plan": preview["to_plan"],
        "upgrade": preview["upgrade"],
        "at": serializers.iso(preview["at"]),
        "period_start": serializers.iso(preview["period_start"]),
        "period_end": serializers.iso(preview["period_end"]),
        "total_days": preview["total_days"],
        "remaining_days": preview["remaining_days"],
        "ratio": preview["ratio"],
        "old_period_amount": serializers.money(preview["old_period_amount"]),
        "new_period_amount": serializers.money(preview["new_period_amount"]),
        "credit": serializers.money(preview["credit"]),
        "charge": serializers.money(preview["charge"]),
        "net": serializers.money(preview["net"]),
        "currency": preview["currency"],
        "seats": preview["seats"],
        "new_price_id": preview["new_price_id"],
    }


def _snapshot_dict(snapshot):
    """客户概览渲染：金额统一字符串，日期统一 ISO。"""
    data = dict(snapshot)
    for key in ("balance", "credit_limit", "credit_available", "outstanding",
                "paid_total", "mrr"):
        if key in data:
            data[key] = serializers.money(data[key])
    for row in data.get("subscriptions", []):
        row["current_period_start"] = serializers.iso(row.get("current_period_start"))
        row["current_period_end"] = serializers.iso(row.get("current_period_end"))
    for row in data.get("recent_invoices", []):
        row["total"] = serializers.money(row.get("total", 0))
        row["amount_due"] = serializers.money(row.get("amount_due", 0))
        row["due_date"] = serializers.iso(row.get("due_date"))
    events = []
    for ev in data.get("events", []):
        events.append({
            "id": ev["id"], "event_type": ev["event_type"], "status": ev["status"],
            "payload": ev["payload"], "created_at": serializers.iso(ev["created_at"]),
        })
    data["events"] = events
    return data


# ===========================================================================
# 客户
# ===========================================================================


@endpoint(("GET",))
def customer_list(request):
    """客户列表（q/status + 分页）。"""
    qs = services.visible(Customer.objects.all(), request.user)
    qs = apply_search(qs, request, ["name", "email", "tax_id", "country"])
    return paginate(qs.order_by("-created_at", "-id"), request,
                    lambda obj: serializers.customer_dict(obj, with_metrics=True))


@endpoint()
def customer_create(request):
    """新建客户（名称必填，邮箱可选但必须合法）。"""
    from billing.models import Customer

    name = req_str(request, "name", max_len=200).strip()
    if Customer.objects.filter(owner=request.user, name=name).exists():
        raise ValueError("同名客户已存在")
    email = _check_email(opt_str(request, "email"))
    balance = money_param(request, "balance", default=0) or services.ZERO
    credit_limit = money_param(request, "credit_limit", default=0, minimum=0) or services.ZERO
    with transaction.atomic():
        customer = Customer.objects.create(
            owner=request.user,
            name=name,
            email=email,
            tax_id=opt_str(request, "tax_id", max_len=60),
            address=opt_str(request, "address", max_len=5000),
            country=opt_str(request, "country", "CN", max_len=8).upper() or "CN",
            region=opt_str(request, "region", max_len=60),
            currency=opt_str(request, "currency", "CNY", max_len=8).upper() or "CNY",
            status=choice_param(request, "status", CUSTOMER_STATUS, "active", "客户状态"),
            balance=services.quantize_money(balance),
            credit_limit=services.quantize_money(credit_limit),
            metadata=dict_param(request, "metadata"),
        )
        services.emit_event(request.user, "customer.created", customer, {
            "name": name, "currency": customer.currency,
        }, idempotency_key=f"customer:{customer.pk}:created")
    return ok(serializers.customer_dict(customer, with_metrics=True))


@endpoint(("GET",))
def customer_detail(request, pk):
    """客户详情（含额度与欠款汇总）。"""
    customer = get_customer(pk, request.user)
    return ok(serializers.customer_dict(customer, with_metrics=True))


@endpoint()
def customer_update(request, pk):
    """更新客户资料（余额与信用额度也在此维护，金额走 Decimal）。"""
    customer = get_customer(pk,
                            request.user, write=True)
    fields = []
    for key, attr, limit in (("name", "name", 200), ("tax_id", "tax_id", 60),
                             ("address", "address", 5000), ("region", "region", 60)):
        if request.data.get(key) is not None:
            value = req_str(request, key, max_len=limit).strip() if key == "name" \
                else opt_str(request, key, max_len=limit)
            setattr(customer, attr, value)
            fields.append(attr)
    if request.data.get("email") is not None:
        customer.email = _check_email(opt_str(request, "email"))
        fields.append("email")
    if request.data.get("country") is not None:
        customer.country = opt_str(request, "country", "CN", max_len=8).upper() or "CN"
        fields.append("country")
    if request.data.get("currency") is not None:
        customer.currency = opt_str(request, "currency", "CNY", max_len=8).upper() or "CNY"
        fields.append("currency")
    if request.data.get("status") is not None:
        customer.status = choice_param(request, "status", CUSTOMER_STATUS,
                                       customer.status, "客户状态")
        fields.append("status")
    if request.data.get("balance") is not None:
        customer.balance = services.quantize_money(
            money_param(request, "balance", required=True))
        fields.append("balance")
    if request.data.get("credit_limit") is not None:
        customer.credit_limit = services.quantize_money(
            money_param(request, "credit_limit", required=True, minimum=0))
        fields.append("credit_limit")
    if request.data.get("metadata") is not None:
        customer.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    if not fields:
        raise ValueError("没有需要更新的字段")
    if request.data.get("name") is not None and Customer.objects.filter(
            owner=customer.owner_id, name=customer.name).exclude(pk=customer.pk).exists():
        raise ValueError("同名客户已存在")
    customer.save(update_fields=fields + ["updated_at"])
    services.emit_event(request.user, "customer.updated", customer, {"fields": fields},
                        idempotency_key=f"customer:{customer.pk}:updated:{services.now().isoformat()}")
    return ok(serializers.customer_dict(customer, with_metrics=True))


@endpoint()
def customer_delete(request, pk):
    """删除客户（存在订阅或发票时拒绝，保证账单可追溯）。"""
    customer = get_customer(pk,
                            request.user, write=True)
    if customer.subscriptions.exists():
        raise ValueError("客户存在订阅，不能删除（请先取消订阅）")
    if customer.invoices.exists():
        raise ValueError("客户存在发票，不能删除（请先作废或归档）")
    pk = customer.pk
    with transaction.atomic():
        customer.delete()
        services.emit_event(request.user, "customer.deleted", None, {"customer_id": pk},
                            idempotency_key=f"customer:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


@endpoint(("GET",))
def customer_overview(request, pk):
    """客户概览：订阅、发票、余额、信用额度与近期事件。"""
    customer = get_customer(pk, request.user)
    return ok(_snapshot_dict(services.customer_snapshot(customer)))


# ===========================================================================
# 订阅
# ===========================================================================


@endpoint(("GET",))
def subscription_list(request):
    """订阅列表（q/status/customer_id/plan_id + 分页）。"""
    qs = services.visible(
        Subscription.objects.select_related("customer", "plan"), request.user)
    qs = apply_search(qs, request, ["customer__name", "plan__code", "plan__name"])
    qs = filter_by(qs, request, "customer_id")
    qs = filter_by(qs, request, "plan_id")
    return paginate(qs.order_by("-created_at", "-id"), request,
                    serializers.subscription_dict)


@endpoint()
def subscription_create(request):
    """新建订阅（试用按计划天数自动判断，落一条订阅明细）。"""
    customer = get_customer(int_param(request, "customer_id", required=True, minimum=1),
                            request.user, write=True)
    plan = get_plan(int_param(request, "plan_id", required=True, minimum=1), request.user)
    price = None
    price_id = int_param(request, "price_id", minimum=1)
    if price_id:
        price = get_price(price_id, request.user)
    trial = None
    if request.data.get("trial") is not None:
        trial = bool_param(request, "trial")
    subscription = services.create_subscription(
        request.user, customer, plan,
        currency=opt_str(request, "currency", "", max_len=8).upper() or None,
        seats=int_param(request, "seats", 1, minimum=1, maximum=100000),
        start_date=date_param(request, "start_date"),
        trial=trial, price=price, metadata=dict_param(request, "metadata"),
    )
    return ok(serializers.subscription_dict(subscription, detail=True))


@endpoint(("GET",))
def subscription_detail(request, pk):
    """订阅详情（明细、当期用量、近期发票、事件）。"""
    subscription = get_subscription(pk, request.user)
    return ok(serializers.subscription_dict(subscription, detail=True))


@endpoint()
def subscription_update(request, pk):
    """更新订阅（席位、自动续费、扩展信息；计划变更请走 change-plan）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    fields = []
    if subscription.status == "canceled":
        raise ValueError("已取消的订阅不能修改")
    if request.data.get("seats") is not None:
        subscription.seats = int_param(request, "seats", subscription.seats,
                                       minimum=1, maximum=100000)
        fields.append("seats")
    if request.data.get("auto_renew") is not None:
        subscription.auto_renew = bool_param(request, "auto_renew", subscription.auto_renew)
        fields.append("auto_renew")
    if request.data.get("metadata") is not None:
        subscription.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    if not fields:
        raise ValueError("没有需要更新的字段")
    subscription.save(update_fields=fields + ["updated_at"])
    return ok(serializers.subscription_dict(subscription, detail=True))


@endpoint()
def subscription_delete(request, pk):
    """删除订阅（仅已取消，保留计费历史的完整性）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    if subscription.status != "canceled":
        raise ValueError("仅已取消的订阅可以删除")
    if subscription.invoices.exists():
        raise ValueError("订阅存在发票，不能删除（请保留账单追溯）")
    pk = subscription.pk
    with transaction.atomic():
        subscription.delete()
        services.emit_event(request.user, "subscription.deleted", None,
                            {"subscription_id": pk},
                            idempotency_key=f"subscription:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


@endpoint()
def subscription_activate(request, pk):
    """开通/恢复订阅（可按需补开当期账单）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    result = services.activate_subscription(request.user, subscription,
                                            generate=bool_param(request, "invoice", False))
    payload = {"subscription": serializers.subscription_dict(result["subscription"]),
               "changed": result["changed"], "invoice": None}
    if result["invoice"] is not None:
        payload["invoice"] = serializers.invoice_dict(result["invoice"], detail=True)
    return ok(payload)


@endpoint()
def subscription_trial_convert(request, pk):
    """试用转正（写入试用结束时间、重置账期并生成首张账单）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    result = services.convert_trial(request.user, subscription,
                                    generate=bool_param(request, "invoice", True))
    payload = {"subscription": serializers.subscription_dict(result["subscription"]),
               "changed": result["changed"], "invoice": None}
    if result["invoice"] is not None:
        payload["invoice"] = serializers.invoice_dict(result["invoice"], detail=True)
    return ok(payload)


@endpoint()
def subscription_change_preview(request, pk):
    """变更预览：按天折算差额（不落账，供确认弹窗展示）。"""
    subscription = get_subscription(pk,
                                    request.user)
    new_plan = get_plan(int_param(request, "new_plan_id", required=True, minimum=1),
                        request.user)
    preview = services.proration_for_plan_change(
        subscription, new_plan,
        at=datetime_param(request, "at") or services.now(),
        seats=int_param(request, "seats", subscription.seats, minimum=1, maximum=100000),
    )
    data = _proration_dict(preview)
    data["subscription_id"] = subscription.pk
    return ok(data)


@endpoint()
def subscription_change_plan(request, pk):
    """升级/降级（按天折算，正差额开票、负差额进余额）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    new_plan = get_plan(int_param(request, "new_plan_id", required=True, minimum=1),
                        request.user)
    result = services.apply_plan_change(
        request.user, subscription, new_plan,
        at=datetime_param(request, "at") or services.now(),
        seats=int_param(request, "seats", subscription.seats, minimum=1, maximum=100000),
        generate=bool_param(request, "generate", True),
        reason=opt_str(request, "reason", max_len=200),
    )
    return ok({
        "subscription": serializers.subscription_dict(result["subscription"]),
        "preview": _proration_dict(result["preview"]),
        "invoice": serializers.invoice_dict(result["invoice"], detail=True)
        if result["invoice"] else None,
        "balance_credit": serializers.money(result["balance_credit"]),
    })


@endpoint()
def subscription_pause(request, pk):
    """暂停订阅（停止计费，数据保留）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    sub = services.pause_subscription(request.user, subscription)
    return ok(serializers.subscription_dict(sub, detail=True))


@endpoint()
def subscription_resume(request, pk):
    """恢复订阅（暂停期间不补收费用）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    sub = services.resume_subscription(request.user, subscription)
    return ok(serializers.subscription_dict(sub, detail=True))


@endpoint()
def subscription_cancel(request, pk):
    """期末取消（到期前继续服务，续费时真正失效）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    sub = services.cancel_subscription(request.user, subscription,
                                       reason=opt_str(request, "reason", max_len=200),
                                       immediate=False)
    return ok(serializers.subscription_dict(sub, detail=True))


@endpoint()
def subscription_cancel_now(request, pk):
    """立即取消（马上停止服务，不退款；如需退款请开信用票据）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    sub = services.cancel_subscription(request.user, subscription,
                                       reason=opt_str(request, "reason", max_len=200),
                                       immediate=True)
    return ok(serializers.subscription_dict(sub, detail=True))


@endpoint()
def subscription_renew(request, pk):
    """续费（顺延一个周期并生成下期账单）。"""
    subscription = get_subscription(pk,
                                    request.user, write=True)
    result = services.renew_subscription(request.user, subscription,
                                         generate=bool_param(request, "invoice", True))
    payload = {"subscription": serializers.subscription_dict(result["subscription"]),
               "renewed": result["renewed"], "invoice": None}
    if result["invoice"] is not None:
        payload["invoice"] = serializers.invoice_dict(result["invoice"], detail=True)
    return ok(payload)


@endpoint(("GET",))
def subscription_items(request, pk):
    """订阅明细列表。"""
    subscription = get_subscription(pk, request.user)
    qs = subscription.items.select_related("price", "price__plan").order_by("id")
    return paginate(qs, request, serializers.subscription_item_dict)


@endpoint()
def subscription_item_add(request):
    """添加订阅明细（加购席/插件，可从今天生效或指定日期）。"""
    subscription = get_subscription(int_param(request, "id", required=True, minimum=1),
                                    request.user, write=True)
    price = get_price(int_param(request, "price_id", required=True, minimum=1),
                      request.user)
    if subscription.status == "canceled":
        raise ValueError("已取消的订阅不能加购")
    if price.plan_id != subscription.plan_id:
        raise ValueError("加购价格必须属于当前订阅计划")
    quantity = money_param(request, "quantity", default=1, minimum=0.0001) or services.ONE
    effective_from = date_param(request, "effective_from") or services.today()
    if SubscriptionItem.objects.filter(subscription=subscription, price=price,
                                       effective_to__isnull=True).exists():
        raise ValueError("该价格已在订阅中，请直接调整数量")
    with transaction.atomic():
        item = SubscriptionItem.objects.create(
            owner=subscription.owner,
            subscription=subscription,
            price=price,
            quantity=services.quantize_unit(quantity),
            effective_from=effective_from,
            metadata=dict_param(request, "metadata"),
        )
        services.emit_event(subscription.owner, "subscription.item_added", subscription, {
            "item_id": item.pk, "price_id": price.pk, "quantity": str(item.quantity),
        }, idempotency_key=f"subscription:{subscription.pk}:item:{item.pk}:added")
    return ok(serializers.subscription_item_dict(item))


@endpoint()
def subscription_item_remove(request):
    """移除订阅明细（置为今天失效，历史账单不受影响）。"""
    subscription = get_subscription(int_param(request, "id", required=True, minimum=1),
                                    request.user, write=True)
    item_pk = int_param(request, "item_id", required=True, minimum=1)
    item = subscription.items.select_related("price").filter(pk=item_pk).first()
    if item is None:
        raise ValueError("订阅明细不存在")
    if item.effective_to is not None and item.effective_to <= services.today():
        raise ValueError("该明细已失效")
    if subscription.items.count() <= 1:
        raise ValueError("订阅至少保留一条明细，如需停止请取消订阅")
    with transaction.atomic():
        item.effective_to = services.today()
        item.save(update_fields=["effective_to", "updated_at"])
        services.emit_event(subscription.owner, "subscription.item_removed", subscription, {
            "item_id": item.pk, "effective_to": item.effective_to.isoformat(),
        }, idempotency_key=f"subscription:{subscription.pk}:item:{item.pk}:removed")
    return ok(serializers.subscription_item_dict(item))
