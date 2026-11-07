import request from './request'

/**
 * 项目看板第三轮升级（281–305）新增接口。
 * 只放「第三轮新增/此前前端未接线」的项目接口，沿用 request 的
 * Bearer / 刷新 / 错误文案统一处理；返回值结构与 backend/projects/views.py 一致。
 */
export const pxApi = {
  // 283：列 WIP 上限（active / limit / over_limit）
  wipLimit: (boardId) => request.get(`/projects/boards/${boardId}/wip-limit/`),
  setWipLimit: (boardId, wip_limit) =>
    request.post(`/projects/boards/${boardId}/wip-limit/`, { wip_limit }),

  // 292：项目内搜索（分页 + highlight）+ 305：C-12 编号定位
  search: (projectId, params) => request.get(`/projects/${projectId}/search/`, { params }),
  byNumber: (projectId, code) =>
    request.get(`/projects/${projectId}/cards/by-number/${encodeURIComponent(code)}/`),

  // 288：卡片模板（存为模板 / 模板列表 / 套用）
  saveTemplate: (cardId, data = {}) => request.post(`/projects/cards/${cardId}/save-template/`, data),
  templates: () => request.get('/projects/card-templates/'),
  applyTemplate: (templateId, data) => request.post(`/projects/card-templates/${templateId}/apply/`, data),

  // 289：卡片估时对比
  estimate: (cardId) => request.get(`/projects/cards/${cardId}/estimate/`),
  setEstimate: (cardId, minutes) =>
    request.post(`/projects/cards/${cardId}/estimate/`, { estimated_minutes: minutes }),

  // 290：卡片时间线（分页 / before 游标）
  timeline: (cardId, params) => request.get(`/projects/cards/${cardId}/timeline/`, { params }),

  // 291：批量操作 / 批量移动（目标列超 WIP 时返回 409 over_limit）
  batch: (data) => request.post('/projects/cards/batch/', data),
  batchMove: (data) => request.post('/projects/cards/batch-move/', data),

  // 294：项目活动流（分页 + actor / action 筛选）
  activities: (projectId, params) => request.get(`/projects/${projectId}/activities/`, { params }),

  // 296：已归档卡片（列表 / 恢复 / 彻底删除）
  archivedCards: (projectId, params) =>
    request.get(`/projects/${projectId}/archived-cards/`, { params }),
  archivedAction: (projectId, data) => request.post(`/projects/${projectId}/archived-cards/`, data),
  archiveCard: (cardId, is_archived = true) =>
    request.post(`/projects/cards/${cardId}/archive/`, { is_archived }),

  // 297：成员负载
  workload: (projectId) => request.get(`/projects/${projectId}/workload/`),

  // 298：站会三栏（per_member）
  standup: (projectId, params) => request.get(`/projects/${projectId}/standup/`, { params }),

  // 299：周报（返回 markdown / filename）
  weeklyReport: (projectId, params) =>
    request.get(`/projects/${projectId}/weekly-report/`, { params }),

  // 300：标记解决（写解决说明 + 时间线）
  resolve: (cardId, reason) => request.post(`/projects/cards/${cardId}/resolve/`, { reason }),

  // 301：到期倒计时
  countdown: (cardId) => request.get(`/projects/cards/${cardId}/countdown/`),

  // 304：成员列表（含 open_count / overdue_count）与候选
  members: (projectId, q) => request.get(`/projects/${projectId}/members/`, { params: { q } }),

  // 285：DoD 验收清单
  dod: (cardId) => request.get(`/projects/cards/${cardId}/dod/`),
  addDod: (cardId, content) => request.post(`/projects/cards/${cardId}/dod/`, { content }),
  updateDod: (cardId, itemId, data) =>
    request.patch(`/projects/cards/${cardId}/dod/${itemId}/`, data),
  deleteDod: (cardId, itemId) => request.delete(`/projects/cards/${cardId}/dod/${itemId}/`),

  // 295：卡片关注
  watch: (cardId) => request.get(`/projects/cards/${cardId}/watch/`),
  watchOn: (cardId) => request.post(`/projects/cards/${cardId}/watch/`, {}),
  unwatch: (cardId) => request.delete(`/projects/cards/${cardId}/watch/`),

  // 286：迭代（开启前容量校验，超限 409 warning，confirm=1 再提交）
  sprints: (projectId) => request.get(`/projects/${projectId}/sprints/`),
  sprintAction: (projectId, sprintId, action, data = {}) =>
    request.post(`/projects/${projectId}/sprints/${sprintId}/${action}/`, data),
}

export default pxApi
