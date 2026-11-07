<template>
  <section class="space-y-3">
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <input v-model="q" class="input w-52" placeholder="搜索任务名称 / cron / 报表" />
      <select v-model="reportFilter" class="input w-56">
        <option value="">全部报表</option>
        <option v-for="r in reports" :key="r.id" :value="r.id">{{ r.name }}（{{ r.code }}）</option>
      </select>
      <select v-model="enabledFilter" class="input w-28">
        <option value="">全部状态</option>
        <option value="true">已启用</option>
        <option value="false">已停用</option>
      </select>
      <span class="tag">共 {{ count }} 个</span>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <button class="btn-ghost" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
        <button class="btn-primary" @click="openCreate">新建计划任务</button>
      </div>
    </div>

    <div class="card p-0">
      <div class="border-b border-ink-100 px-4 py-2.5">
        <h3 class="text-[14px] font-semibold text-ink-800">计划任务</h3>
        <p class="mt-0.5 text-[11px] text-ink-400">
          cron 与时区在保存时校验并计算下次运行时间；「立即运行」会执行报表并把结果写回任务状态。
        </p>
      </div>

      <div v-if="loading && !items.length" class="space-y-2 p-4">
        <div v-for="n in 5" :key="`sk-${n}`" class="h-9 animate-pulse rounded-control bg-ink-50"></div>
      </div>
      <div v-else-if="unavailable" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800">
        <span class="min-w-0 flex-1">{{ unavailable }}。已降级为空态。</span>
        <button class="font-medium text-brand-600" @click="load">重试</button>
      </div>
      <div v-else-if="error" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-rose-50 px-3 py-2.5 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ error }}</span>
        <button class="font-medium" @click="load">重试</button>
      </div>
      <div v-else-if="!items.length" class="px-4 py-12 text-center">
        <p class="text-[13px] text-ink-500">{{ hasFilters ? '当前筛选条件下没有计划任务' : '还没有创建计划任务' }}</p>
        <p class="mt-1 text-[11px] text-ink-400">配置 cron、时区与收件人后，外部调度器会拉取到期任务并触发报表执行。</p>
        <button class="btn-primary mt-3" @click="openCreate">新建计划任务</button>
      </div>
      <div v-else class="overflow-auto">
        <table class="w-full min-w-[1100px]">
          <thead class="bg-ink-50">
            <tr>
              <th class="th">任务 / 报表</th>
              <th class="th w-48">cron</th>
              <th class="th w-20">状态</th>
              <th class="th w-36">下次运行</th>
              <th class="th w-36">上次运行</th>
              <th class="th w-20 text-right">次数</th>
              <th class="th w-48">收件人</th>
              <th class="th w-64">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in items" :key="row.id" class="hover:bg-ink-50/50">
              <td class="td">
                <button class="block max-w-[240px] truncate text-left text-[13px] font-medium text-ink-800 hover:text-brand-600" @click="openHistory(row)">
                  {{ row.name || `${row.report_name || '报表'} 定时任务` }}
                </button>
                <div class="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-ink-400">
                  <span class="max-w-[180px] truncate">{{ row.report_name || '—' }}</span>
                  <span v-if="row.last_status" class="tag" :class="statusClass(row.last_status)">{{ statusLabel(row.last_status) }}</span>
                </div>
              </td>
              <td class="td">
                <span class="block font-mono text-[11px] text-ink-700">{{ row.cron_expr }}</span>
                <span class="text-[10px] text-ink-400">{{ row.timezone }}</span>
              </td>
              <td class="td">
                <span class="tag" :class="row.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-ink-100 text-ink-500'">
                  {{ row.enabled ? '已启用' : '已停用' }}
                </span>
              </td>
              <td class="td text-[11px]" :class="row.enabled ? 'text-ink-600' : 'text-ink-300'">
                {{ row.enabled ? fmtDT(row.next_run_at) : '未启用' }}
              </td>
              <td class="td text-[11px] text-ink-500">{{ fmtDT(row.last_run_at) }}</td>
              <td class="td text-right tabular-nums">{{ row.run_count ?? 0 }}</td>
              <td class="td">
                <div class="flex flex-wrap gap-1">
                  <span v-for="r in (row.recipients || []).slice(0, 2)" :key="r" class="tag max-w-[140px] truncate" :title="r">{{ r }}</span>
                  <span v-if="(row.recipients || []).length > 2" class="tag">+{{ row.recipients.length - 2 }}</span>
                  <span v-if="!(row.recipients || []).length" class="text-[10px] text-ink-400">未配置</span>
                </div>
              </td>
              <td class="td">
                <div class="flex flex-wrap gap-x-2.5 gap-y-1 text-[11px]">
                  <button class="text-brand-600 hover:underline" @click="openEdit(row)">编辑</button>
                  <button class="text-brand-600 hover:underline" :disabled="runningId === row.id" @click="toggleSchedule(row)">
                    {{ row.enabled ? '停用' : '启用' }}
                  </button>
                  <button class="text-emerald-600 hover:underline" :disabled="runningId === row.id" @click="runNow(row)">
                    {{ runningId === row.id ? '执行中…' : '立即运行' }}
                  </button>
                  <button class="text-ink-500 hover:text-brand-600" @click="openHistory(row)">执行历史</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="count > 0" class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-4 py-2.5 text-[12px] text-ink-500">
        <span>第 {{ page }} / {{ totalPages }} 页，共 {{ count }} 条</span>
        <div class="flex items-center gap-1">
          <button class="btn-outline px-2 py-0.5" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <button class="btn-outline px-2 py-0.5" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑 -->
    <Modal :show="formOpen" :title="form.id ? '编辑计划任务' : '新建计划任务'" width="720px" @close="formOpen = false">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">报表 <span class="text-rose-500">*</span></span>
            <select v-model="form.report_id" class="input">
              <option value="">选择报表</option>
              <option v-for="r in reports" :key="r.id" :value="r.id">{{ r.name }}（{{ r.code }}）</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">任务名称</span>
            <input v-model="form.name" class="input" placeholder="留空则使用报表名" />
          </label>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">cron 表达式 <span class="text-rose-500">*</span></span>
            <input v-model="form.cron_expr" class="input font-mono" placeholder="0 9 * * 1-5" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">时区</span>
            <input v-model="form.timezone" class="input font-mono" list="schedule-timezones" placeholder="Asia/Shanghai" />
            <datalist id="schedule-timezones">
              <option v-for="tz in TIMEZONES" :key="tz" :value="tz" />
            </datalist>
          </label>
        </div>

        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-[11px] text-ink-400">常用：</span>
          <button
            v-for="preset in CRON_PRESETS"
            :key="preset.cron"
            class="rounded-pill bg-ink-50 px-2 py-0.5 text-[11px] text-ink-600 hover:bg-brand-50 hover:text-brand-700"
            @click="form.cron_expr = preset.cron"
          >{{ preset.label }}</button>
        </div>

        <div class="rounded-control border border-ink-100 bg-ink-50/60 p-3 text-[11px]">
          <div class="flex items-center gap-2">
            <span class="font-medium text-ink-700">cron 预览</span>
            <span v-if="cronPreview.loading" class="text-ink-400">校验中…</span>
            <span v-else-if="cronPreview.error" class="text-rose-600">{{ cronPreview.error }}</span>
            <span v-else-if="cronPreview.data?.description" class="text-ink-500">{{ cronPreview.data.description }}</span>
          </div>
          <ul v-if="cronPreview.data?.upcoming?.length" class="mt-1.5 space-y-0.5 text-ink-500">
            <li v-for="(time, idx) in cronPreview.data.upcoming" :key="time">
              第 {{ idx + 1 }} 次：{{ fmtDT(time) }}
            </li>
          </ul>
          <p v-else-if="!cronPreview.loading && !cronPreview.error" class="mt-1 text-ink-400">
            输入合法的 cron 后自动展示未来 5 次运行时间。
          </p>
        </div>

        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">收件人（逗号分隔的邮箱或用户名）</span>
          <input v-model="form.recipientsText" class="input" placeholder="ops@example.com, finance@example.com" />
        </label>

        <label class="flex items-center gap-2 text-[12px] text-ink-600">
          <input v-model="form.enabled" type="checkbox" />
          保存后立即启用（启用时会计算下次运行时间）
        </label>

        <div v-if="formError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ formError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="formOpen = false">取消</button>
          <button class="btn-primary" :disabled="saving" @click="saveSchedule">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </Modal>

    <!-- 执行历史 -->
    <Modal :show="historyOpen" :title="`执行历史：${historyTarget?.name || historyTarget?.report_name || ''}`" width="960px" @close="historyOpen = false">
      <div class="space-y-3">
        <div v-if="historyLoading && !historyRuns.length" class="py-10 text-center text-[12px] text-ink-400">执行历史加载中…</div>
        <div v-else-if="historyError" class="flex flex-wrap items-center gap-2 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ historyError }}</span>
          <button class="font-medium" @click="reloadHistory">重试</button>
        </div>
        <template v-else>
          <div class="grid gap-2 rounded-control border border-ink-100 bg-ink-50/50 p-3 text-[11px] sm:grid-cols-3">
            <div>
              <div class="text-ink-400">cron</div>
              <div class="mt-0.5 font-mono text-ink-700">{{ historyDetail?.cron_expr || historyTarget?.cron_expr || '—' }}</div>
            </div>
            <div>
              <div class="text-ink-400">时区</div>
              <div class="mt-0.5 text-ink-700">{{ historyDetail?.timezone || historyTarget?.timezone || '—' }}</div>
            </div>
            <div>
              <div class="text-ink-400">下次运行</div>
              <div class="mt-0.5 text-ink-700">{{ fmtDT(historyDetail?.next_run_at || historyTarget?.next_run_at) }}</div>
            </div>
            <div>
              <div class="text-ink-400">上次运行</div>
              <div class="mt-0.5 text-ink-700">{{ fmtDT(historyDetail?.last_run_at || historyTarget?.last_run_at) }}</div>
            </div>
            <div>
              <div class="text-ink-400">累计运行</div>
              <div class="mt-0.5 text-ink-700">{{ historyDetail?.run_count ?? historyTarget?.run_count ?? 0 }} 次</div>
            </div>
            <div>
              <div class="text-ink-400">上次状态</div>
              <div class="mt-0.5">
                <span class="tag" :class="statusClass(historyDetail?.last_status || historyTarget?.last_status)">
                  {{ statusLabel(historyDetail?.last_status || historyTarget?.last_status) }}
                </span>
              </div>
            </div>
          </div>

          <div v-if="historyUpcoming.length" class="rounded-control border border-ink-100 p-3 text-[11px]">
            <div class="mb-1 font-medium text-ink-700">未来运行时间</div>
            <div class="flex flex-wrap gap-2">
              <span v-for="(time, idx) in historyUpcoming" :key="time" class="tag">{{ idx + 1 }}. {{ fmtDT(time) }}</span>
            </div>
          </div>

          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="text-[12px] font-medium text-ink-700">报表执行流水</div>
            <div class="flex items-center gap-2 text-[11px] text-ink-400">
              <span>第 {{ historyPage }} 页</span>
              <button class="text-brand-600" :disabled="historyPage <= 1 || historyRunsLoading" @click="loadHistoryRuns(historyPage - 1)">上一页</button>
              <button class="text-brand-600" :disabled="historyRunsLoading" @click="loadHistoryRuns(historyPage + 1)">下一页</button>
              <button class="text-brand-600" :disabled="historyRunsLoading" @click="loadHistoryRuns(1)">刷新</button>
            </div>
          </div>

          <div v-if="historyRunsLoading" class="py-6 text-center text-[12px] text-ink-400">流水加载中…</div>
          <div v-else-if="!historyRuns.length" class="rounded-control bg-ink-50 px-3 py-6 text-center text-[12px] text-ink-400">
            该报表还没有执行记录
          </div>
          <div v-else class="max-h-72 overflow-auto rounded-control border border-ink-100">
            <table class="w-full min-w-[640px]">
              <thead class="bg-ink-50">
                <tr>
                  <th class="th">开始时间</th>
                  <th class="th w-20">触发</th>
                  <th class="th w-20">状态</th>
                  <th class="th w-24 text-right">耗时</th>
                  <th class="th w-20 text-right">行数</th>
                  <th class="th">错误</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="run in historyRuns" :key="run.id">
                  <td class="td text-[11px]">{{ fmtDT(run.started_at || run.created_at) }}</td>
                  <td class="td"><span class="tag">{{ triggerLabel(run.trigger) }}</span></td>
                  <td class="td"><span class="tag" :class="statusClass(run.status)">{{ statusLabel(run.status) }}</span></td>
                  <td class="td text-right tabular-nums">{{ fmtMs(run.duration_ms) }}</td>
                  <td class="td text-right tabular-nums">{{ run.row_count ?? 0 }}</td>
                  <td class="td">
                    <span v-if="run.error" class="block max-w-[220px] truncate text-[11px] text-rose-500" :title="run.error">{{ run.error }}</span>
                    <span v-else class="text-[11px] text-ink-300">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { reportingApi } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const app = useAppStore()

