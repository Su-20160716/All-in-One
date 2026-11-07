# -*- coding: utf-8 -*-
"""统计接口：合规看板、框架达成率、风险分布、逾期整改、评审提醒、发现趋势。

统计口径统一由 governance.services 提供，本文件只做参数校验与响应包装，
保证「看板卡片」与「列表页」永远来自同一套计算，不会出现两处数字打架。
"""
from devtools.common import endpoint, ok

from governance import services
from governance.models import Finding
from governance.views_common import get_framework, param_int, param_str


@endpoint(("GET",))
def stats_dashboard(request):
    """合规看板：框架达成率、开放风险、逾期整改、DPIA 覆盖率。"""
    return ok(services.dashboard(request.user))


@endpoint(("GET",))
def stats_framework_coverage(request):
    """框架达成率：全部框架汇总，或指定 framework_id 单框架明细。"""
    framework_id = param_int(request, "framework_id", default=None, minimum=1)
    if framework_id:
        framework = get_framework(framework_id, request.user)
        return ok({"summary": services.framework_coverage(framework),
                   "frameworks": [{
                       "framework_id": framework.pk,
                       "name": framework.name,
                       "version": framework.version,
                       "status": framework.status,
                   }]})
    return ok(services.framework_summary(request.user))


@endpoint(("GET",))
def stats_risk_distribution(request):
    """风险分布：按等级/状态/类别的计数与平均剩余分。"""
    return ok(services.risk_distribution(request.user))


@endpoint(("GET",))
def stats_overdue_remediations(request):
    """逾期整改：及时率、逾期数量与逾期清单（可限制返回条数）。"""
    limit = param_int(request, "limit", default=20, minimum=1, maximum=200)
    data = services.remediation_timeliness(request.user)
    data["overdue_items"] = data["overdue_items"][:limit]
    data["limit"] = limit
    return ok(data)


@endpoint(("GET",))
def stats_review_reminders(request):
    """策略评审提醒：下次评审日 ≤ N 天（默认 30 天）。"""
    days = param_int(request, "days", default=30, minimum=0, maximum=3650)
    return ok(services.policy_review_reminders(request.user, days=days))


@endpoint(("GET",))
def stats_finding_trend(request):
    """审计发现趋势：按月新增/解决/严重数，最多 36 个月。"""
    months = param_int(request, "months", default=6, minimum=1, maximum=36)
    trend = services.finding_trend(request.user, months=months)
    scope = param_str(request, "scope", max_len=20)
    if scope == "severity":
        trend["by_severity"] = {
            severity: Finding.objects.filter(owner=request.user,
                                             severity=severity).count() for severity in
            ("critical", "high", "medium", "low")
        }
    return ok(trend)
