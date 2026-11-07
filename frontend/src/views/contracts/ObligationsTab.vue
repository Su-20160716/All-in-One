<template>
  <section class="space-y-3">
    <div class="card p-3">
      <div class="flex flex-wrap items-end gap-2">
        <label class="block min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
          <input v-model="search.value" class="input" type="search" placeholder="按义务内容、责任人搜索" />
        </label>
        <label class="block w-[140px]">
          <span class="mb-1 block text-[11px] text-ink-400">状态</span>
          <select v-model="status" class="input" @change="reloadFromFirstPage">
            <option value="">全部状态</option>
            <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="block w-[120px]">
          <span class="mb-1 block text-[11px] text-ink-400">每页</span>
          <select :value="pageSize" class="input" @change="changePageSize">
            <option :value="10">10 条</option>
            <option :value="20">20 条</option>
            <option :value="50">50 条</option>
          </select>
        </label>
        <label class="flex items-center gap-1.5 pb-2 text-[12px] text-ink-600">
          <input v-model="overdueOnly" type="checkbox" class="h-3.5 w-3.5" @change="reloadFromFirstPage" />
          仅看逾期
        </label>
        <div class="flex flex-wrap items-center gap-1.5">
          <button class="btn-outline" type="button" :disabled="loading" @click="loadList">
            {{ loading ? '加载中…' : '刷新' }}
          </button>
          <button class="btn-ghost" type="button" @click="resetFilters">重置</button>
        </div>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <span>共 {{ formatNumber(total) }} 条义务</span>
        <span class="tag bg-amber-50 text-amber-600">7 天内到期 {{ formatNumber(dueSoonCount) }}</span>
        <span class="tag bg-rose-50 text-rose-600">当前页逾期 {{ formatNumber(overdueCount) }}</span>
        <span class="ml-auto">数据来源 /contracts/obligations</span>
      </div>
    </div>

    <div class="grid gap-3 lg:grid-cols-3">
      <!-- 义务列表 -->
      <div class="card p-3 lg:col-span-2">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-[13px] font-medium text-ink-800">履约义务</h3>
          <span class="text-[11px] text-ink-400">第 {{ page }} / {{ pages }} 页</span>
        </div>

        <div
          v-if="error"
          class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
        >
          <span class="min-w-0 flex-1">{{ error }}</span>
          <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="loadList">重试</button>
        </div>

        <div v-if="loading && !rows.length" class="space-y-2">
          <div v-for="n in 5" :key="n" class="h-9 animate-pulse rounded bg-ink-100" />
        </div>
        <div v-else-if="!loading && !rows.length && !error" class="py-10 text-center text-[12px] text-ink-400">
          <p>暂无履约义务</p>
          <p class="mt-1">在合同详情中创建义务后，会在这里统一跟踪</p>
        </div>

        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[720px]">
            <thead>
              <tr class="border-b border-ink-100">
                <th class="th">义务内容</th>
                <th class="th">合同</th>
                <th class="th">责任人</th>
                <th class="th">截止日</th>
                <th class="th">状态</th>
                <th class="th w-[150px]">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id" class="border-b border-ink-50 last:border-0 hover:bg-ink-50/60">
                <td class="td max-w-[240px]">
                  <div class="truncate text-ink-800">{{ row.content || '未填写' }}</div>
                  <div class="mt-0.5 flex flex-wrap gap-1 text-[11px] text-ink-400">
                    <span>周期 {{ cycleLabel(row.cycle) }}</span>
                    <span v-if="row.trigger">触发 {{ row.trigger }}</span>
                    <span v-if="row.priority !== 'normal'">优先级 {{ priorityLabel(row.priority) }}</span>
                  </div>
                </td>
                <td class="td text-[12px] text-ink-500">{{ row.contract_number || `#${row.contract}` }}</td>
                <td class="td text-ink-500">{{ row.responsible_name || '—' }}</td>
                <td class="td whitespace-nowrap" :class="dueClass(row)">{{ formatDate(row.due_date) }}</td>
                <td class="td">
                  <span class="tag" :class="tagClass(statusTone(row.status))">{{ statusLabel(row.status) }}</span>
                </td>
                <td class="td">
                  <div class="flex flex-wrap items-center gap-1">
                    <button
                      v-if="!['completed', 'waived'].includes(row.status)"
                      class="text-[12px] text-brand-600 hover:underline"
                      type="button"
                      @click="openAction('complete', row)"
                    >完成</button>
                    <button
                      v-if="!['completed', 'waived'].includes(row.status)"
                      class="text-[12px] text-ink-500 hover:text-brand-600"
                      type="button"
                      @click="openAction('postpone', row)"
                    >延期</button>
                    <button
                      v-if="!['completed', 'waived'].includes(row.status)"
                      class="text-[12px] text-ink-500 hover:text-brand-600"
                      type="button"
                      @click="openAction('waive', row)"
                    >豁免</button>
                    <button
                      class="text-[12px] text-ink-500 hover:text-brand-600"
                      type="button"
                      @click="openAction('schedule', row)"
                    >排期</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="rows.length" class="mt-3 flex items-center gap-2 text-[11px] text-ink-400">
          <button class="btn-outline px-2 py-1" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">
            上一页
          </button>
          <button class="btn-outline px-2 py-1" type="button" :disabled="page >= pages || loading" @click="goPage(page + 1)">
            下一页
          </button>
          <span>共 {{ formatNumber(total) }} 条</span>
        </div>
      </div>

      <!-- 逾期列表 -->
      <div class="card p-3">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-[13px] font-medium text-ink-800">逾期义务</h3>
          <button class="text-[11px] text-brand-600" type="button" @click="loadOverdue">刷新</button>
        </div>
        <div v-if="overdueLoading" class="space-y-2">
          <div v-for="n in 3" :key="n" class="h-9 animate-pulse rounded bg-ink-100" />
        </div>
        <div v-else-if="overdueError" class="rounded-control bg-rose-50 px-2 py-2 text-[11px] text-rose-600">
          <div class="truncate">{{ overdueError }}</div>
          <button class="mt-1 font-medium" type="button" @click="loadOverdue">重试</button>
        </div>
        <div v-else-if="!overdueRows.length" class="py-8 text-center text-[12px] text-ink-400">当前没有逾期义务</div>
        <div v-else class="space-y-1">
          <div
            v-for="row in overdueRows"
            :key="row.id"
            class="rounded-control border border-rose-100 bg-rose-50/40 px-2 py-1.5 text-[12px]"
          >
            <div class="truncate text-ink-800">{{ row.content || '未填写义务' }}</div>
            <div class="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
              <span>截止 {{ formatDate(row.due_date) }}</span>
              <span>逾期 {{ overdueDays(row) }} 天</span>
              <button class="text-brand-600 hover:underline" type="button" @click="openAction('complete', row)">完成</button>
            </div>
          </div>
          <p class="pt-1 text-[11px] text-ink-400">接口 /contracts/obligations/overdue</p>
        </div>
      </div>
    </div>

    <!-- 里程碑 -->
    <div class="card p-3">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <h3 class="text-[13px] font-medium text-ink-800">里程碑完成</h3>
        <label class="ml-auto flex items-center gap-1.5 text-[12px] text-ink-500">
          合同
          <select v-model="milestoneContract" class="input w-[240px] py-1" @change="loadMilestones">
            <option :value="null">选择合同</option>
            <option v-for="item in contractOptions" :key="item.id" :value="item.id">
              {{ item.number || item.id }} {{ item.name }}
            </option>
          </select>
        </label>
        <button class="btn-outline px-2 py-1" type="button" :disabled="!milestoneContract || milestoneLoading" @click="loadMilestones">
          刷新
        </button>
      </div>

      <p v-if="!milestoneContract" class="py-6 text-center text-[12px] text-ink-400">
        选择一份合同后查看其里程碑，点击完成即可登记实际完成日期
      </p>
      <div v-else-if="milestoneLoading" class="space-y-2">
        <div v-for="n in 3" :key="n" class="h-8 animate-pulse rounded bg-ink-100" />
      </div>
      <div v-else-if="milestoneError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ milestoneError }}</span>
        <button class="shrink-0 font-medium" type="button" @click="loadMilestones">重试</button>
      </div>
      <div v-else-if="!milestoneRows.length" class="py-6 text-center text-[12px] text-ink-400">
        该合同还没有里程碑，可在合同详情中补充
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[640px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">里程碑</th>
              <th class="th">计划日期</th>
              <th class="th">实际日期</th>
              <th class="th text-right">金额</th>
              <th class="th">状态</th>
              <th class="th w-[90px]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in milestoneRows" :key="row.id" class="border-b border-ink-50 last:border-0">
              <td class="td max-w-[240px] truncate">{{ row.name }}</td>
              <td class="td whitespace-nowrap text-ink-500">{{ formatDate(row.plan_date) }}</td>
              <td class="td whitespace-nowrap text-ink-500">{{ formatDate(row.actual_date) }}</td>
              <td class="td text-right">{{ formatMoney(row.amount, 'CNY') }}</td>
              <td class="td">
                <span class="tag" :class="tagClass(milestoneTone(row.status))">{{ milestoneLabel(row.status) }}</span>
              </td>
              <td class="td">
                <button
                  class="text-[12px] text-brand-600 hover:underline disabled:text-ink-300"
                  type="button"
                  :disabled="row.status === 'completed' || acting"
                  @click="completeMilestone(row)"
                >{{ row.status === 'completed' ? '已完成' : '完成' }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 义务动作弹窗 -->
    <Modal :show="actionModal.show" :title="actionModal.title" width="460px" @close="closeAction">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-500">{{ actionModal.hint }}</p>
        <p class="rounded-control bg-ink-50 px-2 py-1.5 text-[12px] text-ink-700">
          {{ actionModal.row?.content || '未填写义务内容' }}
        </p>

        <label v-if="actionModal.kind === 'postpone'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">新的截止日</span>
          <input v-model="actionForm.due_date" class="input" type="date" />
        </label>

        <label v-if="actionModal.kind === 'schedule'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">生成期数</span>
          <input v-model.number="actionForm.count" class="input" type="number" min="1" max="24" />
        </label>

        <label v-if="actionModal.kind === 'complete'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">完成说明</span>
          <textarea v-model.trim="actionForm.note" class="input min-h-[64px]" maxlength="300" placeholder="填写履约结果，可留空" />
        </label>

        <label v-if="actionModal.kind === 'complete'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">证据 / 附件说明</span>
          <input v-model.trim="actionForm.evidence" class="input" maxlength="300" placeholder="例如验收单编号，可留空" />
        </label>

        <label v-if="['postpone', 'waive'].includes(actionModal.kind)" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">说明</span>
          <textarea v-model.trim="actionForm.note" class="input min-h-[56px]" maxlength="300" placeholder="填写调整原因" />
        </label>

        <p v-if="actionError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ actionError }}</p>

        <div class="flex items-center justify-end gap-2">
          <button class="btn-ghost" type="button" @click="closeAction">取消</button>
          <button class="btn-primary" type="button" :disabled="acting" @click="confirmAction">
            {{ acting ? '处理中…' : actionModal.confirmText }}
          </button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { contractsApi, normalizeList } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
  useDebounce,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['changed'])

const app = useAppStore()

const STATUS_OPTIONS = [
  { value: 'pending', label: '待履行' },
  { value: 'in_progress', label: '履行中' },
  { value: 'completed', label: '已完成' },
  { value: 'overdue', label: '已逾期' },
  { value: 'waived', label: '已豁免' },
  { value: 'cancelled', label: '已取消' },
]

const STATUS_LABELS = {
  pending: '待履行',
  in_progress: '履行中',
  completed: '已完成',
  overdue: '已逾期',
  waived: '已豁免',
  cancelled: '已取消',
}

const CYCLE_LABELS = {
  once: '一次性',
  weekly: '每周',
  monthly: '每月',
  quarterly: '每季',
  yearly: '每年',
}

const PRIORITY_LABELS = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}

