<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">我的学习</h2>
        <p class="text-[12px] text-ink-400">学习进度、代码收藏、专注打卡、学习计划与掌握度，全部云端保存</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in tabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="tab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="switchTab(t.v)">{{ t.label }}</button>
      </div>
    </div>

    <!-- 学习进度 + 掌握度 -->
    <template v-if="tab === 'progress'">
      <div class="grid grid-cols-12 gap-4">
        <div class="card col-span-12 p-4 lg:col-span-5">
          <h3 class="mb-3 text-[14px] font-semibold text-ink-800">记录 / 更新进度</h3>
          <div class="space-y-2">
            <select v-model="pf.domain" class="input"><option value="programming">编程</option><option value="school">学科</option><option value="tool">工具</option></select>
            <input v-model="pf.target_key" class="input" placeholder="目标标识，如 python 或 junior.math" />
            <input v-model="pf.target_name" class="input" placeholder="目标名称，如 Python / 初中数学" />
            <div class="flex items-center gap-2"><input v-model.number="pf.percent" type="range" min="0" max="100" class="flex-1" /><span class="w-12 text-[13px] text-brand-700">{{ pf.percent }}%</span></div>
            <select v-model="pf.status" class="input"><option value="learning">学习中</option><option value="finished">已完成</option></select>
            <input v-model="pf.note" class="input" placeholder="备注（可选）" />
            <button class="btn-primary w-full" @click="saveProgress">保存进度</button>
          </div>
          <div v-if="mastery.by_subject" class="mt-4">
            <h3 class="mb-2 text-[14px] font-semibold text-ink-800">错题掌握度</h3>
            <div v-for="(v, k) in mastery.by_subject" :key="k" class="mb-1.5">
              <div class="flex justify-between text-[12px] text-ink-500"><span>{{ k }}</span><span>{{ v.mastered }}/{{ v.total }}（{{ v.mastery }}%）</span></div>
              <div class="h-1.5 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: v.mastery + '%' }"></div></div>
            </div>
          </div>
        </div>
        <div class="card col-span-12 p-4 lg:col-span-7">
          <h3 class="mb-3 text-[14px] font-semibold text-ink-800">进度列表（{{ progress.length }}）</h3>
          <div v-for="p in progress" :key="p.id" class="mb-2 rounded-control border border-ink-100 p-3">
            <div class="flex items-center gap-2">
              <span class="tag-brand">{{ domainName(p.domain) }}</span><span class="text-[13px] font-medium text-ink-800">{{ p.target_name || p.target_key }}</span>
              <span v-if="p.status === 'finished'" class="tag bg-emerald-50 text-emerald-600">已完成</span>
            </div>
            <div class="mt-1.5 h-1.5 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: p.percent + '%' }"></div></div>
            <div class="mt-1 text-[11px] text-ink-400">{{ p.percent }}% · 更新于 {{ fmt(p.updated_at) }}</div>
          </div>
          <div v-if="!progress.length" class="grid h-32 place-items-center text-[13px] text-ink-400">还没有学习进度</div>
        </div>
      </div>
    </template>

    <!-- 代码收藏 -->
    <template v-else-if="tab === 'bookmark'">
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="bf.language" class="input col-span-2" placeholder="语言 key，如 python" />
          <input v-model="bf.title" class="input col-span-3" placeholder="标题" />
          <input v-model="bf.code" class="input col-span-6" placeholder="代码 / 命令" />
          <button class="btn-primary col-span-1" @click="addBookmark">收藏</button>
        </div>
      </div>
      <div class="grid gap-2 md:grid-cols-2">
        <div v-for="b in bookmarks" :key="b.id" class="card p-3">
          <div class="flex items-center gap-2"><span class="tag-brand">{{ b.language }}</span><span class="text-[13px] font-semibold text-ink-800">{{ b.title }}</span>
            <button class="btn-danger ml-auto" @click="delBookmark(b.id)">删除</button></div>
          <pre class="mt-1.5 overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ b.code }}</pre>
          <div v-if="b.note" class="mt-1 text-[12px] text-ink-400">{{ b.note }}</div>
        </div>
      </div>
    </template>

    <!-- 专注记录 -->
    <template v-else-if="tab === 'session'">
      <div class="grid grid-cols-3 gap-3">
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ sessSummary.total_minutes || 0 }}</div><div class="text-[12px] text-ink-400">累计分钟</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ sessSummary.count || 0 }}</div><div class="text-[12px] text-ink-400">专注次数</div></div>
        <div class="card p-4 text-center"><div class="text-[22px] font-bold text-brand-700">{{ Math.round((sessSummary.total_minutes || 0) / 60 * 10) / 10 }}</div><div class="text-[12px] text-ink-400">累计小时</div></div>
      </div>
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="sf.subject" class="input col-span-3" placeholder="科目/主题，如 数学" />
          <input v-model.number="sf.minutes" type="number" class="input col-span-2" placeholder="分钟" />
          <input v-model="sf.study_date" type="date" class="input col-span-3" />
          <button class="btn-primary col-span-2" @click="addSession">打卡</button>
          <div class="col-span-2 text-[12px] leading-8 text-ink-400">番茄钟建议 25 分钟</div>
        </div>
      </div>
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">按科目统计</h3>
        <div class="flex flex-wrap gap-2"><span v-for="(m, k) in sessSummary.by_subject" :key="k" class="tag-brand">{{ k }}：{{ m }} 分钟</span></div>
      </div>
      <div class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">打卡记录</h3>
        <div v-for="s in sessions" :key="s.id" class="flex items-center gap-3 border-b border-ink-50 py-1.5 text-[13px]">
          <span class="tag-brand">{{ s.subject }}</span><span>{{ s.minutes }} 分钟</span><span class="text-ink-400">{{ s.study_date }}</span>
          <button class="btn-danger ml-auto" @click="delSession(s.id)">删除</button>
        </div>
      </div>
    </template>

    <!-- 学习计划 -->
    <template v-else>
      <div class="card p-4">
        <div class="grid grid-cols-12 gap-2">
          <input v-model="plf.title" class="input col-span-3" placeholder="计划名称，如 30 天背单词" />
          <input v-model="plf.subject" class="input col-span-2" placeholder="科目" />
          <input v-model.number="plf.total" type="number" class="input col-span-2" placeholder="总任务量" />
          <input v-model.number="plf.days" type="number" class="input col-span-1" placeholder="天数" />
          <input v-model="plf.start_date" type="date" class="input col-span-2" />
          <button class="btn-primary col-span-2" @click="addPlan">生成计划</button>
        </div>
      </div>
      <div class="grid gap-3 md:grid-cols-2">
        <div v-for="p in plans" :key="p.id" class="card p-4">
          <div class="flex items-center gap-2"><span class="text-[14px] font-semibold text-ink-800">{{ p.title }}</span><span class="tag">{{ p.subject }}</span>
            <button class="btn-danger ml-auto" @click="delPlan(p.id)">删除</button></div>
          <div class="mt-2 h-2 overflow-hidden rounded-pill bg-ink-100"><div class="h-full bg-brand-500" :style="{ width: (p.total ? p.finished / p.total * 100 : 0) + '%' }"></div></div>
          <div class="mt-1 flex items-center gap-2 text-[12px] text-ink-500">
            <span>已完成 {{ p.finished }}/{{ p.total }}，{{ p.days }} 天</span>
            <button class="btn-outline px-2 py-0.5" @click="bumpPlan(p, -1)">-</button>
            <button class="btn-outline px-2 py-0.5" @click="bumpPlan(p, 1)">+</button>
          </div>
          <details class="mt-2"><summary class="cursor-pointer text-[12px] text-brand-600">查看每日安排</summary>
            <ol class="mt-1 ml-4 list-decimal text-[12px] text-ink-500"><li v-for="(d, i) in p.plan" :key="i">{{ d }}</li></ol>
          </details>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { learnApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const tabs = [
  { v: 'progress', label: '学习进度' }, { v: 'bookmark', label: '代码收藏' },
  { v: 'session', label: '专注记录' }, { v: 'plan', label: '学习计划' },
]
const tab = ref('progress')
const today = new Date().toISOString().slice(0, 10)
const domainName = (d) => ({ programming: '编程', school: '学科', tool: '工具' })[d] || d
const fmt = (t) => (t || '').replace('T', ' ').slice(0, 16)

const progress = ref([])
const mastery = ref({})
const pf = reactive({ domain: 'programming', target_key: '', target_name: '', percent: 0, status: 'learning', note: '' })
async function loadProgress() {
  progress.value = (await learnApi.progress()).list
  mastery.value = (await learnApi.mastery())
}
async function saveProgress() {
  if (!pf.target_key) return app.toastMsg('请填写目标标识', 'warn')
  await learnApi.saveProgress({ ...pf })
  app.toastMsg('进度已保存', 'success')
  await loadProgress()
}

const bookmarks = ref([])
const bf = reactive({ language: 'python', title: '', code: '' })
async function loadBookmarks() { bookmarks.value = (await learnApi.bookmarks()).list }
async function addBookmark() {
  if (!bf.title) return app.toastMsg('请填写标题', 'warn')
  await learnApi.addBookmark({ ...bf }); bf.title = ''; bf.code = ''
  await loadBookmarks()
}
async function delBookmark(id) { await learnApi.delBookmark(id); await loadBookmarks() }

const sessions = ref([])
const sessSummary = ref({})
const sf = reactive({ subject: '数学', minutes: 25, study_date: today })
async function loadSessions() { const data = await learnApi.sessions(); sessions.value = data.list; sessSummary.value = data }
async function addSession() { await learnApi.addSession({ ...sf }); await loadSessions() }
async function delSession(id) { await learnApi.delSession(id); await loadSessions() }

const plans = ref([])
const plf = reactive({ title: '', subject: '', total: 100, days: 7, start_date: today })
async function loadPlans() { plans.value = (await learnApi.plans()).list }
async function addPlan() {
  if (!plf.title) return app.toastMsg('请填写计划名称', 'warn')
  await learnApi.addPlan({ ...plf })
  plf.title = ''
  await loadPlans()
}
async function bumpPlan(p, delta) { await learnApi.updatePlan({ id: p.id, finished: Math.max(0, p.finished + delta) }); await loadPlans() }
async function delPlan(id) { await learnApi.delPlan(id); await loadPlans() }

async function switchTab(v) {
  tab.value = v
  if (v === 'progress') await loadProgress()
  if (v === 'bookmark') await loadBookmarks()
  if (v === 'session') await loadSessions()
  if (v === 'plan') await loadPlans()
}

onMounted(loadProgress)
</script>
