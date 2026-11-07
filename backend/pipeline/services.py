# -*- coding: utf-8 -*-
"""服务层门面：对外提供「解析对象 / 导入导出 / 版本 / 批量保存」能力。

引擎细节分散在 dag / executors / runner / quality / insights / stats，
本模块负责把它们组织成视图可以直接调用的高层动作，并统一：

- 对象解析（读走数据范围，写严格 owner）；
- 配置脱敏（密钥字段只回显名称，配置里的敏感键打码）；
- 事务边界（节点 + 连线 + 映射 + 规则必须原子落库）；
- JSON 导出 / 导入与版本快照（同一套序列化，保证往返一致）。
"""
from __future__ import annotations

import copy
import re
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from core.scoping import can_write, get_owned, scope_queryset
from pipeline.catalog import BUILTIN_CONNECTORS, MAX_PAGE_SIZE, MAX_RUN_ROWS
from pipeline.dag import validate_dag, validate_node_config
from pipeline.insights import generate_profile, profile_summary, record_lineage
from pipeline.models import (CredentialRef, Connector, Connection, Mapping,
                             PipeEdge, PipeNode, Pipeline, PipelineRun,
                             PipelineVariable, PipelineVersion, Schedule,
                             DataQualityRule, WebhookTrigger)
from pipeline.quality import evaluate_rule, run_quality_checks, test_rule
from pipeline.runner import cancel_run, compare_runs, rerun_failed, run_pipeline
from pipeline.schedule import (describe_cron, mark_schedule_run, next_run_time,
                               normalize_cron, preview_next_runs)
from pipeline.stats import (failed_nodes, latency, overview, pipeline_stats,
                            row_trend, success_rate)

# 疑似密钥的键名：命中即打码（只保留键名，方便用户知道自己配过什么）
_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"credential|authorization|cookie|session|signature)", re.IGNORECASE)
_SECRET_MASK = "******"
_URL_USERINFO_RE = re.compile(r"(https?://)([^/@\s]+)@")


def mask_value(value) -> str:
    """密钥打码：固定长度，避免通过长度侧信道判断原文。"""
    return _SECRET_MASK


def sanitize_config(config, prefix: str = "") -> tuple:
    """递归脱敏配置中的敏感键与 URL 内嵌凭据。

    返回 ``(sanitized, masked_keys)``；``masked_keys`` 只含键路径，
    不含值——它用于前端提示「这里配过密钥」，而不是回显任何内容。
    """
    masked: list[str] = []

    def walk(value, path):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                key_path = f"{path}.{key}" if path else str(key)
                if _SECRET_KEY_RE.search(str(key)) and item not in (None, ""):
                    out[key] = mask_value(item)
                    masked.append(key_path)
                else:
                    out[key] = walk(item, key_path)
            return out
        if isinstance(value, list):
            return [walk(item, f"{path}[{index}]") for index, item in enumerate(value)]
        if isinstance(value, str) and _URL_USERINFO_RE.search(value):
            masked.append(path or "url")
            return _URL_USERINFO_RE.sub(r"\1******@", value)
        return value

    return walk(config if config is not None else {}, prefix), masked


def resolve_pipeline(user, pk, write: bool = False) -> Pipeline:
    """解析管道：读按数据范围，写严格 owner。"""
    if write:
        pipeline = get_owned(Pipeline.objects.all(), user, pk)
        if pipeline is None:
            raise ValueError("管道不存在或无权修改")
    else:
        pipeline = scope_queryset(Pipeline.objects.all(), user).filter(pk=pk).first()
        if pipeline is None:
            raise ValueError("管道不存在或无权查看")
    return pipeline


def resolve_connection(user, pk, write: bool = False) -> Connection:
    """解析连接：读对同数据范围可见，写仅 owner。"""
    if write:
        connection = get_owned(Connection.objects.select_related("connector"), user, pk)
        if connection is None:
            raise ValueError("连接不存在或无权修改")
    else:
        connection = (scope_queryset(Connection.objects.select_related("connector"), user)
                      .filter(pk=pk).first())
        if connection is None:
            raise ValueError("连接不存在或无权查看")
    return connection


