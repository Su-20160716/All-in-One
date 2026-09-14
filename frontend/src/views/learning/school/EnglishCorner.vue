<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">英语角</h2>
        <p class="text-[12px] text-ink-400">分级词表、中文听写、单词选择测验、48 个国际音标、个人生词本</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in tabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="tab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="switchTab(t.v)">{{ t.label }}</button>
      </div>
    </div>

    <!-- 词表 -->
    <div v-if="tab === 'words'" class="space-y-3">
      <div class="card flex flex-wrap items-end gap-3 p-4">
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">学段</span>
          <select v-model="wStage" class="input w-32" @change="loadWords"><option value="">全部</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
        </label>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">主题</span>
          <select v-model="wTopic" class="input w-40" @change="loadWords"><option value="">全部</option><option v-for="t in topics" :key="t" :value="t">{{ t }}</option></select>
        </label>
        <span class="text-[12px] text-ink-400">共 {{ words.length }} 词</span>
      </div>
      <div class="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        <div v-for="w in words" :key="w.word" class="card p-3">
          <div class="flex items-baseline gap-2"><span class="text-[15px] font-semibold text-ink-900">{{ w.word }}</span><span class="font-mono text-[11px] text-ink-400">{{ w.phonetic }}</span><span class="tag">{{ w.pos }}</span></div>
          <div class="mt-1 text-[13px] text-ink-700">{{ w.meaning }}</div>
          <div class="mt-1 text-[12px] italic text-ink-400">{{ w.example }}</div>
          <button class="btn-ghost mt-1 px-0 text-[12px] text-brand-600" @click="addWord(w.word)">＋ 加入生词本</button>
        </div>
      </div>
    </div>

    <!-- 听写 -->
    <div v-else-if="tab === 'dict'" class="space-y-3">
      <div class="card flex items-center gap-3 p-4">
        <span class="text-[13px] text-ink-600">看中文写英文</span>
        <select v-model.number="dN" class="input w-24"><option :value="5">5 词</option><option :value="10">10 词</option><option :value="15">15 词</option></select>
        <select v-model="dStage" class="input w-32"><option value="">全部学段</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
        <button class="btn-primary" @click="loadDict">开始听写</button>
      </div>
      <div v-for="(d, i) in dictation" :key="i" class="card p-3">
        <div class="flex items-center gap-2"><span class="tag-brand">{{ i + 1 }}</span><span class="text-[14px] font-medium text-ink-800">{{ d.prompt }}</span><span class="font-mono text-[11px] text-ink-400">{{ d.phonetic }}</span></div>
        <div class="mt-2 flex gap-2">
          <input v-model="dictAns[i]" class="input" placeholder="拼写英文单词" />
          <button class="btn-outline" @click="d.show = !d.show">{{ d.show ? '隐藏' : '对照' }}</button>
        </div>
        <div v-if="d.show" class="mt-1 text-[13px]"><span class="font-semibold text-brand-700">{{ d.answer }}</span> <span class="text-[12px] italic text-ink-400">{{ d.example }}</span></div>
      </div>
    </div>

    <!-- 测验 -->
    <div v-else-if="tab === 'quiz'" class="space-y-3">
      <div class="card flex items-center gap-3 p-4">
        <select v-model="qStage" class="input w-32"><option value="">全部学段</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
        <button class="btn-primary" @click="loadQuiz">生成测验</button>
        <span v-if="quizScore !== null" class="text-[14px] font-semibold text-brand-700">答对 {{ quizRight }}/{{ quiz.length }}，得分 {{ quizScore }}</span>
      </div>
      <div v-for="(q, i) in quiz" :key="i" class="card p-4">
        <div class="flex items-center gap-2"><span class="tag-brand">{{ i + 1 }}</span><span class="text-[15px] font-semibold text-ink-900">{{ q.word }}</span><span class="font-mono text-[11px] text-ink-400">{{ q.phonetic }}</span></div>
        <div class="mt-2 grid gap-1.5 md:grid-cols-2">
          <button v-for="(o, oi) in q.options" :key="oi" class="rounded-control border px-3 py-1.5 text-left text-[13px]"
            :class="pickCls(i, oi)" @click="choose(i, oi)">{{ String.fromCharCode(65 + oi) }}. {{ o }}</button>
        </div>
      </div>
    </div>

    <!-- 音标 -->
    <div v-else-if="tab === 'ipa'" class="space-y-3">
      <div v-for="(items, gname) in ipa" :key="gname" class="card p-4">
        <h3 class="mb-2 text-[14px] font-semibold text-ink-800">{{ gname }}</h3>
        <div class="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
          <div v-for="(x, i) in items" :key="i" class="rounded-control border border-ink-100 p-2.5">
            <div class="flex items-baseline gap-2"><span class="font-mono text-[18px] font-bold text-brand-700">{{ x.ipa }}</span><span class="text-[11px] text-ink-400">{{ x.example }}</span></div>
            <div class="mt-0.5 text-[12px] text-ink-500">{{ x.tip }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 生词本 -->
    <div v-else class="space-y-3">
      <div class="card flex items-center gap-2 p-4">
        <input v-model="newWord" class="input w-48" placeholder="输入单词加入生词本" @keyup.enter="addNew" />
        <button class="btn-primary" @click="addNew">添加</button>
        <button class="btn-outline" @click="loadBook">刷新</button>
        <span class="text-[12px] text-ink-400">共 {{ book.length }} 个，已掌握 {{ masteredCount }} 个</span>
      </div>
      <div class="grid gap-2 md:grid-cols-2">
        <div v-for="b in book" :key="b.id" class="card flex items-center gap-3 p-3" :class="b.mastered ? 'opacity-60' : ''">
          <div class="flex-1">
            <div class="text-[14px] font-semibold" :class="b.mastered ? 'text-ink-400 line-through' : 'text-ink-900'">{{ b.word }}</div>
            <div class="text-[12px] text-ink-400">{{ b.phonetic }} {{ b.meaning }}</div>
          </div>
          <button class="btn-outline" @click="toggleBook(b.id)">{{ b.mastered ? '未掌握' : '已掌握' }}</button>
          <button class="btn-danger" @click="removeBook(b.id)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'

const app = useAppStore()
const tabs = [
  { v: 'words', label: '分级词表' }, { v: 'dict', label: '听写' }, { v: 'quiz', label: '单词测验' },
  { v: 'ipa', label: '国际音标' }, { v: 'book', label: '生词本' },
]
const tab = ref('words')

const words = ref([])
const topics = ref([])
const wStage = ref('')
const wTopic = ref('')
async function loadWords() {
  const data = await learnApi.words({ stage: wStage.value, topic: wTopic.value })
  words.value = data.list
  topics.value = data.topics
}

const dictation = ref([])
const dictAns = ref({})
const dN = ref(10)
const dStage = ref('')
async function loadDict() {
  dictAns.value = {}
  dictation.value = (await learnApi.dictation({ n: dN.value, stage: dStage.value })).list
}

const quiz = ref([])
const quizPick = ref({})
const quizScore = ref(null)
const quizRight = ref(0)
const qStage = ref('')
async function loadQuiz() {
  quizPick.value = {}
  quizScore.value = null
  quiz.value = (await learnApi.wordQuiz({ n: 8, stage: qStage.value })).list
}
function choose(i, oi) {
  if (quizPick.value[i] !== undefined) return
  quizPick.value[i] = oi
  const done = quiz.value.every((_, k) => quizPick.value[k] !== undefined)
  if (done) {
    quizRight.value = quiz.value.filter((q, k) => quizPick.value[k] === q.answer).length
    quizScore.value = Math.round((quizRight.value / quiz.value.length) * 100)
  }
}
function pickCls(i, oi) {
  if (quizPick.value[i] === undefined) return 'border-ink-200 hover:bg-ink-50'
  const correct = quiz.value[i].answer === oi
  const picked = quizPick.value[i] === oi
  if (correct) return 'border-emerald-400 bg-emerald-50 text-emerald-700'
  if (picked) return 'border-rose-400 bg-rose-50 text-rose-600'
  return 'border-ink-100 opacity-60'
}

const ipa = ref({})

const book = ref([])
const newWord = ref('')
const masteredCount = computed(() => book.value.filter((b) => b.mastered).length)
async function loadBook() { book.value = (await learnApi.wordbook()).list }
async function addWord(w) { await learnApi.addWord(w); app.toastMsg(`已加入生词本：${w}`, 'success') }
async function addNew() { if (!newWord.value) return; await learnApi.addWord(newWord.value); newWord.value = ''; await loadBook() }
async function toggleBook(id) { await learnApi.toggleWord(id); await loadBook() }
async function removeBook(id) { await learnApi.delWord(id); await loadBook() }

async function switchTab(v) {
  tab.value = v
  if (v === 'book') await loadBook()
  if (v === 'ipa' && !Object.keys(ipa.value).length) ipa.value = (await learnApi.toolRun('ipa-table', {})).result.groups
}

onMounted(loadWords)
</script>
