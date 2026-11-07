<template>
  <div class="space-y-4">
    <div v-if="!forms.length" class="card py-10 text-center text-[12px] text-ink-400">
      暂无可管理分享与模板的表单
    </div>

    <!-- 模板目录 -->
    <SectionCard title="模板目录" subtitle="内置模板与个人模板，一键创建新表单" dense>
      <template #actions>
        <span class="tag">{{ templates.length }} 个模板</span>
        <button class="btn-ghost" type="button" :disabled="templateLoading" @click="loadTemplates">
          {{ templateLoading ? '加载中…' : '刷新' }}
        </button>
      </template>
      <div class="mb-3 flex flex-wrap items-end gap-2">
        <label class="flex min-w-[220px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
          新表单名称（可选）
          <input v-model="templateName" class="input" maxlength="200" placeholder="留空则沿用模板名称" />
        </label>
        <span class="pb-1.5 text-[11px] text-ink-400">创建后进入草稿状态，可继续在设计器中调整字段</span>
      </div>
      <div v-if="templateError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ templateError }}</span>
        <button class="shrink-0 font-medium" type="button" @click="loadTemplates">重试</button>
      </div>
      <div v-else-if="templateLoading && !templates.length" class="py-8 text-center text-[12px] text-ink-400">
        模板加载中…
      </div>
      <div v-else-if="!templates.length" class="py-8 text-center text-[12px] text-ink-400">
        暂无可用模板
      </div>
      <div v-else class="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
        <div v-for="tpl in templates" :key="tpl.id" class="flex flex-col rounded-control border border-ink-100 p-3">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate text-[13px] font-medium text-ink-800">{{ tpl.name }}</p>
              <p class="mt-0.5 line-clamp-2 text-[11px] text-ink-400">{{ tpl.description || '暂无说明' }}</p>
            </div>
            <span class="tag shrink-0">{{ tpl.category || '通用' }}</span>
          </div>
          <div class="mt-2 flex flex-wrap items-center gap-1">
            <span class="tag">{{ formTypeLabel(tpl.form_type) }}</span>
            <span class="tag">{{ tpl.field_count || 0 }} 字段</span>
            <span v-if="tpl.builtin" class="tag bg-brand-50 text-brand-700">内置</span>
            <span class="tag">使用 {{ tpl.usage_count || 0 }}</span>
          </div>
          <button
            class="btn-outline mt-2 w-full !py-1"
            type="button"
            :disabled="creatingTemplateId === tpl.id"
            @click="instantiate(tpl)"
          >
            {{ creatingTemplateId === tpl.id ? '创建中…' : '从模板创建' }}
          </button>
        </div>
      </div>
    </SectionCard>

    <template v-if="forms.length">
      <div class="card p-3">
        <div class="flex flex-wrap items-end gap-2">
          <label class="flex min-w-[260px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
            作用于表单
            <select v-model="dataFormId" class="input" @change="loadShareLinks(); loadWebhooks()">
              <option v-for="form in forms" :key="form.id" :value="form.id">
                {{ form.name }}（{{ form.code }}）
              </option>
            </select>
          </label>
          <span class="pb-1.5 text-[11px] text-ink-400">
            分享链接与 Webhook 投递记录均按当前选择表单过滤
          </span>
        </div>
      </div>

      <!-- 分享链接 -->
      <SectionCard title="分享链接" subtitle="按表单生成带令牌的填报入口，可设密码、有效期与使用上限" dense>
        <template #actions>
          <span class="tag">{{ shareLinks.length }} 条</span>
          <button class="btn-primary !py-1" type="button" :disabled="!dataFormId" @click="openShareModal">
            新建链接
          </button>
          <button class="btn-ghost" type="button" :disabled="shareLoading" @click="loadShareLinks">
            {{ shareLoading ? '加载中…' : '刷新' }}
          </button>
        </template>
        <div v-if="shareError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ shareError }}</span>
          <button class="shrink-0 font-medium" type="button" @click="loadShareLinks">重试</button>
        </div>
        <div v-else-if="shareUnavailable" class="py-8 text-center text-[12px] text-ink-400">
          <p>分享链接接口暂不可用，已降级为空态</p>
          <button class="btn-ghost mt-2" type="button" @click="loadShareLinks">重试</button>
        </div>
        <div v-else-if="shareLoading && !shareLinks.length" class="py-8 text-center text-[12px] text-ink-400">
          加载中…
        </div>
        <div v-else-if="!shareLinks.length" class="py-8 text-center text-[12px] text-ink-400">
          还没有分享链接
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[860px] text-left">
            <thead class="border-b border-ink-100 bg-ink-50/60">
              <tr>
                <th class="th">备注</th>
                <th class="th">令牌</th>
                <th class="th">状态</th>
                <th class="th">使用</th>
                <th class="th">密码</th>
                <th class="th">过期时间</th>
                <th class="th">最后使用</th>
                <th class="th">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="link in shareLinks" :key="link.id" class="hover:bg-ink-50/60">
                <td class="td">{{ link.label || '未备注' }}</td>
                <td class="td">
                  <span class="block max-w-[220px] truncate font-mono text-[11px] text-ink-600">{{ link.token }}</span>
                </td>
                <td class="td">
                  <span class="tag" :class="shareStatusClass(link)">
                    {{ shareStatusLabel(link) }}
                  </span>
                </td>
                <td class="td">
                  {{ link.used_count }} / {{ link.max_uses ? link.max_uses : '不限' }}
                </td>
                <td class="td">{{ link.requires_password ? '需要' : '无' }}</td>
                <td class="td">{{ link.expires_at ? formatDate(link.expires_at, true) : '永不过期' }}</td>
                <td class="td">{{ link.last_used_at ? formatDate(link.last_used_at, true) : '—' }}</td>
                <td class="td">
                  <div class="flex flex-wrap gap-1">
                    <button class="btn-ghost !px-1.5 !py-0.5 !text-[11px]" type="button" @click="copyShareLink(link)">
                      复制链接
                    </button>
                    <button
                      v-if="link.active"
                      class="btn-ghost !px-1.5 !py-0.5 !text-[11px] !text-rose-600"
                      type="button"
                      :disabled="disablingId === link.id"
                      @click="disableShareLink(link)"
                    >
                      {{ disablingId === link.id ? '停用中…' : '停用' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>

      <!-- Webhook -->
      <SectionCard title="Webhook 与投递记录" subtitle="查看当前表单的 Webhook 配置、测试投递并重试失败记录" dense>
        <template #actions>
          <span class="tag">{{ webhooks.length }} 个 Webhook</span>
          <button class="btn-ghost" type="button" :disabled="webhookLoading" @click="loadWebhooks(); loadDeliveries()">
            {{ webhookLoading ? '加载中…' : '刷新' }}
          </button>
        </template>
        <div v-if="webhookError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ webhookError }}</span>
          <button class="shrink-0 font-medium" type="button" @click="loadWebhooks(); loadDeliveries()">重试</button>
        </div>
        <div v-else-if="webhookUnavailable" class="py-8 text-center text-[12px] text-ink-400">
          <p>Webhook 接口暂不可用，已降级为空态</p>
          <button class="btn-ghost mt-2" type="button" @click="loadWebhooks(); loadDeliveries()">重试</button>
        </div>
        <template v-else>
          <div v-if="webhookLoading && !webhooks.length" class="py-8 text-center text-[12px] text-ink-400">
            加载中…
          </div>
          <div v-else-if="!webhooks.length" class="rounded-control bg-ink-50 px-3 py-6 text-center text-[12px] text-ink-400">
            当前表单还没有配置 Webhook
          </div>
          <div v-else class="divide-y divide-ink-50 rounded-control border border-ink-100">
            <div v-for="hook in webhooks" :key="hook.id" class="flex flex-wrap items-center gap-2 px-3 py-2 text-[12px]">
              <span class="tag" :class="hook.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-600'">
                {{ hook.enabled ? '启用' : '停用' }}
              </span>
              <span class="min-w-0 flex-1 truncate font-mono text-[11px] text-ink-700">{{ hook.url }}</span>
              <span class="tag">{{ eventLabel(hook.event) }}</span>
              <span class="tag">失败 {{ hook.failure_count || 0 }}</span>
              <span v-if="hook.last_status" class="tag" :class="deliveryStatusClass(hook.last_status)">
                {{ hook.last_status }}
              </span>
              <span class="text-[11px] text-ink-400">{{ hook.last_delivery_at ? formatDate(hook.last_delivery_at, true) : '未投递' }}</span>
              <button
                class="btn-outline !px-2 !py-0.5 !text-[11px]"
                type="button"
                :disabled="testingHookId === hook.id"
                @click="testWebhook(hook)"
              >
                {{ testingHookId === hook.id ? '测试中…' : '测试投递' }}
              </button>
            </div>
          </div>

          <div class="mt-4">
            <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span class="text-[13px] font-medium text-ink-700">投递记录</span>
              <div class="flex flex-wrap items-center gap-2">
                <select v-model="deliveryStatus" class="input !w-auto !py-1 !text-[11px]" @change="loadDeliveries">
                  <option value="">全部状态</option>
                  <option value="pending">待投递</option>
                  <option value="success">成功</option>
                  <option value="failed">失败</option>
                  <option value="skipped">已跳过</option>
                </select>
                <span class="tag">{{ deliveries.length }} 条</span>
              </div>
            </div>
            <div v-if="deliveryError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
              <span class="min-w-0 flex-1">{{ deliveryError }}</span>
              <button class="shrink-0 font-medium" type="button" @click="loadDeliveries">重试</button>
            </div>
            <div v-else-if="deliveryLoading && !deliveries.length" class="py-6 text-center text-[12px] text-ink-400">
              加载中…
            </div>
            <div v-else-if="!deliveries.length" class="py-6 text-center text-[12px] text-ink-400">
              暂无投递记录
            </div>
            <div v-else class="overflow-x-auto rounded-control border border-ink-100">
              <table class="w-full min-w-[820px] text-left">
                <thead class="border-b border-ink-100 bg-ink-50/60">
                  <tr>
                    <th class="th">ID</th>
                    <th class="th">事件</th>
                    <th class="th">状态</th>
                    <th class="th">尝试</th>
                    <th class="th">响应码</th>
                    <th class="th">耗时</th>
                    <th class="th">创建时间</th>
                    <th class="th">操作</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="row in deliveries" :key="row.id" class="hover:bg-ink-50/60">
                    <td class="td">#{{ row.id }}</td>
                    <td class="td">{{ eventLabel(row.event) }}</td>
                    <td class="td">
                      <span class="tag" :class="deliveryStatusClass(row.status)">{{ deliveryStatusLabel(row.status) }}</span>
                    </td>
                    <td class="td">{{ row.attempt }}</td>
                    <td class="td">{{ row.response_code ?? '—' }}</td>
                    <td class="td">{{ row.duration_ms }} ms</td>
                    <td class="td">{{ formatDate(row.created_at, true) }}</td>
                    <td class="td">
                      <button
                        v-if="row.status === 'failed'"
                        class="btn-ghost !px-1.5 !py-0.5 !text-[11px]"
                        type="button"
                        :disabled="retryingId === row.id"
                        @click="retryDelivery(row)"
                      >
                        {{ retryingId === row.id ? '重试中…' : '重试' }}
                      </button>
                      <span v-else class="text-[11px] text-ink-400">—</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </SectionCard>
    </template>

    <!-- 新建分享链接 -->
    <Modal v-model="shareModalOpen" title="新建分享链接" width="480px">
      <div class="space-y-3">
        <div v-if="shareModalError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ shareModalError }}
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            备注
            <input v-model="shareForm.label" class="input" maxlength="120" placeholder="例如：官网活动入口" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            访问密码
            <input v-model="shareForm.password" class="input" maxlength="128" placeholder="留空表示无密码" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            过期时间
            <input v-model="shareForm.expires_at" class="input" type="datetime-local" />
          </label>
          <label class="flex flex-col gap-1 text-[11px] text-ink-500">
            使用上限
            <input v-model.number="shareForm.max_uses" class="input" type="number" min="0" max="1000000" />
          </label>
        </div>
        <p class="text-[11px] text-ink-400">使用上限填 0 表示不限制次数；过期时间必须晚于当前时间。</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" type="button" @click="shareModalOpen = false">取消</button>
          <button class="btn-primary" type="button" :disabled="shareSaving" @click="submitShareLink">
            {{ shareSaving ? '创建中…' : '创建链接' }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useAppStore } from '../../stores/app'
import { formstudioApi } from '../../api/platform'
import { formatDate } from '../../composables/useDomainResource'
import SectionCard from '../../components/platform/SectionCard.vue'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  forms: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed'])

const app = useAppStore()

const FORM_TYPE_LABELS = {
  survey: '问卷',
  quiz: '测验',
  collect: '信息收集',
  registration: '报名登记',
  approval: '审批申请',
  feedback: '意见反馈',
}
const EVENT_LABELS = {
  'submission.created': '提交创建',
  'submission.reviewed': '审核完成',
  'form.published': '表单发布',
  'webhook.test': '测试投递',
  all: '全部事件',
}
const DELIVERY_STATUS_LABELS = {
  pending: '待投递',
  success: '成功',
  failed: '失败',
  skipped: '已跳过',
}

function formTypeLabel(value) {
  return FORM_TYPE_LABELS[value] || value || '—'
}
function eventLabel(value) {
  return EVENT_LABELS[value] || value || '—'
}
function deliveryStatusLabel(value) {
  return DELIVERY_STATUS_LABELS[value] || value || '—'
}
function deliveryStatusClass(value) {
  if (value === 'success') return 'bg-emerald-50 text-emerald-600'
  if (value === 'failed') return 'bg-rose-50 text-rose-600'
  if (value === 'pending') return 'bg-amber-50 text-amber-600'
  return 'bg-ink-100 text-ink-600'
}
function shareStatusLabel(link) {
  if (!link.active) return '已停用'
  if (link.is_expired) return '已过期'
  if (link.max_uses && link.remaining_uses <= 0) return '已用尽'
  return '可用'
}
function shareStatusClass(link) {
  const label = shareStatusLabel(link)
  if (label === '可用') return 'bg-emerald-50 text-emerald-600'
  if (label === '已停用') return 'bg-ink-100 text-ink-600'
  return 'bg-amber-50 text-amber-600'
}

// ---------------------------------------------------------------------------
// 模板
// ---------------------------------------------------------------------------
const templates = ref([])
const templateLoading = ref(false)
const templateError = ref('')
const templateName = ref('')
const creatingTemplateId = ref(null)

async function loadTemplates() {
  templateLoading.value = true
  templateError.value = ''
  try {
    const data = await formstudioApi.list('templates/', { page: 1, page_size: 100 })
    templates.value = data.items || []
  } catch (e) {
    templateError.value = e?.message || '模板加载失败'
    templates.value = []
  } finally {
    templateLoading.value = false
  }
}
async function instantiate(tpl) {
  creatingTemplateId.value = tpl.id
  try {
    const payload = { template_id: tpl.id }
    if (templateName.value.trim()) payload.name = templateName.value.trim()
    const created = await formstudioApi.action('forms/from-template/', payload)
    app.toastMsg(`已创建表单：${created?.name || tpl.name}`, 'success')
    loadTemplates()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '创建失败', 'error')
  } finally {
    creatingTemplateId.value = null
  }
}

// ---------------------------------------------------------------------------
// 分享链接
// ---------------------------------------------------------------------------
const dataFormId = ref('')
const shareLinks = ref([])
const shareLoading = ref(false)
const shareError = ref('')
const shareUnavailable = ref(false)
const disablingId = ref(null)
const shareModalOpen = ref(false)
const shareModalError = ref('')
const shareSaving = ref(false)
const shareForm = reactive({ label: '', password: '', expires_at: '', max_uses: 0 })

async function loadShareLinks() {
  if (!dataFormId.value) {
    shareLinks.value = []
    return
  }
  shareLoading.value = true
  shareError.value = ''
  shareUnavailable.value = false
  try {
    const data = await formstudioApi.list('share-links/', {
      form_id: dataFormId.value,
      page: 1,
      page_size: 100,
    })
    shareLinks.value = data.items || []
  } catch (e) {
    shareLinks.value = []
    const down = e?.status === 404 || e?.status === 405
    shareUnavailable.value = down
    shareError.value = down ? '' : e?.message || '分享链接加载失败'
  } finally {
    shareLoading.value = false
  }
}
function openShareModal() {
  if (!dataFormId.value) {
    app.toastMsg('请先选择表单', 'info')
    return
  }
  shareForm.label = ''
  shareForm.password = ''
  shareForm.expires_at = ''
  shareForm.max_uses = 0
  shareModalError.value = ''
  shareModalOpen.value = true
}
async function submitShareLink() {
  shareModalError.value = ''
  if (shareForm.expires_at) {
    const stamp = new Date(shareForm.expires_at).getTime()
    if (Number.isFinite(stamp) && stamp <= Date.now()) {
      shareModalError.value = '过期时间必须晚于当前时间'
      return
    }
  }
  shareSaving.value = true
  try {
    const payload = {
      label: shareForm.label.trim(),
      password: shareForm.password,
      max_uses: Number(shareForm.max_uses) || 0,
    }
    if (shareForm.expires_at) payload.expires_at = new Date(shareForm.expires_at).toISOString()
    await formstudioApi.action(`forms/${dataFormId.value}/share-links/`, payload)
    app.toastMsg('已创建分享链接', 'success')
    shareModalOpen.value = false
    await loadShareLinks()
  } catch (e) {
    shareModalError.value = e?.message || '创建失败'
    app.toastMsg(shareModalError.value, 'error')
  } finally {
    shareSaving.value = false
  }
}
async function disableShareLink(link) {
  disablingId.value = link.id
  try {
    await formstudioApi.action(`share-links/${link.id}/disable/`, {})
    app.toastMsg('已停用分享链接', 'success')
    await loadShareLinks()
  } catch (e) {
    app.toastMsg(e?.message || '停用失败', 'error')
  } finally {
    disablingId.value = null
  }
}
async function copyShareLink(link) {
  const url = `${window.location.origin}/forms/share?token=${encodeURIComponent(link.token)}`
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(url)
      app.toastMsg('分享链接已复制', 'success')
    } else {
      app.toastMsg(url, 'info')
    }
  } catch (e) {
    app.toastMsg(url, 'info')
  }
}

