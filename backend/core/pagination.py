"""统一分页器"""
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
