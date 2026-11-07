# -*- coding: utf-8 -*-
"""应用市场路由：102 个接口，全部挂载在 /api/marketplace/ 下。

分组（与 views_*.py 的 *_ENDPOINT_COUNT 对应）：
- 目录 1（catalog，含 endpoint_index）
- 发布者 9（CRUD/认证/暂停/概览/结算）
- 分类 4（列表/树/更新/删除）
- 应用与版本 24（CRUD/审核/上下架/克隆/推荐位/标签/版本/对比/升级检查）
- 安装 8（安装/卸载/启停/配置/升级/解析预演）
- 评价 11（CRUD/发布/隐藏/有用/回复/评分）
- 商业化 12（定价/购买/退款/许可证）
- 开放能力 27（Webhook/事件/合集/举报/截图/兼容标签）
- 统计 6（概览/分类/发布者/趋势/评分/收入）

约定：公开浏览（列表/详情/搜索/合集）只要登录即可读；
审核、认证、暂停、推荐位、分类、举报处置、收入汇总仅 is_staff。
"""
import logging
import traceback

from django.urls import path

from devtools.common import endpoint_index
from marketplace import views_catalog as cat
from marketplace import views_category as ctg
from marketplace import views_commerce as com
from marketplace import views_install as ins
from marketplace import views_listing as lst
from marketplace import views_platform as plat
from marketplace import views_publisher as pub
from marketplace import views_review as rev
from marketplace import views_stats as st


def _catalog(request):
    """目录 + 端点明细（endpoints 为附加字段，失败不影响主响应）。"""
    response = cat.catalog(request)
    try:
        inner = response.data.get("data")
        if isinstance(inner, dict):
            inner["endpoints"] = endpoint_index(urlpatterns, exclude=("",))
    except Exception:  # noqa: BLE001 —— 目录增强失败不能拖垮主目录
        logging.getLogger("marketplace").warning(
            "catalog endpoints 导出失败:\n%s", traceback.format_exc()
        )
    return response


