# -*- coding: utf-8 -*-
"""应用市场 · 视图公共助手：分页、权限、对象获取与入参归一化。

把重复逻辑收口在这里，视图里只保留「业务动作 + 一句中文 docstring」。
权限口径与平台其他应用保持一致：
- 读：已上架内容对所有登录用户开放；未上架内容仅维护者/发布者/管理员可见；
- 写：owner（或发布者 owner）+ 管理员；
- 审核/认证/暂停等治理动作：仅 is_staff / is_superuser。
"""
import re

from django.db.models import Q
from django.utils import timezone

from devtools.common import opt_num, opt_str, p

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
    Pricing,
    Publisher,
    Purchase,
    Review,
    ReviewReply,
    Screenshot,
    WebhookDelivery,
    WebhookSubscription,
)

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 200

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,99}$")


def is_staff_user(user):
    """管理员判定：超管或 staff（与平台其他应用一致）。"""
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))


def require_staff(user, message="仅管理员可审核"):
    """治理动作准入：非管理员统一抛中文 ValueError（400 语义）。"""
    if not is_staff_user(user):
        raise ValueError(message)


def require_owner(user, obj, message="无权修改该对象", owner_field="owner"):
    """严格 owner 判定（管理员放行）。"""
    if is_staff_user(user):
        return
    if getattr(obj, f"{owner_field}_id", None) != getattr(user, "id", None):
        raise ValueError(message)


def ensure_admin_or_owner(user, obj, message="无权修改该对象"):
    """owner 或管理员的通用写权限。"""
    require_owner(user, obj, message)


# ---------------------------------------------------------------------------
# 分页
# ---------------------------------------------------------------------------


def page_params(request):
    """读取 page / page_size：page_size 上限 200（与平台统一约定一致）。"""
    page = int(opt_num(request, "page", 1, minimum=1, maximum=100000, integer=True) or 1)
    size = int(opt_num(request, "page_size", PAGE_SIZE_DEFAULT, minimum=1,
                       maximum=PAGE_SIZE_MAX, integer=True) or PAGE_SIZE_DEFAULT)
    return page, size


def page_payload(items, total, page, size):
    """统一分页响应结构。"""
    return {"items": items, "count": total, "page": page, "page_size": size}


def paginate_queryset(request, queryset, serializer, search_fields=(),
                      status_field="status"):
    """数据库分页 + q/status 过滤。

    :param search_fields: q 参与匹配的字段（icontains，OR 关系）
    :param status_field: 状态过滤字段；传 None 表示该实体没有 status 概念
    """
    page, size = page_params(request)
    status = opt_str(request, "status").strip()
    if status and status_field:
        queryset = queryset.filter(**{status_field: status})
    query = opt_str(request, "q").strip()
    if query and search_fields:
        condition = Q()
        for field in search_fields:
            condition |= Q(**{f"{field}__icontains": query})
        queryset = queryset.filter(condition)
    total = queryset.count()
    start = (page - 1) * size
    rows = queryset[start:start + size]
    return page_payload([serializer(row) for row in rows], total, page, size)


def paginate_rows(request, rows, serializer):
    """内存分页（搜索打分/统计排序后使用）。rows 元素可以是对象或 (对象, 分值)。"""
    page, size = page_params(request)
    total = len(rows)
    start = (page - 1) * size
    items = []
    for row in rows[start:start + size]:
        if isinstance(row, tuple):
            items.append(serializer(row[0], row[1]))
        else:
            items.append(serializer(row))
    return page_payload(items, total, page, size)


# ---------------------------------------------------------------------------
# 入参归一化
# ---------------------------------------------------------------------------


def parse_tags(request, key="tags", max_items=20, max_len=40):
    """标签入参：支持 JSON 数组或逗号分隔字符串，去重并截断。"""
    raw = p(request, key)
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        raw = [x for x in re.split(r"[,，\s]+", raw) if x.strip()]
    if not isinstance(raw, list):
        raise ValueError(f"参数 {key} 必须是数组或逗号分隔字符串")
    out = []
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        if len(text) > max_len:
            raise ValueError(f"标签 “{text[:10]}…” 超过 {max_len} 字符")
        if text not in out:
            out.append(text)
        if len(out) > max_items:
            raise ValueError(f"标签最多 {max_items} 个")
    return out


