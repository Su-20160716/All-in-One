# -*- coding: utf-8 -*-
"""报表、页面、组件、筛选器、批注接口（含执行/预览/导出/收藏/分享）。

权限口径
--------
- 读：数据范围内可见（``get_report``）；执行/预览/导出都算读 —— 同部门
  同事需要看报表，但不应能改配置；
- 写：仅 owner（``get_report(write=True)``），覆盖改配置、发布、归档、删除、
  页面/组件维护。
"""
from time import perf_counter

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_num, opt_str, p, req_str

from reporting import services as svc
from reporting.models import (
    EXPORT_FORMATS, REPORT_STATUS, WIDGET_TYPES, ReportAnnotation,
    ReportDefinition, ReportExportJob, ReportFavorite, ReportPage, ReportRun,
    ReportSnapshot, ReportWidget, WidgetFilter,
)
from reporting.payloads import (
    annotation_dict, apply_q, apply_status, export_job_dict, favorite_dict,
    filter_dict, page_dict, paginate, report_dict, run_dict, snapshot_dict,
    widget_dict,
)
from reporting.views_common import (
    get_annotation, get_page, get_report, get_widget, read_bool,
    read_choice, read_int_list, read_json, read_json_obj, read_limit,
)


# =====================================================================
# 报表（14）
# =====================================================================


@endpoint(("GET",))
def reports_list(request):
    """报表列表（q/category/status/favorite 过滤 + 分页）。"""
    qs = scope_queryset(ReportDefinition.objects.all(), request.user, "owner")
    qs = apply_q(qs, request, ["name", "code", "description", "category"])
    category = opt_str(request, "category").strip()
    if category:
        qs = qs.filter(category=category)
    qs = apply_status(qs, request)
    if read_bool(request, "favorite", False):
        ids = ReportFavorite.objects.filter(user=request.user).values_list("report_id", flat=True)
        qs = qs.filter(pk__in=list(ids))
    qs = qs.order_by("-updated_at", "-id")
    return ok(paginate(qs, request, lambda o: report_dict(o)))


@endpoint()
def report_create(request):
    """新建报表（编码在本人名下唯一；默认建一个「总览」页面）。"""
    code = req_str(request, "code")[:80].strip()
    name = req_str(request, "name")[:160]
    if ReportDefinition.objects.filter(owner=request.user, code=code).exists():
        raise ValueError(f"报表编码 {code} 已存在")
    permissions = read_json_obj(request, "permissions", {})
    cache_ttl = int(p(request, "cache_ttl") or 300)
    if cache_ttl < 0 or cache_ttl > 86400:
        raise ValueError("cache_ttl 需在 0~86400 秒之间")
    with transaction.atomic():
        report = ReportDefinition.objects.create(
            code=code, name=name,
            category=opt_str(request, "category")[:40] or "通用",
            description=opt_str(request, "description"),
            status="draft", theme=opt_str(request, "theme")[:20] or "light",
            permissions=permissions, cache_ttl=cache_ttl, owner=request.user,
        )
        with_page = read_bool(request, "with_page", True)
        if with_page:
            ReportPage.objects.create(report=report, title="总览", order=0,
                                      layout={"columns": 12})
    return ok({"report": report_dict(report, detail=True)})


@endpoint(("GET",))
def report_detail(request, pk):
    """报表详情（页面与组件 + 最新结果快照 + 收藏状态）。"""
    report = get_report(pk, request.user)
    data = report_dict(report, detail=True)
    data["pages"] = [page_dict(page, with_widgets=True)
                     for page in report.rep_pages.all().order_by("order", "id")]
    snap = svc.latest_snapshot(report)
    data["latest_snapshot"] = snapshot_dict(snap) if snap else None
    data["favorited"] = ReportFavorite.objects.filter(report=report, user=request.user).exists()
    data["can_write"] = report.owner_id == request.user.id
    return ok(data)


