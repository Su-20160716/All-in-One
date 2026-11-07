<template>
  <div class="min-h-screen bg-ink-50 p-6">
    <div v-if="loading" class="grid h-64 place-items-center text-ink-400">加载中…</div>
    <!-- 282：设了口令的分享链接先校验口令 -->
    <div v-else-if="needPassword" class="mx-auto mt-20 max-w-md text-center">
      <div class="text-[40px]">🔒</div>
      <div class="mt-2 text-[15px] font-semibold text-ink-700">该看板已设置访问口令</div>
      <div class="mt-1 text-[12px] text-ink-400">请输入口令后查看只读看板</div>
      <div class="mt-4 space-y-2 rounded-control bg-white p-3 text-left shadow-card">
        <input
          v-model="password"
          type="password"
          class="input"
          placeholder="访问口令"
          autocomplete="current-password"
          @keyup.enter="verify"
        />
        <button class="btn-primary w-full" :disabled="verifying" @click="verify">
          {{ verifying ? '校验中…' : '验证口令' }}
        </button>
        <div v-if="error" class="text-[12px] text-rose-500">{{ error }}</div>
      </div>
    </div>
    <div v-else-if="error" class="mx-auto mt-20 max-w-md text-center">
      <div class="text-[40px]">🔗</div>
      <div class="mt-2 text-[15px] font-semibold text-ink-700">{{ error }}</div>
      <div class="mt-1 text-[12px] text-ink-400">链接可能已失效或被撤销</div>
      <!-- #162 错误态给出重试与可复制的分享链接，弱网不至于一直干等 -->
      <div class="mt-4 flex items-center gap-2 rounded-control bg-white p-2 text-left shadow-card">
        <input :value="shareLink" readonly class="input flex-1 py-1 text-[12px]" aria-label="分享链接" />
        <button class="btn-outline shrink-0 text-[12px]" @click="copyLink">复制</button>
      </div>
      <div class="mt-3 flex justify-center gap-2">
        <button class="btn-primary" :disabled="loading" @click="fetchBoard">重试</button>
        <span v-if="copied" class="self-center text-[12px] text-emerald-600">链接已复制</span>
      </div>
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
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { API_URL, shareUrl } from '../../api/base'

const route = useRoute()
const project = ref({})
const boards = ref([])
const loading = ref(true)
const error = ref('')
const copied = ref(false)
const shareLink = computed(() => shareUrl(route.params.token))
// 282：口令校验拿到的短期访问票据，仅存内存
const accessKey = ref('')
const needPassword = ref(false)
const password = ref('')
const verifying = ref(false)

async function fetchBoard() {
  loading.value = true
  error.value = ''
  try {
    // F3：走 /api/share/board/*（前端不再代理 /share 前缀）；#162 加超时，弱网快速落到错误态
    const params = accessKey.value ? { access_key: accessKey.value } : {}
    const res = await axios.get(`${API_URL}/share/board/${route.params.token}/`, { timeout: 15000, params })
    project.value = res.data.project
    boards.value = res.data.boards || []
    needPassword.value = false
  } catch (e) {
    const status = e?.response?.status
    const data = e?.response?.data || {}
    if (status === 401 && data.need_password) {
      // 282：需要口令时展示口令输入而不是「链接无效」
      needPassword.value = true
      error.value = ''
    } else if (status === 429) {
      // 口令错误次数过多的按 IP 锁定
      error.value = data.message || '访问过于频繁，请稍后再试'
      needPassword.value = Boolean(data.need_password) || needPassword.value
    } else if (status === 404 || status === 410) {
      error.value = data.message || '分享链接无效'
    } else if (e?.code === 'ECONNABORTED') {
      error.value = '请求超时，请检查网络后重试'
    } else {
      error.value = data.message || '分享链接无效'
    }
  } finally {
    loading.value = false
  }
}

async function verify() {
  if (!password.value) {
    error.value = '请输入访问口令'
    return
  }
  verifying.value = true
  error.value = ''
  try {
    const res = await axios.post(
      `${API_URL}/share/board/${route.params.token}/verify/`,
      { password: password.value },
      { timeout: 15000 }
    )
    accessKey.value = res.data.access_key || ''
    password.value = ''
    needPassword.value = false
    await fetchBoard()
  } catch (e) {
    const status = e?.response?.status
    const data = e?.response?.data || {}
    error.value = data.message || (status === 403 ? '口令不正确' : '验证失败，请稍后再试')
  } finally {
    verifying.value = false
  }
}

async function copyLink() {
  try {
    await navigator.clipboard.writeText(shareLink.value)
    copied.value = true
  } catch {
    // 剪贴板不可用时不阻断，用户可手动选中输入框里的链接
  }
}

onMounted(fetchBoard)
</script>
