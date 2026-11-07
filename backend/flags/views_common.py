# -*- coding: utf-8 -*-
"""功能开关 · 视图公共助手。

集中四类重复劳动：

1. 分页：统一 ``{items, count, page, page_size}``，page_size 上限 200；
2. 入参：百分比/布尔/JSON/数组/枚举统一中文报错；
3. 取对象 + 权限：读走数据范围（core.scoping），写只认 owner/管理员；
4. 审计与缓存失效：所有写接口收口到 ``after_write``，避免漏记审计或漏清缓存。

为什么要多一层「父对象权限」
----------------------------
环境、开关、细分、实验存在层级关系，但 owner 分别落在各自表上。如果只按
子对象 owner 判定，项目负责人把成员的开关归档就会被拒绝；反之如果完全不
校验，任何登录用户都能改别人的开关。这里的口径是：

- 读：子对象可见 **或** 所属项目可见；
- 写：子对象 owner 可写 **或** 所属项目 owner 可写（管理员恒可写）。
"""
from django.db.models import Q

from core.scoping import can_write, is_visible

from devtools.common import ok, opt_bool, opt_num, opt_str, p
from flags import services
from flags.models import (
    Audience,
    Environment,
    Experiment,
    ExperimentMetric,
    Flag,
    FlagDependency,
    Guardrail,
    Project,
    Rollout,
    Segment,
    SegmentRule,
    TargetingRule,
    Variant,
)

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 200


# ---------------------------------------------------------------------------
# 分页与搜索
# ---------------------------------------------------------------------------


def page_params(request):
    """分页参数：page >= 1，page_size 1..200（默认 20）。"""
    page = int(opt_num(request, "page", 1, integer=True, minimum=1) or 1)
    size = int(
        opt_num(request, "page_size", PAGE_SIZE_DEFAULT, integer=True,
                minimum=1, maximum=PAGE_SIZE_MAX) or PAGE_SIZE_DEFAULT
    )
    return page, size


def paginate(qs, request, render):
    """标准列表响应：翻页切片 + 总数 + 回显分页参数。"""
    page, size = page_params(request)
    total = qs.count()
    start = (page - 1) * size
    rows = [render(obj) for obj in qs[start:start + size]]
    return ok({"items": rows, "count": total, "page": page, "page_size": size})


def apply_search(qs, request, fields, status_field="status"):
    """q 模糊搜索 + status 精确过滤。

    搜索字段由调用方按模型给出（只允许真实列名），避免把用户输入拼进
    ORM 字段名；status 为空串时不过滤，前端「全部」选项直接透传。
    """
    keyword = opt_str(request, "q").strip()
    if keyword:
        cond = Q()
        for field in fields:
            cond |= Q(**{f"{field}__icontains": keyword})
        qs = qs.filter(cond)
    status = opt_str(request, "status").strip()
    if status and status_field:
        qs = qs.filter(**{status_field: status})
    return qs


def filter_int(qs, request, key, field=None):
    """可选整型过滤（project_id / environment_id / flag_id 等）。"""
    value = p(request, key)
    if value in (None, ""):
        return qs
    number = services.parse_int(value, key, minimum=1)
    return qs.filter(**{field or key: number})


# ---------------------------------------------------------------------------
# 入参助手
# ---------------------------------------------------------------------------


def str_param(request, key, default="", max_len=200000):
    return opt_str(request, key, default, max_len=max_len).strip()


def bool_param(request, key, default=False):
    return opt_bool(request, key, default)


def int_param(request, key, default=None, minimum=None, maximum=None):
    if p(request, key) in (None, ""):
        return default
    return services.parse_int(p(request, key), key, default, minimum=minimum, maximum=maximum)


def percent_param(request, key, default=0):
    return services.parse_percent(p(request, key), key, default)


def json_param(request, key, default=None):
    return services.parse_json(p(request, key), key, default)


def list_param(request, key, default=None, max_len=500):
    value = p(request, key)
    if value in (None, ""):
        return [] if default is None else default
    value = services.parse_json(value, key, default)
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    return value


def dict_param(request, key, default=None):
    value = p(request, key)
    if value in (None, ""):
        return {} if default is None else default
    value = services.parse_json(value, key, default)
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是对象")
    return value


def choice_param(request, key, allowed, default, label):
    return services.parse_choice(p(request, key), allowed, label, default)


def flag_param(request, key="flag_type", default="boolean"):
    from flags.models import FLAG_TYPES

    return services.parse_choice(p(request, key), FLAG_TYPES, "开关类型", default)


# ---------------------------------------------------------------------------
# 权限与取对象
# ---------------------------------------------------------------------------


def can_read_project(project, user):
    return services.is_admin(user) or is_visible(project, user)