def resolve_credential(user, pk, write: bool = False) -> CredentialRef:
    """解析凭据引用（永远不含密钥本体）。"""
    if write:
        credential = get_owned(CredentialRef.objects.all(), user, pk)
        if credential is None:
            raise ValueError("凭据不存在或无权修改")
    else:
        credential = scope_queryset(CredentialRef.objects.all(), user).filter(pk=pk).first()
        if credential is None:
            raise ValueError("凭据不存在或无权查看")
    return credential


def validate_secret_ref(owner, secret_ref: str) -> str:
    """校验密钥引用名存在；只允许名称，拒绝看起来像明文的长串。"""
    secret_ref = (secret_ref or "").strip()
    if not secret_ref:
        return ""
    if len(secret_ref) > 120:
        raise ValueError("密钥引用名不能超过 120 字符")
    if not CredentialRef.objects.filter(owner=owner, name=secret_ref).exists():
        raise ValueError(f"密钥引用 {secret_ref} 不存在，请先创建凭据")
    return secret_ref


def require_write(user, obj, message: str = "无权修改该对象") -> None:
    """写权限断言（单对象）。"""
    if not can_write(user, obj):
        raise ValueError(message)


# ---------------------------------------------------------------------------
# 序列化辅助（导入导出与快照共用）
# ---------------------------------------------------------------------------


def _node_snapshot(node: PipeNode) -> dict:
    return {
        "node_key": node.node_key,
        "name": node.name,
        "node_type": node.node_type,
        "config": node.config or {},
        "order": node.order,
        "position_x": node.position_x,
        "position_y": node.position_y,
        "enabled": node.enabled,
        "description": node.description,
    }


def _edge_snapshot(edge: PipeEdge) -> dict:
    return {
        "source": edge.source.node_key,
        "target": edge.target.node_key,
        "source_port": edge.source_port,
        "target_port": edge.target_port,
        "order": edge.order,
    }


def _mapping_snapshot(mapping: Mapping) -> dict:
    return {
        "node": mapping.node.node_key if mapping.node_id else "",
        "source_field": mapping.source_field,
        "target_field": mapping.target_field,
        "cast": mapping.cast,
        "default_value": mapping.default_value,
        "expression": mapping.expression,
        "required": mapping.required,
        "order": mapping.order,
    }


def _rule_snapshot(rule: DataQualityRule) -> dict:
    return {
        "name": rule.name,
        "rule_type": rule.rule_type,
        "field": rule.field,
        "params": rule.params or {},
        "severity": rule.severity,
        "enabled": rule.enabled,
        "description": rule.description,
    }


def _variable_snapshot(variable: PipelineVariable) -> dict:
    return {
        "name": variable.name,
        "value": variable.value,
        "kind": variable.kind,
        "description": variable.description,
    }


def _schedule_snapshot(schedule: Schedule) -> dict:
    return {
        "name": schedule.name,
        "cron": schedule.cron,
        "timezone": schedule.timezone,
        "enabled": schedule.enabled,
        "catchup": schedule.catchup,
    }


def export_pipeline(pipeline, include_schedules: bool = True) -> dict:
    """导出为可移植 JSON：不含主键与运行数据，可安全跨环境迁移。"""
    nodes = list(pipeline.nodes.order_by("order", "id"))
    edges = list(pipeline.edges.select_related("source", "target").order_by("order", "id"))
    payload = {
        "format": "pipeline/v1",
        "exported_at": timezone.now().isoformat(),
        "pipeline": {
            "code": pipeline.code,
            "name": pipeline.name,
            "description": pipeline.description,
            "concurrency": pipeline.concurrency,
            "max_retries": pipeline.max_retries,
            "timeout_seconds": pipeline.timeout_seconds,
            "assignee": pipeline.assignee,
            "tags": pipeline.tags or [],
            "watermark_field": pipeline.watermark_field,
            "watermark_value": pipeline.watermark_value,
            "row_limit": pipeline.row_limit,
            "version": pipeline.version,
        },
        "nodes": [_node_snapshot(node) for node in nodes],
        "edges": [_edge_snapshot(edge) for edge in edges],
        "mappings": [_mapping_snapshot(m) for m in pipeline.mappings.order_by("order", "id")],
        "quality_rules": [_rule_snapshot(r) for r in pipeline.quality_rules.order_by("id")],
        "variables": [_variable_snapshot(v) for v in pipeline.variables.order_by("name")],
    }
    if include_schedules:
        payload["schedules"] = [_schedule_snapshot(s)
                                for s in pipeline.schedules.order_by("id")]
    return payload


