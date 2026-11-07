<template>
  <div class="space-y-3">
    <!-- 查询 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-end gap-2">
        <label class="text-[12px] text-ink-500">
          起点管道
          <select v-model="queryForm.pipeline" class="input mt-1 w-[230px] py-1">
            <option value="">请选择管道</option>
            <option v-for="item in pipelines" :key="item.id" :value="String(item.id)">
              {{ item.name }}（{{ item.code }}）
            </option>
          </select>
        </label>
        <label class="text-[12px] text-ink-500">
          节点标识（可选）
          <input v-model="queryForm.node" class="input mt-1 w-[170px] py-1 font-mono" placeholder="node_key" />
        </label>
        <label class="text-[12px] text-ink-500">
          资源标识（可选）
          <input v-model="queryForm.key" class="input mt-1 w-[200px] py-1 font-mono" placeholder="表名或数据集名" />
        </label>
        <div class="flex items-center gap-1">
          <button
            v-for="mode in MODES"
            :key="mode.key"
            class="rounded-pill px-2.5 py-1 text-[12px]"
            :class="modeKey === mode.key ? 'bg-ink-800 text-white' : 'border border-ink-200 bg-white text-ink-600 hover:bg-ink-50'"
            @click="modeKey = mode.key"
          >
            {{ mode.label }}
          </button>
        </div>
        <button class="btn-primary py-1 text-[12px]" :disabled="querying" @click="runQuery">
          {{ querying ? '查询中…' : '执行查询' }}
        </button>
        <button class="btn-outline py-1 text-[12px]" :disabled="loadingGraph" @click="loadGraph">
          {{ loadingGraph ? '加载中…' : '加载全图' }}
        </button>
        <span class="ml-auto text-[11px] text-ink-400">{{ modeHint }}</span>
      </div>
    </div>

    <!-- 查询结果 -->
    <SectionCard :title="resultTitle" :subtitle="resultSubtitle">
      <template #actions>
        <span class="tag">{{ resultRows.length }} 条关系</span>
        <button class="btn-ghost py-1 text-[12px]" :disabled="querying" @click="runQuery">重新查询</button>
      </template>

      <div v-if="queryError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ queryError }}</span>
        <button class="shrink-0 font-medium" @click="runQuery">重试</button>
      </div>
      <div v-else-if="querying && !resultRows.length" class="py-10 text-center text-[12px] text-ink-400">血缘查询中…</div>
      <div v-else-if="!resultRows.length && !queried" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
        选择管道后执行查询，即可查看上下游依赖与影响范围
      </div>
      <div v-else-if="!resultRows.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
        当前条件下没有血缘关系，可能是尚未产生运行或字段未登记
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[860px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">上游类型</th>
              <th class="th">上游标识</th>
              <th class="th">下游类型</th>
              <th class="th">下游标识</th>
              <th class="th">字段映射</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="(row, index) in resultRows" :key="`${row.upstreamKey}-${row.downstreamKey}-${index}`">
              <td class="td"><span class="tag">{{ typeLabel(row.upstreamType) }}</span></td>
              <td class="td font-mono text-[12px]">{{ row.upstreamKey }}</td>
              <td class="td"><span class="tag">{{ typeLabel(row.downstreamType) }}</span></td>
              <td class="td font-mono text-[12px]">{{ row.downstreamKey }}</td>
              <td class="td">
                <div class="flex flex-wrap gap-1">
                  <span v-for="(field, idx) in row.fieldMap" :key="idx" class="tag text-[10px]">
                    {{ fieldText(field) }}
                  </span>
                  <span v-if="!row.fieldMap.length" class="text-[11px] text-ink-400">—</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="impactSummary.length" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div v-for="item in impactSummary" :key="item.label" class="rounded-control bg-ink-50 px-3 py-2">
          <div class="text-[11px] text-ink-400">{{ item.label }}</div>
          <div class="text-[15px] font-semibold text-ink-800">{{ item.value }}</div>
        </div>
      </div>
    </SectionCard>

    <div class="grid gap-3 lg:grid-cols-5">
      <!-- 全图 -->
      <SectionCard class="lg:col-span-3" title="全图血缘" subtitle="按上下游关系自动分层，节点可点击查看详情">
        <template #actions>
          <select v-model="graphPipeline" class="input w-[180px] py-1" @change="loadGraph">
            <option value="">全部管道</option>
            <option v-for="item in pipelines" :key="item.id" :value="String(item.id)">{{ item.name }}</option>
          </select>
          <button class="btn-ghost py-1 text-[12px]" :disabled="loadingGraph" @click="loadGraph">刷新</button>
        </template>

        <div v-if="graphError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ graphError }}</span>
          <button class="shrink-0 font-medium" @click="loadGraph">重试</button>
        </div>
        <div v-else-if="loadingGraph && !graph.nodes.length" class="py-12 text-center text-[12px] text-ink-400">全图加载中…</div>
        <DagCanvas
          v-else
          :nodes="graph.nodes"
          :edges="graph.edges"
          :selected-key="selectedGraphKey"
          empty-text="还没有血缘节点，运行一次管道后会自动登记上下游"
          aria-label="数据血缘全图"
          @select="selectedGraphKey = $event"
        />
        <div v-if="selectedGraphNode" class="mt-2 rounded-control border border-brand-100 bg-brand-50/40 px-3 py-2 text-[12px] text-ink-600">
          节点 <span class="font-mono">{{ selectedGraphNode.key }}</span> ·
          类型 {{ typeLabel(selectedGraphNode.type) }}
          <button class="ml-2 text-[11px] text-brand-600" @click="queryFromNode(selectedGraphNode)">以此节点查询</button>
        </div>
      </SectionCard>

      <!-- 画像列表 -->
      <SectionCard class="lg:col-span-2" title="数据画像" subtitle="空值率、唯一值、最值与分布采样">
        <template #actions>
          <button class="btn-primary py-1 text-[12px]" :disabled="generating" @click="openGenerate">
            {{ generating ? '生成中…' : '生成画像' }}
          </button>
          <button class="btn-ghost py-1 text-[12px]" :disabled="profilesLoading" @click="loadProfiles">刷新</button>
        </template>

        <div v-if="profilesError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ profilesError }}</span>
          <button class="shrink-0 font-medium" @click="loadProfiles">重试</button>
        </div>
        <div v-else-if="profilesLoading && !profiles.length" class="py-10 text-center text-[12px] text-ink-400">画像加载中…</div>
        <div v-else-if="!profiles.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          暂无画像数据，可基于最近一次运行生成
        </div>
        <div v-else class="divide-y divide-ink-50">
          <button
            v-for="item in profiles"
            :key="item.id"
            class="flex w-full flex-wrap items-center gap-2 py-2 text-left transition-colors hover:bg-ink-50/70"
            @click="openProfile(item)"
          >
            <span class="min-w-0 flex-1 truncate text-[13px] text-ink-800">{{ item.dataset || 'default' }}</span>
            <span class="tag">{{ formatNumber(item.row_count) }} 行</span>
            <span class="tag">{{ item.column_count ?? columnCount(item) }} 列</span>
            <span v-if="highNullCount(item)" class="tag bg-amber-50 text-amber-600">高缺失 {{ highNullCount(item) }}</span>
            <span class="shrink-0 text-[11px] text-ink-400">{{ formatDate(item.sampled_at, true) }}</span>
          </button>
        </div>
      </SectionCard>
    </div>

    <!-- 生成画像 -->
    <Modal :show="generateOpen" title="生成数据画像" width="520px" @close="generateOpen = false">
      <form class="space-y-3" @submit.prevent="submitGenerate">
        <label class="block text-[12px] text-ink-500">
          管道
          <select v-model="generateForm.pipeline" class="input mt-1">
            <option value="">请选择管道</option>
            <option v-for="item in pipelines" :key="item.id" :value="String(item.id)">{{ item.name }}</option>
          </select>
        </label>
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="text-[12px] text-ink-500">
            运行 ID（可选）
            <input v-model="generateForm.run" class="input mt-1" placeholder="默认最近一次成功运行" />
          </label>
          <label class="text-[12px] text-ink-500">
            数据集
            <input v-model="generateForm.dataset" class="input mt-1" placeholder="default" />
          </label>
        </div>
        <div v-if="generateError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ generateError }}</div>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="generateOpen = false">取消</button>
          <button type="submit" class="btn-primary" :disabled="generating">{{ generating ? '生成中…' : '开始生成' }}</button>
        </div>
      </form>
    </Modal>

    <!-- 画像详情 -->
    <Modal :show="profileOpen" :title="profileTitle" width="980px" @close="profileOpen = false">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag">{{ profileDetail.dataset || 'default' }}</span>
          <span class="tag">{{ formatNumber(profileDetail.row_count) }} 行</span>
          <span class="tag">采样 {{ formatNumber(profileDetail.sample_size) }} 行</span>
          <span class="text-[11px] text-ink-400">采样时间 {{ formatDate(profileDetail.sampled_at, true) }}</span>
          <button class="btn-outline ml-auto py-1 text-[11px]" :disabled="profileLoading" @click="reloadProfile">刷新</button>
        </div>
        <div v-if="profileLoading" class="py-10 text-center text-[12px] text-ink-400">画像详情加载中…</div>
        <div v-else-if="profileError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ profileError }}</div>
        <div v-else-if="!profileColumns.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          该画像没有字段明细
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[860px]">
            <thead>
              <tr class="border-b border-ink-100">
                <th class="th">字段</th>
                <th class="th">空值率</th>
                <th class="th text-right">唯一值</th>
                <th class="th">最小值</th>
                <th class="th">最大值</th>
                <th class="th">分布</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="column in profileColumns" :key="column.name">
                <td class="td">
                  <div class="font-mono text-[12px] text-ink-800">{{ column.name }}</div>
                  <div class="text-[11px] text-ink-400">{{ column.type || column.dtype || '—' }}</div>
                </td>
                <td class="td">
                  <div class="flex items-center gap-2">
                    <div class="h-1.5 w-20 overflow-hidden rounded-pill bg-ink-100">
                      <div
                        class="h-full rounded-pill"
                        :class="column.nullRate >= 50 ? 'bg-rose-500' : column.nullRate >= 10 ? 'bg-amber-500' : 'bg-emerald-500'"
                        :style="{ width: `${Math.min(100, column.nullRate)}%` }"
                      ></div>
                    </div>
                    <span class="text-[11px] text-ink-500">{{ column.nullRate.toFixed(1) }}%</span>
                  </div>
                </td>
                <td class="td text-right">{{ formatNumber(column.uniqueCount) }}</td>
                <td class="td font-mono text-[11px]">{{ column.minText }}</td>
                <td class="td font-mono text-[11px]">{{ column.maxText }}</td>
                <td class="td">
                  <div v-if="column.distribution.length" class="space-y-0.5">
                    <div v-for="bucket in column.distribution" :key="bucket.label" class="flex items-center gap-1.5">
                      <span class="w-16 shrink-0 truncate text-right text-[10px] text-ink-400">{{ bucket.label }}</span>
                      <div class="h-1.5 flex-1 overflow-hidden rounded-pill bg-ink-100">
                        <div class="h-full rounded-pill bg-brand-500" :style="{ width: `${bucket.percent}%` }"></div>
                      </div>
                      <span class="w-10 shrink-0 text-[10px] text-ink-400">{{ formatNumber(bucket.value) }}</span>
                    </div>
                  </div>
                  <span v-else class="text-[11px] text-ink-400">无分布数据</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="profileDetail.notes" class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
          备注：{{ profileDetail.notes }}
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiFor, listOf } from '../../api/platform'
import { formatDate, formatNumber } from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import DagCanvas from './DagCanvas.vue'

