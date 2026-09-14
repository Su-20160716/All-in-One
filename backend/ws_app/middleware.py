"""WebSocket 认证中间件

原实现只依赖 AuthMiddlewareStack（Session），而前端用的是 JWT —— token 存在
localStorage 里、请求不带 Session Cookie，因此 scope["user"] 一直是匿名，
WebSocket 会被直接 close(4001)。

这里补上 JWT 认证：
1. 优先从 `?token=<access_token>` 查询参数取（浏览器 WebSocket 无法自定义请求头）
2. 其次读 `Authorization: Bearer`（供测试客户端/原生客户端使用）
3. 都不可用时退回 AuthMiddlewareStack（保留 Session 登录的场景）

排障：握手失败会打印一条 WARNING（含 path 与具体原因），因为 Daphne 只会显示一个
笼统的 `WebSocket REJECT`，无法区分「没带 token」「token 过期」「签名不对」。
"""
import logging
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger("ws_app.auth")


@database_sync_to_async
def _resolve_user(token: str):
    """校验 token 并取出用户，返回 (user, reason)。

    reason 仅用于日志排障，取值：ok / no-token / token-expired /
    token-invalid(...) / token-missing-user_id / user-not-found-or-inactive
    """
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    if not token:
        return AnonymousUser(), "no-token"
    try:
        validated = AccessToken(token)
    except TokenError as exc:
        detail = str(exc).lower()
        if "expired" in detail:
            return AnonymousUser(), "token-expired"
        return AnonymousUser(), f"token-invalid({exc})"
    except Exception as exc:  # noqa: BLE001 - 任何解析异常都不应中断握手
        return AnonymousUser(), f"token-error({exc})"

    user_id = validated.get("user_id")
    if not user_id:
        return AnonymousUser(), "token-missing-user_id"
    user = get_user_model().objects.filter(id=user_id, is_active=True).first()
    if not user:
        return AnonymousUser(), "user-not-found-or-inactive"
    return user, "ok"


def _extract_token(scope):
    qs = parse_qs((scope.get("query_string") or b"").decode(errors="ignore"))
    token = (qs.get("token") or [""])[0].strip()
    if token:
        return token
    for key, value in (scope.get("headers") or []):
        if key == b"authorization":
            raw = value.decode(errors="ignore").strip()
            if raw.lower().startswith("bearer "):
                return raw[7:].strip()
    return ""


class JWTAuthMiddleware:
    """JWT 优先、Session 兜底的 WebSocket 认证中间件"""

    def __init__(self, inner):
        self.inner = inner
        self.fallback = AuthMiddlewareStack(inner)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "?")
        token = _extract_token(scope)

        if token:
            user, reason = await _resolve_user(token)
            if getattr(user, "is_authenticated", False):
                scope = dict(scope)
                scope["user"] = user
                scope["ws_auth"] = "jwt"
                return await self.inner(scope, receive, send)
            # 带了 token 却没通过 —— 这是最需要排障的场景（历史行为：继续回退 Session）
            logger.warning("WebSocket 携带的 token 未通过校验 path=%s reason=%s，回退 Session", path, reason)
            scope = dict(scope)
            scope["ws_auth"] = reason
            return await self.fallback(scope, receive, send)

        # 未携带 token：交给 Session 兜底。若前端本应带 token，说明前端没送出来。
        logger.info("WebSocket 未携带 token，回退 Session 认证 path=%s", path)
        scope = dict(scope)
        scope["ws_auth"] = "session-fallback"
        return await self.fallback(scope, receive, send)