const TIMEZONES = ['Asia/Shanghai', 'Asia/Tokyo', 'Asia/Singapore', 'UTC', 'Europe/London', 'America/New_York']
const CRON_PRESETS = [
  { label: '每天 09:00', cron: '0 9 * * *' },
  { label: '工作日 09:00', cron: '0 9 * * 1-5' },
  { label: '每周一 09:00', cron: '0 9 * * 1' },
  { label: '每月 1 日 09:00', cron: '0 9 1 * *' },
  { label: '每小时', cron: '0 * * * *' },
]
const TRIGGER_LABELS = {
  manual: '手动',
  schedule: '计划',
  api: '接口',
  cache: '缓存',
  share: '分享',
}

const items = ref([])
const count = ref(0)
const page = ref(1)
const pageSize = ref(20)
const q = ref('')
const reportFilter = ref('')
const enabledFilter = ref('')
const loading = ref(false)
const error = ref('')
const unavailable = ref('')
const reports = ref([])
const runningId = ref(null)

const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref({})
const cronPreview = ref({ loading: false, error: '', data: null })
let cronTimer = null

const historyOpen = ref(false)
const historyTarget = ref(null)
const historyDetail = ref(null)
const historyRuns = ref([])
const historyPage = ref(1)
const historyLoading = ref(false)
const historyRunsLoading = ref(false)
const historyError = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / Math.max(1, pageSize.value))))
const hasFilters = computed(() => Boolean(q.value.trim() || reportFilter.value || enabledFilter.value))
const historyUpcoming = computed(() => {
  const list = historyDetail.value?.upcoming
  return Array.isArray(list) ? list.slice(0, 5) : []
})

