/**
 * access token 刷新单例。
 *
 * 后端开启了 ROTATE_REFRESH_TOKENS：同一个 refresh 只能兑换一次，旧值立即进
 * 黑名单。HTTP 拦截器与 WebSocket 各自刷新时若发生并发，后到者会用已作废的
 * refresh 换 token 并失败，把用户无故踢下线。所有调用方共用同一个 in-flight
 * Promise，并在成功后立即写回轮换后的 refresh。
 */
import axios from 'axios'
import { API_URL } from './base'

let inflight = null

export function refreshAccessToken() {
  if (inflight) return inflight
  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) return Promise.reject(new Error('no refresh token'))

  inflight = axios
    .post(`${API_URL}/auth/refresh/`, { refresh }, { timeout: 10000 })
    .then((r) => {
      const data = r.data || {}
      if (!data.access) throw new Error('refresh 未返回 access token')
      localStorage.setItem('access_token', data.access)
      if (data.refresh) localStorage.setItem('refresh_token', data.refresh)
      window.dispatchEvent(new CustomEvent('auth:token', { detail: { access: data.access } }))
      return data.access
    })
    .finally(() => {
      inflight = null
    })
  return inflight
}
