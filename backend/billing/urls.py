# -*- coding: utf-8 -*-
"""订阅计费 · 路由（106 个接口）。

分组（括号内为接口数，合计 106）：
- 目录 catalog(1)
- 商品目录 plan(22)：计划 9 + 价格 6 + 功能项 4 + 计划功能 4（价格/功能合计 16）
- 客户与订阅 customer(23)：客户 6 + 订阅 17
- 用量 usage(8)：计量项 4 + 用量 4
- 账单 invoice(21)：发票 12 + 支付 5 + 信用票据 4
- 优惠 promo(7)
- 催收与税率 dunning(14)：催收策略 4 + 催收运行 5 + 税率 4 + 事件 1
- 指标 stats(10)

所有路径挂在 /api/billing/ 下；列表统一返回 {items,count,page,page_size}。
"""
from django.urls import path

from billing import (
    views_catalog,
    views_customer,
    views_dunning,
    views_invoice,
    views_plan,
    views_promo,
    views_stats,
    views_usage,
)

urlpatterns = [
    # ---- 目录（1）----
    path("", views_catalog.catalog, name="billing-catalog"),

    # ---- 计划（9）----
    path("plans/", views_plan.plan_list),
    path("plans/create/", views_plan.plan_create),
    path("plans/<int:pk>/", views_plan.plan_detail),
    path("plans/<int:pk>/update/", views_plan.plan_update),
    path("plans/<int:pk>/delete/", views_plan.plan_delete),
    path("plans/<int:pk>/publish/", views_plan.plan_publish),
    path("plans/<int:pk>/archive/", views_plan.plan_archive),
    path("plans/<int:pk>/clone/", views_plan.plan_clone),
    path("plans/<int:pk>/features/", views_plan.plan_features),

    # ---- 价格（6）----
    path("prices/", views_plan.price_list),
    path("prices/create/", views_plan.price_create),
    path("prices/resolve/", views_plan.price_resolve),
    path("prices/<int:pk>/update/", views_plan.price_update),
    path("prices/<int:pk>/delete/", views_plan.price_delete),

    # ---- 功能项（4）----
    path("features/", views_plan.feature_list),
    path("features/create/", views_plan.feature_create),
    path("features/<int:pk>/update/", views_plan.feature_update),
    path("features/<int:pk>/delete/", views_plan.feature_delete),

    # ---- 计划功能配置（4）----
    path("plan-features/", views_plan.plan_feature_list),
    path("plan-features/create/", views_plan.plan_feature_create),
    path("plan-features/<int:pk>/update/", views_plan.plan_feature_update),
    path("plan-features/<int:pk>/delete/", views_plan.plan_feature_delete),

    # ---- 客户（6）----
    path("customers/", views_customer.customer_list),
    path("customers/create/", views_customer.customer_create),
    path("customers/<int:pk>/", views_customer.customer_detail),
    path("customers/<int:pk>/update/", views_customer.customer_update),
    path("customers/<int:pk>/delete/", views_customer.customer_delete),
    path("customers/<int:pk>/overview/", views_customer.customer_overview),

    # ---- 订阅（17）----
    path("subscriptions/", views_customer.subscription_list),
    path("subscriptions/create/", views_customer.subscription_create),
    path("subscriptions/<int:pk>/", views_customer.subscription_detail),
    path("subscriptions/<int:pk>/update/", views_customer.subscription_update),
    path("subscriptions/<int:pk>/delete/", views_customer.subscription_delete),
    path("subscriptions/<int:pk>/activate/", views_customer.subscription_activate),
    path("subscriptions/<int:pk>/trial-convert/",
         views_customer.subscription_trial_convert),
    path("subscriptions/<int:pk>/change-preview/",
         views_customer.subscription_change_preview),
    path("subscriptions/<int:pk>/change-plan/", views_customer.subscription_change_plan),
    path("subscriptions/<int:pk>/pause/", views_customer.subscription_pause),
    path("subscriptions/<int:pk>/resume/", views_customer.subscription_resume),
    path("subscriptions/<int:pk>/cancel/", views_customer.subscription_cancel),
    path("subscriptions/<int:pk>/cancel-now/", views_customer.subscription_cancel_now),
    path("subscriptions/<int:pk>/renew/", views_customer.subscription_renew),
    path("subscriptions/<int:pk>/items/", views_customer.subscription_items),
    path("subscriptions/items/add/", views_customer.subscription_item_add),
    path("subscriptions/items/remove/", views_customer.subscription_item_remove),

    # ---- 计量项（4）----
    path("meters/", views_usage.meter_list),
    path("meters/create/", views_usage.meter_create),
    path("meters/<int:pk>/update/", views_usage.meter_update),
    path("meters/<int:pk>/delete/", views_usage.meter_delete),

    # ---- 用量（4）----
    path("usage/", views_usage.usage_list),
    path("usage/report/", views_usage.usage_report),
    path("usage/batch/", views_usage.usage_batch),
    path("usage/summary/", views_usage.usage_summary),

    # ---- 发票（12）----
    path("invoices/", views_invoice.invoice_list),
    path("invoices/create/", views_invoice.invoice_create),
    path("invoices/generate/", views_invoice.invoice_generate),
    path("invoices/overdue-scan/", views_invoice.invoice_overdue_scan),
    path("invoices/<int:pk>/", views_invoice.invoice_detail),
    path("invoices/<int:pk>/update/", views_invoice.invoice_update),
    path("invoices/<int:pk>/delete/", views_invoice.invoice_delete),
    path("invoices/<int:pk>/send/", views_invoice.invoice_send),
    path("invoices/<int:pk>/void/", views_invoice.invoice_void),
    path("invoices/<int:pk>/mark-paid/", views_invoice.invoice_mark_paid),
    path("invoices/<int:pk>/pdf/", views_invoice.invoice_pdf),
    path("invoices/<int:pk>/recalc/", views_invoice.invoice_recalc),

    # ---- 支付（5）----
    path("payments/", views_invoice.payment_list),
    path("payments/create/", views_invoice.payment_create),
    path("payments/<int:pk>/", views_invoice.payment_detail),
    path("payments/<int:pk>/retry/", views_invoice.payment_retry),
    path("payments/<int:pk>/refund/", views_invoice.payment_refund),

    # ---- 信用票据（4）----
    path("credit-notes/", views_invoice.credit_note_list),
    path("credit-notes/create/", views_invoice.credit_note_create),
    path("credit-notes/<int:pk>/update/", views_invoice.credit_note_update),
    path("credit-notes/<int:pk>/apply/", views_invoice.credit_note_apply),

    # ---- 优惠券（7）----
    path("coupons/", views_promo.coupon_list),
    path("coupons/create/", views_promo.coupon_create),
    path("coupons/validate/", views_promo.coupon_validate),
    path("coupons/redeem/", views_promo.coupon_redeem),
    path("coupons/redemptions/", views_promo.coupon_redemptions),
    path("coupons/<int:pk>/update/", views_promo.coupon_update),
    path("coupons/<int:pk>/delete/", views_promo.coupon_delete),

    # ---- 催收策略（4）----
    path("dunning-policies/", views_dunning.dunning_policy_list),
    path("dunning-policies/create/", views_dunning.dunning_policy_create),
    path("dunning-policies/<int:pk>/update/", views_dunning.dunning_policy_update),
    path("dunning-policies/<int:pk>/delete/", views_dunning.dunning_policy_delete),

    # ---- 催收运行（5）----
    path("dunning/start/", views_dunning.dunning_start),
    path("dunning/runs/", views_dunning.dunning_run_list),
    path("dunning/runs/<int:pk>/", views_dunning.dunning_run_detail),
    path("dunning/advance/", views_dunning.dunning_advance),
    path("dunning/scan/", views_dunning.dunning_scan),

    # ---- 税率（4）----
    path("tax-rates/", views_dunning.tax_rate_list),
    path("tax-rates/create/", views_dunning.tax_rate_create),
    path("tax-rates/<int:pk>/update/", views_dunning.tax_rate_update),
    path("tax-rates/<int:pk>/delete/", views_dunning.tax_rate_delete),

    # ---- 事件时间线（1）----
    path("events/", views_dunning.events_list),

    # ---- 指标（10）----
    path("stats/mrr/", views_stats.stats_mrr),
    path("stats/arr/", views_stats.stats_arr),
    path("stats/arpu/", views_stats.stats_arpu),
    path("stats/churn/", views_stats.stats_churn),
    path("stats/trial-conversion/", views_stats.stats_trial_conversion),
    path("stats/delinquency/", views_stats.stats_delinquency),
    path("stats/revenue-trend/", views_stats.stats_revenue_trend),
    path("stats/plan-distribution/", views_stats.stats_plan_distribution),
    path("stats/forecast/", views_stats.stats_forecast),
    path("stats/overview/", views_stats.stats_overview),
]

# 接口数自检：新增/删除路由时立刻暴露，避免目录与实际路由漂移。
_GROUPS = (1, 22, 23, 8, 21, 7, 14, 10)
assert len(urlpatterns) == 106 == sum(_GROUPS), \
    f"billing 接口数应为 106，实际 {len(urlpatterns)}"
