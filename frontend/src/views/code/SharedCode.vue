<script setup>
/**
 * 代码分享页（公开，免登录）
 *
 * 路由：/code/share/:token
 * 数据：GET /api/share/code/<token>/  —— 后端唯一免鉴权接口，严格只读
 *
 * 页面特点：
 * - 不依赖 AppShell / 登录态，任何人都能打开
 * - 只读渲染代码（CodeMirror readonly），可复制、可下载（由后端 allow_download 控制）
 * - 若后端 allow_run 为 true，提供「在线运行」按钮（同样走免登录的公开执行通道）
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import codeApi from '../../api/code.js'
// #161 运行请求走统一 request 实例（带超时/取消能力），不再用裸 axios
import request from '../../api/request.js'

// 公开执行通道也需要上限：后端单次执行 30s，留一点编译余量
const RUN_TIMEOUT = 45000

const route = useRoute()
const token = computed(() => route.params.token)

const loading = ref(true)
const error = ref('')
const data = ref(null)

// 运行态
const running = ref(false)
const runResult = ref(null)
const runError = ref('')
const stdin = ref('')
const showStdin = ref(false)

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await codeApi.publicShare(token.value)
    // 裸 axios 返回的是完整响应体 {ok, data}
    if (res && res.ok === false) {
      error.value = res.error || '分享链接不可用'
    } else {
      data.value = (res && res.data) || res
    }
  } catch (e) {
    const status = e?.response?.status
    if (status === 404) error.value = '分享链接不存在或已被撤销'
    else if (status === 410) error.value = '分享链接已过期'
    else error.value = e?.response?.data?.error || e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(data.value?.code || '')
    copied.value = true
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    // 剪贴板不可用时降级：选中文本让用户自己 Ctrl+C
    copyFallback.value = true
    setTimeout(() => (copyFallback.value = false), 3000)
  }
}
const copied = ref(false)
const copyFallback = ref(false)

// #270 保存到我的片段库（需登录；未登录先去登录页）
const cloneBusy = ref(false)
const cloned = ref(false)
const cloneNotice = ref('')

async function saveToMySnippets() {
  if (!localStorage.getItem('access_token')) {
    window.location.href = '/login'
    return
  }
  if (cloneBusy.value) return
  cloneBusy.value = true
  cloneNotice.value = ''
  try {
    const res = await codeApi.cloneShare(token.value)
    cloned.value = true
    cloneNotice.value = `已保存为片段「${res?.snippet?.title || ''}」，可在代码工坊的片段库里查看`
  } catch (e) {
    cloneNotice.value = e?.response?.data?.error || e?.message || '保存失败，请稍后重试'
  } finally {
    cloneBusy.value = false
  }
}

function download() {
  const d = data.value
  if (!d) return
  const blob = new Blob([d.code || ''], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${d.title || 'shared'}.${extOf(d.language)}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function extOf(lang) {
  const map = {
    python: 'py', javascript: 'js', typescript: 'ts', bash: 'sh', c: 'c', cpp: 'cpp',
    go: 'go', rust: 'rs', java: 'java', php: 'php', ruby: 'rb', sql: 'sql',
    lua: 'lua', r: 'R', perl: 'pl',
  }
  return map[lang] || 'txt'
}

// 在途运行请求的取消句柄（组件卸载 / 重复点击时 abort）
let runAbort = null

async function runShared() {
  const d = data.value
  if (!d || running.value) return
  // #161 每次运行独立控制器：重复点击先取消上一次，卸载时整体 abort
  runAbort?.abort()
  const controller = new AbortController()
  runAbort = controller
  running.value = true
  runResult.value = null
  runError.value = ''
  try {
    // 只传 stdin —— 后端永远执行分享里的那份代码，不接受客户端替换代码
    const res = await request.post(
      `/share/code/${token.value}/run/`,
      { stdin: stdin.value },
      { timeout: RUN_TIMEOUT, signal: controller.signal },
    )
    if (controller.signal.aborted) return
    if (res && res.ok === false) runError.value = res.error || '执行失败'
    else runResult.value = res?.data || res
  } catch (e) {
    // 主动取消（重复点击/离开页面）不当成错误
    if (controller.signal.aborted || e?.code === 'ERR_CANCELED') return
    runError.value = e?.response?.data?.error || e?.message || '执行失败'
  } finally {
    if (runAbort === controller) {
      runAbort = null
      running.value = false
    }
  }
}

// 卸载时中断在途运行，避免组件销毁后仍回写结果
onBeforeUnmount(() => {
  runAbort?.abort()
  runAbort = null
})


const statusText = computed(() => {
  const r = runResult.value
  if (!r) return ''
  if (r.status === 'ok') return `执行成功 · ${r.duration_ms || 0} ms`
  if (r.status === 'timeout') return '执行超时'
  if (r.status === 'error') return `运行出错（退出码 ${r.exit_code}）`
  if (r.status === 'unavailable') return '运行时不可用'
  return r.status || ''
})

const statusClass = computed(() => {
  const s = runResult.value?.status
  if (s === 'ok') return 'text-emerald-600'
  if (s === 'unavailable') return 'text-ink-400'
  return 'text-rose-600'
})
</script>

<template>
  <div class="min-h-screen bg-ink-50 px-4 py-6 sm:px-8">
    <div class="mx-auto max-w-5xl">
      <!-- 加载中 -->
      <div v-if="loading" class="card flex items-center justify-center py-20 text-ink-400">
        正在加载分享内容…
      </div>

      <!-- 错误 -->
      <div v-else-if="error" class="card py-16 text-center">
        <div class="mb-2 text-4xl">🔗</div>
        <div class="mb-1 text-lg font-semibold text-ink-900">打不开</div>
        <p class="text-sm text-ink-500">{{ error }}</p>
        <p class="mt-4 text-xs text-ink-400">分享链接可能已被撤销、过期，或从未存在过。</p>
      </div>

      <!-- 正常渲染 -->
      <template v-else-if="data">
        <div class="card mb-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="min-w-0">
              <h1 class="truncate text-lg font-semibold text-ink-900">
                {{ data.title || '共享代码' }}
              </h1>
              <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-500">
                <span class="tag">{{ data.language }}</span>
                <span>{{ data.lines }} 行</span>
                <span class="tag-brand">只读分享</span>
                <span v-if="data.kind === 'snippet'">片段</span>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <button class="btn-outline" @click="copyCode">
                {{ copied ? '已复制 ✓' : '复制代码' }}
              </button>
              <button v-if="data.allow_download" class="btn-outline" @click="download">
                下载
              </button>
              <button class="btn-outline" :disabled="cloneBusy || cloned" @click="saveToMySnippets">
                {{ cloned ? '已保存到片段库 ✓' : cloneBusy ? '保存中…' : '保存到我的片段库' }}
              </button>
              <button
                v-if="data.allow_run"
                class="btn-primary"
                :disabled="running"
                @click="runShared"
              >
                {{ running ? '执行中…' : '▶ 运行' }}
              </button>
            </div>
          </div>
          <p v-if="cloneNotice" class="mt-2 text-xs text-ink-500">{{ cloneNotice }}</p>
          <p v-if="copyFallback" class="mt-2 text-xs text-amber-600">
            浏览器拒绝了剪贴板访问，请手动选中代码复制。
          </p>
        </div>

        <!-- 代码区（#190 公开页只读渲染，不加载完整 CodeMirror） -->
        <div class="card overflow-hidden p-0">
          <pre class="h-[60vh] overflow-auto bg-ink-900 px-4 py-3 font-mono text-[13px] leading-relaxed text-ink-100"><code>{{ data.code || '' }}</code></pre>
        </div>

        <!-- 运行区 -->
        <div v-if="data.allow_run" class="card mt-4">
          <div class="mb-2 flex items-center justify-between">
            <div class="text-sm font-semibold text-ink-900">在线运行</div>
            <button class="btn-ghost text-xs" @click="showStdin = !showStdin">
              {{ showStdin ? '收起输入' : '标准输入' }}
            </button>
          </div>

          <textarea
            v-if="showStdin"
            v-model="stdin"
            class="input mb-3 h-24 w-full font-mono text-xs"
            placeholder="程序的标准输入（可选）"
          />

          <div v-if="running" class="py-6 text-center text-sm text-ink-400">正在执行…</div>

          <div v-else-if="runError" class="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {{ runError }}
          </div>

          <div v-else-if="runResult">
            <div class="mb-2 text-xs font-medium" :class="statusClass">{{ statusText }}</div>
            <pre
              v-if="runResult.stdout"
              class="max-h-72 overflow-auto rounded bg-ink-900 px-3 py-2 font-mono text-xs text-ink-100 whitespace-pre-wrap"
            >{{ runResult.stdout }}</pre>
            <pre
              v-if="runResult.stderr"
              class="mt-2 max-h-72 overflow-auto rounded bg-rose-950 px-3 py-2 font-mono text-xs text-rose-100 whitespace-pre-wrap"
            >{{ runResult.stderr }}</pre>
            <div
              v-if="!runResult.stdout && !runResult.stderr"
              class="rounded bg-ink-100 px-3 py-2 text-sm text-ink-500"
            >
              程序没有输出。
            </div>
            <div v-if="runResult.truncated" class="mt-2 text-xs text-amber-600">
              输出过长，已截断。
            </div>
          </div>

          <div v-else class="text-xs text-ink-400">点击右上角「运行」执行这段代码。</div>
        </div>

        <p class="mt-6 text-center text-xs text-ink-400">
          由代码工坊生成 · 分享内容仅读，不会暴露作者的账号信息
        </p>
      </template>
    </div>
  </div>
</template>
