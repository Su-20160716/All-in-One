<template>
  <section class="space-y-3">
    <div
      v-if="primaryError"
      class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
    >
      <span class="min-w-0 flex-1">{{ primaryError }}</span>
      <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="loadAll">重试</button>
    </div>

    <!-- 顶部五项指标 -->
    <StatsGrid :items="statItems" :loading="loading" :skeleton-count="5" />

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="状态分布" subtitle="全部可见合同按状态计数，环形图中心为合同总数">
        <template #actions>
          <span class="tag">共 {{ formatNumber(statusTotal) }} 份</span>
          <button class="text-[11px] text-brand-600" type="button" @click="$emit('go-tab', 'contracts')">进入台账</button>
        </template>
        <div v-if="loading && !loaded" class="grid h-[180px] place-items-center text-[12px] text-ink-400">加载中…</div>
        <DonutChart
          v-else
          :data="statusData"
          :center-value="formatNumber(statusTotal)"
          center-label="合同总数"
          :size="156"
          empty-text="暂无合同状态数据"
        />
        <p v-if="errs.overview" class="mt-2 text-[11px] text-amber-600">{{ errs.overview }}</p>
      </SectionCard>

      <SectionCard title="到期月份分布" subtitle="未来到期合同的月份分布，用于提前安排续约与终止">
        <template #actions>
          <span class="tag bg-amber-50 text-amber-600">30 天内 {{ formatNumber(expiring30) }}</span>
        </template>
        <div v-if="loading && !loaded" class="grid h-[180px] place-items-center text-[12px] text-ink-400">加载中…</div>
        <BarChart
          v-else
          :data="monthData"
          :height="180"
          color="var(--brand-500)"
          empty-text="暂无到期月份数据"
        />
        <p v-if="errs.expiry" class="mt-2 text-[11px] text-amber-600">{{ errs.expiry }}</p>
      </SectionCard>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="金额汇总" subtitle="按币种统计合同金额与待审批金额，不做跨币种折算">
        <template #actions>
          <span class="tag bg-emerald-50 text-emerald-600">待审批 {{ formatMoney(pendingAmount, 'CNY') }}</span>
        </template>
        <div v-if="loading && !loaded" class="space-y-2">
          <div v-for="n in 3" :key="n" class="h-6 animate-pulse rounded bg-ink-100" />
        </div>
        <div v-else-if="!amountRows.length" class="py-8 text-center text-[12px] text-ink-400">暂无金额汇总数据</div>
        <table v-else class="w-full">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">币种</th>
              <th class="th text-right">合同份数</th>
              <th class="th text-right">合同金额</th>
              <th class="th text-right">已收付</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in amountRows" :key="row.currency" class="border-b border-ink-50 last:border-0">
              <td class="td">{{ row.currency }}</td>
              <td class="td text-right">{{ formatNumber(row.count) }}</td>
              <td class="td text-right">{{ formatMoney(row.amount, row.currency) }}</td>
              <td class="td text-right text-ink-500">{{ formatMoney(row.paid, row.currency) }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr class="bg-ink-50/60">
              <td class="td font-medium text-ink-700">合计</td>
              <td class="td text-right text-ink-600">{{ formatNumber(amountTotal.count) }}</td>
              <td class="td text-right text-ink-600">{{ amountTotal.amount }}</td>
              <td class="td text-right text-ink-500">{{ amountTotal.paid }}</td>
            </tr>
          </tfoot>
        </table>
        <p v-if="errs.amount" class="mt-2 text-[11px] text-amber-600">{{ errs.amount }}</p>
      </SectionCard>

      <SectionCard title="履约健康度" subtitle="综合生效占比、到期压力与高风险合同计算，0 到 100 分">
        <template #actions>
          <span class="tag" :class="healthTone">{{ healthLevel }}</span>
        </template>
        <div v-if="loading && !loaded" class="grid h-[140px] place-items-center text-[12px] text-ink-400">加载中…</div>
        <div v-else class="space-y-3">
          <div class="flex items-end gap-3">
            <span class="text-[30px] font-semibold leading-none" :class="healthTextTone">{{ healthScore }}</span>
            <span class="pb-1 text-[12px] text-ink-400">分 / 100</span>
            <span v-if="healthSource" class="pb-1 text-[11px] text-ink-400">{{ healthSource }}</span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-pill bg-ink-100">
            <div class="h-full rounded-pill transition-all" :class="healthBarTone" :style="{ width: `${healthScore}%` }" />
          </div>
          <div class="grid gap-2 sm:grid-cols-3">
            <div v-for="item in healthItems" :key="item.key" class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">{{ item.label }}</div>
              <div class="text-[14px] font-medium text-ink-800">{{ item.value }}</div>
              <div class="text-[11px] text-ink-400">{{ item.hint }}</div>
            </div>
          </div>
        </div>
        <p v-if="errs.health" class="mt-2 text-[11px] text-amber-600">{{ errs.health }}</p>
      </SectionCard>
    </div>

    <SectionCard title="最近合同" subtitle="按更新时间倒序展示最近 8 份合同，点击行打开台账详情">
      <template #actions>
        <span class="tag">样本 {{ formatNumber(recent.length) }} 份</span>
        <button class="text-[11px] text-brand-600" type="button" @click="$emit('go-tab', 'contracts')">查看全部</button>
      </template>
      <div v-if="recentLoading" class="space-y-2 py-2">
        <div v-for="n in 4" :key="n" class="h-7 animate-pulse rounded bg-ink-100" />
      </div>
      <div
        v-else-if="recentError"
        class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ recentError }}</span>
        <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="loadRecent">重试</button>
      </div>
      <div v-else-if="!recent.length" class="py-8 text-center text-[12px] text-ink-400">
        还没有合同，先在台账页创建第一份合同
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[640px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">编号</th>
              <th class="th">名称</th>
              <th class="th">相对方</th>
              <th class="th text-right">金额</th>
              <th class="th">到期日</th>
              <th class="th">风险</th>
              <th class="th">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in recent"
              :key="row.id"
              class="cursor-pointer border-b border-ink-50 transition-colors last:border-0 hover:bg-ink-50/70"
              @click="$emit('open-contract', row.id)"
            >
              <td class="td font-mono text-[12px] text-ink-500">{{ row.number || '—' }}</td>
              <td class="td max-w-[220px] truncate">{{ row.name || '未命名合同' }}</td>
              <td class="td max-w-[160px] truncate text-ink-500">{{ row.counterparty_name || '—' }}</td>
              <td class="td text-right">{{ formatMoney(row.amount, row.currency || 'CNY') }}</td>
              <td class="td text-ink-500">{{ formatDate(row.expire_date) }}</td>
              <td class="td">
                <span class="tag" :class="riskClass(row)">{{ riskLabel(row) }}</span>
              </td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(row.status))">{{ statusLabel(row.status) }}</span>
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
import { contractsApi, normalizeList } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
} from '../../composables/useDomainResource'
import SectionCard from '../../components/platform/SectionCard.vue'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import BarChart from '../../components/platform/BarChart.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
defineEmits(['open-contract', 'go-tab'])

