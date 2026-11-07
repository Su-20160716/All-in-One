<template>
  <!-- ================= S26 #420 开发者门户 ================= -->
  <div class="mx-auto max-w-6xl space-y-4">
    <div class="card flex flex-wrap items-center justify-between gap-2 p-4">
      <div>
        <h2 class="text-[15px] font-semibold">开发者门户</h2>
        <p class="mt-0.5 text-[12px] text-ink-500">
          令牌、Webhook 事件订阅、投递记录与接口用量的统一入口。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="summary?.generated_at" class="text-[11px] text-ink-400">
          更新于 {{ formatTime(summary.generated_at) }}
        </span>
        <button class="btn-outline text-[12px]" :disabled="summaryLoading" @click="refreshAll">刷新</button>
      </div>
    </div>

    <!-- 四张汇总卡 -->
    <div v-if="summaryError" class="card flex flex-wrap items-center justify-between gap-2 p-4">
      <span class="text-[12px] text-rose-500">汇总数据加载失败：{{ summaryError }}</span>
      <button class="btn-outline text-[12px]" @click="loadSummary">重试</button>
    </div>
    <div v-else class="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <div v-for="c in summaryCards" :key="c.label" class="card p-4">
        <div class="text-[12px] text-ink-500">{{ c.label }}</div>
        <div class="mt-1 text-[24px] font-bold text-ink-900">
          <span v-if="summaryLoading" class="text-ink-300">--</span>
          <span v-else>{{ c.value }}</span>
        </div>
        <div class="mt-0.5 text-[11px] text-ink-400">{{ c.note }}</div>
      </div>
    </div>

    <!-- Webhook 订阅管理 -->
    <div class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 class="text-[14px] font-semibold">Webhook 事件订阅</h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            事件发生时向回调地址投递带签名的 JSON；签名头
            <code class="font-mono">{{ signatureSpec || 'X-Webhook-Signature' }}</code>。
          </p>
        </div>
        <div class="flex items-center gap-2">
          <span v-if="maxSubs" class="tag">上限 {{ maxSubs }} 个</span>
          <span class="tag" :class="subs.length ? 'tag-brand' : ''">{{ subs.length }} / {{ maxSubs ?? '-' }}</span>
        </div>
      </div>

      <!-- 新建订阅 -->
      <div class="mt-3 rounded-control border border-ink-100 p-3">
        <div class="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
          <input v-model="createForm.url" class="input" placeholder="回调地址，如 https://example.com/hooks/platform" />
          <input v-model="createForm.events" class="input font-mono" placeholder="事件，逗号分隔；* = 全部" />
          <button class="btn-primary text-[12px]" :disabled="creating" @click="createSub">
            {{ creating ? '创建中…' : '＋ 新建订阅' }}
          </button>
        </div>
        <div class="mt-2 flex flex-wrap items-center gap-1.5">
          <span class="text-[11px] text-ink-400">快捷事件：</span>
          <button v-for="e in eventSuggestions" :key="e" class="tag" :class="hasEvent(e) ? 'tag-brand' : ''"
                  @click="toggleEvent(e)">{{ e }}</button>
          <label class="ml-auto flex items-center gap-1.5 text-[11px] text-ink-500">
            <input v-model="createForm.active" type="checkbox" /> 创建后立即启用
          </label>
        </div>
      </div>

      <!-- 一次性 secret -->
      <div v-if="newSecret" class="mt-3 rounded-control border border-amber-200 bg-amber-50 p-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="text-[12px] font-medium text-amber-700">签名密钥仅本次完整返回，请立即保存</span>
          <button class="btn-ghost text-[12px]" @click="newSecret = null">我已保存</button>
        </div>
        <div class="mt-1 break-all font-mono text-[12px] text-ink-800">{{ newSecret.secret }}</div>
        <div class="mt-1 truncate text-[11px] text-ink-500">{{ newSecret.url }}</div>
        <button class="btn-outline mt-2 text-[12px]" @click="copyText(newSecret.secret, '签名密钥已复制')">复制密钥</button>
      </div>

      <!-- 订阅列表 -->
      <div v-if="subsLoading" class="py-8 text-center text-[12px] text-ink-400">订阅加载中…</div>
      <div v-else-if="subsError" class="mt-3 flex items-center justify-between rounded-control border border-rose-100 bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span>订阅加载失败：{{ subsError }}</span>
        <button class="font-medium underline" @click="loadSubs">重试</button>
      </div>
      <div v-else class="mt-3 space-y-2">
        <div v-for="s in subs" :key="s.id" class="rounded-control border border-ink-100 px-3 py-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="break-all text-[13px] text-ink-800">{{ s.url }}</span>
                <span class="tag" :class="s.active ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                  {{ s.active ? '启用中' : '已停用' }}
                </span>
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-1">
                <span v-if="!(s.events || []).length" class="tag tag-brand">全部事件</span>
                <span v-for="e in s.events || []" :key="e" class="tag font-mono">{{ e }}</span>
                <span class="ml-1 font-mono text-[10px] text-ink-400">secret {{ s.secret_preview || '-' }}</span>
              </div>
              <div class="mt-0.5 text-[11px] text-ink-400">创建于 {{ formatTime(s.created_at) }}</div>
            </div>
            <div class="flex shrink-0 flex-wrap items-center gap-1">
              <button class="btn-ghost text-[12px] text-brand-600" :disabled="verifyBusy[s.id]" @click="verifySub(s)">
                {{ verifyBusy[s.id] ? '自测中…' : '签名自测' }}
              </button>
              <button class="btn-ghost text-[12px]" :disabled="toggling[s.id]" @click="toggleSub(s)">
                {{ s.active ? '停用' : '启用' }}
              </button>
              <button class="btn-ghost text-[12px] text-rose-500" :disabled="deleting[s.id]" @click="removeSub(s)">删除</button>
            </div>
          </div>
          <div v-if="verifyResult[s.id]" class="mt-2 rounded-control border border-emerald-100 bg-emerald-50/60 px-3 py-2 text-[11px]">
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-emerald-700">{{ verifyResult[s.id].message || '签名已生成' }}</span>
              <button class="text-emerald-600 hover:underline" @click="clearVerify(s.id)">关闭</button>
            </div>
            <div class="mt-1 break-all font-mono text-ink-700">
              {{ verifyResult[s.id].header_name }}: {{ verifyResult[s.id].signature }}
            </div>
            <div class="text-ink-500">X-Webhook-Timestamp: {{ verifyResult[s.id].timestamp }}</div>
            <details class="mt-1">
              <summary class="cursor-pointer text-ink-500">查看样例请求体</summary>
              <pre class="mt-1 whitespace-pre-wrap break-all font-mono text-[10px] text-ink-500">{{ verifyResult[s.id].body }}</pre>
            </details>
          </div>
        </div>
        <div v-if="!subs.length" class="py-6 text-center text-[12px] text-ink-400">
          还没有 Webhook 订阅，填写回调地址后在上方创建
        </div>
      </div>
    </div>

    <!-- 投递记录 -->
    <div class="card p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 class="text-[14px] font-semibold">投递记录</h3>
          <p class="mt-0.5 text-[11px] text-ink-400">失败投递会指数退避自动重试；也可手动重试最近一条。</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <select v-model="deliveryFilter.status" class="input w-28 text-[12px]" @change="loadDeliveries">
            <option value="">全部状态</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="pending">待投递</option>
          </select>
          <select v-model.number="deliveryFilter.limit" class="input w-24 text-[12px]" @change="loadDeliveries">
            <option :value="20">最近 20</option>
            <option :value="50">最近 50</option>
            <option :value="100">最近 100</option>
          </select>
          <button class="btn-outline text-[12px]" :disabled="deliveriesLoading" @click="loadDeliveries">刷新</button>
        </div>
      </div>

      <div v-if="deliveriesLoading" class="py-8 text-center text-[12px] text-ink-400">投递记录加载中…</div>
      <div v-else-if="deliveriesError" class="mt-3 flex items-center justify-between rounded-control border border-rose-100 bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span>投递记录加载失败：{{ deliveriesError }}</span>
        <button class="font-medium underline" @click="loadDeliveries">重试</button>
      </div>
      <div v-else class="mt-3 overflow-x-auto">
        <table class="w-full min-w-[760px]">
          <thead class="border-b border-ink-100 bg-ink-50/50">
            <tr>
              <th class="th">时间</th>
              <th class="th">事件</th>
              <th class="th">回调地址</th>
              <th class="th">状态</th>
              <th class="th">次数</th>
              <th class="th">响应码</th>
              <th class="th">耗时</th>
              <th class="th">错误</th>
              <th class="th">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="d in deliveries" :key="d.id" class="hover:bg-ink-50/40">
              <td class="td whitespace-nowrap text-ink-500">{{ formatTime(d.created_at) }}</td>
              <td class="td"><span class="tag font-mono">{{ d.event || '-' }}</span></td>
              <td class="td max-w-[220px] truncate text-ink-600">{{ d.url || '-' }}</td>
              <td class="td">
                <span class="tag" :class="statusClass[d.status] || ''">{{ statusText[d.status] || d.status }}</span>
              </td>
              <td class="td">{{ d.attempts ?? 0 }}</td>
              <td class="td">{{ d.response_code ?? '-' }}</td>
              <td class="td">{{ d.latency_ms != null ? d.latency_ms + ' ms' : '-' }}</td>
              <td class="td max-w-[200px] truncate text-[11px] text-rose-500">{{ d.error || '-' }}</td>
              <td class="td">
                <button v-if="d.status === 'failed'" class="btn-ghost text-[12px] text-brand-600"
                        :disabled="retrying[d.id]" @click="retryDelivery(d)">
                  {{ retrying[d.id] ? '重试中…' : '重试' }}
                </button>
                <span v-else class="text-[11px] text-ink-300">-</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!deliveries.length" class="py-10 text-center text-[12px] text-ink-400">
          暂无投递记录，订阅被事件触发后会在此展示
        </div>
        <div v-if="deliveries.length" class="mt-2 text-[11px] text-ink-400">当前展示 {{ deliveries.length }} 条</div>
      </div>
    </div>

    <!-- 开发者资源 -->
    <div class="card p-4">
      <h3 class="text-[14px] font-semibold">开发者资源</h3>
      <div class="mt-3 grid gap-2 sm:grid-cols-3">
        <button class="rounded-control border border-ink-100 p-3 text-left transition-colors hover:border-brand-400" @click="go('/profile')">
          <div class="text-[13px] font-medium text-ink-800">访问令牌（PAT）</div>
          <div class="mt-1 text-[11px] text-ink-400">创建带作用域的令牌，查看近 30 天用量</div>
        </button>
        <button class="rounded-control border border-ink-100 p-3 text-left transition-colors hover:border-brand-400" @click="go('/admin/stats')">
          <div class="flex items-center gap-1.5">
            <span class="text-[13px] font-medium text-ink-800">接口用量报表</span>
            <span v-if="!user.isAdmin" class="tag">仅管理员</span>
          </div>
          <div class="mt-1 text-[11px] text-ink-400">按应用查看调用量、慢接口与错误率</div>
        </button>
        <a class="rounded-control border border-ink-100 p-3 transition-colors hover:border-brand-400" :href="docsUrl" target="_blank" rel="noopener">
          <div class="text-[13px] font-medium text-ink-800">OpenAPI 文档</div>
          <div class="mt-1 text-[11px] text-ink-400">/api/docs/ · 在浏览器新标签打开</div>
        </a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { developerxApi } from '../api/developerx'
