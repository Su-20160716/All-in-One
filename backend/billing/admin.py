# -*- coding: utf-8 -*-
"""订阅计费 · Django Admin 注册。

管理后台只做「看 + 轻改」：计费数据的资金字段由 services 统一写入，
这里不提供批量改金额的入口，避免绕过行项重算与幂等校验。
"""
from django.contrib import admin

from billing import models


class BillingAdmin(admin.ModelAdmin):
    """统一只读字段与列表配置：created_at/updated_at 不允许手改。"""

    readonly_fields = ("created_at", "updated_at")
    list_per_page = 50


@admin.register(models.Plan)
class PlanAdmin(BillingAdmin):
    list_display = ("id", "code", "name", "billing_period", "status", "trial_days")
    list_filter = ("status", "billing_period")
    search_fields = ("code", "name")


@admin.register(models.Price)
class PriceAdmin(BillingAdmin):
    list_display = ("id", "plan", "currency", "amount", "billing_mode", "status")
    list_filter = ("currency", "billing_mode", "status")
    search_fields = ("plan__code", "nickname")


@admin.register(models.Feature)
class FeatureAdmin(BillingAdmin):
    list_display = ("id", "code", "name", "feature_type")
    list_filter = ("feature_type",)
    search_fields = ("code", "name")


@admin.register(models.PlanFeature)
class PlanFeatureAdmin(BillingAdmin):
    list_display = ("id", "plan", "feature", "included_qty", "unit")
    search_fields = ("plan__code", "feature__code")


@admin.register(models.Customer)
class CustomerAdmin(BillingAdmin):
    list_display = ("id", "name", "email", "currency", "status", "balance")
    list_filter = ("status", "currency")
    search_fields = ("name", "email", "tax_id")


@admin.register(models.Subscription)
class SubscriptionAdmin(BillingAdmin):
    list_display = ("id", "customer", "plan", "status", "seats",
                    "current_period_start", "current_period_end")
    list_filter = ("status", "currency")
    search_fields = ("customer__name", "plan__code")


@admin.register(models.SubscriptionItem)
class SubscriptionItemAdmin(BillingAdmin):
    list_display = ("id", "subscription", "price", "quantity", "effective_from")
    search_fields = ("subscription__customer__name",)


@admin.register(models.Meter)
class MeterAdmin(BillingAdmin):
    list_display = ("id", "code", "name", "aggregation", "reset_period")
    list_filter = ("aggregation", "reset_period")
    search_fields = ("code", "name")


@admin.register(models.UsageRecord)
class UsageRecordAdmin(BillingAdmin):
    list_display = ("id", "subscription", "meter", "quantity", "invoiced", "occurred_at")
    list_filter = ("invoiced",)
    search_fields = ("subscription__customer__name", "meter__code")


@admin.register(models.Invoice)
class InvoiceAdmin(BillingAdmin):
    list_display = ("id", "number", "customer", "status", "currency",
                    "total", "amount_paid", "due_date")
    list_filter = ("status", "currency")
    search_fields = ("number", "customer__name")


@admin.register(models.InvoiceLine)
class InvoiceLineAdmin(BillingAdmin):
    list_display = ("id", "invoice", "line_type", "description", "amount")
    list_filter = ("line_type",)
    search_fields = ("invoice__number", "description")


@admin.register(models.Payment)
class PaymentAdmin(BillingAdmin):
    list_display = ("id", "invoice", "customer", "status", "method",
                    "amount", "gateway_ref")
    list_filter = ("status", "method")
    search_fields = ("gateway_ref", "customer__name")


@admin.register(models.CreditNote)
class CreditNoteAdmin(BillingAdmin):
    list_display = ("id", "number", "customer", "status", "amount")
    list_filter = ("status",)
    search_fields = ("number", "customer__name")


@admin.register(models.Coupon)
class CouponAdmin(BillingAdmin):
    list_display = ("id", "code", "coupon_type", "percent", "amount",
                    "status", "redeemed_count")
    list_filter = ("coupon_type", "status")
    search_fields = ("code", "name")


@admin.register(models.CouponRedemption)
class CouponRedemptionAdmin(BillingAdmin):
    list_display = ("id", "coupon", "customer", "subscription", "amount")
    search_fields = ("coupon__code", "customer__name")


@admin.register(models.DunningPolicy)
class DunningPolicyAdmin(BillingAdmin):
    list_display = ("id", "code", "name", "status")
    list_filter = ("status",)
    search_fields = ("code", "name")


@admin.register(models.DunningStep)
class DunningStepAdmin(BillingAdmin):
    list_display = ("id", "policy", "sequence", "delay_days", "action")
    list_filter = ("action",)
    search_fields = ("policy__code",)


@admin.register(models.DunningRun)
class DunningRunAdmin(BillingAdmin):
    list_display = ("id", "subscription", "policy", "status", "current_step", "started_at")
    list_filter = ("status",)
    search_fields = ("subscription__customer__name", "policy__code")


@admin.register(models.TaxRate)
class TaxRateAdmin(BillingAdmin):
    list_display = ("id", "name", "country", "region", "rate", "enabled", "is_default")
    list_filter = ("country", "enabled", "is_default")
    search_fields = ("name", "country", "region")


@admin.register(models.BillingEvent)
class BillingEventAdmin(BillingAdmin):
    list_display = ("id", "event_type", "object_type", "object_id", "status", "created_at")
    list_filter = ("status", "event_type")
    search_fields = ("event_type", "idempotency_key", "object_type")