def parse_dict(request, key, required=False):
    """对象型参数（缺省返回 {}）。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是对象")
    return value


def parse_list(request, key, required=False, max_items=200):
    """数组型参数（缺省返回 []）。"""
    value = p(request, key)
    if value in (None, ""):
        if required:
            raise ValueError(f"缺少必填参数: {key}")
        return []
    if isinstance(value, str):
        value = [x for x in re.split(r"[,，\s]+", value) if x.strip()]
    if not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是数组")
    if len(value) > max_items:
        raise ValueError(f"参数 {key} 最多 {max_items} 项")
    return value


def parse_ids(request, key="ids", max_items=200):
    """整数 id 数组（排序/批量操作）。"""
    raw = parse_list(request, key, max_items=max_items)
    ids = []
    for item in raw:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            raise ValueError(f"参数 {key} 只能包含整数")
    return ids


def valid_email(value, required=False):
    """邮箱格式校验（空值在非必填场景放行）。"""
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError("联系邮箱不能为空")
        return ""
    if not _EMAIL_RE.match(text):
        raise ValueError("联系邮箱格式不正确")
    return text


def valid_slug(value, field="标识"):
    """标识校验：小写字母数字与 ._-，长度 2~100。"""
    text = str(value or "").strip().lower()
    if not text:
        raise ValueError(f"{field}不能为空")
    if not _SLUG_RE.match(text):
        raise ValueError(f"{field}只能包含小写字母、数字、点、下划线和中划线，且不超过 100 字符")
    return text


def status_or_default(raw, allowed, default="draft", field="status"):
    """状态枚举校验：非法值直接 400，避免写入不可达状态。"""
    text = str(raw or "").strip() or default
    if text not in allowed:
        raise ValueError(f"{field} 支持 {'/'.join(allowed)}")
    return text


def optional_status(raw, allowed, field="status"):
    """可空状态校验（用于查询参数）。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    if text not in allowed:
        raise ValueError(f"{field} 支持 {'/'.join(allowed)}")
    return text


# ---------------------------------------------------------------------------
# 对象获取 + 权限
# ---------------------------------------------------------------------------


def get_publisher(pk, user=None, write=False):
    """取发布者并校验写权限。"""
    publisher = Publisher.objects.select_related("owner").filter(pk=pk).first()
    if publisher is None:
        raise ValueError("发布者不存在")
    if write:
        require_owner(user, publisher, "无权修改该发布者")
    return publisher


def can_manage_listing(user, listing):
    """应用维护权：管理员、应用 owner 或所属发布者 owner。"""
    if is_staff_user(user):
        return True
    if listing.owner_id == getattr(user, "id", None):
        return True
    return listing.publisher.owner_id == getattr(user, "id", None)


def get_listing(pk, user=None, write=False, allow_unpublished=True):
    """取应用；读接口对未上架内容做可见性收敛。"""
    listing = (Listing.objects.select_related("publisher", "publisher__owner",
                                              "category", "latest_version")
               .filter(pk=pk).first())
    if listing is None:
        raise ValueError("应用不存在")
    if not allow_unpublished and listing.status != "published":
        if not can_manage_listing(user, listing):
            raise ValueError("应用未上架")
    if write:
        ensure_listing_writable(listing, user)
    return listing


def ensure_listing_visible(listing, user):
    """读可见性：已上架对登录用户开放；未上架仅维护者/发布者/管理员。"""
    if listing.status == "published":
        return listing
    if not can_manage_listing(user, listing):
        raise ValueError("应用未上架")
    return listing


def ensure_listing_writable(listing, user):
    """写权限：维护者/发布者/管理员；发布者被暂停时禁止发布侧操作。"""
    if not can_manage_listing(user, listing):
        raise ValueError("无权修改该应用")
    if listing.publisher.status == "suspended" and not is_staff_user(user):
        raise ValueError("发布者已被暂停，暂不能修改应用")


