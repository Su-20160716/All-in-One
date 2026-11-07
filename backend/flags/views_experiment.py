# -*- coding: utf-8 -*-
"""功能开关 · 实验与指标接口（13 个）。

实验生命周期：draft → running ⇄ paused → concluded。开始/暂停/结束都写
审计并清评估缓存，因为 running 实验会改变开关的评估结果。
"""
from django.db import IntegrityError, transaction

from devtools.common import endpoint, ok, opt_str, p, req_str

from flags import services
from flags.models import (
    EXPERIMENT_STATUS,
    METRIC_DIRECTIONS,
    METRIC_TYPES,
    Experiment,
    ExperimentMetric,
    Exposure,
)
from flags.views_common import (
    after_write,
    apply_search,
    bool_param,
    context_param,
    filter_int,
    get_experiment,
    get_flag,
    get_metric,
    int_param,
    json_param,
    paginate,
    str_param,
)


def _experiment_id(request, write=False):
    experiment_id = int_param(request, "experiment_id", None, minimum=1)
    if not experiment_id:
        experiment_id = int_param(request, "id", None, minimum=1)
    if not experiment_id:
        raise ValueError("缺少必填参数: experiment_id")
    return get_experiment(experiment_id, request.user, write=write)


def _user_key(request):
    value = p(request, "user_key")
    if value in (None, ""):
        value = p(request, "user") or p(request, "user_id")
    text = str(value or "").strip()
    if not text:
        raise ValueError("缺少必填参数: user_key")
    if len(text) > 200:
        raise ValueError("user_key 最长为 200 字符")
    return text


# =====================================================================
# 实验
# =====================================================================


@endpoint(("GET", "POST"))
def experiments(request):
    """实验列表（GET）或创建实验（POST）。"""
    if request.method == "POST":
        flag_id = int_param(request, "flag_id", None, minimum=1)
        if not flag_id:
            raise ValueError("缺少必填参数: flag_id")
        flag = get_flag(flag_id, request.user, write=True)
        name = req_str(request, "name")[:200]
        status = services.parse_choice(
            p(request, "status"), ("draft", "running", "paused"), "实验状态", "draft"
        )
        metric = opt_str(request, "primary_metric").strip()[:120]
        try:
            with transaction.atomic():
                experiment = Experiment.objects.create(
                    owner=request.user,
                    flag=flag,
                    name=name,
                    hypothesis=opt_str(request, "hypothesis"),
                    status=status,
                    start_at=services.parse_datetime(
                        p(request, "start_at"), "开始时间",
                        services.now() if status in ("running", "paused") else None,
                    ),
                    end_at=services.parse_datetime(p(request, "end_at"), "结束时间"),
                    primary_metric=metric,
                    min_sample_size=int_param(
                        request, "min_sample_size", 100, minimum=1, maximum=1000000
                    ),
                    description=opt_str(request, "description"),
                )
                metric_name = metric or "conversion"
                ExperimentMetric.objects.create(
                    owner=request.user,
                    experiment=experiment,
                    name=metric_name,
                    metric_type="conversion",
                    direction="increase",
                )
                experiment.primary_metric = metric_name
                experiment.save(update_fields=["primary_metric", "updated_at"])
        except IntegrityError:
            raise ValueError("同一开关下实验名称已存在")
        after_write(request.user, experiment, "experiment.create",
                    after={"name": name, "status": status}, project=flag.project)
        return ok(experiment.as_dict())

    qs = services.visible(Experiment.objects.select_related("flag"), request.user)
    qs = filter_int(qs, request, "flag_id")
    qs = filter_int(qs, request, "project_id", "flag__project_id")
    qs = apply_search(qs, request, ["name", "hypothesis", "primary_metric"])
    return paginate(qs.order_by("-created_at", "-id"), request, lambda obj: obj.as_dict())


@endpoint(("GET",))
def experiment_detail(request, pk):
    """实验详情（含指标、进度与分组样本）。"""
    experiment = get_experiment(pk, request.user)
    data = experiment.as_dict()
    data["metrics"] = [item.as_dict() for item in experiment.metrics.all().order_by("id")]
    data["progress"] = services.experiment_progress(experiment)
    data["assignment_count"] = experiment.assignments.count()
    data["exposure_count"] = experiment.exposures.count()
    return ok(data)


