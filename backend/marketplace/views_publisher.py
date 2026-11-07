# -*- coding: utf-8 -*-
"""应用市场 · 发布者接口（9 个）。

发布者认证与暂停是平台治理动作：
- 认证（verify）后才能提交应用审核；
- 暂停（suspend）会级联暂停其已上架应用，避免违规主体继续分发；
- 收入概览按订单实时计算，不落冗余汇总表，保证与账目一致。
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_str)

from . import services
from .common import (is_staff_user, paginate_queryset, parse_dict, parse_tags,
                     require_owner, require_staff, valid_email, valid_slug,
                     get_publisher)
from .models import (
    PUBLISHER_STATUS_VALUES,
    Install,
    Listing,
    Publisher,
)
from .serializers import iso, publisher_dict


def _share_value(request, default):
    """分成比例校验：0~100，保留两位小数。"""
    raw = p(request, "revenue_share")
    if raw in (None, ""):
        return default
    value = opt_num(request, "revenue_share", default, minimum=0, maximum=100)
    return Decimal(str(round(value, 2)))


def _unique_slug(slug, exclude=None):
    """标识唯一性预检（避免并发下把 IntegrityError 暴露成 422）。"""
    queryset = Publisher.objects.filter(slug=slug)
    if exclude is not None:
        queryset = queryset.exclude(pk=exclude.pk)
    if queryset.exists():
        raise ValueError(f"发布者标识 {slug} 已被占用")
    return slug


def _fallback_slug():
    """未提供标识时按时间戳生成可读 slug（中文名无法直接转写）。"""
    return f"pub-{timezone.now():%Y%m%d%H%M%S}"


@endpoint(("GET", "POST"))
def publishers(request):
    """发布者列表（q/status 分页）或创建发布者（当前账号成为所有者）。"""
    if request.method == "GET":
        queryset = Publisher.objects.select_related("owner").order_by("-created_at")
        return ok(paginate_queryset(
            request, queryset, publisher_dict,
            search_fields=("name", "slug", "summary", "contact_email"),
        ))
    name = req_str(request, "name", max_len=120).strip()
    if not name:
        raise ValueError("发布者名称不能为空")
    slug = valid_slug(opt_str(request, "slug").strip() or _fallback_slug())
    _unique_slug(slug)
    publisher = Publisher.objects.create(
        owner=request.user,
        name=name[:120],
        slug=slug,
        summary=opt_str(request, "summary", max_len=500),
        website=opt_str(request, "website", max_len=300),
        contact_email=valid_email(opt_str(request, "contact_email")),
        status="pending",
        revenue_share=_share_value(request, Decimal("70.00")),
        settlement_info=parse_dict(request, "settlement_info"),
        remark=opt_str(request, "remark"),
    )
    return ok(publisher_dict(publisher))


@endpoint(("GET",))
def publishers_mine(request):
    """我拥有的发布者（含每个发布者的应用数与安装量）。"""
    queryset = (Publisher.objects.filter(owner=request.user)
                .select_related("owner").order_by("-created_at"))
    items = []
    for publisher in queryset:
        data = publisher_dict(publisher)
        listings = publisher.mp_publisher_listings.all()
        data["stats"] = {
            "listings": listings.count(),
            "published_listings": listings.filter(status="published").count(),
            "installs": int(listings.aggregate(total=Sum("install_count"))["total"] or 0),
        }
        items.append(data)
    return ok({"items": items, "count": len(items)})


@endpoint(("GET",))
def publisher_detail(request, pk):
    """发布者详情（公开只读，含应用数/安装量统计）。"""
    publisher = get_publisher(pk)
    data = publisher_dict(publisher)
    listings = publisher.mp_publisher_listings.all()
    data["stats"] = {
        "listings": listings.count(),
        "published_listings": listings.filter(status="published").count(),
        "installs": int(listings.aggregate(total=Sum("install_count"))["total"] or 0),
        "reviews": listings.aggregate(total=Sum("rating_count"))["total"] or 0,
    }
    data["top_listings"] = [
        {"id": row.id, "code": row.code, "name": row.name,
         "install_count": row.install_count, "rating": float(row.rating or 0)}
        for row in listings.filter(status="published").order_by("-install_count")[:10]
    ]
    return ok(data)


@endpoint()
def publisher_update(request, pk):
    """更新发布者资料（名称/简介/官网/邮箱/分成比例/结算信息）。"""
    publisher = get_publisher(pk, request.user, write=True)
    publisher.name = opt_str(request, "name", publisher.name, max_len=120).strip() or publisher.name
    summary = p(request, "summary")
    if summary is not None:
        publisher.summary = str(summary)[:500]
    website = p(request, "website")
    if website is not None:
        publisher.website = str(website)[:300]
    email_raw = p(request, "contact_email")
    if email_raw is not None:
        publisher.contact_email = valid_email(email_raw)
    if p(request, "revenue_share") not in (None, ""):
        # 分成比例涉及结算，仅管理员可调整；owner 只能看到当前值
        require_staff(request.user, "仅管理员可调整分成比例")
        publisher.revenue_share = _share_value(request, publisher.revenue_share)
    settlement = p(request, "settlement_info")
    if settlement is not None:
        publisher.settlement_info = parse_dict(request, "settlement_info")
    publisher.remark = opt_str(request, "remark", publisher.remark)
    publisher.save()
    return ok(publisher_dict(publisher))


@endpoint()
def publisher_delete(request, pk):
    """删除发布者（仅所有者，且名下不能还有应用）。"""
    publisher = get_publisher(pk, request.user, write=True)
    if publisher.mp_publisher_listings.exists():
        raise ValueError("该发布者名下仍有应用，请先删除或转移应用")
    if publisher.mp_webhooks.exists():
        raise ValueError("该发布者仍有 Webhook 订阅，请先删除订阅")
    pid = publisher.id
    publisher.delete()
    return ok({"deleted": True, "id": pid})


@endpoint()
def publisher_verify(request, pk):
    """认证发布者（仅管理员；已认证的重复调用幂等）。"""
    require_staff(request.user, "仅管理员可认证发布者")
    publisher = get_publisher(pk)
    if publisher.status == "verified":
        return ok({"id": publisher.id, "status": publisher.status, "changed": False})
    publisher.status = "verified"
    publisher.verified_at = timezone.now()
    publisher.suspended_reason = ""
    publisher.save(update_fields=["status", "verified_at", "suspended_reason", "updated_at"])
    return ok({"id": publisher.id, "status": publisher.status, "changed": True,
               "verified_at": iso(publisher.verified_at)})


@endpoint()
def publisher_suspend(request, pk):
    """暂停发布者（仅管理员；级联暂停其已上架应用并记录原因）。"""
    require_staff(request.user, "仅管理员可暂停发布者")
    reason = req_str(request, "reason", max_len=300).strip()
    with transaction.atomic():
        publisher = get_publisher(pk)
        if publisher.status == "suspended":
            raise ValueError("该发布者已处于暂停状态")
        publisher.status = "suspended"
        publisher.suspended_reason = reason
        publisher.save(update_fields=["status", "suspended_reason", "updated_at"])
        affected = []
        for listing in publisher.mp_publisher_listings.filter(status="published"):
            listing.status = "suspended"
            listing.review_note = f"发布者暂停：{reason}"
            listing.save(update_fields=["status", "review_note", "updated_at"])
            services.emit_event(
                listing, "listing.suspended",
                {"reason": reason, "publisher_id": publisher.id},
                request.user,
            )
            affected.append(listing.code)
    return ok({"id": publisher.id, "status": publisher.status,
               "suspended_listings": affected, "count": len(affected)})


@endpoint(("GET",))
def publisher_overview(request, pk):
    """发布者概览：应用数、安装量、评价与收入分成（所有者/管理员）。"""
    publisher = get_publisher(pk)
    require_owner(request.user, publisher, "无权查看该发布者的经营数据")
    listings = publisher.mp_publisher_listings.all()
    by_status = {row["status"]: row["c"] for row in
                 listings.values("status").annotate(c=Count("id"))}
    revenue = services.publisher_revenue(publisher)
    active_installs = Install.objects.filter(
        listing__publisher=publisher, status__in=("installed", "disabled"),
    ).count()
    return ok({
        "publisher": publisher_dict(publisher),
        "listings": {
            "total": listings.count(),
            "by_status": by_status,
            "published": by_status.get("published", 0),
        },
        "installs": {
            "active": active_installs,
            "total_counters": int(listings.aggregate(total=Sum("install_count"))["total"] or 0),
        },
        "ratings": {
            "reviews": int(listings.aggregate(total=Sum("rating_count"))["total"] or 0),
            "average": round(
                float(listings.aggregate(value=Sum("rating"))["value"] or 0)
                / max(listings.filter(rating_count__gt=0).count(), 1), 2
            ),
        },
        "revenue": revenue,
    })


@endpoint()
def publisher_settlement(request, pk):
    """更新结算信息（所有者；仅接受本地模拟的银行/结算周期字段）。"""
    publisher = get_publisher(pk, request.user, write=True)
    info = parse_dict(request, "settlement_info", required=True)
    allowed = ("bank_name", "account_name", "account_no", "cycle", "tax_no", "contact")
    cleaned = {key: str(info.get(key, ""))[:200] for key in allowed if info.get(key) is not None}
    if not cleaned:
        raise ValueError("结算信息至少包含 bank_name/account_name/account_no 之一")
    publisher.settlement_info = cleaned
    publisher.save(update_fields=["settlement_info", "updated_at"])
    return ok({"id": publisher.id, "settlement_info": publisher.settlement_info})


# 导出给 urls.py 做接口计数断言使用，避免文档与实现漂移。
PUBLISHER_ENDPOINT_COUNT = 9
