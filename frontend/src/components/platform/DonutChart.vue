<template>
  <div class="flex min-w-0 flex-wrap items-center gap-4" :class="legendPosition === 'bottom' ? 'justify-center' : ''">
    <div class="relative shrink-0" :style="{ width: `${size}px`, height: `${size}px` }">
      <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`" role="img" :aria-label="ariaLabel">
        <!-- 底环：没有数据时也保留结构，避免布局跳动 -->
        <circle
          :cx="center"
          :cy="center"
          :r="radius"
          fill="none"
          stroke="currentColor"
          class="text-ink-100"
          :stroke-width="thickness"
        />
        <circle
          v-for="seg in segments"
          :key="seg.key"
          :cx="center"
          :cy="center"
          :r="radius"
          fill="none"
          :stroke="seg.color"
          :stroke-width="seg.active ? thickness + 3 : thickness"
          :stroke-dasharray="`${seg.length} ${circumference - seg.length}`"
          :stroke-dashoffset="-seg.offset"
          :transform="`rotate(-90 ${center} ${center})`"
          stroke-linecap="butt"
          class="transition-[stroke-width] duration-200"
          @mouseenter="hovered = seg.key"
          @mouseleave="hovered = ''"
        >
          <title>{{ seg.label }}：{{ formatValue(seg.value) }}（{{ seg.percentText }}）</title>
        </circle>
      </svg>

      <div class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        <span class="text-[18px] font-semibold leading-tight text-ink-900">{{ centerText }}</span>
        <span v-if="centerLabel" class="mt-0.5 max-w-[80%] truncate text-[11px] text-ink-400">{{ centerLabel }}</span>
      </div>
    </div>

    <ul v-if="showLegend" class="min-w-0 flex-1 space-y-1 text-[12px]">
      <li
        v-for="seg in segments"
        :key="`lg-${seg.key}`"
        class="flex cursor-default items-center gap-2 rounded px-1 py-0.5 transition-colors"
        :class="hovered === seg.key ? 'bg-ink-50' : ''"
        @mouseenter="hovered = seg.key"
        @mouseleave="hovered = ''"
      >
        <span class="h-2 w-2 shrink-0 rounded-sm" :style="{ background: seg.color }"></span>
        <span class="min-w-0 flex-1 truncate text-ink-600" :title="seg.label">{{ seg.label }}</span>
        <span class="shrink-0 tabular-nums text-ink-700">{{ formatValue(seg.value) }}</span>
        <span class="w-11 shrink-0 text-right text-[11px] tabular-nums text-ink-400">{{ seg.percentText }}</span>
      </li>
      <li v-if="!segments.length" class="text-[12px] text-ink-400">{{ emptyText }}</li>
    </ul>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const PALETTE = ['#0ea5e9', '#10b981', '#f59e0b', '#8b5cf6', '#f43f5e', '#64748b', '#14b8a6', '#f97316']

const props = defineProps({
  /** 数据：[{ label, value, color? }] 或 { 标签: 数值 } */
  data: { type: [Array, Object], default: () => [] },
  size: { type: Number, default: 168 },
  /** 圆环厚度（px） */
  thickness: { type: Number, default: 18 },
  /** 中心主文案；缺省展示总计 */
  centerValue: { type: [String, Number], default: '' },
  centerLabel: { type: String, default: '总计' },
  showLegend: { type: Boolean, default: true },
  /** legend 位置：right / bottom */
  legendPosition: { type: String, default: 'right' },
  format: { type: Function, default: null },
  /** 小数位（百分比） */
  precision: { type: Number, default: 1 },
  emptyText: { type: String, default: '暂无数据' },
  ariaLabel: { type: String, default: '环形占比图' },
})

const hovered = ref('')

const center = computed(() => props.size / 2)
const radius = computed(() => Math.max(props.size / 2 - props.thickness / 2 - 2, 1))
const circumference = computed(() => 2 * Math.PI * radius.value)

const segments = computed(() => {
  const raw = Array.isArray(props.data)
    ? props.data
    : Object.entries(props.data || {}).map(([label, value]) => ({ label, value }))
  const items = raw
    .filter((d) => d && typeof d === 'object')
    .map((d, i) => ({
      key: d.key ?? d.label ?? `seg-${i}`,
      label: String(d.label ?? d.name ?? `分组 ${i + 1}`),
      value: Number(d.value) || 0,
      color: d.color || PALETTE[i % PALETTE.length],
    }))
    .filter((d) => d.value > 0)

  const total = items.reduce((sum, d) => sum + d.value, 0)
  let acc = 0
  return items.map((d) => {
    const ratio = total > 0 ? d.value / total : 0
    const length = ratio * circumference.value
    const seg = {
      ...d,
      ratio,
      length,
      offset: acc,
      percentText: `${(ratio * 100).toFixed(props.precision)}%`,
      active: hovered.value === d.key,
    }
    acc += length
    return seg
  })
})

const total = computed(() => segments.value.reduce((sum, s) => sum + s.value, 0))

const centerText = computed(() => {
  if (props.centerValue !== '' && props.centerValue !== null && props.centerValue !== undefined) {
    return typeof props.centerValue === 'number' ? formatValue(props.centerValue) : String(props.centerValue)
  }
  return formatValue(total.value)
})

function formatValue(v) {
  if (typeof props.format === 'function') return props.format(v)
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
</script>
