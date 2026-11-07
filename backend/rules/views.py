# -*- coding: utf-8 -*-
"""rules · 接口层：规则集 / 版本 / 规则 / 条件 / 动作 / 变量。

约定（与平台其他应用一致）：
- @endpoint 统一兜底异常，ValueError → 400，其余 → 422；
- 列表统一 items/count/page/page_size，q/status/page/page_size 由服务层 helper 收口；
- 写接口先做 owner 校验（core.scoping.can_write），读接口走数据范围可见性；
- 每个接口一行中文 docstring，参数语义写在注释里，不写空话。
"""
import json

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from core.scoping import can_write, is_visible, owner_qs, scope_queryset
from devtools.common import (endpoint, endpoint_index, fail, ok, opt_bool,
                             opt_num, opt_str, p, req, req_num, req_str)
from rules import services
from rules.expressions import (MAX_DEPTH, MAX_EXPR_LEN, MAX_VARIABLES,
                               ExprError, combine_conditions,
                               condition_expression, function_catalog,
                               operator_catalog, validate_expression,
                               validate_path)
from rules.models import (ACTION_TYPES, CONFLICT_SEVERITIES, CONFLICT_STATUS,
                          CONFLICT_TYPES, CONDITION_OPERATORS, HIT_POLICIES,
                          HIT_POLICY_LABELS, RULESET_STATUS, RULESET_STATUS_LABELS,
                          VARIABLE_TYPES, DecisionRow, Rule, RuleAction,
                          RuleApproval, RuleCondition, RuleConflict,
                          RuleDecisionTable, RuleEvaluation, RuleExecutionLog,
                          RuleNotification, RuleSchedule, RuleSet,
                          RuleSetVersion, RuleSimulation, RuleTag, RuleTask,
                          RuleTemplate, RuleTestCase, RuleVariable)


# ---------------------------------------------------------------------------
# 通用入参 helper
# ---------------------------------------------------------------------------


def _payload(request):
    return request.data if isinstance(request.data, dict) else {}


def _has(request, key):
    return key in _payload(request) or key in request.query_params


def _pk(value, name="id"):
    return services.as_int(value, name, minimum=1)


def _list_arg(request, key, default=None, max_items=200, expect=None):
    """列表入参：兼容 JSON 字符串与原生数组，顺带限制条数。"""
    value = p(request, key, default)
    if value is None:
        return None
    value = services.parse_json_arg(value, key, list)
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_items:
        raise ValueError(f"参数 {key} 最多 {max_items} 项")
    if expect is not None:
        for index, item in enumerate(value):
            if not isinstance(item, expect):
                raise ValueError(f"参数 {key} 第 {index + 1} 项格式不正确")
    return value


def _dict_arg(request, key, default=None):
    value = p(request, key, default)
    if value is None:
        return None
    return services.parse_json_arg(value, key, dict)


def _ruleset(request, pk=None, write=False):
    return services.resolve_ruleset(request, pk=pk, write=write)


def _version(request, pk):
    version = services.get_visible(RuleSetVersion, request, pk, message="版本不存在")
    if not is_visible(version.ruleset, request.user) and not getattr(
            request.user, "is_staff", False):
        raise ValueError("无权访问该版本")
    return version


def _rule_payload(request, rule=None, ruleset=None):
    """创建/更新规则的公共解析：条件表达式与动作都在这里做一次语法校验。"""
    data = {}
    if ruleset is not None:
        data["ruleset"] = ruleset
    name = opt_str(request, "name", rule.name if rule else "", max_len=200).strip()
    if not name:
        raise ValueError("缺少必填参数: name")
    data["name"] = name
    data["description"] = opt_str(
        request, "description", rule.description if rule else "", max_len=500)
    data["priority"] = int(opt_num(request, "priority", rule.priority if rule else 100,
                                   minimum=-100000, maximum=100000, integer=True))
    data["enabled"] = opt_bool(request, "enabled", rule.enabled if rule else True)
    condition = opt_str(request, "condition", rule.condition if rule else "",
                        max_len=MAX_EXPR_LEN)
    condition = condition.strip()
    if condition:
        report = validate_expression(condition)
        if not report["valid"]:
            raise ValueError(f"条件表达式非法: {report['error']}")
        if report["depth"] > MAX_DEPTH:
            raise ValueError(f"条件表达式嵌套超过上限 {MAX_DEPTH} 层")
        if len(report["variables"]) > MAX_VARIABLES:
            raise ValueError(f"条件表达式变量数超过上限 {MAX_VARIABLES}")
    data["condition"] = condition
    tags = _list_arg(request, "tags", max_items=50)
    if tags is not None:
        data["tags"] = services.to_json(tags)
    actions = _list_arg(request, "actions", max_items=50)
    if actions is not None:
        data["actions"] = services.normalize_actions(actions)
    return data


def _write_rule_children(rule, conditions, action_items):
    """重建规则的可视化条件/动作行：整体替换比逐行 diff 更符合前端保存语义。"""
    if conditions is not None:
        rule.conditions.all().delete()
        for index, item in enumerate(conditions):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index + 1} 个条件格式不正确")
            field = str(item.get("field") or "").strip()
            if not field:
                raise ValueError(f"第 {index + 1} 个条件缺少 field")
            operator = str(item.get("operator") or "==")
            if operator not in CONDITION_OPERATORS:
                raise ValueError(f"第 {index + 1} 个条件操作符不支持: {operator}")
            try:
                condition_expression(field, operator, item.get("value"),
                                     item.get("logic_group") or "and")
            except ExprError as e:
                raise ValueError(f"第 {index + 1} 个条件非法: {e}")
            RuleCondition.objects.create(
                owner=rule.owner, rule=rule, field=field[:200],
                operator=operator[:20], value=services.to_json(item.get("value")),
                logic_group=(str(item.get("logic_group") or "and").lower())[:3],
                sort_order=int(item.get("sort_order", index)),
                enabled=bool(item.get("enabled", True)),
            )
    if action_items is not None:
        rule.action_items.all().delete()
        for index, item in enumerate(action_items):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index + 1} 个动作格式不正确")
            action_type = str(item.get("type") or "").strip()
            if action_type not in ACTION_TYPES:
                raise ValueError(f"第 {index + 1} 个动作类型不支持: {action_type or '(空)'}")
            params = item.get("params") if isinstance(item.get("params"), dict) else {
                k: v for k, v in item.items() if k not in ("type", "id", "sort_order", "enabled")
            }
            RuleAction.objects.create(
                owner=rule.owner, rule=rule, type=action_type,
                params=services.to_json(params), sort_order=int(item.get("sort_order", index)),
                enabled=bool(item.get("enabled", True)),
            )


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def catalog(request):
    """规则引擎目录：枚举、操作符、函数、限制与全部接口清单。"""
    from rules.urls import urlpatterns

    endpoints = endpoint_index(urlpatterns)
    return ok({
        "app": "rules",
        "name": "业务规则引擎",
        "version": "1.0",
        "statuses": [{"value": s, "label": RULESET_STATUS_LABELS.get(s, s)}
                     for s in RULESET_STATUS],
        "hit_policies": [{"value": s, "label": HIT_POLICY_LABELS.get(s, s)}
                         for s in HIT_POLICIES],
        "action_types": list(ACTION_TYPES),
        "operators": operator_catalog(),
        "condition_operators": list(CONDITION_OPERATORS),
        "functions": function_catalog(),
        "variable_types": list(VARIABLE_TYPES),
        "conflict_types": list(CONFLICT_TYPES),
        "limits": {
            "expression_length": MAX_EXPR_LEN,
            "expression_depth": MAX_DEPTH,
            "expression_variables": MAX_VARIABLES,
            "page_size": 200,
            "batch_evaluate": 200,
            "simulation_facts": 500,
        },
        "endpoints": endpoints,
        "endpoint_count": len(endpoints),
    })


