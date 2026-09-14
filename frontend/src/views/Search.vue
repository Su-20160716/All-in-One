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
          <input v-model="q" class="input" placeholder="搜索笔记正文、文件内容、项目与任务…（支持中文词组）"
                 @keyup.enter="doSearch" @input="onInput" @focus="onInput" />
          <div v-if="suggests.length && focused"
               class="absolute left-0 top-full z-10 mt-1 w-full overflow-hidden rounded-control border border-ink-100 bg-white shadow-pop">
            <button v-for="s in suggests" :key="s.term"
                    class="flex w-full items-center gap-2 px-2 py-1.5 text-left text-[12px] hover:bg-ink-50"
                    @click="pickSuggest(s.term)">
              <span class="flex-1">{{ s.term }}</span>
              <span class="text-[11px] text-ink-400">{{ s.count }} 篇</span>
            </button>
          </div>
        </div>
        <select v-model="module" class="input w-36" @change="doSearch">
          <option value="">全部模块</option>
          <option value="note">笔记</option>
          <option value="file">文件内容</option>
          <option value="project">项目</option>
          <option value="task">任务</option>
        </select>
        <button class="btn-primary px-3 py-1.5" :disabled="loading" @click="doSearch">
          {{ loading ? '搜索中…' : '搜索' }}
        </button>
      </div>
      <div v-if="searched" class="mt-2 text-[12px] text-ink-400">
        命中 {{ total }} 条<template v-if="tookMs !== null"> · 耗时 {{ tookMs }}ms</template>
        <template v-if="terms.length"> · 分词：{{ terms.slice(0, 8).join(' / ') }}</template>
      </div>
    </div>

    <div v-if="results.length" class="card divide-y divide-ink-50">
      <div v-for="r in results" :key="`${r.module}-${r.id}`" class="p-3 hover:bg-ink-50/60">
        <div class="flex items-center gap-2">
          <span class="tag shrink-0">{{ moduleLabel(r.module) }}</span>
          <component :is="'button'" class="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-ink-800 hover:text-brand-600"
                     @click="openResult(r)">
            {{ r.title }}
          </component>
          <span class="shrink-0 text-[11px] text-ink-400">相关度 {{ r.score }}</span>
        </div>
        <div class="mt-1 text-[12px] leading-relaxed text-ink-600" v-html="r.snippet"></div>
        <div v-if="r.matched_terms?.length" class="mt-1 flex flex-wrap gap-1">
          <span v-for="t in r.matched_terms" :key="t" class="tag">{{ t }}</span>
        </div>
      </div>
      <div v-if="total > results.length" class="p-3 text-center">
        <button class="btn-outline text-[12px]" :disabled="loading" @click="loadMore">
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

    <div v-else class="card p-6 text-[12px] leading-relaxed text-ink-500">
      <div class="text-[13px] font-medium text-ink-700">检索范围</div>
      <ul class="mt-1 list-disc space-y-0.5 pl-5">
        <li><b>笔记</b>：标题与 Markdown 正文</li>
        <li><b>文件内容</b>：txt / md / csv / json / pdf / docx / xlsx 的正文（保存时自动抽取入库）</li>
        <li><b>项目与任务</b>：名称与描述</li>
      </ul>
      <div class="mt-2">中文无需空格切分：输入「协同编辑」即可命中「支持实时协同编辑的文档」这类内容。</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { searchApi } from '../api'
import { useAppStore } from '../stores/app'

const app = useAppStore()
const router = useRouter()
const q = ref('')
const module = ref('')
const results = ref([])
const total = ref(0)
const terms = ref([])
const tookMs = ref(null)
const loading = ref(false)
const searched = ref(false)
const suggests = ref([])
const focused = ref(true)
const showStats = ref(false)
const stats = ref(null)
const reindexing = ref(false)

const MODULE_LABELS = { note: '笔记', file: '文件', project: '项目', task: '任务' }
function moduleLabel(m) { return MODULE_LABELS[m] || m }

async function doSearch(append = false) {
  const keyword = q.value.trim()
  if (!keyword) {
    results.value = []; total.value = 0; searched.value = false; return
  }
  loading.value = true
  focused.value = false
  try {
    const r = await searchApi.fulltext({
      q: keyword, module: module.value || undefined,
      limit: 20, offset: append ? results.value.length : 0,
    })
    results.value = append ? [...results.value, ...r.results] : r.results
    total.value = r.total
    terms.value = r.terms || []
    tookMs.value = r.took_ms ?? null
    searched.value = true
  } catch (e) {
    app.toastMsg(e.message || '搜索失败', 'error')
  } finally {
    loading.value = false
  }
}

function loadMore() { doSearch(true) }

let suggestTimer = null
function onInput() {
  focused.value = true
  clearTimeout(suggestTimer)
  const keyword = q.value.trim()
  if (!keyword) { suggests.value = []; return }
  suggestTimer = setTimeout(async () => {
    try {
      suggests.value = (await searchApi.suggest(keyword, 8)).list || []
    } catch (e) { suggests.value = [] }
  }, 250)
}
function pickSuggest(term) {
  q.value = term
  suggests.value = []
  doSearch()
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
  if (r.module === 'note') app.toastMsg(`已定位到笔记模块：《${r.title}》`, 'success')
  router.push(route)
}

onMounted(loadStats)
</script>
