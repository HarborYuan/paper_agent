import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    proxy: {
      '/authors': 'http://localhost:8000',
      '/papers': 'http://localhost:8000',
      '/run': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
      '/docs': 'http://localhost:8000',
      '/openapi.json': 'http://localhost:8000',
    }
  }
})
