<template>
  <header class="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-ink-100 bg-white px-5 py-2.5">
    <div class="flex min-w-0 items-center gap-3">
      <button class="btn-ghost px-2 text-[16px] md:hidden" aria-label="打开导航" @click="emit('toggle-sidebar')">☰</button>
      <h1 class="shrink-0 text-[15px] font-semibold text-ink-800">{{ route.meta.title || '全能协作平台' }}</h1>
      <!-- 全局搜索 -->
      <div class="relative">
        <input
          v-model="kw"
          class="input w-72"
          placeholder="全局搜索：文件 / 笔记 / 项目 / 任务…"
          aria-label="全局搜索"
          aria-controls="global-search-panel"
          :aria-expanded="!!(searching && kw)"
          @focus="searching = true"
          @input="onInput"
          @keydown="onSearchKeydown"
          @blur="hideLater"
        />
        <div v-if="searching && kw" id="global-search-panel" class="absolute left-0 top-10 z-50 w-96 rounded-card border border-ink-100 bg-white p-2 shadow-pop">
          <template v-if="results.total">
            <!-- #177 ↑↓ 移动、Enter 打开、Esc 关闭；高亮项随键盘滚动可见 -->
            <div v-for="g in resultGroups" :key="g.title" class="search-group">
              <div class="group-title">{{ g.title }}</div>
              <RouterLink
                v-for="it in g.items"
                :key="it.idx"
                :ref="(el) => setItemRef(el, it.idx)"
                :to="it.to"
                class="search-item"
                :class="{ 'search-item-active': activeIndex === it.idx }"
                @click="closeSearch"
              >{{ it.label }}</RouterLink>
            </div>
          </template>
          <div v-else class="px-2 py-3 text-[12px] text-ink-400">没有找到「{{ kw }}」相关内容</div>
        </div>
      </div>
    </div>

    <div class="flex shrink-0 items-center gap-2">
      <!-- #193 纯图标按钮补 aria-label/title，头像补描述性 alt -->
      <RouterLink to="/announcements" class="btn-ghost px-2 text-[13px]" aria-label="系统公告" title="系统公告">📣</RouterLink>
      <!-- 通知 -->
      <div ref="notifyBox" class="relative">
        <button
          class="btn-ghost relative px-2 text-[13px]"
          aria-haspopup="true"
          :aria-expanded="notifyOpen"
          aria-controls="notify-panel"
          :aria-label="`通知中心（${app.unreadCount} 条未读）`"
          title="通知中心"
          @click="toggleNotify"
        >
          🔔
          <span v-if="app.unreadCount > 0" class="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-pill bg-rose-500 px-1 text-[10px] font-medium text-white">
            {{ app.unreadCount > 99 ? '99+' : app.unreadCount }}
          </span>
        </button>
        <div v-if="notifyOpen" id="notify-panel" class="absolute right-0 top-10 z-50 w-[26rem] rounded-card border border-ink-100 bg-white shadow-pop">
          <div class="flex items-center justify-between gap-2 border-b border-ink-100 px-3 py-2">
            <span class="text-[13px] font-semibold">
              通知中心
              <span v-if="app.unreadCount" class="ml-1 rounded-pill bg-rose-50 px-1.5 text-[10px] text-rose-500">{{ app.unreadCount }} 未读</span>
            </span>
            <div class="flex items-center gap-1.5">
              <!-- #336 分类筛选下提供「该类全部已读」 -->
              <button v-if="notifyFilter.category" class="text-[11px] text-brand-600 hover:underline" @click="readCategory">该类全部已读</button>
              <button class="text-[11px] text-brand-600" @click="readAll">全部已读</button>
              <button class="text-[11px] text-ink-400" @click="clearRead">清空已读</button>
              <button
                class="rounded-pill px-1 text-[12px] text-ink-400 hover:bg-ink-50"
                :class="showNotifySettings ? 'text-brand-600' : ''"
                title="通知设置"
                aria-label="通知设置"
                @click="toggleNotifySettings"
              >⚙</button>
            </div>
          </div>

          <!-- #338/#339/#347/#340/#337 通知设置：静默预览、Webhook 自检、每日简报、桌面通知、稍后提醒状态 -->
          <div v-if="showNotifySettings" class="max-h-[26rem] space-y-2 overflow-y-auto border-b border-ink-50 p-3">
            <template v-if="notifySettings">
              <div class="flex items-center gap-2">
                <span class="tag" :class="notifySettings.currently_quiet ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'">
                  {{ notifySettings.currently_quiet ? '当前静默中' : '当前可打扰' }}
                </span>
                <span class="min-w-0 flex-1 truncate text-[11px] text-ink-500">{{ notifySettings.quiet_hint }}</span>
              </div>
              <div v-if="notifySettings.next_quiet_end" class="text-[11px] text-ink-400">
                {{ notifySettings.currently_quiet ? '下次可打扰：' : '本轮静默结束：' }}{{ fmtDateTime(notifySettings.next_quiet_end) }}
                <span v-if="!notifySettings.currently_quiet && notifySettings.next_quiet_start">
                  （{{ fmtDateTime(notifySettings.next_quiet_start) }} 开始）
                </span>
              </div>
              <div class="flex items-center gap-1">
                <input v-model="quietForm.start" type="time" class="input w-24 text-[12px]" aria-label="免打扰开始时间" />
                <span class="text-ink-300">–</span>
                <input v-model="quietForm.end" type="time" class="input w-24 text-[12px]" aria-label="免打扰结束时间" />
                <button class="btn-outline px-2 py-1 text-[11px]" @click="saveQuiet">保存免打扰</button>
              </div>
              <div class="flex items-center gap-1">
                <label class="flex items-center gap-1 text-[11px] text-ink-600">
                  <input v-model="dailyForm.enabled" type="checkbox" /> 每日简报
                </label>
                <input v-model="dailyForm.time" type="time" class="input w-24 text-[12px]" aria-label="每日简报时间" />
                <button class="btn-outline px-2 py-1 text-[11px]" @click="saveDaily">保存</button>
              </div>
              <div>
                <div class="mb-1 flex items-center justify-between text-[11px] text-ink-500">
                  <span>Webhook</span>
                  <button class="text-[11px] text-brand-600" @click="saveWebhook">保存地址</button>
                </div>
                <div class="flex items-center gap-1">
                  <input v-model="webhookForm.url" class="input min-w-0 flex-1 text-[12px]" placeholder="https://example.com/hook" />
                  <button class="btn-outline px-2 py-1 text-[11px]" :disabled="webhookTesting" @click="testWebhook">
                    {{ webhookTesting ? '测试中…' : '测试 Webhook' }}
                  </button>
                </div>
                <div v-if="webhookResult" class="mt-1 rounded-control bg-ink-50 p-2 text-[11px]">
                  <div :class="webhookResult.ok ? 'text-emerald-600' : 'text-rose-500'">
                    {{ webhookResult.ok ? '自检成功' : '自检失败' }}
                    · 状态 {{ webhookResult.status == null ? '-' : webhookResult.status }}
                    · {{ webhookResult.elapsed_ms || 0 }}ms
                  </div>
                  <div v-if="webhookResult.response" class="mt-0.5 max-h-16 overflow-y-auto break-all text-ink-500">{{ webhookResult.response }}</div>
                  <div v-else-if="webhookResult.error" class="mt-0.5 break-all text-rose-500">{{ webhookResult.error }}</div>
                </div>
              </div>
              <div class="flex items-center justify-between border-t border-ink-50 pt-2">
                <span class="text-[11px] text-ink-500">桌面通知：{{ permissionText }}</span>
                <button v-if="notifyPermission !== 'granted'" class="btn-outline px-2 py-1 text-[11px]" @click="requestNotifyPermission">开启</button>
              </div>
              <label class="flex items-center gap-1 text-[11px] text-ink-500">
                <input v-model="notifyFilter.includeSnoozed" type="checkbox" @change="loadNotifyList" />
                显示稍后提醒中（{{ snoozedHidden }} 条）
              </label>
            </template>
            <div v-else class="py-3 text-center text-[12px] text-ink-400">设置加载中…</div>
          </div>

          <template v-else>
            <!-- #335 分类页签 + 仅未读 -->
            <div class="border-b border-ink-50 px-2 py-1.5">
              <div class="flex flex-wrap gap-1">
                <button
                  v-for="c in NOTIFY_CATS"
                  :key="c.value || 'all'"
                  class="rounded-pill px-2 py-0.5 text-[11px] transition"
                  :class="notifyFilter.category === c.value ? 'bg-brand-500 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
                  @click="setCategory(c.value)"
                >{{ c.label }}</button>
              </div>
              <div class="mt-1.5 flex items-center justify-between">
                <label class="flex items-center gap-1 text-[11px] text-ink-500">
                  <input v-model="notifyFilter.unread" type="checkbox" @change="loadNotifyList" /> 仅未读
                </label>
                <span v-if="snoozedHidden" class="text-[11px] text-ink-400">稍后提醒中 {{ snoozedHidden }} 条</span>
              </div>
            </div>

            <!-- #334 分组未读小计，点击直接带分类过滤 -->
            <div v-if="unreadGroups.length" class="flex flex-wrap gap-1 border-b border-ink-50 px-2 py-1.5">
              <button
                v-for="g in unreadGroups"
                :key="g.category"
                class="rounded-pill border border-ink-100 px-2 py-0.5 text-[11px] text-ink-600 hover:border-brand-300 hover:text-brand-600"
                :class="notifyFilter.category === g.category ? 'border-brand-300 bg-brand-50' : ''"
                @click="setCategory(g.category)"
              >
                {{ g.label }} <b class="ml-0.5 text-ink-800">{{ g.count }}</b>
              </button>
            </div>

            <div class="max-h-80 overflow-y-auto">
              <div
                v-for="n in notifyItems"
                :key="n.id"
                class="cursor-pointer border-b border-ink-50 px-3 py-2 text-[12px] hover:bg-ink-50"
                :class="n.is_read ? 'text-ink-400' : 'bg-brand-50/40 text-ink-700'"
                @click="openNotify(n)"
              >
                <div class="flex items-center justify-between gap-2">
                  <span class="truncate font-medium">{{ n.title }}</span>
                  <span class="tag shrink-0">{{ categoryName(n.category) }}</span>
                </div>
                <div class="mt-0.5 line-clamp-2 whitespace-pre-line text-ink-500">{{ n.content }}</div>
                <div class="mt-1 flex items-center justify-between">
                  <span class="text-[10px] text-ink-300">{{ fmtDateTime(n.created_at) }}</span>
                  <span class="flex items-center gap-2">
                    <span v-if="n.snooze_until" class="text-[10px] text-amber-500">稍后提醒中</span>
                    <!-- #337 一角钟后再提醒；列表默认隐藏未到期项（服务端过滤） -->
                    <button class="text-[10px] text-ink-400 hover:text-brand-600" @click.stop="snoozeOne(n)">1 小时后提醒</button>
                    <button class="text-[10px] text-rose-400 hover:text-rose-600" @click.stop="deleteOne(n)">删除</button>
                  </span>
                </div>
              </div>
              <div v-if="notifyLoading" class="px-3 py-6 text-center text-[12px] text-ink-400">加载中…</div>
              <div v-else-if="!notifyItems.length" class="px-3 py-6 text-center text-[12px] text-ink-400">暂无通知</div>
            </div>
          </template>
        </div>
      </div>

      <div ref="menuBox" class="relative">
        <button
          class="flex items-center gap-2 rounded-pill py-1 pl-1 pr-2 hover:bg-ink-50"
          aria-haspopup="menu"
          :aria-expanded="menuOpen"
          aria-controls="user-menu"
          :aria-label="`${user.displayName} 的账号菜单`"
          @click="menuOpen = !menuOpen"
        >
          <img v-if="user.profile?.avatar" :src="user.profile.avatar" :alt="`${user.displayName} 的头像`" class="h-7 w-7 rounded-full object-cover" />
          <div v-else class="grid h-7 w-7 place-items-center rounded-full bg-brand-100 text-[12px] font-semibold text-brand-700" aria-hidden="true">
            {{ user.displayName.slice(0, 1) }}
          </div>
          <span class="text-[13px] font-medium text-ink-700">{{ user.displayName }}</span>
          <span class="text-[10px] text-ink-400" aria-hidden="true">▾</span>
        </button>
        <div v-if="menuOpen" id="user-menu" role="menu" class="absolute right-0 top-10 z-50 w-44 overflow-hidden rounded-card border border-ink-100 bg-white py-1 shadow-pop">
          <RouterLink to="/profile" class="block px-3 py-2 text-[13px] hover:bg-ink-50" @click="menuOpen = false">个人设置</RouterLink>
          <RouterLink to="/announcements" class="block px-3 py-2 text-[13px] hover:bg-ink-50" @click="menuOpen = false">系统公告</RouterLink>
          <button class="block w-full px-3 py-2 text-left text-[13px] text-rose-600 hover:bg-rose-50" @click="logout">退出登录</button>
        </div>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'