# ---------------------------------------------------------------------------
# 规则集
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def rulesets(request):
    """规则集列表 / 新建规则集。"""
    if request.method == "GET":
        qs = scope_queryset(RuleSet.objects.all(), request.user)
        qs = services.apply_q(qs, opt_str(request, "q"), ["code", "name", "category", "description"])
        status = opt_str(request, "status").strip()
        if status:
            if status not in RULESET_STATUS:
                raise ValueError(f"不支持的状态: {status}")
            qs = qs.filter(status=status)
        category = opt_str(request, "category").strip()
        if category:
            qs = qs.filter(category=category)
        page, size = services.page_args(request)
        return ok(services.paginate(qs.order_by("-updated_at", "-id"), page, size,
                                    services.ruleset_dict))
    code = req_str(request, "code", max_len=64).strip()
    if not all(ch.isalnum() or ch in "_-." for ch in code):
        raise ValueError("规则集编码只能包含字母、数字、下划线、短横线与点")
    name = req_str(request, "name", max_len=200).strip()
    status = opt_str(request, "status", "draft").strip()
    if status not in RULESET_STATUS:
        raise ValueError(f"不支持的状态: {status}")
    hit_policy = opt_str(request, "hit_policy", "first").strip()
    if hit_policy not in HIT_POLICIES:
        raise ValueError(f"不支持的命中策略: {hit_policy}")
    tags = _list_arg(request, "tags", [], max_items=50) or []
    settings = _dict_arg(request, "settings") or {}
    with transaction.atomic():
        if RuleSet.objects.filter(owner=request.user, code=code).exists():
            raise ValueError(f"规则集编码 {code} 已存在")
        ruleset = RuleSet.objects.create(
            owner=request.user, code=code, name=name,
            category=opt_str(request, "category", "自定义", max_len=60).strip() or "自定义",
            description=opt_str(request, "description"),
            status=status, hit_policy=hit_policy,
            max_executions=int(opt_num(request, "max_executions", 100,
                                       minimum=1, maximum=1000, integer=True)),
            timeout_ms=int(opt_num(request, "timeout_ms", 2000,
                                   minimum=50, maximum=60000, integer=True)),
            priority=int(opt_num(request, "priority", 0,
                                 minimum=-100000, maximum=100000, integer=True)),
            tags=services.to_json(tags), settings=services.to_json(settings),
        )
    return ok(services.ruleset_dict(ruleset, detail=True))


@endpoint(("GET", "POST"))
def ruleset_detail(request, pk):
    """规则集详情 / 更新规则集配置。"""
    ruleset = _ruleset(request, pk, write=request.method == "POST")
    if request.method == "GET":
        data = services.ruleset_dict(ruleset, detail=True)
        data["rules"] = [services.rule_dict(r) for r in
                         ruleset.rules.order_by("priority", "id")[:200]]
        data["variables"] = [services.variable_dict(v) for v in ruleset.variables.all()]
        data["decision_tables"] = [services.table_dict(t) for t in
                                   ruleset.decision_tables.all()[:50]]
        return ok(data)
    name = opt_str(request, "name", ruleset.name, max_len=200).strip()
    if not name:
        raise ValueError("规则集名称不能为空")
    status = opt_str(request, "status", ruleset.status).strip()
    if status not in RULESET_STATUS:
        raise ValueError(f"不支持的状态: {status}")
    hit_policy = opt_str(request, "hit_policy", ruleset.hit_policy).strip()
    if hit_policy not in HIT_POLICIES:
        raise ValueError(f"不支持的命中策略: {hit_policy}")
    tags = _list_arg(request, "tags", None, max_items=50)
    settings = _dict_arg(request, "settings")
    ruleset.name = name
    ruleset.category = opt_str(request, "category", ruleset.category, max_len=60).strip() or "自定义"
    ruleset.description = opt_str(request, "description", ruleset.description)
    ruleset.status = status
    ruleset.hit_policy = hit_policy
    ruleset.max_executions = int(opt_num(request, "max_executions", ruleset.max_executions,
                                         minimum=1, maximum=1000, integer=True))
    ruleset.timeout_ms = int(opt_num(request, "timeout_ms", ruleset.timeout_ms,
                                     minimum=50, maximum=60000, integer=True))
    ruleset.priority = int(opt_num(request, "priority", ruleset.priority,
                                   minimum=-100000, maximum=100000, integer=True))
    if tags is not None:
        ruleset.tags = services.to_json(tags)
    if settings is not None:
        ruleset.settings = services.to_json(settings)
    ruleset.save()
    return ok(services.ruleset_dict(ruleset, detail=True))


@endpoint()
def ruleset_delete(request, pk):
    """删除规则集及其全部规则、版本、调度（级联）。"""
    ruleset = _ruleset(request, pk, write=True)
    ruleset_id, code = ruleset.id, ruleset.code
    with transaction.atomic():
        ruleset.delete()
    return ok({"id": ruleset_id, "code": code, "deleted": True})


@endpoint()
def ruleset_publish(request, pk):
    """发布规则集：生成版本快照并置为生效中。"""
    ruleset = _ruleset(request, pk, write=True)
    report = services.validate_ruleset(ruleset)
    if not report["valid"] and not opt_bool(request, "force", False):
        raise ValueError("规则集校验未通过，修复后再发布（或传 force=true 强制发布）")
    version = services.publish_ruleset(ruleset, request.user,
                                       opt_str(request, "note", "发布版本"))
    ruleset.refresh_from_db()
    return ok({"ruleset": services.ruleset_dict(ruleset), "version": services.version_dict(version),
               "validation": report})


@endpoint()
def ruleset_pause(request, pk):
    """暂停规则集：调度扫描会跳过 paused 状态。"""
    ruleset = _ruleset(request, pk, write=True)
    if ruleset.status == "archived":
        raise ValueError("已归档规则集请先恢复为草稿再暂停")
    ruleset.status = "paused"
    ruleset.save(update_fields=["status", "updated_at"])
    return ok(services.ruleset_dict(ruleset))


@endpoint()
def ruleset_archive(request, pk):
    """归档规则集：保留数据但不再参与任何自动执行。"""
    ruleset = _ruleset(request, pk, write=True)
    ruleset.status = "archived"
    ruleset.save(update_fields=["status", "updated_at"])
    return ok(services.ruleset_dict(ruleset))


@endpoint()
def ruleset_clone(request, pk):
    """克隆规则集为本人名下的新草稿。"""
    ruleset = _ruleset(request, pk, write=False)
    cloned = services.clone_ruleset(ruleset, request.user,
                                    opt_str(request, "name", "", max_len=200))
    return ok(services.ruleset_dict(cloned, detail=True))


@endpoint(("GET", "POST"))
def ruleset_validate(request, pk):
    """静态校验规则集：表达式、动作参数、变量引用与决策表结构。"""
    ruleset = _ruleset(request, pk)
    return ok(services.validate_ruleset(ruleset))


@endpoint(("GET",))
def ruleset_export(request, pk):
    """导出规则集快照（JSON，可用于导入或版本对比）。"""
    ruleset = _ruleset(request, pk)
    return ok(services.ruleset_snapshot(ruleset))


@endpoint()
def ruleset_import(request):
    """导入规则集快照；编码冲突需显式 overwrite=true。"""
    payload = p(request, "snapshot")
    if payload is None:
        body = _payload(request)
        if "ruleset" in body or "rules" in body:
            payload = body
    if payload is None:
        raise ValueError("缺少必填参数: snapshot")
    ruleset = services.import_ruleset(request.user, payload,
                                      overwrite=opt_bool(request, "overwrite", False))
    return ok(services.ruleset_dict(ruleset, detail=True))


