// Loads the backend exports (RESPONSIBILITIES.md interface contract). All geometry is WGS84.
export const AREA = 'hebbal'
// Study box (west, south, east, north), same as AREAS in backend/urban/data.py
export const BBOX = [77.5890, 13.0290, 77.6050, 13.0430]

const base = `/data/${AREA}`
const cache = new Map()

export function getJSON(file) {
  if (!cache.has(file)) {
    cache.set(file, fetch(`${base}/${file}`).then(r => {
      if (!r.ok) throw new Error(`${file}: HTTP ${r.status}`)
      return r.json()
    }).catch(e => { cache.delete(file); throw e }))
  }
  return cache.get(file)
}

export const candKey = (u, v) => `${u}|${v}`
export const runName = (cand, sim) => `c${String(cand).padStart(2, '0')}_${sim}`

export async function loadAll() {
  const [roads, buildings, zones, construction, candidates, edgeStats, scenarios] = await Promise.all([
    'roads.geojson', 'buildings.geojson',
    // zones = obstacles + kind (water/park/institutional); older exports only have obstacles.geojson
    getJSON('zones.geojson').catch(() => getJSON('obstacles.geojson')),
    'construction.geojson', 'candidates.geojson', 'edge_stats.json', 'scenarios.json',
  ].map(f => typeof f === 'string' ? getJSON(f) : f))

  // Join scenario results to candidate geometry through (u, v), as the contract prefers.
  const meso = new Map((scenarios.meso || []).map(r => [candKey(r.u, r.v), r]))
  const micro = new Map((scenarios.micro || []).map(r => [candKey(r.u, r.v), r]))
  // ranking happens in App.jsx, because it depends on the user's scoring weights

  const selected = candidates.features
    .filter(f => f.properties.status === 'selected')
    .map(f => {
      const key = candKey(f.properties.u, f.properties.v)
      return { key, feature: f, props: f.properties, meso: meso.get(key), micro: micro.get(key) }
    })
  const others = candidates.features.filter(f => f.properties.status !== 'selected')

  return { roads, buildings, zones, construction, edgeStats, selected, others,
           baseline: scenarios.baseline || {}, hasMicro: micro.size > 0 }
}

// Per-edge stats for the before/after comparison. Both sides come from the same simulator (meso vs meso, micro vs
// micro), because meso and micro baselines differ on their own.
export async function loadComparison(cand, sim) {
  const [before, after] = await Promise.all([getJSON(`scenario_stats/base_${sim}.json`),
                                             getJSON(`scenario_stats/${runName(cand, sim)}.json`)])
  return { before, after }
}
