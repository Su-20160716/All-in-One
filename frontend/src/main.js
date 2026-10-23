import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAppStore } from './stores/app'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)

// F10：全局错误兜底——错误不再静默。
// 1) Vue 渲染 / 生命周期 / watcher 抛出的同步错误走 errorHandler；
// 2) 事件处理器、定时器、WebSocket 回调里未被捕获的 Promise rejection 走 unhandledrejection。
// 两者统一弹 toast（拦截器已把后端错误码映射成中文，这里直接取 e.message）。
const toast = useAppStore()
let lastText = ''
let lastAt = 0
function reportError(err, source) {
  const text = (err && (err.message || (typeof err === 'string' ? err : ''))) || '发生未知错误'
  console.error(`[${source}]`, err)
  // 同一条错误 2 秒内只提示一次，防止轮询类失败把 toast 顶住不消失
  const now = Date.now()
  if (text === lastText && now - lastAt < 2000) return
  lastText = text
  lastAt = now
  toast.toastMsg(text, 'error')
}
app.config.errorHandler = (err, vm, info) => reportError(err, `vue:${info}`)
window.addEventListener('unhandledrejection', (e) => reportError(e.reason, 'unhandledrejection'))

app.mount('#app')
