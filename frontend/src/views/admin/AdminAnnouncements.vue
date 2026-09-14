<template>
  <div class="mx-auto max-w-4xl space-y-4">
    <div class="card p-4">
      <h3 class="mb-3 text-[14px] font-semibold">发布公告</h3>
      <input v-model="form.title" class="input mb-2" placeholder="公告标题" />
      <textarea v-model="form.content" class="input h-28 resize-none" placeholder="公告正文"></textarea>
      <div class="mt-2 flex items-center gap-3">
        <select v-model="form.level" class="input w-32">
          <option value="info">普通</option>
          <option value="important">重要</option>
          <option value="urgent">紧急</option>
        </select>
        <label class="flex items-center gap-1.5 text-[13px]"><input v-model="form.is_pinned" type="checkbox" /> 置顶</label>
        <button class="btn-primary ml-auto" @click="publish">发布</button>
      </div>
    </div>

    <div class="card overflow-hidden">
      <table class="w-full">
        <thead class="bg-ink-50">
          <tr><th class="th">标题</th><th class="th">级别</th><th class="th">已读</th><th class="th">发布时间</th><th class="th">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in list" :key="a.id" class="border-t border-ink-50">
            <td class="td">{{ a.is_pinned ? '📌 ' : '' }}{{ a.title }}</td>
            <td class="td">{{ levelName(a.level) }}</td>
            <td class="td">{{ a.read_count }}</td>
            <td class="td">{{ fmt(a.created_at) }}</td>
            <td class="td">
              <button class="btn-ghost px-2 text-[12px]" @click="togglePin(a)">{{ a.is_pinned ? '取消置顶' : '置顶' }}</button>
              <button class="btn-danger px-2 text-[12px]" @click="remove(a)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { coreApi } from '../../api'
import { formatTime } from '../../utils/format'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const list = ref([])
const form = reactive({ title: '', content: '', level: 'info', is_pinned: false })
const fmt = formatTime
const levelName = (l) => ({ info: '普通', important: '重要', urgent: '紧急' }[l])

async function load() {
  const r = await coreApi.adminAnnouncements()
  list.value = r.list
}
async function publish() {
  if (!form.title.trim()) return app.toastMsg('请填写标题', 'error')
  await coreApi.createAnnouncement({ ...form })
  app.toastMsg('已发布', 'success')
  form.title = ''
  form.content = ''
  load()
}
async function togglePin(a) {
  await coreApi.updateAnnouncement(a.id, { is_pinned: !a.is_pinned })
  load()
}
async function remove(a) {
  if (!confirm(`确定删除公告「${a.title}」？`)) return
  await coreApi.deleteAnnouncement(a.id)
  load()
}
onMounted(load)
</script>
