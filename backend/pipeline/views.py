# -*- coding: utf-8 -*-
"""数据集成管道 · HTTP 视图（82 个接口）。

分组：
- 目录 1
- 连接器 4、凭据 4、连接 5
- 管道 14（CRUD / 克隆 / 发布 / 暂停 / 归档 / 校验 / 拓扑 / 导出 / 版本 / 统计）
- 节点 4、连线 3、映射 3、变量 3
- 调度 6（CRUD / 开关 / 下次运行 / 扫描）
- 运行 8（触发 / 列表 / 详情 / 步骤 / 日志 / 取消 / 失败重跑 / 对比）
- 输出 1、质量 5、血缘 4、画像 4、Webhook 5、统计 5

约定：
- 所有写操作在视图层先解析出「本人拥有」的对象，再落库；
- 跨表写入（归档 + 停调度、批量节点、导入、运行）统一包在事务里；
- 列表一律 ``{items, count, page, page_size}``，page_size 上限 200；
- 密钥只回显名称 / 摘要提示，任何接口都拿不到明文。
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from core.scoping import get_owned, scope_queryset
from devtools.common import endpoint, endpoint_index, ok, opt_num, p
from pipeline import insights, services, stats
from pipeline.catalog import (CAST_TYPES, CONNECTOR_KINDS, MAX_RETRIES,
                              MAX_RUN_ROWS, MAX_TIMEOUT, ensure_builtin_connectors)
from pipeline.common import (apply_search, apply_status, bool_param, connection_dict,
                             connector_dict, credential_dict, edge_dict, int_param, iso,
                             json_param, lineage_dict, list_param, list_payload,
                             log_dict, mapping_dict, node_dict, output_dict,
                             page_params, paginate, payload, pipeline_dag_payload,
                             pipeline_dict, quality_result_dict, quality_rule_dict,
                             run_dict, schedule_dict, step_dict, str_param,
                             variable_dict, webhook_dict)
from pipeline.dag import topology_preview, validate_dag, validate_node_config
from pipeline.generators import mark_connection_error, test_connection
from pipeline.insights import (compare_profiles, lineage_for_pipeline, generate_profile,
                               graph, impact_analysis, downstream_of, upstream_of)
from pipeline.models import (CONNECTION_STATUS, CONNECTOR_CAPABILITIES, CREDENTIAL_KINDS,
                             LOG_LEVELS, NODE_TYPES, PIPELINE_STATUS, QUALITY_RULE_TYPES,
                             QUALITY_SEVERITY, RUN_STATUS, STEP_STATUS, TRIGGER_TYPES,
                             Connector, Connection, CredentialRef, DataQualityRule,
                             DatasetProfile, LineageEdge, Mapping, PipeEdge, PipeNode,
                             Pipeline, PipelineOutput, PipelineRun, PipelineVariable,
                             QualityResult, Schedule, WebhookTrigger)
from pipeline.quality import test_rule, validate_rule
from pipeline.runner import cancel_run, compare_runs, preview_source, rerun_failed
from pipeline.schedule import (describe_cron, due_schedules, mark_schedule_run,
                               next_run_times, normalize_cron,
                               schedule_next_run as compute_schedule_next_run)

IDENT_RE = re.compile(r"[A-Za-z0-9_.\-]{1,80}")
VARIABLE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}")
VARIABLE_KINDS = ("string", "number", "boolean", "json")


# ---------------------------------------------------------------------------
# 局部辅助
# ---------------------------------------------------------------------------


def _text(request, key: str, max_len: int = 200) -> str:
    """必填文本：裁剪后为空直接 400，避免空名称落库。"""
    value = str_param(request, key, "", max_len=max_len)
    if not value:
        raise ValueError(f"缺少必填参数: {key}")
    return value


def _optional_text(request, key: str, default: str = "", max_len: int = 200) -> str:
    return str_param(request, key, default, max_len=max_len)


def _version_dict(obj) -> dict:
    """版本列表项：只回显节点 / 连线数量，不把整份快照塞进列表。"""
    snapshot = obj.snapshot or {}
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "version": obj.version,
        "note": obj.note,
        "published": obj.published,
        "node_count": len(snapshot.get("nodes") or []),
        "edge_count": len(snapshot.get("edges") or []),
        "created_at": iso(obj.created_at),
    }


def _profile_brief(obj) -> dict:
    columns = obj.columns or []
    return {
        "id": obj.id,
        "pipeline_id": obj.pipeline_id,
        "run_id": obj.run_id,
        "dataset": obj.dataset,
        "row_count": obj.row_count,
        "sample_size": obj.sample_size,
        "column_count": len(columns),
        "high_null_columns": [c.get("name") for c in columns
                              if (c.get("null_rate") or 0) >= 0.5],
        "sampled_at": iso(obj.sampled_at),
        "notes": obj.notes,
    }


def _scope_run(user, pk):
    """按数据范围取运行记录；找不到即视为无权限。"""
    run = (scope_queryset(PipelineRun.objects.select_related("pipeline", "actor"), user)
           .filter(pk=pk).first())
    if run is None:
        raise ValueError("运行记录不存在或无权查看")
    return run


def _owned_run(user, pk):
    """写操作用的运行记录：必须是本人管道产生的运行。"""
    run = get_owned(PipelineRun.objects.select_related("pipeline"), user, pk)
    if run is None:
        raise ValueError("运行记录不存在或无权操作")
    return run


def _owned_node(user, pk):
    node = get_owned(PipeNode.objects.select_related("pipeline"), user, pk)
    if node is None:
        raise ValueError("节点不存在或无权操作")
    return node


def _owned_edge(user, pk):
    edge = get_owned(PipeEdge.objects.select_related("pipeline", "source", "target"), user, pk)
    if edge is None:
        raise ValueError("连线不存在或无权操作")
    return edge


def _owned_mapping(user, pk):
    mapping = get_owned(Mapping.objects.select_related("pipeline", "node"), user, pk)
    if mapping is None:
        raise ValueError("字段映射不存在或无权操作")
    return mapping


def _owned_variable(user, pk):
    variable = get_owned(PipelineVariable.objects.select_related("pipeline"), user, pk)
    if variable is None:
        raise ValueError("变量不存在或无权操作")
    return variable


def _owned_schedule(user, pk):
    schedule = get_owned(Schedule.objects.select_related("pipeline"), user, pk)
    if schedule is None:
        raise ValueError("调度不存在或无权操作")
    return schedule


def _owned_rule(user, pk):
    rule = get_owned(DataQualityRule.objects.select_related("pipeline"), user, pk)
    if rule is None:
        raise ValueError("质量规则不存在或无权操作")
    return rule


def _owned_webhook(user, pk):
    webhook = get_owned(WebhookTrigger.objects.select_related("pipeline"), user, pk)
    if webhook is None:
        raise ValueError("Webhook 不存在或无权操作")
    return webhook


def _node_for_pipeline(pipeline, value, label: str) -> PipeNode:
    """连线 / 映射引用节点：兼容主键与 node_key 两种写法。"""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label}不能为空")
    node = None
    if raw.isdigit():
        node = pipeline.nodes.filter(pk=int(raw)).first()
    if node is None:
        node = pipeline.nodes.filter(node_key=raw).first()
    if node is None:
        raise ValueError(f"{label} {raw} 不存在")
    return node


def _validate_node_config(node_key: str, node_type: str, config: dict) -> None:
    """节点配置静态校验：错误信息直接作为 400 返回。"""
    errors = validate_node_config(SimpleNamespace(
        node_key=node_key, node_type=node_type, config=config or {}))
    if errors:
        raise ValueError(f"节点 {node_key} 配置错误：{errors[0]['message']}")


def _check_pipeline_name(user, name: str, exclude_id=None) -> None:
    qs = Pipeline.objects.filter(owner=user, name=name)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValueError(f"管道名称 {name} 已存在")


# ---------------------------------------------------------------------------
# 目录
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def catalog(request):
    """目录：枚举、限制、连接器模板、节点面板与全部接口清单。"""
    from pipeline.urls import urlpatterns

    # 首屏顺带补齐内置连接器：用户不需要手动「安装」五种基础类型
    ensure_builtin_connectors(request.user)
    data = {
        "app": "pipeline",
        "name": "数据集成管道",
        "version": "1.0",
        "limits": {
            "max_run_rows": MAX_RUN_ROWS,
            "page_size": 200,
            "max_retries": MAX_RETRIES,
            "max_timeout": MAX_TIMEOUT,
        },
        "connector_kinds": [{"value": k, "label": k} for k in CONNECTOR_KINDS],
        "connector_capabilities": list(CONNECTOR_CAPABILITIES),
        "connection_status": list(CONNECTION_STATUS),
        "credential_kinds": list(CREDENTIAL_KINDS),
        "pipeline_status": list(PIPELINE_STATUS),
        "node_types": list(NODE_TYPES),
        "trigger_types": list(TRIGGER_TYPES),
        "run_status": list(RUN_STATUS),
        "log_levels": list(LOG_LEVELS),
        "quality_rule_types": list(QUALITY_RULE_TYPES),
        "quality_severity": list(QUALITY_SEVERITY),
        "cast_types": list(CAST_TYPES),
        "endpoints": endpoint_index(urlpatterns),
    }
    data["endpoint_count"] = len(data["endpoints"])
    return ok(data)


# ---------------------------------------------------------------------------
# 连接器
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def connectors(request):
    """连接器列表 / 新建自定义连接器。"""
    if request.method == "GET":
        ensure_builtin_connectors(request.user)
        qs = scope_queryset(Connector.objects.all(), request.user)
        qs = apply_search(qs, request, ["name", "description"])
        kind = _optional_text(request, "kind", max_len=20)
        if kind:
            if kind not in CONNECTOR_KINDS:
                raise ValueError(f"不支持的连接器类型：{kind}")
            qs = qs.filter(kind=kind)
        page, size = page_params(request)
        return ok(paginate(qs.order_by("-builtin", "kind", "name", "id"),
                          page, size, connector_dict))
    name = _text(request, "name", max_len=120)
    kind = _optional_text(request, "kind", "http", max_len=20)
    if kind not in CONNECTOR_KINDS:
        raise ValueError(f"不支持的连接器类型：{kind}")
    capabilities = list_param(request, "capabilities", [])
    invalid = [item for item in capabilities if item not in CONNECTOR_CAPABILITIES]
    if invalid:
        raise ValueError(f"不支持的能力标记：{', '.join(map(str, invalid))}")
    if Connector.objects.filter(owner=request.user, name=name).exists():
        raise ValueError(f"连接器名称 {name} 已存在")
    connector = Connector.objects.create(
        owner=request.user, name=name, kind=kind,
        config_template=json_param(request, "config_template", {}),
        capabilities=[str(item) for item in capabilities],
        builtin=False,
        description=_optional_text(request, "description", "", max_len=1000),
        docs_url=_optional_text(request, "docs_url", "", max_len=300),
    )
    return ok(connector_dict(connector))


@endpoint(("GET",))
def connector_templates(request):
    """内置连接器模板：不落库也能展示，便于用户先看再建。"""
    from pipeline.catalog import builtin_templates

    return ok(list_payload(builtin_templates()))


@endpoint()
def connector_update(request, pk):
    """更新自定义连接器：内置模板只允许改说明，防止误改模板结构。"""
    connector = get_owned(Connector.objects.all(), request.user, pk)
    if connector is None:
        raise ValueError("连接器不存在或无权修改")
    data = payload(request)
    if "name" in data:
        name = _text(request, "name", max_len=120)
        if Connector.objects.filter(owner=request.user, name=name) \
                .exclude(pk=connector.pk).exists():
            raise ValueError(f"连接器名称 {name} 已存在")
        connector.name = name
    if "kind" in data:
        if connector.builtin:
            raise ValueError("内置连接器的类型不可修改")
        kind = _optional_text(request, "kind", connector.kind, max_len=20)
        if kind not in CONNECTOR_KINDS:
            raise ValueError(f"不支持的连接器类型：{kind}")
        connector.kind = kind
    if "capabilities" in data:
        capabilities = list_param(request, "capabilities", [])
        invalid = [item for item in capabilities if item not in CONNECTOR_CAPABILITIES]
        if invalid:
            raise ValueError(f"不支持的能力标记：{', '.join(map(str, invalid))}")
        connector.capabilities = [str(item) for item in capabilities]
    if "config_template" in data:
        if connector.builtin:
            raise ValueError("内置连接器的配置模板不可修改")
        connector.config_template = json_param(request, "config_template", {})
    if "description" in data:
        connector.description = _optional_text(request, "description", "", max_len=1000)
    if "docs_url" in data:
        connector.docs_url = _optional_text(request, "docs_url", "", max_len=300)
    connector.save()
    return ok(connector_dict(connector))


@endpoint()
def connector_delete(request, pk):
    """删除自定义连接器：内置连接器与已被连接引用的连接器都拒绝删除。"""
    connector = get_owned(Connector.objects.all(), request.user, pk)
    if connector is None:
        raise ValueError("连接器不存在或无权删除")
    if connector.builtin:
        raise ValueError("内置连接器不允许删除")
    in_use = connector.connections.count()
    if in_use:
        raise ValueError(f"该连接器仍被 {in_use} 个连接使用，无法删除")
    connector.delete()
    return ok({"deleted": 1, "id": pk})


# ---------------------------------------------------------------------------
# 凭据引用
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def credentials(request):
    """凭据引用列表 / 新建；平台只保存名称，不接收也不回显明文。"""
    if request.method == "GET":
        qs = scope_queryset(CredentialRef.objects.all(), request.user)
        qs = apply_search(qs, request, ["name", "description", "provider"])
        kind = _optional_text(request, "kind", max_len=20)
        if kind:
            if kind not in CREDENTIAL_KINDS:
                raise ValueError(f"不支持的凭据类型：{kind}")
            qs = qs.filter(kind=kind)
        page, size = page_params(request)
        return ok(paginate(qs.order_by("name", "id"), page, size, credential_dict))

    name = _text(request, "name", max_len=120)
    kind = _optional_text(request, "kind", "token", max_len=20)
    if kind not in CREDENTIAL_KINDS:
        raise ValueError(f"不支持的凭据类型：{kind}")
    if CredentialRef.objects.filter(owner=request.user, name=name).exists():
        raise ValueError(f"凭据名称 {name} 已存在")
    credential = CredentialRef.objects.create(
        owner=request.user, name=name, kind=kind,
        provider=_optional_text(request, "provider", "", max_len=80),
        description=_optional_text(request, "description", "", max_len=1000),
    )
    data = credential_dict(credential)
    # 即使调用方传了 secret，也只提示「未存储」：从源头保证明文不落库
    if p(request, "secret") not in (None, ""):
        data["secret_notice"] = "平台不保存密钥明文，请通过 KMS / 环境变量托管后仅填写名称"
    return ok(data)


@endpoint()
def credential_update(request, pk):
    """更新凭据引用的元信息（名称 / 类型 / 托管方 / 说明）。"""
    credential = get_owned(CredentialRef.objects.all(), request.user, pk)
    if credential is None:
        raise ValueError("凭据不存在或无权修改")
    data = payload(request)
    if "name" in data:
        name = _text(request, "name", max_len=120)
        if CredentialRef.objects.filter(owner=request.user, name=name) \
                .exclude(pk=credential.pk).exists():
            raise ValueError(f"凭据名称 {name} 已存在")
        if name != credential.name:
            used = Connection.objects.filter(owner=request.user,
                                            secret_ref=credential.name).count()
            if used:
                raise ValueError(f"该凭据仍被 {used} 个连接引用，请先解绑再改名")
        credential.name = name
    if "kind" in data:
        kind = _optional_text(request, "kind", credential.kind, max_len=20)
        if kind not in CREDENTIAL_KINDS:
            raise ValueError(f"不支持的凭据类型：{kind}")
        credential.kind = kind
    if "provider" in data:
        credential.provider = _optional_text(request, "provider", "", max_len=80)
    if "description" in data:
        credential.description = _optional_text(request, "description", "", max_len=1000)
    credential.save()
    return ok(credential_dict(credential))


@endpoint()
def credential_delete(request, pk):
    """删除凭据引用：仍被连接引用时拒绝，避免连接突然失去密钥来源。"""
    credential = get_owned(CredentialRef.objects.all(), request.user, pk)
    if credential is None:
        raise ValueError("凭据不存在或无权删除")
    used = Connection.objects.filter(owner=request.user, secret_ref=credential.name).count()
    if used:
        raise ValueError(f"该凭据仍被 {used} 个连接引用，无法删除")
    credential.delete()
    return ok({"deleted": 1, "id": pk})


@endpoint()
def credential_rotate(request, pk):
    """标记凭据已轮换：只更新时间，不接收也不保存新密钥。"""
    credential = get_owned(CredentialRef.objects.all(), request.user, pk)
    if credential is None:
        raise ValueError("凭据不存在或无权修改")
    credential.last_rotated_at = timezone.now()
    provider = _optional_text(request, "provider", credential.provider, max_len=80)
    credential.provider = provider
    credential.save(update_fields=["last_rotated_at", "provider", "updated_at"])
    data = credential_dict(credential)
    data["secret_notice"] = "请在托管方完成密钥轮换；平台仅记录轮换时间"
    return ok(data)


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def connections(request):
    """连接列表 / 新建连接（配置写前校验，密钥只存引用名）。"""
    if request.method == "GET":
        qs = scope_queryset(Connection.objects.select_related("connector"), request.user)
        qs = apply_search(qs, request, ["name", "description"])
        qs = apply_status(qs, request, "status", CONNECTION_STATUS)
        connector_id = int_param(request, "connector_id", 0, minimum=0)
        if connector_id:
            qs = qs.filter(connector_id=connector_id)
        kind = _optional_text(request, "kind", max_len=20)
        if kind:
            if kind not in CONNECTOR_KINDS:
                raise ValueError(f"不支持的连接器类型：{kind}")
            qs = qs.filter(connector__kind=kind)
        page, size = page_params(request)
        return ok(paginate(qs.order_by("-updated_at", "-id"), page, size,
                          connection_dict))

    connector = get_owned(Connector.objects.all(), request.user,
                          int_param(request, "connector_id", None, minimum=1))
    if connector is None:
        raise ValueError("连接器不存在或无权使用")
    name = _text(request, "name", max_len=120)
    if Connection.objects.filter(owner=request.user, name=name).exists():
        raise ValueError(f"连接名称 {name} 已存在")
    config = json_param(request, "config", {})
    from pipeline.generators import validate_connection_config

    config = validate_connection_config(connector.kind, config)
    secret_ref = services.validate_secret_ref(
        request.user, _optional_text(request, "secret_ref", "", max_len=120))
    connection = Connection.objects.create(
        owner=request.user, name=name, connector=connector, config=config,
        secret_ref=secret_ref, status="active",
        description=_optional_text(request, "description", "", max_len=1000),
    )
    return ok(connection_dict(connection))


@endpoint(("GET",))
def connection_detail(request, pk):
    """连接详情：配置脱敏后返回，绝不回显密钥值。"""
    connection = services.resolve_connection(request.user, pk)
    return ok(connection_dict(connection))


@endpoint()
def connection_update(request, pk):
    """更新连接：名称唯一、配置重新校验、密钥引用名必须存在。"""
    connection = services.resolve_connection(request.user, pk, write=True)
    data = payload(request)
    if "name" in data:
        name = _text(request, "name", max_len=120)
        if Connection.objects.filter(owner=request.user, name=name) \
                .exclude(pk=connection.pk).exists():
            raise ValueError(f"连接名称 {name} 已存在")
        connection.name = name
    if "connector_id" in data:
        connector = get_owned(Connector.objects.all(), request.user,
                              int_param(request, "connector_id", None, minimum=1))
        if connector is None:
            raise ValueError("连接器不存在或无权使用")
        connection.connector = connector
    if "config" in data:
        from pipeline.generators import validate_connection_config

        connection.config = validate_connection_config(
            connection.connector.kind, json_param(request, "config", {}))
    elif "connector_id" in data:
        # 只换连接器不给新配置时，也要保证旧配置对新类型仍然合法
        from pipeline.generators import validate_connection_config

        connection.config = validate_connection_config(
            connection.connector.kind, connection.config or {})
    if "secret_ref" in data:
        connection.secret_ref = services.validate_secret_ref(
            request.user, _optional_text(request, "secret_ref", "", max_len=120))
    if "description" in data:
        connection.description = _optional_text(request, "description", "", max_len=1000)
    if "status" in data:
        status = _optional_text(request, "status", connection.status, max_len=20)
        if status not in CONNECTION_STATUS:
            raise ValueError(f"不支持的连接状态：{status}")
        connection.status = status
    connection.save()
    return ok(connection_dict(connection))


@endpoint()
def connection_delete(request, pk):
    """删除连接：连接是配置对象，删除不级联任何管道。"""
    connection = services.resolve_connection(request.user, pk, write=True)
    connection.delete()
    return ok({"deleted": 1, "id": pk})


@endpoint()
def connection_test(request, pk):
    """测试连接：只做配置校验与样例模拟，不发起真实网络 / SQL。"""
    connection = services.resolve_connection(request.user, pk, write=True)
    try:
        result = test_connection(connection)
    except ValueError as exc:
        # 失败也要落状态，列表页才能一眼看出坏连接
        mark_connection_error(connection, str(exc))
        raise ValueError(f"连接测试失败：{exc}")
    return ok(result)


@endpoint()
def connection_toggle(request, pk):
    """启用 / 停用连接：异常状态恢复为可用，可用状态转为停用。"""
    connection = services.resolve_connection(request.user, pk, write=True)
    connection.status = "disabled" if connection.status == "active" else "active"
    connection.save(update_fields=["status", "updated_at"])
    return ok(connection_dict(connection))


# ---------------------------------------------------------------------------
# 管道
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def pipelines(request):
    """管道列表 / 新建管道。"""
    if request.method == "GET":
        qs = scope_queryset(Pipeline.objects.all(), request.user)
        qs = apply_search(qs, request, ["code", "name", "description", "assignee"])
        qs = apply_status(qs, request, "status", PIPELINE_STATUS)
        assignee = _optional_text(request, "assignee", max_len=80)
        if assignee:
            qs = qs.filter(assignee=assignee)
        with_counts = bool_param(request, "with_counts", False)
        page, size = page_params(request)
        return ok(paginate(qs.order_by("-updated_at", "-id"), page, size,
                          lambda obj: pipeline_dict(obj, with_counts=with_counts)))

    code = services.clean_code(_text(request, "code", max_len=80))
    name = _text(request, "name", max_len=200)
    if Pipeline.objects.filter(owner=request.user, code=code).exists():
        raise ValueError(f"管道编码 {code} 已存在")
    _check_pipeline_name(request.user, name)
    concurrency = _optional_text(request, "concurrency", "skip", max_len=20)
    if concurrency not in ("skip", "serial", "allow"):
        raise ValueError(f"不支持的并发策略：{concurrency}")
    tags = list_param(request, "tags", [], max_items=20)
    pipeline = Pipeline.objects.create(
        owner=request.user, code=code, name=name,
        description=_optional_text(request, "description", "", max_len=200000),
        concurrency=concurrency,
        max_retries=int_param(request, "max_retries", 1, minimum=0, maximum=MAX_RETRIES),
        timeout_seconds=int_param(request, "timeout_seconds", 120, minimum=5,
                                  maximum=MAX_TIMEOUT),
        assignee=_optional_text(request, "assignee", "", max_len=80),
        tags=[str(item)[:40] for item in tags],
        watermark_field=_optional_text(request, "watermark_field", "", max_len=80),
        watermark_value=_optional_text(request, "watermark_value", "", max_len=200),
        row_limit=int_param(request, "row_limit", MAX_RUN_ROWS, minimum=1,
                            maximum=MAX_RUN_ROWS),
    )
    return ok(pipeline_dict(pipeline, with_counts=True))


@endpoint()
def pipeline_import(request):
    """导入管道 JSON：事务内创建管道、节点、连线、映射、规则与调度。"""
    document = json_param(request, "document", None)
    if document is None:
        # 兼容直接以整个请求体作为导出文档的调用方式
        document = payload(request)
        if "pipeline" not in document:
            raise ValueError("缺少必填参数: document")
    code = _optional_text(request, "code", "", max_len=80)
    if code:
        code = services.clean_code(code)
    result = services.import_pipeline(request.user, document, code_override=code)
    pipeline = Pipeline.objects.get(pk=result["pipeline_id"])
    result["pipeline"] = pipeline_dict(pipeline, with_counts=True)
    return ok(result)


@endpoint(("GET",))
def pipeline_detail(request, pk):
    """管道详情：元信息 + 节点 + 连线 + 映射 + 变量，一次拉全画布。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    data = pipeline_dag_payload(pipeline)
    data["orphans"] = validate_dag(pipeline)["warnings"]
    return ok(data)


