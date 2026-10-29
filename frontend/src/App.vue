<template>
  <router-view />
  <Transition name="toast">
    <div
      v-if="app.toast.show"
      class="fixed bottom-6 left-1/2 z-[999] -translate-x-1/2 rounded-pill px-4 py-2 text-[13px] text-white shadow-pop"
      :class="app.toast.type === 'error' ? 'bg-rose-500' : app.toast.type === 'success' ? 'bg-emerald-500' : 'bg-ink-800'"
    >
      {{ app.toast.text }}
    </div>
  </Transition>
</template>

<script setup>
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useAppStore } from './stores/app'
import { useUserStore } from './stores/user'
import { stopWs } from './utils/ws'
import { coreApi } from './api'
import { initTheme } from './utils/theme'

const app = useAppStore()
const user = useUserStore()
let stopTheme = null

/** 登录态变化时同步实时通道：有 token 就连，没有就停（避免空转重连） */
function syncWs() {
  if (user.token) {
    app.initWs()
    app.fetchUnread()
    app.fetchNotifications()
  } else {
    app.wsConnected = false
    stopWs()
  }
}

// #57 主题偏好：本地偏好（亮暗 + 强调色）由 utils/theme.js 统一应用
// （F58：data-accent 驱动九级 brand 色阶，跟随系统时监听 OS 切换）

// #100 站点品牌定制：读取公开设置并应用
async function applyBranding() {
  try {
    const r = await coreApi.publicSettings()
    const s = r.settings || {}
    if (s.primary_color) {
      document.documentElement.style.setProperty('--brand-color', s.primary_color)
    }
    if (s.site_name) {
      document.title = `${s.site_name} · 协作平台`
    }
    if (s.logo_url) {
      let link = document.querySelector('link[rel="icon"]')
      if (!link) {
        link = document.createElement('link')
        link.rel = 'icon'
        document.head.appendChild(link)
      }
      link.href = s.logo_url
    }
  } catch (e) { /* ignore */ }
}

onMounted(() => {
  stopTheme = initTheme()
  applyBranding()
  syncWs()
})
onBeforeUnmount(() => stopTheme?.())
watch(() => user.token, syncWs)
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 10px);
}
</style>
