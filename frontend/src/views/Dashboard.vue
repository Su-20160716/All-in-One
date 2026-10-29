<template>
  <div class="mx-auto max-w-6xl space-y-5">
    <!-- F665 首页公告横幅：未读置顶公告 -->
    <div v-if="banner" class="card flex items-start gap-3 border-l-4 border-amber-400 bg-amber-50/70 p-4">
      <span class="mt-0.5 text-[18px]">📢</span>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag bg-amber-100 text-amber-700">{{ banner.level || '公告' }}</span>
          <RouterLink to="/announcements" class="truncate text-[14px] font-semibold text-ink-800 hover:text-brand-600">
            {{ banner.title }}
          </RouterLink>
          <span v-if="!banner.is_read" class="tag bg-rose-100 text-rose-600">未读</span>
        </div>
        <p class="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink-500">{{ banner.content }}</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <button class="btn-outline px-2 py-1 text-[12px]" @click="dismissBanner">知道了</button>
        <button class="text-ink-300 hover:text-ink-500" @click="banner = null">×</button>
      </div>
    </div>

    <div class="card flex items-center justify-between p-5">
      <div>
        <h2 class="text-[18px] font-bold text-ink-900">你好，{{ user.displayName }} 👋</h2>
        <p class="mt-1 text-[13px] text-ink-500">{{ today }}，今天也高效工作吧。</p>
      </div>
      <div class="flex gap-2">
        <RouterLink to="/projects/my-tasks" class="btn-outline">我的任务</RouterLink>
        <RouterLink to="/files" class="btn-primary">上传文件</RouterLink>
        <RouterLink to="/notes" class="btn-outline">写笔记</RouterLink>
      </div>
    </div>

    <!-- #97 可编辑快捷入口 + F664 emoji 图标选择 -->
    <div class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <span class="text-[13px] font-medium text-ink-700">快捷入口</span>
        <button class="text-[12px] text-brand-600" @click="editingQuick = !editingQuick">
          {{ editingQuick ? '完成' : '编辑' }}
        </button>
      </div>
      <div class="flex flex-wrap gap-2">
        <div v-for="(q, qi) in quickLinks" :key="q.url" class="group flex items-center">
          <!-- F25：http(s) 开头按外链处理，用原生 a + 新窗口；内部路径才走 RouterLink -->
          <component
            :is="isExternalUrl(q.url) ? 'a' : RouterLink"
            v-bind="isExternalUrl(q.url)
              ? { href: q.url, target: '_blank', rel: 'noopener noreferrer' }
              : { to: q.url }"
            class="btn-outline text-[12px]"
          >
            <span v-if="pickingFor !== qi" class="cursor-pointer" @click.prevent.stop="openEmojiPicker(qi)">
              {{ q.icon || '🔗' }}
            </span>
            <select v-else class="mr-1 max-w-[64px] cursor-pointer border-0 bg-transparent text-[12px] outline-none"
                    :value="q.icon" @change="setIcon(qi, $event.target.value)">
              <option v-for="e in EMOJIS" :key="e" :value="e">{{ e }}</option>
            </select>
            {{ q.label }}
          </component>
          <button v-if="editingQuick" class="ml-1 text-rose-400" @click="removeQuick(q)">×</button>
        </div>
        <div v-if="editingQuick" class="flex items-center gap-1">
          <button class="btn-outline px-2 text-[12px]" title="选择图标" @click="openEmojiPicker('new')">
            {{ newQuick.icon || '图标' }}
          </button>
          <select v-if="pickingFor === 'new'" class="input w-16 text-[12px]"
                  :value="newQuick.icon" @change="setIcon('new', $event.target.value)">
            <option v-for="e in EMOJIS" :key="e" :value="e">{{ e }}</option>
          </select>
          <input v-model="newQuick.label" class="input w-20 text-[12px]" placeholder="名称" />
          <input v-model="newQuick.url" class="input w-28 text-[12px]" placeholder="路径或网址" />
          <button class="btn-primary text-[12px]" @click="addQuick">添加</button>
        </div>
      </div>
      <!-- F664 emoji 调色板 -->
      <div v-if="pickingFor !== null" class="mt-2 flex flex-wrap gap-1 rounded-control bg-ink-50 p-2">
        <button v-for="e in EMOJIS" :key="e"
                class="h-7 w-7 rounded-control text-[15px] hover:bg-white hover:shadow-pop"
                @click="setIcon(pickingFor, e)">{{ e }}</button>
        <button class="ml-1 text-[12px] text-ink-400 hover:text-rose-500" @click="pickingFor = null">收起</button>
      </div>
    </div>

    <!-- 今日卡片：F657 今日到期 / F658 今日学习 / F659 今日日程（F667 手动刷新 + 时间戳） -->
    <div class="grid gap-3 lg:grid-cols-3">
      <!-- F657 今日到期聚合卡 -->
      <div class="card p-4">
        <div class="flex items-center justify-between">
          <span class="text-[13px] font-medium text-ink-700">📅 今日到期</span>
          <span class="flex items-center gap-1 text-[11px] text-ink-300">
            <span v-if="stamps.due">更新于 {{ stamps.due }}</span>
            <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadDue">↻</button>
          </span>
        </div>
        <div class="mt-1 flex items-end gap-2">
          <div class="text-[24px] font-bold text-amber-500">{{ due?.total ?? 0 }}</div>
          <div class="mb-1 text-[11px] text-ink-400">今日到期 · 逾期 {{ due?.overdue_total ?? 0 }}</div>
        </div>
        <div class="mt-2 space-y-1.5">
          <div v-for="g in (due?.groups || [])" :key="g.key"
               class="flex items-center gap-2 rounded-control px-2 py-1 hover:bg-ink-50">
            <RouterLink :to="g.link || '/dashboard'" class="min-w-0 flex-1">
              <span class="text-[12px] text-ink-600">{{ g.label }}</span>
              <span v-if="g.error" class="ml-1 text-[11px] text-ink-300">该模块暂不可用</span>
            </RouterLink>
            <span class="shrink-0 text-[13px] font-semibold"
                  :class="g.count ? 'text-ink-900' : 'text-ink-300'">{{ g.count }}</span>
          </div>
          <div v-if="due?.errors?.length" class="text-[11px] text-rose-400">
            部分模块取数失败，已跳过 {{ due.errors.length }} 个
          </div>
        </div>
        <div v-if="dueItems.length" class="mt-2 space-y-0.5 border-t border-ink-50 pt-2">
          <div v-for="it in dueItems" :key="it.key" class="truncate text-[11px] text-ink-400">
            · {{ it.title }}
          </div>
        </div>
      </div>

      <!-- F658 今日学习卡 -->
      <div class="card p-4">
        <div class="flex items-center justify-between">
          <span class="text-[13px] font-medium text-ink-700">📚 今日学习</span>
          <span class="flex items-center gap-1 text-[11px] text-ink-300">
            <span v-if="stamps.learning">更新于 {{ stamps.learning }}</span>
            <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadLearning">↻</button>
          </span>
        </div>
        <template v-if="!learning?.error">
          <div class="mt-1 flex items-end gap-2">
            <div class="text-[24px] font-bold text-brand-600">{{ learning?.minutes ?? 0 }}</div>
            <div class="mb-1 text-[11px] text-ink-400">/ {{ learning?.goal_minutes ?? 60 }} 分钟目标</div>
          </div>
          <div class="mt-2 h-2 overflow-hidden rounded-pill bg-ink-100">
            <div class="h-full rounded-pill bg-brand-500 transition-all"
                 :style="{ width: Math.min(100, learning?.percent || 0) + '%' }"></div>
          </div>
          <div class="mt-2 flex items-center justify-between text-[12px] text-ink-500">
            <span>🔥 连续 <b class="text-ink-800">{{ learning?.streak ?? 0 }}</b> 天</span>
            <span>今日 {{ learning?.sessions ?? 0 }} 次记录</span>
            <span :class="learning?.reached ? 'text-emerald-600' : 'text-amber-500'">
              {{ learning?.reached ? '已达目标' : '还差 ' + Math.max(0, (learning?.goal_minutes || 0) - (learning?.minutes || 0)) + ' 分钟' }}
            </span>
          </div>
          <div v-if="learning?.subjects?.length" class="mt-1 truncate text-[11px] text-ink-400">
            科目：{{ learning.subjects.join('、') }}
          </div>
        </template>
        <div v-else class="mt-3 text-[12px] text-ink-400">学习数据暂不可用（learning 模块未响应）</div>
      </div>

      <!-- F659 今日日程卡 -->
      <div class="card p-4">
        <div class="flex items-center justify-between">
          <span class="text-[13px] font-medium text-ink-700">🗓️ 今日日程</span>
          <span class="flex items-center gap-1 text-[11px] text-ink-300">
            <span v-if="stamps.schedule">更新于 {{ stamps.schedule }}</span>
            <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadSchedule">↻</button>
          </span>
        </div>
        <div class="mt-2 space-y-1">
          <div v-for="m in scheduleMeetings" :key="'m' + m.id"
               class="flex items-center gap-2 rounded-control px-2 py-1"
               :class="m.mine ? 'bg-brand-50' : 'hover:bg-ink-50'">
            <span class="shrink-0 text-[11px] text-ink-400">{{ fmtClock(m.start_at) }}</span>
            <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ m.title }}</span>
            <span v-if="m.mine" class="shrink-0 text-[10px] text-brand-600">我的</span>
          </div>
          <div v-for="d in scheduleDuty" :key="'d' + d.id"
               class="flex items-center gap-2 rounded-control px-2 py-1"
               :class="d.mine ? 'bg-emerald-50' : 'hover:bg-ink-50'">
            <span class="shrink-0 text-[11px] text-ink-400">值班</span>
            <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ d.member }} · {{ d.shift }}</span>
            <span v-if="d.mine" class="shrink-0 text-[10px] text-emerald-600">我</span>
          </div>
          <div v-if="!scheduleMeetings.length && !scheduleDuty.length"
               class="py-3 text-center text-[12px] text-ink-400">
            {{ scheduleError ? '日程数据暂不可用' : '今天没有会议与值班' }}
          </div>
        </div>
      </div>
    </div>

    <!-- 待办聚合 -->
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <RouterLink to="/projects/my-tasks" class="card p-4 hover:shadow-pop">
        <div class="text-[12px] text-ink-500">已逾期</div>
        <div class="mt-1 text-[24px] font-bold text-rose-500">{{ todo.overdue ?? 0 }}</div>
      </RouterLink>
      <RouterLink to="/projects/my-tasks" class="card p-4 hover:shadow-pop">
        <div class="text-[12px] text-ink-500">今日到期</div>
        <div class="mt-1 text-[24px] font-bold text-amber-500">{{ todo.today ?? 0 }}</div>
      </RouterLink>
      <RouterLink to="/im" class="card p-4 hover:shadow-pop">
        <div class="text-[12px] text-ink-500">未读消息</div>
        <div class="mt-1 text-[24px] font-bold text-brand-600">{{ todo.unread_messages ?? 0 }}</div>
      </RouterLink>
      <div class="card p-4">
        <div class="text-[12px] text-ink-500">本周到期</div>
        <div class="mt-1 text-[24px] font-bold text-ink-900">{{ todo.week ?? 0 }}</div>
      </div>
    </div>

    <!-- #53 可拖拽排序的统计卡片（F668 顺序同步到服务端） -->
    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4" ref="statGrid">
      <div v-for="s in orderedStatCards" :key="s.label" class="card p-4 cursor-move"
           draggable="true" @dragstart="onDragStart($event, s.label)" @dragover.prevent @drop="onDrop($event, s.label)">
        <div class="text-[12px] text-ink-500">{{ s.label }}</div>
        <div class="mt-1 text-[24px] font-bold text-ink-900">{{ s.value }}</div>
        <div class="mt-0.5 text-[11px] text-ink-400">{{ s.note }}</div>
      </div>
    </div>

    <!-- F660 存储用量卡：总量 + 类型占比迷你条 -->
    <div class="card p-5">
      <div class="mb-2 flex items-center justify-between">
        <span class="text-[13px] font-medium text-ink-700">存储空间</span>
        <span class="flex items-center gap-2 text-[12px] text-ink-500">
          <span>{{ storage.total_text || formatSize(stats.storage_bytes) }} / {{ storage.quota_text || stats.quota_mb + ' MB' }}</span>
          <span v-if="stamps.storage" class="text-[11px] text-ink-300">更新于 {{ stamps.storage }}</span>
          <button class="rounded-pill px-1 text-[12px] hover:bg-ink-50" title="刷新" @click="loadStorage">↻</button>
        </span>
      </div>
      <div class="h-2.5 overflow-hidden rounded-pill bg-ink-100">
        <div class="h-full rounded-pill bg-brand-500" :style="{ width: Math.min(100, storage.percent || stats.quota_used_pct || 0) + '%' }"></div>
      </div>
      <div v-if="storage.by_kind?.length" class="mt-3">
        <!-- 迷你占比条（手写 flex 分段，不引图表库） -->
        <div class="flex h-2 overflow-hidden rounded-pill bg-ink-100">
          <div v-for="(k, i) in storage.by_kind" :key="k.kind"
               :title="`${k.kind}: ${k.text} (${k.percent}%)`"
               :style="{ width: k.percent + '%', background: PALETTE[i % PALETTE.length] }"></div>
        </div>
        <div class="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-500">
          <span v-for="(k, i) in storage.by_kind" :key="'lg' + k.kind" class="inline-flex items-center gap-1">
            <span class="inline-block h-2 w-2 rounded-pill" :style="{ background: PALETTE[i % PALETTE.length] }"></span>
            {{ k.kind }} · {{ k.count }} 个 · {{ k.text }} · {{ k.percent }}%
          </span>
        </div>
      </div>
      <div v-else class="mt-2 text-[11px] text-ink-400">
        {{ storage.error ? '存储统计暂不可用' : '暂无文件类型分布' }}
      </div>
    </div>

    <!-- F666 最近动态时间线（跨模块最新 10 条） -->
    <div class="card p-5">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">最近动态</h3>
        <span class="flex items-center gap-2 text-[11px] text-ink-300">
          <span v-if="stamps.activity">更新于 {{ stamps.activity }}</span>
          <button class="rounded-pill px-1 hover:bg-ink-50" title="刷新" @click="loadActivity">↻</button>
        </span>
      </div>
      <div v-if="activity.length" class="relative space-y-3 pl-4">
        <div class="absolute bottom-1 left-[3px] top-1 w-px bg-ink-100"></div>
        <button v-for="(a, i) in activity" :key="i"
                class="relative flex w-full items-start gap-2 text-left hover:bg-ink-50/60"
                @click="router.push(a.link || '/dashboard')">
          <span class="absolute -left-4 top-1.5 h-2 w-2 rounded-full"
                :class="i === 0 ? 'bg-brand-500' : 'bg-ink-200'"></span>
          <span class="tag shrink-0">{{ a.label }}</span>
          <span class="min-w-0 flex-1 truncate text-[12px] text-ink-700">{{ a.title }}</span>
          <span class="shrink-0 text-[11px] text-ink-300">{{ a.at_text }}</span>
        </button>
      </div>
      <div v-else class="py-6 text-center text-[12px] text-ink-400">
        {{ activityError ? '动态聚合暂不可用' : '暂无最近动态' }}
      </div>
    </div>

    <!-- #94 性能监控面板 -->
    <div class="card p-5" v-if="latencyStats.samples">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">接口延迟监控</h3>
        <button class="text-[12px] text-ink-400" @click="clearLatency">清空数据</button>
      </div>
      <div class="grid grid-cols-3 gap-3">
        <div class="rounded-control bg-ink-50 p-3 text-center">
          <div class="text-[11px] text-ink-500">P50</div>
          <div class="text-[20px] font-bold text-ink-900">{{ latencyStats.p50 }}ms</div>
        </div>
        <div class="rounded-control bg-ink-50 p-3 text-center">
          <div class="text-[11px] text-ink-500">P95</div>
          <div class="text-[20px] font-bold text-amber-500">{{ latencyStats.p95 }}ms</div>
        </div>
        <div class="rounded-control bg-ink-50 p-3 text-center">
          <div class="text-[11px] text-ink-500">P99</div>
          <div class="text-[20px] font-bold text-rose-500">{{ latencyStats.p99 }}ms</div>
        </div>
      </div>
    </div>

    <!-- 14 天产出趋势 -->
    <div class="card p-5" v-if="trend.labels">
      <h3 class="mb-3 text-[14px] font-semibold">近 14 天产出</h3>
      <div class="flex h-32 items-end gap-1">
        <div v-for="(lb, i) in trend.labels" :key="i" class="group flex flex-1 flex-col items-center justify-end gap-0.5">
          <div class="flex w-full items-end justify-center gap-px" :title="`${lb} 笔记${trend.notes[i]} 文件${trend.files[i]} 完成${trend.tasks_done[i]}`">
            <div class="w-1/3 rounded-t bg-brand-400" :style="{ height: barH(trend.notes[i]) }"></div>
            <div class="w-1/3 rounded-t bg-emerald-400" :style="{ height: barH(trend.files[i]) }"></div>
            <div class="w-1/3 rounded-t bg-amber-400" :style="{ height: barH(trend.tasks_done[i]) }"></div>
          </div>
          <span class="text-[9px] text-ink-300">{{ lb }}</span>
        </div>
      </div>
      <div class="mt-2 flex gap-3 text-[11px] text-ink-400">
        <span>■ 笔记</span><span class="text-emerald-400">■ 文件</span><span class="text-amber-400">■ 完成任务</span>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <div class="card p-5">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-[14px] font-semibold">最近编辑的笔记</h3>
          <RouterLink to="/notes" class="text-[12px] text-brand-600">全部</RouterLink>
        </div>
        <div v-if="recentNotes.length" class="space-y-2">
          <RouterLink v-for="n in recentNotes" :key="n.id" to="/notes" class="flex items-center justify-between rounded-control px-2 py-1.5 hover:bg-ink-50">
            <span class="truncate text-[13px]">{{ n.title }}</span>
            <span class="shrink-0 text-[11px] text-ink-400">{{ formatTime(n.updated_at) }}</span>
          </RouterLink>
        </div>
        <div v-else class="py-6 text-center text-[12px] text-ink-400">还没有笔记</div>
      </div>

      <div class="card p-5">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-[14px] font-semibold">最新通知</h3>
          <button class="text-[12px] text-brand-600" @click="app.markAllRead">全部已读</button>
        </div>
        <div v-if="app.notifications.length" class="space-y-2">
          <div v-for="n in app.notifications.slice(0, 6)" :key="n.id" class="flex items-start gap-2 rounded-control px-2 py-1.5 hover:bg-ink-50">
            <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" :class="n.is_read ? 'bg-ink-200' : 'bg-brand-500'"></span>
            <div class="min-w-0">
              <div class="truncate text-[13px]">{{ n.title }}</div>
              <div class="text-[11px] text-ink-400">{{ n.content }}</div>
            </div>
            <span class="ml-auto shrink-0 text-[10px] text-ink-300">{{ formatTime(n.created_at) }}</span>
          </div>
        </div>
        <div v-else class="py-6 text-center text-[12px] text-ink-400">暂无通知</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'
