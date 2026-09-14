<template>
  <div class="mx-auto max-w-5xl space-y-4">
    <div>
      <h2 class="text-[16px] font-semibold text-ink-800">编程刷题训练</h2>
      <p class="text-[12px] text-ink-400">单选 / 读程序写结果 / 代码填空 / 找错，服务端判分并给出解析</p>
    </div>

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

    <div v-if="questions.length === 0" class="card grid h-56 place-items-center text-[13px] text-ink-400">点击「抽题」开始练习</div>

    <div v-for="(q, qi) in questions" :key="q.id" class="card p-4">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <span class="tag-brand">第 {{ qi + 1 }} 题</span>
        <span class="tag">{{ langName(q.lang) }}</span>
        <span class="tag">{{ typeName(q.type) }}</span>
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