def can_write_project(project, user):
    return services.is_admin(user) or can_write(user, project)


def can_read_flag(flag, user):
    if services.is_admin(user):
        return True
    return is_visible(flag, user) or is_visible(flag.project, user)


def can_write_flag(flag, user):
    if services.is_admin(user):
        return True
    return can_write(user, flag) or can_write(user, flag.project)


def get_project(pk, user, write=False):
    project = Project.objects.filter(pk=pk).first()
    if project is None:
        raise ValueError("项目不存在")
    if write:
        if not can_write_project(project, user):
            raise ValueError("无权修改该项目")
    elif not can_read_project(project, user):
        raise ValueError("无权查看该项目")
    return project


def get_environment(pk, user, write=False):
    env = Environment.objects.select_related("project").filter(pk=pk).first()
    if env is None:
        raise ValueError("环境不存在")
    if write:
        if not (can_write_project(env.project, user) or can_write(user, env)):
            raise ValueError("无权修改该环境")
    elif not can_read_project(env.project, user) and not is_visible(env, user):
        raise ValueError("无权查看该环境")
    return env


def get_flag(pk, user, write=False):
    flag = Flag.objects.select_related("project", "environment").filter(pk=pk).first()
    if flag is None:
        raise ValueError("开关不存在")
    if write:
        if not can_write_flag(flag, user):
            raise ValueError("无权修改该开关")
    elif not can_read_flag(flag, user):
        raise ValueError("无权查看该开关")
    return flag


def get_flag_by_key(project, environment, key, user, write=False):
    """按项目 + 环境 + 键名定位开关（评估接口对 SDK 友好）。"""
    flag = Flag.objects.select_related("project", "environment").filter(
        project=project, environment=environment, key=str(key).strip().lower()
    ).first()
    if flag is None:
        raise ValueError(f"开关不存在: {key}")
    if write:
        if not can_write_flag(flag, user):
            raise ValueError("无权修改该开关")
    elif not can_read_flag(flag, user):
        raise ValueError("无权查看该开关")
    return flag


def get_segment(pk, user, write=False):
    segment = Segment.objects.select_related("project").filter(pk=pk).first()
    if segment is None:
        raise ValueError("细分不存在")
    if write:
        if not (can_write_project(segment.project, user) or can_write(user, segment)):
            raise ValueError("无权修改该细分")
    elif not can_read_project(segment.project, user) and not is_visible(segment, user):
        raise ValueError("无权查看该细分")
    return segment


def get_rollout(pk, user, write=False):
    rollout = Rollout.objects.select_related("flag", "flag__project", "segment").filter(
        pk=pk).first()
    if rollout is None:
        raise ValueError("灰度不存在")
    if write:
        if not can_write_flag(rollout.flag, user):
            raise ValueError("无权修改该灰度")
    elif not can_read_flag(rollout.flag, user):
        raise ValueError("无权查看该灰度")
    return rollout


def get_targeting_rule(pk, user, write=False):
    rule = TargetingRule.objects.select_related("flag", "flag__project").filter(pk=pk).first()
    if rule is None:
        raise ValueError("定向规则不存在")
    if write:
        if not can_write_flag(rule.flag, user):
            raise ValueError("无权修改该定向规则")
    elif not can_read_flag(rule.flag, user):
        raise ValueError("无权查看该定向规则")
    return rule


def get_variant(pk, user, write=False):
    variant = Variant.objects.select_related("flag", "flag__project").filter(pk=pk).first()
    if variant is None:
        raise ValueError("变体不存在")
    if write:
        if not can_write_flag(variant.flag, user):
            raise ValueError("无权修改该变体")
    elif not can_read_flag(variant.flag, user):
        raise ValueError("无权查看该变体")
    return variant


def get_segment_rule(pk, user, write=False):
    rule = SegmentRule.objects.select_related("segment", "segment__project").filter(pk=pk).first()
    if rule is None:
        raise ValueError("细分规则不存在")
    if write:
        if not (can_write_project(rule.segment.project, user) or can_write(user, rule.segment)):
            raise ValueError("无权修改该细分规则")
    elif not can_read_project(rule.segment.project, user):
        raise ValueError("无权查看该细分规则")
    return rule


def get_experiment(pk, user, write=False):
    experiment = Experiment.objects.select_related("flag", "flag__project").filter(pk=pk).first()
    if experiment is None:
        raise ValueError("实验不存在")
    if write:
        if not can_write_flag(experiment.flag, user) and not can_write(user, experiment):
            raise ValueError("无权修改该实验")
    elif not can_read_flag(experiment.flag, user):
        raise ValueError("无权查看该实验")
    return experiment


