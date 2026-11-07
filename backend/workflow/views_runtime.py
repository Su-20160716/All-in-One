# -*- coding: utf-8 -*-
"""流程引擎 · 运行态接口（实例 / 任务 / 变量 / 评论 / 附件）。

运行态接口是「人」真正操作的入口，因此这里统一做三件事：
1. 可见性校验交给 services（管理员 / 所有者 / 参与人 / 部门范围）；
2. 状态机拒绝非法操作（完成任务再完成、已结束实例继续办理等）由 services 抛
   ValueError，视图不吞异常；
3. 列表统一 {items, count, page, page_size}，候选池任务在 Python 侧过滤
   （SQLite 不支持 JSONField contains，且候选人数很少）。
"""
from django.db.models import Q
from django.utils import timezone

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_str)
from workflow import services
from workflow.models import (
    TASK_OPEN_STATUS,
    WorkflowAttachment,
    WorkflowAuditLog,
    WorkflowComment,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowSnapshot,
    WorkflowTask,
    WorkflowVariable,
)
from workflow.serializers import (apply_q, apply_status, attachment_dict,
                                  comment_dict, instance_dict, paginate,
                                  parse_page_params, snapshot_dict, task_dict,
                                  variable_dict)
from workflow.views_common import (get_instance, get_task, payload_dict,
                                   payload_list, visible_task_queryset)


def _paginate_items(request, items, mapper):
    """列表分页：候选池任务需要先过滤再分页，这里复用统一分页口径。"""
    page, size = parse_page_params(request)
    count = len(items)
    start = (page - 1) * size
    return {
        "items": [mapper(item) for item in items[start:start + size]],
        "count": count,
        "page": page,
        "page_size": size,
    }


def _open_task_ids_for(user):
    """我可见的未结任务 id：指派给我，或我在候选池里。

    候选池无法用 SQL 精确过滤（JSON 数组 + 角色/部门），先缩小到可见实例的
    未结任务，再用模型方法判定，任务量级在千以内，内存过滤可接受。
    """
    qs = visible_task_queryset(user).filter(status__in=TASK_OPEN_STATUS)
    return [task.id for task in qs.select_related("instance", "node") if task.is_candidate(user)]


# ---------------------------------------------------------------------------
# 实例
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def instance_list(request):
    """实例列表：按可见范围过滤，支持 q / status / definition_id / priority。"""
    qs = services.instance_queryset_for(request.user).select_related(
        "definition", "version", "owner", "starter", "current_node"
    )
    qs = apply_q(qs, request, ["business_no", "title", "definition__name", "definition__code"])
    qs = apply_status(qs, request, "status",
                      {"running", "completed", "rejected", "cancelled", "terminated"})
    definition_id = opt_num(request, "definition_id", integer=True)
    if definition_id:
        qs = qs.filter(definition_id=int(definition_id))
    priority = (request.query_params.get("priority") or "").strip()
    if priority in ("low", "normal", "high", "urgent"):
        qs = qs.filter(priority=priority)
    only_mine = opt_bool(request, "mine", False)
    if only_mine:
        qs = qs.filter(Q(starter=request.user) | Q(owner=request.user))
    overdue = opt_bool(request, "overdue", False)
    if overdue:
        qs = qs.filter(status="running", due_at__lt=timezone.now())
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(request, qs, lambda obj: instance_dict(obj, user=request.user)))


@endpoint()
def instance_start(request):
    """发起流程：校验发布态与发起权限后创建实例并推进到首个等待点。"""
    definition_id = opt_num(request, "definition_id", integer=True, minimum=1)
    if not definition_id:
        raise ValueError("缺少必填参数: definition_id")
    definition = WorkflowDefinition.objects.select_related("owner", "sla_policy").filter(
        pk=int(definition_id)
    ).first()
    if definition is None:
        raise ValueError("流程定义不存在")
    services.ensure_definition_visible(definition, request.user)
    context = payload_dict(request, "context")
    variables = p(request, "variables")
    if variables is not None and not isinstance(variables, (dict, list)):
        raise ValueError("variables 必须是对象或数组")
    instance = services.start_instance(
        definition,
        request.user,
        title=opt_str(request, "title").strip(),
        business_no=opt_str(request, "business_no").strip(),
        business_key=opt_str(request, "business_key").strip(),
        context=context,
        priority=opt_str(request, "priority", "normal").strip() or "normal",
        variables=variables,
        ip=request.META.get("REMOTE_ADDR", "")[:45],
    )
    instance = WorkflowInstance.objects.select_related(
        "definition", "version", "owner", "starter", "current_node"
    ).get(pk=instance.pk)
    return ok(instance_dict(instance, detail=True, user=request.user))


