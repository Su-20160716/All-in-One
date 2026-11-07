# -*- coding: utf-8 -*-
"""订阅计费 · 目录接口（1 个）。

目录是前端的「能力说明书」：枚举、资金口径、分页契约、接口清单与当前
用户的规模统计一次返回，前端不需要硬编码任何状态码或路径。
"""
from devtools.common import endpoint, ok

from billing import services
from billing.models import (
    BILLING_MODES,
    BILLING_MODE_LABELS,
    COUPON_DURATIONS,
    COUPON_DURATION_LABELS,
    COUPON_STATUS,
    COUPON_STATUS_LABELS,
    COUPON_TYPES,
    COUPON_TYPE_LABELS,
    CREDIT_NOTE_STATUS,
    CREDIT_NOTE_STATUS_LABELS,
    CUSTOMER_STATUS,
    CUSTOMER_STATUS_LABELS,
    DUNNING_ACTIONS,
    DUNNING_ACTION_LABELS,
    DUNNING_RUN_STATUS,
    DUNNING_RUN_STATUS_LABELS,
    EVENT_STATUS,
    EVENT_STATUS_LABELS,
    FEATURE_TYPES,
    FEATURE_TYPE_LABELS,
    INVOICE_STATUS,
    INVOICE_STATUS_LABELS,
    LINE_TYPES,
    LINE_TYPE_LABELS,
    METER_AGGREGATIONS,
    METER_AGGREGATION_LABELS,
    METER_RESET_PERIODS,
    METER_RESET_LABELS,
    PAYMENT_METHODS,
    PAYMENT_METHOD_LABELS,
    PAYMENT_STATUS,
    PAYMENT_STATUS_LABELS,
    PLAN_PERIODS,
    PLAN_PERIOD_LABELS,
    PLAN_STATUS,
    PLAN_STATUS_LABELS,
    SUBSCRIPTION_STATUS,
    SUBSCRIPTION_STATUS_LABELS,
    Customer,
    Invoice,
    Payment,
    Plan,
    Subscription,
)

# 能力清单：与 services 的 10 组真实能力一一对应，前端按此渲染模块导航
CAPABILITY_DOMAINS = [
    {"key": "catalog", "title": "商品目录", "items": [
        "计划/价格/功能项/计划功能配置", "计划发布/停用/克隆", "按窗口解析生效价格"]},
    {"key": "customer", "title": "客户", "items": [
        "客户档案与信用额度", "客户账户余额", "客户 360 概览"]},
    {"key": "subscription", "title": "订阅", "items": [
        "开通/试用/转正/暂停/恢复/取消/续期", "换计划按日折算（proration）",
        "订阅明细项"]},
    {"key": "usage", "title": "用量", "items": [
        "上报（幂等键）与批量上报", "按计量聚合口径汇总", "包含额度与阶梯计价"]},
    {"key": "invoice", "title": "账单", "items": [
        "按订阅生成（同周期幂等）", "行项/折扣/税费/信用抵扣", "发送/作废/逾期扫描/PDF 元数据"]},
    {"key": "payment", "title": "收款", "items": [
        "登记收款（状态模拟 + 网关流水号）", "余额抵扣/充值", "重试/退款"]},
    {"key": "credit", "title": "信用票据", "items": [
        "开票/核销/作废", "抵扣发票未结金额"]},
    {"key": "coupon", "title": "优惠券", "items": [
        "百分比/固定额折扣", "有效期/次数上限/客户限制", "核销幂等"]},
    {"key": "dunning", "title": "催收", "items": [
        "催收策略与步骤", "扫描逾期账单推进状态机", "暂停/取消订阅"]},
    {"key": "metrics", "title": "指标", "items": [
        "MRR/ARR/ARPU", "流失率/试用转化/逾期率", "收入趋势/计划分布/账单预测"]},
]

# 资金口径说明：对账页面直接展示，避免「为什么金额差一分」的争议
MONEY_RULES = {
    "quantize": "ROUND_HALF_UP",
    "money_places": 2,
    "unit_places": 4,
    "percent_places": 2,
    "period_boundary": "current_period_start 含、current_period_end 不含",
    "proration": "按剩余自然日占比折算计费天数",
    "invoice_total": "小计 - 折扣 + 税费，最低 0",
    "amount_due": "应收 - 已收 - 信用抵扣",
    "currency": services.DEFAULT_CURRENCY,
}


