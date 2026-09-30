<template>
  <div class="mx-auto max-w-5xl space-y-4">
    <div>
      <h2 class="text-[16px] font-semibold text-ink-800">编程刷题训练</h2>
      <p class="text-[12px] text-ink-400">单选 / 读程序写结果 / 代码填空 / 找错，服务端判分并给出解析</p>
    </div>

    <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
      一次完整练习按六步走：先在下面条件栏定语言、题型、难度、题量 → 点「抽题」（或「随机一题」）拿题 →
      逐题作答 → 点「判定本题」看单题对错与解析 → 「整卷提交计分」出总分 → 错的点「加入错题本」沉淀。
      四种题型用不同颜色左边条区分：蓝=单选、紫=读程序、黄=代码填空、红=找错。
    </p>

    <div class="card flex flex-wrap items-end gap-3 p-4">
      <label class="block"><span class="mb-1 block text-[12px] text-ink-500">语言</span>
        <select v-model="lang" class="input w-36"><option value="">全部</option>
          <option v-for="l in langs" :key="l.key" :value="l.key">{{ l.name }}</option></select>
      </label>
      <label class="block"><span class="mb-1 block text-[12px] text-ink-500">题型</span>
        <select v-model="type" class="input w-40">
          <option value="quiz">单选题</option><option value="output">读程序写结果</option>
          <option value="fill">代码填空</option><option value="bug">找错题</option>
        </select>
      </label>
      <label class="block"><span class="mb-1 block text-[12px] text-ink-500">难度</span>
        <select v-model="level" class="input w-28"><option value="">不限</option><option value="1">1 星</option><option value="2">2 星</option><option value="3">3 星</option></select>
      </label>
      <label class="block"><span class="mb-1 block text-[12px] text-ink-500">题量</span>
        <select v-model.number="n" class="input w-24"><option :value="3">3</option><option :value="5">5</option><option :value="8">8</option></select>
      </label>
      <button class="btn-primary" @click="load">抽题</button>
      <button class="btn-outline" @click="submitAll">整卷提交计分</button>
      <button class="btn-ghost" @click="randomOne">随机一题</button>
      <span v-if="score !== null" class="ml-auto text-[14px] font-semibold" :class="score >= 60 ? 'text-emerald-600' : 'text-rose-500'">得分 {{ score }}（{{ correctCnt }}/{{ questions.length }}）</span>
    </div>

    <div v-if="questions.length === 0" class="card grid h-56 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
      条件栏当前是「Python · 单选题 · 不限难度 · 5 道」：点「抽题」按条件组卷，想先热身就点「随机一题」来一道。
    </div>

    <div v-for="(q, qi) in questions" :key="q.id" class="card p-4" :class="typeMeta(q.type).bar">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <span class="tag-brand">第 {{ qi + 1 }} 题</span>
        <span class="tag">{{ langName(q.lang) }}</span>
        <span class="rounded-pill px-2 py-0.5 text-[11px]" :class="typeMeta(q.type).chip">{{ typeName(q.type) }}</span>
        <span class="tag">难度 {{ q.level }}</span>
        <span v-if="results[q.id]" class="ml-auto text-[13px] font-medium" :class="results[q.id].correct ? 'text-emerald-600' : 'text-rose-500'">
          {{ results[q.id].correct ? '✓ 正确' : '✗ 参考答案：' + results[q.id].right_answer }}
        </span>
      </div>
      <p class="text-[13px] leading-6 text-ink-800">{{ q.stem }}</p>
      <pre v-if="q.code" class="mt-2 overflow-auto rounded-control bg-ink-900 p-3 font-mono text-[12px] leading-relaxed text-ink-100">{{ q.code }}</pre>

      <div v-if="q.options" class="mt-2 space-y-1.5">
        <button v-for="(o, i) in q.options" :key="i" class="block w-full rounded-control border px-3 py-1.5 text-left text-[13px]"
          :class="answers[q.id] === i ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-ink-200 text-ink-700 hover:bg-ink-50'"
          @click="answers[q.id] = i">{{ String.fromCharCode(65 + i) }}. {{ o }}</button>
      </div>
      <input v-else v-model="answers[q.id]" class="input mt-2" placeholder="填写程序运行结果 / 空缺内容（多空用英文逗号分隔）" />

      <div class="mt-2 flex items-center gap-2">
        <button class="btn-outline" @click="gradeOne(q)">判定本题</button>
        <button class="btn-ghost" @click="toMistake(q)">加入错题本</button>
      </div>
      <div v-if="results[q.id]" class="mt-2 rounded-control bg-ink-50 p-2.5 text-[12px] leading-6 text-ink-600">解析：{{ results[q.id].explain }}</div>
      <div v-if="results[q.id]" class="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
        <span class="text-ink-500">关联知识点：</span>
        <template v-if="knowledges(q).length">
          <span v-for="k in knowledges(q)" :key="k" class="tag-brand">{{ k }}</span>
          <RouterLink class="text-brand-600 hover:underline" to="/learning/school">去学科中心巩固 →</RouterLink>
        </template>
        <template v-else>
          <span class="rounded-pill px-2 py-0.5 text-[11px]" :class="typeMeta(q.type).chip">考点 · {{ typeMeta(q.type).point }}</span>
          <span class="text-ink-400">本题暂无关联知识点，先按题型考点回看上面的解析</span>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'

