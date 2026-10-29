// F58 主题与配色定制：亮暗模式（class 策略）+ 强调色（data-accent 覆盖 --brand-* 色阶）。
// 状态全部落在 localStorage，App.vue 启动时调用 initTheme 恢复。

export const THEMES = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
]

// 色阶定义在 style.css 的 [data-accent=...] 块里，这里只保留展示用的主色
export const ACCENTS = [
  { value: 'sky', label: '天际蓝', color: '#0ea5e9' },
  { value: 'emerald', label: '翡翠绿', color: '#10b981' },
  { value: 'violet', label: '紫罗兰', color: '#8b5cf6' },
  { value: 'amber', label: '琥珀橙', color: '#f59e0b' },
  { value: 'rose', label: '玫瑰红', color: '#f43f5e' },
]

const KEY_THEME = 'theme'
const KEY_ACCENT = 'accent'
const mq = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null

export function getTheme() {
  const v = localStorage.getItem(KEY_THEME)
  return THEMES.some((t) => t.value === v) ? v : 'system'
}

export function getAccent() {
  const v = localStorage.getItem(KEY_ACCENT)
  return ACCENTS.some((a) => a.value === v) ? v : 'sky'
}

export function isDark(mode = getTheme()) {
  return mode === 'dark' || (mode === 'system' && !!mq?.matches)
}

export function applyTheme(mode = getTheme(), accent = getAccent()) {
  const dark = isDark(mode)
  const root = document.documentElement
  root.classList.toggle('dark', dark)
  root.dataset.accent = accent
  localStorage.setItem(KEY_THEME, mode)
  localStorage.setItem(KEY_ACCENT, accent)
  // 移动端/安装到桌面的浏览器标题栏颜色跟随主题
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) {
    meta.content = dark ? '#0f172a' : ACCENTS.find((a) => a.value === accent)?.color || '#0ea5e9'
  }
  window.dispatchEvent(new CustomEvent('theme:change', { detail: { mode, accent, dark } }))
  return { mode, accent, dark }
}

/** 应用当前偏好，并监听系统主题变化（仅 system 模式生效）。返回清理函数 */
export function initTheme() {
  applyTheme()
  const onChange = () => {
    if (getTheme() === 'system') applyTheme('system', getAccent())
  }
  mq?.addEventListener?.('change', onChange)
  return () => mq?.removeEventListener?.('change', onChange)
}
