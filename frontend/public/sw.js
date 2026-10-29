/* F59 PWA 离线壳
 * 策略：导航请求 network-first（成功回写壳缓存，失败用缓存的 index.html）；
 *       静态资源 cache-first；/api /ws /media 一律不拦截、不缓存，避免脏数据。
 * 换版本时改 CACHE 后缀即可让旧缓存整体失效。
 */
const CACHE = 'aio-shell-v1'
const SHELL = ['/', '/manifest.webmanifest', '/icon.svg']

const OFFLINE_HTML = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>当前离线</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;background:#f8fafc;color:#334155;
       font:14px/1.6 "PingFang SC","Microsoft YaHei",system-ui,sans-serif}
  .box{text-align:center;padding:24px}
  h1{font-size:18px;margin:0 0 8px}
  p{margin:0 0 16px;color:#64748b}
  button{border:0;border-radius:6px;background:#0ea5e9;color:#fff;padding:8px 16px;font-size:13px;cursor:pointer}
</style></head>
<body><div class="box">
  <h1>当前处于离线状态</h1>
  <p>网络恢复后刷新即可继续使用，已打开的页面数据不会丢失。</p>
  <button onclick="location.reload()">重新加载</button>
</div></body></html>`

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => { /* 首次装机网络异常时不影响后续运行 */ })
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  )
})

function isBypassed(url) {
  return (
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/ws/') ||
    url.pathname.startsWith('/media/') ||
    url.pathname.startsWith('/admin/')
  )
}

async function networkFirstShell(request) {
  const cache = await caches.open(CACHE)
  try {
    const res = await fetch(request)
    if (res && res.ok && res.type === 'basic') {
      // SPA 的任意路由都返回同一份 index.html，统一以 '/' 为键，避免缓存膨胀
      cache.put('/', res.clone())
    }
    return res
  } catch {
    const cached = await cache.match('/')
    return cached || new Response(OFFLINE_HTML, {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    })
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  const res = await fetch(request)
  if (res && res.ok) cache.put(request, res.clone())
  return res
}

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin || isBypassed(url)) return

  if (req.mode === 'navigate') {
    event.respondWith(networkFirstShell(req))
    return
  }
  if (url.pathname.startsWith('/assets/') || /\.(css|js|svg|png|jpe?g|webp|woff2?)$/i.test(url.pathname)) {
    event.respondWith(cacheFirst(req).catch(() => Response.error()))
  }
})
