<template>
  <section class="space-y-3">
    <div
      v-if="summaryError"
      class="flex flex-wrap items-center gap-3 rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700"
    >
      <span class="min-w-0 flex-1">{{ summaryError }}</span>
      <button class="btn-ghost shrink-0 px-2 text-[12px] text-amber-700" type="button" @click="loadSummary">重试</button>
    </div>

    <StatsGrid :items="statItems" :loading="summaryLoading || planLoading" :skeleton-count="4" />

    <div class="grid gap-3 lg:grid-cols-2">
      <!-- 金额汇总 -->
      <div class="card p-3">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-[13px] font-medium text-ink-800">金额汇总（按币种）</h3>
          <span class="text-[11px] text-ink-400">/contracts/finance/summary</span>
        </div>
        <div v-if="summaryLoading && !summaryRows.length" class="space-y-2">
          <div v-for="n in 3" :key="n" class="h-7 animate-pulse rounded bg-ink-100" />
        </div>
        <div v-else-if="!summaryRows.length" class="py-8 text-center text-[12px] text-ink-400">
          暂无金额汇总数据，先为合同生成付款计划
        </div>
        <table v-else class="w-full">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">币种</th>
              <th class="th text-right">计划金额</th>
              <th class="th text-right">已付金额</th>
              <th class="th text-right">未付金额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in summaryRows" :key="row.currency" class="border-b border-ink-50 last:border-0">
              <td class="td">{{ row.currency }}</td>
              <td class="td text-right">{{ formatMoney(row.plan, row.currency) }}</td>
              <td class="td text-right text-emerald-600">{{ formatMoney(row.paid, row.currency) }}</td>
              <td class="td text-right text-amber-600">{{ formatMoney(row.pending, row.currency) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="mt-2 text-[11px] text-ink-400">
          金额口径为付款计划金额，未做跨币种折算；样本来自 {{ summarySource }}
        </p>
      </div>

      <!-- 逾期统计 -->
      <div class="card p-3">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-[13px] font-medium text-ink-800">逾期统计</h3>
          <button class="text-[11px] text-brand-600" type="button" @click="loadOverdue">刷新</button>
        </div>
        <div class="mb-2 flex flex-wrap gap-2 text-[11px]">
          <span class="tag bg-rose-50 text-rose-600">逾期 {{ formatNumber(overdueRows.length) }} 笔</span>
          <span class="tag bg-amber-50 text-amber-600">逾期金额 {{ overdueAmountText }}</span>
          <span class="tag">统计窗口 当前逾期</span>
        </div>
        <div v-if="overdueLoading" class="space-y-2">
          <div v-for="n in 3" :key="n" class="h-8 animate-pulse rounded bg-ink-100" />
        </div>
        <div v-else-if="overdueError" class="rounded-control bg-rose-50 px-2 py-2 text-[11px] text-rose-600">
          <div class="truncate">{{ overdueError }}</div>
          <button class="mt-1 font-medium" type="button" @click="loadOverdue">重试</button>
        </div>
        <div v-else-if="!overdueRows.length" class="py-8 text-center text-[12px] text-ink-400">暂无逾期付款</div>
        <div v-else class="max-h-[220px] space-y-1 overflow-y-auto">
          <div
            v-for="row in overdueRows"
            :key="row.id"
            class="flex flex-wrap items-center gap-2 rounded-control border border-rose-100 bg-rose-50/40 px-2 py-1.5 text-[12px]"
          >
            <span class="min-w-0 flex-1 truncate">
              第 {{ row.period_no ?? '—' }} 期 · 计划 {{ formatDate(row.plan_date) }}
            </span>
            <span class="text-rose-600">{{ formatMoney(row.plan_amount, row.currency || 'CNY') }}</span>
            <button class="text-brand-600 hover:underline" type="button" @click="openPay(row)">登记实付</button>
          </div>
        </div>
        <p class="mt-2 text-[11px] text-ink-400">接口 /contracts/payments/overdue</p>
      </div>
    </div>

    <!-- 付款计划列表 -->
    <div class="card p-3">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <h3 class="text-[13px] font-medium text-ink-800">付款计划</h3>
        <span class="text-[11px] text-ink-400">最近 {{ planContracts }} 份合同的付款期次</span>
        <label class="ml-auto flex items-center gap-1.5 text-[12px] text-ink-500">
          状态
          <select v-model="statusFilter" class="input w-[130px] py-1">
            <option value="">全部状态</option>
            <option value="planned">计划中</option>
            <option value="partial">部分支付</option>
            <option value="paid">已支付</option>
            <option value="overdue">已逾期</option>
            <option value="cancelled">已取消</option>
          </select>
        </label>
        <button class="btn-outline px-2 py-1" type="button" :disabled="planLoading" @click="loadPlans">
          {{ planLoading ? '加载中…' : '刷新' }}
        </button>
      </div>

      <div
        v-if="planError"
        class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ planError }}</span>
        <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="loadPlans">重试</button>
      </div>

      <div v-if="planLoading && !planRows.length" class="space-y-2">
        <div v-for="n in 6" :key="n" class="h-8 animate-pulse rounded bg-ink-100" />
      </div>
      <div v-else-if="!planLoading && !planRows.length && !planError" class="py-10 text-center text-[12px] text-ink-400">
        <p>暂无付款计划</p>
        <p class="mt-1">可在合同详情中生成付款计划，或在合同创建后补充期次</p>
      </div>

      <div v-else-if="planRows.length" class="overflow-x-auto">
        <table class="w-full min-w-[860px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">合同</th>
              <th class="th">期次</th>
              <th class="th text-right">计划金额</th>
              <th class="th text-right">实付金额</th>
              <th class="th">计划日</th>
              <th class="th">实付日</th>
              <th class="th">状态</th>
              <th class="th w-[130px]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in pagedRows" :key="`${row.contract}-${row.id}`" class="border-b border-ink-50 last:border-0 hover:bg-ink-50/60">
              <td class="td max-w-[200px]">
                <div class="truncate text-ink-800">{{ row.contract_name || '未命名合同' }}</div>
                <div class="font-mono text-[11px] text-ink-400">{{ row.contract_number || `#${row.contract}` }}</div>
              </td>
              <td class="td">第 {{ row.period_no ?? '—' }} 期</td>
              <td class="td text-right">{{ formatMoney(row.plan_amount, row.currency || 'CNY') }}</td>
              <td class="td text-right text-ink-500">{{ formatMoney(row.paid_amount, row.currency || 'CNY') }}</td>
              <td class="td whitespace-nowrap text-ink-500">{{ formatDate(row.plan_date) }}</td>
              <td class="td whitespace-nowrap text-ink-500">{{ formatDate(row.paid_date) }}</td>
              <td class="td">
                <span class="tag" :class="tagClass(paymentTone(row))">{{ paymentLabel(row) }}</span>
              </td>
              <td class="td">
                <div class="flex flex-wrap items-center gap-1">
                  <button
                    v-if="!['paid', 'cancelled'].includes(row.status)"
                    class="text-[12px] text-brand-600 hover:underline"
                    type="button"
                    @click="openPay(row)"
                  >登记实付</button>
                  <button
                    v-if="!['paid', 'cancelled'].includes(row.status)"
                    class="text-[12px] text-ink-500 hover:text-rose-600"
                    type="button"
                    @click="openCancel(row)"
                  >取消</button>
                  <span v-if="row.status === 'paid'" class="text-[11px] text-ink-400">已结清</span>
                  <span v-else-if="row.status === 'cancelled'" class="text-[11px] text-ink-400">已取消</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="filteredRows.length" class="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <span>第 {{ page }} / {{ pages }} 页</span>
        <button class="btn-outline px-2 py-1" type="button" :disabled="page <= 1" @click="page -= 1">上一页</button>
        <button class="btn-outline px-2 py-1" type="button" :disabled="page >= pages" @click="page += 1">下一页</button>
        <span>共 {{ formatNumber(filteredRows.length) }} 期</span>
        <span v-if="planLoading" class="text-brand-600">加载中…</span>
      </div>
    </div>

    <!-- 登记实付 -->
    <Modal :show="payModal.show" title="登记实付" width="440px" @close="closePay">
      <div class="space-y-3">
        <div class="rounded-control bg-ink-50 px-2 py-1.5 text-[12px] text-ink-700">
          <div class="truncate">{{ payModal.row?.contract_name || '未命名合同' }}</div>
          <div class="text-[11px] text-ink-500">
            第 {{ payModal.row?.period_no ?? '—' }} 期 · 计划
            {{ formatMoney(payModal.row?.plan_amount, payModal.row?.currency || 'CNY') }}
          </div>
        </div>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">实付金额</span>
          <input v-model="payForm.paid_amount" class="input" type="number" min="0" step="0.01" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">实际付款日期</span>
          <input v-model="payForm.paid_date" class="input" type="date" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">备注</span>
          <input v-model.trim="payForm.remark" class="input" maxlength="200" placeholder="付款渠道、流水号等，可留空" />
        </label>
        <p v-if="payError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ payError }}</p>
        <div class="flex items-center justify-end gap-2">
          <button class="btn-ghost" type="button" @click="closePay">取消</button>
          <button class="btn-primary" type="button" :disabled="paying" @click="confirmPay">
            {{ paying ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 取消付款 -->
    <Modal :show="cancelModal.show" title="取消付款期次" width="420px" @close="closeCancel">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">
          确认取消第 {{ cancelModal.row?.period_no ?? '—' }} 期付款计划？取消后可在合同详情中重新生成。
        </p>
        <div class="flex items-center justify-end gap-2">
          <button class="btn-ghost" type="button" @click="closeCancel">返回</button>
          <button class="btn-danger" type="button" :disabled="paying" @click="confirmCancel">
            {{ paying ? '处理中…' : '确认取消' }}
          </button>
        </div>
      </div>
    </Modal>
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
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import StatsGrid from '../../components/platform/StatsGrid.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['changed'])

const app = useAppStore()

const PAYMENT_LABELS = {
  planned: '计划中',
  partial: '部分支付',
  paid: '已支付',
  overdue: '已逾期',
  cancelled: '已取消',
}

const summary = ref(null)
const summaryLoading = ref(false)
const summaryError = ref('')
const summaryFallback = ref([])

const planRows = ref([])
const planLoading = ref(false)
const planError = ref('')
const planContracts = ref(0)

const overdueRows = ref([])
const overdueLoading = ref(false)
const overdueError = ref('')

const statusFilter = ref('')
const page = ref(1)
const pageSize = 10

const payModal = ref({ show: false, row: null })
const payForm = ref({ paid_amount: '', paid_date: '', remark: '' })
const payError = ref('')
const paying = ref(false)

const cancelModal = ref({ show: false, row: null })

function rowsOf(value) {
  if (Array.isArray(value)) return value.filter((row) => row && typeof row === 'object')
  if (Array.isArray(value?.items)) return value.items.filter((row) => row && typeof row === 'object')
  if (Array.isArray(value?.rows)) return value.rows.filter((row) => row && typeof row === 'object')
  return []
}

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

const summaryRows = computed(() => {
  const direct = pick(summary.value, ['by_currency', 'currencies', 'currency_rows', 'groups', 'items', 'rows'], [])
  const rows = rowsOf(direct)
  if (rows.length) {
    return rows.map((row) => {
      const plan = Number(row.plan_amount ?? row.plan ?? row.total ?? row.amount ?? 0) || 0
      const paid = Number(row.paid_amount ?? row.paid ?? row.received ?? 0) || 0
      return {
        currency: row.currency || row.key || row.code || 'CNY',
        plan,
        paid,
        pending: Number(row.pending_amount ?? row.pending ?? Math.max(0, plan - paid)) || 0,
        count: Number(row.count ?? row.periods ?? 0) || 0,
      }
    })
  }
  return summaryFallback.value
})

const summarySource = computed(() => (summaryRows.value.length ? (summary.value ? 'finance/summary 接口' : '付款计划聚合') : '暂无'))

const overdueAmountText = computed(() => {
  if (!overdueRows.value.length) return formatMoney(0, 'CNY')
  const bucket = new Map()
  for (const row of overdueRows.value) {
    const currency = row.currency || 'CNY'
    const amount = Number(row.plan_amount ?? row.amount ?? 0) || 0
    bucket.set(currency, (bucket.get(currency) || 0) + amount)
  }
  return Array.from(bucket.entries())
    .map(([currency, amount]) => formatMoney(amount, currency))
    .join(' / ')
})

const totalPlan = computed(() => summaryRows.value.reduce((sum, row) => sum + row.plan, 0))
const totalPaid = computed(() => summaryRows.value.reduce((sum, row) => sum + row.paid, 0))
const totalPending = computed(() => summaryRows.value.reduce((sum, row) => sum + row.pending, 0))

const statItems = computed(() => [
  {
    key: 'plan',
    label: '计划金额',
    value: totalPlan.value,
    hint: `覆盖 ${formatNumber(planRows.value.length)} 个付款期次`,
    tone: 'brand',
    format: (v) => formatMoney(v, 'CNY'),
  },
  {
    key: 'paid',
    label: '已付金额',
    value: totalPaid.value,
    hint: totalPlan.value ? `回款率 ${((totalPaid.value / Math.max(1, totalPlan.value)) * 100).toFixed(1)}%` : '暂无付款',
    tone: 'emerald',
    format: (v) => formatMoney(v, 'CNY'),
  },
  {
    key: 'pending',
    label: '未付金额',
    value: totalPending.value,
    hint: '计划金额减去已付金额',
    tone: 'amber',
    format: (v) => formatMoney(v, 'CNY'),
  },
  {
    key: 'overdue',
    label: '逾期期次',
    value: overdueRows.value.length,
    unit: '笔',
    hint: overdueAmountText.value,
    tone: 'rose',
  },
])

const filteredRows = computed(() =>
  statusFilter.value ? planRows.value.filter((row) => row.status === statusFilter.value) : planRows.value
)

const pages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / pageSize)))

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredRows.value.slice(start, start + pageSize)
})

