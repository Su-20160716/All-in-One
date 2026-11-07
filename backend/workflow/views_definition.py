# -*- coding: utf-8 -*-
"""流程引擎 · 定义与版本接口（19 个）。

定义生命周期：草稿设计 → 校验 → 发布（生成版本快照）→ 停用；
版本支持查看、对比、回滚；克隆/导入导出用于跨环境迁移。
"""
from django.db import transaction

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_str, req)
from workflow import services
from workflow.models import WorkflowDefinition, WorkflowSlaPolicy, WorkflowVersion
from workflow.serializers import (apply_q, apply_status, definition_dict,
                                  paginate, version_dict)
from workflow.views_common import (get_definition, payload_dict, payload_list)

DEFINITION_ORDERING = ("updated_at", "created_at", "name", "code", "version_no", "status")


@endpoint(("GET",))
def definition_list(request):
    """流程定义列表：支持 q / status / category 过滤与分页。"""
    from core.scoping import scope_queryset

    qs = scope_queryset(
        WorkflowDefinition.objects.select_related("owner", "sla_policy"), request.user
    )
    qs = apply_q(qs, request, ["name", "code", "description", "category"])
    qs = apply_status(qs, request, "status", {"draft", "published", "disabled", "archived"})
    category = (request.query_params.get("category") or "").strip()
    if category:
        qs = qs.filter(category=category)
    qs = qs.order_by("-updated_at", "-id")
    return ok(paginate(request, qs, definition_dict))


@endpoint()
def definition_create(request):
    """创建流程定义（草稿）。"""
    code = req_str(request, "code").strip()[:64]
    if not services.KEY_PATTERN.match(code):
        raise ValueError("流程编码只能包含字母、数字、下划线、点与中划线，且不超过 64 字符")
    name = req_str(request, "name").strip()[:200]
    if WorkflowDefinition.objects.filter(owner=request.user, code=code).exists():
        raise ValueError(f"流程编码 {code} 已存在")
    permission = payload_dict(request, "start_permission")
    if not permission:
        permission = {"allow_all": True}
    tags = payload_list(request, "tags", max_len=50)
    settings = payload_dict(request, "settings")
    policy_id = opt_num(request, "sla_policy_id", integer=True)
    policy = None
    if policy_id:
        policy = WorkflowSlaPolicy.objects.filter(pk=int(policy_id)).first()
        if policy is None:
            raise ValueError("SLA 策略不存在")
    with transaction.atomic():
        definition = WorkflowDefinition.objects.create(
            owner=request.user,
            code=code,
            name=name,
            category=(opt_str(request, "category", "通用").strip() or "通用")[:40],
            description=opt_str(request, "description"),
            version_no=1,
            status="draft",
            start_permission=permission,
            form_key=opt_str(request, "form_key").strip()[:64],
            icon=opt_str(request, "icon").strip()[:40],
            tags=[str(x)[:40] for x in tags],
            settings=settings,
            sla_policy=policy,
        )
        services.log_audit("definition.created", definition=definition, actor=request.user,
                           detail={"code": code, "name": name})
    return ok(definition_dict(definition, detail=True))


@endpoint(("GET",))
def definition_detail(request, pk):
    """流程定义详情（默认带节点与连线，便于设计器直接渲染）。"""
    definition = get_definition(pk, request.user)
    data = definition_dict(definition, detail=True)
    with_graph = opt_bool(request, "with_graph", True)
    if with_graph:
        data["nodes"] = [
            services.node_payload(node) | {"id": node.id}
            for node in definition.nodes.order_by("order", "id")
        ]
        data["transitions"] = [
            services.transition_payload(edge) | {"id": edge.id}
            for edge in definition.transitions.select_related("from_node", "to_node")
            .order_by("priority", "id")
        ]
        data["validation"] = services.validate_definition(definition)
    return ok(data)


