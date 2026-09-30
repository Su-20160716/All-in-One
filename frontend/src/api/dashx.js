/**
 * 仪表盘今日卡片 / 最近动态 / 卡片顺序接口（F657–F660、F666–F668）
 * 与 src/api/index.js 里的 dashApi 并列，避免改动既有 index.js。
 */
import request from './request'

export const dashx = {
  todayDue: () => request.get('/dashboard/today-due/'),
  todayLearning: (goal) => request.get('/dashboard/today-learning/', { params: goal ? { goal } : {} }),
  todaySchedule: () => request.get('/dashboard/today-schedule/'),
  storageUsage: () => request.get('/dashboard/storage-usage/'),
  recentActivity: () => request.get('/dashboard/recent-activity/'),
  cardOrder: () => request.get('/dashboard/card-order/'),
  saveCardOrder: (order) => request.put('/dashboard/card-order/', { order }),
}
