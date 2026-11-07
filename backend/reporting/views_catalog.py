# -*- coding: utf-8 -*-
"""目录与元信息接口：catalog / 模型白名单 / 枚举 / 公式 / cron 预览。

这些接口都是「只读 + 无副作用」的，前端进入模块先打 catalog 拿到
接口清单与枚举，再按需渲染表单；公式与 cron 提供独立的校验接口，
让用户在保存前就知道表达式对不对。
"""
from django.urls import get_resolver

from core.scoping import scope_queryset
from devtools.common import endpoint, endpoint_index, ok, opt_str, p

from reporting import cron as cron_mod
from reporting import formula as formula_mod
from reporting.models import (
    AGGREGATES, BUCKETS, DASHBOARD_STATUS, EXPORT_FORMATS, FIELD_TYPES,
    JOB_STATUS, JOIN_TYPES, MODEL_REGISTRY, PARAM_TYPES, REPORT_STATUS,
    RUN_TRIGGERS, SOURCE_KINDS, SOURCE_STATUS, SUB_CHANNELS, SUB_FREQUENCIES,
    WIDGET_TYPES, Dashboard, DataSource, Dataset, ReportDefinition, ReportRun,
    ReportSchedule,
)
from reporting import services as svc
from reporting.views_common import read_json_obj, read_str_list

CATALOG_VERSION = "1.0"


def urlpatterns_of_app():
    """懒加载本 app 的 urlpatterns（放在函数里避免与 urls.py 循环导入）。"""
    from reporting import urls as reporting_urls

    return reporting_urls.urlpatterns


@endpoint(("GET",))
def catalog(request):
    """报表模块目录：接口清单 + 模型白名单 + 枚举 + 当前规模。"""
    patterns = urlpatterns_of_app()
    endpoints = endpoint_index(patterns, exclude=("",))
    user = request.user
    counts = {
        "sources": scope_queryset(DataSource.objects.all(), user, "owner").count(),
        "datasets": scope_queryset(Dataset.objects.all(), user, "owner").count(),
        "reports": scope_queryset(ReportDefinition.objects.all(), user, "owner").count(),
        "dashboards": scope_queryset(Dashboard.objects.all(), user, "owner").count(),
        "runs": scope_queryset(ReportRun.objects.all(), user, "owner").count(),
        "schedules": scope_queryset(ReportSchedule.objects.all(), user, "owner").count(),
    }
    return ok({
        "name": "报表与仪表盘",
        "version": CATALOG_VERSION,
        "prefix": "/api/reporting/",
        "endpoint_count": len(endpoints),
        "endpoints": endpoints,
        "models": svc.whitelist_entries(),
        "model_count": len(svc.whitelist_labels()),
        "counts": counts,
        "enums": {
            "source_kinds": SOURCE_KINDS,
            "source_status": SOURCE_STATUS,
            "field_types": FIELD_TYPES,
            "aggregates": AGGREGATES,
            "buckets": BUCKETS,
            "join_types": JOIN_TYPES,
            "param_types": PARAM_TYPES,
            "report_status": REPORT_STATUS,
            "widget_types": WIDGET_TYPES,
            "run_triggers": RUN_TRIGGERS,
            "export_formats": EXPORT_FORMATS,
            "job_status": JOB_STATUS,
            "sub_channels": SUB_CHANNELS,
            "sub_frequencies": SUB_FREQUENCIES,
            "dashboard_status": DASHBOARD_STATUS,
            "operators": sorted(svc.OPERATORS.keys()),
            "relative_keywords": sorted(svc.RELATIVE_KEYWORDS.keys()),
            "formula_functions": sorted(formula_mod.FUNCTIONS.keys()),
        },
        "capabilities": {
            "model_whitelist": True,
            "time_buckets": [b[0] for b in BUCKETS if b[0]],
            "export_formats": [f[0] for f in EXPORT_FORMATS],
            "kpi_comparisons": ["yoy", "mom", "qoq", "wow", "dod"],
            "median_simulation": True,
            "network_probe": False,
        },
    })


@endpoint(("GET",))
def models_list(request):
    """模型白名单（支持 q 模糊搜索 + 分页）。"""
    keyword = opt_str(request, "q").strip().lower()
    entries = svc.whitelist_entries()
    if keyword:
        entries = [
            item for item in entries
            if keyword in item["label"].lower()
            or keyword in item["verbose_name"].lower()
            or keyword in item["model"].lower()
        ]
    page = int(p(request, "page") or 1)
    size = int(p(request, "page_size") or 50)
    page = max(1, page)
    size = max(1, min(size, 200))
    start = (page - 1) * size
    return ok({
        "items": entries[start:start + size],
        "count": len(entries),
        "page": page,
        "page_size": size,
    })


