"""#416 幂等键中间件：同键同用户的 POST 在 24 小时内直接回放首次 2xx 响应。

约定（与前端 ``Idempotency-Key`` 头对齐）：
- 只处理 ``POST /api/...``，且请求头必须带 8–128 位安全字符的 ``Idempotency-Key``；
  缺失时完全走原链路（行为逐字节不变）；
- 只缓存 **2xx** 响应（失败不占用幂等键，客户端可重试）；
- 缓存 24 小时，键按「用户 + 请求路径 + 幂等键」隔离，不同用户互不可见；
- 流式响应、附件下载、超过 1MB 的响应一律不缓存（避免把文件流塞进缓存）；
- 缓存后端用 settings.CACHES（默认 LocMem，单进程有效；多实例部署请配 Redis）。

注册位置：MIDDLEWARE 末尾（认证 / 操作日志 / 维护模式之后，最靠近视图），
这样判断用户时 JWT 已由 DRF 解析完成（DRF 认证会把 user 回写到 Django request）。
"""
import hashlib
import logging
import re

from django.core.cache import cache
from django.http import HttpResponse

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"
CACHE_PREFIX = "idem:"
CACHE_TTL = 24 * 60 * 60          # 24 小时
MAX_CACHED_BYTES = 1024 * 1024    # 1MB：超过不缓存
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
# 登录/注册/刷新等「一次性凭据」接口绝不缓存：回放会泄露他人的令牌
SKIP_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/token",
    "/api/auth/refresh",
    "/api/auth/verify",
)


def _scope_for_request(request) -> str:
    """用户作用域：登录用户用 ``u<id>``，JWT 用令牌里的 user_id，兜底用凭据指纹。

    取不到用户时返回空串（调用方据此放弃缓存）——宁可不去重，也不能把 A 的响应
    回放给 B。
    """
    user = getattr(request, "user", None)
    try:
        if user is not None and getattr(user, "is_authenticated", False):
            return f"u{getattr(user, 'pk', '')}"
    except Exception:  # noqa: BLE001 —— SimpleLazyObject 解析异常按未登录处理
        pass
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth[:7].lower() == "bearer ":
        token = auth[7:].strip()
        try:
            from rest_framework_simplejwt.tokens import AccessToken

            uid = AccessToken(token).get("user_id")
            if uid:
                return f"u{uid}"
        except Exception:  # noqa: BLE001 —— 令牌无效/过期：下面用指纹兜底
            pass
        if token:
            return "c" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
    credential = (request.headers.get("X-Api-Token") or "").strip()
    if credential:
        return "c" + hashlib.sha256(credential.encode("utf-8")).hexdigest()[:32]
    return ""


def _cache_key(scope: str, path: str, key: str) -> str:
    digest = hashlib.sha256(f"{scope}\n{path}\n{key}".encode("utf-8")).hexdigest()
    return f"{CACHE_PREFIX}{digest}"


def _response_is_cacheable(response) -> bool:
    if not (200 <= getattr(response, "status_code", 0) < 300):
        return False
    if getattr(response, "streaming", False):
        return False
    if response.has_header("Content-Disposition"):  # 附件 / 导出下载
        return False
    return True


class IdempotencyMiddleware:
    """读 ``Idempotency-Key``，24h 内同键同用户回放首次 2xx 响应"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = (request.headers.get(IDEMPOTENCY_HEADER) or "").strip()
        if not self._eligible(request, key):
            return self.get_response(request)
        scope = _scope_for_request(request)
        if not scope:
            return self.get_response(request)
        cache_key = _cache_key(scope, request.path, key)
        cached = self._load(cache_key)
        if cached is not None:
            request.idempotent_replay = True
            return self._replay(cached)
        response = self.get_response(request)
        try:
            request.idempotent_replay = False
        except Exception:  # noqa: BLE001
            pass
        self._store(cache_key, response)
        return response

    @staticmethod
    def _eligible(request, key: str) -> bool:
        if request.method != "POST":
            return False
        path = request.path or ""
        if not path.startswith("/api/"):
            return False
        if any(path.startswith(p) for p in SKIP_PREFIXES):
            return False
        return bool(key and KEY_RE.match(key))

    @staticmethod
    def _load(cache_key: str):
        try:
            value = cache.get(cache_key)
        except Exception:  # noqa: BLE001 —— 缓存不可用就当没命中
            logger.debug("幂等缓存读取失败 key=%s", cache_key, exc_info=True)
            return None
        if not isinstance(value, dict) or "body" not in value:
            return None
        return value

    @staticmethod
    def _replay(payload: dict) -> HttpResponse:
        response = HttpResponse(
            payload.get("body") or b"",
            status=int(payload.get("status") or 200),
            content_type=payload.get("content_type") or "application/json",
        )
        response["X-Idempotent-Replay"] = "true"
        return response

    @staticmethod
    def _store(cache_key: str, response) -> None:
        if not _response_is_cacheable(response):
            return
        try:
            body = response.content
        except Exception:  # noqa: BLE001 —— 已被流式消费/无内容，放弃缓存
            return
        if body is None or len(body) > MAX_CACHED_BYTES:
            return
        payload = {
            "status": response.status_code,
            "body": body,
            "content_type": response.get("Content-Type") or "application/json",
        }
        try:
            cache.set(cache_key, payload, CACHE_TTL)
        except Exception:  # noqa: BLE001 —— 写缓存失败不能影响响应
            logger.debug("幂等缓存写入失败 key=%s", cache_key, exc_info=True)
