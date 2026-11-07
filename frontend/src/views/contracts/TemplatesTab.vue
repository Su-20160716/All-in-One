<template>
  <section class="space-y-3">
    <!-- 模板列表 -->
    <div class="card p-3">
      <div class="flex flex-wrap items-end gap-2">
        <label class="block min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">关键词</span>
          <input v-model="search.value" class="input" type="search" placeholder="按模板编码、名称、场景搜索" />
        </label>
        <label class="block w-[140px]">
          <span class="mb-1 block text-[11px] text-ink-400">状态</span>
          <select v-model="statusFilter" class="input" @change="reloadTemplates">
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="published">已发布</option>
            <option value="disabled">已停用</option>
          </select>
        </label>
        <div class="flex flex-wrap items-center gap-1.5">
          <button class="btn-outline" type="button" :disabled="templateLoading" @click="loadTemplates">
            {{ templateLoading ? '加载中…' : '刷新' }}
          </button>
          <button class="btn-primary" type="button" @click="openCreate">新建模板</button>
        </div>
        <span class="ml-auto text-[11px] text-ink-400">共 {{ formatNumber(templateTotal) }} 个模板</span>
      </div>
    </div>

    <div class="card p-3">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[13px] font-medium text-ink-800">合同模板</h3>
        <span class="text-[11px] text-ink-400">第 {{ templatePage }} / {{ templatePages }} 页 · /contracts/templates</span>
      </div>

      <div
        v-if="templateError"
        class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ templateError }}</span>
        <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="loadTemplates">重试</button>
      </div>

      <div v-if="templateLoading && !templates.length" class="space-y-2">
        <div v-for="n in 5" :key="n" class="h-8 animate-pulse rounded bg-ink-100" />
      </div>
      <div v-else-if="!templateLoading && !templates.length && !templateError" class="py-10 text-center text-[12px] text-ink-400">
        <p>还没有合同模板</p>
        <p class="mt-1">创建模板后可以发布、克隆并按变量渲染预览</p>
        <button class="btn-primary mt-3" type="button" @click="openCreate">新建模板</button>
      </div>

      <div v-else-if="templates.length" class="overflow-x-auto">
        <table class="w-full min-w-[900px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">编码</th>
              <th class="th">名称</th>
              <th class="th">类型</th>
              <th class="th">场景</th>
              <th class="th">版本</th>
              <th class="th">状态</th>
              <th class="th">更新时间</th>
              <th class="th w-[220px]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in templates" :key="row.id" class="border-b border-ink-50 last:border-0 hover:bg-ink-50/60">
              <td class="td font-mono text-[12px] text-ink-500">{{ row.code || '—' }}</td>
              <td class="td max-w-[200px] truncate">
                <button class="text-left text-ink-800 hover:text-brand-600" type="button" @click="openRender(row)">
                  {{ row.name || '未命名模板' }}
                </button>
              </td>
              <td class="td text-ink-500">{{ typeLabel(row.template_type) }}</td>
              <td class="td max-w-[140px] truncate text-ink-500">{{ row.scene || '—' }}</td>
              <td class="td text-ink-500">{{ row.version || 'v1.0' }}</td>
              <td class="td">
                <span class="tag" :class="tagClass(templateTone(row.status))">{{ templateLabel(row.status) }}</span>
              </td>
              <td class="td whitespace-nowrap text-ink-400">{{ formatDate(row.updated_at, true) }}</td>
              <td class="td">
                <div class="flex flex-wrap items-center gap-1">
                  <button class="text-[12px] text-brand-600 hover:underline" type="button" @click="openRender(row)">渲染预览</button>
                  <button
                    v-if="row.status !== 'published'"
                    class="text-[12px] text-ink-500 hover:text-brand-600"
                    type="button"
                    :disabled="acting"
                    @click="runTemplateAction(row, 'publish')"
                  >发布</button>
                  <button
                    v-if="row.status === 'published'"
                    class="text-[12px] text-ink-500 hover:text-brand-600"
                    type="button"
                    :disabled="acting"
                    @click="runTemplateAction(row, 'disable')"
                  >停用</button>
                  <button
                    class="text-[12px] text-ink-500 hover:text-brand-600"
                    type="button"
                    :disabled="acting"
                    @click="cloneTemplate(row)"
                  >克隆</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="templates.length" class="mt-3 flex items-center gap-2 text-[11px] text-ink-400">
        <button class="btn-outline px-2 py-1" type="button" :disabled="templatePage <= 1 || templateLoading" @click="goTemplatePage(templatePage - 1)">
          上一页
        </button>
        <button class="btn-outline px-2 py-1" type="button" :disabled="templatePage >= templatePages || templateLoading" @click="goTemplatePage(templatePage + 1)">
          下一页
        </button>
        <span>共 {{ formatNumber(templateTotal) }} 个</span>
      </div>
    </div>

    <!-- 条款库 -->
    <div class="card p-3">
      <div class="mb-2 flex flex-wrap items-end gap-2">
        <label class="block min-w-[200px] flex-1">
          <span class="mb-1 block text-[11px] text-ink-400">条款搜索</span>
          <input v-model="clauseSearch.value" class="input" type="search" placeholder="按条款标题、正文搜索" />
        </label>
        <label class="block w-[150px]">
          <span class="mb-1 block text-[11px] text-ink-400">分类</span>
          <select v-model="clauseCategory" class="input" @change="reloadClauses">
            <option value="">全部分类</option>
            <option v-for="item in categoryOptions" :key="item.category" :value="item.category">
              {{ item.category }}（{{ item.count }}）
            </option>
          </select>
        </label>
        <label class="block w-[130px]">
          <span class="mb-1 block text-[11px] text-ink-400">风险等级</span>
          <select v-model="clauseRisk" class="input" @change="reloadClauses">
            <option value="">全部等级</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="critical">极高</option>
          </select>
        </label>
        <button class="btn-outline" type="button" :disabled="clauseLoading" @click="loadClauses">
          {{ clauseLoading ? '加载中…' : '搜索' }}
        </button>
        <span class="text-[11px] text-ink-400">共 {{ formatNumber(clauseTotal) }} 条条款</span>
      </div>

      <div class="mb-2 flex flex-wrap items-center gap-1.5">
        <span class="text-[11px] text-ink-400">分类统计</span>
        <button
          class="rounded-pill px-2 py-0.5 text-[11px]"
          :class="clauseCategory === '' ? 'bg-ink-700 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
          type="button"
          @click="pickCategory('')"
        >全部 {{ formatNumber(clauseStatsTotal) }}</button>
        <button
          v-for="item in categoryStats"
          :key="item.category"
          class="rounded-pill px-2 py-0.5 text-[11px]"
          :class="clauseCategory === item.category ? 'bg-brand-600 text-white' : 'bg-ink-50 text-ink-500 hover:bg-ink-100'"
          type="button"
          @click="pickCategory(item.category)"
        >{{ item.category }} {{ item.count }}</button>
        <span v-if="clauseStatsError" class="text-[11px] text-amber-600">{{ clauseStatsError }}</span>
      </div>

      <div
        v-if="clauseError"
        class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
      >
        <span class="min-w-0 flex-1">{{ clauseError }}</span>
        <button class="btn-ghost shrink-0 px-2 text-[12px] text-rose-600" type="button" @click="loadClauses">重试</button>
      </div>

      <div v-if="clauseLoading && !clauses.length" class="space-y-2">
        <div v-for="n in 5" :key="n" class="h-8 animate-pulse rounded bg-ink-100" />
      </div>
      <div v-else-if="!clauseLoading && !clauses.length && !clauseError" class="py-8 text-center text-[12px] text-ink-400">
        条款库暂无匹配条款，可调整关键词或分类
      </div>

      <div v-else-if="clauses.length" class="overflow-x-auto">
        <table class="w-full min-w-[820px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">条款标题</th>
              <th class="th">分类</th>
              <th class="th">风险</th>
              <th class="th">法域</th>
              <th class="th text-right">引用次数</th>
              <th class="th">状态</th>
              <th class="th w-[80px]">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in clauses" :key="row.id" class="border-b border-ink-50 last:border-0 hover:bg-ink-50/60">
              <td class="td max-w-[280px]">
                <div class="truncate text-ink-800">{{ row.title || '未命名条款' }}</div>
                <div class="truncate text-[11px] text-ink-400">{{ snippet(row.body) }}</div>
              </td>
              <td class="td">
                <span class="tag">{{ row.category || '通用' }}</span>
              </td>
              <td class="td">
                <span class="tag" :class="riskClass(row.risk_level)">{{ riskLabel(row.risk_level) }}</span>
              </td>
              <td class="td text-ink-500">{{ row.jurisdiction || 'CN' }}</td>
              <td class="td text-right">{{ formatNumber(row.usage_count) }}</td>
              <td class="td">
                <span class="tag" :class="row.status === 'active' ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                  {{ row.status === 'active' ? '启用' : '停用' }}
                </span>
              </td>
              <td class="td">
                <button class="text-[12px] text-brand-600 hover:underline" type="button" @click="openClause(row)">查看</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="clauses.length" class="mt-3 flex items-center gap-2 text-[11px] text-ink-400">
        <button class="btn-outline px-2 py-1" type="button" :disabled="clausePage <= 1 || clauseLoading" @click="goClausePage(clausePage - 1)">
          上一页
        </button>
        <button class="btn-outline px-2 py-1" type="button" :disabled="clausePage >= clausePages || clauseLoading" @click="goClausePage(clausePage + 1)">
          下一页
        </button>
        <span>第 {{ clausePage }} / {{ clausePages }} 页</span>
      </div>
    </div>

    <!-- 新建模板 -->
    <Modal :show="createModal.show" title="新建合同模板" width="620px" @close="closeCreate">
      <form class="space-y-3" @submit.prevent="submitTemplate">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">模板编码 <span class="text-rose-500">*</span></span>
            <input v-model.trim="createForm.code" class="input" maxlength="60" placeholder="例如 TPL-SERVICE-01" />
          </label>
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">模板名称 <span class="text-rose-500">*</span></span>
            <input v-model.trim="createForm.name" class="input" maxlength="200" placeholder="例如 标准服务合同模板" />
          </label>
        </div>
        <div class="grid gap-3 sm:grid-cols-3">
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">合同类型</span>
            <select v-model="createForm.template_type" class="input">
              <option v-for="item in TYPE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">适用场景</span>
            <input v-model.trim="createForm.scene" class="input" maxlength="120" placeholder="例如 年度续签" />
          </label>
          <label class="block">
            <span class="mb-1 block text-[12px] text-ink-500">版本号</span>
            <input v-model.trim="createForm.version" class="input" maxlength="20" placeholder="v1.0" />
          </label>
        </div>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">模板正文</span>
          <textarea
            v-model="createForm.body"
            class="input min-h-[140px] font-mono"
            maxlength="8000"
            placeholder="支持 {{party_a}} 这类变量占位，渲染预览时会替换为示例值"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-ink-500">备注</span>
          <input v-model.trim="createForm.remark" class="input" maxlength="300" placeholder="可留空" />
        </label>
        <p v-if="createError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ createError }}</p>
        <div class="flex items-center justify-end gap-2">
          <button class="btn-ghost" type="button" @click="closeCreate">取消</button>
          <button class="btn-primary" type="submit" :disabled="creating">
            {{ creating ? '创建中…' : '创建模板' }}
          </button>
        </div>
      </form>
    </Modal>

    <!-- 渲染预览 -->
    <Modal :show="renderModal.show" :title="`渲染预览 · ${renderModal.template?.name || ''}`" width="680px" @close="closeRender">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
          <span class="tag">{{ renderModal.template?.code || '—' }}</span>
          <span class="tag">{{ renderModal.template?.version || 'v1.0' }}</span>
          <span>接口 /contracts/templates/{{ renderModal.template?.id }}/render</span>
        </div>
        <div v-if="renderLoading" class="space-y-2">
          <div v-for="n in 6" :key="n" class="h-5 animate-pulse rounded bg-ink-100" />
        </div>
        <div v-else-if="renderError" class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ renderError }}</span>
          <button class="shrink-0 font-medium" type="button" @click="loadRender">重试</button>
        </div>
        <template v-else>
          <div v-if="renderMissing.length" class="rounded-control bg-amber-50 px-3 py-2 text-[11px] text-amber-700">
            以下变量未提供示例值，已用占位符保留：{{ renderMissing.join('、') }}
          </div>
          <pre class="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-control bg-ink-50 p-3 text-[12px] leading-relaxed text-ink-700">{{ renderText || '模板正文为空，无法渲染预览' }}</pre>
        </template>
        <div class="flex items-center justify-end gap-2">
          <button class="btn-ghost" type="button" @click="closeRender">关闭</button>
          <button class="btn-outline" type="button" :disabled="renderLoading" @click="loadRender">重新渲染</button>
        </div>
      </div>
    </Modal>

    <!-- 条款详情 -->
    <Modal :show="clauseModal.show" :title="clauseModal.row?.title || '条款详情'" width="560px" @close="clauseModal.show = false">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2 text-[11px]">
          <span class="tag">{{ clauseModal.row?.category || '通用' }}</span>
          <span class="tag" :class="riskClass(clauseModal.row?.risk_level)">风险 {{ riskLabel(clauseModal.row?.risk_level) }}</span>
          <span class="tag">{{ clauseModal.row?.jurisdiction || 'CN' }}</span>
          <span class="tag">引用 {{ formatNumber(clauseModal.row?.usage_count) }}</span>
        </div>
        <pre class="max-h-[360px] overflow-auto whitespace-pre-wrap rounded-control bg-ink-50 p-3 text-[12px] leading-relaxed text-ink-700">{{ clauseModal.row?.body || '暂无条款正文' }}</pre>
        <div class="flex flex-wrap gap-1">
          <span v-for="tag in clauseModal.row?.tags || []" :key="tag" class="tag">{{ tag }}</span>
        </div>
        <div class="flex justify-end">
          <button class="btn-ghost" type="button" @click="clauseModal.show = false">关闭</button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { contractsApi, normalizeList } from '../../api/platform'
