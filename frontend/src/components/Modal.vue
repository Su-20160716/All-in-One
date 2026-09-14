<template>
  <Teleport to="body">
    <div v-if="show" class="fixed inset-0 z-[100] flex items-center justify-center bg-ink-900/40 p-4" @click.self="$emit('close')">
      <div class="max-h-[85vh] w-full overflow-y-auto rounded-card bg-white shadow-pop" :style="{ maxWidth: width }">
        <div class="flex items-center justify-between border-b border-ink-100 px-4 py-3">
          <h3 class="text-[14px] font-semibold text-ink-800">{{ title }}</h3>
          <button class="text-ink-400 hover:text-ink-600" @click="$emit('close')">✕</button>
        </div>
        <div class="p-4">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({
  show: Boolean,
  title: { type: String, default: '' },
  width: { type: String, default: '520px' },
})
defineEmits(['close'])
</script>
