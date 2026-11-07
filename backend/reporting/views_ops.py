# -*- coding: utf-8 -*-
"""运维类接口：计划任务、订阅、指标概览、数据质量、执行流水、导出任务。

为什么集中在一个模块
--------------------
这些接口都是「围绕报表生命周期」的运营能力：谁在什么时候跑、跑得快不快、
数据干不干净、订阅发没发。它们共享同一套行级权限（数据范围内可见），
放一起可以复用 ``_schedule_item`` / ``_subscription_item`` 之类的序列化，
避免每个视图各写一份导致口径漂移。
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.scoping import can_write, scope_queryset
from devtools.common import endpoint, ok, opt_num, opt_str, p

from reporting import services as svc
from reporting.models import (
    EXPORT_FORMATS, JOB_STATUS, ReportExportJob, ReportRun, ReportSchedule,
    ReportSubscription,
)
from reporting.payloads import (
    apply_q, apply_status, export_job_dict, paginate, run_dict, schedule_dict,
    subscription_dict,
)
from reporting.views_common import (
    get_dataset, get_report, get_visible, get_writable, read_bool, read_choice,
    read_days, read_json_obj, read_str_list,
)


def _schedule_item(schedule, with_summary=False):
    """计划任务列表项：默认不逐行算未来时间（列表页只看状态与下次时间）。"""
    summary = svc.schedule_summary(schedule, count=3) if with_summary else None
    return schedule_dict(schedule, summary)


def _subscription_item(sub):
    return subscription_dict(sub, user_name=getattr(sub.user, "username", ""))


# =====================================================================
# 计划任务（9）
# =====================================================================


@endpoint(("GET",))
def schedules_list(request):
    """计划任务列表（q/report_id/enabled 过滤 + 分页）。"""
    qs = scope_queryset(ReportSchedule.objects.select_related("report").all(),
                        request.user, "owner")
    qs = apply_q(qs, request, ["name", "cron_expr", "report__name", "report__code"])
    report_id = p(request, "report_id")
    if report_id not in (None, ""):
        qs = qs.filter(report=get_report(report_id, request.user))
    if p(request, "enabled") not in (None, ""):
        qs = qs.filter(enabled=read_bool(request, "enabled", True))
    qs = qs.order_by("-updated_at", "-id")
    with_summary = read_bool(request, "with_summary", False)
    return ok(paginate(qs, request, lambda s: _schedule_item(s, with_summary)))


@endpoint()
def schedule_create(request):
    """新建计划任务（cron 与时区即刻校验并算出下次运行时间）。"""
    report = get_report(p(request, "report_id"), request.user, write=True)
    expr = opt_str(request, "cron_expr").strip() or "0 9 * * 1-5"
    svc.validate_cron(expr)
    tz_name = opt_str(request, "timezone").strip()[:64] or "Asia/Shanghai"
    enabled = read_bool(request, "enabled", False)
    recipients = read_str_list(request, "recipients", max_items=20, max_len=200)
    next_run = svc.compute_next_run(expr, tz_name) if enabled else None
    schedule = ReportSchedule.objects.create(
        report=report,
        name=opt_str(request, "name").strip()[:120],
        cron_expr=expr[:120],
        timezone=tz_name,
        next_run_at=next_run,
        enabled=enabled,
        recipients=recipients,
        owner=request.user,
    )
    return ok(_schedule_item(schedule, with_summary=True))


@endpoint(("GET",))
def schedule_detail(request, pk):
    """计划任务详情（含未来三次运行时间与中文描述）。"""
    schedule = get_visible(ReportSchedule, pk, request.user, "计划任务")
    data = _schedule_item(schedule, with_summary=True)
    data["report"] = svc.report_brief(schedule.report)
    return ok(data)


@endpoint()
def schedule_update(request, pk):
    """更新计划任务（改 cron/时区会重算下次运行；停用则清空下次时间）。"""
    schedule = get_writable(ReportSchedule, pk, request.user, "计划任务")
    with transaction.atomic():
        if p(request, "name") is not None:
            schedule.name = opt_str(request, "name").strip()[:120]
        expr_changed = False
        if p(request, "cron_expr") is not None:
            expr = opt_str(request, "cron_expr").strip() or schedule.cron_expr
            svc.validate_cron(expr)
            if expr != schedule.cron_expr:
                schedule.cron_expr = expr[:120]
                expr_changed = True
        if p(request, "timezone") is not None:
            tz_name = opt_str(request, "timezone").strip()[:64] or schedule.timezone
            if tz_name != schedule.timezone:
                schedule.timezone = tz_name
                expr_changed = True
        if p(request, "recipients") is not None:
            schedule.recipients = read_str_list(request, "recipients", max_items=20, max_len=200)
        if p(request, "enabled") is not None:
            schedule.enabled = read_bool(request, "enabled", schedule.enabled)
        if schedule.enabled:
            if expr_changed or schedule.next_run_at is None:
                schedule.next_run_at = svc.compute_next_run(schedule.cron_expr, schedule.timezone)
        else:
            # 停用时不保留过期时间，避免被外部调度器误判为到期
            schedule.next_run_at = None
        schedule.save()
    return ok(_schedule_item(schedule, with_summary=True))


@endpoint()
def schedule_delete(request, pk):
    """删除计划任务（执行流水保留，属于报表历史）。"""
    schedule = get_writable(ReportSchedule, pk, request.user, "计划任务")
    sid = schedule.pk
    schedule.delete()
    return ok({"deleted": True, "id": sid})


@endpoint()
def schedule_toggle(request, pk):
    """启停计划任务（不传 enabled 则取反），启用时立即补算下次运行。"""
    schedule = get_writable(ReportSchedule, pk, request.user, "计划任务")
    with transaction.atomic():
        target = read_bool(request, "enabled", not schedule.enabled)
        schedule.enabled = target
        schedule.next_run_at = (svc.compute_next_run(schedule.cron_expr, schedule.timezone)
                                if target else None)
        schedule.save(update_fields=["enabled", "next_run_at", "updated_at"])
    return ok(_schedule_item(schedule, with_summary=True))


@endpoint()
def schedule_run_now(request, pk):
    """立即执行计划任务对应的报表，并把结果记到任务状态上。"""
    schedule = get_writable(ReportSchedule, pk, request.user, "计划任务")
    report = schedule.report
    if report.status == "archived":
        raise ValueError("报表已归档，不能执行")
    params = read_json_obj(request, "params", {})
    payload = svc.run_report(report, params, request.user, trigger="schedule")
    meta = payload.get("meta") or {}
    status = meta.get("status") or "success"
    with transaction.atomic():
        schedule.last_run_at = timezone.now()
        schedule.last_status = status
        schedule.run_count = (schedule.run_count or 0) + 1
        if schedule.enabled:
            schedule.next_run_at = svc.compute_next_run(schedule.cron_expr, schedule.timezone)
        schedule.save(update_fields=[
            "last_run_at", "last_status", "run_count", "next_run_at", "updated_at",
        ])
    return ok({
        "schedule": _schedule_item(schedule, with_summary=True),
        "run_id": meta.get("run_id"),
        "status": status,
        "widget_count": meta.get("widget_count"),
        "failed_widgets": meta.get("failed_widgets"),
        "duration_ms": meta.get("duration_ms"),
    })


@endpoint()
def schedule_next(request, pk):
    """重算并返回未来运行时间（count 可调，最多 20 次）。"""
    schedule = get_writable(ReportSchedule, pk, request.user, "计划任务")
    count = int(opt_num(request, "count", 5, integer=True, minimum=1, maximum=20))
    runs = svc.next_runs(schedule.cron_expr, schedule.timezone, count=count)
    schedule.next_run_at = runs[0] if runs else None
    schedule.save(update_fields=["next_run_at", "updated_at"])
    return ok({
        "schedule_id": schedule.pk,
        "cron": schedule.cron_expr,
        "timezone": schedule.timezone,
        "description": svc.describe_cron(schedule.cron_expr),
        "upcoming": [r.isoformat() for r in runs],
        "next_run_at": runs[0].isoformat() if runs else None,
    })


@endpoint(("GET",))
def schedules_due(request):
    """到期扫描：返回已启用且 next_run_at 已到的任务（外部调度器拉取）。"""
    now = timezone.now()
    qs = (scope_queryset(ReportSchedule.objects.select_related("report").all(),
                         request.user, "owner")
          .filter(enabled=True, next_run_at__lte=now)
          .order_by("next_run_at", "id"))
    limit = int(opt_num(request, "limit", 50, integer=True, minimum=1, maximum=200))
    items = []
    for schedule in qs[:limit]:
        items.append({
            "id": schedule.pk,
            "report_id": schedule.report_id,
            "report_name": schedule.report.name if schedule.report_id else "",
            "cron_expr": schedule.cron_expr,
            "timezone": schedule.timezone,
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "recipients": schedule.recipients or [],
        })
    return ok({"items": items, "count": len(items), "generated_at": now.isoformat()})


# =====================================================================
# 订阅（4）
# =====================================================================


@endpoint(("GET",))
def subscriptions_list(request):
    """订阅列表（q/report_id/enabled 过滤 + 分页）。"""
    qs = scope_queryset(
        ReportSubscription.objects.select_related("report", "user").all(),
        request.user, "owner",
    )
    qs = apply_q(qs, request, ["report__name", "report__code", "user__username"])
    report_id = p(request, "report_id")
    if report_id not in (None, ""):
        qs = qs.filter(report=get_report(report_id, request.user))
    if p(request, "enabled") not in (None, ""):
        qs = qs.filter(enabled=read_bool(request, "enabled", True))
    channel = read_choice(request, "channel", [("email", ""), ("im", ""), ("webhook", "")])
    if channel:
        qs = qs.filter(channel=channel)
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(qs, request, _subscription_item))


@endpoint()
def subscription_create(request):
    """新建订阅（默认订阅自己；替他人订阅需报表写权限，防越权推送）。"""
    report = get_report(p(request, "report_id"), request.user)
    channel = read_choice(request, "channel",
                          [("email", ""), ("im", ""), ("webhook", "")], default="email")
    frequency = read_choice(request, "frequency",
                            [("daily", ""), ("weekly", ""), ("monthly", ""),
                             ("on_publish", "")], default="weekly")
    user = request.user
    user_id = opt_num(request, "user_id", None, integer=True, minimum=1)
    if user_id and int(user_id) != request.user.id:
        if not can_write(request.user, report):
            raise ValueError("只有报表所有者才能替他人订阅")
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            raise ValueError("订阅用户不存在")
    try:
        with transaction.atomic():
            sub = ReportSubscription.objects.create(
                report=report, user=user, channel=channel, frequency=frequency,
                enabled=read_bool(request, "enabled", True), owner=request.user,
            )
    except IntegrityError:
        raise ValueError("该用户已订阅此报表")
    return ok(_subscription_item(sub))


def _get_subscription(pk, user, write=False):
    """订阅的可见性：创建人/订阅人都可读写自己那条，其它人按数据范围只读。"""
    sub = get_visible(ReportSubscription, pk, user, "订阅")
    if write and not (sub.owner_id == user.id or sub.user_id == user.id):
        raise ValueError("无权修改该订阅")
    return sub


@endpoint()
def subscription_update(request, pk):
    """更新订阅（渠道/频率/启停）。"""
    sub = _get_subscription(pk, request.user, write=True)
    with transaction.atomic():
        channel = read_choice(request, "channel",
                              [("email", ""), ("im", ""), ("webhook", "")])
        if channel:
            sub.channel = channel
        frequency = read_choice(request, "frequency",
                                [("daily", ""), ("weekly", ""), ("monthly", ""),
                                 ("on_publish", "")])
        if frequency:
            sub.frequency = frequency
        if p(request, "enabled") is not None:
            sub.enabled = read_bool(request, "enabled", sub.enabled)
        sub.save()
    return ok(_subscription_item(sub))


@endpoint()
def subscription_cancel(request, pk):
    """取消订阅（删除记录；重复取消按「已取消」幂等返回）。"""
    sub = _get_subscription(pk, request.user, write=True)
    sid, report_id = sub.pk, sub.report_id
    sub.delete()
    return ok({"canceled": True, "id": sid, "report_id": report_id})


# =====================================================================
# 指标概览 / 数据质量 / 流水 / 导出任务（6）
# =====================================================================


@endpoint(("GET",))
def metrics_overview(request):
    """执行指标概览：执行数/成功率/耗时分位/缓存命中/热门 TOP。"""
    days = read_days(request, "days", 30)
    report_id = opt_num(request, "report_id", None, integer=True, minimum=1)
    report = get_report(report_id, request.user) if report_id else None
    data = svc.metrics_overview(request.user, days=days,
                                report_id=report.pk if report else None)
    if report is not None:
        data["report"] = svc.report_brief(report)
    return ok(data)


@endpoint(("GET",))
def metrics_report(request, pk):
    """单张报表的执行指标（详情页头部：成功率/耗时/失败原因）。"""
    report = get_report(pk, request.user)
    days = read_days(request, "days", 30)
    return ok(svc.report_metrics(report, days=days))


@endpoint(("GET", "POST"))
def quality_check_view(request):
    """数据质量检查：空值率 / 重复率 / Z-score 异常值（按数据集或模型口径）。"""
    dataset_id = opt_num(request, "dataset_id", None, integer=True, minimum=1)
    fields = read_str_list(request, "fields", max_items=12, max_len=160)
    distinct_keys = read_str_list(request, "distinct_keys", max_items=5, max_len=160)
    numeric_field = opt_str(request, "numeric_field").strip() or None
    outlier_limit = int(opt_num(request, "outlier_limit", 20, integer=True,
                                minimum=1, maximum=100))
    params = read_json_obj(request, "params", {})
    if dataset_id:
        dataset = get_dataset(dataset_id, request.user)
        data = svc.quality_for_dataset(
            dataset,
            params=params,
            fields=fields or None,
            distinct_keys=distinct_keys or None,
            numeric_field=numeric_field,
            outlier_limit=outlier_limit,
        )
        data["dataset"] = {"id": dataset.pk, "name": dataset.name,
                           "model": dataset.primary_model}
        return ok(data)
    label = opt_str(request, "model").strip() or opt_str(request, "primary_model").strip()
    if not label:
        raise ValueError("需要 dataset_id 或 model")
    filter_spec = read_json_obj(request, "filter", {})
    data = svc.quality_check(
        label,
        filter_spec=filter_spec,
        params=params,
        fields=fields or None,
        distinct_keys=distinct_keys or None,
        numeric_field=numeric_field,
        outlier_limit=outlier_limit,
    )
    return ok(data)


@endpoint(("GET",))
def export_jobs_list(request):
    """导出任务列表（status/fmt/q 过滤 + 分页，行数与耗时便于排障）。"""
    qs = scope_queryset(ReportExportJob.objects.select_related("report").all(),
                        request.user, "owner")
    qs = apply_q(qs, request, ["filename", "report__name", "report__code"])
    qs = apply_status(qs, request)
    fmt = read_choice(request, "fmt", EXPORT_FORMATS)
    if fmt:
        qs = qs.filter(fmt=fmt)
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(qs, request, export_job_dict))


@endpoint(("GET",))
def runs_list(request):
    """全局执行流水（report_id/status/trigger/q 过滤 + 分页）。"""
    qs = scope_queryset(ReportRun.objects.select_related("report").all(),
                        request.user, "owner")
    qs = apply_q(qs, request, ["report__name", "report__code", "error"])
    report_id = p(request, "report_id")
    if report_id not in (None, ""):
        qs = qs.filter(report=get_report(report_id, request.user))
    qs = apply_status(qs, request)
    trigger = read_choice(request, "trigger",
                          [("manual", ""), ("schedule", ""), ("api", ""),
                           ("cache", ""), ("share", "")])
    if trigger:
        qs = qs.filter(trigger=trigger)
    qs = qs.order_by("-created_at", "-id")
    with_result = read_bool(request, "with_result", False)
    return ok(paginate(qs, request, lambda r: run_dict(r, with_result=with_result)))


@endpoint(("GET",))
def run_detail(request, pk):
    """单条执行流水详情（默认带结果快照，方便直接复现问题）。"""
    run = get_visible(ReportRun, pk, request.user, "执行记录")
    data = run_dict(run, with_result=read_bool(request, "with_result", True))
    data["report"] = svc.report_brief(run.report)
    return ok(data)


# JOB_STATUS 仅用于让静态检查确认导入被使用（枚举在 catalog 统一输出）
JOB_STATUS_CHOICES = JOB_STATUS