import { coreApi } from '../api'
import { notifyx } from '../api/notifyx'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const app = useAppStore()
const emit = defineEmits(['toggle-sidebar'])
const menuOpen = ref(false)
const notifyOpen = ref(false)
const notifyBox = ref(null)
const menuBox = ref(null)
const searching = ref(false)
const kw = ref('')
const results = ref({ files: [], notes: [], projects: [], tasks: [], total: 0 })
// #177 搜索结果键盘导航状态
const activeIndex = ref(-1)
const itemRefs = []
let timer = null

const CATS = { system: '系统', file: '文件', note: '笔记', project: '项目', message: '消息', share: '分享' }
const categoryName = (c) => CATS[c] || c
const NOTIFY_CATS = [
  { value: '', label: '全部' },
  { value: 'system', label: '系统' },
  { value: 'file', label: '文件' },
  { value: 'note', label: '笔记' },
  { value: 'project', label: '项目' },
  { value: 'message', label: '消息' },
  { value: 'share', label: '分享' },
]

// ---------------- #334-#341 通知下拉 ----------------
const notifyItems = ref([])
const notifyLoading = ref(false)
const unreadGroups = ref([])
const snoozedHidden = ref(0)
const notifyFilter = reactive({ category: '', unread: false, includeSnoozed: false })
const showNotifySettings = ref(false)
const notifySettings = ref(null)
const quietForm = reactive({ start: '', end: '' })
const dailyForm = reactive({ enabled: false, time: '18:00' })
const webhookForm = reactive({ url: '' })
const webhookResult = ref(null)
const webhookTesting = ref(false)
const notifyPermission = ref(typeof window !== 'undefined' && 'Notification' in window ? Notification.permission : 'unsupported')
const permissionText = computed(() => {
  if (notifyPermission.value === 'granted') return '已开启'
  if (notifyPermission.value === 'denied') return '已被浏览器拒绝'
  if (notifyPermission.value === 'unsupported') return '浏览器不支持'
  return '未开启'
})