const CONTRACT_STATUS = {
  draft: '草稿',
  pending: '待提交',
  pending_approval: '待审批',
  submitted: '已提交',
  approving: '审批中',
  approved: '已批准',
  rejected: '已驳回',
  signed: '已签署',
  active: '生效中',
  executing: '履行中',
  completed: '已完成',
  terminated: '已终止',
  expired: '已到期',
  archived: '已归档',
  paused: '已暂停',
}

const STATUS_COLORS = {
  draft: '#cbd5e1',
  pending: '#fbbf24',
  pending_approval: '#f59e0b',
  submitted: '#f59e0b',
  approving: '#f59e0b',
  approved: '#38bdf8',
  rejected: '#fb7185',
  signed: '#a78bfa',
  active: '#10b981',
  executing: '#10b981',
  completed: '#0ea5e9',
  terminated: '#f43f5e',
  expired: '#f97316',
  archived: '#94a3b8',
  paused: '#94a3b8',
}

const loading = ref(false)
const loaded = ref(false)
const primaryError = ref('')
const errs = ref({ overview: '', expiry: '', amount: '', health: '' })

const overview = ref(null)
const expiry = ref(null)
const amount = ref(null)
const health = ref(null)
const riskRemote = ref(-1)
const recent = ref([])
const recentLoading = ref(false)
const recentError = ref('')

const expiring30 = ref(0)

function pick(obj, paths, fallback = null) {
  for (const path of paths) {
    let cur = obj
    let ok = true
    for (const key of path.split('.')) {
      if (cur == null || typeof cur !== 'object') {
        ok = false
        break
      }
      cur = cur[key]
    }
    if (ok && cur !== undefined && cur !== null && cur !== '') return cur
  }
  return fallback
}

function numOf(obj, paths, fallback = 0) {
  const n = Number(pick(obj, paths, fallback))
  return Number.isFinite(n) ? n : fallback
}

