<template>
  <div class="mx-auto max-w-3xl space-y-3">
    <h2 class="text-[16px] font-semibold text-ink-800">系统公告 <span class="text-[12px] font-normal text-ink-400">未读 {{ unread }}</span></h2>
    <div v-for="a in list" :key="a.id" class="card p-4" :class="a.is_pinned ? 'ring-1 ring-amber-200' : ''">
      <div class="flex items-center gap-2">
        <span class="rounded-pill px-2 py-0.5 text-[11px]" :class="levelClass(a.level)">{{ levelName(a.level) }}</span>
        <span v-if="a.is_pinned" class="tag">置顶</span>
        <h3 class="text-[15px] font-semibold text-ink-800">{{ a.title }}</h3>
        <span v-if="!a.is_read" class="ml-auto h-2 w-2 rounded-full bg-rose-500"></span>
      </div>
      <p class="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-600">{{ a.content }}</p>
      <div class="mt-2 flex items-center justify-between text-[11px] text-ink-400">
        <span>{{ a.author_name }} · {{ fmt(a.created_at) }}</span>
        <span>已读 {{ a.read_count }}</span>
      </div>
    </div>
    <div v-if="!list.length" class="card grid h-40 place-items-center text-[13px] text-ink-400">暂无公告</div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { coreApi } from '../api'
import { formatTime } from '../utils/format'

const list = ref([])
const unread = ref(0)
const fmt = formatTime
const levelName = (l) => ({ info: '普通', important: '重要', urgent: '紧急' }[l] || '普通')
const levelClass = (l) => ({
  info: 'bg-ink-100 text-ink-600',
  important: 'bg-amber-50 text-amber-600',
  urgent: 'bg-rose-50 text-rose-600',
}[l] || 'bg-ink-100 text-ink-600')

onMounted(async () => {
  const r = await coreApi.announcements()
  list.value = r.list || []
  unread.value = list.value.filter((x) => !x.is_read).length
  for (const a of list.value.filter((x) => !x.is_read)) {
    coreApi.readAnnouncement(a.id).catch(() => {})
  }
})
</script>
