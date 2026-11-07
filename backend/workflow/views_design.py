# -*- coding: utf-8 -*-
"""流程引擎 · 设计器接口（节点、连线、整图保存）。

设计器通常一次拖拽会产生多次请求：先加节点再加连线。因此单节点/单连线
写接口不做整图强校验（否则中间态永远不合法），只在「发布 / 校验 / 整图保存
(strict)」时做全图校验；任何入口都会校验条件表达式与指派规则本身。
"""
from django.db import transaction

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p
from workflow import services
from workflow.models import WorkflowNode, WorkflowTransition
from workflow.serializers import (apply_q, node_dict, paginate, transition_dict)
from workflow.views_common import (ensure_graph_editable, get_definition,
                                   normalize_node_item, normalize_transition_item,
                                   node_fields, payload_list, transition_fields)


def _get_node(pk, user, write=False):
    """取节点并校验所属定义权限。"""
    node = WorkflowNode.objects.select_related("definition", "owner").filter(pk=pk).first()
    if node is None:
        raise ValueError("流程节点不存在")
    get_definition(node.definition_id, user, write=write)
    return node


def _get_transition(pk, user, write=False):
    """取连线并校验所属定义权限。"""
    edge = WorkflowTransition.objects.select_related(
        "definition", "from_node", "to_node", "owner"
    ).filter(pk=pk).first()
    if edge is None:
        raise ValueError("流程连线不存在")
    get_definition(edge.definition_id, user, write=write)
    return edge


def _validate_task_assignment(fields):
    """只对任务节点校验指派规则，网关/起止节点不要求办理人。"""
    if fields.get("node_type") != "task":
        return
    issues = services._validate_assignee_rule(fields)
    if issues:
        raise ValueError(issues[0]["message"])


@endpoint(("GET",))
def node_list(request, pk):
    """流程节点列表（支持 node_type / q 过滤）。"""
    definition = get_definition(pk, request.user)
    qs = definition.nodes.select_related("owner").all()
    node_type = (request.query_params.get("node_type") or "").strip()
    if node_type:
        qs = qs.filter(node_type=node_type)
    qs = apply_q(qs, request, ["name", "key"])
    qs = qs.order_by("order", "id")
    return ok(paginate(request, qs, node_dict))


@endpoint()
def node_create(request, pk):
    """新增流程节点。"""
    definition = get_definition(pk, request.user, write=True)
    ensure_graph_editable(definition)
    fields = node_fields(request)
    _validate_task_assignment(fields)
    if definition.nodes.filter(key=fields["key"]).exists():
        raise ValueError(f"节点标识 {fields['key']} 已存在")
    with transaction.atomic():
        node = WorkflowNode.objects.create(
            definition=definition, owner=definition.owner, **fields
        )
        services.log_audit("node.created", definition=definition, actor=request.user,
                           detail={"node": node.key, "type": node.node_type})
    return ok(node_dict(node))


@endpoint()
def node_update(request, pk):
    """更新流程节点（标识不可变）。"""
    node = _get_node(pk, request.user, write=True)
    ensure_graph_editable(node.definition)
    fields = node_fields(request, existing=node)
    _validate_task_assignment(fields)
    for attr, value in fields.items():
        setattr(node, attr, value)
    node.save()
    services.log_audit("node.updated", definition=node.definition, actor=request.user,
                       detail={"node": node.key, "fields": sorted(fields)})
    return ok(node_dict(node))


@endpoint()
def node_delete(request, pk):
    """删除流程节点（关联连线级联删除）。"""
    node = _get_node(pk, request.user, write=True)
    ensure_graph_editable(node.definition)
    payload = {"id": node.id, "key": node.key, "name": node.name}
    with transaction.atomic():
        node.delete()
        services.log_audit("node.deleted", definition=node.definition, actor=request.user,
                           detail=payload)
    return ok({"deleted": True, **payload})


@endpoint(("GET",))
def transition_list(request, pk):
    """流程连线列表（支持 q 过滤标签与条件）。"""
    definition = get_definition(pk, request.user)
    qs = definition.transitions.select_related("from_node", "to_node", "owner").all()
    qs = apply_q(qs, request, ["label", "condition", "from_node__name", "to_node__name"])
    qs = qs.order_by("priority", "id")
    return ok(paginate(request, qs, transition_dict))


@endpoint()
def transition_create(request, pk):
    """新增流程连线（条件表达式即时编译校验）。"""
    definition = get_definition(pk, request.user, write=True)
    ensure_graph_editable(definition)
    fields = transition_fields(request, definition)
    if WorkflowTransition.objects.filter(
        from_node=fields["from_node"], to_node=fields["to_node"],
        priority=fields["priority"],
    ).exists():
        raise ValueError("相同源/目标/优先级的连线已存在")
    with transaction.atomic():
        edge = WorkflowTransition.objects.create(
            definition=definition, owner=definition.owner, **fields
        )
        services.log_audit("transition.created", definition=definition, actor=request.user,
                           detail={"from": edge.from_node.key, "to": edge.to_node.key})
    return ok(transition_dict(edge))


