<template>
  <div class="space-y-3">
    <!-- 工具栏 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="statusFilter" class="input w-[130px]" @change="reloadFirst">
          <option value="">全部状态</option>
          <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <select v-model="pipelineFilter" class="input w-[220px]" @change="reloadFirst">
          <option value="">全部管道</option>
          <option v-for="item in pipelines" :key="item.id" :value="String(item.id)">
            {{ item.name }}（{{ item.code }}）
          </option>
        </select>
        <button class="btn-outline" :disabled="loading" @click="loadRuns">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <span class="mx-1 hidden h-4 w-px bg-ink-200 sm:block"></span>
        <button class="btn-primary" @click="openTrigger">手动触发运行</button>
        <button class="btn-outline" :disabled="!items.length" @click="openCompare">运行对比</button>
        <span class="ml-auto text-[11px] text-ink-400">共 {{ total }} 条 · 第 {{ page }}/{{ pages }} 页</span>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-1.5">
        <span class="tag">运行中 {{ statusCount.running }}</span>
        <span class="tag bg-emerald-50 text-emerald-600">成功 {{ statusCount.success }}</span>
        <span class="tag bg-rose-50 text-rose-600">失败 {{ statusCount.failed }}</span>
        <span class="tag">本页输出 {{ formatNumber(pageOutputRows) }} 行</span>
        <span class="ml-auto text-[11px] text-ink-400">运行状态以服务端为准，取消后不可恢复</span>
      </div>
    </div>

    <!-- 列表 -->
    <div class="card p-3">
      <div v-if="error" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="shrink-0 font-medium" @click="loadRuns">重试</button>
      </div>
      <div v-else-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">运行记录加载中…</div>
      <div v-else-if="!items.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
        暂无运行记录，可点击「手动触发运行」发起一次
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1000px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">运行</th>
              <th class="th">管道</th>
              <th class="th">触发</th>
              <th class="th">状态</th>
              <th class="th text-right">耗时</th>
              <th class="th text-right">输入 / 输出</th>
              <th class="th">开始时间</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="run in items" :key="run.id" class="transition-colors hover:bg-ink-50/60">
              <td class="td">
                <button class="font-mono text-[12px] text-ink-700 hover:text-brand-600" @click="openDetail(run)">#{{ run.id }}</button>
                <div v-if="run.resumed_from" class="text-[11px] text-ink-400">重跑自 {{ run.resumed_from }}</div>
              </td>
              <td class="td">
                <div class="max-w-[190px] truncate">{{ run.pipeline_name || pipelineName(run.pipeline_id) }}</div>
                <div class="text-[11px] text-ink-400">{{ run.pipeline_code || pipelineCode(run.pipeline_id) }}</div>
              </td>
              <td class="td text-[12px] text-ink-500">{{ triggerLabel(run.trigger) }}</td>
              <td class="td">
                <span class="tag" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span>
              </td>
              <td class="td text-right">{{ durationText(run.duration_ms) }}</td>
              <td class="td text-right text-[12px]">
                {{ formatNumber(run.input_rows) }} / {{ formatNumber(run.output_rows) }}
              </td>
              <td class="td text-[11px] text-ink-400">{{ formatDate(run.started_at, true) }}</td>
              <td class="td text-right">
                <div class="flex justify-end gap-1">
                  <button class="btn-ghost py-0.5 text-[11px]" @click="openDetail(run)">详情</button>
                  <button
                    class="btn-ghost py-0.5 text-[11px]"
                    :disabled="!canCancel(run)"
                    @click="cancelRun(run)"
                  >
                    取消
                  </button>
                  <button
                    class="btn-ghost py-0.5 text-[11px]"
                    :disabled="run.status !== 'failed'"
                    @click="retryFailed(run)"
                  >
                    重跑失败
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 pt-2.5">
        <div class="flex items-center gap-2 text-[12px] text-ink-500">
          <span>每页</span>
          <select class="input w-[76px] py-1" :value="pageSize" @change="changePageSize($event.target.value)">
            <option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }}</option>
          </select>
          <span>条</span>
        </div>
        <div class="flex items-center gap-1.5">
          <button class="btn-outline py-1 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <span class="px-1 text-[12px] text-ink-500">{{ page }} / {{ pages }}</span>
          <button class="btn-outline py-1 text-[12px]" :disabled="page >= pages || loading" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <!-- 手动触发 -->
    <Modal :show="triggerOpen" title="手动触发运行" width="520px" @close="triggerOpen = false">
      <form class="space-y-3" @submit.prevent="submitTrigger">
        <label class="block text-[12px] text-ink-500">
          选择管道
          <select v-model="triggerForm.pipeline" class="input mt-1">
            <option value="">请选择管道</option>
            <option v-for="item in pipelines" :key="item.id" :value="String(item.id)">
              {{ item.name }}（{{ item.code }}）
            </option>
          </select>
        </label>
        <label class="block text-[12px] text-ink-500">
          触发方式
          <select v-model="triggerForm.trigger" class="input mt-1">
            <option value="manual">手动</option>
            <option value="retry">重跑</option>
            <option value="api">接口</option>
          </select>
        </label>
        <p class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
          触发后会立即创建运行记录，执行过程与节点日志可在详情里查看。
        </p>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="triggerOpen = false">取消</button>
          <button type="submit" class="btn-primary" :disabled="triggering">{{ triggering ? '触发中…' : '立即运行' }}</button>
        </div>
      </form>
    </Modal>

    <!-- 运行详情 -->
    <Modal :show="detailOpen" :title="detailRun ? `运行详情 #${detailRun.id}` : '运行详情'" width="1080px" @close="closeDetail">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag" :class="statusClass(detail.status)">{{ statusLabel(detail.status) }}</span>
          <span class="tag">{{ triggerLabel(detail.trigger) }}</span>
          <span class="text-[12px] text-ink-500">{{ detail.pipeline_name || pipelineName(detail.pipeline_id) }}</span>
          <span class="ml-auto text-[11px] text-ink-400">
            {{ formatDate(detail.started_at, true) }} → {{ formatDate(detail.finished_at, true) }}
          </span>
        </div>

        <div v-if="detailLoading" class="py-10 text-center text-[12px] text-ink-400">详情加载中…</div>
        <div v-else-if="detailError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ detailError }}</span>
          <button class="shrink-0 font-medium" @click="loadDetail(detailRun)">重试</button>
        </div>
        <template v-else>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">耗时</div>
              <div class="text-[14px] font-semibold text-ink-800">{{ durationText(detail.duration_ms) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">输入行数</div>
              <div class="text-[14px] font-semibold text-ink-800">{{ formatNumber(detail.input_rows) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">输出行数</div>
              <div class="text-[14px] font-semibold text-ink-800">{{ formatNumber(detail.output_rows) }}</div>
            </div>
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="text-[11px] text-ink-400">水位</div>
              <div class="truncate text-[13px] font-medium text-ink-800">
                {{ detail.watermark_after || detail.watermark_before || '—' }}
              </div>
            </div>
          </div>

          <div v-if="detail.error" class="rounded-control bg-rose-50 px-3 py-2">
            <div class="text-[12px] font-medium text-rose-600">运行错误</div>
            <pre class="mt-1 whitespace-pre-wrap break-all text-[11px] text-rose-600">{{ detail.error }}</pre>
          </div>

          <div class="flex flex-wrap items-center gap-1.5">
            <button
              v-for="pane in DETAIL_PANES"
              :key="pane.key"
              class="rounded-pill px-2.5 py-1 text-[12px]"
              :class="detailPane === pane.key ? 'bg-ink-800 text-white' : 'border border-ink-200 bg-white text-ink-600'"
              @click="detailPane = pane.key"
            >
              {{ pane.label }}
              <span class="ml-1 text-[11px] opacity-70">{{ paneCount(pane.key) }}</span>
            </button>
            <span class="ml-auto flex flex-wrap gap-1.5">
              <button class="btn-outline py-1 text-[11px]" :disabled="busy" @click="cancelRun(detailRun)">取消运行</button>
              <button class="btn-outline py-1 text-[11px]" :disabled="busy || detail.status !== 'failed'" @click="retryFailed(detailRun)">
                重跑失败节点
              </button>
              <button class="btn-outline py-1 text-[11px]" :disabled="!previousRunId" @click="compareWithPrevious">
                与上次对比
              </button>
            </span>
          </div>

          <!-- 步骤 -->
          <div v-if="detailPane === 'steps'">
            <div v-if="stepsLoading" class="py-8 text-center text-[12px] text-ink-400">步骤加载中…</div>
            <div v-else-if="stepsError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ stepsError }}</div>
            <div v-else-if="!steps.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
              该运行还没有步骤明细
            </div>
            <div v-else class="overflow-x-auto">
              <table class="w-full min-w-[760px]">
                <thead>
                  <tr class="border-b border-ink-100">
                    <th class="th text-right">序号</th>
                    <th class="th">节点</th>
                    <th class="th">类型</th>
                    <th class="th">状态</th>
                    <th class="th text-right">尝试</th>
                    <th class="th text-right">耗时</th>
                    <th class="th text-right">输入 / 输出</th>
                    <th class="th">摘要 / 错误</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="step in steps" :key="step.id" :class="step.status === 'failed' ? 'bg-rose-50/40' : ''">
                    <td class="td text-right">{{ step.seq }}</td>
                    <td class="td font-mono text-[12px]">{{ step.node_key }}</td>
                    <td class="td text-[12px] text-ink-500">{{ step.node_type }}</td>
                    <td class="td">
                      <span class="tag" :class="statusClass(step.status)">{{ statusLabel(step.status) }}</span>
                    </td>
                    <td class="td text-right">{{ step.attempt }}</td>
                    <td class="td text-right">{{ durationText(step.duration_ms) }}</td>
                    <td class="td text-right text-[12px]">{{ formatNumber(step.input_rows) }} / {{ formatNumber(step.output_rows) }}</td>
                    <td class="td">
                      <div class="max-w-[240px] truncate text-[11px] text-ink-500">{{ step.error || step.summary || '—' }}</div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 日志 -->
          <div v-else-if="detailPane === 'logs'">
            <div class="mb-1.5 flex items-center gap-2">
              <span class="text-[11px] text-ink-400">最近 {{ logs.length }} 条</span>
              <button class="btn-ghost py-0.5 text-[11px]" :disabled="logsLoading" @click="loadLogs(detailRun)">刷新日志</button>
            </div>
            <div v-if="logsLoading" class="py-8 text-center text-[12px] text-ink-400">日志加载中…</div>
            <div v-else-if="logsError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ logsError }}</div>
            <div v-else-if="!logs.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
              暂无日志
            </div>
            <div v-else class="max-h-[320px] space-y-1 overflow-y-auto rounded-control bg-ink-900 px-3 py-2 font-mono text-[11px] leading-relaxed">
              <div v-for="log in logs" :key="log.id" class="flex gap-2">
                <span class="shrink-0 text-ink-500">{{ formatDate(log.logged_at, true) }}</span>
                <span class="shrink-0" :class="levelClass(log.level)">[{{ log.level }}]</span>
                <span v-if="log.node_key" class="shrink-0 text-sky-300">{{ log.node_key }}</span>
                <span class="min-w-0 flex-1 break-all text-ink-100">{{ log.message }}</span>
              </div>
            </div>
          </div>

          <!-- 输出预览 -->
          <div v-else>
            <div class="mb-2 flex flex-wrap items-center gap-2">
              <label class="flex items-center gap-1.5 text-[12px] text-ink-500">
                数据集
                <input v-model="outputDataset" class="input w-[150px] py-1" placeholder="default" />
              </label>
              <button class="btn-outline py-1 text-[11px]" :disabled="outputsLoading" @click="loadOutputs(detailRun)">
                {{ outputsLoading ? '加载中…' : '加载预览' }}
              </button>
              <span class="tag">前 {{ outputs.length }} 行</span>
            </div>
            <div v-if="outputsError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ outputsError }}</div>
            <div v-else-if="outputsLoading && !outputs.length" class="py-8 text-center text-[12px] text-ink-400">输出加载中…</div>
            <div v-else-if="!outputs.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
              该运行没有输出数据，或数据集名称不匹配
            </div>
            <div v-else class="overflow-x-auto">
              <table class="w-full">
                <thead>
                  <tr class="border-b border-ink-100">
                    <th class="th text-right">#</th>
                    <th v-for="column in outputColumns" :key="column" class="th">{{ column }}</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="row in outputs" :key="row.id">
                    <td class="td text-right text-[11px] text-ink-400">{{ row.seq }}</td>
                    <td v-for="column in outputColumns" :key="`${row.id}-${column}`" class="td font-mono text-[11px]">
                      <div class="max-w-[220px] truncate">{{ cellText(row.data?.[column]) }}</div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </div>
    </Modal>

    <!-- 运行对比 -->
    <Modal :show="compareOpen" title="运行对比" width="820px" @close="compareOpen = false">
      <div class="space-y-3">
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="text-[12px] text-ink-500">
            基准运行 A
            <input v-model="compareForm.a" type="number" min="1" class="input mt-1" placeholder="运行 ID" />
          </label>
          <label class="text-[12px] text-ink-500">
            对照运行 B
            <input v-model="compareForm.b" type="number" min="1" class="input mt-1" placeholder="运行 ID" />
          </label>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button class="btn-primary py-1 text-[12px]" :disabled="comparing" @click="runCompare">
            {{ comparing ? '对比中…' : '开始对比' }}
          </button>
          <span class="text-[11px] text-ink-400">默认取列表首条与第二条运行</span>
        </div>
        <div v-if="compareError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ compareError }}</div>
        <template v-else-if="compareResult">
          <div class="overflow-x-auto rounded-control border border-ink-100">
            <table class="w-full min-w-[520px]">
              <thead>
                <tr class="border-b border-ink-100 bg-ink-50/60">
                  <th class="th">指标</th>
                  <th class="th text-right">A</th>
                  <th class="th text-right">B</th>
                  <th class="th text-right">差异</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="row in compareRows" :key="row.key">
                  <td class="td text-[12px]">{{ row.label }}</td>
                  <td class="td text-right">{{ row.a }}</td>
                  <td class="td text-right">{{ row.b }}</td>
                  <td class="td text-right" :class="row.tone">{{ row.text }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <details class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
            <summary class="cursor-pointer">查看原始对比结果</summary>
            <pre class="mt-2 max-h-[240px] overflow-auto whitespace-pre-wrap break-all font-mono">{{ compactCompare }}</pre>
          </details>
        </template>
        <div v-else class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
          选择两次运行后点击开始对比
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { formatDate, formatNumber } from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  pipelines: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['refresh'])

const api = apiFor('pipeline')
const app = useAppStore()

const PAGE_SIZES = [10, 20, 50]
const DETAIL_PANES = [
  { key: 'steps', label: '步骤' },
  { key: 'logs', label: '日志' },
  { key: 'outputs', label: '输出预览' },
]
const STATUS_OPTIONS = [
  { value: 'running', label: '运行中' },
  { value: 'queued', label: '排队中' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]
const STATUS_LABELS = {
  queued: '排队中',
  pending: '待执行',
  running: '运行中',
  success: '成功',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
}
const TRIGGER_LABELS = {
  manual: '手动',
  schedule: '定时',
  webhook: '回调',
  retry: '重跑',
  api: '接口',
}

const items = ref([])
const loading = ref(false)
const error = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const statusFilter = ref('')
const pipelineFilter = ref('')

const busy = ref(false)
const triggerOpen = ref(false)
const triggering = ref(false)
const triggerForm = ref({ pipeline: '', trigger: 'manual' })

const detailOpen = ref(false)
const detailRun = ref(null)
const detail = ref({})
const detailLoading = ref(false)
const detailError = ref('')
const detailPane = ref('steps')

const steps = ref([])
const stepsLoading = ref(false)
const stepsError = ref('')
const logs = ref([])
const logsLoading = ref(false)
const logsError = ref('')
const outputs = ref([])
const outputsLoading = ref(false)
const outputsError = ref('')
const outputDataset = ref('default')

const compareOpen = ref(false)
const compareForm = ref({ a: '', b: '' })
const comparing = ref(false)
const compareError = ref('')
const compareResult = ref(null)

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

const statusCount = computed(() => {
  const counts = { running: 0, success: 0, failed: 0 }
  for (const run of items.value) {
    if (run.status === 'running' || run.status === 'queued') counts.running += 1
    else if (run.status === 'success') counts.success += 1
    else if (run.status === 'failed') counts.failed += 1
  }
  return counts
})

const pageOutputRows = computed(() => items.value.reduce((acc, run) => acc + (Number(run.output_rows) || 0), 0))

const previousRunId = computed(() => {
  if (!detailRun.value) return ''
  const index = items.value.findIndex((run) => run.id === detailRun.value.id)
  if (index >= 0 && items.value[index + 1]) return String(items.value[index + 1].id)
  return ''
})

const outputColumns = computed(() => {
  const columns = []
  for (const row of outputs.value) {
    const data = row?.data
    if (!data || typeof data !== 'object') continue
    for (const key of Object.keys(data)) {
      if (!columns.includes(key)) columns.push(key)
    }
    if (columns.length >= 8) break
  }
  return columns.slice(0, 8)
})

const compareSeed = computed(() => {
  const first = items.value[0]
  const second = items.value[1]
  return { a: first ? String(first.id) : '', b: second ? String(second.id) : '' }
})

const compactCompare = computed(() => {
  if (!compareResult.value) return ''
  try {
    return JSON.stringify(compareResult.value, null, 2)
  } catch (e) {
    return String(compareResult.value)
  }
})

const METRIC_LABELS = {
  duration_ms: '耗时(ms)',
  input_rows: '输入行数',
  output_rows: '输出行数',
  failed_steps: '失败步骤',
  total_steps: '步骤总数',
  node_count: '节点数',
  quality_failed: '质量失败数',
  error_count: '错误数',
}

const compareRows = computed(() => {
  const data = compareResult.value
  if (!data) return []
  if (Array.isArray(data.items)) {
    return data.items.map((item, index) => {
      const a = item.a ?? item.left ?? item.before ?? '—'
      const b = item.b ?? item.right ?? item.after ?? '—'
      return {
        key: item.metric || item.key || `row-${index}`,
        label: METRIC_LABELS[item.metric] || item.label || item.metric || `指标 ${index + 1}`,
        a: formatCell(a),
        b: formatCell(b),
        text: item.delta !== undefined ? formatCell(item.delta) : '—',
        tone: 'text-ink-500',
      }
    })
  }
  if (data.diff && typeof data.diff === 'object' && !Array.isArray(data.diff)) {
    return Object.entries(data.diff).map(([key, value]) => {
      const delta = typeof value === 'object' ? value.delta ?? value.diff : value
      return {
        key,
        label: METRIC_LABELS[key] || key,
        a: formatCell(data.a?.[key] ?? data.run_a?.[key] ?? '—'),
        b: formatCell(data.b?.[key] ?? data.run_b?.[key] ?? '—'),
        text: formatCell(delta),
        tone: Number(delta) > 0 ? 'text-rose-600' : Number(delta) < 0 ? 'text-emerald-600' : 'text-ink-500',
      }
    })
  }
  const sourceA = data.run_a || data.a || {}
  const sourceB = data.run_b || data.b || {}
  const keys = Object.keys(sourceA).filter((key) => typeof sourceA[key] === 'number' && key in sourceB)
  return keys.slice(0, 14).map((key) => {
    const delta = Number(sourceB[key]) - Number(sourceA[key])
    return {
      key,
      label: METRIC_LABELS[key] || key,
      a: formatCell(sourceA[key]),
      b: formatCell(sourceB[key]),
      text: `${delta > 0 ? '+' : ''}${formatCell(delta)}`,
      tone: delta > 0 ? 'text-rose-600' : delta < 0 ? 'text-emerald-600' : 'text-ink-500',
    }
  })
})

function formatCell(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number') return formatNumber(value, Number.isInteger(value) ? 0 : 2)
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function cellText(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function statusLabel(value) {
  return STATUS_LABELS[value] || value || '未知'
}

function statusClass(value) {
  const map = {
    success: 'bg-emerald-50 text-emerald-600',
    running: 'bg-amber-50 text-amber-600',
    queued: 'bg-sky-50 text-sky-600',
    pending: 'bg-sky-50 text-sky-600',
    failed: 'bg-rose-50 text-rose-600',
    cancelled: 'bg-ink-100 text-ink-500',
    skipped: 'bg-ink-100 text-ink-500',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

function levelClass(level) {
  const map = {
    error: 'text-rose-400',
    warn: 'text-amber-300',
    warning: 'text-amber-300',
    info: 'text-sky-300',
    debug: 'text-ink-400',
  }
  return map[String(level || '').toLowerCase()] || 'text-ink-300'
}

function triggerLabel(value) {
  return TRIGGER_LABELS[value] || value || '手动'
}

function durationText(ms) {
  const num = Number(ms)
  if (!Number.isFinite(num) || num <= 0) return '—'
  if (num < 1000) return `${num} ms`
  if (num < 60000) return `${(num / 1000).toFixed(1)} s`
  return `${(num / 60000).toFixed(1)} min`
}

function pipelineName(id) {
  const hit = props.pipelines.find((item) => String(item.id) === String(id))
  return hit ? hit.name : (id ? `管道 #${id}` : '—')
}

function pipelineCode(id) {
  const hit = props.pipelines.find((item) => String(item.id) === String(id))
  return hit ? hit.code : '—'
}

function canCancel(run) {
  return run && (run.status === 'running' || run.status === 'queued')
}

function paneCount(key) {
  if (key === 'steps') return steps.value.length
  if (key === 'logs') return logs.value.length
  return outputs.value.length
}

async function loadRuns() {
  if (!api) {
    error.value = '数据管道接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (statusFilter.value) params.status = statusFilter.value
    if (pipelineFilter.value) params.pipeline = pipelineFilter.value
    const data = await api.list('runs/', params)
    items.value = data.items || []
    total.value = data.count || 0
    if (data.page) page.value = Number(data.page) || page.value
  } catch (e) {
    items.value = []
    total.value = 0
    error.value = e?.message || '运行记录加载失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
  }
}

function reloadFirst() {
  page.value = 1
  loadRuns()
}

function goPage(next) {
  page.value = Math.min(Math.max(1, next), pages.value)
  loadRuns()
}

function changePageSize(next) {
  pageSize.value = Number(next) || 20
  page.value = 1
  loadRuns()
}

function openTrigger() {
  triggerForm.value = {
    pipeline: props.pipelines.length ? String(props.pipelines[0].id) : '',
    trigger: 'manual',
  }
  triggerOpen.value = true
}

async function submitTrigger() {
  if (!triggerForm.value.pipeline) {
    app.toastMsg('请选择要触发的管道', 'error')
    return
  }
  triggering.value = true
  try {
    await api.action(`pipelines/${triggerForm.value.pipeline}/run/`, { trigger: triggerForm.value.trigger })
    app.toastMsg('已提交运行', 'success')
    triggerOpen.value = false
    await loadRuns()
    emit('refresh')
  } catch (e) {
    app.toastMsg(e?.message || '触发运行失败', 'error')
  } finally {
    triggering.value = false
  }
}

async function cancelRun(run) {
  if (!run) return
  busy.value = true
  try {
    await api.action(`runs/${run.id}/cancel/`)
    app.toastMsg('已取消运行', 'success')
    await loadRuns()
    if (detailOpen.value) await loadDetail({ id: run.id })
  } catch (e) {
    app.toastMsg(e?.message || '取消运行失败', 'error')
  } finally {
    busy.value = false
  }
}

async function retryFailed(run) {
  if (!run) return
  busy.value = true
  try {
    await api.action(`runs/${run.id}/retry-failed/`)
    app.toastMsg('已提交失败节点重跑', 'success')
    await loadRuns()
    if (detailOpen.value) await loadDetail({ id: run.id })
  } catch (e) {
    app.toastMsg(e?.message || '重跑失败节点失败', 'error')
  } finally {
    busy.value = false
  }
}

async function openDetail(run) {
  detailRun.value = run
  detailPane.value = 'steps'
  detailOpen.value = true
  steps.value = []
  logs.value = []
  outputs.value = []
  compareResult.value = null
  await loadDetail(run)
}

async function loadDetail(run) {
  if (!api || !run) return
  detailLoading.value = true
  detailError.value = ''
  try {
    const data = await api.get(`runs/${run.id}/`)
    detail.value = data?.run || data || {}
    if (!detail.value.pipeline_id && detail.value.pipeline) {
      detail.value.pipeline_id = detail.value.pipeline
    }
  } catch (e) {
    detailError.value = e?.message || '运行详情加载失败'
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
  await Promise.all([loadSteps(run), loadLogs(run), loadOutputs(run)])
}

async function loadSteps(run) {
  if (!api || !run) return
  stepsLoading.value = true
  stepsError.value = ''
  try {
    const data = await api.list(`runs/${run.id}/steps/`, { page: 1, page_size: 200 })
    steps.value = (data.items || []).slice().sort((a, b) => (a.seq || 0) - (b.seq || 0))
  } catch (e) {
    steps.value = []
    stepsError.value = e?.message || '步骤加载失败'
  } finally {
    stepsLoading.value = false
  }
}

async function loadLogs(run) {
  if (!api || !run) return
  logsLoading.value = true
  logsError.value = ''
  try {
    const data = await api.list(`runs/${run.id}/logs/`, { page: 1, page_size: 200 })
    logs.value = data.items || []
  } catch (e) {
    logs.value = []
    logsError.value = e?.message || '日志加载失败'
  } finally {
    logsLoading.value = false
  }
}

async function loadOutputs(run) {
  if (!api || !run) return
  outputsLoading.value = true
  outputsError.value = ''
  try {
    const params = { run: run.id, page: 1, page_size: 20 }
    if (outputDataset.value.trim()) params.dataset = outputDataset.value.trim()
    const data = await api.list('outputs/', params)
    outputs.value = data.items || []
  } catch (e) {
    outputs.value = []
    outputsError.value = e?.message || '输出数据加载失败'
  } finally {
    outputsLoading.value = false
  }
}

function closeDetail() {
  detailOpen.value = false
  detailRun.value = null
  detail.value = {}
  steps.value = []
  logs.value = []
  outputs.value = []
}

function openCompare() {
  compareForm.value = { ...compareSeed.value }
  compareError.value = ''
  compareResult.value = null
  compareOpen.value = true
}

function compareWithPrevious() {
  if (!detailRun.value || !previousRunId.value) {
    app.toastMsg('没有可对比的上一条运行', 'error')
    return
  }
  compareForm.value = { a: String(detailRun.value.id), b: previousRunId.value }
  compareError.value = ''
  compareResult.value = null
  compareOpen.value = true
  runCompare()
}

async function runCompare() {
  const a = Number(compareForm.value.a)
  const b = Number(compareForm.value.b)
  if (!a || !b) {
    compareError.value = '请填写两次运行的 ID'
    return
  }
  if (a === b) {
    compareError.value = '请选择两次不同的运行'
    return
  }
  comparing.value = true
  compareError.value = ''
  try {
    compareResult.value = await api.get('runs/compare/', { a, b, run_a: a, run_b: b })
  } catch (e) {
    compareResult.value = null
    compareError.value = e?.message || '运行对比失败'
    app.toastMsg(compareError.value, 'error')
  } finally {
    comparing.value = false
  }
}

watch(() => props.refreshKey, () => loadRuns())

onMounted(() => loadRuns())
</script>