# -*- coding: utf-8 -*-
"""应用市场 · 统计接口（6 个）。

口径说明：
- 概览/分类/发布者/趋势/评分对登录用户开放（运营与开发者都需要）；
- 收入汇总含平台抽成与发布者结算，仅管理员可见；
- 安装趋势按自然日补零，累计值以「有效安装」为基线，避免卸载后曲线倒挂。
"""
from devtools.common import endpoint, ok, opt_bool, opt_num, opt_str

from . import services
from .common import require_staff
from .models import Listing, Publisher
from .serializers import iso


def _days(request, default=30):
    """统计窗口天数：1~365，非法值直接 400。"""
    return int(opt_num(request, "days", default, minimum=1, maximum=365,
                       integer=True) or default)


@endpoint(("GET",))
def stats_overview(request):
    """市场概览：应用/发布者/安装/评价/收入规模指标。"""
    data = services.marketplace_overview()
    # 推荐位与新上架给运营看板一个快速切片
    data["featured"] = [
        {"id": row.id, "code": row.code, "name": row.name,
         "featured_rank": row.featured_rank, "install_count": row.install_count}
        for row in Listing.objects.filter(status="published", featured=True)
        .order_by("featured_rank", "-install_count")[:10]
    ]
    data["newest"] = [
        {"id": row.id, "code": row.code, "name": row.name,
         "published_at": iso(row.published_at)}
        for row in Listing.objects.filter(status="published")
        .order_by("-published_at")[:10]
    ]
    return ok(data)


@endpoint(("GET",))
def stats_categories(request):
    """分类分布：各分类应用数、安装量与平均评分（含未分类）。"""
    return ok(services.category_distribution())


@endpoint(("GET",))
def stats_publishers(request):
    """发布者 TOP：按安装量与收入排序（days 可选统计窗口）。"""
    days = None
    if opt_str(request, "days").strip():
        days = _days(request)
    limit = int(opt_num(request, "limit", 10, minimum=1, maximum=100, integer=True) or 10)
    data = services.top_publishers(limit=limit, days=days)
    data["days"] = days
    return ok(data)


@endpoint(("GET",))
def stats_installs(request):
    """安装趋势：近 N 天安装/卸载/净增与累计曲线（mine=1 只看自己）。"""
    days = _days(request)
    owner = request.user if opt_bool(request, "mine", False) else None
    return ok(services.install_trend(days=days, owner=owner))


@endpoint(("GET",))
def stats_ratings(request):
    """评分分布：全市场 1~5 星分布与高分应用榜。"""
    limit = int(opt_num(request, "limit", 10, minimum=1, maximum=50, integer=True) or 10)
    return ok(services.rating_statistics(limit=limit))


@endpoint(("GET",))
def stats_revenue(request):
    """收入汇总（仅管理员）：流水、平台抽成、发布者净收入与月度走势。"""
    require_staff(request.user, "仅管理员可查看收入汇总")
    days = None
    if opt_str(request, "days").strip():
        days = _days(request)
    data = services.revenue_statistics(days=days)
    data["days"] = days
    data["publishers"] = Publisher.objects.count()
    return ok(data)


STATS_ENDPOINT_COUNT = 6