@endpoint()
def ruleset_rollback(request, pk):
    """回滚到历史版本（会把回滚动作记为新的版本）。"""
    ruleset = _ruleset(request, pk, write=True)
    version_id = p(request, "version_id")
    version_no = p(request, "version_no")
    if version_id not in (None, ""):
        version = ruleset.versions.filter(pk=version_id).first()
    elif version_no not in (None, ""):
        version = ruleset.versions.filter(version_no=version_no).first()
    else:
        raise ValueError("缺少必填参数: version_id 或 version_no")
    if version is None:
        raise ValueError("版本不存在")
    snapshot = services.rollback_ruleset(ruleset, version, request.user)
    ruleset.refresh_from_db()
    return ok({"ruleset": services.ruleset_dict(ruleset), "snapshot": snapshot})


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def versions_list(request, pk):
    """规则集的版本列表（倒序，支持分页）。"""
    ruleset = _ruleset(request, pk)
    qs = ruleset.versions.all()
    q = opt_str(request, "q").strip()
    if q:
        qs = qs.filter(Q(note__icontains=q))
    page, size = services.page_args(request)
    return ok(services.paginate(qs.order_by("-version_no", "-id"), page, size,
                                services.version_dict))


@endpoint(("GET",))
def version_detail(request, pk):
    """版本详情（含完整快照）。"""
    version = _version(request, pk)
    return ok(services.version_dict(version, include_snapshot=True))


@endpoint(("GET",))
def versions_compare(request):
    """对比两个版本：规则/变量/决策表的增删改。"""
    left_id = p(request, "left_id") or p(request, "a")
    right_id = p(request, "right_id") or p(request, "b")
    if left_id in (None, "") or right_id in (None, ""):
        raise ValueError("缺少必填参数: left_id / right_id")
    left = _version(request, _pk(left_id, "left_id"))
    right = _version(request, _pk(right_id, "right_id"))
    if left.ruleset_id != right.ruleset_id:
        raise ValueError("只能对比同一规则集的两个版本")
    return ok(services.compare_versions(left, right))


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------


def _rule_obj(request, pk, write=False):
    return services.get_visible(Rule, request, pk, write=write, message="规则不存在")


@endpoint(("GET", "POST"))
def rules(request):
    """规则列表 / 新建规则。"""
    if request.method == "GET":
        qs = scope_queryset(Rule.objects.all(), request.user)
        if p(request, "ruleset_id") not in (None, ""):
            ruleset = _ruleset(request, p(request, "ruleset_id"))
            qs = qs.filter(ruleset=ruleset)
        qs = services.apply_q(qs, opt_str(request, "q"), ["name", "description", "condition"])
        status = opt_str(request, "status").strip()
        if status in ("enabled", "active", "1", "true"):
            qs = qs.filter(enabled=True)
        elif status in ("disabled", "inactive", "0", "false"):
            qs = qs.filter(enabled=False)
        elif status:
            raise ValueError(f"不支持的规则状态过滤: {status}")
        tag = opt_str(request, "tag").strip()
        if tag:
            qs = qs.filter(tags__contains=tag)
        page, size = services.page_args(request)
        return ok(services.paginate(qs.order_by("ruleset_id", "priority", "id"),
                                    page, size, services.rule_dict))
    ruleset = _ruleset(request, None, write=True)
    data = _rule_payload(request, ruleset=ruleset)
    conditions = _list_arg(request, "conditions", None, max_items=100, expect=dict)
    action_items = _list_arg(request, "action_items", None, max_items=50, expect=dict)
    if not data["condition"] and conditions:
        try:
            composed = combine_conditions(conditions)
        except ExprError as e:
            raise ValueError(f"条件配置错误: {e}")
        report = validate_expression(composed)
        if not report["valid"]:
            raise ValueError(f"条件表达式非法: {report['error']}")
    with transaction.atomic():
        rule = Rule.objects.create(owner=request.user, **data)
        _write_rule_children(rule, conditions or [], action_items or [])
    return ok(services.rule_dict(rule, detail=True))


@endpoint(("GET", "POST"))
def rule_detail(request, pk):
    """规则详情 / 更新规则（含条件与动作行整体替换）。"""
    rule = _rule_obj(request, pk, write=request.method == "POST")
    if request.method == "GET":
        return ok(services.rule_dict(rule, detail=True))
    data = _rule_payload(request, rule=rule, ruleset=rule.ruleset)
    conditions = _list_arg(request, "conditions", None, max_items=100, expect=dict)
    action_items = _list_arg(request, "action_items", None, max_items=50, expect=dict)
    with transaction.atomic():
        for key, value in data.items():
            setattr(rule, key, value)
        rule.save()
        _write_rule_children(rule, conditions, action_items)
    return ok(services.rule_dict(rule, detail=True))


@endpoint()
def rule_delete(request, pk):
    """删除规则（条件与动作行级联删除）。"""
    rule = _rule_obj(request, pk, write=True)
    rule_id, name = rule.id, rule.name
    with transaction.atomic():
        rule.delete()
    return ok({"id": rule_id, "name": name, "deleted": True})


@endpoint()
def rule_toggle(request, pk):
    """启用/停用规则；不传 enabled 时取反。"""
    rule = _rule_obj(request, pk, write=True)
    enabled = opt_bool(request, "enabled", not rule.enabled)
    rule.enabled = bool(enabled)
    rule.save(update_fields=["enabled", "updated_at"])
    return ok({"id": rule.id, "enabled": rule.enabled})


@endpoint()
def rules_reorder(request):
    """按给定 id 顺序重排规则优先级（步长 10）。"""
    ruleset = _ruleset(request, None, write=True)
    order = _list_arg(request, "order", None, max_items=1000)
    if order is None:
        raise ValueError("缺少必填参数: order")
    ids = [_pk(item, "order") for item in order]
    if len(set(ids)) != len(ids):
        raise ValueError("order 中存在重复的规则 id")
    owned = set(ruleset.rules.filter(id__in=ids).values_list("id", flat=True))
    if owned != set(ids):
        raise ValueError("部分规则不属于该规则集")
    with transaction.atomic():
        for index, rule_id in enumerate(ids):
            Rule.objects.filter(pk=rule_id).update(priority=(index + 1) * 10)
    return ok({"ruleset_id": ruleset.id,
               "items": [{"id": i, "priority": (n + 1) * 10}
                         for n, i in enumerate(ids)]})


@endpoint()
def rules_import(request):
    """批量导入规则（JSON 数组），逐条校验后一次性写入。"""
    ruleset = _ruleset(request, None, write=True)
    items = _list_arg(request, "rules", None, max_items=200, expect=dict)
    if not items:
        raise ValueError("缺少必填参数: rules（非空数组）")
    created = []
    with transaction.atomic():
        for index, item in enumerate(items):
            name = str(item.get("name") or "").strip()
            if not name:
                raise ValueError(f"第 {index + 1} 条规则缺少 name")
            condition = str(item.get("condition") or "").strip()
            if condition:
                report = validate_expression(condition)
                if not report["valid"]:
                    raise ValueError(f"第 {index + 1} 条规则表达式非法: {report['error']}")
            actions = services.normalize_actions(item.get("actions") or [])
            rule = Rule.objects.create(
                owner=request.user, ruleset=ruleset, name=name[:200],
                description=str(item.get("description") or "")[:500],
                priority=int(item.get("priority", 100)),
                enabled=bool(item.get("enabled", True)),
                condition=condition[:MAX_EXPR_LEN],
                actions=services.to_json(actions),
                tags=services.to_json(item.get("tags") or []),
            )
            conditions = item.get("conditions") or []
            action_items = item.get("action_items") or []
            if not isinstance(conditions, list) or not isinstance(action_items, list):
                raise ValueError(f"第 {index + 1} 条规则的 conditions/action_items 必须是数组")
            _write_rule_children(rule, conditions, action_items)
            created.append(rule.id)
    return ok({"ruleset_id": ruleset.id, "created": len(created), "ids": created})


