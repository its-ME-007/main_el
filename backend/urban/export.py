"""Exports for the frontend (RESPONSIBILITIES.md, interface contract). All geometry WGS84.

Writes into data/<area>/:
  roads.geojson          every non-internal SUMO edge: id, name, type, lanes, speed (m/s), length (m), in_box
  zones.geojson          no-build polygons (same as obstacles.geojson) with kind water/park/institutional, name
  edge_stats.json        {edge_id: {...}} from the micro baseline edges.xml
  scenario_stats/<run>.json  same schema for every evaluated scenario dir (base_meso, c22_meso, c22_micro, ...),
                         so the UI can compare a candidate with the baseline of the same simulator
  scenarios.json         {"meso": scenarios.csv records, "micro": scenarios_micro.csv records,
                          "baseline": {"meso": {...}, "micro": {...}} totals (mean_time_loss, box_waiting, ...)}
  noise.json             repeated runs from urban.noise: {variant: {label, sim, seeds, baseline: {mean_time_loss, sd,
                         min, max}, cands: {cand: {n, dT, dT_sd, dT_min, dT_max, score, score_sd, cand_vph, verdict}}}}
                         variant "" = the evaluated candidates (1 lane, 40 km/h); "l2v60" = 2 lanes, 60 km/h, ...

Stats keep only edges that saw traffic (entered > 0); a missing edge means no vehicles.
Usage: uv run python -m urban.export [area]   (default: hebbal)
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

os.environ.setdefault("SUMO_HOME", r"C:\Program Files (x86)\SUMO")
import osmnx as ox  # noqa: E402
import pandas as pd  # noqa: E402
import sumolib  # noqa: E402

from urban.data import AREAS, DATA, OBSTACLE_TAGS  # noqa: E402
from urban.sim import in_box  # noqa: E402

STAT_FIELDS = {"speed": "speed", "speedRelative": "speed_rel", "timeLoss": "time_loss", "entered": "entered",
               "waitingTime": "waiting", "occupancy": "occupancy"}


def roads(nw, bbox):
    feats = []
    for e in nw.getEdges():  # getEdges() skips internal junction edges
        coords = [[round(c, 6) for c in nw.convertXY2LonLat(x, y)] for x, y in e.getShape()]
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"id": e.getID(), "name": e.getName() or None, "type": e.getType(),
                                     "lanes": e.getLaneNumber(), "speed": round(e.getSpeed(), 2),
                                     "length": round(e.getLength(), 1), "in_box": in_box(nw, e, bbox)}})
    return {"type": "FeatureCollection", "features": feats}


def zone_kind(row):
    g = lambda k: row.get(k) if isinstance(row.get(k), str) else None
    if g("natural") == "water" or g("water") or g("landuse") == "reservoir":
        return "water"
    if g("leisure") == "park":
        return "park"
    return "institutional"   # school, hospital, military, cemetery


def zones(area):
    """The same no-build polygons as obstacles.geojson, plus a kind (water/park/institutional) and name for display."""
    feats = ox.features_from_xml(DATA / area / "features.osm", polygon=ox.utils_geo.bbox_to_poly(AREAS[area]),
                                 tags=OBSTACLE_TAGS)
    feats = feats[feats.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    feats["kind"] = feats.apply(zone_kind, axis=1)
    feats["name"] = feats["name"].where(feats["name"].notna(), None) if "name" in feats else None
    return json.loads(feats[["geometry", "kind", "name"]].to_json(drop_id=True))


def edge_stats(path):
    out = {}
    for el in ET.parse(path).getroot().iter("edge"):
        if el.get("id").startswith(":") or float(el.get("entered", 0)) <= 0:
            continue
        out[el.get("id")] = {k: round(float(el.get(src, 0)), 3) for src, k in STAT_FIELDS.items()}
    return out


def macro_edge_stats(path):
    """Same schema as edge_stats() from marouter's netload.xml. Delay per edge = flow x travel time x (1 - speed/limit),
    as in sim.assign(); a static assignment has no waiting time, and occupancy is reported as v/c (flowCapacityRatio)."""
    out = {}
    for el in ET.parse(path).getroot().iter("edge"):
        q = float(el.get("entered", 0))
        if el.get("id").startswith(":") or q <= 0:
            continue
        rel, tt = float(el.get("speedRelative", 1)), float(el.get("traveltime", 0))
        out[el.get("id")] = {"speed": round(float(el.get("speed", 0)), 3), "speed_rel": round(rel, 3),
                             "time_loss": round(q * tt * (1 - rel), 3), "entered": round(q, 3), "waiting": 0.0,
                             "occupancy": round(float(el.get("flowCapacityRatio", 0)), 3)}
    return out


def dump(obj, path):
    path.write_text(json.dumps(obj, separators=(",", ":")))
    print(f"  {path.relative_to(DATA)}  {path.stat().st_size / 1e6:.1f} MB")


def export(area="hebbal"):
    d = DATA / area
    nw = sumolib.net.readNet(str(d / "sim" / "net.net.xml"))
    dump(roads(nw, AREAS[area]), d / "roads.geojson")
    dump(zones(area), d / "zones.geojson")
    if (d / "sim" / "baseline" / "edges.xml").exists():
        dump(edge_stats(d / "sim" / "baseline" / "edges.xml"), d / "edge_stats.json")

    # independent of the candidate results, so exported even before urban.evaluate has run
    if (d / "parallel.csv").exists():   # urban.parallel: speedup/efficiency per worker count (Phase 5)
        dump(pd.read_csv(d / "parallel.csv").round(4).to_dict(orient="records"), d / "parallel.json")
    sd = d / "scenario_stats"
    sd.mkdir(exist_ok=True)
    names = {"macro": ["scenarios_macro.csv"], "meso": ["scenarios_meso.csv", "scenarios.csv"],  # scenarios.csv: old
             "micro": ["scenarios_micro.csv"]}
    found = {k: next((d / n for n in ns if (d / n).exists()), None) for k, ns in names.items()}
    if not any(found.values()):   # simulation not run yet: geometry only
        print(f"  {area}: no scenarios_*.csv yet (run urban.evaluate); exported geometry only")
        write_areas()
        return
    for run in sorted((d / "sim" / "scenarios").glob("*/edges.xml")):
        if not any(run.parent.glob("metrics_*.json")):  # still running: edges.xml is half-written
            continue
        dump(edge_stats(run), sd / f"{run.parent.name}.json")
    for run in sorted((d / "sim" / "scenarios").glob("*_macro/netload.xml")):   # macro: marouter netload, no edges.xml
        if any(run.parent.glob("metrics_*.json")):
            dump(macro_edge_stats(run), sd / f"{run.parent.name}.json")

    res = {}
    for key, f in found.items():
        if f:
            res[key] = pd.read_csv(f).round(3).to_dict(orient="records")
    # baseline totals per simulator, so the UI can show before/after numbers next to dT, dQ
    res["baseline"] = {}
    for m in sorted((d / "sim" / "scenarios").glob("base_*/metrics_*.json")):
        res["baseline"][m.parent.name.removeprefix("base_")] = json.loads(m.read_text())
    dump(res, d / "scenarios.json")
    noise = noise_runs(d)
    if noise:
        dump(noise, d / "noise.json")
    write_areas()


def noise_runs(d):
    """Every noise_<sim>[_l<lanes>v<kmh>].csv with at least 2 seeds and a candidate (a single seed says nothing)."""
    import re
    from urban.evaluate import DEFAULT_CAND
    from urban.noise import summary
    out = {}
    for f in sorted(d.glob("noise_*.csv")):
        mt = re.fullmatch(r"noise_(meso|micro)(?:_l(\d+)v(\d+))?", f.stem)
        df = pd.read_csv(f)
        if not mt or df[df.run == "base"].seed.nunique() < 2 or (df.run == "base").all():
            continue
        lanes, kmh = (int(mt[2]), int(mt[3])) if mt[2] else DEFAULT_CAND
        key = mt[1] + (f"_l{lanes}v{kmh}" if mt[2] else "")
        out[key] = {"label": f"{lanes} lane{'s' if lanes > 1 else ''} each way, {kmh} km/h", "lanes": lanes, "kmh": kmh,
                    **summary(df)}
    return out


def write_areas():
    """data/areas.json: every area with frontend exports, for the UI's area picker."""
    out = {}
    for a, bbox in AREAS.items():
        d = DATA / a
        if (d / "roads.geojson").exists():
            out[a] = {"bbox": bbox, "scenarios": (d / "scenarios.json").exists(),
                      "micro": (d / "scenarios_micro.csv").exists(), "live": (d / "live_traffic.json").exists()}
    dump(out, DATA / "areas.json")


if __name__ == "__main__":
    export(next((a for a in sys.argv[1:] if a in AREAS), "hebbal"))
