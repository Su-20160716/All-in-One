/**
 * 仪表盘今日卡片 / 最近动态 / 卡片顺序接口（F657–F660、F666–F668）
 * 与 src/api/index.js 里的 dashApi 并列，避免改动既有 index.js。
 * #331-#350：布局尺寸/分组、环比、活动筛选、提及/里程碑/健康、简报、延期、错误重试。
 */
import request from './request'

export const dashx = {
  todayDue: (includeOverdue = false) => request.get('/dashboard/today-due/', {
    params: includeOverdue ? { include_overdue: 1 } : {},
  }),
  todayLearning: (goal) => request.get('/dashboard/today-learning/', { params: goal ? { goal } : {} }),
  todaySchedule: () => request.get('/dashboard/today-schedule/'),
  storageUsage: () => request.get('/dashboard/storage-usage/'),
  recentActivity: (module) => request.get('/dashboard/recent-activity/', {
    params: module ? { module } : {},
  }),
  personalTrend: (params) => request.get('/dashboard/personal-trend/', { params }),
  cardOrder: () => request.get('/dashboard/card-order/'),
  saveCardOrder: (order) => request.put('/dashboard/card-order/', { order }),
  // #331/#332 布局（卡片尺寸/分组）持久化
  layout: () => request.get('/dashboard/layout/'),
  saveLayout: (layout) => request.put('/dashboard/layout/', { layout }),
  // #344-#346 提及 / 里程碑 / 项目健康
  mentions: (limit = 5) => request.get('/dashboard/mentions/', { params: { limit } }),
  milestones: (days = 7, includeOverdue = true) => request.get('/dashboard/milestones/', {
    params: { days, include_overdue: includeOverdue ? 1 : 0 },
  }),
  projectHealth: (limit = 20) => request.get('/dashboard/project-health/', { params: { limit } }),
  // #347 每日简报最近一期 + 定时配置 / 立即推送
  dailySummary: () => request.get('/dashboard/daily-summary/'),
  pushDailySummary: (payload = {}) => request.post('/dashboard/daily-summary/push/', payload),
  // #348 逾期项一键延期
  postponeDue: (kind, id, days = 1) => request.post('/dashboard/postpone-due/', { kind, id, days }),
}
