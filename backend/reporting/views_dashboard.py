# -*- coding: utf-8 -*-
"""仪表盘与分享链接接口：看板 CRUD、组件拼装、导出、公开只读访问。

权限口径
--------
- 仪表盘自身有 owner：读按数据范围，写仅 owner；
- 往仪表盘里挂组件时，组件所属报表必须对当前用户可见（否则等于借看板
  读别人报表），因此额外走 ``assert_visible_report``；
- 公开分享接口不做登录校验，只校验 token + 报表已发布，且只读。
"""
from django.db import IntegrityError, transaction

from core.scoping import scope_queryset
from devtools.common import endpoint, ok, opt_str, p, req_str
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny

from reporting import services as svc
from reporting.models import (
    DASHBOARD_STATUS, EXPORT_FORMATS, Dashboard, DashboardWidget,
    ReportDefinition, ReportShare, ReportWidget,
)
from reporting.payloads import (
    apply_q, apply_status, dashboard_dict, dashboard_widget_dict,
    paginate, ts,
)
from reporting.views_common import (
    assert_visible_report, get_dashboard, get_report, get_widget, get_writable,
    read_bool, read_choice, read_int_list, read_json_obj,
)


# =====================================================================
# 仪表盘（8）
# =====================================================================


@endpoint(("GET",))
def dashboards_list(request):
    """仪表盘列表（q/status 过滤 + 分页，只返回本人可见范围）。"""
    qs = scope_queryset(Dashboard.objects.all(), request.user, "owner")
    qs = apply_q(qs, request, ["name", "description"])
    qs = apply_status(qs, request)
    qs = qs.order_by("-updated_at", "-id")
    return ok(paginate(qs, request, dashboard_dict))


@endpoint()
def dashboard_create(request):
    """新建仪表盘（名称必填，布局与默认筛选以 JSON 保存）。"""
    name = req_str(request, "name")[:120]
    layout = read_json_obj(request, "layout", {"columns": 12})
    default_filters = read_json_obj(request, "default_filters", {})
    dashboard = Dashboard.objects.create(
        name=name,
        description=opt_str(request, "description"),
        layout=layout,
        theme=opt_str(request, "theme")[:20] or "light",
        default_filters=default_filters,
        status="active",
        owner=request.user,
    )
    return ok({"dashboard": dashboard_dict(dashboard, detail=True)})


@endpoint(("GET",))
def dashboard_detail(request, pk):
    """仪表盘详情：组件 + 最新结果（refresh=true 时实时重算）。"""
    dashboard = get_dashboard(pk, request.user)
    params = read_json_obj(request, "params", {})
    refresh = read_bool(request, "refresh", False)
    payload = svc.dashboard_payload(dashboard, params, refresh=refresh)
    payload["dashboard"]["can_write"] = dashboard.owner_id == request.user.id
    payload["links"] = [dashboard_widget_dict(link, with_widget=True)
                        for link in dashboard.rep_dashboard_widgets
                        .select_related("widget", "widget__page")
                        .all().order_by("order", "id")]
    return ok(payload)


@endpoint()
def dashboard_update(request, pk):
    """更新仪表盘（名称/描述/布局/主题/默认筛选/状态）。"""
    dashboard = get_dashboard(pk, request.user, write=True)
    with transaction.atomic():
        name = opt_str(request, "name").strip()
        if name:
            dashboard.name = name[:120]
        if p(request, "description") is not None:
            dashboard.description = opt_str(request, "description")
        if p(request, "layout") is not None:
            dashboard.layout = read_json_obj(request, "layout", {})
        if p(request, "theme") is not None:
            dashboard.theme = opt_str(request, "theme")[:20] or "light"
        if p(request, "default_filters") is not None:
            dashboard.default_filters = read_json_obj(request, "default_filters", {})
        status = read_choice(request, "status", DASHBOARD_STATUS)
        if status:
            dashboard.status = status
        dashboard.save()
    return ok({"dashboard": dashboard_dict(dashboard, detail=True)})


@endpoint()
def dashboard_delete(request, pk):
    """删除仪表盘（仅删看板与拼装关系，不动报表组件本身）。"""
    dashboard = get_dashboard(pk, request.user, write=True)
    did, name = dashboard.pk, dashboard.name
    dashboard.delete()
    return ok({"deleted": True, "id": did, "name": name})


