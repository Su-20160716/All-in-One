/**
 * S26 开发者平台接口（#415/#418/#419/#420）：
 * 开发者门户汇总、Webhook 事件订阅与投递、签名自测、PAT 用量、接口用量报表、
 * 定时任务到期触发。与 src/api/authx.js、corex.js 互补，只新增文件不改动既有模块。
 */
import request from './request'

export const developerxApi = {
  // ---- #420 开发者门户四卡片（令牌 / 近 7 天调用 / 订阅 / 失败投递）----
  summary: () => request.get('/core/developer/summary/'),

  // ---- #419 错误码目录（前端启动时由 request.js 自行拉取，此处供页面查询）----
  errorCatalog: () => request.get('/core/errors/catalog/'),

  // ---- #411 Webhook 事件订阅 ----
  subscriptions: () => request.get('/core/webhooks/subscriptions/'),
  // data: { url, events: 'a,b' | ['a','b'], active, secret? }
  createSubscription: (data) => request.post('/core/webhooks/subscriptions/', data),
  updateSubscription: (id, data) => request.patch(`/core/webhooks/subscriptions/${id}/`, data),
  deleteSubscription: (id) => request.delete(`/core/webhooks/subscriptions/${id}/`),

  // ---- #412 投递记录与重试 ----
  deliveries: (params) => request.get('/core/webhooks/deliveries/', { params }),
  retryDelivery: (id) => request.post(`/core/webhooks/deliveries/${id}/retry/`, {}),

  // ---- #413 签名自测：{ subscription_id } 生成签名头，可再带 url 真实投递 ----
  verifyWebhook: (data) => request.post('/core/webhooks/verify/', data),

  // ---- #415 单个 PAT 的按日调用量（days 默认 30）----
  tokenUsage: (id, days = 30) =>
    request.get(`/auth/profile/tokens/${id}/usage/`, { params: { days } }),

  // ---- #418 管理端接口用量报表（按 app 聚合）----
  apiUsage: (days = 7) => request.get('/core/admin/api-usage/', { params: { days } }),

  // ---- #417 执行当前分钟到期的定时任务（外部 cron 同款入口）----
  runDueSchedules: () => request.post('/core/admin/schedules/due/', {}),
}

export default developerxApi
