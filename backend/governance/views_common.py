# -*- coding: utf-8 -*-
"""合规治理 · 视图公共助手。

把 100+ 接口里重复的分页、入参归一化、取对象 + 行级权限收敛成一组
小函数，视图本身只保留「业务分支 + 状态机」。

权限口径（与 core.scoping 对齐，不另起炉灶）
------------------------------------------
- 读：数据范围可见（scope_queryset / is_visible）；
- 写：owner 严格收口，管理员（is_staff / is_superuser）额外放行；
- 审批 / 发布 / 验证：允许 owner 与管理员，因为治理流程里审批人往往是
  合规负责人而非录入人；其余角色一律无写权限。
"""
from django.db.models import Q

from core.scoping import is_visible, scope_queryset
from devtools.common import ok, opt_bool, opt_num, opt_str, p

from governance import services
from governance.models import (
    Assessment,
    AssessmentItem,
    Audit,
    ConsentRecord,
    Control,
    ControlTest,
    DataAsset,
    Evidence,
    Finding,
    Framework,
    FrameworkControl,
    Policy,
    ProcessingActivity,
    RemediationTask,
    RetentionAction,
    RetentionRule,
    Risk,
    RiskTreatment,
)

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 200


# ---------------------------------------------------------------------------
# 分页与筛选
# ---------------------------------------------------------------------------


def page_params(request):
    """分页参数：page >= 1，page_size 1..200（默认 20，上限强制夹住）。"""
    page = int(opt_num(request, "page", 1, integer=True, minimum=1) or 1)
    size = int(opt_num(request, "page_size", PAGE_SIZE_DEFAULT, integer=True,
                       minimum=1, maximum=PAGE_SIZE_MAX) or PAGE_SIZE_DEFAULT)
    return page, size


def paginate(qs, request, render=None):
    """统一列表响应 {items,count,page,page_size}；切片在数据库侧完成。"""
    page, size = page_params(request)
    total = qs.count()
    start = (page - 1) * size
    rows = list(qs[start:start + size])
    items = [render(obj) if render else obj.to_dict() for obj in rows]
    return ok({"items": items, "count": total, "page": page, "page_size": size})


def apply_search(qs, request, fields, status_field="status"):
    """q 模糊搜索 + status 精确过滤。

    fields 由调用方显式给出真实列名（不做动态字段拼接），
    避免把用户输入当 ORM 路径导致意外的跨表关联或注入式查询。
    """
    keyword = opt_str(request, "q").strip()
    if keyword:
        cond = Q()
        for field in fields:
            cond |= Q(**{f"{field}__icontains": keyword})
        qs = qs.filter(cond)
    status = opt_str(request, "status").strip()
    if status:
        if not status_field:
            raise ValueError("该资源不支持 status 过滤")
        qs = qs.filter(**{status_field: status})
    return qs


def filter_int(qs, request, key, field=None):
    """可选整型过滤（framework_id / risk_id / assessment_id ...）。"""
    value = p(request, key)
    if value in (None, ""):
        return qs
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是整数")
    return qs.filter(**{field or key: number})


def filter_choice(qs, request, key, allowed, field=None):
    """可选枚举过滤：非法值直接报错，避免返回空列表让人误以为没数据。"""
    value = opt_str(request, key).strip()
    if not value:
        return qs
    if value not in allowed:
        raise ValueError(f"参数 {key} 必须是 {'/'.join(allowed)} 之一")
    return qs.filter(**{field or key: value})


def filter_bool(qs, request, key, field=None):
    """可选布尔过滤（仅当参数出现时才生效）。"""
    if p(request, key) in (None, ""):
        return qs
    return qs.filter(**{field or key: opt_bool(request, key)})


def param_int(request, key, default=None, minimum=None, maximum=None, required=False):
    """整型入参（视图层薄封装，保持错误提示统一为中文）。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    # 统一转成「必须是整数」：底层 req_num 的提示是「必须是数字」，
    # 但业务语义上 3.5 这类小数对等级/次数并不合法，不能被静默截断。
    try:
        number = opt_num(request, key, None, integer=False)
    except ValueError:
        raise ValueError(f"参数 {key} 必须是整数")
    if isinstance(number, bool):
        raise ValueError(f"参数 {key} 必须是整数")
    try:
        as_int = int(number)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是整数")
    if as_int != number:
        raise ValueError(f"参数 {key} 必须是整数")
    if minimum is not None and as_int < minimum:
        raise ValueError(f"参数 {key} 不能小于 {minimum}")
    if maximum is not None and as_int > maximum:
        raise ValueError(f"参数 {key} 不能大于 {maximum}")
    return as_int


def param_str(request, key, default="", required=False, max_len=200):
    """短字符串入参：统一截断或报错，避免超长值进 CharField 触发数据库异常。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    text = str(value)
    if max_len and len(text) > max_len:
        raise ValueError(f"参数 {key} 超过最大长度 {max_len} 字符（当前 {len(text)}）")
    return text


