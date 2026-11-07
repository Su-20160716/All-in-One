<template>
  <div class="min-w-0">
    <div v-if="title || $slots.actions" class="mb-1.5 flex items-center justify-between gap-2">
      <span class="text-[12px] font-medium text-ink-600">{{ title }}</span>
      <slot name="actions" />
    </div>

    <div v-if="!rows.length" class="grid place-items-center rounded-control border border-dashed border-ink-200 py-8 text-[12px] text-ink-400">
      {{ emptyText }}
    </div>

    <!-- 横向条形：适合类目多、名称长的分布 -->
    <ul v-else-if="horizontal" class="space-y-1.5">
      <li v-for="row in rows" :key="row.key" class="flex items-center gap-2 text-[12px]">
        <span class="w-24 shrink-0 truncate text-right text-ink-500" :title="row.label">{{ row.label }}</span>
        <span class="relative h-4 min-w-0 flex-1 overflow-hidden rounded-control bg-ink-50">
          <span
            class="absolute inset-y-0 left-0 rounded-control transition-[width] duration-300"
            :style="{ width: `${row.widthPercent}%`, background: row.color }"
          >
            <span class="sr-only">{{ row.label }}</span>
          </span>
        </span>
        <span class="w-14 shrink-0 text-right font-medium text-ink-700" :title="`${row.label}：${formatValue(row.value)}`">
          {{ formatValue(row.value) }}
        </span>
      </li>
    </ul>

    <!-- 纵向柱形：适合时间序列、对比项较少的场景 -->
    <div v-else class="min-w-0">
      <div class="flex items-end gap-1.5" :style="{ height: `${height}px` }">
        <div
          v-for="row in rows"
          :key="row.key"
          class="group flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1"
          :title="`${row.label}：${formatValue(row.value)}`"
        >
          <span v-if="showValue" class="text-[10px] leading-none text-ink-500">{{ formatValue(row.value) }}</span>
          <span
            class="w-full max-w-[46px] rounded-t-[3px] transition-all duration-300 group-hover:opacity-80"
            :style="{ height: `${Math.max(row.heightPercent, row.value > 0 ? 2 : 0)}%`, background: row.color }"
          ></span>
        </div>
      </div>
      <div class="mt-1 flex items-start gap-1.5 border-t border-ink-100 pt-1">
        <span
          v-for="(row, i) in rows"
          :key="`lb-${row.key}`"
          class="min-w-0 flex-1 truncate text-center text-[10px] text-ink-400"
          :class="rows.length > 8 && i % 2 === 1 ? 'opacity-0' : ''"
          :title="row.label"
        >
          {{ row.label }}
        </span>
      </div>
    </div>

    <div v-if="$slots.footer" class="mt-2 text-[11px] text-ink-400">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const PALETTE = ['#0ea5e9', '#10b981', '#f59e0b', '#8b5cf6', '#f43f5e', '#64748b', '#14b8a6', '#f97316']

const props = defineProps({
  /** 数据：[{ label, value, color? }] 或 { 标签: 数值 } 对象 */
  data: { type: [Array, Object], default: () => [] },
  /** 横向条形（默认纵向柱形） */
  horizontal: { type: Boolean, default: false },
  /** 纵向柱形绘图区高度（px） */
  height: { type: Number, default: 160 },
  /** 柱顶是否显示数值 */
  showValue: { type: Boolean, default: true },
  /** 统一柱色，缺省按调色板轮转 */
  color: { type: String, default: '' },
  /** 最大值（用于占比刻度），缺省取数据最大值 */
  max: { type: Number, default: null },
  /** 数值格式化 */
  format: { type: Function, default: null },
  title: { type: String, default: '' },
  emptyText: { type: String, default: '暂无分布数据' },
  /** 小数位（无 format 时生效） */
  precision: { type: Number, default: 0 },
})

const rows = computed(() => {
  const raw = Array.isArray(props.data)
    ? props.data
    : Object.entries(props.data || {}).map(([label, value]) => ({ label, value }))
  const list = raw
    .filter((r) => r && typeof r === 'object')
    .map((r, i) => {
      const value = Number(r.value)
      return {
        key: r.key ?? r.label ?? `bar-${i}`,
        label: String(r.label ?? r.name ?? `项 ${i + 1}`),
        value: Number.isFinite(value) ? value : 0,
        color: r.color || props.color || PALETTE[i % PALETTE.length],
      }
    })
  const maxValue = props.max !== null && props.max !== undefined
    ? Number(props.max)
    : Math.max(...list.map((r) => r.value), 0)
  const safeMax = maxValue > 0 ? maxValue : 1
  return list.map((r) => ({
    ...r,
    widthPercent: Math.max(0, Math.min(100, (r.value / safeMax) * 100)),
    heightPercent: Math.max(0, Math.min(100, (r.value / safeMax) * 100)),
  }))
})

function formatValue(v) {
  if (typeof props.format === 'function') return props.format(v)
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', {
    maximumFractionDigits: props.precision,
    minimumFractionDigits: 0,
  })
}
</script>
