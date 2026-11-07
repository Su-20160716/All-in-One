<template>
  <div class="min-w-0">
    <div v-if="title || $slots.actions" class="mb-1.5 flex items-center justify-between gap-2">
      <span class="text-[12px] font-medium text-ink-600">{{ title }}</span>
      <slot name="actions" />
    </div>

    <div v-if="!hasData" class="grid place-items-center rounded-control border border-dashed border-ink-200 py-8 text-[12px] text-ink-400">
      {{ emptyText }}
    </div>

    <svg
      v-else
      :viewBox="`0 0 ${W} ${H}`"
      class="w-full"
      :style="{ height: `${height}px` }"
      role="img"
      :aria-label="ariaLabel"
    >
      <!-- 网格与纵轴刻度 -->
      <g v-if="showGrid">
        <line
          v-for="t in ticks"
          :key="`g-${t.value}`"
          :x1="PAD.left"
          :x2="W - PAD.right"
          :y1="t.y"
          :y2="t.y"
          stroke="currentColor"
          class="text-ink-100"
          stroke-width="1"
        />
        <text
          v-for="t in ticks"
          :key="`t-${t.value}`"
          :x="PAD.left - 6"
          :y="t.y + 3.5"
          text-anchor="end"
          class="fill-ink-400 text-[9px]"
        >
          {{ formatValue(t.value) }}
        </text>
      </g>

      <!-- 横向网格线之外再补一条基线，视觉上收口 -->
      <line
        :x1="PAD.left"
        :x2="W - PAD.right"
        :y1="H - PAD.bottom"
        :y2="H - PAD.bottom"
        stroke="currentColor"
        class="text-ink-200"
        stroke-width="1"
      />

      <!-- 横轴标签：标签过多时按步长抽稀 -->
      <text
        v-for="l in xLabels"
        :key="`x-${l.index}`"
        :x="l.x"
        :y="H - PAD.bottom + 13"
        text-anchor="middle"
        class="fill-ink-400 text-[9px]"
      >
        {{ l.text }}
      </text>

      <!-- 序列 -->
      <g v-for="s in drawnSeries" :key="s.name">
        <path
          v-if="s.area && drawnSeries.length === 1"
          :d="s.areaPath"
          :fill="s.color"
          fill-opacity="0.08"
          stroke="none"
        />
        <path
          :d="s.path"
          fill="none"
          :stroke="s.color"
          :stroke-width="s.emphasized ? 2.2 : 1.6"
          :stroke-dasharray="s.dashed ? '4 3' : undefined"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <template v-for="p in s.points" :key="`${s.name}-${p.i}`">
          <circle :cx="p.x" :cy="p.y" r="2.2" :fill="s.color" />
          <!-- 透明命中区：扩大 hover 面积，tooltip 用原生 title -->
          <circle :cx="p.x" :cy="p.y" r="8" fill="transparent">
            <title>{{ s.name }} · {{ p.label }}：{{ formatValue(p.v) }}</title>
          </circle>
        </template>
      </g>
    </svg>

    <div v-if="showLegend && series.length" class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
      <span v-for="s in series" :key="`lg-${s.name}`" class="inline-flex items-center gap-1 text-[11px] text-ink-500">
        <span class="h-1.5 w-3 rounded-pill" :style="{ background: s.color }"></span>
        {{ s.name }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const PALETTE = ['#0ea5e9', '#10b981', '#f59e0b', '#8b5cf6', '#f43f5e', '#64748b']

const props = defineProps({
  /**
   * 序列：[{ name, color?, data: number[], dashed?, area? }]
   * 也兼容单序列直接传 number[]，此时自动包成一条默认序列。
   */
  series: { type: Array, default: () => [] },
  /** 横轴标签，数量应与数据点一致，缺省用下标 */
  labels: { type: Array, default: () => [] },
  height: { type: Number, default: 220 },
  title: { type: String, default: '' },
  showGrid: { type: Boolean, default: true },
  showLegend: { type: Boolean, default: true },
  /** 纵轴刻度段数 */
  yTicks: { type: Number, default: 4 },
  /** 横轴标签最多显示几个（超出自动抽稀） */
  maxXLabels: { type: Number, default: 8 },
  /** 数值格式化（刻度与 tooltip 共用） */
  format: { type: Function, default: null },
  /** 是否从 0 开始，避免“缩放错觉” */
  startAtZero: { type: Boolean, default: true },
  emptyText: { type: String, default: '暂无趋势数据' },
  ariaLabel: { type: String, default: '折线图' },
})

const W = 640
const H = computed(() => Math.max(props.height, 120))
const PAD = { left: 40, right: 12, top: 12, bottom: 22 }

const normalizedSeries = computed(() => {
  const raw = props.series || []
  if (!raw.length) return []
  // 兼容 number[] 单序列
  if (typeof raw[0] === 'number') {
    return [{ name: '数值', data: raw, color: PALETTE[0] }]
  }
  return raw
    .filter((s) => s && Array.isArray(s.data))
    .map((s, i) => ({
      name: s.name || `序列 ${i + 1}`,
      color: s.color || PALETTE[i % PALETTE.length],
      data: s.data.map((v) => (Number.isFinite(Number(v)) ? Number(v) : null)),
      dashed: s.dashed === true,
      area: s.area !== false,
      emphasized: s.emphasized === true,
    }))
})

const pointCount = computed(() =>
  normalizedSeries.value.reduce((max, s) => Math.max(max, s.data.length), 0)
)

const hasData = computed(() => normalizedSeries.value.some((s) => s.data.some((v) => v !== null)))

const scale = computed(() => {
  const all = normalizedSeries.value.flatMap((s) => s.data.filter((v) => v !== null))
  if (!all.length) return { lo: 0, hi: 1, span: 1 }
  let lo = Math.min(...all)
  let hi = Math.max(...all)
  if (props.startAtZero && lo > 0) lo = 0
  if (lo === hi) hi = lo + (Math.abs(lo) || 1)
  return { lo, hi, span: hi - lo || 1 }
})

const ticks = computed(() => {
  const n = Math.max(2, props.yTicks)
  const { lo, hi } = scale.value
  const plotH = H.value - PAD.top - PAD.bottom
  return Array.from({ length: n + 1 }, (_, i) => {
    const value = lo + ((hi - lo) * i) / n
    return { value, y: PAD.top + plotH * (1 - i / n) }
  })
})

const xAt = (index) => {
  const n = Math.max(pointCount.value - 1, 1)
  const plotW = W - PAD.left - PAD.right
  return PAD.left + (index / n) * plotW
}

const yAt = (value) => {
  const plotH = H.value - PAD.top - PAD.bottom
  const { lo, span } = scale.value
  return PAD.top + (1 - (value - lo) / span) * plotH
}

const drawnSeries = computed(() =>
  normalizedSeries.value.map((s) => {
    const points = []
    s.data.forEach((v, i) => {
      if (v === null) return
      points.push({
        i,
        v,
        x: xAt(i),
        y: yAt(v),
        label: props.labels[i] ?? String(i + 1),
      })
    })
    const path = points
      .map((p, idx) => `${idx === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
      .join(' ')
    const areaPath = points.length
      ? `${path} L${points[points.length - 1].x.toFixed(1)},${H.value - PAD.bottom} L${points[0].x.toFixed(1)},${H.value - PAD.bottom} Z`
      : ''
    return { ...s, points, path, areaPath }
  })
)

const xLabels = computed(() => {
  const n = pointCount.value
  if (!n) return []
  const step = Math.max(1, Math.ceil(n / Math.max(1, props.maxXLabels)))
  return Array.from({ length: n }, (_, i) => i)
    .filter((i) => i % step === 0 || i === n - 1)
    .map((i) => ({
      index: i,
      x: xAt(i),
      text: props.labels[i] ?? String(i + 1),
    }))
})

function formatValue(v) {
  if (typeof props.format === 'function') return props.format(v)
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const abs = Math.abs(n)
  if (abs >= 10000) return `${(n / 1000).toFixed(abs >= 100000 ? 0 : 1)}k`
  if (Number.isInteger(n)) return String(n)
  return n.toFixed(abs < 10 ? 2 : 1)
}
</script>
