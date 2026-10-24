<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <h1 class="text-[18px] font-semibold text-ink-800">全文搜索</h1>
      <span class="tag">倒排索引 · 中文分词 · BM25 排序</span>
      <button class="btn-outline ml-auto px-2 py-1 text-[12px]" @click="showStats = !showStats">
        {{ showStats ? '收起索引概况' : '索引概况' }}
      </button>
      <button class="btn-outline px-2 py-1 text-[12px]" :disabled="reindexing" @click="reindex">
        {{ reindexing ? '重建中…' : '重建我的索引' }}
      </button>
    </div>

    <div v-if="showStats && stats" class="card p-3 text-[12px] text-ink-600">
      <div class="flex flex-wrap gap-4">
        <span>文档 {{ stats.documents }} 篇</span>
        <span>词项 {{ stats.terms }} 条</span>
        <span>词表 {{ stats.vocabulary }} 个</span>
      </div>
      <div class="mt-1 flex flex-wrap gap-2">
        <span v-for="m in stats.by_module" :key="m.module" class="tag">
          {{ moduleLabel(m.module) }} {{ m.c }}
        </span>
      </div>
    </div>

    <div class="card p-3">
      <div class="flex flex-wrap items-center gap-2">
        <div class="relative min-w-[240px] flex-1">
          <input v-model="q" class="input"
                 placeholder='搜索笔记、文件、项目…"精确短语" 与 -排除词 均支持'
                 @keyup.enter="doSearch()" @input="onInput" @focus="onInput" @blur="closeSuggestLater" />
          <!-- F663 搜索框建议下拉：历史 + 热词 + 路由建议 + 词联想 -->
          <div v-if="showSuggest && suggestGroups.length"
               class="absolute left-0 top-full z-20 mt-1 max-h-[360px] w-full overflow-y-auto rounded-control border border-ink-100 bg-white shadow-pop">
            <div v-for="g in suggestGroups" :key="g.title">
              <div class="flex items-center justify-between bg-ink-50/70 px-2 py-1 text-[11px] text-ink-400">
                <span>{{ g.title }}</span>
                <span>{{ g.items.length }}</span>
              </div>
              <button v-for="item in g.items" :key="g.title + item.text"
                      class="flex w-full items-center gap-2 px-2 py-1.5 text-left text-[12px] hover:bg-ink-50"
                      @mousedown.prevent="pickSuggestItem(g, item)">
                <span class="w-4 shrink-0 text-center">{{ groupIcon(g.type) }}</span>
                <span class="min-w-0 flex-1 truncate">{{ item.text }}</span>
                <span class="shrink-0 text-[11px] text-ink-400">{{ item.meta }}</span>
              </button>
            </div>
          </div>
        </div>
        <select v-model="module" class="input w-36" @change="doSearch()">
          <option value="">全部模块</option>
          <option value="note">笔记</option>
          <option value="file">文件内容</option>
          <option value="project">项目</option>
          <option value="task">任务</option>
          <option v-for="m in extraModules" :key="m" :value="m">{{ moduleLabel(m) }}</option>
        </select>
        <button class="btn-primary px-3 py-1.5" :disabled="loading" @click="doSearch()">
          {{ loading ? '搜索中…' : '搜索' }}
        </button>
        <button v-if="searched && q" class="btn-outline px-2 py-1.5 text-[12px]" @click="exportCsv">导出 CSV</button>
      </div>

      <!-- F662 搜索语法：提示 + 已解析的短语/排除词 chips -->
      <div class="mt-2 flex flex-wrap items-center gap-1 text-[12px] text-ink-400">
        <span class="tag">语法</span>
        <code class="rounded bg-ink-50 px-1">"精确短语"</code>
        <code class="rounded bg-ink-50 px-1">-排除词</code>
        <template v-if="syntax.phrases.length">
          <span>已解析：</span>
          <button v-for="p in syntax.phrases" :key="'p' + p" class="tag hover:bg-rose-50"
                  title="点击移除该短语条件" @click="removePhrase(p)">“{{ p }}” ×</button>
        </template>
        <template v-if="syntax.excludes.length">
          <button v-for="e in syntax.excludes" :key="'e' + e" class="tag hover:bg-rose-50"
                  title="点击移除该排除词" @click="removeExclude(e)">−{{ e }} ×</button>
        </template>
        <span v-if="syntax.phrase_fallback" class="text-amber-500">
          精确短语未在摘要中直接命中，已按关键词匹配
        </span>
      </div>

      <div v-if="searched" class="mt-2 text-[12px] text-ink-400">
        命中 {{ total }} 条<template v-if="tookMs !== null"> · 耗时 {{ tookMs }}ms</template>
        <template v-if="terms.length"> · 分词：{{ terms.slice(0, 8).join(' / ') }}</template>
      </div>
    </div>

    <!-- F661 搜索结果按模块分组：分组 Tab + 计数 -->
    <div v-if="searched && groupList.length" class="card p-2">
      <div class="flex flex-wrap items-center gap-1 text-[12px]">
        <button class="rounded-pill px-2.5 py-1"
                :class="module === '' ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                @click="pickGroup('')">
          全部 <span class="ml-0.5 text-[11px] text-ink-400">{{ total }}</span>
        </button>
        <button v-for="g in groupList" :key="g.module" class="rounded-pill px-2.5 py-1"
                :class="module === g.module ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                @click="pickGroup(g.module)">
          {{ moduleLabel(g.module) }}
          <span class="ml-0.5 text-[11px] text-ink-400">{{ g.count }}</span>
        </button>
      </div>
    </div>

    <div v-if="results.length" class="card divide-y divide-ink-50">
      <div v-for="r in results" :key="`${r.module}-${r.doc_id ?? r.id}`" class="p-3 hover:bg-ink-50/60">
        <div class="flex items-center gap-2">
          <span class="tag shrink-0">{{ moduleLabel(r.module) }}</span>
          <component :is="'button'" class="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-ink-800 hover:text-brand-600"
                     @click="openResult(r)">
            {{ r.title }}
          </component>
          <span class="shrink-0 text-[11px] text-ink-400">相关度 {{ r.score }}</span>
        </div>
        <!-- 片段含 <em> 高亮标记；后端已对正文做 HTML 转义，v-html 渲染不会注入 -->
        <div class="mt-1 text-[12px] leading-relaxed text-ink-600" v-html="r.snippet"></div>
        <div v-if="r.matched_terms?.length" class="mt-1 flex flex-wrap gap-1">
          <span v-for="t in r.matched_terms" :key="t" class="tag">{{ t }}</span>
        </div>
      </div>
      <div v-if="total > results.length" class="p-3 text-center">
        <button class="btn-outline text-[12px]" :disabled="loading" @click="loadMore()">
          加载更多（已显示 {{ results.length }}/{{ total }}）
        </button>
      </div>
    </div>

    <div v-else-if="searched && !loading" class="card grid place-items-center py-16 text-center">
      <div>
        <div class="text-[32px]">🔍</div>
        <div class="mt-2 text-[13px] text-ink-500">没有找到匹配内容</div>
        <div class="mt-1 text-[12px] text-ink-400">试试更短的关键词，或点「重建我的索引」确保内容已入库</div>
      </div>
    </div>

    <div v-if="!searched" class="card p-4">
      <div class="text-[12px] font-medium text-ink-700">热门搜索</div>
      <div class="mt-1 flex flex-wrap gap-1">
        <button v-for="h in hot" :key="h.term" class="tag hover:bg-brand-50" @click="quickSearch(h.term)">🔥 {{ h.term }} <span class="text-ink-400">{{ h.count }}</span></button>
        <span v-if="!hot.length" class="text-[12px] text-ink-400">暂无热词</span>
      </div>
      <div class="mt-3 flex items-center text-[12px] font-medium text-ink-700">
        <span>搜索历史</span>
        <button class="ml-auto text-ink-400 hover:text-brand-600" @click="clearHist">清空</button>
      </div>
      <div class="mt-1 flex flex-wrap gap-1">
        <button v-for="h in history" :key="h.term" class="tag hover:bg-brand-50" @click="quickSearch(h.term)">🕘 {{ h.term }}</button>
        <span v-if="!history.length" class="text-[12px] text-ink-400">暂无历史</span>
      </div>
    </div>

    <div v-else class="card p-6 text-[12px] leading-relaxed text-ink-500">
      <div class="text-[13px] font-medium text-ink-700">检索范围</div>
      <ul class="mt-1 list-disc space-y-0.5 pl-5">
        <li><b>笔记</b>：标题与 Markdown 正文</li>
        <li><b>文件内容</b>：txt / md / csv / json / pdf / docx / xlsx 的正文（保存时自动抽取入库）</li>
        <li><b>项目与任务</b>：名称与描述</li>
      </ul>
      <div class="mt-2">中文无需空格切分：输入「协同编辑」即可命中「支持实时协同编辑的文档」这类内容。</div>
      <div class="mt-1">搜索语法：<code class="rounded bg-ink-50 px-1">"精确短语"</code> 只命中完整短语，
        <code class="rounded bg-ink-50 px-1">-排除词</code> 过滤掉含该词的结果。</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { searchApi } from '../api'
