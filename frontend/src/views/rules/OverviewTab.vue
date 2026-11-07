<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1.5">
        <span class="text-[12px] text-ink-500">统计窗口</span>
        <button
          v-for="d in DAY_OPTIONS"
          :key="d"
          class="rounded-pill px-2.5 py-1 text-[12px]"
          :class="days === d ? 'bg-ink-700 text-white' : 'bg-white text-ink-500 border border-ink-200 hover:bg-ink-50'"
          @click="days = d"
        >
          {{ d }} 天
        </button>
        <span class="ml-1 tag">{{ scopeLabel }}</span>
      </div>
      <div class="flex items-center gap-1.5">
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'rulesets')">规则集</button>
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'tables')">决策表</button>
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'simulate')">仿真评估</button>
        <button class="btn-outline py-1 text-[12px]" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '刷新统计' }}
        </button>
      </div>
    </div>

    <div
      v-if="error"
      class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
    >
      <span class="min-w-0 flex-1">{{ error }}</span>
      <button class="shrink-0 font-medium" @click="load">重试</button>
    </div>

    <div v-else-if="notice" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      {{ notice }}
    </div>

    <StatsGrid :items="kpis" :loading="loading" :skeleton-count="5" gap="normal" />

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="规则命中 TOP" :subtitle="`窗口 ${days} 天，共采样 ${sampledEvaluations} 条评估`">
        <template #actions>
          <span class="tag">前 {{ topRules.length }} 条</span>
        </template>
        <div v-if="loading && !topRules.length" class="py-10 text-center text-[12px] text-ink-400">
          加载中…
        </div>
        <div v-else-if="!topRules.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          窗口内暂无规则命中记录
        </div>
        <template v-else>
          <BarChart :data="topRuleBars" horizontal :height="188" />
          <div class="mt-3 divide-y divide-ink-50">
            <div
              v-for="(item, index) in topRules"
              :key="item.name"
              class="flex items-center gap-2 py-1.5 text-[12px]"
            >
              <span class="w-5 shrink-0 text-ink-400">{{ index + 1 }}</span>
              <span class="min-w-0 flex-1 truncate text-ink-700">{{ item.name }}</span>
              <span class="shrink-0 text-ink-500">窗口 {{ item.hits }} 次</span>
              <span class="w-16 shrink-0 text-right text-ink-400">累计 {{ item.lifetime_hits }}</span>
            </div>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="失败原因分布" :subtitle="`动作失败 ${failureTotal} 次，评估异常 ${evaluationErrorTotal} 条`">
        <template #actions>
          <button class="btn-ghost py-1 text-[11px]" @click="emit('go', 'analytics')">查看日志</button>
        </template>
        <div v-if="loading && !failureBars.length" class="py-10 text-center text-[12px] text-ink-400">
          加载中…
        </div>
        <div v-else-if="!failureBars.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          窗口内没有失败记录，执行链路稳定
        </div>
        <div v-else class="flex flex-wrap items-center gap-4">
          <DonutChart
            :data="failureBars"
            :size="168"
            center-label="失败次数"
            legend-position="right"
            :format="formatCount"
          />
          <ul class="min-w-0 flex-1 space-y-1.5">
            <li
              v-for="item in topErrors"
              :key="item.error"
              class="flex items-start gap-2 text-[12px]"
            >
              <span class="mt-0.5 shrink-0 rounded-pill bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600">
                {{ item.count }}
              </span>
              <span class="min-w-0 flex-1 break-all text-ink-600">{{ item.error }}</span>
            </li>
            <li v-if="!topErrors.length" class="text-[12px] text-ink-400">暂无错误原文样本</li>
          </ul>
        </div>
      </SectionCard>
    </div>

    <SectionCard title="评估趋势" :subtitle="`按日聚合评估量、命中量与异常量，窗口 ${days} 天`">
      <template #actions>
        <div class="flex items-center gap-2">
          <MetricDelta :value="hitRateDelta" mode="percent" label="较前一日命中率" />
          <span class="tag">平均 {{ fmtMs(overview?.duration?.avg) }}</span>
        </div>
      </template>
      <div v-if="loading && !trendItems.length" class="py-14 text-center text-[12px] text-ink-400">
        加载中…
      </div>
      <div v-else-if="!trendItems.length" class="rounded-control border border-dashed border-ink-200 py-14 text-center text-[12px] text-ink-400">
        暂无趋势数据
      </div>
      <LineChart
        v-else
        :series="trendSeries"
        :labels="trendLabels"
        :height="230"
        :format="formatCount"
      />
    </SectionCard>

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="耗时分位" subtitle="基于窗口内评估记录的 duration_ms 统计">
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div v-for="p in latencyCells" :key="p.label" class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">{{ p.label }}</div>
            <div class="mt-0.5 text-[15px] font-semibold text-ink-800">{{ p.value }}</div>
            <div class="text-[10px] text-ink-400">毫秒</div>
          </div>
        </div>
        <div class="mt-3">
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">最慢规则集</div>
          <div v-if="!slowestRulesets.length" class="py-3 text-center text-[12px] text-ink-400">
            暂无足够样本
          </div>
          <div v-else class="divide-y divide-ink-50">
            <div
              v-for="row in slowestRulesets"
              :key="row.ruleset_code"
              class="flex items-center gap-2 py-1.5 text-[12px]"
            >
              <span class="min-w-0 flex-1 truncate font-mono text-ink-700">{{ row.ruleset_code }}</span>
              <span class="text-ink-400">p50 {{ fmtMs(row.p50) }}</span>
              <span class="text-ink-500">p99 {{ fmtMs(row.p99) }}</span>
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="规则资产" subtitle="规则、测试用例与冲突的整体健康度">
        <div class="grid grid-cols-2 gap-2">
          <div class="rounded-control border border-ink-100 px-3 py-2">
            <div class="text-[11px] text-ink-400">规则总数</div>
            <div class="text-[16px] font-semibold text-ink-800">{{ formatCount(overview?.rules) }}</div>
            <div class="text-[11px] text-ink-400">启用 {{ formatCount(overview?.enabled_rules) }}</div>
          </div>
          <div class="rounded-control border border-ink-100 px-3 py-2">
            <div class="text-[11px] text-ink-400">测试用例</div>
            <div class="text-[16px] font-semibold text-ink-800">{{ formatCount(overview?.test_cases) }}</div>
            <div class="text-[11px] text-ink-400">通过 {{ formatCount(overview?.test_passed) }}</div>
          </div>
          <div class="rounded-control border border-ink-100 px-3 py-2">
            <div class="text-[11px] text-ink-400">未解决冲突</div>
            <div class="text-[16px] font-semibold" :class="overview?.open_conflicts ? 'text-rose-600' : 'text-ink-800'">
              {{ formatCount(overview?.open_conflicts) }}
            </div>
            <div class="text-[11px] text-ink-400">待审批 {{ formatCount(overview?.pending_approvals) }}</div>
          </div>
          <div class="rounded-control border border-ink-100 px-3 py-2">
            <div class="text-[11px] text-ink-400">未完成任务</div>
            <div class="text-[16px] font-semibold text-ink-800">{{ formatCount(overview?.open_tasks) }}</div>
            <div class="text-[11px] text-ink-400">用例通过率 {{ fmtPercent(overview?.test_pass_rate) }}</div>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <button class="btn-ghost py-1 text-[11px]" @click="emit('go', 'rulesets')">维护规则</button>
          <button class="btn-ghost py-1 text-[11px]" @click="emit('go', 'simulate')">运行仿真</button>
          <button class="btn-ghost py-1 text-[11px]" @click="emit('go', 'analytics')">排查失败</button>
        </div>
      </SectionCard>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import BarChart from '../../components/platform/BarChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import LineChart from '../../components/platform/LineChart.vue'
