# -*- coding: utf-8 -*-
"""订阅计费 · 账单与收款接口：发票(12) + 支付(5) + 信用票据(4) = 21 个。

账单是计费的「输出面」：生成必须幂等、发送只有一次、作废要释放用量、
收款要能部分/超额、退款要能回滚。所有金额写入都走 services 的 Decimal
工具，视图层不出现 float。

路由（挂在 /api/billing/ 下）：
    GET  invoices/                     发票列表
    POST invoices/create/              手工建账单（草稿）
    GET  invoices/<pk>/                发票详情（行项/支付/事件/PDF 元数据）
    POST invoices/<pk>/update/         更新草稿（行项可整体替换）
    POST invoices/<pk>/delete/         删除草稿/作废票
    POST invoices/generate/            按订阅生成账单（幂等）
    POST invoices/<pk>/send/           发送（草稿 → 待支付）
    POST invoices/<pk>/void/           作废（释放用量）
    POST invoices/<pk>/mark-paid/      登记收款并结清
    POST invoices/overdue-scan/        逾期扫描
    GET  invoices/<pk>/pdf/            PDF 元数据（不生成文件）
    POST invoices/<pk>/recalc/         重算汇总
    GET  payments/                     支付流水列表
    POST payments/create/              登记收款/充值（状态模拟）
    GET  payments/<pk>/                支付详情
    POST payments/<pk>/retry/          重试失败支付
    POST payments/<pk>/refund/         退款（部分/全额）
    GET  credit-notes/                 信用票据列表
    POST credit-notes/create/          开信用票据
    POST credit-notes/<pk>/update/     更新/作废票据
    POST credit-notes/<pk>/apply/      核销票据
"""
from datetime import timedelta

from django.db import transaction

from devtools.common import endpoint, ok, opt_str

from billing import serializers, services
from billing.models import (
    CREDIT_NOTE_STATUS,
    INVOICE_STATUS,
    LINE_TYPES,
    PAYMENT_METHODS,
    CreditNote,
    Invoice,
    Payment,
)
from billing.views_common import (
    apply_search,
    bool_param,
    choice_param,
    date_param,
    dict_param,
    filter_by,
    get_customer,
    get_invoice,
    get_subscription,
    int_param,
    list_param,
    money_param,
    paginate,
)


def _invoice_detail(invoice):
    """发票详情渲染（含行项/支付/事件/PDF 元数据）。"""
    return serializers.invoice_dict(invoice, detail=True)


def _pdf_dict(metadata):
    """PDF 元数据渲染：日期 ISO、金额已是字符串。"""
    data = dict(metadata)
    for key in ("issue_date", "due_date", "period_start", "period_end"):
        data[key] = serializers.iso(data.get(key))
    return data