const MILESTONE_LABELS = {
  planned: '计划中',
  completed: '已完成',
  delayed: '已延期',
  cancelled: '已取消',
}

const search = useDebounce(350)
const status = ref('')
const overdueOnly = ref(false)
const page = ref(1)
const pageSize = ref(20)
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const acting = ref(false)

const overdueRows = ref([])
const overdueLoading = ref(false)
const overdueError = ref('')

const contractOptions = ref([])
const milestoneContract = ref(null)
const milestoneRows = ref([])
const milestoneLoading = ref(false)
const milestoneError = ref('')

const actionModal = ref({ show: false, kind: '', title: '', hint: '', confirmText: '确认', row: null })
const actionForm = ref({ note: '', evidence: '', due_date: '', count: 3 })
const actionError = ref('')

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

const overdueCount = computed(() => rows.value.filter((row) => isOverdue(row)).length)

const dueSoonCount = computed(() => {
  const now = Date.now()
  return rows.value.filter((row) => {
    if (['completed', 'waived', 'cancelled'].includes(row.status)) return false
    const time = row.due_date ? new Date(row.due_date).getTime() : NaN
    if (Number.isNaN(time)) return false
    const diff = time - now
    return diff >= 0 && diff <= 7 * 86400000
  }).length
})

function statusLabel(value) {
  return STATUS_LABELS[value] || value || '未知'
}

