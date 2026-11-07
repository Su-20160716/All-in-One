<template>
  <div class="space-y-3">
    <!-- 工具栏 -->
    <div class="card p-3">
      <form class="flex flex-wrap items-center gap-2" @submit.prevent="applySearch">
        <input v-model="q" class="input w-[250px]" placeholder="搜索编码 / 名称 / 描述" />
        <select v-model="status" class="input w-[130px]">
          <option value="">全部状态</option>
          <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <button class="btn-primary" type="submit">查询</button>
        <button class="btn-ghost" type="button" @click="resetAndReload">重置</button>
        <span class="mx-1 hidden h-4 w-px bg-ink-200 sm:block"></span>
        <button class="btn-primary" type="button" @click="openCreate">新建管道</button>
        <button class="btn-outline" type="button" @click="openImport">导入 JSON</button>
        <button class="btn-ghost" type="button" :disabled="loading" @click="refresh()">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <span class="ml-auto text-[11px] text-ink-400">共 {{ total }} 条 · 第 {{ page }}/{{ pages }} 页</span>
      </form>
    </div>

    <!-- 列表 -->
    <div class="card p-3">
      <div v-if="error" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="shrink-0 font-medium" @click="refresh()">重试</button>
      </div>
      <div v-else-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">管道加载中…</div>
      <div v-else-if="!items.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
        没有符合条件的管道，尝试调整关键词或直接新建
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[980px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">编码 / 名称</th>
              <th class="th">状态</th>
              <th class="th text-right">节点</th>
              <th class="th text-right">连线</th>
              <th class="th">并发</th>
              <th class="th text-right">重试 / 超时</th>
              <th class="th">最近运行</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in items" :key="row.id" class="transition-colors hover:bg-ink-50/60">
              <td class="td">
                <button class="max-w-[260px] truncate text-left font-medium text-ink-800 hover:text-brand-600" @click="openEditor(row)">
                  {{ row.name || '未命名管道' }}
                </button>
                <div class="mt-0.5 flex items-center gap-1.5">
                  <span class="font-mono text-[11px] text-ink-400">{{ row.code }}</span>
                  <span v-if="row.version" class="text-[11px] text-ink-300">· v{{ row.version }}</span>
                </div>
              </td>
              <td class="td">
                <span class="tag" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
              </td>
              <td class="td text-right">{{ formatNumber(row.node_count) }}</td>
              <td class="td text-right">{{ formatNumber(row.edge_count) }}</td>
              <td class="td text-[12px] text-ink-500">{{ concurrencyLabel(row.concurrency) }}</td>
              <td class="td text-right text-[12px] text-ink-500">
                {{ row.max_retries ?? 0 }} 次 / {{ row.timeout_seconds ?? 120 }}s
              </td>
              <td class="td">
                <div class="text-[12px] text-ink-600">{{ formatDate(row.last_run_at, true) }}</div>
                <span v-if="row.last_run_status" class="tag mt-0.5" :class="runStatusClass(row.last_run_status)">
                  {{ runStatusLabel(row.last_run_status) }}
                </span>
              </td>
              <td class="td text-right">
                <div class="flex justify-end gap-1">
                  <button class="btn-ghost py-0.5 text-[11px]" @click="openEditor(row)">编排</button>
                  <button class="btn-ghost py-0.5 text-[11px]" @click="openActions(row)">更多</button>
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

    <!-- 新建 / 编辑 -->
    <Modal
      :show="formOpen"
      :title="form.id ? `编辑管道 ${form.code}` : '新建管道'"
      width="700px"
      @close="formOpen = false"
    >
      <form class="space-y-3" @submit.prevent="savePipeline">
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="text-[12px] text-ink-500">
            编码
            <input v-model="form.code" class="input mt-1 font-mono" placeholder="orders_daily" />
          </label>
          <label class="text-[12px] text-ink-500">
            名称
            <input v-model="form.name" class="input mt-1" placeholder="订单日增量同步" />
          </label>
        </div>
        <label class="block text-[12px] text-ink-500">
          描述
          <textarea v-model="form.description" rows="2" class="input mt-1" placeholder="说明数据来源、口径与产出"></textarea>
        </label>
        <div class="grid gap-2 sm:grid-cols-3">
          <label class="text-[12px] text-ink-500">
            并发策略
            <select v-model="form.concurrency" class="input mt-1">
              <option v-for="item in CONCURRENCY_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="text-[12px] text-ink-500">
            单节点重试上限
            <input v-model.number="form.max_retries" type="number" min="0" max="5" class="input mt-1" />
          </label>
          <label class="text-[12px] text-ink-500">
            运行超时（秒）
            <input v-model.number="form.timeout_seconds" type="number" min="1" class="input mt-1" />
          </label>
        </div>
        <div class="grid gap-2 sm:grid-cols-3">
          <label class="text-[12px] text-ink-500">
            单次行数上限
            <input v-model.number="form.row_limit" type="number" min="1" class="input mt-1" />
          </label>
          <label class="text-[12px] text-ink-500">
            增量水位字段
            <input v-model="form.watermark_field" class="input mt-1" placeholder="updated_at" />
          </label>
          <label class="text-[12px] text-ink-500">
            负责人
            <input v-model="form.assignee" class="input mt-1" placeholder="选填" />
          </label>
        </div>
        <label class="block text-[12px] text-ink-500">
          标签（逗号分隔）
          <input v-model="form.tagsText" class="input mt-1" placeholder="核心链路, 每日" />
        </label>
        <div v-if="formError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ formError }}</div>
        <div class="flex items-center justify-between gap-2">
          <span class="text-[11px] text-ink-400">保存后可在「编排」里配置节点与连线</span>
          <div class="flex gap-2">
            <button type="button" class="btn-ghost" @click="formOpen = false">取消</button>
            <button type="submit" class="btn-primary" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
          </div>
        </div>
      </form>
    </Modal>

    <!-- 操作面板 -->
    <Modal :show="!!actionRow" :title="actionRow ? `管道操作 · ${actionRow.name}` : '管道操作'" width="560px" @close="actionRow = null">
      <div v-if="actionRow" class="space-y-3">
        <div class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-500">
          编码 <span class="font-mono text-ink-700">{{ actionRow.code }}</span> ·
          状态 <span class="text-ink-700">{{ statusLabel(actionRow.status) }}</span> ·
          节点 {{ formatNumber(actionRow.node_count) }} 个
        </div>
        <div class="grid gap-2 sm:grid-cols-2">
          <button class="btn-outline justify-start" @click="openEditor(actionRow)">打开 DAG 编排</button>
          <button class="btn-outline justify-start" :disabled="busy" @click="validatePipeline(actionRow)">DAG 校验</button>
          <button class="btn-outline justify-start" :disabled="busy" @click="showTopology(actionRow)">拓扑预览</button>
          <button class="btn-outline justify-start" :disabled="busy || actionRow.status === 'published'" @click="publishPipeline(actionRow)">
            发布
          </button>
          <button class="btn-outline justify-start" :disabled="busy || actionRow.status !== 'published'" @click="pausePipeline(actionRow)">
            暂停
          </button>
          <button class="btn-outline justify-start" :disabled="busy || actionRow.status === 'archived'" @click="archivePipeline(actionRow)">
            归档
          </button>
          <button class="btn-outline justify-start" :disabled="busy" @click="clonePipeline(actionRow)">克隆</button>
          <button class="btn-outline justify-start" :disabled="busy" @click="exportPipeline(actionRow)">导出 JSON</button>
          <button class="btn-outline justify-start" :disabled="busy" @click="openEdit(actionRow)">编辑基础信息</button>
          <button class="btn-danger justify-start" :disabled="busy" @click="askDelete(actionRow)">删除管道</button>
        </div>
        <p class="text-[11px] text-ink-400">发布、暂停、归档都会写回后端状态，并同步影响调度与运行入口。</p>
      </div>
    </Modal>

    <!-- 校验结果 -->
    <Modal :show="validateOpen" title="DAG 校验结果" width="640px" @close="validateOpen = false">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag" :class="validation.ok ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
            {{ validation.ok ? '校验通过' : '校验未通过' }}
          </span>
          <span class="text-[11px] text-ink-400">{{ validation.pipelineCode }}</span>
        </div>
        <div>
          <div class="mb-1 text-[12px] font-medium text-rose-600">错误（{{ validation.errors.length }}）</div>
          <ul v-if="validation.errors.length" class="space-y-1 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <li v-for="(item, index) in validation.errors" :key="`ve-${index}`" class="break-all">· {{ item }}</li>
          </ul>
          <p v-else class="text-[12px] text-ink-400">没有阻塞性错误</p>
        </div>
        <div>
          <div class="mb-1 text-[12px] font-medium text-amber-600">警告（{{ validation.warnings.length }}）</div>
          <ul v-if="validation.warnings.length" class="space-y-1 rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
            <li v-for="(item, index) in validation.warnings" :key="`vw-${index}`" class="break-all">· {{ item }}</li>
          </ul>
          <p v-else class="text-[12px] text-ink-400">没有告警项</p>
        </div>
        <div v-if="validation.order.length" class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
          拓扑顺序：{{ validation.order.join(' → ') }}
        </div>
      </div>
    </Modal>

    <!-- 拓扑预览 -->
    <Modal :show="topologyOpen" title="DAG 拓扑预览" width="980px" @close="topologyOpen = false">
      <div class="space-y-2">
        <div v-if="topologyLoading" class="py-12 text-center text-[12px] text-ink-400">拓扑加载中…</div>
        <div v-else-if="topologyError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ topologyError }}</div>
        <DagCanvas v-else :nodes="topology.nodes" :edges="topology.edges" empty-text="该管道还没有节点" />
        <div v-if="!topologyLoading && !topologyError" class="flex flex-wrap gap-2 text-[11px] text-ink-400">
          <span v-if="topology.entry?.length">入口：{{ topology.entry.join('、') }}</span>
          <span v-if="topology.exit?.length">出口：{{ topology.exit.join('、') }}</span>
        </div>
      </div>
    </Modal>

    <!-- 导出 -->
    <Modal :show="exportOpen" title="导出管道 JSON" width="760px" @close="exportOpen = false">
      <div class="space-y-2">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag">{{ exportName }}</span>
          <button class="btn-outline py-1 text-[12px]" @click="copyExport">复制 JSON</button>
          <button class="btn-outline py-1 text-[12px]" @click="downloadExport">下载文件</button>
          <span class="text-[11px] text-ink-400">导出包含管道、节点、连线与调度定义</span>
        </div>
        <textarea :value="exportText" rows="16" readonly class="input font-mono text-[11px]"></textarea>
      </div>
    </Modal>

    <!-- 导入 -->
    <Modal :show="importOpen" title="导入管道 JSON" width="760px" @close="importOpen = false">
      <form class="space-y-2" @submit.prevent="submitImport">
        <textarea
          v-model="importText"
          rows="14"
          class="input font-mono text-[11px]"
          placeholder='粘贴导出接口返回的 JSON，例如 {"pipeline": {...}, "nodes": [...], "edges": [...]}'
        ></textarea>
        <div v-if="importError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ importError }}</div>
        <div class="flex items-center justify-between gap-2">
          <span class="text-[11px] text-ink-400">导入会新建管道，编码重复时由后端拒绝</span>
          <div class="flex gap-2">
            <button type="button" class="btn-ghost" @click="importOpen = false">取消</button>
            <button type="submit" class="btn-primary" :disabled="importing">{{ importing ? '导入中…' : '导入' }}</button>
          </div>
        </div>
      </form>
    </Modal>

    <!-- 删除确认 -->
    <Modal :show="deleteOpen" title="删除管道" width="480px" @close="deleteOpen = false">
      <div class="space-y-3">
        <p class="text-[13px] text-ink-700">
          确认删除管道 <span class="font-medium">{{ deleteTarget?.name }}</span>（{{ deleteTarget?.code }}）？
          节点、连线、映射与运行记录会一并清理，无法恢复。
        </p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="deleteOpen = false">取消</button>
          <button class="btn-danger" :disabled="busy" @click="confirmDelete">{{ busy ? '删除中…' : '确认删除' }}</button>
        </div>
      </div>
    </Modal>

    <!-- DAG 编排 -->
    <Modal :show="!!editorRow" :title="editorRow ? `DAG 编排 · ${editorRow.name}` : 'DAG 编排'" width="1180px" @close="closeEditor">
      <PipelineEditor v-if="editorRow" :pipeline="editorRow" @changed="onEditorChanged" />
    </Modal>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { formatDate, formatNumber, useDomainResource } from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import DagCanvas from './DagCanvas.vue'
import PipelineEditor from './PipelineEditor.vue'

const props = defineProps({
  pipelines: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['refresh', 'go'])

const api = apiFor('pipeline')
const app = useAppStore()

const PAGE_SIZES = [10, 20, 50]
const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'published', label: '已发布' },
  { value: 'paused', label: '已暂停' },
  { value: 'archived', label: '已归档' },
]
const CONCURRENCY_OPTIONS = [
  { value: 'parallel', label: '并行' },
  { value: 'serial', label: '串行' },
  { value: 'auto', label: '自动' },
]

