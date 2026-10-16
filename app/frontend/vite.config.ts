import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 로컬 개발: 백엔드(uvicorn :8000)로 /api 프록시
export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
})
