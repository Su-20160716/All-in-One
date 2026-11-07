# -*- coding: utf-8 -*-
"""rules 服务层：评估编排、动作执行、决策表、冲突检测、仿真、调度与统计。

分层约定：
- 视图层只做参数提取与权限入口，业务逻辑全部集中在本模块，便于测试与复用；
- 所有多表写入包在 transaction.atomic() 内：评估 + 日志 + 规则计数 + 动作落库
  必须同成同败，否则会出现「有命中记录但没有动作日志」的脏数据；
- 评估永远返回 trace（条件树 + 每步布尔值），前端调试面板不依赖日志开关；
- 批量入口（仿真/测试用例）默认 dry_run：动作仍然被计算并产出结果，
  但不写通知/任务，避免跑一次回归就在业务库里制造几百条任务。
"""
import copy
import json
import math
from time import perf_counter
import uuid
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Avg, Count, F, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.scoping import can_write, is_visible, owner_qs, scope_queryset
from devtools.common import opt_num, opt_str, p
from rules.expressions import (ExprError, MAX_DEPTH, MAX_EXPR_LEN, MAX_VARIABLES,
                               LogicalNode, combine_conditions, condition_expression,
                               evaluate_expression, explain_expression,
                               literal_text, parse_expression, render_template,
                               resolve_path, validate_expression, validate_path)
from rules.models import (ACTION_TYPES, APPROVAL_STATUS, CONFLICT_SEVERITIES,
                          CONFLICT_TYPES, HIT_POLICIES, RULESET_STATUS,
                          Rule, RuleAction, RuleApproval, RuleCondition,
                          RuleConflict, RuleDecisionTable, RuleEvaluation,
                          RuleExecutionLog, RuleNotification, RuleSchedule,
                          RuleSet, RuleSetVersion, RuleSimulation, RuleTag,
                          RuleTask, RuleTemplate, RuleTestCase, RuleVariable,
                          DecisionRow, VARIABLE_TYPES)

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def now_iso(value=None):
    """时间统一转 ISO 字符串，空值返回 None（前端好判断）。"""
    value = value or timezone.now()
    return value.isoformat()


def perf_ms(started):
    return round((perf_counter() - started) * 1000, 3)


def to_json(value):
    """把任意求值结果转成可 JSON 序列化的结构（Decimal/日期/集合统一降级）。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json(v) for v in value]
    if hasattr(value, "pk"):
        return value.pk
    return str(value)


def values_equal(left, right):
    """期望值比较：数字跨 int/float，bool 不与数字互通，字符串去首尾空白。"""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if isinstance(left, str) and isinstance(right, str):
        return left.strip() == right.strip()
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(values_equal(left[k], right[k]) for k in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            values_equal(a, b) for a, b in zip(left, right))
    return left == right


def subset_match(expected, actual):
    """期望输出是实际输出的子集：用例只断言关心的字段，不锁死整份决策。"""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and subset_match(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(subset_match(e, a) for a in actual) for e in expected)
    return values_equal(expected, actual)


def user_payload(user):
    if user is None:
        return None
    return {
        "id": getattr(user, "id", None),
        "username": getattr(user, "username", ""),
        "display_name": getattr(user, "display_name", "") or getattr(user, "username", ""),
    }


def parse_json_arg(value, field_name, expect=None):
    """入参可能是 JSON 字符串（前端 textarea），统一解析并校验顶层类型。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            value = {} if expect is dict else ([] if expect is list else None)
        else:
            try:
                value = json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(f"参数 {field_name} 不是合法 JSON: {e.msg}")
    if expect is not None and value is not None and not isinstance(value, expect):
        raise ValueError(f"参数 {field_name} 必须是 {'对象' if expect is dict else '数组'}")
    return value


def as_int(value, field_name, default=None, minimum=None, maximum=None):
    """把路径/请求里的值转整数，失败给出中文字段名（比裸 ValueError 友好）。"""
    if value is None or value == "":
        if default is not None:
            return default
        raise ValueError(f"缺少必填参数: {field_name}")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {field_name} 必须是整数")
    if minimum is not None and result < minimum:
        raise ValueError(f"参数 {field_name} 不能小于 {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"参数 {field_name} 不能大于 {maximum}")
    return result


def clamp_int(value, default, minimum, maximum):
    """宽容版整数：越界直接夹到区间，用于 limit 之类的非关键参数。"""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, result))


def page_args(request, default_size=20):
    """标准分页参数：page ≥ 1，page_size 1~200（超过 200 直接 400）。"""
    page = int(opt_num(request, "page", 1, minimum=1, maximum=1000000, integer=True))
    size = int(opt_num(request, "page_size", default_size, minimum=1,
                       maximum=200, integer=True))
    return page, size


def paginate(qs, page, size, mapper):
    """统一列表响应：items/count/page/page_size，切片在数据库完成。"""
    total = qs.count()
    start = (page - 1) * size
    items = [mapper(obj) for obj in qs[start:start + size]]
    return {"items": items, "count": total, "page": page, "page_size": size}


def apply_q(qs, q, fields):
    """按多个字段做包含匹配；q 为空时原样返回，避免无谓查询。"""
    q = (q or "").strip()
    if not q:
        return qs
    cond = Q()
    for field in fields:
        cond |= Q(**{f"{field}__icontains": q})
    return qs.filter(cond)


def get_visible(model, request, pk, write=False, message="对象不存在"):
    """取对象 + 行级读/写校验（staff 与超管放行，与平台其他应用一致）。"""
    try:
        obj = model.objects.get(pk=int(pk))
    except (model.DoesNotExist, TypeError, ValueError):
        raise ValueError(message)
    user = request.user
    admin = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    if not admin and not is_visible(obj, user):
        raise ValueError("无权访问该对象")
    if write and not admin and not can_write(user, obj):
        raise ValueError("无权修改该对象")
    return obj


def get_by_pk(model, pk, message="对象不存在"):
    try:
        return model.objects.get(pk=int(pk))
    except (model.DoesNotExist, TypeError, ValueError):
        raise ValueError(message)


def resolve_ruleset(request, pk=None, write=False):
    """路径 pk / ruleset_id / code 三种方式定位规则集。"""
    if pk is not None:
        return get_visible(RuleSet, request, pk, write=write, message="规则集不存在")
    raw_id = p(request, "ruleset_id")
    code = opt_str(request, "code").strip()
    if raw_id not in (None, ""):
        return get_visible(RuleSet, request, raw_id, write=write, message="规则集不存在")
    if code:
        qs = RuleSet.objects.filter(code=code)
        if write:
            qs = owner_qs(qs, request.user)
        else:
            qs = scope_queryset(qs, request.user)
        ruleset = qs.first()
        if ruleset is None:
            raise ValueError("规则集不存在")
        return ruleset
    raise ValueError("缺少必填参数: ruleset_id")


# ---------------------------------------------------------------------------
# 序列化渲染
# ---------------------------------------------------------------------------


def ruleset_dict(rs, detail=False):
    data = {
        "id": rs.id,
        "code": rs.code,
        "name": rs.name,
        "category": rs.category,
        "description": rs.description,
        "status": rs.status,
        "status_label": dict(RULESET_LABELS).get(rs.status, rs.status),
        "version_no": rs.version_no,
        "hit_policy": rs.hit_policy,
        "max_executions": rs.max_executions,
        "timeout_ms": rs.timeout_ms,
        "priority": rs.priority,
        "tags": to_json(rs.tags or []),
        "settings": to_json(rs.settings or {}),
        "owner": user_payload(rs.owner),
        "created_at": now_iso(rs.created_at) if rs.created_at else None,
        "updated_at": now_iso(rs.updated_at) if rs.updated_at else None,
    }
    if detail:
        data["rule_count"] = rs.rules.count()
        data["enabled_rule_count"] = rs.rules.filter(enabled=True).count()
        data["variable_count"] = rs.variables.count()
        data["table_count"] = rs.decision_tables.count()
        data["version_count"] = rs.versions.count()
        data["open_conflicts"] = rs.conflicts.filter(status="open").count()
        data["schedule_count"] = rs.schedules.count()
    return data


RULESET_LABELS = (
    ("draft", "草稿"), ("active", "生效中"), ("paused", "已暂停"), ("archived", "已归档"),
)


def condition_dict(cond):
    return {
        "id": cond.id,
        "rule_id": cond.rule_id,
        "field": cond.field,
        "operator": cond.operator,
        "value": to_json(cond.value),
        "logic_group": cond.logic_group,
        "sort_order": cond.sort_order,
        "enabled": cond.enabled,
        "created_at": now_iso(cond.created_at) if cond.created_at else None,
        "updated_at": now_iso(cond.updated_at) if cond.updated_at else None,
    }


def action_dict(action):
    return {
        "id": action.id,
        "rule_id": action.rule_id,
        "type": action.type,
        "params": to_json(action.params or {}),
        "sort_order": action.sort_order,
        "enabled": action.enabled,
        "created_at": now_iso(action.created_at) if action.created_at else None,
        "updated_at": now_iso(action.updated_at) if action.updated_at else None,
    }


def rule_dict(rule, detail=False):
    data = {
        "id": rule.id,
        "ruleset_id": rule.ruleset_id,
        "name": rule.name,
        "description": rule.description,
        "priority": rule.priority,
        "enabled": rule.enabled,
        "condition": rule.condition,
        "actions": to_json(rule.actions or []),
        "tags": to_json(rule.tags or []),
        "hit_count": rule.hit_count,
        "last_hit_at": now_iso(rule.last_hit_at) if rule.last_hit_at else None,
        "created_at": now_iso(rule.created_at) if rule.created_at else None,
        "updated_at": now_iso(rule.updated_at) if rule.updated_at else None,
    }
    if detail:
        data["effective_expression"] = rule_condition_text(rule)
        data["conditions"] = [condition_dict(c) for c in rule.conditions.all()]
        data["action_items"] = [action_dict(a) for a in rule.action_items.all()]
        data["resolved_actions"] = rule_actions(rule)
    return data


def variable_dict(var):
    return {
        "id": var.id,
        "ruleset_id": var.ruleset_id,
        "name": var.name,
        "type": var.var_type,
        "default_value": to_json(var.default_value),
        "description": var.description,
        "created_at": now_iso(var.created_at) if var.created_at else None,
        "updated_at": now_iso(var.updated_at) if var.updated_at else None,
    }


def version_dict(version, include_snapshot=False):
    data = {
        "id": version.id,
        "ruleset_id": version.ruleset_id,
        "version_no": version.version_no,
        "note": version.note,
        "published_by": user_payload(version.published_by),
        "created_at": now_iso(version.created_at) if version.created_at else None,
    }
    if include_snapshot:
        data["snapshot"] = to_json(version.snapshot or {})
    return data


def evaluation_dict(evaluation, include_trace=False, include_logs=False):
    data = {
        "id": evaluation.id,
        "ruleset_id": evaluation.ruleset_id,
        "ruleset_code": evaluation.ruleset_code,
        "facts": to_json(evaluation.facts or {}),
        "variables": to_json(evaluation.variables or {}),
        "matched_rules": to_json(evaluation.matched_rules or []),
        "decision": to_json(evaluation.decision or {}),
        "duration_ms": evaluation.duration_ms,
        "caller": evaluation.caller,
        "trace_id": evaluation.trace_id,
        "status": evaluation.status,
        "error": evaluation.error,
        "source": evaluation.source,
        "created_at": now_iso(evaluation.created_at) if evaluation.created_at else None,
        "log_count": getattr(evaluation, "log_total", None),
    }
    if include_trace:
        data["trace"] = to_json(evaluation.trace or {})
    if include_logs:
        data["logs"] = [log_dict(log) for log in evaluation.logs.all()[:200]]
    return data


def log_dict(log):
    return {
        "id": log.id,
        "evaluation_id": log.evaluation_id,
        "rule_id": log.rule_id,
        "rule_name": log.rule_name,
        "action_type": log.action_type,
        "status": log.status,
        "error": log.error,
        "retries": log.retries,
        "duration_ms": log.duration_ms,
        "detail": to_json(log.detail or {}),
        "created_at": now_iso(log.created_at) if log.created_at else None,
    }


def table_dict(table, with_rows=False):
    data = {
        "id": table.id,
        "ruleset_id": table.ruleset_id,
        "name": table.name,
        "description": table.description,
        "inputs": to_json(table.inputs or []),
        "outputs": to_json(table.outputs or []),
        "hit_policy": table.hit_policy,
        "enabled": table.enabled,
        "created_at": now_iso(table.created_at) if table.created_at else None,
        "updated_at": now_iso(table.updated_at) if table.updated_at else None,
    }
    if with_rows:
        data["rows"] = [row_dict(r) for r in table.rows.all()]
    return data


def row_dict(row):
    return {
        "id": row.id,
        "table_id": row.table_id,
        "conditions": to_json(row.conditions or {}),
        "outputs": to_json(row.outputs or {}),
        "priority": row.priority,
        "enabled": row.enabled,
        "remark": row.remark,
        "created_at": now_iso(row.created_at) if row.created_at else None,
        "updated_at": now_iso(row.updated_at) if row.updated_at else None,
    }


def testcase_dict(case):
    return {
        "id": case.id,
        "ruleset_id": case.ruleset_id,
        "name": case.name,
        "facts": to_json(case.facts or {}),
        "expected": to_json(case.expected or {}),
        "passed": case.passed,
        "last_run_at": now_iso(case.last_run_at) if case.last_run_at else None,
        "last_result": to_json(case.last_result or {}),
        "created_at": now_iso(case.created_at) if case.created_at else None,
        "updated_at": now_iso(case.updated_at) if case.updated_at else None,
    }


