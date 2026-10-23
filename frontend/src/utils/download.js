/**
 * 带 JWT 的下载工具（F2）
 *
 * 背景：后端下载/导出接口都要 Authorization 头，裸 `<a href="/api/...">`
 * 不带令牌会 401（或跳登录页），故统一走 axios blob + 前端拼 URL。
 *
 * 注意：request 拦截器成功分支返回的是 res.data（项目既有约定），
 * 所以这里拿到的直接是 Blob；错误分支拦截器已映射好 message，
 * 再用 describeDownloadError 兜底解析 blob 里的 JSON 错误体。
 */
import request from '../api/request'

function toBlob(data) {
  if (data instanceof Blob) return data
  if (data == null) return new Blob([''])
  return new Blob([data])
}

/** 触发浏览器下载；调用方负责在组件卸载时无需管（URL 已定时回收） */
export function saveBlob(blob, filename) {
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename || 'download'
  document.body.appendChild(a)
  a.click()
  a.remove()
  // 延迟回收：部分浏览器 click 后立即 revoke 会取消下载
  setTimeout(() => URL.revokeObjectURL(href), 2000)
}

/**
 * 带鉴权下载。url 为 /api 之后的相对路径（request 实例会补 baseURL）。
 * 返回实际使用的文件名。
 */
export async function downloadWithAuth(url, filename = '') {
  const data = await request.get(url, { responseType: 'blob' })
  const blob = toBlob(data)
  const name = filename || 'download'
  saveBlob(blob, name)
  return name
}

/** 下载失败的友好提示：优先用拦截器映射的 message，其次解析 blob 错误体 */
export async function describeDownloadError(e) {
  try {
    const d = e && e.response && e.response.data
    if (d instanceof Blob) {
      const text = await d.text()
      const j = JSON.parse(text)
      if (j && (j.message || j.detail)) return j.message || j.detail
    }
  } catch {
    /* ignore */
  }
  return (e && e.message) || '下载失败'
}

/**
 * 带鉴权加载媒体（图片/音视频）objectURL。
 * 返回 { url, revoke }——组件卸载时必须调 revoke() 释放内存。
 */
export async function loadMediaObjectUrl(url) {
  const data = await request.get(url, { responseType: 'blob' })
  const blob = toBlob(data)
  const url2 = URL.createObjectURL(blob)
  return {
    url: url2,
    revoke: () => URL.revokeObjectURL(url2),
  }
}
