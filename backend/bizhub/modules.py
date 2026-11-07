# -*- coding: utf-8 -*-
"""bizhub 的 34 个业务模块定义。

每个模块只描述「字段 schema + 状态 + 分类」，数据统一落在 BizRecord：
- 固定列：标题/状态/分类/优先级/负责人/到期日/标签/归档/删除
- 扩展字段：data JSON，按 fields 定义做类型校验与 CSV 映射

这样 34 个业务域共享同一套可靠的 CRUD、权限、批量、统计与导入导出引擎，
页面由模块元数据驱动，新增模块只需要在这里加一段配置。
"""

from .features import feature_detail, feature_keys


def f(key, label, type="text", required=False, options=None):
    return {
        "key": key,
        "label": label,
        "type": type,
        "required": bool(required),
        "options": list(options or []),
    }


def s(key, label, done=False):
    return {"key": key, "label": label, "done": bool(done)}


def m(slug, name, group, icon, description, fields, statuses, categories):
    return {
        "slug": slug,
        "name": name,
        "group": group,
        "icon": icon,
        "description": description,
        "fields": fields,
        "statuses": statuses,
        "categories": categories,
    }


MODULES = [
    # ---------------- 销售与市场 ----------------
    m(
        "crm-accounts", "客户档案", "销售与市场", "👥", "客户主数据、分级、跟进与流失管理。",
        [f("industry", "行业"), f("level", "客户等级", "select", options=["A", "B", "C"]),
         f("phone", "联系电话"), f("region", "所在地区")],
        [s("potential", "潜在"), s("following", "跟进中"), s("active", "合作中"), s("lost", "已流失", True)],
        ["直客", "渠道", "伙伴", "线上"],
    ),
    m(
        "crm-leads", "销售线索", "销售与市场", "🎯", "线索采集、清洗、跟进与转化。",
        [f("source", "来源", "select", options=["官网", "展会", "转介绍", "广告"]),
         f("contact", "联系人"), f("phone", "电话"), f("budget", "预算", "number")],
        [s("new", "新线索"), s("contacted", "已联系"), s("converted", "已转化", True), s("invalid", "无效", True)],
        ["高意向", "中意向", "低意向"],
    ),
    m(
        "crm-opportunities", "商机管理", "销售与市场", "💰", "商机阶段、金额、赢单率与输赢复盘。",
        [f("amount", "预计金额", "number"), f("probability", "赢单率", "number"),
         f("contact", "关键联系人"), f("stage_note", "阶段说明", "textarea")],
        [s("early", "初期"), s("proposal", "方案"), s("negotiation", "谈判"), s("won", "赢单", True), s("lost", "输单", True)],
        ["新签", "续约", "增购"],
    ),
    m(
        "sales-quotes", "报价单", "销售与市场", "🧾", "报价草稿、审批、发送与客户反馈。",
        [f("amount", "报价金额", "number"), f("currency", "币种", "select", options=["CNY", "USD", "EUR"]),
         f("valid_until", "有效期", "date"), f("contact", "联系人")],
        [s("draft", "草稿"), s("pending", "待审批"), s("sent", "已发送"), s("accepted", "已接受", True), s("rejected", "已拒绝", True)],
        ["标准", "定制", "框架"],
    ),
    m(
        "sales-orders", "销售订单", "销售与市场", "📦", "订单确认、备货、发货与回款跟踪。",
        [f("amount", "订单金额", "number"), f("quantity", "数量", "number"),
         f("delivery_date", "交付日期", "date"), f("contact", "客户联系人")],
        [s("pending", "待确认"), s("stocking", "备货中"), s("shipped", "已发货"), s("completed", "已完成", True), s("cancelled", "已取消", True)],
        ["直销", "渠道", "线上"],
    ),
    m(
        "product-catalog", "产品目录", "销售与市场", "🏷", "产品 SKU、定价、规格与上下架。",
        [f("sku", "SKU"), f("price", "标准价", "number"), f("unit", "单位"), f("spec", "规格", "textarea")],
        [s("draft", "草稿"), s("on_sale", "在售"), s("off_sale", "停售", True), s("out_of_stock", "缺货")],
        ["软件", "硬件", "服务", "耗材"],
    ),
    m(
        "campaigns", "市场活动", "销售与市场", "📣", "活动策划、预算、执行与效果归因。",
        [f("channel", "渠道", "select", options=["线上", "线下", "混合"]), f("budget", "预算", "number"),
         f("start_date", "开始日期", "date"), f("end_date", "结束日期", "date")],
        [s("planning", "策划中"), s("running", "进行中"), s("finished", "已结束", True), s("cancelled", "已取消", True)],
        ["品牌", "获客", "促销", "活动"],
    ),
    m(
        "content-calendar", "内容日历", "销售与市场", "🗓", "选题、撰稿、审核与多平台发布排期。",
        [f("channel", "发布渠道", "select", options=["公众号", "视频", "官网", "社媒"]),
         f("publish_date", "发布日期", "date"), f("author", "作者"), f("url", "链接")],
        [s("idea", "选题"), s("drafting", "撰写"), s("review", "审核"), s("published", "已发布", True)],
        ["图文", "视频", "直播", "新闻"],
    ),
    m(
        "competitor-intel", "竞品情报", "销售与市场", "🔭", "竞品动态、威胁等级与情报归档。",
        [f("competitor", "竞品名称"), f("source_url", "来源链接"),
         f("threat", "威胁等级", "select", options=["低", "中", "高"]), f("summary", "情报摘要", "textarea")],
        [s("monitoring", "监控中"), s("key", "重点"), s("archived", "归档", True)],
        ["产品", "价格", "渠道", "人事"],
    ),
    # ---------------- 供应链 ----------------
    m(
        "suppliers", "供应商", "供应链", "🏭", "供应商准入、分级、绩效与合作状态。",
        [f("contact", "联系人"), f("phone", "电话"), f("rating", "评分", "number"), f("note", "备注", "textarea")],
        [s("pending", "待审核"), s("active", "合作中"), s("paused", "暂停"), s("blacklisted", "黑名单", True)],
        ["生产", "物流", "服务", "贸易"],
    ),
    m(
        "purchase-orders", "采购单", "供应链", "🛒", "请购、审批、下单、到货与验收入库。",
        [f("amount", "采购金额", "number"), f("quantity", "数量", "number"),
         f("expected_date", "预计到货", "date"), f("supplier", "供应商")],
        [s("draft", "草稿"), s("pending", "待审批"), s("purchasing", "采购中"), s("received", "已入库", True), s("cancelled", "已取消", True)],
        ["常规", "紧急", "框架"],
    ),
    m(
        "warehouses", "仓库管理", "供应链", "🏬", "仓库主数据、容量、盘点与启用状态。",
        [f("location", "位置"), f("capacity", "容量", "number"), f("area", "面积", "number"), f("manager", "负责人")],
        [s("active", "启用"), s("inactive", "停用", True), s("stocktaking", "盘点中")],
        ["自营", "租赁", "第三方"],
    ),
    m(
        "inventory-items", "库存物料", "供应链", "📊", "物料库存、安全库存、缺货与报废。",
        [f("sku", "物料编码"), f("quantity", "当前库存", "number"),
         f("min_stock", "安全库存", "number"), f("unit", "单位")],
        [s("sufficient", "充足"), s("low", "低库存"), s("out", "缺货"), s("obsolete", "报废", True)],
        ["原材料", "半成品", "成品", "备件"],
    ),
    # ---------------- 人力 ----------------
    m(
        "recruitment-jobs", "招聘职位", "人力", "🧑‍💼", "职位需求、编制、薪资区间与招聘状态。",
        [f("department", "用人部门"), f("headcount", "招聘人数", "number"),
         f("salary_range", "薪资区间"), f("location", "工作地点")],
        [s("draft", "草稿"), s("hiring", "招聘中"), s("paused", "暂停"), s("closed", "已关闭", True)],
        ["技术", "产品", "销售", "职能"],
    ),
    m(
        "candidates", "候选人", "人力", "👤", "候选人来源、面试流程、Offer 与入职。",
        [f("job", "应聘职位"), f("phone", "电话"), f("source", "来源"), f("score", "评分", "number")],
        [s("new", "新投递"), s("screening", "初筛"), s("interview", "面试"), s("offer", "Offer"),
         s("hired", "已入职", True), s("rejected", "已淘汰", True)],
        ["社招", "校招", "内推", "猎头"],
    ),
    m(
        "onboarding", "入职任务", "人力", "🪪", "新人报到、账号开通、培训与导师任务。",
        [f("employee", "新员工"), f("department", "部门"), f("mentor", "导师"), f("start_date", "入职日期", "date")],
        [s("pending", "待开始"), s("doing", "进行中"), s("done", "已完成", True), s("delayed", "延期")],
        ["资料", "账号", "培训", "设备"],
    ),
    m(
        "performance-reviews", "绩效评估", "人力", "📈", "自评、主管评、校准与结果归档。",
        [f("cycle", "考核周期"), f("employee", "被考核人"), f("score", "得分", "number"), f("reviewer", "评估人")],
        [s("self_review", "待自评"), s("manager_review", "待主管"), s("calibration", "校准中"), s("completed", "已完成", True)],
        ["月度", "季度", "年度", "试用期"],
    ),
    m(
        "payroll-runs", "薪酬批次", "人力", "💵", "月度薪资核算、审批与发放批次。",
        [f("period", "所属期间"), f("headcount", "人数", "number"),
         f("amount", "发放金额", "number"), f("pay_date", "发放日期", "date")],
        [s("draft", "草稿"), s("calculating", "核算中"), s("pending_pay", "待发放"), s("paid", "已发放", True)],
        ["月度", "奖金", "补发"],
    ),
    m(
        "attendance-exceptions", "考勤异常", "人力", "⏰", "迟到、早退、缺卡与旷工异常处理。",
        [f("employee", "员工"), f("exception_type", "异常类型", "select", options=["迟到", "早退", "缺卡", "旷工"]),
         f("minutes", "异常分钟", "number"), f("date", "发生日期", "date")],
        [s("pending", "待处理"), s("confirmed", "已确认"), s("appealed", "已申诉"), s("closed", "已关闭", True)],
        ["迟到", "早退", "缺卡", "旷工"],
    ),
    # ---------------- 财务与合规 ----------------
    m(
        "invoices", "发票台账", "财务与合规", "🧾", "开票申请、发票登记、回款与作废。",
        [f("invoice_no", "发票号"), f("buyer", "购买方"),
         f("amount", "金额", "number"), f("tax_rate", "税率", "number")],
        [s("pending", "待开票"), s("issued", "已开票"), s("paid", "已收款", True), s("void", "已作废", True)],
        ["增值税专票", "增值税普票", "电子发票"],
    ),
    m(
        "budgets", "预算计划", "财务与合规", "🧮", "部门预算编制、审批、执行与关账。",
        [f("period", "预算期间"), f("amount", "预算金额", "number"),
         f("spent", "已使用", "number"), f("department", "所属部门")],
        [s("draft", "草稿"), s("approving", "审批中"), s("active", "执行中"), s("closed", "已关闭", True)],
        ["人力", "市场", "研发", "行政"],
    ),
    m(
        "compliance-checks", "合规检查", "财务与合规", "✅", "法规要求、检查任务、证据与整改。",
        [f("regulation", "法规/条款"), f("deadline", "截止日期", "date"),
         f("evidence", "证据说明", "textarea"), f("owner_note", "责任人")],
        [s("pending", "待检查"), s("checking", "进行中"), s("passed", "已通过", True), s("rectify", "需整改")],
        ["数据", "安全", "财务", "劳动"],
    ),
    m(
        "risk-register", "风险登记", "财务与合规", "⚠️", "风险识别、评估、缓解与关闭。",
        [f("likelihood", "发生概率", "select", options=["低", "中", "高"]),
         f("impact", "影响程度", "select", options=["低", "中", "高"]),
         f("mitigation", "缓解措施", "textarea"), f("owner_note", "风险责任人")],
        [s("identified", "已识别"), s("assessing", "评估中"), s("mitigating", "缓解中"), s("closed", "已关闭", True)],
        ["战略", "运营", "财务", "合规"],
    ),
    m(
        "audit-findings", "审计问题", "财务与合规", "🔍", "审计发现、整改责任、复核与关闭。",
        [f("audit_no", "审计编号"), f("severity", "严重程度", "select", options=["低", "中", "高"]),
         f("deadline", "整改期限", "date"), f("finding", "问题描述", "textarea")],
        [s("pending", "待整改"), s("rectifying", "整改中"), s("review", "待复核"), s("closed", "已关闭", True)],
        ["财务", "内控", "流程", "IT"],
    ),
    # ---------------- 数据与平台 ----------------
    m(
        "data-catalog", "数据资产", "数据与平台", "🗃", "数据表、主题域、敏感级别与责任人。",
        [f("table_name", "表名"), f("domain", "主题域"),
         f("sensitivity", "敏感级别", "select", options=["公开", "内部", "敏感", "机密"]), f("owner_note", "数据责任人")],
        [s("draft", "草稿"), s("published", "已发布"), s("offline", "已下线", True)],
        ["事实表", "维度表", "指标", "接口"],
    ),
    m(
        "metric-dictionary", "指标字典", "数据与平台", "📐", "指标口径、公式、单位与评审发布。",
        [f("code", "指标编码"), f("formula", "计算公式", "textarea"),
         f("unit", "单位"), f("owner_note", "指标负责人")],
        [s("draft", "草稿"), s("review", "评审中"), s("published", "已发布"), s("disabled", "已停用", True)],
        ["业务", "财务", "运营", "技术"],
    ),
    m(
        "integration-apps", "集成应用", "数据与平台", "🔌", "第三方应用、鉴权方式、启停与异常。",
        [f("provider", "服务商"), f("endpoint", "回调地址"),
         f("auth_type", "鉴权方式", "select", options=["OAuth", "APIKey", "Basic"]), f("owner_note", "负责人")],
        [s("pending", "待接入"), s("enabled", "已启用"), s("disabled", "已停用", True), s("error", "异常")],
        ["协作", "CRM", "财务", "存储"],
    ),
    m(
        "automation-rules", "自动化规则", "数据与平台", "⚙️", "触发器、动作、调度与运行状态。",
        [f("trigger", "触发条件"), f("action", "执行动作"),
         f("schedule", "调度周期"), f("last_run", "最近运行")],
        [s("draft", "草稿"), s("enabled", "已启用"), s("paused", "已暂停"), s("error", "异常")],
        ["通知", "审批", "同步", "清理"],
    ),
    m(
        "report-subscriptions", "报表订阅", "数据与平台", "📬", "报表周期、收件人、格式与启停。",
        [f("report", "报表名称"), f("frequency", "频率", "select", options=["日", "周", "月"]),
         f("recipients", "收件人"), f("format", "格式", "select", options=["PDF", "CSV", "Excel"])],
        [s("pending", "待启用"), s("enabled", "已启用"), s("paused", "已暂停", True)],
        ["经营", "项目", "财务", "人力"],
    ),
    # ---------------- 法务与安全 ----------------
    m(
        "legal-cases", "法务案件", "法务与安全", "⚖️", "法律咨询、诉讼案件、开庭与结案归档。",
        [f("case_no", "案件编号"), f("counterparty", "对方当事人"),
         f("lawyer", "承办律师"), f("hearing_date", "开庭日期", "date")],
        [s("advice", "咨询"), s("ongoing", "进行中"), s("closed", "已结案", True), s("archived", "归档", True)],
        ["合同", "劳动", "知识产权", "诉讼"],
    ),
    m(
        "ip-portfolio", "知识产权", "法务与安全", "💡", "专利、商标、著作权申请与年费维持。",
        [f("ip_type", "类型", "select", options=["专利", "商标", "著作权", "商业秘密"]),
         f("application_no", "申请号"), f("expiry_date", "到期日", "date"), f("owner_note", "权利人")],
        [s("applying", "申请中"), s("granted", "已授权"), s("maintaining", "维持中"), s("expired", "已失效", True)],
        ["专利", "商标", "著作权", "秘密"],
    ),
    m(
        "privacy-requests", "隐私请求", "法务与安全", "🛡", "数据主体查询、更正、删除与撤回同意。",
        [f("requester", "申请人"), f("request_type", "请求类型", "select", options=["查询", "更正", "删除", "撤回同意"]),
         f("received_date", "收到日期", "date"), f("deadline", "答复期限", "date")],
        [s("pending", "待处理"), s("processing", "处理中"), s("replied", "已回复"), s("closed", "已关闭", True)],
        ["查询", "更正", "删除", "撤回"],
    ),
    m(
        "incident-reports", "事故报告", "法务与安全", "🚨", "安全/生产/IT/环境事故上报、调查与关闭。",
        [f("incident_type", "事故类型"), f("severity", "严重程度", "select", options=["一般", "较大", "重大"]),
         f("occurred_at", "发生日期", "date"), f("root_cause", "根因分析", "textarea")],
        [s("reported", "已上报"), s("investigating", "调查中"), s("mitigated", "已缓解"), s("closed", "已关闭", True)],
        ["安全", "生产", "IT", "环境"],
    ),
    m(
        "asset-maintenance", "设备维保", "法务与安全", "🔧", "设备保养计划、维修记录、巡检与校准。",
        [f("asset_name", "设备名称"), f("asset_no", "设备编号"),
         f("maintainer", "维保人"), f("next_date", "下次维保", "date")],
        [s("pending", "待保养"), s("doing", "保养中"), s("done", "已完成", True), s("overdue", "已逾期")],
        ["保养", "维修", "巡检", "校准"],
    ),
]


