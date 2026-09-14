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

export function formatTime(value) {
  if (!value) return '-'
  const d = new Date(value)
  const now = new Date()
  const pad = (x) => String(x).padStart(2, '0')
  if (d.toDateString() === now.toDateString()) {
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatDate(value) {
  if (!value) return '-'
  const d = new Date(value)
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
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

export function priorityColor(p) {
  return { low: 'bg-ink-100 text-ink-500', medium: 'bg-sky-50 text-sky-600', high: 'bg-amber-50 text-amber-600', urgent: 'bg-rose-50 text-rose-600' }[p] || ''
}

export function statusColor(s) {
  return { todo: 'bg-ink-100 text-ink-500', doing: 'bg-sky-50 text-sky-600', done: 'bg-emerald-50 text-emerald-600' }[s] || ''
}