async function loadNotifyList() {
  notifyLoading.value = true
  try {
    const r = await notifyx.list({
      page_size: 20,
      category: notifyFilter.category || undefined,
      unread: notifyFilter.unread ? 1 : undefined,
      include_snoozed: notifyFilter.includeSnoozed ? 1 : undefined,
    })
    notifyItems.value = r.list || []
    snoozedHidden.value = r.snoozed_hidden || 0
  } catch (e) {
    app.toastMsg(e.message || '通知加载失败', 'error')
  } finally {
    notifyLoading.value = false
  }
}

async function loadUnreadGroups() {
  try {
    const r = await notifyx.unread({ grouped: 1 })
    unreadGroups.value = (r.groups || []).filter((g) => g.count > 0)
  } catch (e) { /* 角标失败不阻塞下拉 */ }
}

function setCategory(category) {
  notifyFilter.category = notifyFilter.category === category ? '' : category
  loadNotifyList()
}

async function readCategory() {
  if (!notifyFilter.category) return
  try {
    const r = await notifyx.markRead({ category: notifyFilter.category })
    app.fetchUnread()
    app.fetchNotifications()
    loadUnreadGroups()
    loadNotifyList()
    app.toastMsg(r.message || '已标记该类已读')
  } catch (e) {
    app.toastMsg(e.message || '操作失败', 'error')
  }
}

