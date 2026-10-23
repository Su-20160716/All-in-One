import request from './request'
import { apiUrl } from './base'

// ===== 认证 / 用户 =====
export const authApi = {
  register: (data) => request.post('/auth/register/', data),
  login: (data) => request.post('/auth/login/', data),
  logout: (refresh) => request.post('/auth/logout/', { refresh }),
  usernameCheck: (username) => request.get('/auth/username-check/', { params: { username } }),
  profile: () => request.get('/auth/profile/'),
  updateProfile: (data) => request.patch('/auth/profile/', data),
  changeUsername: (username) => request.post('/auth/profile/change-username/', { username }),
  changePassword: (data) => request.post('/auth/profile/change-password/', data),
  uploadAvatar: (formData) =>
    request.post('/auth/profile/avatar/', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  deleteAvatar: () => request.delete('/auth/profile/avatar/'),
  deactivate: (password) => request.post('/auth/profile/deactivate/', { password }),
  exportData: () => request.get('/auth/profile/export/'),
  loginHistory: () => request.get('/auth/profile/login-history/'),
  badges: () => request.get('/auth/profile/badges/'),
  invites: () => request.get('/auth/profile/invites/'),
  createInvite: (data) => request.post('/auth/profile/invites/', data),
  sessions: () => request.get('/auth/profile/sessions/'),
  revokeSession: (id) => request.post(`/auth/profile/sessions/${id}/revoke/`, {}),
  heartbeat: () => request.post('/auth/heartbeat/', {}),
  directory: (q) => request.get('/auth/directory/', { params: { q } }),
  myPermissions: () => request.get('/auth/me/permissions/'),
  // 管理员
  adminUsers: (params) => request.get('/auth/admin/users/', { params }),
  adminCreateUser: (data) => request.post('/auth/admin/users/create/', data),
  adminUpdateUser: (id, data) => request.patch(`/auth/admin/users/${id}/`, data),
  adminResetPassword: (id, new_password) =>
    request.post(`/auth/admin/users/${id}/reset-password/`, { new_password }),
  adminBatch: (data) => request.post('/auth/admin/users/batch/', data),
  assignRoles: (user_ids, role_ids) => request.post('/auth/admin/users/assign-roles/', { user_ids, role_ids }),
  roles: () => request.get('/auth/admin/roles/'),
  createRole: (data) => request.post('/auth/admin/roles/', data),
  updateRole: (id, data) => request.patch(`/auth/admin/roles/${id}/`, data),
  deleteRole: (id) => request.delete(`/auth/admin/roles/${id}/`),
  permissions: (params) => request.get('/auth/admin/permissions/', { params }),
  online: (params) => request.get('/auth/admin/online/', { params }),
}

// ===== 文件 =====
export const fileApi = {
  folders: (parent) => request.get('/files/folders/', { params: { parent: parent ?? '' } }),
  folderTree: () => request.get('/files/folders/tree/'),
  createFolder: (data) => request.post('/files/folders/', data),
  updateFolder: (id, data) => request.patch(`/files/folders/${id}/`, data),
  deleteFolder: (id) => request.delete(`/files/folders/${id}/`),
  breadcrumb: (id) => request.get(`/files/folders/${id}/breadcrumb/`),
  list: (params) => request.get('/files/', { params }),
  search: (params) => request.get('/files/search/', { params }),
  detail: (id) => request.get(`/files/${id}/`),
  update: (id, data) => request.patch(`/files/${id}/`, data),
  rename: (id, name) => request.patch(`/files/${id}/`, { name }),
  moveFile: (id, folder) => request.patch(`/files/${id}/`, { folder: folder ?? null }),
  star: (id) => request.post(`/files/${id}/star/`, {}),
  copy: (id) => request.post(`/files/${id}/copy/`, {}),
  createText: (data) => request.post('/files/create-text/', data),
  saveText: (id, content) => request.post(`/files/${id}/save-text/`, { content }),
  remove: (id) => request.delete(`/files/${id}/`),
  downloadUrl: (id) => apiUrl(`/api/files/${id}/download/`),
  preview: (id) => request.get(`/files/${id}/preview/`),
  batch: (data) => request.post('/files/batch/', data),
  batchDownload: (file_ids) =>
    request.post('/files/batch-download/', { file_ids }, { responseType: 'blob' }),
  uploadInit: (data) => request.post('/files/upload/init/', data),
  uploadStatus: (upload_id) => request.get('/files/upload/status/', { params: { upload_id } }),
  uploadAbort: (upload_id) => request.post('/files/upload/abort/', { upload_id }),
  uploadChunk: (formData) =>
    request.post('/files/upload/chunk/', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),
  uploadComplete: (upload_id) => request.post('/files/upload/complete/', { upload_id }),
  recent: () => request.get('/files/recent/'),
  starred: () => request.get('/files/starred/'),
  analysis: () => request.get('/files/analysis/'),
  // 多类型在线预览 + Range 流式 + Office 转 PDF
  rawUrl: (id) => apiUrl(`/api/files/${id}/raw/`),
  pdfUrl: (id) => apiUrl(`/api/files/${id}/pdf/`),
  toPdf: (id, force = false) => request.post(`/files/${id}/to-pdf/`, { force }),
  officeCapability: () => request.get('/files/office-capability/'),
  fileTags: () => request.get('/files/tags/'),
  createFileTag: (data) => request.post('/files/tags/', data),
  updateFileTag: (id, data) => request.patch(`/files/tags/${id}/`, data),
  deleteFileTag: (id) => request.delete(`/files/tags/${id}/`),
  batchTag: (data) => request.post('/files/batch-tag/', data),
  batchRename: (data) => request.post('/files/batch-rename/', data),
  folderTemplates: () => request.get('/files/folder-templates/'),
  folderFromTemplate: (data) => request.post('/files/folders/from-template/', data),
  cleanConfig: () => request.get('/files/clean-config/'),
  trashList: () => request.get('/files/trash/'),
  trashAction: (action, file_ids) => request.post('/files/trash/action/', { action, file_ids }),
  trashAutoClean: () => request.post('/files/trash/auto-clean/', {}),
  shares: (params) => request.get('/files/shares/', { params }),
  createShare: (data) => request.post('/files/shares/create/', data),
  updateShare: (token, data) => request.patch(`/files/shares/${token}/`, data),
  revokeShare: (token) => request.delete(`/files/shares/${token}/`),
}

// ===== 笔记 =====
export const noteApi = {
  list: (params) => request.get('/notes/', { params }),
  tree: () => request.get('/notes/tree/'),
  tags: () => request.get('/notes/tags/'),
  createTag: (data) => request.post('/notes/tags/', data),
  updateTag: (id, data) => request.patch(`/notes/tags/${id}/`, data),
  deleteTag: (id) => request.delete(`/notes/tags/${id}/`),
  recent: () => request.get('/notes/recent/'),
  stats: () => request.get('/notes/stats/'),
  templates: () => request.get('/notes/templates/'),
  fromTemplate: (key) => request.post('/notes/from-template/', { key }),
  create: (data) => request.post('/notes/', data),
  detail: (id) => request.get(`/notes/${id}/`),
  update: (id, data) => request.patch(`/notes/${id}/`, data),
  remove: (id) => request.delete(`/notes/${id}/`),
  copy: (id) => request.post(`/notes/${id}/copy/`, {}),
  batch: (data) => request.post('/notes/batch/', data),
  trash: () => request.get('/notes/trash/'),
  emptyTrash: () => request.delete('/notes/trash/'),
  outline: (id) => request.get(`/notes/${id}/outline/`),
  versions: (id) => request.get(`/notes/${id}/versions/`),
  versionDiff: (id, from, to) =>
    request.get(`/notes/${id}/versions/diff/`, { params: { from, to } }),
  rollback: (id, version) => request.post(`/notes/${id}/rollback/${version}/`, {}),
  exportUrl: (id) => apiUrl(`/api/notes/${id}/export/`),
  exportAllUrl: () => apiUrl('/api/notes/export-all/'),
  // [[双链]]
  backlinks: (id) => request.get(`/notes/${id}/backlinks/`),
  linkGraph: (limit = 300) => request.get('/notes/graph/', { params: { limit } }),
  linkSuggest: (q, exclude) => request.get('/notes/link-suggest/', { params: { q, exclude } }),
  dangling: () => request.get('/notes/dangling/'),
  fromTitle: (title) => request.post('/notes/from-title/', { title }),
  rebuildLinks: () => request.post('/notes/links/rebuild/', {}),
  batchImport: (data) => request.post('/notes/batch-import/', data),
  tagCloud: () => request.get('/notes/tag-cloud/'),
  exportSelected: (data) =>
    request.post('/notes/export-selected/', data, { responseType: 'blob' }),
  flashcards: (id) => request.get(`/notes/${id}/flashcards/`),
  aiOutline: (id) => request.post(`/notes/${id}/ai-outline/`, {}),
}

// ===== 项目看板 =====
export const projectApi = {
  list: (params) => request.get('/projects/', { params }),
  create: (data) => request.post('/projects/', data),
  detail: (id) => request.get(`/projects/${id}/`),
  update: (id, data) => request.patch(`/projects/${id}/`, data),
  star: (id) => request.post(`/projects/${id}/star/`, {}),
  clone: (id) => request.post(`/projects/${id}/clone/`, {}),
  remove: (id) => request.delete(`/projects/${id}/`),
  members: (id, q) => request.get(`/projects/${id}/members/`, { params: { q } }),
  addMembers: (id, user_ids) => request.post(`/projects/${id}/members/`, { user_ids }),
  removeMember: (id, user_id) => request.delete(`/projects/${id}/members/?user_id=${user_id}`),
  board: (projectId) => request.get(`/projects/${projectId}/boards/`),
  reorderBoards: (projectId, orders) =>
    request.post(`/projects/${projectId}/boards/reorder/`, { orders }),
  createBoard: (projectId, name) => request.post(`/projects/${projectId}/boards/`, { name }),
  renameBoard: (boardId, name) => request.patch(`/projects/boards/${boardId}/`, { name }),
  deleteBoard: (boardId) => request.delete(`/projects/boards/${boardId}/`),
  createCard: (boardId, data) => request.post(`/projects/boards/${boardId}/cards/`, data),
  card: (cardId) => request.get(`/projects/cards/${cardId}/`),
  updateCard: (cardId, data) => request.patch(`/projects/cards/${cardId}/`, data),
  deleteCard: (cardId) => request.delete(`/projects/cards/${cardId}/`),
  copyCard: (cardId) => request.post(`/projects/cards/${cardId}/copy/`, {}),
  batchCards: (data) => request.post('/projects/cards/batch/', data),
  moveCard: (cardId, board_id, index) =>
    request.post(`/projects/cards/${cardId}/move/`, { board_id, index }),
  searchCards: (projectId, params) =>
    request.get(`/projects/${projectId}/search/`, { params }),
  subtasks: (cardId) => request.get(`/projects/cards/${cardId}/`),
  addSubtask: (cardId, title) => request.post(`/projects/cards/${cardId}/subtasks/`, { title }),
  updateSubtask: (cardId, sid, data) =>
    request.patch(`/projects/cards/${cardId}/subtasks/${sid}/`, data),
  deleteSubtask: (cardId, sid) =>
    request.delete(`/projects/cards/${cardId}/subtasks/${sid}/`),
  worklogs: (cardId) => request.get(`/projects/cards/${cardId}/worklogs/`),
  addWorklog: (cardId, data) => request.post(`/projects/cards/${cardId}/worklogs/`, data),
  deleteWorklog: (cardId, wid) => request.delete(`/projects/cards/${cardId}/worklogs/${wid}/`),
  comments: (cardId) => request.get(`/projects/cards/${cardId}/comments/`),
  addComment: (cardId, content) => request.post(`/projects/cards/${cardId}/comments/`, { content }),
  updateComment: (cardId, cid, content) =>
    request.patch(`/projects/cards/${cardId}/comments/${cid}/`, { content }),
  deleteComment: (cardId, cid) => request.delete(`/projects/cards/${cardId}/comments/${cid}/`),
  activities: (projectId) => request.get(`/projects/${projectId}/activities/`),
  stats: (projectId) => request.get(`/projects/${projectId}/stats/`),
  calendar: (projectId) => request.get(`/projects/${projectId}/calendar/`),
  burndown: (projectId) => request.get(`/projects/${projectId}/burndown/`),
  templates: () => request.get('/projects/templates/'),
  fromTemplate: (data) => request.post('/projects/from-template/', data),
  createShare: (projectId) => request.post(`/projects/${projectId}/share/`, {}),
  revokeShare: (projectId, token) => request.delete(`/projects/${projectId}/share/${token}/`),
  myTasks: (params) => request.get('/projects/my-tasks/', { params }),
}

// ===== 消息 =====
export const imApi = {
  sessions: (params) => request.get('/im/sessions/', { params }),
  createSession: (data) => request.post('/im/sessions/create/', data),
  sessionDetail: (id) => request.get(`/im/sessions/${id}/`),
  updateSession: (id, data) => request.patch(`/im/sessions/${id}/`, data),
  leaveSession: (id) => request.post(`/im/sessions/${id}/leave/`, {}),
  transfer: (id, user_id) => request.post(`/im/sessions/${id}/transfer/`, { user_id }),
  addMembers: (id, member_ids) => request.post(`/im/sessions/${id}/members/`, { member_ids }),
  removeMember: (id, user_id) => request.delete(`/im/sessions/${id}/members/?user_id=${user_id}`),
  setting: (id, data) => request.post(`/im/sessions/${id}/setting/`, data),
  messages: (sessionId, params) => request.get(`/im/sessions/${sessionId}/messages/`, { params }),
  send: (sessionId, data) =>
    request.post(`/im/sessions/${sessionId}/send/`, typeof data === 'string' ? { content: data } : data),
  recall: (id) => request.post(`/im/messages/${id}/recall/`, {}),
  deleteMsg: (id) => request.post(`/im/messages/${id}/delete/`, {}),
  forward: (id, session_ids) => request.post(`/im/messages/${id}/forward/`, { session_ids }),
  searchMessages: (params) => request.get('/im/sessions/search-messages/', { params: typeof params === 'string' ? { q: params } : params }),
  unreadTotal: () => request.get('/im/unread-total/'),
  unreadSummary: () => request.get('/im/sessions/unread-summary/'),
  pinMsg: (id) => request.post(`/im/messages/${id}/pin/`, {}),
  quickReplies: () => request.get('/im/quick-replies/'),
  createQuickReply: (data) => request.post('/im/quick-replies/', data),
  updateQuickReply: (id, data) => request.patch(`/im/quick-replies/${id}/`, data),
  deleteQuickReply: (id) => request.delete(`/im/quick-replies/${id}/`),
  keywordAlert: () => request.get('/im/keyword-alert/'),
  saveKeywordAlert: (keywords) => request.post('/im/keyword-alert/', { keywords }),
}

// ===== 通知 / 公告 / 日志 / 搜索 / 设置 =====
export const coreApi = {
  notifications: (params) => request.get('/core/notifications/', { params }),
  markRead: (ids) => request.post('/core/notifications/read/', { ids }),
  unreadCount: (params) => request.get('/core/notifications/unread-count/', { params }),
  deleteNotifications: (data) => request.post('/core/notifications/delete/', data),
  notificationSettings: () => request.get('/core/notifications/settings/'),
  saveNotificationSettings: (settings) =>
    request.post('/core/notifications/settings/', { settings }),
  announcements: () => request.get('/core/announcements/'),
  announcement: (id) => request.get(`/core/announcements/${id}/`),
  readAnnouncement: (id) => request.post(`/core/announcements/${id}/read/`, {}),
  adminAnnouncements: () => request.get('/core/admin/announcements/'),
  createAnnouncement: (data) => request.post('/core/admin/announcements/', data),
  updateAnnouncement: (id, data) => request.patch(`/core/admin/announcements/${id}/`, data),
  deleteAnnouncement: (id) => request.delete(`/core/admin/announcements/${id}/`),
  announcementReadersExportUrl: (id) => apiUrl(`/api/core/admin/announcements/${id}/readers/export/`),
  storageTopUsers: () => request.get('/core/admin/storage/top-users/'),
  backup: () => request.post('/core/admin/backup/', {}),
  logs: (params) => request.get('/core/logs/', { params }),
  myLogs: (params) => request.get('/core/my-logs/', { params }),
  logStats: () => request.get('/core/logs/stats/'),
  logExportUrl: () => apiUrl('/api/core/logs/export/'),
  search: (q) => request.get('/core/search/', { params: { q } }),
  health: () => request.get('/core/health/'),
  publicSettings: () => request.get('/core/settings/public/'),
  adminSettings: () => request.get('/core/admin/settings/'),
  saveAdminSettings: (settings) => request.post('/core/admin/settings/', { settings }),
}

// ===== 统计 =====
export const dashApi = {
  stats: () => request.get('/dashboard/stats/'),
  personalTrend: () => request.get('/dashboard/personal-trend/'),
  taskDistribution: () => request.get('/dashboard/my-task-distribution/'),
  fileTypeDist: () => request.get('/dashboard/file-type-distribution/'),
  todoAggregate: () => request.get('/dashboard/todo-aggregate/'),
  global: () => request.get('/dashboard/admin/global/'),
  trend: () => request.get('/dashboard/admin/trend/'),
  userGrowth: () => request.get('/dashboard/admin/user-growth/'),
  moduleUsage: () => request.get('/dashboard/admin/module-usage/'),
}

// ===== 工具（统一运行入口 + 目录）=====
export const toolApi = {
  catalog: () => request.get('/tools/catalog/'),
  run: (tool, params) => request.post('/tools/run/', { tool, ...params }),
}

// ===== v5 能力域（devtools / dataintel / officesuite，目录驱动）=====
// catalog 响应: { ok, data: { domain, domain_name, subsystems, endpoint_count, endpoints } }
// endpoints 为接口明细 [{path, methods}]，path 形如 "text/case/"、wiki/<int:pk>/move/
export const suiteApi = {
  catalog: (domain) => request.get(`/${domain}/catalog/`),
  call: (domain, path, method = 'POST', data = null) =>
    method === 'GET'
      ? request.get(`/${domain}/${path}`, { params: data || {} })
      : request.post(`/${domain}/${path}`, data || {}),
}

// ===== 管理后台别名（与 authApi 中管理员方法一致）=====
export const adminApi = {
  users: authApi.adminUsers,
  createUser: authApi.adminCreateUser,
  updateUser: authApi.adminUpdateUser,
  resetPassword: authApi.adminResetPassword,
  batch: authApi.adminBatch,
  assignRoles: authApi.assignRoles,
  roles: authApi.roles,
  createRole: authApi.createRole,
  updateRole: authApi.updateRole,
  deleteRole: authApi.deleteRole,
  permissions: authApi.permissions,
  online: authApi.online,
}

// ===== 学习中心（全新方向：10 种编程语言 + 小学/初中/高中）=====
export const learnApi = {
  // —— 编程学习 ——
  langCatalog: () => request.get('/learning/prog/languages/'),
  langDetail: (key) => request.get(`/learning/prog/languages/${key}/`),
  langRoadmap: (key) => request.get(`/learning/prog/languages/${key}/roadmap/`),
  langCheatsheet: (key) => request.get(`/learning/prog/languages/${key}/cheatsheet/`),
  langKeywords: (key) => request.get(`/learning/prog/languages/${key}/keywords/`),
  langKeywordsDetail: (key) => request.get(`/learning/prog/languages/${key}/keywords/`, { params: { detail: true } }),
  langKeywordDetail: (key, word) => request.get(`/learning/prog/languages/${key}/keywords/${encodeURIComponent(word)}/`),
  langModules: (key) => request.get(`/learning/prog/languages/${key}/modules/`),
  langModuleDetail: (key, idx) => request.get(`/learning/prog/languages/${key}/modules/${idx}/`),
  langTypes: (key) => request.get(`/learning/prog/languages/${key}/types/`),
  langSnippets: (key, params) => request.get(`/learning/prog/languages/${key}/snippets/`, { params }),
  langSnippet: (key, idx) => request.get(`/learning/prog/languages/${key}/snippets/${idx}/`),
  langLessons: (key) => request.get(`/learning/prog/languages/${key}/lessons/`),
  langLesson: (key, idx) => request.get(`/learning/prog/languages/${key}/lessons/${idx}/`),
  langErrors: (key) => request.get(`/learning/prog/languages/${key}/troubleshoot/`),
  langIde: (key) => request.get(`/learning/prog/languages/${key}/ide/`),
  langStyle: (key) => request.get(`/learning/prog/languages/${key}/style/`),
  langCompare: (keys) => request.get('/learning/prog/languages/compare/', { params: { keys: keys.join(',') } }),
  glossary: (params) => request.get('/learning/prog/glossary/', { params }),
  paradigms: () => request.get('/learning/prog/paradigms/'),
  algorithms: (params) => request.get('/learning/prog/algorithms/', { params }),
  dataStructures: () => request.get('/learning/prog/data-structures/'),
  recommend: (params) => request.get('/learning/prog/recommend/', { params }),
  dailyChallenge: (params) => request.get('/learning/prog/daily-challenge/', { params }),
  drill: (type, params) => request.get(`/learning/prog/drill/${type}/`, { params }),
  drillRandom: (params) => request.get('/learning/prog/drill/random/', { params }),
  drillGrade: (data) => request.post('/learning/prog/drill/grade/', data),
  quizSubmit: (answers) => request.post('/learning/prog/drill/quiz-submit/', { answers }),
  progress: (params) => request.get('/learning/prog/progress/', { params }),
  saveProgress: (data) => request.post('/learning/prog/progress/', data),
  bookmarks: (params) => request.get('/learning/prog/snippets/bookmarks/', { params }),
  addBookmark: (data) => request.post('/learning/prog/snippets/bookmarks/', data),
  delBookmark: (id) => request.delete(`/learning/prog/snippets/bookmarks/?id=${id}`),
  // —— K12 学科 ——
  stages: () => request.get('/learning/school/stages/'),
  subject: (stage, subject) => request.get(`/learning/school/stages/${stage}/subjects/${subject}/`),
  knowledgeTree: (params) => request.get('/learning/school/knowledge/', { params }),
  knowledge: (id) => request.get(`/learning/school/knowledge/${id}/`),
  knowledgeSearch: (q) => request.get('/learning/school/knowledge/search/', { params: { q } }),
  formulas: (params) => request.get('/learning/school/formulas/', { params }),
  formula: (key) => request.get(`/learning/school/formulas/${key}/`),
  formulaCalc: (key, values) => request.post('/learning/school/formulas/calc/', { key, values }),
  poems: (params) => request.get('/learning/school/poems/', { params }),
  poem: (key) => request.get(`/learning/school/poems/${key}/`),
  poemDrill: (params) => request.get('/learning/school/poems/drill/', { params }),
  words: (params) => request.get('/learning/school/words/', { params }),
  word: (w) => request.get(`/learning/school/words/${w}/`),
  dictation: (params) => request.get('/learning/school/words/dictation/', { params }),
  wordQuiz: (params) => request.get('/learning/school/words/quiz/', { params }),
  wordbook: (params) => request.get('/learning/school/words/wordbook/', { params }),
  addWord: (word) => request.post('/learning/school/words/wordbook/', { word }),
  toggleWord: (id) => request.patch('/learning/school/words/wordbook/', { id }),
  delWord: (id) => request.delete(`/learning/school/words/wordbook/?id=${id}`),
  questions: (params) => request.get('/learning/school/questions/', { params }),
  question: (id) => request.get(`/learning/school/questions/${id}/`),
  paperCompose: (params) => request.get('/learning/school/paper/compose/', { params }),
  paperGrade: (answers) => request.post('/learning/school/paper/grade/', { answers }),
  mistakes: (params) => request.get('/learning/school/mistakes/', { params }),
  addMistake: (data) => request.post('/learning/school/mistakes/', data),
  toggleMistake: (id) => request.patch('/learning/school/mistakes/', { id }),
  delMistake: (id) => request.delete(`/learning/school/mistakes/?id=${id}`),
  mastery: () => request.get('/learning/school/mastery/'),
  idioms: (q) => request.get('/learning/school/idioms/', { params: { q } }),
  idiomChain: (word) => request.get('/learning/school/idioms/chain/', { params: { word } }),
  hanzi: (params) => request.get('/learning/school/hanzi/', { params }),
  elements: (params) => request.get('/learning/school/elements/', { params }),
  element: (key) => request.get(`/learning/school/elements/${key}/`),
  equations: (params) => request.get('/learning/school/equations/', { params }),
  grammar: (params) => request.get('/learning/school/grammar/', { params }),
  grammarDetail: (key) => request.get(`/learning/school/grammar/${key}/`),
  // —— 个人学习中心 ——
  sessions: (params) => request.get('/learning/study/sessions/', { params }),
  addSession: (data) => request.post('/learning/study/sessions/', data),
  delSession: (id) => request.delete(`/learning/study/sessions/?id=${id}`),
  plans: () => request.get('/learning/study/plans/'),
  addPlan: (data) => request.post('/learning/study/plans/', data),
  updatePlan: (data) => request.patch('/learning/study/plans/', data),
  delPlan: (id) => request.delete(`/learning/study/plans/?id=${id}`),
  // —— 学习雷达（v8：弱项 / 多语言进度，手写 SVG）——
  weaknessRadar: () => request.get('/learning/study/weakness/'),
  progRadar: () => request.get('/learning/prog/radar/'),
  // —— v8 学习闭环（打卡 / 复习队列 / 错题重练 / 报告 / 备份 / 全局搜索）——
  studyStreak: () => request.get('/learning/study/streak/'),
  studyReport: (month) => request.get('/learning/study/report/', { params: month ? { month } : {} }),
  reviewQueue: () => request.get('/learning/study/review-queue/'),
  reviewMark: (kind, id) => request.post('/learning/study/review-queue/', { kind, id }),
  reDrill: (params) => request.get('/learning/study/re-drill/', { params }),
  reDrillSubmit: (id, answer) => request.post('/learning/study/re-drill/', { id, answer }),
  backupExport: () => request.get('/learning/study/backup/'),
  backupImport: (data) => request.post('/learning/study/backup/', data),
  globalSearch: (q) => request.get('/learning/search/', { params: { q } }),
  // —— v8 学习区新增能力（F523–F546，dsh 接口 / Doubao 接线）——
  dailyGoal: () => request.get('/learning/study/daily-goal/'),                                   // F523
  saveDailyGoal: (data) => request.post('/learning/study/daily-goal/', data),
  pomodoro: () => request.get('/learning/study/pomodoro/'),                                     // F524
  pomodoroSave: (data) => request.post('/learning/study/pomodoro/', data),
  questionSets: () => request.get('/learning/study/question-sets/'),                            // F525
  questionSet: (id) => request.get('/learning/study/question-sets/', { params: { id } }),
  saveQuestionSet: (data) => request.post('/learning/study/question-sets/', data),
  updateQuestionSet: (data) => request.patch('/learning/study/question-sets/', data),
  delQuestionSet: (id) => request.delete(`/learning/study/question-sets/?id=${id}`),
  masteryRatings: (stageSubject) => request.get('/learning/study/mastery-rating/', { params: stageSubject ? { stage_subject: stageSubject } : {} }), // F526
  saveMasteryRating: (data) => request.post('/learning/study/mastery-rating/', data),
  delMasteryRating: (id) => request.delete(`/learning/study/mastery-rating/?id=${id}`),
  poemFillBlank: (key) => request.get('/learning/school/poems/fill-blank/', { params: key ? { key } : {} }), // F528
  poemFillSubmit: (data) => request.post('/learning/school/poems/fill-blank/', data),
  idiomChainRecords: () => request.get('/learning/school/idioms/chain-records/'),               // F529
  saveIdiomChain: (data) => request.post('/learning/school/idioms/chain-records/', data),
  equationPractice: () => request.get('/learning/school/equations/practice/'),                  // F530
  equationPracticeSubmit: (data) => request.post('/learning/school/equations/practice/', data),
  dictationCollect: (words) => request.post('/learning/school/words/dictation/collect/', { words }), // F531
  dictationGrade: (items) => request.post('/learning/school/words/dictation/grade/', { items }), // F543
  formulaFavorites: () => request.get('/learning/school/formulas/favorites/'),                  // F532
  toggleFormulaFavorite: (key) => request.post('/learning/school/formulas/favorites/', { key }),
  questionFavorites: () => request.get('/learning/school/questions/favorites/'),                // F536
  toggleQuestionFavorite: (id) => request.post('/learning/school/questions/favorites/', { id }),
  paperArchives: () => request.get('/learning/study/paper-archive/'),                           // F537
  paperArchive: (id) => request.get('/learning/study/paper-archive/', { params: { id } }),
  savePaperArchive: (data) => request.post('/learning/study/paper-archive/', data),
  updatePaperArchive: (data) => request.patch('/learning/study/paper-archive/', data),
  delPaperArchive: (id) => request.delete(`/learning/study/paper-archive/?id=${id}`),
  toolUsage: () => request.get('/learning/study/tool-usage/'),                                  // F538
  saveToolUsage: (key) => request.post('/learning/study/tool-usage/', { key }),
  knowledgeRelated: (kid) => request.get('/learning/school/knowledge/related/', { params: { kid } }), // F539
  learningBadges: () => request.get('/learning/study/badges/'),                                 // F540
  progressDetail: (id) => request.get('/learning/study/progress-detail/', { params: { id } }),  // F544
  mistakeCause: () => request.get('/learning/study/mistake-cause/'),                            // F545
  setMistakeCause: (data) => request.post('/learning/study/mistake-cause/', data),
  planDetail: (id) => request.get('/learning/study/plan-detail/', { params: { id } }),          // F546
  // —— 40 个学习工具 ——
  toolCatalog: () => request.get('/learning/tools/catalog/'),
  toolRun: (tool, params) => request.post('/learning/tools/run/', { tool, ...params }),
}

// ===== 全文搜索（倒排索引 + BM25）=====
export const searchApi = {
  fulltext: (params) => request.get('/core/search/fulltext/', { params }),
  suggest: (q, limit = 10) => request.get('/core/search/suggest/', { params: { q, limit } }),
  stats: () => request.get('/core/search/stats/'),
  reindex: (data = { scope: 'own' }) => request.post('/core/search/reindex/', data),
  global: (q) => request.get('/core/search/', { params: { q } }),
  history: () => request.get('/core/search/history/'),
  clearHistory: () => request.delete('/core/search/history/'),
  hot: () => request.get('/core/search/hot/'),
  exportUrl: (q) => apiUrl(`/api/core/search/export/?q=${encodeURIComponent(q)}`),
}

// ===== 组织架构 / 数据范围 / 多租户 =====
export const orgApi = {
  myScope: () => request.get('/auth/me/scope/'),
  departments: (params) => request.get('/auth/admin/departments/', { params }),
  department: (id) => request.get(`/auth/admin/departments/${id}/`),
  createDepartment: (data) => request.post('/auth/admin/departments/', data),
  updateDepartment: (id, data) => request.patch(`/auth/admin/departments/${id}/`, data),
  deleteDepartment: (id) => request.delete(`/auth/admin/departments/${id}/`),
  tenants: () => request.get('/auth/admin/tenants/'),
  tenant: (id) => request.get(`/auth/admin/tenants/${id}/`),
  createTenant: (data) => request.post('/auth/admin/tenants/', data),
  updateTenant: (id, data) => request.patch(`/auth/admin/tenants/${id}/`, data),
  deleteTenant: (id) => request.delete(`/auth/admin/tenants/${id}/`),
}

// ===== AI 助手 =====
// 走大模型的 POST 请求放宽超时：后端 LLM_TIMEOUT 默认 90s，推理慢时更久；
// 普通接口仍走全局 60s，挂住时能尽快报错。
const AI_TIMEOUT = 180000
export const aiApi = {
  status: () => request.get('/assistant/status/'),
  // 笔记摘要 / 问答
  summarize: (noteId, data = {}) => request.post(`/assistant/notes/${noteId}/summarize/`, data, { timeout: AI_TIMEOUT }),
  cachedSummary: (noteId) => request.get(`/assistant/notes/${noteId}/summarize/`),
  askNote: (noteId, question) => request.post(`/assistant/notes/${noteId}/ask/`, { question }, { timeout: AI_TIMEOUT }),
  ask: (question, extra = {}) => request.post('/assistant/ask/', { question, ...extra }, { timeout: AI_TIMEOUT }),
  // 聊天助手
  chat: (message, opts = {}) => request.post('/assistant/chat/', { message, ...opts }, { timeout: AI_TIMEOUT }),
  conversations: () => request.get('/assistant/conversations/'),
  createConversation: (data) => request.post('/assistant/conversations/', data),
  conversation: (id) => request.get(`/assistant/conversations/${id}/`),
  renameConversation: (id, title) => request.patch(`/assistant/conversations/${id}/`, { title }),
  deleteConversation: (id) => request.delete(`/assistant/conversations/${id}/`),
  // 出题 / 批改
  generateQuestions: (data) => request.post('/assistant/questions/generate/', data, { timeout: AI_TIMEOUT }),
  myQuestions: (params) => request.get('/assistant/questions/', { params }),
  deleteQuestions: (ids) => request.delete('/assistant/questions/', { data: { ids } }),
  grade: (items, recordMistakes = true) =>
    request.post('/assistant/grade/', { items, record_mistakes: recordMistakes }, { timeout: AI_TIMEOUT }),
  // 自动标签 / 写作润色 / 每日摘要（#59 #61 #60）
  autoTag: (data) => request.post('/assistant/auto-tag/', data, { timeout: AI_TIMEOUT }),
  polish: (data) => request.post('/assistant/polish/', data, { timeout: AI_TIMEOUT }),
  dailyDigest: (data = {}) => request.post('/assistant/daily-digest/', data, { timeout: AI_TIMEOUT }),
}
