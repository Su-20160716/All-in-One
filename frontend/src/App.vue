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
import { onMounted, watch } from 'vue'
import { useAppStore } from './stores/app'
import { useUserStore } from './stores/user'
import { stopWs } from './utils/ws'

const app = useAppStore()
const user = useUserStore()

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

onMounted(syncWs)
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