@endpoint(("GET",))
def instance_detail(request, pk):
    """实例详情：默认带上下文、变量、活跃令牌与可取消标记。"""
    instance = get_instance(pk, request.user)
    data = instance_dict(instance, detail=True, user=request.user)
    data["definition"] = {
        "id": instance.definition_id,
        "code": instance.definition.code,
        "name": instance.definition.name,
        "category": instance.definition.category,
        "version_no": instance.version.version_no if instance.version_id else 0,
    }
    data["open_tasks"] = [task_dict(task, user=request.user)
                          for task in instance.tasks.filter(status__in=TASK_OPEN_STATUS)
                          .select_related("instance", "node", "assignee")[:50]]
    data["stats"] = {
        "token_total": instance.tokens.count(),
        "task_total": instance.tasks.count(),
        "comment_total": instance.comments.count(),
        "attachment_total": instance.attachments.count(),
    }
    return ok(data)


@endpoint(("GET",))
def instance_timeline(request, pk):
    """实例时间线：审计日志 + 评论 + 通知 + 快照，按时间倒序。"""
    instance = get_instance(pk, request.user)
    limit = int(opt_num(request, "limit", 200, minimum=1, maximum=1000, integer=True))
    return ok(services.build_timeline(instance, limit=limit))


@endpoint(("GET",))
def instance_variables(request, pk):
    """读取实例变量（敏感变量返回掩码）。"""
    instance = get_instance(pk, request.user)
    qs = instance.variables.all().order_by("key")
    return ok(paginate(request, qs, variable_dict))


@endpoint()
def instance_variables_set(request, pk):
    """写入实例变量：仅运行中实例，类型强校验，事务内 upsert。"""
    instance = get_instance(pk, request.user)
    raw = p(request, "variables")
    if raw is None:
        # 兼容单个变量写法：{key, value, var_type}
        key = req_str(request, "key").strip()
        raw = [{"key": key, "value": p(request, "value"),
                "var_type": opt_str(request, "var_type").strip() or None,
                "is_secret": opt_bool(request, "is_secret", False)}]
    if not isinstance(raw, (dict, list)):
        raise ValueError("variables 必须是对象或数组")
    saved = services.set_variables(instance, request.user, raw)
    return ok({"saved": saved, "count": len(saved)})


@endpoint()
def instance_cancel(request, pk):
    """取消实例：仅发起人/所有者/管理员，且实例必须运行中。"""
    instance = get_instance(pk, request.user)
    result = services.cancel_instance(
        instance.id, request.user,
        reason=opt_str(request, "reason").strip(),
        ip=request.META.get("REMOTE_ADDR", "")[:45],
    )
    result.refresh_from_db()
    return ok(instance_dict(result, detail=True, user=request.user))


@endpoint()
def instance_terminate(request, pk):
    """终止实例：管理动作，必须填写原因，仅流程所有者/管理员可用。"""
    instance = get_instance(pk, request.user)
    reason = opt_str(request, "reason").strip()
    if not reason:
        raise ValueError("终止原因不能为空")
    result = services.terminate_instance(
        instance.id, request.user, reason=reason,
        ip=request.META.get("REMOTE_ADDR", "")[:45],
    )
    result.refresh_from_db()
    return ok(instance_dict(result, detail=True, user=request.user))


@endpoint(("GET",))
def instance_replay(request, pk):
    """回放实例：按 seq 升序返回全部状态快照帧。"""
    instance = get_instance(pk, request.user)
    return ok(services.replay_instance(instance))


@endpoint(("GET",))
def instance_snapshots(request, pk):
    """实例快照列表（按序号倒序，分页）。"""
    instance = get_instance(pk, request.user)
    qs = instance.snapshots.select_related("created_by").order_by("-seq", "-id")
    return ok(paginate(request, qs, snapshot_dict))


@endpoint()
def instance_snapshot_create(request, pk):
    """手动打一个状态快照（运行中实例，用于回放锚点）。"""
    instance = get_instance(pk, request.user)
    if not instance.is_running:
        raise ValueError("只有运行中的实例可以创建快照")
    snapshot = services.snapshot_instance(instance, "manual", request.user)
    return ok(snapshot_dict(snapshot, detail=True))


