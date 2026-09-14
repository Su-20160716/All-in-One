<template>
  <div class="mx-auto max-w-2xl space-y-4">
    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">个人资料</h2>
      <div class="mt-4 flex items-center gap-4">
        <img v-if="user.profile?.avatar" :src="user.profile.avatar" class="h-16 w-16 rounded-full object-cover" />
        <div v-else class="grid h-16 w-16 place-items-center rounded-full bg-brand-100 text-[20px] font-bold text-brand-700">{{ user.displayName.slice(0, 1) }}</div>
        <div class="space-y-1.5">
          <button class="btn-outline text-[12px]" @click="avatarInput?.click()">更换头像</button>
          <input ref="avatarInput" type="file" accept="image/*" class="hidden" @change="uploadAvatar" />
          <button v-if="user.profile?.avatar" class="block btn-ghost px-2 text-[12px] text-rose-500" @click="removeAvatar">移除头像</button>
        </div>
      </div>
      <div class="mt-5 grid gap-4 sm:grid-cols-2">
        <div>
          <label class="mb-1 block text-[12px] font-medium text-ink-600">用户名（登录名）</label>
          <div class="flex gap-2">
            <input v-model="username" class="input" />
            <button class="btn-outline shrink-0 text-[12px]" @click="saveUsername">修改</button>
          </div>
        </div>
        <div><label class="mb-1 block text-[12px] font-medium text-ink-600">昵称</label><input v-model="form.nickname" class="input" /></div>
        <div><label class="mb-1 block text-[12px] font-medium text-ink-600">邮箱</label><input v-model="form.email" class="input" /></div>
        <div><label class="mb-1 block text-[12px] font-medium text-ink-600">手机号</label><input v-model="form.phone" class="input" /></div>
        <div class="sm:col-span-2"><label class="mb-1 block text-[12px] font-medium text-ink-600">个人简介</label><textarea v-model="form.bio" class="input h-20 resize-none"></textarea></div>
      </div>
      <div class="mt-4 flex justify-end"><button class="btn-primary" @click="saveProfile">保存资料</button></div>
    </div>

    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">修改密码</h2>
      <div class="mt-4 grid gap-4 sm:grid-cols-3">
        <input v-model="pwd.old_password" type="password" class="input" placeholder="原密码" />
        <input v-model="pwd.new_password" type="password" class="input" placeholder="新密码（至少 6 位）" />
        <input v-model="pwd.confirm" type="password" class="input" placeholder="确认新密码" />
      </div>
      <div class="mt-4 flex justify-end"><button class="btn-primary" @click="changePassword">修改密码</button></div>
    </div>

    <div class="card p-5">
      <div class="mb-2 flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-ink-800">登录历史</h2>
        <button class="text-[12px] text-brand-600" @click="loadHistory">刷新</button>
      </div>
      <div class="divide-y divide-ink-50">
        <div v-for="h in history" :key="h.id" class="flex items-center justify-between py-2 text-[12px] text-ink-600">
          <span>{{ h.ip || '未知 IP' }} · {{ h.device || '未知设备' }}</span>
          <span class="text-ink-400">{{ formatTime(h.created_at) }}<span v-if="h.is_success" class="ml-1 text-emerald-500">成功</span></span>
        </div>
        <div v-if="!history.length" class="py-4 text-center text-[12px] text-ink-400">暂无记录</div>
      </div>
    </div>

    <div class="card p-5">
      <h2 class="text-[15px] font-semibold text-ink-800">账号与数据</h2>
      <div class="mt-3 flex flex-wrap gap-2">
        <button class="btn-outline text-[12px]" @click="exportData">导出我的数据（JSON）</button>
        <span class="tag">存储配额 {{ user.profile?.storage_quota_mb || 512 }} MB</span>
        <button class="btn-danger ml-auto text-[12px]" @click="deactivate">注销账号</button>
      </div>
      <div class="mt-3 flex flex-wrap gap-1.5">
        <span v-for="r in user.permissions" :key="r" class="tag tag-brand font-mono">{{ r }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../api'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'
import { formatTime } from '../utils/format'

const user = useUserStore()
const app = useAppStore()
const router = useRouter()
const avatarInput = ref(null)
const username = ref('')
const form = reactive({ nickname: '', email: '', phone: '', bio: '' })
const pwd = reactive({ old_password: '', new_password: '', confirm: '' })
const history = ref([])

async function loadProfile() {
  await user.fetchProfile()
  const p = user.profile || {}
  username.value = p.username || ''
  Object.assign(form, { nickname: p.nickname || '', email: p.email || '', phone: p.phone || '', bio: p.bio || '' })
}
async function loadHistory() {
  history.value = (await authApi.loginHistory()).list || []
}
async function saveProfile() {
  await authApi.updateProfile(form)
  await user.fetchProfile()
  app.toastMsg('资料已保存', 'success')
}
async function saveUsername() {
  await authApi.changeUsername(username.value.trim())
  await loadProfile()
  app.toastMsg('用户名已修改', 'success')
}
async function uploadAvatar(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('avatar', file)
  await authApi.uploadAvatar(fd)
  await user.fetchProfile()
  app.toastMsg('头像已更新', 'success')
}
async function removeAvatar() {
  await authApi.deleteAvatar()
  await user.fetchProfile()
}
async function changePassword() {
  if (pwd.new_password !== pwd.confirm) return app.toastMsg('两次密码不一致', 'error')
  await authApi.changePassword({ old_password: pwd.old_password, new_password: pwd.new_password })
  app.toastMsg('密码已修改，请重新登录', 'success')
  setTimeout(async () => { await user.logout(); router.push('/login') }, 1200)
}
async function exportData() {
  const data = await authApi.exportData()
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'my-data.json'; a.click()
  URL.revokeObjectURL(url)
}
async function deactivate() {
  const pw = prompt('注销后账号将被禁用，如需继续请输入登录密码：')
  if (pw === null) return
  await authApi.deactivate(pw)
  app.toastMsg('账号已注销', 'success')
  await user.logout()
  router.push('/login')
}
onMounted(() => { loadProfile(); loadHistory() })
</script>
