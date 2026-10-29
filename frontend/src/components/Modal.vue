<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="fixed inset-0 z-[100] flex items-center justify-center bg-ink-900/40 p-4"
      @click.self="dismiss"
    >
      <div class="max-h-[85vh] w-full overflow-y-auto rounded-card bg-white shadow-pop" :style="{ maxWidth: width }">
        <div class="flex items-center justify-between border-b border-ink-100 px-4 py-3">
          <h3 class="text-[14px] font-semibold text-ink-800">{{ title }}</h3>
          <button class="text-ink-400 hover:text-ink-600" @click="dismiss">✕</button>
        </div>
        <div class="p-4">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  // F1：v-model 支持。新代码用 v-model，旧代码继续用 :show + @close 不受影响
  // ⚠ 必须显式 default: undefined —— Boolean prop 未传时 Vue 会强转成 false，
  //   那样 `modelValue ?? props.show` 永远取 false，导致所有 :show 弹窗静默失效。
  modelValue: { type: Boolean, default: undefined },
  title: { type: String, default: '' },
  width: { type: String, default: '520px' },
})
const emit = defineEmits(['close', 'update:modelValue'])

// 显式传了 modelValue 以它为准，否则回落到 show（向后兼容）
const visible = computed(() => props.modelValue ?? props.show)

function dismiss() {
  // 两个事件都发：旧监听方收 close，v-model 收 update:modelValue，互不干扰
  emit('close')
  emit('update:modelValue', false)
}
</script>
