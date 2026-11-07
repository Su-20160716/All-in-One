<template>
  <div class="mx-auto max-w-[1440px] space-y-4">
    <PageHeader
      title="应用市场"
      subtitle="应用上架审核、版本兼容、安装授权、评价与收入分成统一工作台"
      :crumbs="[{ label: '平台' }, { label: '应用市场' }]"
    >
      <template #actions>
        <span class="tag-brand">5 个页签</span>
        <span v-if="summaryLoading" class="tag">市场指标加载中</span>
        <span v-else-if="summaryError" class="tag bg-rose-50 text-rose-600">市场指标不可用</span>
        <span v-else class="tag">上架 {{ fmtNum(summary?.published_listings) }} 个</span>
        <button class="btn-outline" :disabled="refreshing" @click="refreshAll">
          {{ refreshing ? '刷新中…' : '刷新全部' }}
        </button>
      </template>
    </PageHeader>

    <div class="card p-3">
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          v-for="item in TABS"
          :key="item.key"
          class="rounded-pill px-3 py-1.5 text-[12px] transition-colors"
          :class="tab === item.key
            ? 'bg-brand-600 text-white'
            : 'border border-ink-200 bg-white text-ink-600 hover:border-brand-300 hover:text-brand-600'"
          @click="switchTab(item.key)"
        >
          {{ item.label }}
        </button>

        <span class="mx-1 hidden h-4 w-px bg-ink-200 sm:block"></span>

        <span class="tag">发布者 {{ fmtNum(summary?.publishers) }}</span>
        <span class="tag">有效安装 {{ fmtNum(summary?.active_installs) }}</span>
        <span
          class="tag"
          :class="pendingTotal ? 'bg-amber-50 text-amber-700' : ''"
        >
          待处理 {{ fmtNum(pendingTotal) }}
        </span>
        <span v-if="summary?.generated_at" class="text-[11px] text-ink-400">
          数据时间 {{ fmtDate(summary.generated_at, true) }}
        </span>

        <button class="btn-ghost ml-auto py-1 text-[12px]" :disabled="summaryLoading" @click="loadSummary(true)">
          重新加载指标
        </button>
      </div>

      <p class="mt-2 text-[11px] text-ink-400">{{ activeHint }}</p>

      <div
        v-if="summaryError"
        class="mt-2 flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1 truncate">{{ summaryError }}</span>
        <button class="shrink-0 font-medium" @click="loadSummary()">重试</button>
      </div>
    </div>

    <OverviewTab
      v-if="tab === 'overview'"
      :refresh-key="refreshKey"
      @go="switchTab"
    />
    <ListingsTab
      v-else-if="tab === 'listings'"
      :refresh-key="refreshKey"
      @changed="onTabChanged"
    />
    <InstallsTab
      v-else-if="tab === 'installs'"
      :refresh-key="refreshKey"
      @go="switchTab"
      @changed="onTabChanged"
    />
    <PublishersTab
      v-else-if="tab === 'publishers'"
      :refresh-key="refreshKey"
      @go="switchTab"
      @changed="onTabChanged"
    />
    <AnalyticsTab
      v-else
      :refresh-key="refreshKey"
      @go="switchTab"
    />

    <p class="pb-2 text-center text-[11px] text-ink-400">
      所有浏览、安装、评价与结算动作均通过市场接口完成，审核结论以服务端为准
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { formatDate, formatNumber } from '../../composables/useDomainResource'
import PageHeader from '../../components/platform/PageHeader.vue'
import OverviewTab from './OverviewTab.vue'
import ListingsTab from './ListingsTab.vue'
import InstallsTab from './InstallsTab.vue'
import PublishersTab from './PublishersTab.vue'
import AnalyticsTab from './AnalyticsTab.vue'

const api = apiFor('marketplace')
const app = useAppStore()

const TABS = [
  { key: 'overview', label: '市场总览', hint: '市场指标、分类分布、安装趋势、发布者排行、评分分布与推荐位' },
  { key: 'listings', label: '应用目录', hint: '卡片与表格浏览、搜索筛选、详情、安装、评价与举报' },
  { key: 'installs', label: '我的安装', hint: '已安装应用、配置、升级检查、许可证校验与卸载' },
  { key: 'publishers', label: '发布者', hint: '发布者入驻与认证、应用与版本发布、收入分成概览' },
  { key: 'analytics', label: '运营分析', hint: '安装与收入趋势、分类/评分分布、合集运营与条目排序' },
]

const tab = ref('overview')
const refreshKey = ref(0)
const refreshing = ref(false)
const summary = ref(null)
const summaryLoading = ref(false)
const summaryError = ref('')

const pendingTotal = computed(() => {
  const data = summary.value
  if (!data) return 0
  const reviewing = Number(data.listings_by_status?.reviewing || 0)
  const reports = Number(data.pending_reports || 0)
  const reviews = Number(data.pending_reviews || 0)
  return reviewing + reports + reviews
})

const activeHint = computed(() => {
  const current = TABS.find((item) => item.key === tab.value)
  return current ? current.hint : ''
})

function fmtNum(value) {
  return formatNumber(value)
}

function fmtDate(value, withTime = false) {
  return formatDate(value, withTime)
}

async function loadSummary(silent = false) {
  if (!api) {
    summaryError.value = '应用市场接口不可用'
    return
  }
  summaryLoading.value = true
  summaryError.value = ''
  try {
    summary.value = await api.get('stats/overview/')
  } catch (e) {
    summary.value = null
    summaryError.value = e?.message || '市场指标加载失败'
    if (!silent) app.toastMsg(summaryError.value, 'info')
  } finally {
    summaryLoading.value = false
  }
}

function switchTab(key) {
  if (!TABS.some((item) => item.key === key)) return
  tab.value = key
}

async function refreshAll() {
  refreshing.value = true
  try {
    refreshKey.value += 1
    await loadSummary(true)
    app.toastMsg('已刷新应用市场', 'success')
  } finally {
    refreshing.value = false
  }
}

function onTabChanged() {
  refreshKey.value += 1
  loadSummary(true)
}

onMounted(() => loadSummary(true))
</script>