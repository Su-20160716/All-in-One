# -*- coding: utf-8 -*-
"""可观测性 · 指标面：指标定义(4) + 指标点(6) = 10 个接口。

上报接口模拟真实 agent 的行为：agent 只认识「服务 + 指标名 + 值 + 标签」，
不关心指标定义 id；因此这里两种寻址都支持（metric_id 直连、service+name
反查），并允许 agent 首次上报时自动注册指标定义（auto_register），避免
「上监控前要先手工建指标」的落地阻力。

查询侧刻意区分两种口径：
- `/metrics/points/query/`：按聚合口径压成单值 + 分桶序列，用于画图；
- `/metrics/points/percentiles/`：原始样本分位，用于定容量与排障。
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p, req_str

from observability import services
from observability.common import (
    bool_param,
    dict_param,
    filter_int,
    get_metric_def,
    int_param,
    list_param,
    metric_def_dict,
    paginate,
    point_dict,
    str_param,
    window_params,
)
from observability.models import METRIC_TYPES, MetricDef, MetricPoint, Service

# 单次批量上报的上限：超过就走多次请求，避免一个请求长时间占用 worker
MAX_BATCH_POINTS = 2000


def _resolve_metric(request, write=False):
    """按 metric_id 或 service_id+metric 定位指标定义（两种寻址方式）。"""
    metric_id = int_param(request, "metric_id")
    if metric_id:
        return get_metric_def(metric_id, request.user, write=write)
    service_id = int_param(request, "service_id")
    name = opt_str(request, "metric").strip()
    if not service_id or not name:
        raise ValueError("请通过 metric_id 或 service_id+metric 指定指标")
    service = services.get_visible(Service, service_id, request.user, "服务不存在")
    if write:
        services.ensure_writable(service, request.user)
    metric = MetricDef.objects.filter(service=service, name=name).first()
    if metric is None:
        raise ValueError(f"指标不存在: {name}")
    return metric


def _metric_for_report(request):
    """上报场景的指标寻址：支持 auto_register 自动注册缺失的指标定义。"""
    metric_id = int_param(request, "metric_id")
    if metric_id:
        return get_metric_def(metric_id, request.user, write=True)
    service_id = int_param(request, "service_id", required=True)
    name = req_str(request, "metric", max_len=120).strip()
    # 上报是写操作：直接用写权限取服务，否则越权者会先收到「无权查看」
    # 这种读口径的提示，与实际动作（写入指标点）不一致。
    service = services.get_writable(Service, service_id, request.user, "服务不存在")
    metric = MetricDef.objects.filter(service=service, name=name).first()
    if metric is not None:
        return metric
    if not bool_param(request, "auto_register", False):
        raise ValueError(f"指标不存在: {name}（可传 auto_register=true 自动注册）")
    metric_type = opt_str(request, "metric_type", "gauge").strip()
    if metric_type not in METRIC_TYPES:
        raise ValueError(f"指标类型必须是 {'/'.join(METRIC_TYPES)} 之一")
    return MetricDef.objects.create(
        owner=request.user,
        service=service,
        name=name,
        metric_type=metric_type,
        unit=opt_str(request, "unit")[:20],
        description=opt_str(request, "description")[:300],
    )


def _point_timestamp(request, key="timestamp", default=None):
    """指标点时间：缺省用当前时间；显式传入则按 ISO 解析（非法 400）。"""
    raw = p(request, key)
    if raw in (None, ""):
        return default or timezone.now()
    return services.parse_datetime(raw, "时间")


def _clamp_future(timestamp, now=None):
    """把晚于接收时刻的时间夹到当前时刻。

    agent 的时钟漂移会产生「未来」的指标点，这些点不会落进任何
    [since, until) 查询窗口，表现为「刚上报却查不到」；入库时夹到当前
    时刻既保留了数值与标签，又不会让未来数据污染 latest/趋势。
    """
    now = now or timezone.now()
    return timestamp if timestamp <= now else now


def _labels(request, key="labels"):
    """标签：必须是对象；字符串标签值统一转字符串，避免下游按标签分组时报错。"""
    value = p(request, key)
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是对象")
    return {str(k): (v if isinstance(v, (int, float, bool)) else str(v))
            for k, v in value.items()}


# =====================================================================
# 指标定义（4）
# =====================================================================


@endpoint(("GET",))
def metric_list(request):
    """指标定义列表：按服务/名称/类型过滤。"""
    qs = services.visible(MetricDef.objects.select_related("service").all(), request.user)
    qs = filter_int(qs, request, "service_id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
    metric_type = opt_str(request, "metric_type", opt_str(request, "status")).strip()
    if metric_type:
        if metric_type not in METRIC_TYPES:
            raise ValueError(f"指标类型必须是 {'/'.join(METRIC_TYPES)} 之一")
        qs = qs.filter(metric_type=metric_type)
    return paginate(qs.order_by("service_id", "name"), request, metric_def_dict)


@endpoint()
def metric_create(request):
    """创建指标定义：同一服务下指标名唯一。"""
    service = services.get_visible(Service, int_param(request, "service_id", required=True),
                                   request.user, "服务不存在")
    services.ensure_writable(service, request.user)
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("指标名不能为空")
    if MetricDef.objects.filter(service=service, name=name).exists():
        raise ValueError("该服务下已存在同名指标")
    metric_type = opt_str(request, "metric_type", "gauge").strip()
    if metric_type not in METRIC_TYPES:
        raise ValueError(f"指标类型必须是 {'/'.join(METRIC_TYPES)} 之一")
    obj = MetricDef.objects.create(
        owner=request.user,
        service=service,
        name=name,
        metric_type=metric_type,
        unit=opt_str(request, "unit")[:20],
        labels=dict_param(request, "labels"),
        description=opt_str(request, "description")[:300],
        retention_days=int_param(request, "retention_days", 30, minimum=1, maximum=3650),
    )
    return ok(metric_def_dict(obj))


@endpoint()
def metric_update(request, pk=None):
    """更新指标定义：名称/类型/单位/标签约定/保留天数。"""
    obj = get_metric_def(pk or int_param(request, "id", required=True),
                         request.user, write=True)
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("指标名不能为空")
        if MetricDef.objects.filter(service_id=obj.service_id, name=name).exclude(pk=obj.pk).exists():
            raise ValueError("该服务下已存在同名指标")
        obj.name = name[:120]
    if p(request, "metric_type") is not None:
        metric_type = opt_str(request, "metric_type", obj.metric_type).strip()
        if metric_type not in METRIC_TYPES:
            raise ValueError(f"指标类型必须是 {'/'.join(METRIC_TYPES)} 之一")
        obj.metric_type = metric_type
    if p(request, "unit") is not None:
        obj.unit = opt_str(request, "unit")[:20]
    if p(request, "labels") is not None:
        obj.labels = dict_param(request, "labels")
    if p(request, "description") is not None:
        obj.description = opt_str(request, "description")[:300]
    if p(request, "retention_days") is not None:
        obj.retention_days = int_param(request, "retention_days", obj.retention_days,
                                       minimum=1, maximum=3650)
    obj.save()
    return ok(metric_def_dict(obj))


@endpoint()
def metric_delete(request, pk):
    """删除指标定义：级联删除其指标点（历史数据不可恢复，返回删除点数）。"""
    obj = get_metric_def(pk, request.user, write=True)
    points = obj.points.count()
    obj.delete()
    return ok({"deleted": True, "id": pk, "points_deleted": points})


# =====================================================================
# 指标点（6）
# =====================================================================


@endpoint()
def point_report(request):
    """上报单个指标点（模拟 agent 一次采集）。"""
    metric = _metric_for_report(request)
    value = services.to_float(p(request, "value"), "数值")
    timestamp = _clamp_future(_point_timestamp(request))
    point = MetricPoint.objects.create(
        owner=request.user,
        metric=metric,
        value=value,
        timestamp=timestamp,
        labels=_labels(request),
        source=str_param(request, "source", "agent", max_len=80),
    )
    return ok(point_dict(point))


@endpoint()
def point_batch(request):
    """批量上报指标点：先整体校验再事务写入，避免半批成功。"""
    points = list_param(request, "points", required=True, max_len=MAX_BATCH_POINTS)
    if not points:
        raise ValueError("参数 points 不能为空数组")
    default_source = str_param(request, "source", "agent", max_len=80)
    prepared = []
    metric_ids = set()
    owner = request.user
    for index, item in enumerate(points):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 个点必须是对象")
        metric = _resolve_item_metric(item, owner)
        try:
            value = services.to_float(item.get("value"), f"points[{index}].value")
        except ValueError as exc:
            raise ValueError(f"第 {index + 1} 个点数值非法: {exc}")
        timestamp = item.get("timestamp")
        timestamp = services.parse_datetime(timestamp, f"points[{index}].timestamp") \
            if timestamp else timezone.now()
        timestamp = _clamp_future(timestamp)
        labels = item.get("labels") or {}
        if not isinstance(labels, dict):
            raise ValueError(f"第 {index + 1} 个点的 labels 必须是对象")
        prepared.append(MetricPoint(
            owner=owner,
            metric=metric,
            value=value,
            timestamp=timestamp,
            labels={str(k): (v if isinstance(v, (int, float, bool)) else str(v))
                    for k, v in labels.items()},
            source=str(item.get("source") or default_source)[:80],
        ))
        metric_ids.add(metric.id)
    with transaction.atomic():
        MetricPoint.objects.bulk_create(prepared, batch_size=500)
    return ok({"created": len(prepared), "metric_ids": sorted(metric_ids)})


def _resolve_item_metric(item, owner):
    """批量上报里单点的指标寻址：metric_id 优先，否则 service_id+metric。"""
    metric_id = item.get("metric_id")
    if metric_id:
        metric = MetricDef.objects.filter(pk=metric_id).first()
        if metric is None:
            raise ValueError(f"指标不存在: id={metric_id}")
        services.ensure_writable(metric.service, owner)
        return metric
    service_id = item.get("service_id")
    name = str(item.get("metric") or "").strip()
    if not service_id or not name:
        raise ValueError("每个点必须提供 metric_id 或 service_id+metric")
    service = services.get_writable(Service, int(service_id), owner, "服务不存在")
    metric = MetricDef.objects.filter(service=service, name=name).first()
    if metric is None:
        raise ValueError(f"指标不存在: {name}")
    return metric


@endpoint(("GET",))
def point_query(request):
    """按时间范围查询指标：聚合单值 + 分桶序列 + 分位摘要。"""
    metric = _resolve_metric(request)
    since, until = window_params(request, default_hours=6)
    aggregation = opt_str(request, "aggregation", "avg").strip() or "avg"
    rows, _ = services.metric_series(metric.service, metric.name, since, until)
    values = [float(v) for _, v in rows]
    bucket_seconds = int_param(request, "bucket_seconds") \
        or services.choose_bucket_seconds(since, until)
    buckets = services.bucketize(rows, bucket_seconds, since=since, until=until,
                                 aggregation=aggregation,
                                 fill_empty=bool_param(request, "fill_empty", False))
    max_points = int_param(request, "max_points", 240, minimum=2, maximum=2000)
    buckets = services.downsample(buckets, max_points=max_points, aggregation=aggregation)
    group_by = opt_str(request, "group_by").strip()
    payload = {
        "metric_id": metric.id,
        "metric": metric.name,
        "unit": metric.unit,
        "metric_type": metric.metric_type,
        "since": services.iso(since),
        "until": services.iso(until),
        "aggregation": aggregation,
        "value": services.aggregate_values(values, aggregation),
        "summary": services.summarize(values),
        "bucket_seconds": bucket_seconds,
        "points": buckets,
        "count": len(values),
        "missing": not values,
    }
    if group_by:
        payload["groups"] = _group_by_label(metric, since, until, group_by, aggregation)
    return ok(payload)


def _group_by_label(metric, since, until, label_key, aggregation):
    """按标签维度分组聚合：多实例/多机房指标下钻的常用口径。"""
    rows = MetricPoint.objects.filter(metric=metric, timestamp__gte=since,
                                      timestamp__lt=until).values_list("labels", "value")
    grouped = {}
    for labels, value in rows[:services.MAX_POINTS_SCAN]:
        key = str((labels or {}).get(label_key, "")) or "(空)"
        grouped.setdefault(key, []).append(float(value))
    out = [{
        "label": key,
        "value": services.aggregate_values(values, aggregation),
        "count": len(values),
        "avg": services.round4(sum(values) / len(values)),
        "max": services.round4(max(values)),
    } for key, values in grouped.items()]
    return sorted(out, key=lambda row: -row["value"])


@endpoint(("GET",))
def point_percentiles(request):
    """指标分位：P50/P90/P95/P99（最近秩法）+ 基础统计。"""
    metric = _resolve_metric(request)
    since, until = window_params(request, default_hours=6)
    values, _ = services.metric_values(metric.service, metric.name, since, until)
    if not values:
        raise ValueError("窗口内没有指标数据，无法计算分位")
    return ok({
        "metric_id": metric.id,
        "metric": metric.name,
        "unit": metric.unit,
        "since": services.iso(since),
        "until": services.iso(until),
        "summary": services.summarize(values),
        "method": "nearest_rank",
    })


@endpoint(("GET",))
def point_latest(request):
    """指标最新值：支持按标签过滤（多实例场景取某实例的最新值）。"""
    metric = _resolve_metric(request)
    label_key = opt_str(request, "label_key").strip()
    label_value = opt_str(request, "label_value").strip()
    qs = MetricPoint.objects.filter(metric=metric).order_by("-timestamp", "-id")
    if label_key:
        # SQLite 的 JSON 查询能力有限：先取最近一批点在内存里按标签筛
        rows = list(qs[:2000])
        if label_value:
            rows = [r for r in rows if str((r.labels or {}).get(label_key, "")) == label_value]
        point = rows[0] if rows else None
    else:
        point = qs.first()
    if point is None:
        raise ValueError("该指标暂无数据")
    return ok({
        "metric_id": metric.id,
        "metric": metric.name,
        "unit": metric.unit,
        "point": point_dict(point),
        "age_seconds": services.round4(
            (timezone.now() - point.timestamp).total_seconds()),
    })


@endpoint(("GET",))
def point_labels(request):
    """标签枚举：返回最近窗口内出现过的标签键与取值（用于筛选器下拉）。"""
    metric = _resolve_metric(request)
    since, until = window_params(request, default_hours=24 * 7)
    rows = MetricPoint.objects.filter(metric=metric, timestamp__gte=since,
                                      timestamp__lt=until) \
        .order_by("-timestamp").values_list("labels", flat=True)[:services.MAX_POINTS_SCAN]
    keys = {}
    for labels in rows:
        for key, value in (labels or {}).items():
            bucket = keys.setdefault(str(key), set())
            if len(bucket) < services.MAX_LABEL_VALUES:
                bucket.add(str(value))
    return ok({
        "metric_id": metric.id,
        "metric": metric.name,
        "since": services.iso(since),
        "until": services.iso(until),
        "labels": [{"key": key, "values": sorted(values),
                    "count": len(values)} for key, values in sorted(keys.items())],
        "keys": sorted(keys),
    })