def _parse_fields(spec):
    out = []
    for item in spec.split(";"):
        parts = item.split(":")
        opts = parts[3].split("|") if len(parts) > 3 else []
        out.append(f(parts[0], parts[1], parts[2] if len(parts) > 2 else "text", options=opts))
    return out


def _parse_statuses(spec):
    out = []
    for item in spec.split(";"):
        parts = item.split(":")
        out.append(s(parts[0], parts[1], len(parts) > 2 and parts[2] == "1"))
    return out


def _extend(group, rows):
    for slug, name, icon, desc, fields_spec, statuses_spec, categories in rows:
        MODULES.append(
            m(
                slug,
                name,
                group,
                icon,
                desc,
                _parse_fields(fields_spec),
                _parse_statuses(statuses_spec),
                categories,
            )
        )


# ---------------- 第五轮扩展：12 个业务域 × 10 个模块 = 120 个模块 ----------------
# 字段格式 "key:label[:type[:opt1|opt2]]"，状态格式 "key:label[:1]"（1 = 已完成态）。
_extend(
    "制造与生产",
    [
        ("mfg-work-orders", "生产工单", "🏭", "产线工单排产、报工与完工质检。", "line:产线;qty:计划数量:number;start:计划开工:date;note:备注:textarea", "planned:待排产;running:生产中;done:已完成:1;paused:已暂停", ["常规", "加急", "试产"]),
        ("mfg-bom", "BOM 清单", "🧱", "物料清单版本、用量与替代料维护。", "product:产品;version:版本;qty:标准用量:number;note:工艺说明:textarea", "draft:草稿;review:审核中;active:已生效:1;obsolete:已停用:1", ["整机", "部件", "包材"]),
        ("mfg-routing", "工艺路线", "🛠", "工序顺序、工时与设备要求。", "process:工序;station:工位;minutes:标准工时:number;equipment:设备", "draft:草稿;approved:已批准:1;running:执行中;changed:已变更", ["机械加工", "装配", "表面处理"]),
        ("mfg-quality-inspections", "质检记录", "🔬", "来料、过程与出货检验记录。", "batch:批次;sample:抽检数:number;defects:不良数:number;result:结论:select:合格|让步|不合格", "pending:待检;passed:合格:1;failed:不合格:1;recheck:复检中", ["来料", "过程", "出货"]),
        ("mfg-equipment-ledger", "设备台账", "⚙️", "生产设备档案、精度与责任人。", "code:设备编号;location:位置;capacity:产能:number;keeper:责任人", "idle:闲置;running:运行中;repair:维修中;retired:已报废:1", ["加工", "检测", "动力"]),
        ("mfg-maintenance-plans", "保养计划", "🧰", "预防性保养周期与执行跟踪。", "equipment:设备;cycle:周期天数:number;next:下次保养:date;keeper:保养人", "planned:待执行;doing:保养中;done:已完成:1;skipped:已跳过:1", ["日保", "月保", "年保"]),
        ("mfg-scrap-records", "报废记录", "🗑", "报废申请、原因与处置结果。", "material:物料;qty:数量:number;reason:原因;disposal:处置方式", "pending:待审批;approved:已批准:1;rejected:已驳回:1;scrapped:已报废:1", ["原料", "半成品", "成品"]),
        ("mfg-change-requests", "工程变更单", "🔁", "工程变更申请、评估与切换。", "ecn:变更单号;impact:影响范围;effective:生效日期:date;change_owner:负责人", "draft:草稿;review:评估中;approved:已批准:1;closed:已关闭:1", ["设计", "工艺", "物料"]),
        ("mfg-shift-reports", "班组报工", "⏱", "班组产量、工时与异常上报。", "shift:班次:select:白班|中班|夜班;output:产量:number;hours:工时:number;issue:异常说明:textarea", "open:进行中;submitted:已提交:1;confirmed:已确认:1;disputed:有争议", ["装配", "加工", "包装"]),
        ("mfg-safety-checks", "安全检查", "🦺", "车间安全检查、隐患与整改。", "area:区域;checker:检查人;hazard:隐患描述:textarea;deadline:整改期限:date", "planned:待检查;passed:合格:1;issue:发现隐患;closed:已整改:1", ["消防", "用电", "设备"]),
    ],
)

