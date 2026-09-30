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

    <div class="card divide-y divide-ink-50">
      <div v-for="f in list" :key="f.id" class="flex items-center gap-3 px-4 py-2.5">
        <span class="text-[18px]">{{ fileIcon(f.kind, f.ext) }}</span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px] font-medium">{{ f.name }}</div>
          <div class="text-[11px] text-ink-400">{{ f.size_text }} · 删除于 {{ formatTime(f.deleted_at) }}<span v-if="f.origin_folder_id"> · 原目录 #{{ f.origin_folder_id }}</span></div>
        </div>
        <button class="btn-outline px-2 text-[12px]" @click="restore([f.id])">还原</button>
        <button class="btn-danger px-2 text-[12px]" @click="destroy([f.id])">彻底删除</button>
      </div>
      <div v-if="!list.length" class="py-16 text-center text-[13px] text-ink-400">回收站是空的</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { fileApi } from '../../api'
import { filesx } from '../../api/filesx'
import { fileIcon, formatTime } from '../../utils/format'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const list = ref([])
const keepDays = 30
// F551 回收站统计
const stats = ref({})
const KINDS = { image: '图片', video: '视频', audio: '音频', archive: '压缩包', text: '文档', other: '其它' }
const kindName = (k) => KINDS[k] || k

async function loadStats() {
  try { stats.value = await filesx.trashStats() } catch (e) { stats.value = {} }
}
async function load() {
  const r = await fileApi.trashList()
  list.value = r.list || []
  loadStats()
}
async function restore(ids) {
  await fileApi.trashAction('restore', ids)
  app.toastMsg('已还原到原目录', 'success')
  load()
}
async function destroy(ids) {
  if (!confirm('彻底删除后无法恢复，确定？')) return
  await fileApi.trashAction('delete', ids)
  load()
}
async function empty() {
  const n = stats.value.count ?? list.value.length
  if (!confirm(`确定清空整个回收站？共 ${n} 个文件，清空后无法恢复。`)) return
  await fileApi.trashAction('empty', [])
  app.toastMsg('已清空', 'success')
  load()
}
async function autoClean() {
  const r = await fileApi.trashAutoClean()
  app.toastMsg(`已清理 ${r.cleaned ?? r.deleted ?? 0} 个过期文件`, 'success')
  load()
}
onMounted(load)
</script>