const props = defineProps({
  pipelines: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})

const api = apiFor('pipeline')
const app = useAppStore()

const MODES = [
  { key: 'upstream', label: '上游', path: 'lineage/upstream/', hint: '查询当前节点的数据来源链路' },
  { key: 'downstream', label: '下游', path: 'lineage/downstream/', hint: '查询当前节点流向的消费方' },
  { key: 'impact', label: '影响分析', path: 'lineage/impact/', hint: '评估变更会波及的下游对象数量' },
]

const TYPE_LABELS = {
  pipeline: '管道',
  table: '数据表',
  dataset: '数据集',
  report: '报表',
  file: '文件',
  api: '接口',
  node: '节点',
  external: '外部系统',
}

const modeKey = ref('upstream')
const queryForm = reactive({ pipeline: '', node: '', key: '' })
const querying = ref(false)
const queryError = ref('')
const queried = ref(false)
const resultRows = ref([])
const impactStats = ref({})

const graphPipeline = ref('')
const graph = ref({ nodes: [], edges: [] })
const graphError = ref('')
const loadingGraph = ref(false)
const selectedGraphKey = ref('')

const profiles = ref([])
const profilesLoading = ref(false)
const profilesError = ref('')

const generateOpen = ref(false)
const generating = ref(false)
const generateError = ref('')
const generateForm = reactive({ pipeline: '', run: '', dataset: 'default' })

