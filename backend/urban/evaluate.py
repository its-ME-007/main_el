"""Phase 4: add each selected candidate road to the network, simulate, compare with the baseline, score, rank.

Screening uses macro (marouter static assignment: deterministic, ~2 min) by default, or meso (`--screen meso`:
~500 s and seed noise of 7.6 % std in dT, larger than most candidate effects). The top `--micro K` candidates are
re-run with microsim as a sanity check. Reads data/<area>/candidates.geojson (urban.candidates).
Writes data/<area>/scenarios_<macro|meso>.csv and scenarios_micro.csv; per-scenario outputs in sim/scenarios/.

Usage: uv run python -m urban.evaluate [area] [--limit N] [--screen macro|meso] [--micro K] [--workers P]
       (default: hebbal, all selected, macro, K=0, P=1 = sequential)
"""
import json
import os
from concurrent.futures import ProcessPoolExecutor
import subprocess
import sys
import time

os.environ.setdefault("SUMO_HOME", r"C:\Program Files (x86)\SUMO")
import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import sumolib  # noqa: E402

from urban.data import AREAS, DATA  # noqa: E402
from urban.sim import DURATION, SEED, assign, in_box, make_demand, run  # noqa: E402

# default: 40 km/h, 1 lane each way (a local connector, not an arterial). Override for stronger variants, e.g.
# CAND_LANES=2 CAND_KMH=60 (urban.noise keeps each variant's runs and CSV apart via VARIANT).
CAND_LANES = int(os.environ.get("CAND_LANES", 1))
CAND_KMH = int(os.environ.get("CAND_KMH", 40))
CAND_SPEED = CAND_KMH / 3.6   # m/s
VARIANT = "" if (CAND_LANES, CAND_KMH) == (1, 40) else f"_l{CAND_LANES}v{CAND_KMH}"
CAND_EDGES = ("cand_f", "cand_b")
# S = w1 dT + w2 dQ + w3 dC - w4 L - w5 P   (idea.md §7). Units chosen so terms are comparable:
#   dT % mean time loss saved, dQ % study-box queueing (edge waiting time) saved,
#   dC % of the old network detour the new road removes, L metres, P cost units (below).
WEIGHTS = {"dT": 1.0, "dQ": 0.5, "dC": 0.01, "L": 0.002, "P": 0.25}
# P cost units: a demolished building = 1, a grade-separated road crossing = 0.5, a metro worksite crossing = 1
P_COST = {"buildings_hit": 1.0, "road_crossings": 0.5, "worksite_crossings": 1.0}


def scenario_net(base, cand, incoming, out):
    """netconvert the base net plus the candidate (both directions). cand=None: plain round trip, so the
    baseline goes through the same netconvert pass as every scenario (fair comparison)."""
    out.mkdir(parents=True, exist_ok=True)
    net, cmd = out / "net.net.xml", [sumolib.checkBinary("netconvert"), "--sumo-net-file", str(base)]
    if cand is not None:
        edg = out / "cand.edg.xml"
        edg.write_text("<edges>" + "".join(
            f'<edge id="{eid}" from="{a}" to="{b}" numLanes="{CAND_LANES}" speed="{CAND_SPEED:.2f}" name="candidate"/>'
            for eid, a, b in ((CAND_EDGES[0], cand.u, cand.v), (CAND_EDGES[1], cand.v, cand.u))) + "</edges>")
        # a loaded .net.xml keeps its connections as-is, so nothing would turn INTO the new road: add them
        con = out / "cand.con.xml"
        con.write_text("<connections>" + "".join(
            f'<connection from="{e}" to="{eid}" fromLane="0" toLane="{k}"/>'  # edge-level ones are ignored
            for eid, j in ((CAND_EDGES[0], cand.u), (CAND_EDGES[1], cand.v))
            for e in incoming[j] for k in range(CAND_LANES)) + "</connections>")
        cmd += ["--edge-files", str(edg), "--connection-files", str(con)]
    subprocess.run(cmd + ["-o", str(net), "--no-warnings"], check=True, stdout=subprocess.DEVNULL)
    return net


def simulate(base, routes, box, cand, incoming, out, mode, seed=SEED):
    """mode = macro | meso | micro. One scenario, self-contained (picklable args only), so it can run in a worker
    process. seed = SUMO's random seed (driver behaviour); the demand files stay the same (urban.noise varies it)."""
    done = out / f"metrics_{DURATION}.json"   # checkpoint: a killed sweep resumes where it stopped
    if done.exists():
        return json.loads(done.read_text())
    t0 = time.perf_counter()
    net = scenario_net(base, cand, incoming, out)
    m, edges = assign(net, routes, out) if mode == "macro" else run(net, routes, out, seed=seed, meso=mode == "meso")
    net.unlink()           # 30 MB per scenario; rebuild from cand.edg.xml if needed
    (out / "tripinfo.xml").unlink(missing_ok=True)
    m["box_waiting"] = sum(s["waiting"] for eid, s in edges.items() if eid in box)
    m["cand_vph"] = sum(edges.get(e, {}).get("entered", 0) for e in CAND_EDGES) * 3600 / DURATION
    m["seconds"] = time.perf_counter() - t0
    done.write_text(json.dumps(m))
    return m


