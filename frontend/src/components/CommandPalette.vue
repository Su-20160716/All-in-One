<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[100]" @click.self="close">
      <div class="absolute inset-0 bg-black/40" @click="close"></div>
      <div class="relative mx-auto mt-[12vh] w-[90%] max-w-xl rounded-xl bg-white shadow-2xl dark:bg-slate-800">
        <div class="flex items-center border-b border-gray-200 px-4 dark:border-slate-700">
          <span class="text-gray-400">⌘</span>
          <input
            ref="inputEl"
            v-model="query"
            class="w-full bg-transparent px-3 py-3 text-sm outline-none dark:text-slate-100"
            placeholder="输入命令或搜索页面…"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="run(picked)"
            @keydown.esc="close"
          />
          <kbd class="text-xs text-gray-400">ESC</kbd>
        </div>
        <div class="max-h-80 overflow-y-auto py-2">
          <button
            v-for="(item, i) in filtered"
            :key="item.key"
            @click="run(item)"
            @mouseenter="pickedIdx = i"
            class="flex w-full items-center gap-3 px-4 py-2 text-left text-sm"
            :class="i === pickedIdx ? 'bg-indigo-50 dark:bg-slate-700' : ''"
          >
            <span class="text-base">{{ item.icon }}</span>
            <span class="flex-1 dark:text-slate-200">{{ item.label }}</span>
            <span class="text-xs text-gray-400">{{ item.hint }}</span>
          </button>          <div v-if="!filtered.length" class="px-4 py-6 text-center text-sm text-gray-400">
            无匹配命令
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { noteApi, suiteApi } from '../api'
import { useAppStore } from '../stores/app'
import { useUserStore } from '../stores/user'
import { applyTheme, getAccent } from '../utils/theme'

const router = useRouter()
const app = useAppStore()
const user = useUserStore()
const open = ref(false)
const query = ref('')
const pickedIdx = ref(0)
const inputEl = ref(null)
const busy = ref(false)

// F57：除跳转外，面板直接执行动作（走既有 API，不新增后端接口）
const COMMANDS = [
  {
    key: 'new-note', icon: '✨', label: '新建笔记', hint: '立即创建',
    action: async () => {
      const n = await noteApi.create({})
      app.toastMsg(`已新建《${n?.title || '未命名笔记'}》`, 'success')
      router.push('/notes')
    },
  },
  {
    key: 'new-todo', icon: '✅', label: '新建待办', hint: '办公套件',
    action: async () => {
      const r = await suiteApi.call('officesuite', 'todo/create/', 'POST', { title: '新待办（命令面板）' })
      app.toastMsg(`已新建待办：${r?.data?.title || '新待办'}`, 'success')
    },
  },
  {
    key: 'read-all', icon: '📭', label: '全部通知标为已读', hint: '通知中心',
    action: async () => {
      await app.markAllRead()
      app.toastMsg('已全部标记为已读', 'success')
    },
  },
  {
    key: 'theme-light', icon: '☀️', label: '主题：浅色', hint: '外观',
    action: async () => { applyTheme('light', getAccent()); app.toastMsg('已切换为浅色主题', 'success') },
  },
  {
    key: 'theme-dark', icon: '🌙', label: '主题：深色', hint: '外观',
    action: async () => { applyTheme('dark', getAccent()); app.toastMsg('已切换为深色主题', 'success') },
  },
  {
    key: 'theme-system', icon: '🖥️', label: '主题：跟随系统', hint: '外观',
    action: async () => { applyTheme('system', getAccent()); app.toastMsg('已跟随系统主题', 'success') },
  },
  { key: 'search', icon: '🔍', label: '全局搜索', hint: '/search', action: () => router.push('/search') },
  { key: 'ai', icon: '🤖', label: '打开 AI 助手', hint: '/ai', action: () => router.push('/ai') },
  { key: 'notes', icon: '📝', label: '笔记知识库', hint: '/notes', action: () => router.push('/notes') },
  { key: 'upload', icon: '📤', label: '上传文件', hint: '/files', action: () => router.push('/files') },
  { key: 'files', icon: '📁', label: '文件管理', hint: '/files', action: () => router.push('/files') },
  { key: 'code', icon: '💻', label: '代码工坊', hint: '/code', action: () => router.push('/code') },
  { key: 'learning', icon: '📚', label: '学习中心', hint: '/learning', action: () => router.push('/learning') },
  { key: 'im', icon: '💬', label: '站内消息', hint: '/im', action: () => router.push('/im') },
  { key: 'projects', icon: '📊', label: '项目看板', hint: '/projects', action: () => router.push('/projects') },
  { key: 'office', icon: '🏢', label: '办公套件', hint: '/toolbox/office', action: () => router.push('/toolbox/office') },
  { key: 'dashboard', icon: '🏠', label: '工作台', hint: '/dashboard', action: () => router.push('/dashboard') },
  { key: 'profile', icon: '👤', label: '个人设置', hint: '/profile', action: () => router.push('/profile') },
  { key: 'reload', icon: '🔄', label: '刷新页面', hint: '重载', action: () => window.location.reload() },
  {
    key: 'logout', icon: '🚪', label: '退出登录', hint: '注销',
    action: async () => {
      if (!window.confirm('确定退出登录？')) return
      await user.logout()
      router.push('/login')
    },
  },
]

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return COMMANDS
  return COMMANDS.filter(c => c.label.toLowerCase().includes(q) || c.hint.toLowerCase().includes(q))
})
// 搜索词变化后高亮复位，避免旧 pickedIdx 越界导致无高亮
watch(query, () => { pickedIdx.value = 0 })

function move(d) {
  // F24：空结果时 (x + d + 0) % 0 = NaN，会让 pickedIdx 变 NaN，必须挡掉
  const n = filtered.value.length
  if (!n) return
  pickedIdx.value = (pickedIdx.value + d + n) % n
}
async function run(item) {
  if (!item || busy.value) return
  close()
  busy.value = true
  try {
    await item.action()
  } catch (e) {
    // 拦截器已把后端错误码映射成中文，直接展示 e.message
    app.toastMsg(e?.message || '执行失败', 'error')
  } finally {
    busy.value = false
  }
}
function close() {
  open.value = false
  query.value = ''
}
function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    open.value = true
    pickedIdx.value = 0
    nextTick(() => inputEl.value?.focus())
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>
