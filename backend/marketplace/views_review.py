# -*- coding: utf-8 -*-
"""应用市场 · 评价接口（11 个）。

评价治理语义：
- 评价先进入待审（pending），由应用维护者/管理员发布后才计入评分；
- 隐藏不删除数据（可恢复），每次隐藏/发布/删除都会重算加权评分与分布；
- 「有用」一人一票且不能给自己投票，投票会触发评分重算（权重含有用数）；
- 回复权限归应用维护者/管理员与评价作者本人，避免无关账号刷回复。
"""
from django.db import transaction

from devtools.common import (endpoint, ok, opt_bool, opt_num, opt_str, p,
                             req_num, req_str)

from . import services
from .common import (can_manage_listing, ensure_listing_visible, get_listing,
                     get_reply, get_review, is_staff_user, paginate_queryset,
                     require_staff)
from .models import REVIEW_STATUS_VALUES, Review, ReviewHelpful, ReviewReply
from .serializers import (iso, listing_brief, reply_dict, review_dict)


def _visible_reviews(listing, user):
    """评价可见集合：普通用户只看已发布；维护者/管理员看全部。"""
    queryset = Review.objects.filter(listing=listing).select_related("owner")
    if can_manage_listing(user, listing):
        return queryset
    return queryset.filter(status="published")


def _recalc(listing):
    """重算评分（隐藏/发布/删除/投票后调用）。"""
    return services.aggregate_rating(listing, commit=True)


def _mark_verified(review):
    """已购买标记：存在已支付订单才算（退款后不再算）。"""
    review.verified_purchase = review.listing.mp_purchases.filter(
        owner=review.owner, payment_status="paid").exists()
    return review.verified_purchase


@endpoint(("GET", "POST"))
def listing_reviews(request, pk):
    """应用评价列表（已发布评价公开）或发表评价（先进入待审）。"""
    listing = get_listing(pk, request.user)
    ensure_listing_visible(listing, request.user)
    if request.method == "GET":
        queryset = _visible_reviews(listing, request.user).order_by("-created_at")
        status = opt_str(request, "status").strip()
        if status:
            if status not in REVIEW_STATUS_VALUES:
                raise ValueError(f"status 支持 {'/'.join(REVIEW_STATUS_VALUES)}")
            queryset = queryset.filter(status=status)
        data = paginate_queryset(
            request, queryset, review_dict,
            search_fields=("title", "content"), status_field=None,
        )
        data["summary"] = services.aggregate_rating(listing, commit=False)
        return ok(data)

    rating = int(req_num(request, "rating", minimum=1, maximum=5, integer=True))
    if Review.objects.filter(owner=request.user, listing=listing).exists():
        raise ValueError("你已经评价过该应用，可修改原评价")
    review = Review.objects.create(
        owner=request.user,
        listing=listing,
        rating=rating,
        title=opt_str(request, "title", max_len=200),
        content=opt_str(request, "content"),
        status="pending",
        verified_purchase=listing.mp_purchases.filter(
            owner=request.user, payment_status="paid").exists(),
        remark=opt_str(request, "remark"),
    )
    return ok(review_dict(review))


@endpoint(("GET",))
def reviews_mine(request):
    """我的评价（含待审/已隐藏，支持 q/status 分页）。"""
    queryset = (Review.objects.filter(owner=request.user)
                .select_related("listing", "listing__publisher")
                .order_by("-created_at"))
    return ok(paginate_queryset(
        request, queryset, review_dict,
        search_fields=("listing__name", "listing__code", "title", "content"),
    ))


@endpoint(("GET",))
def review_detail(request, pk):
    """评价详情（含回复；未发布评价仅作者与维护者可见）。"""
    review = get_review(pk, request.user)
    if review.status != "published" \
            and review.owner_id != request.user.id \
            and not can_manage_listing(request.user, review.listing):
        raise ValueError("评价未发布")
    data = review_dict(review, with_replies=True)
    data["listing"] = listing_brief(review.listing)
    return ok(data)


@endpoint()
def review_update(request, pk):
    """修改自己的评价（隐藏状态不可改；已发布评价改动后重算评分）。"""
    review = get_review(pk, request.user, write=True)
    if review.owner_id != request.user.id:
        raise ValueError("只能修改自己的评价")
    if review.status == "hidden":
        raise ValueError("评价已被隐藏，不能修改")
    if p(request, "rating") not in (None, ""):
        review.rating = int(req_num(request, "rating", review.rating,
                                    minimum=1, maximum=5, integer=True))
    if p(request, "title") is not None:
        review.title = str(p(request, "title"))[:200]
    if p(request, "content") is not None:
        review.content = str(p(request, "content"))
    _mark_verified(review)
    review.save()
    if review.status == "published":
        _recalc(review.listing)
    return ok(review_dict(review))


@endpoint()
def review_delete(request, pk):
    """删除评价（作者/应用维护者/管理员；删除后重算评分）。"""
    review = get_review(pk, request.user, write=True)
    listing = review.listing
    rid = review.id
    with transaction.atomic():
        review.delete()
        _recalc(listing)
    return ok({"deleted": True, "id": rid})


