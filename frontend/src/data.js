// Loads the backend exports (RESPONSIBILITIES.md interface contract). All geometry is WGS84.
// The study area is Hebbal; ?area=<name> loads another exported area (data/areas.json lists them with their boxes).
export const AREA = new URLSearchParams(location.search).get('area') || 'hebbal'
export const AREA_NAMES = { hebbal: 'Hebbal', koramangala: 'Koramangala' }
export const areaName = a => AREA_NAMES[a] || a
// Fallback study boxes (west, south, east, north), same as AREAS in backend/urban/data.py
const BBOXES = { hebbal: [77.5890, 13.0290, 77.6050, 13.0430] }

const cache = new Map()

function fetchJSON(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(`/data/${path}`).then(r => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`)
      return r.json()
    }).catch(e => { cache.delete(path); throw e }))
  }
  return cache.get(path)
}
export const getJSON = file => fetchJSON(`${AREA}/${file}`)
const optional = (p, dflt) => p.catch(() => dflt)

export const candKey = (u, v) => `${u}|${v}`
export const runName = (cand, sim) => `c${String(cand).padStart(2, '0')}_${sim}`

export async function loadAll() {
  const areas = await optional(fetchJSON('areas.json'), { hebbal: { bbox: BBOXES.hebbal, scenarios: true } })
  const bbox = areas[AREA]?.bbox || BBOXES[AREA]
  if (!bbox) throw new Error(`area "${AREA}" has not been exported yet`)
  const empty = { type: 'FeatureCollection', features: [] }
  const [roads, buildings, zones, construction, candidates, edgeStats, scenarios, live, noise] = await Promise.all([
    getJSON('roads.geojson'),
    getJSON('buildings.geojson'),
    // zones = obstacles + kind (water/park/institutional); older exports only have obstacles.geojson
    optional(getJSON('zones.geojson').catch(() => getJSON('obstacles.geojson')), empty),
    optional(getJSON('construction.geojson'), empty),
    // the rest exists only once the simulation pipeline has run for this area
    optional(getJSON('candidates.geojson'), empty),
    optional(getJSON('edge_stats.json'), {}),
    optional(getJSON('scenarios.json'), {}),
    optional(getJSON('live_traffic.json'), null),
    // repeated runs over several SUMO seeds (urban.noise), per candidate variant (1 lane 40 km/h, 2 lanes 60 km/h, ...)
    optional(getJSON('noise.json'), {}),
  ])

  // Join scenario results to candidate geometry through (u, v), as the contract prefers.
  // screening results: macro (deterministic marouter assignment) when exported, else the older meso screen.
  // TODO: UI labels still say "meso"; per-scenario heatmap stats for macro runs are not exported yet.
  const meso = new Map((scenarios.macro || scenarios.meso || []).map(r => [candKey(r.u, r.v), r]))
  const micro = new Map((scenarios.micro || []).map(r => [candKey(r.u, r.v), r]))
  // ranking happens in App.jsx, because it depends on the user's scoring weights

  const selected = candidates.features
    .filter(f => f.properties.status === 'selected')
    .map(f => {
      const key = candKey(f.properties.u, f.properties.v)
      const c = { key, feature: f, props: f.properties, meso: meso.get(key), micro: micro.get(key) }
      const num = c.meso?.cand ?? c.micro?.cand
      // default variant first, then stronger ones; each entry = that variant's summary for this candidate
      c.noise = Object.entries(noise).filter(([, v]) => v.cands?.[num])
        .sort(([, a], [, b]) => a.lanes - b.lanes || a.kmh - b.kmh)
        .map(([id, v]) => ({ id, label: v.label, sim: v.sim, seeds: v.seeds, baseline: v.baseline, ...v.cands[num] }))
      return c
    })
  const others = candidates.features.filter(f => f.properties.status !== 'selected')

  return { areas, bbox, roads, buildings, zones, construction, edgeStats, selected, others, live, noise,
           baseline: scenarios.baseline || {}, hasMicro: micro.size > 0, hasSim: Object.keys(edgeStats).length > 0 }
}

// Per-edge stats for the before/after comparison. Both sides come from the same simulator (meso vs meso, micro vs
// micro), because meso and micro baselines differ on their own.
export async function loadComparison(cand, sim) {
  const [before, after] = await Promise.all([getJSON(`scenario_stats/base_${sim}.json`),
                                             getJSON(`scenario_stats/${runName(cand, sim)}.json`)])
  return { before, after }
}