@endpoint()
def report_update(request, pk):
    """更新报表元信息（名称/分类/描述/主题/缓存/权限/状态）。"""
    report = get_report(pk, request.user, write=True)
    with transaction.atomic():
        name = opt_str(request, "name").strip()
        if name:
            report.name = name[:160]
        if p(request, "code") is not None:
            code = opt_str(request, "code").strip()[:80]
            if code and ReportDefinition.objects.exclude(pk=report.pk).filter(
                    owner=request.user, code=code).exists():
                raise ValueError(f"报表编码 {code} 已存在")
            if code:
                report.code = code
        if p(request, "category") is not None:
            report.category = opt_str(request, "category")[:40] or "通用"
        if p(request, "description") is not None:
            report.description = opt_str(request, "description")
        if p(request, "theme") is not None:
            report.theme = opt_str(request, "theme")[:20] or "light"
        if p(request, "permissions") is not None:
            report.permissions = read_json_obj(request, "permissions", {})
        if p(request, "cache_ttl") is not None:
            ttl = int(p(request, "cache_ttl") or 0)
            if ttl < 0 or ttl > 86400:
                raise ValueError("cache_ttl 需在 0~86400 秒之间")
            report.cache_ttl = ttl
        status = read_choice(request, "status", REPORT_STATUS)
        if status:
            report.status = status
            if status == "published" and report.published_at is None:
                report.published_at = timezone.now()
        report.save()
    return ok({"report": report_dict(report, detail=True)})


@endpoint()
def report_delete(request, pk):
    """删除报表（页面/组件/快照/分享级联；执行流水一并移除）。"""
    report = get_report(pk, request.user, write=True)
    rid, name = report.pk, report.name
    report.delete()
    return ok({"deleted": True, "id": rid, "name": name})


@endpoint()
def report_clone(request, pk):
    """克隆报表（页面/组件/筛选器深拷贝，编码冲突自动加后缀）。"""
    report = get_report(pk, request.user, write=True)
    code = opt_str(request, "code").strip()[:80] or None
    name = opt_str(request, "name").strip()[:160] or None
    if code and ReportDefinition.objects.filter(owner=request.user, code=code).exists():
        raise ValueError(f"报表编码 {code} 已存在")
    clone = svc.clone_report(report, request.user, code=code, name=name)
    return ok({"report": report_dict(clone, detail=True), "source_id": report.pk})


@endpoint()
def report_publish(request, pk):
    """发布报表（要求至少一个页面且至少一个组件，避免发空报表）。"""
    report = get_report(pk, request.user, write=True)
    pages = report.rep_pages.count()
    widgets = ReportWidget.objects.filter(page__report=report).count()
    if pages == 0:
        raise ValueError("报表还没有页面，不能发布")
    if widgets == 0:
        raise ValueError("报表还没有组件，不能发布")
    with transaction.atomic():
        report.status = "published"
        report.published_at = timezone.now()
        report.save(update_fields=["status", "published_at", "updated_at"])
    return ok({"id": report.pk, "status": report.status,
               "published_at": report.published_at.isoformat(),
               "pages": pages, "widgets": widgets})


@endpoint()
def report_archive(request, pk):
    """归档报表（归档后不可执行，可随时改回 published）。"""
    report = get_report(pk, request.user, write=True)
    with transaction.atomic():
        report.status = "archived"
        report.save(update_fields=["status", "updated_at"])
    return ok({"id": report.pk, "status": report.status})


@endpoint()
def report_run(request, pk):
    """执行报表（参数化 + 可选绕过缓存），返回页面/组件与 columns/rows/meta。"""
    report = get_report(pk, request.user)
    if report.status == "archived":
        raise ValueError("报表已归档，不能执行")
    params = read_json_obj(request, "params", {})
    bypass = read_bool(request, "bypass_cache", False)
    payload = svc.run_report(report, params, request.user, trigger="manual",
                             bypass_cache=bypass)
    return ok(payload)


@endpoint()
def report_preview(request, pk):
    """预览报表（每组件限制行数、不写执行流水，调样式时用）。"""
    report = get_report(pk, request.user)
    params = read_json_obj(request, "params", {})
    limit = read_limit(request, "limit", 20, maximum=200)
    payload = svc.preview_report(report, params, request.user, limit=limit)
    return ok(payload)


@endpoint(("GET",))
def report_result(request, pk):
    """读取结果缓存（无缓存时返回 available=false，不触发重算）。"""
    report = get_report(pk, request.user)
    key = opt_str(request, "params_key").strip()
    snapshot = None
    if key:
        snapshot = ReportSnapshot.objects.filter(report=report, params_key=key).first()
    if snapshot is None:
        snapshot = svc.latest_snapshot(report, valid_only=read_bool(request, "valid_only", False))
    if snapshot is None:
        return ok({"available": False, "report": svc.report_brief(report),
                   "message": "还没有缓存结果，请先执行一次"})
    return ok({
        "available": True,
        "snapshot": snapshot_dict(snapshot),
        "payload": snapshot.payload or {},
    })


