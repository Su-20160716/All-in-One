"""WebSocket 认证中间件

原实现只依赖 AuthMiddlewareStack（Session），而前端用的是 JWT —— token 存在
localStorage 里、请求不带 Session Cookie，因此 scope["user"] 一直是匿名，
WebSocket 会被直接 close(4001)。

这里补上 JWT 认证，凭证读取优先级：
1. `?ticket=<一次性票据>`（#37：60 秒有效、校验即作废，见 mint_ws_ticket）
2. `?token=<access_token>`（历史方式，仍可用但会打弃用日志）
3. `Authorization: Bearer`（供测试客户端/原生客户端使用）
4. 都不可用时退回 AuthMiddlewareStack（保留 Session 登录的场景）

安全约束（审查 #33）：
- 只要请求「带了凭证」就绝不再回退 Session：凭证失效即 close(4003)。
  否则恶意页面可以塞一个坏 token 让服务端走 Cookie 认证（CSWSH）。
- 生产环境（DEBUG=False）在中间件层再兜一次 Origin：不在显式白名单内直接拒绝，
  绝不允许 `*` 通配（asgi 层的 OriginValidator 只是第一道闸）。

排障：握手失败会打印一条 WARNING（含 path 与具体原因），因为 Daphne 只会显示一个
笼统的 `WebSocket REJECT`，无法区分「没带 token」「token 过期」「签名不对」。
"""
import logging
import os
import secrets
from urllib.parse import parse_qs

from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache

logger = logging.getLogger("ws_app.auth")

# #37：一次性 ticket 的有效期与缓存前缀。
# ticket 只在握手时用一次，不进查询串长期保存；校验成功即刻删除。
WS_TICKET_TTL = 60
WS_TICKET_PREFIX = "ws:ticket:"


def mint_ws_ticket(user) -> str:
    """为已登录用户签发短时一次性 WS ticket（默认 60 秒）。

    前端拿到后以 `/ws/notify/?ticket=<ticket>` 握手，避免把 access token 写进
    URL（Daphne/Nginx 访问日志、代理日志、浏览器历史都会留存查询串）。
    """
    ticket = secrets.token_urlsafe(32)
    try:
        cache.set(f"{WS_TICKET_PREFIX}{ticket}", getattr(user, "id", None), WS_TICKET_TTL)
    except Exception:  # cache 不可用时退化为空串，调用方仍可回落到 ?token=
        logger.exception("#37 签发 WS ticket 失败（cache 不可用）")
        return ""
    return ticket


@database_sync_to_async
def _consume_ticket(ticket: str):
    """校验并作废一次性 ticket，返回 (user, reason)。"""
    from django.contrib.auth import get_user_model

    if not ticket:
        return AnonymousUser(), "empty-ticket"
    key = f"{WS_TICKET_PREFIX}{ticket}"
    try:
        user_id = cache.get(key)
    except Exception as exc:  # noqa: BLE001 - cache 故障不应中断握手日志
        return AnonymousUser(), f"ticket-cache-error({exc})"
    if not user_id:
        return AnonymousUser(), "ticket-invalid"
    try:
        cache.delete(key)  # 一次性：无论后续用户校验结果如何都不再可用
    except Exception:  # noqa: BLE001
        logger.warning("#37 ticket 作废失败（cache delete），已按有效凭证继续校验")
    user = get_user_model().objects.filter(id=user_id, is_active=True).first()
    if not user:
        return AnonymousUser(), "user-not-found-or-inactive"
    return user, "ok"


