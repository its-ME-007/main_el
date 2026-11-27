# Pipeline: every step with its input and output

All paths are under `backend/data/<area>/` unless shown otherwise. Run each command from `backend/` as
`uv run python -m urban.<step> ...`.

Run one SUMO step at a time: steps 2, 5, 7, 9, 10 and 11 all rewrite the shared demand files in `sim/`.

| # | Step | Command | Input | Output |
|---|---|---|---|---|
| 0 | City cut (one-time) | inside `urban.data` | `data/osm/southern-zone-latest.osm.pbf` (Geofabrik, 534 MB) | `data/osm/bengaluru.osm.pbf` (~15 min) |
| 1 | Data | `urban.data <area>` | `bengaluru.osm.pbf`, the area box in `AREAS` | `roads.osm` (drivable roads, box padded ~1.1 km), `roads.graphml` (OSMnx graph, largest strongly connected component), `features.osm`, `buildings.geojson`, `obstacles.geojson` (water, parks, schools, hospitals, ...), `construction.geojson` (metro / suburban rail works), `rail.geojson` (at-grade rail), `vacant.geojson` |
| 2 | Baseline | `urban.sim <area>` | `roads.osm`; calibration settings `CALIB`, `FLYOVER_RATE`, `OTHER_RATE`, `LOCAL_RATE`; seed 42 | `sim/net.net.xml` (SUMO net: left-hand traffic, untagged-speed fix, zipper merges), `sim/through.rou.xml` (arterial entry → exit flows), `sim/local.trips.xml` (box-weighted random trips), `sim/baseline/{tripinfo,stats,edges}.xml` (micro run). Prints metrics, calibration road flow, top bottlenecks |
| 3 | Validation (optional) | `urban.validate <area>` | `sim/baseline/edges.xml`, `backend/tomtom/tomtom_live_2026-11-27.json` | Printed only: sim vs real speed, bias, MAE, roads within 10 km/h. (`urban.live <area>` makes `live_traffic.json` from the TomTom API, key in `backend/.env`) |
| 4 | Candidates | `urban.candidates <area>` | `sim/net.net.xml`, `sim/baseline/edges.xml` (time loss → 30 hot edges), buildings, obstacles, construction, rail, vacant | `candidates.geojson`: every examined pair, status `selected` / `feasible` / `rejected:<reason>`, with `u`, `v`, `length_m`, `net_dist`, `detour`, `buildings_hit`, crossings, `prescore` |
| 5 | Macro screen | `urban.evaluate <area> --workers 4` | Net, demand (regenerated, seed 42), selected candidates | Per scenario: `netconvert` (base net + `cand.edg.xml` + `cand.con.xml`) then `marouter` UE → `sim/scenarios/<cNN>_macro/{netload.xml, metrics_3600.json}`. Overall: `scenarios_macro.csv` (dT, dQ, dC, L, P, score, veh/h, ranked) |
| 6 | Shortlist | `urban.pick <area> top10` | `scenarios_macro.csv` | Printed list, e.g. `20,0,4,...` |
| 7 | Micro check | `urban.noise <area> --cands <top10> --seeds 42,1,2,3,4 --workers 2` | Same net and demand, 10 candidates, 5 seeds | `sumo` per run (seed 42 reuses `sim/scenarios/`, others `sim/noise/<cNN>_micro_s<seed>/`); `noise_micro.csv` (one row per run, paired with the same seed's baseline). Prints mean ± sd and the verdict |
| 8 | Winner | `urban.pick <area> winner` | `noise_micro.csv` | Best mean score among candidates with a real positive effect |
| 9 | Sets of roads (optional) | `urban.combos <area> --pool 10 --max 4 --workers 4 --micro-seeds 5` | `scenarios_macro.csv` (pool), `candidates.geojson`, net, demand | `combos_macro.csv` (every set tried, synergy), `combos_micro.csv` (final set over 5 seeds); runs in `sim/combos/<set>_<mode>[_s<seed>]/` |
| 10 | Parallel benchmark (optional) | `urban.parallel <area> --n 16 --workers 2,4` | Net, demand, first 16 candidates | `parallel.csv` (wall time, speedup, efficiency, utilisation, throughput, identical to sequential); runs in `sim/bench/p<P>/` |
| 11 | Animation (optional) | `urban.fcd <area> --cands <winner>` | Net, demand, winner | `traffic_base.json`, `traffic_c<NN>.json` (vehicle positions every 2 s, sim time 1200–1800 s), `traffic.json` (index) |
| 12 | Export | `urban.export <area>` | All of the above | `roads.geojson`, `zones.geojson`, `edge_stats.json`, `scenario_stats/<run>.json`, `scenarios.json`, `noise.json`, `combos.json`, `parallel.json`, `data/areas.json` |
| 13 | UI | `npm run dev`, or `npm run build` + `uvicorn urban.api:app --port 8000` | Exported JSON/GeoJSON at `/data/<area>/...` | The 3D interface; its Run tab starts steps 1–12 through `POST /api/jobs` |

Side tool: `urban.isolate <area> --variants ...` takes the net and demand, changes one model setting at a time
against the reference run, and writes `isolate.csv`. It found the zipper merge fix and is not part of a normal run.

Unattended runs: `backend/run_tt_hebbal.ps1` and `backend/run_tt_baiyappanahalli.ps1` run steps 1–12 in order,
log to `data/overnight/tt_<area>_progress.txt` and resume from the last finished step when rerun.

Details of each step: [study_guide_backend.md](study_guide_backend.md).
