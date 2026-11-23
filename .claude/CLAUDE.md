# Project: Parallelized 3D Urban Infrastructure Planning & Traffic Simulation

Semester project. Models a real road network (one Bengaluru locality), simulates traffic, finds bottlenecks,
generates candidate new roads, evaluates each by simulation, ranks them, parallelizes the evaluation,
and shows everything in an interactive 3D interface.

**Source of truth: `idea.md`.** Read the relevant section before starting work on any component.

## Status
- Phase 1 done: `backend/urban/data.py` (`fetch(area)`, `load(area)`, areas in `AREAS`);
  run `cd backend; uv run python -m urban.data <area>`. Output cached in `backend/data/<area>/` (gitignored).
- OSM data is OFFLINE (Overpass servers unreachable from this network): Geofabrik
  `data/osm/southern-zone-latest.osm.pbf` (534 MB) -> one-time `data/osm/bengaluru.osm.pbf` cut (~15 min)
  -> per-area cuts via pyosmium (`clip()`), loaded with `ox.graph_from_xml` / `ox.features_from_xml`.
- Road graph uses bbox padded by `ROAD_PAD` (~1.1 km). Without it the strongly-connected trim drops one-way
  arterials crossing the box edge (lost the entire Hebbal flyover/ORR/Bellary Rd). Self-check asserts arterials exist.
- Hebbal: 3730 nodes, 9374 edges (58 arterial: ORR, Bellary Rd, Hebbal Flyover + ramps), 9140 buildings.
  OSM has in bbox: `railway=construction` "Namma Metro - Phase 2B" (subway) and "Mallige Line" (suburban rail),
  proposed "Red Line (Sarjapur-Hebbal)" and "ORR-West Line (Orange Line)". Not yet extracted as data. Local branch `master`, no commits yet.
- Phase 2 baseline done: `backend/urban/sim.py` (`build_net`, `make_demand`, `run`, `bottlenecks`, `in_box`);
  run `cd backend; uv run python -m urban.sim hebbal`. Outputs in `data/<area>/sim/` (net, through.rou.xml,
  local.trips.xml, baseline/{tripinfo,edges,stats}.xml). No TraCI yet: file outputs, headless `sumo`.
  - Demand = through flows between arterial boundary entry/exit edges (`THROUGH_RATE` 4000 veh/h, 20 pairs)
    + randomTrips local trips weighted `BOX_WEIGHT`x into the study box (`LOCAL_RATE` 2000 veh/h). Seed 42.
    Pure randomTrips was tried first: 89% of time loss landed outside the box and arterials carried <370 veh/h.
  - Rerouting device on (period 60 s) so drivers would use a new road; `--ignore-route-errors`, teleport 300 s.
  - Hebbal baseline: 6000 veh, all arrived, 2 teleports, mean travel 328 s, mean time loss 130 s.
    Top box bottlenecks: ORR (speed 6-11% of limit), Flyover, Service Road, Bellary Rd, flyover ramps.
  - Cost: netconvert ~2-8 s, demand ~11 s, one sumo run ~126 s (matters for Phase 4/5; mesosim is the speed lever).
  - Gotchas: randomTrips `--weights-prefix` files must have one `<edge>` per line (parse_fast is line-based).
  - Real signals (2026-11-21): city cut redone with `BackReferenceWriter(remove_tags=False)`; netconvert uses
    `--tls.guess-signals --tls.join` -> 10 TLS from OSM `highway=traffic_signals`.
  - Calibration (2026-11-21): target = Hebbal flyover main carriageway 3,225 PCU/h morning peak (Bengaluru flyover
    v/c study via Deccan Herald; RITES junction total 26,896 PCU/h not used, mixed-traffic/counting basis differs).
    Surveyed road in OSM = way 377832181, highway=trunk "Hebbal Flyover", 3 lanes, 60 km/h. Other "Hebbal Flyover"
    ways are trunk_link loops (1-3 lanes, 30 km/h, incl. new loop opened 2025-08-18): NOT the calibration edge.
    Through demand split: `FLYOVER_RATE` over pairs whose free-flow path uses that carriageway, `OTHER_RATE` over the
    rest. 15-min run at FLYOVER_RATE=3300 gave 3,084 veh/h; default set to 3450. Env overrides: DURATION,
    FLYOVER_RATE, OTHER_RATE, LOCAL_RATE (use DURATION=900 for sweeps). Cars only, so veh ~ PCU is an approximation.
  - Calibrated full-hour baseline (defaults): 9,083 inserted, 8,859 arrived, 15 teleports, mean travel 422 s,
    mean time loss 200 s, flyover main 3,223 veh/h (target 3,225). sumo = 659 s per run.
    Main carriageway runs at 0.69 x 60 = ~41 km/h vs observed 15-20 km/h (VISSIM study): sim too fast, likely
    cars-only (no two-wheeler/bus mix). Top box bottleneck: way 238204954, unnamed 3-lane one-way tertiary
    frontage (service) road, then new flyover loop 1422993566, ORR.
  - Phase 4 cost (decided 2026-11-21): candidate SCREENING uses mesosim (`run(..., meso=True)`, CLI `--meso`,
    flags `--mesosim --meso-junction-control true`), full hour: 167 s/run vs 659 s micro (3.9x), flyover 3,216 veh/h,
    all 9,252 arrived. Micro vs meso bottleneck ranking agreement is only moderate (Spearman 0.48 over 2,345 box
    edges, top-10 overlap 4/10, top-25 15/25), so VALIDATE the top-k candidates with microsim before reporting.
    DURATION=900 meso = 39 s but underloads (flyover 2,728 veh/h, network still warming up): smoke tests only.
  - Slowness is microsim cost (9k vehicles, rerouting every 60 s, 9.5k edges), NOT a lack-of-real-data issue.
    Real data would improve calibration (speeds too high: 41 vs 15-20 km/h), not runtime.
  - Scaling ALL through traffic 4x (16000 veh/h) was tried: >10 min run, killed for low system memory. Don't.
    User monitors memory themselves now.
