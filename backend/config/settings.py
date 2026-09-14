"""
全能协作平台 —— Django 配置
开发环境默认使用 SQLite + Channels InMemory 层，开箱即跑；
如需生产，可通过环境变量切换 PostgreSQL 与 Redis。
"""
import json
import os
from datetime import timedelta
from pathlib import Path

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

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

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
    "ws_app",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
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
]

# 生产部署（Render 等）：启用 WhiteNoise 托管静态文件（admin / DRF 页面），
# 并信任反向代理传来的 HTTPS 头。本地 DEBUG=1 不受影响。
if not DEBUG:
    MIDDLEWARE.insert(2, "whitenoise.middleware.WhiteNoiseMiddleware")
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

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

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
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
_DATA_DIR = os.environ.get("DATA_DIR", "").strip()
if _DATA_DIR:
    _dp = Path(_DATA_DIR)
    _dp.mkdir(parents=True, exist_ok=True)
    DATABASES["default"]["NAME"] = _dp / "db.sqlite3"
    MEDIA_ROOT = _dp / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS（开发环境放开；生产通过 CORS_ALLOWED_ORIGINS 白名单收敛）
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOW_CREDENTIALS = True
# 生产白名单：逗号分隔的前端站点地址（如 https://xxx.pages.dev）
_cors_allowed = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_allowed:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_allowed.split(",") if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False

# CSRF 可信来源（admin 登录等表单场景用），逗号分隔
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
}

# JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=int(os.environ.get("JWT_ACCESS_HOURS", "12"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,
}

# 文件上传限制
FILE_MAX_SIZE_MB = int(os.environ.get("FILE_MAX_SIZE_MB", "1024"))
FILE_CHUNK_SIZE_MB = int(os.environ.get("FILE_CHUNK_SIZE_MB", "5"))

# 分页大小上限
PAGE_SIZE_MAX = 100

# 回收站保留天数（到期可由清理任务清除）
TRASH_KEEP_DAYS = int(os.environ.get("TRASH_KEEP_DAYS", "30"))
# 平台版本
PLATFORM_VERSION = "4.0.0"

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
