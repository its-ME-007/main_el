"""Phase 3: generate candidate road connections near congestion and filter them by spatial feasibility.

Reads the baseline (urban.sim) and the cached area features (urban.data). Writes
data/<area>/candidates.geojson: every examined pair with status "feasible"/"selected"/"rejected:<reason>".

Usage: uv run python -m urban.candidates [area]   (default: hebbal)
"""
import os
import sys

os.environ.setdefault("SUMO_HOME", r"C:\Program Files (x86)\SUMO")
import geopandas as gpd  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
import sumolib  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402
from shapely.ops import substring  # noqa: E402

from urban.data import AREAS, DATA  # noqa: E402
from urban.sim import in_box  # noqa: E402

HOT_EDGES = 30       # top study-box edges by baseline time loss; their end junctions seed candidates
MIN_LEN, MAX_LEN = 50, 600   # m, straight-line length of a new road
DETOUR = 2.0         # keep pair only if current network distance >= DETOUR x straight line (both directions)
ROAD_HALF_WIDTH = 4  # m buffer for building/obstacle clearance
END_TRIM = 8         # m trimmed off each end before clearance tests (endpoints sit on existing roads)
WORKSITE_BUFFER = 15  # m: crossing points of one corridor closer than 2x this count once (parallel tracks, split ways)
MAX_DEMOLISH = int(os.environ.get("MAX_DEMOLISH", 3))  # buildings a road may cut through; cost proxy P (idea.md §7)
TOP_K = 40           # feasible candidates passed on to Phase 4
MAX_PER_SEED = 3     # diversity: at most this many selected candidates per seed junction
NO_CONNECT = ("flyover", "ramp")  # junctions on elevated structures can't take a new at-grade road


def worksite_crossings(core, corridors):
    """True crossings of worksite centrelines, once per corridor crossing (user, 2026-11-24: roads running ALONGSIDE
    the metro are preferred, so being near a worksite is free; only going over/under it is penalised)."""
    return sum(shapely.get_num_geometries(x.buffer(WORKSITE_BUFFER))
               for x in (core.intersection(c) for c in corridors) if not x.is_empty)


