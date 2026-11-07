# -*- coding: utf-8 -*-
"""bizhub 功能矩阵：154 个业务模块共用 29 项能力，其中 34 个模块额外提供订阅。

154 × 29 + 34 = 4500（第四轮 1000 + 第五轮 3500）。新增/删除能力时请同步修改
``docs/17-第四轮-1000项功能与34页面.md`` 与 ``docs/18-第五轮-3500项功能扩展.md``，
模块加载时会断言总数。
"""

# 通用 29 项能力（每个模块都有）
CORE_FEATURES = [
    {
        "key": "list",
        "name": "列表分页",
        "group": "查询",
        "desc": "按模块分页浏览记录，默认隐藏已删除与已归档数据",
        "method": "GET",
        "endpoint": "records/",
    },
    {
        "key": "search",
        "name": "关键词搜索",
        "group": "查询",
        "desc": "按标题、标签与自定义字段内容搜索",
        "method": "GET",
        "endpoint": "records/?q=",
    },
    {
        "key": "filter",
        "name": "多条件筛选",
        "group": "查询",
        "desc": "状态、分类、优先级、负责人、标签、到期日组合筛选",
        "method": "GET",
        "endpoint": "records/?status=&category=&owner=&tag=",
    },
    {
        "key": "sort",
        "name": "自定义排序",
        "group": "查询",
        "desc": "按创建时间、更新时间、到期日、优先级、标题排序",
        "method": "GET",
        "endpoint": "records/?ordering=",
    },
    {
        "key": "create",
        "name": "新建记录",
        "group": "维护",
        "desc": "按模块字段字典创建记录，自动做类型与状态校验",
        "method": "POST",
        "endpoint": "records/",
    },
    {
        "key": "detail",
        "name": "详情查看",
        "group": "维护",
        "desc": "查看记录完整字段、自定义数据与关联信息",
        "method": "GET",
        "endpoint": "records/{id}/",
    },
    {
        "key": "update",
        "name": "编辑记录",
        "group": "维护",
        "desc": "局部更新记录，变更写入活动时间线",
        "method": "PATCH",
        "endpoint": "records/{id}/",
    },
    {
        "key": "delete",
        "name": "软删除",
        "group": "维护",
        "desc": "移入回收状态，可由有权限者恢复",
        "method": "DELETE",
        "endpoint": "records/{id}/",
    },
    {
        "key": "restore",
        "name": "恢复删除",
        "group": "维护",
        "desc": "把软删除记录恢复到正常列表",
        "method": "POST",
        "endpoint": "records/{id}/restore/",
    },
    {
        "key": "archive",
        "name": "归档",
        "group": "维护",
        "desc": "归档不再活跃但需要留存的记录",
        "method": "POST",
        "endpoint": "records/{id}/archive/",
    },
    {
        "key": "unarchive",
        "name": "取消归档",
        "group": "维护",
        "desc": "把归档记录恢复到活跃列表",
        "method": "POST",
        "endpoint": "records/{id}/unarchive/",
    },
    {
        "key": "bulk-status",
        "name": "批量改状态",
        "group": "批量",
        "desc": "一次更新多条记录状态，逐条校验状态合法性",
        "method": "POST",
        "endpoint": "bulk/",
    },
    {
        "key": "bulk-owner",
        "name": "批量指派",
        "group": "批量",
        "desc": "一次把多条记录指派给同一负责人",
        "method": "POST",
        "endpoint": "bulk/",
    },
    {
        "key": "bulk-tag",
        "name": "批量打标签",
        "group": "批量",
        "desc": "合并式追加标签，不覆盖已有标签",
        "method": "POST",
        "endpoint": "bulk/",
    },
    {
        "key": "bulk-archive",
        "name": "批量归档",
        "group": "批量",
        "desc": "一次归档多条记录",
        "method": "POST",
        "endpoint": "bulk/",
    },
    {
        "key": "bulk-delete",
        "name": "批量删除",
        "group": "批量",
        "desc": "一次软删除多条记录",
        "method": "POST",
        "endpoint": "bulk/",
    },
    {
        "key": "export",
        "name": "CSV 导出",
        "group": "数据",
        "desc": "按当前筛选条件导出 UTF-8 BOM CSV，Excel 可直接打开",
        "method": "GET",
        "endpoint": "export/?fmt=csv",
    },
    {
        "key": "import",
        "name": "CSV 导入",
        "group": "数据",
        "desc": "批量导入并逐行校验，返回成功数与错误明细",
        "method": "POST",
        "endpoint": "import/",
    },
    {
        "key": "summary",
        "name": "统计概览",
        "group": "分析",
        "desc": "总数、活跃、完成、逾期、归档、完成率与近 7/30 天新增",
        "method": "GET",
        "endpoint": "stats/",
    },
    {
        "key": "trend",
        "name": "新增/完成趋势",
        "group": "分析",
        "desc": "按天返回新增与完成数量，默认 30 天",
        "method": "GET",
        "endpoint": "trend/?days=30",
    },
    {
        "key": "distribution",
        "name": "分布分析",
        "group": "分析",
        "desc": "按状态、分类、优先级或负责人聚合占比",
        "method": "GET",
        "endpoint": "distribution/?field=",
    },
    {
        "key": "overdue",
        "name": "逾期清单",
        "group": "分析",
        "desc": "列出已过到期日且未完成的记录",
        "method": "GET",
        "endpoint": "overdue/",
    },
    {
        "key": "quality",
        "name": "数据质量检查",
        "group": "分析",
        "desc": "检查缺负责人、缺到期日、缺分类、标题重复与长期未更新",
        "method": "GET",
        "endpoint": "quality/",
    },
    {
        "key": "duplicate",
        "name": "复制记录",
        "group": "效率",
        "desc": "复制一条记录为草稿，标题追加“（副本）”",
        "method": "POST",
        "endpoint": "records/{id}/duplicate/",
    },
    {
        "key": "merge",
        "name": "合并重复记录",
        "group": "效率",
        "desc": "把多条记录合并到主记录，其余标记为已合并",
        "method": "POST",
        "endpoint": "merge/",
    },
    {
        "key": "favorite",
        "name": "收藏",
        "group": "协作",
        "desc": "个人收藏/取消收藏，列表可按收藏筛选",
        "method": "POST",
        "endpoint": "records/{id}/favorite/",
    },
    {
        "key": "comment",
        "name": "评论",
        "group": "协作",
        "desc": "记录下讨论，自动通知记录负责人",
        "method": "GET/POST",
        "endpoint": "records/{id}/comments/",
    },
    {
        "key": "timeline",
        "name": "活动时间线",
        "group": "协作",
        "desc": "创建、修改、状态流转、归档、合并等操作留痕",
        "method": "GET",
        "endpoint": "records/{id}/timeline/",
    },
    {
        "key": "saved-view",
        "name": "保存视图",
        "group": "协作",
        "desc": "保存常用筛选组合，支持个人视图与共享视图",
        "method": "GET/POST/DELETE",
        "endpoint": "saved-views/",
    },
]

