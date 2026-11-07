# -*- coding: utf-8 -*-
"""订阅计费 · 统计指标接口（10 个）。

指标只读，不写库；全部走 services 的聚合函数，保证列表接口、详情页与
统计页对「什么算在服/什么算收入」口径一致。金额一律字符串输出。

路由（挂在 /api/billing/stats/ 下）：
    GET mrr/               月度经常性收入（按币种）
    GET arr/               年度经常性收入（MRR × 12）
    GET arpu/              每付费客户平均月收入
    GET churn/             流失率（窗口可配）
    GET trial-conversion/  试用转化率
    GET delinquency/       逾期率与逾期金额
    GET revenue-trend/     近 N 个自然月收入趋势
    GET plan-distribution/ 按计划分布（订阅数/MRR/占比）
    GET forecast/          下一账期收入预测
    GET overview/          计费总览（首屏聚合）
"""
from devtools.common import endpoint, ok, opt_num, opt_str

from billing import serializers, services
from billing.views_common import date_param, datetime_param, int_param


def _money_map(values):
    """币种 → 金额字符串（拒绝把 Decimal 直接塞进 JSON）。"""
    return {key: serializers.money(value) for key, value in (values or {}).items()}


def _window_days(request, default=30, maximum=366):
    """窗口天数参数：默认 30，1..366。"""
    return int(opt_num(request, "days", default, integer=True,
                       minimum=1, maximum=maximum) or default)


def _as_of(request):
    """统计基准时间：默认当前时间，允许回放历史。

    回放参数用 at（ISO 时间）；只给日期时按当天零点处理，便于报表按日对齐。
    """
    value = opt_str(request, "at").strip()
    if not value:
        return None
    return datetime_param(request, "at")


@endpoint(("GET",))
def stats_mrr(request):
    """MRR：月度经常性收入（按币种汇总，试用/暂停/取消不计入）。"""
    at = _as_of(request)
    data = services.mrr_breakdown(request.user, at)
    mrr = services.to_decimal(data["mrr"])
    return ok({
        "mrr": serializers.money(mrr),
        "arr": serializers.money(services.quantize_money(mrr * 12)),
        "by_currency": _money_map(data["by_currency"]),
        "subscription_count": data["subscription_count"],
        "currency": data["currency"],
        "as_of": serializers.iso(at or services.now()),
    })


@endpoint(("GET",))
def stats_arr(request):
    """ARR：年度经常性收入（MRR × 12，按币种分别放大）。"""
    at = _as_of(request)
    data = services.arr_breakdown(request.user, at)
    return ok({
        "arr": serializers.money(data["arr"]),
        "mrr": serializers.money(data["mrr"]),
        "by_currency": _money_map(data["by_currency"]),
        "subscription_count": data["subscription_count"],
        "as_of": serializers.iso(at or services.now()),
    })


@endpoint(("GET",))
def stats_arpu(request):
    """ARPU：每付费客户平均月收入（按币种）。"""
    at = _as_of(request)
    data = services.arpu(request.user, at)
    return ok({
        "arpu": serializers.money(data["arpu"]),
        "by_currency": _money_map(data["by_currency"]),
        "customer_count": data["customer_count"],
        "subscription_count": data["subscription_count"],
    })


@endpoint(("GET",))
def stats_churn(request):
    """流失率：窗口内取消数 ÷ 窗口开始时在服数（days 默认 30）。"""
    days = _window_days(request, 30)
    at = _as_of(request)
    data = services.churn_rate(request.user, days=days, at=at)
    return ok({
        "churn_rate": data["churn_rate"],
        "canceled": data["canceled"],
        "base": data["base"],
        "window_days": data["window_days"],
        "from": serializers.iso(data["from"]),
        "to": serializers.iso(data["to"]),
    })


@endpoint(("GET",))
def stats_trial_conversion(request):
    """试用转化率：窗口内到期试用中转为付费的比例（days 默认 90）。"""
    days = _window_days(request, 90, maximum=730)
    at = _as_of(request)
    data = services.trial_conversion(request.user, days=days, at=at)
    return ok({
        "conversion_rate": data["conversion_rate"],
        "trials_ended": data["trials_ended"],
        "converted": data["converted"],
        "window_days": data["window_days"],
        "from": serializers.iso(data["from"]),
        "to": serializers.iso(data["to"]),
    })