@endpoint()
def experiment_update(request):
    """更新实验名称/假设/主指标/最小样本量/时间窗口。"""
    experiment = _experiment_id(request, write=True)
    before = experiment.as_dict()
    if p(request, "name") not in (None, ""):
        experiment.name = req_str(request, "name")[:200]
    if p(request, "hypothesis") not in (None, ""):
        experiment.hypothesis = opt_str(request, "hypothesis")
    if p(request, "description") not in (None, ""):
        experiment.description = opt_str(request, "description")
    if p(request, "primary_metric") not in (None, ""):
        experiment.primary_metric = opt_str(request, "primary_metric")[:120]
    if p(request, "min_sample_size") not in (None, ""):
        experiment.min_sample_size = int_param(
            request, "min_sample_size", experiment.min_sample_size,
            minimum=1, maximum=1000000,
        )
    for field, label in (("start_at", "开始时间"), ("end_at", "结束时间")):
        if p(request, field) not in (None, ""):
            setattr(experiment, field, services.parse_datetime(p(request, field), label))
    if experiment.start_at and experiment.end_at and experiment.end_at <= experiment.start_at:
        raise ValueError("结束时间必须晚于开始时间")
    try:
        # 保存点回滚，避免唯一约束错误破坏外层事务
        with transaction.atomic():
            experiment.save()
    except IntegrityError:
        raise ValueError("同一开关下实验名称已存在")
    after_write(request.user, experiment, "experiment.update", before=before,
                after=experiment.as_dict(), project=experiment.flag.project)
    return ok(experiment.as_dict())


@endpoint()
def experiment_start(request):
    """启动实验（draft/paused → running），立即影响开关评估。"""
    experiment = _experiment_id(request, write=True)
    if experiment.status == "running":
        raise ValueError("实验已在进行中")
    if experiment.status == "concluded":
        raise ValueError("实验已结束，不能重新启动")
    before = {"status": experiment.status}
    experiment.status = "running"
    if experiment.start_at is None:
        experiment.start_at = services.now()
    experiment.save(update_fields=["status", "start_at", "updated_at"])
    services.invalidate_flag(experiment.flag_id)
    after_write(request.user, experiment, "experiment.start", before=before,
                after={"status": "running"}, project=experiment.flag.project)
    return ok(experiment.as_dict())


@endpoint()
def experiment_pause(request):
    """暂停实验（running → paused），暂停期间评估回落到灰度/默认。"""
    experiment = _experiment_id(request, write=True)
    if experiment.status != "running":
        raise ValueError(f"当前状态 {experiment.status} 不能暂停")
    experiment.status = "paused"
    experiment.save(update_fields=["status", "updated_at"])
    services.invalidate_flag(experiment.flag_id)
    after_write(request.user, experiment, "experiment.pause",
                before={"status": "running"}, after={"status": "paused"},
                project=experiment.flag.project)
    return ok(experiment.as_dict())


@endpoint()
def experiment_conclude(request):
    """结束实验并记录结束时间（之后结果只读）。"""
    experiment = _experiment_id(request, write=True)
    if experiment.status == "concluded":
        raise ValueError("实验已结束")
    if experiment.status == "draft":
        raise ValueError("草稿实验尚未开始，不能直接结束")
    before = {"status": experiment.status}
    experiment.status = "concluded"
    experiment.end_at = services.parse_datetime(
        p(request, "end_at"), "结束时间", services.now()
    )
    experiment.save(update_fields=["status", "end_at", "updated_at"])
    services.invalidate_flag(experiment.flag_id)
    after_write(request.user, experiment, "experiment.conclude", before=before,
                after={"status": "concluded"}, project=experiment.flag.project)
    result = services.experiment_results(experiment)
    result["metrics"] = [item.as_dict() for item in experiment.metrics.all().order_by("id")]
    result["progress"] = services.experiment_progress(experiment)
    return ok(result)


@endpoint(("GET",))
def experiment_results(request, pk):
    """实验结果：分组转化率、lift、卡方显著性、样本量校验与胜出组。"""
    experiment = get_experiment(pk, request.user)
    data = services.experiment_results(experiment)
    data["metrics"] = [item.as_dict() for item in experiment.metrics.all().order_by("id")]
    data["progress"] = services.experiment_progress(experiment)
    return ok(data)


@endpoint(("GET",))
def experiment_progress(request, pk):
    """实验进度：总曝光、目标样本量与各组缺口。"""
    experiment = get_experiment(pk, request.user)
    return ok(services.experiment_progress(experiment))


@endpoint()
def experiment_exposure_report(request):
    """曝光上报（幂等）：实验 + 用户键唯一，重复上报只合并上下文。"""
    experiment = _experiment_id(request, write=False)
    user_key = _user_key(request)
    variant_key = opt_str(request, "variant_key").strip()
    context = context_param(request)
    if not isinstance(context, dict):
        raise ValueError("context 必须是对象")
    exposure, created = services.record_exposure(
        experiment, user_key, variant_key, context
    )
    assignment = experiment.assignments.filter(user_key=user_key).first()
    return ok({
        "exposure": exposure.as_dict(),
        "created": created,
        "idempotent": not created,
        "assignment": assignment.as_dict() if assignment else None,
    })