const app = useAppStore()
const TYPE = { quiz: '单选题', output: '读程序写结果', fill: '代码填空', bug: '找错题' }
const typeName = (t) => TYPE[t] || t
// 四种题型的视觉区分：左边条 + 徽章底色 + 题型考点标签（判定后展示）
const TYPE_META = {
  quiz: { bar: 'border-l-4 border-l-brand-500', chip: 'bg-brand-50 text-brand-700', point: '基础语法与 API 辨析' },
  output: { bar: 'border-l-4 border-l-violet-500', chip: 'bg-violet-50 text-violet-700', point: '程序执行跟踪 · 逐行推演' },
  fill: { bar: 'border-l-4 border-l-amber-400', chip: 'bg-amber-50 text-amber-700', point: '语法细节与代码补全' },
  bug: { bar: 'border-l-4 border-l-rose-400', chip: 'bg-rose-50 text-rose-600', point: '调试排错与代码阅读' },
}
const typeMeta = (t) => TYPE_META[t] || { bar: '', chip: 'bg-ink-100 text-ink-600', point: '综合代码能力' }
// 有关联知识点字段就展示（后端补充后自动生效），否则回落到题型考点标签
function knowledges(q) {
  const kp = q?.kp || q?.knowledge_point
  const arr = q?.knowledge || q?.points || q?.kps || []
  const out = []
  if (kp) out.push(...(Array.isArray(kp) ? kp : [kp]))
  if (Array.isArray(arr)) out.push(...arr)
  return [...new Set(out.filter(Boolean))]
}
const langs = ref([])
const langName = (k) => langs.value.find((l) => l.key === k)?.name || k

const lang = ref('python')
const type = ref('quiz')
const level = ref('')
const n = ref(5)
const questions = ref([])
const answers = ref({})
const results = ref({})
const score = ref(null)
const correctCnt = ref(0)

function reset() { answers.value = {}; results.value = {}; score.value = null; correctCnt.value = 0 }
async function load() {
  reset()
  const params = { n: n.value }
  if (lang.value) params.lang = lang.value
  if (level.value) params.level = level.value
  questions.value = (await learnApi.drill(type.value, params)).list
}
async function randomOne() {
  reset()
  const params = {}
  if (lang.value) params.lang = lang.value
  if (type.value) params.type = type.value
  questions.value = [await learnApi.drillRandom(params)]
}
async function gradeOne(q) {
  const ans = answers.value[q.id]
  if (ans === undefined || ans === '') return app.toastMsg('请先作答', 'warn')
  results.value[q.id] = (await learnApi.drillGrade({ id: q.id, answer: ans }))
}
async function submitAll() {
  if (!questions.value.length) return
  const payload = questions.value.map((q) => ({ id: q.id, answer: answers.value[q.id] ?? '' }))
  const r = (await learnApi.quizSubmit(payload))
  r.details.forEach((d) => (results.value[d.id] = d))
  score.value = r.score
  correctCnt.value = r.correct
  app.toastMsg(`交卷完成，得分 ${r.score}`, r.score >= 60 ? 'success' : 'warn')
}
async function toMistake(q) {
  await learnApi.addMistake({
    subject: `编程-${langName(q.lang)}`, question_type: q.type === 'quiz' ? 'single' : 'other',
    difficulty: q.level, stem: q.stem, answer: results.value[q.id]?.right_answer || '',
    user_answer: String(answers.value[q.id] ?? ''), analysis: results.value[q.id]?.explain || '',
  })
  app.toastMsg('已加入错题本', 'success')
}

onMounted(async () => {
  langs.value = (await learnApi.langCatalog()).list
  await load()
})
</script>
