<template>
  <section class="space-y-3">
    <!-- 顶部：待办 / 已办切换与筛选 -->
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <div class="flex items-center gap-1 rounded-control bg-ink-50 p-0.5">
        <button
          v-for="m in MODES"
          :key="m.key"
          type="button"
          class="rounded-control px-3 py-1 text-[12px] transition-colors"
          :class="mode === m.key ? 'bg-white font-medium text-brand-700 shadow-card' : 'text-ink-500 hover:text-ink-700'"
          @click="switchMode(m.key)"
        >
          {{ m.label }}
        </button>
      </div>
      <label class="min-w-[200px] flex-1">
        <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
        <input v-model="q" class="input" type="search" placeholder="按任务名、实例标题或业务单号搜索" />
      </label>
      <label v-if="mode === 'done'" class="w-32">
        <span class="mb-1 block text-[11px] text-ink-400">办理动作</span>
        <select v-model="actionFilter" class="input">
          <option value="">全部动作</option>
          <option v-for="a in ACTION_OPTIONS" :key="a.value" :value="a.value">{{ a.label }}</option>
        </select>
      </label>
      <label v-else class="flex items-center gap-1.5 pb-1.5 text-[12px] text-ink-500">
        <input v-model="onlyOverdue" type="checkbox" />
        仅看逾期
      </label>
      <label class="w-28">
        <span class="mb-1 block text-[11px] text-ink-400">每页</span>
        <select class="input" :value="pageSize" @change="changePageSize($event)">
          <option v-for="n in [10, 15, 30, 50]" :key="n" :value="n">{{ n }} 条</option>
        </select>
      </label>
      <button class="btn-primary" @click="reload">查询</button>
      <button class="btn-ghost" :disabled="loading" @click="reload">刷新</button>
      <button class="btn-ghost ml-auto" :disabled="scanning" @click="scanSla">
        {{ scanning ? '扫描中…' : '逾期标记扫描' }}
      </button>
    </div>

    <div v-if="batchFeedback" class="flex items-start gap-2 rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
      <span class="min-w-0 flex-1">{{ batchFeedback }}</span>
      <button class="shrink-0 text-ink-400" @click="batchFeedback = ''">关闭</button>
    </div>

    <!-- 批量操作条 -->
    <div
      v-if="mode === 'pending' && selected.length"
      class="flex flex-wrap items-center gap-2 rounded-control border border-brand-200 bg-brand-50 px-3 py-2 text-[12px] text-brand-700"
    >
      <span>已选择 {{ selected.length }} 条待办</span>
      <button class="btn-primary px-2 text-[12px]" @click="openBatch">批量同意</button>
      <button class="btn-ghost px-2 text-[12px]" @click="selected = []">清空选择</button>
      <span class="ml-auto text-[11px] text-brand-600">批量办理逐条独立事务，失败条目会单独提示</span>
    </div>

    <!-- 列表 -->
    <div class="card overflow-hidden">
      <div v-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div
        v-else-if="error"
        class="m-3 flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="font-medium" @click="reload">重试</button>
      </div>
      <div v-else-if="!visibleItems.length" class="py-12 text-center text-[12px] text-ink-400">
        {{ emptyText }}
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1000px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th v-if="mode === 'pending'" class="th w-8">
                <input type="checkbox" :checked="allChecked" @change="toggleAll" />
              </th>
              <th class="th">任务 / 实例</th>
              <th class="th">节点</th>
              <th class="th">优先级</th>
              <th class="th">状态</th>
              <th class="th">办理人</th>
              <th class="th">{{ mode === 'pending' ? '办理截止' : '完成时间' }}</th>
              <th class="th">{{ mode === 'pending' ? '操作' : '办理结果' }}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="task in visibleItems" :key="task.id" class="hover:bg-ink-50/50">
              <td v-if="mode === 'pending'" class="td">
                <input
                  type="checkbox"
                  :checked="selected.includes(task.id)"
                  @change="toggleOne(task.id)"
                />
              </td>
              <td class="td">
                <div class="max-w-[280px]">
                  <div class="flex items-center gap-1.5">
                    <span class="truncate font-medium text-ink-800">{{ task.name }}</span>
                    <span
                      v-if="overdueOf(task)"
                      class="tag shrink-0 bg-rose-50 text-rose-600"
                    >已逾期</span>
                  </div>
                  <div class="truncate text-[11px] text-ink-400">
                    {{ task.business_no || '—' }} · {{ task.instance_title || '未命名实例' }}
                  </div>
                </div>
              </td>
              <td class="td text-[12px] text-ink-500">{{ task.node_name || '—' }}</td>
              <td class="td">
                <span class="tag" :class="priorityClass(task.priority)">{{ priorityLabel(task.priority) }}</span>
              </td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(task.status))">{{ taskStatusLabel(task.status) }}</span>
              </td>
              <td class="td text-[12px] text-ink-500">
                <span v-if="task.assignee">{{ task.assignee.name || task.assignee.username }}</span>
                <span v-else class="tag bg-amber-50 text-amber-600">待认领</span>
              </td>
              <td class="td text-[12px] text-ink-500">
                {{ mode === 'pending' ? formatDate(task.due_at, true) : formatDate(task.completed_at, true) }}
              </td>
              <td class="td whitespace-nowrap">
                <template v-if="mode === 'pending'">
                  <button
                    v-if="task.status === 'pending'"
                    class="btn-ghost px-1.5 text-[12px]"
                    :disabled="busyId === task.id"
                    @click="claimTask(task)"
                  >认领</button>
                  <button class="btn-ghost px-1.5 text-[12px] text-brand-600" @click="openComplete(task)">
                    办理
                  </button>
                  <button class="btn-ghost px-1.5 text-[12px]" @click="openAssign(task, 'delegate')">委派</button>
                  <button class="btn-ghost px-1.5 text-[12px]" @click="openAssign(task, 'transfer')">转办</button>
                  <button class="btn-ghost px-1.5 text-[12px]" @click="focusTask(task)">详情</button>
                </template>
                <template v-else>
                  <div class="flex flex-wrap items-center gap-1">
                    <span class="tag" :class="actionClass(task.action)">{{ actionLabel(task.action) }}</span>
                    <span class="max-w-[220px] truncate text-[11px] text-ink-400" :title="task.comment">
                      {{ task.comment || '无意见' }}
                    </span>
                  </div>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
        <span>共 {{ formatNumber(total) }} 条 · 第 {{ page }} / {{ pages }} 页</span>
        <span class="flex items-center gap-1">
          <button class="btn-ghost px-2 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <button class="btn-ghost px-2 text-[12px]" :disabled="page >= pages || loading" @click="goPage(page + 1)">下一页</button>
        </span>
      </div>
    </div>

    <!-- 办理弹窗 -->
    <Modal :show="completeOpen" title="办理任务" width="600px" @close="completeOpen = false">
      <div class="space-y-3">
        <div v-if="taskDetailLoading" class="py-6 text-center text-[12px] text-ink-400">加载任务详情…</div>
        <template v-else>
          <div class="rounded-control bg-ink-50 px-3 py-2 text-[12px]">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-ink-800">{{ completeTarget?.name }}</span>
              <span class="tag">{{ completeTarget?.node_name || '任务节点' }}</span>
              <span v-if="overdueOf(completeTarget)" class="tag bg-rose-50 text-rose-600">已逾期</span>
            </div>
            <div class="mt-1 text-[11px] text-ink-500">
              实例：{{ completeTarget?.business_no }} · {{ completeTarget?.instance_title }}
            </div>
            <div v-if="taskDetail?.instance" class="mt-0.5 text-[11px] text-ink-500">
              当前节点：{{ taskDetail.instance.current_node?.name || '—' }} ·
              发起人：{{ taskDetail.instance.starter?.name || taskDetail.instance.starter?.username || '—' }}
            </div>
          </div>

          <div v-if="taskDetail?.payload && Object.keys(taskDetail.payload).length" class="rounded-control border border-ink-100 px-3 py-2">
            <div class="mb-1 text-[11px] text-ink-400">提交数据</div>
            <pre class="max-h-[120px] overflow-auto whitespace-pre-wrap break-all text-[11px] text-ink-600">{{ payloadText }}</pre>
          </div>

          <div class="flex flex-wrap gap-2">
            <button
              v-for="a in COMPLETE_ACTIONS"
              :key="a.value"
              type="button"
              class="rounded-control border px-3 py-1 text-[12px]"
              :class="completeForm.action === a.value ? a.active : 'border-ink-200 text-ink-600 hover:border-brand-300'"
              @click="completeForm.action = a.value"
            >{{ a.label }}</button>
          </div>

          <label v-if="completeForm.action === 'return'" class="block">
            <span class="mb-1 block text-[11px] text-ink-400">退回目标节点标识（可选）</span>
            <input v-model.trim="completeForm.targetNodeKey" class="input font-mono" placeholder="如 dept_review，留空则退回上一节点" />
          </label>

          <label class="block">
            <span class="mb-1 block text-[11px] text-ink-400">办理意见</span>
            <textarea
              v-model="completeForm.comment"
              class="input min-h-[76px]"
              :placeholder="completeForm.action === 'approve' ? '同意理由（可选）' : '请说明原因，后端可能要求必填'"
            ></textarea>
          </label>

          <div class="flex justify-end gap-2">
            <button class="btn-ghost" @click="completeOpen = false">取消</button>
            <button class="btn-primary" :disabled="busy" @click="submitComplete">
              {{ busy ? '提交中…' : '提交办理' }}
            </button>
          </div>
        </template>
      </div>
    </Modal>

    <!-- 委派 / 转办 -->
    <Modal :show="assignOpen" :title="assignForm.kind === 'delegate' ? '委派任务' : '转办任务'" width="480px" @close="assignOpen = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">
          {{ assignForm.kind === 'delegate'
            ? '委派后保留原候选集，受托人可办理，你仍可接管。'
            : '转办后候选集替换为目标用户，你将不再看到该任务。' }}
        </p>
        <div class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
          {{ assignForm.task?.name }} · {{ assignForm.task?.business_no }}
        </div>
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-400">目标用户 ID</span>
          <input v-model.trim="assignForm.targetUserId" class="input" inputmode="numeric" placeholder="如 12" />
          <span class="mt-0.5 block text-[11px] text-ink-400">按平台用户 ID 指派，后端会校验用户是否存在</span>
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-400">说明（可选）</span>
          <textarea v-model="assignForm.comment" class="input min-h-[60px]" placeholder="委派/转办原因"></textarea>
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="assignOpen = false">取消</button>
          <button class="btn-primary" :disabled="busy" @click="submitAssign">
            {{ busy ? '提交中…' : '确认' }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 批量同意 -->
    <Modal :show="batchOpen" title="批量办理待办" width="480px" @close="batchOpen = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">将对已选择的 {{ selected.length }} 条待办执行「同意」，逐条独立事务。</p>
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-400">统一办理意见（可选）</span>
          <textarea v-model="batchComment" class="input min-h-[64px]" placeholder="批量同意说明"></textarea>
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="batchOpen = false">取消</button>
          <button class="btn-primary" :disabled="busy" @click="submitBatch">
            {{ busy ? '提交中…' : '确认批量办理' }}
          </button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import {
  formatDate,
  formatNumber,
  statusTone,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  /** 父级刷新计数：变化时重新拉取列表 */
  refreshKey: { type: Number, default: 0 },
})

