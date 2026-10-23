/**
 * WebSocket 客户端：JWT 认证 + 令牌自动刷新 + 指数退避重连 + 心跳
 *
 * 修复的历史问题：连接只带 localStorage 里的 access_token，且断开后每 3 秒无条件重连。
 * 一旦 token 过期（默认 12 小时），服务端持续 close(4001)，前端就在
 * 「REJECT → 3 秒后重连 → 再 REJECT」之间无限刷屏，且永远不会自愈
 * —— 因为 HTTP 层的 401 刷新逻辑只有发 API 请求时才会触发，WebSocket 不经过它。
 *
 * 现在的策略：
 *  1. 连接前先确保 token 未过期（临近过期或已过期则用 refresh_token 换新）
 *  2. 被 4001 拒绝时，刷新一次再重试；仍失败则停止重连、清理登录态并回到登录页
 *  3. 普通断线按指数退避重连（3s → 6s → … → 上限 30s），连上后立即复位
 */
import { API_BASE, API_URL } from '../api/base'

const REFRESH_SKEW_MS = 60 * 1000 // 提前 60 秒视为过期，避免握手瞬间失效
const BASE_RETRY_MS = 3000
const MAX_RETRY_MS = 30000
const AUTH_CLOSE_CODE = 4001

let ws = null
let heartbeatTimer = null
let reconnectTimer = null
let retryDelay = BASE_RETRY_MS
let stopped = false
let refreshing = null

const handlers = { onOpen: () => {}, onClose: () => {}, onMessage: () => {} }

function b64urlDecode(str) {
  const b64 = str.replace(/-/g, '+').replace(/_/g, '/')
  const pad = b64.length % 4 ? '='.repeat(4 - (b64.length % 4)) : ''
  const bin = atob(b64 + pad)
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0))
  return new TextDecoder().decode(bytes)
}

/** 解析 JWT payload（不校验签名，仅用于判断本地是否临近过期） */
export function tokenPayload(token) {
  try {
    const part = String(token || '').split('.')[1]
    return part ? JSON.parse(b64urlDecode(part)) : null
  } catch (e) {
    return null
  }
}

/** 本地 access token 是否仍可用；解不出 exp 时交给服务端判断 */
export function accessTokenUsable(skew = REFRESH_SKEW_MS) {
  const token = localStorage.getItem('access_token') || ''
  if (!token) return false
  const payload = tokenPayload(token)
  if (!payload || !payload.exp) return true
  return payload.exp * 1000 - Date.now() > skew
}

/** 取一个「确定还没过期」的 access token；需要时用 refresh_token 换新的 */
export async function ensureFreshToken() {
  const current = localStorage.getItem('access_token') || ''
  if (accessTokenUsable()) return current

  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) return current

  try {
      refreshing =
        refreshing ||
        fetch(`${API_URL}/auth/refresh/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`refresh ${r.status}`))))
    const data = await refreshing
    refreshing = null
    if (data && data.access) {
      localStorage.setItem('access_token', data.access)
      return data.access
    }
  } catch (e) {
    refreshing = null
  }
  return localStorage.getItem('access_token') || ''
}

/**
 * 带 JWT 的 WebSocket 地址（浏览器无法自定义请求头，只能用查询参数）。
 * 不传 token 时读取 localStorage，保持对旧调用的兼容。
 */
export function buildWsUrl(path, token) {
  // 生产环境（VITE_API_BASE 指向 Render）时把后端域名转成 ws/wss；本地开发仍用当前域名
  const base = API_BASE
    ? API_BASE.replace(/^http/, 'ws')
    : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`
  const value = token === undefined ? localStorage.getItem('access_token') || '' : token
  const sep = path.includes('?') ? '&' : '?'
  return `${base}${path}${value ? `${sep}token=${encodeURIComponent(value)}` : ''}`
}

function startHeartbeat() {
  clearInterval(heartbeatTimer)
  heartbeatTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
  }, 30000)
}

function stopHeartbeat() {
  clearInterval(heartbeatTimer)
}

function clearAuthAndGoLogin() {
  try {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user_profile')
  } catch (e) {
    /* ignore */
  }
  if (!location.pathname.startsWith('/login')) location.href = '/login'
}

export async function connectWs(cb = {}) {
  Object.assign(handlers, cb)
  stopped = false
  // 幂等：已连上或正在连接时不重复建连（避免多个重连循环并存）
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return ws
  retryDelay = BASE_RETRY_MS
  clearTimeout(reconnectTimer)
  return openNotify()
}