# ---------------------------------------------------------------------------
# 条件（可视化编辑）
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def conditions(request):
    """条件列表 / 为规则新增一条条件。"""
    if request.method == "GET":
        qs = scope_queryset(RuleCondition.objects.all(), request.user)
        if p(request, "rule_id") not in (None, ""):
            rule = _rule_obj(request, p(request, "rule_id"))
            qs = qs.filter(rule=rule)
        qs = services.apply_q(qs, opt_str(request, "q"), ["field", "operator"])
        page, size = services.page_args(request, 50)
        return ok(services.paginate(qs.order_by("rule_id", "sort_order", "id"),
                                    page, size, services.condition_dict))
    rule = _rule_obj(request, req(request, "rule_id"), write=True)
    field = req_str(request, "field", max_len=200).strip()
    operator = opt_str(request, "operator", "==").strip()
    if operator not in CONDITION_OPERATORS:
        raise ValueError(f"不支持的操作符: {operator}")
    logic_group = opt_str(request, "logic_group", "and").strip().lower()
    if logic_group not in ("and", "or"):
        raise ValueError("logic_group 只能是 and/or")
    value = p(request, "value")
    try:
        expression = condition_expression(field, operator, value, logic_group)
    except ExprError as e:
        raise ValueError(str(e))
    item = RuleCondition.objects.create(
        owner=request.user, rule=rule, field=field, operator=operator,
        value=services.to_json(value), logic_group=logic_group,
        sort_order=int(opt_num(request, "sort_order", rule.conditions.count(),
                               minimum=-10000, maximum=10000, integer=True)),
        enabled=opt_bool(request, "enabled", True),
    )
    return ok({"condition": services.condition_dict(item),
               "expression": expression,
               "rule_expression": services.rule_condition_text(rule)})


@endpoint()
def condition_update(request, pk):
    """更新一条条件。"""
    item = services.get_visible(RuleCondition, request, pk, write=True,
                                message="条件不存在")
    field = opt_str(request, "field", item.field, max_len=200).strip()
    operator = opt_str(request, "operator", item.operator).strip()
    if operator not in CONDITION_OPERATORS:
        raise ValueError(f"不支持的操作符: {operator}")
    logic_group = opt_str(request, "logic_group", item.logic_group).strip().lower()
    if logic_group not in ("and", "or"):
        raise ValueError("logic_group 只能是 and/or")
    value = p(request, "value", item.value)
    try:
        condition_expression(field, operator, value, logic_group)
    except ExprError as e:
        raise ValueError(str(e))
    item.field = field
    item.operator = operator
    item.value = services.to_json(value)
    item.logic_group = logic_group
    item.sort_order = int(opt_num(request, "sort_order", item.sort_order,
                                  minimum=-10000, maximum=10000, integer=True))
    item.enabled = opt_bool(request, "enabled", item.enabled)
    item.save()
    return ok(services.condition_dict(item))


@endpoint()
def condition_delete(request, pk):
    """删除一条条件。"""
    item = services.get_visible(RuleCondition, request, pk, write=True,
                                message="条件不存在")
    condition_id = item.id
    item.delete()
    return ok({"id": condition_id, "deleted": True})


@endpoint()
def conditions_compose(request):
    """把规则的条件行拼装成表达式并校验（不落库）。"""
    rule = _rule_obj(request, req(request, "rule_id"))
    items = _list_arg(request, "conditions", None, max_items=100, expect=dict)
    if items is None:
        items = [{"field": c.field, "operator": c.operator, "value": c.value,
                  "logic_group": c.logic_group} for c in rule.conditions.all()
                 if c.enabled]
    try:
        expression = combine_conditions(items)
    except ExprError as e:
        raise ValueError(f"条件拼装失败: {e}")
    report = validate_expression(expression)
    return ok({"rule_id": rule.id, "expression": expression, "report": report})


# ---------------------------------------------------------------------------
# 动作（可视化编辑）
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def actions(request):
    """动作列表 / 为规则新增动作。"""
    if request.method == "GET":
        qs = scope_queryset(RuleAction.objects.all(), request.user)
        if p(request, "rule_id") not in (None, ""):
            rule = _rule_obj(request, p(request, "rule_id"))
            qs = qs.filter(rule=rule)
        status = opt_str(request, "status").strip()
        if status in ("enabled", "active"):
            qs = qs.filter(enabled=True)
        elif status in ("disabled", "inactive"):
            qs = qs.filter(enabled=False)
        page, size = services.page_args(request, 50)
        return ok(services.paginate(qs.order_by("rule_id", "sort_order", "id"),
                                    page, size, services.action_dict))
    rule = _rule_obj(request, req(request, "rule_id"), write=True)
    action_type = req_str(request, "type", max_len=20).strip()
    if action_type not in ACTION_TYPES:
        raise ValueError(f"不支持的动作类型: {action_type}")
    params = _dict_arg(request, "params") or {}
    for key in services.REQUIRED_ACTION_PARAMS.get(action_type, ()):
        if not params.get(key):
            raise ValueError(f"动作 {action_type} 缺少参数 {key}")
    item = RuleAction.objects.create(
        owner=request.user, rule=rule, type=action_type,
        params=services.to_json(params),
        sort_order=int(opt_num(request, "sort_order", rule.action_items.count(),
                               minimum=-10000, maximum=10000, integer=True)),
        enabled=opt_bool(request, "enabled", True),
    )
    return ok(services.action_dict(item))


@endpoint()
def action_update(request, pk):
    """更新一条动作。"""
    item = services.get_visible(RuleAction, request, pk, write=True,
                                message="动作不存在")
    action_type = opt_str(request, "type", item.type).strip()
    if action_type not in ACTION_TYPES:
        raise ValueError(f"不支持的动作类型: {action_type}")
    params = _dict_arg(request, "params")
    item.type = action_type
    if params is not None:
        item.params = services.to_json(params)
    item.sort_order = int(opt_num(request, "sort_order", item.sort_order,
                                  minimum=-10000, maximum=10000, integer=True))
    item.enabled = opt_bool(request, "enabled", item.enabled)
    item.save()
    return ok(services.action_dict(item))


@endpoint()
def action_delete(request, pk):
    """删除一条动作。"""
    item = services.get_visible(RuleAction, request, pk, write=True,
                                message="动作不存在")
    action_id = item.id
    item.delete()
    return ok({"id": action_id, "deleted": True})


# ---------------------------------------------------------------------------
# 变量
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def variables(request):
    """变量列表 / 新建变量。"""
    if request.method == "GET":
        qs = scope_queryset(RuleVariable.objects.all(), request.user)
        if p(request, "ruleset_id") not in (None, ""):
            ruleset = _ruleset(request, p(request, "ruleset_id"))
            qs = qs.filter(ruleset=ruleset)
        qs = services.apply_q(qs, opt_str(request, "q"), ["name", "description"])
        page, size = services.page_args(request, 50)
        return ok(services.paginate(qs.order_by("ruleset_id", "name"),
                                    page, size, services.variable_dict))
    ruleset = _ruleset(request, None, write=True)
    name = req_str(request, "name", max_len=80).strip()
    if "." in name:
        raise ValueError("变量名不能包含点号")
    try:
        validate_path(name)
    except ExprError as e:
        raise ValueError(str(e))
    var_type = opt_str(request, "type", "string").strip()
    if var_type not in VARIABLE_TYPES:
        raise ValueError(f"不支持的变量类型: {var_type}")
    if RuleVariable.objects.filter(ruleset=ruleset, name=name).exists():
        raise ValueError(f"变量 {name} 已存在")
    item = RuleVariable.objects.create(
        owner=request.user, ruleset=ruleset, name=name, var_type=var_type,
        default_value=services.to_json(p(request, "default_value")),
        description=opt_str(request, "description", "", max_len=300),
    )
    return ok(services.variable_dict(item))


