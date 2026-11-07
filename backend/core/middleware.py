"""core 中间件：
- MaintenanceModeMiddleware（F639 维护模式守卫）：开启后非 superuser 的 /api/ 请求
  一律返回统一的 503 结构化提示；默认关闭，不影响任何现有接口。
- PAT 鉴权（F621）：`Authorization: Bearer pat_xxx` 或 `X-Api-Token: pat_xxx`
  校验长期访问令牌后，就地换成一个短期 JWT，交给 DRF 既有鉴权链路。

注册说明：`config/settings.py` 的 MIDDLEWARE 已注册 `core.middleware.OperationLogMiddleware`
（config/ 属于本次不可改动范围），因此维护模式与 PAT 鉴权以基类/前置钩子的形式挂在
该类上——它的 process_request 恰好在鉴权中间件之后、视图执行之前运行，效果等价于
独立中间件；两者默认均为「放行」，开启维护模式前行为完全不变。

- OperationLogMiddleware：统一操作日志（写请求记录到 OperationLog），原有行为保持不变。
"""
import logging

logger = logging.getLogger(__name__)

import contextvars
import hashlib
import json
import os
import re
import time
import uuid

from django.http import JsonResponse
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from core.platform import MAINTENANCE_PUBLIC_PREFIXES, maintenance_enabled
from core.utils import get_client_ip

# 注意：`core.models`（OperationLog）改为在 process_response 内延迟导入。
# 本模块会被 LOGGING 的 request_context 过滤器在 django.setup() 阶段导入（早于
# apps.populate），模块级导入项目模型会触发 AppRegistryNotReady。


# ---------------------------------------------------------------------------
# #134 请求上下文（request_id / 当前用户）
# 用 contextvar 保存，供 logging.Filter 注入到每条日志；在 ASGI 下每个请求
# 各自有独立上下文，不会串号。formatter 见 config/settings.py 的 LOGGING。
# ---------------------------------------------------------------------------
_request_id_ctx: contextvars.ContextVar = contextvars.ContextVar("aio_request_id", default="-")
_request_user_ctx: contextvars.ContextVar = contextvars.ContextVar("aio_request_user", default="-")
# 只接受形如 UUID/十六进制的上游 request-id，避免把任意头内容写进日志（日志注入）
_RID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def get_request_id() -> str:
    """当前请求的 request_id（无请求上下文时返回 '-'）"""
    return _request_id_ctx.get()


class RequestContextFilter(logging.Filter):
    """把 request_id / 用户名注入日志记录，供 formatter 的 {request_id} 占位使用"""

    def filter(self, record):  # noqa: A003 —— logging.Filter 约定名
        record.request_id = _request_id_ctx.get()
        record.request_user = _request_user_ctx.get()
        return True


class RequestIdMiddleware:
    """#134：为每个请求分配 request_id，回写 X-Request-Id 响应头。

    放在 MIDDLEWARE 最外层：越早生成，覆盖的日志（含中间件自身）越完整。
    上游（Nginx / 网关）已带 X-Request-Id 时透传，保证跨服务可串联。
    """

    HEADER = "X-Request-Id"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        candidate = (request.headers.get(self.HEADER) or "").strip()
        rid = candidate if _RID_RE.match(candidate) else uuid.uuid4().hex[:16]
        request.request_id = rid
        request_token = _request_id_ctx.set(rid)
        # 同线程上下文可能被复用：先清掉上一次请求残留的用户名
        _request_user_ctx.set("-")
        try:
            response = self.get_response(request)
        finally:
            _request_id_ctx.reset(request_token)
            _request_user_ctx.set("-")
        try:
            response[self.HEADER] = rid
        except Exception:
            pass
        return response

# 跳过路径（避免噪音）。口令类接口必须在内：OperationLog 会把 JSON body 落库，
# 而管理员可通过 /api/core/logs/ 读回，口令一旦入日志等于全站密码泄露。
SKIP_PREFIXES = (
    "/admin", "/static", "/media",
    "/api/auth/token", "/api/auth/refresh", "/api/auth/verify", "/api/auth/login",
)

# #16：账号安全类事件（改密 / 2FA / 管理员改用户与重置密码）不能整段静默——
# 但 body 里有口令与验证码，绝不能落库。只记元信息：用户、路径、结果码、IP。
META_ONLY_PREFIXES = (
    "/api/auth/profile/change-password",
    "/api/auth/profile/deactivate",
    "/api/auth/profile/2fa",
    "/api/auth/admin/users",  # 含 <pk>/reset-password/
)

