<template>
  <div class="flex h-[calc(100vh-110px)] gap-4">
    <!-- 会话列表 -->
    <div class="card flex w-72 shrink-0 flex-col">
      <div class="flex items-center gap-2 border-b border-ink-100 p-3">
        <input v-model="keyword" class="input flex-1" placeholder="搜索会话…" @keyup.enter="loadSessions" />
        <button class="btn-primary px-2.5" title="发起聊天" @click="openNew">＋</button>
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
        <div v-if="!sessions.length" class="py-10 text-center text-[12px] text-ink-400">暂无会话</div>
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
            <button class="btn-ghost px-2 text-[12px]" :class="activeSession.is_pinned ? 'text-brand-600' : ''" @click="togglePin">{{ activeSession.is_pinned ? '取消置顶' : '置顶' }}</button>
            <button class="btn-ghost px-2 text-[12px]" :class="activeSession.is_muted ? 'text-amber-600' : ''" @click="toggleMute">{{ activeSession.is_muted ? '取消免打扰' : '免打扰' }}</button>
            <button v-if="activeSession.type === 'group'" class="btn-ghost px-2 text-[12px]" @click="showGroup = true">群管理</button>
            <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="leave">退出</button>
          </div>
        </div>
        <div ref="msgBox" class="flex-1 space-y-3 overflow-y-auto bg-ink-50/40 p-4">
          <div v-for="m in messages" :key="m.id" class="group flex" :class="m.sender === myId ? 'justify-end' : 'justify-start'">
            <div class="max-w-[70%]">
              <div v-if="m.sender !== myId" class="mb-0.5 text-[11px] text-ink-400">{{ m.sender_name }}</div>
              <div class="relative rounded-card px-3 py-2 text-[13px] leading-relaxed" :class="m.sender === myId ? 'bg-brand-600 text-white' : 'bg-white text-ink-800 shadow-card'">
                <span v-if="m.is_recalled" class="italic opacity-70">消息已撤回</span>
                <template v-else>{{ m.content }}<span v-if="m.forward_from" class="ml-1 text-[10px] opacity-70">（转发）</span></template>
                <div v-if="!m.is_recalled" class="absolute -top-2 right-2 hidden gap-1 rounded-pill bg-white px-1 text-[10px] shadow-card group-hover:flex" :class="m.sender === myId ? 'text-ink-600' : ''">
                  <button @click="forwardMsg(m)">转发</button>
                  <button v-if="m.sender === myId && canRecall(m)" @click="recall(m)">撤回</button>
                  <button @click="deleteForMe(m)">删除</button>
                </div>
              </div>
              <div class="mt-0.5 text-right text-[10px] text-ink-300">{{ formatTime(m.created_at) }}</div>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-2 border-t border-ink-100 p-3">
          <input v-model="draft" class="input flex-1" placeholder="输入消息，回车发送…" @input="saveDraft" @keyup.enter="send" />
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
        <div class="divide-y divide-ink-50">
          <div v-for="m in activeSession?.members_info || []" :key="m.id" class="flex items-center justify-between py-2 text-[13px]">
            <span>{{ m.display_name }} <span v-if="m.id === activeSession.owner" class="tag-brand">群主</span></span>
            <button v-if="m.id !== myId" class="btn-ghost px-2 text-[12px] text-rose-500" @click="kick(m.id)">移除</button>
          </div>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
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
let unsub = null
let draftTimer = null
let typingTimer = null

function otherMember(s) {
  return (s.members_info || []).find((m) => m.id !== myId)
}
function sessionName(s) {
  if (!s) return ''
  if (s.type === 'group') return s.name || '群聊'
  return otherMember(s)?.display_name || '会话'
}
function avatarText(s) {
  return s.type === 'group' ? '👥' : sessionName(s).slice(0, 1)
}
function lastText(s) {
  if (!s.last_message) return '暂无消息'
  return `${s.last_message.sender_name === user.displayName ? '我: ' : ''}${s.last_message.content}`
}
function canRecall(m) {
  return (Date.now() - new Date(m.created_at).getTime()) / 1000 < 120
}