function rowsOf(value) {
  if (Array.isArray(value)) return value.filter((row) => row && typeof row === 'object')
  if (Array.isArray(value?.items)) return value.items.filter((row) => row && typeof row === 'object')
  if (Array.isArray(value?.rows)) return value.rows.filter((row) => row && typeof row === 'object')
  return []
}

function statusLabel(status) {
  return CONTRACT_STATUS[status] || status || '未知'
}

function statusTone(status) {
  const s = String(status || '').toLowerCase()
  if (['active', 'approved', 'signed', 'executing'].includes(s)) return 'success'
  if (['completed', 'archived'].includes(s)) return 'info'
  if (['draft', 'pending', 'pending_approval', 'submitted', 'approving', 'paused'].includes(s)) return 'warning'
  if (['rejected', 'terminated', 'expired'].includes(s)) return 'danger'
  return 'neutral'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    info: 'bg-sky-50 text-sky-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function riskLevelOf(row) {
  const score = Number(row?.risk_score)
  if (Number.isFinite(score)) {
    if (score >= 80) return 'critical'
    if (score >= 60) return 'high'
    if (score >= 30) return 'medium'
    return 'low'
  }
  return row?.risk_level || 'low'
}

function riskLabel(row) {
  const level = riskLevelOf(row)
  return { critical: '极高', high: '高', medium: '中', low: '低' }[level] || '低'
}

function riskClass(row) {
  const level = riskLevelOf(row)
  return {
    critical: 'bg-rose-100 text-rose-700',
    high: 'bg-rose-50 text-rose-600',
    medium: 'bg-amber-50 text-amber-600',
    low: 'bg-emerald-50 text-emerald-600',
  }[level] || 'bg-ink-100 text-ink-600'
}

const contractTotal = computed(() => {
  const fromOverview = numOf(overview.value, [
    'totals.contracts',
    'totals.total',
    'contracts',
    'total',
    'counts.total',
  ], -1)
  if (fromOverview >= 0) return fromOverview
  return numOf(overview.value, ['count'], 0)
})

const activeCount = computed(() =>
  numOf(overview.value, ['totals.active', 'status_counts.active', 'by_status.active', 'active'], 0)
)

const highRiskCount = computed(() => {
  if (riskRemote.value >= 0) return riskRemote.value
  const direct = numOf(overview.value, [
    'totals.high_risk',
    'risk.high',
    'risk_counts.high',
    'high_risk',
    'risk_high',
  ], -1)
  if (direct >= 0) return direct
  return recent.value.filter((row) => ['high', 'critical'].includes(riskLevelOf(row))).length
})

const pendingAmount = computed(() =>
  numOf(overview.value, [
    'totals.pending_amount',
    'amounts.pending',
    'pending_amount',
    'pending_amount_total',
  ], 0)
)

const statItems = computed(() => [
  {
    key: 'total',
    label: '合同数',
    value: contractTotal.value,
    unit: '份',
    hint: `台账最近更新 ${recent.value.length ? formatDate(recent.value[0]?.updated_at) : '—'}`,
    tone: 'brand',
  },
  {
    key: 'active',
    label: '生效中',
    value: activeCount.value,
    unit: '份',
    hint: contractTotal.value ? `占全部 ${((activeCount.value / Math.max(1, contractTotal.value)) * 100).toFixed(1)}%` : '暂无合同',
    tone: 'emerald',
  },
  {
    key: 'expiring',
    label: '30 天内到期',
    value: expiring30.value,
    unit: '份',
    hint: expiring30.value ? '需要提前确认续约方式' : '近期没有到期合同',
    tone: 'amber',
  },
  {
    key: 'risk',
    label: '风险高',
    value: highRiskCount.value,
    unit: '份',
    hint: highRiskCount.value ? '建议优先复核条款与付款' : '风险整体可控',
    tone: 'rose',
  },
  {
    key: 'pending',
    label: '待审批金额',
    value: pendingAmount.value,
    hint: '进入审批流程但尚未批准的合同金额',
    tone: 'default',
    format: (v) => formatMoney(v, 'CNY'),
  },
])

const statusRows = computed(() => {
  const direct = pick(overview.value, [
    'status_distribution',
    'statuses',
    'by_status',
    'status_counts',
    'distribution',
  ], [])
  const rows = rowsOf(direct)
  if (rows.length) {
    return rows.map((row) => ({
      status: row.status || row.key || row.label || 'unknown',
      count: Number(row.count ?? row.value ?? row.total ?? 0) || 0,
    }))
  }
  // 概览接口没有分布字段时，用最近合同样本兜底，图表不至于空白
  const bucket = new Map()
  for (const row of recent.value) {
    const key = row.status || 'unknown'
    bucket.set(key, (bucket.get(key) || 0) + 1)
  }
  return Array.from(bucket.entries()).map(([status, count]) => ({ status, count }))
})