_extend(
    "客服与支持",
    [
        ("service-tickets", "服务工单", "🎫", "客户报障、派单与处理闭环。", "channel:来源:select:电话|邮件|在线|现场;customer:客户;issue:问题描述:textarea;assignee:处理人", "new:待受理;assigned:已派单;processing:处理中;resolved:已解决:1;closed:已关闭:1", ["咨询", "故障", "投诉"]),
        ("service-sla", "SLA 规则", "⏳", "服务等级、响应与解决时限。", "level:等级:select:P1|P2|P3;response:响应分钟:number;resolve:解决分钟:number;scope:适用范围", "draft:草稿;active:生效中:1;paused:已暂停;expired:已过期:1", ["标准", "高级", "关键"]),
        ("service-knowledge", "服务知识", "📚", "排障手册、FAQ 与复用方案。", "kb_category:分类;keywords:关键词;content:正文:textarea;author:作者", "draft:草稿;review:审核中;published:已发布:1;archived:已归档:1", ["FAQ", "排障", "操作"]),
        ("service-complaints", "客户投诉", "😤", "投诉登记、定级与回访闭环。", "customer:客户;level:级别:select:一般|重要|重大;detail:投诉内容:textarea;handler:处理人", "new:待处理;investigating:调查中;resolved:已解决:1;appealed:已申诉", ["质量", "服务", "交付"]),
        ("service-refunds", "退款申请", "💸", "退款原因、金额与审批。", "order:订单号;amount:退款金额:number;reason:原因;approver:审批人", "pending:待审批;approved:已批准:1;paid:已退款:1;rejected:已驳回:1", ["质量", "错发", "协商"]),
        ("service-callbacks", "回访记录", "📞", "服务后回访、满意度与建议。", "customer:客户;method:方式:select:电话|微信|邮件;score:满意度:number;note:回访记录:textarea", "planned:待回访;done:已完成:1;unreachable:未接通:1;closed:已关闭:1", ["售后", "续约", "投诉"]),
        ("service-escalations", "升级处理", "🚨", "超时或高风险工单的升级流转。", "ticket:关联工单;level:升级级别:select:一级|二级|三级;reason:升级原因;handler:接手人", "open:待接手;handling:处理中;resolved:已解决:1;rejected:已驳回:1", ["超时", "投诉", "重大"]),
        ("service-surveys", "满意度调查", "📊", "调查问卷、回收与结果分析。", "target:调查对象;channel:渠道:select:站内|短信|邮件;questions:题目数:number;score:平均分:number", "draft:草稿;running:进行中:1;closed:已结束:1;archived:已归档:1", ["NPS", "CSAT", "专项"]),
        ("service-entitlements", "服务权益", "🎟", "客户服务包、剩余次数与有效期。", "customer:客户;package:服务包;quota:总次数:number;expire:到期日:date", "active:生效中:1;exhausted:已用尽:1;expired:已过期:1;frozen:已冻结", ["基础", "标准", "尊享"]),
        ("service-field-visits", "上门服务", "🚗", "上门排期、签到与服务报告。", "customer:客户;address:地址;visit_at:上门时间:date;engineer:工程师", "scheduled:已排期;enroute:在途;onsite:已到场;done:已完成:1", ["安装", "维修", "巡检"]),
    ],
)

