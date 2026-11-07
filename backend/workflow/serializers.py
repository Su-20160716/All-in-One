# -*- coding: utf-8 -*-
"""流程引擎 · 序列化与列表查询助手。

视图层只做「取参 → 调服务 → 统一响应」，所有字典结构集中在这里，
保证同一实体在列表、详情、时间线里的字段名完全一致，前端不需要多套解析。
"""
from django.db.models import Q
from django.utils import timezone

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20
MAX_Q_LENGTH = 120


def iso(value):
    """时间转 ISO 字符串；None 返回空串（前端直接展示不炸）。"""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def date_iso(value):
    """日期转 ISO 字符串。"""
    if not value:
        return ""
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def user_brief(user):
    """用户简要信息：id / username / 展示名 / 部门。"""
    if user is None:
        return None
    return {
        "id": getattr(user, "id", None),
        "username": getattr(user, "username", ""),
        "name": getattr(user, "display_name", "") or getattr(user, "username", ""),
        "department_id": getattr(user, "department_id", None),
    }


def _count(qs):
    """安全 count（queryset 为空或异常时返回 0）。"""
    try:
        return int(qs.count())
    except Exception:  # noqa: BLE001 —— 统计失败不应让列表 500
        return 0


# ---------------------------------------------------------------------------
# 实体字典
# ---------------------------------------------------------------------------


def definition_dict(obj, detail=False):
    """流程定义字典。"""
    data = {
        "id": obj.id,
        "code": obj.code,
        "name": obj.name,
        "category": obj.category,
        "description": obj.description,
        "version_no": obj.version_no,
        "status": obj.status,
        "form_key": obj.form_key,
        "icon": obj.icon,
        "tags": obj.tags or [],
        "sla_policy_id": obj.sla_policy_id,
        "owner": user_brief(obj.owner),
        "published_at": iso(obj.published_at),
        "node_count": _count(obj.nodes.all()),
        "transition_count": _count(obj.transitions.all()),
        "instance_count": _count(obj.instances.all()),
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
        "is_editable": obj.is_editable,
    }
    if detail:
        data["start_permission"] = obj.permission_payload()
        data["settings"] = obj.settings or {}
        latest = obj.latest_version
        data["latest_version"] = version_dict(latest) if latest else None
    return data


def version_dict(obj, detail=False):
    """流程版本字典。"""
    data = {
        "id": obj.id,
        "definition_id": obj.definition_id,
        "version_no": obj.version_no,
        "status": obj.status,
        "publisher": user_brief(obj.publisher),
        "published_at": iso(obj.published_at),
        "change_note": obj.change_note,
        "node_count": obj.node_count,
        "transition_count": obj.transition_count,
        "checksum": obj.checksum,
        "is_current": obj.is_current,
        "created_at": iso(obj.created_at),
    }
    if detail:
        data["snapshot"] = obj.snapshot or {}
    return data


def node_dict(obj):
    """流程节点字典。"""
    return {
        "id": obj.id,
        "definition_id": obj.definition_id,
        "key": obj.key,
        "name": obj.name,
        "node_type": obj.node_type,
        "assignee_type": obj.assignee_type,
        "assignee_rule": obj.assignee_rule or {},
        "assignee_summary": obj.assignee_summary(),
        "sla_minutes": obj.sla_minutes,
        "sla_hours": obj.sla_hours,
        "form_fields": obj.form_fields or [],
        "config": obj.config or {},
        "position": {"x": obj.position_x, "y": obj.position_y},
        "order": obj.order,
        "allow_reject": obj.allow_reject,
        "allow_return": obj.allow_return,
        "allow_add_sign": obj.allow_add_sign,
        "allow_transfer": obj.allow_transfer,
        "require_comment": obj.require_comment,
        "outgoing_count": _count(obj.outgoing.all()),
        "incoming_count": _count(obj.incoming.all()),
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }


def transition_dict(obj):
    """流程连线字典（from/to 同时给 id 与 key，方便画布与 key 引用）。"""
    return {
        "id": obj.id,
        "definition_id": obj.definition_id,
        "from_node_id": obj.from_node_id,
        "from_key": obj.from_node.key,
        "from_name": obj.from_node.name,
        "to_node_id": obj.to_node_id,
        "to_key": obj.to_node.key,
        "to_name": obj.to_node.name,
        "condition": obj.condition,
        "has_condition": obj.has_condition,
        "priority": obj.priority,
        "is_default": obj.is_default,
        "label": obj.label,
        "created_at": iso(obj.created_at),
    }


def token_dict(obj):
    """执行令牌字典。"""
    return {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "node_id": obj.node_id,
        "node_key": obj.node.key if obj.node_id else "",
        "node_name": obj.node.name if obj.node_id else "",
        "status": obj.status,
        "parent_id": obj.parent_id,
        "branch_label": obj.branch_label,
        "generation": obj.generation,
        "consumed_at": iso(obj.consumed_at),
        "created_at": iso(obj.created_at),
    }


