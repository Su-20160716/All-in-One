<template>
  <div class="mx-auto max-w-4xl space-y-3">
    <div class="card flex items-center gap-2 p-3">
      <h2 class="text-[15px] font-semibold text-ink-800">回收站</h2>
      <span class="text-[12px] text-ink-400">文件保留 {{ keepDays }} 天，到期自动清理</span>
      <div class="ml-auto flex gap-2">
        <button class="btn-outline" @click="autoClean">立即清理过期</button>
        <button class="btn-danger" @click="empty">清空回收站</button>
      </div>
    </div>

    <!-- F551 回收站统计 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-center gap-4 text-[13px]">
        <span class="text-[12px] font-semibold text-ink-600">回收站统计</span>
        <span>文件 <b class="text-ink-800">{{ stats.count ?? list.length }}</b> 个</span>
        <span>占用 <b class="text-rose-500">{{ stats.text || '0 B' }}</b></span>
        <span v-if="stats.oldest_at">最早删除 {{ formatTime(stats.oldest_at) }}</span>
        <span v-if="stats.keep_days">保留 {{ stats.keep_days }} 天</span>
        <button class="btn-danger ml-auto px-2 py-1 text-[12px]" @click="empty">🗑 一键清空（{{ stats.count ?? list.length }} 个）</button>
      </div>
      <div v-if="(stats.by_kind || []).length" class="mt-2 flex flex-wrap gap-3 text-[11px] text-ink-500">
        <span v-for="k in stats.by_kind" :key="k.kind">{{ kindName(k.kind) }} {{ k.count }} 个 · {{ k.text }}</span>
      </div>
      <div v-else class="mt-1 text-[11px] text-ink-400">回收站里没有文件，统计为空</div>
    </div>

    <!-- S24-232 回收站筛选工具条 -->
    <div class="card flex flex-wrap items-center gap-2 p-3 text-[12px]">
      <input v-model="q" class="input w-44" placeholder="文件名 / 备注关键词" @keyup.enter="load" />
      <select v-model="kindFilter" class="input w-24" @change="load">
        <option value="">全部类型</option>
        <option v-for="(label, k) in KINDS" :key="k" :value="k">{{ label }}</option>
      </select>
      <span class="text-ink-400">删除时间</span>
      <input v-model="deletedAfter" type="date" class="input w-36" @change="load" />
      <span class="text-ink-400">至</span>
      <input v-model="deletedBefore" type="date" class="input w-36" @change="load" />
      <button class="btn-outline px-2" @click="load">查询</button>
      <button class="btn-ghost px-2" @click="resetFilters">重置</button>
      <span class="ml-auto text-ink-400">共 {{ list.length }} 个 · 按剩余天数排序</span>
    </div>

    <!-- #160 加载/操作失败提示 + 重试，不再停在旧数据上静默失败 -->
    <div v-if="error" class="card flex items-center gap-3 p-3" role="alert">
      <span class="text-[13px] text-rose-600">{{ error }}</span>
      <button class="btn-outline ml-auto px-2 py-1 text-[12px]" :disabled="loading" @click="load">
        {{ loading ? '重试中…' : t('common.retry', '重试') }}
      </button>
    </div>

    <div v-if="!error" class="card divide-y divide-ink-50">
      <div v-for="f in list" :key="f.id" class="flex items-center gap-3 px-4 py-2.5">
        <span class="text-[18px]">{{ fileIcon(f.kind, f.ext) }}</span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px] font-medium">{{ f.name }}</div>
          <div class="text-[11px] text-ink-400">{{ f.size_text }} · 删除于 {{ formatTime(f.deleted_at) }}<span v-if="f.origin_folder_id"> · 原目录 #{{ f.origin_folder_id }}</span></div>
        </div>
        <!-- S24-225 距自动清理剩余天数（<=3 天高亮） -->
        <span v-if="f.remaining_days !== undefined" class="shrink-0 rounded-pill px-2 py-0.5 text-[11px]"
              :class="f.remaining_days <= 3 ? 'bg-rose-50 text-rose-600' : 'bg-ink-50 text-ink-500'">
          {{ f.remaining_days }} 天后清理
        </span>
        <button class="btn-outline px-2 text-[12px]" @click="restore([f.id])">还原</button>
        <button class="btn-danger px-2 text-[12px]" @click="destroy([f.id])">彻底删除</button>
      </div>
      <div v-if="!list.length" class="py-16 text-center text-[13px] text-ink-400">{{ t('trash.empty', '回收站是空的') }}</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { fileApi } from '../../api'