@endpoint()
def pipeline_update(request, pk):
    """更新管道元信息；状态变更必须走发布 / 暂停 / 归档接口。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    data = payload(request)
    if "status" in data:
        raise ValueError("请通过发布 / 暂停 / 归档接口变更管道状态")
    if "code" in data:
        code = services.clean_code(_text(request, "code", max_len=80))
        if Pipeline.objects.filter(owner=request.user, code=code) \
                .exclude(pk=pipeline.pk).exists():
            raise ValueError(f"管道编码 {code} 已存在")
        pipeline.code = code
    if "name" in data:
        name = _text(request, "name", max_len=200)
        _check_pipeline_name(request.user, name, exclude_id=pipeline.pk)
        pipeline.name = name
    if "description" in data:
        pipeline.description = _optional_text(request, "description", "", max_len=200000)
    if "concurrency" in data:
        concurrency = _optional_text(request, "concurrency", "skip", max_len=20)
        if concurrency not in ("skip", "serial", "allow"):
            raise ValueError(f"不支持的并发策略：{concurrency}")
        pipeline.concurrency = concurrency
    if "max_retries" in data:
        pipeline.max_retries = int_param(request, "max_retries", pipeline.max_retries,
                                         minimum=0, maximum=MAX_RETRIES)
    if "timeout_seconds" in data:
        pipeline.timeout_seconds = int_param(request, "timeout_seconds",
                                            pipeline.timeout_seconds, minimum=5,
                                            maximum=MAX_TIMEOUT)
    if "assignee" in data:
        pipeline.assignee = _optional_text(request, "assignee", "", max_len=80)
    if "tags" in data:
        pipeline.tags = [str(item)[:40] for item in
                         list_param(request, "tags", [], max_items=20)]
    if "watermark_field" in data:
        pipeline.watermark_field = _optional_text(request, "watermark_field", "",
                                                  max_len=80)
    if "watermark_value" in data:
        pipeline.watermark_value = _optional_text(request, "watermark_value", "",
                                                  max_len=200)
    if "row_limit" in data:
        pipeline.row_limit = int_param(request, "row_limit", pipeline.row_limit,
                                       minimum=1, maximum=MAX_RUN_ROWS)
    pipeline.save()
    return ok(pipeline_dict(pipeline, with_counts=True))


@endpoint()
def pipeline_delete(request, pk):
    """删除管道：有运行中的任务时拒绝，避免删掉正在写入的目标。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    if pipeline.runs.filter(status__in=("queued", "running")).exists():
        raise ValueError("管道有正在进行的运行，请先取消后再删除")
    counts = {
        "nodes": pipeline.nodes.count(),
        "edges": pipeline.edges.count(),
        "runs": pipeline.runs.count(),
        "outputs": pipeline.outputs.count(),
    }
    pipeline.delete()
    return ok({"deleted": 1, "id": pk, "cascade": counts})


