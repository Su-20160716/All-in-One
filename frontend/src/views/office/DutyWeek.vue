<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 标题 + 周导航 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">值班排班周视图</h2>
        <p class="text-[12px] text-ink-400">按周查看 7 天排班，管理我的班次与添加排班</p>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn-outline" @click="shiftWeek(-1)">◀ 上周</button>
        <button class="btn-ghost" @click="goThisWeek">本周</button>
        <button class="btn-outline" @click="shiftWeek(1)">下周 ▶</button>
        <button class="btn-primary" @click="openAdd">＋ 添加班次</button>
      </div>
    </div>

    <!-- 周范围 + 我的班次概览 -->
    <div class="card flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
      <div class="text-[13px] text-ink-700">
        当前周：<b>{{ week.week_start }}</b> 起
      </div>
      <div class="text-[13px] text-ink-600">我即将到来的班次：<b class="text-brand-700">{{ myUpcoming }}</b></div>
    </div>

    <!-- 7 天网格 -->
    <div class="grid gap-2 md:grid-cols-7">
      <div v-for="d in week.days" :key="d.date" class="card min-h-[140px] p-2.5"
        :class="isToday(d.date) ? 'ring-2 ring-brand-400' : ''">
        <div class="flex items-center justify-between border-b border-ink-100 pb-1.5">
          <span class="text-[12px] font-semibold text-ink-700">周{{ d.weekday }}</span>
          <span class="text-[11px] text-ink-400">{{ shortDate(d.date) }}</span>
        </div>
        <div v-if="!d.shifts.length" class="pt-3 text-center text-[11px] text-ink-300">无排班</div>
        <div v-for="(s, i) in d.shifts" :key="i" class="mt-1.5 rounded-control bg-ink-50 px-2 py-1 text-[11px]">
          <div class="font-medium text-ink-800">{{ s.member }}</div>
          <div class="text-ink-500">{{ s.shift }}</div>
          <div v-if="s.swapped_to" class="text-emerald-600">已换给 {{ s.swapped_to }}</div>
        </div>
      </div>
    </div>

    <!-- 我的班次（可换班/删除） -->
    <div class="card p-4">
      <h3 class="mb-2 text-[14px] font-semibold text-ink-800">我的班次</h3>
      <div v-if="!myShifts.length" class="text-[13px] text-ink-400">暂无排班</div>
      <div v-for="s in myShifts" :key="s.id" class="flex flex-wrap items-center gap-2 border-b border-ink-50 py-2 text-[13px]">
        <span class="tag-brand">{{ s.duty_date }}</span>
        <span class="text-ink-700">{{ s.shift }}</span>
        <span class="text-ink-400">（{{ s.schedule }}）</span>
        <span v-if="s.is_swapped_in" class="tag bg-emerald-50 text-emerald-600">换入</span>
        <span class="ml-auto flex gap-2">
          <button class="btn-outline" @click="openSwap(s)">换班</button>
          <button class="btn-danger" @click="doDelete(s.id)">删除</button>
        </span>
      </div>
    </div>

    <!-- 添加班次 Modal -->
    <Modal :show="showAdd" title="添加班次" width="520px" @close="showAdd = false">
      <div class="space-y-3">
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">排班表</span>
          <div class="flex gap-2">
            <select v-model="addForm.schedule_id" class="input flex-1">
              <option value="" disabled>请选择排班表</option>
              <option v-for="s in schedules" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
            <button class="btn-outline" @click="createSchedule">＋ 新表</button>
          </div>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">日期</span>
          <input type="date" v-model="addForm.duty_date" class="input" /></label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block"><span class="mb-1 block text-[12px] text-ink-500">值班成员</span>
            <input v-model="addForm.member_name" class="input" placeholder="用户名 / 姓名" /></label>
          <label class="block"><span class="mb-1 block text-[12px] text-ink-500">班次</span>
            <select v-model="addForm.shift_name" class="input">
              <option>白班</option><option>夜班</option><option>中班</option><option>全天</option>
            </select></label>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showAdd = false">取消</button>
          <button class="btn-primary" @click="doAdd">添加</button>
        </div>
      </div>
    </Modal>

    <!-- 换班 Modal -->
    <Modal :show="showSwapModal" title="换班" width="420px" @close="showSwapModal = false">
      <div class="space-y-3">
        <p class="text-[13px] text-ink-600">将 <b>{{ swapItem?.duty_date }} {{ swapItem?.shift }}</b> 让给：</p>
        <input v-model="swapTo" class="input" placeholder="接收人（用户名 / 姓名）" />
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showSwapModal = false">取消</button>
          <button class="btn-primary" @click="doSwap">确认换班</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { suiteApi } from '../../api'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const D = 'officesuite'
