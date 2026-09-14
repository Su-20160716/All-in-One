<template>
  <div class="mx-auto max-w-6xl space-y-3">
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <input v-model="filters.username" class="input w-36" placeholder="操作用户" @keyup.enter="load" />
      <select v-model="filters.module" class="input w-28" @change="load">
        <option value="">全部模块</option>
        <option v-for="m in modules" :key="m" :value="m">{{ m }}</option>
      </select>
      <select v-model="filters.action" class="input w-28" @change="load">
        <option value="">全部动作</option>
        <option v-for="a in actions" :key="a" :value="a">{{ a }}</option>
      </select>
      <input v-model="filters.start" type="date" class="input w-36" @change="load" />
      <span class="text-ink-300">~</span>
      <input v-model="filters.end" type="date" class="input w-36" @change="load" />
      <input v-model="filters.ip" class="input w-32" placeholder="IP" @keyup.enter="load" />
      <button class="btn-primary" @click="load">查询</button>
      <button class="btn-outline" @click="reset">重置</button>
      <a class="btn-outline ml-auto" :href="exportUrl">⬇ 导出 CSV</a>
    </div>

    <div class="grid grid-cols-4 gap-3" v-if="logStats.total != null">
      <div class="card p-3"><div class="text-[11px] text-ink-400">日志总量</div><div class="text-[18px] font-bold">{{ logStats.total }}</div></div>
      <div class="card p-3" v-for="(m, i) in topModules" :key="i">
        <div class="text-[11px] text-ink-400">{{ m.module }}</div><div class="text-[18px] font-bold">{{ m.c }}</div>
      </div>
    </div>

    <div class="card overflow-x-auto">
      <table class="w-full min-w-[820px]">
        <thead class="border-b border-ink-100 bg-ink-50/50">
          <tr><th class="th">时间</th><th class="th">用户</th><th class="th">模块</th><th class="th">动作</th><th class="th">目标</th><th class="th">详情</th><th class="th">IP</th></tr>
        </thead>
        <tbody class="divide-y divide-ink-50">
          <tr v-for="l in logs" :key="l.id" class="hover:bg-ink-50/40">
            <td class="td whitespace-nowrap text-ink-500">{{ formatTime(l.created_at) }}</td>
            <td class="td">{{ l.username || '系统' }}</td>
            <td class="td"><span class="tag">{{ l.module }}</span></td>
            <td class="td"><span class="tag" :class="actionClass(l.action)">{{ l.action }}</span></td>
            <td class="td max-w-[220px] truncate text-ink-600">{{ l.target }}</td>
            <td class="td max-w-[220px] truncate font-mono text-[11px] text-ink-400">{{ l.detail }}</td>
            <td class="td font-mono text-[11px] text-ink-400">{{ l.ip || '-' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!logs.length" class="py-14 text-center text-[13px] text-ink-400">暂无日志</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { coreApi } from '../../api'
import { formatTime } from '../../utils/format'

const logs = ref([])
const filters = reactive({ username: '', module: '', action: '', ip: '', start: '', end: '' })
const logStats = ref({})
const modules = ['accounts', 'files', 'notes', 'projects', 'im', 'tools', 'dashboard', 'core']
const actions = ['create', 'update', 'delete', 'read', 'login', 'logout', 'upload', 'download', 'share', 'move', 'restore', 'other']
const topModules = computed(() => (logStats.value.by_module || []).slice(0, 3))
const exportUrl = computed(() => {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => v && p.set(k, v))
  return `/api/core/logs/export/?${p.toString()}`
})
function actionClass(a) {
  return { create: 'bg-emerald-50 text-emerald-600', delete: 'bg-rose-50 text-rose-600', update: 'bg-sky-50 text-sky-600' }[a] || ''
}
async function load() {
  const params = {}
  Object.entries(filters).forEach(([k, v]) => v && (params[k] = v))
  logs.value = (await coreApi.logs({ ...params, page_size: 100 })).list || []
}
function reset() {
  Object.keys(filters).forEach((k) => (filters[k] = ''))
  load()
}
onMounted(() => {
  load()
  coreApi.logStats().then((r) => (logStats.value = r)).catch(() => {})
})
</script>
