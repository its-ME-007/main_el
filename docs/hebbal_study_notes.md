# Hebbal – study notes for the presentation (28 Nov 2026)

All Hebbal results below are final (rules of 2026-11-26: turn cap 135°, rail reject, flyover/metro crossings
5.5 points each).

## Plan for 27 Nov (nothing left for the morning of the 28th)

| When | What |
|---|---|
| Now – ~14:30 | Study Hebbal; Baiyappanahalli full run (`backend/run_bai_full.ps1`) finishes in its own window |
| Afternoon | Write the last 6 slides with final numbers |
| 6–8 pm | TomTom peak snapshot of both areas: a "sim vs real speeds" validation slide only, no recalibration |
| By ~9–10 pm | Deck done, app rebuilt (`npm run build`), one run-through; nothing runs overnight |

## Study area

- Bellary Road × ORR flyover junction, about 1.7 × 1.5 km.
- Metro Phase 2B and suburban rail (Mallige Line) works cross the box.
- Network: 3,730 junctions, 9,374 road segments, 9,140 buildings (OpenStreetMap, offline Geofabrik extract).

## Baseline and calibration

- Calibration target: 3,225 PCU/h on the flyover's main carriageway (morning peak, Bengaluru flyover v/c study).
- Simulated: 3,186 veh/h, within 1.2 %.
- About 8,800 vehicles per hour; 88 s lost per trip; 7 teleports.
- Run-to-run noise: ±4.7 % between random seeds (baseline 87.1 s mean over 5 seeds), so a claimed gain must beat
  2 standard errors.

## Junction fixes (one change at a time)

- Delay 193 s → 88 s, teleports 38 → 7.
- Main fix: zipper merge where the new flyover loop joins Bellary Road (it never found a gap as a priority merge).
- Smaller vehicle gaps or a two-wheeler/bus mix moved moderate roads but not the true stalls: those were junction
  topology, not driver parameters.
- Known stall, not fixed: the ORR signal segment stays at 3–4 km/h in every variant.

## Candidate generation

- Seeds: ends of the 30 worst road segments in the study box.
- Pairs 50–600 m apart whose network detour is at least 2× the straight line.
- 1,626 pairs examined → 22 selected. Rejected: 1,477 hit buildings, 84 cross rail, 20 hit obstacles.

| Rule | Outcome |
|---|---|
| Demolishes more than 3 buildings, or hits water / park | Reject |
| Crosses in-service rail at grade | Reject (unless over vacant land) |
| Crosses the metro works | −5.5 points |
| Crosses a flyover or ramp | −5.5 points |
| Entry turn sharper than 135° | Not connected |
| Ends on a flyover, ramp or link road | Not allowed |

## Evaluation

- Score S = ΔT + 0.5 ΔQ + 0.01 ΔC − 0.002 L − 0.25 P
  (ΔT % delay saved, ΔQ % study-box queueing saved, ΔC % detour removed, L metres, P penalty units).
- Two stages:
  - Macro (static traffic assignment, SUMO marouter): fast and deterministic, screens every candidate.
  - Micro (SUMO simulation): top 10 over 5 seeds, paired with the baseline at each seed.
- Macro and micro disagree because macro has no junction behaviour, so the ranking comes from micro.

## Results (micro, 5 seeds)

| Candidate | Delay saved | Score | Verdict |
|---|---|---|---|
| **c11** (63 m, crosses Bellary Road only) | **+9.51 ± 4.8 %** | **+8.29** | real gain, winner |
| c09 | +8.33 ± 4.5 % | +2.80 | real gain |
| c07 (crosses metro) | +8.48 ± 4.9 % | −14.36 | delay saved, but study-box queueing worse |
| c21 | +3.51 ± 4.4 % | +8.70 | within noise |
| c04, c05, c14, c15, c16, c20 | −3.4 to +2.2 % | | within noise |

### The turn-rule story

- The first winner (old c39, +9.4 %) reached its end junction through a 137° swing off the Bellary Road off-ramp
  and a 147° near-U-turn from the frontage road.
- With entry turns capped at 135°, that version loses both entries.
- c11 reaches the same junction with realistic turns only, and keeps the same ~9.5 % gain.

## Combinations of roads

- The roads compete for the same traffic: synergy is negative almost everywhere.
- c09 + c11: +11.09 ± 3.67 % delay saved (real), but score only +1.86 (study-box queueing −8.9 %, metro crossing).
- Greedy macro set c07 + c11 + c21: +5.8 ± 7.5 % on micro, within noise, score −18.95.
- Conclusion: build c11 alone.

## Parallel evaluation (PAGP)

| Workers | Wall time | Speedup | Efficiency |
|---|---|---|---|
| 1 | 1,430 s | 1.00 | 1.00 |
| 2 | 715 s | 2.00 | 1.00 |
| 4 | 395 s | 3.62 | 0.90 |

- 17 macro scenarios (baseline + 16 candidates); results identical to sequential at every worker count.
- Loss at 4 workers: 17 jobs on 4 workers leave the last wave part-empty, plus a slight per-run slowdown.

## Likely questions

- Why do macro and micro disagree? Macro has no junctions, signals or queues spilling back.
- Why 5 seeds? One run can be off by ~9 % (2 sd); single-seed rankings were meaningless.
- What does a cars-only fleet leave out? Bengaluru traffic is mostly two-wheelers; flows are in vehicles ≈ PCU.
- Why was the old +9.4 % redone? It depended on hairpin entries a real junction couldn't build.
- Why is Baiyappanahalli uncalibrated? The survey peak (21,789 PCU/h) exceeds what one road can carry; the sim's
  stable demand level is used and results are relative only.