def param_text(request, key, default="", required=False, max_len=20000):
    """长文本入参（正文、描述）：默认 2 万字符，防止单条记录拖垮列表。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    text = str(value)
    if max_len and len(text) > max_len:
        raise ValueError(f"参数 {key} 超过最大长度 {max_len} 字符")
    return text


def param_date(request, key, required=False, default=None):
    """日期入参（YYYY-MM-DD）。"""
    return services.parse_date(p(request, key), key, required=required) or default


def param_datetime(request, key, required=False, default=None):
    """时间入参（ISO 8601）。"""
    return services.parse_datetime(p(request, key), key, required=required) or default


def param_choice(request, key, allowed, default=None, required=False):
    """枚举入参。"""
    return services.choice(p(request, key), key, allowed, default=default, required=required)


def param_bool(request, key, default=None):
    """布尔入参：未传时返回 default，用于区分「显式 false」与「未提供」。"""
    if p(request, key) in (None, ""):
        return default
    return bool(opt_bool(request, key))


def param_list(request, key, required=False, max_len=200):
    """JSON 数组入参（步骤、数据类别等）。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return []
    return services.json_list(value, key, max_len=max_len)


# ---------------------------------------------------------------------------
# 取对象 + 权限
# ---------------------------------------------------------------------------


def _fetch(model, pk, user, label, write):
    """通用取数：不存在 / 不可见 / 不可写分别给出可读中文错误。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(f"{label}不存在")
    # 写场景允许管理员越过「数据范围可见性」：审批 / 发布类操作由平台管理员
    # 兜底是治理流程的既定口径（数据范围只决定「看见什么」，不决定「能否治理」）。
    if not is_visible(obj, user) and not (write and services.is_admin(user)):
        raise ValueError(f"无权访问该{label}")
    if write:
        services.ensure_writable(obj, user)
    return obj


def get_framework(pk, user, write=False):
    """框架。"""
    return _fetch(Framework, pk, user, "合规框架", write)


def get_framework_control(pk, user, write=False):
    """框架控制项。"""
    return _fetch(FrameworkControl, pk, user, "框架控制项", write)


def get_policy(pk, user, write=False):
    """策略。"""
    return _fetch(Policy, pk, user, "策略", write)


def get_control(pk, user, write=False):
    """内部控制。"""
    return _fetch(Control, pk, user, "控制", write)


def get_control_test(pk, user, write=False):
    """控制测试。"""
    return _fetch(ControlTest, pk, user, "控制测试", write)


def get_assessment(pk, user, write=False):
    """评估。"""
    return _fetch(Assessment, pk, user, "评估", write)


def get_assessment_item(pk, user, write=False):
    """评估项。"""
    return _fetch(AssessmentItem, pk, user, "评估项", write)


def get_evidence(pk, user, write=False):
    """证据。"""
    return _fetch(Evidence, pk, user, "证据", write)


def get_risk(pk, user, write=False):
    """风险。"""
    return _fetch(Risk, pk, user, "风险", write)


def get_treatment(pk, user, write=False):
    """风险处置。"""
    return _fetch(RiskTreatment, pk, user, "风险处置", write)


def get_data_asset(pk, user, write=False):
    """数据资产。"""
    return _fetch(DataAsset, pk, user, "数据资产", write)


def get_processing(pk, user, write=False):
    """处理活动。"""
    return _fetch(ProcessingActivity, pk, user, "处理活动", write)


def get_retention_rule(pk, user, write=False):
    """保留规则。"""
    return _fetch(RetentionRule, pk, user, "保留规则", write)


def get_retention_action(pk, user, write=False):
    """保留期动作。"""
    return _fetch(RetentionAction, pk, user, "保留动作", write)


def get_consent(pk, user, write=False):
    """同意记录。"""
    return _fetch(ConsentRecord, pk, user, "同意记录", write)


def get_audit(pk, user, write=False):
    """审计。"""
    return _fetch(Audit, pk, user, "审计", write)


def get_finding(pk, user, write=False):
    """审计发现。"""
    return _fetch(Finding, pk, user, "审计发现", write)


def get_remediation(pk, user, write=False):
    """整改任务。"""
    return _fetch(RemediationTask, pk, user, "整改任务", write)


def scoped(model, user, **filters):
    """列表用 queryset：数据范围 + 可选过滤。"""
    return scope_queryset(model.objects.filter(**filters), user)


def ensure_parent_owned(parent, user, label):
    """子资源写入前校验父资源写权限（子表的 owner 继承父表）。"""
    if parent is None:
        raise ValueError(f"{label}不存在")
    services.ensure_writable(parent, user)
    return parent
