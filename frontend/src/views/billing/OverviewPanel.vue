<template>
  <section class="space-y-3">
    <!-- 工具条 -->
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <span class="text-[11px] text-ink-400">流失率窗口</span>
      <div class="flex items-center gap-1">
        <button
          v-for="d in DAY_OPTIONS"
          :key="d"
          type="button"
          class="rounded-pill px-2.5 py-1 text-[12px] transition-colors"
          :class="churnDays === d ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
          @click="setChurnDays(d)"
        >近 {{ d }} 天</button>
      </div>
      <span class="ml-2 text-[11px] text-ink-400">趋势区间</span>
      <div class="flex items-center gap-1">
        <button
          v-for="m in MONTH_OPTIONS"
          :key="m"
          type="button"
          class="rounded-pill px-2.5 py-1 text-[12px] transition-colors"
          :class="months === m ? 'bg-ink-700 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
          @click="setMonths(m)"
        >近 {{ m }} 月</button>
      </div>
      <span v-if="overview" class="tag">客户 {{ formatNumber(overview.customers) }}</span>
      <span v-if="overview" class="tag">订阅 {{ formatNumber(overview.subscriptions) }}</span>
      <span v-if="updatedText" class="hidden text-[11px] text-ink-400 sm:inline">更新于 {{ updatedText }}</span>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <button class="btn-ghost" :disabled="loading" @click="loadAll">
          {{ loading ? '加载中…' : '刷新指标' }}
        </button>
        <button class="btn-outline" @click="emit('go', 'invoices')">查看发票</button>
      </div>
    </div>

    <!-- 端点缺失：降级为空态，不阻塞其余卡片 -->
    <div
      v-if="unavailable.length"
      class="card flex flex-wrap items-center gap-2 border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800"
    >
      <span class="min-w-0 flex-1">
        以下统计端点缺失或方法不可用：{{ unavailable.join('、') }}。对应卡片已降级为空态，其余数据仍来自真实接口。
      </span>
      <button class="btn-outline px-2 py-0.5" @click="loadAll">重试</button>
    </div>

    <!-- 整体错误：全部接口失败时才阻断 -->
    <div
      v-if="error"
      class="card flex flex-wrap items-center gap-2 border-rose-200 bg-rose-50 p-3 text-[12px] text-rose-600"
    >
      <span class="min-w-0 flex-1">收入总览加载失败：{{ error }}</span>
      <button class="btn-outline px-2 py-0.5" @click="loadAll">重试</button>
    </div>

    <!-- 六个核心指标 -->
    <StatsGrid
      :items="statItems"
      :columns="6"
      :loading="loading && !loadedOnce"
      :skeleton-count="6"
    />

    <!-- 收入趋势与套餐分布 -->
    <div class="grid gap-3 lg:grid-cols-3">
      <SectionCard
        class="lg:col-span-2"
        title="收入趋势"
        :subtitle="`最近 ${months} 个自然月的已收款与发票张数，金额按月汇总`"
      >
        <template #actions>
          <span class="tag">合计 {{ formatMoney(trend.total) }}</span>
          <span class="tag bg-brand-50 text-brand-700">{{ trend.items?.length || 0 }} 个月</span>
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
          :format="moneyFormat"
          aria-label="月度收入趋势"
          empty-text="窗口内还没有已收款发票，生成并结清发票后会出现趋势"
        />
        <template #footer>
          <div class="flex flex-wrap items-center gap-3">
            <span>月均 {{ formatMoney(trendAvg) }}</span>
            <span>最高 {{ formatMoney(trendMax) }}</span>
            <span>最近月 {{ trend.items?.length ? formatMoney(trend.items[trend.items.length - 1].revenue) : '—' }}</span>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="按套餐分布" subtitle="在服订阅的 MRR 占比，中心为总 MRR">
        <template #actions>
          <span class="tag">{{ planRows.length }} 个套餐</span>
        </template>
        <div v-if="loading && !loadedOnce" class="grid h-[180px] place-items-center text-[12px] text-ink-400">加载中…</div>
        <DonutChart
          v-else
          :data="planData"
          :size="150"
          :thickness="16"
          :center-value="formatMoney(distribution.total_mrr)"
          center-label="总 MRR"
          legend-position="bottom"
          empty-text="暂无在服订阅，按套餐分布为空"
          aria-label="套餐收入占比"
        />
      </SectionCard>
    </div>

    <!-- 订阅状态分布、下期预测、回款质量 -->
    <div class="grid gap-3 lg:grid-cols-3">
      <SectionCard title="订阅状态分布" subtitle="试用、生效、逾期、暂停与取消的数量占比">
        <template #actions>
          <span class="tag">共 {{ formatNumber(subscriptionTotal) }} 个</span>
        </template>
        <div v-if="loading && !loadedOnce" class="grid h-[180px] place-items-center text-[12px] text-ink-400">加载中…</div>
        <DonutChart
          v-else
          :data="statusData"
          :size="150"
          :thickness="16"
          :center-value="formatNumber(subscriptionTotal)"
          center-label="订阅总数"
          legend-position="bottom"
          empty-text="还没有订阅记录"
          aria-label="订阅状态占比"
        />
      </SectionCard>

      <SectionCard class="lg:col-span-2" title="下期预测" subtitle="固定费月摊 + 近 90 天用量月均，按订阅逐条预测">
        <template #actions>
          <span class="tag">合计 {{ formatMoney(forecast.total) }}</span>
          <span class="tag bg-emerald-50 text-emerald-600">{{ forecast.count || 0 }} 条</span>
        </template>
        <div v-if="loading && !loadedOnce" class="py-8 text-center text-[12px] text-ink-400">预测加载中…</div>
        <div v-else-if="!forecastRows.length" class="py-8 text-center text-[12px] text-ink-400">
          暂无可预测的在服订阅，开通订阅后这里会给出下期收入
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[560px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">客户</th>
                <th class="th">套餐</th>
                <th class="th">币种</th>
                <th class="th">固定费</th>
                <th class="th">用量费</th>
                <th class="th">预测合计</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in forecastRows.slice(0, 6)" :key="row.subscription_id">
                <td class="td max-w-[160px] truncate">{{ row.customer || '—' }}</td>
                <td class="td max-w-[140px] truncate text-ink-500">{{ row.plan || '—' }}</td>
                <td class="td text-[12px] text-ink-500">{{ row.currency || '—' }}</td>
                <td class="td">{{ formatMoney(row.fixed, row.currency) }}</td>
                <td class="td">{{ formatMoney(row.usage, row.currency) }}</td>
                <td class="td font-medium text-ink-800">{{ formatMoney(row.forecast, row.currency) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <template #footer>
          <div class="flex flex-wrap items-center gap-3">
            <span v-for="(amount, cur) in forecast.by_currency || {}" :key="cur">
              {{ cur }} {{ formatMoney(amount, cur) }}
            </span>
            <span v-if="!forecastRows.length" class="text-ink-400">预测窗口 {{ forecast.horizon_days || 30 }} 天</span>
            <button class="ml-auto text-brand-600" @click="emit('go', 'subscriptions')">前往订阅页核对</button>
          </div>
        </template>
      </SectionCard>
    </div>

    <!-- 回款质量与币种构成 -->
    <div class="grid gap-3 lg:grid-cols-3">
      <SectionCard title="回款质量" subtitle="逾期金额占全部未结金额的比例">
        <div class="grid grid-cols-2 gap-2">
          <div class="rounded-control bg-ink-50 px-3 py-2">
            <div class="text-[11px] text-ink-400">未结金额</div>
            <div class="mt-0.5 text-[16px] font-semibold text-ink-800">{{ formatMoney(delinquency.outstanding) }}</div>
          </div>
          <div class="rounded-control bg-rose-50 px-3 py-2">
            <div class="text-[11px] text-rose-500">其中逾期</div>
            <div class="mt-0.5 text-[16px] font-semibold text-rose-600">{{ formatMoney(delinquency.overdue) }}</div>
          </div>
          <div class="rounded-control bg-ink-50 px-3 py-2">
            <div class="text-[11px] text-ink-400">未结发票</div>
            <div class="mt-0.5 text-[16px] font-semibold text-ink-800">{{ formatNumber(delinquency.open_invoices) }}</div>
          </div>
          <div class="rounded-control bg-amber-50 px-3 py-2">
            <div class="text-[11px] text-amber-600">逾期发票</div>
            <div class="mt-0.5 text-[16px] font-semibold text-amber-700">{{ formatNumber(delinquency.overdue_invoices) }}</div>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <span v-for="(bucket, cur) in delinquency.by_currency || {}" :key="cur" class="tag">
            {{ cur }} 逾期率 {{ ratioText(bucket.rate) }}
          </span>
        </div>
        <template #footer>
          <button class="text-brand-600" @click="emit('go', 'invoices')">去处理逾期发票</button>
        </template>
      </SectionCard>

      <SectionCard title="币种构成" subtitle="MRR 与 ARR 按结算币种拆分">
        <div v-if="!mrrRows.length" class="py-6 text-center text-[12px] text-ink-400">暂无在服订阅收入</div>
        <ul v-else class="divide-y divide-ink-50">
          <li v-for="row in mrrRows" :key="row.currency" class="flex items-center gap-2 py-1.5 text-[12px]">
            <span class="w-14 shrink-0 font-mono text-ink-500">{{ row.currency }}</span>
            <span class="flex-1 text-right text-ink-800">{{ formatMoney(row.mrr, row.currency) }}</span>
            <span class="w-24 shrink-0 text-right text-[11px] text-ink-400">
              ARR {{ formatMoney(row.arr, row.currency) }}
            </span>
          </li>
        </ul>
        <template #footer>
          <span>MRR 合计 {{ formatMoney(mrr.mrr) }} · ARR 合计 {{ formatMoney(arr.arr || mrr.arr) }}</span>
        </template>
      </SectionCard>

      <SectionCard title="转化与流失" subtitle="试用转化率与窗口内取消情况">
        <div class="space-y-2 text-[12px]">
          <div class="flex items-center justify-between rounded-control bg-ink-50 px-3 py-2">
            <span class="text-ink-500">试用结束</span>
            <span class="font-medium text-ink-800">{{ formatNumber(trial.trials_ended) }} 个</span>
          </div>
          <div class="flex items-center justify-between rounded-control bg-emerald-50 px-3 py-2">
            <span class="text-emerald-600">转为付费</span>
            <span class="font-medium text-emerald-700">{{ formatNumber(trial.converted) }} 个</span>
          </div>
          <div class="flex items-center justify-between rounded-control bg-rose-50 px-3 py-2">
            <span class="text-rose-500">窗口内取消</span>
            <span class="font-medium text-rose-600">{{ formatNumber(churn.canceled) }} 个</span>
          </div>
          <div class="flex items-center justify-between rounded-control bg-amber-50 px-3 py-2">
            <span class="text-amber-600">期初在服基数</span>
            <span class="font-medium text-amber-700">{{ formatNumber(churn.base) }} 个</span>
          </div>
        </div>
        <template #footer>
          <span>转化率 {{ ratioText(trial.conversion_rate) }} · 流失率 {{ ratioText(churn.churn_rate) }}</span>
        </template>
      </SectionCard>
    </div>

    <!-- 最近发票 -->
    <SectionCard title="最近发票" subtitle="按创建时间倒序，点击行进入发票页签查看行项与收款">
      <template #actions>
        <button class="btn-ghost px-2 text-[12px]" :disabled="recentLoading" @click="loadRecent">
          {{ recentLoading ? '刷新中…' : '刷新' }}
        </button>
        <button class="btn-outline px-2 text-[12px]" @click="emit('go', 'invoices')">全部发票</button>
      </template>
      <div
        v-if="recentError"
        class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ recentError }}</span>
        <button class="font-medium" @click="loadRecent">重试</button>
      </div>
      <div v-else-if="recentLoading && !recentInvoices.length" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="!recentInvoices.length" class="py-8 text-center text-[12px] text-ink-400">
        还没有发票，先到发票页签按订阅生成一张
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[780px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th">发票编号</th>
              <th class="th">客户</th>
              <th class="th">状态</th>
              <th class="th">账单周期</th>
              <th class="th">总额</th>
              <th class="th">待收</th>
              <th class="th">到期日</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr
              v-for="row in recentInvoices"
              :key="row.id"
              class="cursor-pointer hover:bg-ink-50/60"
              @click="emit('go', 'invoices')"
            >
              <td class="td font-mono text-[12px] text-ink-600">{{ row.number || '—' }}</td>
              <td class="td max-w-[180px] truncate">{{ row.customer_name || '—' }}</td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(row.status))">{{ row.status_label || row.status }}</span>
                <span v-if="row.is_overdue" class="tag ml-1 bg-rose-50 text-rose-600">逾期</span>
              </td>
              <td class="td text-[12px] text-ink-500">{{ periodText(row) }}</td>
              <td class="td">{{ formatMoney(row.total, row.currency) }}</td>
              <td class="td">{{ formatMoney(row.amount_due, row.currency) }}</td>
              <td class="td text-[12px] text-ink-500">{{ formatDate(row.due_date) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <template #footer>
        <span>共 {{ formatNumber(recentCount) }} 张发票；最近 {{ recentInvoices.length }} 张展示在此</span>
      </template>
    </SectionCard>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { billingApi } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
  statusTone,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import LineChart from '../../components/platform/LineChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])
const app = useAppStore()

const DAY_OPTIONS = [30, 90, 180]
const MONTH_OPTIONS = [6, 12, 24]

const churnDays = ref(30)
const months = ref(12)
const loading = ref(false)
const loadedOnce = ref(false)
const error = ref('')
const unavailable = ref([])
const updatedAt = ref(null)

const overview = ref({})
const mrr = ref({})
const arr = ref({})
const arpu = ref({})
const churn = ref({})
const trial = ref({})
const delinquency = ref({})
const trend = ref({ items: [] })
const distribution = ref({ items: [] })
const forecast = ref({ items: [], by_currency: {} })

const recentInvoices = ref([])
const recentCount = ref(0)
const recentLoading = ref(false)
const recentError = ref('')

const moneyFormat = (value) => formatMoney(value)
const updatedText = computed(() => (updatedAt.value ? formatDate(updatedAt.value, true) : ''))

function ratioText(value, digits = 1) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  const pctValue = n <= 1 ? n * 100 : n
  return `${pctValue.toFixed(digits)}%`
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function isUnavailable(e) {
  const status = Number(e?.status || e?.response?.status || 0)
  const message = String(e?.message || '')
  return status === 404 || status === 405 || /not found|method not allowed|405/i.test(message)
}

function periodText(row) {
  if (!row?.period_start && !row?.period_end) return '—'
  return `${row.period_start || '—'} ~ ${row.period_end || '—'}`
}

const statItems = computed(() => {
  const o = overview.value || {}
  const m = mrr.value || {}
  const a = arr.value || {}
  const p = arpu.value || {}
  const c = churn.value || {}
  const t = trial.value || {}
  const d = delinquency.value || {}
  return [
    {
      key: 'mrr',
      label: 'MRR 月度经常性收入',
      value: formatMoney(m.mrr ?? o.mrr),
      hint: `在服订阅 ${formatNumber(m.subscription_count)} 个`,
      tone: 'brand',
    },
    {
      key: 'arr',
      label: 'ARR 年度经常性收入',
      value: formatMoney(a.arr ?? o.arr),
      hint: 'MRR × 12，按币种放大',
      tone: 'emerald',
    },
    {
      key: 'arpu',
      label: 'ARPU 每客户月均收入',
      value: formatMoney(p.arpu),
      hint: `付费客户 ${formatNumber(p.customer_count)} 个`,
      tone: 'brand',
    },
    {
      key: 'churn',
      label: '流失率',
      value: ratioText(c.churn_rate ?? o.churn_rate),
      hint: `近 ${c.window_days || churnDays.value} 天取消 ${formatNumber(c.canceled)} 个`,
      tone: 'rose',
    },
    {
      key: 'delinquency',
      label: '逾期率',
      value: ratioText(d.delinquency_rate ?? o.delinquency_rate),
      hint: `逾期 ${formatMoney(d.overdue)} / 未结 ${formatMoney(d.outstanding)}`,
      tone: 'amber',
    },
    {
      key: 'trial',
      label: '试用转化率',
      value: ratioText(t.conversion_rate ?? o.trial_conversion_rate),
      hint: `试用结束 ${formatNumber(t.trials_ended)} 个 · 转化 ${formatNumber(t.converted)} 个`,
      tone: 'emerald',
    },
  ]
})

const trendLabels = computed(() =>
  (trend.value?.items || []).map((row) => String(row.month || ''))
)

const trendSeries = computed(() => [
  {
    name: '已收款',
    color: 'var(--brand-500)',
    area: true,
    data: (trend.value?.items || []).map((row) => Number(row.revenue) || 0),
  },
])

const trendAvg = computed(() => {
  const rows = trend.value?.items || []
  if (!rows.length) return 0
  return rows.reduce((sum, row) => sum + (Number(row.revenue) || 0), 0) / rows.length
})

const trendMax = computed(() => {
  const rows = trend.value?.items || []
  return rows.reduce((max, row) => Math.max(max, Number(row.revenue) || 0), 0)
})

const planRows = computed(() => (distribution.value?.items || []))
const planData = computed(() =>
  planRows.value.map((row) => ({
    label: row.name || row.plan || `套餐 ${row.plan_id}`,
    value: Number(row.mrr) || 0,
  }))
)

const SUBSCRIPTION_STATUS = {
  trialing: '试用中',
  active: '生效中',
  past_due: '逾期',
  canceled: '已取消',
  paused: '已暂停',
}

const STATUS_COLORS = {
  trialing: '#f59e0b',
  active: '#10b981',
  past_due: '#f43f5e',
  canceled: '#94a3b8',
  paused: '#6366f1',
}

const statusRows = computed(() => {
  const raw = overview.value?.subscriptions_by_status || {}
  return Object.entries(raw).map(([status, count]) => ({
    status,
    label: SUBSCRIPTION_STATUS[status] || status,
    count: Number(count) || 0,
    color: STATUS_COLORS[status] || '#cbd5e1',
  }))
})

const statusData = computed(() =>
  statusRows.value.map((row) => ({ label: row.label, value: row.count, color: row.color }))
)

const subscriptionTotal = computed(() =>
  statusRows.value.reduce((sum, row) => sum + row.count, 0)
)

const forecastRows = computed(() => (forecast.value?.items || []))

const mrrRows = computed(() => {
  const byCurrency = mrr.value?.by_currency || {}
  const arrByCurrency = arr.value?.by_currency || {}
  return Object.entries(byCurrency).map(([currency, amount]) => ({
    currency,
    mrr: amount,
    arr: arrByCurrency[currency] ?? (Number(amount) || 0) * 12,
  }))
})

function assign(key, value) {
  const map = {
    overview,
    mrr,
    arr,
    arpu,
    churn,
    trial,
    delinquency,
    trend,
    distribution,
    forecast,
  }
  if (map[key]) map[key].value = value
}

async function loadAll() {
  loading.value = true
  error.value = ''
  unavailable.value = []
  const entries = [
    ['overview', 'stats/overview/'],
    ['mrr', 'stats/mrr/'],
    ['arr', 'stats/arr/'],
    ['arpu', 'stats/arpu/'],
    ['churn', `stats/churn/?days=${churnDays.value}`],
    ['trial', `stats/trial-conversion/?days=${churnDays.value}`],
    ['delinquency', 'stats/delinquency/'],
    ['trend', `stats/revenue-trend/?months=${months.value}`],
    ['distribution', 'stats/plan-distribution/'],
    ['forecast', 'stats/forecast/'],
  ]
  const results = await Promise.allSettled(entries.map((entry) => billingApi.get(entry[1])))
  const failed = []
  const missing = []
  results.forEach((result, index) => {
    const key = entries[index][0]
    if (result.status === 'fulfilled') {
      assign(key, result.value || {})
      return
    }
    const reason = result.reason
    failed.push(`${entries[index][1]}：${reason?.message || '请求失败'}`)
    if (isUnavailable(reason)) missing.push(entries[index][1])
  })
  unavailable.value = missing
  if (failed.length === entries.length) {
    error.value = failed[0] || '全部统计接口不可用'
    app.toastMsg(error.value, 'error')
  } else if (failed.length) {
    app.toastMsg(`部分统计接口失败 ${failed.length} 个，已降级展示`, 'warning')
  }
  updatedAt.value = new Date()
  loadedOnce.value = true
  loading.value = false
}

async function loadRecent() {
  recentLoading.value = true
  recentError.value = ''
  try {
    const data = await billingApi.list('invoices/', { page: 1, page_size: 8 })
    recentInvoices.value = data.items || []
    recentCount.value = data.count || 0
  } catch (e) {
    recentError.value = isUnavailable(e)
      ? '发票端点缺失（404/405），最近发票降级为空态'
      : (e?.message || '最近发票加载失败')
    recentInvoices.value = []
    recentCount.value = 0
  } finally {
    recentLoading.value = false
  }
}

function setChurnDays(value) {
  if (churnDays.value === value) return
  churnDays.value = value
  loadAll()
}

function setMonths(value) {
  if (months.value === value) return
  months.value = value
  loadAll()
}

watch(() => props.reloadToken, () => {
  loadAll()
  loadRecent()
})

onMounted(() => {
  loadAll()
  loadRecent()
})
</script>