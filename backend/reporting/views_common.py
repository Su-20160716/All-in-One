# -*- coding: utf-8 -*-
"""视图公共助手：对象获取（含行级权限）、入参解析、状态校验。

为什么单独一层
--------------
reporting 的接口都围绕「数据集/报表/组件/仪表盘」这几类对象展开，
读取要按数据范围（同部门可见），写入只允许 owner（core.scoping.can_write）。
把这些判定收口到 get_visible / get_writable，视图里就不会出现
「有的接口漏了权限判断」这种低级越权。
"""
import json
from datetime import datetime

from django.utils import timezone

from core.scoping import can_write, is_visible, scope_queryset
from devtools.common import opt_num, opt_str, p

from reporting.models import (
    Dashboard, DataSource, Dataset, ReportAnnotation, ReportDefinition,
    ReportPage, ReportWidget,
)
from reporting.whitelist import get_whitelisted_model, model_info

MAX_JSON_CHARS = 200000


def read_json(request, key, default=None, required=False):
    """读取 JSON 入参：既支持对象直传，也支持 JSON 字符串（表单提交常见）。

    长度上限与全局文本参数一致，避免深嵌套大 JSON 拖垮解析。
    """
    value = p(request, key)
    if value is None or value == "":
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_JSON_CHARS:
            raise ValueError(f"参数 {key} 的 JSON 过大")
        try:
            return json.loads(value)
        except ValueError:
            raise ValueError(f"参数 {key} 不是合法 JSON")
    raise ValueError(f"参数 {key} 必须是对象或数组")


def read_json_obj(request, key, default=None):
    """限定为 JSON 对象（数据集过滤/组件配置等）。"""
    value = read_json(request, key, default if default is not None else {})
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是 JSON 对象")
    return value


def read_int_list(request, key, default=None, max_items=50, item_max=3650):
    """整数数组入参（如 recipients 之外的天数列表）。"""
    value = p(request, key)
    if value in (None, ""):
        return list(default or [])
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_items:
        raise ValueError(f"参数 {key} 最多 {max_items} 项")
    out = []
    for item in value:
        try:
            num = int(item)
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 含非整数项")
        if num < 0 or num > item_max:
            raise ValueError(f"参数 {key} 的取值需在 0~{item_max}")
        out.append(num)
    return out


def read_str_list(request, key, default=None, max_items=50, max_len=200):
    """字符串数组（收件人、去重字段等）。"""
    value = p(request, key)
    if value in (None, ""):
        return list(default or [])
    if isinstance(value, str):
        value = [x.strip() for x in value.split(",") if x.strip()]
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_items:
        raise ValueError(f"参数 {key} 最多 {max_items} 项")
    out = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if len(text) > max_len:
            raise ValueError(f"参数 {key} 的单项长度不能超过 {max_len}")
        out.append(text)
    return out


def read_choice(request, key, choices, default=None, required=False):
    """枚举入参校验：choices 是 [(值, 中文)] 或值的集合。"""
    allowed = {c[0] if isinstance(c, (tuple, list)) else c for c in choices}
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return default
    text = str(value)
    if text not in allowed:
        raise ValueError(f"参数 {key} 只支持：{'/'.join(sorted(map(str, allowed)))}")
    return text


def read_bool(request, key, default=False):
    value = p(request, key)
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def read_limit(request, key="limit", default=20, maximum=2000):
    value = opt_num(request, key, default, integer=True, minimum=1, maximum=maximum)
    return int(value)


def read_offset(request, key="offset", default=0):
    value = opt_num(request, key, default, integer=True, minimum=0)
    return int(value)


def read_days(request, key="days", default=30, maximum=365):
    value = opt_num(request, key, default, integer=True, minimum=1, maximum=maximum)
    return int(value)


def read_datetime(request, key, default=None):
    """ISO 日期/时间入参 → aware datetime（为空返回 default）。"""
    text = opt_str(request, key).strip()
    if not text:
        return default
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"参数 {key} 需为 ISO 时间格式")
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


# ---------------------------------------------------------------------------
# 对象获取（含行级权限）
# ---------------------------------------------------------------------------


