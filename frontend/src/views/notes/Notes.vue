<template>
  <div class="flex gap-4">
    <!-- 目录树 -->
    <div class="card w-64 shrink-0 self-start p-3">
      <div class="mb-2 flex items-center justify-between px-1">
        <span class="text-[12px] font-semibold text-ink-600">{{ sideTab === 'trash' ? '回收站' : '笔记目录' }}</span>
        <button v-if="sideTab !== 'trash'" class="btn-primary px-2 py-1 text-[11px]" @click="createNote()">＋ 新建</button>
      </div>
      <div class="mb-2 flex gap-1">
        <button class="flex-1 rounded-control py-1 text-[12px]" :class="sideTab === 'all' ? 'bg-brand-50 text-brand-700' : 'text-ink-500 hover:bg-ink-50'" @click="switchSide('all')">全部</button>
        <button class="flex-1 rounded-control py-1 text-[12px]" :class="sideTab === 'trash' ? 'bg-rose-50 text-rose-600' : 'text-ink-500 hover:bg-ink-50'" @click="switchSide('trash')">回收站</button>
      </div>

      <div v-if="sideTab === 'trash'" class="space-y-1">
        <div v-for="n in trashList" :key="n.id" class="flex items-center justify-between rounded-control px-2 py-1.5 text-[13px] hover:bg-ink-50">
          <span class="truncate">🗑 {{ n.title }}</span>
          <span class="flex shrink-0 gap-1">
            <button class="text-[11px] text-brand-600" @click="restoreNote(n)">还原</button>
            <button class="text-[11px] text-rose-500" @click="destroyNote(n)">清除</button>
          </span>
        </div>
        <button v-if="trashList.length" class="mt-2 w-full rounded-control bg-rose-50 py-1.5 text-[12px] text-rose-600" @click="emptyTrash">清空回收站</button>
      </div>

      <div v-else class="space-y-0.5 text-[13px]">
        <div v-if="activeTag" class="mb-1 rounded-control bg-brand-50/50 px-2 py-1.5 text-[12px] text-brand-700">
          标签「{{ activeTag }}」<button @click="activeTag = null">×</button>
        </div>
        <div v-for="n in shownList" :key="n.id" class="flex cursor-pointer items-center justify-between rounded-control px-2 py-1.5 hover:bg-ink-50" :class="activeNote === n.id ? 'bg-brand-50 text-brand-700' : ''" @click="openNote(n.id)">
          <span class="truncate">{{ n.is_public ? '🌐' : n.is_favorite ? '★' : '📄' }} {{ n.title }}</span>
        </div>
      </div>

      <div v-if="sideTab !== 'trash'" class="mt-3 border-t border-ink-100 pt-2">
        <div class="mb-1 flex items-center justify-between px-1">
          <span class="text-[11px] text-ink-400">标签</span>
          <button class="text-[11px] text-brand-600" @click="showTagMgr = true">管理</button>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="t in tags" :key="t.id" class="cursor-pointer tag" :class="activeTag === t.name ? 'tag-brand' : ''" @click="filterByTag(t.name)">#{{ t.name }}</span>
        </div>
      </div>
      <div class="mt-3 space-y-0.5 border-t border-ink-100 pt-2">
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showTemplates = true">📋 从模板新建</button>
        <button class="block w-full rounded-control px-2 py-1.5 text-left text-[12px] text-ink-500 hover:bg-ink-50" @click="showStats = true; loadStats()">📊 写作统计</button>
        <a :href="noteApi.exportAllUrl()" class="block rounded-control px-2 py-1.5 text-[12px] text-ink-500 hover:bg-ink-50">⬇ 导出全部 ZIP</a>
      </div>
    </div>

    <!-- 编辑器 -->
    <div class="min-w-0 flex-1">
      <div v-if="current" class="card overflow-hidden">
        <div class="flex items-center gap-2 border-b border-ink-100 px-4 py-2">
          <input v-model="current.title" class="flex-1 border-none bg-transparent text-[16px] font-semibold focus:outline-none" placeholder="笔记标题" />
          <button class="btn-ghost px-2 text-[12px]" :class="current.is_favorite ? 'text-amber-500' : ''" @click="toggleFlag('is_favorite')">★</button>
          <button class="btn-ghost px-2 text-[12px]" :class="current.is_pinned ? 'text-brand-600' : ''" @click="toggleFlag('is_pinned')">📌</button>
          <button class="btn-ghost px-2 text-[12px]" :class="current.is_public ? 'text-emerald-600' : ''" @click="toggleFlag('is_public')">🌐</button>
          <button class="btn-ghost px-2 text-[12px]" @click="showOutline = true; loadOutline()">大纲</button>
          <button class="btn-ghost px-2 text-[12px]" :class="rightPanel ? 'text-brand-600' : ''" @click="rightPanel = !rightPanel">
            🔗 关联<span v-if="backlinkCount" class="ml-0.5 text-brand-600">{{ backlinkCount }}</span>
          </button>
          <button class="btn-ghost px-2 text-[12px]" :class="collabMode ? 'text-emerald-600' : ''" @click="toggleCollab">
            👥 协同
          </button>
          <button class="btn-ghost px-2 text-[12px]" @click="duplicate">复制</button>
          <a :href="noteApi.exportUrl(current.id)" class="btn-ghost px-2 text-[12px]">导出</a>
          <button class="btn-ghost px-2 text-[12px]" @click="showVersions = true; loadVersions()">🕘</button>
          <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="deleteNote">🗑</button>
        </div>
        <div class="flex border-b border-ink-100">
          <button class="flex-1 border-b-2 px-3 py-2 text-[13px]" :class="editorTab === 'write' ? 'border-brand-500 font-medium text-brand-600' : 'border-transparent text-ink-500'" @click="editorTab = 'write'">编辑</button>
          <button class="flex-1 border-b-2 px-3 py-2 text-[13px]" :class="editorTab === 'preview' ? 'border-brand-500 font-medium text-brand-600' : 'border-transparent text-ink-500'" @click="editorTab = 'preview'">预览</button>
        </div>
        <div class="relative">
          <textarea v-show="editorTab !== 'preview'"
                    :value="collabMode ? collabText : current.content"
                    class="h-[52vh] w-full resize-none bg-ink-50/50 p-4 font-mono text-[13px] leading-relaxed focus:outline-none"
                    placeholder="支持 Markdown…  输入 [[ 可引用其他笔记建立双链"
                    @input="onContentInput"
                    @keyup="detectLinkQuery($event.target)"
                    @click="detectLinkQuery($event.target)"></textarea>
          <div v-if="linkSuggest.length && editorTab !== 'preview'"
               class="absolute left-4 top-2 z-10 w-56 overflow-hidden rounded-control border border-ink-100 bg-white shadow-pop">
            <div class="border-b border-ink-50 px-2 py-1 text-[11px] text-ink-400">选择要引用的笔记</div>
            <button v-for="s in linkSuggest" :key="s.id"
                    class="block w-full truncate px-2 py-1.5 text-left text-[12px] hover:bg-ink-50"
                    @click="insertLink(s.title)">{{ s.title }}</button>
            <button class="block w-full px-2 py-1.5 text-left text-[12px] text-ink-400 hover:bg-ink-50"
                    @click="linkSuggest = []">取消</button>
          </div>
        </div>
        <div v-show="editorTab !== 'write'" class="h-[52vh] overflow-y-auto bg-white p-4 markdown-body" v-html="rendered"></div>
        <div class="flex items-center justify-between border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
          <span>
            v{{ current.version }} · {{ current.words || 0 }} 字 · {{ formatTime(current.updated_at) }}
            <span v-if="collabMode" class="ml-2 tag" :class="collabStatus === 'ready' ? 'tag-brand' : ''">
              协同 {{ collabStatusLabel }}<span v-if="collabPeers.length"> · {{ collabPeers.join('、') }}</span>
            </span>
          </span>
          <div class="flex items-center gap-2">
            <input v-model="tagInput" class="input w-32 py-1 text-[12px]" placeholder="+ 标签" @keyup.enter="addTag" />
            <span v-for="t in current.tag_names" :key="t" class="tag tag-brand">{{ t }} <button class="ml-0.5" @click="removeTag(t)">×</button></span>
            <span v-if="collabMode" class="text-emerald-500">协同模式（自动同步）</span>
            <span v-else-if="saving" class="text-emerald-500">已保存</span>
          </div>
        </div>
      </div>
      <div v-else class="card grid place-items-center py-24">
        <div class="text-center">
          <div class="text-[36px]">📝</div>
          <div class="mt-2 text-[14px] font-medium text-ink-700">选择或创建一篇笔记</div>
          <button class="btn-primary mt-4" @click="createNote()">新建笔记</button>
        </div>
      </div>
    </div>

    <!-- 右侧：关联（双链）/ AI 面板 -->
    <aside v-if="current && rightPanel" class="w-72 shrink-0">
      <div class="card p-3">
        <div class="mb-2 flex gap-1 text-[12px]">
          <button class="flex-1 rounded-control px-2 py-1"
                  :class="rightTab === 'links' ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                  @click="rightTab = 'links'">反链 {{ backlinkCount }}</button>
          <button class="flex-1 rounded-control px-2 py-1"
                  :class="rightTab === 'ai' ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-500 hover:bg-ink-50'"
                  @click="rightTab = 'ai'">AI 助手</button>
        </div>

        <!-- 双链 -->
        <div v-if="rightTab === 'links'" class="space-y-2">
          <div>
            <div class="mb-1 text-[11px] font-medium text-ink-500">反向链接（谁引用了本篇）</div>
            <div v-if="!backlinks.length" class="rounded-control bg-ink-50 p-2 text-[11px] text-ink-400">
              还没有笔记引用本篇。在别的笔记里写 <code>[[{{ current.title }}]]</code> 即可建立双链。
            </div>
            <button v-for="b in backlinks" :key="b.link_id"
                    class="block w-full rounded-control px-2 py-1.5 text-left hover:bg-ink-50"
                    @click="openNote(b.note_id)">
              <div class="truncate text-[12px] font-medium text-ink-700">{{ b.title }}</div>
              <div class="truncate text-[11px] text-ink-400">{{ b.excerpt }}</div>
            </button>
          </div>

          <div class="border-t border-ink-100 pt-2">
            <div class="mb-1 text-[11px] font-medium text-ink-500">出链（本篇引用了谁）</div>
            <div v-if="!outgoingLinks.length" class="text-[11px] text-ink-400">暂无出链</div>
            <div v-for="o in outgoingLinks" :key="o.link_id" class="flex items-center gap-1 py-0.5 text-[12px]">
              <span :class="o.resolved ? 'text-brand-600' : 'text-amber-500'">{{ o.resolved ? '→' : '○' }}</span>
              <button v-if="o.resolved" class="truncate text-ink-700 hover:underline" @click="openNote(o.target_id)">
                {{ o.title }}
              </button>
              <span v-else class="truncate text-amber-600">{{ o.title }}</span>
              <button v-if="!o.resolved" class="ml-auto shrink-0 text-[11px] text-brand-600" @click="createFromTitle(o.title)">
                创建
              </button>
            </div>
          </div>

          <div v-if="dangling.length" class="border-t border-ink-100 pt-2">
            <div class="mb-1 text-[11px] font-medium text-ink-500">悬浮链接（被引用但未创建）</div>
            <div v-for="d in dangling" :key="d.title" class="flex items-center gap-1 py-0.5 text-[12px]">
              <span class="truncate text-ink-600">{{ d.title }}</span>
              <span class="text-[11px] text-ink-400">×{{ d.ref_count }}</span>
              <button class="ml-auto shrink-0 text-[11px] text-brand-600" @click="createFromTitle(d.title)">创建</button>
            </div>
          </div>

          <button class="btn-outline w-full py-1 text-[12px]" @click="loadGraph">查看关系图谱</button>
        </div>

        <!-- AI -->
        <div v-else class="space-y-2">
          <button class="btn-primary w-full py-1.5 text-[12px]" :disabled="aiBusy" @click="aiSummarize">
            {{ aiBusy ? '生成中…' : '✨ 生成 AI 摘要' }}
          </button>
          <div v-if="aiSummary" class="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-control bg-ink-50 p-2 text-[12px] leading-relaxed text-ink-700">
            {{ aiSummary }}
          </div>
          <ul v-if="aiPoints.length" class="space-y-0.5 text-[12px] text-ink-600">
            <li v-for="(p, i) in aiPoints" :key="i">· {{ p }}</li>
          </ul>

          <div class="border-t border-ink-100 pt-2">
            <div class="mb-1 text-[11px] font-medium text-ink-500">就本篇内容提问</div>
            <div v-for="(qa, i) in aiQa" :key="i" class="mb-2 text-[12px]">
              <div class="font-medium text-ink-700">Q：{{ qa.q }}</div>
              <div class="mt-0.5 whitespace-pre-wrap text-ink-600">A：{{ qa.a }}</div>
              <div v-if="qa.refs?.length" class="mt-0.5 text-[11px] text-ink-400">
                来源：{{ qa.refs.map(r => r.title).join('、') }}
              </div>
            </div>
            <div class="flex gap-1">
              <input v-model="aiQuestion" class="input py-1 text-[12px]" placeholder="问点什么…" @keyup.enter="aiAsk" />
              <button class="btn-outline shrink-0 px-2 py-1 text-[12px]" :disabled="aiBusy" @click="aiAsk">问</button>
            </div>
          </div>
          <div class="text-[11px] text-ink-400">
            提供方：{{ aiProvider || '本地' }}<span v-if="aiHint"> · {{ aiHint }}</span>
          </div>
        </div>
      </div>
    </aside>
  </div>

    <!-- 模板 -->
    <Modal :show="showTemplates" title="从模板新建" @close="showTemplates = false">
      <div class="grid grid-cols-2 gap-2">
        <button v-for="t in templates" :key="t.key" class="rounded-card border border-ink-100 p-3 text-left hover:border-brand-400" @click="useTemplate(t.key)">
          <div class="text-[13px] font-medium text-ink-800">{{ t.title }}</div>
        </button>
      </div>
    </Modal>

    <!-- 大纲 -->
    <Modal :show="showOutline" title="内容大纲" @close="showOutline = false">
      <div class="space-y-1">
        <div v-for="(h, i) in outline" :key="i" class="text-[13px] text-ink-700" :style="{ paddingLeft: (h.level - 1) * 14 + 'px' }">
          {{ h.level === 1 ? '■' : '▸' }} {{ h.text }}
        </div>
        <div v-if="!outline.length" class="text-[12px] text-ink-400">使用 # ## ### 生成标题即可提取大纲</div>
      </div>
    </Modal>

    <!-- 统计 -->
    <Modal :show="showStats" title="写作统计" @close="showStats = false">
      <div class="grid grid-cols-3 gap-3 text-center">
        <div class="rounded-card bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.total || 0 }}</div><div class="text-[11px] text-ink-400">笔记数</div></div>
        <div class="rounded-card bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.total_words || 0 }}</div><div class="text-[11px] text-ink-400">总字数</div></div>
        <div class="rounded-card bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.updated_7d || 0 }}</div><div class="text-[11px] text-ink-400">近7天更新</div></div>
      </div>
    </Modal>

    <!-- 标签管理 -->
    <Modal :show="showTagMgr" title="标签管理" @close="showTagMgr = false">
      <div class="space-y-2">
        <div v-for="t in tags" :key="t.id" class="flex items-center gap-2">
          <input v-model="t.name" class="input flex-1" @change="saveTag(t)" />
          <input v-model="t.color" type="color" class="h-8 w-10 rounded-control border border-ink-200" @change="saveTag(t)" />
          <button class="btn-danger px-2 text-[12px]" @click="delTag(t)">删除</button>
        </div>
        <div class="flex gap-2">
          <input v-model="newTagName" class="input flex-1" placeholder="新标签名" @keyup.enter="addNewTag" />
          <button class="btn-primary" @click="addNewTag">新增</button>
        </div>
      </div>
    </Modal>

    <!-- 版本 -->
    <Modal :show="showVersions" title="版本历史" width="480px" @close="showVersions = false">
      <div v-if="versions.length" class="space-y-2">
        <div v-for="v in versions" :key="v.id" class="flex items-center justify-between rounded-control bg-ink-50 px-3 py-2">
          <div><div class="text-[13px] font-medium">v{{ v.version }} · {{ v.title }}</div><div class="text-[11px] text-ink-400">{{ formatTime(v.created_at) }} {{ v.created_by_name }}</div></div>
          <button class="btn-outline px-2 py-1 text-[12px]" @click="rollback(v)">回滚</button>
        </div>
      </div>
      <div v-else class="py-8 text-center text-[12px] text-ink-400">暂无版本</div>
    </Modal>

    <!-- 双链关系图谱 -->
    <Modal :show="showGraph" title="笔记关系图谱" width="640px" @close="showGraph = false">
      <div v-if="graph" class="space-y-3">
        <div class="flex gap-3 text-[12px] text-ink-500">
          <span>笔记 {{ graph.node_count }} 篇</span>
          <span>链接 {{ graph.edge_count }} 条</span>
        </div>
        <div class="max-h-[50vh] space-y-1 overflow-y-auto">
          <div v-for="n in graph.nodes.slice(0, 60)" :key="n.id"
               class="flex items-center gap-2 rounded-control px-2 py-1.5 hover:bg-ink-50">
            <span class="tag" :class="n.degree ? 'tag-brand' : ''">{{ n.degree }}</span>
            <button class="min-w-0 flex-1 truncate text-left text-[13px] text-ink-700 hover:underline"
                    @click="showGraph = false; openNote(n.id)">{{ n.title }}</button>
            <span v-if="n.is_orphan" class="text-[11px] text-ink-400">孤立</span>
          </div>
        </div>
        <div v-if="graph.nodes.length" class="text-[11px] text-ink-400">
          按关联度排序。用 <code>[[标题]]</code> 建立链接后，这里会自动出现关系。
        </div>
      </div>
      <div v-else class="py-8 text-center text-[12px] text-ink-400">加载中…</div>
    </Modal>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { aiApi, noteApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import { NoteCollab } from '../../utils/collab'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const tree = ref([])
const tags = ref([])
const current = ref(null)
const activeNote = ref(null)
const activeTag = ref(null)
const tagNotes = ref([])
const sideTab = ref('all')
const trashList = ref([])
const editorTab = ref('write')
const showVersions = ref(false)
const versions = ref([])
const showTemplates = ref(false)
const templates = ref([])
const showOutline = ref(false)
const outline = ref([])
const showStats = ref(false)
const stats = ref({})
const showTagMgr = ref(false)
const newTagName = ref('')
const saving = ref(false)
const tagInput = ref('')
let saveTimer = null

// ---- 双链 ----
const rightPanel = ref(false)
const rightTab = ref('links')
const backlinks = ref([])
const outgoingLinks = ref([])
const dangling = ref([])
const graph = ref(null)
const showGraph = ref(false)
const linkSuggest = ref([])
let linkQuery = { start: -1, end: -1 }

const backlinkCount = computed(() => backlinks.value.length)

// ---- AI ----
const aiBusy = ref(false)
const aiSummary = ref('')
const aiPoints = ref([])
const aiQa = ref([])
const aiQuestion = ref('')
const aiProvider = ref('')
const aiHint = ref('')

// ---- 协同 ----
const collabMode = ref(false)
const collabStatus = ref('off')
const collabPeers = ref([])
const collabText = ref('')
let collab = null

const collabStatusLabel = computed(() => ({
  off: '未开启', connecting: '连接中', connected: '已连接', ready: '同步中', closed: '已断开',
}[collabStatus.value] || collabStatus.value))

const shownList = computed(() => (activeTag.value ? tagNotes.value : flattenTree(tree.value)))
function flattenTree(nodes) {
  const out = []
  for (const n of nodes) { out.push(n); if (n.children) out.push(...flattenTree(n.children)) }
  return out
}
const rendered = computed(() => {
  try { return marked.parse(current.value?.content || '') } catch (e) { return current.value?.content || '' }
})

async function loadTree() {
  const r = await noteApi.tree()
  tree.value = r.tree || []
}
async function loadTags() {
  const r = await noteApi.tags()
  tags.value = r.list || []
}
async function loadTrash() {
  const r = await noteApi.trash()
  trashList.value = r.list || []
}
async function loadTemplates() {
  const r = await noteApi.templates()
  templates.value = r.list || []
}
function switchSide(t) {
  sideTab.value = t
  if (t === 'trash') loadTrash()
}
async function openNote(id) {
  if (collabMode.value) stopCollab()
  current.value = await noteApi.detail(id)
  activeNote.value = id
  activeTag.value = null
  backlinks.value = current.value.backlinks || []
  outgoingLinks.value = current.value.outgoing_links || []
  aiSummary.value = current.value.ai_summary || ''
  aiPoints.value = []
  aiQa.value = []
  linkSuggest.value = []
  resetAiInfo()
  if (rightPanel.value) loadDangling()
}
async function createNote() {
  const n = await noteApi.create({ title: '未命名笔记', content: '' })
  loadTree(); openNote(n.id)
}
async function useTemplate(key) {
  const n = await noteApi.fromTemplate(key)
  showTemplates.value = false
  loadTree(); openNote(n.id)
}
async function duplicate() {
  if (!current.value) return
  const n = await noteApi.copy(current.value.id)
  app.toastMsg('已复制', 'success')
  loadTree(); openNote(n.id)
}
async function deleteNote() {
  await noteApi.remove(current.value.id)
  app.toastMsg('已移入回收站', 'success')
  current.value = null
  loadTree()
}
async function restoreNote(n) {
  await noteApi.batch({ action: 'restore', note_ids: [n.id] })
  loadTrash(); loadTree()
}
async function destroyNote(n) {
  if (!confirm('彻底删除无法恢复？')) return
  await noteApi.batch({ action: 'destroy', note_ids: [n.id] })
  loadTrash()
}
async function emptyTrash() {
  if (!confirm('清空回收站？')) return
  await noteApi.emptyTrash()
  loadTrash()
}
function autoSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(async () => {
    if (!current.value || collabMode.value) return
    saving.value = true
    current.value = await noteApi.update(current.value.id, { title: current.value.title, content: current.value.content })
    loadTree()
    setTimeout(() => (saving.value = false), 600)
  }, 800)
}

