<template>
  <section class="space-y-3">
    <!-- 筛选栏 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-end gap-2">
        <label class="block min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
          <input
            v-model="search.value"
            class="input"
            type="search"
            placeholder="按编号、名称、相对方搜索"
          />
        </label>
        <label class="block w-[132px]">
          <span class="mb-1 block text-[11px] text-ink-400">状态</span>
          <select v-model="status" class="input" @change="applyFilter">
            <option value="">全部状态</option>
            <option v-for="item in STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="block w-[132px]">
          <span class="mb-1 block text-[11px] text-ink-400">类型</span>
          <select v-model="typeFilter" class="input" @change="applyFilter">
            <option value="">全部类型</option>
            <option v-for="item in TYPE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="block w-[132px]">
          <span class="mb-1 block text-[11px] text-ink-400">排序</span>
          <select v-model="ordering" class="input" @change="applyFilter">
            <option value="-updated_at">最近更新</option>
            <option value="expire_date">到期日升序</option>
            <option value="-expire_date">到期日降序</option>
            <option value="-amount">金额从高到低</option>
            <option value="number">编号升序</option>
          </select>
        </label>
        <label class="block w-[104px]">
          <span class="mb-1 block text-[11px] text-ink-400">每页</span>
          <select :value="pageSize" class="input" @change="changePageSize">
            <option :value="10">10 条</option>
            <option :value="20">20 条</option>
            <option :value="50">50 条</option>
          </select>
        </label>
        <div class="flex flex-wrap items-center gap-1.5">
          <button class="btn-outline" type="button" :disabled="loading" @click="refresh">
            {{ loading ? '加载中…' : '刷新' }}
          </button>
          <button class="btn-ghost" type="button" @click="resetAll">重置</button>
          <button class="btn-primary" type="button" @click="openCreate">新建合同</button>
        </div>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <span>共 {{ formatNumber(total) }} 份合同</span>
        <span v-if="selected.length" class="tag-brand">已选 {{ selected.length }}</span>
        <span v-if="pageAmountText">本页金额 {{ pageAmountText }}</span>
      </div>
    </div>

    <!-- 批量操作 -->
    <div
      v-if="selected.length"
      class="flex flex-wrap items-center gap-2 rounded-control border border-brand-200 bg-brand-50/60 px-3 py-2 text-[12px]"
    >
      <span class="text-brand-700">已选择 {{ selected.length }} 份合同</span>
      <button class="btn-outline px-2 py-1" type="button" :disabled="acting" @click="batchSubmit">批量提交审批</button>
      <button class="btn-outline px-2 py-1" type="button" :disabled="acting" @click="batchArchive">批量归档</button>
      <button class="btn-outline px-2 py-1" type="button" :disabled="acting" @click="batchExport">批量导出</button>
      <button class="btn-danger px-2 py-1" type="button" :disabled="acting" @click="openBatchDelete">批量删除</button>
      <button class="btn-ghost px-2 py-1" type="button" @click="clearSelection">取消选择</button>
      <span class="ml-auto text-[11px] text-ink-400">批量动作逐条调用合同状态机接口，失败的条目会在结果中列出</span>
    </div>

    <!-- 列表 -->
    <div class="card p-3">
      <div
        v-if="error"
        class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="refresh">重试</button>
      </div>

      <div v-if="loading && !items.length" class="space-y-2 py-2">
        <div v-for="n in 6" :key="n" class="h-8 animate-pulse rounded bg-ink-100" />
      </div>

      <div v-else-if="!loading && !items.length && !error" class="py-12 text-center text-[12px] text-ink-400">
        <p>暂无符合条件的合同</p>
        <p class="mt-1">可以调整筛选条件，或直接新建一份合同</p>
        <button class="btn-primary mt-3" type="button" @click="openCreate">新建合同</button>
      </div>

      <div v-else-if="items.length" class="overflow-x-auto">
        <table class="w-full min-w-[1040px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th w-8">
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5"
                  :checked="allSelected"
                  aria-label="全选本页合同"
                  @change="toggleAll"
                />
              </th>
              <th class="th">编号</th>
              <th class="th">名称</th>
              <th class="th">类型</th>
              <th class="th text-right">金额</th>
              <th class="th">相对方</th>
              <th class="th">状态</th>
              <th class="th">负责人</th>
              <th class="th">到期日</th>
              <th class="th">风险</th>
              <th class="th w-[190px]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in items"
              :key="row.id"
              class="border-b border-ink-50 transition-colors last:border-0 hover:bg-ink-50/60"
            >
              <td class="td">
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5"
                  :checked="selected.includes(row.id)"
                  :aria-label="`选择合同 ${row.number || row.id}`"
                  @change="toggleOne(row.id)"
                />
              </td>
              <td class="td">
                <button class="font-mono text-[12px] text-brand-600 hover:underline" type="button" @click="openDetail(row.id)">
                  {{ row.number || '—' }}
                </button>
              </td>
              <td class="td max-w-[220px] truncate">{{ row.name || '未命名合同' }}</td>
              <td class="td text-ink-500">{{ typeLabel(row.contract_type) }}</td>
              <td class="td whitespace-nowrap text-right">{{ formatMoney(row.amount, row.currency || 'CNY') }}</td>
              <td class="td max-w-[140px] truncate text-ink-500">{{ row.counterparty_name || '—' }}</td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(row.status))">{{ statusLabel(row.status) }}</span>
              </td>
              <td class="td text-ink-500">{{ row.responsible_name || row.responsible || '—' }}</td>
              <td class="td whitespace-nowrap" :class="expiryClass(row)">
                {{ formatDate(row.expire_date) }}
              </td>
              <td class="td">
                <span class="tag" :class="riskClass(row)">{{ riskLabel(row) }}</span>
              </td>
              <td class="td">
                <div class="flex flex-wrap items-center gap-1">
                  <button class="text-[12px] text-brand-600 hover:underline" type="button" @click="openDetail(row.id)">详情</button>
                  <button class="text-[12px] text-ink-500 hover:text-brand-600" type="button" @click="openEdit(row)">编辑</button>
                  <select
                    class="rounded-control border border-ink-200 bg-white px-1 py-0.5 text-[11px] text-ink-600"
                    :value="''"
                    aria-label="合同状态操作"
                    :disabled="acting"
                    @change="onRowAction($event, row)"
                  >
                    <option value="">状态操作</option>
                    <option v-for="opt in rowActions(row)" :key="opt.kind" :value="opt.kind">{{ opt.label }}</option>
                  </select>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="items.length" class="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <span>第 {{ page }} / {{ pages }} 页</span>
        <button class="btn-outline px-2 py-1" type="button" :disabled="page <= 1 || loading" @click="goPage(page - 1)">
          上一页
        </button>
        <button class="btn-outline px-2 py-1" type="button" :disabled="page >= pages || loading" @click="goPage(page + 1)">
          下一页
        </button>
        <span>共 {{ formatNumber(total) }} 条</span>
        <span v-if="loading" class="text-brand-600">加载中…</span>
      </div>
    </div>

    <!-- 创建 / 编辑 -->
    <ContractFormModal
      :show="formVisible"
      :contract="editTarget"
      :submitting="submitting"
      @close="closeForm"
      @submit="submitForm"
    />

    <!-- 状态流转弹窗 -->
    <Modal :show="actionModal.show" :title="actionModal.title" width="460px" @close="closeAction">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-500">{{ actionModal.hint }}</p>
        <p class="rounded-control bg-ink-50 px-2 py-1.5 text-[12px] text-ink-700">
          {{ actionModal.contract?.number || '—' }} · {{ actionModal.contract?.name || '未命名合同' }}
        </p>

        <label v-if="actionModal.kind === 'clone'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">新合同名称</span>
          <input v-model.trim="actionForm.name" class="input" maxlength="200" placeholder="留空则由后端自动生成" />
        </label>

        <label v-if="actionModal.kind === 'sign'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">签署人</span>
          <input v-model.trim="actionForm.signer_name" class="input" maxlength="60" placeholder="签署人姓名" />
        </label>

        <label v-if="actionModal.kind === 'sign'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">签署方式</span>
          <select v-model="actionForm.method" class="input">
            <option value="electronic">电子签署</option>
            <option value="seal">印章签署</option>
            <option value="paper">纸质签署</option>
          </select>
        </label>

        <label v-if="actionModal.kind === 'terminate'" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">终止原因</span>
          <textarea v-model.trim="actionForm.reason" class="input min-h-[64px]" maxlength="300" placeholder="请说明终止原因" />
        </label>

        <label v-if="actionModal.needsOpinion" class="block">
          <span class="mb-1 block text-[12px] text-ink-500">
            {{ actionModal.kind === 'reject' ? '驳回意见' : '审批意见' }}
          </span>
          <textarea
            v-model.trim="actionForm.opinion"
            class="input min-h-[64px]"
            maxlength="300"
            :placeholder="actionModal.kind === 'reject' ? '请说明驳回原因' : '可填写审批意见，留空表示同意'"
          />
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

    <!-- 删除确认 -->
    <Modal :show="deleteModal.show" title="删除合同" width="420px" @close="closeDelete">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">{{ deleteModal.hint }}</p>
        <div v-if="deleteModal.targets.length" class="max-h-[160px] overflow-y-auto rounded-control bg-ink-50 px-2 py-1.5 text-[12px] text-ink-600">
          <div v-for="row in deleteModal.targets" :key="row.id" class="truncate">
            {{ row.number || row.id }} · {{ row.name || '未命名合同' }}
          </div>
        </div>
        <p class="text-[11px] text-rose-600">删除后不可恢复，已签署或生效中的合同请改用终止。</p>
        <div class="flex items-center justify-end gap-2">
          <button class="btn-ghost" type="button" @click="closeDelete">取消</button>
          <button class="btn-danger" type="button" :disabled="acting" @click="confirmDelete">
            {{ acting ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 详情抽屉 -->
    <ContractDetailDrawer
      :show="drawerVisible"
      :contract-id="detailId"
      :seed="detailSeed"
      :reload-token="drawerToken"
      :acting="acting"
      @close="closeDetail"
      @action="performAction"
    />
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { contractsApi } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
  useDebounce,
  useDomainResource,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import ContractFormModal from './ContractFormModal.vue'
import ContractDetailDrawer from './ContractDetailDrawer.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['changed'])

const app = useAppStore()

const {
  items,
  loading,
  error,
  page,
  pageSize,
  total,
  pages,
  q,
  status,
  filters,
  setPage,
  setPageSize,
  refresh,
  resetFilters,
} = useDomainResource('contracts', 'contracts/', {
  pageSize: 20,
  params: { ordering: '-updated_at' },
})

const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'pending_approval', label: '待审批' },
  { value: 'approved', label: '已批准' },
  { value: 'signed', label: '已签署' },
  { value: 'active', label: '生效中' },
  { value: 'completed', label: '已完成' },
  { value: 'terminated', label: '已终止' },
  { value: 'expired', label: '已到期' },
  { value: 'archived', label: '已归档' },
  { value: 'rejected', label: '已驳回' },
]

