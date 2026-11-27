# Handover: state of the Hebbal pipeline (2026-11-23)

> **2026-11-24 update (Anushruth): see [CHANGES_2026-11-24.md](CHANGES_2026-11-24.md)**: Mac reproduction, Phase 5
> benchmark, macro/micro results in the UI, 3D bridges, vehicle animation, GLSL shaders.

From Anushruth's session, for whoever picks this up next (human or Claude Code: start with "read HANDOVER.md and
continue"). Branch `feat/viz`, PR #1. Project notes in `.claude/CLAUDE.md` are updated too.

## TL;DR
1. **Single runs are not enough.** SUMO's seed alone moves the micro baseline delay by ±6.7 % (173.7–209.3 s over
   5 seeds). The old single-run micro check (seed 42) was the luckiest baseline and overstated how bad c22/c24/c25 were.
2. **Old results (default speeds), 5 seeds, micro:** c22 delay 12.6 % worse (real effect, Braess, ~278 veh/h);
   c24 −1.4 ± 12.6 % and c25 −4.0 ± 5.7 % = no measurable effect. As 2 lanes/60 km/h: c24 still noise,
   c25 6.6 ± 2.4 % worse (real). The candidates attract only ~40 veh/h whatever their size.
3. **The worst jam was a model artefact.** Untagged OSM ways got netconvert's typemap defaults (tertiary 80, secondary
   100 km/h), so the unnamed tertiary service road 238204954 was "faster" than the 60 km/h flyover. Rerouting sent
   ~714 veh/h of Bellary Rd through traffic down it, which jammed merging back into Bellary Rd.
4. **Fixed in `sim.py`** (`UNTAGGED_KMH`, `untagged_speeds()`): untagged ways get the median maxspeed that OSM mappers
   tagged on the same road type in this net (residential 30, secondary 40, tertiary 50, trunk 60, *_link 30 km/h).
   Applied as a 2nd netconvert pass (`--sumo-net-file` + edge file), because `--ramps.guess` depends on speeds and
   setting them via `--type-files` dropped 10 ramp edges including the surveyed flyover segment. Verified: identical
   edge set, lanes, 28,850 connections and 10 TLS; only speeds differ (8,976 edges).
5. **New baseline (micro, seed 42):** flyover 3,241 veh/h (survey 3,225), 8,966 arrived, 20 teleports, mean time loss
   133 s (was 200). Service-road shortcut 714 → 135 veh; Bellary Rd carriageway 2,936 → 3,610. Worst bottleneck is
   now the new flyover loop 1422993566 merging into Bellary Rd (377 veh, speed 23 % of limit). sumo took 103 s.

## Not done yet (in order)
1. **Merge Anirudh's local fixes** with this branch before any long run.
2. Optional calibration: flyover main runs 55 km/h vs 15–20 km/h observed. Proposed: add a `TAU` (car-following
   headway) setting and sweep 1.0/1.5/2.0/2.5 s so SUMO's flyover capacity ≈ the surveyed 3,300 PCU/h, then use
   speed as the check (do not tune speed directly). About 2 min per run now.
3. Rerun on the new baseline: `urban.candidates` → `urban.evaluate --workers 2` → `urban.noise --cands <top 3>` →
   `urban.export`. Old results are archived in `backend/data/hebbal/archive_v1_default_speeds/` (local only,
   data/ is gitignored); the frontend still shows the old exports until the new export runs.
4. Report: present c22 as a Braess case caught by the tool; use 5-seed means, never single runs; limitations:
   cars only (no two-wheelers/buses), right-hand traffic, merge behaviour at priority junctions.

