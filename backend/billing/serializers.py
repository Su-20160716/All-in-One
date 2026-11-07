# -*- coding: utf-8 -*-
"""订阅计费 · 响应渲染。

视图只负责业务，渲染集中在这里，保证同一对象在列表/详情/回调里字段一致。
金额一律输出字符串（两位/四位小数）：前端不需要猜浮点精度，JSON 也不会
出现 12.0 与 12 两种形态，对账页面可以直接字符串比对。
"""
from billing import services
from billing.models import (
    BILLING_MODE_LABELS,
    COUPON_DURATION_LABELS,
    COUPON_STATUS_LABELS,
    COUPON_TYPE_LABELS,
    CREDIT_NOTE_STATUS_LABELS,
    CUSTOMER_STATUS_LABELS,
    DUNNING_ACTION_LABELS,
    DUNNING_RUN_STATUS_LABELS,
    EVENT_STATUS_LABELS,
    FEATURE_TYPE_LABELS,
    INVOICE_STATUS_LABELS,
    LINE_TYPE_LABELS,
    METER_AGGREGATION_LABELS,
    METER_RESET_LABELS,
    PAYMENT_METHOD_LABELS,
    PAYMENT_STATUS_LABELS,
    PLAN_PERIOD_LABELS,
    PLAN_STATUS_LABELS,
    SUBSCRIPTION_STATUS_LABELS,
    label_of,
)


def iso(value):
    """时间渲染：None 保持 None，日期/时间统一 ISO 8601。"""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else value


def day(value):
    """日期渲染（DateField 直接 isoformat）。"""
    return value.isoformat() if value else None


def money(value):
    """金额渲染，统一两位小数。"""
    return services.money_str(value)


def unit(value):
    """单价/数量渲染，最多四位小数。"""
    return services.unit_str(value)


def plan_dict(plan, detail=False):
    data = {
        "id": plan.pk,
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "billing_period": plan.billing_period,
        "billing_period_label": label_of(plan.billing_period, PLAN_PERIOD_LABELS),
        "trial_days": plan.trial_days,
        "status": plan.status,
        "status_label": label_of(plan.status, PLAN_STATUS_LABELS),
        "sort_order": plan.sort_order,
        "limits": plan.limits or {},
        "metadata": plan.metadata or {},
        "published_at": iso(plan.published_at),
        "created_at": iso(plan.created_at),
        "updated_at": iso(plan.updated_at),
    }
    if detail:
        data["prices"] = [price_dict(p) for p in plan.prices.all()]
        data["plan_features"] = [plan_feature_dict(b) for b in
                                 plan.plan_features.select_related("feature").all()]
        data["stats"] = services.plan_usage_stats(plan)
    return data


def price_dict(price):
    return {
        "id": price.pk,
        "plan_id": price.plan_id,
        "currency": price.currency,
        "amount": unit(price.amount),
        "billing_mode": price.billing_mode,
        "billing_mode_label": label_of(price.billing_mode, BILLING_MODE_LABELS),
        "tiers": price.tiers or [],
        "nickname": price.nickname,
        "effective_from": day(price.effective_from),
        "effective_to": day(price.effective_to),
        "status": price.status,
        "created_at": iso(price.created_at),
        "updated_at": iso(price.updated_at),
    }


def feature_dict(feature):
    return {
        "id": feature.pk,
        "code": feature.code,
        "name": feature.name,
        "feature_type": feature.feature_type,
        "feature_type_label": label_of(feature.feature_type, FEATURE_TYPE_LABELS),
        "description": feature.description,
        "unit": feature.unit,
        "status": feature.status,
        "created_at": iso(feature.created_at),
        "updated_at": iso(feature.updated_at),
    }


def plan_feature_dict(binding):
    feature = getattr(binding, "feature", None)
    return {
        "id": binding.pk,
        "plan_id": binding.plan_id,
        "feature_id": binding.feature_id,
        "feature_code": feature.code if feature else "",
        "feature_name": feature.name if feature else "",
        "feature_type": feature.feature_type if feature else "",
        "included_qty": unit(binding.included_qty),
        "unit": binding.unit,
        "overage_unit_amount": unit(binding.overage_unit_amount),
        "metadata": binding.metadata or {},
        "created_at": iso(binding.created_at),
        "updated_at": iso(binding.updated_at),
    }


