# -*- coding: utf-8 -*-
"""视图公共层：入参解析、分页、序列化、脱敏。

为什么单独一层：
- 列表接口有 20 多个，如果每个视图各写一份 page/page_size 解析，
  上限 200 这类规则迟早会在某个接口漏掉；
- 连接 / 凭据的密钥脱敏必须在序列化层统一做，任何视图都拿不到明文，
  从源头上杜绝「新接口忘了打码」；
- 时间统一输出 ISO 字符串，前端不用猜时区。
"""
from __future__ import annotations

from django.db.models import Q

from devtools.common import opt_num, opt_str, p
from pipeline.models import CONNECTION_STATUS_LABELS, CONNECTOR_KIND_LABELS, \
    NODE_TYPE_LABELS, PIPELINE_STATUS_LABELS, RUN_STATUS_LABELS, \
    STEP_STATUS_LABELS, TRIGGER_TYPE_LABELS
from pipeline.schedule import describe_cron

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# 入参
# ---------------------------------------------------------------------------


def payload(request) -> dict:
    """POST 请求体：必须是 JSON 对象，数组 / 文本一律拒绝。"""
    if request.method == "GET":
        return request.query_params.dict()
    data = request.data
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return data


def int_param(request, key: str, default=None, minimum=None, maximum=None) -> int:
    """整数入参：缺失取默认值，越界抛中文错误。"""
    value = p(request, key, default)
    if value is None or value == "":
        if default is None:
            raise ValueError(f"缺少必填参数: {key}")
        value = default
    return int(round(float(opt_num(request, key, default, minimum=minimum,
                                   maximum=maximum, integer=True))))


def str_param(request, key: str, default: str = "", max_len: int = 500) -> str:
    """字符串入参：统一裁剪长度，避免超长文本进入查询。"""
    value = opt_str(request, key, default, max_len=max_len)
    return value.strip()


def bool_param(request, key: str, default: bool = False) -> bool:
    """布尔入参：兼容 true/1/on 与字符串形式。"""
    value = p(request, key, default)
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def json_param(request, key: str, default=None, expect=dict):
    """JSON 入参：允许对象 / 数组直接传，也允许 JSON 字符串。"""
    value = p(request, key, default)
    if value is None:
        return default
    if isinstance(value, str):
        import json

        text = value.strip()
        if not text:
            return default
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"参数 {key} 不是合法 JSON：{exc.msg}")
    if expect is not None and not isinstance(value, expect):
        kind = "对象" if expect is dict else "数组"
        raise ValueError(f"参数 {key} 必须是{kind}")
    return value


def list_param(request, key: str, default=None, max_items: int = 500) -> list:
    """数组入参：JSON 字符串与原生数组都接受，条数封顶。"""
    value = json_param(request, key, default if default is not None else [], expect=list)
    if len(value) > max_items:
        raise ValueError(f"参数 {key} 最多 {max_items} 项")
    return value


def page_params(request) -> tuple[int, int]:
    """分页参数：page ≥ 1，page_size 1~200，默认 20。"""
    page = int_param(request, "page", 1, minimum=1, maximum=100000)
    size = int_param(request, "page_size", DEFAULT_PAGE_SIZE, minimum=1,
                     maximum=MAX_PAGE_SIZE)
    return page, size


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


def apply_search(qs, request, fields: list[str]):
    """q 模糊搜索：多字段 OR，空 q 不改变 queryset。"""
    keyword = str_param(request, "q", "", max_len=100)
    if not keyword or not fields:
        return qs
    cond = Q()
    for field in fields:
        cond |= Q(**{f"{field}__icontains": keyword})
    return qs.filter(cond)


def apply_status(qs, request, field: str = "status", choices=None):
    """status 过滤：多值用逗号分隔；非法值不静默返回全部。"""
    raw = str_param(request, "status", "", max_len=200)
    if not raw:
        return qs
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if choices is not None:
        invalid = [item for item in values if item not in choices]
        if invalid:
            raise ValueError(f"不支持的状态：{', '.join(invalid)}")
    return qs.filter(**{f"{field}__in": values})


def paginate(qs, page: int, size: int, serializer) -> dict:
    """统一列表结构：items / count / page / page_size。"""
    count = qs.count()
    offset = (page - 1) * size
    items = [serializer(obj) for obj in qs[offset:offset + size]]
    return {"items": items, "count": count, "page": page, "page_size": size}


def list_payload(items: list, count: int | None = None, page: int = 1,
                 size: int | None = None) -> dict:
    """非 queryset 列表（内存计算）也保持同一信封。"""
    size = size or len(items) or DEFAULT_PAGE_SIZE
    return {"items": items, "count": len(items) if count is None else count,
            "page": page, "page_size": size}


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def iso(value) -> str | None:
    return value.isoformat() if value else None


