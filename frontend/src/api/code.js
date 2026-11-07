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
  comments: (fileId, params) => request.get(`/code/files/${fileId}/comments/`, { params }),
  createComment: (fileId, data) => request.post(`/code/files/${fileId}/comments/create/`, data),
  resolveComment: (fileId, cid) => request.post(`/code/files/${fileId}/comments/${cid}/resolve/`, {}),
  deleteComment: (fileId, cid) => request.post(`/code/files/${fileId}/comments/${cid}/delete/`, {}),

  // ===== 分享 =====
  shares: () => request.get('/code/shares/'),
  createShare: (data) => request.post('/code/shares/create/', data),
  updateShare: (token, data) => request.post(`/code/shares/${token}/`, data),
  revokeShare: (token) => request.post(`/code/shares/${token}/revoke/`),
  /** #269 分享访问统计：总数 / 独立访客 / 近 30 天 */
  shareVisits: (token) => request.get(`/code/shares/${token}/visits/`),
  /** #270 把分享内容保存到自己的片段库（可同时写入工作区文件） */
  cloneShare: (token, data = {}) => request.post(`/code/share/code/${token}/clone/`, data),

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
  todos: (params = {}) => request.get('/code/todos/', { params }),
  diff: (data) => request.post('/code/diff/', data),
  insights: (workspace = null) =>
    request.get('/code/insights/', { params: workspace ? { workspace } : {} }),
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

  // ===== 第三轮 261–280：模板 / 导入 / 全局替换 / 复制 / 依赖图 / 格式化 =====
  /** #263 多文件工作区模板 */
  workspaceTemplates: () => request.get('/code/workspaces/templates/'),
  /** #263 按模板批量建目录与文件 */
  createWorkspaceFromTemplate: (data) => request.post('/code/workspaces/from-template/', data),
  /** #266 导入 zip 为工作区（FormData，字段名 file） */
  importWorkspace: (formData, onProgress) =>
    request.post('/code/workspaces/import/', formData, {
      timeout: 120000,
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    }),
  /** #264 工作区全局搜索替换（dry_run 预览，确认后写回） */
  replaceInWorkspace: (id, data) => request.post(`/code/workspaces/${id}/replace/`, data),
  /** #276 复制文件为「name(副本).ext」 */
  copyFile: (id, dir = '') => request.post(`/code/files/${id}/copy/`, dir ? { dir } : {}),
  /** #272 未被引用文件检测 */
  fileOrphans: (workspace) => request.get('/code/files/orphans/', { params: { workspace } }),
  /** #271 工作区依赖图 */
  dependencyGraph: (workspace) => request.get('/code/dependencies/graph/', { params: { workspace } }),
  /** #273 本地格式化 */
  formatCode: (data) => request.post('/code/format/', data),
  /** #274 运行历史导出 CSV */
  exportRuns: (params = {}) =>
    request.get('/code/run/export/', { params, responseType: 'blob', timeout: 120000 }),
  /** #279 运行预设导出 / 导入 */
  exportRunPresets: (language) =>
    request.get('/code/run/presets/export/', { params: language ? { language } : {} }),
  importRunPresets: (items) => request.post('/code/run/presets/import/', { items }),
  /** #275 判题用例集 */
  judgeCaseSets: (params = {}) => request.get('/code/judge/testcases/', { params }),
  createJudgeCaseSet: (data) => request.post('/code/judge/testcases/', data),
  updateJudgeCaseSet: (id, data) => request.post(`/code/judge/testcases/${id}/`, data),
  deleteJudgeCaseSet: (id) => request.delete(`/code/judge/testcases/${id}/`),
  /** #267 片段库导出 / 导入 */
  exportSnippets: () => request.get('/code/snippets/export/'),
  importSnippets: (items) => request.post('/code/snippets/import/', { items }),
  /** #265 片段生成工作区文件 */
  snippetToFile: (id, data) => request.post(`/code/snippets/${id}/to-file/`, data),
}

export default codeApi