// ================= 双链 =================
async function loadBacklinks() {
  if (!current.value) return
  const r = await noteApi.backlinks(current.value.id)
  backlinks.value = r.backlinks || []
  outgoingLinks.value = r.outgoing_links || []
  if (rightPanel.value) loadDangling()
}
async function loadDangling() {
  try {
    dangling.value = (await noteApi.dangling()).list || []
  } catch (e) { dangling.value = [] }
}
async function loadGraph() {
  graph.value = await noteApi.linkGraph(120)
  showGraph.value = true
}
async function createFromTitle(title) {
  const n = await noteApi.fromTitle(title)
  app.toastMsg('已创建并接上双链', 'success')
  loadTree()
  if (n.id) openNote(n.id)
}
function onContentInput(e) {
  if (collabMode.value && collab) {
    collab.applyLocalText(e.target.value)
    return
  }
  autoSave()
  detectLinkQuery(e.target)
}
function detectLinkQuery(el) {
  if (!el || collabMode.value) return
  const pos = el.selectionStart ?? 0
  const before = (el.value || '').slice(0, pos)
  const open = before.lastIndexOf('[[')
  if (open < 0) { linkSuggest.value = []; return }
  const frag = before.slice(open + 2)
  if (frag.includes(']]') || frag.includes('\n') || frag.length > 30) {
    linkSuggest.value = []
    return
  }
  linkQuery = { start: open, end: pos }
  noteApi.linkSuggest(frag.trim(), current.value?.id)
    .then((r) => { linkSuggest.value = (r.list || []).slice(0, 8) })
    .catch(() => { linkSuggest.value = [] })
}
function insertLink(title) {
  if (!current.value || linkQuery.start < 0) return
  const val = current.value.content || ''
  current.value.content = `${val.slice(0, linkQuery.start)}[[${title}]]${val.slice(linkQuery.end)}`
  linkSuggest.value = []
  autoSave()
  // 出链/反链由后端信号异步重建，稍后刷新面板
  setTimeout(loadBacklinks, 900)
}

