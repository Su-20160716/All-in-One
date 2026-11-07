# -*- coding: utf-8 -*-
"""可观测性 · SLO 面（10 个接口）：CRUD + 计算 + 窗口历史 + 预算 + 燃烧率 + 预测。

口径统一由 services.compute_slo 决定：视图只负责解析窗口、落库与渲染。
「计算」接口会同时写 SloWindow 与 ErrorBudget 两张表，因此必须包在
transaction.atomic() 里 —— 达成率与预算必须来自同一次采样，否则复盘时
会出现「达成率 99.5% 但预算已耗尽」这种自相矛盾的快照。
"""
from datetime import timedelta

from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p, req_str

from observability import services
from observability.common import (
    datetime_param,
    filter_int,
    get_slo,
    int_param,
    paginate,
    slo_dict,
    slo_window_dict,
    str_param,
    window_params,
)
from observability.models import (
    SLO_STATUS,
    SLO_TYPES,
    Service,
    Slo,
    SloWindow,
)


def _slo_window(request, slo):
    """计算窗口：显式 since/until 优先，否则用 SLO 的 window_days 回看。"""
    since = datetime_param(request, "since")
    until = datetime_param(request, "until")
    if since is None and until is None:
        return services.default_slo_window(slo)
    if since is None:
        since = until - timedelta(days=max(int(slo.window_days or 1), 1))
    if until is None:
        until = timezone.now()
    if since >= until:
        raise ValueError("窗口开始时间必须早于结束时间")
    return since, until


def _slo_row(slo):
    """列表行：SLO 定义 + 最近窗口快照（一次渲染只查一条窗口）。"""
    row = slo_dict(slo)
    row["snapshot"] = services.slo_status_snapshot(slo)
    return row


@endpoint(("GET",))
def slo_list(request):
    """SLO 列表：按服务/类型/状态过滤，附带最近窗口达成率快照。"""
    qs = services.visible(Slo.objects.select_related("service").all(), request.user)
    qs = filter_int(qs, request, "service_id")
    slo_type = opt_str(request, "slo_type").strip()
    if slo_type:
        if slo_type not in SLO_TYPES:
            raise ValueError(f"SLO 类型必须是 {'/'.join(SLO_TYPES)} 之一")
        qs = qs.filter(slo_type=slo_type)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(name__icontains=keyword)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    return paginate(qs.order_by("service_id", "name"), request, _slo_row)


@endpoint()
def slo_create(request):
    """创建 SLO：延迟类必须给阈值，目标百分比限定 0~100。"""
    service = services.get_visible(Service, int_param(request, "service_id", required=True),
                                   request.user, "服务不存在")
    services.ensure_writable(service, request.user)
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("SLO 名称不能为空")
    if Slo.objects.filter(service=service, name=name).exists():
        raise ValueError("该服务下已存在同名 SLO")
    slo_type = opt_str(request, "slo_type", "availability").strip()
    if slo_type not in SLO_TYPES:
        raise ValueError(f"SLO 类型必须是 {'/'.join(SLO_TYPES)} 之一")
    target = services.to_float(p(request, "target_pct", 99.0), "target_pct")
    if not 0 < target <= 100:
        raise ValueError("目标百分比必须在 0 到 100 之间")
    threshold = int_param(request, "latency_threshold_ms", 0, minimum=0, maximum=600000)
    if slo_type == "latency" and threshold <= 0:
        raise ValueError("延迟类 SLO 必须配置大于 0 的延迟阈值")
    status = opt_str(request, "status", "active").strip()
    if status not in SLO_STATUS:
        raise ValueError(f"SLO 状态必须是 {'/'.join(SLO_STATUS)} 之一")
    metrics = p(request, "metrics")
    if metrics is not None and not isinstance(metrics, dict):
        raise ValueError("参数 metrics 必须是对象")
    obj = Slo.objects.create(
        owner=request.user,
        service=service,
        name=name,
        slo_type=slo_type,
        target_pct=target,
        window_days=int_param(request, "window_days", 30, minimum=1, maximum=365),
        latency_threshold_ms=threshold,
        status=status,
        owner_name=str_param(request, "owner_name", max_len=80)
        or (getattr(request.user, "nickname", "") or request.user.username),
        metrics=metrics or {},
        description=opt_str(request, "description")[:300],
    )
    return ok(_slo_row(obj))


@endpoint(("GET",))
def slo_detail(request, pk):
    """SLO 详情：定义 + 最近快照 + 最近 5 个窗口 + 预算。"""
    slo = get_slo(pk, request.user)
    data = _slo_row(slo)
    data["windows"] = [slo_window_dict(w) for w in
                       slo.windows.order_by("-start_at")[:5]]
    data["budget"] = services.budget_snapshot(slo)
    return ok(data)


