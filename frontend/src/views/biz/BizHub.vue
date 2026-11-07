<template>
  <div class="mx-auto max-w-7xl space-y-4">
    <!-- 头部 -->
    <div class="card p-4">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 class="text-[18px] font-semibold text-ink-900">业务中心</h2>
          <p class="mt-1 text-[12px] text-ink-500">
            {{ moduleCount }} 个业务模块 · 统一台账、状态流转、批量治理与数据分析
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <div class="rounded-control bg-brand-50 px-3 py-1.5 text-center">
            <div class="text-[16px] font-semibold text-brand-700">{{ moduleCount }}</div>
            <div class="text-[11px] text-brand-600/80">业务模块</div>
          </div>
          <div class="rounded-control bg-ink-50 px-3 py-1.5 text-center">
            <div class="text-[16px] font-semibold text-ink-700">{{ featureText }}</div>
            <div class="text-[11px] text-ink-400">项能力</div>
          </div>
          <div v-if="recordCount !== null" class="rounded-control bg-ink-50 px-3 py-1.5 text-center">
            <div class="text-[16px] font-semibold text-ink-700">{{ recordCount }}</div>
            <div class="text-[11px] text-ink-400">条记录</div>
          </div>
          <div v-if="overdueCount !== null" class="rounded-control bg-rose-50 px-3 py-1.5 text-center">
            <div class="text-[16px] font-semibold text-rose-600">{{ overdueCount }}</div>
            <div class="text-[11px] text-rose-500/80">项逾期</div>
          </div>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <input v-model="kw" class="input w-full sm:w-72" placeholder="搜索模块名称或描述…" />
        <div class="ml-auto flex flex-wrap gap-1">
          <button
            v-for="g in groupNames"
            :key="g"
            class="btn-ghost px-2 py-1 text-[12px]"
            :class="groupFilter === g ? 'bg-brand-50 text-brand-700' : ''"
            @click="groupFilter = groupFilter === g ? '' : g"
          >{{ g }}</button>
        </div>
        <button class="btn-outline" :disabled="loading" @click="load">{{ loading ? '刷新中…' : '刷新' }}</button>
      </div>
    </div>

    <!-- 降级/错误提示：不阻断，用内置目录继续可用 -->
    <div v-if="notice" class="card border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-700">
      {{ notice }}
      <button class="ml-2 underline" @click="load">重新加载</button>
    </div>

    <!-- 加载骨架 -->
    <div v-if="loading && !loaded" class="space-y-4">
      <div v-for="i in 2" :key="i" class="card p-4">
        <div class="mb-3 h-4 w-32 animate-pulse rounded bg-ink-100"></div>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="j in 3" :key="j" class="h-24 animate-pulse rounded-control bg-ink-50"></div>
        </div>
      </div>
    </div>

    <!-- 分组卡片 -->
    <template v-else>
      <section v-for="g in shownGroups" :key="g.name" class="space-y-2">
        <div class="flex items-center gap-2">
          <h3 class="text-[14px] font-semibold text-ink-800">{{ g.name }}</h3>
          <span class="tag">{{ g.modules.length }} 个模块</span>
          <span v-if="g.featureCount" class="text-[11px] text-ink-400">{{ g.featureCount }} 项能力</span>
        </div>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          <RouterLink
            v-for="m in g.modules"
            :key="m.slug"
            :to="`/biz/${m.slug}`"
            class="card group flex flex-col p-3 transition-shadow hover:border-brand-300 hover:shadow-pop"
          >
            <div class="flex items-start gap-2.5">
              <div class="grid h-9 w-9 shrink-0 place-items-center rounded-control bg-ink-50 text-[18px]">{{ m.icon }}</div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="truncate text-[13px] font-semibold text-ink-800 group-hover:text-brand-700">{{ m.name }}</span>
                  <span v-if="m.feature_count" class="tag shrink-0">{{ m.feature_count }} 项</span>
                </div>
                <p class="mt-1 line-clamp-2 text-[11px] leading-relaxed text-ink-500">{{ m.description }}</p>
              </div>
            </div>
            <div class="mt-auto flex items-center justify-between pt-2 text-[11px] text-ink-400">
              <span class="font-mono">/biz/{{ m.slug }}</span>
              <span v-if="m.record_count != null" class="text-ink-500">{{ m.record_count }} 条记录</span>
              <span v-else class="text-brand-500 opacity-0 transition-opacity group-hover:opacity-100">进入 →</span>
            </div>
          </RouterLink>
        </div>
      </section>

      <!-- 空态 -->
      <div v-if="!shownGroups.length" class="card py-20 text-center">
        <div class="text-[32px]">🧩</div>
        <div class="mt-2 text-[13px] text-ink-400">没有匹配「{{ kw }}」的业务模块</div>
        <div class="mt-1 text-[12px] text-ink-400">试试搜索客户、采购、招聘、发票、合规…</div>
        <button class="btn-outline mt-3" @click="resetFilter">清空筛选</button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { bizApi } from '../../api/bizx'
