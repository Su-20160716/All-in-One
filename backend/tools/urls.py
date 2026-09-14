"""tools 路由"""
from django.urls import path

from tools.views import TOOL_REGISTRY, ToolCatalogView, ToolRunView

urlpatterns = [
    path("catalog/", ToolCatalogView.as_view(), name="tool-catalog"),
    path("run/", ToolRunView.as_view(), name="tool-run"),
]

# 为每个工具生成 /api/tools/<key>/ 的直达入口（兼容旧前端）
for _key in TOOL_REGISTRY:
    urlpatterns.append(path(f"{_key}/", ToolRunView.as_view(), kwargs={"tool": _key}))