def _parse_manual_lines(request):
    """解析手工行项：行类型白名单 + 金额 Decimal 校验。"""
    rows = list_param(request, "lines", max_len=200)
    parsed = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 行格式不正确")
        line_type = str(row.get("line_type") or "subscription")
        if line_type not in LINE_TYPES:
            raise ValueError(f"第 {index} 行类型 {line_type} 不支持")
        description = str(row.get("description") or "").strip()
        if not description:
            raise ValueError(f"第 {index} 行缺少说明")
        quantity = services.to_decimal(row.get("quantity", 1), f"第 {index} 行数量", minimum=0)
        unit_amount = services.to_decimal(row.get("unit_amount", 0), f"第 {index} 行单价")
        amount = row.get("amount")
        parsed.append({
            "line_type": line_type,
            "description": description[:200],
            "quantity": services.quantize_unit(quantity),
            "unit_amount": services.quantize_unit(unit_amount),
            "amount": services.quantize_money(amount) if amount not in (None, "") else None,
            "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        })
    return parsed


# ===========================================================================
# 发票
# ===========================================================================


@endpoint(("GET",))
def invoice_list(request):
    """发票列表（q/status/客户/订阅 + 分页）。"""
    qs = services.visible(Invoice.objects.select_related("customer", "subscription"),
                          request.user)
    qs = apply_search(qs, request, ["number", "customer__name", "notes"])
    qs = filter_by(qs, request, "customer_id")
    qs = filter_by(qs, request, "subscription_id")
    only_overdue = opt_str(request, "overdue").strip().lower()
    if only_overdue in ("1", "true", "yes", "on"):
        qs = qs.filter(status="open", due_date__lt=services.today())
    return paginate(qs.order_by("-created_at", "-id"), request,
                    serializers.invoice_dict)


@endpoint()
def invoice_create(request):
    """手工建账单（草稿；行项可选，金额由行项汇总）。"""
    customer = get_customer(int_param(request, "customer_id", required=True, minimum=1),
                            request.user, write=True)
    subscription = None
    subscription_id = int_param(request, "subscription_id", minimum=1)
    if subscription_id:
        subscription = get_subscription(subscription_id, request.user, write=True)
        if subscription.customer_id != customer.pk:
            raise ValueError("订阅不属于该客户")
    lines = _parse_manual_lines(request)
    due_date = date_param(request, "due_date") or (services.today() + timedelta(days=7))
    with transaction.atomic():
        invoice = Invoice.objects.create(
            owner=request.user,
            number=services.next_invoice_number(request.user),
            customer=customer,
            subscription=subscription,
            status="draft",
            source="manual",
            currency=opt_str(request, "currency", customer.currency, max_len=8).upper()
            or customer.currency,
            period_start=date_param(request, "period_start"),
            period_end=date_param(request, "period_end"),
            due_date=due_date,
            notes=opt_str(request, "notes", max_len=2000),
            metadata=dict_param(request, "metadata"),
        )
        for index, row in enumerate(lines, start=1):
            services.add_invoice_line(
                invoice, row["line_type"], row["description"],
                quantity=row["quantity"], unit_amount=row["unit_amount"],
                amount=row["amount"], metadata=row["metadata"], sort_order=index,
            )
        services.recalc_invoice(invoice)
        services.emit_event(request.user, "invoice.created", invoice, {
            "customer_id": customer.pk, "manual": True, "total": str(invoice.total),
        }, idempotency_key=f"invoice:{invoice.pk}:created")
    return ok(_invoice_detail(invoice))


@endpoint(("GET",))
def invoice_detail(request, pk):
    """发票详情（行项、支付、信用票据、事件、PDF 元数据）。"""
    invoice = get_invoice(pk, request.user)
    return ok(_invoice_detail(invoice))


@endpoint()
def invoice_update(request, pk):
    """更新草稿发票（行项传入则整体替换，并重算汇总）。"""
    invoice = get_invoice(pk,
                          request.user, write=True)
    if invoice.status != "draft":
        raise ValueError("仅草稿发票可以修改")
    fields = []
    if request.data.get("due_date") is not None:
        invoice.due_date = date_param(request, "due_date")
        fields.append("due_date")
    if request.data.get("notes") is not None:
        invoice.notes = opt_str(request, "notes", max_len=2000)
        fields.append("notes")
    if request.data.get("metadata") is not None:
        invoice.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    lines = None
    if request.data.get("lines") is not None:
        lines = _parse_manual_lines(request)
    with transaction.atomic():
        if lines is not None:
            invoice.lines.all().delete()
            for index, row in enumerate(lines, start=1):
                services.add_invoice_line(
                    invoice, row["line_type"], row["description"],
                    quantity=row["quantity"], unit_amount=row["unit_amount"],
                    amount=row["amount"], metadata=row["metadata"], sort_order=index,
                )
            services.recalc_invoice(invoice)
            fields.extend(["subtotal", "discount_total", "tax_total", "total"])
        if fields:
            invoice.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
    invoice.refresh_from_db()
    return ok(_invoice_detail(invoice))


@endpoint()
def invoice_delete(request, pk):
    """删除发票（仅草稿/作废，且不能有已成功支付）。"""
    invoice = get_invoice(pk,
                          request.user, write=True)
    if invoice.status not in ("draft", "void"):
        raise ValueError("仅草稿或已作废发票可以删除")
    if invoice.payments.filter(status="succeeded").exists():
        raise ValueError("发票存在成功支付，不能删除")
    pk = invoice.pk
    with transaction.atomic():
        invoice.delete()
        services.emit_event(request.user, "invoice.deleted", None, {"invoice_id": pk},
                            idempotency_key=f"invoice:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


@endpoint()
def invoice_generate(request):
    """按订阅生成账单（订阅费+用量+折扣+税；同周期重复生成会被拒绝）。"""
    subscription = get_subscription(
        int_param(request, "subscription_id", required=True, minimum=1),
        request.user, write=True)
    invoice = services.generate_invoice(
        request.user, subscription,
        period_start=date_param(request, "period_start"),
        currency=opt_str(request, "currency", "", max_len=8).upper() or None,
        due_days=int_param(request, "due_days", 7, minimum=0, maximum=365),
        include_usage=bool_param(request, "include_usage", True),
        coupon_code=opt_str(request, "coupon_code", max_len=60),
        notes=opt_str(request, "notes", max_len=2000),
    )
    if bool_param(request, "send", False):
        invoice = services.send_invoice(request.user, invoice)
    invoice.refresh_from_db()
    return ok(_invoice_detail(invoice))


@endpoint()
def invoice_send(request, pk):
    """发送发票（草稿 → 待支付；已发送则幂等返回）。"""
    invoice = get_invoice(pk,
                          request.user, write=True)
    invoice = services.send_invoice(request.user, invoice)
    return ok(_invoice_detail(invoice))


@endpoint()
def invoice_void(request, pk):
    """作废发票（释放已占用的用量流水）。"""
    invoice = get_invoice(pk,
                          request.user, write=True)
    invoice = services.void_invoice(request.user, invoice,
                                    reason=opt_str(request, "reason", max_len=500))
    return ok(_invoice_detail(invoice))


@endpoint()
def invoice_mark_paid(request, pk):
    """人工登记收款（可部分收款；全额后自动置为已支付）。"""
    invoice = get_invoice(pk,
                          request.user, write=True)
    amount = money_param(request, "amount")
    method = choice_param(request, "method", PAYMENT_METHODS, "manual", "支付方式")
    invoice, payment = services.mark_invoice_paid(
        request.user, invoice, amount=amount, method=method)
    return ok({"invoice": _invoice_detail(invoice),
               "payment": serializers.payment_dict(payment)})


@endpoint()
def invoice_overdue_scan(request):
    """逾期扫描：列出已过期未结清的发票并写审计事件。"""
    result = services.scan_overdue_invoices(request.user)
    items = []
    for row in result["items"]:
        row = dict(row)
        row["amount_due"] = serializers.money(row["amount_due"])
        row["due_date"] = serializers.iso(row["due_date"])
        items.append(row)
    return ok({"count": result["count"],
               "total_due": serializers.money(result["total_due"]),
               "items": items, "scanned_at": serializers.iso(result["scanned_at"])})


@endpoint(("GET",))
def invoice_pdf(request, pk):
    """发票 PDF 元数据（结构化快照，不生成真实文件）。"""
    invoice = get_invoice(pk, request.user)
    return ok(_pdf_dict(services.invoice_pdf_metadata(invoice)))


@endpoint()
def invoice_recalc(request, pk):
    """重算草稿发票汇总（行项被外部修改后的修复入口）。"""
    invoice = get_invoice(pk,
                          request.user, write=True)
    if invoice.status != "draft":
        raise ValueError("仅草稿发票可以重算")
    services.recalc_invoice(invoice)
    invoice.refresh_from_db()
    return ok(_invoice_detail(invoice))


# ===========================================================================
# 支付
# ===========================================================================


@endpoint(("GET",))
def payment_list(request):
    """支付流水列表（q/status/发票/客户/方式 + 分页）。"""
    qs = services.visible(Payment.objects.select_related("customer", "invoice"),
                          request.user)
    qs = apply_search(qs, request, ["gateway_ref", "failure_reason", "customer__name"])
    qs = filter_by(qs, request, "invoice_id")
    qs = filter_by(qs, request, "customer_id")
    method = opt_str(request, "method").strip()
    if method:
        qs = qs.filter(method=method)
    return paginate(qs.order_by("-created_at", "-id"), request, serializers.payment_dict)


@endpoint()
def payment_create(request):
    """登记收款（针对发票）或充值（针对客户余额），默认即时模拟成功。"""
    invoice_id = int_param(request, "invoice_id", minimum=1)
    if invoice_id:
        invoice = get_invoice(invoice_id, request.user, write=True)
        payment = services.create_payment(
            request.user, invoice,
            amount=money_param(request, "amount"),
            method=choice_param(request, "method", PAYMENT_METHODS, "card", "支付方式"),
            auto_capture=bool_param(request, "auto_capture", True),
            metadata=dict_param(request, "metadata"),
        )
    else:
        customer = get_customer(
            int_param(request, "customer_id", required=True, minimum=1),
            request.user, write=True)
        payment = services.topup_balance(
            request.user, customer,
            money_param(request, "amount", required=True, minimum=0.01),
            method=choice_param(request, "method", PAYMENT_METHODS,
                                "bank_transfer", "支付方式"),
            auto_capture=bool_param(request, "auto_capture", True),
            metadata=dict_param(request, "metadata"),
        )
    payment.refresh_from_db()
    return ok(serializers.payment_dict(payment))


@endpoint(("GET",))
def payment_detail(request, pk):
    """支付详情。"""
    payment = visible_or_none(Payment, pk, request.user, "支付记录不存在")
    return ok(serializers.payment_dict(payment))


@endpoint()
def payment_retry(request, pk):
    """重试失败支付（重置流水号并重新捕获）。"""
    payment = visible_or_none(Payment, pk,
                              request.user, "支付记录不存在", write=True)
    payment = services.retry_payment(request.user, payment)
    payment.refresh_from_db()
    return ok(serializers.payment_dict(payment))


@endpoint()
def payment_refund(request, pk):
    """退款（部分/全额；同步冲减发票已付与客户余额）。"""
    payment = visible_or_none(Payment, pk,
                              request.user, "支付记录不存在", write=True)
    payment = services.refund_payment(
        request.user, payment,
        amount=money_param(request, "amount"),
        reason=opt_str(request, "reason", max_len=300),
    )
    payment.refresh_from_db()
    invoice = payment.invoice
    return ok({
        "payment": serializers.payment_dict(payment),
        "invoice": serializers.invoice_dict(invoice) if invoice else None,
    })


def visible_or_none(model, pk, user, message, write=False):
    """取支付对象并做权限校验（重试/退款走写权限）。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


# ===========================================================================
# 信用票据
# ===========================================================================


@endpoint(("GET",))
def credit_note_list(request):
    """信用票据列表（q/status/客户/发票 + 分页）。"""
    qs = services.visible(CreditNote.objects.select_related("customer", "invoice"),
                          request.user)
    qs = apply_search(qs, request, ["number", "reason", "customer__name"])
    qs = filter_by(qs, request, "customer_id")
    qs = filter_by(qs, request, "invoice_id")
    return paginate(qs.order_by("-created_at", "-id"), request,
                    serializers.credit_note_dict)


@endpoint()
def credit_note_create(request):
    """开信用票据（红字），可关联发票。"""
    customer = get_customer(int_param(request, "customer_id", required=True, minimum=1),
                            request.user, write=True)
    invoice = None
    invoice_id = int_param(request, "invoice_id", minimum=1)
    if invoice_id:
        invoice = get_invoice(invoice_id, request.user, write=True)
        if invoice.customer_id != customer.pk:
            raise ValueError("发票不属于该客户")
    note = services.create_credit_note(
        request.user, customer,
        money_param(request, "amount", required=True, minimum=0.01),
        reason=opt_str(request, "reason", max_len=2000),
        invoice=invoice,
        currency=opt_str(request, "currency", "", max_len=8).upper() or None,
    )
    return ok(serializers.credit_note_dict(note))


@endpoint()
def credit_note_update(request, pk):
    """更新票据备注，或将未核销票据作废。"""
    note = visible_or_none(CreditNote, pk,
                           request.user, "信用票据不存在", write=True)
    fields = []
    if request.data.get("reason") is not None:
        note.reason = opt_str(request, "reason", max_len=2000)
        fields.append("reason")
    if request.data.get("metadata") is not None:
        note.metadata = dict_param(request, "metadata")
        fields.append("metadata")
    if request.data.get("status") is not None:
        status = choice_param(request, "status", CREDIT_NOTE_STATUS,
                              note.status, "票据状态")
        if status != note.status:
            if status != "void":
                raise ValueError("只能将票据作废；核销请使用 apply 接口")
            if note.status != "open":
                raise ValueError(f"当前票据状态 {note.status} 不能作废")
            note.status = "void"
            fields.append("status")
    if not fields:
        raise ValueError("没有需要更新的字段")
    note.save(update_fields=list(dict.fromkeys(fields + ["updated_at"])))
    return ok(serializers.credit_note_dict(note))


@endpoint()
def credit_note_apply(request, pk):
    """核销信用票据（优先冲抵发票，剩余进客户余额）。"""
    note = visible_or_none(CreditNote, pk,
                           request.user, "信用票据不存在", write=True)
    invoice = None
    invoice_id = int_param(request, "invoice_id", minimum=1)
    if invoice_id:
        invoice = get_invoice(invoice_id, request.user, write=True)
    result = services.apply_credit_note(request.user, note, invoice=invoice)
    return ok({
        "credit_note": serializers.credit_note_dict(result["credit_note"]),
        "applied": serializers.money(result["applied"]),
        "to_balance": serializers.money(result["to_balance"]),
        "invoice": serializers.invoice_dict(invoice) if invoice else None,
    })
