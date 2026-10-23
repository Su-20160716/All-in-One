"""统一分页器（S2-B1 约定）。

项目内部分页就两个选择，新代码按场景挑，**不要再造第三种**：

1. ``StandardPagination`` —— 标准 DRF 分页（``page`` / ``page_size`` 参数，
   响应 ``{count, next, previous, results}``）。用于**新建**的、数据量
   可能很大的列表接口。
2. ``OptionalPageNumberPagination`` —— 可选分页：不带 ``page`` 时返回
   完整列表 + 原响应结构（list/total），带 ``page`` 时按标准分页。
   用于**兼容存量响应结构**的接口（老客户端不传 page，逐字节一致）。

存量约定（勿改，改了炸前端）：
- ``dataintel`` 套件用手写 ``limit``/``offset`` 参数 + ``{list,total,
  offset,limit}`` 响应结构，是 v5 既有契约，保持原样。
- ``settings.REST_FRAMEWORK.DEFAULT_PAGINATION_CLASS`` 为
  ``StandardPagination``， generic ListAPIView 默认走标准分页。

新增分页相关需求先读本段；要动存量分页行为，先确认前端消费方。
"""
from rest_framework.pagination import PageNumberPagination

from django.conf import settings


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = settings.PAGE_SIZE_MAX


class OptionalPageNumberPagination(PageNumberPagination):
    """B11：可选分页。

    不带 `page` 参数时与「不分页」完全一致——返回完整列表 + 原响应结构；
    带 `page`（或 `page_size`）时按标准分页返回。

    用于替换各处 `Serializer(qs, many=True)` + `qs.count()` 的手写组合：
    - 老客户端不传 page → 响应与以前逐字节一致（list/total 字段不变）
    - 数据量大的列表可按 page 分批，避免一次性序列化上万条

    注意：DRF 的 paginate_queryset 返回 None 表示「本页不分页」，
    此时视图直接序列化完整 queryset 即可，配合 `get_paginated_response`
    不会走到（返回 None 时 DRF 不会调 get_paginated_response）。
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = settings.PAGE_SIZE_MAX

    def paginate_queryset(self, queryset, request, view=None):
        # 没有显式分页意图（无 page 参数）→ 返回 None，视图走全量分支
        if "page" not in request.query_params:
            return None
        return super().paginate_queryset(queryset, request, view)