const app = useAppStore()
const api = apiFor('workflow')

const MODES = [
  { key: 'pending', label: '我的待办' },
  { key: 'done', label: '我的已办' },
]

const ACTION_OPTIONS = [
  { value: 'approve', label: '同意' },
  { value: 'reject', label: '拒绝' },
  { value: 'return', label: '退回' },
  { value: 'add_sign', label: '加签' },
  { value: 'complete', label: '完成' },
]

const COMPLETE_ACTIONS = [
  {
    value: 'approve',
    label: '同意',
    active: 'border-emerald-300 bg-emerald-50 text-emerald-700',
  },
  {
    value: 'reject',
    label: '拒绝',
    active: 'border-rose-300 bg-rose-50 text-rose-700',
  },
  {
    value: 'return',
    label: '退回',
    active: 'border-amber-300 bg-amber-50 text-amber-700',
  },
]

const TASK_STATUS = {
  pending: '待认领',
  claimed: '处理中',
  completed: '已完成',
  cancelled: '已取消',
  expired: '已过期',
}

const PRIORITY = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}

const mode = ref('pending')
const items = ref([])
const loading = ref(false)
const error = ref('')
const q = ref('')
const actionFilter = ref('')
const onlyOverdue = ref(false)
const page = ref(1)
const pageSize = ref(15)
const total = ref(0)
const selected = ref([])
const busy = ref(false)
const busyId = ref(0)
const scanning = ref(false)
const batchFeedback = ref('')

