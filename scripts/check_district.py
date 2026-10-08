"""Score a whole district against Amsterdam's heat design guidelines.

    uv run python scripts/check_district.py --district nieuw-west --date 2015-07-01

Same rules as check_guidelines.py (see amsterdam_heat.guidelines), on the stitched
district so routes and cool spots carry across tile edges:

1. shade on the pedestrian PLUS and HOOFD routes, 40% at 15:00,
2. shade on walking areas per neighbourhood, 30% at 15:00,
3. a cool spot within 300 m walking of every home.

Shade uses the 1 m grid; walking distances use a 2 m grid to fit in memory. Cool
spots just outside the run area are not seen, so homes near the district edge come
out a little worse than they are. Needs make_map.py (stitched PET) and BGT wegdeel
and begroeidterreindeel for the district in data/raw/city. Writes
docs/guidelines_<district>_<date>.md, figures/guidelines_<district>_<date>.png and
adds the results to buurt_stats.csv.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import Affine
from scipy.ndimage import binary_dilation, distance_transform_edt, label
from skimage.graph import MCP_Geometric

from amsterdam_heat import guidelines as gl
from amsterdam_heat.paths import inputs_dir, output_dir

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
TILE, BUFFER = 500, 100
BANDS = sorted({b for h in gl.SHADE_HOURS for b in (h, h + 1)})


@dataclass
class Grid:
    """Duck-types TileSpec for the guideline functions: a rectangle at ``res``."""
    transform: Affine
    shape: tuple[int, int]
    res: float = 1.0
    buffer: float = 1.0


class Bands:
    """Stitched shadow bands kept as bytes; indexing by hour returns 0 to 1 floats."""

    def __init__(self, bands: dict[int, np.ndarray]):
        self.bands = bands

    def __getitem__(self, h: int) -> np.ndarray:
        return self.bands[h].astype("float32") / 255


def stitch(tiles, date, grid: Grid):
    h, w = grid.shape
    x0, y1 = grid.transform.c, grid.transform.f
    lc = np.full((h, w), 7, "uint8")  # unrun ground counts as water: not walkable
    bands = {b: np.full((h, w), 255, "uint8") for b in BANDS}
    for x, y in tiles:
        out = output_dir(f"{x}_{y}", "mps", date)
        if not (out / "Shadow_0_0.tif").exists():
            continue
        r, c = round(y1 - y - TILE), round(x - x0)
        core = (slice(BUFFER, BUFFER + TILE), slice(BUFFER, BUFFER + TILE))
        lc[r:r + TILE, c:c + TILE] = rasterio.open(inputs_dir(f"{x}_{y}") / "Landcover.tif").read(1)[core]
        with rasterio.open(out / "Shadow_0_0.tif") as src:
            for b in BANDS:
                bands[b][r:r + TILE, c:c + TILE] = np.round(255 * src.read(b + 1)[core])
    return lc, Bands(bands)


def fix_text(s):
    """The city's network file is UTF-8 read as Latin-1 (BelgiÃ«plein); undo that."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (AttributeError, UnicodeError):
        return s


