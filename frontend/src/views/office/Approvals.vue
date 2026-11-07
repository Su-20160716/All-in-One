<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 标题 + 操作 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">审批中心</h2>
        <p class="text-[12px] text-ink-400">待我审 / 我发起双列表，点击行打开详情抽屉查看流转记录并处理</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="tag-brand">待我审 {{ pendingCount }}</span>
        <button class="btn-outline" :disabled="scanning" @click="scanOverdue">
          {{ scanning ? '扫描中…' : '⏱ 超时扫描' }}
        </button>
        <button class="btn-outline" :disabled="loadingPending || loadingSubmitted" @click="loadAll">↻ 刷新</button>
      </div>
    </div>

    <!-- 页签 -->
    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="t in TABS"
        :key="t.key"
        class="rounded-pill px-3 py-1 text-[12px] transition-colors"
        :class="tab === t.key ? 'bg-brand-600 text-white' : 'bg-white text-ink-600 border border-ink-200 hover:border-brand-300'"
        @click="switchTab(t.key)"
      >
        {{ t.label }}
        <span class="ml-1 text-[11px]" :class="tab === t.key ? 'text-white/80' : 'text-ink-400'">
          {{ t.key === 'pending' ? pendingCount : submittedCount }}
        </span>
      </button>
      <!-- 我发起：状态筛选 -->
      <span v-if="tab === 'submitted'" class="ml-1 flex flex-wrap gap-1">
        <button
          v-for="s in STATUS_FILTERS"
          :key="s.value || 'all'"
          class="rounded-pill px-2 py-0.5 text-[11px]"
          :class="statusFilter === s.value ? 'bg-ink-700 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
          @click="setStatusFilter(s.value)"
        >
          {{ s.label }}
        </button>
      </span>
    </div>

    <!-- 列表 -->
    <div class="card p-4">
      <div v-if="currentLoading && !currentItems.length" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="currentError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1 truncate">{{ currentError }}</span>
        <button class="shrink-0 font-medium" @click="reloadCurrent">重试</button>
      </div>
      <div v-else-if="!currentItems.length" class="py-10 text-center text-[12px] text-ink-400">
        {{ tab === 'pending' ? '暂无待我审批的单据' : '还没有发起过审批' }}
      </div>
      <div v-else class="divide-y divide-ink-50">
        <button
          v-for="it in currentItems"
          :key="it.id"
          class="flex w-full flex-wrap items-center gap-2 py-2 text-left transition-colors hover:bg-ink-50/70"
          @click="openDetail(it)"
        >
          <span class="tag shrink-0">{{ typeLabel(it.data?.type) }}</span>
          <span class="min-w-0 flex-1 truncate text-[13px] text-ink-800">{{ it.title }}</span>
          <span v-if="it.data?.urgency === 'urgent'" class="tag shrink-0 bg-rose-50 text-rose-600">加急</span>
          <span v-if="isOverdue(it)" class="tag shrink-0 bg-rose-50 text-rose-600">
            超时 {{ waitingHours(it) }}h
          </span>
          <span v-if="it.data?.urge_count" class="tag shrink-0 bg-amber-50 text-amber-600">
            已催 {{ it.data.urge_count }}
          </span>
          <span class="shrink-0 text-[11px] text-ink-400">{{ it.owner || '—' }}</span>
          <span class="w-28 shrink-0 text-right text-[11px] text-ink-400">{{ fmtDT(it.created_at) }}</span>
          <span class="tag shrink-0" :class="statusClass(it.status)">{{ statusLabel(it.status) }}</span>
        </button>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <div v-if="detailItem" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="closeDrawer"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[540px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="tag">{{ typeLabel(detailItem.data?.type) }}</span>
              <span class="tag" :class="statusClass(detailItem.status)">{{ statusLabel(detailItem.status) }}</span>
              <span v-if="isOverdue(detailItem)" class="tag bg-rose-50 text-rose-600">已超时</span>
            </div>
            <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">{{ detailItem.title }}</h3>
          </div>
          <button class="shrink-0 text-ink-400 hover:text-ink-600" aria-label="关闭详情" @click="closeDrawer">✕</button>
        </div>

        <div class="flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <div class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12px]">
            <div class="text-ink-400">发起人</div>
            <div class="text-ink-700">{{ detailItem.owner || '—' }}</div>
            <div class="text-ink-400">提交时间</div>
            <div class="text-ink-700">{{ fmtDT(detailItem.created_at) }}</div>
            <div class="text-ink-400">指定审批人</div>
            <div class="text-ink-700">{{ detailItem.data?.approver || '按数据范围' }}</div>
            <div class="text-ink-400">已等待</div>
            <div class="text-ink-700">{{ waitingHours(detailItem) }} 小时</div>
            <div v-if="detailItem.remark" class="text-ink-400">说明</div>
            <div v-if="detailItem.remark" class="text-ink-700">{{ detailItem.remark }}</div>
            <template v-for="kv in detailPairs" :key="kv.key">
              <div class="text-ink-400">{{ kv.key }}</div>
              <div class="break-all text-ink-700">{{ kv.value }}</div>
            </template>
          </div>

          <div>
            <div class="mb-1.5 flex items-center justify-between">
              <span class="text-[13px] font-medium text-ink-700">流转记录</span>
              <button class="text-[11px] text-brand-600" @click="loadEvents">刷新</button>
            </div>
            <div v-if="eventsLoading" class="py-3 text-center text-[12px] text-ink-400">加载中…</div>
            <div v-else-if="eventsError" class="rounded-control bg-rose-50 px-2 py-2 text-[11px] text-rose-600">
              <div class="truncate">{{ eventsError }}</div>
              <button class="mt-1 font-medium" @click="loadEvents">重试</button>
            </div>
            <div v-else-if="!events.length" class="py-3 text-center text-[12px] text-ink-400">暂无流转记录</div>
            <div v-else class="relative space-y-2.5 pl-4">
              <div class="absolute bottom-1 left-[3px] top-1 w-px bg-ink-100"></div>
              <div v-for="(ev, i) in events" :key="i" class="relative">
                <span
                  class="absolute -left-4 top-1.5 h-2 w-2 rounded-full"
                  :class="i === events.length - 1 ? 'bg-brand-500' : 'bg-ink-200'"
                ></span>
                <div class="flex items-center gap-2 text-[12px]">
                  <span class="font-medium text-ink-700">{{ actionLabel(ev.action) }}</span>
                  <span class="text-[11px] text-ink-400">{{ ev.by }}</span>
                  <span class="ml-auto text-[11px] text-ink-300">{{ fmtDT(ev.at) }}</span>
                </div>
                <div v-if="ev.note" class="text-[11px] text-ink-500">备注：{{ ev.note }}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 操作区 -->
        <div v-if="detailItem.status === 'pending'" class="border-t border-ink-100 px-4 py-3">
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">
              {{ tab === 'pending' ? '审批意见（驳回时必填）' : '催办留言（可选）' }}
            </span>
            <textarea v-model="note" class="input h-16 resize-none" maxlength="500" placeholder="填写意见 / 理由"></textarea>
          </label>
          <div class="mt-2 flex flex-wrap justify-end gap-2">
            <button class="btn-outline" :disabled="acting" @click="doUrge">催办</button>
            <template v-if="tab === 'pending'">
              <button class="btn-outline !text-rose-600" :disabled="acting" @click="doReject">驳回</button>
              <button class="btn-primary" :disabled="acting" @click="doApprove">通过</button>
            </template>
          </div>
        </div>
        <div v-else class="border-t border-ink-100 px-4 py-3 text-[12px] text-ink-400">
          该单据当前状态为「{{ statusLabel(detailItem.status) }}」，不可再流转。
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { officex } from '../../api/officex'
import { useAppStore } from '../../stores/app'

const app = useAppStore()

const TABS = [
  { key: 'pending', label: '待我审' },
  { key: 'submitted', label: '我发起' },
]
const STATUS_FILTERS = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待审' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
  { value: 'cancelled', label: '已撤回' },
]
const TYPE_LABELS = {
  leave: '请假',
  expense: '报销',
  purchase: '采购',
  overtime: '加班',
  seal: '用印',
  travel: '出差',
  custom: '自定义',
}
const STATUS_LABELS = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已驳回',
  cancelled: '已撤回',
}
const ACTION_LABELS = {
  submit: '提交',
  approve: '通过',
  reject: '驳回',
  cancel: '撤回',
  comment: '评论',
  urge: '催办',
  overdue: '超时提醒',
}
const typeLabel = (t) => TYPE_LABELS[t] || '自定义'
const statusLabel = (s) => STATUS_LABELS[s] || s || '—'
const actionLabel = (a) => ACTION_LABELS[a] || a || '操作'
function statusClass(s) {
  return {
    pending: 'bg-amber-50 text-amber-600',
    approved: 'bg-emerald-50 text-emerald-600',
    rejected: 'bg-rose-50 text-rose-600',
    cancelled: 'bg-ink-100 text-ink-500',
  }[s] || ''
}