import { apiUrl } from '../api/base'
import { useAppStore } from '../stores/app'
import { useUserStore } from '../stores/user'
import { formatNumber, formatTime } from '../utils/format'

const app = useAppStore()
const user = useUserStore()
const router = useRouter()

const docsUrl = apiUrl('/api/docs/')

const statusText = { pending: '待投递', success: '成功', failed: '失败' }
const statusClass = {
  pending: 'bg-amber-50 text-amber-700',
  success: 'bg-emerald-50 text-emerald-600',
  failed: 'bg-rose-50 text-rose-600',
}

// ---------------- #420 汇总 ----------------
const summary = ref(null)
const summaryLoading = ref(true)
const summaryError = ref('')

const summaryCards = computed(() => {
  const s = summary.value || {}
  const tokens = s.tokens || {}
  const subInfo = s.subscriptions || {}
  const deliveries = s.deliveries || {}
  return [
    {
      label: '令牌数',
      value: `${tokens.active ?? 0} / ${tokens.total ?? 0}`,
      note: tokens.last_used_at ? `最近使用 ${formatTime(tokens.last_used_at)}` : '暂无使用记录',
    },
    {
      label: '近 7 天调用',
      value: formatNumber(s.calls_7d ?? 0),
      note: 'PAT 接口调用总量',
    },
    {
      label: 'Webhook 订阅',
      value: `${subInfo.active ?? 0} / ${subInfo.total ?? 0}`,
      note: '启用 / 总数',
    },
    {
      label: '失败投递',
      value: formatNumber(deliveries.failed ?? 0),
      note: `近 7 天 ${formatNumber(deliveries.failed_7d ?? 0)} 次 · 成功率 ${deliveries.success_rate ?? 100}%`,
    },
  ]
})

