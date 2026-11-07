<template>
  <div class="mx-auto max-w-5xl space-y-3">
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <h2 class="text-[15px] font-semibold text-ink-800">共享链接</h2>
      <select v-model="statusFilter" class="input w-28" @change="load(true)">
        <option value="">全部状态</option><option value="active">有效</option><option value="expired">已过期</option>
      </select>
      <select v-model="typeFilter" class="input w-28" @change="load(true)">
        <option value="">全部类型</option><option value="file">文件</option><option value="folder">文件夹</option>
      </select>
      <!-- #180 权限筛选：变化回到第一页 -->
      <select v-model="permissionFilter" class="input w-28" @change="load(true)">
        <option value="">全部权限</option>
        <option value="view">仅预览</option>
        <option value="download">可下载</option>
        <option value="edit">可编辑</option>
      </select>
      <span class="ml-auto text-[12px] text-ink-400">共 {{ total }} 条链接</span>
    </div>

    <!-- #180 加载失败可重试 -->
    <div v-if="error" class="card flex items-center gap-3 p-3" role="alert">
      <span class="text-[13px] text-rose-600">{{ error }}</span>
      <button class="btn-outline ml-auto px-2 py-1 text-[12px]" :disabled="loading" @click="load">
        {{ loading ? '重试中…' : '重试' }}
      </button>
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
              <span v-if="s.max_downloads" class="tag mr-1">限 {{ s.max_downloads }} 次</span>
              <span v-if="s.allow_upload" class="tag">⬆ 可上传</span>
              <span v-if="!s.has_password && !s.max_downloads && !s.allow_upload" class="text-ink-300">-</span>
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
      <div v-if="!list.length" class="grid h-32 place-items-center text-[13px] text-ink-400">
        {{ loading ? '加载中…' : '还没有共享链接' }}
      </div>
      <!-- #180 前端分页 -->
      <div class="flex items-center justify-between border-t border-ink-100 px-4 py-2 text-[12px] text-ink-500">
        <span>共 {{ total }} 条{{ totalPages > 1 ? ` · 第 ${page}/${totalPages} 页` : '' }}</span>
        <div class="flex items-center gap-1">
          <button class="btn-ghost px-2 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <button class="btn-ghost px-2 text-[12px]" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <Modal :show="!!editing" title="链接设置" @close="editing = null">
      <div class="space-y-3 text-[13px]">
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">权限</span>
          <select v-model="editForm.permission" class="input w-40"><option value="view">仅预览</option><option value="download">可下载</option></select></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">访问密码</span>
          <!-- #143 密码不明文展示 -->
          <input v-model="editForm.password" type="password" autocomplete="new-password" class="input w-40" placeholder="留空则不修改" />
          <label class="flex items-center gap-1 text-ink-500"><input v-model="clearPwd" type="checkbox" />清除已有密码</label></div>
        <div class="flex items-center gap-3"><span class="w-20 text-ink-500">下载上限</span><input v-model.number="editForm.max_downloads" type="number" class="input w-40" placeholder="不限" /></div>
        <!-- S24-223 仅文件夹分享可开启访客上传 -->
        <label v-if="editing.target_type === 'folder' || editing.folder" class="flex items-center gap-2 text-ink-600">
          <input v-model="editForm.allow_upload" type="checkbox" /> 允许访客上传（收集链接）
        </label>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="editing = null">取消</button><button class="btn-primary" @click="save">保存</button></div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { fileApi } from '../../api'
import { filesx } from '../../api/filesx'
import { shareUrl as buildShareUrl } from '../../api/base'
import { formatTime } from '../../utils/format'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const list = ref([])
const statusFilter = ref('')
const typeFilter = ref('')
const permissionFilter = ref('')
const editing = ref(null)
const editForm = ref({})
const clearPwd = ref(false)
const permName = (p) => ({ view: '仅预览', download: '可下载', edit: '可编辑' }[p] || p)
// F560 到期前 3 天提醒
const expiring = ref([])
const expiringDays = ref(3)
// #180 分页状态（后端已统一为 {count,next,previous,results}）
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const error = ref('')
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

async function load(resetPage = false) {
  if (resetPage === true) page.value = 1
  loading.value = true
  error.value = ''
  try {
    const r = await fileApi.shares({
      status: statusFilter.value,
      type: typeFilter.value,
      permission: permissionFilter.value,
      page: page.value,
      page_size: pageSize.value,
    })
    // #53/#180 后端改为统一分页结构；兼容旧 {list} 响应
    list.value = r.results || r.list || []
    total.value = typeof r.count === 'number' ? r.count : list.value.length
  } catch (e) {
    list.value = []
    total.value = 0
    error.value = e?.message || '共享链接加载失败，请重试'
  } finally {
    loading.value = false
  }
}
function goPage(p) {
  const next = Math.min(totalPages.value, Math.max(1, p))
  if (next === page.value) return
  page.value = next
  load()
}
// 撤销/删除后当前页可能空掉，回退一页再拉
async function reloadAfterChange() {
  if (page.value > 1 && list.value.length <= 1) page.value -= 1
  await load()
}
async function loadExpiring() {
  try {
    const r = await filesx.expiringShares(expiringDays.value)
    expiring.value = r.list || []
  } catch (e) { expiring.value = [] }
}
// F4：复制走 base.js shareUrl()（VITE_PUBLIC_BASE 优先），本地 origin 仅兜底
function copyUrl(url) {
  const token = String(url || '').replace(/^\/share\//, '').replace(/\/+$/, '')
  navigator.clipboard?.writeText(token ? buildShareUrl(token) : `${location.origin}${url}`)
  app.toastMsg('链接已复制', 'success')
}
function copy(s) { copyUrl(s.url) }
function edit(s) { editing.value = s; clearPwd.value = false; editForm.value = { permission: s.permission, password: '', max_downloads: s.max_downloads, allow_upload: !!s.allow_upload } }
async function save() {
  // 未填新密码就不提交该字段，避免只改权限时把已有密码清空；要清空需显式勾选
  const payload = {
    permission: editForm.value.permission,
    max_downloads: editForm.value.max_downloads,
  }
  if (editing.value?.target_type === 'folder' || editing.value?.folder) {
    payload.allow_upload = !!editForm.value.allow_upload
  }
  const pwd = (editForm.value.password || '').trim()
  if (pwd) payload.password = pwd
  else if (clearPwd.value) payload.password = ''
  try {
    await fileApi.updateShare(editing.value.token, payload)
    editing.value = null
    app.toastMsg('已更新', 'success')
    await load()
    loadExpiring()
  } catch (e) {
    app.toastMsg(e?.message || '更新失败', 'error')
  }
}
async function revoke(s) {
  if (!confirm('确定让该链接立即失效？')) return
  try {
    await fileApi.revokeShare(s.token)
    app.toastMsg('链接已失效', 'success')
    await reloadAfterChange()
    loadExpiring()
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  }
}
onMounted(() => { load(); loadExpiring() })
</script>
