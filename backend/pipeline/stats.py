# -*- coding: utf-8 -*-
"""运行统计：成功率、耗时分位、行数趋势、失败节点 TOP。

所有查询都走 ``core.scoping.scope_queryset``：统计与明细必须遵守同一套
数据范围，否则「部门看板」会泄露其他部门的数据。
聚合尽量在 Python 侧完成（数据量是单租户级别的运行记录），
原因是 SQLite 的日期函数与 PostgreSQL 不一致，跨库写 ``TruncDate``
会在本地与生产表现不同。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Avg, Count, Max, Sum
from django.utils import timezone

from core.scoping import scope_queryset
from pipeline.models import (Connection, Connector, DataQualityRule,
                             DatasetProfile, Pipeline, PipelineOutput,
                             PipelineRun, QualityResult, RunStep, Schedule,
                             WebhookTrigger)


def _since(days: int):
    days = max(1, min(int(days or 30), 365))
    return timezone.now() - timedelta(days=days)


def _scoped_runs(user, days: int, pipeline_id=None):
    qs = scope_queryset(PipelineRun.objects.filter(started_at__gte=_since(days)), user)
    if pipeline_id:
        qs = qs.filter(pipeline_id=pipeline_id)
    return qs


def _percentile(values: list[float], ratio: float) -> float:
    """线性插值分位数：空集返回 0，单值直接返回。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _local_day(value):
    return timezone.localtime(value).date().isoformat() if value else ""


def _day_series(days: int):
    """生成连续的日期键，避免「没运行的那天」在折线图里断档。"""
    today = timezone.localtime(timezone.now()).date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def _run_brief(run: PipelineRun) -> dict:
    return {
        "id": run.id,
        "pipeline_id": run.pipeline_id,
        "pipeline_code": run.pipeline.code if run.pipeline_id else "",
        "pipeline_name": run.pipeline.name if run.pipeline_id else "",
        "trigger": run.trigger,
        "status": run.status,
        "duration_ms": run.duration_ms,
        "input_rows": run.input_rows,
        "output_rows": run.output_rows,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "error": run.error[:300] if run.error else "",
    }


def overview(user, days: int = 30) -> dict:
    """总览：管道 / 运行 / 质量 / 连接 / 调度的关键指标。"""
    days = max(1, min(int(days or 30), 365))
    pipelines = scope_queryset(Pipeline.objects.all(), user)
    pipeline_status = Counter(pipelines.values_list("status", flat=True))
    runs = _scoped_runs(user, days)
    run_status = Counter(runs.values_list("status", flat=True))
    total_runs = sum(run_status.values())
    success = run_status.get("success", 0)
    failed = run_status.get("failed", 0)
    durations = [d for d in runs.values_list("duration_ms", flat=True) if d]
    quality = scope_queryset(QualityResult.objects.filter(run__started_at__gte=_since(days)), user)
    quality_total = quality.count()
    quality_failed = quality.filter(passed=False).count()
    connections = scope_queryset(Connection.objects.all(), user)
    conn_status = Counter(connections.values_list("status", flat=True))
    output_count = scope_queryset(
        PipelineOutput.objects.filter(run__started_at__gte=_since(days)), user).count()
    total_input = runs.aggregate(total=Sum("input_rows")).get("total") or 0
    total_output = runs.aggregate(total=Sum("output_rows")).get("total") or 0
    recent = [_run_brief(run) for run in
              runs.select_related("pipeline").order_by("-started_at", "-id")[:5]]
    top_pipelines = []
    counts = Counter(runs.values_list("pipeline_id", flat=True))
    name_map = {p.id: p for p in pipelines.filter(id__in=list(counts.keys())[:50])}
    for pipeline_id, count in counts.most_common(5):
        pipeline = name_map.get(pipeline_id)
        if pipeline is not None:
            top_pipelines.append({"id": pipeline_id, "code": pipeline.code,
                                  "name": pipeline.name, "runs": count})
    return {
        "days": days,
        "pipelines": {
            "total": pipelines.count(),
            "by_status": {status: pipeline_status.get(status, 0)
                          for status in ("draft", "active", "paused", "archived")},
        },
        "runs": {
            "total": total_runs,
            "by_status": {status: run_status.get(status, 0)
                          for status in ("queued", "running", "success", "failed", "cancelled")},
            "success_rate": round(success * 100.0 / (success + failed), 2)
            if (success + failed) else 0,
            "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0,
            "p95_duration_ms": round(_percentile(durations, 0.95), 2),
        },
        "rows": {"input": total_input, "output": total_output,
                 "avg_output": round(total_output / total_runs, 2) if total_runs else 0},
        "quality": {
            "total": quality_total,
            "failed": quality_failed,
            "pass_rate": round((quality_total - quality_failed) * 100.0 / quality_total, 2)
            if quality_total else 100.0,
        },
        "connections": {
            "total": connections.count(),
            "by_status": {status: conn_status.get(status, 0)
                          for status in ("active", "disabled", "error")},
        },
        "connectors": scope_queryset(Connector.objects.all(), user).count(),
        "schedules": scope_queryset(Schedule.objects.filter(enabled=True), user).count(),
        "webhooks": scope_queryset(WebhookTrigger.objects.filter(enabled=True), user).count(),
        "quality_rules": scope_queryset(DataQualityRule.objects.filter(enabled=True), user).count(),
        "profiles": scope_queryset(DatasetProfile.objects.all(), user).count(),
        "top_pipelines": top_pipelines,
        "recent_runs": recent,
        "outputs": output_count,
    }


