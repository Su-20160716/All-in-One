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
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        背单词的输入端：先按学段（小学 / 初中 / 高中）和主题（食物、动词、学术动词…）筛词，
        每张卡片给出音标、词性、中文释义和一句原声例句；眼生的点「＋ 加入生词本」，稍后在生词本里集中过。
        想看搭配、词根和辨析，点单词本身弹出详情。
      </p>
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
          <div class="flex items-baseline gap-2">
            <span class="cursor-pointer text-[15px] font-semibold text-ink-900 underline decoration-dotted decoration-ink-300 underline-offset-4 hover:text-brand-600"
              @click="openWord(w.word)" :title="`查看 ${w.word} 的详情`">{{ w.word }}</span>
            <span class="font-mono text-[11px] text-ink-400">{{ w.phonetic }}</span><span class="tag">{{ w.pos }}</span>
          </div>
          <div class="mt-1 text-[13px] text-ink-700">{{ w.meaning }}</div>
          <div class="mt-1 text-[12px] italic text-ink-400">{{ w.example }}</div>
          <div class="mt-1 flex items-center gap-3">
            <button class="btn-ghost px-0 text-[12px] text-brand-600" @click="addWord(w.word)">＋ 加入生词本</button>
            <button class="btn-ghost px-0 text-[12px] text-ink-500" @click="openWord(w.word)">详情 / 搭配</button>
          </div>
        </div>
        <div v-if="!words.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          这个学段 / 主题下没有收录词：把两个下拉都切回「全部」，词库目前覆盖小学到高中共 139 词。
        </div>
      </div>
    </div>

    <!-- 听写 -->
    <div v-else-if="tab === 'dict'" class="space-y-3">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        主动回忆这一环：选 5 / 10 / 15 词和学段点「开始听写」，系统给中文释义（附音标提示），你凭记忆拼出英文；
        点「对照」逐词批改——拼对打 ✓，拼错打 ✗ 并把正确拼写用绿色高亮出来，下面还会汇总这组对错几题。
      </p>
      <div class="card flex items-center gap-3 p-4">
        <span class="text-[13px] text-ink-600">看中文写英文</span>
        <select v-model.number="dN" class="input w-24"><option :value="5">5 词</option><option :value="10">10 词</option><option :value="15">15 词</option></select>
        <select v-model="dStage" class="input w-32"><option value="">全部学段</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
        <button class="btn-primary" @click="loadDict">开始听写</button>
      </div>
      <div v-if="!dictation.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
        还没开始听写：选好数量和学段点「开始听写」，第一批中文释义就在这里等着你拼。
      </div>
      <div v-for="(d, i) in dictation" :key="i" class="card p-3">
        <div class="flex items-center gap-2"><span class="tag-brand">{{ i + 1 }}</span><span class="text-[14px] font-medium text-ink-800">{{ d.prompt }}</span><span class="font-mono text-[11px] text-ink-400">{{ d.phonetic }}</span></div>
        <div class="mt-2 flex gap-2">
          <input v-model="dictAns[i]" class="input" placeholder="拼写英文单词" />
          <button class="btn-outline" @click="d.show = !d.show">{{ d.show ? '隐藏' : '对照批改' }}</button>
        </div>
        <div v-if="d.show" class="mt-2 space-y-1.5">
          <div class="text-[13px]"><span class="font-semibold text-brand-700">{{ d.answer }}</span> <span class="text-[12px] italic text-ink-400">{{ d.example }}</span></div>
          <div class="flex flex-wrap items-center gap-2 text-[13px]">
            <template v-if="dictState(i).correct">
              <span class="font-medium text-emerald-600">✓ 拼写正确</span>
              <span class="text-ink-400">你写的是 <b class="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700">{{ dictAns[i] }}</b></span>
            </template>
            <template v-else-if="dictState(i).answered">
              <span class="font-medium text-rose-500">✗ 拼写有误</span>
              <span class="text-ink-500">正确拼写：<b class="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700">{{ d.answer }}</b>
                <span class="text-ink-400">（你写的是 {{ dictAns[i] }}）</span></span>
              <button class="btn-outline px-2 py-0.5 text-[11px]" @click="collectWrong([d.answer])">＋ 生词本</button>
            </template>
            <template v-else>
              <span class="text-ink-400">○ 还没作答——先自己拼再看答案，记得回来批改</span>
            </template>
          </div>
        </div>
      </div>
      <div v-if="dictSummary.total" class="card p-3 text-[13px] text-ink-600">
        <div>本组听写：<b class="text-emerald-600">对 {{ dictSummary.right }}</b> ·
        <b class="text-rose-500">错 {{ dictSummary.wrong }}</b> ·
        <span class="text-ink-400">未作答 {{ dictSummary.blank }}</span>（共 {{ dictSummary.total }} 词已批改）</div>
        <button v-if="dictWrongWords.length" class="btn-outline mt-2 px-2 py-1 text-[11px]" @click="collectWrong(dictWrongWords)">把错词（{{ dictWrongWords.length }}）加入生词本</button>
      </div>
    </div>

    <!-- 测验 -->
    <div v-else-if="tab === 'quiz'" class="space-y-3">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        检测这一环：选学段点「生成测验」拿到 8 道四选一——给英文单词选中文释义，点选项即时判色
        （绿=正确项，红=你选错的，其余变淡）。每题作答后立刻展开该词的中文释义和例句；全部答完顶部汇总得分。
      </p>
      <div class="card flex items-center gap-3 p-4">
        <select v-model="qStage" class="input w-32"><option value="">全部学段</option><option value="primary">小学</option><option value="junior">初中</option><option value="senior">高中</option></select>
        <button class="btn-primary" @click="loadQuiz">生成测验</button>
        <span v-if="quizScore !== null" class="text-[14px] font-semibold text-brand-700">答对 {{ quizRight }}/{{ quiz.length }}，得分 {{ quizScore }}</span>
      </div>
      <div v-if="!quiz.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
        还没有测验：点上面「生成测验」出 8 道题；想只考一个学段就先在左边选「小学 / 初中 / 高中」。
      </div>
      <div v-for="(q, i) in quiz" :key="i" class="card p-4">
        <div class="flex items-center gap-2"><span class="tag-brand">{{ i + 1 }}</span><span class="text-[15px] font-semibold text-ink-900">{{ q.word }}</span><span class="font-mono text-[11px] text-ink-400">{{ q.phonetic }}</span></div>
        <div class="mt-2 grid gap-1.5 md:grid-cols-2">
          <button v-for="(o, oi) in q.options" :key="oi" class="rounded-control border px-3 py-1.5 text-left text-[13px]"
            :class="pickCls(i, oi)" @click="choose(i, oi)">{{ String.fromCharCode(65 + oi) }}. {{ o }}</button>
        </div>
        <div v-if="quizPick[i] !== undefined" class="mt-2 rounded-control bg-brand-50 px-3 py-2 text-[12px] leading-6 text-brand-800">
          <span class="font-semibold">{{ q.word }}</span> 的中文释义：{{ q.meaning || q.options[q.answer] }}
          <span v-if="q.pos" class="text-brand-600">（{{ q.pos }}）</span>
          <span v-if="q.example" class="mt-0.5 block italic text-ink-500">例句：{{ q.example }}</span>
        </div>
      </div>
    </div>

    <!-- 音标 -->
    <div v-else-if="tab === 'ipa'" class="space-y-3">
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        正音这块：48 个国际音标按「元音 / 辅音」分组（第一次切到本页才去取数，所以会稍等一下）。
        每格三行——音标符号、一个例词、一句发音要领；对照例词大声读两遍，比死记口型图管用。
      </p>
      <div v-if="!Object.keys(ipa).length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
        音标表正在加载：本页是惰性加载的，稍等片刻就会出现元音 / 辅音两组卡片；若一直空白，切到别的 Tab 再切回来。
      </div>
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
      <p class="rounded-lg bg-ink-50 px-3 py-2 text-[12px] leading-5 text-ink-500">
        沉淀区：词表里点「＋」进来的、或你在上面手动输入的词都收在这里；顶部统计总数与已掌握数。
        过完一遍觉得稳了点「已掌握」，卡片会变灰划上删除线，随时能删——它是听写和测验的复习底账。
      </p>
      <div class="card flex flex-wrap items-center gap-2 p-4">
        <input v-model="newWord" class="input w-48" placeholder="输入单词加入生词本" @keyup.enter="addNew" />
        <button class="btn-primary" @click="addNew">添加</button>
        <button class="btn-outline" @click="loadBook">刷新</button>
        <button class="btn-outline" @click="exportBook">导出 CSV</button>
        <button class="btn-outline" @click="showImport = !showImport">{{ showImport ? '收起导入' : '导入' }}</button>
        <span class="text-[12px] text-ink-400">共 {{ book.length }} 个，已掌握 {{ masteredCount }} 个</span>
      </div>
      <div v-if="showImport" class="card p-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-ink-700">导入生词本</span>
          <select v-model="impFmt" class="input h-8 w-24 text-[12px]">
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
          <button class="btn-primary px-3 py-1" :disabled="importing" @click="importBook">{{ importing ? '导入中…' : '开始导入' }}</button>
          <span class="text-[11px] text-ink-400">CSV 表头：单词,音标,释义,已掌握；按单词去重</span>
        </div>
        <textarea v-model="impText" rows="4" class="input w-full font-mono text-[11px]"
          :placeholder="impFmt === 'csv' ? '单词,音标,释义,已掌握\napple,/ˈæpl/,苹果,否' : '[{&quot;word&quot;:&quot;apple&quot;,&quot;meaning&quot;:&quot;苹果&quot;}]'"></textarea>
        <div v-if="impMsg" class="mt-2 rounded-control bg-ink-50 p-2 text-[12px] leading-6 text-ink-600">{{ impMsg }}</div>
        <div v-else class="mt-2 text-[11px] leading-5 text-ink-400">换设备或换端时把导出的 CSV 粘进来即可；已存在的单词会跳过，不会重复。</div>
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
        <div v-if="!book.length" class="card grid h-32 place-items-center px-6 text-center text-[13px] leading-6 text-ink-400">
          生词本还是空的：去「分级词表」点「＋ 加入生词本」，或在上面直接输入一个单词回车，它就会出现在这里。
        </div>
      </div>
    </div>

    <!-- 单词详情弹层（F508/S10：接通 learnApi.word · #187 无障碍对话框） -->
    <div v-if="wordDetail" class="fixed inset-0 z-50 grid place-items-center bg-ink-900/40 p-4" @click.self="closeWord">
      <div ref="wordDialogRef" class="card w-full max-w-lg p-5" role="dialog" aria-modal="true"
        aria-labelledby="word-detail-title" tabindex="-1">
        <div class="flex flex-wrap items-center gap-2">
          <h3 id="word-detail-title" class="text-[18px] font-semibold text-ink-900">{{ wordDetail.word }}</h3>
          <span class="font-mono text-[12px] text-ink-400">{{ wordDetail.phonetic }}</span>
          <span v-if="wordDetail.pos" class="tag">{{ wordDetail.pos }}</span>
          <button class="btn-ghost ml-auto" @click="closeWord">关闭 ✕</button>
        </div>
        <div v-if="wordDetail.meaning" class="mt-2 text-[14px] leading-6 text-ink-800">{{ wordDetail.meaning }}</div>
        <div v-if="wordDetail.example" class="mt-1 text-[13px] italic leading-6 text-ink-500">{{ wordDetail.example }}</div>
        <div v-if="wordDetail.stage || wordDetail.topic" class="mt-1 text-[11px] text-ink-400">{{ stageLabel(wordDetail.stage) }}<template v-if="wordDetail.topic"> · 主题「{{ wordDetail.topic }}」</template></div>

        <div v-if="wordLoading" class="mt-3 text-[12px] text-ink-400">正在取词详情…</div>
        <div v-else class="mt-3 space-y-2 text-[12px] leading-6">
          <div v-if="asList(wordDetail.collocations).length">
            <span class="font-semibold text-ink-700">常用搭配：</span>
            <span v-for="(c, ci) in asList(wordDetail.collocations)" :key="ci" class="tag-brand mr-1">{{ c }}</span>
          </div>
          <div v-if="wordDetail.roots"><span class="font-semibold text-ink-700">词根词缀：</span><span class="text-ink-600">{{ textOf(wordDetail.roots) }}</span></div>
          <div v-if="wordDetail.confusion"><span class="font-semibold text-ink-700">易混辨析：</span><span class="text-ink-600">{{ textOf(wordDetail.confusion) }}</span></div>
          <div v-if="wordDetail.memory_tip" class="rounded-control bg-amber-50 px-2.5 py-1.5 text-amber-700">
            <span class="font-semibold">记忆提示：</span>{{ textOf(wordDetail.memory_tip) }}
          </div>
          <div v-if="!asList(wordDetail.collocations).length && !wordDetail.roots && !wordDetail.confusion && !wordDetail.memory_tip" class="text-ink-400">
            这个词的搭配 / 词根 / 辨析 / 记忆提示还在逐词补充，先记住上面的释义和例句。
          </div>
        </div>

        <div class="mt-4 flex gap-2">
          <button class="btn-primary" @click="addWord(wordDetail.word)">＋ 加入生词本</button>
          <button class="btn-outline" @click="closeWord">返回词表</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'
