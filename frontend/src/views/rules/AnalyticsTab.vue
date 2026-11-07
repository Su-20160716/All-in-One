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
      <div class="flex items-center gap-2">
        <MetricDelta :value="hitRateDelta" mode="percent" label="命中率较前一日" />
        <button class="btn-outline py-1 text-[12px]" :disabled="loading" @click="loadAll">
          {{ loading ? '加载中…' : '刷新分析' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
      <span class="min-w-0 flex-1">{{ error }}</span>
      <button class="shrink-0 font-medium" @click="loadAll">重试</button>
    </div>
    <div v-else-if="notice" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      {{ notice }}
    </div>

    <div class="grid gap-3 lg:grid-cols-3">
      <SectionCard class="lg:col-span-2" title="命中率趋势" :subtitle="`近 ${days} 天每日命中率与评估量`">
        <div v-if="loading && !trend.length" class="py-14 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!trend.length" class="rounded-control border border-dashed border-ink-200 py-14 text-center text-[12px] text-ink-400">
          暂无趋势数据
        </div>
        <template v-else>
          <LineChart
            :series="rateSeries"
            :labels="trendLabels"
            :height="220"
            :format="(v) => `${Number(v).toFixed(0)}%`"
            :start-at-zero="false"
          />
          <div class="mt-2 grid grid-cols-3 gap-2">
            <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
              <div class="text-[10px] text-ink-400">窗口评估量</div>
              <div class="text-[15px] font-semibold text-ink-800">{{ formatCount(windowTotal) }}</div>
            </div>
            <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
              <div class="text-[10px] text-ink-400">窗口命中量</div>
              <div class="text-[15px] font-semibold text-emerald-600">{{ formatCount(windowMatched) }}</div>
            </div>
            <div class="rounded-control bg-ink-50/60 px-2 py-1.5">
              <div class="text-[10px] text-ink-400">窗口异常量</div>
              <div class="text-[15px] font-semibold" :class="windowErrors ? 'text-rose-600' : 'text-ink-800'">
                {{ formatCount(windowErrors) }}
              </div>
            </div>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="动作类型分布" subtitle="基于最近 200 条动作执行日志">
        <div v-if="logsLoading && !logs.length" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!actionBars.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          暂无动作执行日志
        </div>
        <DonutChart
          v-else
          :data="actionBars"
          :size="170"
          center-label="执行次数"
          legend-position="bottom"
          :format="formatCount"
        />
        <div class="mt-2 text-center text-[11px] text-ink-400">
          共 {{ formatCount(actionTotal) }} 次动作执行
        </div>
      </SectionCard>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="规则命中排行" :subtitle="`窗口内命中次数与全生命周期计数`">
        <template #actions>
          <span class="tag">前 {{ topRules.length }} 条</span>
        </template>
        <div v-if="loading && !topRules.length" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!topRules.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          窗口内没有规则命中
        </div>
        <template v-else>
          <BarChart :data="topRuleBars" horizontal :height="170" />
          <div class="mt-2 max-h-[180px] overflow-auto">
            <table class="w-full">
              <thead class="bg-ink-50/60">
                <tr>
                  <th class="th">规则</th>
                  <th class="th text-right">窗口命中</th>
                  <th class="th text-right">累计命中</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="item in topRules" :key="item.name">
                  <td class="td max-w-[220px] truncate">{{ item.name }}</td>
                  <td class="td text-right">{{ formatCount(item.hits) }}</td>
                  <td class="td text-right text-ink-500">{{ formatCount(item.lifetime_hits) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="失败原因" :subtitle="`动作失败 ${formatCount(failureTotal)} 次，评估异常 ${formatCount(evaluationErrorTotal)} 条`">
        <div v-if="loading && !failures" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!failures" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          暂无失败统计
        </div>
        <template v-else>
          <div v-if="failureBars.length" class="mb-2">
            <BarChart :data="failureBars" horizontal :height="110" />
          </div>
          <div class="mb-2 flex flex-wrap gap-1">
            <span v-for="item in failures.evaluation_status || []" :key="item.status" class="tag bg-rose-50 text-rose-600">
              {{ evalStatusLabel(item.status) }} {{ item.count }}
            </span>
            <span v-if="!failures.evaluation_status?.length" class="tag">没有评估异常状态</span>
          </div>
          <div class="max-h-[170px] overflow-auto">
            <div v-if="!topErrors.length" class="py-4 text-center text-[12px] text-ink-400">没有错误原文样本</div>
            <div v-for="item in topErrors" :key="item.error" class="flex items-start gap-2 border-b border-ink-50 py-1.5 last:border-0">
              <span class="shrink-0 rounded-pill bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-600">{{ item.count }}</span>
              <span class="min-w-0 flex-1 break-all text-[12px] text-ink-600">{{ item.error }}</span>
            </div>
          </div>
        </template>
      </SectionCard>
    </div>

    <!-- 执行日志 -->
    <div class="card overflow-hidden">
      <div class="flex flex-wrap items-end gap-2 border-b border-ink-100 p-3">
        <div class="mr-auto">
          <div class="text-[13px] font-medium text-ink-700">执行日志</div>
          <div class="text-[11px] text-ink-400">按规则、动作类型、状态与错误原文检索</div>
        </div>
        <label class="flex w-[160px] flex-col gap-1 text-[11px] text-ink-500">
          关键词
          <input v-model="logQ" class="input py-1" placeholder="规则名 / 错误" @keyup.enter="applyLogFilters" />
        </label>
        <label class="flex w-[120px] flex-col gap-1 text-[11px] text-ink-500">
          状态
          <select v-model="logStatus" class="input py-1" @change="applyLogFilters">
            <option value="">全部</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="skipped">跳过</option>
          </select>
        </label>
        <label class="flex w-[140px] flex-col gap-1 text-[11px] text-ink-500">
          动作类型
          <select v-model="logActionType" class="input py-1" @change="applyLogFilters">
            <option value="">全部动作</option>
            <option v-for="item in ACTION_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <button class="btn-outline py-1 text-[12px]" :disabled="logsLoading" @click="applyLogFilters">查询</button>
        <button class="btn-ghost py-1 text-[12px]" :disabled="logsLoading" @click="resetLogFilters">重置</button>
      </div>

      <div v-if="logNotice" class="bg-amber-50 px-3 py-2 text-[12px] text-amber-700">{{ logNotice }}</div>
      <div v-if="logsLoading && !logs.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="logsError" class="flex items-center gap-3 bg-rose-50 px-3 py-3 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ logsError }}</span>
        <button class="shrink-0 font-medium" @click="loadLogs">重试</button>
      </div>
      <div v-else-if="!logs.length" class="px-3 py-12 text-center text-[12px] text-ink-400">
        没有符合条件的执行日志
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[940px]">
          <thead class="bg-ink-50/60">
            <tr>
              <th class="th">时间</th>
              <th class="th">规则</th>
              <th class="th">动作</th>
              <th class="th">状态</th>
              <th class="th">耗时</th>
              <th class="th">重试</th>
              <th class="th">错误</th>
              <th class="th">评估</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in logs" :key="row.id" class="hover:bg-ink-50/50">
              <td class="td w-32 text-[11px] text-ink-500">{{ fmtDate(row.created_at, true) }}</td>
              <td class="td max-w-[200px] truncate">{{ row.rule_name || '—' }}</td>
              <td class="td"><span class="tag">{{ actionLabel(row.action_type) }}</span></td>
              <td class="td">
                <span class="tag" :class="logStatusClass(row.status)">{{ logStatusLabel(row.status) }}</span>
              </td>
              <td class="td text-[12px]">{{ fmtMs(row.duration_ms) }}</td>
              <td class="td text-[12px]">{{ row.retries || 0 }}</td>
              <td class="td max-w-[220px] truncate text-[11px] text-ink-500">{{ row.error || '—' }}</td>
              <td class="td text-[11px] text-ink-400">#{{ row.evaluation_id || '—' }}</td>
              <td class="td text-right">
                <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="openLog(row)">详情</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex items-center justify-between border-t border-ink-100 px-3 py-2">
        <span class="text-[11px] text-ink-400">共 {{ logTotal }} 条 · 每页 {{ logPageSize }} 条</span>
        <div class="flex items-center gap-1">
          <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="logPage <= 1 || logsLoading" @click="goLogPage(logPage - 1)">上一页</button>
          <span class="px-2 text-[12px] text-ink-500">{{ logPage }} / {{ logPages }}</span>
          <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="logPage >= logPages || logsLoading" @click="goLogPage(logPage + 1)">下一页</button>
        </div>
      </div>
    </div>

    <!-- 日志详情 -->
    <Modal v-model="logShow" :title="`执行日志 #${logDetail?.id || ''}`" width="720px">
      <div v-if="logDetailLoading" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="logDetailError" class="flex items-center gap-2 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ logDetailError }}</span>
        <button class="shrink-0 font-medium" @click="reloadLog">重试</button>
      </div>
      <template v-else-if="logDetail">
        <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
          <div class="text-ink-400">规则</div>
          <div class="text-ink-700">{{ logDetail.rule_name || '—' }}</div>
          <div class="text-ink-400">动作类型</div>
          <div class="text-ink-700">{{ actionLabel(logDetail.action_type) }}</div>
          <div class="text-ink-400">状态</div>
          <div>
            <span class="tag" :class="logStatusClass(logDetail.status)">{{ logStatusLabel(logDetail.status) }}</span>
          </div>
          <div class="text-ink-400">耗时</div>
          <div class="text-ink-700">{{ fmtMs(logDetail.duration_ms) }}（重试 {{ logDetail.retries || 0 }} 次）</div>
          <div class="text-ink-400">评估记录</div>
          <div class="text-ink-700">#{{ logDetail.evaluation_id || '—' }}</div>
          <div class="text-ink-400">发生时间</div>
          <div class="text-ink-700">{{ fmtDate(logDetail.created_at, true) }}</div>
          <div class="text-ink-400">错误</div>
          <div class="break-all text-rose-600">{{ logDetail.error || '—' }}</div>
        </div>
        <div class="mt-3">
          <div class="mb-1 text-[12px] font-medium text-ink-600">执行明细</div>
          <pre class="max-h-[280px] overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ pretty(logDetail.detail) }}</pre>
        </div>
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Modal from '../../components/Modal.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import LineChart from '../../components/platform/LineChart.vue'
import BarChart from '../../components/platform/BarChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import MetricDelta from '../../components/platform/MetricDelta.vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { formatDate } from '../../composables/useDomainResource'

const props = defineProps({
  rulesetId: { type: [String, Number], default: '' },
  rulesets: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})

const api = apiFor('rules')
const app = useAppStore()

const DAY_OPTIONS = [7, 14, 30]
const days = ref(7)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const trend = ref([])
const topRules = ref([])
const failures = ref(null)

const ACTION_OPTIONS = [
  { value: 'set_field', label: '设置字段' },
  { value: 'notify', label: '站内通知' },
  { value: 'webhook', label: 'Webhook' },
  { value: 'approve', label: '通过决策' },
  { value: 'reject', label: '驳回决策' },
  { value: 'route', label: '路由分派' },
  { value: 'create_task', label: '创建任务' },
  { value: 'score', label: '评分累加' },
  { value: 'flag', label: '打标' },
]

const logs = ref([])
const logQ = ref('')
const logStatus = ref('')
const logActionType = ref('')
const logPage = ref(1)
const logPageSize = ref(20)
const logTotal = ref(0)
const logsLoading = ref(false)
const logsError = ref('')
const logNotice = ref('')

const logShow = ref(false)
const logDetail = ref(null)
const logDetailId = ref('')
const logDetailLoading = ref(false)
const logDetailError = ref('')

const scopeLabel = computed(() => {
  if (!props.rulesetId) return '全部规则集'
  const found = props.rulesets.find((item) => String(item.id) === String(props.rulesetId))
  return found ? found.name : `规则集 #${props.rulesetId}`
})

const logPages = computed(() => Math.max(1, Math.ceil(logTotal.value / Math.max(1, logPageSize.value))))

const trendLabels = computed(() => trend.value.map((item) => String(item.date || '').slice(5)))

const rateSeries = computed(() => [{
  name: '命中率',
  color: '#10b981',
  area: true,
  data: trend.value.map((item) => (Number(item.total) ? (Number(item.matched) / Number(item.total)) * 100 : 0)),
}])

const windowTotal = computed(() => trend.value.reduce((sum, item) => sum + (Number(item.total) || 0), 0))
const windowMatched = computed(() => trend.value.reduce((sum, item) => sum + (Number(item.matched) || 0), 0))
const windowErrors = computed(() => trend.value.reduce((sum, item) => sum + (Number(item.errors) || 0), 0))

const hitRateDelta = computed(() => {
  if (trend.value.length < 2) return 0
  const last = trend.value[trend.value.length - 1]
  const prev = trend.value[trend.value.length - 2]
  const rate = (row) => (row.total ? (row.matched / row.total) * 100 : 0)
  return Number((rate(last) - rate(prev)).toFixed(1))
})

const topRuleBars = computed(() =>
  topRules.value.map((item) => ({ label: item.name, value: Number(item.hits) || 0 }))
)

const topErrors = computed(() => failures.value?.top_errors || [])

const failureBars = computed(() =>
  (failures.value?.action_failures || []).map((item) => ({
    label: actionLabel(item.action_type),
    value: Number(item.count) || 0,
  }))
)

const failureTotal = computed(() => Number(failures.value?.action_failure_total) || 0)

const evaluationErrorTotal = computed(() =>
  (failures.value?.evaluation_status || []).reduce((sum, item) => sum + (Number(item.count) || 0), 0)
)

const actionBars = computed(() => {
  const counter = {}
  for (const row of logs.value) {
    const key = row.action_type || 'unknown'
    counter[key] = (counter[key] || 0) + 1
  }
  return Object.entries(counter)
    .map(([key, value]) => ({ label: actionLabel(key), value }))
    .sort((a, b) => b.value - a.value)
})

const actionTotal = computed(() => logs.value.length)

function actionLabel(value) {
  const found = ACTION_OPTIONS.find((item) => item.value === value)
  return found ? found.label : value || '未知动作'
}

function evalStatusLabel(value) {
  const map = { error: '执行异常', degraded: '降级', timeout: '超时' }
  return map[value] || value
}

function logStatusLabel(value) {
  const map = { success: '成功', failed: '失败', skipped: '跳过' }
  return map[value] || value || '—'
}

function logStatusClass(value) {
  const map = {
    success: 'bg-emerald-50 text-emerald-600',
    failed: 'bg-rose-50 text-rose-600',
    skipped: 'bg-ink-100 text-ink-500',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

function formatCount(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0'
  return n.toLocaleString('zh-CN')
}

function fmtMs(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(n >= 100 ? 0 : 1)} ms`
}

function fmtDate(value, withTime = false) {
  return formatDate(value, withTime)
}

function pretty(value) {
  if (value === null || value === undefined) return '—'
  try {
    return JSON.stringify(value, null, 2)
  } catch (e) {
    return String(value)
  }
}

function isMissingEndpoint(e) {
  const s = e?.response?.status
  return s === 404 || s === 405 || s === 501
}

function scopeParams() {
  const params = { days: days.value }
  if (props.rulesetId) params.ruleset_id = props.rulesetId
  return params
}

async function loadAll() {
  if (!api) {
    error.value = '规则引擎接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  const base = `days=${days.value}${props.rulesetId ? `&ruleset_id=${props.rulesetId}` : ''}`
  const results = await Promise.allSettled([
    api.get(`stats/trend/?${base}`),
    api.get(`stats/top-rules/?${base}&limit=20`),
    api.get(`stats/failures/?${base}`),
  ])
  const [trendRes, topRes, failRes] = results
  let missing = 0
  let firstError = ''

  if (trendRes.status === 'fulfilled') {
    trend.value = trendRes.value?.items || []
  } else {
    trend.value = []
    if (isMissingEndpoint(trendRes.reason)) missing += 1
    else firstError = firstError || (trendRes.reason?.message || '趋势加载失败')
  }

  if (topRes.status === 'fulfilled') {
    topRules.value = topRes.value?.items || []
  } else {
    topRules.value = []
    if (isMissingEndpoint(topRes.reason)) missing += 1
    else firstError = firstError || (topRes.reason?.message || '命中排行加载失败')
  }

  if (failRes.status === 'fulfilled') {
    failures.value = failRes.value || null
  } else {
    failures.value = null
    if (isMissingEndpoint(failRes.reason)) missing += 1
    else firstError = firstError || (failRes.reason?.message || '失败统计加载失败')
  }

  if (firstError) {
    error.value = firstError
    app.toastMsg(firstError, 'error')
  } else if (missing) {
    notice.value = '部分统计接口在当前后端版本不可用，已隐藏对应数据块'
  }
  loading.value = false
  await loadLogs()
}

function buildLogParams() {
  const params = { page: logPage.value, page_size: logPageSize.value }
  if (props.rulesetId) params.ruleset_id = props.rulesetId
  if (logQ.value.trim()) params.q = logQ.value.trim()
  if (logStatus.value) params.status = logStatus.value
  if (logActionType.value) params.action_type = logActionType.value
  return params
}

async function loadLogs() {
  if (!api) return
  logsLoading.value = true
  logsError.value = ''
  logNotice.value = ''
  try {
    const data = await api.list('logs/', buildLogParams())
    logs.value = data.items || []
    logTotal.value = Number(data.count) || 0
  } catch (e) {
    logs.value = []
    logTotal.value = 0
    if (isMissingEndpoint(e)) {
      logNotice.value = '当前后端未提供执行日志接口，页面已降级为空态'
    } else {
      logsError.value = e?.message || '执行日志加载失败'
      app.toastMsg(logsError.value, 'error')
    }
  } finally {
    logsLoading.value = false
  }
}

function applyLogFilters() {
  logPage.value = 1
  loadLogs()
}

function resetLogFilters() {
  logQ.value = ''
  logStatus.value = ''
  logActionType.value = ''
  logPage.value = 1
  loadLogs()
}

function goLogPage(next) {
  logPage.value = Math.min(Math.max(1, next), logPages.value)
  loadLogs()
}

async function openLog(row) {
  logShow.value = true
  logDetail.value = null
  logDetailId.value = row.id
  logDetailError.value = ''
  logDetailLoading.value = true
  try {
    logDetail.value = await api.get(`logs/${row.id}/`)
  } catch (e) {
    logDetailError.value = e?.message || '日志详情加载失败'
  } finally {
    logDetailLoading.value = false
  }
}

async function reloadLog() {
  if (logDetailId.value) await openLog({ id: logDetailId.value })
}

watch(
  () => [props.refreshKey, props.rulesetId, days.value],
  () => {
    logPage.value = 1
    loadAll()
  }
)

onMounted(loadAll)
</script>