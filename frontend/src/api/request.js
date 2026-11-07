import axios from 'axios'
import { API_URL, rewriteBackendUrls } from './base'
import { refreshAccessToken } from './refresh'

const request = axios.create({
  baseURL: API_URL,
  timeout: 60000,
})

// #96 统一错误码映射
// #203 错误码只存文案 key，渲染时经 t() 取当前语言文案；
// 这里内置一份 key→中文的字典（不引入 i18n 库），默认输出与改造前完全一致。
const ERROR_MESSAGES = {
  1001: 'err.invalid_params',
  1002: 'err.username_taken',
  1003: 'err.email_taken',
  1004: 'err.weak_password',
  1005: 'err.old_password',
  1006: 'err.account_disabled',
  1007: 'err.invite_invalid',
  1008: 'err.invite_required',
  1009: 'err.file_too_large',
  1010: 'err.quota_exceeded',
  1011: 'err.forbidden',
  1012: 'err.resource_locked',
  1013: 'err.network',
  1014: 'err.server',
  1015: 'err.session_expired',
  1016: 'err.login_locked',
  1017: 'err.need_2fa',
  1018: 'err.bad_2fa',
}

const ERROR_TEXT = {
  'err.invalid_params': '参数校验失败，请检查输入',
  'err.username_taken': '用户名已被占用',
  'err.email_taken': '该邮箱已被注册',
  'err.weak_password': '密码强度不足',
  'err.old_password': '原密码不正确',
  'err.account_disabled': '账号已被禁用',
  'err.invite_invalid': '邀请码无效或已过期',
  'err.invite_required': '需要邀请码才能注册',
  'err.file_too_large': '文件超出大小限制',
  'err.quota_exceeded': '存储配额已满',
  'err.forbidden': '没有操作权限',
  'err.resource_locked': '资源被锁定',
  'err.network': '网络异常，请稍后重试',
  'err.server': '服务器内部错误',
  'err.session_expired': '登录已过期，请重新登录',
  'err.login_locked': '登录失败次数过多，账号已临时锁定',
  'err.need_2fa': '该账号已开启两步验证，请输入验证码',
  'err.bad_2fa': '两步验证码错误或已过期',
}

/** 极简翻译：命中字典取文案，未命中回落 key 本身 */
function t(key) {
  return ERROR_TEXT[key] || key
}

// #419 错误码目录：后端 /core/errors/catalog/ 反射 ERR_* 返回 {code,message,hint}。
// 启动时非阻塞拉取并合并进本地映射；拉取失败则保持现有映射不变。
// 用裸 axios + 绝对地址，绕开 request 实例的鉴权/错误拦截器，避免循环请求。
const ERROR_CATALOG = {}
axios
  .get(`${API_URL}/core/errors/catalog/`, { timeout: 8000 })
  .then((res) => {
    const rows = res?.data?.list
    if (!Array.isArray(rows)) return
    for (const row of rows) {
      if (row && row.code != null) {
        ERROR_CATALOG[row.code] = { message: row.message || '', hint: row.hint || '' }
      }
    }
  })
  .catch(() => { /* 目录不可用时静默降级，沿用原有映射 */ })

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // #94 记录请求开始时间
  config._startTime = performance.now()
  return config
})

let redirecting = false

// 认证类接口的 401 是「业务结果」（密码错误、验证码错误、refresh 失效），
// 不能当成令牌过期去刷新/跳转，否则登录失败会变成整页刷新死循环。
const AUTH_ENDPOINTS = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/2fa']

function isAuthEndpoint(url) {
  const path = String(url || '').split('?')[0]
  return AUTH_ENDPOINTS.some((p) => path.includes(p))
}

function clearAuthAndRedirect() {
  // 只清认证数据，保留 theme / 快捷入口 / 侧边栏等偏好设置
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  if (redirecting) return
  if (window.location.pathname === '/login') return
  redirecting = true
  window.location.href = '/login'
}

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
    const skipAuthHandling = isAuthEndpoint(config?.url)
    if (response && response.status === 401 && !skipAuthHandling && config && !config._retry) {
      config._retry = true
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          // 与 WebSocket 共用同一个刷新单例：refresh 已轮换，并发兑换必失败
          const access = await refreshAccessToken()
          config.headers.Authorization = `Bearer ${access}`
          return await request(config)
        } catch (e) {
          // 刷新失败、超时，或刷新后重试仍 401：统一清登录态，不再卡死
          if (!e?.response || e.response.status === 401 || e.response.status === 403) {
            clearAuthAndRedirect()
          }
          throw e
        }
      } else {
        clearAuthAndRedirect()
      }
    }
    // #96 统一错误码映射（#203 经 t() 渲染文案；#419 合并后端错误码目录与 hint）
    const code = response?.data?.code
    const catalog = code != null
      ? (ERROR_CATALOG[code] || ERROR_CATALOG[Number(code)] || null)
      : null
    const messageKey = code && ERROR_MESSAGES[code]
    let message = (messageKey && t(messageKey)) || catalog?.message || response?.data?.message || response?.data?.error || error.message || '请求失败'
    // 处置建议（hint）拼在文案后，toast 直接展示时更可操作
    if (catalog?.hint && !message.includes(catalog.hint)) {
      message = `${message} · ${catalog.hint}`
    }
    // 保留原始 error 字段，避免调用方拿不到 response/code
    error.message = message
    error.code = code
    error.status = response?.status
    return Promise.reject(error)
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
