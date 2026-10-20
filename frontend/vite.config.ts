import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // The backend the dev server proxies to. Override it with
  // ROUTELENS_BACKEND_URL when you need to run against a backend on a
  // different port, such as one started from a worktree.
  const backend = loadEnv(mode, process.cwd(), '').ROUTELENS_BACKEND_URL || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: '127.0.0.1',
      proxy: {
        '/health': backend,
        '/routes': backend,
        '/lookup': backend,
        '/packet-journey': backend,
        '/api/lab': backend,
        '/api/pcap': backend,
        '/api/scenarios': backend,
        '/api/exercises': backend,
        '/api/host-exercises': backend,
        '/api/discovery': backend,
        '/api/report': backend,
        '/network': backend,
      },
    },
  }
})
