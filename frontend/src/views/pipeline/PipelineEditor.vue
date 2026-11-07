<template>
  <div class="space-y-3">
    <!-- 头部 -->
    <div class="flex flex-wrap items-center gap-2">
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[14px] font-semibold text-ink-900">{{ pipeline?.name || '未命名管道' }}</span>
          <span class="tag">{{ pipeline?.code || '—' }}</span>
          <span class="tag" :class="statusClass(pipeline?.status)">{{ statusLabel(pipeline?.status) }}</span>
          <span v-if="pipeline?.version" class="tag">v{{ pipeline.version }}</span>
        </div>
        <p class="mt-1 text-[12px] text-ink-400">
          节点 {{ nodes.length }} 个 · 连线 {{ edges.length }} 条 · 映射 {{ mappings.length }} 条
          <span v-if="pipeline?.concurrency"> · 并发 {{ pipeline.concurrency }}</span>
          <span v-if="pipeline?.timeout_seconds"> · 超时 {{ pipeline.timeout_seconds }}s</span>
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <button class="btn-outline py-1 text-[12px]" :disabled="loading" @click="loadAll">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <button class="btn-primary py-1 text-[12px]" :disabled="validating" @click="validateDag">
          {{ validating ? '校验中…' : '校验 DAG' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
      <span class="min-w-0 flex-1">{{ error }}</span>
      <button class="shrink-0 font-medium" @click="loadAll">重试</button>
    </div>

    <!-- 编辑分区 -->
    <div class="flex flex-wrap items-center gap-1.5">
      <button
        v-for="section in SECTIONS"
        :key="section.key"
        class="rounded-pill px-2.5 py-1 text-[12px]"
        :class="section_key === section.key
          ? 'bg-ink-800 text-white'
          : 'border border-ink-200 bg-white text-ink-600 hover:bg-ink-50'"
        @click="section_key = section.key"
      >
        {{ section.label }}
        <span class="ml-1 text-[11px] opacity-70">{{ sectionCount(section.key) }}</span>
      </button>
      <span class="ml-auto text-[11px] text-ink-400">节点增删改会立即写入后端，拓扑按连线自动分层</span>
    </div>

    <!-- 节点 -->
    <div v-if="section_key === 'nodes'" class="space-y-2">
      <div class="flex flex-wrap items-center gap-1.5">
        <button class="btn-primary py-1 text-[12px]" @click="openNodeCreate">新增节点</button>
        <button class="btn-ghost py-1 text-[12px]" :disabled="nodesLoading" @click="loadNodes">刷新节点</button>
        <span class="tag">{{ NODE_TYPES.length }} 种节点类型</span>
      </div>

      <div v-if="nodesLoading && !nodes.length" class="py-10 text-center text-[12px] text-ink-400">节点加载中…</div>
      <div v-else-if="!nodes.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
        还没有节点，建议先添加 source 数据源节点与 sink 输出节点
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[760px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">标识</th>
              <th class="th">名称</th>
              <th class="th">类型</th>
              <th class="th">状态</th>
              <th class="th">配置摘要</th>
              <th class="th text-right">排序</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="node in nodes" :key="node.id" class="transition-colors hover:bg-ink-50/60">
              <td class="td font-mono text-[12px]">{{ node.node_key }}</td>
              <td class="td">{{ node.name }}</td>
              <td class="td"><span class="tag">{{ typeLabel(node.node_type) }}</span></td>
              <td class="td">
                <span class="tag" :class="node.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                  {{ node.enabled ? '启用' : '停用' }}
                </span>
              </td>
              <td class="td">
                <div class="max-w-[260px] truncate font-mono text-[11px] text-ink-400">{{ configSummary(node.config) }}</div>
              </td>
              <td class="td text-right">{{ node.order ?? '—' }}</td>
              <td class="td text-right">
                <div class="flex justify-end gap-1">
                  <button class="btn-ghost py-0.5 text-[11px]" @click="openNodeEdit(node)">编辑</button>
                  <button class="btn-ghost py-0.5 text-[11px]" @click="toggleNode(node)">
                    {{ node.enabled ? '停用' : '启用' }}
                  </button>
                  <button class="btn-danger py-0.5 text-[11px]" @click="removeNode(node)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 连线 -->
    <div v-else-if="section_key === 'edges'" class="space-y-2">
      <div class="rounded-control border border-ink-100 bg-ink-50/60 p-2.5">
        <div class="flex flex-wrap items-end gap-2">
          <label class="text-[12px] text-ink-500">
            上游节点
            <select v-model="edgeForm.source" class="input mt-1 w-[190px] py-1">
              <option value="">请选择</option>
              <option v-for="node in nodes" :key="node.id" :value="String(node.id)">
                {{ node.name }}（{{ node.node_key }}）
              </option>
            </select>
          </label>
          <label class="text-[12px] text-ink-500">
            下游节点
            <select v-model="edgeForm.target" class="input mt-1 w-[190px] py-1">
              <option value="">请选择</option>
              <option v-for="node in nodes" :key="node.id" :value="String(node.id)">
                {{ node.name }}（{{ node.node_key }}）
              </option>
            </select>
          </label>
          <label class="text-[12px] text-ink-500">
            上游端口
            <input v-model="edgeForm.source_port" class="input mt-1 w-[100px] py-1" placeholder="out" />
          </label>
          <label class="text-[12px] text-ink-500">
            下游端口
            <input v-model="edgeForm.target_port" class="input mt-1 w-[100px] py-1" placeholder="in" />
          </label>
          <button class="btn-primary py-1 text-[12px]" :disabled="edgeSaving" @click="createEdge">
            {{ edgeSaving ? '保存中…' : '添加连线' }}
          </button>
          <button class="btn-ghost py-1 text-[12px]" :disabled="edgesLoading" @click="loadEdges">刷新</button>
        </div>
        <p class="mt-1.5 text-[11px] text-ink-400">连线代表数据流向，不允许自环；保存后由后端做 DAG 合法性检查</p>
      </div>

      <div v-if="edgesLoading && !edges.length" class="py-8 text-center text-[12px] text-ink-400">连线加载中…</div>
      <div v-else-if="!edges.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
        暂无连线，节点之间还没有数据流
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[620px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">上游</th>
              <th class="th">下游</th>
              <th class="th">端口</th>
              <th class="th text-right">排序</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="edge in edges" :key="edge.id">
              <td class="td">{{ nodeLabel(edge.source) }}</td>
              <td class="td">{{ nodeLabel(edge.target) }}</td>
              <td class="td text-[12px] text-ink-500">{{ edge.source_port || 'out' }} → {{ edge.target_port || 'in' }}</td>
              <td class="td text-right">{{ edge.order ?? '—' }}</td>
              <td class="td text-right">
                <button class="btn-danger py-0.5 text-[11px]" @click="removeEdge(edge)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 字段映射 -->
    <div v-else-if="section_key === 'mappings'" class="space-y-2">
      <div class="rounded-control border border-ink-100 bg-ink-50/60 p-2.5">
        <div class="flex flex-wrap items-end gap-2">
          <label class="text-[12px] text-ink-500">
            所属节点
            <select v-model="mappingForm.node" class="input mt-1 w-[170px] py-1">
              <option value="">不限节点</option>
              <option v-for="node in nodes" :key="node.id" :value="String(node.id)">{{ node.name }}</option>
            </select>
          </label>
          <label class="text-[12px] text-ink-500">
            源字段
            <input v-model="mappingForm.source_field" class="input mt-1 w-[140px] py-1" placeholder="order_id" />
          </label>
          <label class="text-[12px] text-ink-500">
            目标字段
            <input v-model="mappingForm.target_field" class="input mt-1 w-[140px] py-1" placeholder="id" />
          </label>
          <label class="text-[12px] text-ink-500">
            类型转换
            <select v-model="mappingForm.cast" class="input mt-1 w-[110px] py-1">
              <option value="">不转换</option>
              <option v-for="cast in CAST_TYPES" :key="cast" :value="cast">{{ cast }}</option>
            </select>
          </label>
          <label class="flex items-center gap-1 pb-1.5 text-[12px] text-ink-600">
            <input v-model="mappingForm.required" type="checkbox" /> 必填
          </label>
          <button class="btn-primary py-1 text-[12px]" :disabled="mappingSaving" @click="createMapping">
            {{ mappingSaving ? '保存中…' : '添加映射' }}
          </button>
          <button class="btn-ghost py-1 text-[12px]" :disabled="mappingsLoading" @click="loadMappings">刷新</button>
        </div>
        <div class="mt-2 flex flex-wrap items-end gap-2">
          <label class="flex-1 text-[12px] text-ink-500">
            取值表达式（可选，支持引用上游字段）
            <input v-model="mappingForm.expression" class="input mt-1 py-1" placeholder="例如 upper(name) 或 amount * 100" />
          </label>
          <label class="text-[12px] text-ink-500">
            默认值
            <input v-model="mappingForm.default_value" class="input mt-1 w-[140px] py-1" placeholder="留空表示无" />
          </label>
        </div>
      </div>

      <div v-if="mappingsLoading && !mappings.length" class="py-8 text-center text-[12px] text-ink-400">映射加载中…</div>
      <div v-else-if="!mappings.length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
        暂无字段映射，输出将沿用上游字段名
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[700px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">节点</th>
              <th class="th">源字段</th>
              <th class="th">目标字段</th>
              <th class="th">转换</th>
              <th class="th">表达式</th>
              <th class="th">必填</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="mapping in mappings" :key="mapping.id">
              <td class="td text-[12px] text-ink-500">{{ mapping.node ? nodeLabel(mapping.node) : '全管道' }}</td>
              <td class="td font-mono text-[12px]">{{ mapping.source_field || '—' }}</td>
              <td class="td font-mono text-[12px]">{{ mapping.target_field }}</td>
              <td class="td">{{ mapping.cast || '—' }}</td>
              <td class="td">
                <div class="max-w-[220px] truncate font-mono text-[11px] text-ink-500">{{ mapping.expression || '—' }}</div>
              </td>
              <td class="td">
                <span class="tag" :class="mapping.required ? 'bg-amber-50 text-amber-600' : ''">
                  {{ mapping.required ? '必填' : '可选' }}
                </span>
              </td>
              <td class="td text-right">
                <button class="btn-danger py-0.5 text-[11px]" @click="removeMapping(mapping)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 拓扑 -->
    <div v-else class="space-y-2">
      <div class="flex flex-wrap items-center gap-1.5">
        <button class="btn-outline py-1 text-[12px]" :disabled="validating" @click="validateDag">
          {{ validating ? '校验中…' : '重新校验' }}
        </button>
        <span v-if="validation" class="tag" :class="validation.ok ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
          {{ validation.ok ? 'DAG 校验通过' : 'DAG 校验未通过' }}
        </span>
      </div>

      <div v-if="validation" class="grid gap-2 md:grid-cols-2">
        <div class="rounded-control border border-ink-100 p-2.5">
          <div class="mb-1 text-[12px] font-medium text-rose-600">错误 {{ validation.errors.length }} 条</div>
          <ul v-if="validation.errors.length" class="space-y-1 text-[11px] text-rose-600">
            <li v-for="(item, index) in validation.errors" :key="`err-${index}`" class="break-all">· {{ item }}</li>
          </ul>
          <p v-else class="text-[11px] text-ink-400">没有阻塞性错误</p>
        </div>
        <div class="rounded-control border border-ink-100 p-2.5">
          <div class="mb-1 text-[12px] font-medium text-amber-600">警告 {{ validation.warnings.length }} 条</div>
          <ul v-if="validation.warnings.length" class="space-y-1 text-[11px] text-amber-700">
            <li v-for="(item, index) in validation.warnings" :key="`warn-${index}`" class="break-all">· {{ item }}</li>
          </ul>
          <p v-else class="text-[11px] text-ink-400">没有告警项</p>
        </div>
      </div>

      <div class="rounded-control border border-ink-100 p-2.5">
        <DagCanvas
          :nodes="dagNodes"
          :edges="dagEdges"
          :selected-key="selectedKey"
          empty-text="暂无节点，先到「节点」分区添加 source 与 sink"
          @select="selectedKey = $event"
        />
      </div>

      <div v-if="validation?.order?.length" class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
        拓扑顺序：{{ validation.order.join(' → ') }}
      </div>
      <div v-if="selectedNode" class="rounded-control border border-brand-100 bg-brand-50/50 px-3 py-2 text-[12px] text-ink-600">
        已选节点 {{ selectedNode.node_key }}（{{ typeLabel(selectedNode.node_type) }}），
        配置：<span class="font-mono text-[11px]">{{ configSummary(selectedNode.config) }}</span>
      </div>
    </div>

    <!-- 节点表单 -->
    <Modal
      :show="nodeModalOpen"
      :title="nodeForm.id ? `编辑节点 ${nodeForm.node_key}` : '新增节点'"
      width="660px"
      @close="nodeModalOpen = false"
    >
      <form class="space-y-3" @submit.prevent="saveNode">
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="text-[12px] text-ink-500">
            节点标识
            <input v-model="nodeForm.node_key" class="input mt-1" placeholder="extract_orders" />
          </label>
          <label class="text-[12px] text-ink-500">
            节点名称
            <input v-model="nodeForm.name" class="input mt-1" placeholder="抽取订单" />
          </label>
          <label class="text-[12px] text-ink-500">
            节点类型
            <select v-model="nodeForm.node_type" class="input mt-1">
              <option v-for="type in NODE_TYPES" :key="type.value" :value="type.value">{{ type.label }}</option>
            </select>
          </label>
          <label class="flex items-center gap-2 pt-5 text-[12px] text-ink-600">
            <input v-model="nodeForm.enabled" type="checkbox" /> 启用该节点
          </label>
        </div>
        <label class="block text-[12px] text-ink-500">
          节点配置（JSON）
          <textarea
            v-model="nodeForm.configText"
            rows="8"
            class="input mt-1 font-mono text-[12px]"
            placeholder='{"table": "orders", "limit": 1000}'
          ></textarea>
        </label>
        <label class="block text-[12px] text-ink-500">
          说明
          <textarea v-model="nodeForm.description" rows="2" class="input mt-1"></textarea>
        </label>
        <div v-if="nodeFormError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ nodeFormError }}</div>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="nodeModalOpen = false">取消</button>
          <button type="submit" class="btn-primary" :disabled="nodeSaving">{{ nodeSaving ? '保存中…' : '保存节点' }}</button>
        </div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import DagCanvas from './DagCanvas.vue'

const props = defineProps({
  pipeline: { type: Object, default: null },
})
const emit = defineEmits(['changed'])

const api = apiFor('pipeline')
const app = useAppStore()

const SECTIONS = [
  { key: 'nodes', label: '节点' },
  { key: 'edges', label: '连线' },
  { key: 'mappings', label: '字段映射' },
  { key: 'topology', label: '拓扑' },
]

const NODE_TYPES = [
  { value: 'source', label: '数据源 source' },
  { value: 'transform', label: '转换 transform' },
  { value: 'filter', label: '过滤 filter' },
  { value: 'aggregate', label: '聚合 aggregate' },
  { value: 'join', label: '关联 join' },
  { value: 'sort', label: '排序 sort' },
  { value: 'dedupe', label: '去重 dedupe' },
  { value: 'map', label: '映射 map' },
  { value: 'sink', label: '输出 sink' },
  { value: 'webhook', label: '回调 webhook' },
]

const CAST_TYPES = ['string', 'integer', 'number', 'boolean', 'date', 'datetime', 'json']

const section_key = ref('nodes')
const nodes = ref([])
const edges = ref([])
const mappings = ref([])
const nodesLoading = ref(false)
const edgesLoading = ref(false)
const mappingsLoading = ref(false)
const loading = ref(false)
const error = ref('')
const validating = ref(false)
const validation = ref(null)
const selectedKey = ref('')

const nodeModalOpen = ref(false)
const nodeSaving = ref(false)
const nodeFormError = ref('')
const nodeForm = ref(emptyNode())

const edgeSaving = ref(false)
const edgeForm = ref({ source: '', target: '', source_port: 'out', target_port: 'in' })

const mappingSaving = ref(false)
const mappingForm = ref({ node: '', source_field: '', target_field: '', cast: '', expression: '', default_value: '', required: false })

function emptyNode() {
  return { id: null, node_key: '', name: '', node_type: 'transform', enabled: true, description: '', configText: '{}' }
}

const TYPE_LABEL_MAP = NODE_TYPES.reduce((acc, item) => {
  acc[item.value] = item.label.split(' ')[0]
  return acc
}, {})

const STATUS_LABELS = {
  draft: '草稿',
  published: '已发布',
  paused: '已暂停',
  archived: '已归档',
}

function typeLabel(type) {
  return TYPE_LABEL_MAP[type] || type || '节点'
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || '未知'
}

function statusClass(status) {
  const map = {
    published: 'bg-emerald-50 text-emerald-600',
    draft: 'bg-sky-50 text-sky-600',
    paused: 'bg-amber-50 text-amber-600',
    archived: 'bg-ink-100 text-ink-500',
  }
  return map[status] || 'bg-ink-100 text-ink-500'
}

function configSummary(config) {
  if (!config || typeof config !== 'object') return '—'
  const keys = Object.keys(config)
  if (!keys.length) return '{}'
  return keys.slice(0, 4).map((key) => `${key}=${JSON.stringify(config[key])}`).join('，')
}

function sectionCount(key) {
  if (key === 'nodes') return nodes.value.length
  if (key === 'edges') return edges.value.length
  if (key === 'mappings') return mappings.value.length
  return validation.value ? validation.value.errors.length + validation.value.warnings.length : 0
}

const dagNodes = computed(() =>
  nodes.value.map((node) => ({
    key: node.node_key,
    label: node.name || node.node_key,
    type: node.node_type,
    enabled: node.enabled,
  })),
)

const dagEdges = computed(() =>
  edges.value.map((edge) => ({
    source: nodeKey(edge.source),
    target: nodeKey(edge.target),
    label: edge.source_port && edge.source_port !== 'out' ? edge.source_port : '',
  })),
)

const selectedNode = computed(() => nodes.value.find((node) => node.node_key === selectedKey.value) || null)

function nodeKey(value) {
  const hit = nodes.value.find((node) => String(node.id) === String(value))
  return hit ? hit.node_key : String(value ?? '')
}

function nodeLabel(value) {
  const hit = nodes.value.find((node) => String(node.id) === String(value))
  return hit ? `${hit.name}（${hit.node_key}）` : `节点 #${value}`
}

function pipelineId() {
  return props.pipeline?.id
}

async function loadNodes() {
  const id = pipelineId()
  if (!api || !id) return
  nodesLoading.value = true
  try {
    const data = await api.list(`pipelines/${id}/nodes/`, { page: 1, page_size: 200 })
    nodes.value = data.items || []
    if (selectedKey.value && !nodes.value.some((node) => node.node_key === selectedKey.value)) {
      selectedKey.value = ''
    }
  } catch (e) {
    error.value = e?.message || '节点加载失败'
    nodes.value = []
  } finally {
    nodesLoading.value = false
  }
}

async function loadEdges() {
  const id = pipelineId()
  if (!api || !id) return
  edgesLoading.value = true
  try {
    const data = await api.list(`pipelines/${id}/edges/`, { page: 1, page_size: 200 })
    edges.value = data.items || []
  } catch (e) {
    error.value = e?.message || '连线加载失败'
    edges.value = []
  } finally {
    edgesLoading.value = false
  }
}

async function loadMappings() {
  const id = pipelineId()
  if (!api || !id) return
  mappingsLoading.value = true
  try {
    const data = await api.list(`pipelines/${id}/mappings/`, { page: 1, page_size: 200 })
    mappings.value = data.items || []
  } catch (e) {
    error.value = e?.message || '字段映射加载失败'
    mappings.value = []
  } finally {
    mappingsLoading.value = false
  }
}

async function loadAll() {
  if (!api || !pipelineId()) {
    error.value = '缺少管道上下文，无法加载编排数据'
    return
  }
  loading.value = true
  error.value = ''
  await Promise.all([loadNodes(), loadEdges(), loadMappings()])
  loading.value = false
}

function openNodeCreate() {
  nodeForm.value = emptyNode()
  nodeForm.value.node_key = `node_${nodes.value.length + 1}`
  nodeForm.value.name = `节点 ${nodes.value.length + 1}`
  nodeFormError.value = ''
  nodeModalOpen.value = true
}

function openNodeEdit(node) {
  nodeForm.value = {
    id: node.id,
    node_key: node.node_key,
    name: node.name,
    node_type: node.node_type || 'transform',
    enabled: node.enabled !== false,
    description: node.description || '',
    configText: JSON.stringify(node.config || {}, null, 2),
  }
  nodeFormError.value = ''
  nodeModalOpen.value = true
}

function parseConfig() {
  const text = String(nodeForm.value.configText || '').trim()
  if (!text) return {}
  const parsed = JSON.parse(text)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('节点配置必须是 JSON 对象')
  }
  return parsed
}

async function saveNode() {
  const form = nodeForm.value
  if (!form.node_key.trim()) {
    nodeFormError.value = '节点标识不能为空'
    return
  }
  if (!form.name.trim()) {
    nodeFormError.value = '节点名称不能为空'
    return
  }
  let config
  try {
    config = parseConfig()
  } catch (e) {
    nodeFormError.value = e?.message || 'JSON 解析失败'
    return
  }
  nodeSaving.value = true
  nodeFormError.value = ''
  try {
    const payload = {
      node_key: form.node_key.trim(),
      name: form.name.trim(),
      node_type: form.node_type,
      config,
      enabled: form.enabled,
      description: form.description || '',
    }
    if (form.id) {
      await api.update(`nodes/${form.id}/update/`, payload)
      app.toastMsg('节点已更新', 'success')
    } else {
      await api.create(`pipelines/${pipelineId()}/nodes/`, payload)
      app.toastMsg('节点已创建', 'success')
    }
    nodeModalOpen.value = false
    await Promise.all([loadNodes(), loadEdges()])
    emit('changed')
  } catch (e) {
    nodeFormError.value = e?.message || '保存节点失败'
    app.toastMsg(nodeFormError.value, 'error')
  } finally {
    nodeSaving.value = false
  }
}

async function toggleNode(node) {
  try {
    await api.update(`nodes/${node.id}/update/`, { enabled: !node.enabled })
    app.toastMsg(node.enabled ? '节点已停用' : '节点已启用', 'success')
    await loadNodes()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '更新节点失败', 'error')
  }
}

async function removeNode(node) {
  try {
    await api.action(`nodes/${node.id}/delete/`)
    app.toastMsg('节点已删除', 'success')
    await Promise.all([loadNodes(), loadEdges(), loadMappings()])
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '删除节点失败', 'error')
  }
}

async function createEdge() {
  if (!edgeForm.value.source || !edgeForm.value.target) {
    app.toastMsg('请选择上游与下游节点', 'error')
    return
  }
  if (edgeForm.value.source === edgeForm.value.target) {
    app.toastMsg('上下游不能是同一个节点', 'error')
    return
  }
  edgeSaving.value = true
  try {
    await api.create(`pipelines/${pipelineId()}/edges/`, {
      source: Number(edgeForm.value.source),
      target: Number(edgeForm.value.target),
      source_port: edgeForm.value.source_port || 'out',
      target_port: edgeForm.value.target_port || 'in',
    })
    app.toastMsg('连线已添加', 'success')
    edgeForm.value = { source: '', target: '', source_port: 'out', target_port: 'in' }
    await loadEdges()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '添加连线失败', 'error')
  } finally {
    edgeSaving.value = false
  }
}

async function removeEdge(edge) {
  try {
    await api.action(`edges/${edge.id}/delete/`)
    app.toastMsg('连线已删除', 'success')
    await loadEdges()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '删除连线失败', 'error')
  }
}

