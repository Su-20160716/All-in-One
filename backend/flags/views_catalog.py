# -*- coding: utf-8 -*-
"""功能开关 · 目录接口（1 个）。

目录是前端的「能力说明书」：枚举、操作符、字段约定、分页契约、评估语义与
接口清单一次返回，前端不需要硬编码任何状态或路径。
"""
from devtools.common import endpoint, endpoint_index, ok

from flags import services
from flags.models import (
    DEPENDENCY_RELATIONS,
    DEPENDENCY_RELATION_LABELS,
    ENV_TYPES,
    ENV_TYPE_LABELS,
    EXPERIMENT_STATUS,
    EXPERIMENT_STATUS_LABELS,
    FLAG_STATUS,
    FLAG_STATUS_LABELS,
    FLAG_TYPES,
    FLAG_TYPE_LABELS,
    GUARDRAIL_ACTIONS,
    GUARDRAIL_ACTION_LABELS,
    LOGIC_OPS,
    LOGIC_OP_LABELS,
    METRIC_DIRECTIONS,
    METRIC_DIRECTION_LABELS,
    METRIC_TYPES,
    METRIC_TYPE_LABELS,
    OPERATORS,
    OPERATOR_LABELS,
    PROJECT_STATUS,
    PROJECT_STATUS_LABELS,
    ROLLOUT_STATUS,
    ROLLOUT_STATUS_LABELS,
    Audience,
    Environment,
    Experiment,
    Flag,
    Guardrail,
    Project,
    Rollout,
    Segment,
)

CAPABILITY_DOMAINS = [
    {"key": "catalog", "title": "目录", "items": [
        "枚举与操作符清单", "评估语义与分页契约", "接口明细"]},
    {"key": "project", "title": "项目与环境", "items": [
        "项目 CRUD 与成员管理", "环境 CRUD/启停", "生产环境修改写审计"]},
    {"key": "flag", "title": "功能开关", "items": [
        "布尔/多变量开关", "启停/克隆/归档", "版本发布/列表/回滚"]},
    {"key": "evaluation", "title": "评估", "items": [
        "单用户评估", "批量评估", "布尔快照", "命中解释", "评估历史"]},
    {"key": "targeting", "title": "定向与灰度", "items": [
        "细分与细分规则", "定向规则优先级", "灰度百分比推进", "变体权重"]},
    {"key": "experiment", "title": "实验", "items": [
        "实验生命周期", "稳定入组与曝光幂等", "结果/进度/曝光统计"]},
    {"key": "governance", "title": "依赖与护栏", "items": [
        "开关依赖与环检测", "护栏阈值检查", "受众预览", "审计日志"]},
    {"key": "stats", "title": "统计", "items": [
        "概览", "评估量 TOP", "变体分布", "评估趋势", "实验看板"]},
]


def _enum(values, labels):
    return [{"value": value, "label": labels.get(value, value)} for value in values]


def _counts(user):
    """当前用户可见的规模统计（管理员看全量）。"""
    flags = services.visible(Flag.objects.all(), user)
    experiments = services.visible(Experiment.objects.all(), user)
    return {
        "projects": services.visible(Project.objects.all(), user).count(),
        "environments": services.visible(Environment.objects.all(), user).count(),
        "flags": flags.count(),
        "active_flags": flags.filter(status="active").count(),
        "segments": services.visible(Segment.objects.all(), user).count(),
        "audiences": services.visible(Audience.objects.all(), user).count(),
        "rollouts": services.visible(Rollout.objects.all(), user).count(),
        "experiments": experiments.count(),
        "running_experiments": experiments.filter(status="running").count(),
        "guardrails": services.visible(Guardrail.objects.all(), user).count(),
    }


@endpoint(("GET",))
def catalog(request):
    """功能开关目录：枚举、操作符、字段、分页契约、评估语义与接口清单。"""
    from flags.urls import urlpatterns

    endpoints = endpoint_index(urlpatterns, exclude=("",))
    return ok({
        "app": "flags",
        "name": "功能开关与实验",
        "version": "1.0",
        "description": "功能开关 / 灰度发布 / A-B 实验一体化引擎，评估结果确定性可复现。",
        "capabilities": CAPABILITY_DOMAINS,
        "pagination": {
            "page_size_default": 20,
            "page_size_max": 200,
            "response_shape": ["items", "count", "page", "page_size"],
            "filters": ["q", "status", "page", "page_size"],
        },
        "enums": {
            "project_status": _enum(PROJECT_STATUS, PROJECT_STATUS_LABELS),
            "env_types": _enum(ENV_TYPES, ENV_TYPE_LABELS),
            "flag_types": _enum(FLAG_TYPES, FLAG_TYPE_LABELS),
            "flag_status": _enum(FLAG_STATUS, FLAG_STATUS_LABELS),
            "rollout_status": _enum(ROLLOUT_STATUS, ROLLOUT_STATUS_LABELS),
            "experiment_status": _enum(EXPERIMENT_STATUS, EXPERIMENT_STATUS_LABELS),
            "metric_types": _enum(METRIC_TYPES, METRIC_TYPE_LABELS),
            "metric_directions": _enum(METRIC_DIRECTIONS, METRIC_DIRECTION_LABELS),
            "guardrail_actions": _enum(GUARDRAIL_ACTIONS, GUARDRAIL_ACTION_LABELS),
            "dependency_relations": _enum(DEPENDENCY_RELATIONS, DEPENDENCY_RELATION_LABELS),
            "logic_ops": _enum(LOGIC_OPS, LOGIC_OP_LABELS),
        },
        "operators": _enum(OPERATORS, OPERATOR_LABELS),
        "fields": {
            "user": ["user.id", "user.email", "user.country", "user.plan", "user.version"],
            "custom": ["custom.*（任意自定义属性，如 custom.device）"],
            "flat": ["上下文中已存在的同名字段或 a.b.c 点路径"],
            "notes": "user.* 优先取 context.user，其次取扁平键；custom.* 取 context.custom。",
        },
        "evaluation": {
            "input": ["flag_id 或 flag + project_id/environment_id", "user_key", "context"],
            "output": ["enabled", "value", "variant", "payload", "reason", "latency_ms"],
            "reasons": [
                "targeting:<rule_id>",
                "experiment:<name>",
                "rollout:<N>%",
                "segment:<name>",
                "dependency:<flag_key>",
                "flag-inactive",
                "environment-disabled",
                "default",
            ],
            "deterministic": "sha256(flag_key + user_key + salt) 映射 0..9999，同一输入结果稳定。",
            "log_retention": "每个开关最多保留最近若干条评估日志，超出按时间截断。",
        },
        "semantics": {
            "flag_types": {
                "boolean": "enabled=true/false，value 为布尔值",
                "multivariate": "variant 为变体键，value 为变体 payload",
            },
            "rollout": "百分比 + 可选细分 + 生效时间窗口；100% 不自动改状态，由推进接口完成。",
            "experiment": "running 状态的实验优先于灰度；用户入组由实验 id 分桶，换配置不换组。",
            "dependency": "requires 要求上游开启，forbids 要求上游关闭；成环在写入时拒绝。",
            "guardrail": "指标超阈值时按 pause/rollback/notify 处置并写审计。",
        },
        "counts": _counts(request.user),
        "endpoints": endpoints,
    })