const completeOpen = ref(false)
const completeTarget = ref(null)
const taskDetail = ref(null)
const taskDetailLoading = ref(false)
const completeForm = reactive({ action: 'approve', comment: '', targetNodeKey: '' })

const assignOpen = ref(false)
const assignForm = reactive({ kind: 'delegate', targetUserId: '', comment: '', task: null })

const batchOpen = ref(false)
const batchComment = ref('')

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

const visibleItems = computed(() => {
  if (mode.value !== 'pending' || !onlyOverdue.value) return items.value
  return items.value.filter((task) => overdueOf(task))
})

const allChecked = computed(
  () => visibleItems.value.length > 0 && visibleItems.value.every((task) => selected.value.includes(task.id))
)

const emptyText = computed(() => {
  if (mode.value === 'done') return '还没有办理记录，处理待办后会出现在这里'
  if (onlyOverdue.value) return '当前没有逾期任务，SLA 状态良好'
  return '暂无待办任务，新的审批会实时进入候选池'
})

const payloadText = computed(() => {
  try {
    return JSON.stringify(taskDetail.value?.payload || {}, null, 2)
  } catch (e) {
    return '—'
  }
})

function taskStatusLabel(value) {
  return TASK_STATUS[value] || value || '未知'
}

function priorityLabel(value) {
  return PRIORITY[value] || value || '普通'
}