@endpoint(("GET",))
def instance_comments(request, pk):
    """实例评论列表：非参与人看不到内部评论。"""
    instance = get_instance(pk, request.user)
    qs = instance.comments.select_related("owner").order_by("created_at", "id")
    if not (services.is_staff_user(request.user) or services.is_participant(instance, request.user)):
        qs = qs.filter(is_internal=False)
    qs = apply_q(qs, request, ["content", "owner__username", "owner__display_name"])
    return ok(paginate(request, qs, comment_dict))


@endpoint()
def instance_comment_create(request, pk):
    """新增实例评论（可选内部评论，仅参与人可发）。"""
    instance = get_instance(pk, request.user)
    comment = services.add_comment(
        instance, request.user,
        content=req_str(request, "content"),
        kind=opt_str(request, "kind", "comment").strip() or "comment",
        is_internal=opt_bool(request, "is_internal", False),
    )
    return ok(comment_dict(comment))


@endpoint(("GET",))
def instance_attachments(request, pk):
    """实例附件列表。"""
    instance = get_instance(pk, request.user)
    qs = instance.attachments.select_related("owner").order_by("-created_at", "-id")
    qs = apply_q(qs, request, ["name", "mime"])
    return ok(paginate(request, qs, attachment_dict))


@endpoint()
def instance_attachment_create(request, pk):
    """登记实例附件元数据（文件本体由文件服务负责）。"""
    instance = get_instance(pk, request.user)
    attachment = services.add_attachment(
        instance, request.user,
        name=req_str(request, "name").strip(),
        url=opt_str(request, "url").strip(),
        size=int(opt_num(request, "size", 0, minimum=0, integer=True)),
        mime=opt_str(request, "mime").strip(),
        checksum=opt_str(request, "checksum").strip(),
        kind=opt_str(request, "kind", "file").strip() or "file",
    )
    return ok(attachment_dict(attachment))


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def task_list(request):
    """任务列表：支持 q / status / instance_id / node / overdue 过滤。"""
    qs = visible_task_queryset(request.user).select_related(
        "instance", "node", "assignee"
    )
    qs = apply_q(qs, request, ["name", "instance__business_no", "instance__title",
                              "node__name", "assignee__username"])
    qs = apply_status(qs, request, "status", set(TASK_OPEN_STATUS) | {"completed", "cancelled"})
    instance_id = opt_num(request, "instance_id", integer=True)
    if instance_id:
        qs = qs.filter(instance_id=int(instance_id))
    node_key = (request.query_params.get("node_key") or "").strip()
    if node_key:
        qs = qs.filter(node__key=node_key)
    if opt_bool(request, "overdue", False):
        qs = qs.filter(status__in=TASK_OPEN_STATUS).filter(
            Q(is_overdue=True) | Q(due_at__lt=timezone.now())
        )
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(request, qs, lambda obj: task_dict(obj, user=request.user)))


@endpoint(("GET",))
def task_my_pending(request):
    """我的待办：指派给我或我仍在候选池中的未结任务。"""
    ids = _open_task_ids_for(request.user)
    qs = WorkflowTask.objects.filter(pk__in=ids).select_related(
        "instance", "node", "assignee"
    )
    qs = apply_q(qs, request, ["name", "instance__business_no", "instance__title"])
    items = list(qs.order_by("-priority", "due_at", "id"))
    return ok(_paginate_items(request, items, lambda obj: task_dict(obj, user=request.user)))


@endpoint(("GET",))
def task_my_done(request):
    """我的已办：我实际办理过的任务（含候选池直接办理）。"""
    qs = WorkflowTask.objects.filter(assignee=request.user, status="completed").select_related(
        "instance", "node", "assignee"
    )
    qs = apply_q(qs, request, ["name", "instance__business_no", "instance__title"])
    action = (request.query_params.get("action") or "").strip()
    if action in ("approve", "reject", "return", "add_sign", "complete"):
        qs = qs.filter(action=action)
    qs = qs.order_by("-completed_at", "-id")
    return ok(paginate(request, qs, lambda obj: task_dict(obj, user=request.user)))


