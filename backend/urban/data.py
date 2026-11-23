"""Phase 1: cut a real urban area out of an offline OpenStreetMap extract and cache it locally.

Needs the Geofabrik extract (one-time, ~hundreds of MB):
  curl -L -o data/osm/southern-zone-latest.osm.pbf \
    https://download.geofabrik.de/asia/india/southern-zone/southern-zone-latest.osm.pbf

Usage: uv run python -m urban.data [area]   (default: hebbal)
"""
import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmium
import osmnx as ox

DATA = Path(__file__).resolve().parent.parent / "data"
OSM = DATA / "osm"
REGION_PBF = OSM / "southern-zone-latest.osm.pbf"
CITY_PBF = OSM / "bengaluru.osm.pbf"            # cut once from REGION_PBF, then areas cut from this
CITY_BBOX = (77.45, 12.80, 77.80, 13.20)

# (west, south, east, north) in WGS84, each ~1.5 km x 1.5 km.
AREAS = {
    "koramangala": (77.6150, 12.9250, 77.6300, 12.9400),  # dense grid, dev/test area
    "hebbal": (77.5890, 13.0290, 77.6050, 13.0430),       # flyover + metro interchange works
}

ROAD_PAD = 0.01  # degrees (~1.1 km) of road network kept around each area

OBSTACLE_TAGS = {
    "natural": ["water"],
    "water": True,
    "landuse": ["reservoir", "military", "cemetery"],
    "leisure": ["park"],
    "amenity": ["hospital", "school"],
}
FEATURE_KEYS = {"building", "railway", *OBSTACLE_TAGS}

# Same exclusions as OSMnx's network_type="drive" filter.
NOT_DRIVE = {"abandoned", "bridleway", "bus_guideway", "construction", "corridor", "cycleway", "elevator",
             "escalator", "footway", "no", "path", "pedestrian", "planned", "platform", "proposed", "raceway",
             "razed", "service", "steps", "track"}
NOT_DRIVE_SERVICE = {"alley", "driveway", "emergency_access", "parking", "parking_aisle", "private"}


def is_drive(o):
    t = o.tags
    return (o.is_way() and t.get("highway") not in (None, *NOT_DRIVE) and t.get("area") != "yes"
            and t.get("access") != "private" and t.get("motor_vehicle") != "no"
            and t.get("motorcar") != "no" and t.get("service") not in NOT_DRIVE_SERVICE)


def is_feature(o):
    return any(k in o.tags for k in FEATURE_KEYS)


def clip(src, bbox, dst, keep=lambda o: True):
    """Write ways touching bbox (and relations using them) that pass `keep`, plus everything they reference."""
    w, s, e, n = bbox
    inside = lambda loc: loc.valid() and w <= loc.lon <= e and s <= loc.lat <= n
    ways = (osmium.FileProcessor(str(src), osmium.osm.NODE | osmium.osm.WAY).with_locations()
            .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY)))  # nodes feed the cache, not Python
    touching = {way.id for way in ways if any(inside(nd.location) for nd in way.nodes)}
    rels = {r.id for r in osmium.FileProcessor(str(src), osmium.osm.RELATION)
            if keep(r) and any(m.type == "w" and m.ref in touching for m in r.members)}
    # remove_tags=False keeps node tags (highway=traffic_signals, crossings) on referenced nodes
    with osmium.BackReferenceWriter(str(dst), ref_src=str(src), overwrite=True, remove_tags=False) as out:
        for o in osmium.FileProcessor(str(src), osmium.osm.WAY | osmium.osm.RELATION):
            if (o.is_way() and o.id in touching and keep(o)) or (o.is_relation() and o.id in rels):
                out.add(o)


def fetch(area="hebbal"):
    bbox, out = AREAS[area], DATA / area
    out.mkdir(parents=True, exist_ok=True)
    if not CITY_PBF.exists():
        clip(REGION_PBF, CITY_BBOX, CITY_PBF)
    # Roads use a padded box: one-way arterials crossing a hard bbox edge become dead ends and the
    # strong-connectivity trim would drop them (it dropped the whole Hebbal flyover + ORR).
    padded = (bbox[0] - ROAD_PAD, bbox[1] - ROAD_PAD, bbox[2] + ROAD_PAD, bbox[3] + ROAD_PAD)
    clip(CITY_PBF, padded, out / "roads.osm", is_drive)
    clip(CITY_PBF, bbox, out / "features.osm", is_feature)

    g = ox.graph_from_xml(out / "roads.osm")
    g = ox.truncate.truncate_graph_bbox(g, padded)
    g = ox.truncate.largest_component(g, strongly=True)  # every OD pair must be routable
    g = ox.add_edge_speeds(g)        # fills speed_kph from maxspeed / highway defaults
    g = ox.add_edge_travel_times(g)  # travel_time in seconds
    ox.save_graphml(g, out / "roads.graphml")

    poly = ox.utils_geo.bbox_to_poly(bbox)
    feats = ox.features_from_xml(out / "features.osm", polygon=poly, tags={"building": True, **OBSTACLE_TAGS})
    feats = feats[feats.geom_type.isin(["Polygon", "MultiPolygon"])]
    is_bldg = feats["building"].notna() if "building" in feats else False
    feats[is_bldg][["geometry"]].to_file(out / "buildings.geojson", driver="GeoJSON")
    feats[~is_bldg][["geometry"]].to_file(out / "obstacles.geojson", driver="GeoJSON")

    # Active rail/metro worksites (e.g. Namma Metro Phase 2B, Mallige Line at Hebbal). Lines, not polygons.
    try:
        rail = ox.features_from_xml(out / "features.osm", polygon=poly, tags={"railway": ["construction"]})
        rail = rail[rail.geom_type.isin(["LineString", "MultiLineString"])]
    except ox._errors.InsufficientResponseError:  # area has no rail construction
        rail = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    cols = [c for c in ("name", "construction") if c in rail]
    rail[["geometry", *cols]].to_file(out / "construction.geojson", driver="GeoJSON")
    return g


def load(area="hebbal"):
    """Return (graph, buildings, obstacles) from cache."""
    out = DATA / area
    g = ox.load_graphml(out / "roads.graphml")
    return g, gpd.read_file(out / "buildings.geojson"), gpd.read_file(out / "obstacles.geojson")


if __name__ == "__main__":
    area = sys.argv[1] if len(sys.argv) > 1 else "hebbal"
    g = fetch(area)
    _, b, o = load(area)
    assert g.number_of_nodes() > 0 and g.number_of_edges() > 0
    assert all("travel_time" in d for *_, d in g.edges(data=True))
    arterials = sum(str(d.get("highway")).startswith(("motorway", "trunk", "primary")) for *_, d in g.edges(data=True))
    assert arterials > 0, "no arterial roads survived: check bbox / ROAD_PAD"
    print(f"nodes={g.number_of_nodes()} edges={g.number_of_edges()} "
          f"arterial_edges={arterials} strongly_connected={nx.is_strongly_connected(g)} "
          f"buildings={len(b)} obstacles={len(o)}")
