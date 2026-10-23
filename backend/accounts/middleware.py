"""账号相关中间件：
- LastActiveMiddleware：节流更新用户最后活跃时间；拦截被禁用账号的已登录请求；
  会话被踢出 / 批量强制下线后，对应 access token 立即失效（F637 批量下线依赖此实现）。
- TenantMiddleware：解析当前请求所属租户，挂到 request.tenant（多租户基础层）
"""
import logging

logger = logging.getLogger(__name__)

import base64
import json

from django.http import JsonResponse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from core.utils import get_client_ip

# 仅这些前缀计入活跃 / 做禁用拦截
API_PREFIX = "/api/"
# 距离上次活跃超过该秒数才落库，避免每次请求写库
ACTIVE_THROTTLE_SECONDS = 60


def _peek_jti(raw_token: str):
    """不解签地读取 JWT payload 里的 jti（仅用于查 ActiveSession，不做鉴权）"""
    try:
        parts = (raw_token or "").split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
        jti = data.get("jti")
        return str(jti) if jti else None
    except Exception:
        return None


class LastActiveMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # F637：被踢出的会话（ActiveSession.is_revoked）对应令牌立即失效。
        # 该判定只依赖 Authorization 头，因此放在用户认证判断之前
        # （JWT 请求在中间件阶段 request.user 仍是匿名）。
        if request.path.startswith(API_PREFIX):
            auth = request.META.get("HTTP_AUTHORIZATION") or ""
            if auth[:7].lower() == "bearer ":
                token = auth[7:].strip()
                if token and not token.startswith("pat_"):
                    jti = _peek_jti(token)
                    if jti:
                        try:
                            from accounts.models import ActiveSession

                            if ActiveSession.objects.filter(jti=jti, is_revoked=True).exists():
                                return JsonResponse(
                                    {
                                        "ok": False,
                                        "code": 401,
                                        "error": "session_revoked",
                                        "message": "登录会话已被踢出，请重新登录",
                                    },
                                    status=401,
                                )
                        except Exception:
                            logger.exception("B23：静默兜底已登记（accounts/middleware.py:62 原为 pass）——review 是否应收窄异常类型")

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None
        # 被禁用账号：除登出外一律拒绝
        if getattr(user, "is_disabled", False):
            # 延迟导入，避免循环依赖
            from rest_framework.response import Response
            from rest_framework import status as http_status

            if request.path.startswith(API_PREFIX) and not request.path.endswith("/logout/"):
                return Response(
                    {"code": 403, "message": "账号已被禁用，请联系管理员", "detail": {}},
                    status=http_status.HTTP_403_FORBIDDEN,
                )
        now = timezone.now()
        last = user.last_active_at
        if last is None or (now - last).total_seconds() > ACTIVE_THROTTLE_SECONDS:
            # 注意：request.user 可能是 SimpleLazyObject，type(user) 会拿到包装类而非 User 模型，
            # 用 __class__ 才能取到真实模型类（SimpleLazyObject 会代理该属性）
            user.__class__.objects.filter(pk=user.pk).update(last_active_at=now)
            user.last_active_at = now
        return None


class TenantMiddleware(MiddlewareMixin):
    """把当前用户的租户挂到 request.tenant。

    解析顺序：显式请求头 X-Tenant-Code（超管切换租户）→ 用户自身租户。
    仅供业务代码读取，不做硬性拦截（是否强隔离由 TENANCY_ENABLED 决定）。
    """

    def process_request(self, request):
        request.tenant = None
        code = request.headers.get("X-Tenant-Code", "").strip()
        if code:
            from accounts.models import Tenant

            tenant = Tenant.objects.filter(code=code, is_active=True).first()
            if tenant is not None:
                request.tenant = tenant
                return None
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False) and getattr(user, "tenant_id", None):
            request.tenant = user.tenant
        return None
