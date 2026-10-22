# -*- coding: utf-8 -*-
"""HTTP 入参安全转换：as_int / parse_bool / as_date。

背景（S1-B1）：全仓巡检发现成片 `int(request.data["x"])` 与
`bool(request.data["flag"])`——前者传 "abc" 就地 500，后者
`bool("false") is True` 语义反转。HTTP 入参一律不可信，
「转换」必须同时是「校验」。

约定：
- 值缺失（None / 空串）：传了 default 就用 default；没传（_MISSING）报错
- 显式传了垃圾值（"abc" / "3.7" / JSON true）：报错，不猜、不静默截断
- "12.0" 这类整数值字符串按 12 处理；"12.5" 算错
- 失败统一抛 DRF ValidationError → 走统一异常处理 → 400

已在 devtools/common.py 提供 req_num/opt_num/opt_bool（绑定 request），
本模块面向 DRF 视图里散落的裸转换，不重复造轮子。
"""
from datetime import date, datetime

from rest_framework.exceptions import ValidationError

__all__ = ["as_int", "parse_bool", "as_date"]

# 没传 default 时的哨兵：区别于「default=None 表示缺失取 None」
_MISSING = object()

_TRUTHY = {"1", "true", "yes", "on", "y", "t"}
_FALSY = {"0", "false", "no", "off", "n", "f", ""}


def _label(field):
    return field or "参数"


def as_int(value, default=_MISSING, field="", minimum=None, maximum=None):
    """把入参安全转成 int；失败抛 ValidationError（→ 400）。

    :param default: 值缺失时的兜底；不传表示必填
    """
    name = _label(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is _MISSING:
            raise ValidationError(f"{name} 必须是整数")
        return default
    if isinstance(value, bool):
        # bool 是 int 的子类，JSON true 不该悄悄变成 1
        raise ValidationError(f"{name} 必须是整数")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValidationError(f"{name} 必须是整数")
        result = int(value)
    else:
        text = str(value).strip()
        try:
            result = int(text)
        except ValueError:
            try:
                num = float(text)
            except ValueError:
                raise ValidationError(f"{name} 必须是整数")
            if not num.is_integer():
                raise ValidationError(f"{name} 必须是整数")
            result = int(num)
    if minimum is not None and result < minimum:
        raise ValidationError(f"{name} 不能小于 {minimum}")
    if maximum is not None and result > maximum:
        raise ValidationError(f"{name} 不能大于 {maximum}")
    return result


def parse_bool(value, default=False, field=""):
    """安全解析布尔入参：只认显式真假值集合，垃圾值 400。

    `bool("false")` 是 True——历史上直接用 bool() 包字符串，
    `?flag=false` 实际把功能打开了。这里显式列举，传错就报错。
    """
    name = _label(field)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    raise ValidationError(f"{name} 必须是布尔值")


def as_date(value, field=""):
    """把入参安全转成 date（YYYY-MM-DD）；失败抛 ValidationError。

    历史上 `created_at__date__gte=date_from` 直接透传字符串，
    Django 在查询校验期抛的异常不被 DRF 识别 → 500。
    """
    name = _label(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{name} 必须是日期（YYYY-MM-DD）")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(f"{name} 必须是日期（YYYY-MM-DD）")