@endpoint()
def transition_update(request, pk):
    """更新流程连线（条件、优先级、标签、默认分支）。"""
    edge = _get_transition(pk, request.user, write=True)
    ensure_graph_editable(edge.definition)
    fields = transition_fields(request, edge.definition, existing=edge)
    duplicate = WorkflowTransition.objects.filter(
        from_node=fields["from_node"], to_node=fields["to_node"],
        priority=fields["priority"],
    ).exclude(pk=edge.pk)
    if duplicate.exists():
        raise ValueError("相同源/目标/优先级的连线已存在")
    for attr, value in fields.items():
        setattr(edge, attr, value)
    edge.save()
    services.log_audit("transition.updated", definition=edge.definition, actor=request.user,
                       detail={"from": edge.from_node.key, "to": edge.to_node.key,
                               "fields": sorted(fields)})
    return ok(transition_dict(edge))


@endpoint()
def transition_delete(request, pk):
    """删除流程连线。"""
    edge = _get_transition(pk, request.user, write=True)
    ensure_graph_editable(edge.definition)
    payload = {"id": edge.id, "from": edge.from_node.key, "to": edge.to_node.key}
    with transaction.atomic():
        edge.delete()
        services.log_audit("transition.deleted", definition=edge.definition, actor=request.user,
                           detail=payload)
    return ok({"deleted": True, **payload})


@endpoint(("GET",))
def graph_detail(request, pk):
    """读取整张流程图：节点、连线、校验报告与图算法结果。"""
    definition = get_definition(pk, request.user)
    validation = services.validate_definition(definition)
    nodes, transitions = services._definition_graph(definition)
    return ok({
        "definition_id": definition.id,
        "definition": {
            "code": definition.code,
            "name": definition.name,
            "status": definition.status,
            "version_no": definition.version_no,
            "is_editable": definition.is_editable,
        },
        "nodes": [item | {"id": node.id} for item, node in
                  zip(nodes, definition.nodes.order_by("order", "id"))],
        "transitions": transitions,
        "validation": validation,
        "graph": {
            "cycles": validation["stats"].get("cycles", []),
            "topological_order": validation["stats"].get("topological_order", []),
            "longest_path_minutes": validation["stats"].get("longest_path_minutes", 0),
        },
    })


@endpoint()
def graph_save(request, pk):
    """整图保存：一次提交 nodes + transitions，事务内整体替换。

    strict=true（默认）时先做全图校验，不合法直接回滚；设计器自动保存草稿时
    可传 strict=false，仅落库并在响应里返回问题清单。
    """
    definition = get_definition(pk, request.user, write=True)
    ensure_graph_editable(definition)
    raw_nodes = payload_list(request, "nodes", required=True, max_len=500)
    raw_edges = payload_list(request, "transitions", max_len=2000)
    nodes = [normalize_node_item(item, index) for index, item in enumerate(raw_nodes)]
    edges = [normalize_transition_item(item) for item in raw_edges]
    keys = [n["key"] for n in nodes]
    if len(keys) != len(set(keys)):
        raise ValueError("节点 key 不能重复")
    validation = services.validate_payload({"nodes": nodes, "transitions": edges})
    strict = opt_bool(request, "strict", True)
    if strict and not validation["valid"]:
        raise ValueError("流程图校验未通过：" + "；".join(
            e["message"] for e in validation["errors"][:3]))
    with transaction.atomic():
        definition.transitions.all().delete()
        definition.nodes.all().delete()
        created = {}
        for index, item in enumerate(nodes):
            node = services._node_from_payload(definition, definition.owner, item, index)
            node.save()
            created[node.key] = node
        for item in edges:
            source = created.get(item["from"])
            target = created.get(item["to"])
            if source is None or target is None:
                raise ValueError("连线引用了不存在的节点")
            WorkflowTransition.objects.create(
                definition=definition,
                owner=definition.owner,
                from_node=source,
                to_node=target,
                condition=item["condition"],
                priority=item["priority"],
                is_default=item["is_default"],
                label=item["label"],
            )
        services.log_audit("graph.saved", definition=definition, actor=request.user,
                           detail={"nodes": len(nodes), "transitions": len(edges),
                                   "strict": strict, "valid": validation["valid"]})
    return ok({
        "definition_id": definition.id,
        "nodes": len(nodes),
        "transitions": len(edges),
        "validation": validation,
        "saved": True,
    })


@endpoint(("GET",))
def node_options(request, pk):
    """设计器下拉数据：候选人、部门、角色与节点类型候选。

    单独返回而不是塞进节点详情，是因为这些选项随组织架构变化，需要按需刷新。
    """
    from accounts.models import Department, Role
    from django.contrib.auth import get_user_model

    definition = get_definition(pk, request.user)
    User = get_user_model()
    users = User.objects.filter(is_active=True).order_by("id")[:200]
    roles = Role.objects.all().order_by("id")[:100]
    departments = Department.objects.all().order_by("sort", "id")[:200]
    return ok({
        "definition_id": definition.id,
        "users": [{"id": u.id, "username": u.username,
                   "name": getattr(u, "display_name", "") or u.username,
                   "department_id": getattr(u, "department_id", None)} for u in users],
        "roles": [{"id": r.id, "code": r.code, "name": r.name} for r in roles],
        "departments": [{"id": d.id, "name": d.name,
                         "parent_id": d.parent_id,
                         "leader_id": d.leader_id} for d in departments],
        "node_types": [{"value": v, "label": label} for v, label in
                       WorkflowNode._meta.get_field("node_type").choices],
        "assignee_types": [{"value": v, "label": label} for v, label in
                           WorkflowNode._meta.get_field("assignee_type").choices],
    })