@endpoint()
def pipeline_clone(request, pk):
    """克隆管道：复制结构 / 规则 / 调度，不复制运行与输出。"""
    source = services.resolve_pipeline(request.user, pk)
    code = _optional_text(request, "code", "", max_len=80)
    if code:
        code = services.clean_code(code)
    pipeline = services.clone_pipeline(source, request.user, code=code)
    return ok(pipeline_dict(pipeline, with_counts=True))


@endpoint()
def pipeline_publish(request, pk):
    """发布管道：DAG 校验通过后生成版本快照并切换为可用。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    note = _optional_text(request, "note", "", max_len=300)
    return ok(services.publish_pipeline(pipeline, note=note))


@endpoint()
def pipeline_pause(request, pk):
    """暂停管道：暂停后手动 / 调度触发都会被拒绝。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    if pipeline.status == "archived":
        raise ValueError("已归档管道不能暂停")
    pipeline.status = "paused"
    pipeline.save(update_fields=["status", "updated_at"])
    return ok(pipeline_dict(pipeline, with_counts=True))


@endpoint()
def pipeline_archive(request, pk):
    """归档管道：同时停用其全部调度，避免归档后仍被定时触发。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    with transaction.atomic():
        pipeline.status = "archived"
        pipeline.save(update_fields=["status", "updated_at"])
        stopped = pipeline.schedules.filter(enabled=True).update(
            enabled=False, next_run_at=None, updated_at=timezone.now())
    return ok({"pipeline": pipeline_dict(pipeline, with_counts=True),
               "stopped_schedules": stopped})


@endpoint(("GET", "POST"))
def pipeline_validate(request, pk):
    """校验 DAG：端口、唯一源汇、环、孤立节点与执行顺序。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    report = validate_dag(pipeline)
    from pipeline.dag import find_orphan_nodes

    report["orphans"] = find_orphan_nodes(pipeline)
    return ok(report)


