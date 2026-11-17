import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { createReadStream, existsSync, statSync } from 'node:fs'
import { join, normalize, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// The Python side (code/dashboard.py, scheduled 23:10 UTC) writes data/paper/dashboard.json.
// In dev this plugin serves that folder at /data/*, so the app shows the real file without copying anything.
// `npm run build` copies the same file into dist/data/ (scripts/copy-data.mjs) so the built site is self-contained.
const DATA_DIR = resolve(fileURLToPath(new URL('../data/paper', import.meta.url)))

function servePaperData(): Plugin {
  return {
    name: 'serve-paper-data',
    configureServer(server) {
      server.middlewares.use('/data', (req, res, next) => {
        const rel = normalize(decodeURIComponent((req.url ?? '/').split('?')[0]))
        const file = join(DATA_DIR, rel)
        if (!file.startsWith(DATA_DIR) || !existsSync(file) || !statSync(file).isFile()) return next()
        res.setHeader('Cache-Control', 'no-store')
        res.setHeader('Content-Type', file.endsWith('.json') ? 'application/json; charset=utf-8' : 'text/plain; charset=utf-8')
        createReadStream(file).pipe(res)
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), servePaperData()],
  base: './',
  // /api goes to the FastAPI backend (`btc-bot api` or `docker compose up`); if it is down the app falls back to /data
  server: { port: 5173, strictPort: true, host: '127.0.0.1', proxy: { '/api': 'http://127.0.0.1:8000' } },
  preview: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // one chunk for the chart library (and its d3 helpers), one for everything else from node_modules
        manualChunks: (id) => (id.includes('node_modules') ? (/recharts|[\\/]d3-|victory-vendor/.test(id) ? 'vendor-charts' : 'vendor') : undefined),
      },
    },
  },
})