@endpoint(("GET",))
def task_detail(request, pk):
    """任务详情（含提交数据、加签数、是否能操作）。"""
    task = get_task(pk, request.user)
    data = task_dict(task, user=request.user, detail=True)
    data["instance"] = instance_dict(task.instance, user=request.user)
    data["comments"] = [comment_dict(c) for c in
                        task.comments.select_related("owner").order_by("created_at")[:50]]
    data["attachments"] = [attachment_dict(a) for a in
                           task.attachments.select_related("owner").order_by("-created_at")[:50]]
    return ok(data)


@endpoint()
def task_claim(request, pk):
    """认领任务：仅待认领，且必须是候选人或管理员。"""
    task = get_task(pk, request.user)
    claimed = services.claim_task(
        task.id, request.user, ip=request.META.get("REMOTE_ADDR", "")[:45]
    )
    return ok(task_dict(claimed, user=request.user, detail=True))


@endpoint()
def task_complete(request, pk):
    """办理任务：同意 / 拒绝 / 退回 / 加签，非法状态由引擎拒绝。"""
    task = get_task(pk, request.user)
    action = opt_str(request, "action", "approve").strip() or "approve"
    add_sign_ids = p(request, "add_sign_user_ids")
    if add_sign_ids is not None and not isinstance(add_sign_ids, list):
        raise ValueError("add_sign_user_ids 必须是数组")
    instance = services.complete_task(
        task.id,
        request.user,
        action=action,
        comment=opt_str(request, "comment"),
        payload=payload_dict(request, "payload"),
        target_node_key=opt_str(request, "target_node_key").strip(),
        add_sign_user_ids=add_sign_ids or [],
        ip=request.META.get("REMOTE_ADDR", "")[:45],
    )
    instance = WorkflowInstance.objects.select_related(
        "definition", "version", "owner", "starter", "current_node"
    ).get(pk=instance.pk)
    task.refresh_from_db()
    return ok({
        "task": task_dict(task, user=request.user, detail=True),
        "instance": instance_dict(instance, user=request.user),
    })


@endpoint()
def task_delegate(request, pk):
    """委派任务：保留原候选集，受托人可办理，原办理人仍可接管。"""
    task = get_task(pk, request.user)
    target = p(request, "target_user_id") or p(request, "target") or p(request, "user_id")
    if target in (None, ""):
        raise ValueError("缺少必填参数: target_user_id")
    result = services.delegate_task(
        task.id, request.user, target,
        comment=opt_str(request, "comment"),
        ip=request.META.get("REMOTE_ADDR", "")[:45],
    )
    return ok(task_dict(result, user=request.user, detail=True))


@endpoint()
def task_transfer(request, pk):
    """转办任务：候选集替换为目标用户，原办理人不再可见。"""
    task = get_task(pk, request.user)
    target = p(request, "target_user_id") or p(request, "target") or p(request, "user_id")
    if target in (None, ""):
        raise ValueError("缺少必填参数: target_user_id")
    result = services.transfer_task(
        task.id, request.user, target,
        comment=opt_str(request, "comment"),
        ip=request.META.get("REMOTE_ADDR", "")[:45],
    )
    return ok(task_dict(result, user=request.user, detail=True))


@endpoint()
def task_batch_complete(request):
    """批量办理：逐条独立事务，返回成功与失败明细。"""
    task_ids = p(request, "task_ids")
    if not isinstance(task_ids, list) or not task_ids:
        raise ValueError("task_ids 必须是非空数组")
    action = opt_str(request, "action", "approve").strip() or "approve"
    result = services.batch_complete(
        task_ids, request.user, action=action,
        comment=opt_str(request, "comment"),
        ip=request.META.get("REMOTE_ADDR", "")[:45],
    )
    return ok(result)


@endpoint(("GET",))
def task_overdue(request):
    """逾期任务列表：已标记逾期或已过截止时间的未结任务。"""
    qs = visible_task_queryset(request.user).filter(status__in=TASK_OPEN_STATUS).filter(
        Q(is_overdue=True) | Q(due_at__lt=timezone.now())
    ).select_related("instance", "node", "assignee")
    qs = apply_q(qs, request, ["name", "instance__business_no", "assignee__username"])
    qs = qs.order_by("due_at", "id")
    data = paginate(request, qs, lambda obj: task_dict(obj, user=request.user))
    data["summary"] = {
        "overdue_total": data["count"],
        "unassigned": sum(1 for item in data["items"] if item.get("assignee") is None),
    }
    return ok(data)