urlpatterns = [
    # ---- 目录（1）----
    path("", _catalog, name="marketplace-catalog"),

    # ---- 发布者（9）----
    path("publishers/", pub.publishers, name="marketplace-publishers"),
    path("publishers/mine/", pub.publishers_mine, name="marketplace-publishers-mine"),
    path("publishers/<int:pk>/", pub.publisher_detail, name="marketplace-publisher-detail"),
    path("publishers/<int:pk>/update/", pub.publisher_update, name="marketplace-publisher-update"),
    path("publishers/<int:pk>/delete/", pub.publisher_delete, name="marketplace-publisher-delete"),
    path("publishers/<int:pk>/verify/", pub.publisher_verify, name="marketplace-publisher-verify"),
    path("publishers/<int:pk>/suspend/", pub.publisher_suspend, name="marketplace-publisher-suspend"),
    path("publishers/<int:pk>/overview/", pub.publisher_overview, name="marketplace-publisher-overview"),
    path("publishers/<int:pk>/settlement/", pub.publisher_settlement,
         name="marketplace-publisher-settlement"),

    # ---- 分类（4）----
    path("categories/", ctg.categories, name="marketplace-categories"),
    path("categories/tree/", ctg.categories_tree, name="marketplace-categories-tree"),
    path("categories/<int:pk>/update/", ctg.category_update, name="marketplace-category-update"),
    path("categories/<int:pk>/delete/", ctg.category_delete, name="marketplace-category-delete"),

    # ---- 应用（18：列表/我的/搜索/详情/更新/删除/提交/撤回/审核/驳回/
    #      上架/下架/暂停/克隆/推荐位/标签/版本/升级检查）----
    path("listings/", lst.listings, name="marketplace-listings"),
    path("listings/mine/", lst.listings_mine, name="marketplace-listings-mine"),
    path("listings/search/", lst.listings_search, name="marketplace-listings-search"),
    path("listings/<int:pk>/", lst.listing_detail, name="marketplace-listing-detail"),
    path("listings/<int:pk>/update/", lst.listing_update, name="marketplace-listing-update"),
    path("listings/<int:pk>/delete/", lst.listing_delete, name="marketplace-listing-delete"),
    path("listings/<int:pk>/submit/", lst.listing_submit, name="marketplace-listing-submit"),
    path("listings/<int:pk>/withdraw/", lst.listing_withdraw, name="marketplace-listing-withdraw"),
    path("listings/<int:pk>/approve/", lst.listing_approve, name="marketplace-listing-approve"),
    path("listings/<int:pk>/reject/", lst.listing_reject, name="marketplace-listing-reject"),
    path("listings/<int:pk>/publish/", lst.listing_publish, name="marketplace-listing-publish"),
    path("listings/<int:pk>/delist/", lst.listing_delist, name="marketplace-listing-delist"),
    path("listings/<int:pk>/suspend/", lst.listing_suspend, name="marketplace-listing-suspend"),
    path("listings/<int:pk>/clone/", lst.listing_clone, name="marketplace-listing-clone"),
    path("listings/<int:pk>/feature/", lst.listing_feature, name="marketplace-listing-feature"),
    path("listings/<int:pk>/tags/", lst.listing_set_tags, name="marketplace-listing-tags"),
    path("listings/<int:pk>/versions/", lst.listing_versions, name="marketplace-listing-versions"),
    path("listings/<int:pk>/upgrade-check/", lst.listing_upgrade_check,
         name="marketplace-listing-upgrade-check"),

    # ---- 版本（5）----
    path("versions/compare/", lst.versions_compare, name="marketplace-versions-compare"),
    path("versions/<int:pk>/", lst.version_detail, name="marketplace-version-detail"),
    path("versions/<int:pk>/update/", lst.version_update, name="marketplace-version-update"),
    path("versions/<int:pk>/publish/", lst.version_publish, name="marketplace-version-publish"),
    path("versions/<int:pk>/delist/", lst.version_delist, name="marketplace-version-delist"),
    path("versions/<int:pk>/delete/", lst.version_delete, name="marketplace-version-delete"),

    # ---- 安装（8）----
    path("installs/", ins.installs, name="marketplace-installs"),
    path("installs/resolve/", ins.install_resolve, name="marketplace-installs-resolve"),
    path("installs/<int:pk>/", ins.install_detail, name="marketplace-install-detail"),
    path("installs/<int:pk>/uninstall/", ins.install_uninstall, name="marketplace-install-uninstall"),
    path("installs/<int:pk>/enable/", ins.install_enable, name="marketplace-install-enable"),
    path("installs/<int:pk>/disable/", ins.install_disable, name="marketplace-install-disable"),
    path("installs/<int:pk>/config/", ins.install_config, name="marketplace-install-config"),
    path("installs/<int:pk>/upgrade/", ins.install_upgrade, name="marketplace-install-upgrade"),

    # ---- 评价（11）----
    path("listings/<int:pk>/reviews/", rev.listing_reviews, name="marketplace-listing-reviews"),
    path("listings/<int:pk>/rating/", rev.listing_rating, name="marketplace-listing-rating"),
    path("reviews/mine/", rev.reviews_mine, name="marketplace-reviews-mine"),
    path("reviews/<int:pk>/", rev.review_detail, name="marketplace-review-detail"),
    path("reviews/<int:pk>/update/", rev.review_update, name="marketplace-review-update"),
    path("reviews/<int:pk>/delete/", rev.review_delete, name="marketplace-review-delete"),
    path("reviews/<int:pk>/publish/", rev.review_publish, name="marketplace-review-publish"),
    path("reviews/<int:pk>/hide/", rev.review_hide, name="marketplace-review-hide"),
    path("reviews/<int:pk>/helpful/", rev.review_helpful, name="marketplace-review-helpful"),
    path("reviews/<int:pk>/replies/", rev.review_replies, name="marketplace-review-replies"),
    path("replies/<int:pk>/delete/", rev.reply_delete, name="marketplace-reply-delete"),

    # ---- 商业化（12）----
    path("listings/<int:pk>/pricing/", com.listing_pricing, name="marketplace-listing-pricing"),
    path("pricing/<int:pk>/update/", com.pricing_update, name="marketplace-pricing-update"),
    path("pricing/<int:pk>/delete/", com.pricing_delete, name="marketplace-pricing-delete"),
    path("purchases/", com.purchases, name="marketplace-purchases"),
    path("purchases/<int:pk>/", com.purchase_detail, name="marketplace-purchase-detail"),
    path("purchases/<int:pk>/refund/", com.purchase_refund, name="marketplace-purchase-refund"),
    path("purchases/<int:pk>/license/", com.purchase_license, name="marketplace-purchase-license"),
    path("licenses/", com.licenses, name="marketplace-licenses"),
    path("licenses/verify/", com.license_verify, name="marketplace-licenses-verify"),
    path("licenses/<int:pk>/", com.license_detail, name="marketplace-license-detail"),
    path("licenses/<int:pk>/activate/", com.license_activate, name="marketplace-license-activate"),
    path("licenses/<int:pk>/deactivate/", com.license_deactivate,
         name="marketplace-license-deactivate"),

    # ---- 开放能力：Webhook / 事件（9）----
    path("webhooks/", plat.webhooks, name="marketplace-webhooks"),
    path("webhooks/<int:pk>/", plat.webhook_detail, name="marketplace-webhook-detail"),
    path("webhooks/<int:pk>/update/", plat.webhook_update, name="marketplace-webhook-update"),
    path("webhooks/<int:pk>/delete/", plat.webhook_delete, name="marketplace-webhook-delete"),
    path("webhooks/<int:pk>/test/", plat.webhook_test, name="marketplace-webhook-test"),
    path("webhooks/<int:pk>/deliveries/", plat.webhook_deliveries,
         name="marketplace-webhook-deliveries"),
    path("deliveries/<int:pk>/", plat.delivery_detail, name="marketplace-delivery-detail"),
    path("events/", plat.events, name="marketplace-events"),
    path("events/<int:pk>/", plat.event_detail, name="marketplace-event-detail"),

    # ---- 合集（9）----
    path("collections/", plat.collections, name="marketplace-collections"),
    path("collections/public/", plat.collections_public, name="marketplace-collections-public"),
    path("collections/<int:pk>/", plat.collection_detail, name="marketplace-collection-detail"),
    path("collections/<int:pk>/update/", plat.collection_update,
         name="marketplace-collection-update"),
    path("collections/<int:pk>/delete/", plat.collection_delete,
         name="marketplace-collection-delete"),
    path("collections/<int:pk>/publish/", plat.collection_publish,
         name="marketplace-collection-publish"),
    path("collections/<int:pk>/items/", plat.collection_add_item,
         name="marketplace-collection-items"),
    path("collections/<int:pk>/items/reorder/", plat.collection_reorder,
         name="marketplace-collection-items-reorder"),
    path("collection-items/<int:pk>/delete/", plat.collection_item_delete,
         name="marketplace-collection-item-delete"),

    # ---- 举报（3）----
    path("reports/", plat.reports, name="marketplace-reports"),
    path("reports/<int:pk>/", plat.report_detail, name="marketplace-report-detail"),
    path("reports/<int:pk>/handle/", plat.report_handle, name="marketplace-report-handle"),

    # ---- 截图（4）----
    path("listings/<int:pk>/screenshots/", plat.listing_screenshots,
         name="marketplace-listing-screenshots"),
    path("listings/<int:pk>/screenshots/reorder/", plat.screenshots_reorder,
         name="marketplace-screenshots-reorder"),
    path("screenshots/<int:pk>/update/", plat.screenshot_update,
         name="marketplace-screenshot-update"),
    path("screenshots/<int:pk>/delete/", plat.screenshot_delete,
         name="marketplace-screenshot-delete"),

    # ---- 兼容标签（2）----
    path("listings/<int:pk>/compatibility/", plat.listing_compatibility,
         name="marketplace-listing-compatibility"),
    path("compatibility/<int:pk>/delete/", plat.compatibility_delete,
         name="marketplace-compatibility-delete"),

    # ---- 统计（6）----
    path("stats/overview/", st.stats_overview, name="marketplace-stats-overview"),
    path("stats/categories/", st.stats_categories, name="marketplace-stats-categories"),
    path("stats/publishers/", st.stats_publishers, name="marketplace-stats-publishers"),
    path("stats/installs/", st.stats_installs, name="marketplace-stats-installs"),
    path("stats/ratings/", st.stats_ratings, name="marketplace-stats-ratings"),
    path("stats/revenue/", st.stats_revenue, name="marketplace-stats-revenue"),
]

# 计数断言：文档、前端菜单与实现一旦漂移，测试启动即失败（与 officesuite 一致）。
_ENDPOINT_TOTAL = 1 + 9 + 4 + 18 + 6 + 8 + 11 + 12 + 27 + 6
assert len(urlpatterns) == 102 == _ENDPOINT_TOTAL, \
    f"marketplace 接口数应为 102，实际 {len(urlpatterns)}"
