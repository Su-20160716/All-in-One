<template>
  <div class="space-y-3">
    <!-- 概览 -->
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div class="card p-3">
        <div class="text-[12px] text-ink-400">质量规则</div>
        <div class="mt-1 text-[20px] font-semibold text-ink-900">{{ formatNumber(ruleTotal) }}</div>
        <div class="mt-0.5 text-[11px] text-ink-400">启用 {{ enabledRuleCount }} 条 · 停用 {{ disabledRuleCount }} 条</div>
      </div>
      <div class="card p-3">
        <div class="text-[12px] text-ink-400">结果通过率</div>
        <div class="mt-1 text-[20px] font-semibold" :class="passRate >= 90 ? 'text-emerald-600' : passRate >= 70 ? 'text-amber-600' : 'text-rose-600'">
          {{ passRateText }}
        </div>
        <div class="mt-0.5 text-[11px] text-ink-400">基于当前结果 {{ resultTotal }} 条</div>
      </div>
      <div class="card p-3">
        <div class="text-[12px] text-ink-400">失败结果</div>
        <div class="mt-1 text-[20px] font-semibold text-rose-600">{{ formatNumber(failedResultCount) }}</div>
        <div class="mt-0.5 text-[11px] text-ink-400">失败行数 {{ formatNumber(failedRowCount) }}</div>
      </div>
      <div class="card p-3">
        <div class="text-[12px] text-ink-400">规则类型覆盖</div>
        <div class="mt-1 text-[20px] font-semibold text-ink-900">{{ typeBars.length }} / {{ RULE_TYPES.length }}</div>
        <div class="mt-0.5 text-[11px] text-ink-400">已配置的规则类型数量</div>
      </div>
    </div>

    <div class="grid gap-3 lg:grid-cols-3">
      <SectionCard class="lg:col-span-1" title="结果构成" subtitle="通过 / 失败与严重度分布">
        <div v-if="!results.length && !resultsLoading" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          暂无质量结果
        </div>
        <template v-else>
          <DonutChart
            :data="resultBars"
            :size="150"
            center-label="结果数"
            legend-position="bottom"
            :format="(value) => formatNumber(value)"
          />
          <BarChart :data="severityBars" horizontal :height="96" class="mt-2" />
        </template>
      </SectionCard>

      <SectionCard class="lg:col-span-2" title="规则列表" :subtitle="`关键词与管道过滤后共 ${ruleTotal} 条规则`">
        <template #actions>
          <button class="btn-primary py-1 text-[12px]" @click="openCreate">新建规则</button>
          <button class="btn-ghost py-1 text-[12px]" :disabled="rulesLoading" @click="loadRules">
            {{ rulesLoading ? '加载中…' : '刷新' }}
          </button>
        </template>

        <div class="mb-2 flex flex-wrap items-center gap-2">
          <select v-model="rulePipeline" class="input w-[200px] py-1" @change="reloadRules">
            <option value="">全部管道</option>
            <option v-for="item in pipelines" :key="item.id" :value="String(item.id)">{{ item.name }}</option>
          </select>
          <select v-model="ruleTypeFilter" class="input w-[150px] py-1" @change="reloadRules">
            <option value="">全部类型</option>
            <option v-for="type in RULE_TYPES" :key="type.value" :value="type.value">{{ type.label }}</option>
          </select>
          <input v-model="ruleKeyword" class="input w-[180px] py-1" placeholder="搜索规则名称" @keyup.enter="reloadRules" />
          <button class="btn-outline py-1 text-[12px]" @click="reloadRules">查询</button>
          <span class="ml-auto text-[11px] text-ink-400">{{ rulePage }} / {{ rulePages }} 页</span>
        </div>

        <div v-if="rulesError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ rulesError }}</span>
          <button class="shrink-0 font-medium" @click="loadRules">重试</button>
        </div>
        <div v-else-if="rulesLoading && !rules.length" class="py-10 text-center text-[12px] text-ink-400">规则加载中…</div>
        <div v-else-if="!rules.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          还没有质量规则，先为关键字段配置非空、唯一或范围校验
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[860px]">
            <thead>
              <tr class="border-b border-ink-100">
                <th class="th">规则</th>
                <th class="th">类型</th>
                <th class="th">字段</th>
                <th class="th">严重度</th>
                <th class="th">启用</th>
                <th class="th">最近检查</th>
                <th class="th text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="rule in rules" :key="rule.id" class="transition-colors hover:bg-ink-50/60">
                <td class="td">
                  <div class="max-w-[220px] truncate font-medium text-ink-800">{{ rule.name }}</div>
                  <div class="text-[11px] text-ink-400">{{ rule.description || '—' }}</div>
                </td>
                <td class="td"><span class="tag">{{ typeLabel(rule.rule_type) }}</span></td>
                <td class="td font-mono text-[12px]">{{ rule.field || '全表' }}</td>
                <td class="td">
                  <span class="tag" :class="severityClass(rule.severity)">{{ severityLabel(rule.severity) }}</span>
                </td>
                <td class="td">
                  <span class="tag" :class="rule.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                    {{ rule.enabled ? '启用' : '停用' }}
                  </span>
                </td>
                <td class="td">
                  <div class="text-[12px] text-ink-600">{{ formatDate(rule.last_checked_at, true) }}</div>
                  <span v-if="rule.last_passed !== null && rule.last_passed !== undefined" class="text-[11px]" :class="rule.last_passed ? 'text-emerald-600' : 'text-rose-600'">
                    {{ rule.last_passed ? '通过' : '未通过' }}
                  </span>
                </td>
                <td class="td text-right">
                  <div class="flex justify-end gap-1">
                    <button class="btn-ghost py-0.5 text-[11px]" @click="openTest(rule)">测试</button>
                    <button class="btn-ghost py-0.5 text-[11px]" @click="openEdit(rule)">编辑</button>
                    <button class="btn-danger py-0.5 text-[11px]" @click="askDelete(rule)">删除</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-2 flex items-center justify-end gap-1.5">
          <button class="btn-outline py-1 text-[12px]" :disabled="rulePage <= 1 || rulesLoading" @click="goRulePage(rulePage - 1)">上一页</button>
          <span class="text-[12px] text-ink-500">{{ rulePage }} / {{ rulePages }}</span>
          <button class="btn-outline py-1 text-[12px]" :disabled="rulePage >= rulePages || rulesLoading" @click="goRulePage(rulePage + 1)">下一页</button>
        </div>
      </SectionCard>
    </div>

    <SectionCard title="质量结果" :subtitle="`最近检查记录，失败结果会带样例与说明`">
      <template #actions>
        <select v-model="resultPassed" class="input w-[120px] py-1" @change="reloadResults">
          <option value="">全部结果</option>
          <option value="true">仅通过</option>
          <option value="false">仅失败</option>
        </select>
        <button class="btn-ghost py-1 text-[12px]" :disabled="resultsLoading" @click="loadResults">
          {{ resultsLoading ? '加载中…' : '刷新结果' }}
        </button>
      </template>

      <div v-if="resultsError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ resultsError }}</span>
        <button class="shrink-0 font-medium" @click="loadResults">重试</button>
      </div>
      <div v-else-if="resultsLoading && !results.length" class="py-10 text-center text-[12px] text-ink-400">结果加载中…</div>
      <div v-else-if="!results.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
        暂无质量结果，先测试一条规则或运行携带质量检查的管道
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[900px]">
          <thead>
            <tr class="border-b border-ink-100">
              <th class="th">规则</th>
              <th class="th">运行</th>
              <th class="th">结果</th>
              <th class="th text-right">检查行数</th>
              <th class="th text-right">失败行数</th>
              <th class="th">说明</th>
              <th class="th text-right">耗时</th>
              <th class="th text-right">检查时间</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="result in results" :key="result.id" :class="result.passed ? '' : 'bg-rose-50/30'">
              <td class="td">
                <div class="max-w-[200px] truncate">{{ ruleName(result.rule) }}</div>
                <div class="text-[11px] text-ink-400">#{{ result.rule }}</div>
              </td>
              <td class="td font-mono text-[12px] text-ink-500">#{{ result.run || '—' }}</td>
              <td class="td">
                <span class="tag" :class="result.passed ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                  {{ result.passed ? '通过' : '未通过' }}
                </span>
              </td>
              <td class="td text-right">{{ formatNumber(result.checked_rows) }}</td>
              <td class="td text-right" :class="result.failed_rows ? 'text-rose-600' : ''">{{ formatNumber(result.failed_rows) }}</td>
              <td class="td">
                <div class="max-w-[260px] truncate text-[12px] text-ink-500">{{ result.message || '—' }}</div>
              </td>
              <td class="td text-right">{{ durationText(result.duration_ms) }}</td>
              <td class="td text-right text-[11px] text-ink-400">{{ formatDate(result.checked_at, true) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mt-2 flex items-center justify-end gap-1.5">
        <button class="btn-outline py-1 text-[12px]" :disabled="resultPage <= 1 || resultsLoading" @click="goResultPage(resultPage - 1)">上一页</button>
        <span class="text-[12px] text-ink-500">{{ resultPage }} / {{ resultPages }}</span>
        <button class="btn-outline py-1 text-[12px]" :disabled="resultPage >= resultPages || resultsLoading" @click="goResultPage(resultPage + 1)">下一页</button>
      </div>
    </SectionCard>

    <!-- 规则表单 -->
    <Modal :show="formOpen" :title="form.id ? `编辑规则 ${form.name}` : '新建质量规则'" width="680px" @close="formOpen = false">
      <form class="space-y-3" @submit.prevent="saveRule">
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="text-[12px] text-ink-500">
            规则名称
            <input v-model="form.name" class="input mt-1" placeholder="订单号非空" />
          </label>
          <label class="text-[12px] text-ink-500">
            所属管道
            <select v-model="form.pipeline" class="input mt-1">
              <option value="">不绑定管道</option>
              <option v-for="item in pipelines" :key="item.id" :value="String(item.id)">{{ item.name }}</option>
            </select>
          </label>
          <label class="text-[12px] text-ink-500">
            规则类型
            <select v-model="form.rule_type" class="input mt-1" @change="onTypeChange">
              <option v-for="type in RULE_TYPES" :key="type.value" :value="type.value">{{ type.label }}</option>
            </select>
          </label>
          <label class="text-[12px] text-ink-500">
            校验字段
            <input v-model="form.field" class="input mt-1 font-mono" placeholder="order_id（留空表示全表）" />
          </label>
          <label class="text-[12px] text-ink-500">
            严重度
            <select v-model="form.severity" class="input mt-1">
              <option value="error">错误 error</option>
              <option value="warn">警告 warn</option>
              <option value="info">提示 info</option>
            </select>
          </label>
          <label class="flex items-center gap-2 pt-5 text-[12px] text-ink-600">
            <input v-model="form.enabled" type="checkbox" /> 启用规则
          </label>
        </div>
        <label class="block text-[12px] text-ink-500">
          规则参数（JSON）
          <textarea v-model="form.paramsText" rows="6" class="input mt-1 font-mono text-[12px]" :placeholder="typeHint"></textarea>
        </label>
        <p class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
          参数示例：<span class="font-mono">{{ typeHint }}</span>
        </p>
        <label class="block text-[12px] text-ink-500">
          说明
          <input v-model="form.description" class="input mt-1" placeholder="选填，说明校验目的" />
        </label>
        <div v-if="formError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ formError }}</div>
        <div class="flex justify-end gap-2">
          <button type="button" class="btn-ghost" @click="formOpen = false">取消</button>
          <button type="submit" class="btn-primary" :disabled="saving">{{ saving ? '保存中…' : '保存规则' }}</button>
        </div>
      </form>
    </Modal>

    <!-- 规则测试 -->
    <Modal :show="testOpen" :title="testRule ? `测试规则 · ${testRule.name}` : '测试规则'" width="640px" @close="testOpen = false">
      <div class="space-y-3">
        <div class="flex flex-wrap items-end gap-2">
          <label class="text-[12px] text-ink-500">
            样本运行 ID（可选）
            <input v-model="testRunId" class="input mt-1 w-[150px]" placeholder="不填则用最近成功运行" />
          </label>
          <button class="btn-primary py-1 text-[12px]" :disabled="testing" @click="submitTest">
            {{ testing ? '测试中…' : '执行测试' }}
          </button>
        </div>
        <div v-if="testError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ testError }}</div>
        <div v-if="testResult" class="space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tag" :class="testResult.passed ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
              {{ testResult.passed ? '通过' : '未通过' }}
            </span>
            <span class="tag">检查 {{ formatNumber(testResult.checked_rows) }} 行</span>
            <span class="tag">失败 {{ formatNumber(testResult.failed_rows) }} 行</span>
            <span class="tag">耗时 {{ durationText(testResult.duration_ms) }}</span>
          </div>
          <p v-if="testResult.message" class="text-[12px] text-ink-600">{{ testResult.message }}</p>
          <div v-if="testSamples.length" class="rounded-control border border-ink-100 p-2">
            <div class="mb-1 text-[11px] text-ink-400">失败样例（前 {{ testSamples.length }} 条）</div>
            <pre class="max-h-[220px] overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-ink-600">{{ testSamplesText }}</pre>
          </div>
          <details class="rounded-control bg-ink-50 px-3 py-2 text-[11px] text-ink-500">
            <summary class="cursor-pointer">查看原始返回</summary>
            <pre class="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap break-all font-mono">{{ testRaw }}</pre>
          </details>
        </div>
      </div>
    </Modal>

    <!-- 删除确认 -->
    <Modal :show="deleteOpen" title="删除质量规则" width="460px" @close="deleteOpen = false">
      <div class="space-y-3">
        <p class="text-[13px] text-ink-700">确认删除规则「{{ deleteTarget?.name }}」？历史检查结果会保留。</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="deleteOpen = false">取消</button>
          <button class="btn-danger" :disabled="saving" @click="confirmDelete">{{ saving ? '删除中…' : '确认删除' }}</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { apiFor } from '../../api/platform'
import { formatDate, formatNumber } from '../../composables/useDomainResource'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import BarChart from '../../components/platform/BarChart.vue'

defineProps({
  pipelines: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})

const api = apiFor('pipeline')
const app = useAppStore()

const RULE_TYPES = [
  { value: 'not_null', label: '非空 not_null', hint: '{"allow_empty": false}' },
  { value: 'unique', label: '唯一 unique', hint: '{"ignore_null": true}' },
  { value: 'range', label: '范围 range', hint: '{"min": 0, "max": 10000}' },
  { value: 'regex', label: '正则 regex', hint: '{"pattern": "^[A-Z]{2}\\\\d{6}$"}' },
  { value: 'enum', label: '枚举 enum', hint: '{"values": ["paid", "refunded"], "case_sensitive": false}' },
  { value: 'freshness', label: '时效 freshness', hint: '{"max_age_hours": 24}' },
  { value: 'row_count', label: '行数 row_count', hint: '{"min_rows": 1, "max_rows": 100000}' },
]

const SEVERITY_LABELS = { error: '错误', warn: '警告', info: '提示' }

const rules = ref([])
const rulesLoading = ref(false)
const rulesError = ref('')
const rulePage = ref(1)
const rulePageSize = ref(10)
const ruleTotal = ref(0)
const rulePipeline = ref('')
const ruleTypeFilter = ref('')
const ruleKeyword = ref('')

const results = ref([])
const resultsLoading = ref(false)
const resultsError = ref('')
const resultPage = ref(1)
const resultPageSize = ref(10)
const resultTotal = ref(0)
const resultPassed = ref('')

const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = reactive(emptyForm())

const testOpen = ref(false)
const testRule = ref(null)
const testRunId = ref('')
const testing = ref(false)
const testError = ref('')
const testResult = ref(null)
const testRaw = ref('')

const deleteOpen = ref(false)
const deleteTarget = ref(null)

const rulePages = computed(() => Math.max(1, Math.ceil(ruleTotal.value / Math.max(1, rulePageSize.value))))
const resultPages = computed(() => Math.max(1, Math.ceil(resultTotal.value / Math.max(1, resultPageSize.value))))

const enabledRuleCount = computed(() => rules.value.filter((rule) => rule.enabled).length)
const disabledRuleCount = computed(() => rules.value.filter((rule) => !rule.enabled).length)

const passRate = computed(() => {
  if (!results.value.length) return 0
  const passed = results.value.filter((item) => item.passed).length
  return Number(((passed / results.value.length) * 100).toFixed(1))
})
const passRateText = computed(() => (results.value.length ? `${passRate.value}%` : '—'))
const failedResultCount = computed(() => results.value.filter((item) => !item.passed).length)
const failedRowCount = computed(() => results.value.reduce((acc, item) => acc + (Number(item.failed_rows) || 0), 0))

const resultBars = computed(() => {
  const passed = results.value.filter((item) => item.passed).length
  const failed = results.value.length - passed
  return [
    { label: '通过', value: passed, color: '#10b981' },
    { label: '未通过', value: failed, color: '#f43f5e' },
  ].filter((item) => item.value > 0)
})

const severityBars = computed(() => {
  const counts = { error: 0, warn: 0, info: 0 }
  for (const rule of rules.value) {
    if (counts[rule.severity] !== undefined) counts[rule.severity] += 1
  }
  return Object.entries(counts).map(([key, value]) => ({ label: SEVERITY_LABELS[key], value }))
})

const typeBars = computed(() => {
  const seen = new Set(rules.value.map((rule) => rule.rule_type))
  return Array.from(seen)
})

const typeHint = computed(() => {
  const hit = RULE_TYPES.find((item) => item.value === form.rule_type)
  return hit ? hit.hint : '{}'
})

const testSamples = computed(() => (Array.isArray(testResult.value?.sample) ? testResult.value.sample : []))
const testSamplesText = computed(() => testSamples.value.map((item) => JSON.stringify(item)).join('\n'))

function emptyForm() {
  return {
    id: null,
    name: '',
    pipeline: '',
    rule_type: 'not_null',
    field: '',
    severity: 'error',
    enabled: true,
    paramsText: '{}',
    description: '',
  }
}

function typeLabel(value) {
  const hit = RULE_TYPES.find((item) => item.value === value)
  return hit ? hit.label.split(' ')[0] : (value || '—')
}

function severityLabel(value) {
  return SEVERITY_LABELS[value] || value || '—'
}

function severityClass(value) {
  const map = {
    error: 'bg-rose-50 text-rose-600',
    warn: 'bg-amber-50 text-amber-600',
    info: 'bg-sky-50 text-sky-600',
  }
  return map[value] || 'bg-ink-100 text-ink-500'
}

function ruleName(id) {
  const hit = rules.value.find((rule) => String(rule.id) === String(id))
  return hit ? hit.name : `规则 #${id}`
}

function durationText(ms) {
  const num = Number(ms)
  if (!Number.isFinite(num) || num <= 0) return '—'
  if (num < 1000) return `${num} ms`
  return `${(num / 1000).toFixed(2)} s`
}

async function loadRules() {
  if (!api) {
    rulesError.value = '数据管道接口不可用'
    return
  }
  rulesLoading.value = true
  rulesError.value = ''
  try {
    const params = { page: rulePage.value, page_size: rulePageSize.value }
    if (rulePipeline.value) params.pipeline = rulePipeline.value
    if (ruleTypeFilter.value) params.rule_type = ruleTypeFilter.value
    if (ruleKeyword.value.trim()) params.q = ruleKeyword.value.trim()
    const data = await api.list('quality/rules/', params)
    rules.value = data.items || []
    ruleTotal.value = data.count || 0
  } catch (e) {
    rules.value = []
    ruleTotal.value = 0
    rulesError.value = e?.message || '规则加载失败'
    app.toastMsg(rulesError.value, 'error')
  } finally {
    rulesLoading.value = false
  }
}

async function loadResults() {
  if (!api) return
  resultsLoading.value = true
  resultsError.value = ''
  try {
    const params = { page: resultPage.value, page_size: resultPageSize.value }
    if (rulePipeline.value) params.pipeline = rulePipeline.value
    if (resultPassed.value) params.passed = resultPassed.value
    const data = await api.list('quality/results/', params)
    results.value = data.items || []
    resultTotal.value = data.count || 0
  } catch (e) {
    results.value = []
    resultTotal.value = 0
    resultsError.value = e?.message || '质量结果加载失败'
  } finally {
    resultsLoading.value = false
  }
}

function reloadRules() {
  rulePage.value = 1
  loadRules()
  resultPage.value = 1
  loadResults()
}

function goRulePage(next) {
  rulePage.value = Math.min(Math.max(1, next), rulePages.value)
  loadRules()
}

function goResultPage(next) {
  resultPage.value = Math.min(Math.max(1, next), resultPages.value)
  loadResults()
}

function reloadResults() {
  resultPage.value = 1
  loadResults()
}

function openCreate() {
  Object.assign(form, emptyForm())
  form.pipeline = rulePipeline.value || ''
  form.paramsText = '{}'
  formError.value = ''
  formOpen.value = true
}

function openEdit(rule) {
  Object.assign(form, emptyForm())
  form.id = rule.id
  form.name = rule.name || ''
  form.pipeline = rule.pipeline ? String(rule.pipeline) : ''
  form.rule_type = rule.rule_type || 'not_null'
  form.field = rule.field || ''
  form.severity = rule.severity || 'error'
  form.enabled = rule.enabled !== false
  form.paramsText = JSON.stringify(rule.params || {}, null, 2)
  form.description = rule.description || ''
  formError.value = ''
  formOpen.value = true
}

function onTypeChange() {
  form.paramsText = typeHint.value
}

function parseParams() {
  const text = String(form.paramsText || '').trim()
  if (!text) return {}
  const parsed = JSON.parse(text)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('规则参数必须是 JSON 对象')
  }
  return parsed
}

async function saveRule() {
  if (!form.name.trim()) {
    formError.value = '规则名称不能为空'
    return
  }
  let params
  try {
    params = parseParams()
  } catch (e) {
    formError.value = e?.message || '参数 JSON 解析失败'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    const payload = {
      name: form.name.trim(),
      pipeline: form.pipeline ? Number(form.pipeline) : null,
      rule_type: form.rule_type,
      field: form.field.trim(),
      severity: form.severity,
      enabled: form.enabled,
      params,
      description: form.description.trim(),
    }
    if (form.id) {
      await api.update(`quality/rules/${form.id}/update/`, payload)
      app.toastMsg('规则已更新', 'success')
    } else {
      await api.create('quality/rules/', payload)
      app.toastMsg('规则已创建', 'success')
    }
    formOpen.value = false
    await Promise.all([loadRules(), loadResults()])
  } catch (e) {
    formError.value = e?.message || '保存规则失败'
    app.toastMsg(formError.value, 'error')
  } finally {
    saving.value = false
  }
}

function openTest(rule) {
  testRule.value = rule
  testRunId.value = ''
  testResult.value = null
  testError.value = ''
  testRaw.value = ''
  testOpen.value = true
}

async function submitTest() {
  if (!testRule.value) return
  testing.value = true
  testError.value = ''
  testResult.value = null
  try {
    const payload = {}
    if (testRunId.value.trim()) payload.run_id = Number(testRunId.value.trim())
    const data = await api.action(`quality/rules/${testRule.value.id}/test/`, payload)
    testResult.value = {
      passed: Boolean(data?.passed ?? data?.result?.passed),
      checked_rows: data?.checked_rows ?? data?.result?.checked_rows ?? 0,
      failed_rows: data?.failed_rows ?? data?.result?.failed_rows ?? 0,
      duration_ms: data?.duration_ms ?? data?.result?.duration_ms ?? 0,
      message: data?.message || data?.result?.message || '',
      sample: data?.sample || data?.result?.sample || [],
    }
    testRaw.value = JSON.stringify(data, null, 2)
    if (testResult.value.passed) app.toastMsg('规则测试通过', 'success')
    else app.toastMsg('规则测试未通过', 'error')
    await Promise.all([loadRules(), loadResults()])
  } catch (e) {
    testError.value = e?.message || '规则测试失败'
    app.toastMsg(testError.value, 'error')
  } finally {
    testing.value = false
  }
}

function askDelete(rule) {
  deleteTarget.value = rule
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  saving.value = true
  try {
    await api.action(`quality/rules/${deleteTarget.value.id}/delete/`)
    app.toastMsg('规则已删除', 'success')
    deleteOpen.value = false
    deleteTarget.value = null
    await Promise.all([loadRules(), loadResults()])
  } catch (e) {
    app.toastMsg(e?.message || '删除规则失败', 'error')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadRules()
  loadResults()
})
</script>