@endpoint(("GET",))
def experiment_exposures(request, pk):
    """曝光统计：分组数量/占比/首末时间，并附最近曝光明细。"""
    experiment = get_experiment(pk, request.user)
    data = services.exposure_stats(experiment)
    qs = experiment.exposures.all().order_by("-exposed_at", "-id")
    from flags.views_common import page_params

    page, size = page_params(request)
    total = qs.count()
    start = (page - 1) * size
    data.update({
        "items": [item.as_dict() for item in qs[start:start + size]],
        "count": total,
        "page": page,
        "page_size": size,
    })
    return ok(data)


# =====================================================================
# 实验指标
# =====================================================================


@endpoint(("GET", "POST"))
def experiment_metrics(request):
    """实验指标列表（GET）或新增指标（POST）。"""
    experiment = _experiment_id(request, write=request.method == "POST")
    if request.method == "POST":
        name = req_str(request, "name")[:120]
        metric_type = services.parse_choice(
            p(request, "metric_type"), METRIC_TYPES, "指标类型", "conversion"
        )
        direction = services.parse_choice(
            p(request, "direction"), METRIC_DIRECTIONS, "优化方向", "increase"
        )
        try:
            # 内层原子块把唯一约束失败限制在保存点内，外层事务仍可继续
            with transaction.atomic():
                metric = ExperimentMetric.objects.create(
                    owner=request.user,
                    experiment=experiment,
                    name=name,
                    metric_type=metric_type,
                    unit=opt_str(request, "unit")[:40],
                    direction=direction,
                    note=opt_str(request, "note")[:200],
                )
        except IntegrityError:
            raise ValueError("该实验下指标名称已存在")
        if bool_param(request, "set_primary", False):
            experiment.primary_metric = metric.name
            experiment.save(update_fields=["primary_metric", "updated_at"])
        after_write(request.user, metric, "experiment_metric.create",
                    after=metric.as_dict(), project=experiment.flag.project)
        return ok(metric.as_dict())

    qs = experiment.metrics.all().order_by("id")
    qs = apply_search(qs, request, ["name", "unit", "note"], status_field=None)
    return paginate(qs, request, lambda obj: obj.as_dict())


@endpoint()
def experiment_metric_update(request):
    """更新实验指标名称/类型/单位/方向。"""
    metric_id = int_param(request, "metric_id", None, minimum=1)
    if not metric_id:
        metric_id = int_param(request, "id", None, minimum=1)
    if not metric_id:
        raise ValueError("缺少必填参数: metric_id")
    metric = get_metric(metric_id, request.user, write=True)
    before = metric.as_dict()
    if p(request, "name") not in (None, ""):
        metric.name = req_str(request, "name")[:120]
    if p(request, "metric_type") not in (None, ""):
        metric.metric_type = services.parse_choice(
            p(request, "metric_type"), METRIC_TYPES, "指标类型", metric.metric_type
        )
    if p(request, "direction") not in (None, ""):
        metric.direction = services.parse_choice(
            p(request, "direction"), METRIC_DIRECTIONS, "优化方向", metric.direction
        )
    if p(request, "unit") not in (None, ""):
        metric.unit = opt_str(request, "unit")[:40]
    if p(request, "note") not in (None, ""):
        metric.note = opt_str(request, "note")[:200]
    try:
        # 保存点回滚，避免唯一约束错误破坏外层事务
        with transaction.atomic():
            metric.save()
    except IntegrityError:
        raise ValueError("该实验下指标名称已存在")
    after_write(request.user, metric, "experiment_metric.update", before=before,
                after=metric.as_dict(), project=metric.experiment.flag.project)
    return ok(metric.as_dict())


@endpoint()
def experiment_metric_delete(request):
    """删除实验指标（主指标被删除时回退到 conversion）。"""
    metric_id = int_param(request, "metric_id", None, minimum=1)
    if not metric_id:
        raise ValueError("缺少必填参数: metric_id")
    metric = get_metric(metric_id, request.user, write=True)
    experiment = metric.experiment
    snapshot = metric.as_dict()
    with transaction.atomic():
        services.record_audit(
            request.user, metric, "experiment_metric.delete", before=snapshot,
            after={"deleted": True}, project=experiment.flag.project,
        )
        metric.delete()
        if experiment.primary_metric == snapshot.get("name"):
            fallback = experiment.metrics.order_by("id").first()
            experiment.primary_metric = fallback.name if fallback else "conversion"
            experiment.save(update_fields=["primary_metric", "updated_at"])
    return ok({
        "deleted": True,
        "id": snapshot["id"],
        "primary_metric": experiment.primary_metric,
    })
