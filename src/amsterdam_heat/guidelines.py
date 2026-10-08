"""Check a tile against Amsterdam's heat design guidelines.

The guidelines come from the HvA practice study with Dutch municipalities
(Praktijkonderzoek hitte richtlijnen, 2020):

1. Shade on important walking routes during the hottest part of the day.
   The study measured shade at sun positions of 11:00, 15:00 and 17:00 and
   proposes 30 to 40 percent; we test 40 percent on the city's pedestrian PLUS
   and HOOFD routes. Tree and building shade count the same.
2. Shade on walking areas in neighbourhoods, 30 percent.
3. A cool spot within 300 m walking of every home. A cool spot has an afternoon
   PET of 35 C or lower on the reference hot day, at least 200 m2 of it, inside
   green space of at least 1000 m2.

Shade is read from SOLWEIG's shadow output (below 0.5 counts as shade, so a tree
canopy that lets 3 percent through is shade). Each hour band is labelled by the
end of the hour and SOLWEIG puts the sun at the middle of it, so shade "at 15:00"
is the mean of the bands labelled 15 and 16.

Only the core of the tile is scored; cool spots outside the tile buffer are not
seen, so the distance check is pessimistic near the tile edge.
"""

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from scipy.ndimage import binary_dilation, distance_transform_edt, label
from skimage.graph import MCP_Geometric

from .tile_inputs import CRS, TileSpec

WALK_FUNCTIONS = {"voetpad", "voetgangersgebied", "woonerf", "voetpad op trap"}
ROUTE_SHADE_TARGET = 0.40
NEIGHBOURHOOD_SHADE_TARGET = 0.30
COOL_PET = 35.0
COOL_MIN_AREA = 200.0  # m2
GREEN_MIN_AREA = 1000.0  # m2
COOL_DISTANCE = 300.0  # m walking
AFTERNOON = range(13, 19)  # bands labelled 13 to 18: 12:00 to 18:00, as the national PET map
SHADE_HOURS = (11, 15, 17)


@dataclass
class TileLayers:
    spec: TileSpec
    landcover: np.ndarray
    trees: np.ndarray
    shadow: np.ndarray  # (24, rows, cols), 1 sunlit, 0 shade
    pet: np.ndarray  # (24, rows, cols)

    @property
    def core(self) -> np.ndarray:
        b = round(self.spec.buffer / self.spec.res)
        m = np.zeros(self.landcover.shape, bool)
        m[b:-b, b:-b] = True
        return m

    @property
    def walkable(self) -> np.ndarray:
        return (self.landcover != 2) & (self.landcover != 7)


def _raster(geoms, spec: TileSpec, values=None, dtype="uint8", fill=0) -> np.ndarray:
    shapes = zip(geoms, values, strict=True) if values is not None else ((g, 1) for g in geoms)
    return rasterize(shapes, out_shape=spec.shape, transform=spec.transform, fill=fill,
                     dtype=dtype)


def shaded_at(shadow: np.ndarray, hour: int) -> np.ndarray:
    """Shade with the sun at ``hour``:00 (mean of the two bands around it)."""
    return 0.5 * (shadow[hour] + shadow[hour + 1]) < 0.5


def walking_areas(wegdeel: gpd.GeoDataFrame, spec: TileSpec) -> np.ndarray:
    walk = wegdeel[wegdeel["functie"].isin(WALK_FUNCTIONS)]
    return _raster(walk.geometry, spec).astype(bool)


def route_shade(
    layers: TileLayers, routes: gpd.GeoDataFrame, walk: np.ndarray, reach: float = 15.0
) -> pd.DataFrame:
    """Shade per street on the pedestrian PLUS and HOOFD routes. Each walking-area
    pixel within ``reach`` metres of a route line is given to the nearest route."""
    spec = layers.spec
    routes = routes[routes["VOET"].isin(["PLUS", "HOOFD"])].reset_index(drop=True)
    ids = _raster(routes.geometry, spec, values=range(1, len(routes) + 1), dtype="int32")
    dist, (ri, ci) = distance_transform_edt(ids == 0, return_indices=True)
    nearest = ids[ri, ci]
    mine = walk & layers.core & (dist * spec.res <= reach) & (nearest > 0)
    rows = []
    for idx, route in routes.iterrows():
        cells = mine & (nearest == idx + 1)
        if cells.sum() < 20:
            continue
        rec = {"street": route["STT_NAAM"], "network": route["VOET"],
               "area_m2": float(cells.sum() * spec.res**2)}
        for h in SHADE_HOURS:
            rec[f"shade_{h:02d}"] = float(shaded_at(layers.shadow, h)[cells].mean())
        rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    hours = [f"shade_{h:02d}" for h in SHADE_HOURS]
    weighted = df[hours].multiply(df["area_m2"], axis=0)
    agg = weighted.groupby([df["street"], df["network"]]).sum()
    area = df.groupby(["street", "network"])["area_m2"].sum()
    out = agg.divide(area, axis=0).reset_index()
    out["area_m2"] = area.values
    out["meets_40pct_at_15"] = out["shade_15"] >= ROUTE_SHADE_TARGET
    return out.sort_values("shade_15")


