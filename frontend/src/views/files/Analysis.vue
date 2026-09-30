<template>
  <div class="mx-auto max-w-5xl space-y-4" v-if="data">
    <!-- 用量概览 -->
    <div class="grid grid-cols-4 gap-3">
      <div class="card p-4">
        <div class="text-[12px] text-ink-400">已用空间</div>
        <div class="mt-1 text-[20px] font-bold text-ink-800">{{ data.used_text }}</div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-100">
          <div class="h-full bg-brand-500" :style="{ width: Math.min(100, data.quota_used_pct) + '%' }"></div>
        </div>
        <div class="mt-1 text-[11px] text-ink-400">配额 {{ data.quota_mb }} MB · {{ data.quota_used_pct }}%</div>
      </div>
      <div class="card p-4"><div class="text-[12px] text-ink-400">文件总数</div><div class="mt-1 text-[20px] font-bold">{{ data.file_count }}</div></div>
      <div class="card p-4"><div class="text-[12px] text-ink-400">收藏文件</div><div class="mt-1 text-[20px] font-bold">{{ data.starred }}</div></div>
      <div class="card p-4"><div class="text-[12px] text-ink-400">回收站占用</div><div class="mt-1 text-[20px] font-bold text-rose-500">{{ data.trash_text }}</div></div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <!-- F552 文件类型占比环形图（手写 SVG） -->
      <div class="card p-4">
        <h3 class="mb-3 text-[14px] font-semibold">类型占比 <span class="text-[12px] font-normal text-ink-400">按体积</span></h3>
        <div class="flex items-center gap-4">
          <svg viewBox="0 0 120 120" class="h-36 w-36 shrink-0" role="img" aria-label="类型占比环形图">
            <circle cx="60" cy="60" r="45" fill="none" stroke="#eef2f6" stroke-width="18" />
            <circle v-for="(seg, i) in donut" :key="seg.kind" cx="60" cy="60" r="45" fill="none"
                    :stroke="seg.color" stroke-width="18"
                    :stroke-dasharray="seg.dash" :stroke-dashoffset="seg.offset"
                    transform="rotate(-90 60 60)" />
            <text x="60" y="57" text-anchor="middle" fill="#1e293b" style="font-size:15px;font-weight:700">{{ data.file_count }}</text>
            <text x="60" y="73" text-anchor="middle" fill="#94a3b8" style="font-size:9px">个文件</text>
          </svg>
          <div class="min-w-0 flex-1 space-y-1.5">
            <div v-for="s in donut" :key="s.kind" class="flex items-center gap-2 text-[12px]">
              <span class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ background: s.color }"></span>
              <span class="min-w-0 flex-1 truncate">{{ kindName(s.kind) }}</span>
              <span class="text-ink-400">{{ s.pct }}% · {{ s.size_text }}</span>
            </div>
            <div v-if="!donut.length" class="text-[12px] text-ink-400">暂无文件</div>
          </div>
        </div>
      </div>

      <!-- 类型分布 -->
      <div class="card p-4">
        <h3 class="mb-3 text-[14px] font-semibold">按类型分布</h3>
        <div v-for="k in data.by_kind" :key="k.kind" class="mb-2">
          <div class="mb-1 flex justify-between text-[12px]">
            <span>{{ kindName(k.kind) }}</span><span class="text-ink-400">{{ k.count }} 个 · {{ k.size_text }}</span>
          </div>
          <div class="h-2 rounded-full bg-ink-100">
            <div class="h-full rounded-full bg-brand-500" :style="{ width: pct(k.bytes_sum) + '%' }"></div>
          </div>
        </div>
        <div v-if="!data.by_kind.length" class="text-[12px] text-ink-400">暂无文件</div>
      </div>
    </div>

    <!-- F548 存储体积 30 天趋势（手写 SVG） -->
    <div class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">存储体积趋势 <span class="text-[12px] font-normal text-ink-400">近 {{ trend?.days || 30 }} 天</span></h3>
        <span v-if="trend" class="text-[12px] text-ink-400">
          当前 {{ trend.latest_text }} · 峰值 {{ trend.peak_text }} ·
          <span :class="trend.change_bytes >= 0 ? 'text-rose-500' : 'text-emerald-600'">
            {{ trend.change_bytes >= 0 ? '+' : '-' }}{{ trend.change_text }}（{{ trend.change_pct }}%）
          </span>
        </span>
      </div>
      <svg v-if="trendPath" viewBox="0 0 600 150" class="h-40 w-full" preserveAspectRatio="none" role="img" aria-label="存储趋势折线图">
        <line v-for="i in 4" :key="i" x1="6" :y1="6 + (i - 1) * 33" x2="594" :y2="6 + (i - 1) * 33" stroke="#eef2f6" stroke-width="1" />
        <path :d="trendArea" fill="rgba(14,165,233,0.12)" />
        <path :d="trendPath" fill="none" stroke="#0ea5e9" stroke-width="2" stroke-linejoin="round" />
        <circle v-if="lastTrendPoint" :cx="lastTrendPoint.x" :cy="lastTrendPoint.y" r="3.5" fill="#0ea5e9" />
      </svg>
      <div v-else class="py-6 text-center text-[12px] text-ink-400">趋势加载中…</div>
      <div v-if="trend && trend.points.length" class="mt-1 flex justify-between text-[11px] text-ink-400">
        <span>{{ trend.points[0].date }}</span>
        <span>{{ trend.points[trend.points.length - 1].date }}</span>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <!-- 大文件 Top（既有） -->
      <div class="card p-4">
        <h3 class="mb-3 text-[14px] font-semibold">大文件 Top {{ data.big_files.length }}</h3>
        <div v-for="f in data.big_files" :key="f.id" class="flex items-center justify-between border-b border-ink-50 py-1.5 text-[13px]">
          <span class="truncate">{{ fileIcon(f.kind, f.ext) }} {{ f.name }}</span>
          <span class="ml-2 shrink-0 text-ink-400">{{ f.size_text }}</span>
        </div>
      </div>

      <!-- F549 大文件清单（阈值可调） -->
      <div class="card p-4">
        <div class="mb-3 flex items-center gap-2">
          <h3 class="text-[14px] font-semibold">大文件清单</h3>
          <input v-model.number="largeMb" type="number" min="0" class="input w-24 py-1 text-[12px]" placeholder="阈值 MB" />
          <span class="text-[12px] text-ink-400">MB 以上</span>
          <button class="btn-outline ml-auto px-2 py-1 text-[12px]" @click="loadLarge">查询</button>
        </div>
        <div v-if="large.count !== undefined" class="mb-1.5 text-[12px] text-ink-400">
          共 {{ large.count }} 个 · 合计 {{ large.total_text }}
        </div>
        <div class="max-h-56 overflow-y-auto">
          <div v-for="f in large.files || []" :key="f.id" class="flex items-center justify-between border-b border-ink-50 py-1.5 text-[13px]">
            <span class="truncate">{{ fileIcon(f.kind, f.ext) }} {{ f.name }}</span>
            <span class="ml-2 shrink-0 text-ink-400">{{ f.size_text }} · {{ f.folder_name }}</span>
          </div>
          <div v-if="large.count === 0" class="py-6 text-center text-[12px] text-ink-400">该阈值下没有大文件</div>
          <div v-if="large.count === undefined" class="py-6 text-center text-[12px] text-ink-400">输入阈值后点击查询</div>
        </div>
      </div>
    </div>

    <!-- 重复文件 -->
    <div class="card p-4">
      <div class="mb-2 flex items-center justify-between">
        <h3 class="text-[14px] font-semibold">重复文件 <span class="text-[12px] font-normal text-ink-400">可释放 {{ dupData.wasted_text || data.duplicate_wasted_text }}</span></h3>
        <button class="btn-outline px-2 py-1 text-[12px]" @click="loadDuplicates">
          {{ dupLoading ? '检测中…' : '重新检测' }}
        </button>
      </div>
      <!-- 概要（既有） -->
      <div v-for="d in data.duplicates" :key="d.sha1" class="flex items-center justify-between py-1.5 text-[13px]">
        <span>{{ d.name }}</span><span class="text-ink-400">{{ d.count }} 份 · 每份 {{ d.size_text }}</span>
      </div>
      <!-- F547 重复文件检测（hash 分组明细） -->
      <div v-if="dupData.groups" class="mt-2 space-y-2">
        <div v-for="g in dupData.groups" :key="g.sha1" class="rounded-card border border-ink-100 p-3">
          <div class="flex items-center justify-between text-[13px]">
            <span class="font-medium text-ink-700">哈希 {{ g.sha1.slice(0, 12) }}… × {{ g.count }}</span>
            <span class="text-[12px] text-ink-400">{{ g.size_text }} / 份 · 可释放 {{ g.wasted_text }}</span>
          </div>
          <div class="mt-1.5 space-y-0.5">
            <div v-for="f in g.files" :key="f.id" class="flex items-center justify-between text-[12px] text-ink-500">
              <span class="truncate">{{ f.name }}</span>
              <span class="ml-2 shrink-0">{{ f.folder_name }} · {{ formatSize(f.size) }}</span>
            </div>
          </div>
        </div>
        <div v-if="!dupData.groups.length" class="text-[12px] text-ink-400">没有检测到重复文件 🎉</div>
      </div>
      <div v-else class="text-[12px] text-ink-400">点击「重新检测」按 SHA1 分组查看重复文件明细</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { fileApi } from '../../api'
