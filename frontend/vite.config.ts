import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/health': 'http://127.0.0.1:8000',
      '/routes': 'http://127.0.0.1:8000',
      '/lookup': 'http://127.0.0.1:8000',
      '/api/lab': 'http://127.0.0.1:8000',
      '/api/scenarios': 'http://127.0.0.1:8000',
      '/api/exercises': 'http://127.0.0.1:8000',
      '/network': 'http://127.0.0.1:8000',
    },
  },
})
