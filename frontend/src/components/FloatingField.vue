<template>
  <div class="relative">
    <input
      :id="id"
      :value="modelValue"
      :type="type"
      :inputmode="inputmode"
      :maxlength="maxlength"
      :autocomplete="autocomplete"
      :required="required"
      class="floating-input input"
      @input="$emit('update:modelValue', $event.target.value)"
      @focus="focused = true"
      @blur="focused = false"
    />
    <label
      :for="id"
      class="floating-label"
      :class="raised ? 'floating-label--raised' : ''"
    >{{ label }}</label>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, required: true },
  id: { type: String, required: true },
  type: { type: String, default: 'text' },
  inputmode: { type: String, default: undefined },
  maxlength: { type: [String, Number], default: undefined },
  autocomplete: { type: String, default: 'off' },
  required: { type: Boolean, default: false },
})

defineEmits(['update:modelValue'])

const focused = ref(false)
// 聚焦或有内容时标签上移缩小；初始状态标签留在输入框内
const raised = computed(() => focused.value || !!props.modelValue)
</script>

<style scoped>
.floating-input {
  padding-top: 1.35rem;
  padding-bottom: 0.35rem;
}

.floating-label {
  position: absolute;
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 13px;
  color: var(--color-ink-400);
  pointer-events: none;
  transition: all 0.18s var(--ease-spring, ease);
}

.floating-label--raised {
  top: 0.32rem;
  transform: none;
  font-size: 10.5px;
  color: var(--color-ink-500);
}
</style>
