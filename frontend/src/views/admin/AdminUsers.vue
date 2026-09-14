<template>
  <div class="mx-auto max-w-6xl space-y-3">
    <div class="card flex flex-wrap items-center gap-2 p-3">
      <input v-model="keyword" class="input w-56" placeholder="搜索用户名/昵称/邮箱…" @keyup.enter="load" />
      <select v-model="statusFilter" class="input w-32" @change="load">
        <option value="">全部状态</option><option value="active">正常</option><option value="disabled">已禁用</option><option value="online">在线</option>
      </select>
      <select v-model="roleFilter" class="input w-32" @change="load">
        <option value="">全部角色</option>
        <option v-for="r in allRoles" :key="r.id" :value="r.id">{{ r.name }}</option>
      </select>
      <button class="btn-primary" @click="load">查询</button>
      <button class="btn-outline ml-auto" @click="openCreate">＋ 新建用户</button>
    </div>

    <div v-if="selected.size" class="card flex flex-wrap items-center gap-2 p-2.5">
      <span class="text-[12px] text-ink-500">已选 {{ selected.size }} 人</span>
      <button class="btn-outline px-2 text-[12px]" @click="batch('enable')">批量启用</button>
      <button class="btn-outline px-2 text-[12px]" @click="batch('disable')">批量禁用</button>
      <button class="btn-outline px-2 text-[12px]" @click="batchQuota">统一配额</button>
      <button class="btn-outline px-2 text-[12px]" @click="batchAssignRoles">分配角色</button>
      <button class="btn-ghost px-2 text-[12px]" @click="selected = new Set()">取消</button>
    </div>

    <div class="card overflow-x-auto">
      <table class="w-full min-w-[860px]">
        <thead class="border-b border-ink-100 bg-ink-50/50">
          <tr>
            <th class="th w-8"><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
            <th class="th">用户</th><th class="th">部门</th><th class="th">角色</th><th class="th">配额</th><th class="th">状态</th><th class="th">最近活跃</th><th class="th">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-ink-50">
          <tr v-for="u in users" :key="u.id" class="hover:bg-ink-50/40">
            <td class="td"><input type="checkbox" :checked="selected.has(u.id)" @change="toggleOne(u.id)" /></td>
            <td class="td">
              <div class="flex items-center gap-2.5">
                <img v-if="u.avatar" :src="u.avatar" class="h-8 w-8 rounded-full object-cover" />
                <div v-else class="grid h-8 w-8 place-items-center rounded-full bg-brand-100 text-[12px] font-semibold text-brand-700">{{ (u.nickname || u.username).slice(0, 1) }}</div>
                <div>
                  <div class="font-medium">{{ u.nickname || u.username }} <span v-if="u.is_superuser" class="tag bg-amber-50 text-amber-600">超管</span></div>
                  <div class="text-[11px] text-ink-400">@{{ u.username }} · {{ u.email || '无邮箱' }}</div>
                </div>
              </div>
            </td>
            <td class="td">
              <span v-if="u.department_path" class="tag">{{ u.department_path }}</span>
              <span v-else class="text-[12px] text-ink-300">未分配</span>
              <div v-if="u.tenant_name" class="mt-0.5 text-[11px] text-ink-400">租户：{{ u.tenant_name }}</div>
            </td>
            <td class="td"><span v-for="r in u.role_names" :key="r" class="mr-1 tag tag-brand">{{ r }}</span></td>
            <td class="td">{{ u.storage_quota_mb }} MB</td>
            <td class="td"><span class="tag" :class="u.is_disabled ? 'bg-rose-50 text-rose-600' : 'bg-emerald-50 text-emerald-600'">{{ u.is_disabled ? '已禁用' : '正常' }}</span></td>
            <td class="td text-ink-500">{{ formatTime(u.last_active_at || u.last_login) }}</td>
            <td class="td whitespace-nowrap">
              <button class="btn-ghost px-2 text-[12px]" @click="editUser(u)">编辑</button>
              <button class="btn-ghost px-2 text-[12px]" @click="resetPwd(u)">重置密码</button>
              <button class="btn-ghost px-2 text-[12px]" :class="u.is_disabled ? 'text-emerald-500' : 'text-rose-500'" @click="toggleDisable(u)">{{ u.is_disabled ? '启用' : '禁用' }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!users.length" class="py-14 text-center text-[13px] text-ink-400">暂无用户</div>
    </div>

    <Modal :show="!!editing" :title="editing?.id ? `编辑 ${editing.username}` : '新建用户'" @close="editing = null">
      <div class="space-y-3">
        <input v-if="!editing?.id" v-model="form.username" class="input" placeholder="用户名" />
        <input v-if="!editing?.id" v-model="form.password" type="password" class="input" placeholder="初始密码（≥6 位）" />
        <input v-model="form.nickname" class="input" placeholder="昵称" />
        <input v-model="form.email" class="input" placeholder="邮箱" />
        <input v-model="form.phone" class="input" placeholder="手机号" />
        <input v-model.number="form.storage_quota_mb" type="number" class="input" placeholder="存储配额 MB" />
        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="mb-1.5 text-[12px] font-medium text-ink-600">所属部门</div>
            <select v-model="form.department" class="input">
              <option :value="null">未分配</option>
              <option v-for="d in flatDepts" :key="d.id" :value="d.id">{{ d.path_name }}</option>
            </select>
          </div>
          <div v-if="tenants.length">
            <div class="mb-1.5 text-[12px] font-medium text-ink-600">所属租户</div>
            <select v-model="form.tenant" class="input">
              <option :value="null">未关联</option>
              <option v-for="t in tenants" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </div>
        </div>
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">角色</div>
          <div class="flex flex-wrap gap-2">
            <label v-for="r in allRoles" :key="r.id" class="flex items-center gap-1.5 text-[13px]"><input v-model="form.role_ids" type="checkbox" :value="r.id" /> {{ r.name }}</label>
          </div>
        </div>
        <div class="flex justify-end gap-2"><button class="btn-ghost" @click="editing = null">取消</button><button class="btn-primary" @click="saveUser">保存</button></div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { adminApi, orgApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatTime } from '../../utils/format'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const users = ref([])
const allRoles = ref([])
const flatDepts = ref([])
const tenants = ref([])
const keyword = ref('')
const statusFilter = ref('')
const roleFilter = ref('')
const selected = ref(new Set())
const editing = ref(null)
const form = reactive({ username: '', password: '', nickname: '', email: '', phone: '', storage_quota_mb: 2048, role_ids: [], department: null, tenant: null })
const allChecked = computed(() => users.value.length > 0 && users.value.every((u) => selected.value.has(u.id)))

async function load() {
  users.value = (await adminApi.users({ keyword: keyword.value || undefined, status: statusFilter.value || undefined, role: roleFilter.value || undefined, page_size: 100 })).list || []
}
async function loadRoles() { allRoles.value = (await adminApi.roles()).list || [] }
async function loadOrg() {
  try {
    const r = await orgApi.departments({ flat: 1 })
    flatDepts.value = r.list || []
    tenants.value = (await orgApi.tenants()).list || []
  } catch (e) { /* 组织架构未启用时忽略 */ }
}
function openCreate() {
  Object.assign(form, { username: '', password: '', nickname: '', email: '', phone: '', storage_quota_mb: 2048, role_ids: [], department: null, tenant: null })
  editing.value = {}
}
function editUser(u) {
  editing.value = u
  Object.assign(form, { username: u.username, password: '', nickname: u.nickname || '', email: u.email || '', phone: u.phone || '', storage_quota_mb: u.storage_quota_mb, role_ids: [...(u.role_ids || [])], department: u.department ?? null, tenant: u.tenant ?? null })
}
async function saveUser() {
  if (editing.value.id) {
    await adminApi.updateUser(editing.value.id, { nickname: form.nickname, email: form.email, phone: form.phone, storage_quota_mb: form.storage_quota_mb, role_ids: form.role_ids, department: form.department, tenant: form.tenant })
  } else {
    await adminApi.createUser({ ...form })
  }
  app.toastMsg('已保存', 'success')
  editing.value = null
  load()
}
async function resetPwd(u) {
  const np = prompt(`为 ${u.username} 设置新密码（≥6 位）：`)
  if (!np) return
  await adminApi.resetPassword(u.id, np)
  app.toastMsg('密码已重置', 'success')
}
async function toggleDisable(u) {
  await adminApi.updateUser(u.id, { is_disabled: !u.is_disabled })
  load()
}
function toggleOne(id) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
function toggleAll() {
  selected.value = allChecked.value ? new Set() : new Set(users.value.map((u) => u.id))
}
async function batch(action) {
  await adminApi.batch({ action, user_ids: [...selected.value] })
  app.toastMsg('批量操作完成', 'success')
  selected.value = new Set()
  load()
}
async function batchQuota() {
  const q = prompt('统一存储配额（MB）：')
  if (!q) return
  await adminApi.batch({ action: 'quota', user_ids: [...selected.value], storage_quota_mb: Number(q) })
  load()
}
async function batchAssignRoles() {
  const ids = prompt('输入要分配的角色 ID（逗号分隔，可选：' + allRoles.value.map((r) => `${r.id}=${r.name}`).join('，') + '）：')
  if (!ids) return
  const roleIds = ids.split(',').map((x) => Number(x.trim())).filter(Boolean)
  await adminApi.assignRoles([...selected.value], roleIds)
  app.toastMsg('已分配角色', 'success')
  load()
}
onMounted(() => { load(); loadRoles(); loadOrg() })
</script>
