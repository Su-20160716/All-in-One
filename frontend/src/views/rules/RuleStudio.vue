<template>
  <div class="mx-auto max-w-[1400px] space-y-4">
    <PageHeader
      title="规则引擎"
      subtitle="规则集、决策表、表达式求值、冲突检测与仿真测试统一工作台"
      :crumbs="[{ label: '平台' }, { label: '规则引擎' }]"
    >
      <template #actions>
        <div class="flex items-center gap-2">
          <span class="tag-brand">5 个页签</span>
          <button class="btn-outline" :disabled="refreshing" @click="refreshAll">
            {{ refreshing ? '刷新中…' : '刷新全部' }}
          </button>
        </div>
      </template>
    </PageHeader>

    <!-- 页签 + 规则集上下文 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          v-for="t in TABS"
          :key="t.key"
          class="rounded-pill px-3 py-1.5 text-[12px] transition-colors"
          :class="tab === t.key
            ? 'bg-brand-600 text-white'
            : 'border border-ink-200 bg-white text-ink-600 hover:border-brand-300 hover:text-brand-600'"
          @click="switchTab(t.key)"
        >
          {{ t.label }}
        </button>

        <span class="mx-1 hidden h-4 w-px bg-ink-200 sm:block"></span>

        <label class="flex items-center gap-1.5 text-[12px] text-ink-500">
          规则集
          <select v-model="rulesetId" class="input w-[220px] py-1">
            <option value="">全部规则集</option>
            <option v-for="rs in rulesets" :key="rs.id" :value="String(rs.id)">
              {{ rs.name }}（{{ rs.code }}）
            </option>
          </select>
        </label>

        <span v-if="rulesetsLoading" class="tag">规则集加载中…</span>
        <span v-else-if="rulesetsError" class="tag bg-rose-50 text-rose-600">规则集加载失败</span>
        <span v-else-if="!rulesets.length" class="tag">暂无规则集</span>
        <span v-else class="tag">共 {{ rulesets.length }} 个</span>

        <span v-if="selectedRuleSet" class="tag" :class="statusClass(selectedRuleSet.status)">
          {{ selectedRuleSet.status_label || selectedRuleSet.status }}
        </span>
        <span v-if="selectedRuleSet" class="text-[11px] text-ink-400">
          v{{ selectedRuleSet.version_no }} · {{ hitPolicyLabel(selectedRuleSet.hit_policy) }}
        </span>

        <button class="btn-ghost ml-auto py-1 text-[12px]" :disabled="rulesetsLoading" @click="loadRulesets()">
          重新加载规则集
        </button>
      </div>

      <p class="mt-2 text-[11px] text-ink-400">{{ activeTabHint }}</p>

      <div
        v-if="rulesetsError"
        class="mt-2 flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1 truncate">{{ rulesetsError }}</span>
        <button class="shrink-0 font-medium" @click="loadRulesets()">重试</button>
      </div>
    </div>

    <OverviewTab
      v-if="tab === 'overview'"
      :ruleset-id="rulesetId"
      :rulesets="rulesets"
      :refresh-key="refreshKey"
      @go="switchTab"
    />
    <RuleSetsTab
      v-else-if="tab === 'rulesets'"
      :ruleset-id="rulesetId"
      :rulesets="rulesets"
      :refresh-key="refreshKey"
      @select="rulesetId = String($event)"
      @changed="onCatalogChanged"
    />
    <DecisionTablesTab
      v-else-if="tab === 'tables'"
      :ruleset-id="rulesetId"
      :rulesets="rulesets"
      :refresh-key="refreshKey"
      @changed="loadRulesets(true)"
    />
    <SimulateTab
      v-else-if="tab === 'simulate'"
      :ruleset-id="rulesetId"
      :rulesets="rulesets"
      :refresh-key="refreshKey"
      @go="switchTab"
    />
    <AnalyticsTab
      v-else
      :ruleset-id="rulesetId"
      :rulesets="rulesets"
      :refresh-key="refreshKey"
    />

    <p class="pb-2 text-center text-[11px] text-ink-400">
      规则执行全部走后端接口，命中判定以服务端结果为准
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import PageHeader from '../../components/platform/PageHeader.vue'
import OverviewTab from './OverviewTab.vue'
import RuleSetsTab from './RuleSetsTab.vue'
import DecisionTablesTab from './DecisionTablesTab.vue'
import SimulateTab from './SimulateTab.vue'
import AnalyticsTab from './AnalyticsTab.vue'

const api = apiFor('rules')
const app = useAppStore()

const TABS = [
  { key: 'overview', label: '规则总览', hint: '规则集健康度、命中 TOP、失败原因与评估趋势' },
  { key: 'rulesets', label: '规则集', hint: '规则集、版本、规则与条件动作的可视化编辑' },
  { key: 'tables', label: '决策表', hint: '输入输出列配置、行编辑与在线求值' },
  { key: 'simulate', label: '仿真评估', hint: '单条与批量评估、测试用例、冲突检测' },
  { key: 'analytics', label: '命中分析', hint: '命中率趋势、规则排行、动作分布与执行日志' },
]

const tab = ref('overview')
const rulesets = ref([])
const rulesetsLoading = ref(false)
const rulesetsError = ref('')
const rulesetId = ref('')
const refreshKey = ref(0)
const refreshing = ref(false)

const selectedRuleSet = computed(() => {
  if (!rulesetId.value) return null
  return rulesets.value.find((item) => String(item.id) === String(rulesetId.value)) || null
})

const activeTabHint = computed(() => {
  const current = TABS.find((item) => item.key === tab.value)
  return current ? current.hint : ''
})

const HIT_POLICY_LABELS = {
  first: '首条命中',
  all: '全部命中',
  priority: '最高优先级',
  collect: '汇总输出',
}

function hitPolicyLabel(value) {
  return HIT_POLICY_LABELS[value] || value || '—'
}

function statusClass(status) {
  const map = {
    active: 'bg-emerald-50 text-emerald-600',
    published: 'bg-emerald-50 text-emerald-600',
    draft: 'bg-amber-50 text-amber-600',
    paused: 'bg-amber-50 text-amber-600',
    archived: 'bg-ink-100 text-ink-500',
  }
  return map[status] || 'bg-ink-100 text-ink-500'
}

function switchTab(key) {
  tab.value = key
}

async function loadRulesets(silent = false) {
  if (!api) {
    rulesetsError.value = '规则引擎接口不可用'
    return
  }
  rulesetsLoading.value = true
  rulesetsError.value = ''
  try {
    const data = await api.list('rulesets/', { page: 1, page_size: 100 })
    rulesets.value = data.items || []
    const stillExists = rulesets.value.some((item) => String(item.id) === String(rulesetId.value))
    if (!stillExists) {
      const first = rulesets.value.find((item) => item.status === 'active') || rulesets.value[0]
      rulesetId.value = first ? String(first.id) : ''
    }
    if (!rulesetsLoading.value && !silent && !rulesets.value.length) {
      rulesetsError.value = ''
    }
  } catch (e) {
    rulesets.value = []
    rulesetsError.value = e?.message || '规则集加载失败'
    if (!silent) app.toastMsg(rulesetsError.value, 'error')
  } finally {
    rulesetsLoading.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await loadRulesets(true)
    refreshKey.value += 1
    app.toastMsg('已刷新', 'success')
  } finally {
    refreshing.value = false
  }
}

function onCatalogChanged() {
  loadRulesets(true)
  refreshKey.value += 1
}

onMounted(() => loadRulesets(true))
</script>