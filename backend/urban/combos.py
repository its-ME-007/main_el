"""Sets of candidate roads: do several new roads together beat the best single one? (user, 2026-11-26)

Greedy forward search on the macro screen (deterministic, ~2 min per scenario): start from the best single road in
scenarios_macro.csv, then at each step try adding every remaining pool candidate, simulate each set in parallel
(urban.evaluate.run_all, the Phase 5 worker pool) and keep the best-scoring set. Stop when no addition raises the score
or at --max roads. Members may not share an endpoint or cross each other (that needs its own junction).

Set score = urban.evaluate's formula: dT, dQ from the set's run; dC, L, P summed over the members.
synergy = dT(set) - sum of the members' single-road dT: > 0 means the roads help each other, < 0 that they compete
for the same traffic.

--micro-seeds N: the final set on micro over N SUMO seeds, paired with the baseline at each seed (reuses urban.noise's
run dirs), verdict |mean dT| > 2 standard errors.

Writes data/<area>/combos_macro.csv (every set tried) and combos_micro.csv. Runs in sim/combos/<c17+c39>_<mode>[_s<seed>]/,
checkpointed (a killed search resumes).
Usage: uv run python -m urban.combos [area] [--pool 10] [--max 4] [--workers 4] [--micro-seeds 5]
"""
import sys

import geopandas as gpd
import pandas as pd

from urban.data import AREAS, DATA
from urban.evaluate import MAX_SET, VARIANT, WEIGHTS, run_all, score, setup
from urban.noise import run_dir, verdict
from urban.sim import DURATION, SEED

SEEDS = (SEED, 1, 2, 3, 4, 5, 6, 7)


def name(members):
    return "+".join(f"c{i:02d}" for i in sorted(members))


def set_score(rows, members, m, b):
    """Score of a set run m vs baseline b: dT/dQ from the run, dC/L/P summed over the members."""
    parts = [score(rows.loc[i], m, b) for i in members]
    d = {"dT": parts[0]["dT"], "dQ": parts[0]["dQ"], **{k: sum(p[k] for p in parts) for k in ("dC", "L", "P")}}
    d["score"] = sum(s * WEIGHTS[k] * d[k] for k, s in (("dT", 1), ("dQ", 1), ("dC", 1), ("L", -1), ("P", -1)))
    return d


def compatible(rows, lines, members, c):
    ends = {x for i in members for x in (rows.loc[i].u, rows.loc[i].v)}
    return (rows.loc[c].u not in ends and rows.loc[c].v not in ends
            and not any(lines[c].crosses(lines[i]) for i in members))


def search(area="hebbal", pool=10, max_roads=4, workers=4):
    env = setup(area)
    d, base, routes, box, rows, incoming = env
    single = pd.read_csv(d / f"scenarios_macro{VARIANT}.csv").sort_values("score", ascending=False)
    cand = [int(c) for c in single.cand.head(pool)]
    single = single.set_index("cand")
    lines = gpd.GeoSeries(rows.geometry, crs="EPSG:4326").to_crs(32643)   # metric, for the crossing test
    root = d / "sim" / "combos"
    b = next(run_all([(base, routes, box, None, incoming, d / "sim" / "scenarios" / "base_macro", "macro")]))

    best = [cand[0]]
    s0 = single.loc[cand[0]]
    tried = [{"step": 1, "set": name(best), "roads": 1, "dT": s0.dT, "dQ": s0.dQ, "dC": s0.dC, "L": s0.L, "P": s0.P,
              "score": s0.score, "synergy": 0.0, "cand_vph": s0.cand_vph, "kept": True}]
    best_score = s0.score
    print(f"step 1: {name(best)} score {best_score:+.2f} (best single road)", flush=True)
    while len(best) < min(max_roads, MAX_SET):
        nxt = [c for c in cand if c not in best and compatible(rows, lines, best, c)]
        if not nxt:
            break
        sets = [best + [c] for c in nxt]
        jobs = [(base, routes, box, [rows.loc[i] for i in s], incoming, root / f"{name(s)}{VARIANT}_macro", "macro")
                for s in sets]
        step = []
        for s, m in zip(sets, run_all(jobs, workers)):
            r = {"step": len(s), "set": name(s), "roads": len(s), **set_score(rows, s, m, b),
                 "cand_vph": m["cand_vph"], "kept": False}
            r["synergy"] = r["dT"] - sum(single.loc[i].dT for i in s)
            step.append(r)
            print(f"  {r['set']:<24} dT {r['dT']:+5.2f}%  dQ {r['dQ']:+6.2f}%  synergy {r['synergy']:+5.2f}  "
                  f"score {r['score']:+6.2f}", flush=True)
        top = max(step, key=lambda r: r["score"])
        tried += step
        if top["score"] <= best_score:
            print(f"step {len(best) + 1}: no addition beats {best_score:+.2f}; stop", flush=True)
            break
        top["kept"], best, best_score = True, [int(x[1:]) for x in top["set"].split("+")], top["score"]
        print(f"step {len(best)}: keep {top['set']} score {best_score:+.2f}", flush=True)
    df = pd.DataFrame(tried)
    df.to_csv(d / f"combos_macro{VARIANT}.csv", index=False)
    return env, best, df


def micro(env, members, seeds):
    """Final set on micro, paired with the baseline at each seed."""
    d, base, routes, box, rows, incoming = env
    jobs, keys = [], []
    for s in seeds:
        jobs.append((base, routes, box, None, incoming, run_dir(d, "base", "micro", s), "micro", s))
        out = d / "sim" / "combos" / (f"{name(members)}{VARIANT}_micro_s{s}" + ("" if DURATION == 3600 else f"_d{DURATION}"))
        jobs.append((base, routes, box, [rows.loc[i] for i in members], incoming, out, "micro", s))
        keys += [("base", s), ("set", s)]
    res = dict(zip(keys, run_all(jobs, 2)))
    df = pd.DataFrame([{"set": name(members), "seed": s, **set_score(rows, members, res[("set", s)], res[("base", s)]),
                        "cand_vph": res[("set", s)]["cand_vph"], "teleports": res[("set", s)]["teleports"]}
                       for s in seeds])
    df.to_csv(d / f"combos_micro{VARIANT}.csv", index=False)
    print(f"\nmicro, {len(seeds)} seeds, {name(members)}: dT {df.dT.mean():+.2f} +- {df.dT.std():.2f} %  "
          f"score {df.score.mean():+.2f}  -> {verdict(list(df.dT))}")
    return df


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda k, dflt: int(args[args.index(k) + 1]) if k in args else dflt
    area = next((a for a in args if a in AREAS), "hebbal")
    if "--set" in args:   # micro-check a given set only, e.g. --set 9,11 (no search); writes combos_micro_<set>.csv
        members = [int(x) for x in args[args.index("--set") + 1].split(",")]
        out = micro(setup(area), members, SEEDS[:opt("--micro-seeds", 5)])
        out.to_csv(DATA / area / f"combos_micro_{name(members)}{VARIANT}.csv", index=False)
        sys.exit()
    env, best, df = search(area, opt("--pool", 10), opt("--max", 4), opt("--workers", 4))
    kept = df[df.kept]
    assert kept.score.is_monotonic_increasing, "greedy steps must not lower the score"
    print("\nkept sets:\n" + kept[["set", "dT", "dQ", "P", "synergy", "score"]].round(2).to_string(index=False))
    if opt("--micro-seeds", 0):
        micro(env, best, SEEDS[:opt("--micro-seeds", 0)])
