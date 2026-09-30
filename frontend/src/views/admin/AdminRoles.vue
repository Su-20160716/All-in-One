<template>
  <div class="mx-auto max-w-6xl space-y-3">
    <div class="card flex items-center justify-between p-4">
      <div>
        <h2 class="text-[15px] font-semibold">角色与权限</h2>
        <p class="mt-0.5 text-[12px] text-ink-500">RBAC：角色绑定权限点，用户绑定角色。</p>
      </div>
      <button class="btn-primary" @click="editing = { name: '', code: '', description: '', permission_ids: [], data_scope: 'self' }">＋ 新建角色</button>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <div v-for="r in roles" :key="r.id" class="card p-4">
        <div class="flex items-center justify-between">
          <div>
            <span class="text-[14px] font-semibold">{{ r.name }}</span>
            <span class="ml-2 font-mono text-[11px] text-ink-400">{{ r.code }}</span>
            <span v-if="r.is_builtin" class="tag ml-1 bg-amber-50 text-amber-600">内置</span>
            <span class="tag ml-1">{{ r.user_count }} 人</span>
            <span class="tag ml-1 bg-violet-50 text-violet-600" :title="'数据行级权限范围'">数据范围：{{ r.data_scope_label || r.data_scope }}</span>
          </div>
          <div class="flex gap-1">
            <button class="btn-ghost px-2 text-[12px]" @click="editRole(r)">编辑</button>
            <button v-if="!r.is_builtin" class="btn-ghost px-2 text-[12px] text-rose-500" @click="removeRole(r)">删除</button>
          </div>
        </div>
        <p class="mt-1 text-[12px] text-ink-500">{{ r.description || '暂无描述' }}</p>
        <div class="mt-2.5 flex flex-wrap gap-1">
          <span v-for="p in permissionNames(r.permission_ids)" :key="p" class="tag tag-brand">{{ p }}</span>
          <span v-if="!r.permission_ids?.length" class="text-[11px] text-ink-300">未配置权限</span>
        </div>
      </div>
    </div>

    <Modal :show="!!editing" :title="editing?.id ? '编辑角色' : '新建角色'" width="680px" @close="editing = null">
      <div class="space-y-3">
        <div class="grid grid-cols-2 gap-3">
          <input v-model="editing.name" class="input" placeholder="角色名，如：运营" />
          <input v-model="editing.code" class="input" placeholder="编码，如 operator" :disabled="editing?.is_builtin" />
        </div>
        <input v-model="editing.description" class="input" placeholder="描述（选填）" />
        <div class="rounded-control border border-ink-100 p-2.5">
          <div class="text-[12px] font-medium text-ink-600">数据行级权限（Data Scope）</div>
          <p class="mt-0.5 text-[11px] text-ink-400">
            控制该角色用户能看到「谁的」数据；多角色时取最高级别。行级过滤由 core.scoping 统一收口。
          </p>
          <div class="mt-2 flex flex-wrap gap-2">
            <label v-for="s in DATA_SCOPES" :key="s.v"
                   class="flex cursor-pointer items-center gap-1.5 rounded-control border px-2 py-1 text-[12px]"
                   :class="editing.data_scope === s.v ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-ink-100'">
              <input v-model="editing.data_scope" type="radio" :value="s.v" />
              {{ s.label }}
            </label>
          </div>
        </div>
        <div>
          <div class="mb-1.5 flex items-center justify-between text-[12px] font-medium text-ink-600">
            <span>权限点（按模块）</span>
            <div class="flex gap-2">
              <!-- #74 权限点搜索过滤 -->
              <input v-model="permSearch" class="input w-32 text-[11px]" placeholder="搜索权限…" />
              <button class="text-brand-600" @click="toggleAllPerms(true)">全选</button>
              <button class="text-ink-400" @click="toggleAllPerms(false)">清空</button>
            </div>
          </div>
          <div class="max-h-64 space-y-2 overflow-y-auto rounded-control border border-ink-100 p-2">
            <div v-for="(items, mod) in filteredGrouped" :key="mod">
              <div class="text-[11px] font-semibold uppercase text-ink-400">{{ mod }}</div>
              <label v-for="p in items" :key="p.id" class="flex items-center gap-1.5 rounded px-1 py-0.5 text-[12px] hover:bg-ink-50">
                <input v-model="editing.permission_ids" type="checkbox" :value="p.id" />
                {{ p.name }}<span class="ml-auto font-mono text-[10px] text-ink-300">{{ p.code }}</span>
              </label>
            </div>
          </div>
        </div>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="editing = null">取消</button><button class="btn-primary" @click="saveRole">保存</button></div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { adminApi } from '../../api'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const roles = ref([])
const permissions = ref([])
const grouped = ref({})
const editing = ref(null)
const permSearch = ref('')

// #74 权限点搜索过滤
const filteredGrouped = computed(() => {
  if (!permSearch.value) return grouped.value
  const q = permSearch.value.toLowerCase()
  const out = {}
  for (const [mod, items] of Object.entries(grouped.value)) {
    const filtered = items.filter(p => p.name.toLowerCase().includes(q) || p.code.toLowerCase().includes(q))
    if (filtered.length) out[mod] = filtered
  }
  return out
})

function permissionNames(ids) {
  return permissions.value.filter((p) => ids?.includes(p.id)).map((p) => p.name)
}
async function load() { roles.value = (await adminApi.roles()).list || [] }
async function loadPerms() {
  const r = await adminApi.permissions({ grouped: 1 })
  permissions.value = r.list || []
  grouped.value = r.grouped || {}
}
function editRole(r) { editing.value = { ...r, permission_ids: [...(r.permission_ids || [])], data_scope: r.data_scope || 'self' } }
function toggleAllPerms(on) {
  editing.value.permission_ids = on ? permissions.value.map((p) => p.id) : []
}
async function saveRole() {
  const payload = { name: editing.value.name, description: editing.value.description, permission_ids: editing.value.permission_ids, data_scope: editing.value.data_scope || 'self' }
  if (editing.value.id) await adminApi.updateRole(editing.value.id, payload)
  else await adminApi.createRole({ ...payload, code: editing.value.code })
  app.toastMsg('已保存', 'success')
  editing.value = null
  load()
}
async function removeRole(r) {
  if (!confirm(`删除角色「${r.name}」？`)) return
  await adminApi.deleteRole(r.id)
  load()
}
onMounted(() => { load(); loadPerms() })
</script>
