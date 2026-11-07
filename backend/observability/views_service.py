# -*- coding: utf-8 -*-
"""可观测性 · 服务目录面：服务(8) + 端点(4) + 依赖(4) + 仪表盘面板(6) = 22 个接口。

这一面的核心是「拓扑」：服务是归属根，端点/依赖/面板都挂在服务上。写操作
全部要求对服务的写权限（owner/管理员），读操作走数据范围；依赖的增删会
同步维护 Service.dependency_count，避免总览页出现「依赖数对不上依赖图」。
"""
import re

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p, req_str

from observability import services
from observability.common import (
    bool_param,
    check_dict,
    datetime_param,
    dependency_dict,
    endpoint_dict,
    enum_param,
    filter_int,
    get_dependency,
    get_endpoint,
    get_panel,
    get_service,
    int_param,
    list_param,
    paginate,
    panel_dict,
    service_dict,
    str_param,
    window_params,
)
from observability.models import (
    CRITICALITIES,
    DEPENDENCY_TYPES,
    PANEL_CHART_TYPES,
    SERVICE_LEVELS,
    SERVICE_STATUS,
    DashboardPanel,
    Dependency,
    Endpoint,
    Service,
)


def _slugify(text):
    """由名称生成服务标识：小写、非字母数字转连字符，最长 80。"""
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-")
    return slug[:80]


def _unique_slug(user, base):
    """同一 owner 下 slug 唯一：冲突时追加序号，避免用户为了建服务先改名。"""
    base = base or "service"
    slug = base
    index = 1
    while Service.objects.filter(owner=user, slug=slug).exists():
        index += 1
        suffix = f"-{index}"
        slug = f"{base[:80 - len(suffix)]}{suffix}"
    return slug


def _refresh_dependency_counts(service_ids):
    """按依赖边重算 dependency_count（出边数）。

    冗余计数的唯一目的是让总览/列表不用 join 依赖表；既然冗余，就必须
    在每次依赖变更后同步，否则会长期漂移成错误数据。
    """
    ids = [i for i in set(service_ids) if i]
    if not ids:
        return
    counts = dict(Dependency.objects.filter(upstream_id__in=ids)
                  .values_list("upstream_id").annotate(total=Count("id")))
    for service_id in ids:
        Service.objects.filter(pk=service_id).update(
            dependency_count=counts.get(service_id, 0))


# =====================================================================
# 服务（8）
# =====================================================================


@endpoint(("GET",))
def service_list(request):
    """服务列表：支持 q/status/level/team 过滤与分页。"""
    qs = services.visible(Service.objects.all(), request.user)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(slug__icontains=keyword)
                       | Q(team__icontains=keyword) | Q(owner_name__icontains=keyword))
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    level = opt_str(request, "level").strip()
    if level:
        if level not in SERVICE_LEVELS:
            raise ValueError(f"服务等级必须是 {'/'.join(SERVICE_LEVELS)} 之一")
        qs = qs.filter(level=level)
    team = opt_str(request, "team").strip()
    if team:
        qs = qs.filter(team=team)
    qs = qs.order_by("-created_at")
    return paginate(qs, request, service_dict)


@endpoint()
def service_create(request):
    """创建服务：名称必填，标识缺省由名称生成且同 owner 内唯一。"""
    # 空白名称要报「服务名称不能为空」，而不是通用的「缺少必填参数」
    name = opt_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("服务名称不能为空")
    level = enum_param(request, "level", SERVICE_LEVELS, "P2", "服务等级")
    status = enum_param(request, "status", SERVICE_STATUS, "healthy", "服务状态")
    slug = opt_str(request, "slug").strip()
    if slug:
        if Service.objects.filter(owner=request.user, slug=slug).exists():
            raise ValueError("服务标识已存在，请换一个 slug")
    else:
        # 纯中文名称 slugify 后为空：自动生成并追加序号，而不是逼用户改名
        slug = _unique_slug(request.user, _slugify(name))
    service = Service.objects.create(
        owner=request.user,
        name=name,
        slug=slug[:80],
        owner_name=str_param(request, "owner_name", max_len=80)
        or (getattr(request.user, "nickname", "") or request.user.username),
        team=str_param(request, "team", max_len=80),
        level=level,
        status=status,
        description=str_param(request, "description"),
        labels=p(request, "labels") if isinstance(p(request, "labels"), dict) else {},
        repository=str_param(request, "repository", max_len=300),
    )
    return ok(service_dict(service))