import { useAppStore } from '../stores/app'
import { describeDownloadError, downloadWithAuth } from '../utils/download'

const app = useAppStore()
const router = useRouter()
const route = useRoute()
const q = ref('')
const module = ref('')
const results = ref([])
const total = ref(0)
const terms = ref([])
const tookMs = ref(null)
const loading = ref(false)
const searched = ref(false)
const termSuggests = ref([])
const showSuggest = ref(false)
const showStats = ref(false)
const stats = ref(null)
const reindexing = ref(false)
const history = ref([])
const hot = ref([])
// F662：语法解析结果（后端回显）
const syntax = ref({ phrases: [], excludes: [], terms_text: '', phrase_fallback: false })
// F661：模块分组计数（后端回显）
const groupCounts = ref({})

const MODULE_LABELS = { note: '笔记', file: '文件', project: '项目', task: '任务' }
function moduleLabel(m) { return MODULE_LABELS[m] || m }

/** 分组 Tab 数据（全部 + 各模块计数） */
const groupList = computed(() => {
  const src = groupCounts.value && Object.keys(groupCounts.value).length
    ? Object.entries(groupCounts.value).map(([module, count]) => ({ module, count }))
    : Object.entries(results.value.reduce((acc, r) => {
        acc[r.module] = (acc[r.module] || 0) + 1
        return acc
      }, {})).map(([module, count]) => ({ module, count }))
  return src.sort((a, b) => b.count - a.count)
})

