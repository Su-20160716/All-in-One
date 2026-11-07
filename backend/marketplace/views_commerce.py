# -*- coding: utf-8 -*-
"""应用市场 · 定价、购买与许可证接口（12 个）。

本地支付模拟（不联网）但语义完整：
- 定价必须与应用的定价模式一致（免费应用不能配置价格）；
- 购买生成订单号，支付成功才签发许可证，许可证只返回一次明文密钥；
- 订阅按周期计算有效期，永久授权无到期时间，试用按试用天数；
- 退款在 7 天内可自助申请（管理员不受限），退款会撤销许可证并冲减收入。
"""
import secrets
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)

from . import services
from .common import (ensure_listing_visible, get_license, get_listing,
                     get_pricing, get_purchase, is_staff_user,
                     listing_by_reference, paginate_queryset, parse_dict)
from .models import (
    LICENSE_STATUS_VALUES,
    LICENSE_TYPE_VALUES,
    PRICING_MODE_VALUES,
    PURCHASE_STATUS_VALUES,
    License,
    Listing,
    Pricing,
    Purchase,
)
from .serializers import (iso, license_dict, listing_brief, pricing_dict,
                          purchase_dict)

# 定价周期：一次性 / 月 / 年（订阅制据此推导许可证有效期）
PRICING_PERIODS = ("one_time", "month", "year")
# 自助退款窗口（天）
REFUND_WINDOW_DAYS = 7
MAX_PRICE = Decimal("10000000")


def _decimal_price(request, field="price", default=Decimal("0")):
    """价格入参：Decimal 转换 + 非负 + 上限，禁止 NaN/Infinity。"""
    raw = p(request, field)
    if raw in (None, ""):
        return default
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("price 必须是数字")
    if not value.is_finite():
        raise ValueError("price 必须是有限数字")
    if value < 0:
        raise ValueError("price 不能小于 0")
    if value > MAX_PRICE:
        raise ValueError(f"price 不能大于 {MAX_PRICE}")
    return value.quantize(Decimal("0.01"))


def _currency(value, default="CNY"):
    """币种校验。"""
    text = str(value or default).upper().strip()
    if text not in services.CURRENCY_VALUES:
        raise ValueError(f"currency 支持 {'/'.join(services.CURRENCY_VALUES)}")
    return text


def _period(value, default="one_time"):
    """定价周期校验。"""
    text = str(value or default).strip()
    if text not in PRICING_PERIODS:
        raise ValueError(f"period 支持 {'/'.join(PRICING_PERIODS)}")
    return text


def _order_no():
    """订单号：时间前缀 + 随机后缀（本地唯一性由数据库约束兜底）。"""
    return f"MP{timezone.now():%Y%m%d%H%M%S}{secrets.token_hex(3).upper()}"


def _license_type_for(listing, price, trial_days):
    """按定价推导许可证类型：试用 > 订阅 > 永久。"""
    if trial_days > 0 and price <= 0:
        return "trial"
    pricing = None
    try:
        pricing = listing.mp_pricing
    except Pricing.DoesNotExist:
        pricing = None
    if pricing is not None and pricing.period in ("month", "year"):
        return "subscription"
    return "perpetual"


def _activate_metadata(request):
    """设备元信息（激活时记录，便于用户识别设备）。"""
    meta = parse_dict(request, "meta")
    allowed = ("os", "app_version", "machine", "note")
    return {key: str(meta.get(key, ""))[:200] for key in allowed if meta.get(key)}


