<template>
  <component
    :is="clickable ? 'button' : 'div'"
    :type="clickable ? 'button' : undefined"
    class="card flex min-w-0 flex-col gap-1 p-3.5 text-left transition-colors"
    :class="[clickable ? 'hover:border-brand-300 hover:shadow-pop' : '', toneRing]"
    :aria-busy="loading ? 'true' : undefined"
    @click="clickable && !loading && emit('select', label)"
  >
    <div class="flex items-start justify-between gap-2">
      <span class="min-w-0 truncate text-[12px] text-ink-500">{{ label }}</span>
      <span v-if="icon" class="shrink-0 text-[15px] leading-none text-ink-400" aria-hidden="true">{{ icon }}</span>
    </div>

    <div v-if="loading" class="mt-1 space-y-1.5">
      <div class="h-6 w-24 animate-pulse rounded bg-ink-100"></div>
      <div class="h-3 w-16 animate-pulse rounded bg-ink-50"></div>
    </div>
    <template v-else>
      <div class="flex flex-wrap items-baseline gap-1">
        <span class="text-[22px] font-semibold leading-tight text-ink-900">{{ displayValue }}</span>
        <span v-if="unit" class="text-[11px] text-ink-400">{{ unit }}</span>
      </div>

      <div class="flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
        <MetricDelta v-if="delta !== null && delta !== undefined" :value="delta" :invert="invertDelta" />
        <span v-if="hint" class="min-w-0 truncate">{{ hint }}</span>
      </div>
    </template>

    <div v-if="$slots.footer" class="mt-1 border-t border-ink-50 pt-1.5 text-[11px] text-ink-500">
      <slot name="footer" />
    </div>
  </component>
</template>

<script setup>
import { computed } from 'vue'
import MetricDelta from './MetricDelta.vue'

const props = defineProps({
  /** 指标名称 */
  label: { type: String, default: '' },
  /** 指标值，允许字符串（后端已格式化）或数字 */
  value: { type: [String, Number], default: null },
  /** 单位，如 “单 / 小时 / %” */
  unit: { type: String, default: '' },
  /** 补充说明，展示在数值下方 */
  hint: { type: String, default: '' },
  /** 图标文本（emoji 或单字符） */
  icon: { type: String, default: '' },
  /** 环比变化，null 表示不展示 */
  delta: { type: [Number, String], default: null },
  /** 指标越低越好时反转涨跌配色 */
  invertDelta: { type: Boolean, default: false },
  /** 数值格式化，缺省按千分位数字或原样字符串 */
  format: { type: Function, default: null },
  /** 空值占位 */
  placeholder: { type: String, default: '—' },
  loading: { type: Boolean, default: false },
  clickable: { type: Boolean, default: false },
  /** 主题色描边：default / brand / emerald / amber / rose */
  tone: { type: String, default: 'default' },
})
const emit = defineEmits(['select'])

const TONES = {
  default: '',
  brand: 'border-brand-200',
  emerald: 'border-emerald-200',
  amber: 'border-amber-200',
  rose: 'border-rose-200',
}

const toneRing = computed(() => TONES[props.tone] || '')

const displayValue = computed(() => {
  const v = props.value
  if (v === null || v === undefined || v === '') return props.placeholder
  if (typeof props.format === 'function') return props.format(v)
  if (typeof v === 'number') return Number.isFinite(v) ? v.toLocaleString('zh-CN') : props.placeholder
  return String(v)
})
</script>
