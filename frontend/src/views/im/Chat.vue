<template>
  <div class="flex h-[calc(100vh-110px)] gap-4">
    <!-- 会话列表 -->
    <div class="card flex w-72 shrink-0 flex-col">
      <div class="flex items-center gap-2 border-b border-ink-100 p-3">
        <input v-model="keyword" class="input flex-1" placeholder="搜索会话…" @keyup.enter="loadSessions" />
        <button class="btn-primary px-2.5" title="发起聊天" @click="openNew">＋</button>
      </div>
      <div class="flex gap-1 border-b border-ink-100 px-2 py-1.5 text-[11px]">
        <button class="rounded-pill px-2 py-0.5" :class="!showArchived?'bg-brand-600 text-white':'text-ink-500'" @click="showArchived=false; loadSessions()">会话</button>
        <button class="rounded-pill px-2 py-0.5" :class="showArchived?'bg-brand-600 text-white':'text-ink-500'" @click="showArchived=true; loadSessions()">归档</button>
      </div>
      <div class="flex-1 overflow-y-auto">
        <div v-for="s in sessions" :key="s.id" class="flex cursor-pointer items-center gap-2.5 border-b border-ink-50 px-3 py-2.5" :class="activeSession?.id === s.id ? 'bg-brand-50/60' : 'hover:bg-ink-50/60'" @click="openSession(s)">
          <div class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-brand-100 text-[13px] font-semibold text-brand-700">{{ avatarText(s) }}</div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1 truncate text-[13px] font-medium">
              <span v-if="s.is_pinned">📌</span><span v-if="s.is_muted">🔕</span>
              <span class="truncate">{{ sessionName(s) }}</span>
            </div>
            <div class="truncate text-[11px] text-ink-400">{{ lastText(s) }}</div>
          </div>
          <div class="shrink-0 text-right">
            <div v-if="s.unread" class="grid h-4 min-w-4 place-items-center rounded-pill px-1 text-[10px] font-medium" :class="s.is_muted ? 'bg-ink-300 text-white' : 'bg-rose-500 text-white'">{{ s.unread }}</div>
          </div>
        </div>
        <div v-if="!sessions.length" class="py-10 text-center text-[12px] text-ink-400">{{ showArchived?'暂无归档会话':'暂无会话' }}</div>
      </div>
    </div>

    <!-- 聊天区 -->
    <div class="card flex min-w-0 flex-1 flex-col">
      <template v-if="activeSession">
        <div class="flex items-center justify-between border-b border-ink-100 px-4 py-2.5">
          <div>
            <span class="text-[14px] font-semibold">{{ sessionName(activeSession) }}</span>
            <span class="ml-2 text-[11px] text-ink-400">{{ activeSession.type === 'group' ? activeSession.member_count + ' 人群' : '单聊' }}</span>
            <span v-if="typing" class="ml-2 text-[11px] text-brand-500">{{ typing }} 正在输入…</span>
          </div>
          <div class="flex gap-1">
            <button class="btn-ghost px-2 text-[12px]" @click="openSearch">🔍</button>
            <button class="btn-ghost px-2 text-[12px]" @click="exportChat">⬇ 导出</button>
            <button class="btn-ghost px-2 text-[12px]" @click="openKeyword">关键词</button>
            <button class="btn-ghost px-2 text-[12px]" :class="activeSession.is_pinned ? 'text-brand-600' : ''" @click="togglePin">{{ activeSession.is_pinned ? '取消置顶' : '置顶' }}</button>
            <button class="btn-ghost px-2 text-[12px]" :class="activeSession.is_muted ? 'text-amber-600' : ''" @click="toggleMute">{{ activeSession.is_muted ? '取消免打扰' : '免打扰' }}</button>
            <button class="btn-ghost px-2 text-[12px]" @click="toggleArchiveSession">{{ activeSession.is_archived ? '取消归档' : '归档' }}</button>
            <button v-if="activeSession.type === 'group'" class="btn-ghost px-2 text-[12px]" @click="showGroup = true">群管理</button>
            <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="leave">退出</button>
          </div>
        </div>

        <!-- 置顶消息区 -->
        <div v-if="pinned.length" class="border-b border-amber-100 bg-amber-50/60 px-4 py-1.5 text-[12px]">
          <span class="font-medium text-amber-700">📌 置顶</span>
          <div v-for="p in pinned" :key="p.id" class="mt-0.5 flex items-center gap-1 text-ink-600">
            <span class="truncate">{{ p.sender_name }}: {{ p.content }}</span>
            <button class="text-ink-400 hover:text-rose-500" @click="unpin(p)">×</button>
          </div>
        </div>

        <div ref="msgBox" class="flex-1 space-y-3 overflow-y-auto bg-ink-50/40 p-4">
          <div v-for="m in messages" :key="m.id" class="group flex" :class="m.sender === myId ? 'justify-end' : 'justify-start'">
            <div class="max-w-[70%]">
              <div v-if="m.sender !== myId" class="mb-0.5 text-[11px] text-ink-400">{{ m.sender_name }}</div>
              <!-- 引用回复块 -->
              <div v-if="m.reply_to_info" class="mb-1 rounded-control border-l-2 border-brand-300 bg-white/70 px-2 py-1 text-[11px] text-ink-500">
                回复 {{ m.reply_to_info.sender_name }}：{{ m.reply_to_info.content }}
              </div>
              <div class="relative rounded-card px-3 py-2 text-[13px] leading-relaxed" :class="m.sender === myId ? 'bg-brand-600 text-white' : 'bg-white text-ink-800 shadow-card'">
                <span v-if="m.is_recalled" class="italic opacity-70">消息已撤回</span>
                <template v-else>
                  <div class="chat-md" v-html="renderContent(m)"></div>
                  <span v-if="m.forward_from" class="ml-1 text-[10px] opacity-70">（转发）</span>
                </template>
                <div v-if="!m.is_recalled" class="absolute -top-2 right-2 hidden gap-1 rounded-pill bg-white px-1 text-[10px] shadow-card group-hover:flex" :class="m.sender === myId ? 'text-ink-600' : ''">
                  <button @click="replyMsg(m)">回复</button>
                  <button @click="forwardMsg(m)">转发</button>
                  <button v-if="m.sender === myId && canRecall(m)" @click="recall(m)">撤回</button>
                  <button @click="togglePinMsg(m)">📌</button>
                  <button @click="deleteForMe(m)">删除</button>
                </div>
              </div>
              <div class="mt-0.5 flex items-center gap-1 text-[10px] text-ink-300" :class="m.sender === myId ? 'justify-end' : ''">
                <span>{{ formatTime(m.created_at) }}</span>
                <span v-if="m.sender === myId">· 已读 {{ m.read_by_count || 0 }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 正在回复的消息 -->
        <div v-if="replying" class="flex items-center gap-2 border-t border-ink-100 bg-ink-50 px-3 py-1.5 text-[12px] text-ink-500">
          回复 {{ replying.sender_name }}：{{ replying.content.slice(0, 40) }}
          <button class="ml-auto text-rose-400" @click="replying = null">×</button>
        </div>

        <div class="flex items-center gap-2 border-t border-ink-100 p-3">
          <button class="btn-ghost px-2" title="表情" @click="showEmoji = !showEmoji">😊</button>
          <button class="btn-ghost px-2" title="快捷回复" @click="openQuickReplies">⚡</button>
          <div class="relative flex-1">
            <input v-model="draft" class="input w-full" placeholder="输入消息，回车发送…" @input="saveDraft" @keyup.enter="send" />
            <div v-if="showEmoji" class="absolute bottom-10 left-0 z-10 grid w-64 grid-cols-8 gap-1 rounded-card border border-ink-100 bg-white p-2 shadow-pop">
              <button v-for="e in emojiList" :key="e" class="text-[16px] hover:scale-125" @click="pickEmoji(e)">{{ e }}</button>
            </div>
          </div>
          <button class="btn-primary" @click="send">发送</button>
        </div>
      </template>
      <div v-else class="grid flex-1 place-items-center text-[13px] text-ink-400">选择一个会话开始聊天</div>
    </div>

    <!-- 新建会话 -->
    <Modal :show="showNew" title="发起聊天" @close="showNew = false">
      <div class="space-y-3">
        <div class="flex gap-2">
          <input v-model="newGroupName" class="input flex-1" placeholder="群名称（填了即建群，可多选成员）" />
        </div>
        <div class="flex gap-2">
          <input v-model="candidateQuery" class="input flex-1" placeholder="搜索用户…" @input="loadCandidates" />
          <button class="btn-outline" @click="loadCandidates">搜索</button>
        </div>
        <div class="max-h-52 space-y-1 overflow-y-auto">
          <div v-for="c in candidates" :key="c.id" class="flex items-center justify-between rounded-control px-2 py-2 hover:bg-ink-50">
            <span class="text-[13px]">{{ c.display_name }} <span class="text-[11px] text-ink-400">@{{ c.username }}</span></span>
            <input type="checkbox" :checked="picked.has(c.id)" @change="togglePick(c.id)" />
          </div>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showNew = false">取消</button>
          <button class="btn-primary" @click="startSession">发起</button>
        </div>
      </div>
    </Modal>

    <!-- 转发 -->
    <Modal :show="!!forwarding" title="转发给…" @close="forwarding = null">
      <div class="max-h-60 space-y-1 overflow-y-auto">
        <label v-for="s in sessions" :key="s.id" class="flex items-center gap-2 rounded-control px-2 py-2 text-[13px] hover:bg-ink-50">
          <input type="checkbox" :checked="forwardTargets.has(s.id)" @change="toggleForward(s.id)" /> {{ sessionName(s) }}
        </label>
      </div>
      <div class="mt-3 flex justify-end"><button class="btn-primary" @click="confirmForward">转发</button></div>
    </Modal>

    <!-- 群管理 -->
    <Modal :show="showGroup" title="群管理" @close="showGroup = false">
      <div class="space-y-3">
        <input v-model="groupAnn" class="input" placeholder="群公告" @change="updateGroup('announcement', groupAnn)" />
        <div class="flex gap-2">
          <input v-model="groupAddQ" class="input flex-1" placeholder="搜索用户添加" @input="searchAdd" />
        </div>
        <div v-if="addCandidates.length" class="max-h-32 space-y-1 overflow-y-auto rounded-control border border-ink-100 p-1">
          <div v-for="c in addCandidates" :key="c.id" class="flex items-center justify-between px-2 py-1.5 text-[13px]">
            <span>{{ c.display_name }}</span><button class="btn-outline px-2 py-0.5 text-[11px]" @click="addMember(c.id)">＋</button>
          </div>
        </div>
        <!-- 群成员搜索框 -->
        <input v-model="memberSearchQ" class="input" placeholder="搜索群成员…" />
        <div class="divide-y divide-ink-50">
          <div v-for="m in filteredMembers" :key="m.id" class="flex items-center justify-between py-2 text-[13px]">
            <span>{{ m.display_name }} <span v-if="m.id === activeSession.owner" class="tag-brand">群主</span></span>
            <button v-if="m.id !== myId" class="btn-ghost px-2 text-[12px] text-rose-500" @click="kick(m.id)">移除</button>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 快捷回复 -->
    <Modal :show="showQuickReply" title="快捷回复" @close="showQuickReply = false">
      <div class="space-y-2">
        <div v-for="q in quickReplies" :key="q.id" class="flex items-center gap-2 rounded-control border border-ink-100 p-2">
          <div class="min-w-0 flex-1"><div class="text-[12px] font-medium">{{ q.title || '未命名' }}</div><div class="truncate text-[11px] text-ink-400">{{ q.content }}</div></div>
          <button class="btn-outline text-[11px]" @click="useQuickReply(q)">使用</button>
          <button class="text-rose-400" @click="delQuickReply(q)">×</button>
        </div>
        <div class="flex gap-2 border-t border-ink-50 pt-2">
          <input v-model="newQRTitle" class="input w-24" placeholder="标题" />
          <input v-model="newQRContent" class="input flex-1" placeholder="快捷回复内容" @keyup.enter="addQuickReply" />
          <button class="btn-primary" @click="addQuickReply">添加</button>
        </div>
      </div>
    </Modal>

    <!-- 关键词提醒 -->
    <Modal :show="showKeyword" title="关键词提醒" @close="showKeyword = false">
      <div class="space-y-3">
        <p class="text-[12px] text-ink-500">消息内容命中以下任一关键词时，将推送通知提醒（逗号分隔）。</p>
        <input v-model="keywordInput" class="input" placeholder="如：紧急, 上线, @我" />
        <div class="flex justify-end"><button class="btn-primary" @click="saveKeywords">保存</button></div>
      </div>
    </Modal>

    <!-- 消息搜索 -->
    <Modal :show="showSearch" title="搜索消息" @close="showSearch = false">
      <div class="space-y-2">
        <input v-model="searchForm.q" class="input" placeholder="关键字" />
        <div class="flex gap-2">
          <input v-model="searchForm.sender" class="input w-28" placeholder="发送者ID" />
          <input v-model="searchForm.date_from" type="date" class="input" />
          <input v-model="searchForm.date_to" type="date" class="input" />
          <button class="btn-primary" @click="doSearch">搜索</button>
        </div>
        <div class="max-h-60 space-y-1 overflow-y-auto">
          <div v-for="m in searchResults" :key="m.id" class="rounded-control bg-ink-50 px-2 py-1.5 text-[12px]">
            <span class="text-ink-500">{{ m.sender_name }}:</span> {{ m.content }}
          </div>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { imApi, authApi } from '../../api'
import { useUserStore } from '../../stores/user'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import Modal from '../../components/Modal.vue'

const user = useUserStore()
const app = useAppStore()
const myId = user.profile?.id
const sessions = ref([])
const activeSession = ref(null)
const messages = ref([])
const pinned = ref([])
const draft = ref('')
const keyword = ref('')
const typing = ref('')
const showNew = ref(false)
const newGroupName = ref('')
const candidates = ref([])
const candidateQuery = ref('')
const picked = ref(new Set())
const forwarding = ref(null)
const forwardTargets = ref(new Set())
const showGroup = ref(false)
const groupAnn = ref('')
const groupAddQ = ref('')
const addCandidates = ref([])
const msgBox = ref(null)
const showArchived = ref(false)
const replying = ref(null)
const showEmoji = ref(false)
const showQuickReply = ref(false)
const quickReplies = ref([])
const newQRTitle = ref('')
const newQRContent = ref('')
const showKeyword = ref(false)
const keywordInput = ref('')
const showSearch = ref(false)
const searchForm = ref({ q: '', sender: '', date_from: '', date_to: '' })
const searchResults = ref([])
const memberSearchQ = ref('')
const emojiList = ['😀','😂','❤️','👍','🙏','🎉','🔥','✨','💡','✅','❌','⚠️','🚀','😅','🤝','👋','🙌','💪','😴','🥳']
let unsub = null
let draftTimer = null
let typingTimer = null

function otherMember(s) { return (s.members_info || []).find((m) => m.id !== myId) }
function sessionName(s) {
  if (!s) return ''
  if (s.type === 'group') return s.name || '群聊'
  return otherMember(s)?.display_name || '会话'
}
function avatarText(s) { return s.type === 'group' ? '👥' : sessionName(s).slice(0, 1) }
function lastText(s) {
  if (!s.last_message) return '暂无消息'
  return `${s.last_message.sender_name === user.displayName ? '我: ' : ''}${s.last_message.content}`
}
function canRecall(m) { return (Date.now() - new Date(m.created_at).getTime()) / 1000 < 120 }

const filteredMembers = computed(() => {
  const arr = activeSession.value?.members_info || []
  if (!memberSearchQ.value) return arr
  return arr.filter((m) => m.display_name.includes(memberSearchQ.value))
})

// 安全渲染：仅把 ``` 代码块渲染为样式化 <pre>，其余文本转义后按行展示（防 XSS）
function esc(t) { return (t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
function renderContent(m) {
  if (m.is_recalled) return ''
  const parts = (m.content || '').split(/```/)
  let html = ''
  parts.forEach((seg, i) => {
    if (i % 2 === 1) {
      const firstNl = seg.indexOf('\n')
      const lang = firstNl > -1 ? seg.slice(0, firstNl).trim() : ''
      const code = firstNl > -1 ? seg.slice(firstNl + 1) : seg
      html += `<pre style="background:#0f172a;color:#e2e8f0;padding:8px;border-radius:6px;overflow-x:auto;font-size:12px;margin:4px 0;"><span style="color:#64748b">${esc(lang)}</span>\n${esc(code)}</pre>`
    } else {
      html += esc(seg).replace(/\n/g, '<br>')
    }
  })
  return html
}

async function loadSessions() {
  try {
    const r = await imApi.sessions({ search: keyword.value || undefined, archived: showArchived.value ? '1' : undefined })
    sessions.value = r.list || []
  } catch (e) { app.toastMsg(e?.message || '加载会话列表失败', 'error') }
}
async function openSession(s) {
  try {
    activeSession.value = s
    draft.value = s.draft || ''
    groupAnn.value = s.announcement || ''
    replying.value = null
    const r = await imApi.messages(s.id, { page_size: 30 })
    // F5：r.list 是接口响应里的新数组，无其他引用，直接 reverse 即可，
    // 原来的 .slice().reverse() 多一次无用拷贝
    messages.value = (r.list || []).reverse()
    pinned.value = r.pinned || []
    await imApi.setting(s.id, { mark_read: true })
    s.unread = 0
    nextTick(scrollBottom)
  } catch (e) { app.toastMsg(e?.message || '打开会话失败', 'error') }
}
async function send() {
  try {
    const content = draft.value.trim()
    if (!content || !activeSession.value) return
    const payload = { content }
    if (replying.value) payload.reply_to = replying.value.id
    const m = await imApi.send(activeSession.value.id, payload)
    messages.value.push(m)
    draft.value = ''
    replying.value = null
    showEmoji.value = false
    await imApi.setting(activeSession.value.id, { draft: '' })
    nextTick(scrollBottom)
  } catch (e) { app.toastMsg(e?.message || '发送失败', 'error') }
}
function replyMsg(m) { replying.value = m }
function pickEmoji(e) { draft.value += e; showEmoji.value = false }
function saveDraft() {
  if (!activeSession.value) return
  clearTimeout(draftTimer)
  draftTimer = setTimeout(() => imApi.setting(activeSession.value.id, { draft: draft.value }), 500)
}
async function togglePin() {
  try {
    await imApi.setting(activeSession.value.id, { is_pinned: !activeSession.value.is_pinned })
    activeSession.value.is_pinned = !activeSession.value.is_pinned
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '置顶操作失败', 'error') }
}
async function toggleMute() {
  try {
    await imApi.setting(activeSession.value.id, { is_muted: !activeSession.value.is_muted })
    activeSession.value.is_muted = !activeSession.value.is_muted
  } catch (e) { app.toastMsg(e?.message || '免打扰操作失败', 'error') }
}
async function toggleArchiveSession() {
  try {
    const v = !activeSession.value.is_archived
    await imApi.setting(activeSession.value.id, { is_archived: v })
    app.toastMsg(v ? '已归档' : '已取消归档', 'success')
    activeSession.value = null
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '归档操作失败', 'error') }
}
async function leave() {
  try {
    if (!confirm('确定退出该会话？群聊将解散或退出')) return
    await imApi.leaveSession(activeSession.value.id)
    activeSession.value = null
    loadSessions()
  } catch (e) { app.toastMsg(e?.message || '退出会话失败', 'error') }
}
function recall(m) {
  imApi.recall(m.id).then(() => (m.is_recalled = true)).catch(() => app.toastMsg('撤回失败', 'error'))
}
async function deleteForMe(m) {
  try {
    await imApi.deleteMsg(m.id)
    messages.value = messages.value.filter((x) => x.id !== m.id)
  } catch (e) { app.toastMsg(e?.message || '删除消息失败', 'error') }
}
async function togglePinMsg(m) {
  try {
    await imApi.pinMsg(m.id)
    m.is_pinned = !m.is_pinned
    if (m.is_pinned) pinned.value.unshift(m)
    else pinned.value = pinned.value.filter((p) => p.id !== m.id)
  } catch (e) { app.toastMsg(e?.message || '置顶操作失败', 'error') }
}
function unpin(m) {
  imApi.pinMsg(m.id).then(() => { pinned.value = pinned.value.filter((p) => p.id !== m.id) }).catch(() => app.toastMsg('取消置顶失败', 'error'))
}
function forwardMsg(m) { forwarding.value = m; forwardTargets.value = new Set() }
function toggleForward(id) {
  const s = new Set(forwardTargets.value)
  s.has(id) ? s.delete(id) : s.add(id)
  forwardTargets.value = s
}
async function confirmForward() {
  try {
    if (!forwardTargets.value.size) return
    await imApi.forward(forwarding.value.id, [...forwardTargets.value])
    app.toastMsg('已转发', 'success')
    forwarding.value = null
  } catch (e) { app.toastMsg(e?.message || '转发失败', 'error') }
}
function openNew() { showNew.value = true; picked.value = new Set(); newGroupName.value = '' }
let candTimer = null
function loadCandidates() {
  clearTimeout(candTimer)
  candTimer = setTimeout(async () => {
    try {
      candidates.value = (await authApi.directory(candidateQuery.value)).list || []
    } catch (e) { app.toastMsg(e?.message || '搜索失败', 'error') }
  }, 250)
}
function togglePick(id) {
  const s = new Set(picked.value)
  s.has(id) ? s.delete(id) : s.add(id)
  picked.value = s
}
async function startSession() {
  try {
    if (!picked.value.size) return app.toastMsg('请选择成员', 'error')
    const payload = { member_ids: [...picked.value] }
    payload.type = newGroupName.value.trim() || picked.value.size > 1 ? 'group' : 'direct'
    if (newGroupName.value.trim()) payload.name = newGroupName.value.trim()
    const s = await imApi.createSession(payload)
    showNew.value = false
    await loadSessions()
    const found = sessions.value.find((x) => x.id === s.id) || s
    openSession(found)
  } catch (e) { app.toastMsg(e?.message || '创建会话失败', 'error') }
}
let addTimer = null
function searchAdd() {
  clearTimeout(addTimer)
  addTimer = setTimeout(async () => {
    try {
      addCandidates.value = (await authApi.directory(groupAddQ.value)).list || []
    } catch (e) { app.toastMsg(e?.message || '搜索失败', 'error') }
  }, 250)
}
async function addMember(uid) {
  try {
    await imApi.addMembers(activeSession.value.id, [uid])
    app.toastMsg('已添加', 'success')
    const fresh = await imApi.sessionDetail(activeSession.value.id)
    activeSession.value = fresh
  } catch (e) { app.toastMsg(e?.message || '添加成员失败', 'error') }
}
async function kick(uid) {
  try {
    await imApi.removeMember(activeSession.value.id, uid)
    const fresh = await imApi.sessionDetail(activeSession.value.id)
    activeSession.value = fresh
  } catch (e) { app.toastMsg(e?.message || '移出成员失败', 'error') }
}
async function updateGroup(field, val) {
  try {
    await imApi.updateSession(activeSession.value.id, { [field]: val })
    app.toastMsg('已更新', 'success')
  } catch (e) { app.toastMsg(e?.message || '更新群信息失败', 'error') }
}
// 导出聊天记录为 JSON
async function exportChat() {
  try {
    const r = await imApi.messages(activeSession.value.id, {})
    const data = { session: sessionName(activeSession.value), exported_at: new Date().toISOString(), messages: r.list }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `chat-${activeSession.value.id}-${Date.now()}.json`
    a.click()
    app.toastMsg('已导出 JSON', 'success')
  } catch (e) { app.toastMsg(e?.message || '导出聊天记录失败', 'error') }
}
async function openQuickReplies() {
  try {
    quickReplies.value = (await imApi.quickReplies()).list || []
    showQuickReply.value = true
  } catch (e) { app.toastMsg(e?.message || '加载快捷回复失败', 'error') }
}
function useQuickReply(q) {
  draft.value = q.content
  showQuickReply.value = false
}
async function addQuickReply() {
  try {
    if (!newQRContent.value.trim()) return
    await imApi.createQuickReply({ title: newQRTitle.value, content: newQRContent.value })
    newQRTitle.value = ''; newQRContent.value = ''
    openQuickReplies()
  } catch (e) { app.toastMsg(e?.message || '添加快捷回复失败', 'error') }
}
async function delQuickReply(q) {
  try {
    await imApi.deleteQuickReply(q.id)
    openQuickReplies()
  } catch (e) { app.toastMsg(e?.message || '删除快捷回复失败', 'error') }
}
async function openKeyword() {
  try {
    const r = await imApi.keywordAlert()
    keywordInput.value = (r.keywords || []).join(', ')
    showKeyword.value = true
  } catch (e) { app.toastMsg(e?.message || '加载关键词失败', 'error') }
}
async function saveKeywords() {
  try {
    const kws = keywordInput.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
    await imApi.saveKeywordAlert(kws)
    app.toastMsg('关键词已保存', 'success')
    showKeyword.value = false
  } catch (e) { app.toastMsg(e?.message || '保存关键词失败', 'error') }
}
async function openSearch() {
  searchResults.value = []
  showSearch.value = true
}
async function doSearch() {
  try {
    searchResults.value = (await imApi.searchMessages(searchForm.value)).list || []
  } catch (e) { app.toastMsg(e?.message || '搜索失败', 'error') }
}
function scrollBottom() { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight }

onMounted(() => {
  loadSessions()
  unsub = app.onChat((type, data) => {
    if (type === 'chat.message' && activeSession.value && data?.session === activeSession.value.id) {
      if (!messages.value.some((m) => m.id === data.id)) messages.value.push(data)
      imApi.setting(activeSession.value.id, { mark_read: true })
      nextTick(scrollBottom)
    } else if (type === 'chat.message') {
      loadSessions()
    } else if (type === 'message.recalled') {
      const m = messages.value.find((x) => x.id === data?.message_id)
      if (m) m.is_recalled = true
    } else if (type === 'session.updated') {
      loadSessions()
    } else if (type === 'chat.typing' && activeSession.value && data.session_id === activeSession.value.id) {
      typing.value = data.user
      clearTimeout(typingTimer)
      typingTimer = setTimeout(() => (typing.value = ''), 2000)
    }
  })
})
onBeforeUnmount(() => unsub && unsub())
</script>
