# -*- coding: utf-8 -*-
"""功能开关 · 治理接口（15 个）：受众、依赖、护栏、审计。

治理能力回答三个问题：
- 给谁看：Audience 定义可复用受众，可先预览再引用；
- 能不能开：FlagDependency 约束上下游，写入时做环检测；
- 出事怎么办：Guardrail 监控指标，超阈值按动作处置并写审计。
"""
from django.db import IntegrityError, transaction

from devtools.common import endpoint, ok, opt_str, p, req_str

from flags import services
from flags.models import (
    DEPENDENCY_RELATIONS,
    GUARDRAIL_ACTIONS,
    LOGIC_OPS,
    OPERATORS,
    AuditEvent,
    Audience,
    Flag,
    FlagDependency,
    Guardrail,
    Project,
)
from flags.views_common import (
    after_write,
    apply_search,
    bool_param,
    filter_int,
    get_audience,
    get_dependency,
    get_flag,
    get_guardrail,
    get_project,
    int_param,
    json_param,
    list_param,
    paginate,
    str_param,
)


def _validate_rules(rows):
    logic, conditions = services.normalize_conditions(rows or [], "and")
    for condition in conditions:
        services.validate_condition(condition)
    return logic, conditions


def _preview_contexts(request):
    """预览上下文归一：数组优先，单个 context 次之，最多 500 条。"""
    raw = p(request, "contexts")
    contexts = []
    if raw not in (None, ""):
        rows = json_param(request, "contexts", [])
        if not isinstance(rows, list):
            raise ValueError("contexts 必须是数组")
        if len(rows) > 500:
            raise ValueError("单次预览最多 500 个上下文")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError("contexts 的每一项必须是对象")
            user_key = str(row.get("user_key") or (row.get("user") or {}).get("id") or f"c{index}")
            contexts.append(services.normalize_context(user_key, row))
    else:
        context = json_param(request, "context", {}) or {}
        if not isinstance(context, dict):
            raise ValueError("context 必须是对象")
        contexts.append(services.normalize_context(
            str(p(request, "user_key") or "preview-1"), context
        ))
    return contexts


# =====================================================================
# 受众
# =====================================================================


@endpoint(("GET", "POST"))
def audiences(request):
    """受众列表（GET）或创建受众（POST）。"""
    if request.method == "POST":
        project_id = int_param(request, "project_id", None, minimum=1)
        if not project_id:
            raise ValueError("缺少必填参数: project_id")
        project = get_project(project_id, request.user, write=True)
        name = req_str(request, "name")[:120]
        rules = list_param(request, "rules", [], max_len=200)
        logic, _conditions = _validate_rules(rules)
        rule_logic = services.parse_choice(
            p(request, "rule_logic"), LOGIC_OPS, "规则组合", logic
        )
        try:
            # 保存点回滚，避免唯一约束错误破坏外层事务
            with transaction.atomic():
                audience = Audience.objects.create(
                    owner=request.user,
                    project=project,
                    name=name,
                    rules=rules,
                    rule_logic=rule_logic,
                    description=opt_str(request, "description"),
                )
        except IntegrityError:
            raise ValueError("同一项目下受众名称已存在")
        after_write(request.user, audience, "audience.create", after=audience.as_dict(),
                    project=project)
        return ok(audience.as_dict())

    qs = services.visible(Audience.objects.all(), request.user)
    qs = filter_int(qs, request, "project_id")
    qs = apply_search(qs, request, ["name", "description"], status_field=None)
    return paginate(qs.order_by("-created_at", "-id"), request, lambda obj: obj.as_dict())


@endpoint(("GET",))
def audience_detail(request, pk):
    """受众详情（含规则字段清单与成员数缓存）。"""
    audience = get_audience(pk, request.user)
    data = audience.as_dict()
    data["fields"] = services.condition_fields(audience.rules or [])
    data["operator_count"] = len(OPERATORS)
    return ok(data)


