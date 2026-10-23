import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
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