function cycleLabel(value) {
  return CYCLE_LABELS[value] || value || '一次性'
}

function priorityLabel(value) {
  return PRIORITY_LABELS[value] || value || '普通'
}

function milestoneLabel(value) {
  return MILESTONE_LABELS[value] || value || '计划中'
}

function statusTone(value) {
  const s = String(value || '').toLowerCase()
  if (['completed', 'waived'].includes(s)) return 'success'
  if (s === 'overdue') return 'danger'
  if (s === 'in_progress') return 'info'
  if (s === 'cancelled') return 'neutral'
  return 'warning'
}

function milestoneTone(value) {
  const s = String(value || '').toLowerCase()
  if (s === 'completed') return 'success'
  if (s === 'delayed') return 'danger'
  if (s === 'cancelled') return 'neutral'
  return 'warning'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    info: 'bg-sky-50 text-sky-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function isOverdue(row) {
  if (!row?.due_date) return row?.status === 'overdue'
  if (['completed', 'waived', 'cancelled'].includes(row.status)) return false
  const time = new Date(row.due_date).getTime()
  return Number.isFinite(time) && time < Date.now()
}

function overdueDays(row) {
  if (!row?.due_date) return 0
  const time = new Date(row.due_date).getTime()
  if (!Number.isFinite(time)) return 0
  return Math.max(0, Math.floor((Date.now() - time) / 86400000))
}

