# -*- coding: utf-8 -*-
"""应用市场 · 应用与版本接口（24 个）。

生命周期：
    创建（draft）→ 提交审核（reviewing）→ 审核通过（published）
    → 下架（delisted）/ 暂停（suspended，管理员）→ 重新上架

发布约束（真实语义，不做无校验直通）：
- 提交审核要求发布者已认证、至少一个版本、依赖清单可解析；
- 审核通过会自动发布最高版本，避免「应用已上架但没有可安装版本」；
- 已发布版本不物理删除（先下架），保证历史安装/订单的可追溯性；
- 克隆复制版本与截图，但不复制安装、订单与评价（业务上不应继承）。
"""
import hashlib
import json

from django.db import transaction
from django.utils import timezone

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)

from . import services
from .common import (ensure_listing_visible, ensure_listing_writable,
                     get_listing, get_version, is_staff_user,
                     listing_by_reference, page_payload, page_params,
                     paginate_queryset, parse_dict, parse_tags,
                     require_staff, status_or_default, valid_slug,
                     visible_listing_queryset)
from .models import (
    LISTING_EDITABLE_STATUS,
    LISTING_STATUS_CHOICES,
    LISTING_STATUS_VALUES,
    LISTING_TYPE_VALUES,
    PRICING_MODE_VALUES,
    VERSION_STATUS_VALUES,
    Category,
    Install,
    Listing,
    ListingVersion,
    Pricing,
    Screenshot,
)
from .serializers import (iso, listing_brief, listing_dict, version_brief,
                          version_dict)


# ---------------------------------------------------------------------------
# 内部助手
# ---------------------------------------------------------------------------


def _audit(listing, action, user, note=""):
    """把治理动作写进 audit.events（尾部保留 50 条，防 JSON 无限膨胀）。"""
    data = dict(listing.audit or {})
    events = list(data.get("events") or [])
    events.append({
        "action": action,
        "by": getattr(user, "username", "system"),
        "note": str(note or "")[:500],
        "at": timezone.now().isoformat(),
    })
    data["events"] = events[-50:]
    listing.audit = data


def _unique_code(code, exclude=None):
    """应用标识唯一性预检。"""
    queryset = Listing.objects.filter(code=code)
    if exclude is not None:
        queryset = queryset.exclude(pk=exclude.pk)
    if queryset.exists():
        raise ValueError(f"应用标识 {code} 已被占用")
    return code


def _check_type(value, default="app"):
    """类型枚举校验。"""
    text = str(value or default).strip()
    if text not in LISTING_TYPE_VALUES:
        raise ValueError(f"type 支持 {'/'.join(LISTING_TYPE_VALUES)}")
    return text


def _check_pricing_mode(value, default="free"):
    """定价模式枚举校验。"""
    text = str(value or default).strip()
    if text not in PRICING_MODE_VALUES:
        raise ValueError(f"pricing_mode 支持 {'/'.join(PRICING_MODE_VALUES)}")
    return text


def _manifest_value(request, existing=None):
    """清单入参：必须是对象；requires 每条校验 code/range 语法。"""
    raw = p(request, "manifest")
    if raw is None:
        return existing if existing is not None else {}
    manifest = parse_dict(request, "manifest")
    requires = manifest.get("requires") or []
    if not isinstance(requires, list):
        raise ValueError("manifest.requires 必须是数组")
    cleaned = []
    for item in requires:
        if not isinstance(item, dict):
            raise ValueError("manifest.requires 的每一项必须是对象")
        code = str(item.get("code") or "").strip()
        if not code:
            raise ValueError("依赖项缺少 code")
        rng = str(item.get("range") or "*").strip()
        services.parse_range(rng, f"依赖 {code} 的版本范围")
        cleaned.append({"code": valid_slug(code, "依赖标识"), "range": rng})
    manifest["requires"] = cleaned
    return manifest


def _checksum(listing, version, manifest):
    """包校验和：由应用标识 + 版本 + 清单确定性生成（本地模拟构建产物）。"""
    payload = json.dumps(manifest or {}, sort_keys=True, ensure_ascii=False)
    raw = f"{listing.code}:{version}:{payload}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _latest_published(listing):
    """当前可用的最高已发布版本。"""
    return services.best_version_for_platform(listing, None)