_extend(
    "教育科研",
    [
        ("edu-courses", "课程目录", "📘", "课程大纲、课时与授课教师。", "subject:学科;hours:课时:number;teacher:教师;outline:课程大纲:textarea", "draft:草稿;open:开放报名:1;running:进行中;closed:已结课:1", ["必修", "选修", "实践"]),
        ("edu-classes", "班级管理", "🏫", "班级编制、班主任与上课安排。", "grade:年级;headteacher:班主任;size:人数:number;room:教室", "planned:待开班;active:在读:1;graduated:已结业:1;paused:已停课", ["行政班", "教学班", "临时班"]),
        ("edu-enrollments", "报名记录", "📝", "报名、缴费与分班状态。", "student:学员;course:课程;fee:费用:number;channel:来源:select:线上|线下|转介绍", "pending:待审核;confirmed:已确认:1;paid:已缴费:1;cancelled:已取消:1", ["新生", "续报", "插班"]),
        ("edu-attendance", "上课考勤", "🕒", "签到、请假与缺勤统计。", "class:班级;student:学员;date:上课日期:date;attendance:考勤:select:出勤|迟到|请假|缺勤", "pending:待记录;present:出勤:1;late:迟到:1;absent:缺勤:1", ["日常", "补课", "考试"]),
        ("edu-grades", "成绩单", "🏆", "成绩录入、排名与等级。", "student:学员;course:课程;score:分数:number;rank:排名:number", "draft:草稿;published:已发布:1;revised:已修订:1;locked:已锁定:1", ["期中", "期末", "平时"]),
        ("edu-assignments", "作业布置", "📄", "作业发布、提交与批改。", "class:班级;assignment:作业标题;due:截止日期:date;submit_rate:提交率:number", "draft:草稿;assigned:已布置:1;grading:批改中;closed:已结束:1", ["练习", "实验", "项目"]),
        ("edu-exams", "考试安排", "📅", "考场、监考与考试日程。", "course:课程;exam_at:考试时间:date;room:考场;invigilator:监考人", "planned:待安排;confirmed:已确认:1;ongoing:进行中;finished:已结束:1", ["月考", "期中", "期末"]),
        ("edu-scholarships", "奖学金", "🎖", "奖项设置、申请与评审。", "name:奖项;amount:金额:number;quota:名额:number;deadline:截止日期:date", "draft:草稿;open:申请中:1;reviewing:评审中;awarded:已发放:1", ["学业", "竞赛", "助困"]),
        ("edu-research-projects", "科研项目", "🔬", "课题立项、经费与结题。", "leader:负责人;funding:经费:number;start:开始日期:date;result:成果形式", "draft:草稿;approved:已立项:1;running:在研;closed:已结题:1", ["纵向", "横向", "校级"]),
        ("edu-thesis", "论文成果", "📖", "论文投稿、收录与引用跟踪。", "author:作者;journal:期刊;level:级别:select:核心|普刊|会议;status_note:进展说明:textarea", "draft:撰写中;submitted:已投稿:1;accepted:已录用:1;published:已发表:1", ["论文", "专利", "专著"]),
    ],
)

