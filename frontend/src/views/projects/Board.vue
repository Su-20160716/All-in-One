<template>
  <div class="space-y-4" :class="themeClass">
    <div class="card flex flex-wrap items-center gap-3 p-4">
      <div class="h-3 w-12 rounded-pill" :style="{ background: project?.color || '#0ea5e9' }"></div>
      <h2 class="text-[16px] font-bold text-ink-900">{{ project?.name }}</h2>
      <span v-if="project?.is_archived" class="tag bg-amber-50 text-amber-600">已归档</span>
      <input v-model="cardKw" class="input w-40" placeholder="筛选卡片…" />
      <select v-model="prioFilter" class="input w-28">
        <option value="">全部优先级</option><option value="urgent">紧急</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option>
      </select>
      <select v-model="assigneeFilter" class="input w-28">
        <option value="">全部负责人</option><option v-for="(n,i) in project?.member_names||[]" :key="n" :value="project.member_ids[i]">{{ n }}</option>
      </select>
      <select v-model="dueFilter" class="input w-28">
        <option value="">全部到期</option><option value="overdue">已逾期</option><option value="today">今天</option><option value="week">本周</option><option value="nodate">无日期</option>
      </select>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <button class="btn-ghost text-[12px]" :class="compact?'text-brand-600':''" @click="compact=!compact; saveTheme()">{{ compact?'⊟ 紧凑':'⊞ 完整' }}</button>
        <button class="btn-ghost text-[12px]" @click="cycleTheme">🎨 {{ themeName }}</button>
        <button class="btn-ghost text-[12px]" @click="showShare=true; loadShare()">分享</button>
        <button class="btn-ghost text-[12px]" @click="showMembers = true">成员</button>
        <button class="btn-ghost text-[12px]" @click="showStats = true; loadStats(); loadBurndown()">统计</button>
        <button class="btn-outline" @click="showNewCard = { board: null }">＋ 新卡片</button>
      </div>
    </div>

    <div class="flex items-start gap-3 overflow-x-auto pb-2">
      <div v-for="b in boards" :key="b.id" class="w-72 shrink-0 rounded-card bg-ink-100/70 p-2.5" @dragover.prevent @drop="onDrop($event, b.id)">
        <div class="mb-2 flex items-center justify-between px-1">
          <span class="text-[13px] font-semibold text-ink-700">{{ b.name }} <span class="text-[11px] font-normal text-ink-400">{{ matchCards(b).length }}</span></span>
          <div class="flex gap-1">
            <button class="btn-ghost px-1.5 text-[12px]" @click="renameBoard(b)">✎</button>
            <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="removeBoard(b)">✕</button>
          </div>
        </div>
        <div class="space-y-2">
          <div v-for="c in matchCards(b)" :key="c.id" class="card group cursor-grab p-3 active:cursor-grabbing" :class="cardTone(c)" draggable="true" @dragstart="onDragStart($event, c)" @click="openCard(c)">
            <div class="flex items-start justify-between gap-2">
              <span class="text-[13px] font-medium leading-snug">{{ c.title }}</span>
              <span class="shrink-0 text-[12px]">{{ prioIcon(c.priority) }}</span>
            </div>
            <div v-if="!compact" class="mt-2 flex flex-wrap items-center gap-1">
              <span v-for="l in c.labels || []" :key="labelName(l)" class="rounded-pill px-1.5 py-0.5 text-[10px]" :style="labelStyle(l)">{{ labelName(l) }}</span>
            </div>
            <div v-if="!compact && c.subtask_total" class="mt-2">
              <div class="h-1.5 w-full overflow-hidden rounded-pill bg-ink-100"><div class="h-full rounded-pill bg-emerald-500" :style="{ width: (c.progress||0)+'%' }"></div></div>
            </div>
            <div class="mt-2 flex items-center gap-2 text-[11px] text-ink-400">
              <span v-if="c.due_date" :class="dueTone(c)">{{ dueIcon(c) }} {{ c.due_date }}</span>
              <span v-if="!compact && c.subtask_total">☑ {{ c.subtask_done }}/{{ c.subtask_total }}</span>
              <span v-if="!compact && c.comment_count" class="ml-auto">💬 {{ c.comment_count }}</span>
              <span v-if="c.assignee_names.length" :class="compact?'':'ml-auto'">{{ c.assignee_names.map((n) => n.slice(0, 1)).join('') }}</span>
            </div>
            <button class="absolute right-1 top-1 hidden rounded bg-white/90 px-1 text-[10px] shadow group-hover:block" title="复制卡片" @click.stop="quickCopy(c)">⧉</button>
          </div>
        </div>
        <button class="mt-2 w-full rounded-control border border-dashed border-ink-200 py-1.5 text-[12px] text-ink-400 hover:border-brand-300 hover:text-brand-600" @click="showNewCard = { board: b.id }">＋ 添加卡片</button>
      </div>
      <div class="w-56 shrink-0">
        <button class="w-full rounded-card border border-dashed border-ink-200 py-2.5 text-[12px] text-ink-400 hover:border-brand-300 hover:text-brand-600" @click="addBoard">＋ 新建列</button>
      </div>
    </div>

    <!-- 新建卡片 -->
    <Modal :show="!!showNewCard" title="新建任务卡片" @close="showNewCard = null">
      <div class="space-y-3">
        <select v-if="!showNewCard?.board" v-model="cardForm.board" class="input">
          <option :value="null" disabled>选择列</option>
          <option v-for="b in boards" :key="b.id" :value="b.id">{{ b.name }}</option>
        </select>
        <input v-model="cardForm.title" class="input" placeholder="任务标题" />
        <textarea v-model="cardForm.description" class="input h-20 resize-none" placeholder="描述（选填）"></textarea>
        <div class="flex gap-3">
          <select v-model="cardForm.priority" class="input w-1/2">
            <option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="urgent">紧急</option>
          </select>
          <input v-model="cardForm.due_date" type="date" class="input w-1/2" />
        </div>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="showNewCard = null">取消</button><button class="btn-primary" @click="createCard">创建</button></div>
      </div>
    </Modal>

    <!-- 卡片详情 -->
    <Modal :show="!!activeCard" :title="activeCard?.title" width="640px" @close="activeCard = null">
      <div v-if="activeCard" class="space-y-4">
        <div class="flex flex-wrap gap-2">
          <select v-model="activeCard.priority" class="input w-32" @change="updateCard({ priority: activeCard.priority })">
            <option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="urgent">紧急</option>
          </select>
          <select v-model="activeCard.status" class="input w-32" @change="updateCard({ status: activeCard.status })">
            <option value="todo">待办</option><option value="doing">进行中</option><option value="done">已完成</option>
          </select>
          <input v-model="activeCard.due_date" type="date" class="input w-40" @change="updateCard({ due_date: activeCard.due_date })" />
          <div class="flex items-center gap-1"><span class="text-[12px] text-ink-500">故事点</span><input v-model.number="activeCard.story_points" type="number" min="0" class="input w-20" @change="updateCard({ story_points: activeCard.story_points })" /></div>
        </div>
        <textarea v-model="activeCard.description" class="input h-20 resize-none" placeholder="任务描述" @change="updateCard({ description: activeCard.description })"></textarea>

        <!-- 负责人 -->
        <div>
          <div class="mb-1 text-[12px] font-medium text-ink-600">负责人</div>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="(name, i) in project?.member_names || []" :key="i" class="rounded-pill px-2 py-0.5 text-[11px]" :class="activeCard.assignee_ids.includes(project.member_ids[i]) ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-500'" @click="toggleAssignee(project.member_ids[i])">{{ name }}</button>
          </div>
        </div>

        <!-- 标签 -->
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">标签</div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span v-for="l in activeCard.labels || []" :key="labelName(l)" class="rounded-pill px-2 py-0.5 text-[11px]" :style="labelStyle(l)">{{ labelName(l) }} <button @click="removeLabel(labelName(l))">×</button></span>
            <input v-model="labelInput" class="input w-24 py-1 text-[12px]" placeholder="+标签" @keyup.enter="addLabel" />
          </div>
        </div>

        <!-- 子任务 -->
        <div>
          <div class="mb-1.5 flex items-center justify-between">
            <span class="text-[12px] font-medium text-ink-600">子任务 {{ activeCard.subtask_done }}/{{ activeCard.subtask_total }}（{{ activeCard.progress }}%）</span>
          </div>
          <div class="h-1.5 w-full overflow-hidden rounded-pill bg-ink-100"><div class="h-full rounded-pill bg-emerald-500" :style="{ width: (activeCard.progress||0)+'%' }"></div></div>
          <div class="mt-1.5 space-y-1">
            <div v-for="s in subtasks" :key="s.id" class="group flex items-center gap-2 text-[13px]">
              <input type="checkbox" :checked="s.is_done" @change="toggleSubtask(s)" />
              <span :class="s.is_done ? 'text-ink-300 line-through' : 'text-ink-700'">{{ s.title }}</span>
              <button class="ml-auto text-[11px] text-rose-400 opacity-0 group-hover:opacity-100" @click="delSubtask(s)">删除</button>
            </div>
          </div>
          <div class="mt-1.5 flex gap-2">
            <input v-model="subInput" class="input py-1 text-[12px]" placeholder="新增子任务，回车" @keyup.enter="addSubtask" />
          </div>
        </div>

        <!-- 工时 -->
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">工时记录（累计 {{ Math.round(activeCard.spent_minutes / 60 * 10) / 10 }}h）</div>
          <div class="space-y-1">
            <div v-for="w in worklogs" :key="w.id" class="flex items-center justify-between text-[12px] text-ink-600">
              <span>{{ w.user_name }} · {{ (w.minutes / 60).toFixed(1) }}h · {{ w.note || '-' }}</span>
              <button class="text-rose-400" @click="delWorklog(w)">×</button>
            </div>
          </div>
          <div class="mt-1.5 flex gap-2">
            <input v-model.number="wlMinutes" type="number" min="1" class="input w-24 py-1 text-[12px]" placeholder="分钟" />
            <input v-model="wlNote" class="input flex-1 py-1 text-[12px]" placeholder="工作说明" @keyup.enter="addWorklog" />
            <button class="btn-outline py-1 text-[12px]" @click="addWorklog">记录</button>
          </div>
        </div>

        <!-- 评论 -->
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">评论 ({{ comments.length }})</div>
          <div class="max-h-40 space-y-2 overflow-y-auto">
            <div v-for="cm in comments" :key="cm.id" class="group rounded-control bg-ink-50 px-3 py-2">
              <div class="flex items-center text-[11px] text-ink-400">
                <span>{{ cm.author_name }} · {{ formatTime(cm.created_at) }}</span>
                <span class="ml-auto opacity-0 group-hover:opacity-100">
                  <button class="mr-2 text-brand-600" @click="editComment(cm)">编辑</button>
                  <button v-if="cm.can_delete" class="text-rose-500" @click="delComment(cm)">删除</button>
                </span>
              </div>
              <div class="mt-0.5 text-[13px] text-ink-700">{{ cm.content }}</div>
            </div>
          </div>
          <div class="mt-2 flex gap-2">
            <input v-model="commentInput" class="input" placeholder="写评论…" @keyup.enter="addComment" />
            <button class="btn-primary" @click="addComment">发送</button>
          </div>
        </div>

        <div class="flex justify-between border-t border-ink-100 pt-3">
          <button class="btn-outline" @click="copyCard">⧉ 复制卡片</button>
          <button class="btn-danger" @click="deleteCard">删除任务</button>
        </div>
      </div>
    </Modal>

    <!-- 成员管理 -->
    <Modal :show="showMembers" title="成员管理" @close="showMembers = false">
      <div class="space-y-3">
        <div class="flex gap-2">
          <input v-model="memberQ" class="input flex-1" placeholder="搜索用户名/昵称" @input="searchMembers" />
        </div>
        <div v-if="candidates.length" class="max-h-40 space-y-1 overflow-y-auto rounded-control border border-ink-100 p-1">
          <div v-for="c in candidates" :key="c.id" class="flex items-center justify-between rounded-control px-2 py-1.5 text-[13px] hover:bg-ink-50">
            <span>{{ c.display_name }} <span class="text-[11px] text-ink-400">@{{ c.username }}</span></span>
            <button class="btn-outline px-2 py-0.5 text-[11px]" @click="addMembers([c.id])">＋ 添加</button>
          </div>
        </div>
        <div class="divide-y divide-ink-50">
          <div v-for="(m, i) in project?.member_names || []" :key="i" class="flex items-center justify-between py-2 text-[13px]">
            <span>{{ m }}</span>
            <button class="btn-ghost px-1.5 text-[12px] text-rose-500" @click="removeMember(project.member_ids[i])">移除</button>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 统计 + 燃尽图 -->
    <Modal :show="showStats" title="项目统计" width="560px" @close="showStats = false">
      <div v-if="stats" class="space-y-4">
        <div class="grid grid-cols-3 gap-2 text-center">
          <div class="rounded-control bg-ink-50 p-3"><div class="text-[20px] font-bold">{{ stats.total }}</div><div class="text-[11px] text-ink-500">总任务</div></div>
          <div class="rounded-control bg-emerald-50 p-3"><div class="text-[20px] font-bold text-emerald-600">{{ stats.done }}</div><div class="text-[11px] text-ink-500">已完成</div></div>
          <div class="rounded-control bg-rose-50 p-3"><div class="text-[20px] font-bold text-rose-600">{{ stats.overdue }}</div><div class="text-[11px] text-ink-500">已逾期</div></div>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">燃尽图（剩余工作量）</div>
          <svg v-if="burn.dates && burn.dates.length" :viewBox="`0 0 520 200`" class="w-full rounded-control bg-ink-50">
            <polyline :points="linePoints(burn.remaining)" fill="none" stroke="#0ea5e9" stroke-width="2" />
            <polyline :points="linePoints(burn.ideal)" fill="none" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="4 3" />
          </svg>
          <div v-else class="grid h-24 place-items-center rounded-control bg-ink-50 text-[12px] text-ink-400">暂无数据</div>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">各列分布</div>
          <div v-for="b in stats.by_board" :key="b.board__name" class="mb-1 flex justify-between text-[12px]"><span>{{ b.board__name }}</span><span class="text-ink-400">{{ b.c }} 张</span></div>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">最近动态</div>
          <div class="max-h-40 space-y-1.5 overflow-y-auto">
            <div v-for="a in stats.activities" :key="a.id" class="text-[12px] text-ink-500"><span class="font-medium text-ink-700">{{ a.user_name }}</span> {{ a.action }} {{ a.target }} <span class="text-[10px] text-ink-300">{{ formatTime(a.created_at) }}</span></div>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 分享链接 -->
    <Modal :show="showShare" title="只读分享看板" @close="showShare = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-500">生成免登录只读链接，任何人可查看当前看板（不可编辑）。</p>
        <div v-if="shareUrl" class="flex items-center gap-2 rounded-control bg-ink-50 p-2">
          <input :value="shareUrl" readonly class="input flex-1 py-1 text-[12px]" />
          <button class="btn-outline text-[12px]" @click="copyShare">复制链接</button>
          <button class="btn-ghost text-[12px] text-rose-500" @click="revokeShare">撤销</button>
        </div>
        <div v-else class="flex justify-end">
          <button class="btn-primary" @click="genShare">生成分享链接</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { projectApi, authApi } from '../../api'
