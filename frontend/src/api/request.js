import axios from 'axios'
import { API_URL, rewriteBackendUrls } from './base'

const request = axios.create({
  baseURL: API_URL,
  timeout: 60000,
})

// #96 统一错误码映射
const ERROR_MESSAGES = {
  1001: '参数校验失败，请检查输入',
  1002: '用户名已被占用',
  1003: '该邮箱已被注册',
  1004: '密码强度不足',
  1005: '原密码不正确',
  1006: '账号已被禁用',
  1007: '邀请码无效或已过期',
  1008: '需要邀请码才能注册',
  1009: '文件超出大小限制',
  1010: '存储配额已满',
  1011: '没有操作权限',
  1012: '资源被锁定',
  1013: '网络异常，请稍后重试',
  1014: '服务器内部错误',
  1015: '登录已过期，请重新登录',
}

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // #94 记录请求开始时间
  config._startTime = performance.now()
  return config
})

let refreshing = null

request.interceptors.response.use(
  (res) => {
    // #94 记录响应耗时
    if (res.config._startTime) {
      const duration = performance.now() - res.config._startTime
      recordLatency(res.config.url, duration)
    }
    return rewriteBackendUrls(res.data)
  },
  async (error) => {
    const { response, config } = error
    // #94 记录失败请求耗时
    if (config?._startTime) {
      recordLatency(config.url, performance.now() - config._startTime)
    }
    if (response && response.status === 401 && !config._retry) {
      config._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          refreshing = refreshing || axios.post(`${API_URL}/auth/refresh/`, { refresh }).then((r) => r.data)
          const { access } = await refreshing
          refreshing = null
          localStorage.setItem('access_token', access)
          config.headers.Authorization = `Bearer ${access}`
          return request(config)
        } catch (e) {
          refreshing = null
          localStorage.clear()
          window.location.href = '/login'
        }
      } else {
        window.location.href = '/login'
      }
    }
    // #96 统一错误码映射
    const code = response?.data?.code
    const message = (code && ERROR_MESSAGES[code]) || response?.data?.message || response?.data?.error || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

// #94 性能监控：记录接口耗时到 localStorage
function recordLatency(url, duration) {
  try {
    const key = 'api_latency_samples'
    const samples = JSON.parse(localStorage.getItem(key) || '[]')
    // 只记录 API 路径（不含 baseURL），截取前 40 字符作为路径分组
    const path = (url || '').split('?')[0].slice(0, 40)
    samples.push({ path, duration: Math.round(duration), ts: Date.now() })
    // 保留最近 500 条
    if (samples.length > 500) samples.splice(0, samples.length - 500)
    localStorage.setItem(key, JSON.stringify(samples))
  } catch (e) { /* ignore */ }
}

export default request