/** 下拉里出现、而 select 中没有的模块键 */
const extraModules = computed(() => {
  const known = ['note', 'file', 'project', 'task']
  return groupList.value.map((g) => g.module).filter((m) => !known.includes(m))
})

function pickGroup(m) {
  module.value = m
  localStorage.setItem('search_module', m)
  doSearch()
}

function pickSuggestItem(group, item) {
  showSuggest.value = false
  if (group.type === 'route') {
    router.push(item.path)
    return
  }
  q.value = item.text
  doSearch()
}

function groupIcon(type) {
  return { history: '🕘', hot: '🔥', route: '🧭', term: '🏷️' }[type] || '🔎'
}

async function doSearch(append = false) {
  const isAppend = append === true   // 事件对象不当作 append（修掉 Enter/点击误判）
  const keyword = q.value.trim()
  if (!keyword) {
    results.value = []; total.value = 0; searched.value = false
    groupCounts.value = {}; syntax.value = { phrases: [], excludes: [], terms_text: '', phrase_fallback: false }
    return
  }
  localStorage.setItem('search_module', module.value)  // #64 记忆筛选
  loading.value = true
  showSuggest.value = false
  try {
    const r = await searchApi.fulltext({
      q: keyword, module: module.value || undefined,
      limit: 20, offset: isAppend ? results.value.length : 0,
    })
    results.value = isAppend ? [...results.value, ...(r.results || [])] : (r.results || [])
    total.value = r.total
    terms.value = r.terms || []
    tookMs.value = r.took_ms ?? null
    syntax.value = r.syntax || { phrases: [], excludes: [], terms_text: '', phrase_fallback: false }
    groupCounts.value = r.group_counts || {}
    searched.value = true
  } catch (e) {
    app.toastMsg(e.message || '搜索失败', 'error')
  } finally {
    loading.value = false
  }
}

function loadMore() { doSearch(true) }

/** F662：从查询串里删掉一个短语 / 排除词后重搜 */
function removePhrase(p) {
  q.value = q.value.split(`"${p}"`).join('')
                     .split(`“${p}”`).join('')
                     .split(`「${p}」`).join('')
                     .replace(/\s+/g, ' ').trim()
  doSearch()
}
function removeExclude(e) {
  q.value = q.value.split(`-${e}`).join(' ').replace(/\s+/g, ' ').trim()
  doSearch()
}

// ---------------- F663 搜索建议：历史 + 热词 + 路由建议 + 词联想 ----------------
const ROUTE_SUGGESTIONS = [
  { label: '笔记知识库', path: '/notes', kw: '笔记 note 知识' },
  { label: '文件管理', path: '/files', kw: '文件 file 上传' },
  { label: '项目看板', path: '/projects', kw: '项目 project 任务 看板' },
  { label: '我的任务', path: '/projects/my-tasks', kw: '任务 task 待办' },
  { label: '工作台首页', path: '/dashboard', kw: '工作台 dashboard 首页' },
  { label: 'AI 助手', path: '/ai', kw: 'ai 助手 智能 问答' },
  { label: '学习中心', path: '/learning', kw: '学习 learning 课程 刷题' },
  { label: '站内消息', path: '/im', kw: '消息 im 聊天 沟通' },
]

