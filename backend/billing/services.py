# -*- coding: utf-8 -*-
"""订阅计费 · 服务层。

本模块是 billing 的「唯一业务真相」，视图只负责取参、权限与渲染。这样拆分
的原因：金额、周期、用量、折算、催收这些规则会被多个接口复用（例如发票
生成、账单预测、客户概览都要算订阅费），逻辑留在视图里必然出现两份实现，
而后端最怕的就是「两套算法对同一个客户给出两个数字」。

章节
----
1. 金额工具        —— Decimal 量化、百分比、安全除法
2. 周期推进        —— 月末对齐、闰年安全、试用到期
3. 定价            —— 阶梯计价、按量单价、包含额度
4. 用量            —— 聚合、幂等上报、超量计费
5. 升降级折算      —— 按天 proration
6. 发票            —— 生成、行项、税、幂等、作废、PDF 元数据
7. 支付            —— 登记、捕获、重试、退款、余额/信用额度
8. 催收            —— 策略步骤、状态机推进、幂等扫描
9. 优惠券          —— 校验、折扣计算、核销
10. 指标与预测     —— MRR/ARR/ARPU/流失/试用转化/逾期/趋势/分布/预测
11. 事件与权限     —— 审计事件、可见/可写判定

约定：所有对「当前时间」的判断都走 timezone.now()/localdate()，不写死日期，
测试里可以直接构造过去/未来的数据来验证状态机，无需 mock 时钟。
"""
import calendar
import random
import string
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

from core.scoping import scope_queryset

from billing.models import (
    CREDIT_NOTE_STATUS,
    DUNNING_ACTIONS,
    INVOICE_BLOCKING_STATUS,
    LIVE_SUBSCRIPTION_STATUS,
    BillingEvent,
    Coupon,
    CouponRedemption,
    CreditNote,
    Customer,
    DunningPolicy,
    DunningRun,
    DunningStep,
    Feature,
    Invoice,
    InvoiceLine,
    Meter,
    Payment,
    Plan,
    PlanFeature,
    Price,
    Subscription,
    SubscriptionItem,
    TaxRate,
    UsageRecord,
)

# ---------------------------------------------------------------------------
# 常量：金额精度集中在这里，避免各处出现魔法数字
# ---------------------------------------------------------------------------

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
MONEY_QUANT = Decimal("0.01")      # 汇总金额保留 2 位（分）
UNIT_QUANT = Decimal("0.0001")     # 单价/数量保留 4 位
PERCENT_QUANT = Decimal("0.0001")  # 税率保留 4 位（13.0000%）

DEFAULT_CURRENCY = "CNY"
DEFAULT_DUE_DAYS = 7
MAX_PERIOD_ITERATIONS = 2400  # 100 年，防御脏数据导致死循环


# ===========================================================================
# 1. 金额工具
# ===========================================================================


def to_decimal(value, field="金额", minimum=None, maximum=None):
    """把入参安全转成 Decimal。

    拒绝 bool（Python 里 True 是 1，直接被当成金额会静默写错账），拒绝
    NaN/Infinity（会污染后续聚合且无法 JSON 序列化），拒绝科学计数法以外
    的非法字符串。所有写入金额的入口都必须先过这一关，保证「禁止 float 入库」。
    """
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是数字")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        # float 只在解析入口出现，且立即用 str() 截断二进制尾差；
        # 数据库层永远是 DecimalField，不会存 float。
        result = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} 不能为空")
        try:
            result = Decimal(text)
        except InvalidOperation:
            raise ValueError(f"{field} 必须是数字")
    else:
        raise ValueError(f"{field} 必须是数字")
    if not result.is_finite():
        raise ValueError(f"{field} 必须是有限数字")
    if minimum is not None and result < Decimal(str(minimum)):
        raise ValueError(f"{field} 不能小于 {minimum}")
    if maximum is not None and result > Decimal(str(maximum)):
        raise ValueError(f"{field} 不能大于 {maximum}")
    return result


def quantize_money(value):
    """金额量化到 2 位，四舍五入用 ROUND_HALF_UP。

    不用默认的 ROUND_HALF_EVEN：财务口径（发票、对账）普遍要求四舍五入，
    银行家舍入会让 0.125 变成 0.12，与客户手算结果不一致。
    """
    return to_decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def quantize_unit(value):
    """单价/数量量化到 4 位（按量单价可能小于 1 分）。"""
    return to_decimal(value).quantize(UNIT_QUANT, rounding=ROUND_HALF_UP)


def quantize_percent(value):
    """税率/折扣率量化到 4 位。"""
    return to_decimal(value).quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)


def money_str(value):
    """渲染用字符串：统一两位小数，避免 JSON 里出现 12.0 / 12 两种形态。"""
    return str(quantize_money(value))


def unit_str(value):
    """单价渲染：保留 4 位，去掉无意义的尾零由前端决定。"""
    return str(quantize_unit(value))


def percent_amount(amount, percent):
    """按百分比算金额：percent=13 表示 13%。

    先乘后除且只量化一次，减少中间舍入误差；负数金额（折算抵扣）同样适用。
    """
    base = to_decimal(amount)
    pct = to_decimal(percent)
    return quantize_money(base * pct / HUNDRED)


def safe_div(numerator, denominator, default=ZERO, places=4):
    """安全除法：分母为 0 时返回默认值（比例类指标常见空集）。"""
    den = to_decimal(denominator)
    if den == 0:
        return to_decimal(default)
    return (to_decimal(numerator) / den).quantize(
        Decimal("1." + "0" * places), rounding=ROUND_HALF_UP)


def percent_ratio(numerator, denominator, places=2):
    """算百分比（0–100），分母为 0 返回 0。"""
    return safe_div(to_decimal(numerator) * HUNDRED, denominator, default=ZERO, places=places)


def sum_money(values):
    """Decimal 求和并量化；空集合返回 0.00。"""
    total = ZERO
    for value in values:
        total += to_decimal(value)
    return quantize_money(total)


def clamp_money(value, low=ZERO):
    """金额下限裁剪（应收/余额不允许出现负数展示）。"""
    amount = quantize_money(value)
    return amount if amount > low else quantize_money(low)


def min_money(a, b):
    """取较小金额（部分退款、额度上限都用它）。"""
    left, right = quantize_money(a), quantize_money(b)
    return left if left < right else right


def is_positive(value):
    """金额是否大于 0（避免在视图里 repeated 写 to_decimal(...) > 0）。"""
    return to_decimal(value) > ZERO


