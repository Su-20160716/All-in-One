# -*- coding: utf-8 -*-
"""统一异常处理：把 DRF 异常转成 {code, message, detail} 结构"""
import logging

from django.conf import settings
from django.core.exceptions import RequestDataTooBig, TooManyFieldsSent
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# #94 请求体超限 → 413 统一 JSON
# Django 遇到超过 DATA_UPLOAD_MAX_MEMORY_SIZE 的正文会抛 RequestDataTooBig（SuspiciousOperation），
# 默认被渲染成 400 的纯文本响应，前端拿不到 code/message，只能提示「请求失败」；
# 字段数超限同理（TooManyFieldsSent）。这里在进视图前按 Content-Length 预判，
# 直接返回与全站一致的 JSON 结构，且不读 body（不先占一整块内存）。
# 上限值见 config/settings.py：DATA_UPLOAD_MAX_MEMORY_SIZE / DATA_UPLOAD_MAX_NUMBER_FIELDS。
# ---------------------------------------------------------------------------
def upload_limit_bytes() -> int:
    """当前生效的请求体上限（字节）；配置异常时返回 0 表示不预判"""
    try:
        return int(getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 0) or 0)
    except (TypeError, ValueError):
        return 0


def payload_too_large_response(limit_bytes: int = 0, reason: str = "size"):
    limit_mb = round(limit_bytes / 1024 / 1024, 1) if limit_bytes else None
    if reason == "fields":
        message = "请求字段过多"
    else:
        message = "请求体过大" + (f"（上限 {limit_mb}MB）" if limit_mb else "")
    return JsonResponse(
        {
            "code": 413,
            "error": "payload_too_large",
            "message": message,
            "detail": {"max_bytes": limit_bytes or None, "reason": reason},
        },
        status=413,
    )


class PayloadTooLargeMiddleware:
    """#94：把超限请求映射为 413 JSON。

    multipart/form-data 的正文是文件分片，不计入 DATA_UPLOAD_MAX_MEMORY_SIZE，
    只受 DATA_UPLOAD_MAX_NUMBER_FIELDS 约束（超限时 Django 抛 TooManyFieldsSent，
    在下面按 413 兜底）。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        limit = upload_limit_bytes()
        try:
            content_type = (request.content_type or "").lower()
            if limit > 0 and "multipart/form-data" not in content_type:
                length = int(request.META.get("CONTENT_LENGTH") or 0)
                if length > limit:
                    try:
                        from core.middleware import get_request_id

                        rid = get_request_id()
                    except Exception:
                        rid = "-"
                    logger.warning(
                        "请求体超限 %s %s %s>%s rid=%s",
                        request.method, request.path, length, limit, rid,
                    )
                    return payload_too_large_response(limit)
        except (TypeError, ValueError):
            pass
        try:
            return self.get_response(request)
        except (RequestDataTooBig, TooManyFieldsSent) as exc:
            return payload_too_large_response(limit, reason="fields" if isinstance(exc, TooManyFieldsSent) else "size")



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
