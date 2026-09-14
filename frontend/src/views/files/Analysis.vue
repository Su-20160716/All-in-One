<template>
  <div class="mx-auto max-w-5xl space-y-4" v-if="data">
    <!-- 用量概览 -->
    <div class="grid grid-cols-4 gap-3">
      <div class="card p-4">
        <div class="text-[12px] text-ink-400">已用空间</div>
        <div class="mt-1 text-[20px] font-bold text-ink-800">{{ data.used_text }}</div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-100">
          <div class="h-full bg-brand-500" :style="{ width: Math.min(100, data.quota_used_pct) + '%' }"></div>
        </div>
        <div class="mt-1 text-[11px] text-ink-400">配额 {{ data.quota_mb }} MB · {{ data.quota_used_pct }}%</div>
      </div>
      <div class="card p-4"><div class="text-[12px] text-ink-400">文件总数</div><div class="mt-1 text-[20px] font-bold">{{ data.file_count }}</div></div>
      <div class="card p-4"><div class="text-[12px] text-ink-400">收藏文件</div><div class="mt-1 text-[20px] font-bold">{{ data.starred }}</div></div>
      <div class="card p-4"><div class="text-[12px] text-ink-400">回收站占用</div><div class="mt-1 text-[20px] font-bold text-rose-500">{{ data.trash_text }}</div></div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <!-- 类型分布 -->
      <div class="card p-4">
        <h3 class="mb-3 text-[14px] font-semibold">按类型分布</h3>
        <div v-for="k in data.by_kind" :key="k.kind" class="mb-2">
          <div class="mb-1 flex justify-between text-[12px]">
            <span>{{ kindName(k.kind) }}</span><span class="text-ink-400">{{ k.count }} 个 · {{ k.size_text }}</span>
          </div>
          <div class="h-2 rounded-full bg-ink-100">
            <div class="h-full rounded-full bg-brand-500" :style="{ width: pct(k.bytes_sum) + '%' }"></div>
          </div>
        </div>
        <div v-if="!data.by_kind.length" class="text-[12px] text-ink-400">暂无文件</div>
      </div>

      <!-- 大文件 -->
      <div class="card p-4">
        <h3 class="mb-3 text-[14px] font-semibold">大文件 Top {{ data.big_files.length }}</h3>
        <div v-for="f in data.big_files" :key="f.id" class="flex items-center justify-between border-b border-ink-50 py-1.5 text-[13px]">
          <span class="truncate">{{ fileIcon(f.kind, f.ext) }} {{ f.name }}</span>
          <span class="ml-2 shrink-0 text-ink-400">{{ f.size_text }}</span>
        </div>
      </div>
    </div>

    <!-- 重复文件 -->
    <div class="card p-4">
      <h3 class="mb-2 text-[14px] font-semibold">重复文件 <span class="text-[12px] font-normal text-ink-400">可释放 {{ data.duplicate_wasted_text }}</span></h3>
      <div v-for="d in data.duplicates" :key="d.sha1" class="flex items-center justify-between py-1.5 text-[13px]">
        <span>{{ d.name }}</span><span class="text-ink-400">{{ d.count }} 份 · 每份 {{ d.size_text }}</span>
      </div>
      <div v-if="!data.duplicates.length" class="text-[12px] text-ink-400">没有检测到重复文件</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref, computed } from 'vue'
import { fileApi } from '../../api'
import { fileIcon, formatSize } from '../../utils/format'

const data = ref(null)
const maxBytes = computed(() => Math.max(1, ...(data.value?.by_kind || []).map((k) => k.bytes_sum || 0)))
const pct = (b) => Math.round(((b || 0) / maxBytes.value) * 100)
const NAMES = { image: '图片', video: '视频', audio: '音频', archive: '压缩包', text: '文档', other: '其它' }
const kindName = (k) => NAMES[k] || k

onMounted(async () => {
  data.value = await fileApi.analysis()
})
</script>