@endpoint()
def variable_update(request, pk):
    """更新变量（变量名参与表达式解析，改名需调用方自行同步规则）。"""
    item = services.get_visible(RuleVariable, request, pk, write=True,
                                message="变量不存在")
    name = opt_str(request, "name", item.name, max_len=80).strip()
    if not name or "." in name:
        raise ValueError("变量名不能为空且不能包含点号")
    try:
        validate_path(name)
    except ExprError as e:
        raise ValueError(str(e))
    if RuleVariable.objects.filter(ruleset_id=item.ruleset_id, name=name).exclude(pk=item.pk).exists():
        raise ValueError(f"变量 {name} 已存在")
    var_type = opt_str(request, "type", item.var_type).strip()
    if var_type not in VARIABLE_TYPES:
        raise ValueError(f"不支持的变量类型: {var_type}")
    item.name = name
    item.var_type = var_type
    if _has(request, "default_value"):
        item.default_value = services.to_json(p(request, "default_value"))
    item.description = opt_str(request, "description", item.description, max_len=300)
    item.save()
    return ok(services.variable_dict(item))


@endpoint()
def variable_delete(request, pk):
    """删除变量。"""
    item = services.get_visible(RuleVariable, request, pk, write=True,
                                message="变量不存在")
    variable_id = item.id
    item.delete()
    return ok({"id": variable_id, "deleted": True})


# ---------------------------------------------------------------------------
# 决策表
# ---------------------------------------------------------------------------


def _table_obj(request, pk, write=False):
    return services.get_visible(RuleDecisionTable, request, pk, write=write,
                                message="决策表不存在")


@endpoint(("GET", "POST"))
def tables(request):
    """决策表列表 / 新建决策表。"""
    if request.method == "GET":
        qs = scope_queryset(RuleDecisionTable.objects.all(), request.user)
        if p(request, "ruleset_id") not in (None, ""):
            ruleset = _ruleset(request, p(request, "ruleset_id"))
            qs = qs.filter(ruleset=ruleset)
        qs = services.apply_q(qs, opt_str(request, "q"), ["name", "description"])
        status = opt_str(request, "status").strip()
        if status in ("enabled", "active"):
            qs = qs.filter(enabled=True)
        elif status in ("disabled", "inactive"):
            qs = qs.filter(enabled=False)
        page, size = services.page_args(request, 50)
        return ok(services.paginate(qs.order_by("id"), page, size, services.table_dict))
    ruleset = _ruleset(request, None, write=True)
    name = req_str(request, "name", max_len=200).strip()
    inputs = services.table_columns(p(request, "inputs") or [], "输入列")
    outputs = services.table_columns(p(request, "outputs") or [], "输出列")
    hit_policy = opt_str(request, "hit_policy", "first").strip()
    if hit_policy not in HIT_POLICIES:
        raise ValueError(f"不支持的命中策略: {hit_policy}")
    table = RuleDecisionTable.objects.create(
        owner=request.user, ruleset=ruleset, name=name,
        description=opt_str(request, "description", "", max_len=500),
        inputs=services.to_json(inputs), outputs=services.to_json(outputs),
        hit_policy=hit_policy, enabled=opt_bool(request, "enabled", True),
    )
    return ok(services.table_dict(table, with_rows=True))


@endpoint(("GET", "POST"))
def table_detail(request, pk):
    """决策表详情 / 更新列与命中策略。"""
    table = _table_obj(request, pk, write=request.method == "POST")
    if request.method == "GET":
        return ok(services.table_dict(table, with_rows=True))
    if _has(request, "inputs"):
        table.inputs = services.to_json(
            services.table_columns(p(request, "inputs") or [], "输入列"))
    if _has(request, "outputs"):
        table.outputs = services.to_json(
            services.table_columns(p(request, "outputs") or [], "输出列"))
    hit_policy = opt_str(request, "hit_policy", table.hit_policy).strip()
    if hit_policy not in HIT_POLICIES:
        raise ValueError(f"不支持的命中策略: {hit_policy}")
    table.hit_policy = hit_policy
    table.name = opt_str(request, "name", table.name, max_len=200).strip() or table.name
    table.description = opt_str(request, "description", table.description, max_len=500)
    table.enabled = opt_bool(request, "enabled", table.enabled)
    table.save()
    return ok(services.table_dict(table, with_rows=True))


@endpoint()
def table_delete(request, pk):
    """删除决策表及其所有行。"""
    table = _table_obj(request, pk, write=True)
    table_id = table.id
    with transaction.atomic():
        table.delete()
    return ok({"id": table_id, "deleted": True})


@endpoint(("GET", "POST"))
def table_rows(request, pk):
    """决策表行列表 / 追加一行。"""
    table = _table_obj(request, pk, write=request.method == "POST")
    if request.method == "GET":
        qs = table.rows.all()
        status = opt_str(request, "status").strip()
        if status in ("enabled", "active"):
            qs = qs.filter(enabled=True)
        elif status in ("disabled", "inactive"):
            qs = qs.filter(enabled=False)
        qs = services.apply_q(qs, opt_str(request, "q"), ["remark"])
        page, size = services.page_args(request, 50)
        return ok(services.paginate(qs.order_by("priority", "id"), page, size,
                                    services.row_dict))
    item = {
        "conditions": _dict_arg(request, "conditions") or {},
        "outputs": _dict_arg(request, "outputs") or {},
        "priority": opt_num(request, "priority", table.rows.count() + 1,
                            minimum=-100000, maximum=100000, integer=True),
        "enabled": opt_bool(request, "enabled", True),
        "remark": opt_str(request, "remark", "", max_len=300),
    }
    saved = services.save_table_rows(table, [item])
    return ok(services.row_dict(saved[0]))


@endpoint()
def table_rows_bulk(request, pk):
    """批量保存决策表行（replace=true 时整体覆盖）。"""
    table = _table_obj(request, pk, write=True)
    rows = _list_arg(request, "rows", None, max_items=500, expect=dict)
    if rows is None:
        raise ValueError("缺少必填参数: rows")
    saved = services.save_table_rows(table, rows,
                                     replace=opt_bool(request, "replace", False))
    return ok({"table_id": table.id, "saved": len(saved),
               "items": [services.row_dict(r) for r in saved]})


@endpoint()
def row_update(request, pk):
    """更新一行决策表单元格。"""
    row = services.get_visible(DecisionRow, request, pk, write=True,
                               message="决策表行不存在")
    conditions = _dict_arg(request, "conditions")
    outputs = _dict_arg(request, "outputs")
    if conditions is not None:
        row.conditions = services.to_json(conditions)
    if outputs is not None:
        row.outputs = services.to_json(outputs)
    row.priority = int(opt_num(request, "priority", row.priority,
                               minimum=-100000, maximum=100000, integer=True))
    row.enabled = opt_bool(request, "enabled", row.enabled)
    row.remark = opt_str(request, "remark", row.remark, max_len=300)
    row.save()
    return ok(services.row_dict(row))


@endpoint()
def row_delete(request, pk):
    """删除一行决策表。"""
    row = services.get_visible(DecisionRow, request, pk, write=True,
                               message="决策表行不存在")
    row_id = row.id
    row.delete()
    return ok({"id": row_id, "deleted": True})


@endpoint()
def table_evaluate(request, pk):
    """试算决策表：可用内存行覆盖数据库行，不产生评估记录。"""
    table = _table_obj(request, pk)
    facts = _dict_arg(request, "facts") or {}
    rows = _list_arg(request, "rows", None, max_items=500, expect=dict)
    hit_policy = opt_str(request, "hit_policy", "").strip() or None
    result = services.evaluate_decision_table(table, facts, hit_policy=hit_policy,
                                              rows=rows)
    return ok(result)


# ---------------------------------------------------------------------------
# 评估
# ---------------------------------------------------------------------------


