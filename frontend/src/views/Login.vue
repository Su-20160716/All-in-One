<template>
  <div class="grid min-h-screen place-items-center bg-ink-900 p-4">
    <div class="grid w-full max-w-4xl overflow-hidden rounded-card bg-white shadow-pop lg:grid-cols-2">
      <div class="hidden flex-col justify-between bg-ink-900 p-8 text-white lg:flex">
        <div>
          <div class="flex items-center gap-2">
            <div class="grid h-9 w-9 place-items-center rounded-control bg-brand-600 text-[16px] font-bold">A</div>
            <span class="text-[16px] font-semibold">全能协作平台</span>
          </div>
          <h1 class="mt-10 text-[26px] font-bold leading-snug">文件 · 笔记 · 看板<br />消息 · 工具 · 后台<br />一个平台全都有</h1>
          <p class="mt-4 text-[13px] leading-relaxed text-ink-400">Vue3 + TailwindCSS + Django DRF + Channels 全栈实践项目，80+ 功能。</p>
        </div>
        <div class="space-y-2 text-[12px] text-ink-500">
          <div class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-brand-400"></span>分片上传 / 断点续传 / 秒传</div>
          <div class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>笔记版本历史与回滚</div>
          <div class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-amber-400"></span>看板拖拽 + 实时通知</div>
        </div>
      </div>
      <div class="p-8">
        <h2 class="text-[20px] font-bold text-ink-900">{{ mode === 'login' ? '欢迎回来' : '创建账号' }}</h2>
        <p class="mt-1 text-[12px] text-ink-500">
          {{ mode === 'login' ? '登录以继续使用平台' : '注册后默认获得普通用户角色' }}
        </p>
        <form class="mt-6 space-y-4" @submit.prevent="submit">
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">用户名</label>
            <input v-model="form.username" class="input" placeholder="请输入用户名" required />
          </div>
          <div v-if="mode === 'register'">
            <label class="mb-1 block text-[12px] font-medium text-ink-600">昵称</label>
            <input v-model="form.nickname" class="input" placeholder="选填" />
          </div>
          <div>
            <label class="mb-1 block text-[12px] font-medium text-ink-600">密码</label>
            <input v-model="form.password" type="password" class="input" placeholder="至少 6 位" required />
          </div>
          <button type="submit" class="btn-primary w-full py-2" :disabled="loading">
            {{ loading ? '处理中…' : mode === 'login' ? '登 录' : '注 册' }}
          </button>
        </form>
        <div v-if="error" class="mt-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ error }}</div>
        <div class="mt-4 text-center text-[12px] text-ink-500">
          {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
          <button class="font-medium text-brand-600 hover:underline" @click="toggle">{{ mode === 'login' ? '立即注册' : '去登录' }}</button>
        </div>
        <div class="mt-4 rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-400">
          演示账号：admin / admin123（管理员）· 也可注册新账号
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'

const router = useRouter()
const user = useUserStore()
const app = useAppStore()
const mode = ref('login')
const loading = ref(false)
const error = ref('')
const form = reactive({ username: '', password: '', nickname: '' })

function toggle() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}

async function submit() {
  loading.value = true
  error.value = ''
  try {
    if (mode.value === 'login') {
      await user.login({ username: form.username, password: form.password })
    } else {
      await user.register({ ...form })
    }
    app.initWs()
    app.fetchUnread()
    router.push('/dashboard')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
</script>
