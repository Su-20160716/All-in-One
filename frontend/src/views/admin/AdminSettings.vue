<template>
  <div class="mx-auto max-w-2xl space-y-4">
    <div class="card p-5">
      <h3 class="mb-3 text-[14px] font-semibold">站点设置（键值对）</h3>
      <div class="space-y-2">
        <div v-for="(item, key) in settings" :key="key" class="flex items-center gap-2">
          <span class="w-36 shrink-0 text-[12px] text-ink-500">{{ labels[key] || key }}</span>
          <input v-model="settings[key].value" class="input" />
        </div>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <input v-model="newKey" class="input w-36" placeholder="新键名" />
        <input v-model="newValue" class="input flex-1" placeholder="新键值" />
        <button class="btn-outline" @click="addRow">新增</button>
      </div>
      <button class="btn-primary mt-4" @click="save">保存全部</button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { coreApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const settings = reactive({})
const newKey = ref('')
const newValue = ref('')
const labels = {
  site_name: '站点名称',
  site_description: '站点描述',
  register_enabled: '开放注册(true/false)',
  contact_email: '联系邮箱',
  footer_text: '页脚文案',
}

async function load() {
  const r = await coreApi.adminSettings()
  Object.keys(r.settings).forEach((k) => (settings[k] = r.settings[k]))
}
function addRow() {
  if (!newKey.value) return
  settings[newKey.value] = { value: newValue.value, label: '' }
  newKey.value = ''
  newValue.value = ''
}
async function save() {
  const payload = {}
  Object.entries(settings).forEach(([k, v]) => (payload[k] = typeof v === 'string' ? v : v.value))
  await coreApi.saveAdminSettings(payload)
  app.toastMsg('已保存', 'success')
  load()
}
onMounted(load)
</script>