@endpoint()
def evaluate(request):
    """单条评估：返回决策、命中规则与完整 trace（可关闭 explain 省带宽）。"""
    ruleset = _ruleset(request, None)
    facts = _dict_arg(request, "facts") or {}
    variables = _dict_arg(request, "variables") or {}
    result = services.evaluate_ruleset(
        ruleset, facts, variables=variables,
        caller=opt_str(request, "caller", "api", max_len=100),
        trace_id=opt_str(request, "trace_id", "", max_len=64),
        source="manual", owner=request.user,
        persist=opt_bool(request, "persist", True),
        with_trace=opt_bool(request, "explain", True),
    )
    return ok(result)


@endpoint()
def evaluate_batch(request):
    """批量评估：一次最多 200 条事实，返回逐条结果与耗时汇总。"""
    ruleset = _ruleset(request, None)
    facts_list = _list_arg(request, "facts", None, max_items=200, expect=dict)
    if not facts_list:
        raise ValueError("缺少必填参数: facts（非空数组）")
    variables = _dict_arg(request, "variables") or {}
    caller = opt_str(request, "caller", "batch", max_len=100)
    persist = opt_bool(request, "persist", True)
    items, durations, matched = [], [], 0
    started = timezone.now()
    for index, facts in enumerate(facts_list):
        try:
            result = services.evaluate_ruleset(
                ruleset, facts, variables=variables, caller=caller,
                source="batch", owner=request.user, persist=persist,
                with_trace=False,
            )
        except (ValueError, ExprError) as e:
            items.append({"index": index, "error": str(e), "matched": False})
            continue
        durations.append(result["duration_ms"])
        if result["matched"]:
            matched += 1
        items.append({
            "index": index,
            "evaluation_id": result["evaluation_id"],
            "matched": result["matched"],
            "status": result["status"],
            "decision": (result["decision"] or {}).get("decision"),
            "rules": [r.get("name") for r in
                      (result["decision"] or {}).get("rules") or []],
            "duration_ms": result["duration_ms"],
        })
    return ok({
        "ruleset_id": ruleset.id,
        "total": len(facts_list),
        "matched": matched,
        "errors": sum(1 for item in items if item.get("error")),
        "duration": services.percentiles(durations),
        "items": items,
        "started_at": started.isoformat(),
    })


@endpoint(("GET",))
def evaluations(request):
    """评估记录列表（可按规则集、状态、追踪 ID 过滤）。"""
    qs = _eval_queryset(request)
    page, size = services.page_args(request)
    return ok(services.paginate(qs.order_by("-created_at", "-id"), page, size,
                                services.evaluation_dict))


def _eval_queryset(request):
    qs = scope_queryset(RuleEvaluation.objects.all(), request.user)
    if p(request, "ruleset_id") not in (None, ""):
        qs = qs.filter(ruleset_id=_pk(p(request, "ruleset_id"), "ruleset_id"))
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    source = opt_str(request, "source").strip()
    if source:
        qs = qs.filter(source=source)
    return services.apply_q(qs, opt_str(request, "q"), ["trace_id", "caller", "ruleset_code"])


@endpoint(("GET",))
def evaluation_detail(request, pk):
    """评估详情（含 trace 与动作执行日志）。"""
    evaluation = services.get_visible(RuleEvaluation, request, pk,
                                      message="评估记录不存在")
    return ok(services.evaluation_dict(evaluation, include_trace=True,
                                       include_logs=True))


@endpoint(("GET",))
def evaluation_miss_diagnose(request, pk):
    """未命中诊断：逐条规则指出失败的那一步与缺失事实。"""
    evaluation = services.get_visible(RuleEvaluation, request, pk,
                                      message="评估记录不存在")
    return ok(services.diagnose_miss(evaluation))


@endpoint()
def evaluation_reevaluate(request, pk):
    """按原事实重新评估（规则可能已变化），并记录来源评估。"""
    evaluation = services.get_visible(RuleEvaluation, request, pk,
                                      message="评估记录不存在")
    return ok(services.reevaluate(evaluation, request.user))


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


def _case_obj(request, pk, write=False):
    return services.get_visible(RuleTestCase, request, pk, write=write,
                                message="测试用例不存在")


@endpoint(("GET", "POST"))
def testcases(request):
    """测试用例列表 / 新建用例。"""
    if request.method == "GET":
        qs = scope_queryset(RuleTestCase.objects.all(), request.user)
        if p(request, "ruleset_id") not in (None, ""):
            ruleset = _ruleset(request, p(request, "ruleset_id"))
            qs = qs.filter(ruleset=ruleset)
        qs = services.apply_q(qs, opt_str(request, "q"), ["name"])
        status = opt_str(request, "status").strip()
        if status in ("passed", "success"):
            qs = qs.filter(passed=True)
        elif status in ("failed", "error"):
            qs = qs.filter(passed=False)
        page, size = services.page_args(request, 50)
        return ok(services.paginate(qs.order_by("-created_at"), page, size,
                                    services.testcase_dict))
    ruleset = _ruleset(request, None, write=True)
    case = RuleTestCase.objects.create(
        owner=request.user, ruleset=ruleset,
        name=req_str(request, "name", max_len=200).strip(),
        facts=_dict_arg(request, "facts") or {},
        expected=_dict_arg(request, "expected") or {},
    )
    return ok(services.testcase_dict(case))


@endpoint()
def testcase_update(request, pk):
    """更新测试用例的输入与期望输出。"""
    case = _case_obj(request, pk, write=True)
    case.name = opt_str(request, "name", case.name, max_len=200).strip() or case.name
    facts = _dict_arg(request, "facts")
    expected = _dict_arg(request, "expected")
    if facts is not None:
        case.facts = facts
    if expected is not None:
        case.expected = expected
    case.save()
    return ok(services.testcase_dict(case))


@endpoint()
def testcase_delete(request, pk):
    """删除测试用例。"""
    case = _case_obj(request, pk, write=True)
    case_id = case.id
    case.delete()
    return ok({"id": case_id, "deleted": True})


@endpoint()
def testcase_run(request, pk):
    """运行单个测试用例并回写通过状态。"""
    case = _case_obj(request, pk, write=True)
    return ok(services.run_test_case(case,
                                     persist=opt_bool(request, "persist", True)))


@endpoint()
def testcases_run_all(request):
    """批量运行规则集下全部用例。"""
    ruleset = _ruleset(request, None, write=True)
    return ok(services.run_all_cases(ruleset,
                                     persist=opt_bool(request, "persist", True)))


@endpoint(("GET",))
def testcases_coverage(request):
    """用例覆盖率：覆盖了哪些启用规则、哪些规则没有任何用例命中。"""
    ruleset = _ruleset(request, None)
    return ok(services.test_coverage(ruleset))


# ---------------------------------------------------------------------------
# 仿真
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def simulations(request):
    """仿真列表 / 创建并运行一次批量仿真。"""
    if request.method == "GET":
        qs = scope_queryset(RuleSimulation.objects.all(), request.user)
        if p(request, "ruleset_id") not in (None, ""):
            ruleset = _ruleset(request, p(request, "ruleset_id"))
            qs = qs.filter(ruleset=ruleset)
        qs = services.apply_q(qs, opt_str(request, "q"), ["name"])
        page, size = services.page_args(request, 20)
        return ok(services.paginate(qs.order_by("-created_at"), page, size,
                                    services.simulation_dict))
    ruleset = _ruleset(request, None)
    facts = _list_arg(request, "facts", None, max_items=500)
    if facts is None:
        raise ValueError("缺少必填参数: facts")
    for index, item in enumerate(facts):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 条事实必须是对象")
    result = services.run_simulation(
        ruleset, facts, name=opt_str(request, "name", "", max_len=200),
        owner=request.user, persist=opt_bool(request, "persist", True),
    )
    return ok(result)


