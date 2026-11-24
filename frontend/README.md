# Frontend: 3D decision-support UI (Phase 6)

React + Three.js, built with Vite. Draws the Hebbal study area in 3D and shows the backend's simulation results.

## Run

```bash
cd backend && uv run python -m urban.export hebbal   # once, and after every urban.evaluate run
cd ../frontend && npm install && npm run dev          # http://localhost:5173
```

The dev server reads the exports straight from `backend/data/hebbal/` (see `vite.config.js`), so no copying is needed.
Teammates without the backend can unzip a shared `data/hebbal/` folder into `backend/data/`.

## What it shows

- Roads coloured by congestion (speed as a share of the limit) from the baseline simulation
- Buildings (heights are illustrative; OSM has none here), no-build zones, metro worksites, the study box
- The 40 simulated candidate roads, coloured by score; the ranking list on the left
- Ranking uses the micro score where a candidate was validated (tagged micro ✓ / ✗), otherwise the meso screen
- Click a candidate: score breakdown, before/after delay, construction cost; **Before / After / Change** views
  recolour every road with that scenario's per-road results (meso vs meso, or micro vs micro)
- Click a road: its speed, vehicles and delay; during a comparison, before vs after for that road
- **Chart** tab: score vs traffic on the new road for all candidates (the Braess pattern)
- **Scoring weights** sliders (w1..w5) re-rank all candidates live; defaults = backend `WEIGHTS`
- Hover a candidate on the map, in the list or in the chart to highlight it everywhere
- **Repeated runs**: when `noise.json` exists (`urban.noise` over several seeds, then `urban.export`), candidates
  show mean ± sd delay change per variant (1 lane 40 km/h; 2 lanes 60 km/h via `CAND_LANES=2 CAND_KMH=60`) with
  a real-effect / no-effect tag; this verdict outranks the single-run scores
- **Real traffic (TomTom)**: appears when `live_traffic.json` exists (`uv run python -m urban.live hebbal`, needs
  `TOMTOM_API_KEY` in `backend/.env`); colours measured road segments and compares real vs simulated speeds

Deep links for demos: `/?cand=22&view=change&sim=micro`, `/?tab=chart`, `/?view=live`.

## Files

| File | Role |
|---|---|
| `src/data.js` | loads the exports and joins scenarios to candidates through `(u, v)` |
| `src/scene.js` | the Three.js city: geometry, layers, colours, picking, camera focus |
| `src/colors.js` | colour scales and legends |
| `src/App.jsx` | panels: ranking, view controls, weights, layers, candidate / road cards, real-traffic summary |
| `src/ResultsChart.jsx` | the score vs traffic scatter chart |

Graphics upgrade ideas for the CGVR component: [CGVR_ROADMAP.md](CGVR_ROADMAP.md).
