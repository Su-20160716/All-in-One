# -*- coding: utf-8 -*-
"""订阅计费 · 用量接口：计量项(4) + 用量(4) = 8 个。

用量是「按量计费」的输入：上报必须幂等（接入方重试很常见），查询必须
按账期边界过滤（否则跨月用量会被算进错误账单），汇总必须给出包含额度/
超量/金额三段，方便客服解释账单。

路由（挂在 /api/billing/ 下）：
    GET  meters/                 计量项列表
    POST meters/create/          新建计量项
    POST meters/<pk>/update/     更新计量项
    POST meters/<pk>/delete/     删除计量项
    POST usage/report/           上报单条用量（幂等键）
    POST usage/batch/            批量上报
    GET  usage/                  用量流水列表
    GET  usage/summary/          账期用量汇总（含超量金额）
"""
import re

from django.db import transaction

from devtools.common import endpoint, ok, opt_str, p, req_str

from billing import serializers, services
from billing.models import (
    METER_AGGREGATIONS,
    METER_RESET_PERIODS,
    Meter,
    UsageRecord,
)
from billing.views_common import (
    apply_search,
    bool_param,
    choice_param,
    date_param,
    dict_param,
    datetime_param,
    filter_by,
    get_meter,
    get_subscription,
    int_param,
    list_param,
    money_param,
    paginate,
)

METER_CODE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{1,59}$")


def _check_meter_code(code):
    """计量编码与功能编码同规则：字母开头，可含点号（如 api.calls）。"""
    if not METER_CODE_PATTERN.match(code or ""):
        raise ValueError("计量编码必须字母开头，仅含字母/数字/下划线/中划线/点号（2-60 位）")
    return code


def _resolve_meter(request, user, write=False):
    """按 meter_id 或 code 取计量项（两个入口都支持，接入方习惯不同）。"""
    meter_id = int_param(request, "meter_id", minimum=1)
    if meter_id:
        return get_meter(meter_id, user, write=write)
    code = str(p(request, "meter") or p(request, "meter_code") or "").strip()
    if not code:
        raise ValueError("缺少必填参数: meter 或 meter_id")
    meter = Meter.objects.filter(code=code).first()
    if meter is None:
        raise ValueError("计量项不存在")
    services.ensure_visible(meter, user)
    if write:
        services.ensure_writable(meter, user)
    return meter


def _usage_summary_dict(summary):
    """用量汇总渲染：数量保留 4 位、金额两位、日期 ISO。"""
    items = []
    for row in summary["items"]:
        items.append({
            "meter_id": row["meter_id"],
            "meter_code": row["meter_code"],
            "meter_name": row["meter_name"],
            "aggregation": row["aggregation"],
            "unit": row["unit"],
            "records": row["records"],
            "quantity": serializers.unit(row["quantity"]),
            "included": serializers.unit(row["included"]),
            "billable": serializers.unit(row["billable"]),
            "unit_amount": serializers.unit(row["unit_amount"]),
            "amount": serializers.money(row["amount"]),
        })
    return {
        "subscription_id": summary["subscription_id"],
        "period_start": serializers.iso(summary["period_start"]),
        "period_end": serializers.iso(summary["period_end"]),
        "items": items,
        "meter_count": summary["meter_count"],
        "total_quantity": serializers.unit(summary["total_quantity"]),
        "total_amount": serializers.money(summary["total_amount"]),
    }


# ===========================================================================
# 计量项
# ===========================================================================


@endpoint(("GET",))
def meter_list(request):
    """计量项列表（q/status + 分页）。"""
    qs = services.visible(Meter.objects.all(), request.user)
    qs = apply_search(qs, request, ["code", "name", "description"])
    return paginate(qs.order_by("id"), request, serializers.meter_dict)


@endpoint()
def meter_create(request):
    """新建计量项（聚合方式与重置周期决定后续账单口径）。"""
    code = _check_meter_code(req_str(request, "code", max_len=60).strip())
    if Meter.objects.filter(owner=request.user, code=code).exists():
        raise ValueError("计量编码已存在")
    with transaction.atomic():
        meter = Meter.objects.create(
            owner=request.user,
            code=code,
            name=req_str(request, "name", max_len=120).strip(),
            aggregation=choice_param(request, "aggregation", METER_AGGREGATIONS,
                                     "sum", "聚合方式"),
            unit=opt_str(request, "unit", max_len=20),
            reset_period=choice_param(request, "reset_period", METER_RESET_PERIODS,
                                      "month", "重置周期"),
            status=choice_param(request, "status", ("active", "archived"),
                                "active", "计量项状态"),
            description=opt_str(request, "description", max_len=5000),
        )
        services.emit_event(request.user, "meter.created", meter, {
            "code": code, "aggregation": meter.aggregation,
        }, idempotency_key=f"meter:{meter.pk}:created")
    return ok(serializers.meter_dict(meter))


