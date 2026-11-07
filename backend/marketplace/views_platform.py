# -*- coding: utf-8 -*-
"""应用市场 · 开放能力接口（27 个）。

覆盖 Webhook/事件、合集、举报、截图与兼容标签：
- Webhook 采用本地模拟投递（不联网），但订阅匹配、失败计数、最近状态真实；
- 事件写入带幂等键，重复提交不会重复投递（购买/安装侧可传 idempotency_key）；
- 合集发布前做去重与「应用必须已上架」校验，草稿不对外；
- 举报走 pending → reviewing → resolved/dismissed 状态机，处置需结论；
- 截图只存元数据（文件由前端上传通道处理），兼容标签需合法平台版本。
"""
import secrets

from django.db import transaction
from django.utils import timezone

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)

from . import services
from .common import (ensure_listing_visible, ensure_listing_writable,
                     get_category, get_collection, get_collection_item,
                     get_compat, get_delivery, get_listing, get_publisher,
                     get_report, get_screenshot, get_webhook,
                     is_staff_user, listing_by_reference, page_params,
                     paginate_queryset, paginate_rows, parse_dict, parse_ids,
                     parse_list, require_owner, require_staff, valid_slug)
from .models import (
    COLLECTION_STATUS_VALUES,
    EVENT_STATUS_VALUES,
    REPORT_REASON_CHOICES,
    REPORT_STATUS_VALUES,
    WEBHOOK_STATUS_CHOICES,
    Collection,
    CollectionItem,
    CompatibilityTag,
    Listing,
    ListingReport,
    MarketplaceEvent,
    Screenshot,
    WebhookDelivery,
    WebhookSubscription,
)
from .serializers import (collection_dict, compat_dict, delivery_dict, event_dict,
                          iso, listing_brief, report_dict, screenshot_dict,
                          webhook_dict)
from .views_catalog import EVENT_TYPES

WEBHOOK_EVENT_VALUES = tuple(item["value"] for item in EVENT_TYPES)
COMPAT_TAG_VALUES = ("verified", "beta", "deprecated", "broken")
REPORT_REASON_VALUES = tuple(value for value, _label in REPORT_REASON_CHOICES)


def _webhook_events(request):
    """Webhook 事件入参：必须命中事件清单或 *，且至少一项。"""
    events = [str(x).strip() for x in parse_list(request, "events")]
    events = [x for x in events if x]
    if not events:
        raise ValueError("events 至少需要一个事件类型（可用 * 表示全部）")
    for event in events:
        if event != "*" and event not in WEBHOOK_EVENT_VALUES:
            raise ValueError(f"不支持的事件类型 {event}")
    return list(dict.fromkeys(events))


def _validate_url(url):
    """回调地址必须是 http(s)（本地模拟投递也要求形态正确）。"""
    text = str(url or "").strip()
    if not (text.startswith("http://") or text.startswith("https://")):
        raise ValueError("回调地址必须是 http:// 或 https:// 开头")
    if len(text) > 500:
        raise ValueError("回调地址过长（上限 500 字符）")
    return text


# ---------------------------------------------------------------------------
# Webhook 与事件
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def webhooks(request):
    """Webhook 订阅列表（我的/发布者的）或创建订阅（返回一次签名密钥）。"""
    if request.method == "GET":
        if is_staff_user(request.user) and opt_bool(request, "all", False):
            queryset = WebhookSubscription.objects.all()
        else:
            queryset = WebhookSubscription.objects.filter(owner=request.user)
        queryset = queryset.select_related("publisher", "listing").order_by("-created_at")
        return ok(paginate_queryset(
            request, queryset, webhook_dict,
            search_fields=("url", "publisher__name", "listing__code"),
        ))

    publisher = get_publisher(int(req_num(request, "publisher_id", integer=True)),
                              request.user, write=True)
    url = _validate_url(req_str(request, "url", max_len=500))
    events = _webhook_events(request)
    listing = None
    listing_id = opt_num(request, "listing_id", integer=True)
    if listing_id:
        listing = publisher.mp_publisher_listings.filter(pk=int(listing_id)).first()
        if listing is None:
            raise ValueError("应用不属于该发布者")
    secret = opt_str(request, "secret", "").strip() or secrets.token_hex(16)
    subscription = WebhookSubscription.objects.create(
        owner=request.user,
        publisher=publisher,
        listing=listing,
        url=url,
        events=events,
        secret=secret,
        status="active",
    )
    data = webhook_dict(subscription)
    # 与许可证一致：签名密钥只在创建响应返回一次，便于接入方保存
    data["secret"] = secret
    return ok(data)


