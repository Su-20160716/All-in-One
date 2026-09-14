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

    <div class="card overflow-hidden">
      <table class="w-full">
        <thead class="bg-ink-50">
          <tr><th class="th">任务</th><th class="th">所属项目</th><th class="th">优先级</th><th class="th">截止</th><th class="th">子任务</th><th class="th">工时</th><th class="th"></th></tr>
        </thead>
        <tbody>
          <tr v-for="c in list" :key="c.id" class="border-t border-ink-50">
            <td class="td">
              <span v-if="c.is_overdue" class="mr-1 text-rose-500">⏰</span>{{ c.title }}
            </td>
            <td class="td"><RouterLink :to="`/projects/${c.project_id}/board`" class="text-brand-600">{{ c.project_name }}</RouterLink></td>
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
      <div v-if="!list.length" class="grid h-32 place-items-center text-[13px] text-ink-400">当前没有任务</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
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

async function load() {
  const r = await projectApi.myTasks({ status: status.value, priority: priority.value })
  list.value = r.list
  r.counts.forEach((c) => (count[c.status] = c.total))
}
function changeStatus(v) {
  status.value = v
  load()
}
async function move(c, value) {
  await projectApi.updateCard(c.id, { status: value })
  app.toastMsg('已更新', 'success')
  load()
}
onMounted(load)
</script>