function priorityClass(value) {
  if (value === 'urgent') return 'bg-rose-50 text-rose-600'
  if (value === 'high') return 'bg-amber-50 text-amber-600'
  if (value === 'low') return 'bg-ink-100 text-ink-500'
  return 'bg-ink-50 text-ink-600'
}

function actionLabel(value) {
  return ACTION_OPTIONS.find((a) => a.value === value)?.label || value || '—'
}

function actionClass(value) {
  if (value === 'approve' || value === 'complete') return 'bg-emerald-50 text-emerald-600'
  if (value === 'reject') return 'bg-rose-50 text-rose-600'
  if (value === 'return') return 'bg-amber-50 text-amber-600'
  return 'bg-ink-100 text-ink-600'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function overdueOf(task) {
  if (!task) return false
  if (task.is_overdue) return true
  if (task.status === 'completed' || task.status === 'cancelled') return false
  if (!task.due_at) return false
  const at = new Date(task.due_at).getTime()
  return Number.isFinite(at) && at < Date.now()
}

async function load() {
  if (!api) {
    error.value = '流程引擎接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const path = mode.value === 'pending' ? 'tasks/my-pending/' : 'tasks/my-done/'
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (mode.value === 'done' && actionFilter.value) params.action = actionFilter.value
    const data = await api.list(path, params)
    // 端点不可用（405/404）时保持空态并提示，不白屏
    items.value = data.items || []
    total.value = data.count || 0
    selected.value = selected.value.filter((id) => items.value.some((task) => task.id === id))
  } catch (e) {
    items.value = []
    total.value = 0
    error.value = e?.message || '待办加载失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function goPage(next) {
  page.value = Math.min(Math.max(1, next), pages.value)
  load()
}

function changePageSize(event) {
  pageSize.value = Number(event.target.value) || 15
  page.value = 1
  load()
}

function switchMode(next) {
  if (mode.value === next) return
  mode.value = next
  selected.value = []
  batchFeedback.value = ''
  page.value = 1
  load()
}

function toggleOne(id) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id]
}

function toggleAll() {
  selected.value = allChecked.value ? [] : visibleItems.value.map((task) => task.id)
}

