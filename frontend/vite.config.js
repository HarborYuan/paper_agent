import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import tailwindcss from '@tailwindcss/vite'

const BACKEND = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    proxy: {
      // Every backend endpoint (REST + WebSocket) is under /api, so one rule covers them all
      '/api': {
        target: BACKEND,
        ws: true,
      },
      '/health': BACKEND,
      '/docs': BACKEND,
      '/openapi.json': BACKEND,
    }
  }
})