# 键名命中即脱敏（双保险：即使将来新增口令接口忘了加白名单，也不会写进日志）
_SENSITIVE_KEY_HINTS = (
    "password", "passwd", "secret", "token", "credential",
    "totp", "otp_code", "verify_code", "captcha",
    # #15：嵌套结构里同样会出现的凭证键
    "api_key", "apikey", "access_key", "private_key", "cookie", "authorization",
)

# #15：递归打码的上限——深度 3 层、单层最多 20 个键/元素，超出只留占位
_MAX_MASK_DEPTH = 3
_MAX_DETAIL_KEYS = 20
_MAX_DETAIL_ITEMS = 20
_MAX_VALUE_CHARS = 40
_MAX_DETAIL_CHARS = 1000


def _is_sensitive_key(key) -> bool:
    low = str(key).lower()
    return any(h in low for h in _SENSITIVE_KEY_HINTS)


def _mask_value(value, depth=0):
    """#15：递归遍历 dict/list，按敏感键名打码；深度不超过 3 层。"""
    if depth >= _MAX_MASK_DEPTH:
        return "…"  # 更深层只留占位，避免超深结构撑爆日志
    if isinstance(value, dict):
        return {
            str(k): ("***" if _is_sensitive_key(k) else _mask_value(v, depth + 1))
            for k, v in list(value.items())[:_MAX_DETAIL_KEYS]
        }
    if isinstance(value, (list, tuple)):
        return [_mask_value(v, depth + 1) for v in list(value)[:_MAX_DETAIL_ITEMS]]
    if isinstance(value, str):
        return value[:_MAX_VALUE_CHARS]
    return value


def _safe_detail(body: dict) -> str:
    """把请求体压成一行日志摘要，敏感键（含嵌套）一律打码"""
    head = {k: v for k, v in list(body.items())[:8]}
    return json.dumps(_mask_value(head), ensure_ascii=False, default=str)[:_MAX_DETAIL_CHARS]

PAT_PREFIX = "pat_"

# F01：字段级前后值对比只覆盖三类高频业务对象，避免全局序列化开销
DIFF_TARGETS = (
    (re.compile(r"^/api/notes/(\d+)/$"), "notes.Note",
     ("title", "content", "is_public", "is_archived", "folder_id")),
    (re.compile(r"^/api/files/(\d+)/$"), "files.FileMeta",
     ("name", "description", "folder_id", "is_star")),
    (re.compile(r"^/api/projects/(\d+)/$"), "projects.Project",
     ("name", "description", "status", "is_archived")),
)


def _diff_target(path):
    for pattern, model_path, fields in DIFF_TARGETS:
        m = pattern.match(path)
        if m:
            return model_path, m.group(1), fields
    return None


def _load_instance(model_path, pk):
    from django.apps import apps

    app_label, model_name = model_path.split(".")
    return apps.get_model(app_label, model_name).objects.filter(pk=pk).first()


def _snapshot(obj, fields):
    out = {}
    for field in fields:
        value = getattr(obj, field, None)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        out[field] = value
    return out


def _build_diff(request, response, path):
    if not (200 <= response.status_code < 300):
        return None
    before = getattr(request, "_audit_before", None)
    target = _diff_target(path)
    if not before or target is None:
        return None
    obj = _load_instance(target[0], target[1])
    if obj is None:
        return None
    after = _snapshot(obj, target[2])
    changed = {
        k: {"before": before.get(k), "after": after.get(k)}
        for k in target[2]
        if before.get(k) != after.get(k)
    }
    return changed or None


# ---------------------------------------------------------------------------
# F621 长期访问令牌（PAT）→ 短期 JWT 换发
# ---------------------------------------------------------------------------
def _pat_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# #414 PAT 作用域映射表（方法 + 路径前缀 → 所需 scope）
#
# 路径前缀取自 /api/<app>/...，app 即资源名（/api/auth/... 归到 accounts）。
# 所需 scope = ``<资源>:<动作>``，动作为 read（GET/HEAD/OPTIONS）或 write（其余）。
# 令牌 scopes 命中以下任一即放行：
#   1) 空串 或 ``*``            —— 全权（空串兼容升级前签发的旧令牌）
#   2) 精确的 ``<资源>:<动作>``
#   3) ``<资源>:*``             —— 该资源全部动作
#   4) ``read`` / ``write``     —— 全局读 / 写
#   5) 读请求额外接受 ``<资源>:write``（写权限包含读权限）
#
# 资源别名表：路径第一段 → 资源名；未列出的 app 直接用自己的名字。
SCOPE_RESOURCES = {
    "auth": "accounts",
    "accounts": "accounts",
    "files": "files",
    "notes": "notes",
    "projects": "projects",
    "im": "im",
    "tools": "tools",
    "dashboard": "dashboard",
    "core": "core",
    "learning": "learning",
    "assistant": "assistant",
    "devtools": "devtools",
    "minitools": "minitools",
    "dataintel": "dataintel",
    "officesuite": "officesuite",
    "code": "code",
}
READ_METHODS = ("GET", "HEAD", "OPTIONS")
# 预检请求不带业务语义，任何令牌都放行（否则浏览器侧 CORS 预检全挂）
SCOPE_FREE_PREFIXES = ("/api/core/health/", "/api/core/about/")