import { shareUrl as buildShareUrl } from '../../api/base'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import Modal from '../../components/Modal.vue'

const route = useRoute()
const app = useAppStore()
const projectId = route.params.id
const project = ref(null)
const boards = ref([])
const cardKw = ref('')
const prioFilter = ref('')
const assigneeFilter = ref('')
const dueFilter = ref('')
const compact = ref(localStorage.getItem('board_compact') === '1')
const themeIdx = ref(Number(localStorage.getItem('board_theme') || 0))
const showNewCard = ref(null)
const cardForm = reactive({ board: null, title: '', description: '', priority: 'medium', due_date: '' })
const activeCard = ref(null)
const comments = ref([])
const commentInput = ref('')
const labelInput = ref('')
const subtasks = ref([])
const subInput = ref('')
const worklogs = ref([])
const wlMinutes = ref(null)
const wlNote = ref('')
const showMembers = ref(false)
const memberQ = ref('')
const candidates = ref([])
const showStats = ref(false)
const stats = ref(null)
const burn = ref({ dates: [], remaining: [], ideal: [] })
const showShare = ref(false)
const shareUrl = ref('')
const shareToken = ref('')
let dragCard = null

const THEME_BGS = ['', 'bg-sky-50/40', 'bg-amber-50/40', 'bg-emerald-50/40', 'bg-slate-100/60']
const THEME_NAMES = ['浅色', '天蓝', '暖橙', '青绿', '深灰']
const themeClass = ref(THEME_BGS[themeIdx.value])
const themeName = THEME_NAMES[themeIdx.value]
function cycleTheme() { themeIdx.value = (themeIdx.value + 1) % THEME_BGS.length; themeClass.value = THEME_BGS[themeIdx.value]; localStorage.setItem('board_theme', String(themeIdx.value)) }
function saveTheme() { localStorage.setItem('board_compact', compact.value ? '1' : '0') }

