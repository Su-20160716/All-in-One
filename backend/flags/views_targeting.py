# -*- coding: utf-8 -*-
"""功能开关 · 细分/灰度/定向/变体接口（22 个）。

四组配置共同决定「谁会命中什么」：
- 细分（Segment + SegmentRule）：可复用的用户集合；
- 灰度（Rollout）：百分比 + 可选细分 + 时间窗口；
- 定向（TargetingRule）：优先级最高的条件规则，命中后直接给变体；
- 变体（Variant）：多变量开关的返回值与权重。

所有写操作都先校验父对象（开关/项目）权限，再落库，最后审计 + 清缓存。
"""
from django.db import IntegrityError, transaction

from devtools.common import endpoint, ok, opt_str, p, req_str

from flags import services
from flags.models import (
    LOGIC_OPS,
    OPERATORS,
    ROLLOUT_STATUS,
    Rollout,
    Segment,
    SegmentRule,
    TargetingRule,
    Variant,
)
from flags.views_common import (
    after_write,
    apply_search,
    bool_param,
    dict_param,
    filter_int,
    get_flag,
    get_rollout,
    get_segment,
    get_segment_rule,
    get_targeting_rule,
    get_variant,
    int_param,
    json_param,
    list_param,
    paginate,
    percent_param,
    str_param,
)
from flags.views_common import visible_flags


def _segment_from_request(request, write=False):
    segment_id = int_param(request, "segment_id", None, minimum=1)
    if not segment_id:
        segment_id = int_param(request, "id", None, minimum=1)
    if not segment_id:
        raise ValueError("缺少必填参数: segment_id")
    return get_segment(segment_id, request.user, write=write)


def _flag_from_request(request, write=True):
    flag_id = int_param(request, "flag_id", None, minimum=1)
    if not flag_id:
        flag_id = int_param(request, "id", None, minimum=1)
    if not flag_id:
        raise ValueError("缺少必填参数: flag_id")
    return get_flag(flag_id, request.user, write=write)


def _validate_rules(rows):
    """细分/定向条件统一校验并归一化。"""
    logic, conditions = services.normalize_conditions(rows or [], "and")
    for condition in conditions:
        services.validate_condition(condition)
    return logic, conditions


@transaction.atomic
def _replace_segment_rules(segment, rows, owner):
    """整体替换结构化规则（用于导入/批量编辑）。"""
    segment.segment_rules.all().delete()
    created = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, dict):
            raise ValueError("细分规则必须是对象")
        field = str(row.get("field") or "").strip()
        if not field:
            raise ValueError("细分规则缺少 field")
        operator = str(row.get("operator") or "eq").strip()
        if operator not in OPERATORS:
            raise ValueError(f"不支持的操作符: {operator}")
        services.validate_condition({"field": field, "operator": operator, "value": row.get("value")})
        created.append(SegmentRule.objects.create(
            owner=owner,
            segment=segment,
            field=field[:120],
            operator=operator,
            value=row.get("value"),
            logic=services.parse_choice(row.get("logic"), LOGIC_OPS, "规则组合", "and"),
            sort_order=services.parse_int(row.get("sort_order"), "排序", index * 10),
        ))
    return created


# =====================================================================
# 细分
# =====================================================================


