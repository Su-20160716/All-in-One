<template>
  <aside class="flex w-56 shrink-0 flex-col bg-ink-900 text-ink-300">
    <div class="flex items-center gap-2 px-4 py-4">
      <div class="grid h-8 w-8 place-items-center rounded-control bg-brand-600 text-[15px] font-bold text-white">A</div>
      <div>
        <div class="text-[14px] font-semibold text-white">全能协作平台</div>
        <div class="text-[11px] text-ink-500">All-in-One v5.0</div>
      </div>
    </div>
    <nav class="flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
      <RouterLink v-for="item in menus" :key="item.to" :to="item.to" class="menu-item" :class="{ active: isActive(item.to) }">
        <span class="text-[15px] leading-none">{{ item.icon }}</span>
        <span class="flex-1">{{ item.label }}</span>
        <span v-if="item.badge" class="grid h-4 min-w-4 place-items-center rounded-pill bg-rose-500 px-1 text-[10px] font-medium text-white">
          {{ item.badge }}
        </span>
      </RouterLink>
    </nav>
    <div class="border-t border-white/5 p-3 text-[11px] text-ink-500">
      <div class="flex items-center gap-1.5">
        <span class="h-1.5 w-1.5 rounded-full" :class="app.wsConnected ? 'bg-emerald-400' : 'bg-ink-600'"></span>
        {{ app.wsConnected ? '实时通道已连接' : '实时通道重连中…' }}
      </div>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '../stores/app'
import { imApi } from '../api'

const route = useRoute()
const app = useAppStore()
const imUnread = ref(0)

const menus = computed(() => [
  { to: '/dashboard', label: '工作台', icon: '▦' },
  { to: '/search', label: '全文搜索', icon: '🔍' },
  { to: '/ai', label: 'AI 助手', icon: '🤖' },
  { to: '/files', label: '文件管理', icon: '🗂' },
  { to: '/notes', label: '笔记知识库', icon: '📝' },
  { to: '/projects', label: '项目看板', icon: '📋' },
  { to: '/projects/my-tasks', label: '我的任务', icon: '✅' },
  { to: '/im', label: '站内消息', icon: '💬', badge: imUnread.value || '' },
  { to: '/announcements', label: '系统公告', icon: '📣' },
  { to: '/tools', label: '小工具', icon: '🧰' },
  { to: '/toolbox/devtools', label: '开发工具箱', icon: '🛠' },
  { to: '/toolbox/minitools', label: '迷你工具箱', icon: '🎁' },
  { to: '/toolbox/dataintel', label: '数据智能中心', icon: '📈' },
  { to: '/toolbox/office', label: '办公套件', icon: '🏢' },
  { to: '/office/helpdesk', label: '工单台', icon: '🎫' },
  { to: '/office/duty', label: '值班排班', icon: '🗓' },
  { to: '/learning', label: '学习中心', icon: '🎓' },
  { to: '/learning/programming', label: '编程语言广场', icon: '💻' },
  { to: '/learning/drill', label: '编程刷题训练', icon: '🧩' },
  { to: '/learning/school', label: '学科知识中心', icon: '📚' },
  { to: '/learning/chinese', label: '语文园地', icon: '🀄' },
  { to: '/learning/english', label: '英语角', icon: '🔤' },
  { to: '/learning/questions', label: '题库与组卷', icon: '📝' },
  { to: '/learning/tools', label: '学习工具箱', icon: '🧮' },
  { to: '/learning/study', label: '我的学习', icon: '⏱' },
  { to: '/code', label: '代码工坊', icon: '🧑‍💻' },
  { to: '/code/learn', label: '代码学习中心', icon: '🏅' },
  { to: '/admin/stats', label: '统计面板', icon: '📊' },
  { to: '/admin/users', label: '用户管理', icon: '👥' },
  { to: '/admin/roles', label: '角色权限', icon: '🔐' },
  { to: '/admin/org', label: '组织架构', icon: '🏢' },
  { to: '/admin/logs', label: '操作日志', icon: '🧾' },
  { to: '/profile', label: '个人设置', icon: '⚙️' },
])

function isActive(to) {
  if (to === '/admin/stats') return route.path.startsWith('/admin')
  if (to === '/projects') return route.path.startsWith('/projects') && !route.path.includes('my-tasks')
  return route.path.startsWith(to)
}

async function loadImUnread() {
  try {
    const r = await imApi.unreadTotal()
    imUnread.value = r.unread ?? 0
  } catch (e) { /* ignore */ }
}

onMounted(loadImUnread)
</script>
