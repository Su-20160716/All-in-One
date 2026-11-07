<template>
  <section class="space-y-3">
    <!-- 列表 -->
    <template v-if="!current">
      <div class="card flex flex-wrap items-center gap-2 p-3">
        <input v-model="q" class="input w-56" placeholder="搜索数据集名称 / 描述 / 模型" />
        <select v-model="status" class="input w-28">
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="inactive">停用</option>
        </select>
        <select v-model="modelFilter" class="input w-56">
          <option value="">全部主模型</option>
          <option v-for="m in models" :key="m.label" :value="m.label">{{ m.verbose_name }}（{{ m.label }}）</option>
        </select>
        <span class="tag">共 {{ count }} 个</span>
        <div class="ml-auto flex flex-wrap items-center gap-2">
          <button class="btn-ghost" :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
          <button class="btn-primary" @click="openCreate">新建数据集</button>
        </div>
      </div>

      <div class="card p-0">
        <div class="border-b border-ink-100 px-4 py-2.5">
          <h3 class="text-[14px] font-semibold text-ink-800">数据集</h3>
          <p class="mt-0.5 text-[11px] text-ink-400">
            数据集是报表组件的取数口径：主模型 + 过滤条件 + 去重字段 + 字段配置，预览只读取前 50 行。
          </p>
        </div>

        <div v-if="loading && !items.length" class="space-y-2 p-4">
          <div v-for="n in 5" :key="`sk-${n}`" class="h-9 animate-pulse rounded-control bg-ink-50"></div>
        </div>
        <div v-else-if="unavailable" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800">
          <span class="min-w-0 flex-1">{{ unavailable }}。已降级为空态，报表仍可读取历史组件。</span>
          <button class="font-medium text-brand-600" @click="load">重试</button>
        </div>
        <div v-else-if="error" class="m-4 flex flex-wrap items-center gap-2 rounded-control bg-rose-50 px-3 py-2.5 text-[12px] text-rose-600">
          <span class="min-w-0 flex-1">{{ error }}</span>
          <button class="font-medium" @click="load">重试</button>
        </div>
        <div v-else-if="!items.length" class="px-4 py-12 text-center">
          <p class="text-[13px] text-ink-500">{{ q || status || modelFilter ? '当前筛选条件下没有数据集' : '还没有创建数据集' }}</p>
          <p class="mt-1 text-[11px] text-ink-400">选择白名单模型，配置过滤与字段后即可被报表组件引用。</p>
          <button class="btn-primary mt-3" @click="openCreate">新建数据集</button>
        </div>
        <div v-else class="overflow-auto">
          <table class="w-full min-w-[1000px]">
            <thead class="bg-ink-50">
              <tr>
                <th class="th">名称</th>
                <th class="th w-64">主模型</th>
                <th class="th w-20 text-right">字段</th>
                <th class="th w-20 text-right">组件</th>
                <th class="th w-20">状态</th>
                <th class="th w-24 text-right">预览次数</th>
                <th class="th w-36">更新时间</th>
                <th class="th w-64">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="row in items" :key="row.id" class="hover:bg-ink-50/50">
                <td class="td">
                  <button class="max-w-[240px] truncate text-left text-[13px] font-medium text-ink-800 hover:text-brand-600" @click="openDataset(row)">
                    {{ row.name || '未命名数据集' }}
                  </button>
                  <div v-if="row.description" class="mt-0.5 max-w-[260px] truncate text-[10px] text-ink-400" :title="row.description">
                    {{ row.description }}
                  </div>
                </td>
                <td class="td">
                  <span class="block truncate font-mono text-[11px] text-ink-600" :title="row.primary_model">{{ row.primary_model || '—' }}</span>
                </td>
                <td class="td text-right tabular-nums">{{ row.field_count ?? 0 }}</td>
                <td class="td text-right tabular-nums">{{ row.widget_count ?? 0 }}</td>
                <td class="td">
                  <span class="tag" :class="row.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-ink-100 text-ink-500'">
                    {{ row.status === 'active' ? '启用' : '停用' }}
                  </span>
                </td>
                <td class="td text-right tabular-nums">{{ row.preview_count ?? 0 }}</td>
                <td class="td text-[11px] text-ink-500">{{ fmtDT(row.updated_at) }}</td>
                <td class="td">
                  <div class="flex flex-wrap gap-x-2.5 gap-y-1 text-[11px]">
                    <button class="text-brand-600 hover:underline" @click="openDataset(row)">字段配置</button>
                    <button class="text-brand-600 hover:underline" @click="openPreview(row)">预览</button>
                    <button class="text-brand-600 hover:underline" @click="openValues(row)">枚举</button>
                    <button class="text-ink-500 hover:text-brand-600" @click="openEdit(row)">编辑</button>
                    <button class="text-ink-500 hover:text-brand-600" @click="toggleStatus(row)">
                      {{ row.status === 'active' ? '停用' : '启用' }}
                    </button>
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

    <!-- 详情 -->
    <template v-else>
      <div class="card p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <button class="text-[12px] text-brand-600" @click="closeDataset">返回列表</button>
              <span class="text-ink-300">/</span>
              <h3 class="truncate text-[16px] font-semibold text-ink-900">{{ detailData?.name || current.name }}</h3>
              <span class="tag" :class="detailData?.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-ink-100 text-ink-500'">
                {{ detailData?.status === 'active' ? '启用' : '停用' }}
              </span>
              <span class="tag">{{ fields.length }} 个字段</span>
              <span class="tag">{{ detailData?.widget_count ?? 0 }} 个组件引用</span>
            </div>
            <p class="mt-1 font-mono text-[11px] text-ink-500">{{ detailData?.primary_model || current.primary_model }}</p>
            <p v-if="detailData?.description" class="mt-0.5 max-w-2xl text-[12px] text-ink-400">{{ detailData.description }}</p>
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <button class="btn-ghost" :disabled="detailLoading" @click="reloadDetail">{{ detailLoading ? '加载中…' : '刷新' }}</button>
            <button class="btn-outline" @click="openEdit(detailData || current)">编辑口径</button>
            <button class="btn-outline" @click="openPreview(current)">预览 50 行</button>
            <button class="btn-outline" @click="openValues(current)">字段枚举</button>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap gap-1 border-b border-ink-100">
          <button
            v-for="t in DETAIL_TABS"
            :key="t.key"
            class="-mb-px border-b-2 px-3 py-1.5 text-[12px]"
            :class="detailTab === t.key ? 'border-brand-600 text-brand-700' : 'border-transparent text-ink-500 hover:text-ink-700'"
            @click="switchDetailTab(t.key)"
          >{{ t.label }}</button>
        </div>
      </div>

      <div v-if="detailError" class="card flex flex-wrap items-center gap-2 border-rose-200 bg-rose-50 p-4 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1">{{ detailError }}</span>
        <button class="font-medium" @click="reloadDetail">重试</button>
      </div>

      <!-- 字段配置 -->
      <template v-else-if="detailTab === 'fields'">
        <div class="card p-0">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
            <div>
              <h4 class="text-[13px] font-semibold text-ink-800">字段配置</h4>
              <p class="mt-0.5 text-[11px] text-ink-400">
                路径需真实存在于主模型；别名、类型、聚合、分组与时间分桶会写入数据集编译结果。
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-1.5">
              <button class="btn-ghost" :disabled="fieldsSaving" @click="addFieldRow">添加字段</button>
              <button class="btn-outline" :disabled="!schemaSuggestions.length" @click="applySuggestions">按模型建议生成</button>
              <button class="btn-primary" :disabled="fieldsSaving" @click="saveFields">
                {{ fieldsSaving ? '保存中…' : '保存字段' }}
              </button>
            </div>
          </div>

          <div v-if="detailLoading && !fields.length" class="space-y-2 p-4">
            <div v-for="n in 5" :key="`f-sk-${n}`" class="h-9 animate-pulse rounded-control bg-ink-50"></div>
          </div>
          <div v-else-if="!fields.length" class="px-4 py-12 text-center">
            <p class="text-[13px] text-ink-500">还没有配置字段</p>
            <p class="mt-1 text-[11px] text-ink-400">可以按模型建议一键生成，也可以逐个添加路径并设置聚合方式。</p>
            <div class="mt-3 flex justify-center gap-2">
              <button class="btn-outline" :disabled="!schemaSuggestions.length" @click="applySuggestions">按建议生成</button>
              <button class="btn-primary" @click="addFieldRow">添加字段</button>
            </div>
          </div>
          <div v-else class="overflow-auto">
            <table class="w-full min-w-[980px]">
              <thead class="bg-ink-50">
                <tr>
                  <th class="th w-6">#</th>
                  <th class="th w-60">字段路径</th>
                  <th class="th w-40">别名</th>
                  <th class="th w-32">类型</th>
                  <th class="th w-32">聚合</th>
                  <th class="th w-20">分组</th>
                  <th class="th w-28">时间分桶</th>
                  <th class="th w-20">可见</th>
                  <th class="th w-16">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="(field, idx) in fields" :key="`field-${idx}`">
                  <td class="td text-[11px] text-ink-400">{{ idx + 1 }}</td>
                  <td class="td">
                    <input v-model="field.path" class="input py-1 font-mono text-[11px]" list="schema-field-paths" placeholder="如：created_at" />
                  </td>
                  <td class="td">
                    <input v-model="field.alias" class="input py-1 text-[11px]" placeholder="展示名" />
                  </td>
                  <td class="td">
                    <select v-model="field.ftype" class="input py-1 text-[11px]">
                      <option v-for="t in FIELD_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
                    </select>
                  </td>
                  <td class="td">
                    <select v-model="field.aggregate" class="input py-1 text-[11px]">
                      <option v-for="a in AGGREGATES" :key="a.value" :value="a.value">{{ a.label }}</option>
                    </select>
                  </td>
                  <td class="td text-center">
                    <input v-model="field.is_group" type="checkbox" />
                  </td>
                  <td class="td">
                    <select v-model="field.bucket" class="input py-1 text-[11px]">
                      <option v-for="b in BUCKETS" :key="b.value" :value="b.value">{{ b.label }}</option>
                    </select>
                  </td>
                  <td class="td text-center">
                    <input v-model="field.visible" type="checkbox" />
                  </td>
                  <td class="td">
                    <button class="text-[11px] text-rose-500 hover:underline" @click="fields.splice(idx, 1)">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <datalist id="schema-field-paths">
            <option v-for="f in schemaFields" :key="f.name" :value="f.name">{{ f.verbose_name }}</option>
          </datalist>
          <div v-if="fieldsError" class="m-4 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ fieldsError }}</div>
          <div class="flex flex-wrap items-center gap-3 border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
            <span>字段数 {{ fields.length }}</span>
            <span>建议字段 {{ schemaSuggestions.length }}</span>
            <span v-if="schemaError" class="text-amber-700">{{ schemaError }}</span>
            <span class="ml-auto">保存为整体替换，一次事务失败全部回滚。</span>
          </div>
        </div>
      </template>

      <!-- 预览 -->
      <template v-else-if="detailTab === 'preview'">
        <div class="card p-0">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
            <div>
              <h4 class="text-[13px] font-semibold text-ink-800">数据预览</h4>
              <p class="mt-0.5 text-[11px] text-ink-400">按当前字段与过滤条件执行，最多返回前 50 行。</p>
            </div>
            <div class="flex items-center gap-2">
              <span v-if="previewResult" class="tag">返回 {{ previewResult.rows?.length || 0 }} 行</span>
              <span v-if="previewResult?.meta?.total !== undefined" class="tag">命中 {{ previewResult.meta.total }}</span>
              <button class="btn-primary px-2 py-0.5" :disabled="previewLoading" @click="runPreview">
                {{ previewLoading ? '执行中…' : '执行预览' }}
              </button>
            </div>
          </div>
          <div v-if="previewLoading" class="py-12 text-center text-[12px] text-ink-400">预览执行中…</div>
          <div v-else-if="previewError" class="m-4 flex items-center gap-2 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <span class="min-w-0 flex-1">{{ previewError }}</span>
            <button class="shrink-0 font-medium" @click="runPreview">重试</button>
          </div>
          <div v-else-if="!previewResult" class="px-4 py-12 text-center">
            <p class="text-[13px] text-ink-500">还没有执行预览</p>
            <p class="mt-1 text-[11px] text-ink-400">预览不会写执行流水，可放心用于调整字段与过滤条件。</p>
            <button class="btn-primary mt-3" @click="runPreview">预览前 50 行</button>
          </div>
          <div v-else-if="!previewResult.rows?.length" class="px-4 py-12 text-center text-[12px] text-ink-400">
            当前条件下没有命中数据，请调整过滤条件或主模型
          </div>
          <div v-else class="overflow-auto">
            <table class="w-full">
              <thead class="bg-ink-50">
                <tr>
                  <th v-for="col in previewResult.columns || []" :key="col.key" class="th whitespace-nowrap">
                    {{ col.label || col.key }}
                    <span class="ml-1 text-[10px] font-normal text-ink-400">{{ col.type }}</span>
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="(row, idx) in previewResult.rows" :key="`pv-${idx}`" class="hover:bg-ink-50/50">
                  <td v-for="col in previewResult.columns || []" :key="`${col.key}-${idx}`" class="td whitespace-nowrap text-[11px]">
                    {{ cellText(row[col.key]) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="previewResult" class="flex flex-wrap items-center gap-3 border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
            <span>模型 {{ previewResult.meta?.model || detailData?.primary_model }}</span>
            <span>限制 {{ previewResult.meta?.limit ?? 50 }} 行</span>
            <span>耗时 {{ previewResult.meta?.executed_at ? fmtDT(previewResult.meta.executed_at) : '—' }}</span>
          </div>
        </div>
      </template>

      <!-- 字段枚举 -->
      <template v-else>
        <div class="card p-0">
          <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-4 py-2.5">
            <div>
              <h4 class="text-[13px] font-semibold text-ink-800">字段枚举</h4>
              <p class="mt-0.5 text-[11px] text-ink-400">按命中次数倒序返回，供筛选器下拉与参数校验参考。</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <select v-model="valueField" class="input w-64 py-1 text-[12px]" @change="loadValues">
                <option value="">选择字段</option>
                <option v-for="f in valueFieldOptions" :key="f.path" :value="f.path">{{ f.label }}（{{ f.path }}）</option>
              </select>
              <button class="btn-primary px-2 py-0.5" :disabled="valueLoading || !valueField" @click="loadValues">
                {{ valueLoading ? '加载中…' : '加载枚举' }}
              </button>
            </div>
          </div>
          <div v-if="valueLoading" class="py-12 text-center text-[12px] text-ink-400">枚举加载中…</div>
          <div v-else-if="valueError" class="m-4 flex items-center gap-2 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
            <span class="min-w-0 flex-1">{{ valueError }}</span>
            <button class="shrink-0 font-medium" @click="loadValues">重试</button>
          </div>
          <div v-else-if="!valueItems.length" class="px-4 py-12 text-center text-[12px] text-ink-400">
            {{ valueField ? '该字段没有可枚举的取值' : '请选择字段后加载枚举' }}
          </div>
          <div v-else class="overflow-auto">
            <table class="w-full min-w-[360px]">
              <thead class="bg-ink-50">
                <tr>
                  <th class="th">取值</th>
                  <th class="th w-32 text-right">命中次数</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="(item, idx) in valueItems" :key="`val-${idx}`" class="hover:bg-ink-50/50">
                  <td class="td text-[12px]">{{ item.value === null || item.value === undefined ? '（空值）' : item.value }}</td>
                  <td class="td text-right tabular-nums">{{ item.count }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="border-t border-ink-100 px-4 py-2 text-[11px] text-ink-400">
            枚举条数 {{ valueItems.length }}，最多返回 50 条；字段类型由后端解析路径后返回。
          </div>
        </div>
      </template>
    </template>

    <!-- 新建 / 编辑数据集 -->
    <Modal :show="formOpen" :title="form.id ? '编辑数据集' : '新建数据集'" width="720px" @close="formOpen = false">
      <div class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">名称 <span class="text-rose-500">*</span></span>
            <input v-model="form.name" class="input" placeholder="如：订单宽表" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">主模型 <span class="text-rose-500">*</span></span>
            <select v-model="form.primary_model" class="input">
              <option value="">选择白名单模型</option>
              <option v-for="m in models" :key="m.label" :value="m.label">{{ m.verbose_name }}（{{ m.label }}）</option>
            </select>
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">默认行数</span>
            <input v-model.number="form.default_limit" class="input" type="number" min="1" max="2000" />
          </label>
          <label class="block text-[12px] text-ink-600">
            <span class="mb-1 block">缓存秒数</span>
            <input v-model.number="form.cache_ttl" class="input" type="number" min="0" max="86400" />
          </label>
          <label v-if="form.id" class="block text-[12px] text-ink-600">
            <span class="mb-1 block">状态</span>
            <select v-model="form.status" class="input">
              <option value="active">启用</option>
              <option value="inactive">停用</option>
            </select>
          </label>
        </div>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">描述</span>
          <textarea v-model="form.description" class="input min-h-16" placeholder="说明口径、数据范围与负责人" />
        </label>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">过滤条件（JSON 对象）</span>
          <textarea v-model="form.filterText" class="input min-h-20 font-mono text-[12px]" placeholder='{"status": "active"}' />
        </label>
        <label class="block text-[12px] text-ink-600">
          <span class="mb-1 block">去重字段（逗号分隔）</span>
          <input v-model="form.distinctText" class="input font-mono text-[12px]" placeholder="如：order_no,user_id" />
        </label>
        <label v-if="!form.id" class="flex items-center gap-2 text-[12px] text-ink-600">
          <input v-model="form.generateFields" type="checkbox" />
          创建后按模型建议自动生成字段（文本分组、数值求和、日期按月分桶）
        </label>
        <div v-if="formError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">{{ formError }}</div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="formOpen = false">取消</button>
          <button class="btn-primary" :disabled="saving" @click="saveDataset">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </Modal>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { reportingApi } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  reloadToken: { type: Number, default: 0 },
})
const app = useAppStore()

const FIELD_TYPES = [
  { value: 'string', label: '文本' },
  { value: 'number', label: '数值' },
  { value: 'integer', label: '整数' },
  { value: 'decimal', label: '金额' },
  { value: 'datetime', label: '时间' },
  { value: 'date', label: '日期' },
  { value: 'bool', label: '布尔' },
  { value: 'json', label: 'JSON' },
]
const AGGREGATES = [
  { value: 'none', label: '不聚合' },
  { value: 'count', label: '计数' },
  { value: 'sum', label: '求和' },
  { value: 'avg', label: '平均值' },
  { value: 'min', label: '最小值' },
  { value: 'max', label: '最大值' },
  { value: 'count_distinct', label: '去重计数' },
  { value: 'median', label: '中位数' },
]
const BUCKETS = [
  { value: '', label: '不分组' },
  { value: 'hour', label: '小时' },
  { value: 'day', label: '日' },
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'quarter', label: '季度' },
  { value: 'year', label: '年' },
]
const DETAIL_TABS = [
  { key: 'fields', label: '字段配置' },
  { key: 'preview', label: '数据预览' },
  { key: 'values', label: '字段枚举' },
]
const PREVIEW_LIMIT = 50

