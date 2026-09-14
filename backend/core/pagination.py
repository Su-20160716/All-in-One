"""统一分页器"""
from rest_framework.pagination import PageNumberPagination

from django.conf import settings


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = settings.PAGE_SIZE_MAX