import MetricDelta from '../../components/platform/MetricDelta.vue'

const props = defineProps({
  rulesetId: { type: [String, Number], default: '' },
  rulesets: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})

const emit = defineEmits(['go'])
const api = apiFor('rules')
const app = useAppStore()

const DAY_OPTIONS = [7, 14, 30]
const days = ref(7)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const overview = ref(null)
const topRules = ref([])
const sampledEvaluations = ref(0)
const failures = ref(null)
const trendItems = ref([])
const latency = ref(null)

const ACTION_LABELS = {
  set_field: '设置字段',
  notify: '站内通知',
  webhook: 'Webhook',
  approve: '通过决策',
  reject: '驳回决策',
  route: '路由分派',
  create_task: '创建任务',
  score: '评分累加',
  flag: '打标',
}

const EVAL_STATUS_LABELS = {
  error: '执行异常',
  degraded: '降级执行',
  timeout: '执行超时',
}

function formatCount(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0'
  return n.toLocaleString('zh-CN')
}

function fmtPercent(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

function fmtMs(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(n >= 100 ? 0 : 1)} ms`
}

const scopeLabel = computed(() => {
  if (!props.rulesetId) return '全部规则集'
  const found = props.rulesets.find((item) => String(item.id) === String(props.rulesetId))
  return found ? found.name : `规则集 #${props.rulesetId}`
})

