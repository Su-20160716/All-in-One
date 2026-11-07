<template>
  <div class="mx-auto max-w-[1440px] space-y-4">
    <PageHeader
      title="报表与仪表盘"
      :subtitle="domain.description"
      :crumbs="crumbs"
      sticky
    >
      <template #badge>
        <span class="tag-brand">工作台</span>
        <span v-if="catalog" class="tag">{{ catalog.endpoint_count }} 个接口</span>
        <span v-if="catalog && catalog.model_count" class="tag">{{ catalog.model_count }} 个模型</span>
        <span v-if="catalogError" class="tag bg-amber-50 text-amber-700">目录降级</span>
      </template>

      <template #actions>
        <button class="btn-ghost" :disabled="catalogLoading" @click="loadCatalog">
          {{ catalogLoading ? '加载中…' : '刷新目录' }}
        </button>
        <button class="btn-outline" @click="showCatalog = !showCatalog">
          {{ showCatalog ? '收起接口清单' : '接口清单' }}
        </button>
        <button class="btn-primary" @click="reload">刷新数据</button>
      </template>
    </PageHeader>

    <!-- 目录降级提示：目录接口不可用时不阻塞五个页签的独立加载 -->
    <div
      v-if="catalogError"
      class="card flex flex-wrap items-center gap-2 border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800"
    >
      <span class="min-w-0 flex-1">接口目录读取失败：{{ catalogError }}。页签仍可单独使用，请检查后端 reporting 模块是否已挂载。</span>
      <button class="btn-outline px-2 py-0.5" @click="loadCatalog">重试</button>
    </div>

    <!-- 目录概览：接口数量、模型数量与各资源规模 -->
    <section v-if="showCatalog" class="card space-y-3 p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 class="text-[14px] font-semibold text-ink-800">接口目录</h3>
          <p class="mt-0.5 text-[12px] text-ink-400">
            前缀 {{ catalog?.prefix || '/api/reporting/' }}，共 {{ catalog?.endpoint_count || 0 }} 个端点；
            清单来自后端 urlpatterns 反射，前端不维护第二份映射表。
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="tag">版本 {{ catalog?.version || '—' }}</span>
          <span class="tag">模型白名单 {{ catalog?.model_count || 0 }}</span>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <div v-for="c in countCards" :key="c.key" class="rounded-control border border-ink-100 bg-ink-50/60 px-3 py-2">
          <div class="text-[11px] text-ink-400">{{ c.label }}</div>
          <div class="mt-0.5 text-[16px] font-semibold text-ink-800">{{ c.value }}</div>
        </div>
      </div>

      <div class="max-h-64 overflow-auto rounded-control border border-ink-100">
        <table class="w-full min-w-[560px]">
          <thead class="bg-ink-50">
            <tr>
              <th class="th">路径</th>
              <th class="th w-32">方法</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="ep in endpoints" :key="ep.path">
              <td class="td font-mono text-[12px] text-ink-600">{{ ep.path }}</td>
              <td class="td">
                <span v-for="m in ep.methods" :key="m" class="tag mr-1 bg-brand-50 text-brand-700">{{ m }}</span>
              </td>
            </tr>
            <tr v-if="!endpoints.length">
              <td class="td text-ink-400" colspan="2">目录未返回端点明细</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 页签：五个能力面按「总览 → 资产 → 编排 → 数据 → 调度」排列 -->
    <div class="card px-3 pt-2">
      <div class="flex flex-wrap gap-1 border-b border-ink-100">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] transition-colors"
          :class="tab === t.key
            ? 'border-brand-600 font-medium text-brand-700'
            : 'border-transparent text-ink-500 hover:text-ink-700'"
          @click="switchTab(t.key)"
        >
          <span>{{ t.label }}</span>
          <span
            v-if="countFor(t.key) !== null"
            class="rounded-pill px-1.5 py-0.5 text-[10px]"
            :class="tab === t.key ? 'bg-brand-50 text-brand-700' : 'bg-ink-100 text-ink-500'"
          >{{ countFor(t.key) }}</span>
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2 py-2 text-[11px] text-ink-400">
        <span>执行总览读取指标接口，报表/仪表盘/数据集/计划任务均按真实端点分页加载。</span>
        <span v-if="lastReloadAt" class="ml-auto">最近刷新 {{ lastReloadText }}</span>
      </div>
    </div>

    <OverviewPanel
      v-if="tab === 'overview'"
      :reload-token="reloadToken"
      @go="switchTab"
    />
    <ReportsPanel v-else-if="tab === 'reports'" :reload-token="reloadToken" />
    <DashboardsPanel v-else-if="tab === 'dashboards'" :reload-token="reloadToken" />
    <DatasetsPanel v-else-if="tab === 'datasets'" :reload-token="reloadToken" />
    <SchedulesPanel v-else-if="tab === 'schedules'" :reload-token="reloadToken" />

    <footer class="pb-4 text-center text-[11px] text-ink-400">
      报表执行结果默认写入快照缓存；计划任务由外部调度器拉取到期列表后调用执行接口。
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { findDomain } from '../../api/domains'
import { reportingApi } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import PageHeader from '../../components/platform/PageHeader.vue'
import OverviewPanel from './OverviewPanel.vue'
import ReportsPanel from './ReportsPanel.vue'
import DashboardsPanel from './DashboardsPanel.vue'
import DatasetsPanel from './DatasetsPanel.vue'
import SchedulesPanel from './SchedulesPanel.vue'