def listing_by_reference(request, write=False, field="listing_id"):
    """按 listing_id 或 code 取应用（安装/购买/举报等入口共用）。"""
    raw_id = p(request, field)
    code = opt_str(request, "code").strip()
    if raw_id not in (None, ""):
        try:
            listing = Listing.objects.select_related("publisher", "category").filter(
                pk=int(raw_id)).first()
        except (TypeError, ValueError):
            raise ValueError(f"参数 {field} 必须是整数")
    elif code:
        listing = Listing.objects.select_related("publisher", "category").filter(
            code=code).first()
    else:
        raise ValueError(f"缺少必填参数: {field} 或 code")
    if listing is None:
        raise ValueError("应用不存在")
    if write:
        ensure_listing_writable(listing, request.user)
    return listing


def get_version(pk, user=None, write=False):
    """取版本并校验其应用的写权限。"""
    version = (ListingVersion.objects.select_related("listing", "listing__publisher")
               .filter(pk=pk).first())
    if version is None:
        raise ValueError("版本不存在")
    if write:
        ensure_listing_writable(version.listing, user)
    return version


def get_install(pk, user, write=False):
    """取安装记录（仅本人；管理员可读）。"""
    install = (Install.objects.select_related("listing", "listing__publisher", "version")
               .filter(pk=pk).first())
    if install is None:
        raise ValueError("安装记录不存在")
    if install.owner_id != getattr(user, "id", None) and not is_staff_user(user):
        raise ValueError("无权访问该安装记录")
    if write and install.owner_id != getattr(user, "id", None):
        raise ValueError("只能操作自己的安装记录")
    return install


def get_review(pk, user=None, write=False):
    """取评价；写权限允许评价人、应用维护者与管理员。"""
    review = (Review.objects.select_related("listing", "listing__publisher", "owner")
              .filter(pk=pk).first())
    if review is None:
        raise ValueError("评价不存在")
    if write:
        if (review.owner_id != getattr(user, "id", None)
                and not can_manage_listing(user, review.listing)):
            raise ValueError("无权修改该评价")
    return review


def get_reply(pk, user, write=False):
    """取回复；写权限为回复人、应用维护者与管理员。"""
    reply = (ReviewReply.objects.select_related("review", "review__listing",
                                               "review__listing__publisher", "owner")
             .filter(pk=pk).first())
    if reply is None:
        raise ValueError("回复不存在")
    if write:
        if (reply.owner_id != getattr(user, "id", None)
                and not can_manage_listing(user, reply.review.listing)):
            raise ValueError("无权删除该回复")
    return reply


def get_pricing(pk, user, write=False):
    """取定价并校验应用写权限。"""
    pricing = Pricing.objects.select_related("listing", "listing__publisher").filter(pk=pk).first()
    if pricing is None:
        raise ValueError("定价不存在")
    if write:
        ensure_listing_writable(pricing.listing, user)
    return pricing


def get_purchase(pk, user, write=False):
    """取订单；读权限为购买者、应用发布者与管理员。"""
    purchase = (Purchase.objects.select_related(
        "listing", "listing__publisher", "owner", "version").filter(pk=pk).first())
    if purchase is None:
        raise ValueError("订单不存在")
    allowed = (
        purchase.owner_id == getattr(user, "id", None)
        or purchase.listing.publisher.owner_id == getattr(user, "id", None)
        or is_staff_user(user)
    )
    if not allowed:
        raise ValueError("无权访问该订单")
    if write and purchase.owner_id != getattr(user, "id", None) and not is_staff_user(user):
        raise ValueError("只能操作自己的订单")
    return purchase


def get_license(pk, user, write=False):
    """取许可证（仅被授权人；管理员可读）。"""
    license_obj = (License.objects.select_related("listing", "purchase", "owner")
                   .filter(pk=pk).first())
    if license_obj is None:
        raise ValueError("许可证不存在")
    if license_obj.owner_id != getattr(user, "id", None) and not is_staff_user(user):
        raise ValueError("无权访问该许可证")
    if write and license_obj.owner_id != getattr(user, "id", None):
        raise ValueError("只能操作自己的许可证")
    return license_obj