def task_dict(obj, user=None, detail=False):
    """任务字典；传入 user 时附带 can_operate，前端据此决定按钮可用性。"""
    data = {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "business_no": obj.instance.business_no if obj.instance_id else "",
        "instance_title": obj.instance.title if obj.instance_id else "",
        "instance_status": obj.instance.status if obj.instance_id else "",
        "node_id": obj.node_id,
        "node_key": obj.node.key if obj.node_id else "",
        "node_name": obj.node.name if obj.node_id else "",
        "name": obj.name,
        "status": obj.status,
        "assignee": user_brief(obj.assignee),
        "assignee_source": obj.assignee_source,
        "candidate_users": obj.candidate_users or [],
        "candidate_roles": obj.candidate_roles or [],
        "candidate_depts": obj.candidate_depts or [],
        "action": obj.action,
        "comment": obj.comment,
        "priority": obj.priority,
        "due_at": iso(obj.due_at),
        "is_overdue": obj.is_overdue,
        "overdue_minutes": obj.overdue_minutes,
        "claimed_at": iso(obj.claimed_at),
        "completed_at": iso(obj.completed_at),
        "duration_minutes": obj.duration_minutes,
        "wait_minutes": obj.wait_minutes,
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }
    if detail:
        data["payload"] = obj.payload or {}
        data["parent_task_id"] = obj.parent_task_id
        data["token_id"] = obj.token_id
        data["add_sign_count"] = _count(obj.add_sign_tasks.all())
    if user is not None:
        data["can_operate"] = obj.can_be_operated_by(user)
    return data


def instance_dict(obj, detail=False, user=None):
    """实例字典。"""
    data = {
        "id": obj.id,
        "definition_id": obj.definition_id,
        "definition_code": obj.definition.code if obj.definition_id else "",
        "definition_name": obj.definition.name if obj.definition_id else "",
        "version_id": obj.version_id,
        "version_no": obj.version.version_no if obj.version_id else 0,
        "business_no": obj.business_no,
        "business_key": obj.business_key,
        "title": obj.title,
        "category": obj.category,
        "status": obj.status,
        "priority": obj.priority,
        "result": obj.result,
        "starter": user_brief(obj.starter),
        "owner": user_brief(obj.owner),
        "current_node": {
            "id": obj.current_node_id,
            "key": obj.current_node.key if obj.current_node_id else "",
            "name": obj.current_node_name,
            "type": obj.current_node.node_type if obj.current_node_id else "",
        },
        "due_at": iso(obj.due_at),
        "is_overdue": obj.is_overdue,
        "duration_minutes": obj.duration_minutes,
        "progress_pct": obj.progress_pct,
        "open_task_count": _count(obj.tasks.filter(status__in=("pending", "claimed"))),
        "task_count": _count(obj.tasks.all()),
        "started_at": iso(obj.started_at),
        "finished_at": iso(obj.finished_at),
        "last_activity_at": iso(obj.last_activity_at),
        "created_at": iso(obj.created_at),
        "updated_at": iso(obj.updated_at),
    }
    if detail:
        data["context"] = obj.context or {}
        data["variables"] = [variable_dict(v) for v in obj.variables.all()]
        data["active_tokens"] = [token_dict(t) for t in obj.tokens.filter(status="active")]
        data["can_cancel"] = bool(user is not None and obj.can_be_cancelled_by(user))
    return data


def variable_dict(obj):
    """变量字典；敏感变量返回掩码，避免前端/日志泄露。"""
    return {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "key": obj.key,
        "value": "******" if obj.is_secret else obj.value,
        "var_type": obj.var_type,
        "is_secret": obj.is_secret,
        "updated_at": iso(obj.updated_at),
    }


def comment_dict(obj):
    """评论字典。"""
    return {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "task_id": obj.task_id,
        "author": user_brief(obj.owner),
        "author_name": obj.author_name,
        "content": obj.content,
        "kind": obj.kind,
        "is_internal": obj.is_internal,
        "created_at": iso(obj.created_at),
    }


def attachment_dict(obj):
    """附件字典。"""
    return {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "task_id": obj.task_id,
        "name": obj.name,
        "url": obj.url,
        "size": obj.size,
        "size_kb": obj.size_kb,
        "mime": obj.mime,
        "checksum": obj.checksum,
        "kind": obj.kind,
        "uploader": user_brief(obj.owner),
        "created_at": iso(obj.created_at),
    }


def timer_dict(obj):
    """定时器字典。"""
    return {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "task_id": obj.task_id,
        "timer_type": obj.timer_type,
        "fire_at": iso(obj.fire_at),
        "status": obj.status,
        "fired_at": iso(obj.fired_at),
        "attempts": obj.attempts,
        "repeat_minutes": obj.repeat_minutes,
        "payload": obj.payload or {},
        "is_due": obj.is_due,
    }


def delegation_dict(obj):
    """委托字典。"""
    return {
        "id": obj.id,
        "from_user": user_brief(obj.from_user),
        "to_user": user_brief(obj.to_user),
        "definition_id": obj.definition_id,
        "scope": obj.scope,
        "start_at": iso(obj.start_at),
        "end_at": iso(obj.end_at),
        "status": obj.status,
        "is_active": obj.is_active,
        "reason": obj.reason,
        "created_at": iso(obj.created_at),
    }