const app = useAppStore()
const domain = findDomain('reporting') || {
  name: '报表与仪表盘',
  description: '数据集编译、报表组件、仪表盘布局、计划任务与导出。',
  tabs: [],
}

const FALLBACK_TABS = [
  { key: 'overview', label: '执行总览' },
  { key: 'reports', label: '报表' },
  { key: 'dashboards', label: '仪表盘' },
  { key: 'datasets', label: '数据集' },
  { key: 'schedules', label: '计划任务' },
]

const tabs = computed(() => (Array.isArray(domain.tabs) && domain.tabs.length ? domain.tabs : FALLBACK_TABS))
const crumbs = [
  { label: '能力域' },
  { label: '报表与仪表盘' },
]

const tab = ref('overview')
const reloadToken = ref(0)
const lastReloadAt = ref(null)

const catalog = ref(null)
const catalogLoading = ref(false)
const catalogError = ref('')
const showCatalog = ref(false)

const endpoints = computed(() => {
  const list = catalog.value?.endpoints
  return Array.isArray(list) ? list : []
})

const countCards = computed(() => {
  const counts = catalog.value?.counts || {}
  return [
    { key: 'reports', label: '报表', value: counts.reports ?? '—' },
    { key: 'dashboards', label: '仪表盘', value: counts.dashboards ?? '—' },
    { key: 'datasets', label: '数据集', value: counts.datasets ?? '—' },
    { key: 'schedules', label: '计划任务', value: counts.schedules ?? '—' },
    { key: 'runs', label: '执行流水', value: counts.runs ?? '—' },
    { key: 'sources', label: '数据源', value: counts.sources ?? '—' },
  ]
})

const lastReloadText = computed(() => {
  const d = lastReloadAt.value
  if (!d) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
})

function countFor(key) {
  const counts = catalog.value?.counts
  if (!counts) return null
  const map = { reports: 'reports', dashboards: 'dashboards', datasets: 'datasets', schedules: 'schedules' }
  const field = map[key]
  if (!field) return null
  const value = counts[field]
  return Number.isFinite(Number(value)) ? Number(value) : null
}

function isUnavailable(e) {
  const status = Number(e?.status || e?.response?.status || 0)
  const message = String(e?.message || '')
  return status === 404 || status === 405 || /not found|method not allowed|405/i.test(message)
}

async function loadCatalog() {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    catalog.value = await reportingApi.get('')
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
  app.toastMsg('已刷新当前工作台数据', 'success')
}

function switchTab(key) {
  if (tab.value === key) return
  tab.value = key
}

onMounted(loadCatalog)
</script>