import {
  formatDate,
  formatNumber,
  useDebounce,
} from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['changed'])

const app = useAppStore()

const TYPE_OPTIONS = [
  { value: 'service', label: '服务合同' },
  { value: 'sales', label: '销售合同' },
  { value: 'purchase', label: '采购合同' },
  { value: 'lease', label: '租赁合同' },
  { value: 'labor', label: '劳务合同' },
  { value: 'license', label: '授权许可' },
  { value: 'nda', label: '保密协议' },
  { value: 'other', label: '其他类型' },
]

const TYPE_LABELS = {
  service: '服务合同',
  sales: '销售合同',
  purchase: '采购合同',
  lease: '租赁合同',
  labor: '劳务合同',
  license: '授权许可',
  nda: '保密协议',
  other: '其他类型',
}

const TEMPLATE_LABELS = {
  draft: '草稿',
  published: '已发布',
  disabled: '已停用',
}

const search = useDebounce(350)
const statusFilter = ref('')
const templates = ref([])
const templateTotal = ref(0)
const templatePage = ref(1)
const templatePageSize = 10
const templateLoading = ref(false)
const templateError = ref('')

const clauseSearch = useDebounce(350)
const clauseCategory = ref('')
const clauseRisk = ref('')
const clauses = ref([])
const clauseTotal = ref(0)
const clausePage = ref(1)
const clausePageSize = 10
const clauseLoading = ref(false)
const clauseError = ref('')