def get_metric(pk, user, write=False):
    metric = ExperimentMetric.objects.select_related("experiment", "experiment__flag").filter(
        pk=pk).first()
    if metric is None:
        raise ValueError("指标不存在")
    if write:
        if not can_write_flag(metric.experiment.flag, user):
            raise ValueError("无权修改该指标")
    elif not can_read_flag(metric.experiment.flag, user):
        raise ValueError("无权查看该指标")
    return metric


def get_audience(pk, user, write=False):
    audience = Audience.objects.select_related("project").filter(pk=pk).first()
    if audience is None:
        raise ValueError("受众不存在")
    if write:
        if not (can_write_project(audience.project, user) or can_write(user, audience)):
            raise ValueError("无权修改该受众")
    elif not can_read_project(audience.project, user):
        raise ValueError("无权查看该受众")
    return audience


def get_dependency(pk, user, write=False):
    dep = FlagDependency.objects.select_related(
        "flag", "flag__project", "depends_on").filter(pk=pk).first()
    if dep is None:
        raise ValueError("依赖不存在")
    if write:
        if not can_write_flag(dep.flag, user):
            raise ValueError("无权修改该依赖")
    elif not can_read_flag(dep.flag, user):
        raise ValueError("无权查看该依赖")
    return dep


def get_guardrail(pk, user, write=False):
    guardrail = Guardrail.objects.select_related("flag", "flag__project").filter(pk=pk).first()
    if guardrail is None:
        raise ValueError("护栏不存在")
    if write:
        if not can_write_flag(guardrail.flag, user):
            raise ValueError("无权修改该护栏")
    elif not can_read_flag(guardrail.flag, user):
        raise ValueError("无权查看该护栏")
    return guardrail


# ---------------------------------------------------------------------------
# 写后处理
# ---------------------------------------------------------------------------


def after_write(actor, obj, action, before=None, after=None, project=None, note=""):
    """统一写后动作：审计 + 缓存失效。

    审计失败不影响业务（record_audit 内部吞异常），但缓存必须清干净，
    否则用户会看到「刚改完开关但评估结果没变」。
    """
    services.record_audit(actor, obj, action, before=before, after=after,
                          project=project, note=note)
    if isinstance(obj, Flag):
        services.invalidate_flag(obj.id)
    elif hasattr(obj, "flag_id") and obj.flag_id:
        services.invalidate_flag(obj.flag_id)
    elif isinstance(obj, Environment):
        for flag_id in obj.flags.values_list("id", flat=True):
            services.invalidate_flag(flag_id)


def visible_flags(user):
    """当前用户可读的开关（项目可见也纳入）。"""
    from django.db.models import Q

    if services.is_admin(user):
        return Flag.objects.all()
    from core.scoping import visible_user_ids

    ids = visible_user_ids(user)
    if ids is None:
        return Flag.objects.all()
    return Flag.objects.filter(Q(owner_id__in=ids) | Q(project__owner_id__in=ids)).distinct()


def resolve_flag(request, user, write=False, key="flag_id"):
    """按 id 或 key 解析开关。

    评估接口既接受数值 id，也接受 ``flag`` 键名；键名需要同时给项目或
    环境，否则同名开关在不同环境下会歧义。
    """
    raw = p(request, key)
    if raw in (None, ""):
        raw = p(request, "flag")
    if raw in (None, ""):
        raise ValueError("缺少必填参数: flag_id 或 flag")
    text = str(raw).strip()
    if text.isdigit():
        return get_flag(int(text), user, write=write)
    environment = None
    env_id = p(request, "environment_id")
    env_key = p(request, "environment") or p(request, "environment_key")
    if env_id not in (None, ""):
        environment = get_environment(int(env_id), user)
    elif env_key not in (None, ""):
        environment = Environment.objects.filter(key=str(env_key).strip()).first()
        if environment is None:
            raise ValueError("环境不存在")
    project = None
    project_id = p(request, "project_id")
    project_key = p(request, "project") or p(request, "project_key")
    if project_id not in (None, ""):
        project = get_project(int(project_id), user)
    elif project_key not in (None, ""):
        project = Project.objects.filter(key=str(project_key).strip()).first()
        if project is None:
            raise ValueError("项目不存在")
    if environment is not None and project is None:
        project = environment.project
    if environment is None and project is not None:
        environment = project.environments.order_by("sort_order", "id").first()
        if environment is None:
            raise ValueError("项目下没有环境")
    if project is None or environment is None:
        raise ValueError("按键名评估时必须提供 project_id 或 environment_id")
    return get_flag_by_key(project, environment, text, user, write=write)


def context_param(request):
    """评估上下文：支持 context 对象或 attributes（二者等价）。"""
    raw = p(request, "context")
    field = "context"
    if raw in (None, ""):
        raw = p(request, "attributes")
        field = "attributes"
    return services.parse_json(raw, field, {})