const profileOpen = ref(false)
const profileLoading = ref(false)
const profileError = ref('')
const profileDetail = ref({})
const activeProfile = ref(null)

const modeMeta = computed(() => MODES.find((item) => item.key === modeKey.value) || MODES[0])
const modeHint = computed(() => modeMeta.value.hint)

const resultTitle = computed(() => {
  if (modeKey.value === 'impact') return '影响分析结果'
  return modeKey.value === 'downstream' ? '下游血缘' : '上游血缘'
})

const resultSubtitle = computed(() => {
  const name = pipelineName(queryForm.pipeline)
  if (modeKey.value === 'impact') return `${name} 变更后可能受影响的对象`
  return `${name} 的${modeKey.value === 'downstream' ? '下游消费' : '上游来源'}关系`
})

const selectedGraphNode = computed(() => graph.value.nodes.find((node) => node.key === selectedGraphKey.value) || null)

const impactSummary = computed(() => {
  const stats = impactStats.value || {}
  const rows = []
  const mapping = [
    ['downstream_count', '受影响下游'],
    ['total_affected', '影响对象总数'],
    ['pipeline_count', '涉及管道'],
    ['report_count', '涉及报表'],
    ['depth', '最大层级'],
  ]
  for (const [key, label] of mapping) {
    if (stats[key] !== undefined && stats[key] !== null) {
      rows.push({ label, value: formatNumber(stats[key]) })
    }
  }
  return rows
})