# ---------------------------------------------------------------------------
# 定价
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def listing_pricing(request, pk):
    """读取应用定价或设置定价（维护者；价格/币种/试用/周期一次保存）。"""
    listing = get_listing(pk, request.user)
    if request.method == "GET":
        ensure_listing_visible(listing, request.user)
        data = services.pricing_payload(listing)
        pricing = None
        try:
            pricing = listing.mp_pricing
        except Pricing.DoesNotExist:
            pricing = None
        data["pricing"] = pricing_dict(pricing) if pricing is not None else None
        return ok(data)

    from .common import ensure_listing_writable

    ensure_listing_writable(listing, request.user)
    mode = opt_str(request, "mode", listing.pricing_mode).strip()
    if mode not in PRICING_MODE_VALUES:
        raise ValueError(f"mode 支持 {'/'.join(PRICING_MODE_VALUES)}")
    price = _decimal_price(request, default=Decimal("0"))
    if mode == "free":
        price = Decimal("0")
    if mode == "paid" and price <= 0:
        raise ValueError("付费应用的价格必须大于 0")
    trial_days = int(opt_num(request, "trial_days", 0, minimum=0, maximum=365,
                             integer=True))
    if mode == "free":
        trial_days = 0
    currency = _currency(opt_str(request, "currency", "CNY"))
    period = _period(opt_str(request, "period", "one_time"))
    with transaction.atomic():
        pricing, created = Pricing.objects.update_or_create(
            listing=listing,
            defaults={
                "owner": request.user,
                "mode": mode,
                "price": price,
                "currency": currency,
                "trial_days": trial_days,
                "period": period,
                "active": opt_bool(request, "active", True),
                "remark": opt_str(request, "remark", ""),
            },
        )
        listing.pricing_mode = mode
        listing.save(update_fields=["pricing_mode", "updated_at"])
    return ok({"pricing": pricing_dict(pricing), "created": created,
               "listing_id": listing.id})


@endpoint()
def pricing_update(request, pk):
    """更新定价（维护者；只改传入字段，校验与创建一致）。"""
    pricing = get_pricing(pk, request.user, write=True)
    if p(request, "mode") is not None:
        mode = str(p(request, "mode")).strip()
        if mode not in PRICING_MODE_VALUES:
            raise ValueError(f"mode 支持 {'/'.join(PRICING_MODE_VALUES)}")
        pricing.mode = mode
    if p(request, "price") not in (None, ""):
        pricing.price = _decimal_price(request, default=pricing.price)
    if pricing.mode == "free":
        pricing.price = Decimal("0")
        pricing.trial_days = 0
    if pricing.mode == "paid" and pricing.price <= 0:
        raise ValueError("付费应用的价格必须大于 0")
    if p(request, "currency") is not None:
        pricing.currency = _currency(p(request, "currency"))
    if p(request, "trial_days") not in (None, ""):
        pricing.trial_days = int(opt_num(request, "trial_days", pricing.trial_days,
                                         minimum=0, maximum=365, integer=True))
    if p(request, "period") is not None:
        pricing.period = _period(p(request, "period"))
    if p(request, "active") is not None:
        pricing.active = opt_bool(request, "active", pricing.active)
    pricing.save()
    pricing.listing.pricing_mode = pricing.mode
    pricing.listing.save(update_fields=["pricing_mode", "updated_at"])
    return ok(pricing_dict(pricing))


@endpoint()
def pricing_delete(request, pk):
    """删除定价（维护者；已有订单时拒绝，避免历史订单失去计价依据）。"""
    pricing = get_pricing(pk, request.user, write=True)
    listing = pricing.listing
    if listing.mp_purchases.exists():
        raise ValueError("该应用已有购买订单，不能删除定价（可改为停用）")
    pid = pricing.id
    with transaction.atomic():
        pricing.delete()
        listing.pricing_mode = "free"
        listing.save(update_fields=["pricing_mode", "updated_at"])
    return ok({"deleted": True, "id": pid, "listing_id": listing.id})


