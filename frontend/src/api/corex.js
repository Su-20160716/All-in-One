/**
 * 平台运维扩展接口（F627–F642：健康卡 / 日志导出 / 命令面板 / 趋势 / 分层 /
 * 慢接口 / 异常聚合 / 表统计 / 运行配置 / 维护模式 / 审计检索 / 群发 / 关于）
 *
 * 另含两个“前端上报”助手：接口耗时采样上报、运行时异常上报。
 */
import request from './request'
import { apiUrl } from './base'

export const corexApi = {
  // F627 后端健康卡
  healthCard: () => request.get('/core/admin/health-card/'),
  // F628 日志导出 CSV（operation / login / exception）
  logExportUrl: (kind = 'operation') => apiUrl(`/api/core/admin/logs/export/?kind=${kind}`),
  // F629 管理命令面板（白名单）
  commands: () => request.get('/core/admin/commands/'),
  runCommand: (name) => request.post('/core/admin/commands/run/', { name }),
  // F630 公告已读率趋势（7 天）
  announcementTrend: (params) => request.get('/core/admin/announcement-read-trend/', { params }),
  // F631 用户活跃分层
  activityTiers: (params) => request.get('/core/admin/user-activity-tiers/', { params }),
  // F632 慢接口 TOP10
  slowEndpoints: (params) => request.get('/core/admin/slow-endpoints/', { params }),
  reportLatency: (samples) => request.post('/core/admin/slow-endpoints/report/', { samples }),
  // F633 异常聚合
  exceptions: (params) => request.get('/core/admin/exceptions/', { params }),
  reportException: (data) => request.post('/core/admin/exceptions/report/', data),
  // F634 登录失败 TOP
  loginFailTop: (params) => request.get('/core/admin/login-fail-top/', { params }),
  // F635 数据表行数 / 体积统计
  tableStats: (params) => request.get('/core/admin/table-stats/', { params }),
  // F638 运行配置只读视图（脱敏）
  runtimeConfig: () => request.get('/core/admin/runtime-config/'),
  // F639 维护模式开关
  maintenance: () => request.get('/core/admin/maintenance/'),
  setMaintenance: (enabled) => request.post('/core/admin/maintenance/', { enabled }),
  // F640 跨模块审计检索
  auditSearch: (params) => request.get('/core/admin/audit/search/', { params }),
  // F641 管理员群发通知
  broadcastTargets: (q) => request.get('/core/admin/broadcast/', { params: { q } }),
  broadcast: (data) => request.post('/core/admin/broadcast/', data),
  // F642 关于页
  about: () => request.get('/core/about/'),
}

/** 读出 request.js 记在 localStorage 里的接口耗时样本（读取即清空，避免重复上报） */
export function drainLatencySamples(max = 100) {
  try {
    const raw = JSON.parse(localStorage.getItem('api_latency_samples') || '[]')
    localStorage.removeItem('api_latency_samples')
    if (!Array.isArray(raw) || !raw.length) return []
    return raw.slice(-max).map((s) => ({ path: String(s.path || ''), duration: Number(s.duration) || 0 }))
  } catch (e) {
    return []
  }
}

/** 上报接口耗时采样（F632 前端侧）；静默失败，绝不打扰用户 */
export function reportLatencySamples() {
  try {
    const samples = drainLatencySamples()
    if (!samples.length) return Promise.resolve(null)
    return corexApi.reportLatency(samples).catch(() => null)
  } catch (e) {
    return Promise.resolve(null)
  }
}

/** 上报前端运行时异常（F633 前端侧）；同一会话内每条只报一次 */
export function reportClientError(error, path = '') {
  try {
    const message = String((error && (error.message || error)) || 'unknown error').slice(0, 400)
    const key = `err_reported:${message.slice(0, 80)}`
    if (sessionStorage.getItem(key)) return Promise.resolve(null)
    sessionStorage.setItem(key, '1')
    return corexApi
      .reportException({
        message,
        type: (error && error.name) || 'ClientError',
        path: path || (typeof location !== 'undefined' ? location.pathname : ''),
        stack: (error && error.stack ? String(error.stack) : '').slice(0, 3000),
      })
      .catch(() => null)
  } catch (e) {
    return Promise.resolve(null)
  }
}

export default corexApi
