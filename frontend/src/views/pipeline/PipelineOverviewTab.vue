<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="text-[12px] text-ink-500">统计窗口</span>
        <button
          v-for="day in DAY_OPTIONS"
          :key="day"
          class="rounded-pill px-2.5 py-1 text-[12px]"
          :class="days === day ? 'bg-ink-700 text-white' : 'border border-ink-200 bg-white text-ink-500 hover:bg-ink-50'"
          @click="setDays(day)"
        >
          {{ day }} 天
        </button>
        <span class="ml-1 tag">{{ rangeLabel }}</span>
        <span v-if="latencySource" class="tag">耗时口径 {{ latencySource }}</span>
      </div>
      <div class="flex items-center gap-1.5">
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'pipelines')">去编排</button>
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'runs')">运行记录</button>
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'quality')">数据质量</button>
        <button class="btn-outline py-1 text-[12px]" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '刷新统计' }}
        </button>
      </div>
    </div>

    <div
      v-if="fatalError"
      class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
    >
      <span class="min-w-0 flex-1">{{ fatalError }}</span>
      <button class="shrink-0 font-medium" @click="load">重试</button>
    </div>

    <div v-if="partialErrors.length" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      部分统计接口不可用：{{ partialErrors.join('；') }}
    </div>

    <StatsGrid :items="kpis" :loading="loading" :skeleton-count="5" />

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="成功率趋势" :subtitle="`近 ${days} 天按天聚合，失败率与成功数来自后端统计`">
        <template #actions>
          <span class="tag" :class="averageRate >= 95 ? 'bg-emerald-50 text-emerald-600' : averageRate >= 80 ? 'bg-amber-50 text-amber-600' : 'bg-rose-50 text-rose-600'">
            窗口均值 {{ averageRateText }}
          </span>
        </template>
        <div v-if="loading && !ratePoints.length" class="py-16 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!ratePoints.length" class="rounded-control border border-dashed border-ink-200 py-16 text-center text-[12px] text-ink-400">
          窗口内暂无运行数据，触发一次运行后即可看到趋势
        </div>
        <template v-else>
          <LineChart
            :series="rateSeries"
            :labels="ratePoints.map((item) => item.label)"
            :height="210"
            :format="formatPercentValue"
            :y-ticks="4"
          />
          <div class="mt-2 grid grid-cols-3 gap-2 text-center text-[11px] text-ink-400">
            <div class="rounded-control bg-ink-50 py-1.5">
              <div class="text-[13px] font-semibold text-ink-700">{{ formatNumber(totalRunsInWindow) }}</div>
              窗口运行总数
            </div>
            <div class="rounded-control bg-ink-50 py-1.5">
              <div class="text-[13px] font-semibold text-emerald-600">{{ formatNumber(successRunsInWindow) }}</div>
              成功运行
            </div>
            <div class="rounded-control bg-ink-50 py-1.5">
              <div class="text-[13px] font-semibold text-rose-600">{{ formatNumber(failedRunsInWindow) }}</div>
              失败运行
            </div>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="数据行数趋势" :subtitle="`输入 / 输出行数按天对比，近 ${days} 天`">
        <template #actions>
          <span class="tag">输出 {{ formatNumber(outputRowsInWindow) }} 行</span>
        </template>
        <div v-if="loading && !rowPoints.length" class="py-16 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!rowPoints.length" class="rounded-control border border-dashed border-ink-200 py-16 text-center text-[12px] text-ink-400">
          暂无行数趋势数据
        </div>
        <LineChart
          v-else
          :series="rowSeries"
          :labels="rowPoints.map((item) => item.label)"
          :height="210"
          :format="formatNumber"
          :y-ticks="4"
        />
      </SectionCard>
    </div>

    <div class="grid gap-3 lg:grid-cols-5">
      <SectionCard class="lg:col-span-2" title="失败节点 TOP" :subtitle="`近 ${days} 天失败次数最多的节点`">
        <template #actions>
          <span class="tag">{{ failedNodes.length }} 个节点</span>
        </template>
        <div v-if="loading && !failedNodes.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!failedNodes.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
          窗口内没有失败节点，链路稳定
        </div>
        <template v-else>
          <BarChart :data="failedBars" horizontal :height="176" />
          <div class="mt-2 divide-y divide-ink-50">
            <div v-for="item in failedNodes.slice(0, 5)" :key="item.key" class="flex items-center gap-2 py-1 text-[11px]">
              <span class="min-w-0 flex-1 truncate text-ink-700">{{ item.key }}</span>
              <span class="shrink-0 text-ink-400">{{ typeLabel(item.type) }}</span>
              <span class="w-12 shrink-0 text-right font-medium text-rose-600">{{ formatNumber(item.failures) }}</span>
            </div>
          </div>
        </template>
      </SectionCard>

      <SectionCard class="lg:col-span-3" title="最近运行" :subtitle="`最新 ${recentRuns.length} 条运行记录`">
        <template #actions>
          <button class="btn-ghost py-0.5 text-[11px]" @click="emit('go', 'runs')">查看全部</button>
        </template>
        <div v-if="loading && !recentRuns.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!recentRuns.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
          还没有运行记录，可到「运行记录」页签手动触发
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[520px]">
            <thead>
              <tr class="border-b border-ink-100">
                <th class="th">管道</th>
                <th class="th">状态</th>
                <th class="th">触发</th>
                <th class="th text-right">耗时</th>
                <th class="th text-right">输出行数</th>
                <th class="th text-right">开始时间</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="run in recentRuns" :key="run.id" class="transition-colors hover:bg-ink-50/60">
                <td class="td">
                  <div class="max-w-[180px] truncate">{{ run.pipeline_name || pipelineName(run.pipeline_id) }}</div>
                  <div class="text-[11px] text-ink-400">#{{ run.id }}</div>
                </td>
                <td class="td">
                  <span class="tag" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span>
                </td>
                <td class="td text-[12px] text-ink-500">{{ triggerLabel(run.trigger) }}</td>
                <td class="td text-right">{{ durationText(run.duration_ms) }}</td>
                <td class="td text-right">{{ formatNumber(run.output_rows) }}</td>
                <td class="td text-right text-[11px] text-ink-400">{{ formatDate(run.started_at, true) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiFor, listOf } from '../../api/platform'
import { formatDate, formatNumber } from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import LineChart from '../../components/platform/LineChart.vue'
import BarChart from '../../components/platform/BarChart.vue'

const props = defineProps({
  pipelines: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])

const api = apiFor('pipeline')
const app = useAppStore()

const DAY_OPTIONS = [7, 30, 90]
const TYPE_LABELS = {
  source: '数据源',
  transform: '转换',
  filter: '过滤',
  aggregate: '聚合',
  join: '关联',
  sort: '排序',
  dedupe: '去重',
  map: '映射',
  sink: '输出',
  webhook: '回调',
}
const STATUS_LABELS = {
  queued: '排队中',
  running: '运行中',
  success: '成功',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
}
const TRIGGER_LABELS = {
  manual: '手动',
  schedule: '定时',
  webhook: '回调',
  retry: '重跑',
  api: '接口',
}

const days = ref(30)
const loading = ref(false)
const fatalError = ref('')
const partialErrors = ref([])
const overview = ref({})
const latency = ref({})
const ratePoints = ref([])
const rowPoints = ref([])
const failedNodes = ref([])
const recentRuns = ref([])

const latencySource = computed(() => {
  const value = pickText(latency.value, ['source', 'window', 'scope'], '')
  return value ? String(value) : ''
})

const rangeLabel = computed(() => `近 ${days.value} 天`)

function pickValue(source, keys) {
  const obj = source || {}
  for (const key of keys) {
    const value = obj[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function pickText(source, keys, fallback = '—') {
  const value = pickValue(source, keys)
  return value === null ? fallback : String(value)
}

function pickNum(source, keys, fallback = 0) {
  const value = pickValue(source, keys)
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function normalizeRate(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return 0
  // 后端可能返回 0.93 或 93 两种口径，统一成百分数
  const percentValue = num > 0 && num <= 1 ? num * 100 : num
  return Math.max(0, Math.min(100, Number(percentValue.toFixed(2))))
}

const pipelineCount = computed(() => {
  const fromApi = pickNum(overview.value, ['pipeline_count', 'pipelines', 'total_pipelines'], 0)
  return fromApi || props.pipelines.length
})
const runningCount = computed(() => pickNum(overview.value, ['running_runs', 'running', 'running_count'], 0))
const todaySuccess = computed(() => pickNum(overview.value, ['today_success', 'success_today', 'today_succeeded'], 0))
const failureRate = computed(() => {
  const raw = pickNum(overview.value, ['failure_rate', 'failed_rate', 'error_rate'], 0)
  const percentValue = raw > 0 && raw <= 1 ? raw * 100 : raw
  return Math.max(0, Math.min(100, Number(percentValue.toFixed(2))))
})
const p95 = computed(() => {
  const fromLatency = pickNum(latency.value, ['p95_ms', 'p95', 'p95_duration_ms'], 0)
  if (fromLatency) return fromLatency
  return pickNum(overview.value, ['p95_duration_ms', 'p95_ms', 'p95'], 0)
})

const kpis = computed(() => [
  {
    key: 'pipelines',
    label: '管道数',
    value: pipelineCount.value,
    unit: '条',
    hint: `已发布 ${formatNumber(pickNum(overview.value, ['published_pipelines', 'published'], 0))} 条`,
    tone: 'brand',
  },
  {
    key: 'running',
    label: '运行中',
    value: runningCount.value,
    unit: '个',
    hint: `排队 ${formatNumber(pickNum(overview.value, ['queued_runs', 'queued'], 0))} 个`,
    tone: 'amber',
  },
  {
    key: 'today_success',
    label: '今日成功',
    value: todaySuccess.value,
    unit: '次',
    hint: `今日失败 ${formatNumber(pickNum(overview.value, ['today_failed', 'failed_today'], 0))} 次`,
    tone: 'emerald',
  },
  {
    key: 'failure_rate',
    label: '失败率',
    value: `${failureRate.value.toFixed(1)}%`,
    hint: `窗口运行 ${formatNumber(pickNum(overview.value, ['total_runs', 'runs'], 0))} 次`,
    tone: failureRate.value > 10 ? 'rose' : 'default',
    invertDelta: true,
  },
  {
    key: 'p95',
    label: 'P95 耗时',
    value: durationText(p95.value),
    hint: p95.value ? '节点耗时 95 分位' : '接口未返回延迟数据',
    tone: 'default',
  },
])

const averageRate = computed(() => {
  if (!ratePoints.value.length) return 0
  const sum = ratePoints.value.reduce((acc, item) => acc + item.rate, 0)
  return Number((sum / ratePoints.value.length).toFixed(1))
})
const averageRateText = computed(() => `${averageRate.value.toFixed(1)}%`)

const rateSeries = computed(() => [
  { name: '成功率(%)', data: ratePoints.value.map((item) => Number(item.rate.toFixed(2))), area: true },
])

const rowSeries = computed(() => [
  { name: '输入行数', data: rowPoints.value.map((item) => item.input), color: '#6366f1' },
  { name: '输出行数', data: rowPoints.value.map((item) => item.output), color: '#10b981' },
])

const totalRunsInWindow = computed(() => ratePoints.value.reduce((acc, item) => acc + item.total, 0))
const successRunsInWindow = computed(() => ratePoints.value.reduce((acc, item) => acc + item.success, 0))
const failedRunsInWindow = computed(() => ratePoints.value.reduce((acc, item) => acc + item.failed, 0))
const outputRowsInWindow = computed(() => rowPoints.value.reduce((acc, item) => acc + item.output, 0))

const failedBars = computed(() =>
  failedNodes.value.map((item) => ({ label: item.key, value: item.failures })),
)

function typeLabel(type) {
  return TYPE_LABELS[type] || type || '节点'
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || '未知'
}

function statusClass(status) {
  const map = {
    success: 'bg-emerald-50 text-emerald-600',
    running: 'bg-amber-50 text-amber-600',
    queued: 'bg-sky-50 text-sky-600',
    failed: 'bg-rose-50 text-rose-600',
    cancelled: 'bg-ink-100 text-ink-500',
  }
  return map[status] || 'bg-ink-100 text-ink-500'
}

function triggerLabel(trigger) {
  return TRIGGER_LABELS[trigger] || trigger || '手动'
}

function durationText(ms) {
  const num = Number(ms)
  if (!Number.isFinite(num) || num <= 0) return '—'
  if (num < 1000) return `${num} ms`
  if (num < 60000) return `${(num / 1000).toFixed(1)} s`
  return `${(num / 60000).toFixed(1)} min`
}

function formatPercentValue(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  return `${num.toFixed(0)}%`
}

function pipelineName(id) {
  const hit = props.pipelines.find((item) => String(item.id) === String(id))
  if (hit) return hit.name || hit.code
  return id ? `管道 #${id}` : '—'
}

function dayLabel(item) {
  const raw = item?.date ?? item?.day ?? item?.bucket ?? item?.label ?? item?.stat_date ?? ''
  if (!raw) return '—'
  return String(raw).slice(5) || String(raw)
}

function normalizeRatePoints(data) {
  return listOf(data)
    .map((item) => {
      const total = pickNum(item, ['total', 'runs', 'total_runs', 'count'], 0)
      const success = pickNum(item, ['success', 'succeeded', 'success_runs', 'success_count'], 0)
      const failed = pickNum(item, ['failed', 'failures', 'failed_runs', 'failure_count'], 0)
      const rateRaw = pickValue(item, ['rate', 'success_rate', 'successRate'])
      const rate = rateRaw === null
        ? normalizeRate(total ? success / total : 0)
        : normalizeRate(rateRaw)
      return { label: dayLabel(item), total, success, failed, rate }
    })
    .filter((item) => item.label !== '—' || item.total > 0)
    .slice(-Math.max(days.value, 7))
}

function normalizeRowPoints(data) {
  return listOf(data)
    .map((item) => ({
      label: dayLabel(item),
      input: pickNum(item, ['input_rows', 'rows_in', 'input', 'read_rows'], 0),
      output: pickNum(item, ['output_rows', 'rows_out', 'output', 'written_rows'], 0),
    }))
    .filter((item) => item.input > 0 || item.output > 0 || item.label !== '—')
    .slice(-Math.max(days.value, 7))
}

function normalizeFailedNodes(data) {
  return listOf(data)
    .map((item) => {
      const key = pickText(item, ['node_key', 'key', 'node', 'name'], '未命名节点')
      return {
        key,
        type: pickText(item, ['node_type', 'type'], ''),
        failures: pickNum(item, ['failures', 'failed', 'failed_count', 'count'], 0),
      }
    })
    .filter((item) => item.failures >= 0)
    .sort((a, b) => b.failures - a.failures)
    .slice(0, 8)
}

async function load() {
  if (!api) {
    fatalError.value = '数据管道接口不可用'
    return
  }
  loading.value = true
  fatalError.value = ''
  partialErrors.value = []

  const tasks = [
    api.get('stats/overview/').then((data) => { overview.value = data || {} }),
    api.get('stats/latency/', { days: days.value }).then((data) => { latency.value = data || {} }),
    api.get('stats/success-rate/', { days: days.value }).then((data) => { ratePoints.value = normalizeRatePoints(data) }),
    api.get('stats/row-trend/', { days: days.value }).then((data) => { rowPoints.value = normalizeRowPoints(data) }),
    api.get('stats/failed-nodes/', { days: days.value }).then((data) => { failedNodes.value = normalizeFailedNodes(data) }),
    api.list('runs/', { page: 1, page_size: 10 }).then((data) => { recentRuns.value = data.items || [] }),
  ]

  const results = await Promise.allSettled(tasks)
  const labels = ['总览', '延迟', '成功率趋势', '行数趋势', '失败节点', '最近运行']
  results.forEach((result, index) => {
    if (result.status === 'rejected') {
      const message = result.reason?.message || '加载失败'
      partialErrors.value.push(`${labels[index]}：${message}`)
    }
  })

  if (results[0].status === 'rejected') {
    fatalError.value = results[0].reason?.message || '总览统计加载失败'
    app.toastMsg(fatalError.value, 'error')
  }
  loading.value = false
}

function setDays(day) {
  if (days.value === day) return
  days.value = day
  load()
}

watch(() => props.refreshKey, () => load())

onMounted(() => load())
</script>