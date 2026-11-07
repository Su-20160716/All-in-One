# -*- coding: utf-8 -*-
"""流程引擎 · 视图公共助手。

把「取对象 + 权限校验 + 入参归一化」集中在这里，避免每个视图复制一遍：
- 对象不存在 / 无权限 / 图不可编辑 → 统一 ValueError（400，中文提示）；
- 节点与连线的入参既支持驼峰前端习惯字段，也支持导出格式（from/to）。
"""
from django.db.models import Q

from core.scoping import is_visible

from devtools.common import opt_bool, opt_num, opt_str, p, req_str
from workflow import services
from workflow.models import (
    DEFINITION_EDITABLE_STATUS,
    NODE_TYPE_VALUES,
    ASSIGNEE_TYPE_VALUES,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowNode,
    WorkflowTask,
)


def client_ip(request):
    """取客户端 IP：优先 X-Forwarded-For 首段，截断到模型字段长度。"""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")
    return str(ip or "")[:45]


def payload_dict(request, key, required=False):
    """读取对象型参数；空值按空字典处理。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是对象")
    return value


def payload_list(request, key, required=False, max_len=500):
    """读取数组型参数，限制长度避免超大 JSON 拖垮请求。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return []
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    return value


def get_definition(pk, user, write=False):
    """取流程定义并做读/写权限校验。"""
    obj = WorkflowDefinition.objects.select_related("owner", "sla_policy").filter(pk=pk).first()
    if obj is None:
        raise ValueError("流程定义不存在")
    if write:
        services.ensure_definition_writable(obj, user)
    else:
        services.ensure_definition_visible(obj, user)
    return obj


def get_instance(pk, user):
    """取流程实例并校验可见性。"""
    obj = WorkflowInstance.objects.select_related(
        "definition", "version", "owner", "starter", "current_node"
    ).filter(pk=pk).first()
    if obj is None:
        raise ValueError("流程实例不存在")
    services.ensure_instance_visible(obj, user)
    return obj


def get_task(pk, user):
    """取任务并校验所属实例可见。"""
    obj = WorkflowTask.objects.select_related(
        "instance", "instance__definition", "node", "assignee", "token", "owner"
    ).filter(pk=pk).first()
    if obj is None:
        raise ValueError("任务不存在")
    services.ensure_instance_visible(obj.instance, user)
    return obj


def ensure_graph_editable(definition):
    """图结构可编辑：草稿/停用 + 无运行中实例。

    发布态的图正在被在途令牌引用；即便状态是停用，只要有运行中实例也不让改，
    否则令牌指向的节点可能被删掉。写权限已由调用方的 get_definition(write=True)
    校验，这里只判定「图能不能动」，避免重复取用户参数。
    """
    if definition.status not in DEFINITION_EDITABLE_STATUS:
        raise ValueError("流程已发布，请克隆副本或回滚版本后再编辑流程图")
    running = definition.instances.filter(status="running").count()
    if running:
        raise ValueError(f"存在 {running} 个运行中的实例，暂不能修改流程图")


def _pick(request, name, existing, attr, default=None):
    """更新场景取值：请求里没传就沿用数据库中的旧值。"""
    value = p(request, name)
    if value is None:
        if existing is not None:
            return getattr(existing, attr)
        return default
    return value


