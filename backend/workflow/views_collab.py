# -*- coding: utf-8 -*-
"""流程引擎 · 协作接口（委托 / 通知 / 审计 / Webhook / SLA 策略 / 表达式）。

协作类数据都带「归属人」：委托按委托人/受托人双向可见，通知只看收件箱，
Webhook 与 SLA 策略按所有者隔离；审计则跟随实例可见范围，管理员全量。
"""
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p, req_str
from workflow import services
from workflow.models import (
    NOTIFICATION_STATUS_CHOICES,
    WorkflowAuditLog,
    WorkflowDefinition,
    WorkflowDelegation,
    WorkflowNotification,
    WorkflowSlaPolicy,
    WorkflowWebhook,
)
from workflow.serializers import (apply_ordering, apply_q, apply_status,
                                  audit_dict, delegation_dict, notification_dict,
                                  paginate, sla_policy_dict, webhook_dict)
from workflow.views_common import get_instance, parse_ids, payload_list


def _parse_time(value, field):
    """解析 ISO 时间参数；空值返回 None，非法值抛中文错误。"""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是 ISO 时间字符串")
    parsed = parse_datetime(value.strip())
    if parsed is None:
        raise ValueError(f"{field} 格式不正确，应为 ISO 时间（如 2025-01-01T09:00:00）")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


# ---------------------------------------------------------------------------
# 委托
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def delegation_list(request):
    """委托列表：direction=out/in 控制方向，默认双向可见。"""
    qs = WorkflowDelegation.objects.select_related("from_user", "to_user", "definition", "owner")
    if not services.is_staff_user(request.user):
        direction = (request.query_params.get("direction") or "").strip()
        if direction == "out":
            qs = qs.filter(from_user=request.user)
        elif direction == "in":
            qs = qs.filter(to_user=request.user)
        else:
            qs = qs.filter(Q(from_user=request.user) | Q(to_user=request.user))
    qs = apply_q(qs, request, ["reason", "from_user__username", "to_user__username"])
    qs = apply_status(qs, request, "status", {"active", "revoked", "expired"})
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(request, qs, delegation_dict))


@endpoint()
def delegation_create(request):
    """创建委托：窗口合法、不能委托给自己、同一受托人不能重复生效。"""
    target = p(request, "to_user_id") or p(request, "to_user") or p(request, "target")
    if target in (None, ""):
        raise ValueError("缺少必填参数: to_user_id")
    to_user = services.resolve_user(target)
    definition = None
    definition_id = opt_num(request, "definition_id", integer=True)
    if definition_id:
        definition = WorkflowDefinition.objects.filter(pk=int(definition_id)).first()
        if definition is None:
            raise ValueError("流程定义不存在")
        services.ensure_definition_visible(definition, request.user)
    delegation = services.create_delegation(
        request.user,
        to_user,
        start_at=_parse_time(p(request, "start_at"), "start_at"),
        end_at=_parse_time(p(request, "end_at"), "end_at"),
        definition=definition,
        scope=opt_str(request, "scope", "all").strip() or "all",
        reason=opt_str(request, "reason"),
    )
    return ok(delegation_dict(delegation))


@endpoint()
def delegation_revoke(request, pk):
    """撤销委托：仅委托人本人或管理员。"""
    delegation = WorkflowDelegation.objects.select_related(
        "from_user", "to_user", "definition"
    ).filter(pk=pk).first()
    if delegation is None:
        raise ValueError("委托不存在")
    revoke = services.revoke_delegation(delegation, request.user)
    return ok(delegation_dict(revoke))


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def notification_list(request):
    """我的通知：支持 q / status / level / channel 过滤。"""
    qs = WorkflowNotification.objects.filter(recipient=request.user).select_related(
        "instance", "task", "recipient"
    )
    qs = apply_q(qs, request, ["title", "content"])
    status_filter = (request.query_params.get("status") or "").strip()
    if status_filter == "unread":
        qs = qs.exclude(status="read")
    elif status_filter == "read":
        qs = qs.filter(status="read")
    level = (request.query_params.get("level") or "").strip()
    if level in ("info", "success", "warning", "danger"):
        qs = qs.filter(level=level)
    channel = (request.query_params.get("channel") or "").strip()
    if channel in ("inapp", "email", "sms", "webhook", "im"):
        qs = qs.filter(channel=channel)
    qs = qs.order_by("-created_at", "-id")
    data = paginate(request, qs, notification_dict)
    data["unread"] = WorkflowNotification.objects.filter(
        recipient=request.user
    ).exclude(status="read").count()
    return ok(data)


