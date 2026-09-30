<template>
  <div class="mx-auto max-w-6xl space-y-5">
    <!-- 头图 -->
    <div class="card overflow-hidden">
      <div class="bg-gradient-to-r from-brand-600 to-brand-400 px-6 py-7 text-white">
        <h2 class="text-[20px] font-semibold">学习中心</h2>
        <p class="mt-1 text-[13px] text-white/85">10 种编程语言 · 小学 / 初中 / 高中全学科资料 · 40 个学习工具，一站式自学与备考</p>
        <div class="mt-4 flex flex-wrap gap-2">
          <span class="rounded-pill bg-white/15 px-3 py-1 text-[12px]">编程语言 {{ stats.langs }} 种</span>
          <span class="rounded-pill bg-white/15 px-3 py-1 text-[12px]">知识点 {{ stats.points }}+</span>
          <span class="rounded-pill bg-white/15 px-3 py-1 text-[12px]">学习工具 {{ stats.tools }} 个</span>
          <span class="rounded-pill bg-white/15 px-3 py-1 text-[12px]">公式 {{ stats.formulas }} 条</span>
          <span class="rounded-pill bg-white/15 px-3 py-1 text-[12px]">题库持续更新</span>
        </div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
      <RouterLink v-for="e in entries" :key="e.to" :to="e.to"
        class="card group p-4 transition-shadow hover:shadow-pop">
        <div class="text-[24px]">{{ e.icon }}</div>
        <div class="mt-2 text-[14px] font-semibold text-ink-800">{{ e.title }}</div>
        <div class="mt-0.5 text-[12px] leading-5 text-ink-400">{{ e.desc }}</div>
      </RouterLink>
    </div>

    <div class="grid grid-cols-12 gap-4">
      <!-- 每日一题 -->
      <div class="card col-span-12 p-5 lg:col-span-7">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-[15px] font-semibold text-ink-800">每日一题 · 编程</h3>
          <select v-model="dailyLang" class="input w-36" @change="loadDaily">
            <option value="">全部语言</option>
            <option v-for="l in langs" :key="l.key" :value="l.key">{{ l.name }}</option>
          </select>
        </div>
        <p class="mb-3 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
          今天练哪道？用右上角下拉把题目锁到一门语言（默认全部），可能是四选一的选择题，也可能是让你读程序写结果、
          填空的文本题；选/写完点「提交判定」立刻对答案，无论对错都给一段解析，没思路就「换一题」重抽。
        </p>
        <div v-if="daily" class="space-y-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tag-brand">{{ langName(daily.lang) }}</span>
            <span class="rounded-pill px-2 py-0.5 text-[11px]" :class="typeMeta(daily.type).chip">{{ typeName(daily.type) }}</span>
            <span class="tag">难度 {{ daily.level }}</span>
          </div>
          <p class="text-[13px] font-medium text-ink-700">{{ daily.stem }}</p>
          <pre class="overflow-auto rounded-control bg-ink-900 p-3 font-mono text-[12px] leading-relaxed text-ink-100">{{ daily.code }}</pre>
          <div v-if="daily.options" class="space-y-1.5">
            <button v-for="(o, i) in daily.options" :key="i"
              class="block w-full rounded-control border px-3 py-1.5 text-left text-[13px] transition-colors"
              :class="pick === i ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-ink-200 text-ink-700 hover:bg-ink-50'"
              @click="pick = i">{{ String.fromCharCode(65 + i) }}. {{ o }}</button>
          </div>
          <input v-else v-model="textAnswer" class="input" placeholder="输入你的答案" />
          <div class="flex items-center gap-2">
            <button class="btn-primary" @click="gradeDaily">提交判定</button>
            <button class="btn-outline" @click="loadDaily">换一题</button>
            <span v-if="dailyResult" class="text-[13px] font-medium" :class="dailyResult.correct ? 'text-emerald-600' : 'text-rose-500'">
              {{ dailyResult.correct ? '回答正确！' : '答案：' + dailyResult.right_answer }}
            </span>
          </div>
          <div v-if="dailyResult" class="rounded-control bg-ink-50 p-3 text-[12px] leading-6 text-ink-600">解析：{{ dailyResult.explain }}</div>
          <div v-if="dailyResult" class="flex flex-wrap items-center gap-2 text-[12px]">
            <span class="text-ink-500">关联知识点：</span>
            <template v-if="dailyKnowledge.length">
              <span v-for="k in dailyKnowledge" :key="k" class="tag-brand">{{ k }}</span>
              <RouterLink class="text-brand-600 hover:underline" to="/learning/school">去学科中心巩固 →</RouterLink>
            </template>
            <template v-else>
              <span class="rounded-pill px-2 py-0.5 text-[11px]" :class="typeMeta(daily.type).chip">考点 · {{ typeMeta(daily.type).point }}</span>
              <span class="text-ink-400">这道题暂未标注关联知识点，先按题型考点回看解析</span>
            </template>
          </div>
        </div>
        <div v-else class="rounded-control bg-ink-50 p-4 text-[13px] leading-6 text-ink-400">
          还没抽到今日题目：把上方语言切回「全部语言」再等几秒，或刷新页面重抽。
        </div>
      </div>

      <!-- 为你推荐 -->
      <div class="card col-span-12 p-5 lg:col-span-5">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-[15px] font-semibold text-ink-800">学什么？按目标推荐</h3>
          <select v-model="goal" class="input w-32" @change="loadRecommend">
            <option value="ai">人工智能</option>
            <option value="web">网站开发</option>
            <option value="job">求职就业</option>
            <option value="game">游戏开发</option>
            <option value="system">底层系统</option>
            <option value="mobile">移动开发</option>
          </select>
        </div>
        <p class="mb-3 rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
          先回答“我要做什么”：人工智能偏 Python、网站开发看 JavaScript/Go/Java、底层系统盯 C/C++/Rust。
          挑一个目标，下面给出推荐理由和匹配语言卡片，点「去学」直接带语言参数跳进广场对应详情。
        </p>
        <p class="mb-3 rounded-control bg-brand-50 p-2.5 text-[12px] leading-6 text-brand-700">{{ recReason }}</p>
        <div class="space-y-2">
          <div v-for="l in recommends" :key="l.key" class="flex items-center gap-3 rounded-control border border-ink-100 p-3">
            <div class="grid h-9 w-9 place-items-center rounded-control text-[16px]" :style="{ background: (l.color || '#0ea5e9') + '22' }">{{ l.icon }}</div>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] font-semibold text-ink-800">{{ l.name }}</div>
              <div class="truncate text-[12px] text-ink-400">{{ l.summary }}</div>
            </div>
            <RouterLink class="btn-ghost" :to="{ path: '/learning/programming', query: { lang: l.key } }">去学</RouterLink>
          </div>
          <div v-if="!recommends.length" class="rounded-control bg-ink-50 p-3 text-[12px] leading-6 text-ink-400">
            这个目标下还没返回语言：换一个目标（试试「求职就业」——它给 Java/Python/JavaScript），或稍后重试。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { learnApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const entries = [
  { to: '/learning/programming', icon: '💻', title: '编程语言广场', desc: 'Python/JS/C/C++/Java/Go/Rust 等 10 种' },
  { to: '/learning/drill', icon: '🧩', title: '编程刷题训练', desc: '单选、读程序、填空、找错四类练习' },
  { to: '/learning/school', icon: '📚', title: '学科知识中心', desc: '知识点树、公式手册、语法、理化' },
  { to: '/learning/chinese', icon: '🀄', title: '语文园地', desc: '古诗文、成语接龙、汉字字典' },
  { to: '/learning/english', icon: '🔤', title: '英语角', desc: '词表、听写测验、音标、生词本' },
  { to: '/learning/questions', icon: '📝', title: '题库与组卷', desc: '智能组卷、在线判分、错题本' },
  { to: '/learning/tools', icon: '🧮', title: '学习工具箱', desc: '40 个计算与练习生成工具' },
  { to: '/learning/study', icon: '⏱', title: '我的学习', desc: '进度、收藏、专注、计划' },
]
const TYPE = { quiz: '单选题', output: '读程序写结果', fill: '代码填空', bug: '找错题' }
const typeName = (t) => TYPE[t] || t
// 四种题型的视觉区分：与刷题训练页同一套配色（蓝/紫/黄/红）
const TYPE_META = {
  quiz: { chip: 'bg-brand-50 text-brand-700', point: '基础语法与 API 辨析' },
  output: { chip: 'bg-violet-50 text-violet-700', point: '程序执行跟踪 · 逐行推演' },
  fill: { chip: 'bg-amber-50 text-amber-700', point: '语法细节与代码补全' },
  bug: { chip: 'bg-rose-50 text-rose-600', point: '调试排错与代码阅读' },
}
const typeMeta = (t) => TYPE_META[t] || { chip: 'bg-ink-100 text-ink-600', point: '综合代码能力' }
// 判定后展示关联知识点；后端补充 kp/knowledge 字段后自动显示，否则回落到题型考点标签
const dailyKnowledge = computed(() => {
  const d = daily.value
  if (!d) return []
  const kp = d.kp || d.knowledge_point
  const arr = d.knowledge || d.points || d.kps || []
  const out = []
  if (kp) out.push(...(Array.isArray(kp) ? kp : [kp]))
  if (Array.isArray(arr)) out.push(...arr)
  return [...new Set(out.filter(Boolean))]
})
const langName = (k) => langs.value.find((l) => l.key === k)?.name || k

const stats = ref({ langs: 10, points: 1500, tools: 40, formulas: 60 })
const langs = ref([])
const daily = ref(null)
const dailyLang = ref('')
const pick = ref(null)
const textAnswer = ref('')
const dailyResult = ref(null)
const goal = ref('ai')
const recommends = ref([])
const recReason = ref('')

async function loadDaily() {
  dailyResult.value = null
  pick.value = null
  textAnswer.value = ''
  const data = await learnApi.dailyChallenge(dailyLang.value ? { lang: dailyLang.value } : {})
  daily.value = data
}
async function gradeDaily() {
  const answer = daily.value.options ? pick.value : textAnswer.value
  if (answer === null || answer === '') return app.toastMsg('请先作答', 'warn')
  const data = await learnApi.drillGrade({ id: daily.value.id, answer })
  dailyResult.value = data
}
async function loadRecommend() {
  const data = await learnApi.recommend({ goal: goal.value })
  recommends.value = data.list
  recReason.value = data.reason
}
async function loadStats() {
  const [l, t, f] = await Promise.all([learnApi.langCatalog(), learnApi.toolCatalog(), learnApi.formulas()])
  stats.value.langs = l.total
  stats.value.tools = t.total
  stats.value.formulas = f.total
  langs.value = l.list
}

onMounted(async () => {
  await loadStats()
  await Promise.all([loadDaily(), loadRecommend()])
})
</script>
