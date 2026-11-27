"""Pick candidates for unattended runs (run_tt_*.ps1): prints a comma-separated list.

  uv run python -m urban.pick <area> top10    macro top 10 by score (scenarios_macro.csv)
  uv run python -m urban.pick <area> winner   best micro candidate: highest mean score among those with a real
                                              positive delay saving over seeds (noise_micro.csv, urban.noise's rule);
                                              if none is real, the highest mean score
  uv run python -m urban.pick <area> healthy  1 if the micro baseline is not gridlocked, else 0
"""
import sys

import pandas as pd

from urban.data import AREAS, DATA


def top10(area):
    d = pd.read_csv(DATA / area / "scenarios_macro.csv").sort_values("score", ascending=False)
    return [int(c) for c in d.cand.head(10)]


def winner(area):
    d = pd.read_csv(DATA / area / "noise_micro.csv")
    g = d[d.run != "base"].groupby("run").agg(dT=("dT", "mean"), sd=("dT", "std"), n=("dT", "size"), score=("score", "mean"))
    real = g[(g.n > 2) & (g.dT > 2 * g.sd / g.n ** 0.5)]
    best = (real if len(real) else g).score.idxmax()
    return [int(best[1:])]


def healthy(area, max_teleports=100, max_loss=600):
    """1 if the micro baseline is not gridlocked (Baiyappanahalli's stable run: 44 teleports, 360 s), else 0."""
    import xml.etree.ElementTree as ET
    r = ET.parse(DATA / area / "sim" / "baseline" / "stats.xml").getroot()
    tp, loss = int(r.find("teleports").get("total")), float(r.find("vehicleTripStatistics").get("timeLoss"))
    print(f"baseline: {tp} teleports, {loss:.0f} s time loss", file=sys.stderr)
    return [int(tp <= max_teleports and loss <= max_loss)]


if __name__ == "__main__":
    area, what = sys.argv[1], sys.argv[2]
    assert area in AREAS, f"unknown area {area}"
    print(",".join(map(str, {"top10": top10, "winner": winner, "healthy": healthy}[what](area))))