@endpoint(("GET",))
def webhook_detail(request, pk):
    """Webhook 订阅详情（密钥不回显）。"""
    subscription = get_webhook(pk, request.user)
    data = webhook_dict(subscription)
    data["recent_deliveries"] = [
        delivery_dict(d) for d in
        subscription.mp_deliveries.all()[:10]
    ]
    return ok(data)


@endpoint()
def webhook_update(request, pk):
    """更新 Webhook 订阅（地址/事件/密钥/状态/应用范围）。"""
    subscription = get_webhook(pk, request.user, write=True)
    if p(request, "url") is not None:
        subscription.url = _validate_url(p(request, "url"))
    if p(request, "events") is not None:
        subscription.events = _webhook_events(request)
    if p(request, "secret") is not None:
        subscription.secret = opt_str(request, "secret", "").strip()
    if p(request, "status") is not None:
        status = str(p(request, "status")).strip()
        if status not in [value for value, _label in WEBHOOK_STATUS_CHOICES]:
            raise ValueError("status 支持 active/disabled")
        subscription.status = status
    if p(request, "listing_id") not in (None, ""):
        listing = subscription.publisher.mp_publisher_listings.filter(
            pk=int(opt_num(request, "listing_id", integer=True))).first()
        if listing is None:
            raise ValueError("应用不属于该发布者")
        subscription.listing = listing
    elif p(request, "listing_id") == "":
        subscription.listing = None
    subscription.save()
    return ok(webhook_dict(subscription))


@endpoint()
def webhook_delete(request, pk):
    """删除 Webhook 订阅（发布者/管理员；投递记录级联删除）。"""
    subscription = get_webhook(pk, request.user, write=True)
    sid = subscription.id
    subscription.delete()
    return ok({"deleted": True, "id": sid})


@endpoint()
def webhook_test(request, pk):
    """测试投递（本地模拟；URL 含 fail 时模拟 500，便于验证失败分支）。"""
    subscription = get_webhook(pk, request.user)
    if subscription.owner_id != request.user.id \
            and subscription.publisher.owner_id != request.user.id \
            and not is_staff_user(request.user):
        raise ValueError("无权测试该订阅")
    event_type = opt_str(request, "event_type", "webhook.test").strip()
    payload = parse_dict(request, "payload")
    result = services.test_webhook(subscription, event_type, payload)
    result["subscription"] = webhook_dict(subscription)
    return ok(result)


@endpoint(("GET",))
def webhook_deliveries(request, pk):
    """投递记录列表（按事件/成功失败筛选，q 匹配事件类型与响应摘要）。"""
    subscription = get_webhook(pk, request.user)
    queryset = subscription.mp_deliveries.all().order_by("-delivered_at")
    status = opt_str(request, "status").strip()
    if status in ("success", "failed"):
        queryset = queryset.filter(success=(status == "success"))
    elif status:
        raise ValueError("status 支持 success/failed")
    query = opt_str(request, "q").strip()
    if query:
        queryset = queryset.filter(event_type__icontains=query)
    page, size = page_params(request)
    total = queryset.count()
    start = (page - 1) * size
    return ok({
        "items": [delivery_dict(d) for d in queryset[start:start + size]],
        "count": total,
        "page": page,
        "page_size": size,
    })


@endpoint(("GET",))
def delivery_detail(request, pk):
    """投递记录详情（含负载与响应摘要）。"""
    return ok(delivery_dict(get_delivery(pk, request.user)))


@endpoint(("GET",))
def events(request):
    """市场事件列表（本人触发；管理员 all=1 看全部，支持 q/status）。"""
    if is_staff_user(request.user) and opt_bool(request, "all", False):
        queryset = MarketplaceEvent.objects.all()
    else:
        queryset = MarketplaceEvent.objects.filter(owner=request.user)
    queryset = queryset.select_related("listing").order_by("-created_at")
    event_type = opt_str(request, "event_type").strip()
    if event_type:
        queryset = queryset.filter(event_type=event_type)
    status = opt_str(request, "status").strip()
    if status:
        if status not in EVENT_STATUS_VALUES:
            raise ValueError(f"status 支持 {'/'.join(EVENT_STATUS_VALUES)}")
        queryset = queryset.filter(status=status)
    return ok(paginate_queryset(
        request, queryset, event_dict,
        search_fields=("event_type", "listing__code", "idempotency_key"),
        status_field=None,
    ))


