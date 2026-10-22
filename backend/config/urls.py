"""全能协作平台 —— 根路由"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from rest_framework_simplejwt.views import TokenVerifyView

from accounts.views import RefreshView  # noqa: E402 —— B12：带 tv claim 校验的刷新视图


def api_root(request):
    """根路径说明。

    后端只提供 REST API 与 WebSocket；页面请在前端端口（Vite 默认 5173）打开，
    这里返回说明而不是 404，避免「打开 8000 端口看到 Not Found」的困惑。
    """
    return JsonResponse({
        "name": "全能协作平台 · 后端服务",
        "version": getattr(settings, "PLATFORM_VERSION", ""),
        "api_prefix": "/api/",
        "websocket": "/ws/notify/",
        "frontend_dev": "http://127.0.0.1:5173",
        "docs": ["/api/core/health/", "/api/core/settings/public/"],
        "hint": "这是后端端口，页面请在前端端口打开；接口均以 /api/ 开头。",
    })


def favicon(request):
    """避免浏览器请求 /favicon.ico 时打出 404 噪声"""
    return HttpResponse(status=204)


urlpatterns = [
    path("", api_root, name="api-root"),
    path("favicon.ico", favicon),
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/files/", include("files.urls")),
    path("api/notes/", include("notes.urls")),
    path("api/projects/", include("projects.urls")),
    path("api/im/", include("im.urls")),
    path("api/tools/", include("tools.urls")),
    path("api/dashboard/", include("dashboard.urls")),
    path("api/core/", include("core.urls")),
    path("api/learning/", include("learning.urls")),
    path("api/assistant/", include("assistant.urls")),
    path("api/devtools/", include("devtools.urls")),
    path("api/minitools/", include("minitools.urls")),
    path("api/dataintel/", include("dataintel.urls")),
    path("api/officesuite/", include("officesuite.urls")),
    path("api/code/", include("code.urls")),
    path("api/auth/refresh/", RefreshView.as_view(), name="token_refresh"),
    path("api/auth/verify/", TokenVerifyView.as_view(), name="token_verify"),
]

# 公开共享链接（无需登录）
from files.urls import share_urlpatterns

urlpatterns += share_urlpatterns

# 看板只读分享（无需登录）
from projects.urls import board_share_urlpatterns

urlpatterns += board_share_urlpatterns

# 代码工坊公开分享（无需登录，只读）
from code.urls import public_urlpatterns as code_public_urlpatterns

urlpatterns += code_public_urlpatterns

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