async function openNotify() {
  if (stopped) return null

  const token = await ensureFreshToken()
  if (stopped) return null
  if (!token) {
    // 没有 token：不打开连接（否则必然 4001），稍后重试等用户登录
    scheduleReconnect()
    return null
  }

  ws = new WebSocket(buildWsUrl('/ws/notify/', token))

  ws.onopen = () => {
    retryDelay = BASE_RETRY_MS
    startHeartbeat()
    handlers.onOpen()
  }
  ws.onmessage = (e) => {
    try {
      handlers.onMessage(JSON.parse(e.data))
    } catch (err) {
      /* ignore */
    }
  }
  ws.onerror = () => {
    /* 随后会触发 onclose，统一在那里处理 */
  }
  ws.onclose = async (e) => {
    stopHeartbeat()
    handlers.onClose()
    if (stopped) return

    if (e && e.code === AUTH_CLOSE_CODE) {
      // 令牌被服务端拒绝：刷新后只重试一次，仍失败就停止刷屏并回登录页
      const fresh = await ensureFreshToken()
      if (fresh && fresh !== token) {
        retryDelay = BASE_RETRY_MS
        openNotify()
        return
      }
      stopWs()
      clearAuthAndGoLogin()
      return
    }
    scheduleReconnect()
  }

  return ws
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer)
  const delay = retryDelay
  reconnectTimer = setTimeout(() => openNotify(), delay)
  retryDelay = Math.min(retryDelay * 2, MAX_RETRY_MS)
}

/** 停止重连（登出、或进入登录页时调用） */
export function stopWs() {
  stopped = true
  clearTimeout(reconnectTimer)
  stopHeartbeat()
  try {
    ws && ws.close()
  } catch (e) {
    /* ignore */
  }
  ws = null
}

export function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj))
}

/**
 * 认证版 WebSocket 封装。
 * 对外保持「同步可用的 socket 对象」语义（readyState / send / close），
 * 内部等 token 就绪后再真正建连，发送的消息在未连上时先入队。
 * 这样 noteApi 协同等调用方无需改成 await。
 */
class AuthedSocket {
  constructor(path, opts = {}) {
    this.path = path
    this.opts = opts
    this.readyState = WebSocket.CONNECTING
    this._socket = null
    this._queue = []
    this._closed = false
    // F8：4001 刷新重连 + 普通断线指数退避（与 connectWs 主通道同策略）
    this._token = ''
    this._retryDelay = BASE_RETRY_MS
    this._retryTimer = null
    this._open()
  }

  async _open() {
    const token = await ensureFreshToken()
    if (this._closed) return
    if (!token) {
      this.readyState = WebSocket.CLOSED
      this.opts.onClose && this.opts.onClose({ code: AUTH_CLOSE_CODE, reason: 'no-token' })
      return
    }
    this._token = token
    const socket = new WebSocket(buildWsUrl(this.path, token))
    this._socket = socket

    socket.onopen = () => {
      this.readyState = WebSocket.OPEN
      this._retryDelay = BASE_RETRY_MS
      this._queue.forEach((d) => socket.send(d))
      this._queue = []
      this.opts.onOpen && this.opts.onOpen()
    }
    socket.onmessage = (e) => {
      try {
        this.opts.onMessage && this.opts.onMessage(JSON.parse(e.data))
      } catch (err) {
        /* ignore */
      }
    }
    socket.onerror = () => {
      /* onclose 会跟着触发 */
    }
    socket.onclose = async (e) => {
      this.readyState = WebSocket.CLOSED
      // 主动 close() 后不重连
      if (this._closed) {
        this.opts.onClose && this.opts.onClose(e)
        return
      }
      if (e && e.code === AUTH_CLOSE_CODE) {
        // F8：令牌被服务端拒绝 → 刷新一次再重连；换不到新令牌则放弃
        //（否则会在 REJECT→重连之间刷屏，且永远不会自愈）
        const fresh = await ensureFreshToken()
        if (fresh && fresh !== this._token) {
          this._retryDelay = BASE_RETRY_MS
          this._open()
          return
        }
        this.opts.onClose && this.opts.onClose(e)
        return
      }
      // F8：普通断线按指数退避重连（3s→6s→…→30s），连上后复位
      this.opts.onReconnecting && this.opts.onReconnecting(this._retryDelay)
      clearTimeout(this._retryTimer)
      this._retryTimer = setTimeout(() => {
        if (!this._closed) this._open()
      }, this._retryDelay)
      this._retryDelay = Math.min(this._retryDelay * 2, MAX_RETRY_MS)
      this.opts.onClose && this.opts.onClose(e)
    }
  }

  send(data) {
    if (this._socket && this._socket.readyState === WebSocket.OPEN) this._socket.send(data)
    else if (!this._closed) this._queue.push(data)
  }

  close() {
    this._closed = true
    clearTimeout(this._retryTimer)
    try {
      this._socket && this._socket.close()
    } catch (e) {
      /* ignore */
    }
  }
}

/** 通用带认证的 WebSocket 连接（供笔记协同等独立通道使用） */
export function createSocket(path, opts = {}) {
  return new AuthedSocket(path, opts)
}
