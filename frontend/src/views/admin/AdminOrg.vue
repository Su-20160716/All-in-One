<template>
  <div class="mx-auto max-w-6xl space-y-3">
    <div class="card flex flex-wrap items-center gap-2 p-4">
      <div>
        <h2 class="text-[15px] font-semibold">组织架构与数据权限</h2>
        <p class="mt-0.5 text-[12px] text-ink-500">
          部门树决定「本部门 / 本部门及下级」数据范围的可见人员；租户用于一套部署服务多个组织。
        </p>
      </div>
      <span v-if="scope.scope_label" class="tag ml-auto tag-brand">
        我的数据范围：{{ scope.scope_label }}<template v-if="scope.visible_user_count != null"> · 可见 {{ scope.visible_user_count }} 人</template>
      </span>
    </div>

    <div v-if="scope.scope" class="card grid gap-2 p-3 text-[12px] text-ink-600 md:grid-cols-4">
      <div>数据范围：<b>{{ scope.scope_label }}</b></div>
      <div>所属部门：<b>{{ scope.department || '未分配' }}</b></div>
      <div>所属租户：<b>{{ scope.tenant || '未关联' }}</b></div>
      <div>多租户开关：<b>{{ scope.tenancy_enabled ? '已启用' : '未启用' }}</b></div>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <!-- 部门树 -->
      <div class="card p-4">
        <div class="flex items-center justify-between">
          <div class="text-[13px] font-semibold text-ink-700">部门树</div>
          <div class="flex gap-1">
            <button class="btn-ghost px-2 text-[12px]" @click="loadDepts">刷新</button>
            <button class="btn-primary px-2 py-1 text-[12px]" @click="openDept(null)">＋ 顶级部门</button>
          </div>
        </div>
        <div class="mt-2 max-h-[62vh] overflow-y-auto">
          <DeptNode v-for="(d, i) in deptTree" :key="d.id" :node="d" :depth="0"
                    :can-up="i > 0" :can-down="i < deptTree.length - 1"
                    @add="openDept" @edit="openDept" @remove="removeDept" @move="moveDept" />
          <div v-if="!deptTree.length" class="py-10 text-center text-[12px] text-ink-400">暂无部门，点右上角新建</div>
        </div>
      </div>

      <!-- 租户 -->
      <div class="card p-4">
        <div class="flex items-center justify-between">
          <div class="text-[13px] font-semibold text-ink-700">租户列表</div>
          <button class="btn-primary px-2 py-1 text-[12px]" @click="openTenant(null)">＋ 新建租户</button>
        </div>
        <div class="mt-2 space-y-1.5">
          <div v-for="t in tenants" :key="t.id" class="rounded-control border border-ink-100 p-2.5">
            <div class="flex items-center gap-2">
              <span class="text-[13px] font-medium text-ink-800">{{ t.name }}</span>
              <span class="font-mono text-[11px] text-ink-400">{{ t.code }}</span>
              <span class="tag" :class="t.is_active ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
                {{ t.is_active ? '启用' : '停用' }}
              </span>
              <div class="ml-auto flex gap-1">
                <button class="btn-ghost px-2 text-[12px]" @click="openTenant(t)">编辑</button>
                <button class="btn-ghost px-2 text-[12px] text-rose-500" @click="removeTenant(t)">删除</button>
              </div>
            </div>
            <div class="mt-1 text-[11px] text-ink-400">
              {{ t.user_count }} 名用户 · {{ t.dept_count }} 个部门
              <template v-if="t.expire_at"> · 到期 {{ String(t.expire_at).slice(0, 10) }}</template>
            </div>
            <div v-if="t.remark" class="mt-0.5 text-[11px] text-ink-400">{{ t.remark }}</div>
          </div>
          <div v-if="!tenants.length" class="py-10 text-center text-[12px] text-ink-400">
            暂无租户。默认不启用多租户隔离，新增租户并开启开关后生效。
          </div>
        </div>
      </div>
    </div>

    <!-- 部门表单 -->
    <Modal :show="!!deptForm" :title="deptForm?.id ? '编辑部门' : '新建部门'" @close="deptForm = null">
      <div class="space-y-3">
        <input v-model="deptForm.name" class="input" placeholder="部门名称，如：研发中心" />
        <input v-model="deptForm.code" class="input" placeholder="部门编码（选填），如：RD" />
        <div>
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">上级部门</div>
          <select v-model="deptForm.parent" class="input">
            <option :value="null">（顶级部门）</option>
            <option v-for="o in parentOptions" :key="o.id" :value="o.id">{{ o.path_name }}</option>
          </select>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="mb-1.5 text-[12px] font-medium text-ink-600">负责人</div>
            <select v-model="deptForm.leader" class="input">
              <option :value="null">未指定</option>
              <option v-for="u in userOptions" :key="u.id" :value="u.id">{{ u.nickname || u.username }}</option>
            </select>
          </div>
          <div>
            <div class="mb-1.5 text-[12px] font-medium text-ink-600">排序（小在前）</div>
            <input v-model.number="deptForm.sort" type="number" class="input" />
          </div>
        </div>
        <div v-if="tenants.length">
          <div class="mb-1.5 text-[12px] font-medium text-ink-600">所属租户</div>
          <select v-model="deptForm.tenant" class="input">
            <option :value="null">不限制（全局部门）</option>
            <option v-for="t in tenants" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="deptForm = null">取消</button>
          <button class="btn-primary" @click="saveDept">保存</button>
        </div>
      </div>
    </Modal>

    <!-- 租户表单 -->
    <Modal :show="!!tenantForm" :title="tenantForm?.id ? '编辑租户' : '新建租户'" @close="tenantForm = null">
      <div class="space-y-3">
        <input v-model="tenantForm.name" class="input" placeholder="租户名称，如：星海科技" />
        <input v-model="tenantForm.code" class="input" placeholder="租户编码，如：xinghai" :disabled="!!tenantForm.id" />
        <textarea v-model="tenantForm.remark" rows="2" class="input" placeholder="备注（选填）"></textarea>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <div class="mb-1.5 text-[12px] font-medium text-ink-600">到期时间</div>
            <input v-model="tenantForm.expire_at" type="date" class="input" />
          </div>
          <label class="flex items-end gap-1.5 pb-2 text-[12px] text-ink-600">
            <input v-model="tenantForm.is_active" type="checkbox" /> 启用
          </label>
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="tenantForm = null">取消</button>
          <button class="btn-primary" @click="saveTenant">保存</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { orgApi, adminApi } from '../../api'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const app = useAppStore()
