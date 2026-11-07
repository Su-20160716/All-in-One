# -*- coding: utf-8 -*-
"""导出接口：把治理台账渲染成 CSV 文本（不落文件、不产生临时目录）。

为什么返回文本而不是文件地址
----------------------------
1. 平台没有为治理模块单独的文件存储，落一份 CSV 到磁盘反而会留下
   「包含全部风险/发现明细」的副本，与最小化原则冲突；
2. 前端拿 content 做 Blob 下载即可，服务端零副作用，重复调用完全幂等；
3. 导出同样走读权限（scope_queryset），可见范围小的人只能导出自己那份。

行数上限由 limit 控制（默认 5000，最大 20000）：CSV 是给 Excel 打开的，
再大的数据应该走分页接口，而不是把内存撑爆。
"""
from devtools.common import endpoint, ok

from governance import services
from governance.views_common import get_assessment, param_int


EXPORT_DATASETS = (
    ("risks", "风险台账", "风险编号、分值、等级、状态与复核日期"),
    ("findings", "审计发现", "严重度、整改负责人、截止日与逾期标记"),
    ("controls", "内部控制", "频率、自动化、有效性与最近测试时间"),
    ("assessment-items", "评估明细", "条款编号、状态、权重与得分系数"),
    ("retention-actions", "保留期动作", "资源、动作、到期日与执行时间"),
)


@endpoint(("GET",))
def export_catalog(request):
    """导出目录：可用数据集与列说明，前端据此渲染导出入口。"""
    items = [
        {"dataset": key, "label": label, "description": desc,
         "path": f"/api/governance/exports/{key}/"}
        for key, label, desc in EXPORT_DATASETS
    ]
    return ok({"items": items, "count": len(items)})


@endpoint(("GET",))
def export_risks(request):
    """导出风险台账 CSV（固有分/剩余分/等级/负责人）。"""
    limit = param_int(request, "limit", default=5000, minimum=1, maximum=20000)
    return ok(services.export_risks(request.user, limit=limit))


@endpoint(("GET",))
def export_findings(request):
    """导出审计发现 CSV（含逾期与关闭日期）。"""
    limit = param_int(request, "limit", default=5000, minimum=1, maximum=20000)
    return ok(services.export_findings(request.user, limit=limit))


@endpoint(("GET",))
def export_controls(request):
    """导出内部控制 CSV（频率/有效性/映射数）。"""
    limit = param_int(request, "limit", default=5000, minimum=1, maximum=20000)
    return ok(services.export_controls(request.user, limit=limit))


@endpoint(("GET",))
def export_assessment_items(request):
    """导出评估项明细 CSV，可用 assessment_id 限定单次评估。"""
    limit = param_int(request, "limit", default=5000, minimum=1, maximum=20000)
    assessment_id = param_int(request, "assessment_id", default=None, minimum=1)
    if assessment_id:
        # 先过一遍可见性校验：评估不属于当前用户时直接报「不存在」，
        # 而不是返回空 CSV 让人误以为「这次评估没有条目」。
        get_assessment(assessment_id, request.user)
    return ok(services.export_assessment_items(
        request.user, assessment_id=assessment_id, limit=limit))


@endpoint(("GET",))
def export_retention_actions(request):
    """导出保留期动作 CSV（交给存储/法务团队执行）。"""
    limit = param_int(request, "limit", default=5000, minimum=1, maximum=20000)
    return ok(services.export_retention_actions(request.user, limit=limit))