async function loadSessions() {
  const r = await imApi.sessions({ search: keyword.value || undefined })
  sessions.value = r.list || []
}
async function openSession(s) {
  activeSession.value = s
  draft.value = s.draft || ''
  groupAnn.value = s.announcement || ''
  const r = await imApi.messages(s.id, { page_size: 30 })
  messages.value = (r.list || []).slice().reverse()
  await imApi.setting(s.id, { mark_read: true })
  s.unread = 0
  nextTick(scrollBottom)
}
async function send() {
  const content = draft.value.trim()
  if (!content || !activeSession.value) return
  const m = await imApi.send(activeSession.value.id, content)
  messages.value.push(m)
  draft.value = ''
  await imApi.setting(activeSession.value.id, { draft: '' })
  nextTick(scrollBottom)
}
function saveDraft() {
  if (!activeSession.value) return
  clearTimeout(draftTimer)
  draftTimer = setTimeout(() => imApi.setting(activeSession.value.id, { draft: draft.value }), 500)
}
async function togglePin() {
  await imApi.setting(activeSession.value.id, { is_pinned: !activeSession.value.is_pinned })
  activeSession.value.is_pinned = !activeSession.value.is_pinned
  loadSessions()
}
async function toggleMute() {
  await imApi.setting(activeSession.value.id, { is_muted: !activeSession.value.is_muted })
  activeSession.value.is_muted = !activeSession.value.is_muted
}
async function leave() {
  if (!confirm('确定退出该会话？群聊将解散或退出')) return
  await imApi.leaveSession(activeSession.value.id)
  activeSession.value = null
  loadSessions()
}
function recall(m) {
  imApi.recall(m.id).then(() => (m.is_recalled = true))
}
async function deleteForMe(m) {
  await imApi.deleteMsg(m.id)
  messages.value = messages.value.filter((x) => x.id !== m.id)
}
function forwardMsg(m) { forwarding.value = m; forwardTargets.value = new Set() }
function toggleForward(id) {
  const s = new Set(forwardTargets.value)
  s.has(id) ? s.delete(id) : s.add(id)
  forwardTargets.value = s
}
async function confirmForward() {
  if (!forwardTargets.value.size) return
  await imApi.forward(forwarding.value.id, [...forwardTargets.value])
  app.toastMsg('已转发', 'success')
  forwarding.value = null
}
function openNew() { showNew.value = true; picked.value = new Set(); newGroupName.value = '' }
let candTimer = null
function loadCandidates() {
  clearTimeout(candTimer)
  candTimer = setTimeout(async () => { candidates.value = (await authApi.directory(candidateQuery.value)).list || [] }, 250)
}
function togglePick(id) {
  const s = new Set(picked.value)
  s.has(id) ? s.delete(id) : s.add(id)
  picked.value = s
}
async function startSession() {
  if (!picked.value.size) return app.toastMsg('请选择成员', 'error')
  const payload = { member_ids: [...picked.value] }
  payload.type = newGroupName.value.trim() || picked.value.size > 1 ? 'group' : 'direct'
  if (newGroupName.value.trim()) payload.name = newGroupName.value.trim()
  const s = await imApi.createSession(payload)
  showNew.value = false
  await loadSessions()
  const found = sessions.value.find((x) => x.id === s.id) || s
  openSession(found)
}
let addTimer = null
function searchAdd() {
  clearTimeout(addTimer)
  addTimer = setTimeout(async () => { addCandidates.value = (await authApi.directory(groupAddQ.value)).list || [] }, 250)
}
async function addMember(uid) {
  await imApi.addMembers(activeSession.value.id, [uid])
  app.toastMsg('已添加', 'success')
  const fresh = await imApi.sessionDetail(activeSession.value.id)
  activeSession.value = fresh
}
async function kick(uid) {
  await imApi.removeMember(activeSession.value.id, uid)
  const fresh = await imApi.sessionDetail(activeSession.value.id)
  activeSession.value = fresh
}
async function updateGroup(field, val) {
  await imApi.updateSession(activeSession.value.id, { [field]: val })
  app.toastMsg('已更新', 'success')
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