// ---------------------------------------------------------------------------
// Webhook 与投递
// ---------------------------------------------------------------------------
const webhooks = ref([])
const webhookLoading = ref(false)
const webhookError = ref('')
const webhookUnavailable = ref(false)
const testingHookId = ref(null)
const deliveries = ref([])
const deliveryLoading = ref(false)
const deliveryError = ref('')
const deliveryStatus = ref('')
const retryingId = ref(null)

async function loadWebhooks() {
  if (!dataFormId.value) {
    webhooks.value = []
    return
  }
  webhookLoading.value = true
  webhookError.value = ''
  webhookUnavailable.value = false
  try {
    const data = await formstudioApi.list('webhooks/', {
      form_id: dataFormId.value,
      page: 1,
      page_size: 100,
    })
    webhooks.value = data.items || []
  } catch (e) {
    webhooks.value = []
    const down = e?.status === 404 || e?.status === 405
    webhookUnavailable.value = down
    webhookError.value = down ? '' : e?.message || 'Webhook 加载失败'
  } finally {
    webhookLoading.value = false
  }
}
async function loadDeliveries() {
  if (!dataFormId.value) {
    deliveries.value = []
    return
  }
  deliveryLoading.value = true
  deliveryError.value = ''
  try {
    const params = { form_id: dataFormId.value, page: 1, page_size: 50 }
    if (deliveryStatus.value) params.status = deliveryStatus.value
    const data = await formstudioApi.list('deliveries/', params)
    deliveries.value = data.items || []
  } catch (e) {
    deliveries.value = []
    deliveryError.value = e?.message || '投递记录加载失败'
  } finally {
    deliveryLoading.value = false
  }
}
async function testWebhook(hook) {
  testingHookId.value = hook.id
  try {
    const data = await formstudioApi.action(`webhooks/${hook.id}/test/`, {})
    const status = data?.delivery?.status
    app.toastMsg(`测试投递完成：${deliveryStatusLabel(status)}`, status === 'failed' ? 'error' : 'success')
    await loadWebhooks()
    await loadDeliveries()
  } catch (e) {
    app.toastMsg(e?.message || '测试投递失败', 'error')
  } finally {
    testingHookId.value = null
  }
}
async function retryDelivery(row) {
  retryingId.value = row.id
  try {
    const data = await formstudioApi.action(`deliveries/${row.id}/retry/`, {})
    app.toastMsg(`重试完成：${deliveryStatusLabel(data?.status)}`, data?.status === 'failed' ? 'error' : 'success')
    await loadDeliveries()
    await loadWebhooks()
  } catch (e) {
    app.toastMsg(e?.message || '重试失败', 'error')
  } finally {
    retryingId.value = null
  }
}

watch(
  () => props.forms,
  (list) => {
    const rows = Array.isArray(list) ? list : []
    if (!rows.length) {
      dataFormId.value = ''
      return
    }
    const exists = rows.some((form) => String(form.id) === String(dataFormId.value))
    if (!exists) {
      dataFormId.value = rows[0].id
      loadShareLinks()
      loadWebhooks()
      loadDeliveries()
    }
  },
  { immediate: true }
)

onMounted(() => {
  loadTemplates()
})
</script>