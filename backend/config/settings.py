"""
全能协作平台 —— Django 配置
开发环境默认使用 SQLite + Channels InMemory 层，开箱即跑；
如需生产，可通过环境变量切换 PostgreSQL 与 Redis。
"""
import json
import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# .env 配置文件（backend/.env，可选依赖 python-dotenv）
# 未安装 python-dotenv 时静默跳过，仅使用系统环境变量，不影响启动；
# 同名变量以系统环境变量优先（load_dotenv 默认不覆盖已存在的变量）。
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 密钥与运行模式
# 修复 1.3 遗留：原默认密钥仅 26 字节（dev-insecure-key-change-me），
# 且生产环境若忘记配置会静默沿用弱密钥 —— JWT 签名同样依赖它。
# 现在：① 开发默认值加长到 76 字节；② 生产（DEBUG=0）未配置环境变量时直接拒绝启动。
# ---------------------------------------------------------------------------
_DEV_SECRET_KEY = (
    "dev-insecure-key-change-me-"
    "please-set-DJANGO_SECRET_KEY-in-production-"
    "9f3a7c1e5b8d2046af17c93e6d05b28a"
)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", _DEV_SECRET_KEY)
# fail-close：一旦配置了生产密钥（说明是正式部署）而忘设 DJANGO_DEBUG，默认按生产处理；
# 纯本地开发（无密钥）仍默认 DEBUG=1，行为不变。
DEBUG = os.environ.get("DJANGO_DEBUG", "0" if os.environ.get("DJANGO_SECRET_KEY") else "1") == "1"

# 代码工坊执行开关：开发默认开，生产默认关。
# 没有容器/gVisor 级隔离时，开启等于允许登录用户读取服务器文件与密钥。
CODE_EXEC_ENABLED = os.environ.get("CODE_EXEC_ENABLED", "1" if DEBUG else "0") == "1"
if not DEBUG and SECRET_KEY == _DEV_SECRET_KEY:
    raise ImproperlyConfigured(
        "生产环境（DJANGO_DEBUG=0）必须通过环境变量 DJANGO_SECRET_KEY 提供独立密钥，"
        "拒绝以内置开发密钥启动。生成方式："
        "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )
# ALLOWED_HOSTS：开发默认放开（*）；生产必须显式配置域名白名单，
# 拒绝静默使用通配符（Host 头攻击面）。确需通配可在生产中显式设 DJANGO_ALLOWED_HOSTS="*"。
_allowed_hosts = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
if _allowed_hosts:
    ALLOWED_HOSTS = _allowed_hosts
elif DEBUG:
    ALLOWED_HOSTS = ["*"]
else:
    raise ImproperlyConfigured(
        "生产环境（DJANGO_DEBUG=0）必须通过环境变量 DJANGO_ALLOWED_HOSTS 配置允许的域名"
        "（逗号分隔，如 example.com,www.example.com）；本地开发无需配置。"
    )

# ---------------------------------------------------------------------------
# 写权限策略
# 数据范围（self/dept/dept_and_sub/all）只决定「能看见什么」，不决定「能改什么」。
# 默认严格按 owner 收口；设为 0 可临时回退到旧行为（读范围即写范围），仅用于紧急回滚。
# ---------------------------------------------------------------------------
WRITE_SCOPE_STRICT = os.environ.get("WRITE_SCOPE_STRICT", "1") == "1"

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "channels",
    # S2-B1：OpenAPI 文档（缺失时 manage.py check 不报错，仅 /api/docs 不可用）
    "drf_spectacular",
    # 业务应用
    "core",
    "accounts",
    "files",
    "notes",
    "projects",
    "im",
    "tools",
    "dashboard",
    "learning",
    "assistant",
    "devtools",
    "minitools",
    "dataintel",
    "officesuite",
    "code",
    "bizhub",
    # 平台能力域（扩展批次）：流程、表单、报表、规则、合同、数据管道、
    # 计费、应用市场、功能开关、可观测性、知识图谱、合规治理
    "workflow",
    "formstudio",
    "reporting",
    "rules",
    "contracts",
    "pipeline",
    "billing",
    "marketplace",
    "flags",
    "observability",
    "knowledgegraph",
    "governance",
    "ws_app",
]

