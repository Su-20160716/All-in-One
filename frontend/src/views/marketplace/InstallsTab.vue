<template>
  <div class="space-y-3">
    <div class="card space-y-2 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="q"
          class="input w-full sm:w-[240px]"
          placeholder="搜索已安装应用"
          aria-label="搜索已安装应用"
        />
        <select v-model="status" class="input w-[140px] py-1" aria-label="按安装状态筛选">
          <option value="">全部状态</option>
          <option value="installed">已启用</option>
          <option value="disabled">已停用</option>
          <option value="uninstalled">已卸载</option>
        </select>
        <button class="btn-ghost py-1 text-[12px]" @click="resetFilters">重置</button>
        <div class="ml-auto flex items-center gap-1.5">
          <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'listings')">去应用目录</button>
          <button class="btn-outline py-1 text-[12px]" :disabled="loading" @click="loadInstalls">
            {{ loading ? '刷新中…' : '刷新安装' }}
          </button>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-400">
        <span class="tag">筛选结果 {{ fmtNum(total) }} 条</span>
        <span class="tag">账号安装 {{ fmtNum(summaryItems.length) }} 个</span>
        <span class="tag">许可证 {{ fmtNum(licenseTotal) }} 张</span>
        <span v-if="lastLoadedAt" class="ml-auto">更新于 {{ fmtDate(lastLoadedAt, true) }}</span>
      </div>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">已启用</div>
        <div class="mt-0.5 text-[20px] font-semibold text-emerald-600">{{ fmtNum(summaryCounts.installed) }}</div>
        <div class="text-[11px] text-ink-400">正常可用的应用</div>
      </div>
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">已停用</div>
        <div class="mt-0.5 text-[20px] font-semibold text-amber-600">{{ fmtNum(summaryCounts.disabled) }}</div>
        <div class="text-[11px] text-ink-400">仍计入安装量</div>
      </div>
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">已卸载</div>
        <div class="mt-0.5 text-[20px] font-semibold text-ink-500">{{ fmtNum(summaryCounts.uninstalled) }}</div>
        <div class="text-[11px] text-ink-400">可随时重新安装</div>
      </div>
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">自动更新</div>
        <div class="mt-0.5 text-[20px] font-semibold text-brand-600">{{ fmtNum(summaryCounts.autoUpdate) }}</div>
        <div class="text-[11px] text-ink-400">升级检查仍以手动确认为准</div>
      </div>
    </div>

    <SectionCard title="已安装应用" subtitle="配置、升级检查、启停与卸载均直接作用于安装记录">
      <template #actions>
        <span class="tag">共 {{ fmtNum(total) }} 条</span>
      </template>

      <div v-if="error" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1 truncate">{{ error }}</span>
        <button class="shrink-0 font-medium" @click="loadInstalls">重试</button>
      </div>
      <div v-else-if="loading && !items.length" class="py-12 text-center text-[12px] text-ink-400">安装记录加载中…</div>
      <div v-else-if="!items.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
        还没有安装记录，去应用目录挑选应用安装
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[860px]">
          <thead class="border-b border-ink-100 bg-ink-50/60">
            <tr>
              <th class="th">应用</th>
              <th class="th">版本</th>
              <th class="th">状态</th>
              <th class="th">自动更新</th>
              <th class="th">安装时间</th>
              <th class="th">最近升级</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in items" :key="row.id" class="hover:bg-ink-50/40">
              <td class="td">
                <div class="flex items-center gap-2">
                  <span class="grid h-8 w-8 shrink-0 place-items-center rounded-control bg-brand-50 text-[12px] font-semibold text-brand-700">
                    {{ (row.listing?.name || '应').slice(0, 1) }}
                  </span>
                  <div class="min-w-0">
                    <div class="max-w-[220px] truncate font-medium text-ink-800">{{ row.listing?.name || '应用已删除' }}</div>
                    <div class="max-w-[220px] truncate text-[11px] text-ink-400">{{ row.listing?.code || '—' }}</div>
                  </div>
                </div>
              </td>
              <td class="td font-mono">{{ row.version?.version || '—' }}</td>
              <td class="td">
                <span class="tag" :class="installClass(row.status)">{{ installLabel(row.status) }}</span>
              </td>
              <td class="td">{{ row.auto_update ? '开启' : '关闭' }}</td>
              <td class="td text-[11px] text-ink-500">{{ fmtDate(row.installed_at, true) }}</td>
              <td class="td text-[11px] text-ink-500">{{ fmtDate(row.last_upgraded_at, true) }}</td>
              <td class="td">
                <div class="flex flex-wrap justify-end gap-1">
                  <button class="btn-ghost py-0.5 text-[11px]" @click="openConfig(row)">配置</button>
                  <button
                    class="btn-ghost py-0.5 text-[11px]"
                    :disabled="row.status === 'uninstalled'"
                    @click="openUpgrade(row)"
                  >
                    升级检查
                  </button>
                  <button
                    v-if="row.status === 'installed'"
                    class="btn-ghost py-0.5 text-[11px]"
                    @click="toggleInstall(row, false)"
                  >
                    停用
                  </button>
                  <button
                    v-else-if="row.status === 'disabled'"
                    class="btn-ghost py-0.5 text-[11px]"
                    @click="toggleInstall(row, true)"
                  >
                    启用
                  </button>
                  <button
                    class="btn-ghost py-0.5 text-[11px] text-rose-600"
                    :disabled="row.status === 'uninstalled'"
                    @click="askUninstall(row)"
                  >
                    卸载
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <template #footer>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span>第 {{ page }} / {{ pages }} 页</span>
          <div class="flex items-center gap-1.5">
            <button class="btn-outline py-1 text-[11px]" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
            <button class="btn-outline py-1 text-[11px]" :disabled="page >= pages || loading" @click="goPage(page + 1)">下一页</button>
          </div>
        </div>
      </template>
    </SectionCard>

    <SectionCard title="许可证" subtitle="查看授权状态、有效期与激活设备，并向服务端发起校验">
      <template #actions>
        <div class="flex items-center gap-1.5">
          <select v-model="licenseStatus" class="input w-[110px] py-1 text-[11px]" aria-label="许可证状态筛选">
            <option value="">全部</option>
            <option value="active">有效</option>
            <option value="expired">已过期</option>
            <option value="revoked">已撤销</option>
          </select>
          <button class="btn-ghost py-1 text-[11px]" :disabled="licenseLoading" @click="loadLicenses">刷新</button>
        </div>
      </template>

      <div v-if="licenseError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1 truncate">{{ licenseError }}</span>
        <button class="shrink-0 font-medium" @click="loadLicenses">重试</button>
      </div>
      <div v-else-if="licenseLoading && !licenses.length" class="py-10 text-center text-[12px] text-ink-400">许可证加载中…</div>
      <div v-else-if="!licenses.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
        暂无许可证，购买付费应用或开通试用后会在此展示
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[820px]">
          <thead class="border-b border-ink-100 bg-ink-50/60">
            <tr>
              <th class="th">应用</th>
              <th class="th">密钥提示</th>
              <th class="th">类型</th>
              <th class="th">状态</th>
              <th class="th">到期</th>
              <th class="th text-right">激活</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in licenses" :key="row.id">
              <td class="td">
                <div class="font-medium text-ink-800">{{ row.listing_code }}</div>
                <div class="text-[11px] text-ink-400">购买单 {{ row.purchase_id || '—' }}</div>
              </td>
              <td class="td font-mono text-[11px]">{{ row.key_hint || '—' }}</td>
              <td class="td">{{ licenseTypeLabel(row.type) }}</td>
              <td class="td">
                <span class="tag" :class="licenseClass(row.effective_status || row.status)">
                  {{ licenseLabel(row.effective_status || row.status) }}
                </span>
              </td>
              <td class="td text-[11px] text-ink-500">
                {{ fmtDate(row.expires_at) }}
                <span v-if="row.remaining_days !== null && row.remaining_days !== undefined" class="text-ink-400">
                  （剩 {{ row.remaining_days }} 天）
                </span>
              </td>
              <td class="td text-right">{{ fmtNum(row.activation_count) }} / {{ fmtNum(row.max_activations) }}</td>
              <td class="td">
                <div class="flex flex-wrap justify-end gap-1">
                  <button class="btn-ghost py-0.5 text-[11px]" @click="verifyLicense(row)">校验</button>
                  <button class="btn-ghost py-0.5 text-[11px]" @click="openActivate(row)">激活设备</button>
                  <button class="btn-ghost py-0.5 text-[11px]" @click="viewDevices(row)">设备</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <template #footer>
        <span>许可证密钥仅展示提示位，完整密钥不会在前端回显</span>
      </template>
    </SectionCard>

    <Modal :show="configOpen" title="安装配置" width="560px" @close="closeConfig">
      <div v-if="configTarget" class="space-y-3">
        <div class="text-[12px] text-ink-500">
          {{ configTarget.listing?.name }} · {{ configTarget.version?.version || '未知版本' }}
        </div>
        <textarea
          v-model="configText"
          class="input min-h-[180px] font-mono text-[11px]"
          placeholder="{}"
        ></textarea>
        <p class="text-[11px] text-ink-400">配置以 JSON 对象整体替换，保存后立即生效。</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeConfig">取消</button>
          <button class="btn-primary" :disabled="configSaving" @click="saveConfig">
            {{ configSaving ? '保存中…' : '保存配置' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="upgradeOpen" title="升级检查" width="600px" @close="closeUpgrade">
      <div v-if="upgradeTarget" class="space-y-3">
        <div class="rounded-control bg-ink-50/60 px-3 py-2 text-[12px]">
          <span class="font-medium text-ink-800">{{ upgradeTarget.listing?.name }}</span>
          <span class="text-ink-400"> · 当前 {{ upgradeTarget.version?.version || '—' }}</span>
        </div>
        <div v-if="upgradeLoading" class="py-6 text-center text-[12px] text-ink-400">正在检查升级…</div>
        <div v-else-if="upgradeError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ upgradeError }}
        </div>
        <template v-else-if="upgradeResult">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tag" :class="upgradeResult.upgrade_available ? 'bg-emerald-50 text-emerald-600' : ''">
              {{ upgradeResult.upgrade_available ? '可升级' : '无需升级' }}
            </span>
            <span v-if="upgradeResult.breaking" class="tag bg-rose-50 text-rose-600">含破坏性变更</span>
            <span class="text-[12px] text-ink-500">
              平台 {{ upgradeResult.platform_version || '默认' }}
            </span>
          </div>
          <div v-if="upgradeResult.reason" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
            {{ upgradeResult.reason }}
          </div>
          <div v-if="upgradeResult.latest" class="rounded-control border border-ink-100 px-3 py-2 text-[12px]">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-ink-800">目标版本 {{ upgradeResult.latest.version }}</span>
              <span class="text-ink-400">平台 ≥ {{ upgradeResult.latest.min_platform_version }}</span>
              <span class="ml-auto text-ink-400">{{ fmtDate(upgradeResult.latest.published_at) }}</span>
            </div>
            <p v-if="upgradeResult.latest.changelog" class="mt-1 whitespace-pre-line text-[11px] leading-relaxed text-ink-500">
              {{ upgradeResult.latest.changelog }}
            </p>
          </div>
          <div v-if="(upgradeResult.changes || []).length">
            <div class="mb-1 text-[12px] font-medium text-ink-700">途经版本变更</div>
            <div class="max-h-48 space-y-1 overflow-y-auto">
              <div
                v-for="change in upgradeResult.changes"
                :key="change.version"
                class="rounded-control bg-ink-50/60 px-2 py-1.5 text-[11px]"
              >
                <div class="flex items-center gap-2">
                  <span class="font-mono text-ink-700">{{ change.version }}</span>
                  <span v-if="change.breaking" class="tag bg-rose-50 text-rose-600">破坏性</span>
                  <span class="ml-auto text-ink-400">{{ fmtDate(change.published_at) }}</span>
                </div>
                <p class="mt-0.5 whitespace-pre-line text-ink-500">{{ change.changelog || '无变更说明' }}</p>
              </div>
            </div>
          </div>
        </template>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeUpgrade">关闭</button>
          <button
            class="btn-primary"
            :disabled="!upgradeResult?.upgrade_available || upgradeSaving"
            @click="doUpgrade"
          >
            {{ upgradeSaving ? '升级中…' : '确认升级' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="verifyOpen" title="许可证校验" width="520px" @close="closeVerify">
      <div class="space-y-3">
        <div v-if="verifyLoading" class="py-6 text-center text-[12px] text-ink-400">校验中…</div>
        <div v-else-if="verifyError" class="rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
          {{ verifyError }}
        </div>
        <template v-else-if="verifyResult">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tag" :class="verifyResult.valid ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
              {{ verifyResult.valid ? '校验通过' : '校验未通过' }}
            </span>
            <span v-if="verifyResult.checked_at" class="text-[11px] text-ink-400">校验时间 {{ fmtDate(verifyResult.checked_at, true) }}</span>
          </div>
          <ul v-if="(verifyResult.reasons || []).length" class="space-y-1">
            <li v-for="(reason, index) in verifyResult.reasons" :key="index" class="rounded-control bg-rose-50 px-2 py-1 text-[11px] text-rose-600">
              {{ reason }}
            </li>
          </ul>
          <div v-if="verifyResult.license" class="grid grid-cols-2 gap-x-3 gap-y-1.5 rounded-control bg-ink-50/60 px-3 py-2 text-[12px]">
            <div class="text-ink-400">状态</div>
            <div class="text-ink-700">{{ licenseLabel(verifyResult.license.status) }}</div>
            <div class="text-ink-400">到期时间</div>
            <div class="text-ink-700">{{ fmtDate(verifyResult.license.expires_at) }}</div>
            <div class="text-ink-400">剩余天数</div>
            <div class="text-ink-700">{{ verifyResult.license.remaining_days ?? '不限' }}</div>
            <div class="text-ink-400">激活设备</div>
            <div class="text-ink-700">{{ fmtNum(verifyResult.license.activation_count) }}</div>
          </div>
        </template>
        <div class="flex justify-end">
          <button class="btn-ghost" @click="closeVerify">关闭</button>
        </div>
      </div>
    </Modal>

    <Modal :show="activateOpen" title="激活许可证设备" width="460px" @close="closeActivate">
      <div class="space-y-3">
        <div class="text-[12px] text-ink-500">
          {{ activateTarget?.listing_code }} · 当前激活 {{ fmtNum(activateTarget?.activation_count) }} / {{ fmtNum(activateTarget?.max_activations) }}
        </div>
        <label class="block text-[12px] text-ink-500">
          设备标识
          <input v-model="activateDeviceId" class="input mt-1" placeholder="例如 work-pc-001" />
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeActivate">取消</button>
          <button class="btn-primary" :disabled="activateSaving" @click="submitActivate">
            {{ activateSaving ? '激活中…' : '确认激活' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="devicesOpen" title="激活设备" width="520px" @close="devicesOpen = false">
      <div class="space-y-2">
        <div v-if="!(devicesTarget?.devices || []).length" class="rounded-control border border-dashed border-ink-200 py-6 text-center text-[12px] text-ink-400">
          该许可证尚未激活任何设备
        </div>
        <div v-else class="divide-y divide-ink-50">
          <div v-for="(device, index) in devicesTarget.devices" :key="index" class="flex flex-wrap items-center gap-2 py-1.5 text-[12px]">
            <span class="min-w-0 flex-1 truncate font-mono text-ink-700">{{ device.device_id || device.id || '未知设备' }}</span>
            <span class="text-[11px] text-ink-400">{{ fmtDate(device.activated_at || device.last_seen_at, true) }}</span>
            <button class="btn-ghost py-0.5 text-[11px] text-rose-600" @click="deactivateDevice(device)">
              停用
            </button>
          </div>
        </div>
        <div class="flex justify-end">
          <button class="btn-ghost" @click="devicesOpen = false">关闭</button>
        </div>
      </div>
    </Modal>

    <Modal :show="confirmOpen" :title="confirmTitle" width="440px" @close="closeConfirm">
      <div class="space-y-3">
        <p class="text-[12px] leading-relaxed text-ink-600">{{ confirmText }}</p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeConfirm">取消</button>
          <button class="btn-danger" :disabled="confirmBusy" @click="runConfirm">
            {{ confirmBusy ? '处理中…' : confirmLabel }}
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { formatDate, formatNumber } from '../../composables/useDomainResource'
import { useDebounce } from '../../composables/useDomainResource'
import SectionCard from '../../components/platform/SectionCard.vue'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['go', 'changed'])

const api = apiFor('marketplace')
const app = useAppStore()

const { value: q, debounced: debouncedQ } = useDebounce(320)

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const loading = ref(false)
const error = ref('')
const status = ref('')
const lastLoadedAt = ref(null)
const summaryItems = ref([])

const licenses = ref([])
const licenseTotal = ref(0)
const licenseStatus = ref('')
const licenseLoading = ref(false)
const licenseError = ref('')

const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))
const summaryCounts = computed(() => {
  const out = { installed: 0, disabled: 0, uninstalled: 0, autoUpdate: 0 }
  for (const row of summaryItems.value) {
    if (row.status === 'installed') out.installed += 1
    else if (row.status === 'disabled') out.disabled += 1
    else if (row.status === 'uninstalled') out.uninstalled += 1
    if (row.auto_update) out.autoUpdate += 1
  }
  return out
})

const fmtNum = (value) => formatNumber(value)
const fmtDate = (value, withTime = false) => formatDate(value, withTime)

const configOpen = ref(false)
const configTarget = ref(null)
const configText = ref('')
const configSaving = ref(false)

const upgradeOpen = ref(false)
const upgradeTarget = ref(null)
const upgradeResult = ref(null)
const upgradeLoading = ref(false)
const upgradeError = ref('')
const upgradeSaving = ref(false)

const verifyOpen = ref(false)
const verifyLoading = ref(false)
const verifyError = ref('')
const verifyResult = ref(null)

const activateOpen = ref(false)
const activateTarget = ref(null)
const activateDeviceId = ref('')
const activateSaving = ref(false)

const devicesOpen = ref(false)
const devicesTarget = ref(null)

const confirmOpen = ref(false)
const confirmTitle = ref('')
const confirmText = ref('')
const confirmLabel = ref('确认')
const confirmBusy = ref(false)
const confirmAction = ref(null)

function installLabel(value) {
  const map = { installed: '已启用', disabled: '已停用', uninstalled: '已卸载' }
  return map[value] || value || '未知'
}

function installClass(value) {
  const map = {
    installed: 'bg-emerald-50 text-emerald-600',
    disabled: 'bg-amber-50 text-amber-600',
    uninstalled: 'bg-ink-100 text-ink-500',
  }
  return map[value] || ''
}

function licenseLabel(value) {
  const map = { active: '有效', expired: '已过期', revoked: '已撤销' }
  return map[value] || value || '未知'
}

function licenseClass(value) {
  const map = {
    active: 'bg-emerald-50 text-emerald-600',
    expired: 'bg-amber-50 text-amber-600',
    revoked: 'bg-rose-50 text-rose-600',
  }
  return map[value] || ''
}

function licenseTypeLabel(value) {
  const map = { perpetual: '永久', subscription: '订阅', trial: '试用' }
  return map[value] || value || '—'
}

async function loadInstalls() {
  if (!api) {
    error.value = '应用市场接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await api.list('installs/', {
      page: page.value,
      page_size: pageSize.value,
      q: debouncedQ.value.trim() || undefined,
      status: status.value || undefined,
    })
    items.value = data.items || []
    total.value = Number(data.count) || 0
    page.value = Number(data.page) || page.value
    lastLoadedAt.value = new Date()
  } catch (e) {
    items.value = []
    total.value = 0
    error.value = e?.message || '安装记录加载失败'
    app.toastMsg(error.value, 'error')
  } finally {
    loading.value = false
  }
}

async function loadSummary() {
  try {
    const data = await api.list('installs/', { page: 1, page_size: 100 })
    summaryItems.value = data.items || []
  } catch (e) {
    summaryItems.value = []
  }
}

async function loadLicenses() {
  licenseLoading.value = true
  licenseError.value = ''
  try {
    const data = await api.list('licenses/', {
      page: 1,
      page_size: 100,
      status: licenseStatus.value || undefined,
    })
    licenses.value = data.items || []
    licenseTotal.value = Number(data.count) || 0
  } catch (e) {
    licenses.value = []
    licenseTotal.value = 0
    licenseError.value = e?.message || '许可证加载失败'
    app.toastMsg(licenseError.value, 'error')
  } finally {
    licenseLoading.value = false
  }
}

function resetFilters() {
  q.value = ''
  debouncedQ.value = ''
  status.value = ''
  page.value = 1
  loadInstalls()
}

function goPage(next) {
  const target = Math.min(Math.max(1, Number(next) || 1), pages.value)
  if (target === page.value) return
  page.value = target
  loadInstalls()
}

async function refreshAfterChange() {
  await Promise.all([loadInstalls(), loadSummary(), loadLicenses()])
  emit('changed')
}

function openConfig(row) {
  configTarget.value = row
  configText.value = JSON.stringify(row.config || {}, null, 2)
  configOpen.value = true
}

function closeConfig() {
  configOpen.value = false
  configTarget.value = null
  configSaving.value = false
}

async function saveConfig() {
  if (!configTarget.value) return
  let parsed
  try {
    parsed = JSON.parse(configText.value || '{}')
  } catch (e) {
    app.toastMsg('配置不是合法 JSON', 'error')
    return
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    app.toastMsg('配置必须是 JSON 对象', 'error')
    return
  }
  configSaving.value = true
  try {
    await api.post(`installs/${configTarget.value.id}/config/`, { config: parsed })
    app.toastMsg('配置已保存', 'success')
    closeConfig()
    await refreshAfterChange()
  } catch (e) {
    app.toastMsg(e?.message || '配置保存失败', 'error')
  } finally {
    configSaving.value = false
  }
}

async function openUpgrade(row) {
  upgradeTarget.value = row
  upgradeOpen.value = true
  upgradeResult.value = null
  upgradeError.value = ''
  upgradeLoading.value = true
  try {
    const current = row.version?.version || '0.0.0'
    upgradeResult.value = await api.get(
      `listings/${row.listing.id}/upgrade-check/?current_version=${encodeURIComponent(current)}`
    )
  } catch (e) {
    upgradeError.value = e?.message || '升级检查失败'
    app.toastMsg(upgradeError.value, 'error')
  } finally {
    upgradeLoading.value = false
  }
}

function closeUpgrade() {
  upgradeOpen.value = false
  upgradeTarget.value = null
  upgradeResult.value = null
  upgradeError.value = ''
  upgradeSaving.value = false
}

async function doUpgrade() {
  if (!upgradeTarget.value || !upgradeResult.value?.latest?.id) return
  upgradeSaving.value = true
  try {
    const result = await api.post(`installs/${upgradeTarget.value.id}/upgrade/`, {
      version_id: upgradeResult.value.latest.id,
    })
    app.toastMsg(`已升级到 ${result?.to || upgradeResult.value.latest.version}`, 'success')
    closeUpgrade()
    await refreshAfterChange()
  } catch (e) {
    app.toastMsg(e?.message || '升级失败', 'error')
  } finally {
    upgradeSaving.value = false
  }
}

function toggleInstall(row, enable) {
  confirmTitle.value = enable ? '启用应用' : '停用应用'
  confirmText.value = enable ? '启用后应用恢复可用。' : '停用后应用不可用，但仍计入安装量。'
  confirmLabel.value = enable ? '确认启用' : '确认停用'
  confirmAction.value = async () => {
    await api.post(`installs/${row.id}/${enable ? 'enable' : 'disable'}/`)
    app.toastMsg(enable ? '已启用' : '已停用', 'success')
    await refreshAfterChange()
  }
  confirmOpen.value = true
}

function askUninstall(row) {
  confirmTitle.value = '卸载应用'
  confirmText.value = `确认卸载 ${row.listing?.name || '该应用'}？安装记录会保留以便重装。`
  confirmLabel.value = '确认卸载'
  confirmAction.value = async () => {
    await api.post(`installs/${row.id}/uninstall/`)
    app.toastMsg('已卸载', 'success')
    await refreshAfterChange()
  }
  confirmOpen.value = true
}

async function runConfirm() {
  if (typeof confirmAction.value !== 'function') return
  confirmBusy.value = true
  try {
    await confirmAction.value()
    closeConfirm()
  } catch (e) {
    app.toastMsg(e?.message || '操作失败', 'error')
  } finally {
    confirmBusy.value = false
  }
}

function closeConfirm() {
  confirmOpen.value = false
  confirmBusy.value = false
  confirmAction.value = null
}

async function verifyLicense(row) {
  verifyOpen.value = true
  verifyLoading.value = true
  verifyResult.value = null
  verifyError.value = ''
  try {
    verifyResult.value = await api.post('licenses/verify/', { license_id: row.id })
    await loadLicenses()
  } catch (e) {
    verifyError.value = e?.message || '许可证校验失败'
    app.toastMsg(verifyError.value, 'error')
  } finally {
    verifyLoading.value = false
  }
}

function closeVerify() {
  verifyOpen.value = false
  verifyResult.value = null
  verifyError.value = ''
}

function openActivate(row) {
  activateTarget.value = row
  activateDeviceId.value = ''
  activateOpen.value = true
}

function closeActivate() {
  activateOpen.value = false
  activateTarget.value = null
  activateDeviceId.value = ''
  activateSaving.value = false
}

async function submitActivate() {
  if (!activateTarget.value) return
  const deviceId = activateDeviceId.value.trim()
  if (!deviceId) {
    app.toastMsg('请输入设备标识', 'info')
    return
  }
  activateSaving.value = true
  try {
    await api.post(`licenses/${activateTarget.value.id}/activate/`, { device_id: deviceId })
    app.toastMsg('设备已激活', 'success')
    closeActivate()
    await loadLicenses()
  } catch (e) {
    app.toastMsg(e?.message || '激活失败', 'error')
  } finally {
    activateSaving.value = false
  }
}

function viewDevices(row) {
  devicesTarget.value = row
  devicesOpen.value = true
}

async function deactivateDevice(device) {
  if (!devicesTarget.value) return
  try {
    await api.post(`licenses/${devicesTarget.value.id}/deactivate/`, { device_id: device.device_id })
    app.toastMsg('设备已停用', 'success')
    const data = await api.list('licenses/', { page: 1, page_size: 100 })
    licenses.value = data.items || []
    const refreshed = licenses.value.find((row) => row.id === devicesTarget.value.id)
    if (refreshed) devicesTarget.value = refreshed
  } catch (e) {
    app.toastMsg(e?.message || '停用设备失败', 'error')
  }
}

watch([debouncedQ, status], () => {
  page.value = 1
  loadInstalls()
})

watch(licenseStatus, () => loadLicenses())

watch(
  () => props.refreshKey,
  () => {
    loadInstalls()
    loadSummary()
    loadLicenses()
  }
)

onMounted(() => {
  loadInstalls()
  loadSummary()
  loadLicenses()
})
</script>