_extend(
    "医疗健康",
    [
        ("health-patients", "患者档案", "🧑‍⚕️", "患者基本信息、过敏史与联系人。", "gender:性别:select:男|女|其他;age:年龄:number;phone:联系电话;allergy:过敏史:textarea", "active:在册:1;followup:随访中;archived:已归档:1;deceased:已注销:1", ["门诊", "住院", "体检"]),
        ("health-appointments", "预约挂号", "📅", "号源、预约与爽约管理。", "patient:患者;department:科室;doctor:医生;visit_at:就诊时间:date", "booked:已预约:1;checked:已签到:1;cancelled:已取消:1;no_show:已爽约:1", ["普通", "专家", "急诊"]),
        ("health-encounters", "就诊记录", "🩺", "主诉、诊断与处置记录。", "patient:患者;doctor:医生;diagnosis:诊断;note:处置说明:textarea", "open:接诊中;closed:已完成:1;referred:已转诊:1;reopened:已复诊", ["初诊", "复诊", "急诊"]),
        ("health-prescriptions", "处方管理", "💊", "处方开具、审核与调配。", "patient:患者;drugs:药品;dosage:用法用量:textarea;days:天数:number", "draft:草稿;review:审核中;dispensed:已调配:1;voided:已作废:1", ["口服", "外用", "注射"]),
        ("health-lab-orders", "检验申请", "🧪", "检验项目、样本与结果。", "patient:患者;items:检验项目;sample:样本类型:select:血液|尿液|影像;result:结果摘要:textarea", "ordered:已开单;sampled:已采样;testing:检验中;reported:已出报告:1", ["常规", "生化", "免疫"]),
        ("health-imaging", "影像检查", "🖼", "影像申请、检查与报告。", "patient:患者;modality:检查类型:select:CT|MRI|X光|超声;body:检查部位;report:报告结论:textarea", "ordered:已申请;scheduled:已预约;performed:已检查;reported:已出报告:1", ["头颅", "胸部", "腹部"]),
        ("health-vaccinations", "疫苗接种", "💉", "疫苗批次、接种与不良反应。", "patient:患者;vaccine:疫苗;batch:批号;dose:剂次:number", "planned:待接种;done:已接种:1;delayed:已延迟;reaction:有反应", ["儿童", "成人", "加强"]),
        ("health-followups", "随访计划", "📞", "慢病随访、指标与干预。", "patient:患者;condition:病种;next:下次随访:date;follower:随访人", "planned:待随访;done:已完成:1;missed:已失访:1;closed:已结案:1", ["高血压", "糖尿病", "术后"]),
        ("health-insurance", "医保结算", "🧾", "结算单、报销比例与到账。", "patient:患者;amount:总金额:number;reimburse:报销金额:number;batch_no:结算批次", "pending:待结算;submitted:已提交:1;settled:已结算:1;rejected:已退回:1", ["门诊", "住院", "异地"]),
        ("health-inventory", "药品耗材", "📦", "药品耗材库存、效期与预警。", "item:品名;spec:规格;stock:库存:number;expire:有效期:date", "normal:正常:1;low:库存偏低;expiring:临近效期;expired:已过期:1", ["药品", "耗材", "试剂"]),
    ],
)

_extend(
    "政务与园区",
    [
        ("gov-permits", "行政许可", "🏛", "许可事项、材料与办结。", "applicant:申请人;matter:事项;deadline:承诺时限:date;officer:承办人", "received:已受理;reviewing:审核中;approved:已许可:1;rejected:不予许可:1", ["登记", "审批", "备案"]),
        ("gov-inspections", "执法检查", "🔍", "检查计划、问题与处罚。", "target:检查对象;checker:检查人;issues:问题描述:textarea;result:处理结果", "planned:待检查;ongoing:检查中;rectified:已整改:1;penalized:已处罚:1", ["日常", "专项", "双随机"]),
        ("gov-petitions", "信访件", "📨", "信访登记、转办与答复。", "petitioner:信访人;topic:诉求;assignee:承办人;deadline:办理期限:date", "new:待登记;assigned:已转办;handling:办理中;replied:已答复:1", ["来访", "来信", "网上"]),
        ("gov-assets", "国有资产", "🏢", "资产台账、使用与处置。", "asset_no:资产编号;asset_category:类别;value:原值:number;keeper:保管人", "in_use:使用中:1;idle:闲置;repair:维修中;disposed:已处置:1", ["房产", "车辆", "设备"]),
        ("gov-contracts", "政府合同", "📄", "合同签订、履约与付款。", "partner:相对方;amount:金额:number;sign_date:签订日期:date;contract_owner:负责人", "draft:草稿;active:履约中:1;completed:已完成:1;terminated:已解除:1", ["采购", "服务", "工程"]),
        ("gov-subsidies", "补贴申报", "💰", "补贴项目、申报与拨付。", "applicant:申报单位;program:项目;amount:申请金额:number;deadline:截止日期:date", "draft:草稿;submitted:已申报:1;reviewing:评审中;granted:已拨付:1", ["产业", "人才", "科技"]),
        ("gov-events", "政务活动", "🎤", "会议、培训与活动组织。", "place:地点;host:主办方;start:开始时间:date;attendees:参加人数:number", "planned:待举办;ongoing:进行中;done:已结束:1;cancelled:已取消:1", ["会议", "培训", "接待"]),
        ("gov-rooms", "园区房源", "🏬", "房源、面积与租赁状态。", "building:楼宇;floor:楼层;area:面积:number;tenant:承租方", "vacant:空置;reserved:已预订;leased:已出租:1;maintenance:维护中", ["办公", "厂房", "商业"]),
        ("gov-tenants", "园区企业", "🏢", "入驻企业、联系人与服务。", "industry:行业;contact:联系人;area:租赁面积:number;entry_date:入驻日期:date", "applying:申请中;active:已入驻:1;renewing:续约中;left:已退租:1", ["科技", "制造", "服务"]),
        ("gov-utilities", "园区能耗", "⚡", "水电气能耗与费用分摊。", "tenant:企业;type:能源类型:select:水|电|气;usage:用量:number;fee:费用:number", "pending:待抄表;billed:已出账:1;paid:已缴费:1;disputed:有异议", ["水", "电", "气"]),
    ],
)

_extend(
    "电商与零售",
    [
        ("retail-products", "商品管理", "🛍", "商品信息、类目与上下架。", "product_category:类目;brand:品牌;price:售价:number;supplier:供货商", "draft:草稿;on_sale:在售:1;off_sale:下架:1;sold_out:售罄", ["服饰", "食品", "数码"]),
        ("retail-skus", "SKU 规格", "🎨", "规格组合、条码与库存。", "product:商品;spec:规格;barcode:条码;stock:库存:number", "active:正常:1;low:低库存;out:缺货;disabled:已停用:1", ["颜色", "尺码", "套装"]),
        ("retail-orders", "线上订单", "🧾", "下单、支付与履约状态。", "channel:渠道:select:小程序|APP|网页;amount:金额:number;buyer:买家;paid_at:支付时间:date", "pending:待付款;paid:已付款:1;shipped:已发货:1;completed:已完成:1", ["自营", "平台", "直播"]),
        ("retail-carts", "购物车", "🛒", "购物车商品、价格与放弃原因。", "buyer:买家;items:商品数:number;amount:金额:number;note:备注:textarea", "active:活跃;abandoned:已放弃:1;converted:已下单:1;expired:已失效:1", ["加购", "待支付", "已转化"]),
        ("retail-coupons", "优惠券", "🎟", "券种、门槛与核销。", "type:类型:select:满减|折扣|免邮;value:面值:number;threshold:门槛:number;expire:有效期:date", "draft:草稿;active:发放中:1;exhausted:已领完:1;expired:已过期:1", ["满减", "折扣", "运费"]),
        ("retail-promotions", "促销活动", "📣", "活动排期、商品与效果。", "channel:渠道;start:开始日期:date;end:结束日期:date;budget:预算:number", "planned:待开始;running:进行中;ended:已结束:1;cancelled:已取消:1", ["大促", "日常", "清仓"]),
        ("retail-returns", "退货退款", "↩️", "退货原因、审核与退款。", "order:订单号;amount:退款金额:number;reason:原因;handler:处理人", "requested:待审核;approved:已同意:1;received:已收货;refunded:已退款:1", ["质量问题", "七天无理由", "错发"]),
        ("retail-reviews", "商品评价", "⭐", "评价内容、评分与回复。", "product:商品;rating:评分:number;user:用户;content:评价内容:textarea", "pending:待审核;published:已发布:1;hidden:已隐藏:1;replied:已回复:1", ["好评", "中评", "差评"]),
        ("retail-stores", "门店管理", "🏪", "门店档案、人员与营业状态。", "city:城市;manager:店长;staff:员工数:number;area:面积:number", "preparing:筹备中;open:营业中:1;closed:已闭店:1;renovating:装修中", ["直营", "加盟", "快闪"]),
        ("retail-inventory", "门店库存", "📦", "门店库存、调拨与盘点。", "store:门店;sku:SKU;stock:库存:number;alert:预警值:number", "normal:正常:1;low:低库存;out:缺货;counting:盘点中", ["在库", "在途", "锁定"]),
    ],
)