- Phase 3 done (2026-11-21): `backend/urban/candidates.py` (`generate(area)`); run
  `cd backend; uv run python -m urban.candidates hebbal`. Writes `data/<area>/candidates.geojson` (WGS84 lines; every
  examined pair with status selected/feasible/rejected:<reason>; cols u, v = SUMO junction ids, length_m, net_dist,
  detour, seed_loss, buildings_hit, road_crossings, worksite_crossings, prescore).
  - Seeds = end junctions of top `HOT_EDGES`=30 box edges by micro-baseline timeLoss. Pairs: 50-600 m straight,
    network distance >= 2x straight both ways. Junctions touching flyover/ramp/_link edges are not connectable.
  - Geometry in SUMO metric XY (`nw.convertLonLat2XY`), Shapely STRtree. Ends trimmed 8 m, 4 m half-width buffer.
  - `data.py` now also writes `construction.geojson` (railway=construction lines: Metro Phase 2B, Mallige Line).
  - Hebbal reality: median straight line hits 22 buildings; metro + Mallige corridors quarter the box (93% of pairs
    cross a worksite), 95% cross an existing road. Strict rules left 3 candidates.
  - USER DECISION: crossings of roads/metro worksite are allowed as grade separations and priced in penalty P;
    hard rejects only for > `MAX_DEMOLISH`=3 buildings or water/park/etc obstacle. Result: 88 feasible, 40 selected
    (`TOP_K`, max 3 per seed) from 16 seeds; 22 demolish nothing; 28 cross the metro worksite.
  - Prescore = (net_dist - straight) x seed time loss: a cheap ranking only, not the Phase 4 score.
