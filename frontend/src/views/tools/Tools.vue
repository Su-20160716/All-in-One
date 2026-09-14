<template>
  <div class="mx-auto max-w-6xl">
    <div class="mb-4 flex items-center justify-between">
      <div>
        <h2 class="text-[16px] font-semibold text-ink-800">开发者工具箱</h2>
        <p class="text-[12px] text-ink-400">共 {{ total }} 个纯前端触发、服务端计算的工具</p>
      </div>
      <input v-model="kw" class="input w-56" placeholder="搜索工具…" />
    </div>

    <div class="grid grid-cols-12 gap-4">
      <!-- 左侧分类 + 工具列表 -->
      <div class="col-span-3 space-y-3">
        <div v-for="(items, cat) in filteredCatalog" :key="cat" class="card p-2">
          <div class="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-400">{{ catName(cat) }}</div>
          <button
            v-for="t in items"
            :key="t.key"
            class="block w-full rounded-control px-2 py-1.5 text-left text-[13px] transition-colors"
            :class="active === t.key ? 'bg-brand-600 text-white' : 'text-ink-600 hover:bg-ink-100'"
            @click="switchTool(t)"
          >
            {{ t.name }}
          </button>
        </div>
      </div>

      <!-- 右侧工作区 -->
      <div class="col-span-9">
        <div class="card p-5" v-if="current">
          <div class="mb-1 flex items-center gap-2">
            <h3 class="text-[15px] font-semibold text-ink-800">{{ current.name }}</h3>
            <span class="tag-brand">{{ catName(current.cat) }}</span>
          </div>
          <p class="mb-3 text-[12px] text-ink-400">{{ current.desc }}</p>

          <div class="space-y-3">
            <template v-for="f in fields" :key="f.name">
              <label v-if="f.type !== 'checkbox'" class="block">
                <span class="mb-1 block text-[12px] font-medium text-ink-600">{{ f.label }}</span>
                <textarea
                  v-if="f.type === 'textarea'"
                  v-model="form[f.name]"
                  class="input h-40 resize-none font-mono text-[12px]"
                  :placeholder="f.placeholder || ''"
                ></textarea>
                <select v-else-if="f.type === 'select'" v-model="form[f.name]" class="input">
                  <option v-for="o in f.options" :key="o.v" :value="o.v">{{ o.label }}</option>
                </select>
                <input v-else v-model="form[f.name]" :type="f.type || 'text'" class="input" :placeholder="f.placeholder || ''" />
              </label>
              <label v-else class="flex items-center gap-2 text-[13px] text-ink-600">
                <input v-model="form[f.name]" type="checkbox" /> {{ f.label }}
              </label>
            </template>
          </div>

          <div class="mt-4 flex items-center gap-2">
            <button class="btn-primary" :disabled="running" @click="run">{{ running ? '计算中…' : '执 行' }}</button>
            <button class="btn-outline" @click="form = {}">清空</button>
            <button class="btn-ghost" @click="copyResult">复制结果</button>
            <span v-if="runInfo" class="text-[12px] text-emerald-600">{{ runInfo }}</span>
          </div>

          <!-- 结果 -->
          <div v-if="result !== null" class="mt-4">
            <div class="mb-1 text-[12px] font-medium text-ink-600">结果</div>
            <img v-if="current.key === 'qrcode' && result.image" :src="result.image" class="h-56 w-56 rounded-control border border-ink-100 bg-white p-2" />
            <div v-else-if="current.key === 'color-palette'" class="flex gap-2">
              <div v-for="(c, i) in result.palette" :key="i" class="text-center">
                <div class="h-14 w-14 rounded-control border border-ink-100" :style="{ background: c }"></div>
                <div class="mt-1 font-mono text-[10px] text-ink-500">{{ c }}</div>
              </div>
              <div class="text-center">
                <div class="h-14 w-14 rounded-control border border-ink-100" :style="{ background: result.complement }"></div>
                <div class="mt-1 font-mono text-[10px] text-ink-500">互补 {{ result.complement }}</div>
              </div>
            </div>
            <div v-else-if="current.key === 'password-strength'" class="space-y-1">
              <div class="text-[14px] font-semibold" :class="strengthColor">{{ result.level }}（{{ result.score }}/6）</div>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="(ok, k) in result.checks" :key="k" class="rounded-pill px-2 py-0.5 text-[11px]" :class="ok ? 'bg-emerald-50 text-emerald-600' : 'bg-ink-100 text-ink-400'">{{ k }}</span>
              </div>
            </div>
            <pre v-else class="max-h-80 overflow-auto whitespace-pre-wrap rounded-control bg-ink-900 p-3 font-mono text-[12px] leading-relaxed text-ink-100">{{ pretty }}</pre>
          </div>
        </div>
        <div v-else class="card grid h-64 place-items-center text-[13px] text-ink-400">从左侧选择一个工具开始</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { toolApi } from '../../api'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const catalog = ref({})