def generate(area="hebbal", baseline="baseline"):
    d = DATA / area
    nw = sumolib.net.readNet(str(d / "sim" / "net.net.xml"))
    bbox = AREAS[area]
    to_xy = lambda c: np.array([nw.convertLonLat2XY(x, y) for x, y in c])  # WGS84 -> SUMO metric XY
    layer = lambda f: [shapely.transform(g, to_xy) for g in gpd.read_file(d / f).geometry if g is not None]

    # 1. congestion seeds: junctions at the ends of the worst study-box edges
    loss = {e.id: float(e.timeLoss or 0) for e in sumolib.xml.parse(str(d / "sim" / baseline / "edges.xml"), "edge")
            if e.speed is not None}
    box_edges = [e for e in nw.getEdges() if in_box(nw, e, bbox)]
    hot = sorted(box_edges, key=lambda e: -loss.get(e.getID(), 0))[:HOT_EDGES]
    node_loss = {}
    for e in hot:
        for n in (e.getFromNode(), e.getToNode()):
            node_loss[n.getID()] = node_loss.get(n.getID(), 0) + loss[e.getID()]

    def connectable(n):
        return all(not any(k in e.getName().lower() for k in NO_CONNECT) and not e.getType().endswith("_link")
                   for e in n.getIncoming() + n.getOutgoing())

    box_nodes = {n.getID(): n for e in box_edges for n in (e.getFromNode(), e.getToNode()) if connectable(n)}
    seeds = [box_nodes[i] for i in node_loss if i in box_nodes]

    # 2. pairs with a long detour on the current network
    g = nx.DiGraph()
    for e in nw.getEdges():
        u, v, length = e.getFromNode().getID(), e.getToNode().getID(), e.getLength()
        if not g.has_edge(u, v) or g[u][v]["w"] > length:
            g.add_edge(u, v, w=length)
    cutoff = DETOUR * MAX_LEN * 3
    dist_from = {s.getID(): nx.single_source_dijkstra_path_length(g, s.getID(), cutoff=cutoff, weight="w") for s in seeds}
    dist_to = {s.getID(): nx.single_source_dijkstra_path_length(g.reverse(copy=False), s.getID(), cutoff=cutoff, weight="w")
               for s in seeds}

    # 3. spatial constraints, in metric XY
    buildings, obstacles = STRtree(layer("buildings.geojson")), STRtree(layer("obstacles.geojson"))
    # one merged centreline per worksite corridor (OSM name), e.g. Metro Phase 2B, Mallige Line
    cons = gpd.read_file(d / "construction.geojson")
    corridors = [shapely.transform(shapely.union_all(list(g.geometry)), to_xy)
                 for _, g in cons.groupby(cons["name"].fillna(""))] if len(cons) else []
    road_edges = [e for e in nw.getEdges()]
    roads = STRtree([LineString(e.getShape()) for e in road_edges])

    rows, seen = [], set()
    for s in seeds:
        su = s.getID()
        for vid, v in box_nodes.items():
            key = tuple(sorted((su, vid)))
            if vid == su or key in seen:
                continue
            seen.add(key)
            a, b = Point(s.getCoord()), Point(v.getCoord())
            straight = a.distance(b)
            if not MIN_LEN <= straight <= MAX_LEN:
                continue
            # unreachable within cutoff -> store cutoff as a lower bound on the detour
            net_dist = min(dist_from[su].get(vid, cutoff), dist_to[su].get(vid, cutoff))
            if net_dist < DETOUR * straight:
                continue
            line = LineString([a, b])
            core = substring(line, END_TRIM, straight - END_TRIM)
            body = core.buffer(ROAD_HALF_WIDTH)
            touching = {e.getID() for e in s.getIncoming() + s.getOutgoing() + v.getIncoming() + v.getOutgoing()}
            hit = len(buildings.query(body, predicate="intersects"))
            obstacle = bool(len(obstacles.query(body, predicate="intersects")))
            # Crossings are allowed as grade separations (bridge/underpass) and priced in Phase 4's penalty P.
            # SUMO needs no extra modelling: an edge crossing another without a shared junction is grade-separated.
            # Opposite directions (id / -id) of one road count once.
            crossed = {road_edges[i].getID().lstrip("-").split("#")[0]
                       for i in roads.query(core, predicate="intersects") if road_edges[i].getID() not in touching}
            flags = {"road_crossings": len(crossed),
                     "worksite_crossings": worksite_crossings(core, corridors)}
            failed = (["building"] if hit > MAX_DEMOLISH else []) + (["obstacle"] if obstacle else [])
            status = f"rejected:{failed[0]}" if failed else "feasible"
            rows.append({"u": su, "v": vid, "length_m": round(straight, 1), "net_dist": round(net_dist, 1),
                         "detour": round(net_dist / straight, 2), "seed_loss": round(node_loss[su]), "buildings_hit": hit,
                         "prescore": round((net_dist - straight) * node_loss[su]), "status": status, **flags,
                         "geometry": LineString([nw.convertXY2LonLat(*a.coords[0]), nw.convertXY2LonLat(*b.coords[0])])})

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    if len(gdf):
        feas = gdf[gdf.status == "feasible"].sort_values("prescore", ascending=False)
        top = feas.groupby("u").head(MAX_PER_SEED).head(TOP_K).index
        gdf.loc[top, "status"] = "selected"
    gdf.to_file(d / "candidates.geojson", driver="GeoJSON")
    return gdf


if __name__ == "__main__":
    area = sys.argv[1] if len(sys.argv) > 1 else "hebbal"
    gdf = generate(area)
    assert len(gdf), "no candidate pairs passed the distance/detour filter"
    sel = gdf[gdf.status == "selected"]
    assert len(sel), "no feasible candidates"
    assert (sel.length_m.between(MIN_LEN, MAX_LEN) & (sel.detour >= DETOUR)).all()
    assert (sel.buildings_hit <= MAX_DEMOLISH).all() and (sel.groupby("u").size() <= MAX_PER_SEED).all()
    print(gdf.status.value_counts().to_string())
    print(f"\nselected: {len(sel)} from {sel.u.nunique()} seeds; buildings hit per road: "
          f"{sel.buildings_hit.value_counts().sort_index().to_dict()}")
    print(f"road crossings per road: {sel.road_crossings.describe()[['min', '50%', 'max']].to_dict()}, "
          f"crossing metro worksite: {(sel.worksite_crossings > 0).sum()}")
    print("\ntop selected (u -> v, length m, detour x, buildings, road x-ings, worksite x-ings, seed loss s):")
    for r in sel.nlargest(10, "prescore").itertuples():
        print(f"  {r.u[:22]:<22} -> {r.v[:22]:<22} {r.length_m:6.0f} {r.detour:5.1f}x {r.buildings_hit} "
              f"{r.road_crossings:3} {r.worksite_crossings:2} {r.seed_loss:>8,}")