_extend(
    "物流与运输",
    [
        ("logistics-shipments", "运单管理", "🚚", "运单、起止地与签收状态。", "carrier:承运商;from_to:起止地;weight:重量:number;eta:预计到达:date", "created:已下单;picked:已提货;transit:运输中;delivered:已签收:1", ["整车", "零担", "快递"]),
        ("logistics-routes", "运输线路", "🗺", "线路、里程与时效。", "origin:始发地;destination:目的地;km:里程:number;hours:时效小时:number", "draft:草稿;active:启用中:1;suspended:已停用;optimized:已优化:1", ["干线", "支线", "城配"]),
        ("logistics-carriers", "承运商", "🤝", "承运商资质、价格与评级。", "contact:联系人;mode:运输方式:select:公路|铁路|航空|水运;price:单价:number;rating:评级:number", "pending:待审核;active:合作中:1;suspended:已暂停;blacklisted:已拉黑:1", ["快递", "专线", "车队"]),
        ("logistics-vehicles", "车辆档案", "🚛", "车辆信息、证照与保养。", "plate:车牌;type:车型;capacity:载重:number;expire:年检到期:date", "idle:空闲;in_transit:运输中;maintenance:保养中;retired:已停用:1", ["货车", "冷链车", "牵引车"]),
        ("logistics-drivers", "司机档案", "🧑‍✈️", "司机信息、证照与在途状态。", "phone:电话;license:驾照;route:常跑线路;expire:证件到期:date", "available:可派:1;driving:在途;resting:休息;suspended:已停派:1", ["全职", "兼职", "外包"]),
        ("logistics-deliveries", "配送任务", "📦", "配送排线、签收与异常。", "order:关联订单;driver:司机;address:地址;slot:配送时段:select:上午|下午|晚间", "assigned:已派单;enroute:配送中;delivered:已送达:1;failed:配送失败:1", ["即时", "预约", "批量"]),
        ("logistics-returns", "逆向物流", "↩️", "退货取件、质检与入库。", "order:原订单;reason:退回原因;pickup:取件时间:date;warehouse:目的仓", "requested:待取件;picked:已取件;received:已入库:1;scrapped:已报废:1", ["退货", "换货", "维修"]),
        ("logistics-warehouse-tasks", "仓储作业", "🏬", "收货、上架、拣货与盘点任务。", "warehouse:仓库;type:作业类型:select:收货|上架|拣货|盘点;operator:作业员;qty:数量:number", "pending:待执行;doing:进行中;done:已完成:1;exception:异常", ["入库", "出库", "库内"]),
        ("logistics-freight-bills", "运费账单", "💳", "运费核算、对账与结算。", "carrier:承运商;period:账期;amount:金额:number;status_note:对账说明:textarea", "draft:草稿;confirmed:已对账:1;paid:已结算:1;disputed:有争议", ["月结", "现结", "预付"]),
        ("logistics-exceptions", "物流异常", "⚠️", "延误、破损与丢件处理。", "shipment:运单;type:异常类型:select:延误|破损|丢件|拒收;handler:处理人;detail:异常说明:textarea", "open:待处理;handling:处理中;resolved:已解决:1;closed:已关闭:1", ["运输", "仓储", "配送"]),
    ],
)

_extend(
    "能源与环境",
    [
        ("energy-meters", "能源表计", "🔌", "表计档案、倍率与所属区域。", "type:类型:select:电表|水表|气表;location:位置;ratio:倍率:number;keeper:责任人", "active:正常:1;offline:离线;fault:故障;replaced:已更换:1", ["电", "水", "气"]),
        ("energy-readings", "抄表记录", "📈", "抄表读数、用量与异常。", "meter:表计;reading:读数:number;usage:用量:number;read_at:抄表日期:date", "pending:待抄;confirmed:已确认:1;estimated:估算:1;abnormal:异常", ["日抄", "月抄", "补抄"]),
        ("energy-consumption", "能耗分析", "📊", "区域/设备能耗与同比环比。", "scope:范围;period:周期;usage:用量:number;cost:费用:number", "draft:草稿;published:已发布:1;reviewed:已复核:1;archived:已归档:1", ["同比", "环比", "基准"]),
        ("energy-projects", "节能项目", "🌱", "节能改造项目、投资与收益。", "manager:负责人;investment:投资额:number;start:开始日期:date;saving:预计节能率:number", "draft:草稿;approved:已立项:1;running:实施中;verified:已验收:1", ["照明", "空调", "工艺"]),
        ("energy-emissions", "碳排放", "🌍", "排放源、核算与配额。", "source:排放源;scope:范围:select:范围一|范围二|范围三;amount:排放量:number;year:年度", "draft:草稿;calculated:已核算:1;verified:已核查:1;reported:已报送:1", ["直接", "间接", "供应链"]),
        ("energy-waste", "废弃物", "🗑", "废弃物分类、处置与转移。", "type:类型:select:一般固废|危废|可回收;weight:重量:number;handler:处置单位;manifest:联单号", "stored:暂存中;transferred:已转移:1;disposed:已处置:1;violation:违规", ["固废", "危废", "回收"]),
        ("env-monitoring", "环境监测", "🌡", "空气、水质与噪声监测。", "station:监测点;metric:指标;value:监测值:number;measured_at:监测时间:date", "normal:正常:1;warning:预警;exceeded:超标;offline:离线", ["空气", "水质", "噪声"]),
        ("env-permits", "环保许可", "📜", "排污许可、环评与有效期。", "type:类型:select:排污许可|环评|危废经营;authority:发证机关;expire:到期日:date;keeper:负责人", "draft:草稿;submitted:已申报:1;active:有效:1;expired:已过期:1", ["排污", "环评", "经营"]),
        ("env-incidents", "环境事件", "🚨", "泄漏、超标与应急处置。", "type:类型;severity:等级:select:一般|较大|重大;detail:事件描述:textarea;handler:处置人", "reported:已上报;handling:处置中;mitigated:已控制:1;closed:已结案:1", ["泄漏", "超标", "投诉"]),
        ("energy-equipment", "能源设备", "⚙️", "锅炉、空调与配电设备台账。", "type:类型;capacity:容量:number;location:位置;next_check:下次检验:date", "running:运行中:1;standby:备用;maintenance:检修中;retired:已退役:1", ["锅炉", "空调", "配电"]),
    ],
)