@endpoint(("GET",))
def simulation_detail(request, pk):
    """仿真详情（摘要 + 明细样本）。"""
    sim = services.get_visible(RuleSimulation, request, pk,
                               message="仿真记录不存在")
    return ok(services.simulation_dict(sim, include_results=True))


# ---------------------------------------------------------------------------
# 冲突
# ---------------------------------------------------------------------------


@endpoint()
def conflicts_detect(request):
    """检测规则集内部冲突（重复/重叠/不可达/动作矛盾）并落库。"""
    ruleset = _ruleset(request, None, write=True)
    return ok(services.detect_rule_conflicts(
        ruleset, persist=opt_bool(request, "persist", True)))


@endpoint(("GET",))
def conflicts(request):
    """冲突列表（按规则集/类型/严重度/状态过滤）。"""
    qs = scope_queryset(RuleConflict.objects.all(), request.user)
    if p(request, "ruleset_id") not in (None, ""):
        qs = qs.filter(ruleset_id=_pk(p(request, "ruleset_id"), "ruleset_id"))
    status = opt_str(request, "status").strip()
    if status:
        if status not in CONFLICT_STATUS:
            raise ValueError(f"不支持的冲突状态: {status}")
        qs = qs.filter(status=status)
    conflict_type = opt_str(request, "conflict_type").strip()
    if conflict_type:
        qs = qs.filter(conflict_type=conflict_type)
    severity = opt_str(request, "severity").strip()
    if severity:
        if severity not in CONFLICT_SEVERITIES:
            raise ValueError(f"不支持的严重度: {severity}")
        qs = qs.filter(severity=severity)
    page, size = services.page_args(request)
    return ok(services.paginate(qs.select_related("rule_a", "rule_b")
                                .order_by("-created_at", "-id"),
                                page, size, services.conflict_dict))


def _close_conflict(request, pk, status):
    conflict = services.get_visible(RuleConflict, request, pk, write=True,
                                    message="冲突记录不存在")
    if conflict.status != "open":
        raise ValueError(f"冲突已处理（当前 {conflict.status}）")
    conflict.status = status
    conflict.note = opt_str(request, "note", "", max_len=500)
    conflict.save(update_fields=["status", "note", "updated_at"])
    return ok(services.conflict_dict(conflict))


@endpoint()
def conflict_resolve(request, pk):
    """标记冲突已解决。"""
    return _close_conflict(request, pk, "resolved")


@endpoint()
def conflict_ignore(request, pk):
    """忽略冲突（保留记录但不再提示）。"""
    return _close_conflict(request, pk, "ignored")


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------


def _schedule_obj(request, pk, write=False):
    return services.get_visible(RuleSchedule, request, pk, write=write,
                                message="调度不存在")


@endpoint(("GET", "POST"))
def schedules(request):
    """调度列表 / 新建调度（创建时即计算下次运行时间）。"""
    if request.method == "GET":
        qs = scope_queryset(RuleSchedule.objects.all(), request.user)
        if p(request, "ruleset_id") not in (None, ""):
            qs = qs.filter(ruleset_id=_pk(p(request, "ruleset_id"), "ruleset_id"))
        status = opt_str(request, "status").strip()
        if status in ("enabled", "active"):
            qs = qs.filter(enabled=True)
        elif status in ("disabled", "inactive"):
            qs = qs.filter(enabled=False)
        qs = services.apply_q(qs, opt_str(request, "q"), ["name", "cron"])
        page, size = services.page_args(request)
        return ok(services.paginate(qs.select_related("ruleset")
                                    .order_by("next_run_at", "id"),
                                    page, size, services.schedule_dict))
    ruleset = _ruleset(request, None, write=True)
    cron = req_str(request, "cron", max_len=120).strip()
    next_run = services.cron_next(cron)
    schedule = RuleSchedule.objects.create(
        owner=request.user, ruleset=ruleset,
        name=opt_str(request, "name", f"{ruleset.name} 调度", max_len=200),
        cron=cron, facts=_dict_arg(request, "facts") or {},
        enabled=opt_bool(request, "enabled", True), next_run_at=next_run,
    )
    return ok(services.schedule_dict(schedule))


@endpoint()
def schedule_update(request, pk):
    """更新调度：cron 变化时重新计算下次运行时间。"""
    schedule = _schedule_obj(request, pk, write=True)
    cron = opt_str(request, "cron", schedule.cron, max_len=120).strip()
    if cron != schedule.cron:
        schedule.next_run_at = services.cron_next(cron)
    schedule.cron = cron
    schedule.name = opt_str(request, "name", schedule.name, max_len=200)
    facts = _dict_arg(request, "facts")
    if facts is not None:
        schedule.facts = services.to_json(facts)
    schedule.enabled = opt_bool(request, "enabled", schedule.enabled)
    if schedule.enabled and schedule.next_run_at is None:
        schedule.next_run_at = services.cron_next(schedule.cron)
    schedule.save()
    return ok(services.schedule_dict(schedule))


@endpoint()
def schedule_toggle(request, pk):
    """启停调度；重新启用时若下次运行时间已过期则顺延到未来。"""
    schedule = _schedule_obj(request, pk, write=True)
    schedule.enabled = opt_bool(request, "enabled", not schedule.enabled)
    if schedule.enabled and (schedule.next_run_at is None
                             or schedule.next_run_at <= timezone.now()):
        schedule.next_run_at = services.cron_next(schedule.cron)
    schedule.save(update_fields=["enabled", "next_run_at", "updated_at"])
    return ok(services.schedule_dict(schedule))


@endpoint()
def schedule_run(request, pk):
    """立即执行一次调度（手动触发，不改变 cron 节奏）。"""
    schedule = _schedule_obj(request, pk, write=True)
    result = services.run_schedule_now(schedule, request.user)
    return ok({"schedule_id": schedule.id, "result": result})


@endpoint()
def schedules_scan(request):
    """扫描本人到期调度并执行（写接口，只处理 owner 本人）。"""
    return ok(services.scan_schedules(request.user))


@endpoint()
def schedule_delete(request, pk):
    """删除调度。"""
    schedule = _schedule_obj(request, pk, write=True)
    schedule_id = schedule.id
    schedule.delete()
    return ok({"id": schedule_id, "deleted": True})


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------


def _approval_for_review(request, pk):
    """审批权限：申请人可查看自己的，管理员可审所有人的；其余一律拒绝。"""
    try:
        approval = RuleApproval.objects.select_related("ruleset").get(pk=int(pk))
    except (RuleApproval.DoesNotExist, TypeError, ValueError):
        raise ValueError("审批记录不存在")
    user = request.user
    if not (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
            or approval.owner_id == user.id):
        raise ValueError("无权处理该审批")
    return approval


@endpoint(("GET", "POST"))
def approvals(request):
    """审批列表 / 提交规则变更审批。"""
    if request.method == "GET":
        qs = scope_queryset(RuleApproval.objects.all(), request.user)
        if p(request, "ruleset_id") not in (None, ""):
            qs = qs.filter(ruleset_id=_pk(p(request, "ruleset_id"), "ruleset_id"))
        status = opt_str(request, "status").strip()
        if status:
            if status not in ("pending", "approved", "rejected", "cancelled"):
                raise ValueError(f"不支持的审批状态: {status}")
            qs = qs.filter(status=status)
        page, size = services.page_args(request)
        return ok(services.paginate(qs.select_related("ruleset", "owner", "reviewer")
                                    .order_by("-created_at"), page, size,
                                    services.approval_dict))
    ruleset = _ruleset(request, None, write=True)
    change = p(request, "change")
    if change is None:
        fields = _dict_arg(request, "fields")
        if fields is None:
            raise ValueError("缺少必填参数: change 或 fields")
        change = {"fields": fields, "publish": opt_bool(request, "publish", True)}
    approval = services.submit_approval(ruleset, request.user, change,
                                        opt_str(request, "note", "", max_len=500))
    return ok(services.approval_dict(approval))


