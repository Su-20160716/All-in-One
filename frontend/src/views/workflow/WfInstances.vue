<template>
  <section class="space-y-3">
    <!-- 筛选条 -->
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <label class="min-w-[220px] flex-1">
        <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
        <input v-model="q" class="input" type="search" placeholder="按业务单号、标题或流程名称搜索" />
      </label>
      <label class="w-32">
        <span class="mb-1 block text-[11px] text-ink-400">状态</span>
        <select v-model="status" class="input">
          <option value="">全部状态</option>
          <option v-for="s in STATUS_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
      </label>
      <label class="w-28">
        <span class="mb-1 block text-[11px] text-ink-400">优先级</span>
        <select v-model="priority" class="input">
          <option value="">全部</option>
          <option v-for="p in PRIORITY_OPTIONS" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </label>
      <label class="flex items-center gap-1.5 pb-1.5 text-[12px] text-ink-500">
        <input v-model="onlyOverdue" type="checkbox" />
        仅看逾期
      </label>
      <label class="w-28">
        <span class="mb-1 block text-[11px] text-ink-400">每页</span>
        <select class="input" :value="pageSize" @change="changePageSize($event)">
          <option v-for="n in [10, 20, 50]" :key="n" :value="n">{{ n }} 条</option>
        </select>
      </label>
      <button class="btn-primary" @click="reload">查询</button>
      <button class="btn-ghost" :disabled="loading" @click="reload">刷新</button>
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
      <div v-else-if="!items.length" class="py-12 text-center text-[12px] text-ink-400">
        没有匹配的流程实例，调整筛选条件或先发起一个流程
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[1040px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th">业务单号 / 标题</th>
              <th class="th">流程</th>
              <th class="th">状态</th>
              <th class="th">当前节点</th>
              <th class="th">优先级</th>
              <th class="th">发起人</th>
              <th class="th">开始时间</th>
              <th class="th">已运行</th>
              <th class="th">未结任务</th>
              <th class="th">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr
              v-for="row in items"
              :key="row.id"
              class="cursor-pointer hover:bg-ink-50/50"
              @click="openDrawer(row)"
            >
              <td class="td">
                <div class="max-w-[250px]">
                  <div class="flex items-center gap-1.5">
                    <span class="truncate font-medium text-ink-800">{{ row.title || '未命名实例' }}</span>
                    <span v-if="row.is_overdue" class="tag shrink-0 bg-rose-50 text-rose-600">逾期</span>
                  </div>
                  <div class="truncate font-mono text-[11px] text-ink-400">{{ row.business_no }}</div>
                </div>
              </td>
              <td class="td max-w-[180px] truncate text-[12px] text-ink-500">
                {{ row.definition_name || '—' }}
                <span class="text-ink-300">v{{ row.version_no }}</span>
              </td>
              <td class="td">
                <span class="tag" :class="tagClass(statusTone(row.status))">{{ statusLabel(row.status) }}</span>
              </td>
              <td class="td text-[12px] text-ink-500">{{ row.current_node?.name || '—' }}</td>
              <td class="td">
                <span class="tag" :class="priorityClass(row.priority)">{{ priorityLabel(row.priority) }}</span>
              </td>
              <td class="td text-[12px] text-ink-500">
                {{ row.starter?.name || row.starter?.username || '—' }}
              </td>
              <td class="td text-[12px] text-ink-500">{{ formatDate(row.started_at, true) }}</td>
              <td class="td text-[12px] text-ink-500">{{ durationText(row.duration_minutes) }}</td>
              <td class="td text-[12px]" :class="row.open_task_count ? 'text-amber-600' : 'text-ink-400'">
                {{ row.open_task_count }} / {{ row.task_count }}
              </td>
              <td class="td whitespace-nowrap" @click.stop>
                <button class="btn-ghost px-1.5 text-[12px]" @click="openDrawer(row)">详情</button>
                <button
                  v-if="row.status === 'running'"
                  class="btn-ghost px-1.5 text-[12px] text-amber-600"
                  @click="openAction(row, 'cancel')"
                >取消</button>
                <button
                  v-if="row.status === 'running'"
                  class="btn-ghost px-1.5 text-[12px] text-rose-500"
                  @click="openAction(row, 'terminate')"
                >终止</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-3 py-2 text-[12px] text-ink-500">
        <span>共 {{ formatNumber(total) }} 个实例 · 第 {{ page }} / {{ pages }} 页</span>
        <span class="flex items-center gap-1">
          <button class="btn-ghost px-2 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <button class="btn-ghost px-2 text-[12px]" :disabled="page >= pages || loading" @click="goPage(page + 1)">下一页</button>
        </span>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <div v-if="drawerOpen" class="fixed inset-0 z-[95] flex justify-end">
      <div class="absolute inset-0 bg-ink-900/40" @click="closeDrawer"></div>
      <aside class="relative z-10 flex h-full w-full max-w-[660px] flex-col bg-white shadow-pop">
        <div class="flex items-start justify-between gap-3 border-b border-ink-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="tag" :class="tagClass(statusTone(current?.status))">{{ statusLabel(current?.status) }}</span>
              <span class="tag" :class="priorityClass(current?.priority)">{{ priorityLabel(current?.priority) }}</span>
              <span v-if="current?.is_overdue" class="tag bg-rose-50 text-rose-600">已逾期</span>
            </div>
            <h3 class="mt-1 truncate text-[15px] font-semibold text-ink-900">{{ current?.title || '实例详情' }}</h3>
            <p class="truncate font-mono text-[11px] text-ink-400">{{ current?.business_no }}</p>
          </div>
          <button class="shrink-0 text-ink-400 hover:text-ink-600" aria-label="关闭详情" @click="closeDrawer">✕</button>
        </div>

        <div class="flex flex-wrap items-center gap-1 border-b border-ink-100 px-4 py-2">
          <button
            v-for="t in DRAWER_TABS"
            :key="t.key"
            type="button"
            class="rounded-pill px-2.5 py-0.5 text-[12px]"
            :class="drawerTab === t.key ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
            @click="switchDrawerTab(t.key)"
          >{{ t.label }}</button>
          <button class="btn-ghost ml-auto px-2 text-[12px]" :disabled="!current" @click="reloadCurrent">刷新</button>
        </div>

        <div class="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          <div v-if="detailLoading && !detail" class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
          <div v-else-if="detailError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <div class="truncate">{{ detailError }}</div>
            <button class="mt-1 font-medium" @click="loadDetail(current?.id)">重试</button>
          </div>
          <template v-else>
            <!-- 概览信息始终展示 -->
            <div class="rounded-control bg-ink-50 px-3 py-2">
              <div class="grid grid-cols-2 gap-x-3 gap-y-1 text-[12px]">
                <div class="text-ink-400">流程</div>
                <div class="text-ink-700">{{ detail?.definition?.name || current?.definition_name || '—' }}</div>
                <div class="text-ink-400">分类</div>
                <div class="text-ink-700">{{ detail?.category || current?.category || '通用' }}</div>
                <div class="text-ink-400">当前节点</div>
                <div class="text-ink-700">{{ detail?.current_node?.name || current?.current_node?.name || '—' }}</div>
                <div class="text-ink-400">发起人</div>
                <div class="text-ink-700">{{ detail?.starter?.name || detail?.starter?.username || '—' }}</div>
                <div class="text-ink-400">负责人</div>
                <div class="text-ink-700">{{ detail?.owner?.name || detail?.owner?.username || '—' }}</div>
                <div class="text-ink-400">开始时间</div>
                <div class="text-ink-700">{{ formatDate(detail?.started_at, true) }}</div>
                <div class="text-ink-400">截止时间</div>
                <div class="text-ink-700">{{ formatDate(detail?.due_at, true) }}</div>
                <div class="text-ink-400">完成时间</div>
                <div class="text-ink-700">{{ formatDate(detail?.finished_at, true) }}</div>
                <div class="text-ink-400">耗时</div>
                <div class="text-ink-700">{{ durationText(detail?.duration_minutes || current?.duration_minutes) }}</div>
              </div>
              <div class="mt-2">
                <div class="flex items-center justify-between text-[11px] text-ink-400">
                  <span>流程进度</span>
                  <span>{{ Number(detail?.progress_pct || 0).toFixed(0) }}%</span>
                </div>
                <div class="mt-1 h-1.5 overflow-hidden rounded-pill bg-ink-200">
                  <div
                    class="h-full rounded-pill bg-brand-500 transition-all"
                    :style="{ width: `${Math.min(100, Number(detail?.progress_pct) || 0)}%` }"
                  ></div>
                </div>
              </div>
            </div>

            <!-- 时间线 -->
            <div v-if="drawerTab === 'timeline'">
              <div v-if="timelineLoading" class="py-6 text-center text-[12px] text-ink-400">加载中…</div>
              <div v-else-if="timelineError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
                <div class="truncate">{{ timelineError }}</div>
                <button class="mt-1 font-medium" @click="loadTimeline(current?.id)">重试</button>
              </div>
              <div v-else-if="!timeline.length" class="py-6 text-center text-[12px] text-ink-400">暂无流转事件</div>
              <div v-else class="relative space-y-2.5 pl-4">
                <div class="absolute bottom-1 left-[3px] top-1 w-px bg-ink-100"></div>
                <div v-for="(ev, i) in timeline" :key="`${ev.at}-${i}`" class="relative">
                  <span
                    class="absolute -left-4 top-1.5 h-2 w-2 rounded-full"
                    :class="i === 0 ? 'bg-brand-500' : 'bg-ink-200'"
                  ></span>
                  <div class="flex flex-wrap items-center gap-1.5 text-[12px]">
                    <span class="tag" :class="kindClass(ev.kind)">{{ kindLabel(ev.kind) }}</span>
                    <span class="min-w-0 flex-1 truncate text-ink-800">{{ ev.title }}</span>
                    <span class="text-[11px] text-ink-400">{{ formatDate(ev.at, true) }}</span>
                  </div>
                  <div class="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
                    <span v-if="ev.actor">操作人 {{ ev.actor }}</span>
                    <span v-if="ev.from_status || ev.to_status">{{ ev.from_status || '—' }} → {{ ev.to_status || '—' }}</span>
                    <span v-if="ev.duration_ms">耗时 {{ ev.duration_ms }} ms</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 变量 -->
            <div v-else-if="drawerTab === 'variables'">
              <div v-if="variablesLoading" class="py-6 text-center text-[12px] text-ink-400">加载中…</div>
              <div v-else-if="variablesError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
                <div class="truncate">{{ variablesError }}</div>
                <button class="mt-1 font-medium" @click="loadVariables(current?.id)">重试</button>
              </div>
              <div v-else-if="!variables.length" class="py-6 text-center text-[12px] text-ink-400">该实例还没有变量</div>
              <table v-else class="w-full">
                <thead class="border-b border-ink-100 bg-ink-50/50">
                  <tr>
                    <th class="th">变量名</th>
                    <th class="th">值</th>
                    <th class="th">类型</th>
                    <th class="th">更新时间</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="v in variables" :key="v.id">
                    <td class="td font-mono text-[12px]">
                      {{ v.key }}
                      <span v-if="v.is_secret" class="tag ml-1 bg-amber-50 text-amber-600">敏感</span>
                    </td>
                    <td class="td max-w-[220px] break-all text-[12px] text-ink-600">{{ valueText(v.value) }}</td>
                    <td class="td text-[12px] text-ink-500">{{ v.var_type }}</td>
                    <td class="td text-[11px] text-ink-400">{{ formatDate(v.updated_at, true) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- 任务 -->
            <div v-else-if="drawerTab === 'tasks'">
              <div v-if="tasksLoading" class="py-6 text-center text-[12px] text-ink-400">加载中…</div>
              <div v-else-if="tasksError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
                <div class="truncate">{{ tasksError }}</div>
                <button class="mt-1 font-medium" @click="loadTasks(current?.id)">重试</button>
              </div>
              <div v-else-if="!tasks.length" class="py-6 text-center text-[12px] text-ink-400">暂无任务记录</div>
              <ul v-else class="space-y-1">
                <li
                  v-for="task in tasks"
                  :key="task.id"
                  class="rounded-control border border-ink-100 px-2 py-1.5 text-[12px]"
                >
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="tag" :class="tagClass(statusTone(task.status))">{{ taskStatusLabel(task.status) }}</span>
                    <span class="min-w-0 flex-1 truncate text-ink-800">{{ task.name }}</span>
                    <span class="text-[11px] text-ink-400">{{ task.node_name }}</span>
                  </div>
                  <div class="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
                    <span>办理人 {{ task.assignee?.name || task.assignee?.username || '待认领' }}</span>
                    <span>截止 {{ formatDate(task.due_at, true) }}</span>
                    <span v-if="task.completed_at">完成 {{ formatDate(task.completed_at, true) }}</span>
                    <span v-if="task.is_overdue" class="text-rose-500">已逾期</span>
                  </div>
                </li>
              </ul>
            </div>

            <!-- 审计日志 -->
            <div v-else-if="drawerTab === 'audit'">
              <div v-if="auditLoading" class="py-6 text-center text-[12px] text-ink-400">加载中…</div>
              <div v-else-if="auditError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
                <div class="truncate">{{ auditError }}</div>
                <button class="mt-1 font-medium" @click="loadAudit(current?.id)">重试</button>
              </div>
              <div v-else-if="!audit.length" class="py-6 text-center text-[12px] text-ink-400">暂无审计日志</div>
              <table v-else class="w-full">
                <thead class="border-b border-ink-100 bg-ink-50/50">
                  <tr>
                    <th class="th">动作</th>
                    <th class="th">操作人</th>
                    <th class="th">状态变化</th>
                    <th class="th">耗时</th>
                    <th class="th">时间</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="log in audit" :key="log.id">
                    <td class="td font-mono text-[11px] text-ink-600">{{ log.action }}</td>
                    <td class="td text-[12px] text-ink-600">{{ log.actor_name || log.actor?.name || '系统' }}</td>
                    <td class="td text-[11px] text-ink-500">
                      {{ log.from_status || '—' }} → {{ log.to_status || '—' }}
                    </td>
                    <td class="td text-[11px] text-ink-400">{{ log.duration_ms ? `${log.duration_ms} ms` : '—' }}</td>
                    <td class="td text-[11px] text-ink-400">{{ formatDate(log.created_at, true) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
        </div>

        <div class="flex flex-wrap items-center justify-end gap-2 border-t border-ink-100 px-4 py-2.5">
          <button class="btn-ghost text-[12px]" @click="closeDrawer">关闭</button>
          <button
            class="btn-danger text-[12px]"
            :disabled="current?.status !== 'running'"
            @click="openAction(current, 'cancel')"
          >取消实例</button>
          <button
            class="btn-danger text-[12px]"
            :disabled="current?.status !== 'running'"
            @click="openAction(current, 'terminate')"
          >终止实例</button>
        </div>
      </aside>
    </div>

    <!-- 取消 / 终止确认 -->
    <Modal
      :show="actionOpen"
      :title="actionKind === 'cancel' ? '取消流程实例' : '终止流程实例'"
      width="480px"
      @close="actionOpen = false"
    >
      <div class="space-y-3">
        <p class="text-[12px] text-ink-600">
          {{ actionKind === 'cancel'
            ? '取消后实例停止流转，未结任务会被关闭，可在审计日志中追溯。'
            : '终止是管理动作，必须填写原因，只有流程所有者或管理员可以执行。' }}
        </p>
        <div class="rounded-control bg-ink-50 px-3 py-2 text-[12px] text-ink-600">
          {{ actionTarget?.business_no }} · {{ actionTarget?.title }}
        </div>
        <label class="block">
          <span class="mb-1 block text-[11px] text-ink-400">原因{{ actionKind === 'terminate' ? '（必填）' : '（可选）' }}</span>
          <textarea v-model="actionReason" class="input min-h-[64px]" placeholder="说明取消/终止原因"></textarea>
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="actionOpen = false">取消</button>
          <button
            class="btn-danger"
            :disabled="actionBusy || (actionKind === 'terminate' && !actionReason.trim())"
            @click="submitAction"
          >{{ actionBusy ? '提交中…' : '确认' }}</button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
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

const STATUS_OPTIONS = [
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'rejected', label: '已拒绝' },
  { value: 'cancelled', label: '已取消' },
  { value: 'terminated', label: '已终止' },
]

const PRIORITY_OPTIONS = [
  { value: 'low', label: '低' },
  { value: 'normal', label: '普通' },
  { value: 'high', label: '高' },
  { value: 'urgent', label: '紧急' },
]

const DRAWER_TABS = [
  { key: 'timeline', label: '时间线' },
  { key: 'variables', label: '变量' },
  { key: 'tasks', label: '任务' },
  { key: 'audit', label: '审计日志' },
]

const TASK_STATUS = {
  pending: '待认领',
  claimed: '处理中',
  completed: '已完成',
  cancelled: '已取消',
  expired: '已过期',
}

const items = ref([])
const loading = ref(false)
const error = ref('')
const q = ref('')
const status = ref('')
const priority = ref('')
const onlyOverdue = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const drawerOpen = ref(false)
const current = ref(null)
const drawerTab = ref('timeline')
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const timeline = ref([])
const timelineLoading = ref(false)
const timelineError = ref('')
const variables = ref([])
const variablesLoading = ref(false)
const variablesError = ref('')
const tasks = ref([])
const tasksLoading = ref(false)
const tasksError = ref('')
const audit = ref([])
const auditLoading = ref(false)
const auditError = ref('')

const actionOpen = ref(false)
const actionKind = ref('cancel')
const actionTarget = ref(null)
const actionReason = ref('')
const actionBusy = ref(false)

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

function statusLabel(value) {
  return STATUS_OPTIONS.find((s) => s.value === value)?.label || value || '未知'
}

function taskStatusLabel(value) {
  return TASK_STATUS[value] || value || '未知'
}

function priorityLabel(value) {
  return PRIORITY_OPTIONS.find((p) => p.value === value)?.label || value || '普通'
}

function priorityClass(value) {
  if (value === 'urgent') return 'bg-rose-50 text-rose-600'
  if (value === 'high') return 'bg-amber-50 text-amber-600'
  if (value === 'low') return 'bg-ink-100 text-ink-500'
  return 'bg-ink-50 text-ink-600'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function kindLabel(kind) {
  return {
    audit: '审计',
    comment: '评论',
    notification: '通知',
    snapshot: '快照',
  }[kind] || '事件'
}

function kindClass(kind) {
  if (kind === 'comment') return 'bg-brand-50 text-brand-700'
  if (kind === 'notification') return 'bg-amber-50 text-amber-600'
  if (kind === 'snapshot') return 'bg-ink-100 text-ink-600'
  return 'bg-emerald-50 text-emerald-600'
}

function durationText(minutes) {
  const n = Number(minutes)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n < 60) return `${n.toFixed(0)} 分钟`
  if (n < 1440) return `${(n / 60).toFixed(1)} 小时`
  return `${(n / 1440).toFixed(1)} 天`
}

function valueText(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch (e) {
      return '—'
    }
  }
  return String(value)
}

async function load() {
  if (!api) {
    error.value = '流程引擎接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (status.value) params.status = status.value
    if (priority.value) params.priority = priority.value
    if (onlyOverdue.value) params.overdue = true
    const data = await api.list('instances/', params)
    items.value = data.items || []
    total.value = data.count || 0
  } catch (e) {
    items.value = []
    total.value = 0
    error.value = e?.message || '实例列表加载失败'
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
  pageSize.value = Number(event.target.value) || 20
  page.value = 1
  load()
}

let qTimer = null
watch(q, () => {
  if (qTimer) clearTimeout(qTimer)
  qTimer = setTimeout(() => {
    page.value = 1
    load()
  }, 320)
})
watch([status, priority, onlyOverdue], () => {
  page.value = 1
  load()
})

watch(
  () => props.refreshKey,
  () => {
    load()
  }
)

async function openDrawer(row) {
  drawerOpen.value = true
  current.value = row
  drawerTab.value = 'timeline'
  detail.value = null
  detailError.value = ''
  timeline.value = []
  variables.value = []
  tasks.value = []
  audit.value = []
  await Promise.all([loadDetail(row.id), loadTimeline(row.id)])
}

function closeDrawer() {
  drawerOpen.value = false
  current.value = null
  detail.value = null
  detailError.value = ''
  timeline.value = []
  variables.value = []
  tasks.value = []
  audit.value = []
}

async function loadDetail(id) {
  if (!id) return
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await api.get(`instances/${id}/`)
  } catch (e) {
    detail.value = null
    detailError.value = e?.message || '实例详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

async function loadTimeline(id) {
  if (!id) return
  timelineLoading.value = true
  timelineError.value = ''
  try {
    const data = await api.get(`instances/${id}/timeline/?limit=120`)
    timeline.value = data?.items || []
  } catch (e) {
    timeline.value = []
    timelineError.value = e?.message || '时间线加载失败'
  } finally {
    timelineLoading.value = false
  }
}

async function loadVariables(id) {
  if (!id) return
  variablesLoading.value = true
  variablesError.value = ''
  try {
    const data = await api.list(`instances/${id}/variables/`, { page: 1, page_size: 50 })
    variables.value = data.items || []
  } catch (e) {
    variables.value = []
    variablesError.value = e?.message || '变量加载失败'
  } finally {
    variablesLoading.value = false
  }
}

async function loadTasks(id) {
  if (!id) return
  tasksLoading.value = true
  tasksError.value = ''
  try {
    const data = await api.list('tasks/', { instance_id: id, page: 1, page_size: 30 })
    tasks.value = data.items || []
  } catch (e) {
    tasks.value = []
    tasksError.value = e?.message || '任务列表加载失败'
  } finally {
    tasksLoading.value = false
  }
}

async function loadAudit(id) {
  if (!id) return
  auditLoading.value = true
  auditError.value = ''
  try {
    const data = await api.list(`instances/${id}/audit/`, { page: 1, page_size: 40 })
    audit.value = data.items || []
  } catch (e) {
    audit.value = []
    auditError.value = e?.message || '审计日志加载失败'
  } finally {
    auditLoading.value = false
  }
}

function switchDrawerTab(key) {
  drawerTab.value = key
  const id = current.value?.id
  if (!id) return
  if (key === 'variables' && !variables.value.length) loadVariables(id)
  if (key === 'tasks' && !tasks.value.length) loadTasks(id)
  if (key === 'audit' && !audit.value.length) loadAudit(id)
}

async function reloadCurrent() {
  const id = current.value?.id
  if (!id) return
  await loadDetail(id)
  if (drawerTab.value === 'timeline') await loadTimeline(id)
  if (drawerTab.value === 'variables') await loadVariables(id)
  if (drawerTab.value === 'tasks') await loadTasks(id)
  if (drawerTab.value === 'audit') await loadAudit(id)
}

function openAction(row, kind) {
  if (!row) return
  actionKind.value = kind
  actionTarget.value = row
  actionReason.value = ''
  actionOpen.value = true
}

async function submitAction() {
  const row = actionTarget.value
  if (!row) return
  actionBusy.value = true
  try {
    await api.post(`instances/${row.id}/${actionKind.value}/`, { reason: actionReason.value })
    app.toastMsg(actionKind.value === 'cancel' ? '实例已取消' : '实例已终止', 'success')
    actionOpen.value = false
    await load()
    if (current.value?.id === row.id) {
      await loadDetail(row.id)
      await loadTimeline(row.id)
    }
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    actionBusy.value = false
  }
}

onMounted(() => {
  load()
})
</script>