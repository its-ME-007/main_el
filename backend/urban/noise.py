"""Phase 4 noise floor: how much do results change from SUMO's randomness alone?

The demand (who travels where, seed 42) stays fixed; only SUMO's --seed changes (driver speed factors,
rerouting choices, insertion details). Near capacity (the ORR) this alone can flip a road between slow and jammed,
so a single run per scenario is not enough to judge a few-percent change.

Runs the baseline (and optionally candidates) once per seed, then compares each candidate with the baseline of the
SAME seed (paired). Seed 42 reuses the runs in sim/scenarios/ from urban.evaluate; other seeds go to sim/noise/.
Writes data/<area>/noise.csv (one row per run) and prints a summary.

Usage: uv run python -m urban.noise [area] [--seeds 42,1,2,3,4] [--cands 22,24,25] [--meso] [--workers 2]
       (default: hebbal, micro, baseline only, seeds 42,1,2,3,4)
"""
import statistics as st
import sys

import pandas as pd

from urban.data import AREAS
from urban.evaluate import CAND_KMH, CAND_LANES, VARIANT, run_all, score, setup
from urban.sim import DURATION, SEED

FULL = 3600   # urban.evaluate's default DURATION


def run_dir(d, tag, sim, seed):
    # reuse urban.evaluate's seed-42 runs only at the full duration; short test runs must never write into them.
    # Candidate variants (CAND_LANES/CAND_KMH) get their own dirs (urban.evaluate names them the same way); the
    # baseline has no candidate, so it is shared.
    if tag != "base":
        tag += VARIANT
    if seed == SEED and DURATION == FULL:
        return d / "sim" / "scenarios" / f"{tag}_{sim}"
    return d / "sim" / "noise" / (f"{tag}_{sim}_s{seed}" + ("" if DURATION == FULL else f"_d{DURATION}"))


def noise(area="hebbal", seeds=(42, 1, 2, 3, 4), cands=(), meso=False, workers=2):
    env = setup(area)
    d, base, routes, box, rows, incoming = env
    sim = "meso" if meso else "micro"
    jobs, keys = [], []
    for s in seeds:
        jobs.append((base, routes, box, None, incoming, run_dir(d, "base", sim, s), sim, s)); keys.append(("base", s))
        for i in cands:
            jobs.append((base, routes, box, rows.loc[i], incoming, run_dir(d, f"c{i:02d}", sim, s), sim, s))
            keys.append((i, s))
    res = dict(zip(keys, run_all(jobs, workers)))

    out = []
    for (k, s), m in res.items():
        r = {"run": "base" if k == "base" else f"c{k:02d}", "seed": s, "sim": sim, **m}
        if k != "base":
            r.update(score(rows.loc[k], m, res[("base", s)]))   # paired with the same seed's baseline
        out.append(r)
    df = pd.DataFrame(out)
    df.to_csv(d / f"noise_{sim}{VARIANT}.csv", index=False)
    return df


def spread(xs):
    return (st.mean(xs), st.stdev(xs) if len(xs) > 1 else 0.0, min(xs), max(xs))


def verdict(xs):
    """'real effect' if the mean is more than 2 standard errors from zero (needs > 2 seeds), else 'within noise'."""
    m, sd, *_ = spread(xs)
    return "real effect" if len(xs) > 2 and abs(m) > 2 * sd / len(xs) ** 0.5 else "within noise"


def summary(df):
    """JSON-ready version of report(): baseline spread and, per candidate, the paired dT/score over seeds."""
    b = df[df.run == "base"]
    m, sd, lo, hi = spread(list(b.mean_time_loss))
    out = {"sim": df.sim.iloc[0], "seeds": sorted(int(x) for x in b.seed),
           "baseline": {"mean_time_loss": m, "sd": sd, "min": lo, "max": hi}, "cands": {}}
    for run, g in df[df.run != "base"].groupby("run"):
        dm, dsd, dlo, dhi = spread(list(g.dT))
        sm, ssd, *_ = spread(list(g.score))
        out["cands"][int(run[1:])] = {"n": len(g), "dT": dm, "dT_sd": dsd, "dT_min": dlo, "dT_max": dhi,
                                      "score": sm, "score_sd": ssd, "cand_vph": float(g.cand_vph.mean()),
                                      "verdict": verdict(list(g.dT))}
    return out


def report(df):
    b = df[df.run == "base"]
    m, sd, lo, hi = spread(list(b.mean_time_loss))
    print(f"\nbaseline over {len(b)} seeds ({df.sim.iloc[0]}); candidates: {CAND_LANES} lane(s) each way, {CAND_KMH} km/h")
    print(f"  mean delay per trip  {m:7.1f} s  sd {sd:5.1f} s  ({100 * sd / m:4.1f} %)  range {lo:.1f} to {hi:.1f}")
    m2, sd2, lo2, hi2 = spread(list(b.box_waiting))
    print(f"  study-box queueing   {m2:9,.0f} s  sd {sd2:7,.0f} s  ({100 * sd2 / m2:4.1f} %)")
    print(f"  teleports            {', '.join(str(int(t)) for t in b.teleports)}")
    print(f"  -> one run can be off by about {200 * sd / m:.0f} % (2 sd) from the average, on delay alone")
    for run, g in df[df.run != "base"].groupby("run"):
        dm, dsd, dlo, dhi = spread(list(g.dT))
        sm, ssd, *_ = spread(list(g.score))
        print(f"  {run}: delay saved {dm:+6.2f} % (sd {dsd:4.1f}, range {dlo:+.1f} to {dhi:+.1f}), "
              f"score {sm:+6.2f} (sd {ssd:4.1f})  -> {verdict(list(g.dT))}")


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda k, dflt: args[args.index(k) + 1] if k in args else dflt
    ints = lambda s: tuple(int(x) for x in s.split(",") if x)
    area = next((a for a in args if a in AREAS), "hebbal")
    df = noise(area, ints(opt("--seeds", "42,1,2,3,4")), ints(opt("--cands", "")), "--meso" in args,
               int(opt("--workers", 2)))
    report(df)