const scope = ref({})
const deptTree = ref([])
const flatDepts = ref([])
const tenants = ref([])
const userOptions = ref([])
const deptForm = ref(null)
const tenantForm = ref(null)

/* ---- 递归部门节点（函数式组件，避免再开一个文件）---- */
const DeptNode = {
  name: 'DeptNode',
  props: { node: Object, depth: Number, canUp: Boolean, canDown: Boolean },
  emits: ['add', 'edit', 'remove', 'move'],
  setup(props, { emit }) {
    const collapsed = ref(false)
    const render = () => {
      const d = props.node
      const pad = 8 + props.depth * 16
      const row = h('div', {
        class: 'flex items-center gap-2 rounded-control px-2 py-1.5 hover:bg-ink-50',
        style: { paddingLeft: pad + 'px' },
      }, [
        d.children?.length
          ? h('button', {
              class: 'w-4 shrink-0 text-[10px] text-ink-400',
              'aria-label': `${collapsed.value ? '展开' : '收起'}「${d.name}」的子部门`,
              'aria-expanded': !collapsed.value,
              onClick: () => { collapsed.value = !collapsed.value },
            }, collapsed.value ? '▶' : '▼')
          : h('span', { class: 'w-4 shrink-0' }),
        h('span', { class: 'text-[13px] font-medium text-ink-800' }, d.name),
        d.code ? h('span', { class: 'font-mono text-[11px] text-ink-400' }, d.code) : null,
        d.member_count ? h('span', { class: 'tag' }, `${d.member_count} 人`) : null,
        d.leader_name ? h('span', { class: 'text-[11px] text-ink-400' }, `负责人：${d.leader_name}`) : null,
        !d.is_active ? h('span', { class: 'tag bg-rose-50 text-rose-500' }, '停用') : null,
        h('div', { class: 'ml-auto flex shrink-0 gap-0.5' }, [
          // #194 上移/下移只有箭头字符，补可读名称并在边界禁用
          h('button', {
            class: 'btn-ghost px-1.5 text-[12px]',
            'aria-label': `上移「${d.name}」`,
            title: props.canUp ? `上移「${d.name}」` : '已经是第一个，无法上移',
            disabled: !props.canUp,
            onClick: () => emit('move', d, -1),
          }, '↑'),
          h('button', {
            class: 'btn-ghost px-1.5 text-[12px]',
            'aria-label': `下移「${d.name}」`,
            title: props.canDown ? `下移「${d.name}」` : '已经是最后一个，无法下移',
            disabled: !props.canDown,
            onClick: () => emit('move', d, 1),
          }, '↓'),
          h('button', { class: 'btn-ghost px-1.5 text-[12px]', onClick: () => emit('add', d.id) }, '＋子部门'),
          h('button', { class: 'btn-ghost px-1.5 text-[12px]', onClick: () => emit('edit', d) }, '编辑'),
          h('button', { class: 'btn-ghost px-1.5 text-[12px] text-rose-500', onClick: () => emit('remove', d) }, '删除'),
        ]),
      ])
      const kids = !collapsed.value && d.children?.length
        ? d.children.map((c, i) => h(DeptNode, {
            node: c,
            depth: props.depth + 1,
            canUp: i > 0,
            canDown: i < d.children.length - 1,
            onAdd: (v) => emit('add', v),
            onEdit: (v) => emit('edit', v),
            onRemove: (v) => emit('remove', v),
            onMove: (v, dir) => emit('move', v, dir),
          }))
        : []
      return h('div', [row, ...kids])
    }
    return render
  },
}