@endpoint(("GET",))
def report_snapshots(request, pk):
    """结果缓存列表（含过期标记，便于排查「看到旧数据」）。"""
    report = get_report(pk, request.user)
    qs = ReportSnapshot.objects.filter(report=report).order_by("-updated_at", "-id")
    return ok(paginate(qs, request, lambda s: snapshot_dict(s)))


@endpoint()
def report_export(request, pk):
    """导出报表（CSV/JSON，含公式注入防护），并记录导出任务。"""
    report = get_report(pk, request.user)
    fmt = read_choice(request, "fmt", EXPORT_FORMATS, default="csv")
    params = read_json_obj(request, "params", {})
    widget_id = opt_num(request, "widget_id", None, integer=True, minimum=1)
    started = perf_counter()
    payload = svc.run_report(report, params, request.user, trigger="manual")
    if (payload.get("meta") or {}).get("status") == "failed":
        ReportExportJob.objects.create(
            report=report, fmt=fmt, status="failed", owner=request.user,
            params=params, error=str(payload["meta"].get("error"))[:2000],
        )
        raise ValueError(f"报表执行失败，无法导出：{payload['meta'].get('error')}")
    try:
        data = svc.export_report(payload, fmt, report.name, widget_id=widget_id)
    except ValueError as e:
        ReportExportJob.objects.create(
            report=report, fmt=fmt, status="failed", owner=request.user,
            params=params, error=str(e)[:2000],
        )
        raise
    duration = int((perf_counter() - started) * 1000)
    job = ReportExportJob.objects.create(
        report=report, fmt=fmt, status="done", row_count=data["rows"],
        owner=request.user, params=params, filename=data["filename"],
        size_bytes=data["bytes"], duration_ms=duration,
    )
    return ok({**data, "job": export_job_dict(job)})


@endpoint(("GET",))
def report_runs(request, pk):
    """执行流水（分页；with_result=true 时附带结果快照，默认不返回以省带宽）。"""
    report = get_report(pk, request.user)
    qs = scope_queryset(ReportRun.objects.filter(report=report), request.user, "owner")
    qs = apply_status(qs, request)
    trigger = read_choice(request, "trigger", [("manual", ""), ("schedule", ""),
                                               ("api", ""), ("cache", ""), ("share", "")])
    if trigger:
        qs = qs.filter(trigger=trigger)
    qs = qs.order_by("-created_at", "-id")
    with_result = read_bool(request, "with_result", False)
    return ok(paginate(qs, request, lambda r: run_dict(r, with_result=with_result)))


@endpoint()
def report_favorite(request, pk):
    """收藏/取消收藏报表（幂等切换，返回最新状态与收藏数）。"""
    report = get_report(pk, request.user)
    with transaction.atomic():
        fav = ReportFavorite.objects.filter(report=report, user=request.user).first()
        if fav is None:
            try:
                ReportFavorite.objects.create(report=report, user=request.user,
                                              owner=request.user)
                favorited = True
            except IntegrityError:  # 并发双击：已存在即视为已收藏
                favorited = True
        else:
            fav.delete()
            favorited = False
    return ok({"report_id": report.pk, "favorited": favorited,
               "count": report.rep_favorites.count()})


@endpoint(("GET",))
def favorites_list(request):
    """我的收藏列表（带报表摘要与分页）。"""
    qs = ReportFavorite.objects.filter(user=request.user).select_related("report")
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(qs, request, favorite_dict))


@endpoint()
def report_share_create(request, pk):
    """创建只读分享链接（可设有效期，0 表示长期有效）。"""
    report = get_report(pk, request.user, write=True)
    days = opt_num(request, "days", 7, integer=True, minimum=0, maximum=365)
    share = svc.create_share(
        report, request.user, days=int(days),
        readonly=read_bool(request, "readonly", True),
        note=opt_str(request, "note"),
    )
    return ok(svc.share_brief(share))


# =====================================================================
# 页面（5）
# =====================================================================


@endpoint(("GET",))
def report_pages(request, pk):
    """页面列表（含组件概要，便于目录树渲染）。"""
    report = get_report(pk, request.user)
    pages = [page_dict(page) for page in report.rep_pages.all().order_by("order", "id")]
    return ok({"items": pages, "count": len(pages), "report_id": report.pk})


