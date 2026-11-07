import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAppStore } from './stores/app'
import { useUserStore } from './stores/user'
import { reportClientError } from './api/corex'
import { initI18n } from './i18n'
import './style.css'

// #197 启动即同步 <html lang> 与已保存语言，首屏文案与读屏语音一致
initI18n()

const app = createApp(App)
app.use(createPinia())
app.use(router)

// F10：全局错误兜底——错误不再静默。
// 1) Vue 渲染 / 生命周期 / watcher 抛出的同步错误走 errorHandler；
// 2) 事件处理器、定时器、WebSocket 回调里未被捕获的 Promise rejection 走 unhandledrejection。
// 两者统一弹 toast（拦截器已把后端错误码映射成中文，这里直接取 e.message）。
// F15：同时上报到后端异常聚合（/core/admin/exceptions/report/，登录即可）。
// 防循环三件套：有 token 才报（未登录 401 无意义）；.catch 吞掉上报本身的失败
// （否则上报失败又会变成 unhandledrejection 再次进入本函数）；reportClientError
// 内部已按 message 去重 + try/catch。
const toast = useAppStore()
let lastText = ''
let lastAt = 0
function reportError(err, source) {
  const text = (err && (err.message || (typeof err === 'string' ? err : ''))) || '发生未知错误'
  console.error(`[${source}]`, err)
  if (typeof localStorage !== 'undefined' && localStorage.getItem('access_token')) {
    try {
      Promise.resolve(reportClientError(err, typeof location !== 'undefined' ? location.pathname : ''))
        .catch(() => { /* 上报失败不影响 toast 主流程，更不能变成新的 rejection */ })
    } catch { /* 上报入口异常（如隐私模式 sessionStorage 不可用）直接忽略 */ }
  }
  // 同一条错误 2 秒内只提示一次，防止轮询类失败把 toast 顶住不消失
  const now = Date.now()
  if (text === lastText && now - lastAt < 2000) return
  lastText = text
  lastAt = now
  toast.toastMsg(text, 'error')
}
app.config.errorHandler = (err, vm, info) => reportError(err, `vue:${info}`)
window.addEventListener('unhandledrejection', (e) => reportError(e.reason, 'unhandledrejection'))

// F20：request.js 刷新令牌后只写了 localStorage 并派发 auth:token 事件，
// 这里接住它同步进 Pinia——否则 store 里的 token 停留在刷新前的旧值，
// WS 重连、路由守卫等读 store.token 的地方都会用过期的令牌。
// App.vue 的 watch(() => user.token, syncWs) 会顺势用新令牌重建实时通道。
const userStore = useUserStore()
window.addEventListener('auth:token', (e) => {
  const access = e.detail?.access
  if (access && userStore.token !== access) userStore.token = access
})

// 已登录状态下启动即校准权限：is_admin/权限码持久化后仍以服务端为准，
// 避免管理员刷新后进不了后台；请求失败时保留缓存值，不阻塞挂载。
if (userStore.token) {
  userStore.fetchPermissions()
}

app.mount('#app')

// F59 PWA：仅生产构建注册 Service Worker（开发环境注册会干扰 Vite HMR 与代理）
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  let refreshing = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return
    refreshing = true
    window.location.reload()
  })
  window.addEventListener('load', () => {
    // #198 构建号作为 cache 版本，发版后旧 cache 自动失效
    navigator.serviceWorker.register(`/sw.js?v=${__APP_BUILD__}`).then((reg) => {
      reg.addEventListener('updatefound', () => {
        const sw = reg.installing
        if (!sw) return
        sw.addEventListener('statechange', () => {
          if (sw.state === 'installed' && navigator.serviceWorker.controller) {
            if (window.confirm('发现新版本，是否立即刷新？')) sw.postMessage({ type: 'SKIP_WAITING' })
          }
        })
      })
    }).catch(() => { /* 离线能力不可用不影响在线使用 */ })
  })
}
