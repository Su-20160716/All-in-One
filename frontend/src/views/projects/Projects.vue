<template>
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="card flex flex-wrap items-center gap-2 p-4">
      <div>
        <h2 class="text-[15px] font-semibold text-ink-800">我的项目</h2>
        <p class="mt-0.5 text-[12px] text-ink-500">看板管理任务，支持收藏、克隆与成员协作。</p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <input v-model="kw" class="input w-44" placeholder="搜索项目…" @input="load" />
        <select v-model="scope" class="input w-32" @change="load">
          <option value="">全部</option><option value="starred">仅收藏</option><option value="archived">已归档</option>
        </select>
        <button class="btn-primary" @click="showCreate = true">＋ 新建项目</button>
      </div>
    </div>

    <div v-if="shown.length" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="p in shown" :key="p.id" class="card group cursor-pointer p-4 transition-shadow hover:shadow-pop" @click="openBoard(p.id)">
        <div class="flex items-start justify-between">
          <div class="h-2 w-10 rounded-pill" :style="{ background: p.color }"></div>
          <div class="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100" @click.stop>
            <button class="btn-ghost px-1.5 text-[13px]" :class="p.is_star ? 'text-amber-500' : ''" title="收藏" @click="star(p)">{{ p.is_star ? '★' : '☆' }}</button>
            <button class="btn-ghost px-1.5 text-[12px]" title="克隆" @click="clone(p)">⧉</button>
            <button class="btn-ghost px-1.5 text-[12px]" :title="p.is_archived ? '取消归档' : '归档'" @click="toggleArchive(p)">{{ p.is_archived ? '↺' : '🗄' }}</button>
            <button class="btn-ghost px-1.5 text-[12px] text-rose-500" title="删除" @click="removeProject(p)">✕</button>
          </div>
        </div>
        <h3 class="mt-3 text-[15px] font-semibold text-ink-900">{{ p.is_star ? '★ ' : '' }}{{ p.name }}</h3>
        <p class="mt-1 line-clamp-2 text-[12px] text-ink-500">{{ p.description || '暂无描述' }}</p>
        <div class="mt-3 flex items-center justify-between text-[11px] text-ink-400">
          <span>{{ p.board_count }} 列 · {{ p.card_total }} 卡 · 👥 {{ p.member_names.length + 1 }}</span>
          <span v-if="p.card_total" class="text-emerald-500">{{ Math.round((p.done_total / p.card_total) * 100) }}% 完成</span>
        </div>
        <div class="mt-2 h-1 overflow-hidden rounded-pill bg-ink-100">
          <div class="h-full bg-emerald-400" :style="{ width: p.card_total ? Math.round((p.done_total / p.card_total) * 100) + '%' : '0%' }"></div>
        </div>
      </div>
    </div>
    <div v-else class="card py-20 text-center">
      <div class="text-[32px]">📋</div>
      <div class="mt-2 text-[13px] text-ink-400">没有匹配的项目</div>
    </div>

    <Modal :show="showCreate" title="新建项目" @close="showCreate = false">
      <div class="space-y-3">
        <input v-model="form.name" class="input" placeholder="项目名称" />
        <textarea v-model="form.description" class="input h-20 resize-none" placeholder="项目描述（选填）"></textarea>
        <div class="flex gap-2">
          <span v-for="c in colors" :key="c" class="h-7 w-7 cursor-pointer rounded-pill border-2" :style="{ background: c, borderColor: form.color === c ? '#0f172a' : 'transparent' }" @click="form.color = c"></span>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showCreate = false">取消</button>
          <button class="btn-primary" @click="createProject">创建</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { projectApi } from '../../api'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const router = useRouter()
const app = useAppStore()
const projects = ref([])
const showCreate = ref(false)
const kw = ref('')
const scope = ref('')
const form = reactive({ name: '', description: '', color: '#0ea5e9' })
const colors = ['#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#64748b']

const shown = computed(() => {
  let arr = projects.value
  if (scope.value === 'starred') arr = arr.filter((p) => p.is_star)
  if (scope.value === 'archived') arr = arr.filter((p) => p.is_archived)
  if (kw.value) arr = arr.filter((p) => p.name.includes(kw.value))
  return arr
})

async function load() {
  projects.value = (await projectApi.list()).list || []
}
async function createProject() {
  if (!form.name.trim()) return
  const p = await projectApi.create({ ...form })
  app.toastMsg('项目已创建', 'success')
  showCreate.value = false
  form.name = ''; form.description = ''
  load()
  router.push(`/projects/${p.id}/board`)
}
async function toggleArchive(p) {
  await projectApi.update(p.id, { is_archived: !p.is_archived })
  load()
}
async function star(p) {
  await projectApi.star(p.id)
  p.is_star = !p.is_star
}
async function clone(p) {
  await projectApi.clone(p.id)
  app.toastMsg('已克隆', 'success')
  load()
}
async function removeProject(p) {
  if (!confirm(`确定删除项目「${p.name}」？`)) return
  await projectApi.remove(p.id)
  app.toastMsg('已删除', 'success')
  load()
}
function openBoard(id) { router.push(`/projects/${id}/board`) }
onMounted(load)
</script>