const categoryStats = ref([])
const clauseStatsTotal = ref(0)
const clauseStatsError = ref('')

const acting = ref(false)
const creating = ref(false)
const createError = ref('')
const createModal = ref({ show: false })
const createForm = ref({
  code: '',
  name: '',
  template_type: 'service',
  scene: '',
  version: 'v1.0',
  body: '',
  remark: '',
})

const renderModal = ref({ show: false, template: null })
const renderLoading = ref(false)
const renderError = ref('')
const renderText = ref('')
const renderMissing = ref([])

const clauseModal = ref({ show: false, row: null })

const templatePages = computed(() => Math.max(1, Math.ceil(templateTotal.value / templatePageSize)))
const clausePages = computed(() => Math.max(1, Math.ceil(clauseTotal.value / clausePageSize)))

const categoryOptions = computed(() => categoryStats.value)

function typeLabel(value) {
  return TYPE_LABELS[value] || value || '未分类'
}

function templateLabel(value) {
  return TEMPLATE_LABELS[value] || value || '草稿'
}

function templateTone(value) {
  if (value === 'published') return 'success'
  if (value === 'disabled') return 'neutral'
  return 'warning'
}

function riskLabel(value) {
  return { low: '低', medium: '中', high: '高', critical: '极高' }[value] || value || '低'
}