import { coreApi, dashApi, noteApi } from '../api'
import { dashx } from '../api/dashx'
import { formatSize, formatTime } from '../utils/format'

// localStorage 可能存着损坏的 JSON（手工改过/写入中断），解析失败时清掉回落默认值，
// 否则首页会在 setup 阶段直接抛错变成白屏
function loadJson(key, fallback = null) {
  const raw = localStorage.getItem(key)
  if (!raw) return fallback
  try {
    return JSON.parse(raw)
  } catch {
    localStorage.removeItem(key)
    return fallback
  }
}

const router = useRouter()
const user = useUserStore()
const app = useAppStore()
const stats = ref({})
const todo = ref({})
const trend = ref({})
const recentNotes = ref([])
const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })

// ---------------- F665 首页公告横幅 ----------------
const banner = ref(null)
async function loadBanner() {
  try {
    const r = await coreApi.announcements()
    const list = r.list || []
    banner.value = list.find((a) => a.is_pinned && !a.is_read) || list.find((a) => a.is_pinned) || null
  } catch (e) { banner.value = null }
}
async function dismissBanner() {
  const b = banner.value
  banner.value = null
  if (b && !b.is_read) {
    try { await coreApi.readAnnouncement(b.id) } catch (e) { /* ignore */ }
  }
}

