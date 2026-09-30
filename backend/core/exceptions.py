"""统一异常处理：把 DRF 异常转成 {code, message, detail} 结构"""
from rest_framework.response import Response
from rest_framework.views import exception_handler


def _record(exc, context):
    """F633 异常聚合：把未处理的服务端异常按签名去重计数（失败静默，绝不影响响应）"""
    try:
        from core.platform import record_exception

        request = (context or {}).get("request")
        record_exception(exc, getattr(request, "path", "") if request else "")
    except Exception:
        pass


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        _record(exc, context)
    elif response.status_code >= 500:
        _record(exc, context)
    if response is not None:
        data = response.data
        if isinstance(data, dict) and "detail" in data and len(data) == 1:
            message = str(data["detail"])
        else:
            parts = []
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, (list, tuple)) and v:
                        parts.append(f"{k}: {v[0]}")
                    else:
                        parts.append(f"{k}: {v}")
            else:
                parts.append(str(data))
            message = "；".join(parts)
        return Response(
            {"code": response.status_code, "message": message, "detail": data},
            status=response.status_code,
        )
    return Response({"code": 500, "message": "服务器内部错误", "detail": str(exc)}, status=500)