@endpoint(("GET",))
def event_detail(request, pk):
    """市场事件详情（本人或管理员）。"""
    event = MarketplaceEvent.objects.select_related("listing").filter(pk=pk).first()
    if event is None:
        raise ValueError("事件不存在")
    if event.owner_id != request.user.id and not is_staff_user(request.user):
        raise ValueError("无权访问该事件")
    data = event_dict(event)
    delivery_qs = WebhookDelivery.objects.none()
    if event.listing_id:
        delivery_qs = WebhookDelivery.objects.filter(
            subscription__publisher_id=event.listing.publisher_id,
        )
    data["deliveries"] = [delivery_dict(d) for d in delivery_qs[:20]]
    return ok(data)


# ---------------------------------------------------------------------------
# 合集
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def collections(request):
    """合集列表（公开只看已发布，mine=1 看自己的草稿）或创建合集。"""
    if request.method == "GET":
        mine = opt_bool(request, "mine", False)
        if is_staff_user(request.user) and opt_bool(request, "all", False):
            queryset = Collection.objects.all()
        elif mine:
            queryset = Collection.objects.filter(owner=request.user)
        else:
            queryset = Collection.objects.filter(status="published")
        queryset = queryset.select_related("owner").order_by("order", "-created_at")
        return ok(paginate_queryset(
            request, queryset, collection_dict,
            search_fields=("title", "slug", "description"),
        ))

    title = req_str(request, "title", max_len=200).strip()
    slug = valid_slug(opt_str(request, "slug").strip()
                      or f"col-{timezone.now():%Y%m%d%H%M%S}")
    if Collection.objects.filter(slug=slug).exists():
        raise ValueError(f"合集标识 {slug} 已被占用")
    collection = Collection.objects.create(
        owner=request.user,
        slug=slug,
        title=title[:200],
        description=opt_str(request, "description"),
        cover=opt_str(request, "cover", max_len=300),
        order=int(opt_num(request, "order", 0, minimum=0, maximum=100000, integer=True)),
        status="draft",
        featured=opt_bool(request, "featured", False),
    )
    return ok(collection_dict(collection))


@endpoint(("GET",))
def collections_public(request):
    """公开合集列表（已发布，按排序；q/分页）。"""
    queryset = Collection.objects.filter(status="published").order_by("order", "-created_at")
    page, size = page_params(request)
    query = opt_str(request, "q").strip()
    if query:
        queryset = queryset.filter(title__icontains=query)
    total = queryset.count()
    start = (page - 1) * size
    return ok({
        "items": [collection_dict(c, with_items=True)
                  for c in queryset[start:start + size]],
        "count": total,
        "page": page,
        "page_size": size,
    })


@endpoint(("GET",))
def collection_detail(request, pk):
    """合集详情（已发布公开；草稿仅创建者/管理员）。"""
    collection = get_collection(pk, request.user)
    return ok(collection_dict(collection, with_items=True))


@endpoint()
def collection_update(request, pk):
    """更新合集（创建者；标题/描述/封面/排序/推荐）。"""
    collection = get_collection(pk, request.user, write=True)
    if p(request, "title") is not None:
        title = str(p(request, "title")).strip()
        if not title:
            raise ValueError("合集标题不能为空")
        collection.title = title[:200]
    if p(request, "description") is not None:
        collection.description = str(p(request, "description"))
    if p(request, "cover") is not None:
        collection.cover = str(p(request, "cover"))[:300]
    if p(request, "order") not in (None, ""):
        collection.order = int(opt_num(request, "order", collection.order,
                                       minimum=0, maximum=100000, integer=True))
    if p(request, "featured") is not None:
        collection.featured = opt_bool(request, "featured", collection.featured)
    collection.save()
    return ok(collection_dict(collection, with_items=True))


@endpoint()
def collection_delete(request, pk):
    """删除合集（创建者；条目级联删除，不影响应用本身）。"""
    collection = get_collection(pk, request.user, write=True)
    cid, title = collection.id, collection.title
    collection.delete()
    return ok({"deleted": True, "id": cid, "title": title})


@endpoint()
def collection_publish(request, pk):
    """发布合集（创建者；至少一个条目且全部应用已上架）。"""
    collection = get_collection(pk, request.user, write=True)
    result = services.publish_collection(collection)
    return ok(result)


@endpoint()
def collection_add_item(request, pk):
    """向合集添加应用（创建者；仅已上架应用，重复添加幂等）。"""
    collection = get_collection(pk, request.user, write=True)
    listing = listing_by_reference(request)
    if listing.status != "published":
        raise ValueError("只能把已上架应用加入合集")
    item, created = services.add_collection_item(collection, listing)
    data = collection_dict(collection, with_items=True)
    data["added_item_id"] = item.id
    data["created"] = created
    return ok(data)


