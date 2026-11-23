"""Real traffic speeds from the TomTom Traffic Flow API, to compare with (and later calibrate) the simulation.

Needs a free API key from developer.tomtom.com, saved in backend/.env (gitignored) as:
    TOMTOM_API_KEY=your-key
Samples one point per major road (motorway..tertiary) in the study box, spaced >= SPACING m apart, at most --max
points. Each point is one request; the free tier allows 2,500 per day. Speeds are a snapshot of NOW, so note the
time of day (Bengaluru peaks are roughly 8-11 am and 5-9 pm).

Writes data/<area>/live_traffic.json:
  {"source", "fetched_at", "area", "points": [{"edge", "lon", "lat", "current_kmh", "free_flow_kmh", "ratio",
   "confidence", "closed", "segment": [[lon, lat], ...]}]}
ratio = current / free-flow speed, the same measure as speed_rel in edge_stats.json.

Usage: uv run python -m urban.live [area] [--max 120]
"""
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("SUMO_HOME", r"C:\Program Files (x86)\SUMO")
import sumolib  # noqa: E402

from urban.data import AREAS, DATA  # noqa: E402
from urban.sim import in_box  # noqa: E402

URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/14/json"
ROAD_TYPES = ("motorway", "trunk", "primary", "secondary", "tertiary")   # TomTom covers these well
SPACING = 120    # m between sampled points; TomTom answers with a whole segment, so closer points repeat it
PAUSE = 0.25     # s between requests (stay well under the per-second limit)


def api_key():
    key = os.environ.get("TOMTOM_API_KEY")
    env = Path(__file__).resolve().parent.parent / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("TOMTOM_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("No TOMTOM_API_KEY: get a free key at developer.tomtom.com and put TOMTOM_API_KEY=... in backend/.env")
    return key


def sample_points(nw, bbox, limit):
    """Midpoints of major in-box roads, most important classes first, spaced SPACING m apart."""
    rank = {t: i for i, t in enumerate(ROAD_TYPES)}
    edges = []
    for e in nw.getEdges():
        t = e.getType().removeprefix("highway.")
        if t in rank and in_box(nw, e, bbox) and e.getLength() > 30:
            edges.append((rank[t], -e.getLength(), e))
    chosen = []
    for *_, e in sorted(edges, key=lambda x: x[:2]):
        x, y = e.getShape()[len(e.getShape()) // 2]
        if all(math.dist((x, y), c[1]) >= SPACING for c in chosen):
            chosen.append((e, (x, y)))
        if len(chosen) >= limit:
            break
    return [(e.getID(), *nw.convertXY2LonLat(x, y)) for e, (x, y) in chosen]


def fetch_point(key, lon, lat):
    q = urllib.parse.urlencode({"point": f"{lat},{lon}", "unit": "KMPH", "key": key})
    with urllib.request.urlopen(f"{URL}?{q}", timeout=15) as r:
        return json.load(r)["flowSegmentData"]


def live(area="hebbal", limit=120):
    key = api_key()
    d = DATA / area
    nw = sumolib.net.readNet(str(d / "sim" / "net.net.xml"))
    pts = sample_points(nw, AREAS[area], limit)
    print(f"{area}: querying {len(pts)} road points")
    out, failed = [], 0
    for i, (edge, lon, lat) in enumerate(pts):
        try:
            f = fetch_point(key, lon, lat)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f"TomTom rejected the key (HTTP {e.code}): check TOMTOM_API_KEY in backend/.env")
            failed += 1
            continue
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError):
            failed += 1
            continue
        cur, free = f.get("currentSpeed"), f.get("freeFlowSpeed")
        out.append({"edge": edge, "lon": round(lon, 6), "lat": round(lat, 6), "current_kmh": cur, "free_flow_kmh": free,
                    "ratio": round(cur / free, 3) if cur and free else None, "confidence": f.get("confidence"),
                    "closed": bool(f.get("roadClosure")),
                    "segment": [[round(c["longitude"], 6), round(c["latitude"], 6)]
                                for c in f.get("coordinates", {}).get("coordinate", [])]})
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(pts)}", flush=True)
        time.sleep(PAUSE)
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))   # IST
    res = {"source": "TomTom Traffic Flow API (flowSegmentData)", "fetched_at": now.isoformat(timespec="minutes"),
           "area": area, "points": out}
    (d / "live_traffic.json").write_text(json.dumps(res, separators=(",", ":")))
    ok = [p["ratio"] for p in out if p["ratio"]]
    print(f"saved {len(out)} segments ({failed} failed) at {res['fetched_at']} IST; "
          f"mean speed {100 * sum(ok) / max(1, len(ok)):.0f} % of free flow")
    return res


if __name__ == "__main__":
    args = sys.argv[1:]
    area = next((a for a in args if a in AREAS), "hebbal")
    live(area, int(args[args.index("--max") + 1]) if "--max" in args else 120)
