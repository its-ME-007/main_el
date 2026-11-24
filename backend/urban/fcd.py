"""Vehicle trajectories for the 3D animation (CGVR): SUMO floating car data (FCD) for the baseline and chosen
candidates, cut to the study box and a time window, written as compact JSON for frontend/src/traffic.js.

One micro run per scenario (same demand and seed as urban.evaluate / urban.noise seed 42), recording every vehicle's
position every PERIOD s between BEGIN and END (sim seconds; the first 20 min warm the network up). The run stops at
END, so its trip metrics cover only that part: the animation is for looking at, the scores come from urban.noise.

Writes data/<area>/traffic_<run>.json:
  {run, period, begin, end, max, frames: [[idx, x, z, angle, kmh, cand, idx, x, z, ...], ...]}
  x = metres east, z = metres south of the study-box centre (same projection as frontend/src/scene.js),
  angle = degrees clockwise from north (SUMO), idx = vehicle number, stable across frames (for interpolation),
  cand = 1 on the new road (so the UI can lift it onto a bridge deck; SUMO has no heights).
and data/<area>/traffic.json listing the runs.

Usage: uv run python -m urban.fcd [area] [--cands 39] [--begin 1200] [--end 1800] [--period 2]
"""
import json
import math
import sys
import time
import xml.etree.ElementTree as ET

from urban.data import AREAS, DATA
from urban.evaluate import CAND_EDGES, scenario_net, setup
from urban.sim import SEED, run

MARGIN = 150   # m around the study box, so cars enter and leave smoothly instead of popping at the edge


def projector(bbox):
    lon0, lat0 = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110574
    return lambda lon, lat: ((lon - lon0) * kx, -(lat - lat0) * ky)


def convert(fcd, bbox, begin, end, period):
    proj = projector(bbox)
    hx = (bbox[2] - bbox[0]) / 2 * 111320 * math.cos(math.radians((bbox[1] + bbox[3]) / 2)) + MARGIN
    hz = (bbox[3] - bbox[1]) / 2 * 110574 + MARGIN
    ids, frames = {}, []
    for _, el in ET.iterparse(fcd, events=("end",)):
        if el.tag != "timestep":
            continue
        if float(el.get("time")) > end:
            break
        row = []
        for v in el.iter("vehicle"):
            x, z = proj(float(v.get("x")), float(v.get("y")))   # --fcd-output.geo: x = lon, y = lat
            if abs(x) > hx or abs(z) > hz:
                continue
            i = ids.setdefault(v.get("id"), len(ids))
            row += [i, round(x, 1), round(z, 1), round(float(v.get("angle"))), round(float(v.get("speed")) * 3.6),
                    int(v.get("lane", "").startswith(CAND_EDGES))]
        frames.append(row)
        el.clear()
    return {"period": period, "begin": begin, "end": end, "vehicles": len(ids),
            "max": max((len(f) // 6 for f in frames), default=0), "stride": 6, "frames": frames}


def record(area="hebbal", cands=(39,), begin=1200, end=1800, period=2):
    env = setup(area)
    d, base, routes, box, rows, incoming = env
    runs = [("base", None, "Baseline (no new road)")] + [
        (f"c{i:02d}", rows.loc[i], f"With candidate c{i:02d}") for i in cands]
    listing = []
    for tag, cand, label in runs:
        out = d / "sim" / "fcd" / tag
        t0 = time.perf_counter()
        net = scenario_net(base, cand, incoming, out)
        fcd = out / "fcd.xml"
        m, _ = run(net, routes, out, seed=SEED, extra_args=[
            "--fcd-output", str(fcd), "--fcd-output.geo", "--fcd-output.attributes", "x,y,angle,speed,lane",
            "--device.fcd.period", str(period), "--device.fcd.begin", str(begin)],
            end=end)   # SUMO has no device.fcd.end: stop the whole run at the window's end
        data = {"run": tag, "label": label, **convert(fcd, AREAS[area], begin, end, period)}
        path = d / f"traffic_{tag}.json"
        path.write_text(json.dumps(data, separators=(",", ":")))
        for f in (net, fcd, out / "tripinfo.xml"):   # large; the JSON is all the UI needs
            f.unlink(missing_ok=True)
        listing.append({"run": tag, "label": label, "file": path.name, "mean_time_loss": m["mean_time_loss"]})
        print(f"{tag}: {data['vehicles']:,} vehicles in the box, up to {data['max']} at once, "
              f"{len(data['frames'])} frames, {path.stat().st_size / 1e6:.1f} MB, {time.perf_counter() - t0:.0f} s",
              flush=True)
    (d / "traffic.json").write_text(json.dumps({"runs": listing, "begin": begin, "end": end, "period": period}))


if __name__ == "__main__":
    args = sys.argv[1:]
    opt = lambda k, dflt: args[args.index(k) + 1] if k in args else dflt
    area = next((a for a in args if a in AREAS), "hebbal")
    record(area, tuple(int(x) for x in opt("--cands", "39").split(",")), int(opt("--begin", 1200)),
           int(opt("--end", 1800)), int(opt("--period", 2)))
