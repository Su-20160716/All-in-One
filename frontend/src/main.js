import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAppStore } from './stores/app'
import { useUserStore } from './stores/user'
import { reportClientError } from './api/corex'
import './style.css'

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

app.mount('#app')