// ---------------- F657–F659 / F660 / F666 今日卡片与动态 ----------------
const due = ref(null)
const learning = ref(null)
const schedule = ref(null)
const storage = ref({})
const activity = ref([])
const activityError = ref(false)
const scheduleError = ref(false)
// F667 卡片数据更新时间戳
const stamps = reactive({ due: '', learning: '', schedule: '', storage: '', activity: '' })

function stampOf(iso) {
  if (!iso) return new Date().toLocaleTimeString('zh-CN', { hour12: false })
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('zh-CN', { hour12: false })
}

async function loadDue() {
  try {
    const r = await dashx.todayDue()
    due.value = r
    stamps.due = stampOf(r.fetched_at)
  } catch (e) { due.value = due.value || { total: 0, groups: [], errors: [{ module: 'all' }] } }
}
async function loadLearning() {
  try {
    const r = await dashx.todayLearning()
    learning.value = r
    stamps.learning = stampOf(r.fetched_at)
  } catch (e) {
    learning.value = { error: 'unavailable', minutes: 0, streak: 0, goal_minutes: 60, percent: 0 }
  }
}
async function loadSchedule() {
  try {
    const r = await dashx.todaySchedule()
    schedule.value = r
    scheduleError.value = !!(r.errors && r.errors.length)
    stamps.schedule = stampOf(r.fetched_at)
  } catch (e) {
    scheduleError.value = true
    schedule.value = { meetings: { items: [] }, duty: { items: [] } }
  }
}
async function loadStorage() {
  try {
    const r = await dashx.storageUsage()
    storage.value = r
    stamps.storage = stampOf(r.fetched_at)
  } catch (e) { storage.value = { error: 'unavailable', by_kind: [] } }
}
async function loadActivity() {
  try {
    const r = await dashx.recentActivity()
    activity.value = r.list || []
    activityError.value = !!(r.errors && r.errors.length)
    stamps.activity = stampOf(r.fetched_at)
  } catch (e) {
    activityError.value = true
    activity.value = []
  }
}