# ---------------------------------------------------------------------------
# 购买
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def purchases(request):
    """我的购买列表（q/status 分页）或购买应用（支付成功即签发许可证）。"""
    if request.method == "GET":
        queryset = (Purchase.objects.filter(owner=request.user)
                    .select_related("listing", "listing__publisher", "version", "owner")
                    .order_by("-created_at"))
        status = opt_str(request, "status").strip()
        if status:
            if status not in PURCHASE_STATUS_VALUES:
                raise ValueError(f"status 支持 {'/'.join(PURCHASE_STATUS_VALUES)}")
            queryset = queryset.filter(payment_status=status)
        return ok(paginate_queryset(
            request, queryset, purchase_dict,
            search_fields=("order_no", "listing__name", "listing__code"),
            status_field=None,
        ))

    listing = listing_by_reference(request)
    ensure_listing_visible(listing, request.user)
    if listing.status != "published":
        raise ValueError("应用未上架，不能购买")
    if listing.publisher.owner_id == request.user.id:
        raise ValueError("不能购买自己发布的应用")
    if listing.pricing_mode == "free":
        # 免费应用无需下单：直接返回可安装提示，避免产生 0 元垃圾订单
        raise ValueError("免费应用无需购买，直接安装即可")
    price, currency = services.effective_price(listing)
    pay_now = opt_bool(request, "pay", True)
    trial_days = 0
    try:
        trial_days = int(listing.mp_pricing.trial_days or 0)
    except Pricing.DoesNotExist:
        trial_days = 0
    existing = listing.mp_purchases.filter(owner=request.user, payment_status="paid").first()
    period = "one_time"
    try:
        period = listing.mp_pricing.period
    except Pricing.DoesNotExist:
        period = "one_time"
    if existing is not None and period not in ("month", "year"):
        raise ValueError("你已购买该应用，无需重复购买")

    order_no = _order_no()
    while Purchase.objects.filter(order_no=order_no).exists():
        order_no = _order_no()
    plain_key = None
    with transaction.atomic():
        purchase = Purchase.objects.create(
            owner=request.user,
            listing=listing,
            version=listing.latest_version,
            order_no=order_no,
            price=price,
            currency=currency,
            payment_status="pending",
            channel=opt_str(request, "channel", "local")[:30],
            invoice=parse_dict(request, "invoice"),
        )
        if pay_now:
            purchase.payment_status = "paid"
            purchase.purchased_at = timezone.now()
            purchase.save(update_fields=["payment_status", "purchased_at", "updated_at"])
            license_type = _license_type_for(listing, price, trial_days)
            license_obj, plain_key = services.issue_license(
                purchase,
                license_type=license_type,
                max_activations=int(opt_num(request, "max_activations", 3,
                                            minimum=1, maximum=20, integer=True)),
                trial_days=trial_days,
            )
            services.emit_event(
                listing, "purchase.paid",
                {"order_no": purchase.order_no, "price": float(price),
                 "currency": currency, "license_id": license_obj.id},
                request.user,
            )
    data = purchase_dict(purchase, with_breakdown=True)
    data["license"] = license_dict(purchase.mp_license) if hasattr(purchase, "mp_license") else None
    # 明文密钥只在此响应返回一次，数据库仅保存哈希
    data["license_key"] = plain_key
    return ok(data)


@endpoint(("GET",))
def purchase_detail(request, pk):
    """订单详情（购买者/发布者/管理员；含分成拆分与许可证）。"""
    purchase = get_purchase(pk, request.user)
    show_breakdown = (
        is_staff_user(request.user)
        or purchase.listing.publisher.owner_id == request.user.id
    )
    data = purchase_dict(purchase, with_breakdown=show_breakdown)
    license_obj = getattr(purchase, "mp_license", None)
    data["license"] = license_dict(license_obj) if license_obj is not None else None
    return ok(data)


@endpoint()
def purchase_refund(request, pk):
    """申请退款（购买者 7 天内自助；管理员不受限；退款撤销许可证）。"""
    purchase = get_purchase(pk, request.user, write=True)
    if purchase.payment_status == "refunded":
        raise ValueError("订单已退款")
    if purchase.payment_status != "paid":
        raise ValueError("只有已支付订单可以退款")
    if not is_staff_user(request.user):
        if purchase.purchased_at is None:
            raise ValueError("订单缺少支付时间，请联系管理员")
        days = (timezone.now() - purchase.purchased_at).days
        if days > REFUND_WINDOW_DAYS:
            raise ValueError(f"已超过 {REFUND_WINDOW_DAYS} 天退款窗口，请联系管理员")
    reason = opt_str(request, "reason", "", max_len=300)
    with transaction.atomic():
        purchase.payment_status = "refunded"
        purchase.refunded_at = timezone.now()
        purchase.refund_amount = purchase.price
        purchase.save(update_fields=["payment_status", "refunded_at",
                                     "refund_amount", "updated_at"])
        license_obj = getattr(purchase, "mp_license", None)
        if license_obj is not None and license_obj.status != "revoked":
            license_obj.status = "revoked"
            license_obj.revoked_reason = f"订单退款：{reason or '用户申请'}"[:300]
            license_obj.save(update_fields=["status", "revoked_reason", "updated_at"])
        services.emit_event(
            purchase.listing, "purchase.refunded",
            {"order_no": purchase.order_no, "amount": float(purchase.price),
             "reason": reason},
            request.user,
        )
    data = purchase_dict(purchase, with_breakdown=True)
    data["license"] = (license_dict(purchase.mp_license)
                       if hasattr(purchase, "mp_license") else None)
    return ok(data)