- Phase 4 in progress (2026-11-22): `backend/urban/evaluate.py` (`evaluate(area, limit, micro)`); run
  `cd backend; uv run python -m urban.evaluate hebbal [--limit N] [--micro K]`. Regenerates demand (seed 42, full
  DURATION) so baseline and every scenario share it. Each scenario = `netconvert --sumo-net-file net.net.xml` +
  `cand.edg.xml` (cand_f/cand_b, 1 lane each way, 40 km/h) + `cand.con.xml`. The baseline also goes through a plain
  netconvert round trip, for fairness. Meso screen over all selected candidates -> `data/<area>/scenarios.csv`; top K
  re-run on micro -> `scenarios_micro.csv`. Outputs go to `sim/scenarios/<cand>_<meso|micro>/`; the 30 MB net and
  tripinfo are deleted after each run.
  - GOTCHA: a loaded .net.xml keeps its connections, so nothing turns INTO a new edge. Edge-level `<connection>`
    entries are silently ignored. Explicit `fromLane="0" toLane="0"` from each incoming edge at u/v works.
  - Score units: dT % mean travel time, dQ % box edge waiting time, dC % detour removed, L m, P = buildings
    + 0.5 x road crossings + 1 x worksite crossings. `WEIGHTS` = {dT 1, dQ 0.5, dC 0.01, L 0.002, P 0.25}; arbitrary,
    so tune them and report the components too.
  - 15-min smoke test: the top 2 prescore candidates (Bellary Rd trunk junction to residential street) carry
    1,100-1,300 veh/h and make things WORSE (dT -3..-4 %, box waiting about 2x). Braess-like: trunk traffic floods
    a 1-lane shortcut.
  - dT switched to mean_time_loss (2026-11-22). The first kill was really the laptop locking on low battery
    (user), not memory.
  - Full run 2026-11-22 killed after 14/40 candidates (meso ~260-370 s each, slower than 167 s
    alone). The sweep now checkpoints `metrics_<DURATION>.json` per scenario dir, so a restart resumes; c00-c13 and the
    baseline were backfilled from their stats.xml/edges.xml. Partial result: all 14 are worse than baseline
    (dT -0 to -48 %); heavily used shortcuts are the worst (Braess).
  - Meso screen COMPLETE 2026-11-22 (all 40, `scenarios.csv`). Runs took ~460-690 s each (machine under memory
    pressure). Only 3 score positive: c25 (+7.1, dT +5.7 %, 43 veh/h), c22 (+4.6, 286 veh/h, 114 m), c24 (+2.9,
    41 veh/h). Everything carrying 600+ veh/h is much worse (dT -10 to -80 %, Braess). The low-use positives sit
    inside the noise floor: c36-c39 with ~55 veh/h range from -5 to -17 %. c22 is the only plausible real gain.
    Micro validation DONE 2026-11-23 (`scenarios_micro.csv`): base_micro mean travel 392 s, time loss 172.6 s,
    13 teleports, 1,165 s/run. ALL THREE WORSE: c25 dT -14.0 % (41 veh/h), c24 -18.9 % (36 veh/h), c22 -26.7 %
    (276 veh/h); teleports 25-44 vs 13. A 40 veh/h road cannot cost 14 % system-wide, so either noise (rerouting
    chaos) or the new junction leg re-signs right-of-way at u/v for all traffic there. No candidate shows a real gain.
