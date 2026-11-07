<template>
  <div class="mx-auto max-w-6xl space-y-3">
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <input v-model="filters.username" class="input w-36" placeholder="操作用户" @keyup.enter="reload" />
      <select v-model="filters.module" class="input w-28" @change="reload">
        <option value="">全部模块</option>
        <option v-for="m in modules" :key="m" :value="m">{{ m }}</option>
      </select>
      <select v-model="filters.action" class="input w-28" @change="reload">
        <option value="">全部动作</option>
        <option v-for="a in actions" :key="a" :value="a">{{ a }}</option>
      </select>
      <!-- #69 对象类型筛选 -->
      <input v-model="filters.target" class="input w-36" placeholder="操作对象关键词" @keyup.enter="reload" />
      <!-- #69 结果筛选 -->
      <select v-model="filters.result" class="input w-28" @change="reload">
        <option value="">全部结果</option>
        <option value="fail">仅失败</option>
      </select>
      <input v-model="filters.start" type="date" class="input w-36" @change="reload" />
      <span class="text-ink-300">~</span>
      <input v-model="filters.end" type="date" class="input w-36" @change="reload" />
      <input v-model="filters.ip" class="input w-32" placeholder="IP" @keyup.enter="reload" />
      <button class="btn-primary" @click="reload">查询</button>
      <button class="btn-outline" @click="reset">重置</button>
      <button class="btn-outline ml-auto" @click="exportCsv">⬇ 导出 CSV</button>
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

    <!-- #179 分页：更早的日志可通过上一页/下一页翻到，筛选条件保持不变 -->
    <div class="flex items-center justify-between px-1 text-[12px] text-ink-500">
      <span>
        第 {{ page }} 页 · 本页 {{ logs.length }} 条<template v-if="total != null"> · 共 {{ total }} 条</template>
      </span>
      <div class="flex items-center gap-2">
        <button class="btn-outline px-2 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
        <button class="btn-outline px-2 text-[12px]" :disabled="!hasNext || loading" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { coreApi } from '../../api'
import { formatTime } from '../../utils/format'
import { describeDownloadError, downloadWithAuth } from '../../utils/download'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const logs = ref([])
const filters = reactive({ username: '', module: '', action: '', ip: '', start: '', end: '', target: '', result: '' })
const logStats = ref({})
// #179 分页状态：后端返回 total，缺失时以「本页是否满页」推断是否还有下一页
const PAGE_SIZE = 100
const page = ref(1)
const total = ref(null)
const hasNext = ref(false)
const loading = ref(false)
const modules = ['accounts', 'files', 'notes', 'projects', 'im', 'tools', 'dashboard', 'core']
const actions = ['create', 'update', 'delete', 'read', 'login', 'logout', 'upload', 'download', 'share', 'move', 'restore', 'other']
const topModules = computed(() => (logStats.value.by_module || []).slice(0, 3))
// F2：导出接口要 JWT，裸 href 会 401，改走带鉴权下载
async function exportCsv() {
  const p = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => v && p.set(k, v))
  try {
    await downloadWithAuth(`/core/logs/export/?${p.toString()}`, '操作日志.csv')
  } catch (e) {
    app.toastMsg(await describeDownloadError(e), 'error')
  }
}
function actionClass(a) {
  return { create: 'bg-emerald-50 text-emerald-600', delete: 'bg-rose-50 text-rose-600', update: 'bg-sky-50 text-sky-600' }[a] || ''
}
async function load() {
  const params = {}
  Object.entries(filters).forEach(([k, v]) => v && (params[k] = v))
  loading.value = true
  try {
    const r = await coreApi.logs({ ...params, page: page.value, page_size: PAGE_SIZE })
    logs.value = r.list || []
    total.value = r.total ?? null
    hasNext.value = total.value != null
      ? page.value * PAGE_SIZE < total.value
      : logs.value.length >= PAGE_SIZE
  } finally {
    loading.value = false
  }
}
function reload() {
  page.value = 1
  load()
}
function goPage(p) {
  if (p < 1 || p === page.value) return
  page.value = p
  load()
}
function reset() {
  Object.keys(filters).forEach((k) => (filters[k] = ''))
  reload()
}
onMounted(() => {
  load()
  coreApi.logStats().then((r) => (logStats.value = r)).catch(() => {})
})
</script>