const total = ref(0)
const active = ref('')
const current = ref(null)
const form = ref({})
const result = ref(null)
const running = ref(false)
const runInfo = ref('')
const kw = ref('')

const CAT_NAMES = {
  JSON: 'JSON', 时间: '时间', 生成: '生成器', 加密: '加密', 编码: '编码转换', 颜色: '颜色',
  转换: '格式转换', 图像: '图像', 文本: '文本处理', 校验: '校验工具', 换算: '单位换算',
}
const catName = (c) => CAT_NAMES[c] || c

// 每个工具的输入字段定义
const FIELD_SCHEMA = {
  'json-format': [{ name: 'text', label: 'JSON 内容', type: 'textarea', placeholder: '{"a":1}' },
    { name: 'mode', label: '模式', type: 'select', options: [{ v: '', label: '美化' }, { v: 'minify', label: '压缩' }] }],
  'text-case': [{ name: 'text', label: '文本', type: 'textarea' },
    { name: 'mode', label: '大小写', type: 'select', options: [
      { v: 'upper', label: '全部大写' }, { v: 'lower', label: '全部小写' }, { v: 'title', label: '标题式' },
      { v: 'capitalize', label: '首字母大写' }, { v: 'swapcase', label: '大小写反转' }] }],
  'text-diff': [{ name: 'a', label: '文本 A', type: 'textarea' }, { name: 'b', label: '文本 B', type: 'textarea' }],
  'text-dedupe': [{ name: 'text', label: '每行一条', type: 'textarea' }],
  'text-sort': [{ name: 'text', label: '每行一条', type: 'textarea' },
    { name: 'order', label: '顺序', type: 'select', options: [{ v: 'asc', label: '升序' }, { v: 'desc', label: '降序' }] },
    { name: 'numeric', label: '按数值排序', type: 'checkbox' }],
  'text-trim': [{ name: 'text', label: '文本', type: 'textarea' },
    { name: 'remove_blank', label: '去除空行', type: 'checkbox' }, { name: 'strip_line', label: '去除行首尾空白', type: 'checkbox' }],
  'text-count': [{ name: 'text', label: '文本', type: 'textarea' }],
  'text-reverse': [{ name: 'text', label: '文本', type: 'textarea' },
    { name: 'mode', label: '反转维度', type: 'select', options: [
      { v: 'chars', label: '字符' }, { v: 'words', label: '单词' }, { v: 'lines', label: '行' }] }],
  slugify: [{ name: 'text', label: '文本', type: 'text' }],
  'markdown-plain': [{ name: 'text', label: 'Markdown', type: 'textarea' }],
  'regex-test': [{ name: 'pattern', label: '正则表达式', type: 'text', placeholder: '\\d+' }, { name: 'text', label: '待匹配文本', type: 'textarea' }],
  base64: [{ name: 'text', label: '文本', type: 'textarea' },
    { name: 'mode', label: '方向', type: 'select', options: [{ v: 'encode', label: '编码' }, { v: 'decode', label: '解码' }] }],
  url: [{ name: 'text', label: 'URL', type: 'textarea' },
    { name: 'mode', label: '方向', type: 'select', options: [{ v: 'encode', label: '编码' }, { v: 'decode', label: '解码' }] }],
  morse: [{ name: 'text', label: '文本/摩斯码', type: 'text' },
    { name: 'mode', label: '方向', type: 'select', options: [{ v: 'encode', label: '文本→摩斯' }, { v: 'decode', label: '摩斯→文本' }] }],
  rot13: [{ name: 'text', label: '文本', type: 'text' }],
  'html-entity': [{ name: 'text', label: 'HTML', type: 'textarea' },
    { name: 'mode', label: '方向', type: 'select', options: [{ v: 'encode', label: '转义' }, { v: 'decode', label: '反转义' }] }],
  'number-base': [{ name: 'value', label: '数值', type: 'text' }, { name: 'from_base', label: '输入进制', type: 'number' }],
  'text-hex': [{ name: 'text', label: '文本', type: 'text' },
    { name: 'mode', label: '方向', type: 'select', options: [{ v: 'encode', label: '文本→HEX' }, { v: 'decode', label: 'HEX→文本' }] }],
  'text-binary': [{ name: 'text', label: '文本', type: 'text' },
    { name: 'mode', label: '方向', type: 'select', options: [{ v: 'encode', label: '文本→二进制' }, { v: 'decode', label: '二进制→文本' }] }],
  'jwt-decode': [{ name: 'token', label: 'JWT', type: 'textarea' }],
  hash: [{ name: 'text', label: '文本', type: 'textarea' },
    { name: 'alg', label: '算法', type: 'select', options: [
      { v: 'md5', label: 'MD5' }, { v: 'sha1', label: 'SHA1' }, { v: 'sha256', label: 'SHA256' }, { v: 'sha512', label: 'SHA512' }, { v: 'all', label: '全部' }] }],
  'password-strength': [{ name: 'password', label: '密码', type: 'text' }],
  luhn: [{ name: 'number', label: '银行卡号', type: 'text' }],
  idcard: [{ name: 'idcard', label: '18 位身份证号', type: 'text' }],
  password: [{ name: 'length', label: '长度', type: 'number' }, { name: 'count', label: '数量', type: 'number' }, { name: 'symbol', label: '包含特殊符号', type: 'checkbox' }],
  uuid: [{ name: 'count', label: '数量', type: 'number' }, { name: 'upper', label: '大写', type: 'checkbox' }],
  'random-number': [{ name: 'min', label: '最小值', type: 'number' }, { name: 'max', label: '最大值', type: 'number' }, { name: 'count', label: '数量', type: 'number' }],
  timestamp: [{ name: 'mode', label: '模式', type: 'select', options: [
    { v: 'now', label: '当前时间戳' }, { v: 'to_date', label: '时间戳→日期' }, { v: '', label: '日期→时间戳' }] },
    { name: 'timestamp', label: '时间戳(to_date)', type: 'text' }, { name: 'date', label: '日期(如 2026-09-10T12:00)', type: 'text' }],
  'date-diff': [{ name: 'start', label: '开始日期', type: 'text', placeholder: '2026-01-01' }, { name: 'end', label: '结束日期', type: 'text', placeholder: '2026-01-11' }],
  'unit-convert': [{ name: 'value', label: '数值', type: 'number' },
    { name: 'table', label: '量纲', type: 'select', options: [{ v: 'length', label: '长度' }, { v: 'weight', label: '重量' }, { v: 'temperature', label: '温度' }] },
    { name: 'from', label: '原单位', type: 'text', placeholder: 'm / kg / c' }, { name: 'to', label: '目标单位', type: 'text', placeholder: 'cm / g / f' }],
  color: [{ name: 'hex', label: 'HEX 色值', type: 'text', placeholder: '#0ea5e9' }],
  'color-palette': [{ name: 'hex', label: '基色', type: 'text', placeholder: '#0ea5e9' }],
  'csv-json': [{ name: 'text', label: 'CSV', type: 'textarea' }],
  'json-csv': [{ name: 'data', label: 'JSON 对象数组', type: 'textarea' }],
  qrcode: [{ name: 'text', label: '文本/链接', type: 'textarea' }],
}
const DEFAULT_FIELDS = [{ name: 'text', label: '输入内容', type: 'textarea' }]
const fields = computed(() => (current.value ? FIELD_SCHEMA[current.value.key] || DEFAULT_FIELDS : []))

