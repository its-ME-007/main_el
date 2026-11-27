"""Sim vs real speeds: a micro baseline's per-edge speeds against the committed TomTom snapshot (sim.TOMTOM_FILE).

Usage: uv run python -m urban.validate <area> [sim|sim_tomtom]   (default sim = the current baseline)
Prints mean real vs sim speed, speed as a share of free flow, and how many sampled edges are within 10 km/h.
Closed segments are left out.
"""
import json
import statistics as st
import sys

import sumolib

from urban.data import AREAS, DATA
from urban.sim import TOMTOM_FILE


def validate(area, sim_dir="sim"):
    pts = [p for p in json.loads(TOMTOM_FILE.read_text())["areas"][area]["points"]
           if p.get("current_kmh") and not p.get("closed")]
    d = DATA / area / sim_dir
    nw = sumolib.net.readNet(str(d / "net.net.xml"))
    sim = {e.id: float(e.speed) * 3.6 for e in sumolib.xml.parse(str(d / "baseline" / "edges.xml"), "edge")
           if e.speed and float(e.sampledSeconds or 0) > 0}
    rows = [(p["current_kmh"], sim[p["edge"]], p["free_flow_kmh"], nw.getEdge(p["edge"]).getSpeed() * 3.6)
            for p in pts if p["edge"] in sim]
    real, s, ff, lim = zip(*rows)
    r = {"area": area, "sim": sim_dir, "n": len(rows), "real_kmh": st.mean(real), "sim_kmh": st.mean(s),
         "bias_kmh": st.mean(s) - st.mean(real), "mae_kmh": st.mean(abs(a - b) for a, b in zip(real, s)),
         "within_10": sum(abs(a - b) <= 10 for a, b in zip(real, s)),
         "real_share_ff": st.mean(a / f for a, f in zip(real, ff)), "sim_share_ff": st.mean(b / x for b, x in zip(s, lim)),
         "ff_tomtom_kmh": st.mean(ff), "ff_sim_kmh": st.mean(lim)}
    print(f"{area} [{sim_dir}] {r['n']} edges: real {r['real_kmh']:.1f} vs sim {r['sim_kmh']:.1f} km/h "
          f"(bias {r['bias_kmh']:+.1f}, MAE {r['mae_kmh']:.1f}, within 10 km/h {r['within_10']}/{r['n']}) | "
          f"share of free flow real {r['real_share_ff']:.2f} vs sim {r['sim_share_ff']:.2f} | "
          f"free flow TomTom {r['ff_tomtom_kmh']:.0f} vs sim {r['ff_sim_kmh']:.0f} km/h")
    return r


if __name__ == "__main__":
    args = sys.argv[1:]
    area = next((a for a in args if a in AREAS), "hebbal")
    validate(area, next((a for a in args if a.startswith("sim")), "sim"))
