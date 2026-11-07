<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="card flex items-center justify-between p-4">
      <div>
        <h2 class="text-[15px] font-semibold">全局统计面板</h2>
        <p class="mt-0.5 text-[12px] text-ink-500">平台整体运行情况（仅管理员可见）。</p>
      </div>
      <span class="tag tag-brand">{{ formatNumber(stats.users) }} 位用户</span>
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
        <!-- #195 柱状图用 div 高度表达数据，补 role="img" + 摘要与 sr-only 数据列表 -->
        <div v-if="trend.labels?.length" class="flex h-36 items-end gap-1" role="img" :aria-label="trendSummary">
          <div v-for="(v, i) in trend.values" :key="i" class="flex-1">
            <div class="w-full rounded-t bg-brand-400" :style="{ height: Math.max(2, (v / maxTrend) * 120) + 'px' }" :title="`${trend.labels[i]}: ${v}`"></div>
            <div class="mt-1 text-center text-[9px] text-ink-300">{{ trend.labels[i] }}</div>
          </div>
        </div>
        <div v-else class="py-10 text-center text-[12px] text-ink-400">暂无数据</div>
        <ul class="sr-only">
          <li v-for="(v, i) in trend.values" :key="'t' + i">{{ trend.labels[i] }}：{{ v }} 次操作</li>
        </ul>
      </div>

      <div class="card p-4">
        <h3 class="mb-3 text-[13px] font-semibold">近 30 天新增用户</h3>
        <div v-if="growth.labels?.length" class="flex h-36 items-end gap-px" role="img" :aria-label="growthSummary">
          <div v-for="(v, i) in growth.new" :key="i" class="flex-1">
            <div class="w-full rounded-t bg-emerald-400" :style="{ height: Math.max(2, (v / maxGrowth) * 120) + 'px' }" :title="`${growth.labels[i]}: 新增 ${v}，累计 ${growth.cumulative[i]}`"></div>
            <div class="mt-1 text-center text-[8px] text-ink-300">{{ growth.labels[i] }}</div>
          </div>
        </div>
        <div v-else class="py-10 text-center text-[12px] text-ink-400">暂无数据</div>
        <ul class="sr-only">
          <li v-for="(v, i) in growth.new" :key="'g' + i">{{ growth.labels[i] }}：新增 {{ v }}，累计 {{ growth.cumulative?.[i] }}</li>
        </ul>
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
            <span class="text-ink-400">{{ u.total_text }} ({{ formatNumber(u.file_count) }} 文件)</span>
          </div>
          <div v-if="!storageTop.length" class="py-3 text-center text-[12px] text-ink-400">暂无数据</div>
        </div>
      </div>
    </div>

    <!-- ================= #418 接口用量（按 app 聚合） ================= -->
    <div class="card p-4">
      <div class="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 class="text-[14px] font-semibold">接口用量</h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            按应用前缀聚合写操作、PAT 调用、慢接口与异常；慢接口/异常为采样口径。
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button v-for="d in apiUsageDaysChoices" :key="d" class="btn-outline text-[12px]"
                  :class="apiUsageDays === d ? 'border-brand-400 bg-brand-50 text-brand-700' : ''"
                  :disabled="apiUsageLoading" @click="loadApiUsage(d)">{{ d }} 天</button>
          <button class="btn-outline text-[12px]" :disabled="apiUsageLoading" @click="loadApiUsage(apiUsageDays)">刷新</button>
          <button class="btn-outline text-[12px]" :disabled="dueBusy" @click="runDueSchedules">
            {{ dueBusy ? '执行中…' : '执行到期任务' }}
          </button>
        </div>
      </div>

      <div v-if="apiUsageLoading" class="py-8 text-center text-[12px] text-ink-400">接口用量加载中…</div>
      <div v-else-if="apiUsageError" class="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-control border border-rose-100 bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span>接口用量加载失败：{{ apiUsageError }}</span>
        <button class="font-medium underline" @click="loadApiUsage(apiUsageDays)">重试</button>
      </div>
      <template v-else>
        <div class="mt-3 flex flex-wrap gap-2 text-[11px]">
          <span class="rounded-control bg-ink-50 px-2 py-1 text-ink-600">调用量 <b class="text-ink-800">{{ formatNumber(apiUsage.totals?.calls ?? 0) }}</b></span>
          <span class="rounded-control bg-ink-50 px-2 py-1 text-ink-600">写操作 <b class="text-ink-800">{{ formatNumber(apiUsage.totals?.ops ?? 0) }}</b></span>
          <span class="rounded-control bg-ink-50 px-2 py-1 text-ink-600">PAT 调用 <b class="text-ink-800">{{ formatNumber(apiUsage.totals?.pat_calls ?? 0) }}</b></span>
          <span class="rounded-control bg-ink-50 px-2 py-1 text-ink-600">慢调用 <b class="text-ink-800">{{ formatNumber(apiUsage.totals?.slow ?? 0) }}</b></span>
          <span class="rounded-control bg-ink-50 px-2 py-1 text-ink-600">异常 <b class="text-ink-800">{{ formatNumber(apiUsage.totals?.errors ?? 0) }}</b></span>
          <span class="rounded-control bg-ink-50 px-2 py-1 text-ink-600">应用数 <b class="text-ink-800">{{ formatNumber(apiUsage.totals?.apps ?? 0) }}</b></span>
        </div>

        <div class="mt-3 overflow-x-auto">
          <table class="w-full min-w-[760px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">应用</th>
                <th class="th">调用量</th>
                <th class="th">写操作</th>
                <th class="th">PAT 调用</th>
                <th class="th">平均耗时</th>
                <th class="th">慢调用</th>
                <th class="th">异常</th>
                <th class="th">错误率</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="r in apiUsage.list || []" :key="r.app" class="hover:bg-ink-50/40">
                <td class="td"><span class="tag tag-brand font-mono">{{ r.app }}</span></td>
                <td class="td font-medium">{{ formatNumber(r.calls) }}</td>
                <td class="td text-ink-500">{{ formatNumber(r.ops) }}</td>
                <td class="td text-ink-500">{{ formatNumber(r.pat_calls) }}</td>
                <td class="td text-ink-500">{{ r.avg_ms ? r.avg_ms + ' ms' : '-' }}</td>
                <td class="td text-ink-500">{{ formatNumber(r.slow) }}</td>
                <td class="td" :class="r.errors ? 'text-rose-500' : 'text-ink-500'">{{ formatNumber(r.errors) }}</td>
                <td class="td"><span class="tag" :class="errorRateClass(r.error_rate)">{{ r.error_rate ?? 0 }}%</span></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!(apiUsage.list || []).length" class="py-10 text-center text-[12px] text-ink-400">窗口内暂无接口调用</div>
        </div>
        <div class="mt-2 text-[11px] text-ink-400">
          {{ apiUsage.start || '-' }} ~ {{ apiUsage.end || '-' }}<span v-if="apiUsage.note"> · {{ apiUsage.note }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { dashApi, coreApi, authApi } from '../../api'
import { developerxApi } from '../../api/developerx'
import { useAppStore } from '../../stores/app'
import { formatNumber, formatSize } from '../../utils/format'

const app = useAppStore()

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
// #195 图表摘要：给读屏一个能替代柱状图的口述版本
const trendSummary = computed(() => {
  const vals = trend.value.values || []
  const labels = trend.value.labels || []
  if (!vals.length) return '近 14 天操作量柱状图：暂无数据'
  const total = vals.reduce((a, b) => a + b, 0)
  const max = Math.max(...vals)
  return `近 14 天操作量柱状图：共 ${total} 次，峰值 ${max} 次（${labels[vals.indexOf(max)] || '-'}），最近一天 ${labels[labels.length - 1] || '-'} 为 ${vals[vals.length - 1]} 次`
})
const growthSummary = computed(() => {
  const vals = growth.value.new || []
  const labels = growth.value.labels || []
  if (!vals.length) return '近 30 天新增用户柱状图：暂无数据'
  const total = vals.reduce((a, b) => a + b, 0)
  const max = Math.max(...vals)
  return `近 30 天新增用户柱状图：共新增 ${total} 人，峰值 ${max} 人（${labels[vals.indexOf(max)] || '-'}），最近一天新增 ${vals[vals.length - 1]} 人`
})

const cards = computed(() => [
  { label: '用户总数', value: stats.value.users == null ? '-' : formatNumber(stats.value.users), note: `今日新增 ${formatNumber(stats.value.user_signups_today ?? 0)} · 7日活跃 ${formatNumber(stats.value.active_users_7d ?? 0)}` },
  { label: '文件总数', value: stats.value.files == null ? '-' : formatNumber(stats.value.files), note: `占用 ${formatSize(stats.value.storage_bytes || 0)}` },
  { label: '笔记 / 项目', value: `${formatNumber(stats.value.notes ?? 0)} / ${formatNumber(stats.value.projects ?? 0)}`, note: `${formatNumber(stats.value.tasks ?? 0)} 张任务卡片` },
  { label: '消息 / 日志', value: `${formatNumber(stats.value.messages ?? 0)} / ${formatNumber(stats.value.ops_total ?? 0)}`, note: `今日操作 ${formatNumber(stats.value.ops_today ?? 0)} 次` },
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
  // #418 接口用量局部降级：失败只影响本区块
  loadApiUsage()
})

// ===========================================================================
// #418 接口用量（按 app 聚合）+ #417 执行到期任务
// ===========================================================================
const apiUsage = ref({})
const apiUsageDays = ref(7)
const apiUsageDaysChoices = [7, 14, 30]
const apiUsageLoading = ref(false)
const apiUsageError = ref('')
const dueBusy = ref(false)

const errorRateClass = (rate) => {
  const n = Number(rate) || 0
  if (n >= 10) return 'bg-rose-50 text-rose-600'
  if (n >= 3) return 'bg-amber-50 text-amber-700'
  if (n > 0) return 'bg-emerald-50 text-emerald-600'
  return 'bg-ink-100 text-ink-500'
}

async function loadApiUsage(days = apiUsageDays.value) {
  apiUsageDays.value = days
  apiUsageLoading.value = true
  apiUsageError.value = ''
  try {
    apiUsage.value = await developerxApi.apiUsage(days)
  } catch (e) {
    apiUsage.value = {}
    apiUsageError.value = e?.message || '加载失败'
  } finally {
    apiUsageLoading.value = false
  }
}

async function runDueSchedules() {
  if (dueBusy.value) return
  dueBusy.value = true
  try {
    const r = await developerxApi.runDueSchedules()
    app.toastMsg(r.message || '已检查到期任务', 'success')
  } catch (e) {
    app.toastMsg(e?.message || '执行失败', 'error')
  } finally {
    dueBusy.value = false
  }
}
</script>
