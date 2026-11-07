# -*- coding: utf-8 -*-
"""运行器：按拓扑序同步执行 DAG。

为什么同步：
- 不引入 Celery / Redis 依赖，部署面最小；
- 接口返回时结果、日志、输出数据都已落库，前端可以直接查；
- 单次上限 5000 行，同步执行的耗时是可控的（毫秒到秒级）。

关键语义：
- 单节点失败按 ``pipeline.max_retries`` 重试（retry 次数，非总次数）；
- 任一节点最终失败 → 运行 failed，下游节点标记 skipped，不再继续；
- 超时在节点间与节点内（每 200 行）双重检查；
- 成功运行后回写增量水位、执行质量检查、记录血缘。
"""
from __future__ import annotations

import time
import traceback
from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from pipeline.catalog import (MAX_RETRIES, MAX_RUN_ROWS, MAX_TIMEOUT,
                              MAX_PAGE_SIZE)
from pipeline.dag import validate_dag
from pipeline.executors import execute_node, get_path
from pipeline.expressions import to_number, to_text
from pipeline.generators import (estimate_source_rows, simulate_webhook_delivery,
                                 source_rows)
from pipeline.models import (Connection, Mapping, PipeNode, PipelineOutput,
                             PipelineRun, RunLog, RunStep)


class RunTimeout(ValueError):
    """运行超时：单独类型，因为超时重试没有意义。"""


class RunContext:
    """运行上下文：执行器只依赖这里的协议，便于脱离数据库测试。

    ``outputs`` 用 (node_key, port) 作为键：一个 filter 会同时产出
    pass / fail 两路，runner 按连线端口精确取用，而不是靠节点顺序猜。
    """

    def __init__(self, run: PipelineRun, pipeline, actor=None, options: dict | None = None):
        self.run = run
        self.pipeline = pipeline
        self.actor = actor
        self.options = options or {}
        self.limit = max(1, min(int(pipeline.row_limit or MAX_RUN_ROWS), MAX_RUN_ROWS))
        self.timeout_seconds = max(1, min(int(pipeline.timeout_seconds or 120), MAX_TIMEOUT))
        self.started_monotonic = time.monotonic()
        self.deadline = self.started_monotonic + self.timeout_seconds
        self.watermark_field = pipeline.watermark_field or ""
        self.watermark_before = pipeline.watermark_value or ""
        self.watermark_after = ""
        self.pipeline_code = pipeline.code
        self.run_id = run.id

        self.outputs: dict[tuple[str, str], list[dict]] = {}
        self.node_meta: dict[str, dict] = {}
        self.source_rows: list[dict] = []
        self.source_row_count = 0
        self.sink_rows = 0
        self.webhook_calls: list[dict] = []
        self.timings: list[dict] = []
        self.mapping_cache: dict[str, list] = {}
        self.connection_cache: dict[int, Connection | None] = {}
        self.nodes_by_key: dict[str, PipeNode] = {}

    # ---- 超时 ----

    def check_timeout(self) -> None:
        if time.monotonic() > self.deadline:
            raise RunTimeout(f"运行超过 {self.timeout_seconds} 秒上限")

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_monotonic) * 1000)

    # ---- 日志 ----

    def log(self, level: str, message: str, node_key: str = "",
            context: dict | None = None) -> RunLog:
        """写一条运行日志；日志失败不能反过来影响主流程。"""
        try:
            return RunLog.objects.create(
                owner=self.pipeline.owner,
                run=self.run,
                level=level if level in ("debug", "info", "warning", "error") else "info",
                message=str(message)[:500],
                node_key=node_key,
                context=context or {},
            )
        except Exception:  # noqa: BLE001 —— 审计日志失败不阻断数据链路
            return RunLog(run=self.run, level=level, message=str(message)[:500])

    # ---- 数据访问 ----

    def get_connection(self, connection_id):
        try:
            key = int(connection_id)
        except (TypeError, ValueError):
            return None
        if key in self.connection_cache:
            return self.connection_cache[key]
        conn = (Connection.objects.select_related("connector")
                .filter(pk=key, owner=self.pipeline.owner).first())
        self.connection_cache[key] = conn
        return conn

    def mapping_rows(self, node_key: str) -> list:
        """取管道级 + 节点级字段映射；节点级在前，便于逐条维护。"""
        if node_key in self.mapping_cache:
            return self.mapping_cache[node_key]
        node = self.nodes_by_key.get(node_key)
        if node is None:
            return []
        rows = list(Mapping.objects.filter(pipeline=self.pipeline)
                    .filter(Q(node__isnull=True) | Q(node=node))
                    .order_by("order", "id"))
        self.mapping_cache[node_key] = rows
        return rows

    def write_outputs(self, node, rows: list[dict], dataset: str, mode: str = "append") -> int:
        """真实写入 PipelineOutput：分批 bulk_create，避免一条一条 insert。"""
        if mode == "replace":
            PipelineOutput.objects.filter(run=self.run, dataset=dataset,
                                          node=node).delete()
        objects = [
            PipelineOutput(owner=self.pipeline.owner, pipeline=self.pipeline,
                           run=self.run, node=node, dataset=dataset,
                           seq=index, data=dict(row))
            for index, row in enumerate(rows[:self.limit])
        ]
        for start in range(0, len(objects), 500):
            PipelineOutput.objects.bulk_create(objects[start:start + 500])
        self.sink_rows += len(objects)
        return len(objects)

    def deliver_webhook(self, url: str, payload: dict, method: str = "POST") -> dict:
        result = simulate_webhook_delivery(url, payload, method)
        self.webhook_calls.append({"url": url, "method": method,
                                   "status_code": result.get("status_code"),
                                   "node_row_count": payload.get("row_count")})
        return result


