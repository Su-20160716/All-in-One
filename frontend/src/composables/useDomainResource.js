/**
 * 平台域页面通用数据逻辑。
 *
 * 页面只需要提供域名与列表路径，列表分页、关键词、状态过滤、
 * 创建/更新/删除后的刷新与 toast 都在这里收口，避免 12 个页面
 * 各写一份容易漂移的样板代码。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAppStore } from '../stores/app'
import { apiFor, normalizeList } from '../api/platform'

/** 防抖：搜索框逐字输入不打断后端 */
export function useDebounce(delay = 300) {
  let timer = null
  const value = ref('')
  const debounced = ref('')

  function flush() {
    debounced.value = value.value
  }

  watch(value, () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      debounced.value = value.value
    }, delay)
  })

  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer)
  })

  return { value, debounced, flush }
}

/** 分页状态：总页数至少为 1，避免空列表时出现 0/0 */
export function usePagination(initialSize = 20) {
  const page = ref(1)
  const pageSize = ref(initialSize)
  const total = ref(0)
  const pages = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

  function setPage(next) {
    page.value = Math.min(Math.max(1, Number(next) || 1), pages.value)
  }

  function setPageSize(next) {
    pageSize.value = Math.min(200, Math.max(1, Number(next) || initialSize))
    page.value = 1
  }

  return { page, pageSize, total, pages, setPage, setPageSize }
}

/**
 * 域资源列表。
 * @param {string} domainKey workflow / billing ...
 * @param {string} path 列表路径，如 'definitions/'
 * @param {object} options { pageSize, auto, status, params, transform }
 */
export function useDomainResource(domainKey, path, options = {}) {
  const app = useAppStore()
  const api = apiFor(domainKey)
  const { page, pageSize, total, pages, setPage, setPageSize } = usePagination(options.pageSize || 20)

  const items = ref([])
  const loading = ref(false)
  const error = ref('')
  const q = ref('')
  const status = ref(options.status || '')
  const filters = ref({ ...(options.params || {}) })
  const lastLoadedAt = ref(null)
  const requestSeq = ref(0)

  const empty = computed(() => !loading.value && !error.value && items.value.length === 0)

  function params() {
    const out = { page: page.value, page_size: pageSize.value }
    if (q.value.trim()) out.q = q.value.trim()
    if (status.value) out.status = status.value
    for (const [k, v] of Object.entries(filters.value || {})) {
      if (v !== '' && v !== null && v !== undefined) out[k] = v
    }
    return out
  }

  async function refresh(silent = false) {
    if (!api) {
      error.value = `未知能力域：${domainKey}`
      return []
    }
    const seq = requestSeq.value + 1
    requestSeq.value = seq
    loading.value = true
    error.value = ''
    try {
      const data = await api.list(path, params())
      // 只接受最后一次请求的结果，避免快速切换页签时旧响应覆盖新数据
      if (seq !== requestSeq.value) return items.value
      const normalized = normalizeList(data, { page: page.value, page_size: pageSize.value })
      items.value = typeof options.transform === 'function'
        ? options.transform(normalized.items)
        : normalized.items
      total.value = normalized.count
      lastLoadedAt.value = new Date()
      return items.value
    } catch (e) {
      if (seq !== requestSeq.value) return items.value
      error.value = e?.message || '加载失败'
      items.value = []
      total.value = 0
      if (!silent) app.toastMsg(error.value, 'error')
      return []
    } finally {
      if (seq === requestSeq.value) loading.value = false
    }
  }

  async function create(payload, createPath = path) {
    if (!api) throw new Error('未知能力域')
    const data = await api.create(createPath, payload)
    app.toastMsg('已创建', 'success')
    await refresh(true)
    return data
  }

  async function update(updatePath, payload) {
    if (!api) throw new Error('未知能力域')
    const data = await api.update(updatePath, payload)
    app.toastMsg('已保存', 'success')
    await refresh(true)
    return data
  }

  async function remove(removePath) {
    if (!api) throw new Error('未知能力域')
    const data = await api.remove(removePath)
    app.toastMsg('已删除', 'success')
    await refresh(true)
    return data
  }

  async function run(actionPath, payload = {}, successText = '操作成功') {
    if (!api) throw new Error('未知能力域')
    const data = await api.action(actionPath, payload)
    app.toastMsg(successText, 'success')
    await refresh(true)
    return data
  }

  function resetFilters() {
    q.value = ''
    status.value = ''
    filters.value = {}
    page.value = 1
  }

  if (options.auto !== false) {
    onMounted(() => refresh())
  }

  return {
    api,
    items,
    loading,
    error,
    empty,
    q,
    status,
    filters,
    page,
    pageSize,
    total,
    pages,
    setPage,
    setPageSize,
    lastLoadedAt,
    refresh,
    create,
    update,
    remove,
    run,
    resetFilters,
  }
}

/** 单对象详情加载（抽屉/详情页共用） */
export function useDomainDetail(domainKey) {
  const app = useAppStore()
  const api = apiFor(domainKey)
  const data = ref(null)
  const loading = ref(false)
  const error = ref('')

  async function load(path, silent = false) {
    if (!api) {
      error.value = `未知能力域：${domainKey}`
      return null
    }
    loading.value = true
    error.value = ''
    try {
      data.value = await api.get(path)
      return data.value
    } catch (e) {
      error.value = e?.message || '加载失败'
      data.value = null
      if (!silent) app.toastMsg(error.value, 'error')
      return null
    } finally {
      loading.value = false
    }
  }

  function clear() {
    data.value = null
    error.value = ''
  }

  return { data, loading, error, load, clear }
}

// ---------------------------------------------------------------------------
// 展示格式化：页面里大量重复的 toFixed/日期切片收口到这里
// ---------------------------------------------------------------------------

export function formatNumber(value, digits = 0) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatMoney(value, currency = 'CNY') {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  try {
    return n.toLocaleString('zh-CN', { style: 'currency', currency, maximumFractionDigits: 2 })
  } catch (e) {
    return `${n.toFixed(2)} ${currency}`
  }
}

export function formatDate(value, withTime = false) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  if (!withTime) return date
  return `${date} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function timeAgo(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  const diff = Math.floor((Date.now() - d.getTime()) / 1000)
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`
  return formatDate(value)
}

export function percent(value, digits = 1) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

/** 状态色：未知状态回落中性色，避免页面出现空白徽标 */
export function statusTone(status) {
  const s = String(status || '').toLowerCase()
  if (['active', 'published', 'approved', 'done', 'completed', 'success', 'resolved', 'passed', 'paid', 'enabled', 'online', 'up'].includes(s)) return 'success'
  if (['pending', 'draft', 'queued', 'reviewing', 'running', 'processing', 'in_progress', 'trialing', 'warning', 'degraded'].includes(s)) return 'warning'
  if (['failed', 'error', 'rejected', 'overdue', 'down', 'critical', 'firing', 'cancelled', 'canceled', 'suspended', 'expired'].includes(s)) return 'danger'
  return 'neutral'
}