def simulation_dict(sim, include_results=False):
    data = {
        "id": sim.id,
        "ruleset_id": sim.ruleset_id,
        "name": sim.name,
        "fact_count": len(sim.facts or []),
        "summary": to_json(sim.summary or {}),
        "duration_ms": sim.duration_ms,
        "status": sim.status,
        "created_at": now_iso(sim.created_at) if sim.created_at else None,
    }
    if include_results:
        data["results"] = to_json(sim.results or [])
        data["facts"] = to_json(sim.facts or [])
    return data


def conflict_dict(conflict):
    return {
        "id": conflict.id,
        "ruleset_id": conflict.ruleset_id,
        "rule_a": {"id": conflict.rule_a_id,
                   "name": conflict.rule_a.name if conflict.rule_a else ""},
        "rule_b": {"id": conflict.rule_b_id,
                   "name": conflict.rule_b.name if conflict.rule_b else ""},
        "conflict_type": conflict.conflict_type,
        "severity": conflict.severity,
        "status": conflict.status,
        "detail": to_json(conflict.detail or {}),
        "note": conflict.note,
        "created_at": now_iso(conflict.created_at) if conflict.created_at else None,
    }


def schedule_dict(schedule):
    return {
        "id": schedule.id,
        "ruleset_id": schedule.ruleset_id,
        "ruleset_code": schedule.ruleset.code if schedule.ruleset_id else "",
        "name": schedule.name,
        "cron": schedule.cron,
        "facts": to_json(schedule.facts or {}),
        "enabled": schedule.enabled,
        "last_run_at": now_iso(schedule.last_run_at) if schedule.last_run_at else None,
        "next_run_at": now_iso(schedule.next_run_at) if schedule.next_run_at else None,
        "run_count": schedule.run_count,
        "created_at": now_iso(schedule.created_at) if schedule.created_at else None,
    }


def approval_dict(approval):
    return {
        "id": approval.id,
        "ruleset_id": approval.ruleset_id,
        "ruleset_code": approval.ruleset.code if approval.ruleset_id else "",
        "change": to_json(approval.change or {}),
        "status": approval.status,
        "note": approval.note,
        "applicant": user_payload(approval.owner),
        "reviewer": user_payload(approval.reviewer),
        "review_note": approval.review_note,
        "reviewed_at": now_iso(approval.reviewed_at) if approval.reviewed_at else None,
        "created_at": now_iso(approval.created_at) if approval.created_at else None,
    }


def tag_dict(tag):
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "ruleset_count": tag.rulesets.count(),
        "created_at": now_iso(tag.created_at) if tag.created_at else None,
    }


def template_dict(template):
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "template": to_json(template.template or {}),
        "builtin": template.builtin,
        "usage_count": template.usage_count,
        "created_at": now_iso(template.created_at) if template.created_at else None,
    }


def task_dict(task):
    return {
        "id": task.id,
        "ruleset_id": task.ruleset_id,
        "rule_id": task.rule_id,
        "evaluation_id": task.evaluation_id,
        "title": task.title,
        "assignee": user_payload(task.assignee),
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "status": task.status,
        "payload": to_json(task.payload or {}),
        "created_at": now_iso(task.created_at) if task.created_at else None,
    }


def notification_dict(item):
    return {
        "id": item.id,
        "ruleset_id": item.ruleset_id,
        "rule_id": item.rule_id,
        "evaluation_id": item.evaluation_id,
        "channel": item.channel,
        "target": item.target,
        "title": item.title,
        "body": item.body,
        "status": item.status,
        "payload": to_json(item.payload or {}),
        "sent_at": now_iso(item.sent_at) if item.sent_at else None,
        "created_at": now_iso(item.created_at) if item.created_at else None,
    }


# ---------------------------------------------------------------------------
# 条件 / 动作归一化
# ---------------------------------------------------------------------------


def rule_condition_text(rule):
    """规则的有效条件表达式：手写优先，否则由可视化条件按顺序拼装。"""
    manual = (rule.condition or "").strip()
    if manual:
        return manual
    conditions = [c for c in rule.conditions.all() if c.enabled]
    items = [{
        "field": c.field,
        "operator": c.operator,
        "value": c.value,
        "logic_group": c.logic_group,
    } for c in conditions]
    return combine_conditions(items)