_extend(
    "传媒与内容",
    [
        ("media-assets", "素材库", "🖼", "图片、视频与音频素材。", "type:类型:select:图片|视频|音频|文档;size:大小MB:number;uploader:上传人;rights:版权状态:select:自有|授权|待确认", "draft:草稿;review:审核中;published:已发布:1;archived:已归档:1", ["图片", "视频", "音频"]),
        ("media-programs", "节目栏目", "📺", "栏目定位、档期与负责人。", "channel:渠道;frequency:更新频率:select:日更|周更|月更;producer:负责人;start:开播日期:date", "planning:筹备中;running:播出中:1;paused:已暂停;ended:已完结:1", ["新闻", "综艺", "专题"]),
        ("media-shoots", "拍摄任务", "🎬", "拍摄排期、场地与人员。", "program:栏目;location:场地;shoot_at:拍摄时间:date;crew:摄制组", "planned:待拍摄;confirmed:已确认:1;shooting:拍摄中;done:已完成:1", ["外景", "棚拍", "直播"]),
        ("media-editorial", "选题策划", "💡", "选题来源、角度与排期。", "angle:角度;source:来源;editor:编辑;publish_at:计划发布:date", "idea:灵感;review:评审中;approved:已通过:1;published:已发布:1", ["热点", "深度", "系列"]),
        ("media-distribution", "分发渠道", "📡", "平台账号、分发与数据回传。", "platform:平台;account:账号;followers:粉丝数:number;operator:运营", "active:运营中:1;paused:已暂停;banned:已封禁;review:审核中", ["短视频", "图文", "音频"]),
        ("media-rights", "版权管理", "©️", "版权来源、期限与授权范围。", "asset:素材;rights_holder:版权方;start:授权开始:date;end:授权结束:date", "pending:待确认;active:授权中:1;expiring:即将到期;expired:已过期:1", ["采购", "自制", "合作"]),
        ("media-influencers", "达人合作", "🤳", "达人档案、报价与合作记录。", "platform:平台;followers:粉丝数:number;quote:报价:number;contact:联系人", "prospect:储备中;negotiating:洽谈中;cooperating:合作中:1;ended:已结束:1", ["种草", "带货", "品牌"]),
        ("media-campaigns", "投放计划", "📢", "投放目标、预算与效果。", "channel:渠道;budget:预算:number;start:开始日期:date;roi:ROI:number", "draft:草稿;running:投放中:1;paused:已暂停;finished:已结束:1", ["品牌", "效果", "活动"]),
        ("media-analytics", "传播数据", "📊", "播放、互动与转化数据。", "program:内容;platform:平台;views:播放量:number;engagement:互动量:number", "pending:待采集;collected:已采集:1;verified:已复核:1;archived:已归档:1", ["日榜", "周榜", "专题"]),
        ("media-archives", "内容归档", "🗄", "成片、工程文件与归档位置。", "program:栏目;format:格式:select:成片|工程|字幕|海报;storage:存储位置;keeper:归档人", "pending:待归档;archived:已归档:1;restored:已调阅:1;lost:已遗失:1", ["长期", "临时", "备份"]),
    ],
)

_extend(
    "金融与风控",
    [
        ("fin-accounts", "账户管理", "🏦", "账户开立、余额与状态。", "bank:开户行;account_no:账号;balance:余额:number;manager:负责人", "active:正常:1;frozen:已冻结;closed:已销户:1;review:审核中", ["基本户", "一般户", "专户"]),
        ("fin-transactions", "交易流水", "💳", "收支流水、对方与凭证。", "account:账户;direction:方向:select:收入|支出;amount:金额:number;voucher:凭证号", "pending:待确认;confirmed:已确认:1;reconciled:已对账:1;voided:已作废:1", ["收款", "付款", "转账"]),
        ("fin-loans", "贷款申请", "🏦", "贷款金额、期限与审批。", "borrower:借款人;amount:金额:number;term:期限月:number;rate:利率:number", "draft:草稿;submitted:已提交:1;approved:已批准:1;disbursed:已放款:1", ["信用", "抵押", "担保"]),
        ("fin-repayments", "还款计划", "📅", "期次、本息与逾期。", "loan:贷款;period:期次:number;due:应还日期:date;amount:应还金额:number", "pending:待还款;paid:已还款:1;overdue:已逾期;restructured:已重组:1", ["等额本息", "等额本金", "先息后本"]),
        ("fin-credit-reviews", "授信审查", "🔍", "授信额度、评级与结论。", "customer:客户;amount:申请额度:number;rating:评级:select:AAA|AA|A|B;reviewer:审查人", "draft:草稿;reviewing:审查中;approved:已通过:1;rejected:已拒绝:1", ["新增", "调整", "复审"]),
        ("fin-collateral", "抵质押物", "🏠", "押品估值、权属与状态。", "type:类型:select:房产|设备|存货|股权;value:估值:number;holder:权属人;expire:到期日:date", "pending:待评估;approved:已准入:1;pledged:已抵质押:1;released:已解押:1", ["房产", "设备", "存货"]),
        ("fin-fraud-cases", "反欺诈案件", "🕵", "欺诈线索、调查与处置。", "type:类型:select:申请欺诈|交易欺诈|团伙;amount:涉案金额:number;investigator:调查人;detail:案情描述:textarea", "reported:已上报;investigating:调查中;confirmed:已确认:1;closed:已结案:1", ["信贷", "交易", "账户"]),
        ("fin-aml-alerts", "反洗钱预警", "🚨", "可疑交易、评级与上报。", "customer:客户;amount:涉及金额:number;rule:命中规则;handler:处理人", "new:待处理;reviewing:分析中;reported:已上报:1;dismissed:已排除:1", ["大额", "频繁", "跨境"]),
        ("fin-collections", "催收任务", "📞", "逾期账务、催收与承诺还款。", "customer:客户;overdue:逾期金额:number;days:逾期天数:number;collector:催收员", "new:待分配;contacting:催收中;promised:已承诺:1;settled:已结清:1", ["电话", "上门", "法务"]),
        ("fin-products", "金融产品", "📦", "产品要素、利率与上线状态。", "type:类型:select:存款|贷款|理财|保险;rate:利率:number;term:期限月:number;product_owner:产品经理", "draft:草稿;review:审核中;online:已上线:1;offline:已下线:1", ["存款", "贷款", "理财"]),
    ],
)

