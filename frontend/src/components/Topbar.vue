<template>
  <header class="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-ink-100 bg-white px-5 py-2.5">
    <div class="flex min-w-0 items-center gap-3">
      <h1 class="shrink-0 text-[15px] font-semibold text-ink-800">{{ route.meta.title || '全能协作平台' }}</h1>
      <!-- 全局搜索 -->
      <div class="relative">
        <input
          v-model="kw"
          class="input w-72"
          placeholder="全局搜索：文件 / 笔记 / 项目 / 任务…"
          @focus="searching = true"
          @input="onInput"
          @blur="hideLater"
        />
        <div v-if="searching && kw" class="absolute left-0 top-10 z-50 w-96 rounded-card border border-ink-100 bg-white p-2 shadow-pop">
          <template v-if="results.total">
            <div v-if="results.files.length" class="search-group">
              <div class="group-title">文件</div>
              <RouterLink v-for="f in results.files" :key="'f' + f.id" :to="'/files?q=' + encodeURIComponent(f.name)" class="search-item">📄 {{ f.name }}</RouterLink>
            </div>
            <div v-if="results.notes.length" class="search-group">
              <div class="group-title">笔记</div>
              <RouterLink v-for="n in results.notes" :key="'n' + n.id" :to="'/search?q=' + encodeURIComponent(n.title)" class="search-item">📝 {{ n.title }}</RouterLink>
            </div>
            <div v-if="results.projects.length" class="search-group">
              <div class="group-title">项目</div>
              <RouterLink v-for="p in results.projects" :key="'p' + p.id" :to="`/projects/${p.id}/board`" class="search-item">📋 {{ p.name }}</RouterLink>
            </div>
            <div v-if="results.tasks.length" class="search-group">
              <div class="group-title">任务</div>
              <RouterLink v-for="t in results.tasks" :key="'t' + t.id" :to="`/projects/${t.project_id}/board`" class="search-item">✅ {{ t.title }}</RouterLink>
            </div>
          </template>
          <div v-else class="px-2 py-3 text-[12px] text-ink-400">没有找到「{{ kw }}」相关内容</div>
        </div>
      </div>
    </div>

    <div class="flex shrink-0 items-center gap-2">
      <RouterLink to="/announcements" class="btn-ghost px-2 text-[13px]">📣</RouterLink>
      <!-- 通知 -->
      <div class="relative">
        <button class="btn-ghost relative px-2 text-[13px]" @click="toggleNotify">
          🔔
          <span v-if="app.unreadCount > 0" class="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-pill bg-rose-500 px-1 text-[10px] font-medium text-white">
            {{ app.unreadCount > 99 ? '99+' : app.unreadCount }}
          </span>
        </button>
        <div v-if="notifyOpen" class="absolute right-0 top-10 z-50 w-80 rounded-card border border-ink-100 bg-white shadow-pop">
          <div class="flex items-center justify-between border-b border-ink-100 px-3 py-2">
            <span class="text-[13px] font-semibold">通知中心</span>
            <div class="flex gap-1">
              <button class="text-[11px] text-brand-600" @click="readAll">全部已读</button>
              <button class="text-[11px] text-ink-400" @click="clearRead">清空已读</button>
            </div>
          </div>
          <div class="max-h-80 overflow-y-auto">
            <div
              v-for="n in app.notifications"
              :key="n.id"
              class="cursor-pointer border-b border-ink-50 px-3 py-2 text-[12px] hover:bg-ink-50"
              :class="n.is_read ? 'text-ink-400' : 'bg-brand-50/40 text-ink-700'"
              @click="openNotify(n)"
            >
              <div class="flex items-center justify-between">
                <span class="font-medium">{{ n.title }}</span>
                <span class="tag">{{ categoryName(n.category) }}</span>
              </div>
              <div class="mt-0.5 line-clamp-2 text-ink-500">{{ n.content }}</div>
            </div>
            <div v-if="!app.notifications.length" class="px-3 py-6 text-center text-[12px] text-ink-400">暂无通知</div>
          </div>
        </div>
      </div>

      <div class="relative">
        <button class="flex items-center gap-2 rounded-pill py-1 pl-1 pr-2 hover:bg-ink-50" @click="menuOpen = !menuOpen">
          <img v-if="user.profile?.avatar" :src="user.profile.avatar" class="h-7 w-7 rounded-full object-cover" />
          <div v-else class="grid h-7 w-7 place-items-center rounded-full bg-brand-100 text-[12px] font-semibold text-brand-700">
            {{ user.displayName.slice(0, 1) }}
          </div>
          <span class="text-[13px] font-medium text-ink-700">{{ user.displayName }}</span>
          <span class="text-[10px] text-ink-400">▾</span>
        </button>
        <div v-if="menuOpen" class="absolute right-0 top-10 z-50 w-44 overflow-hidden rounded-card border border-ink-100 bg-white py-1 shadow-pop">
          <RouterLink to="/profile" class="block px-3 py-2 text-[13px] hover:bg-ink-50" @click="menuOpen = false">个人设置</RouterLink>
          <RouterLink to="/announcements" class="block px-3 py-2 text-[13px] hover:bg-ink-50" @click="menuOpen = false">系统公告</RouterLink>
          <button class="block w-full px-3 py-2 text-left text-[13px] text-rose-600 hover:bg-rose-50" @click="logout">退出登录</button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'
import { coreApi } from '../api'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const app = useAppStore()
const menuOpen = ref(false)
const notifyOpen = ref(false)
const searching = ref(false)
const kw = ref('')
const results = ref({ files: [], notes: [], projects: [], tasks: [], total: 0 })
let timer = null

const CATS = { system: '系统', file: '文件', note: '笔记', project: '项目', message: '消息', share: '分享' }
const categoryName = (c) => CATS[c] || c

function onInput() {
  clearTimeout(timer)
  timer = setTimeout(doSearch, 300)
}
async function doSearch() {
  if (!kw.value.trim()) {
    results.value = { files: [], notes: [], projects: [], tasks: [], total: 0 }
    return
  }
  try {
    results.value = await coreApi.search(kw.value.trim())
  } catch (e) { /* ignore */ }
}
function hideLater() {
  setTimeout(() => (searching.value = false), 200)
}
function toggleNotify() {
  notifyOpen.value = !notifyOpen.value
  if (notifyOpen.value) app.fetchNotifications()
}
async function readAll() {
  await app.markAllRead()
}
// F23：通知可点击——未读先标已读，再按 link 跳转（站内路径 push，http(s) 外链新开页）
async function openNotify(n) {
  if (!n.is_read) await app.markOneRead(n)
  const link = n.link || ''
  if (!link) return
  if (/^https?:\/\//i.test(link)) window.open(link, '_blank', 'noopener')
  else router.push(link)
}
async function clearRead() {
  await coreApi.deleteNotifications({ scope: 'read' })
  app.fetchNotifications()
}
async function logout() {
  await user.logout()
  router.push('/login')
}
// F23：搜索防抖 timer 卸载时清理，避免组件销毁后回调再触发
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.search-group {
  padding: 4px 0;
}
.group-title {
  padding: 2px 8px;
  font-size: 11px;
  color: #94a3b8;
}
.search-item {
  display: block;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
  color: #334155;
}
.search-item:hover {
  background: #f1f5f9;
}
</style>