// ================= AI =================
function resetAiInfo() {
  aiHint.value = ''
  aiProvider.value = ''
}
async function ensureAiStatus() {
  if (aiProvider.value) return
  try {
    const s = await aiApi.status()
    aiProvider.value = s.mode_label || s.provider
    aiHint.value = s.configured ? '' : '未配置大模型，使用本地降级'
  } catch (e) { aiProvider.value = '本地' }
}
async function aiSummarize() {
  if (!current.value || aiBusy.value) return
  aiBusy.value = true
  try {
    const r = await aiApi.summarize(current.value.id, { force: false })
    aiSummary.value = r.summary || ''
    aiPoints.value = r.key_points || []
    aiProvider.value = r.provider === 'cache' ? '缓存' : (r.provider === 'llm' ? '大模型' : '本地降级')
    aiHint.value = r.fallback_reason || ''
  } catch (e) {
    app.toastMsg(e.message || '生成失败', 'error')
  } finally {
    aiBusy.value = false
  }
}
async function aiAsk() {
  const q = aiQuestion.value.trim()
  if (!q || !current.value || aiBusy.value) return
  aiBusy.value = true
  try {
    const r = await aiApi.askNote(current.value.id, q)
    aiQa.value.unshift({ q, a: r.answer, refs: r.references || [] })
    aiQuestion.value = ''
    aiProvider.value = r.provider === 'llm' ? '大模型' : '本地降级'
    aiHint.value = r.fallback_reason || ''
  } catch (e) {
    app.toastMsg(e.message || '提问失败', 'error')
  } finally {
    aiBusy.value = false
  }
}