def success_rate(user, days: int = 30, pipeline_id=None) -> dict:
    """成功率：整体 + 按天 + 按管道，失败率用于告警阈值。"""
    days = max(1, min(int(days or 30), 365))
    runs = list(_scoped_runs(user, days, pipeline_id)
                .values("pipeline_id", "status", "started_at"))
    daily: dict[str, dict] = {key: {"date": key, "total": 0, "success": 0,
                                    "failed": 0, "cancelled": 0, "other": 0}
                              for key in _day_series(days)}
    by_pipeline: dict[int, dict] = defaultdict(lambda: {"total": 0, "success": 0,
                                                        "failed": 0, "cancelled": 0})
    for run in runs:
        day = _local_day(run["started_at"])
        bucket = daily.setdefault(day, {"date": day, "total": 0, "success": 0,
                                        "failed": 0, "cancelled": 0, "other": 0})
        bucket["total"] += 1
        status = run["status"]
        if status in ("success", "failed", "cancelled"):
            bucket[status] += 1
        else:
            bucket["other"] += 1
        pipeline_bucket = by_pipeline[run["pipeline_id"]]
        pipeline_bucket["total"] += 1
        if status in ("success", "failed", "cancelled"):
            pipeline_bucket[status] += 1

    total = len(runs)
    success = sum(1 for run in runs if run["status"] == "success")
    failed = sum(1 for run in runs if run["status"] == "failed")
    pipeline_names = {p.id: p for p in scope_queryset(
        Pipeline.objects.filter(id__in=list(by_pipeline.keys())[:200]), user)}
    pipelines = []
    for pid, bucket in sorted(by_pipeline.items(), key=lambda item: -item[1]["total"])[:20]:
        pipeline = pipeline_names.get(pid)
        count = bucket["total"]
        pipelines.append({
            "pipeline_id": pid,
            "code": pipeline.code if pipeline else "",
            "name": pipeline.name if pipeline else "",
            **bucket,
            "success_rate": round(bucket["success"] * 100.0 / count, 2) if count else 0,
        })
    series = [daily[key] for key in sorted(daily.keys())]
    for item in series:
        item["success_rate"] = round(item["success"] * 100.0 / item["total"], 2) \
            if item["total"] else 0
    return {
        "days": days,
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": round(success * 100.0 / total, 2) if total else 0,
        "failure_rate": round(failed * 100.0 / total, 2) if total else 0,
        "series": series,
        "pipelines": pipelines,
    }


def latency(user, days: int = 30, pipeline_id=None) -> dict:
    """耗时分布：分位数 + 直方图 + 按节点类型 / 按管道的均值。"""
    days = max(1, min(int(days or 30), 365))
    runs = _scoped_runs(user, days, pipeline_id)
    durations = [d for d in runs.values_list("duration_ms", flat=True) if d is not None]
    histogram = {"0-100ms": 0, "100-500ms": 0, "500ms-1s": 0,
                 "1-5s": 0, "5s+": 0}
    for value in durations:
        if value < 100:
            histogram["0-100ms"] += 1
        elif value < 500:
            histogram["100-500ms"] += 1
        elif value < 1000:
            histogram["500ms-1s"] += 1
        elif value < 5000:
            histogram["1-5s"] += 1
        else:
            histogram["5s+"] += 1

    steps = scope_queryset(RunStep.objects.filter(run__started_at__gte=_since(days)), user)
    if pipeline_id:
        steps = steps.filter(run__pipeline_id=pipeline_id)
    node_rows = (steps.values("node_type")
                 .annotate(count=Count("id"), avg=Avg("duration_ms"),
                           max=Max("duration_ms"), total=Sum("duration_ms"))
                 .order_by("-avg"))
    by_node = [
        {"node_type": row["node_type"], "count": row["count"],
         "avg_ms": round(row["avg"] or 0, 2), "max_ms": row["max"] or 0,
         "total_ms": row["total"] or 0}
        for row in node_rows
    ]

    per_pipeline = []
    grouped = (runs.values("pipeline_id")
               .annotate(count=Count("id"), avg=Avg("duration_ms"),
                         max=Max("duration_ms")))
    pipelines = {p.id: p for p in scope_queryset(
        Pipeline.objects.filter(id__in=[g["pipeline_id"] for g in grouped][:200]), user)}
    for row in sorted(grouped, key=lambda g: -(g["avg"] or 0))[:20]:
        pipeline = pipelines.get(row["pipeline_id"])
        per_pipeline.append({
            "pipeline_id": row["pipeline_id"],
            "code": pipeline.code if pipeline else "",
            "name": pipeline.name if pipeline else "",
            "runs": row["count"],
            "avg_ms": round(row["avg"] or 0, 2),
            "max_ms": row["max"] or 0,
        })

    return {
        "days": days,
        "samples": len(durations),
        "avg_ms": round(sum(durations) / len(durations), 2) if durations else 0,
        "min_ms": min(durations) if durations else 0,
        "max_ms": max(durations) if durations else 0,
        "p50_ms": round(_percentile(durations, 0.50), 2),
        "p75_ms": round(_percentile(durations, 0.75), 2),
        "p90_ms": round(_percentile(durations, 0.90), 2),
        "p95_ms": round(_percentile(durations, 0.95), 2),
        "p99_ms": round(_percentile(durations, 0.99), 2),
        "histogram": histogram,
        "by_node_type": by_node,
        "by_pipeline": per_pipeline,
    }


