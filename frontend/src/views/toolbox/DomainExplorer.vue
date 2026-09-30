<template>
  <div class="mx-auto max-w-7xl">
    <!-- 头部 -->
    <div class="mb-4 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">{{ domainName }}</h2>
        <p class="text-[12px] text-ink-400">
          {{ subs.length }} 个子系统 · 共 {{ eps.length }} 个接口 · 目录驱动（catalog 返回什么就渲染什么，后端加接口无需改前端）
        </p>
      </div>
      <input v-model="kw" class="input w-56" placeholder="搜索接口路径…" />
    </div>

    <div v-if="!ready" class="card grid h-64 place-items-center text-[13px] text-ink-400">目录加载中…</div>

    <div v-else class="grid grid-cols-12 gap-4">
      <!-- 子系统列 -->
      <div class="col-span-3 max-h-[72vh] space-y-1 overflow-y-auto pr-1">
        <button
          v-for="s in filteredSubs"
          :key="s.key"
          class="block w-full rounded-control px-2.5 py-2 text-left transition-colors"
          :class="subKey === s.key ? 'bg-brand-600 text-white' : 'hover:bg-ink-100'"
          @click="pickSub(s.key)"
        >
          <div class="text-[13px] font-medium" :class="subKey === s.key ? 'text-white' : 'text-ink-700'">{{ s.name }}</div>
          <div class="text-[11px]" :class="subKey === s.key ? 'text-white/70' : 'text-ink-400'">{{ s.key }} · {{ s.eps.length }} 接口</div>
        </button>
        <div v-if="!filteredSubs.length" class="px-2 py-6 text-center text-[12px] text-ink-400">没有匹配的子系统</div>
      </div>

      <!-- 接口列 -->
      <div class="col-span-4 card max-h-[72vh] overflow-y-auto p-2">
        <div
          v-for="ep in curSub?.eps || []"
          :key="ep.path"
          class="mb-1 block w-full cursor-pointer rounded-control px-2.5 py-1.5 text-left transition-colors"
          :class="cur?.path === ep.path ? 'bg-ink-100 ring-1 ring-brand-500/40' : 'hover:bg-ink-50'"
          @click="pickEp(ep)"
        >
          <div class="flex items-center gap-1.5">
            <span
              class="rounded-pill px-1.5 py-0.5 font-mono text-[10px] font-semibold"
              :class="(ep.methods[0] || 'POST') === 'GET' ? 'bg-sky-100 text-sky-700' : 'bg-violet-100 text-violet-700'"
            >{{ ep.methods[0] || 'POST' }}</span>
            <span class="truncate font-mono text-[12px] text-ink-700">{{ ep.path }}</span>
          </div>
        </div>
        <div v-if="!(curSub?.eps || []).length" class="px-2 py-6 text-center text-[12px] text-ink-400">该子系统没有匹配的接口</div>
      </div>

      <!-- 执行器列 -->
      <div class="col-span-5">
        <div class="card p-4" v-if="cur">
          <div class="mb-2 flex items-center gap-2">
            <h3 class="font-mono text-[13px] font-semibold text-ink-800">{{ domain }}/{{ cur.path }}</h3>
          </div>

          <div class="mb-2 flex items-center gap-2">
            <select v-model="method" class="input w-24 font-mono text-[12px]">
              <option v-for="m in methodOptions" :key="m" :value="m">{{ m }}</option>
            </select>
            <input v-model="pathInput" class="input flex-1 font-mono text-[12px]" spellcheck="false" />
          </div>
          <p v-if="/<[a-z:]+>/.test(pathInput)" class="mb-2 text-[11px] text-amber-600">
            路径含占位符（如 &lt;int:pk&gt;），请在上方替换为实际 ID 后执行
          </p>

          <label class="mb-1 block text-[12px] font-medium text-ink-600">
            {{ method === 'GET' ? '查询参数（JSON，作为 query string 发送）' : '请求体（JSON）' }}
          </label>
          <textarea v-model="bodyText" class="input h-36 resize-none font-mono text-[12px]" spellcheck="false"></textarea>

          <div class="mt-3 flex items-center gap-2">
            <button class="btn-primary" :disabled="running" @click="run">{{ running ? '请求中…' : '执 行' }}</button>
            <button class="btn-outline" @click="resetBody">重置参数</button>
            <button class="btn-ghost" @click="copyResult">复制响应</button>
          </div>

          <div v-if="result !== null" class="mt-3">
            <div class="mb-1 flex items-center gap-2">
              <span class="text-[12px] font-medium text-ink-600">响应</span>
              <span
                class="rounded-pill px-2 py-0.5 text-[10px] font-semibold"
                :class="result.ok ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'"
              >{{ result.ok ? '成功' : '失败' }}</span>
            </div>
            <pre class="max-h-80 overflow-auto whitespace-pre-wrap rounded-control bg-ink-900 p-3 font-mono text-[12px] leading-relaxed text-ink-100">{{ prettyResult }}</pre>
          </div>
        </div>
        <div v-else class="card grid h-64 place-items-center text-[13px] text-ink-400">从左侧选择一个接口开始调试</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { suiteApi } from '../../api'
import { useAppStore } from '../../stores/app'

const props = defineProps({
  domain: { type: String, required: true },
})

const app = useAppStore()
const ready = ref(false)
const domainName = ref('')
const subs = ref([]) // [{key,name,eps:[{path,methods}]}]
const eps = ref([]) // 全部接口明细
const subKey = ref('')
const kw = ref('')

const cur = ref(null) // {path, methods}
const method = ref('POST')
const pathInput = ref('')
const bodyText = ref('{}')
const result = ref(null)
const running = ref(false)
const methodOptions = ['GET', 'POST']

