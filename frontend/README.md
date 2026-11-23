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
- Click a candidate: score breakdown, before/after delay, construction cost; **Before / After / Change** views
  recolour every road with that scenario's per-road results (meso vs meso, or micro vs micro)
- Click a road: its speed, vehicles and delay

Deep links for demos: `/?cand=22&view=change&sim=micro`.

## Files

| File | Role |
|---|---|
| `src/data.js` | loads the exports and joins scenarios to candidates through `(u, v)` |
| `src/scene.js` | the Three.js city: geometry, layers, colours, picking, camera focus |
| `src/colors.js` | colour scales and legends |
| `src/App.jsx` | panels: ranking, view controls, layers, candidate and road cards |
