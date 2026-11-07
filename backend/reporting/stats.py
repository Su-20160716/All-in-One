# -*- coding: utf-8 -*-
"""执行统计与数据质量检查。

执行统计
--------
- 数据范围：ReportRun.owner 是触发人，复用 core.scoping.scope_queryset，
  同部门/全平台角色看到的是自己范围内的执行流水；
- 耗时分位：ORM 没有 percentile，这里取耗时列（上限 2 万条）在内存算
  P50/P95；报表执行量级远小于这个上限，成本可接受；
- 热门报表：按「执行次数 / 失败次数 / 平均耗时」三个维度各取 TOP N。

数据质量
--------
- 空值率：``field__isnull`` 计数 / 总行数；文本字段额外统计空字符串；
- 重复率：按给定键分组，统计 count>1 的组与多余行数（重复行 = 组内行数-1）；
- 异常值：数值列做 Z-score，|z|>3 视为异常，返回偏离最大的 N 条（含主键）。
"""
import math
from datetime import timedelta

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.scoping import scope_queryset
from reporting.compiler import compile_filter
from reporting.models import ReportDefinition, ReportRun
from reporting.whitelist import get_whitelisted_model, resolve_path

MAX_DURATION_SAMPLE = 20000
MAX_QUALITY_FIELDS = 12
MAX_OUTLIER_SCAN = 5000
Z_THRESHOLD = 3.0


def percentile(values, pct):
    """线性插值分位数（pct 取 0~100）；空列表返回 0。"""
    numbers = sorted(float(v) for v in values if v is not None)
    if not numbers:
        return 0
    if len(numbers) == 1:
        return round(numbers[0], 2)
    pos = (len(numbers) - 1) * (float(pct) / 100.0)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return round(numbers[low], 2)
    weight = pos - low
    return round(numbers[low] * (1 - weight) + numbers[high] * weight, 2)


def _since(days):
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ValueError("days 必须是整数")
    if days < 1 or days > 365:
        raise ValueError("统计窗口需在 1~365 天之间")
    return timezone.now() - timedelta(days=days)


def metrics_overview(user, days=30, report_id=None):
    """指标概览：执行量、成功率、耗时 P50/P95、热门与最慢报表、日趋势。"""
    since = _since(days)
    qs = scope_queryset(ReportRun.objects.filter(created_at__gte=since), user, "owner")
    if report_id:
        qs = qs.filter(report_id=report_id)

    totals = qs.aggregate(
        total=Count("id"),
        success=Count("id", filter=Q(status="success")),
        failed=Count("id", filter=Q(status="failed")),
        running=Count("id", filter=Q(status="running")),
        avg_ms=Avg("duration_ms"),
        max_ms=Max("duration_ms"),
    )
    total = totals["total"] or 0
    success = totals["success"] or 0
    failed = totals["failed"] or 0
    finished = success + failed
    durations = list(qs.values_list("duration_ms", flat=True)[:MAX_DURATION_SAMPLE])

    trigger_rows = (qs.values("trigger").annotate(c=Count("id")).order_by("-c"))
    triggers = {row["trigger"] or "manual": row["c"] for row in trigger_rows}
    cached_hits = triggers.get("cache", 0)

    trend_rows = (
        qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"),
                  failed=Count("id", filter=Q(status="failed")),
                  avg_ms=Avg("duration_ms"))
        .order_by("day")[:400]
    )
    trend = [{
        "date": row["day"].isoformat() if row["day"] else None,
        "total": row["total"],
        "failed": row["failed"],
        "avg_ms": round(row["avg_ms"] or 0, 2),
    } for row in trend_rows]

    top_rows = (
        qs.values("report_id", "report__name", "report__code")
        .annotate(runs=Count("id"),
                  fails=Count("id", filter=Q(status="failed")),
                  avg_ms=Avg("duration_ms"))
        .order_by("-runs")[:10]
    )
    top_reports = [{
        "report_id": row["report_id"],
        "name": row["report__name"] or "",
        "code": row["report__code"] or "",
        "runs": row["runs"],
        "fails": row["fails"],
        "failure_rate_pct": round(row["fails"] / row["runs"] * 100, 2) if row["runs"] else 0,
        "avg_ms": round(row["avg_ms"] or 0, 2),
    } for row in top_rows]

    slow_rows = (
        qs.filter(status="success")
        .values("report_id", "report__name")
        .annotate(avg_ms=Avg("duration_ms"), runs=Count("id"))
        .order_by("-avg_ms")[:10]
    )
    slowest = [{
        "report_id": row["report_id"],
        "name": row["report__name"] or "",
        "avg_ms": round(row["avg_ms"] or 0, 2),
        "runs": row["runs"],
    } for row in slow_rows]

    failure_rows = (
        qs.filter(status="failed").exclude(error="")
        .values("report_id", "report__name", "error")
        .annotate(c=Count("id")).order_by("-c")[:10]
    )
    failures = [{
        "report_id": row["report_id"],
        "name": row["report__name"] or "",
        "error": (row["error"] or "")[:200],
        "count": row["c"],
    } for row in failure_rows]

    return {
        "window_days": int(days),
        "total": total,
        "success": success,
        "failed": failed,
        "running": totals["running"] or 0,
        "success_rate_pct": round(success / finished * 100, 2) if finished else None,
        "failure_rate_pct": round(failed / finished * 100, 2) if finished else None,
        "duration_p50_ms": percentile(durations, 50),
        "duration_p95_ms": percentile(durations, 95),
        "duration_avg_ms": round(totals["avg_ms"] or 0, 2),
        "duration_max_ms": totals["max_ms"] or 0,
        "sample_size": len(durations),
        "triggers": triggers,
        "cache_hit_rate_pct": round(cached_hits / total * 100, 2) if total else None,
        "trend": trend,
        "top_reports": top_reports,
        "slowest_reports": slowest,
        "failure_reasons": failures,
        "generated_at": timezone.now().isoformat(),
    }