let qTimer = null
watch(q, () => {
  if (qTimer) clearTimeout(qTimer)
  qTimer = setTimeout(() => {
    page.value = 1
    load()
  }, 320)
})
watch(actionFilter, () => {
  page.value = 1
  load()
})
watch(onlyOverdue, () => {
  selected.value = []
})

watch(
  () => props.refreshKey,
  () => {
    load()
  }
)

async function claimTask(task) {
  busyId.value = task.id
  try {
    await api.post(`tasks/${task.id}/claim/`)
    app.toastMsg('已认领，任务进入处理中', 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '认领失败', 'error')
  } finally {
    busyId.value = 0
  }
}

async function focusTask(task) {
  completeTarget.value = task
  completeForm.action = 'approve'
  completeForm.comment = ''
  completeForm.targetNodeKey = ''
  completeOpen.value = true
  taskDetail.value = null
  taskDetailLoading.value = true
  try {
    taskDetail.value = await api.get(`tasks/${task.id}/`)
  } catch (e) {
    app.toastMsg(e?.message || '任务详情加载失败', 'error')
  } finally {
    taskDetailLoading.value = false
  }
}

async function openComplete(task) {
  await focusTask(task)
}

async function submitComplete() {
  if (!completeTarget.value) return
  busy.value = true
  try {
    const payload = {
      action: completeForm.action,
      comment: completeForm.comment,
    }
    if (completeForm.action === 'return' && completeForm.targetNodeKey) {
      payload.target_node_key = completeForm.targetNodeKey
    }
    await api.post(`tasks/${completeTarget.value.id}/complete/`, payload)
    app.toastMsg('任务办理完成', 'success')
    completeOpen.value = false
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '办理失败', 'error')
  } finally {
    busy.value = false
  }
}

function openAssign(task, kind) {
  assignForm.kind = kind
  assignForm.targetUserId = ''
  assignForm.comment = ''
  assignForm.task = task
  assignOpen.value = true
}

async function submitAssign() {
  const task = assignForm.task
  if (!task) return
  if (!assignForm.targetUserId) {
    app.toastMsg('请填写目标用户 ID', 'error')
    return
  }
  busy.value = true
  try {
    const path = assignForm.kind === 'delegate' ? 'delegate' : 'transfer'
    await api.post(`tasks/${task.id}/${path}/`, {
      target_user_id: Number(assignForm.targetUserId) || assignForm.targetUserId,
      comment: assignForm.comment,
    })
    app.toastMsg(assignForm.kind === 'delegate' ? '已委派' : '已转办', 'success')
    assignOpen.value = false
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    busy.value = false
  }
}

function openBatch() {
  if (!selected.value.length) return
  batchComment.value = ''
  batchOpen.value = true
}

async function submitBatch() {
  if (!selected.value.length) return
  busy.value = true
  try {
    const result = await api.post('tasks/batch-complete/', {
      task_ids: selected.value,
      action: 'approve',
      comment: batchComment.value,
    })
    const success = Number(result?.success_count) || 0
    const failed = Number(result?.failed_count) || 0
    batchFeedback.value = failed
      ? `批量办理完成：成功 ${success} 条，失败 ${failed} 条。${result?.failed?.[0]?.error || ''}`
      : `批量办理完成：成功 ${success} 条`
    app.toastMsg(failed ? `成功 ${success} 条，失败 ${failed} 条` : '批量办理成功', failed ? 'error' : 'success')
    batchOpen.value = false
    selected.value = []
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '批量办理失败', 'error')
  } finally {
    busy.value = false
  }
}

async function scanSla() {
  scanning.value = true
  try {
    const result = await api.post('monitor/sla-scan/', { limit: 500 })
    const counts = result?.counts || {}
    const summary = `扫描任务 ${counts.scanned_tasks ?? 0} 条，新标记逾期 ${counts.newly_overdue ?? 0} 条，提醒 ${counts.reminders ?? 0} 条`
    batchFeedback.value = `SLA 扫描完成：${summary}`
    app.toastMsg('逾期标记扫描完成', 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '逾期扫描失败', 'error')
  } finally {
    scanning.value = false
  }
}

onMounted(() => {
  load()
})
</script>