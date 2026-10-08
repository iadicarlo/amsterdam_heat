"""Street furniture and street use as obstacles for new trunks.

Layers come from open data without logins: the city's API (parking bays, waste
containers, litter bins, tree register, replanting register), the BGT plus layers
kept by the city (lampposts, cabinets, hydrants, shelters, tram rails) and
OpenStreetMap (bike racks, bus and tram stops). ``fetch_all`` writes one GeoJSON
per layer to ``data/raw/streetscape`` with a sidecar and a SOURCE.json.

Clearances are from the trunk centre to the object. The lamppost value is the
municipal tree table (matentabel bomen, after Handboek Bomen 2014, Norminstituut
Bomen); the underground container value is half the crown plus 3 m free for the
crane (Utrecht siting rules for underground containers, 2nd size tree). The rest are
our own screening values, see docs/street_check.md.
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from rasterio.features import rasterize
from shapely.geometry import LineString, Point, Polygon, box

from amsterdam_heat.guidelines import read_vector
from amsterdam_heat.sources import bgt_collection

ROOT = Path("data/raw/streetscape")
NIEUW_WEST = (111500, 482000, 118500, 490500)
CRS = 28992

AMS_WFS = "https://api.data.amsterdam.nl/v1/wfs"
MAPS = "https://maps.amsterdam.nl/open_geodata/geojson_lnglat.php"
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]

CITY = "Gemeente Amsterdam, data.amsterdam.nl"
LICENCES = {
    "parking_bays": f"Parkeervakken, {CITY}, open data",
    "underground_containers": f"Huishoudelijk afval (containerlocatie), {CITY}, public",
    "containers": f"Huishoudelijk afval (container), {CITY}, public",
    "litter_bins": f"Beheerobjecten openbare ruimte (afvalbakken), {CITY}, public",
    "street_lights": "BGT paal, plus type lichtmast, bronhouder Gemeente Amsterdam, via PDOK, CC0",
    "cabinets": "BGT kast, bronhouder Gemeente Amsterdam, via PDOK, CC0",
    "hydrants": "BGT put, plus type brandkraan, via PDOK, CC0",
    "shelters": "BGT straatmeubilair, plus type abri, via PDOK, CC0",
    "tram_tracks": "BGT spoor, functie tram, via PDOK, CC0",
    "bike_racks": "OpenStreetMap contributors, amenity=bicycle_parking, ODbL",
    "stops": "OpenStreetMap contributors, bus and tram stops and platforms, ODbL",
    "markets": "Markten, Gemeente Amsterdam, Maps Amsterdam open geodata",
    "register_trees": f"Bomen (stamgegevens), {CITY}, public",
    "replant_spots": f"Bomen (kapenherplant), {CITY}, public",
    "green_works": f"Uitvoeringsplan openbare ruimte, {CITY}, public",
}

# m from trunk centre to the object; 0 means "not inside", None means report only
CLEARANCE = {
    "parking_bays": 0.0,  # not on a bay unless the bay is converted
    "underground_containers": 7.0,  # half crown (4 m) plus 3 m for the crane
    "containers": 1.0,
    "litter_bins": 1.0,
    "street_lights": 4.0,  # matentabel bomen, all tree sizes
    "cabinets": 1.0,
    "hydrants": 1.0,
    "shelters": 1.5,
    "tram_tracks": 3.0,  # rail centreline, swept tram plus crown
    "bike_racks": 1.0,
    "stops": 2.0,
    "register_trees": 4.0,  # half the 8 m spacing between new trees
    "markets": None,
    "replant_spots": None,
    "green_works": None,
}


def _sidecar(path: Path, url: str, params: dict, licence: str) -> dict:
    meta = {"url": url, "params": params, "licence": licence,
            "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    path.with_suffix(path.suffix + ".source.json").write_text(json.dumps(meta, indent=2))
    return meta


def _write(features: list, out: Path) -> None:
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def city_wfs(dataset: str, table: str, bbox, out: Path, licence: str, page: int = 10000) -> dict:
    """One table of the city's WFS inside the box, EPSG:28992, paged."""
    xmin, ymin, xmax, ymax = bbox
    crs = "urn:ogc:def:crs:EPSG::28992"
    url = f"{AMS_WFS}/{dataset}/"
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": table,
              "BBOX": f"{xmin},{ymin},{xmax},{ymax},{crs}", "SRSNAME": crs,
              "OUTPUTFORMAT": "geojson", "COUNT": page}
    features, start = [], 0
    while True:
        r = requests.get(url, params={**params, "STARTINDEX": start}, timeout=600)
        r.raise_for_status()
        batch = r.json()["features"]
        features += batch
        if len(batch) < page:
            break
        start += page
    _write(features, out)
    return _sidecar(out, url, params, licence)


