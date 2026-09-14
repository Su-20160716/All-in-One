<template>
  <div class="mx-auto max-w-6xl">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">学习工具箱</h2>
        <p class="text-[12px] text-ink-400">共 {{ total }} 个服务端计算工具，覆盖数理计算、英语、化学、学习方法</p>
      </div>
      <input v-model="kw" class="input w-56" placeholder="搜索工具…" />
    </div>

    <div class="grid grid-cols-12 gap-4">
      <div class="col-span-3 space-y-3">
        <div v-for="(items, cat) in filteredCatalog" :key="cat" class="card p-2">
          <div class="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">{{ cat }}</div>
          <button v-for="t in items" :key="t.key" class="block w-full rounded-control px-2 py-1.5 text-left text-[13px] transition-colors"
            :class="activeKey === t.key ? 'bg-brand-600 text-white' : 'text-ink-600 hover:bg-ink-100'" @click="pick(t)">{{ t.name }}</button>
        </div>
      </div>

      <div class="col-span-9">
        <div v-if="current" class="card p-5">
          <div class="mb-1 flex items-center gap-2">
            <h3 class="text-[15px] font-semibold text-ink-800">{{ current.name }}</h3>
            <span class="tag-brand">{{ current.cat }}</span><span class="font-mono text-[11px] text-ink-400">{{ current.key }}</span>
          </div>
          <p class="mb-3 text-[12px] text-ink-400">{{ current.desc }}</p>

          <label class="block">
            <span class="mb-1 block text-[12px] font-medium text-ink-600">参数（JSON，可直接修改示例）</span>
            <textarea v-model="paramText" class="input h-44 resize-none font-mono text-[12px]" spellcheck="false"></textarea>
          </label>
          <div class="mt-3 flex items-center gap-2">
            <button class="btn-primary" :disabled="running" @click="run">{{ running ? '计算中…' : '执 行' }}</button>
            <button class="btn-outline" @click="resetParam">重置示例</button>
            <button class="btn-ghost" @click="copyResult">复制结果</button>
            <span v-if="err" class="text-[12px] text-rose-500">{{ err }}</span>
          </div>

          <div v-if="result !== null" class="mt-4">
            <div class="mb-1 text-[12px] font-medium text-ink-600">结果</div>
            <pre class="max-h-[26rem] overflow-auto whitespace-pre-wrap rounded-control bg-ink-900 p-3 font-mono text-[12px] leading-relaxed text-ink-100">{{ pretty }}</pre>
          </div>
        </div>
        <div v-else class="card grid h-64 place-items-center text-[13px] text-ink-400">从左侧选择一个学习工具</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { learnApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const catalog = ref({})
const total = ref(0)
const kw = ref('')
const activeKey = ref('')
const current = ref(null)
const paramText = ref('{}')
const result = ref(null)
const running = ref(false)
const err = ref('')

// 每个工具的示例入参（无则空对象，工具内部用默认值）
const EXAMPLES = {
  'arith-gen': { n: 8, op: 'mixed', max: 100 }, 'fraction-simplify': { a: 12, b: 18 },
  'gcd-lcm': { nums: '12,18,24' }, prime: { n: 360 }, roman: { mode: 'to_roman', n: 2024 },
  quadratic: { a: 1, b: -5, c: 6 }, linear2: { a1: 1, b1: 1, c1: 5, a2: 1, b2: -1, c2: 1 },
  sequence: { kind: 'arithmetic', a1: 2, d: 3, n: 10 }, 'plane-geo': { shape: 'trapezoid', dims: '3,4,2' },
  'solid-geo': { shape: 'sphere', dims: '2' }, percent: { part: 25, whole: 80 },
  'unit-convert': { table: 'length', value: 1, from: 'km', to: 'm' }, temp: { value: 100, from: 'c' },
  'molar-mass': { formula: 'H2SO4' },
  'balance-check': { left: [{ f: 'Fe', n: 3 }, { f: 'O2', n: 2 }], right: [{ f: 'Fe3O4', n: 1 }] },
  'en-word-freq': { text: 'I like apples. I like milk. Apples are good.' },
  'en-readability': { text: 'The cat sat on the mat. It was a warm and sunny day. We played in the small green garden.' },
  'en-inflect': { word: 'study' }, pinyin: { text: '学习中文水山' },
  'composition-count': { text: '我爱学习。Learning is fun!\n\n第二段 here。' },
  'score-stats': { scores: '66,77,88,99,100,77' }, rank: { scores: '90,80,90,70', method: 'dense' },
  gpa: { score: 87 }, ebbinghaus: { start: '2026-09-11' }, pomodoro: { sessions: '25,25,50,65' },
  'roll-call': { names: '张三,李四,王五,赵六', n: 2 }, group: { names: 'a,b,c,d,e,f', by: 'count', count: 3 },
  'study-plan': { total: 100, days: 7, rest_every: 4, start: '2026-09-11' },
  'flashcard-sched': { level: 2, rating: 'good' }, 'truth-table': { expr: 'A and (B or not C)' },
  'study-time': { start: '08:30', end: '10:15' }, rmb: { number: 1234.56 },
  'calendar-math': { year: 2024, date: '2026-09-11', start: '2026-09-01', end: '2026-09-11' },
  'clock-drill': { n: 5 }, pattern: { n: 4, kind: 'arithmetic' }, 'ipa-table': {},
  'multiplication-table': { mode: 'drill', n: 8 }, 'unit-rate-table': {},
  probability: { kind: 'dice', n: 200 },
  'points-to-flashcard': { text: '光合作用：植物利用光能合成有机物\n呼吸作用：分解有机物释放能量\n- 牛顿第二定律：F=ma' },
}

const filteredCatalog = computed(() => {
  const out = {}
  for (const [cat, items] of Object.entries(catalog.value)) {
    const hit = items
      .filter((t) => !kw.value || t.name.includes(kw.value) || t.key.includes(kw.value) || t.desc.includes(kw.value))
      .map((t) => ({ ...t, cat }))
    if (hit.length) out[cat] = hit
  }
  return out
})
const pretty = computed(() => JSON.stringify(result.value, null, 2))

function pick(t) {
  activeKey.value = t.key
  current.value = t
  result.value = null
  err.value = ''
  resetParam()
}
function resetParam() { paramText.value = JSON.stringify(EXAMPLES[current.value.key] ?? {}, null, 2) }
async function run() {
  let params
  try { params = JSON.parse(paramText.value || '{}') } catch (e) { err.value = '参数不是合法 JSON'; return }
  running.value = true; err.value = ''
  try {
    result.value = (await learnApi.toolRun(activeKey.value, params)).result
  } catch (e) {
    err.value = e.response?.data?.message || '执行失败'
  } finally { running.value = false }
}
async function copyResult() {
  if (result.value === null) return
  await navigator.clipboard.writeText(pretty.value)
  app.toastMsg('结果已复制', 'success')
}

onMounted(async () => {
  const data = await learnApi.toolCatalog()
  catalog.value = data.categories
  total.value = data.total
})
</script>