@endpoint()
def slo_update(request, pk=None):
    """更新 SLO：目标/窗口/阈值/状态/负责人/计算口径。"""
    slo = get_slo(pk or int_param(request, "id", required=True),
                  request.user, write=True)
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("SLO 名称不能为空")
        if Slo.objects.filter(service_id=slo.service_id, name=name).exclude(pk=slo.pk).exists():
            raise ValueError("该服务下已存在同名 SLO")
        slo.name = name[:120]
    if p(request, "slo_type") is not None:
        slo_type = opt_str(request, "slo_type", slo.slo_type).strip()
        if slo_type not in SLO_TYPES:
            raise ValueError(f"SLO 类型必须是 {'/'.join(SLO_TYPES)} 之一")
        slo.slo_type = slo_type
    if p(request, "target_pct") is not None:
        target = services.to_float(p(request, "target_pct"), "target_pct")
        if not 0 < target <= 100:
            raise ValueError("目标百分比必须在 0 到 100 之间")
        slo.target_pct = target
    if p(request, "window_days") is not None:
        slo.window_days = int_param(request, "window_days", slo.window_days,
                                    minimum=1, maximum=365)
    if p(request, "latency_threshold_ms") is not None:
        slo.latency_threshold_ms = int_param(request, "latency_threshold_ms",
                                             slo.latency_threshold_ms,
                                             minimum=0, maximum=600000)
    if p(request, "status") is not None:
        slo.status = opt_str(request, "status", slo.status).strip()
        if slo.status not in SLO_STATUS:
            raise ValueError(f"SLO 状态必须是 {'/'.join(SLO_STATUS)} 之一")
    if p(request, "owner_name") is not None:
        slo.owner_name = opt_str(request, "owner_name")[:80]
    if p(request, "metrics") is not None:
        metrics = p(request, "metrics")
        if not isinstance(metrics, dict):
            raise ValueError("参数 metrics 必须是对象")
        slo.metrics = metrics
    if p(request, "description") is not None:
        slo.description = opt_str(request, "description")[:300]
    if slo.slo_type == "latency" and int(slo.latency_threshold_ms or 0) <= 0:
        raise ValueError("延迟类 SLO 必须配置大于 0 的延迟阈值")
    slo.save()
    return ok(_slo_row(slo))


@endpoint()
def slo_delete(request, pk):
    """删除 SLO（窗口与预算随之级联删除）。"""
    slo = get_slo(pk, request.user, write=True)
    slo.delete()
    return ok({"deleted": True, "id": pk})


@endpoint()
def slo_compute(request, pk=None):
    """计算 SLO 窗口：达成率/请求数/燃烧率，并落库快照与错误预算。"""
    slo = get_slo(pk or int_param(request, "id", required=True),
                  request.user, write=True)
    since, until = _slo_window(request, slo)
    result = services.record_slo_window(slo, request.user, since=since, until=until)
    result["budget"] = services.budget_snapshot(slo)
    return ok(result)


@endpoint(("GET",))
def slo_windows(request, pk):
    """SLO 窗口历史：按开始时间倒序分页。"""
    slo = get_slo(pk, request.user)
    qs = SloWindow.objects.filter(slo=slo).order_by("-start_at")
    since = datetime_param(request, "since")
    until = datetime_param(request, "until")
    if since:
        qs = qs.filter(start_at__gte=since)
    if until:
        qs = qs.filter(end_at__lte=until)
    return paginate(qs, request, slo_window_dict)


@endpoint(("GET",))
def slo_budget(request, pk):
    """错误预算：总额度/已消耗/剩余/消耗速率/预测耗尽日（可强制重算）。"""
    slo = get_slo(pk, request.user)
    recompute = opt_str(request, "recompute", "").lower() in ("1", "true", "yes", "on")
    if recompute:
        services.ensure_writable(slo, request.user)
        since, until = _slo_window(request, slo)
        result = services.record_slo_window(slo, request.user, since=since, until=until)
        snapshot = services.budget_snapshot(slo)
        snapshot["attainment_pct"] = result["attainment_pct"]
        return ok(snapshot)
    snapshot = services.budget_snapshot(slo)
    if snapshot is None:
        raise ValueError("该 SLO 尚无预算快照，请先调用计算接口")
    return ok(snapshot)


@endpoint(("GET",))
def slo_burn_rate(request, pk):
    """燃烧率：1h/6h/3d 多窗口对比，给出综合判定（critical/elevated/ok）。"""
    slo = get_slo(pk, request.user)
    return ok(services.burn_rate_report(slo))


@endpoint(("GET",))
def slo_forecast(request, pk):
    """预算燃尽预测：按当前消耗速率外推未来 N 天剩余额度曲线。"""
    slo = get_slo(pk, request.user)
    days = int_param(request, "days", 30, minimum=1, maximum=365)
    return ok(services.budget_forecast(slo, days=days))
