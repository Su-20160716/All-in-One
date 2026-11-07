# -*- coding: utf-8 -*-
"""模型 → 响应字典，以及列表接口的统一分页/筛选助手。

所有列表接口都返回 ``{"items", "count", "page", "page_size"}``
（项目统一约定，前端一份列表组件通吃），因此这里只写一个
``paginate``，不在每个视图里重复切页逻辑。
"""
from datetime import date, datetime

from django.utils import timezone

from devtools.common import opt_num, opt_str, p

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 200
Q_MAX_CHARS = 120


def ts(value):
    """时间统一 ISO 字符串（前端 dayjs 直接 parse）。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).isoformat() if timezone.is_aware(value) else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _base(obj):
    return {
        "id": obj.pk,
        "created_at": ts(getattr(obj, "created_at", None)),
        "updated_at": ts(getattr(obj, "updated_at", None)),
    }


# ---------------------------------------------------------------------------
# 数据源 / 数据集
# ---------------------------------------------------------------------------


def source_dict(obj, detail=False):
    data = {
        **_base(obj),
        "name": obj.name,
        "kind": obj.kind,
        "description": obj.description,
        "status": obj.status,
        "last_ok_at": ts(obj.last_ok_at),
        "last_checked_at": ts(obj.last_checked_at),
        "last_message": obj.last_message,
        "owner_id": obj.owner_id,
        "summary": obj.summarize(),
    }
    if detail:
        data["config"] = obj.config or {}
        data["dataset_count"] = obj.rep_datasets.count()
    return data


def field_dict(field):
    return {
        "id": field.pk,
        "dataset_id": field.dataset_id,
        "path": field.path,
        "alias": field.alias,
        "key": field.key,
        "ftype": field.ftype,
        "aggregate": field.aggregate,
        "is_group": field.is_group,
        "bucket": field.bucket,
        "order": field.order,
        "fmt": field.fmt,
        "visible": field.visible,
    }


def join_dict(join):
    return {
        "id": join.pk,
        "dataset_id": join.dataset_id,
        "target_model": join.target_model,
        "via": join.via,
        "left_field": join.left_field,
        "right_field": join.right_field,
        "join_type": join.join_type,
        "order": join.order,
    }


def param_dict(param):
    return {
        "id": param.pk,
        "dataset_id": param.dataset_id,
        "name": param.name,
        "ptype": param.ptype,
        "default": param.default,
        "required": param.required,
        "description": param.description,
    }


def dataset_dict(obj, detail=False, with_fields=False, with_joins=False):
    data = {
        **_base(obj),
        "name": obj.name,
        "description": obj.description,
        "primary_model": obj.primary_model,
        "source_id": obj.source_id,
        "filter": obj.filter or {},
        "distinct_fields": obj.distinct_fields or [],
        "default_limit": obj.default_limit,
        "cache_ttl": obj.cache_ttl,
        "status": obj.status,
        "owner_id": obj.owner_id,
        "last_preview_at": ts(obj.last_preview_at),
        "preview_count": obj.preview_count,
        "field_count": obj.rep_dataset_fields.count(),
        "widget_count": obj.rep_widgets.count(),
    }
    if detail or with_fields:
        data["fields"] = [field_dict(f) for f in obj.rep_dataset_fields.all().order_by("order", "id")]
    if detail:
        data["joins"] = [join_dict(j) for j in obj.rep_dataset_joins.all().order_by("order", "id")]
        data["params"] = [param_dict(x) for x in obj.rep_dataset_params.all()]
    return data


# ---------------------------------------------------------------------------
# 报表 / 页面 / 组件
# ---------------------------------------------------------------------------


def report_dict(obj, detail=False):
    data = {
        **_base(obj),
        "code": obj.code,
        "name": obj.name,
        "category": obj.category,
        "description": obj.description,
        "status": obj.status,
        "theme": obj.theme,
        "cache_ttl": obj.cache_ttl,
        "published_at": ts(obj.published_at),
        "run_count": obj.run_count,
        "last_run_at": ts(obj.last_run_at),
        "owner_id": obj.owner_id,
        "page_count": obj.rep_pages.count(),
        "share_count": obj.rep_shares.filter(enabled=True).count(),
        "favorite_count": obj.rep_favorites.count(),
    }
    if detail:
        data["permissions"] = obj.permissions or {}
        data["schedule_count"] = obj.rep_schedules.count()
        data["subscription_count"] = obj.rep_subscriptions.count()
    return data


def page_dict(obj, with_widgets=False):
    data = {
        **_base(obj),
        "report_id": obj.report_id,
        "title": obj.title,
        "description": obj.description,
        "order": obj.order,
        "layout": obj.layout or {},
        "widget_count": obj.rep_widgets.count(),
    }
    if with_widgets:
        data["widgets"] = [widget_dict(w, with_filters=True)
                           for w in obj.rep_widgets.all().order_by("order", "id")]
    return data


def widget_dict(obj, with_filters=False):
    data = {
        **_base(obj),
        "page_id": obj.page_id,
        "report_id": obj.page.report_id if obj.page_id else None,
        "type": obj.rtype,
        "title": obj.title,
        "description": obj.description,
        "dataset_id": obj.dataset_id,
        "dataset_name": obj.dataset.name if obj.dataset_id else "",
        "config": obj.config or {},
        "position": {"x": obj.x, "y": obj.y, "w": obj.w, "h": obj.h},
        "order": obj.order,
    }
    if with_filters:
        data["filters"] = [filter_dict(f) for f in obj.rep_widget_filters.all().order_by("order", "id")]
    return data


def filter_dict(obj):
    return {
        "id": obj.pk,
        "widget_id": obj.widget_id,
        "field": obj.field,
        "operator": obj.operator,
        "default_value": obj.default_value,
        "bound_param": obj.bound_param,
        "label": obj.label,
        "order": obj.order,
    }


# ---------------------------------------------------------------------------
# 执行 / 缓存 / 计划 / 订阅 / 分享
# ---------------------------------------------------------------------------


def run_dict(obj, with_result=False):
    data = {
        "id": obj.pk,
        "report_id": obj.report_id,
        "report_name": obj.report.name if obj.report_id else "",
        "trigger": obj.trigger,
        "params": obj.params or {},
        "status": obj.status,
        "duration_ms": obj.duration_ms,
        "row_count": obj.row_count,
        "error": obj.error,
        "result_size": obj.result_size,
        "started_at": ts(obj.started_at),
        "finished_at": ts(obj.finished_at),
        "created_at": ts(obj.created_at),
        "owner_id": obj.owner_id,
    }
    if with_result:
        data["result"] = obj.result or {}
    return data


def snapshot_dict(obj, with_payload=False):
    data = {
        "id": obj.pk,
        "report_id": obj.report_id,
        "params_key": obj.params_key,
        "params": obj.params or {},
        "row_count": obj.row_count,
        "expires_at": ts(obj.expires_at),
        "expired": obj.is_expired,
        "hits": obj.hits,
        "created_at": ts(obj.created_at),
        "updated_at": ts(obj.updated_at),
    }
    if with_payload:
        data["payload"] = obj.payload or {}
    return data


def schedule_dict(obj, summary=None):
    data = {
        **_base(obj),
        "report_id": obj.report_id,
        "report_name": obj.report.name if obj.report_id else "",
        "name": obj.name,
        "cron_expr": obj.cron_expr,
        "timezone": obj.timezone,
        "next_run_at": ts(obj.next_run_at),
        "last_run_at": ts(obj.last_run_at),
        "enabled": obj.enabled,
        "recipients": obj.recipients or [],
        "run_count": obj.run_count,
        "last_status": obj.last_status,
        "owner_id": obj.owner_id,
    }
    if summary:
        data["upcoming"] = summary.get("upcoming", [])
        data["cron_valid"] = summary.get("valid", True)
        data["cron_error"] = summary.get("error", "")
        data["description"] = summary.get("description", "")
    return data


def subscription_dict(obj, user_name=""):
    return {
        **_base(obj),
        "report_id": obj.report_id,
        "report_name": obj.report.name if obj.report_id else "",
        "user_id": obj.user_id,
        "user_name": user_name or getattr(obj.user, "username", "") if obj.user_id else "",
        "channel": obj.channel,
        "frequency": obj.frequency,
        "enabled": obj.enabled,
        "last_sent_at": ts(obj.last_sent_at),
        "owner_id": obj.owner_id,
    }


def dashboard_dict(obj, detail=False):
    data = {
        **_base(obj),
        "name": obj.name,
        "description": obj.description,
        "layout": obj.layout or {},
        "theme": obj.theme,
        "default_filters": obj.default_filters or {},
        "status": obj.status,
        "owner_id": obj.owner_id,
        "widget_count": obj.rep_dashboard_widgets.count(),
    }
    if detail:
        data["widgets"] = [dashboard_widget_dict(dw, with_widget=True)
                           for dw in obj.rep_dashboard_widgets.all().order_by("order", "id")]
    return data


def dashboard_widget_dict(obj, with_widget=False):
    data = {
        **_base(obj),
        "dashboard_id": obj.dashboard_id,
        "widget_id": obj.widget_id,
        "widget_title": obj.widget.title if obj.widget_id else "",
        "widget_type": obj.widget.rtype if obj.widget_id else "",
        "report_id": obj.widget.page.report_id if obj.widget_id and obj.widget.page_id else None,
        "override": obj.override or {},
        "position": {"x": obj.x, "y": obj.y, "w": obj.w, "h": obj.h},
        "order": obj.order,
    }
    if with_widget:
        data["widget"] = widget_dict(obj.widget, with_filters=True) if obj.widget_id else None
    return data


def annotation_dict(obj):
    return {
        "id": obj.pk,
        "report_id": obj.report_id,
        "widget_id": obj.widget_id,
        "widget_title": obj.widget.title if obj.widget_id else "",
        "body": obj.body,
        "data_point": obj.data_point or {},
        "color": obj.color,
        "resolved": obj.resolved,
        "owner_id": obj.owner_id,
        "created_at": ts(obj.created_at),
        "updated_at": ts(obj.updated_at),
    }


def export_job_dict(obj):
    return {
        **_base(obj),
        "report_id": obj.report_id,
        "report_name": obj.report.name if obj.report_id else "",
        "fmt": obj.fmt,
        "status": obj.status,
        "row_count": obj.row_count,
        "error": obj.error,
        "params": obj.params or {},
        "filename": obj.filename,
        "size_bytes": obj.size_bytes,
        "duration_ms": obj.duration_ms,
        "owner_id": obj.owner_id,
    }


def favorite_dict(obj):
    return {
        "id": obj.pk,
        "report_id": obj.report_id,
        "report_name": obj.report.name if obj.report_id else "",
        "report_code": obj.report.code if obj.report_id else "",
        "created_at": ts(obj.created_at),
    }


# ---------------------------------------------------------------------------
# 列表分页与筛选
# ---------------------------------------------------------------------------


def page_params(request):
    """统一分页参数：page ≥1，page_size ∈ [1,200]。"""
    page = int(opt_num(request, "page", 1, integer=True, minimum=1) or 1)
    size = int(opt_num(request, "page_size", PAGE_SIZE_DEFAULT, integer=True,
                       minimum=1, maximum=PAGE_SIZE_MAX) or PAGE_SIZE_DEFAULT)
    return page, size


def apply_q(qs, request, fields):
    """通用关键字搜索：对给定字段做 icontains 或匹配；空 q 直接跳过。"""
    keyword = opt_str(request, "q").strip()
    if not keyword:
        return qs
    if len(keyword) > Q_MAX_CHARS:
        raise ValueError(f"搜索词过长（上限 {Q_MAX_CHARS} 字符）")
    from django.db.models import Q

    cond = Q()
    for field in fields:
        cond |= Q(**{f"{field}__icontains": keyword})
    return qs.filter(cond).distinct()


def apply_status(qs, request, field="status"):
    """状态筛选：只接受调用方声明的已知状态（避免拼任意 lookup）。"""
    status = opt_str(request, "status").strip()
    if not status:
        return qs
    return qs.filter(**{field: status})


def paginate(qs, request, serializer, size_default=PAGE_SIZE_DEFAULT):
    """统一列表响应：items/count/page/page_size。"""
    page = int(opt_num(request, "page", 1, integer=True, minimum=1) or 1)
    size = int(opt_num(request, "page_size", size_default, integer=True,
                       minimum=1, maximum=PAGE_SIZE_MAX) or size_default)
    count = qs.count()
    offset = (page - 1) * size
    items = [serializer(obj) for obj in qs[offset:offset + size]]
    return {"items": items, "count": count, "page": page, "page_size": size}


def body_list(request, key, max_items=100):
    """取数组入参并做长度上限（批量保存字段/组件时用）。"""
    value = p(request, key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_items:
        raise ValueError(f"参数 {key} 最多 {max_items} 项")
    return value
