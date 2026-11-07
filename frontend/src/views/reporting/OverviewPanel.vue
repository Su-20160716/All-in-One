<template>
  <section class="space-y-3">
    <!-- 工具条 -->
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <div class="flex items-center gap-1">
        <button
          v-for="d in DAY_OPTIONS"
          :key="d.value"
          class="rounded-pill px-2.5 py-1 text-[12px] transition-colors"
          :class="days === d.value ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
          @click="setDays(d.value)"
        >最近 {{ d.label }}</button>
      </div>
      <span class="tag">报表 {{ reportCountText }}</span>
      <span class="tag">样本 {{ metrics.sample_size || 0 }} 次</span>
      <span v-if="metrics.generated_at" class="hidden text-[11px] text-ink-400 sm:inline">
        统计时间 {{ fmtDT(metrics.generated_at) }}
      </span>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <button class="btn-ghost" :disabled="loading" @click="loadAll">{{ loading ? '加载中…' : '刷新' }}</button>
        <button class="btn-outline" @click="emit('go', 'reports')">查看报表</button>
      </div>
    </div>

    <!-- 指标接口不可用：降级为空态，但保留报表数与最近流水 -->
    <div
      v-if="unavailable"
      class="card flex flex-wrap items-center gap-2 border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800"
    >
      <span class="min-w-0 flex-1">{{ unavailable }}。已降级为空态展示，报表与流水仍可单独访问。</span>
      <button class="btn-outline px-2 py-0.5" @click="loadAll">重试</button>
    </div>

    <!-- 错误：可重试 -->
    <div
      v-else-if="error"
      class="card flex flex-wrap items-center gap-2 border-rose-200 bg-rose-50 p-3 text-[12px] text-rose-600"
    >
      <span class="min-w-0 flex-1">指标加载失败：{{ error }}</span>
      <button class="btn-outline px-2 py-0.5" @click="loadAll">重试</button>
    </div>

    <!-- 五个核心指标 -->
    <StatsGrid :items="statItems" :columns="5" :loading="loading && !loadedOnce" :skeleton-count="5" />

    <!-- 趋势与构成 -->
    <div class="grid gap-3 lg:grid-cols-3">
      <SectionCard
        class="lg:col-span-2"
        title="执行趋势"
        :subtitle="`按天聚合最近 ${days} 天的执行量、失败量与平均耗时`"
      >
        <template #actions>
          <span class="tag">执行 {{ metrics.total || 0 }}</span>
          <span class="tag bg-rose-50 text-rose-600">失败 {{ metrics.failed || 0 }}</span>
        </template>
        <div v-if="loading && !loadedOnce" class="grid h-[240px] place-items-center text-[12px] text-ink-400">
          趋势加载中…
        </div>
        <LineChart
          v-else
          :series="trendSeries"
          :labels="trendLabels"
          :height="240"
          :max-x-labels="10"
          aria-label="执行趋势折线图"
          empty-text="窗口内还没有执行记录，去报表页执行一次即可生成趋势"
        />
        <template #footer>
          <div class="flex flex-wrap items-center gap-3">
            <span>平均耗时 {{ fmtMs(metrics.duration_avg_ms) }}</span>
            <span>P50 {{ fmtMs(metrics.duration_p50_ms) }}</span>
            <span>P95 {{ fmtMs(metrics.duration_p95_ms) }}</span>
            <span>最长 {{ fmtMs(metrics.duration_max_ms) }}</span>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="触发方式" subtitle="缓存命中率反映结果复用效率">
        <template #actions>
          <span class="tag">缓存 {{ fmtPct(metrics.cache_hit_rate_pct) }}</span>
        </template>
        <DonutChart
          :data="triggerData"
          :size="150"
          :thickness="16"
          center-label="执行总量"
          :center-value="String(metrics.total || 0)"
          legend-position="bottom"
          empty-text="暂无触发记录"
          aria-label="触发方式占比图"
        />
      </SectionCard>
    </div>

    <!-- 失败原因与热门报表 -->
    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="失败原因分布" subtitle="按错误文案聚合，最多展示前 10 条">
        <template #actions>
          <span class="tag bg-rose-50 text-rose-600">失败 {{ metrics.failed || 0 }}</span>
        </template>
        <BarChart
          :data="failureBars"
          horizontal
          :show-value="true"
          empty-text="窗口内没有失败记录"
        />
        <ul v-if="failureRows.length" class="mt-2 divide-y divide-ink-50">
          <li v-for="row in failureRows.slice(0, 5)" :key="`${row.report_id}-${row.error}`" class="flex items-center gap-2 py-1.5 text-[11px]">
            <span class="min-w-0 flex-1 truncate text-ink-500" :title="row.error">{{ row.name || '未知报表' }}</span>
            <span class="shrink-0 text-ink-400">{{ shortText(row.error, 28) }}</span>
            <span class="shrink-0 font-medium text-rose-600">{{ row.count }}</span>
          </li>
        </ul>
        <template #footer>
          <button class="text-brand-600" @click="emit('go', 'reports')">前往报表页排查</button>
        </template>
      </SectionCard>

      <SectionCard title="热门报表 TOP" subtitle="按窗口内执行次数排序">
        <template #actions>
          <span class="tag">{{ topReports.length }} 张</span>
        </template>
        <BarChart
          :data="topBars"
          horizontal
          empty-text="窗口内还没有报表执行记录"
        />
        <template #footer>
          <button class="text-brand-600" @click="emit('go', 'reports')">查看全部报表</button>
        </template>
      </SectionCard>
    </div>

    <!-- 明细表 -->
    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="热门报表明细" subtitle="执行次数、失败率与平均耗时">
        <div v-if="loading && !loadedOnce" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!topReports.length" class="py-8 text-center text-[12px] text-ink-400">
          暂无执行数据，执行任意报表后会出现在这里
        </div>
        <div v-else class="overflow-auto">
          <table class="w-full min-w-[420px]">
            <thead class="bg-ink-50">
              <tr>
                <th class="th">报表</th>
                <th class="th text-right">执行</th>
                <th class="th text-right">失败率</th>
                <th class="th text-right">平均耗时</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in topReports" :key="row.report_id">
                <td class="td">
                  <div class="truncate text-[12px] text-ink-800" :title="row.name">{{ row.name || '未命名报表' }}</div>
                  <div class="font-mono text-[10px] text-ink-400">{{ row.code || '—' }}</div>
                </td>
                <td class="td text-right tabular-nums">{{ row.runs }}</td>
                <td class="td text-right tabular-nums" :class="Number(row.failure_rate_pct) > 0 ? 'text-rose-600' : 'text-ink-500'">
                  {{ fmtPct(row.failure_rate_pct) }}
                </td>
                <td class="td text-right tabular-nums">{{ fmtMs(row.avg_ms) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="最慢报表" subtitle="成功执行的平均耗时倒序">
        <div v-if="loading && !loadedOnce" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!slowestReports.length" class="py-8 text-center text-[12px] text-ink-400">暂无成功的执行样本</div>
        <div v-else class="overflow-auto">
          <table class="w-full min-w-[360px]">
            <thead class="bg-ink-50">
              <tr>
                <th class="th">报表</th>
                <th class="th text-right">样本</th>
                <th class="th text-right">平均耗时</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in slowestReports" :key="row.report_id">
                <td class="td">
                  <span class="block truncate text-[12px] text-ink-800" :title="row.name">{{ row.name || '未命名报表' }}</span>
                </td>
                <td class="td text-right tabular-nums">{{ row.runs }}</td>
                <td class="td text-right tabular-nums">{{ fmtMs(row.avg_ms) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>

    <!-- 最近执行流水 -->
    <SectionCard title="最近执行" subtitle="全局执行流水前 10 条，含失败原因">
      <template #actions>
        <button class="text-[11px] text-brand-600" :disabled="runsLoading" @click="loadRuns">
          {{ runsLoading ? '加载中…' : '刷新流水' }}
        </button>
      </template>
      <div v-if="runsLoading && !runs.length" class="py-8 text-center text-[12px] text-ink-400">流水加载中…</div>
      <div v-else-if="runsError" class="flex items-center gap-2 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1 truncate">{{ runsError }}</span>
        <button class="shrink-0 font-medium" @click="loadRuns">重试</button>
      </div>
      <div v-else-if="!runs.length" class="py-8 text-center text-[12px] text-ink-400">
        还没有执行记录，去报表页点击「执行」生成第一条流水
      </div>
      <div v-else class="overflow-auto">
        <table class="w-full min-w-[720px]">
          <thead class="bg-ink-50">
            <tr>
              <th class="th">报表</th>
              <th class="th w-20">触发</th>
              <th class="th w-20">状态</th>
              <th class="th w-24 text-right">耗时</th>
              <th class="th w-20 text-right">行数</th>
              <th class="th w-36">开始时间</th>
              <th class="th">错误</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="run in runs" :key="run.id">
              <td class="td">
                <span class="block max-w-[200px] truncate text-[12px] text-ink-800" :title="run.report_name">{{ run.report_name || '—' }}</span>
              </td>
              <td class="td"><span class="tag">{{ triggerLabel(run.trigger) }}</span></td>
              <td class="td">
                <span class="tag" :class="statusTone(run.status)">{{ runStatusLabel(run.status) }}</span>
              </td>
              <td class="td text-right tabular-nums">{{ fmtMs(run.duration_ms) }}</td>
              <td class="td text-right tabular-nums">{{ fmtInt(run.row_count) }}</td>
              <td class="td text-[11px] text-ink-500">{{ fmtDT(run.started_at || run.created_at) }}</td>
              <td class="td">
                <span v-if="run.error" class="block max-w-[240px] truncate text-[11px] text-rose-500" :title="run.error">
                  {{ run.error }}
                </span>
                <span v-else class="text-[11px] text-ink-300">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </SectionCard>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { reportingApi } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import SectionCard from '../../components/platform/SectionCard.vue'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import LineChart from '../../components/platform/LineChart.vue'
import BarChart from '../../components/platform/BarChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])
const app = useAppStore()

const DAY_OPTIONS = [
  { value: 7, label: '7 天' },
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
]

const days = ref(30)
const loading = ref(false)
const loadedOnce = ref(false)
const error = ref('')
const unavailable = ref('')
const metrics = ref({})
const reportCount = ref(null)
const runs = ref([])
const runsLoading = ref(false)
const runsError = ref('')

const TRIGGER_LABELS = {
  manual: '手动执行',
  schedule: '计划任务',
  api: '接口调用',
  cache: '缓存命中',
  share: '分享访问',
}

function isUnavailable(e) {
  const status = Number(e?.status || e?.response?.status || 0)
  const message = String(e?.message || '')
  return status === 404 || status === 405 || /not found|method not allowed|405/i.test(message)
}

function fmtInt(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN')
}

function fmtMs(value) {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '—'
  if (n < 1000) return `${Math.round(n)} ms`
  if (n < 60000) return `${(n / 1000).toFixed(2)} s`
  return `${(n / 60000).toFixed(1)} min`
}

function fmtPct(value, digits = 1) {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '—'
  return `${n.toFixed(digits)}%`
}

function pad(n) {
  return String(n).padStart(2, '0')
}

function fmtDT(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtDay(value) {
  if (!value) return '—'
  const text = String(value)
  return text.length >= 10 ? text.slice(5, 10) : text
}

function shortText(value, max = 24) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text) return '—'
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function triggerLabel(value) {
  return TRIGGER_LABELS[value] || value || '手动执行'
}

function runStatusLabel(value) {
  const map = { running: '执行中', success: '成功', failed: '失败' }
  return map[value] || value || '未知'
}

function statusTone(value) {
  if (value === 'success') return 'bg-emerald-50 text-emerald-700'
  if (value === 'failed') return 'bg-rose-50 text-rose-600'
  if (value === 'running') return 'bg-amber-50 text-amber-700'
  return 'bg-ink-100 text-ink-600'
}

const reportCountText = computed(() => (reportCount.value === null ? '—' : fmtInt(reportCount.value)))

const todayKey = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
})

const todayRuns = computed(() => {
  const trend = Array.isArray(metrics.value.trend) ? metrics.value.trend : []
  const row = trend.find((item) => String(item.date || '').slice(0, 10) === todayKey.value)
  return row ? Number(row.total) || 0 : 0
})

const statItems = computed(() => [
  {
    key: 'reports',
    label: '报表数',
    value: reportCount.value === null ? '—' : fmtInt(reportCount.value),
    hint: '当前可见范围',
    footer: '含草稿、已发布与归档',
  },
  {
    key: 'today',
    label: '今日执行',
    value: unavailable.value ? '—' : fmtInt(todayRuns.value),
    hint: `窗口内 ${fmtInt(metrics.value.total || 0)} 次`,
    footer: `失败 ${fmtInt(metrics.value.failed || 0)} 次`,
  },
  {
    key: 'success',
    label: '成功率',
    value: unavailable.value ? '—' : fmtPct(metrics.value.success_rate_pct),
    hint: metrics.value.success_rate_pct === null ? '暂无完成样本' : `成功 ${fmtInt(metrics.value.success || 0)} 次`,
    footer: `完成样本 ${fmtInt((metrics.value.success || 0) + (metrics.value.failed || 0))}`,
  },
  {
    key: 'avg',
    label: '平均耗时',
    value: unavailable.value ? '—' : fmtMs(metrics.value.duration_avg_ms),
    hint: `P50 ${fmtMs(metrics.value.duration_p50_ms)}`,
    footer: `样本 ${fmtInt(metrics.value.sample_size || 0)} 次`,
  },
  {
    key: 'p95',
    label: 'P95 耗时',
    value: unavailable.value ? '—' : fmtMs(metrics.value.duration_p95_ms),
    hint: `最长 ${fmtMs(metrics.value.duration_max_ms)}`,
    footer: '95% 的执行不超过该值',
  },
])

const trendRows = computed(() => (Array.isArray(metrics.value.trend) ? metrics.value.trend : []))
const trendLabels = computed(() => trendRows.value.map((row) => fmtDay(row.date)))
const trendSeries = computed(() => [
  { name: '执行量', data: trendRows.value.map((row) => Number(row.total) || 0) },
  { name: '失败量', data: trendRows.value.map((row) => Number(row.failed) || 0) },
])

const triggerData = computed(() => {
  const triggers = metrics.value.triggers || {}
  return Object.entries(triggers).map(([key, value]) => ({
    label: triggerLabel(key),
    value: Number(value) || 0,
  }))
})

const failureRows = computed(() => (Array.isArray(metrics.value.failure_reasons) ? metrics.value.failure_reasons : []))
const failureBars = computed(() => failureRows.value.map((row) => ({
  label: shortText(row.error, 22),
  value: Number(row.count) || 0,
})))

const topReports = computed(() => (Array.isArray(metrics.value.top_reports) ? metrics.value.top_reports : []))
const topBars = computed(() => topReports.value.map((row) => ({
  label: row.name || row.code || '未命名报表',
  value: Number(row.runs) || 0,
})))

const slowestReports = computed(() => (Array.isArray(metrics.value.slowest_reports) ? metrics.value.slowest_reports : []))

async function loadMetrics() {
  const data = await reportingApi.get(`metrics/overview/?days=${days.value}`)
  metrics.value = data && typeof data === 'object' ? data : {}
}

async function loadReportCount() {
  const page = await reportingApi.list('reports/', { page: 1, page_size: 1 })
  reportCount.value = Number(page.count) || 0
}

async function loadRuns() {
  runsLoading.value = true
  runsError.value = ''
  try {
    const page = await reportingApi.list('runs/', { page: 1, page_size: 10 })
    runs.value = page.items
  } catch (e) {
    runs.value = []
    runsError.value = isUnavailable(e) ? '执行流水接口不可用（404/405）' : (e?.message || '流水加载失败')
  } finally {
    runsLoading.value = false
  }
}

async function loadAll() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  const results = await Promise.allSettled([loadMetrics(), loadReportCount(), loadRuns()])
  const [metricResult, countResult] = results
  if (metricResult.status === 'rejected') {
    const reason = metricResult.reason
    metrics.value = {}
    if (isUnavailable(reason)) {
      unavailable.value = '执行指标接口不存在或方法不可用（404/405）'
    } else {
      error.value = reason?.message || '指标加载失败'
      app.toastMsg(error.value, 'error')
    }
  }
  if (countResult.status === 'rejected') {
    reportCount.value = null
  }
  loadedOnce.value = true
  loading.value = false
}

function setDays(value) {
  if (days.value === value) return
  days.value = value
  loadAll()
}

watch(() => props.reloadToken, () => loadAll())
onMounted(loadAll)
</script>