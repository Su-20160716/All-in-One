<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="text-[12px] text-ink-500">统计窗口</span>
        <button
          v-for="d in DAY_OPTIONS"
          :key="d"
          class="rounded-pill px-2.5 py-1 text-[12px]"
          :class="days === d ? 'bg-ink-700 text-white' : 'border border-ink-200 bg-white text-ink-500 hover:bg-ink-50'"
          @click="days = d"
        >
          {{ d }} 天
        </button>
        <span class="tag">安装 / 分类 / 评分 / 收入</span>
      </div>
      <div class="flex items-center gap-1.5">
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'listings')">应用目录</button>
        <button class="btn-outline py-1 text-[12px]" :disabled="loading" @click="loadAll">
          {{ loading ? '刷新中…' : '刷新分析' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
      <span class="min-w-0 flex-1">{{ error }}</span>
      <button class="shrink-0 font-medium" @click="loadAll">重试</button>
    </div>
    <div v-else-if="notice" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      {{ notice }}
    </div>

    <StatsGrid :items="kpis" :loading="loading" :skeleton-count="5" />

    <SectionCard title="安装趋势" :subtitle="`近 ${days} 天每日安装、卸载、净增与累计有效安装`">
      <template #actions>
        <span class="tag">安装 {{ fmtNum(installTrend?.total_installs) }}</span>
        <span class="tag">卸载 {{ fmtNum(installTrend?.total_uninstalls) }}</span>
        <span class="tag" :class="Number(installTrend?.net) >= 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
          净增 {{ fmtNum(installTrend?.net) }}
        </span>
      </template>
      <div v-if="sectionErrors.installs" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
        安装趋势暂不可用：{{ sectionErrors.installs }}
      </div>
      <div v-else-if="loading && !trendLabels.length" class="py-14 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="!trendLabels.length" class="rounded-control border border-dashed border-ink-200 py-14 text-center text-[12px] text-ink-400">
        窗口内暂无安装记录
      </div>
      <div v-else class="grid gap-3 lg:grid-cols-2">
        <LineChart
          :series="installSeries"
          :labels="trendLabels"
          :height="230"
          :format="fmtNum"
          aria-label="每日安装与卸载"
        />
        <LineChart
          :series="cumulativeSeries"
          :labels="trendLabels"
          :height="230"
          :show-legend="false"
          :format="fmtNum"
          aria-label="累计有效安装"
        />
      </div>
    </SectionCard>

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="分类分布" :subtitle="`${fmtNum(categoryStats?.total_categories)} 个分类的应用、安装与平均评分`">
        <template #actions>
          <span class="tag">前 10 个分类</span>
        </template>
        <div v-if="sectionErrors.categories" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
          分类分布暂不可用：{{ sectionErrors.categories }}
        </div>
        <div v-else-if="loading && !categoryRows.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!categoryRows.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
          暂无分类数据
        </div>
        <template v-else>
          <div class="flex flex-wrap items-center gap-4">
            <DonutChart
              :data="categoryChart"
              :size="160"
              center-label="应用"
              legend-position="right"
              :format="fmtNum"
            />
            <div class="min-w-0 flex-1">
              <BarChart :data="categoryInstallChart" horizontal :height="160" :format="fmtNum" empty-text="暂无安装数据" />
            </div>
          </div>
          <div class="mt-3 overflow-x-auto">
            <table class="w-full min-w-[420px]">
              <thead>
                <tr>
                  <th class="th">分类</th>
                  <th class="th text-right">应用</th>
                  <th class="th text-right">安装</th>
                  <th class="th text-right">平均评分</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-ink-50">
                <tr v-for="row in categoryRows.slice(0, 10)" :key="row.category_id || 'none'">
                  <td class="td">{{ row.name }}</td>
                  <td class="td text-right">{{ fmtNum(row.listings) }}</td>
                  <td class="td text-right">{{ fmtNum(row.installs) }}</td>
                  <td class="td text-right">{{ fmtRating(row.avg_rating) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="评分分布" :subtitle="`已发布评价 ${fmtNum(ratingStats?.overall?.total)} 条，平均 ${fmtRating(ratingStats?.overall?.average)} 分`">
        <div v-if="sectionErrors.ratings" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
          评分分布暂不可用：{{ sectionErrors.ratings }}
        </div>
        <div v-else-if="loading && !ratingBars.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <template v-else>
          <BarChart :data="ratingBars" :height="180" :format="fmtNum" empty-text="暂无评分数据" />
          <div class="mt-2 divide-y divide-ink-50">
            <div
              v-for="row in ratingStats?.top_rated || []"
              :key="row.listing_id"
              class="flex items-center gap-2 py-1.5 text-[12px]"
            >
              <span class="min-w-0 flex-1 truncate text-ink-700">{{ row.name }}</span>
              <span class="shrink-0 text-ink-500">{{ row.publisher }}</span>
              <span class="w-14 shrink-0 text-right text-amber-600">{{ fmtRating(row.rating) }} 分</span>
              <span class="w-14 shrink-0 text-right text-ink-400">{{ fmtNum(row.rating_count) }} 条</span>
            </div>
            <div v-if="!(ratingStats?.top_rated || []).length" class="py-3 text-center text-[12px] text-ink-400">
              暂无高分应用
            </div>
          </div>
        </template>
      </SectionCard>
    </div>

    <SectionCard title="收入汇总" subtitle="成交、退款冲减、平台抽成与发布者净收入（仅管理员可见）">
      <template #actions>
        <span v-if="revenueStats" class="tag">订单 {{ fmtNum(revenueStats.orders) }}</span>
        <span v-if="revenueStats" class="tag">平台抽成 {{ fmtPct(revenueStats.platform_share_pct) }}</span>
      </template>
      <div v-if="sectionErrors.revenue" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
        {{ sectionErrors.revenue }}
      </div>
      <div v-else-if="loading && !revenueStats" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="!revenueStats" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
        暂无收入数据
      </div>
      <template v-else>
        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">成交流水</div>
            <div class="text-[16px] font-semibold text-ink-900">{{ fmtMoney(revenueStats.gross_cny) }}</div>
            <div class="text-[11px] text-ink-400">退款 {{ fmtMoney(revenueStats.refund_cny) }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">净成交</div>
            <div class="text-[16px] font-semibold text-ink-900">{{ fmtMoney(revenueStats.net_cny) }}</div>
            <div class="text-[11px] text-ink-400">退款订单 {{ fmtNum(revenueStats.refunded_orders) }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">发布者净收入</div>
            <div class="text-[16px] font-semibold text-emerald-600">{{ fmtMoney(revenueStats.publisher_net_cny) }}</div>
            <div class="text-[11px] text-ink-400">平台抽成 {{ fmtMoney(revenueStats.platform_fee_cny) }}</div>
          </div>
          <div class="rounded-control bg-ink-50/60 px-3 py-2">
            <div class="text-[11px] text-ink-400">发布者</div>
            <div class="text-[16px] font-semibold text-ink-900">{{ fmtNum(revenueStats.publishers) }}</div>
            <div class="text-[11px] text-ink-400">月度走势按订单月份</div>
          </div>
        </div>

        <div class="mt-3 grid gap-3 lg:grid-cols-2">
          <div>
            <div class="mb-1 text-[12px] font-medium text-ink-600">月度成交走势</div>
            <LineChart
              :series="revenueSeries"
              :labels="revenueLabels"
              :height="190"
              :format="fmtMoneyShort"
              empty-text="暂无月度收入"
              aria-label="月度成交走势"
            />
          </div>
          <div class="min-w-0">
            <div class="mb-1 text-[12px] font-medium text-ink-600">发布者收入排行</div>
            <div v-if="!(revenueStats.top_publishers || []).length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
              暂无成交发布者
            </div>
            <div v-else class="max-h-[220px] overflow-y-auto">
              <table class="w-full">
                <thead>
                  <tr>
                    <th class="th">发布者</th>
                    <th class="th text-right">订单</th>
                    <th class="th text-right">净成交</th>
                    <th class="th text-right">净收入</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-ink-50">
                  <tr v-for="row in revenueStats.top_publishers" :key="row.publisher_id">
                    <td class="td max-w-[150px] truncate">{{ row.publisher }}</td>
                    <td class="td text-right">{{ fmtNum(row.orders) }}</td>
                    <td class="td text-right">{{ fmtMoney(row.net_cny) }}</td>
                    <td class="td text-right">{{ fmtMoney(row.publisher_net_cny) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </template>
    </SectionCard>

    <SectionCard title="合集管理" subtitle="创建合集、维护条目顺序、发布后对市场用户可见">
      <template #actions>
        <div class="flex flex-wrap items-center gap-1.5">
          <select v-model="collectionScope" class="input w-[110px] py-1 text-[11px]" aria-label="合集范围">
            <option value="mine">我的合集</option>
            <option v-if="userStore.isAdmin" value="all">全部合集</option>
          </select>
          <button class="btn-ghost py-1 text-[11px]" :disabled="collectionLoading" @click="loadCollections">刷新</button>
          <button class="btn-primary py-1 text-[11px]" @click="openCollectionCreate">新建合集</button>
        </div>
      </template>

      <div v-if="collectionError" class="flex items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600">
        <span class="min-w-0 flex-1 truncate">{{ collectionError }}</span>
        <button class="shrink-0 font-medium" @click="loadCollections">重试</button>
      </div>
      <div v-else-if="collectionLoading && !collections.length" class="py-10 text-center text-[12px] text-ink-400">合集加载中…</div>
      <div v-else-if="!collections.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
        暂无合集，创建后可将多个应用组织为主题清单
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full min-w-[760px]">
          <thead class="border-b border-ink-100 bg-ink-50/60">
            <tr>
              <th class="th">合集</th>
              <th class="th">状态</th>
              <th class="th text-right">条目</th>
              <th class="th text-right">排序</th>
              <th class="th">发布时间</th>
              <th class="th text-right">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-50">
            <tr v-for="row in collections" :key="row.id" :class="selectedCollection?.id === row.id ? 'bg-brand-50/40' : ''">
              <td class="td">
                <button class="block max-w-[260px] truncate text-left font-medium text-ink-800 hover:text-brand-600" @click="openCollection(row)">
                  {{ row.title }}
                </button>
                <div class="max-w-[260px] truncate text-[11px] text-ink-400">{{ row.slug }}</div>
              </td>
              <td class="td">
                <span class="tag" :class="collectionClass(row.status)">{{ collectionLabel(row.status) }}</span>
                <span v-if="row.featured" class="ml-1 tag bg-amber-50 text-amber-700">推荐</span>
              </td>
              <td class="td text-right">{{ fmtNum(row.item_count) }}</td>
              <td class="td text-right">{{ fmtNum(row.order) }}</td>
              <td class="td text-[11px] text-ink-500">{{ fmtDate(row.published_at) }}</td>
              <td class="td">
                <div class="flex flex-wrap justify-end gap-1">
                  <button class="btn-ghost py-0.5 text-[11px]" @click="openCollection(row)">条目</button>
                  <button
                    v-if="row.status !== 'published'"
                    class="btn-ghost py-0.5 text-[11px] text-emerald-600"
                    @click="publishCollection(row)"
                  >
                    发布
                  </button>
                  <button class="btn-ghost py-0.5 text-[11px] text-rose-600" @click="askDeleteCollection(row)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="selectedCollection" class="mt-3 rounded-control border border-brand-200 bg-brand-50/30 p-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-semibold text-ink-800">{{ selectedCollection.title }}</span>
          <span class="tag" :class="collectionClass(selectedCollection.status)">{{ collectionLabel(selectedCollection.status) }}</span>
          <span class="tag">{{ (selectedCollection.items || []).length }} 个条目</span>
          <button class="btn-ghost py-0.5 text-[11px]" :disabled="collectionDetailLoading" @click="openCollection(selectedCollection)">
            刷新条目
          </button>
          <button class="btn-ghost ml-auto py-0.5 text-[11px]" @click="selectedCollection = null">收起</button>
        </div>

        <div v-if="collectionDetailError" class="mt-2 rounded-control bg-rose-50 px-2 py-1.5 text-[11px] text-rose-600">
          {{ collectionDetailError }}
        </div>
        <div v-else-if="collectionDetailLoading" class="py-4 text-center text-[12px] text-ink-400">条目加载中…</div>
        <div v-else-if="!(selectedCollection.items || []).length" class="mt-2 rounded-control border border-dashed border-ink-200 py-4 text-center text-[12px] text-ink-400">
          合集还没有条目，从下方添加已上架应用
        </div>
        <div v-else class="mt-2 divide-y divide-ink-100">
          <div
            v-for="(item, index) in selectedCollection.items"
            :key="item.id"
            class="flex flex-wrap items-center gap-2 py-1.5 text-[12px]"
          >
            <span class="w-5 shrink-0 text-ink-400">{{ index + 1 }}</span>
            <span class="min-w-0 flex-1 truncate text-ink-700">{{ item.listing?.name || `应用 ${item.listing_id}` }}</span>
            <span class="shrink-0 text-[11px] text-ink-400">{{ item.listing?.code }}</span>
            <span class="w-16 shrink-0 text-right text-[11px] text-ink-400">#{{ item.order }}</span>
            <button class="btn-ghost px-1 py-0.5 text-[11px]" :disabled="index === 0 || reorderBusy" @click="moveItem(index, -1)">上移</button>
            <button
              class="btn-ghost px-1 py-0.5 text-[11px]"
              :disabled="index === selectedCollection.items.length - 1 || reorderBusy"
              @click="moveItem(index, 1)"
            >
              下移
            </button>
            <button class="btn-ghost px-1 py-0.5 text-[11px] text-rose-600" @click="removeItem(item)">移除</button>
          </div>
        </div>

        <div class="mt-2 flex flex-wrap items-center gap-1.5">
          <select v-model="addListingId" class="input w-full sm:w-[300px] py-1 text-[11px]" aria-label="选择要加入合集的应用">
            <option value="">选择已上架应用</option>
            <option v-for="row in publishedListings" :key="row.id" :value="String(row.id)">
              {{ row.name }}（{{ row.code }}）
            </option>
          </select>
          <button class="btn-primary py-1 text-[11px]" :disabled="!addListingId || addItemBusy" @click="addItem">
            {{ addItemBusy ? '添加中…' : '加入合集' }}
          </button>
          <span v-if="!publishedListings.length" class="text-[11px] text-ink-400">暂无可选应用</span>
        </div>
      </div>
    </SectionCard>

    <Modal :show="collectionCreateOpen" title="新建合集" width="560px" @close="closeCollectionCreate">
      <div class="space-y-2">
        <label class="block text-[12px] text-ink-500">
          合集标题
          <input v-model="collectionForm.title" class="input mt-1" maxlength="200" placeholder="例如 数据分析精选" />
        </label>
        <label class="block text-[12px] text-ink-500">
          标识（可选）
          <input v-model="collectionForm.slug" class="input mt-1" placeholder="留空自动生成" />
        </label>
        <label class="block text-[12px] text-ink-500">
          描述
          <textarea v-model="collectionForm.description" class="input mt-1 min-h-[64px]"></textarea>
        </label>
        <div class="grid gap-2 sm:grid-cols-2">
          <label class="block text-[12px] text-ink-500">
            封面地址（可选）
            <input v-model="collectionForm.cover" class="input mt-1" placeholder="https://" />
          </label>
          <label class="block text-[12px] text-ink-500">
            排序值
            <input v-model.number="collectionForm.order" type="number" min="0" class="input mt-1" />
          </label>
        </div>
        <label class="flex items-center gap-2 text-[12px] text-ink-600">
          <input v-model="collectionForm.featured" type="checkbox" class="h-3.5 w-3.5" />
          标记为推荐合集
        </label>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="closeCollectionCreate">取消</button>
          <button class="btn-primary" :disabled="collectionSaving" @click="createCollection">
            {{ collectionSaving ? '创建中…' : '创建合集' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal :show="deleteOpen" title="删除合集" width="440px" @close="deleteOpen = false">
      <div class="space-y-3">
        <p class="text-[12px] leading-relaxed text-ink-600">
          确认删除合集「{{ deleteTarget?.title }}」？条目会一并删除，但不影响应用本身。
        </p>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="deleteOpen = false">取消</button>
          <button class="btn-danger" :disabled="deleteBusy" @click="removeCollection">
            {{ deleteBusy ? '删除中…' : '确认删除' }}
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
import { useUserStore } from '../../stores/user'
import { formatDate, formatMoney, formatNumber } from '../../composables/useDomainResource'
import SectionCard from '../../components/platform/SectionCard.vue'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import BarChart from '../../components/platform/BarChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import LineChart from '../../components/platform/LineChart.vue'
import Modal from '../../components/Modal.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])

const api = apiFor('marketplace')
const app = useAppStore()
const userStore = useUserStore()

const DAY_OPTIONS = [7, 30, 90]
const STAR_KEYS = ['5', '4', '3', '2', '1']

const days = ref(30)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const sectionErrors = ref({})
const installTrend = ref(null)
const categoryStats = ref(null)
const ratingStats = ref(null)
const revenueStats = ref(null)

const collections = ref([])
const collectionTotal = ref(0)
const collectionLoading = ref(false)
const collectionError = ref('')
const collectionScope = ref('mine')
const selectedCollection = ref(null)
const collectionDetailLoading = ref(false)
const collectionDetailError = ref('')
const publishedListings = ref([])
const addListingId = ref('')
const addItemBusy = ref(false)
const reorderBusy = ref(false)

const collectionCreateOpen = ref(false)
const collectionSaving = ref(false)
const collectionForm = reactive({ title: '', slug: '', description: '', cover: '', order: 0, featured: false })

const deleteOpen = ref(false)
const deleteTarget = ref(null)
const deleteBusy = ref(false)

const fmtNum = (value) => formatNumber(value)
const fmtDate = (value) => formatDate(value)
const fmtMoney = (value) => formatMoney(value)
const fmtMoneyShort = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(1)} 万`
  return n.toFixed(0)
}
const fmtPct = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(2)}%`
}
const fmtRating = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

const trendItems = computed(() => installTrend.value?.items || [])
const trendLabels = computed(() => trendItems.value.map((row) => String(row.date || '').slice(5)))
const installSeries = computed(() => [
  { name: '安装', color: '#4f46e5', data: trendItems.value.map((row) => Number(row.installs) || 0) },
  { name: '卸载', color: '#f43f5e', data: trendItems.value.map((row) => Number(row.uninstalls) || 0) },
])
const cumulativeSeries = computed(() => [
  { name: '累计有效安装', color: '#0d9488', area: true, data: trendItems.value.map((row) => Number(row.cumulative) || 0) },
])

const categoryRows = computed(() => categoryStats.value?.items || [])
const categoryChart = computed(() =>
  categoryRows.value.filter((row) => Number(row.listings) > 0).slice(0, 10)
    .map((row) => ({ label: row.name || '未命名', value: Number(row.listings) || 0 }))
)
const categoryInstallChart = computed(() =>
  categoryRows.value.filter((row) => Number(row.installs) > 0).slice(0, 10)
    .map((row) => ({ label: row.name || '未命名', value: Number(row.installs) || 0 }))
)

const ratingBars = computed(() => {
  const distribution = ratingStats.value?.overall?.distribution || {}
  return STAR_KEYS.map((star) => ({ label: `${star} 星`, value: Number(distribution[star]) || 0 }))
})

const revenueLabels = computed(() => (revenueStats.value?.by_month || []).map((row) => row.month))
const revenueSeries = computed(() => [
  {
    name: '成交额',
    color: '#4f46e5',
    data: (revenueStats.value?.by_month || []).map((row) => Number(row.gross_cny) || 0),
  },
  {
    name: '发布者净收入',
    color: '#0d9488',
    data: (revenueStats.value?.by_month || []).map((row) => Number(row.publisher_net_cny) || 0),
  },
])

const kpis = computed(() => {
  const installs = installTrend.value || {}
  const ratings = ratingStats.value?.overall || {}
  const revenue = revenueStats.value || {}
  return [
    {
      key: 'installs',
      label: '窗口安装',
      value: fmtNum(installs.total_installs),
      hint: `窗口 ${days.value} 天`,
      icon: '⇣',
    },
    {
      key: 'uninstalls',
      label: '窗口卸载',
      value: fmtNum(installs.total_uninstalls),
      hint: `净增 ${fmtNum(installs.net)}`,
      icon: '⇡',
    },
    {
      key: 'active',
      label: '累计有效安装',
      value: fmtNum(trendItems.value.length ? trendItems.value[trendItems.value.length - 1].cumulative : null),
      hint: '按自然日累计',
      icon: '◈',
    },
    {
      key: 'rating',
      label: '平均评分',
      value: fmtRating(ratings.average),
      unit: '分',
      hint: `已发布评价 ${fmtNum(ratings.total)} 条`,
      icon: '★',
    },
    {
      key: 'revenue',
      label: '净成交',
      value: sectionErrors.value.revenue ? '—' : fmtMoney(revenue.net_cny),
      hint: sectionErrors.value.revenue ? '仅管理员可查看' : `退款 ${fmtMoney(revenue.refund_cny)}`,
      icon: '¥',
    },
  ]
})

const collectionLabel = (value) => (value === 'published' ? '已发布' : value === 'draft' ? '草稿' : value || '未知')
const collectionClass = (value) => (value === 'published' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600')

function setSectionError(key, e) {
  sectionErrors.value[key] = e?.message || '加载失败'
}

async function loadInstalls() {
  try {
    installTrend.value = await api.get(`stats/installs/?days=${days.value}`)
    delete sectionErrors.value.installs
  } catch (e) {
    installTrend.value = null
    setSectionError('installs', e)
  }
}

async function loadCategories() {
  try {
    categoryStats.value = await api.get('stats/categories/')
    delete sectionErrors.value.categories
  } catch (e) {
    categoryStats.value = null
    setSectionError('categories', e)
  }
}

async function loadRatings() {
  try {
    ratingStats.value = await api.get('stats/ratings/?limit=10')
    delete sectionErrors.value.ratings
  } catch (e) {
    ratingStats.value = null
    setSectionError('ratings', e)
  }
}

async function loadRevenue() {
  try {
    revenueStats.value = await api.get('stats/revenue/')
    delete sectionErrors.value.revenue
  } catch (e) {
    revenueStats.value = null
    setSectionError('revenue', e)
  }
}

async function loadAll() {
  if (!api) {
    error.value = '应用市场接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  sectionErrors.value = {}
  const results = await Promise.allSettled([
    loadInstalls(),
    loadCategories(),
    loadRatings(),
    loadRevenue(),
  ])
  if (results.every((row) => row.status === 'rejected')) {
    error.value = results[0].reason?.message || '运营分析加载失败'
    app.toastMsg(error.value, 'error')
  } else if (Object.keys(sectionErrors.value).length) {
    notice.value = '部分统计接口不可用或权限不足，已按可用数据降级展示'
  }
  loading.value = false
}

async function loadCollections() {
  collectionLoading.value = true
  collectionError.value = ''
  try {
    const params = { page: 1, page_size: 50 }
    if (collectionScope.value === 'all' && userStore.isAdmin) params.all = 1
    else params.mine = 1
    const data = await api.list('collections/', params)
    collections.value = data.items || []
    collectionTotal.value = Number(data.count) || 0
    if (selectedCollection.value) {
      const still = collections.value.find((row) => row.id === selectedCollection.value.id)
      if (!still) selectedCollection.value = null
    }
  } catch (e) {
    collections.value = []
    collectionTotal.value = 0
    collectionError.value = e?.message || '合集加载失败'
    app.toastMsg(collectionError.value, 'error')
  } finally {
    collectionLoading.value = false
  }
}

async function loadPublishedListings() {
  try {
    const data = await api.list('listings/', { page: 1, page_size: 100, sort: 'installs' })
    publishedListings.value = data.items || []
  } catch (e) {
    publishedListings.value = []
  }
}

async function openCollection(row) {
  if (!row) return
  collectionDetailLoading.value = true
  collectionDetailError.value = ''
  try {
    selectedCollection.value = await api.get(`collections/${row.id}/`)
  } catch (e) {
    selectedCollection.value = row
    collectionDetailError.value = e?.message || '合集详情加载失败'
    app.toastMsg(collectionDetailError.value, 'error')
  } finally {
    collectionDetailLoading.value = false
  }
}

function openCollectionCreate() {
  collectionForm.title = ''
  collectionForm.slug = ''
  collectionForm.description = ''
  collectionForm.cover = ''
  collectionForm.order = 0
  collectionForm.featured = false
  collectionCreateOpen.value = true
}

function closeCollectionCreate() {
  collectionCreateOpen.value = false
  collectionSaving.value = false
}

async function createCollection() {
  const title = collectionForm.title.trim()
  if (!title) {
    app.toastMsg('请输入合集标题', 'info')
    return
  }
  collectionSaving.value = true
  try {
    await api.post('collections/', {
      title,
      slug: collectionForm.slug.trim() || undefined,
      description: collectionForm.description.trim(),
      cover: collectionForm.cover.trim(),
      order: Number(collectionForm.order) || 0,
      featured: Boolean(collectionForm.featured),
    })
    app.toastMsg('合集已创建为草稿', 'success')
    closeCollectionCreate()
    await loadCollections()
  } catch (e) {
    app.toastMsg(e?.message || '创建合集失败', 'error')
  } finally {
    collectionSaving.value = false
  }
}

async function publishCollection(row) {
  try {
    await api.post(`collections/${row.id}/publish/`)
    app.toastMsg('合集已发布', 'success')
    await loadCollections()
    if (selectedCollection.value?.id === row.id) await openCollection(row)
  } catch (e) {
    app.toastMsg(e?.message || '发布合集失败', 'error')
  }
}

function askDeleteCollection(row) {
  deleteTarget.value = row
  deleteOpen.value = true
}

async function removeCollection() {
  if (!deleteTarget.value) return
  deleteBusy.value = true
  try {
    await api.remove(`collections/${deleteTarget.value.id}/delete/`)
    app.toastMsg('合集已删除', 'success')
    if (selectedCollection.value?.id === deleteTarget.value.id) selectedCollection.value = null
    deleteOpen.value = false
    deleteTarget.value = null
    await loadCollections()
  } catch (e) {
    app.toastMsg(e?.message || '删除合集失败', 'error')
  } finally {
    deleteBusy.value = false
  }
}

async function addItem() {
  if (!selectedCollection.value || !addListingId.value) return
  addItemBusy.value = true
  try {
    const data = await api.post(`collections/${selectedCollection.value.id}/items/`, {
      listing_id: Number(addListingId.value),
    })
    selectedCollection.value = data
    addListingId.value = ''
    app.toastMsg(data?.created === false ? '应用已在合集中' : '已加入合集', 'success')
    await loadCollections()
  } catch (e) {
    app.toastMsg(e?.message || '加入合集失败', 'error')
  } finally {
    addItemBusy.value = false
  }
}

async function moveItem(index, delta) {
  const collection = selectedCollection.value
  if (!collection) return
  const list = [...(collection.items || [])]
  const target = index + delta
  if (target < 0 || target >= list.length) return
  const moved = list.splice(index, 1)[0]
  list.splice(target, 0, moved)
  reorderBusy.value = true
  try {
    await api.post(`collections/${collection.id}/items/reorder/`, {
      items: list.map((item) => item.id),
    })
    collection.items = list
    app.toastMsg('条目顺序已保存', 'success')
    await loadCollections()
  } catch (e) {
    app.toastMsg(e?.message || '排序失败', 'error')
  } finally {
    reorderBusy.value = false
  }
}

async function removeItem(item) {
  if (!selectedCollection.value || !item) return
  try {
    await api.remove(`collection-items/${item.id}/delete/`)
    app.toastMsg('条目已移除', 'success')
    selectedCollection.value.items = (selectedCollection.value.items || []).filter((row) => row.id !== item.id)
    await loadCollections()
  } catch (e) {
    app.toastMsg(e?.message || '移除条目失败', 'error')
  }
}

watch(days, () => {
  loadInstalls()
})

watch(collectionScope, () => loadCollections())

watch(
  () => props.refreshKey,
  () => {
    loadAll()
    loadCollections()
  }
)

onMounted(() => {
  loadAll()
  loadCollections()
  loadPublishedListings()
})
</script>