/**
 * 业务中心静态兜底目录（34 个初始模块；运行期以 /api/biz/modules/ 的全量模块为准）。
 *
 * 只放「前端即可确定」的展示元数据：路由、侧边栏、目录页都以这里为准。
 * 运行期能力数、字段、状态集等由 /api/biz/modules/ 与 /api/biz/modules/<slug>/ 返回，
 * 后端不可用时页面用本目录兜底渲染，不伪造业务数据。
 */

/** 分组顺序（目录页 / 设置页都按此顺序渲染；与后端 GROUP_ORDER 对齐） */
export const BIZ_GROUP_ORDER = [
  '销售与市场',
  '供应链',
  '制造与生产',
  '人力',
  '财务与合规',
  '金融与风控',
  '客服与支持',
  '电商与零售',
  '物流与运输',
  '教育科研',
  '医疗健康',
  '政务与园区',
  '能源与环境',
  '农业与食品',
  '传媒与内容',
  '建筑与工程',
  '数据与平台',
  '法务与安全',
]

/** 34 个业务模块：slug 与后端 /api/biz/<slug>/ 一一对应 */
export const bizCatalog = [
  // ── 销售与市场 ────────────────────────────────────────────────
  { slug: 'crm-accounts', name: '客户档案', group: '销售与市场', icon: '👥', description: '统一维护客户主数据、联系人与合作状态' },
  { slug: 'crm-leads', name: '销售线索', group: '销售与市场', icon: '🎯', description: '线索捕获、评分与分配跟进' },
  { slug: 'crm-opportunities', name: '商机管理', group: '销售与市场', icon: '💰', description: '跟踪商机阶段、金额与赢单概率' },
  { slug: 'sales-quotes', name: '报价单', group: '销售与市场', icon: '🧾', description: '报价编制、审批与版本留痕' },
  { slug: 'sales-orders', name: '销售订单', group: '销售与市场', icon: '📦', description: '订单履约、回款与交付进度跟踪' },
  { slug: 'product-catalog', name: '产品目录', group: '销售与市场', icon: '🏷', description: '产品规格、价格与上下架管理' },
  { slug: 'campaigns', name: '市场活动', group: '销售与市场', icon: '📣', description: '活动策划、预算与效果复盘' },
  { slug: 'content-calendar', name: '内容日历', group: '销售与市场', icon: '🗓', description: '内容排期与多渠道发布计划' },
  { slug: 'competitor-intel', name: '竞品情报', group: '销售与市场', icon: '🔭', description: '竞品动态收集与对比分析' },

  // ── 供应链 ────────────────────────────────────────────────────
  { slug: 'suppliers', name: '供应商', group: '供应链', icon: '🏭', description: '供应商准入、评级与资质管理' },
  { slug: 'purchase-orders', name: '采购单', group: '供应链', icon: '🛒', description: '采购申请、下单到收货全流程' },
  { slug: 'warehouses', name: '仓库管理', group: '供应链', icon: '🏬', description: '仓库分布、容量与责任人管理' },
  { slug: 'inventory-items', name: '库存物料', group: '供应链', icon: '📊', description: '物料库存、补货与盘点核对' },

  // ── 人力 ──────────────────────────────────────────────────────
  { slug: 'recruitment-jobs', name: '招聘职位', group: '人力', icon: '🧑‍💼', description: '职位发布、需求与招聘进度管理' },
  { slug: 'candidates', name: '候选人', group: '人力', icon: '👤', description: '候选人跟进、面试与录用决策' },
  { slug: 'onboarding', name: '入职任务', group: '人力', icon: '🪪', description: '新人入职流程与资料收集' },
  { slug: 'performance-reviews', name: '绩效评估', group: '人力', icon: '📈', description: '周期考核、评级与目标达成评估' },
  { slug: 'payroll-runs', name: '薪酬批次', group: '人力', icon: '💵', description: '月度薪酬核算、审批与发放跟踪' },
  { slug: 'attendance-exceptions', name: '考勤异常', group: '人力', icon: '⏰', description: '迟到、缺卡与请假异常处理' },

  // ── 财务与合规 ────────────────────────────────────────────────
  { slug: 'invoices', name: '发票台账', group: '财务与合规', icon: '🧾', description: '开票、收票与核销台账管理' },
  { slug: 'budgets', name: '预算计划', group: '财务与合规', icon: '🧮', description: '部门预算编制与执行监控' },
  { slug: 'compliance-checks', name: '合规检查', group: '财务与合规', icon: '✅', description: '合规项自查、评分与整改闭环' },
  { slug: 'risk-register', name: '风险登记', group: '财务与合规', icon: '⚠️', description: '风险识别、评级与应对措施跟踪' },
  { slug: 'audit-findings', name: '审计问题', group: '财务与合规', icon: '🔍', description: '审计发现、责任人与整改跟踪' },

  // ── 数据与平台 ────────────────────────────────────────────────
  { slug: 'data-catalog', name: '数据资产', group: '数据与平台', icon: '🗃', description: '数据表、数据集资产登记与血缘' },
  { slug: 'metric-dictionary', name: '指标字典', group: '数据与平台', icon: '📐', description: '指标口径、计算逻辑与责任人统一' },
  { slug: 'integration-apps', name: '集成应用', group: '数据与平台', icon: '🔌', description: '第三方应用接入、凭据与状态管理' },
  { slug: 'automation-rules', name: '自动化规则', group: '数据与平台', icon: '⚙️', description: '触发器、条件与自动化动作编排' },
  { slug: 'report-subscriptions', name: '报表订阅', group: '数据与平台', icon: '📬', description: '报表定时推送与订阅人管理' },

  // ── 法务与安全 ────────────────────────────────────────────────
  { slug: 'legal-cases', name: '法务案件', group: '法务与安全', icon: '⚖️', description: '诉讼、仲裁与法律事务进度跟踪' },
  { slug: 'ip-portfolio', name: '知识产权', group: '法务与安全', icon: '💡', description: '商标、专利等 IP 资产台账' },
  { slug: 'privacy-requests', name: '隐私请求', group: '法务与安全', icon: '🛡', description: '个人信息查询、删除请求响应' },
  { slug: 'incident-reports', name: '事故报告', group: '法务与安全', icon: '🚨', description: '安全事件上报、处置与复盘' },
  { slug: 'asset-maintenance', name: '设备维保', group: '法务与安全', icon: '🔧', description: '设备台账、保养计划与维修记录' },
]

/** 分组后的目录：[{name, modules}]，空分组自动剔除 */
export const bizGroups = BIZ_GROUP_ORDER.map((name) => ({
  name,
  modules: bizCatalog.filter((m) => m.group === name),
})).filter((g) => g.modules.length)

/** 按 slug 查模块；未命中返回 null */
export function findBizModule(slug) {
  return bizCatalog.find((m) => m.slug === slug) || null
}

export default bizCatalog