def _prune_inputs(rows: list[dict]) -> list[dict]:
    """去掉明显超限的输入，错误在节点前抛出更易定位。"""
    return rows[:MAX_RUN_ROWS] if len(rows) > MAX_RUN_ROWS else rows


def _collect_inputs(node: PipeNode, ctx: RunContext) -> dict[str, list[dict]]:
    """按连线端口取上游输出；多路连线按 order 合并（保持确定性）。"""
    inputs: dict[str, list[dict]] = defaultdict(list)
    edges = (node.in_edges.select_related("source")
             .order_by("order", "id"))
    for edge in edges:
        if not edge.source.enabled:
            continue
        rows = ctx.outputs.get((edge.source.node_key, edge.source_port))
        if rows is None:
            raise ValueError(f"上游节点 {edge.source.node_key} 尚未产出端口 "
                             f"{edge.source_port} 的数据")
        inputs[edge.target_port].extend(rows)
    return {port: _prune_inputs(rows) for port, rows in inputs.items()}


def _store_outputs(node: PipeNode, ports: dict, ctx: RunContext) -> None:
    for port, rows in (ports or {}).items():
        ctx.outputs[(node.node_key, port)] = list(rows or [])


def _step_row_counts(inputs: dict, ports: dict) -> tuple[int, int]:
    input_rows = sum(len(rows) for rows in inputs.values())
    output_rows = sum(len(rows) for rows in (ports or {}).values())
    return input_rows, output_rows