const LABEL_COLORS = ['#dbeafe', '#fce7f3', '#dcfce7', '#fef9c3', '#ffedd5', '#e0e7ff', '#f3e8ff']
const LABEL_TEXT = ['#1d4ed8', '#be185d', '#15803d', '#a16207', '#c2410c', '#4338ca', '#7e22ce']
function labelName(l) { return typeof l === 'string' ? l : (l.name || '') }
function labelStyle(l) {
  const name = labelName(l)
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  const i = h % LABEL_COLORS.length
  return { background: LABEL_COLORS[i], color: LABEL_TEXT[i] }
}

const prioIcon = (p) => ({ low: '🟢', medium: '🟡', high: '🟠', urgent: '🔴' }[p] || '⚪')
function todayStr() { return new Date().toISOString().slice(0, 10) }
function dueTone(c) {
  if (c.is_overdue) return 'font-medium text-rose-500'
  if (c.due_date === todayStr()) return 'font-medium text-orange-500'
  return ''
}
function dueIcon(c) {
  if (c.is_overdue) return '⚠'
  if (c.due_date === todayStr()) return '📌'
  return '🗓'
}
function cardTone(c) {
  if (c.is_overdue) return 'border-l-4 border-l-rose-400'
  if (c.due_date === todayStr()) return 'border-l-4 border-l-orange-400'
  return ''
}
function matchCards(b) {
  const today = todayStr()
  return (b.cards || []).filter((c) => {
    const okKw = !cardKw.value || c.title.includes(cardKw.value)
    const okPrio = !prioFilter.value || c.priority === prioFilter.value
    const okAssignee = !assigneeFilter.value || (c.assignee_ids || []).map(String).includes(String(assigneeFilter.value))
    let okDue = true
    if (dueFilter.value === 'overdue') okDue = c.is_overdue
    else if (dueFilter.value === 'today') okDue = c.due_date === today
    else if (dueFilter.value === 'week') { const diff = (new Date(c.due_date) - new Date(today)) / 86400000; okDue = c.due_date && diff >= 0 && diff <= 7 }
    else if (dueFilter.value === 'nodate') okDue = !c.due_date
    return okKw && okPrio && okAssignee && okDue
  })
}