const TYPE_OPTIONS = [
  { value: 'service', label: '服务合同' },
  { value: 'sales', label: '销售合同' },
  { value: 'purchase', label: '采购合同' },
  { value: 'lease', label: '租赁合同' },
  { value: 'labor', label: '劳务合同' },
  { value: 'license', label: '授权许可' },
  { value: 'nda', label: '保密协议' },
  { value: 'other', label: '其他类型' },
]

const CONTRACT_STATUS = {
  draft: '草稿',
  pending: '待提交',
  pending_approval: '待审批',
  submitted: '已提交',
  approving: '审批中',
  approved: '已批准',
  rejected: '已驳回',
  signed: '已签署',
  active: '生效中',
  executing: '履行中',
  completed: '已完成',
  terminated: '已终止',
  expired: '已到期',
  archived: '已归档',
  paused: '已暂停',
}

const TYPE_LABELS = {
  service: '服务合同',
  sales: '销售合同',
  purchase: '采购合同',
  lease: '租赁合同',
  labor: '劳务合同',
  license: '授权许可',
  nda: '保密协议',
  other: '其他类型',
}

const search = useDebounce(350)
const typeFilter = ref('')
const ordering = ref('-updated_at')
const selected = ref([])
const acting = ref(false)
const submitting = ref(false)

