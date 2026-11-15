<template>
  <div class="flex h-screen overflow-hidden">
    <!-- 液态玻璃折射光源：两个固定漂浮光斑，浮层玻璃由此透出流动彩晕 -->
    <div class="liquid-orb orb-a" aria-hidden="true"></div>
    <div class="liquid-orb orb-b" aria-hidden="true"></div>
    <!-- #186 跳过导航：键盘用户第一个 Tab 即可直达主内容 -->
    <a
      href="#main"
      class="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[120] focus:rounded-control focus:bg-brand-600 focus:px-3 focus:py-1.5 focus:text-[13px] focus:font-medium focus:text-white"
    >跳到主要内容</a>
    <div v-if="mobileOpen" class="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm md:hidden" @click="mobileOpen = false"></div>
    <Sidebar :mobile-open="mobileOpen" @close="mobileOpen = false" />
    <div class="flex min-w-0 flex-1 flex-col">
      <Topbar @toggle-sidebar="mobileOpen = true" />
      <CommandPalette />
      <main id="main" tabindex="-1" class="flex-1 overflow-y-auto p-3 md:p-5">
        <router-view v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </main>
      <!-- #190 视觉 toast 由 App.vue 渲染（不在本次改动范围），这里补一份仅供读屏的 live region -->
      <div class="sr-only" role="status" aria-live="polite">{{ politeToast }}</div>
      <div class="sr-only" role="alert" aria-live="assertive">{{ assertiveToast }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import Sidebar from './components/Sidebar.vue'
import Topbar from './components/Topbar.vue'
import CommandPalette from './components/CommandPalette.vue'
import { useAppStore } from './stores/app'

// 移动端（<md）侧栏改为抽屉：默认收起，不挤压主内容
const mobileOpen = ref(false)
const app = useAppStore()
// #190 错误用 assertive（role=alert），其余提示走 polite（role=status）
const politeToast = computed(() => (app.toast.show && app.toast.type !== 'error' ? app.toast.text : ''))
const assertiveToast = computed(() => (app.toast.show && app.toast.type === 'error' ? app.toast.text : ''))
</script>

<style scoped>
/* 液态光斑配色与位置：品牌色 + 紫罗兰，暗色下收敛透明度。
   颜色通过 color 传给 .liquid-orb 的 currentColor 径向渐变。 */
.orb-a {
  top: -12%;
  right: -8%;
  width: 44vw;
  height: 44vw;
  color: color-mix(in srgb, var(--brand-color, var(--brand-500)) 26%, transparent);
}
.orb-b {
  bottom: -16%;
  left: 18%;
  width: 38vw;
  height: 38vw;
  color: rgba(139, 92, 246, 0.18);
  animation-delay: -9s;
}
:global(.dark) .orb-a {
  color: color-mix(in srgb, var(--brand-color, var(--brand-500)) 20%, transparent);
}
:global(.dark) .orb-b {
  color: rgba(139, 92, 246, 0.13);
}
.page-enter-active,
.page-leave-active {
  transition: opacity 0.26s cubic-bezier(0.34, 1.35, 0.64, 1), transform 0.26s cubic-bezier(0.34, 1.35, 0.64, 1);
}
.page-enter-from {
  opacity: 0;
  transform: translateY(12px) scale(0.99);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-5px);
}
</style>
