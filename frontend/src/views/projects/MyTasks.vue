<template>
  <div class="mx-auto max-w-5xl space-y-4">
    <div class="flex items-center gap-2">
      <button v-for="t in tabs" :key="t.v" class="rounded-pill px-3 py-1.5 text-[12px]" :class="status === t.v ? 'bg-brand-600 text-white' : 'bg-white text-ink-500'" @click="changeStatus(t.v)">
        {{ t.label }} {{ count[t.v] || 0 }}
      </button>
      <select v-model="priority" class="input ml-auto w-32" @change="load">
        <option value="">全部优先级</option>
        <option value="low">低</option><option value="medium">中</option><option value="high">高</option><option value="urgent">紧急</option>
      </select>
    </div>

    <div v-for="g in grouped" :key="g.project_id" class="card overflow-hidden">
      <div class="flex items-center gap-2 border-b border-ink-50 bg-ink-50/60 px-4 py-2">
        <RouterLink :to="`/projects/${g.project_id}/board`" class="text-[13px] font-semibold text-brand-600">{{ g.project_name }}</RouterLink>
        <span class="text-[11px] text-ink-400">{{ g.cards.length }} 项</span>
      </div>
      <table class="w-full">
        <tbody>
          <tr v-for="c in g.cards" :key="c.id" class="border-t border-ink-50">
            <td class="td">
              <span v-if="c.is_overdue" class="mr-1 text-rose-500">⏰</span>{{ c.title }}
            </td>
            <td class="td"><span class="rounded-pill px-2 py-0.5 text-[11px]" :class="priorityColor(c.priority)">{{ pName(c.priority) }}</span></td>
            <td class="td" :class="c.is_overdue ? 'text-rose-500' : ''">{{ fmt(c.due_date) }}</td>
            <td class="td">{{ c.progress }}%</td>
            <td class="td">{{ c.spent_minutes ? Math.round(c.spent_minutes / 60 * 10) / 10 + 'h' : '-' }}</td>
            <td class="td">
              <select class="input w-24 py-1 text-[12px]" :value="c.status" @change="move(c, $event.target.value)">
                <option value="todo">待办</option><option value="doing">进行中</option><option value="done">已完成</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="!list.length" class="card grid h-32 place-items-center text-[13px] text-ink-400">当前没有任务</div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { projectApi } from '../../api'
import { formatDate, priorityColor } from '../../utils/format'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const list = ref([])
const status = ref('doing')
const priority = ref('')
const count = reactive({ todo: 0, doing: 0, done: 0 })
const tabs = [{ v: 'todo', label: '待办' }, { v: 'doing', label: '进行中' }, { v: 'done', label: '已完成' }]
const fmt = formatDate
const pName = (p) => ({ low: '低', medium: '中', high: '高', urgent: '紧急' }[p] || '-')

// 按项目分组
const grouped = computed(() => {
  const map = new Map()
  for (const c of list.value) {
    const key = c.project_id
    if (!map.has(key)) map.set(key, { project_id: key, project_name: c.project_name || '未分配', cards: [] })
    map.get(key).cards.push(c)
  }
  return [...map.values()]
})

async function load() {
  const r = await projectApi.myTasks({ status: status.value, priority: priority.value })
  list.value = r.list || []
  // counts 为 dict {all, open, overdue, today, week, done}；必须使用后端明确计数，
  // 不能用当前筛选列表长度兜底（切换 tab 后角标会变成另一组数字）
  const c = r.counts || {}
  count.todo = c.todo ?? c.open ?? 0
  count.doing = c.open ?? 0
  count.done = c.done ?? 0
}
function changeStatus(v) { status.value = v; load() }
async function move(c, value) {
  // #158 乐观更新 + 失败回滚：catch 里还原原状态并提示，界面不再与后端不一致
  const prev = c.status
  c.status = value
  try {
    await projectApi.updateCard(c.id, { status: value })
    app.toastMsg('已更新', 'success')
    await load()
  } catch (e) {
    c.status = prev
    app.toastMsg(e?.message || '更新状态失败，已还原', 'error')
  }
}
onMounted(load)
</script>
