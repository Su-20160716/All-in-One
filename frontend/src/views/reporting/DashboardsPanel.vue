<template>
  <section class="space-y-3">
    <!-- 列表视图 -->
    <template v-if="!detail">
      <div class="card flex flex-wrap items-center gap-2 p-3">
        <input v-model="q" class="input w-56" placeholder="搜索仪表盘名称 / 描述" />
        <select v-model="status" class="input w-28">
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="archived">已归档</option>
        </select>
        <span class="tag">共 {{ count }} 个</span>
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <button class="btn-ghost" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
          <button class="btn-primary" @click="openCreate">新建仪表盘</button>
        </div>
      </div>

      <div class="card p-0">
        <div class="border-b border-ink-100 px-4 py-2.5">
          <h3 class="text-[14px] font-semibold text-ink-800">仪表盘列表</h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            仪表盘从报表组件池中挑选组件拼装，打开时优先复用报表最新快照，避免一次打开触发全量重算。
          </p>
        </div>

        <div v-if="loading && !items.length" class="space-y-2 p-4">
          <div v-for="n in 5" :key="`sk-${n}`" class="h-9 animate-pulse rounded-control bg-ink-50"></div>
        </div>
        <div v-else-if="unavailable" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800">
          <span class="min-w-0 flex-1">{{ unavailable }}。已降级为空态。</span>
          <button class="font-medium text-brand-600" @click="load">重试</button>
        </div>
        <div v-else-if="error" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-rose-50 px-3 py-2.5 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ error }}</span>
          <button class="font-medium" @click="load">重试</button>
        </div>
        <div v-else-if="!items.length" class="px-4 py-12 text-center">
          <p class="text-[13px] text-ink-500">{{ q || status ? '当前筛选条件下没有仪表盘' : '还没有创建仪表盘' }}</p>
          <p class="mt-1 text-[11px] text-ink-400">创建后可添加报表组件，按 12 栏网格排列 KPI、表格与图表。</p>
          <button class="btn-primary mt-3" @click="openCreate">新建仪表盘</button>
        </div>
        <div v-else class="overflow-auto">
          <table class="w-full min-w-[840px]">
            <thead class="bg-ink-50">
              <tr>
                <th class="th">名称</th>
                <th class="th">描述</th>
                <th class="th w-24">状态</th>
                <th class="th w-24 text-right">组件数</th>
                <th class="th w-36">更新时间</th>
                <th class="th w-52">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in items" :key="row.id" class="hover:bg-ink-50/50">
                <td class="td">
                  <button class="max-w-[220px] truncate text-left text-[13px] font-medium text-ink-800 hover:text-brand-600" @click="openDetail(row)">
                    {{ row.name || '未命名仪表盘' }}
                  </button>
                </td>
                <td class="td">
                  <span class="block max-w-[360px] truncate text-[11px] text-ink-500" :title="row.description">{{ row.description || '—' }}</span>
                </td>
                <td class="td">
                  <span class="tag" :class="row.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-600'">
                    {{ row.status === 'active' ? '启用' : '已归档' }}
                  </span>
                </td>
                <td class="td text-right tabular-nums">{{ row.widget_count ?? 0 }}</td>
                <td class="td text-[11px] text-ink-500">{{ fmtDT(row.updated_at) }}</td>
                <td class="td">
                  <div class="flex flex-wrap gap-x-2.5 gap-y-1 text-[11px]">
                    <button class="text-brand-600 hover:underline" @click="openDetail(row)">打开</button>
                    <button class="text-brand-600 hover:underline" @click="openEdit(row)">编辑</button>
                    <button class="text-ink-500 hover:text-brand-600" @click="exportDashboard(row, 'csv')">导出 CSV</button>
                    <button class="text-ink-500 hover:text-brand-600" @click="exportDashboard(row, 'json')">导出 JSON</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="count > 0" class="flex flex-wrap items-center justify-between gap-2 border-t border-ink-100 px-4 py-2.5 text-[12px] text-ink-500">
          <span>第 {{ page }} / {{ totalPages }} 页，共 {{ count }} 条</span>
          <div class="flex items-center gap-1">
            <button class="btn-outline px-2 py-0.5" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
            <button class="btn-outline px-2 py-0.5" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 详情视图 -->
    <template v-else>
      <div class="card p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <button class="text-[12px] text-brand-600" @click="closeDetail">返回列表</button>
              <span class="text-ink-300">/</span>
              <h3 class="truncate text-[16px] font-semibold text-ink-900">{{ detail.dashboard?.name || '仪表盘' }}</h3>
              <span class="tag" :class="detail.dashboard?.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-600'">
                {{ detail.dashboard?.status === 'active' ? '启用' : '已归档' }}
              </span>
              <span class="tag">{{ detail.meta?.widget_count ?? widgets.length }} 个组件</span>
              <span v-if="detail.meta?.failed_widgets" class="tag bg-rose-50 text-rose-600">
                {{ detail.meta.failed_widgets }} 个失败
              </span>
            </div>
            <p class="mt-1 max-w-3xl text-[12px] text-ink-500">{{ detail.dashboard?.description || '暂无描述' }}</p>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <button class="btn-ghost" :disabled="detailLoading" @click="refreshDetail">{{ detailLoading ? '加载中…' : '刷新数据' }}</button>
            <button class="btn-outline" @click="openAddWidget">添加组件</button>
            <button class="btn-outline" @click="openEdit(detail.dashboard)">编辑</button>
            <button class="btn-outline" @click="exportDashboard(detail.dashboard, 'csv')">导出 CSV</button>
            <button class="btn-outline" @click="exportDashboard(detail.dashboard, 'json')">导出 JSON</button>
          </div>
        </div>

        <!-- 筛选器 -->
        <div class="mt-3 rounded-control border border-ink-100 bg-ink-50/50 p-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-[12px] font-medium text-ink-700">筛选器</span>
            <span class="tag">绑定参数 {{ filterFields.length }}</span>
            <button class="text-[11px] text-brand-600" :disabled="detailLoading" @click="applyFilters">应用</button>
            <button class="text-[11px] text-ink-500 hover:text-brand-600" :disabled="detailLoading" @click="resetFilters">重置</button>
          </div>
          <div v-if="filterFields.length" class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label v-for="field in filterFields" :key="field.key" class="block text-[11px] text-ink-500">
              <span class="mb-0.5 block truncate" :title="field.label">{{ field.label }}</span>
              <input v-model="filterValues[field.key]" class="input" :placeholder="field.placeholder || '不限制'" />
            </label>
          </div>
          <p v-else class="mt-2 text-[11px] text-ink-400">
            当前仪表盘的组件没有绑定筛选参数；可在报表组件里配置筛选器后重新打开。
          </p>
        </div>
      </div>

      <div v-if="detailLoading && !widgets.length" class="card grid gap-3 p-4 md:grid-cols-2">
        <div v-for="n in 4" :key="`dw-sk-${n}`" class="h-40 animate-pulse rounded-control bg-ink-50"></div>
      </div>
      <div v-else-if="detailError" class="card flex flex-wrap items-center gap-2 border-rose-200 bg-rose-50 p-4 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ detailError }}</span>
        <button class="font-medium" @click="reloadDetail">重试</button>
      </div>
      <div v-else-if="!widgets.length" class="card px-4 py-12 text-center">
        <p class="text-[13px] text-ink-500">仪表盘还没有组件</p>
        <p class="mt-1 text-[11px] text-ink-400">从报表组件池添加 KPI、表格或图表，按 12 栏网格拼装。</p>
        <button class="btn-primary mt-3" @click="openAddWidget">添加组件</button>
      </div>

      <div v-else class="flex flex-wrap gap-3">
        <div
          v-for="widget in widgets"
          :key="`dbw-${widget.id}`"
          class="card flex min-w-0 flex-col p-3"
          :style="widgetStyle(widget)"
        >
          <div class="mb-2 flex flex-wrap items-start justify-between gap-1.5">
            <div class="min-w-0">
              <div class="flex items-center gap-1.5">
                <h4 class="truncate text-[13px] font-medium text-ink-800">{{ widget.title || '未命名组件' }}</h4>
                <span class="tag">{{ typeLabel(widget.type) }}</span>
              </div>
              <p class="mt-0.5 truncate text-[10px] text-ink-400">
                {{ widget.report_name || '—' }} / {{ widget.config?.dataset_name || widget.dataset_id || '无数据集' }}
              </p>
            </div>
            <button
              class="shrink-0 text-[11px] text-ink-400 hover:text-rose-500"
              title="从仪表盘移除"
              @click="removeWidget(widget)"
            >移除</button>
          </div>

          <div v-if="widget.result?.meta?.error" class="rounded-control bg-rose-50 px-2.5 py-2 text-[11px] text-rose-600">
            {{ widget.result.meta.error }}
          </div>

          <template v-else-if="widget.type === 'kpi'">
            <StatCard
              :label="widget.title"
              :value="kpiValue(widget)"
              :unit="widget.result?.meta?.unit || ''"
              :hint="kpiHint(widget)"
            />
          </template>

          <template v-else-if="widget.type === 'text'">
            <p class="whitespace-pre-wrap text-[12px] leading-relaxed text-ink-600">
              {{ widget.result?.rows?.[0]?.text || '暂无文本内容' }}
            </p>
          </template>

          <template v-else-if="widget.type === 'bar'">
            <BarChart :data="barData(widget)" :height="widgetHeight(widget)" empty-text="组件没有可绘制的数据" />
          </template>

          <template v-else-if="widget.type === 'line'">
            <LineChart
              :series="lineSeries(widget)"
              :labels="lineLabels(widget)"
              :height="widgetHeight(widget)"
              empty-text="组件没有可绘制的数据"
            />
          </template>

          <template v-else-if="widget.type === 'pie'">
            <DonutChart
              :data="pieData(widget)"
              :size="Math.min(180, widgetHeight(widget) + 40)"
              legend-position="bottom"
              empty-text="组件没有可绘制的数据"
            />
          </template>

          <template v-else>
            <div class="max-h-[320px] overflow-auto rounded-control border border-ink-50">
              <table class="w-full min-w-[280px]">
                <thead class="bg-ink-50">
                  <tr>
                    <th v-for="col in widget.result?.columns || []" :key="col.key" class="th whitespace-nowrap text-[10px]">
                      {{ col.label || col.key }}
                    </th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="(row, idx) in tableRows(widget)" :key="`${widget.id}-r-${idx}`">
                    <td v-for="col in widget.result?.columns || []" :key="`${widget.id}-${col.key}-${idx}`" class="td whitespace-nowrap text-[10px]">
                      {{ cellText(row[col.key]) }}
                    </td>
                  </tr>
                  <tr v-if="!tableRows(widget).length">
                    <td class="td text-center text-[10px] text-ink-400" :colspan="Math.max(1, (widget.result?.columns || []).length)">
                      没有返回数据行
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>

          <div class="mt-1.5 flex flex-wrap items-center gap-2 border-t border-ink-50 pt-1 text-[10px] text-ink-400">
            <span v-if="widget.result?.meta?.cached || widget.result?.meta?.from_snapshot">来自快照</span>
            <span v-if="widget.config?.x">X 轴 {{ widget.config.x }}</span>
            <span v-if="Array.isArray(widget.config?.series) && widget.config.series.length">
              系列 {{ widget.config.series.join(' / ') }}
            </span>
            <span class="ml-auto">位置 {{ widget.position?.x ?? 0 }},{{ widget.position?.y ?? 0 }} · {{ widget.position?.w ?? 6 }}×{{ widget.position?.h ?? 4 }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- 新建 / 编辑仪表盘 -->
    <Modal :show="formOpen" :title="form.id ? '编辑仪表盘' : '新建仪表盘'" width="620px" @close="formOpen = false">
      <div class="space-y-3">
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">名称 <span class="text-rose-500">*</span></span>
          <input v-model="form.name" class="input" placeholder="如：经营驾驶舱" />
        </label>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">描述</span>
          <textarea v-model="form.description" class="input min-h-16" placeholder="说明看板的使用对象与刷新频率" />
        </label>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">主题</span>
            <select v-model="form.theme" class="input">
              <option value="light">浅色</option>
              <option value="dark">深色</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">状态</span>
            <select v-model="form.status" class="input">
              <option value="active">启用</option>
              <option value="archived">已归档</option>
            </select>
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">默认筛选（JSON 对象）</span>
          <textarea v-model="defaultFiltersText" class="input min-h-24 font-mono text-[12px]" placeholder='{"region": "华东"}' />
        </label>
        <div v-if="formError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ formError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="formOpen = false">取消</button>
          <button class="btn-primary" :disabled="saving" @click="saveDashboard">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </Modal>

    <!-- 添加组件 -->
    <Modal :show="addOpen" title="添加报表组件" width="720px" @close="addOpen = false">
      <div class="space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <input v-model="availableQ" class="input w-56" placeholder="搜索组件标题" />
          <button class="btn-ghost" :disabled="availableLoading" @click="loadAvailable">
            {{ availableLoading ? '加载中…' : '搜索' }}
          </button>
          <span class="tag">{{ availableWidgets.length }} 个候选</span>
        </div>
        <div v-if="availableError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ availableError }}</div>
        <div v-else-if="availableLoading && !availableWidgets.length" class="py-8 text-center text-[12px] text-ink-400">候选组件加载中…</div>
        <div v-else-if="!availableWidgets.length" class="rounded-control bg-ink-50 px-3 py-6 text-center text-[12px] text-ink-400">
          没有可挂载的组件，请先在报表中添加组件
        </div>
        <div v-else class="max-h-64 overflow-auto rounded-control border border-ink-100">
          <button
            v-for="w in availableWidgets"
            :key="w.id"
            class="flex w-full items-center gap-2 border-b border-ink-50 px-3 py-2 text-left text-[12px] last:border-b-0"
            :class="selectedWidgetId === w.id ? 'bg-brand-50 text-brand-800' : 'hover:bg-ink-50'"
            @click="selectedWidgetId = w.id"
          >
            <span class="tag shrink-0">{{ typeLabel(w.type) }}</span>
            <span class="min-w-0 flex-1 truncate">{{ w.title }}</span>
            <span class="shrink-0 text-[10px] text-ink-400">{{ w.report_name }} / {{ w.page_title }}</span>
          </button>
        </div>
        <div class="grid gap-3 sm:grid-cols-3">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">覆盖标题</span>
            <input v-model="addTitle" class="input" placeholder="留空沿用组件标题" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">宽度（1-12）</span>
            <input v-model.number="addWidth" class="input" type="number" min="3" max="12" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">高度</span>
            <input v-model.number="addHeight" class="input" type="number" min="2" max="12" />
          </label>
        </div>
        <div v-if="addError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ addError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="addOpen = false">取消</button>
          <button class="btn-primary" :disabled="adding || !selectedWidgetId" @click="addWidget">
            {{ adding ? '添加中…' : '添加到仪表盘' }}
          </button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { reportingApi } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { saveBlob } from '../../utils/download'
import Modal from '../../components/Modal.vue'
import StatCard from '../../components/platform/StatCard.vue'
import BarChart from '../../components/platform/BarChart.vue'
import LineChart from '../../components/platform/LineChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const app = useAppStore()

const TYPE_LABELS = {
  table: '表格',
  bar: '柱状图',
  line: '折线图',
  pie: '饼图',
  kpi: '指标卡',
  pivot: '透视表',
  heatmap: '热力图',
  text: '文本',
}
const TABLE_ROW_LIMIT = 20

const items = ref([])
const count = ref(0)
const page = ref(1)
const pageSize = ref(20)
const q = ref('')
const status = ref('')
const loading = ref(false)
const error = ref('')
const unavailable = ref('')

const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const filterValues = ref({})
const filtersInitedId = ref(null)

const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref({})
const defaultFiltersText = ref('{}')

const addOpen = ref(false)
const availableWidgets = ref([])
const availableLoading = ref(false)
const availableError = ref('')
const availableQ = ref('')
const selectedWidgetId = ref(null)
const addTitle = ref('')
const addWidth = ref(6)
const addHeight = ref(4)
const adding = ref(false)
const addError = ref('')

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / Math.max(1, pageSize.value))))
const widgets = computed(() => (Array.isArray(detail.value?.widgets) ? detail.value.widgets : []))