import { filesx } from '../../api/filesx'
import { fileIcon, formatSize } from '../../utils/format'

const data = ref(null)
const maxBytes = computed(() => Math.max(1, ...(data.value?.by_kind || []).map((k) => k.bytes_sum || 0)))
const pct = (b) => Math.round(((b || 0) / maxBytes.value) * 100)
const NAMES = { image: '图片', video: '视频', audio: '音频', archive: '压缩包', text: '文档', other: '其它' }
const kindName = (k) => NAMES[k] || k

// ---- F552 类型占比环形图（SVG 手写） ----
const KIND_COLORS = { image: '#0ea5e9', video: '#8b5cf6', audio: '#f59e0b', archive: '#14b8a6', text: '#22c55e', other: '#94a3b8' }
const C = 2 * Math.PI * 45
const donut = computed(() => {
  const rows = data.value?.by_kind || []
  const total = rows.reduce((s, r) => s + (r.bytes_sum || 0), 0)
  if (!total) return []
  let acc = 0
  return rows.map((r) => {
    const frac = (r.bytes_sum || 0) / total
    const seg = {
      kind: r.kind,
      color: KIND_COLORS[r.kind] || '#94a3b8',
      pct: Math.round(frac * 1000) / 10,
      size_text: r.size_text,
      dash: `${(frac * C).toFixed(2)} ${C.toFixed(2)}`,
      offset: (-acc * C).toFixed(2),
    }
    acc += frac
    return seg
  })
})

