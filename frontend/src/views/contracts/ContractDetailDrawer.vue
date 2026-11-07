<template>
  <Teleport to="body">
    <div v-if="show" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="$emit('close')"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[620px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="tag">{{ typeLabel(contract?.contract_type) }}</span>
              <span class="tag" :class="tagClass(statusTone(contract?.status))">{{ statusLabel(contract?.status) }}</span>
              <span v-if="contract" class="tag" :class="riskClass(contract)">风险 {{ riskLabel(contract) }}</span>
            </div>
            <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">
              {{ contract?.name || '合同详情' }}
            </h3>
            <p class="text-[11px] text-ink-400">{{ contract?.number || '—' }}</p>
          </div>
          <button class="shrink-0 text-[12px] text-ink-400 hover:text-ink-600" type="button" @click="$emit('close')">
            关闭
          </button>
        </div>

        <div class="flex flex-wrap items-center gap-1.5 border-b border-ink-100 px-4 py-2">
          <button
            v-for="btn in actionButtons"
            :key="btn.kind"
            class="btn-ghost px-2 py-1 text-[12px]"
            :class="btn.primary ? 'text-brand-600' : ''"
            type="button"
            :disabled="btn.disabled || acting"
            @click="$emit('action', btn.kind, contract)"
          >
            {{ btn.label }}
          </button>
        </div>

        <div class="flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <div v-if="detailLoading && !contract" class="space-y-2">
            <div v-for="n in 5" :key="n" class="h-6 animate-pulse rounded bg-ink-100" />
          </div>
          <div
            v-else-if="detailError"
            class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
          >
            <span class="min-w-0 flex-1">{{ detailError }}</span>
            <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="loadDetail">重试</button>
          </div>

          <template v-else>
            <!-- 基本信息 -->
            <section>
              <h4 class="mb-1.5 text-[13px] font-medium text-ink-700">基本信息</h4>
              <div class="grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-control bg-ink-50 px-3 py-2 text-[12px]">
                <div class="text-ink-400">合同类型</div>
                <div class="text-ink-700">{{ typeLabel(contract?.contract_type) }}</div>
                <div class="text-ink-400">合同金额</div>
                <div class="text-ink-700">{{ formatMoney(contract?.amount, contract?.currency || 'CNY') }}</div>
                <div class="text-ink-400">相对方</div>
                <div class="truncate text-ink-700">{{ contract?.counterparty_name || '—' }}</div>
                <div class="text-ink-400">负责人</div>
                <div class="text-ink-700">{{ contract?.responsible_name || contract?.responsible || '—' }}</div>
                <div class="text-ink-400">签订日</div>
                <div class="text-ink-700">{{ formatDate(contract?.sign_date) }}</div>
                <div class="text-ink-400">生效日</div>
                <div class="text-ink-700">{{ formatDate(contract?.effective_date) }}</div>
                <div class="text-ink-400">到期日</div>
                <div class="text-ink-700">{{ formatDate(contract?.expire_date) }}</div>
                <div class="text-ink-400">续约方式</div>
                <div class="text-ink-700">{{ renewalLabel(contract?.renewal_mode) }}</div>
                <div class="text-ink-400">风险分</div>
                <div class="text-ink-700">{{ formatNumber(contract?.risk_score) }}</div>
                <div class="text-ink-400">创建时间</div>
                <div class="text-ink-700">{{ formatDate(contract?.created_at, true) }}</div>
              </div>
            </section>

            <!-- 参与方 -->
            <section>
              <div class="mb-1.5 flex items-center justify-between">
                <h4 class="text-[13px] font-medium text-ink-700">参与方</h4>
                <span class="text-[11px] text-ink-400">{{ parties.length }} 个主体</span>
              </div>
              <p v-if="sectionErrors.parties" class="text-[11px] text-amber-600">{{ sectionErrors.parties }}</p>
              <p v-else-if="!parties.length && !sectionLoading.parties" class="text-[11px] text-ink-400">暂无参与方记录</p>
              <div v-else class="space-y-1">
                <div
                  v-for="row in parties"
                  :key="row.id"
                  class="flex flex-wrap items-center gap-2 rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <span class="min-w-0 flex-1 truncate text-ink-800">{{ row.name || '未命名主体' }}</span>
                  <span class="tag">{{ roleLabel(row.role) }}</span>
                  <span class="text-[11px] text-ink-400">{{ row.contact || '无联系人' }} {{ row.phone || '' }}</span>
                  <span class="tag" :class="row.signed ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                    {{ row.signed ? '已签署' : '待签署' }}
                  </span>
                </div>
              </div>
            </section>

            <!-- 版本 -->
            <section>
              <div class="mb-1.5 flex items-center justify-between">
                <h4 class="text-[13px] font-medium text-ink-700">版本</h4>
                <span class="text-[11px] text-ink-400">{{ versions.length }} 个版本</span>
              </div>
              <p v-if="sectionErrors.versions" class="text-[11px] text-amber-600">{{ sectionErrors.versions }}</p>
              <p v-else-if="!versions.length && !sectionLoading.versions" class="text-[11px] text-ink-400">暂无版本记录</p>
              <div v-else class="overflow-x-auto">
                <table class="w-full min-w-[420px]">
                  <thead>
                    <tr class="border-b border-ink-100">
                      <th class="th">版本</th>
                      <th class="th">变更摘要</th>
                      <th class="th">创建人</th>
                      <th class="th">时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in versions" :key="row.id" class="border-b border-ink-50 last:border-0">
                      <td class="td">
                        v{{ row.version_no }}
                        <span v-if="row.is_current" class="tag ml-1 bg-emerald-50 text-emerald-600">当前</span>
                      </td>
                      <td class="td max-w-[200px] truncate text-ink-500">{{ row.change_summary || '—' }}</td>
                      <td class="td text-ink-500">{{ row.created_by_name || row.created_by || '—' }}</td>
                      <td class="td text-ink-400">{{ formatDate(row.created_at, true) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- 履约义务 -->
            <section>
              <div class="mb-1.5 flex items-center justify-between">
                <h4 class="text-[13px] font-medium text-ink-700">履约义务</h4>
                <span class="text-[11px] text-ink-400">{{ obligations.length }} 条</span>
              </div>
              <p v-if="sectionErrors.obligations" class="text-[11px] text-amber-600">{{ sectionErrors.obligations }}</p>
              <p v-else-if="!obligations.length && !sectionLoading.obligations" class="text-[11px] text-ink-400">暂无履约义务</p>
              <div v-else class="space-y-1">
                <div
                  v-for="row in obligations"
                  :key="row.id"
                  class="rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <div class="flex items-center gap-2">
                    <span class="min-w-0 flex-1 truncate text-ink-800">{{ row.content || '未填写义务内容' }}</span>
                    <span class="tag" :class="tagClass(obligationTone(row.status))">{{ obligationLabel(row.status) }}</span>
                  </div>
                  <div class="mt-0.5 flex flex-wrap gap-2 text-[11px] text-ink-400">
                    <span>截止 {{ formatDate(row.due_date) }}</span>
                    <span>责任人 {{ row.responsible_name || '—' }}</span>
                    <span>周期 {{ cycleLabel(row.cycle) }}</span>
                  </div>
                </div>
              </div>
            </section>

            <!-- 里程碑 -->
            <section>
              <div class="mb-1.5 flex items-center justify-between">
                <h4 class="text-[13px] font-medium text-ink-700">里程碑</h4>
                <span class="text-[11px] text-ink-400">{{ milestones.length }} 个</span>
              </div>
              <p v-if="sectionErrors.milestones" class="text-[11px] text-amber-600">{{ sectionErrors.milestones }}</p>
              <p v-else-if="!milestones.length && !sectionLoading.milestones" class="text-[11px] text-ink-400">暂无里程碑</p>
              <div v-else class="space-y-1">
                <div
                  v-for="row in milestones"
                  :key="row.id"
                  class="flex flex-wrap items-center gap-2 rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <span class="min-w-0 flex-1 truncate text-ink-800">{{ row.name }}</span>
                  <span class="text-[11px] text-ink-400">计划 {{ formatDate(row.plan_date) }}</span>
                  <span class="text-[11px] text-ink-400">实际 {{ formatDate(row.actual_date) }}</span>
                  <span class="tag" :class="tagClass(milestoneTone(row.status))">{{ milestoneLabel(row.status) }}</span>
                </div>
              </div>
            </section>

            <!-- 付款 -->
            <section>
              <div class="mb-1.5 flex items-center justify-between">
                <h4 class="text-[13px] font-medium text-ink-700">付款计划</h4>
                <span class="text-[11px] text-ink-400">{{ payments.length }} 期</span>
              </div>
              <p v-if="sectionErrors.payments" class="text-[11px] text-amber-600">{{ sectionErrors.payments }}</p>
              <p v-else-if="!payments.length && !sectionLoading.payments" class="text-[11px] text-ink-400">暂无付款计划</p>
              <div v-else class="overflow-x-auto">
                <table class="w-full min-w-[460px]">
                  <thead>
                    <tr class="border-b border-ink-100">
                      <th class="th">期次</th>
                      <th class="th text-right">计划金额</th>
                      <th class="th text-right">实付金额</th>
                      <th class="th">计划日</th>
                      <th class="th">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in payments" :key="row.id" class="border-b border-ink-50 last:border-0">
                      <td class="td">第 {{ row.period_no ?? '—' }} 期</td>
                      <td class="td text-right">{{ formatMoney(row.plan_amount, contract?.currency || 'CNY') }}</td>
                      <td class="td text-right text-ink-500">{{ formatMoney(row.paid_amount, contract?.currency || 'CNY') }}</td>
                      <td class="td text-ink-500">{{ formatDate(row.plan_date) }}</td>
                      <td class="td">
                        <span class="tag" :class="tagClass(paymentTone(row.status))">{{ paymentLabel(row.status) }}</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- 签署 -->
            <section>
              <div class="mb-1.5 flex items-center justify-between">
                <h4 class="text-[13px] font-medium text-ink-700">签署记录</h4>
                <span class="text-[11px] text-ink-400">{{ signatures.length }} 条</span>
              </div>
              <p v-if="sectionErrors.signatures" class="text-[11px] text-amber-600">{{ sectionErrors.signatures }}</p>
              <p v-else-if="!signatures.length && !sectionLoading.signatures" class="text-[11px] text-ink-400">暂无签署记录</p>
              <div v-else class="space-y-1">
                <div
                  v-for="row in signatures"
                  :key="row.id"
                  class="flex flex-wrap items-center gap-2 rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <span class="min-w-0 flex-1 truncate text-ink-800">{{ row.signer_name || '未填写签署人' }}</span>
                  <span class="tag">{{ methodLabel(row.method) }}</span>
                  <span class="text-[11px] text-ink-400">{{ formatDate(row.signed_at, true) }}</span>
                  <span class="tag" :class="tagClass(signatureTone(row.status))">{{ signatureLabel(row.status) }}</span>
                </div>
              </div>
            </section>

            <!-- 风险 -->
            <section>
              <div class="mb-1.5 flex items-center justify-between">
                <h4 class="text-[13px] font-medium text-ink-700">风险项</h4>
                <span class="text-[11px] text-ink-400">{{ risks.length }} 条</span>
              </div>
              <p v-if="sectionErrors.risks" class="text-[11px] text-amber-600">{{ sectionErrors.risks }}</p>
              <p v-else-if="!risks.length && !sectionLoading.risks" class="text-[11px] text-ink-400">暂无风险记录</p>
              <div v-else class="space-y-1">
                <div
                  v-for="row in risks"
                  :key="row.id"
                  class="rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <div class="flex items-center gap-2">
                    <span class="min-w-0 flex-1 truncate text-ink-800">{{ row.title || '未命名风险' }}</span>
                    <span class="tag" :class="riskLevelClass(row.level)">{{ riskLevelLabel(row.level) }}</span>
                    <span class="tag" :class="tagClass(row.status === 'open' ? 'warning' : 'success')">
                      {{ row.status === 'open' ? '打开' : '已关闭' }}
                    </span>
                  </div>
                  <p class="mt-0.5 line-clamp-2 text-[11px] text-ink-500">{{ row.description || '无描述' }}</p>
                  <p v-if="row.mitigation" class="mt-0.5 line-clamp-2 text-[11px] text-ink-400">
                    缓解：{{ row.mitigation }}
                  </p>
                </div>
              </div>
            </section>
          </template>
        </div>

        <div class="border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
          详情来源：/contracts/contracts/{{ contractId }} 及参与方、版本、义务、里程碑、付款、签署、风险子资源
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { contractsApi, normalizeList } from '../../api/platform'
import {
  formatDate,
  formatMoney,
  formatNumber,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'

const props = defineProps({
  show: { type: Boolean, default: false },
  contractId: { type: [Number, String], default: null },
  seed: { type: Object, default: null },
  reloadToken: { type: Number, default: 0 },
  acting: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'action'])

const app = useAppStore()

const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const parties = ref([])
const versions = ref([])
const obligations = ref([])
const milestones = ref([])
const payments = ref([])
const signatures = ref([])
const risks = ref([])

const sectionLoading = ref({
  parties: false,
  versions: false,
  obligations: false,
  milestones: false,
  payments: false,
  signatures: false,
  risks: false,
})
const sectionErrors = ref({
  parties: '',
  versions: '',
  obligations: '',
  milestones: '',
  payments: '',
  signatures: '',
  risks: '',
})

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

const RENEWAL_LABELS = {
  none: '不续约',
  auto: '自动续约',
  manual: '手动续约',
  negotiate: '协商续约',
}

const ROLE_LABELS = {
  party_a: '甲方',
  party_b: '乙方',
  party_c: '丙方',
  witness: '见证方',
  guarantor: '担保方',
  other: '其他',
}

const OBLIGATION_LABELS = {
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

const MILESTONE_LABELS = {
  planned: '计划中',
  completed: '已完成',
  delayed: '已延期',
  cancelled: '已取消',
}

const PAYMENT_LABELS = {
  planned: '计划中',
  partial: '部分支付',
  paid: '已支付',
  overdue: '已逾期',
  cancelled: '已取消',
}

const SIGNATURE_LABELS = {
  pending: '待签署',
  signed: '已签署',
  declined: '已拒签',
  cancelled: '已取消',
}

const METHOD_LABELS = {
  electronic: '电子签署',
  seal: '印章签署',
  paper: '纸质签署',
}

const RISK_LEVEL_LABELS = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '极高',
}

const contract = computed(() => detail.value || props.seed || null)

const actionButtons = computed(() => {
  const status = String(contract.value?.status || '').toLowerCase()
  return [
    {
      kind: 'submit',
      label: '提交审批',
      primary: true,
      disabled: !['draft', 'pending', 'rejected'].includes(status),
    },
    {
      kind: 'approve',
      label: '审批通过',
      primary: true,
      disabled: !['pending_approval', 'submitted', 'approving'].includes(status),
    },
    {
      kind: 'reject',
      label: '驳回',
      disabled: !['pending_approval', 'submitted', 'approving'].includes(status),
    },
    {
      kind: 'sign',
      label: '登记签署',
      disabled: status !== 'approved',
    },
    {
      kind: 'activate',
      label: '生效',
      disabled: status !== 'signed',
    },
    {
      kind: 'terminate',
      label: '终止',
      disabled: status !== 'active',
    },
    {
      kind: 'complete',
      label: '完成',
      disabled: !['active', 'signed'].includes(status),
    },
    {
      kind: 'clone',
      label: '克隆',
    },
  ]
})

function statusLabel(status) {
  return CONTRACT_STATUS[status] || status || '未知'
}

function statusTone(status) {
  const s = String(status || '').toLowerCase()
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

function typeLabel(value) {
  return TYPE_LABELS[value] || value || '未分类'
}

function renewalLabel(value) {
  return RENEWAL_LABELS[value] || value || '不续约'
}

function roleLabel(value) {
  return ROLE_LABELS[value] || value || '其他'
}

function obligationLabel(value) {
  return OBLIGATION_LABELS[value] || value || '未知'
}

function obligationTone(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'completed' || s === 'waived') return 'success'
  if (s === 'overdue') return 'danger'
  if (s === 'in_progress') return 'info'
  return 'warning'
}

function cycleLabel(value) {
  return CYCLE_LABELS[value] || value || '一次性'
}

function milestoneLabel(value) {
  return MILESTONE_LABELS[value] || value || '计划中'
}

function milestoneTone(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'completed') return 'success'
  if (s === 'delayed') return 'danger'
  if (s === 'cancelled') return 'neutral'
  return 'warning'
}

function paymentLabel(value) {
  return PAYMENT_LABELS[value] || value || '计划中'
}

function paymentTone(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'paid') return 'success'
  if (s === 'partial') return 'info'
  if (s === 'overdue') return 'danger'
  if (s === 'cancelled') return 'neutral'
  return 'warning'
}

function signatureLabel(value) {
  return SIGNATURE_LABELS[value] || value || '待签署'
}

function signatureTone(status) {
  const s = String(status || '').toLowerCase()
  if (s === 'signed') return 'success'
  if (s === 'declined') return 'danger'
  if (s === 'cancelled') return 'neutral'
  return 'warning'
}

function methodLabel(value) {
  return METHOD_LABELS[value] || value || '电子签署'
}

function riskLevelLabel(value) {
  return RISK_LEVEL_LABELS[value] || value || '低'
}

function riskLevelClass(value) {
  return {
    low: 'bg-emerald-50 text-emerald-600',
    medium: 'bg-amber-50 text-amber-600',
    high: 'bg-rose-50 text-rose-600',
    critical: 'bg-rose-100 text-rose-700',
  }[value] || 'bg-ink-100 text-ink-600'
}

function riskLabel(row) {
  const score = Number(row?.risk_score)
  if (Number.isFinite(score) && score >= 80) return '极高'
  if (Number.isFinite(score) && score >= 60) return '高'
  if (Number.isFinite(score) && score >= 30) return '中'
  return '低'
}

function riskClass(row) {
  const score = Number(row?.risk_score)
  return riskLevelClass(score >= 80 ? 'critical' : score >= 60 ? 'high' : score >= 30 ? 'medium' : 'low')
}

async function loadSection(name, path, target) {
  sectionLoading.value = { ...sectionLoading.value, [name]: true }
  sectionErrors.value = { ...sectionErrors.value, [name]: '' }
  try {
    const data = await contractsApi.list(path, { page: 1, page_size: 20 })
    target.value = normalizeList(data).items
  } catch (e) {
    target.value = []
    sectionErrors.value = {
      ...sectionErrors.value,
      [name]: e?.message || '子资源暂不可用',
    }
  } finally {
    sectionLoading.value = { ...sectionLoading.value, [name]: false }
  }
}

async function loadDetail() {
  const id = props.contractId
  if (!id) return
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await contractsApi.get(`contracts/${id}/`)
  } catch (e) {
    detailError.value = e?.message || '合同详情加载失败'
    detail.value = null
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
}

function loadSections() {
  const id = props.contractId
  if (!id) return
  loadSection('parties', `contracts/${id}/parties/`, parties)
  loadSection('versions', `contracts/${id}/versions/`, versions)
  loadSection('obligations', `contracts/${id}/obligations/`, obligations)
  loadSection('milestones', `contracts/${id}/milestones/`, milestones)
  loadSection('payments', `contracts/${id}/payments/`, payments)
  loadSection('signatures', `contracts/${id}/signatures/`, signatures)
  loadSection('risks', `contracts/${id}/risks/`, risks)
}

function reset() {
  detail.value = null
  detailError.value = ''
  parties.value = []
  versions.value = []
  obligations.value = []
  milestones.value = []
  payments.value = []
  signatures.value = []
  risks.value = []
  sectionLoading.value = {
    parties: false,
    versions: false,
    obligations: false,
    milestones: false,
    payments: false,
    signatures: false,
    risks: false,
  }
  sectionErrors.value = {
    parties: '',
    versions: '',
    obligations: '',
    milestones: '',
    payments: '',
    signatures: '',
    risks: '',
  }
}

function reload() {
  loadDetail()
  loadSections()
}

watch(
  () => props.show,
  (open) => {
    if (!open) {
      reset()
      return
    }
    detail.value = props.seed || null
    reload()
  }
)

watch(
  () => props.contractId,
  (next, prev) => {
    if (next && next !== prev && props.show) {
      detail.value = props.seed || null
      reload()
    }
  }
)

watch(
  () => props.reloadToken,
  () => {
    if (props.show) reload()
  }
)

defineExpose({ reload })
</script>