const filteredCatalog = computed(() => {
  const out = {}
  for (const [cat, items] of Object.entries(catalog.value)) {
    const hit = items.filter((t) => !kw.value || t.name.includes(kw.value) || t.desc.includes(kw.value) || t.key.includes(kw.value))
    if (hit.length) out[cat] = hit
  }
  return out
})

const pretty = computed(() => {
  if (result.value === null) return ''
  if (typeof result.value === 'string') return result.value
  try {
    return JSON.stringify(result.value, null, 2)
  } catch (e) {
    return String(result.value)
  }
})
const strengthColor = computed(() => {
  const s = result.value?.score ?? 0
  return ['text-rose-600', 'text-rose-600', 'text-amber-600', 'text-amber-600', 'text-emerald-600', 'text-emerald-600'][Math.min(s, 5)]
})

function switchTool(t) {
  active.value = t.key
  current.value = { ...t, cat: findCat(t.key) }
  form.value = {}
  result.value = null
  runInfo.value = ''
  // 默认值
  for (const f of fields.value) {
    if (f.type === 'checkbox') form.value[f.name] = false
    else if (f.type === 'select') form.value[f.name] = f.options[0].v
    else form.value[f.name] = f.type === 'number' ? null : ''
  }
}
function findCat(key) {
  for (const [cat, items] of Object.entries(catalog.value)) {
    if (items.some((t) => t.key === key)) return cat
  }
  return ''
}

async function run() {
  running.value = true
  runInfo.value = ''
  try {
    const payload = {}
    for (const [k, v] of Object.entries(form.value)) {
      if (v !== '' && v !== null && v !== undefined) payload[k] = v
    }
    const r = await toolApi.run(active.value, payload)
    result.value = r.result
    runInfo.value = '✓ 执行完成'
  } catch (e) {
    result.value = null
    app.toastMsg(e.message, 'error')
  } finally {
    running.value = false
  }
}

async function copyResult() {
  if (result.value === null) return
  try {
    await navigator.clipboard.writeText(pretty.value)
    app.toastMsg('已复制', 'success')
  } catch (e) { /* ignore */ }
}

onMounted(async () => {
  try {
    const r = await toolApi.catalog()
    catalog.value = r.categories
    total.value = r.total
    const first = Object.values(r.categories)[0]?.[0]
    if (first) switchTool(first)
  } catch (e) {
    app.toastMsg('工具目录加载失败', 'error')
  }
})
</script>
