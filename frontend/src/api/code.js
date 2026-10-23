/**
 * 代码工坊 API（v6）
 *
 * 全量接口封装，与后端 /api/code/ 一一对应（75 个接口）。
 * 长耗时接口（运行/判题/AI）单独放宽超时，避免 60s 全局超时打断。
 */
import axios from 'axios'
import request from './request'
import { API_URL, apiUrl } from './base'

// 运行类接口放宽到 60s（后端单次执行上限 30s + 编译时间）
const RUN_TIMEOUT = 60000
// AI 类接口与全局一致走 180s（后端 LLM_TIMEOUT 默认 90s）
const AI_TIMEOUT = 180000

export const codeApi = {
  // ===== 元信息 =====
  catalog: () => request.get('/code/catalog/'),
  runtimes: (force = false) => request.get('/code/runtimes/', { params: force ? { force: true } : {} }),
  languages: () => request.get('/code/languages/'),
  templates: () => request.get('/code/templates/'),

  // ===== 工作区 =====
  workspaces: (params) => request.get('/code/workspaces/', { params }),
  createWorkspace: (data) => request.post('/code/workspaces/create/', data),
  workspace: (id) => request.get(`/code/workspaces/${id}/`),
  updateWorkspace: (id, data) => request.post(`/code/workspaces/${id}/update/`, data),
  deleteWorkspace: (id) => request.post(`/code/workspaces/${id}/delete/`),
  starWorkspace: (id) => request.post(`/code/workspaces/${id}/star/`, {}),
  cloneWorkspace: (id) => request.post(`/code/workspaces/${id}/clone/`, {}),

  // ===== 代码文件 =====
  files: (params) => request.get('/code/files/', { params }),
  createFile: (data) => request.post('/code/files/create/', data),
  file: (id) => request.get(`/code/files/${id}/`),
  updateFile: (id, data) => request.post(`/code/files/${id}/update/`, data),
  deleteFile: (id) => request.post(`/code/files/${id}/delete/`),
  favoriteFile: (id) => request.post(`/code/files/${id}/favorite/`, {}),
  setEntryFile: (id) => request.post(`/code/files/${id}/entry/`, {}),
  moveFile: (id, path) => request.post(`/code/files/${id}/move/`, { path }),
  batchFiles: (data) => request.post('/code/files/batch/', data),
  fileTree: (workspace) => request.get('/code/files/tree/', { params: { workspace } }),

  // ===== 版本 =====
  versions: (fileId) => request.get(`/code/files/${fileId}/versions/`),
  createVersion: (fileId, message) => request.post(`/code/files/${fileId}/versions/create/`, { message }),
  versionDiff: (fileId, params) => request.get(`/code/files/${fileId}/versions/diff/`, { params }),
  rollback: (fileId, vid) => request.post(`/code/files/${fileId}/versions/${vid}/rollback/`, {}),
  deleteVersion: (fileId, vid) => request.post(`/code/files/${fileId}/versions/${vid}/delete/`, {}),

  // ===== 运行 =====
  run: (data) => request.post('/code/run/', data, { timeout: RUN_TIMEOUT }),
  repl: (data) => request.post('/code/run/repl/', data, { timeout: RUN_TIMEOUT }),
  runHistory: (params) => request.get('/code/run/history/', { params }),
  runDetail: (id) => request.get(`/code/run/${id}/`),
  deleteRun: (id) => request.post(`/code/run/${id}/delete/`, {}),
  clearRuns: (language) => request.post('/code/run/clear/', language ? { language } : {}),
  runStats: () => request.get('/code/run/stats/'),

  // ===== 判题 =====
  judge: (data) => request.post('/code/judge/', data, { timeout: RUN_TIMEOUT }),
  judgeHistory: (params) => request.get('/code/judge/history/', { params }),
  judgeDetail: (id) => request.get(`/code/judge/${id}/`),
  leaderboard: (limit = 20) => request.get('/code/leaderboard/', { params: { limit } }),

  // ===== 片段库 =====
  snippets: (params) => request.get('/code/snippets/', { params }),
  createSnippet: (data) => request.post('/code/snippets/create/', data),
  snippet: (id) => request.get(`/code/snippets/${id}/`),
  updateSnippet: (id, data) => request.post(`/code/snippets/${id}/update/`, data),
  deleteSnippet: (id) => request.post(`/code/snippets/${id}/delete/`, {}),
  copySnippet: (id, intoMine = false) => request.post(`/code/snippets/${id}/copy/`, { into_mine: intoMine }),
  snippetTags: () => request.get('/code/snippets/tags/'),
  snippetFromFile: (data) => request.post('/code/snippets/from-file/', data),

  // ===== 静态分析 =====
  analyze: (data) => request.post('/code/analyze/', data),
  outline: (data) => request.post('/code/outline/', data),
  complexity: (data) => request.post('/code/complexity/', data),
  quality: (data) => request.post('/code/quality/', data),
  flow: (data) => request.post('/code/flow/', data),
  similarity: (data) => request.post('/code/similarity/', data),
  secretScan: (data) => request.post('/code/secret-scan/', data),
  refactorHints: (data) => request.post('/code/refactor-hints/', data),

  // ===== 智能辅助 =====
  aiStatus: () => request.get('/code/ai/status/'),
  aiGenerate: (data) => request.post('/code/ai/generate/', data, { timeout: AI_TIMEOUT }),
  aiTransform: (data) => request.post('/code/ai/transform/', data, { timeout: AI_TIMEOUT }),
  aiErrorExplain: (data) => request.post('/code/ai/error-explain/', data, { timeout: AI_TIMEOUT }),
  aiRegex: (data) => request.post('/code/ai/regex/', data, { timeout: AI_TIMEOUT }),
  aiNl2sql: (data) => request.post('/code/ai/nl2sql/', data, { timeout: AI_TIMEOUT }),
  aiLearningPath: (data) => request.post('/code/ai/learning-path/', data, { timeout: AI_TIMEOUT }),
  aiChatEdit: (data) => request.post('/code/ai/chat-edit/', data, { timeout: AI_TIMEOUT }),
  aiInline: (data) => request.post('/code/ai/inline/', data, { timeout: AI_TIMEOUT }),
  aiApply: (fileId, data) => request.post(`/code/ai/apply/${fileId}/`, data),

  // ===== 协作 =====
  comments: (fileId) => request.get(`/code/files/${fileId}/comments/`),
  createComment: (fileId, data) => request.post(`/code/files/${fileId}/comments/create/`, data),
  resolveComment: (fileId, cid) => request.post(`/code/files/${fileId}/comments/${cid}/resolve/`, {}),
  deleteComment: (fileId, cid) => request.post(`/code/files/${fileId}/comments/${cid}/delete/`, {}),
  collabState: (fileId) => request.get(`/code/files/${fileId}/collab/`),
  collabWs: (fileId) => request.get(`/code/files/${fileId}/collab/ws/`),

  // ===== 分享 =====
  shares: () => request.get('/code/shares/'),
  createShare: (data) => request.post('/code/shares/create/', data),
  updateShare: (token, data) => request.post(`/code/shares/${token}/`, data),
  revokeShare: (token) => request.post(`/code/shares/${token}/revoke/`),

  /**
   * 公开分享页数据：免登录只读。
   * 走裸 axios 而非 request 实例 —— 分享页可能未登录，
   * 若用 request 会触发 401 拦截器把用户弹去 /login，显然不合理。
   */
  publicShare: async (token) => {
    const res = await axios.get(`${API_URL}/share/code/${token}/`)
    return res.data
  },

  /** 公开分享页在线运行（免登录）。后端只执行分享内容本身，忽略 code。 */
  publicRun: async (token, stdin = '') => {
    const res = await axios.post(`${API_URL}/share/code/${token}/run/`, { stdin })
    return res.data
  },

  // ===== 导出 =====
  exportZipUrl: () => apiUrl('/api/code/export/zip/'),
  exportFileUrl: (id) => apiUrl(`/api/code/export/file/${id}/`),
  exportZip: (data) => request.post('/code/export/zip/', data, { responseType: 'blob' }),

  // ===== 每日一题（L5）=====
  dailyToday: () => request.get('/code/daily/today/'),
  dailySubmit: (data) => request.post('/code/daily/submit/', data, { timeout: RUN_TIMEOUT }),
  dailyHistory: (limit = 30) => request.get('/code/daily/history/', { params: { limit } }),

  // ===== 成就徽章（L5）=====
  achievements: () => request.get('/code/achievements/'),
  myAchievements: () => request.get('/code/achievements/mine/'),

  // ===== 错题本（L5）=====
  wrongList: (params = {}) => request.get('/code/wrongbook/', { params }),
  wrongAdd: (data) => request.post('/code/wrongbook/add/', data),
  wrongReview: (id, data = {}) => request.post(`/code/wrongbook/${id}/review/`, data),
  wrongDelete: (id) => request.post(`/code/wrongbook/${id}/delete/`, {}),

  // ===== 学习路径（L5）=====
  pathList: (limit = 20) => request.get('/code/paths/', { params: { limit } }),
  pathGenerate: (data) => request.post('/code/paths/generate/', data, { timeout: AI_TIMEOUT }),
  pathDetail: (id) => request.get(`/code/paths/${id}/`),
  pathTick: (id, item, done = true) => request.post(`/code/paths/${id}/tick/`, { item, done }),
  pathDelete: (id) => request.post(`/code/paths/${id}/delete/`, {}),

  // ===== 竞技场（L5）=====
  arenaBoard: () => request.get('/code/arena/board/'),
  arenaChallenge: (difficulty = '') =>
    request.get('/code/arena/challenge/', { params: difficulty ? { difficulty } : {} }),
  arenaSubmit: (data) => request.post('/code/arena/submit/', data, { timeout: RUN_TIMEOUT }),

  // ===== 学习总览（L5）=====
  learnOverview: () => request.get('/code/learn/overview/'),

  // ===== 工程化（L4）=====
  blame: (fileId, maxLines = 2000) =>
    request.get(`/code/blame/${fileId}/`, { params: { max_lines: maxLines } }),
  todos: (params = {}) => request.get('/code/todos/', { params }),
  diff: (data) => request.post('/code/diff/', data),
  insights: (workspace = null) =>
    request.get('/code/insights/', { params: workspace ? { workspace } : {} }),
  contributors: (workspace = null) =>
    request.get('/code/contributors/', { params: workspace ? { workspace } : {} }),
  versionSideBySide: (fileId, vid) =>
    request.get(`/code/files/${fileId}/versions/${vid}/side-by-side/`),

  // ===== AI 深度能力（L3 补齐）=====
  aiTranslate: (data) => request.post('/code/ai/translate/', data, { timeout: AI_TIMEOUT }),
  aiComment: (data) => request.post('/code/ai/comment/', data, { timeout: AI_TIMEOUT }),
  aiOptimize: (data) => request.post('/code/ai/optimize/', data, { timeout: AI_TIMEOUT }),
  aiTestgen: (data) => request.post('/code/ai/testgen/', data, { timeout: AI_TIMEOUT }),
  aiSummary: (data) => request.post('/code/ai/summary/', data, { timeout: AI_TIMEOUT }),
  aiReview: (data) => request.post('/code/ai/review/', data, { timeout: AI_TIMEOUT }),

  // ===== F669–F680 代码工坊新能力 =====
  /** F669 片段收藏夹分组：分组列表 + 计数 */
  snippetFolders: () => request.get('/code/snippets/folders/'),
  /** F676 运行参数预设：按语言列出 */
  runPresets: (language) => request.get('/code/run/presets/', { params: language ? { language } : {} }),
  /** F676 新建预设 */
  createRunPreset: (data) => request.post('/code/run/presets/', data),
  /** F676 更新预设 */
  updateRunPreset: (id, data) => request.post(`/code/run/presets/${id}/`, data),
  /** F676 删除预设 */
  deleteRunPreset: (id) => request.delete(`/code/run/presets/${id}/`),
  /** F677 代码统计卡（行数/注释率/函数数） */
  codeStats: (data) => request.post('/code/code-stats/', data),
  /** F680 每日一题提醒状态 */
  dailyReminder: () => request.get('/code/daily/reminder/'),
  /** F680 立即发一条站内提醒（幂等） */
  notifyDailyReminder: () => request.post('/code/daily/reminder/', {}),
}

export default codeApi