@endpoint()
def collection_reorder(request, pk):
    """合集条目排序（创建者；去重后按给定顺序重排，未提交项追加末尾）。"""
    collection = get_collection(pk, request.user, write=True)
    ids = parse_ids(request, "items")
    if not ids:
        raise ValueError("items 不能为空")
    count = services.reorder_collection(collection, ids)
    return ok({"id": collection.id, "reordered": count,
               "items": [item.id for item in collection.mp_items.order_by("order", "id")]})


@endpoint()
def collection_item_delete(request, pk):
    """移除合集条目（创建者；不影响应用本身）。"""
    item = get_collection_item(pk, request.user, write=True)
    item_id, collection_id = item.id, item.collection_id
    item.delete()
    return ok({"deleted": True, "id": item_id, "collection_id": collection_id})


# ---------------------------------------------------------------------------
# 举报
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def reports(request):
    """举报列表（普通用户看自己的；管理员看全部并可看汇总）或提交举报。"""
    if request.method == "GET":
        if is_staff_user(request.user):
            queryset = ListingReport.objects.all()
        else:
            queryset = ListingReport.objects.filter(owner=request.user)
        queryset = queryset.select_related("listing", "listing__publisher",
                                           "owner").order_by("-created_at")
        reason = opt_str(request, "reason").strip()
        if reason:
            if reason not in REPORT_REASON_VALUES:
                raise ValueError(f"reason 支持 {'/'.join(REPORT_REASON_VALUES)}")
            queryset = queryset.filter(reason=reason)
        data = paginate_queryset(
            request, queryset, report_dict,
            search_fields=("detail", "resolution", "listing__name", "listing__code"),
        )
        if is_staff_user(request.user):
            data["summary"] = services.report_summary(queryset)
        return ok(data)

    listing = listing_by_reference(request)
    if listing.status != "published":
        raise ValueError("只能举报已上架应用")
    if listing.publisher.owner_id == request.user.id:
        raise ValueError("不能举报自己发布的应用")
    reason = req_str(request, "reason", max_len=30).strip()
    if reason not in REPORT_REASON_VALUES:
        raise ValueError(f"reason 支持 {'/'.join(REPORT_REASON_VALUES)}")
    existing = ListingReport.objects.filter(
        owner=request.user, listing=listing,
        status__in=("pending", "reviewing"),
    ).first()
    if existing is not None:
        raise ValueError("你已举报过该应用，请等待处理")
    report = ListingReport.objects.create(
        owner=request.user,
        listing=listing,
        reason=reason,
        detail=opt_str(request, "detail"),
        evidence=parse_list(request, "evidence"),
        status="pending",
    )
    with transaction.atomic():
        services.emit_event(
            listing, "report.created",
            {"report_id": report.id, "reason": reason},
            request.user,
        )
    return ok(report_dict(report))


@endpoint(("GET",))
def report_detail(request, pk):
    """举报详情（举报人/被举报发布者/管理员）。"""
    report = get_report(pk, request.user)
    data = report_dict(report)
    data["transitions"] = list(
        services.REPORT_TRANSITIONS.get(report.status, ()))
    return ok(data)


@endpoint()
def report_handle(request, pk):
    """处理举报（仅管理员；review/resolve/dismiss，已解决必须给结论）。"""
    report = get_report(pk, request.user, write=True)
    action = req_str(request, "action", max_len=20).strip()
    resolution = opt_str(request, "resolution", "").strip()
    result = services.transition_report(report, action, resolution, request.user)
    result["listing_id"] = report.listing_id
    return ok(result)


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def listing_screenshots(request, pk):
    """应用截图列表（公开只读）或新增截图元数据（维护者）。"""
    listing = get_listing(pk, request.user)
    ensure_listing_visible(listing, request.user)
    if request.method == "GET":
        queryset = listing.mp_screenshots.all().order_by("order", "id")
        return ok(paginate_queryset(
            request, queryset, screenshot_dict,
            search_fields=("file_name", "caption"), status_field=None,
        ))
    ensure_listing_writable(listing, request.user)
    file_name = req_str(request, "file_name", max_len=255).strip()
    file_url = req_str(request, "file_url", max_len=500).strip()
    mime_type = opt_str(request, "mime_type", "image/png", max_len=80).strip()
    if not mime_type.startswith("image/"):
        raise ValueError("截图 mime_type 必须是 image/*")
    last_order = (listing.mp_screenshots.order_by("-order")
                  .values_list("order", flat=True).first())
    screenshot = Screenshot.objects.create(
        owner=request.user,
        listing=listing,
        file_name=file_name,
        file_url=file_url,
        mime_type=mime_type,
        file_size=int(opt_num(request, "file_size", 0, minimum=0,
                              maximum=10 ** 11, integer=True)),
        width=int(opt_num(request, "width", 0, minimum=0, maximum=100000, integer=True)),
        height=int(opt_num(request, "height", 0, minimum=0, maximum=100000, integer=True)),
        order=int(opt_num(request, "order", (last_order or -1) + 1,
                          minimum=0, maximum=100000, integer=True)),
        caption=opt_str(request, "caption", max_len=200),
    )
    return ok(screenshot_dict(screenshot))


