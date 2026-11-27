# Backend study guide

This guide walks through the backend from raw map data to a ranked list of road proposals. It explains what each
step does, why it was built that way, and which numbers came out. Read it alongside the code in `backend/urban/`:
every section names the module and the constants that matter.

Contents

1. [The question the backend answers](#1-the-question-the-backend-answers)
2. [Data sources](#2-data-sources)
3. [Phase 1: data acquisition (`urban.data`)](#3-phase-1-data-acquisition-urbandata)
4. [Phase 2: network, demand and baseline (`urban.sim`)](#4-phase-2-network-demand-and-baseline-urbansim)
5. [Baseline metrics: what was measured and why](#5-baseline-metrics-what-was-measured-and-why)
6. [Calibration, model fixes and validation](#6-calibration-model-fixes-and-validation)
7. [Phase 3: candidate generation (`urban.candidates`)](#7-phase-3-candidate-generation-urbancandidates)
8. [Phase 4: building and scoring a scenario (`urban.evaluate`)](#8-phase-4-building-and-scoring-a-scenario-urbanevaluate)
9. [The macro screen](#9-the-macro-screen)
10. [The micro check](#10-the-micro-check)
11. [Why two stages, and how they disagree](#11-why-two-stages-and-how-they-disagree)
12. [Sets of roads (`urban.combos`)](#12-sets-of-roads-urbancombos)
13. [Phase 5: parallel evaluation (`urban.parallel`)](#13-phase-5-parallel-evaluation-urbanparallel)
14. [Phase 7: exports and the API](#14-phase-7-exports-and-the-api)
15. [Results](#15-results)
16. [Limitations](#16-limitations)
17. [Likely questions](#17-likely-questions)
18. [Glossary](#18-glossary)

---

## 1. The question the backend answers

> Given a real congested area, which short new road link (if any) would reduce delay, and how sure are we?

The backend answers it in five stages:

```text
OSM extract ──► road network + buildings + no-build zones           (Phase 1, urban.data)
            ──► calibrated peak-hour simulation = BASELINE          (Phase 2, urban.sim)
            ──► candidate roads near the worst bottlenecks          (Phase 3, urban.candidates)
            ──► MACRO screen: every candidate, fast, deterministic   (Phase 4, urban.evaluate)
            ──► MICRO check: top 10, 5 random seeds each, paired     (Phase 4, urban.noise)
            ──► optional: best SET of roads                          (urban.combos)
            ──► exports for the 3D UI                                (urban.export)
```

All scenario runs go through one process pool (Phase 5), so the same code gives both the results and the speedup
measurements.

Stack: Python 3.12 managed with `uv`, OSMnx / NetworkX / GeoPandas / Shapely / pyosmium for map data, SUMO 1.28
(`netconvert`, `marouter`, `sumo`) for simulation, pandas for result tables, FastAPI for the app server.

---

## 2. Data sources

| Source | What it gives | How it is used | Where |
|---|---|---|---|
| **OpenStreetMap**, Geofabrik extract `southern-zone-latest.osm.pbf` (534 MB) | Roads with type, lanes, one-way, maxspeed; traffic signal nodes; building footprints; water, parks, hospitals, schools, military, cemeteries; `railway=construction` (Metro Phase 2B, Mallige Line, Metro Phase 2A); in-service rail; vacant land (brownfield, greenfield, grass, scrub) | The road network, the spatial constraints, and the 3D city | `urban.data` |
| **Hebbal flyover volume/capacity study** (Bengaluru, reported by Deccan Herald) | Morning-peak flow of **3,225 PCU/h** on the flyover's 3-lane main carriageway (capacity 3,300) | Calibration target for Hebbal demand | `sim.CALIB` |
| RITES junction count, Hebbal | 26,896 PCU/h for the whole junction | Not used: mixed traffic and a different counting basis | noted only |
| VISSIM study of the Hebbal flyover | Observed speeds of 15–20 km/h on the main carriageway | Sanity check on simulated speeds | noted only |
| **B-SMILE Yeshwanthpur – KR Puram elevated corridor DPR** (Infra Support Engineering), count TVC 02 near NGEF, Old Madras Road, 20 May 2025 | 200,183 PCU/day, peak 21,789 PCU/h (V/C 4.04), direction split 53:47, design capacity 5,400 PCU/h two-way | Baiyappanahalli calibration attempt (see §6.4) | `sim.py` comments |
| **TomTom Traffic Flow API** (`flowSegmentData`), snapshot 2026-11-27, 18:34–18:35 (evening peak) | Current and free-flow speed per sampled road segment | Validation of simulated speeds; optional free-flow speed patch (`SPEEDS=tomtom`) | `urban.live`, `urban.validate`, `backend/tomtom/tomtom_live_2026-11-27.json` |
| SUMO typemap `osmNetconvert.typ.xml` | Default speeds per road type for untagged OSM ways | Replaced by local medians (§6.2) | `sim.untagged_speeds` |

Why offline OSM and not the Overpass API: the Overpass servers were unreachable from the project network, and a
local extract gives the same data every time ("a definite hit rather than hit and trial", decision of 2026-11-20).

What OSM does **not** have: traffic counts, speeds or building heights. Counts come from the published surveys,
speeds from TomTom, and building heights in the UI are illustrative.

---

## 3. Phase 1: data acquisition (`urban.data`)

Command: `uv run python -m urban.data <area>`

1. **City cut (once).** pyosmium clips the regional extract to Bengaluru (`CITY_BBOX`) and writes
   `data/osm/bengaluru.osm.pbf`. This takes about 15 minutes. Node tags are kept (`remove_tags=False`), so
   `highway=traffic_signals` survives for the signal model.
2. **Area cut.** Each study box in `AREAS` (west, south, east, north) is clipped twice:
   - **roads** with the box padded by `ROAD_PAD` = 0.01° (about 1.1 km), and only drivable ways (the same filter as
     OSMnx `network_type="drive"`);
   - **features** (buildings, obstacles, railways, land use) with the exact box.
3. **Graph.** OSMnx builds a directed graph, trims it to the padded box and keeps the **largest strongly connected
   component**, so every origin can reach every destination.
4. **Layers written:** `roads.osm`, `roads.graphml`, `buildings.geojson`, `obstacles.geojson`,
   `construction.geojson`, `rail.geojson` (at-grade rail only, not bridges or tunnels), `vacant.geojson`.

Why the padding matters: one-way arterials that cross the box edge become dead ends inside a tight box, and the
strong-connectivity trim then deletes them. Without padding the whole Hebbal flyover, ORR and Bellary Road vanished.
The self-check asserts that arterial roads survive.

| Area | Box (W, S, E, N) | Size | Network | Buildings |
|---|---|---|---|---|
| Hebbal | 77.5890, 13.0290, 77.6050, 13.0430 | ~1.7 × 1.5 km | 3,730 nodes, 9,374 edges, 58 arterial | 9,140 |
| Baiyappanahalli | 77.6500, 12.9850, 77.6720, 13.0030 | ~2.4 × 2.0 km | 4,323 nodes, 10,525 edges, 149 arterial | 5,109 |
| Koramangala (test) | 77.6150, 12.9250, 77.6300, 12.9400 | ~1.6 × 1.7 km | 441 nodes, 1,101 edges | 4,084 |

`hebbal_tt` and `baiyappanahalli_tt` are the same boxes with TomTom free-flow speeds, in their own folders (§6.5).

---

## 4. Phase 2: network, demand and baseline (`urban.sim`)

Command: `uv run python -m urban.sim <area>` (add `--meso` for a mesoscopic baseline).

### 4.1 Network (`build_net`)

`netconvert` turns `roads.osm` into a SUMO network with these options:

| Option | Why |
|---|---|
| `--lefthand` | India drives on the left |
| `--ramps.guess`, `--junctions.join`, `--roundabouts.guess` | OSM draws one junction as many nodes; joining them gives realistic junction control |
| `--tls.guess-signals --tls.join --tls.default-type actuated` | Uses OSM `highway=traffic_signals` nodes; signal clusters become one controller (Hebbal: 10 signals) |
| `--remove-edges.isolated --keep-edges.components 1` | Drops fragments a vehicle could never leave |

A **second netconvert pass** (`untagged_speeds`) then sets realistic speeds on untagged ways and turns the merges in
`ZIPPER_NODES` into zipper junctions (§6.2, §6.3).

### 4.2 Demand (`make_demand`)

Two parts, both fixed by seed 42, so the baseline and every scenario see exactly the same trips:

- **Through traffic** (`through.rou.xml`): flows between every arterial entry edge (no incoming edge) and every
  arterial exit edge (no outgoing edge). Pairs whose free-flow route uses the calibration road get `FLYOVER_RATE`
  in total, the others get `OTHER_RATE`. This lets the surveyed road be loaded to its survey volume without
  overloading every other road.
- **Local traffic** (`local.trips.xml`): SUMO `randomTrips.py` at `LOCAL_RATE` = 2,000 veh/h, with origins and
  destinations weighted `BOX_WEIGHT` = 10× inside the study box, minimum trip 300 m.

Why not random trips alone: the first attempt put 89 % of the delay outside the study box and the arterials carried
fewer than 370 veh/h. Real peak traffic at these junctions is dominated by through movement on the arterials.

### 4.3 Simulation (`run`)

`sumo` runs headless for one departure hour (`DURATION` = 3,600 s) and up to 2 hours of clearance:

| Setting | Value | Why |
|---|---|---|
| Rerouting device | every vehicle, every 60 s | Drivers must be able to discover a new road; without it no one would use a candidate |
| `--time-to-teleport` | 300 s | A vehicle stuck 5 min is removed and counted; stops one gridlock from freezing the run |
| `--ignore-junction-blocker` | 20 s | Breaks circular waits on the local all-minor ring roads |
| `--seed` | 42 by default | Driver randomness; varied in the micro check |
| Outputs | `tripinfo.xml`, `stats.xml`, `edgeData` (`edges.xml`) | Per-trip and per-road metrics |

`assign()` is the macro alternative (§9). `bottlenecks()` ranks the study-box edges by total time loss.

---

## 5. Baseline metrics: what was measured and why

The baseline is the network as it is today, under the calibrated demand. Every candidate is judged as a change
against it, so the choice of metric decides the ranking.

### 5.1 System-wide metrics (per run)

| Metric | Definition (micro) | Why it was chosen |
|---|---|---|
| **Mean time loss per trip** (headline, basis of ΔT) | mean of `tripinfo.timeLoss` over arrived vehicles: time lost against driving the same route at the desired speed | Measures **delay**, not trip length. A new road can change route lengths, so mean travel time mixes delay with distance. An early meso run also returned the same mean duration (357.97 s) for different scenarios, while time loss differed. |
| Mean travel time, total travel time | mean and sum of `tripinfo.duration` | Reported for context and for the calibration story |
| Mean waiting time | mean of `tripinfo.waitingTime` (time below 0.1 m/s) | Reported; queue-level detail comes from the per-edge figure below |
| Loaded / inserted / arrived | from `stats.xml` and `tripinfo.xml` | Health check. A run with many stuck vehicles can look better because time loss counts arrived vehicles only. |
| Teleports | `stats.xml` | Gridlock indicator; a candidate that doubles teleports is suspect even if delay drops |

### 5.2 Study-box metrics

| Metric | Definition | Why |
|---|---|---|
| **Study-box queueing** (basis of ΔQ) | sum of edge `waitingTime` over edges inside the study box, plus the candidate edges | A road can cut network delay while flooding local streets with diverted through traffic. ΔQ catches that. |
| Bottleneck ranking | study-box edges sorted by edge `timeLoss`, with speed as a share of the limit | Seeds the candidate search (§7) and finds model artefacts (§6) |
| Calibration road flow | max hourly `entered` on the surveyed road | Compared with the survey |

Only the study box is analysed. The padding exists for connectivity and to load the arterials realistically.

### 5.3 Macro equivalents

Macro has no vehicles, only flows, so the same names are computed from `netload.xml`:

- edge delay = q · tt · (1 − speedRelative), where q = vehicles on the edge, tt = its travel time and
  speedRelative = free-flow time / travel time;
- mean time loss = total edge delay / number of vehicles;
- study-box queueing = the same edge delay summed over box edges;
- teleports = 0 by definition.

### 5.4 Baseline values

| | Hebbal micro (seed 42) | Hebbal macro | Baiyappanahalli micro (seed 42) | Baiyappanahalli macro |
|---|---|---|---|---|
| Vehicles arrived | 8,831 | 8,830 | 5,807 | 5,800 |
| Teleports | 7 | 0 | 44 | 0 |
| Mean travel time | 343.9 s | 700.2 s | 786.1 s | 629.0 s |
| Mean time loss | 88.0 s | 449.6 s | 359.5 s | 286.8 s |
| Calibration road | 3,186 veh/h (target 3,225) | | ~1,000 veh/h (target 2,860, not reached) | |
| Over 5 seeds | 87.1 s, sd 4.7 % | deterministic | 316.4 s, sd 18.3 % | deterministic |

Macro and micro baselines are on different scales (macro has no queue dynamics and its own delay function). A
candidate is therefore only ever compared with the baseline from the **same** model and the **same** seed.

---

## 6. Calibration, model fixes and validation

### 6.1 Calibration (Hebbal)

The surveyed road is OSM way 377832181, `highway=trunk` "Hebbal Flyover", 3 lanes, 60 km/h. The other ways named
"Hebbal Flyover" are loops and ramps and are not the surveyed carriageway. `FLYOVER_RATE` was swept; with
left-hand traffic and the zipper merge, the default **3,030 veh/h** gives **3,186 veh/h** on the flyover against
the 3,225 PCU/h target (within 1.2 %). The fleet is cars only, so vehicles ≈ PCU is an approximation.

### 6.2 Untagged speeds (an artefact found and fixed)

The worst "bottleneck" of an early baseline was an unnamed tertiary service road (way 238204954). Untagged OSM ways
had received netconvert's defaults (tertiary 80 km/h, secondary 100 km/h), so the service road looked faster than
the 60 km/h flyover and rerouting sent ~714 veh/h of Bellary Road traffic down it. Untagged ways now get the median
maxspeed tagged on the same road type in the area (residential 30, secondary 40, tertiary 50, trunk 60, links
30 km/h). This is applied as a second pass because changing speeds in the first pass changes how netconvert guesses
ramps, which dropped 10 ramp edges including the surveyed flyover segment.

### 6.3 Junction fixes (`urban.isolate`)

`urban.isolate` changes one thing at a time against the same reference run (same demand, same seed). On Hebbal:

| Variant | Mean time loss | Teleports | Finding |
|---|---|---|---|
| Reference | 193 s | 38 | |
| Car gap 1.0 m | 173 s | 30 | Moderate roads speed up; the stalls do not move |
| Two-wheeler / car / bus mix | 164 s | 7 | Same; also lowers flyover flow, would need PCU recalibration |
| **Zipper merge at node 13052245180** | **101 s** | **7** | The new flyover loop never found a gap as a priority merge into 3-lane Bellary Road |
| All signals actuated | 220 s | | Worse |
| Zipper + junction blocker + mix | 89 s | 8 | |

Conclusion: the true stalls were junction topology, not driver parameters. The **zipper baseline** was adopted
(88 s, 7 teleports). One stall is known and not fixed: the ORR signal segment 1073384218#0 stays at 3–4 km/h in
every variant.

### 6.4 Baiyappanahalli calibration (not achieved)

The DPR's peak of 21,789 PCU/h is far more than a 6-lane road can carry, so the road was treated as saturated, with
a target of 5,400 × 53 % = 2,860 PCU/h in the busier direction. The simulated Old Madras Road plateaued around
1,850–1,950 veh/h whatever the demand, capped by a netconvert-guessed 39/90 s signal split and a 2-lane OSM stretch
ending at a pedestrian signal. Loading it to the survey level made queues grow all hour (501 teleports). The adopted
demand is the stable level `FLYOVER_RATE` 1,830 + `OTHER_RATE` 1,970 veh/h. **Baiyappanahalli results are
therefore relative: they rank candidates under one consistent demand, not a calibrated peak.**

### 6.5 Speed validation against TomTom (`urban.live`, `urban.validate`)

`urban.live` samples one point per major road segment (≥ 120 m apart) and stores TomTom's current and free-flow
speeds. `urban.validate` compares them with the micro baseline's per-edge speeds.

| Hebbal, 24 sampled roads | Default net | TomTom free-flow net (`hebbal_tt`) |
|---|---|---|
| Mean speed, sim vs real | 43.3 vs 16.8 km/h | **20.0 vs 16.8 km/h** |
| Bias / mean absolute error | +26.5 / 26.5 km/h | +3.2 / 5.8 km/h |
| Roads within 10 km/h | 2 / 24 | 18 / 24 |

The default net uses posted limits, while real free flow in Bengaluru is 22–28 km/h. The simulation finds the right
corridors (Bellary Road; Old Madras Road is the sim's worst road in Baiyappanahalli), but drives them too fast. The
patch (`SPEEDS=tomtom` / `<area>_tt`) gives sampled edges TomTom's free-flow speed and scales every other edge by its
road type's median ratio. The presentation uses the default net; the full re-evaluation on `hebbal_tt` and
`baiyappanahalli_tt` is running unattended (`backend/run_tt_*.ps1`).

---

## 7. Phase 3: candidate generation (`urban.candidates`)

Command: `uv run python -m urban.candidates <area>` → `data/<area>/candidates.geojson` (every examined pair, with
its status and the reason for any rejection).

### 7.1 Algorithm

1. **Seeds.** Take the `HOT_EDGES` = 30 study-box edges with the highest baseline time loss. Their end junctions
   are the seeds, each weighted by the time loss of its hot edges.
2. **Connectable junctions.** Junctions touching a flyover, ramp or `_link` edge are excluded (`NO_CONNECT`):
   a new at-grade road cannot join an elevated structure.
3. **Pairs.** Pair each seed with every connectable box junction where
   - the straight line is **50–600 m** (`MIN_LEN`, `MAX_LEN`), and
   - the current network distance is **≥ 2×** the straight line in both directions (`DETOUR`), so the link removes a
     real detour (Dijkstra on a NetworkX copy of the SUMO graph).
4. **Geometry tests** in SUMO's metric XY with Shapely `STRtree` indexes. The line is trimmed 8 m at each end
   (endpoints sit on existing roads) and buffered 4 m each side (`ROAD_HALF_WIDTH`).
5. **Selection.** Feasible pairs are sorted by **prescore** = (network distance − straight length) × seed time loss.
   At most 3 per seed (`MAX_PER_SEED`, for diversity) and 40 in total (`TOP_K`) go to Phase 4.

### 7.2 Feasibility rules

| Condition | Outcome | Reason |
|---|---|---|
| Cuts more than 3 buildings (`MAX_DEMOLISH`) | `rejected:building` | Demolition limit |
| Touches water, park, hospital, school, military, cemetery, reservoir | `rejected:obstacle` | No-build zones |
| Crosses in-service rail at grade, unless the crossing is on vacant land | `rejected:rail` | Level crossings on a main line are not acceptable |
| Crosses an existing road | allowed, `road_crossings` | Built as a bridge or underpass; priced in P |
| Crosses the metro / suburban rail works | allowed, `worksite_crossings` | Priced heavily in P; running alongside is free |
| Crosses a flyover or ramp | allowed, `flyover_crossings` | Needs a third level or deep underpass; priced like the metro |

Crossings are allowed because Hebbal is quartered by the metro and Mallige corridors: 93 % of pairs crossed a
worksite and 95 % crossed a road. Strict rules left 3 candidates. The decision (2026-11-21) was to price crossings
in the penalty P instead.

### 7.3 Counts

| | Pairs examined | Building | Obstacle | Rail | Feasible | Selected |
|---|---|---|---|---|---|---|
| Hebbal | 1,626 | 1,477 | 20 | 84 | 45 | **22** from 8 seeds |
| Baiyappanahalli | 1,880 | 1,449 | 218 | 131 | 82 | **26** from 13 seeds |

---

## 8. Phase 4: building and scoring a scenario (`urban.evaluate`)

### 8.1 Adding a road to the network (`scenario_net`)

A scenario = the baseline net + one candidate (or a set), via `netconvert --sumo-net-file net.net.xml` with:

- `cand.edg.xml`: two edges (`cand_f`, `cand_b`), **2 lanes each way, 50 km/h** (`DEFAULT_CAND`; other variants via
  `CAND_LANES` / `CAND_KMH`);
- `cand.con.xml`: explicit lane connections from every incoming edge at each end into the new road.

Two details matter:

- **Connections must be explicit.** A loaded `.net.xml` keeps its existing connections, so nothing would turn into
  the new edge. Edge-level `<connection>` entries are silently ignored; lane-level ones (`fromLane="0"`) work.
- **Turn cap.** An entry that turns more than `MAX_TURN` = 135° is not built (U-turns and hairpins would need extra
  lanes or a loop). On Hebbal this drops 23 of 136 entries.

The baseline also goes through the same netconvert round trip with no candidate, so baseline and scenarios differ
only by the new road.

### 8.2 Score

```text
S(c) = w1·ΔT + w2·ΔQ + w3·ΔC − w4·L − w5·P          (idea.md §7)
```

| Term | Definition | Unit | Weight |
|---|---|---|---|
| ΔT | (baseline mean time loss − scenario) / baseline | % delay saved, network-wide | 1.0 |
| ΔQ | (baseline box queueing − scenario) / baseline | % queueing saved in the study box | 0.5 |
| ΔC | 1 − straight length / old network distance | % of the detour removed | 0.01 |
| L | straight length | m | 0.002 |
| P | 1 × buildings + 0.5 × road crossings + 22 × metro crossings + 22 × flyover crossings + 30 × rail-on-vacant-land crossings | cost units | 0.25 |

So one metro or flyover crossing costs 22 × 0.25 = **5.5 score points** and one rail crossing 7.5: a crossing
candidate only wins on a large gain. The weights are a stated planning preference, not a law. The UI exposes them as
sliders, and every component is reported next to the score.

### 8.3 Checkpointing

`simulate()` writes `metrics_<DURATION>.json` into each scenario directory and returns it on a rerun. A killed sweep
(power loss, memory) resumes at the first unfinished scenario. The 30 MB scenario net and `tripinfo.xml` are deleted
after each run to save disk.

---

## 9. The macro screen

Command: `uv run python -m urban.evaluate <area> --workers 4` → `scenarios_macro.csv`

### 9.1 What it is

**Static traffic assignment.** SUMO `marouter --assignment-method UE` treats traffic as flows, not vehicles. It
assigns the same demand (the through flows and local trips) to routes until **user equilibrium**: no driver could
switch to a faster route. Each edge's travel time comes from a volume/capacity function, so a road gets slower as
its flow approaches capacity.

### 9.2 Why it was chosen for screening

| Property | Macro | Meso (earlier screen) | Micro |
|---|---|---|---|
| Time per scenario (full hour) | ~2 min (31 s routing) | 167 s alone, 460–690 s under memory pressure | ~1–20 min (machine, congestion and worker count) |
| Randomness | **none**: identical inputs give byte-identical output | seed sd 7.6 % in ΔT, 19.4 % in ΔQ | seed sd 4.7 % (Hebbal) |
| Junctions, signals, queues spilling back | no | simplified | yes |

The meso screen came first and turned out to be useless for ranking: its seed noise (7.6 %) was larger than every
candidate effect, and seed 42 was the luckiest of six seeds, so single-seed comparisons were biased. Detecting a
3 % effect at that variance would need about 40 seeds per scenario. Turning rerouting off made noise worse (8.5 %),
with gridlock. The decision (2026-11-23) was to screen with a deterministic stream model, where any difference
between two runs is caused by the road and nothing else.

### 9.3 What it found

- Clear trade-off with no noise: ΔT rises with traffic on the new road, ΔQ falls with it (correlations +0.72 and
  −0.92 on the earlier net).
- Big shortcuts (1,000–2,500 veh/h) cut network delay by 2–7 % but add 5–40 % study-box queueing: they pull through
  traffic off the arterials onto local streets.
- A minority improve both, and those make the shortlist.

### 9.4 Limits

- No junction behaviour: a new road meeting a busy priority road costs nothing extra in macro.
- marouter capacity is about 800 veh/h/lane on the flyover against 1,100 surveyed, so arterial entry edges sit at
  v/c up to 169 % in every scenario. That inflates the baseline and dilutes ΔT %.
- Hence: **macro shortlists, micro decides.**

---

## 10. The micro check

Command: `uv run python -m urban.noise <area> --cands <macro top 10> --seeds 42,1,2,3,4 --workers 2`
→ `noise_micro.csv` (one row per run) and `noise.json` via export.

### 10.1 What it is

**Microscopic simulation** with `sumo`: every vehicle is simulated individually with car-following (Krauss) and lane
changing, real junction right-of-way, traffic signals, queues that spill back, rerouting every 60 s and teleports
after 300 s stuck.

### 10.2 Paired multi-seed design

- The **demand stays fixed** (seed 42 in `make_demand`). Only SUMO's `--seed` changes: driver speed factors,
  insertion details, rerouting choices.
- For each seed s in {42, 1, 2, 3, 4}: run the baseline at seed s and each candidate at seed s, and compute ΔT, ΔQ
  and the score **against the baseline of the same seed**. Pairing removes the between-seed variation of the
  baseline itself.
- Seed 42 reuses the runs `urban.evaluate` already made; other seeds go to `sim/noise/`.

### 10.3 Verdict rule

```text
real effect  ⇔  n > 2  and  |mean ΔT| > 2 · sd(ΔT) / √n        (about a 95 % two-sided test)
```

Otherwise the result is "within noise". The UI shows mean ± sd and the verdict on each candidate card, and ranks
the micro view by the 5-seed mean score.

### 10.4 Noise floor

| | Hebbal (zipper baseline) | Baiyappanahalli |
|---|---|---|
| Baseline mean time loss over 5 seeds | 87.1 s, sd 4.7 % | 316.4 s, sd 18.3 % (range 226–363) |
| One run can be off by (2 sd) | ~9 % | ~37 % |

Why a near-capacity network is noisy: small random differences decide whether a queue forms at a saturated merge,
and once it forms it grows. Hebbal's arterials run at their survey flow, Baiyappanahalli's Old Madras Road is
saturated by design.

---

## 11. Why two stages, and how they disagree

Hebbal, micro 5-seed check of the macro top 10 (zipper baseline, before the turn and rail rules):

| Candidate | Macro rank | Micro ΔT | Verdict |
|---|---|---|---|
| c39 (72 m, no crossing) | 5 | +10.2 ± 4.0 % | real, better |
| c27 | 4 | +8.4 % but box queueing +37 % | real, mixed |
| c15 / c16 / c17 | 1–3 | −4.9 / −7.7 / −7.5 % | real, **worse** |
| c11 / c22 (540–560 veh/h) | | −28 / −32 % | real, worse (Braess) |

Macro's top three end at a junction where the new road joins as a minor approach. In macro that merge is free, in
micro it blocks. **Lesson: rank on the micro check of a macro shortlist.** The macro screen still earns its place:
it is 5–10× cheaper, deterministic, and removes the big Braess shortcuts before any micro time is spent on them.

**Braess's paradox** shows up repeatedly: adding a heavily used shortcut makes the network slower, because drivers
choosing their own fastest route overload the junctions at its ends.

---

## 12. Sets of roads (`urban.combos`)

Command: `uv run python -m urban.combos <area> --pool 10 --max 4 --workers 4 --micro-seeds 5`

Greedy forward search on macro: start from the best single road, try adding each remaining pool candidate (in
parallel), keep the best set, and stop when nothing raises the score or at `--max` roads. Members may not share an
endpoint or cross each other. Set score: ΔT and ΔQ from the set's own run; ΔC, L and P summed over the members.
**Synergy** = ΔT(set) − Σ ΔT(member alone); negative means the roads compete for the same traffic. The final set is
then micro-checked over 5 seeds.

- Hebbal: synergy is negative almost everywhere. c09 + c11 saves +11.1 ± 3.7 % delay (real), but scores only +1.9
  (box queueing −8.9 %, metro crossing). Conclusion: **build c11 alone.**
- Baiyappanahalli: c13 + c21 + c22 + c24 saves +19.9 ± 14.7 % (real), score +29.1, about the same as c22 alone
  (+29.7) at four times the construction.

---

## 13. Phase 5: parallel evaluation (`urban.parallel`)

Full justification and analysis: [pagp_cgvr_justification.md](pagp_cgvr_justification.md#part-a-pagp).

- Every scenario is independent: same read-only inputs (base net, demand files, box edge ids, candidate rows with
  their incoming edge ids), its own output directory, no shared state.
- `evaluate.run_all` maps `simulate` over a `ProcessPoolExecutor`, one scenario per task. `urban.evaluate`,
  `urban.noise` and `urban.combos` all use it.
- `urban.parallel` runs the same sweep (baseline + 16 candidates, macro) at P = 1, 2, 4 in fresh directories, checks
  that the result tables are identical to the sequential one, and writes `parallel.csv`.

| P | Wall time | Speedup | Efficiency | Results identical |
|---|---|---|---|---|
| 1 | 1,430 s | 1.00 | 1.00 | yes |
| 2 | 715 s | 2.00 | 1.00 | yes |
| 4 | 395 s | 3.62 | 0.90 | yes |

---

## 14. Phase 7: exports and the API

`urban.export <area>` writes the frontend contract into `data/<area>/` (all geometry WGS84):

| File | Content |
|---|---|
| `roads.geojson` | every SUMO edge: id, name, type, lanes, speed, length, in_box |
| `buildings.geojson`, `zones.geojson`, `construction.geojson` | city layers |
| `candidates.geojson` | every examined pair with status and penalty components |
| `edge_stats.json` | micro baseline per edge: speed, speed_rel, time_loss, entered, waiting, occupancy |
| `scenario_stats/<run>.json` | the same per scenario (`base_macro`, `c11_micro`, ...) for before/after |
| `scenarios.json` | macro and micro rankings plus baseline totals |
| `noise.json`, `combos.json`, `parallel.json`, `traffic*.json`, `live_traffic.json` | micro check, sets, benchmark, vehicle trajectories, TomTom |
| `../areas.json` | the exported areas and their boxes (area switcher) |

`urban.api` (FastAPI) serves these at `/data/<area>/<file>`, serves the built UI from `frontend/dist`, and runs
pipeline steps as jobs (`POST /api/jobs {step, area, args}`). Only one job runs at a time, because SUMO steps share
route files. Arguments are restricted to `[\w.,=-]`, and the step runs as `python -m urban.<step>` without a shell.
Logs go to `data/jobs/`. The Docker image (1.3 GB) bundles the built UI, Python, uv and the SUMO 1.28 wheel.

`urban.fcd` records vehicle positions (SUMO floating car data, every 2 s, sim time 1,200–1,800 s, box + 150 m) for
the baseline and a chosen candidate, for the animation only: its trip metrics are partial and never used for scores.

---

## 15. Results

### Hebbal (final rules: turn cap 135°, rail reject, crossing penalties)

| Candidate | Micro ΔT (5 seeds) | Score | Verdict |
|---|---|---|---|
| **c11** (63 m, crosses Bellary Road only) | **+9.51 ± 4.8 %** | **+8.29** | real gain, **recommended** |
| c09 | +8.33 ± 4.5 % | +2.80 | real gain |
| c07 (crosses the metro works) | +8.48 ± 4.9 % | −14.36 | saves delay, but box queueing worse and penalty high |
| c21 | +3.51 ± 4.4 % | +8.70 | within noise |
| c04, c05, c14, c15, c16, c20 | −3.4 to +2.2 % | | within noise |

The earlier winner (old c39, +9.4 %) entered its end junction through a 137° swing and a 147° near-U-turn. Under the
turn cap that version loses both entries; c11 reaches the same junction with realistic turns and keeps the gain.

### Baiyappanahalli (uncalibrated demand: relative ranking only)

| Candidate | Micro ΔT (5 seeds) | Score | Verdict |
|---|---|---|---|
| **c22** (481741594 → 2411848590) | **+17.12 ± 7.5 %** | **+29.71** | real gain, **recommended** |
| c19 | +16.33 ± 17.5 % | +24.66 | real gain |
| c20 | +15.33 ± 13.8 % | +24.62 | real gain |
| c13, c18, c21, c15, c23, c24, c06 | −3.7 to +14.9 % | | within noise (large spread) |

---

## 16. Limitations

- **Cars only.** Bengaluru traffic is mostly two-wheelers; flows are in vehicles ≈ PCU.
- **Speeds.** The default net drives too fast (43 vs 17 km/h at Hebbal); the TomTom patch fixes the bias but its
  full re-evaluation is not part of the presented results yet.
- **Baiyappanahalli is uncalibrated** (sim road capacity ~32 % below the real one); results are relative.
- **Signals** are netconvert's guesses from OSM signal nodes, not real timing plans. The ORR signal segment at
  Hebbal stays at 3–4 km/h in every variant.
- **Demand** is synthetic: arterial through flows plus box-weighted random local trips, one peak hour.
- **Macro** has no junctions or spillback; it is only a screen.
- **Costs** are proxies (length, buildings, crossings); bridge heights in the UI are illustrative. No terrain,
  utilities, legal design rules or land acquisition.
- **Five seeds** give about ±4 % (Hebbal) resolution; smaller effects cannot be claimed.

---

## 17. Likely questions

**Why not rank on macro alone?** Macro has no junction behaviour. Its top three at Hebbal got worse in micro.

**Why five seeds?** One run can be off by ~9 % at Hebbal (2 sd). Single-seed rankings flipped signs.

**Why time loss and not travel time?** Time loss isolates delay from route length, and meso once returned identical
mean durations for different scenarios.

**Why pair by seed?** The baseline itself moves 4.7 % between seeds. Comparing like with like removes that part.

**Why allow crossings at all?** At Hebbal 93 % of pairs cross the metro works. Rejecting them left 3 candidates;
pricing them in P keeps the trade-off visible.

**What is Braess's paradox here?** A shortcut that attracts 500+ veh/h overloads the junctions at its ends and makes
the whole network slower (c11/c22 at −28/−32 % on the earlier net).

**How do you know the parallel results are correct?** Every parallel round's result table is compared with the
sequential one; they are identical at every worker count because macro is deterministic.

**Why SUMO via subprocess and not TraCI?** Scoring only needs end-of-run files. TraCI adds a socket round trip per
step and would slow every run; it was deferred to a possible live view.

---

## 18. Glossary

| Term | Meaning |
|---|---|
| PCU | Passenger car unit: a car = 1, a two-wheeler ≈ 0.5, a bus ≈ 3 |
| v/c | Volume over capacity |
| Time loss | Time lost against driving the same route at the desired speed |
| Teleport | SUMO removes a vehicle stuck longer than 300 s and moves it ahead |
| Macro / meso / micro | Flows on links / queues per edge / individual vehicles |
| User equilibrium (UE) | No driver can lower their own travel time by changing route |
| Zipper merge | Two streams take turns at a merge instead of one yielding |
| Study box | The analysed area; the road network extends ~1.1 km further |
| Seed | Random seed for SUMO's driver behaviour (demand stays fixed) |
| Prescore | Cheap pre-ranking of feasible pairs: detour length × seed time loss |
