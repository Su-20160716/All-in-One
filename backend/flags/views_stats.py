# -*- coding: utf-8 -*-
"""功能开关 · 统计接口（5 个）。

统计全部基于 EvaluationLog 聚合，不额外维护汇总表：开关数量与评估量都不大
（日志按开关截断），实时聚合比「双写汇总表」更不容易出现口径不一致。
"""
from devtools.common import endpoint, ok, p

from flags import services
from flags.views_common import get_flag, int_param


def _days(request, default=7):
    return int_param(request, "days", default, minimum=1, maximum=90)


@endpoint(("GET",))
def stats_overview(request):
    """统计概览：规模、近 N 天评估量/命中率/原因分布。"""
    return ok(services.evaluation_summary(request.user, _days(request, 7)))


@endpoint(("GET",))
def stats_top_flags(request):
    """评估量 TOP 开关（含命中率）。"""
    limit = int_param(request, "limit", 10, minimum=1, maximum=100)
    return ok(services.top_flags(request.user, limit=limit, days=_days(request, 7)))


@endpoint(("GET",))
def stats_variant_distribution(request):
    """变体分布：可按开关过滤，按评估次数倒序。"""
    flag = None
    flag_id = p(request, "flag_id")
    if flag_id not in (None, ""):
        flag = get_flag(services.parse_int(flag_id, "flag_id", minimum=1), request.user)
    return ok(services.variant_distribution(request.user, flag=flag, days=_days(request, 7)))


@endpoint(("GET",))
def stats_evaluation_trend(request):
    """评估趋势：按自然日返回评估量、命中量与命中率。"""
    return ok(services.evaluation_trend(request.user, days=_days(request, 14)))


@endpoint(("GET",))
def stats_experiment_board(request):
    """实验看板：状态分布与每个实验的样本进度。"""
    limit = int_param(request, "limit", 20, minimum=1, maximum=100)
    return ok(services.experiment_board(request.user, limit=limit))