async function snoozeOne(n) {
  try {
    const r = await notifyx.snooze([n.id], 60)
    notifyItems.value = notifyItems.value.filter((x) => x.id !== n.id)
    if (typeof r.unread === 'number') app.unreadCount = r.unread
    snoozedHidden.value += 1
    loadUnreadGroups()
    app.toastMsg('已设为 1 小时后提醒')
  } catch (e) {
    app.toastMsg(e.message || '稍后提醒失败', 'error')
  }
}

async function deleteOne(n) {
  try {
    await coreApi.deleteNotifications({ ids: [n.id] })
    notifyItems.value = notifyItems.value.filter((x) => x.id !== n.id)
    app.refreshNotificationsSoon(0)
    loadUnreadGroups()
  } catch (e) {
    app.toastMsg(e.message || '删除失败', 'error')
  }
}

function fmtDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return sameDay ? `${hh}:${mm}` : `${d.getMonth() + 1}-${d.getDate()} ${hh}:${mm}`
}

async function loadNotifySettings() {
  try {
    const r = await notifyx.settings()
    notifySettings.value = r
    quietForm.start = r.quiet_start || ''
    quietForm.end = r.quiet_end || ''
    dailyForm.enabled = !!r.daily_push_enabled
    dailyForm.time = r.daily_push_time || '18:00'
    webhookForm.url = r.webhook_url || ''
  } catch (e) {
    notifySettings.value = null
    app.toastMsg(e.message || '通知设置加载失败', 'error')
  }
}

