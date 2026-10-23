# -*- coding: utf-8 -*-
"""统一异常处理：把 DRF 异常转成 {code, message, detail} 结构"""
import logging

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def _record(exc, context):
    """F633 异常聚合：把未处理的服务端异常按签名去重计数（失败静默，绝不影响响应）"""
    try:
        from core.platform import record_exception

        request = (context or {}).get("request")
        record_exception(exc, getattr(request, "path", "") if request else "")
    except Exception:
        # 有意兜底：聚合记录失败绝不能影响主响应；但留日志便于发现
        # record_exception 自身的问题（B23）
        logger.exception("F633 异常聚合记录失败（不影响主响应）")


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
            elif isinstance(data, (list, tuple)):
                # DRF ValidationError 的 detail 是列表（如 as_int 抛的），
                # 直接 str() 会带上方括号和引号，逐条拍平 join
                parts = [str(x) for x in data]
            else:
                parts.append(str(data))
            message = "；".join(parts) or "参数校验失败"
        return Response(
            {"code": response.status_code, "message": message, "detail": data},
            status=response.status_code,
        )
    # 未识别异常（ValueError 等）：DRF 默认会 re-raise 成 500，
    # 这里结构化兜底。生产环境不回显 str(exc)——可能带 SQL、路径、
    # 密钥片段；完整堆栈进日志，前端只拿通用文案（S1-B25）。
    request = (context or {}).get("request")
    logger.exception(
        "未处理异常 %s %s", getattr(request, "method", ""), getattr(request, "path", "")
    )
    if settings.DEBUG:
        return Response(
            {"code": 500, "message": "服务器内部错误", "detail": str(exc)}, status=500
        )
    return Response({"code": 500, "message": "服务器内部错误"}, status=500)
