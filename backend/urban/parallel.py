"""Phase 5: sequential vs parallel scenario evaluation. Speedup S = Ts / Tp, efficiency E = S / P (idea.md §8).

Runs the same sweep (MODE=macro default, or MODE=meso) (baseline + N candidates) with P = 1 (sequential) and each P in --workers, every time in a
fresh directory so no checkpoint is reused, then checks the parallel results equal the sequential ones.
Macro: full hour, ~2 min per scenario. MODE=meso: DURATION defaults to 900 s (39 s per run).
Writes data/<area>/parallel.csv.

Usage: uv run python -m urban.parallel [area] [--n N] [--workers 2,4,8]   (default: hebbal, N=16)
"""
import os
import shutil
import sys
import time

MODE = os.environ.get("MODE", "macro")   # macro (deterministic, ~2 min, full hour) or meso
if MODE == "meso":
    os.environ.setdefault("DURATION", "900")   # 39 s per meso run; macro keeps the full calibrated hour
import pandas as pd  # noqa: E402

from urban.data import AREAS  # noqa: E402
from urban.evaluate import sweep, setup  # noqa: E402
COMPARE = ["cand", "arrived", "teleports", "mean_time_loss", "box_waiting", "cand_vph", "score"]


def bench(area="hebbal", n=16, workers=(2, 4, 8)):
    env = setup(area)
    d, rows = env[0], env[4].head(n)
    rows_out, ref = [], None
    for p in (1, *workers):
        root = d / "sim" / "bench" / f"p{p}"
        shutil.rmtree(root, ignore_errors=True)
        t0 = time.perf_counter()
        b, df = sweep(env, rows, MODE, root, workers=p, quiet=True)
        wall = time.perf_counter() - t0
        busy = b["seconds"] + df.seconds.sum()   # summed per-scenario run time (netconvert + sumo)
        df = df.sort_values("cand").reset_index(drop=True)
        ref = df if ref is None else ref
        rows_out.append({"workers": p, "scenarios": len(df) + 1, "wall_s": wall, "busy_s": busy,
                         "utilization": busy / (p * wall),   # < 1: idle workers (load imbalance) or startup
                         "per_run_s": busy / (len(df) + 1),  # grows with P if runs contend for memory/cache
                         "identical": df[COMPARE].equals(ref[COMPARE])})
        r = rows_out[-1]
        print(f"P={p}: {wall:6.0f} s wall, {r['per_run_s']:5.1f} s/run, identical={r['identical']}", flush=True)
    out = pd.DataFrame(rows_out)
    ts = out.wall_s.iloc[0]
    out["speedup"] = ts / out.wall_s
    out["efficiency"] = out.speedup / out.workers
    out["throughput_per_min"] = 60 * out.scenarios / out.wall_s
    out.to_csv(d / "parallel.csv", index=False)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda k, dflt: args[args.index(k) + 1] if k in args else dflt
    area = next((a for a in args if a in AREAS), "hebbal")
    res = bench(area, int(opt("--n", 16)), tuple(int(x) for x in opt("--workers", "2,4,8").split(",")))
    print("\n" + res.round(2).to_string(index=False))
    assert res.identical.all(), "parallel results differ from sequential"
    assert (res.speedup.iloc[1:] > 1).all(), "parallel was not faster than sequential"