const dueItems = computed(() => {
  const out = []
  for (const g of due.value?.groups || []) {
    for (const it of (g.items || []).slice(0, 2)) {
      out.push({ key: `${g.key}-${it.id}`, title: it.title })
    }
  }
  return out.slice(0, 4)
})
const scheduleMeetings = computed(() => (schedule.value?.meetings?.items || []).slice(0, 3))
const scheduleDuty = computed(() => (schedule.value?.duty?.items || []).slice(0, 2))
const PALETTE = ['#6366f1', '#10b981', '#f59e0b', '#f43f5e', '#0ea5e9', '#8b5cf6', '#14b8a6', '#94a3b8']

function fmtClock(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// #53 拖拽排序（F668：同步服务端，跨浏览器一致）
let dragLabel = null
const cardOrder = ref(loadJson('dashboard_card_order'))
async function loadCardOrder() {
  try {
    const r = await dashx.cardOrder()
    if (r.order && r.order.length) {
      cardOrder.value = r.order
      localStorage.setItem('dashboard_card_order', JSON.stringify(r.order))
    }
  } catch (e) { /* 服务端不可用时沿用本地顺序 */ }
}

const statCards = computed(() => [
  { label: '我的文件', value: stats.value.files ?? '-', note: `${formatSize(stats.value.storage_bytes || 0)} 已用` },
  { label: '我的笔记', value: stats.value.notes ?? '-', note: `${stats.value.folders ?? 0} 个文件夹` },
  { label: '参与项目', value: stats.value.projects ?? '-', note: `${stats.value.my_tasks ?? 0} 个进行中任务` },
  { label: '收藏文件', value: todo.value.starred_files ?? '-', note: `置顶笔记 ${todo.value.pinned_notes ?? 0}` },
])
const orderedStatCards = computed(() => {
  if (!cardOrder.value) return statCards.value
  return [...statCards.value].sort((a, b) => {
    const ia = cardOrder.value.indexOf(a.label)
    const ib = cardOrder.value.indexOf(b.label)
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib)
  })
})
function onDragStart(e, label) { dragLabel = label }
function onDrop(e, targetLabel) {
  if (!dragLabel || dragLabel === targetLabel) return
  const order = statCards.value.map(c => c.label)
  const from = order.indexOf(dragLabel)
  const to = order.indexOf(targetLabel)
  order.splice(to, 0, order.splice(from, 1)[0])
  cardOrder.value = order
  localStorage.setItem('dashboard_card_order', JSON.stringify(order))
  // F668：同步到服务端，换浏览器登录后顺序一致（失败静默，本地已保存）
  dashx.saveCardOrder(order).catch(() => {})
}