def _execute_with_retry(node: PipeNode, inputs: dict, ctx: RunContext,
                        seq: int) -> tuple[dict, dict]:
    """单节点执行 + 重试；返回 (输出端口, 元信息)。

    每次尝试都落一条 RunStep：重试的成功/失败轨迹是排障的第一手材料，
    折叠成一行会丢掉「第一次为什么失败」。
    """
    attempts = max(1, min(int(ctx.pipeline.max_retries or 0), MAX_RETRIES) + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        step = RunStep.objects.create(
            owner=ctx.pipeline.owner, run=ctx.run, node=node,
            node_key=node.node_key, node_type=node.node_type,
            seq=seq, attempt=attempt, status="running",
        )
        started = time.monotonic()
        try:
            ctx.check_timeout()
            ports, meta = execute_node(node, inputs, ctx)
            duration = int((time.monotonic() - started) * 1000)
            input_rows, output_rows = _step_row_counts(inputs, ports)
            step.status = "success"
            step.duration_ms = duration
            step.input_rows = input_rows
            step.output_rows = output_rows
            step.summary = (f"输入 {input_rows} 行 / 输出 {output_rows} 行"
                            f"（第 {attempt} 次尝试）")
            step.save(update_fields=["status", "duration_ms", "input_rows",
                                     "output_rows", "summary", "updated_at"])
            ctx.timings.append({"node_key": node.node_key, "node_type": node.node_type,
                                "duration_ms": duration, "input_rows": input_rows,
                                "output_rows": output_rows, "attempt": attempt})
            ctx.node_meta[node.node_key] = meta or {}
            return ports, meta or {}
        except RunTimeout:
            duration = int((time.monotonic() - started) * 1000)
            step.status = "failed"
            step.duration_ms = duration
            step.error = "运行超时"
            step.summary = "超时终止，不再重试"
            step.save(update_fields=["status", "duration_ms", "error", "summary",
                                     "updated_at"])
            raise
        except Exception as exc:  # noqa: BLE001 —— 节点异常必须转成可读失败
            duration = int((time.monotonic() - started) * 1000)
            last_error = str(exc) or type(exc).__name__
            step.status = "failed"
            step.duration_ms = duration
            step.input_rows = sum(len(rows) for rows in inputs.values())
            step.error = last_error[:2000]
            step.summary = f"第 {attempt} 次尝试失败：{last_error[:300]}"
            step.save(update_fields=["status", "duration_ms", "input_rows",
                                     "error", "summary", "updated_at"])
            ctx.log("warning" if attempt < attempts else "error",
                    f"节点 {node.node_key} 第 {attempt} 次尝试失败：{last_error}",
                    node_key=node.node_key,
                    context={"traceback": traceback.format_exc()[-1200:]})
            if attempt < attempts:
                ctx.check_timeout()
                continue
            raise ValueError(f"节点 {node.node_key} 执行失败：{last_error}")
    raise ValueError(f"节点 {node.node_key} 执行失败：{last_error}")


def _mark_skipped(pipeline, run, order: list[str], executed: set[str],
                  ctx: RunContext) -> None:
    """失败后把未执行节点标成 skipped：前端能清楚看到「停在哪」。"""
    nodes = {n.node_key: n for n in pipeline.nodes.all()}
    seq = len(executed) + 1
    for key in order:
        if key in executed:
            continue
        node = nodes.get(key)
        if node is None or not node.enabled:
            continue
        RunStep.objects.create(
            owner=pipeline.owner, run=run, node=node, node_key=key,
            node_type=node.node_type, seq=seq, attempt=1, status="skipped",
            summary="上游节点失败，未执行",
        )
        seq += 1


def _source_estimate(pipeline, options: dict) -> int:
    """估算输入行数：用于在创建运行前拦住超限请求。"""
    if isinstance(options.get("rows"), list):
        return len(options["rows"])
    total = 0
    for node in pipeline.nodes.filter(node_type="source", enabled=True):
        total += estimate_source_rows(node.config or {})
    return total


def _extract_watermark(rows: list[dict], field: str):
    """取字段最大值；无法比较时退回字符串最大（ISO 时间可直接比较）。"""
    best = None
    best_num = None
    for row in rows:
        value = get_path(row, field)
        if value is None or value == "":
            continue
        num = to_number(value)
        if best is None:
            best, best_num = value, num
            continue
        if num is not None and best_num is not None:
            if num > best_num:
                best, best_num = value, num
        elif to_text(value) > to_text(best):
            best, best_num = value, num
    return best


def _update_watermark(pipeline, run, ctx: RunContext) -> None:
    fields: list[str] = []
    if pipeline.watermark_field:
        fields.append(pipeline.watermark_field)
        after = _extract_watermark(ctx.source_rows, pipeline.watermark_field)
        if after is not None:
            ctx.watermark_after = str(after)
            pipeline.watermark_value = str(after)[:200]
            run.watermark_after = str(after)[:200]
            ctx.log("info", f"水位从 {ctx.watermark_before or '空'} 更新为 {after}",
                    context={"field": pipeline.watermark_field})


def _finish_success(pipeline, run, ctx: RunContext, quality_summary: dict) -> None:
    now = timezone.now()
    run.status = "success"
    run.finished_at = now
    run.duration_ms = ctx.elapsed_ms()
    run.input_rows = ctx.source_row_count or sum(
        len(rows) for rows in ctx.outputs.values())
    run.output_rows = ctx.sink_rows
    run.stats = {
        "nodes": ctx.timings,
        "source_rows": ctx.source_row_count,
        "sink_rows": ctx.sink_rows,
        "webhook_calls": ctx.webhook_calls,
        "quality": {k: v for k, v in quality_summary.items() if k != "results"},
        "node_meta": ctx.node_meta,
        "timeout_seconds": ctx.timeout_seconds,
        "limit": ctx.limit,
    }
    pipeline.last_run_at = now
    pipeline.last_run_status = "success"
    with transaction.atomic():
        _update_watermark(pipeline, run, ctx)
        run.save()
        pipeline.save(update_fields=["last_run_at", "last_run_status",
                                     "watermark_value", "updated_at"])
    ctx.log("info", f"运行成功：输入 {run.input_rows} 行，落地 {run.output_rows} 行，"
                    f"耗时 {run.duration_ms} ms")


def _finish_failure(pipeline, run, ctx: RunContext, message: str) -> None:
    now = timezone.now()
    run.status = "failed"
    run.finished_at = now
    run.duration_ms = ctx.elapsed_ms()
    run.input_rows = ctx.source_row_count or sum(
        len(rows) for rows in ctx.outputs.values())
    run.output_rows = ctx.sink_rows
    run.error = str(message)[:4000]
    run.stats = {
        "nodes": ctx.timings,
        "source_rows": ctx.source_row_count,
        "sink_rows": ctx.sink_rows,
        "webhook_calls": ctx.webhook_calls,
        "node_meta": ctx.node_meta,
        "timeout_seconds": ctx.timeout_seconds,
        "limit": ctx.limit,
    }
    pipeline.last_run_at = now
    pipeline.last_run_status = "failed"
    with transaction.atomic():
        run.save()
        pipeline.save(update_fields=["last_run_at", "last_run_status", "updated_at"])
    ctx.log("error", f"运行失败：{message}")


def run_pipeline(pipeline, trigger: str = "manual", actor=None,
                 options: dict | None = None) -> PipelineRun:
    """执行一次管道（同步）。返回已落库的 PipelineRun。

    预检失败（已暂停 / 并发策略 / DAG 非法 / 行数超限）直接抛 ValueError，
    接口层映射为 400；节点执行期失败落一条 failed 运行，供前端查看日志。
    """
    options = options or {}
    if trigger not in ("manual", "schedule", "api", "webhook", "retry"):
        raise ValueError(f"不支持的触发方式：{trigger}")
    if pipeline.status == "archived":
        raise ValueError("已归档管道不能运行")
    if pipeline.status == "paused":
        raise ValueError("已暂停管道不能运行，请先恢复")

    limit = max(1, min(int(pipeline.row_limit or MAX_RUN_ROWS), MAX_RUN_ROWS))
    estimate = _source_estimate(pipeline, options)
    if estimate > limit:
        raise ValueError(f"单次运行行数上限 {limit}，当前约 {estimate} 行")

    report = validate_dag(pipeline)
    if not report["valid"]:
        message = "；".join(item["message"] for item in report["errors"][:4])
        raise ValueError(f"管道校验失败：{message}")

    with transaction.atomic():
        # 行锁 + 再查一次活跃运行：并发触发时只有第一个能创建运行
        locked = type(pipeline).objects.select_for_update().get(pk=pipeline.pk)
        active = PipelineRun.objects.filter(
            pipeline=locked, status__in=("queued", "running")).exists()
        if active and locked.concurrency in ("skip", "serial"):
            raise ValueError("管道正在运行，已按并发策略拒绝本次触发")
        run = PipelineRun.objects.create(
            owner=locked.owner,
            pipeline=locked,
            trigger=trigger,
            status="queued",
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            watermark_before=locked.watermark_value or "",
            resumed_from=str(options.get("resume_from") or "")[:80],
            stats={"limit": limit},
        )

    ctx = RunContext(run, pipeline, actor=actor, options=options)
    ctx.nodes_by_key = {n.node_key: n for n in pipeline.nodes.all()}
    executed: set[str] = set()
    order = report["order"]

    with transaction.atomic():
        run.status = "running"
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])
    ctx.log("info", f"开始运行（{trigger}），共 {len(order)} 个节点",
            context={"order": order, "limit": limit,
                     "resume_from": run.resumed_from or None})

    # 允许调用方直接注入行集（API 联调 / 单测），优先于 source 节点取数
    injected = options.get("rows")
    if isinstance(injected, list):
        if len(injected) > limit:
            raise ValueError(f"单次运行行数上限 {limit}，当前 {len(injected)} 行")
        if any(not isinstance(r, dict) for r in injected):
            raise ValueError("rows 必须是对象数组")

    try:
        seq = 0
        for key in order:
            node = ctx.nodes_by_key.get(key)
            if node is None or not node.enabled:
                continue
            ctx.check_timeout()
            seq += 1
            if node.node_type == "source" and isinstance(injected, list):
                # 注入行集：跳过模拟取数，但仍走 source 的端口与水位逻辑
                rows = [dict(r) for r in injected]
                ctx.outputs[(key, "out")] = rows
                ctx.source_rows.extend(rows)
                ctx.source_row_count += len(rows)
                RunStep.objects.create(
                    owner=pipeline.owner, run=run, node=node, node_key=key,
                    node_type="source", seq=seq, attempt=1, status="success",
                    input_rows=0, output_rows=len(rows),
                    summary=f"使用调用方注入的 {len(rows)} 行（跳过模拟取数）",
                )
                ctx.log("info", f"数据源 {key} 使用注入行集 {len(rows)} 行")
                executed.add(key)
                continue

            inputs = _collect_inputs(node, ctx)
            ports, meta = _execute_with_retry(node, inputs, ctx, seq)
            _store_outputs(node, ports, ctx)
            executed.add(key)

            if node.node_type == "source":
                source_rows_out = ports.get("out") or []
                ctx.source_rows.extend(source_rows_out)
                ctx.source_row_count += len(source_rows_out)
                if len(ctx.source_rows) > limit:
                    raise ValueError(f"数据源累计 {len(ctx.source_rows)} 行，"
                                     f"超过单次上限 {limit}")

        quality_summary: dict = {}
        try:
            from pipeline import insights
            from pipeline.quality import output_rows_for_run, run_quality_checks

            rows = output_rows_for_run(run)
            quality_summary = run_quality_checks(pipeline, run, rows)
            ctx.log("info", f"质量检查 {quality_summary['total']} 条规则，"
                            f"失败 {quality_summary['failed']} 条")
            insights.record_lineage(pipeline, run)
        except Exception as exc:  # noqa: BLE001 —— 质检 / 血缘失败不算数据链路失败
            quality_summary = {"error": f"{type(exc).__name__}: {exc}"}
            ctx.log("warning", f"质量检查或血缘记录失败：{exc}")

        _finish_success(pipeline, run, ctx, quality_summary)
    except RunTimeout as exc:
        _finish_failure(pipeline, run, ctx, f"运行超时：{exc}")
        _mark_skipped(pipeline, run, order, executed, ctx)
    except ValueError as exc:
        _finish_failure(pipeline, run, ctx, str(exc))
        _mark_skipped(pipeline, run, order, executed, ctx)
    except Exception as exc:  # noqa: BLE001 —— 兜底：任何异常都要留下失败运行
        _finish_failure(pipeline, run, ctx, f"{type(exc).__name__}: {exc}")
        _mark_skipped(pipeline, run, order, executed, ctx)

    run.refresh_from_db()
    return run


