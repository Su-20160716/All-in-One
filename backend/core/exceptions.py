"""统一异常处理：把 DRF 异常转成 {code, message, detail} 结构"""
from rest_framework.response import Response
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
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