def bgt_plus(collection: str, bbox, out: Path, licence: str, key: str | None = None,
             values: set | None = None) -> dict:
    """Current BGT objects from PDOK, kept where ``key`` is in ``values``."""
    bgt_collection(collection, bbox, out)
    data = json.loads(out.read_text())
    if key:
        data["features"] = [f for f in data["features"] if f["properties"].get(key) in values]
    out.write_text(json.dumps(data))
    url = f"https://api.pdok.nl/lv/bgt/ogc/v1/collections/{collection}/items"
    return _sidecar(out, url, {"bbox": bbox, "filter": f"{key} in {sorted(values or [])}"}, licence)


def _osm_geometry(el: dict):
    if el["type"] == "node":
        return Point(el["lon"], el["lat"])
    pts = [(p["lon"], p["lat"]) for p in el.get("geometry", [])]
    if len(pts) >= 4 and pts[0] == pts[-1]:
        return Polygon(pts)
    if len(pts) >= 2:
        return LineString(pts)
    return Point(el["center"]["lon"], el["center"]["lat"]) if "center" in el else None


def osm(selectors: list[str], bbox, out: Path, licence: str) -> dict:
    """OpenStreetMap nodes and ways matching ``selectors`` (Overpass filters such as
    ``["amenity"="bicycle_parking"]``), reprojected to EPSG:28992."""
    lonlat = gpd.GeoSeries([box(*bbox)], crs=CRS).to_crs(4326).total_bounds
    s, w, n, e = lonlat[1], lonlat[0], lonlat[3], lonlat[2]
    body = "".join(f"nw{sel}({s:.5f},{w:.5f},{n:.5f},{e:.5f});" for sel in selectors)
    query = f"[out:json][timeout:180];({body});out geom tags;"
    headers = {"User-Agent": "amsterdam_heat street check (github.com/iadicarlo)"}
    for attempt in range(6):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": query}, headers=headers, timeout=300)
            if r.ok and r.text.lstrip().startswith("{"):
                break
        except requests.RequestException:
            pass
        time.sleep(20)
    else:
        raise RuntimeError("Overpass did not answer")
    rows = [(el.get("tags", {}), _osm_geometry(el)) for el in r.json()["elements"]]
    rows = [(t, g) for t, g in rows if g is not None]
    gdf = gpd.GeoDataFrame([t for t, _ in rows], geometry=[g for _, g in rows], crs=4326)
    gdf = gdf.to_crs(CRS)
    keep = [c for c in ("amenity", "highway", "railway", "public_transport", "bicycle_parking",
                        "capacity", "name") if c in gdf]
    gdf[keep + ["geometry"]].to_file(out, driver="GeoJSON")
    return _sidecar(out, url, {"query": query}, licence)


def maps_layer(layer: str, theme: str, bbox, out: Path, licence: str) -> dict:
    """A Maps Amsterdam open geodata layer (WGS84) clipped to the box, in EPSG:28992."""
    params = {"KAARTLAAG": layer, "THEMA": theme}
    r = requests.get(MAPS, params=params, timeout=300)
    r.raise_for_status()
    gdf = gpd.read_file(r.text).set_crs(4326, allow_override=True).to_crs(CRS)
    gdf = gdf[gdf.intersects(box(*bbox))]
    gdf.to_file(out, driver="GeoJSON")
    return _sidecar(out, MAPS, params, licence)