async function createMapping() {
  if (!mappingForm.value.target_field.trim()) {
    app.toastMsg('目标字段不能为空', 'error')
    return
  }
  mappingSaving.value = true
  try {
    let defaultValue = null
    const raw = mappingForm.value.default_value.trim()
    if (raw) {
      try {
        defaultValue = JSON.parse(raw)
      } catch (e) {
        defaultValue = raw
      }
    }
    await api.create(`pipelines/${pipelineId()}/mappings/`, {
      node: mappingForm.value.node ? Number(mappingForm.value.node) : null,
      source_field: mappingForm.value.source_field.trim(),
      target_field: mappingForm.value.target_field.trim(),
      cast: mappingForm.value.cast,
      expression: mappingForm.value.expression,
      default_value: defaultValue,
      required: mappingForm.value.required,
    })
    app.toastMsg('字段映射已添加', 'success')
    mappingForm.value = { node: '', source_field: '', target_field: '', cast: '', expression: '', default_value: '', required: false }
    await loadMappings()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '添加映射失败', 'error')
  } finally {
    mappingSaving.value = false
  }
}

async function removeMapping(mapping) {
  try {
    await api.action(`mappings/${mapping.id}/delete/`)
    app.toastMsg('字段映射已删除', 'success')
    await loadMappings()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '删除映射失败', 'error')
  }
}

