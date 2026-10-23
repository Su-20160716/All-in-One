<template>
  <div class="min-h-screen bg-ink-50 p-6">
    <div v-if="loading" class="grid h-64 place-items-center text-ink-400">加载中…</div>
    <div v-else-if="error" class="mx-auto mt-20 max-w-md text-center">
      <div class="text-[40px]">🔗</div>
      <div class="mt-2 text-[15px] font-semibold text-ink-700">{{ error }}</div>
      <div class="mt-1 text-[12px] text-ink-400">链接可能已失效或被撤销</div>
    </div>
    <div v-else>
      <div class="mb-4 flex items-center gap-3">
        <div class="h-3 w-12 rounded-pill" :style="{ background: project.color }"></div>
        <h1 class="text-[18px] font-bold text-ink-900">{{ project.name }}</h1>
        <span class="tag bg-ink-100 text-ink-500">只读分享</span>
      </div>
      <div class="flex gap-3 overflow-x-auto">
        <div v-for="b in boards" :key="b.id" class="w-72 shrink-0 rounded-card bg-white p-3 shadow-card">
          <div class="mb-2 text-[13px] font-semibold text-ink-700">{{ b.name }} <span class="text-[11px] text-ink-400">{{ b.cards.length }}</span></div>
          <div class="space-y-2">
            <div v-for="c in b.cards" :key="c.id" class="rounded-control border border-ink-100 p-2.5">
              <div class="text-[13px] font-medium">{{ c.title }}</div>
              <div class="mt-1.5 flex flex-wrap gap-1">
                <span v-for="l in c.labels || []" :key="l" class="rounded-pill bg-brand-50 px-1.5 py-0.5 text-[10px] text-brand-700">{{ l }}</span>
              </div>
              <div class="mt-1.5 text-[11px] text-ink-400">
                <span v-if="c.due_date" :class="c.is_overdue ? 'text-rose-500' : ''">{{ c.due_date }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { API_URL } from '../../api/base'

const route = useRoute()
const project = ref({})
const boards = ref([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    // F3：走 /api/share/board/*（前端不再代理 /share 前缀）
    const res = await axios.get(`${API_URL}/share/board/${route.params.token}/`)
    project.value = res.data.project
    boards.value = res.data.boards || []
  } catch (e) {
    error.value = e.response?.data?.message || '分享链接无效'
  } finally {
    loading.value = false
  }
})
</script>