function isUnavailable(e) {
  const s = Number(e?.status || e?.response?.status || 0)
  const message = String(e?.message || '')
  return s === 404 || s === 405 || /not found|method not allowed|405/i.test(message)
}

function pad(n) {
  return String(n).padStart(2, '0')
}

function fmtDT(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtMs(value) {
  const n = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '—'
  if (n < 1000) return `${Math.round(n)} ms`
  if (n < 60000) return `${(n / 1000).toFixed(2)} s`
  return `${(n / 60000).toFixed(1)} min`
}

function statusLabel(value) {
  const map = {
    success: '成功',
    failed: '失败',
    running: '执行中',
    pending: '排队中',
    queued: '排队中',
    done: '已完成',
  }
  return map[value] || value || '—'
}

function statusClass(value) {
  if (value === 'success' || value === 'done') return 'bg-emerald-50 text-emerald-700'
  if (value === 'failed') return 'bg-rose-50 text-rose-600'
  if (value === 'running' || value === 'pending' || value === 'queued') return 'bg-amber-50 text-amber-700'
  return 'bg-ink-100 text-ink-600'
}

function triggerLabel(value) {
  return TRIGGER_LABELS[value] || value || '手动'
}

// ---------------------------------------------------------------------------
// 列表
// ---------------------------------------------------------------------------

async function loadReports() {
  if (reports.value.length) return
  try {
    const data = await reportingApi.list('reports/', { page: 1, page_size: 200 })
    reports.value = data.items
  } catch {
    reports.value = []
  }
}

async function load() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  loadReports()
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (reportFilter.value) params.report_id = reportFilter.value
    if (enabledFilter.value) params.enabled = enabledFilter.value === 'true'
    const data = await reportingApi.list('schedules/', params)
    items.value = data.items
    count.value = data.count
  } catch (e) {
    items.value = []
    count.value = 0
    if (isUnavailable(e)) unavailable.value = '计划任务列表接口不可用（404/405）'
    else {
      error.value = e?.message || '计划任务列表加载失败'
      app.toastMsg(error.value, 'error')
    }
  } finally {
    loading.value = false
  }
}

