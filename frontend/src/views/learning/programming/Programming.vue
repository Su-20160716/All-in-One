<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">编程语言广场</h2>
        <p class="text-[12px] text-ink-400">10 种主流语言的元信息、学习路线、语法速查、课程与代码片段</p>
      </div>
      <div class="flex gap-1 rounded-control bg-ink-100 p-1">
        <button v-for="t in topTabs" :key="t.v" class="rounded-control px-3 py-1 text-[12px]"
          :class="topTab === t.v ? 'bg-white text-brand-700 shadow-sm' : 'text-ink-500'" @click="topTab = t.v">{{ t.label }}</button>
      </div>
    </div>

    <!-- 语言广场 -->
    <div v-if="topTab === 'square'" class="grid grid-cols-12 gap-4">
      <div class="col-span-3 space-y-1.5">
        <button v-for="l in langs" :key="l.key" class="card flex w-full items-center gap-2.5 p-2.5 text-left transition-shadow"
          :class="cur === l.key ? 'ring-2 ring-brand-500' : 'hover:shadow-pop'" @click="openLang(l.key)">
          <span class="text-[18px]">{{ l.icon }}</span>
          <span class="flex-1 text-[13px] font-medium text-ink-800">{{ l.name }}</span>
          <span class="tag">难度{{ l.difficulty }}</span>
        </button>
      </div>

      <div class="col-span-9">
        <div v-if="!cur" class="card grid h-72 place-items-center text-[13px] text-ink-400">从左侧选择一门语言</div>
        <div v-else class="card p-5">
          <div class="flex flex-wrap items-center gap-3">
            <span class="text-[28px]">{{ detail.icon }}</span>
            <div>
              <h3 class="text-[17px] font-semibold text-ink-900">{{ detail.name }} <span class="text-[12px] font-normal text-ink-400">{{ detail.en }}</span></h3>
              <div class="mt-0.5 flex flex-wrap gap-1.5 text-[11px] text-ink-500">
                <span class="tag">{{ detail.year }} 年诞生</span><span class="tag">{{ detail.designer }}</span>
                <span class="tag">{{ detail.typing }}</span>
              </div>
            </div>
            <button class="btn-outline ml-auto" @click="bookmark">收藏片段/语言</button>
          </div>

          <div class="mt-4 flex flex-wrap gap-1 border-b border-ink-100 pb-2">
            <button v-for="s in subTabs" :key="s.v" class="rounded-pill px-3 py-1 text-[12px]"
              :class="subTab === s.v ? 'bg-brand-600 text-white' : 'text-ink-500 hover:bg-ink-100'" @click="loadSub(s.v)">{{ s.label }}</button>
          </div>

          <div class="pt-4 text-[13px] leading-7 text-ink-700">
            <!-- 概览 -->
            <div v-if="subTab === 'overview'" class="space-y-3">
              <p>{{ detail.summary }}</p>
              <div><span class="font-semibold text-ink-800">为什么学它：</span>
                <ul class="ml-4 list-disc"><li v-for="(w, i) in detail.why" :key="i">{{ w }}</li></ul>
              </div>
              <div class="flex flex-wrap gap-1.5"><span class="font-semibold text-ink-800">范式：</span><span v-for="p in detail.paradigms" :key="p" class="tag-brand">{{ p }}</span></div>
              <div class="flex flex-wrap gap-1.5"><span class="font-semibold text-ink-800">领域：</span><span v-for="d in detail.domains" :key="d" class="tag">{{ d }}</span></div>
              <div><span class="font-semibold text-ink-800">Hello World：</span>
                <pre class="mt-1 rounded-control bg-ink-900 p-3 font-mono text-[12px] text-ink-100">{{ detail.hello }}</pre>
              </div>
            </div>

            <!-- 路线 -->
            <ol v-else-if="subTab === 'roadmap'" class="space-y-3">
              <li v-for="(r, i) in cache.roadmap" :key="i" class="rounded-control border border-ink-100 p-3">
                <div class="flex items-center gap-2"><span class="tag-brand">{{ r.stage }}</span><span class="font-semibold text-ink-800">{{ r.title }}</span></div>
                <div class="mt-1 text-ink-600">目标：{{ r.goal }}</div>
                <div class="mt-1 flex flex-wrap gap-1.5"><span v-for="t in r.items" :key="t" class="tag">{{ t }}</span></div>
              </li>
            </ol>

            <!-- 速查 -->
            <div v-else-if="subTab === 'cheatsheet'" class="grid gap-2 md:grid-cols-2">
              <div v-for="(c, i) in cache.cheatsheet" :key="i" class="rounded-control border border-ink-100 p-2.5">
                <div class="mb-1 text-[12px] font-semibold text-ink-700">{{ c.point }}</div>
                <pre class="overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ c.code }}</pre>
              </div>
            </div>

            <!-- 关键字 -->
            <div v-else-if="subTab === 'keywords'" class="space-y-3">
              <div class="flex flex-wrap gap-1.5">
                <button v-for="k in cache.keywords" :key="k.word || k" class="rounded-pill bg-ink-900 px-2.5 py-1 font-mono text-[12px] text-ink-100 transition hover:bg-brand-600"
                  :class="selKeyword === (k.word || k) ? 'bg-brand-600 ring-2 ring-brand-400' : ''"
                  @click="selectKeyword(k)">{{ k.word || k }}</button>
              </div>
              <div v-if="keywordDetail" class="rounded-control border border-brand-200 bg-brand-50 p-4">
                <div class="flex items-center gap-2">
                  <span class="font-mono text-[16px] font-bold text-brand-700">{{ keywordDetail.word }}</span>
                  <span class="tag-brand">关键字详解</span>
                </div>
                <div class="mt-2 text-[13px] text-ink-700"><span class="font-semibold">定义：</span>{{ keywordDetail.desc }}</div>
                <div class="mt-2 text-[13px] text-ink-700"><span class="font-semibold">语法：</span><code class="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-[12px]">{{ keywordDetail.syntax }}</code></div>
                <div class="mt-2">
                  <div class="text-[13px] font-semibold text-ink-700">示例：</div>
                  <pre class="mt-1 overflow-auto rounded-control bg-ink-900 p-3 font-mono text-[12px] text-ink-100">{{ keywordDetail.example }}</pre>
                </div>
              </div>
              <div v-else class="text-[12px] text-ink-400">点击上方任意关键字查看完整教学（定义、语法、示例）</div>
            </div>

            <!-- 模块用法 -->
            <div v-else-if="subTab === 'modules'" class="space-y-3">
              <div class="grid gap-2 md:grid-cols-2">
                <button v-for="m in cache.modules" :key="m.index" class="rounded-control border border-ink-100 p-3 text-left transition hover:border-brand-300 hover:shadow-sm"
                  :class="selModule === m.index ? 'border-brand-500 ring-2 ring-brand-200' : ''"
                  @click="selectModule(m.index)">
                  <div class="font-mono text-[13px] font-semibold text-brand-700">{{ m.name }}</div>
                  <div class="mt-1 text-[11px] text-ink-500 line-clamp-2">{{ m.desc }}</div>
                </button>
              </div>
              <div v-if="moduleDetail" class="rounded-control border border-brand-200 bg-white p-4 shadow-sm">
                <div class="flex items-center gap-2 border-b border-ink-100 pb-2">
                  <span class="font-mono text-[15px] font-bold text-brand-700">{{ moduleDetail.name }}</span>
                  <span class="tag-brand">模块完整用法</span>
                </div>
                <div class="mt-2 text-[13px] text-ink-700">{{ moduleDetail.desc }}</div>
                <div class="mt-3">
                  <div class="text-[13px] font-semibold text-ink-800">常用函数/方法：</div>
                  <div class="mt-1 flex flex-wrap gap-1">
                    <span v-for="(f, i) in moduleDetail.functions" :key="i" class="tag font-mono text-[11px]">{{ f }}</span>
                  </div>
                </div>
                <div class="mt-3">
                  <div class="text-[13px] font-semibold text-ink-800">完整示例代码：</div>
                  <pre class="mt-1 max-h-96 overflow-auto rounded-control bg-ink-900 p-3 font-mono text-[11px] text-ink-100">{{ moduleDetail.example }}</pre>
                </div>
                <div class="mt-3">
                  <div class="text-[13px] font-semibold text-ink-800">注意事项：</div>
                  <div class="mt-1 text-[12px] text-ink-600">{{ moduleDetail.tips }}</div>
                </div>
              </div>
              <div v-else class="text-[12px] text-ink-400">点击上方任意模块查看完整用法（函数列表、示例代码、注意事项）</div>
            </div>

            <!-- 类型 -->
            <div v-else-if="subTab === 'types'" class="grid gap-2 md:grid-cols-2">
              <div v-for="(t, i) in cache.types" :key="i" class="rounded-control border border-ink-100 p-2.5">
                <div class="font-mono text-[13px] font-semibold text-brand-700">{{ t.name }}</div>
                <div class="text-[12px] text-ink-500">{{ t.desc }}</div>
                <pre class="mt-1 rounded-control bg-ink-50 p-2 font-mono text-[11px] text-ink-700">{{ t.example }}</pre>
              </div>
            </div>

            <!-- 课程 -->
            <div v-else-if="subTab === 'lessons'" class="space-y-2">
              <div v-for="ls in cache.lessons" :key="ls.index" class="rounded-control border border-ink-100">
                <button class="flex w-full items-center justify-between p-3 text-left" @click="openLesson(ls.index)">
                  <span class="font-semibold text-ink-800">{{ ls.title }}</span><span class="text-[12px] text-ink-400">{{ ls.summary }}</span>
                </button>
                <div v-if="lesson && lessonIdx === ls.index" class="border-t border-ink-100 p-3">
                  <ul class="ml-4 list-disc text-[12px] text-ink-600"><li v-for="(p, i) in lesson.points" :key="i">{{ p }}</li></ul>
                  <pre class="mt-2 overflow-auto rounded-control bg-ink-900 p-2.5 font-mono text-[11px] text-ink-100">{{ lesson.code }}</pre>
                </div>
              </div>
            </div>

            <!-- 片段 -->
            <div v-else-if="subTab === 'snippets'" class="space-y-2">
              <div v-for="s in cache.snippets" :key="s.index" class="rounded-control border border-ink-100 p-3">
                <div class="flex items-center gap-2"><span class="font-semibold text-ink-800">{{ s.title }}</span><span class="tag">{{ s.topic }}</span></div>
                <pre class="mt-1.5 overflow-auto rounded-control bg-ink-900 p-2.5 font-mono text-[11px] text-ink-100">{{ s.code }}</pre>
                <div class="mt-1 text-[12px] text-ink-500">{{ s.explain }}</div>
              </div>
            </div>

            <!-- 环境 -->
            <div v-else-if="subTab === 'ide'" class="grid gap-2 md:grid-cols-2">
              <div v-for="(e, i) in cache.ide" :key="i" class="rounded-control border border-ink-100 p-3">
                <div class="font-semibold text-ink-800">{{ e.name }}</div><div class="text-[12px] text-ink-500">{{ e.desc }}</div>
              </div>
            </div>

            <!-- 规范 -->
            <ul v-else-if="subTab === 'style'" class="ml-4 list-disc space-y-1">
              <li v-for="(s, i) in cache.style" :key="i">{{ s }}</li>
            </ul>

            <!-- 报错 -->
            <div v-else-if="subTab === 'errors'" class="space-y-2">
              <div v-for="(e, i) in cache.errors" :key="i" class="rounded-control border border-ink-100 p-3">
                <div class="font-mono text-[13px] font-semibold text-rose-600">{{ e.error }}</div>
                <div class="text-[12px] text-ink-600">原因：{{ e.cause }}</div>
                <div class="text-[12px] text-emerald-600">解决：{{ e.fix }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 语言对比 -->
    <div v-else-if="topTab === 'compare'" class="card p-5">
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <span class="text-[13px] text-ink-600">选择 2-3 门：</span>
        <button v-for="l in langs" :key="l.key" class="tag cursor-pointer"
          :class="cmpKeys.includes(l.key) ? 'bg-brand-600 text-white' : ''" @click="toggleCmp(l.key)">{{ l.name }}</button>
        <button class="btn-primary ml-auto" @click="runCompare">开始对比</button>
      </div>
      <table v-if="cmp.rows.length" class="w-full border-collapse">
        <thead><tr class="border-b border-ink-100">
          <th class="th w-32">维度</th>
          <th v-for="k in cmp.keys" :key="k" class="th">{{ cmp.names[k] }}</th>
        </tr></thead>
        <tbody>
          <tr v-for="(r, i) in cmp.rows" :key="i" class="border-b border-ink-50">
            <td class="td font-medium text-ink-500">{{ r.dimension }}</td>
            <td v-for="k in cmp.keys" :key="k" class="td">{{ fmt(r[k]) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 术语词典 -->
    <div v-else-if="topTab === 'glossary'" class="card p-5">
      <div class="mb-3 flex gap-2">
        <input v-model="glossQ" class="input w-64" placeholder="搜索术语，如 递归、指针" @keyup.enter="loadGloss" />
        <button class="btn-primary" @click="loadGloss">搜索</button>
        <div class="flex flex-wrap gap-1">
          <button v-for="t in glossTags" :key="t" class="tag cursor-pointer" :class="glossTag === t ? 'bg-brand-600 text-white' : ''" @click="pickTag(t)">{{ t }}</button>
        </div>
      </div>
      <div class="grid gap-2 md:grid-cols-2">
        <div v-for="(g, i) in gloss" :key="i" class="rounded-control border border-ink-100 p-3">
          <div class="text-[13px] font-semibold text-ink-800">{{ g.term }}</div>
          <div class="text-[12px] text-ink-500">{{ g.desc }}</div>
        </div>
      </div>
    </div>

    <!-- 范式/算法/结构 -->
    <div v-else class="space-y-4">
      <div class="card p-5">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">六大编程范式</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="p in paradigms" :key="p.key" class="rounded-control border border-ink-100 p-3">
            <div class="font-semibold text-ink-800">{{ p.name }}</div>
            <div class="text-[12px] text-ink-500">{{ p.idea }}</div>
            <pre class="mt-1 rounded-control bg-ink-50 p-2 font-mono text-[11px] text-ink-700">{{ p.example }}</pre>
          </div>
        </div>
      </div>
      <div class="card p-5">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">14 个入门算法</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="a in algorithms" :key="a.key" class="rounded-control border border-ink-100 p-3">
            <div class="flex items-center gap-2"><span class="font-semibold text-ink-800">{{ a.name }}</span><span class="tag-brand">{{ a.level }}</span></div>
            <div class="text-[12px] text-ink-500">{{ a.idea }}</div>
            <div class="mt-1 flex flex-wrap gap-1"><span v-for="p in a.points" :key="p" class="tag">{{ p }}</span></div>
          </div>
        </div>
      </div>
      <div class="card p-5">
        <h3 class="mb-3 text-[15px] font-semibold text-ink-800">12 种核心数据结构</h3>
        <div class="grid gap-2 md:grid-cols-2">
          <div v-for="d in dataStructures" :key="d.key" class="rounded-control border border-ink-100 p-3">
            <div class="font-semibold text-ink-800">{{ d.name }}</div>
            <div class="text-[12px] text-emerald-600">优：{{ d.pros }}</div>
            <div class="text-[12px] text-rose-500">劣：{{ d.cons }}</div>
            <div class="text-[12px] text-ink-500">适用：{{ d.use }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { learnApi } from '../../../api'
import { useAppStore } from '../../../stores/app'

const app = useAppStore()
const topTabs = [
  { v: 'square', label: '语言广场' }, { v: 'compare', label: '横向对比' },
  { v: 'glossary', label: '术语词典' }, { v: 'algo', label: '范式/算法/结构' },
]
const subTabs = [
  { v: 'overview', label: '概览' }, { v: 'roadmap', label: '学习路线' }, { v: 'cheatsheet', label: '语法速查' },
  { v: 'keywords', label: '关键字' }, { v: 'modules', label: '模块用法' }, { v: 'types', label: '数据类型' }, { v: 'lessons', label: '入门课程' },
  { v: 'snippets', label: '代码片段' }, { v: 'ide', label: '开发环境' }, { v: 'style', label: '编码规范' }, { v: 'errors', label: '常见报错' },
]
const topTab = ref('square')
const langs = ref([])
const cur = ref('')
const detail = ref({})
const subTab = ref('overview')
const cache = reactive({})
const lesson = ref(null)
const lessonIdx = ref(-1)
const selKeyword = ref('')
const keywordDetail = ref(null)
const selModule = ref(-1)
const moduleDetail = ref(null)

async function openLang(key) {
  cur.value = key
  subTab.value = 'overview'
  Object.keys(cache).forEach((k) => delete cache[k])
  selKeyword.value = ''
  keywordDetail.value = null
  selModule.value = -1
  moduleDetail.value = null
  detail.value = (await learnApi.langDetail(key))
  await loadSub('overview')
}
async function loadSub(v) {
  subTab.value = v
  lesson.value = null
  if (v === 'overview') return
  if (cache[v]) return
  const k = cur.value
  const map = {
    roadmap: () => learnApi.langRoadmap(k).then((r) => (cache.roadmap = r.roadmap)),
    cheatsheet: () => learnApi.langCheatsheet(k).then((r) => (cache.cheatsheet = r.cheatsheet)),
    keywords: () => learnApi.langKeywordsDetail(k).then((r) => (cache.keywords = r.keywords)),
    modules: () => learnApi.langModules(k).then((r) => (cache.modules = r.modules)),
    types: () => learnApi.langTypes(k).then((r) => (cache.types = r.types)),
    lessons: () => learnApi.langLessons(k).then((r) => (cache.lessons = r.list)),
    snippets: () => learnApi.langSnippets(k).then((r) => (cache.snippets = r.list)),
    ide: () => learnApi.langIde(k).then((r) => (cache.ide = r.ide)),
    style: () => learnApi.langStyle(k).then((r) => (cache.style = r.style)),
    errors: () => learnApi.langErrors(k).then((r) => (cache.errors = r.errors)),
  }
  await map[v]()
}
async function selectKeyword(k) {
  const word = k.word || k
  if (selKeyword.value === word) { selKeyword.value = ''; keywordDetail.value = null; return }
  selKeyword.value = word
  if (k.word && k.desc) {
    keywordDetail.value = k
  } else {
    keywordDetail.value = await learnApi.langKeywordDetail(cur.value, word)
  }
}
async function selectModule(idx) {
  if (selModule.value === idx) { selModule.value = -1; moduleDetail.value = null; return }
  selModule.value = idx
  moduleDetail.value = await learnApi.langModuleDetail(cur.value, idx)
}
async function openLesson(idx) {
  if (lessonIdx.value === idx) { lessonIdx.value = -1; lesson.value = null; return }
  lessonIdx.value = idx
  lesson.value = (await learnApi.langLesson(cur.value, idx))
}
async function bookmark() {
  await learnApi.addBookmark({ language: cur.value, title: `${detail.value.name} 学习卡`, code: detail.value.hello, note: '从语言广场收藏' })
  app.toastMsg('已加入我的学习-代码收藏', 'success')
}

// 对比
const cmpKeys = ref(['python', 'go'])
const cmp = ref({ keys: [], names: {}, rows: [] })
function toggleCmp(k) {
  const i = cmpKeys.value.indexOf(k)
  if (i >= 0) cmpKeys.value.splice(i, 1)
  else if (cmpKeys.value.length < 3) cmpKeys.value.push(k)
  else app.toastMsg('最多对比 3 门', 'warn')
}
async function runCompare() {
  if (cmpKeys.value.length < 2) return app.toastMsg('至少选 2 门', 'warn')
  cmp.value = (await learnApi.langCompare(cmpKeys.value))
}
const fmt = (v) => (Array.isArray(v) ? v.join('、') : v)

// 术语
const gloss = ref([])
const glossTags = ref([])
const glossQ = ref('')
const glossTag = ref('')
async function loadGloss() {
  gloss.value = (await learnApi.glossary({ q: glossQ.value, tag: glossTag.value })).list
}
async function pickTag(t) { glossTag.value = glossTag.value === t ? '' : t; await loadGloss() }

// 范式/算法/结构
const paradigms = ref([])
const algorithms = ref([])
const dataStructures = ref([])

onMounted(async () => {
  langs.value = (await learnApi.langCatalog()).list
  await openLang('python')
  const [p, a, ds, g] = await Promise.all([
    learnApi.paradigms(), learnApi.algorithms(), learnApi.dataStructures(), learnApi.glossary({})])
  paradigms.value = p.list
  algorithms.value = a.list
  dataStructures.value = ds.list
  gloss.value = g.list
  glossTags.value = g.tags
})
</script>
