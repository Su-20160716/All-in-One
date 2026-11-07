/**
 * 业务中心 API 封装（所有业务模块共用一套 CRUD / 分析 / 治理接口）。
 *
 * 后端在 /api/biz/ 下统一返回 {ok:true,data}，这里用 unwrap 把 data 拍平，
 * 页面直接拿业务字段；失败仍 reject（由页面 catch 后统一 toast）。
 * 导出接口是文件流，走 responseType:'blob'，不参与 unwrap。
 */
import request from './request'

const D = '/biz'

/** 拆掉 {ok,data} 包装；结构不符时原样返回，方便降级处理 */
export function unwrap(p) {
  return p.then((r) => (r && typeof r === 'object' && r.ok === true && r.data !== undefined ? r.data : r))
}

/** 列表类返回既可能是数组也可能是 {items:[...]}，统一成数组 */
function listOf(d) {
  if (Array.isArray(d)) return d
  if (d && Array.isArray(d.items)) return d.items
  if (d && Array.isArray(d.results)) return d.results
  return []
}

export const bizApi = {
  // ---------------- 目录 / 概览 ----------------
  // {module_count,feature_count,groups[],modules[]}
  modules: () => unwrap(request.get(`${D}/modules/`)),
  // 模块详情：额外含 fields / features
  moduleDetail: (slug) => unwrap(request.get(`${D}/modules/${slug}/`)),
  // {module_count,feature_count,record_count,overdue_count,by_group[]}
  overview: () => unwrap(request.get(`${D}/overview/`)),
  // 成员既可返回 {items} 也可能直接是数组
  members: () => unwrap(request.get(`${D}/members/`)).then(listOf),

  // ---------------- 记录 CRUD ----------------
  // params: q,status,category,priority,owner,tag,favorite,archived,deleted,include_archived,ordering,page,page_size
  records: (slug, params) => unwrap(request.get(`${D}/${slug}/records/`, { params })),
  createRecord: (slug, payload) => unwrap(request.post(`${D}/${slug}/records/`, payload)),
  record: (slug, id) => unwrap(request.get(`${D}/${slug}/records/${id}/`)),
  updateRecord: (slug, id, payload) => unwrap(request.patch(`${D}/${slug}/records/${id}/`, payload)),
  deleteRecord: (slug, id) => unwrap(request.delete(`${D}/${slug}/records/${id}/`)),
  restoreRecord: (slug, id) => unwrap(request.post(`${D}/${slug}/records/${id}/restore/`, {})),
  archiveRecord: (slug, id) => unwrap(request.post(`${D}/${slug}/records/${id}/archive/`, {})),
  unarchiveRecord: (slug, id) => unwrap(request.post(`${D}/${slug}/records/${id}/unarchive/`, {})),
  duplicateRecord: (slug, id) => unwrap(request.post(`${D}/${slug}/records/${id}/duplicate/`, {})),

  // ---------------- 评论 / 时间线 / 收藏 ----------------
  comments: (slug, id) => unwrap(request.get(`${D}/${slug}/records/${id}/comments/`)).then(listOf),
  addComment: (slug, id, content) =>
    unwrap(request.post(`${D}/${slug}/records/${id}/comments/`, { content })),
  timeline: (slug, id) => unwrap(request.get(`${D}/${slug}/records/${id}/timeline/`)).then(listOf),
  // favorite 不传则后端切换；传布尔则显式设置
  favorite: (slug, id, favorite) =>
    unwrap(request.post(`${D}/${slug}/records/${id}/favorite/`, typeof favorite === 'boolean' ? { favorite } : {})),

  // ---------------- 批量 ----------------
  // {action:'status'|'owner'|'tag'|'archive'|'delete', ids,...} → {updated,skipped,ids}
  bulk: (slug, payload) => unwrap(request.post(`${D}/${slug}/bulk/`, payload)),

  // ---------------- 导入 / 导出 ----------------
  // CSV 文件流；失败由页面 describeDownloadError 解析
  exportCsv: (slug, params) =>
    request.get(`${D}/${slug}/export/`, {
      params: { fmt: 'csv', ...(params || {}) },
      responseType: 'blob',
    }),
  // {csv} 或 {rows}; → {total,created,errors:[{row,message}]}
  importRecords: (slug, payload) => unwrap(request.post(`${D}/${slug}/import/`, payload)),

  // ---------------- 分析 ----------------
  stats: (slug) => unwrap(request.get(`${D}/${slug}/stats/`)),
  trend: (slug, days = 30) => unwrap(request.get(`${D}/${slug}/trend/`, { params: { days } })),
  distribution: (slug, field) => unwrap(request.get(`${D}/${slug}/distribution/`, { params: { field } })),
  overdue: (slug) => unwrap(request.get(`${D}/${slug}/overdue/`)),
  quality: (slug) => unwrap(request.get(`${D}/${slug}/quality/`)),

  // ---------------- 合并 ----------------
  merge: (slug, ids, primary_id) =>
    unwrap(request.post(`${D}/${slug}/merge/`, { ids, primary_id })),

  // ---------------- 保存视图 ----------------
  savedViews: (slug) => unwrap(request.get(`${D}/${slug}/saved-views/`)).then(listOf),
  // {name, params}（后端字段名可能是 query/filters，三处都带一份，后端取其一即可）
  createSavedView: (slug, payload) => unwrap(request.post(`${D}/${slug}/saved-views/`, payload)),
  deleteSavedView: (slug, id) =>
    unwrap(request.delete(`${D}/${slug}/saved-views/`, { params: { id } })),

  // ---------------- 订阅 ----------------
  // {enabled,frequency,last_sent_at}
  subscription: (slug) => unwrap(request.get(`${D}/${slug}/subscription/`)),
  saveSubscription: (slug, payload) => unwrap(request.post(`${D}/${slug}/subscription/`, payload)),
}

export default bizApi
