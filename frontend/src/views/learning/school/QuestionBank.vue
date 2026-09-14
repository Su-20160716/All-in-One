<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">题库 · 智能组卷 · 错题本</h2>
        <p class="text-[12px] text-ink-400">按学段学科抽题、在线作答服务端判分，错题自动沉淀到错题本</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in tabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="tab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="switchTab(t.v)">{{ t.label }}</button>
      </div>
    </div>

    <!-- 题库浏览 -->
    <template v-if="tab === 'bank'">
      <div class="card flex flex-wrap items-end gap-3 p-4">
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">学段</span>
          <select v-model="f.stage" class="input w-32"><option value="">全部</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">学科</span>
          <select v-model="f.subject" class="input w-32"><option value="">全部</option><option v-for="s in subjectOpts" :key="s.v" :value="s.v">{{ s.label }}</option></select>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">题型</span>
          <select v-model="f.type" class="input w-32"><option value="">全部</option><option value="single">单选</option><option value="judge">判断</option><option value="fill">填空</option></select>
        </label>
        <button class="btn-primary" @click="loadBank">筛选</button>
        <span class="text-[12px] text-ink-400">共 {{ bank.length }} 题</span>
      </div>
      <div class="space-y-2">
        <div v-for="(q, i) in bank" :key="q.id" class="card p-4">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tag-brand">{{ i + 1 }}</span><span class="tag">{{ typeName(q.type) }}</span>
            <span class="tag">难度 {{ q.difficulty }}</span><span class="tag">{{ q.kp }}</span>
          </div>
          <p class="mt-2 text-[13px] leading-6 text-ink-800">{{ q.stem }}</p>
          <div v-if="q.options" class="mt-1.5 grid gap-1 md:grid-cols-2">
            <div v-for="(o, oi) in q.options" :key="oi" class="text-[13px] text-ink-600">{{ String.fromCharCode(65 + oi) }}. {{ o }}</div>
          </div>
          <div class="mt-2 flex gap-2">
            <button class="btn-outline" @click="showDetail(q)">查看答案解析</button>
            <button class="btn-ghost" @click="toMistake(q)">收进错题本</button>
          </div>
          <div v-if="detailId === q.id" class="mt-2 rounded-control bg-ink-50 p-2.5 text-[12px] leading-6 text-ink-600">
            答案：<b class="text-brand-700">{{ answerText(q, qDetail.answer) }}</b><br />解析：{{ qDetail.analysis }}
          </div>
        </div>
      </div>
    </template>

    <!-- 智能组卷 -->
    <template v-else-if="tab === 'paper'">
      <div class="card flex flex-wrap items-end gap-3 p-4">
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">学段</span>
          <select v-model="p.stage" class="input w-32"><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">学科</span>
          <select v-model="p.subject" class="input w-32"><option v-for="s in subjectOpts" :key="s.v" :value="s.v">{{ s.label }}</option></select>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">题量</span>
          <select v-model.number="p.count" class="input w-28"><option :value="5">5 题</option><option :value="8">8 题</option><option :value="10">10 题</option></select>
        </label>
        <button class="btn-primary" @click="compose">智能组卷</button>
        <button v-if="paper.length" class="btn-outline" @click="gradePaper">交卷判分</button>
        <button v-if="paper.length" class="btn-ghost" @click="showAnswer = !showAnswer">{{ showAnswer ? '隐藏答案卷' : '查看答案卷' }}</button>
        <span v-if="paperResult" class="text-[14px] font-semibold" :class="paperResult.score >= 60 ? 'text-emerald-600' : 'text-rose-500'">
          得分 {{ paperResult.score }}（对 {{ paperResult.correct }} / 错 {{ paperResult.wrong }}）
        </span>
      </div>

      <div v-if="showAnswer" class="card p-4">
        <h3 class="mb-2 text-[13px] font-semibold text-ink-700">答案卷</h3>
        <div v-for="a in answerSheet" :key="a.id" class="text-[12px] text-ink-600">{{ a.id }}：{{ answerTextById(a.id, a.answer) }} —— {{ a.analysis }}</div>
      </div>

      <div v-for="(q, i) in paper" :key="q.id" class="card p-4">
        <div class="flex items-center gap-2"><span class="tag-brand">{{ i + 1 }}</span><span class="tag">{{ typeName(q.type) }}</span><span class="tag">{{ q.kp }}</span>
          <span v-if="graded[q.id]" class="ml-auto text-[13px] font-medium" :class="graded[q.id].correct ? 'text-emerald-600' : 'text-rose-500'">{{ graded[q.id].correct ? '✓' : '✗ 正确答案：' + answerText(q, graded[q.id].right_answer) }}</span>
        </div>
        <p class="mt-2 text-[13px] text-ink-800">{{ q.stem }}</p>
        <div v-if="q.options" class="mt-1.5 grid gap-1.5 md:grid-cols-2">
          <button v-for="(o, oi) in q.options" :key="oi" class="rounded-control border px-3 py-1.5 text-left text-[13px]"
            :class="ans[q.id] === oi ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-ink-200 hover:bg-ink-50'" @click="ans[q.id] = oi">{{ String.fromCharCode(65 + oi) }}. {{ o }}</button>
        </div>
        <div v-else-if="q.type === 'judge'" class="mt-1.5 flex gap-2">
          <button class="btn-outline" :class="ans[q.id] === true ? '!border-brand-500 !text-brand-700' : ''" @click="ans[q.id] = true">✓ 正确</button>
          <button class="btn-outline" :class="ans[q.id] === false ? '!border-brand-500 !text-brand-700' : ''" @click="ans[q.id] = false">✗ 错误</button>
        </div>
        <input v-else v-model="ans[q.id]" class="input mt-1.5" placeholder="填写答案" />
        <div v-if="graded[q.id] && !graded[q.id].correct" class="mt-2 rounded-control bg-ink-50 p-2 text-[12px] text-ink-600">解析：{{ graded[q.id].analysis }}</div>
      </div>
    </template>

    <!-- 错题本 -->
    <template v-else>
      <div class="card flex items-center gap-3 p-4">
        <span class="text-[13px] text-ink-600">共 {{ mistakes.length }} 道错题</span>
        <button class="btn-outline" @click="loadMistakes">刷新</button>
      </div>
      <div v-for="m in mistakes" :key="m.id" class="card p-4" :class="m.mastered ? 'opacity-60' : ''">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag-brand">{{ m.subject }}</span><span class="tag">{{ typeName(m.question_type) }}</span>
          <span v-if="m.mastered" class="tag bg-emerald-50 text-emerald-600">已订正</span>
        </div>
        <p class="mt-2 text-[13px] text-ink-800">{{ m.stem }}</p>
        <div class="mt-1 text-[12px] text-ink-500">正确答案：{{ m.answer }}　我的答案：{{ m.user_answer }}</div>
        <div v-if="m.analysis" class="text-[12px] text-ink-400">解析：{{ m.analysis }}</div>
        <div class="mt-2 flex gap-2">
          <button class="btn-outline" @click="toggleMistake(m.id)">{{ m.mastered ? '标为未掌握' : '订正掌握' }}</button>
          <button class="btn-danger" @click="removeMistake(m.id)">删除</button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'

