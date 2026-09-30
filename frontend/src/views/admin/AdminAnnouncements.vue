<template>
  <div class="mx-auto max-w-4xl space-y-4">
    <div class="card p-4">
      <h3 class="mb-3 text-[14px] font-semibold">发布公告</h3>
      <input v-model="form.title" class="input mb-2" placeholder="公告标题" />
      <textarea v-model="form.content" class="input h-28 resize-none" placeholder="公告正文"></textarea>
      <div class="mt-2 flex flex-wrap items-center gap-3">
        <select v-model="form.level" class="input w-32">
          <option value="info">普通</option>
          <option value="important">重要</option>
          <option value="urgent">紧急</option>
        </select>
        <label class="flex items-center gap-1.5 text-[13px]"><input v-model="form.is_pinned" type="checkbox" /> 置顶</label>
        <label class="flex items-center gap-1.5 text-[13px]"><input v-model="form.is_published" type="checkbox" /> 立即发布</label>
      </div>
      <!-- #70 定时发布 + 到期 -->
      <div class="mt-2 flex flex-wrap items-center gap-3">
        <label class="text-[12px] text-ink-500">定时发布：</label>
        <input v-model="form.scheduled_at" type="datetime-local" class="input w-52" />
        <label class="text-[12px] text-ink-500">到期时间：</label>
        <input v-model="form.expires_at" type="datetime-local" class="input w-52" />
        <button class="btn-primary ml-auto" @click="publish">发布</button>
      </div>
    </div>

    <div class="card overflow-hidden">
      <table class="w-full">
        <thead class="bg-ink-50">
          <tr><th class="th">标题</th><th class="th">级别</th><th class="th">状态</th><th class="th">已读</th><th class="th">发布时间</th><th class="th">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="a in list" :key="a.id" class="border-t border-ink-50">
            <td class="td">{{ a.is_pinned ? '📌 ' : '' }}{{ a.title }}</td>
            <td class="td">{{ levelName(a.level) }}</td>
            <td class="td"><span class="tag" :class="statusClass(a.status)">{{ statusName(a.status) }}</span></td>
            <td class="td">{{ a.read_count }}</td>
            <td class="td">{{ fmt(a.created_at) }}</td>
            <td class="td whitespace-nowrap">
              <button class="btn-ghost px-2 text-[12px]" @click="togglePin(a)">{{ a.is_pinned ? '取消置顶' : '置顶' }}</button>
              <!-- #73 导出已读名单 -->
              <a class="btn-ghost px-2 text-[12px] text-brand-600" :href="readersExportUrl(a.id)">导出已读</a>
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
const form = reactive({ title: '', content: '', level: 'info', is_pinned: false, is_published: true, scheduled_at: '', expires_at: '' })
const fmt = formatTime
const levelName = (l) => ({ info: '普通', important: '重要', urgent: '紧急' }[l])
const readersExportUrl = (id) => `/api/core/admin/announcements/${id}/readers/export/`
function statusName(s) {
  return { draft: '草稿', scheduled: '定时', published: '已发布', expired: '已过期' }[s] || s
}
function statusClass(s) {
  return { draft: 'bg-ink-100 text-ink-500', scheduled: 'bg-blue-50 text-blue-600', published: 'bg-emerald-50 text-emerald-600', expired: 'bg-rose-50 text-rose-600' }[s] || ''
}

async function load() {
  const r = await coreApi.adminAnnouncements()
  list.value = r.list
}
async function publish() {
  if (!form.title.trim()) return app.toastMsg('请填写标题', 'error')
  const payload = { ...form }
  if (!payload.scheduled_at) delete payload.scheduled_at
  if (!payload.expires_at) delete payload.expires_at
  await coreApi.createAnnouncement(payload)
  app.toastMsg('已发布', 'success')
  form.title = ''; form.content = ''; form.scheduled_at = ''; form.expires_at = ''
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
