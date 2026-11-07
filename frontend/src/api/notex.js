/**
 * 笔记知识库扩展接口（F565–F582）
 * 只封装新增能力，不改动 src/api/index.js 既有契约。
 */
import request from './request'

export const notex = {
  // F565 写作字数目标与完成度
  goals: () => request.get('/notes/goals/'),
  createGoal: (data) => request.post('/notes/goals/', data),
  updateGoal: (id, data) => request.patch(`/notes/goals/${id}/`, data),
  deleteGoal: (id) => request.delete(`/notes/goals/${id}/`),
  // F566 日记视图（按日历聚合）
  diary: (year, month) => request.get('/notes/diary/', { params: { year, month } }),
  // F567 未链接提及清单
  unlinkedMentions: (limit = 50) =>
    request.get('/notes/unlinked-mentions/', { params: { limit } }),
  // F568 随机回顾 🎲
  random: (exclude) => request.get('/notes/random/', { params: { exclude } }),
  // F569 笔记健康度报告
  health: (params = {}) => request.get('/notes/health/', { params }),
  // F573 笔记来源统计
  sources: () => request.get('/notes/sources/'),
  // F574 个人片段库
  snippets: (params = {}) => request.get('/notes/snippets/', { params }),
  createSnippet: (data) => request.post('/notes/snippets/', data),
  updateSnippet: (id, data) => request.patch(`/notes/snippets/${id}/`, data),
  deleteSnippet: (id) => request.delete(`/notes/snippets/${id}/`),
  useSnippet: (id) => request.post(`/notes/snippets/${id}/use/`, {}),
  // F575 两篇笔记合并
  merge: (data) => request.post('/notes/merge/', data),
  // F576 按一级标题拆分笔记
  split: (id, data) => request.post(`/notes/${id}/split/`, data),
  // F579 每周回顾清单
  weeklyReview: (week) => request.get('/notes/weekly-review/', { params: { week } }),
  // F580 `- [ ]` 待办抽取清单
  todos: (params = {}) => request.get('/notes/todos/', { params }),
  toggleTodo: (data) => request.post('/notes/todos/toggle/', data),
  // F581 参考文献引用格式（GB/T7714 / APA）
  citation: (params = {}) => request.get('/notes/citation/', { params }),
  // F582 笔记分组文件夹
  folders: () => request.get('/notes/folders/'),
  createFolder: (data) => request.post('/notes/folders/', data),
  updateFolder: (id, data) => request.patch(`/notes/folders/${id}/`, data),
  deleteFolder: (id) => request.delete(`/notes/folders/${id}/`),
  // F578 选词存生词（对接学习区生词本，失败降级）
  addWord: (word) => request.post('/learning/school/words/wordbook/', { word }),
  listWords: () => request.get('/learning/school/words/wordbook/'),

  // ===== F236–F260 笔记协作 / 素材 / 模板 / 推荐 =====
  // F236 段落讨论
  comments: (id) => request.get(`/notes/${id}/comments/`),
  createComment: (id, data) => request.post(`/notes/${id}/comments/`, data),
  updateComment: (id, cid, data) => request.patch(`/notes/${id}/comments/${cid}/`, data),
  deleteComment: (id, cid) => request.delete(`/notes/${id}/comments/${cid}/`),
  // F237 附件
  attachments: (id) => request.get(`/notes/${id}/attachments/`),
  bindAttachment: (id, data) => request.post(`/notes/${id}/attachments/`, data),
  removeAttachment: (id, aid) => request.delete(`/notes/${id}/attachments/${aid}/`),
  // F237/F239 选文件清单（仅本人未删除文件）
  attachableFiles: (params = {}) => request.get('/notes/attachable-files/', { params }),
  // F243 我的模板
  myTemplates: (params = {}) => request.get('/notes/templates/mine/', { params }),
  createMyTemplate: (data) => request.post('/notes/templates/mine/', data),
  updateMyTemplate: (id, data) => request.patch(`/notes/templates/mine/${id}/`, data),
  deleteMyTemplate: (id) => request.delete(`/notes/templates/mine/${id}/`),
  fromMyTemplate: (id, data = {}) => request.post(`/notes/templates/mine/${id}/create/`, data),
  // F245 相关笔记推荐
  related: (id) => request.get(`/notes/${id}/related/`),
  // F246 快速记录
  quick: (data) => request.post('/notes/quick/', data),
  // F256 标签合并
  mergeTags: (data) => request.post('/notes/tags/merge/', data),
  // F257 双链悬停预览
  preview: (id) => request.get(`/notes/${id}/preview/`),
  previewByTitle: (title, exclude) =>
    request.get('/notes/preview/', { params: { title, exclude } }),
  // F260 置顶区拖拽排序
  pinOrder: (noteIds) => request.post('/notes/pin-order/', { note_ids: noteIds }),
}

export default notex
