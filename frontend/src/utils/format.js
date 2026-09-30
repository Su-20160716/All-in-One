export function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(n >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

// #95 统一时区：后端返回 ISO 8601 UTC，浏览器按本地时区渲染
const dtf = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
})
const dtfDate = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit',
})
const dtfTime = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit', minute: '2-digit', hour12: false,
})

export function formatTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  if (isNaN(d.getTime())) return '-'
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return dtfTime.format(d)
  }
  return dtf.format(d)
}

export function formatDate(value) {
  if (!value) return '-'
  const d = new Date(value)
  if (isNaN(d.getTime())) return '-'
  return dtfDate.format(d)
}

export function fileIcon(kind, ext) {
  const map = {
    image: '🖼',
    video: '🎬',
    audio: '🎵',
    archive: '🗜',
    text: '📄',
    other: '📦',
  }
  return map[kind] || '📦'
}

// 文件类型图标 + 配色（#9 文件类型图标与配色）
const EXT_ICON = {
  pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗', csv: '📗',
  ppt: '📙', pptx: '📙', md: '📝', txt: '📃', js: '🟨', ts: '🟦',
  py: '🐍', java: '☕', zip: '🗜', rar: '🗜', '7z': '🗜', mp3: '🎵',
  wav: '🎵', mp4: '🎬', mov: '🎬', png: '🖼', jpg: '🖼', jpeg: '🖼',
  gif: '🖼', svg: '🖼', html: '🌐', css: '🎨', json: '🧾', sql: '🗄',
}
const EXT_COLOR = {
  pdf: 'bg-rose-100 text-rose-600', doc: 'bg-sky-100 text-sky-600', docx: 'bg-sky-100 text-sky-600',
  xls: 'bg-emerald-100 text-emerald-600', xlsx: 'bg-emerald-100 text-emerald-600', csv: 'bg-emerald-100 text-emerald-600',
  ppt: 'bg-amber-100 text-amber-600', pptx: 'bg-amber-100 text-amber-600',
  image: 'bg-violet-100 text-violet-600', video: 'bg-fuchsia-100 text-fuchsia-600',
  audio: 'bg-cyan-100 text-cyan-600', archive: 'bg-orange-100 text-orange-600',
  text: 'bg-slate-100 text-slate-600', other: 'bg-ink-100 text-ink-500',
}
export function fileTypeMeta(kind, ext) {
  const e = (ext || '').toLowerCase().replace(/^\./, '')
  return {
    icon: EXT_ICON[e] || fileIcon(kind, ext),
    color: EXT_COLOR[e] || EXT_COLOR[kind] || EXT_COLOR.other,
  }
}

export function priorityColor(p) {
  return { low: 'bg-ink-100 text-ink-500', medium: 'bg-sky-50 text-sky-600', high: 'bg-amber-50 text-amber-600', urgent: 'bg-rose-50 text-rose-600' }[p] || ''
}

export function statusColor(s) {
  return { todo: 'bg-ink-100 text-ink-500', doing: 'bg-sky-50 text-sky-600', done: 'bg-emerald-50 text-emerald-600' }[s] || ''
}