async function load() {
  try {
    const r = await projectApi.board(projectId)
    project.value = r.project
    boards.value = r.boards || []
  } catch (e) { app.toastMsg(e?.message || '加载看板失败', 'error') }
}
async function addBoard() {
  try {
    const name = prompt('新列名称：')
    if (name) { await projectApi.createBoard(projectId, name); load() }
  } catch (e) { app.toastMsg(e?.message || '新建列失败', 'error') }
}
async function renameBoard(b) {
  try {
    const name = prompt('列名称：', b.name)
    if (name) { await projectApi.renameBoard(b.id, name); load() }
  } catch (e) { app.toastMsg(e?.message || '重命名失败', 'error') }
}
async function removeBoard(b) {
  try {
    if (confirm(`删除列「${b.name}」及所有卡片？`)) { await projectApi.deleteBoard(b.id); load() }
  } catch (e) { app.toastMsg(e?.message || '删除列失败', 'error') }
}
async function createCard() {
  try {
    const boardId = showNewCard.value.board || cardForm.board
    if (!cardForm.title.trim() || !boardId) return app.toastMsg('请填写标题并选择列', 'error')
    await projectApi.createCard(boardId, { title: cardForm.title, description: cardForm.description, priority: cardForm.priority, due_date: cardForm.due_date || null })
    app.toastMsg('已创建', 'success')
    Object.assign(cardForm, { board: null, title: '', description: '', due_date: '' })
    showNewCard.value = null
    load()
  } catch (e) { app.toastMsg(e?.message || '创建卡片失败', 'error') }
}
function onDragStart(e, card) { dragCard = card; e.dataTransfer.effectAllowed = 'move' }
async function onDrop(e, targetBoardId) {
  try {
    if (!dragCard) return
    const target = boards.value.find((b) => b.id === targetBoardId)
    await projectApi.moveCard(dragCard.id, targetBoardId, target.cards.length)
    dragCard = null
    load()
  } catch (e) { app.toastMsg(e?.message || '移动卡片失败', 'error') }
}
async function openCard(c) {
  try {
    const [full, cm] = await Promise.all([projectApi.card(c.id), projectApi.comments(c.id)])
    activeCard.value = { ...full }
    comments.value = cm.list || []
    subtasks.value = full.subtasks || []
    worklogs.value = full.worklogs || []
  } catch (e) { app.toastMsg(e?.message || '打开卡片失败', 'error') }
}
async function updateCard(patch) {
  try {
    const r = await projectApi.updateCard(activeCard.value.id, patch)
    activeCard.value = { ...activeCard.value, ...r }
    load()
  } catch (e) { app.toastMsg(e?.message || '更新卡片失败', 'error') }
}
async function deleteCard() {
  try {
    if (!confirm('删除该任务？')) return
    await projectApi.deleteCard(activeCard.value.id)
    activeCard.value = null
    load()
  } catch (e) { app.toastMsg(e?.message || '删除卡片失败', 'error') }
}
async function copyCard() {
  try {
    await projectApi.copyCard(activeCard.value.id)
    app.toastMsg('已复制', 'success')
    activeCard.value = null
    load()
  } catch (e) { app.toastMsg(e?.message || '复制卡片失败', 'error') }
}
async function quickCopy(c) {
  try {
    await projectApi.copyCard(c.id)
    app.toastMsg('已复制卡片', 'success')
    load()
  } catch (e) { app.toastMsg(e?.message || '复制卡片失败', 'error') }
}
async function addComment() {
  try {
    const content = commentInput.value.trim()
    if (!content) return
    comments.value.push(await projectApi.addComment(activeCard.value.id, content))
    commentInput.value = ''
  } catch (e) { app.toastMsg(e?.message || '发表评论失败', 'error') }
}
async function editComment(cm) {
  try {
    const content = prompt('修改评论：', cm.content)
    if (content === null) return
    const r = await projectApi.updateComment(activeCard.value.id, cm.id, content)
    Object.assign(cm, r)
  } catch (e) { app.toastMsg(e?.message || '修改评论失败', 'error') }
}
async function delComment(cm) {
  try {
    await projectApi.deleteComment(activeCard.value.id, cm.id)
    comments.value = comments.value.filter((x) => x.id !== cm.id)
  } catch (e) { app.toastMsg(e?.message || '删除评论失败', 'error') }
}
async function addLabel() {
  try {
    const l = labelInput.value.trim()
    if (!l) return
    const labels = [...(activeCard.value.labels || []), l]
    labelInput.value = ''
    await updateCard({ labels })
  } catch (e) { app.toastMsg(e?.message || '添加标签失败', 'error') }
}
async function removeLabel(l) {
  try {
    await updateCard({ labels: (activeCard.value.labels || []).filter((x) => labelName(x) !== l) })
  } catch (e) { app.toastMsg(e?.message || '移除标签失败', 'error') }
}
async function toggleAssignee(uid) {
  try {
    let ids = [...activeCard.value.assignee_ids]
    ids = ids.includes(uid) ? ids.filter((x) => x !== uid) : [...ids, uid]
    await updateCard({ assignee_ids: ids })
  } catch (e) { app.toastMsg(e?.message || '调整负责人失败', 'error') }
}
async function addSubtask() {
  try {
    const title = subInput.value.trim()
    if (!title) return
    subtasks.value.push(await projectApi.addSubtask(activeCard.value.id, title))
    subInput.value = ''
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '添加子任务失败', 'error') }
}
async function toggleSubtask(s) {
  try {
    const r = await projectApi.updateSubtask(activeCard.value.id, s.id, { is_done: !s.is_done })
    Object.assign(s, r)
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '更新子任务失败', 'error') }
}
async function delSubtask(s) {
  try {
    await projectApi.deleteSubtask(activeCard.value.id, s.id)
    subtasks.value = subtasks.value.filter((x) => x.id !== s.id)
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '删除子任务失败', 'error') }
}
async function addWorklog() {
  try {
    if (!wlMinutes.value) return
    const wl = await projectApi.addWorklog(activeCard.value.id, { minutes: wlMinutes.value, note: wlNote.value })
    worklogs.value.push(wl)
    wlMinutes.value = null; wlNote.value = ''
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '记录工时失败', 'error') }
}
async function delWorklog(w) {
  try {
    await projectApi.deleteWorklog(activeCard.value.id, w.id)
    worklogs.value = worklogs.value.filter((x) => x.id !== w.id)
    refreshCardMeta()
  } catch (e) { app.toastMsg(e?.message || '删除工时失败', 'error') }
}
async function refreshCardMeta() {
  try {
    const full = await projectApi.card(activeCard.value.id)
    activeCard.value = { ...activeCard.value, subtask_total: full.subtask_total, subtask_done: full.subtask_done, progress: full.progress, spent_minutes: full.spent_minutes }
  } catch (e) { app.toastMsg(e?.message || '刷新卡片失败', 'error') }
}
let memberTimer = null
function searchMembers() {
  clearTimeout(memberTimer)
  memberTimer = setTimeout(async () => {
    try {
      candidates.value = (await authApi.directory(memberQ.value)).list || []
    } catch (e) { app.toastMsg(e?.message || '搜索成员失败', 'error') }
  }, 250)
}
async function addMembers(ids) {
  try {
    await projectApi.addMembers(projectId, ids)
    app.toastMsg('已添加', 'success')
    load()
  } catch (e) { app.toastMsg(e?.message || '添加成员失败', 'error') }
}
async function removeMember(uid) {
  try {
    await projectApi.removeMember(projectId, uid)
    load()
  } catch (e) { app.toastMsg(e?.message || '移出成员失败', 'error') }
}
async function loadStats() {
  try {
    stats.value = await projectApi.stats(projectId)
  } catch (e) { app.toastMsg(e?.message || '加载统计失败', 'error') }
}
async function loadBurndown() {
  try {
    burn.value = await projectApi.burndown(projectId)
  } catch (e) { app.toastMsg(e?.message || '加载燃尽图失败', 'error') }
}
function linePoints(arr) {
  if (!arr || arr.length < 2) return ''
  const max = Math.max(...arr, 1)
  const w = 520, h = 180, pad = 10
  return arr.map((v, i) => `${(i / (arr.length - 1)) * (w - 2 * pad) + pad},${h - pad - (v / max) * (h - 2 * pad)}`).join(' ')
}
async function loadShare() {
  shareUrl.value = ''; shareToken.value = ''
}
async function genShare() {
  try {
    const r = await projectApi.createShare(projectId)
    shareToken.value = r.token
    // F4：对外链接走 base.js shareUrl()，部署时给出正确的前端站点地址
    shareUrl.value = buildShareUrl(r.token)
    app.toastMsg('已生成分享链接', 'success')
  } catch (e) { app.toastMsg(e?.message || '生成分享链接失败', 'error') }
}
function copyShare() {
  // 剪贴板在非安全上下文/无权限时会 reject，吞掉避免触发全局兜底弹错
  navigator.clipboard?.writeText(shareUrl.value).catch(() => {})
  app.toastMsg('已复制', 'success')
}
async function revokeShare() {
  try {
    if (!shareToken.value) return
    await projectApi.revokeShare(projectId, shareToken.value)
    shareUrl.value = ''; shareToken.value = ''
    app.toastMsg('已撤销', 'success')
  } catch (e) { app.toastMsg(e?.message || '撤销分享失败', 'error') }
}
onMounted(load)
</script>
