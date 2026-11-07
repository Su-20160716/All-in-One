<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 标题 + 周切换 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">日程周视图</h2>
        <p class="text-[12px] text-ink-400">7 × 24 小时网格，点击空白格新建；新建前会自动做冲突检查</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button class="btn-outline" @click="shiftWeek(-1)">◀ 上周</button>
        <button class="btn-ghost" @click="goThisWeek">本周</button>
        <button class="btn-outline" @click="shiftWeek(1)">下周 ▶</button>
        <input
          type="date"
          class="input w-36 py-1"
          :value="weekStart"
          aria-label="选择要查看的周"
          @change="jumpToWeek"
        />
        <button class="btn-outline" :disabled="exporting" @click="exportIcs">
          {{ exporting ? '导出中…' : '⬇ 导出 .ics' }}
        </button>
        <button class="btn-primary" @click="openCreateDefault">＋ 新建日程</button>
      </div>
    </div>

    <div class="card flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 text-[12px] text-ink-600">
      <span>本周：<b class="text-ink-800">{{ weekStart }}</b> ~ <b class="text-ink-800">{{ weekEnd }}</b></span>
      <span>共 <b class="text-brand-600">{{ totalEvents }}</b> 个日程</span>
      <span v-if="!loading && !error && !totalEvents" class="text-ink-400">本周暂无日程，点击网格空白格即可新建</span>
    </div>

    <!-- 错误态 -->
    <div v-if="error" class="card flex items-center gap-3 border-l-4 border-rose-300 p-4">
      <span class="text-[18px]">⚠️</span>
      <div class="min-w-0 flex-1">
        <div class="text-[13px] font-medium text-ink-800">周视图加载失败</div>
        <div class="truncate text-[12px] text-rose-500">{{ error }}</div>
      </div>
      <button class="btn-outline shrink-0" @click="load">重试</button>
    </div>

    <!-- 7×24 网格 -->
    <div v-else class="card overflow-hidden">
      <div v-if="loading && !week" class="py-16 text-center text-[12px] text-ink-400">日程加载中…</div>
      <div v-else class="overflow-auto" style="max-height: 620px">
        <div class="min-w-[860px]">
          <!-- 表头 -->
          <div class="sticky top-0 z-10 flex border-b border-ink-100 bg-white">
            <div class="w-14 shrink-0"></div>
            <div
              v-for="d in days"
              :key="'head-' + d.date"
              class="flex-1 border-l border-ink-50 px-1 py-1.5 text-center"
            >
              <div class="text-[12px] font-medium" :class="isToday(d.date) ? 'text-brand-600' : 'text-ink-700'">
                周{{ d.weekday }}
              </div>
              <div class="text-[11px] text-ink-400">{{ d.date.slice(5) }}</div>
            </div>
          </div>

          <!-- 主体：左侧小时刻度 + 7 天列 -->
          <div class="flex">
            <div class="w-14 shrink-0">
              <div
                v-for="h in HOURS"
                :key="'h-' + h"
                class="h-10 pr-1.5 pt-0.5 text-right text-[10px] leading-none text-ink-300"
              >
                {{ pad(h) }}:00
              </div>
            </div>
            <div
              v-for="d in days"
              :key="'col-' + d.date"
              class="relative flex-1 border-l border-ink-50"
              :style="{ height: HOURS.length * HOUR_H + 'px' }"
            >
              <!-- 空时段：点击新建（键盘可达） -->
              <button
                v-for="h in HOURS"
                :key="'cell-' + h"
                class="block h-10 w-full border-b border-ink-50 text-left transition-colors hover:bg-brand-50/50"
                :aria-label="`在 ${d.date} ${pad(h)}:00 新建日程`"
                @click="openCreate(d.date, h)"
              ></button>
              <!-- 事件块：按 start_at 定位 -->
              <button
                v-for="e in eventsOf(d)"
                :key="'ev-' + e.id"
                class="absolute left-0.5 right-0.5 overflow-hidden rounded-control border px-1 text-left text-[10px] leading-tight transition-colors"
                :class="kindClass(e.kind)"
                :style="boxStyle(e)"
                :title="`${hm(e.start_at)} ${e.title}（${kindLabel(e.kind)}）`"
                @click="openDetail(d.date, e)"
              >
                <span class="block truncate font-medium">{{ hm(e.start_at) }} {{ e.title }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建日程 -->
    <Modal :show="showCreate" title="新建日程" width="560px" @close="closeCreate">
      <div class="space-y-3">
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">标题</span>
          <input v-model="form.title" class="input" placeholder="如：需求评审" maxlength="200" />
        </label>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">开始时间</span>
            <input v-model="form.start" type="datetime-local" class="input" @change="resetConflict" />
          </label>
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">时长</span>
            <select v-model.number="form.duration" class="input" @change="resetConflict">
              <option :value="15">15 分钟</option>
              <option :value="30">30 分钟</option>
              <option :value="60">60 分钟</option>
              <option :value="90">90 分钟</option>
              <option :value="120">120 分钟</option>
            </select>
          </label>
        </div>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">类型</span>
          <select v-model="form.kind" class="input">
            <option value="event">日程</option>
            <option value="meeting">会议</option>
            <option value="review">评审</option>
            <option value="other">其他</option>
          </select>
        </label>

        <div v-if="conflicts.length" class="rounded-control bg-amber-50 p-2.5 text-[12px] text-amber-700">
          <div class="mb-1 font-medium">与 {{ conflicts.length }} 个日程时间重叠</div>
          <div v-for="c in conflicts" :key="c.id" class="truncate">
            {{ hm(c.start_at) }}–{{ hm(c.end_at) || '未设结束' }} {{ c.title }}
            <span v-if="c.owner" class="text-[11px] text-amber-600">（{{ c.owner }}）</span>
          </div>
          <div class="mt-1 text-[11px] text-amber-600">可以调整时间，或再次点击按钮仍然创建。</div>
        </div>

        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeCreate">取消</button>
          <button class="btn-primary" :disabled="saving" @click="submitEvent">
            {{ saving ? '提交中…' : (conflicts.length ? '仍然创建' : '检查并创建') }}
          </button>
        </div>
      </div>
    </Modal>

    <!-- 日程详情 -->
    <Modal :show="showDetail" title="日程详情" width="420px" @close="showDetail = false">
      <div v-if="detail" class="space-y-2 text-[13px] text-ink-700">
        <div class="text-[15px] font-semibold text-ink-900">{{ detail.event.title }}</div>
        <div>时间：{{ detail.date }} {{ hm(detail.event.start_at) }}</div>
        <div>类型：<span class="tag">{{ kindLabel(detail.event.kind) }}</span></div>
        <div class="text-[11px] text-ink-400">详情与参会人可在办公套件日程页维护</div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { officex } from '../../api/officex'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import { saveBlob } from '../../utils/download'

const app = useAppStore()

const pad = (n) => String(n).padStart(2, '0')
const HOUR_H = 40
const HOURS = Array.from({ length: 24 }, (_, i) => i)

function isoDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function addDays(d, n) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}
function mondayOf(d) {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  const wd = (x.getDay() + 6) % 7 // 周一 = 0
  return addDays(x, -wd)
}
function hm(iso) {
  if (!iso) return '--:--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--:--'
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function isToday(date) {
  return date === isoDate(new Date())
}

// ---------------- 周数据 ----------------
const cursor = ref(mondayOf(new Date()))
const week = ref(null)
const loading = ref(false)
const error = ref('')

const weekStart = computed(() => isoDate(cursor.value))
const weekEnd = computed(() => isoDate(addDays(cursor.value, 6)))

const days = computed(() => {
  if (week.value?.days?.length) return week.value.days
  // 接口不可用时也保持 7 列骨架，方便点击重试 / 新建
  return Array.from({ length: 7 }, (_, i) => {
    const d = addDays(cursor.value, i)
    return { date: isoDate(d), weekday: '一二三四五六日'[i], events: [] }
  })
})
const totalEvents = computed(() => days.value.reduce((n, d) => n + (d.events?.length || 0), 0))

async function load() {
  loading.value = true
  error.value = ''
  try {
    week.value = await officex.agendaWeek(weekStart.value)
  } catch (e) {
    week.value = null
    error.value = e?.message || '日程加载失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
  }
}

function shiftWeek(n) {
  cursor.value = addDays(cursor.value, n * 7)
  week.value = null
  load()
}
function goThisWeek() {
  cursor.value = mondayOf(new Date())
  week.value = null
  load()
}
function jumpToWeek(e) {
  const v = e?.target?.value
  if (!v) return
  // 手动解析 YYYY-MM-DD 为本地零点，避免 new Date('YYYY-MM-DD') 按 UTC 解析偏一天
  const [y, m, d] = v.split('-').map(Number)
  if (!y || !m || !d) return
  cursor.value = mondayOf(new Date(y, m - 1, d))
  week.value = null
  load()
}

function eventsOf(day) {
  return day.events || []
}

// ---------------- 事件定位与配色 ----------------
function boxStyle(e) {
  const d = new Date(e.start_at)
  if (isNaN(d.getTime())) return { display: 'none' }
  const startMin = d.getHours() * 60 + d.getMinutes()
  const top = Math.round((startMin / 60) * HOUR_H)
  const maxH = HOURS.length * HOUR_H - top - 1
  const rawH = e.end_at ? Math.round(((new Date(e.end_at) - d) / 3600000) * HOUR_H) : HOUR_H
  const height = Math.max(18, Math.min(maxH, rawH - 2))
  return { top: top + 'px', height: height + 'px' }
}
const KIND_CLASS = {
  event: 'border-brand-200 bg-brand-50 text-brand-700 hover:bg-brand-100',
  meeting: 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100',
  review: 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100',
  other: 'border-ink-200 bg-ink-50 text-ink-600 hover:bg-ink-100',
}
function kindClass(kind) {
  return KIND_CLASS[kind] || KIND_CLASS.other
}
const KIND_LABELS = { event: '日程', meeting: '会议', review: '评审', other: '其他' }
function kindLabel(kind) {
  return KIND_LABELS[kind] || kind || '日程'
}

// ---------------- 新建 / 冲突检查 ----------------
const showCreate = ref(false)
const saving = ref(false)
const conflicts = ref([])
const form = reactive({ title: '', start: '', duration: 60, kind: 'event' })

function defaultStart() {
  const now = new Date()
  const d = addDays(now, 0)
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return `${isoDate(d)}T${pad(d.getHours())}:00`
}

function openCreate(date, hour) {
  form.title = ''
  form.start = `${date}T${pad(hour)}:00`
  form.duration = 60
  form.kind = 'event'
  resetConflict()
  showCreate.value = true
}
function openCreateDefault() {
  form.title = ''
  form.start = defaultStart()
  form.duration = 60
  form.kind = 'event'
  resetConflict()
  showCreate.value = true
}
function closeCreate() {
  showCreate.value = false
}
function resetConflict() {
  conflicts.value = []
}

const endValue = computed(() => {
  if (!form.start) return ''
  const d = new Date(form.start)
  if (isNaN(d.getTime())) return ''
  d.setMinutes(d.getMinutes() + (Number(form.duration) || 0))
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
})

async function submitEvent() {
  if (!form.title.trim()) return app.toastMsg('请填写日程标题', 'warn')
  if (!form.start) return app.toastMsg('请选择开始时间', 'warn')
  if (new Date(endValue.value) <= new Date(form.start)) {
    return app.toastMsg('结束时间必须晚于开始时间', 'warn')
  }
  saving.value = true
  try {
    // 首次提交先做冲突预检；有冲突时提示，再点一次才真正创建
    if (!conflicts.value.length) {
      const c = await officex.conflictCheck({ start_at: form.start, end_at: endValue.value })
      if (c?.has_conflict) {
        conflicts.value = c.conflicts || []
        app.toastMsg('该时段与其他日程重叠，请确认', 'warn')
        return
      }
    }
    const r = await officex.createEvent({
      title: form.title.trim(),
      start_at: form.start,
      end_at: endValue.value,
      kind: form.kind,
    })
    app.toastMsg(r?.has_conflict ? `已创建（与 ${r.conflict_count} 个日程重叠）` : '日程已创建', r?.has_conflict ? 'warn' : 'success')
    showCreate.value = false
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '创建失败', 'error')
  } finally {
    saving.value = false
  }
}

// ---------------- 详情 ----------------
const showDetail = ref(false)
const detail = ref(null)
function openDetail(date, event) {
  detail.value = { date, event }
  showDetail.value = true
}

// ---------------- 导出 .ics（359） ----------------
const exporting = ref(false)
async function exportIcs() {
  exporting.value = true
  try {
    const blob = await officex.exportIcs(weekStart.value, weekEnd.value)
    saveBlob(blob instanceof Blob ? blob : new Blob([blob], { type: 'text/calendar;charset=utf-8' }), `日程-${weekStart.value}.ics`)
    app.toastMsg('已导出本周日程 (.ics)', 'success')
  } catch (e) {
    // 二进制流被网关改写等场景：回落到后端导出地址新窗口打开
    try {
      window.open(officex.exportIcsUrl(weekStart.value, weekEnd.value), '_blank', 'noopener')
      app.toastMsg(e?.message ? `导出失败：${e.message}，已打开导出地址` : '已在新窗口打开导出地址', 'warn')
    } catch {
      app.toastMsg(e?.message || '导出失败', 'error')
    }
  } finally {
    exporting.value = false
  }
}

onMounted(load)
</script>