const profileTitle = computed(() => {
  const dataset = profileDetail.value.dataset || activeProfile.value?.dataset || 'default'
  return `字段画像 · ${dataset}`
})

const profileColumns = computed(() => {
  const columns = Array.isArray(profileDetail.value.columns) ? profileDetail.value.columns : []
  return columns.map((column) => {
    const nullRateRaw = Number(column.null_rate ?? column.nullRate ?? 0)
    const nullRate = nullRateRaw > 0 && nullRateRaw <= 1 ? nullRateRaw * 100 : nullRateRaw
    const distribution = normalizeDistribution(column.distribution || column.histogram || column.top_values)
    return {
      name: column.name || column.field || column.column || '未命名字段',
      type: column.type || column.dtype || column.data_type || '',
      nullRate: Number.isFinite(nullRate) ? nullRate : 0,
      uniqueCount: Number(column.unique_count ?? column.distinct ?? column.unique ?? 0) || 0,
      minText: column.min === undefined || column.min === null ? '—' : String(column.min),
      maxText: column.max === undefined || column.max === null ? '—' : String(column.max),
      distribution,
    }
  })
})

function normalizeDistribution(raw) {
  const items = Array.isArray(raw)
    ? raw
    : raw && typeof raw === 'object'
      ? Object.entries(raw).map(([label, value]) => ({ label, value }))
      : []
  const rows = items.map((item) => ({
    label: String(item.label ?? item.bucket ?? item.key ?? '—'),
    value: Number(item.value ?? item.count ?? item.n ?? 0) || 0,
  }))
  const max = rows.reduce((acc, item) => Math.max(acc, item.value), 0)
  return rows.slice(0, 5).map((item) => ({
    ...item,
    percent: max ? Math.max(2, Math.round((item.value / max) * 100)) : 0,
  }))
}