@endpoint(("GET",))
def purchase_license(request, pk):
    """查看订单对应的许可证（不返回明文密钥）。"""
    purchase = get_purchase(pk, request.user)
    license_obj = getattr(purchase, "mp_license", None)
    if license_obj is None:
        raise ValueError("该订单没有关联许可证")
    return ok(license_dict(license_obj))


# ---------------------------------------------------------------------------
# 许可证
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def licenses(request):
    """我的许可证列表（q/status 分页；管理员可看全部）。"""
    if is_staff_user(request.user) and opt_bool(request, "all", False):
        queryset = License.objects.all()
    else:
        queryset = License.objects.filter(owner=request.user)
    queryset = queryset.select_related("listing", "purchase", "owner").order_by("-created_at")
    status = opt_str(request, "status").strip()
    if status:
        if status not in LICENSE_STATUS_VALUES:
            raise ValueError(f"status 支持 {'/'.join(LICENSE_STATUS_VALUES)}")
        queryset = queryset.filter(status=status)
    return ok(paginate_queryset(
        request, queryset, license_dict,
        search_fields=("listing__name", "listing__code", "key_hint"),
        status_field=None,
    ))


@endpoint(("GET",))
def license_detail(request, pk):
    """许可证详情（不含密钥哈希与明文）。"""
    license_obj = get_license(pk, request.user)
    data = license_dict(license_obj)
    data["verification"] = services.verify_license(
        license_obj, None, mark=False)
    return ok(data)


@endpoint()
def license_verify(request):
    """校验许可证：密钥哈希、有效期、激活次数与应用一致性。"""
    license_id = opt_num(request, "license_id", integer=True)
    key = opt_str(request, "key").strip()
    license_obj = None
    if license_id:
        license_obj = get_license(int(license_id), request.user)
    elif key:
        license_obj = License.objects.select_related("listing").filter(
            key_hash=services.hash_license_key(key)).first()
        if license_obj is None:
            raise ValueError("许可证密钥无效")
        if license_obj.owner_id != request.user.id and not is_staff_user(request.user):
            raise ValueError("无权校验他人的许可证")
    else:
        raise ValueError("请提供 license_id 或 key")
    listing_code = opt_str(request, "listing_code").strip()
    listing = None
    if listing_code:
        listing = Listing.objects.filter(code=listing_code).first()
        if listing is None:
            raise ValueError("应用不存在")
    device_id = opt_str(request, "device_id").strip()
    result = services.verify_license(license_obj, key or None, listing=listing,
                                     device_id=device_id)
    result["checked_at"] = timezone.now().isoformat()
    return ok(result)


@endpoint()
def license_activate(request, pk):
    """激活许可证到设备（同一设备幂等；超上限报错）。"""
    license_obj = get_license(pk, request.user, write=True)
    device_id = req_str(request, "device_id", max_len=120).strip()
    result = services.activate_license(
        license_obj, device_id, _activate_metadata(request))
    services.emit_event(
        license_obj.listing, "license.activated",
        {"license_id": license_obj.id, "device_id": device_id},
        request.user,
    )
    result["activation_count"] = len(license_obj.activations or [])
    return ok(result)


@endpoint()
def license_deactivate(request, pk):
    """停用许可证设备（不传 device_id 视为全部停用）。"""
    license_obj = get_license(pk, request.user, write=True)
    device_id = opt_str(request, "device_id").strip()
    result = services.deactivate_license(license_obj, device_id)
    result["license"] = license_dict(license_obj)
    return ok(result)


COMMERCE_ENDPOINT_COUNT = 12
