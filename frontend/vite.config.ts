import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 开发时 `npm run dev`，/api 和对象存储走本机已启动的 Docker 入口
export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://localhost', '/lessontrace': 'http://localhost' } },
})