const pad = (n) => String(n).padStart(2, '0')
function fmtDT(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function waitingHours(it) {
  if (!it?.created_at) return 0
  const d = new Date(it.created_at)
  if (isNaN(d.getTime())) return 0
  return Math.max(0, Math.round((Date.now() - d.getTime()) / 3600000))
}
// 362：挂起超 24 小时，或后端已写过 overdue 事件
function isOverdue(it) {
  if (it?.status !== 'pending') return false
  const hasEvent = (it.data?.events || []).some((e) => e.action === 'overdue')
  return hasEvent || waitingHours(it) >= 24
}

const tab = ref('pending')
const statusFilter = ref('')
const pendingItems = ref([])
const submittedItems = ref([])
const pendingCount = ref(0)
const submittedCount = ref(0)
const loadingPending = ref(false)
const loadingSubmitted = ref(false)
const pendingError = ref('')
const submittedError = ref('')

const currentItems = computed(() => (tab.value === 'pending' ? pendingItems.value : submittedItems.value))
const currentLoading = computed(() => (tab.value === 'pending' ? loadingPending.value : loadingSubmitted.value))
const currentError = computed(() => (tab.value === 'pending' ? pendingError.value : submittedError.value))

async function loadPending() {
  loadingPending.value = true
  pendingError.value = ''
  try {
    const r = await officex.approvalPending()
    pendingItems.value = r?.items || []
    pendingCount.value = r?.count ?? pendingItems.value.length
  } catch (e) {
    pendingError.value = e?.message || '待我审加载失败'
    app.toastMsg(pendingError.value, 'error')
  } finally {
    loadingPending.value = false
  }
}
async function loadSubmitted() {
  loadingSubmitted.value = true
  submittedError.value = ''
  try {
    const r = await officex.approvalSubmitted(statusFilter.value ? { status: statusFilter.value } : {})
    submittedItems.value = r?.items || []
    submittedCount.value = r?.count ?? submittedItems.value.length
  } catch (e) {
    submittedError.value = e?.message || '我发起的审批加载失败'
    app.toastMsg(submittedError.value, 'error')
  } finally {
    loadingSubmitted.value = false
  }
}
async function loadAll() {
  await Promise.allSettled([loadPending(), loadSubmitted()])
}
function reloadCurrent() {
  if (tab.value === 'pending') loadPending()
  else loadSubmitted()
}
function switchTab(key) {
  tab.value = key
  closeDrawer()
  if (key === 'pending') loadPending()
  else loadSubmitted()
}
function setStatusFilter(v) {
  statusFilter.value = v
  loadSubmitted()
}

// ---------------- 详情抽屉 ----------------
const detailItem = ref(null)
const events = ref([])
const eventsLoading = ref(false)
const eventsError = ref('')
const note = ref('')
const acting = ref(false)

const detailPairs = computed(() => {
  const d = detailItem.value?.data?.detail
  if (!d || typeof d !== 'object') return []
  return Object.entries(d).map(([key, value]) => ({
    key,
    value: value && typeof value === 'object' ? JSON.stringify(value) : String(value ?? ''),
  }))
})

async function openDetail(it) {
  detailItem.value = it
  note.value = ''
  events.value = []
  eventsError.value = ''
  await loadEvents()
}
function closeDrawer() {
  detailItem.value = null
  events.value = []
  note.value = ''
}
async function loadEvents() {
  if (!detailItem.value) return
  eventsLoading.value = true
  eventsError.value = ''
  try {
    const r = await officex.approvalEvents(detailItem.value.id)
    events.value = r?.events || []
  } catch (e) {
    eventsError.value = e?.message || '流转记录加载失败'
    app.toastMsg(eventsError.value, 'error')
  } finally {
    eventsLoading.value = false
  }
}

async function afterAction(msg) {
  app.toastMsg(msg, 'success')
  closeDrawer()
  await loadAll()
}

async function doApprove() {
  if (!detailItem.value) return
  acting.value = true
  try {
    await officex.approvalApprove(detailItem.value.id, note.value.trim())
    await afterAction('已通过该审批')
  } catch (e) {
    app.toastMsg(e?.message || '审批失败', 'error')
  } finally {
    acting.value = false
  }
}
async function doReject() {
  if (!detailItem.value) return
  const reason = note.value.trim()
  if (!reason) return app.toastMsg('驳回必须填写理由', 'warn')
  acting.value = true
  try {
    await officex.approvalReject(detailItem.value.id, reason)
    await afterAction('已驳回该审批')
  } catch (e) {
    app.toastMsg(e?.message || '驳回失败', 'error')
  } finally {
    acting.value = false
  }
}
async function doUrge() {
  if (!detailItem.value) return
  acting.value = true
  try {
    const r = await officex.approvalUrge(detailItem.value.id, note.value.trim())
    app.toastMsg(`已催办（第 ${r?.urge_count ?? 1} 次）`, 'success')
    note.value = ''
    await loadEvents()
    await loadPending()
    // 同步抽屉里的催办次数
    const fresh = pendingItems.value.find((x) => x.id === detailItem.value?.id)
    if (fresh) detailItem.value = fresh
  } catch (e) {
    app.toastMsg(e?.message || '催办失败', 'error')
  } finally {
    acting.value = false
  }
}

// ---------------- 超时扫描（362） ----------------
const scanning = ref(false)
async function scanOverdue() {
  scanning.value = true
  try {
    const r = await officex.approvalOverdueCheck(24)
    app.toastMsg(`扫描 ${r?.scanned ?? 0} 条，超时 ${r?.overdue ?? 0} 条，已通知 ${r?.notified ?? 0} 人`, 'success')
    await loadAll()
  } catch (e) {
    app.toastMsg(e?.message || '超时扫描失败', 'error')
  } finally {
    scanning.value = false
  }
}

function onKey(e) {
  if (e.key === 'Escape' && detailItem.value) closeDrawer()
}

onMounted(() => {
  document.addEventListener('keydown', onKey)
  loadAll()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>