def cancel_run(run: PipelineRun, actor=None) -> PipelineRun:
    """取消运行：仅 queued / running 可取消，已结束的运行不允许改写状态。"""
    if run.status not in ("queued", "running"):
        raise ValueError(f"当前状态 {run.status} 不可取消")
    run.status = "cancelled"
    run.finished_at = timezone.now()
    if run.started_at:
        run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    run.save(update_fields=["status", "finished_at", "duration_ms", "updated_at"])
    RunLog.objects.create(owner=run.owner, run=run, level="warning",
                          message="运行被手动取消",
                          context={"actor": getattr(actor, "username", "")})
    return run


def rerun_failed(run: PipelineRun, actor=None) -> PipelineRun:
    """重跑失败节点：从第一个失败节点开始重跑整条链路。

    中间结果不落盘，因此无法只重算下游；这里明确重算上游以保证输入一致，
    并在新运行上标记 ``resumed_from``，让审计者知道这是补救运行。
    """
    failed = run.steps.filter(status="failed").order_by("seq", "id").first()
    if failed is None:
        raise ValueError("该运行没有失败的节点，无需重跑")
    pipeline = run.pipeline
    new_run = run_pipeline(pipeline, trigger="retry", actor=actor,
                           options={"resume_from": failed.node_key})
    new_run.resumed_from = failed.node_key
    new_run.save(update_fields=["resumed_from", "updated_at"])
    RunLog.objects.create(
        owner=pipeline.owner, run=new_run, level="info",
        message=f"从失败节点 {failed.node_key} 重跑（上游节点重算以保证输入一致）",
        node_key=failed.node_key, context={"source_run": run.id},
    )
    return new_run


