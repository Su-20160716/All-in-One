<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="card flex items-center justify-between p-4">
      <div>
        <h2 class="text-[15px] font-semibold">全局统计面板</h2>
        <p class="mt-0.5 text-[12px] text-ink-500">平台整体运行情况（仅管理员可见）。</p>
      </div>
      <span class="tag tag-brand">{{ stats.users }} 位用户</span>
    </div>

    <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div v-for="c in cards" :key="c.label" class="card p-4">
        <div class="text-[12px] text-ink-500">{{ c.label }}</div>
        <div class="mt-1 text-[24px] font-bold text-ink-900">{{ c.value }}</div>
        <div class="mt-0.5 text-[11px] text-ink-400">{{ c.note }}</div>
      </div>
    </div>

    <!-- #71 在线用户面板 -->
    <div class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">在线用户（5分钟内活跃）</h3>
        <span class="tag bg-emerald-50 text-emerald-600">{{ onlineUsers.length }} 人在线</span>
      </div>
      <div class="flex flex-wrap gap-2">
        <div v-for="u in onlineUsers" :key="u.id" class="flex items-center gap-1.5 rounded-control bg-emerald-50 px-2 py-1 text-[12px]">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
          {{ u.nickname || u.username }}
        </div>
        <div v-if="!onlineUsers.length" class="py-3 text-center text-[12px] text-ink-400">暂无在线用户</div>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <div class="card p-4">
        <h3 class="mb-3 text-[13px] font-semibold">近 14 天操作量</h3>
        <div v-if="trend.labels?.length" class="flex h-36 items-end gap-1">
          <div v-for="(v, i) in trend.values" :key="i" class="flex-1">
            <div class="w-full rounded-t bg-brand-400" :style="{ height: Math.max(2, (v / maxTrend) * 120) + 'px' }" :title="`${trend.labels[i]}: ${v}`"></div>
            <div class="mt-1 text-center text-[9px] text-ink-300">{{ trend.labels[i] }}</div>
          </div>
        </div>
        <div v-else class="py-10 text-center text-[12px] text-ink-400">暂无数据</div>
      </div>

      <div class="card p-4">
        <h3 class="mb-3 text-[13px] font-semibold">近 30 天新增用户</h3>
        <div v-if="growth.labels?.length" class="flex h-36 items-end gap-px">
          <div v-for="(v, i) in growth.new" :key="i" class="flex-1">
            <div class="w-full rounded-t bg-emerald-400" :style="{ height: Math.max(2, (v / maxGrowth) * 120) + 'px' }" :title="`${growth.labels[i]}: 新增 ${v}，累计 ${growth.cumulative[i]}`"></div>
            <div class="mt-1 text-center text-[8px] text-ink-300">{{ growth.labels[i] }}</div>
          </div>
        </div>
        <div v-else class="py-10 text-center text-[12px] text-ink-400">暂无数据</div>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <div class="card p-4">
        <h3 class="mb-3 text-[13px] font-semibold">模块使用量</h3>
        <div v-for="m in moduleUsage.by_module || []" :key="m.module" class="mb-2">
          <div class="mb-1 flex justify-between text-[12px]"><span>{{ m.module || '未知' }}</span><span class="text-ink-400">{{ m.c }}</span></div>
          <div class="h-2 rounded-full bg-ink-100"><div class="h-full rounded-full bg-brand-500" :style="{ width: modulePct(m.c) + '%' }"></div></div>
        </div>
      </div>

      <!-- #72 存储使用 TOP 用户 -->
      <div class="card p-4">
        <h3 class="mb-3 text-[13px] font-semibold">存储使用 Top 10</h3>
        <div class="space-y-1.5">
          <div v-for="(u, i) in storageTop" :key="i" class="flex justify-between text-[13px]">
            <span>{{ i + 1 }}. {{ u.nickname || u.username }}</span>
            <span class="text-ink-400">{{ u.total_text }} ({{ u.file_count }} 文件)</span>
          </div>
          <div v-if="!storageTop.length" class="py-3 text-center text-[12px] text-ink-400">暂无数据</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { dashApi, coreApi, authApi } from '../../api'
import { formatSize } from '../../utils/format'

const stats = ref({})
const trend = ref({})
const growth = ref({})
const moduleUsage = ref({})
const onlineUsers = ref([])
const storageTop = ref([])
const maxTrend = computed(() => Math.max(1, ...(trend.value.values || [])))
const maxGrowth = computed(() => Math.max(1, ...(growth.value.new || [])))
const maxModule = computed(() => Math.max(1, ...(moduleUsage.value.by_module || []).map((m) => m.c)))
function modulePct(c) { return Math.round((c / maxModule.value) * 100) }

const cards = computed(() => [
  { label: '用户总数', value: stats.value.users ?? '-', note: `今日新增 ${stats.value.user_signups_today ?? 0} · 7日活跃 ${stats.value.active_users_7d ?? 0}` },
  { label: '文件总数', value: stats.value.files ?? '-', note: `占用 ${formatSize(stats.value.storage_bytes || 0)}` },
  { label: '笔记 / 项目', value: `${stats.value.notes ?? 0} / ${stats.value.projects ?? 0}`, note: `${stats.value.tasks ?? 0} 张任务卡片` },
  { label: '消息 / 日志', value: `${stats.value.messages ?? 0} / ${stats.value.ops_total ?? 0}`, note: `今日操作 ${stats.value.ops_today ?? 0} 次` },
])

onMounted(async () => {
  const [g, t, ug, mu, online, topUsers] = await Promise.all([
    dashApi.global().catch(() => ({})),
    dashApi.trend().catch(() => ({})),
    dashApi.userGrowth().catch(() => ({})),
    dashApi.moduleUsage().catch(() => ({})),
    authApi.online({ minutes: 5 }).catch(() => ({ list: [] })),
    coreApi.storageTopUsers().catch(() => ({ list: [] })),
  ])
  stats.value = g; trend.value = t; growth.value = ug; moduleUsage.value = mu
  onlineUsers.value = online.list || []
  storageTop.value = topUsers.list || []
})
</script>
