# -*- coding: utf-8 -*-
"""订阅计费 · 视图公共助手。

集中三类重复劳动：
1. 分页（统一 {items,count,page,page_size}，page_size 上限 200）；
2. 入参归一化（金额走 Decimal、日期走 YYYY-MM-DD、枚举给出中文错误）；
3. 取对象 + 权限（读走数据范围，写只认 owner/管理员）。
视图里只保留业务分支，避免 100+ 接口各写一遍分页与异常。
"""
from django.db.models import Q

from devtools.common import ok, opt_bool, opt_num, opt_str, p, req_str
from core.scoping import is_visible

from billing import services
from billing.models import (
    Customer,
    Invoice,
    Meter,
    Plan,
    Price,
    Subscription,
)

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 200


def page_params(request):
    """分页参数：page>=1，page_size 1..200（默认 20）。"""
    page = int(opt_num(request, "page", 1, integer=True, minimum=1) or 1)
    size = int(opt_num(request, "page_size", PAGE_SIZE_DEFAULT, integer=True,
                       minimum=1, maximum=PAGE_SIZE_MAX) or PAGE_SIZE_DEFAULT)
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

    搜索字段由调用方按模型给出（只允许真实列名，避免 ORM 注入式的
    动态字段拼接）；status 为空串时不过滤，便于前端「全部」选项。
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


def filter_by(qs, request, key, field=None):
    """按可选整型外键过滤（parent_id 等），未传则原样返回。"""
    value = p(request, key)
    if value in (None, ""):
        return qs
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是整数")
    return qs.filter(**{field or key: number})


def choice_param(request, key, allowed, default, label):
    """枚举参数校验：非法值直接中文报错，而不是静默落库脏数据。"""
    value = opt_str(request, key, default).strip()
    if value not in allowed:
        raise ValueError(f"{label}必须是 {'/'.join(allowed)} 之一")
    return value


def money_param(request, key, required=False, default=None, minimum=None, maximum=None):
    """金额参数：走 Decimal 解析，required 时校验存在。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    return services.to_decimal(value, key, minimum=minimum, maximum=maximum)


def int_param(request, key, default=None, minimum=None, maximum=None, required=False):
    """整型参数：交给 devtools 的 req_num/opt_num，NaN/超界统一中文提示。"""
    if required and p(request, key) is None:
        raise ValueError(f"缺少必填参数: {key}")
    if p(request, key) is None:
        return default
    return int(opt_num(request, key, default, integer=True,
                       minimum=minimum, maximum=maximum))


def bool_param(request, key, default=False):
    """布尔参数（兼容 1/true/yes/on 字符串）。"""
    return opt_bool(request, key, default)


def date_param(request, key, required=False):
    """日期参数：YYYY-MM-DD；空值返回 None。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return None
    return services.parse_date(value, key)


def datetime_param(request, key, required=False):
    """时间参数：ISO 8601；空值返回 None。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return None
    return services.parse_datetime(value, key)


def dict_param(request, key, required=False):
    """对象型参数；空值按空字典处理（PATCH 语义）。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是对象")
    return value


def list_param(request, key, required=False, max_len=500):
    """数组型参数；限制长度避免超大 JSON 拖垮请求。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return []
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_len:
        raise ValueError(f"参数 {key} 最多 {max_len} 项")
    return value


def get_plan(pk, user, write=False):
    """取计划并做读/写权限校验。"""
    plan = Plan.objects.filter(pk=pk).first()
    if plan is None:
        raise ValueError("计划不存在")
    (services.ensure_writable if write else services.ensure_visible)(plan, user)
    return plan


def get_plan_feature(pk, user, write=False):
    from billing.models import PlanFeature

    obj = PlanFeature.objects.select_related("plan", "feature").filter(pk=pk).first()
    if obj is None:
        raise ValueError("计划功能不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_price(pk, user, write=False):
    """取价格；价格写权限跟随其所属计划（改价必须能改计划）。"""
    price = Price.objects.select_related("plan").filter(pk=pk).first()
    if price is None:
        raise ValueError("价格不存在")
    if write:
        services.ensure_writable(price.plan, user)
    else:
        services.ensure_visible(price, user)
    return price


def get_feature(pk, user, write=False):
    from billing.models import Feature

    obj = Feature.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError("功能项不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_customer(pk, user, write=False):
    """取客户并做权限校验；客户是后续订阅/发票的归属根。"""
    obj = Customer.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError("客户不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_subscription(pk, user, write=False):
    obj = Subscription.objects.select_related("customer", "plan").filter(pk=pk).first()
    if obj is None:
        raise ValueError("订阅不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_meter(pk, user, write=False):
    obj = Meter.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError("计量项不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def get_invoice(pk, user, write=False):
    obj = Invoice.objects.select_related("customer", "subscription").filter(pk=pk).first()
    if obj is None:
        raise ValueError("发票不存在")
    (services.ensure_writable if write else services.ensure_visible)(obj, user)
    return obj


def visible_or_404(model, pk, user, message):
    """通用取数：不存在 → 中文错误；存在但不可见 → 无权查看。"""
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise ValueError(message)
    services.ensure_visible(obj, user)
    return obj


def assert_status(obj, allowed, action="执行该操作"):
    """状态机前置校验：不在允许集合内时给出「当前状态 X 不可…」。"""
    if obj.status not in allowed:
        raise ValueError(f"当前状态 {obj.status} 不能{action}")
    return obj


def ensure_owner_visible(obj, user):
    """兼容旧调用的可见性判定（返回布尔，不抛异常）。"""
    return services._is_admin(user) or is_visible(obj, user)