function typeLabel(value) {
  return TYPE_LABELS[value] || value || '资源'
}

function pipelineName(id) {
  const hit = props.pipelines.find((item) => String(item.id) === String(id))
  return hit ? hit.name : (id ? `管道 #${id}` : '全部管道')
}

function fieldText(field) {
  if (!field) return '—'
  if (typeof field === 'string') return field
  const from = field.source || field.from || field.source_field || ''
  const to = field.target || field.to || field.target_field || ''
  if (from || to) return `${from || '—'} → ${to || '—'}`
  return JSON.stringify(field)
}

function highNullCount(item) {
  if (Array.isArray(item.high_null_columns)) return item.high_null_columns.length
  return 0
}

function columnCount(item) {
  if (Array.isArray(item.columns)) return item.columns.length
  return item.column_count ?? 0
}

function buildParams() {
  const params = {}
  if (queryForm.pipeline) {
    params.pipeline = Number(queryForm.pipeline)
    params.type = 'pipeline'
    params.key = pipelineCode(queryForm.pipeline)
  }
  if (queryForm.node.trim()) {
    params.node_key = queryForm.node.trim()
    if (!params.key) params.key = queryForm.node.trim()
  }
  if (queryForm.key.trim()) params.key = queryForm.key.trim()
  return params
}

function pipelineCode(id) {
  const hit = props.pipelines.find((item) => String(item.id) === String(id))
  return hit ? hit.code : ''
}

function normalizeRows(data) {
  const source = Array.isArray(data?.items)
    ? data.items
    : Array.isArray(data?.edges)
      ? data.edges
      : Array.isArray(data?.relations)
        ? data.relations
        : listOf(data)
  return source.map((row) => ({
    upstreamType: row.upstream_type || row.source_type || row.type || '',
    upstreamKey: row.upstream_key || row.source_key || row.source || row.from || '—',
    downstreamType: row.downstream_type || row.target_type || row.type || '',
    downstreamKey: row.downstream_key || row.target_key || row.target || row.to || '—',
    fieldMap: Array.isArray(row.field_map) ? row.field_map : [],
  }))
}

async function runQuery() {
  if (!api) {
    queryError.value = '数据管道接口不可用'
    return
  }
  if (!queryForm.pipeline && !queryForm.node.trim() && !queryForm.key.trim()) {
    queryError.value = '请选择管道，或填写节点标识 / 资源标识'
    return
  }
  querying.value = true
  queryError.value = ''
  queried.value = true
  resultRows.value = []
  impactStats.value = {}
  try {
    const data = await api.get(modeMeta.value.path, buildParams())
    resultRows.value = normalizeRows(data)
    impactStats.value = data?.stats || data?.summary || {}
    if (!impactStats.value || typeof impactStats.value !== 'object') impactStats.value = {}
    if (!resultRows.value.length) {
      app.toastMsg('查询完成，暂无血缘关系', 'info')
    }
  } catch (e) {
    queryError.value = e?.message || '血缘查询失败'
    app.toastMsg(queryError.value, 'error')
  } finally {
    querying.value = false
  }
}