def _unique_code(owner, base: str) -> str:
    """生成不冲突的管道编码：base / base-2 / base-3 …"""
    base = (base or "pipeline").strip()[:70] or "pipeline"
    code = base
    index = 2
    while Pipeline.objects.filter(owner=owner, code=code).exists():
        suffix = f"-{index}"
        code = f"{base[:70 - len(suffix)]}{suffix}"
        index += 1
        if index > 999:
            raise ValueError("无法生成唯一的管道编码")
    return code


def clean_code(value: str) -> str:
    """管道编码只允许字母数字与 - _ .，避免 URL / 日志里出现怪字符。"""
    value = str(value or "").strip()
    if not value:
        raise ValueError("管道编码不能为空")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", value):
        raise ValueError("管道编码只能包含字母、数字、下划线、点和短横线")
    return value


def _create_node(pipeline, item: dict, order: int) -> PipeNode:
    node = PipeNode(
        owner=pipeline.owner,
        pipeline=pipeline,
        node_key=str(item.get("node_key") or "").strip(),
        name=str(item.get("name") or item.get("node_key") or "").strip()[:120],
        node_type=str(item.get("node_type") or "transform"),
        config=item.get("config") if isinstance(item.get("config"), dict) else {},
        order=int(item.get("order", order)),
        position_x=float(item.get("position_x", 0) or 0),
        position_y=float(item.get("position_y", 0) or 0),
        enabled=bool(item.get("enabled", True)),
        description=str(item.get("description") or ""),
    )
    if not node.node_key:
        raise ValueError("节点缺少 node_key")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", node.node_key):
        raise ValueError(f"节点标识 {node.node_key} 只能包含字母、数字、下划线、点和短横线")
    return node