function riskClass(value) {
  return {
    low: 'bg-emerald-50 text-emerald-600',
    medium: 'bg-amber-50 text-amber-600',
    high: 'bg-rose-50 text-rose-600',
    critical: 'bg-rose-100 text-rose-700',
  }[value] || 'bg-ink-100 text-ink-600'
}

function tagClass(tone) {
  return {
    success: 'bg-emerald-50 text-emerald-600',
    info: 'bg-sky-50 text-sky-600',
    warning: 'bg-amber-50 text-amber-600',
    danger: 'bg-rose-50 text-rose-600',
    neutral: 'bg-ink-100 text-ink-600',
  }[tone] || 'bg-ink-100 text-ink-600'
}

function snippet(value) {
  if (!value) return '暂无正文'
  const text = String(value).replace(/\s+/g, ' ').trim()
  return text.length > 48 ? `${text.slice(0, 48)}…` : text
}

function rowsOf(value) {
  if (Array.isArray(value)) return value.filter((row) => row && typeof row === 'object')
  if (Array.isArray(value?.items)) return value.items.filter((row) => row && typeof row === 'object')
  if (Array.isArray(value?.rows)) return value.rows.filter((row) => row && typeof row === 'object')
  return []
}

function pick(obj, paths, fallback = null) {
  for (const path of paths) {
    let cur = obj
    let ok = true
    for (const key of path.split('.')) {
      if (cur == null || typeof cur !== 'object') {
        ok = false
        break
      }
      cur = cur[key]
    }
    if (ok && cur !== undefined && cur !== null && cur !== '') return cur
  }
  return fallback
}

