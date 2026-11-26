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
REROUTE = os.environ.get("REROUTE", "1") != "0"   # REROUTE=0: keep free-flow routes (noise-source test)
# Calibration knobs (override via env for sweeps). Through traffic = flows between arterial boundary edges,
# split by whether the pair's free-flow route uses the area's surveyed road (CALIB), so that road can be loaded to
# its surveyed volume without inflating every other road. FLYOVER_RATE overrides the area's default rate.
OTHER_RATE = int(os.environ.get("OTHER_RATE", 3800))      # veh/h total over the remaining arterial pairs
LOCAL_RATE = int(os.environ.get("LOCAL_RATE", 2000))      # veh/h random local trips, biased into the study box
BOX_WEIGHT = 10      # local trip origin/destination weight for edges inside the study box (others = 1)
ARTERIAL = ("highway.motorway", "highway.trunk", "highway.primary")
# Calibration target: Hebbal flyover, 3-lane carriageway, morning peak 3,225 PCU/h vs 3,300 capacity
# (Bengaluru flyover volume/capacity study, reported by Deccan Herald). Junction total per RITES: 26,896 PCU/h.
# In OSM that carriageway is the highway=trunk "Hebbal Flyover" (way 377832181, 3 lanes, 60 km/h); the other
# "Hebbal Flyover"/"Flyover" ways are trunk_link loops/ramps (1-3 lanes, 30 km/h) and are not the surveyed road.
# Baiyappanahalli (user, 2026-11-25): B-SMILE Yeshwanthpur-KR Puram elevated corridor DPR (Infra Support Engineering),
# TVC 02 "Near NGEF, Old Madras Road", 20.05.2025: 200,183 PCU/day, peak 21,789 PCU/h (V/C 4.04), split 53:47.
# A 6-lane road cannot carry 21,789 PCU/h, so the road is taken as SATURATED: DPR design capacity 5,400 PCU/h two-way
# x 53 % = 2,860 PCU/h in the busier (westbound) direction. Here OMR is named "Swamy Vivekananda Road" in OSM.
# Sweep (15 min, rates 4,000/5,400/7,000): OMR flow plateaus at ~1,850-1,950 veh/h whatever the demand, capped by the
# netconvert-guessed 39/90 s split at TLS 481750173 (westbound) and a 2-lane OSM stretch 328758436#2 ending at a
# pedestrian signal (eastbound). Accepted as a model limit (user, 2026-11-25): sim capacity ~32 % below the real one,
# demand first kept at the DPR's 5,400 so the road is saturated as observed (LOS F). But 5,400 is ~40 % above what the
# sim road carries, so queues grew all hour (full hour: 501 teleports, time loss 1,287 s). Default 4,000 (user,
# 2026-11-25) = demand ~ sim capacity: still saturated, queues bounded (30 min: 52 teleports, 496 s vs 73 / 582 s).
# urban.isolate (30 min) also tried allway junctions, half local demand and --weights.priority-factor 1: none helped.
# 1st A Main Rd 1535119254 / 2nd Main Rd -232875115#0 (1-lane, north of the Kasturinagar underpass) stay ~1 km/h in
# every variant: a known limitation, like Hebbal's ORR 1073384218#0. 77-90 % of their traffic is rerouted through
# traffic, but only 26-36 vehicles per 30 min use them.
# area -> (OSM highway type, name, target veh/h on its busiest in-box edge, default total rate over pairs using it)
CALIB = {"hebbal": ("highway.trunk", "hebbal flyover", 3225, 3030),
         "baiyappanahalli": ("highway.primary", "swamy vivekananda road", 2860, 4000)}
FLYOVER_TARGET_VPH = 3225   # Hebbal; other areas: CALIB[area][2]
# Speeds for OSM ways WITHOUT a maxspeed tag. netconvert's typemap defaults are 80-100 km/h for tertiary/secondary/
# trunk, faster than the 60 km/h flyover, so rerouting sent Bellary Rd through traffic down the unnamed tertiary
# service road 238204954, which then jammed merging back. Values = median maxspeed that OSM mappers tagged on the same
# road type in the Hebbal net (2026-11-23): residential 30 (228 tagged), secondary 40 (28), tertiary 50 (219),
# trunk 60 (61), trunk_link 30 (10). Types with no tagged sample get the nearest analogue. Tagged ways keep their tag.
UNTAGGED_KMH = {"trunk": 60, "primary": 50, "secondary": 40, "tertiary": 50, "unclassified": 30, "residential": 30,
                "trunk_link": 30, "primary_link": 30, "secondary_link": 30, "tertiary_link": 30}