@endpoint()
def report_page_create(request, pk):
    """新建页面（排序默认追加到末尾）。"""
    report = get_report(pk, request.user, write=True)
    if report.rep_pages.count() >= 30:
        raise ValueError("单张报表最多 30 个页面")
    title = req_str(request, "title")[:120]
    order = opt_num(request, "order", report.rep_pages.count(),
                    integer=True, minimum=0, maximum=999)
    page = ReportPage.objects.create(
        report=report, title=title,
        description=opt_str(request, "description")[:255],
        order=int(order), layout=read_json_obj(request, "layout", {"columns": 12}),
    )
    return ok(page_dict(page))


@endpoint()
def page_update(request, pk):
    """更新页面（标题/描述/排序/布局）。"""
    page = get_page(pk, request.user, write=True)
    with transaction.atomic():
        title = opt_str(request, "title").strip()
        if title:
            page.title = title[:120]
        if p(request, "description") is not None:
            page.description = opt_str(request, "description")[:255]
        if p(request, "order") is not None:
            page.order = int(opt_num(request, "order", page.order, integer=True,
                                     minimum=0, maximum=999))
        if p(request, "layout") is not None:
            page.layout = read_json_obj(request, "layout", {})
        page.save()
    return ok(page_dict(page, with_widgets=True))


@endpoint()
def page_delete(request, pk):
    """删除页面（报表至少保留一页，否则发布与执行都会失去入口）。"""
    page = get_page(pk, request.user, write=True)
    if page.report.rep_pages.count() <= 1:
        raise ValueError("报表至少保留一个页面")
    pid = page.pk
    page.delete()
    return ok({"deleted": True, "id": pid})


@endpoint()
def page_reorder(request, pk):
    """页面排序：按 ids 顺序重排。"""
    report = get_report(pk, request.user, write=True)
    ids = read_int_list(request, "ids", max_items=30)
    if not ids:
        raise ValueError("缺少必填参数: ids")
    pages = {page.pk: page for page in report.rep_pages.all()}
    with transaction.atomic():
        for idx, pid in enumerate(ids):
            page = pages.get(pid)
            if page is None:
                raise ValueError(f"页面 {pid} 不属于该报表")
            if page.order != idx:
                page.order = idx
                page.save(update_fields=["order"])
    return ok({"report_id": report.pk, "count": len(ids)})


# =====================================================================
# 组件（6）
# =====================================================================


def _validate_dataset_ref(request, dataset_id):
    """组件引用的数据集必须可见且启用。"""
    if dataset_id in (None, ""):
        return None
    from reporting.views_common import get_dataset

    ref = get_dataset(dataset_id, request.user)
    if ref.status != "active":
        raise ValueError(f"数据集「{ref.name}」已停用")
    return ref


@endpoint(("GET",))
def page_widgets(request, pk):
    """页面下的组件列表（含筛选器）。"""
    page = get_page(pk, request.user)
    widgets = [widget_dict(w, with_filters=True)
               for w in page.rep_widgets.all().order_by("order", "id")]
    return ok({"items": widgets, "count": len(widgets), "page_id": page.pk})


@endpoint()
def page_widget_create(request, pk):
    """新增组件（类型 + 数据集 + 配置 + 位置尺寸）。"""
    page = get_page(pk, request.user, write=True)
    if page.rep_widgets.count() >= 60:
        raise ValueError("单个页面最多 60 个组件")
    rtype = read_choice(request, "type", WIDGET_TYPES, required=True)
    dataset = _validate_dataset_ref(request, p(request, "dataset_id"))
    if dataset is None and rtype != "text":
        raise ValueError(f"{rtype} 组件必须绑定数据集")
    config = read_json_obj(request, "config", {})
    title = opt_str(request, "title").strip()[:160] or f"{dict(WIDGET_TYPES)[rtype]}组件"
    widget = ReportWidget.objects.create(
        page=page, rtype=rtype, title=title,
        description=opt_str(request, "description")[:255],
        dataset=dataset, config=config,
        x=int(opt_num(request, "x", 0, integer=True, minimum=0, maximum=12)),
        y=int(opt_num(request, "y", 0, integer=True, minimum=0, maximum=9999)),
        w=int(opt_num(request, "w", 6, integer=True, minimum=1, maximum=12)),
        h=int(opt_num(request, "h", 4, integer=True, minimum=1, maximum=200)),
        order=page.rep_widgets.count(),
    )
    return ok(widget_dict(widget, with_filters=True))