@database_sync_to_async
def _resolve_user(token: str):
    """校验 token 并取出用户，返回 (user, reason)。

    reason 仅用于日志排障，取值：ok / no-token / token-expired /
    token-invalid(...) / token-missing-user_id / user-not-found-or-inactive /
    token-version-mismatch（B12：tv claim 与用户当前 token_version 不一致，
    改密 / 强制下线后签发的旧 token 一律拒绝，与 HTTP 侧认证保持同一套规则）
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
    # B12：tv claim 缺失或与当前 token_version 不一致 → 视为已失效
    if validated.get("tv") != user.token_version:
        return AnonymousUser(), "token-version-mismatch"
    return user, "ok"


def _extract_credentials(scope):
    """返回 (kind, value, supplied)。supplied=True 表示客户端主动提供了凭证，
    即使值为空也不能再回退 Session（否则 `?token=` 就是绕过口子）。

    kind: "ticket"（#37 一次性票据）/ "query-token"（历史 ?token=）/
    "header-token"（Authorization: Bearer）
    """
    qs = parse_qs((scope.get("query_string") or b"").decode(errors="ignore"), keep_blank_values=True)
    if "ticket" in qs:
        return "ticket", (qs.get("ticket") or [""])[0].strip(), True
    if "token" in qs:
        return "query-token", (qs.get("token") or [""])[0].strip(), True
    for key, value in (scope.get("headers") or []):
        if key == b"authorization":
            raw = value.decode(errors="ignore").strip()
            if raw.lower().startswith("bearer "):
                return "header-token", raw[7:].strip(), True
            if raw:
                return "header-token", "", True
    return "header-token", "", False


def _header(scope, name: bytes) -> str:
    for key, value in (scope.get("headers") or []):
        if key == name:
            return value.decode(errors="ignore").strip()
    return ""


def _explicit_origins():
    """显式允许的 Origin 集合（绝不包含 `*`）。

    与 config.asgi._ws_allowed_origins 保持同样的来源（CORS / CSRF / ALLOWED_HOSTS /
    WS_ALLOWED_ORIGINS），但不做任何通配回退：生产配置里即使写了 `*` 也忽略。
    """
    origins = set()
    for raw in list(getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []) + list(
        getattr(settings, "CSRF_TRUSTED_ORIGINS", []) or []
    ):
        raw = str(raw or "").strip().rstrip("/")
        if raw and "*" not in raw:
            origins.add(raw)
    for host in getattr(settings, "ALLOWED_HOSTS", []) or []:
        host = str(host or "").strip()
        if not host or "*" in host:
            continue
        origins.add(f"https://{host}")
        origins.add(f"http://{host}")
    for raw in os.environ.get("WS_ALLOWED_ORIGINS", "").split(","):
        raw = raw.strip().rstrip("/")
        if raw and "*" not in raw:
            origins.add(raw)
    return origins


def _origin_allowed(scope) -> bool:
    """生产环境校验 Origin；开发（DEBUG）与无 Origin 的原生客户端放行。"""
    if settings.DEBUG:
        return True
    origin = _header(scope, b"origin").rstrip("/")
    if not origin:
        return True
    return origin in _explicit_origins()


async def _reject(send, code: int = 4003, reason: str = ""):
    """握手阶段拒绝：4003 = 认证/来源被拒绝。"""
    await send({"type": "websocket.close", "code": code, "reason": reason})


class JWTAuthMiddleware:
    """JWT 优先、Session 兜底的 WebSocket 认证中间件"""

    def __init__(self, inner):
        self.inner = inner
        self.fallback = AuthMiddlewareStack(inner)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "?")
        if not _origin_allowed(scope):
            logger.warning("WebSocket Origin 不在白名单，拒绝连接 path=%s origin=%s",
                           path, _header(scope, b"origin"))
            return await _reject(send, 4003, "origin-rejected")

        kind, credential, supplied = _extract_credentials(scope)

        if supplied:
            if not credential:
                logger.warning("WebSocket 提供了空凭证，拒绝连接 path=%s", path)
                return await _reject(send, 4003, "empty-token")
            if kind == "ticket":
                # #37：一次性 ticket —— 校验通过即作废，可用于全部 WS 路由
                user, reason = await _consume_ticket(credential)
                auth_mode = "ticket"
            else:
                if kind == "query-token":
                    # 历史 ?token= 方式：保留可用，但记录弃用日志推动客户端迁移
                    # （token 会落入访问日志/代理日志/浏览器历史）
                    logger.warning(
                        "#37 WebSocket 使用已弃用的 ?token= 凭证 path=%s，请改用短时一次性 ticket",
                        path,
                    )
                user, reason = await _resolve_user(credential)
                auth_mode = "jwt"
            if getattr(user, "is_authenticated", False):
                scope = dict(scope)
                scope["user"] = user
                scope["ws_auth"] = auth_mode
                return await self.inner(scope, receive, send)
            # 带了凭证却没通过：绝不回退 Session（否则坏 token 可借 Cookie 建连）
            logger.warning("WebSocket 携带的凭证未通过校验 path=%s reason=%s，拒绝连接", path, reason)
            return await _reject(send, 4003, reason)

        # 未携带 token：交给 Session 兜底。若前端本应带 token，说明前端没送出来。
        logger.info("WebSocket 未携带 token，回退 Session 认证 path=%s", path)
        scope = dict(scope)
        scope["ws_auth"] = "session-fallback"
        return await self.fallback(scope, receive, send)