def _publish_version_row(version, user):
    """把版本置为已发布并维护应用的 latest_version（幂等）。"""
    if version.status != "published":
        version.status = "published"
        version.published_at = timezone.now()
        version.save(update_fields=["status", "published_at", "breaking", "updated_at"])
    listing = version.listing
    latest = _latest_published(listing)
    if latest is not None and listing.latest_version_id != latest.id:
        listing.latest_version = latest
        listing.save(update_fields=["latest_version", "updated_at"])
    return version


def _ensure_publisher_can_publish(listing):
    """发布侧前置：发布者必须已认证且未被暂停。"""
    if listing.publisher.status == "suspended":
        raise ValueError("发布者已被暂停，不能发布应用")
    if listing.publisher.status != "verified":
        raise ValueError("发布者尚未认证，请先完成发布者认证")


def _viewer_flags(listing, user):
    """详情页的当前用户上下文：是否已安装/已购买/持有有效许可证。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return {"installed": False, "purchased": False, "licensed": False}
    install = Install.objects.filter(
        owner=user, listing=listing, status__in=("installed", "disabled")).first()
    purchase = listing.mp_purchases.filter(
        owner=user, payment_status="paid").first()
    license_obj = listing.mp_licenses.filter(owner=user, status="active").first()
    return {
        "installed": install is not None,
        "install_id": install.id if install else None,
        "installed_version": install.version.version if install and install.version else None,
        "purchased": purchase is not None,
        "purchase_id": purchase.id if purchase else None,
        "licensed": license_obj is not None,
        "license_id": license_obj.id if license_obj else None,
    }


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def listings(request):
    """应用列表（登录用户只读已上架，mine=1 看自己的全部）或创建应用草稿。"""
    if request.method == "GET":
        mine = opt_bool(request, "mine", False)
        queryset = visible_listing_queryset(request.user, mine=mine)
        publisher_id = opt_num(request, "publisher_id", integer=True)
        if publisher_id:
            queryset = queryset.filter(publisher_id=int(publisher_id))
        category_id = opt_num(request, "category_id", integer=True)
        if category_id:
            queryset = queryset.filter(category_id=int(category_id))
        category_code = opt_str(request, "category").strip()
        if category_code:
            queryset = queryset.filter(category__code=category_code)
        listing_type = opt_str(request, "type").strip()
        if listing_type:
            if listing_type not in LISTING_TYPE_VALUES:
                raise ValueError(f"type 支持 {'/'.join(LISTING_TYPE_VALUES)}")
            queryset = queryset.filter(type=listing_type)
        pricing_mode = opt_str(request, "pricing_mode").strip()
        if pricing_mode and pricing_mode in PRICING_MODE_VALUES:
            queryset = queryset.filter(pricing_mode=pricing_mode)
        if opt_bool(request, "featured", False):
            queryset = queryset.filter(featured=True)
        sort = opt_str(request, "sort", "relevance").strip()
        query = opt_str(request, "q").strip()
        status = opt_str(request, "status").strip()
        if status:
            if status not in LISTING_STATUS_VALUES:
                raise ValueError(f"status 支持 {'/'.join(LISTING_STATUS_VALUES)}")
            queryset = queryset.filter(status=status)
        rows = services.search_listings(queryset, query=query, sort=sort)
        page, size = page_params(request)
        start = (page - 1) * size
        items = [listing_brief(item, score) for item, score in rows[start:start + size]]
        return ok(page_payload(items, len(rows), page, size))

    # ---- 创建草稿 ----
    name = req_str(request, "name", max_len=200).strip()
    if not name:
        raise ValueError("应用名称不能为空")
    publisher_id = opt_num(request, "publisher_id", integer=True)
    if not publisher_id:
        raise ValueError("缺少必填参数: publisher_id")
    publisher = request.user.mp_publishers.filter(pk=int(publisher_id)).first()
    if publisher is None:
        # 管理员可为任意发布者创建（代运营场景），但仍要求发布者存在
        from .models import Publisher

        publisher = Publisher.objects.filter(pk=int(publisher_id)).first()
        if publisher is None:
            raise ValueError("发布者不存在")
        if not is_staff_user(request.user):
            raise ValueError("无权在该发布者下创建应用")
    code = valid_slug(opt_str(request, "code").strip() or f"{publisher.slug}-{timezone.now():%y%m%d%H%M%S}")
    _unique_code(code)
    category = None
    category_id = opt_num(request, "category_id", integer=True)
    if category_id:
        category = Category.objects.filter(pk=int(category_id), active=True).first()
        if category is None:
            raise ValueError("分类不存在或已停用")
    listing = Listing.objects.create(
        owner=publisher.owner,
        publisher=publisher,
        category=category,
        code=code,
        name=name[:200],
        summary=opt_str(request, "summary", max_len=500),
        description=opt_str(request, "description"),
        icon=opt_str(request, "icon", max_len=300),
        type=_check_type(opt_str(request, "type", "app")),
        status="draft",
        pricing_mode=_check_pricing_mode(opt_str(request, "pricing_mode", "free")),
        tags=parse_tags(request),
        audit={"events": [{"action": "create", "by": request.user.username,
                           "at": timezone.now().isoformat()}]},
        remark=opt_str(request, "remark"),
    )
    return ok(listing_dict(listing))


@endpoint(("GET",))
def listings_mine(request):
    """我的应用（含草稿/审核中/已下架，支持 q/status/type 分页）。"""
    queryset = visible_listing_queryset(request.user, mine=True).order_by("-created_at")
    listing_type = opt_str(request, "type").strip()
    if listing_type:
        queryset = queryset.filter(type=listing_type)
    return ok(paginate_queryset(
        request, queryset, listing_brief,
        search_fields=("name", "code", "summary"),
    ))


@endpoint(("GET",))
def listings_search(request):
    """应用搜索：关键词 + 评分/安装量/推荐位排序（仅已上架）。"""
    query = opt_str(request, "q").strip()
    sort = opt_str(request, "sort", "relevance").strip()
    queryset = visible_listing_queryset(request.user)
    listing_type = opt_str(request, "type").strip()
    if listing_type:
        queryset = queryset.filter(type=listing_type)
    category_id = opt_num(request, "category_id", integer=True)
    if category_id:
        queryset = queryset.filter(category_id=int(category_id))
    rows = services.search_listings(queryset, query=query, sort=sort)
    page, size = page_params(request)
    start = (page - 1) * size
    items = [listing_brief(item, score) for item, score in rows[start:start + size]]
    return ok(page_payload(items, len(rows), page, size))


@endpoint(("GET",))
def listing_detail(request, pk):
    """应用详情（未上架仅维护者可见；附带当前用户的安装/购买/许可状态）。"""
    listing = get_listing(pk, request.user)
    ensure_listing_visible(listing, request.user)
    data = listing_dict(listing)
    data["viewer"] = _viewer_flags(listing, request.user)
    data["health"] = services.listing_health(listing)
    return ok(data)


@endpoint()
def listing_update(request, pk):
    """更新应用信息（审核中锁定；类型/分类/标签/定价模式可改）。"""
    listing = get_listing(pk, request.user, write=True)
    if listing.status not in LISTING_EDITABLE_STATUS and not is_staff_user(request.user):
        raise ValueError("审核中或已上架的应用不能直接编辑，请先下架或等待审核结束")
    if p(request, "name") is not None:
        name = str(p(request, "name")).strip()
        if not name:
            raise ValueError("应用名称不能为空")
        listing.name = name[:200]
    for field, limit in (("summary", 500), ("description", None), ("icon", 300)):
        raw = p(request, field)
        if raw is not None:
            setattr(listing, field, str(raw) if limit is None else str(raw)[:limit])
    if p(request, "type") is not None:
        listing.type = _check_type(p(request, "type"), listing.type)
    if p(request, "pricing_mode") is not None:
        listing.pricing_mode = _check_pricing_mode(p(request, "pricing_mode"),
                                                   listing.pricing_mode)
    if p(request, "category_id") not in (None, ""):
        category = Category.objects.filter(pk=int(opt_num(request, "category_id",
                                                          integer=True))).first()
        if category is None:
            raise ValueError("分类不存在")
        listing.category = category
    elif p(request, "category_id") == "":
        listing.category = None
    if p(request, "tags") is not None:
        listing.tags = parse_tags(request)
    listing.remark = opt_str(request, "remark", listing.remark)
    _audit(listing, "update", request.user)
    listing.save()
    return ok(listing_dict(listing))


@endpoint()
def listing_delete(request, pk):
    """删除应用（仅维护者；存在有效安装时拒绝，避免用户端突然失联）。"""
    listing = get_listing(pk, request.user, write=True)
    if listing.status == "published":
        raise ValueError("已上架应用需先下架才能删除")
    active = Install.objects.filter(listing=listing,
                                    status__in=("installed", "disabled")).count()
    if active:
        raise ValueError(f"仍有 {active} 个有效安装，不能删除应用")
    lid, code = listing.id, listing.code
    listing.delete()
    return ok({"deleted": True, "id": lid, "code": code})


@endpoint()
def listing_submit(request, pk):
    """提交审核：发布者需认证、至少一个版本且依赖清单可解析。"""
    listing = get_listing(pk, request.user, write=True)
    if listing.status not in ("draft", "delisted"):
        raise ValueError(f"当前状态 {listing.status} 不能提交审核")
    _ensure_publisher_can_publish(listing)
    version = services.best_any_version(listing)
    if version is None:
        raise ValueError("请先创建至少一个版本再提交审核")
    services.parse_version(version.version, "版本号")
    services.parse_version(version.min_platform_version, "平台版本下限")
    issues = services.ensure_no_broken_dependency(listing, version)
    if issues:
        raise ValueError("依赖检查未通过: " + "；".join(
            f"{item['code']} {item['message']}" for item in issues[:5]
        ))
    listing.status = "reviewing"
    listing.submitted_at = timezone.now()
    listing.review_note = opt_str(request, "note", listing.review_note)
    _audit(listing, "submit", request.user, listing.review_note)
    listing.save()
    return ok({"id": listing.id, "status": listing.status,
               "submitted_at": iso(listing.submitted_at)})


@endpoint()
def listing_withdraw(request, pk):
    """撤回审核（维护者；reviewing → draft，允许修改后重新提交）。"""
    listing = get_listing(pk, request.user, write=True)
    if listing.status != "reviewing":
        raise ValueError("只有审核中的应用可以撤回")
    listing.status = "draft"
    _audit(listing, "withdraw", request.user)
    listing.save()
    return ok({"id": listing.id, "status": listing.status})


@endpoint()
def listing_approve(request, pk):
    """审核通过并上架（仅管理员；自动发布最高版本）。"""
    require_staff(request.user, "仅管理员可审核")
    with transaction.atomic():
        listing = get_listing(pk, request.user)
        if listing.status != "reviewing":
            raise ValueError(f"当前状态 {listing.status} 不能审核通过")
        version = services.best_any_version(listing)
        if version is None:
            raise ValueError("应用没有可发布的版本")
        if version.status != "published":
            _publish_version_row(version, request.user)
        listing.status = "published"
        listing.published_at = timezone.now()
        listing.delisted_at = None
        listing.review_note = opt_str(request, "note", "")
        listing.latest_version = _latest_published(listing)
        _audit(listing, "approve", request.user, listing.review_note)
        listing.save()
        services.emit_event(
            listing, "listing.published",
            {"listing": listing.code, "version": version.version},
            request.user,
        )
    return ok({"id": listing.id, "status": listing.status,
               "published_at": iso(listing.published_at),
               "latest_version": version_brief(listing.latest_version)})


@endpoint()
def listing_reject(request, pk):
    """驳回审核（仅管理员；必填理由，回到草稿态）。"""
    require_staff(request.user, "仅管理员可审核")
    listing = get_listing(pk, request.user)
    reason = req_str(request, "reason", max_len=2000).strip()
    if listing.status != "reviewing":
        raise ValueError(f"当前状态 {listing.status} 不能驳回")
    listing.status = "draft"
    listing.review_note = reason
    _audit(listing, "reject", request.user, reason)
    listing.save()
    return ok({"id": listing.id, "status": listing.status, "reason": reason})


@endpoint()
def listing_publish(request, pk):
    """重新上架（下架应用由维护者直接上架；暂停应用仅管理员可恢复）。"""
    listing = get_listing(pk, request.user, write=True)
    if listing.status == "published":
        raise ValueError("应用已经是上架状态")
    if listing.status == "draft":
        raise ValueError("草稿应用需先提交审核")
    if listing.status == "reviewing":
        raise ValueError("审核中的应用不能直接上架")
    if listing.status == "suspended":
        require_staff(request.user, "暂停应用仅管理员可恢复上架")
    _ensure_publisher_can_publish(listing)
    latest = _latest_published(listing)
    if latest is None:
        raise ValueError("应用没有已发布版本，不能上架")
    listing.status = "published"
    listing.published_at = listing.published_at or timezone.now()
    listing.delisted_at = None
    listing.latest_version = latest
    listing.review_note = opt_str(request, "note", "")
    _audit(listing, "publish", request.user, listing.review_note)
    listing.save()
    services.emit_event(listing, "listing.published",
                        {"listing": listing.code, "version": latest.version},
                        request.user)
    return ok({"id": listing.id, "status": listing.status,
               "latest_version": version_brief(latest)})


@endpoint()
def listing_delist(request, pk):
    """下架应用（维护者/管理员；已上架 → 已下架）。"""
    listing = get_listing(pk, request.user, write=True)
    if listing.status != "published":
        raise ValueError(f"当前状态 {listing.status} 不能下架")
    reason = opt_str(request, "reason", "", max_len=300)
    listing.status = "delisted"
    listing.delisted_at = timezone.now()
    listing.review_note = reason
    _audit(listing, "delist", request.user, reason)
    listing.save()
    services.emit_event(listing, "listing.delisted",
                        {"listing": listing.code, "reason": reason}, request.user)
    return ok({"id": listing.id, "status": listing.status,
               "delisted_at": iso(listing.delisted_at)})


@endpoint()
def listing_suspend(request, pk):
    """暂停应用（仅管理员；违规下架前置动作，保留版本与安装数据）。"""
    require_staff(request.user, "仅管理员可暂停应用")
    listing = get_listing(pk, request.user)
    if listing.status == "suspended":
        raise ValueError("应用已处于暂停状态")
    reason = req_str(request, "reason", max_len=300).strip()
    listing.status = "suspended"
    listing.review_note = reason
    _audit(listing, "suspend", request.user, reason)
    listing.save()
    services.emit_event(listing, "listing.suspended",
                        {"listing": listing.code, "reason": reason}, request.user)
    return ok({"id": listing.id, "status": listing.status, "reason": reason})


@endpoint()
def listing_clone(request, pk):
    """克隆应用（复制版本/定价/截图，不复制安装、订单与评价）。"""
    source = get_listing(pk, request.user)
    ensure_listing_writable(source, request.user)
    with transaction.atomic():
        suffix = 1
        code = f"{source.code}-copy"
        while Listing.objects.filter(code=code).exists():
            suffix += 1
            code = f"{source.code}-copy-{suffix}"
        clone = Listing.objects.create(
            owner=source.owner,
            publisher=source.publisher,
            category=source.category,
            code=code[:100],
            name=f"{source.name[:180]}（副本）",
            summary=source.summary,
            description=source.description,
            icon=source.icon,
            type=source.type,
            status="draft",
            pricing_mode=source.pricing_mode,
            tags=list(source.tags or []),
            audit={"events": [{"action": "clone", "from": source.code,
                               "by": request.user.username,
                               "at": timezone.now().isoformat()}]},
        )
        for version in source.mp_versions.all().order_by("id"):
            ListingVersion.objects.create(
                owner=clone.owner,
                listing=clone,
                version=version.version,
                changelog=version.changelog,
                min_platform_version=version.min_platform_version,
                manifest=version.manifest or {},
                package_size=version.package_size,
                checksum=version.checksum,
                status="draft",
                breaking=version.breaking,
            )
        try:
            pricing = source.mp_pricing
        except Pricing.DoesNotExist:
            pricing = None
        if pricing is not None:
            Pricing.objects.create(
                owner=clone.owner,
                listing=clone,
                mode=pricing.mode,
                price=pricing.price,
                currency=pricing.currency,
                trial_days=pricing.trial_days,
                period=pricing.period,
                active=pricing.active,
            )
        for shot in source.mp_screenshots.all():
            Screenshot.objects.create(
                owner=clone.owner,
                listing=clone,
                file_name=shot.file_name,
                file_url=shot.file_url,
                mime_type=shot.mime_type,
                file_size=shot.file_size,
                width=shot.width,
                height=shot.height,
                order=shot.order,
                caption=shot.caption,
            )
    return ok(listing_dict(clone))


@endpoint()
def listing_feature(request, pk):
    """设置推荐位（仅管理员；featured + featured_rank，rank 越小越靠前）。"""
    require_staff(request.user, "仅管理员可设置推荐位")
    listing = get_listing(pk, request.user)
    featured = opt_bool(request, "featured", True)
    rank = int(opt_num(request, "featured_rank", listing.featured_rank,
                       minimum=0, maximum=100000, integer=True))
    if featured and listing.status != "published":
        raise ValueError("只有已上架应用可以进入推荐位")
    listing.featured = featured
    listing.featured_rank = rank if featured else 0
    _audit(listing, "feature", request.user, f"featured={featured} rank={rank}")
    listing.save()
    return ok({"id": listing.id, "featured": listing.featured,
               "featured_rank": listing.featured_rank})


@endpoint()
def listing_set_tags(request, pk):
    """设置应用标签（维护者；整体替换，最多 20 个）。"""
    listing = get_listing(pk, request.user, write=True)
    tags = parse_tags(request, max_items=20)
    listing.tags = tags
    _audit(listing, "tags", request.user, ",".join(tags))
    listing.save(update_fields=["tags", "audit", "updated_at"])
    return ok({"id": listing.id, "tags": listing.tags})


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------


@endpoint(("GET", "POST"))
def listing_versions(request, pk):
    """版本列表（维护者看全部，其他用户只看已发布）或创建版本草稿。"""
    listing = get_listing(pk, request.user)
    if request.method == "GET":
        ensure_listing_visible(listing, request.user)
        queryset = listing.mp_versions.all().order_by("-id")
        if not can_write_listing(request.user, listing):
            queryset = queryset.filter(status="published")
        status = opt_str(request, "status").strip()
        if status:
            if status not in VERSION_STATUS_VALUES:
                raise ValueError(f"status 支持 {'/'.join(VERSION_STATUS_VALUES)}")
            queryset = queryset.filter(status=status)
        query = opt_str(request, "q").strip()
        if query:
            queryset = queryset.filter(version__icontains=query)
        page, size = page_params(request)
        total = queryset.count()
        start = (page - 1) * size
        items = [version_dict(v, with_listing=False)
                 for v in queryset[start:start + size]]
        return ok(page_payload(items, total, page, size))

    ensure_listing_writable(listing, request.user)
    version_text = req_str(request, "version", max_len=40).strip()
    services.parse_version(version_text, "版本号")
    if listing.mp_versions.filter(version=version_text).exists():
        raise ValueError(f"版本 {version_text} 已存在")
    min_platform = opt_str(request, "min_platform_version", "3.0.0").strip()
    services.parse_version(min_platform, "平台版本下限")
    manifest = _manifest_value(request)
    package_size = int(opt_num(request, "package_size", 0, minimum=0,
                               maximum=10 ** 12, integer=True))
    checksum = opt_str(request, "checksum", "", max_len=128).strip() \
        or _checksum(listing, version_text, manifest)
    # 只与「比新版本低」的最高已发布版本比较，避免维护分支版本（如 1.2.0）
    # 被更高的主线版本（2.0.0）误判为破坏性升级
    previous = services.best_version_for_platform(
        listing, None, expression=f"<{version_text}")
    breaking = opt_bool(request, "breaking", False)
    if previous is not None:
        try:
            breaking = breaking or services.is_breaking_change(previous.version, version_text)
        except ValueError:
            breaking = bool(breaking)
    version = ListingVersion.objects.create(
        owner=request.user,
        listing=listing,
        version=version_text,
        changelog=opt_str(request, "changelog"),
        min_platform_version=min_platform,
        manifest=manifest,
        package_size=package_size,
        checksum=checksum,
        status="draft",
        breaking=breaking,
    )
    return ok(version_dict(version))


def can_write_listing(user, listing):
    """版本列表复用的写权限判定（避免重复导入 common 私有逻辑）。"""
    from .common import can_manage_listing

    return can_manage_listing(user, listing)


@endpoint(("GET",))
def version_detail(request, pk):
    """版本详情（未上架应用的版本仅维护者可见）。"""
    version = get_version(pk, request.user)
    ensure_listing_visible(version.listing, request.user)
    data = version_dict(version)
    data["satisfies_platform"] = services.platform_compatible(
        version, services.platform_version_value())
    data["checks"] = services.explain_satisfies(
        version.version, f">={version.version}") if services.is_valid_version(version.version) else {}
    return ok(data)


@endpoint()
def version_update(request, pk):
    """更新版本草稿（版本号不可改；清单/说明/平台下限可改）。"""
    version = get_version(pk, request.user, write=True)
    if version.status != "draft":
        raise ValueError("只有草稿版本可以编辑")
    if p(request, "changelog") is not None:
        version.changelog = str(p(request, "changelog"))
    if p(request, "min_platform_version") not in (None, ""):
        minimum = str(p(request, "min_platform_version")).strip()
        services.parse_version(minimum, "平台版本下限")
        version.min_platform_version = minimum
    if p(request, "manifest") is not None:
        version.manifest = _manifest_value(request, version.manifest)
    if p(request, "package_size") not in (None, ""):
        version.package_size = int(opt_num(request, "package_size", version.package_size,
                                           minimum=0, maximum=10 ** 12, integer=True))
    if p(request, "checksum") is not None:
        version.checksum = opt_str(request, "checksum", "", max_len=128).strip() \
            or _checksum(version.listing, version.version, version.manifest)
    if version.checksum == "":
        version.checksum = _checksum(version.listing, version.version, version.manifest)
    version.save()
    return ok(version_dict(version))


@endpoint()
def version_publish(request, pk):
    """发布版本（维护者；依赖必须可解析，发布后自动刷新应用最新版本）。"""
    version = get_version(pk, request.user, write=True)
    if version.status == "published":
        raise ValueError("版本已发布")
    if version.status == "delisted":
        raise ValueError("已下架版本不能重新发布，请创建新版本")
    listing = version.listing
    issues = services.ensure_no_broken_dependency(listing, version)
    if issues:
        raise ValueError("依赖检查未通过: " + "；".join(
            f"{item['code']} {item['message']}" for item in issues[:5]
        ))
    # 发布时的破坏性判定同样只看更低版本，防止分支版本被主线版本带偏
    previous = services.best_version_for_platform(
        listing, None, expression=f"<{version.version}")
    with transaction.atomic():
        if previous is not None:
            try:
                version.breaking = version.breaking or services.is_breaking_change(
                    previous.version, version.version)
            except ValueError:
                pass
        _publish_version_row(version, request.user)
        listing = Listing.objects.select_for_update().get(pk=listing.pk)
        latest = _latest_published(listing)
        listing.latest_version = latest
        listing.save(update_fields=["latest_version", "updated_at"])
        services.emit_event(
            listing, "version.published",
            {"listing": listing.code, "version": version.version,
             "breaking": version.breaking},
            request.user,
        )
    return ok(version_dict(version))


@endpoint()
def version_delist(request, pk):
    """下架版本（维护者；已下架版本不参与安装解析）。"""
    version = get_version(pk, request.user, write=True)
    if version.status != "published":
        raise ValueError("只有已发布版本可以下架")
    if version.status == "delisted":
        raise ValueError("版本已下架")
    version.status = "delisted"
    version.save(update_fields=["status", "updated_at"])
    listing = version.listing
    listing.latest_version = _latest_published(listing)
    listing.save(update_fields=["latest_version", "updated_at"])
    return ok({"id": version.id, "status": version.status,
               "latest_version": version_brief(listing.latest_version)})


@endpoint()
def version_delete(request, pk):
    """删除版本（仅草稿；已发布/已下架版本需保留审计痕迹）。"""
    version = get_version(pk, request.user, write=True)
    if version.status != "draft":
        raise ValueError("只有草稿版本可以删除，已发布版本请先下架")
    vid, text = version.id, version.version
    version.delete()
    return ok({"deleted": True, "id": vid, "version": text})


@endpoint(("GET",))
def versions_compare(request):
    """版本对比：差异级别、破坏性、清单依赖与包大小变化。"""
    listing_id = opt_num(request, "listing_id", integer=True)
    from_id = opt_num(request, "from_id", integer=True)
    to_id = opt_num(request, "to_id", integer=True)
    from_raw = opt_str(request, "from").strip()
    to_raw = opt_str(request, "to").strip()

    versions = []
    for version_id in (from_id, to_id):
        if version_id:
            row = ListingVersion.objects.select_related("listing").filter(
                pk=int(version_id)).first()
            if row is None:
                raise ValueError("版本不存在")
            versions.append(row)
    if len(versions) == 2:
        if versions[0].listing_id != versions[1].listing_id:
            raise ValueError("只能对比同一应用的两个版本")
        listing = versions[0].listing
        left, right = versions
    else:
        if not listing_id:
            raise ValueError("按版本号对比时需提供 listing_id")
        listing = Listing.objects.filter(pk=int(listing_id)).first()
        if listing is None:
            raise ValueError("应用不存在")
        if not from_raw or not to_raw:
            raise ValueError("请提供 from/to 版本号或 from_id/to_id")
        left = listing.mp_versions.filter(version=from_raw).first()
        right = listing.mp_versions.filter(version=to_raw).first()
        if left is None or right is None:
            raise ValueError("对比的版本不存在")
    diff = services.diff_versions(left.version, right.version)
    left_requires = {x.get("code"): x.get("range")
                     for x in ((left.manifest or {}).get("requires") or [])
                     if isinstance(x, dict)}
    right_requires = {x.get("code"): x.get("range")
                      for x in ((right.manifest or {}).get("requires") or [])
                      if isinstance(x, dict)}
    added = sorted(set(right_requires) - set(left_requires))
    removed = sorted(set(left_requires) - set(right_requires))
    changed = sorted(
        code for code in set(left_requires) & set(right_requires)
        if left_requires[code] != right_requires[code]
    )
    return ok({
        "listing": {"id": listing.id, "code": listing.code, "name": listing.name},
        "from": version_dict(left, with_listing=False),
        "to": version_dict(right, with_listing=False),
        "diff": diff,
        "requires": {
            "added": [{"code": c, "range": right_requires[c]} for c in added],
            "removed": [{"code": c, "range": left_requires[c]} for c in removed],
            "changed": [
                {"code": c, "from": left_requires[c], "to": right_requires[c]}
                for c in changed
            ],
        },
        "package_size_delta": right.package_size - left.package_size,
        "changelog": right.changelog,
    })


@endpoint(("GET",))
def listing_upgrade_check(request, pk):
    """升级检查：当前版本 → 最新可升级版本、变更说明与破坏性标记。"""
    listing = get_listing(pk, request.user)
    ensure_listing_visible(listing, request.user)
    current = req_str(request, "current_version", max_len=40).strip()
    platform_version = opt_str(request, "platform_version",
                               services.platform_version_value()).strip()
    services.parse_version(platform_version, "平台版本")
    result = services.check_upgrade(listing, current, platform_version)
    return ok(result)


# 接口计数（与 urls.py 的断言对应）。
LISTING_ENDPOINT_COUNT = 24
