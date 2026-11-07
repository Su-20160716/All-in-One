# -*- coding: utf-8 -*-
"""数据质量检查：对落地行执行规则，产出通过状态、失败行数与样例。

规则求值刻意做成「逐行判定 + 汇总」：
- 失败行数决定是否阻断（severity=error 的规则由调用方决定是否标红运行）；
- 样例最多 5 条，足够排障又不会把结果表撑爆；
- 所有判定都基于内存行集，单次上限 5000 行，同步执行可控。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

from pipeline.catalog import MAX_RUN_ROWS
from pipeline.expressions import ExprError, parse_datetime_value, to_number, to_text
from pipeline.models import (QUALITY_RULE_TYPES, QUALITY_SEVERITY,
                             DataQualityRule, PipelineOutput, QualityResult)

SAMPLE_LIMIT = 5
MAX_REGEX_LEN = 300


def _get(rule, key: str, default=None):
    """同时支持模型实例与字典（测试规则时用的是未落库的草案）。"""
    if isinstance(rule, dict):
        return rule.get(key, default)
    return getattr(rule, key, default)


def _params(rule) -> dict:
    params = _get(rule, "params") or {}
    if not isinstance(params, dict):
        raise ValueError("规则参数必须是对象")
    return params


def _field(rule) -> str:
    field = str(_get(rule, "field") or "").strip()
    if not field:
        raise ValueError("该规则必须指定校验字段")
    return field


def _value(row: dict, field: str):
    """取字段值，兼容点路径。"""
    if field in row:
        return row[field]
    current = row
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _null(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _failure(index: int, value, reason: str, extra: dict | None = None) -> dict:
    item = {"row": index + 1, "value": value, "reason": reason}
    if extra:
        item.update(extra)
    return item


def _check_not_null(rows, rule):
    field = _field(rule)
    failures = [_failure(i, _value(row, field), "字段为空")
                for i, row in enumerate(rows) if _null(_value(row, field))]
    return len(failures), failures[:SAMPLE_LIMIT], f"字段 {field} 存在空值"


def _check_unique(rows, rule):
    field = _field(rule)
    params = _params(rule)
    ignore_null = params.get("ignore_null", True)
    counts: dict[str, int] = {}
    for row in rows:
        value = _value(row, field)
        if _null(value):
            if ignore_null:
                continue
            key = "\x00"
        else:
            key = to_text(value).strip().lower()
        counts[key] = counts.get(key, 0) + 1
    failures = []
    total = 0
    for i, row in enumerate(rows):
        value = _value(row, field)
        if _null(value):
            if ignore_null:
                continue
            key = "\x00"
        else:
            key = to_text(value).strip().lower()
        if counts.get(key, 0) > 1:
            total += 1
            if len(failures) < SAMPLE_LIMIT:
                failures.append(_failure(i, value, f"重复值出现 {counts[key]} 次",
                                         {"duplicates": counts[key]}))
    return total, failures, f"字段 {field} 存在重复值"


def _check_range(rows, rule):
    field = _field(rule)
    params = _params(rule)
    low = params.get("min")
    high = params.get("max")
    if low is None and high is None:
        raise ValueError("区间规则必须配置 min 或 max")
    low_num = to_number(low) if low is not None else None
    high_num = to_number(high) if high is not None else None
    if low is not None and low_num is None:
        raise ValueError("区间规则的 min 必须是数字")
    if high is not None and high_num is None:
        raise ValueError("区间规则的 max 必须是数字")
    if low_num is not None and high_num is not None and low_num > high_num:
        raise ValueError("区间规则的 min 不能大于 max")
    failures = []
    for i, row in enumerate(rows):
        value = _value(row, field)
        if _null(value):
            failures.append(_failure(i, value, "字段为空，无法判断区间"))
            continue
        num = to_number(value)
        if num is None:
            failures.append(_failure(i, value, "不是数值"))
            continue
        if low_num is not None and num < low_num:
            failures.append(_failure(i, value, f"小于下限 {low_num}"))
        elif high_num is not None and num > high_num:
            failures.append(_failure(i, value, f"大于上限 {high_num}"))
    return len(failures), failures[:SAMPLE_LIMIT], f"字段 {field} 越界"


def _check_regex(rows, rule):
    field = _field(rule)
    params = _params(rule)
    pattern = str(params.get("pattern") or "")
    if not pattern:
        raise ValueError("正则规则必须配置 pattern")
    if len(pattern) > MAX_REGEX_LEN:
        raise ValueError(f"正则长度不能超过 {MAX_REGEX_LEN}")
    flags = re.IGNORECASE if params.get("ignore_case") else 0
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"正则表达式不合法：{exc}")
    mode = str(params.get("mode") or "search")
    failures = []
    for i, row in enumerate(rows):
        value = _value(row, field)
        text = to_text(value)
        matched = compiled.fullmatch(text) if mode == "full" else compiled.search(text)
        if not matched:
            failures.append(_failure(i, value, "未匹配正则"))
    return len(failures), failures[:SAMPLE_LIMIT], f"字段 {field} 格式不匹配"


def _check_enum(rows, rule):
    field = _field(rule)
    params = _params(rule)
    values = params.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("枚举规则必须配置 values 数组")
    case_sensitive = params.get("case_sensitive", True)
    allowed = {to_text(v) if case_sensitive else to_text(v).lower() for v in values}
    failures = []
    for i, row in enumerate(rows):
        value = _value(row, field)
        probe = to_text(value) if case_sensitive else to_text(value).lower()
        if probe not in allowed:
            failures.append(_failure(i, value, "不在枚举范围内"))
    return len(failures), failures[:SAMPLE_LIMIT], f"字段 {field} 存在非法枚举值"


def _age_seconds(value) -> float | None:
    dt = parse_datetime_value(value)
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return (timezone.now() - dt).total_seconds()


def _check_freshness(rows, rule):
    field = _field(rule)
    params = _params(rule)
    max_age = params.get("max_age_seconds", 86400)
    max_age_num = to_number(max_age)
    if max_age_num is None or max_age_num <= 0:
        raise ValueError("时效规则的 max_age_seconds 必须是正数")
    failures = []
    for i, row in enumerate(rows):
        value = _value(row, field)
        if _null(value):
            failures.append(_failure(i, value, "时间字段为空"))
            continue
        age = _age_seconds(value)
        if age is None:
            failures.append(_failure(i, value, "无法解析为日期时间"))
        elif age > max_age_num:
            failures.append(_failure(i, value, f"数据已过期 {int(age)} 秒"))
    return len(failures), failures[:SAMPLE_LIMIT], f"字段 {field} 数据不新鲜"


def _check_row_count(rows, rule):
    params = _params(rule)
    count = len(rows)
    low = params.get("min_rows")
    high = params.get("max_rows")
    low_num = to_number(low) if low is not None else None
    high_num = to_number(high) if high is not None else None
    if low is not None and low_num is None:
        raise ValueError("行数规则的 min_rows 必须是数字")
    if high is not None and high_num is None:
        raise ValueError("行数规则的 max_rows 必须是数字")
    failures = []
    if low_num is not None and count < low_num:
        failures.append(_failure(0, count, f"行数 {count} 少于下限 {int(low_num)}"))
    if high_num is not None and count > high_num:
        failures.append(_failure(0, count, f"行数 {count} 超过上限 {int(high_num)}"))
    return len(failures), failures[:SAMPLE_LIMIT], f"行数 {count} 不在预期区间"


CHECKERS = {
    "not_null": _check_not_null,
    "unique": _check_unique,
    "range": _check_range,
    "regex": _check_regex,
    "enum": _check_enum,
    "freshness": _check_freshness,
    "row_count": _check_row_count,
}


def validate_rule(rule) -> None:
    """规则静态校验：类型、严重度、字段与参数形态。"""
    rule_type = str(_get(rule, "rule_type") or "")
    if rule_type not in QUALITY_RULE_TYPES:
        raise ValueError(f"不支持的质量规则类型：{rule_type}")
    severity = str(_get(rule, "severity") or "warning")
    if severity not in QUALITY_SEVERITY:
        raise ValueError(f"不支持的严重度：{severity}")
    if rule_type != "row_count":
        _field(rule)
    params = _params(rule)
    if rule_type == "range" and params.get("min") is None and params.get("max") is None:
        raise ValueError("区间规则必须配置 min 或 max")
    if rule_type == "regex":
        pattern = str(params.get("pattern") or "")
        if not pattern:
            raise ValueError("正则规则必须配置 pattern")
        if len(pattern) > MAX_REGEX_LEN:
            raise ValueError(f"正则长度不能超过 {MAX_REGEX_LEN}")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"正则表达式不合法：{exc}")
    if rule_type == "enum":
        if not isinstance(params.get("values"), list) or not params["values"]:
            raise ValueError("枚举规则必须配置 values 数组")
    if rule_type == "freshness":
        max_age = to_number(params.get("max_age_seconds", 86400))
        if max_age is None or max_age <= 0:
            raise ValueError("时效规则的 max_age_seconds 必须是正数")


def evaluate_rule(rule, rows: list[dict]) -> dict:
    """执行单条规则，返回可直接入库 / 回显的结果字典。"""
    validate_rule(rule)
    rule_type = str(_get(rule, "rule_type"))
    checker = CHECKERS[rule_type]
    rows = list(rows or [])
    if len(rows) > MAX_RUN_ROWS:
        rows = rows[:MAX_RUN_ROWS]
    started = timezone.now()
    try:
        failed, sample, message = checker(rows, rule)
    except ExprError as exc:
        raise ValueError(str(exc))
    duration = int((timezone.now() - started).total_seconds() * 1000)
    checked = len(rows) if rule_type != "row_count" else len(rows)
    passed = failed == 0
    return {
        "rule_id": _get(rule, "id"),
        "name": _get(rule, "name", ""),
        "rule_type": rule_type,
        "severity": _get(rule, "severity", "warning"),
        "field": _get(rule, "field", ""),
        "passed": passed,
        "checked_rows": checked,
        "failed_rows": failed,
        "pass_rate": 100.0 if not checked else round((checked - failed) * 100.0 / checked, 2),
        "message": message if failed else "校验通过",
        "sample": sample,
        "duration_ms": duration,
    }


def output_rows_for_run(run, limit: int = MAX_RUN_ROWS) -> list[dict]:
    """取一次运行的落地行（按 seq 稳定排序，供质量 / 画像复用）。"""
    qs = PipelineOutput.objects.filter(run=run).order_by("seq", "id").values_list("data", flat=True)
    return [dict(row) for row in qs[:limit]]


def latest_output_rows(pipeline, limit: int = MAX_RUN_ROWS) -> list[dict]:
    """取管道最近一次成功运行的落地行；没有则返回空列表。"""
    run = pipeline.runs.filter(status="success").order_by("-started_at", "-id").first()
    if run is None:
        return []
    return output_rows_for_run(run, limit)


@transaction.atomic
def run_quality_checks(pipeline, run, rows: list[dict]) -> dict:
    """对一次运行执行全部启用的规则，并落库 QualityResult。"""
    rules = list(pipeline.quality_rules.filter(enabled=True).order_by("id"))
    results = []
    for rule in rules:
        outcome = evaluate_rule(rule, rows)
        QualityResult.objects.create(
            owner=pipeline.owner,
            rule=rule,
            run=run,
            passed=outcome["passed"],
            checked_rows=outcome["checked_rows"],
            failed_rows=outcome["failed_rows"],
            sample=outcome["sample"],
            message=outcome["message"][:500],
            duration_ms=outcome["duration_ms"],
        )
        rule.last_checked_at = timezone.now()
        rule.last_passed = outcome["passed"]
        rule.save(update_fields=["last_checked_at", "last_passed", "updated_at"])
        results.append(outcome)

    by_severity = {level: {"total": 0, "failed": 0} for level in QUALITY_SEVERITY}
    for item in results:
        bucket = by_severity.setdefault(item["severity"],
                                        {"total": 0, "failed": 0})
        bucket["total"] += 1
        if not item["passed"]:
            bucket["failed"] += 1
    severe_failures = sum(1 for item in results
                          if not item["passed"] and item["severity"] == "error")
    return {
        "total": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "severe_failures": severe_failures,
        "by_severity": by_severity,
        "results": results,
    }


def test_rule(pipeline, payload: dict, rows: list[dict] | None = None) -> dict:
    """测试规则：可传样例行，也可直接对最近一次落地数据试跑（不落库）。"""
    if payload is None or not isinstance(payload, dict):
        raise ValueError("规则参数必须是对象")
    rule_id = payload.get("id") or payload.get("rule_id")
    if rule_id:
        rule = pipeline.quality_rules.filter(pk=rule_id).first()
        if rule is None:
            raise ValueError("质量规则不存在")
        draft = {
            "id": rule.id,
            "name": rule.name,
            "rule_type": payload.get("rule_type") or rule.rule_type,
            "field": payload.get("field", rule.field),
            "params": payload.get("params", rule.params),
            "severity": payload.get("severity") or rule.severity,
        }
    else:
        draft = {
            "name": payload.get("name") or "临时规则",
            "rule_type": payload.get("rule_type"),
            "field": payload.get("field", ""),
            "params": payload.get("params") or {},
            "severity": payload.get("severity") or "warning",
        }
    validate_rule(draft)

    if rows is None:
        if payload.get("run_id"):
            run = pipeline.runs.filter(pk=payload["run_id"]).first()
            if run is None:
                raise ValueError("运行记录不存在")
            rows = output_rows_for_run(run)
        else:
            rows = latest_output_rows(pipeline)
    rows = list(rows or [])
    if not rows:
        # 没有落地数据的纯校验场景：给一条空行，至少能验证规则参数
        rows = [{}]
    outcome = evaluate_rule(draft, rows)
    outcome["sample_rows"] = rows[:3]
    return outcome