def parse_boolish(value, default=False):
    """宽松布尔解析（HTTP 参数常以字符串出现）。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


# ===========================================================================
# 2. 周期推进（月末对齐 / 闰年安全）
# ===========================================================================


def month_last_day(year, month):
    """某年某月最后一天，calendar.monthrange 已处理闰年。"""
    return calendar.monthrange(year, month)[1]


def add_months(day, months):
    """日期加 N 个月，月末对齐。

    规则：1/31 + 1 月 = 2/28（闰年 2/29），而不是抛异常或溢出到 3/3。
    订阅周期必须可预测，溢出会让「每月 31 日」的客户在 2 月连续扣两次。
    """
    if not isinstance(day, date):
        raise ValueError("日期格式不正确")
    total = day.year * 12 + (day.month - 1) + int(months)
    year, month = divmod(total, 12)
    month += 1
    last = month_last_day(year, month)
    return date(year, month, min(day.day, last))


def add_period(start, billing_period):
    """按计费周期返回「下一周期起始」（即本周期结束，左闭右开）。

    one_time 没有续期概念，用 +1 天表示单日周期，让区间校验与天数折算
    仍然成立（避免出现 start == end 的除零）。
    """
    if not isinstance(start, date):
        raise ValueError("周期起始日期格式不正确")
    if billing_period == "monthly":
        return add_months(start, 1)
    if billing_period == "yearly":
        return add_months(start, 12)
    if billing_period == "one_time":
        return start + timedelta(days=1)
    raise ValueError(f"未知计费周期: {billing_period}")


def period_bounds(start, billing_period):
    """返回 (start, end_exclusive)。"""
    return start, add_period(start, billing_period)


def period_days(start, end):
    """周期天数，至少 1（防御 start == end 的脏数据）。"""
    if not start or not end:
        return 1
    return max((end - start).days, 1)


def period_datetimes(start, end):
    """把日期区间转成「本地时区」的 aware datetime 区间（左闭右开）。

    用量按时间戳过滤，必须与账期的本地日界一致；直接用 UTC 会让
    「1 号 00:00（北京时间）」的用量被算进上月。
    """
    tz = timezone.get_current_timezone()
    begin = timezone.make_aware(datetime.combine(start, time.min), tz)
    finish = timezone.make_aware(datetime.combine(end, time.min), tz)
    return begin, finish


def current_period_for(start_date, billing_period, at=None):
    """给定首期起始日，推算包含 at（默认今天）的周期 (start, end)。

    校验 at 不早于首期；循环上限防御脏配置（例如周期长度算成 0）。
    """
    at = at or timezone.localdate()
    start = start_date
    if at < start:
        # 未来起租：直接以首期为当前期，不在「无周期」状态上抛错，
        # 预付费场景允许客户先建订阅、后生效。
        return start, add_period(start, billing_period)
    for _ in range(MAX_PERIOD_ITERATIONS):
        end = add_period(start, billing_period)
        if start <= at < end:
            return start, end
        start = end
    raise ValueError("订阅周期配置异常，无法定位当前账期")


def next_period_bounds(start, billing_period):
    """下一周期区间 (next_start, next_end)。"""
    next_start = add_period(start, billing_period)
    return next_start, add_period(next_start, billing_period)


def trial_end_from(start_date, trial_days):
    """试用结束时间：首日 00:00 + N 天（本地时区 aware）。

    用 DateTime 而不是 Date：试用到期往往在当天某刻触发转化，保留时间精度
    便于「到期即转正」的定时任务判定。
    """
    days = int(trial_days or 0)
    tz = timezone.get_current_timezone()
    base = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    return base + timedelta(days=max(days, 0))


def month_key(value):
    """统一月份键 YYYY-MM（收入趋势分组用）。"""
    if isinstance(value, datetime):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return f"{value.year:04d}-{value.month:02d}"


def month_start(day):
    """当月第一天。"""
    return day.replace(day=1)


def month_range_back(months, at=None):
    """最近 N 个自然月的 (start, end) 列表，按时间升序。

    end 是「下月 1 日」（不含），与账期口径一致，避免月末最后一天漏算。
    """
    at = at or timezone.localdate()
    current = month_start(at)
    out = []
    for offset in range(months - 1, -1, -1):
        start = add_months(current, -offset)
        out.append((start, add_months(start, 1)))
    return out


def parse_date(value, field="日期"):
    """解析 YYYY-MM-DD；兼容 date/datetime 实例。"""
    if value in (None, ""):
        raise ValueError(f"{field}不能为空")
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    if isinstance(value, date):
        return value
    from django.utils.dateparse import parse_date as _parse_date

    parsed = _parse_date(str(value).strip())
    if parsed is None:
        raise ValueError(f"{field}格式应为 YYYY-MM-DD")
    return parsed


def parse_datetime(value, field="时间"):
    """解析 ISO 时间；不带时区时按本地时区补齐（避免 naive/aware 比较报错）。"""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        from django.utils.dateparse import parse_datetime as _parse_datetime

        dt = _parse_datetime(str(value).strip())
        if dt is None:
            raise ValueError(f"{field}格式应为 ISO 8601")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def now():
    """统一取当前时间（测试可 monkeypatch 本函数，而不是散落各处）。"""
    return timezone.now()


def today():
    """统一取本地今天。"""
    return timezone.localdate()


# ===========================================================================
# 3. 定价
# ===========================================================================


def normalize_tiers(raw):
    """校验并归一化阶梯配置。

    输入 ``[{"up_to": 100, "unit_amount": 0.5}, ...]``，输出金额统一为字符串
    （JSON 里 0.1 的浮点尾差会让「刚好 100 件」的账单相差 0.01）。
    up_to=null/0 表示最后一档「以上」，必须排在最后且唯一。
    """
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError("阶梯配置必须是数组")
    if len(raw) > 50:
        raise ValueError("阶梯配置最多 50 档")
    out = []
    last_up_to = 0
    for index, tier in enumerate(raw):
        if not isinstance(tier, dict):
            raise ValueError(f"第 {index + 1} 档阶梯格式不正确")
        up_to_raw = tier.get("up_to", tier.get("to"))
        unlimited = up_to_raw in (None, "", 0, "0")
        if unlimited:
            up_to = None
        else:
            up_to = int(to_decimal(up_to_raw, f"第 {index + 1} 档阶梯上限", minimum=1))
            if up_to <= last_up_to:
                raise ValueError("阶梯上限必须严格递增")
            if up_to in [t["up_to"] for t in out if t["up_to"] is not None]:
                raise ValueError("阶梯上限不能重复")
            last_up_to = up_to
        unit_amount = quantize_unit(to_decimal(
            tier.get("unit_amount", tier.get("amount", 0)),
            f"第 {index + 1} 档单价", minimum=0))
        out.append({
            "up_to": up_to,
            "unit_amount": str(unit_amount),
            "label": str(tier.get("label", ""))[:60],
        })
    unlimited_count = sum(1 for t in out if t["up_to"] is None)
    if unlimited_count > 1:
        raise ValueError("只能有一个「以上」阶梯")
    if unlimited_count and out[-1]["up_to"] is not None:
        raise ValueError("「以上」阶梯必须放在最后一档")
    return out


def tiered_amount(tiers, quantity):
    """累计阶梯计价：每一档只对落在该档内的数量计费。

    例：100 件以内 0.5，1000 件以内 0.3，以上 0.1，150 件 =
    100*0.5 + 50*0.3 = 65.00。用「累计」而非「统一价」是 SaaS 计费惯例，
    客户不会因为跨档而整体涨价。
    """
    qty = to_decimal(quantity, "数量", minimum=0)
    if qty == 0:
        return quantize_money(0)
    normalized = normalize_tiers(tiers) if tiers else []
    if not normalized:
        return quantize_money(0)
    total = ZERO
    previous = ZERO
    for tier in normalized:
        up_to = tier["up_to"]
        unit_amount = to_decimal(tier["unit_amount"])
        if up_to is None:
            take = qty - previous
        else:
            take = min(qty, Decimal(up_to)) - previous
        if take > 0:
            total += take * unit_amount
        if up_to is not None:
            previous = Decimal(up_to)
        if up_to is None or qty <= previous:
            break
    return quantize_money(total)


def line_amount(price, quantity=ONE):
    """按价格模式计算行金额。

    flat     : 固定价 × 数量（数量表示席位/份数）
    per_unit : 单价 × 数量
    tiered   : 阶梯累计价，单价字段不参与（避免两种口径混用）
    """
    if price is None:
        return quantize_money(0)
    qty = to_decimal(quantity, "数量", minimum=0)
    if price.billing_mode == "tiered":
        return tiered_amount(price.tiers, qty)
    amount = to_decimal(price.amount) * qty
    return quantize_money(amount)


def applicable_price(plan, currency=DEFAULT_CURRENCY, at=None):
    """按币种 + 生效窗口取当前价格；同一窗口多条时取最新创建的一条。

    返回 None 表示「该计划在该币种下暂不可售」，由调用方给出中文提示，
    而不是静默按 0 元开票。
    """
    at = at or today()
    qs = plan.prices.filter(currency=(currency or DEFAULT_CURRENCY), status="active")
    candidates = [p for p in qs if p.covers(at)]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p.effective_from or date.min, p.pk), reverse=True)
    return candidates[0]


def require_price(plan, currency=DEFAULT_CURRENCY, at=None):
    """取价，取不到抛业务错误（中文提示直接给前端）。"""
    price = applicable_price(plan, currency, at)
    if price is None:
        raise ValueError(f"计划 {plan.name} 在 {currency} 下没有生效价格")
    return price


def plan_limits(plan):
    """计划功能上限字典的安全读取（JSON 可能是 null/数组等脏值）。"""
    limits = plan.limits if isinstance(plan.limits, dict) else {}
    return limits


def plan_feature_map(plan):
    """计划功能绑定：feature.code -> PlanFeature。"""
    out = {}
    for binding in plan.plan_features.select_related("feature").all():
        out[binding.feature.code] = binding
    return out


def included_allowance(plan, feature_code):
    """包含额度：PlanFeature 优先，其次 Plan.limits 里的数值配置。"""
    binding = plan_feature_map(plan).get(feature_code)
    if binding is not None:
        return quantize_unit(binding.included_qty)
    limits = plan_limits(plan)
    raw = limits.get(feature_code)
    if isinstance(raw, dict):
        raw = raw.get("included", raw.get("limit", 0))
    if isinstance(raw, bool) or raw in (None, ""):
        return quantize_unit(0)
    try:
        return quantize_unit(to_decimal(raw, minimum=0))
    except ValueError:
        return quantize_unit(0)


def overage_rate(plan, feature_code):
    """超量单价：只认 PlanFeature；没配置视为不收费（0）。"""
    binding = plan_feature_map(plan).get(feature_code)
    if binding is None:
        return quantize_unit(0)
    return quantize_unit(binding.overage_unit_amount)


def feature_enabled(plan, feature_code):
    """布尔型功能是否开启：limits 里 true / PlanFeature 存在即视为开启。"""
    limits = plan_limits(plan)
    if feature_code in limits:
        value = limits.get(feature_code)
        if isinstance(value, dict):
            return bool(value.get("enabled", True))
        return bool(value)
    return feature_code in plan_feature_map(plan)


def subscription_item_amount(item, at=None):
    """单条订阅明细的周期金额（数量 × 价格，按价格模式）。"""
    return line_amount(item.price, item.quantity)


def subscription_period_amount(subscription, at=None):
    """订阅一个周期的固定费（不含用量），用于 MRR 与折算基准。

    没有任何明细行的历史/手工订阅，回退到「计划当前价 × 席位数」，
    保证老数据也能算出金额而不是 0。
    """
    items = list(subscription.items.select_related("price").all())
    if items:
        total = ZERO
        for item in items:
            if item.active_on(at or today()):
                total += subscription_item_amount(item, at)
        return quantize_money(total)
    price = applicable_price(subscription.plan, subscription.currency, at)
    if price is None:
        return quantize_money(0)
    return line_amount(price, subscription.seats or 1)


def monthly_value(amount, billing_period):
    """把周期金额折算成月金额（MRR 口径）。

    年付 /12、月付原值、一次性不计入经常性收入（return 0）。用除法后量化，
    不反向乘 12 再除，避免放大误差。
    """
    amount = to_decimal(amount)
    if billing_period == "monthly":
        return quantize_money(amount)
    if billing_period == "yearly":
        return quantize_money(amount / Decimal(12))
    return quantize_money(0)


def subscription_monthly_value(subscription, at=None):
    """订阅的月度经常性收入（含明细行，按各自价格所属计划的周期折算）。"""
    items = list(subscription.items.select_related("price", "price__plan").all())
    if not items:
        price = applicable_price(subscription.plan, subscription.currency, at)
        if price is None:
            return quantize_money(0)
        amount = line_amount(price, subscription.seats or 1)
        return monthly_value(amount, subscription.plan.billing_period)
    total = ZERO
    day = at or today()
    for item in items:
        if not item.active_on(day):
            continue
        period = item.price.plan.billing_period if item.price_id else subscription.plan.billing_period
        total += monthly_value(subscription_item_amount(item, day), period)
    return quantize_money(total)

# ===========================================================================
# 4. 用量：聚合、幂等上报、超量计费
# ===========================================================================


def usage_queryset(subscription, meter=None, start=None, end=None):
    """账期内的用量流水（左闭右开，本地日界）。"""
    qs = UsageRecord.objects.filter(subscription=subscription)
    if meter is not None:
        qs = qs.filter(meter=meter)
    if start and end:
        begin, finish = period_datetimes(start, end)
        qs = qs.filter(occurred_at__gte=begin, occurred_at__lt=finish)
    return qs


def aggregate_quantity(qs, aggregation):
    """按计量项的聚合方式算一个数。

    sum/max/count 直接下推到数据库；latest 取最新一条的 quantity（不是
    累加），用于「当前存储量」「当前席位」这类瞬时值。
    """
    if aggregation == "sum":
        value = qs.aggregate(v=Sum("quantity"))["v"]
        return quantize_unit(value or 0)
    if aggregation == "max":
        value = qs.aggregate(v=Max("quantity"))["v"]
        return quantize_unit(value or 0)
    if aggregation == "count":
        return quantize_unit(qs.count())
    if aggregation == "latest":
        value = qs.order_by("-occurred_at", "-id").values_list("quantity", flat=True).first()
        return quantize_unit(value or 0)
    raise ValueError(f"未知聚合方式: {aggregation}")


def aggregate_usage(subscription, meter, start, end):
    """某订阅某计量项在账期内的聚合用量。"""
    return aggregate_quantity(usage_queryset(subscription, meter, start, end), meter.aggregation)


def usage_charge(subscription, meter, quantity):
    """计算超量费用：先扣包含额度，再乘超量单价。

    返回结构化结果而不是单个金额，是因为前端要同时展示「用了多少 / 免多少 /
    超多少 / 收多少」，只返回金额会让审计无从核对。
    """
    qty = quantize_unit(quantity)
    included = included_allowance(subscription.plan, meter.code)
    billable = qty - included
    if billable < 0:
        billable = ZERO
    rate = overage_rate(subscription.plan, meter.code)
    amount = quantize_money(billable * rate)
    return {
        "quantity": qty,
        "included": included,
        "billable": quantize_unit(billable),
        "unit_amount": rate,
        "amount": amount,
    }


def usage_breakdown(subscription, start, end):
    """账期内所有计量项的用量明细（有流水的计量项才出现）。"""
    rows = []
    meter_ids = list(usage_queryset(subscription, start=start, end=end)
                     .values_list("meter_id", flat=True).distinct())
    meters = Meter.objects.filter(pk__in=meter_ids).order_by("id")
    for meter in meters:
        qs = usage_queryset(subscription, meter, start, end)
        qty = aggregate_quantity(qs, meter.aggregation)
        charge = usage_charge(subscription, meter, qty)
        rows.append({
            "meter_id": meter.pk,
            "meter_code": meter.code,
            "meter_name": meter.name,
            "aggregation": meter.aggregation,
            "unit": meter.unit or charge.get("unit", ""),
            "records": qs.count(),
            "quantity": charge["quantity"],
            "included": charge["included"],
            "billable": charge["billable"],
            "unit_amount": charge["unit_amount"],
            "amount": charge["amount"],
        })
    return rows


def usage_summary(subscription, start, end):
    """用量汇总：明细 + 合计用量/合计金额。"""
    rows = usage_breakdown(subscription, start, end)
    total_amount = sum_money([row["amount"] for row in rows])
    total_quantity = sum((row["quantity"] for row in rows), ZERO)
    return {
        "subscription_id": subscription.pk,
        "period_start": start,
        "period_end": end,
        "items": rows,
        "meter_count": len(rows),
        "total_quantity": quantize_unit(total_quantity),
        "total_amount": total_amount,
    }


def report_usage(owner, subscription, meter, quantity, occurred_at=None,
                 idempotency_key="", source="api", metadata=None):
    """上报一条用量，返回 (记录, 是否新建)。

    幂等键冲突时返回既有记录且 created=False：调用方重试不会重复计费。
    锁订阅行是为了拦住「取消中的订阅仍在写入量」的并发窗口。
    """
    qty = to_decimal(quantity, "用量", minimum=0)
    if qty <= 0:
        raise ValueError("用量必须大于 0")
    event_time = parse_datetime(occurred_at, "发生时间") if occurred_at else now()
    if event_time > now() + timedelta(minutes=5):
        # 允许 5 分钟时钟漂移；更远的未来时间通常是接入方时间戳单位写错（毫秒）
        raise ValueError("发生时间不能晚于当前时间")
    key = str(idempotency_key or "").strip()[:120]
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().select_related("plan", "customer") \
            .filter(pk=subscription.pk).first()
        if sub is None:
            raise ValueError("订阅不存在")
        if sub.status == "canceled":
            raise ValueError("订阅已取消，不能上报用量")
        if meter.status != "active":
            raise ValueError("计量项已停用")
        if key:
            existing = UsageRecord.objects.filter(owner=sub.owner_id,
                                                  idempotency_key=key).first()
            if existing is not None:
                return existing, False
        record = UsageRecord.objects.create(
            owner=sub.owner,
            subscription=sub,
            meter=meter,
            quantity=quantize_unit(qty),
            occurred_at=event_time,
            idempotency_key=key,
            source=str(source or "api")[:60],
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        emit_event(
            sub.owner, "usage.reported", record,
            {"subscription_id": sub.pk, "meter": meter.code,
             "quantity": str(record.quantity), "occurred_at": event_time.isoformat()},
            idempotency_key=f"usage:{record.pk}",
        )
    return record, True


def batch_report_usage(owner, subscription, rows):
    """批量上报：整体一个事务，任意一条非法则全部回滚。

    返回每条的 (id, created)；重复幂等键不报错，只标记 created=False，
    这样接入方可以安全重放整批数据。
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows 必须是非空数组")
    if len(rows) > 500:
        raise ValueError("单批最多 500 条用量")
    meter_cache = {}
    results = []
    created_count = 0
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().select_related("plan") \
            .filter(pk=subscription.pk).first()
        if sub is None:
            raise ValueError("订阅不存在")
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"第 {index} 条用量格式不正确")
            meter_code = row.get("meter") or row.get("meter_code")
            if not meter_code:
                raise ValueError(f"第 {index} 条缺少计量编码")
            meter = meter_cache.get(meter_code)
            if meter is None:
                meter = Meter.objects.filter(code=str(meter_code)).first()
                if meter is None:
                    raise ValueError(f"计量项不存在: {meter_code}")
                meter_cache[meter_code] = meter
            record, created = report_usage(
                owner, sub, meter,
                row.get("quantity", row.get("qty")),
                occurred_at=row.get("occurred_at"),
                idempotency_key=row.get("idempotency_key", ""),
                source=row.get("source", "batch"),
                metadata=row.get("metadata"),
            )
            created_count += 1 if created else 0
            results.append({"id": record.pk, "meter": meter.code,
                            "quantity": record.quantity, "created": created})
    return {"items": results, "count": len(results), "created": created_count}