const {
  items, loading, error, q, status, page, pageSize, total, pages,
  setPage, setPageSize, refresh, resetFilters,
} = useDomainResource('pipeline', 'pipelines/', { pageSize: 20 })

const busy = ref(false)
const formOpen = ref(false)
const formError = ref('')
const saving = ref(false)
const form = reactive(emptyForm())

const actionRow = ref(null)
const validateOpen = ref(false)
const validation = ref({ ok: true, errors: [], warnings: [], order: [], pipelineCode: '' })
const topologyOpen = ref(false)
const topologyLoading = ref(false)
const topologyError = ref('')
const topology = ref({ nodes: [], edges: [], entry: [], exit: [] })

const exportOpen = ref(false)
const exportData = ref(null)
const exportName = ref('')
const importOpen = ref(false)
const importText = ref('')
const importError = ref('')
const importing = ref(false)

const deleteOpen = ref(false)
const deleteTarget = ref(null)
const editorRow = ref(null)

const exportText = computed(() => (exportData.value ? JSON.stringify(exportData.value, null, 2) : ''))

const STATUS_LABELS = {
  draft: '草稿',
  published: '已发布',
  paused: '已暂停',
  archived: '已归档',
}
const RUN_STATUS_LABELS = {
  success: '成功',
  running: '运行中',
  queued: '排队中',
  failed: '失败',
  cancelled: '已取消',
}