async function loadSummary() {
  summaryLoading.value = true
  summaryError.value = ''
  try {
    summary.value = await developerxApi.summary()
  } catch (e) {
    summaryError.value = e?.message || '加载失败'
  } finally {
    summaryLoading.value = false
  }
}

// ---------------- #411 订阅 ----------------
const subs = ref([])
const subsLoading = ref(false)
const subsError = ref('')
const eventSuggestions = ref([])
const maxSubs = ref(null)
const signatureSpec = ref('')
const createForm = reactive({ url: '', events: '*', active: true })
const creating = ref(false)
const newSecret = ref(null)
const toggling = ref({})
const deleting = ref({})

async function loadSubs() {
  subsLoading.value = true
  subsError.value = ''
  try {
    const r = await developerxApi.subscriptions()
    subs.value = r.list || []
    eventSuggestions.value = r.events || []
    maxSubs.value = r.max ?? null
    signatureSpec.value = r.signature || ''
  } catch (e) {
    subs.value = []
    subsError.value = e?.message || '加载失败'
  } finally {
    subsLoading.value = false
  }
}

function splitEvents(raw) {
  return String(raw || '').replace(/，/g, ',').split(',').map((x) => x.trim()).filter(Boolean)
}

function hasEvent(e) {
  return splitEvents(createForm.events).includes(e)
}

