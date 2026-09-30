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
}

export default notex
