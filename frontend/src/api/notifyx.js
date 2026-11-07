/**
 * 通知中心专用接口（#334-#339）：分组未读、分类筛选、整类已读、稍后提醒、
 * 通知偏好（免打扰预览 / 每日简报）与 Webhook 自检。
 * 与 src/api/index.js 的 coreApi 通知方法并存，避免改动既有 index.js。
 */
import request from './request'

export const notifyx = {
  list: (params) => request.get('/core/notifications/', { params }),
  unread: (params) => request.get('/core/notifications/unread-count/', { params }),
  // 传 { ids } 标记指定 / 传 { category } 整类已读 / 都不传则全部已读
  markRead: (data = {}) => request.post('/core/notifications/read/', data),
  snooze: (ids, minutes = 60) => request.post('/core/notifications/snooze/', { ids, minutes }),
  deleteRead: () => request.post('/core/notifications/delete/', { scope: 'read' }),
  settings: () => request.get('/core/notifications/settings/'),
  saveSettings: (payload) => request.post('/core/notifications/settings/', payload),
  testWebhook: (webhook_url) => request.post('/core/notifications/settings/test-webhook/', { webhook_url }),
}