def connector_dict(obj, with_template: bool = True) -> dict:
    data = {
        "id": obj.id,
        "name": obj.name,
        "kind": obj.kind,
        "kind_label": CONNECTOR_KIND_LABELS.get(obj.kind, obj.kind),
        "capabilities": obj.capabilities or [],
        "builtin": obj.builtin,
        "description": obj.description,
        "docs_url": obj.docs_url,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }
    if with_template:
        data["config_template"] = obj.config_template or {}
    return data


def credential_dict(obj) -> dict:
    """凭据引用：只返回名称与类型，**永远不返回密钥本体**。"""
    return {
        "id": obj.id,
        "name": obj.name,
        "kind": obj.kind,
        "description": obj.description,
        "provider": obj.provider,
        "last_rotated_at": iso(obj.last_rotated_at),
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }


def connection_dict(obj, with_config: bool = True) -> dict:
    """连接：配置脱敏、密钥只给名称与「是否已配置」。"""
    from pipeline.services import sanitize_config

    sanitized, masked = sanitize_config(obj.config or {})
    data = {
        "id": obj.id,
        "name": obj.name,
        "connector_id": obj.connector_id,
        "connector_name": obj.connector.name if obj.connector_id else "",
        "connector_kind": obj.connector.kind if obj.connector_id else "",
        "status": obj.status,
        "status_label": CONNECTION_STATUS_LABELS.get(obj.status, obj.status),
        "secret_ref": obj.secret_ref,
        "has_secret": bool(obj.secret_ref),
        "masked_keys": masked,
        "last_tested_at": iso(obj.last_tested_at),
        "last_error": obj.last_error,
        "description": obj.description,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }
    if with_config:
        data["config"] = sanitized
    return data


def pipeline_dict(obj, with_counts: bool = False) -> dict:
    data = {
        "id": obj.id,
        "code": obj.code,
        "name": obj.name,
        "description": obj.description,
        "status": obj.status,
        "status_label": PIPELINE_STATUS_LABELS.get(obj.status, obj.status),
        "concurrency": obj.concurrency,
        "max_retries": obj.max_retries,
        "timeout_seconds": obj.timeout_seconds,
        "assignee": obj.assignee,
        "tags": obj.tags or [],
        "watermark_field": obj.watermark_field,
        "watermark_value": obj.watermark_value,
        "row_limit": obj.row_limit,
        "version": obj.version,
        "last_run_at": iso(obj.last_run_at),
        "last_run_status": obj.last_run_status,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }
    if with_counts:
        data.update({
            "node_count": obj.nodes.count(),
            "edge_count": obj.edges.count(),
            "mapping_count": obj.mappings.count(),
            "schedule_count": obj.schedules.count(),
            "quality_rule_count": obj.quality_rules.count(),
            "run_count": obj.runs.count(),
        })
    return data


def node_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "node_key": obj.node_key,
        "name": obj.name,
        "node_type": obj.node_type,
        "node_type_label": NODE_TYPE_LABELS.get(obj.node_type, obj.node_type),
        "config": obj.config or {},
        "order": obj.order,
        "position_x": obj.position_x,
        "position_y": obj.position_y,
        "enabled": obj.enabled,
        "description": obj.description,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }


def edge_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "source": obj.source.node_key if obj.source_id else "",
        "target": obj.target.node_key if obj.target_id else "",
        "source_id": obj.source_id,
        "target_id": obj.target_id,
        "source_port": obj.source_port,
        "target_port": obj.target_port,
        "order": obj.order,
        "created_at": iso(obj.created_at),
    }


def mapping_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "node_id": obj.node_id,
        "node_key": obj.node.node_key if obj.node_id else "",
        "source_field": obj.source_field,
        "target_field": obj.target_field,
        "cast": obj.cast,
        "default_value": obj.default_value,
        "expression": obj.expression,
        "required": obj.required,
        "order": obj.order,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }


def variable_dict(obj) -> dict:
    return {
        "id": obj.id,
        "name": obj.name,
        "value": obj.value,
        "kind": obj.kind,
        "description": obj.description,
        "updated_at": iso(obj.updated_at),
    }


def schedule_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "pipeline_code": obj.pipeline.code if obj.pipeline_id else "",
        "pipeline_name": obj.pipeline.name if obj.pipeline_id else "",
        "name": obj.name,
        "cron": obj.cron,
        "cron_description": describe_cron(obj.cron),
        "timezone": obj.timezone,
        "enabled": obj.enabled,
        "next_run_at": iso(obj.next_run_at),
        "last_run_at": iso(obj.last_run_at),
        "last_status": obj.last_status,
        "catchup": obj.catchup,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }


