<template>
  <div class="space-y-3">
    <div class="card flex flex-wrap items-end gap-2 p-3">
      <label class="flex min-w-[180px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
        关键词
        <input v-model="q" class="input" placeholder="决策表名称 / 说明" @keyup.enter="applyFilters" />
      </label>
      <label class="flex w-[140px] flex-col gap-1 text-[11px] text-ink-500">
        状态
        <select v-model="status" class="input" @change="applyFilters">
          <option value="">全部状态</option>
          <option value="enabled">启用</option>
          <option value="disabled">停用</option>
        </select>
      </label>
      <span class="tag mb-1">{{ scopeLabel }}</span>
      <button class="btn-outline" :disabled="loading" @click="applyFilters">查询</button>
      <button class="btn-ghost" :disabled="loading" @click="resetFilters">重置</button>
      <button class="btn-primary ml-auto" :disabled="!rulesetId" @click="openCreate">
        新建决策表
      </button>
    </div>

    <div v-if="!rulesetId" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      新建决策表需要先在页面顶部选择一个规则集；列表默认展示当前用户可见的全部决策表。
    </div>
    <div v-if="listNotice" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      {{ listNotice }}
    </div>

    <div class="card overflow-hidden">
      <div class="flex items-center justify-between border-b border-ink-100 px-3 py-2">
        <span class="text-[13px] font-medium text-ink-700">决策表列表</span>
        <span class="text-[11px] text-ink-400">共 {{ total }} 张 · 第 {{ page }}/{{ pages }} 页</span>
      </div>

      <div v-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="listError" class="flex items-center gap-3 bg-rose-50 px-3 py-3 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ listError }}</span>
        <button class="shrink-0 font-medium" @click="loadList">重试</button>
      </div>
      <div v-else-if="!items.length" class="px-3 py-12 text-center text-[12px] text-ink-400">
        暂无决策表，选择规则集后点击「新建决策表」
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[880px]">
          <thead class="bg-ink-50/60">
            <tr>
              <th class="th">名称</th>
              <th class="th">说明</th>
              <th class="th">输入列</th>
              <th class="th">输出列</th>
              <th class="th">命中策略</th>
              <th class="th">状态</th>
              <th class="th">更新时间</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in items" :key="row.id" class="hover:bg-ink-50/50">
              <td class="td">
                <button class="max-w-[200px] truncate text-left font-medium text-brand-600" @click="openEditor(row)">
                  {{ row.name }}
                </button>
                <div class="text-[11px] text-ink-400">#{{ row.id }} · 规则集 {{ row.ruleset_id }}</div>
              </td>
              <td class="td max-w-[200px] truncate text-[12px] text-ink-500">{{ row.description || '—' }}</td>
              <td class="td text-[12px]">{{ (row.inputs || []).map((c) => c.name).join('、') || '—' }}</td>
              <td class="td text-[12px]">{{ (row.outputs || []).map((c) => c.name).join('、') || '—' }}</td>
              <td class="td text-[12px]">{{ hitPolicyLabel(row.hit_policy) }}</td>
              <td class="td">
                <span class="tag" :class="row.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                  {{ row.enabled ? '启用' : '停用' }}
                </span>
              </td>
              <td class="td text-[12px] text-ink-500">{{ fmtDate(row.updated_at) }}</td>
              <td class="td">
                <div class="flex justify-end gap-1">
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="openEditor(row)">编辑</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px]" @click="openEditor(row, true)">求值</button>
                  <button class="btn-ghost px-2 py-0.5 text-[11px] text-rose-600" @click="askDelete(row)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex items-center justify-between border-t border-ink-100 px-3 py-2">
        <span class="text-[11px] text-ink-400">每页 {{ pageSize }} 条</span>
        <div class="flex items-center gap-1">
          <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
          <span class="px-2 text-[12px] text-ink-500">{{ page }} / {{ pages }}</span>
          <button class="btn-ghost px-2 py-0.5 text-[12px]" :disabled="page >= pages || loading" @click="goPage(page + 1)">下一页</button>
        </div>
      </div>
    </div>

    <!-- 新建决策表 -->
    <Modal v-model="createShow" title="新建决策表" width="720px">
      <div v-if="createError" class="mb-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ createError }}</div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="flex flex-col gap-1 text-[12px] text-ink-600 sm:col-span-2">
          名称
          <input v-model.trim="createForm.name" class="input" placeholder="如 订单金额分档" />
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600">
          命中策略
          <select v-model="createForm.hit_policy" class="input">
            <option v-for="item in HIT_POLICY_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label class="flex items-center gap-2 pt-5 text-[12px] text-ink-600">
          <input v-model="createForm.enabled" type="checkbox" class="h-3.5 w-3.5" />
          创建后立即启用
        </label>
        <label class="flex flex-col gap-1 text-[12px] text-ink-600 sm:col-span-2">
          说明
          <input v-model.trim="createForm.description" class="input" placeholder="业务用途与维护说明" />
        </label>
      </div>

      <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <div class="mb-1 flex items-center justify-between">
            <span class="text-[12px] font-medium text-ink-700">输入列</span>
            <button class="btn-ghost py-0.5 text-[11px]" @click="createForm.inputs.push({ name: '', field: '', type: 'auto' })">添加</button>
          </div>
          <div v-if="!createForm.inputs.length" class="text-[11px] text-ink-400">至少配置一个输入列</div>
          <div v-for="(col, i) in createForm.inputs" :key="`ci-${i}`" class="mb-1 flex items-center gap-1">
            <input v-model.trim="col.name" class="input py-1 text-[12px]" placeholder="列名" />
            <input v-model.trim="col.field" class="input py-1 text-[12px]" placeholder="facts.amount" />
            <button class="btn-ghost px-1.5 py-0.5 text-[11px]" @click="createForm.inputs.splice(i, 1)">删</button>
          </div>
        </div>
        <div>
          <div class="mb-1 flex items-center justify-between">
            <span class="text-[12px] font-medium text-ink-700">输出列</span>
            <button class="btn-ghost py-0.5 text-[11px]" @click="createForm.outputs.push({ name: '', field: '', type: 'auto' })">添加</button>
          </div>
          <div v-if="!createForm.outputs.length" class="text-[11px] text-ink-400">至少配置一个输出列</div>
          <div v-for="(col, i) in createForm.outputs" :key="`co-${i}`" class="mb-1 flex items-center gap-1">
            <input v-model.trim="col.name" class="input py-1 text-[12px]" placeholder="列名" />
            <input v-model.trim="col.field" class="input py-1 text-[12px]" placeholder="outputs.level" />
            <button class="btn-ghost px-1.5 py-0.5 text-[11px]" @click="createForm.outputs.splice(i, 1)">删</button>
          </div>
        </div>
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="createShow = false">取消</button>
        <button class="btn-primary" :disabled="creating" @click="createTable">{{ creating ? '创建中…' : '创建并编辑' }}</button>
      </div>
    </Modal>

    <!-- 决策表编辑器 -->
    <Modal v-model="editorShow" :title="editor.name ? `决策表 · ${editor.name}` : '决策表编辑器'" width="1180px">
      <div v-if="editorLoading" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="editorError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ editorError }}</span>
        <button class="shrink-0 font-medium" @click="reloadEditor">重试</button>
      </div>
      <template v-else>
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag">规则集 {{ editor.ruleset_id }}</span>
          <span class="tag">{{ hitPolicyLabel(editor.hit_policy) }}</span>
          <span class="tag" :class="editor.enabled ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
            {{ editor.enabled ? '启用' : '停用' }}
          </span>
          <span class="tag" :class="dirty ? 'bg-amber-50 text-amber-600' : ''">{{ dirty ? '有未保存修改' : '已同步' }}</span>
          <div class="ml-auto flex gap-1.5">
            <button class="btn-outline py-1 text-[11px]" :disabled="savingRows" @click="saveAll">
              {{ savingRows ? '保存中…' : '批量保存' }}
            </button>
            <button class="btn-ghost py-1 text-[11px]" :disabled="editorLoading" @click="reloadEditor">重新加载</button>
          </div>
        </div>

        <!-- 列配置 -->
        <div class="mt-3 grid gap-2 sm:grid-cols-2">
          <div class="rounded-control border border-ink-100 p-2">
            <div class="mb-1 flex items-center justify-between">
              <span class="text-[12px] font-medium text-ink-700">输入列</span>
              <button class="btn-ghost py-0.5 text-[11px]" @click="addColumn('inputs')">添加列</button>
            </div>
            <div v-if="!editor.inputs.length" class="py-2 text-[11px] text-ink-400">暂无输入列，求值不会命中任何行</div>
            <div v-for="(col, i) in editor.inputs" :key="`ei-${i}`" class="mb-1 flex items-center gap-1">
              <input v-model.trim="col.name" class="input py-1 text-[12px]" placeholder="列名" @input="dirty = true" />
              <input v-model.trim="col.field" class="input py-1 font-mono text-[12px]" placeholder="facts.amount" @input="dirty = true" />
              <button class="btn-ghost px-1.5 py-0.5 text-[11px]" @click="removeColumn('inputs', i)">删</button>
            </div>
          </div>
          <div class="rounded-control border border-ink-100 p-2">
            <div class="mb-1 flex items-center justify-between">
              <span class="text-[12px] font-medium text-ink-700">输出列</span>
              <button class="btn-ghost py-0.5 text-[11px]" @click="addColumn('outputs')">添加列</button>
            </div>
            <div v-if="!editor.outputs.length" class="py-2 text-[11px] text-ink-400">暂无输出列，求值结果为空</div>
            <div v-for="(col, i) in editor.outputs" :key="`eo-${i}`" class="mb-1 flex items-center gap-1">
              <input v-model.trim="col.name" class="input py-1 text-[12px]" placeholder="列名" @input="dirty = true" />
              <input v-model.trim="col.field" class="input py-1 font-mono text-[12px]" placeholder="level" @input="dirty = true" />
              <button class="btn-ghost px-1.5 py-0.5 text-[11px]" @click="removeColumn('outputs', i)">删</button>
            </div>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap items-end gap-2">
          <label class="flex w-[160px] flex-col gap-1 text-[11px] text-ink-500">
            名称
            <input v-model.trim="editor.name" class="input py-1 text-[12px]" @input="dirty = true" />
          </label>
          <label class="flex w-[160px] flex-col gap-1 text-[11px] text-ink-500">
            命中策略
            <select v-model="editor.hit_policy" class="input py-1 text-[12px]" @change="dirty = true">
              <option v-for="item in HIT_POLICY_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
          <label class="flex min-w-[220px] flex-1 flex-col gap-1 text-[11px] text-ink-500">
            说明
            <input v-model.trim="editor.description" class="input py-1 text-[12px]" @input="dirty = true" />
          </label>
          <label class="flex items-center gap-1.5 pb-1.5 text-[12px] text-ink-600">
            <input v-model="editor.enabled" type="checkbox" class="h-3.5 w-3.5" @change="dirty = true" />
            启用
          </label>
          <button class="btn-ghost mb-0.5 py-1 text-[11px]" @click="addRow">新增行</button>
        </div>

        <!-- 数据行 -->
        <div class="mt-2 overflow-x-auto rounded-control border border-ink-100">
          <table class="w-full min-w-[820px]">
            <thead class="bg-ink-50/70">
              <tr>
                <th class="th w-14">行号</th>
                <th v-for="col in editor.inputs" :key="`hi-${col.name}`" class="th">
                  {{ col.name || col.field || '输入' }}
                </th>
                <th v-for="col in editor.outputs" :key="`ho-${col.name}`" class="th text-brand-700">
                  {{ col.name || col.field || '输出' }}
                </th>
                <th class="th w-20">优先级</th>
                <th class="th w-16">启用</th>
                <th class="th w-32">备注</th>
                <th class="th w-14"></th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-if="!editorRows.length">
                <td :colspan="editor.inputs.length + editor.outputs.length + 5" class="td py-8 text-center text-ink-400">
                  还没有数据行，点击「新增行」开始配置
                </td>
              </tr>
              <tr v-for="(row, index) in editorRows" :key="row.id || `new-${index}`">
                <td class="td text-[11px] text-ink-400">{{ index + 1 }}</td>
                <td v-for="col in editor.inputs" :key="`ic-${col.name}`" class="td">
                  <input
                    v-model.trim="row.conditions[colKey(col)]"
                    class="input min-w-[96px] py-1 text-[12px]"
                    placeholder="* 通配"
                    @input="dirty = true"
                  />
                </td>
                <td v-for="col in editor.outputs" :key="`oc-${col.name}`" class="td">
                  <input
                    v-model.trim="row.outputs[colKey(col)]"
                    class="input min-w-[88px] py-1 text-[12px]"
                    placeholder="输出值"
                    @input="dirty = true"
                  />
                </td>
                <td class="td">
                  <input v-model.number="row.priority" type="number" class="input w-[72px] py-1 text-[12px]" @input="dirty = true" />
                </td>
                <td class="td">
                  <input v-model="row.enabled" type="checkbox" class="h-3.5 w-3.5" @change="dirty = true" />
                </td>
                <td class="td">
                  <input v-model.trim="row.remark" class="input py-1 text-[12px]" placeholder="备注" @input="dirty = true" />
                </td>
                <td class="td">
                  <button class="btn-ghost px-1.5 py-0.5 text-[11px] text-rose-600" @click="deleteRow(index)">删</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="mt-1 text-[11px] text-ink-400">
          条件单元格支持 * 通配、&gt;100、100..200、A|B 等写法；输出按文本保存，可写数字、true/false 或 JSON。
        </p>

        <!-- 在线求值 -->
        <div class="mt-4 rounded-control border border-ink-100 p-3">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="text-[13px] font-medium text-ink-700">在线求值</span>
            <div class="flex gap-1.5">
              <button class="btn-ghost py-1 text-[11px]" @click="fillSampleFacts">载入示例事实</button>
              <button class="btn-primary py-1 text-[11px]" :disabled="evaluating || !editor.id" @click="evaluateTable">
                {{ evaluating ? '求值中…' : '使用已保存行求值' }}
              </button>
            </div>
          </div>
          <textarea
            v-model="evalFacts"
            class="input mt-2 min-h-[88px] font-mono text-[12px]"
            placeholder='{"amount": 1200, "channel": "app"}'
          ></textarea>
          <div v-if="evalError" class="mt-2 rounded-control bg-rose-50 px-2 py-2 text-[12px] text-rose-600">{{ evalError }}</div>
          <div v-else-if="evalResult" class="mt-2 space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="tag" :class="evalResult.matched ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                {{ evalResult.matched ? '命中' : '未命中' }}
              </span>
              <span class="tag">命中行 {{ evalResult.matched_count ?? 0 }} / {{ evalResult.row_count ?? 0 }}</span>
              <span class="tag">策略 {{ hitPolicyLabel(evalResult.hit_policy) }}</span>
              <span class="tag">{{ evalResult.source === 'inline' ? '内存行' : '数据库行' }}</span>
              <span class="text-[11px] text-ink-400">
                行 ID：{{ (evalResult.matched_rows || []).map((r) => r.id).join('、') || '—' }}
              </span>
            </div>
            <div class="grid gap-2 lg:grid-cols-2">
              <div>
                <div class="mb-1 text-[12px] font-medium text-ink-600">输出</div>
                <pre class="max-h-[180px] overflow-auto rounded-control bg-ink-900 p-2 font-mono text-[11px] text-ink-100">{{ pretty(evalResult.outputs) }}</pre>
              </div>
              <div>
                <div class="mb-1 text-[12px] font-medium text-ink-600">逐行条件追踪</div>
                <div class="max-h-[180px] overflow-auto rounded-control border border-ink-100">
                  <div v-if="!evalResult.trace?.length" class="py-4 text-center text-[12px] text-ink-400">无追踪数据</div>
                  <div v-for="item in evalResult.trace" :key="item.row_id" class="border-b border-ink-50 px-2 py-1.5 last:border-0">
                    <div class="flex items-center gap-2 text-[11px]">
                      <span class="tag" :class="item.matched ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-500'">
                        行 {{ item.row_id }}
                      </span>
                      <span class="text-ink-400">优先级 {{ item.priority }}</span>
                      <span class="min-w-0 flex-1 truncate text-ink-400">{{ item.remark || '' }}</span>
                    </div>
                    <div class="mt-1 flex flex-wrap gap-1">
                      <span
                        v-for="(cell, ci) in item.cells || []"
                        :key="`${item.row_id}-${ci}`"
                        class="tag"
                        :class="cell.matched ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'"
                      >
                        {{ cell.column }}：{{ cell.cell }} vs {{ cell.value }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </Modal>

    <Modal v-model="confirm.show" :title="confirm.title" width="420px">
      <p class="text-[13px] text-ink-600">{{ confirm.text }}</p>
      <div class="mt-4 flex justify-end gap-2">
        <button class="btn-ghost" @click="confirm.show = false">取消</button>
        <button class="btn-primary !bg-rose-600 hover:!bg-rose-700" :disabled="confirm.busy" @click="runConfirm">
          确认删除
        </button>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import Modal from '../../components/Modal.vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { formatDate } from '../../composables/useDomainResource'

const props = defineProps({
  rulesetId: { type: [String, Number], default: '' },
  rulesets: { type: Array, default: () => [] },
  refreshKey: { type: Number, default: 0 },
})

const emit = defineEmits(['changed'])
const api = apiFor('rules')
const app = useAppStore()

const HIT_POLICY_OPTIONS = [
  { value: 'first', label: '首条命中' },
  { value: 'all', label: '全部命中' },
  { value: 'priority', label: '最高优先级命中' },
  { value: 'collect', label: '汇总所有命中输出' },
]

const items = ref([])
const q = ref('')
const status = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const loading = ref(false)
const listError = ref('')
const listNotice = ref('')

const createShow = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = ref(emptyCreate())

const editorShow = ref(false)
const editor = ref({})
const editorRows = ref([])
const editorLoading = ref(false)
const editorError = ref('')
const editorTargetId = ref('')
const savingRows = ref(false)
const dirty = ref(false)

const evalFacts = ref('{\n  "amount": 1200,\n  "channel": "app"\n}')
const evaluating = ref(false)
const evalResult = ref(null)
const evalError = ref('')

const confirm = ref({ show: false, title: '', text: '', busy: false, action: null })

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

const scopeLabel = computed(() => {
  if (!props.rulesetId) return '全部规则集'
  const found = props.rulesets.find((item) => String(item.id) === String(props.rulesetId))
  return found ? found.name : `规则集 #${props.rulesetId}`
})

function emptyCreate() {
  return {
    name: '',
    description: '',
    hit_policy: 'first',
    enabled: true,
    inputs: [{ name: 'amount', field: 'facts.amount', type: 'auto' }],
    outputs: [{ name: 'level', field: 'level', type: 'auto' }],
  }
}

function hitPolicyLabel(value) {
  const found = HIT_POLICY_OPTIONS.find((item) => item.value === value)
  return found ? found.label : value || '—'
}

function fmtDate(value) {
  return formatDate(value)
}

function pretty(value) {
  if (value === null || value === undefined) return '—'
  try {
    return JSON.stringify(value, null, 2)
  } catch (e) {
    return String(value)
  }
}

function isMissingEndpoint(e) {
  const s = e?.response?.status
  return s === 404 || s === 405 || s === 501
}

function buildParams() {
  const params = { page: page.value, page_size: pageSize.value }
  if (q.value.trim()) params.q = q.value.trim()
  if (status.value) params.status = status.value
  if (props.rulesetId) params.ruleset_id = props.rulesetId
  return params
}

async function loadList() {
  if (!api) {
    listError.value = '规则引擎接口不可用'
    return
  }
  loading.value = true
  listError.value = ''
  listNotice.value = ''
  try {
    const data = await api.list('tables/', buildParams())
    items.value = data.items || []
    total.value = Number(data.count) || 0
  } catch (e) {
    items.value = []
    total.value = 0
    if (isMissingEndpoint(e)) {
      listNotice.value = '当前后端未提供决策表接口，页面已降级为空态'
    } else {
      listError.value = e?.message || '决策表加载失败'
      app.toastMsg(listError.value, 'error')
    }
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  loadList()
}

function resetFilters() {
  q.value = ''
  status.value = ''
  page.value = 1
  loadList()
}

function goPage(next) {
  page.value = Math.min(Math.max(1, next), pages.value)
  loadList()
}

function openCreate() {
  if (!props.rulesetId) {
    app.toastMsg('请先在页面顶部选择规则集', 'error')
    return
  }
  createForm.value = emptyCreate()
  createError.value = ''
  createShow.value = true
}

function normalizeColumns(columns) {
  return (columns || [])
    .filter((col) => col && (col.name || col.field))
    .map((col) => ({
      name: String(col.name || col.field).trim(),
      field: String(col.field || col.name).trim(),
      type: col.type || 'auto',
    }))
}

async function createTable() {
  if (!createForm.value.name.trim()) {
    createError.value = '请填写决策表名称'
    return
  }
  const inputs = normalizeColumns(createForm.value.inputs)
  const outputs = normalizeColumns(createForm.value.outputs)
  if (!inputs.length || !outputs.length) {
    createError.value = '至少配置一个输入列与一个输出列'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    const created = await api.create('tables/', {
      ruleset_id: props.rulesetId,
      name: createForm.value.name.trim(),
      description: createForm.value.description,
      hit_policy: createForm.value.hit_policy,
      enabled: createForm.value.enabled,
      inputs,
      outputs,
    })
    app.toastMsg('决策表已创建', 'success')
    createShow.value = false
    await loadList()
    emit('changed')
    if (created?.id) await openEditor(created)
  } catch (e) {
    createError.value = e?.message || '创建失败'
    app.toastMsg(createError.value, 'error')
  } finally {
    creating.value = false
  }
}

function colKey(col) {
  return col.name || col.field
}

function cellToText(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.join('|')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function coerceValue(text) {
  const raw = String(text ?? '').trim()
  if (raw === '') return ''
  if (/^-?\d+(\.\d+)?$/.test(raw)) return Number(raw)
  if (raw === 'true') return true
  if (raw === 'false') return false
  return raw
}

function comparePriority(a, b) {
  return (Number(a.priority) || 0) - (Number(b.priority) || 0)
}

async function openEditor(row, focusEval = false) {
  editorShow.value = true
  editorTargetId.value = row.id
  editor.value = {}
  editorRows.value = []
  evalResult.value = null
  evalError.value = ''
  dirty.value = false
  await loadEditor(row.id)
  if (focusEval) evalFacts.value = evalFacts.value || '{}'
}

async function loadEditor(id) {
  if (!api || !id) return
  editorLoading.value = true
  editorError.value = ''
  try {
    const data = await api.get(`tables/${id}/`)
    editor.value = {
      id: data.id,
      ruleset_id: data.ruleset_id,
      name: data.name || '',
      description: data.description || '',
      hit_policy: data.hit_policy || 'first',
      enabled: data.enabled !== false,
      inputs: normalizeColumns(data.inputs),
      outputs: normalizeColumns(data.outputs),
    }
    editorRows.value = (data.rows || []).map((row) => ({
      id: row.id,
      conditions: mapCells(row.conditions, editor.value.inputs),
      outputs: mapCells(row.outputs, editor.value.outputs),
      priority: Number(row.priority) || 0,
      enabled: row.enabled !== false,
      remark: row.remark || '',
    }))
    dirty.value = false
  } catch (e) {
    editor.value = {}
    editorRows.value = []
    editorError.value = e?.message || '决策表详情加载失败'
    app.toastMsg(editorError.value, 'error')
  } finally {
    editorLoading.value = false
  }
}

function mapCells(source, columns) {
  const out = {}
  const raw = source || {}
  for (const col of columns) {
    const key = colKey(col)
    const value = raw[col.name] !== undefined ? raw[col.name] : raw[col.field]
    out[key] = cellToText(value)
  }
  return out
}

async function reloadEditor() {
  if (editorTargetId.value) await loadEditor(editorTargetId.value)
}

function addColumn(kind) {
  editor.value[kind].push({ name: '', field: '', type: 'auto' })
  dirty.value = true
}

function removeColumn(kind, index) {
  editor.value[kind].splice(index, 1)
  dirty.value = true
}

function addRow() {
  editorRows.value.push({
    id: null,
    conditions: {},
    outputs: {},
    priority: (editorRows.value.length + 1) * 10,
    enabled: true,
    remark: '',
  })
  dirty.value = true
}

function deleteRow(index) {
  const row = editorRows.value[index]
  if (!row) return
  if (!row.id) {
    editorRows.value.splice(index, 1)
    dirty.value = true
    return
  }
  confirm.value = {
    show: true,
    title: '删除数据行',
    text: `删除第 ${index + 1} 行后无法恢复，确认继续？`,
    busy: false,
    action: async () => {
      confirm.value.busy = true
      try {
        await api.action(`rows/${row.id}/delete/`, {})
        app.toastMsg('数据行已删除', 'success')
        editorRows.value.splice(index, 1)
        await loadEditor(editor.value.id)
      } catch (e) {
        app.toastMsg(e?.message || '删除失败', 'error')
      } finally {
        confirm.value.busy = false
      }
    },
  }
}

async function saveAll() {
  if (!editor.value.id) return
  savingRows.value = true
  try {
    const inputs = normalizeColumns(editor.value.inputs)
    const outputs = normalizeColumns(editor.value.outputs)
    await api.post(`tables/${editor.value.id}/`, {
      name: editor.value.name,
      description: editor.value.description,
      hit_policy: editor.value.hit_policy,
      enabled: editor.value.enabled,
      inputs,
      outputs,
    })
    const rows = editorRows.value.map((row) => {
      const conditions = {}
      for (const col of inputs) {
        const text = row.conditions[colKey(col)]
        if (text !== undefined && String(text).trim() !== '') conditions[col.name] = String(text).trim()
      }
      const out = {}
      for (const col of outputs) {
        const text = row.outputs[colKey(col)]
        if (text !== undefined) out[col.name] = coerceValue(text)
      }
      const item = {
        conditions,
        outputs: out,
        priority: Number(row.priority) || 0,
        enabled: !!row.enabled,
        remark: row.remark || '',
      }
      if (row.id) item.id = row.id
      return item
    })
    await api.action(`tables/${editor.value.id}/rows/bulk/`, { rows })
    app.toastMsg('决策表已保存', 'success')
    dirty.value = false
    await loadEditor(editor.value.id)
    await loadList()
    emit('changed')
  } catch (e) {
    app.toastMsg(e?.message || '保存失败', 'error')
  } finally {
    savingRows.value = false
  }
}

function fillSampleFacts() {
  const sample = {}
  for (const col of editor.value.inputs || []) {
    const path = String(col.field || '').replace(/^facts\./, '')
    if (!path) continue
    sample[path] = 100
  }
  evalFacts.value = JSON.stringify(sample, null, 2)
}

async function evaluateTable() {
  if (!editor.value.id) return
  evaluating.value = true
  evalError.value = ''
  evalResult.value = null
  let facts
  try {
    facts = evalFacts.value.trim() ? JSON.parse(evalFacts.value) : {}
  } catch (e) {
    evaluating.value = false
    evalError.value = '事实 JSON 解析失败，请检查格式'
    return
  }
  try {
    evalResult.value = await api.action(`tables/${editor.value.id}/evaluate/`, { facts })
    app.toastMsg(evalResult.value?.matched ? '已命中决策行' : '未命中任何决策行', 'success')
  } catch (e) {
    evalError.value = e?.message || '求值失败'
    app.toastMsg(evalError.value, 'error')
  } finally {
    evaluating.value = false
  }
}

function askDelete(row) {
  confirm.value = {
    show: true,
    title: '删除决策表',
    text: `删除「${row.name}」会移除全部数据行，操作不可撤销。`,
    busy: false,
    action: async () => {
      confirm.value.busy = true
      try {
        await api.action(`tables/${row.id}/delete/`, {})
        app.toastMsg('决策表已删除', 'success')
        if (editor.value.id === row.id) editorShow.value = false
        await loadList()
        emit('changed')
      } catch (e) {
        app.toastMsg(e?.message || '删除失败', 'error')
      } finally {
        confirm.value.busy = false
      }
    },
  }
}

async function runConfirm() {
  const action = confirm.value.action
  confirm.value.show = false
  if (typeof action === 'function') await action()
}

watch(
  () => [props.refreshKey, props.rulesetId],
  () => loadList()
)

onMounted(loadList)
</script>