function toggleEvent(e) {
  const list = splitEvents(createForm.events)
  const idx = list.indexOf(e)
  if (idx >= 0) list.splice(idx, 1)
  else list.push(e)
  createForm.events = list.length ? list.join(',') : '*'
}

async function createSub() {
  const url = createForm.url.trim()
  if (!url) return app.toastMsg('请填写回调地址', 'error')
  creating.value = true
  try {
    const events = splitEvents(createForm.events).join(',') || '*'
    const r = await developerxApi.createSubscription({ url, events, active: createForm.active })
    const sub = r.subscription || {}
    if (sub.secret) newSecret.value = { url: sub.url || url, secret: sub.secret }
    createForm.url = ''
    createForm.events = '*'
    createForm.active = true
    await Promise.all([loadSubs(), loadSummary(), loadDeliveries()])
    app.toastMsg('订阅已创建，请保存签名密钥', 'success')
  } catch (e) {
    app.toastMsg(e?.message || '创建失败', 'error')
  } finally {
    creating.value = false
  }
}

async function toggleSub(s) {
  if (toggling.value[s.id]) return
  toggling.value[s.id] = true
  try {
    await developerxApi.updateSubscription(s.id, { active: !s.active })
    await loadSubs()
    app.toastMsg(s.active ? '订阅已停用' : '订阅已启用', 'success')
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    toggling.value[s.id] = false
  }
}

