# -*- coding: utf-8 -*-
"""报表执行器：数据集取数 → 组件后处理 → 报表编排 → 结果缓存。

分层
----
1. ``run_dataset``      ：数据集 → columns/rows/meta（编译器）。
2. ``execute_widget``   ：按组件类型做后处理（KPI 公式、透视矩阵、热力范围…）。
3. ``run_report``       ：页面/组件编排 + ReportRun 流水 + ReportSnapshot 缓存。
4. ``dashboard_payload``：仪表盘跨报表复用「最新快照」，避免打开看板就全量重算。

失败策略
--------
单组件失败**不拖垮整张报表**：异常写进该组件的 ``result.meta.error``，
报表整体仍返回，``meta.failed_widgets`` 记录失败数。这样前端能部分渲染，
也便于「哪个组件坏了」的定位。只有缓存读写等基础设施异常才整单失败。
"""
import hashlib
import json
from time import perf_counter

from django.db import transaction
from django.utils import timezone

from reporting import compiler, formula
from reporting.export import widget_columns
from reporting.models import (
    ReportDefinition, ReportPage, ReportRun, ReportSnapshot,
    ReportWidget, snapshot_expiry,
)

EMPTY_RESULT = {"columns": [], "rows": [], "meta": {}}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def params_key(params):
    """参数指纹：键排序后 sha256，保证同参数同缓存。"""
    try:
        raw = json.dumps(params or {}, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        raw = str(params)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def combine_filters(base, extra):
    """把数据集过滤与组件过滤合成 AND（两者都空则空）。"""
    has_base = bool(base) and base not in ({}, [])
    has_extra = bool(extra) and extra not in ({}, [])
    if has_base and has_extra:
        return {"and": [base, extra]}
    if has_base:
        return base
    if has_extra:
        return extra
    return {}


def ensure_result(result):
    """结果结构兜底：前端契约是 columns/rows/meta 三件套，缺一不可。"""
    if not isinstance(result, dict):
        return dict(EMPTY_RESULT)
    out = dict(result)
    out.setdefault("columns", [])
    out.setdefault("rows", [])
    out.setdefault("meta", {})
    if not isinstance(out["columns"], list):
        out["columns"] = []
    if not isinstance(out["rows"], list):
        out["rows"] = []
    if not isinstance(out["meta"], dict):
        out["meta"] = {}
    return out


def result_error(message, meta=None):
    """构造「结构化失败」结果：前端显示 error 而不是白屏。"""
    payload = dict(EMPTY_RESULT)
    payload["meta"] = {"error": str(message)[:1000], **(meta or {})}
    return payload


def widget_filter_defaults(widget):
    """组件筛选器默认值 → 参数表（仅绑定到数据集参数的才参与取数）。"""
    out = {}
    for f in widget.rep_widget_filters.all():
        if f.bound_param and f.default_value not in (None, ""):
            out[f.bound_param] = f.default_value
    return out


def widget_config(widget):
    """组件配置（dict 兜底）。"""
    return widget.config if isinstance(widget.config, dict) else {}


# ---------------------------------------------------------------------------
# 数据集执行
# ---------------------------------------------------------------------------


def run_dataset(dataset, params=None, overrides=None, shift=None):
    """执行数据集：spec 合成 → 编译 → 结果（含列定义与元信息）。"""
    if dataset is None:
        raise ValueError("数据集不存在")
    if dataset.status != "active":
        raise ValueError(f"数据集 {dataset.name} 已停用")
    spec = compiler.dataset_spec(dataset, overrides)
    if shift:
        spec["shift"] = shift
    result = compiler.compile_query(spec, params or {})
    meta = result.setdefault("meta", {})
    meta["dataset"] = {"id": dataset.pk, "name": dataset.name}
    return result


# ---------------------------------------------------------------------------
# 组件后处理
# ---------------------------------------------------------------------------


def execute_widget(widget, params=None, limit=None, dataset_cache=None):
    """执行单个组件，返回 {columns, rows, meta}（永不抛异常给调用方）。"""
    try:
        return _execute_widget(widget, params or {}, limit, dataset_cache)
    except ValueError as e:
        return result_error(e, {"widget_id": getattr(widget, "pk", None)})
    except Exception as e:  # noqa: BLE001 —— 组件级兜底，坏一个组件不炸整张报表
        return result_error(f"{type(e).__name__}: {e}",
                            {"widget_id": getattr(widget, "pk", None)})


def _execute_widget(widget, params, limit, dataset_cache):
    rtype = widget.rtype
    config = widget_config(widget)
    if rtype == "text":
        return {
            "columns": [],
            "rows": [{"text": str(config.get("text") or widget.description or "")[:5000]}],
            "meta": {"type": "text", "align": config.get("align", "left")},
        }

    if widget.dataset_id is None:
        raise ValueError(f"组件「{widget.title}」未绑定数据集")

    dataset = widget.dataset
    merged_params = {**widget_filter_defaults(widget), **params}
    overrides = {}
    if config.get("filter"):
        overrides["filter"] = combine_filters(dataset.filter, config.get("filter"))
    if config.get("having"):
        overrides["having"] = config["having"]
    if config.get("order"):
        overrides["order"] = compiler.normalize_order(config["order"])
    effective_limit = limit or config.get("limit") or dataset.default_limit
    overrides["limit"] = compiler.clamp_limit(effective_limit)

    cache_key = None
    if dataset_cache is not None:
        cache_key = json.dumps({
            "dataset": dataset.pk,
            "params": merged_params,
            "overrides": overrides,
            "shift": "base",
        }, ensure_ascii=False, sort_keys=True, default=str)
        if cache_key in dataset_cache:
            base_result = dataset_cache[cache_key]
        else:
            base_result = run_dataset(dataset, merged_params, overrides)
            dataset_cache[cache_key] = base_result
    else:
        base_result = run_dataset(dataset, merged_params, overrides)

    if rtype == "kpi":
        return _kpi_result(widget, dataset, merged_params, overrides, config, base_result, dataset_cache)
    if rtype in ("pivot", "heatmap"):
        return _pivot_result(widget, config, base_result, rtype)
    return _chart_result(widget, config, base_result, rtype)


def _chart_result(widget, config, base_result, rtype):
    """表格/柱/折线/饼：数据集结果直接可用，补图表语义元信息。"""
    result = ensure_result(base_result)
    meta = dict(result.get("meta") or {})
    columns = result.get("columns") or []
    x_key = config.get("x") or (columns[0]["key"] if columns else "")
    series = config.get("series")
    if series is None:
        series = [c["key"] for c in columns if c.get("role") == "metric"][:6]
    if not isinstance(series, list):
        series = [str(series)]
    if x_key and x_key not in {c["key"] for c in columns}:
        raise ValueError(f"组件的 X 轴字段 {x_key} 不在数据集输出列内")
    bad = [s for s in series if s not in {c["key"] for c in columns}]
    if bad:
        raise ValueError(f"组件的系列字段 {','.join(map(str, bad))} 不在数据集输出列内")
    meta.update({
        "type": rtype,
        "x": x_key,
        "series": series,
        "stacked": bool(config.get("stacked")),
        "show_legend": bool(config.get("show_legend", True)),
        "widget_id": widget.pk,
    })
    if rtype == "line":
        grain = config.get("grain") or ""
        bucket_col = next((c for c in columns if c.get("bucket")), None)
        if bucket_col and config.get("fill_gaps", True):
            result["rows"] = compiler.fill_bucket_gaps(
                result["rows"], bucket_col["key"], bucket_col.get("bucket") or grain or "month",
            )
            meta["filled_gaps"] = bucket_col.get("bucket") or grain or "month"
    if rtype == "pie":
        value_keys = series or [c["key"] for c in columns if c.get("role") == "metric"]
        meta["value"] = value_keys[0] if value_keys else ""
        meta["name"] = x_key
        rows = result.get("rows") or []
        if meta["value"]:
            total = sum(float(r.get(meta["value"]) or 0) for r in rows if isinstance(r, dict))
            for row in rows:
                if isinstance(row, dict):
                    row["_share_pct"] = formula.safe_share(row.get(meta["value"]), total)
            meta["total"] = round(total, 6)
    return result


def _kpi_result(widget, dataset, params, overrides, config, base_result, dataset_cache):
    """指标卡：可选公式 + 同比/环比对照 + 上期值。

    对照周期通过「时间区间整体平移」实现：把数据集里 relative 过滤的区间
    往前挪一个周期再算一次，这样同比/环比口径与主指标完全一致。
    """
    base = ensure_result(base_result)
    rows = base.get("rows") or []
    if not rows:
        raise ValueError("KPI 组件的数据集没有返回任何行")
    current_row = rows[0]
    columns = base.get("columns") or []
    metric_keys = [c["key"] for c in columns if c.get("role") == "metric"]
    metric = str(config.get("metric") or (metric_keys[0] if metric_keys else ""))
    if metric and metric not in current_row:
        raise ValueError(f"KPI 指标 {metric} 不在数据集输出列内")
    expr = str(config.get("formula") or metric)
    if not expr:
        raise ValueError("KPI 组件缺少 formula 或 metric 配置")
    variables = formula.formula_variables(columns, current_row)
    digits = int(config.get("digits", 2))
    try:
        value = formula.evaluate_round(expr, variables, digits)
    except ValueError as e:
        raise ValueError(f"KPI 公式错误：{e}")

    comparison = str(config.get("compare") or "none")
    shift = compiler.shift_for_comparison(comparison)
    previous = None
    previous_row = None
    if shift:
        key = json.dumps({"dataset": dataset.pk, "params": params, "overrides": overrides,
                          "shift": shift}, ensure_ascii=False, sort_keys=True, default=str)
        if dataset_cache is not None and key in dataset_cache:
            prev_result = dataset_cache[key]
        else:
            prev_result = run_dataset(dataset, params, overrides, shift=shift)
            if dataset_cache is not None:
                dataset_cache[key] = prev_result
        prev_rows = (prev_result.get("rows") or [])
        if prev_rows:
            previous_row = prev_rows[0]
            try:
                previous = formula.evaluate_round(
                    expr, formula.formula_variables(prev_result.get("columns") or [], previous_row), digits,
                )
            except ValueError:
                previous = None

    delta = round(value - previous, 4) if previous is not None else None
    payload_row = {
        "label": config.get("label") or widget.title,
        "value": value,
        "previous": previous,
        "delta": delta,
        "delta_pct": formula.safe_pct_change(value, previous) if previous is not None else None,
    }
    meta = {
        "type": "kpi",
        "widget_id": widget.pk,
        "metric": metric,
        "formula": expr,
        "comparison": comparison,
        "unit": config.get("unit", ""),
        "digits": digits,
        "target": config.get("target"),
        "base_columns": [c.get("key") for c in columns],
        "dataset": {"id": dataset.pk, "name": dataset.name},
    }
    if config.get("target") is not None:
        try:
            target = float(config["target"])
            meta["achievement_pct"] = round(value / target * 100, 2) if target else None
        except (TypeError, ValueError):
            meta["achievement_pct"] = None
    return {
        "columns": [
            {"key": "label", "label": "指标", "type": "string", "role": "dimension"},
            {"key": "value", "label": "当前值", "type": "number", "role": "metric"},
            {"key": "previous", "label": "上期值", "type": "number", "role": "metric"},
            {"key": "delta", "label": "变化量", "type": "number", "role": "metric"},
            {"key": "delta_pct", "label": "变化率%", "type": "number", "role": "metric"},
        ],
        "rows": [payload_row],
        "meta": meta,
    }


def _pivot_result(widget, config, base_result, rtype):
    """透视表 / 热力图：行维度 × 列维度 → 矩阵，附带行合计与全局极值。"""
    base = ensure_result(base_result)
    columns = base.get("columns") or []
    rows = base.get("rows") or []
    keys = [c.get("key") for c in columns]
    row_dim = str(config.get("row_dim") or (keys[0] if keys else ""))
    col_dim = str(config.get("col_dim") or (keys[1] if len(keys) > 1 else ""))
    value = str(config.get("value") or "")
    if not value:
        metric_keys = [c["key"] for c in columns if c.get("role") == "metric"]
        value = metric_keys[0] if metric_keys else (keys[-1] if keys else "")
    for label, key in (("行维度", row_dim), ("列维度", col_dim), ("值字段", value)):
        if key not in keys:
            raise ValueError(f"透视的{label} {key} 不在数据集输出列内")
    if row_dim == col_dim:
        raise ValueError("透视的行维度与列维度不能相同")

    row_keys = []
    col_keys = []
    cells = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rk = row.get(row_dim)
        ck = row.get(col_dim)
        rk_key = "" if rk is None else str(rk)
        ck_key = "" if ck is None else str(ck)
        if rk_key not in row_keys:
            row_keys.append(rk_key)
        if ck_key not in col_keys:
            col_keys.append(ck_key)
        try:
            number = float(row.get(value) or 0)
        except (TypeError, ValueError):
            number = 0.0
        cells[(rk_key, ck_key)] = round(number, 6)

    row_keys = sort_labels(row_keys)[:200]
    col_keys = sort_labels(col_keys)[:60]
    out_columns = [{"key": "row", "label": row_dim, "type": "string", "role": "dimension"}]
    out_columns += [{"key": f"c__{ck}", "label": ck or "（空）", "type": "number", "role": "metric"}
                    for ck in col_keys]
    out_columns.append({"key": "row_total", "label": "合计", "type": "number", "role": "metric"})
    out_rows = []
    all_values = []
    for rk in row_keys:
        row = {"row": rk}
        total = 0.0
        for ck in col_keys:
            v = cells.get((rk, ck))
            row[f"c__{ck}"] = v
            if v is not None:
                total += v
                all_values.append(v)
        row["row_total"] = round(total, 6)
        out_rows.append(row)

    meta = {
        "type": rtype,
        "widget_id": widget.pk,
        "row_dim": row_dim,
        "col_dim": col_dim,
        "value": value,
        "row_count": len(out_rows),
        "col_count": len(col_keys),
    }
    if rtype == "heatmap":
        meta["heatmap"] = {
            "min": round(min(all_values), 6) if all_values else None,
            "max": round(max(all_values), 6) if all_values else None,
        }
    return {"columns": out_columns, "rows": out_rows, "meta": meta}


def sort_labels(labels):
    """标签排序：能转数字按数值，否则按字符串（保证矩阵行列稳定）。"""
    def key(value):
        try:
            return (0, float(value), "")
        except (TypeError, ValueError):
            return (1, 0.0, str(value))
    return sorted(labels, key=key)


# ---------------------------------------------------------------------------
# 报表编排
# ---------------------------------------------------------------------------


def build_report_payload(report, params, run_id=None, trigger="manual",
                         dataset_cache=None, limit=None):
    """按页面/组件执行整张报表，返回前端可直接渲染的结构。"""
    pages = report.rep_pages.all().order_by("order", "id")
    page_payloads = []
    widget_count = 0
    failed = 0
    row_total = 0
    dataset_cache = dataset_cache if dataset_cache is not None else {}

    for page in pages:
        widgets = page.rep_widgets.select_related("dataset").all().order_by("order", "id")
        widget_payloads = []
        for widget in widgets:
            widget_count += 1
            result = execute_widget(widget, params, limit=limit, dataset_cache=dataset_cache)
            meta = result.get("meta") or {}
            if meta.get("error"):
                failed += 1
            row_total += len(result.get("rows") or [])
            widget_payloads.append(widget_payload(widget, result))
        page_payloads.append({
            "id": page.pk,
            "title": page.title,
            "description": page.description,
            "order": page.order,
            "layout": page.layout or {},
            "widgets": widget_payloads,
        })

    return {
        "report": report_brief(report),
        "pages": page_payloads,
        "params": params or {},
        "meta": {
            "run_id": run_id,
            "trigger": trigger,
            "widget_count": widget_count,
            "failed_widgets": failed,
            "row_total": row_total,
            "page_count": len(page_payloads),
            "generated_at": timezone.now().isoformat(),
        },
    }


def report_brief(report):
    return {
        "id": report.pk,
        "code": report.code,
        "name": report.name,
        "category": report.category,
        "status": report.status,
        "theme": report.theme,
        "description": report.description,
        "cache_ttl": report.cache_ttl,
        "owner_id": report.owner_id,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


def widget_payload(widget, result):
    """组件输出：配置 + 结果 + 筛选器声明（前端渲染与联动都靠它）。"""
    return {
        "id": widget.pk,
        "type": widget.rtype,
        "title": widget.title,
        "description": widget.description,
        "dataset_id": widget.dataset_id,
        "config": widget.config or {},
        "position": {"x": widget.x, "y": widget.y, "w": widget.w, "h": widget.h},
        "order": widget.order,
        "filters": [
            {
                "id": f.pk, "field": f.field, "operator": f.operator,
                "default_value": f.default_value, "bound_param": f.bound_param,
                "label": f.label,
            }
            for f in widget.rep_widget_filters.all().order_by("order", "id")
        ],
        "result": ensure_result(result),
    }


def get_valid_snapshot(report, key):
    """取未过期的缓存快照（不存在返回 None）。"""
    return ReportSnapshot.objects.filter(
        report=report, params_key=key, expires_at__gt=timezone.now(),
    ).first()


def save_snapshot(report, key, params, payload, row_count, ttl, owner):
    """写入/刷新快照（唯一约束下用 update_or_create，避免并发插入冲突）。"""
    if ttl <= 0:
        return None
    expires = snapshot_expiry(ttl)
    snap, _created = ReportSnapshot.objects.update_or_create(
        report=report,
        params_key=key,
        defaults={
            "params": params or {},
            "payload": payload,
            "row_count": row_count,
            "expires_at": expires,
            "owner": owner,
        },
    )
    return snap


def run_report(report, params=None, user=None, trigger="manual", bypass_cache=False):
    """执行报表：写 Run 流水 + 命中/写入 Snapshot，返回结构化结果。

    返回值 ``meta.cached=True`` 表示这是缓存结果（同时记一条 trigger=cache 的
    Run，让「执行次数」与真实请求次数一致）。
    """
    params = params or {}
    user = user or report.owner
    key = params_key(params)
    started_wall = perf_counter()
    run = ReportRun.objects.create(
        report=report, trigger=trigger, params=params, status="running",
        owner=user, started_at=timezone.now(),
    )

    if not bypass_cache:
        snap = get_valid_snapshot(report, key)
        if snap is not None:
            payload = dict(snap.payload or {})
            meta = dict(payload.get("meta") or {})
            meta.update({
                "run_id": run.pk,
                "cached": True,
                "snapshot_id": snap.pk,
                "cache_expires_at": snap.expires_at.isoformat() if snap.expires_at else None,
                "generated_at": meta.get("generated_at") or timezone.now().isoformat(),
            })
            payload["meta"] = meta
            snap.touch_hit()
            run.trigger = "cache" if trigger == "manual" else trigger
            run.finish_success(payload, int(snap.row_count or 0))
            report.mark_run(snap.row_count)
            payload["meta"]["duration_ms"] = int((perf_counter() - started_wall) * 1000)
            return payload

    try:
        payload = build_report_payload(report, params, run_id=run.pk, trigger=trigger)
    except Exception as e:  # noqa: BLE001 —— 执行失败结构化返回，不抛 500
        run.finish_failure(f"{type(e).__name__}: {e}")
        payload = {
            "report": report_brief(report),
            "pages": [],
            "params": params,
            "meta": {
                "run_id": run.pk,
                "trigger": trigger,
                "status": "failed",
                "error": str(e)[:1000],
                "cached": False,
                "duration_ms": int((perf_counter() - started_wall) * 1000),
            },
        }
        return payload

    row_total = int(payload.get("meta", {}).get("row_total") or 0)
    ttl = report.effective_cache_ttl
    payload["meta"]["cached"] = False
    payload["meta"]["cache_ttl"] = ttl
    try:
        with transaction.atomic():
            if ttl > 0:
                snap = save_snapshot(report, key, params, payload, row_total, ttl, user)
                if snap is not None:
                    payload["meta"]["snapshot_id"] = snap.pk
                    # 结果里带上过期时间，前端可做「数据新鲜度」提示
                    payload["meta"]["cache_expires_at"] = snap.expires_at.isoformat()
            run.finish_success(payload, row_total)
            report.mark_run(row_total)
    except Exception as e:  # noqa: BLE001 —— 缓存写失败不应让用户拿不到结果
        payload["meta"]["cache_error"] = f"{type(e).__name__}: {e}"
        if run.status == "running":
            run.finish_failure(str(e))
    payload["meta"]["duration_ms"] = int((perf_counter() - started_wall) * 1000)
    return payload


def preview_report(report, params=None, user=None, limit=20, bypass_cache=True):
    """报表预览：限制每个组件行数、不写 Run/Snapshot（避免调样式时刷脏流水）。"""
    params = params or {}
    payload = build_report_payload(report, params, trigger="preview", limit=limit)
    payload["meta"]["preview"] = True
    payload["meta"]["limit"] = limit
    payload["meta"]["cached"] = False
    if bypass_cache:
        payload["meta"]["cache_bypassed"] = True
    return payload


def latest_snapshot(report, valid_only=False):
    """报表最近一次快照（仪表盘复用「最后一次算好的结果」）。"""
    qs = ReportSnapshot.objects.filter(report=report)
    if valid_only:
        qs = qs.filter(expires_at__gt=timezone.now())
    return qs.order_by("-updated_at", "-id").first()


def latest_widget_result(widget):
    """从所属报表的最新快照里取该组件的上次结果；取不到返回 None。"""
    page = widget.page
    if page is None or page.report_id is None:
        return None
    snap = latest_snapshot(page.report)
    if snap is None:
        return None
    payload = snap.payload or {}
    for p in payload.get("pages") or []:
        for w in p.get("widgets") or []:
            if int(w.get("id") or 0) == widget.pk:
                result = ensure_result(w.get("result") or {})
                result["meta"] = {**result.get("meta", {}), "from_snapshot": snap.pk,
                                  "snapshot_updated_at": snap.updated_at.isoformat()}
                return result
    return None


# ---------------------------------------------------------------------------
# 仪表盘
# ---------------------------------------------------------------------------


def dashboard_payload(dashboard, params=None, refresh=False):
    """仪表盘详情：组件按 DashboardWidget 排列。

    结果优先复用「所属报表最新快照」——打开看板不该把 N 张报表全量重算；
    没有快照（或 refresh=True）才实时执行该组件，保证首屏也有数据。
    """
    params = params or {}
    links = (dashboard.rep_dashboard_widgets
             .select_related("widget", "widget__page", "widget__page__report", "widget__dataset")
             .all().order_by("order", "id"))
    items = []
    failed = 0
    for link in links:
        widget = link.widget
        override = link.override if isinstance(link.override, dict) else {}
        result = None if refresh else latest_widget_result(widget)
        if result is None:
            result = execute_widget(widget, params, limit=override.get("limit"))
        if (result.get("meta") or {}).get("error"):
            failed += 1
        merged_config = {**(widget.config or {}), **override}
        items.append({
            "id": link.pk,
            "widget_id": widget.pk,
            "type": widget.rtype,
            "title": override.get("title") or widget.title,
            "report_id": widget.page.report_id if widget.page_id else None,
            "report_name": widget.page.report.name if widget.page_id and widget.page.report_id else "",
            "page_id": widget.page_id,
            "dataset_id": widget.dataset_id,
            "config": merged_config,
            "position": {
                "x": link.x if link.x is not None else widget.x,
                "y": link.y if link.y is not None else widget.y,
                "w": link.w if link.w is not None else widget.w,
                "h": link.h if link.h is not None else widget.h,
            },
            "result": ensure_result(result),
        })
    return {
        "dashboard": {
            "id": dashboard.pk,
            "name": dashboard.name,
            "description": dashboard.description,
            "theme": dashboard.theme,
            "layout": dashboard.layout or {},
            "default_filters": dashboard.default_filters or {},
            "status": dashboard.status,
            "owner_id": dashboard.owner_id,
            "updated_at": dashboard.updated_at.isoformat() if dashboard.updated_at else None,
        },
        "widgets": items,
        "meta": {
            "widget_count": len(items),
            "failed_widgets": failed,
            "generated_at": timezone.now().isoformat(),
            "filters": {**(dashboard.default_filters or {}), **params},
        },
    }


def dashboard_flat_rows(dashboard, params=None):
    """仪表盘导出用的行数据（保留组件分节所需的最小信息）。"""
    payload = dashboard_payload(dashboard, params)
    out = []
    for item in payload.get("widgets") or []:
        result = item.get("result") or {}
        out.append({
            "id": item.get("widget_id"),
            "title": item.get("title"),
            "type": item.get("type"),
            "columns": widget_columns(result),
            "rows": result.get("rows") or [],
        })
    return out


# ---------------------------------------------------------------------------
# 报表克隆
# ---------------------------------------------------------------------------


def clone_report(report, user, code=None, name=None):
    """深拷贝报表（页面/组件/筛选器/数据集引用），编码冲突自动加后缀。"""
    with transaction.atomic():
        new_code = code or _unique_code(report, user)
        clone = ReportDefinition.objects.create(
            code=new_code,
            name=name or f"{report.name} 副本",
            category=report.category,
            description=report.description,
            status="draft",
            permissions=report.permissions or {},
            theme=report.theme,
            cache_ttl=report.cache_ttl,
            owner=user,
        )
        for page in report.rep_pages.all().order_by("order", "id"):
            new_page = ReportPage.objects.create(
                report=clone, title=page.title, description=page.description,
                order=page.order, layout=page.layout or {},
            )
            for widget in page.rep_widgets.all().order_by("order", "id"):
                new_widget = ReportWidget.objects.create(
                    page=new_page, rtype=widget.rtype, title=widget.title,
                    description=widget.description, dataset=widget.dataset,
                    config=widget.config or {}, x=widget.x, y=widget.y,
                    w=widget.w, h=widget.h, order=widget.order,
                )
                for f in widget.rep_widget_filters.all().order_by("order", "id"):
                    new_widget.rep_widget_filters.create(
                        field=f.field, operator=f.operator, default_value=f.default_value,
                        bound_param=f.bound_param, label=f.label, order=f.order,
                    )
    return clone


def _unique_code(report, user):
    base = f"{report.code}-copy"
    candidate = base
    idx = 1
    while ReportDefinition.objects.filter(owner=user, code=candidate).exists():
        idx += 1
        candidate = f"{base}{idx}"
    return candidate[:80]