function toggleNotifySettings() {
  showNotifySettings.value = !showNotifySettings.value
  if (showNotifySettings.value) loadNotifySettings()
}

async function saveQuiet() {
  try {
    const r = await notifyx.saveSettings({ quiet_start: quietForm.start || null, quiet_end: quietForm.end || null })
    notifySettings.value = { ...(notifySettings.value || {}), ...r }
    app.toastMsg('免打扰时段已保存')
  } catch (e) {
    app.toastMsg(e.message || '保存失败', 'error')
  }
}

async function saveDaily() {
  try {
    const r = await notifyx.saveSettings({
      daily_push_enabled: dailyForm.enabled,
      daily_push_time: dailyForm.time || null,
    })
    notifySettings.value = { ...(notifySettings.value || {}), ...r }
    app.toastMsg('每日简报设置已保存')
  } catch (e) {
    app.toastMsg(e.message || '保存失败', 'error')
  }
}

async function saveWebhook() {
  try {
    await notifyx.saveSettings({ webhook_url: webhookForm.url || '' })
    app.toastMsg('Webhook 地址已保存')
  } catch (e) {
    app.toastMsg(e.message || '保存失败', 'error')
  }
}

// #339 Webhook 自检：展示状态码、耗时与响应前 200 字
async function testWebhook() {
  webhookTesting.value = true
  webhookResult.value = null
  try {
    webhookResult.value = await notifyx.testWebhook(webhookForm.url || '')
  } catch (e) {
    const data = e.response?.data || {}
    webhookResult.value = {
      ok: false,
      status: data.status ?? null,
      elapsed_ms: data.elapsed_ms || 0,
      response: data.response || '',
      error: data.message || data.error || e.message || '自检失败',
    }
  } finally {
    webhookTesting.value = false
  }
}

// #340 桌面通知
async function requestNotifyPermission() {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    app.toastMsg('当前浏览器不支持桌面通知', 'error')
    return
  }
  try {
    const p = await Notification.requestPermission()
    notifyPermission.value = p
    app.toastMsg(p === 'granted' ? '已开启桌面通知' : '桌面通知未授权', p === 'granted' ? 'success' : 'error')
  } catch (e) {
    app.toastMsg('桌面通知授权失败', 'error')
  }
}

