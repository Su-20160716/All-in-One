<template>
  <div class="space-y-4">
    <!-- 筛选 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-end gap-2">
        <label class="flex min-w-[180px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
          关键词
          <input
            v-model="q"
            class="input"
            placeholder="搜索表单名称 / 编码"
            @keyup.enter="applyFilters"
          />
        </label>
        <label class="flex w-44 flex-col gap-1 text-[11px] text-ink-500">
          表单
          <select v-model="formId" class="input" @change="applyFilters">
            <option value="">全部表单</option>
            <option v-for="form in forms" :key="form.id" :value="form.id">{{ form.name }}</option>
          </select>
        </label>
        <label class="flex w-32 flex-col gap-1 text-[11px] text-ink-500">
          状态
          <select v-model="status" class="input" @change="applyFilters">
            <option value="">有效提交</option>
            <option v-for="s in STATUS_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
            <option value="draft">草稿</option>
          </select>
        </label>
        <label class="flex w-32 flex-col gap-1 text-[11px] text-ink-500">
          来源
          <select v-model="source" class="input" @change="applyFilters">
            <option value="">全部来源</option>
            <option v-for="s in SOURCE_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </label>
        <label class="flex w-36 flex-col gap-1 text-[11px] text-ink-500">
          开始日期
          <input v-model="dateFrom" class="input" type="date" />
        </label>
        <label class="flex w-36 flex-col gap-1 text-[11px] text-ink-500">
          结束日期
          <input v-model="dateTo" class="input" type="date" />
        </label>
        <button class="btn-primary" type="button" @click="applyFilters">查询</button>
        <button class="btn-ghost" type="button" @click="resetFilters">重置</button>
        <button class="btn-outline" type="button" :disabled="exporting || !formId" @click="exportCsv">
          {{ exporting ? '导出中…' : '导出 CSV' }}
        </button>
      </div>
      <p class="mt-2 text-[11px] text-ink-400">
        导出使用后端表单导出端点，按当前状态 / 来源过滤；未选择表单时导出按钮不可用。
      </p>
    </div>

    <!-- 列表 -->
    <div class="card overflow-hidden">
      <div v-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="error" class="px-4 py-4">
        <div class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ error }}</span>
          <button class="shrink-0 font-medium" type="button" @click="load()">重试</button>
        </div>
      </div>
      <div v-else-if="unavailable" class="px-4 py-10 text-center text-[12px] text-ink-400">
        <p>提交记录接口暂不可用，已降级为空列表</p>
        <button class="btn-ghost mt-3" type="button" @click="load()">重试</button>
      </div>
      <div v-else-if="!items.length" class="py-12 text-center text-[12px] text-ink-400">
        没有符合筛选条件的提交记录
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[980px] text-left">
          <thead class="border-b border-ink-100 bg-ink-50/60">
            <tr>
              <th class="th w-16">ID</th>
              <th class="th">表单</th>
              <th class="th">提交人</th>
              <th class="th">状态</th>
              <th class="th">版本</th>
              <th class="th">得分</th>
              <th class="th">耗时</th>
              <th class="th">来源</th>
              <th class="th">提交时间</th>
              <th class="th">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in items" :key="row.id" class="hover:bg-ink-50/60">
              <td class="td">#{{ row.id }}</td>
              <td class="td">
                <span class="block max-w-[200px] truncate">{{ row.form_name || '未命名表单' }}</span>
                <span class="text-[11px] text-ink-400">{{ row.answers_count || 0 }} 个答题</span>
              </td>
              <td class="td">{{ personName(row.submitted_by) }}</td>
              <td class="td">
                <span class="tag" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
              </td>
              <td class="td">v{{ row.version_no || 0 }}</td>
              <td class="td">{{ scoreText(row) }}</td>
              <td class="td">{{ durationText(row.duration_seconds) }}</td>
              <td class="td">{{ sourceLabel(row.source) }}</td>
              <td class="td">{{ formatDate(row.submitted_at, true) }}</td>
              <td class="td">
                <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="openDetail(row)">
                  详情
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="items.length" class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
        <span>共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页</span>
        <div class="flex items-center gap-2">
          <select
            class="input !w-auto !py-1 !text-[11px]"
            :value="pageSize"
            aria-label="每页条数"
            @change="changePageSize(Number($event.target.value))"
          >
            <option :value="10">10 条/页</option>
            <option :value="20">20 条/页</option>
            <option :value="50">50 条/页</option>
          </select>
          <button class="btn-ghost" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <button class="btn-ghost" type="button" :disabled="page >= pages" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <div v-if="detailOpen" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="closeDetail"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[600px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="tag">#{{ detailId }}</span>
              <span v-if="detail" class="tag" :class="statusClass(detail.status)">{{ statusLabel(detail.status) }}</span>
              <span v-if="detail" class="tag">v{{ detail.version_no || 0 }}</span>
              <span v-if="detail" class="tag">{{ sourceLabel(detail.source) }}</span>
            </div>
            <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">
              {{ detail?.form_name || '提交详情' }}
            </h3>
          </div>
          <button class="shrink-0 text-ink-400 hover:text-ink-600" aria-label="关闭详情" type="button" @click="closeDetail">
            ✕
          </button>
        </div>

        <div class="flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <div v-if="detailLoading" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
          <div v-else-if="detailError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <div class="flex items-center gap-2">
              <span class="min-w-0 flex-1">{{ detailError }}</span>
              <button class="shrink-0 font-medium" type="button" @click="loadDetail">重试</button>
            </div>
          </div>
          <template v-else-if="detail">
            <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
              <div class="text-ink-400">提交人</div>
              <div class="text-ink-700">{{ personName(detail.submitted_by) }}</div>
              <div class="text-ink-400">提交时间</div>
              <div class="text-ink-700">{{ formatDate(detail.submitted_at, true) }}</div>
              <div class="text-ink-400">得分</div>
              <div class="text-ink-700">{{ scoreText(detail) }}</div>
              <div class="text-ink-400">填写耗时</div>
              <div class="text-ink-700">{{ durationText(detail.duration_seconds) }}</div>
              <div class="text-ink-400">来源</div>
              <div class="text-ink-700">{{ sourceLabel(detail.source) }}</div>
              <div class="text-ink-400">IP / UA</div>
              <div class="break-all text-ink-700">{{ detail.ip || '—' }} · {{ detail.user_agent || '—' }}</div>
              <div class="text-ink-400">审核时间</div>
              <div class="text-ink-700">{{ detail.reviewed_at ? formatDate(detail.reviewed_at, true) : '尚未审核' }}</div>
              <template v-if="detail.review_note">
                <div class="text-ink-400">审核意见</div>
                <div class="break-all text-ink-700">{{ detail.review_note }}</div>
              </template>
            </div>

            <div>
              <div class="mb-1.5 flex items-center justify-between">
                <span class="text-[13px] font-medium text-ink-700">字段填报值</span>
                <span class="tag">{{ detail.values?.length || 0 }} 项</span>
              </div>
              <div v-if="!detail.values?.length" class="rounded-control bg-ink-50 px-3 py-3 text-[12px] text-ink-400">
                该提交没有字段值（可能为草稿或结构已变更）
              </div>
              <div v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
                <div v-for="value in detail.values" :key="value.id" class="px-3 py-2">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="text-[12px] font-medium text-ink-700">{{ fieldLabel(value.field_key) }}</span>
                    <span class="tag">{{ value.field_key }}</span>
                    <span class="tag">{{ fieldTypeLabel(value.field_type) }}</span>
                    <span v-if="value.score !== null && value.score !== undefined" class="tag bg-brand-50 text-brand-700">
                      得分 {{ value.score }}
                    </span>
                  </div>
                  <p class="mt-1 whitespace-pre-wrap break-all text-[12px] text-ink-600">{{ valueText(value) }}</p>
                </div>
              </div>
            </div>

            <div v-if="detail.review_tasks?.length">
              <div class="mb-1.5 text-[13px] font-medium text-ink-700">审核任务</div>
              <div class="space-y-1.5">
                <div
                  v-for="task in detail.review_tasks"
                  :key="task.id"
                  class="flex flex-wrap items-center gap-2 rounded-control border border-ink-100 px-3 py-2 text-[12px]"
                >
                  <span class="tag" :class="taskStatusClass(task.status)">{{ taskStatusLabel(task.status) }}</span>
                  <span class="text-ink-600">{{ task.reviewer?.name || task.reviewer?.username || '待指派' }}</span>
                  <span class="text-ink-400">优先级 {{ task.priority }}</span>
                  <span class="text-ink-400">{{ formatDate(task.due_at, true) }}</span>
                </div>
              </div>
            </div>

            <div v-if="detail.can_review" class="flex flex-wrap gap-2 border-t border-ink-100 pt-3">
              <button
                class="btn-primary"
                type="button"
                :disabled="detail.status !== 'submitted'"
                @click="openReview('approve')"
              >
                审核通过
              </button>
              <button
                class="btn-danger"
                type="button"
                :disabled="detail.status !== 'submitted'"
                @click="openReview('reject')"
              >
                驳回
              </button>
              <span v-if="detail.status !== 'submitted'" class="self-center text-[11px] text-ink-400">
                仅“已提交”状态可以审核
              </span>
            </div>
          </template>
        </div>
      </aside>
    </div>

    <!-- 审核弹窗 -->
    <Modal v-model="reviewOpen" :title="reviewMode === 'approve' ? '审核通过' : '驳回提交'" width="460px">
      <div class="space-y-3">
        <div v-if="reviewError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ reviewError }}
        </div>
        <p class="text-[12px] text-ink-500">
          {{ reviewMode === 'approve' ? '通过后提交状态变为已审核，并触发审核完成 Webhook。' : '驳回必须填写原因，提交人会看到审核意见。' }}
        </p>
        <label class="flex flex-col gap-1 text-[11px] text-ink-500">
          审核意见{{ reviewMode === 'reject' ? '（必填）' : '（可选）' }}
          <textarea
            v-model="reviewNote"
            class="input min-h-[88px]"
            maxlength="1000"
            placeholder="填写审核结论或驳回原因"
          />
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" type="button" @click="reviewOpen = false">取消</button>
          <button class="btn-primary" type="button" :disabled="reviewSaving" @click="submitReview">
            {{ reviewSaving ? '提交中…' : '确认' }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useAppStore } from '../../stores/app'
import { formstudioApi, unwrap } from '../../api/platform'
import { formatDate, usePagination } from '../../composables/useDomainResource'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  forms: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed'])

const app = useAppStore()
const { page, pageSize, total, pages, setPage, setPageSize } = usePagination(20)

const STATUS_OPTIONS = [
  { value: 'submitted', label: '已提交' },
  { value: 'reviewed', label: '已审核' },
  { value: 'rejected', label: '已驳回' },
]
const SOURCE_OPTIONS = [
  { value: 'web', label: '网页' },
  { value: 'share', label: '分享链接' },
  { value: 'api', label: '接口' },
  { value: 'embed', label: '嵌入' },
  { value: 'import', label: '导入' },
]
const STATUS_LABELS = {
  draft: '草稿',
  submitted: '已提交',
  reviewed: '已审核',
  rejected: '已驳回',
}
const SOURCE_LABELS = {
  web: '网页',
  share: '分享链接',
  api: '接口',
  embed: '嵌入',
  import: '导入',
}
const TASK_STATUS_LABELS = {
  pending: '待处理',
  approved: '已通过',
  rejected: '已驳回',
  skipped: '已跳过',
}
const FIELD_TYPE_LABELS = {
  text: '单行文本',
  textarea: '多行文本',
  number: '数字',
  select: '单选',
  multiselect: '多选',
  date: '日期',
  datetime: '日期时间',
  boolean: '开关',
  file: '文件',
  rating: '评分',
  email: '邮箱',
  phone: '手机号',
  url: '链接',
  signature: '签名',
  matrix: '矩阵',
}

const q = ref('')
const formId = ref('')
const status = ref('')
const source = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const items = ref([])
const loading = ref(false)
const error = ref('')
const unavailable = ref(false)
let seq = 0

function statusLabel(value) {
  return STATUS_LABELS[value] || value || '—'
}
function statusClass(value) {
  if (value === 'reviewed') return 'bg-emerald-50 text-emerald-600'
  if (value === 'submitted') return 'bg-brand-50 text-brand-700'
  if (value === 'rejected') return 'bg-rose-50 text-rose-600'
  return 'bg-ink-100 text-ink-600'
}
function sourceLabel(value) {
  return SOURCE_LABELS[value] || value || '—'
}
function taskStatusLabel(value) {
  return TASK_STATUS_LABELS[value] || value || '—'
}
function taskStatusClass(value) {
  if (value === 'approved') return 'bg-emerald-50 text-emerald-600'
  if (value === 'rejected') return 'bg-rose-50 text-rose-600'
  if (value === 'pending') return 'bg-amber-50 text-amber-600'
  return 'bg-ink-100 text-ink-600'
}
function fieldTypeLabel(value) {
  return FIELD_TYPE_LABELS[value] || value || '—'
}
function personName(user) {
  if (!user) return '匿名'
  return user.name || user.username || '—'
}
function scoreText(row) {
  if (row?.score === null || row?.score === undefined) return '—'
  const max = row?.max_score
  return max === null || max === undefined ? String(row.score) : `${row.score} / ${max}`
}
function durationText(seconds) {
  const n = Number(seconds)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n < 60) return `${Math.round(n)} 秒`
  const minutes = Math.floor(n / 60)
  const rest = Math.round(n % 60)
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
}