const formVisible = ref(false)
const editTarget = ref(null)

const actionModal = ref({
  show: false,
  kind: '',
  title: '',
  hint: '',
  confirmText: '确认',
  needsOpinion: false,
  contract: null,
})
const actionForm = ref({ name: '', signer_name: '', method: 'electronic', reason: '', opinion: '' })
const actionError = ref('')

const deleteModal = ref({ show: false, targets: [], batch: false, hint: '' })

const drawerVisible = ref(false)
const detailId = ref(null)
const detailSeed = ref(null)
const drawerToken = ref(0)

function statusLabel(value) {
  return CONTRACT_STATUS[value] || value || '未知'
}

function typeLabel(value) {
  return TYPE_LABELS[value] || value || '未分类'
}

function statusTone(value) {
  const s = String(value || '').toLowerCase()
  if (['active', 'approved', 'signed', 'executing'].includes(s)) return 'success'
  if (['completed', 'archived'].includes(s)) return 'info'
  if (['draft', 'pending', 'pending_approval', 'submitted', 'approving', 'paused'].includes(s)) return 'warning'
  if (['rejected', 'terminated', 'expired'].includes(s)) return 'danger'
  return 'neutral'
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

function riskLabel(row) {
  const score = Number(row?.risk_score)
  if (Number.isFinite(score)) {
    if (score >= 80) return '极高'
    if (score >= 60) return '高'
    if (score >= 30) return '中'
    return '低'
  }
  return { critical: '极高', high: '高', medium: '中', low: '低' }[row?.risk_level] || '低'
}

function riskClass(row) {
  const score = Number(row?.risk_score)
  const level = Number.isFinite(score)
    ? (score >= 80 ? 'critical' : score >= 60 ? 'high' : score >= 30 ? 'medium' : 'low')
    : (row?.risk_level || 'low')
  return {
    critical: 'bg-rose-100 text-rose-700',
    high: 'bg-rose-50 text-rose-600',
    medium: 'bg-amber-50 text-amber-600',
    low: 'bg-emerald-50 text-emerald-600',
  }[level] || 'bg-ink-100 text-ink-600'
}

function expiryClass(row) {
  const time = row?.expire_date ? new Date(row.expire_date).getTime() : NaN
  if (Number.isNaN(time)) return 'text-ink-400'
  const diff = time - Date.now()
  if (diff < 0) return 'text-rose-600'
  if (diff <= 30 * 86400000) return 'text-amber-600'
  return 'text-ink-500'
}

const allSelected = computed(() => items.value.length > 0 && items.value.every((row) => selected.value.includes(row.id)))

const pageAmountText = computed(() => {
  if (!items.value.length) return ''
  const bucket = new Map()
  for (const row of items.value) {
    const currency = row.currency || 'CNY'
    bucket.set(currency, (bucket.get(currency) || 0) + (Number(row.amount) || 0))
  }
  return Array.from(bucket.entries())
    .map(([currency, amount]) => formatMoney(amount, currency))
    .join(' / ')
})

function rowActions(row) {
  const status = String(row?.status || '').toLowerCase()
  const list = []
  if (['draft', 'pending', 'rejected'].includes(status)) list.push({ kind: 'submit', label: '提交审批' })
  if (['pending_approval', 'submitted', 'approving'].includes(status)) {
    list.push({ kind: 'approve', label: '审批通过' })
    list.push({ kind: 'reject', label: '驳回' })
  }
  if (status === 'approved') list.push({ kind: 'sign', label: '登记签署' })
  if (status === 'signed') list.push({ kind: 'activate', label: '生效' })
  if (status === 'active') {
    list.push({ kind: 'terminate', label: '终止' })
    list.push({ kind: 'complete', label: '完成' })
  }
  list.push({ kind: 'clone', label: '克隆' })
  list.push({ kind: 'export', label: '导出' })
  if (!['active', 'signed'].includes(status)) list.push({ kind: 'delete', label: '删除' })
  return list
}

watch(search.debounced, (value) => {
  q.value = value
  setPage(1)
  refresh()
})

watch(items, (rows) => {
  const ids = new Set(rows.map((row) => row.id))
  selected.value = selected.value.filter((id) => ids.has(id))
})

watch(
  () => props.refreshKey,
  () => refresh()
)

function applyFilter() {
  filters.value = {
    ...filters.value,
    contract_type: typeFilter.value,
    ordering: ordering.value,
  }
  setPage(1)
  refresh()
}

function changePageSize(event) {
  const next = Number(event?.target?.value) || 20
  setPageSize(next)
  refresh()
}

function goPage(next) {
  setPage(next)
  refresh()
}

function resetAll() {
  resetFilters()
  typeFilter.value = ''
  ordering.value = '-updated_at'
  filters.value = { ordering: '-updated_at' }
  search.value = ''
  search.flush()
  selected.value = []
  refresh()
}

function toggleOne(id) {
  if (selected.value.includes(id)) selected.value = selected.value.filter((item) => item !== id)
  else selected.value = [...selected.value, id]
}

function toggleAll() {
  selected.value = allSelected.value ? [] : items.value.map((row) => row.id)
}

function clearSelection() {
  selected.value = []
}

function openCreate() {
  editTarget.value = null
  formVisible.value = true
}

function openEdit(row) {
  editTarget.value = { ...row }
  formVisible.value = true
}

function closeForm() {
  formVisible.value = false
  editTarget.value = null
}

async function submitForm(payload) {
  submitting.value = true
  try {
    if (editTarget.value?.id) {
      await contractsApi.update(`contracts/${editTarget.value.id}/update/`, payload)
      app.toastMsg('合同已保存', 'success')
    } else {
      await contractsApi.create('contracts/create/', payload)
      app.toastMsg('合同已创建', 'success')
    }
    closeForm()
    await refresh()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '保存失败', 'error')
  } finally {
    submitting.value = false
  }
}