@endpoint(("GET",))
def model_detail_view(request, label):
    """单个模型的字段与关系明细（数据集字段选择器用）。"""
    info = svc.model_detail(label)
    info["writable_hint"] = "数据集只读，写入需在业务模块完成"
    return ok(info)


@endpoint(("GET",))
def model_fields_view(request, label):
    """模型字段清单（只返回字段元信息，不含任何数据行）。"""
    fields = svc.model_fields(label)
    return ok({"label": label, "items": fields, "count": len(fields)})


@endpoint(("GET",))
def meta_options(request):
    """枚举字典：前端表单下拉统一从这里取，避免前后端常量漂移。"""
    return ok({
        "source_kinds": SOURCE_KINDS,
        "source_status": SOURCE_STATUS,
        "field_types": FIELD_TYPES,
        "aggregates": AGGREGATES,
        "buckets": BUCKETS,
        "join_types": JOIN_TYPES,
        "param_types": PARAM_TYPES,
        "report_status": REPORT_STATUS,
        "widget_types": WIDGET_TYPES,
        "run_triggers": RUN_TRIGGERS,
        "export_formats": EXPORT_FORMATS,
        "sub_channels": SUB_CHANNELS,
        "sub_frequencies": SUB_FREQUENCIES,
        "dashboard_status": DASHBOARD_STATUS,
        "operators": sorted(svc.OPERATORS.keys()),
        "relative_keywords": sorted(svc.RELATIVE_KEYWORDS.keys()),
        "formula_functions": sorted(formula_mod.FUNCTIONS.keys()),
    })


@endpoint()
def formula_eval(request):
    """求值一个公式：body {formula, variables:{...}} → 数值 + 变量快照。

    只做数值计算，不读业务数据；用于 KPI 卡片编辑时的即时试算。
    """
    expr = str(p(request, "formula") or "").strip()
    if not expr:
        raise ValueError("缺少必填参数: formula")
    variables = read_json_obj(request, "variables", {})
    if len(variables) > 200:
        raise ValueError("变量不能超过 200 个")
    value = svc.evaluate_formula(expr, variables)
    normalized = formula_mod.normalize_variables(variables)
    return ok({
        "formula": expr,
        "value": round(value, 6),
        "variables": normalized,
        "functions": sorted(formula_mod.FUNCTIONS.keys()),
    })


@endpoint()
def formula_validate(request):
    """校验公式语法（可选 sample_keys 做试算），保存前先挡一层。"""
    expr = str(p(request, "formula") or "").strip()
    if not expr:
        raise ValueError("缺少必填参数: formula")
    sample_keys = read_str_list(request, "sample_keys", max_items=200)
    svc.validate_formula(expr, sample_keys or None)
    tokens = formula_mod.tokenize(expr)
    return ok({
        "formula": expr,
        "valid": True,
        "token_count": len(tokens),
        "functions_used": sorted({
            t.value.lower() for t in tokens
            if t.kind == "name" and t.value.lower() in formula_mod.FUNCTIONS
        }),
    })


@endpoint()
def cron_preview(request):
    """cron 预览：返回中文描述 + 未来 N 次运行时间（不落库）。"""
    expr = str(p(request, "cron") or p(request, "cron_expr") or "").strip()
    if not expr:
        raise ValueError("缺少必填参数: cron")
    tz_name = str(p(request, "timezone") or "Asia/Shanghai").strip()
    count = int(p(request, "count") or 5)
    count = max(1, min(count, 20))
    runs = cron_mod.next_runs(expr, tz_name, count)
    spec = cron_mod.parse_cron(expr)
    return ok({
        "cron": expr,
        "timezone": tz_name,
        "description": cron_mod.describe(expr),
        "fields": spec.as_dict(),
        "upcoming": [r.isoformat() for r in runs],
        "next_run_at": runs[0].isoformat() if runs else None,
    })


@endpoint(("GET",))
def registry_summary(request):
    """模型注册表规模（自检用：确认 19 张表都注册在案）。"""
    items = []
    for name, model in sorted(MODEL_REGISTRY.items()):
        items.append({
            "key": name,
            "model": model._meta.label,
            "verbose_name": str(model._meta.verbose_name),
            "field_count": len(model._meta.concrete_fields),
        })
    return ok({"items": items, "count": len(items)})


@endpoint(("GET",))
def resolver_sanity(request):
    """路由自检：统计 /api/reporting/ 下已注册的路径数（排障用）。"""
    resolver = get_resolver()
    prefixes = [str(pat.pattern) for pat in resolver.url_patterns]
    return ok({
        "api_prefix_present": "api/reporting/" in prefixes,
        "endpoint_count": len(urlpatterns_of_app()),
        "prefixes_sampled": [p for p in prefixes if p.startswith("api/")][:5],
    })
