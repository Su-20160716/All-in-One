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
            <input v-model="form.password" type="password" class="input" placeholder="至少 6 位" required @input="checkStrength" />
            <!-- #50 注册密码强度条 -->
            <div v-if="mode === 'register' && form.password" class="mt-1.5 flex gap-1">
              <div v-for="i in 5" :key="i" class="h-1 flex-1 rounded" :class="i <= pwdScore ? strengthColor : 'bg-ink-100'"></div>
            </div>
            <div v-if="mode === 'register' && form.password" class="mt-1 text-[11px] text-ink-400">强度：{{ strengthLabel }}</div>
          </div>
          <!-- #52 邀请码 -->
          <div v-if="mode === 'register'">
            <label class="mb-1 block text-[12px] font-medium text-ink-600">邀请码（选填）</label>
            <input v-model="form.invite_code" class="input" placeholder="如有邀请码请输入" />
          </div>
          <!-- #F615 两步验证（TOTP）验证码输入 -->
          <div v-if="mode === 'login' && twoFa.required">
            <label class="mb-1 block text-[12px] font-medium text-ink-600">两步验证码（6 位动态口令）</label>
            <input v-model="twoFa.code" class="input tracking-[0.4em]" inputmode="numeric" maxlength="6"
                   placeholder="000000" autocomplete="one-time-code" required />
            <div class="mt-1 flex items-center justify-between text-[11px] text-ink-400">
              <span>打开验证器 App（Google Authenticator / Authy 等）读取 6 位数字</span>
              <button type="button" class="text-brand-600 hover:underline" @click="resetTwoFa">返回登录</button>
            </div>
          </div>
          <button type="submit" class="btn-primary w-full py-2" :disabled="loading">
            {{ loading ? '处理中…' : twoFa.required && mode === 'login' ? '验 证' : mode === 'login' ? '登 录' : '注 册' }}
          </button>
        </form>
        <div v-if="error" class="mt-3 rounded-control px-3 py-2 text-[12px]"
             :class="locked ? 'bg-amber-50 text-amber-700' : 'bg-rose-50 text-rose-600'">
          {{ error }}
          <div v-if="locked" class="mt-1 text-[11px] opacity-80">
            #F626 登录失败保护：同账号连续 5 次失败将锁定 10 分钟，失败记录可在个人中心的登录历史中查看。
          </div>
        </div>
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
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { authApi } from '../api'
import { useUserStore } from '../stores/user'
import { useAppStore } from '../stores/app'

const router = useRouter()
const user = useUserStore()
const app = useAppStore()
const mode = ref('login')
const loading = ref(false)
const error = ref('')
const locked = ref(false)
const form = reactive({ username: '', password: '', nickname: '', invite_code: '' })
// #F615 两步验证状态：后端返回 twofa_required 时切换到验证码输入
const twoFa = reactive({ required: false, code: '' })
const pwdScore = ref(0)

const strengthLabel = computed(() => ['', '弱', '一般', '中等', '强', '很强'][pwdScore.value])
const strengthColor = computed(() => ['', 'bg-rose-400', 'bg-amber-400', 'bg-amber-400', 'bg-emerald-400', 'bg-emerald-500'][pwdScore.value])

function checkStrength() {
  const p = form.password
  if (!p) { pwdScore.value = 0; return }
  let s = 0
  if (p.length >= 8) s++
  if (/[A-Z]/.test(p)) s++
  if (/[a-z]/.test(p)) s++
  if (/\d/.test(p)) s++
  if (/[^A-Za-z0-9]/.test(p)) s++
  pwdScore.value = s
}

function toggle() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
  locked.value = false
  twoFa.required = false
  twoFa.code = ''
}

function resetTwoFa() {
  twoFa.required = false
  twoFa.code = ''
  error.value = ''
}

async function submit() {
  loading.value = true
  error.value = ''
  locked.value = false
  try {
    if (mode.value === 'register') {
      await user.register({ ...form })
    } else {
      const res = await authApi.login({
        username: form.username,
        password: form.password,
        ...(twoFa.required ? { totp_code: twoFa.code } : {}),
      })
      if (res && res.twofa_required) {
        // #F615 账号已开启两步验证：不发令牌，先要验证码
        twoFa.required = true
        twoFa.code = ''
        loading.value = false
        return
      }
      // 手动落令牌（与 stores/user.js login() 行为一致）
      user.setTokens(res.access, res.refresh)
      user.setProfile(res.user)
      await user.fetchPermissions()
    }
    app.initWs()
    app.fetchUnread()
    router.push('/dashboard')
  } catch (e) {
    error.value = e.message
    // #F626 锁定提示（后端 code=1016 的文案含“锁定”）
    locked.value = /锁定|连续\s*5\s*次/.test(e.message || '')
    if (locked.value) twoFa.required = false
  } finally {
    loading.value = false
  }
}
</script>