- Phase 5 code (2026-11-23): `evaluate.py --workers P` (ProcessPoolExecutor, one scenario per task; `simulate` takes
  incoming edge ids, not the net). `urban/parallel.py` benchmark (DURATION=900 meso, N=16, P=1,2,4,8, fresh
  `sim/bench/p{P}/`, checks results identical to sequential) -> `parallel.csv`. Not yet run. Machine: 16 cores /
  24 threads, 15.7 GB RAM. Never run two sims at once: `make_demand` rewrites the shared route files in `sim/`.
  - NOISE FLOOR (2026-11-23, `evaluate.py --noise 6 --workers 2`, `noise_meso.csv`): meso baseline, same demand,
    SUMO seeds 42-47. Mean time loss 141.4 / 151.5 / 144.7 / 155.3 / 158.2 / 171.3 s: std 7.6 % in dT, 19.4 % in
    dQ. Seed 42 (the baseline every candidate was compared to) is the LUCKIEST draw, about 8 % below the seed mean,
    so single-seed candidates look systematically worse. Every meso positive (max +5.7 %) and the micro -14..-19 %
    on ~40 veh/h roads are inside noise. Only the big Braess losses (-30 % and worse, 600+ veh/h) are real.
    Detecting a 3 % effect at this variance needs ~40 seeds per scenario: single-seed ranking is meaningless.
    2 workers ran ~480-540 s per meso run.
    Rerouting is NOT the noise source (2026-11-23, `REROUTE=0 ... --noise 6`, `noise_meso_no_reroute.csv`): with
    free-flow routes only, std got WORSE (dT 8.5 %, dQ 47.6 %), 34-59 teleports, only 8,361-9,231 of 9,252 arrived
    (gridlock), 1,000-2,000 s per run. Likely cause (unproven): the network runs near capacity (flyover calibrated
    to its survey flow), so small random differences grow into different queues. Note mean_time_loss counts arrived
    vehicles only, so a run with more stuck vehicles can look better.
  - USER DECISION 2026-11-23: model traffic as a stream. Screening = MACRO static assignment, `sim.assign()` =
    SUMO `marouter --assignment-method UE`, deterministic (repeat runs byte-identical), ~2 min/scenario (only 31 s is
    routing). `evaluate.py` default `--screen macro` (meso still via `--screen meso`), `--micro K` default 0.
    Results `scenarios_macro.csv`; old meso screen renamed `scenarios_meso.csv`. Per-edge `netload.xml` kept in each
    scenario dir (for the 3D heatmap). Macro metrics: delay per edge = q * tt * (1 - speedRelative); mean_time_loss
    = total delay / vehicles. Macro baseline: mean travel 651 s (vs micro 392), flyover way 377832181 carries
    2,691 veh/h (target 3,225) at v/c 112 % and 21 % of limit (~13 km/h, observed 15-20). Only 23 of 6,281 loaded
    edges are over capacity, worst = arterial ENTRY edges (4,052 veh/h, v/c 169 %): demand exceeds entry capacity,
    same in every scenario, so it inflates the baseline and dilutes dT %. marouter capacity ~800 veh/h/lane on the
    flyover vs survey 1,100. Smoke test: c00/c01 dT +3.0/+2.4 % system-wide but dQ -46/-55 % (1,500-1,700 veh/h
    pulled into the box).
  - MACRO SCREEN COMPLETE 2026-11-23 (40 candidates, 4 workers, median 162 s/run vs ~120 s alone). Clear trade-off,
    no noise: dT vs candidate flow corr +0.72, dQ vs flow -0.92. Big shortcuts (c02/c08/c33/c09/c13, 1,900-2,500
    veh/h) cut network delay 6.4-7.5 % but add ~40 % box delay (through traffic diverted onto local streets).
    Only 13/40 improve both. Winners: c23/c22/c21 (all from junction 2408528584, 108-126 m, ~430 veh/h):
    dT +1.1 %, dQ +3.0 %, score 2.3-2.9. c22 was also the meso screen's only plausible gain. Next tier c24/c25/c03/c04
    (~60 veh/h): dT +0.2 %, dQ +1.6 %.
  - Merge 2026-11-23 (branch `feat/macro` on top of PR #1): `evaluate.py --noise` removed, use `urban.noise`
    (paired multi-seed). `simulate(..., mode, seed)` takes "macro"|"meso"|"micro" (noise.py updated). export.py
    reads scenarios_<macro|meso|micro>.csv and adds a "macro" key; the UI still reads "meso" (switching it to macro
    is a frontend task). export's per-scenario heatmap stats read edges.xml only, not macro netload.xml (TODO).
    ALL macro/meso numbers above are on the OLD net (before the untagged-speed fix below).
  - OPEN: c03/c04 carry about 25 veh/h yet show dT -3.4 %, so the meso noise floor from rerouting chaos is a few %.
    Consider multiple seeds. c02/c07 report a mean duration identical to baseline (357.97) while timeLoss/routeLength
    differ. Suspect; dT may be better taken from mean_time_loss.
  - Net is RIGHT-hand traffic (no `--lefthand` at netconvert); India drives on the left. Mirror-image
    approximation; fixing it means rebuild + recalibrate.
- Noise floor (2026-11-23, Mac, `urban.noise`, micro, seeds 42,1,2,3,4, demand fixed): baseline mean time loss
  194.2 s, sd 12.9 (6.7 %), range 173.7-209.3; seed 42 is the luckiest, so single seed-42 micro runs overstate harm.
  Paired over 5 seeds: c22 dT -12.6 % +- 12.0 (real effect, worse, Braess, ~278 veh/h); c24 -1.4 +- 12.6 and c25
  -4.0 +- 5.7 (within noise). 2 lanes/60 km/h variant (`CAND_LANES=2 CAND_KMH=60`, dirs `*_l2v60_*`): c24 +0.6 +- 11.2
  (noise), c25 -6.6 +- 2.4 (real, worse). Usage stays ~40 veh/h either way. `urban.export` writes `noise.json`; the
  UI shows it on candidate cards. Verdict rule: |mean| > 2 standard errors, n > 2.
- Untagged speed fix (2026-11-23, `sim.py` `UNTAGGED_KMH`/`untagged_speeds`): the top "bottleneck" 238204954 was an
  artefact; untagged tertiary got netconvert's 80 km/h, faster than the 60 km/h flyover, so ~714 veh/h of Bellary Rd
  through traffic cut down the service road. Untagged ways now get the median tagged maxspeed of their type in this
  net (res 30, sec 40, tert 50, trunk 60, links 30), as a 2nd netconvert pass (via --type-files, --ramps.guess
  dropped 10 ramp edges). New baseline: flyover 3,241 veh/h, mean time loss 133 s, shortcut 135 veh, worst = flyover
  loop 1422993566 merging into Bellary Rd. All earlier candidate/noise results are on the OLD baseline (archived in
  data/hebbal/archive_v1_default_speeds/); rerun candidates -> evaluate -> noise. See HANDOVER.md.
- SUMO 1.28.0 installed via winget at `C:\Program Files (x86)\SUMO\` (SUMO_HOME set machine-wide;
  shells opened before install may not see it or PATH). `traci` + `sumolib` in backend deps.

## Deferred ideas (pick up only if needed)
- Live traffic speeds for calibration/validation (user: "we'll look at this if needed", 2026-11-21).
  OSM has NO traffic data (static map only). Live speeds come from commercial APIs: TomTom Traffic Flow
  (free tier, easiest), HERE Traffic (free tier), Google Routes (paid, storage restricted), Mapbox.
  They give per-segment speeds/travel times, NOT vehicle counts; flow target still from published surveys.
  Value: second calibration target (flow alone is ambiguous between free-flow and jammed), per-segment coverage
  of ORR/Bellary Rd/ramps, time-of-day profile, current conditions (surveys predate metro works), and a
  measurable validation claim for the report. Caveat: real mix is mostly two-wheelers, sim is cars only.
  Needs an API key in a gitignored `.env` plus a small sampler script.

## Pipeline (idea.md §11)
1. Data acquisition: OSM roads, building footprints, water/parks/restricted zones -> road graph G=(V,E).
2. Baseline analysis: connectivity, traffic demand, baseline sim, baseline metrics.
3. Candidate generation: pick endpoint pairs (u,v) of existing nodes near congestion; reject via geometry
   (crosses buildings/water/restricted, too long, bad geometry, duplicates existing road, steep terrain).
4. Scenario evaluation: for each feasible c_i, simulate G ∪ {c_i}, compare to baseline, score, rank.
5. Parallelization: sequential vs parallel scenario eval; measure speedup and efficiency.
6. 3D visualization: city, roads, traffic, heatmaps, candidate roads, before/after.
7. Integration into one app.

## Key formulas
- Candidate score: S(c_i) = w1·ΔT + w2·ΔQ + w3·ΔC − w4·L − w5·P
  (ΔT travel-time reduction, ΔQ queue/congestion reduction, ΔC connectivity gain, L length/cost proxy, P feasibility penalty; weights configurable).
- Speedup S = Ts / Tp. Efficiency E = S / P (P = workers).

## Course components
- PAGP (parallel computing): independent candidate scenarios evaluated concurrently. Python multiprocessing first;
  CUDA/Numba optional. Report speedup, efficiency, scaling, throughput, result consistency vs sequential.
- CGVR (graphics): Three.js 3D city as the decision-support UI, not a standalone visualization.

## Stack
- Data/graph: OpenStreetMap, OSMnx, NetworkX, GeoPandas, Shapely.
- Simulation: SUMO controlled via TraCI (simplified model acceptable).
- Backend: Python + FastAPI. Frontend: Next.js/React + Three.js. Deployment: Docker.
- Choices may change based on implementation complexity (idea.md §10).

## MVP scope (idea.md §12)
In: one small area, simplified demand, baseline sim, congestion detection, algorithmic candidates, basic spatial
constraints, candidate sim + ranking, parallel eval, 3D view, before/after comparison.
Out: metro-scale sim, population forecasting, detailed driver behaviour, legal design compliance,
real construction costs, guaranteed constructibility.

## Decisions log
Append dated decisions here (locality chosen, sim model, repo layout, etc.).
- 2026-11-20: OSM source = offline Geofabrik extract, not Overpass (user: "definite hit rather than hit and trial").
- 2026-11-21: Candidate crossings of existing roads and the metro worksite = grade-separated with a cost penalty, not
  rejected (user picked "Penalty, <=3 bldgs"). Phase 4 P must include buildings_hit, road_crossings, worksite_crossings.
- 2026-11-21: Sim = SUMO microsim via subprocess + XML outputs (TraCI deferred to live viz). Bottlenecks ranked by
  edgeData timeLoss inside the study box only (padding exists for connectivity, not for analysis).
- 2026-11-20: Backend = uv project in `backend/`, Python 3.12, package `urban/`.
- 2026-11-20: Primary study area = Hebbal (flyover junction + metro interchange under construction), bbox
  (77.5890, 13.0290, 77.6050, 13.0430). Chosen by user for a real planning context. Koramangala kept as dev/test area.
- 2026-11-20: Dev/test locality = Koramangala bbox (77.6150, 12.9250, 77.6300, 12.9400), drive network,
  trimmed to the largest strongly connected component (441 nodes, 1101 edges, 4084 buildings, 30 obstacles).
