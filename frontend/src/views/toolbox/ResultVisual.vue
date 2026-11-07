<template>
  <div>
    <div v-if="vm" class="space-y-2.5">
      <p v-if="vm.notice" class="rounded-control bg-ink-50 px-2.5 py-1.5 font-mono text-[11px] leading-relaxed text-ink-600">
        {{ vm.notice.text }}
      </p>

      <!-- 指标卡 -->
      <div v-if="vm.stats && vm.stats.length" class="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <div v-for="s in vm.stats" :key="s.label" class="rounded-control border border-ink-100 px-2.5 py-2">
          <div class="truncate text-[11px] text-ink-400">{{ s.label }}</div>
          <div
            class="truncate font-semibold text-ink-800"
            :class="s.big ? 'text-[22px] leading-tight' : 'text-[14px]'"
            :title="String(s.value)"
          >{{ s.value }}</div>
        </div>
      </div>

      <!-- 图片预览 -->
      <div v-if="vm.image" class="rounded-control border border-ink-100 p-2">
        <img :src="vm.image.src" :alt="vm.image.alt" class="max-h-64 w-auto max-w-full rounded-control object-contain" />
        <p v-if="vm.image.caption" class="mt-1 text-[11px] text-ink-400">{{ vm.image.caption }}</p>
      </div>

      <!-- 下载 -->
      <div v-if="vm.downloads && vm.downloads.length" class="flex flex-wrap gap-2">
        <button v-for="dl in vm.downloads" :key="dl.label" class="btn-outline" @click="download(dl)">{{ dl.label }}</button>
      </div>

      <!-- 条形图 -->
      <div v-if="vm.bars" class="rounded-control border border-ink-100 p-2.5">
        <div class="mb-1.5 text-[12px] font-medium text-ink-600">{{ vm.bars.title }}</div>
        <div v-if="!vm.bars.items.length" class="py-3 text-center text-[12px] text-ink-400">暂无数据</div>
        <div v-for="(b, bi) in vm.bars.items" :key="bi" class="mb-1.5 last:mb-0">
          <div class="flex items-center justify-between gap-2 text-[12px]">
            <span class="truncate text-ink-600" :title="b.label">{{ b.label }}</span>
            <span class="shrink-0 font-mono text-[11px] text-ink-500">{{ b.text }}</span>
          </div>
          <div class="mt-0.5 h-1.5 overflow-hidden rounded-pill bg-ink-100">
            <div class="h-full rounded-pill bg-brand-500" :style="{ width: Math.max(2, Math.min(100, b.pct)) + '%' }"></div>
          </div>
        </div>
      </div>

      <!-- 文本块（合并结果 / 代码 / 脱敏文本） -->
      <div
        v-for="b in blocks"
        :key="b.title"
        class="rounded-control border p-2.5"
        :class="b.tone === 'danger' ? 'border-rose-200 bg-rose-50/60' : 'border-ink-100'"
      >
        <div class="mb-1 flex items-center justify-between gap-2">
          <span class="truncate text-[12px] font-medium text-ink-600">{{ b.title }}</span>
          <button v-if="b.copy" class="shrink-0 text-[11px] text-brand-600 hover:underline" @click="copyText(b.text)">一键复制</button>
        </div>
        <div
          v-if="b.lines"
          class="max-h-72 overflow-auto rounded-control bg-ink-900 p-2.5 font-mono text-[12px] leading-relaxed text-ink-100"
        >
          <div v-for="(ln, i) in b.lines" :key="i" class="whitespace-pre" :class="lineClass(ln.tone)">{{ ln.text || ' ' }}</div>
        </div>
        <pre
          v-else
          class="max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-control bg-ink-900 p-2.5 font-mono text-[12px] leading-relaxed text-ink-100"
        >{{ b.text }}</pre>
      </div>

      <!-- 数据表 -->
      <div v-for="t in tables" :key="t.title" class="rounded-control border border-ink-100">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-2.5 py-1.5">
          <span class="text-[12px] font-medium text-ink-600">{{ t.title }}</span>
          <span v-if="t.note" class="text-[11px] text-ink-400">{{ t.note }}</span>
        </div>
        <div v-if="!t.rows.length" class="px-2.5 py-6 text-center text-[12px] text-ink-400">暂无数据</div>
        <div v-else class="max-h-80 overflow-auto">
          <table class="w-full border-collapse text-[12px]">
            <thead class="sticky top-0 z-[1] bg-white">
              <tr>
                <th
                  v-for="c in t.columns"
                  :key="c.key"
                  class="whitespace-nowrap border-b border-ink-100 px-2 py-1.5 font-medium text-ink-500"
                  :class="c.align === 'right' ? 'text-right' : 'text-left'"
                >{{ c.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(row, ri) in t.rows"
                :key="ri"
                class="border-b border-ink-100 last:border-0"
                :class="row.tone === 'error' ? 'bg-rose-50' : row.tone === 'ok' ? 'bg-emerald-50/40' : ''"
              >
                <td
                  v-for="c in t.columns"
                  :key="c.key"
                  class="px-2 py-1.5 align-top text-ink-700"
                  :class="[c.align === 'right' ? 'text-right tabular-nums' : '', c.mono ? 'font-mono' : '', c.kind === 'new' ? 'text-brand-600 font-medium' : '']"
                >
                  <span
                    v-if="c.kind === 'grade'"
                    class="rounded-pill px-1.5 py-0.5 text-[10px] font-semibold"
                    :class="gradeClass(row[c.key])"
                  >{{ row[c.key] }}</span>
                  <template v-else-if="isSegments(row[c.key])">
                    <template v-for="(seg, si) in row[c.key]" :key="si">
                      <mark v-if="seg.hit" class="rounded bg-amber-200 px-0.5 text-ink-900">{{ seg.text }}</mark>
                      <span v-else>{{ seg.text }}</span>
                    </template>
                  </template>
                  <span v-else :class="!row[c.key] && row[c.key] !== 0 ? 'text-ink-300' : ''">{{ cellText(c, row) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 可视化失败 / 结构不符：回落原始 JSON -->
    <div v-else>
      <p class="mb-1 text-[11px] text-amber-600">该结果结构未能识别，已回落到原始 JSON。</p>
      <pre class="max-h-80 overflow-auto whitespace-pre-wrap rounded-control bg-ink-900 p-3 font-mono text-[12px] leading-relaxed text-ink-100">{{ raw }}</pre>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatNumber, formatSize } from '../../utils/format'
import { describeDownloadError, downloadWithAuth, saveBlob } from '../../utils/download'
import { useAppStore } from '../../stores/app'

const props = defineProps({
  kind: { type: String, required: true },
  data: { type: [Object, Array, String, Number, Boolean], default: null },
  raw: { type: String, default: '' },
  url: { type: String, default: '' },
  params: { type: Object, default: () => ({}) },
})

const app = useAppStore()

// ===== 通用小工具 =====
function arr(v) {
  return Array.isArray(v) ? v : []
}

function txt(v) {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function numText(v) {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v !== 'number') return String(v)
  return formatNumber(v, '—')
}

function money(v) {
  const n = Number(v)
  if (!isFinite(n)) return '—'
  return `¥${formatNumber(Math.round(n * 100) / 100, '0')}`
}

function durationText(sec) {
  const s = Number(sec)
  if (!isFinite(s) || s < 0) return '—'
  if (s < 60) return `${Math.round(s)} 秒后`
  if (s < 3600) return `${Math.round(s / 60)} 分钟后`
  if (s < 86400) return `${(s / 3600).toFixed(1)} 小时后`
  return `${(s / 86400).toFixed(1)} 天后`
}

function isSegments(v) {
  return Array.isArray(v) && v.length > 0 && typeof v[0] === 'object' && v[0] !== null && 'text' in v[0]
}

function cellText(col, row) {
  const v = row[col.key]
  if (isSegments(v)) return v.map((s) => s.text).join('')
  if (Array.isArray(v)) return v.length ? v.join(', ') : '—'
  if (col.kind === 'num') return numText(v)
  if (col.kind === 'pct') return v === null || v === undefined || v === '' ? '—' : `${numText(v)}%`
  if (col.kind === 'bool') return v === null || v === undefined ? '—' : v ? '是' : '否'
  return txt(v)
}

function gradeClass(g) {
  const map = {
    低: 'bg-emerald-50 text-emerald-600',
    中: 'bg-sky-50 text-sky-600',
    高: 'bg-amber-50 text-amber-600',
    极高: 'bg-rose-50 text-rose-600',
  }
  return map[g] || 'bg-ink-100 text-ink-500'
}

function lineClass(tone) {
  const map = {
    head: 'bg-rose-500/25 font-semibold text-rose-100',
    sep: 'bg-rose-500/15 text-rose-100',
    ours: 'bg-emerald-500/15 text-emerald-100',
    theirs: 'bg-violet-500/20 text-violet-100',
  }
  return map[tone] || ''
}

/** 把命中的区间转成 [{text,hit}] 片段，供表格内高亮 */
function highlight(text, matches) {
  const s = String(text === null || text === undefined ? '' : text)
  const spans = arr(matches)
    .filter((m) => m && isFinite(m.start) && isFinite(m.end) && m.end > m.start && m.end <= s.length)
    .sort((a, b) => a.start - b.start)
    .slice(0, 40)
  if (!spans.length) return s
  const out = []
  let pos = 0
  for (const sp of spans) {
    if (sp.start < pos) continue
    if (sp.start > pos) out.push({ text: s.slice(pos, sp.start), hit: false })
    out.push({ text: s.slice(sp.start, sp.end), hit: true })
    pos = sp.end
  }
  if (pos < s.length) out.push({ text: s.slice(pos), hit: false })
  return out
}

function dataUrlToBlob(url) {
  const comma = String(url).indexOf(',')
  if (comma < 0) throw new Error('无效的 data URL')
  const head = url.slice(0, comma)
  const body = url.slice(comma + 1)
  const mime = (/^data:([^;,]+)/i.exec(head) || [null, 'application/octet-stream'])[1]
  if (!/;base64/i.test(head)) return new Blob([decodeURIComponent(body)], { type: mime })
  const bin = atob(body)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

// 请求体里若直接给了图片 data URL（如 image-info 不回传原图），拿来做缩略图
const inputImage = computed(() => {
  const p = props.params || {}
  const cand = p.data_url || p.data || p.image || ''
  return typeof cand === 'string' && /^data:image\//i.test(cand) ? cand : ''
})

// ===== 各接口的视图模型 =====
function buildComplexity(d) {
  const fns = arr(d.functions)
  const s = d.summary || {}
  if (!Array.isArray(d.functions) && !d.summary) return null
  return {
    stats: [
      { label: '函数数', value: numText(d.count ?? fns.length) },
      { label: '平均复杂度', value: numText(s.avg_complexity) },
      { label: '最高复杂度', value: numText(s.max_complexity) },
      { label: '最大嵌套', value: numText(s.max_depth) },
      { label: '高风险函数', value: numText(s.high_risk) },
      { label: '类数', value: numText(d.classes) },
    ],
    tables: [{
      title: '函数复杂度',
      note: fns.length > 200 ? `仅显示前 200 / ${fns.length} 个` : '',
      columns: [
        { label: '函数', key: 'name', mono: true },
        { label: '行号', key: 'line', kind: 'num', align: 'right' },
        { label: '分支数', key: 'branches', kind: 'num', align: 'right' },
        { label: '嵌套深度', key: 'depth', kind: 'num', align: 'right' },
        { label: '复杂度', key: 'complexity', kind: 'num', align: 'right' },
        { label: '等级', key: 'grade', kind: 'grade' },
      ],
      rows: fns.slice(0, 200).map((f) => ({
        name: f.qualified || f.name || '—',
        line: f.line,
        branches: f.branches ?? f.complexity,
        depth: f.depth,
        complexity: f.complexity,
        grade: f.grade || '—',
      })),
    }],
  }
}

function buildImportGraph(d) {
  const nodes = arr(d.nodes)
  const edges = arr(d.edges)
  const top = arr(d.top10)
  if (!Array.isArray(d.nodes) && !Array.isArray(d.edges) && !Array.isArray(d.top10)) return null
  const c = d.counts || {}
  const max = top.reduce((m, t) => Math.max(m, Number(t.count) || 0), 0) || 1
  return {
    stats: [
      { label: '文件数', value: numText(c.files ?? 0) },
      { label: '节点数', value: numText(c.nodes ?? nodes.length) },
      { label: '边数', value: numText(c.edges ?? edges.length) },
      { label: '外部依赖', value: numText(c.external ?? 0) },
      { label: '内部依赖边', value: numText(c.internal_edges ?? 0) },
    ],
    bars: top.length
      ? {
          title: '被引 Top10',
          items: top.map((t) => ({
            label: t.module,
            text: `${numText(t.count)} 次`,
            pct: ((Number(t.count) || 0) / max) * 100,
          })),
        }
      : null,
    tables: [
      {
        title: '节点',
        note: nodes.length > 200 ? `仅显示前 200 / ${nodes.length} 个` : '',
        columns: [
          { label: '节点', key: 'id', mono: true },
          { label: '类型', key: 'type' },
          { label: '被引', key: 'in', kind: 'num', align: 'right' },
          { label: '引用', key: 'out', kind: 'num', align: 'right' },
        ],
        rows: nodes.slice(0, 200),
      },
      {
        title: '边',
        note: edges.length > 200 ? `仅显示前 200 / ${edges.length} 条` : '',
        columns: [
          { label: '来源', key: 'source', mono: true },
          { label: '目标', key: 'target', mono: true },
          { label: '类型', key: 'type' },
          { label: '次数', key: 'weight', kind: 'num', align: 'right' },
          { label: '行号', key: 'lines' },
        ],
        rows: edges.slice(0, 200).map((e) => ({ ...e, lines: arr(e.lines).slice(0, 8).join(', ') })),
      },
    ],
  }
}

function groupText(it) {
  const first = arr(it.matches)[0]
  const g = arr(it.groups).length ? it.groups : first ? arr(first.groups) : []
  if (g.length) return g.map((x) => (x === null ? 'null' : String(x))).join(' | ')
  const named = first && first.named
  if (named && typeof named === 'object' && Object.keys(named).length) {
    return Object.entries(named).map(([k, v]) => `${k}=${v}`).join(' ')
  }
  return ''
}

function buildRegexCases(d) {
  const items = arr(d.items)
  if (!items.length) return null
  return {
    notice: { text: `pattern: ${txt(d.pattern)}${d.flags ? ` · flags: ${d.flags}` : ''}` },
    stats: [
      { label: '用例数', value: numText(d.total ?? items.length) },
      { label: '命中用例', value: numText(d.matched_cases ?? 0) },
      { label: '失败用例', value: numText(d.failed_cases ?? 0) },
      { label: '命中总数', value: numText(d.total_matches ?? 0) },
    ],
    tables: [{
      title: '用例结果',
      note: items.length > 100 ? `仅显示前 100 / ${items.length} 条` : '',
      columns: [
        { label: '用例', key: 'label' },
        { label: '文本', key: 'text' },
        { label: '命中数', key: 'count', kind: 'num', align: 'right' },
        { label: '分组', key: 'groups', mono: true },
        { label: '错误', key: 'error' },
      ],
      rows: items.slice(0, 100).map((it, i) => ({
        label: it.label || `#${(Number.isInteger(it.index) ? it.index : i) + 1}`,
        text: highlight(it.case, it.matches),
        count: it.count ?? arr(it.matches).length,
        groups: groupText(it),
        error: it.error || '',
        tone: it.error ? 'error' : '',
      })),
    }],
  }
}

function buildThreeWay(d) {
  if (typeof d.merged !== 'string') return null
  const all = d.merged.split('\n')
  const shown = all.slice(0, 400)
  let side = ''
  const lines = shown.map((text) => {
    let tone = ''
    if (text.startsWith('<<<<<<<')) {
      side = 'ours'
      tone = 'head'
    } else if (text.startsWith('=======') && side) {
      side = 'theirs'
      tone = 'sep'
    } else if (text.startsWith('>>>>>>>')) {
      side = ''
      tone = 'head'
    } else if (side === 'ours') {
      tone = 'ours'
    } else if (side === 'theirs') {
      tone = 'theirs'
    }
    return { text, tone }
  })
  const conflicts = arr(d.hunks).filter((h) => h && h.type === 'conflict')
  const blocks = [{
    title: all.length > 400
      ? `合并结果（共 ${all.length} 行，仅显示前 400 行）`
      : `合并结果（${all.length} 行）`,
    lines,
  }]
  conflicts.slice(0, 20).forEach((h, i) => {
    const base = arr(h.base)
    blocks.push({
      title: `冲突 #${i + 1}${base.length === 2 ? ` · base 行 ${base[0]}–${base[1]}` : ''}`,
      text: arr(h.result).join('\n'),
      tone: 'danger',
    })
  })
  return {
    stats: [
      { label: '冲突数', value: numText(d.conflicts ?? conflicts.length), big: true },
      { label: '是否干净', value: d.clean ? '无冲突' : '存在冲突' },
      { label: 'ours 变更', value: numText(d.ours_changes) },
      { label: 'theirs 变更', value: numText(d.theirs_changes) },
      { label: 'base 行数', value: numText(d.base_lines) },
    ],
    blocks,
  }
}

function buildCronRuns(d) {
  const runs = arr(d.runs)
  if (!runs.length) return null
  return {
    notice: {
      text: `表达式 ${txt(d.expression)} · 时区 ${txt(d.timezone)}${d.truncated ? ' · 结果被截断' : ''}`,
    },
    stats: [
      { label: '触发次数', value: numText(d.count ?? runs.length) },
      { label: '最近一次', value: runs[0].local || runs[0].iso || '—' },
    ],
    tables: [{
      title: '未来触发时间',
      columns: [
        { label: '#', key: 'no', kind: 'num', align: 'right' },
        { label: '触发时间', key: 'local', mono: true },
        { label: '星期', key: 'weekday' },
        { label: 'ISO', key: 'iso', mono: true },
        { label: '距今', key: 'ago' },
      ],
      rows: runs.map((r, i) => ({
        no: i + 1,
        local: r.local || '—',
        weekday: r.weekday || '—',
        iso: r.iso || '—',
        ago: durationText(r.in_seconds),
      })),
    }],
  }
}

function buildCidrMerge(d) {
  const merged = arr(d.merged)
  const details = arr(d.details)
  if (!merged.length && !details.length) return null
  return {
    stats: [
      { label: '输入网段', value: numText(d.input ?? 0) },
      { label: '合并后', value: numText(d.merged_count ?? merged.length) },
      { label: '被合并', value: numText(d.removed ?? 0) },
      { label: '地址总数', value: numText(d.total_addresses ?? 0) },
      { label: 'IPv4 / IPv6', value: `${numText(d.v4 ?? 0)} / ${numText(d.v6 ?? 0)}` },
    ],
    blocks: merged.length ? [{ title: '合并结果', text: merged.join('\n') }] : [],
    tables: details.length
      ? [{
          title: '网段明细',
          columns: [
            { label: '网段', key: 'cidr', mono: true },
            { label: '网络地址', key: 'network', mono: true },
            { label: '前缀', key: 'prefix', kind: 'num', align: 'right' },
            { label: '版本', key: 'version', kind: 'num', align: 'right' },
            { label: '地址数', key: 'total_addresses', kind: 'num', align: 'right' },
          ],
          rows: details,
        }]
      : [],
  }
}

function buildSnowflake(d) {
  if (d.timestamp_ms === undefined && d.worker === undefined && d.sequence === undefined) return null
  const bits = d.bits || {}
  const rows = [
    { field: '雪花 ID', value: d.id },
    { field: '时间戳 (ms)', value: d.timestamp_ms },
    { field: 'datetime', value: d.datetime || '—' },
    { field: 'UTC', value: d.utc || '—' },
    { field: '时区', value: d.timezone || '—' },
    { field: 'worker', value: d.worker },
    { field: 'datacenter', value: d.datacenter },
    { field: 'sequence', value: d.sequence },
    { field: 'epoch', value: d.epoch },
    { field: '距今', value: d.age_days === null || d.age_days === undefined ? '—' : `${numText(d.age_days)} 天` },
    { field: '时间戳超前', value: d.in_future ? '是' : '否' },
    {
      field: '位分布',
      value: bits.timestamp === undefined
        ? '—'
        : `sign ${bits.sign} / ts ${bits.timestamp} / dc ${bits.datacenter} / worker ${bits.worker} / seq ${bits.sequence}`,
    },
  ]
  return {
    tables: [{
      title: '反解字段',
      columns: [
        { label: '字段', key: 'field' },
        { label: '值', key: 'value', mono: true },
      ],
      rows,
    }],
  }
}

function buildSqlToModel(d) {
  if (typeof d.code !== 'string') return null
  const blocks = [{ title: `${d.model || 'models'}.py`, text: d.code, copy: true }]
  const notes = arr(d.notes)
  if (notes.length) blocks.push({ title: '解析提示', text: notes.join('\n') })
  const fields = arr(d.fields)
  return {
    stats: [
      { label: '模型类', value: d.model || '—' },
      { label: '表名', value: d.table || '—' },
      { label: '字段数', value: numText(d.field_count ?? fields.length) },
    ],
    blocks,
    tables: fields.length
      ? [{
          title: '字段映射',
          note: fields.length > 100 ? `仅显示前 100 / ${fields.length} 个` : '',
          columns: [
            { label: '列名', key: 'name', mono: true },
            { label: 'SQL 类型', key: 'sql_type', mono: true },
            { label: 'Django 类型', key: 'django_type', mono: true },
            { label: '主键', key: 'primary_key', kind: 'bool' },
            { label: '可空', key: 'nullable', kind: 'bool' },
            { label: '赋值', key: 'assignment', mono: true },
          ],
          rows: fields.slice(0, 100),
        }]
      : [],
  }
}

function buildGpa(d) {
  const courses = arr(d.courses)
  if (d.gpa === undefined && !courses.length) return null
  return {
    stats: [
      { label: `加权 GPA（${txt(d.scale)} 分制）`, value: numText(d.gpa), big: true },
      { label: '加权均分', value: numText(d.average) },
      { label: '总学分', value: numText(d.total_credits) },
      { label: '课程数', value: numText(d.count ?? courses.length) },
    ],
    tables: [{
      title: '课程明细',
      columns: [
        { label: '课程', key: 'name' },
        { label: '学分', key: 'credit', kind: 'num', align: 'right' },
        { label: '成绩', key: 'score', kind: 'num', align: 'right' },
        { label: '绩点', key: 'point', kind: 'num', align: 'right' },
        { label: '分段', key: 'band' },
        { label: '来源', key: 'source' },
      ],
      rows: courses,
    }],
  }
}

function buildAnnualLeave(d) {
  if (d.days === undefined && d.entitled_days === undefined) return null
  const basis = arr(d.basis_list)
  const next = d.next_tier
  return {
    notice: next
      ? { text: `下一档：满 ${next.years} 年 → ${next.days} 天（约 ${next.in_years} 年后）；下次入职周年 ${txt(d.next_anniversary)}` }
      : null,
    stats: [
      { label: '当年可休（天）', value: numText(d.days), big: true },
      { label: '法定应享（天）', value: numText(d.entitled_days) },
      { label: '工龄', value: `${numText(d.service_years)} 年` },
      { label: '档位', value: txt(d.tier) },
      { label: '是否折算', value: d.prorated ? '是（入职当年）' : '否' },
      { label: '剩余日历天', value: numText(d.remaining_days_in_year) },
    ],
    blocks: basis.length ? [{ title: '计算依据', text: basis.join('\n') }] : (d.basis ? [{ title: '计算依据', text: d.basis }] : []),
  }
}

function buildOvertimePay(d) {
  if (d.pay === undefined) return null
  return {
    stats: [
      { label: '应发加班费', value: money(d.pay), big: true },
      { label: '时薪', value: money(d.hourly_rate) },
      { label: '倍数', value: `×${txt(d.multiplier)}` },
      { label: '时长', value: `${numText(d.hours)} 小时` },
      { label: '类型', value: txt(d.kind_name || d.kind) },
    ],
    blocks: [{ title: '计算明细', text: txt(d.breakdown || d.summary) }],
    tables: [{
      title: '费率参数',
      columns: [
        { label: '项目', key: 'k' },
        { label: '值', key: 'v', align: 'right' },
      ],
      rows: [
        { k: '月薪', v: money(d.monthly_salary) },
        { k: '月计薪天数', v: `${numText(d.monthly_work_days)} 天` },
        { k: '日薪', v: money(d.day_rate) },
        { k: '时薪', v: money(d.hourly_rate) },
        { k: '加班倍数', v: `×${txt(d.multiplier)}` },
      ],
    }],
  }
}

function buildSeverancePay(d) {
  if (d.amount === undefined) return null
  const notes = arr(d.notes)
  const blocks = []
  if (d.formula) blocks.push({ title: '计算过程', text: d.formula })
  if (notes.length) blocks.push({ title: '封顶说明', text: notes.join('\n') })
  return {
    stats: [
      { label: '补偿金 N', value: money(d.amount), big: true },
      { label: 'N+1 合计', value: money(d.amount_n_plus_1), big: true },
      { label: '补偿月数', value: `${numText(d.months)} 个月` },
      { label: '补偿基数', value: money(d.base_salary) },
      { label: '是否封顶', value: d.capped ? '是' : '否' },
    ],
    blocks,
    tables: [{
      title: 'N / N+1 对比',
      columns: [
        { label: '方案', key: 'plan' },
        { label: '金额', key: 'amount', align: 'right' },
        { label: '说明', key: 'note' },
      ],
      rows: [
        { plan: 'N', amount: money(d.amount), note: `${numText(d.months)} 个月 × ${money(d.base_salary)}` },
        { plan: 'N+1', amount: money(d.amount_n_plus_1), note: `含代通知金 ${money(d.notice_pay)}` },
      ],
    }],
  }
}

function buildImageInfo(d) {
  if (d.width === undefined && !d.format) return null
  const exif = d.exif && typeof d.exif === 'object' ? Object.entries(d.exif) : []
  return {
    image: inputImage.value
      ? { src: inputImage.value, alt: '输入图片', caption: `${txt(d.format)} · ${numText(d.width)}×${numText(d.height)}` }
      : null,
    stats: [
      { label: '格式', value: txt(d.format) },
      { label: '尺寸', value: `${numText(d.width)}×${numText(d.height)}` },
      { label: '体积', value: formatSize(d.bytes) },
      { label: '像素', value: `${numText(d.megapixels)} MP` },
      { label: '色彩模式', value: txt(d.mode) },
      { label: 'EXIF', value: `${numText(d.exif_tags)} 项` },
    ],
    tables: [
      {
        title: '元信息',
        columns: [
          { label: '字段', key: 'field' },
          { label: '值', key: 'value', mono: true },
        ],
        rows: [
          { field: 'MIME', value: d.mime || '—' },
          { field: '帧数', value: numText(d.frames) },
          { field: '动图', value: d.is_animated ? '是' : '否' },
          { field: '透明通道', value: d.has_alpha ? '有' : '无' },
          { field: 'DPI', value: arr(d.dpi).length ? arr(d.dpi).join(' × ') : '—' },
          { field: '字节数', value: numText(d.bytes) },
          { field: '备注', value: d.note || '—' },
        ],
      },
      ...(exif.length
        ? [{
            title: 'EXIF 关键字段',
            columns: [
              { label: '标签', key: 'field' },
              { label: '值', key: 'value' },
            ],
            rows: exif.map(([k, v]) => ({ field: k, value: txt(v) })),
          }]
        : []),
    ],
  }
}

function buildImageWatermark(d) {
  if (!d.data_url) return null
  const ext = d.format === 'jpeg' ? 'jpg' : d.format || 'png'
  return {
    image: {
      src: d.data_url,
      alt: '水印结果',
      caption: `${numText(d.width)}×${numText(d.height)} · ${formatSize(d.bytes)}`,
    },
    downloads: [{ label: `下载图片（${txt(d.format)}）`, filename: `watermarked.${ext}`, dataUrl: d.data_url }],
    stats: [
      { label: '尺寸', value: `${numText(d.width)}×${numText(d.height)}` },
      { label: '体积', value: formatSize(d.bytes) },
      { label: '压缩比', value: numText(d.ratio) },
      { label: '文字', value: txt(d.text) },
      { label: '位置', value: txt(d.position) },
      { label: '不透明度', value: `${numText(Math.round((Number(d.opacity) || 0) * 100))}%` },
    ],
  }
}

function buildSensitiveWords(d) {
  const hits = arr(d.hits)
  if (!Array.isArray(d.hits)) return null
  const sourceText = { builtin: '内置词表', custom: '自定义词表' }[d.source] || txt(d.source)
  return {
    stats: [
      { label: '命中处数', value: numText(d.count ?? hits.length), big: true },
      { label: '独立敏感词', value: numText(d.unique ?? 0) },
      { label: '词表', value: `${sourceText}（${numText(d.word_count)} 词）` },
      { label: '结论', value: d.clean ? '未命中' : '需修改' },
    ],
    blocks: [{ title: '脱敏后文本', text: d.masked === undefined ? '—' : String(d.masked) }],
    tables: [{
      title: '命中明细',
      note: hits.length > 200 ? `仅显示前 200 / ${hits.length} 条` : '',
      columns: [
        { label: '敏感词', key: 'word' },
        { label: '行', key: 'line', kind: 'num', align: 'right' },
        { label: '位置', key: 'range', mono: true },
        { label: '上下文', key: 'context' },
      ],
      rows: hits.slice(0, 200).map((h) => ({
        ...h,
        range: `${numText(h.start)}–${numText(h.end)}`,
      })),
    }],
  }
}

function buildTransform(d) {
  const preview = arr(d.preview).length ? arr(d.preview) : arr(d.rows)
  const newCols = arr(d.new_columns)
  const maskedFields = arr(d.masked_fields)
  if (!preview.length && !newCols.length && !maskedFields.length) return null
  const rows = preview.slice(0, 20)
  const keys = []
  for (const r of rows) {
    if (!r || typeof r !== 'object') continue
    for (const k of Object.keys(r)) if (!keys.includes(k)) keys.push(k)
    if (keys.length >= 14) break
  }
  const highlightKeys = newCols.length ? newCols : maskedFields
  const ver = d.version
  const versionText = ver
    ? `新版本 v${ver.version}（#${ver.id}，${numText(ver.row_count)} 行）`
    : d.version_error || '未传 dataset_id，结果未落版'
  const stats = [
    { label: '总行数', value: numText(d.total_rows ?? preview.length) },
    { label: '预览行数', value: numText(rows.length) },
  ]
  if (newCols.length) stats.push({ label: '新增列', value: numText(newCols.length) })
  if (maskedFields.length) stats.push({ label: '脱敏字段', value: numText(maskedFields.length) })
  if (d.total_hits !== undefined) stats.push({ label: '命中条数', value: numText(d.total_hits) })
  return {
    notice: {
      text: `${d.field ? `字段 ${d.field} · ` : ''}${versionText}${newCols.length ? ` · 新增列：${newCols.slice(0, 6).join(', ')}${newCols.length > 6 ? ' …' : ''}` : ''}`,
    },
    stats,
    tables: rows.length && keys.length
      ? [{
          title: `预览（前 ${rows.length} 行）`,
          note: keys.length >= 14 ? '列数较多，仅显示前 14 列' : '',
          columns: keys.map((k) => ({
            label: k,
            key: k,
            mono: true,
            kind: highlightKeys.includes(k) ? 'new' : undefined,
          })),
          rows,
        }]
      : [],
  }
}

function buildUniqueValues(d) {
  const items = arr(d.items)
  if (!items.length && d.unique === undefined) return null
  const max = items.reduce((m, i) => Math.max(m, Number(i.pct) || 0), 0) || 1
  return {
    notice: { text: `字段 ${txt(d.field)} · TOP ${numText(d.limit ?? items.length)}${d.truncated ? '（有截断）' : ''}` },
    stats: [
      { label: '总行数', value: numText(d.total) },
      { label: '唯一值', value: numText(d.unique) },
      { label: '空值', value: numText(d.blank) },
      { label: '覆盖率', value: `${numText(d.coverage)}%` },
      { label: '未展示取值', value: numText(d.other_values) },
    ],
    bars: {
      title: `取值分布（${txt(d.field)}）`,
      items: items.map((i) => ({
        label: txt(i.value),
        text: `${numText(i.count)} · ${numText(i.pct)}%`,
        pct: ((Number(i.pct) || 0) / max) * 100,
      })),
    },
  }
}

function exportUrl(fmt) {
  const q = new URLSearchParams()
  const p = props.params || {}
  for (const [k, v] of Object.entries(p)) {
    if (k === 'fmt' || v === null || v === undefined || v === '') continue
    q.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v))
  }
  q.set('fmt', fmt)
  const path = String(props.url || '').replace(/^\/+/, '')
  return `/${path}${path.includes('?') ? '&' : '?'}${q.toString()}`
}

function buildExport(d) {
  if (d === null || d === undefined) return null
  const fmt = String((props.params || {}).fmt || '').toLowerCase() === 'json' ? 'json' : 'csv'
  if (typeof d === 'string') {
    const all = d.split(/\r?\n/).filter((l, i, a) => !(i === a.length - 1 && !l))
    return {
      notice: { text: '响应为文件流，已按文本接收；可直接下载原始文件。' },
      stats: [
        { label: '格式', value: fmt.toUpperCase() },
        { label: '行数', value: numText(all.length) },
        { label: '字符数', value: numText(d.length) },
      ],
      blocks: [{ title: '内容预览（前 20 行）', text: all.slice(0, 20).join('\n') }],
      downloads: [{ label: `下载 ${fmt.toUpperCase()}`, filename: `dataset-export.${fmt}`, url: exportUrl(fmt) }],
    }
  }
  if (typeof d !== 'object') return null
  const rows = arr(d.rows)
  return {
    notice: { text: '响应为 JSON 数据集快照。' },
    stats: [
      { label: '数据集', value: txt(d.name) },
      { label: '行数', value: numText(d.row_count ?? rows.length) },
      { label: '列数', value: numText(arr(d.columns).length) },
    ],
    downloads: [{ label: `下载 ${fmt.toUpperCase()}`, filename: `dataset-export.${fmt}`, url: exportUrl(fmt) }],
  }
}

function build(kind, d) {
  if (kind === 'dataset-export') return buildExport(d)
  if (d === null || d === undefined || typeof d !== 'object') return null
  switch (kind) {
    case 'complexity':
      return buildComplexity(d)
    case 'import-graph':
      return buildImportGraph(d)
    case 'regex-cases':
      return buildRegexCases(d)
    case 'three-way':
      return buildThreeWay(d)
    case 'cron-runs':
      return buildCronRuns(d)
    case 'cidr-merge':
      return buildCidrMerge(d)
    case 'snowflake':
      return buildSnowflake(d)
    case 'sql-to-model':
      return buildSqlToModel(d)
    case 'gpa':
      return buildGpa(d)
    case 'annual-leave':
      return buildAnnualLeave(d)
    case 'overtime-pay':
      return buildOvertimePay(d)
    case 'severance-pay':
      return buildSeverancePay(d)
    case 'image-info':
      return buildImageInfo(d)
    case 'image-watermark':
      return buildImageWatermark(d)
    case 'sensitive-words':
      return buildSensitiveWords(d)
    case 'transform':
      return buildTransform(d)
    case 'unique-values':
      return buildUniqueValues(d)
    default:
      return null
  }
}

// 任一构建异常都视为「不可识别」，交给外部回落 JSON
const vm = computed(() => {
  try {
    return build(props.kind, props.data)
  } catch (e) {
    return null
  }
})

const tables = computed(() => (vm.value?.tables || []).filter(Boolean))
const blocks = computed(() => (vm.value?.blocks || []).filter(Boolean))

async function download(dl) {
  try {
    if (dl.dataUrl) {
      saveBlob(dataUrlToBlob(dl.dataUrl), dl.filename)
      app.toastMsg('已开始下载', 'success')
      return
    }
    if (dl.url) {
      await downloadWithAuth(dl.url, dl.filename)
      app.toastMsg('已开始下载', 'success')
    }
  } catch (e) {
    app.toastMsg(await describeDownloadError(e), 'error')
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(String(text || ''))
    app.toastMsg('已复制', 'success')
  } catch (e) {
    app.toastMsg('复制失败，请手动选择内容', 'error')
  }
}
</script>
