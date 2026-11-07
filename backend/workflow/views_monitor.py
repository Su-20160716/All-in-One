# -*- coding: utf-8 -*-
"""流程引擎 · 监控接口（运行中实例 / SLA 扫描 / 指标 / 瓶颈 / 趋势）。

监控数据只做只读聚合，但必须遵守数据范围：非管理员只能看到自己可见范围内的
实例；SLA 扫描对管理员是全量，对普通用户只处理其可见实例，避免越权改状态。
"""
from django.db.models import Count, Q
from django.utils import timezone

from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str, p
from workflow import services
from workflow.models import TASK_OPEN_STATUS, WorkflowInstance, WorkflowTask
from workflow.serializers import (apply_q, instance_dict, paginate,
                                  parse_page_params, task_dict)
from workflow.views_common import visible_task_queryset


def _definition_id(request):
    """读取 definition_id 参数（可选）。"""
    value = opt_num(request, "definition_id", integer=True)
    return int(value) if value else None


@endpoint(("GET",))
def running_instances(request):
    """运行中实例：按停留时长倒序，附带活跃令牌与积压任务数。"""
    qs = services.instance_queryset_for(request.user).filter(status="running").select_related(
        "definition", "version", "owner", "starter", "current_node"
    )
    qs = apply_q(qs, request, ["business_no", "title", "definition__name"])
    definition_id = _definition_id(request)
    if definition_id:
        qs = qs.filter(definition_id=definition_id)
    if opt_bool(request, "overdue", False):
        qs = qs.filter(due_at__lt=timezone.now())
    qs = qs.order_by("started_at", "id")
    # 活跃令牌数用 annotation 一次算出，避免每行再查一次数据库。
    qs = qs.annotate(
        active_tokens_count=Count("tokens", filter=Q(tokens__status="active"))
    )
    data = paginate(request, qs, lambda obj: instance_dict(obj, user=request.user) | {
        "aging_minutes": obj.duration_minutes,
        "active_token_count": obj.active_tokens_count,
    })
    data["summary"] = {
        "running_total": data["count"],
        "overdue_total": qs.filter(due_at__lt=timezone.now()).count(),
        "unassigned_tasks": WorkflowTask.objects.filter(
            instance__in=qs, status="pending", assignee__isnull=True
        ).count(),
    }
    return ok(data)


@endpoint()
def sla_scan(request):
    """SLA 扫描：逾期标记、临期提醒、定时器触发、实例超期标记（幂等）。"""
    scope_user = None if services.is_staff_user(request.user) else request.user
    limit = int(opt_num(request, "limit", 500, minimum=1, maximum=2000, integer=True))
    counts = services.scan_sla(user=scope_user, limit=limit)
    return ok({"counts": counts, "scanned_at": timezone.now().isoformat()})


@endpoint(("GET",))
def metrics(request):
    """指标概览：完成率、平均耗时、任务健康度与 SLA 达成率。"""
    days = int(opt_num(request, "days", 30, minimum=1, maximum=365, integer=True))
    return ok(services.metrics_overview(
        user=request.user, definition_id=_definition_id(request), days=days
    ))


@endpoint(("GET",))
def status_distribution(request):
    """实例状态分布（含占比）。"""
    return ok(services.status_distribution(
        user=request.user, definition_id=_definition_id(request)
    ))


@endpoint(("GET",))
def category_distribution(request):
    """按分类的实例量与完成率。"""
    return ok(services.category_distribution(user=request.user))


@endpoint(("GET",))
def bottlenecks(request):
    """节点瓶颈 TOP N：平均办理时长、P90、积压与逾期。"""
    days = int(opt_num(request, "days", 90, minimum=1, maximum=365, integer=True))
    limit = int(opt_num(request, "limit", 10, minimum=1, maximum=50, integer=True))
    return ok(services.node_bottlenecks(
        user=request.user, definition_id=_definition_id(request), days=days, limit=limit
    ))


@endpoint(("GET",))
def trend(request):
    """趋势：逐日发起 / 完成 / 拒绝 / 任务完成量。"""
    days = int(opt_num(request, "days", 14, minimum=1, maximum=90, integer=True))
    return ok(services.trend(user=request.user, definition_id=_definition_id(request), days=days))


@endpoint(("GET",))
def dashboard(request):
    """监控大盘：一次返回概览、分布、趋势、瓶颈与我的待办数量。"""
    days = int(opt_num(request, "days", 30, minimum=1, maximum=365, integer=True))
    definition_id = _definition_id(request)
    my_open = visible_task_queryset(request.user).filter(status__in=TASK_OPEN_STATUS)
    my_pending = [task.id for task in my_open.select_related("instance", "node")
                  if task.is_candidate(request.user)]
    overdue_qs = visible_task_queryset(request.user).filter(status__in=TASK_OPEN_STATUS).filter(
        Q(is_overdue=True) | Q(due_at__lt=timezone.now())
    )
    return ok({
        "metrics": services.metrics_overview(
            user=request.user, definition_id=definition_id, days=days
        ),
        "status_distribution": services.status_distribution(
            user=request.user, definition_id=definition_id
        ),
        "category_distribution": services.category_distribution(user=request.user),
        "trend": services.trend(user=request.user, definition_id=definition_id, days=14),
        "bottlenecks": services.node_bottlenecks(
            user=request.user, definition_id=definition_id, days=days, limit=5
        ),
        "my": {
            "pending_count": len(my_pending),
            "overdue_count": overdue_qs.count(),
        },
        "staff": services.is_staff_user(request.user),
        "generated_at": timezone.now().isoformat(),
    })
