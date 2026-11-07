# -*- coding: utf-8 -*-
"""应用市场 · 序列化助手。

视图只依赖这里的 to_* 函数，保证同一实体在不同接口里的字段形态一致：
前端一份类型定义即可覆盖列表 / 详情 / 下拉，不必按接口做适配。

约定：
- 外键统一输出 ``*_id`` + 少量展示字段（名称/编码），避免详情页二次请求；
- 金额输出 float（数据库 Decimal 已 quantize 到分，转 float 不丢精度到分位）；
- 时间统一 ISO8601 字符串，空值为 None（前端不用判空字符串）；
- 敏感字段（许可证哈希、Webhook 密钥）绝不出现在响应里。
"""
from decimal import Decimal

from django.db.models import Sum

from . import services
from .models import (
    Category,
    Collection,
    CollectionItem,
    CompatibilityTag,
    Install,
    License,
    Listing,
    ListingReport,
    ListingVersion,
    MarketplaceEvent,
    Pricing,
    Publisher,
    Purchase,
    Review,
    ReviewReply,
    Screenshot,
    WebhookDelivery,
    WebhookSubscription,
)


def iso(value):
    """datetime/date → ISO 字符串；None 保持 None。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def decimal_out(value):
    """Decimal → float（None → 0.0），金额与评分统一走这里。"""
    if value is None:
        return 0.0
    return float(Decimal(str(value)))


def user_brief(user):
    """用户简卡：id/用户名/昵称。"""
    if user is None:
        return {"id": None, "username": "", "nickname": ""}
    return {
        "id": user.pk,
        "username": getattr(user, "username", "") or "",
        "nickname": getattr(user, "nickname", "") or getattr(user, "username", "") or "",
    }


def publisher_dict(publisher, with_stats=False):
    """发布者详情；with_stats=True 时附带应用数/安装量（概览接口用）。"""
    data = {
        "id": publisher.id,
        "name": publisher.name,
        "slug": publisher.slug,
        "summary": publisher.summary,
        "website": publisher.website,
        "contact_email": publisher.contact_email,
        "status": publisher.status,
        "revenue_share": decimal_out(publisher.revenue_share),
        "settlement_info": publisher.settlement_info or {},
        "verified_at": iso(publisher.verified_at),
        "suspended_reason": publisher.suspended_reason,
        "owner_id": publisher.owner_id,
        "owner": user_brief(publisher.owner),
        "remark": publisher.remark,
        "created_at": iso(publisher.created_at),
        "updated_at": iso(publisher.updated_at),
    }
    if with_stats:
        listings = publisher.mp_publisher_listings.all()
        published = listings.filter(status="published")
        data["stats"] = {
            "listings": listings.count(),
            "published_listings": published.count(),
            "installs": int(published.aggregate(total=Sum("install_count"))["total"] or 0),
        }
    return data


def category_dict(category, with_counts=False):
    """分类详情。"""
    data = {
        "id": category.id,
        "code": category.code,
        "name": category.name,
        "parent_id": category.parent_id,
        "parent_name": category.parent.name if category.parent_id and category.parent else "",
        "order": category.order,
        "icon": category.icon,
        "active": category.active,
        "description": category.description,
        "owner_id": category.owner_id,
        "created_at": iso(category.created_at),
        "updated_at": iso(category.updated_at),
    }
    if with_counts:
        data["listing_count"] = category.mp_category_listings.filter(status="published").count()
    return data


def category_tree():
    """分类树：一次取全表在内存组装，避免递归查询。"""
    rows = list(Category.objects.select_related("parent").order_by("order", "id"))
    index = {}
    for row in rows:
        index[row.id] = {
            **category_dict(row),
            "children": [],
            "listing_count": row.mp_category_listings.filter(status="published").count(),
        }
    roots = []
    for row in rows:
        node = index[row.id]
        if row.parent_id and row.parent_id in index:
            index[row.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


def version_brief(version):
    """版本简卡（列表/最新版本引用）。"""
    if version is None:
        return None
    return {
        "id": version.id,
        "version": version.version,
        "status": version.status,
        "min_platform_version": version.min_platform_version,
        "breaking": version.breaking,
        "published_at": iso(version.published_at),
    }


def version_dict(version, with_listing=True):
    """版本详情：含 manifest 与依赖声明。"""
    data = {
        "id": version.id,
        "listing_id": version.listing_id,
        "version": version.version,
        "changelog": version.changelog,
        "min_platform_version": version.min_platform_version,
        "manifest": version.manifest or {},
        "requires": (version.manifest or {}).get("requires") or [],
        "package_size": version.package_size,
        "checksum": version.checksum,
        "status": version.status,
        "breaking": version.breaking,
        "download_count": version.download_count,
        "published_at": iso(version.published_at),
        "owner_id": version.owner_id,
        "created_at": iso(version.created_at),
        "updated_at": iso(version.updated_at),
    }
    if with_listing:
        data["listing"] = {
            "id": version.listing_id,
            "code": version.listing.code,
            "name": version.listing.name,
            "status": version.listing.status,
        }
    return data


def listing_brief(listing, score=None):
    """应用卡片：列表/搜索/合集条目共用。"""
    latest = listing.latest_version
    data = {
        "id": listing.id,
        "code": listing.code,
        "name": listing.name,
        "summary": listing.summary,
        "icon": listing.icon,
        "type": listing.type,
        "status": listing.status,
        "pricing_mode": listing.pricing_mode,
        "rating": decimal_out(listing.rating),
        "rating_count": listing.rating_count,
        "install_count": listing.install_count,
        "featured": listing.featured,
        "tags": listing.tags or [],
        "publisher": {
            "id": listing.publisher_id,
            "name": listing.publisher.name,
            "slug": listing.publisher.slug,
            "status": listing.publisher.status,
        },
        "category": (
            {"id": listing.category_id, "code": listing.category.code,
             "name": listing.category.name}
            if listing.category_id and listing.category else None
        ),
        "latest_version": version_brief(latest),
        "pricing": services.pricing_payload(listing),
        "published_at": iso(listing.published_at),
    }
    if score is not None:
        data["score"] = score
    return data


def listing_dict(listing):
    """应用详情：包含审核记录、截图、兼容标签与版本列表。"""
    data = listing_brief(listing)
    data.update({
        "description": listing.description,
        "featured_rank": listing.featured_rank,
        "review_note": listing.review_note,
        "audit": listing.audit or {},
        "submitted_at": iso(listing.submitted_at),
        "delisted_at": iso(listing.delisted_at),
        "owner_id": listing.owner_id,
        "owner": user_brief(listing.owner),
        "remark": listing.remark,
        "created_at": iso(listing.created_at),
        "updated_at": iso(listing.updated_at),
        "versions": [
            version_brief(v) for v in
            listing.mp_versions.filter(status="published").order_by("-published_at", "-id")[:20]
        ],
        "screenshots": [screenshot_dict(s) for s in listing.mp_screenshots.all()[:20]],
        "compatibility": [compat_dict(c) for c in listing.mp_compat_tags.all()[:30]],
        "open_reports": listing.mp_reports.filter(status__in=("pending", "reviewing")).count(),
    })
    return data


def install_dict(install):
    """安装记录（我的应用列表/详情）。"""
    return {
        "id": install.id,
        "status": install.status,
        "config": install.config or {},
        "auto_update": install.auto_update,
        "installed_at": iso(install.installed_at),
        "uninstalled_at": iso(install.uninstalled_at),
        "last_upgraded_at": iso(install.last_upgraded_at),
        "version": version_brief(install.version),
        "listing": listing_brief(install.listing),
        "owner_id": install.owner_id,
        "created_at": iso(install.created_at),
        "updated_at": iso(install.updated_at),
    }


def reply_dict(reply):
    """评价回复。"""
    return {
        "id": reply.id,
        "review_id": reply.review_id,
        "content": reply.content,
        "owner_id": reply.owner_id,
        "owner": user_brief(reply.owner),
        "created_at": iso(reply.created_at),
        "updated_at": iso(reply.updated_at),
    }


def review_dict(review, with_replies=False):
    """评价详情；with_replies=True 时附回复列表。"""
    data = {
        "id": review.id,
        "listing_id": review.listing_id,
        "rating": review.rating,
        "title": review.title,
        "content": review.content,
        "status": review.status,
        "reply_count": review.reply_count,
        "helpful_count": review.helpful_count,
        "verified_purchase": review.verified_purchase,
        "hidden_reason": review.hidden_reason,
        "owner_id": review.owner_id,
        "owner": user_brief(review.owner),
        "created_at": iso(review.created_at),
        "updated_at": iso(review.updated_at),
    }
    if with_replies:
        data["replies"] = [reply_dict(r) for r in review.mp_replies.all()[:100]]
    return data


def pricing_dict(pricing):
    """定价详情。"""
    return {
        "id": pricing.id,
        "listing_id": pricing.listing_id,
        "mode": pricing.mode,
        "price": decimal_out(pricing.price),
        "currency": pricing.currency,
        "trial_days": pricing.trial_days,
        "period": pricing.period,
        "active": pricing.active,
        "owner_id": pricing.owner_id,
        "created_at": iso(pricing.created_at),
        "updated_at": iso(pricing.updated_at),
    }


def purchase_dict(purchase, with_breakdown=False):
    """购买订单；with_breakdown=True 时附分成拆分（发布者/管理员视角）。"""
    data = {
        "id": purchase.id,
        "order_no": purchase.order_no,
        "status": purchase.payment_status,
        "price": decimal_out(purchase.price),
        "currency": purchase.currency,
        "channel": purchase.channel,
        "purchased_at": iso(purchase.purchased_at),
        "refunded_at": iso(purchase.refunded_at),
        "refund_amount": decimal_out(purchase.refund_amount),
        "version_id": purchase.version_id,
        "listing": listing_brief(purchase.listing),
        "owner_id": purchase.owner_id,
        "owner": user_brief(purchase.owner),
        "created_at": iso(purchase.created_at),
    }
    license_obj = getattr(purchase, "mp_license", None)
    data["license_id"] = license_obj.id if license_obj is not None else None
    if with_breakdown:
        data["breakdown"] = services.purchase_breakdown(purchase)
    return data


def license_dict(license_obj, include_devices=True):
    """许可证（永不输出密钥哈希）。"""
    snapshot = services.license_snapshot(license_obj)
    data = {
        "id": license_obj.id,
        "listing_id": license_obj.listing_id,
        "listing_code": license_obj.listing.code,
        "purchase_id": license_obj.purchase_id,
        "key_hint": license_obj.key_hint,
        "type": license_obj.type,
        "status": snapshot["status"],
        "effective_status": services.license_status_of(license_obj),
        "expired": snapshot["expired"],
        "expires_at": snapshot["expires_at"],
        "remaining_days": snapshot["remaining_days"],
        "max_activations": license_obj.max_activations,
        "activation_count": snapshot["activation_count"],
        "last_verified_at": snapshot["last_verified_at"],
        "revoked_reason": license_obj.revoked_reason,
        "owner_id": license_obj.owner_id,
        "created_at": iso(license_obj.created_at),
    }
    if include_devices:
        data["devices"] = snapshot["devices"]
    return data


def webhook_dict(subscription):
    """Webhook 订阅（secret 只输出是否配置，不回显明文）。"""
    return {
        "id": subscription.id,
        "publisher_id": subscription.publisher_id,
        "publisher": subscription.publisher.name,
        "listing_id": subscription.listing_id,
        "listing_code": subscription.listing.code if subscription.listing_id else "",
        "url": subscription.url,
        "events": subscription.events or [],
        "status": subscription.status,
        "secret_configured": bool(subscription.secret),
        "last_delivery_at": iso(subscription.last_delivery_at),
        "last_status": subscription.last_status,
        "failure_count": subscription.failure_count,
        "owner_id": subscription.owner_id,
        "created_at": iso(subscription.created_at),
        "updated_at": iso(subscription.updated_at),
    }


def delivery_dict(delivery):
    """Webhook 投递记录。"""
    return {
        "id": delivery.id,
        "subscription_id": delivery.subscription_id,
        "event_type": delivery.event_type,
        "payload": delivery.payload or {},
        "response_status": delivery.response_status,
        "response_body": delivery.response_body,
        "success": delivery.success,
        "attempt": delivery.attempt,
        "delivered_at": iso(delivery.delivered_at),
    }


def event_dict(event):
    """市场事件。"""
    return {
        "id": event.id,
        "event_type": event.event_type,
        "listing_id": event.listing_id,
        "listing_code": event.listing.code if event.listing_id else "",
        "payload": event.payload or {},
        "idempotency_key": event.idempotency_key,
        "status": event.status,
        "attempts": event.attempts,
        "error": event.error,
        "processed_at": iso(event.processed_at),
        "owner_id": event.owner_id,
        "created_at": iso(event.created_at),
    }


def collection_item_dict(item):
    """合集条目。"""
    return {
        "id": item.id,
        "collection_id": item.collection_id,
        "listing_id": item.listing_id,
        "order": item.order,
        "listing": listing_brief(item.listing),
    }


def collection_dict(collection, with_items=False):
    """合集详情；with_items=True 时附条目（按 order 排序）。"""
    items = collection.mp_items.select_related("listing", "listing__publisher",
                                                "listing__category")
    data = {
        "id": collection.id,
        "slug": collection.slug,
        "title": collection.title,
        "description": collection.description,
        "cover": collection.cover,
        "order": collection.order,
        "status": collection.status,
        "featured": collection.featured,
        "published_at": iso(collection.published_at),
        "item_count": items.count(),
        "owner_id": collection.owner_id,
        "created_at": iso(collection.created_at),
        "updated_at": iso(collection.updated_at),
    }
    if with_items:
        data["items"] = [collection_item_dict(item) for item in items.order_by("order", "id")]
    return data


def report_dict(report):
    """举报记录。"""
    return {
        "id": report.id,
        "listing_id": report.listing_id,
        "listing": listing_brief(report.listing),
        "reason": report.reason,
        "detail": report.detail,
        "evidence": report.evidence or [],
        "status": report.status,
        "resolution": report.resolution,
        "handled_at": iso(report.handled_at),
        "owner_id": report.owner_id,
        "owner": user_brief(report.owner),
        "created_at": iso(report.created_at),
        "updated_at": iso(report.updated_at),
    }


def screenshot_dict(screenshot):
    """截图元数据。"""
    return {
        "id": screenshot.id,
        "listing_id": screenshot.listing_id,
        "file_name": screenshot.file_name,
        "file_url": screenshot.file_url,
        "mime_type": screenshot.mime_type,
        "file_size": screenshot.file_size,
        "width": screenshot.width,
        "height": screenshot.height,
        "order": screenshot.order,
        "caption": screenshot.caption,
        "owner_id": screenshot.owner_id,
        "created_at": iso(screenshot.created_at),
    }


def compat_dict(tag):
    """兼容性标签。"""
    return {
        "id": tag.id,
        "listing_id": tag.listing_id,
        "platform_version": tag.platform_version,
        "tag": tag.tag,
        "note": tag.note,
        "owner_id": tag.owner_id,
        "created_at": iso(tag.created_at),
    }
