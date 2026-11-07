<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <PageHeader
      title="合同中心"
      subtitle="模板条款、审批签署、履约义务、收付款与到期续约的统一工作台，数据全部来自 /contracts 真实接口"
      :crumbs="[{ label: '平台能力' }, { label: '合同中心' }]"
    >
      <template #badge>
        <span class="tag-brand">合同 {{ countText(counts.contracts) }}</span>
        <span class="tag bg-amber-50 text-amber-600">30 天到期 {{ countText(counts.expiring) }}</span>
        <span class="tag bg-rose-50 text-rose-600">逾期义务 {{ countText(counts.overdueObligations) }}</span>
      </template>
      <template #actions>
        <button class="btn-ghost" type="button" :disabled="refreshing" @click="refreshAll">
          {{ refreshing ? '刷新中…' : '刷新数据' }}
        </button>
        <button class="btn-primary" type="button" @click="createContract">新建合同</button>
      </template>
    </PageHeader>

    <!-- 五个页签：总览 / 台账 / 履约 / 收付款 / 模板条款 -->
    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="t in tabs"
        :key="t.key"
        type="button"
        class="rounded-pill px-3 py-1 text-[12px] transition-colors"
        :class="tab === t.key ? 'bg-brand-600 text-white' : 'border border-ink-200 bg-white text-ink-600 hover:border-brand-300'"
        @click="switchTab(t.key)"
      >
        {{ t.label }}
        <span
          v-if="tabCount(t.key) !== ''"
          class="ml-1 text-[11px]"
          :class="tab === t.key ? 'text-white/80' : 'text-ink-400'"
        >{{ tabCount(t.key) }}</span>
      </button>
      <span class="ml-auto text-[11px] text-ink-400">
        计数更新于 {{ countsUpdated || '—' }} · 接口前缀 /api/contracts
      </span>
    </div>

    <div
      v-if="countsError"
      class="flex flex-wrap items-center gap-2 rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700"
    >
      <span class="min-w-0 flex-1">{{ countsError }}</span>
      <button class="btn-ghost shrink-0 px-2 text-[12px] text-amber-700" type="button" @click="loadCounts">重试计数</button>
    </div>

    <!-- 一、合同总览 -->
    <OverviewTab
      v-if="tab === 'overview'"
      :refresh-key="refreshKey"
      @open-contract="openContract"
      @go-tab="switchTab"
    />

    <!-- 二、合同台账 -->
    <ContractLedger
      v-else-if="tab === 'contracts'"
      ref="ledgerRef"
      :refresh-key="refreshKey"
      @changed="onChanged"
    />

    <!-- 三、履约义务 -->
    <ObligationsTab
      v-else-if="tab === 'obligations'"
      :refresh-key="refreshKey"
      @changed="onChanged"
    />

    <!-- 四、收付款 -->
    <FinanceTab
      v-else-if="tab === 'finance'"
      :refresh-key="refreshKey"
      @changed="onChanged"
    />

    <!-- 五、模板条款 -->
    <TemplatesTab
      v-else-if="tab === 'templates'"
      :refresh-key="refreshKey"
      @changed="onChanged"
    />

    <p class="pb-2 text-[11px] leading-relaxed text-ink-400">
      数据来源：/contracts/stats/overview · /contracts/contracts · /contracts/obligations ·
      /contracts/finance/summary · /contracts/templates · /contracts/clauses/library
    </p>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { contractsApi } from '../../api/platform'
import { findDomain } from '../../api/domains'
import { formatDate } from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import PageHeader from '../../components/platform/PageHeader.vue'
import OverviewTab from './OverviewTab.vue'
import ContractLedger from './ContractLedger.vue'
import ObligationsTab from './ObligationsTab.vue'
import FinanceTab from './FinanceTab.vue'
import TemplatesTab from './TemplatesTab.vue'

const app = useAppStore()

// 页签名称从能力域目录读取，避免与侧边栏、路由 title 漂移
const domain = findDomain('contracts')
const tabs = domain?.tabs || [
  { key: 'overview', label: '合同总览' },
  { key: 'contracts', label: '合同台账' },
  { key: 'obligations', label: '履约义务' },
  { key: 'finance', label: '收付款' },
  { key: 'templates', label: '模板条款' },
]

const tab = ref('overview')
const refreshKey = ref(0)
const refreshing = ref(false)
const ledgerRef = ref(null)

const counts = ref({
  contracts: 0,
  expiring: 0,
  obligations: 0,
  overdueObligations: 0,
  payments: 0,
  templates: 0,
})
const countsError = ref('')
const countsUpdated = ref('')

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

function countText(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n > 9999 ? '9999+' : String(n)
}

function tabCount(key) {
  if (key === 'contracts') return counts.value.contracts ? countText(counts.value.contracts) : ''
  if (key === 'obligations') return counts.value.obligations ? countText(counts.value.obligations) : ''
  if (key === 'finance') return counts.value.payments ? countText(counts.value.payments) : ''
  if (key === 'templates') return counts.value.templates ? countText(counts.value.templates) : ''
  return ''
}

function switchTab(next) {
  if (!next || next === tab.value) return
  tab.value = next
}

/** 计数接口缺失时依次回落到各列表的 count，避免顶部徽标空白 */
async function loadCounts() {
  countsError.value = ''
  try {
    const data = await contractsApi.get('counts/')
    counts.value = {
      contracts: numOf(data, ['contracts', 'contract', 'total', 'totals.contracts']),
      expiring: numOf(data, ['expiring', 'expiring_30d', 'expiring30', 'totals.expiring']),
      obligations: numOf(data, ['obligations', 'obligation', 'totals.obligations']),
      overdueObligations: numOf(data, ['overdue_obligations', 'obligations_overdue', 'totals.overdue_obligations']),
      payments: numOf(data, ['payments', 'payment', 'totals.payments']),
      templates: numOf(data, ['templates', 'template', 'totals.templates']),
    }
    countsUpdated.value = formatDate(new Date(), true)
    return
  } catch (e) {
    countsError.value = e?.message || '合同计数接口暂不可用，已回落到列表计数'
  }

  const [contracts, expiring, overdue] = await Promise.allSettled([
    contractsApi.list('contracts/', { page: 1, page_size: 1 }),
    contractsApi.list('contracts/expiring/', { page: 1, page_size: 1, days: 30 }),
    contractsApi.list('obligations/overdue/', { page: 1, page_size: 1 }),
  ])
  counts.value = {
    contracts: contracts.status === 'fulfilled' ? Number(contracts.value.count) || 0 : 0,
    expiring: expiring.status === 'fulfilled' ? Number(expiring.value.count) || 0 : 0,
    obligations: counts.value.obligations,
    overdueObligations: overdue.status === 'fulfilled' ? Number(overdue.value.count) || 0 : 0,
    payments: counts.value.payments,
    templates: counts.value.templates,
  }
  countsUpdated.value = formatDate(new Date(), true)
}

async function refreshAll() {
  refreshing.value = true
  try {
    refreshKey.value += 1
    await loadCounts()
    if (tab.value === 'overview') app.toastMsg('已刷新合同总览', 'success')
  } finally {
    refreshing.value = false
  }
}

function onChanged() {
  loadCounts()
}

function openContract(id) {
  tab.value = 'contracts'
  nextTick(() => ledgerRef.value?.openDetail(id))
}

function createContract() {
  tab.value = 'contracts'
  nextTick(() => ledgerRef.value?.openCreate())
}

onMounted(() => {
  loadCounts()
})
</script>