def score(c, m, b):
    # dT from time loss: meso mean duration showed identical values (357.97 s) across different scenarios
    d = {"dT": 100 * (b["mean_time_loss"] - m["mean_time_loss"]) / b["mean_time_loss"],
         "dQ": 100 * (b["box_waiting"] - m["box_waiting"]) / b["box_waiting"],
         "dC": 100 * (1 - c.length_m / c.net_dist),
         "L": c.length_m,
         "P": sum(w * c[k] for k, w in P_COST.items())}
    d["score"] = sum(s * WEIGHTS[k] * d[k] for k, s in (("dT", 1), ("dQ", 1), ("dC", 1), ("L", -1), ("P", -1)))
    return d


def run_all(jobs, workers=1):
    """jobs = list of simulate() arg tuples. workers > 1: a process pool, one scenario per task (dynamic load
    balancing, since run times vary with how much traffic a candidate attracts). Yields results in job order."""
    if workers <= 1:
        yield from (simulate(*j) for j in jobs)
        return
    with ProcessPoolExecutor(workers) as ex:
        yield from ex.map(simulate, *zip(*jobs))


def setup(area):
    """Shared, read-only inputs for every scenario: base net, demand, study-box edge ids, selected candidates
    (each with the incoming edge ids at its two ends, so workers never load the 30 MB net)."""
    d = DATA / area
    base = d / "sim" / "net.net.xml"
    routes = make_demand(base, area)   # deterministic (seed 42): identical demand for baseline and every scenario
    nw = sumolib.net.readNet(str(base))
    box = {e.getID() for e in nw.getEdges() if in_box(nw, e, AREAS[area])} | set(CAND_EDGES)
    cands = gpd.read_file(d / "candidates.geojson")
    cands = cands[cands.status == "selected"].sort_values("prescore", ascending=False).reset_index(drop=True)
    incoming = {j: [e.getID() for e in nw.getNode(j).getIncoming()] for j in set(cands.u) | set(cands.v)}
    return d, base, routes, box, cands, incoming


def sweep(env, rows, mode, root, workers=1, quiet=False):
    """Baseline + every candidate in rows. Returns (baseline metrics, DataFrame ranked by score)."""
    d, base, routes, box, _, incoming = env
    tag = mode
    jobs = [(base, routes, box, None, incoming, root / f"base_{tag}", mode)]
    jobs += [(base, routes, box, c, incoming, root / f"c{i:02d}_{tag}", mode) for i, c in rows.iterrows()]
    res = run_all(jobs, workers)
    b = next(res)
    quiet or print(f"[{tag}] baseline: mean travel {b['mean_travel_time']:.1f} s, {b['seconds'] or 0:.0f} s")
    out = []
    for (i, c), m in zip(rows.iterrows(), res):
        out.append({"cand": i, "u": c.u, "v": c.v, **score(c, m, b), **m})
        quiet or print(f"[{tag}] c{i:02d} {c.length_m:4.0f} m  dT {out[-1]['dT']:+5.2f}%  dQ {out[-1]['dQ']:+6.2f}%  "
                       f"uses {m['cand_vph']:5.0f} veh/h  score {out[-1]['score']:+6.2f}  ({m['seconds'] or 0:.0f} s)",
                       flush=True)
    return b, pd.DataFrame(out).sort_values("score", ascending=False)


def evaluate(area="hebbal", limit=None, micro=0, workers=1, screen="macro"):
    env = setup(area)
    d, cands, root = env[0], env[4].head(limit), env[0] / "sim" / "scenarios"
    b, screen_df = sweep(env, cands, screen, root, workers)
    screen_df.to_csv(d / f"scenarios_{screen}.csv", index=False)
    micro_df = None
    if micro:
        _, micro_df = sweep(env, cands.loc[screen_df.cand.head(micro)], "micro", root, workers)
        micro_df.to_csv(d / "scenarios_micro.csv", index=False)
    return b, screen_df, micro_df


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda k, dflt: int(args[args.index(k) + 1]) if k in args else dflt
    area = next((a for a in args if a in AREAS), "hebbal")
    screen = args[args.index("--screen") + 1] if "--screen" in args else "macro"
    b, meso_df, micro_df = evaluate(area, limit=opt("--limit", None), micro=opt("--micro", 0),
                                    workers=opt("--workers", 1), screen=screen)
    assert len(meso_df) and (meso_df.arrived > 0).all(), "a scenario produced no traffic"
    assert meso_df.score.is_monotonic_decreasing
    print(f"\nused at all: {(meso_df.cand_vph > 0).sum()}/{len(meso_df)} candidates; "
          f"improve travel time: {(meso_df.dT > 0).sum()}")
    cols = ["cand", "u", "v", "L", "P", "dT", "dQ", "dC", "cand_vph", "teleports", "score"]
    print(f"\n{screen} ranking:\n" + meso_df[cols].head(10).round(2).to_string(index=False))
    if micro_df is not None:
        print("\nmicro validation:\n" + micro_df[cols].round(2).to_string(index=False))