def get_visible(model, pk, user, label="对象"):
    """按数据范围取可见对象；取不到统一提示「不存在或无权访问」（不泄露存在性）。"""
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise ValueError(f"{label} ID 非法")
    obj = scope_queryset(model.objects.all(), user).filter(pk=pk).first()
    if obj is None:
        raise ValueError(f"{label}不存在或无权访问")
    return obj


def get_writable(model, pk, user, label="对象"):
    """取对象并校验写权限（严格 owner 口径，见 core.scoping.can_write）。"""
    obj = get_visible(model, pk, user, label)
    if not can_write(user, obj):
        raise ValueError(f"无权修改该{label}")
    return obj


def get_source(pk, user, write=False):
    model = DataSource
    return get_writable(model, pk, user, "数据源") if write else get_visible(model, pk, user, "数据源")


def get_dataset(pk, user, write=False):
    return get_writable(Dataset, pk, user, "数据集") if write else get_visible(Dataset, pk, user, "数据集")


def get_report(pk, user, write=False):
    return get_writable(ReportDefinition, pk, user, "报表") if write else get_visible(ReportDefinition, pk, user, "报表")


def get_page(pk, user, write=False):
    """页面没有 owner 字段：可见性/写权限都跟随所属报表（避免无 owner 的 scope 报错）。"""
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise ValueError("页面 ID 非法")
    page = ReportPage.objects.select_related("report").filter(pk=pk).first()
    if page is None or not is_visible(page.report, user):
        raise ValueError("页面不存在或无权访问")
    if write and not can_write(user, page.report):
        raise ValueError("无权修改该页面")
    return page


def get_widget(pk, user, write=False):
    """组件自身没有 owner 字段，权限跟随所属页面 → 报表。"""
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        raise ValueError("组件 ID 非法")
    widget = (ReportWidget.objects.select_related("page", "page__report")
              .filter(pk=pk).first())
    if widget is None or widget.page is None or not is_visible(widget.page.report, user):
        raise ValueError("组件不存在或无权访问")
    if write and not can_write(user, widget.page.report):
        raise ValueError("无权修改该组件")
    return widget


def get_annotation(pk, user, write=False):
    return get_writable(ReportAnnotation, pk, user, "批注") if write else get_visible(ReportAnnotation, pk, user, "批注")


def get_dashboard(pk, user, write=False):
    return get_writable(Dashboard, pk, user, "仪表盘") if write else get_visible(Dashboard, pk, user, "仪表盘")


def assert_visible_report(report, user):
    """跨对象引用时的可见性断言（把别人的报表挂进自己仪表盘要拦）。"""
    if not is_visible(report, user) and not can_write(user, report):
        raise ValueError("无权引用该报表")


# ---------------------------------------------------------------------------
# 模型 / 字段校验
# ---------------------------------------------------------------------------


def require_model(label, field_name="primary_model"):
    """校验模型标签在白名单内，返回模型类。"""
    text = str(label or "").strip()
    if not text:
        raise ValueError(f"缺少必填参数: {field_name}")
    try:
        return get_whitelisted_model(text)
    except ValueError:
        raise ValueError(f"参数 {field_name} 不在模型白名单内：{text}")


def require_model_fields(label, paths, field_name="字段"):
    """批量校验字段路径（保存字段/关联前的前置检查）。"""
    model = require_model(label)
    from reporting.whitelist import resolve_path

    out = []
    for path in paths:
        try:
            out.append(resolve_path(model, path))
        except ValueError as e:
            raise ValueError(f"{field_name} {path} 非法：{e}")
    return out


def model_label_of(label):
    """规范化模型标签并返回原始写法（白名单里的 key）。"""
    info = model_info(str(label or "").strip())
    return f"{info['app_label']}.{info['model_name']}"


def coerce_order(value):
    """排序入参：字符串 "a,-b" 或数组 → 统一列表。"""
    from reporting.compiler import normalize_order

    if value in (None, ""):
        return []
    return normalize_order(value)


def page_size_hint(count, page, size):
    """给前端的翻页提示（是否还有下一页）。"""
    return {"count": count, "page": page, "page_size": size,
            "has_more": page * size < count}


def ensure_dataset_active(dataset):
    if dataset.status != "active":
        raise ValueError(f"数据集「{dataset.name}」已停用，不能执行")


def ensure_report_published(report, action="执行"):
    if report.status == "archived":
        raise ValueError(f"报表已归档，不能{action}")
