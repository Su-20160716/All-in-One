<template>
  <div class="inline-flex items-end" :style="{ width: `${width}px`, height: `${height}px` }">
    <svg
      v-if="hasData"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="ariaLabel"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="color" stop-opacity="0.28" />
          <stop offset="100%" :stop-color="color" stop-opacity="0" />
        </linearGradient>
      </defs>

      <path v-if="showArea" :d="areaPath" :fill="`url(#${gradientId})`" stroke="none" />
      <path
        :d="linePath"
        fill="none"
        :stroke="color"
        :stroke-width="strokeWidth"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle v-if="showLast" :cx="lastPoint.x" :cy="lastPoint.y" :r="strokeWidth + 0.8" :fill="color">
        <title>{{ lastLabel }}</title>
      </circle>
    </svg>
    <span v-else class="pb-0.5 text-[11px] text-ink-400">{{ emptyText }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 数值序列，按时间从左到右 */
  values: { type: Array, default: () => [] },
  width: { type: Number, default: 120 },
  height: { type: Number, default: 32 },
  /** 线条颜色（CSS 颜色值） */
  color: { type: String, default: 'var(--brand-500)' },
  strokeWidth: { type: Number, default: 1.6 },
  /** 是否填充面积 */
  showArea: { type: Boolean, default: true },
  /** 是否标记最后一个点 */
  showLast: { type: Boolean, default: true },
  /** 纵轴下界/上界，null 表示按数据自适应 */
  min: { type: Number, default: null },
  max: { type: Number, default: null },
  /** 最后一个点的 tooltip 文案 */
  lastLabel: { type: String, default: '最新值' },
  emptyText: { type: String, default: '暂无数据' },
  ariaLabel: { type: String, default: '趋势迷你图' },
})

const gradientId = `spark-${Math.random().toString(36).slice(2, 9)}`

const numbers = computed(() =>
  (props.values || []).map((v) => Number(v)).filter((v) => Number.isFinite(v))
)

const hasData = computed(() => numbers.value.length >= 2)

const bounds = computed(() => {
  const nums = numbers.value
  if (!nums.length) return { lo: 0, hi: 1 }
  let lo = props.min !== null ? props.min : Math.min(...nums)
  let hi = props.max !== null ? props.max : Math.max(...nums)
  if (hi === lo) {
    // 全平数据：给一点上下留白，线条落在中间而不是贴边
    const pad = Math.abs(lo) * 0.1 || 1
    lo -= pad
    hi += pad
  }
  return { lo, hi }
})

const points = computed(() => {
  const nums = numbers.value
  const n = nums.length
  if (n < 2) return []
  const { lo, hi } = bounds.value
  const span = hi - lo || 1
  const pad = props.strokeWidth
  const usableH = Math.max(props.height - pad * 2, 1)
  return nums.map((v, i) => ({
    x: pad + (i / (n - 1)) * (props.width - pad * 2),
    y: pad + (1 - (v - lo) / span) * usableH,
    v,
  }))
})

const linePath = computed(() => {
  const pts = points.value
  if (!pts.length) return ''
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ')
})

const areaPath = computed(() => {
  const pts = points.value
  if (!pts.length) return ''
  const first = pts[0]
  const last = pts[pts.length - 1]
  return `${linePath.value} L${last.x.toFixed(2)},${props.height} L${first.x.toFixed(2)},${props.height} Z`
})

const lastPoint = computed(() => points.value[points.value.length - 1] || { x: 0, y: 0, v: 0 })
</script>