async function removeSub(s) {
  if (!confirm(`确定删除订阅「${s.url}」？其投递记录也会一并删除。`)) return
  deleting.value[s.id] = true
  try {
    await developerxApi.deleteSubscription(s.id)
    delete verifyResult[s.id]
    if (newSecret.value?.url === s.url) newSecret.value = null
    await Promise.all([loadSubs(), loadSummary(), loadDeliveries()])
    app.toastMsg('订阅已删除', 'success')
  } catch (e) {
    app.toastMsg(e?.message || '删除失败', 'error')
  } finally {
    deleting.value[s.id] = false
  }
}

// ---------------- #413 签名自测 ----------------
const verifyBusy = ref({})
const verifyResult = reactive({})

async function verifySub(s) {
  if (verifyBusy.value[s.id]) return
  verifyBusy.value[s.id] = true
  try {
    verifyResult[s.id] = await developerxApi.verifyWebhook({ subscription_id: s.id })
    app.toastMsg(verifyResult[s.id]?.message || '签名已生成', 'success')
  } catch (e) {
    delete verifyResult[s.id]
    app.toastMsg(e?.message || '签名自测失败', 'error')
  } finally {
    verifyBusy.value[s.id] = false
  }
}

function clearVerify(id) {
  delete verifyResult[id]
}

// ---------------- #412 投递记录 ----------------
const deliveries = ref([])
const deliveriesLoading = ref(false)
const deliveriesError = ref('')
const deliveryFilter = reactive({ status: '', limit: 20 })
const retrying = ref({})

async function loadDeliveries() {
  deliveriesLoading.value = true
  deliveriesError.value = ''
  try {
    const params = { limit: deliveryFilter.limit }
    if (deliveryFilter.status) params.status = deliveryFilter.status
    const r = await developerxApi.deliveries(params)
    deliveries.value = r.list || []
  } catch (e) {
    deliveries.value = []
    deliveriesError.value = e?.message || '加载失败'
  } finally {
    deliveriesLoading.value = false
  }
}

async function retryDelivery(d) {
  if (retrying.value[d.id]) return
  retrying.value[d.id] = true
  try {
    const r = await developerxApi.retryDelivery(d.id)
    const ok = r.delivery?.status === 'success'
    app.toastMsg(r.message || (ok ? '重试成功' : '重试仍失败'), ok ? 'success' : 'error')
    await Promise.all([loadDeliveries(), loadSummary(), loadSubs()])
  } catch (e) {
    app.toastMsg(e?.message || '重试失败', 'error')
  } finally {
    retrying.value[d.id] = false
  }
}

// ---------------- 通用 ----------------
function go(path) {
  router.push(path)
}

function copyText(text, msg) {
  const done = () => app.toastMsg(msg || '已复制', 'success')
  const fallback = () => {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      done()
    } catch (e) {
      app.toastMsg('复制失败，请手动复制', 'error')
    }
    document.body.removeChild(ta)
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(fallback)
  } else {
    fallback()
  }
}

function refreshAll() {
  loadSummary()
  loadSubs()
  loadDeliveries()
}

onMounted(() => {
  refreshAll()
})
</script>