@transaction.atomic
def import_pipeline(user, payload: dict, code_override: str = "") -> dict:
    """导入 JSON：在事务内创建管道 + 节点 + 连线 + 映射 + 规则。

    导入允许「草稿态」的不完整 DAG（可能还没连完线），但引用不存在的
    节点 / 端口会直接拒绝，避免把垃圾数据写进库。
    """
    if payload is None or not isinstance(payload, dict):
        raise ValueError("导入内容必须是 JSON 对象")
    meta = payload.get("pipeline")
    if not isinstance(meta, dict):
        raise ValueError("导入内容缺少 pipeline 元信息")
    code = clean_code(code_override or meta.get("code") or "")
    nodes_payload = payload.get("nodes") or []
    edges_payload = payload.get("edges") or []
    if not isinstance(nodes_payload, list) or not isinstance(edges_payload, list):
        raise ValueError("nodes 与 edges 必须是数组")
    if not nodes_payload:
        raise ValueError("导入的管道至少需要一个节点")

    pipeline = Pipeline.objects.create(
        owner=user,
        code=_unique_code(user, code),
        name=str(meta.get("name") or code)[:200],
        description=str(meta.get("description") or ""),
        status="draft",
        concurrency=str(meta.get("concurrency") or "skip"),
        max_retries=int(meta.get("max_retries", 1) or 0),
        timeout_seconds=int(meta.get("timeout_seconds", 120) or 120),
        assignee=str(meta.get("assignee") or "")[:80],
        tags=meta.get("tags") if isinstance(meta.get("tags"), list) else [],
        watermark_field=str(meta.get("watermark_field") or "")[:80],
        watermark_value=str(meta.get("watermark_value") or "")[:200],
        row_limit=int(meta.get("row_limit", MAX_RUN_ROWS) or MAX_RUN_ROWS),
    )

    node_map: dict[str, PipeNode] = {}
    created_nodes = []
    for order, item in enumerate(nodes_payload):
        if not isinstance(item, dict):
            raise ValueError(f"第 {order + 1} 个节点不是对象")
        node = _create_node(pipeline, item, order)
        if node.node_key in node_map:
            raise ValueError(f"节点标识重复：{node.node_key}")
        node.save()
        node_map[node.node_key] = node
        created_nodes.append(node)

    created_edges = []
    for item in edges_payload:
        if not isinstance(item, dict):
            raise ValueError("连线必须是对象")
        src = node_map.get(str(item.get("source") or ""))
        dst = node_map.get(str(item.get("target") or ""))
        if src is None or dst is None:
            raise ValueError("连线引用了不存在的节点")
        edge = PipeEdge.objects.create(
            owner=user, pipeline=pipeline, source=src, target=dst,
            source_port=str(item.get("source_port") or "out")[:30],
            target_port=str(item.get("target_port") or "in")[:30],
            order=int(item.get("order", 0) or 0),
        )
        created_edges.append(edge)

    for index, item in enumerate(payload.get("mappings") or []):
        if not isinstance(item, dict):
            raise ValueError("字段映射必须是对象")
        node = node_map.get(str(item.get("node") or "")) if item.get("node") else None
        target = str(item.get("target_field") or "").strip()
        if not target:
            raise ValueError(f"第 {index + 1} 条映射缺少 target_field")
        Mapping.objects.create(
            owner=user, pipeline=pipeline, node=node,
            source_field=str(item.get("source_field") or "")[:120],
            target_field=target[:120],
            cast=str(item.get("cast") or "")[:20],
            default_value=item.get("default_value"),
            expression=str(item.get("expression") or ""),
            required=bool(item.get("required")),
            order=int(item.get("order", index) or 0),
        )

    for index, item in enumerate(payload.get("quality_rules") or []):
        if not isinstance(item, dict):
            raise ValueError("质量规则必须是对象")
        _create_rule(pipeline, item, index)

    for item in payload.get("variables") or []:
        if isinstance(item, dict) and item.get("name"):
            PipelineVariable.objects.create(
                owner=user, pipeline=pipeline,
                name=str(item["name"])[:80],
                value=item.get("value"),
                kind=str(item.get("kind") or "string")[:20],
                description=str(item.get("description") or "")[:300],
            )

    created_schedules = []
    for item in payload.get("schedules") or []:
        if not isinstance(item, dict):
            continue
        cron = normalize_cron(str(item.get("cron") or "0 * * * *"))
        schedule = Schedule.objects.create(
            owner=user, pipeline=pipeline,
            name=str(item.get("name") or f"调度-{len(created_schedules) + 1}")[:120],
            cron=cron,
            timezone=str(item.get("timezone") or "Asia/Shanghai")[:64],
            enabled=bool(item.get("enabled", True)),
            catchup=bool(item.get("catchup")),
        )
        if schedule.enabled:
            schedule.next_run_at = next_run_time(cron, None, schedule.timezone)
            schedule.save(update_fields=["next_run_at"])
        created_schedules.append(schedule)

    report = validate_dag(pipeline)
    return {
        "pipeline_id": pipeline.id,
        "code": pipeline.code,
        "node_count": len(created_nodes),
        "edge_count": len(created_edges),
        "schedule_count": len(created_schedules),
        "validation": {"valid": report["valid"], "errors": report["errors"],
                       "warnings": report["warnings"]},
    }


def _create_rule(pipeline, item: dict, index: int) -> DataQualityRule:
    """质量规则落库 + 静态校验（校验失败直接抛，导入整体回滚）。"""
    draft = SimpleNamespace(
        rule_type=str(item.get("rule_type") or "not_null"),
        field=str(item.get("field") or ""),
        params=item.get("params") if isinstance(item.get("params"), dict) else {},
        severity=str(item.get("severity") or "warning"),
    )
    from pipeline.quality import validate_rule

    validate_rule(draft)
    return DataQualityRule.objects.create(
        owner=pipeline.owner,
        pipeline=pipeline,
        name=str(item.get("name") or f"规则-{index + 1}")[:120],
        rule_type=draft.rule_type,
        field=draft.field[:120],
        params=draft.params,
        severity=draft.severity,
        enabled=bool(item.get("enabled", True)),
        description=str(item.get("description") or "")[:300],
    )


