# -*- coding: utf-8 -*-
"""订阅计费 · 优惠券接口（7 个）。

优惠券涉及「钱」，因此校验（validate）与核销（redeem）必须共用同一套规则，
且核销要锁券、幂等、限制次数。这里只做取参与渲染，规则全部在 services。

路由（挂在 /api/billing/ 下）：
    GET  coupons/                优惠券列表
    POST coupons/create/         新建优惠券
    POST coupons/<pk>/update/    更新优惠券
    POST coupons/<pk>/delete/    删除优惠券（有核销记录时拒绝）
    POST coupons/validate/       校验优惠码（只读）
    POST coupons/redeem/         核销优惠码
    GET  coupons/redemptions/    核销记录列表
"""
from django.db import transaction

from devtools.common import endpoint, ok, opt_str, req_str

from billing import serializers, services
from billing.models import (
    COUPON_DURATIONS,
    COUPON_STATUS,
    COUPON_TYPES,
    Coupon,
    CouponRedemption,
)
from billing.views_common import (
    apply_search,
    choice_param,
    datetime_param,
    dict_param,
    filter_by,
    get_customer,
    get_subscription,
    int_param,
    money_param,
    paginate,
)


def _check_coupon_code(code):
    """优惠码只允许 2-60 位可见字符（大小写敏感，便于做渠道专属码）。"""
    value = str(code or "").strip()
    if len(value) < 2 or len(value) > 60:
        raise ValueError("优惠码长度必须在 2-60 位之间")
    if any(ch.isspace() for ch in value):
        raise ValueError("优惠码不能包含空白字符")
    return value


def _parse_time_window(request):
    """解析有效期窗口并校验先后顺序（空表示不限）。"""
    valid_from = datetime_param(request, "valid_from")
    valid_until = datetime_param(request, "valid_until")
    if valid_from and valid_until and valid_until <= valid_from:
        raise ValueError("失效时间必须晚于生效时间")
    return valid_from, valid_until


def _validate_coupon_economics(request, coupon_type, current=None):
    """按券类型校验面额：百分比 0-100，固定金额必须大于 0。"""
    if coupon_type == "percent":
        percent = money_param(request, "percent", required=current is None,
                              default=current.percent if current else 0,
                              minimum=0, maximum=100)
        amount = current.amount if current else services.ZERO
        if percent is not None and percent <= 0:
            raise ValueError("百分比折扣必须大于 0")
        return services.quantize_percent(percent or 0), services.quantize_money(amount or 0)
    amount = money_param(request, "amount", required=current is None,
                         default=current.amount if current else 0, minimum=0)
    percent = current.percent if current else services.ZERO
    if amount is not None and amount <= 0:
        raise ValueError("固定减免金额必须大于 0")
    return services.quantize_percent(percent or 0), services.quantize_money(amount or 0)


# ===========================================================================
# 优惠券
# ===========================================================================


@endpoint(("GET",))
def coupon_list(request):
    """优惠券列表（q/status + 分页）。"""
    qs = services.visible(Coupon.objects.select_related("customer"), request.user)
    qs = apply_search(qs, request, ["code", "name", "description"])
    return paginate(qs.order_by("-created_at", "-id"), request,
                    serializers.coupon_dict)


@endpoint()
def coupon_create(request):
    """新建优惠券（百分比/固定金额，支持一次性/重复 N 期/永久）。"""
    code = _check_coupon_code(req_str(request, "code", max_len=60))
    if Coupon.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("优惠码已存在")
    coupon_type = choice_param(request, "coupon_type", COUPON_TYPES, "percent", "优惠券类型")
    percent, amount = _validate_coupon_economics(request, coupon_type)
    duration = choice_param(request, "duration", COUPON_DURATIONS, "once", "持续时间")
    duration_months = int_param(request, "duration_months", 1, minimum=1, maximum=120)
    if duration != "repeating":
        duration_months = 1
    valid_from, valid_until = _parse_time_window(request)
    customer = None
    customer_id = int_param(request, "customer_id", minimum=1)
    if customer_id:
        customer = get_customer(customer_id, request.user)
    coupon = Coupon.objects.create(
        owner=request.user,
        code=code,
        name=req_str(request, "name", max_len=120).strip(),
        description=opt_str(request, "description", max_len=5000),
        coupon_type=coupon_type,
        percent=percent,
        amount=amount,
        currency=opt_str(request, "currency", "CNY", max_len=8).upper() or "CNY",
        duration=duration,
        duration_months=duration_months,
        max_redemptions=int_param(request, "max_redemptions", 0, minimum=0, maximum=1000000),
        valid_from=valid_from,
        valid_until=valid_until,
        status=choice_param(request, "status", COUPON_STATUS, "active", "优惠券状态"),
        customer=customer,
        metadata=dict_param(request, "metadata"),
    )
    services.emit_event(request.user, "coupon.created", coupon, {
        "code": code, "type": coupon_type, "duration": duration,
    }, idempotency_key=f"coupon:{coupon.pk}:created")
    return ok(serializers.coupon_dict(coupon))