async function loadTemplates() {
  templateLoading.value = true
  templateError.value = ''
  const params = { page: templatePage.value, page_size: templatePageSize }
  if (search.debounced.value.trim()) params.q = search.debounced.value.trim()
  if (statusFilter.value) params.status = statusFilter.value
  try {
    const data = await contractsApi.list('templates/', params)
    const normalized = normalizeList(data, { page: templatePage.value, page_size: templatePageSize })
    templates.value = normalized.items
    templateTotal.value = normalized.count
  } catch (e) {
    templates.value = []
    templateTotal.value = 0
    templateError.value = e?.message || '模板列表加载失败'
    app.toastMsg(templateError.value, 'error')
  } finally {
    templateLoading.value = false
  }
}

async function loadClauses() {
  clauseLoading.value = true
  clauseError.value = ''
  const params = { page: clausePage.value, page_size: clausePageSize }
  if (clauseSearch.debounced.value.trim()) params.q = clauseSearch.debounced.value.trim()
  if (clauseCategory.value) params.category = clauseCategory.value
  if (clauseRisk.value) params.risk_level = clauseRisk.value
  try {
    const data = await contractsApi.list('clauses/library/', params)
    const normalized = normalizeList(data, { page: clausePage.value, page_size: clausePageSize })
    clauses.value = normalized.items
    clauseTotal.value = normalized.count
  } catch (e) {
    clauses.value = []
    clauseTotal.value = 0
    clauseError.value = e?.message || '条款库加载失败，接口可能尚未部署'
    app.toastMsg(clauseError.value, 'error')
  } finally {
    clauseLoading.value = false
  }
}