function showSystemNotification(n) {
  if (notifyPermission.value !== 'granted' || !document.hidden) return
  try {
    const notice = new Notification(n.title || '新通知', {
      body: n.content || '',
      tag: `notify-${n.id}`,
    })
    notice.onclick = () => {
      try { window.focus() } catch (e) { /* ignore */ }
      const link = n.link || ''
      if (link) {
        if (/^https?:\/\//i.test(link)) window.open(link, '_blank', 'noopener')
        else router.push(link)
      }
      notice.close()
    }
  } catch (e) { /* 部分环境禁止构造系统通知，忽略 */ }
}

// 监听全局 store 的通知刷新（WS notification 事件会触发 refreshNotificationsSoon），
// 页面隐藏时弹系统通知，点击回到页面并跳转 link。
const seenNotifyKeys = new Set()
// 合并通知（#333）会复用 id 并追加计数，签名带上 content 长度才能识别「同一 id 的新内容」
const notifyKey = (n) => `${n.id}:${n.title || ''}:${(n.content || '').length}`
let notifySeeded = false
watch(
  () => app.notifications,
  (list) => {
    if (!Array.isArray(list) || !list.length) return
    if (!notifySeeded) {
      list.forEach((n) => seenNotifyKeys.add(notifyKey(n)))
      notifySeeded = true
      return
    }
    for (const n of list) {
      const key = notifyKey(n)
      if (seenNotifyKeys.has(key)) continue
      seenNotifyKeys.add(key)
      if (!n.is_read) showSystemNotification(n)
    }
  },
  { deep: true }
)

// #341 未读角标：favicon 与 document.title 前缀
let originalIconHref = null
let originalIconType = null
function iconLink() {
  let link = document.querySelector('link[rel="icon"]')
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  if (originalIconHref === null) originalIconHref = link.getAttribute('href') || ''
  if (originalIconType === null) originalIconType = link.getAttribute('type') || ''
  return link
}

function faviconDataUrl(count) {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 64
    canvas.height = 64
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.fillStyle = '#e11d48'
    ctx.beginPath()
    ctx.arc(32, 32, 30, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = '#ffffff'
    ctx.font = `bold ${count > 9 ? 26 : 34}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(count > 99 ? '99+' : String(count), 32, 34)
    return canvas.toDataURL('image/png')
  } catch (e) {
    return ''
  }
}

function applyUnreadBadge() {
  if (typeof document === 'undefined') return
  const count = app.unreadCount || 0
  const base = document.title.replace(/^\(\d+\+?\)\s*/, '')
  document.title = count > 0 ? `(${count > 99 ? '99+' : count}) ${base}` : base
  const link = iconLink()
  if (count > 0) {
    const href = faviconDataUrl(count)
    if (href) {
      link.setAttribute('type', 'image/png')
      link.href = href
    }
  } else if (originalIconHref) {
    if (originalIconType) link.setAttribute('type', originalIconType)
    else link.removeAttribute('type')
    link.href = originalIconHref
  }
}

watch(() => app.unreadCount, applyUnreadBadge, { immediate: true })
// 路由切换会重写 document.title，稍后再补前缀，避免覆盖页面标题
watch(() => route.fullPath, () => setTimeout(applyUnreadBadge, 0))

// #177 把分组结果拍平，键盘按拍平后的下标移动；idx 同时用于高亮与 ref
const resultGroups = computed(() => {
  const r = results.value
  const groups = []
  if (r.files?.length) groups.push({ title: '文件', items: r.files.map((f) => ({ to: '/files?q=' + encodeURIComponent(f.name), label: `📄 ${f.name}` })) })
  if (r.notes?.length) groups.push({ title: '笔记', items: r.notes.map((n) => ({ to: '/search?q=' + encodeURIComponent(n.title), label: `📝 ${n.title}` })) })
  if (r.projects?.length) groups.push({ title: '项目', items: r.projects.map((p) => ({ to: `/projects/${p.id}/board`, label: `📋 ${p.name}` })) })
  if (r.tasks?.length) groups.push({ title: '任务', items: r.tasks.map((t) => ({ to: `/projects/${t.project_id}/board`, label: `✅ ${t.title}` })) })
  let i = 0
  return groups.map((g) => ({ title: g.title, items: g.items.map((it) => ({ ...it, idx: i++ })) }))
})
const flatItems = computed(() => resultGroups.value.flatMap((g) => g.items))

function setItemRef(el, i) {
  // RouterLink 是组件，取 $el 才是真实 DOM 节点
  itemRefs[i] = el?.$el || el || null
}
function closeSearch() {
  searching.value = false
  activeIndex.value = -1
}
function moveActive(step) {
  const n = flatItems.value.length
  if (!n) return
  if (activeIndex.value < 0) activeIndex.value = step > 0 ? 0 : n - 1
  else activeIndex.value = (activeIndex.value + step + n) % n
  nextTick(() => itemRefs[activeIndex.value]?.scrollIntoView?.({ block: 'nearest' }))
}
function onSearchKeydown(e) {
  if (e.key === 'Escape') {
    if (searching.value) {
      e.preventDefault()
      closeSearch()
    }
    return
  }
  if (!searching.value || !kw.value) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveActive(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveActive(-1)
  } else if (e.key === 'Enter') {
    const it = flatItems.value[activeIndex.value]
    if (!it) return
    e.preventDefault()
    router.push(it.to)
    closeSearch()
  }
}

function onInput() {
  activeIndex.value = -1
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
    activeIndex.value = -1
  } catch (e) { /* ignore */ }
}
function hideLater() {
  setTimeout(() => (searching.value = false), 200)
}
function toggleNotify() {
  notifyOpen.value = !notifyOpen.value
  if (notifyOpen.value) {
    showNotifySettings.value = false
    loadNotifyList()
    loadUnreadGroups()
    app.refreshNotificationsSoon(0)
  }
}
async function readAll() {
  await app.markAllRead()
  loadUnreadGroups()
  loadNotifyList()
}
// F23：通知可点击——未读先标已读，再按 link 跳转（站内路径 push，http(s) 外链新开页）
async function openNotify(n) {
  if (!n.is_read) {
    await app.markOneRead(n)
    n.is_read = true
    loadUnreadGroups()
  }
  const link = n.link || ''
  if (!link) return
  if (/^https?:\/\//i.test(link)) window.open(link, '_blank', 'noopener')
  else router.push(link)
}
async function clearRead() {
  await coreApi.deleteNotifications({ scope: 'read' })
  app.refreshNotificationsSoon(0)
  loadNotifyList()
  loadUnreadGroups()
}
async function logout() {
  await user.logout()
  router.push('/login')
}

// #178 通知与用户菜单：外部点击（捕获阶段）与 Esc 都要关闭，卸载时移除监听
function onDocClick(e) {
  if (notifyOpen.value && notifyBox.value && !notifyBox.value.contains(e.target)) notifyOpen.value = false
  if (menuOpen.value && menuBox.value && !menuBox.value.contains(e.target)) menuOpen.value = false
}
function onDocKeydown(e) {
  if (e.key !== 'Escape') return
  if (notifyOpen.value) notifyOpen.value = false
  if (menuOpen.value) menuOpen.value = false
  if (searching.value) closeSearch()
}
onMounted(() => {
  document.addEventListener('click', onDocClick, true)
  document.addEventListener('keydown', onDocKeydown)
  // #340 首次进入尝试申请桌面通知权限（被拒绝则仅在设置面板提示）
  if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().then((p) => (notifyPermission.value = p)).catch(() => {})
  }
})
// F23：搜索防抖 timer 与全局监听在卸载时清理，避免组件销毁后回调再触发
onBeforeUnmount(() => {
  clearTimeout(timer)
  document.removeEventListener('click', onDocClick, true)
  document.removeEventListener('keydown', onDocKeydown)
})
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
/* #177 键盘高亮项，与 hover 视觉一致 */
.search-item-active {
  background: #e2e8f0;
}
</style>
