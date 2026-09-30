/**
 * AI 助手扩展接口（F643–F656）
 * 与 src/api/index.js 里的 aiApi 并列，避免改动既有 index.js。
 * 生成类接口放宽超时：本地降级很快，走大模型时后端 LLM_TIMEOUT 默认 90s。
 */
import request from './request'

const AI_TIMEOUT = 180000

export const aix = {
  // F645 分支：以某条消息为父创建新会话
  branch: (convId, messageId) =>
    request.post(`/assistant/conversations/${convId}/branch/`, { message_id: messageId }, { timeout: AI_TIMEOUT }),
  // F655 导出 Markdown（blob 触发浏览器下载）
  exportConversation: (convId) =>
    request.get(`/assistant/conversations/${convId}/export/`, { responseType: 'blob', timeout: AI_TIMEOUT }),

  // F644 提示词库 CRUD
  prompts: (params) => request.get('/assistant/prompts/', { params }),
  createPrompt: (data) => request.post('/assistant/prompts/', data),
  updatePrompt: (id, data) => request.patch(`/assistant/prompts/${id}/`, data),
  deletePrompt: (id) => request.delete(`/assistant/prompts/${id}/`),
  usePrompt: (id) => request.post(`/assistant/prompts/${id}/`, {}),

  // 创作工具
  translate: (data) => request.post('/assistant/translate/', data, { timeout: AI_TIMEOUT }),
  names: (data) => request.post('/assistant/names/', data, { timeout: AI_TIMEOUT }),
  weeklyReport: (data) => request.post('/assistant/weekly-report/', data, { timeout: AI_TIMEOUT }),
  agenda: (data) => request.post('/assistant/agenda/', data, { timeout: AI_TIMEOUT }),
  emailDraft: (data) => request.post('/assistant/email-draft/', data, { timeout: AI_TIMEOUT }),
  socialCopy: (data) => request.post('/assistant/social-copy/', data, { timeout: AI_TIMEOUT }),
  mathExplain: (data) => request.post('/assistant/math-explain/', data, { timeout: AI_TIMEOUT }),

  // F654 快捷指令菜单（工具 + 路由建议）
  commands: () => request.get('/assistant/commands/'),
}