const parentOptions = computed(() =>
  flatDepts.value.filter((d) => d.id !== deptForm.value?.id),
)

function flatten(tree, out = []) {
  for (const n of tree) {
    out.push({ id: n.id, path_name: n.path_name || n.name })
    if (n.children?.length) flatten(n.children, out)
  }
  return out
}

async function loadScope() {
  try { scope.value = await orgApi.myScope() } catch (e) { /* ignore */ }
}
async function loadDepts() {
  const r = await orgApi.departments()
  deptTree.value = r.tree || []
  flatDepts.value = flatten(deptTree.value)
}
async function loadTenants() {
  tenants.value = (await orgApi.tenants()).list || []
}
async function loadUsers() {
  try { userOptions.value = (await adminApi.users({ page_size: 200 })).list || [] } catch (e) { /* ignore */ }
}

function openDept(payload) {
  if (payload && typeof payload === 'object') {
    deptForm.value = { id: payload.id, name: payload.name, code: payload.code || '', parent: payload.parent ?? null, leader: payload.leader ?? null, sort: payload.sort ?? 0, tenant: payload.tenant ?? null }
  } else {
    deptForm.value = { name: '', code: '', parent: payload ?? null, leader: null, sort: 0, tenant: null }
  }
}
async function saveDept() {
  const f = deptForm.value
  if (!f.name?.trim()) return app.toastMsg('请填写部门名称', 'error')
  const payload = { name: f.name, code: f.code, parent: f.parent, leader: f.leader, sort: f.sort, tenant: f.tenant }
  if (f.id) await orgApi.updateDepartment(f.id, payload)
  else await orgApi.createDepartment(payload)
  app.toastMsg('部门已保存', 'success')
  deptForm.value = null
  loadDepts()
}
async function removeDept(d) {
  if (!confirm(`删除部门「${d.name}」？`)) return
  try {
    await orgApi.deleteDepartment(d.id)
    app.toastMsg('部门已删除', 'success')
    loadDepts()
  } catch (e) { /* 后端会给出「仍有成员/子部门」的提示，request 拦截器已弹窗 */ }
}

// #194 上移/下移：在同一父级的兄弟节点间交换位置，按新顺序回写 sort
function findSiblingList(nodes, id) {
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i].id === id) return { list: nodes, index: i }
    const kids = nodes[i].children
    if (kids?.length) {
      const hit = findSiblingList(kids, id)
      if (hit) return hit
    }
  }
  return null
}
async function moveDept(d, dir) {
  const hit = findSiblingList(deptTree.value, d.id)
  if (!hit) return
  const target = hit.index + dir
  if (target < 0 || target >= hit.list.length) return
  const order = hit.list.map((n) => n.id)
  order.splice(target, 0, order.splice(hit.index, 1)[0])
  // 按新顺序重排 sort（步长 10）；只提交发生变化的节点，其余字段原样带上
  const updates = order
    .map((id, i) => {
      const node = hit.list.find((n) => n.id === id)
      const sort = (i + 1) * 10
      return { node, sort, changed: (node?.sort ?? 0) !== sort }
    })
    .filter((u) => u.changed && u.node)
  try {
    await Promise.all(updates.map((u) => orgApi.updateDepartment(u.node.id, {
      name: u.node.name,
      code: u.node.code || '',
      parent: u.node.parent ?? null,
      leader: u.node.leader ?? null,
      sort: u.sort,
      tenant: u.node.tenant ?? null,
    })))
    await loadDepts()
  } catch (e) {
    app.toastMsg(e?.message || '移动失败', 'error')
  }
}

function openTenant(t) {
  tenantForm.value = t
    ? { id: t.id, name: t.name, code: t.code, remark: t.remark || '', expire_at: t.expire_at ? String(t.expire_at).slice(0, 10) : '', is_active: t.is_active }
    : { name: '', code: '', remark: '', expire_at: '', is_active: true }
}
async function saveTenant() {
  const f = tenantForm.value
  if (!f.name?.trim() || !f.code?.trim()) return app.toastMsg('租户名与编码必填', 'error')
  const payload = { name: f.name, code: f.code, remark: f.remark, expire_at: f.expire_at || null, is_active: f.is_active }
  if (f.id) await orgApi.updateTenant(f.id, payload)
  else await orgApi.createTenant(payload)
  app.toastMsg('租户已保存', 'success')
  tenantForm.value = null
  loadTenants()
}
async function removeTenant(t) {
  if (!confirm(`删除租户「${t.name}」？`)) return
  try {
    await orgApi.deleteTenant(t.id)
    app.toastMsg('租户已删除', 'success')
    loadTenants()
  } catch (e) { /* ignore */ }
}

onMounted(() => { loadScope(); loadDepts(); loadTenants(); loadUsers() })
</script>