def row_trend(user, days: int = 14, pipeline_id=None) -> dict:
    """行数趋势：每天的运行数、成功失败数、输入 / 输出行数。"""
    days = max(1, min(int(days or 14), 365))
    runs = list(_scoped_runs(user, days, pipeline_id)
                .values("status", "started_at", "input_rows", "output_rows"))
    series: dict[str, dict] = {key: {"date": key, "runs": 0, "success": 0,
                                     "failed": 0, "input_rows": 0, "output_rows": 0}
                               for key in _day_series(days)}
    for run in runs:
        day = _local_day(run["started_at"])
        bucket = series.setdefault(day, {"date": day, "runs": 0, "success": 0,
                                         "failed": 0, "input_rows": 0, "output_rows": 0})
        bucket["runs"] += 1
        if run["status"] == "success":
            bucket["success"] += 1
        elif run["status"] == "failed":
            bucket["failed"] += 1
        bucket["input_rows"] += run["input_rows"] or 0
        bucket["output_rows"] += run["output_rows"] or 0
    ordered = [series[key] for key in sorted(series.keys())]
    return {
        "days": days,
        "series": ordered,
        "totals": {
            "runs": sum(item["runs"] for item in ordered),
            "input_rows": sum(item["input_rows"] for item in ordered),
            "output_rows": sum(item["output_rows"] for item in ordered),
        },
        "peak": max(ordered, key=lambda item: item["output_rows"]) if ordered else None,
    }


def failed_nodes(user, days: int = 30, limit: int = 10, pipeline_id=None) -> dict:
    """失败节点 TOP：按节点统计失败次数、最近错误与影响运行数。"""
    days = max(1, min(int(days or 30), 365))
    limit = max(1, min(int(limit or 10), 100))
    steps = scope_queryset(RunStep.objects.filter(
        status="failed", run__started_at__gte=_since(days)), user)
    if pipeline_id:
        steps = steps.filter(run__pipeline_id=pipeline_id)
    grouped = (steps.values("node_key", "node_type")
               .annotate(failures=Count("id"), runs=Count("run_id", distinct=True),
                         last_at=Max("created_at"))
               .order_by("-failures")[:limit])
    rows = []
    for row in grouped:
        latest = (steps.filter(node_key=row["node_key"])
                  .order_by("-id").values_list("error", flat=True).first())
        rows.append({
            "node_key": row["node_key"],
            "node_type": row["node_type"],
            "failures": row["failures"],
            "affected_runs": row["runs"],
            "last_error": (latest or "")[:300],
            "last_failed_at": timezone.localtime(row["last_at"]).isoformat()
            if row["last_at"] else None,
        })
    total_failures = steps.count()
    return {
        "days": days,
        "total_failures": total_failures,
        "items": rows,
        "count": len(rows),
    }


def pipeline_stats(pipeline, days: int = 30) -> dict:
    """单管道统计摘要：给详情页顶部卡片用。"""
    runs = pipeline.runs.filter(started_at__gte=_since(days))
    total = runs.count()
    success = runs.filter(status="success").count()
    failed = runs.filter(status="failed").count()
    durations = [d for d in runs.values_list("duration_ms", flat=True) if d]
    last = runs.order_by("-started_at", "-id").first()
    return {
        "pipeline_id": pipeline.id,
        "days": days,
        "runs": total,
        "success": success,
        "failed": failed,
        "success_rate": round(success * 100.0 / total, 2) if total else 0,
        "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0,
        "p95_duration_ms": round(_percentile(durations, 0.95), 2),
        "last_run": _run_brief(last) if last else None,
    }
