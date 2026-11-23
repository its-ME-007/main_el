"""Phase 2: SUMO baseline simulation for an area cached by urban.data.

Usage: uv run python -m urban.sim [area]   (default: hebbal)
"""
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("SUMO_HOME", r"C:\Program Files (x86)\SUMO")
import sumolib  # noqa: E402  (needs SUMO_HOME to find binaries)

from urban.data import AREAS, DATA  # noqa: E402

SUMO_HOME = Path(os.environ["SUMO_HOME"])
SEED = 42            # same seed -> same demand for baseline and every candidate
DURATION = int(os.environ.get("DURATION", 3600))  # s of departures; 900 is enough for calibration sweeps
# Calibration knobs (override via env for sweeps). Through traffic = flows between arterial boundary edges,
# split by whether the pair's free-flow route uses the Hebbal flyover, so the flyover can be loaded to
# its surveyed volume without inflating every other road.
FLYOVER_RATE = int(os.environ.get("FLYOVER_RATE", 3450))  # veh/h total over pairs routed via the main flyover
OTHER_RATE = int(os.environ.get("OTHER_RATE", 3800))      # veh/h total over the remaining arterial pairs
LOCAL_RATE = int(os.environ.get("LOCAL_RATE", 2000))      # veh/h random local trips, biased into the study box
BOX_WEIGHT = 10      # local trip origin/destination weight for edges inside the study box (others = 1)
ARTERIAL = ("highway.motorway", "highway.trunk", "highway.primary")
# Calibration target: Hebbal flyover, 3-lane carriageway, morning peak 3,225 PCU/h vs 3,300 capacity
# (Bengaluru flyover volume/capacity study, reported by Deccan Herald). Junction total per RITES: 26,896 PCU/h.
# In OSM that carriageway is the highway=trunk "Hebbal Flyover" (way 377832181, 3 lanes, 60 km/h); the other
# "Hebbal Flyover"/"Flyover" ways are trunk_link loops/ramps (1-3 lanes, 30 km/h) and are not the surveyed road.
FLYOVER_TARGET_VPH = 3225
# Speeds for OSM ways WITHOUT a maxspeed tag. netconvert's typemap defaults are 80-100 km/h for tertiary/secondary/
# trunk, faster than the 60 km/h flyover, so rerouting sent Bellary Rd through traffic down the unnamed tertiary
# service road 238204954, which then jammed merging back. Values = median maxspeed that OSM mappers tagged on the same
# road type in the Hebbal net (2026-11-23): residential 30 (228 tagged), secondary 40 (28), tertiary 50 (219),
# trunk 60 (61), trunk_link 30 (10). Types with no tagged sample get the nearest analogue. Tagged ways keep their tag.
UNTAGGED_KMH = {"trunk": 60, "primary": 50, "secondary": 40, "tertiary": 50, "unclassified": 30, "residential": 30,
                "trunk_link": 30, "primary_link": 30, "secondary_link": 30, "tertiary_link": 30}


def untagged_speeds(raw, net):
    """Second netconvert pass: set UNTAGGED_KMH on edges still at their type's default speed (= no maxspeed tag; no
    tagged value in this area equals a default). Done after building, not via --type-files, because --ramps.guess
    depends on speeds and would otherwise change the topology (it dropped 10 ramp edges incl. the flyover segment)."""
    import xml.etree.ElementTree as ET
    dflt = {t.get("id"): float(t.get("speed")) for t in
            ET.parse(SUMO_HOME / "data" / "typemap" / "osmNetconvert.typ.xml").getroot().iter("type")}
    edges = []
    for e in sumolib.net.readNet(str(raw)).getEdges():
        kind = e.getType().removeprefix("highway.")
        if kind in UNTAGGED_KMH and abs(e.getSpeed() - dflt.get(e.getType(), -1)) < 0.01:
            edges.append(f'<edge id="{e.getID()}" speed="{UNTAGGED_KMH[kind] / 3.6:.2f}"/>')
    edg = net.parent / "untagged_speeds.edg.xml"
    edg.write_text("<edges>\n" + "\n".join(edges) + "\n</edges>\n")
    subprocess.run([sumolib.checkBinary("netconvert"), "--sumo-net-file", str(raw), "--edge-files", str(edg),
                    "-o", str(net), "--no-warnings"], check=True, stdout=subprocess.DEVNULL)
    return len(edges)