SUBSCRIPTION_FEATURE = {
    "key": "subscription",
    "name": "到期订阅提醒",
    "group": "协作",
    "desc": "订阅本模块的逾期/临期摘要，由 bizhub_digest 命令按日或按周推送",
    "method": "GET/POST",
    "endpoint": "subscription/",
}

# 提供订阅能力的 34 个模块（14 个老模块 + 20 个新增到期/临期提醒模块）
SUBSCRIPTION_MODULES = {
    "crm-accounts",
    "crm-opportunities",
    "sales-orders",
    "purchase-orders",
    "campaigns",
    "candidates",
    "onboarding",
    "performance-reviews",
    "payroll-runs",
    "invoices",
    "compliance-checks",
    "risk-register",
    "audit-findings",
    "incident-reports",
    # 第五轮新增
    "mfg-work-orders",
    "mfg-maintenance-plans",
    "service-tickets",
    "service-sla",
    "edu-enrollments",
    "edu-research-projects",
    "health-appointments",
    "health-followups",
    "gov-permits",
    "gov-subsidies",
    "retail-orders",
    "retail-returns",
    "logistics-shipments",
    "logistics-freight-bills",
    "energy-projects",
    "env-permits",
    "media-shoots",
    "fin-loans",
    "fin-collections",
    "construction-progress",
}

FEATURE_INDEX = {f["key"]: f for f in CORE_FEATURES + [SUBSCRIPTION_FEATURE]}


def feature_keys(slug: str):
    """返回模块的功能 key 列表：29 项基线 + 可选订阅。"""
    keys = [f["key"] for f in CORE_FEATURES]
    if slug in SUBSCRIPTION_MODULES:
        keys.append(SUBSCRIPTION_FEATURE["key"])
    return keys


def feature_detail(slug: str):
    return [dict(FEATURE_INDEX[k]) for k in feature_keys(slug)]