def run_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "pipeline_code": obj.pipeline.code if obj.pipeline_id else "",
        "pipeline_name": obj.pipeline.name if obj.pipeline_id else "",
        "trigger": obj.trigger,
        "trigger_label": TRIGGER_TYPE_LABELS.get(obj.trigger, obj.trigger),
        "status": obj.status,
        "status_label": RUN_STATUS_LABELS.get(obj.status, obj.status),
        "actor_id": obj.actor_id,
        "actor_name": getattr(obj.actor, "username", "") if obj.actor_id else "",
        "started_at": iso(obj.started_at),
        "finished_at": iso(obj.finished_at),
        "duration_ms": obj.duration_ms,
        "input_rows": obj.input_rows,
        "output_rows": obj.output_rows,
        "error": obj.error,
        "watermark_before": obj.watermark_before,
        "watermark_after": obj.watermark_after,
        "resumed_from": obj.resumed_from,
        "stats": obj.stats or {},
        "created_at": iso(obj.created_at),
    }


def step_dict(obj) -> dict:
    return {
        "id": obj.id,
        "run_id": obj.run_id,
        "node_id": obj.node_id,
        "node_key": obj.node_key,
        "node_type": obj.node_type,
        "node_type_label": NODE_TYPE_LABELS.get(obj.node_type, obj.node_type),
        "seq": obj.seq,
        "attempt": obj.attempt,
        "status": obj.status,
        "status_label": STEP_STATUS_LABELS.get(obj.status, obj.status),
        "duration_ms": obj.duration_ms,
        "input_rows": obj.input_rows,
        "output_rows": obj.output_rows,
        "error": obj.error,
        "summary": obj.summary,
        "created_at": iso(obj.created_at),
    }


def log_dict(obj) -> dict:
    return {
        "id": obj.id,
        "run_id": obj.run_id,
        "level": obj.level,
        "message": obj.message,
        "node_key": obj.node_key,
        "context": obj.context or {},
        "logged_at": iso(obj.logged_at),
    }


def output_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "run_id": obj.run_id,
        "node_id": obj.node_id,
        "dataset": obj.dataset,
        "seq": obj.seq,
        "data": obj.data or {},
        "created_at": iso(obj.created_at),
    }


def quality_rule_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "name": obj.name,
        "rule_type": obj.rule_type,
        "field": obj.field,
        "params": obj.params or {},
        "severity": obj.severity,
        "enabled": obj.enabled,
        "description": obj.description,
        "last_checked_at": iso(obj.last_checked_at),
        "last_passed": obj.last_passed,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }


def quality_result_dict(obj) -> dict:
    return {
        "id": obj.id,
        "rule_id": obj.rule_id,
        "rule_name": obj.rule.name if obj.rule_id else "",
        "rule_type": obj.rule.rule_type if obj.rule_id else "",
        "severity": obj.rule.severity if obj.rule_id else "",
        "run_id": obj.run_id,
        "pipeline_id": obj.run.pipeline_id if obj.run_id else None,
        "passed": obj.passed,
        "checked_rows": obj.checked_rows,
        "failed_rows": obj.failed_rows,
        "sample": obj.sample or [],
        "message": obj.message,
        "duration_ms": obj.duration_ms,
        "created_at": iso(obj.created_at),
    }


def lineage_dict(obj) -> dict:
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "run_id": obj.run_id,
        "upstream_type": obj.upstream_type,
        "upstream_key": obj.upstream_key,
        "downstream_type": obj.downstream_type,
        "downstream_key": obj.downstream_key,
        "field_map": obj.field_map or [],
        "updated_at": iso(obj.updated_at),
    }


def webhook_dict(obj, secret_once: str = "") -> dict:
    """Webhook 触发：默认只回显提示串；创建时可通过 secret_once 回显一次。"""
    data = {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "name": obj.name,
        "enabled": obj.enabled,
        "secret_hint": obj.secret_hint,
        "secret_configured": bool(obj.secret_digest),
        "last_triggered_at": iso(obj.last_triggered_at),
        "trigger_count": obj.trigger_count,
        "description": obj.description,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }
    if secret_once:
        data["secret"] = secret_once
        data["secret_notice"] = "密钥仅在创建时展示一次，请立即保存"
    return data


def pipeline_dag_payload(pipeline) -> dict:
    """DAG 视图数据：节点 + 连线 + 映射，画布一次拉全。"""
    from pipeline.expressions import function_catalog

    nodes = [node_dict(n) for n in pipeline.nodes.order_by("order", "id")]
    edges = [edge_dict(e) for e in pipeline.edges.select_related("source", "target")
             .order_by("order", "id")]
    return {
        "pipeline": pipeline_dict(pipeline, with_counts=True),
        "nodes": nodes,
        "edges": edges,
        "mappings": [mapping_dict(m) for m in pipeline.mappings.order_by("order", "id")],
        "variables": [variable_dict(v) for v in pipeline.variables.order_by("name")],
        "functions": function_catalog(),
    }
