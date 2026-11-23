# Parallel Responsibilities

How the work is split between two people so both can proceed at once. The split follows the pipeline in
`idea.md` §11. Every phase reads and writes plain files, so the two halves only meet at the file interface below.

## Owners

| Area | Owner | Scope |
|---|---|---|
| Backend / simulation (PAGP) | Member A | Phases 4, 5 and the Phase 7 API |
| Frontend / visualization (CGVR) | Member B | Phase 6 and the Phase 7 app shell |

### Member A: backend, simulation, parallel computing
- Phase 4: micro validation of the top meso candidates (c25, c22, c24), a multi-seed noise floor, and weight tuning
  for `WEIGHTS` in `backend/urban/evaluate.py`.
- Phase 5: run `uv run python -m urban.parallel hebbal`, then report speedup, efficiency, throughput, scaling and
  result consistency (`data/hebbal/parallel.csv`).
- Exports for the frontend: `roads.geojson` and per-edge baseline stats as JSON (see the contract below).
- Phase 7: FastAPI endpoints that serve the same files and schemas.

### Member B: frontend, 3D decision-support UI
- Phase 6: a Three.js city with extruded buildings, roads, obstacles, and the metro and Mallige worksites.
- A traffic heatmap on the roads from the per-edge baseline stats.
- A candidate-road overlay coloured by score, with click-through to its components (dT, dQ, dC, L, P, veh/h).
- A before/after comparison toggle for a selected candidate.
- The Next.js/React app shell and panels.

## Interface contract (freeze before splitting)

The frontend builds against these static files first. Later the API serves identical schemas, so no frontend
rewrite is needed. All geometry is WGS84 (EPSG:4326). Files live in `backend/data/<area>/`.

| File | Exists | Content |
|---|---|---|
| `buildings.geojson` | yes | building footprint polygons |
| `obstacles.geojson` | yes | water, parks and other no-build polygons |
| `construction.geojson` | yes | `railway=construction` lines (Metro Phase 2B, Mallige Line) |
| `candidates.geojson` | yes | candidate lines: `status`, `u`, `v`, `length_m`, `net_dist`, `detour`, `buildings_hit`, `road_crossings`, `worksite_crossings`, `prescore` |
| `scenarios.csv` | yes | meso ranking: `cand`, `u`, `v`, `dT`, `dQ`, `dC`, `L`, `P`, `score`, `cand_vph`, `teleports`, ... |
| `scenarios_micro.csv` | after validation | same columns, microsim validation of the top K |
| `roads.geojson` | TODO (A) | road lines with SUMO edge id, name, highway type, lanes, speed limit |
| `edge_stats.json` | TODO (A) | `{edge_id: {speed, time_loss, entered, waiting, occupancy}}` from baseline `edges.xml` |

Rules:
- A candidate in `scenarios*.csv` joins to `candidates.geojson` through the `cand` index of the selected rows,
  sorted by `prescore`, or through `(u, v)`. Prefer `(u, v)`.
- Schema changes go through this file first, then the code.
- Values (scores, ranking) will change as weights are tuned. Only the schema is frozen.

## Repository and workflow

1. Make the first commit on `master`, push it to GitHub and add Member B as a collaborator.
2. Layout: `backend/` belongs to Member A and `frontend/` to Member B. Shared changes go only through this document.
3. Use one branch per feature (`feat/parallel`, `feat/viz`, ...) and merge through pull requests.
4. If Member B uses Claude Code, add a `frontend/CLAUDE.md` with their scope and a pointer to this file.

## Data handoff

`backend/data/` is gitignored. Rebuilding it needs the 534 MB Geofabrik PBF and a ~15-minute city cut.
- Member A zips `backend/data/hebbal/` without `sim/` (large and frontend-irrelevant) and shares it via Drive.
- Member B then needs no SUMO, uv or OSM tooling to do frontend work.
- Member A re-shares when `scenarios*.csv` or the exports change.

## Sync points and deferred coupling

- The only live dependency is the `scenarios*.csv` values. Member B reloads the files and the code is unaffected.
- Live traffic animation (SUMO over TraCI streaming to the browser) couples both halves tightly. It is deferred
  until both halves work, then planned together.
- Docker packaging (Phase 7) is done together at the end.