async function loadGraph() {
  if (!api) {
    graphError.value = '数据管道接口不可用'
    return
  }
  loadingGraph.value = true
  graphError.value = ''
  try {
    const params = {}
    if (graphPipeline.value) params.pipeline = Number(graphPipeline.value)
    const data = await api.get('lineage/graph/', params)
    const rawNodes = Array.isArray(data?.nodes) ? data.nodes : (Array.isArray(data?.items) ? data.items : [])
    const rawEdges = Array.isArray(data?.edges) ? data.edges : (Array.isArray(data?.links) ? data.links : [])
    graph.value = {
      nodes: rawNodes.map((node, index) => ({
        key: String(node.key ?? node.node_key ?? node.id ?? `node-${index}`),
        label: node.label || node.name || node.key || node.node_key || '未命名',
        type: node.type || node.node_type || node.kind || '',
      })),
      edges: rawEdges.map((edge) => ({
        source: String(edge.source ?? edge.source_key ?? edge.upstream_key ?? edge.from ?? ''),
        target: String(edge.target ?? edge.target_key ?? edge.downstream_key ?? edge.to ?? ''),
        label: edge.label || '',
      })).filter((edge) => edge.source && edge.target),
    }
    selectedGraphKey.value = ''
  } catch (e) {
    graphError.value = e?.message || '血缘全图加载失败'
    app.toastMsg(graphError.value, 'error')
  } finally {
    loadingGraph.value = false
  }
}

function queryFromNode(node) {
  selectedGraphKey.value = node.key
  queryForm.node = node.key
  queryForm.pipeline = ''
  queryForm.key = node.key
  modeKey.value = 'downstream'
  runQuery()
}

async function loadProfiles() {
  if (!api) return
  profilesLoading.value = true
  profilesError.value = ''
  try {
    const params = { page: 1, page_size: 50 }
    if (graphPipeline.value) params.pipeline = graphPipeline.value
    const data = await api.list('profiles/', params)
    profiles.value = data.items || []
  } catch (e) {
    profiles.value = []
    profilesError.value = e?.message || '画像列表加载失败'
  } finally {
    profilesLoading.value = false
  }
}

function openGenerate() {
  generateForm.pipeline = graphPipeline.value || queryForm.pipeline || (props.pipelines[0] ? String(props.pipelines[0].id) : '')
  generateForm.run = ''
  generateForm.dataset = 'default'
  generateError.value = ''
  generateOpen.value = true
}

async function submitGenerate() {
  if (!generateForm.pipeline) {
    generateError.value = '请选择要生成画像的管道'
    return
  }
  generating.value = true
  generateError.value = ''
  try {
    const payload = { pipeline: Number(generateForm.pipeline) }
    if (generateForm.run.trim()) payload.run_id = Number(generateForm.run.trim())
    if (generateForm.dataset.trim()) payload.dataset = generateForm.dataset.trim()
    const data = await api.action('profiles/generate/', payload)
    app.toastMsg('画像已生成', 'success')
    generateOpen.value = false
    await loadProfiles()
    if (data?.id) await openProfile(data)
  } catch (e) {
    generateError.value = e?.message || '生成画像失败'
    app.toastMsg(generateError.value, 'error')
  } finally {
    generating.value = false
  }
}

async function openProfile(item) {
  activeProfile.value = item
  profileDetail.value = { ...item }
  profileOpen.value = true
  profileLoading.value = true
  profileError.value = ''
  try {
    const data = await api.get(`profiles/${item.id}/`)
    profileDetail.value = { ...item, ...(data?.profile || data) }
  } catch (e) {
    profileError.value = e?.message || '画像详情加载失败'
  } finally {
    profileLoading.value = false
  }
}

async function reloadProfile() {
  if (!activeProfile.value) return
  await openProfile(activeProfile.value)
}

watch(() => props.refreshKey, () => {
  loadGraph()
  loadProfiles()
})

watch(graphPipeline, () => {
  loadProfiles()
})

onMounted(() => {
  if (props.pipelines.length) {
    queryForm.pipeline = String(props.pipelines[0].id)
    graphPipeline.value = String(props.pipelines[0].id)
  }
  loadGraph()
  loadProfiles()
})
</script>