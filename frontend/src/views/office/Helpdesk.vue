<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 标题 + 操作 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">工单台 Helpdesk</h2>
        <p class="text-[12px] text-ink-400">提交、指派、回复与关闭工单，支持按状态 / 优先级 / 分类筛选</p>
      </div>
      <button class="btn-primary" @click="openCreate">＋ 新建工单</button>
    </div>

    <!-- 筛选栏 -->
    <div class="card flex flex-wrap items-end gap-3 p-4">
      <label class="block"><span class="mb-1 block text-[12px] text-ink-500">状态</span>
        <select v-model="filters.status" class="input w-32">
          <option value="">全部</option>
          <option value="open">待处理</option>
          <option value="in_progress">处理中</option>
          <option value="resolved">已解决</option>
        </select>
      </label>
      <label class="block"><span class="mb-1 block text-[12px] text-ink-500">优先级</span>
        <select v-model="filters.priority" class="input w-32">
          <option value="">全部</option>
          <option value="low">低</option>
          <option value="normal">普通</option>
          <option value="high">高</option>
          <option value="urgent">紧急</option>
        </select>
      </label>
      <label class="block"><span class="mb-1 block text-[12px] text-ink-500">分类</span>
        <input v-model="filters.category" class="input w-36" placeholder="如：系统/账号" />
      </label>
      <button class="btn-primary" @click="loadList">筛选</button>
      <button class="btn-ghost" @click="resetFilters">重置</button>
      <span class="text-[12px] text-ink-400">共 {{ total }} 单</span>
    </div>

    <div class="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
      <!-- 工单列表 -->
      <div class="space-y-2">
        <div v-if="!list.length" class="card p-6 text-center text-[13px] text-ink-400">暂无符合条件的工单</div>
        <button v-for="t in list" :key="t.id" class="card w-full p-3 text-left"
          :class="selectedId === t.id ? 'ring-2 ring-brand-400' : ''" @click="select(t.id)">
          <div class="flex items-center gap-2">
            <span class="text-[13px] font-medium text-ink-800">#{{ t.id }} {{ t.title }}</span>
          </div>
          <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
            <span class="tag" :class="statusCls(t.status)">{{ statusName(t.status) }}</span>
            <span class="tag" :class="prioCls(t.priority)">{{ prioName(t.priority) }}</span>
            <span class="tag">{{ t.assignee_name || '未指派' }}</span>
          </div>
        </button>
      </div>

      <!-- 详情 -->
      <div class="card p-4">
        <div v-if="!detail" class="grid h-full place-items-center text-[13px] text-ink-400">请选择左侧工单查看详情</div>
        <div v-else class="space-y-3">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-[15px] font-semibold text-ink-800">#{{ detail.id }} {{ detail.title }}</h3>
            </div>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span class="tag" :class="statusCls(detail.status)">{{ statusName(detail.status) }}</span>
              <span class="tag" :class="prioCls(detail.priority)">{{ prioName(detail.priority) }}</span>
              <span class="tag">分类：{{ detail.category || '其他' }}</span>
              <span class="tag">负责人：{{ detail.assignee_name || '未指派' }}</span>
            </div>
          </div>

          <div v-if="detail.description" class="rounded-control bg-ink-50 p-3 text-[13px] leading-6 text-ink-700">{{ detail.description }}</div>

          <!-- 操作区 -->
          <div v-if="detail.status !== 'resolved'" class="space-y-2 rounded-control border border-ink-100 p-3">
            <div class="flex gap-2">
              <input v-model="assignee" class="input flex-1" placeholder="指派处理人（用户名）" />
              <button class="btn-outline" @click="doAssign">指派</button>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-[12px] text-ink-500">优先级</span>
              <button v-for="p in ['low', 'normal', 'high', 'urgent']" :key="p" class="tag"
                :class="detail.priority === p ? prioCls(p) : ''" @click="doPriority(p)">{{ prioName(p) }}</button>
            </div>
            <div class="flex gap-2">
              <input v-model="replyContent" class="input flex-1" placeholder="回复内容" @keyup.enter="doReply" />
              <button class="btn-primary" @click="doReply">回复</button>
            </div>
            <div class="flex gap-2">
              <input v-model="solution" class="input flex-1" placeholder="解决方案（可选）" />
              <button class="btn-outline" @click="doResolve">解决工单</button>
            </div>
          </div>
          <div v-else class="flex gap-2">
            <input v-model="reopenReason" class="input flex-1" placeholder="重开原因（可选）" />
            <button class="btn-outline" @click="doReopen">重开工单</button>
          </div>

          <!-- 回复记录 -->
          <div>
            <h4 class="mb-1 text-[13px] font-semibold text-ink-700">处理记录（{{ detail.replies.length }}）</h4>
            <div v-if="!detail.replies.length" class="text-[12px] text-ink-400">暂无回复</div>
            <div v-for="(r, i) in detail.replies" :key="i" class="mt-1 rounded-control bg-ink-50 p-2 text-[12px]">
              <span class="font-medium text-brand-700">{{ r.by }}</span>
              <span class="text-ink-400"> · {{ fmtTime(r.at) }}</span>
              <div class="text-ink-700">{{ r.content }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建工单 Modal -->
    <Modal :show="showCreate" title="新建工单" width="560px" @close="showCreate = false">
      <div class="space-y-3">
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">标题</span>
          <input v-model="form.title" class="input" placeholder="一句话描述问题" /></label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block"><span class="mb-1 block text-[12px] text-ink-500">优先级</span>
            <select v-model="form.priority" class="input">
              <option value="low">低</option><option value="normal">普通</option>
              <option value="high">高</option><option value="urgent">紧急</option>
            </select></label>
          <label class="block"><span class="mb-1 block text-[12px] text-ink-500">分类</span>
            <input v-model="form.category" class="input" placeholder="如：系统/账号" /></label>
        </div>
        <label class="block"><span class="mb-1 block text-[12px] text-ink-500">详细描述</span>
          <textarea v-model="form.description" rows="4" class="input" placeholder="复现步骤、期望结果等"></textarea></label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showCreate = false">取消</button>
          <button class="btn-primary" @click="doCreate">提交</button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { suiteApi } from '../../api'
import { useAppStore } from '../../stores/app'
import Modal from '../../components/Modal.vue'

const D = 'officesuite'
const app = useAppStore()

const STATUS = { open: '待处理', in_progress: '处理中', resolved: '已解决' }
const PRIO = { low: '低', normal: '普通', high: '高', urgent: '紧急' }
const statusName = (s) => STATUS[s] || s
const prioName = (p) => PRIO[p] || p
const statusCls = (s) => ({
  open: 'bg-sky-50 text-sky-600',
  in_progress: 'bg-amber-50 text-amber-600',
  resolved: 'bg-emerald-50 text-emerald-600',
}[s] || '')
const prioCls = (p) => ({
  low: 'bg-ink-100 text-ink-500',
  normal: 'bg-sky-50 text-sky-600',
  high: 'bg-orange-50 text-orange-600',
  urgent: 'bg-rose-50 text-rose-600',
}[p] || '')
function fmtTime(iso) {
  try { return iso.replace('T', ' ').slice(0, 16) } catch { return iso }
}

const filters = reactive({ status: '', priority: '', category: '' })
const list = ref([])
const total = ref(0)
const selectedId = ref(null)
const detail = ref(null)
const assignee = ref('')
const replyContent = ref('')
const solution = ref('')
const reopenReason = ref('')

async function loadList() {
  const params = {}
  if (filters.status) params.status = filters.status
  if (filters.priority) params.priority = filters.priority
  if (filters.category.trim()) params.category = filters.category.trim()
  const r = await suiteApi.call(D, 'ticket/list/', 'GET', params)
  list.value = r.data.items
  total.value = r.data.count
}
function resetFilters() {
  filters.status = ''; filters.priority = ''; filters.category = ''
  loadList()
}
async function select(id) {
  selectedId.value = id
  const r = await suiteApi.call(D, `ticket/${id}/`, 'GET')
  detail.value = r.data
}

const showCreate = ref(false)
const form = reactive({ title: '', priority: 'normal', category: '其他', description: '' })
function openCreate() {
  form.title = ''; form.priority = 'normal'; form.category = '其他'; form.description = ''
  showCreate.value = true
}
async function doCreate() {
  if (!form.title.trim()) return app.toastMsg('请填写标题', 'warn')
  await suiteApi.call(D, 'ticket/create/', 'POST', { ...form })
  showCreate.value = false
  app.toastMsg('工单已提交', 'success')
  await loadList()
}
async function doAssign() {
  if (!assignee.trim()) return app.toastMsg('请填写处理人', 'warn')
  await suiteApi.call(D, `ticket/${selectedId.value}/assign/`, 'POST', { assignee: assignee.trim() })
  app.toastMsg('已指派', 'success')
  await select(selectedId.value); await loadList()
}
async function doReply() {
  if (!replyContent.trim()) return app.toastMsg('请填写回复', 'warn')
  await suiteApi.call(D, `ticket/${selectedId.value}/reply/`, 'POST', { content: replyContent.trim() })
  replyContent.value = ''
  app.toastMsg('已回复', 'success')
  await select(selectedId.value)
}
async function doPriority(p) {
  await suiteApi.call(D, `ticket/${selectedId.value}/priority/`, 'POST', { priority: p })
  app.toastMsg(`优先级已调整为${prioName(p)}`, 'success')
  await select(selectedId.value); await loadList()
}
async function doResolve() {
  await suiteApi.call(D, `ticket/${selectedId.value}/resolve/`, 'POST', { solution: solution.value })
  solution.value = ''
  app.toastMsg('工单已解决', 'success')
  await select(selectedId.value); await loadList()
}
async function doReopen() {
  await suiteApi.call(D, `ticket/${selectedId.value}/reopen/`, 'POST', { reason: reopenReason.value })
  reopenReason.value = ''
  app.toastMsg('工单已重开', 'success')
  await select(selectedId.value); await loadList()
}

onMounted(loadList)
</script>
