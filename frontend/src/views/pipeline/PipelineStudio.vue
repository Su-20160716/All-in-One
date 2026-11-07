<template>
  <div class="mx-auto max-w-[1500px] space-y-4">
    <PageHeader
      title="数据管道"
      subtitle="连接器、DAG 编排、转换执行、质量规则与血缘追踪统一工作台"
      :crumbs="[{ label: '平台' }, { label: '数据管道' }]"
    >
      <template #actions>
        <span class="tag-brand">5 个页签</span>
        <span class="tag">后端 82 个接口</span>
        <button class="btn-outline" :disabled="refreshing" @click="refreshAll">
          {{ refreshing ? '刷新中…' : '刷新全部' }}
        </button>
      </template>
    </PageHeader>

    <!-- 页签 + 管道上下文 -->
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
          <span
            v-if="t.key === 'pipelines' && pipelines.length"
            class="ml-1 text-[11px]"
            :class="tab === t.key ? 'text-white/80' : 'text-ink-400'"
          >
            {{ pipelines.length }}
          </span>
        </button>

        <span class="mx-1 hidden h-4 w-px bg-ink-200 sm:block"></span>

        <span v-if="pipelinesLoading" class="tag">管道加载中…</span>
        <span v-else-if="pipelinesError" class="tag bg-rose-50 text-rose-600">管道加载失败</span>
        <span v-else-if="!pipelines.length" class="tag">暂无管道</span>
        <span v-else class="tag">共 {{ pipelines.length }} 条管道</span>

        <button class="btn-ghost ml-auto py-1 text-[11px]" :disabled="pipelinesLoading" @click="loadPipelines(false)">
          重新加载管道
        </button>
      </div>

      <p class="mt-2 text-[11px] text-ink-400">{{ activeHint }}</p>

      <div
        v-if="pipelinesError"
        class="mt-2 flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1 truncate">{{ pipelinesError }}</span>
        <button class="shrink-0 font-medium" @click="loadPipelines(false)">重试</button>
      </div>
    </div>

    <PipelineOverviewTab
      v-if="tab === 'overview'"
      :pipelines="pipelines"
      :refresh-key="refreshKey"
      @go="switchTab"
    />
    <PipelinesTab
      v-else-if="tab === 'pipelines'"
      :pipelines="pipelines"
      :refresh-key="refreshKey"
      @refresh="loadPipelines(true)"
      @go="switchTab"
    />
    <RunsTab
      v-else-if="tab === 'runs'"
      :pipelines="pipelines"
      :refresh-key="refreshKey"
      @refresh="loadPipelines(true)"
    />
    <QualityTab
      v-else-if="tab === 'quality'"
      :pipelines="pipelines"
      :refresh-key="refreshKey"
    />
    <LineageTab v-else :pipelines="pipelines" :refresh-key="refreshKey" />

    <p class="pb-2 text-center text-[11px] text-ink-400">
      编排、执行、质量与血缘数据均来自后端 /api/pipeline/ 接口，前端不做本地兜底计算
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import PageHeader from '../../components/platform/PageHeader.vue'
import PipelineOverviewTab from './PipelineOverviewTab.vue'
import PipelinesTab from './PipelinesTab.vue'
import RunsTab from './RunsTab.vue'
import QualityTab from './QualityTab.vue'
import LineageTab from './LineageTab.vue'

const api = apiFor('pipeline')
const app = useAppStore()

const TABS = [
  { key: 'overview', label: '运行总览', hint: '管道规模、成功率、行数吞吐、失败节点与最近运行' },
  { key: 'pipelines', label: '管道编排', hint: 'DAG 节点、连线、字段映射与导入导出的完整编排台' },
  { key: 'runs', label: '运行记录', hint: '运行详情、步骤日志、输出预览、重跑与对比' },
  { key: 'quality', label: '数据质量', hint: '校验规则、规则测试、结果列表与通过率统计' },
  { key: 'lineage', label: '血缘图谱', hint: '上下游查询、影响分析、全图层级视图与字段画像' },
]

const tab = ref('overview')
const pipelines = ref([])
const pipelinesLoading = ref(false)
const pipelinesError = ref('')
const refreshKey = ref(0)
const refreshing = ref(false)

const activeHint = computed(() => {
  const current = TABS.find((item) => item.key === tab.value)
  return current ? current.hint : ''
})

function switchTab(key) {
  tab.value = key
}

async function loadPipelines(silent = false) {
  if (!api) {
    pipelinesError.value = '数据管道接口不可用'
    return
  }
  pipelinesLoading.value = true
  pipelinesError.value = ''
  try {
    const data = await api.list('pipelines/', { page: 1, page_size: 200 })
    pipelines.value = data.items || []
  } catch (e) {
    pipelines.value = []
    pipelinesError.value = e?.message || '管道列表加载失败'
    if (!silent) app.toastMsg(pipelinesError.value, 'error')
  } finally {
    pipelinesLoading.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await loadPipelines(true)
    refreshKey.value += 1
    app.toastMsg('已刷新', 'success')
  } finally {
    refreshing.value = false
  }
}

onMounted(() => loadPipelines(true))
</script>