MIDDLEWARE = [
    # #134：最外层生成 request_id（接受上游 X-Request-Id 透传），写入 contextvar
    # 供日志 formatter 使用，并回写响应头便于前后端串联排障
    "core.middleware.RequestIdMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # #94：请求体超限时直接返回统一 413 JSON（不读 body，见 core/exceptions.py）
    "core.exceptions.PayloadTooLargeMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # 最后活跃时间 + 禁用用户拦截中间件
    "accounts.middleware.LastActiveMiddleware",
    # 多租户：解析 request.tenant
    "accounts.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # 统一操作日志中间件（写操作记录到 OperationLog）
    "core.middleware.OperationLogMiddleware",
    # /media 直出时的安全响应头（阻断 SVG/HTML 脚本执行）
    "core.middleware.MediaSecurityMiddleware",
    # #416 幂等键：放最内侧（最靠近视图）。响应阶段 DRF 已把 user 回写到
    # Django request；请求阶段若仍是匿名（JWT 在视图内解析），则从 JWT 里取
    # user_id 作为隔离维度（签名/有效期由 simplejwt 校验），取不到就不缓存。
    # 只处理 POST /api/，无 Idempotency-Key 头时完全放行（行为不变）。
    "core.idempotency.IdempotencyMiddleware",
]

# 生产部署（ClawCloud Run / CF Pages 等）：启用 WhiteNoise 托管静态文件
# （admin / DRF 页面），并信任反向代理传来的 HTTPS 头。本地 DEBUG=1 不受影响。
if not DEBUG:
    MIDDLEWARE.insert(2, "whitenoise.middleware.WhiteNoiseMiddleware")
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # #44 传输安全：仅设代理 SSL 头不够，生产分支补齐重定向 / HSTS /
    # 安全 Cookie / Referrer-Policy。反向代理已做 HTTPS 跳转的部署可用
    # SECURE_SSL_REDIRECT=0 关掉 Django 侧重定向（避免健康检查被 301）。
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "1") == "1"
    SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "0") == "1"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_REFERRER_POLICY = "same-origin"
    # 前端 SPA 走 Bearer 头，Cookie 只服务 admin/会话场景；Samesite=Lax 兼容
    # 站内跳转同时收敛跨站提交面。
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ASGI —— Channels 接管
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # B10：等锁 20s（配合 core/apps.py 的 busy_timeout=20000 / WAL），
        # 开发期并发请求不再轻易 database is locked；仅 sqlite 分支需要
        "timeout": 20,
    }
}
if os.environ.get("POSTGRES_DB"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # 与 DATABASE_URL 分支保持一致：复用连接，避免每请求新建连接
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
    }

# DATABASE_URL（云数据库标准格式，Neon / Render / Supabase 等通用）：
# 优先级高于 POSTGRES_*，URL 中的 ?sslmode=require 会自动带入连接参数。
# 免费云部署（Neon Postgres）走这里；本地开发不设该变量，仍用 SQLite。
_database_url = os.environ.get("DATABASE_URL", "").strip()
if _database_url:
    from urllib.parse import urlparse, parse_qs

    _u = urlparse(_database_url.replace("postgres://", "postgresql://"))
    _opts = {}
    _sslmode = parse_qs(_u.query).get("sslmode", [None])[0]
    if _sslmode:
        _opts["sslmode"] = _sslmode
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _u.path.lstrip("/"),
        "USER": _u.username or "",
        "PASSWORD": _u.password or "",
        "HOST": _u.hostname or "",
        "PORT": str(_u.port or 5432),
        "OPTIONS": _opts,
        "CONN_MAX_AGE": 60,  # 连接复用，省 Neon 免费档的连接数
        "CONN_HEALTH_CHECKS": True,
    }

# Channels Channel Layer：有 Redis 用 Redis，否则用内存层（单进程开发）
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    }