def is_flyover_main(nw, edge, bbox):
    return edge.getType() == "highway.trunk" and "hebbal flyover" in edge.getName().lower() and in_box(nw, edge, bbox)


def flyover_flow(net, edges, bbox):
    """Max hourly flow on the surveyed flyover carriageway (cars ~ 1 PCU), to compare with FLYOVER_TARGET_VPH."""
    nw = sumolib.net.readNet(str(net))
    return max((s["entered"] * 3600 / DURATION for eid, s in edges.items()
                if is_flyover_main(nw, nw.getEdge(eid), bbox)), default=0)


def build_net(area):
    out = DATA / area / "sim"
    out.mkdir(exist_ok=True)
    net, raw = out / "net.net.xml", out / "raw.net.xml"
    subprocess.run([
        sumolib.checkBinary("netconvert"), "--osm-files", str(DATA / area / "roads.osm"), "-o", str(raw),
        "--geometry.remove", "--ramps.guess", "--junctions.join", "--roundabouts.guess",
        # real OSM highway=traffic_signals nodes; guess-signals/join merge signal clusters into one junction TLS
        "--tls.guess-signals", "--tls.join", "--tls.default-type", "actuated",
        "--remove-edges.isolated", "--keep-edges.components", "1",
        "--output.street-names", "--no-warnings",
    ], check=True)
    n = untagged_speeds(raw, net)
    raw.unlink()
    print(f"untagged speed limits set on {n} edges")
    return net