const statusTotal = computed(() =>
  statusRows.value.reduce((sum, row) => sum + (Number(row.count) || 0), 0)
)

const statusData = computed(() =>
  statusRows.value.map((row) => ({
    label: statusLabel(row.status),
    value: row.count,
    color: STATUS_COLORS[row.status] || '#cbd5e1',
  }))
)

const monthRows = computed(() => {
  const direct = pick(expiry.value, [
    'months',
    'by_month',
    'month_distribution',
    'distribution',
    'items',
  ], [])
  const rows = rowsOf(direct)
  if (rows.length) {
    return rows.map((row) => ({
      label: String(row.month || row.key || row.label || '').slice(0, 7),
      value: Number(row.count ?? row.value ?? row.total ?? 0) || 0,
    }))
  }
  // 没有到期统计时，按最近合同到期日落到未来 12 个月
  const now = new Date()
  const keys = []
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(now.getFullYear(), now.getMonth() + i, 1)
    keys.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }
  const bucket = new Map(keys.map((key) => [key, 0]))
  for (const row of recent.value) {
    const key = String(row.expire_date || '').slice(0, 7)
    if (bucket.has(key)) bucket.set(key, bucket.get(key) + 1)
  }
  return Array.from(bucket.entries()).map(([label, value]) => ({ label: label.slice(5), value }))
})

const monthData = computed(() => monthRows.value.filter((row) => row.value > 0))

const amountRows = computed(() => {
  const direct = pick(amount.value, [
    'by_currency',
    'currencies',
    'currency_rows',
    'groups',
    'items',
  ], [])
  const rows = rowsOf(direct)
  if (rows.length) {
    return rows.map((row) => ({
      currency: row.currency || row.key || row.code || 'CNY',
      count: Number(row.count ?? row.contracts ?? 0) || 0,
      amount: Number(row.amount ?? row.total ?? row.plan_amount ?? 0) || 0,
      paid: Number(row.paid ?? row.paid_amount ?? row.received ?? 0) || 0,
    }))
  }
  // 兜底：按最近合同样本聚合，页面上会标注样本来源
  const bucket = new Map()
  for (const row of recent.value) {
    const currency = row.currency || 'CNY'
    const cur = bucket.get(currency) || { currency, count: 0, amount: 0, paid: 0 }
    cur.count += 1
    cur.amount += Number(row.amount) || 0
    bucket.set(currency, cur)
  }
  return Array.from(bucket.values())
})

const amountTotal = computed(() => {
  const rows = amountRows.value
  const currencies = new Set(rows.map((row) => row.currency))
  return {
    count: rows.reduce((sum, row) => sum + row.count, 0),
    amount: currencies.size > 1
      ? '多币种'
      : formatMoney(rows.reduce((sum, row) => sum + row.amount, 0), rows[0]?.currency || 'CNY'),
    paid: currencies.size > 1
      ? '多币种'
      : formatMoney(rows.reduce((sum, row) => sum + row.paid, 0), rows[0]?.currency || 'CNY'),
  }
})

const healthScore = computed(() => {
  const direct = numOf(health.value, ['score', 'health.score', 'overall', 'health_score', 'value'], -1)
  if (direct >= 0) return Math.max(0, Math.min(100, Math.round(direct)))
  const total = contractTotal.value
  if (!total) return 0
  const activeRatio = activeCount.value / total
  const riskRatio = highRiskCount.value / total
  return Math.max(0, Math.min(100, Math.round(activeRatio * 100 - riskRatio * 40)))
})

const healthLevel = computed(() => {
  const explicit = pick(health.value, ['level', 'grade', 'health.level', 'rating'])
  if (explicit) return String(explicit)
  if (healthScore.value >= 80) return '健康'
  if (healthScore.value >= 60) return '基本健康'
  if (healthScore.value >= 40) return '需关注'
  return '高风险'
})

const healthTone = computed(() => {
  if (healthScore.value >= 80) return 'bg-emerald-50 text-emerald-600'
  if (healthScore.value >= 60) return 'bg-sky-50 text-sky-600'
  if (healthScore.value >= 40) return 'bg-amber-50 text-amber-600'
  return 'bg-rose-50 text-rose-600'
})

const healthTextTone = computed(() => {
  if (healthScore.value >= 80) return 'text-emerald-600'
  if (healthScore.value >= 60) return 'text-sky-600'
  if (healthScore.value >= 40) return 'text-amber-600'
  return 'text-rose-600'
})