async function loadClauseStats() {
  clauseStatsError.value = ''
  try {
    const data = await contractsApi.get('clauses/library/stats/')
    const direct = pick(data, ['by_category', 'categories', 'category_stats', 'items', 'rows'], [])
    const rows = rowsOf(direct)
    categoryStats.value = rows.map((row) => ({
      category: row.category || row.key || row.label || '未分类',
      count: Number(row.count ?? row.value ?? row.total ?? 0) || 0,
    }))
    clauseStatsTotal.value = Number(
      pick(data, ['total', 'count', 'totals.clauses', 'totals.total'], clauseStatsTotal.value)
    ) || categoryStats.value.reduce((sum, row) => sum + row.count, 0)
  } catch (e) {
    categoryStats.value = []
    clauseStatsError.value = e?.message || '分类统计暂不可用'
  }
}

function reloadTemplates() {
  templatePage.value = 1
  loadTemplates()
}

function goTemplatePage(next) {
  templatePage.value = Math.min(Math.max(1, next), templatePages.value)
  loadTemplates()
}

function reloadClauses() {
  clausePage.value = 1
  loadClauses()
}

function goClausePage(next) {
  clausePage.value = Math.min(Math.max(1, next), clausePages.value)
  loadClauses()
}

function pickCategory(category) {
  clauseCategory.value = category
  reloadClauses()
}

function openCreate() {
  createError.value = ''
  createForm.value = {
    code: '',
    name: '',
    template_type: 'service',
    scene: '',
    version: 'v1.0',
    body: '',
    remark: '',
  }
  createModal.value = { show: true }
}

function closeCreate() {
  createModal.value = { show: false }
}

async function submitTemplate() {
  if (!createForm.value.code) {
    createError.value = '请填写模板编码'
    return
  }
  if (!createForm.value.name) {
    createError.value = '请填写模板名称'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    await contractsApi.create('templates/create/', {
      ...createForm.value,
      variables: [],
    })
    app.toastMsg('模板已创建', 'success')
    closeCreate()
    await loadTemplates()
    emit('changed')
  } catch (e) {
    createError.value = e?.message || '模板创建失败'
    app.toastMsg(createError.value, 'error')
  } finally {
    creating.value = false
  }
}

async function runTemplateAction(row, kind) {
  if (!row?.id) return
  acting.value = true
  try {
    await contractsApi.action(`templates/${row.id}/${kind}/`, {})
    app.toastMsg(kind === 'publish' ? '模板已发布' : '模板已停用', 'success')
    await loadTemplates()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '模板状态更新失败', 'error')
  } finally {
    acting.value = false
  }
}

async function cloneTemplate(row) {
  if (!row?.id) return
  acting.value = true
  try {
    await contractsApi.action(`templates/${row.id}/clone/`, { name: `${row.name || '模板'} 副本` })
    app.toastMsg('模板已克隆', 'success')
    await loadTemplates()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '模板克隆失败', 'error')
  } finally {
    acting.value = false
  }
}

function openRender(row) {
  renderModal.value = { show: true, template: row }
  renderText.value = ''
  renderMissing.value = []
  loadRender()
}

function closeRender() {
  renderModal.value = { show: false, template: null }
  renderText.value = ''
  renderMissing.value = []
  renderError.value = ''
}

async function loadRender() {
  const row = renderModal.value.template
  if (!row?.id) return
  renderLoading.value = true
  renderError.value = ''
  try {
    const data = await contractsApi.action(`templates/${row.id}/render/`, {})
    const text = pick(data, ['rendered', 'body', 'content', 'text', 'preview'], '')
    renderText.value = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
    const missing = pick(data, ['missing', 'missing_variables', 'undefined_variables'], [])
    renderMissing.value = Array.isArray(missing) ? missing.map((item) => String(item)) : []
  } catch (e) {
    renderText.value = ''
    renderError.value = e?.message || '渲染接口暂不可用'
  } finally {
    renderLoading.value = false
  }
}

function openClause(row) {
  clauseModal.value = { show: true, row }
}

watch(search.debounced, () => {
  reloadTemplates()
})

watch(clauseSearch.debounced, () => {
  reloadClauses()
})

watch(
  () => props.refreshKey,
  () => {
    loadTemplates()
    loadClauses()
    loadClauseStats()
  }
)

onMounted(() => {
  loadTemplates()
  loadClauses()
  loadClauseStats()
})
</script>