# 口令策略（#6）：相似度 + 最小长度 8 + 常见弱口令库 + 纯数字拦截。
# 只加校验器不改现有 API 契约；validate_password 调用方（注册 / 改密 / 重置）
# 会自动继承更严的策略。
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# 容器部署数据目录（ClawCloud Run 等平台挂载持久卷用）：
# 设置 DATA_DIR 后，SQLite 数据库与上传的 media 都落在持久卷里，容器重启/重部署不丢。
# D4：数据库文件只在**当前引擎是 sqlite** 时改 NAME——同时配了 DATABASE_URL
# （Postgres）时只挪 MEDIA_ROOT，绝不能把 PG 的 NAME 覆盖成 sqlite 路径。
# 变量名兼容：docker-compose 注入的是 DJANGO_DATA_DIR（带前缀更不容易撞名），
# 裸机部署习惯写 DATA_DIR，两者都认，避免"env 填了但卷没挂上"的静默失效。
_DATA_DIR = (os.environ.get("DATA_DIR") or os.environ.get("DJANGO_DATA_DIR") or "").strip()
if _DATA_DIR:
    _dp = Path(_DATA_DIR)
    _dp.mkdir(parents=True, exist_ok=True)
    if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
        DATABASES["default"]["NAME"] = _dp / "db.sqlite3"
    MEDIA_ROOT = _dp / "media"

# DEBUG=0 时 Django 不挂 MEDIA_URL 路由（urls.py 里被 DEBUG 门控）。
# 单容器 / 平台直连场景没有 Nginx 帮忙吐 media，此时把 SERVE_MEDIA 设为 1，
# 由 Django 直接服务 MEDIA_ROOT（性能一般但能跑通上传-访问闭环）。
# 已经用 Nginx/Caddy 反代 /media/ 的部署保持默认 0，别让 Django 抢这活。
SERVE_MEDIA = os.environ.get("SERVE_MEDIA", "0") == "1"
# #46：生产环境（DEBUG=0）即使开了 SERVE_MEDIA，也默认不允许 Django 裸挂
# /media/（无鉴权直出全部附件）。确实没有反代、只能由 Django 直出的部署，
# 必须显式设置 MEDIA_SERVE_INSECURE=1 表示接受该风险；本地 DEBUG=1 不受影响。
MEDIA_SERVE_INSECURE = os.environ.get("MEDIA_SERVE_INSECURE", "0") == "1"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS（开发环境放开；生产通过 CORS_ALLOWED_ORIGINS 白名单收敛）
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_CREDENTIALS = True
# 生产白名单：逗号分隔的前端站点地址（如 https://xxx.pages.dev）
_cors_allowed = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_allowed:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_allowed.split(",") if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
elif not DEBUG:
    # 不拒绝启动（有些部署前后端同域），但必须吼一声：否则前端跨域全挂很难排查
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "生产环境未配置 CORS_ALLOWED_ORIGINS：所有跨域请求将被拒绝。"
        "如前后端不同域，请设置前端站点地址（逗号分隔）。"
    )

# CSRF 可信来源（admin 登录等表单场景用），逗号分隔
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # B12：带 token_version（tv claim）校验的 JWT 认证，改密/踢人后旧 token 立即失效
        "accounts.auth.TokenVersionJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/min",
        "anon": "100/min",
        # #47：重资源接口的 scoped 限流（ScopedRateThrottle）
        "code_run": "30/min",
        "code_judge": "20/min",
        "assistant_chat": "60/min",
    },
    # S2-B1：drf-spectacular OpenAPI schema（/api/schema/ 输出，
    # /api/docs/ 内嵌 Swagger UI）。仅文档用途，不改动任何接口行为。
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# JWT
# #45：refresh 轮换 + 旧 refresh 自动进黑名单；access 缩短到 30 分钟
# （可用 JWT_ACCESS_MINUTES 覆盖）。token_blacklist 已在 INSTALLED_APPS。
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "30"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,
}

# 文件上传限制
FILE_MAX_SIZE_MB = int(os.environ.get("FILE_MAX_SIZE_MB", "1024"))
FILE_CHUNK_SIZE_MB = int(os.environ.get("FILE_CHUNK_SIZE_MB", "5"))

# #94 请求体上限：显式声明（Django 默认仅 2.5MB / 1000 字段，富文本与批量 JSON 易误伤）。
# 注意：该值只管「非文件字段与 JSON 正文」，分片上传的文件数据走 FILE_MAX_SIZE_MB。
# 超限请求由 MIDDLEWARE 里的 core.exceptions.PayloadTooLargeMiddleware 统一映射为
# {"code":413,"message":...} 的 JSON，而不是 Django 默认的 400/HTML 或 500。
DATA_UPLOAD_MAX_MEMORY_SIZE = int(
    os.environ.get("DATA_UPLOAD_MAX_MEMORY_SIZE", str(8 * 1024 * 1024))
)
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(os.environ.get("DATA_UPLOAD_MAX_NUMBER_FIELDS", "1000"))

