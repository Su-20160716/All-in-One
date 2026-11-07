<template>
  <div class="space-y-3">
    <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
      和小组成员一起打卡：先建一个小组（如「高三数学冲刺」），填名称、学科和每日目标分钟；成员加入后每天填分钟点「打卡」，
      会写进自己的「专注记录」。下方「本周榜」按本周学习分钟排名，只有开启「学习榜公开」的同学会出现在榜上，名字已做脱敏。
    </p>

    <!-- 建组 -->
    <div class="card p-4">
      <h3 class="mb-2 text-[14px] font-semibold text-ink-800">创建学习小组</h3>
      <div class="grid grid-cols-12 gap-2">
        <input v-model="nf.name" class="input col-span-3" placeholder="小组名称，如 高三数学冲刺" />
        <input v-model="nf.subject" class="input col-span-2" placeholder="学科（可选）" />
        <input v-model.number="nf.goal_minutes" type="number" min="1" max="1440" class="input col-span-2" placeholder="每日目标分钟" />
        <input v-model="nf.note" class="input col-span-3" placeholder="一句话目标（可选）" />
        <button class="btn-primary col-span-2" :disabled="creating" @click="createGroup">{{ creating ? '创建中…' : '创建小组' }}</button>
      </div>
    </div>

    <!-- 小组列表 -->
    <div class="card flex flex-wrap items-center gap-2 p-3 text-[12px] text-ink-500">
      <span>共 <b class="text-brand-700">{{ groups.length }}</b> 个小组</span>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button class="rounded-control px-2 py-0.5" :class="scope === 'mine' ? 'bg-white text-brand-700 shadow-sm' : ''" @click="setScope('mine')">我的小组</button>
        <button class="rounded-control px-2 py-0.5" :class="scope === 'all' ? 'bg-white text-brand-700 shadow-sm' : ''" @click="setScope('all')">全部小组</button>
      </div>
      <button class="btn-outline ml-auto px-2 py-0.5" @click="loadGroups">刷新</button>
    </div>

    <div v-if="groups.length" class="grid gap-2 md:grid-cols-2">
      <div v-for="g in groups" :key="g.id" class="card p-4">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[14px] font-semibold text-ink-800">{{ g.name }}</span>
          <span v-if="g.subject" class="tag">{{ g.subject }}</span>
          <span v-if="g.is_owner" class="tag-brand">我创建的</span>
          <span v-if="g.my_checked_in" class="tag bg-emerald-50 text-emerald-600">今日已打卡</span>
          <button v-if="scope === 'all'" class="btn-outline ml-auto px-2 py-0.5 text-[11px]" @click="join(g)">加入</button>
        </div>
        <div v-if="g.note" class="mt-1 text-[12px] text-ink-400">{{ g.note }}</div>
        <div class="mt-2 grid grid-cols-3 gap-2 text-center text-[11px] text-ink-400">
          <div><div class="text-[15px] font-semibold text-ink-800">{{ g.members }}</div>成员</div>
          <div><div class="text-[15px] font-semibold text-ink-800">{{ g.checked_in }}</div>今日打卡</div>
          <div><div class="text-[15px] font-semibold text-brand-700">{{ g.today_minutes }}</div>今日分钟</div>
        </div>
        <div class="mt-1.5 h-1.5 overflow-hidden rounded-pill bg-ink-100">
          <div class="h-full bg-brand-500" :style="{ width: Math.min(100, g.goal_minutes ? g.today_minutes / g.goal_minutes * 100 : 0) + '%' }"></div>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
          <span class="text-ink-400">打卡分钟</span>
          <input v-model.number="mins[g.id]" type="number" min="1" max="600" class="input h-8 w-20 text-[12px]" placeholder="25" />
          <button class="btn-primary px-3 py-1" :disabled="checking[g.id]" @click="checkin(g)">{{ checking[g.id] ? '打卡中…' : '打卡' }}</button>
          <span class="ml-auto text-[11px] text-ink-400">目标 {{ g.goal_minutes }} 分钟/天</span>
        </div>
      </div>
    </div>
    <div v-else class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
      还没有小组：上面填名称点「创建小组」，或切到「全部小组」加入别人建的组；加入后每天打卡，小组进度会一起往前走。
    </div>

    <!-- 380 本周榜 -->
    <div class="card p-4">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <h3 class="text-[14px] font-semibold text-ink-800">学习榜</h3>
        <div class="flex gap-1 rounded-control bg-ink-100 p-1 text-[11px]">
          <button v-for="r in RANGES" :key="r.v" class="rounded-control px-2 py-0.5" :class="range === r.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="setRange(r.v)">{{ r.label }}</button>
        </div>
        <span class="ml-auto text-[11px] text-ink-400">仅统计公开学习榜的同学</span>
        <button class="btn-outline px-2 py-0.5 text-[11px]" @click="loadBoard">刷新</button>
      </div>
      <div v-if="board.list && board.list.length" class="space-y-1">
        <div v-for="row in board.list" :key="row.rank" class="flex items-center gap-2 rounded-control px-2.5 py-1.5 text-[12px]"
             :class="row.rank <= 3 ? 'bg-amber-50/70' : 'bg-ink-50'">
          <span class="w-5 text-center font-semibold" :class="row.rank <= 3 ? 'text-amber-600' : 'text-ink-400'">{{ row.rank }}</span>
          <span class="text-[13px] font-medium text-ink-800">{{ row.name }}</span>
          <span class="text-ink-400">{{ row.days }} 天有记录</span>
          <span class="ml-auto font-medium text-brand-700">{{ row.minutes }} 分钟</span>
        </div>
      </div>
      <div v-else class="text-[12px] leading-6 text-ink-400">
        榜单还空着：先去「学习概览」打开「学习榜公开」，再打卡几分钟；公开的同学越多，这里越热闹。
      </div>
      <div v-if="board.me" class="mt-2 flex flex-wrap items-center gap-2 rounded-control bg-brand-50 px-2.5 py-1.5 text-[11px] text-brand-700">
        <span>我：{{ board.me.minutes }} 分钟 · {{ board.me.days }} 天有记录</span>
        <span class="text-ink-500">{{ board.me.public ? '已在榜上公开' : '当前未公开，不会出现在榜单' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { learnApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const RANGES = [{ v: 'day', label: '今日' }, { v: 'week', label: '本周' }, { v: 'month', label: '本月' }]

const scope = ref('mine')
const groups = ref([])
const mins = reactive({})
const checking = reactive({})
const creating = ref(false)
const nf = reactive({ name: '', subject: '', goal_minutes: 60, note: '' })

async function loadGroups() {
  try {
    const d = await learnApi.groups({ scope: scope.value })
    groups.value = d.list || []
    groups.value.forEach((g) => { if (!mins[g.id]) mins[g.id] = 25 })
  } catch (e) {
    groups.value = []
    app.toastMsg('小组列表加载失败：' + (e?.message || '网络异常'), 'error')
  }
}
function setScope(v) { scope.value = v; loadGroups() }
async function createGroup() {
  if (!nf.name.trim()) return app.toastMsg('请填写小组名称', 'warn')
  creating.value = true
  try {
    await learnApi.createGroup({ ...nf })
    nf.name = ''; nf.note = ''
    app.toastMsg('小组已创建', 'success')
    scope.value = 'mine'
    await loadGroups()
  } catch (e) {
    app.toastMsg('创建失败：' + (e?.message || '网络异常'), 'error')
  } finally {
    creating.value = false
  }
}
async function join(g) {
  try {
    const r = await learnApi.joinGroup(g.id)
    app.toastMsg(r.joined ? `已加入「${g.name}」` : `你已在「${g.name}」里`, r.joined ? 'success' : 'info')
    await loadGroups()
  } catch (e) {
    app.toastMsg('加入失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function checkin(g) {
  const m = Number(mins[g.id]) || 25
  if (m < 1) return app.toastMsg('打卡分钟需大于 0', 'warn')
  checking[g.id] = true
  try {
    await learnApi.checkinGroup(g.id, m)
    app.toastMsg(`已打卡 ${m} 分钟，今日共 ${(g.today_minutes || 0) + m} 分钟`, 'success')
    await loadGroups()
    await loadBoard()
  } catch (e) {
    app.toastMsg('打卡失败：' + (e?.message || '请先加入该小组'), 'error')
  } finally {
    checking[g.id] = false
  }
}

const range = ref('week')
const board = ref({})
async function loadBoard() {
  try {
    board.value = await learnApi.leaderboard(range.value, 10)
  } catch (e) {
    board.value = { list: [], me: null }
    app.toastMsg('学习榜加载失败：' + (e?.message || '网络异常'), 'error')
  }
}
function setRange(v) { range.value = v; loadBoard() }

onMounted(() => { loadGroups(); loadBoard() })
</script>