@endpoint()
def definition_update(request, pk):
    """更新流程定义元信息（编码在已有实例后不可变更）。"""
    definition = get_definition(pk, request.user, write=True)
    fields = []
    code = p(request, "code")
    if code is not None:
        new_code = str(code).strip()[:64]
        if new_code != definition.code:
            if not services.KEY_PATTERN.match(new_code):
                raise ValueError("流程编码只能包含字母、数字、下划线、点与中划线")
            if definition.instances.exists():
                raise ValueError("已有实例的流程不能修改编码")
            if WorkflowDefinition.objects.filter(owner=request.user, code=new_code).exclude(
                    pk=definition.pk).exists():
                raise ValueError(f"流程编码 {new_code} 已存在")
            definition.code = new_code
            fields.append("code")
    for name, attr, max_len in (("name", "name", 200), ("category", "category", 40),
                                ("description", "description", None),
                                ("form_key", "form_key", 64), ("icon", "icon", 40)):
        raw = p(request, name)
        if raw is None:
            continue
        value = str(raw).strip()
        if attr == "name" and not value:
            raise ValueError("流程名称不能为空")
        setattr(definition, attr, value[:max_len] if max_len else value)
        fields.append(attr)
    permission = p(request, "start_permission")
    if permission is not None:
        if not isinstance(permission, dict):
            raise ValueError("start_permission 必须是对象")
        definition.start_permission = permission
        fields.append("start_permission")
    tags = p(request, "tags")
    if tags is not None:
        if not isinstance(tags, list):
            raise ValueError("tags 必须是数组")
        definition.tags = [str(x)[:40] for x in tags[:50]]
        fields.append("tags")
    settings = p(request, "settings")
    if settings is not None:
        if not isinstance(settings, dict):
            raise ValueError("settings 必须是对象")
        definition.settings = settings
        fields.append("settings")
    policy_id = p(request, "sla_policy_id")
    if policy_id is not None:
        if policy_id in ("", 0, "0", None):
            definition.sla_policy = None
        else:
            policy = WorkflowSlaPolicy.objects.filter(pk=int(policy_id)).first()
            if policy is None:
                raise ValueError("SLA 策略不存在")
            definition.sla_policy = policy
        fields.append("sla_policy")
    if not fields:
        raise ValueError("没有需要更新的字段")
    definition.save()
    services.log_audit("definition.updated", definition=definition, actor=request.user,
                       detail={"fields": fields})
    return ok(definition_dict(definition, detail=True))


@endpoint()
def definition_delete(request, pk):
    """删除流程定义（存在运行中实例时拒绝）。"""
    definition = get_definition(pk, request.user, write=True)
    running = definition.instances.filter(status="running").count()
    if running:
        raise ValueError(f"存在 {running} 个运行中的实例，不能删除流程")
    payload = {"id": definition.id, "code": definition.code, "name": definition.name}
    with transaction.atomic():
        services.log_audit("definition.deleted", definition=definition, actor=request.user,
                           detail=payload)
        definition.delete()
    return ok({"deleted": True, **payload})


@endpoint()
def definition_publish(request, pk):
    """发布流程：校验通过后生成版本快照并切到 published。"""
    definition = get_definition(pk, request.user, write=True)
    version = services.publish_definition(definition, request.user,
                                          note=opt_str(request, "note"))
    # 服务内部用 select_for_update 重新取了一份定义并落库，当前对象还是旧的
    # draft 状态，必须回读后才能把 published 返回给前端（否则前端要再拉一次）。
    definition.refresh_from_db()
    return ok({
        "definition": definition_dict(definition, detail=True),
        "version": version_dict(version, detail=True),
    })


@endpoint()
def definition_disable(request, pk):
    """停用流程：已发布的流程不再允许发起（在途实例继续跑）。"""
    definition = get_definition(pk, request.user, write=True)
    if definition.status != "published":
        raise ValueError("只有已发布的流程可以停用")
    definition.status = "disabled"
    definition.save(update_fields=["status", "updated_at"])
    services.log_audit("definition.disabled", definition=definition, actor=request.user,
                       from_status="published", to_status="disabled")
    services.emit_definition_event(definition, "definition.disabled", {"code": definition.code})
    return ok({"id": definition.id, "status": definition.status})