@endpoint()
def coupon_update(request, pk):
    """更新优惠券（面额/有效期/上限/状态）。"""
    coupon = services.get_writable(Coupon, pk,
                                   request.user, "优惠券不存在")
    fields = []
    coupon_type = coupon.coupon_type
    if request.data.get("coupon_type") is not None:
        coupon_type = choice_param(request, "coupon_type", COUPON_TYPES,
                                   coupon.coupon_type, "优惠券类型")
    if request.data.get("percent") is not None or request.data.get("amount") is not None \
            or request.data.get("coupon_type") is not None:
        percent, amount = _validate_coupon_economics(request, coupon_type, coupon)
        coupon.coupon_type = coupon_type
        coupon.percent = percent
        coupon.amount = amount
        fields.extend(["coupon_type", "percent", "amount"])
    if request.data.get("name") is not None:
        coupon.name = req_str(request, "name", max_len=120).strip()
        fields.append("name")
    if request.data.get("description") is not None:
        coupon.description = opt_str(request, "description", max_len=5000)
        fields.append("description")
    if request.data.get("currency") is not None:
        coupon.currency = opt_str(request, "currency", "CNY", max_len=8).upper() or "CNY"
        fields.append("currency")
    if request.data.get("duration") is not None:
        coupon.duration = choice_param(request, "duration", COUPON_DURATIONS,
                                       coupon.duration, "持续时间")
        fields.append("duration")
    if request.data.get("duration_months") is not None:
        coupon.duration_months = int_param(request, "duration_months", 1,
                                           minimum=1, maximum=120)
        fields.append("duration_months")
    if coupon.duration != "repeating":
        coupon.duration_months = 1
    if request.data.get("max_redemptions") is not None:
        max_redemptions = int_param(request, "max_redemptions", 0,
                                    minimum=0, maximum=1000000)
        if max_redemptions and max_redemptions < coupon.redeemed_count:
            raise ValueError("最大核销次数不能小于已核销次数")
        coupon.max_redemptions = max_redemptions
        fields.append("max_redemptions")
    if request.data.get("valid_from") is not None or request.data.get("valid_until") is not None:
        valid_from, valid_until = _parse_time_window(request)
        coupon.valid_from = valid_from
        coupon.valid_until = valid_until
        fields.extend(["valid_from", "valid_until"])
    if request.data.get("status") is not None:
        coupon.status = choice_param(request, "status", COUPON_STATUS,
                                     coupon.status, "优惠券状态")
        fields.append("status")
    if request.data.get("customer_id") is not None:
        customer_id = int_param(request, "customer_id", minimum=0)
        if customer_id:
            coupon.customer = get_customer(customer_id, request.user)
        else:
            coupon.customer = None
        fields.append("customer")
    if request.data.get("metadata") is not None:
        coupon.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    if not fields:
        raise ValueError("没有需要更新的字段")
    coupon.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
    return ok(serializers.coupon_dict(coupon))


@endpoint()
def coupon_delete(request, pk):
    """删除优惠券（已有核销记录时拒绝，建议停用）。"""
    coupon = services.get_writable(Coupon, pk,
                                   request.user, "优惠券不存在")
    if coupon.redemptions.exists():
        raise ValueError("优惠券已有核销记录，不能删除（请停用）")
    pk = coupon.pk
    with transaction.atomic():
        coupon.delete()
        services.emit_event(request.user, "coupon.deleted", None, {"coupon_id": pk},
                            idempotency_key=f"coupon:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


@endpoint()
def coupon_validate(request):
    """校验优惠码（只读）：有效期/上限/客户限制/一次性 + 抵扣金额。"""
    code = req_str(request, "code", max_len=60)
    customer = get_customer(int_param(request, "customer_id", required=True, minimum=1),
                            request.user)
    subscription = None
    subscription_id = int_param(request, "subscription_id", minimum=1)
    if subscription_id:
        subscription = get_subscription(subscription_id, request.user)
        if subscription.customer_id != customer.pk:
            raise ValueError("订阅不属于该客户")
    result = services.validate_coupon(
        code, customer,
        amount=money_param(request, "amount", default=0, minimum=0) or services.ZERO,
        subscription=subscription, user=request.user,
    )
    data = dict(result)
    data["base_amount"] = serializers.money(data["base_amount"])
    data["discount"] = serializers.money(data["discount"])
    data["amount"] = serializers.money(data["amount"])
    data["percent"] = str(data["percent"])
    return ok(data)


@endpoint()
def coupon_redeem(request):
    """核销优惠码（幂等键重复时返回原核销记录）。"""
    code = req_str(request, "code", max_len=60)
    coupon = services.find_coupon(code, request.user)
    if coupon is None:
        raise ValueError("优惠券不存在")
    customer = get_customer(int_param(request, "customer_id", required=True, minimum=1),
                            request.user, write=True)
    subscription = None
    subscription_id = int_param(request, "subscription_id", minimum=1)
    if subscription_id:
        subscription = get_subscription(subscription_id, request.user, write=True)
        if subscription.customer_id != customer.pk:
            raise ValueError("订阅不属于该客户")
    redemption = services.redeem_coupon(
        request.user, coupon, customer, subscription=subscription,
        amount=money_param(request, "amount", required=True, minimum=0.01),
        idempotency_key=opt_str(request, "idempotency_key", max_len=120),
    )
    coupon.refresh_from_db()
    return ok({
        "redemption": serializers.redemption_dict(redemption),
        "coupon_remaining": coupon.remaining,
        "redeemed_count": coupon.redeemed_count,
    })


@endpoint(("GET",))
def coupon_redemptions(request):
    """核销记录列表（q/优惠券/客户/订阅 + 分页）。"""
    qs = services.visible(
        CouponRedemption.objects.select_related("coupon", "customer", "subscription"),
        request.user)
    qs = filter_by(qs, request, "coupon_id")
    qs = filter_by(qs, request, "customer_id")
    qs = filter_by(qs, request, "subscription_id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        from django.db.models import Q

        qs = qs.filter(Q(coupon__code__icontains=keyword)
                       | Q(customer__name__icontains=keyword))
    return paginate(qs.order_by("-created_at", "-id"), request,
                    serializers.redemption_dict)