# 分页大小上限
PAGE_SIZE_MAX = 100

# S2-B1：drf-spectacular 配置
SPECTACULAR_SETTINGS = {
    "TITLE": "全能协作平台 API",
    "DESCRIPTION": "看板 / 网盘 / 笔记 / IM / 学习中心 / 代码工坊等模块的 REST 接口文档",
    "VERSION": "6.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # 项目大量裸 APIView（手写 Response），serializer 推断不全会 warning——
    # 这些是文档完整度提示，不是错误；需要逐个补 @extend_schema 时再处理
    "DISABLE_DRF_WARNINGS": False,
}

# 回收站保留天数（到期可由清理任务清除）
TRASH_KEEP_DAYS = int(os.environ.get("TRASH_KEEP_DAYS", "30"))
# #68 数据保留策略：`python manage.py purge_retention` 按以下天数分批清理
# （<=0 表示该类不清理）。OPLOG 是审计追溯底线，默认 180 天；
# Notification 只清「已读」的，未读通知永不自动删除。
OPLOG_KEEP_DAYS = int(os.environ.get("OPLOG_KEEP_DAYS", "180"))
SHARE_VISIT_KEEP_DAYS = int(os.environ.get("SHARE_VISIT_KEEP_DAYS", "90"))
NOTIFICATION_KEEP_DAYS = int(os.environ.get("NOTIFICATION_KEEP_DAYS", "90"))
REFRESH_TOKEN_KEEP_DAYS = int(os.environ.get("REFRESH_TOKEN_KEEP_DAYS", "7"))
# #17 搜索词保留期（默认 30 天；搜索历史接口会按此做个人到期清理）
SEARCH_LOG_KEEP_DAYS = int(os.environ.get("SEARCH_LOG_KEEP_DAYS", "30"))
# 平台版本（与 README / FEATURES 标题 / docs/12 对齐：v8 = 迷你工具箱扩到 26 家族 374 工具）
PLATFORM_VERSION = "8.0.0"

# ---------------------------------------------------------------------------
# 多租户 / 行级数据权限
# ---------------------------------------------------------------------------
# 开启后，数据范围（Role.data_scope）与租户会被强制收敛；
# 关闭时仅「角色 data_scope」生效，租户字段保留但不参与隔离。
TENANCY_ENABLED = os.environ.get("TENANCY_ENABLED", "0") == "1"

# ---------------------------------------------------------------------------
# 全文搜索（core.search）
# ---------------------------------------------------------------------------
SEARCH_ENABLED = os.environ.get("SEARCH_ENABLED", "1") == "1"
# 单文档建立索引时，正文最多截取的字符数
SEARCH_MAX_TEXT_CHARS = int(os.environ.get("SEARCH_MAX_TEXT_CHARS", "200000"))

# ---------------------------------------------------------------------------
# AI 助手（assistant）
# 兼容 OpenAI Chat Completions 协议的任意服务（OpenAI / DeepSeek / 通义 / 本地 vLLM…）
# 未配置 LLM_API_KEY 时自动降级为「本地抽取式」实现，功能仍可用。
# ---------------------------------------------------------------------------
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "60"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1200"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.3"))
# 额外请求体（JSON 字符串），会合并进 /chat/completions 的 payload ——
# 用于厂商专属开关，例如 NVIDIA NIM 关闭思考：LLM_EXTRA_BODY={"chat_template_kwargs":{"thinking":false}}
# 解析失败时忽略（保持空 dict），不影响启动。
LLM_EXTRA_BODY = {}
_extra_body = os.environ.get("LLM_EXTRA_BODY", "").strip()
if _extra_body:
    try:
        LLM_EXTRA_BODY = json.loads(_extra_body)
    except ValueError:
        pass