function params() {
  const out = { page: page.value, page_size: pageSize.value }
  if (q.value.trim()) out.q = q.value.trim()
  if (formId.value) out.form_id = Number(formId.value)
  if (status.value) out.status = status.value
  if (source.value) out.source = source.value
  if (dateFrom.value) out.date_from = dateFrom.value
  if (dateTo.value) out.date_to = `${dateTo.value}T23:59:59`
  return out
}

async function load(reset = false) {
  if (reset) setPage(1)
  const current = ++seq
  loading.value = true
  error.value = ''
  unavailable.value = false
  try {
    const data = await formstudioApi.list('submissions/', params())
    if (current !== seq) return
    items.value = data.items || []
    total.value = data.count || 0
  } catch (e) {
    if (current !== seq) return
    items.value = []
    total.value = 0
    const down = e?.status === 404 || e?.status === 405
    unavailable.value = down
    error.value = down ? '' : e?.message || '提交记录加载失败'
  } finally {
    if (current === seq) loading.value = false
  }
}
function applyFilters() {
  setPage(1)
  load()
}
function changePageSize(size) {
  setPageSize(size)
  load()
}
function goPage(next) {
  setPage(next)
  load()
}
function resetFilters() {
  q.value = ''
  formId.value = ''
  status.value = ''
  source.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  setPage(1)
  load()
}

