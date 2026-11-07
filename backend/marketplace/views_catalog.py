# -*- coding: utf-8 -*-
"""应用市场 · 目录接口。

前端工作台启动时先拉目录，拿到枚举、分类树、平台版本与端点清单，
避免把状态机/类型硬编码在页面里（后端一改前端就漂移）。
"""
from django.db.models import Count, Sum

from devtools.common import endpoint, ok

from . import services
from .models import (
    COLLECTION_STATUS_CHOICES,
    EVENT_STATUS_CHOICES,
    INSTALL_STATUS_CHOICES,
    LICENSE_STATUS_CHOICES,
    LICENSE_TYPE_CHOICES,
    LISTING_STATUS_CHOICES,
    LISTING_TYPE_CHOICES,
    PRICING_MODE_CHOICES,
    PUBLISHER_STATUS_CHOICES,
    PURCHASE_STATUS_CHOICES,
    REPORT_REASON_CHOICES,
    REPORT_STATUS_CHOICES,
    REVIEW_STATUS_CHOICES,
    VERSION_STATUS_CHOICES,
    WEBHOOK_STATUS_CHOICES,
    Collection,
    Install,
    License,
    Listing,
    ListingReport,
    Publisher,
    Purchase,
    Review,
)
from .serializers import category_tree, iso

# 能力域划分与 urls.py 的分组保持一致，前端据此渲染导航。
CAPABILITY_DOMAINS = [
    {"key": "catalog", "name": "市场目录", "description": "元信息、分类与平台版本",
     "endpoint_prefixes": ["catalog", "categories"]},
    {"key": "publisher", "name": "发布者", "description": "认证、暂停、结算与收入概览",
     "endpoint_prefixes": ["publishers"]},
    {"key": "listing", "name": "应用管理", "description": "创建、审核、上下架、克隆与推荐位",
     "endpoint_prefixes": ["listings"]},
    {"key": "version", "name": "版本管理", "description": "发版、下架、对比与升级检查",
     "endpoint_prefixes": ["versions"]},
    {"key": "install", "name": "安装管理", "description": "安装解析、卸载、启停与配置",
     "endpoint_prefixes": ["installs"]},
    {"key": "review", "name": "评价互动", "description": "评价、隐藏、有用票与回复",
     "endpoint_prefixes": ["reviews"]},
    {"key": "commerce", "name": "定价与许可", "description": "定价、购买、退款与许可证激活",
     "endpoint_prefixes": ["pricing", "purchases", "licenses"]},
    {"key": "platform", "name": "开放能力", "description": "Webhook、事件、合集、举报、截图与兼容标签",
     "endpoint_prefixes": ["webhooks", "events", "collections", "reports",
                            "screenshots", "compatibility"]},
    {"key": "stats", "name": "市场统计", "description": "概览、分类、发布者、趋势、评分与收入",
     "endpoint_prefixes": ["stats"]},
]

# Webhook 可订阅事件清单（与业务写入点保持一致）。
EVENT_TYPES = [
    {"value": "listing.published", "label": "应用上架"},
    {"value": "listing.delisted", "label": "应用下架"},
    {"value": "listing.suspended", "label": "应用暂停"},
    {"value": "version.published", "label": "版本发布"},
    {"value": "install.created", "label": "新安装"},
    {"value": "install.uninstalled", "label": "卸载"},
    {"value": "install.upgraded", "label": "升级"},
    {"value": "review.published", "label": "评价发布"},
    {"value": "review.hidden", "label": "评价隐藏"},
    {"value": "purchase.paid", "label": "支付成功"},
    {"value": "purchase.refunded", "label": "订单退款"},
    {"value": "report.created", "label": "收到举报"},
    {"value": "license.activated", "label": "许可证激活"},
]

SORT_OPTIONS = [
    {"value": "relevance", "label": "相关度"},
    {"value": "rating", "label": "评分"},
    {"value": "installs", "label": "安装量"},
    {"value": "newest", "label": "最新上架"},
    {"value": "price", "label": "价格"},
    {"value": "featured", "label": "推荐位"},
]

COMPAT_TAGS = [
    {"value": "verified", "label": "已验证"},
    {"value": "beta", "label": "测试可用"},
    {"value": "deprecated", "label": "已弃用"},
    {"value": "broken", "label": "不可用"},
]


def _choices(pairs):
    """把 Django choices 转成前端友好的 [{value,label}]。"""
    return [{"value": value, "label": label} for value, label in pairs]


def _counts():
    """目录里的规模统计（数量级小，直接 count 可接受）。"""
    listings = Listing.objects.all()
    by_status = {row["status"]: row["c"] for row in
                 listings.values("status").annotate(c=Count("id"))}
    return {
        "publishers": Publisher.objects.count(),
        "listings": listings.count(),
        "published_listings": by_status.get("published", 0),
        "listings_by_status": by_status,
        "installs": Install.objects.filter(status__in=("installed", "disabled")).count(),
        "reviews": Review.objects.filter(status="published").count(),
        "collections": Collection.objects.filter(status="published").count(),
        "licenses": License.objects.filter(status="active").count(),
        "orders": Purchase.objects.filter(payment_status="paid").count(),
        "open_reports": ListingReport.objects.filter(
            status__in=("pending", "reviewing")).count(),
        "total_installs": int(
            listings.aggregate(total=Sum("install_count"))["total"] or 0
        ),
    }


@endpoint(("GET",))
def catalog(request):
    """应用市场目录：平台版本、枚举、分类树、事件清单、排序选项与规模统计。"""
    return ok({
        "name": "应用市场",
        "version": "1.0",
        "platform_version": services.platform_version_value(),
        "generated_at": iso(services.timezone.now()),
        "domains": CAPABILITY_DOMAINS,
        "listing_types": _choices(LISTING_TYPE_CHOICES),
        "listing_statuses": _choices(LISTING_STATUS_CHOICES),
        "pricing_modes": _choices(PRICING_MODE_CHOICES),
        "publisher_statuses": _choices(PUBLISHER_STATUS_CHOICES),
        "version_statuses": _choices(VERSION_STATUS_CHOICES),
        "install_statuses": _choices(INSTALL_STATUS_CHOICES),
        "review_statuses": _choices(REVIEW_STATUS_CHOICES),
        "purchase_statuses": _choices(PURCHASE_STATUS_CHOICES),
        "license_types": _choices(LICENSE_TYPE_CHOICES),
        "license_statuses": _choices(LICENSE_STATUS_CHOICES),
        "webhook_statuses": _choices(WEBHOOK_STATUS_CHOICES),
        "event_statuses": _choices(EVENT_STATUS_CHOICES),
        "collection_statuses": _choices(COLLECTION_STATUS_CHOICES),
        "report_statuses": _choices(REPORT_STATUS_CHOICES),
        "report_reasons": _choices(REPORT_REASON_CHOICES),
        "event_types": EVENT_TYPES,
        "sort_options": SORT_OPTIONS,
        "compatibility_tags": COMPAT_TAGS,
        "category_tree": category_tree(),
        "pagination": {
            "page_size_default": 20,
            "page_size_max": 200,
            "response_shape": ["items", "count", "page", "page_size"],
        },
        "permissions": {
            "publish_requires": "发布者需认证（verified）",
            "review": "审核/暂停/认证仅 is_staff",
            "write": "应用写权限 = 维护者 / 发布者 owner / 管理员",
        },
        "counts": _counts(),
    })