@endpoint(("GET", "POST"))
def definition_validate(request, pk):
    """校验流程结构（可选把结果写回 settings.last_validation）。"""
    definition = get_definition(pk, request.user)
    persist = opt_bool(request, "persist", False)
    if persist:
        services.ensure_definition_writable(definition, request.user)
    return ok(services.validate_definition(definition, persist=persist))


@endpoint()
def definition_clone(request, pk):
    """克隆流程定义（新流程为草稿，图结构完整复制）。"""
    definition = get_definition(pk, request.user)
    clone = services.clone_definition(
        definition, request.user,
        code=opt_str(request, "code").strip(),
        name=opt_str(request, "name").strip(),
    )
    return ok(definition_dict(clone, detail=True))


@endpoint(("GET",))
def definition_export(request, pk):
    """导出流程为可迁移 JSON（含校验报告）。"""
    definition = get_definition(pk, request.user)
    return ok(services.export_definition(definition))


@endpoint()
def definition_import(request):
    """导入流程 JSON（dry_run=true 只校验不落库）。"""
    payload = p(request, "payload")
    if payload is None:
        if "nodes" in (request.data or {}):
            payload = {
                "definition": request.data.get("definition") or request.data,
                "nodes": request.data.get("nodes") or [],
                "transitions": request.data.get("transitions") or [],
            }
        else:
            raise ValueError("缺少必填参数: payload")
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是对象")
    report = services.import_definition(
        request.user, payload,
        dry_run=opt_bool(request, "dry_run", False),
        code=opt_str(request, "code").strip(),
        name=opt_str(request, "name").strip(),
    )
    return ok(report)


@endpoint(("GET",))
def definition_stats(request, pk):
    """单个流程的运行统计（状态、耗时、积压、近 30 天发起量）。"""
    definition = get_definition(pk, request.user)
    return ok(services.definition_stats(definition))


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def version_list(request, pk):
    """流程版本列表。"""
    definition = get_definition(pk, request.user)
    qs = definition.versions.select_related("publisher").all()
    qs = apply_q(qs, request, ["change_note"])
    qs = apply_status(qs, request, "status", {"published", "superseded", "rolled_back"})
    qs = qs.order_by("-version_no", "-id")
    return ok(paginate(request, qs, version_dict))


@endpoint(("GET",))
def version_detail(request, pk):
    """版本详情（默认带完整图快照）。"""
    version = WorkflowVersion.objects.select_related("definition", "publisher").filter(pk=pk).first()
    if version is None:
        raise ValueError("版本不存在")
    services.ensure_definition_visible(version.definition, request.user)
    data = version_dict(version, detail=opt_bool(request, "with_snapshot", True))
    data["definition"] = definition_dict(version.definition)
    return ok(data)


@endpoint()
def version_rollback(request, pk):
    """回滚到指定版本（要求没有运行中的实例）。"""
    version = WorkflowVersion.objects.select_related("definition").filter(pk=pk).first()
    if version is None:
        raise ValueError("版本不存在")
    definition = get_definition(version.definition_id, request.user, write=True)
    new_version = services.rollback_version(
        definition, version, request.user, note=opt_str(request, "note")
    )
    return ok({"rolled_back_from": version.version_no,
               "version": version_dict(new_version),
               "definition": definition_dict(definition)})


@endpoint(("GET",))
def version_diff(request):
    """对比两个版本：节点与连线的新增/删除/变更明细。"""
    left_id = opt_num(request, "from_id", integer=True)
    right_id = opt_num(request, "to_id", integer=True)
    if not left_id or not right_id:
        raise ValueError("缺少参数: from_id / to_id")
    left = WorkflowVersion.objects.select_related("definition").filter(pk=int(left_id)).first()
    right = WorkflowVersion.objects.select_related("definition").filter(pk=int(right_id)).first()
    if left is None or right is None:
        raise ValueError("版本不存在")
    if left.definition_id != right.definition_id:
        raise ValueError("只能对比同一流程定义下的版本")
    services.ensure_definition_visible(left.definition, request.user)
    return ok(services.diff_versions(left, right))
