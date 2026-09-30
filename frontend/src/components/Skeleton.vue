<template>
  <div class="animate-pulse">
    <div v-if="rows" v-for="i in rows" :key="i" class="mb-3">
      <div class="h-4 rounded bg-ink-100" :style="{ width: (80 - i * 10) + '%' }"></div>
      <div class="mt-2 h-3 rounded bg-ink-50" :style="{ width: (60 + i * 5) + '%' }"></div>
    </div>
    <slot>
      <div class="h-32 rounded-card bg-ink-50"></div>
    </slot>
  </div>
</template>

<script setup>
defineProps({ rows: { type: Number, default: 0 } })
</script>
