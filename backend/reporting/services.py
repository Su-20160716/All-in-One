# -*- coding: utf-8 -*-
"""服务层门面：视图只依赖本模块，内部实现按职责拆分到子模块。

- whitelist  ：模型白名单 / 字段路径解析（安全边界）
- compiler   ：过滤编译、聚合、分组、分桶、排序分页
- formula    ：公式求值（自写 tokenizer + 递归下降，禁 eval）
- executor   ：数据集/组件/报表/仪表盘执行与结果缓存
- cron       ：5 段 cron 解析与下一次运行时间
- export     ：CSV/JSON 导出（公式注入防护）
- sharing    ：分享 token
- stats      ：执行统计与数据质量检查

视图层统一 ``from reporting import services as svc``，避免到处 import
子模块导致依赖关系散乱；测试也可以直接对服务层做单元测试。
"""
from devtools.common import p

from reporting.compiler import (  # noqa: F401
    DEFAULT_LIMIT, MAX_LIMIT, OPERATORS, RELATIVE_KEYWORDS, clamp_limit,
    clamp_offset, coalesce_zero, compile_filter, compile_query, dataset_spec,
    distinct_values, fill_bucket_gaps, merge_overrides, normalize_having,
    normalize_order, preview_count, quick_preview, resolve_params,
    resolve_relative, shift_for_comparison, validate_filter,
)
from reporting.cron import (  # noqa: F401
    compute_next_run, describe as describe_cron, get_zone, is_due, next_runs,
    parse_cron, schedule_summary, validate_cron,
)
from reporting.executor import (  # noqa: F401
    EMPTY_RESULT, build_report_payload, clone_report, combine_filters,
    dashboard_flat_rows, dashboard_payload, ensure_result, execute_widget,
    get_valid_snapshot, latest_snapshot, latest_widget_result, params_key,
    preview_report, report_brief, result_error, run_dataset, run_report,
    save_snapshot, widget_config, widget_filter_defaults, widget_payload,
)
from reporting.export import (  # noqa: F401
    MAX_EXPORT_ROWS, export_dashboard, export_report, export_widget, find_widget,
    render_csv, render_json, safe_filename, sanitize_cell, widget_columns,
)
from reporting.formula import (  # noqa: F401
    FUNCTIONS, evaluate as evaluate_formula, evaluate_round, formula_variables,
    kpi_from_rows, safe_pct_change, safe_share, validate_formula,
)
from reporting.sharing import (  # noqa: F401
    create_share, disable_share, new_token, share_brief, validate_share,
)
from reporting.stats import (  # noqa: F401
    MAX_QUALITY_FIELDS, count_reports, metrics_overview, percentile,
    quality_check, quality_for_dataset, report_metrics,
)
from reporting.whitelist import (  # noqa: F401
    clear_model_cache, get_whitelisted_model, model_detail, model_fields,
    model_info, resolve_path, whitelist_entries, whitelist_labels,
)

# 预览/组件可覆盖的键（显式列出，拒绝把任意键混进 spec）
OVERRIDE_KEYS = ("fields", "filter", "having", "order", "limit", "offset",
                 "distinct_fields", "shift")


def overrides_from_request(request, defaults=None):
    """从请求体收集「临时覆盖」，供预览/导出复用同一份数据集但换条件。

    同时接受扁平写法（``filter`` / ``limit`` …）与 ``spec`` 嵌套写法；
    只认白名单键，别的一律忽略，避免用户把 ``model`` 之类塞进覆盖里改口径。
    """
    out = dict(defaults or {})
    raw_spec = p(request, "spec")
    if isinstance(raw_spec, dict):
        for key in OVERRIDE_KEYS:
            if key in raw_spec and raw_spec.get(key) is not None:
                out[key] = raw_spec[key]
    for key in OVERRIDE_KEYS:
        value = p(request, key)
        if value is not None:
            out[key] = value
    # limit=0 / 空字符串视为「不覆盖」，防止把 clamp_limit 的错误提前抛给用户
    if out.get("limit") in (0, ""):
        out.pop("limit", None)
    return out


def dataset_result(dataset, params=None, overrides=None):
    """便捷封装：执行数据集并按 columns/rows/meta 三件套返回。"""
    return ensure_result(run_dataset(dataset, params or {}, overrides or {}))


def run_summary(run):
    """执行流水的极简摘要（组件失败提示里带上 run id 便于排查）。"""
    return {
        "id": run.pk,
        "status": run.status,
        "duration_ms": run.duration_ms,
        "row_count": run.row_count,
        "error": run.error,
    }


def pagination_meta(count, page, size):
    """分页元信息（导出/仪表盘等非列表场景复用同一口径）。"""
    pages = (count + size - 1) // size if size else 0
    return {"count": count, "page": page, "page_size": size, "pages": pages}