# ===========================================================================
# 5. 订阅生命周期
# ===========================================================================


def _lock_subscription(subscription):
    """事务内锁定订阅（必须在 atomic 内调用）。"""
    sub = Subscription.objects.select_for_update().select_related("plan", "customer") \
        .filter(pk=subscription.pk).first()
    if sub is None:
        raise ValueError("订阅不存在")
    return sub


def _is_admin(user):
    """管理员通行判定（超管/员工）。数据范围再宽也不是写权限，见 core.scoping。"""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def ensure_visible(obj, user):
    """读权限：管理员放行，其余走数据范围（self/dept/all + 租户）。"""
    if obj is None:
        raise ValueError("对象不存在")
    if _is_admin(user):
        return obj
    ids = _visible_ids(user)
    if ids is not None and getattr(obj, "owner_id", None) not in ids:
        raise ValueError("无权查看该数据")
    return obj


def _visible_ids(user):
    """当前用户可见 owner 集合；None 表示不限。"""
    from core.scoping import visible_user_ids

    return visible_user_ids(user)


def ensure_writable(obj, user):
    """写权限：管理员或 owner 本人。

    与读取范围刻意分离：部门负责人可以看本部门账单，但不能改价/收款，
    否则财务口径会被业务侧随手改乱。
    """
    if obj is None:
        raise ValueError("对象不存在")
    if _is_admin(user):
        return obj
    if getattr(obj, "owner_id", None) != getattr(user, "id", None):
        raise ValueError("无权修改该数据")
    return obj


def visible(qs, user):
    """按数据范围过滤；管理员不限制（满足「管理员可看全部」）。"""
    if _is_admin(user):
        return qs
    return scope_queryset(qs, user)


def get_visible(model, pk, user, message="对象不存在"):
    """按主键取可见对象，取不到统一中文提示。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    return ensure_visible(obj, user)


def get_writable(model, pk, user, message="对象不存在"):
    """按主键取可写对象（视图更新/删除入口统一用它）。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    return ensure_writable(obj, user)