function openDetail(id) {
  detailId.value = id
  detailSeed.value = items.value.find((row) => row.id === id) || null
  drawerVisible.value = true
}

function closeDetail() {
  drawerVisible.value = false
  detailId.value = null
  detailSeed.value = null
}

const ACTION_META = {
  submit: { title: '提交审批', hint: '提交后合同进入审批流程，审批人可在合同台账中处理。', confirmText: '提交', needsOpinion: false },
  approve: { title: '审批通过', hint: '确认通过该合同，审批意见会写入流转记录。', confirmText: '通过', needsOpinion: true },
  reject: { title: '驳回合同', hint: '驳回后合同回到草稿态，可修改后重新提交。', confirmText: '驳回', needsOpinion: true },
  sign: { title: '登记签署', hint: '登记签署人与签署方式，签署完成后合同可生效。', confirmText: '登记签署', needsOpinion: false },
  activate: { title: '合同生效', hint: '生效后合同进入履约阶段，可继续登记履约义务与付款。', confirmText: '确认生效', needsOpinion: false },
  terminate: { title: '终止合同', hint: '终止是不可逆操作，请填写终止原因备查。', confirmText: '确认终止', needsOpinion: false },
  complete: { title: '完成合同', hint: '合同履约完毕，完成后可归档。', confirmText: '确认完成', needsOpinion: false },
  clone: { title: '克隆合同', hint: '以当前合同为模板复制一份草稿，便于快速复用条款。', confirmText: '克隆', needsOpinion: false },
}

