import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/camera': {
        target: 'http://127.0.0.1',
        changeOrigin: true,
      },
      '/api/shop': {
        target: 'http://127.0.0.1:5100',
        changeOrigin: true,
      }
    }
  },
  build: {
    outDir: 'dist',
  }
})