// officesuite 三个 URL 前缀与子系统 key 不同（form/ticket/todo），目录分组用别名归位
const SUB_ALIAS = { todo: 'todobox', form: 'formcollect', ticket: 'helpdesk' }

// 常用接口参数模板：按路径前缀给个能跑的示例，省得用户对着空 {} 猜
const BODY_HINTS = [
  [/^text\//, { text: '你好，World！Hello 123' }],
  [/^str\//, { text: '  Hello World  ' }],
  [/^md\//, { text: '# 标题\n\n- 项目一\n- 项目二' }],
  [/^json\//, { text: '{"a":1,"b":{"c":2},"d":[3,4]}' }],
  [/^regex\//, { pattern: '\\d+', text: '订单 123 和 456' }],
  [/^encode\//, { text: '待编码内容' }],
  [/^hash\//, { text: '哈希内容' }],
  [/^token\//, { text: 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOjF9.x' }],
  [/^code\//, { text: 'function f(){return 1}' }],
  [/^diff\//, { a: '第一版内容', b: '第二版内容' }],
  [/^web\//, { text: 'https://example.com/api?x=1' }],
  [/^db\//, { sql: 'SELECT id, name FROM users WHERE age > 18' }],
  [/^num\//, { value: '255', from_base: 10 }],
  [/^color\//, { color1: '#0ea5e9', color2: '#f97316' }],
  [/^cron\//, { expr: '0 9 * * 1-5' }],
  [/^math\//, {}],
  [/^fake\//, { count: 5 }],
  [/^asciiart\//, { text: 'HELLO' }],
  [/^(profile|transform|calc)\//, { rows: [{ name: '甲', v: 10 }, { name: '乙', v: 20 }] }],
  [/^stats\//, { a: [12, 15, 13, 16, 14], b: [18, 20, 19, 21, 22] }],
  [/^(forecast|regress)\//, { y: [10, 12, 13, 15, 17] }],
  [/^nlp\//, { text: '自然语言处理是人工智能的重要方向' }],
  [/^vector\//, { a: [1, 2, 3], b: [4, 5, 6] }],
  [/^ai\//, { prompt: '用一句话介绍 OKR' }],
  [/^chart\//, { values: [3, 7, 2, 9, 4] }],
  [/^geo\//, { lat1: 39.9, lng1: 116.4, lat2: 31.2, lng2: 121.5 }],
]

const curSub = computed(() => subs.value.find((s) => s.key === subKey.value) || null)

const filteredSubs = computed(() => {
  if (!kw.value) return subs.value
  const k = kw.value.toLowerCase()
  return subs.value
    .map((s) => ({
      ...s,
      eps: s.eps.filter((e) => e.path.toLowerCase().includes(k) || s.name.toLowerCase().includes(k) || s.key.includes(k)),
    }))
    .filter((s) => s.eps.length)
})

const prettyResult = computed(() => {
  if (result.value === null) return ''
  try {
    return JSON.stringify(result.value, null, 2)
  } catch (e) {
    return String(result.value)
  }
})

function guessBody(path) {
  for (const [re, v] of BODY_HINTS) {
    if (re.test(path)) return v
  }
  return {}
}

function resetBody() {
  bodyText.value = JSON.stringify(guessBody(cur.value?.path || ''), null, 2)
}

function pickSub(key) {
  subKey.value = key
  const first = curSub.value?.eps?.[0]
  if (first) pickEp(first)
}

function pickEp(ep) {
  cur.value = ep
  method.value = ep.methods[0] || 'POST'
  methodOptions.value = ep.methods.length > 1 ? ['GET', 'POST'] : [ep.methods[0]]
  pathInput.value = ep.path
  result.value = null
  resetBody()
}

async function run() {
  let payload = null
  const raw = bodyText.value.trim()
  if (raw) {
    try {
      payload = JSON.parse(raw)
    } catch (e) {
      app.toastMsg(`JSON 解析失败: ${e.message}`, 'error')
      return
    }
  }
  running.value = true
  result.value = null
  try {
    const path_ = pathInput.value.replace(/^\/+/, '')
    const r = await suiteApi.call(props.domain, path_, method.value, payload)
    result.value = { ok: true, data: r }
  } catch (e) {
    result.value = { ok: false, error: e.message }
  } finally {
    running.value = false
  }
}

async function copyResult() {
  if (result.value === null) return
  try {
    await navigator.clipboard.writeText(prettyResult.value)
    app.toastMsg('已复制', 'success')
  } catch (e) {
    /* ignore */
  }
}

onMounted(async () => {
  try {
    const r = await suiteApi.catalog(props.domain)
    const d = r.data || {}
    domainName.value = d.domain_name || props.domain
    eps.value = d.endpoints || []
    const keys = (d.subsystems || []).map((s) => s.key)
    // 按子系统 key 分组（URL 首段 → key，含别名归位）
    const byKey = {}
    for (const ep of eps.value) {
      const seg = ep.path.split('/')[0]
      const key = keys.includes(seg) ? seg : (SUB_ALIAS[seg] || seg)
      ;(byKey[key] = byKey[key] || []).push(ep)
    }
    subs.value = (d.subsystems || [])
      .map((s) => ({ ...s, eps: byKey[s.key] || [] }))
      .filter((s) => s.eps.length)
    // 目录没覆盖到的散落分组（防御性）：补到末尾
    const known = new Set(subs.value.map((s) => s.key))
    for (const [k2, list] of Object.entries(byKey)) {
      if (!known.has(k2)) subs.value.push({ key: k2, name: k2, eps: list })
    }
    ready.value = true
    if (subs.value.length) pickSub(subs.value[0].key)
  } catch (e) {
    app.toastMsg('目录加载失败', 'error')
    ready.value = true
  }
})
</script>