function performAction(kind, contract) {
  if (!kind || !contract) return
  if (kind === 'export') {
    exportContracts([contract.id])
    return
  }
  if (kind === 'delete') {
    deleteModal.value = {
      show: true,
      batch: false,
      targets: [contract],
      hint: `确认删除合同「${contract.name || contract.number || contract.id}」？`,
    }
    return
  }
  const meta = ACTION_META[kind]
  if (!meta) return
  actionError.value = ''
  actionForm.value = {
    name: kind === 'clone' ? `${contract.name || '合同'} 副本` : '',
    signer_name: contract.responsible_name || '',
    method: 'electronic',
    reason: '',
    opinion: '',
  }
  actionModal.value = {
    show: true,
    kind,
    contract,
    title: meta.title,
    hint: meta.hint,
    confirmText: meta.confirmText,
    needsOpinion: meta.needsOpinion,
  }
}

function closeAction() {
  actionModal.value = {
    show: false,
    kind: '',
    contract: null,
    title: '',
    hint: '',
    confirmText: '确认',
    needsOpinion: false,
  }
  actionError.value = ''
}

function buildPayload(kind) {
  const form = actionForm.value
  if (kind === 'approve' || kind === 'reject') return { opinion: form.opinion }
  if (kind === 'sign') {
    return {
      signer_name: form.signer_name || actionModal.value.contract?.responsible_name || '签署人',
      method: form.method,
    }
  }
  if (kind === 'terminate') return { reason: form.reason }
  if (kind === 'clone') return { name: form.name }
  if (kind === 'submit') return { opinion: form.opinion }
  return {}
}