import { bizCatalog, BIZ_GROUP_ORDER } from '../../biz/catalog'
import { formatNumber } from '../../utils/format'

const kw = ref('')
const groupFilter = ref('')
const loading = ref(true)
const loaded = ref(false)
const notice = ref('')
const modules = ref([]) // 后端目录（失败时为空，用 catalog 兜底）
const overview = ref(null)

const moduleCount = computed(() => modules.value.length || bizCatalog.length)
const featureTotal = computed(() => {
  const o = overview.value
  if (o && Number.isFinite(Number(o.feature_count))) return Number(o.feature_count)
  const sum = modules.value.reduce((acc, m) => acc + (Number(m.feature_count) || 0), 0)
  return sum || null
})
const featureText = computed(() => (featureTotal.value == null ? '—' : formatNumber(featureTotal.value)))
const recordCount = computed(() => {
  const v = overview.value?.record_count
  return v == null ? null : formatNumber(v)
})
const overdueCount = computed(() => {
  const v = overview.value?.overdue_count
  return v == null ? null : formatNumber(v)
})

const groupNames = computed(() => {
  const src = modules.value.length ? modules.value : bizCatalog
  const names = src
    .map((m) => m.group || bizCatalog.find((c) => c.slug === m.slug)?.group)
    .filter(Boolean)
  const ordered = BIZ_GROUP_ORDER.filter((n) => names.includes(n))
  for (const n of names) if (!ordered.includes(n)) ordered.push(n)
  return ordered
})

// 以后端目录为准（名称/图标/描述以 catalog 兜底补齐），按分组顺序渲染
const groups = computed(() => {
  const source = modules.value.length
    ? modules.value.map((m) => {
        const c = bizCatalog.find((x) => x.slug === m.slug)
        return {
          ...(c || {}),
          ...m,
          name: m.name || c?.name || m.slug,
          icon: m.icon || c?.icon || '🧩',
          description: m.description || c?.description || '',
          group: m.group || c?.group || '其他',
        }
      })
    : bizCatalog.map((m) => ({ ...m }))
  // groupNames 已包含后端出现的未知分组（追加在末尾），这里不会丢模块
  return groupNames.value
    .map((name) => {
      const mods = source.filter((m) => m.group === name)
      return {
        name,
        modules: mods,
        featureCount: mods.reduce((acc, m) => acc + (Number(m.feature_count) || 0), 0),
      }
    })
    .filter((g) => g.modules.length)
})

const shownGroups = computed(() => {
  const k = kw.value.trim().toLowerCase()
  return groups.value
    .filter((g) => !groupFilter.value || g.name === groupFilter.value)
    .map((g) => ({
      ...g,
      modules: k
        ? g.modules.filter((m) =>
            `${m.name} ${m.description} ${m.slug} ${m.group}`.toLowerCase().includes(k)
          )
        : g.modules,
    }))
    .filter((g) => g.modules.length)
})

function resetFilter() {
  kw.value = ''
  groupFilter.value = ''
}

async function load() {
  loading.value = true
  notice.value = ''
  // 两个接口互不阻塞：目录可用即可进入，概览失败只影响统计数字
  const [modRes, ovRes] = await Promise.allSettled([bizApi.modules(), bizApi.overview()])
  if (modRes.status === 'fulfilled' && modRes.value) {
    const d = modRes.value
    modules.value = Array.isArray(d.modules) ? d.modules : []
    if (!modules.value.length && Array.isArray(d.groups)) {
      modules.value = d.groups.flatMap((g) => g.modules || [])
    }
  } else {
    modules.value = []
  }
  if (ovRes.status === 'fulfilled' && ovRes.value) {
    overview.value = ovRes.value
  } else {
    overview.value = null
  }
  if (modRes.status === 'rejected' || ovRes.status === 'rejected') {
    notice.value = '后端业务目录/概览暂不可用，已降级使用内置目录：模块入口可用，能力数与记录统计暂不可见。'
  } else if (!modules.value.length) {
    notice.value = '后端返回的模块目录为空，已使用内置目录展示。'
  }
  loading.value = false
  loaded.value = true
}

onMounted(load)
</script>
