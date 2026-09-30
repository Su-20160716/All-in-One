# -*- coding: utf-8 -*-
"""devtools 通用助手：统一入参提取、统一响应、统一异常兜底。

约定：
- 所有接口 POST 为主（少量 GET），入参从 JSON body / query 提取；
- 参数缺失/非法抛 ValueError → 400，计算类异常兜底 422（结构化，不 500）；
- 响应统一 {"ok": True, "data": ...} / {"ok": False, "error": ...}。
"""
from functools import wraps

from rest_framework.decorators import api_view
from rest_framework.response import Response


def endpoint_index(patterns, exclude=("catalog/",)):
    """从 urlpatterns 导出接口明细 [{path, methods}]，供前端目录动态渲染。

    DRF api_view 会把允许方法写入 view.cls.http_method_names（小写），
    借此还原每个路径的真实方法；排除目录自身。仅新增能力，不改任何既有契约。
    """
    out = []
    for p in patterns:
        route = str(p.pattern)
        if route in exclude:
            continue
        cls = getattr(getattr(p, "callback", None), "cls", None)
        names = [
            m.upper()
            for m in (getattr(cls, "http_method_names", None) or [])
            if m not in ("options", "head")
        ]
        out.append({"path": route, "methods": names or ["POST"]})
    return out


def ok(data=None, **extra):
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return Response(payload)


def fail(message, status=400, **extra):
    body = {"ok": False, "error": str(message)}
    body.update(extra)
    return Response(body, status=status)


def endpoint(methods=("POST",)):
    """视图装饰器：api_view + 统一异常兜底。"""

    def deco(fn):
        @wraps(fn)
        def impl(request, *a, **kw):
            try:
                return fn(request, *a, **kw)
            except ValueError as e:
                return fail(e, status=400)
            except Exception as e:  # noqa: BLE001 —— 结构化降级，绝不 500
                return fail(f"{type(e).__name__}: {e}", status=422)

        return api_view(list(methods))(impl)

    return deco


# ---------- 入参提取 ----------


def _payload(request):
    if request.method == "GET":
        return request.query_params.dict()
    data = request.data
    return data if isinstance(data, dict) else {}


def p(request, key, default=None):
    """任意取参。"""
    return _payload(request).get(key, default)


def req(request, key, default=None):
    """必填取参，缺失抛 ValueError。"""
    val = _payload(request).get(key, default)
    if val is None or (isinstance(val, str) and not val.strip()):
        raise ValueError(f"缺少必填参数: {key}")
    return val


def req_str(request, key="text", default=None):
    val = req(request, key, default)
    return val if isinstance(val, str) else str(val)


def opt_str(request, key, default=""):
    val = p(request, key, default)
    return val if isinstance(val, str) else str(val)


def req_num(request, key, default=None, minimum=None, maximum=None, integer=False):
    val = _payload(request).get(key, default)
    if val is None:
        raise ValueError(f"缺少必填参数: {key}")
    try:
        val = float(val)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {key} 必须是数字")
    if integer:
        val = int(round(val))
    if minimum is not None and val < minimum:
        raise ValueError(f"参数 {key} 不能小于 {minimum}")
    if maximum is not None and val > maximum:
        raise ValueError(f"参数 {key} 不能大于 {maximum}")
    return val


def opt_num(request, key, default=None, **kw):
    if p(request, key) is None:
        return default
    return req_num(request, key, default=default, **kw)


def req_list(request, key, default=None, max_len=20000):
    val = _payload(request).get(key, default)
    if val is None:
        raise ValueError(f"缺少必填参数: {key}")
    if isinstance(val, str):
        val = [ln for ln in val.replace("\r\n", "\n").split("\n")]
    if not isinstance(val, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(val) > max_len:
        raise ValueError(f"参数 {key} 超过最大长度 {max_len}")
    return val


def opt_bool(request, key, default=False):
    val = p(request, key, default)
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("1", "true", "yes", "on")


def as_lines(text):
    return text.replace("\r\n", "\n").split("\n")