def node_fields(request, existing=None):
    """归一化节点入参。

    返回可直接用于 create/update 的字段字典；key 在更新时不可变
    （连线、条件、退回目标都用 key 引用，改名会让历史数据失去指向）。
    """
    fields = {}
    if existing is None:
        key = req_str(request, "key").strip()
        if not services.KEY_PATTERN.match(key):
            raise ValueError("节点标识只能包含字母、数字、下划线、点与中划线，且不超过 64 字符")
        fields["key"] = key
    else:
        provided = p(request, "key")
        if provided is not None and str(provided).strip() != existing.key:
            raise ValueError("节点标识创建后不可修改，请删除后重建")

    name = _pick(request, "name", existing, "name")
    if name is None or not str(name).strip():
        raise ValueError("节点名称不能为空")
    fields["name"] = str(name).strip()[:200]

    node_type = str(_pick(request, "node_type", existing, "node_type", "task"))
    if node_type not in NODE_TYPE_VALUES:
        raise ValueError("node_type 支持 start/task/decision/parallel_split/parallel_join/end")
    fields["node_type"] = node_type

    assignee_type = str(_pick(request, "assignee_type", existing, "assignee_type", "user"))
    if assignee_type not in ASSIGNEE_TYPE_VALUES:
        raise ValueError("assignee_type 支持 none/user/role/dept/manager/expression")
    fields["assignee_type"] = assignee_type

    rule = p(request, "assignee_rule")
    if rule is None:
        fields["assignee_rule"] = existing.assignee_rule if existing is not None else {}
    else:
        if not isinstance(rule, dict):
            raise ValueError("assignee_rule 必须是对象")
        fields["assignee_rule"] = rule

    fields["sla_minutes"] = int(opt_num(
        request, "sla_minutes",
        existing.sla_minutes if existing is not None else 0,
        minimum=0, maximum=525600, integer=True,
    ))

    form_fields = p(request, "form_fields")
    if form_fields is None:
        fields["form_fields"] = existing.form_fields if existing is not None else []
    else:
        if not isinstance(form_fields, list):
            raise ValueError("form_fields 必须是数组")
        fields["form_fields"] = form_fields

    config = p(request, "config")
    if config is None:
        fields["config"] = existing.config if existing is not None else {}
    else:
        if not isinstance(config, dict):
            raise ValueError("config 必须是对象")
        fields["config"] = config

    position = p(request, "position")
    if isinstance(position, dict):
        fields["position_x"] = int(position.get("x") or 0)
        fields["position_y"] = int(position.get("y") or 0)
    else:
        fields["position_x"] = int(opt_num(
            request, "position_x", existing.position_x if existing is not None else 0,
            integer=True,
        ))
        fields["position_y"] = int(opt_num(
            request, "position_y", existing.position_y if existing is not None else 0,
            integer=True,
        ))

    fields["order"] = int(opt_num(
        request, "order", existing.order if existing is not None else 0, integer=True,
    ))
    for flag in ("allow_reject", "allow_return", "allow_add_sign", "allow_transfer", "require_comment"):
        current = getattr(existing, flag) if existing is not None else (flag != "require_comment")
        fields[flag] = opt_bool(request, flag, current)
    return fields


def transition_fields(request, definition, existing=None):
    """归一化连线入参：校验节点归属、条件语法与默认分支唯一性。"""
    from_node = None
    to_node = None
    if existing is None:
        from_id = opt_num(request, "from_node_id", integer=True)
        to_id = opt_num(request, "to_node_id", integer=True)
        from_key = opt_str(request, "from_key").strip()
        to_key = opt_str(request, "to_key").strip()
        nodes = WorkflowNode.objects.filter(definition=definition)
        if from_id:
            from_node = nodes.filter(pk=int(from_id)).first()
        elif from_key:
            from_node = nodes.filter(key=from_key).first()
        if to_id:
            to_node = nodes.filter(pk=int(to_id)).first()
        elif to_key:
            to_node = nodes.filter(key=to_key).first()
        if from_node is None:
            raise ValueError("源节点不存在")
        if to_node is None:
            raise ValueError("目标节点不存在")
    else:
        from_node = existing.from_node
        to_node = existing.to_node
        for name, attr in (("from_node_id", "from_node_id"), ("to_node_id", "to_node_id")):
            raw = p(request, name)
            if raw is not None and int(raw) != getattr(existing, attr):
                raise ValueError("连线创建后不可更换源/目标节点，请删除后重建")
    if from_node.id == to_node.id:
        raise ValueError("连线不能指向自身")

    condition = p(request, "condition")
    if condition is None:
        condition = existing.condition if existing is not None else ""
    condition = str(condition)
    if condition.strip():
        services.compile_condition(condition)

    priority = int(opt_num(
        request, "priority", existing.priority if existing is not None else 100,
        minimum=0, maximum=100000, integer=True,
    ))
    is_default = opt_bool(
        request, "is_default", existing.is_default if existing is not None else False
    )
    if is_default:
        if _default_branch_exists(definition, from_node, existing):
            raise ValueError("同一节点只能有一个默认分支")
    label = str(_pick(request, "label", existing, "label", "") or "")[:100]
    return {
        "from_node": from_node,
        "to_node": to_node,
        "condition": condition,
        "priority": priority,
        "is_default": is_default,
        "label": label,
    }


