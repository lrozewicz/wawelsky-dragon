import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { tanstackRouter } from '@tanstack/router-plugin/vite'

// Proxy dev servera Vite do backendu (nakładka docker-compose.dev.yml wyrzuca api na 8000;
// z kontenera web-dev ustawia to WD_API_UPSTREAM=http://api:8000)
const upstream = process.env.WD_API_UPSTREAM ?? 'http://localhost:8000'

const proxy = {
  '/api': { target: upstream, changeOrigin: true, ws: false },
  '/v1': { target: upstream, changeOrigin: true, ws: false },
  '/user-api': { target: upstream, changeOrigin: true, ws: false },
  '/sharepoint-sync-api': { target: upstream, changeOrigin: true, ws: false },
}

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react()],
  server: { proxy },
  // Manifest (`.vite/manifest.json`) czyta skrypt budżetu JS (`scripts/bundle-budget.mjs`, kontrakt E3-7 §C4).
  build: { manifest: true },
})