@transaction.atomic
def clone_pipeline(source: Pipeline, user, code: str = "") -> Pipeline:
    """克隆管道：复制结构、映射、规则、变量与调度，不带运行与输出数据。"""
    payload = export_pipeline(source)
    payload["pipeline"]["code"] = code or f"{source.code}-copy"
    payload["pipeline"]["name"] = f"{source.name} 副本"
    result = import_pipeline(user, payload)
    return Pipeline.objects.get(pk=result["pipeline_id"])


def create_version(pipeline, note: str = "", published: bool = False) -> PipelineVersion:
    """生成版本快照：版本号取当前最大值 + 1，避免重复发布撞号。"""
    latest = pipeline.versions.order_by("-version").first()
    version_no = (latest.version + 1) if latest else 1
    snapshot = export_pipeline(pipeline)
    version = PipelineVersion.objects.create(
        owner=pipeline.owner, pipeline=pipeline, version=version_no,
        snapshot=snapshot, note=str(note or "")[:300], published=published,
    )
    pipeline.version = version_no
    pipeline.save(update_fields=["version", "updated_at"])
    return version


@transaction.atomic
def publish_pipeline(pipeline, note: str = "") -> dict:
    """发布：DAG 必须合法，随后创建版本快照并切换 active。"""
    report = validate_dag(pipeline)
    if not report["valid"]:
        message = "；".join(item["message"] for item in report["errors"][:4])
        raise ValueError(f"管道校验失败，无法发布：{message}")
    if pipeline.status == "archived":
        raise ValueError("已归档管道不能发布")
    version = create_version(pipeline, note=note or "发布", published=True)
    pipeline.status = "active"
    pipeline.save(update_fields=["status", "updated_at"])
    return {"version": version.version, "pipeline_status": pipeline.status,
            "validation": {"valid": True, "order": report["order"]}}


@transaction.atomic
def rollback_version(pipeline, version: PipelineVersion) -> dict:
    """回滚到历史版本：整体替换 DAG 结构，老运行记录保留不受影响。"""
    snapshot = copy.deepcopy(version.snapshot or {})
    if not isinstance(snapshot, dict) or not snapshot.get("nodes"):
        raise ValueError("该版本快照没有可恢复的节点")
    meta = snapshot.get("pipeline") or {}
    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []

    pipeline.nodes.all().delete()
    pipeline.edges.all().delete()
    pipeline.mappings.all().delete()
    pipeline.variables.all().delete()

    node_map: dict[str, PipeNode] = {}
    for order, item in enumerate(nodes):
        node = _create_node(pipeline, item, order)
        node.save()
        node_map[node.node_key] = node
    for item in edges:
        src = node_map.get(str(item.get("source") or ""))
        dst = node_map.get(str(item.get("target") or ""))
        if src is None or dst is None:
            continue
        PipeEdge.objects.create(
            owner=pipeline.owner, pipeline=pipeline, source=src, target=dst,
            source_port=str(item.get("source_port") or "out"),
            target_port=str(item.get("target_port") or "in"),
            order=int(item.get("order", 0) or 0),
        )
    for index, item in enumerate(snapshot.get("mappings") or []):
        node = node_map.get(str(item.get("node") or "")) if item.get("node") else None
        if not item.get("target_field"):
            continue
        Mapping.objects.create(
            owner=pipeline.owner, pipeline=pipeline, node=node,
            source_field=str(item.get("source_field") or "")[:120],
            target_field=str(item["target_field"])[:120],
            cast=str(item.get("cast") or "")[:20],
            default_value=item.get("default_value"),
            expression=str(item.get("expression") or ""),
            required=bool(item.get("required")),
            order=int(item.get("order", index) or 0),
        )
    for item in snapshot.get("variables") or []:
        if item.get("name"):
            PipelineVariable.objects.create(
                owner=pipeline.owner, pipeline=pipeline,
                name=str(item["name"])[:80], value=item.get("value"),
                kind=str(item.get("kind") or "string")[:20],
                description=str(item.get("description") or "")[:300],
            )

    pipeline.description = str(meta.get("description") or pipeline.description)
    pipeline.concurrency = str(meta.get("concurrency") or pipeline.concurrency)
    pipeline.max_retries = int(meta.get("max_retries", pipeline.max_retries) or 0)
    pipeline.timeout_seconds = int(meta.get("timeout_seconds", pipeline.timeout_seconds) or 120)
    pipeline.watermark_field = str(meta.get("watermark_field") or "")[:80]
    pipeline.watermark_value = str(meta.get("watermark_value") or "")[:200]
    pipeline.version = version.version
    pipeline.status = "draft"
    pipeline.save()
    report = validate_dag(pipeline)
    return {"pipeline_id": pipeline.id, "version": version.version,
            "validation": {"valid": report["valid"], "errors": report["errors"]}}