@endpoint()
def audience_update(request):
    """更新受众名称/规则/组合方式/描述。"""
    audience_id = int_param(request, "audience_id", None, minimum=1)
    if not audience_id:
        audience_id = int_param(request, "id", None, minimum=1)
    if not audience_id:
        raise ValueError("缺少必填参数: audience_id")
    audience = get_audience(audience_id, request.user, write=True)
    before = audience.as_dict()
    if p(request, "name") not in (None, ""):
        audience.name = req_str(request, "name")[:120]
    if p(request, "description") not in (None, ""):
        audience.description = opt_str(request, "description")
    if p(request, "rules") not in (None, ""):
        rules = list_param(request, "rules", [], max_len=200)
        _validate_rules(rules)
        audience.rules = rules
    if p(request, "rule_logic") not in (None, ""):
        audience.rule_logic = services.parse_choice(
            p(request, "rule_logic"), LOGIC_OPS, "规则组合", audience.rule_logic
        )
    try:
        # 保存点回滚，避免唯一约束错误破坏外层事务
        with transaction.atomic():
            audience.save()
    except IntegrityError:
        raise ValueError("同一项目下受众名称已存在")
    after_write(request.user, audience, "audience.update", before=before,
                after=audience.as_dict(), project=audience.project)
    return ok(audience.as_dict())