// ---------------------------------------------------------------------------
// 详情与字段标签
// ---------------------------------------------------------------------------
const detailOpen = ref(false)
const detailId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const schemaCache = ref({})

async function ensureSchema(formIdValue) {
  if (!formIdValue) return null
  if (schemaCache.value[formIdValue]) return schemaCache.value[formIdValue]
  try {
    const data = await formstudioApi.get(`forms/${formIdValue}/schema/`)
    const schema = data?.schema || { fields: [] }
    schemaCache.value = { ...schemaCache.value, [formIdValue]: schema }
    return schema
  } catch (e) {
    schemaCache.value = { ...schemaCache.value, [formIdValue]: { fields: [] } }
    return null
  }
}
function currentSchema() {
  if (!detail.value?.form_id) return null
  return schemaCache.value[detail.value.form_id] || null
}
function fieldLabel(key) {
  const schema = currentSchema()
  const field = (schema?.fields || []).find((f) => f.key === key)
  return field?.label || key
}
function valueText(value) {
  const raw = value?.raw
  if (raw === null || raw === undefined || raw === '') return '—'
  if (Array.isArray(raw)) return raw.length ? raw.join('、') : '—'
  if (typeof raw === 'boolean') return raw ? '是' : '否'
  if (typeof raw === 'object') {
    try {
      return JSON.stringify(raw)
    } catch (e) {
      return String(raw)
    }
  }
  return String(raw)
}