def _default_branch_exists(definition, from_node, existing=None):
    """统计同一源节点已有的默认分支（排除当前正在更新的那条）。"""
    from workflow.models import WorkflowTransition

    qs = WorkflowTransition.objects.filter(
        definition=definition, from_node=from_node, is_default=True
    )
    if existing is not None:
        qs = qs.exclude(pk=existing.pk)
    return qs.exists()


def normalize_node_item(item, index=0):
    """批量保存时把前端节点对象补全成模型字段结构。"""
    if not isinstance(item, dict):
        raise ValueError("nodes 数组元素必须是对象")
    key = str(item.get("key") or "").strip()
    if not key:
        raise ValueError("节点缺少 key")
    position = item.get("position") if isinstance(item.get("position"), dict) else {}
    node_type = str(item.get("node_type") or "task")
    if node_type not in NODE_TYPE_VALUES:
        raise ValueError(f"节点 {key} 的类型 {node_type} 不受支持")
    assignee_type = str(item.get("assignee_type") or "user")
    if assignee_type not in ASSIGNEE_TYPE_VALUES:
        raise ValueError(f"节点 {key} 的办理人类型 {assignee_type} 不受支持")
    return {
        "key": key,
        "name": str(item.get("name") or key)[:200],
        "node_type": node_type,
        "assignee_type": assignee_type,
        "assignee_rule": item.get("assignee_rule") or {},
        "sla_minutes": int(item.get("sla_minutes") or 0),
        "form_fields": item.get("form_fields") or [],
        "config": item.get("config") or {},
        "position_x": int(position.get("x", item.get("position_x") or 0) or 0),
        "position_y": int(position.get("y", item.get("position_y") or 0) or 0),
        "order": int(item.get("order", index) or index),
        "allow_reject": bool(item.get("allow_reject", True)),
        "allow_return": bool(item.get("allow_return", True)),
        "allow_add_sign": bool(item.get("allow_add_sign", True)),
        "allow_transfer": bool(item.get("allow_transfer", True)),
        "require_comment": bool(item.get("require_comment", False)),
    }


def normalize_transition_item(item):
    """批量保存时把前端连线对象补全成校验器结构（from/to 兼容 key 与 id）。"""
    if not isinstance(item, dict):
        raise ValueError("transitions 数组元素必须是对象")
    source = item.get("from") or item.get("from_key")
    target = item.get("to") or item.get("to_key")
    if not source or not target:
        raise ValueError("连线缺少 from/to")
    return {
        "from": str(source),
        "to": str(target),
        "condition": str(item.get("condition") or ""),
        "priority": int(item.get("priority") or 100),
        "is_default": bool(item.get("is_default", False)),
        "label": str(item.get("label") or "")[:100],
    }


def visible_task_queryset(user, queryset=None):
    """任务可见集合：管理员全部；否则本人指派 + 候选池 + 实例可见范围内的任务。"""
    from workflow.models import WorkflowTask

    qs = queryset if queryset is not None else WorkflowTask.objects.all()
    if services.is_staff_user(user):
        return qs
    instance_ids = services.instance_queryset_for(user).values("id")
    return qs.filter(
        Q(assignee=user)
        | Q(instance_id__in=instance_ids)
        | services.candidate_index_q(user)
    ).distinct()


def definition_option_list(user, limit=200):
    """发起页的流程下拉：只列已发布且当前用户可发起的流程。"""
    qs = WorkflowDefinition.objects.filter(status="published").select_related("owner")[:limit]
    items = []
    for definition in qs:
        if not services.can_start_definition(definition, user):
            continue
        items.append({
            "id": definition.id,
            "code": definition.code,
            "name": definition.name,
            "category": definition.category,
            "icon": definition.icon,
            "version_no": definition.version_no,
            "form_key": definition.form_key,
        })
    return items


def can_see_definition(definition, user):
    """定义是否可见（不抛异常，供下拉/搜索过滤用）。"""
    return services.is_staff_user(user) or is_visible(definition, user)


def parse_ids(request, key="ids", max_len=200):
    """解析 id 数组（既支持 JSON 数组也支持逗号分隔字符串）。"""
    raw = p(request, key)
    if raw in (None, "", []):
        return []
    if isinstance(raw, str):
        raw = [x for x in raw.replace("，", ",").split(",") if x.strip()]
    if not isinstance(raw, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(raw) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    out = []
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 只能包含整数")
    return out
