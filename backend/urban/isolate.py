"""Isolate model shortcomings: one change at a time vs the same reference, micro, same demand (seed 42).

Variants change only the vehicle type (gaps, vehicle mix), via a vType / vTypeDistribution with id DEFAULT_VEHTYPE
in the run's additional file, so demand files and the net stay identical. Reports, per variant: flyover flow (veh
and PCU) and speed, speed on the reference run's top-10 box bottlenecks (user target ~5-10 km/h), share of used
box edges below 10 % of their limit, and the error vs TomTom speeds (data/<area>/live_traffic.json, if present).

Writes data/<area>/isolate.csv. Runs go to sim/isolate/<variant>/ and are reused if done (resume after a kill).
Usage: uv run python -m urban.isolate [area] [--variants ref,gap10,mix,mixgap] [--workers 2]
"""
import json
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from urban.data import AREAS, DATA
from urban.sim import DURATION, bottlenecks, in_box, is_flyover_main, make_demand, run, sumolib

PCU = {"car": 1.0, "moto": 0.5, "bus": 3.0}
MOTO = '<vType id="moto" vClass="motorcycle" length="2.2" minGap="0.5" probability="0.60"/>'
BUS = '<vType id="bus" vClass="bus" probability="0.05"/>'
MOTO_DATA = '<edgeData id="m" file="{}" vTypes="moto"/><edgeData id="b" file="{}" vTypes="bus"/>'


def mix(car_gap=2.5):
    return (f'<vTypeDistribution id="DEFAULT_VEHTYPE"><vType id="car" minGap="{car_gap}" probability="0.35"/>'
            f'{MOTO}{BUS}</vTypeDistribution>')


# junction fixes (round 2): each applies to the reference vehicles. zipper = the flyover-loop merge into Bellary Rd
# becomes a zipper junction; jb20 = vehicles ignore a junction blocker after 20 s (local-road gridlock ring);
# act = all signals actuated instead of SUMO's equal-split fixed timing (ORR starved at 33 of 90 s).
ZIPPER_NODE = "13052245180"
JB = ("--ignore-junction-blocker", "20")
VARIANTS = {
    "ref": "",
    "gap10": '<vType id="DEFAULT_VEHTYPE" minGap="1.0"/>',
    "mix": mix(),
    "mixgap": mix(1.0),
    "zipper": {"zipper": True},
    "jb20": {"args": JB},
    "act": {"act": True},
    "all3": {"zipper": True, "args": JB, "act": True},
}


def actuated(net):
    """Every signal's existing phases as an actuated program; the last loaded program for a TLS is the one used."""
    nw = sumolib.net.readNet(str(net), withPrograms=True)
    out = []
    for tl in nw.getTrafficLights():
        for p in tl.getPrograms().values():
            ph = "".join(f'<phase duration="{x.duration}" state="{x.state}"'
                         + ('' if "y" in x.state or "G" not in x.state.upper() else ' minDur="5" maxDur="60"') + "/>"
                         for x in p.getPhases())
            out.append(f'<tlLogic id="{tl.getID()}" type="actuated" programID="act" offset="0">{ph}</tlLogic>')
            break
    return "".join(out)


def zipper_net(net, out):
    """The base net with one junction switched to type zipper (second netconvert pass, like urban.evaluate)."""
    import subprocess
    dst = out / "net_zipper.net.xml"
    if not dst.exists():
        out.mkdir(parents=True, exist_ok=True)
        x, y = sumolib.net.readNet(str(net)).getNode(ZIPPER_NODE).getCoord()
        nod = out / "zipper.nod.xml"
        nod.write_text(f'<nodes><node id="{ZIPPER_NODE}" x="{x}" y="{y}" type="zipper"/></nodes>')
        subprocess.run([sumolib.checkBinary("netconvert"), "--sumo-net-file", str(net), "--node-files", str(nod),
                        "-o", str(dst), "--no-warnings"], check=True, stdout=subprocess.DEVNULL)
    return dst


def job(args):
    net, routes, out, xml, extra = args
    done = out / "metrics.json"
    if done.exists():
        return json.loads(done.read_text())
    if "vTypeDistribution" in xml:
        xml += MOTO_DATA.format((out / "edges_moto.xml").as_posix(), (out / "edges_bus.xml").as_posix())
    import time
    t = time.perf_counter()
    m, _ = run(net, routes, out, extra_add=xml, extra_args=extra)
    m["sumo_s"] = time.perf_counter() - t
    done.write_text(json.dumps(m))
    return m


def entered(path):
    if not path.exists():
        return {}
    return {e.id: float(e.entered or 0) for e in sumolib.xml.parse(str(path), "edge")}


