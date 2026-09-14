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
import { fileIcon, formatTime } from '../../utils/format'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const list = ref([])
const keepDays = 30

async function load() {
  const r = await fileApi.trashList()
  list.value = r.list || []
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
  if (!confirm('确定清空整个回收站？')) return
  await fileApi.trashAction('empty', [])
  app.toastMsg('已清空', 'success')
  load()
}
async function autoClean() {
  const r = await fileApi.trashAutoClean()
  app.toastMsg(`已清理 ${r.deleted} 个过期文件`, 'success')
  load()
}
onMounted(load)
</script>