@endpoint()
def widget_update(request, pk):
    """更新组件（标题/类型/数据集/配置/位置）。"""
    widget = get_widget(pk, request.user, write=True)
    with transaction.atomic():
        title = opt_str(request, "title").strip()
        if title:
            widget.title = title[:160]
        if p(request, "description") is not None:
            widget.description = opt_str(request, "description")[:255]
        rtype = read_choice(request, "type", WIDGET_TYPES)
        if rtype:
            widget.rtype = rtype
        if p(request, "dataset_id") is not None:
            widget.dataset = _validate_dataset_ref(request, p(request, "dataset_id"))
        if p(request, "config") is not None:
            widget.config = read_json_obj(request, "config", {})
        for key, field in (("x", "x"), ("y", "y"), ("w", "w"), ("h", "h"), ("order", "order")):
            if p(request, key) is not None:
                value = int(opt_num(request, key, getattr(widget, field), integer=True,
                                    minimum=0, maximum=9999))
                setattr(widget, field, value)
        if widget.rtype != "text" and widget.dataset_id is None:
            raise ValueError(f"{widget.rtype} 组件必须绑定数据集")
        widget.save()
    return ok(widget_dict(widget, with_filters=True))


@endpoint()
def widget_delete(request, pk):
    """删除组件（同时解除仪表盘引用，返回解绑数量）。"""
    widget = get_widget(pk, request.user, write=True)
    linked = widget.rep_dashboard_links.count()
    wid = widget.pk
    widget.delete()
    return ok({"deleted": True, "id": wid, "detached_dashboards": linked})


@endpoint()
def widget_reorder(request, pk):
    """组件排序：同页面内按 ids 重排。"""
    page = get_page(pk, request.user, write=True)
    ids = read_int_list(request, "ids", max_items=60)
    if not ids:
        raise ValueError("缺少必填参数: ids")
    widgets = {w.pk: w for w in page.rep_widgets.all()}
    with transaction.atomic():
        for idx, wid in enumerate(ids):
            widget = widgets.get(wid)
            if widget is None:
                raise ValueError(f"组件 {wid} 不属于该页面")
            if widget.order != idx:
                widget.order = idx
                widget.save(update_fields=["order"])
    return ok({"page_id": page.pk, "count": len(ids)})


@endpoint()
def widget_run(request, pk):
    """单独执行一个组件（调样式/排障用，不写报表流水）。"""
    widget = get_widget(pk, request.user)
    params = read_json_obj(request, "params", {})
    limit = read_limit(request, "limit", 50, maximum=500)
    result = svc.execute_widget(widget, params, limit=limit)
    return ok({**result, "widget_id": widget.pk, "title": widget.title})


# =====================================================================
# 组件筛选器（4）
# =====================================================================


@endpoint(("GET",))
def widget_filters(request, pk):
    """组件筛选器列表。"""
    widget = get_widget(pk, request.user)
    items = [filter_dict(f) for f in widget.rep_widget_filters.all().order_by("order", "id")]
    return ok({"items": items, "count": len(items), "widget_id": widget.pk})


def _read_filter_value(request, key="default_value"):
    """筛选默认值既可能是 JSON（数组/对象），也可能是纯字符串（如状态码）。"""
    try:
        return read_json(request, key)
    except ValueError:
        raw = p(request, key)
        if isinstance(raw, (str, int, float, bool)):
            return raw
        raise


@endpoint()
def widget_filter_create(request, pk):
    """新增筛选器（字段/操作符校验，绑定参数须在数据集参数表里）。"""
    widget = get_widget(pk, request.user, write=True)
    field = req_str(request, "field")[:120]
    operator = read_choice(request, "operator", list(svc.OPERATORS.keys()), default="eq")
    bound_param = opt_str(request, "bound_param")[:60].strip()
    if widget.dataset_id:
        svc.resolve_path(svc.get_whitelisted_model(widget.dataset.primary_model), field)
        if bound_param and not widget.dataset.rep_dataset_params.filter(name=bound_param).exists():
            raise ValueError(f"数据集没有名为 {bound_param} 的参数")
    if widget.rep_widget_filters.count() >= 20:
        raise ValueError("单个组件最多 20 个筛选器")
    default_value = _read_filter_value(request)
    item = widget.rep_widget_filters.create(
        field=field, operator=operator, default_value=default_value,
        bound_param=bound_param, label=opt_str(request, "label")[:80],
        order=widget.rep_widget_filters.count(),
    )
    return ok(filter_dict(item))