# Merges built as zipper junctions (user, 2026-11-24). 13052245180: the new flyover loop (1422993566) joining 3-lane
# Bellary Rd; as a priority merge the loop never found a gap in 3,265 veh/h and queued back 649 m into the local
# roads (urban.isolate: time loss 193 -> 101 s, teleports 38 -> 7).
ZIPPER_NODES = ("13052245180",)


def untagged_speeds(raw, net):
    """Second netconvert pass: set UNTAGGED_KMH on edges still at their type's default speed (= no maxspeed tag; no
    tagged value in this area equals a default). Done after building, not via --type-files, because --ramps.guess
    depends on speeds and would otherwise change the topology (it dropped 10 ramp edges incl. the flyover segment)."""
    import xml.etree.ElementTree as ET
    dflt = {t.get("id"): float(t.get("speed")) for t in
            ET.parse(SUMO_HOME / "data" / "typemap" / "osmNetconvert.typ.xml").getroot().iter("type")}
    edges = []
    nw = sumolib.net.readNet(str(raw))
    for e in nw.getEdges():
        kind = e.getType().removeprefix("highway.")
        if kind in UNTAGGED_KMH and abs(e.getSpeed() - dflt.get(e.getType(), -1)) < 0.01:
            edges.append(f'<edge id="{e.getID()}" speed="{UNTAGGED_KMH[kind] / 3.6:.2f}"/>')
    edg = net.parent / "untagged_speeds.edg.xml"
    edg.write_text("<edges>\n" + "\n".join(edges) + "\n</edges>\n")
    nod = net.parent / "zipper.nod.xml"   # same pass: ZIPPER_NODES become zipper merges
    nod.write_text("<nodes>" + "".join(f'<node id="{n}" x="{nw.getNode(n).getCoord()[0]}" '
                                       f'y="{nw.getNode(n).getCoord()[1]}" type="zipper"/>'
                                       for n in ZIPPER_NODES if nw.hasNode(n))   # ids are per area
                   + "</nodes>")
    subprocess.run([sumolib.checkBinary("netconvert"), "--sumo-net-file", str(raw), "--edge-files", str(edg),
                    "--node-files", str(nod), "-o", str(net), "--no-warnings"], check=True, stdout=subprocess.DEVNULL)
    return len(edges)


def is_flyover_main(nw, edge, bbox):
    """The surveyed calibration road of whichever CALIB area this bbox is (name kept from the Hebbal flyover)."""
    return any(edge.getType() == kind and name in edge.getName().lower() for kind, name, *_ in CALIB.values())         and in_box(nw, edge, bbox)


def calib_rate(area):
    return int(os.environ.get("FLYOVER_RATE", CALIB.get(area, (0, 0, 0, 0))[3]))


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
        "--lefthand",   # India drives on the left
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
    assert fly or other, "no routable arterial entry->exit pairs"
    if not fly:   # area without a surveyed road: one uncalibrated through rate (OTHER_RATE) over all pairs
        print("  no calibration road in this area: through demand uncalibrated")
    rate = calib_rate(area)
    rated = ([(p, rate / len(fly)) for p in fly] if fly else []) + [(p, OTHER_RATE / len(other)) for p in other]
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
    print(f"demand: {len(fly)} calibration-road pairs @ {rate / max(1, len(fly)):.0f} veh/h, "
          f"{len(other)} other pairs @ {OTHER_RATE / max(1, len(other)):.0f} veh/h, local {LOCAL_RATE} veh/h")
    return [d / "through.rou.xml", local]


MESO = ["--mesosim", "--meso-junction-control", "true"]  # queue-based edges; junction-control keeps TLS effects