def _enum(values, labels):
    """枚举 + 中文名，前端 select 直接可用。"""
    return [{"value": value, "label": labels.get(value, value)} for value in values]


def _counts(user):
    """当前用户可见的规模统计（管理员看全量）。"""
    plans = services.visible(Plan.objects.all(), user)
    customers = services.visible(Customer.objects.all(), user)
    subscriptions = services.visible(Subscription.objects.all(), user)
    invoices = services.visible(Invoice.objects.all(), user)
    payments = services.visible(Payment.objects.all(), user)
    return {
        "plans": plans.count(),
        "active_plans": plans.filter(status="active").count(),
        "customers": customers.count(),
        "subscriptions": subscriptions.count(),
        "live_subscriptions": subscriptions.filter(
            status__in=("trialing", "active", "past_due")).count(),
        "invoices": invoices.count(),
        "open_invoices": invoices.filter(status="open").count(),
        "payments": payments.count(),
    }


@endpoint(("GET",))
def catalog(request):
    """计费目录：枚举、资金口径、分页契约、接口清单与规模统计。"""
    # 延迟导入：urls 模块会 import 本模块，顶层导入会形成循环依赖。
    from billing.urls import urlpatterns

    from devtools.common import endpoint_index

    endpoints = endpoint_index(urlpatterns, exclude=("",))
    return ok({
        "app": "billing",
        "name": "订阅计费",
        "version": "1.0",
        "description": "计划/价格/订阅/用量/账单/收款/优惠/催收/指标的一体化订阅计费引擎。",
        "capabilities": CAPABILITY_DOMAINS,
        "money": MONEY_RULES,
        "pagination": {
            "page_size_default": 20,
            "page_size_max": 200,
            "response_shape": ["items", "count", "page", "page_size"],
            "filters": ["q", "status", "page", "page_size"],
        },
        "enums": {
            "plan_periods": _enum(PLAN_PERIODS, PLAN_PERIOD_LABELS),
            "plan_status": _enum(PLAN_STATUS, PLAN_STATUS_LABELS),
            "feature_types": _enum(FEATURE_TYPES, FEATURE_TYPE_LABELS),
            "billing_modes": _enum(BILLING_MODES, BILLING_MODE_LABELS),
            "customer_status": _enum(CUSTOMER_STATUS, CUSTOMER_STATUS_LABELS),
            "subscription_status": _enum(SUBSCRIPTION_STATUS, SUBSCRIPTION_STATUS_LABELS),
            "invoice_status": _enum(INVOICE_STATUS, INVOICE_STATUS_LABELS),
            "line_types": _enum(LINE_TYPES, LINE_TYPE_LABELS),
            "payment_status": _enum(PAYMENT_STATUS, PAYMENT_STATUS_LABELS),
            "payment_methods": _enum(PAYMENT_METHODS, PAYMENT_METHOD_LABELS),
            "credit_note_status": _enum(CREDIT_NOTE_STATUS, CREDIT_NOTE_STATUS_LABELS),
            "coupon_types": _enum(COUPON_TYPES, COUPON_TYPE_LABELS),
            "coupon_durations": _enum(COUPON_DURATIONS, COUPON_DURATION_LABELS),
            "coupon_status": _enum(COUPON_STATUS, COUPON_STATUS_LABELS),
            "meter_aggregations": _enum(METER_AGGREGATIONS, METER_AGGREGATION_LABELS),
            "meter_resets": _enum(METER_RESET_PERIODS, METER_RESET_LABELS),
            "dunning_actions": _enum(DUNNING_ACTIONS, DUNNING_ACTION_LABELS),
            "dunning_run_status": _enum(DUNNING_RUN_STATUS, DUNNING_RUN_STATUS_LABELS),
            "event_status": _enum(EVENT_STATUS, EVENT_STATUS_LABELS),
        },
        "counts": _counts(request.user),
        "endpoints": endpoints,
        "endpoint_count": len(endpoints),
    })