@endpoint()
def meter_update(request, pk):
    """更新计量项（已产生流水后不建议改聚合方式，这里仍允许但会改变历史口径）。"""
    meter = get_meter(pk,
                      request.user, write=True)
    fields = []
    if request.data.get("code") is not None:
        code = _check_meter_code(req_str(request, "code", max_len=60).strip())
        if Meter.objects.filter(owner=meter.owner_id, code=code) \
                .exclude(pk=meter.pk).exists():
            raise ValueError("计量编码已存在")
        meter.code = code
        fields.append("code")
    if request.data.get("name") is not None:
        meter.name = req_str(request, "name", max_len=120).strip()
        fields.append("name")
    if request.data.get("aggregation") is not None:
        meter.aggregation = choice_param(request, "aggregation", METER_AGGREGATIONS,
                                         meter.aggregation, "聚合方式")
        fields.append("aggregation")
    if request.data.get("reset_period") is not None:
        meter.reset_period = choice_param(request, "reset_period", METER_RESET_PERIODS,
                                          meter.reset_period, "重置周期")
        fields.append("reset_period")
    if request.data.get("unit") is not None:
        meter.unit = opt_str(request, "unit", max_len=20)
        fields.append("unit")
    if request.data.get("description") is not None:
        meter.description = opt_str(request, "description", max_len=5000)
        fields.append("description")
    if request.data.get("status") is not None:
        meter.status = choice_param(request, "status", ("active", "archived"),
                                    meter.status, "计量项状态")
        fields.append("status")
    if not fields:
        raise ValueError("没有需要更新的字段")
    meter.save(update_fields=fields + ["updated_at"])
    return ok(serializers.meter_dict(meter))


@endpoint()
def meter_delete(request, pk):
    """删除计量项（已有用量流水时拒绝，保证历史账单可解释）。"""
    meter = get_meter(pk,
                      request.user, write=True)
    if meter.usage_records.exists():
        raise ValueError("计量项已有用量流水，不能删除（请停用）")
    pk = meter.pk
    with transaction.atomic():
        meter.delete()
        services.emit_event(request.user, "meter.deleted", None, {"meter_id": pk},
                            idempotency_key=f"meter:{pk}:deleted")
    return ok({"deleted": True, "id": pk})


# ===========================================================================
# 用量
# ===========================================================================


@endpoint()
def usage_report(request):
    """上报单条用量（幂等键重复时返回原记录，created=False）。"""
    subscription = get_subscription(
        int_param(request, "subscription_id", required=True, minimum=1),
        request.user, write=True)
    meter = _resolve_meter(request, request.user)
    quantity = money_param(request, "quantity", required=True, minimum=0.0001)
    record, created = services.report_usage(
        subscription.owner,
        subscription,
        meter,
        quantity,
        occurred_at=datetime_param(request, "occurred_at"),
        idempotency_key=opt_str(request, "idempotency_key", max_len=120),
        source=opt_str(request, "source", "api", max_len=60),
        metadata=dict_param(request, "metadata"),
    )
    data = serializers.usage_dict(record, detail=True)
    data["created"] = created
    return ok(data)


@endpoint()
def usage_batch(request):
    """批量上报用量（整体事务；重复幂等键不报错）。"""
    subscription = get_subscription(
        int_param(request, "subscription_id", required=True, minimum=1),
        request.user, write=True)
    rows = list_param(request, "rows", required=True, max_len=500)
    prepared = []
    meter_cache = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条用量格式不正确")
        row = dict(row)
        if not (row.get("meter") or row.get("meter_code")) and row.get("meter_id"):
            meter_id = row.get("meter_id")
            if meter_id not in meter_cache:
                meter = Meter.objects.filter(pk=meter_id).first()
                if meter is None:
                    raise ValueError(f"第 {index} 条计量项不存在")
                meter_cache[meter_id] = meter
            row["meter"] = meter_cache[meter_id].code
        prepared.append(row)
    result = services.batch_report_usage(subscription.owner, subscription, prepared)
    # 数量统一转字符串：JSON 里 Decimal 会被 DRF 降级成 float，整数/小数形态不一致
    items = [{
        "id": row["id"],
        "meter": row["meter"],
        "quantity": services.unit_str(row["quantity"]),
        "created": row["created"],
    } for row in result["items"]]
    return ok({"items": items, "count": result["count"], "created": result["created"]})


@endpoint(("GET",))
def usage_list(request):
    """用量流水列表（订阅/计量项/是否已开票/时间范围 + 分页）。"""
    qs = services.visible(UsageRecord.objects.select_related("meter", "subscription"),
                          request.user)
    qs = filter_by(qs, request, "subscription_id")
    qs = filter_by(qs, request, "meter_id")
    invoiced = p(request, "invoiced")
    if invoiced not in (None, ""):
        qs = qs.filter(invoiced=bool_param(request, "invoiced"))
    start = date_param(request, "start")
    end = date_param(request, "end")
    if start:
        begin, _ = services.period_datetimes(start, services.add_period(start, "one_time"))
        qs = qs.filter(occurred_at__gte=begin)
    if end:
        _, finish = services.period_datetimes(end, services.add_period(end, "one_time"))
        qs = qs.filter(occurred_at__lt=finish)
    qs = apply_search(qs, request, ["source", "idempotency_key"], status_field="")
    return paginate(qs.order_by("-occurred_at", "-id"), request, serializers.usage_dict)


@endpoint(("GET",))
def usage_summary(request):
    """账期用量汇总：默认为订阅当前周期，可指定 period_start/period_end。"""
    subscription = get_subscription(
        int_param(request, "subscription_id", required=True, minimum=1), request.user)
    start = date_param(request, "period_start") or subscription.current_period_start
    end = date_param(request, "period_end") or (
        services.add_period(start, subscription.plan.billing_period)
        if start else subscription.current_period_end)
    if not start or not end:
        raise ValueError("订阅缺少账期，无法汇总用量")
    if end <= start:
        raise ValueError("period_end 必须晚于 period_start")
    return ok(_usage_summary_dict(services.usage_summary(subscription, start, end)))
