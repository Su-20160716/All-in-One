"""统一操作日志中间件：记录写请求（非 GET）到 OperationLog"""
import json

from django.utils.deprecation import MiddlewareMixin

from core.models import OperationLog
from core.utils import get_client_ip

# 跳过路径（避免噪音）
SKIP_PREFIXES = ("/admin", "/static", "/media", "/api/auth/token", "/api/auth/refresh", "/api/auth/verify")


class OperationLogMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        try:
            path = request.path
            if request.method == "GET" or request.method in ("HEAD", "OPTIONS"):
                return response
            if any(path.startswith(p) for p in SKIP_PREFIXES):
                return response
            if not request.user or not request.user.is_authenticated:
                return response

            # 只记录轻量信息，不读取 body
            detail = ""
            try:
                ct = request.content_type or ""
                if "json" in ct and request.body:
                    body = json.loads(request.body[:4096].decode("utf-8", "ignore"))
                    keys = list(body.keys())[:8]
                    detail = "{" + ", ".join(f"{k}: {str(body[k])[:40]}" for k in keys) + "}"
            except Exception:
                pass

            module = path.strip("/").split("/")[0] if path.strip("/") else "root"
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

            OperationLog.objects.create(
                user=request.user,
                module=module,
                action=action,
                target=path,
                detail=detail,
                ip=get_client_ip(request),
            )
        except Exception:
            pass
        return response