@endpoint()
def approval_approve(request, pk):
    """通过审批并应用变更（默认同时发布新版本）。"""
    approval = _approval_for_review(request, pk)
    approval = services.review_approval(
        approval, request.user, True, opt_str(request, "note", "", max_len=500))
    return ok(services.approval_dict(approval))


@endpoint()
def approval_reject(request, pk):
    """驳回审批，必须给出意见。"""
    approval = _approval_for_review(request, pk)
    note = req_str(request, "reason", max_len=500)
    approval = services.review_approval(approval, request.user, False, note)
    return ok(services.approval_dict(approval))


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def stats_overview(request):
    """统计概览：评估量、命中率、失败率、耗时、规则/冲突/用例健康度。"""
    days = opt_num(request, "days", 7, minimum=1, maximum=365, integer=True)
    ruleset_id = p(request, "ruleset_id")
    return ok(services.stats_overview(request.user, days=days, ruleset_id=ruleset_id))


@endpoint(("GET",))
def stats_top_rules(request):
    """命中 TOP：窗口内命中次数排行 + 全生命周期计数。"""
    days = opt_num(request, "days", 7, minimum=1, maximum=365, integer=True)
    limit = opt_num(request, "limit", 10, minimum=1, maximum=100, integer=True)
    return ok(services.stats_top_rules(request.user, days=days, limit=limit,
                                       ruleset_id=p(request, "ruleset_id")))


@endpoint(("GET",))
def stats_failures(request):
    """失败原因分布：动作失败类型 + 错误原文 TOP + 评估异常状态。"""
    days = opt_num(request, "days", 7, minimum=1, maximum=365, integer=True)
    return ok(services.stats_failures(request.user, days=days,
                                      ruleset_id=p(request, "ruleset_id")))


@endpoint(("GET",))
def stats_latency(request):
    """耗时分位：整体 p50/p90/p95/p99 与最慢规则集 TOP。"""
    days = opt_num(request, "days", 7, minimum=1, maximum=365, integer=True)
    return ok(services.stats_latency(request.user, days=days,
                                     ruleset_id=p(request, "ruleset_id")))


@endpoint(("GET",))
def stats_trend(request):
    """按日趋势：评估量/命中量/异常量，自动补齐空白日期。"""
    days = opt_num(request, "days", 7, minimum=1, maximum=365, integer=True)
    return ok(services.stats_trend(request.user, days=days,
                                   ruleset_id=p(request, "ruleset_id")))


# ---------------------------------------------------------------------------
# 执行日志
# ---------------------------------------------------------------------------


@endpoint(("GET",))
def logs(request):
    """动作执行日志列表（按状态/评估/关键字过滤）。"""
    qs = scope_queryset(RuleExecutionLog.objects.all(), request.user)
    if p(request, "evaluation_id") not in (None, ""):
        qs = qs.filter(evaluation_id=_pk(p(request, "evaluation_id"), "evaluation_id"))
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    action_type = opt_str(request, "action_type").strip()
    if action_type:
        qs = qs.filter(action_type=action_type)
    qs = services.apply_q(qs, opt_str(request, "q"),
                          ["rule_name", "error", "action_type"])
    page, size = services.page_args(request, 50)
    return ok(services.paginate(qs.order_by("-created_at", "-id"), page, size,
                                services.log_dict))


@endpoint(("GET",))
def log_detail(request, pk):
    """动作执行日志详情。"""
    log = services.get_visible(RuleExecutionLog, request, pk,
                               message="执行日志不存在")
    return ok(services.log_dict(log))


# ---------------------------------------------------------------------------
# 标签 / 模板 / 任务 / 通知
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def tags(request):
    """标签列表 / 新建标签并可挂载到规则集。"""
    if request.method == "GET":
        qs = scope_queryset(RuleTag.objects.all(), request.user)
        qs = services.apply_q(qs, opt_str(request, "q"), ["name"])
        page, size = services.page_args(request, 50)
        return ok(services.paginate(qs.order_by("name"), page, size, services.tag_dict))
    name = req_str(request, "name", max_len=60).strip()
    if RuleTag.objects.filter(owner=request.user, name=name).exists():
        raise ValueError(f"标签 {name} 已存在")
    ruleset_ids = _list_arg(request, "ruleset_ids", [], max_items=200) or []
    with transaction.atomic():
        tag = RuleTag.objects.create(
            owner=request.user, name=name,
            color=opt_str(request, "color", "#409eff", max_len=20),
        )
        for ruleset_id in ruleset_ids:
            ruleset = _ruleset(request, ruleset_id, write=True)
            tag.rulesets.add(ruleset)
    return ok(services.tag_dict(tag))


@endpoint()
def tag_delete(request, pk):
    """删除标签（多对多关系自动解除，不影响规则集）。"""
    tag = services.get_visible(RuleTag, request, pk, write=True, message="标签不存在")
    tag_id = tag.id
    tag.delete()
    return ok({"id": tag_id, "deleted": True})


@endpoint(("GET", "POST"))
def templates(request):
    """模板目录（内置 + 本人）/ 把规则集保存为本人模板。"""
    if request.method == "GET":
        items = services.list_templates(request.user)
        q = opt_str(request, "q").strip().lower()
        if q:
            items = [item for item in items if q in item["name"].lower()
                     or q in item["category"].lower()]
        page, size = services.page_args(request, 50)
        start = (page - 1) * size
        return ok({"items": items[start:start + size], "count": len(items),
                   "page": page, "page_size": size})
    name = req_str(request, "name", max_len=200).strip()
    source_ruleset = None
    if p(request, "ruleset_id") not in (None, ""):
        source_ruleset = _ruleset(request, p(request, "ruleset_id"))
    payload = _dict_arg(request, "template")
    if payload is None and source_ruleset is not None:
        payload = services.ruleset_snapshot(source_ruleset)
    if not isinstance(payload, dict) or not payload.get("ruleset"):
        raise ValueError("模板内容必须包含 ruleset 段（可直接传规则集快照）")
    template = RuleTemplate.objects.create(
        owner=request.user, name=name,
        category=opt_str(request, "category", "通用", max_len=60),
        description=opt_str(request, "description", "", max_len=500),
        template=services.to_json(payload),
    )
    return ok(services.template_dict(template))


@endpoint()
def template_apply(request):
    """从模板创建规则集（内置模板用 key，个人模板用 template_id）。"""
    ruleset = services.apply_template(
        request.user,
        template_id=p(request, "template_id"),
        key=opt_str(request, "key", "", max_len=100),
        name=opt_str(request, "name", "", max_len=200),
    )
    return ok(services.ruleset_dict(ruleset, detail=True))


@endpoint(("GET",))
def tasks(request):
    """规则生成的任务列表（按状态/关键字过滤）。"""
    qs = scope_queryset(RuleTask.objects.all(), request.user)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    if p(request, "ruleset_id") not in (None, ""):
        qs = qs.filter(ruleset_id=_pk(p(request, "ruleset_id"), "ruleset_id"))
    qs = services.apply_q(qs, opt_str(request, "q"), ["title"])
    page, size = services.page_args(request, 50)
    return ok(services.paginate(qs.order_by("-created_at"), page, size,
                                services.task_dict))


@endpoint(("GET",))
def notifications(request):
    """规则通知/模拟 webhook 投递台账。"""
    qs = scope_queryset(RuleNotification.objects.all(), request.user)
    status = opt_str(request, "status").strip()
    if status:
        qs = qs.filter(status=status)
    channel = opt_str(request, "channel").strip()
    if channel:
        qs = qs.filter(channel=channel)
    qs = services.apply_q(qs, opt_str(request, "q"), ["title", "target"])
    page, size = services.page_args(request, 50)
    return ok(services.paginate(qs.order_by("-created_at"), page, size,
                                services.notification_dict))