def compare_runs(run_a: PipelineRun, run_b: PipelineRun) -> dict:
    """运行对比：状态、行数、耗时、节点级差异与质量结果差异。"""
    if run_a.pipeline_id != run_b.pipeline_id:
        raise ValueError("只能对比同一管道的两次运行")
    steps_a = {s.node_key: s for s in run_a.steps.order_by("seq", "id")}
    steps_b = {s.node_key: s for s in run_b.steps.order_by("seq", "id")}
    nodes = sorted(set(steps_a) | set(steps_b))
    step_diff = []
    for key in nodes:
        left, right = steps_a.get(key), steps_b.get(key)
        step_diff.append({
            "node_key": key,
            "node_type": (left or right).node_type,
            "status_a": left.status if left else "missing",
            "status_b": right.status if right else "missing",
            "duration_a": left.duration_ms if left else 0,
            "duration_b": right.duration_ms if right else 0,
            "duration_delta": (right.duration_ms if right else 0) - (left.duration_ms if left else 0),
            "output_a": left.output_rows if left else 0,
            "output_b": right.output_rows if right else 0,
            "output_delta": (right.output_rows if right else 0) - (left.output_rows if left else 0),
        })
    quality_a = run_a.quality_results.count()
    quality_b = run_b.quality_results.count()
    failed_a = run_a.quality_results.filter(passed=False).count()
    failed_b = run_b.quality_results.filter(passed=False).count()
    return {
        "pipeline_id": run_a.pipeline_id,
        "run_a": {"id": run_a.id, "status": run_a.status, "trigger": run_a.trigger,
                  "duration_ms": run_a.duration_ms, "input_rows": run_a.input_rows,
                  "output_rows": run_a.output_rows,
                  "started_at": run_a.started_at.isoformat() if run_a.started_at else None},
        "run_b": {"id": run_b.id, "status": run_b.status, "trigger": run_b.trigger,
                  "duration_ms": run_b.duration_ms, "input_rows": run_b.input_rows,
                  "output_rows": run_b.output_rows,
                  "started_at": run_b.started_at.isoformat() if run_b.started_at else None},
        "duration_delta": run_b.duration_ms - run_a.duration_ms,
        "input_delta": run_b.input_rows - run_a.input_rows,
        "output_delta": run_b.output_rows - run_a.output_rows,
        "status_changed": run_a.status != run_b.status,
        "steps": step_diff,
        "quality": {
            "a": {"total": quality_a, "failed": failed_a},
            "b": {"total": quality_b, "failed": failed_b},
        },
    }


def preview_source(node_config: dict, limit: int = 20) -> dict:
    """连接 / 节点试跑预览：只取数，不创建运行。"""
    result = source_rows(node_config or {}, limit=min(limit, MAX_PAGE_SIZE))
    return result


def next_run_preview(pipeline, limit: int = 3) -> list[dict]:
    """调度预览占位：真实计算在 schedule 模块，runner 只负责运行。"""
    from pipeline.schedule import preview_next_runs

    return preview_next_runs(pipeline, limit)


__all__ = [
    "RunContext", "RunTimeout", "cancel_run", "compare_runs", "next_run_preview",
    "preview_source", "rerun_failed", "run_pipeline",
]
