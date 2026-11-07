<template>
  <section class="space-y-3">
    <!-- 时间范围切换 -->
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <span class="text-[12px] text-ink-500">时间范围</span>
      <div class="flex items-center gap-1 rounded-control bg-ink-50 p-0.5">
        <button
          v-for="r in RANGES"
          :key="r.value"
          type="button"
          class="rounded-control px-3 py-1 text-[12px] transition-colors"
          :class="days === r.value ? 'bg-white font-medium text-brand-700 shadow-card' : 'text-ink-500 hover:text-ink-700'"
          @click="changeRange(r.value)"
        >{{ r.label }}</button>
      </div>
      <span class="text-[11px] text-ink-400">统计窗口：近 {{ metrics?.window_days || days }} 天</span>
      <button class="btn-ghost ml-auto" :disabled="loading" @click="loadAll">
        {{ loading ? '加载中…' : '刷新分析' }}
      </button>
    </div>

    <!-- 部分接口失败时的降级提示：有数据仍然展示 -->
    <div
      v-if="failures.length"
      class="flex flex-wrap items-center gap-2 rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700"
    >
      <span class="min-w-0 flex-1">
        以下分析数据暂不可用：{{ failures.map((f) => f.label).join('、') }}（{{ failures[0].message }}）
      </span>
      <button class="font-medium" @click="loadAll">重试</button>
    </div>

    <div v-if="loading && !hasAnyData" class="card py-16 text-center text-[12px] text-ink-400">加载中…</div>
    <div v-else-if="!hasAnyData" class="card flex flex-wrap items-center justify-center gap-3 py-16 text-[12px] text-ink-400">
      <span>暂无分析数据，可能当前账号还没有可见的流程实例</span>
      <button class="btn-ghost px-2 text-[12px]" @click="loadAll">重试</button>
    </div>

    <template v-else>
      <StatsGrid :items="statItems" :loading="loading" :skeleton-count="6" />

      <div class="grid gap-3 lg:grid-cols-2">
        <SectionCard title="按日趋势" :subtitle="`近 ${days} 天发起、完成与任务完成量`">
          <template #actions>
            <span class="tag">发起 {{ formatNumber(trendTotals.started) }}</span>
            <span class="tag bg-emerald-50 text-emerald-600">完成 {{ formatNumber(trendTotals.completed) }}</span>
            <span class="tag bg-amber-50 text-amber-600">任务 {{ formatNumber(trendTotals.tasks) }}</span>
          </template>
          <LineChart
            :series="trendSeries"
            :labels="trendLabels"
            :height="220"
            empty-text="所选时间范围内没有趋势数据"
          />
        </SectionCard>

        <SectionCard title="状态分布" subtitle="全部实例按状态计数与占比">
          <template #actions>
            <span class="tag">共 {{ formatNumber(statusTotal) }} 个</span>
          </template>
          <DonutChart
            :data="statusData"
            :center-value="formatNumber(statusTotal)"
            center-label="实例总数"
            :size="160"
            empty-text="暂无状态分布数据"
          />
        </SectionCard>
      </div>

      <div class="grid gap-3 lg:grid-cols-2">
        <SectionCard title="节点瓶颈" :subtitle="`近 ${days} 天平均办理时长 TOP`" dense>
          <template #actions>
            <span class="tag">{{ bottleneckRows.length }} 个节点</span>
          </template>
          <BarChart
            :data="bottleneckData"
            horizontal
            color="var(--brand-400)"
            :format="formatMinutes"
            empty-text="暂无已办理任务，无法统计节点瓶颈"
          />
        </SectionCard>

        <SectionCard title="分类分布" subtitle="按流程分类统计实例量与完成率" dense>
          <template #actions>
            <span class="tag">{{ categoryRows.length }} 个分类</span>
          </template>
          <BarChart
            :data="categoryData"
            horizontal
            color="#10b981"
            empty-text="暂无分类统计数据"
          />
          <ul v-if="categoryRows.length" class="mt-2 space-y-1 border-t border-ink-100 pt-2">
            <li
              v-for="row in categoryRows"
              :key="row.category"
              class="flex items-center gap-2 text-[11px] text-ink-500"
            >
              <span class="min-w-0 flex-1 truncate">{{ row.category }}</span>
              <span>完成 {{ row.completed }} / {{ row.total }}</span>
              <span class="tag bg-ink-100 text-ink-600">{{ formatPct(row.completion_rate_pct) }}</span>
            </li>
          </ul>
        </SectionCard>
      </div>

      <SectionCard title="节点耗时明细" subtitle="平均、P90、积压与逾期，用于排产与人力调配">
        <div v-if="!bottleneckRows.length" class="py-8 text-center text-[12px] text-ink-400">
          暂无节点耗时数据
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[720px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">节点</th>
                <th class="th">类型</th>
                <th class="th">已完成</th>
                <th class="th">平均耗时</th>
                <th class="th">P90</th>
                <th class="th">积压</th>
                <th class="th">逾期</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in bottleneckRows" :key="row.node_id">
                <td class="td">
                  <div class="max-w-[220px] truncate font-medium text-ink-800">{{ row.node_name || row.node_key }}</div>
                  <div class="truncate font-mono text-[11px] text-ink-400">{{ row.node_key }}</div>
                </td>
                <td class="td text-[12px] text-ink-500">{{ nodeTypeLabel(row.node_type) }}</td>
                <td class="td text-[12px] text-ink-500">{{ formatNumber(row.completed) }}</td>
                <td class="td text-[12px] text-ink-700">{{ formatMinutes(row.avg_duration_minutes) }}</td>
                <td class="td text-[12px] text-ink-500">{{ formatMinutes(row.p90_duration_minutes) }}</td>
                <td class="td text-[12px]" :class="row.backlog ? 'text-amber-600' : 'text-ink-400'">
                  {{ formatNumber(row.backlog) }}
                </td>
                <td class="td text-[12px]" :class="row.overdue ? 'text-rose-500' : 'text-ink-400'">
                  {{ formatNumber(row.overdue) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="指标口径说明" dense>
        <ul class="space-y-1 text-[11px] leading-relaxed text-ink-500">
          <li>· 完成率 = 已完成实例数 / 窗口内发起实例数，拒绝率单独统计。</li>
          <li>· 平均耗时取已完成实例的运行时长均值，节点耗时为已办理任务的处理时长。</li>
          <li>· SLA 达成率 = 未逾期完成任务数 / 已完成任务数，数据来自 /workflow/monitor 接口。</li>
        </ul>
      </SectionCard>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { formatNumber } from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import LineChart from '../../components/platform/LineChart.vue'
import BarChart from '../../components/platform/BarChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'

const props = defineProps({
  /** 父级刷新计数：变化时重新拉取分析数据 */
  refreshKey: { type: Number, default: 0 },
})

const app = useAppStore()
const api = apiFor('workflow')

const RANGES = [
  { value: 7, label: '近 7 天' },
  { value: 14, label: '近 14 天' },
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
]

const NODE_TYPE_LABELS = {
  start: '开始',
  task: '人工任务',
  decision: '条件分支',
  parallel_split: '并行拆分',
  parallel_join: '并行汇聚',
  end: '结束',
}

const INSTANCE_STATUS = {
  running: '运行中',
  completed: '已完成',
  rejected: '已拒绝',
  cancelled: '已取消',
  terminated: '已终止',
}

const STATUS_COLORS = {
  running: 'var(--brand-500)',
  completed: '#10b981',
  rejected: '#f43f5e',
  cancelled: '#94a3b8',
  terminated: '#f59e0b',
}

const days = ref(14)
const loading = ref(false)
const failures = ref([])
const metrics = ref(null)
const statusDistribution = ref(null)
const trend = ref(null)
const bottlenecks = ref(null)
const categories = ref(null)

const hasAnyData = computed(
  () => !!(metrics.value || statusDistribution.value || trend.value || bottlenecks.value || categories.value)
)

const instanceStats = computed(() => metrics.value?.instances || {})
const taskStats = computed(() => metrics.value?.tasks || {})

function formatPct(value) {
  const n = Number(value)
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : '—'
}

function formatMinutes(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 60) return `${(n / 60).toFixed(1)} 小时`
  return `${n.toFixed(0)} 分钟`
}

function nodeTypeLabel(value) {
  return NODE_TYPE_LABELS[value] || value || '节点'
}

const statItems = computed(() => {
  const inst = instanceStats.value
  const tasks = taskStats.value
  return [
    {
      key: 'completion',
      label: '实例完成率',
      value: inst.completion_rate_pct ?? 0,
      unit: '%',
      hint: `窗口内发起 ${formatNumber(inst.total)} 个`,
      tone: 'emerald',
    },
    {
      key: 'avg-duration',
      label: '平均耗时',
      value: inst.avg_duration_minutes ?? 0,
      unit: '分钟',
      hint: '已完成实例的运行时长均值',
      tone: 'brand',
    },
    {
      key: 'reject-rate',
      label: '拒绝率',
      value: inst.reject_rate_pct ?? 0,
      unit: '%',
      hint: `已拒绝 ${formatNumber(inst.rejected)} 个`,
      tone: 'rose',
    },
    {
      key: 'task-rate',
      label: '任务完成率',
      value: tasks.completion_rate_pct ?? 0,
      unit: '%',
      hint: `已完成任务 ${formatNumber(tasks.completed)} 个`,
      tone: 'emerald',
    },
    {
      key: 'sla',
      label: 'SLA 达成率',
      value: tasks.sla_compliance_pct ?? 0,
      unit: '%',
      hint: `逾期任务 ${formatNumber(tasks.overdue)} 个`,
      tone: 'amber',
    },
    {
      key: 'task-avg',
      label: '任务平均办理',
      value: tasks.avg_handling_minutes ?? 0,
      unit: '分钟',
      hint: `未结任务 ${formatNumber(tasks.open)} 个`,
      tone: 'brand',
    },
  ]
})

const statusTotal = computed(() => {
  const rows = statusDistribution.value?.items || []
  return rows.reduce((sum, row) => sum + (Number(row.count) || 0), 0)
})

const statusData = computed(() => {
  const rows = statusDistribution.value?.items || []
  return rows.map((row) => ({
    label: INSTANCE_STATUS[row.status] || row.status || '未知',
    value: Number(row.count) || 0,
    color: STATUS_COLORS[row.status] || '#cbd5e1',
  }))
})

const trendRows = computed(() => trend.value?.items || [])
const trendLabels = computed(() => trendRows.value.map((row) => String(row.date || '').slice(5)))

const trendSeries = computed(() => [
  {
    name: '发起',
    color: 'var(--brand-500)',
    data: trendRows.value.map((row) => Number(row.started) || 0),
  },
  {
    name: '完成',
    color: '#10b981',
    data: trendRows.value.map((row) => Number(row.completed) || 0),
  },
  {
    name: '任务完成',
    color: '#f59e0b',
    data: trendRows.value.map((row) => Number(row.tasks_completed) || 0),
  },
])

const trendTotals = computed(() => ({
  started: trendRows.value.reduce((sum, row) => sum + (Number(row.started) || 0), 0),
  completed: trendRows.value.reduce((sum, row) => sum + (Number(row.completed) || 0), 0),
  tasks: trendRows.value.reduce((sum, row) => sum + (Number(row.tasks_completed) || 0), 0),
}))

const bottleneckRows = computed(() => bottlenecks.value?.items || [])

const bottleneckData = computed(() =>
  bottleneckRows.value.map((row) => ({
    label: row.node_name || row.node_key || `节点 ${row.node_id}`,
    value: Number(row.avg_duration_minutes) || 0,
  }))
)

const categoryRows = computed(() => categories.value?.items || [])

const categoryData = computed(() =>
  categoryRows.value.map((row) => ({
    label: row.category || '未分类',
    value: Number(row.total) || 0,
  }))
)

async function loadAll() {
  if (!api) {
    failures.value = [{ label: '流程引擎接口', message: '接口不可用' }]
    return
  }
  loading.value = true
  failures.value = []

  const jobs = [
    {
      key: 'metrics',
      label: '指标概览',
      run: () => api.get(`monitor/metrics/?days=${days.value}`),
      assign: (v) => { metrics.value = v },
    },
    {
      key: 'status',
      label: '状态分布',
      run: () => api.get('monitor/status-distribution/'),
      assign: (v) => { statusDistribution.value = v },
    },
    {
      key: 'trend',
      label: '按日趋势',
      run: () => api.get(`monitor/trend/?days=${days.value}`),
      assign: (v) => { trend.value = v },
    },
    {
      key: 'bottlenecks',
      label: '节点瓶颈',
      run: () => api.get(`monitor/bottlenecks/?days=${days.value}&limit=10`),
      assign: (v) => { bottlenecks.value = v },
    },
    {
      key: 'categories',
      label: '分类分布',
      run: () => api.get('monitor/category-distribution/'),
      assign: (v) => { categories.value = v },
    },
  ]

  // 单个接口失败不影响其它区块，能展示的先展示，不能展示的降级为空态
  const results = await Promise.allSettled(jobs.map((job) => job.run()))
  results.forEach((result, index) => {
    const job = jobs[index]
    if (result.status === 'fulfilled') {
      job.assign(result.value)
    } else {
      job.assign(null)
      failures.value = [
        ...failures.value,
        { label: job.label, message: result.reason?.message || '接口异常' },
      ]
    }
  })
  loading.value = false
}

function changeRange(value) {
  if (days.value === value) return
  days.value = value
  loadAll()
}

watch(
  () => props.refreshKey,
  () => {
    loadAll()
  }
)

onMounted(() => {
  loadAll()
})
</script>