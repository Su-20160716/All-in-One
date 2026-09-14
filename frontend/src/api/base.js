/**
 * 后端基地址配置 —— 免费云部署（Cloudflare Pages + Render）专用
 *
 * 开发环境：不设 VITE_API_BASE，一切走 Vite 代理的相对路径（/api、/media、/ws），行为不变。
 * 生产环境：Cloudflare Pages 构建时设置 VITE_API_BASE=https://<你的服务>.onrender.com，
 *          前端所有请求/WebSocket/媒体地址都会指向 Render 后端。
 */
export const API_BASE = import.meta.env.VITE_API_BASE || ''

// axios / fetch 用的 API 前缀（如 https://xxx.onrender.com/api）
export const API_URL = `${API_BASE}/api`

// 媒体文件前缀（后端返回的 /media/... 相对路径需要拼上后端域名）
export const MEDIA_BASE = API_BASE

/** 给相对路径补全后端基地址；已是绝对地址则原样返回 */
export function withBackendBase(path) {
  if (!path) return path
  if (/^(https?:|wss?:|data:|blob:)/.test(path)) return path
  if (path.startsWith('/media/') || path.startsWith('/share/')) return `${API_BASE}${path}`
  return path
}

/** 递归遍历接口响应，把以 /media/ /share/ 开头的字符串补全为后端绝对地址 */
export function rewriteBackendUrls(data, depth = 0) {
  if (depth > 6 || data == null) return data
  if (typeof data === 'string') return withBackendBase(data)
  if (Array.isArray(data)) {
    for (let i = 0; i < data.length; i++) data[i] = rewriteBackendUrls(data[i], depth + 1)
    return data
  }
  if (typeof data === 'object') {
    for (const k of Object.keys(data)) data[k] = rewriteBackendUrls(data[k], depth + 1)
    return data
  }
  return data
}