# ---------------------------------------------------------------------------
# Office 文档转 PDF（LibreOffice）
# 留空则自动探测 soffice；探测不到时相关接口返回明确的安装指引而不是报错。
# ---------------------------------------------------------------------------
SOFFICE_PATH = os.environ.get("SOFFICE_PATH", "")
OFFICE_CONVERT_TIMEOUT = int(os.environ.get("OFFICE_CONVERT_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# 缓存（S2-B1）
# 默认 LocMemCache：单进程部署（当前 ClawCloud 单实例）零依赖可用；
# 多实例部署时把 backend 换成 django.core.cache.backends.redis.RedisCache
# 并配 CONNECTION（与 Channels 共用同一 Redis），保证各实例间缓存一致。
# 目前缓存对象：公开站点设置（public site settings，低频变更）。
# ---------------------------------------------------------------------------
CACHE_URL = os.environ.get("CACHE_URL") or os.environ.get("REDIS_URL", "")
if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
            "TIMEOUT": 300,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "allinone-default",
            "TIMEOUT": 300,
        }
    }

# ---------------------------------------------------------------------------
# 日志（#199 / #134）
# 控制台结构化输出 + request_id / 操作注入 + 文件轮转（10MB × 3 份）。
# request_id 由 core.middleware.RequestIdMiddleware 写入 contextvar，再由
# core.middleware.RequestContextFilter 注入每条日志记录（含 django/core 的既有 logger）。
# 容器里日志已由 docker logging driver 收集时，可用 DJANGO_LOG_TO_FILE=0 关掉文件句柄；
# 落盘目录优先 DATA_DIR/logs（与数据库同一持久卷），否则 backend/logs。
# 慢请求阈值由 SLOW_REQUEST_MS 控制（见 core/middleware.py）。
# 配置 SENTRY_DSN 且安装了 sentry-sdk 时自动上报异常，未安装则静默跳过。
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "[{asctime}] {levelname} {name} [rid={request_id} user={request_user}]: {message}"
LOG_FORMAT_FILE = (
    "[{asctime}] {levelname} {name} [rid={request_id} user={request_user}] "
    "{module}:{lineno}: {message}"
)
LOG_MAX_BYTES = int(os.environ.get("DJANGO_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.environ.get("DJANGO_LOG_BACKUP_COUNT", "3"))
LOG_TO_FILE = os.environ.get("DJANGO_LOG_TO_FILE", "1") == "1"
_LOG_DIR_RAW = (os.environ.get("DJANGO_LOG_DIR") or "").strip()
if _LOG_DIR_RAW:
    LOG_DIR = Path(_LOG_DIR_RAW)
elif _DATA_DIR:
    LOG_DIR = Path(_DATA_DIR) / "logs"
else:
    LOG_DIR = BASE_DIR / "logs"
if LOG_TO_FILE:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 只读文件系统（未挂卷的容器）降级为仅控制台，绝不让日志配置拖垮启动
        LOG_TO_FILE = False
LOG_FILE = LOG_DIR / "app.log"

_console_handler = {
    "class": "logging.StreamHandler",
    "formatter": "verbose",
    "filters": ["request_context"],
}
_file_handler = {
    "class": "logging.handlers.RotatingFileHandler",
    "filename": str(LOG_FILE),
    "maxBytes": LOG_MAX_BYTES,
    "backupCount": LOG_BACKUP_COUNT,
    "encoding": "utf-8",
    # delay=True：首次写日志时才打开文件，避免启动期只读目录直接报错
    "delay": True,
    "formatter": "file",
    "filters": ["request_context"],
}
_handler_names = ["console"]
_log_handlers = {"console": _console_handler}
if LOG_TO_FILE:
    _handler_names.append("file")
    _log_handlers["file"] = _file_handler

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {"()": "core.middleware.RequestContextFilter"},
    },
    "formatters": {
        "verbose": {"format": LOG_FORMAT, "style": "{"},
        "file": {"format": LOG_FORMAT_FILE, "style": "{"},
    },
    "handlers": _log_handlers,
    "root": {"handlers": _handler_names, "level": LOG_LEVEL},
    "loggers": {
        "django.request": {"handlers": _handler_names, "level": "WARNING", "propagate": False},
        "django.db.backends": {"handlers": _handler_names, "level": "WARNING", "propagate": False},
        "core": {"handlers": _handler_names, "level": LOG_LEVEL, "propagate": False},
    },
}

_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=_sentry_dsn,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
            release=os.environ.get("SENTRY_RELEASE") or None,
        )
    except ImportError:
        pass
