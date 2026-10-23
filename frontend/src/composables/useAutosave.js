/**
 * useAutosave（F7）—— 防抖自动保存 + 离开前强制落盘
 *
 * 解决的痛点：原来 800ms 防抖保存，在防抖窗口内切笔记 / 切标签页 /
 * 关页面，最后一段输入直接丢失。
 *
 * 能力：
 * - schedule()：防抖调度（默认 800ms）
 * - flush()：立即执行待存的保存（await 后保证已落库），切笔记/卸载前调用
 * - 页面隐藏（visibilitychange）与卸载（beforeunload）时自动保底：
 *   同步 XHR 已废弃、sendBeacon 又带不了 Authorization 头，
 *   故用 fetch keepalive（页面卸载后浏览器仍会尽力发完）复用同一 PATCH 接口
 *
 * 用法：
 *   const { schedule, flush } = useAutosave(doSave, {
 *     delay: 800,
 *     beacon: () => fetch(...)  // keepalive 保底，无则不注册
 *   })
 */
import { onBeforeUnmount, onMounted } from 'vue'

export function useAutosave(saveFn, opts = {}) {
  const delay = opts.delay ?? 800
  let timer = null
  let pending = false
  let inFlight = null

  function schedule() {
    pending = true
    clearTimeout(timer)
    timer = setTimeout(() => {
      flush()
    }, delay)
  }

  async function flush() {
    clearTimeout(timer)
    if (!pending) return
    if (inFlight) return inFlight
    pending = false
    inFlight = (async () => {
      try {
        await saveFn()
      } catch (e) {
        // 保底失败不抛出：调用方多为事件处理器，抛了也没人接
        console.error('autosave failed', e)
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  }

  function cancel() {
    clearTimeout(timer)
    pending = false
  }

  function flushBeacon() {
    if (!pending) return
    pending = false
    try {
      if (opts.beacon) opts.beacon()
    } catch (e) {
      console.error('autosave beacon failed', e)
    }
  }

  function onVisibility() {
    if (document.visibilityState === 'hidden') flushBeacon()
  }
  function onUnload() {
    flushBeacon()
  }

  onMounted(() => {
    window.addEventListener('beforeunload', onUnload)
    document.addEventListener('visibilitychange', onVisibility)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('beforeunload', onUnload)
    document.removeEventListener('visibilitychange', onVisibility)
  })

  return { schedule, flush, cancel }
}

export default useAutosave