def customer_dict(customer, with_metrics=False):
    data = {
        "id": customer.pk,
        "name": customer.name,
        "email": customer.email,
        "tax_id": customer.tax_id,
        "address": customer.address,
        "country": customer.country,
        "region": customer.region,
        "currency": customer.currency,
        "status": customer.status,
        "status_label": label_of(customer.status, CUSTOMER_STATUS_LABELS),
        "balance": money(customer.balance),
        "credit_limit": money(customer.credit_limit),
        "metadata": customer.metadata or {},
        "created_at": iso(customer.created_at),
        "updated_at": iso(customer.updated_at),
    }
    if with_metrics:
        data["credit_available"] = money(services.credit_available(customer))
        data["outstanding"] = money(services.outstanding_total(customer))
        data["subscription_count"] = customer.subscriptions.count()
        data["invoice_count"] = customer.invoices.count()
    return data


def subscription_item_dict(item):
    price = getattr(item, "price", None)
    return {
        "id": item.pk,
        "subscription_id": item.subscription_id,
        "price_id": item.price_id,
        "currency": price.currency if price else "",
        "unit_amount": unit(price.amount) if price else "0.0000",
        "billing_mode": price.billing_mode if price else "",
        "quantity": unit(item.quantity),
        "effective_from": day(item.effective_from),
        "effective_to": day(item.effective_to),
        "metadata": item.metadata or {},
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def subscription_dict(subscription, detail=False):
    customer = getattr(subscription, "customer", None)
    plan = getattr(subscription, "plan", None)
    data = {
        "id": subscription.pk,
        "customer_id": subscription.customer_id,
        "customer_name": customer.name if customer else "",
        "plan_id": subscription.plan_id,
        "plan_code": plan.code if plan else "",
        "plan_name": plan.name if plan else "",
        "status": subscription.status,
        "status_label": label_of(subscription.status, SUBSCRIPTION_STATUS_LABELS),
        "currency": subscription.currency,
        "seats": subscription.seats,
        "start_date": day(subscription.start_date),
        "trial_end": iso(subscription.trial_end),
        "in_trial": subscription.status == "trialing",
        "current_period_start": day(subscription.current_period_start),
        "current_period_end": day(subscription.current_period_end),
        "current_period_days": subscription.current_period_days,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "auto_renew": subscription.auto_renew,
        "canceled_at": iso(subscription.canceled_at),
        "cancel_reason": subscription.cancel_reason,
        "paused_at": iso(subscription.paused_at),
        "period_amount": money(services.subscription_period_amount(subscription)),
        "monthly_value": money(services.subscription_monthly_value(subscription)),
        "metadata": subscription.metadata or {},
        "created_at": iso(subscription.created_at),
        "updated_at": iso(subscription.updated_at),
    }
    if detail:
        data["items"] = [subscription_item_dict(i) for i in
                         subscription.items.select_related("price", "price__plan").all()]
        data["usage"] = services.usage_summary(
            subscription, subscription.current_period_start, subscription.current_period_end)
        data["recent_invoices"] = [
            invoice_dict(inv)
            for inv in subscription.invoices.select_related("customer").order_by("-id")[:10]
        ]
        data["events"] = [
            event_dict(ev) for ev in services.events_for(subscription, limit=20)
        ]
    return data


def meter_dict(meter):
    return {
        "id": meter.pk,
        "code": meter.code,
        "name": meter.name,
        "aggregation": meter.aggregation,
        "aggregation_label": label_of(meter.aggregation, METER_AGGREGATION_LABELS),
        "unit": meter.unit,
        "reset_period": meter.reset_period,
        "reset_period_label": label_of(meter.reset_period, METER_RESET_LABELS),
        "status": meter.status,
        "description": meter.description,
        "created_at": iso(meter.created_at),
        "updated_at": iso(meter.updated_at),
    }


def usage_dict(record, detail=False):
    meter = getattr(record, "meter", None)
    data = {
        "id": record.pk,
        "subscription_id": record.subscription_id,
        "meter_id": record.meter_id,
        "meter_code": meter.code if meter else "",
        "meter_name": meter.name if meter else "",
        "unit": meter.unit if meter else "",
        "quantity": unit(record.quantity),
        "occurred_at": iso(record.occurred_at),
        "idempotency_key": record.idempotency_key,
        "source": record.source,
        "invoiced": record.invoiced,
        "invoice_id": record.invoice_id,
        "created_at": iso(record.created_at),
    }
    if detail:
        data["metadata"] = record.metadata or {}
    return data


def invoice_line_dict(line):
    return {
        "id": line.pk,
        "invoice_id": line.invoice_id,
        "line_type": line.line_type,
        "line_type_label": label_of(line.line_type, LINE_TYPE_LABELS),
        "description": line.description,
        "quantity": unit(line.quantity),
        "unit_amount": unit(line.unit_amount),
        "amount": money(line.amount),
        "metadata": line.metadata or {},
        "sort_order": line.sort_order,
    }


def invoice_dict(invoice, detail=False):
    customer = getattr(invoice, "customer", None)
    data = {
        "id": invoice.pk,
        "number": invoice.number,
        "customer_id": invoice.customer_id,
        "customer_name": customer.name if customer else "",
        "subscription_id": invoice.subscription_id,
        "status": invoice.status,
        "status_label": label_of(invoice.status, INVOICE_STATUS_LABELS),
        "source": invoice.source,
        "currency": invoice.currency,
        "period_start": day(invoice.period_start),
        "period_end": day(invoice.period_end),
        "subtotal": money(invoice.subtotal),
        "discount_total": money(invoice.discount_total),
        "tax_total": money(invoice.tax_total),
        "total": money(invoice.total),
        "amount_paid": money(invoice.amount_paid),
        "credit_applied": money(invoice.credit_applied),
        "amount_due": money(invoice.amount_due),
        "due_date": day(invoice.due_date),
        "is_overdue": invoice.is_overdue,
        "paid_at": iso(invoice.paid_at),
        "sent_at": iso(invoice.sent_at),
        "voided_at": iso(invoice.voided_at),
        "notes": invoice.notes,
        "metadata": invoice.metadata or {},
        "created_at": iso(invoice.created_at),
        "updated_at": iso(invoice.updated_at),
    }
    if detail:
        data["lines"] = [invoice_line_dict(line) for line in invoice.lines.all()]
        data["payments"] = [payment_dict(p) for p in
                            invoice.payments.select_related("customer").all()]
        data["credit_notes"] = [credit_note_dict(n) for n in invoice.credit_notes.all()]
        data["events"] = [event_dict(ev) for ev in services.events_for(invoice, limit=30)]
        data["pdf"] = services.invoice_pdf_metadata(invoice)
    return data


def payment_dict(payment):
    customer = getattr(payment, "customer", None)
    return {
        "id": payment.pk,
        "invoice_id": payment.invoice_id,
        "customer_id": payment.customer_id,
        "customer_name": customer.name if customer else "",
        "amount": money(payment.amount),
        "currency": payment.currency,
        "method": payment.method,
        "method_label": label_of(payment.method, PAYMENT_METHOD_LABELS),
        "status": payment.status,
        "status_label": label_of(payment.status, PAYMENT_STATUS_LABELS),
        "gateway_ref": payment.gateway_ref,
        "failure_reason": payment.failure_reason,
        "paid_at": iso(payment.paid_at),
        "attempts": payment.attempts,
        "metadata": payment.metadata or {},
        "created_at": iso(payment.created_at),
        "updated_at": iso(payment.updated_at),
    }


def credit_note_dict(note):
    customer = getattr(note, "customer", None)
    return {
        "id": note.pk,
        "number": note.number,
        "customer_id": note.customer_id,
        "customer_name": customer.name if customer else "",
        "invoice_id": note.invoice_id,
        "amount": money(note.amount),
        "currency": note.currency,
        "reason": note.reason,
        "status": note.status,
        "status_label": label_of(note.status, CREDIT_NOTE_STATUS_LABELS),
        "applied_at": iso(note.applied_at),
        "metadata": note.metadata or {},
        "created_at": iso(note.created_at),
        "updated_at": iso(note.updated_at),
    }


def coupon_dict(coupon, detail=False):
    data = {
        "id": coupon.pk,
        "code": coupon.code,
        "name": coupon.name,
        "description": coupon.description,
        "coupon_type": coupon.coupon_type,
        "coupon_type_label": label_of(coupon.coupon_type, COUPON_TYPE_LABELS),
        # 百分比按金额精度输出，避免内存中 4 位小数与库内 2 位不一致
        "percent": money(coupon.percent),
        "amount": money(coupon.amount),
        "currency": coupon.currency,
        "duration": coupon.duration,
        "duration_label": label_of(coupon.duration, COUPON_DURATION_LABELS),
        "duration_months": coupon.duration_months,
        "max_redemptions": coupon.max_redemptions,
        "redeemed_count": coupon.redeemed_count,
        "remaining": coupon.remaining,
        "valid_from": iso(coupon.valid_from),
        "valid_until": iso(coupon.valid_until),
        "status": coupon.status,
        "status_label": label_of(coupon.status, COUPON_STATUS_LABELS),
        "customer_id": coupon.customer_id,
        "metadata": coupon.metadata or {},
        "created_at": iso(coupon.created_at),
        "updated_at": iso(coupon.updated_at),
    }
    if detail:
        data["redemptions"] = [redemption_dict(r) for r in
                               coupon.redemptions.select_related("customer").all()[:50]]
    return data


def redemption_dict(redemption):
    coupon = getattr(redemption, "coupon", None)
    customer = getattr(redemption, "customer", None)
    return {
        "id": redemption.pk,
        "coupon_id": redemption.coupon_id,
        "coupon_code": coupon.code if coupon else "",
        "customer_id": redemption.customer_id,
        "customer_name": customer.name if customer else "",
        "subscription_id": redemption.subscription_id,
        "amount": money(redemption.amount),
        "currency": redemption.currency,
        "idempotency_key": redemption.idempotency_key,
        "metadata": redemption.metadata or {},
        "created_at": iso(redemption.created_at),
    }


def dunning_step_dict(step):
    return {
        "id": step.pk,
        "policy_id": step.policy_id,
        "sequence": step.sequence,
        "delay_days": step.delay_days,
        "action": step.action,
        "action_label": label_of(step.action, DUNNING_ACTION_LABELS),
        "template": step.template,
        "metadata": step.metadata or {},
    }


def dunning_policy_dict(policy, detail=False):
    data = {
        "id": policy.pk,
        "code": policy.code,
        "name": policy.name,
        "description": policy.description,
        "status": policy.status,
        "metadata": policy.metadata or {},
        "created_at": iso(policy.created_at),
        "updated_at": iso(policy.updated_at),
    }
    if detail:
        data["steps"] = [dunning_step_dict(s) for s in policy.steps.order_by("sequence")]
        data["run_count"] = policy.runs.count()
    return data


def dunning_run_dict(run, detail=False):
    subscription = getattr(run, "subscription", None)
    policy = getattr(run, "policy", None)
    data = {
        "id": run.pk,
        "subscription_id": run.subscription_id,
        "customer_id": subscription.customer_id if subscription else None,
        "policy_id": run.policy_id,
        "policy_code": policy.code if policy else "",
        "status": run.status,
        "status_label": label_of(run.status, DUNNING_RUN_STATUS_LABELS),
        "current_step": run.current_step,
        "started_at": iso(run.started_at),
        "next_retry_at": iso(run.next_retry_at),
        "completed_at": iso(run.completed_at),
        "note": run.note,
        "metadata": run.metadata or {},
    }
    if detail:
        data["steps"] = [dunning_step_dict(s) for s in policy.steps.order_by("sequence")] \
            if policy else []
        data["events"] = [event_dict(ev) for ev in services.events_for(run, limit=50)]
    return data


def tax_rate_dict(rate):
    return {
        "id": rate.pk,
        "country": rate.country,
        "region": rate.region,
        "name": rate.name,
        "rate": str(rate.rate),
        "effective_from": day(rate.effective_from),
        "effective_to": day(rate.effective_to),
        "enabled": rate.enabled,
        "is_default": rate.is_default,
        "created_at": iso(rate.created_at),
        "updated_at": iso(rate.updated_at),
    }


def event_dict(event):
    return {
        "id": event.pk,
        "event_type": event.event_type,
        "object_type": event.object_type,
        "object_id": event.object_id,
        "payload": event.payload or {},
        "idempotency_key": event.idempotency_key,
        "status": event.status,
        "status_label": label_of(event.status, EVENT_STATUS_LABELS),
        "processed_at": iso(event.processed_at),
        "error": event.error,
        "created_at": iso(event.created_at),
    }