function validateAction(kind) {
  if (kind === 'reject' && !actionForm.value.opinion) return '驳回需要填写意见'
  if (kind === 'terminate' && !actionForm.value.reason) return '终止需要填写原因'
  if (kind === 'sign' && !actionForm.value.signer_name) return '请填写签署人'
  return ''
}

async function confirmAction() {
  const kind = actionModal.value.kind
  const contract = actionModal.value.contract
  if (!kind || !contract) return
  const message = validateAction(kind)
  if (message) {
    actionError.value = message
    return
  }
  acting.value = true
  actionError.value = ''
  try {
    await contractsApi.action(`contracts/${contract.id}/${kind}/`, buildPayload(kind))
    app.toastMsg(`${ACTION_META[kind]?.title || '操作'}成功`, 'success')
    closeAction()
    await refresh()
    drawerToken.value += 1
    emit('changed')
  } catch (e) {
    actionError.value = e?.message || '操作失败'
    app.toastMsg(actionError.value, 'error')
  } finally {
    acting.value = false
  }
}

function onRowAction(event, row) {
  const kind = event?.target?.value
  if (kind) performAction(kind, row)
  if (event?.target) event.target.value = ''
}

function openBatchDelete() {
  const targets = items.value.filter((row) => selected.value.includes(row.id))
  deleteModal.value = {
    show: true,
    batch: true,
    targets,
    hint: `确认删除选中的 ${targets.length} 份合同？`,
  }
}

function closeDelete() {
  deleteModal.value = { show: false, targets: [], batch: false, hint: '' }
}

async function confirmDelete() {
  const targets = deleteModal.value.targets
  if (!targets.length) return
  acting.value = true
  const failed = []
  for (const row of targets) {
    try {
      await contractsApi.remove(`contracts/${row.id}/delete/`)
    } catch (e) {
      failed.push(`${row.number || row.id}: ${e?.message || '删除失败'}`)
    }
  }
  acting.value = false
  closeDelete()
  selected.value = []
  await refresh()
  emit('changed')
  if (failed.length) app.toastMsg(`删除完成，${failed.length} 条失败：${failed[0]}`, 'error')
  else app.toastMsg('已删除', 'success')
}

async function batchRun(kind, label) {
  const targets = items.value.filter((row) => selected.value.includes(row.id))
  if (!targets.length) return
  acting.value = true
  const failed = []
  for (const row of targets) {
    try {
      const payload = kind === 'clone' ? { name: `${row.name || '合同'} 副本` } : {}
      await contractsApi.action(`contracts/${row.id}/${kind}/`, payload)
    } catch (e) {
      failed.push(`${row.number || row.id}: ${e?.message || '失败'}`)
    }
  }
  acting.value = false
  await refresh()
  emit('changed')
  if (failed.length) app.toastMsg(`${label}完成，${failed.length} 条失败：${failed[0]}`, 'error')
  else app.toastMsg(`${label}完成，共 ${targets.length} 份合同`, 'success')
}

function batchSubmit() {
  batchRun('submit', '批量提交审批')
}

function batchArchive() {
  batchRun('archive', '批量归档')
}

function downloadJson(payload, filename) {
  try {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  } catch (e) {
    app.toastMsg(e?.message || '本地下载失败', 'error')
  }
}

async function exportContracts(ids) {
  if (!ids.length) return
  acting.value = true
  const results = await Promise.allSettled(ids.map((id) => contractsApi.action(`contracts/${id}/export/`, {})))
  acting.value = false
  const rows = results.filter((item) => item.status === 'fulfilled').map((item) => item.value)
  const firstError = results.find((item) => item.status === 'rejected')
  if (!rows.length) {
    app.toastMsg(firstError?.reason?.message || '导出接口不可用', 'error')
    return
  }
  downloadJson(
    { exported_at: new Date().toISOString(), count: rows.length, items: rows },
    `contracts-export-${Date.now()}.json`
  )
  app.toastMsg(`已导出 ${rows.length} 份合同的归档数据`, 'success')
  if (firstError) app.toastMsg(`部分合同导出失败：${firstError.reason?.message || '未知原因'}`, 'error')
}

function batchExport() {
  exportContracts(items.value.filter((row) => selected.value.includes(row.id)).map((row) => row.id))
}

defineExpose({ openCreate, openDetail })
</script>