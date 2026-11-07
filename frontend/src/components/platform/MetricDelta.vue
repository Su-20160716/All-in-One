<template>
  <span class="inline-flex items-center gap-0.5" :class="[sizeClass, toneClass]" :title="title">
    <span aria-hidden="true">{{ arrow }}</span>
    <span>{{ text }}</span>
    <span v-if="label" class="text-ink-400">{{ label }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 变化值：绝对值（12）或比例（0.12）；配合 mode 决定展示 */
  value: { type: [Number, String], default: 0 },
  /** percent：value 视为百分比数值；ratio：value 视为比例；raw：原样展示 */
  mode: { type: String, default: 'percent' },
  /** 涨跌是否反向着色（如失败率、延迟） */
  invert: { type: Boolean, default: false },
  /** 小数位 */
  precision: { type: Number, default: 1 },
  /** 数值后缀 */
  suffix: { type: String, default: '%' },
  /** 数值前缀 */
  prefix: { type: String, default: '' },
  /** 补充文案，如 “较上周” */
  label: { type: String, default: '' },
  /** 中性/正/负固定配色 */
  tone: { type: String, default: 'auto' },
  size: { type: String, default: 'sm' },
  /** 零值是否视为上涨 */
  zeroAsUp: { type: Boolean, default: false },
  /** 无数据占位 */
  placeholder: { type: String, default: '—' },
})

const num = computed(() => {
  const n = typeof props.value === 'number' ? props.value : Number(String(props.value).replace(/[%,\s]/g, ''))
  return Number.isFinite(n) ? n : null
})

const text = computed(() => {
  const n = num.value
  if (n === null) return props.placeholder
  const abs = Math.abs(n)
  let body
  if (props.mode === 'ratio') body = (abs * 100).toFixed(props.precision)
  else if (props.mode === 'raw') body = String(abs)
  else body = abs.toFixed(props.precision)
  // 去掉 12.0 这类无意义小数尾巴，同时保留 0.5 这样的有效位
  body = body.replace(/\.0+$/, '')
  return `${props.prefix}${body}${props.suffix}`
})

const direction = computed(() => {
  const n = num.value
  if (n === null || n === 0) return props.zeroAsUp ? 'up' : 'flat'
  return n > 0 ? 'up' : 'down'
})

const arrow = computed(() => ({ up: '▲', down: '▼', flat: '—' })[direction.value])

const toneClass = computed(() => {
  if (props.tone && props.tone !== 'auto') {
    return {
      up: 'text-emerald-600',
      down: 'text-rose-600',
      flat: 'text-ink-500',
      positive: 'text-emerald-600',
      negative: 'text-rose-600',
      neutral: 'text-ink-500',
    }[props.tone] || 'text-ink-500'
  }
  const d = direction.value
  if (d === 'flat') return 'text-ink-400'
  const good = d === 'up' ? !props.invert : props.invert
  return good ? 'text-emerald-600' : 'text-rose-600'
})

const sizeClass = computed(() => ({
  xs: 'text-[10px]',
  sm: 'text-[11px]',
  md: 'text-[13px]',
}[props.size] || 'text-[11px]'))

const title = computed(() => {
  const n = num.value
  if (n === null) return '暂无对比数据'
  const sign = n > 0 ? '+' : ''
  return `${props.label ? `${props.label} ` : ''}${sign}${n}${props.mode === 'percent' ? '%' : ''}`
})
</script>