function routeMatches(kw) {
  const k = (kw || '').toLowerCase()
  const hit = k
    ? ROUTE_SUGGESTIONS.filter((r) => (r.label + r.path + r.kw).toLowerCase().includes(k))
    : ROUTE_SUGGESTIONS
  return hit.slice(0, 4)
}

const suggestGroups = computed(() => {
  const kw = q.value.trim()
  const groups = []
  const push = (title, type, items) => { if (items.length) groups.push({ title, type, items }) }

  if (!kw) {
    push('搜索历史', 'history', history.value.slice(0, 5)
      .map((h) => ({ text: h.term, meta: `${h.result_count} 篇` })))
    push('热词', 'hot', hot.value.slice(0, 5)
      .map((h) => ({ text: h.term, meta: `${h.count} 次` })))
    push('快捷跳转', 'route', routeMatches('').map((r) => ({ text: r.label, path: r.path, meta: r.path })))
    return groups
  }

  const lower = kw.toLowerCase()
  push('联想词', 'term', termSuggests.value.slice(0, 5)
    .map((s) => ({ text: s.term, meta: `${s.count} 篇` })))
  push('搜索历史', 'history', history.value
    .filter((h) => h.term.toLowerCase().includes(lower)).slice(0, 4)
    .map((h) => ({ text: h.term, meta: `${h.result_count} 篇` })))
  push('热词', 'hot', hot.value
    .filter((h) => h.term.toLowerCase().includes(lower)).slice(0, 3)
    .map((h) => ({ text: h.term, meta: `${h.count} 次` })))
  push('快捷跳转', 'route', routeMatches(lower).map((r) => ({ text: r.label, path: r.path, meta: r.path })))
  return groups
})

let suggestTimer = null
function onInput() {
  showSuggest.value = true
  clearTimeout(suggestTimer)
  const keyword = q.value.trim()
  if (!keyword) { termSuggests.value = []; return }
  suggestTimer = setTimeout(async () => {
    try {
      termSuggests.value = (await searchApi.suggest(keyword, 8)).list || []
    } catch (e) { termSuggests.value = [] }
  }, 250)
}
// 失焦稍后再关，保证 mousedown 处理能先执行
function closeSuggestLater() {
  setTimeout(() => { showSuggest.value = false }, 120)
}

async function loadStats() {
  try { stats.value = await searchApi.stats() } catch (e) { /* ignore */ }
}
async function reindex() {
  reindexing.value = true
  try {
    const r = await searchApi.reindex({ scope: 'own' })
    app.toastMsg(`索引已重建，共 ${r.indexed} 篇`, 'success')
    loadStats()
    if (q.value.trim()) doSearch()
  } catch (e) {
    app.toastMsg(e.message || '重建失败', 'error')
  } finally {
    reindexing.value = false
  }
}
function openResult(r) {
  const route = { note: '/notes', file: '/files', project: '/projects', task: '/projects' }[r.module]
  if (!route) return
  // F23：文件结果带关键词跳转（Files 页消费 ?q= 直接定位）；笔记无本地搜索框保持模块跳转
  if (r.module === 'file') {
    router.push(`/files?q=${encodeURIComponent(r.title)}`)
    return
  }
  if (r.module === 'note') app.toastMsg(`已定位到笔记模块：《${r.title}》`, 'success')
  router.push(route)
}

// #64 搜索条件记忆：恢复上次模块筛选
const savedModule = localStorage.getItem('search_module')
if (savedModule) module.value = savedModule

function quickSearch(term) { q.value = term; doSearch() }
async function loadHistory() {
  try { history.value = (await searchApi.history()).list || [] } catch (e) { history.value = [] }
}
async function loadHot() {
  try { hot.value = (await searchApi.hot()).list || [] } catch (e) { hot.value = [] }
}
async function clearHist() {
  try { await searchApi.clearHistory() } catch (e) {}
  history.value = []
}
// F2：导出接口要 JWT，window.open 裸 URL 会 401，改带鉴权下载
async function exportCsv() {
  try {
    await downloadWithAuth(searchApi.exportUrl(q.value.trim()), `搜索结果-${q.value.trim()}.csv`)
  } catch (e) {
    app.toastMsg(await describeDownloadError(e), 'error')
  }
}

onMounted(() => {
  loadStats(); loadHistory(); loadHot()
  // F23：从 Topbar 全局搜索带 ?q= 跳入时自动执行搜索（原来落空白页要手输）
  const q0 = route.query.q
  if (q0) {
    q.value = String(q0)
    doSearch()
  }
})
</script>