# ---------------------------------------------------------------------------
# 批量保存（画布粘贴 / 拖拽后一次性提交）
# ---------------------------------------------------------------------------


@transaction.atomic
def bulk_save_nodes(pipeline, items: list[dict], replace: bool = False) -> dict:
    """批量保存节点：按 node_key upsert，可选删除未提交的节点。"""
    if not isinstance(items, list):
        raise ValueError("nodes 必须是数组")
    if len(items) > 500:
        raise ValueError("一次最多保存 500 个节点")
    existing = {n.node_key: n for n in pipeline.nodes.all()}
    seen: set[str] = set()
    saved: list[PipeNode] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 个节点不是对象")
        node_key = str(item.get("node_key") or "").strip()
        if not node_key:
            raise ValueError(f"第 {index + 1} 个节点缺少 node_key")
        if node_key in seen:
            raise ValueError(f"节点标识重复：{node_key}")
        seen.add(node_key)
        node = existing.get(node_key) or PipeNode(owner=pipeline.owner,
                                                   pipeline=pipeline,
                                                   node_key=node_key)
        node.name = str(item.get("name") or node.name or node_key)[:120]
        node.node_type = str(item.get("node_type") or node.node_type or "transform")
        if node.node_type not in ("source", "transform", "filter", "aggregate",
                                  "join", "sort", "dedupe", "map", "sink", "webhook"):
            raise ValueError(f"不支持的节点类型：{node.node_type}")
        if "config" in item:
            if not isinstance(item["config"], dict):
                raise ValueError("节点 config 必须是对象")
            node.config = item["config"]
        node.order = int(item.get("order", node.order) or 0)
        node.position_x = float(item.get("position_x", node.position_x) or 0)
        node.position_y = float(item.get("position_y", node.position_y) or 0)
        node.enabled = bool(item.get("enabled", node.enabled))
        node.description = str(item.get("description", node.description) or "")
        errors = validate_node_config(SimpleNamespace(
            node_key=node.node_key, node_type=node.node_type, config=node.config))
        if errors:
            raise ValueError(f"节点 {node_key} 配置错误：{errors[0]['message']}")
        node.save()
        saved.append(node)

    removed = 0
    if replace:
        stale = [key for key in existing.keys() if key not in seen]
        for key in stale:
            pipeline.nodes.filter(node_key=key).delete()
            removed += 1
        # 级联删除会把相关映射一并带走，这里同步清理孤儿映射
        pipeline.mappings.filter(node__isnull=False, node__pipeline__isnull=True).delete()

    report = validate_dag(pipeline)
    return {
        "items": saved,
        "saved": len(saved),
        "removed": removed,
        "validation": {"valid": report["valid"], "errors": report["errors"],
                       "warnings": report["warnings"]},
    }


@transaction.atomic
def bulk_save_edges(pipeline, items: list[dict], replace: bool = True) -> dict:
    """批量保存连线：默认整体替换，避免画布删除后残留旧边。"""
    if not isinstance(items, list):
        raise ValueError("edges 必须是数组")
    if len(items) > 1000:
        raise ValueError("一次最多保存 1000 条连线")
    nodes = {n.node_key: n for n in pipeline.nodes.all()}
    if replace:
        pipeline.edges.all().delete()
    saved: list[PipeEdge] = []
    seen: set[tuple] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 条连线不是对象")
        src = nodes.get(str(item.get("source") or ""))
        dst = nodes.get(str(item.get("target") or ""))
        if src is None or dst is None:
            raise ValueError(f"第 {index + 1} 条连线引用了不存在的节点")
        if src.node_key == dst.node_key:
            raise ValueError("节点不能连到自己")
        source_port = str(item.get("source_port") or "out")[:30]
        target_port = str(item.get("target_port") or "in")[:30]
        signature = (src.node_key, source_port, dst.node_key, target_port)
        if signature in seen:
            raise ValueError(f"重复连线：{src.node_key} → {dst.node_key}")
        seen.add(signature)
        saved.append(PipeEdge.objects.create(
            owner=pipeline.owner, pipeline=pipeline, source=src, target=dst,
            source_port=source_port, target_port=target_port,
            order=int(item.get("order", index) or 0),
        ))
    report = validate_dag(pipeline)
    return {
        "items": saved,
        "saved": len(saved),
        "validation": {"valid": report["valid"], "errors": report["errors"],
                       "warnings": report["warnings"]},
    }