function goPage(next) {
  const target = Math.min(Math.max(1, next), totalPages.value)
  if (target === page.value) return
  page.value = target
  load()
}

watch([q, reportFilter, enabledFilter], () => {
  page.value = 1
  load()
})

// ---------------------------------------------------------------------------
// 新建 / 编辑
// ---------------------------------------------------------------------------

function emptyForm() {
  return {
    id: null,
    report_id: '',
    name: '',
    cron_expr: '0 9 * * 1-5',
    timezone: 'Asia/Shanghai',
    recipientsText: '',
    enabled: false,
  }
}

async function openCreate() {
  await loadReports()
  form.value = emptyForm()
  formError.value = ''
  cronPreview.value = { loading: false, error: '', data: null }
  formOpen.value = true
  previewCron()
}

async function openEdit(row) {
  await loadReports()
  form.value = {
    id: row.id,
    report_id: row.report_id || '',
    name: row.name || '',
    cron_expr: row.cron_expr || '0 9 * * 1-5',
    timezone: row.timezone || 'Asia/Shanghai',
    recipientsText: Array.isArray(row.recipients) ? row.recipients.join(', ') : '',
    enabled: Boolean(row.enabled),
  }
  formError.value = ''
  cronPreview.value = { loading: false, error: '', data: null }
  formOpen.value = true
  previewCron()
}