@endpoint(("GET",))
def service_detail(request, pk):
    """服务详情：含端点/指标/SLO/告警规则的数量与最近健康分。"""
    service = get_service(pk, request.user)
    data = service_dict(service)
    data["counts"] = {
        "endpoints": service.endpoints.count(),
        "metrics": service.metrics.count(),
        "slos": service.slos.count(),
        "alert_rules": service.alert_rules.count(),
        "health_checks": service.health_checks.count(),
        "panels": service.panels.count(),
        "runbooks": service.runbooks.count(),
    }
    data["health"] = services.service_health(service, include_checks=True)
    return ok(data)


@endpoint()
def service_update(request, pk=None):
    """更新服务（部分字段）：名称/标识/负责人/团队/等级/状态/描述。"""
    target_id = pk or int_param(request, "id", required=True)
    service = get_service(target_id, request.user, write=True)
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("服务名称不能为空")
        service.name = name[:120]
    if p(request, "slug") is not None:
        slug = opt_str(request, "slug").strip()
        if not slug:
            raise ValueError("服务标识不能为空")
        if Service.objects.filter(owner=service.owner, slug=slug).exclude(pk=service.pk).exists():
            raise ValueError("服务标识已存在，请换一个 slug")
        service.slug = slug[:80]
    if p(request, "owner_name") is not None:
        service.owner_name = opt_str(request, "owner_name")[:80]
    if p(request, "team") is not None:
        service.team = opt_str(request, "team")[:80]
    if p(request, "level") is not None:
        service.level = enum_param(request, "level", SERVICE_LEVELS, service.level, "服务等级")
    if p(request, "status") is not None:
        service.status = enum_param(request, "status", SERVICE_STATUS, service.status, "服务状态")
    if p(request, "description") is not None:
        service.description = opt_str(request, "description")
    if p(request, "repository") is not None:
        service.repository = opt_str(request, "repository")[:300]
    labels = p(request, "labels")
    if isinstance(labels, dict):
        service.labels = labels
    service.save()
    return ok(service_dict(service))


@endpoint()
def service_delete(request, pk):
    """删除服务：级联清理端点/指标/SLO/告警等，并修复受影响服务的依赖计数。"""
    service = get_service(pk, request.user, write=True)
    affected = set()
    pairs = list(Dependency.objects.filter(
        Q(upstream=service) | Q(downstream=service)).values_list(
        "upstream_id", "downstream_id"))
    for upstream_id, downstream_id in pairs:
        affected.add(upstream_id)
        affected.add(downstream_id)
    affected.discard(service.id)
    with transaction.atomic():
        service.delete()
        _refresh_dependency_counts(affected)
    return ok({"deleted": True, "id": pk, "affected_services": sorted(affected)})


@endpoint(("GET",))
def service_overview(request):
    """服务健康总览：健康分分布、P0 异常服务、平均分（按可见范围）。"""
    qs = services.visible(Service.objects.all(), request.user)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(team__icontains=keyword))
    level = opt_str(request, "level").strip()
    if level:
        if level not in SERVICE_LEVELS:
            raise ValueError(f"服务等级必须是 {'/'.join(SERVICE_LEVELS)} 之一")
        qs = qs.filter(level=level)
    team = opt_str(request, "team").strip()
    if team:
        qs = qs.filter(team=team)
    overview = services.services_health_overview(qs)
    overview["by_level"] = dict(qs.values_list("level").annotate(total=Count("id")))
    return ok(overview)


@endpoint(("GET",))
def service_graph(request):
    """依赖图：节点 + 边 + 根/叶，供前端拓扑图直接渲染。"""
    qs = services.visible(Service.objects.all(), request.user)
    edges = Dependency.objects.filter(upstream__in=qs, downstream__in=qs) \
        .select_related("upstream", "downstream")
    graph = services.dependency_graph(services=list(qs), edges=list(edges))
    graph["cycle_detected"] = _has_cycle([(e["upstream_id"], e["downstream_id"])
                                          for e in graph["edges"]])
    return ok(graph)