def in_box(nw, edge, bbox):
    x, y = edge.getShape()[len(edge.getShape()) // 2]
    lon, lat = nw.convertXY2LonLat(x, y)
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def make_demand(net, area, seed=SEED):
    """Write through-traffic flows + box-weighted local trips. Returns route files for sumo -r."""
    nw, d = sumolib.net.readNet(str(net)), net.parent
    is_art = lambda e: e.getType().startswith(ARTERIAL) and "link" not in e.getType()
    entries = [e for e in nw.getEdges() if is_art(e) and not e.getIncoming()]
    exits = [e for e in nw.getEdges() if is_art(e) and not e.getOutgoing()]
    fly, other = [], []
    for a in entries:
        for b in exits:
            path = nw.getShortestPath(a, b)[0] if a.getFromNode() != b.getToNode() else None
            if path:
                uses = any(is_flyover_main(nw, e, AREAS[area]) for e in path)
                (fly if uses else other).append((a, b))
    assert fly and other, "no routable arterial entry->exit pairs"
    rated = [(p, FLYOVER_RATE / len(fly)) for p in fly] + [(p, OTHER_RATE / len(other)) for p in other]
    flows = "".join(f'<flow id="through{i}" from="{a.getID()}" to="{b.getID()}" begin="0" end="{DURATION}" '
                    f'vehsPerHour="{vph:.2f}" departLane="best" departSpeed="max"/>'
                    for i, ((a, b), vph) in enumerate(rated))
    (d / "through.rou.xml").write_text(f"<routes>{flows}</routes>")

    # one <edge> per line: randomTrips reads weights with sumolib parse_fast, which is line-based
    weights = "\n".join(f'<edge id="{e.getID()}" value="{BOX_WEIGHT if in_box(nw, e, AREAS[area]) else 1}"/>'
                        for e in nw.getEdges())
    for kind in ("src", "dst"):
        (d / f"w.{kind}.xml").write_text(f'<edgedata><interval begin="0" end="{DURATION}">\n{weights}\n</interval></edgedata>\n')
    local = d / "local.trips.xml"
    subprocess.run([
        sys.executable, str(SUMO_HOME / "tools" / "randomTrips.py"), "-n", str(net), "-o", str(local),
        "-b", "0", "-e", str(DURATION), "--insertion-rate", str(LOCAL_RATE), "--seed", str(seed),
        "--weights-prefix", str(d / "w"), "--min-distance", "300", "--validate", "--prefix", "local",
    ], check=True, stdout=subprocess.DEVNULL)
    print(f"demand: {len(fly)} flyover pairs @ {FLYOVER_RATE / len(fly):.0f} veh/h, "
          f"{len(other)} other pairs @ {OTHER_RATE / len(other):.0f} veh/h, local {LOCAL_RATE} veh/h")
    return [d / "through.rou.xml", local]


MESO = ["--mesosim", "--meso-junction-control", "true"]  # queue-based edges; junction-control keeps TLS effects


def run(net, routes, out, seed=SEED, meso=False):
    """Run SUMO headless; return (summary metrics, per-edge stats).
    meso=True: mesoscopic model, much faster, for candidate screening (validate top picks with microsim)."""
    out.mkdir(parents=True, exist_ok=True)
    add = out / "edgedata.add.xml"
    add.write_text(f'<additional><edgeData id="e" file="{(out / "edges.xml").as_posix()}"/></additional>')
    subprocess.run([
        sumolib.checkBinary("sumo"), "-n", str(net), "-r", ",".join(map(str, routes)), "-a", str(add),
        "--tripinfo-output", str(out / "tripinfo.xml"), "--statistic-output", str(out / "stats.xml"),
        "--seed", str(seed), "--ignore-route-errors",
        "--device.rerouting.probability", "1", "--device.rerouting.period", "60",  # drivers adapt to congestion
        "--time-to-teleport", "300", "--end", str(DURATION * 2),
        "--no-step-log", "--no-warnings", "--duration-log.statistics", "false",
        *(MESO if meso else []),
    ], check=True)

    trips_done = list(sumolib.xml.parse(str(out / "tripinfo.xml"), "tripinfo"))
    veh = next(sumolib.xml.parse(str(out / "stats.xml"), "vehicles"))
    tele = next(sumolib.xml.parse(str(out / "stats.xml"), "teleports"))
    n = len(trips_done) or 1
    metrics = {
        "loaded": int(veh.loaded),
        "inserted": int(veh.inserted),
        "arrived": len(trips_done),
        "teleports": int(tele.total),
        "mean_travel_time": sum(float(t.duration) for t in trips_done) / n,
        "total_travel_time": sum(float(t.duration) for t in trips_done),
        "mean_time_loss": sum(float(t.timeLoss) for t in trips_done) / n,
        "mean_waiting_time": sum(float(t.waitingTime) for t in trips_done) / n,
    }
    edges = {}
    for e in sumolib.xml.parse(str(out / "edges.xml"), "edge"):
        if e.speed is not None and float(e.sampledSeconds or 0) > 0:
            edges[e.id] = {"speed": float(e.speed), "time_loss": float(e.timeLoss or 0), "entered": float(e.entered or 0),
                           "waiting": float(e.waitingTime or 0), "occupancy": float(e.occupancy or 0)}
    return metrics, edges


def bottlenecks(net, edges, bbox, k=10):
    """Study-box edges ranked by total time loss, with speed as a fraction of the limit."""
    nw = sumolib.net.readNet(str(net))
    rows = []
    for eid, s in edges.items():
        e = nw.getEdge(eid)
        if in_box(nw, e, bbox):
            rows.append((s["time_loss"], eid, e.getName() or "?", s["speed"] / e.getSpeed(), s["occupancy"]))
    return sorted(rows, reverse=True)[:k]


if __name__ == "__main__":
    import time
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    meso = "--meso" in sys.argv
    area = args[0] if args else "hebbal"
    t0 = time.perf_counter(); net = build_net(area)
    t1 = time.perf_counter(); routes = make_demand(net, area)
    t2 = time.perf_counter(); metrics, edges = run(net, routes, net.parent / ("baseline_meso" if meso else "baseline"), meso=meso)
    t3 = time.perf_counter()
    assert metrics["arrived"] > 0 and edges, "simulation produced no traffic"
    through = (FLYOVER_RATE + OTHER_RATE) * DURATION / 3600
    assert metrics["loaded"] > through * 1.1, "local trips missing: check randomTrips weights"
    for k, v in metrics.items():
        print(f"{k:>18}: {v:,.1f}")
    print(f"timing s: netconvert={t1 - t0:.0f} demand={t2 - t1:.0f} sumo={t3 - t2:.0f}")
    print(f"traffic lights: {len(sumolib.net.readNet(str(net)).getTrafficLights())}")
    print(f"flyover peak flow: {flyover_flow(net, edges, AREAS[area]):,.0f} veh/h (survey {FLYOVER_TARGET_VPH:,} PCU/h)")
    print("\ntop study-box bottlenecks (time loss s, edge, name, speed/limit, occupancy %):")
    for tl, eid, name, ratio, occ in bottlenecks(net, edges, AREAS[area]):
        print(f"  {tl:>9,.0f}  {eid:<22} {name[:30]:<30} {ratio:5.2f}  {occ:5.1f}")
