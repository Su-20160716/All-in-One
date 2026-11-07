<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="fixed inset-0 z-[100] flex items-center justify-center bg-ink-900/40 p-4"
      @click.self="dismiss"
    >
      <div
        ref="dialogRef"
        class="max-h-[85vh] w-full overflow-y-auto rounded-card bg-white shadow-pop"
        :style="{ maxWidth: width }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="title ? titleId : undefined"
        tabindex="-1"
        @keydown="onKeydown"
      >
        <div class="flex items-center justify-between border-b border-ink-100 px-4 py-3">
          <h3 :id="titleId" class="text-[14px] font-semibold text-ink-800">{{ title }}</h3>
          <button type="button" class="text-ink-400 hover:text-ink-600" aria-label="关闭" @click="dismiss">✕</button>
        </div>
        <div class="p-4">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

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

const dialogRef = ref(null)
const titleId = `modal-title-${Math.random().toString(36).slice(2, 9)}`
let lastActive = null
let prevOverflow = ''

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables() {
  return dialogRef.value ? Array.from(dialogRef.value.querySelectorAll(FOCUSABLE)) : []
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    dismiss()
    return
  }
  if (e.key !== 'Tab') return
  // 焦点陷阱：Tab 在弹窗内循环，不逃逸到背景页面
  const list = focusables()
  if (!list.length) {
    e.preventDefault()
    dialogRef.value?.focus()
    return
  }
  const first = list[0]
  const last = list[list.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

async function onOpen() {
  lastActive = document.activeElement
  prevOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  await nextTick()
  const list = focusables()
  ;(list[0] || dialogRef.value)?.focus()
}

function onClose() {
  document.body.style.overflow = prevOverflow
  // 关闭后把焦点还给触发元素，键盘用户不会迷失在页面顶部
  if (lastActive && typeof lastActive.focus === 'function') lastActive.focus()
  lastActive = null
}

watch(visible, (open) => {
  if (open) onOpen()
  else onClose()
})

onBeforeUnmount(() => {
  if (visible.value) document.body.style.overflow = prevOverflow
})

function dismiss() {
  // 两个事件都发：旧监听方收 close，v-model 收 update:modelValue，互不干扰
  emit('close')
  emit('update:modelValue', false)
}
</script>