import { saveBlob } from '../../../utils/download'

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

// ===== 单词详情弹层（接通 learnApi.word，字段缺失时优雅隐藏）=====
const wordDetail = ref(null)
const wordLoading = ref(false)
const wordDialogRef = ref(null)
const stageLabel = (s) => ({ primary: '小学', junior: '初中', senior: '高中' }[s] || '全部学段')
const asList = (v) => (Array.isArray(v) ? v : v ? [v] : [])
const textOf = (v) => {
  if (v === null || v === undefined || v === '') return ''
  if (Array.isArray(v)) return v.join('、')
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k}：${x}`).join('；')
  return String(v)
}
// #154 竞态守卫：记录本次请求的单词，回包与当前选中不一致则丢弃
let wordSeq = 0
async function openWord(w) {
  const seq = ++wordSeq
  wordLoading.value = true
  wordDetail.value = { word: w }
  try {
    const data = await learnApi.word(w)
    if (seq !== wordSeq) return
    wordDetail.value = data
  } catch (e) {
    if (seq !== wordSeq) return
    app.toastMsg(e?.message || '该词详情暂未收录', 'warn')
    wordDetail.value = null
  } finally {
    if (seq === wordSeq) wordLoading.value = false
  }
}
// #187 关闭时焦点归还原触发元素 + 解除滚动锁（由 watch 统一处理）
function closeWord() {
  wordSeq += 1  // 关闭后迟到的回包不再写入
  wordDetail.value = null
  wordLoading.value = false
}
// #187 滚动锁 + 焦点归还 + Esc 关闭
let wordLastActive = null
let wordPrevOverflow = ''
function onWordDialogKeydown(e) {
  if (e.key !== 'Escape') return
  e.stopPropagation()
  closeWord()
}
watch(() => !!wordDetail.value, async (open) => {
  if (open) {
    wordLastActive = document.activeElement
    wordPrevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onWordDialogKeydown)
    await nextTick()
    wordDialogRef.value?.focus()
  } else {
    document.body.style.overflow = wordPrevOverflow
    document.removeEventListener('keydown', onWordDialogKeydown)
    if (wordLastActive && typeof wordLastActive.focus === 'function') wordLastActive.focus()
    wordLastActive = null
  }
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onWordDialogKeydown)
  if (wordDetail.value) document.body.style.overflow = wordPrevOverflow
})

const dictation = ref([])
const dictAns = ref({})
const dN = ref(10)
const dStage = ref('')
async function loadDict() {
  dictAns.value = {}
  dictation.value = (await learnApi.dictation({ n: dN.value, stage: dStage.value })).list
}
// F543 逐词反馈：对 / 错标记 + 正确拼写高亮
function dictState(i) {
  const raw = dictAns.value[i]
  const answered = raw !== undefined && String(raw).trim() !== ''
  const correct = answered && String(raw).trim().toLowerCase() === String(dictation.value[i]?.answer || '').trim().toLowerCase()
  return { answered, correct }
}
const dictSummary = computed(() => {
  let total = 0, right = 0, wrong = 0, blank = 0
  dictation.value.forEach((d, i) => {
    if (!d.show) return
    total++
    const s = dictState(i)
    if (!s.answered) blank++
    else if (s.correct) right++
    else wrong++
  })
  return { total, right, wrong, blank }
})

// F531 听写错词自动入生词本（后端带来源标记 dictation、自动去重）
const collectedWrong = ref({})
const dictWrongWords = computed(() => {
  const out = []
  dictation.value.forEach((d, i) => {
    if (!d.show) return
    const s = dictState(i)
    if (s.answered && !s.correct && d.answer && !out.includes(d.answer) && !collectedWrong.value[d.answer]) out.push(d.answer)
  })
  return out
})
async function collectWrong(words) {
  const r = await learnApi.dictationCollect(words)
  words.forEach((w) => { collectedWrong.value[w] = true })
  app.toastMsg(r.added_count ? `已加入生词本 ${r.added_count} 词（跳过已存在 ${r.skipped.length}）` : '这些词已在生词本中', r.added_count ? 'success' : 'warn')
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

// 386 生词本导入 / 导出（换端不丢）
const showImport = ref(false)
const impFmt = ref('csv')
const impText = ref('')
const impMsg = ref('')
const importing = ref(false)
async function exportBook() {
  try {
    const blob = await learnApi.exportWordbook('csv')
    saveBlob(blob, `wordbook_${new Date().toISOString().slice(0, 10)}.csv`)
    app.toastMsg('生词本已导出为 CSV', 'success')
  } catch (e) {
    app.toastMsg('导出失败：' + (e?.message || '网络异常'), 'error')
  }
}
async function importBook() {
  if (!impText.value.trim()) return app.toastMsg('请先粘贴要导入的内容', 'warn')
  importing.value = true
  impMsg.value = ''
  try {
    const r = await learnApi.importWordbook({ format: impFmt.value, text: impText.value })
    impMsg.value = `共 ${r.total} 行：新增 ${r.created} 个、跳过 ${r.skipped} 行（重复 ${r.duplicated || 0}）`
    if (r.errors?.length) impMsg.value += '；有 ' + r.errors.length + ' 行格式不对：' + r.errors.map((x) => `第${x.row}行 ${x.error}`).join('，')
    app.toastMsg(`导入完成：新增 ${r.created} 个单词`, 'success')
    await loadBook()
  } catch (e) {
    impMsg.value = ''
    app.toastMsg('导入失败：' + (e?.message || '格式或行内容有误'), 'error')
  } finally {
    importing.value = false
  }
}

async function switchTab(v) {
  tab.value = v
  if (v === 'book') await loadBook()
  if (v === 'ipa' && !Object.keys(ipa.value).length) ipa.value = (await learnApi.toolRun('ipa-table', {})).result.groups
}

onMounted(loadWords)
</script>