import { filesx } from '../../api/filesx'
import { fileIcon, formatTime } from '../../utils/format'
import { useAppStore } from '../../stores/app'
import { t } from '../../i18n'

const app = useAppStore()
const list = ref([])
const keepDays = ref(30)
// S24-232 筛选条件
const q = ref('')
const kindFilter = ref('')
const deletedAfter = ref('')
const deletedBefore = ref('')
// #160 统一的加载/错误状态
const loading = ref(false)
const error = ref('')
// F551 回收站统计
const stats = ref({})
const KINDS = { image: '图片', video: '视频', audio: '音频', archive: '压缩包', text: '文档', other: '其它' }
const kindName = (k) => KINDS[k] || k

async function loadStats() {
  try { stats.value = await filesx.trashStats() } catch (e) { stats.value = {} }
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const r = await filesx.trashList({
      q: q.value || undefined,
      kind: kindFilter.value || undefined,
      deleted_after: deletedAfter.value || undefined,
      deleted_before: deletedBefore.value || undefined,
    })
    if (r.keep_days) keepDays.value = r.keep_days
    const rows = r.list || r.results || []
    // S24-225 按剩余天数升序，快过期的排在最前
    rows.sort((a, b) => (a.remaining_days ?? 9999) - (b.remaining_days ?? 9999))
    list.value = rows
    loadStats()
  } catch (e) {
    error.value = e?.message || `${t('trash.loadFailed', '回收站加载失败')}，请重试`
  } finally {
    loading.value = false
  }
}
function resetFilters() {
  q.value = ''
  kindFilter.value = ''
  deletedAfter.value = ''
  deletedBefore.value = ''
  load()
}
// #160 操作统一收敛：失败提示 + 重新拉取，避免页面停留在旧数据
async function runAction(fn, okMsg) {
  error.value = ''
  try {
    await fn()
    if (okMsg) app.toastMsg(okMsg, 'success')
    await load()
  } catch (e) {
    error.value = e?.message || t('trash.actionFailed', '操作失败，请重试')
    app.toastMsg(e?.message || t('trash.actionFailed', '操作失败，请重试'), 'error')
  }
}
async function restore(ids) {
  // S24-229 冲突自动改名：提示「N 个文件已改名恢复」
  error.value = ''
  try {
    const r = await fileApi.trashAction('restore', ids)
    const renamed = r?.renamed || 0
    if (renamed) app.toastMsg(`${r?.restored ?? ids.length} 个文件已恢复，其中 ${renamed} 个文件已改名恢复`, 'success')
    else app.toastMsg('已还原到原目录', 'success')
    await load()
  } catch (e) {
    error.value = e?.message || t('trash.actionFailed', '操作失败，请重试')
    app.toastMsg(e?.message || t('trash.actionFailed', '操作失败，请重试'), 'error')
  }
}
async function destroy(ids) {
  if (!confirm('彻底删除后无法恢复，确定？')) return
  await runAction(() => fileApi.trashAction('delete', ids), '已彻底删除')
}
async function empty() {
  const n = stats.value.count ?? list.value.length
  if (!confirm(`确定清空整个回收站？共 ${n} 个文件，清空后无法恢复。`)) return
  await runAction(() => fileApi.trashAction('empty', []), '已清空')
}
async function autoClean() {
  try {
    const r = await fileApi.trashAutoClean()
    app.toastMsg(`已清理 ${r.cleaned ?? r.deleted ?? 0} 个过期文件`, 'success')
    await load()
  } catch (e) {
    error.value = e?.message || t('trash.cleanFailed', '清理失败，请重试')
    app.toastMsg(e?.message || t('trash.cleanFailed', '清理失败，请重试'), 'error')
  }
}
onMounted(load)

</script>
