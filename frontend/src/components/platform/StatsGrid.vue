<template>
  <div :class="gridClass" :style="styleColumns">
    <template v-if="loading && !items.length">
      <div v-for="n in Math.max(1, skeletonCount)" :key="`sk-${n}`" class="card space-y-2 p-3.5">
        <div class="h-3 w-20 animate-pulse rounded bg-ink-100"></div>
        <div class="h-6 w-24 animate-pulse rounded bg-ink-50"></div>
        <div class="h-3 w-16 animate-pulse rounded bg-ink-50"></div>
      </div>
    </template>

    <StatCard
      v-for="item in normalized"
      :key="item.key"
      :label="item.label"
      :value="item.value"
      :unit="item.unit"
      :hint="item.hint"
      :icon="item.icon"
      :delta="item.delta"
      :invert-delta="item.invertDelta === true"
      :format="format"
      :tone="item.tone || tone"
      :loading="loading"
      :clickable="clickable || item.clickable === true"
      @select="onSelect(item)"
    >
      <template v-if="item.footer" #footer>{{ item.footer }}</template>
    </StatCard>

    <slot />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import StatCard from './StatCard.vue'

const props = defineProps({
  /**
   * 指标集合：
   * [{ key, label, value, unit, hint, icon, delta, tone, invertDelta, footer, clickable }]
   */
  items: { type: Array, default: () => [] },
  /** 固定列数，0 表示按断点自适应（1/2/4 列） */
  columns: { type: Number, default: 0 },
  /** 加载态（已有数据时保留旧值，不闪骨架） */
  loading: { type: Boolean, default: false },
  /** 首屏加载占位卡片数量 */
  skeletonCount: { type: Number, default: 4 },
  /** 统一主题色，可被单条 item.tone 覆盖 */
  tone: { type: String, default: 'default' },
  /** 统一数值格式化函数 */
  format: { type: Function, default: null },
  clickable: { type: Boolean, default: false },
  /** 卡片间距：tight / normal / loose */
  gap: { type: String, default: 'normal' },
})
const emit = defineEmits(['select'])

const gridClass = computed(() => {
  const gap = props.gap === 'tight' ? 'gap-2' : props.gap === 'loose' ? 'gap-4' : 'gap-3'
  if (props.columns > 0) return `grid ${gap}`
  return `grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 ${gap}`
})

// 固定列数走内联样式，避免为 5/6/7 列写一堆 Tailwind 变体
const styleColumns = computed(() =>
  props.columns > 0
    ? { gridTemplateColumns: `repeat(${Math.max(1, props.columns)}, minmax(0, 1fr))` }
    : null
)

const normalized = computed(() =>
  (props.items || [])
    .filter((it) => it && typeof it === 'object')
    .map((it, idx) => ({ ...it, key: it.key ?? it.label ?? `stat-${idx}` }))
)

function onSelect(item) {
  emit('select', item)
}
</script>