@endpoint(("GET",))
def notification_summary(request):
    """通知汇总：未读数与按级别/渠道的分布（红点与分组用）。"""
    qs = WorkflowNotification.objects.filter(recipient=request.user)
    unread = qs.exclude(status="read")
    by_level = {row["level"]: row["c"] for row in unread.values("level").annotate(c=Count("id"))}
    return ok({
        "total": qs.count(),
        "unread": unread.count(),
        "by_level": by_level,
        "latest_at": qs.order_by("-created_at").values_list("created_at", flat=True).first(),
    })


@endpoint()
def notification_read(request):
    """批量标记通知已读：不传 ids 时全部已读。"""
    ids = parse_ids(request, "ids")
    count = services.mark_notifications_read(request.user, ids or None)
    return ok({"marked": count,
               "unread": WorkflowNotification.objects.filter(
                   recipient=request.user).exclude(status="read").count()})


@endpoint()
def notification_read_one(request, pk):
    """单条通知标记已读（只能操作自己的通知）。"""
    notification = WorkflowNotification.objects.filter(pk=pk).first()
    if notification is None:
        raise ValueError("通知不存在")
    if notification.recipient_id != request.user.id:
        raise ValueError("只能操作自己的通知")
    if notification.status != "read":
        notification.mark_read()
        notification.save(update_fields=["status", "read_at", "updated_at"])
    return ok(notification_dict(notification))


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def audit_instance(request, pk):
    """实例审计日志：按时间倒序，支持按动作过滤。"""
    instance = get_instance(pk, request.user)
    qs = instance.audit_logs.select_related("actor", "task").order_by("-created_at", "-id")
    action = (request.query_params.get("action") or "").strip()
    if action:
        qs = qs.filter(action__startswith=action)
    qs = apply_q(qs, request, ["action", "actor__username", "actor__display_name"])
    return ok(paginate(request, qs, audit_dict))


@endpoint(("GET",))
def audit_global(request):
    """全局审计：管理员全量，普通用户仅自己可见实例/自己发起/自己操作。"""
    qs = WorkflowAuditLog.objects.select_related(
        "actor", "instance", "task", "definition"
    )
    if not services.is_staff_user(request.user):
        visible = services.instance_queryset_for(request.user).values("id")
        qs = qs.filter(
            Q(instance_id__in=visible) | Q(definition__owner=request.user) |
            Q(actor=request.user)
        ).distinct()
    instance_id = opt_num(request, "instance_id", integer=True)
    if instance_id:
        qs = qs.filter(instance_id=int(instance_id))
    definition_id = opt_num(request, "definition_id", integer=True)
    if definition_id:
        qs = qs.filter(definition_id=int(definition_id))
    action = (request.query_params.get("action") or "").strip()
    if action:
        qs = qs.filter(action__startswith=action)
    qs = apply_q(qs, request, ["action", "actor__username", "instance__business_no"])
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(request, qs, audit_dict))


# ---------------------------------------------------------------------------
# Webhook（模拟投递，落库可查）
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def webhook_list(request):
    """Webhook 列表：非管理员只看自己的订阅。"""
    qs = WorkflowWebhook.objects.select_related("definition", "owner")
    if not services.is_staff_user(request.user):
        qs = qs.filter(owner=request.user)
    qs = apply_q(qs, request, ["name", "url"])
    active = p(request, "active")
    if active is not None:
        qs = qs.filter(active=opt_bool(request, "active", False))
    qs = qs.order_by("-created_at", "-id")
    return ok(paginate(request, qs, webhook_dict))