def get_webhook(pk, user, write=False):
    """取 Webhook 订阅：owner 或发布者 owner 或管理员。"""
    subscription = (WebhookSubscription.objects.select_related(
        "publisher", "publisher__owner", "listing").filter(pk=pk).first())
    if subscription is None:
        raise ValueError("Webhook 订阅不存在")
    allowed = (
        subscription.owner_id == getattr(user, "id", None)
        or subscription.publisher.owner_id == getattr(user, "id", None)
        or is_staff_user(user)
    )
    if not allowed:
        raise ValueError("无权访问该 Webhook 订阅")
    if write and subscription.publisher.owner_id != getattr(user, "id", None) \
            and not is_staff_user(user):
        raise ValueError("只有发布者可以修改该订阅")
    return subscription


def get_delivery(pk, user):
    """取投递记录（订阅所有者/管理员）。"""
    delivery = (WebhookDelivery.objects.select_related(
        "subscription", "subscription__publisher").filter(pk=pk).first())
    if delivery is None:
        raise ValueError("投递记录不存在")
    if (delivery.subscription.publisher.owner_id != getattr(user, "id", None)
            and not is_staff_user(user)):
        raise ValueError("无权访问该投递记录")
    return delivery


def get_collection(pk, user=None, write=False):
    """取合集；草稿态仅创建者/管理员可见。"""
    collection = Collection.objects.select_related("owner").filter(pk=pk).first()
    if collection is None:
        raise ValueError("合集不存在")
    if write:
        require_owner(user, collection, "无权修改该合集")
    elif collection.status != "published" and collection.owner_id != getattr(user, "id", None) \
            and not is_staff_user(user):
        raise ValueError("合集未发布")
    return collection


def get_collection_item(pk, user, write=False):
    """取合集条目并校验合集写权限。"""
    item = (CollectionItem.objects.select_related("collection", "listing")
            .filter(pk=pk).first())
    if item is None:
        raise ValueError("合集条目不存在")
    if write:
        require_owner(user, item.collection, "无权修改该合集")
    return item


def get_report(pk, user, write=False):
    """取举报：举报人、被举报应用的发布者、管理员可见。"""
    report = (ListingReport.objects.select_related(
        "listing", "listing__publisher", "owner").filter(pk=pk).first())
    if report is None:
        raise ValueError("举报不存在")
    allowed = (
        report.owner_id == getattr(user, "id", None)
        or report.listing.publisher.owner_id == getattr(user, "id", None)
        or is_staff_user(user)
    )
    if not allowed:
        raise ValueError("无权访问该举报")
    if write:
        require_staff(user, "仅管理员可处理举报")
    return report


def get_screenshot(pk, user, write=False):
    """取截图并校验应用写权限。"""
    shot = (Screenshot.objects.select_related("listing", "listing__publisher")
            .filter(pk=pk).first())
    if shot is None:
        raise ValueError("截图不存在")
    if write:
        ensure_listing_writable(shot.listing, user)
    return shot


def get_compat(pk, user, write=False):
    """取兼容标签并校验应用写权限。"""
    tag = (CompatibilityTag.objects.select_related("listing", "listing__publisher")
           .filter(pk=pk).first())
    if tag is None:
        raise ValueError("兼容标签不存在")
    if write:
        ensure_listing_writable(tag.listing, user)
    return tag


def get_category(pk, write=False):
    """取分类（分类维护仅管理员）。"""
    category = Category.objects.select_related("parent").filter(pk=pk).first()
    if category is None:
        raise ValueError("分类不存在")
    if write:
        # 分类维护属于平台治理动作，由视图先做 require_staff，这里不再重复取 user
        pass
    return category


def visible_listing_queryset(user, mine=False):
    """应用列表基础集合：mine=True 看自己的全部状态，否则只看已上架。

    管理员在 mine=False 时也只看已上架：市场前台列表应保持「所见即已发布」，
    审核/下架操作走各自的治理接口与后台列表（status 参数）。
    """
    queryset = Listing.objects.select_related("publisher", "category", "latest_version")
    if mine:
        if is_staff_user(user):
            return queryset
        return queryset.filter(
            Q(owner=user) | Q(publisher__owner=user)
        ).distinct()
    return queryset.filter(status__in=("published",))


def public_collection_queryset():
    """对外可见合集：已发布。"""
    return Collection.objects.filter(status="published")


def today():
    """当前日期（统计口径统一取本地时区）。"""
    return timezone.localdate()
