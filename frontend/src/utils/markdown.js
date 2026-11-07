/**
 * Markdown 安全渲染（F6）
 *
 * marked 只负责 md → html，不消毒；DOMPurify 再剥掉危险标签/属性/协议，
 * 两者串成「先渲染后消毒」的固定链路，杜绝笔记内容里的 XSS payload
 * （<script> / onerror= / javascript: 等）。
 *
 * 用法：
 *   import { renderMarkdown } from '../utils/markdown'
 *   <div v-html="renderMarkdown(note.content)"></div>
 */
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// 用 useNativeParser 版本（浏览器环境），非 Node jsdom 版
const purify = typeof window !== 'undefined' ? DOMPurify(window) : DOMPurify

marked.setOptions({
  gfm: true,
  breaks: true,
})

/**
 * 渲染 Markdown 为安全 HTML。
 * @param {string} md 原始 Markdown
 * @returns {string} 消毒后的 HTML（渲染失败时退化为转义文本）
 */
export function renderMarkdown(md) {
  const text = md == null ? '' : String(md)
  if (!text.trim()) return ''
  let html
  try {
    html = marked.parse(text)
  } catch {
    return escapeHtml(text)
  }
  return purify.sanitize(html, {
    // 笔记场景保留常见格式标签；脚本/事件/危险协议一律剥掉
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'hr', 'span', 'div', 'blockquote',
      'pre', 'code', 'em', 'i', 'strong', 'b', 'u', 's', 'del', 'mark', 'sub', 'sup',
      'ul', 'ol', 'li', 'dl', 'dt', 'dd', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'a', 'img', 'figure', 'figcaption', 'details', 'summary', 'input',
    ],
    ALLOWED_ATTR: [
      'href', 'title', 'alt', 'src', 'width', 'height', 'class', 'id',
      'start', 'colspan', 'rowspan', 'align', 'type', 'checked', 'disabled', 'open',
    ],
    ALLOW_DATA_ATTR: false,
    // 双链 [[]标题]] 渲染出的锚点跳转依赖站内 hash，不放行任意 target
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel|#|\/|\.\/|\.\.\/):|[^a-z]|[a-z+.-]+(?:[^a-z+.:-]|$))/i,
  })
}

/** 纯文本转义（渲染失败时的兜底，保证不出 HTML） */
export function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export default renderMarkdown