// ---- F548 30 天趋势 SVG ----
const trend = ref(null)
const trendPath = ref('')
const trendArea = ref('')
const lastTrendPoint = ref(null)
function buildTrend() {
  const pts = trend.value?.points || []
  if (pts.length < 2) { trendPath.value = ''; trendArea.value = ''; lastTrendPoint.value = null; return }
  const max = Math.max(...pts.map((p) => p.bytes), 1)
  const W = 600
  const H = 140
  const pad = 8
  const coords = pts.map((p, i) => ({
    x: pad + (i / (pts.length - 1)) * (W - pad * 2),
    y: H - pad - (p.bytes / max) * (H - pad * 2),
  }))
  trendPath.value = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')
  trendArea.value = `${trendPath.value} L${coords[coords.length - 1].x.toFixed(1)},${H} L${coords[0].x.toFixed(1)},${H} Z`
  lastTrendPoint.value = coords[coords.length - 1]
}

// ---- F547 重复文件检测（hash 分组） ----
const dupData = ref({})
const dupLoading = ref(false)
async function loadDuplicates() {
  dupLoading.value = true
  try { dupData.value = await filesx.duplicates(50) } catch (e) { dupData.value = {} } finally { dupLoading.value = false }
}

// ---- F549 大文件清单（阈值可调） ----
const largeMb = ref(50)
const large = ref({})
async function loadLarge() {
  try { large.value = await filesx.largeFiles(largeMb.value || 0) } catch (e) { large.value = {} }
}

onMounted(async () => {
  data.value = await fileApi.analysis()
  try {
    trend.value = await filesx.storageTrend(30)
    buildTrend()
  } catch (e) { trend.value = null }
  loadLarge()
})
</script>
