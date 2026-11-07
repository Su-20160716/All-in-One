<template>
  <header class="flex flex-wrap items-start justify-between gap-3" :class="sticky ? 'sticky top-0 z-20 bg-ink-50/90 py-2 backdrop-blur' : ''">
    <div class="min-w-0 flex-1">
      <nav v-if="crumbs.length" class="mb-1 flex flex-wrap items-center gap-1 text-[11px] text-ink-400" aria-label="面包屑导航">
        <template v-for="(c, i) in crumbs" :key="`${i}-${c.label}`">
          <span v-if="i > 0" class="text-ink-300">/</span>
          <RouterLink v-if="c.to" :to="c.to" class="rounded px-0.5 hover:text-brand-600">
            {{ c.label }}
          </RouterLink>
          <span v-else class="px-0.5 text-ink-500">{{ c.label }}</span>
        </template>
      </nav>

      <div class="flex flex-wrap items-center gap-2">
        <h2 class="truncate text-[16px] font-semibold text-ink-800">{{ title }}</h2>
        <slot name="badge" />
      </div>

      <p v-if="subtitle" class="mt-0.5 max-w-3xl text-[12px] leading-relaxed text-ink-400">
        {{ subtitle }}
      </p>
      <div v-if="$slots.default" class="mt-2 text-[12px] text-ink-500">
        <slot />
      </div>
    </div>

    <div v-if="$slots.actions" class="flex flex-wrap items-center justify-end gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** 页面主标题 */
  title: { type: String, default: '' },
  /** 一句话说明，建议 40 字内 */
  subtitle: { type: String, default: '' },
  /** 面包屑：[{ label, to? }]，不带 to 的最后一级为当前位置 */
  crumbs: { type: Array, default: () => [] },
  /** 滚动时吸附在顶部（工作台长页面使用） */
  sticky: { type: Boolean, default: false },
})

// 结构化校验面包屑，避免调用方传入字符串数组时渲染出 undefined
const crumbs = computed(() =>
  (props.crumbs || [])
    .filter((c) => c && (typeof c === 'string' || c.label))
    .map((c) => (typeof c === 'string' ? { label: c, to: '' } : c))
)
</script>