def create_subscription(actor, customer, plan, currency=None, seats=1,
                        start_date=None, trial=None, price=None, metadata=None):
    """新建订阅并落一条订阅明细。

    - 计划必须已发布（草稿/停用计划不能售卖，避免测试价被误开通）；
    - 试用开关：显式 trial=True/False 优先，否则按计划 trial_days 自动判断；
    - 明细行必须存在：后续账单、MRR、折算都以明细为基准，缺行会导致金额为 0。
    """
    if customer.status != "active":
        raise ValueError("客户已归档，不能开通订阅")
    if plan.status != "active":
        raise ValueError("计划未发布，不能开通订阅")
    start = parse_date(start_date, "开始日期") if start_date else today()
    currency = (currency or customer.currency or DEFAULT_CURRENCY).upper()[:8]
    chosen_price = price or require_price(plan, currency, start)
    if chosen_price.plan_id != plan.pk:
        raise ValueError("价格不属于该计划")
    if chosen_price.currency != currency:
        raise ValueError("价格币种与订阅币种不一致")
    try:
        seat_count = int(to_decimal(seats, "席位数", minimum=1))
    except (TypeError, ValueError):
        raise ValueError("席位数必须是正整数")
    if trial is True:
        trial_days = plan.trial_days or 14
    elif trial is False:
        trial_days = 0
    else:
        trial_days = plan.trial_days or 0
    period_start, period_end = period_bounds(start, plan.billing_period)
    status = "trialing" if trial_days > 0 else "active"
    with transaction.atomic():
        sub = Subscription.objects.create(
            owner=actor,
            customer=customer,
            plan=plan,
            status=status,
            currency=currency,
            seats=seat_count,
            start_date=start,
            trial_end=trial_end_from(start, trial_days) if trial_days > 0 else None,
            current_period_start=period_start,
            current_period_end=period_end,
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        SubscriptionItem.objects.create(
            owner=actor,
            subscription=sub,
            price=chosen_price,
            quantity=Decimal(seat_count),
            effective_from=period_start,
        )
        emit_event(actor, "subscription.created", sub, {
            "customer_id": customer.pk, "plan": plan.code,
            "status": status, "trial_days": trial_days,
            "amount": str(line_amount(chosen_price, seat_count)),
        }, idempotency_key=f"subscription:{sub.pk}:created")
    return sub


def activate_subscription(actor, subscription, generate=True):
    """开通/恢复服务：试用转正或暂停恢复，必要时补一张当期账单。"""
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status == "active":
            return {"subscription": sub, "invoice": None, "changed": False}
        if sub.status == "canceled":
            raise ValueError("订阅已取消，不能开通")
        if sub.status == "paused":
            sub.status = "active"
            sub.paused_at = None
            sub.save(update_fields=["status", "paused_at", "updated_at"])
        else:
            sub.status = "active"
            if sub.trial_end is not None:
                sub.trial_end = now()
            start = today()
            sub.current_period_start = start
            sub.current_period_end = add_period(start, sub.plan.billing_period)
            sub.save(update_fields=["status", "trial_end", "current_period_start",
                                    "current_period_end", "updated_at"])
        invoice = None
        if generate and sub.current_period_start:
            existing = existing_invoice_for(sub, sub.current_period_start)
            if existing is None:
                invoice = generate_invoice(actor, sub, period_start=sub.current_period_start)
        emit_event(sub.owner, "subscription.activated", sub, {
            "invoice_id": invoice.pk if invoice else None,
        }, idempotency_key=f"subscription:{sub.pk}:activated:{sub.current_period_start}")
    return {"subscription": sub, "invoice": invoice, "changed": True}


def convert_trial(actor, subscription, generate=True):
    """试用转正：写入真实试用结束时间、重置账期、生成首张账单。

    只允许 trialing → active，重复调用返回 changed=False（幂等），避免
    前端重试把试用转正执行两次、开出两张首期账单。
    """
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status != "trialing":
            raise ValueError("只有试用中的订阅可以转正")
        ended = now()
        start = today()
        sub.status = "active"
        sub.trial_end = ended
        sub.current_period_start = start
        sub.current_period_end = add_period(start, sub.plan.billing_period)
        sub.save(update_fields=["status", "trial_end", "current_period_start",
                                "current_period_end", "updated_at"])
        invoice = None
        if generate and existing_invoice_for(sub, start) is None:
            invoice = generate_invoice(actor, sub, period_start=start)
        emit_event(sub.owner, "subscription.trial_converted", sub, {
            "invoice_id": invoice.pk if invoice else None,
            "trial_end": ended.isoformat(),
        }, idempotency_key=f"subscription:{sub.pk}:trial_converted")
    return {"subscription": sub, "invoice": invoice, "changed": True}


def pause_subscription(actor, subscription):
    """暂停服务：保留数据与订阅关系，停止计费（不生成新账单）。"""
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status == "paused":
            return sub
        if sub.status not in LIVE_SUBSCRIPTION_STATUS:
            raise ValueError(f"当前状态 {sub.status} 不能暂停")
        sub.status = "paused"
        sub.paused_at = now()
        sub.save(update_fields=["status", "paused_at", "updated_at"])
        emit_event(sub.owner, "subscription.paused", sub, {},
                   idempotency_key=f"subscription:{sub.pk}:paused:{sub.paused_at.isoformat()}")
    return sub


def resume_subscription(actor, subscription):
    """恢复服务：从暂停回到生效，不补收暂停期间费用（暂停即不计费）。"""
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status == "active":
            return sub
        if sub.status != "paused":
            raise ValueError(f"当前状态 {sub.status} 不能恢复")
        sub.status = "active"
        sub.paused_at = None
        sub.save(update_fields=["status", "paused_at", "updated_at"])
        emit_event(sub.owner, "subscription.resumed", sub, {},
                   idempotency_key=f"subscription:{sub.pk}:resumed:{now().isoformat()}")
    return sub


def cancel_subscription(actor, subscription, reason="", immediate=False):
    """取消订阅：默认期末取消（保留服务到期满），immediate=True 立即失效。"""
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status == "canceled":
            return sub
        if sub.status not in LIVE_SUBSCRIPTION_STATUS and sub.status != "paused":
            raise ValueError(f"当前状态 {sub.status} 不能取消")
        sub.cancel_reason = str(reason or "")[:200]
        sub.canceled_at = now()
        sub.auto_renew = False
        if immediate:
            sub.status = "canceled"
            sub.cancel_at_period_end = False
        else:
            sub.cancel_at_period_end = True
        sub.save(update_fields=["status", "cancel_reason", "canceled_at", "auto_renew",
                                "cancel_at_period_end", "updated_at"])
        emit_event(sub.owner, "subscription.canceled", sub, {
            "immediate": bool(immediate), "reason": sub.cancel_reason,
        }, idempotency_key=f"subscription:{sub.pk}:canceled:{sub.canceled_at.isoformat()}")
    return sub


def renew_subscription(actor, subscription, generate=True):
    """续费：按当前周期顺延一个周期并生成下期账单。

    期末取消的订阅在这里真正变为 canceled（不再延期），避免「点了取消还在扣费」。
    重复续费是幂等的：同一周期已有账单时不会重复开票，只返回既有账单。
    """
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status == "canceled":
            raise ValueError("订阅已取消，不能续费")
        if sub.cancel_at_period_end:
            sub.status = "canceled"
            sub.save(update_fields=["status", "updated_at"])
            emit_event(sub.owner, "subscription.canceled_at_period_end", sub, {},
                       idempotency_key=f"subscription:{sub.pk}:ended")
            return {"subscription": sub, "invoice": None, "renewed": False}
        new_start = sub.current_period_end
        new_end = add_period(new_start, sub.plan.billing_period)
        sub.current_period_start = new_start
        sub.current_period_end = new_end
        if sub.status == "past_due":
            sub.status = "active"
        sub.save(update_fields=["current_period_start", "current_period_end",
                                "status", "updated_at"])
        invoice = None
        if generate and existing_invoice_for(sub, new_start) is None:
            invoice = generate_invoice(actor, sub, period_start=new_start)
        emit_event(sub.owner, "subscription.renewed", sub, {
            "period_start": new_start.isoformat(),
            "period_end": new_end.isoformat(),
            "invoice_id": invoice.pk if invoice else None,
        }, idempotency_key=f"subscription:{sub.pk}:renewed:{new_start}")
    return {"subscription": sub, "invoice": invoice, "renewed": True}


# ===========================================================================
# 6. 升降级折算（proration，按天）
# ===========================================================================


def remaining_days(subscription, at=None):
    """当前周期剩余天数（不含当天之前的整段）。"""
    at_date = at or today()
    if isinstance(at_date, datetime):
        at_date = timezone.localtime(at_date).date() if timezone.is_aware(at_date) else at_date.date()
    end = subscription.current_period_end
    return max((end - at_date).days, 0)


def proration_for_plan_change(subscription, new_plan, at=None, new_price=None, seats=None):
    """计算升/降级折算：退未用旧费 + 收未用新费。

    按天折算（remaining / total_days），保留 2 位。不用「按秒」是因为账期
    以自然日结算，秒级精度除了制造对账噪音没有业务价值。
    返回 credit（退）、charge（收）、net（差额）与天数明细，供预览与落账共用。
    """
    at = at or now()
    at_date = at.date() if isinstance(at, datetime) else at
    if new_plan.pk == subscription.plan_id:
        raise ValueError("新计划与当前计划相同")
    total_days = period_days(subscription.current_period_start, subscription.current_period_end)
    left = remaining_days(subscription, at_date)
    ratio = Decimal(left) / Decimal(total_days)
    old_amount = subscription_period_amount(subscription, at_date)
    new_price = new_price or require_price(new_plan, subscription.currency, at_date)
    seat_count = seats or subscription.seats or 1
    try:
        seat_count = int(to_decimal(seat_count, "席位数", minimum=1))
    except (TypeError, ValueError):
        raise ValueError("席位数必须是正整数")
    new_amount = line_amount(new_price, seat_count)
    credit = quantize_money(old_amount * ratio)
    charge = quantize_money(new_amount * ratio)
    net = charge - credit
    return {
        "from_plan_id": subscription.plan_id,
        "to_plan_id": new_plan.pk,
        "from_plan": subscription.plan.code,
        "to_plan": new_plan.code,
        "upgrade": new_amount > old_amount,
        "at": at_date,
        "period_start": subscription.current_period_start,
        "period_end": subscription.current_period_end,
        "total_days": total_days,
        "remaining_days": left,
        "ratio": str(ratio.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "old_period_amount": old_amount,
        "new_period_amount": new_amount,
        "credit": credit,
        "charge": charge,
        "net": net,
        "currency": subscription.currency,
        "seats": seat_count,
        "new_price_id": new_price.pk,
    }


def apply_plan_change(actor, subscription, new_plan, at=None, seats=None,
                      generate=True, reason=""):
    """执行升降级：改计划/明细价、按差额开折算账单（或退到余额）。

    为什么不改历史账单：已开出的上一张发票是法律凭证，折算必须落在新账单上，
    否则作废重开会导致已收款发票与银行流水对不上。
    """
    at = at or now()
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status not in LIVE_SUBSCRIPTION_STATUS:
            raise ValueError(f"当前状态 {sub.status} 不能变更计划")
        if new_plan.status != "active":
            raise ValueError("目标计划未发布")
        preview = proration_for_plan_change(sub, new_plan, at=at, seats=seats)
        sub.plan = new_plan
        if seats:
            sub.seats = preview["seats"]
        sub.save(update_fields=["plan", "seats", "updated_at"])
        items = list(sub.items.select_related("price").order_by("id"))
        new_price = Price.objects.get(pk=preview["new_price_id"])
        if items:
            item = items[0]
            item.price = new_price
            item.quantity = Decimal(preview["seats"])
            item.save(update_fields=["price", "quantity", "updated_at"])
        else:
            SubscriptionItem.objects.create(
                owner=sub.owner, subscription=sub, price=new_price,
                quantity=Decimal(preview["seats"]),
                effective_from=sub.current_period_start,
            )
        invoice = None
        balance_credit = ZERO
        if generate and preview["net"] != ZERO:
            if preview["net"] > 0:
                invoice = _create_proration_invoice(actor, sub, preview, reason)
            else:
                # 降级差额退到客户余额，下期账单自动抵扣；不开红字发票，
                # 减少发票张数（客户对账更清爽）。
                balance_credit = -preview["net"]
                customer = sub.customer
                customer.balance = quantize_money((customer.balance or ZERO) + balance_credit)
                customer.save(update_fields=["balance", "updated_at"])
        emit_event(sub.owner, "subscription.plan_changed", sub, {
            "from_plan": preview["from_plan"], "to_plan": preview["to_plan"],
            "net": str(preview["net"]),
            "invoice_id": invoice.pk if invoice else None,
            "balance_credit": str(balance_credit),
        }, idempotency_key=f"subscription:{sub.pk}:plan_changed:{month_key(at)}:{new_plan.pk}")
    return {"subscription": sub, "preview": preview, "invoice": invoice,
            "balance_credit": balance_credit}


def _create_proration_invoice(actor, subscription, preview, reason=""):
    """把正差额落成一张待支付发票（两张行项：退旧 + 收新）。"""
    number = next_invoice_number(actor)
    start = preview["period_start"]
    invoice = Invoice.objects.create(
        owner=actor,
        number=number,
        customer=subscription.customer,
        subscription=subscription,
        status="open",
        source="proration",
        currency=subscription.currency,
        period_start=start,
        period_end=preview["period_end"],
        due_date=today() + timedelta(days=DEFAULT_DUE_DAYS),
        notes=(reason or "计划变更折算")[:2000],
        metadata={"proration": {
            "from_plan": preview["from_plan"], "to_plan": preview["to_plan"],
            "ratio": preview["ratio"], "remaining_days": preview["remaining_days"],
            "total_days": preview["total_days"],
        }},
    )
    InvoiceLine.objects.create(
        owner=actor, invoice=invoice, line_type="proration",
        description=f"旧计划未用部分抵扣（{preview['remaining_days']}/{preview['total_days']} 天）",
        quantity=Decimal("1"), unit_amount=-preview["credit"],
        amount=-preview["credit"], sort_order=1,
        metadata={"direction": "credit", "plan": preview["from_plan"]},
    )
    InvoiceLine.objects.create(
        owner=actor, invoice=invoice, line_type="proration",
        description=f"新计划剩余周期费用（{preview['to_plan']}）",
        quantity=Decimal("1"), unit_amount=preview["charge"],
        amount=preview["charge"], sort_order=2,
        metadata={"direction": "charge", "plan": preview["to_plan"]},
    )
    recalc_invoice(invoice)
    return invoice

# ===========================================================================
# 7. 发票
# ===========================================================================


def _next_sequence_number(model, owner, prefix, width=4):
    """生成「前缀 + 递增序号」的业务编号（按 owner 维度的当月号段）。

    不依赖数据库自增：发票号需要可读（INV-202611-0001），且要能按客户/月份
    归档；冲突时向后探测，唯一约束兜底并发（极少见，重试即可）。
    """
    sequence = model.objects.filter(owner=owner, number__startswith=prefix).count() + 1
    for _ in range(1000):
        candidate = f"{prefix}{sequence:0{width}d}"
        if not model.objects.filter(owner=owner, number=candidate).exists():
            return candidate
        sequence += 1
    raise ValueError("发票号段已耗尽，请检查编号规则")


def next_invoice_number(owner, at=None):
    """发票编号：INV-YYYYMM-0001。"""
    at = at or now()
    day = at.date() if isinstance(at, datetime) else at
    return _next_sequence_number(Invoice, owner, f"INV-{day.year}{day.month:02d}-")


def next_credit_note_number(owner, at=None):
    """信用票据编号：CN-YYYYMM-0001。"""
    at = at or now()
    day = at.date() if isinstance(at, datetime) else at
    return _next_sequence_number(CreditNote, owner, f"CN-{day.year}{day.month:02d}-")


def existing_invoice_for(subscription, period_start, statuses=INVOICE_BLOCKING_STATUS):
    """同订阅同周期是否已有发票（幂等生成的核心判定）。

    作废（void）与无法收回（uncollectible）不阻塞重新开票，因为这两种状态
    意味着原票不再具有收款效力。
    """
    return Invoice.objects.filter(
        subscription=subscription,
        period_start=period_start,
        status__in=statuses,
    ).order_by("-id").first()


def add_invoice_line(invoice, line_type, description, quantity=ONE, unit_amount=ZERO,
                     amount=None, metadata=None, sort_order=0):
    """追加行项；金额缺省时由数量 × 单价推导并量化。

    行项金额是账单真源，recalc 只做汇总；这里统一量化，避免出现
    「单价 0.3333 × 3 = 0.9999」这种分位误差被带入总额。
    """
    if line_type not in ("subscription", "usage", "proration", "discount", "tax", "credit"):
        raise ValueError(f"未知行类型: {line_type}")
    qty = quantize_unit(to_decimal(quantity, "数量", minimum=0))
    unit = quantize_unit(to_decimal(unit_amount, "单价"))
    line_total = quantize_money(amount) if amount is not None \
        else quantize_money(qty * unit)
    return InvoiceLine.objects.create(
        owner=invoice.owner,
        invoice=invoice,
        line_type=line_type,
        description=str(description or "")[:200],
        quantity=qty,
        unit_amount=unit,
        amount=line_total,
        metadata=metadata if isinstance(metadata, dict) else {},
        sort_order=int(sort_order or 0),
    )


def recalc_invoice(invoice, save=True):
    """按行项重算小计/折扣/税/总额。

    口径：subtotal = 除折扣与税以外的行项之和（含负数折算抵扣）；
    discount_total = 折扣行绝对值；tax_total = 税行之和；
    total = subtotal - discount_total + tax_total，负数按 0 兜底。
    """
    lines = list(invoice.lines.all())
    subtotal = ZERO
    discount = ZERO
    tax = ZERO
    for line in lines:
        if line.line_type == "discount":
            discount += abs(to_decimal(line.amount))
        elif line.line_type == "tax":
            tax += to_decimal(line.amount)
        else:
            subtotal += to_decimal(line.amount)
    subtotal = quantize_money(subtotal)
    discount = quantize_money(discount)
    tax = quantize_money(tax)
    total = quantize_money(subtotal - discount + tax)
    if total < 0:
        # 折扣大于消费时不允许出现负数发票；多余部分应在优惠券校验阶段拦截
        total = quantize_money(0)
    invoice.subtotal = subtotal
    invoice.discount_total = discount
    invoice.tax_total = tax
    invoice.total = total
    if save:
        invoice.save(update_fields=["subtotal", "discount_total", "tax_total",
                                    "total", "updated_at"])
    return invoice


def resolve_tax_rate(customer, at=None):
    """按客户国家/地区与生效日解析税率：精确地区 > 默认 > 同国任意。"""
    day = at or today()
    if isinstance(day, datetime):
        day = timezone.localtime(day).date() if timezone.is_aware(day) else day.date()
    qs = list(TaxRate.objects.filter(enabled=True, country=customer.country or "CN"))
    viable = [t for t in qs if t.covers(day)]
    if not viable:
        return None
    region = customer.region or ""
    exact = [t for t in viable if (t.region or "") == region]
    if exact:
        return sorted(exact, key=lambda t: (not t.is_default, t.pk))[0]
    defaults = [t for t in viable if t.is_default]
    if defaults:
        return sorted(defaults, key=lambda t: t.pk)[0]
    narrowed = [t for t in viable if not t.region]
    return sorted(narrowed or viable, key=lambda t: t.pk)[0]


def find_coupon(code, user=None):
    """按优惠码取券（默认只在可见范围内找，避免跨账号用别人的码）。"""
    text = str(code or "").strip()
    if not text:
        return None
    qs = visible(Coupon.objects.all(), user) if user is not None else Coupon.objects.all()
    return qs.filter(code=text).order_by("-id").first()


def _invoice_usage_lines(invoice, subscription, start, end):
    """把账期内未开票的用量汇聚成行项，并标记已开票。

    即使全部在包含额度内也要标记 invoiced：否则同一笔用量会在下个账期
    再次进入聚合，形成「额度每月重置但历史用量回头计费」的重复收费。
    """
    begin, finish = period_datetimes(start, end)
    base_qs = UsageRecord.objects.filter(
        subscription=subscription, invoiced=False,
        occurred_at__gte=begin, occurred_at__lt=finish,
    )
    meter_ids = list(base_qs.values_list("meter_id", flat=True).distinct())
    if not meter_ids:
        return ZERO
    total = ZERO
    meters = {m.pk: m for m in Meter.objects.filter(pk__in=meter_ids)}
    order = 100
    for meter_id in meter_ids:
        meter = meters.get(meter_id)
        if meter is None:
            continue
        qs = base_qs.filter(meter=meter)
        qty = aggregate_quantity(qs, meter.aggregation)
        charge = usage_charge(subscription, meter, qty)
        if charge["amount"] > 0:
            add_invoice_line(
                invoice, "usage",
                f"{meter.name} 用量（{charge['quantity']} {meter.unit or ''}，"
                f"含额度 {charge['included']}）",
                quantity=charge["billable"] or charge["quantity"],
                unit_amount=charge["unit_amount"],
                amount=charge["amount"],
                metadata={"meter": meter.code, "quantity": str(charge["quantity"]),
                          "included": str(charge["included"]),
                          "billable": str(charge["billable"])},
                sort_order=order,
            )
            total += charge["amount"]
            order += 1
        qs.update(invoiced=True, invoice=invoice)
    return quantize_money(total)


def generate_invoice(actor, subscription, period_start=None, currency=None,
                     due_days=DEFAULT_DUE_DAYS, include_usage=True,
                     coupon_code="", notes="", status="draft"):
    """生成订阅账单：订阅费 + 用量 + 折扣 + 税。

    幂等：同订阅同周期已有 draft/open/paid 发票时直接拒绝（中文提示），
    避免定时任务与手工点击并发开出两张账单。
    """
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        start = parse_date(period_start, "周期起始") if period_start else sub.current_period_start
        if not start:
            raise ValueError("订阅缺少账期起始，无法生成发票")
        end = add_period(start, sub.plan.billing_period)
        if existing_invoice_for(sub, start) is not None:
            raise ValueError("该订阅本期已生成发票，不能重复生成")
        currency = (currency or sub.currency or DEFAULT_CURRENCY).upper()[:8]
        invoice = Invoice.objects.create(
            owner=actor,
            number=next_invoice_number(actor),
            customer=sub.customer,
            subscription=sub,
            status="draft",
            source="subscription",
            currency=currency,
            period_start=start,
            period_end=end,
            due_date=today() + timedelta(days=max(int(due_days), 0)),
            notes=str(notes or "")[:2000],
        )
        line_no = 1
        fee_total = ZERO
        items = list(sub.items.select_related("price", "price__plan").order_by("id"))
        for item in items:
            if not item.active_on(start):
                continue
            amount = subscription_item_amount(item, start)
            if amount == 0:
                continue
            price = item.price
            period_label = {"monthly": "月", "yearly": "年", "one_time": "一次性"} \
                .get(price.plan.billing_period, price.plan.billing_period)
            add_invoice_line(
                invoice, "subscription",
                f"{sub.plan.name} · {price.plan.name}（{period_label}）",
                quantity=item.quantity,
                unit_amount=price.amount,
                amount=amount,
                metadata={"price_id": price.pk, "billing_mode": price.billing_mode,
                          "item_id": item.pk},
                sort_order=line_no,
            )
            fee_total += amount
            line_no += 1
        if fee_total == 0:
            price = applicable_price(sub.plan, currency, start)
            if price is None:
                raise ValueError(f"计划 {sub.plan.name} 在 {currency} 下没有生效价格")
            amount = line_amount(price, sub.seats or 1)
            add_invoice_line(
                invoice, "subscription", f"{sub.plan.name} 订阅费",
                quantity=Decimal(sub.seats or 1), unit_amount=price.amount,
                amount=amount, metadata={"price_id": price.pk},
                sort_order=line_no,
            )
            fee_total = amount
            line_no += 1
        if include_usage:
            used = _invoice_usage_lines(invoice, sub, start, end)
        else:
            used = ZERO
        base_amount = quantize_money(fee_total + used)
        discount = ZERO
        code = str(coupon_code or "").strip()
        if code:
            coupon = find_coupon(code, actor)
            if coupon is None:
                raise ValueError("优惠券不存在")
            check = validate_coupon(coupon_code, sub.customer, base_amount,
                                    subscription=sub, user=actor)
            discount = check["discount"]
            if discount > 0:
                add_invoice_line(
                    invoice, "discount",
                    f"优惠券 {coupon.code} 减免",
                    quantity=ONE, unit_amount=-discount, amount=-discount,
                    metadata={"coupon": coupon.code, "type": coupon.coupon_type,
                              "duration": coupon.duration},
                    sort_order=900,
                )
                redeem_coupon(actor, coupon, sub.customer, subscription=sub,
                              amount=base_amount,
                              idempotency_key=f"invoice:{invoice.number}:coupon")
        taxable = quantize_money(base_amount - discount)
        tax_rate = resolve_tax_rate(sub.customer, start)
        if tax_rate is not None and taxable > 0 and tax_rate.rate > 0:
            tax = percent_amount(taxable, tax_rate.rate)
            if tax > 0:
                add_invoice_line(
                    invoice, "tax", f"{tax_rate.name}（{tax_rate.rate}%）",
                    quantity=ONE, unit_amount=tax, amount=tax,
                    metadata={"tax_rate_id": tax_rate.pk, "rate": str(tax_rate.rate),
                              "base": str(taxable)},
                    sort_order=950,
                )
        if status == "open":
            invoice.status = "open"
            invoice.sent_at = now()
        recalc_invoice(invoice)
        emit_event(sub.owner, "invoice.generated", invoice, {
            "subscription_id": sub.pk, "customer_id": sub.customer_id,
            "period_start": start.isoformat(), "period_end": end.isoformat(),
            "total": str(invoice.total), "currency": invoice.currency,
        }, idempotency_key=f"invoice:{invoice.pk}:generated")
    return invoice


def send_invoice(actor, invoice):
    """发送发票（状态模拟）：草稿 → 待支付，记录发送时间。

    已发送的发票再次调用直接返回，不重复改状态（前端重试友好）。
    """
    with transaction.atomic():
        inv = Invoice.objects.select_for_update().select_related("customer") \
            .filter(pk=invoice.pk).first()
        if inv is None:
            raise ValueError("发票不存在")
        ensure_writable(inv, actor)
        if inv.status == "void":
            raise ValueError("已作废发票不能发送")
        if inv.status == "paid":
            raise ValueError("已支付发票无需发送")
        if inv.sent_at is not None and inv.status == "open":
            return inv
        inv.status = "open"
        inv.sent_at = now()
        inv.save(update_fields=["status", "sent_at", "updated_at"])
        emit_event(inv.owner, "invoice.sent", inv, {"total": str(inv.total)},
                   idempotency_key=f"invoice:{inv.pk}:sent")
    return inv


def void_invoice(actor, invoice, reason=""):
    """作废发票：释放占用的用量流水，避免「票作废了用量也跟着丢」。

    已支付发票必须先退款/开红字，不允许直接作废（会计凭证不可凭空消失）。
    """
    with transaction.atomic():
        inv = Invoice.objects.select_for_update().filter(pk=invoice.pk).first()
        if inv is None:
            raise ValueError("发票不存在")
        ensure_writable(inv, actor)
        if inv.status == "paid" or inv.amount_paid > 0:
            raise ValueError("已收款的发票不能作废，请先退款或开信用票据")
        if inv.status == "void":
            return inv
        inv.status = "void"
        inv.voided_at = now()
        inv.notes = (inv.notes + "\n作废原因：" + str(reason or "未填写"))[:2000]
        inv.save(update_fields=["status", "voided_at", "notes", "updated_at"])
        # 释放用量：作废票不能继续占用用量，否则重新开票时这些用量再也收不到钱
        UsageRecord.objects.filter(invoice=inv).update(invoiced=False, invoice=None)
        emit_event(inv.owner, "invoice.voided", inv, {"reason": str(reason or "")},
                   idempotency_key=f"invoice:{inv.pk}:voided")
    return inv


def invoice_pdf_metadata(invoice):
    """PDF 元数据（不生成真实文件）：给前端打印/存档用的结构化快照。"""
    lines = []
    for line in invoice.lines.all():
        lines.append({
            "type": line.line_type,
            "description": line.description,
            "quantity": unit_str(line.quantity),
            "unit_amount": unit_str(line.unit_amount),
            "amount": money_str(line.amount),
        })
    customer = invoice.customer
    return {
        "invoice_number": invoice.number,
        "status": invoice.status,
        "currency": invoice.currency,
        "issue_date": invoice.created_at.date() if invoice.created_at else None,
        "due_date": invoice.due_date,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "seller": {"name": "平台订阅计费", "tax_id": "SIMULATED"},
        "buyer": {
            "name": customer.name,
            "email": customer.email,
            "tax_id": customer.tax_id,
            "address": customer.address,
            "country": customer.country,
        },
        "lines": lines,
        "totals": {
            "subtotal": money_str(invoice.subtotal),
            "discount": money_str(invoice.discount_total),
            "tax": money_str(invoice.tax_total),
            "total": money_str(invoice.total),
            "paid": money_str(invoice.amount_paid),
            "credit_applied": money_str(invoice.credit_applied),
            "amount_due": money_str(invoice.amount_due),
        },
        "footer": "本文件为系统生成的账单元数据，非税务发票原件。",
        "pdf_ready": False,
    }


def scan_overdue_invoices(actor, at=None):
    """逾期扫描：找出已过期未付清的发票，写事件（按天幂等）并汇总。

    只标记事件不改状态：逾期是事实，催收动作由催收策略决定，扫描器不应
    擅自把发票改成 uncollectible。
    """
    day = at or today()
    qs = visible(Invoice.objects.filter(status="open", due_date__lt=day), actor) \
        .select_related("customer")
    items = []
    total = ZERO
    for inv in qs[:1000]:
        if inv.amount_due <= 0:
            continue
        days_overdue = (day - inv.due_date).days
        total += inv.amount_due
        items.append({
            "invoice_id": inv.pk, "number": inv.number,
            "customer_id": inv.customer_id, "customer": inv.customer.name,
            "currency": inv.currency, "amount_due": inv.amount_due,
            "days_overdue": days_overdue, "due_date": inv.due_date,
        })
        emit_event(inv.owner, "invoice.overdue", inv, {
            "days_overdue": days_overdue, "amount_due": str(inv.amount_due),
        }, idempotency_key=f"invoice:{inv.pk}:overdue:{day.isoformat()}")
    items.sort(key=lambda row: row["days_overdue"], reverse=True)
    return {"count": len(items), "total_due": quantize_money(total), "items": items,
            "scanned_at": day}


# ===========================================================================
# 8. 支付：登记、捕获、重试、退款、余额与信用额度
# ===========================================================================


def gateway_reference(prefix="SIM"):
    """模拟网关流水号：SIM-时间戳-随机串。

    真实接入时这里换成渠道返回的 id；当前实现不联网，但流水号形态与真实
    渠道一致，前端/测试都按「一串不透明字符」处理。
    """
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"{prefix}-{now().strftime('%Y%m%d%H%M%S')}-{suffix}"


def credit_available(customer):
    """客户可用信用 = 余额 + 信用额度（未结应收另行从额度中扣减展示）。"""
    return quantize_money((customer.balance or ZERO) + (customer.credit_limit or ZERO))


def outstanding_total(customer):
    """客户未结应收合计（open 发票的 amount_due）。"""
    total = ZERO
    qs = Invoice.objects.filter(customer=customer, status="open")
    for inv in qs.only("total", "amount_paid", "credit_applied"):
        total += inv.amount_due
    return quantize_money(total)


def _apply_payment_to_invoice(invoice, amount):
    """把一笔成功收款落到发票上，返回 (实际抵扣, 溢出到余额的部分)。

    溢出部分进客户余额而不是丢弃：企业客户常按整数金额付款（1000 付 990.5 的
    账单），多出的钱必须成为下期抵扣，否则财务对不上。
    """
    due = invoice.amount_due
    applied = min_money(amount, due) if due > 0 else ZERO
    invoice.amount_paid = quantize_money((invoice.amount_paid or ZERO) + applied)
    if invoice.amount_due <= 0 and invoice.total > 0:
        invoice.status = "paid"
        invoice.paid_at = now()
    invoice.save(update_fields=["amount_paid", "status", "paid_at", "updated_at"])
    return applied, quantize_money(to_decimal(amount) - applied)


def create_payment(actor, invoice, amount=None, method="card", auto_capture=True,
                   metadata=None):
    """登记一笔支付：默认即时模拟成功，auto_capture=False 可保留 pending。

    credit 方式直接用客户余额/信用额度结算，不经过网关；其余方式生成
    pending 记录与网关流水号，由捕获动作决定最终状态。
    """
    with transaction.atomic():
        inv = Invoice.objects.select_for_update().select_related("customer") \
            .filter(pk=invoice.pk).first()
        if inv is None:
            raise ValueError("发票不存在")
        ensure_writable(inv, actor)
        if inv.status == "void":
            raise ValueError("已作废发票不能收款")
        if inv.status not in ("open", "draft"):
            raise ValueError(f"当前发票状态 {inv.status} 不能收款")
        if inv.status == "draft":
            # 草稿尚未对外发送，先发送再收款，保证客户手里有票
            raise ValueError("发票尚未发送，请先发送后再收款")
        due = inv.amount_due
        if due <= 0:
            raise ValueError("该发票已结清")
        pay_amount = quantize_money(to_decimal(amount, "支付金额")) if amount is not None else due
        if pay_amount <= 0:
            raise ValueError("支付金额必须大于 0")
        method = str(method or "card")
        if method not in ("card", "bank_transfer", "alipay", "wechat", "manual", "credit"):
            raise ValueError(f"不支持的支付方式: {method}")
        customer = inv.customer
        payment = Payment.objects.create(
            owner=actor,
            invoice=inv,
            customer=customer,
            amount=pay_amount,
            currency=inv.currency,
            method=method,
            status="pending",
            gateway_ref=gateway_reference("CREDIT" if method == "credit" else "SIM"),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        if method == "credit":
            available = credit_available(customer)
            if available < pay_amount:
                raise ValueError(f"可用信用不足（可用 {available}，需要 {pay_amount}）")
            customer.balance = quantize_money((customer.balance or ZERO) - pay_amount)
            customer.save(update_fields=["balance", "updated_at"])
            _settle_payment(payment, inv, actor)
        elif auto_capture:
            capture_payment(actor, payment)
    return payment


def _settle_payment(payment, invoice, actor):
    """把 pending 支付结算为成功（捕获/余额支付共用）。"""
    applied, excess = _apply_payment_to_invoice(invoice, payment.amount)
    if excess > 0:
        customer = invoice.customer
        customer.balance = quantize_money((customer.balance or ZERO) + excess)
        customer.save(update_fields=["balance", "updated_at"])
    payment.status = "succeeded"
    payment.paid_at = now()
    payment.failure_reason = ""
    payment.metadata = {**(payment.metadata or {}), "applied": str(applied),
                        "excess_to_balance": str(excess)}
    payment.save(update_fields=["status", "paid_at", "failure_reason", "metadata", "updated_at"])
    emit_event(payment.owner, "payment.succeeded", payment, {
        "invoice_id": invoice.pk, "amount": str(payment.amount),
        "applied": str(applied), "excess": str(excess),
        "gateway_ref": payment.gateway_ref,
    }, idempotency_key=f"payment:{payment.pk}:succeeded")
    return payment


def capture_payment(actor, payment, at=None):
    """捕获支付：pending → succeeded / failed（状态模拟）。

    失败不抛异常而是返回 failed 记录：支付失败是业务结果，调用方需要拿到
    失败原因做重试/提示，而不是把它当成 500 类错误。
    """
    with transaction.atomic():
        pay = Payment.objects.select_for_update().select_related("invoice", "customer") \
            .filter(pk=payment.pk).first()
        if pay is None:
            raise ValueError("支付记录不存在")
        ensure_writable(pay, actor)
        if pay.status == "succeeded":
            return pay
        if pay.status == "refunded":
            raise ValueError("已退款支付不能再次捕获")
        if pay.status != "pending":
            raise ValueError(f"当前支付状态 {pay.status} 不能捕获")
        if (pay.metadata or {}).get("simulate_failure"):
            pay.status = "failed"
            pay.failure_reason = str((pay.metadata or {}).get("failure_reason")
                                     or "模拟网关拒绝（余额不足/风控拦截）")[:200]
            pay.save(update_fields=["status", "failure_reason", "updated_at"])
            emit_event(pay.owner, "payment.failed", pay, {
                "reason": pay.failure_reason, "gateway_ref": pay.gateway_ref,
            }, idempotency_key=f"payment:{pay.pk}:failed")
            return pay
        invoice = pay.invoice
        if invoice is None:
            # 无发票的充值：直接进余额
            customer = pay.customer
            customer.balance = quantize_money((customer.balance or ZERO) + pay.amount)
            customer.save(update_fields=["balance", "updated_at"])
            pay.status = "succeeded"
            pay.paid_at = now()
            pay.save(update_fields=["status", "paid_at", "updated_at"])
            emit_event(pay.owner, "payment.succeeded", pay, {
                "topup": True, "amount": str(pay.amount),
            }, idempotency_key=f"payment:{pay.pk}:succeeded")
            return pay
        if invoice.status == "void":
            raise ValueError("发票已作废，不能收款")
        _settle_payment(pay, invoice, actor)
    return pay


def retry_payment(actor, payment):
    """重试失败支付：重置为 pending、尝试次数 +1、换新流水号后重新捕获。"""
    with transaction.atomic():
        pay = Payment.objects.select_for_update().filter(pk=payment.pk).first()
        if pay is None:
            raise ValueError("支付记录不存在")
        ensure_writable(pay, actor)
        if pay.status == "succeeded":
            raise ValueError("支付已成功，无需重试")
        if pay.status == "refunded":
            raise ValueError("已退款支付不能重试")
        pay.status = "pending"
        pay.attempts = int(pay.attempts or 0) + 1
        pay.gateway_ref = gateway_reference("SIM")
        pay.failure_reason = ""
        # 重试时清掉模拟失败标记，让「先失败后重试成功」的链路可测试
        meta = dict(pay.metadata or {})
        meta.pop("simulate_failure", None)
        pay.metadata = meta
        pay.save(update_fields=["status", "attempts", "gateway_ref",
                                "failure_reason", "metadata", "updated_at"])
    return capture_payment(actor, pay)


def refund_payment(actor, payment, amount=None, reason=""):
    """退款：支持部分退款，同步冲减发票已付金额与客户余额。

    已支付发票退款后重新回到 open（还欠款），这样逾期扫描/催收能接上；
    多付部分的退款从余额扣回，避免重复退款。
    """
    with transaction.atomic():
        pay = Payment.objects.select_for_update().select_related("invoice", "customer") \
            .filter(pk=payment.pk).first()
        if pay is None:
            raise ValueError("支付记录不存在")
        ensure_writable(pay, actor)
        if pay.status != "succeeded":
            raise ValueError("只有成功的支付可以退款")
        refunded_before = to_decimal((pay.metadata or {}).get("refunded_total", 0))
        remaining = quantize_money(to_decimal(pay.amount) - refunded_before)
        if remaining <= 0:
            raise ValueError("该支付已全额退款")
        refund_amount = quantize_money(to_decimal(amount, "退款金额")) if amount is not None else remaining
        if refund_amount <= 0:
            raise ValueError("退款金额必须大于 0")
        if refund_amount > remaining:
            raise ValueError(f"退款金额超过可退余额 {remaining}")
        invoice = pay.invoice
        applied_back = ZERO
        if invoice is not None:
            applied_back = min_money(refund_amount, invoice.amount_paid or ZERO)
            invoice.amount_paid = quantize_money((invoice.amount_paid or ZERO) - applied_back)
            if invoice.status == "paid" and invoice.amount_due > 0:
                invoice.status = "open"
                invoice.paid_at = None
            invoice.save(update_fields=["amount_paid", "status", "paid_at", "updated_at"])
        excess = quantize_money(refund_amount - applied_back)
        if excess > 0:
            customer = pay.customer
            customer.balance = quantize_money((customer.balance or ZERO) - excess)
            customer.save(update_fields=["balance", "updated_at"])
        total_refunded = quantize_money(refunded_before + refund_amount)
        meta = dict(pay.metadata or {})
        meta["refunded_total"] = str(total_refunded)
        meta.setdefault("refunds", []).append({
            "amount": str(refund_amount), "reason": str(reason or ""),
            "at": now().isoformat(),
        })
        pay.metadata = meta
        pay.failure_reason = ""
        if total_refunded >= to_decimal(pay.amount):
            pay.status = "refunded"
        pay.save(update_fields=["status", "failure_reason", "metadata", "updated_at"])
        emit_event(pay.owner, "payment.refunded", pay, {
            "amount": str(refund_amount), "invoice_id": invoice.pk if invoice else None,
            "reason": str(reason or ""), "total_refunded": str(total_refunded),
        }, idempotency_key=f"payment:{pay.pk}:refund:{total_refunded}")
    return pay


def mark_invoice_paid(actor, invoice, amount=None, method="manual"):
    """人工登记收款：生成一条成功支付并结清发票（财务线下收款场景）。"""
    payment = create_payment(actor, invoice, amount=amount, method=method,
                             auto_capture=True)
    invoice.refresh_from_db()
    return invoice, payment


def topup_balance(actor, customer, amount, method="bank_transfer", auto_capture=True,
                  metadata=None):
    """账户充值（无发票支付）：成功后直接增加客户余额。

    充值与收款共用 Payment 表，invoice 为空即可区分；这样对账时「所有钱」
    只有一张流水表，不会出现两套收款记录。
    """
    value = quantize_money(to_decimal(amount, "充值金额"))
    if value <= 0:
        raise ValueError("充值金额必须大于 0")
    if customer.status != "active":
        raise ValueError("客户已归档，不能充值")
    method = str(method or "bank_transfer")
    if method == "credit":
        raise ValueError("充值不能使用账户余额支付")
    with transaction.atomic():
        payment = Payment.objects.create(
            owner=actor,
            invoice=None,
            customer=customer,
            amount=value,
            currency=customer.currency or DEFAULT_CURRENCY,
            method=method,
            status="pending",
            gateway_ref=gateway_reference("TOPUP"),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        if auto_capture:
            capture_payment(actor, payment)
    return payment


def create_credit_note(actor, customer, amount, reason="", invoice=None, currency=None):
    """开信用票据（红字），金额必须大于 0 且币种与客户一致。"""
    value = quantize_money(to_decimal(amount, "票据金额"))
    if value <= 0:
        raise ValueError("票据金额必须大于 0")
    if invoice is not None and invoice.customer_id != customer.pk:
        raise ValueError("票据关联的发票不属于该客户")
    with transaction.atomic():
        note = CreditNote.objects.create(
            owner=actor,
            number=next_credit_note_number(actor),
            customer=customer,
            invoice=invoice,
            amount=value,
            currency=(currency or customer.currency or DEFAULT_CURRENCY),
            reason=str(reason or "")[:2000],
            status="open",
        )
        emit_event(customer.owner if customer.owner_id else actor,
                   "credit_note.created", note,
                   {"customer_id": customer.pk, "amount": str(value)},
                   idempotency_key=f"credit_note:{note.pk}:created")
    return note


def apply_credit_note(actor, note, invoice=None):
    """核销信用票据：优先冲抵指定/关联发票，剩余进客户余额。"""
    with transaction.atomic():
        obj = CreditNote.objects.select_for_update().select_related("customer", "invoice") \
            .filter(pk=note.pk).first()
        if obj is None:
            raise ValueError("信用票据不存在")
        ensure_writable(obj, actor)
        if obj.status != "open":
            raise ValueError(f"当前票据状态 {obj.status} 不能核销")
        target = invoice or obj.invoice
        applied = ZERO
        if target is not None:
            if target.customer_id != obj.customer_id:
                raise ValueError("目标发票不属于票据客户")
            due = target.amount_due
            if due > 0:
                applied = min_money(obj.amount, due)
                target.credit_applied = quantize_money((target.credit_applied or ZERO) + applied)
                if target.amount_due <= 0 and target.total > 0:
                    target.status = "paid"
                    target.paid_at = now()
                target.save(update_fields=["credit_applied", "status", "paid_at", "updated_at"])
        remaining = quantize_money(obj.amount - applied)
        if remaining > 0:
            customer = obj.customer
            customer.balance = quantize_money((customer.balance or ZERO) + remaining)
            customer.save(update_fields=["balance", "updated_at"])
        obj.status = "applied"
        obj.applied_at = now()
        obj.invoice = target
        obj.save(update_fields=["status", "applied_at", "invoice", "updated_at"])
        emit_event(obj.owner, "credit_note.applied", obj, {
            "applied": str(applied), "to_balance": str(remaining),
            "invoice_id": target.pk if target else None,
        }, idempotency_key=f"credit_note:{obj.pk}:applied")
    return {"credit_note": obj, "applied": applied, "to_balance": remaining}

# ===========================================================================
# 9. 优惠券：校验、折扣计算、核销
# ===========================================================================


def coupon_discount(coupon, amount):
    """计算优惠券在给定金额上的减免额（不超过金额本身）。

    百分比券按金额算；固定券按面额，但不能把账单打成负数——多余面额
    不结转（客户理解成本高，也容易被刷），不足部分由客户继续支付。
    """
    base = to_decimal(amount, "金额", minimum=0)
    if base <= 0:
        return quantize_money(0)
    if coupon.coupon_type == "percent":
        value = percent_amount(base, coupon.percent)
    else:
        value = quantize_money(coupon.amount)
    if value > base:
        value = base
    return quantize_money(value)


def assert_coupon_usable(coupon, customer, amount=ZERO, at=None, require_discount=False):
    """校验券是否可用（有效期/上限/客户限制/一次性），不可用抛中文错误。

    单独抽出来是因为「校验接口」和「核销」必须用同一套规则；两边各写一份
    必然出现「校验通过但核销失败」的割裂体验。
    """
    at = at or now()
    if coupon.status != "active":
        raise ValueError("优惠券已停用")
    if coupon.valid_from and at < coupon.valid_from:
        raise ValueError("优惠券尚未生效")
    if coupon.valid_until and at > coupon.valid_until:
        raise ValueError("优惠券已过期")
    if coupon.max_redemptions and coupon.redeemed_count >= coupon.max_redemptions:
        raise ValueError("优惠券已达最大核销次数")
    if coupon.customer_id:
        if customer is None or coupon.customer_id != customer.pk:
            raise ValueError("该优惠券仅限指定客户使用")
    if coupon.duration == "once" and customer is not None:
        used = CouponRedemption.objects.filter(coupon=coupon, customer=customer).exists()
        if used:
            raise ValueError("该客户已使用过此优惠券")
    discount = coupon_discount(coupon, amount)
    if require_discount and discount <= 0:
        raise ValueError("优惠券未产生有效抵扣")
    return discount


def validate_coupon(code, customer, amount=ZERO, subscription=None, at=None, user=None):
    """校验优惠码并返回可用性与抵扣金额（只读，不核销）。"""
    coupon = find_coupon(code, user)
    if coupon is None:
        raise ValueError("优惠券不存在")
    base = to_decimal(amount or 0, "金额", minimum=0)
    discount = assert_coupon_usable(coupon, customer, base, at=at)
    if subscription is not None and coupon.currency and subscription.currency \
            and coupon.currency != subscription.currency:
        raise ValueError("优惠券币种与订阅币种不一致")
    return {
        "coupon_id": coupon.pk,
        "code": coupon.code,
        "name": coupon.name,
        "valid": True,
        "coupon_type": coupon.coupon_type,
        "percent": coupon.percent,
        "amount": coupon.amount,
        "currency": coupon.currency,
        "duration": coupon.duration,
        "duration_months": coupon.duration_months,
        "base_amount": base,
        "discount": discount,
        "remaining": coupon.remaining,
    }


def redeem_coupon(actor, coupon, customer, subscription=None, amount=ZERO,
                  idempotency_key=""):
    """核销优惠券：锁券 → 复核规则 → 记核销 → 计数 +1。

    幂等键命中时返回既有核销记录，不再重复计数；并发核销由 select_for_update
    串行化，避免「最后一张券被两个请求同时用掉」。
    """
    key = str(idempotency_key or "").strip()[:120]
    base = to_decimal(amount or 0, "金额", minimum=0)
    with transaction.atomic():
        obj = Coupon.objects.select_for_update().filter(pk=coupon.pk).first()
        if obj is None:
            raise ValueError("优惠券不存在")
        if key:
            existing = CouponRedemption.objects.filter(owner=obj.owner_id,
                                                       idempotency_key=key).first()
            if existing is not None:
                return existing
        discount = assert_coupon_usable(obj, customer, base, require_discount=True)
        redemption = CouponRedemption.objects.create(
            owner=obj.owner,
            coupon=obj,
            customer=customer,
            subscription=subscription,
            amount=discount,
            currency=obj.currency,
            idempotency_key=key,
            metadata={"base_amount": str(base), "duration": obj.duration},
        )
        obj.redeemed_count = int(obj.redeemed_count or 0) + 1
        obj.save(update_fields=["redeemed_count", "updated_at"])
        emit_event(obj.owner, "coupon.redeemed", redemption, {
            "coupon": obj.code, "customer_id": customer.pk,
            "discount": str(discount), "base_amount": str(base),
        }, idempotency_key=f"coupon_redemption:{redemption.pk}:created")
    return redemption


# ===========================================================================
# 10. 催收：策略、状态机、幂等扫描
# ===========================================================================


def default_dunning_policy(user=None):
    """取默认催收策略：优先可见范围内最早创建的一条 active 策略。"""
    qs = DunningPolicy.objects.filter(status="active")
    if user is not None:
        qs = visible(qs, user)
    return qs.order_by("id").first()


def start_dunning(actor, subscription, policy=None, reason=""):
    """对逾期订阅启动催收：标记 past_due，创建 run 并把下次执行排到第一步。

    同一订阅只允许一个进行中的 run（幂等）：重复调用返回既有 run，
    避免财务重复点击导致同一步骤被执行两次。
    """
    at = now()
    with transaction.atomic():
        sub = _lock_subscription(subscription)
        if sub.status == "canceled":
            raise ValueError("订阅已取消，无需催收")
        existing = DunningRun.objects.filter(subscription=sub, status="running") \
            .order_by("-id").first()
        if existing is not None:
            return existing
        policy = policy or default_dunning_policy(actor)
        if policy is None:
            raise ValueError("没有可用的催收策略，请先创建并配置步骤")
        steps = list(policy.steps.order_by("sequence"))
        if not steps:
            raise ValueError("催收策略没有配置步骤")
        if sub.status in ("active", "trialing"):
            sub.status = "past_due"
            sub.save(update_fields=["status", "updated_at"])
        first = steps[0]
        run = DunningRun.objects.create(
            owner=sub.owner,
            subscription=sub,
            policy=policy,
            status="running",
            current_step=0,
            started_at=at,
            next_retry_at=at + timedelta(days=max(first.delay_days, 0)),
            note=str(reason or "")[:200],
        )
        emit_event(sub.owner, "dunning.started", run, {
            "subscription_id": sub.pk, "policy": policy.code,
            "steps": len(steps), "first_delay_days": first.delay_days,
        }, idempotency_key=f"dunning:{run.pk}:started")
    return run


def _next_dunning_step(run):
    """取下一步（序号大于当前步骤的第一条）。"""
    return run.policy.steps.filter(sequence__gt=run.current_step).order_by("sequence").first()


def advance_dunning(actor, run, at=None, force=False):
    """推进催收状态机一步：notify → suspend → cancel。

    幂等：
    - run 已结束时返回 executed=False，不重复执行动作；
    - 未到 next_retry_at 且未 force 时抛业务错误（前端应展示「未到执行时间」）。
    真正的状态迁移（past_due → paused → canceled）只在这里发生，
    保证「谁在什么时候把服务停了」有唯一入口和审计事件。
    """
    at = at or now()
    with transaction.atomic():
        obj = DunningRun.objects.select_for_update().select_related(
            "subscription", "policy").filter(pk=run.pk).first()
        if obj is None:
            raise ValueError("催收记录不存在")
        ensure_writable(obj, actor)
        if obj.status != "running":
            return {"run": obj, "executed": False, "action": None,
                    "reason": f"催收流程已结束（{obj.status}）"}
        if not force and obj.next_retry_at and obj.next_retry_at > at:
            raise ValueError(f"未到催收执行时间（{obj.next_retry_at.isoformat()}）")
        step = _next_dunning_step(obj)
        if step is None:
            obj.status = "completed"
            obj.completed_at = at
            obj.next_retry_at = None
            obj.save(update_fields=["status", "completed_at", "next_retry_at", "updated_at"])
            return {"run": obj, "executed": False, "action": None,
                    "reason": "没有更多催收步骤"}
        sub = obj.subscription
        action = step.action
        if action == "notify":
            emit_event(obj.owner, "dunning.notify", obj, {
                "subscription_id": sub.pk, "step": step.sequence,
                "delay_days": step.delay_days,
                "message": (step.template or "请尽快结清逾期账单")[:200],
            }, idempotency_key=f"dunning:{obj.pk}:step:{step.sequence}")
        elif action == "suspend":
            if sub.status != "canceled":
                sub.status = "paused"
                sub.paused_at = at
                sub.save(update_fields=["status", "paused_at", "updated_at"])
                emit_event(obj.owner, "dunning.suspend", obj, {
                    "subscription_id": sub.pk, "step": step.sequence,
                }, idempotency_key=f"dunning:{obj.pk}:step:{step.sequence}")
        elif action == "cancel":
            if sub.status != "canceled":
                sub.status = "canceled"
                sub.canceled_at = at
                sub.cancel_reason = "催收超期未付"
                sub.auto_renew = False
                sub.save(update_fields=["status", "canceled_at", "cancel_reason",
                                        "auto_renew", "updated_at"])
                emit_event(obj.owner, "dunning.cancel", obj, {
                    "subscription_id": sub.pk, "step": step.sequence,
                }, idempotency_key=f"dunning:{obj.pk}:step:{step.sequence}")
        obj.current_step = step.sequence
        later = _next_dunning_step(obj)
        if action == "cancel" or later is None:
            obj.status = "completed"
            obj.completed_at = at
            obj.next_retry_at = None
        else:
            # 下次执行按「流程开始时间 + 下一步延迟天数」计算，避免人工提前
            # 推进导致后续步骤被整体前移、失去 D+3/D+7/D+14 的语义。
            obj.next_retry_at = obj.started_at + timedelta(days=max(later.delay_days, 0))
        obj.save(update_fields=["current_step", "next_retry_at", "status",
                                "completed_at", "updated_at"])
    return {"run": obj, "executed": True, "action": action,
            "step": step.sequence, "subscription_status": sub.status}


def due_dunning_runs(actor, at=None):
    """到期应执行的催收流程（running 且 next_retry_at <= now）。"""
    at = at or now()
    qs = DunningRun.objects.filter(status="running", next_retry_at__lte=at) \
        .select_related("subscription", "policy").order_by("next_retry_at", "id")
    return visible(qs, actor)


def run_dunning_scan(actor, at=None):
    """批量推进到期催收（定时任务入口），返回执行明细与失败项。"""
    at = at or now()
    executed = []
    failed = []
    for run in due_dunning_runs(actor, at)[:200]:
        try:
            result = advance_dunning(actor, run, at=at, force=True)
            executed.append({
                "run_id": run.pk, "subscription_id": run.subscription_id,
                "action": result.get("action"),
                "subscription_status": result.get("subscription_status"),
                "executed": result.get("executed"),
            })
        except ValueError as exc:
            failed.append({"run_id": run.pk, "error": str(exc)})
    return {"scanned": len(executed) + len(failed), "executed": len(executed),
            "failed": len(failed), "items": executed, "errors": failed,
            "ran_at": at}


# ===========================================================================
# 11. 指标与账单预测
# ===========================================================================


def live_subscription_qs(user=None, at=None):
    """在服订阅（active/past_due，排除试用与暂停）：MRR/预测的统一口径。"""
    qs = Subscription.objects.filter(status__in=("active", "past_due")) \
        .select_related("plan", "customer").prefetch_related("items__price__plan")
    if user is not None:
        qs = visible(qs, user)
    return qs


def mrr_breakdown(user=None, at=None):
    """MRR：按币种汇总月度经常性收入。

    试用不计入（还没付费），暂停/取消不计入；年付按 /12 摊平，
    一次性收入不算经常性收入。
    """
    totals = {}
    count = 0
    for sub in live_subscription_qs(user, at):
        value = subscription_monthly_value(sub, at)
        currency = sub.currency or DEFAULT_CURRENCY
        totals[currency] = totals.get(currency, ZERO) + value
        count += 1
    by_currency = {k: quantize_money(v) for k, v in totals.items()}
    total = sum_money(by_currency.values())
    return {"mrr": total, "by_currency": by_currency,
            "subscription_count": count, "currency": DEFAULT_CURRENCY}


def arr_breakdown(user=None, at=None):
    """ARR = MRR × 12（按币种分别放大，不做跨币种汇率换算）。"""
    mrr = mrr_breakdown(user, at)
    by_currency = {k: quantize_money(to_decimal(v) * 12)
                   for k, v in mrr["by_currency"].items()}
    return {"arr": sum_money(by_currency.values()), "by_currency": by_currency,
            "mrr": mrr["mrr"], "subscription_count": mrr["subscription_count"]}


def arpu(user=None, at=None):
    """ARPU：每付费客户平均月收入（按币种）。"""
    mrr = mrr_breakdown(user, at)
    qs = live_subscription_qs(user, at)
    customers = {sub.customer_id: sub.currency or DEFAULT_CURRENCY for sub in qs}
    per_currency_customers = {}
    for currency in customers.values():
        per_currency_customers[currency] = per_currency_customers.get(currency, 0) + 1
    by_currency = {}
    for currency, value in mrr["by_currency"].items():
        by_currency[currency] = safe_div(value, per_currency_customers.get(currency, 0), places=2)
    return {
        "arpu": sum_money(by_currency.values()),
        "by_currency": by_currency,
        "customer_count": len(customers),
        "subscription_count": mrr["subscription_count"],
    }


def churn_rate(user=None, days=30, at=None):
    """流失率：窗口内取消数 / 窗口开始时在服数。

    分母用「窗口开始时的在服订阅」而不是当前数，否则分母随取消而缩小，
    流失率会被系统性高估。
    """
    days = max(int(days), 1)
    at_dt = at or now()
    if isinstance(at_dt, date) and not isinstance(at_dt, datetime):
        at_dt = timezone.make_aware(datetime.combine(at_dt, time.min),
                                    timezone.get_current_timezone())
    start = at_dt - timedelta(days=days)
    qs = Subscription.objects.all()
    if user is not None:
        qs = visible(qs, user)
    canceled = qs.filter(status="canceled", canceled_at__gte=start).count()
    base = qs.filter(created_at__lt=start).exclude(
        status="canceled", canceled_at__lt=start).count()
    return {
        "churn_rate": percent_ratio(canceled, base),
        "canceled": canceled,
        "base": base,
        "window_days": days,
        "from": start.isoformat(),
        "to": at_dt.isoformat(),
    }


def trial_conversion(user=None, days=90, at=None):
    """试用转化率：窗口内试用到期且转为付费的比例。

    试用中且尚未到期的不进分母（结果未定），取消/暂停算未转化。
    """
    days = max(int(days), 1)
    at_dt = at or now()
    start = at_dt - timedelta(days=days)
    qs = Subscription.objects.filter(trial_end__isnull=False,
                                     trial_end__gte=start, trial_end__lte=at_dt)
    if user is not None:
        qs = visible(qs, user)
    ended = list(qs)
    converted = [sub for sub in ended if sub.status in ("active", "past_due")]
    return {
        "conversion_rate": percent_ratio(len(converted), len(ended)),
        "trials_ended": len(ended),
        "converted": len(converted),
        "window_days": days,
        "from": start.isoformat(),
        "to": at_dt.isoformat(),
    }


def delinquency(user=None, at=None):
    """逾期率：逾期未结金额 / 全部未结金额（按币种）。"""
    day = at or today()
    if isinstance(day, datetime):
        day = timezone.localtime(day).date() if timezone.is_aware(day) else day.date()
    qs = Invoice.objects.filter(status="open")
    if user is not None:
        qs = visible(qs, user)
    outstanding = ZERO
    overdue = ZERO
    overdue_count = 0
    open_count = 0
    by_currency = {}
    for inv in qs.only("total", "amount_paid", "credit_applied", "due_date", "currency"):
        due = inv.amount_due
        if due <= 0:
            continue
        open_count += 1
        currency = inv.currency or DEFAULT_CURRENCY
        bucket = by_currency.setdefault(currency, {"outstanding": ZERO, "overdue": ZERO})
        bucket["outstanding"] += due
        outstanding += due
        if inv.due_date and inv.due_date < day:
            bucket["overdue"] += due
            overdue += due
            overdue_count += 1
    for bucket in by_currency.values():
        bucket["outstanding"] = quantize_money(bucket["outstanding"])
        bucket["overdue"] = quantize_money(bucket["overdue"])
        bucket["rate"] = percent_ratio(bucket["overdue"], bucket["outstanding"])
    return {
        "delinquency_rate": percent_ratio(overdue, outstanding),
        "outstanding": quantize_money(outstanding),
        "overdue": quantize_money(overdue),
        "open_invoices": open_count,
        "overdue_invoices": overdue_count,
        "by_currency": by_currency,
    }


def revenue_trend(user=None, months=12, at=None):
    """收入趋势：最近 N 个自然月的已收款合计（按 paid_at 归月）。"""
    months = min(max(int(months), 1), 36)
    ranges = month_range_back(months, at)
    if not ranges:
        return {"months": 0, "items": [], "total": quantize_money(0)}
    begin = ranges[0][0]
    end = ranges[-1][1]
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(begin, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(end, time.min), tz)
    qs = Invoice.objects.filter(status="paid", paid_at__gte=start_dt, paid_at__lt=end_dt)
    if user is not None:
        qs = visible(qs, user)
    buckets = {}
    for start, _end in ranges:
        buckets[month_key(start)] = {"month": month_key(start), "revenue": ZERO,
                                     "invoices": 0, "currency": DEFAULT_CURRENCY}
    for inv in qs.only("total", "paid_at"):
        key = month_key(inv.paid_at)
        if key in buckets:
            buckets[key]["revenue"] += inv.total
            buckets[key]["invoices"] += 1
    items = []
    total = ZERO
    for key in sorted(buckets):
        row = buckets[key]
        row["revenue"] = quantize_money(row["revenue"])
        total += row["revenue"]
        items.append(row)
    return {"months": months, "items": items, "total": quantize_money(total),
            "from": begin, "to": end}


def plan_distribution(user=None, at=None):
    """按计划分布：在服订阅数、MRR 与占比，用于收入结构分析。"""
    rows = {}
    total_mrr = ZERO
    for sub in live_subscription_qs(user, at):
        plan = sub.plan
        row = rows.setdefault(plan.pk, {
            "plan_id": plan.pk, "plan": plan.code, "name": plan.name,
            "billing_period": plan.billing_period,
            "subscriptions": 0, "mrr": ZERO,
        })
        value = subscription_monthly_value(sub, at)
        row["subscriptions"] += 1
        row["mrr"] += value
        total_mrr += value
    items = []
    for row in rows.values():
        row["mrr"] = quantize_money(row["mrr"])
        row["share"] = percent_ratio(row["mrr"], total_mrr)
        items.append(row)
    items.sort(key=lambda item: item["mrr"], reverse=True)
    return {"items": items, "count": len(items), "total_mrr": quantize_money(total_mrr)}


def usage_estimate_monthly(subscription, at=None):
    """近 90 天用量的月度平均费用（账单预测的用量部分）。"""
    at = at or today()
    if isinstance(at, datetime):
        at = timezone.localtime(at).date() if timezone.is_aware(at) else at.date()
    begin = at - timedelta(days=90)
    total = ZERO
    meter_ids = list(UsageRecord.objects.filter(
        subscription=subscription, occurred_at__gte=timezone.make_aware(
            datetime.combine(begin, time.min), timezone.get_current_timezone())
    ).values_list("meter_id", flat=True).distinct())
    if not meter_ids:
        return quantize_money(0)
    for meter_id in meter_ids:
        meter = Meter.objects.filter(pk=meter_id).first()
        if meter is None:
            continue
        qs = UsageRecord.objects.filter(
            subscription=subscription, meter=meter,
            occurred_at__gte=timezone.make_aware(
                datetime.combine(begin, time.min), timezone.get_current_timezone()))
        qty = aggregate_quantity(qs, meter.aggregation)
        monthly_qty = qty / Decimal(3)
        total += usage_charge(subscription, meter, monthly_qty)["amount"]
    return quantize_money(total)


def forecast_next_period(user=None, at=None):
    """账单预测：下一个 30 天的预计收入 = 固定费月摊 + 用量月均。

    用量按近 90 天均值估算，而不是按当前账期已用量外推：月初外推会严重
    低估（月初用量天然少），90 天窗口能平滑周内/月内波动。
    """
    at_date = at or today()
    if isinstance(at_date, datetime):
        at_date = timezone.localtime(at_date).date() if timezone.is_aware(at_date) else at_date.date()
    items = []
    by_currency = {}
    for sub in live_subscription_qs(user, at_date):
        fixed = monthly_value(subscription_period_amount(sub, at_date),
                              sub.plan.billing_period)
        usage = usage_estimate_monthly(sub, at_date)
        forecast = quantize_money(fixed + usage)
        currency = sub.currency or DEFAULT_CURRENCY
        by_currency[currency] = by_currency.get(currency, ZERO) + forecast
        items.append({
            "subscription_id": sub.pk,
            "customer_id": sub.customer_id,
            "customer": sub.customer.name if sub.customer_id else "",
            "plan": sub.plan.code,
            "currency": currency,
            "fixed": fixed,
            "usage": usage,
            "forecast": forecast,
        })
    items.sort(key=lambda row: row["forecast"], reverse=True)
    return {
        "horizon_days": 30,
        "as_of": at_date,
        "by_currency": {k: quantize_money(v) for k, v in by_currency.items()},
        "total": sum_money(by_currency.values()),
        "items": items[:200],
        "count": len(items),
    }


def overview(user=None, at=None):
    """计费总览：把常用指标收口成一个接口，减少前端首屏串行请求。"""
    mrr = mrr_breakdown(user, at)
    subs = Subscription.objects.all()
    invoices = Invoice.objects.all()
    customers = Customer.objects.all()
    if user is not None:
        subs = visible(subs, user)
        invoices = visible(invoices, user)
        customers = visible(customers, user)
    by_status = {}
    for row in subs.values("status").annotate(c=Count("id")):
        by_status[row["status"]] = row["c"]
    invoice_status = {}
    for row in invoices.values("status").annotate(c=Count("id")):
        invoice_status[row["status"]] = row["c"]
    return {
        "customers": customers.count(),
        "subscriptions": subs.count(),
        "subscriptions_by_status": by_status,
        "invoices_by_status": invoice_status,
        "mrr": mrr["mrr"],
        "mrr_by_currency": mrr["by_currency"],
        "arr": quantize_money(to_decimal(mrr["mrr"]) * 12),
        "delinquency_rate": delinquency(user, at)["delinquency_rate"],
        "trial_conversion_rate": trial_conversion(user, at=at)["conversion_rate"],
        "churn_rate": churn_rate(user, at=at)["churn_rate"],
    }


# ===========================================================================
# 12. 事件与通用工具
# ===========================================================================


def emit_event(owner, event_type, obj=None, payload=None, idempotency_key="",
               status="processed", error=""):
    """写计费事件（审计轨迹）；幂等键重复时返回既有事件。

    事件与业务写在同一事务：业务回滚则事件一起回滚，不会出现「有事件没账」
    或「有账没事件」。调用方只需保证 key 的语义唯一（如 invoice:{pk}:generated）。
    """
    key = str(idempotency_key or "").strip()[:160]
    owner_obj = owner
    if owner_obj is None:
        raise ValueError("事件缺少 owner")
    object_type = obj.__class__.__name__ if obj is not None else ""
    object_id = getattr(obj, "pk", None) if obj is not None else None
    body = payload if isinstance(payload, dict) else {}
    if key:
        existing = BillingEvent.objects.filter(owner=owner_obj, idempotency_key=key).first()
        if existing is not None:
            return existing
    return BillingEvent.objects.create(
        owner=owner_obj,
        event_type=str(event_type)[:60],
        object_type=object_type[:40],
        object_id=object_id,
        payload=body,
        idempotency_key=key,
        status=status,
        processed_at=now() if status == "processed" else None,
        error=str(error or "")[:300],
    )


def events_for(obj, limit=50):
    """取某个对象的事件时间线（详情页用）。"""
    if obj is None:
        return []
    return list(BillingEvent.objects.filter(
        object_type=obj.__class__.__name__, object_id=obj.pk,
    ).order_by("-created_at", "-id")[:limit])


def plan_usage_stats(plan, user=None):
    """计划的售卖概况：订阅数、活跃数、MRR（计划详情页用）。"""
    qs = Subscription.objects.filter(plan=plan)
    if user is not None:
        qs = visible(qs, user)
    active = qs.filter(status__in=("active", "past_due"))
    mrr = sum_money([subscription_monthly_value(sub) for sub in
                     active.select_related("plan").prefetch_related("items__price__plan")])
    return {"plan_id": plan.pk, "subscriptions": qs.count(),
            "active_subscriptions": active.count(), "mrr": mrr}


def customer_snapshot(customer, user=None):
    """客户概览：订阅、账单、余额、可用信用、近期发票（详情页一次取全）。"""
    subs = customer.subscriptions.select_related("plan").all()
    invoices = customer.invoices.all()
    open_invoices = [inv for inv in invoices if inv.status == "open"]
    outstanding = sum_money([inv.amount_due for inv in open_invoices])
    paid_total = sum_money([inv.total for inv in invoices if inv.status == "paid"])
    mrr = sum_money([subscription_monthly_value(sub) for sub in subs
                     if sub.status in ("active", "past_due")])
    return {
        "customer_id": customer.pk,
        "name": customer.name,
        "currency": customer.currency,
        "balance": quantize_money(customer.balance),
        "credit_limit": quantize_money(customer.credit_limit),
        "credit_available": credit_available(customer),
        "outstanding": outstanding,
        "paid_total": paid_total,
        "mrr": mrr,
        "subscription_count": len(list(subs)),
        "active_subscriptions": sum(1 for sub in subs if sub.is_live),
        "open_invoices": len(open_invoices),
        "overdue_invoices": sum(1 for inv in open_invoices if inv.is_overdue),
        "subscriptions": [
            {"id": sub.pk, "plan": sub.plan.code, "status": sub.status,
             "current_period_start": sub.current_period_start,
             "current_period_end": sub.current_period_end,
             "seats": sub.seats, "currency": sub.currency}
            for sub in subs.order_by("-id")[:20]
        ],
        "recent_invoices": [
            {"id": inv.pk, "number": inv.number, "status": inv.status,
             "total": inv.total, "amount_due": inv.amount_due,
             "currency": inv.currency, "due_date": inv.due_date}
            for inv in invoices.order_by("-id")[:10]
        ],
        "events": [
            {"id": ev.pk, "event_type": ev.event_type, "status": ev.status,
             "payload": ev.payload, "created_at": ev.created_at}
            for ev in events_for(customer, limit=20)
        ],
    }

