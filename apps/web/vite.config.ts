import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // MapLibre's web worker breaks under Vite's dep pre-bundling in dev.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  server: {
    // Proxy API calls to the OpenAid backend during development.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
