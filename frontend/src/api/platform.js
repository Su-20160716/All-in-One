/**
 * 平台 12 个能力域的通用 API 客户端。
 *
 * 后端所有域都遵循同一响应契约：{ok:true, data}；
 * 列表数据为 {items, count, page, page_size}，也兼容数组与 results。
 * 这里不做端点硬编码，页面按真实路径调用 get/post/list，
 * 避免后端新增端点时还要同步维护第二份映射表。
 */
import request from './request'

/** 拆掉 {ok,data} 包装；结构不符时原样返回 */
export function unwrap(p) {
  return p.then((r) => (r && typeof r === 'object' && r.ok === true && r.data !== undefined ? r.data : r))
}

/** 列表结果统一成 {items, count, page, page_size} */
export function normalizeList(d, fallback = {}) {
  if (Array.isArray(d)) {
    return { items: d, count: d.length, page: 1, page_size: d.length, ...fallback }
  }
  const items = Array.isArray(d?.items)
    ? d.items
    : Array.isArray(d?.results)
      ? d.results
      : Array.isArray(d?.list)
        ? d.list
        : []
  return {
    items,
    count: Number(d?.count ?? d?.total ?? items.length) || 0,
    page: Number(d?.page ?? fallback.page ?? 1) || 1,
    page_size: Number(d?.page_size ?? d?.pageSize ?? fallback.page_size ?? items.length) || items.length,
  }
}

/** 列表结果只要数组（下拉、图表等场景） */
export function listOf(d) {
  return normalizeList(d).items
}

function joinPath(prefix, path) {
  const base = String(prefix || '').startsWith('/') ? String(prefix) : `/${prefix}`
  const tail = String(path || '').replace(/^\/+/, '')
  return tail ? `${base}/${tail}` : `${base}/`
}

/**
 * 为一个域创建客户端。
 * @param {string} prefix 后端前缀，如 '/workflow'
 */
export function domainApi(prefix) {
  const url = (path) => joinPath(prefix, path)
  return {
    prefix,
    /** 能力域目录（含端点清单、枚举、统计口径） */
    catalog: () => unwrap(request.get(url())),
    /** 列表：保留 count/page 元信息 */
    list: (path = '', params) =>
      unwrap(request.get(url(path), { params })).then((d) => normalizeList(d, params || {})),
    /** 列表：只要数组 */
    items: (path = '', params) =>
      unwrap(request.get(url(path), { params })).then((d) => listOf(d)),
    get: (path) => unwrap(request.get(url(path))),
    /** 后端大量使用 POST 创建/更新，这里保留语义化别名 */
    create: (path, data) => unwrap(request.post(url(path), data ?? {})),
    update: (path, data) => unwrap(request.post(url(path), data ?? {})),
    patch: (path, data) => unwrap(request.patch(url(path), data ?? {})),
    remove: (path) => unwrap(request.delete(url(path))),
    post: (path, data) => unwrap(request.post(url(path), data ?? {})),
    /** 领域动作：approve / publish / run / compute 等 */
    action: (path, data) => unwrap(request.post(url(path), data ?? {})),
    /** 需要自定义配置（blob、headers）时直接透传 axios config */
    raw: (config) => request(config),
  }
}

export const workflowApi = domainApi('/workflow')
export const formstudioApi = domainApi('/formstudio')
export const reportingApi = domainApi('/reporting')
export const rulesApi = domainApi('/rules')
export const contractsApi = domainApi('/contracts')
export const pipelineApi = domainApi('/pipeline')
export const billingApi = domainApi('/billing')
export const marketplaceApi = domainApi('/marketplace')
export const flagsApi = domainApi('/flags')
export const observabilityApi = domainApi('/observability')
export const knowledgegraphApi = domainApi('/knowledgegraph')
export const governanceApi = domainApi('/governance')

export const API_BY_DOMAIN = {
  workflow: workflowApi,
  formstudio: formstudioApi,
  reporting: reportingApi,
  rules: rulesApi,
  contracts: contractsApi,
  pipeline: pipelineApi,
  billing: billingApi,
  marketplace: marketplaceApi,
  flags: flagsApi,
  observability: observabilityApi,
  knowledgegraph: knowledgegraphApi,
  governance: governanceApi,
}

export function apiFor(domainKey) {
  return API_BY_DOMAIN[domainKey] || null
}

export const platformApi = {
  ...API_BY_DOMAIN,
  for: apiFor,
  unwrap,
  normalizeList,
  listOf,
}

export default platformApi