@endpoint()
def widget_filter_update(request, pk):
    """更新筛选器（操作符/默认值/绑定参数）。"""
    item = WidgetFilter.objects.select_related("widget").filter(pk=pk).first()
    if item is None:
        raise ValueError("筛选器不存在")
    get_widget(item.widget_id, request.user, write=True)
    with transaction.atomic():
        operator = read_choice(request, "operator", list(svc.OPERATORS.keys()))
        if operator:
            item.operator = operator
        if p(request, "field") is not None:
            field = opt_str(request, "field").strip()[:120]
            if field and item.widget.dataset_id:
                svc.resolve_path(
                    svc.get_whitelisted_model(item.widget.dataset.primary_model), field,
                )
            if field:
                item.field = field
        if p(request, "default_value") is not None:
            item.default_value = _read_filter_value(request)
        if p(request, "bound_param") is not None:
            bound = opt_str(request, "bound_param").strip()[:60]
            if bound and item.widget.dataset_id and not item.widget.dataset.rep_dataset_params.filter(
                    name=bound).exists():
                raise ValueError(f"数据集没有名为 {bound} 的参数")
            item.bound_param = bound
        if p(request, "label") is not None:
            item.label = opt_str(request, "label")[:80]
        item.save()
    return ok(filter_dict(item))


@endpoint()
def widget_filter_delete(request, pk):
    """删除筛选器。"""
    item = WidgetFilter.objects.select_related("widget").filter(pk=pk).first()
    if item is None:
        raise ValueError("筛选器不存在")
    get_widget(item.widget_id, request.user, write=True)
    fid, widget_id = item.pk, item.widget_id
    item.delete()
    return ok({"deleted": True, "id": fid, "widget_id": widget_id})


# =====================================================================
# 批注（4）
# =====================================================================


@endpoint(("GET",))
def annotations_list(request):
    """批注列表（按报表或组件过滤；默认只看未解决的）。"""
    from reporting.views_common import get_report as _get_report

    report_id = opt_num(request, "report_id", None, integer=True, minimum=1)
    widget_id = opt_num(request, "widget_id", None, integer=True, minimum=1)
    if report_id:
        report = _get_report(report_id, request.user)
        qs = ReportAnnotation.objects.filter(report=report)
    elif widget_id:
        widget = get_widget(widget_id, request.user)
        qs = ReportAnnotation.objects.filter(report=widget.page.report)
    else:
        raise ValueError("需要 report_id 或 widget_id")
    if widget_id:
        qs = qs.filter(widget_id=widget_id)
    if read_bool(request, "resolved", True) is False:
        qs = qs.filter(resolved=False)
    qs = qs.select_related("widget").order_by("-created_at", "-id")
    return ok(paginate(qs, request, annotation_dict))


@endpoint()
def annotation_create(request):
    """新增批注（可钉到组件与数据点，例如 {key: "amount", index: 3}）。"""
    report = get_report(req_str(request, "report_id"), request.user)
    widget = None
    widget_id = opt_num(request, "widget_id", None, integer=True, minimum=1)
    if widget_id:
        widget = get_widget(widget_id, request.user)
        if widget.page.report_id != report.pk:
            raise ValueError("组件不属于该报表")
    body = req_str(request, "body")
    if len(body) > 4000:
        raise ValueError("批注内容不能超过 4000 字")
    item = ReportAnnotation.objects.create(
        report=report, widget=widget, body=body,
        data_point=read_json_obj(request, "data_point", {}),
        color=opt_str(request, "color")[:20] or "#f59e0b",
        owner=request.user,
    )
    return ok(annotation_dict(item))


@endpoint()
def annotation_update(request, pk):
    """更新批注（内容/颜色/解决状态）。"""
    item = get_annotation(pk, request.user, write=True)
    with transaction.atomic():
        body = opt_str(request, "body").strip()
        if body:
            if len(body) > 4000:
                raise ValueError("批注内容不能超过 4000 字")
            item.body = body
        if p(request, "color") is not None:
            item.color = opt_str(request, "color")[:20] or "#f59e0b"
        if p(request, "resolved") is not None:
            item.resolved = read_bool(request, "resolved", item.resolved)
        if p(request, "data_point") is not None:
            item.data_point = read_json_obj(request, "data_point", {})
        item.save()
    return ok(annotation_dict(item))


@endpoint()
def annotation_delete(request, pk):
    """删除批注。"""
    item = get_annotation(pk, request.user, write=True)
    aid = item.pk
    item.delete()
    return ok({"deleted": True, "id": aid})