async function previewCron() {
  const cron = String(form.value.cron_expr || '').trim()
  if (!cron) {
    cronPreview.value = { loading: false, error: '', data: null }
    return
  }
  cronPreview.value = { loading: true, error: '', data: null }
  try {
    const data = await reportingApi.action('cron/preview/', {
      cron,
      timezone: form.value.timezone || 'Asia/Shanghai',
      count: 5,
    })
    cronPreview.value = { loading: false, error: '', data }
  } catch (e) {
    cronPreview.value = { loading: false, error: e?.message || 'cron 不合法', data: null }
  }
}

watch(() => [form.value.cron_expr, form.value.timezone], () => {
  if (!formOpen.value) return
  if (cronTimer) clearTimeout(cronTimer)
  cronTimer = setTimeout(() => {
    cronTimer = null
    previewCron()
  }, 380)
})

async function saveSchedule() {
  const f = form.value
  if (!f.report_id) {
    formError.value = '请选择报表'
    return
  }
  if (!String(f.cron_expr || '').trim()) {
    formError.value = '请填写 cron 表达式'
    return
  }
  const recipients = String(f.recipientsText || '')
    .split(/[,;，；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  saving.value = true
  formError.value = ''
  try {
    const payload = {
      report_id: Number(f.report_id),
      name: f.name || '',
      cron_expr: String(f.cron_expr).trim(),
      timezone: f.timezone || 'Asia/Shanghai',
      recipients,
      enabled: Boolean(f.enabled),
    }
    if (f.id) {
      await reportingApi.update(`schedules/${f.id}/update/`, payload)
      app.toastMsg('计划任务已保存', 'success')
    } else {
      await reportingApi.create('schedules/create/', payload)
      app.toastMsg('计划任务已创建', 'success')
    }
    formOpen.value = false
    await load()
  } catch (e) {
    formError.value = e?.message || '保存失败'
    app.toastMsg(formError.value, 'error')
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------------------
// 启停 / 立即运行
// ---------------------------------------------------------------------------

async function toggleSchedule(row) {
  runningId.value = row.id
  try {
    await reportingApi.action(`schedules/${row.id}/toggle/`, { enabled: !row.enabled })
    app.toastMsg(row.enabled ? '计划任务已停用' : '计划任务已启用', 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '启停失败', 'error')
  } finally {
    runningId.value = null
  }
}

async function runNow(row) {
  runningId.value = row.id
  try {
    const data = await reportingApi.action(`schedules/${row.id}/run-now/`, {})
    const status = data?.status || 'success'
    const duration = fmtMs(data?.duration_ms)
    app.toastMsg(
      status === 'failed' ? '立即运行失败，请查看执行历史' : `立即运行完成（${statusLabel(status)}，耗时 ${duration}）`,
      status === 'failed' ? 'error' : 'success',
    )
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '立即运行失败', 'error')
  } finally {
    runningId.value = null
  }
}

// ---------------------------------------------------------------------------
// 执行历史
// ---------------------------------------------------------------------------

async function openHistory(row) {
  historyTarget.value = row
  historyOpen.value = true
  historyDetail.value = null
  historyRuns.value = []
  historyPage.value = 1
  historyError.value = ''
  await reloadHistory()
}

async function reloadHistory() {
  if (!historyTarget.value) return
  historyLoading.value = true
  historyError.value = ''
  try {
    const detail = await reportingApi.get(`schedules/${historyTarget.value.id}/`)
    historyDetail.value = detail
  } catch (e) {
    if (!isUnavailable(e)) historyError.value = e?.message || '任务详情加载失败'
  }
  await loadHistoryRuns(1)
  historyLoading.value = false
}

async function loadHistoryRuns(pageNo) {
  if (!historyTarget.value) return
  const target = Math.max(1, Number(pageNo) || 1)
  historyRunsLoading.value = true
  try {
    const data = await reportingApi.list('runs/', {
      report_id: historyTarget.value.report_id,
      page: target,
      page_size: 20,
    })
    historyRuns.value = data.items
    historyPage.value = target
    if (!historyError.value) historyError.value = ''
  } catch (e) {
    historyRuns.value = []
    historyError.value = isUnavailable(e)
      ? '执行流水接口不可用（404/405）'
      : (e?.message || '执行流水加载失败')
  } finally {
    historyRunsLoading.value = false
  }
}

watch(() => props.reloadToken, () => {
  load()
  if (historyOpen.value) reloadHistory()
})

onMounted(load)

onBeforeUnmount(() => {
  if (cronTimer) clearTimeout(cronTimer)
})
</script>