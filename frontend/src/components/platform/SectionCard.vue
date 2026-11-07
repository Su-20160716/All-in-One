<template>
  <section class="card flex min-w-0 flex-col" :class="dense ? 'p-3' : 'p-4'">
    <header
      v-if="title || subtitle || $slots.actions || collapsible"
      class="flex flex-wrap items-start justify-between gap-2"
      :class="dense ? 'mb-2' : 'mb-3'"
    >
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <button
            v-if="collapsible"
            type="button"
            class="grid h-5 w-5 shrink-0 place-items-center rounded-control text-[11px] text-ink-400 hover:bg-ink-100 hover:text-ink-600"
            :aria-expanded="String(!isCollapsed)"
            :aria-label="isCollapsed ? '展开' : '收起'"
            @click="toggle"
          >
            <span class="transition-transform" :class="isCollapsed ? '' : 'rotate-90'">▸</span>
          </button>
          <h3 v-if="title" class="truncate text-[14px] font-semibold text-ink-800">{{ title }}</h3>
          <slot name="badge" />
        </div>
        <p v-if="subtitle" class="mt-0.5 text-[12px] text-ink-400">{{ subtitle }}</p>
      </div>

      <div v-if="$slots.actions" class="flex flex-wrap items-center gap-1.5">
        <slot name="actions" />
      </div>
    </header>

    <div v-show="!isCollapsed" class="min-w-0 flex-1">
      <slot />
    </div>

    <footer v-if="$slots.footer && !isCollapsed" class="mt-3 border-t border-ink-100 pt-2.5 text-[12px] text-ink-500">
      <slot name="footer" />
    </footer>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  /** 是否允许折叠（折叠状态内部维护，也可用 v-model:collapsed 受控） */
  collapsible: { type: Boolean, default: false },
  /** 受控折叠状态；不传时使用内部状态 */
  collapsed: { type: Boolean, default: undefined },
  /** 紧凑内边距，用于嵌套卡片或侧栏 */
  dense: { type: Boolean, default: false },
})
const emit = defineEmits(['update:collapsed'])

const inner = ref(false)
const isCollapsed = computed(() => (props.collapsed === undefined ? inner.value : props.collapsed))

// 受控切换时把外部值同步回内部，避免下次取消受控后状态跳变
watch(
  () => props.collapsed,
  (v) => {
    if (typeof v === 'boolean') inner.value = v
  }
)

function toggle() {
  if (!props.collapsible) return
  const next = !isCollapsed.value
  inner.value = next
  emit('update:collapsed', next)
}
</script>