const app = useAppStore()

const cursor = ref(new Date())
const week = ref({ week_start: '', days: [] })
const myShifts = ref([])
const myUpcoming = ref(0)
const schedules = ref([])

function isoDate(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
function shortDate(s) { return s.slice(5) }
function isToday(s) { return s === isoDate(new Date()) }

async function loadWeek() {
  const r = await suiteApi.call(D, 'duty/week/', 'GET', { date: isoDate(cursor.value) })
  week.value = r.data
}
async function loadMine() {
  const r = await suiteApi.call(D, 'duty/my-shifts/', 'GET')
  myShifts.value = r.data.items
  myUpcoming.value = r.data.upcoming_count
}
async function loadSchedules() {
  const r = await suiteApi.call(D, 'duty/schedule/list/', 'GET')
  schedules.value = r.data.items
}
function shiftWeek(n) {
  const d = new Date(cursor.value)
  d.setDate(d.getDate() + n * 7)
  cursor.value = d
  loadWeek()
}
function goThisWeek() {
  cursor.value = new Date()
  loadWeek()
}

const showAdd = ref(false)
const addForm = reactive({ schedule_id: '', duty_date: '', member_name: '', shift_name: '白班' })
function openAdd() {
  addForm.schedule_id = schedules.value[0]?.id || ''
  addForm.duty_date = isoDate(new Date())
  addForm.member_name = ''
  addForm.shift_name = '白班'
  showAdd.value = true
}
async function createSchedule() {
  const name = window.prompt('新排班表名称：', '默认排班')
  if (!name) return
  const start = isoDate(new Date())
  const r = await suiteApi.call(D, 'duty/schedule/create/', 'POST', { name, start_date: start })
  app.toastMsg('排班表已创建', 'success')
  await loadSchedules()
  addForm.schedule_id = r.data.id
}
async function doAdd() {
  if (!addForm.schedule_id) return app.toastMsg('请选择排班表', 'warn')
  if (!addForm.duty_date) return app.toastMsg('请选择日期', 'warn')
  if (!addForm.member_name.trim()) return app.toastMsg('请填写值班成员', 'warn')
  await suiteApi.call(D, 'duty/shift/add/', 'POST', { ...addForm, member_name: addForm.member_name.trim() })
  showAdd.value = false
  app.toastMsg('班次已添加', 'success')
  await loadWeek(); await loadMine()
}

const showSwapModal = ref(false)
const swapItem = ref(null)
const swapTo = ref('')
function openSwap(s) {
  swapItem.value = s
  swapTo.value = ''
  showSwapModal.value = true
}
async function doSwap() {
  if (!swapTo.value.trim()) return app.toastMsg('请填写接收人', 'warn')
  await suiteApi.call(D, `duty/shift/${swapItem.value.id}/swap/`, 'POST', { swap_to: swapTo.value.trim() })
  showSwapModal.value = false
  app.toastMsg('换班成功', 'success')
  await loadWeek(); await loadMine()
}
async function doDelete(id) {
  await suiteApi.call(D, `duty/shift/${id}/delete/`, 'POST')
  app.toastMsg('班次已删除', 'success')
  await loadWeek(); await loadMine()
}

onMounted(async () => {
  await loadSchedules()
  await Promise.all([loadWeek(), loadMine()])
})
</script>
