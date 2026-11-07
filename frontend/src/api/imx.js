/**
 * IM 第三轮增强接口（docs/16 第 306–330 项）
 * 只封装新增能力，不改动 src/api/index.js 既有契约。
 */
import request from './request'

export const imx = {
  // #306 消息编辑（本人 10 分钟内）
  editMessage: (id, content) => request.post(`/im/messages/${id}/edit/`, { content }),
  // #307 为所有人删除（发送者 / 群主 / 管理员）
  deleteForAll: (id) => request.post(`/im/messages/${id}/delete-for-all/`),
  // #308 消息翻译（target_lang 仅 zh / en）
  translate: (id, targetLang = 'en') =>
    request.post(`/im/messages/${id}/translate/`, { target_lang: targetLang }),
  // #309 已读明细（已读 / 未读两栏 + 未读者 id 列表）
  readers: (id) => request.get(`/im/messages/${id}/readers/`),
  // #310 待办清单（sort=remind 按到期排序）
  todos: (params = {}) => request.get('/im/todo/', { params }),
  createTodo: (payload) => request.post('/im/todo/', payload),
  updateTodo: (id, payload) => request.patch(`/im/todo/${id}/`, payload),
  deleteTodo: (id) => request.delete(`/im/todo/${id}/`),
  // #311 @我的消息
  mentions: (params = {}) => request.get('/im/mentions/', { params }),
  // #312 会话统计
  stats: (sessionId) => request.get(`/im/sessions/${sessionId}/stats/`),
  // #313 首条未读与上下文
  unreadLine: (sessionId) => request.get(`/im/sessions/${sessionId}/unread-line/`),
  // #314 正在输入上报（typing=false 主动结束）
  typing: (sessionId, typing) =>
    request.post(`/im/sessions/${sessionId}/typing/`, { typing: !!typing }),

  // #315 会话列表（tags 多选并集；返回 tags / active_tags）
  sessions: (params = {}) => request.get('/im/sessions/', { params }),
  // #315 标签 / 草稿等成员会话设置
  setSetting: (sessionId, payload) =>
    request.post(`/im/sessions/${sessionId}/setting/`, payload),
  // #317 群公告读取（markRead=1 顺手标记已读）
  announcement: (sessionId, markRead = false) =>
    request.get(`/im/sessions/${sessionId}/announcement/`, {
      params: markRead ? { mark_read: 1 } : {},
    }),
  // #317 群主发布公告
  publishAnnouncement: (sessionId, announcement) =>
    request.post(`/im/sessions/${sessionId}/announcement/`, { announcement }),
  // #318 关键词最近命中
  keywordHits: () => request.get('/im/keyword-alert/hits/'),
  // #319 快捷回复（分组 / 排序）
  quickReplies: (group) =>
    request.get('/im/quick-replies/', { params: group ? { group } : {} }),
  createQuickReply: (payload) => request.post('/im/quick-replies/', payload),
  updateQuickReply: (id, payload) => request.patch(`/im/quick-replies/${id}/`, payload),
  deleteQuickReply: (id) => request.delete(`/im/quick-replies/${id}/`),
  reorderQuickReplies: (items) => request.post('/im/quick-replies/reorder/', { items }),
  // #320 全局消息搜索（发送人 / 类型 / 日期 / 含附件 / 分页）
  searchMessages: (params = {}) =>
    request.get('/im/sessions/search-messages/', { params }),
  // #321 会话消息分页（before 游标）
  messages: (sessionId, params = {}) =>
    request.get(`/im/sessions/${sessionId}/messages/`, { params }),
  // #324 多会话转发（session_ids 批量，返回逐会话明细）
  forward: (id, sessionIds) =>
    request.post(`/im/messages/${id}/forward/`, { session_ids: sessionIds }),
  // #325 会话导出（start / end / format=md|csv）
  exportSession: (sessionId, params = {}) =>
    request.get(`/im/sessions/${sessionId}/export/`, { params }),
  // #326 临时免打扰（duration=1h|8h|tomorrow|off）
  mute: (sessionId, duration) =>
    request.post(`/im/sessions/${sessionId}/mute/`, { duration }),
  // #327 置顶会话拖拽排序
  pinOrder: (items) => request.post('/im/sessions/pin-order/', { items }),
  // #329 会话文件聚合（type / sender / page）
  sessionFiles: (sessionId, params = {}) =>
    request.get(`/im/sessions/${sessionId}/files/`, { params }),
}

export default imx
