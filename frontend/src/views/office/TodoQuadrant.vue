<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 标题 + 操作 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">待办四象限</h2>
        <p class="text-[12px] text-ink-400">
          按「重要 × 紧急」自动分桶（紧急 = 高优先级或今天及以前到期），行内可直接完成 / 重开
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="data?.date" class="text-[12px] text-ink-400">{{ data.date }}</span>
        <span class="tag-brand">未完成 {{ data?.total ?? 0 }}</span>
        <button class="btn-outline" :disabled="loading" @click="load">
          {{ loading ? '刷新中…' : '↻ 刷新' }}
        </button>
      </div>
    </div>

    <!-- 加载态 -->
    <div v-if="loading && !quads.length" class="grid gap-4 md:grid-cols-2">
      <div v-for="i in 4" :key="i" class="card animate-pulse p-4">
        <div class="mb-3 h-4 w-24 rounded bg-ink-100"></div>
        <div class="space-y-2">
          <div v-for="j in 3" :key="j" class="h-8 rounded bg-ink-50"></div>
        </div>
      </div>
    </div>

    <!-- 错误态 -->
    <div v-else-if="error" class="card flex items-center gap-3 border-l-4 border-rose-300 p-4">
      <span class="text-[18px]">⚠️</span>
      <div class="min-w-0 flex-1">
        <div class="text-[13px] font-medium text-ink-800">四象限加载失败</div>
        <div class="truncate text-[12px] text-rose-500">{{ error }}</div>
      </div>
      <button class="btn-outline shrink-0" @click="load">重试</button>
    </div>

    <!-- 四象限网格 -->
    <div v-else class="grid gap-4 md:grid-cols-2">
      <div v-for="q in quads" :key="q.key" class="card flex flex-col p-4" :class="accentOf(q.accent).border">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full" :class="accentOf(q.accent).dot"></span>
            <span class="text-[13px] font-semibold text-ink-800">{{ q.name }}</span>
            <span class="text-[11px] text-ink-400">{{ q.hint }}</span>
          </div>
          <span class="tag" :class="accentOf(q.accent).badge">{{ q.count }}</span>
        </div>

        <div v-if="!q.items?.length" class="py-8 text-center text-[12px] text-ink-300">
          这个象限空着，继续保持
        </div>
        <ul v-else class="mt-2 divide-y divide-ink-50">
          <li
            v-for="it in q.items.slice(0, 10)"
            :key="it.id"
            class="flex items-center gap-2 py-1.5"
          >
            <button
              class="min-w-0 flex-1 truncate text-left text-[12px] text-ink-700 hover:text-brand-600"
              :title="`勾选完成：${it.title}`"
              :aria-label="`完成待办 ${it.title}`"
              :disabled="busyId === it.id"
              @click="completeItem(it)"
            >
              {{ it.title || '未命名待办' }}
            </button>
            <span v-if="it.overdue" class="tag shrink-0 bg-rose-50 text-rose-600">逾期</span>
            <span v-else-if="it.due_date" class="tag shrink-0">今天</span>
            <span v-if="it.priority && it.priority !== 'normal'" class="tag shrink-0 bg-amber-50 text-amber-600">
              {{ priorityLabel(it.priority) }}
            </span>
            <button
              class="btn-outline shrink-0 px-2 py-0.5 text-[11px]"
              :disabled="busyId === it.id"
              :aria-label="`完成待办 ${it.title}`"
              @click="completeItem(it)"
            >
              {{ busyId === it.id ? '…' : '完成' }}
            </button>
          </li>
        </ul>
        <div v-if="q.count > 10" class="mt-2 text-[11px] text-ink-400">
          仅显示前 10 条，另有 {{ q.count - 10 }} 条未展开
        </div>
      </div>
    </div>

    <!-- 本次会话刚完成的条目：可一键重开（后端 reopen 老接口） -->
    <div v-if="recentlyDone.length" class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <span class="text-[13px] font-medium text-ink-700">刚刚完成</span>
        <button class="text-[12px] text-ink-400 hover:text-rose-500" @click="recentlyDone = []">清空</button>
      </div>
      <div class="flex flex-wrap gap-2">
        <div
          v-for="it in recentlyDone"
          :key="it.id"
          class="flex items-center gap-2 rounded-control bg-ink-50 px-2 py-1 text-[12px] text-ink-600"
        >
          <span class="text-emerald-600">✓</span>
          <span class="max-w-[220px] truncate">{{ it.title }}</span>
          <button
            class="text-[11px] text-brand-600 hover:underline"
            :disabled="busyId === it.id"
            @click="reopenItem(it)"
          >
            {{ busyId === it.id ? '…' : '重开' }}
          </button>
        </div>
      </div>
    </div>

    <p v-if="data?.legend" class="px-1 text-[11px] text-ink-300">{{ data.legend }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { officex } from '../../api/officex'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const data = ref(null)
const loading = ref(false)
const error = ref('')
const busyId = ref(null)
const recentlyDone = ref([])

const quads = computed(() => data.value?.quadrants || data.value?.groups || [])

const ACCENTS = {
  rose: { border: 'border-l-4 border-l-rose-400', dot: 'bg-rose-500', badge: 'bg-rose-50 text-rose-600' },
  brand: { border: 'border-l-4 border-l-brand-400', dot: 'bg-brand-500', badge: 'bg-brand-50 text-brand-700' },
  amber: { border: 'border-l-4 border-l-amber-400', dot: 'bg-amber-500', badge: 'bg-amber-50 text-amber-600' },
  slate: { border: 'border-l-4 border-l-ink-300', dot: 'bg-ink-400', badge: 'bg-ink-100 text-ink-600' },
}
function accentOf(key) {
  return ACCENTS[key] || ACCENTS.slate
}

const PRIORITY_LABELS = { low: '低', normal: '普通', high: '高', urgent: '紧急' }
function priorityLabel(p) {
  return PRIORITY_LABELS[p] || p
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await officex.todoQuadrant()
  } catch (e) {
    error.value = e?.message || '请求失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
  }
}

async function completeItem(item) {
  if (busyId.value) return
  busyId.value = item.id
  try {
    await officex.todoComplete(item.id)
    // 会话内保留完成记录，方便误点后立刻重开（后端四象限只返回未完成项）
    recentlyDone.value = [{ id: item.id, title: item.title || '未命名待办' }, ...recentlyDone.value].slice(0, 12)
    app.toastMsg('已完成：' + (item.title || '未命名待办'), 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '完成失败', 'error')
  } finally {
    busyId.value = null
  }
}

async function reopenItem(item) {
  if (busyId.value) return
  busyId.value = item.id
  try {
    await officex.todoReopen(item.id)
    recentlyDone.value = recentlyDone.value.filter((x) => x.id !== item.id)
    app.toastMsg('已重开：' + (item.title || '未命名待办'), 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '重开失败', 'error')
  } finally {
    busyId.value = null
  }
}

onMounted(load)
</script>