@endpoint()
def screenshot_update(request, pk):
    """更新截图元数据（维护者）。"""
    screenshot = get_screenshot(pk, request.user, write=True)
    if p(request, "file_name") is not None:
        screenshot.file_name = str(p(request, "file_name")).strip()[:255]
    if p(request, "file_url") is not None:
        screenshot.file_url = str(p(request, "file_url")).strip()[:500]
    if p(request, "mime_type") is not None:
        mime = str(p(request, "mime_type")).strip()[:80]
        if not mime.startswith("image/"):
            raise ValueError("截图 mime_type 必须是 image/*")
        screenshot.mime_type = mime
    if p(request, "caption") is not None:
        screenshot.caption = str(p(request, "caption"))[:200]
    if p(request, "order") not in (None, ""):
        screenshot.order = int(opt_num(request, "order", screenshot.order,
                                       minimum=0, maximum=100000, integer=True))
    screenshot.save()
    return ok(screenshot_dict(screenshot))


@endpoint()
def screenshot_delete(request, pk):
    """删除截图（维护者）。"""
    screenshot = get_screenshot(pk, request.user, write=True)
    sid = screenshot.id
    screenshot.delete()
    return ok({"deleted": True, "id": sid})


@endpoint()
def screenshots_reorder(request, pk):
    """截图排序（维护者；按 id 顺序重排，未知 id 报错）。"""
    listing = get_listing(pk, request.user, write=True)
    ids = parse_ids(request, "items")
    if not ids:
        raise ValueError("items 不能为空")
    rows = {s.id: s for s in listing.mp_screenshots.all()}
    unknown = [i for i in ids if i not in rows]
    if unknown:
        raise ValueError(f"截图不包含 id: {unknown[0]}")
    with transaction.atomic():
        for position, shot_id in enumerate(ids):
            shot = rows.pop(shot_id)
            if shot.order != position:
                shot.order = position
                shot.save(update_fields=["order", "updated_at"])
        for shot in sorted(rows.values(), key=lambda x: (x.order, x.id)):
            shot.order = len(ids)
            shot.save(update_fields=["order", "updated_at"])
    return ok({"listing_id": listing.id, "reordered": len(ids)})


# ---------------------------------------------------------------------------
# 兼容标签
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def listing_compatibility(request, pk):
    """应用兼容标签列表（公开）或新增标签（维护者，平台版本需合法）。"""
    listing = get_listing(pk, request.user)
    ensure_listing_visible(listing, request.user)
    if request.method == "GET":
        queryset = listing.mp_compat_tags.all().order_by("platform_version", "tag")
        platform_version = opt_str(request, "platform_version").strip()
        if platform_version:
            queryset = queryset.filter(platform_version=platform_version)
        return ok(paginate_queryset(
            request, queryset, compat_dict,
            search_fields=("tag", "note", "platform_version"), status_field=None,
        ))
    ensure_listing_writable(listing, request.user)
    platform_version = req_str(request, "platform_version", max_len=40).strip()
    services.parse_version(platform_version, "平台版本")
    tag = opt_str(request, "tag", "verified", max_len=40).strip()
    if tag not in COMPAT_TAG_VALUES:
        raise ValueError(f"tag 支持 {'/'.join(COMPAT_TAG_VALUES)}")
    if listing.mp_compat_tags.filter(platform_version=platform_version, tag=tag).exists():
        raise ValueError("该平台版本的兼容标签已存在")
    compat = CompatibilityTag.objects.create(
        owner=request.user,
        listing=listing,
        platform_version=platform_version,
        tag=tag,
        note=opt_str(request, "note", max_len=200),
    )
    return ok(compat_dict(compat))


@endpoint()
def compatibility_delete(request, pk):
    """删除兼容标签（维护者）。"""
    compat = get_compat(pk, request.user, write=True)
    cid = compat.id
    compat.delete()
    return ok({"deleted": True, "id": cid})


PLATFORM_ENDPOINT_COUNT = 27
