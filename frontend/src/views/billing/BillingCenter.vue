<template>
  <div class="mx-auto max-w-[1440px] space-y-4">
    <PageHeader
      title="订阅计费"
      :subtitle="domain.description"
      :crumbs="crumbs"
      sticky
    >
      <template #badge>
        <span class="tag-brand">计费工作台</span>
        <span class="tag">真实接口</span>
        <span v-if="endpointCount" class="tag">{{ endpointCount }} 个端点</span>
        <span v-if="catalogError" class="tag bg-amber-50 text-amber-700">目录降级</span>
      </template>

      <template #actions>
        <button class="btn-ghost" :disabled="catalogLoading" @click="loadCatalog">
          {{ catalogLoading ? '加载中…' : '刷新目录' }}
        </button>
        <button class="btn-outline" @click="switchTab('plans')">管理套餐</button>
        <button class="btn-primary" @click="reload">刷新数据</button>
      </template>
    </PageHeader>

    <!-- 目录不可用不阻塞页签：每个页签独立加载真实接口 -->
    <div
      v-if="catalogError"
      class="card flex flex-wrap items-center gap-2 border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800"
    >
      <span class="min-w-0 flex-1">
        接口目录读取失败：{{ catalogError }}。五个页签仍可单独使用，列表会按端点缺失降级为空态。
      </span>
      <button class="btn-outline px-2 py-0.5" @click="loadCatalog">重试</button>
    </div>

    <div class="card px-3 pt-2">
      <div class="flex flex-wrap gap-1 border-b border-ink-100">
        <button
          v-for="t in tabs"
          :key="t.key"
          type="button"
          class="-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] transition-colors"
          :class="tab === t.key
            ? 'border-brand-600 font-medium text-brand-700'
            : 'border-transparent text-ink-500 hover:text-ink-700'"
          @click="switchTab(t.key)"
        >
          <span>{{ t.label }}</span>
          <span
            v-if="tab === t.key"
            class="rounded-pill bg-brand-50 px-1.5 py-0.5 text-[10px] text-brand-700"
          >当前</span>
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2 py-2 text-[11px] text-ink-400">
        <span>收入指标、订阅生命周期、发票收付、用量上报与套餐配置全部调用 /api/billing/ 真实端点。</span>
        <span v-if="lastReloadAt" class="ml-auto">最近刷新 {{ lastReloadText }}</span>
      </div>
    </div>

    <OverviewPanel
      v-if="tab === 'overview'"
      :reload-token="reloadToken"
      @go="switchTab"
    />
    <SubscriptionsPanel
      v-else-if="tab === 'subscriptions'"
      :reload-token="reloadToken"
      @go="switchTab"
    />
    <InvoicesPanel
      v-else-if="tab === 'invoices'"
      :reload-token="reloadToken"
      @go="switchTab"
    />
    <UsagePanel
      v-else-if="tab === 'usage'"
      :reload-token="reloadToken"
      @go="switchTab"
    />
    <PlansPanel
      v-else-if="tab === 'plans'"
      :reload-token="reloadToken"
      @go="switchTab"
    />

    <footer class="pb-4 text-center text-[11px] text-ink-400">
      金额由后端以字符串输出，前端统一用 formatMoney 展示；列表统一读取
      { items, count, page, page_size }，端点缺失时降级为空态而不是报错卡死。
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { findDomain } from '../../api/domains'
import { billingApi } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import PageHeader from '../../components/platform/PageHeader.vue'
import OverviewPanel from './OverviewPanel.vue'
import SubscriptionsPanel from './SubscriptionsPanel.vue'
import InvoicesPanel from './InvoicesPanel.vue'
import UsagePanel from './UsagePanel.vue'
import PlansPanel from './PlansPanel.vue'

const app = useAppStore()
const domain = findDomain('billing') || {
  name: '订阅计费',
  description: '套餐定价、订阅生命周期、用量计费、发票支付与催收。',
  tabs: [],
}

const FALLBACK_TABS = [
  { key: 'overview', label: '收入总览' },
  { key: 'subscriptions', label: '订阅' },
  { key: 'invoices', label: '发票' },
  { key: 'usage', label: '用量' },
  { key: 'plans', label: '套餐' },
]

const tabs = computed(() => (Array.isArray(domain.tabs) && domain.tabs.length ? domain.tabs : FALLBACK_TABS))
const crumbs = [
  { label: '平台能力' },
  { label: '订阅计费' },
]

const tab = ref('overview')
const reloadToken = ref(0)
const lastReloadAt = ref(null)

const catalog = ref(null)
const catalogLoading = ref(false)
const catalogError = ref('')

const endpointCount = computed(() => {
  const c = catalog.value || {}
  const n = Number(c.endpoint_count ?? c.endpoints?.length ?? c.count ?? 0)
  return Number.isFinite(n) && n > 0 ? n : 0
})

const lastReloadText = computed(() => {
  const d = lastReloadAt.value
  if (!d) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})

function isUnavailable(e) {
  const status = Number(e?.status || e?.response?.status || 0)
  const message = String(e?.message || '')
  return status === 404 || status === 405 || /not found|method not allowed|405/i.test(message)
}

async function loadCatalog() {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    catalog.value = await billingApi.get('')
  } catch (e) {
    catalog.value = null
    catalogError.value = isUnavailable(e)
      ? '接口目录不存在或方法不可用（404/405）'
      : (e?.message || '目录加载失败')
    app.toastMsg(catalogError.value, 'error')
  } finally {
    catalogLoading.value = false
  }
}

function reload() {
  reloadToken.value += 1
  lastReloadAt.value = new Date()
  loadCatalog()
  app.toastMsg('已刷新当前计费页签数据', 'success')
}

function switchTab(key) {
  if (tab.value === key) return
  tab.value = key
}

onMounted(loadCatalog)
</script>