@endpoint(("GET",))
def pipeline_topology(request, pk):
    """拓扑预览：按层返回可执行顺序与每层节点。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    return ok(topology_preview(pipeline))


@endpoint(("GET",))
def pipeline_export(request, pk):
    """导出管道 JSON：不含主键与运行数据，可跨环境迁移。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    include_schedules = bool_param(request, "include_schedules", True)
    return ok(services.export_pipeline(pipeline, include_schedules=include_schedules))


@endpoint(("GET",))
def pipeline_versions(request, pk):
    """版本列表：按版本号倒序，分页返回。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    page, size = page_params(request)
    qs = pipeline.versions.order_by("-version", "-id")
    return ok(paginate(qs, page, size, _version_dict))


@endpoint()
def pipeline_rollback(request, pk, vid):
    """回滚到指定版本：整体替换 DAG，历史运行记录保留。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    version = pipeline.versions.filter(pk=vid).first()
    if version is None:
        raise ValueError("版本不存在")
    result = services.rollback_version(pipeline, version)
    result["pipeline"] = pipeline_dict(pipeline, with_counts=True)
    return ok(result)


@endpoint(("GET",))
def pipeline_stats(request, pk):
    """单管道统计：运行趋势、成功率、耗时与质量概览。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    days = int_param(request, "days", 30, minimum=1, maximum=365)
    return ok(stats.pipeline_stats(pipeline, days))


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def pipeline_nodes(request, pk):
    """节点列表 / 新建节点。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    if request.method == "GET":
        qs = pipeline.nodes.all()
        qs = apply_search(qs, request, ["node_key", "name", "description"])
        node_type = _optional_text(request, "node_type", max_len=20)
        if node_type:
            if node_type not in NODE_TYPES:
                raise ValueError(f"不支持的节点类型：{node_type}")
            qs = qs.filter(node_type=node_type)
        page, size = page_params(request)
        return ok(paginate(qs.order_by("order", "id"), page, size, node_dict))

    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    node_key = _text(request, "node_key", max_len=80)
    if not IDENT_RE.fullmatch(node_key):
        raise ValueError("节点标识只能包含字母、数字、下划线、点和短横线")
    if pipeline.nodes.filter(node_key=node_key).exists():
        raise ValueError(f"节点标识 {node_key} 已存在")
    node_type = _optional_text(request, "node_type", "transform", max_len=20)
    if node_type not in NODE_TYPES:
        raise ValueError(f"不支持的节点类型：{node_type}")
    config = json_param(request, "config", {})
    _validate_node_config(node_key, node_type, config)
    node = PipeNode.objects.create(
        owner=request.user, pipeline=pipeline, node_key=node_key,
        name=_optional_text(request, "name", node_key, max_len=120) or node_key,
        node_type=node_type, config=config,
        order=int_param(request, "order", pipeline.nodes.count(), minimum=0),
        position_x=float(opt_num(request, "position_x", 0) or 0),
        position_y=float(opt_num(request, "position_y", 0) or 0),
        enabled=bool_param(request, "enabled", True),
        description=_optional_text(request, "description", "", max_len=1000),
    )
    return ok(node_dict(node))


@endpoint()
def pipeline_nodes_reorder(request, pk):
    """节点重排：一次提交顺序数组，事务内批量更新。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    items = list_param(request, "items", [])
    if not items:
        raise ValueError("items 不能为空")
    nodes = {n.node_key: n for n in pipeline.nodes.all()}
    updated = []
    with transaction.atomic():
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index + 1} 项不是对象")
            key = str(item.get("node_key") or item.get("id") or "").strip()
            node = nodes.get(key)
            if node is None and key.isdigit():
                node = nodes.get(next((n.node_key for n in nodes.values()
                                       if n.id == int(key)), ""))
            if node is None:
                raise ValueError(f"节点 {key} 不存在")
            node.order = int(item.get("order", index) or 0)
            node.save(update_fields=["order", "updated_at"])
            updated.append(node.node_key)
    return ok({"updated": updated, "count": len(updated)})


@endpoint()
def pipeline_nodes_bulk(request, pk):
    """批量保存节点：按 node_key upsert，可选删除未提交的节点。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    items = list_param(request, "items", [])
    replace = bool_param(request, "replace", False)
    result = services.bulk_save_nodes(pipeline, items, replace=replace)
    return ok({"items": [node_dict(node) for node in result["items"]],
               "saved": result["saved"], "removed": result["removed"],
               "validation": result["validation"]})


