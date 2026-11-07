<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 标题 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">会议室预订</h2>
        <p class="text-[12px] text-ink-400">先选日期与会议室看空闲时段，点选时段后提交预订；收藏的会议室置顶显示</p>
      </div>
      <div class="flex items-center gap-2">
        <button class="btn-outline" :disabled="roomsLoading" @click="loadRooms">↻ 刷新会议室</button>
        <button class="btn-outline" :disabled="bookingLoading" @click="loadBookings">↻ 刷新我的预订</button>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-3">
      <!-- 会议室列表 -->
      <div class="card p-4">
        <div class="mb-2 flex items-center justify-between">
          <span class="text-[13px] font-medium text-ink-700">会议室</span>
          <span class="text-[11px] text-ink-400">收藏 {{ favoriteCount }} / 共 {{ rooms.length }}</span>
        </div>

        <div v-if="roomsLoading && !rooms.length" class="py-6 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="roomsError" class="rounded-control bg-rose-50 px-2 py-2 text-[11px] text-rose-600">
          <div class="truncate">{{ roomsError }}</div>
          <button class="mt-1 font-medium" @click="loadRooms">重试</button>
        </div>
        <div v-else-if="!rooms.length" class="py-6 text-center text-[12px] text-ink-400">暂无可预订会议室</div>
        <ul v-else class="space-y-1">
          <li v-for="r in sortedRooms" :key="r.id" class="flex items-center gap-1">
            <button
              class="min-w-0 flex-1 rounded-control px-2 py-1.5 text-left transition-colors"
              :class="selectedRoomId === r.id ? 'bg-brand-50 ring-1 ring-brand-300' : 'hover:bg-ink-50'"
              :aria-pressed="selectedRoomId === r.id"
              @click="selectRoom(r.id)"
            >
              <span class="flex items-center gap-1">
                <span class="min-w-0 truncate text-[13px] text-ink-800">{{ r.name }}</span>
                <span v-if="r.favorite" class="shrink-0 text-[11px] text-amber-500" title="已收藏">★</span>
              </span>
              <span class="block truncate text-[11px] text-ink-400">
                {{ r.capacity }} 人 · {{ r.location || '未填写位置' }}
              </span>
            </button>
            <button
              class="shrink-0 rounded-pill px-1.5 text-[14px] leading-none"
              :class="r.favorite ? 'text-amber-500 hover:text-amber-600' : 'text-ink-300 hover:text-amber-500'"
              :title="r.favorite ? '取消收藏' : '收藏置顶'"
              :aria-label="r.favorite ? `取消收藏 ${r.name}` : `收藏 ${r.name}`"
              @click="toggleFavorite(r)"
            >
              {{ r.favorite ? '★' : '☆' }}
            </button>
          </li>
        </ul>
      </div>

      <!-- 时段与预订 -->
      <div class="card p-4 lg:col-span-2">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="text-[13px] font-medium text-ink-700">
            {{ currentRoom?.name || '未选择会议室' }}
            <span v-if="currentRoom" class="text-[11px] font-normal text-ink-400">（{{ currentRoom.capacity }} 人）</span>
          </span>
          <label class="flex items-center gap-1.5 text-[12px] text-ink-500">
            日期
            <input v-model="form.date" type="date" class="input w-40 py-1" aria-label="预订日期" />
          </label>
        </div>

        <div v-if="!selectedRoomId" class="py-10 text-center text-[12px] text-ink-400">请先在左侧选择一个会议室</div>
        <template v-else>
          <div v-if="availLoading" class="py-6 text-center text-[12px] text-ink-400">时段加载中…</div>
          <div v-else-if="availError" class="mt-2 rounded-control bg-rose-50 px-2 py-2 text-[11px] text-rose-600">
            <div class="truncate">{{ availError }}</div>
            <button class="mt-1 font-medium" @click="loadAvailability">重试</button>
          </div>
          <template v-else>
            <!-- 时段条：08:00–20:00，半小时一格 -->
            <div class="mt-3 flex flex-wrap gap-1">
              <button
                v-for="s in slots"
                :key="s.value"
                class="rounded-control border px-1.5 py-1 text-[11px] transition-colors"
                :class="slotClass(s)"
                :disabled="s.busy"
                :title="s.busy ? `已被预订：${s.title || '会议'}` : `选择 ${s.hm} 开始`"
                @click="pickSlot(s)"
              >
                {{ s.hm }}
              </button>
            </div>
            <p class="mt-1.5 text-[11px] text-ink-300">
              灰色为已被预订时段（当天共 {{ availability?.occupied_count ?? 0 }} 条），点击白色时段即可选中
            </p>

            <!-- 已占用明细 -->
            <div v-if="occupied.length" class="mt-3 rounded-control bg-ink-50 p-2.5">
              <div class="mb-1 text-[11px] font-medium text-ink-600">当天已预订</div>
              <div
                v-for="o in occupied"
                :key="o.id"
                class="flex items-center gap-2 text-[11px] text-ink-500"
              >
                <span class="shrink-0 font-mono">{{ hm(o.start_at) }}–{{ hm(o.end_at) }}</span>
                <span class="min-w-0 truncate">{{ o.title || '会议' }}</span>
              </div>
            </div>

            <!-- 预订表单 -->
            <div class="mt-3 border-t border-ink-50 pt-3">
              <div class="grid gap-2 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1 block text-[12px] text-ink-500">会议主题</span>
                  <input v-model="form.title" class="input" placeholder="如：项目周会" maxlength="200" />
                </label>
                <label class="block">
                  <span class="mb-1 block text-[12px] text-ink-500">时长</span>
                  <select v-model.number="form.duration" class="input">
                    <option :value="30">30 分钟</option>
                    <option :value="60">60 分钟</option>
                    <option :value="90">90 分钟</option>
                    <option :value="120">120 分钟</option>
                  </select>
                </label>
              </div>
              <div class="mt-2 flex flex-wrap items-center gap-3 text-[12px] text-ink-600">
                <span>时段：</span>
                <b class="text-ink-800">{{ selectedStart ? hm(selectedStart) : '未选择' }}</b>
                <span v-if="selectedStart">– {{ hm(endValue) }}</span>
                <span v-if="selectedStart" class="text-[11px] text-ink-400">（{{ form.date }}）</span>
                <button class="btn-primary ml-auto" :disabled="booking" @click="submitBooking">
                  {{ booking ? '提交中…' : '提交预订' }}
                </button>
              </div>
            </div>
          </template>
        </template>
      </div>
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <!-- 我的预订 -->
      <div class="card p-4">
        <div class="mb-2 flex items-center justify-between">
          <span class="text-[13px] font-medium text-ink-700">我的预订</span>
          <button class="text-[11px] text-brand-600" @click="loadBookings">刷新</button>
        </div>
        <div v-if="bookingLoading && !bookings.length" class="py-6 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="bookingsError" class="rounded-control bg-rose-50 px-2 py-2 text-[11px] text-rose-600">
          <div class="truncate">{{ bookingsError }}</div>
          <button class="mt-1 font-medium" @click="loadBookings">重试</button>
        </div>
        <div v-else-if="!bookings.length" class="py-6 text-center text-[12px] text-ink-400">还没有预订记录</div>
        <div v-else class="divide-y divide-ink-50">
          <div v-for="b in bookings" :key="b.id" class="flex items-center gap-2 py-1.5 text-[12px]">
            <span class="w-24 shrink-0 font-mono text-ink-500">{{ fmtDT(b.start_at) }}</span>
            <span class="min-w-0 flex-1 truncate text-ink-800">{{ b.title || '会议' }}</span>
            <span class="shrink-0 text-[11px] text-ink-400">{{ roomName(b.room) }}</span>
            <span class="tag shrink-0" :class="b.status === 'booked' ? 'bg-emerald-50 text-emerald-600' : ''">
              {{ b.status === 'booked' ? '已预订' : (b.status === 'cancelled' ? '已取消' : b.status) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 车辆可用性（先选时段再选车） -->
      <div class="card p-4">
        <div class="mb-2 flex items-center justify-between">
          <span class="text-[13px] font-medium text-ink-700">用车 · 空闲车辆</span>
          <span class="text-[11px] text-ink-400">先选时段，再选车</span>
        </div>
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">用车开始</span>
            <input v-model="veh.start" type="datetime-local" class="input" aria-label="用车开始时间" />
          </label>
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">用车结束</span>
            <input v-model="veh.end" type="datetime-local" class="input" aria-label="用车结束时间" />
          </label>
        </div>
        <div class="mt-2 flex items-center gap-2">
          <button class="btn-outline" :disabled="vehLoading" @click="queryVehicles">
            {{ vehLoading ? '查询中…' : '查询空闲车辆' }}
          </button>
          <span v-if="vehResult" class="text-[11px] text-ink-400">
            空闲 {{ vehResult.count }} 辆 · 占用 {{ vehResult.busy_count }} 辆
          </span>
        </div>
        <div v-if="vehError" class="mt-2 rounded-control bg-rose-50 px-2 py-2 text-[11px] text-rose-600">
          <div class="truncate">{{ vehError }}</div>
          <button class="mt-1 font-medium" @click="queryVehicles">重试</button>
        </div>
        <div v-if="vehResult" class="mt-2">
          <div v-if="!vehResult.items?.length" class="py-3 text-center text-[12px] text-ink-400">
            该时段暂无空闲车辆，请调整时间
          </div>
          <div v-else class="flex flex-wrap gap-2">
            <button
              v-for="v in vehResult.items"
              :key="v.id"
              class="rounded-control border px-2 py-1 text-[12px] transition-colors"
              :class="vehSelected === v.id ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-ink-200 text-ink-700 hover:border-brand-300'"
              :aria-pressed="vehSelected === v.id"
              @click="vehSelected = v.id"
            >
              {{ v.plate }}
              <span class="text-[11px] text-ink-400">{{ v.model_name || '' }} · {{ v.seats }} 座</span>
            </button>
          </div>
          <p v-if="selectedVehicle" class="mt-2 text-[11px] text-ink-500">
            已选择 <b class="text-ink-800">{{ selectedVehicle.plate }}</b>，可到「用车申请」提交该时段的用车单。
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { officex } from '../../api/officex'
import { useAppStore } from '../../stores/app'

const app = useAppStore()

const pad = (n) => String(n).padStart(2, '0')
function isoDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
function hm(iso) {
  if (!iso) return '--:--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--:--'
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function fmtDT(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm(iso)}`
}
function toMin(iso) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 0
  return d.getHours() * 60 + d.getMinutes()
}

// ---------------- 会议室列表 / 收藏 ----------------
const rooms = ref([])
const roomsLoading = ref(false)
const roomsError = ref('')
const selectedRoomId = ref(null)
const favBusy = ref(null)

const sortedRooms = computed(() => {
  // 收藏置顶（357），其余按名称排序
  return [...rooms.value].sort((a, b) => {
    if (!!b.favorite !== !!a.favorite) return b.favorite ? 1 : -1
    return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN')
  })
})
const favoriteCount = computed(() => rooms.value.filter((r) => r.favorite).length)
const currentRoom = computed(() => rooms.value.find((r) => r.id === selectedRoomId.value) || null)

async function loadRooms() {
  roomsLoading.value = true
  roomsError.value = ''
  try {
    const r = await officex.rooms()
    rooms.value = Array.isArray(r) ? r : (r.items || [])
    if (!selectedRoomId.value && rooms.value.length) {
      const first = sortedRooms.value[0]
      selectedRoomId.value = first.id
      loadAvailability()
    }
  } catch (e) {
    roomsError.value = e?.message || '会议室加载失败'
    app.toastMsg(roomsError.value, 'error')
  } finally {
    roomsLoading.value = false
  }
}

async function toggleFavorite(room) {
  if (favBusy.value) return
  favBusy.value = room.id
  try {
    if (room.favorite) await officex.removeRoomFavorite(room.id)
    else await officex.addRoomFavorite(room.id)
    // 本地即时翻转，再拉取一次保证与后端 favorite 字段一致
    room.favorite = !room.favorite
    app.toastMsg(room.favorite ? '已收藏并置顶' : '已取消收藏', 'success')
    await loadRooms()
  } catch (e) {
    app.toastMsg(e?.message || '收藏操作失败', 'error')
  } finally {
    favBusy.value = null
  }
}

// ---------------- 时段 ----------------
const form = reactive({
  date: isoDate(new Date()),
  title: '',
  duration: 60,
})
const availability = ref(null)
const availLoading = ref(false)
const availError = ref('')
const selectedStart = ref('')

const occupied = computed(() => availability.value?.occupied || [])

const SLOT_START = 8
const SLOT_END = 20
const SLOT_STEP = 30

const slots = computed(() => {
  if (!form.date) return []
  const ranges = occupied.value.map((o) => ({ s: toMin(o.start_at), e: toMin(o.end_at), title: o.title }))
  const out = []
  for (let m = SLOT_START * 60; m < SLOT_END * 60; m += SLOT_STEP) {
    const startHm = `${pad(Math.floor(m / 60))}:${pad(m % 60)}`
    const hit = ranges.find((r) => r.s < m + SLOT_STEP && r.e > m)
    out.push({
      hm: startHm,
      value: `${form.date}T${startHm}`,
      busy: !!hit,
      title: hit?.title || '',
    })
  }
  return out
})

function slotClass(s) {
  if (s.busy) return 'border-ink-100 bg-ink-100 text-ink-300 cursor-not-allowed line-through'
  if (s.value === selectedStart.value) return 'border-brand-500 bg-brand-500 text-white'
  return 'border-ink-200 bg-white text-ink-600 hover:border-brand-400 hover:text-brand-600'
}

const endValue = computed(() => {
  if (!selectedStart.value) return ''
  const d = new Date(selectedStart.value)
  if (isNaN(d.getTime())) return ''
  d.setMinutes(d.getMinutes() + (Number(form.duration) || 0))
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
})

async function loadAvailability() {
  if (!selectedRoomId.value || !form.date) return
  availLoading.value = true
  availError.value = ''
  selectedStart.value = ''
  try {
    availability.value = await officex.roomAvailability(selectedRoomId.value, form.date)
  } catch (e) {
    availability.value = null
    availError.value = e?.message || '时段加载失败'
    app.toastMsg(availError.value, 'error')
  } finally {
    availLoading.value = false
  }
}

function selectRoom(id) {
  if (selectedRoomId.value === id) return
  selectedRoomId.value = id
  loadAvailability()
}

function pickSlot(s) {
  if (s.busy) return
  selectedStart.value = s.value
}

watch(() => form.date, () => loadAvailability())

// ---------------- 预订 ----------------
const booking = ref(false)
async function submitBooking() {
  if (!selectedRoomId.value) return app.toastMsg('请先选择会议室', 'warn')
  if (!form.title.trim()) return app.toastMsg('请填写会议主题', 'warn')
  if (!selectedStart.value) return app.toastMsg('请先点选一个空闲时段', 'warn')
  if (new Date(endValue.value) <= new Date(selectedStart.value)) {
    return app.toastMsg('结束时间必须晚于开始时间', 'warn')
  }
  booking.value = true
  try {
    // 后端 meeting_book 读 start_at / end_at；冲突时 400 message 直接 toast
    await officex.bookRoom({
      room_id: selectedRoomId.value,
      start_at: selectedStart.value,
      end_at: endValue.value,
      title: form.title.trim(),
    })
    app.toastMsg('预订成功', 'success')
    form.title = ''
    selectedStart.value = ''
    await Promise.all([loadAvailability(), loadBookings()])
  } catch (e) {
    app.toastMsg(e?.message || '预订失败', 'error')
  } finally {
    booking.value = false
  }
}

// ---------------- 我的预订 ----------------
const bookings = ref([])
const bookingLoading = ref(false)
const bookingsError = ref('')

async function loadBookings() {
  bookingLoading.value = true
  bookingsError.value = ''
  try {
    const r = await officex.myBookings()
    bookings.value = Array.isArray(r) ? r : (r.items || [])
  } catch (e) {
    bookingsError.value = e?.message || '预订记录加载失败'
    app.toastMsg(bookingsError.value, 'error')
  } finally {
    bookingLoading.value = false
  }
}
function roomName(id) {
  return rooms.value.find((r) => r.id === id)?.name || (id ? `#${id}` : '')
}

// ---------------- 车辆可用 ----------------
const veh = reactive({
  start: `${isoDate(new Date())}T09:00`,
  end: `${isoDate(new Date())}T11:00`,
})
const vehResult = ref(null)
const vehLoading = ref(false)
const vehError = ref('')
const vehSelected = ref(null)
const selectedVehicle = computed(() =>
  (vehResult.value?.items || []).find((v) => v.id === vehSelected.value) || null
)

async function queryVehicles() {
  vehError.value = ''
  if (!veh.start || !veh.end) return app.toastMsg('请选择用车开始与结束时间', 'warn')
  if (new Date(veh.end) <= new Date(veh.start)) {
    return app.toastMsg('结束时间必须晚于开始时间', 'warn')
  }
  vehLoading.value = true
  try {
    vehResult.value = await officex.vehicleAvailable(veh.start, veh.end)
    vehSelected.value = null
  } catch (e) {
    vehResult.value = null
    vehError.value = e?.message || '车辆查询失败'
    app.toastMsg(vehError.value, 'error')
  } finally {
    vehLoading.value = false
  }
}

onMounted(async () => {
  await Promise.allSettled([loadRooms(), loadBookings()])
})
</script>
