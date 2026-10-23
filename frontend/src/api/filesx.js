/**
 * 文件中心扩展接口（F547–F564）
 * 只封装新增能力，不改动 src/api/index.js 既有契约。
 */
import request from './request'
import { apiUrl } from './base'

export const filesx = {
  // F547 重复文件检测（hash 分组）
  duplicates: (limit = 100) => request.get('/files/duplicates/', { params: { limit } }),
  // F548 存储体积 30 天趋势（SVG 数据）
  storageTrend: (days = 30) => request.get('/files/storage-trend/', { params: { days } }),
  // F549 大文件清单（阈值可调）
  largeFiles: (minMb = 50, limit = 200) =>
    request.get('/files/large-files/', { params: { min_mb: minMb, limit } }),
  // F550 文件清单导出 CSV（走 axios 带 JWT，返回 blob 下载）
  exportCsvUrl: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== null && v !== undefined) qs.set(k, v)
    })
    const s = qs.toString()
    return `/files/export-csv/${s ? `?${s}` : ''}`
  },
  // F551 回收站统计
  trashStats: () => request.get('/files/trash/stats/'),
  // F553 图片分辨率批量徽章（后端计算并缓存）
  imageDims: (ids) => request.get('/files/image-dims/', { params: { ids: ids.join(',') } }),
  // F555 收藏夹自定义排序
  starOrder: (fileIds) => request.post('/files/starred/order/', { file_ids: fileIds }),
  // F556 文件夹搜索命中计数徽章
  folderHits: (q) => request.get('/files/folder-hits/', { params: { q } }),
  // F559 移动/复制操作记录
  operations: (params = {}) => request.get('/files/operations/', { params }),
  // F560 分享链接到期前 3 天提醒
  expiringShares: (days = 3) => request.get('/files/shares/expiring/', { params: { days } }),
  // F561 文件可见性快照
  visibility: (id) => request.get(`/files/${id}/visibility/`),
  takeVisibilitySnapshot: (id, note = '') =>
    request.post(`/files/${id}/visibility/`, { note }),
  // F563 标签统计与点击过滤
  tagsStats: () => request.get('/files/tags/stats/'),
  // F564 收藏/标签 JSON 导出导入
  favoritesExportUrl: apiUrl('/files/favorites/export/'),
  favoritesExport: () => request.get('/files/favorites/export/', { responseType: 'blob' }),
  favoritesImport: (payload) => request.post('/files/favorites/import/', { payload }),
}

export default filesx
