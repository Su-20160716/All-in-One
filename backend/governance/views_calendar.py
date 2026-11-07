# -*- coding: utf-8 -*-
"""合规日历接口：到期事项时间线、iCalendar 导出、控制测试计划与责任分布。

为什么需要日历
--------------
治理工作的失败往往不是「不知道要做」，而是「到期日散落在七张表里」：
策略评审在 Policy、评估截止在 Assessment、整改在 RemediationTask、
同意到期在 ConsentRecord…… 日历把这些日期聚合成一条时间线，
让「本周要做什么」变成一个接口就能回答的问题。

口径约定
--------
- 已逾期事项无论窗口多短都返回：窗口过滤的是「未来」，不是「欠账」；
- 日历只读：扫描/执行类写入仍由各自模块负责，打开日历绝不改数据；
- 导出 ICS 不落文件：文本直接返回给前端下载，服务端不留调用痕迹。
"""
from devtools.common import endpoint, ok, p

from governance import services
from governance.views_common import param_int


def _parse_sources(request):
    """sources 入参：允许 `a,b` 字符串或数组。

    GET 的 query_params.dict() 只保留同名参数的最后一次出现，前端用
    「重复 key」传数组会静默丢值；因此这里显式接受逗号分隔（含全角逗号），
    让筛选条件在浏览器地址栏里可读、可分享。
    """
    raw = p(request, "sources")
    if raw in (None, ""):
        return None
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.replace("，", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        parts = [str(item).strip() for item in raw]
    else:
        raise ValueError("参数 sources 必须是数组或逗号分隔字符串")
    picked = [part for part in parts if part]
    return picked or None


@endpoint(("GET",))
def calendar_events(request):
    """合规日历：窗口内的到期事项（含已逾期），按到期日排序。"""
    days = param_int(request, "days", default=30, minimum=0, maximum=3650)
    data = services.compliance_calendar(request.user, days=days, sources=_parse_sources(request))
    return ok(data)


@endpoint(("GET",))
def calendar_ics(request):
    """日历导出：生成 iCalendar 文本（全天事件），前端直接下载。"""
    days = param_int(request, "days", default=30, minimum=0, maximum=3650)
    return ok(services.calendar_ics(request.user, days=days, sources=_parse_sources(request)))


@endpoint(("GET",))
def calendar_sources(request):
    """日历来源字典：中文标签与可用筛选值，前端不必硬编码。"""
    rows = [
        {"kind": kind, "label": services.CALENDAR_SOURCE_LABELS[kind]}
        for kind in services.CALENDAR_SOURCES
    ]
    return ok({"items": rows, "count": len(rows)})


@endpoint(("GET",))
def control_test_plan(request):
    """控制测试计划：未来 N 天内应执行的测试（按频率推算到期日）。"""
    days = param_int(request, "days", default=30, minimum=0, maximum=3650)
    return ok(services.control_test_plan(request.user, days=days))


@endpoint(("GET",))
def workload(request):
    """责任分布：按负责人聚合未结事项与逾期数，识别超载。"""
    limit = param_int(request, "limit", default=50, minimum=1, maximum=200)
    return ok(services.workload_summary(request.user, limit=limit))


@endpoint(("GET",))
def calendar_summary(request):
    """日历摘要：只返回计数（看板卡片用，避免传输整条时间线）。"""
    days = param_int(request, "days", default=7, minimum=0, maximum=3650)
    data = services.compliance_calendar(request.user, days=days)
    return ok({
        "window_days": data["window_days"],
        "count": data["count"],
        "overdue": data["overdue"],
        "due_soon": data["due_soon"],
        "by_kind": data["by_kind"],
    })
