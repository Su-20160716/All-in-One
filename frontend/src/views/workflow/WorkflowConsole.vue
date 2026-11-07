<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <PageHeader
      title="流程引擎"
      subtitle="流程定义、版本发布、待办审批与实例监控的一体化工作台，数据全部来自 workflow 真实接口"
      :crumbs="[{ label: '平台能力' }, { label: '流程引擎' }]"
    >
      <template #badge>
        <span class="tag-brand">待办 {{ pendingCount }}</span>
        <span v-if="staff" class="tag bg-ink-100 text-ink-600">管理员视图</span>
      </template>
      <template #actions>
        <button class="btn-ghost" :disabled="loading" @click="refreshAll">
          {{ loading ? '刷新中…' : '刷新数据' }}
        </button>
        <button class="btn-primary" @click="switchTab('definitions')">新建/管理流程</button>
      </template>
    </PageHeader>

    <!-- 五个页签：总览、定义、待办、实例、分析 -->
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
          v-if="t.key === 'tasks'"
          class="ml-1 text-[11px]"
          :class="tab === t.key ? 'text-white/80' : 'text-ink-400'"
        >{{ pendingCount }}</span>
      </button>
      <span class="ml-auto text-[11px] text-ink-400">
        数据窗口近 {{ windowDays }} 天 · 更新于 {{ updatedText }}
      </span>
    </div>

    <!-- 一、运行总览 -->
    <section v-if="tab === 'overview'" class="space-y-3">
      <div
        v-if="error"
        class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" @click="loadOverview">重试</button>
      </div>

      <StatsGrid :items="statItems" :loading="loading" :skeleton-count="5" />

      <div class="grid gap-3 lg:grid-cols-2">
        <SectionCard title="状态分布" subtitle="全部可见实例按状态计数，环形图中心为实例总数">
          <template #actions>
            <span class="tag">共 {{ formatNumber(statusTotal) }} 个</span>
          </template>
          <div v-if="loading && !dash" class="grid h-[180px] place-items-center text-[12px] text-ink-400">加载中…</div>
          <DonutChart
            v-else
            :data="statusData"
            :center-value="formatNumber(statusTotal)"
            center-label="实例总数"
            :size="156"
            empty-text="暂无实例数据"
          />
        </SectionCard>

        <SectionCard title="近 14 天趋势" subtitle="每日发起、完成、拒绝的实例数量">
          <template #actions>
            <span class="tag">发起 {{ formatNumber(trendSummary.started) }}</span>
            <span class="tag bg-emerald-50 text-emerald-600">完成 {{ formatNumber(trendSummary.completed) }}</span>
          </template>
          <div v-if="loading && !dash" class="grid h-[200px] place-items-center text-[12px] text-ink-400">加载中…</div>
          <LineChart
            v-else
            :series="trendSeries"
            :labels="trendLabels"
            :height="200"
            empty-text="近 14 天没有运行数据"
          />
        </SectionCard>
      </div>

      <div class="grid gap-3 lg:grid-cols-5">
        <SectionCard
          class="lg:col-span-3"
          title="节点瓶颈"
          subtitle="按平均办理时长排序，用于定位流程中最慢的环节"
          dense
        >
          <template #actions>
            <span class="tag">TOP {{ bottleneckData.length }}</span>
          </template>
          <div v-if="loading && !dash" class="grid h-[160px] place-items-center text-[12px] text-ink-400">加载中…</div>
          <BarChart
            v-else
            :data="bottleneckData"
            horizontal
            color="var(--brand-400)"
            :format="formatMinutes"
            empty-text="暂无已办理任务，无法统计瓶颈"
          />
        </SectionCard>

        <SectionCard class="lg:col-span-2" title="我的工作" subtitle="待办与 SLA 达成情况" dense>
          <div class="grid grid-cols-2 gap-2">
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">我的待办</div>
              <div class="mt-0.5 text-[20px] font-semibold text-ink-900">{{ formatNumber(myPending) }}</div>
            </div>
            <div class="rounded-control bg-rose-50 px-3 py-2">
              <div class="text-[11px] text-rose-500">逾期任务</div>
              <div class="mt-0.5 text-[20px] font-semibold text-rose-600">{{ formatNumber(myOverdue) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">任务完成率</div>
              <div class="mt-0.5 text-[18px] font-semibold text-ink-900">{{ formatPct(taskStats.completion_rate_pct) }}</div>
            </div>
            <div class="rounded-control bg-emerald-50 px-3 py-2">
              <div class="text-[11px] text-emerald-600">SLA 达成率</div>
              <div class="mt-0.5 text-[18px] font-semibold text-emerald-700">{{ formatPct(taskStats.sla_compliance_pct) }}</div>
            </div>
          </div>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <button class="btn-ghost px-2 text-[12px]" @click="switchTab('tasks')">去处理待办</button>
            <button class="btn-ghost px-2 text-[12px]" @click="switchTab('instances')">查看实例</button>
            <button class="btn-ghost px-2 text-[12px]" @click="switchTab('analytics')">效率分析</button>
          </div>
        </SectionCard>
      </div>

      <SectionCard title="最近实例" subtitle="按创建时间倒序，点击任意行进入实例监控查看详情">
        <template #actions>
          <button class="btn-ghost px-2 text-[12px]" @click="loadRecent">刷新</button>
        </template>

        <div v-if="recentLoading && !recent.length" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
        <div
          v-else-if="recentError"
          class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
        >
          <span class="min-w-0 flex-1">{{ recentError }}</span>
          <button class="font-medium" @click="loadRecent">重试</button>
        </div>
        <div v-else-if="!recent.length" class="py-8 text-center text-[12px] text-ink-400">
          还没有流程实例，先到「流程定义」发布一个流程并发起
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[780px]">
            <thead class="border-b border-ink-100 bg-ink-50/50">
              <tr>
                <th class="th">业务单号</th>
                <th class="th">标题</th>
                <th class="th">流程</th>
                <th class="th">状态</th>
                <th class="th">当前节点</th>
                <th class="th">发起人</th>
                <th class="th">开始时间</th>
                <th class="th">耗时</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr
                v-for="row in recent"
                :key="row.id"
                class="cursor-pointer hover:bg-ink-50/60"
                @click="switchTab('instances')"
              >
                <td class="td font-mono text-[12px] text-ink-600">{{ row.business_no || '—' }}</td>
                <td class="td max-w-[220px] truncate">{{ row.title || '—' }}</td>
                <td class="td max-w-[180px] truncate text-ink-500">{{ row.definition_name || '—' }}</td>
                <td class="td">
                  <span class="tag" :class="tagClass(statusTone(row.status))">{{ statusLabel(row.status) }}</span>
                </td>
                <td class="td text-ink-500">{{ row.current_node?.name || '—' }}</td>
                <td class="td text-ink-500">{{ row.starter?.name || row.starter?.username || '—' }}</td>
                <td class="td text-[12px] text-ink-500">{{ formatDate(row.started_at, true) }}</td>
                <td class="td text-[12px] text-ink-500">{{ formatMinutes(row.duration_minutes) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>
    </section>

    <!-- 二、流程定义 -->
    <WfDefinitions v-else-if="tab === 'definitions'" :refresh-key="refreshKey" />

    <!-- 三、我的待办 -->
    <WfTasks v-else-if="tab === 'tasks'" :refresh-key="refreshKey" />

    <!-- 四、实例监控 -->
    <WfInstances v-else-if="tab === 'instances'" :refresh-key="refreshKey" />

    <!-- 五、效率分析 -->
    <WfAnalytics v-else-if="tab === 'analytics'" :refresh-key="refreshKey" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiFor } from '../../api/platform'
import { findDomain } from '../../api/domains'
import {
  formatDate,
  formatNumber,
  statusTone,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import PageHeader from '../../components/platform/PageHeader.vue'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import LineChart from '../../components/platform/LineChart.vue'
import BarChart from '../../components/platform/BarChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import WfDefinitions from './WfDefinitions.vue'
import WfTasks from './WfTasks.vue'
import WfInstances from './WfInstances.vue'
import WfAnalytics from './WfAnalytics.vue'

const app = useAppStore()
const api = apiFor('workflow')

// 页签直接从能力域元信息取，避免与侧边栏/路由的名称漂移
const domain = findDomain('workflow')
const tabs = domain?.tabs || [
  { key: 'overview', label: '运行总览' },
  { key: 'definitions', label: '流程定义' },
  { key: 'tasks', label: '我的待办' },
  { key: 'instances', label: '实例监控' },
  { key: 'analytics', label: '效率分析' },
]

const tab = ref('overview')
const refreshKey = ref(0)
const loading = ref(false)
const error = ref('')
const dash = ref(null)

const recent = ref([])
const recentLoading = ref(false)
const recentError = ref('')

const INSTANCE_STATUS = {
  running: '运行中',
  completed: '已完成',
  rejected: '已拒绝',
  cancelled: '已取消',
  terminated: '已终止',
}

const STATUS_COLORS = {
  running: 'var(--brand-500)',
  completed: '#10b981',
  rejected: '#f43f5e',
  cancelled: '#94a3b8',
  terminated: '#f59e0b',
}

function statusLabel(status) {
  return INSTANCE_STATUS[status] || status || '未知'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function formatPct(value) {
  const n = Number(value)
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : '—'
}

function formatMinutes(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (n >= 60) return `${(n / 60).toFixed(1)} 小时`
  return `${n.toFixed(0)} 分钟`
}

const metrics = computed(() => dash.value?.metrics || {})
const instanceStats = computed(() => metrics.value.instances || {})
const taskStats = computed(() => metrics.value.tasks || {})
const staff = computed(() => dash.value?.staff === true)
const pendingCount = computed(() => dash.value?.my?.pending_count ?? 0)
const myPending = computed(() => dash.value?.my?.pending_count ?? 0)
const myOverdue = computed(() => dash.value?.my?.overdue_count ?? taskStats.value.overdue ?? 0)
const windowDays = computed(() => metrics.value.window_days || 30)
const updatedText = computed(() =>
  dash.value?.generated_at ? formatDate(dash.value.generated_at, true) : '—'
)

const trendItems = computed(() => dash.value?.trend?.items || [])
const lastTrend = computed(() => trendItems.value[trendItems.value.length - 1] || null)

const statItems = computed(() => {
  const inst = instanceStats.value
  const tasks = taskStats.value
  return [
    {
      key: 'running',
      label: '运行中',
      value: inst.running ?? 0,
      unit: '个',
      hint: `窗口内发起 ${formatNumber(inst.total)} 个`,
      tone: 'brand',
    },
    {
      key: 'today-done',
      label: '今日完成',
      value: lastTrend.value?.completed ?? 0,
      unit: '个',
      hint: lastTrend.value?.date ? `${lastTrend.value.date} 完成` : '今日暂无完成',
      tone: 'emerald',
    },
    {
      key: 'overdue',
      label: '逾期实例',
      value: inst.overdue_running ?? 0,
      unit: '个',
      hint: `逾期待办 ${formatNumber(tasks.overdue)} 个`,
      tone: 'rose',
    },
    {
      key: 'completion',
      label: '完成率',
      value: inst.completion_rate_pct ?? 0,
      unit: '%',
      hint: `已拒绝 ${formatNumber(inst.rejected)} 个`,
      tone: 'emerald',
    },
    {
      key: 'duration',
      label: '平均耗时',
      value: inst.avg_duration_minutes ?? 0,
      unit: '分钟',
      hint: `任务平均 ${formatNumber(tasks.avg_handling_minutes, 1)} 分钟`,
      tone: 'amber',
    },
  ]
})

const statusTotal = computed(() => {
  const rows = dash.value?.status_distribution?.items || []
  return rows.reduce((sum, row) => sum + (Number(row.count) || 0), 0)
})

const statusData = computed(() => {
  const rows = dash.value?.status_distribution?.items || []
  return rows.map((row) => ({
    label: statusLabel(row.status),
    value: Number(row.count) || 0,
    color: STATUS_COLORS[row.status] || '#cbd5e1',
  }))
})

const trendLabels = computed(() =>
  trendItems.value.map((row) => String(row.date || '').slice(5))
)

const trendSeries = computed(() => [
  {
    name: '发起',
    color: 'var(--brand-500)',
    data: trendItems.value.map((row) => Number(row.started) || 0),
  },
  {
    name: '完成',
    color: '#10b981',
    data: trendItems.value.map((row) => Number(row.completed) || 0),
  },
  {
    name: '拒绝',
    color: '#f43f5e',
    data: trendItems.value.map((row) => Number(row.rejected) || 0),
  },
])

const trendSummary = computed(() => {
  const rows = trendItems.value
  return {
    started: rows.reduce((sum, row) => sum + (Number(row.started) || 0), 0),
    completed: rows.reduce((sum, row) => sum + (Number(row.completed) || 0), 0),
  }
})

const bottleneckData = computed(() => {
  const rows = dash.value?.bottlenecks?.items || []
  return rows.map((row) => ({
    label: row.node_name || row.node_key || `节点 ${row.node_id}`,
    value: Number(row.avg_duration_minutes) || 0,
  }))
})

async function loadOverview() {
  if (!api) {
    error.value = '流程引擎接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  try {
    // dashboard 一次返回指标、分布、趋势、瓶颈与我的待办数量
    dash.value = await api.get('monitor/dashboard/?days=30')
  } catch (e) {
    error.value = e?.message || '监控大盘加载失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
  }
}

async function loadRecent() {
  if (!api) return
  recentLoading.value = true
  recentError.value = ''
  try {
    const data = await api.list('instances/', { page: 1, page_size: 8 })
    recent.value = data.items || []
  } catch (e) {
    recentError.value = e?.message || '最近实例加载失败'
    recent.value = []
  } finally {
    recentLoading.value = false
  }
}

function refreshAll() {
  refreshKey.value += 1
  loadOverview()
  loadRecent()
}

function switchTab(key) {
  tab.value = key
  if (key === 'overview' && !dash.value && !loading.value) {
    loadOverview()
    loadRecent()
  }
}

onMounted(() => {
  loadOverview()
  loadRecent()
})
</script>