# Handover: state of the Hebbal pipeline (2026-11-23)

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