@endpoint(("GET",))
def dashboard_available_widgets(request):
    """可挂载组件候选：当前用户可见报表下的全部组件（q/type 过滤 + 分页）。"""
    reports = scope_queryset(ReportDefinition.objects.all(), request.user, "owner")
    qs = (ReportWidget.objects
          .filter(page__report__in=reports)
          .select_related("page", "page__report", "dataset")
          .order_by("page__report_id", "page__order", "order", "id"))
    qs = apply_q(qs, request, ["title", "description"])
    rtype = read_choice(request, "type", [t[0] for t in (
        ("table", ""), ("bar", ""), ("line", ""), ("pie", ""), ("kpi", ""),
        ("pivot", ""), ("heatmap", ""), ("text", ""),
    )])
    if rtype:
        qs = qs.filter(rtype=rtype)
    payload = paginate(qs, request, lambda w: {
        "id": w.pk,
        "title": w.title,
        "type": w.rtype,
        "dataset_id": w.dataset_id,
        "report_id": w.page.report_id,
        "report_name": w.page.report.name if w.page_id and w.page.report_id else "",
        "page_id": w.page_id,
        "page_title": w.page.title if w.page_id else "",
    })
    return ok(payload)


@endpoint()
def dashboard_widget_add(request, pk):
    """往仪表盘挂一个报表组件（同一组件只能挂一次）。"""
    dashboard = get_dashboard(pk, request.user, write=True)
    widget = get_widget(p(request, "widget_id"), request.user)
    assert_visible_report(widget.page.report, request.user)
    if dashboard.rep_dashboard_widgets.count() >= 50:
        raise ValueError("单个仪表盘最多 50 个组件")
    override = read_json_obj(request, "override", {})
    order = int(p(request, "order")) if p(request, "order") is not None \
        else dashboard.rep_dashboard_widgets.count()
    try:
        with transaction.atomic():
            link = DashboardWidget.objects.create(
                dashboard=dashboard,
                widget=widget,
                override=override,
                x=int(p(request, "x") if p(request, "x") is not None else widget.x),
                y=int(p(request, "y") if p(request, "y") is not None else widget.y),
                w=int(p(request, "w") if p(request, "w") is not None else widget.w),
                h=int(p(request, "h") if p(request, "h") is not None else widget.h),
                order=order,
                owner=request.user,
            )
    except IntegrityError:
        # 唯一约束 (dashboard, widget) 兜底并发重复挂载
        raise ValueError("该组件已在仪表盘中")
    return ok(dashboard_widget_dict(link, with_widget=True))


@endpoint()
def dashboard_widget_update(request, pk):
    """更新仪表盘内组件（覆盖配置 / 位置尺寸 / 排序）。"""
    link = DashboardWidget.objects.select_related("dashboard").filter(pk=pk).first()
    if link is None:
        raise ValueError("仪表盘组件不存在")
    get_dashboard(link.dashboard_id, request.user, write=True)
    with transaction.atomic():
        if p(request, "override") is not None:
            link.override = read_json_obj(request, "override", {})
        for key in ("x", "y", "w", "h", "order"):
            if p(request, key) is not None:
                setattr(link, key, int(p(request, key)))
        link.save()
    return ok(dashboard_widget_dict(link, with_widget=True))


@endpoint()
def dashboard_widget_remove(request, pk):
    """从仪表盘移除组件（组件本身保留在报表里）。"""
    link = DashboardWidget.objects.select_related("dashboard").filter(pk=pk).first()
    if link is None:
        raise ValueError("仪表盘组件不存在")
    get_dashboard(link.dashboard_id, request.user, write=True)
    lid, widget_id = link.pk, link.widget_id
    link.delete()
    return ok({"deleted": True, "id": lid, "widget_id": widget_id})


@endpoint()
def dashboard_reorder(request, pk):
    """仪表盘组件排序：按 ids 顺序重排。"""
    dashboard = get_dashboard(pk, request.user, write=True)
    ids = read_int_list(request, "ids", max_items=50)
    if not ids:
        raise ValueError("缺少必填参数: ids")
    links = {link.pk: link for link in dashboard.rep_dashboard_widgets.all()}
    with transaction.atomic():
        for idx, lid in enumerate(ids):
            link = links.get(lid)
            if link is None:
                raise ValueError(f"组件 {lid} 不属于该仪表盘")
            if link.order != idx:
                link.order = idx
                link.save(update_fields=["order"])
    return ok({"dashboard_id": dashboard.pk, "count": len(ids)})