// ================= 协同编辑 =================
function toggleCollab() {
  if (collabMode.value) { stopCollab(); return }
  if (!current.value) return
  collabMode.value = true
  collabStatus.value = 'connecting'
  collabText.value = current.value.content || ''
  collab = new NoteCollab(current.value.id, {
    initialContent: current.value.content || '',
    onText: (t) => { collabText.value = t; current.value.content = t },
    onStatus: (s) => { collabStatus.value = s },
    onPresence: (list) => { collabPeers.value = (list || []).map((p) => p.name) },
  })
  collab.connect()
  app.toastMsg('已开启协同编辑，内容将实时同步', 'success')
}
function stopCollab() {
  if (collab) collab.destroy()
  collab = null
  collabMode.value = false
  collabStatus.value = 'off'
  collabPeers.value = []
  // 拉回服务端最终内容
  if (current.value) noteApi.detail(current.value.id).then((r) => { current.value = r })
}
async function toggleFlag(flag) {
  current.value = await noteApi.update(current.value.id, { [flag]: !current.value[flag] })
  loadTree()
}
async function addTag() {
  const name = tagInput.value.trim()
  if (!name) return
  current.value = await noteApi.update(current.value.id, { tags: [...(current.value.tag_names || []), name] })
  tagInput.value = ''
  loadTags(); loadTree()
}
async function removeTag(name) {
  current.value = await noteApi.update(current.value.id, { tags: current.value.tag_names.filter((t) => t !== name) })
  loadTags()
}
async function loadVersions() {
  versions.value = (await noteApi.versions(current.value.id)).list || []
}
async function rollback(v) {
  const r = await noteApi.rollback(current.value.id, v.version)
  current.value = r.note
  showVersions.value = false
  loadTree()
}
async function loadOutline() {
  outline.value = (await noteApi.outline(current.value.id)).outline || []
}
async function loadStats() {
  stats.value = await noteApi.stats()
}
async function filterByTag(name) {
  if (activeTag.value === name) { activeTag.value = null; tagNotes.value = []; return }
  activeTag.value = name
  tagNotes.value = (await noteApi.list({ tag: name, all: 1, page_size: 100 })).list || []
}
async function saveTag(t) {
  await noteApi.updateTag(t.id, { name: t.name, color: t.color })
  loadTags()
}
async function delTag(t) {
  await noteApi.deleteTag(t.id)
  loadTags()
}
async function addNewTag() {
  if (!newTagName.value.trim()) return
  await noteApi.createTag({ name: newTagName.value.trim(), color: '#0ea5e9' })
  newTagName.value = ''
  loadTags()
}
onMounted(() => { loadTree(); loadTags(); loadTemplates(); ensureAiStatus(); loadDangling() })
onBeforeUnmount(() => { if (collab) collab.destroy() })
</script>
