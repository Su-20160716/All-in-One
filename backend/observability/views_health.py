# -*- coding: utf-8 -*-
"""可观测性 · 处置面：运行手册(7) + 健康检查(7) = 14 个接口。

手册执行记录刻意落在本应用内（RunbookExecution），而不是对接外部工单系统：
约束要求「执行记录（本应用内记录步骤执行）」。每次执行都会：
1. 把手册步骤快照进执行记录（手册后续改版不影响历史）；
2. 逐步记录 status/notes（允许部分失败）；
3. 汇总执行状态并累加 executions_count（列表页不必展开步骤）。

健康检查同理：本应用不联网，`执行` 接口接受 agent 上报的结果或按配置
推断，把结果写入 HealthCheckRun 历史，并同步 HealthCheck 的当前状态与
连续失败次数。
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from devtools.common import endpoint, ok, opt_str, p, req_str

from observability import services
from observability.common import (
    bool_param,
    check_dict,
    check_run_dict,
    datetime_param,
    enum_param,
    execution_dict,
    filter_int,
    get_check,
    get_runbook,
    get_runbook_execution,
    int_param,
    list_param,
    page_params,
    paginate,
    runbook_dict,
    str_param,
    window_params,
)
from observability.models import (
    HEALTH_CHECK_TYPES,
    HEALTH_STATUS,
    RUNBOOK_EXEC_STATUS,
    RUNBOOK_STATUS,
    AlertRule,
    HealthCheck,
    HealthCheckRun,
    Incident,
    Runbook,
    RunbookExecution,
    Service,
)

# 单本手册的步骤上限：超过说明该拆成多本手册了
MAX_STEPS = 50


def _normalize_steps(raw):
    """步骤标准化：允许字符串或对象；对象必须带 title，其余字段原样保留。"""
    steps = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            title = item.strip()
            if title:
                steps.append({"order": index + 1, "title": title,
                              "command": "", "expect": ""})
            continue
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 个步骤必须是字符串或对象")
        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError(f"第 {index + 1} 个步骤缺少 title")
        steps.append({
            "order": index + 1,
            "title": title[:200],
            "command": str(item.get("command") or "")[:1000],
            "expect": str(item.get("expect") or "")[:500],
        })
    if not steps:
        raise ValueError("运行手册至少需要一个步骤")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"运行手册最多 {MAX_STEPS} 个步骤")
    return steps


# =====================================================================
# 运行手册（7）
# =====================================================================


@endpoint(("GET",))
def runbook_list(request):
    """运行手册列表：按服务/状态过滤，支持关键词检索名称与步骤标题。"""
    qs = services.visible(Runbook.objects.select_related("service").all(), request.user)
    qs = filter_int(qs, request, "service_id")
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(name__icontains=keyword) | Q(owner_name__icontains=keyword))
    return paginate(qs.order_by("-created_at"), request, runbook_dict)


@endpoint()
def runbook_create(request):
    """创建运行手册：步骤顺序即执行顺序，可关联服务与适用告警。"""
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("手册名称不能为空")
    service_id = int_param(request, "service_id")
    service = services.get_visible(Service, service_id, request.user,
                                   "服务不存在") if service_id else None
    if service is not None:
        services.ensure_writable(service, request.user)
    alert_rule_id = int_param(request, "alert_rule_id")
    alert_rule = None
    if alert_rule_id:
        alert_rule = services.get_visible(AlertRule, alert_rule_id, request.user,
                                          "告警规则不存在")
    steps = _normalize_steps(list_param(request, "steps", required=True, max_len=MAX_STEPS))
    status = opt_str(request, "status", "active").strip()
    if status not in RUNBOOK_STATUS:
        raise ValueError(f"手册状态必须是 {'/'.join(RUNBOOK_STATUS)} 之一")
    obj = Runbook.objects.create(
        owner=request.user,
        name=name,
        service=service,
        alert_rule=alert_rule,
        steps=steps,
        owner_name=str_param(request, "owner_name", max_len=80)
        or (getattr(request.user, "nickname", "") or request.user.username),
        version=opt_str(request, "version", "v1.0")[:20],
        status=status,
    )
    return ok(runbook_dict(obj))


@endpoint()
def runbook_update(request, pk=None):
    """更新运行手册：名称/关联/步骤/版本/状态。"""
    obj = get_runbook(pk or int_param(request, "id", required=True),
                      request.user, write=True)
    if p(request, "name") is not None:
        name = opt_str(request, "name").strip()
        if not name:
            raise ValueError("手册名称不能为空")
        obj.name = name[:120]
    if p(request, "service_id") is not None:
        service_id = int_param(request, "service_id")
        obj.service = services.get_visible(Service, service_id, request.user,
                                           "服务不存在") if service_id else None
    if p(request, "alert_rule_id") is not None:
        alert_rule_id = int_param(request, "alert_rule_id")
        obj.alert_rule = services.get_visible(AlertRule, alert_rule_id, request.user,
                                             "告警规则不存在") if alert_rule_id else None
    if p(request, "steps") is not None:
        obj.steps = _normalize_steps(list_param(request, "steps", required=True,
                                                max_len=MAX_STEPS))
    if p(request, "version") is not None:
        obj.version = opt_str(request, "version", obj.version)[:20]
    if p(request, "status") is not None:
        status = opt_str(request, "status", obj.status).strip()
        if status not in RUNBOOK_STATUS:
            raise ValueError(f"手册状态必须是 {'/'.join(RUNBOOK_STATUS)} 之一")
        obj.status = status
    if p(request, "owner_name") is not None:
        obj.owner_name = opt_str(request, "owner_name")[:80]
    obj.save()
    return ok(runbook_dict(obj))


@endpoint()
def runbook_delete(request, pk):
    """删除运行手册（执行历史一并删除）。"""
    obj = get_runbook(pk, request.user, write=True)
    obj.delete()
    return ok({"deleted": True, "id": pk})


@endpoint()
def runbook_execute(request, pk=None):
    """执行运行手册：逐步记录结果，汇总执行状态并累加执行次数。"""
    runbook = get_runbook(pk or int_param(request, "id", required=True),
                          request.user, write=True)
    if runbook.status == "retired":
        raise ValueError("已下线的手册不能执行")
    override = p(request, "results")
    if override is not None and not isinstance(override, list):
        raise ValueError("参数 results 必须是数组")
    results = {int(item.get("order") or item.get("index", 0)): item
               for item in (override or []) if isinstance(item, dict)}
    incident = None
    incident_id = int_param(request, "incident_id")
    if incident_id:
        incident = services.get_visible(Incident, incident_id, request.user,
                                        "事故不存在")
    now = timezone.now()
    steps = []
    has_failure = False
    for step in runbook.steps or []:
        order = int(step.get("order") or 0)
        result = results.get(order, {})
        status = str(result.get("status") or "succeeded").strip()
        if status not in RUNBOOK_EXEC_STATUS:
            raise ValueError(f"步骤状态必须是 {'/'.join(RUNBOOK_EXEC_STATUS)} 之一")
        has_failure = has_failure or status == "failed"
        steps.append({
            "order": order,
            "title": step.get("title", ""),
            "command": step.get("command", ""),
            "status": status,
            "notes": str(result.get("notes") or "")[:1000],
            "duration_seconds": result.get("duration_seconds"),
        })
    final_status = "failed" if has_failure else "succeeded"
    with transaction.atomic():
        execution = RunbookExecution.objects.create(
            owner=request.user,
            runbook=runbook,
            incident=incident,
            actor=request.user,
            steps=steps,
            status=final_status,
            started_at=now,
            finished_at=timezone.now(),
            note=opt_str(request, "note")[:300],
        )
        runbook.executions_count = int(runbook.executions_count or 0) + 1
        runbook.save(update_fields=["executions_count", "updated_at"])
    data = execution_dict(execution)
    data["failed"] = has_failure
    data["step_count"] = len(steps)
    return ok(data)


@endpoint(("GET",))
def runbook_executions(request, pk):
    """手册执行历史：按开始时间倒序分页（默认不返回逐步明细）。"""
    runbook = get_runbook(pk, request.user)
    qs = RunbookExecution.objects.select_related("runbook", "actor") \
        .filter(runbook=runbook).order_by("-started_at")
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    return paginate(qs, request, lambda obj: execution_dict(obj, with_steps=False))


@endpoint(("GET",))
def runbook_execution_detail(request, pk):
    """手册执行详情：含每一步的执行结果与备注。"""
    execution = get_runbook_execution(pk, request.user)
    return ok(execution_dict(execution, with_steps=True))


# =====================================================================
# 健康检查（7）
# =====================================================================


@endpoint(("GET",))
def health_check_list(request):
    """健康检查列表：按服务/类型/状态/启停过滤。"""
    qs = services.visible(HealthCheck.objects.select_related("service").all(), request.user)
    qs = filter_int(qs, request, "service_id")
    check_type = opt_str(request, "check_type").strip()
    if check_type:
        if check_type not in HEALTH_CHECK_TYPES:
            raise ValueError(f"检查类型必须是 {'/'.join(HEALTH_CHECK_TYPES)} 之一")
        qs = qs.filter(check_type=check_type)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    keyword = opt_str(request, "q").strip()
    if keyword:
        qs = qs.filter(Q(last_error__icontains=keyword))
    enabled = opt_str(request, "enabled").strip()
    if enabled:
        qs = qs.filter(enabled=enabled.lower() in ("1", "true", "yes", "on"))
    return paginate(qs.order_by("service_id", "id"), request, check_dict)


@endpoint()
def health_check_create(request):
    """创建健康检查：类型决定 config 形态，超时与间隔做范围校验。"""
    service = services.get_visible(Service, int_param(request, "service_id", required=True),
                                   request.user, "服务不存在")
    services.ensure_writable(service, request.user)
    check_type = opt_str(request, "check_type", "http").strip()
    if check_type not in HEALTH_CHECK_TYPES:
        raise ValueError(f"检查类型必须是 {'/'.join(HEALTH_CHECK_TYPES)} 之一")
    config = p(request, "config")
    if config is not None and not isinstance(config, dict):
        raise ValueError("参数 config 必须是对象")
    if not config:
        config = _default_config(check_type)
    status = opt_str(request, "status", "unknown").strip()
    if status not in HEALTH_STATUS:
        raise ValueError(f"健康状态必须是 {'/'.join(HEALTH_STATUS)} 之一")
    obj = HealthCheck.objects.create(
        owner=request.user,
        service=service,
        check_type=check_type,
        config=config,
        interval_seconds=int_param(request, "interval_seconds", 60,
                                   minimum=10, maximum=86400),
        timeout_seconds=int_param(request, "timeout_seconds", 5,
                                  minimum=1, maximum=300),
        status=status,
        enabled=bool_param(request, "enabled", True),
        weight=int_param(request, "weight", 1, minimum=1, maximum=10),
    )
    return ok(check_dict(obj))


def _default_config(check_type):
    """按检查类型给出最小可用配置，避免建了检查却缺少必需字段。"""
    if check_type == "http":
        return {"url": "", "method": "GET", "expect_status": "up"}
    if check_type == "tcp":
        return {"host": "", "port": 0, "expect_status": "up"}
    if check_type == "db":
        return {"engine": "sqlite", "query": "SELECT 1", "expect_status": "up"}
    return {"script": "", "expect_status": "up"}


@endpoint()
def health_check_update(request, pk=None):
    """更新健康检查：配置/间隔/超时/权重/启停。"""
    obj = get_check(pk or int_param(request, "id", required=True), request.user, write=True)
    if p(request, "check_type") is not None:
        check_type = opt_str(request, "check_type", obj.check_type).strip()
        if check_type not in HEALTH_CHECK_TYPES:
            raise ValueError(f"检查类型必须是 {'/'.join(HEALTH_CHECK_TYPES)} 之一")
        obj.check_type = check_type
    if p(request, "config") is not None:
        config = p(request, "config")
        if not isinstance(config, dict):
            raise ValueError("参数 config 必须是对象")
        obj.config = config
    if p(request, "interval_seconds") is not None:
        obj.interval_seconds = int_param(request, "interval_seconds",
                                        obj.interval_seconds, minimum=10, maximum=86400)
    if p(request, "timeout_seconds") is not None:
        obj.timeout_seconds = int_param(request, "timeout_seconds",
                                       obj.timeout_seconds, minimum=1, maximum=300)
    if p(request, "status") is not None:
        status = opt_str(request, "status", obj.status).strip()
        if status not in HEALTH_STATUS:
            raise ValueError(f"健康状态必须是 {'/'.join(HEALTH_STATUS)} 之一")
        obj.status = status
    if p(request, "enabled") is not None:
        obj.enabled = bool_param(request, "enabled", obj.enabled)
    if p(request, "weight") is not None:
        obj.weight = int_param(request, "weight", obj.weight, minimum=1, maximum=10)
    obj.save()
    return ok(check_dict(obj))


@endpoint()
def health_check_delete(request, pk):
    """删除健康检查（执行历史一并删除）。"""
    obj = get_check(pk, request.user, write=True)
    obj.delete()
    return ok({"deleted": True, "id": pk})


@endpoint()
def health_check_run(request, pk=None):
    """执行一次健康检查：记录结果与延迟，同步检查当前状态。"""
    check = get_check(pk or int_param(request, "id", required=True), request.user, write=True)
    succeed = p(request, "succeed")
    if succeed is not None:
        succeed = bool_param(request, "succeed", True)
    latency_ms = p(request, "latency_ms")
    run = services.execute_health_check(
        check,
        request.user,
        succeed=succeed,
        latency_ms=services.to_float(latency_ms, "latency_ms") if latency_ms not in (None, "") else None,
        error=opt_str(request, "error")[:300],
        detail=p(request, "detail") if isinstance(p(request, "detail"), dict) else {},
    )
    return ok({"run": check_run_dict(run), "check": check_dict(check),
               "health": services.health_score(list(check.service.health_checks.filter(
                   enabled=True)))})


@endpoint()
def health_check_run_all(request):
    """批量执行：按服务或全部可见服务跑一遍启用中的检查，汇总健康分。"""
    service_id = int_param(request, "service_id")
    qs = services.visible(HealthCheck.objects.select_related("service").filter(enabled=True),
                          request.user)
    if service_id:
        services.get_visible(Service, service_id, request.user, "服务不存在")
        qs = qs.filter(service_id=service_id)
    checks = list(qs.order_by("service_id", "id")[:200])
    if not checks:
        return ok({"total": 0, "items": [], "by_status": {},
                   "message": "没有启用中的健康检查"})
    succeed = p(request, "succeed")
    succeed = bool_param(request, "succeed", True) if succeed is not None else None
    results = []
    for check in checks:
        run = services.execute_health_check(check, request.user, succeed=succeed)
        results.append({"check_id": check.id, "service_id": check.service_id,
                        "status": run.status, "latency_ms": services.round4(run.latency_ms),
                        "error": run.error})
    by_status = {}
    for row in results:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    return ok({"total": len(results), "by_status": by_status, "items": results,
               "executed_at": services.iso(timezone.now())})


@endpoint(("GET",))
def health_check_history(request, pk):
    """检查历史：时间范围内的执行记录 + 可用率/延迟摘要。"""
    check = get_check(pk, request.user)
    since, until = window_params(request, default_hours=24 * 7)
    qs = HealthCheckRun.objects.filter(health_check=check, checked_at__gte=since,
                                       checked_at__lt=until).order_by("-checked_at")
    summary = services.health_check_runs_summary(check, since=since, until=until)
    page, size = page_params(request)
    total = qs.count()
    rows = [check_run_dict(obj) for obj in qs[(page - 1) * size:page * size]]
    return ok({"items": rows, "count": total, "page": page, "page_size": size,
               "summary": summary, "check": check_dict(check)})