def coarsen(a: np.ndarray, k: int, how: str) -> np.ndarray:
    h, w = a.shape[0] // k * k, a.shape[1] // k * k
    b = a[:h, :w].reshape(h // k, k, w // k, k)
    return b.any(axis=(1, 3)) if how == "any" else b.mean(axis=(1, 3))


def homes_distance(bag: gpd.GeoDataFrame, walk2: np.ndarray, dist: np.ndarray, grid2: Grid):
    homes = bag[bag["gebruiksdoel"].astype(str).str.contains("woonfunctie")].reset_index(drop=True)
    ids = gl._raster(homes.geometry, grid2, values=range(1, len(homes) + 1), dtype="int32")
    ring = binary_dilation(ids > 0, iterations=1) & (ids == 0) & walk2
    _, (ri, ci) = distance_transform_edt(ids == 0, return_indices=True)
    owner = np.where(ring, ids[ri, ci], 0)
    best = np.full(len(homes) + 1, np.inf)
    np.minimum.at(best, owner[ring], dist[ring])
    homes["distance_m"] = best[1:]
    return homes[np.isfinite(homes["distance_m"])]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--district", required=True)
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    d = ROOT / "data" / "processed" / "districts" / f"{args.district}_{args.date}"
    city = ROOT / "data" / "raw" / "city"
    with rasterio.open(d / "pet_afternoon.tif") as src:
        pet_pm, transform = src.read(1), src.transform
    grid = Grid(transform, pet_pm.shape)
    tiles = json.loads((city / f"tiles_{args.district}.json").read_text())
    lc, shadow = stitch(tiles, args.date, grid)
    layers = gl.TileLayers(spec=grid, landcover=lc, trees=None, shadow=shadow, pet=None)
    print("stitched", flush=True)

    district = gl.read_vector(city / "stadsdelen.geojson")
    area = district[district["naam"].str.lower() == args.district].union_all()
    walk = gl.walking_areas(gl.read_vector(city / f"bgt_wegdeel_{args.district}.geojson"), grid)
    routes = gl.read_vector(city / "ams_plushoofdnetten.geojson")
    routes = routes[routes.intersects(area)].copy()
    routes["STT_NAAM"] = routes["STT_NAAM"].map(fix_text)
    route_tab = gl.route_shade(layers, routes, walk)
    buurten = gl.read_vector(city / f"buurten_{args.district}.geojson")
    buurten = buurten[buurten.representative_point().within(area)].reset_index(drop=True)
    buurt_tab = gl.neighbourhood_shade(layers, buurten, walk)
    print("shade done", flush=True)

    begroeid = gl.read_vector(city / f"bgt_begroeidterreindeel_{args.district}.geojson")
    k = 2
    grid2 = Grid(transform * Affine.scale(k), (pet_pm.shape[0] // k, pet_pm.shape[1] // k), res=k)
    walk2 = coarsen(layers.walkable, k, "mean") >= 0.5
    bag = pd.concat([gpd.read_file(ROOT / "data" / "raw" / f"{x}_{y}" / "bag_pand.geojson") for x, y in tiles
                     if (ROOT / "data" / "raw" / f"{x}_{y}" / "bag_pand.geojson").exists()])
    if bag.crs is None or bag.total_bounds[0] > 1000:
        bag = bag.set_crs(gl.CRS, allow_override=True)
    bag = bag.drop_duplicates("identificatie")
    bag = bag[bag.representative_point().within(area)]

    def homes_to_cool(green_min: float, bridge: float):
        """Walking distance from every home to a cool spot inside green of ``green_min`` m2."""
        gl.GREEN_MIN_AREA = green_min
        parks = gl.green_areas(begroeid, grid, bridge=bridge)
        cool = layers.walkable & parks & (pet_pm <= gl.COOL_PET)
        labels, _ = label(cool)
        keep = np.bincount(labels.ravel()) >= gl.COOL_MIN_AREA
        keep[0] = False
        cool2 = coarsen(keep[labels], k, "any") & walk2
        dist, _ = MCP_Geometric(np.where(walk2, 1.0, np.inf)).find_costs(
            list(zip(*np.nonzero(cool2), strict=True)))
        return homes_distance(bag, walk2, dist * k, grid2), dist * k

    homes, _ = homes_to_cool(1000.0, 5.0)  # the guideline: any public green of 1000 m2
    parks_only, dist_park = homes_to_cool(10000.0, 0.0)  # stricter: a park of at least 1 ha
    homes["park_m"] = homes["identificatie"].map(parks_only.set_index("identificatie")["distance_m"])
    homes["buurt"] = gpd.sjoin(gpd.GeoDataFrame(geometry=homes.representative_point(), crs=gl.CRS),
                               buurten[["naam", "geometry"]], how="left", predicate="within")["naam"].to_numpy()
    homes[["identificatie", "buurt", "distance_m", "park_m"]].to_csv(d / "homes_cool_spots.csv", index=False)
    print("cool spots done", flush=True)

    share = lambda col: homes.groupby("buurt")[col].apply(lambda s: float((s <= gl.COOL_DISTANCE).mean()))
    stats_path = d / "buurt_stats.csv"
    stats = pd.read_csv(stats_path)
    stats = stats.drop(columns=["walk_shade_15h", "homes_near_cool", "homes_near_park", "homes"],
                       errors="ignore")
    stats["walk_shade_15h"] = stats["naam"].map(buurt_tab.set_index("buurt")["shade_15"])
    stats["homes_near_cool"] = stats["naam"].map(share("distance_m"))
    stats["homes_near_park"] = stats["naam"].map(share("park_m"))
    stats["homes"] = stats["naam"].map(homes.groupby("buurt").size())
    stats.to_csv(stats_path, index=False)
    route_tab.to_csv(d / "route_shade.csv", index=False)

    pct = lambda v: f"{100 * v:.0f}%"
    r_ok = route_tab["meets_40pct_at_15"]
    r_area = route_tab["area_m2"]
    b_ok = buurt_tab["meets_30pct_at_15"]
    within = float((homes["distance_m"] <= gl.COOL_DISTANCE).mean())
    within_park = float((homes["park_m"] <= gl.COOL_DISTANCE).mean())
    lines = [
        f"# Heat guidelines in {args.district.title()}, {args.date}", "",
        ("Shade at sun positions of 11:00, 15:00 and 17:00 local time, on walking areas from the BGT. "
         "Cool spots: afternoon PET of 35 C or lower (with the afternoon heat island added), at least "
         "200 m2, inside public green of at least 1000 m2 (BGT green closer than 5 m merged). In a garden "
         "city most courtyards and green strips pass that, so we also count only parks of at least "
         "1 ha. Distances are walked around buildings and water."), "",
        "| Guideline | Result |", "|---|---|",
        (f"| Pedestrian routes with 40% shade at 15:00 | {int(r_ok.sum())} of {len(route_tab)} streets, "
         f"{pct(r_area[r_ok].sum() / r_area.sum())} of route walking area |"),
        f"| Neighbourhoods with 30% shade on walking areas at 15:00 | {int(b_ok.sum())} of {len(buurt_tab)} |",
        f"| Homes within 300 m walking of a cool spot | {pct(within)} of {len(homes)} residential buildings |",
        f"| Same, counting only parks of at least 1 ha | {pct(within_park)} |",
        "", "## Least shaded pedestrian routes at 15:00", "",
        "| Street | Network | Walking area (m2) | 11:00 | 15:00 | 17:00 |", "|---|---|---|---|---|---|",
        *[f"| {r['street']} | {r['network']} | {r['area_m2']:.0f} | {pct(r['shade_11'])} | "
          f"{pct(r['shade_15'])} | {pct(r['shade_17'])} |"
          for _, r in route_tab[route_tab["area_m2"] >= 500].head(15).iterrows()],
        "", "## Neighbourhoods", "",
        "| Buurt | Shade on walking areas at 15:00 | Homes within 300 m of a cool spot | Of a cool park of 1 ha | Residents |",
        "|---|---|---|---|---|",
        *[f"| {r['naam']} | {pct(r['walk_shade_15h'])} | {pct(r['homes_near_cool'])} | "
          f"{pct(r['homes_near_park'])} | {r['residents']:.0f} |"
          for _, r in stats[stats["residents"] >= 100].sort_values("walk_shade_15h").iterrows()
          if pd.notna(r["walk_shade_15h"]) and pd.notna(r["homes_near_cool"])],
        "", f"![Guideline check](../figures/guidelines_{args.district}_{args.date}.png)",
    ]
    (ROOT / "docs" / f"guidelines_{args.district}_{args.date}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))

    fig, ax = plt.subplots(1, 2, figsize=(14, 7.5), constrained_layout=True)
    h, w = pet_pm.shape
    ext = (transform.c, transform.c + w, transform.f - h, transform.f)
    sh = gl.shaded_at(shadow, 15)
    ax[0].imshow(np.where(walk, sh, np.nan)[::2, ::2], extent=ext, cmap="RdYlBu", vmin=0, vmax=1,
                 interpolation="nearest")
    ax[0].set_title("Walking areas at 15:00, blue shade, red sun")
    dshow = np.where(walk2, np.clip(dist_park, 0, 900), np.nan)
    im = ax[1].imshow(dshow, extent=ext, cmap="magma_r", vmin=0, vmax=900)
    ax[1].contour(np.isfinite(dshow) & (dshow <= gl.COOL_DISTANCE), levels=[0.5], colors="c",
                  linewidths=0.6, extent=(ext[0], ext[1], ext[3], ext[2]))
    fig.colorbar(im, ax=ax[1], shrink=0.7, label="walking distance to a cool park (m)")
    ax[1].set_title("Distance to a cool spot in a park of 1 ha or more, 300 m line")
    for a in ax:
        buurten.boundary.plot(ax=a, color="0.3", linewidth=0.3)
        a.set_axis_off()
    fig.text(0.01, 0.005, "Model: SOLWEIG-GPU. Data: AHN4, BAG, BGT (PDOK), Gemeente Amsterdam, KNMI, "
             "AAMS (PANGAEA), WUR MAQ", fontsize=7, color="0.4")
    fig.savefig(ROOT / "figures" / f"guidelines_{args.district}_{args.date}.png", dpi=120)


if __name__ == "__main__":
    main()
