<template>
  <div class="mx-auto max-w-2xl space-y-4">
    <div class="card p-5">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">站点设置（键值对）</h3>
        <!-- #68 一键备份 -->
        <button class="btn-outline text-[12px]" @click="doBackup" :disabled="backingUp">
          {{ backingUp ? '备份中…' : '💾 一键备份数据' }}
        </button>
      </div>
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
const backingUp = ref(false)
const labels = {
  site_name: '站点名称',
  site_description: '站点描述',
  register_enabled: '开放注册(true/false)',
  register_invite_required: '注册需邀请码(true/false)',
  contact_email: '联系邮箱',
  footer_text: '页脚文案',
  logo_url: '站点 Logo URL',
  primary_color: '主题色（HEX）',
}

async function load() {
  const r = await coreApi.adminSettings()
  Object.keys(r.settings).forEach((k) => (settings[k] = r.settings[k]))
}
function addRow() {
  const key = newKey.value.trim()
  if (!key) return
  // #163 新增前查重：已有配置项不允许被静默覆盖
  if (Object.prototype.hasOwnProperty.call(settings, key)) {
    app.toastMsg(`配置项「${key}」已存在，请直接修改原值`, 'error')
    return
  }
  settings[key] = { value: newValue.value, label: '' }
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
// #68 一键备份
async function doBackup() {
  backingUp.value = true
  try {
    const r = await coreApi.backup()
    app.toastMsg(`备份完成: ${r.file} (${r.size_kb} KB)`, 'success')
  } catch (e) {
    app.toastMsg('备份失败', 'error')
  } finally {
    backingUp.value = false
  }
}
onMounted(load)
</script>