function dueClass(row) {
  if (row?.status === 'overdue') return 'text-rose-600'
  const time = row?.due_date ? new Date(row.due_date).getTime() : NaN
  if (Number.isNaN(time)) return 'text-ink-400'
  const diff = time - Date.now()
  if (diff < 0) return 'text-rose-600'
  if (diff <= 7 * 86400000) return 'text-amber-600'
  return 'text-ink-500'
}

async function loadList() {
  loading.value = true
  error.value = ''
  const params = { page: page.value, page_size: pageSize.value }
  if (search.debounced.value.trim()) params.q = search.debounced.value.trim()
  if (status.value && !overdueOnly.value) params.status = status.value
  try {
    const data = await contractsApi.list(overdueOnly.value ? 'obligations/overdue/' : 'obligations/', params)
    const normalized = normalizeList(data, { page: page.value, page_size: pageSize.value })
    rows.value = normalized.items
    total.value = normalized.count
  } catch (e) {
    rows.value = []
    total.value = 0
    error.value = e?.message || '履约义务加载失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
  }
}

async function loadOverdue() {
  overdueLoading.value = true
  overdueError.value = ''
  try {
    const data = await contractsApi.list('obligations/overdue/', { page: 1, page_size: 10 })
    overdueRows.value = normalizeList(data).items
  } catch (e) {
    overdueRows.value = []
    overdueError.value = e?.message || '逾期列表暂不可用'
  } finally {
    overdueLoading.value = false
  }
}

async function loadContractOptions() {
  try {
    const data = await contractsApi.list('contracts/', { page: 1, page_size: 50, ordering: '-updated_at' })
    contractOptions.value = normalizeList(data).items
  } catch (e) {
    contractOptions.value = []
  }
}

