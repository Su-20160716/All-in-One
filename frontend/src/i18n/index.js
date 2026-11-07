// #200 极简 i18n：只做字典查找，不引第三方库；语言文件按需扩展。
import zhCN from './zh-CN'

const bundles = { 'zh-CN': zhCN }
let lang = 'zh-CN'

export function setLang(next) {
  if (!next || !bundles[next]) return
  lang = next
  document.documentElement.lang = next
  try { localStorage.setItem('locale', next) } catch { /* ignore */ }
}

export function getLang() {
  return lang
}

/** 查找文案；缺失时回落到 fallback 或 key 本身，保证不会渲染 undefined */
export function t(key, fallback) {
  return bundles[lang]?.[key] ?? bundles['zh-CN']?.[key] ?? fallback ?? key
}

/** 初始化：按本地存储恢复语言，并同步 <html lang> */
export function initI18n() {
  let saved = ''
  try { saved = localStorage.getItem('locale') || '' } catch { /* ignore */ }
  setLang(saved || 'zh-CN')
}