@endpoint()
def audience_delete(request):
    """删除受众。"""
    audience_id = int_param(request, "audience_id", None, minimum=1)
    if not audience_id:
        raise ValueError("缺少必填参数: audience_id")
    audience = get_audience(audience_id, request.user, write=True)
    snapshot = audience.as_dict()
    project = audience.project
    with transaction.atomic():
        services.record_audit(
            request.user, audience, "audience.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        audience.delete()
    return ok({"deleted": True, "id": snapshot["id"]})


@endpoint()
def audience_preview(request):
    """受众预览：对一批上下文求命中并刷新成员数缓存。"""
    audience_id = int_param(request, "audience_id", None, minimum=1)
    if not audience_id:
        audience_id = int_param(request, "id", None, minimum=1)
    if not audience_id:
        raise ValueError("缺少必填参数: audience_id")
    audience = get_audience(audience_id, request.user)
    contexts = _preview_contexts(request)
    logic, conditions = services.normalize_conditions(
        audience.rules or [], audience.rule_logic
    )
    rows = []
    hits = 0
    for context in contexts:
        matched = services.evaluate_conditions(conditions, context, logic)
        if matched:
            hits += 1
        rows.append({
            "user_key": context.get("user_key"),
            "matched": matched,
            "conditions": services.explain_conditions(conditions, context, logic)["conditions"],
        })
    audience.member_count = hits
    audience.save(update_fields=["member_count", "updated_at"])
    return ok({
        "audience_id": audience.id,
        "name": audience.name,
        "total": len(rows),
        "hits": hits,
        "misses": len(rows) - hits,
        "items": rows,
    })


# =====================================================================
# 依赖
# =====================================================================


@endpoint(("GET", "POST"))
def dependencies(request):
    """依赖列表（GET）或新增依赖（POST，写入时检测自依赖与成环）。"""
    if request.method == "POST":
        flag_id = int_param(request, "flag_id", None, minimum=1)
        depends_on_id = int_param(request, "depends_on_id", None, minimum=1)
        if not flag_id or not depends_on_id:
            raise ValueError("缺少必填参数: flag_id / depends_on_id")
        flag = get_flag(flag_id, request.user, write=True)
        depends_on = get_flag(depends_on_id, request.user)
        if flag.project_id != depends_on.project_id:
            raise ValueError("依赖双方必须属于同一项目")
        if flag.id == depends_on.id:
            raise ValueError("开关不能依赖自身")
        relation = services.parse_choice(
            p(request, "relation"), DEPENDENCY_RELATIONS, "依赖关系", "requires"
        )
        if services.would_create_cycle(flag, depends_on):
            raise ValueError("依赖关系会形成环，已拒绝")
        try:
            with transaction.atomic():
                dep = FlagDependency.objects.create(
                    owner=request.user,
                    flag=flag,
                    depends_on=depends_on,
                    expected_value=p(request, "expected_value"),
                    relation=relation,
                )
        except IntegrityError:
            raise ValueError("该依赖关系已存在")
        after_write(request.user, dep, "dependency.create", after=dep.as_dict(),
                    project=flag.project)
        return ok(dep.as_dict())

    flag_ids = services.visible(Flag.objects.all(), request.user).values_list("id", flat=True)
    qs = FlagDependency.objects.select_related("flag", "depends_on").filter(
        flag_id__in=flag_ids)
    qs = filter_int(qs, request, "flag_id")
    qs = filter_int(qs, request, "project_id", "flag__project_id")
    keyword = opt_str(request, "q").strip()
    if keyword:
        from django.db.models import Q

        qs = qs.filter(Q(flag__key__icontains=keyword) | Q(depends_on__key__icontains=keyword))
    return paginate(qs.order_by("id"), request, lambda obj: obj.as_dict())


@endpoint(("GET",))
def dependency_detail(request, pk):
    """依赖详情。"""
    dep = get_dependency(pk, request.user)
    data = dep.as_dict()
    data["flag"] = dep.flag.as_dict()
    data["depends_on"] = dep.depends_on.as_dict()
    return ok(data)


@endpoint()
def dependency_update(request):
    """更新依赖关系/期望值（变更目标时重新做环检测）。"""
    dep_id = int_param(request, "dependency_id", None, minimum=1)
    if not dep_id:
        dep_id = int_param(request, "id", None, minimum=1)
    if not dep_id:
        raise ValueError("缺少必填参数: dependency_id")
    dep = get_dependency(dep_id, request.user, write=True)
    before = dep.as_dict()
    if p(request, "relation") not in (None, ""):
        dep.relation = services.parse_choice(
            p(request, "relation"), DEPENDENCY_RELATIONS, "依赖关系", dep.relation
        )
    if p(request, "depends_on_id") not in (None, ""):
        target = get_flag(
            services.parse_int(p(request, "depends_on_id"), "depends_on_id", minimum=1),
            request.user,
        )
        if target.project_id != dep.flag.project_id:
            raise ValueError("依赖双方必须属于同一项目")
        if target.id == dep.flag_id:
            raise ValueError("开关不能依赖自身")
        if services.would_create_cycle(dep.flag, target):
            raise ValueError("依赖关系会形成环，已拒绝")
        dep.depends_on = target
    if p(request, "expected_value") is not None:
        dep.expected_value = p(request, "expected_value")
    try:
        # 保存点回滚，避免唯一约束错误破坏外层事务
        with transaction.atomic():
            dep.save()
    except IntegrityError:
        raise ValueError("该依赖关系已存在")
    after_write(request.user, dep, "dependency.update", before=before,
                after=dep.as_dict(), project=dep.flag.project)
    return ok(dep.as_dict())


@endpoint()
def dependency_delete(request):
    """删除依赖。"""
    dep_id = int_param(request, "dependency_id", None, minimum=1)
    if not dep_id:
        raise ValueError("缺少必填参数: dependency_id")
    dep = get_dependency(dep_id, request.user, write=True)
    snapshot = dep.as_dict()
    project = dep.flag.project
    with transaction.atomic():
        services.record_audit(
            request.user, dep, "dependency.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        dep.delete()
    services.invalidate_flag(snapshot["flag_id"])
    return ok({"deleted": True, "id": snapshot["id"]})


@endpoint(("GET",))
def dependency_graph(request):
    """项目依赖图：节点 + 边 + 环列表。"""
    project_id = int_param(request, "project_id", None, minimum=1)
    if not project_id:
        raise ValueError("缺少必填参数: project_id")
    project = get_project(project_id, request.user)
    data = services.dependency_graph(project)
    flag_map = {
        item.id: item.key
        for item in services.visible(Flag.objects.filter(project=project), request.user)
    }
    data["cycle_keys"] = [
        [flag_map.get(flag_id, str(flag_id)) for flag_id in cycle]
        for cycle in data["cycles"]
    ]
    return ok(data)


@endpoint(("GET", "POST"))
def dependency_check_cycles(request):
    """检测项目内依赖环（支持 GET 查询与 POST）。"""
    project_id = int_param(request, "project_id", None, minimum=1)
    if not project_id:
        raise ValueError("缺少必填参数: project_id")
    project = get_project(project_id, request.user)
    cycles = services.detect_cycles(project)
    key_map = dict(Flag.objects.filter(project=project).values_list("id", "key"))
    rows = [
        {
            "flag_ids": cycle,
            "flag_keys": [key_map.get(item, str(item)) for item in cycle],
        }
        for cycle in cycles
    ]
    return ok({
        "project_id": project.id,
        "has_cycle": bool(rows),
        "count": len(rows),
        "cycles": rows,
    })


# =====================================================================
# 护栏
# =====================================================================


@endpoint(("GET", "POST"))
def guardrails(request):
    """护栏列表（GET）或新增护栏（POST）。"""
    if request.method == "POST":
        flag_id = int_param(request, "flag_id", None, minimum=1)
        if not flag_id:
            raise ValueError("缺少必填参数: flag_id")
        flag = get_flag(flag_id, request.user, write=True)
        metric = req_str(request, "metric")[:120]
        action = services.parse_choice(
            p(request, "action"), GUARDRAIL_ACTIONS, "触发动作", "notify"
        )
        comparator = str(p(request, "comparator") or "gte").strip()
        if comparator not in ("gte", "lte", "gt", "lt"):
            raise ValueError("comparator 必须是 gte/lte/gt/lt 之一")
        # 没有阈值的护栏永远不会触发，属于无效配置，必须显式提供
        threshold = services.parse_float(
            p(request, "threshold"), "阈值", None, minimum=0
        )
        if threshold is None:
            raise ValueError("缺少必填参数: threshold")
        try:
            with transaction.atomic():
                guardrail = Guardrail.objects.create(
                    owner=request.user,
                    flag=flag,
                    metric=metric,
                    threshold=threshold,
                    window_minutes=int_param(
                        request, "window_minutes", 60, minimum=1, maximum=10080
                    ),
                    action=action,
                    comparator=comparator,
                )
        except IntegrityError:
            raise ValueError("该开关下已存在同名指标的护栏")
        after_write(request.user, guardrail, "guardrail.create",
                    after=guardrail.as_dict(), project=flag.project)
        return ok(guardrail.as_dict())

    flag_ids = services.visible(Flag.objects.all(), request.user).values_list("id", flat=True)
    qs = Guardrail.objects.select_related("flag").filter(flag_id__in=flag_ids)
    qs = filter_int(qs, request, "flag_id")
    qs = filter_int(qs, request, "project_id", "flag__project_id")
    qs = apply_search(qs, request, ["metric"], status_field=None)
    return paginate(qs.order_by("id"), request, lambda obj: obj.as_dict())


@endpoint()
def guardrail_update(request):
    """更新护栏阈值/窗口/动作/比较方向。"""
    guardrail_id = int_param(request, "guardrail_id", None, minimum=1)
    if not guardrail_id:
        guardrail_id = int_param(request, "id", None, minimum=1)
    if not guardrail_id:
        raise ValueError("缺少必填参数: guardrail_id")
    guardrail = get_guardrail(guardrail_id, request.user, write=True)
    before = guardrail.as_dict()
    if p(request, "metric") not in (None, ""):
        guardrail.metric = req_str(request, "metric")[:120]
    if p(request, "threshold") not in (None, ""):
        guardrail.threshold = services.parse_float(p(request, "threshold"), "阈值", 0)
    if p(request, "window_minutes") not in (None, ""):
        guardrail.window_minutes = int_param(
            request, "window_minutes", guardrail.window_minutes, minimum=1, maximum=10080
        )
    if p(request, "action") not in (None, ""):
        guardrail.action = services.parse_choice(
            p(request, "action"), GUARDRAIL_ACTIONS, "触发动作", guardrail.action
        )
    if p(request, "comparator") not in (None, ""):
        comparator = str(p(request, "comparator")).strip()
        if comparator not in ("gte", "lte", "gt", "lt"):
            raise ValueError("comparator 必须是 gte/lte/gt/lt 之一")
        guardrail.comparator = comparator
    try:
        # 保存点回滚，避免唯一约束错误破坏外层事务
        with transaction.atomic():
            guardrail.save()
    except IntegrityError:
        raise ValueError("该开关下已存在同名指标的护栏")
    after_write(request.user, guardrail, "guardrail.update", before=before,
                after=guardrail.as_dict(), project=guardrail.flag.project)
    return ok(guardrail.as_dict())


@endpoint()
def guardrail_delete(request):
    """删除护栏。"""
    guardrail_id = int_param(request, "guardrail_id", None, minimum=1)
    if not guardrail_id:
        raise ValueError("缺少必填参数: guardrail_id")
    guardrail = get_guardrail(guardrail_id, request.user, write=True)
    snapshot = guardrail.as_dict()
    project = guardrail.flag.project
    with transaction.atomic():
        services.record_audit(
            request.user, guardrail, "guardrail.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        guardrail.delete()
    return ok({"deleted": True, "id": snapshot["id"]})


@endpoint()
def guardrail_check(request):
    """护栏检查：接受 readings 对象或 metric+value，超阈值按动作处置。"""
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    flag = get_flag(flag_id, request.user, write=True)
    raw = p(request, "readings")
    if raw not in (None, ""):
        readings = json_param(request, "readings", {})
        # 兼容数组写法 [{"metric": "latency", "value": 900}]，便于批量上报
        if isinstance(readings, list):
            merged = {}
            for row in readings:
                if not isinstance(row, dict):
                    raise ValueError("readings 数组的每一项必须是对象")
                metric = str(row.get("metric") or "").strip()
                if not metric:
                    raise ValueError("readings 每一项必须包含 metric")
                merged[metric] = row.get("value")
            readings = merged
    else:
        metric = opt_str(request, "metric").strip()
        if not metric:
            raise ValueError("缺少必填参数: readings 或 metric/value")
        value = p(request, "value")
        if value in (None, ""):
            raise ValueError("缺少必填参数: value")
        readings = {metric: value}
    if not isinstance(readings, dict) or not readings:
        raise ValueError("护栏读数不能为空")
    result = services.check_guardrails(flag, readings, actor=request.user)
    flag.refresh_from_db()
    result["flag_status"] = flag.status
    return ok(result)


# =====================================================================
# 审计
# =====================================================================


@endpoint(("GET",))
def audit_events(request):
    """审计日志列表：按项目/对象/动作/操作者搜索。"""
    qs = services.visible(AuditEvent.objects.all(), request.user)
    qs = filter_int(qs, request, "project_id")
    object_type = opt_str(request, "object_type").strip()
    if object_type:
        qs = qs.filter(object_type=object_type)
    object_id = p(request, "object_id")
    if object_id not in (None, ""):
        qs = qs.filter(object_id=services.parse_int(object_id, "object_id", minimum=0))
    action = opt_str(request, "action").strip()
    if action:
        qs = qs.filter(action__startswith=action)
    qs = apply_search(qs, request, ["actor_name", "action", "note", "object_type"],
                      status_field=None)
    return paginate(qs.order_by("-created_at", "-id"), request, lambda obj: obj.as_dict())