def pat_resource_for_path(path: str) -> str:
    """路径 → 资源名（取 /api/<app>/ 的 app；非 /api/ 路径归 api）"""
    parts = [p for p in (path or "").strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == "api":
        app = parts[1]
    elif parts:
        app = parts[0]
    else:
        app = "api"
    return SCOPE_RESOURCES.get(app, app)


def pat_required_scope(method: str, path: str) -> str:
    """请求所需 scope（形如 ``files:read`` / ``core:write``）"""
    action = "read" if (method or "").upper() in READ_METHODS else "write"
    return f"{pat_resource_for_path(path)}:{action}"


def pat_scopes_allow(scopes: str, required: str) -> bool:
    """判断令牌 scopes（逗号串）是否覆盖 required"""
    tokens = [s.strip().lower() for s in (scopes or "").split(",") if s.strip()]
    if not tokens or "*" in tokens:
        return True
    required = (required or "").lower()
    if required in tokens:
        return True
    resource, _, action = required.partition(":")
    if not action:
        return True
    if f"{resource}:*" in tokens:
        return True
    if action in tokens:  # 全局 read / write
        return True
    if action == "read" and f"{resource}:write" in tokens:
        return True
    return False


def _record_pat_usage(pat, path: str) -> None:
    """#415 按日累加令牌调用量（失败绝不影响鉴权）"""
    try:
        from django.db.models import F

        from accounts.models import ApiTokenUsage

        today = timezone.localdate()
        ApiTokenUsage.objects.get_or_create(token=pat, date=today)
        ApiTokenUsage.objects.filter(token=pat, date=today).update(
            count=F("count") + 1, last_path=(path or "")[:200]
        )
    except Exception:  # noqa: BLE001 —— 统计失败不能阻断请求
        logger.debug("PAT 用量记录失败 pat=%s", getattr(pat, "id", "-"), exc_info=True)


def pat_authenticate(request):
    """把合法的 PAT 换成一次性 JWT；返回 JsonResponse 表示直接拒绝，None 表示放行。"""
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    raw = ""
    if auth[:7].lower() == "bearer ":
        candidate = auth[7:].strip()
        if candidate.startswith(PAT_PREFIX):
            raw = candidate
    if not raw:
        raw = (request.headers.get("X-Api-Token") or "").strip()
    if not raw or not raw.startswith(PAT_PREFIX):
        return None  # 普通 JWT / 无令牌：交给 DRF
    try:
        from accounts.models import PersonalAccessToken
        from rest_framework_simplejwt.tokens import AccessToken

        pat = (
            PersonalAccessToken.objects.filter(token_hash=_pat_hash(raw))
            .select_related("user")
            .first()
        )
        if pat is None or not pat.is_valid:
            return JsonResponse(
                {"ok": False, "code": 401, "error": "invalid_token",
                 "message": "访问令牌无效、已过期或已被吊销"},
                status=401,
            )
        user = pat.user
        # PAT 必须随改密/强制下线失效：token_version 变化后旧 PAT 一律作废
        if pat.token_version != getattr(user, "token_version", 0):
            return JsonResponse(
                {"ok": False, "code": 401, "error": "invalid_token",
                 "message": "访问令牌已失效，请重新生成"},
                status=401,
            )
        if not user.is_active or getattr(user, "is_disabled", False):
            return JsonResponse(
                {"ok": False, "code": 401, "error": "account_disabled",
                 "message": "账号不可用，令牌无法使用"},
                status=401,
            )
        # #414 作用域校验：按方法 + 路径前缀算所需 scope，越权 403（带 required_scope）
        if (request.method or "").upper() != "OPTIONS" and not any(
            request.path.startswith(p) for p in SCOPE_FREE_PREFIXES
        ):
            required_scope = pat_required_scope(request.method, request.path)
            if not pat_scopes_allow(getattr(pat, "scopes", ""), required_scope):
                return JsonResponse(
                    {
                        "ok": False,
                        "code": 403,
                        "error": "insufficient_scope",
                        "message": f"访问令牌缺少所需权限：{required_scope}",
                        "required_scope": required_scope,
                        "token_scopes": [
                            s.strip() for s in (pat.scopes or "").split(",") if s.strip()
                        ],
                        "detail": {"required_scope": required_scope},
                    },
                    status=403,
                )
        # 换发短期 JWT（DRF 默认 JWTAuthentication 直接可用）。
        # 必须写入 tv claim：鉴权端是 TokenVersionJWTAuthentication，缺 tv 一律判失效，
        # 否则 PAT 换出来的 token 每个请求都会 401。
        access = AccessToken.for_user(user)
        access["tv"] = user.token_version
        request.META["HTTP_AUTHORIZATION"] = f"Bearer {access}"
        now = timezone.now()
        if not pat.last_used_at or (now - pat.last_used_at).total_seconds() > 60:
            PersonalAccessToken.objects.filter(pk=pat.pk).update(last_used_at=now)
        # #415 用量统计（每次请求按日 +1）
        _record_pat_usage(pat, request.path)
        return None
    except Exception:
        # 降级：不拦截，交给 DRF 正常鉴权（会得到标准 401）
        return None


# ---------------------------------------------------------------------------
# F639 维护模式守卫
# ---------------------------------------------------------------------------
def _is_superuser_request(request) -> bool:
    """会话用户（Django admin）或 JWT 用户是否为 superuser；任何异常都按「非超管」处理"""
    try:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.is_superuser:
            return True
    except Exception:
        logger.exception("B23：静默兜底已登记（core/middleware.py:93 原为 pass）——review 是否应收窄异常类型")
    auth = request.META.get("HTTP_AUTHORIZATION") or ""
    if auth[:7].lower() == "bearer " and not auth[7:].strip().startswith(PAT_PREFIX):
        try:
            from rest_framework_simplejwt.authentication import JWTAuthentication

            result = JWTAuthentication().authenticate(request)
            if result and result[0] is not None and result[0].is_superuser:
                return True
        except Exception:
            return False
    return False


def maintenance_response(request):
    """维护模式开启时，非 superuser 的 /api/ 请求 → 统一 503 结构化提示"""
    try:
        if request.method == "OPTIONS":
            return None
        path = request.path
        if not path.startswith("/api/"):
            return None
        if any(path.startswith(p) for p in MAINTENANCE_PUBLIC_PREFIXES):
            return None
        if not maintenance_enabled():
            return None
        if _is_superuser_request(request):
            return None
        return JsonResponse(
            {
                "ok": False,
                "code": 503,
                "error": "maintenance",
                "message": "系统维护中，请稍后再试（超级管理员不受影响）",
                "detail": {"maintenance": True, "retry_after": 60},
            },
            status=503,
        )
    except Exception:
        return None  # 守卫自身异常必须放行，绝不影响现有接口


class MaintenanceModeMiddleware(MiddlewareMixin):
    """F639 维护模式中间件（默认关闭）"""

    def process_request(self, request):
        return maintenance_response(request)


class OperationLogMiddleware(MaintenanceModeMiddleware):
    """统一操作日志中间件 + 维护模式 / PAT 鉴权（继承其 process_request）"""

    # B7：只预读小体积 JSON / 表单 body（上限 1MB），大文件分片上传不碰
    _PREFETCH_MAX_BYTES = 1_000_000

    def process_request(self, request):
        request._aio_start = time.monotonic()
        denied = pat_authenticate(request)
        if denied is not None:
            return denied
        # #134：鉴权之后把用户名放入 contextvar，后续视图/中间件日志都会带上 user=
        self._bind_request_user(request)
        # B7：提前把 body 读进 _body 缓存。DRF 视图解析 request.data 时会消费
        # 底层流并标记 _read_started，之后在 process_response 里读 request.body
        # 会抛 RawPostDataException，导致操作日志 detail 恒为空；
        # 这里在读流前预读，视图与日志阶段共用同一份缓存
        self._prefetch_body(request)
        self._snapshot_before(request)
        return super().process_request(request)

    @staticmethod
    def _bind_request_user(request):
        """#134：当前登录用户名 → contextvar（供 request_context 日志过滤器读取）"""
        try:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                _request_user_ctx.set(str(getattr(user, "username", "-") or "-")[:64])
        except Exception:
            pass

    def _snapshot_before(self, request):
        """F01：PATCH/PUT 前快照白名单对象，供响应阶段计算字段级 diff"""
        try:
            if request.method not in ("PUT", "PATCH"):
                return
            target = _diff_target(request.path)
            if target is None:
                return
            obj = _load_instance(target[0], target[1])
            if obj is not None:
                request._audit_before = _snapshot(obj, target[2])
        except Exception:
            request._audit_before = None

    def _prefetch_body(self, request):
        try:
            ct = (request.content_type or "").lower()
            if "json" not in ct and "form-urlencoded" not in ct:
                return
            length = int(request.META.get("CONTENT_LENGTH") or 0)
            if length > self._PREFETCH_MAX_BYTES:
                return
            _ = request.body
        except Exception:
            logger.exception("B23：静默兜底已登记（core/middleware.py:169 原为 pass）——review 是否应收窄异常类型")

    def process_response(self, request, response):
        # DRF 认证成功后会把用户回写到 Django request，这里补一次绑定，
        # 让响应阶段（含慢请求告警）的日志能带上 user=
        self._bind_request_user(request)
        self._log_slow_request(request, response)
        try:
            path = request.path
            if request.method == "GET" or request.method in ("HEAD", "OPTIONS"):
                return response
            # #16：账号安全类路径只记元信息，其余跳过路径仍整段静默
            meta_only = any(path.startswith(p) for p in META_ONLY_PREFIXES)
            if not meta_only and any(path.startswith(p) for p in SKIP_PREFIXES):
                return response
            if not request.user or not request.user.is_authenticated:
                return response

            # 只记录轻量信息，不读取 body
            detail = ""
            if meta_only:
                # 绝不解析 body：这里装的是口令 / 验证码 / 重置口令请求
                detail = f"status={getattr(response, 'status_code', '-')}"
            else:
                try:
                    ct = request.content_type or ""
                    if "json" in ct and request.body:
                        body = json.loads(request.body[:4096].decode("utf-8", "ignore"))
                        if isinstance(body, dict):
                            detail = _safe_detail(body)
                except Exception:
                    logger.exception("B23：静默兜底已登记（core/middleware.py:190 原为 pass）——review 是否应收窄异常类型")

            # B7：/api/projects/1/boards/ 原来取 parts[0] 恒为 "api"，
            # 模块分组全是同一值；改为跳过 api 前缀取真实模块名
            parts = [p for p in path.strip("/").split("/") if p]
            if len(parts) >= 2 and parts[0] == "api":
                module = parts[1]
            elif parts:
                module = parts[0]
            else:
                module = "root"
            action_map = {
                "POST": "create",
                "PUT": "update",
                "PATCH": "update",
                "DELETE": "delete",
            }
            if "/upload" in path or "upload" in path:
                action = "upload"
            else:
                action = action_map.get(request.method, "other")

            diff = _build_diff(request, response, path)

            # 延迟导入：本模块在 logging 配置阶段就会被导入（早于 app registry）
            from core.models import OperationLog

            OperationLog.objects.create(
                user=request.user,
                module=module,
                action=action,
                target=path,
                detail=detail,
                diff=diff,
                ip=get_client_ip(request),
            )
        except Exception:
            logger.exception("B23：静默兜底已登记（core/middleware.py:221 原为 pass）——review 是否应收窄异常类型")
        return response

    @staticmethod
    def _log_slow_request(request, response):
        """慢请求观测：超过阈值（默认 1s）落一条 warning，便于定位接口级瓶颈。"""
        try:
            start = getattr(request, "_aio_start", None)
            if start is None:
                return
            elapsed_ms = (time.monotonic() - start) * 1000
            threshold = int(os.environ.get("SLOW_REQUEST_MS", "1000"))
            if elapsed_ms >= threshold:
                logger.warning("慢请求 %s %s %.0fms status=%s rid=%s", request.method, request.path,
                               elapsed_ms, getattr(response, "status_code", "-"), get_request_id())
                if elapsed_ms >= threshold * 5:
                    logger.error("极慢请求 %s %s %.0fms rid=%s", request.method, request.path,
                                 elapsed_ms, get_request_id())
        except Exception:
            pass


class MediaSecurityMiddleware:
    """给 /media/ 直出加安全头，避免上传的 SVG/HTML 在同源下执行脚本。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/media/"):
            response["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
            response["X-Content-Type-Options"] = "nosniff"
            if request.path.lower().endswith((".svg", ".svgz", ".html", ".htm", ".xhtml")):
                response["Content-Disposition"] = "attachment"
        return response