@endpoint()
def node_update(request, pk):
    """更新节点：标识可改，但改后仍需全局唯一。"""
    node = _owned_node(request.user, pk)
    data = payload(request)
    new_key = node.node_key
    if "node_key" in data:
        new_key = _text(request, "node_key", max_len=80)
        if not IDENT_RE.fullmatch(new_key):
            raise ValueError("节点标识只能包含字母、数字、下划线、点和短横线")
        if node.pipeline.nodes.filter(node_key=new_key).exclude(pk=node.pk).exists():
            raise ValueError(f"节点标识 {new_key} 已存在")
    node_type = node.node_type
    if "node_type" in data:
        node_type = _optional_text(request, "node_type", node.node_type, max_len=20)
        if node_type not in NODE_TYPES:
            raise ValueError(f"不支持的节点类型：{node_type}")
    config = node.config or {}
    if "config" in data:
        config = json_param(request, "config", {})
    _validate_node_config(new_key, node_type, config)
    node.node_key = new_key
    node.node_type = node_type
    node.config = config
    if "name" in data:
        node.name = _optional_text(request, "name", node.name, max_len=120) or new_key
    if "order" in data:
        node.order = int_param(request, "order", node.order, minimum=0)
    if "position_x" in data:
        node.position_x = float(opt_num(request, "position_x", node.position_x) or 0)
    if "position_y" in data:
        node.position_y = float(opt_num(request, "position_y", node.position_y) or 0)
    if "enabled" in data:
        node.enabled = bool_param(request, "enabled", node.enabled)
    if "description" in data:
        node.description = _optional_text(request, "description", "", max_len=1000)
    node.save()
    return ok(node_dict(node))


@endpoint()
def node_delete(request, pk):
    """删除节点：级联删除其连线，返回被清理的连线数量。"""
    node = _owned_node(request.user, pk)
    edge_count = node.in_edges.count() + node.out_edges.count()
    with transaction.atomic():
        node.delete()
    return ok({"deleted": 1, "id": pk, "removed_edges": edge_count})


# ---------------------------------------------------------------------------
# 连线
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def pipeline_edges(request, pk):
    """连线列表 / 新建连线（校验端口与自连）。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    if request.method == "GET":
        qs = pipeline.edges.select_related("source", "target").all()
        page, size = page_params(request)
        return ok(paginate(qs.order_by("order", "id"), page, size, edge_dict))

    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    source = _node_for_pipeline(pipeline, p(request, "source", p(request, "source_id")),
                                "上游节点")
    target = _node_for_pipeline(pipeline, p(request, "target", p(request, "target_id")),
                                "下游节点")
    if source.pk == target.pk:
        raise ValueError("节点不能连到自己")
    source_port = _optional_text(request, "source_port", "out", max_len=30)
    target_port = _optional_text(request, "target_port", "in", max_len=30)
    if pipeline.edges.filter(source=source, target=target, source_port=source_port,
                             target_port=target_port).exists():
        raise ValueError(f"重复连线：{source.node_key} → {target.node_key}")
    edge = PipeEdge.objects.create(
        owner=request.user, pipeline=pipeline, source=source, target=target,
        source_port=source_port, target_port=target_port,
        order=int_param(request, "order", pipeline.edges.count(), minimum=0),
    )
    report = validate_dag(pipeline)
    return ok({"edge": edge_dict(edge), "validation": {
        "valid": report["valid"], "errors": report["errors"],
        "warnings": report["warnings"]}})


@endpoint()
def pipeline_edges_bulk(request, pk):
    """批量保存连线：默认整体替换，避免画布删除后残留旧边。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    items = list_param(request, "items", [])
    replace = bool_param(request, "replace", True)
    result = services.bulk_save_edges(pipeline, items, replace=replace)
    return ok({"items": [edge_dict(edge) for edge in result["items"]],
               "saved": result["saved"], "validation": result["validation"]})


@endpoint()
def edge_delete(request, pk):
    """删除连线。"""
    edge = _owned_edge(request.user, pk)
    edge.delete()
    return ok({"deleted": 1, "id": pk})


