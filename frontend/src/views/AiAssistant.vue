<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <h1 class="text-[18px] font-semibold text-ink-800">AI 助手</h1>
      <span class="tag" :class="status.configured ? 'tag-brand' : ''">
        {{ status.configured ? `大模型 · ${status.model}` : '本地降级模式' }}
      </span>
      <span v-if="status.recent_success_rate !== null && status.recent_success_rate !== undefined"
            class="text-[12px] text-ink-400">近期成功率 {{ status.recent_success_rate }}%</span>
      <button class="btn-outline ml-auto px-2 py-1 text-[12px]" @click="loadStatus">刷新状态</button>
    </div>

    <div v-if="status.setup_hint" class="card p-3 text-[12px] leading-relaxed text-ink-500">
      {{ status.setup_hint }}
      配置示例（Windows PowerShell）：<code class="rounded bg-ink-50 px-1">$env:LLM_API_KEY="sk-..."</code>
      <code class="ml-1 rounded bg-ink-50 px-1">$env:LLM_MODEL="gpt-4o-mini"</code>
    </div>

    <div class="flex gap-1 border-b border-ink-100 text-[13px]" role="tablist" aria-label="AI 助手分区">
      <button v-for="(t, i) in tabs" :key="t.v" role="tab" :aria-selected="tab === t.v" :tabindex="tab === t.v ? 0 : -1"
              class="border-b-2 px-4 py-2"
              :class="tab === t.v ? 'border-brand-500 font-medium text-brand-600' : 'border-transparent text-ink-500'"
              @click="tab = t.v" @keydown="onTabKey($event, i)">{{ t.label }}</button>
    </div>

    <!-- 对话 -->
    <div v-if="tab === 'chat'" class="grid gap-4 lg:grid-cols-[220px_1fr]">
      <div class="card p-3">
        <button class="btn-primary w-full py-1.5 text-[12px]" @click="newConversation">+ 新对话</button>
        <div class="mt-2 max-h-[52vh] space-y-1 overflow-y-auto">
          <button v-for="c in conversations" :key="c.id"
                  class="group flex w-full items-center gap-1 rounded-control px-2 py-1.5 text-left text-[12px]"
                  :class="c.id === conversationId ? 'bg-brand-50 text-brand-700' : 'hover:bg-ink-50'"
                  @click="openConversation(c.id)">
            <span class="min-w-0 flex-1 truncate">{{ c.title }}</span>
            <span class="shrink-0 text-[11px] text-ink-300 opacity-0 group-hover:opacity-100"
                  @click.stop="removeConversation(c.id)">×</span>
          </button>
          <div v-if="!conversations.length" class="py-4 text-center text-[12px] text-ink-400">暂无会话</div>
        </div>
      </div>

      <div class="card flex h-[62vh] flex-col">
        <div class="flex-1 space-y-3 overflow-y-auto p-4">
          <div v-if="!messages.length" class="grid h-full place-items-center text-center">
            <div>
              <div class="text-[32px]">🤖</div>
              <div class="mt-2 text-[13px] font-medium text-ink-700">问我任何问题</div>
              <div class="mt-1 text-[12px] text-ink-400">会优先检索你的笔记作为回答依据</div>
              <div class="mt-3 flex flex-wrap justify-center gap-2">
                <button v-for="s in samples" :key="s" class="btn-outline px-2 py-1 text-[12px]"
                        @click="ask(s)">{{ s }}</button>
              </div>
            </div>
          </div>
          <div v-for="(m, i) in messages" :key="i" class="flex" :class="m.role === 'user' ? 'justify-end' : 'justify-start'">
            <div class="max-w-[78%] rounded-card px-3 py-2 text-[13px] leading-relaxed"
                 :class="m.role === 'user' ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-700'">
              <div class="whitespace-pre-wrap">{{ m.content }}</div>
              <div v-if="m.references?.length" class="mt-1 border-t border-white/20 pt-1 text-[11px] opacity-70">
                引用：{{ m.references.map(r => r.title).join('、') }}
              </div>
            </div>
          </div>
          <div v-if="sending" class="text-[12px] text-ink-400">思考中…</div>
        </div>
        <div class="flex items-center gap-2 border-t border-ink-100 p-3">
          <label class="flex shrink-0 items-center gap-1 text-[12px] text-ink-500">
            <input v-model="useKnowledge" type="checkbox" /> 检索笔记
          </label>
          <input v-model="draft" class="input flex-1" placeholder="输入问题，Enter 发送"
                 @keydown.enter="onDraftEnter" />
          <button class="btn-primary px-3 py-1.5" :disabled="sending" @click="ask()">发送</button>
        </div>
      </div>
    </div>

    <!-- 出题 -->
    <div v-else-if="tab === 'quiz'" class="space-y-4">
      <div class="card p-4">
        <div class="grid gap-3 md:grid-cols-5">
          <div class="md:col-span-2">
            <label class="text-[12px] text-ink-500">知识点 / 主题</label>
            <input v-model="gen.topic" class="input mt-1" placeholder="例如：一元二次方程 / Python 列表" />
          </div>
          <div>
            <label class="text-[12px] text-ink-500">题型</label>
            <select v-model="gen.type" class="input mt-1">
              <option value="single">单选</option>
              <option value="judge">判断</option>
              <option value="fill">填空</option>
              <option value="subjective">主观</option>
              <option value="code">编程</option>
            </select>
          </div>
          <div>
            <label class="text-[12px] text-ink-500">题量</label>
            <input v-model.number="gen.count" type="number" min="1" max="10" class="input mt-1" />
          </div>
          <div>
            <label class="text-[12px] text-ink-500">难度 1-5</label>
            <input v-model.number="gen.difficulty" type="number" min="1" max="5" class="input mt-1" />
          </div>
        </div>
        <div class="mt-3 flex items-center gap-3">
          <button class="btn-primary" :disabled="generating" @click="generate">
            {{ generating ? '生成中…' : '生成题目' }}
          </button>
          <span v-if="genSource" class="text-[12px] text-ink-400">
            来源：{{ genSource === 'llm' ? '大模型生成' : '内置题库智能抽题' }}
          </span>
        </div>
      </div>

      <div v-if="generated.length" class="space-y-2">
        <div v-for="(q, i) in generated" :key="i" class="card p-3">
          <div class="flex items-start gap-2">
            <span class="tag shrink-0">{{ i + 1 }}</span>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] text-ink-800">{{ q.stem }}</div>
              <div v-if="q.options?.length" class="mt-1 space-y-0.5 text-[12px] text-ink-600">
                <div v-for="(o, oi) in q.options" :key="oi">{{ String.fromCharCode(65 + oi) }}. {{ o }}</div>
              </div>
              <details class="mt-1">
                <summary class="cursor-pointer text-[12px] text-brand-600">查看答案与解析</summary>
                <div class="mt-1 text-[12px] text-ink-600">
                  <div>答案：{{ formatAnswer(q) }}</div>
                  <div v-if="q.analysis" class="mt-0.5">解析：{{ q.analysis }}</div>
                </div>
              </details>
            </div>
          </div>
        </div>
      </div>

      <div class="card p-3">
        <div class="mb-2 text-[13px] font-medium text-ink-700">我的题目（{{ myQuestions.length }}）</div>
        <div class="max-h-64 space-y-1 overflow-y-auto">
          <div v-for="q in myQuestions" :key="q.id" class="flex items-center gap-2 text-[12px]">
            <span class="tag shrink-0">{{ q.question_type }}</span>
            <span class="min-w-0 flex-1 truncate text-ink-600">{{ q.stem }}</span>
            <button class="shrink-0 text-rose-500" @click="removeQuestion(q.id)">删除</button>
          </div>
          <div v-if="!myQuestions.length" class="py-3 text-center text-[12px] text-ink-400">暂无题目</div>
        </div>
      </div>
    </div>

    <!-- 批改 -->
    <div v-else class="space-y-4">
      <div class="card p-4">
        <div class="grid gap-3">
          <div>
            <label class="text-[12px] text-ink-500">题目</label>
            <textarea v-model="grade.question" rows="2" class="input mt-1 font-normal" placeholder="粘贴题目…"></textarea>
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <div>
              <label class="text-[12px] text-ink-500">参考答案</label>
              <textarea v-model="grade.reference" rows="4" class="input mt-1" placeholder="参考答案或评分要点…"></textarea>
            </div>
            <div>
              <label class="text-[12px] text-ink-500">我的作答</label>
              <textarea v-model="grade.answer" rows="4" class="input mt-1" placeholder="写下你的答案…"></textarea>
            </div>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <select v-model="grade.type" class="input w-32">
              <option value="subjective">主观题</option>
              <option value="code">编程题</option>
              <option value="single">单选</option>
              <option value="judge">判断</option>
              <option value="fill">填空</option>
            </select>
            <select v-model="grade.language" class="input w-32" :disabled="grade.type !== 'code'">
              <option value="python">Python</option>
              <option value="javascript">JavaScript</option>
              <option value="java">Java</option>
              <option value="cpp">C++</option>
              <option value="go">Go</option>
            </select>
            <label class="flex items-center gap-1 text-[12px] text-ink-500">
              <input v-model="grade.record" type="checkbox" /> 错题写入错题本
            </label>
            <button class="btn-primary" :disabled="grading" @click="doGrade">
              {{ grading ? '批改中…' : '开始批改' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="gradeResult" class="card p-4">
        <div class="flex items-center gap-3">
          <div class="text-[28px] font-semibold"
               :class="gradeResult.average_score >= 60 ? 'text-emerald-600' : 'text-rose-500'">
            {{ gradeResult.average_score }}
          </div>
          <div class="text-[12px] text-ink-500">
            <div>满分 100 · {{ gradeResult.passed }}/{{ gradeResult.total }} 通过</div>
            <div>提供方：{{ gradeResult.provider === 'llm' ? '大模型' : '本地启发式' }}</div>
          </div>
        </div>
        <div v-for="item in gradeResult.items" :key="item.index" class="mt-3 border-t border-ink-50 pt-3">
          <div class="text-[12px] font-medium"
               :class="item.correct ? 'text-emerald-600' : 'text-rose-500'">
            {{ item.correct ? '通过' : '未通过' }} · {{ item.score }} 分
          </div>
          <div class="mt-1 whitespace-pre-wrap text-[13px] text-ink-700">{{ item.feedback }}</div>
          <div v-if="item.missing_points?.length" class="mt-1 text-[12px] text-ink-500">
            建议补充：{{ item.missing_points.join('、') }}
          </div>
        </div>
        <div v-if="gradeResult.recorded_mistakes" class="mt-2 text-[12px] text-ink-400">
          已写入错题本 {{ gradeResult.recorded_mistakes }} 道
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { aiApi } from '../api'
import { useAppStore } from '../stores/app'

const app = useAppStore()
const tabs = [
  { v: 'chat', label: '对话助手' },
  { v: 'quiz', label: 'AI 出题' },
  { v: 'grade', label: 'AI 批改' },
]
const tab = ref('chat')
const status = ref({})

// #192 tab 语义：左右方向键 / Home / End 切换
function onTabKey(e, i) {
  const n = tabs.length
  let next = -1
  if (e.key === 'ArrowRight') next = (i + 1) % n
  else if (e.key === 'ArrowLeft') next = (i - 1 + n) % n
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = n - 1
  if (next < 0) return
  e.preventDefault()
  tab.value = tabs[next].v
  e.currentTarget?.parentElement?.querySelectorAll('[role="tab"]')[next]?.focus()
}

// 对话
const conversations = ref([])
const conversationId = ref(null)
const messages = ref([])
const draft = ref('')
const sending = ref(false)
const useKnowledge = ref(true)
const samples = ['帮我总结我的笔记要点', '解释一下 CRDT 的核心思想', '给我一份 Python 学习路线']

// 出题
const gen = reactive({ topic: '', type: 'single', count: 5, difficulty: 2 })
const generating = ref(false)
const generated = ref([])
const genSource = ref('')
const myQuestions = ref([])

// 批改
const grade = reactive({ question: '', reference: '', answer: '', type: 'subjective', language: 'python', record: true })
const grading = ref(false)
const gradeResult = ref(null)

async function loadStatus() {
  try { status.value = await aiApi.status() } catch (e) { /* ignore */ }
}
async function loadConversations() {
  const r = await aiApi.conversations()
  conversations.value = r.list || []
}
async function newConversation() {
  conversationId.value = null
  messages.value = []
}
// #156 竞态守卫：快速点两个会话时，只允许「仍选中」的那次响应写入消息
let convSeq = 0
async function openConversation(id) {
  const seq = ++convSeq
  conversationId.value = id
  const r = await aiApi.conversation(id)
  if (seq !== convSeq || conversationId.value !== id) return
  messages.value = (r.messages || []).map((m) => ({ role: m.role, content: m.content, references: m.references }))
}
async function removeConversation(id) {
  await aiApi.deleteConversation(id)
  if (conversationId.value === id) newConversation()
  loadConversations()
}
// #151 输入法组合态（选词回车）不提交
function onDraftEnter(e) {
  if (e.isComposing || e.keyCode === 229) return
  ask()
}
async function ask(preset) {
  const fromDraft = !preset
  const text = (preset || draft.value || '').trim()
  if (!text || sending.value) return
  messages.value.push({ role: 'user', content: text })
  sending.value = true
  try {
    const r = await aiApi.chat(text, { conversation_id: conversationId.value, use_knowledge: useKnowledge.value })
    conversationId.value = r.conversation_id
    messages.value.push({ role: 'assistant', content: r.reply, references: r.references })
    // 成功后再清空输入，且只清掉本次发送的内容（发送期间用户可能又输入了新文字）
    if (fromDraft && draft.value.trim() === text) draft.value = ''
    loadConversations()
  } catch (e) {
    // 失败时把原文放回输入框，用户不用重打
    if (fromDraft && !draft.value.trim()) draft.value = text
    messages.value.push({ role: 'assistant', content: `请求失败：${e.message || e}` })
  } finally {
    sending.value = false
  }
}

function formatAnswer(q) {
  if (typeof q.answer === 'number' && q.options?.length) {
    return `${String.fromCharCode(65 + q.answer)}. ${q.options[q.answer] ?? ''}`
  }
  return String(q.answer ?? '')
}
async function generate() {
  if (!gen.topic.trim()) return app.toastMsg('请填写知识点', 'error')
  generating.value = true
  try {
    const r = await aiApi.generateQuestions({ ...gen, save: true })
    generated.value = r.items || []
    genSource.value = r.source
    app.toastMsg(`已生成 ${r.count} 道题`, 'success')
    loadMyQuestions()
  } catch (e) {
    app.toastMsg(e.message || '生成失败', 'error')
  } finally {
    generating.value = false
  }
}
async function loadMyQuestions() {
  const r = await aiApi.myQuestions()
  myQuestions.value = r.list || []
}
async function removeQuestion(id) {
  await aiApi.deleteQuestions([id])
  loadMyQuestions()
}
async function doGrade() {
  if (!grade.answer.trim()) return app.toastMsg('请填写你的作答', 'error')
  grading.value = true
  try {
    gradeResult.value = await aiApi.grade([{
      question: grade.question,
      reference_answer: grade.reference,
      user_answer: grade.answer,
      type: grade.type,
      language: grade.language,
    }], grade.record)
  } catch (e) {
    app.toastMsg(e.message || '批改失败', 'error')
  } finally {
    grading.value = false
  }
}

onMounted(() => { loadStatus(); loadConversations(); loadMyQuestions() })
</script>