@endpoint()
def dashboard_export(request, pk):
    """导出仪表盘（多组件纵向拼接；JSON 保持完整结构）。"""
    dashboard = get_dashboard(pk, request.user)
    fmt = read_choice(request, "fmt", EXPORT_FORMATS, default="csv")
    params = read_json_obj(request, "params", {})
    payload = svc.dashboard_payload(dashboard, params, refresh=read_bool(request, "refresh", False))
    data = svc.export_dashboard(payload, fmt)
    return ok({
        **data,
        "dashboard_id": dashboard.pk,
        "dashboard_name": dashboard.name,
        "widget_count": len(payload.get("widgets") or []),
        "meta": payload.get("meta") or {},
    })


# =====================================================================
# 分享链接（3）
# =====================================================================


def _share_item(share):
    """分享列表项：在 brief 基础上补报表名与过期标记（列表页需要）。"""
    item = svc.share_brief(share)
    item["report_name"] = share.report.name if share.report_id else ""
    item["report_code"] = share.report.code if share.report_id else ""
    return item


@endpoint(("GET",))
def shares_list(request):
    """分享链接列表（按报表/启用状态过滤 + 分页）。"""
    qs = scope_queryset(ReportShare.objects.select_related("report").all(),
                        request.user, "owner")
    qs = apply_q(qs, request, ["token", "note", "report__name", "report__code"])
    report_id = p(request, "report_id")
    if report_id not in (None, ""):
        report = get_report(report_id, request.user)
        qs = qs.filter(report=report)
    enabled = p(request, "enabled")
    if enabled not in (None, ""):
        qs = qs.filter(enabled=read_bool(request, "enabled", True))
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(qs, request, _share_item))


@endpoint()
def share_disable(request, pk):
    """停用分享链接（保留记录便于审计；停用后公开接口立即 400）。"""
    share = get_writable(ReportShare, pk, request.user, "分享链接")
    svc.disable_share(share)
    return ok(_share_item(share))


@endpoint()
def share_update(request, pk):
    """更新分享备注 / 有效期 / 只读开关（token 不可变更，避免已发链接失效）。"""
    share = get_writable(ReportShare, pk, request.user, "分享链接")
    with transaction.atomic():
        if p(request, "note") is not None:
            share.note = opt_str(request, "note")[:200]
        if p(request, "readonly") is not None:
            share.readonly = read_bool(request, "readonly", share.readonly)
        if p(request, "enabled") is not None:
            share.enabled = read_bool(request, "enabled", share.enabled)
        if p(request, "days") is not None:
            days = int(p(request, "days"))
            if days < 0 or days > 365:
                raise ValueError("有效天数需在 0~365 之间")
            from datetime import timedelta

            from django.utils import timezone

            share.expires_at = timezone.now() + timedelta(days=days) if days else None
        share.save()
    return ok(_share_item(share))


# =====================================================================
# 公开只读分享（1）
# =====================================================================


@api_view(("GET",))
@authentication_classes([SessionAuthentication, TokenAuthentication])
@permission_classes([AllowAny])
def public_share(request, token):
    """公开只读读取：校验 token 后执行已发布报表，不暴露任何写接口。"""
    try:
        share = svc.validate_share(token)
        report = share.report
        if report.status != "published":
            raise ValueError("报表尚未发布，分享链接暂不可用")
        params_text = request.query_params.get("params") or ""
        params = {}
        if params_text:
            import json as _json

            try:
                params = _json.loads(params_text)
            except ValueError:
                raise ValueError("参数 params 不是合法 JSON")
            if not isinstance(params, dict):
                raise ValueError("参数 params 必须是 JSON 对象")
        share.register_view()
        payload = svc.run_report(report, params, share.owner, trigger="share")
        return ok({
            "readonly": True,
            "share": {
                "token": share.token,
                "report_id": report.pk,
                "view_count": share.view_count + 1,
                "expires_at": ts(share.expires_at),
            },
            "payload": payload,
        })
    except ValueError as e:
        from devtools.common import fail

        return fail(e, status=400)
    except Exception as e:  # noqa: BLE001 —— 公开接口同样结构化降级
        from devtools.common import fail

        return fail(f"{type(e).__name__}: {e}", status=422)
