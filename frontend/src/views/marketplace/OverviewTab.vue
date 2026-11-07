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
        <span class="tag">{{ scopeLabel }}</span>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'listings')">浏览应用目录</button>
        <button class="btn-ghost py-1 text-[12px]" @click="emit('go', 'analytics')">运营分析</button>
        <button class="btn-outline py-1 text-[12px]" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '刷新总览' }}
        </button>
      </div>
    </div>

    <div
      v-if="error"
      class="flex flex-wrap items-center gap-3 rounded-control bg-rose-50 px-3 py-2 text-[12px] text-rose-600"
    >
      <span class="min-w-0 flex-1">{{ error }}</span>
      <button class="shrink-0 font-medium" @click="load">重试</button>
    </div>
    <div v-else-if="notice" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
      {{ notice }}
    </div>

    <StatsGrid :items="kpis" :loading="loading" :skeleton-count="5" gap="normal" />

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="分类分布" :subtitle="`共 ${fmtNum(categories.total_categories)} 个分类，按在架应用数统计`">
        <template #actions>
          <span class="tag">前 {{ categoryBars.length }} 个分类</span>
        </template>
        <div v-if="sectionErrors.categories" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
          分类分布暂不可用：{{ sectionErrors.categories }}
        </div>
        <div v-else-if="loading && !categoryBars.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!categoryBars.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
          暂无分类分布数据
        </div>
        <div v-else class="flex flex-wrap items-center gap-4">
          <DonutChart
            :data="categoryBars"
            :size="168"
            center-label="在架应用"
            legend-position="right"
            :format="fmtNum"
          />
          <div class="min-w-0 flex-1">
            <BarChart :data="categoryInstallBars" horizontal :height="168" :format="fmtNum" empty-text="暂无安装分布" />
          </div>
        </div>
      </SectionCard>

      <SectionCard title="应用类型分布" subtitle="按已上架应用的发布类型统计">
        <template #actions>
          <span class="tag">已上架 {{ fmtNum(overview?.published_listings) }}</span>
        </template>
        <div v-if="loading && !typeBars.length" class="py-12 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!typeBars.length" class="rounded-control border border-dashed border-ink-200 py-12 text-center text-[12px] text-ink-400">
          暂无类型分布数据
        </div>
        <BarChart v-else :data="typeBars" horizontal :height="188" :format="fmtNum" />
      </SectionCard>
    </div>

    <SectionCard title="安装趋势" :subtitle="`近 ${days} 天每日安装、卸载与累计有效安装`">
      <template #actions>
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag">安装 {{ fmtNum(trend?.total_installs) }}</span>
          <span class="tag">卸载 {{ fmtNum(trend?.total_uninstalls) }}</span>
          <span class="tag" :class="Number(trend?.net) >= 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'">
            净增 {{ fmtNum(trend?.net) }}
          </span>
        </div>
      </template>
      <div v-if="sectionErrors.installs" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
        安装趋势暂不可用：{{ sectionErrors.installs }}
      </div>
      <div v-else-if="loading && !trendLabels.length" class="py-14 text-center text-[12px] text-ink-400">加载中…</div>
      <div v-else-if="!trendLabels.length" class="rounded-control border border-dashed border-ink-200 py-14 text-center text-[12px] text-ink-400">
        窗口内暂无安装记录
      </div>
      <div v-else class="space-y-3">
        <LineChart
          :series="dailySeries"
          :labels="trendLabels"
          :height="220"
          :format="fmtNum"
          aria-label="每日安装与卸载趋势"
        />
        <LineChart
          :series="cumulativeSeries"
          :labels="trendLabels"
          :height="150"
          :show-legend="false"
          :format="fmtNum"
          aria-label="累计有效安装趋势"
        />
      </div>
    </SectionCard>

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="发布者 TOP" :subtitle="`按安装量排序，窗口 ${days} 天`">
        <template #actions>
          <button class="btn-ghost py-1 text-[11px]" @click="emit('go', 'publishers')">发布者管理</button>
        </template>
        <div v-if="sectionErrors.publishers" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
          发布者排行暂不可用：{{ sectionErrors.publishers }}
        </div>
        <div v-else-if="loading && !topPublishers.length" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
        <div v-else-if="!topPublishers.length" class="rounded-control border border-dashed border-ink-200 py-10 text-center text-[12px] text-ink-400">
          暂无发布者数据
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[520px]">
            <thead class="border-b border-ink-100 bg-ink-50/60">
              <tr>
                <th class="th w-10">#</th>
                <th class="th">发布者</th>
                <th class="th text-right">应用</th>
                <th class="th text-right">安装量</th>
                <th class="th text-right">发布者净收入</th>
                <th class="th text-right">分成</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-50">
              <tr v-for="(row, index) in topPublishers" :key="row.publisher_id">
                <td class="td text-ink-400">{{ index + 1 }}</td>
                <td class="td">
                  <div class="flex items-center gap-2">
                    <span class="min-w-0 truncate font-medium text-ink-800">{{ row.name }}</span>
                    <span class="tag shrink-0" :class="publisherClass(row.status)">{{ publisherLabel(row.status) }}</span>
                  </div>
                  <div class="mt-0.5 truncate text-[11px] text-ink-400">{{ row.slug }}</div>
                </td>
                <td class="td text-right">{{ fmtNum(row.listings) }}</td>
                <td class="td text-right">{{ fmtNum(row.installs) }}</td>
                <td class="td text-right">{{ fmtMoney(row.publisher_net_cny) }}</td>
                <td class="td text-right text-ink-500">{{ fmtPct(row.share_pct) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="评分分布" :subtitle="`已发布评价 ${fmtNum(ratings?.overall?.total)} 条，平均 ${fmtRating(ratings?.overall?.average)} 分`">
        <template #actions>
          <span class="tag">高分应用 {{ ratings?.top_rated?.length || 0 }} 个</span>
        </template>
        <div v-if="sectionErrors.ratings" class="rounded-control bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
          评分分布暂不可用：{{ sectionErrors.ratings }}
        </div>
        <div v-else-if="loading && !ratingBars.length" class="py-10 text-center text-[12px] text-ink-400">加载中…</div>
        <template v-else>
          <div class="flex flex-wrap items-center gap-4">
            <DonutChart
              :data="ratingBars"
              :size="150"
              center-label="评价"
              legend-position="right"
              :format="fmtNum"
            />
            <div class="min-w-0 flex-1 divide-y divide-ink-50">
              <div
                v-for="row in ratings?.top_rated || []"
                :key="row.listing_id"
                class="flex items-center gap-2 py-1.5 text-[12px]"
              >
                <span class="min-w-0 flex-1 truncate text-ink-700">{{ row.name }}</span>
                <span class="shrink-0 text-amber-600">{{ fmtRating(row.rating) }} 分</span>
                <span class="w-14 shrink-0 text-right text-ink-400">{{ fmtNum(row.rating_count) }} 条</span>
              </div>
              <div v-if="!(ratings?.top_rated || []).length" class="py-3 text-center text-[12px] text-ink-400">
                暂无已评分的应用
              </div>
            </div>
          </div>
          <div class="mt-3 grid grid-cols-5 gap-1.5">
            <div
              v-for="star in STAR_KEYS"
              :key="star"
              class="rounded-control bg-ink-50/60 px-2 py-1.5 text-center"
            >
              <div class="text-[11px] text-ink-400">{{ star }} 星</div>
              <div class="text-[13px] font-semibold text-ink-800">{{ fmtNum(ratingDistribution[star]) }}</div>
            </div>
          </div>
        </template>
      </SectionCard>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <SectionCard title="推荐位" subtitle="运营配置的精选应用，按推荐排序展示">
        <template #actions>
          <button class="btn-ghost py-1 text-[11px]" @click="emit('go', 'listings')">进入目录</button>
        </template>
        <div v-if="!(overview?.featured || []).length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
          暂无推荐位应用
        </div>
        <div v-else class="grid gap-2 sm:grid-cols-2">
          <button
            v-for="item in overview.featured"
            :key="item.id"
            class="rounded-control border border-ink-100 bg-white px-3 py-2 text-left transition-colors hover:border-brand-300"
            @click="emit('go', 'listings')"
          >
            <div class="flex items-center gap-2">
              <span class="grid h-7 w-7 shrink-0 place-items-center rounded-control bg-brand-50 text-[12px] font-semibold text-brand-700">
                {{ (item.name || '应').slice(0, 1) }}
              </span>
              <span class="min-w-0 flex-1 truncate text-[13px] font-medium text-ink-800">{{ item.name }}</span>
              <span class="tag shrink-0">第 {{ item.featured_rank }} 位</span>
            </div>
            <div class="mt-1 flex items-center justify-between text-[11px] text-ink-400">
              <span class="truncate">{{ item.code }}</span>
              <span>安装 {{ fmtNum(item.install_count) }}</span>
            </div>
          </button>
        </div>
      </SectionCard>

      <SectionCard title="新上架" subtitle="最近上架的应用，便于运营跟踪冷启动表现">
        <template #actions>
          <span class="tag">共 {{ fmtNum(overview?.published_listings) }}</span>
        </template>
        <div v-if="!(overview?.newest || []).length" class="rounded-control border border-dashed border-ink-200 py-8 text-center text-[12px] text-ink-400">
          暂无新上架应用
        </div>
        <div v-else class="divide-y divide-ink-50">
          <div
            v-for="item in overview.newest"
            :key="item.id"
            class="flex items-center gap-2 py-1.5 text-[12px]"
          >
            <span class="min-w-0 flex-1 truncate text-ink-700">{{ item.name }}</span>
            <span class="shrink-0 font-mono text-[11px] text-ink-400">{{ item.code }}</span>
            <span class="w-24 shrink-0 text-right text-[11px] text-ink-400">{{ fmtDate(item.published_at) }}</span>
          </div>
        </div>
      </SectionCard>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">待审核应用</div>
        <div class="mt-0.5 text-[18px] font-semibold text-ink-900">{{ fmtNum(overview?.listings_by_status?.reviewing) }}</div>
        <div class="text-[11px] text-ink-400">草稿 {{ fmtNum(overview?.listings_by_status?.draft) }}</div>
      </div>
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">待处理举报</div>
        <div class="mt-0.5 text-[18px] font-semibold" :class="overview?.pending_reports ? 'text-rose-600' : 'text-ink-900'">
          {{ fmtNum(overview?.pending_reports) }}
        </div>
        <div class="text-[11px] text-ink-400">评价待审 {{ fmtNum(overview?.pending_reviews) }}</div>
      </div>
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">合集</div>
        <div class="mt-0.5 text-[18px] font-semibold text-ink-900">{{ fmtNum(overview?.collections) }}</div>
        <div class="text-[11px] text-ink-400">已发布 {{ fmtNum(overview?.published_collections) }}</div>
      </div>
      <div class="card p-3">
        <div class="text-[11px] text-ink-400">平台版本</div>
        <div class="mt-0.5 text-[15px] font-semibold text-ink-900">{{ overview?.platform_version || '—' }}</div>
        <div class="text-[11px] text-ink-400">兼容性以服务端解析为准</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiFor } from '../../api/platform'
import { useAppStore } from '../../stores/app'
import { formatDate, formatMoney, formatNumber } from '../../composables/useDomainResource'
import StatsGrid from '../../components/platform/StatsGrid.vue'
import SectionCard from '../../components/platform/SectionCard.vue'
import BarChart from '../../components/platform/BarChart.vue'
import DonutChart from '../../components/platform/DonutChart.vue'
import LineChart from '../../components/platform/LineChart.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})
const emit = defineEmits(['go'])

const api = apiFor('marketplace')
const app = useAppStore()

const DAY_OPTIONS = [7, 30, 90]
const STAR_KEYS = ['5', '4', '3', '2', '1']

const days = ref(30)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const sectionErrors = ref({})
const overview = ref(null)
const categories = ref({ total_categories: 0, items: [] })
const trend = ref(null)
const topPublishers = ref([])
const ratings = ref(null)
const revenue = ref(null)

const TYPE_LABELS = {
  app: '应用',
  plugin: '插件',
  integration: '集成',
  template: '模板',
  theme: '主题',
}

const scopeLabel = computed(() => `近 ${days.value} 天`)

const fmtNum = (value) => formatNumber(value)
const fmtMoney = (value) => formatMoney(value)
const fmtDate = (value) => formatDate(value)
const fmtPct = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${n.toFixed(1)}%`
}
const fmtRating = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function publisherLabel(status) {
  const map = { verified: '已认证', pending: '待认证', suspended: '已暂停' }
  return map[status] || status || '未知'
}

function publisherClass(status) {
  const map = {
    verified: 'bg-emerald-50 text-emerald-600',
    pending: 'bg-amber-50 text-amber-600',
    suspended: 'bg-rose-50 text-rose-600',
  }
  return map[status] || ''
}

const monthRevenue = computed(() => {
  const rows = revenue.value?.by_month || []
  if (!rows.length) return null
  const key = new Date().toISOString().slice(0, 7)
  return rows.find((row) => row.month === key) || rows[rows.length - 1]
})

const pendingTotal = computed(() => {
  const reviewing = Number(overview.value?.listings_by_status?.reviewing || 0)
  const reports = Number(overview.value?.pending_reports || 0)
  const reviews = Number(overview.value?.pending_reviews || 0)
  return reviewing + reports + reviews
})

const kpis = computed(() => {
  const data = overview.value || {}
  const income = monthRevenue.value
  return [
    {
      key: 'listings',
      label: '应用数',
      value: fmtNum(data.published_listings),
      hint: `全部 ${fmtNum(data.listings)} · 草稿 ${fmtNum(data.listings_by_status?.draft)}`,
      icon: '◈',
    },
    {
      key: 'installs',
      label: '安装量',
      value: fmtNum(data.active_installs),
      hint: `累计 ${fmtNum(data.installs)} · 用户 ${fmtNum(data.installed_users)}`,
      icon: '⇣',
    },
    {
      key: 'rating',
      label: '平均评分',
      value: fmtRating(ratings.value?.overall?.average),
      unit: '分',
      hint: `已发布评价 ${fmtNum(ratings.value?.overall?.total)} 条`,
      icon: '★',
    },
    {
      key: 'revenue',
      label: '本月收入',
      value: income ? fmtMoney(income.gross_cny) : '—',
      hint: sectionErrors.value.revenue
        ? '仅管理员可查看收入汇总'
        : `发布者净收入 ${fmtMoney(income?.publisher_net_cny)}`,
      icon: '¥',
    },
    {
      key: 'pending',
      label: '待审核',
      value: fmtNum(pendingTotal.value),
      hint: `应用 ${fmtNum(data.listings_by_status?.reviewing)} · 举报 ${fmtNum(data.pending_reports)} · 评价 ${fmtNum(data.pending_reviews)}`,
      icon: '!',
    },
  ]
})

const categoryBars = computed(() =>
  (categories.value?.items || [])
    .filter((row) => row && Number(row.listings) > 0)
    .slice(0, 8)
    .map((row) => ({ label: row.name || '未命名', value: Number(row.listings) || 0 }))
)

const categoryInstallBars = computed(() =>
  (categories.value?.items || [])
    .filter((row) => row && Number(row.installs) > 0)
    .slice(0, 8)
    .map((row) => ({ label: row.name || '未命名', value: Number(row.installs) || 0 }))
)

const typeBars = computed(() => {
  const map = overview.value?.listings_by_type || {}
  return Object.entries(map).map(([key, value]) => ({
    label: TYPE_LABELS[key] || key,
    value: Number(value) || 0,
  }))
})

const trendItems = computed(() => trend.value?.items || [])
const trendLabels = computed(() => trendItems.value.map((row) => String(row.date || '').slice(5)))
const dailySeries = computed(() => [
  { name: '安装', color: '#4f46e5', data: trendItems.value.map((row) => Number(row.installs) || 0) },
  { name: '卸载', color: '#f43f5e', data: trendItems.value.map((row) => Number(row.uninstalls) || 0) },
])
const cumulativeSeries = computed(() => [
  { name: '有效安装', color: '#0d9488', area: true, data: trendItems.value.map((row) => Number(row.cumulative) || 0) },
])

const ratingDistribution = computed(() => ratings.value?.overall?.distribution || {})
const ratingBars = computed(() =>
  STAR_KEYS.map((star) => ({
    label: `${star} 星`,
    value: Number(ratingDistribution.value[star]) || 0,
  }))
)

function setSectionError(key, e) {
  sectionErrors.value[key] = e?.message || '加载失败'
}

async function loadCategories() {
  try {
    categories.value = await api.list('categories/', { page: 1, page_size: 100 })
    delete sectionErrors.value.categories
  } catch (e) {
    categories.value = { total_categories: 0, items: [] }
    setSectionError('categories', e)
  }
}

async function loadTrend() {
  try {
    trend.value = await api.get(`stats/installs/?days=${days.value}`)
    delete sectionErrors.value.installs
  } catch (e) {
    trend.value = null
    setSectionError('installs', e)
  }
}

async function loadPublishers() {
  try {
    const data = await api.list('stats/publishers/', { limit: 10, days: days.value })
    topPublishers.value = data.items || []
    delete sectionErrors.value.publishers
  } catch (e) {
    topPublishers.value = []
    setSectionError('publishers', e)
  }
}

async function loadRatings() {
  try {
    ratings.value = await api.get('stats/ratings/?limit=8')
    delete sectionErrors.value.ratings
  } catch (e) {
    ratings.value = null
    setSectionError('ratings', e)
  }
}

async function loadRevenue() {
  try {
    revenue.value = await api.get(`stats/revenue/?days=${days.value}`)
    delete sectionErrors.value.revenue
  } catch (e) {
    revenue.value = null
    setSectionError('revenue', e)
  }
}

async function loadOverview() {
  const data = await api.get('stats/overview/')
  overview.value = data
}

async function load() {
  if (!api) {
    error.value = '应用市场接口不可用'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  sectionErrors.value = {}
  const tasks = [
    loadOverview(),
    loadCategories(),
    loadTrend(),
    loadPublishers(),
    loadRatings(),
    loadRevenue(),
  ]
  const results = await Promise.allSettled(tasks)
  if (results[0].status === 'rejected') {
    error.value = results[0].reason?.message || '市场总览加载失败'
    app.toastMsg(error.value, 'error')
  } else if (Object.keys(sectionErrors.value).length) {
    notice.value = '部分统计接口暂不可用，已按可用数据降级展示'
  }
  loading.value = false
}

watch(days, () => {
  loadTrend()
  loadPublishers()
  loadRevenue()
})

watch(
  () => props.refreshKey,
  () => load()
)

onMounted(() => load())
</script>