def edge_speeds(out):
    return {e.id: (float(e.speed), float(e.entered or 0)) for e in sumolib.xml.parse(str(out / "edges.xml"), "edge")
            if e.speed is not None and float(e.sampledSeconds or 0) > 0}


def analyse(nw, bbox, out, hot, live):
    sp = edge_speeds(out)
    moto, bus = entered(out / "edges_moto.xml"), entered(out / "edges_bus.xml")
    fly = [e for e in sp if is_flyover_main(nw, nw.getEdge(e), bbox)]
    k = 3600 / DURATION
    veh = max(sp[e][1] * k for e in fly)
    pcu = max((sp[e][1] - moto.get(e, 0) - bus.get(e, 0) + PCU["moto"] * moto.get(e, 0)
               + PCU["bus"] * bus.get(e, 0)) * k for e in fly)
    fly_kmh = 3.6 * sum(sp[e][0] * sp[e][1] for e in fly) / max(1, sum(sp[e][1] for e in fly))
    box = [e for e in sp if sp[e][1] > 0 and in_box(nw, nw.getEdge(e), bbox)]
    crawl = sum(sp[e][0] < 0.1 * nw.getEdge(e).getSpeed() for e in box) / len(box)
    r = {"flyover_veh_h": veh, "flyover_pcu_h": pcu, "flyover_kmh": fly_kmh,
         "hot10_median_kmh": st.median(3.6 * sp[e][0] for e in hot if e in sp),
         "box_crawl_share": crawl}
    for e in hot:
        r[f"kmh_{e}"] = 3.6 * sp[e][0] if e in sp else None
    if live:
        pts = [(3.6 * sp[p["edge"]][0], p["current_kmh"], p["ratio"]) for p in live if p["edge"] in sp and p["current_kmh"]]
        if pts:
            err = [abs(s - t) for s, t, _ in pts]
            cong = [abs(s - t) for s, t, q in pts if q and q < 0.5]
            r.update(tomtom_n=len(pts), tomtom_mae=st.mean(err), tomtom_median_ae=st.median(err),
                     tomtom_bias=st.mean(s - t for s, t, _ in pts),
                     tomtom_congested_n=len(cong), tomtom_congested_mae=st.mean(cong) if cong else None)
    return r


def isolate(area="hebbal", names=tuple(VARIANTS), workers=2):
    d = DATA / area
    net = d / "sim" / "net.net.xml"
    routes = make_demand(net, area)
    root = d / "sim" / ("isolate" if DURATION == 3600 else f"isolate_d{DURATION}")   # short tests never mix in
    names = ["ref", *[n for n in names if n != "ref"]]   # ref defines the bottleneck set
    jobs = []
    for n in names:
        v = VARIANTS[n] if isinstance(VARIANTS[n], dict) else {"xml": VARIANTS[n]}
        xml = v.get("xml", "") + (actuated(net) if v.get("act") else "")
        jobs.append((zipper_net(net, root) if v.get("zipper") else net, routes, root / n, xml, v.get("args", ())))
    with ProcessPoolExecutor(workers) as ex:
        res = dict(zip(names, ex.map(job, jobs)))

    nw, bbox = sumolib.net.readNet(str(net)), AREAS[area]
    ref = {e: {"speed": s, "time_loss": 0, "occupancy": 0} for e, (s, _) in edge_speeds(root / "ref").items()}
    for e in sumolib.xml.parse(str(root / "ref" / "edges.xml"), "edge"):
        if e.id in ref:
            ref[e.id].update(time_loss=float(e.timeLoss or 0), occupancy=float(e.occupancy or 0))
    hot = [eid for _, eid, *_ in bottlenecks(net, ref, bbox)]
    lp = d / "live_traffic.json"
    live = json.loads(lp.read_text())["points"] if lp.exists() else None
    rows = [{"variant": n, **{k: res[n][k] for k in ("arrived", "teleports", "mean_time_loss", "sumo_s")},
             **analyse(nw, bbox, root / n, hot, live)} for n in names]
    df = pd.DataFrame(rows)
    df.to_csv(d / "isolate.csv", index=False)
    cols = [c for c in df.columns if not c.startswith("kmh_")]
    print(df[cols].round(2).to_string(index=False))
    print("\nkm/h on the reference top-10 box bottlenecks:")
    print(df.set_index("variant")[[c for c in df.columns if c.startswith("kmh_")]].T.round(1).to_string())
    return df


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda k, dflt: args[args.index(k) + 1] if k in args else dflt
    area = next((a for a in args if a in AREAS), "hebbal")
    isolate(area, tuple(opt("--variants", ",".join(VARIANTS)).split(",")), int(opt("--workers", 2)))