def neighbourhood_shade(
    layers: TileLayers, buurten: gpd.GeoDataFrame, walk: np.ndarray
) -> pd.DataFrame:
    spec = layers.spec
    rows = []
    for _, b in buurten.iterrows():
        cells = _raster([b.geometry], spec).astype(bool) & walk & layers.core
        if cells.sum() < 200:
            continue
        rec = {"buurt": b["naam"], "walking_area_m2": float(cells.sum() * spec.res**2)}
        for h in SHADE_HOURS:
            rec[f"shade_{h:02d}"] = float(shaded_at(layers.shadow, h)[cells].mean())
        rec["meets_30pct_at_15"] = rec["shade_15"] >= NEIGHBOURHOOD_SHADE_TARGET
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("shade_15")


def green_areas(begroeid: gpd.GeoDataFrame, spec: TileSpec, bridge: float = 5.0) -> np.ndarray:
    """Public green spaces of at least GREEN_MIN_AREA, from BGT vegetated terrain.

    Polygons closer than ``bridge`` metres are merged, so a park cut up by paths
    counts as one; the green area itself (not the paths) must reach the minimum."""
    green = begroeid[begroeid.geometry.notna()]
    merged = gpd.GeoSeries(green.buffer(bridge).union_all(), crs=green.crs).explode(index_parts=False)
    keep = []
    for park in merged:
        green_area = green.intersection(park).area.sum()
        if green_area >= GREEN_MIN_AREA:
            keep.append(park.buffer(-bridge / 2))
    if not keep:
        return np.zeros(spec.shape, bool)
    return _raster(keep, spec).astype(bool)


def cool_spots(layers: TileLayers, parks: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cool spot mask and the afternoon mean PET it was derived from: places inside a
    public green space where the afternoon PET is at most COOL_PET over at least
    COOL_MIN_AREA."""
    res2 = layers.spec.res**2
    pet_pm = np.nanmean(layers.pet[list(AFTERNOON)], axis=0)
    cool = layers.walkable & parks & (pet_pm <= COOL_PET)
    labels, _ = label(cool)
    size = np.bincount(labels.ravel()) * res2
    keep = size >= COOL_MIN_AREA
    keep[0] = False
    return keep[labels], pet_pm


def walking_distance(layers: TileLayers, targets: np.ndarray) -> np.ndarray:
    """Metres to the nearest target, walking around buildings and water."""
    cost = np.where(layers.walkable, 1.0, np.inf)
    mcp = MCP_Geometric(cost)
    starts = list(zip(*np.nonzero(targets), strict=True))
    if not starts:
        return np.full(cost.shape, np.inf)
    dist, _ = mcp.find_costs(starts)
    return dist * layers.spec.res


def homes_near_cool_spots(
    layers: TileLayers, bag: gpd.GeoDataFrame, dist: np.ndarray
) -> pd.DataFrame:
    """Walking distance from each residential building in the tile core to a cool spot,
    measured from the pavement right outside the building."""
    spec = layers.spec
    homes = bag[bag["gebruiksdoel"].astype(str).str.contains("woonfunctie")].reset_index(drop=True)
    ids = _raster(homes.geometry, spec, values=range(1, len(homes) + 1), dtype="int32")
    ring = binary_dilation(ids > 0, iterations=1) & (ids == 0) & layers.walkable
    _, (ri, ci) = distance_transform_edt(ids == 0, return_indices=True)
    owner = ids[ri, ci]
    rows = []
    for k in np.unique(owner[ring & layers.core]):
        d = dist[ring & (owner == k)]
        rows.append({"bag_id": homes.loc[k - 1, "identificatie"], "distance_m": float(d.min())})
    return pd.DataFrame(rows)


def read_vector(path) -> gpd.GeoDataFrame:
    """Read GeoJSON into RD New. Several Dutch services write RD coordinates without
    a CRS member, which readers then label WGS84; those are relabelled, real
    longitude and latitude files are reprojected."""
    g = gpd.read_file(path)
    in_metres = g.total_bounds[0] > 1000
    if g.crs is None or in_metres:
        return g.set_crs(CRS, allow_override=True)
    return g.to_crs(CRS)