# ---------------------------------------------------------------------------
# 字段映射
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def pipeline_mappings(request, pk):
    """字段映射列表 / 新建映射。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    if request.method == "GET":
        qs = pipeline.mappings.select_related("node").all()
        node_key = _optional_text(request, "node_key", max_len=80)
        if node_key:
            qs = qs.filter(node__node_key=node_key)
        page, size = page_params(request)
        return ok(paginate(qs.order_by("order", "id"), page, size, mapping_dict))

    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    mapping = services.save_mapping(pipeline, payload(request))
    return ok(mapping_dict(mapping))


@endpoint()
def mapping_update(request, pk):
    """更新字段映射：表达式与类型转换都会重新校验。"""
    mapping = _owned_mapping(request.user, pk)
    updated = services.save_mapping(mapping.pipeline, payload(request), mapping)
    return ok(mapping_dict(updated))


@endpoint()
def mapping_delete(request, pk):
    """删除字段映射。"""
    mapping = _owned_mapping(request.user, pk)
    mapping.delete()
    return ok({"deleted": 1, "id": pk})


# ---------------------------------------------------------------------------
# 管道变量
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def pipeline_variables(request, pk):
    """变量列表 / 新建变量（管道内名称唯一）。"""
    pipeline = services.resolve_pipeline(request.user, pk)
    if request.method == "GET":
        page, size = page_params(request)
        qs = pipeline.variables.order_by("name", "id")
        return ok(paginate(qs, page, size, variable_dict))

    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    name = _text(request, "name", max_len=80)
    if not VARIABLE_RE.fullmatch(name):
        raise ValueError("变量名必须以字母或下划线开头，只含字母、数字、下划线")
    if pipeline.variables.filter(name=name).exists():
        raise ValueError(f"变量 {name} 已存在")
    kind = _optional_text(request, "kind", "string", max_len=20)
    if kind not in VARIABLE_KINDS:
        raise ValueError(f"不支持的变量类型：{kind}")
    variable = PipelineVariable.objects.create(
        owner=request.user, pipeline=pipeline, name=name,
        value=p(request, "value", None),
        kind=kind,
        description=_optional_text(request, "description", "", max_len=300),
    )
    return ok(variable_dict(variable))


@endpoint()
def variable_update(request, pk):
    """更新管道变量。"""
    variable = _owned_variable(request.user, pk)
    data = payload(request)
    if "name" in data:
        name = _text(request, "name", max_len=80)
        if not VARIABLE_RE.fullmatch(name):
            raise ValueError("变量名必须以字母或下划线开头，只含字母、数字、下划线")
        if variable.pipeline.variables.filter(name=name).exclude(pk=variable.pk).exists():
            raise ValueError(f"变量 {name} 已存在")
        variable.name = name
    if "value" in data:
        variable.value = p(request, "value", None)
    if "kind" in data:
        kind = _optional_text(request, "kind", variable.kind, max_len=20)
        if kind not in VARIABLE_KINDS:
            raise ValueError(f"不支持的变量类型：{kind}")
        variable.kind = kind
    if "description" in data:
        variable.description = _optional_text(request, "description", "", max_len=300)
    variable.save()
    return ok(variable_dict(variable))


@endpoint()
def variable_delete(request, pk):
    """删除管道变量。"""
    variable = _owned_variable(request.user, pk)
    variable.delete()
    return ok({"deleted": 1, "id": pk})


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def schedules(request):
    """调度列表 / 新建调度（cron 表达式保存前规范化）。"""
    if request.method == "GET":
        qs = scope_queryset(Schedule.objects.select_related("pipeline"), request.user)
        qs = apply_search(qs, request, ["name", "cron", "pipeline__name", "pipeline__code"])
        pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        raw_enabled = request.query_params.get("enabled")
        if raw_enabled not in (None, ""):
            qs = qs.filter(enabled=bool_param(request, "enabled", True))
        page, size = page_params(request)
        return ok(paginate(qs.order_by("next_run_at", "id"), page, size, schedule_dict))

    pipeline = services.resolve_pipeline(
        request.user, int_param(request, "pipeline_id", None, minimum=1), write=True)
    name = _text(request, "name", max_len=120)
    if pipeline.schedules.filter(name=name).exists():
        raise ValueError(f"调度名称 {name} 已存在")
    cron = normalize_cron(_text(request, "cron", max_len=120))
    timezone_name = _optional_text(request, "timezone", "Asia/Shanghai", max_len=64)
    schedule = Schedule(
        owner=request.user, pipeline=pipeline, name=name, cron=cron,
        timezone=timezone_name, enabled=bool_param(request, "enabled", True),
        catchup=bool_param(request, "catchup", False),
    )
    compute_schedule_next_run(schedule)
    schedule.save()
    return ok(schedule_dict(schedule))


@endpoint()
def schedule_update(request, pk):
    """更新调度：cron / 时区变化后立即重算下次运行时间。"""
    schedule = _owned_schedule(request.user, pk)
    data = payload(request)
    if "name" in data:
        name = _text(request, "name", max_len=120)
        if schedule.pipeline.schedules.filter(name=name).exclude(pk=schedule.pk).exists():
            raise ValueError(f"调度名称 {name} 已存在")
        schedule.name = name
    if "cron" in data:
        schedule.cron = normalize_cron(_text(request, "cron", max_len=120))
    if "timezone" in data:
        schedule.timezone = _optional_text(request, "timezone", schedule.timezone, max_len=64)
    if "enabled" in data:
        schedule.enabled = bool_param(request, "enabled", schedule.enabled)
    if "catchup" in data:
        schedule.catchup = bool_param(request, "catchup", schedule.catchup)
    compute_schedule_next_run(schedule)
    schedule.save()
    return ok(schedule_dict(schedule))


@endpoint()
def schedule_delete(request, pk):
    """删除调度。"""
    schedule = _owned_schedule(request.user, pk)
    schedule.delete()
    return ok({"deleted": 1, "id": pk})


@endpoint()
def schedule_toggle(request, pk):
    """启用 / 停用调度：停用时清空下次运行时间。"""
    schedule = _owned_schedule(request.user, pk)
    schedule.enabled = not schedule.enabled
    compute_schedule_next_run(schedule)
    schedule.save(update_fields=["enabled", "next_run_at", "updated_at"])
    return ok(schedule_dict(schedule))


@endpoint(("GET",))
def schedule_next_run(request, pk):
    """调度下次运行预览：连续计算未来 N 次触发时间。"""
    schedule = _owned_schedule(request.user, pk)
    count = int_param(request, "count", 3, minimum=1, maximum=20)
    moments = next_run_times(schedule.cron, count, None, schedule.timezone)
    return ok({
        "schedule_id": schedule.id,
        "pipeline_id": schedule.pipeline_id,
        "cron": schedule.cron,
        "timezone": schedule.timezone,
        "description": describe_cron(schedule.cron),
        "next_runs": [moment.isoformat() for moment in moments],
    })


@endpoint()
def schedules_scan(request):
    """扫描到期调度并同步执行：单条失败不影响其余调度。"""
    limit = int_param(request, "limit", 10, minimum=1, maximum=50)
    # 扫描会真实触发运行（写操作），因此只允许本人调度，不能按读范围放开
    due = due_schedules().select_related("pipeline").filter(owner=request.user)[:limit]
    items = []
    for schedule in due:
        entry = {"schedule_id": schedule.id, "name": schedule.name,
                 "pipeline_id": schedule.pipeline_id,
                 "pipeline_code": schedule.pipeline.code}
        try:
            run = services.run_now(schedule.pipeline, request.user, trigger="schedule")
            with transaction.atomic():
                mark_schedule_run(schedule, run)
            entry.update({"status": run.status, "run_id": run.id,
                          "output_rows": run.output_rows})
        except ValueError as exc:
            # 单条调度失败（暂停 / 并发 / 校验）只记录结果，避免整批中断
            with transaction.atomic():
                mark_schedule_run(schedule, None, status="failed")
            entry.update({"status": "failed", "error": str(exc)})
        items.append(entry)
    return ok(list_payload(items, count=len(items), size=max(len(items), 1)))


# ---------------------------------------------------------------------------
# 运行
# ---------------------------------------------------------------------------


@endpoint()
def pipeline_run(request, pk):
    """手动 / 接口触发一次同步运行，返回运行记录与步骤。"""
    pipeline = services.resolve_pipeline(request.user, pk, write=True)
    trigger = _optional_text(request, "trigger", "manual", max_len=20)
    if trigger not in ("manual", "api"):
        raise ValueError(f"触发方式只支持 manual / api，当前 {trigger}")
    rows = None
    if p(request, "rows") is not None:
        # 多放一行进来，让「超过 5000 行」由运行护栏给出明确中文提示
        rows = list_param(request, "rows", [], max_items=MAX_RUN_ROWS + 1)
        limit = min(pipeline.row_limit or MAX_RUN_ROWS, MAX_RUN_ROWS)
        if len(rows) > limit:
            raise ValueError(f"单次运行行数上限 {limit}，当前 {len(rows)} 行")
        if any(not isinstance(item, dict) for item in rows):
            raise ValueError("rows 必须是对象数组")
    run = services.run_now(pipeline, request.user, trigger=trigger, rows=rows)
    steps = [step_dict(step) for step in run.steps.order_by("seq", "id")]
    return ok({"run": run_dict(run), "steps": steps,
               "quality_results": run.quality_results.count()})


@endpoint(("GET",))
def runs(request):
    """运行列表：按管道 / 状态 / 触发方式筛选。"""
    qs = scope_queryset(
        PipelineRun.objects.select_related("pipeline", "actor"), request.user)
    qs = apply_search(qs, request, ["pipeline__code", "pipeline__name", "error"])
    qs = apply_status(qs, request, "status", RUN_STATUS)
    trigger = _optional_text(request, "trigger", max_len=20)
    if trigger:
        if trigger not in TRIGGER_TYPES:
            raise ValueError(f"不支持的触发方式：{trigger}")
        qs = qs.filter(trigger=trigger)
    pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
    if pipeline_id:
        qs = qs.filter(pipeline_id=pipeline_id)
    page, size = page_params(request)
    return ok(paginate(qs.order_by("-started_at", "-id"), page, size, run_dict))


@endpoint(("GET",))
def run_detail(request, pk):
    """运行详情：状态、行数、水位、步骤计数与质量结果计数。"""
    run = _scope_run(request.user, pk)
    data = run_dict(run)
    data["step_count"] = run.steps.count()
    data["failed_step_count"] = run.steps.filter(status="failed").count()
    data["quality"] = {
        "total": run.quality_results.count(),
        "failed": run.quality_results.filter(passed=False).count(),
    }
    data["output_count"] = run.outputs.count()
    data["logs_count"] = run.logs.count()
    return ok(data)


@endpoint(("GET",))
def run_steps(request, pk):
    """运行步骤：按执行序号返回每个节点的尝试记录。"""
    run = _scope_run(request.user, pk)
    qs = run.steps.all()
    qs = apply_status(qs, request, "status", STEP_STATUS)
    page, size = page_params(request)
    return ok(paginate(qs.order_by("seq", "attempt", "id"), page, size, step_dict))


@endpoint(("GET",))
def run_logs(request, pk):
    """运行日志：可按级别与关键字过滤。"""
    run = _scope_run(request.user, pk)
    qs = run.logs.all()
    qs = apply_search(qs, request, ["message", "node_key"])
    need = _optional_text(request, "level", max_len=10)
    if need:
        if need not in LOG_LEVELS:
            raise ValueError(f"不支持的日志级别：{need}")
        qs = qs.filter(level=need)
    page, size = page_params(request)
    return ok(paginate(qs.order_by("logged_at", "id"), page, size, log_dict))


@endpoint()
def run_cancel(request, pk):
    """取消运行：仅排队 / 运行中的任务可取消。"""
    run = _owned_run(request.user, pk)
    return ok(run_dict(cancel_run(run, actor=request.user)))


@endpoint()
def run_retry_failed(request, pk):
    """重跑失败节点：从第一个失败节点重算整条链路。"""
    run = _owned_run(request.user, pk)
    new_run = rerun_failed(run, actor=request.user)
    return ok({"source_run_id": run.id, "run": run_dict(new_run),
               "steps": [step_dict(step) for step in new_run.steps.order_by("seq", "id")]})


@endpoint(("GET",))
def runs_compare(request):
    """运行对比：同管道两次运行的状态、行数、耗时与节点差异。"""
    run_a = _scope_run(request.user, int_param(request, "run_a", None, minimum=1))
    run_b = _scope_run(request.user, int_param(request, "run_b", None, minimum=1))
    return ok(compare_runs(run_a, run_b))


@endpoint(("GET",))
def outputs(request):
    """落地数据预览：按管道 / 运行 / 数据集分页查看。"""
    qs = scope_queryset(
        PipelineOutput.objects.select_related("pipeline"), request.user)
    pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
    if pipeline_id:
        qs = qs.filter(pipeline_id=pipeline_id)
    run_id = int_param(request, "run_id", 0, minimum=0)
    if run_id:
        qs = qs.filter(run_id=run_id)
    dataset = _optional_text(request, "dataset", "", max_len=120)
    if dataset:
        qs = qs.filter(dataset=dataset)
    page, size = page_params(request)
    return ok(paginate(qs.order_by("run_id", "seq", "id"), page, size, output_dict))


# ---------------------------------------------------------------------------
# 数据质量
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def quality_rules(request):
    """质量规则列表 / 新建规则（保存前做静态校验）。"""
    if request.method == "GET":
        qs = scope_queryset(DataQualityRule.objects.select_related("pipeline"),
                            request.user)
        qs = apply_search(qs, request, ["name", "field", "description"])
        pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        rule_type = _optional_text(request, "rule_type", max_len=20)
        if rule_type:
            if rule_type not in QUALITY_RULE_TYPES:
                raise ValueError(f"不支持的质量规则类型：{rule_type}")
            qs = qs.filter(rule_type=rule_type)
        severity = _optional_text(request, "severity", max_len=10)
        if severity:
            if severity not in QUALITY_SEVERITY:
                raise ValueError(f"不支持的严重度：{severity}")
            qs = qs.filter(severity=severity)
        raw_enabled = request.query_params.get("enabled")
        if raw_enabled not in (None, ""):
            qs = qs.filter(enabled=bool_param(request, "enabled", True))
        page, size = page_params(request)
        return ok(paginate(qs.order_by("id"), page, size, quality_rule_dict))

    pipeline = services.resolve_pipeline(
        request.user, int_param(request, "pipeline_id", None, minimum=1), write=True)
    name = _text(request, "name", max_len=120)
    if pipeline.quality_rules.filter(name=name).exists():
        raise ValueError(f"质量规则 {name} 已存在")
    draft = SimpleNamespace(
        rule_type=_optional_text(request, "rule_type", "not_null", max_len=20),
        field=_optional_text(request, "field", "", max_len=120),
        params=json_param(request, "params", {}),
        severity=_optional_text(request, "severity", "warning", max_len=10),
    )
    validate_rule(draft)
    rule = DataQualityRule.objects.create(
        owner=request.user, pipeline=pipeline, name=name,
        rule_type=draft.rule_type, field=draft.field, params=draft.params,
        severity=draft.severity, enabled=bool_param(request, "enabled", True),
        description=_optional_text(request, "description", "", max_len=300),
    )
    return ok(quality_rule_dict(rule))


@endpoint()
def quality_rule_update(request, pk):
    """更新质量规则：类型 / 字段 / 参数合并后重新校验。"""
    rule = _owned_rule(request.user, pk)
    data = payload(request)
    if "name" in data:
        name = _text(request, "name", max_len=120)
        if rule.pipeline.quality_rules.filter(name=name).exclude(pk=rule.pk).exists():
            raise ValueError(f"质量规则 {name} 已存在")
        rule.name = name
    draft = SimpleNamespace(
        rule_type=_optional_text(request, "rule_type", rule.rule_type, max_len=20),
        field=_optional_text(request, "field", rule.field, max_len=120),
        params=json_param(request, "params", rule.params or {}),
        severity=_optional_text(request, "severity", rule.severity, max_len=10),
    )
    validate_rule(draft)
    rule.rule_type = draft.rule_type
    rule.field = draft.field
    rule.params = draft.params
    rule.severity = draft.severity
    if "enabled" in data:
        rule.enabled = bool_param(request, "enabled", rule.enabled)
    if "description" in data:
        rule.description = _optional_text(request, "description", "", max_len=300)
    rule.save()
    return ok(quality_rule_dict(rule))


@endpoint()
def quality_rule_delete(request, pk):
    """删除质量规则（其历史结果随规则级联删除）。"""
    rule = _owned_rule(request.user, pk)
    rule.delete()
    return ok({"deleted": 1, "id": pk})


@endpoint()
def quality_rule_test(request, pk):
    """测试规则：可传样例行，缺省对最近一次落地数据试跑且不落库。"""
    rule = _owned_rule(request.user, pk)
    rows = None
    if p(request, "rows") is not None:
        rows = list_param(request, "rows", [], max_items=MAX_RUN_ROWS)
        if any(not isinstance(item, dict) for item in rows):
            raise ValueError("rows 必须是对象数组")
    body = {"id": rule.id}
    for key in ("rule_type", "field", "severity"):
        if p(request, key) is not None:
            body[key] = p(request, key)
    if p(request, "params") is not None:
        body["params"] = json_param(request, "params", {})
    return ok(test_rule(rule.pipeline, body, rows=rows))


@endpoint(("GET",))
def quality_results(request):
    """质量结果列表：按运行 / 规则 / 是否通过筛选。"""
    qs = scope_queryset(
        QualityResult.objects.select_related("rule", "run", "run__pipeline"),
        request.user)
    pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
    if pipeline_id:
        qs = qs.filter(run__pipeline_id=pipeline_id)
    run_id = int_param(request, "run_id", 0, minimum=0)
    if run_id:
        qs = qs.filter(run_id=run_id)
    rule_id = int_param(request, "rule_id", 0, minimum=0)
    if rule_id:
        qs = qs.filter(rule_id=rule_id)
    raw_passed = request.query_params.get("passed")
    if raw_passed not in (None, ""):
        qs = qs.filter(passed=bool_param(request, "passed", True))
    severity = _optional_text(request, "severity", max_len=10)
    if severity:
        if severity not in QUALITY_SEVERITY:
            raise ValueError(f"不支持的严重度：{severity}")
        qs = qs.filter(rule__severity=severity)
    qs = apply_search(qs, request, ["rule__name", "message"])
    page, size = page_params(request)
    return ok(paginate(qs.order_by("-created_at", "-id"), page, size,
                      quality_result_dict))


# ---------------------------------------------------------------------------
# 血缘
# ---------------------------------------------------------------------------


def _lineage_args(request):
    """血缘入参：实体类型 + 标识 + 深度。"""
    entity_type = _text(request, "entity_type", max_len=20)
    if entity_type not in ("connection", "pipeline", "dataset", "table", "webhook", "file"):
        raise ValueError(f"不支持的实体类型：{entity_type}")
    key = _text(request, "key", max_len=200)
    depth = int_param(request, "depth", 3, minimum=1, maximum=6)
    return entity_type, key, depth


@endpoint(("GET",))
def lineage_upstream(request):
    """血缘上游：沿「下游 → 上游」反向遍历，带环保护。"""
    entity_type, key, depth = _lineage_args(request)
    return ok(upstream_of(request.user, entity_type, key, depth))


@endpoint(("GET",))
def lineage_downstream(request):
    """血缘下游：沿「上游 → 下游」遍历。"""
    entity_type, key, depth = _lineage_args(request)
    return ok(downstream_of(request.user, entity_type, key, depth))


@endpoint(("GET",))
def lineage_impact(request):
    """影响分析：某实体变化会波及的管道、数据集与 Webhook。"""
    entity_type, key, depth = _lineage_args(request)
    return ok(impact_analysis(request.user, entity_type, key, depth))


@endpoint(("GET",))
def lineage_graph(request):
    """血缘图：全图或指定管道的子图。"""
    pipeline = None
    pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
    if pipeline_id:
        pipeline = services.resolve_pipeline(request.user, pipeline_id)
    depth = int_param(request, "depth", 3, minimum=1, maximum=6)
    return ok(graph(request.user, pipeline=pipeline, depth=depth))


# ---------------------------------------------------------------------------
# 数据画像
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def profiles(request):
    """画像列表：按管道 / 数据集筛选。"""
    qs = scope_queryset(DatasetProfile.objects.select_related("pipeline"), request.user)
    qs = apply_search(qs, request, ["dataset", "notes"])
    pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
    if pipeline_id:
        qs = qs.filter(pipeline_id=pipeline_id)
    dataset = _optional_text(request, "dataset", "", max_len=120)
    if dataset:
        qs = qs.filter(dataset=dataset)
    page, size = page_params(request)
    return ok(paginate(qs.order_by("-sampled_at", "-id"), page, size, _profile_brief))


@endpoint()
def profile_generate(request):
    """生成画像：优先使用传入 rows，其次指定运行，最后取最近一次成功运行。"""
    pipeline = services.resolve_pipeline(
        request.user, int_param(request, "pipeline_id", None, minimum=1), write=True)
    run = None
    run_id = int_param(request, "run_id", 0, minimum=0)
    if run_id:
        run = pipeline.runs.filter(pk=run_id).first()
        if run is None:
            raise ValueError("运行记录不存在")
    rows = None
    if p(request, "rows") is not None:
        rows = list_param(request, "rows", [], max_items=MAX_RUN_ROWS)
        if any(not isinstance(item, dict) for item in rows):
            raise ValueError("rows 必须是对象数组")
    profile = generate_profile(
        request.user, pipeline, run=run,
        dataset=_optional_text(request, "dataset", "", max_len=120),
        rows=rows,
        sample_size=int_param(request, "sample_size", 200, minimum=1,
                              maximum=MAX_RUN_ROWS))
    return ok(insights.profile_summary(profile))


@endpoint(("GET",))
def profile_detail(request, pk):
    """画像详情：字段级空值率 / 唯一值 / 最值 / 均值 / 长度分布。"""
    profile = scope_queryset(DatasetProfile.objects.all(), request.user) \
        .filter(pk=pk).first()
    if profile is None:
        raise ValueError("画像不存在或无权查看")
    return ok(insights.profile_summary(profile))


@endpoint(("GET",))
def profiles_compare(request):
    """画像对比：两次采样的行数与字段空值率变化。"""
    left = scope_queryset(DatasetProfile.objects.all(), request.user) \
        .filter(pk=int_param(request, "left", None, minimum=1)).first()
    right = scope_queryset(DatasetProfile.objects.all(), request.user) \
        .filter(pk=int_param(request, "right", None, minimum=1)).first()
    if left is None or right is None:
        raise ValueError("画像不存在或无权查看")
    return ok(compare_profiles(left, right))


# ---------------------------------------------------------------------------
# Webhook 触发
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def webhooks(request):
    """Webhook 列表 / 新建；创建响应仅此一次回显明文密钥。"""
    if request.method == "GET":
        qs = scope_queryset(
            WebhookTrigger.objects.select_related("pipeline"), request.user)
        qs = apply_search(qs, request, ["name", "description"])
        pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        raw_enabled = request.query_params.get("enabled")
        if raw_enabled not in (None, ""):
            qs = qs.filter(enabled=bool_param(request, "enabled", True))
        page, size = page_params(request)
        return ok(paginate(qs.order_by("id"), page, size,
                          lambda obj: webhook_dict(obj)))

    pipeline = services.resolve_pipeline(
        request.user, int_param(request, "pipeline_id", None, minimum=1), write=True)
    name = _text(request, "name", max_len=120)
    if pipeline.webhooks.filter(name=name).exists():
        raise ValueError(f"Webhook 名称 {name} 已存在")
    secret = _text(request, "secret", max_len=200)
    if len(secret) < 8:
        raise ValueError("Webhook 密钥至少 8 位")
    webhook = WebhookTrigger(
        owner=request.user, pipeline=pipeline, name=name,
        enabled=bool_param(request, "enabled", True),
        description=_optional_text(request, "description", "", max_len=300),
    )
    webhook.set_secret(secret)
    webhook.save()
    return ok(webhook_dict(webhook, secret_once=secret))


@endpoint()
def webhook_trigger(request, pk):
    """入站触发：校验密钥后同步运行管道；密钥错误直接 400。"""
    webhook = _owned_webhook(request.user, pk)
    if not webhook.enabled:
        raise ValueError("Webhook 已停用")
    secret = _text(request, "secret", max_len=200)
    if not webhook.matches(secret):
        raise ValueError("Webhook 密钥校验失败")
    rows = None
    if p(request, "rows") is not None:
        rows = list_param(request, "rows", [], max_items=MAX_RUN_ROWS + 1)
        limit = min(webhook.pipeline.row_limit or MAX_RUN_ROWS, MAX_RUN_ROWS)
        if len(rows) > limit:
            raise ValueError(f"单次运行行数上限 {limit}，当前 {len(rows)} 行")
    run = services.run_now(webhook.pipeline, request.user, trigger="webhook", rows=rows)
    with transaction.atomic():
        webhook.trigger_count += 1
        webhook.last_triggered_at = timezone.now()
        webhook.save(update_fields=["trigger_count", "last_triggered_at", "updated_at"])
    return ok({"webhook": webhook_dict(webhook), "run": run_dict(run),
               "steps": [step_dict(step) for step in run.steps.order_by("seq", "id")]})


@endpoint()
def webhook_toggle(request, pk):
    """启用 / 停用 Webhook。"""
    webhook = _owned_webhook(request.user, pk)
    webhook.enabled = not webhook.enabled
    webhook.save(update_fields=["enabled", "updated_at"])
    return ok(webhook_dict(webhook))


@endpoint()
def webhook_rotate(request, pk):
    """轮换 Webhook 密钥：新密钥只回显一次。"""
    webhook = _owned_webhook(request.user, pk)
    secret = _text(request, "secret", max_len=200)
    if len(secret) < 8:
        raise ValueError("Webhook 密钥至少 8 位")
    webhook.set_secret(secret)
    webhook.save(update_fields=["secret_digest", "secret_hint", "updated_at"])
    return ok(webhook_dict(webhook, secret_once=secret))


@endpoint()
def webhook_delete(request, pk):
    """删除 Webhook。"""
    webhook = _owned_webhook(request.user, pk)
    webhook.delete()
    return ok({"deleted": 1, "id": pk})


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def _stats_pipeline(request):
    """统计接口的管道过滤参数：传了就必须可见，避免越权查询。"""
    pipeline_id = int_param(request, "pipeline_id", 0, minimum=0)
    if not pipeline_id:
        return None
    return services.resolve_pipeline(request.user, pipeline_id).id


@endpoint(("GET",))
def stats_overview(request):
    """总览：管道 / 运行 / 质量 / 连接 / 调度关键指标。"""
    days = int_param(request, "days", 30, minimum=1, maximum=365)
    return ok(stats.overview(request.user, days))


@endpoint(("GET",))
def stats_success_rate(request):
    """成功率：整体、按天与按管道。"""
    days = int_param(request, "days", 30, minimum=1, maximum=365)
    return ok(stats.success_rate(request.user, days, _stats_pipeline(request)))


@endpoint(("GET",))
def stats_latency(request):
    """耗时分布：P50 / P90 / P95 / P99 与慢运行 TOP。"""
    days = int_param(request, "days", 30, minimum=1, maximum=365)
    return ok(stats.latency(request.user, days, _stats_pipeline(request)))


@endpoint(("GET",))
def stats_row_trend(request):
    """行数趋势：按天汇总输入 / 输出行数。"""
    days = int_param(request, "days", 14, minimum=1, maximum=365)
    return ok(stats.row_trend(request.user, days, _stats_pipeline(request)))


@endpoint(("GET",))
def stats_failed_nodes(request):
    """失败节点 TOP：按节点类型与节点标识聚合失败次数。"""
    days = int_param(request, "days", 30, minimum=1, maximum=365)
    limit = int_param(request, "limit", 10, minimum=1, maximum=50)
    return ok(stats.failed_nodes(request.user, days, limit,
                                 _stats_pipeline(request)))


# 供 URL 层引用的血缘辅助（保持模块自洽的导出面）
__all__ = [
    "catalog", "connectors", "connector_templates", "connector_update",
    "connector_delete", "credentials", "credential_update", "credential_delete",
    "credential_rotate", "connections", "connection_detail", "connection_update",
    "connection_delete", "connection_test", "connection_toggle", "pipelines",
    "pipeline_import", "pipeline_detail", "pipeline_update", "pipeline_delete",
    "pipeline_clone", "pipeline_publish", "pipeline_pause", "pipeline_archive",
    "pipeline_validate", "pipeline_topology", "pipeline_export",
    "pipeline_versions", "pipeline_rollback", "pipeline_stats", "pipeline_nodes",
    "pipeline_nodes_reorder", "pipeline_nodes_bulk", "node_update", "node_delete",
    "pipeline_edges", "pipeline_edges_bulk", "edge_delete", "pipeline_mappings",
    "mapping_update", "mapping_delete", "pipeline_variables", "variable_update",
    "variable_delete", "schedules", "schedule_update", "schedule_delete",
    "schedule_toggle", "schedule_next_run", "schedules_scan", "pipeline_run",
    "runs", "run_detail", "run_steps", "run_logs", "run_cancel",
    "run_retry_failed", "runs_compare", "outputs", "quality_rules",
    "quality_rule_update", "quality_rule_delete", "quality_rule_test",
    "quality_results", "lineage_upstream", "lineage_downstream", "lineage_impact",
    "lineage_graph", "profiles", "profile_generate", "profile_detail",
    "profiles_compare", "webhooks", "webhook_trigger", "webhook_toggle",
    "webhook_rotate", "webhook_delete", "stats_overview", "stats_success_rate",
    "stats_latency", "stats_row_trend", "stats_failed_nodes",
]