@endpoint(("GET", "POST"))
def segments(request):
    """细分列表（GET）或创建细分（POST）。"""
    if request.method == "POST":
        from flags.views_common import get_project

        project_id = int_param(request, "project_id", None, minimum=1)
        if not project_id:
            raise ValueError("缺少必填参数: project_id")
        project = get_project(project_id, request.user, write=True)
        name = req_str(request, "name")[:120]
        rules = list_param(request, "rules", [], max_len=200)
        rule_match = services.parse_choice(p(request, "rule_match"), LOGIC_OPS, "规则组合", "and")
        _validate_rules(rules)
        try:
            with transaction.atomic():
                segment = Segment.objects.create(
                    owner=request.user,
                    project=project,
                    name=name,
                    description=opt_str(request, "description"),
                    rules=rules,
                    rule_match=rule_match,
                )
                _replace_segment_rules(
                    segment, list_param(request, "segment_rules", [], max_len=200), request.user
                )
        except IntegrityError:
            raise ValueError("同一项目下细分名称已存在")
        after_write(request.user, segment, "segment.create", after={"name": name},
                    project=project)
        return ok(segment.as_dict())

    qs = services.visible(Segment.objects.all(), request.user)
    qs = filter_int(qs, request, "project_id")
    qs = apply_search(qs, request, ["name", "description"], status_field=None)
    return paginate(qs.order_by("-created_at", "-id"), request, lambda obj: obj.as_dict())


@endpoint(("GET",))
def segment_detail(request, pk):
    """细分详情（含结构化规则、引用它的灰度）。"""
    segment = get_segment(pk, request.user)
    data = segment.as_dict()
    data["segment_rules"] = [item.as_dict() for item in segment.segment_rules.all()]
    data["rollouts"] = [item.as_dict() for item in segment.rollouts.all().order_by("id")]
    data["matched_count"] = segment.member_count
    return ok(data)


@endpoint()
def segment_update(request):
    """更新细分名称/描述/JSON 规则/组合方式。"""
    segment = _segment_from_request(request, write=True)
    before = segment.as_dict()
    if p(request, "name") not in (None, ""):
        segment.name = req_str(request, "name")[:120]
    if p(request, "description") not in (None, ""):
        segment.description = opt_str(request, "description")
    if p(request, "rules") not in (None, ""):
        rules = list_param(request, "rules", [], max_len=200)
        _validate_rules(rules)
        segment.rules = rules
    if p(request, "rule_match") not in (None, ""):
        segment.rule_match = services.parse_choice(
            p(request, "rule_match"), LOGIC_OPS, "规则组合", segment.rule_match
        )
    try:
        with transaction.atomic():
            segment.save()
            if p(request, "segment_rules") not in (None, ""):
                _replace_segment_rules(
                    segment, list_param(request, "segment_rules", [], max_len=200), request.user
                )
    except IntegrityError:
        raise ValueError("同一项目下细分名称已存在")
    after_write(request.user, segment, "segment.update", before=before,
                after=segment.as_dict(), project=segment.project)
    return ok(segment.as_dict())