def normalize_actions(raw):
    """把 Rule.actions 里的多种写法（字符串/扁平 dict/带 params）归一化。

    统一成 {"type","params"} 之后，执行器与校验器只面对一种形状。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("动作列表不是合法 JSON")
    if not isinstance(raw, list):
        raise ValueError("动作列表必须是数组")
    if len(raw) > 50:
        raise ValueError("单条规则的动作数不能超过 50")
    out = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            action_type, params = item, {}
        elif isinstance(item, dict):
            action_type = item.get("type") or item.get("action") or ""
            params = item.get("params")
            if not isinstance(params, dict):
                params = {k: v for k, v in item.items()
                          if k not in ("type", "action", "id", "params")}
        else:
            raise ValueError(f"第 {index + 1} 个动作格式不正确")
        action_type = str(action_type or "").strip()
        if action_type not in ACTION_TYPES:
            raise ValueError(f"不支持的动作类型: {action_type or '(空)'}")
        out.append({"type": action_type, "params": params or {}})
    return out


def rule_actions(rule):
    """规则的有效动作：优先取可视化动作行，没有行时回落到 actions JSON。"""
    rows = list(rule.action_items.filter(enabled=True).order_by("sort_order", "id"))
    if rows:
        return [{"type": a.type, "params": a.params or {}, "id": a.id,
                 "sort_order": a.sort_order} for a in rows]
    return normalize_actions(rule.actions or [])


def action_signature(rule):
    actions = [{"type": a["type"], "params": a.get("params", {})}
               for a in rule_actions(rule)]
    return json.dumps(actions, sort_keys=True, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# 快照 / 版本 / 导入导出 / 回滚
# ---------------------------------------------------------------------------


def ruleset_snapshot(ruleset):
    """把规则集连同规则、变量、决策表序列化为可回滚快照。"""
    rules = []
    for rule in ruleset.rules.all().order_by("priority", "id"):
        rules.append({
            "name": rule.name,
            "description": rule.description,
            "priority": rule.priority,
            "enabled": rule.enabled,
            "condition": rule.condition,
            "actions": to_json(rule.actions or []),
            "tags": to_json(rule.tags or []),
            "conditions": [{
                "field": c.field, "operator": c.operator, "value": to_json(c.value),
                "logic_group": c.logic_group, "sort_order": c.sort_order,
                "enabled": c.enabled,
            } for c in rule.conditions.all()],
            "action_items": [{
                "type": a.type, "params": to_json(a.params or {}),
                "sort_order": a.sort_order, "enabled": a.enabled,
            } for a in rule.action_items.all()],
        })
    tables = []
    for table in ruleset.decision_tables.all().order_by("id"):
        tables.append({
            "name": table.name,
            "description": table.description,
            "inputs": to_json(table.inputs or []),
            "outputs": to_json(table.outputs or []),
            "hit_policy": table.hit_policy,
            "enabled": table.enabled,
            "rows": [{
                "conditions": to_json(row.conditions or {}),
                "outputs": to_json(row.outputs or {}),
                "priority": row.priority,
                "enabled": row.enabled,
                "remark": row.remark,
            } for row in table.rows.all()],
        })
    return {
        "format": "ruleset-snapshot",
        "format_version": 1,
        "ruleset": {
            "code": ruleset.code,
            "name": ruleset.name,
            "category": ruleset.category,
            "description": ruleset.description,
            "status": ruleset.status,
            "version_no": ruleset.version_no,
            "hit_policy": ruleset.hit_policy,
            "max_executions": ruleset.max_executions,
            "timeout_ms": ruleset.timeout_ms,
            "priority": ruleset.priority,
            "tags": to_json(ruleset.tags or []),
            "settings": to_json(ruleset.settings or {}),
        },
        "rules": rules,
        "variables": [{
            "name": v.name, "type": v.var_type,
            "default_value": to_json(v.default_value), "description": v.description,
        } for v in ruleset.variables.all()],
        "decision_tables": tables,
        "generated_at": timezone.now().isoformat(),
    }


def publish_ruleset(ruleset, user, note=""):
    """发布：生成版本快照 + 状态置为 active + 版本号自增（同一事务）。"""
    with transaction.atomic():
        locked = RuleSet.objects.select_for_update().get(pk=ruleset.pk)
        snapshot = ruleset_snapshot(locked)
        version = RuleSetVersion.objects.create(
            owner=locked.owner, ruleset=locked, version_no=locked.version_no,
            snapshot=snapshot, published_by=user,
            note=(note or "发布版本")[:500],
        )
        locked.status = "active"
        locked.version_no = locked.version_no + 1
        locked.save(update_fields=["status", "version_no", "updated_at"])
    return version


def _apply_snapshot(ruleset, snapshot, user):
    """用快照覆盖规则集内容（回滚/导入共用）；调用方负责事务边界。"""
    meta = snapshot.get("ruleset") if isinstance(snapshot, dict) else None
    if not isinstance(meta, dict):
        raise ValueError("快照缺少 ruleset 段")
    for field, max_len in (("name", 200), ("category", 60)):
        if meta.get(field):
            setattr(ruleset, field, str(meta[field])[:max_len])
    if "description" in meta:
        ruleset.description = str(meta.get("description") or "")
    if meta.get("hit_policy") in HIT_POLICIES:
        ruleset.hit_policy = meta["hit_policy"]
    for field, lo, hi in (("max_executions", 1, 1000), ("timeout_ms", 50, 60000),
                          ("priority", -100000, 100000)):
        if meta.get(field) is not None:
            setattr(ruleset, field, clamp_int(meta[field], getattr(ruleset, field), lo, hi))
    if isinstance(meta.get("tags"), list):
        ruleset.tags = to_json(meta["tags"])
    if isinstance(meta.get("settings"), dict):
        ruleset.settings = to_json(meta["settings"])
    if meta.get("status") in RULESET_STATUS:
        ruleset.status = meta["status"]
    ruleset.save()

    # 先清空子表：快照是完整态，增量合并会残留已删除的规则
    ruleset.rules.all().delete()
    ruleset.variables.all().delete()
    ruleset.decision_tables.all().delete()

    for item in snapshot.get("variables") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        RuleVariable.objects.create(
            owner=ruleset.owner, ruleset=ruleset, name=name[:80],
            var_type=item.get("type") if item.get("type") in VARIABLE_TYPES else "string",
            default_value=to_json(item.get("default_value")),
            description=str(item.get("description") or "")[:300],
        )

    for item in snapshot.get("rules") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        rule = Rule.objects.create(
            owner=ruleset.owner, ruleset=ruleset, name=name[:200],
            description=str(item.get("description") or "")[:500],
            priority=clamp_int(item.get("priority"), 100, -100000, 100000),
            enabled=bool(item.get("enabled", True)),
            condition=str(item.get("condition") or ""),
            actions=to_json(item.get("actions") or []),
            tags=to_json(item.get("tags") or []),
        )
        for cond in item.get("conditions") or []:
            field = str(cond.get("field") or "").strip()
            if not field:
                continue
            RuleCondition.objects.create(
                owner=ruleset.owner, rule=rule, field=field[:200],
                operator=str(cond.get("operator") or "==")[:20],
                value=to_json(cond.get("value")),
                logic_group=(cond.get("logic_group") or "and")[:3],
                sort_order=clamp_int(cond.get("sort_order"), 0, -10000, 10000),
                enabled=bool(cond.get("enabled", True)),
            )
        for action in item.get("action_items") or []:
            if action.get("type") not in ACTION_TYPES:
                continue
            RuleAction.objects.create(
                owner=ruleset.owner, rule=rule, type=action["type"],
                params=to_json(action.get("params") or {}),
                sort_order=clamp_int(action.get("sort_order"), 0, -10000, 10000),
                enabled=bool(action.get("enabled", True)),
            )

    for item in snapshot.get("decision_tables") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        table = RuleDecisionTable.objects.create(
            owner=ruleset.owner, ruleset=ruleset, name=name[:200],
            description=str(item.get("description") or "")[:500],
            inputs=to_json(item.get("inputs") or []),
            outputs=to_json(item.get("outputs") or []),
            hit_policy=item.get("hit_policy") if item.get("hit_policy") in HIT_POLICIES else "first",
            enabled=bool(item.get("enabled", True)),
        )
        for row in item.get("rows") or []:
            DecisionRow.objects.create(
                owner=ruleset.owner, table=table,
                conditions=to_json(row.get("conditions") or {}),
                outputs=to_json(row.get("outputs") or {}),
                priority=clamp_int(row.get("priority"), 100, -100000, 100000),
                enabled=bool(row.get("enabled", True)),
                remark=str(row.get("remark") or "")[:300],
            )


def rollback_ruleset(ruleset, version, user):
    """回滚到指定版本：覆盖当前内容，并把回滚动作也记成一个新版本。"""
    if version.ruleset_id != ruleset.id:
        raise ValueError("版本不属于该规则集")
    with transaction.atomic():
        locked = RuleSet.objects.select_for_update().get(pk=ruleset.pk)
        _apply_snapshot(locked, version.snapshot or {}, user)
        max_no = locked.versions.aggregate(m=Max("version_no"))["m"] or 0
        next_no = max(locked.version_no, version.version_no, max_no) + 1
        snapshot = ruleset_snapshot(locked)
        RuleSetVersion.objects.create(
            owner=locked.owner, ruleset=locked, version_no=next_no,
            snapshot=snapshot, published_by=user,
            note=f"回滚到 v{version.version_no}"[:500],
        )
        locked.version_no = next_no + 1
        locked.status = "active"
        locked.save(update_fields=["version_no", "status", "updated_at"])
    return ruleset_snapshot(locked)


def unique_code(user, base, suffix="_copy"):
    """生成同类下唯一的编码：base_copy、base_copy2……（长度截断到 64）。"""
    base = (base or "ruleset")[:60]
    existing = set(RuleSet.objects.filter(owner=user, code__startswith=base)
                   .values_list("code", flat=True))
    candidate = f"{base}{suffix}"[:64]
    index = 2
    while candidate in existing:
        candidate = f"{base}{suffix}{index}"[:64]
        index += 1
    return candidate


def clone_ruleset(ruleset, user, name=""):
    """克隆规则集：编码自动避让，名称默认加「副本」，内容深拷贝。"""
    snapshot = ruleset_snapshot(ruleset)
    code = unique_code(user, ruleset.code)
    snapshot["ruleset"]["code"] = code
    snapshot["ruleset"]["name"] = (name or f"{ruleset.name} 副本")[:200]
    snapshot["ruleset"]["status"] = "draft"
    snapshot["ruleset"]["version_no"] = 1
    with transaction.atomic():
        cloned = RuleSet.objects.create(
            owner=user, code=code, name=snapshot["ruleset"]["name"],
            category=ruleset.category, description=ruleset.description,
            status="draft", version_no=1, hit_policy=ruleset.hit_policy,
            max_executions=ruleset.max_executions, timeout_ms=ruleset.timeout_ms,
            priority=ruleset.priority, tags=to_json(ruleset.tags or []),
            settings=to_json(ruleset.settings or {}),
        )
        _apply_snapshot(cloned, snapshot, user)
    return cloned


def import_ruleset(user, payload, overwrite=False):
    """导入快照：编码冲突时默认报错，overwrite=True 才覆盖本人同编码规则集。"""
    snapshot = parse_json_arg(payload, "snapshot", dict)
    if not snapshot:
        raise ValueError("缺少快照内容")
    meta = snapshot.get("ruleset") or {}
    code = str(meta.get("code") or "").strip()
    if not code:
        raise ValueError("快照缺少规则集编码")
    if len(code) > 64:
        raise ValueError("规则集编码不能超过 64 字符")
    existing = RuleSet.objects.filter(owner=user, code=code).first()
    with transaction.atomic():
        if existing is not None:
            if not overwrite:
                raise ValueError(f"规则集编码 {code} 已存在，如需覆盖请传 overwrite=true")
            _apply_snapshot(existing, snapshot, user)
            existing.status = "draft"
            existing.save(update_fields=["status", "updated_at"])
            return existing
        ruleset = RuleSet.objects.create(
            owner=user, code=code,
            name=str(meta.get("name") or code)[:200],
            category=str(meta.get("category") or "导入")[:60],
            description=str(meta.get("description") or ""),
            status="draft", version_no=1,
            hit_policy=meta.get("hit_policy") if meta.get("hit_policy") in HIT_POLICIES else "first",
            max_executions=clamp_int(meta.get("max_executions"), 100, 1, 1000),
            timeout_ms=clamp_int(meta.get("timeout_ms"), 2000, 50, 60000),
            priority=clamp_int(meta.get("priority"), 0, -100000, 100000),
            tags=to_json(meta.get("tags") or []),
            settings=to_json(meta.get("settings") or {}),
        )
        _apply_snapshot(ruleset, snapshot, user)
    return ruleset


# ---------------------------------------------------------------------------
# 规则集校验
# ---------------------------------------------------------------------------


REQUIRED_ACTION_PARAMS = {
    "set_field": ("field",),
    "notify": (),
    "webhook": ("url",),
    "create_task": ("title",),
    "route": ("target",),
    "score": (),
    "flag": ("name",),
    "approve": (),
    "reject": (),
}


def validate_ruleset(ruleset):
    """静态校验：表达式、动作参数、变量使用、决策表结构，返回错误与告警。

    校验不执行求值：只解析 AST，避免用生产事实触发副作用。
    """
    errors, warnings = [], []
    variables = {v.name for v in ruleset.variables.all()}
    seen_priorities = {}
    rules = list(ruleset.rules.all().order_by("priority", "id"))
    enabled_rules = [r for r in rules if r.enabled]
    if not rules:
        warnings.append({"code": "empty_ruleset", "message": "规则集还没有任何规则"})
    if not enabled_rules:
        warnings.append({"code": "no_enabled_rule", "message": "没有启用的规则，评估永远不会命中"})

    for rule in rules:
        label = f"规则「{rule.name}」"
        try:
            text = rule_condition_text(rule)
            node = parse_expression(text)
            report = validate_expression(text)
        except ExprError as e:
            errors.append({"code": "bad_expression", "rule_id": rule.id,
                           "message": f"{label} 条件表达式非法: {e}"})
            continue
        except ValueError as e:
            errors.append({"code": "bad_condition", "rule_id": rule.id,
                           "message": f"{label} 条件配置错误: {e}"})
            continue
        if report["depth"] > MAX_DEPTH:
            errors.append({"code": "too_deep", "rule_id": rule.id,
                           "message": f"{label} 表达式嵌套过深"})
        missing = [v for v in report["variables"] if v not in variables
                   and not v.startswith(("facts.", "vars."))]
        if missing:
            warnings.append({"code": "unknown_variable", "rule_id": rule.id,
                             "message": f"{label} 使用了未定义的变量: {', '.join(missing[:5])}"})
        if seen_priorities.get(rule.priority):
            warnings.append({"code": "duplicate_priority", "rule_id": rule.id,
                             "message": f"{label} 与「{seen_priorities[rule.priority]}」优先级相同({rule.priority})"})
        else:
            seen_priorities[rule.priority] = rule.name
        try:
            actions = rule_actions(rule)
        except ValueError as e:
            errors.append({"code": "bad_actions", "rule_id": rule.id,
                           "message": f"{label} 动作配置错误: {e}"})
            continue
        if rule.enabled and not actions:
            warnings.append({"code": "no_action", "rule_id": rule.id,
                             "message": f"{label} 没有配置任何动作，命中后不会产生效果"})
        for index, action in enumerate(actions):
            for key in REQUIRED_ACTION_PARAMS.get(action["type"], ()):
                if not action["params"].get(key):
                    errors.append({
                        "code": "missing_param", "rule_id": rule.id,
                        "message": f"{label} 第 {index + 1} 个动作为 {action['type']}，缺少参数 {key}",
                    })
            if action["type"] == "webhook":
                url = str(action["params"].get("url") or "")
                if url and not url.startswith(("http://", "https://")):
                    errors.append({"code": "bad_url", "rule_id": rule.id,
                                   "message": f"{label} 的 webhook 地址必须以 http(s):// 开头"})
            if action["type"] == "set_field":
                try:
                    validate_path(str(action["params"].get("field") or ""))
                except ExprError as e:
                    errors.append({"code": "bad_path", "rule_id": rule.id,
                                   "message": f"{label} 设置字段路径非法: {e}"})
        if len(text) > MAX_EXPR_LEN:
            errors.append({"code": "too_long", "rule_id": rule.id,
                           "message": f"{label} 条件表达式超过长度上限"})
        if node.to_dict() == {"type": "literal", "value": False}:
            warnings.append({"code": "always_false", "rule_id": rule.id,
                             "message": f"{label} 条件恒为 false，规则不可达"})

    for table in ruleset.decision_tables.all():
        if not table.inputs:
            warnings.append({"code": "table_no_input", "table_id": table.id,
                             "message": f"决策表「{table.name}」没有输入列"})
        if not table.outputs:
            warnings.append({"code": "table_no_output", "table_id": table.id,
                             "message": f"决策表「{table.name}」没有输出列"})
        if table.hit_policy not in HIT_POLICIES:
            errors.append({"code": "table_bad_policy", "table_id": table.id,
                           "message": f"决策表「{table.name}」命中策略非法"})
        if not table.rows.exists():
            warnings.append({"code": "table_no_row", "table_id": table.id,
                             "message": f"决策表「{table.name}」还没有数据行"})

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "stats": {
            "rules": len(rules),
            "enabled_rules": len(enabled_rules),
            "variables": len(variables),
            "decision_tables": ruleset.decision_tables.count(),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
    }


# ---------------------------------------------------------------------------
# 评估引擎
# ---------------------------------------------------------------------------


def _variables_for(ruleset, overrides):
    """变量生效顺序：变量定义默认值 → 调用方覆盖值（灰度时只覆盖需要的变量）。"""
    values = {}
    for var in ruleset.variables.all():
        values[var.name] = to_json(var.default_value)
    for key, value in (overrides or {}).items():
        if isinstance(key, str) and key and not key.startswith("_"):
            values[key] = to_json(value)
    if len(values) > MAX_VARIABLES:
        raise ValueError(f"变量数量超过上限 {MAX_VARIABLES}")
    return values


def evaluate_rule(rule, facts, variables, with_trace=True):
    """评估单条规则，返回命中与否 + 表达式 + 条件树（含每步布尔值）。"""
    started = perf_counter()
    try:
        expression = rule_condition_text(rule)
    except (ExprError, ValueError) as e:
        return {
            "rule_id": rule.id, "name": rule.name, "priority": rule.priority,
            "matched": False, "expression": "", "error": f"条件配置错误: {e}",
            "duration_ms": perf_ms(started), "trace": None,
        }
    try:
        if with_trace:
            explained = explain_expression(expression, facts, variables)
            matched = bool(explained["value"])
            trace = explained["trace"]
        else:
            matched = bool(evaluate_expression(expression, facts, variables))
            trace = None
    except ExprError as e:
        return {
            "rule_id": rule.id, "name": rule.name, "priority": rule.priority,
            "matched": False, "expression": expression, "error": str(e),
            "duration_ms": perf_ms(started), "trace": None,
        }
    return {
        "rule_id": rule.id,
        "name": rule.name,
        "priority": rule.priority,
        "matched": matched,
        "expression": expression,
        "error": "",
        "duration_ms": perf_ms(started),
        "trace": trace,
    }


def _trim_trace(item, max_steps=120):
    """裁剪单条规则追踪的步数：完整追踪对前端无价值，JSON 字段要留余量。"""
    trace = item.get("trace")
    if not trace:
        return item
    trimmed = dict(trace)
    steps = list(trimmed.get("steps") or [])
    if len(steps) > max_steps:
        trimmed["steps"] = steps[:max_steps]
        trimmed["truncated"] = True
    item = dict(item)
    item["trace"] = trimmed
    return item


def _run_action(action_type, params, facts, variables, rule, ruleset, evaluation,
                owner, dry_run):
    """执行单个动作；返回结构化输出（outputs 会合并进决策结果）。"""
    params = params if isinstance(params, dict) else {}
    if action_type == "set_field":
        field = str(params.get("field") or params.get("target") or "").strip()
        if not field:
            raise ValueError("set_field 缺少 field 参数")
        validate_path(field)
        if "value_from" in params:
            value = resolve_path(str(params["value_from"]), facts, variables)
        else:
            value = render_value(params.get("value"), facts, variables)
        set_path(facts, field, to_json(value))
        return {"field": field, "value": to_json(value),
                "outputs": {field: to_json(value)}}
    if action_type == "score":
        field = str(params.get("field") or "score").strip()
        validate_path(field)
        raw_delta = params.get("delta", params.get("value", 1))
        if isinstance(raw_delta, str):
            raw_delta = render_template(raw_delta, facts, variables)
        try:
            delta = float(raw_delta)
        except (TypeError, ValueError):
            raise ValueError("score 的 delta 必须是数字")
        current = resolve_path(field, facts, variables)
        try:
            base = float(current) if current is not None else 0.0
        except (TypeError, ValueError):
            base = 0.0
        value = round(base + delta, 6)
        if value.is_integer():
            value = int(value)
        set_path(facts, field, value)
        return {"field": field, "delta": delta, "value": value,
                "outputs": {field: value}}
    if action_type == "flag":
        name = str(params.get("name") or params.get("flag") or "").strip()
        if not name:
            raise ValueError("flag 缺少 name 参数")
        if name.startswith("_"):
            raise ValueError("flag 名称不能以下划线开头")
        value = params.get("value", True)
        if isinstance(value, str):
            value = value.lower() in ("1", "true", "yes", "on")
        flags = facts.get("flags")
        if not isinstance(flags, dict):
            flags = {}
            facts["flags"] = flags
        flags[name] = bool(value)
        return {"name": name, "value": bool(value),
                "outputs": {"flags": dict(flags)}}
    if action_type == "route":
        target = str(params.get("target") or params.get("queue") or "").strip()
        if not target:
            raise ValueError("route 缺少 target 参数")
        target = render_template(target, facts, variables)
        facts["route"] = target
        return {"route": target, "outputs": {"route": target}}
    if action_type == "notify":
        title = render_template(str(params.get("title") or f"规则 {rule.name} 命中"),
                                facts, variables)[:300]
        body = render_template(str(params.get("message") or params.get("body") or ""),
                               facts, variables)[:20000]
        target = render_template(str(params.get("to") or params.get("target") or ""),
                                 facts, variables)[:300]
        payload = {
            "params": to_json(params),
            "facts_snapshot": to_json({
                k: facts.get(k) for k in list(facts)[:30]
            }),
        }
        if dry_run:
            return {"channel": "inapp", "target": target, "title": title,
                    "simulated": True, "outputs": {"notified": True}}
        notification = RuleNotification.objects.create(
            owner=owner or rule.owner, ruleset=ruleset or rule.ruleset,
            rule=rule, evaluation=evaluation, channel="inapp", target=target,
            title=title, body=body, status="sent", payload=payload,
            sent_at=timezone.now(),
        )
        return {"channel": "inapp", "notification_id": notification.id,
                "target": target, "title": title,
                "outputs": {"notified": True}}
    if action_type == "webhook":
        url = str(params.get("url") or "").strip()
        if not url:
            raise ValueError("webhook 缺少 url 参数")
        if not url.startswith(("http://", "https://")):
            raise ValueError("webhook 地址必须以 http(s):// 开头")
        method = str(params.get("method") or "POST").upper()
        body = render_value(params.get("payload") or params.get("body") or {},
                            facts, variables)
        payload = {"method": method, "url": url, "body": to_json(body), "mode": "simulated"}
        if dry_run:
            return {"url": url, "delivery": "simulated",
                    "outputs": {"webhook_queued": True}}
        # 平台禁止联网：webhook 只入库排队，由外部投递器消费，绝不在此发起请求
        notification = RuleNotification.objects.create(
            owner=owner or rule.owner, ruleset=ruleset or rule.ruleset,
            rule=rule, evaluation=evaluation, channel="webhook", target=url[:300],
            title=render_template(str(params.get("title") or "规则 webhook"),
                                  facts, variables)[:300],
            body="", status="queued", payload=payload,
        )
        return {"url": url, "delivery": "queued",
                "notification_id": notification.id,
                "outputs": {"webhook_queued": True}}
    if action_type == "create_task":
        title = render_template(str(params.get("title") or ""), facts, variables).strip()
        if not title:
            raise ValueError("create_task 缺少 title 参数")
        due_days = params.get("due_days")
        due_date = None
        if due_days not in (None, ""):
            try:
                due_days = int(due_days)
            except (TypeError, ValueError):
                raise ValueError("create_task 的 due_days 必须是整数")
            if due_days < 0 or due_days > 3650:
                raise ValueError("create_task 的 due_days 必须在 0~3650 之间")
            due_date = timezone.localdate() + timedelta(days=due_days)
        if dry_run:
            return {"title": title[:300],
                    "due_date": due_date.isoformat() if due_date else None,
                    "simulated": True, "outputs": {"task_created": True}}
        assignee = _resolve_user(params)
        task = RuleTask.objects.create(
            owner=owner or rule.owner, ruleset=ruleset or rule.ruleset, rule=rule,
            evaluation=evaluation, title=title[:300], assignee=assignee,
            due_date=due_date, status="open",
            payload={"params": to_json(params), "facts": to_json(facts)},
        )
        return {"task_id": task.id, "title": task.title,
                "assignee": user_payload(assignee),
                "due_date": due_date.isoformat() if due_date else None,
                "outputs": {"task_created": True}}
    if action_type in ("approve", "reject"):
        decision = "approved" if action_type == "approve" else "rejected"
        reason = render_template(str(params.get("reason") or ""), facts, variables)
        facts["decision"] = decision
        facts["decision_reason"] = reason
        return {"decision": decision, "reason": reason,
                "outputs": {"decision": decision}}
    raise ValueError(f"未知动作类型: {action_type}")


def render_value(value, facts, variables):
    """递归渲染动作参数中的模板占位符（dict/list/str）。"""
    if isinstance(value, str):
        return render_template(value, facts, variables)
    if isinstance(value, dict):
        return {k: render_value(v, facts, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, facts, variables) for v in value]
    return value


def set_path(data, path, value):
    """按点分路径写入 dict，中间节点不存在时自动建对象。"""
    validate_path(path)
    parts = path.split(".")
    cursor = data
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = value


def _resolve_user(params):
    """动作里的处理人：优先 id，其次 username/nickname；找不到返回 None 不阻断。"""
    raw_id = params.get("assignee_id")
    User = get_user_model()
    if raw_id not in (None, ""):
        try:
            user = User.objects.filter(pk=int(raw_id)).first()
        except (TypeError, ValueError):
            user = None
        if user is not None:
            return user
    name = str(params.get("assignee") or params.get("assignee_username") or "").strip()
    if name:
        return User.objects.filter(Q(username=name) | Q(nickname=name)).first()
    return None


def execute_actions(rule, facts, variables, ruleset=None, evaluation=None,
                    owner=None, dry_run=False):
    """按顺序执行规则动作，逐条记录日志；单条失败不影响后续动作。"""
    results = []
    actions = rule_actions(rule)
    for action in actions:
        started = perf_counter()
        status, error, output = "success", "", {}
        try:
            output = _run_action(action["type"], action.get("params") or {}, facts,
                                 variables, rule, ruleset, evaluation, owner, dry_run)
        except Exception as e:  # noqa: BLE001 —— 动作失败必须留痕，不能中断整批评估
            status = "failed"
            error = str(e) or type(e).__name__
            output = {}
        duration = perf_ms(started)
        log_id = None
        if evaluation is not None and not dry_run:
            log = RuleExecutionLog.objects.create(
                owner=owner or rule.owner, evaluation=evaluation, rule=rule,
                rule_name=rule.name[:200], action_type=action["type"],
                status=status, error=error, retries=0, duration_ms=duration,
                detail={"params": to_json(action.get("params") or {}),
                        "output": to_json(output)},
            )
            log_id = log.id
        results.append({
            "type": action["type"], "status": status, "error": error,
            "duration_ms": duration, "output": to_json(output),
            "log_id": log_id, "rule_id": rule.id, "rule_name": rule.name,
        })
    return {"facts": facts, "results": results}


def _select_matched(matched, ruleset):
    """按命中策略取舍：matched 已按优先级排序（数值小优先）。"""
    policy = ruleset.hit_policy if ruleset.hit_policy in HIT_POLICIES else "first"
    if policy == "first":
        return matched[:1], policy
    if policy == "priority":
        return (matched[:1] if matched else []), policy
    return matched, policy


def evaluate_ruleset(ruleset, facts, variables=None, caller="api", trace_id="",
                     source="manual", owner=None, persist=True, dry_run=False,
                     with_trace=True, extra_decision=None):
    """评估整套规则：条件 → 命中策略 → 动作 → 决策，持久化评估与执行日志。

    返回结构里的 trace 是给前端调试的：每条规则一棵条件树 + 逐步布尔值。
    """
    if facts is None:
        facts = {}
    if isinstance(facts, str):
        facts = parse_json_arg(facts, "facts", dict)
    if not isinstance(facts, dict):
        raise ValueError("事实(facts)必须是 JSON 对象")
    if variables is not None and not isinstance(variables, dict):
        raise ValueError("变量(variables)必须是 JSON 对象")
    owner = owner or ruleset.owner
    merged_vars = _variables_for(ruleset, variables)
    trace_id = (trace_id or uuid.uuid4().hex)[:64]
    started = perf_counter()
    budget_ms = max(int(ruleset.timeout_ms or 2000), 50)
    deadline = started + budget_ms / 1000.0
    limit = max(1, min(int(ruleset.max_executions or 100), 1000))

    evaluation = None
    transaction_scope = transaction.atomic() if persist else nullcontext()
    try:
        with transaction_scope:
            if persist:
                evaluation = RuleEvaluation.objects.create(
                    owner=owner, ruleset=ruleset, ruleset_code=ruleset.code,
                    facts=to_json(facts), variables=merged_vars,
                    caller=(caller or "api")[:100], trace_id=trace_id,
                    status="running", source=source[:40],
                )
            rules = list(ruleset.rules.filter(enabled=True)
                         .order_by("priority", "id")[:limit])
            rule_traces, matched, errors = [], [], []
            status = "success"
            for rule in rules:
                if perf_counter() > deadline:
                    status = "timeout"
                    errors.append({"rule_id": rule.id, "rule_name": rule.name,
                                   "error": f"执行超过 {budget_ms}ms 预算，剩余规则未评估"})
                    break
                item = evaluate_rule(rule, facts, merged_vars, with_trace=with_trace)
                if item.get("error"):
                    errors.append({"rule_id": rule.id, "rule_name": rule.name,
                                   "error": item["error"]})
                    # 单条规则表达式坏了只降级，不拖垮整套规则（其余规则仍可命中）
                    if status == "success":
                        status = "degraded"
                if item["matched"]:
                    matched.append(rule)
                rule_traces.append(_trim_trace(item))

            selected, policy = _select_matched(matched, ruleset)
            context = copy.deepcopy(facts)
            action_results, per_rule_outputs = [], []
            for rule in selected:
                outcome = execute_actions(
                    rule, context, merged_vars, ruleset=ruleset,
                    evaluation=evaluation, owner=owner,
                    dry_run=dry_run or not persist,
                )
                context = outcome["facts"]
                rule_output = {}
                for res in outcome["results"]:
                    if res["status"] != "success":
                        continue
                    for key, value in (res["output"].get("outputs") or {}).items():
                        rule_output[key] = value
                if rule_output:
                    per_rule_outputs.append({"rule_id": rule.id, "name": rule.name,
                                             "outputs": to_json(rule_output)})
                action_results.extend(outcome["results"])

            outputs, decision_value = {}, "no_match"
            collected = {}
            for item in per_rule_outputs:
                for key, value in item["outputs"].items():
                    outputs[key] = value
                    if policy == "collect":
                        collected.setdefault(key, []).append(value)
            if matched:
                decision_value = "matched"
            for res in action_results:
                if res["status"] == "success" and res["output"].get("decision"):
                    decision_value = res["output"]["decision"]

            duration = perf_ms(started)
            decision = {
                "matched": bool(matched),
                "matched_count": len(matched),
                "hit_policy": policy,
                "decision": decision_value,
                "rules": [{"id": r.id, "name": r.name, "priority": r.priority}
                          for r in matched],
                "outputs": to_json(per_rule_outputs if policy == "collect" else outputs),
                "actions": action_results,
                "facts_after": to_json(context),
                "errors": errors,
            }
            if policy == "collect":
                decision["collected"] = to_json(collected)
            if extra_decision:
                decision.update(to_json(extra_decision))
            trace_payload = {
                "ruleset": {"id": ruleset.id, "code": ruleset.code,
                            "hit_policy": policy, "timeout_ms": budget_ms,
                            "max_executions": limit},
                "rules": rule_traces,
                "rule_count": len(rules),
                "elapsed_ms": duration,
                "truncated": any((t.get("trace") or {}).get("truncated")
                                 for t in rule_traces),
            }
            if persist and evaluation is not None:
                evaluation.matched_rules = [
                    {"id": r.id, "name": r.name, "priority": r.priority}
                    for r in matched
                ]
                evaluation.decision = to_json(decision)
                evaluation.trace = to_json(trace_payload)
                evaluation.duration_ms = duration
                evaluation.status = status
                evaluation.error = "; ".join(e["error"] for e in errors)[:2000]
                evaluation.save()
            if matched and persist:
                now = timezone.now()
                Rule.objects.filter(id__in=[r.id for r in matched]).update(
                    hit_count=F("hit_count") + 1, last_hit_at=now,
                )
            return {
                "evaluation_id": evaluation.id if evaluation else None,
                "trace_id": trace_id,
                "ruleset": {"id": ruleset.id, "code": ruleset.code,
                            "name": ruleset.name, "hit_policy": policy},
                "matched": bool(matched),
                "decision": to_json(decision),
                "trace": to_json(trace_payload),
                "duration_ms": duration,
                "status": status,
                "errors": errors,
                "logs": [r for r in action_results],
                "persisted": bool(persist),
            }
    except Exception:
        if evaluation is not None and evaluation.pk:
            RuleEvaluation.objects.filter(pk=evaluation.pk).update(
                status="error", duration_ms=perf_ms(started),
                error="评估过程中出现未预期异常",
            )
        raise


# ---------------------------------------------------------------------------
# 未命中诊断 / 重新评估
# ---------------------------------------------------------------------------


def _missing_fact_paths(expression, facts, variables):
    """找出表达式引用但事实里取不到值的路径（区分「变量已定义」的情况）。"""
    try:
        node = parse_expression(expression)
    except ExprError:
        return []
    missing = []
    for item in node.walk():
        name = getattr(item, "path", None)
        if not name or name in variables:
            continue
        parts = name.split(".")
        if parts and parts[0] in ("facts", "vars"):
            continue
        value = resolve_path(name, facts, variables)
        if value is None:
            missing.append(name)
    return sorted(set(missing))


def diagnose_miss(evaluation):
    """未命中诊断：逐条规则给出失败的那一步与缺失事实，帮助定位配置问题。"""
    if not evaluation.ruleset_id:
        return {"matched": bool((evaluation.decision or {}).get("matched")),
                "message": "规则集已删除，无法诊断", "rules": []}
    ruleset = evaluation.ruleset
    facts = evaluation.facts or {}
    variables = evaluation.variables or {}
    diagnosis = []
    for rule in ruleset.rules.filter(enabled=True).order_by("priority", "id"):
        try:
            expression = rule_condition_text(rule)
        except (ExprError, ValueError) as e:
            diagnosis.append({"rule_id": rule.id, "name": rule.name, "matched": False,
                              "error": f"条件配置错误: {e}", "failed_step": None,
                              "missing_facts": []})
            continue
        item = evaluate_rule(rule, facts, variables, with_trace=True)
        failed_step = None
        for step in ((item.get("trace") or {}).get("steps") or []):
            if step.get("bool") is False:
                failed_step = step
                break
        diagnosis.append({
            "rule_id": rule.id,
            "name": rule.name,
            "priority": rule.priority,
            "matched": item["matched"],
            "error": item.get("error") or "",
            "expression": expression,
            "failed_step": failed_step,
            "missing_facts": _missing_fact_paths(expression, facts, variables),
        })
    matched = [d for d in diagnosis if d["matched"]]
    hints = []
    if not matched:
        missing = sorted({path for d in diagnosis for path in d["missing_facts"]})
        if missing:
            hints.append(f"事实中缺少字段: {', '.join(missing[:10])}")
        failed = [d for d in diagnosis if d.get("failed_step")]
        if failed:
            hints.append(f"共 {len(failed)} 条规则在首个比较处为 false，可放宽对应条件或修正事实")
        if not diagnosis:
            hints.append("规则集没有启用的规则")
    return {
        "matched": bool(matched),
        "evaluation_id": evaluation.id,
        "rules": diagnosis,
        "hints": hints,
    }


def reevaluate(evaluation, user):
    """用原事实重新评估（规则可能已改），新评估注明来源评估 id。"""
    if not evaluation.ruleset_id:
        raise ValueError("原规则集已删除，无法重新评估")
    return evaluate_ruleset(
        evaluation.ruleset, evaluation.facts or {},
        variables=evaluation.variables or {},
        caller=evaluation.caller or "reevaluate", trace_id=evaluation.trace_id,
        source="reevaluate", owner=user, persist=True,
        extra_decision={"previous_evaluation_id": evaluation.id},
    )


# ---------------------------------------------------------------------------
# 决策表
# ---------------------------------------------------------------------------


def table_columns(raw, prefix):
    """归一化输入/输出列：支持 ["amount"] 与 [{"name","field","type"}] 两种写法。"""
    items = []
    if raw is None:
        return items
    if isinstance(raw, str):
        raw = parse_json_arg(raw, prefix, list)
    if not isinstance(raw, list):
        raise ValueError(f"{prefix} 必须是数组")
    if len(raw) > 50:
        raise ValueError(f"{prefix} 最多 50 列")
    for index, item in enumerate(raw):
        if isinstance(item, str):
            name = field = item.strip()
            col_type = "auto"
        elif isinstance(item, dict):
            field = str(item.get("field") or item.get("name") or "").strip()
            name = str(item.get("name") or field or f"col{index + 1}").strip()
            col_type = str(item.get("type") or "auto")
        else:
            raise ValueError(f"{prefix} 第 {index + 1} 列格式不正确")
        if not name:
            raise ValueError(f"{prefix} 第 {index + 1} 列缺少列名")
        validate_path(field or name)
        items.append({"name": name[:80], "field": (field or name)[:200],
                      "type": col_type})
    return items


def table_inputs(table):
    return table_columns(table.inputs or [], "输入列")


def table_outputs(table):
    return table_columns(table.outputs or [], "输出列")


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _compare_values(op, actual, expected):
    """单元格比较：数字按数值、字符串忽略大小写，类型不兼容一律不命中。"""
    na, ne = _num(actual), _num(expected)
    if na is not None and ne is not None:
        left, right = na, ne
    elif isinstance(actual, str) and isinstance(expected, str):
        left, right = actual.strip().lower(), expected.strip().lower()
    elif isinstance(actual, bool) and isinstance(expected, bool):
        left, right = actual, expected
    else:
        return False
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op in ("!=", "<>"):
        return left != right
    return left == right


def cell_matches(cell, actual):
    """判断一个条件单元格是否命中。

    支持语法：
    - 通配：None / 空串 / "*"
    - 比较前缀：> >= < <= != = ==
    - 区间：100..200（闭区间）
    - 集合：a|b|c 或数组
    - 对象：{"min","max"} / {"in":[...]} / {"op","value"} / {"not":...}
    """
    if cell is None or cell == "" or cell == "*":
        return True
    if isinstance(cell, bool):
        return isinstance(actual, bool) and actual is cell
    if isinstance(cell, (int, float)):
        return _compare_values("==", actual, cell)
    if isinstance(cell, (list, tuple)):
        return any(cell_matches(item, actual) for item in cell)
    if isinstance(cell, dict):
        if not cell:
            return True
        if "not" in cell:
            return not cell_matches(cell.get("not"), actual)
        if "in" in cell:
            options = cell.get("in")
            if not isinstance(options, (list, tuple)):
                options = [options]
            return any(cell_matches(item, actual) for item in options)
        if "min" in cell or "max" in cell:
            low, high = cell.get("min"), cell.get("max")
            if low is not None and not _compare_values(">=", actual, low):
                return False
            if high is not None and not _compare_values("<=", actual, high):
                return False
            return low is not None or high is not None
        if "op" in cell:
            return _compare_values(str(cell.get("op")), actual, cell.get("value"))
        return values_equal(cell, actual)
    text = str(cell).strip()
    if text == "" or text == "*":
        return True
    for op in ("!=", ">=", "<=", ">", "<", "==", "="):
        if text.startswith(op):
            expected = text[len(op):].strip()
            if op == "=":
                op = "=="
            return _compare_values(op, actual, expected)
    if ".." in text:
        low, _, high = text.partition("..")
        low, high = low.strip(), high.strip()
        if not low or not high:
            return False
        return (_compare_values(">=", actual, low)
                and _compare_values("<=", actual, high))
    if "|" in text:
        return any(cell_matches(part.strip(), actual) for part in text.split("|"))
    return _compare_values("==", actual, text)


def _row_data(row):
    """把模型行/dict 行统一成 plain dict，便于试算时传内存行。"""
    if isinstance(row, dict):
        return {
            "id": row.get("id"),
            "conditions": row.get("conditions") or {},
            "outputs": row.get("outputs") or {},
            "priority": clamp_int(row.get("priority"), 100, -100000, 100000),
            "enabled": bool(row.get("enabled", True)),
            "remark": str(row.get("remark") or ""),
        }
    return {
        "id": row.id,
        "conditions": row.conditions or {},
        "outputs": row.outputs or {},
        "priority": row.priority,
        "enabled": row.enabled,
        "remark": row.remark,
    }


def _row_outputs(row_data, columns):
    """按输出列抽取行输出：优先列名，其次字段名，最后带上全部自定义键。"""
    raw = row_data["outputs"] if isinstance(row_data["outputs"], dict) else {}
    result = {}
    if columns:
        for col in columns:
            if col["name"] in raw:
                result[col["name"]] = to_json(raw[col["name"]])
            elif col["field"] in raw:
                result[col["name"]] = to_json(raw[col["field"]])
            else:
                result[col["name"]] = None
    else:
        result = {str(k): to_json(v) for k, v in raw.items()}
    for key, value in raw.items():
        if key not in result:
            result[str(key)] = to_json(value)
    return result


def evaluate_decision_table(table, facts, hit_policy=None, rows=None, with_trace=True):
    """决策表求值：逐行逐列判定，按 first/all/priority/collect 汇总输出。"""
    if facts is None:
        facts = {}
    if not isinstance(facts, dict):
        raise ValueError("事实(facts)必须是 JSON 对象")
    policy = hit_policy or table.hit_policy or "first"
    if policy not in HIT_POLICIES:
        raise ValueError(f"不支持的命中策略: {policy}")
    inputs = table_inputs(table)
    outputs = table_outputs(table)
    if rows is None:
        row_items = [_row_data(r) for r in
                     table.rows.filter(enabled=True).order_by("priority", "id")]
        from_db = True
    else:
        row_items = []
        for row in rows:
            data = _row_data(row)
            if data["enabled"]:
                row_items.append(data)
        from_db = False
    row_items.sort(key=lambda r: (r["priority"], r["id"] or 0))
    trace, matched = [], []
    for row in row_items:
        cells, row_ok = [], True
        for col in inputs:
            cell = row["conditions"].get(col["name"], row["conditions"].get(col["field"]))
            value = resolve_path(col["field"], facts) if col["field"] else None
            ok = cell_matches(cell, value)
            if not ok:
                row_ok = False
            if with_trace:
                cells.append({
                    "column": col["name"], "field": col["field"],
                    "cell": to_json(cell), "value": to_json(value), "matched": ok,
                })
        outputs_value = _row_outputs(row, outputs)
        if with_trace:
            trace.append({
                "row_id": row["id"], "priority": row["priority"],
                "matched": row_ok, "cells": cells, "outputs": outputs_value,
                "remark": row["remark"],
            })
        if row_ok:
            matched.append((row, outputs_value))
    if policy in ("first", "priority"):
        chosen = matched[:1]
        result_outputs = chosen[0][1] if chosen else {}
        collected = {}
    else:
        chosen = matched
        result_outputs = [item[1] for item in chosen]
        collected = {}
        for _, out in chosen:
            for key, value in out.items():
                collected.setdefault(key, []).append(value)
    result = {
        "table_id": table.id,
        "name": table.name,
        "hit_policy": policy,
        "matched": bool(matched),
        "matched_rows": [{"id": r["id"], "priority": r["priority"]}
                         for r, _ in matched],
        "matched_count": len(matched),
        "outputs": to_json(result_outputs),
        "row_count": len(row_items),
        "trace": trace if with_trace else [],
        "source": "database" if from_db else "inline",
    }
    if policy == "collect":
        result["collected"] = to_json(collected)
    return result


def save_table_rows(table, rows, replace=False):
    """批量保存决策表行：有 id 走更新，无 id 新建；replace=True 先清空。"""
    if isinstance(rows, str):
        rows = parse_json_arg(rows, "rows", list)
    if not isinstance(rows, list):
        raise ValueError("rows 必须是数组")
    if len(rows) > 500:
        raise ValueError("单次最多保存 500 行")
    saved = []
    with transaction.atomic():
        if replace:
            table.rows.all().delete()
        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index + 1} 行格式不正确")
            conditions = item.get("conditions") or {}
            outputs = item.get("outputs") or {}
            if not isinstance(conditions, dict):
                raise ValueError(f"第 {index + 1} 行的 conditions 必须是对象")
            if not isinstance(outputs, dict):
                raise ValueError(f"第 {index + 1} 行的 outputs 必须是对象")
            row = None
            if item.get("id") not in (None, ""):
                row = table.rows.filter(pk=item["id"]).first()
                if row is None:
                    raise ValueError(f"第 {index + 1} 行不存在或不属于该决策表")
            if row is None:
                row = DecisionRow(owner=table.owner, table=table)
            row.conditions = to_json(conditions)
            row.outputs = to_json(outputs)
            row.priority = clamp_int(item.get("priority"), 100 + index, -100000, 100000)
            row.enabled = bool(item.get("enabled", True))
            row.remark = str(item.get("remark") or "")[:300]
            row.save()
            saved.append(row)
    return saved


# ---------------------------------------------------------------------------
# 冲突检测
# ---------------------------------------------------------------------------


def _flatten_and(node):
    """把 AND 树拆成合取项集合：用于判定两条规则条件的包含/重叠关系。"""
    terms = []

    def walk(item):
        if isinstance(item, LogicalNode) and item.op == "and":
            walk(item.left)
            walk(item.right)
        else:
            terms.append(item.signature())

    walk(node)
    return terms


def _rule_meta(rule):
    expression = rule_condition_text(rule)
    node = parse_expression(expression)
    return {
        "rule": rule,
        "expression": expression,
        "signature": node.signature(),
        "terms": _flatten_and(node),
        "literal": node.to_dict().get("value") if node.kind == "literal" else None,
        "is_literal": node.kind == "literal",
        "actions": action_signature(rule),
    }


def _conflict_add(items, seen, ruleset, rule_a, rule_b, conflict_type, severity,
                  detail):
    key = (conflict_type, rule_a.id, rule_b.id if rule_b else None)
    if key in seen:
        return
    seen.add(key)
    items.append({
        "ruleset_id": ruleset.id,
        "rule_a": rule_a,
        "rule_b": rule_b,
        "conflict_type": conflict_type,
        "severity": severity,
        "detail": {
            "rule_a": {"id": rule_a.id, "name": rule_a.name,
                       "priority": rule_a.priority,
                       "expression": detail.get("expression_a", "")},
            "rule_b": ({"id": rule_b.id, "name": rule_b.name,
                        "priority": rule_b.priority,
                        "expression": detail.get("expression_b", "")}
                       if rule_b else None),
            "reason": detail.get("reason", ""),
            "shared_terms": detail.get("shared_terms", []),
        },
        "status": "open",
    })


def detect_rule_conflicts(ruleset, persist=True):
    """检测同一规则集内的条件等价/包含/同优先级重叠/不可达规则。

    采用 AST 规范化签名做深比较（不是字符串比较），因此
    `a > 1 and b == 2` 与 `b == 2 and a > 1` 会被识别为等价。
    """
    rules = list(ruleset.rules.filter(enabled=True).order_by("priority", "id"))
    meta_list, invalid = [], []
    for rule in rules:
        try:
            meta_list.append(_rule_meta(rule))
        except (ExprError, ValueError) as e:
            invalid.append({"rule_id": rule.id, "name": rule.name,
                            "error": str(e)})
    items, seen = [], set()
    shadow_matters = ruleset.hit_policy in ("first", "priority")

    for index, meta in enumerate(meta_list):
        rule = meta["rule"]
        # 恒 false 的规则永远命中不了：直接判不可达
        if meta["is_literal"] and meta["literal"] is False:
            _conflict_add(items, seen, ruleset, rule, None, "unreachable", "high", {
                "reason": "条件恒为 false，规则永远不会命中",
                "expression_a": meta["expression"],
            })
        for other in meta_list[index + 1:]:
            other_rule = other["rule"]
            higher, lower = (rule, other_rule) if (
                rule.priority, rule.id) <= (other_rule.priority, other_rule.id) else (
                other_rule, rule)
            terms_a, terms_b = set(meta["terms"]), set(other["terms"])
            # 合取项顺序不同但集合相同 → 仍视为条件等价（AST 深比较而非字符串比较）
            equivalent = (meta["signature"] == other["signature"]
                          or (terms_a and terms_a == terms_b))
            if equivalent:
                if meta["actions"] == other["actions"]:
                    severity = "high" if rule.priority == other_rule.priority else "medium"
                    _conflict_add(items, seen, ruleset, higher, lower, "duplicate",
                                  severity, {
                                      "reason": "两条规则条件完全等价，动作也相同",
                                      "expression_a": meta["expression"],
                                      "expression_b": other["expression"],
                                  })
                else:
                    _conflict_add(items, seen, ruleset, higher, lower,
                                  "contradiction", "high", {
                                      "reason": "条件完全等价但动作不同，命中结果不确定",
                                      "expression_a": meta["expression"],
                                      "expression_b": other["expression"],
                                      "shared_terms": meta["terms"],
                                  })
                continue

            # 恒 true 的规则在首条命中/优先级策略下会覆盖它后面的所有规则
            if (shadow_matters and meta["is_literal"] and meta["literal"] is True
                    and higher is rule):
                _conflict_add(items, seen, ruleset, rule, other_rule, "shadowed", "high", {
                    "reason": (f"「{rule.name}」条件恒为 true 且优先级更高，"
                               f"「{other_rule.name}」永远不会被评估"),
                    "expression_a": meta["expression"],
                    "expression_b": other["expression"],
                })
                continue

            shared = sorted(terms_a & terms_b)
            # 条件包含：一方条件集是另一方子集 → 更宽的那条在 first/priority 下覆盖窄的
            if shadow_matters and terms_a and terms_b:
                if terms_a < terms_b and higher is rule:
                    _conflict_add(items, seen, ruleset, rule, other_rule,
                                  "shadowed", "high", {
                                      "reason": (f"「{rule.name}」条件更宽且优先级更高，"
                                                 f"「{other_rule.name}」在首条命中策略下不可达"),
                                      "expression_a": meta["expression"],
                                      "expression_b": other["expression"],
                                      "shared_terms": shared,
                                  })
                elif terms_b < terms_a and higher is other_rule:
                    _conflict_add(items, seen, ruleset, other_rule, rule,
                                  "shadowed", "high", {
                                      "reason": (f"「{other_rule.name}」条件更宽且优先级更高，"
                                                 f"「{rule.name}」在首条命中策略下不可达"),
                                      "expression_a": other["expression"],
                                      "expression_b": meta["expression"],
                                      "shared_terms": shared,
                                  })
            if (rule.priority == other_rule.priority and shared
                    and not (terms_a <= terms_b or terms_b <= terms_a)):
                _conflict_add(items, seen, ruleset, higher, lower, "overlap",
                              "medium", {
                                  "reason": "同优先级且条件有交集，可能同时命中",
                                  "expression_a": meta["expression"],
                                  "expression_b": other["expression"],
                                  "shared_terms": shared,
                              })

    if persist:
        with transaction.atomic():
            ruleset.conflicts.filter(status="open").delete()
            for item in items:
                RuleConflict.objects.create(
                    owner=ruleset.owner, ruleset=ruleset,
                    rule_a=item["rule_a"], rule_b=item["rule_b"],
                    conflict_type=item["conflict_type"],
                    severity=item["severity"], status="open",
                    detail=to_json(item["detail"]),
                )
    return {
        "ruleset_id": ruleset.id,
        "conflicts": [
            {
                "rule_a": {"id": i["rule_a"].id, "name": i["rule_a"].name},
                "rule_b": ({"id": i["rule_b"].id, "name": i["rule_b"].name}
                           if i["rule_b"] else None),
                "conflict_type": i["conflict_type"],
                "severity": i["severity"],
                "detail": to_json(i["detail"]),
            } for i in items
        ],
        "count": len(items),
        "invalid_rules": invalid,
        "hit_policy": ruleset.hit_policy,
        "persisted": bool(persist),
    }


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


def _decision_view(result):
    """把评估结果压成用例断言关心的字段。"""
    decision = result.get("decision") or {}
    facts_after = decision.get("facts_after") or {}
    return {
        "matched": bool(decision.get("matched", result.get("matched"))),
        "rules": [r.get("name") for r in (decision.get("rules") or [])],
        "decision": decision.get("decision"),
        "outputs": decision.get("outputs"),
        "collected": decision.get("collected"),
        "score": facts_after.get("score"),
        "route": facts_after.get("route"),
        "flags": facts_after.get("flags"),
    }


def run_test_case(case, persist=True):
    """运行单个用例：实际输出 vs 期望输出（子集匹配），并回写通过状态。"""
    if not case.ruleset_id:
        raise ValueError("用例所属规则集已删除")
    started = perf_counter()
    result = evaluate_ruleset(
        case.ruleset, case.facts or {}, caller="testcase", source="testcase",
        owner=case.owner, persist=False, dry_run=True, with_trace=False,
    )
    actual = _decision_view(result)
    expected = case.expected or {}
    checks, passed = [], True
    for key, expected_value in expected.items():
        if key not in actual:
            checks.append({"field": key, "ok": False,
                           "reason": "不支持的期望字段", "expected": expected_value,
                           "actual": None})
            passed = False
            continue
        ok = subset_match(expected_value, actual[key])
        if not ok:
            passed = False
        checks.append({"field": key, "ok": ok, "expected": expected_value,
                       "actual": to_json(actual[key])})
    if not expected:
        checks.append({"field": "matched", "ok": True,
                       "reason": "未声明期望，仅记录实际输出"})
    last_result = {
        "actual": to_json(actual),
        "checks": checks,
        "status": result["status"],
        "duration_ms": result["duration_ms"],
        "evaluated_at": timezone.now().isoformat(),
    }
    if persist:
        case.passed = passed
        case.last_run_at = timezone.now()
        case.last_result = to_json(last_result)
        case.save(update_fields=["passed", "last_run_at", "last_result", "updated_at"])
    return {
        "case_id": case.id,
        "name": case.name,
        "passed": passed,
        "checks": checks,
        "actual": to_json(actual),
        "status": result["status"],
        "duration_ms": perf_ms(started),
        "evaluation": {
            "matched": result["matched"],
            "status": result["status"],
            "rules": (result["decision"] or {}).get("rules", []),
        },
    }


def run_all_cases(ruleset, persist=True):
    """批量运行规则集下的所有用例，返回通过率与命中规则集合。"""
    cases = list(ruleset.test_cases.all())
    items = [run_test_case(case, persist=persist) for case in cases]
    passed = sum(1 for item in items if item["passed"])
    total = len(items)
    return {
        "ruleset_id": ruleset.id,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "items": items,
    }


def test_coverage(ruleset):
    """覆盖率：用例实际命中过多少条启用规则，并列出未覆盖规则。"""
    enabled = list(ruleset.rules.filter(enabled=True).order_by("priority", "id"))
    enabled_ids = {rule.id: rule.name for rule in enabled}
    hit_ids = set()
    cases = list(ruleset.test_cases.all())
    case_items = []
    for case in cases:
        result = run_test_case(case, persist=False)
        rule_ids = {r.get("id") for r in
                    (result["evaluation"].get("rules") or []) if r.get("id")}
        hit_ids |= rule_ids
        case_items.append({"case_id": case.id, "name": case.name,
                           "passed": result["passed"],
                           "hit_rule_ids": sorted(rule_ids)})
    covered = [rid for rid in enabled_ids if rid in hit_ids]
    uncovered = [{"id": rid, "name": name} for rid, name in enabled_ids.items()
                 if rid not in hit_ids]
    return {
        "ruleset_id": ruleset.id,
        "enabled_rules": len(enabled_ids),
        "covered_rules": len(covered),
        "coverage": round(len(covered) / len(enabled_ids), 4) if enabled_ids else 0.0,
        "uncovered": uncovered[:200],
        "case_count": len(cases),
        "cases": case_items,
    }


# ---------------------------------------------------------------------------
# 批量仿真
# ---------------------------------------------------------------------------


def percentiles(values):
    """计算耗时分位：使用最近秩法，样本很少时也能稳定返回。"""
    values = sorted(float(v) for v in values if v is not None)
    count = len(values)
    if count == 0:
        return {"count": 0, "min": 0, "max": 0, "avg": 0,
                "p50": 0, "p90": 0, "p95": 0, "p99": 0}

    def pick(percent):
        if count == 1:
            return values[0]
        rank = int(math.ceil(percent / 100.0 * count)) - 1
        return values[max(0, min(count - 1, rank))]

    return {
        "count": count,
        "min": round(values[0], 3),
        "max": round(values[-1], 3),
        "avg": round(sum(values) / count, 3),
        "p50": round(pick(50), 3),
        "p90": round(pick(90), 3),
        "p95": round(pick(95), 3),
        "p99": round(pick(99), 3),
    }


def run_simulation(ruleset, facts_list, name="", owner=None, persist=True,
                   max_items=500):
    """批量仿真：逐条事实评估，汇总命中分布与耗时分位，供上线前压测。"""
    if isinstance(facts_list, str):
        facts_list = parse_json_arg(facts_list, "facts", list)
    if not isinstance(facts_list, list) or not facts_list:
        raise ValueError("仿真事实必须是非空数组")
    if len(facts_list) > max_items:
        raise ValueError(f"单次仿真最多 {max_items} 条事实")
    started_all = perf_counter()
    hit_counter = Counter()
    hit_names = {}
    matched = missed = error_count = 0
    durations, samples = [], []
    for index, facts in enumerate(facts_list):
        if not isinstance(facts, dict):
            error_count += 1
            if len(samples) < 20:
                samples.append({"index": index, "error": "事实必须是对象"})
            continue
        try:
            result = evaluate_ruleset(
                ruleset, facts, caller="simulation", source="simulation",
                owner=owner or ruleset.owner, persist=False, dry_run=True,
                with_trace=False,
            )
        except (ValueError, ExprError) as e:
            error_count += 1
            if len(samples) < 20:
                samples.append({"index": index, "error": str(e)})
            continue
        durations.append(result["duration_ms"])
        if result["status"] in ("degraded", "timeout", "error"):
            error_count += 1
        if result["matched"]:
            matched += 1
            for rule in (result["decision"] or {}).get("rules") or []:
                key = rule.get("name") or str(rule.get("id"))
                hit_counter[key] += 1
                hit_names[key] = rule.get("id")
        else:
            missed += 1
        if len(samples) < 20:
            samples.append({
                "index": index,
                "matched": result["matched"],
                "decision": (result["decision"] or {}).get("decision"),
                "rules": [r.get("name") for r in
                          (result["decision"] or {}).get("rules") or []],
                "duration_ms": result["duration_ms"],
            })
    total = len(facts_list)
    summary = {
        "total": total,
        "matched": matched,
        "missed": missed,
        "errors": error_count,
        "match_rate": round(matched / total, 4) if total else 0.0,
        "hit_distribution": [
            {"rule": name, "rule_id": hit_names.get(name), "count": count}
            for name, count in hit_counter.most_common(50)
        ],
        "latency": percentiles(durations),
        "samples": samples,
    }
    duration = perf_ms(started_all)
    simulation = None
    if persist:
        with transaction.atomic():
            simulation = RuleSimulation.objects.create(
                owner=owner or ruleset.owner, ruleset=ruleset,
                name=(name or "批量仿真")[:200],
                facts=to_json(facts_list[:max_items]),
                summary=to_json(summary), results=to_json(samples),
                duration_ms=duration,
                status="success" if error_count == 0 else "degraded",
            )
    return {
        "simulation_id": simulation.id if simulation else None,
        "ruleset_id": ruleset.id,
        "name": name,
        "summary": summary,
        "duration_ms": duration,
        "status": "success" if error_count == 0 else "degraded",
    }


# ---------------------------------------------------------------------------
# 调度（简化 cron）
# ---------------------------------------------------------------------------

CRON_RANGES = (("minute", 0, 59), ("hour", 0, 23), ("day", 1, 31),
               ("month", 1, 12), ("weekday", 0, 7))


def _cron_field(text, low, high, name):
    """解析单个 cron 字段：支持 *、*/n、a-b、a-b/n、a,b 与数字。"""
    values = set()
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"cron 的 {name} 字段含空项")
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            try:
                step = int(step_text)
            except ValueError:
                raise ValueError(f"cron 的 {name} 字段步长必须是整数")
            if step <= 0:
                raise ValueError(f"cron 的 {name} 字段步长必须大于 0")
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                raise ValueError(f"cron 的 {name} 字段区间非法: {part}")
        else:
            try:
                start = end = int(part)
            except ValueError:
                raise ValueError(f"cron 的 {name} 字段非法: {part}")
        if start < low or end > high or start > end:
            raise ValueError(f"cron 的 {name} 字段超出范围 {low}-{high}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"cron 的 {name} 字段没有取值")
    return values


def cron_parse(expression):
    """解析 5 段 cron（分 时 日 月 周），周字段 0=周一，兼容 7=周日。"""
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise ValueError("cron 表达式必须是 5 段：分 时 日 月 周")
    fields = {}
    for (name, low, high), part in zip(CRON_RANGES, parts):
        fields[name] = _cron_field(part, low, high, name)
    if 7 in fields["weekday"]:
        fields["weekday"].discard(7)
        fields["weekday"].add(0)
    return fields


def cron_next(expression, base=None):
    """计算下一次执行时间：按日筛选再按时分收敛，避免逐分钟空转。"""
    fields = cron_parse(expression)
    local = timezone.localtime(base or timezone.now())
    start = (local + timedelta(minutes=1)).replace(second=0, microsecond=0)
    dom_full = fields["day"] == set(range(1, 32))
    dow_full = fields["weekday"] == set(range(0, 7))
    for offset in range(0, 367):
        day = start.date() + timedelta(days=offset)
        if day.month not in fields["month"]:
            continue
        dom_ok = day.day in fields["day"]
        dow_ok = day.weekday() in fields["weekday"]
        if dom_full and dow_full:
            day_ok = True
        elif dom_full:
            day_ok = dow_ok
        elif dow_full:
            day_ok = dom_ok
        else:
            # 标准 cron：日与周同时受限时取并集
            day_ok = dom_ok or dow_ok
        if not day_ok:
            continue
        for hour in sorted(fields["hour"]):
            if offset == 0 and hour < start.hour:
                continue
            for minute in sorted(fields["minute"]):
                if offset == 0 and hour == start.hour and minute < start.minute:
                    continue
                candidate = timezone.make_aware(
                    datetime.combine(day, time(hour, minute)))
                if candidate > local:
                    return candidate
    raise ValueError("未来一年内没有可执行时间，请检查 cron 表达式")


def scan_schedules(user, now=None):
    """扫描本人到期的调度并执行：执行写库，因此只处理 owner 本人的调度。"""
    now = now or timezone.now()
    due = list(RuleSchedule.objects.filter(owner=user, enabled=True)
               .select_related("ruleset").order_by("next_run_at")[:200])
    results = []
    for candidate in due:
        if candidate.next_run_at is not None and candidate.next_run_at > now:
            continue
        with transaction.atomic():
            schedule = RuleSchedule.objects.select_for_update().get(pk=candidate.pk)
            if not schedule.enabled:
                continue
            if schedule.ruleset.status != "active":
                schedule.last_run_at = now
                schedule.next_run_at = cron_next(schedule.cron, now)
                schedule.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
                results.append({"schedule_id": schedule.id, "skipped": True,
                                "reason": "规则集非 active 状态", "executed": False})
                continue
            result = evaluate_ruleset(
                schedule.ruleset, schedule.facts or {},
                caller=f"schedule:{schedule.id}", source="schedule",
                owner=schedule.owner, persist=True,
            )
            schedule.last_run_at = now
            schedule.run_count = schedule.run_count + 1
            schedule.next_run_at = cron_next(schedule.cron, now)
            schedule.save(update_fields=["last_run_at", "run_count",
                                         "next_run_at", "updated_at"])
        results.append({
            "schedule_id": schedule.id,
            "ruleset_id": schedule.ruleset_id,
            "evaluation_id": result["evaluation_id"],
            "matched": result["matched"],
            "status": result["status"],
            "next_run_at": schedule.next_run_at.isoformat(),
            "executed": True,
        })
    return {"scanned": len(due), "executed": sum(1 for r in results if r["executed"]),
            "items": results, "checked_at": now.isoformat()}


def run_schedule_now(schedule, user):
    """立即执行一次调度（手动触发，不改 next_run_at 的节奏）。"""
    result = evaluate_ruleset(
        schedule.ruleset, schedule.facts or {},
        caller=f"schedule:{schedule.id}", source="schedule-manual",
        owner=user, persist=True,
    )
    schedule.last_run_at = timezone.now()
    schedule.run_count = schedule.run_count + 1
    schedule.save(update_fields=["last_run_at", "run_count", "updated_at"])
    return result


# ---------------------------------------------------------------------------
# 版本对比
# ---------------------------------------------------------------------------


def compare_versions(left, right):
    """对比两个版本快照：规则/变量/决策表的增删改，按名称做键。"""
    snap_a = left.snapshot or {}
    snap_b = right.snapshot or {}

    def index(items, key="name"):
        return {str(item.get(key) or ""): item for item in (items or [])
                if item.get(key)}

    rules_a, rules_b = index(snap_a.get("rules")), index(snap_b.get("rules"))
    added = sorted(set(rules_b) - set(rules_a))
    removed = sorted(set(rules_a) - set(rules_b))
    changed = []
    for name in sorted(set(rules_a) & set(rules_b)):
        a, b = rules_a[name], rules_b[name]
        fields = []
        for field in ("condition", "priority", "enabled", "actions", "tags",
                      "conditions", "action_items"):
            if to_json(a.get(field)) != to_json(b.get(field)):
                fields.append(field)
        if fields:
            changed.append({"name": name, "fields": fields,
                            "before": to_json({f: a.get(f) for f in fields}),
                            "after": to_json({f: b.get(f) for f in fields})})
    vars_a, vars_b = index(snap_a.get("variables")), index(snap_b.get("variables"))
    tables_a = index(snap_a.get("decision_tables"))
    tables_b = index(snap_b.get("decision_tables"))
    return {
        "left": {"id": left.id, "version_no": left.version_no,
                 "created_at": now_iso(left.created_at) if left.created_at else None},
        "right": {"id": right.id, "version_no": right.version_no,
                  "created_at": now_iso(right.created_at) if right.created_at else None},
        "rules": {
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": len(set(rules_a) & set(rules_b)) - len(changed),
        },
        "variables": {
            "added": sorted(set(vars_b) - set(vars_a)),
            "removed": sorted(set(vars_a) - set(vars_b)),
            "changed": sorted(name for name in set(vars_a) & set(vars_b)
                              if to_json(vars_a[name]) != to_json(vars_b[name])),
        },
        "decision_tables": {
            "added": sorted(set(tables_b) - set(tables_a)),
            "removed": sorted(set(tables_a) - set(tables_b)),
            "changed": sorted(name for name in set(tables_a) & set(tables_b)
                              if to_json(tables_a[name]) != to_json(tables_b[name])),
        },
        "identical": not added and not removed and not changed
        and set(vars_a) == set(vars_b) and set(tables_a) == set(tables_b),
    }


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


def _since(days):
    days = clamp_int(days, 7, 1, 365)
    return timezone.now() - timedelta(days=days), days


def _eval_scope(user, ruleset_id=None):
    qs = scope_queryset(RuleEvaluation.objects.all(), user)
    if ruleset_id not in (None, ""):
        qs = qs.filter(ruleset_id=as_int(ruleset_id, "ruleset_id"))
    return qs


def stats_overview(user, days=7, ruleset_id=None):
    """概览：评估量、命中率、失败率、平均耗时、规则/冲突/用例健康度。"""
    since, days = _since(days)
    qs = _eval_scope(user, ruleset_id).filter(created_at__gte=since)
    rows = list(qs.values("status", "decision", "duration_ms")[:5000])
    total = qs.count()
    matched = sum(1 for row in rows if (row["decision"] or {}).get("matched"))
    error_status = ("error", "degraded", "timeout")
    errors = sum(1 for row in rows if row["status"] in error_status)
    durations = [row["duration_ms"] for row in rows if row["duration_ms"] is not None]
    rulesets = scope_queryset(RuleSet.objects.all(), user)
    if ruleset_id not in (None, ""):
        rulesets = rulesets.filter(pk=as_int(ruleset_id, "ruleset_id"))
    rules = scope_queryset(Rule.objects.filter(ruleset__in=rulesets), user)
    tests = scope_queryset(RuleTestCase.objects.filter(ruleset__in=rulesets), user)
    test_total = tests.count()
    test_passed = tests.filter(passed=True).count()
    return {
        "days": days,
        "evaluations": total,
        "matched": matched,
        "unmatched": max(0, total - matched),
        "hit_rate": round(matched / total, 4) if total else 0.0,
        "errors": errors,
        "failure_rate": round(errors / total, 4) if total else 0.0,
        "duration": percentiles(durations),
        "rulesets": rulesets.count(),
        "active_rulesets": rulesets.filter(status="active").count(),
        "rules": rules.count(),
        "enabled_rules": rules.filter(enabled=True).count(),
        "open_conflicts": scope_queryset(
            RuleConflict.objects.filter(ruleset__in=rulesets, status="open"), user).count(),
        "test_cases": test_total,
        "test_passed": test_passed,
        "test_pass_rate": round(test_passed / test_total, 4) if test_total else 0.0,
        "pending_approvals": scope_queryset(
            RuleApproval.objects.filter(ruleset__in=rulesets, status="pending"), user).count(),
        "open_tasks": scope_queryset(
            RuleTask.objects.filter(ruleset__in=rulesets, status="open"), user).count(),
    }


def stats_top_rules(user, days=7, limit=10, ruleset_id=None):
    """命中 TOP：统计窗口内评估记录里的规则命中次数，并附全生命周期计数。"""
    since, days = _since(days)
    limit = clamp_int(limit, 10, 1, 100)
    qs = _eval_scope(user, ruleset_id).filter(created_at__gte=since).order_by("-created_at")
    rows = list(qs.values("decision")[:2000])
    counter = Counter()
    for row in rows:
        for rule in (row["decision"] or {}).get("rules") or []:
            name = rule.get("name") or f"#{rule.get('id')}"
            counter[name] += 1
    names = [name for name, _ in counter.most_common(limit)]
    lifetime = {rule.name: rule.hit_count for rule in
                scope_queryset(Rule.objects.filter(name__in=names), user)}
    return {
        "days": days,
        "sampled_evaluations": len(rows),
        "items": [{"name": name, "hits": count,
                   "lifetime_hits": lifetime.get(name, 0)}
                  for name, count in counter.most_common(limit)],
    }


def stats_failures(user, days=7, ruleset_id=None):
    """失败原因分布：动作失败按类型聚合，评估失败按状态聚合，错误原文 TOP 20。"""
    since, days = _since(days)
    logs = scope_queryset(RuleExecutionLog.objects.all(), user).filter(
        status="failed", created_at__gte=since)
    if ruleset_id not in (None, ""):
        logs = logs.filter(rule__ruleset_id=as_int(ruleset_id, "ruleset_id"))
    by_action = list(logs.values("action_type").annotate(count=Count("id"))
                     .order_by("-count")[:20])
    error_counter = Counter()
    for error in logs.values_list("error", flat=True)[:2000]:
        text = (error or "未知错误").strip()[:200]
        error_counter[text] += 1
    eval_status = list(_eval_scope(user, ruleset_id)
                       .filter(created_at__gte=since,
                               status__in=["error", "degraded", "timeout"])
                       .values("status").annotate(count=Count("id")))
    return {
        "days": days,
        "action_failures": by_action,
        "action_failure_total": sum(item["count"] for item in by_action),
        "top_errors": [{"error": text, "count": count}
                       for text, count in error_counter.most_common(20)],
        "evaluation_status": eval_status,
    }


def stats_latency(user, days=7, ruleset_id=None):
    """耗时分位：整体 p50/p90/p95/p99，并给出最慢规则集 TOP。"""
    since, days = _since(days)
    rows = list(_eval_scope(user, ruleset_id).filter(created_at__gte=since)
                .values("duration_ms", "ruleset_code")[:5000])
    overall = percentiles([row["duration_ms"] for row in rows])
    by_code = {}
    for row in rows:
        code = row["ruleset_code"] or "-"
        by_code.setdefault(code, []).append(row["duration_ms"])
    slowest = sorted(
        ({"ruleset_code": code, **percentiles(values)} for code, values in by_code.items()),
        key=lambda item: item["p99"], reverse=True,
    )[:10]
    return {"days": days, "overall": overall, "slowest_rulesets": slowest,
            "sampled": len(rows)}


def stats_trend(user, days=7, ruleset_id=None):
    """按日趋势：补齐空白日期，前端折线不需要自己补 0。"""
    since, days = _since(days)
    rows = list(_eval_scope(user, ruleset_id).filter(created_at__gte=since)
                .values("created_at", "status", "decision")[:10000])
    buckets = {}
    for row in rows:
        created = row["created_at"]
        if created is None:
            continue
        day = timezone.localtime(created).date()
        bucket = buckets.setdefault(day, {"date": day.isoformat(), "total": 0,
                                          "matched": 0, "errors": 0})
        bucket["total"] += 1
        if (row["decision"] or {}).get("matched"):
            bucket["matched"] += 1
        if row["status"] in ("error", "degraded", "timeout"):
            bucket["errors"] += 1
    today = timezone.localdate()
    items = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        items.append(buckets.get(day, {"date": day.isoformat(), "total": 0,
                                       "matched": 0, "errors": 0}))
    return {"days": days, "items": items}


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------

CHANGE_FIELDS = {"name", "category", "description", "hit_policy",
                 "max_executions", "timeout_ms", "priority", "tags",
                 "settings", "status"}


def apply_change_fields(ruleset, fields):
    """把审批变更落到规则集：逐字段白名单校验，编码等敏感字段一律不许改。"""
    if not isinstance(fields, dict) or not fields:
        raise ValueError("变更内容缺少 fields")
    unknown = sorted(set(fields) - CHANGE_FIELDS)
    if unknown:
        raise ValueError(f"不允许通过审批修改字段: {', '.join(unknown)}")
    for key, value in fields.items():
        if key == "name":
            name = str(value or "").strip()
            if not name:
                raise ValueError("规则集名称不能为空")
            ruleset.name = name[:200]
        elif key == "category":
            ruleset.category = str(value or "自定义")[:60]
        elif key == "description":
            ruleset.description = str(value or "")
        elif key == "hit_policy":
            if value not in HIT_POLICIES:
                raise ValueError(f"不支持的命中策略: {value}")
            ruleset.hit_policy = value
        elif key == "max_executions":
            ruleset.max_executions = clamp_int(value, 100, 1, 1000)
        elif key == "timeout_ms":
            ruleset.timeout_ms = clamp_int(value, 2000, 50, 60000)
        elif key == "priority":
            ruleset.priority = clamp_int(value, 0, -100000, 100000)
        elif key == "tags":
            if not isinstance(value, list):
                raise ValueError("tags 必须是数组")
            ruleset.tags = to_json(value[:50])
        elif key == "settings":
            if not isinstance(value, dict):
                raise ValueError("settings 必须是对象")
            ruleset.settings = to_json(value)
        elif key == "status":
            if value not in RULESET_STATUS:
                raise ValueError(f"不支持的状态: {value}")
            ruleset.status = value
    ruleset.save()
    return ruleset


def submit_approval(ruleset, user, change, note=""):
    """提交变更审批：冻结变更内容，待审批通过后再落库。"""
    change = parse_json_arg(change, "change", dict)
    if not change:
        raise ValueError("变更内容不能为空")
    fields = change.get("fields")
    if fields is not None and not isinstance(fields, dict):
        raise ValueError("change.fields 必须是对象")
    if fields:
        apply_change_fields_preview(fields)
    return RuleApproval.objects.create(
        owner=user, ruleset=ruleset, change=to_json(change),
        status="pending", note=(note or "")[:500],
    )


def apply_change_fields_preview(fields):
    """审批提交时先做一次字段校验：把错误挡在提交前，而不是审批时才发现。"""
    if not isinstance(fields, dict):
        raise ValueError("change.fields 必须是对象")
    unknown = sorted(set(fields) - CHANGE_FIELDS)
    if unknown:
        raise ValueError(f"不允许通过审批修改字段: {', '.join(unknown)}")
    for key, value in fields.items():
        if key == "name" and not str(value or "").strip():
            raise ValueError("规则集名称不能为空")
        if key == "hit_policy" and value not in HIT_POLICIES:
            raise ValueError(f"不支持的命中策略: {value}")
        if key == "status" and value not in RULESET_STATUS:
            raise ValueError(f"不支持的状态: {value}")
        if key in ("tags",) and not isinstance(value, list):
            raise ValueError("tags 必须是数组")
        if key in ("settings",) and not isinstance(value, dict):
            raise ValueError("settings 必须是对象")
    return True


def review_approval(approval, reviewer, approve, note=""):
    """审批：通过时应用变更（可选自动发布），驳回只记状态；禁止自批。"""
    if approval.status != "pending":
        raise ValueError(f"当前审批状态 {approval.status} 不可处理")
    if approval.owner_id == reviewer.id and not reviewer.is_superuser:
        raise ValueError("不能审批自己提交的变更")
    with transaction.atomic():
        locked = RuleApproval.objects.select_for_update().get(pk=approval.pk)
        if locked.status != "pending":
            raise ValueError("审批已被处理，请刷新后重试")
        if approve:
            if not locked.ruleset_id:
                raise ValueError("规则集已删除，无法应用变更")
            ruleset = locked.ruleset
            fields = (locked.change or {}).get("fields") or {}
            if fields:
                apply_change_fields(ruleset, fields)
            publish = (locked.change or {}).get("publish", True)
            if publish:
                publish_ruleset(ruleset, reviewer,
                                note=f"审批 #{locked.id} 通过后发布")
            locked.status = "approved"
        else:
            locked.status = "rejected"
        locked.reviewer = reviewer
        locked.review_note = (note or "")[:500]
        locked.reviewed_at = timezone.now()
        locked.save()
    return locked


# ---------------------------------------------------------------------------
# 内置模板
# ---------------------------------------------------------------------------

BUILTIN_TEMPLATES = [
    {
        "key": "risk-amount",
        "name": "金额风险分级",
        "category": "风控",
        "description": "按交易金额分级打标并发通知，适合支付/报销风控场景。",
        "template": {
            "ruleset": {
                "code": "tpl_risk_amount", "name": "金额风险分级",
                "category": "风控", "status": "draft", "hit_policy": "priority",
                "max_executions": 100, "timeout_ms": 2000, "priority": 0,
                "tags": ["模板", "风控"], "settings": {},
                "description": "大额交易自动打标并提醒；中额交易进入复核队列。",
            },
            "variables": [
                {"name": "risk_threshold", "type": "number", "default_value": 10000,
                 "description": "大额风险阈值（默认 10000）"},
            ],
            "rules": [
                {
                    "name": "大额交易拦截",
                    "description": "金额达到阈值时标记高风险并通知",
                    "priority": 10, "enabled": True, "condition": "",
                    "tags": ["高风险"],
                    "conditions": [{
                        "field": "facts.amount", "operator": ">=",
                        "value": 10000, "logic_group": "and",
                        "sort_order": 0, "enabled": True,
                    }],
                    "action_items": [
                        {"type": "flag", "params": {"name": "high_risk", "value": True},
                         "sort_order": 0, "enabled": True},
                        {"type": "notify",
                         "params": {"title": "大额交易提醒",
                                    "message": "金额 {{facts.amount}} 触发大额风控"},
                         "sort_order": 1, "enabled": True},
                        {"type": "score", "params": {"field": "risk_score", "delta": 60},
                         "sort_order": 2, "enabled": True},
                    ],
                    "actions": [],
                },
                {
                    "name": "中额交易复核",
                    "description": "金额在 1000~10000 之间进入复核",
                    "priority": 20, "enabled": True,
                    "condition": "(facts.amount >= 1000 and facts.amount < 10000)",
                    "tags": ["复核"],
                    "conditions": [],
                    "action_items": [
                        {"type": "route", "params": {"target": "risk_review"},
                         "sort_order": 0, "enabled": True},
                        {"type": "score", "params": {"field": "risk_score", "delta": 20},
                         "sort_order": 1, "enabled": True},
                    ],
                    "actions": [],
                },
            ],
            "decision_tables": [],
        },
    },
    {
        "key": "vip-route",
        "name": "VIP 客户路由",
        "category": "客服",
        "description": "VIP 客户的高价值工单优先路由到专属队列并提醒负责人。",
        "template": {
            "ruleset": {
                "code": "tpl_vip_route", "name": "VIP 客户路由",
                "category": "客服", "status": "draft", "hit_policy": "first",
                "max_executions": 100, "timeout_ms": 2000, "priority": 0,
                "tags": ["模板", "客服"], "settings": {},
                "description": "识别 VIP 客户并优先分派。",
            },
            "variables": [],
            "rules": [
                {
                    "name": "VIP 优先路由",
                    "description": "VIP 且金额超过 1000 的工单进入专属队列",
                    "priority": 10, "enabled": True,
                    "condition": ("(facts.customer.level == 'vip' "
                                  "and facts.amount > 1000)"),
                    "tags": ["VIP"],
                    "conditions": [],
                    "action_items": [
                        {"type": "route", "params": {"target": "vip_queue"},
                         "sort_order": 0, "enabled": True},
                        {"type": "set_field",
                         "params": {"field": "priority", "value": "high"},
                         "sort_order": 1, "enabled": True},
                        {"type": "notify",
                         "params": {"title": "VIP 工单待处理",
                                    "message": "客户 {{facts.customer.name}} 提交了高价值工单"},
                         "sort_order": 2, "enabled": True},
                    ],
                    "actions": [],
                },
                {
                    "name": "普通客户入池",
                    "description": "非 VIP 工单进入普通队列",
                    "priority": 100, "enabled": True,
                    "condition": "(facts.customer.level != 'vip')",
                    "tags": ["普通"],
                    "conditions": [],
                    "action_items": [
                        {"type": "route", "params": {"target": "normal_queue"},
                         "sort_order": 0, "enabled": True},
                    ],
                    "actions": [],
                },
            ],
            "decision_tables": [],
        },
    },
    {
        "key": "overdue-task",
        "name": "逾期任务提醒",
        "category": "协同",
        "description": "任务逾期后自动创建跟进任务并累加风险分。",
        "template": {
            "ruleset": {
                "code": "tpl_overdue_task", "name": "逾期任务提醒",
                "category": "协同", "status": "draft", "hit_policy": "first",
                "max_executions": 100, "timeout_ms": 2000, "priority": 0,
                "tags": ["模板", "协同"], "settings": {},
                "description": "逾期的协同任务生成跟进任务。",
            },
            "variables": [],
            "rules": [
                {
                    "name": "逾期生成跟进",
                    "description": "逾期天数大于 0 即生成跟进任务",
                    "priority": 10, "enabled": True,
                    "condition": "(facts.days_overdue > 0)",
                    "tags": ["逾期"],
                    "conditions": [],
                    "action_items": [
                        {"type": "create_task",
                         "params": {"title": "跟进逾期任务：{{facts.title}}",
                                    "due_days": 1, "assignee": "admin"},
                         "sort_order": 0, "enabled": True},
                        {"type": "score", "params": {"field": "risk_score", "delta": 10},
                         "sort_order": 1, "enabled": True},
                    ],
                    "actions": [],
                },
            ],
            "decision_tables": [],
        },
    },
    {
        "key": "leave-auto",
        "name": "请假自动审批",
        "category": "人事",
        "description": "三天以内自动通过，超过三天转人工驳回并提示补充材料。",
        "template": {
            "ruleset": {
                "code": "tpl_leave_auto", "name": "请假自动审批",
                "category": "人事", "status": "draft", "hit_policy": "first",
                "max_executions": 100, "timeout_ms": 2000, "priority": 0,
                "tags": ["模板", "人事"], "settings": {},
                "description": "小长假自动审批，长假转人工。",
            },
            "variables": [
                {"name": "auto_days", "type": "number", "default_value": 3,
                 "description": "自动通过的最大天数"},
            ],
            "rules": [
                {
                    "name": "短假自动通过",
                    "description": "请假天数不超过阈值直接通过",
                    "priority": 10, "enabled": True,
                    "condition": "(facts.leave_days <= 3)",
                    "tags": ["自动通过"],
                    "conditions": [],
                    "action_items": [
                        {"type": "approve",
                         "params": {"reason": "短假自动审批通过"},
                         "sort_order": 0, "enabled": True},
                    ],
                    "actions": [],
                },
                {
                    "name": "长假人工复核",
                    "description": "超过阈值的请假输出驳回决策，等待人工",
                    "priority": 20, "enabled": True,
                    "condition": "(facts.leave_days > 3)",
                    "tags": ["人工"],
                    "conditions": [],
                    "action_items": [
                        {"type": "reject", "params": {"reason": "请假天数较长，需人工复核"},
                         "sort_order": 0, "enabled": True},
                        {"type": "create_task",
                         "params": {"title": "复核请假申请：{{facts.applicant}}"},
                         "sort_order": 1, "enabled": True},
                    ],
                    "actions": [],
                },
            ],
            "decision_tables": [],
        },
    },
]


def builtin_template_list():
    """内置模板：常量提供，不落用户数据，避免每个租户各存一份副本。"""
    return [{
        "id": None, "key": item["key"], "name": item["name"],
        "category": item["category"], "description": item["description"],
        "builtin": True, "usage_count": 0,
    } for item in BUILTIN_TEMPLATES]


def list_templates(user):
    """模板目录：内置模板 + 本人保存的模板。"""
    rows = [template_dict(t) for t in
            RuleTemplate.objects.filter(owner=user).order_by("-created_at")]
    return builtin_template_list() + rows


def apply_template(user, template_id=None, key="", name=""):
    """从模板创建规则集：编码自动避让，内容深拷贝，生成后为草稿态。"""
    source = None
    base_name = ""
    if key:
        for item in BUILTIN_TEMPLATES:
            if item["key"] == key:
                source = copy.deepcopy(item["template"])
                base_name = item["name"]
                break
        if source is None:
            raise ValueError(f"内置模板不存在: {key}")
    elif template_id not in (None, ""):
        row = RuleTemplate.objects.filter(pk=template_id, owner=user).first()
        if row is None:
            raise ValueError("模板不存在")
        source = copy.deepcopy(row.template or {})
        base_name = row.name
        row.usage_count = row.usage_count + 1
        row.save(update_fields=["usage_count", "updated_at"])
    else:
        raise ValueError("缺少必填参数: key 或 template_id")
    if not isinstance(source, dict) or not source.get("ruleset"):
        raise ValueError("模板内容损坏，缺少 ruleset 段")
    meta = source["ruleset"]
    code = unique_code(user, meta.get("code") or "tpl", suffix="_tpl")
    meta["code"] = code
    meta["name"] = (name or base_name or meta.get("name") or "模板规则集")[:200]
    meta["status"] = "draft"
    meta["version_no"] = 1
    with transaction.atomic():
        ruleset = RuleSet.objects.create(
            owner=user, code=code, name=meta["name"],
            category=str(meta.get("category") or "通用")[:60],
            description=str(meta.get("description") or ""),
            status="draft", version_no=1,
            hit_policy=meta.get("hit_policy") if meta.get("hit_policy") in HIT_POLICIES else "first",
            max_executions=clamp_int(meta.get("max_executions"), 100, 1, 1000),
            timeout_ms=clamp_int(meta.get("timeout_ms"), 2000, 50, 60000),
            priority=clamp_int(meta.get("priority"), 0, -100000, 100000),
            tags=to_json(meta.get("tags") or []),
            settings=to_json(meta.get("settings") or {}),
        )
        _apply_snapshot(ruleset, source, user)
    return ruleset




