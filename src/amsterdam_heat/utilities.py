"""Cables and pipes from open data, and where a new tree trunk may not go.

Layers come from scripts/get_utilities.py (data/raw/utilities). Open data covers
Liander electricity and gas (cables, pipes, stations and LS cabinets), Waternet
sewers, Vattenfall district heating, city street lighting cables and ducts and the
gas transmission line. Drinking water mains and telecom cables are not open; the
only open traces are fire hydrants and untyped street cabinets from the BGT, used
here as point clearances. A clear result does not replace the city's KLIC check.

Clearances are from the trunk centre to the pipe or cable centreline. The defaults
are a screening minimum; Stedin advises 2.5 m from the tree centre to the edge of
the cable trench (citing CROW publication 280), see docs/utilities.md.
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from shapely.geometry import box

from amsterdam_heat.guidelines import read_vector

ROOT = Path("data/raw/utilities")

# m from trunk centre to the line
CLEARANCE = {
    "electricity": 1.0,  # Liander low, medium and high voltage cables
    "street_lighting": 1.0,
    "gas": 1.5,  # Liander distribution mains
    "gas_transmission": 5.0,  # belemmeringenstrook of a high pressure pipeline
    "sewer": 2.0,  # Waternet sewers, pressure and transport mains
    "sewer_connection": 1.0,  # house and gully connections, drains
    "district_heating": 2.0,  # Vattenfall heat and cold networks
    "electricity_station": 2.0,  # Liander HS, MS stations and LS cabinets, cables fan out
    "hydrant": 1.5,  # BGT fire hydrant, on a branch of a drinking water main
    "cabinet": 1.5,  # BGT street cabinet: electricity, telecom, cable TV or traffic
}

SEWER_CONNECTION = {"Aansluitleiding", "Drain"}


def load_layers(root: Path = ROOT) -> dict[str, gpd.GeoDataFrame]:
    """All open utility lines and points as one GeoDataFrame per type, EPSG:28992,
    in service only. A layer that is not downloaded comes back empty."""
    def read(name):
        path = root / name / f"{name}.geojson"
        return read_vector(path) if path.exists() else gpd.GeoDataFrame(geometry=[], crs=28992)

    elec = pd.concat([read(f"liander_{v}") for v in ("ls", "ms", "hs")], ignore_index=True)
    sewer = read("waternet_sewers")
    sewer = sewer[~sewer["status"].str.lower().str.startswith("vervallen")]
    connection = sewer["soort"].isin(SEWER_CONNECTION)
    heat = read("district_heating")
    points = read("bgt_points")
    layers = {
        "electricity": elec,
        "street_lighting": pd.concat([read("street_lighting"), read("street_lighting_ducts")],
                                     ignore_index=True),
        "gas": read("liander_gas"),
        "gas_transmission": read("gas_transmission"),
        "sewer": sewer[~connection],
        "sewer_connection": sewer[connection],
        "district_heating": heat[heat["NETTYPE"] != "PLAN"] if "NETTYPE" in heat else heat,
        "electricity_station": read("liander_stations"),
        "hydrant": points[points["kind"] == "hydrant"] if "kind" in points else points,
        "cabinet": points[points["kind"] == "cabinet"] if "kind" in points else points,
    }
    return {k: gpd.GeoDataFrame(v[["geometry"]], crs=28992).reset_index(drop=True)
            for k, v in layers.items()}


def utility_mask(grid_transform, shape: tuple[int, int], layers: dict[str, gpd.GeoDataFrame],
                 clearances: dict[str, float] | None = None) -> np.ndarray:
    """True on grid cells whose centre lies within the clearance of a cable or pipe,
    so a new trunk may not go there. ``grid_transform`` is a rasterio Affine in RD New."""
    clearances = clearances or CLEARANCE
    rows, cols = shape
    x0, y0 = grid_transform * (0, 0)
    x1, y1 = grid_transform * (cols, rows)
    extent = box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    mask = np.zeros(shape, dtype=bool)
    for name, gdf in layers.items():
        d = clearances.get(name)
        if d is None or gdf.empty:
            continue
        near = gdf[gdf.intersects(extent.buffer(d))]
        if near.empty:
            continue
        zones = near.geometry.buffer(d)
        mask |= rasterize(((g, 1) for g in zones), out_shape=shape, transform=grid_transform,
                          fill=0, dtype="uint8").astype(bool)
    return mask


def check_trees(trees_gdf: gpd.GeoDataFrame, layers: dict[str, gpd.GeoDataFrame],
                clearances: dict[str, float] | None = None) -> pd.DataFrame:
    """Distance in m from each tree to the nearest line of every utility type, and
    whether the tree is inside any clearance (``conflict``, ``conflict_with``)."""
    clearances = clearances or CLEARANCE
    pts = trees_gdf.geometry.reset_index(drop=True)
    out = pd.DataFrame(index=pts.index)
    if "rank" in trees_gdf:
        out["rank"] = trees_gdf["rank"].to_numpy()
    out["x"], out["y"] = pts.x.to_numpy(), pts.y.to_numpy()
    hits = [[] for _ in range(len(pts))]
    for name, gdf in layers.items():
        if gdf.empty:
            out[f"d_{name}"] = np.inf
            continue
        idx_tree, idx_line = gdf.sindex.nearest(pts, return_all=False)
        dist = np.full(len(pts), np.inf)
        dist[idx_tree] = pts.iloc[idx_tree].distance(gdf.geometry.iloc[idx_line], align=False).to_numpy()
        out[f"d_{name}"] = dist.round(2)
        d = clearances.get(name)
        if d is not None:
            for i in np.flatnonzero(dist < d):
                hits[i].append(name)
    out["conflict_with"] = [",".join(h) for h in hits]
    out["conflict"] = out["conflict_with"] != ""
    return out