@endpoint()
def segment_delete(request):
    """删除细分（引用它的灰度会置空 segment，不影响开关本身）。"""
    segment = _segment_from_request(request, write=True)
    snapshot = segment.as_dict()
    project = segment.project
    with transaction.atomic():
        services.record_audit(
            request.user, segment, "segment.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        segment.delete()
    return ok({"deleted": True, "id": snapshot["id"]})


@endpoint()
def segment_preview(request):
    """细分预览：对一批上下文求命中并刷新成员数缓存。"""
    segment = _segment_from_request(request, write=False)
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
        user_key = str(p(request, "user_key") or "preview-1")
        contexts.append(services.normalize_context(user_key, context))
    return ok(services.preview_segment(segment, contexts))


# =====================================================================
# 细分规则
# =====================================================================


@endpoint(("GET", "POST"))
def segment_rules(request):
    """细分规则列表（GET）或新增规则（POST）。"""
    segment = _segment_from_request(request, write=request.method == "POST")
    if request.method == "POST":
        field = req_str(request, "field")[:120]
        operator = services.parse_choice(p(request, "operator"), OPERATORS, "操作符", "eq")
        value = p(request, "value")
        services.validate_condition({"field": field, "operator": operator, "value": value})
        rule = SegmentRule.objects.create(
            owner=request.user,
            segment=segment,
            field=field,
            operator=operator,
            value=value,
            logic=services.parse_choice(p(request, "logic"), LOGIC_OPS, "规则组合", "and"),
            sort_order=int_param(request, "sort_order", segment.segment_rules.count() * 10),
        )
        after_write(request.user, rule, "segment_rule.create",
                    after=rule.as_dict(), project=segment.project)
        return ok(rule.as_dict())

    qs = segment.segment_rules.all().order_by("sort_order", "id")
    qs = apply_search(qs, request, ["field", "operator"], status_field=None)
    return paginate(qs, request, lambda obj: obj.as_dict())


@endpoint()
def segment_rule_update(request):
    """更新细分规则字段/操作符/值/逻辑/排序。"""
    rule = get_segment_rule(
        int_param(request, "rule_id", None, minimum=1) or int_param(request, "id", None, minimum=1),
        request.user,
        write=True,
    )
    before = rule.as_dict()
    if p(request, "field") not in (None, ""):
        rule.field = req_str(request, "field")[:120]
    if p(request, "operator") not in (None, ""):
        rule.operator = services.parse_choice(
            p(request, "operator"), OPERATORS, "操作符", rule.operator
        )
    if p(request, "value") is not None:
        rule.value = p(request, "value")
    if p(request, "logic") not in (None, ""):
        rule.logic = services.parse_choice(p(request, "logic"), LOGIC_OPS, "规则组合", rule.logic)
    if p(request, "sort_order") not in (None, ""):
        rule.sort_order = int_param(request, "sort_order", rule.sort_order)
    services.validate_condition(
        {"field": rule.field, "operator": rule.operator, "value": rule.value}
    )
    rule.save()
    after_write(request.user, rule, "segment_rule.update", before=before,
                after=rule.as_dict(), project=rule.segment.project)
    return ok(rule.as_dict())


@endpoint()
def segment_rule_delete(request):
    """删除细分规则。"""
    rule = get_segment_rule(
        int_param(request, "rule_id", None, minimum=1) or int_param(request, "id", None, minimum=1),
        request.user,
        write=True,
    )
    snapshot = rule.as_dict()
    project = rule.segment.project
    with transaction.atomic():
        services.record_audit(
            request.user, rule, "segment_rule.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        rule.delete()
    return ok({"deleted": True, "id": snapshot["id"]})


# =====================================================================
# 灰度
# =====================================================================


@endpoint(("GET", "POST"))
def rollouts(request):
    """灰度列表（GET）或创建灰度（POST）。"""
    if request.method == "POST":
        flag = _flag_from_request(request, write=True)
        percentage = percent_param(request, "percentage", 0)
        segment_id = int_param(request, "segment_id", None, minimum=1)
        segment = None
        if segment_id:
            segment = get_segment(segment_id, request.user)
            if segment.project_id != flag.project_id:
                raise ValueError("细分不属于该开关所在项目")
        start_at = services.parse_datetime(p(request, "start_at"), "开始时间", services.now())
        end_at = services.parse_datetime(p(request, "end_at"), "结束时间")
        if start_at and end_at and end_at <= start_at:
            raise ValueError("结束时间必须晚于开始时间")
        status = services.parse_choice(p(request, "status"), ROLLOUT_STATUS, "灰度状态", "running")
        rollout = Rollout.objects.create(
            owner=request.user,
            flag=flag,
            percentage=percentage,
            segment=segment,
            salt=opt_str(request, "salt")[:120],
            start_at=start_at,
            end_at=end_at,
            status=status,
        )
        after_write(request.user, rollout, "rollout.create",
                    after={"percentage": percentage, "segment_id": segment_id},
                    project=flag.project)
        return ok(rollout.as_dict())

    qs = Rollout.objects.select_related("flag", "segment").all()
    flag_ids = visible_flags(request.user).values_list("id", flat=True)
    qs = qs.filter(flag_id__in=flag_ids)
    qs = filter_int(qs, request, "flag_id")
    qs = filter_int(qs, request, "project_id", "flag__project_id")
    status = opt_str(request, "status").strip()
    if status:
        if status not in ROLLOUT_STATUS:
            raise ValueError(f"灰度状态必须是 {'/'.join(ROLLOUT_STATUS)} 之一")
        qs = qs.filter(status=status)
    return paginate(qs.order_by("-created_at", "-id"), request, lambda obj: obj.as_dict())


@endpoint()
def rollout_update(request):
    """更新灰度百分比/细分/时间窗口/状态。"""
    rollout_id = int_param(request, "rollout_id", None, minimum=1)
    if not rollout_id:
        rollout_id = int_param(request, "id", None, minimum=1)
    if not rollout_id:
        raise ValueError("缺少必填参数: rollout_id")
    rollout = get_rollout(rollout_id, request.user, write=True)
    before = rollout.as_dict()
    if p(request, "percentage") not in (None, ""):
        rollout.percentage = percent_param(request, "percentage", rollout.percentage)
    if p(request, "salt") not in (None, ""):
        rollout.salt = opt_str(request, "salt")[:120]
    if p(request, "status") not in (None, ""):
        rollout.status = services.parse_choice(
            p(request, "status"), ROLLOUT_STATUS, "灰度状态", rollout.status
        )
    if p(request, "segment_id") not in (None, ""):
        segment_id = int_param(request, "segment_id", None, minimum=1)
        if segment_id:
            segment = get_segment(segment_id, request.user)
            if segment.project_id != rollout.flag.project_id:
                raise ValueError("细分不属于该开关所在项目")
            rollout.segment = segment
        else:
            rollout.segment = None
    for field, label in (("start_at", "开始时间"), ("end_at", "结束时间")):
        if p(request, field) not in (None, ""):
            setattr(rollout, field, services.parse_datetime(p(request, field), label))
    if rollout.start_at and rollout.end_at and rollout.end_at <= rollout.start_at:
        raise ValueError("结束时间必须晚于开始时间")
    rollout.save()
    after_write(request.user, rollout, "rollout.update", before=before,
                after=rollout.as_dict(), project=rollout.flag.project)
    return ok(rollout.as_dict())


@endpoint()
def rollout_toggle(request):
    """暂停/恢复灰度（恢复时若已过期则直接置 completed）。"""
    rollout_id = int_param(request, "rollout_id", None, minimum=1)
    if not rollout_id:
        raise ValueError("缺少必填参数: rollout_id")
    rollout = get_rollout(rollout_id, request.user, write=True)
    before = {"status": rollout.status}
    if p(request, "status") not in (None, ""):
        rollout.status = services.parse_choice(
            p(request, "status"), ("running", "paused", "completed"), "灰度状态", rollout.status
        )
    else:
        rollout.status = "paused" if rollout.status == "running" else "running"
    if rollout.status == "running" and rollout_state_expired(rollout):
        rollout.status = "completed"
    rollout.save(update_fields=["status", "updated_at"])
    after_write(request.user, rollout, "rollout.toggle", before=before,
                after={"status": rollout.status}, project=rollout.flag.project)
    return ok(rollout.as_dict())


def rollout_state_expired(rollout):
    """恢复灰度时判断窗口是否已结束，避免恢复一个永远不会生效的灰度。"""
    moment = services.now()
    return bool(rollout.end_at and moment >= rollout.end_at)


@endpoint()
def rollout_advance(request):
    """推进灰度百分比（只增不减，100% 自动完成）。"""
    rollout_id = int_param(request, "rollout_id", None, minimum=1)
    if not rollout_id:
        raise ValueError("缺少必填参数: rollout_id")
    rollout = get_rollout(rollout_id, request.user, write=True)
    before = {"percentage": rollout.percentage, "status": rollout.status}
    target = p(request, "target")
    delta = p(request, "delta")
    if target in (None, "") and delta in (None, ""):
        delta = 10
    services.advance_rollout(rollout, delta=delta, target=target)
    after_write(
        request.user,
        rollout,
        "rollout.advance",
        before=before,
        after={"percentage": rollout.percentage, "status": rollout.status},
        project=rollout.flag.project,
    )
    return ok(rollout.as_dict())


# =====================================================================
# 定向规则
# =====================================================================


@endpoint(("GET", "POST"))
def targeting_rules(request):
    """定向规则列表（GET）或新增规则（POST）。"""
    flag = _flag_from_request(request, write=request.method == "POST")
    if request.method == "POST":
        conditions = list_param(request, "conditions", [], max_len=100)
        logic_conditions = services.normalize_conditions(
            conditions, p(request, "condition_logic") or "and"
        )
        for condition in logic_conditions[1]:
            services.validate_condition(condition)
        variant_key = opt_str(request, "variant_key").strip()[:80]
        if variant_key and flag.flag_type == "multivariate":
            if not flag.variants.filter(key=variant_key).exists():
                raise ValueError(f"变体不存在: {variant_key}")
        if variant_key and flag.flag_type == "boolean":
            if variant_key.lower() not in ("true", "false", "on", "off", "1", "0"):
                raise ValueError("布尔开关的定向变体只能是 true/false")
        priority = int_param(request, "priority", None)
        if priority is None:
            last = flag.targeting_rules.order_by("-priority").values_list(
                "priority", flat=True).first()
            priority = (last or 0) + 10
        if flag.targeting_rules.filter(priority=priority).exists():
            raise ValueError(f"优先级 {priority} 已被占用")
        rule = TargetingRule.objects.create(
            owner=request.user,
            flag=flag,
            priority=priority,
            conditions=logic_conditions[1],
            condition_logic=logic_conditions[0],
            variant_key=variant_key,
            percentage=percent_param(request, "percentage", 100),
            enabled=bool_param(request, "enabled", True),
            note=opt_str(request, "note")[:200],
        )
        after_write(request.user, rule, "targeting.create", after=rule.as_dict(),
                    project=flag.project)
        return ok(rule.as_dict())

    qs = flag.targeting_rules.all().order_by("priority", "id")
    qs = apply_search(qs, request, ["variant_key", "note"], status_field=None)
    return paginate(qs, request, lambda obj: obj.as_dict())


@endpoint()
def targeting_rule_update(request):
    """更新定向规则条件/变体/百分比/启用。"""
    rule_id = int_param(request, "rule_id", None, minimum=1)
    if not rule_id:
        rule_id = int_param(request, "id", None, minimum=1)
    if not rule_id:
        raise ValueError("缺少必填参数: rule_id")
    rule = get_targeting_rule(rule_id, request.user, write=True)
    before = rule.as_dict()
    if p(request, "conditions") not in (None, ""):
        conditions = list_param(request, "conditions", [], max_len=100)
        logic_conditions = services.normalize_conditions(
            conditions, p(request, "condition_logic") or rule.condition_logic
        )
        for condition in logic_conditions[1]:
            services.validate_condition(condition)
        rule.conditions = logic_conditions[1]
        rule.condition_logic = logic_conditions[0]
    if p(request, "variant_key") not in (None, ""):
        variant_key = opt_str(request, "variant_key").strip()[:80]
        if variant_key and rule.flag.flag_type == "multivariate":
            if not rule.flag.variants.filter(key=variant_key).exists():
                raise ValueError(f"变体不存在: {variant_key}")
        if variant_key and rule.flag.flag_type == "boolean":
            if variant_key.lower() not in ("true", "false", "on", "off", "1", "0"):
                raise ValueError("布尔开关的定向变体只能是 true/false")
        rule.variant_key = variant_key
    if p(request, "percentage") not in (None, ""):
        rule.percentage = percent_param(request, "percentage", rule.percentage)
    if p(request, "enabled") not in (None, ""):
        rule.enabled = bool_param(request, "enabled", rule.enabled)
    if p(request, "note") not in (None, ""):
        rule.note = opt_str(request, "note")[:200]
    if p(request, "priority") not in (None, ""):
        priority = int_param(request, "priority", rule.priority)
        if flag_targeting_conflict(rule, priority):
            raise ValueError(f"优先级 {priority} 已被占用")
        rule.priority = priority
    rule.save()
    after_write(request.user, rule, "targeting.update", before=before,
                after=rule.as_dict(), project=rule.flag.project)
    return ok(rule.as_dict())


def flag_targeting_conflict(rule, priority):
    return rule.flag.targeting_rules.exclude(pk=rule.pk).filter(priority=priority).exists()


@endpoint()
def targeting_rule_delete(request):
    """删除定向规则。"""
    rule_id = int_param(request, "rule_id", None, minimum=1)
    if not rule_id:
        raise ValueError("缺少必填参数: rule_id")
    rule = get_targeting_rule(rule_id, request.user, write=True)
    snapshot = rule.as_dict()
    project = rule.flag.project
    with transaction.atomic():
        services.record_audit(
            request.user, rule, "targeting.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        rule.delete()
    return ok({"deleted": True, "id": snapshot["id"]})


@endpoint()
def targeting_rule_reorder(request):
    """按 id 数组重排定向规则优先级（10/20/30...）。"""
    flag = _flag_from_request(request, write=True)
    ids = list_param(request, "ids", [], max_len=200)
    parsed = []
    for raw in ids:
        value = services.parse_int(raw, "规则ID", minimum=1)
        parsed.append(value)
    if len(set(parsed)) != len(parsed):
        raise ValueError("规则ID重复")
    existing = set(flag.targeting_rules.values_list("id", flat=True))
    unknown = [item for item in parsed if item not in existing]
    if unknown:
        raise ValueError(f"规则不属于该开关: {unknown[:5]}")
    with transaction.atomic():
        # 先把目标规则挪到负数优先级，避免与现有 10/20/30 撞唯一约束
        for offset, rule_id in enumerate(parsed):
            flag.targeting_rules.filter(pk=rule_id).update(priority=-(offset + 1))
        for index, rule_id in enumerate(parsed):
            flag.targeting_rules.filter(pk=rule_id).update(priority=(index + 1) * 10)
    services.invalidate_flag(flag.id)
    services.record_audit(request.user, flag, "targeting.reorder",
                          after={"ids": parsed}, project=flag.project)
    return ok({
        "flag_id": flag.id,
        "ids": parsed,
        "rules": [item.as_dict() for item in flag.targeting_rules.all().order_by("priority", "id")],
    })


@endpoint()
def targeting_rule_toggle(request):
    """启用/停用定向规则。"""
    rule_id = int_param(request, "rule_id", None, minimum=1)
    if not rule_id:
        raise ValueError("缺少必填参数: rule_id")
    rule = get_targeting_rule(rule_id, request.user, write=True)
    before = {"enabled": rule.enabled}
    rule.enabled = bool_param(request, "enabled", not rule.enabled)
    rule.save(update_fields=["enabled", "updated_at"])
    after_write(request.user, rule, "targeting.toggle", before=before,
                after={"enabled": rule.enabled}, project=rule.flag.project)
    return ok(rule.as_dict())


# =====================================================================
# 变体
# =====================================================================


@endpoint(("GET", "POST"))
def variants(request):
    """变体列表（GET）或新增变体（POST）。"""
    flag = _flag_from_request(request, write=request.method == "POST")
    if request.method == "POST":
        key = services.parse_key(req_str(request, "key"), "变体键")
        weight = int_param(request, "weight", 0, minimum=0, maximum=100)
        payload = dict_param(request, "payload", {})
        try:
            # 保存点回滚，避免唯一约束错误破坏外层事务
            with transaction.atomic():
                variant = Variant.objects.create(
                    owner=request.user,
                    flag=flag,
                    key=key,
                    name=opt_str(request, "name", key)[:120] or key,
                    weight=weight,
                    payload=payload,
                )
        except IntegrityError:
            raise ValueError("该开关下变体键已存在")
        after_write(request.user, variant, "variant.create", after=variant.as_dict(),
                    project=flag.project)
        return ok(variant.as_dict())

    qs = flag.variants.all().order_by("id")
    return paginate(qs, request, lambda obj: obj.as_dict())


@endpoint()
def variant_update(request):
    """更新变体名称/权重/负载。"""
    variant_id = int_param(request, "variant_id", None, minimum=1)
    if not variant_id:
        variant_id = int_param(request, "id", None, minimum=1)
    if not variant_id:
        raise ValueError("缺少必填参数: variant_id")
    variant = get_variant(variant_id, request.user, write=True)
    before = variant.as_dict()
    if p(request, "name") not in (None, ""):
        variant.name = req_str(request, "name")[:120]
    if p(request, "weight") not in (None, ""):
        variant.weight = int_param(request, "weight", variant.weight, minimum=0, maximum=100)
    if p(request, "payload") not in (None, ""):
        variant.payload = dict_param(request, "payload", {})
    if p(request, "key") not in (None, ""):
        variant.key = services.parse_key(p(request, "key"), "变体键")
    try:
        # 保存点回滚，避免唯一约束错误破坏外层事务
        with transaction.atomic():
            variant.save()
    except IntegrityError:
        raise ValueError("该开关下变体键已存在")
    after_write(request.user, variant, "variant.update", before=before,
                after=variant.as_dict(), project=variant.flag.project)
    return ok(variant.as_dict())


@endpoint()
def variant_delete(request):
    """删除变体（定向规则引用该变体时请先改规则）。"""
    variant_id = int_param(request, "variant_id", None, minimum=1)
    if not variant_id:
        raise ValueError("缺少必填参数: variant_id")
    variant = get_variant(variant_id, request.user, write=True)
    if variant.flag.targeting_rules.filter(variant_key=variant.key).exists():
        raise ValueError("仍有定向规则引用该变体，请先调整规则")
    snapshot = variant.as_dict()
    project = variant.flag.project
    with transaction.atomic():
        services.record_audit(
            request.user, variant, "variant.delete", before=snapshot,
            after={"deleted": True}, project=project,
        )
        variant.delete()
    return ok({"deleted": True, "id": snapshot["id"]})


@endpoint()
def variant_weight(request):
    """调整变体权重：支持单条 weight 或 weights 映射/数组批量调整。"""
    flag = _flag_from_request(request, write=True)
    before = [item.as_dict() for item in flag.variants.all().order_by("id")]
    raw = p(request, "weights")
    updated = []
    with transaction.atomic():
        if raw not in (None, ""):
            rows = json_param(request, "weights", [])
            if isinstance(rows, dict):
                rows = [{"key": key, "weight": value} for key, value in rows.items()]
            if not isinstance(rows, list):
                raise ValueError("weights 必须是对象或数组")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("weights 的每一项必须是对象")
                key = services.parse_key(row.get("key"), "变体键")
                weight = services.parse_int(row.get("weight"), "权重", 0, minimum=0, maximum=100)
                variant = flag.variants.filter(key=key).first()
                if variant is None:
                    raise ValueError(f"变体不存在: {key}")
                variant.weight = weight
                variant.save(update_fields=["weight", "updated_at"])
                updated.append(variant)
        else:
            variant_id = int_param(request, "variant_id", None, minimum=1)
            if not variant_id:
                raise ValueError("缺少必填参数: weights 或 variant_id")
            variant = get_variant(variant_id, request.user, write=True)
            if variant.flag_id != flag.id:
                raise ValueError("变体不属于该开关")
            variant.weight = int_param(
                request, "weight", variant.weight, minimum=0, maximum=100
            )
            variant.save(update_fields=["weight", "updated_at"])
            updated.append(variant)
    after_write(request.user, flag, "variant.weight", before={"variants": before},
                after={"variants": [item.as_dict() for item in updated]},
                project=flag.project)
    return ok({
        "flag_id": flag.id,
        "updated": [item.as_dict() for item in updated],
        "variants": [item.as_dict() for item in flag.variants.all().order_by("id")],
    })