const app = useAppStore()
const tabs = [{ v: 'bank', label: '题库浏览' }, { v: 'paper', label: '智能组卷' }, { v: 'mistake', label: '错题本' }]
const tab = ref('bank')
const subjectOpts = [
  { v: 'chinese', label: '语文' }, { v: 'math', label: '数学' }, { v: 'english', label: '英语' },
  { v: 'physics', label: '物理' }, { v: 'chemistry', label: '化学' }, { v: 'biology', label: '生物' },
  { v: 'history', label: '历史' }, { v: 'geography', label: '地理' }, { v: 'politics', label: '政治' },
]
const TNAME = { single: '单选题', judge: '判断题', fill: '填空题', output: '读程序', other: '其它' }
const typeName = (t) => TNAME[t] || t

const f = reactive({ stage: '', subject: '', type: '' })
const bank = ref([])
const detailId = ref('')
const qDetail = ref({})
async function loadBank() { bank.value = (await learnApi.questions(f)).list }
async function showDetail(q) { detailId.value = q.id; qDetail.value = (await learnApi.question(q.id)) }
function answerText(q, a) {
  if (q.type === 'single') return q.options ? `${String.fromCharCode(65 + Number(a))}. ${q.options[a]}` : a
  if (q.type === 'judge') return a ? '正确' : '错误'
  return a
}
function answerTextById(id, a) { const q = paper.value.find((x) => x.id === id); return q ? answerText(q, a) : a }
async function toMistake(q) {
  await learnApi.addMistake({ stage: q.stage, subject: q.subject, question_type: q.type, difficulty: q.difficulty, stem: q.stem })
  app.toastMsg('已收进错题本', 'success')
}

const p = reactive({ stage: 'junior', subject: 'math', count: 5 })
const paper = ref([])
const answerSheet = ref([])
const ans = reactive({})
const graded = reactive({})
const paperResult = ref(null)
const showAnswer = ref(false)
async function compose() {
  Object.keys(ans).forEach((k) => delete ans[k])
  Object.keys(graded).forEach((k) => delete graded[k])
  paperResult.value = null; showAnswer.value = false
  const data = await learnApi.paperCompose(p)
  paper.value = data.paper
  answerSheet.value = data.answer_sheet
}
async function gradePaper() {
  const answers = paper.value.map((q) => ({ id: q.id, answer: ans[q.id] ?? '' }))
  const data = await learnApi.paperGrade(answers)
  data.details.forEach((d) => (graded[d.id] = d))
  paperResult.value = data
  app.toastMsg(`判分完成：${data.score} 分`, data.score >= 60 ? 'success' : 'warn')
}

const mistakes = ref([])
async function loadMistakes() { mistakes.value = (await learnApi.mistakes()).list }
async function toggleMistake(id) { await learnApi.toggleMistake(id); await loadMistakes() }
async function removeMistake(id) { await learnApi.delMistake(id); await loadMistakes() }

async function switchTab(v) {
  tab.value = v
  if (v === 'mistake') await loadMistakes()
}

onMounted(loadBank)
</script>
