<template>
  <div class="mx-auto max-w-6xl space-y-5">
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

    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div v-for="s in statCards" :key="s.label" class="card p-4">
        <div class="text-[12px] text-ink-500">{{ s.label }}</div>
        <div class="mt-1 text-[24px] font-bold text-ink-900">{{ s.value }}</div>
        <div class="mt-0.5 text-[11px] text-ink-400">{{ s.note }}</div>
      </div>
    </div>

    <div class="card p-5">
      <div class="mb-2 flex items-center justify-between">
        <span class="text-[13px] font-medium text-ink-700">存储空间</span>
        <span class="text-[12px] text-ink-500">{{ formatSize(stats.storage_bytes) }} / {{ stats.quota_mb }} MB</span>
      </div>
      <div class="h-2.5 overflow-hidden rounded-pill bg-ink-100">
        <div class="h-full rounded-pill bg-brand-500" :style="{ width: Math.min(100, stats.quota_used_pct || 0) + '%' }"></div>
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
import { computed, onMounted, ref } from 'vue'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'
import { dashApi, noteApi } from '../api'
import { formatSize, formatTime } from '../utils/format'

const user = useUserStore()
const app = useAppStore()
const stats = ref({})
const todo = ref({})
const trend = ref({})
const recentNotes = ref([])
const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })

const statCards = computed(() => [
  { label: '我的文件', value: stats.value.files ?? '-', note: `${formatSize(stats.value.storage_bytes || 0)} 已用` },
  { label: '我的笔记', value: stats.value.notes ?? '-', note: `${stats.value.folders ?? 0} 个文件夹` },
  { label: '参与项目', value: stats.value.projects ?? '-', note: `${stats.value.my_tasks ?? 0} 个进行中任务` },
  { label: '收藏文件', value: todo.value.starred_files ?? '-', note: `置顶笔记 ${todo.value.pinned_notes ?? 0}` },
])
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
})
</script>
