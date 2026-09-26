import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  envPrefix: ['API_', 'APP_'],
  plugins: [
    tailwindcss(),
    react(),
  ],

  // ── Local dev proxy ──────────────────────────────────────────────────────────
  // When API_URL=http://localhost:8000 in .env.local, the frontend sends requests
  // directly to :8000. This proxy block is a fallback convenience — if you ever
  // remove API_URL from .env.local, Vite will proxy /auth, /chat, /sessions, etc.
  // to the local backend automatically.
  // The ws:true entry handles the WebSocket upgrade for /sync/ws.
  server: {
    proxy: {
      '/auth':        { target: 'http://localhost:8000', changeOrigin: true },
      '/chat':        { target: 'http://localhost:8000', changeOrigin: true },
      '/sessions':    { target: 'http://localhost:8000', changeOrigin: true },
      '/history':     { target: 'http://localhost:8000', changeOrigin: true },
      '/student':     { target: 'http://localhost:8000', changeOrigin: true },
      '/quiz':        { target: 'http://localhost:8000', changeOrigin: true },
      '/spaces':      { target: 'http://localhost:8000', changeOrigin: true },
      '/attachments': { target: 'http://localhost:8000', changeOrigin: true },
      '/curriculum':  { target: 'http://localhost:8000', changeOrigin: true },
      '/admin':       { target: 'http://localhost:8000', changeOrigin: true },
      '/health':      { target: 'http://localhost:8000', changeOrigin: true },
      // WebSocket proxy — handles the ws:// upgrade for /sync/ws
      '/sync/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },

  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('react') || id.includes('react-dom') || id.includes('react-router')) {
              return 'vendor-react';
            }
            if (id.includes('lucide-react')) {
              return 'vendor-icons';
            }
            if (id.includes('react-markdown') || id.includes('remark-gfm')) {
              return 'vendor-markdown';
            }
            return 'vendor';
          }
        },
      },
    },
  },
})