def fetch_all(bbox=NIEUW_WEST, out_dir: Path = ROOT) -> dict:
    """Download every street furniture layer for the box; returns the SOURCE.json content."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = {k: out_dir / f"{k}.geojson" for k in LICENCES}
    L = LICENCES
    src = {
        "parking_bays": city_wfs("parkeervakken", "parkeervakken", bbox, p["parking_bays"], L["parking_bays"]),
        "underground_containers": city_wfs("huishoudelijkafval", "containerlocatie", bbox,
                                           p["underground_containers"], L["underground_containers"]),
        "containers": city_wfs("huishoudelijkafval", "container", bbox, p["containers"], L["containers"]),
        "litter_bins": city_wfs("objectenopenbareruimte", "afvalbakken", bbox, p["litter_bins"], L["litter_bins"]),
        "register_trees": city_wfs("bomen", "stamgegevens", bbox, p["register_trees"], L["register_trees"],
                                   page=50000),
        "replant_spots": city_wfs("bomen", "kapenherplant", bbox, p["replant_spots"], L["replant_spots"]),
        "green_works": city_wfs("uitvoeringsplan", "uitvoeringsplan", bbox, p["green_works"], L["green_works"]),
        "street_lights": bgt_plus("paal", bbox, p["street_lights"], L["street_lights"], "plus_type", {"lichtmast"}),
        "cabinets": bgt_plus("kast", bbox, p["cabinets"], L["cabinets"]),
        "hydrants": bgt_plus("put", bbox, p["hydrants"], L["hydrants"], "plus_type", {"brandkraan / -put"}),
        "shelters": bgt_plus("straatmeubilair", bbox, p["shelters"], L["shelters"], "plus_type", {"abri"}),
        "tram_tracks": bgt_plus("spoor", bbox, p["tram_tracks"], L["tram_tracks"], "functie", {"tram"}),
        "markets": maps_layer("MARKTEN", "markten", bbox, p["markets"], L["markets"]),
        "bike_racks": osm(['["amenity"="bicycle_parking"]'], bbox, p["bike_racks"], L["bike_racks"]),
        "stops": osm(['["highway"="bus_stop"]', '["railway"="tram_stop"]', '["railway"="platform"]',
                      '["public_transport"="platform"]'], bbox, p["stops"], L["stops"]),
    }
    (out_dir / "SOURCE.json").write_text(json.dumps(src, indent=2))
    return src


def load_layers(root: Path = ROOT) -> dict[str, gpd.GeoDataFrame]:
    """Every saved layer as a GeoDataFrame in EPSG:28992. Containers standing on an
    underground pit are dropped from ``containers``, which keeps the ones above ground."""
    root = Path(root)
    layers = {}
    for name in LICENCES:
        f = root / f"{name}.geojson"
        if not f.exists():
            continue
        g = read_vector(f)
        layers[name] = g[g.geometry.notna() & ~g.geometry.is_empty].reset_index(drop=True)
    if "containers" in layers and "underground_containers" in layers:
        pits = layers["underground_containers"]
        c = layers["containers"]
        if len(pits) and len(c):
            _, dist = pits.sindex.nearest(c.geometry, return_distance=True, return_all=False)
            layers["containers"] = c[dist > 1.5].reset_index(drop=True)
    return layers


def obstacle_mask(transform, shape: tuple[int, int], layers: dict[str, gpd.GeoDataFrame],
                  clearances: dict[str, float | None] | None = None) -> np.ndarray:
    """True on grid cells whose centre is inside an obstacle or within its clearance,
    so a new trunk may not go there. ``transform`` is a rasterio Affine in RD New."""
    clearances = CLEARANCE if clearances is None else clearances
    rows, cols = shape
    x0, y0 = transform * (0, 0)
    x1, y1 = transform * (cols, rows)
    extent = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    mask = np.zeros(shape, dtype=bool)
    for name, gdf in layers.items():
        d = clearances.get(name)
        if d is None or gdf.empty:
            continue
        near = gdf[gdf.intersects(extent.buffer(d + 1))]
        if d == 0:
            near = near[near.geom_type.isin(["Polygon", "MultiPolygon"])]
        if near.empty:
            continue
        zones = near.geometry.buffer(d) if d > 0 else near.geometry
        mask |= rasterize(((g, 1) for g in zones), out_shape=shape, transform=transform,
                          fill=0, dtype="uint8").astype(bool)
    return mask


def check_trees(trees_gdf: gpd.GeoDataFrame, layers: dict[str, gpd.GeoDataFrame],
                clearances: dict[str, float | None] | None = None) -> pd.DataFrame:
    """Distance in m from each tree to the nearest object of every layer (0 inside a
    polygon), and which clearances it breaks (``conflict_with``, ``conflict``)."""
    clearances = CLEARANCE if clearances is None else clearances
    pts = trees_gdf.geometry.reset_index(drop=True)
    out = pd.DataFrame(index=pts.index)
    if "rank" in trees_gdf:
        out["rank"] = trees_gdf["rank"].to_numpy()
    out["x"], out["y"] = pts.x.round(1).to_numpy(), pts.y.round(1).to_numpy()
    hits = [[] for _ in range(len(pts))]
    for name, gdf in layers.items():
        dist = np.full(len(pts), np.inf)
        if not gdf.empty:
            idx_tree, idx_obj = gdf.sindex.nearest(pts, return_all=False)
            dist[idx_tree] = pts.iloc[idx_tree].distance(gdf.geometry.iloc[idx_obj], align=False).to_numpy()
        out[f"d_{name}"] = dist.round(2)
        d = clearances.get(name)
        if d is None:
            continue
        broken = dist <= 0 if d == 0 else dist < d
        for i in np.flatnonzero(broken):
            hits[i].append(name)
    out["conflict_with"] = [",".join(h) for h in hits]
    out["conflict"] = out["conflict_with"] != ""
    return out