function paymentLabel(row) {
  if (row?.status) return PAYMENT_LABELS[row.status] || row.status
  const plan = Number(row?.plan_amount) || 0
  const paid = Number(row?.paid_amount) || 0
  if (paid >= plan && plan > 0) return '已支付'
  if (paid > 0) return '部分支付'
  const time = row?.plan_date ? new Date(row.plan_date).getTime() : NaN
  if (Number.isFinite(time) && time < Date.now()) return '已逾期'
  return '计划中'
}

function paymentTone(row) {
  const label = paymentLabel(row)
  if (label === '已支付') return 'success'
  if (label === '部分支付') return 'info'
  if (label === '已逾期') return 'danger'
  if (label === '已取消') return 'neutral'
  return 'warning'
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

function buildSummaryFallback(rows) {
  const bucket = new Map()
  for (const row of rows) {
    const currency = row.currency || 'CNY'
    const cur = bucket.get(currency) || { currency, plan: 0, paid: 0, pending: 0, count: 0 }
    const plan = Number(row.plan_amount) || 0
    const paid = Number(row.paid_amount) || 0
    cur.plan += plan
    cur.paid += paid
    cur.pending += Math.max(0, plan - paid)
    cur.count += 1
    bucket.set(currency, cur)
  }
  return Array.from(bucket.values())
}

async function loadSummary() {
  summaryLoading.value = true
  summaryError.value = ''
  try {
    summary.value = await contractsApi.get('finance/summary/')
    const rows = rowsOf(pick(summary.value, ['by_currency', 'currencies', 'groups', 'items', 'rows'], []))
    if (!rows.length) summaryFallback.value = buildSummaryFallback(planRows.value)
  } catch (e) {
    summary.value = null
    summaryFallback.value = buildSummaryFallback(planRows.value)
    summaryError.value = e?.message || '财务汇总接口暂不可用，已按付款计划聚合'
  } finally {
    summaryLoading.value = false
  }
}

async function loadPlans() {
  planLoading.value = true
  planError.value = ''
  try {
    const data = await contractsApi.list('contracts/', { page: 1, page_size: 8, ordering: '-updated_at' })
    const contracts = normalizeList(data).items
    planContracts.value = contracts.length
    if (!contracts.length) {
      planRows.value = []
      summaryFallback.value = []
      return
    }
    const results = await Promise.allSettled(
      contracts.map((contract) =>
        contractsApi.list(`contracts/${contract.id}/payments/`, { page: 1, page_size: 50 }).then((payments) => ({
          contract,
          payments: normalizeList(payments).items,
        }))
      )
    )
    const merged = []
    const failures = []
    for (const result of results) {
      if (result.status !== 'fulfilled') {
        failures.push(result.reason?.message || '付款计划加载失败')
        continue
      }
      const { contract, payments } = result.value
      for (const payment of payments) {
        merged.push({
          ...payment,
          contract: contract.id,
          contract_name: contract.name,
          contract_number: contract.number,
          currency: payment.currency || contract.currency || 'CNY',
        })
      }
    }
    planRows.value = merged
    summaryFallback.value = buildSummaryFallback(merged)
    if (failures.length) planError.value = `部分合同付款计划不可用：${failures[0]}`
  } catch (e) {
    planRows.value = []
    planError.value = e?.message || '付款计划加载失败'
    app.toastMsg(planError.value, 'error')
  } finally {
    planLoading.value = false
  }
}

async function loadOverdue() {
  overdueLoading.value = true
  overdueError.value = ''
  try {
    const data = await contractsApi.list('payments/overdue/', { page: 1, page_size: 20 })
    overdueRows.value = normalizeList(data).items
  } catch (e) {
    overdueRows.value = []
    overdueError.value = e?.message || '逾期统计暂不可用'
  } finally {
    overdueLoading.value = false
  }
}

function openPay(row) {
  payError.value = ''
  const plan = Number(row?.plan_amount) || 0
  const paid = Number(row?.paid_amount) || 0
  payForm.value = {
    paid_amount: plan > paid ? (plan - paid).toFixed(2) : '',
    paid_date: new Date().toISOString().slice(0, 10),
    remark: '',
  }
  payModal.value = { show: true, row }
}

function closePay() {
  payModal.value = { show: false, row: null }
  payError.value = ''
}

async function confirmPay() {
  const row = payModal.value.row
  if (!row) return
  const amount = Number(payForm.value.paid_amount)
  if (!Number.isFinite(amount) || amount <= 0) {
    payError.value = '实付金额需要大于 0'
    return
  }
  paying.value = true
  payError.value = ''
  try {
    await contractsApi.action(`payments/${row.id}/pay/`, {
      paid_amount: amount,
      paid_date: payForm.value.paid_date || null,
      remark: payForm.value.remark,
    })
    app.toastMsg('实付已登记', 'success')
    closePay()
    await Promise.all([loadPlans(), loadSummary(), loadOverdue()])
    emit('changed')
  } catch (e) {
    payError.value = e?.message || '登记实付失败'
    app.toastMsg(payError.value, 'error')
  } finally {
    paying.value = false
  }
}

function openCancel(row) {
  cancelModal.value = { show: true, row }
}

function closeCancel() {
  cancelModal.value = { show: false, row: null }
}

async function confirmCancel() {
  const row = cancelModal.value.row
  if (!row) return
  paying.value = true
  try {
    await contractsApi.action(`payments/${row.id}/cancel/`, {})
    app.toastMsg('付款期次已取消', 'success')
    closeCancel()
    await Promise.all([loadPlans(), loadSummary(), loadOverdue()])
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '取消失败', 'error')
  } finally {
    paying.value = false
  }
}

watch(statusFilter, () => {
  page.value = 1
})

watch(filteredRows, () => {
  if (page.value > pages.value) page.value = pages.value
})

watch(
  () => props.refreshKey,
  () => {
    loadPlans()
    loadSummary()
    loadOverdue()
  }
)

onMounted(async () => {
  await loadPlans()
  loadSummary()
  loadOverdue()
})
</script>