const filterFields = computed(() => {
  const map = new Map()
  for (const link of detail.value?.links || []) {
    for (const f of link.widget?.filters || []) {
      const key = f.bound_param || f.field
      if (!key || map.has(key)) continue
      map.set(key, {
        key,
        label: f.label || f.bound_param || f.field,
        field: f.field,
        operator: f.operator,
        placeholder: f.default_value === null || f.default_value === undefined ? '' : String(f.default_value),
        default: f.default_value,
      })
    }
  }
  const defaults = detail.value?.dashboard?.default_filters
  if (defaults && typeof defaults === 'object') {
    for (const [key, value] of Object.entries(defaults)) {
      if (map.has(key)) continue
      map.set(key, {
        key,
        label: key,
        field: key,
        operator: 'eq',
        placeholder: value === null || value === undefined ? '' : String(value),
        default: value,
      })
    }
  }
  return Array.from(map.values())
})

function isUnavailable(e) {
  const s = Number(e?.status || e?.response?.status || 0)
  const message = String(e?.message || '')
  return s === 404 || s === 405 || /not found|method not allowed|405/i.test(message)
}

function pad(n) {
  return String(n).padStart(2, '0')
}

function fmtDT(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function typeLabel(value) {
  return TYPE_LABELS[value] || value || '组件'
}

function cellText(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function widgetHeight(widget) {
  const h = Number(widget?.position?.h) || 4
  return Math.max(150, Math.min(320, h * 40))
}

function widgetStyle(widget) {
  const w = Math.min(12, Math.max(3, Number(widget?.position?.w) || 6))
  return {
    flex: `1 1 ${(w / 12 * 100).toFixed(2)}%`,
    minWidth: '280px',
  }
}

function tableRows(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  return rows.slice(0, TABLE_ROW_LIMIT)
}

function axisKey(widget) {
  const meta = widget?.result?.meta || {}
  const columns = widget?.result?.columns || []
  return meta.x || meta.name || columns[0]?.key || ''
}

function seriesKeys(widget) {
  const meta = widget?.result?.meta || {}
  const columns = widget?.result?.columns || []
  if (Array.isArray(meta.series) && meta.series.length) return meta.series
  const metrics = columns.filter((c) => c.role === 'metric').map((c) => c.key)
  if (metrics.length) return metrics.slice(0, 3)
  return columns.slice(1, 3).map((c) => c.key)
}

function columnLabel(widget, key) {
  const col = (widget?.result?.columns || []).find((c) => c.key === key)
  return col?.label || key
}

function labelOf(widget, row, index) {
  const key = axisKey(widget)
  const value = key ? row[key] : index
  if (value === null || value === undefined || value === '') return `第 ${index + 1} 项`
  return String(value)
}

function barData(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  const key = seriesKeys(widget)[0]
  return rows.slice(0, 30).map((row, index) => ({
    label: labelOf(widget, row, index),
    value: Number(row[key]) || 0,
  }))
}

function lineLabels(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  return rows.slice(0, 60).map((row, index) => labelOf(widget, row, index))
}

function lineSeries(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  return seriesKeys(widget).map((key) => ({
    name: columnLabel(widget, key),
    data: rows.slice(0, 60).map((row) => {
      const n = Number(row[key])
      return Number.isFinite(n) ? n : null
    }),
  }))
}

function pieData(widget) {
  const rows = Array.isArray(widget?.result?.rows) ? widget.result.rows : []
  const key = seriesKeys(widget)[0]
  return rows.slice(0, 30).map((row, index) => ({
    label: labelOf(widget, row, index),
    value: Number(row[key]) || 0,
  }))
}

function kpiValue(widget) {
  const value = widget?.result?.rows?.[0]?.value
  if (value === null || value === undefined || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function kpiHint(widget) {
  const meta = widget?.result?.meta || {}
  const row = widget?.result?.rows?.[0] || {}
  const parts = []
  if (meta.formula) parts.push(`公式 ${meta.formula}`)
  if (meta.comparison && meta.comparison !== 'none') parts.push(`对照 ${meta.comparison}`)
  if (row.delta_pct !== null && row.delta_pct !== undefined) parts.push(`变化 ${Number(row.delta_pct).toFixed(1)}%`)
  return parts.join('，')
}

// ---------------------------------------------------------------------------
// 列表
// ---------------------------------------------------------------------------

async function load() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (status.value) params.status = status.value
    const data = await reportingApi.list('dashboards/', params)
    items.value = data.items
    count.value = data.count
  } catch (e) {
    items.value = []
    count.value = 0
    if (isUnavailable(e)) unavailable.value = '仪表盘列表接口不可用（404/405）'
    else {
      error.value = e?.message || '仪表盘列表加载失败'
      app.toastMsg(error.value, 'error')
    }
  } finally {
    loading.value = false
  }
}

function goPage(next) {
  const target = Math.min(Math.max(1, next), totalPages.value)
  if (target === page.value) return
  page.value = target
  load()
}

watch([q, status], () => {
  page.value = 1
  load()
})

// ---------------------------------------------------------------------------
// 详情
// ---------------------------------------------------------------------------

function buildParams() {
  const params = {}
  for (const [key, value] of Object.entries(filterValues.value)) {
    if (value !== '' && value !== null && value !== undefined) params[key] = value
  }
  return params
}

function initFilters() {
  const values = {}
  for (const field of filterFields.value) {
    values[field.key] = field.default === null || field.default === undefined ? '' : String(field.default)
  }
  filterValues.value = values
}

async function loadDetail(id, refresh = false) {
  detailLoading.value = true
  detailError.value = ''
  try {
    const query = []
    if (refresh) query.push('refresh=true')
    const params = buildParams()
    if (Object.keys(params).length) query.push(`params=${encodeURIComponent(JSON.stringify(params))}`)
    const suffix = query.length ? `?${query.join('&')}` : ''
    const data = await reportingApi.get(`dashboards/${id}/${suffix}`)
    detail.value = data
    const detailId = data?.dashboard?.id || id
    if (filtersInitedId.value !== detailId) {
      filtersInitedId.value = detailId
      initFilters()
    }
    if (!data?.widgets?.length && data?.meta?.failed_widgets) {
      app.toastMsg(`${data.meta.failed_widgets} 个组件执行失败`, 'error')
    }
  } catch (e) {
    detailError.value = isUnavailable(e) ? '仪表盘详情接口不可用（404/405）' : (e?.message || '仪表盘详情加载失败')
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function openDetail(row) {
  filtersInitedId.value = null
  detail.value = { dashboard: row, widgets: [], links: [], meta: {} }
  await loadDetail(row.id, false)
}

function closeDetail() {
  detail.value = null
  detailError.value = ''
  filterValues.value = {}
  filtersInitedId.value = null
  load()
}

function refreshDetail() {
  if (!detail.value?.dashboard?.id) return
  loadDetail(detail.value.dashboard.id, true)
}

function reloadDetail() {
  if (!detail.value?.dashboard?.id) return
  loadDetail(detail.value.dashboard.id, false)
}

function applyFilters() {
  if (!detail.value?.dashboard?.id) return
  loadDetail(detail.value.dashboard.id, true)
}

function resetFilters() {
  initFilters()
  if (!detail.value?.dashboard?.id) return
  loadDetail(detail.value.dashboard.id, true)
}

// ---------------------------------------------------------------------------
// 新建 / 编辑
// ---------------------------------------------------------------------------

function emptyForm() {
  return { id: null, name: '', description: '', theme: 'light', status: 'active' }
}

function openCreate() {
  form.value = emptyForm()
  defaultFiltersText.value = '{}'
  formError.value = ''
  formOpen.value = true
}

function openEdit(row) {
  if (!row) return
  form.value = {
    id: row.id,
    name: row.name || '',
    description: row.description || '',
    theme: row.theme || 'light',
    status: row.status || 'active',
  }
  defaultFiltersText.value = JSON.stringify(row.default_filters || {}, null, 2)
  formError.value = ''
  formOpen.value = true
}

async function saveDashboard() {
  const f = form.value
  if (!String(f.name || '').trim()) {
    formError.value = '请填写仪表盘名称'
    return
  }
  let defaultFilters
  try {
    const parsed = JSON.parse(defaultFiltersText.value || '{}')
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) defaultFilters = parsed
    else throw new Error('必须是 JSON 对象')
  } catch (e) {
    formError.value = `默认筛选格式错误：${e?.message || '必须是 JSON 对象'}`
    return
  }
  saving.value = true
  formError.value = ''
  try {
    const payload = {
      name: String(f.name).trim(),
      description: f.description || '',
      theme: f.theme || 'light',
      status: f.status || 'active',
      default_filters: defaultFilters,
      layout: { columns: 12 },
    }
    if (f.id) {
      await reportingApi.update(`dashboards/${f.id}/update/`, payload)
      app.toastMsg('仪表盘已保存', 'success')
    } else {
      await reportingApi.create('dashboards/create/', payload)
      app.toastMsg('仪表盘已创建', 'success')
    }
    formOpen.value = false
    if (detail.value && f.id) await loadDetail(f.id, false)
    else await load()
  } catch (e) {
    formError.value = e?.message || '保存失败'
    app.toastMsg(formError.value, 'error')
  } finally {
    saving.value = false
  }
}

// ---------------------------------------------------------------------------
// 组件挂载
// ---------------------------------------------------------------------------

async function openAddWidget() {
  addOpen.value = true
  availableWidgets.value = []
  selectedWidgetId.value = null
  addTitle.value = ''
  addWidth.value = 6
  addHeight.value = 4
  addError.value = ''
  availableQ.value = ''
  await loadAvailable()
}

async function loadAvailable() {
  availableLoading.value = true
  availableError.value = ''
  try {
    const data = await reportingApi.list('dashboards/available-widgets/', {
      page: 1,
      page_size: 100,
      q: availableQ.value.trim() || undefined,
    })
    availableWidgets.value = data.items
  } catch (e) {
    availableWidgets.value = []
    availableError.value = isUnavailable(e) ? '候选组件接口不可用（404/405）' : (e?.message || '候选组件加载失败')
  } finally {
    availableLoading.value = false
  }
}

async function addWidget() {
  if (!detail.value?.dashboard?.id || !selectedWidgetId.value) return
  adding.value = true
  addError.value = ''
  try {
    const override = {}
    if (addTitle.value.trim()) override.title = addTitle.value.trim()
    await reportingApi.action(`dashboards/${detail.value.dashboard.id}/widgets/add/`, {
      widget_id: Number(selectedWidgetId.value),
      override,
      w: Math.min(12, Math.max(3, Number(addWidth.value) || 6)),
      h: Math.min(12, Math.max(2, Number(addHeight.value) || 4)),
    })
    app.toastMsg('组件已添加', 'success')
    addOpen.value = false
    await loadDetail(detail.value.dashboard.id, true)
  } catch (e) {
    addError.value = e?.message || '添加组件失败'
    app.toastMsg(addError.value, 'error')
  } finally {
    adding.value = false
  }
}

async function removeWidget(widget) {
  if (!detail.value?.dashboard?.id) return
  if (!window.confirm(`从仪表盘移除「${widget.title || '该组件'}」？组件本身仍保留在报表中。`)) return
  try {
    await reportingApi.action(`dashboard-widgets/${widget.id}/remove/`, {})
    app.toastMsg('组件已移除', 'success')
    await loadDetail(detail.value.dashboard.id, false)
  } catch (e) {
    app.toastMsg(e?.message || '移除组件失败', 'error')
  }
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------

async function exportDashboard(row, fmt) {
  if (!row?.id) {
    app.toastMsg('请先选择仪表盘', 'error')
    return
  }
  try {
    const data = await reportingApi.action(`dashboards/${row.id}/export/`, {
      fmt,
      params: buildParams(),
    })
    if (!data?.content) {
      app.toastMsg('导出接口没有返回内容', 'error')
      return
    }
    const filename = data.filename || `dashboard-${row.id}.${fmt}`
    const mime = fmt === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8'
    saveBlob(new Blob([data.content], { type: mime }), filename)
    app.toastMsg(`已导出 ${filename}`, 'success')
  } catch (e) {
    app.toastMsg(e?.message || '导出失败', 'error')
  }
}

watch(() => props.reloadToken, () => {
  if (detail.value?.dashboard?.id) refreshDetail()
  else load()
})

onMounted(load)
</script>