def _has_cycle(pairs):
    """检测依赖图是否有环（DFN 三色标记）。

    有环的依赖图无法排定发布顺序，也无法有意义地做影响分析，必须在
    拓扑页明确标红，而不是让前端画出一个自引用箭头。
    """
    graph = {}
    for upstream, downstream in pairs:
        graph.setdefault(upstream, []).append(downstream)
    color = {}

    def visit(node):
        state = color.get(node, 0)
        if state == 1:
            return True
        if state == 2:
            return False
        color[node] = 1
        for nxt in graph.get(node, []):
            if visit(nxt):
                return True
        color[node] = 2
        return False

    return any(visit(node) for node in list(graph))


@endpoint(("GET",))
def service_health(request, pk):
    """单服务健康详情：检查分布、健康分、未恢复告警、SLO 快照。"""
    service = get_service(pk, request.user)
    data = services.service_health(service, include_checks=True)
    since, until = window_params(request, default_hours=24)
    data["window"] = {"since": services.iso(since), "until": services.iso(until)}
    data["health_checks"] = [check_dict(c) for c in
                             service.health_checks.order_by("id")[:50]]
    return ok(data)


# =====================================================================
# 端点（4）
# =====================================================================


@endpoint(("GET",))
def endpoint_list(request):
    """端点列表：按服务/状态/q(路径) 过滤。"""
    qs = services.visible(Endpoint.objects.select_related("service").all(), request.user)
    qs = filter_int(qs, request, "service_id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(path__icontains=keyword) | Q(description__icontains=keyword))
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    return paginate(qs.order_by("service_id", "path"), request, endpoint_dict)


@endpoint()
def endpoint_create(request):
    """登记端点：同一服务下 method+path 唯一。"""
    service = get_service(int_param(request, "service_id", required=True),
                          request.user, write=True)
    path = req_str(request, "path", max_len=300).strip()
    if not path.startswith("/"):
        raise ValueError("端点路径必须以 / 开头")
    method = (opt_str(request, "method", "GET").strip() or "GET").upper()
    if Endpoint.objects.filter(service=service, method=method, path=path).exists():
        raise ValueError("该服务下已存在相同方法与路径的端点")
    obj = Endpoint.objects.create(
        owner=request.user,
        service=service,
        path=path,
        method=method[:10],
        status=opt_str(request, "status", "up")[:20],
        description=opt_str(request, "description")[:300],
        timeout_ms=int_param(request, "timeout_ms", 3000, minimum=1, maximum=600000),
        p95_ms=services.to_float(p(request, "p95_ms") or 0, "p95_ms"),
    )
    return ok(endpoint_dict(obj))


@endpoint()
def endpoint_update(request, pk=None):
    """更新端点：路径/方法/状态/超时/P95。"""
    obj = get_endpoint(pk or int_param(request, "id", required=True),
                       request.user, write=True)
    if p(request, "path") is not None:
        path = opt_str(request, "path").strip()
        if not path.startswith("/"):
            raise ValueError("端点路径必须以 / 开头")
        obj.path = path[:300]
    if p(request, "method") is not None:
        obj.method = (opt_str(request, "method", obj.method).strip() or obj.method).upper()[:10]
    if p(request, "status") is not None:
        obj.status = opt_str(request, "status", obj.status)[:20]
    if p(request, "description") is not None:
        obj.description = opt_str(request, "description")[:300]
    if p(request, "timeout_ms") is not None:
        obj.timeout_ms = int_param(request, "timeout_ms", obj.timeout_ms,
                                   minimum=1, maximum=600000)
    if p(request, "p95_ms") is not None:
        obj.p95_ms = services.to_float(p(request, "p95_ms"), "p95_ms")
    duplicate = Endpoint.objects.filter(service_id=obj.service_id, method=obj.method,
                                        path=obj.path).exclude(pk=obj.pk).exists()
    if duplicate:
        raise ValueError("该服务下已存在相同方法与路径的端点")
    obj.save()
    return ok(endpoint_dict(obj))


@endpoint()
def endpoint_delete(request, pk):
    """删除端点（不影响服务其它数据）。"""
    obj = get_endpoint(pk, request.user, write=True)
    obj.delete()
    return ok({"deleted": True, "id": pk})


# =====================================================================
# 依赖（4）
# =====================================================================


@endpoint(("GET",))
def dependency_list(request):
    """依赖列表：按上游/下游服务过滤。"""
    qs = services.visible(Dependency.objects.select_related("upstream", "downstream").all(),
                          request.user)
    qs = filter_int(qs, request, "upstream_id")
    qs = filter_int(qs, request, "downstream_id")
    qs = filter_int(qs, request, "service_id", field="upstream_id", label="service_id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(description__icontains=keyword)
    criticality = opt_str(request, "criticality").strip()
    if criticality:
        if criticality not in CRITICALITIES:
            raise ValueError(f"关键程度必须是 {'/'.join(CRITICALITIES)} 之一")
        qs = qs.filter(criticality=criticality)
    return paginate(qs.order_by("upstream_id", "downstream_id"), request, dependency_dict)


@endpoint()
def dependency_create(request):
    """登记依赖边：禁止自依赖与重复边，写入后同步两侧服务的依赖计数。"""
    upstream = get_service(int_param(request, "upstream_id", required=True),
                           request.user, write=True)
    downstream = get_service(int_param(request, "downstream_id", required=True),
                             request.user, write=True)
    if upstream.id == downstream.id:
        raise ValueError("服务不能依赖自身")
    if Dependency.objects.filter(upstream=upstream, downstream=downstream).exists():
        raise ValueError("该依赖关系已存在")
    dep_type = enum_param(request, "dep_type", DEPENDENCY_TYPES, "http", "依赖类型")
    criticality = enum_param(request, "criticality", CRITICALITIES, "medium", "关键程度")
    with transaction.atomic():
        obj = Dependency.objects.create(
            owner=request.user,
            upstream=upstream,
            downstream=downstream,
            dep_type=dep_type,
            criticality=criticality,
            timeout_ms=int_param(request, "timeout_ms", 1000, minimum=1, maximum=600000),
            description=opt_str(request, "description")[:300],
        )
        _refresh_dependency_counts([upstream.id])
    return ok(dependency_dict(obj))


@endpoint()
def dependency_delete(request, pk):
    """删除依赖边并修复上游依赖计数。"""
    obj = get_dependency(pk, request.user)
    upstream_id = obj.upstream_id
    with transaction.atomic():
        obj.delete()
        _refresh_dependency_counts([upstream_id])
    return ok({"deleted": True, "id": pk, "upstream_id": upstream_id})


@endpoint(("GET",))
def dependency_impact(request):
    """影响分析：某服务故障后，会被拖垮的上游服务列表（防环）。"""
    target_id = int_param(request, "service_id", required=True)
    qs = services.visible(Service.objects.all(), request.user)
    if not qs.filter(pk=target_id).exists():
        raise ValueError("目标服务不存在")
    edges = Dependency.objects.filter(upstream__in=qs, downstream__in=qs)
    return ok(services.impact_analysis(target_id, edges=list(edges), services=list(qs),
                                       max_depth=int_param(request, "max_depth", 10,
                                                           minimum=1, maximum=50)))


# =====================================================================
# 仪表盘面板（6）
# =====================================================================


@endpoint(("GET",))
def panel_list(request):
    """面板列表：按服务过滤，默认按 order 升序（与看板展示顺序一致）。"""
    qs = services.visible(DashboardPanel.objects.select_related("service").all(), request.user)
    qs = filter_int(qs, request, "service_id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
    return paginate(qs.order_by("order", "id"), request, panel_dict)


@endpoint()
def panel_create(request):
    """创建面板：图表类型与查询配置校验后落库。"""
    name = req_str(request, "name", max_len=120).strip()
    chart_type = enum_param(request, "chart_type", PANEL_CHART_TYPES, "line", "图表类型")
    service_id = int_param(request, "service_id")
    service = get_service(service_id, request.user, write=True) if service_id else None
    query = p(request, "query")
    if query is not None and not isinstance(query, dict):
        raise ValueError("参数 query 必须是对象")
    obj = DashboardPanel.objects.create(
        owner=request.user,
        name=name,
        service=service,
        chart_type=chart_type,
        query=query or {},
        order=int_param(request, "order", 0, minimum=0, maximum=10000),
        width=int_param(request, "width", 6, minimum=1, maximum=12),
        height=int_param(request, "height", 4, minimum=1, maximum=24),
        description=opt_str(request, "description")[:300],
    )
    return ok(panel_dict(obj))


@endpoint()
def panel_update(request, pk=None):
    """更新面板：名称/服务/图表/查询/尺寸。"""
    obj = get_panel(pk or int_param(request, "id", required=True),
                    request.user, write=True)
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("面板名称不能为空")
        obj.name = name[:120]
    if p(request, "service_id") is not None:
        service_id = int_param(request, "service_id")
        obj.service = get_service(service_id, request.user, write=True) if service_id else None
    if p(request, "chart_type") is not None:
        obj.chart_type = enum_param(request, "chart_type", PANEL_CHART_TYPES,
                                    obj.chart_type, "图表类型")
    if p(request, "query") is not None:
        query = p(request, "query")
        if not isinstance(query, dict):
            raise ValueError("参数 query 必须是对象")
        obj.query = query
    if p(request, "order") is not None:
        obj.order = int_param(request, "order", obj.order, minimum=0, maximum=10000)
    if p(request, "width") is not None:
        obj.width = int_param(request, "width", obj.width, minimum=1, maximum=12)
    if p(request, "height") is not None:
        obj.height = int_param(request, "height", obj.height, minimum=1, maximum=24)
    if p(request, "description") is not None:
        obj.description = opt_str(request, "description")[:300]
    obj.save()
    return ok(panel_dict(obj))


@endpoint()
def panel_delete(request, pk):
    """删除面板。"""
    obj = get_panel(pk, request.user, write=True)
    obj.delete()
    return ok({"deleted": True, "id": pk})


@endpoint()
def panel_reorder(request):
    """批量调整面板顺序：按传入 id 顺序重排，缺失的排在末尾。

    接受整批顺序而不是单条 order 更新：拖拽前端一次会改多行，逐条请求
    会出现「中间态顺序」被别的用户看到。
    """
    ids = list_param(request, "ids", required=True, max_len=500)
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise ValueError("参数 ids 必须是整数数组")
    qs = services.visible(DashboardPanel.objects.all(), request.user)
    panels = {obj.id: obj for obj in qs.filter(pk__in=ids)}
    if len(panels) != len(set(ids)):
        raise ValueError("存在不可见或已删除的面板 id")
    with transaction.atomic():
        for index, panel_id in enumerate(ids):
            DashboardPanel.objects.filter(pk=panel_id).update(order=index * 10)
    return ok({"reordered": len(ids), "ids": ids})


@endpoint(("GET",))
def panel_data(request, pk):
    """面板数据：按面板查询配置取指标时间序列（或健康分/SLO 达成率）。

    ``kind`` 决定数据来源：
    - metric（默认）：指标名 + 聚合 + 分桶；
    - health_score：当前服务健康分；
    - slo_attainment：服务下所有生效 SLO 的最近达成率。
    """
    panel = get_panel(pk, request.user)
    query = panel.query or {}
    since, until = window_params(request, default_hours=float(query.get("hours", 6)))
    service_id = int_param(request, "service_id") or panel.service_id or query.get("service_id")
    service = get_service(int(service_id), request.user) if service_id else None
    kind = str(query.get("kind") or "metric")
    base = {
        "panel_id": panel.id,
        "name": panel.name,
        "chart_type": panel.chart_type,
        "kind": kind,
        "since": services.iso(since),
        "until": services.iso(until),
        "service_id": service.id if service else None,
    }
    if kind == "health_score":
        if service is None:
            raise ValueError("面板未绑定服务，无法计算健康分")
        score = services.health_score(list(service.health_checks.filter(enabled=True)))
        base.update({"value": score["score"], "grade": score["grade"],
                     "counts": score["counts"]})
        return ok(base)
    if kind == "slo_attainment":
        if service is None:
            raise ValueError("面板未绑定服务，无法读取 SLO 达成率")
        rows = [services.slo_status_snapshot(slo)
                for slo in service.slos.filter(status="active")]
        base.update({"items": rows, "count": len(rows)})
        return ok(base)

    metric_name = str(query.get("metric") or "").strip()
    if not metric_name:
        raise ValueError("面板查询配置缺少 metric")
    if service is None:
        raise ValueError("面板未绑定服务，请在查询配置里指定 service_id")
    series = services.timeseries(
        service, metric_name, since, until,
        bucket_seconds=int_param(request, "bucket_seconds"),
        aggregation=str(query.get("aggregation") or "avg"),
        fill_empty=bool_param(request, "fill_empty", bool(query.get("fill_empty", False))),
        max_points=int_param(request, "max_points", 240, minimum=2, maximum=2000),
    )
    base.update(series)
    return ok(base)
