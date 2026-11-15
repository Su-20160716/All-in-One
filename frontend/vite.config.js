import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // 构建号同时用于 Service Worker 缓存版本，发版即换 cache
  define: {
    __APP_BUILD__: JSON.stringify(process.env.VITE_BUILD_ID || String(Date.now())),
  },
  build: {
    // 单 chunk 超过 600KB 时才提示（CodeMirror 语言包天然较大）
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // 手动分包：只把「几乎每个路由都要用、且版本极少变」的框架依赖拆成
        // 独立 vendor chunk，发版时浏览器可复用其 hash 缓存。
        // 注意：CodeMirror / marked / yjs 刻意不在这里合并 —— 它们由路由
        // 动态 import 天然切分，强行归并会把按需加载的语言包变成 1MB 大包。
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('/vue/') || id.includes('vue-router') || id.includes('pinia')) return 'vendor-vue'
          if (id.includes('axios')) return 'vendor-axios'
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      // F3：不再代理 /share —— 那是前端 history 路由（分享落地页），
      // 代理到后端会把页面请求变成 JSON 响应。API 走 /api/share/*。
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