const todayEvaluations = computed(() => {
  const last = trendItems.value[trendItems.value.length - 1]
  return last ? last.total : 0
})

const kpis = computed(() => [
  {
    key: 'rulesets',
    label: '规则集数',
    value: formatCount(overview.value?.rulesets),
    hint: `生效中 ${formatCount(overview.value?.active_rulesets)} 个`,
    tone: 'brand',
  },
  {
    key: 'enabled_rules',
    label: '启用规则',
    value: formatCount(overview.value?.enabled_rules),
    hint: `共 ${formatCount(overview.value?.rules)} 条规则`,
    tone: 'emerald',
  },
  {
    key: 'today',
    label: '今日评估',
    value: formatCount(todayEvaluations.value),
    hint: `窗口累计 ${formatCount(overview.value?.evaluations)} 次`,
    tone: 'default',
  },
  {
    key: 'hit_rate',
    label: '命中率',
    value: fmtPercent(overview.value?.hit_rate),
    hint: `未命中 ${formatCount(overview.value?.unmatched)} 次`,
    tone: 'amber',
  },
  {
    key: 'latency',
    label: '平均耗时',
    value: fmtMs(overview.value?.duration?.avg),
    hint: `p95 ${fmtMs(overview.value?.duration?.p95)}`,
    tone: 'rose',
  },
])

const topRuleBars = computed(() =>
  topRules.value.map((item) => ({ label: item.name, value: Number(item.hits) || 0 }))
)

const failureBars = computed(() => {
  const data = failures.value
  if (!data) return []
  const bars = (data.action_failures || []).map((item) => ({
    label: ACTION_LABELS[item.action_type] || item.action_type || '未知动作',
    value: Number(item.count) || 0,
  }))
  for (const item of data.evaluation_status || []) {
    const label = EVAL_STATUS_LABELS[item.status] || item.status
    bars.push({ label, value: Number(item.count) || 0 })
  }
  return bars.filter((item) => item.value > 0)
})

const failureTotal = computed(() => Number(failures.value?.action_failure_total) || 0)

const evaluationErrorTotal = computed(() =>
  (failures.value?.evaluation_status || []).reduce((sum, item) => sum + (Number(item.count) || 0), 0)
)

const topErrors = computed(() => (failures.value?.top_errors || []).slice(0, 8))

const trendLabels = computed(() =>
  trendItems.value.map((item) => String(item.date || '').slice(5))
)

const trendSeries = computed(() => [
  { name: '评估量', color: '#0ea5e9', data: trendItems.value.map((item) => Number(item.total) || 0) },
  { name: '命中量', color: '#10b981', data: trendItems.value.map((item) => Number(item.matched) || 0) },
  { name: '异常量', color: '#f43f5e', data: trendItems.value.map((item) => Number(item.errors) || 0) },
])