async function loadMilestones() {
  if (!milestoneContract.value) {
    milestoneRows.value = []
    return
  }
  milestoneLoading.value = true
  milestoneError.value = ''
  try {
    const data = await contractsApi.list(`contracts/${milestoneContract.value}/milestones/`, {
      page: 1,
      page_size: 50,
    })
    milestoneRows.value = normalizeList(data).items
  } catch (e) {
    milestoneRows.value = []
    milestoneError.value = e?.message || '里程碑加载失败'
  } finally {
    milestoneLoading.value = false
  }
}

function reloadFromFirstPage() {
  page.value = 1
  loadList()
}

function goPage(next) {
  page.value = Math.min(Math.max(1, next), pages.value)
  loadList()
}

function changePageSize(event) {
  pageSize.value = Number(event?.target?.value) || 20
  page.value = 1
  loadList()
}

function resetFilters() {
  search.value = ''
  search.flush()
  status.value = ''
  overdueOnly.value = false
  page.value = 1
  loadList()
}

function openAction(kind, row) {
  const meta = {
    complete: { title: '完成义务', hint: '登记完成说明与证据后，义务状态变为已完成。', confirmText: '确认完成' },
    postpone: { title: '延期义务', hint: '调整截止日后，义务会按新日期重新计入排期。', confirmText: '确认延期' },
    waive: { title: '豁免义务', hint: '豁免后不再计入逾期统计，请说明原因。', confirmText: '确认豁免' },
    schedule: { title: '生成未来排期', hint: '按当前周期生成后续期次，生成数量建议不超过 12 期。', confirmText: '生成排期' },
  }[kind]
  if (!meta) return
  actionError.value = ''
  actionForm.value = {
    note: '',
    evidence: '',
    due_date: String(row?.due_date || '').slice(0, 10),
    count: 3,
  }
  actionModal.value = { show: true, kind, row, ...meta }
}

function closeAction() {
  actionModal.value = { show: false, kind: '', title: '', hint: '', confirmText: '确认', row: null }
  actionError.value = ''
}

function buildPayload(kind) {
  if (kind === 'complete') {
    return { note: actionForm.value.note, evidence: actionForm.value.evidence }
  }
  if (kind === 'postpone') {
    return { due_date: actionForm.value.due_date, note: actionForm.value.note }
  }
  if (kind === 'waive') {
    return { note: actionForm.value.note }
  }
  if (kind === 'schedule') {
    return { count: Number(actionForm.value.count) || 1 }
  }
  return {}
}

async function confirmAction() {
  const { kind, row } = actionModal.value
  if (!kind || !row) return
  if (kind === 'postpone' && !actionForm.value.due_date) {
    actionError.value = '请选择新的截止日'
    return
  }
  if (kind === 'waive' && !actionForm.value.note) {
    actionError.value = '请填写豁免原因'
    return
  }
  acting.value = true
  actionError.value = ''
  try {
    await contractsApi.action(`obligations/${row.id}/${kind}/`, buildPayload(kind))
    app.toastMsg(`${actionModal.value.title}成功`, 'success')
    closeAction()
    await Promise.all([loadList(), loadOverdue()])
    emit('changed')
  } catch (e) {
    actionError.value = e?.message || '操作失败'
    app.toastMsg(actionError.value, 'error')
  } finally {
    acting.value = false
  }
}

async function completeMilestone(row) {
  acting.value = true
  try {
    await contractsApi.action(`milestones/${row.id}/complete/`, {
      actual_date: new Date().toISOString().slice(0, 10),
    })
    app.toastMsg('里程碑已完成', 'success')
    await loadMilestones()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '里程碑完成失败', 'error')
  } finally {
    acting.value = false
  }
}

watch(search.debounced, () => {
  reloadFromFirstPage()
})

watch(
  () => props.refreshKey,
  () => {
    loadList()
    loadOverdue()
    loadContractOptions()
    if (milestoneContract.value) loadMilestones()
  }
)

onMounted(() => {
  loadList()
  loadOverdue()
  loadContractOptions()
})
</script>