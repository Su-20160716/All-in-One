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
  let retryTimer = null
  let pending = false
  let dirty = false
  let inFlight = null

  function schedule() {
    pending = true
    dirty = true
    clearTimeout(timer)
    timer = setTimeout(() => {
      flush()
    }, delay)
  }

  async function flush() {
    clearTimeout(timer)
    // 保存进行中又来了一次 flush：等它结束，再把期间新产生的改动补存一次，
    // 否则切笔记/卸载前的最后一段输入会静默丢失。
    if (inFlight) {
      await inFlight
    }
    if (!pending) return
    pending = false
    inFlight = (async () => {
      try {
        await saveFn()
        dirty = false
      } catch (e) {
        // 失败后恢复待存标记并退避重试，不能把这次输入静默吞掉
        pending = true
        console.error('autosave failed', e)
        clearTimeout(retryTimer)
        retryTimer = setTimeout(() => {
          if (pending) flush()
        }, 3000)
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  }

  function cancel() {
    clearTimeout(timer)
    clearTimeout(retryTimer)
    pending = false
  }

  function flushBeacon() {
    // 页面隐藏时即使保存请求正在飞行也要兜底：该请求可能随页面一起被取消
    if (!dirty && !inFlight) return
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
    clearTimeout(timer)
    clearTimeout(retryTimer)
  })

  return { schedule, flush, cancel }
}

export default useAutosave