const items = ref([])
const count = ref(0)
const page = ref(1)
const pageSize = ref(20)
const q = ref('')
const status = ref('')
const modelFilter = ref('')
const loading = ref(false)
const error = ref('')
const unavailable = ref('')
const models = ref([])

const current = ref(null)
const detailData = ref(null)
const detailLoading = ref(false)
const detailError = ref('')
const detailTab = ref('fields')
const fields = ref([])
const fieldsError = ref('')
const fieldsSaving = ref(false)
const schemaData = ref(null)
const schemaError = ref('')

const previewLoading = ref(false)
const previewError = ref('')
const previewResult = ref(null)

const valueLoading = ref(false)
const valueError = ref('')
const valueField = ref('')
const valueItems = ref([])

const formOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = ref({})

const totalPages = computed(() => Math.max(1, Math.ceil(count.value / Math.max(1, pageSize.value))))
const schemaFields = computed(() => {
  const list = schemaData.value?.model?.fields
  return Array.isArray(list) ? list : []
})
const schemaSuggestions = computed(() => {
  const list = schemaData.value?.suggestions
  return Array.isArray(list) ? list : []
})
const valueFieldOptions = computed(() => {
  const map = new Map()
  for (const f of fields.value) {
    if (f.path) map.set(f.path, { path: f.path, label: f.alias || f.path })
  }
  for (const f of schemaFields.value) {
    if (!f?.name || map.has(f.name)) continue
    map.set(f.name, { path: f.name, label: f.verbose_name || f.name })
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

function cellText(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

// ---------------------------------------------------------------------------
// 列表与模型
// ---------------------------------------------------------------------------

async function loadModels() {
  if (models.value.length) return
  try {
    const pageData = await reportingApi.list('models/', { page: 1, page_size: 200 })
    models.value = pageData.items
  } catch {
    models.value = []
  }
}

async function load() {
  loading.value = true
  error.value = ''
  unavailable.value = ''
  loadModels()
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) params.q = q.value.trim()
    if (status.value) params.status = status.value
    if (modelFilter.value) params.primary_model = modelFilter.value
    const data = await reportingApi.list('datasets/', params)
    items.value = data.items
    count.value = data.count
  } catch (e) {
    items.value = []
    count.value = 0
    if (isUnavailable(e)) unavailable.value = '数据集列表接口不可用（404/405）'
    else {
      error.value = e?.message || '数据集列表加载失败'
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

watch([q, status, modelFilter], () => {
  page.value = 1
  load()
})

async function toggleStatus(row) {
  const next = row.status === 'active' ? 'inactive' : 'active'
  try {
    await reportingApi.update(`datasets/${row.id}/update/`, { status: next })
    app.toastMsg(next === 'active' ? '数据集已启用' : '数据集已停用', 'success')
    await load()
  } catch (e) {
    app.toastMsg(e?.message || '状态更新失败', 'error')
  }
}

// ---------------------------------------------------------------------------
// 详情与字段
// ---------------------------------------------------------------------------

function normalizeField(field) {
  return {
    id: field.id,
    path: field.path || '',
    alias: field.alias || '',
    ftype: field.ftype || 'string',
    aggregate: field.aggregate || 'none',
    is_group: Boolean(field.is_group),
    bucket: field.bucket || '',
    visible: field.visible !== false,
  }
}

async function loadDataset(id) {
  detailLoading.value = true
  detailError.value = ''
  fieldsError.value = ''
  try {
    const data = await reportingApi.get(`datasets/${id}/`)
    detailData.value = data
    fields.value = Array.isArray(data?.fields) ? data.fields.map(normalizeField) : []
    if (!valueField.value && fields.value.length) valueField.value = fields.value[0].path || ''
    try {
      schemaData.value = await reportingApi.get(`datasets/${id}/schema/`)
      schemaError.value = ''
    } catch (e) {
      schemaData.value = null
      schemaError.value = isUnavailable(e) ? '结构接口不可用（404/405），字段路径需手动填写' : (e?.message || '结构加载失败')
    }
  } catch (e) {
    detailError.value = isUnavailable(e) ? '数据集详情接口不可用（404/405）' : (e?.message || '数据集详情加载失败')
    app.toastMsg(detailError.value, 'error')
  } finally {
    detailLoading.value = false
  }
}

async function openDataset(row) {
  current.value = row
  detailTab.value = 'fields'
  detailData.value = null
  fields.value = []
  schemaData.value = null
  previewResult.value = null
  previewError.value = ''
  valueField.value = ''
  valueItems.value = []
  valueError.value = ''
  await loadDataset(row.id)
}

function closeDataset() {
  current.value = null
  detailData.value = null
  fields.value = []
  schemaData.value = null
  previewResult.value = null
  load()
}

function reloadDetail() {
  if (current.value?.id) loadDataset(current.value.id)
}

function switchDetailTab(key) {
  detailTab.value = key
  if (key === 'preview' && !previewResult.value && !previewLoading.value) runPreview()
  if (key === 'values' && !valueItems.value.length && valueField.value) loadValues()
}

function emptyFieldRow() {
  return {
    path: '',
    alias: '',
    ftype: 'string',
    aggregate: 'none',
    is_group: false,
    bucket: '',
    visible: true,
  }
}

function addFieldRow() {
  fields.value.push(emptyFieldRow())
}

function applySuggestions() {
  if (!schemaSuggestions.value.length) {
    app.toastMsg('当前模型没有可用的字段建议', 'error')
    return
  }
  if (fields.value.length && !window.confirm('按建议生成会替换现有字段配置，确认继续？')) return
  fields.value = schemaSuggestions.value.map((s) => ({
    path: s.path,
    alias: '',
    ftype: s.type || 'string',
    aggregate: s.aggregate || 'none',
    is_group: Boolean(s.is_group),
    bucket: s.bucket || '',
    visible: true,
  }))
  app.toastMsg(`已生成 ${fields.value.length} 个建议字段，保存后生效`, 'success')
}

async function saveFields() {
  if (!current.value?.id) return
  if (!fields.value.length) {
    app.toastMsg('至少配置一个字段', 'error')
    return
  }
  const empty = fields.value.find((f) => !String(f.path || '').trim())
  if (empty) {
    app.toastMsg('字段路径不能为空', 'error')
    return
  }
  fieldsSaving.value = true
  fieldsError.value = ''
  try {
    const payload = fields.value.map((f, idx) => ({
      path: String(f.path).trim(),
      alias: String(f.alias || '').trim(),
      ftype: f.ftype || 'string',
      aggregate: f.aggregate || 'none',
      is_group: Boolean(f.is_group),
      bucket: f.bucket || '',
      order: idx,
      visible: Boolean(f.visible),
    }))
    await reportingApi.action(`datasets/${current.value.id}/fields/save/`, { fields: payload })
    app.toastMsg('字段配置已保存', 'success')
    await loadDataset(current.value.id)
  } catch (e) {
    fieldsError.value = e?.message || '字段保存失败'
    app.toastMsg(fieldsError.value, 'error')
  } finally {
    fieldsSaving.value = false
  }
}

// ---------------------------------------------------------------------------
// 预览与枚举
// ---------------------------------------------------------------------------

async function runPreview() {
  if (!current.value?.id) return
  previewLoading.value = true
  previewError.value = ''
  previewResult.value = null
  try {
    const data = await reportingApi.action(`datasets/${current.value.id}/preview/`, { limit: PREVIEW_LIMIT })
    previewResult.value = data
    if (!data?.rows?.length) app.toastMsg('预览没有命中数据', 'info')
  } catch (e) {
    previewError.value = isUnavailable(e) ? '预览接口不可用（404/405）' : (e?.message || '预览失败')
    app.toastMsg(previewError.value, 'error')
  } finally {
    previewLoading.value = false
  }
}

async function loadValues() {
  if (!current.value?.id || !valueField.value) return
  valueLoading.value = true
  valueError.value = ''
  try {
    const data = await reportingApi.get(
      `datasets/${current.value.id}/values/?field=${encodeURIComponent(valueField.value)}&limit=50`,
    )
    valueItems.value = Array.isArray(data?.items) ? data.items : []
  } catch (e) {
    valueItems.value = []
    valueError.value = isUnavailable(e) ? '字段枚举接口不可用（404/405）' : (e?.message || '枚举加载失败')
  } finally {
    valueLoading.value = false
  }
}

async function openPreview(row) {
  await openDataset(row)
  detailTab.value = 'preview'
  await runPreview()
}

async function openValues(row) {
  await openDataset(row)
  detailTab.value = 'values'
  if (valueField.value) await loadValues()
}

// ---------------------------------------------------------------------------
// 新建 / 编辑
// ---------------------------------------------------------------------------

function emptyForm() {
  return {
    id: null,
    name: '',
    primary_model: '',
    description: '',
    filterText: '{}',
    distinctText: '',
    default_limit: 200,
    cache_ttl: 300,
    status: 'active',
    generateFields: true,
  }
}

async function openCreate() {
  await loadModels()
  form.value = emptyForm()
  formError.value = ''
  formOpen.value = true
}

function openEdit(row) {
  if (!row) return
  form.value = {
    id: row.id,
    name: row.name || '',
    primary_model: row.primary_model || '',
    description: row.description || '',
    filterText: JSON.stringify(row.filter || {}, null, 2),
    distinctText: Array.isArray(row.distinct_fields) ? row.distinct_fields.join(', ') : '',
    default_limit: row.default_limit ?? 200,
    cache_ttl: row.cache_ttl ?? 300,
    status: row.status || 'active',
    generateFields: false,
  }
  formError.value = ''
  formOpen.value = true
  loadModels()
}

function parseJsonObject(text, label) {
  const raw = String(text || '').trim()
  if (!raw) return {}
  const parsed = JSON.parse(raw)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label}必须是 JSON 对象`)
  }
  return parsed
}

async function saveDataset() {
  const f = form.value
  if (!String(f.name || '').trim()) {
    formError.value = '请填写数据集名称'
    return
  }
  if (!String(f.primary_model || '').trim()) {
    formError.value = '请选择主模型'
    return
  }
  let filter
  try {
    filter = parseJsonObject(f.filterText, '过滤条件')
  } catch (e) {
    formError.value = `过滤条件格式错误：${e?.message || '必须是 JSON 对象'}`
    return
  }
  const distinctFields = String(f.distinctText || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  saving.value = true
  formError.value = ''
  try {
    if (f.id) {
      const original = await reportingApi.get(`datasets/${f.id}/`)
      const modelChanged = String(original?.primary_model || '') !== String(f.primary_model)
      if (modelChanged && (original?.field_count || 0) > 0) {
        const ok = window.confirm('更换主模型会清空现有字段与关联，确认继续？')
        if (!ok) {
          saving.value = false
          return
        }
      }
      const payload = {
        name: String(f.name).trim(),
        primary_model: f.primary_model,
        description: f.description || '',
        filter,
        distinct_fields: distinctFields,
        default_limit: Number(f.default_limit) || 200,
        cache_ttl: Number(f.cache_ttl) || 0,
        status: f.status || 'active',
      }
      if (modelChanged) payload.reset_fields = true
      await reportingApi.update(`datasets/${f.id}/update/`, payload)
      app.toastMsg('数据集已保存', 'success')
      formOpen.value = false
      if (current.value?.id === f.id) await loadDataset(f.id)
      else await load()
    } else {
      const created = await reportingApi.create('datasets/create/', {
        name: String(f.name).trim(),
        primary_model: f.primary_model,
        description: f.description || '',
        filter,
        distinct_fields: distinctFields,
        default_limit: Number(f.default_limit) || 200,
        cache_ttl: Number(f.cache_ttl) || 0,
      })
      app.toastMsg('数据集已创建', 'success')
      formOpen.value = false
      const datasetId = created?.dataset?.id || created?.id
      if (datasetId && f.generateFields) {
        try {
          const schema = await reportingApi.get(`datasets/${datasetId}/schema/`)
          const suggestions = Array.isArray(schema?.suggestions) ? schema.suggestions : []
          if (suggestions.length) {
            const rows = suggestions.map((s, idx) => ({
              path: s.path,
              alias: '',
              ftype: s.type || 'string',
              aggregate: s.aggregate || 'none',
              is_group: Boolean(s.is_group),
              bucket: s.bucket || '',
              order: idx,
              visible: true,
            }))
            await reportingApi.action(`datasets/${datasetId}/fields/save/`, { fields: rows })
            app.toastMsg(`已按建议生成 ${rows.length} 个字段`, 'success')
          }
        } catch (e) {
          app.toastMsg(e?.message || '建议字段生成失败，可在详情中手动配置', 'error')
        }
      }
      await load()
    }
  } catch (e) {
    formError.value = e?.message || '保存失败'
    app.toastMsg(formError.value, 'error')
  } finally {
    saving.value = false
  }
}

watch(() => props.reloadToken, () => {
  if (current.value?.id) loadDataset(current.value.id)
  else load()
})

onMounted(() => {
  load()
  loadModels()
})
</script>