function emptyForm() {
  return {
    id: null,
    code: '',
    name: '',
    description: '',
    concurrency: 'parallel',
    max_retries: 1,
    timeout_seconds: 120,
    row_limit: 5000,
    watermark_field: '',
    assignee: '',
    tagsText: '',
  }
}

function statusLabel(value) {
  return STATUS_LABELS[value] || value || '未知'
}

function statusClass(value) {
  const map = {
    published: 'bg-emerald-50 text-emerald-600',
    draft: 'bg-sky-50 text-sky-600',
    paused: 'bg-amber-50 text-amber-600',
    archived: 'bg-ink-100 text-ink-500',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

function runStatusLabel(value) {
  return RUN_STATUS_LABELS[value] || value || '—'
}

function runStatusClass(value) {
  const map = {
    success: 'bg-emerald-50 text-emerald-600',
    running: 'bg-amber-50 text-amber-600',
    queued: 'bg-sky-50 text-sky-600',
    failed: 'bg-rose-50 text-rose-600',
    cancelled: 'bg-ink-100 text-ink-500',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

function concurrencyLabel(value) {
  const hit = CONCURRENCY_OPTIONS.find((item) => item.value === value)
  return hit ? hit.label : (value || '—')
}

function applySearch() {
  setPage(1)
  refresh()
}

function resetAndReload() {
  resetFilters()
  refresh()
}

function goPage(next) {
  setPage(next)
  refresh()
}

function changePageSize(next) {
  setPageSize(Number(next) || 20)
  refresh()
}

function fillForm(row) {
  form.id = row.id ?? null
  form.code = row.code || ''
  form.name = row.name || ''
  form.description = row.description || ''
  form.concurrency = row.concurrency || 'parallel'
  form.max_retries = Number(row.max_retries ?? 1)
  form.timeout_seconds = Number(row.timeout_seconds ?? 120)
  form.row_limit = Number(row.row_limit ?? 5000)
  form.watermark_field = row.watermark_field || ''
  form.assignee = row.assignee || ''
  form.tagsText = Array.isArray(row.tags) ? row.tags.join(', ') : ''
}

function openCreate() {
  Object.assign(form, emptyForm())
  formError.value = ''
  formOpen.value = true
}

async function openEdit(row) {
  actionRow.value = null
  Object.assign(form, emptyForm())
  fillForm(row)
  formError.value = ''
  formOpen.value = true
  // 列表项可能不带完整字段，详情接口补齐后再次覆盖
  try {
    const detail = await api.get(`pipelines/${row.id}/`)
    if (detail && typeof detail === 'object') {
      fillForm({ ...row, ...(detail.pipeline || detail) })
    }
  } catch (e) {
    formError.value = e?.message || ''
  }
}

function buildPayload() {
  const tags = String(form.tagsText || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    concurrency: form.concurrency,
    max_retries: Number(form.max_retries) || 0,
    timeout_seconds: Number(form.timeout_seconds) || 120,
    row_limit: Number(form.row_limit) || 5000,
    watermark_field: form.watermark_field.trim(),
    assignee: form.assignee.trim(),
    tags,
  }
}

async function savePipeline() {
  if (!form.code.trim() || !form.name.trim()) {
    formError.value = '编码与名称均为必填'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    const payload = buildPayload()
    if (form.id) {
      await api.update(`pipelines/${form.id}/update/`, payload)
      app.toastMsg('管道已更新', 'success')
    } else {
      await api.create('pipelines/', payload)
      app.toastMsg('管道已创建', 'success')
    }
    formOpen.value = false
    await refresh(true)
    emit('refresh')
  } catch (e) {
    formError.value = e?.message || '保存管道失败'
    app.toastMsg(formError.value, 'error')
  } finally {
    saving.value = false
  }
}

function openActions(row) {
  actionRow.value = row
}

async function runAction(path, successText, payload = {}) {
  busy.value = true
  try {
    await api.action(path, payload)
    app.toastMsg(successText, 'success')
    actionRow.value = null
    await refresh(true)
    emit('refresh')
    return true
  } catch (e) {
    app.toastMsg(e?.message || `${successText}失败`, 'error')
    return false
  } finally {
    busy.value = false
  }
}

function publishPipeline(row) {
  return runAction(`pipelines/${row.id}/publish/`, '管道已发布')
}

function pausePipeline(row) {
  return runAction(`pipelines/${row.id}/pause/`, '管道已暂停')
}

function archivePipeline(row) {
  return runAction(`pipelines/${row.id}/archive/`, '管道已归档')
}

function clonePipeline(row) {
  return runAction(`pipelines/${row.id}/clone/`, '管道已克隆')
}

function askDelete(row) {
  actionRow.value = null
  deleteTarget.value = row
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  busy.value = true
  try {
    await api.action(`pipelines/${deleteTarget.value.id}/delete/`)
    app.toastMsg('管道已删除', 'success')
    deleteOpen.value = false
    deleteTarget.value = null
    await refresh(true)
    emit('refresh')
  } catch (e) {
    app.toastMsg(e?.message || '删除管道失败', 'error')
  } finally {
    busy.value = false
  }
}

function toTextList(value) {
  if (!value) return []
  if (Array.isArray(value)) {
    return value.map((item) => (typeof item === 'string' ? item : String(item?.message ?? item?.detail ?? JSON.stringify(item))))
  }
  if (typeof value === 'string') return [value]
  if (typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => `${key}：${typeof item === 'string' ? item : JSON.stringify(item)}`)
  }
  return [String(value)]
}

async function validatePipeline(row) {
  actionRow.value = null
  busy.value = true
  try {
    const report = (await api.get(`pipelines/${row.id}/validate/`)) || {}
    validation.value = {
      ok: Boolean(report.ok ?? report.valid ?? (toTextList(report.errors).length === 0)),
      errors: toTextList(report.errors || report.error),
      warnings: toTextList(report.warnings || report.warning),
      order: Array.isArray(report.order) ? report.order : [],
      pipelineCode: row.code,
    }
    validateOpen.value = true
  } catch (e) {
    validation.value = {
      ok: false,
      errors: [e?.message || '校验接口不可用'],
      warnings: [],
      order: [],
      pipelineCode: row.code,
    }
    validateOpen.value = true
    app.toastMsg(validation.value.errors[0], 'error')
  } finally {
    busy.value = false
  }
}

async function showTopology(row) {
  actionRow.value = null
  topology.value = { nodes: [], edges: [], entry: [], exit: [] }
  topologyError.value = ''
  topologyOpen.value = true
  topologyLoading.value = true
  try {
    const data = (await api.get(`pipelines/${row.id}/topology/`)) || {}
    const nodes = Array.isArray(data.nodes) ? data.nodes : []
    const edges = Array.isArray(data.edges) ? data.edges : []
    topology.value = {
      nodes: nodes.map((node) => ({
        key: node.node_key ?? node.key,
        label: node.name || node.node_key,
        type: node.node_type ?? node.type,
        enabled: node.enabled,
      })),
      edges: edges.map((edge) => ({
        source: edge.source_key ?? edge.source,
        target: edge.target_key ?? edge.target,
      })),
      entry: Array.isArray(data.entry) ? data.entry : (Array.isArray(data.roots) ? data.roots : []),
      exit: Array.isArray(data.exit) ? data.exit : (Array.isArray(data.leaves) ? data.leaves : []),
    }
    if (!topology.value.nodes.length) {
      topologyError.value = ''
    }
  } catch (e) {
    topologyError.value = e?.message || '拓扑接口不可用'
    app.toastMsg(topologyError.value, 'error')
  } finally {
    topologyLoading.value = false
  }
}

async function exportPipeline(row) {
  actionRow.value = null
  busy.value = true
  try {
    const data = (await api.get(`pipelines/${row.id}/export/`)) || {}
    exportData.value = data
    exportName.value = `${row.code || `pipeline-${row.id}`}.json`
    exportOpen.value = true
  } catch (e) {
    app.toastMsg(e?.message || '导出失败', 'error')
  } finally {
    busy.value = false
  }
}

async function copyExport() {
  try {
    await navigator.clipboard.writeText(exportText.value)
    app.toastMsg('JSON 已复制', 'success')
  } catch (e) {
    app.toastMsg('复制失败，请手动选择文本', 'error')
  }
}

function downloadExport() {
  try {
    const blob = new Blob([exportText.value], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = exportName.value || 'pipeline.json'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    app.toastMsg('已开始下载', 'success')
  } catch (e) {
    app.toastMsg(e?.message || '下载失败', 'error')
  }
}

function openImport() {
  importText.value = ''
  importError.value = ''
  importOpen.value = true
}

async function submitImport() {
  const text = importText.value.trim()
  if (!text) {
    importError.value = '请粘贴管道 JSON'
    return
  }
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch (e) {
    importError.value = 'JSON 解析失败：请检查格式'
    return
  }
  importing.value = true
  importError.value = ''
  try {
    await api.create('pipelines/import/', { payload: parsed })
    app.toastMsg('管道已导入', 'success')
    importOpen.value = false
    await refresh(true)
    emit('refresh')
  } catch (e) {
    importError.value = e?.message || '导入失败'
    app.toastMsg(importError.value, 'error')
  } finally {
    importing.value = false
  }
}

function openEditor(row) {
  actionRow.value = null
  editorRow.value = row
}

function closeEditor() {
  editorRow.value = null
}

function onEditorChanged() {
  refresh(true)
  emit('refresh')
}

watch(status, () => {
  setPage(1)
  refresh()
})

watch(() => props.refreshKey, () => refresh(true))
</script>