@endpoint()
def webhook_create(request):
    """创建 Webhook 订阅（仅 http/https，事件支持通配）。"""
    events = payload_list(request, "events", max_len=50)
    definition = None
    definition_id = opt_num(request, "definition_id", integer=True)
    if definition_id:
        definition = WorkflowDefinition.objects.filter(pk=int(definition_id)).first()
        if definition is None:
            raise ValueError("流程定义不存在")
        services.ensure_definition_visible(definition, request.user)
    webhook = services.create_webhook(
        request.user,
        name=req_str(request, "name"),
        url=req_str(request, "url"),
        events=events,
        definition=definition,
        secret=opt_str(request, "secret"),
    )
    return ok(webhook_dict(webhook))


@endpoint()
def webhook_update(request, pk):
    """更新 Webhook（启用/停用、改地址与事件）。"""
    webhook = WorkflowWebhook.objects.filter(pk=pk).first()
    if webhook is None:
        raise ValueError("Webhook 不存在")
    if webhook.owner_id != request.user.id and not services.is_staff_user(request.user):
        raise ValueError("只能修改自己的 Webhook")
    changed = []
    name = p(request, "name")
    if name is not None:
        value = str(name).strip()
        if not value:
            raise ValueError("Webhook 名称不能为空")
        webhook.name = value[:120]
        changed.append("name")
    url = p(request, "url")
    if url is not None:
        value = str(url).strip()
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("Webhook 地址必须是 http(s) 链接")
        webhook.url = value[:500]
        changed.append("url")
    events = p(request, "events")
    if events is not None:
        if not isinstance(events, list):
            raise ValueError("events 必须是数组")
        webhook.events = [str(x)[:80] for x in events[:50]]
        changed.append("events")
    active = p(request, "active")
    if active is not None:
        webhook.active = opt_bool(request, "active", webhook.active)
        changed.append("active")
    if not changed:
        raise ValueError("没有需要更新的字段")
    webhook.save()
    return ok(webhook_dict(webhook))


@endpoint()
def webhook_delete(request, pk):
    """删除 Webhook。"""
    webhook = WorkflowWebhook.objects.filter(pk=pk).first()
    if webhook is None:
        raise ValueError("Webhook 不存在")
    if webhook.owner_id != request.user.id and not services.is_staff_user(request.user):
        raise ValueError("只能删除自己的 Webhook")
    payload = {"id": webhook.id, "name": webhook.name}
    webhook.delete()
    return ok({"deleted": True, **payload})


# ---------------------------------------------------------------------------
# SLA 策略
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def sla_policy_list(request):
    """SLA 策略列表：非管理员只看自己的策略。"""
    qs = WorkflowSlaPolicy.objects.select_related("owner")
    if not services.is_staff_user(request.user):
        qs = qs.filter(owner=request.user)
    qs = apply_q(qs, request, ["code", "name", "description"])
    qs = apply_status(qs, request, "priority", {"low", "normal", "high", "urgent"})
    qs = apply_ordering(qs, request, ("priority", "response_minutes", "resolve_minutes",
                                      "created_at"), ("-created_at",))
    return ok(paginate(request, qs, sla_policy_dict))


@endpoint()
def sla_policy_create(request):
    """创建 SLA 策略：编码唯一、时限为正、解决时限不早于响应时限。"""
    policy = services.create_sla_policy(
        request.user,
        code=req_str(request, "code"),
        name=req_str(request, "name"),
        priority=opt_str(request, "priority", "normal").strip() or "normal",
        response_minutes=int(opt_num(request, "response_minutes", 240, integer=True)),
        resolve_minutes=int(opt_num(request, "resolve_minutes", 1440, integer=True)),
        business_hours=opt_bool(request, "business_hours", True),
        escalate_to=opt_str(request, "escalate_to", "manager").strip() or "manager",
        description=opt_str(request, "description"),
    )
    return ok(sla_policy_dict(policy))


# ---------------------------------------------------------------------------
# 表达式
# ---------------------------------------------------------------------------


@endpoint()
def expression_eval(request):
    """表达式诊断：返回是否合法、布尔结果与错误信息（设计器实时预览）。"""
    expression = req_str(request, "expression")
    context = p(request, "context")
    if context is not None and not isinstance(context, dict):
        raise ValueError("context 必须是对象")
    report = services.explain_condition(expression, context or {})
    raw = None
    if report["valid"]:
        raw = services.evaluate_expression(expression, context or {})
    return ok({**report, "raw": raw})
