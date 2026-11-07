/**
 * 平台能力域静态目录。
 *
 * 12 个域共享同一套「总览 / 台账 / 分析 / 配置」工作台骨架，
 * 路由、侧边栏、页面标题与页签都从这里取，避免多处硬编码漂移。
 * 字段约定：
 * - key        域标识，与后端 URL 前缀一致
 * - route      前端路由（AppShell 子路由）
 * - basePath   后端接口前缀（不含 /api）
 * - tabs       页面内页签 key 与中文名，顺序即展示顺序
 */
export const PLATFORM_DOMAINS = [
  {
    key: 'workflow',
    name: '流程引擎',
    short: '流程',
    symbol: '◇',
    tone: 'brand',
    route: '/platform/workflow',
    basePath: '/workflow',
    description: '流程定义、版本发布、并行分支、待办审批与 SLA 监控。',
    tabs: [
      { key: 'overview', label: '运行总览' },
      { key: 'definitions', label: '流程定义' },
      { key: 'tasks', label: '我的待办' },
      { key: 'instances', label: '实例监控' },
      { key: 'analytics', label: '效率分析' },
    ],
  },
  {
    key: 'formstudio',
    name: '表单设计器',
    short: '表单',
    symbol: '▤',
    tone: 'sky',
    route: '/platform/forms',
    basePath: '/formstudio',
    description: '表单建模、条件逻辑、校验计分、提交审核与字段统计。',
    tabs: [
      { key: 'overview', label: '表单总览' },
      { key: 'forms', label: '表单管理' },
      { key: 'submissions', label: '提交记录' },
      { key: 'analytics', label: '字段分析' },
      { key: 'settings', label: '模板与分享' },
    ],
  },
  {
    key: 'reporting',
    name: '报表与仪表盘',
    short: '报表',
    symbol: '▥',
    tone: 'indigo',
    route: '/platform/reporting',
    basePath: '/reporting',
    description: '数据集编译、报表组件、仪表盘布局、计划任务与导出。',
    tabs: [
      { key: 'overview', label: '执行总览' },
      { key: 'reports', label: '报表' },
      { key: 'dashboards', label: '仪表盘' },
      { key: 'datasets', label: '数据集' },
      { key: 'schedules', label: '计划任务' },
    ],
  },
  {
    key: 'rules',
    name: '规则引擎',
    short: '规则',
    symbol: '⌘',
    tone: 'amber',
    route: '/platform/rules',
    basePath: '/rules',
    description: '规则集、决策表、表达式求值、冲突检测与仿真测试。',
    tabs: [
      { key: 'overview', label: '规则总览' },
      { key: 'rulesets', label: '规则集' },
      { key: 'tables', label: '决策表' },
      { key: 'simulate', label: '仿真评估' },
      { key: 'analytics', label: '命中分析' },
    ],
  },
  {
    key: 'contracts',
    name: '合同中心',
    short: '合同',
    symbol: '▣',
    tone: 'emerald',
    route: '/platform/contracts',
    basePath: '/contracts',
    description: '模板条款、审批签署、履约义务、收付款与到期续约。',
    tabs: [
      { key: 'overview', label: '合同总览' },
      { key: 'contracts', label: '合同台账' },
      { key: 'obligations', label: '履约义务' },
      { key: 'finance', label: '收付款' },
      { key: 'templates', label: '模板条款' },
    ],
  },
  {
    key: 'pipeline',
    name: '数据管道',
    short: '管道',
    symbol: '⇉',
    tone: 'cyan',
    route: '/platform/pipeline',
    basePath: '/pipeline',
    description: '连接器、DAG 编排、转换执行、质量规则与血缘追踪。',
    tabs: [
      { key: 'overview', label: '运行总览' },
      { key: 'pipelines', label: '管道编排' },
      { key: 'runs', label: '运行记录' },
      { key: 'quality', label: '数据质量' },
      { key: 'lineage', label: '血缘图谱' },
    ],
  },
  {
    key: 'billing',
    name: '订阅计费',
    short: '计费',
    symbol: '◫',
    tone: 'rose',
    route: '/platform/billing',
    basePath: '/billing',
    description: '套餐定价、订阅生命周期、用量计费、发票支付与催收。',
    tabs: [
      { key: 'overview', label: '收入总览' },
      { key: 'subscriptions', label: '订阅' },
      { key: 'invoices', label: '发票' },
      { key: 'usage', label: '用量' },
      { key: 'plans', label: '套餐' },
    ],
  },
  {
    key: 'marketplace',
    name: '应用市场',
    short: '市场',
    symbol: '◈',
    tone: 'violet',
    route: '/platform/marketplace',
    basePath: '/marketplace',
    description: '应用上架审核、版本兼容、安装授权、评价与收入分成。',
    tabs: [
      { key: 'overview', label: '市场总览' },
      { key: 'listings', label: '应用目录' },
      { key: 'installs', label: '我的安装' },
      { key: 'publishers', label: '发布者' },
      { key: 'analytics', label: '运营分析' },
    ],
  },
  {
    key: 'flags',
    name: '功能开关',
    short: '开关',
    symbol: '◐',
    tone: 'orange',
    route: '/platform/flags',
    basePath: '/flags',
    description: '灰度发布、定向规则、细分受众、A/B 实验与护栏。',
    tabs: [
      { key: 'overview', label: '开关总览' },
      { key: 'flags', label: '开关列表' },
      { key: 'experiments', label: '实验' },
      { key: 'segments', label: '细分受众' },
      { key: 'analytics', label: '评估分析' },
    ],
  },
  {
    key: 'observability',
    name: '可观测性',
    short: '观测',
    symbol: '◉',
    tone: 'teal',
    route: '/platform/observability',
    basePath: '/observability',
    description: '指标采集、SLO 与错误预算、告警、事故与值班升级。',
    tabs: [
      { key: 'overview', label: '健康总览' },
      { key: 'services', label: '服务' },
      { key: 'slos', label: 'SLO' },
      { key: 'incidents', label: '事故' },
      { key: 'oncall', label: '值班告警' },
    ],
  },
  {
    key: 'knowledgegraph',
    name: '知识图谱',
    short: '图谱',
    symbol: '⟡',
    tone: 'blue',
    route: '/platform/graph',
    basePath: '/knowledgegraph',
    description: '本体建模、实体关系、路径查询、实体合并与图谱统计。',
    tabs: [
      { key: 'overview', label: '图谱总览' },
      { key: 'entities', label: '实体' },
      { key: 'relations', label: '关系' },
      { key: 'explore', label: '图查询' },
      { key: 'ontology', label: '本体建模' },
    ],
  },
  {
    key: 'governance',
    name: '合规治理',
    short: '治理',
    symbol: '▦',
    tone: 'slate',
    route: '/platform/governance',
    basePath: '/governance',
    description: '框架控制、策略评估、风险处置、隐私保留与审计整改。',
    tabs: [
      { key: 'overview', label: '合规看板' },
      { key: 'framework', label: '框架控制' },
      { key: 'assessments', label: '评估' },
      { key: 'risks', label: '风险' },
      { key: 'privacy', label: '隐私审计' },
    ],
  },
]

export const DOMAIN_INDEX = PLATFORM_DOMAINS.reduce((acc, item) => {
  acc[item.key] = item
  return acc
}, {})

export function findDomain(key) {
  return DOMAIN_INDEX[key] || null
}

/** 侧边栏分组用的精简列表（按路由顺序） */
export const PLATFORM_MENU = PLATFORM_DOMAINS.map((d) => ({
  to: d.route,
  label: d.name,
  icon: d.symbol,
  key: d.key,
}))

/** 已交付页面的域；未交付的域保留元信息但不注册路由与菜单 */
export const READY_DOMAIN_KEYS = [
  'workflow',
  'formstudio',
  'reporting',
  'rules',
  'contracts',
  'pipeline',
  'billing',
  'marketplace',
]

export const PLATFORM_MENU_READY = PLATFORM_DOMAINS.filter((d) => READY_DOMAIN_KEYS.includes(d.key)).map((d) => ({
  to: d.route,
  label: d.name,
  icon: d.symbol,
  key: d.key,
}))

export default PLATFORM_DOMAINS