async function openDetail(row) {
  detailId.value = row.id
  detail.value = null
  detailError.value = ''
  detailOpen.value = true
  await loadDetail()
}
async function loadDetail() {
  if (!detailId.value) return
  detailLoading.value = true
  detailError.value = ''
  try {
    const data = await formstudioApi.get(`submissions/${detailId.value}/`)
    detail.value = data || null
    if (data?.form_id) await ensureSchema(data.form_id)
  } catch (e) {
    detailError.value = e?.message || '详情加载失败'
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}
function closeDetail() {
  detailOpen.value = false
  detailId.value = null
  detail.value = null
  detailError.value = ''
}

// ---------------------------------------------------------------------------
// 审核
// ---------------------------------------------------------------------------
const reviewOpen = ref(false)
const reviewMode = ref('approve')
const reviewNote = ref('')
const reviewSaving = ref(false)
const reviewError = ref('')

function openReview(mode) {
  reviewMode.value = mode
  reviewNote.value = ''
  reviewError.value = ''
  reviewOpen.value = true
}
async function submitReview() {
  reviewError.value = ''
  if (reviewMode.value === 'reject' && !reviewNote.value.trim()) {
    reviewError.value = '驳回必须填写原因'
    return
  }
  reviewSaving.value = true
  try {
    const action = reviewMode.value === 'approve' ? 'approve' : 'reject'
    await formstudioApi.action(`submissions/${detailId.value}/${action}/`, {
      conclusion: reviewNote.value.trim(),
    })
    app.toastMsg(reviewMode.value === 'approve' ? '已审核通过' : '已驳回', 'success')
    reviewOpen.value = false
    await loadDetail()
    await load()
    emit('changed')
  } catch (e) {
    reviewError.value = e?.message || '审核失败'
    app.toastMsg(reviewError.value, 'error')
  } finally {
    reviewSaving.value = false
  }
}

// ---------------------------------------------------------------------------
// 导出 CSV
// ---------------------------------------------------------------------------
const exporting = ref(false)
async function exportCsv() {
  if (!formId.value) {
    app.toastMsg('请先选择要导出的表单', 'info')
    return
  }
  exporting.value = true
  try {
    const requestParams = {}
    if (status.value) requestParams.status = status.value
    if (source.value) requestParams.source = source.value
    const data = await unwrap(
      formstudioApi.raw({
        url: `/formstudio/forms/${formId.value}/export/`,
        method: 'get',
        params: requestParams,
      })
    )
    const content = data?.content
    if (typeof content !== 'string' || !content) {
      throw new Error('导出接口未返回 CSV 内容')
    }
    const blob = new Blob([content], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = data?.filename || `form-${formId.value}-submissions.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    app.toastMsg(`已导出 ${data?.row_count ?? 0} 行`, 'success')
  } catch (e) {
    app.toastMsg(e?.message || '导出失败', 'error')
  } finally {
    exporting.value = false
  }
}

// 暴露给父级在切页签时手动刷新
onMounted(() => {
  load()
})

defineExpose({ load })
</script>