@endpoint()
def review_publish(request, pk):
    """发布评价（应用维护者/管理员；待审 → 已发布并计入评分）。"""
    review = get_review(pk, request.user, write=True)
    if not can_manage_listing(request.user, review.listing):
        raise ValueError("仅应用维护者或管理员可发布评价")
    if review.status == "published":
        return ok({"id": review.id, "status": review.status, "changed": False})
    if review.status == "hidden":
        raise ValueError("已隐藏评价不能直接发布，请先恢复")
    with transaction.atomic():
        review.status = "published"
        _mark_verified(review)
        review.save(update_fields=["status", "verified_purchase", "updated_at"])
        summary = _recalc(review.listing)
        services.emit_event(
            review.listing, "review.published",
            {"review_id": review.id, "rating": review.rating,
             "listing": review.listing.code},
            request.user,
        )
    return ok({"id": review.id, "status": review.status, "rating_summary": summary})


@endpoint()
def review_hide(request, pk):
    """隐藏评价（应用维护者/管理员；必填原因，隐藏后重算评分）。"""
    review = get_review(pk, request.user, write=True)
    if not can_manage_listing(request.user, review.listing):
        raise ValueError("仅应用维护者或管理员可隐藏评价")
    reason = req_str(request, "reason", max_len=300).strip()
    if review.status == "hidden":
        raise ValueError("评价已隐藏")
    with transaction.atomic():
        review.status = "hidden"
        review.hidden_reason = reason
        review.save(update_fields=["status", "hidden_reason", "updated_at"])
        summary = _recalc(review.listing)
        services.emit_event(
            review.listing, "review.hidden",
            {"review_id": review.id, "reason": reason},
            request.user,
        )
    return ok({"id": review.id, "status": review.status,
               "reason": reason, "rating_summary": summary})


@endpoint()
def review_helpful(request, pk):
    """给评价点「有用」（一人一票；不能给自己投票；触发评分重算）。"""
    review = get_review(pk, request.user)
    if review.status != "published":
        raise ValueError("只能给已发布评价投票")
    if review.owner_id == request.user.id:
        raise ValueError("不能给自己的评价投票")
    existing = ReviewHelpful.objects.filter(owner=request.user, review=review).first()
    if existing is not None:
        # 再点一次视为取消，符合常见交互，同时保证计数不虚高
        with transaction.atomic():
            existing.delete()
            review.helpful_count = max(0, review.helpful_count - 1)
            review.save(update_fields=["helpful_count", "updated_at"])
            _recalc(review.listing)
        return ok({"id": review.id, "helpful": False,
                   "helpful_count": review.helpful_count})
    with transaction.atomic():
        ReviewHelpful.objects.create(owner=request.user, review=review)
        review.helpful_count = ReviewHelpful.objects.filter(review=review).count()
        review.save(update_fields=["helpful_count", "updated_at"])
        _recalc(review.listing)
    return ok({"id": review.id, "helpful": True, "helpful_count": review.helpful_count})


@endpoint(("GET", "POST"))
def review_replies(request, pk):
    """评价回复列表或新增回复（作者本人/应用维护者/管理员可回复）。"""
    review = get_review(pk, request.user)
    if request.method == "GET":
        if review.status != "published" \
                and review.owner_id != request.user.id \
                and not can_manage_listing(request.user, review.listing):
            raise ValueError("评价未发布")
        queryset = review.mp_replies.select_related("owner").order_by("created_at")
        return ok(paginate_queryset(
            request, queryset, reply_dict,
            search_fields=("content",), status_field=None,
        ))
    allowed = (
        review.owner_id == request.user.id
        or can_manage_listing(request.user, review.listing)
    )
    if not allowed:
        raise ValueError("只有评价作者、应用维护者或管理员可以回复")
    content = req_str(request, "content").strip()
    if not content:
        raise ValueError("回复内容不能为空")
    with transaction.atomic():
        reply = ReviewReply.objects.create(
            owner=request.user,
            review=review,
            content=content,
        )
        review.reply_count = ReviewReply.objects.filter(review=review).count()
        review.save(update_fields=["reply_count", "updated_at"])
    return ok(reply_dict(reply))


@endpoint()
def reply_delete(request, pk):
    """删除回复（回复人/评价作者/应用维护者/管理员；同步回复数）。"""
    reply = get_reply(pk, request.user, write=True)
    review = reply.review
    rid = reply.id
    with transaction.atomic():
        reply.delete()
        review.reply_count = ReviewReply.objects.filter(review=review).count()
        review.save(update_fields=["reply_count", "updated_at"])
    return ok({"deleted": True, "id": rid, "reply_count": review.reply_count})


@endpoint(("GET",))
def listing_rating(request, pk):
    """应用评分聚合：加权平均、1~5 星分布与各状态评价数。"""
    listing = get_listing(pk, request.user)
    ensure_listing_visible(listing, request.user)
    summary = services.aggregate_rating(listing, commit=False)
    summary["by_status"] = {
        row["status"]: row["c"] for row in
        Review.objects.filter(listing=listing).values("status").annotate(
            c=services.Count("id"))
    }
    summary["listing"] = {
        "id": listing.id,
        "code": listing.code,
        "name": listing.name,
        "rating": float(listing.rating or 0),
        "rating_count": listing.rating_count,
    }
    return ok(summary)


REVIEW_ENDPOINT_COUNT = 11