def run(net, routes, out, seed=SEED, meso=False, extra_add="", extra_args=(), end=None):
    """Run SUMO headless; return (summary metrics, per-edge stats).
    meso=True: mesoscopic model, much faster, for candidate screening (validate top picks with microsim).
    extra_add: XML put into the additional file, e.g. a vType with id DEFAULT_VEHTYPE (urban.isolate).
    extra_args: more sumo options (urban.isolate). end: stop time (default DURATION * 2; urban.fcd stops early)."""
    out.mkdir(parents=True, exist_ok=True)
    add = out / "edgedata.add.xml"
    add.write_text(f'<additional>{extra_add}<edgeData id="e" file="{(out / "edges.xml").as_posix()}"/></additional>')
    subprocess.run([
        sumolib.checkBinary("sumo"), "-n", str(net), "-r", ",".join(map(str, routes)), "-a", str(add),
        "--tripinfo-output", str(out / "tripinfo.xml"), "--statistic-output", str(out / "stats.xml"),
        "--seed", str(seed), "--ignore-route-errors",
        "--device.rerouting.probability", "1" if REROUTE else "0", "--device.rerouting.period", "60",  # adapt to congestion
        "--time-to-teleport", "300", "--end", str(end or DURATION * 2),
        "--ignore-junction-blocker", "20",   # user 2026-11-24: breaks the local-road gridlock ring (urban.isolate)
        "--no-step-log", "--no-warnings", "--duration-log.statistics", "false",
        *(MESO if meso else []), *extra_args,
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


def assign(net, routes, out):
    """Macroscopic static assignment (SUMO marouter, user equilibrium): traffic as flows, deterministic (no seed
    noise; identical inputs give byte-identical output), ~2 min. No queues spilling back, no signal timing: delay
    comes from marouter's volume/capacity travel-time function. Returns (metrics, edges) shaped like run();
    an edge's "waiting" is its delay in veh*s (flow x (travel time - free-flow time)), "entered" is veh per hour."""
    out.mkdir(parents=True, exist_ok=True)
    load = out / "netload.xml"
    subprocess.run([
        sumolib.checkBinary("marouter"), "-n", str(net), "-r", ",".join(map(str, routes)),
        "--assignment-method", "UE", "--netload-output", str(load), "-o", os.devnull,
        "--ignore-errors", "--no-warnings",
    ], check=True, stdout=subprocess.DEVNULL)
    edges, total_tt = {}, 0.0
    for e in sumolib.xml.parse(str(load), "edge"):
        q, tt, rel = float(e.entered), float(e.traveltime), float(e.speedRelative)  # entered = veh over the demand period
        delay = q * tt * (1 - rel)   # speedRelative = free-flow time / travel time
        total_tt += q * tt
        edges[e.id] = {"speed": float(e.speed), "time_loss": delay, "entered": q,
                       "waiting": delay, "occupancy": float(e.flowCapacityRatio)}  # v/c in % (not occupancy)
    # netload.xml kept (1.5 MB): per-edge flow / travel time / v/c for the 3D heatmap
    veh = sum(1 for _ in sumolib.xml.parse(str(routes[1]), "trip")) + sum(
        float(f.vehsPerHour) * DURATION / 3600 for f in sumolib.xml.parse(str(routes[0]), "flow"))
    total_delay = sum(s["time_loss"] for s in edges.values())
    return {"loaded": veh, "inserted": veh, "arrived": veh, "teleports": 0, "mean_travel_time": total_tt / veh,
            "total_travel_time": total_tt, "mean_time_loss": total_delay / veh}, edges


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
    # through vehicles actually written (areas without a surveyed road have no calibration share)
    through = sum(float(f.vehsPerHour) for f in sumolib.xml.parse(str(routes[0]), "flow")) * DURATION / 3600
    assert metrics["loaded"] > through * 1.1, "local trips missing: check randomTrips weights"
    for k, v in metrics.items():
        print(f"{k:>18}: {v:,.1f}")
    print(f"timing s: netconvert={t1 - t0:.0f} demand={t2 - t1:.0f} sumo={t3 - t2:.0f}")
    print(f"traffic lights: {len(sumolib.net.readNet(str(net)).getTrafficLights())}")
    if area in CALIB:
        print(f"calibration road peak flow: {flyover_flow(net, edges, AREAS[area]):,.0f} veh/h "
              f"(target {CALIB[area][2]:,} PCU/h, {CALIB[area][1]})")
    print("\ntop study-box bottlenecks (time loss s, edge, name, speed/limit, occupancy %):")
    for tl, eid, name, ratio, occ in bottlenecks(net, edges, AREAS[area]):
        print(f"  {tl:>9,.0f}  {eid:<22} {name[:30]:<30} {ratio:5.2f}  {occ:5.1f}")