function toTextList(value) {
  if (!value) return []
  if (Array.isArray(value)) return value.map((item) => (typeof item === 'string' ? item : String(item?.message ?? item?.detail ?? JSON.stringify(item))))
  if (typeof value === 'string') return [value]
  if (typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => `${key}：${typeof item === 'string' ? item : JSON.stringify(item)}`)
  }
  return [String(value)]
}

async function validateDag() {
  const id = pipelineId()
  if (!api || !id) return
  validating.value = true
  try {
    const data = await api.get(`pipelines/${id}/validate/`)
    const report = data || {}
    validation.value = {
      ok: Boolean(report.ok ?? report.valid ?? (toTextList(report.errors).length === 0)),
      errors: toTextList(report.errors || report.error),
      warnings: toTextList(report.warnings || report.warning),
      order: Array.isArray(report.order) ? report.order : [],
    }
    if (validation.value.ok) {
      app.toastMsg('DAG 校验通过', 'success')
    } else {
      app.toastMsg(`DAG 校验未通过：${validation.value.errors[0] || '请检查节点与连线'}`, 'error')
    }
  } catch (e) {
    validation.value = { ok: false, errors: [e?.message || '校验接口不可用'], warnings: [], order: [] }
    app.toastMsg(validation.value.errors[0], 'error')
  } finally {
    validating.value = false
  }
}

// 节点/连线变化后，拓扑视图即时复用同一份数据，无需额外请求
watch(() => props.pipeline?.id, () => {
  validation.value = null
  selectedKey.value = ''
  loadAll()
})

onMounted(() => loadAll())
</script>