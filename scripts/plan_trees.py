"""Choose new street trees for one or more neighbourhoods (greedy, amsterdam_heat.planting).

    uv run python scripts/plan_trees.py --name osdorpplein --buurt FK03
    uv run python scripts/plan_trees.py --name de-aker --buurt FG03 FG01

Works on the district run of the reference day (default Nieuw-West, 1 July 2015).
Walking areas inside the neighbourhoods and within 100 m of homes, shops, schools,
care, community, hotel or sports buildings (BAG) are the target: a pixel shaded at 11:00,
15:00 or 17:00 counts once, 15:00 twice, and pixels within 15 m of a pedestrian
PLUS or HOOFD route twice again. Trees are added until the pavements have 30% shade
and the route pavements 40% at 15:00, or --max trees. Candidates lie on public
pavement or public green (BGT, bronhouder Gemeente Amsterdam), clear of the cables
and pipes in open data (amsterdam_heat.utilities). Writes
data/processed/trees/<name>/ (trees.geojson, steps.csv) and figures/trees_<name>.png.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
import pvlib
import rasterio
from rasterio.features import shapes
from rasterio.transform import Affine, from_origin
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Point, box, shape

from amsterdam_heat import guidelines as gl
from amsterdam_heat import planting as pl
from amsterdam_heat.paths import inputs_dir, output_dir

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
TILE, BUFFER, MARGIN = 500, 100, 60
HOUR_WEIGHT = {11: 1.0, 15: 2.0, 17: 1.0}
PEOPLE_REACH = 100.0  # m
PEOPLE_USES = ("woon", "winkel", "onderwijs", "gezondheidszorg", "bijeenkomst", "logies", "sport")
PATCH = 26  # m, reach of a 12 m tree's shadow at a low afternoon sun, plus its crown
ROUTE_REACH = 15.0
GREEN_TYPES = {"groenvoorziening", "grasland overig"}
LAT, LON = 52.36, 4.80


@dataclass
class Grid:
    transform: Affine
    shape: tuple[int, int]
    res: float = 1.0


def people_near(tiles, win, grid) -> np.ndarray:
    """Cells within PEOPLE_REACH of a building where people live, shop, learn, get care,
    meet, stay or do sport (BAG use). Pavement along business parks and offices only
    does not count towards the targets."""
    bags = [gpd.read_file(ROOT / "data" / "raw" / f"{x}_{y}" / "bag_pand.geojson", bbox=box(*win).bounds)
            for x, y in tiles if box(x, y, x + TILE, y + TILE).intersects(box(*win).buffer(PEOPLE_REACH))
            and (ROOT / "data" / "raw" / f"{x}_{y}" / "bag_pand.geojson").exists()]
    bag = pd.concat(bags).set_crs(gl.CRS, allow_override=True).drop_duplicates("identificatie")
    uses = bag["gebruiksdoel"].astype(str)
    lively = bag[uses.str.contains("|".join(PEOPLE_USES))]
    mask = gl._raster(lively.geometry, grid).astype(bool)
    return distance_transform_edt(~mask) <= PEOPLE_REACH


def window(bounds):
    xmin, ymin, xmax, ymax = (np.floor(bounds[0]) - MARGIN, np.floor(bounds[1]) - MARGIN,
                              np.ceil(bounds[2]) + MARGIN, np.ceil(bounds[3]) + MARGIN)
    return xmin, ymin, xmax, ymax


def stitch(tiles, date, win):
    """Landcover, tree heights and the shadow bands needed, on the window, from tile cores."""
    xmin, ymin, xmax, ymax = win
    h, w = int(ymax - ymin), int(xmax - xmin)
    lc = np.full((h, w), 7, "uint8")
    trees = np.zeros((h, w), "float32")
    bands = sorted({b for hr in HOUR_WEIGHT for b in (hr, hr + 1)})
    shadow = {b: np.ones((h, w), "float32") for b in bands}
    for x, y in tiles:
        if not box(x, y, x + TILE, y + TILE).intersects(box(*win)):
            continue
        # overlap of the tile core and the window, in window and tile pixel indices
        x0, x1 = max(x, xmin), min(x + TILE, xmax)
        y0, y1 = max(y, ymin), min(y + TILE, ymax)
        wr, wc = slice(int(ymax - y1), int(ymax - y0)), slice(int(x0 - xmin), int(x1 - xmin))
        tr = slice(int(y + TILE + BUFFER - y1), int(y + TILE + BUFFER - y0))
        tc = slice(int(x0 - x + BUFFER), int(x1 - x + BUFFER))
        inp, out = inputs_dir(f"{x}_{y}"), output_dir(f"{x}_{y}", "mps", date)
        lc[wr, wc] = rasterio.open(inp / "Landcover.tif").read(1)[tr, tc]
        trees[wr, wc] = rasterio.open(inp / "Trees.tif").read(1)[tr, tc]
        with rasterio.open(out / "Shadow_0_0.tif") as src:
            for b in bands:
                shadow[b][wr, wc] = src.read(b + 1)[tr, tc]
    return lc, trees, shadow


def sun(date):
    """Sun altitude and azimuth at h-0:30 and h+0:30 for each hour h, the middles of the
    two SOLWEIG bands whose mean is the shade "at h"."""
    out = {}
    for h in HOUR_WEIGHT:
        t = pd.DatetimeIndex([f"{date} {h - 1}:30", f"{date} {h}:30"]).tz_localize("Europe/Amsterdam")
        sp = pvlib.solarposition.get_solarposition(t, LAT, LON)
        out[h] = list(zip(sp["apparent_elevation"], sp["azimuth"], strict=True))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--buurt", nargs="+", required=True, help="buurt codes, e.g. FK03")
    ap.add_argument("--district", default="nieuw-west")
    ap.add_argument("--date", default="2015-07-01")
    ap.add_argument("--max", type=int, default=400)
    ap.add_argument("--no-utilities", action="store_true",
                    help="ignore cables and pipes (open data, amsterdam_heat.utilities)")
    args = ap.parse_args()

    city = ROOT / "data" / "raw" / "city"
    out = ROOT / "data" / "processed" / "trees" / args.name
    out.mkdir(parents=True, exist_ok=True)
    tree, rules = pl.TreeSpec(), pl.Rules()

    buurten = gl.read_vector(city / f"buurten_{args.district}.geojson")
    area = buurten[buurten["code"].isin(args.buurt)]
    names = ", ".join(area["naam"])
    win = window(area.total_bounds)
    xmin, ymin, xmax, ymax = win
    grid = Grid(from_origin(xmin, ymax, 1, 1), (int(ymax - ymin), int(xmax - xmin)))
    tiles = json.loads((city / f"tiles_{args.district}.json").read_text())
    lc, trees, shadow = stitch(tiles, args.date, win)

    bb = box(*win)
    wegdeel = gpd.read_file(city / f"bgt_wegdeel_{args.district}.geojson", bbox=bb.bounds)
    wegdeel = wegdeel.set_crs(gl.CRS, allow_override=True)
    green = gpd.read_file(city / f"bgt_begroeidterreindeel_{args.district}.geojson", bbox=bb.bounds)
    green = green.set_crs(gl.CRS, allow_override=True)
    green = green[green["fysiek_voorkomen"].isin(GREEN_TYPES) & (green["bronhouder"] == "G0363")]
    walk = gl._raster(wegdeel[wegdeel["functie"].isin(gl.WALK_FUNCTIONS)].geometry, grid).astype(bool)
    public_green = gl._raster(green.geometry, grid).astype(bool)
    inside = gl._raster(area.geometry, grid).astype(bool)
    routes = gl.read_vector(city / "ams_plushoofdnetten.geojson")
    routes = routes[routes["VOET"].isin(["PLUS", "HOOFD"]) & routes.intersects(bb)]
    route_lines = gl._raster(routes.geometry, grid).astype(bool) if len(routes) else np.zeros(grid.shape, bool)
    near_route = distance_transform_edt(~route_lines) <= ROUTE_REACH if route_lines.any() else route_lines

    people = people_near(tiles, win, grid)
    target = walk & inside & (lc != 2) & (lc != 7) & people
    route_target = target & near_route
    weight = np.where(target, 1.0, 0.0) + np.where(route_target, 1.0, 0.0)
    sunlit = {h: ~gl.shaded_at(shadow, h) for h in HOUR_WEIGHT}
    bands = {h: (shadow[h], shadow[h + 1]) for h in HOUR_WEIGHT}

    plantable = (walk | public_green) & (lc != 2) & (lc != 7)
    plantable &= gl._raster([g.buffer(10) for g in area.geometry], grid).astype(bool)
    blocked = np.zeros(grid.shape, bool)
    if not args.no_utilities:
        from amsterdam_heat import utilities

        blocked |= utilities.utility_mask(grid.transform, grid.shape, utilities.load_layers(ROOT / "data" / "raw" / "utilities"))
    cands = pl.candidates(plantable & ~blocked, lc == 2, trees > 2.0, rules)
    patches = {h: tuple(pl.footprint_patch(tree, alt, az, PATCH) for alt, az in pos)
               for h, pos in sun(args.date).items()}
    print(f"{names}: {len(cands)} candidate spots, {target.sum()} m2 of pavement, "
          f"{route_target.sum()} m2 near main routes", flush=True)

    def shares(state):
        s15 = state.shaded(15)
        pave = float(s15[target].mean())
        route = float(s15[route_target].mean()) if route_target.any() else float("nan")
        return pave, route

    def done(state):
        pave, route = shares(state)
        return pave >= gl.NEIGHBOURHOOD_SHADE_TARGET and (np.isnan(route) or route >= gl.ROUTE_SHADE_TARGET)

    new_state = lambda: pl.Shade(bands, patches, weight, HOUR_WEIGHT)
    before = shares(new_state())
    chosen = pl.greedy(cands, new_state(), args.max, rules.spacing, stop=done)

    # replay to record the shade after each tree
    state = new_state()
    steps, added = [], []
    for i, r in chosen.iterrows():
        was = state.shaded(15) & target
        state.add((int(r["row"]), int(r["col"])))
        new = state.shaded(15) & target & ~was
        for geom, _ in shapes(new.astype("uint8"), mask=new, transform=grid.transform):
            added.append({"rank": i + 1, "geometry": shape(geom)})
        pave, route = shares(state)
        steps.append({"trees": i + 1, "pavement_shade_15": pave, "route_shade_15": route,
                      "pavement_shade_11": float(state.shaded(11)[target].mean()),
                      "pavement_shade_17": float(state.shaded(17)[target].mean())})
    shaded = {h: state.shaded(h) for h in HOUR_WEIGHT}
    steps = pd.DataFrame(steps)
    steps.to_csv(out / "steps.csv", index=False)

    xs = xmin + chosen["col"] + 0.5
    ys = ymax - chosen["row"] - 0.5
    on = ["pavement" if walk[r, c] else "green" for r, c in zip(chosen["row"], chosen["col"], strict=True)]
    gdf = gpd.GeoDataFrame({"rank": np.arange(1, len(chosen) + 1), "gain": chosen["gain"].round(1), "on": on},
                           geometry=[Point(x, y) for x, y in zip(xs, ys, strict=True)], crs=gl.CRS)
    gdf.to_file(out / "trees.geojson", driver="GeoJSON")
    if added:
        gpd.GeoDataFrame(added, crs=gl.CRS).dissolve("rank").reset_index().to_file(
            out / "shade_added.geojson", driver="GeoJSON")
    summary = {"name": args.name, "buurten": names, "codes": args.buurt, "trees": len(gdf),
               "candidates": len(cands), "pavement_m2": int(target.sum()),
               "route_m2": int(route_target.sum()),
               "pavement_shade_15_before": before[0], "route_shade_15_before": before[1],
               "pavement_shade_15_after": steps["pavement_shade_15"].iloc[-1] if len(steps) else before[0],
               "route_shade_15_after": steps["route_shade_15"].iloc[-1] if len(steps) else before[1],
               "tree": tree.__dict__, "rules": rules.__dict__, "window": list(win),
               "utilities": not args.no_utilities}
    summary["trees_xy"] = [[float(x), float(y)] for x, y in zip(xs, ys, strict=True)]
    old = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else {}
    if old.get("trees_xy") == summary["trees_xy"]:
        # same trees: keep the full model checks verify_trees.py already ran
        summary.update({k: v for k, v in old.items() if k.startswith("solweig")})
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    first = new_state()
    gain0 = np.array([first.gain(c) for c in cands])
    np.savez_compressed(out / "masks.npz", target=target, route_target=route_target, window=np.array(win),
                        candidates=cands, gain0=gain0, buildings=lc == 2, canopy=trees > 2.0,
                        shaded15=new_state().shaded(15), near_route=near_route, walk=walk)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("tree", "rules", "window")}, indent=1))

    fig, ax = plt.subplots(1, 2, figsize=(14, 6.5), constrained_layout=True,
                           gridspec_kw={"width_ratios": [1.6, 1]})
    ext = (xmin, xmax, ymin, ymax)
    ax[0].imshow(lc == 2, extent=ext, cmap="Greys", vmin=0, vmax=3)
    ax[0].imshow(np.where(trees > 2, 1.0, np.nan), extent=ext, cmap="Greens", vmin=0, vmax=1.5, alpha=0.6)
    ax[0].imshow(np.where(target & ~sunlit[15], 1.0, np.nan), extent=ext, cmap="Blues", vmin=0, vmax=1.4)
    ax[0].imshow(np.where(target & sunlit[15] & shaded[15], 1.0, np.nan), extent=ext, cmap="cool", vmin=0, vmax=1)
    ax[0].imshow(np.where(target & ~shaded[15], 1.0, np.nan), extent=ext, cmap="autumn", vmin=0, vmax=3)
    gdf.plot(ax=ax[0], color="darkgreen", markersize=12, edgecolor="white", linewidth=0.4)
    area.boundary.plot(ax=ax[0], color="k", linewidth=0.8)
    if len(routes):
        routes.clip(bb).plot(ax=ax[0], color="tab:orange", linewidth=1)
    ax[0].set_xlim(xmin, xmax)
    ax[0].set_ylim(ymin, ymax)
    ax[0].set_axis_off()
    ax[0].set_title(f"{names}: pavement at 15:00, shade now (blue), added by {len(gdf)} trees (pink), sun (orange)")
    if len(steps):
        ax[1].plot(steps["trees"], 100 * steps["pavement_shade_15"], label="pavements")
        ax[1].plot(steps["trees"], 100 * steps["route_shade_15"], label="main route pavements")
    ax[1].axhline(30, color="tab:blue", ls=":", lw=1)
    ax[1].axhline(40, color="tab:orange", ls=":", lw=1)
    ax[1].set_xlabel("new trees, best first")
    ax[1].set_ylabel("shade at 15:00 (%)")
    ax[1].set_title("Shade gained per tree (geometry, before the SOLWEIG check)")
    ax[1].legend()
    fig.savefig(ROOT / "figures" / f"trees_{args.name}.png", dpi=120)


if __name__ == "__main__":
    main()