@transaction.atomic
def save_mapping(pipeline, payload: dict, mapping: Mapping | None = None) -> Mapping:
    """新增 / 更新字段映射。"""
    if not isinstance(payload, dict):
        raise ValueError("映射参数必须是对象")
    # 未显式提交节点时保留原节点：局部更新不应把映射悄悄变成管道级
    node = mapping.node if mapping is not None else None
    if "node_key" in payload or "node" in payload:
        node_key = payload.get("node_key") or payload.get("node")
        if node_key:
            node = pipeline.nodes.filter(node_key=str(node_key)).first()
            if node is None:
                raise ValueError(f"节点 {node_key} 不存在")
        else:
            node = None
    target = str(payload.get("target_field") or (mapping.target_field if mapping else "")).strip()
    if not target:
        raise ValueError("目标字段不能为空")
    if len(target) > 120:
        raise ValueError("目标字段不能超过 120 字符")
    expression = str(payload.get("expression", mapping.expression if mapping else "") or "")
    if expression:
        from pipeline.expressions import validate_expression

        report = validate_expression(expression)
        if not report["valid"]:
            raise ValueError(f"映射表达式错误：{report['error']}")
    cast = str(payload.get("cast", mapping.cast if mapping else "") or "")
    if cast:
        from pipeline.catalog import CAST_TYPES

        if cast not in CAST_TYPES:
            raise ValueError(f"不支持的类型转换：{cast}")
    if mapping is None:
        mapping = Mapping(owner=pipeline.owner, pipeline=pipeline)
    mapping.node = node
    mapping.source_field = str(payload.get("source_field", mapping.source_field) or "")[:120]
    mapping.target_field = target[:120]
    mapping.cast = cast[:20]
    if "default_value" in payload:
        mapping.default_value = payload.get("default_value")
    mapping.expression = expression
    mapping.required = bool(payload.get("required", mapping.required))
    mapping.order = int(payload.get("order", mapping.order) or 0)
    mapping.save()
    return mapping


# ---------------------------------------------------------------------------
# 运行 / 统计门面：视图只依赖服务层，方便以后替换执行后端
# ---------------------------------------------------------------------------


def run_now(pipeline, actor, trigger: str = "manual", rows=None) -> PipelineRun:
    """手动 / 接口触发运行（同步返回运行记录）。"""
    options = {}
    if rows is not None:
        if not isinstance(rows, list):
            raise ValueError("rows 必须是数组")
        options["rows"] = rows
    return run_pipeline(pipeline, trigger=trigger, actor=actor, options=options)


def pipeline_overview(pipeline, days: int = 30) -> dict:
    """管道详情页的统计卡片。"""
    return pipeline_stats(pipeline, days)


__all__ = [
    "BUILTIN_CONNECTORS", "MAX_PAGE_SIZE", "MAX_RUN_ROWS",
    "bulk_save_edges", "bulk_save_nodes", "cancel_run", "clone_pipeline",
    "compare_runs", "create_version", "describe_cron", "evaluate_rule",
    "export_pipeline", "failed_nodes", "generate_profile", "import_pipeline",
    "latency", "mark_schedule_run", "next_run_time", "normalize_cron",
    "overview", "pipeline_overview", "preview_next_runs", "profile_summary",
    "publish_pipeline", "record_lineage", "rerun_failed", "resolve_connection",
    "clean_code", "resolve_credential", "resolve_pipeline", "rollback_version", "row_trend",
    "run_now", "run_pipeline", "run_quality_checks", "sanitize_config",
    "save_mapping", "success_rate", "test_rule", "validate_secret_ref",
]