const hitRateDelta = computed(() => {
  const items = trendItems.value
  if (items.length < 2) return 0
  const last = items[items.length - 1]
  const prev = items[items.length - 2]
  const rate = (row) => (row.total ? (row.matched / row.total) * 100 : 0)
  return Number((rate(last) - rate(prev)).toFixed(1))
})

const latencyCells = computed(() => {
  const data = latency.value?.overall || overview.value?.duration || {}
  return [
    { label: 'P50', value: fmtMs(data.p50) },
    { label: 'P90', value: fmtMs(data.p90) },
    { label: 'P95', value: fmtMs(data.p95) },
    { label: 'P99', value: fmtMs(data.p99) },
  ]
})

const slowestRulesets = computed(() => (latency.value?.slowest_rulesets || []).slice(0, 6))

function isMissingEndpoint(e) {
  const status = e?.response?.status
  return status === 404 || status === 405 || status === 501
}

function scopeParams() {
  const params = { days: days.value }
  if (props.rulesetId) params.ruleset_id = props.rulesetId
  return params
}

async function load() {
  if (!api) {
    error.value = '规则引擎接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  const params = scopeParams()
  const results = await Promise.allSettled([
    api.get(`stats/overview/?days=${params.days}${props.rulesetId ? `&ruleset_id=${props.rulesetId}` : ''}`),
    api.get(`stats/top-rules/?days=${params.days}&limit=10${props.rulesetId ? `&ruleset_id=${props.rulesetId}` : ''}`),
    api.get(`stats/failures/?days=${params.days}${props.rulesetId ? `&ruleset_id=${props.rulesetId}` : ''}`),
    api.get(`stats/trend/?days=${params.days}${props.rulesetId ? `&ruleset_id=${props.rulesetId}` : ''}`),
    api.get(`stats/latency/?days=${params.days}${props.rulesetId ? `&ruleset_id=${props.rulesetId}` : ''}`),
  ])

  const [overviewRes, topRes, failureRes, trendRes, latencyRes] = results
  let missing = 0
  let firstError = ''

  if (overviewRes.status === 'fulfilled') {
    overview.value = overviewRes.value || null
  } else {
    overview.value = null
    if (isMissingEndpoint(overviewRes.reason)) missing += 1
    else firstError = overviewRes.reason?.message || '概览统计加载失败'
  }

  if (topRes.status === 'fulfilled') {
    topRules.value = topRes.value?.items || []
    sampledEvaluations.value = Number(topRes.value?.sampled_evaluations) || 0
  } else {
    topRules.value = []
    if (isMissingEndpoint(topRes.reason)) missing += 1
    else firstError = firstError || (topRes.reason?.message || '命中排行加载失败')
  }

  if (failureRes.status === 'fulfilled') {
    failures.value = failureRes.value || null
  } else {
    failures.value = null
    if (isMissingEndpoint(failureRes.reason)) missing += 1
    else firstError = firstError || (failureRes.reason?.message || '失败原因加载失败')
  }

  if (trendRes.status === 'fulfilled') {
    trendItems.value = trendRes.value?.items || []
  } else {
    trendItems.value = []
    if (isMissingEndpoint(trendRes.reason)) missing += 1
    else firstError = firstError || (trendRes.reason?.message || '评估趋势加载失败')
  }

  if (latencyRes.status === 'fulfilled') {
    latency.value = latencyRes.value || null
  } else {
    latency.value = null
    if (isMissingEndpoint(latencyRes.reason)) missing += 1
    else firstError = firstError || (latencyRes.reason?.message || '耗时统计加载失败')
  }

  if (firstError) {
    error.value = firstError
  } else if (missing) {
    notice.value = '部分统计接口在当前后端版本不可用，已隐藏对应数据块'
  }
  loading.value = false

  if (firstError) app.toastMsg(firstError, 'error')
}

watch(
  () => [props.refreshKey, props.rulesetId, days.value],
  () => load()
)

onMounted(load)
</script>