const healthBarTone = computed(() => {
  if (healthScore.value >= 80) return 'bg-emerald-500'
  if (healthScore.value >= 60) return 'bg-sky-500'
  if (healthScore.value >= 40) return 'bg-amber-500'
  return 'bg-rose-500'
})

const healthSource = computed(() => {
  const direct = numOf(health.value, ['score', 'health.score', 'overall', 'health_score'], -1)
  return direct >= 0 ? '接口计算' : '按台账样本估算'
})

const healthItems = computed(() => {
  const direct = pick(health.value, ['breakdown', 'dimensions', 'items', 'health.items'], [])
  const rows = rowsOf(direct)
  if (rows.length) {
    return rows.slice(0, 3).map((row, index) => ({
      key: row.key || row.code || `health-${index}`,
      label: row.label || row.name || '指标',
      value: row.value ?? row.score ?? '—',
      hint: row.hint || row.note || '',
    }))
  }
  const total = Math.max(1, contractTotal.value)
  return [
    {
      key: 'active',
      label: '生效占比',
      value: `${((activeCount.value / total) * 100).toFixed(0)}%`,
      hint: `${formatNumber(activeCount.value)} / ${formatNumber(contractTotal.value)} 份`,
    },
    {
      key: 'expiring',
      label: '到期压力',
      value: `${formatNumber(expiring30.value)} 份`,
      hint: '30 天内到期需处理',
    },
    {
      key: 'risk',
      label: '高风险合同',
      value: `${formatNumber(highRiskCount.value)} 份`,
      hint: '风险分 60 及以上',
    },
  ]
})

async function loadRecent() {
  recentLoading.value = true
  recentError.value = ''
  try {
    const data = await contractsApi.list('contracts/', { page: 1, page_size: 8, ordering: '-updated_at' })
    recent.value = normalizeList(data).items
  } catch (e) {
    recentError.value = e?.message || '最近合同加载失败'
    recent.value = []
  } finally {
    recentLoading.value = false
  }
}

async function loadAll() {
  loading.value = true
  primaryError.value = ''
  errs.value = { overview: '', expiry: '', amount: '', health: '' }
  await loadRecent()

  const [ov, ex, am, he, rk] = await Promise.allSettled([
    contractsApi.get('stats/overview/'),
    contractsApi.get('stats/expiry/'),
    contractsApi.get('stats/amount/'),
    contractsApi.get('stats/health/'),
    contractsApi.get('stats/risk/'),
  ])

  if (ov.status === 'fulfilled') {
    overview.value = ov.value
  } else {
    overview.value = null
    primaryError.value = ov.reason?.message || '合同概览接口暂不可用'
  }

  if (ex.status === 'fulfilled') {
    expiry.value = ex.value
  } else {
    expiry.value = null
    errs.value.expiry = ex.reason?.message || '到期统计暂不可用，已改用台账样本'
  }

  if (am.status === 'fulfilled') {
    amount.value = am.value
  } else {
    amount.value = null
    errs.value.amount = am.reason?.message || '金额统计暂不可用，已改用台账样本'
  }

  if (he.status === 'fulfilled') {
    health.value = he.value
  } else {
    health.value = null
    errs.value.health = he.reason?.message || '健康度接口暂不可用，已改用估算口径'
  }

  if (rk.status === 'fulfilled') {
    // 风险接口返回高等级数量时以它为准，口径与风险统计页一致
    const riskHigh = numOf(rk.value, ['high', 'counts.high', 'levels.high', 'totals.high'], -1)
    riskRemote.value = riskHigh >= 0 ? riskHigh : -1
  } else {
    riskRemote.value = -1
  }

  // 30 天到期：优先用概览/到期接口，缺失时按合同到期日现算
  const directExpiring = numOf(overview.value, [
    'totals.expiring_30d',
    'expiring_30d',
    'expiry.days_30',
    'expiring',
  ], -1)
  const expiryDirect = numOf(expiry.value, ['days_30', 'within_30', 'expiring_30d', 'count'], -1)
  if (directExpiring >= 0) {
    expiring30.value = directExpiring
  } else if (expiryDirect >= 0) {
    expiring30.value = expiryDirect
  } else {
    const now = Date.now()
    expiring30.value = recent.value.filter((row) => {
      const time = row.expire_date ? new Date(row.expire_date).getTime() : NaN
      if (Number.isNaN(time)) return false
      const diff = time - now
      return diff >= 0 && diff <= 30 * 86400000
    }).length
  }

  loaded.value = true
  loading.value = false
}

onMounted(loadAll)
watch(() => props.refreshKey, loadAll)
</script>