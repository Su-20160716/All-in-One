<template>
  <div class="space-y-4">
    <!-- 工具条 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-end gap-2">
        <label class="flex min-w-[220px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
          选择表单
          <select v-model="formId" class="input" @change="onFormChange">
            <option value="">请选择表单</option>
            <option v-for="form in forms" :key="form.id" :value="form.id">
              {{ form.name }}（{{ form.code }}）
            </option>
          </select>
        </label>
        <div class="flex flex-col gap-1 text-[11px] text-ink-500">
          趋势区间
          <div class="flex flex-wrap gap-1">
            <button
              v-for="option in DAY_OPTIONS"
              :key="option"
              type="button"
              class="rounded-pill px-2.5 py-1 text-[11px]"
              :class="days === option ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-600 hover:bg-ink-100'"
              @click="setDays(option)"
            >
              {{ option }} 天
            </button>
          </div>
        </div>
        <button class="btn-outline" type="button" :disabled="loading || !formId" @click="loadAll">
          {{ loading ? '加载中…' : '刷新统计' }}
        </button>
      </div>
      <p class="mt-2 text-[11px] text-ink-400">
        统计口径：有效提交（已提交 + 已审核），草稿单独计数；字段分布以当前设计或当前版本 schema 为骨架。
      </p>
    </div>

    <div v-if="!forms.length" class="card py-14 text-center text-[12px] text-ink-400">
      <p>暂无可分析的表单</p>
      <p class="mt-1 text-[11px] text-ink-400">请先在「表单管理」中创建或发布表单</p>
    </div>
    <div v-else-if="!formId" class="card py-14 text-center text-[12px] text-ink-400">
      请选择表单后查看字段分析
    </div>
    <template v-else>
      <div v-if="error" class="card p-4">
        <div class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ error }}</span>
          <button class="shrink-0 font-medium" type="button" @click="loadAll">重试</button>
        </div>
      </div>
      <div v-else-if="unavailable" class="card py-14 text-center text-[12px] text-ink-400">
        <p>统计接口暂不可用，已降级为空态</p>
        <button class="btn-ghost mt-3" type="button" @click="loadAll">重试</button>
      </div>
      <div v-else-if="loading && !stats" class="card py-14 text-center text-[12px] text-ink-400">
        统计加载中…
      </div>
      <template v-else-if="stats">
        <div v-if="warning" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-600">
          {{ warning }}
        </div>

        <StatsGrid :items="statItems" :columns="3" :loading="loading" />

        <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SectionCard title="提交来源分布" subtitle="来源取自提交记录，草稿不计入" dense>
            <template #badge>
              <span class="tag">有效 {{ stats.final ?? 0 }} 份</span>
            </template>
            <DonutChart
              :data="sourceDonut"
              :size="160"
              center-label="有效提交"
              :center-value="stats.final ?? 0"
              legend-position="right"
              empty-text="暂无来源数据"
            />
          </SectionCard>

          <SectionCard title="提交状态分布" subtitle="含草稿、驳回等全部状态" dense>
            <template #badge>
              <span class="tag">共 {{ stats.total ?? 0 }} 份</span>
            </template>
            <BarChart
              :data="statusBars"
              horizontal
              :height="160"
              empty-text="暂无状态数据"
            />
          </SectionCard>
        </div>

        <SectionCard title="按日提交趋势" :subtitle="`最近 ${days} 天，含已审核与驳回对比`" dense>
          <template #badge>
            <span class="tag">合计 {{ trendData?.total ?? 0 }} 份</span>
          </template>
          <LineChart
            v-if="trendSeries.length"
            :series="trendSeries"
            :labels="trendLabels"
            :height="240"
            :max-x-labels="9"
            aria-label="按日提交趋势"
          />
          <div v-else class="py-10 text-center text-[12px] text-ink-400">暂无趋势数据</div>
        </SectionCard>

        <SectionCard title="字段分布" subtitle="点击字段行可切换下方分布图" dense>
          <template #actions>
            <span class="tag">{{ fieldRows.length }} 个字段</span>
          </template>
          <div v-if="!fieldRows.length" class="py-8 text-center text-[12px] text-ink-400">
            当前表单还没有字段
          </div>
          <template v-else>
            <div class="grid grid-cols-1 gap-4 xl:grid-cols-5">
              <div class="xl:col-span-3">
                <div class="mb-2 flex flex-wrap items-end gap-2">
                  <label class="flex min-w-[200px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
                    分布字段
                    <select v-model="selectedFieldKey" class="input" @change="onFieldChange">
                      <option v-for="field in fieldRows" :key="field.field_key" :value="field.field_key">
                        {{ field.label }}（{{ field.field_key }}）
                      </option>
                    </select>
                  </label>
                  <span v-if="selectedField" class="tag">
                    答题率 {{ percentText(selectedField.answer_rate) }}
                  </span>
                </div>
                <BarChart
                  v-if="distributionBars.length"
                  :data="distributionBars"
                  horizontal
                  :height="Math.max(160, Math.min(360, distributionBars.length * 30))"
                  :empty-text="distributionEmptyText"
                />
                <div v-else class="rounded-control bg-ink-50 px-3 py-8 text-center text-[12px] text-ink-400">
                  {{ distributionEmptyText }}
                </div>
                <div v-if="selectedField?.stats && hasStats(selectedField.stats)" class="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px] sm:grid-cols-4">
                  <div v-for="item in statPairs(selectedField)" :key="item.label" class="rounded-control bg-ink-50 px-2 py-1.5">
                    <div class="text-[11px] text-ink-400">{{ item.label }}</div>
                    <div class="text-[13px] font-medium text-ink-800">{{ item.value }}</div>
                  </div>
                </div>
              </div>
              <div class="xl:col-span-2">
                <div class="max-h-[360px] overflow-y-auto rounded-control border border-ink-100">
                  <table class="w-full text-left">
                    <thead class="sticky top-0 border-b border-ink-100 bg-ink-50/95">
                      <tr>
                        <th class="th">字段</th>
                        <th class="th">已答</th>
                        <th class="th">答题率</th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-ink-50">
                      <tr
                        v-for="field in fieldRows"
                        :key="field.field_key"
                        class="cursor-pointer hover:bg-brand-50/40"
                        :class="field.field_key === selectedFieldKey ? 'bg-brand-50/60' : ''"
                        @click="pickField(field.field_key)"
                      >
                        <td class="td">
                          <div class="flex min-w-0 flex-col">
                            <span class="truncate text-[12px] text-ink-800">{{ field.label }}</span>
                            <span class="truncate text-[11px] text-ink-400">{{ field.type_label || field.type }}</span>
                          </div>
                        </td>
                        <td class="td">{{ field.answered }} / {{ field.total }}</td>
                        <td class="td">{{ percentText(field.answer_rate) }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </template>
        </SectionCard>

        <SectionCard title="填写耗时" subtitle="基于有效提交的耗时秒数，忽略 0 秒记录" dense>
          <template #badge>
            <span class="tag">{{ durationData?.count ?? 0 }} 条样本</span>
          </template>
          <div v-if="!durationData" class="py-8 text-center text-[12px] text-ink-400">暂无耗时数据</div>
          <div v-else class="space-y-3">
            <div class="grid grid-cols-2 gap-2 text-[12px] sm:grid-cols-5">
              <div v-for="item in durationPairs" :key="item.label" class="rounded-control bg-ink-50 px-2.5 py-2">
                <div class="text-[11px] text-ink-400">{{ item.label }}</div>
                <div class="text-[13px] font-medium text-ink-800">{{ item.value }}</div>
              </div>
            </div>
            <BarChart
              :data="durationBars"
              :height="150"
              :format="(value) => `${value} 份`"
              empty-text="暂无耗时分布"
            />
          </div>
        </SectionCard>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { formstudioApi, unwrap } from '../../api/platform'
import { formatNumber } from '../../composables/useDomainResource'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import BarChart from '../../components/platform/BarChart.vue'
import LineChart from '../../components/platform/LineChart.vue'

const props = defineProps({
  forms: { type: Array, default: () => [] },
})

const DAY_OPTIONS = [7, 14, 30, 90]
const SOURCE_LABELS = {
  web: '网页',
  share: '分享链接',
  api: '接口',
  embed: '嵌入',
  import: '导入',
}
const STATUS_LABELS = {
  draft: '草稿',
  submitted: '已提交',
  reviewed: '已审核',
  rejected: '已驳回',
}

const formId = ref('')
const days = ref(30)
const loading = ref(false)
const error = ref('')
const warning = ref('')
const unavailable = ref(false)
const stats = ref(null)
const fieldsData = ref(null)
const trendData = ref(null)
const durationData = ref(null)
const selectedFieldKey = ref('')
let seq = 0

function percentText(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(1)}%`
}
function durationText(seconds) {
  const n = Number(seconds)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n < 60) return `${Math.round(n)} 秒`
  const minutes = Math.floor(n / 60)
  const rest = Math.round(n % 60)
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
}
function hasStats(value) {
  return value && typeof value === 'object' && Object.keys(value).length > 0
}

const sourceDonut = computed(() => {
  const bySource = stats.value?.by_source || {}
  return Object.entries(bySource).map(([key, value]) => ({
    label: SOURCE_LABELS[key] || key || '未知',
    value: Number(value) || 0,
  }))
})
const statusBars = computed(() => {
  const byStatus = stats.value?.by_status || {}
  return Object.entries(byStatus).map(([key, value]) => ({
    label: STATUS_LABELS[key] || key,
    value: Number(value) || 0,
  }))
})

const statItems = computed(() => {
  const data = stats.value || {}
  const passScore = data.pass_score
  return [
    {
      key: 'final',
      label: '有效提交',
      value: Number(data.final) || 0,
      unit: '份',
      hint: `总提交 ${formatNumber(data.total)} · 草稿 ${formatNumber(data.drafts)}`,
      icon: '▤',
      tone: 'brand',
    },
    {
      key: 'completion',
      label: '完成率',
      value: percentText(data.completion_rate),
      hint: '有效提交 / (有效提交 + 草稿)',
      icon: '◔',
      tone: 'emerald',
    },
    {
      key: 'avgScore',
      label: '平均得分',
      value: Number(data.avg_score) || 0,
      hint: passScore === null || passScore === undefined ? '未配置及格线' : `及格线 ${passScore}`,
      icon: '◈',
    },
    {
      key: 'avgDuration',
      label: '平均耗时',
      value: durationText(data.avg_duration),
      hint: `最长 ${durationText(data.max_duration)} · 最短 ${durationText(data.min_duration)}`,
      icon: '◷',
    },
    {
      key: 'pending',
      label: '待审核',
      value: Number(data.pending_reviews) || 0,
      unit: '条',
      hint: `审核率 ${percentText(data.review_rate)}`,
      icon: '◇',
      tone: Number(data.pending_reviews) > 0 ? 'amber' : 'default',
    },
    {
      key: 'pass',
      label: '通过率',
      value: data.pass_rate === null || data.pass_rate === undefined ? '—' : percentText(data.pass_rate),
      hint: data.pass_score === null || data.pass_score === undefined ? '未配置计分规则' : `通过 ${data.passed} 份`,
      icon: '◑',
    },
  ]
})

const trendSeries = computed(() => {
  const series = trendData.value?.series || []
  if (!series.length) return []
  return [
    {
      name: '提交量',
      color: 'var(--brand-500)',
      area: true,
      data: series.map((row) => Number(row.submissions) || 0),
    },
    {
      name: '已审核',
      color: '#10b981',
      data: series.map((row) => Number(row.reviewed) || 0),
    },
    {
      name: '已驳回',
      color: '#f43f5e',
      data: series.map((row) => Number(row.rejected) || 0),
      dashed: true,
    },
  ]
})
const trendLabels = computed(() => (trendData.value?.series || []).map((row) => String(row.date).slice(5)))

const fieldRows = computed(() => fieldsData.value?.fields || [])
const selectedField = computed(
  () => fieldRows.value.find((field) => field.field_key === selectedFieldKey.value) || null
)
const distributionBars = computed(() => {
  const field = selectedField.value
  if (!field) return []
  return (field.distribution || []).map((item) => ({
    label: String(item.label ?? item.value ?? '—'),
    value: Number(item.count) || 0,
  }))
})
const distributionEmptyText = computed(() => {
  const field = selectedField.value
  if (!field) return '请选择字段'
  if (field.type === 'rating') return '暂无评分分布数据'
  if (field.type === 'number' || field.type === 'date' || field.type === 'datetime') {
    return '该字段为数值/日期类型，请查看下方统计摘要'
  }
  if (field.type === 'file') return '文件字段只统计附件数量'
  return '该字段暂无答题数据'
})

const durationPairs = computed(() => {
  const data = durationData.value
  if (!data) return []
  const statsValue = data.stats || {}
  return [
    { label: '样本数', value: formatNumber(statsValue.count) },
    { label: '平均耗时', value: durationText(statsValue.avg) },
    { label: '中位数', value: durationText(statsValue.median) },
    { label: 'P90', value: durationText(statsValue.p90) },
    { label: '最长耗时', value: durationText(data.slowest) },
  ]
})
const durationBars = computed(() =>
  (durationData.value?.buckets || []).map((bucket) => ({
    label: bucket.label,
    value: Number(bucket.count) || 0,
  }))
)

function statPairs(field) {
  const statsValue = field?.stats || {}
  const out = []
  if (field.type === 'rating' || field.type === 'number') {
    out.push({ label: '样本数', value: formatNumber(statsValue.count) })
    out.push({ label: '均值', value: Number(statsValue.avg || 0).toFixed(2) })
    out.push({ label: '中位数', value: Number(statsValue.median || 0).toFixed(2) })
    out.push({ label: 'P90', value: Number(statsValue.p90 || 0).toFixed(2) })
    out.push({ label: '最小', value: Number(statsValue.min || 0).toFixed(2) })
    out.push({ label: '最大', value: Number(statsValue.max || 0).toFixed(2) })
    out.push({ label: '标准差', value: Number(statsValue.stdev || 0).toFixed(2) })
    out.push({ label: '合计', value: Number(statsValue.sum || 0).toFixed(2) })
  } else if (field.type === 'date' || field.type === 'datetime') {
    out.push({ label: '填写数', value: formatNumber(statsValue.count) })
    out.push({ label: '最早', value: statsValue.earliest ? String(statsValue.earliest).slice(0, 10) : '—' })
    out.push({ label: '最晚', value: statsValue.latest ? String(statsValue.latest).slice(0, 10) : '—' })
  } else if (field.type === 'file') {
    out.push({ label: '附件数', value: formatNumber(statsValue.count) })
  } else {
    out.push({ label: '已答', value: formatNumber(statsValue.count ?? field.answered) })
  }
  return out
}

function pickField(key) {
  selectedFieldKey.value = key
}
function onFormChange() {
  selectedFieldKey.value = ''
  stats.value = null
  fieldsData.value = null
  trendData.value = null
  durationData.value = null
  loadAll()
}

function setDays(value) {
  if (days.value === value) return
  days.value = value
  loadAll()
}

async function fetchTrend(id) {
  return unwrap(
    formstudioApi.raw({
      url: `/formstudio/forms/${id}/stats/trend/`,
      method: 'get',
      params: { days: days.value },
    })
  )
}

async function loadAll() {
  if (!formId.value) {
    stats.value = null
    fieldsData.value = null
    trendData.value = null
    durationData.value = null
    return
  }
  const current = ++seq
  loading.value = true
  error.value = ''
  warning.value = ''
  unavailable.value = false
  const id = formId.value
  const results = await Promise.allSettled([
    formstudioApi.get(`forms/${id}/stats/`),
    formstudioApi.get(`forms/${id}/stats/fields/`),
    fetchTrend(id),
    formstudioApi.get(`forms/${id}/stats/duration/`),
  ])
  if (current !== seq) return
  const failures = []
  if (results[0].status === 'fulfilled') {
    stats.value = results[0].value || null
  } else {
    stats.value = null
    failures.push(results[0].reason)
  }
  if (results[1].status === 'fulfilled') {
    fieldsData.value = results[1].value || null
    const rows = fieldsData.value?.fields || []
    const exists = rows.some((field) => field.field_key === selectedFieldKey.value)
    if ((!selectedFieldKey.value || !exists) && rows.length) {
      selectedFieldKey.value = rows[0].field_key
    }
    if (!rows.length) selectedFieldKey.value = ''
  } else {
    fieldsData.value = null
    failures.push(results[1].reason)
  }
  if (results[2].status === 'fulfilled') {
    trendData.value = results[2].value || null
  } else {
    trendData.value = null
    failures.push(results[2].reason)
  }
  if (results[3].status === 'fulfilled') {
    durationData.value = results[3].value || null
  } else {
    durationData.value = null
    failures.push(results[3].reason)
  }
  if (results[0].status === 'rejected' && failures.length === results.length) {
    const down = failures.every((reason) => reason?.status === 404 || reason?.status === 405)
    unavailable.value = down
    error.value = down ? '' : failures[0]?.message || '统计加载失败'
  } else if (failures.length) {
    warning.value = `部分统计接口暂不可用（${failures.length} 项），已按可用数据展示`
  }
  loading.value = false
}

watch(
  () => props.forms,
  (list) => {
    const rows = Array.isArray(list) ? list : []
    if (!rows.length) {
      formId.value = ''
      return
    }
    const exists = rows.some((form) => String(form.id) === String(formId.value))
    if (!exists) {
      formId.value = rows[0].id
      selectedFieldKey.value = ''
      loadAll()
    }
  },
  { immediate: true }
)
</script>