@endpoint(("GET",))
def stats_delinquency(request):
    """逾期率：逾期未结金额 ÷ 全部未结金额（按币种细分）。"""
    at = date_param(request, "at")
    data = services.delinquency(request.user, at)
    by_currency = {}
    for currency, bucket in (data["by_currency"] or {}).items():
        by_currency[currency] = {
            "outstanding": serializers.money(bucket["outstanding"]),
            "overdue": serializers.money(bucket["overdue"]),
            "rate": bucket["rate"],
        }
    return ok({
        "delinquency_rate": data["delinquency_rate"],
        "outstanding": serializers.money(data["outstanding"]),
        "overdue": serializers.money(data["overdue"]),
        "open_invoices": data["open_invoices"],
        "overdue_invoices": data["overdue_invoices"],
        "by_currency": by_currency,
        "as_of": serializers.iso(at or services.today()),
    })


@endpoint(("GET",))
def stats_revenue_trend(request):
    """收入趋势：最近 N 个自然月的已收款（months 默认 12，上限 36）。"""
    months = int(opt_num(request, "months", 12, integer=True,
                         minimum=1, maximum=36) or 12)
    at = date_param(request, "at")
    data = services.revenue_trend(request.user, months=months, at=at)
    items = [{
        "month": row["month"],
        "revenue": serializers.money(row["revenue"]),
        "invoices": row["invoices"],
        "currency": row["currency"],
    } for row in data["items"]]
    return ok({
        "months": data["months"],
        "items": items,
        "count": len(items),
        "total": serializers.money(data["total"]),
        "from": serializers.iso(data.get("from")),
        "to": serializers.iso(data.get("to")),
    })


@endpoint(("GET",))
def stats_plan_distribution(request):
    """按计划分布：在服订阅数、MRR 与收入占比（降序）。"""
    at = _as_of(request)
    data = services.plan_distribution(request.user, at)
    items = [{
        "plan_id": row["plan_id"],
        "plan": row["plan"],
        "name": row["name"],
        "billing_period": row["billing_period"],
        "subscriptions": row["subscriptions"],
        "mrr": serializers.money(row["mrr"]),
        "share": row["share"],
    } for row in data["items"]]
    return ok({
        "items": items,
        "count": data["count"],
        "total_mrr": serializers.money(data["total_mrr"]),
    })


@endpoint(("GET",))
def stats_forecast(request):
    """收入预测：下一账期固定费月摊 + 近 90 天用量月均。"""
    at = date_param(request, "at")
    data = services.forecast_next_period(request.user, at)
    items = [{
        "subscription_id": row["subscription_id"],
        "customer_id": row["customer_id"],
        "customer": row["customer"],
        "plan": row["plan"],
        "currency": row["currency"],
        "fixed": serializers.money(row["fixed"]),
        "usage": serializers.money(row["usage"]),
        "forecast": serializers.money(row["forecast"]),
    } for row in data["items"]]
    return ok({
        "horizon_days": data["horizon_days"],
        "as_of": serializers.iso(data["as_of"]),
        "by_currency": _money_map(data["by_currency"]),
        "total": serializers.money(data["total"]),
        "items": items,
        "count": data["count"],
    })


@endpoint(("GET",))
def stats_overview(request):
    """计费总览：客户/订阅/账单状态分布 + 核心指标（首屏一次取全）。"""
    at = _as_of(request)
    data = services.overview(request.user, at)
    return ok({
        "customers": data["customers"],
        "subscriptions": data["subscriptions"],
        "subscriptions_by_status": data["subscriptions_by_status"],
        "invoices_by_status": data["invoices_by_status"],
        "mrr": serializers.money(data["mrr"]),
        "arr": serializers.money(data["arr"]),
        "mrr_by_currency": _money_map(data["mrr_by_currency"]),
        "delinquency_rate": data["delinquency_rate"],
        "trial_conversion_rate": data["trial_conversion_rate"],
        "churn_rate": data["churn_rate"],
    })