_extend(
    "农业与食品",
    [
        ("agri-farms", "农场档案", "🚜", "农场主体、面积与认证。", "location:所在地;area:面积:number;manager:负责人;cert:认证类型:select:有机|绿色|无公害|普通", "active:经营中:1;idle:闲置;paused:已暂停;closed:已注销:1", ["种植", "养殖", "综合"]),
        ("agri-plots", "地块管理", "🗺", "地块编号、面积与作物。", "farm:农场;area:面积:number;soil:土壤类型;crop:当前作物", "idle:空闲;planted:已种植:1;harvesting:采收中;fallow:休耕", ["大田", "大棚", "果园"]),
        ("agri-crops", "作物计划", "🌾", "种植计划、投入与目标产量。", "crop:作物;plot:地块;plant_at:播种日期:date;yield_target:目标产量:number", "planned:待播种;growing:生长中;harvested:已采收:1;failed:已失败:1", ["粮食", "蔬菜", "经济作物"]),
        ("agri-livestock", "畜禽档案", "🐄", "畜禽批次、存栏与免疫。", "species:种类:select:猪|牛|羊|禽;count:存栏数:number;barn:圈舍;immune:免疫状态", "active:在养:1;sold:已出栏:1;quarantine:隔离中;dead:已死亡:1", ["生猪", "肉牛", "家禽"]),
        ("agri-harvests", "采收记录", "🧺", "采收批次、产量与等级。", "crop:作物;plot:地块;weight:产量:number;grade:等级:select:一级|二级|等外", "planned:待采收;harvesting:采收中;stored:已入库:1;sold:已销售:1", ["鲜销", "加工", "留种"]),
        ("agri-pesticides", "农资使用", "🧴", "农药化肥使用与安全间隔。", "type:类型:select:农药|化肥|种子;product:品名;amount:用量:number;safe_days:安全间隔天:number", "planned:待使用;applied:已使用:1;expired:已过期;violation:违规使用", ["农药", "化肥", "种子"]),
        ("agri-traceability", "溯源批次", "🔗", "批次来源、流向与扫码记录。", "batch:批次号;product:产品;origin:产地;destination:流向", "created:已建档:1;in_transit:流通中;delivered:已送达:1;recalled:已召回:1", ["种植", "养殖", "加工"]),
        ("agri-cold-chain", "冷链记录", "❄️", "冷链温度、时长与异常。", "batch:批次;vehicle:车辆;temp:温度:number;duration:时长小时:number", "loading:装车中;transit:运输中;delivered:已交付:1;excursion:温度异常", ["仓储", "运输", "配送"]),
        ("agri-food-safety", "食品安全检查", "🧪", "检查项目、抽检与整改。", "target:检查对象;item:检查项目;result:结果:select:合格|不合格|复检;samples:抽样数:number", "planned:待检查;passed:合格:1;failed:不合格;closed:已整改:1", ["生产", "流通", "餐饮"]),
        ("agri-subsidies", "农业补贴", "💰", "补贴项目、面积与发放。", "farmer:农户;program:项目;area:申报面积:number;amount:补贴金额:number", "draft:草稿;submitted:已申报:1;approved:已审核:1;paid:已发放:1", ["种粮", "农机", "保险"]),
    ],
)

_extend(
    "建筑与工程",
    [
        ("construction-projects", "工程项目", "🏗", "项目概况、造价与工期。", "client:建设单位;budget:造价:number;start:开工日期:date;manager:项目经理", "planning:筹备中;building:在建:1;completed:已竣工:1;suspended:已停工", ["房建", "市政", "装饰"]),
        ("construction-drawings", "图纸管理", "📐", "图纸版本、专业与交底。", "project:项目;discipline:专业:select:建筑|结构|机电|装饰;version:版本;designer:设计人", "draft:草稿;review:审核中;approved:已批准:1;obsolete:已作废:1", ["方案图", "施工图", "竣工图"]),
        ("construction-permits", "施工许可", "📜", "许可事项、证号与有效期。", "project:项目;type:类型:select:施工许可|规划许可|消防;cert_no:证号;expire:有效期:date", "draft:草稿;submitted:已申报:1;approved:已发证:1;expired:已过期:1", ["开工", "规划", "消防"]),
        ("construction-subcontractors", "分包商", "🤝", "分包商资质、合同与评价。", "scope:分包范围;qualification:资质等级;amount:合同额:number;rating:评价:number", "pending:待准入;active:合作中:1;suspended:已暂停;exited:已退场:1", ["劳务", "专业", "材料"]),
        ("construction-progress", "进度填报", "📊", "形象进度、完成率与偏差。", "project:项目;milestone:里程碑;percent:完成率:number;report_at:填报日期:date", "draft:草稿;submitted:已提交:1;approved:已确认:1;delayed:已滞后", ["周报", "月报", "节点"]),
        ("construction-materials", "材料进场", "🧱", "材料报验、批次与检测。", "project:项目;material:材料;qty:数量:number;supplier:供应商", "planned:待进场;inspecting:待报验;accepted:已验收:1;rejected:已退回:1", ["主材", "辅材", "周转料"]),
        ("construction-inspections", "现场检查", "🔍", "质量安全巡检与整改。", "project:项目;area:区域;checker:检查人;issue:问题描述:textarea", "planned:待检查;passed:合格:1;issue:发现问题;closed:已整改:1", ["质量", "安全", "文明施工"]),
        ("construction-safety", "安全交底", "🦺", "交底内容、人员与签字。", "project:项目;type:类型:select:三级教育|班前会|专项;present:参加人数:number;trainer:交底人", "planned:待交底;done:已完成:1;missing:有缺席;closed:已归档:1", ["教育", "班前", "专项"]),
        ("construction-variations", "变更签证", "🔁", "变更原因、金额与审批。", "project:项目;reason:变更原因;amount:变更金额:number;approver:审批人", "draft:草稿;review:审核中;approved:已批准:1;rejected:已驳回:1", ["设计", "现场", "材料"]),
        ("construction-settlements", "竣工结算", "🧾", "结算金额、审核与支付。", "project:项目;amount:结算金额:number;auditor:审核人;pay_date:付款日期:date", "draft:草稿;submitted:已报送:1;audited:已审定:1;paid:已支付:1", ["总包", "分包", "材料"]),
    ],
)

MODULE_INDEX = {x["slug"]: x for x in MODULES}

for _mod in MODULES:
    _mod["feature_keys"] = feature_keys(_mod["slug"])
    _mod["features"] = feature_detail(_mod["slug"])
    _mod["feature_count"] = len(_mod["feature_keys"])

FEATURE_TOTAL = sum(x["feature_count"] for x in MODULES)
assert len(MODULES) == len(MODULE_INDEX) == 154, "bizhub 模块数必须为 154"
assert FEATURE_TOTAL == 4500, f"bizhub 功能总数必须为 4500，当前 {FEATURE_TOTAL}"

GROUP_ORDER = [
    "销售与市场",
    "供应链",
    "制造与生产",
    "人力",
    "财务与合规",
    "金融与风控",
    "客服与支持",
    "电商与零售",
    "物流与运输",
    "教育科研",
    "医疗健康",
    "政务与园区",
    "能源与环境",
    "农业与食品",
    "传媒与内容",
    "建筑与工程",
    "数据与平台",
    "法务与安全",
]


def module_public(mod):
    """返回给前端的模块元数据（详情页用，含 30 项功能明细）。"""
    return {
        "slug": mod["slug"],
        "name": mod["name"],
        "group": mod["group"],
        "icon": mod["icon"],
        "description": mod["description"],
        "fields": mod["fields"],
        "statuses": mod["statuses"],
        "categories": mod["categories"],
        "feature_count": mod["feature_count"],
        "features": mod["features"],
    }


def module_summary(mod):
    """目录页/侧边栏用的轻量元数据（不含功能明细，避免一次返回 1000 条）。"""
    return {
        "slug": mod["slug"],
        "name": mod["name"],
        "group": mod["group"],
        "icon": mod["icon"],
        "description": mod["description"],
        "statuses": mod["statuses"],
        "categories": mod["categories"],
        "feature_count": mod["feature_count"],
    }


def catalog():
    groups = []
    for g in GROUP_ORDER:
        items = [module_summary(x) for x in MODULES if x["group"] == g]
        if items:
            groups.append({"name": g, "count": len(items), "modules": items})
    return {
        "module_count": len(MODULES),
        "feature_count": FEATURE_TOTAL,
        "groups": groups,
        "modules": [module_summary(x) for x in MODULES],
    }
