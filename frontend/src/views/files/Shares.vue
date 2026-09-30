<template>
  <div class="mx-auto max-w-5xl space-y-3">
    <div class="card flex items-center gap-2 p-3">
      <h2 class="text-[15px] font-semibold text-ink-800">共享链接</h2>
      <select v-model="statusFilter" class="input w-28" @change="load">
        <option value="">全部状态</option><option value="active">有效</option><option value="expired">已过期</option>
      </select>
      <select v-model="typeFilter" class="input w-28" @change="load">
        <option value="">全部类型</option><option value="file">文件</option><option value="folder">文件夹</option>
      </select>
      <span class="ml-auto text-[12px] text-ink-400">共 {{ list.length }} 条链接</span>
    </div>

    <!-- F560 分享链接到期前 3 天提醒 -->
    <div v-if="expiring.length" class="card border-l-4 border-amber-400 p-3">
      <div class="mb-1.5 flex items-center gap-2">
        <span class="text-[13px] font-semibold text-amber-600">⏰ 即将到期提醒（{{ expiringDays }} 天内）</span>
        <span class="text-[12px] text-ink-400">共 {{ expiring.length }} 条链接即将失效</span>
        <button class="btn-ghost ml-auto px-2 text-[12px]" @click="loadExpiring">刷新</button>
      </div>
      <div class="space-y-1">
        <div v-for="e in expiring" :key="e.token" class="flex items-center justify-between rounded-control bg-amber-50/60 px-3 py-1.5 text-[12px]">
          <span class="truncate">{{ e.target || '(已删除对象)' }} <span class="font-mono text-ink-400">{{ e.url }}</span></span>
          <span class="shrink-0 text-amber-600">
            {{ e.hours_left < 24 ? `${Math.max(1, Math.round(e.hours_left))} 小时后` : `${e.days_left} 天后` }}到期
            <button class="ml-2 text-brand-600" @click="copyUrl(e.url)">复制链接</button>
          </span>
        </div>
      </div>
    </div>

    <div class="card overflow-hidden">
      <table class="w-full">
        <thead class="bg-ink-50">
          <tr><th class="th">对象</th><th class="th">权限</th><th class="th">保护</th><th class="th">浏览/下载</th><th class="th">状态</th><th class="th">创建</th><th class="th">操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in list" :key="s.token" class="border-t border-ink-50">
            <td class="td max-w-48 truncate">{{ s.file_name }}</td>
            <td class="td">{{ permName(s.permission) }}</td>
            <td class="td">
              <span v-if="s.has_password" class="tag mr-1">🔒 密码</span>
              <span v-if="s.max_downloads" class="tag">限 {{ s.max_downloads }} 次</span>
              <span v-if="!s.has_password && !s.max_downloads" class="text-ink-300">-</span>
            </td>
            <td class="td">{{ s.view_count }} / {{ s.download_count }}</td>
            <td class="td">
              <span v-if="s.is_revoked" class="text-rose-500">已失效</span>
              <span v-else-if="s.is_expired" class="text-amber-500">已过期</span>
              <span v-else class="text-emerald-600">有效</span>
            </td>
            <td class="td">{{ formatTime(s.created_at) }}</td>
            <td class="td whitespace-nowrap">
              <button class="btn-ghost px-2 text-[12px]" @click="copy(s)">复制</button>
              <button class="btn-ghost px-2 text-[12px]" @click="edit(s)">设置</button>
              <button class="btn-danger px-2 text-[12px]" @click="revoke(s)">失效</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!list.length" class="grid h-32 place-items-center text-[13px] text-ink-400">还没有共享链接</div>
    </div>

    <Modal :show="!!editing" title="链接设置" @close="editing = null">
      <div class="space-y-3 text-[13px]">
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">权限</span>
          <select v-model="editForm.permission" class="input w-40"><option value="view">仅预览</option><option value="download">可下载</option></select></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">访问密码</span><input v-model="editForm.password" class="input w-40" placeholder="留空清除" /></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">下载上限</span><input v-model.number="editForm.max_downloads" type="number" class="input w-40" placeholder="不限" /></div>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="editing = null">取消</button><button class="btn-primary" @click="save">保存</button></div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { fileApi } from '../../api'
import { filesx } from '../../api/filesx'
import { formatTime } from '../../utils/format'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const list = ref([])
const statusFilter = ref('')
const typeFilter = ref('')
const editing = ref(null)
const editForm = ref({})
const permName = (p) => ({ view: '仅预览', download: '可下载', edit: '可编辑' }[p] || p)
// F560 到期前 3 天提醒
const expiring = ref([])
const expiringDays = ref(3)

async function load() {
  const r = await fileApi.shares({ status: statusFilter.value, type: typeFilter.value })
  list.value = r.list
}
async function loadExpiring() {
  try {
    const r = await filesx.expiringShares(expiringDays.value)
    expiring.value = r.list || []
  } catch (e) { expiring.value = [] }
}
function copyUrl(url) {
  navigator.clipboard?.writeText(`${location.origin}${url}`)
  app.toastMsg('链接已复制', 'success')
}
function copy(s) { copyUrl(s.url) }
function edit(s) { editing.value = s; editForm.value = { permission: s.permission, password: '', max_downloads: s.max_downloads } }
async function save() {
  await fileApi.updateShare(editing.value.token, editForm.value)
  editing.value = null
  app.toastMsg('已更新', 'success')
  load()
  loadExpiring()
}
async function revoke(s) {
  if (!confirm('确定让该链接立即失效？')) return
  await fileApi.revokeShare(s.token)
  load()
  loadExpiring()
}
onMounted(() => { load(); loadExpiring() })
</script>
