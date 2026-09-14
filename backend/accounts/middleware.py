"""账号相关中间件：
- LastActiveMiddleware：节流更新用户最后活跃时间；拦截被禁用账号的已登录请求
- TenantMiddleware：解析当前请求所属租户，挂到 request.tenant（多租户基础层）
"""
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from core.utils import get_client_ip

# 仅这些前缀计入活跃 / 做禁用拦截
API_PREFIX = "/api/"
# 距离上次活跃超过该秒数才落库，避免每次请求写库
ACTIVE_THROTTLE_SECONDS = 60


class LastActiveMiddleware(MiddlewareMixin):
    def process_request(self, request):
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
            type(user).objects.filter(pk=user.pk).update(last_active_at=now)
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
