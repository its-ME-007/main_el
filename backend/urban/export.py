"""Exports for the frontend (RESPONSIBILITIES.md, interface contract). All geometry WGS84.

Writes into data/<area>/:
  roads.geojson          every non-internal SUMO edge: id, name, type, lanes, speed (m/s), length (m), in_box
  zones.geojson          no-build polygons (same as obstacles.geojson) with kind water/park/institutional, name
  edge_stats.json        {edge_id: {...}} from the micro baseline edges.xml
  scenario_stats/<run>.json  same schema for every evaluated scenario dir (base_meso, c22_meso, c22_micro, ...),
                         so the UI can compare a candidate with the baseline of the same simulator
  scenarios.json         {"meso": scenarios.csv records, "micro": scenarios_micro.csv records,
                          "baseline": {"meso": {...}, "micro": {...}} totals (mean_time_loss, box_waiting, ...)}

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


def dump(obj, path):
    path.write_text(json.dumps(obj, separators=(",", ":")))
    print(f"  {path.relative_to(DATA)}  {path.stat().st_size / 1e6:.1f} MB")


def export(area="hebbal"):
    d = DATA / area
    nw = sumolib.net.readNet(str(d / "sim" / "net.net.xml"))
    dump(roads(nw, AREAS[area]), d / "roads.geojson")
    dump(zones(area), d / "zones.geojson")
    dump(edge_stats(d / "sim" / "baseline" / "edges.xml"), d / "edge_stats.json")

    sd = d / "scenario_stats"
    sd.mkdir(exist_ok=True)
    for run in sorted((d / "sim" / "scenarios").glob("*/edges.xml")):
        if not any(run.parent.glob("metrics_*.json")):  # still running: edges.xml is half-written
            continue
        dump(edge_stats(run), sd / f"{run.parent.name}.json")

    res = {}
    for key, name in (("meso", "scenarios.csv"), ("micro", "scenarios_micro.csv")):
        if (d / name).exists():
            res[key] = pd.read_csv(d / name).round(3).to_dict(orient="records")
    # baseline totals per simulator, so the UI can show before/after numbers next to dT, dQ
    res["baseline"] = {}
    for m in sorted((d / "sim" / "scenarios").glob("base_*/metrics_*.json")):
        res["baseline"][m.parent.name.removeprefix("base_")] = json.loads(m.read_text())
    dump(res, d / "scenarios.json")


if __name__ == "__main__":
    export(next((a for a in sys.argv[1:] if a in AREAS), "hebbal"))