Rejected along the way (don't redo): switching study area to get positive results (cherry-picking); bypass
candidates around 238204954 (would have "fixed" the artefact in point 3); a second flyover (Bellary Rd flows at ~90 %).

## What changed in code (this branch, on top of PR #1)
| File | Change |
|---|---|
| `backend/urban/sim.py` | untagged speed fix (above); `build_net` writes `raw.net.xml`, then `net.net.xml` |
| `backend/urban/evaluate.py` | `CAND_LANES`, `CAND_KMH` env settings (default 1 lane, 40 km/h = unchanged); `VARIANT` tag; `seed` param |
| `backend/urban/noise.py` | multi-seed paired test; `summary()` shared with export; variant runs in `sim/noise/<cand>_<variant>_<sim>_s<seed>` |
| `backend/urban/export.py` | writes `noise.json` from every `noise_<sim>[_l<lanes>v<kmh>].csv` with ≥ 2 seeds |
| `frontend/` | candidate cards show repeated-run results (mean ± sd, real effect / no effect) per variant; ranking tags |

## Commands (Mac; on Windows SUMO_HOME is set machine-wide)
```bash
cd backend
export SUMO_HOME=$PWD/.venv/lib/python3.12/site-packages/sumo   # Mac: SUMO from the eclipse-sumo pip wheel
uv run python -m urban.sim hebbal                                # baseline + calibration check
uv run python -m urban.candidates hebbal
uv run python -m urban.evaluate hebbal --workers 2               # meso screen of 40 + micro top 3
uv run python -m urban.noise hebbal --cands 22,24,25 --workers 2 # 5 seeds; prints nothing until done
CAND_LANES=2 CAND_KMH=60 uv run python -m urban.noise hebbal --cands 24,25 --workers 2
uv run python -m urban.export hebbal                             # then: cd ../frontend && npm run dev
```
8 GB machine: keep `--workers 2` and run one SUMO job at a time.

## Next: a second area (Baiyappanahalli - Benniganahalli) — teammate task (2026-11-25)
Area changed from RR Nagar (user, 2026-11-25): Hebbal's problem is a flyover junction; this one is a network cut by
rail lines and yards, with heavy congestion (Tin Factory / ORR junction) and a real access question (SMVT terminal,
Baiyappanahalli metro). The code runs on any area inside the offline city cut (`CITY_BBOX` in `urban/data.py`).
`ZIPPER_NODES` ids missing from an area are skipped, and an area without the Hebbal flyover gets one uncalibrated
through rate (`OTHER_RATE` over all arterial pairs). Tested on Koramangala.

Done: box `"baiyappanahalli": (77.6500, 12.9850, 77.6720, 13.0030)` in `AREAS` (~2.4 x 2.0 km, from Baiyappanahalli
metro 77.6524,12.9907 to Benniganahalli metro / Tin Factory 77.6685,12.9965, incl. the whole Benniganahalli Flyover);
`urban.data baiyappanahalli` ran: 4,323 nodes, 10,525 edges, 149 arterial (Swamy Vivekananda Rd = Old Madras Rd
here, ORR NH44/48/75, Benniganahalli Flyover), 5,109 buildings, 40 obstacles. construction.geojson = Metro Phase 2A
(ORR Blue Line) + Mallige / Kanaka suburban rail, so the worksite crossing rule applies as-is.

To do (in this order, one SUMO job at a time):
1. DONE (2026-11-25, user): in-service rail at grade (`railway=rail|narrow_gauge`, not bridge/tunnel) is a hard
   reject (`rejected:rail`) unless the crossing lies on vacant land (`vacant.geojson`: brownfield, greenfield, grass,
   natural=scrub); those cost `rail_crossings` x 30 = 7.5 points (metro works 5.5). Elevated/underground metro is
   not a barrier. Here 43 at-grade ways, 26.9 km, and only ~5 m of it on vacant land: every crossing is rejected.
2. `uv run python -m urban.sim baiyappanahalli` (baseline). The box is ~1.9x Hebbal's area: expect a slower run.
3. Find a published peak-hour count for one main road (Old Madras Rd / ORR at Tin Factory / Benniganahalli Flyover).
   Without one, demand is a guess and results are relative only: say so in the report. Calibration is currently
   Hebbal-only (`FLYOVER_TARGET_VPH`, `is_flyover_main`, `FLYOVER_RATE`); a count needs the same pattern for that
   road. TomTom speeds (`urban.live`) are the fallback check.
4. Stalls: check the baseline's top bottlenecks (printed by `urban.sim`). Anything below ~10 % of its limit is
   likely a junction problem (merge that never gets a gap, all-minor gridlock ring, signal). Test fixes with
   `uv run python -m urban.isolate baiyappanahalli --variants ref,zipper,...` (set `ZIPPER_NODE` in isolate.py
   first) and add confirmed merges to `ZIPPER_NODES` in sim.py.
5. `urban.candidates baiyappanahalli` -> `urban.evaluate baiyappanahalli --workers 2` (macro screen) ->
   `urban.noise baiyappanahalli --cands <macro top 10> --workers 2` (micro, 5 seeds; rank on THIS, not on macro) ->
   `urban.export baiyappanahalli`; the UI opens it with `?area=baiyappanahalli` (add a display name to `AREA_NAMES`
   in `frontend/src/data.js`).

## Next: re-validate the pipeline on TomTom free-flow speeds — teammate task (2026-11-27)
Why: the TomTom peak snapshot (`backend/tomtom/tomtom_live_2026-11-27.json`) showed the default net drives far too
fast (Hebbal sim 43.3 vs real 16.8 km/h: the net uses posted limits, real free flow is 22-28 km/h). The minimal fix
is in `sim.py` (`tomtom_speeds`): sampled edges get TomTom's free-flow speed, every other edge is scaled by its road
type's median ratio. Validated on Hebbal: sim 20.0 vs real 16.8 km/h, bias +26.5 -> +3.2, MAE 26.5 -> 5.8, roads
within 10 km/h 2/24 -> 18/24, 8,831 vehicles all arrived, 0 teleports, flyover 3,096 veh/h (target 3,225).

How: the areas `hebbal_tt` and `baiyappanahalli_tt` (data.py) are the same boxes with TomTom speeds always on, in
their own `data/<area>_tt/` folders, so nothing touches the default results used in the presentation. Every step
works unchanged with the alias. One simulation at a time, in a plain PowerShell window (`cd backend`):

1. Hebbal (~2-2.5 h):
   `uv run python -m urban.data hebbal_tt` -> `uv run python -m urban.sim hebbal_tt` ->
   `uv run python -m urban.validate hebbal_tt` (expect ~20 vs 16.8 km/h) -> `urban.candidates hebbal_tt` ->
   `urban.evaluate hebbal_tt --workers 4` -> `urban.noise hebbal_tt --cands <macro top 10> --workers 2` ->
   `urban.combos hebbal_tt --pool 10 --max 4 --workers 4 --micro-seeds 5` -> `urban.export hebbal_tt`.
   Candidate numbers differ from `hebbal` (new hot spots), so compare roads by their (u, v) junctions, not by cNN.
2. Baiyappanahalli (~5-7 h, the micro check is the long part): same steps with `baiyappanahalli_tt`. Set
   `$env:FLYOVER_RATE=1830; $env:OTHER_RATE=1970` for EVERY step (the stable demand used for `baiyappanahalli`), and
   first check `urban.validate baiyappanahalli_tt`: if the sim is now much slower than TomTom, lower the rates.
3. Compare: does the Hebbal winner (c11's junctions, 163095719#2-AddedOffRampNode -> 7304953142) and Baiyappanahalli's
   c22 (481741594 -> 2411848590) still win? The UI shows each alias as its own area (`?area=hebbal_tt`).
`SPEEDS=tomtom` on the default area name is the quick check only (writes `data/<area>/sim_tomtom/`, baseline only).
Shortcut (2026-11-27): `backend/run_tt_hebbal.ps1` and `backend/run_tt_baiyappanahalli.ps1` run all the steps above
unattended (`powershell -ExecutionPolicy Bypass -File .\run_tt_hebbal.ps1`). Each logs START/END/INTERRUPTED to
`data/overnight/tt_<area>_progress.txt`, records finished steps in `tt_<area>_done.txt` and resumes from there when
rerun; a lock makes the second script wait for the first; top 10 and the winner are picked by `urban.pick`; the
Baiyappanahalli script cuts demand 20 % (at most twice) if the baseline gridlocks.