def report_metrics(report, days=30):
    """单张报表的执行指标（报表详情页头部用）。"""
    data = metrics_overview(report.owner, days=days, report_id=report.pk)
    data["report_id"] = report.pk
    data["report_name"] = report.name
    return data


def count_reports(user):
    """当前用户可见范围内的报表数量（目录页展示规模）。"""
    return scope_queryset(ReportDefinition.objects.all(), user, "owner").count()


def _pick_fields(model):
    """默认检查字段：前 N 个标量字段（跳过主键、文件、二进制与 JSON）。"""
    picked = []
    for field in model._meta.concrete_fields:
        if field.primary_key:
            continue
        if field.get_internal_type() in ("FileField", "ImageField", "BinaryField"):
            continue
        picked.append(field.name)
        if len(picked) >= MAX_QUALITY_FIELDS:
            break
    return picked


def quality_check(model_label, filter_spec=None, params=None, fields=None,
                  distinct_keys=None, numeric_field=None, outlier_limit=20):
    """数据质量检查：空值率 / 重复率 / 异常值（Z-score）。

    入参都是可选项；不传字段时自动挑选前 12 个标量字段，不传数值字段时
    自动挑第一个数值字段做异常值检查。
    """
    model = get_whitelisted_model(model_label)
    q = compile_filter(model, filter_spec or {}, params or {})
    qs = model._default_manager.all()
    if q:
        qs = qs.filter(q)
    total = qs.count()

    if fields in (None, ""):
        fields = _pick_fields(model)
    if isinstance(fields, str):
        fields = [fields]
    if not isinstance(fields, list):
        raise ValueError("fields 必须是数组")
    if len(fields) > MAX_QUALITY_FIELDS:
        raise ValueError(f"一次最多检查 {MAX_QUALITY_FIELDS} 个字段")

    checks = []
    for path in fields:
        resolved = resolve_path(model, path)
        orm_path = resolved["orm_path"]
        null_count = qs.filter(**{f"{orm_path}__isnull": True}).count()
        empty_count = 0
        if (resolved["type"] == "string" and not resolved.get("is_json")
                and not resolved.get("relation")):
            # 关系字段的 orm_path 是外键列（整数），拿 "" 过滤会触发类型错误
            empty_count = qs.filter(**{orm_path: ""}).count()
        checks.append({
            "field": path,
            "type": resolved["type"],
            "null_count": null_count,
            "empty_count": empty_count,
            "null_rate_pct": round(null_count / total * 100, 2) if total else None,
            "empty_rate_pct": round(empty_count / total * 100, 2) if total else None,
            "passed": (null_count == 0) if total else None,
        })

    duplicates = {"keys": [], "duplicate_groups": 0, "duplicate_rows": 0,
                  "duplicate_rate_pct": None, "items": []}
    keys = distinct_keys or []
    if isinstance(keys, str):
        keys = [keys]
    if keys:
        if len(keys) > 5:
            raise ValueError("重复检查的键最多 5 个")
        for key in keys:
            resolve_path(model, key)
        groups = (qs.values(*keys).annotate(c=Count("pk")).filter(c__gt=1)
                  .order_by("-c")[:50])
        group_items = []
        duplicate_rows = 0
        for row in groups:
            extra = int(row.get("c") or 0) - 1
            duplicate_rows += extra
            group_items.append({
                "values": [row.get(k) for k in keys],
                "count": row.get("c"),
                "extra_rows": extra,
            })
        duplicates = {
            "keys": keys,
            "duplicate_groups": len(group_items),
            "duplicate_rows": duplicate_rows,
            "duplicate_rate_pct": round(duplicate_rows / total * 100, 2) if total else None,
            "items": group_items[:10],
        }

    if numeric_field is None:
        numeric_field = _pick_numeric_field(model)
    outliers = {"field": "", "mean": None, "std": None, "threshold": Z_THRESHOLD,
                "count": 0, "items": []}
    if numeric_field:
        resolved = resolve_path(model, numeric_field)
        if resolved["type"] not in ("integer", "number", "decimal") and not resolved.get("is_json"):
            raise ValueError(f"字段 {numeric_field} 不是数值型，无法做异常值检查")
        pairs = list(qs.values_list("pk", resolved["orm_path"])[:MAX_OUTLIER_SCAN])
        numbers = []
        for _pk, raw in pairs:
            try:
                numbers.append(float(raw))
            except (TypeError, ValueError):
                continue
        if len(numbers) >= 3:
            mean = sum(numbers) / len(numbers)
            variance = sum((x - mean) ** 2 for x in numbers) / len(numbers)
            std = math.sqrt(variance)
            if std > 0:
                found = []
                for pk, raw in pairs:
                    try:
                        value = float(raw)
                    except (TypeError, ValueError):
                        continue
                    z = (value - mean) / std
                    if abs(z) > Z_THRESHOLD:
                        found.append({"id": pk, "value": round(value, 6),
                                      "z_score": round(z, 2)})
                found.sort(key=lambda item: -abs(item["z_score"]))
                outliers = {
                    "field": numeric_field,
                    "mean": round(mean, 4),
                    "std": round(std, 4),
                    "threshold": Z_THRESHOLD,
                    "count": len(found),
                    "items": found[:outlier_limit],
                }
            else:
                outliers = {"field": numeric_field, "mean": round(mean, 4), "std": 0,
                            "threshold": Z_THRESHOLD, "count": 0, "items": []}
        outliers["scanned"] = len(pairs)

    worst_null = max((c["null_rate_pct"] or 0 for c in checks), default=0)
    score = 100.0
    score -= min(worst_null, 50)
    if duplicates["duplicate_rate_pct"]:
        score -= min(duplicates["duplicate_rate_pct"], 30)
    if outliers["count"]:
        score -= min(outliers["count"] * 0.5, 20)
    return {
        "model": model_label,
        "row_count": total,
        "fields": checks,
        "duplicates": duplicates,
        "outliers": outliers,
        "score": round(max(score, 0), 1),
        "meta": {
            "scanned_fields": len(checks),
            "outlier_scan_limit": MAX_OUTLIER_SCAN,
            "z_threshold": Z_THRESHOLD,
            "generated_at": timezone.now().isoformat(),
        },
    }


def _pick_numeric_field(model):
    """自动挑一个数值字段：优先金额/数值，其次整数（跳过主键与布尔）。"""
    candidates = []
    for field in model._meta.concrete_fields:
        if field.primary_key:
            continue
        internal = field.get_internal_type()
        if internal in ("DecimalField", "FloatField"):
            candidates.append((0, field.name))
        elif internal in ("IntegerField", "BigIntegerField", "SmallIntegerField"):
            candidates.append((1, field.name))
    candidates.sort()
    return candidates[0][1] if candidates else None


def quality_for_dataset(dataset, **kwargs):
    """按数据集口径做质量检查（沿用数据集的过滤条件）。"""
    return quality_check(
        dataset.primary_model,
        filter_spec=dataset.filter or {},
        distinct_keys=kwargs.pop("distinct_keys", None) or (dataset.distinct_fields or []),
        **kwargs,
    )