// #97 快捷入口 + F664 emoji 图标选择
const editingQuick = ref(false)
const newQuick = reactive({ label: '', url: '', icon: '🔗' })
const defaultQuicks = [
  { icon: '📁', label: '文件', url: '/files' },
  { icon: '📝', label: '笔记', url: '/notes' },
  { icon: '📋', label: '项目', url: '/projects' },
  { icon: '💬', label: '消息', url: '/im' },
  { icon: '🔍', label: '搜索', url: '/search' },
]
const quickLinks = ref(loadJson('quick_links') || defaultQuicks)
// F25：快捷入口允许填外链。RouterLink 会把 "https://x" 当成站内路径拼到 #/ 后面，必须分流。
const isExternalUrl = (url) => /^https?:\/\//i.test(String(url || '').trim())
function normalizeQuickUrl(raw) {
  const u = String(raw || '').trim()
  if (!u) return ''
  if (/^https?:\/\//i.test(u)) return u
  if (u.startsWith('/')) return u
  // 形如 www.example.com / example.com 的裸域名补 https，其余按站内路径处理
  if (/^[\w-]+(\.[\w-]+)+([/?#].*)?$/.test(u)) return 'https://' + u
  return '/' + u
}
const EMOJIS = ['📁', '📝', '📋', '💬', '🔍', '🏠', '📊', '🗓️', '✉️', '🧮',
                '🌐', '✨', '🧹', '📚', '🎵', '🎨', '📅', '✅', '❤️', '⭐',
                '🔥', '💡', '🚀', '📌', '📈', '📉', '🗂️', '🗃️', '🕒', '🎯']
const pickingFor = ref(null)
function openEmojiPicker(target) {
  if (!editingQuick.value && target !== 'new') editingQuick.value = true
  pickingFor.value = pickingFor.value === target ? null : target
}
function setIcon(target, emoji) {
  if (target === 'new') newQuick.icon = emoji
  else if (quickLinks.value[target]) quickLinks.value[target].icon = emoji
  pickingFor.value = null
  saveQuick()
}
function saveQuick() { localStorage.setItem('quick_links', JSON.stringify(quickLinks.value)) }
function addQuick() {
  if (!newQuick.label || !newQuick.url) return
  const url = normalizeQuickUrl(newQuick.url)
  if (!url) return
  quickLinks.value.push({ icon: newQuick.icon || '🔗', label: newQuick.label, url })
  newQuick.label = ''; newQuick.url = ''; newQuick.icon = '🔗'
  saveQuick()
}
function removeQuick(q) {
  quickLinks.value = quickLinks.value.filter(x => x !== q)
  saveQuick()
}

// #94 性能监控
const latencyStats = ref({ samples: 0, p50: 0, p95: 0, p99: 0 })
function computeLatency() {
  try {
    const samples = JSON.parse(localStorage.getItem('api_latency_samples') || '[]')
    if (!samples.length) return
    const durations = samples.map(s => s.duration).sort((a, b) => a - b)
    const p = (pct) => durations[Math.floor(durations.length * pct) - 1] || 0
    latencyStats.value = { samples: samples.length, p50: p(0.5), p95: p(0.95), p99: p(0.99) }
  } catch (e) { /* ignore */ }
}
function clearLatency() {
  localStorage.removeItem('api_latency_samples')
  latencyStats.value = { samples: 0, p50: 0, p95: 0, p99: 0 }
}

const trendMax = computed(() => Math.max(1, ...(trend.value.notes || []), ...(trend.value.files || []), ...(trend.value.tasks_done || [])))
function barH(v) {
  return Math.max(2, Math.round((v / trendMax.value) * 100)) + 'px'
}

onMounted(async () => {
  ;[stats.value, todo.value, trend.value] = await Promise.all([
    dashApi.stats().catch(() => ({})),
    dashApi.todoAggregate().catch(() => ({})),
    dashApi.personalTrend().catch(() => ({})),
  ])
  noteApi.recent().then((r) => (recentNotes.value = r.list || [])).catch(() => {})
  app.fetchNotifications()
  app.fetchUnread()
  computeLatency()
  // 今日卡片与动态：各自独立兜底，单卡失败不影响整页
  loadBanner()
  loadDue()
  loadLearning()
  loadSchedule()
  loadStorage()
  loadActivity()
  loadCardOrder()
})
</script>