def notification_dict(obj):
    """通知字典。"""
    return {
        "id": obj.id,
        "recipient": user_brief(obj.recipient),
        "instance_id": obj.instance_id,
        "task_id": obj.task_id,
        "title": obj.title,
        "content": obj.content,
        "level": obj.level,
        "channel": obj.channel,
        "status": obj.status,
        "is_read": obj.is_read,
        "payload": obj.payload or {},
        "sent_at": iso(obj.sent_at),
        "read_at": iso(obj.read_at),
        "created_at": iso(obj.created_at),
    }


def audit_dict(obj):
    """审计日志字典。"""
    return {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "task_id": obj.task_id,
        "definition_id": obj.definition_id,
        "actor": user_brief(obj.actor),
        "actor_name": obj.actor_name,
        "action": obj.action,
        "from_status": obj.from_status,
        "to_status": obj.to_status,
        "detail": obj.detail or {},
        "duration_ms": obj.duration_ms,
        "ip": obj.ip,
        "created_at": iso(obj.created_at),
    }


def snapshot_dict(obj, detail=False):
    """实例快照字典。"""
    data = {
        "id": obj.id,
        "instance_id": obj.instance_id,
        "seq": obj.seq,
        "reason": obj.reason,
        "node_key": obj.node_key,
        "token_count": obj.token_count,
        "task_count": obj.task_count,
        "checksum": obj.checksum,
        "created_by": user_brief(obj.created_by),
        "created_at": iso(obj.created_at),
    }
    if detail:
        data["state"] = obj.state or {}
    return data


def metric_dict(obj):
    """指标字典。"""
    return {
        "id": obj.id,
        "definition_id": obj.definition_id,
        "metric_date": date_iso(obj.metric_date),
        "instances_started": obj.instances_started,
        "instances_completed": obj.instances_completed,
        "instances_rejected": obj.instances_rejected,
        "tasks_created": obj.tasks_created,
        "tasks_completed": obj.tasks_completed,
        "overdue_tasks": obj.overdue_tasks,
        "avg_duration_minutes": obj.avg_duration_minutes,
        "completion_rate": obj.completion_rate,
    }


def webhook_dict(obj):
    """Webhook 订阅字典。"""
    return {
        "id": obj.id,
        "name": obj.name,
        "url": obj.url,
        "definition_id": obj.definition_id,
        "events": obj.events or [],
        "active": obj.active,
        "last_status": obj.last_status,
        "last_delivery_at": iso(obj.last_delivery_at),
        "failure_count": obj.failure_count,
        "has_secret": bool(obj.secret),
        "created_at": iso(obj.created_at),
    }


def sla_policy_dict(obj):
    """SLA 策略字典。"""
    return obj.to_payload() | {
        "owner": user_brief(obj.owner),
        "description": obj.description,
        "escalate_to": obj.escalate_to,
        "created_at": iso(obj.created_at),
    }


# ---------------------------------------------------------------------------
# 查询助手
# ---------------------------------------------------------------------------


def parse_page_params(request):
    """解析 page / page_size：非法值回退默认，page_size 上限 200。"""
    def _int(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    page = max(_int(request.query_params.get("page"), 1), 1)
    size = _int(request.query_params.get("page_size"), DEFAULT_PAGE_SIZE)
    size = min(max(size, 1), MAX_PAGE_SIZE)
    return page, size


def paginate(request, queryset, mapper):
    """统一分页响应：{items, count, page, page_size}。"""
    page, size = parse_page_params(request)
    count = _count(queryset)
    start = (page - 1) * size
    rows = queryset[start:start + size]
    return {
        "items": [mapper(obj) for obj in rows],
        "count": count,
        "page": page,
        "page_size": size,
    }


def apply_q(queryset, request, fields):
    """q 关键字模糊搜索：多个字段 OR，长度超限直接忽略（防超长 LIKE）。"""
    q = (request.query_params.get("q") or "").strip()
    if not q or not fields:
        return queryset
    q = q[:MAX_Q_LENGTH]
    cond = Q()
    for field in fields:
        cond |= Q(**{f"{field}__icontains": q})
    return queryset.filter(cond)


def apply_status(queryset, request, field="status", allowed=None):
    """status 过滤：只接受白名单值，未知值忽略而不是报错（列表兼容性）。"""
    value = (request.query_params.get("status") or "").strip()
    if not value:
        return queryset
    if allowed is not None and value not in allowed:
        return queryset
    return queryset.filter(**{field: value})


def apply_ordering(queryset, request, allowed, default):
    """排序：只允许白名单字段，前缀 - 表示倒序。"""
    raw = (request.query_params.get("ordering") or "").strip()
    if not raw:
        return queryset.order_by(*default)
    field = raw[1:] if raw.startswith("-") else raw
    if field not in allowed:
        return queryset.order_by(*default)
    return queryset.order_by(raw)


def now_iso():
    """当前时间 ISO 串（catalog/健康检查用）。"""
    return timezone.now().isoformat()
