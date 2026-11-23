import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server serves the backend exports straight from backend/data/<area>/ at /data/<area>/<file>.
// The Phase 7 FastAPI server will serve the same paths, so the frontend code does not change.
const DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../backend/data')
const SAFE = /^\/([\w-]+\/(scenario_stats\/)?)?[\w-][\w.-]*\.(geojson|json)$/   // no "..", only exported json

function backendData() {
  return {
    name: 'backend-data',
    configureServer(server) {
      server.middlewares.use('/data', (req, res, next) => {
        const p = decodeURIComponent(req.url.split('?')[0])
        if (!SAFE.test(p)) return next()
        const f = path.join(DATA, p)
        if (!fs.existsSync(f)) { res.statusCode = 404; return res.end('not exported yet: run uv run python -m urban.export') }
        res.setHeader('Content-Type', 'application/json')
        fs.createReadStream(f).pipe(res)
      })
    },
  }
}

export default defineConfig({ plugins: [react(), backendData()] })
