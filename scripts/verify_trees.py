"""Check a tree plan with the full model: SOLWEIG and PET with and without the new trees.

    uv run python scripts/verify_trees.py --name osdorpplein

Takes data/processed/trees/<name>/ from plan_trees.py. Every tile whose 700 m run
area holds a new crown is copied to <tile>_plan-<name> with the crowns burned into
Trees.tif, then run with run_solweig.py and compute_pet.py. On the target pavements
it compares shade at 11:00, 15:00 and 17:00, Tmrt at 15:00 and afternoon PET.
Writes docs/trees_<name>.md and adds the results to summary.json.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import box

from amsterdam_heat import guidelines as gl
from amsterdam_heat import planting as pl
from amsterdam_heat.paths import inputs_dir, output_dir

ROOT = Path(__file__).resolve().parents[1]
TILE, BUFFER = 500, 100


def run(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def window_stack(tiles, names, date, win, fname, bands):
    """Bands of one output raster on the window, from tile cores (names maps tile to run)."""
    xmin, ymin, xmax, ymax = win
    h, w = int(ymax - ymin), int(xmax - xmin)
    out = np.full((len(bands), h, w), np.nan, "float32")
    for x, y in tiles:
        if not box(x, y, x + TILE, y + TILE).intersects(box(*win)):
            continue
        x0, x1 = max(x, xmin), min(x + TILE, xmax)
        y0, y1 = max(y, ymin), min(y + TILE, ymax)
        wr, wc = slice(int(ymax - y1), int(ymax - y0)), slice(int(x0 - xmin), int(x1 - xmin))
        tr = slice(int(y + TILE + BUFFER - y1), int(y + TILE + BUFFER - y0))
        tc = slice(int(x0 - x + BUFFER), int(x1 - x + BUFFER))
        with rasterio.open(output_dir(names.get((x, y), f"{x}_{y}"), "mps", date) / fname) as src:
            for k, b in enumerate(bands):
                out[k, wr, wc] = src.read(b + 1)[tr, tc]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--district", default="nieuw-west")
    ap.add_argument("--date", default="2015-07-01")
    args = ap.parse_args()

    plan = ROOT / "data" / "processed" / "trees" / args.name
    summary = json.loads((plan / "summary.json").read_text())
    tree = pl.TreeSpec(**summary["tree"])
    trees = gpd.read_file(plan / "trees.geojson").set_crs(gl.CRS, allow_override=True)
    masks = np.load(plan / "masks.npz")
    target, route_target, win = masks["target"], masks["route_target"], tuple(masks["window"])
    tiles = json.loads((ROOT / "data" / "raw" / "city" / f"tiles_{args.district}.json").read_text())

    names = {}
    for x, y in tiles:
        run_area = box(x - BUFFER, y - BUFFER, x + TILE + BUFFER, y + TILE + BUFFER)
        mine = trees[trees.buffer(tree.crown_radius).intersects(run_area)]
        if mine.empty:
            continue
        src, name = f"{x}_{y}", f"{x}_{y}_plan-{args.name}"
        dst = inputs_dir(name)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(inputs_dir(src), dst, ignore=shutil.ignore_patterns("windcoeff", "Buildings.tif"))
        with rasterio.open(dst / "Trees.tif", "r+") as t:
            rows, cols = rasterio.transform.rowcol(t.transform, mine.geometry.x, mine.geometry.y)
            t.write(pl.burn(t.read(1), rows, cols, tree), 1)
        print(f"{name}: {len(mine)} trees", flush=True)
        run("scripts/run_solweig.py", "--tile", name, "--date", args.date)
        run("scripts/compute_pet.py", "--tile", name, "--date", args.date)
        names[(x, y)] = name

    hours = (11, 15, 17)
    sb = sorted({b for h in hours for b in (h, h + 1)})
    res = {}
    for label, nm in (("before", {}), ("after", names)):
        sh = window_stack(tiles, nm, args.date, win, "Shadow_0_0.tif", sb)
        shadow = {b: sh[k] for k, b in enumerate(sb)}
        tm = window_stack(tiles, nm, args.date, win, "TMRT_0_0.tif", [15, 16]).mean(axis=0)
        pet = np.nanmean(window_stack(tiles, nm, args.date, win, "PET_0_0.tif", list(gl.AFTERNOON)), axis=0)
        r = {f"pavement_shade_{h}": float(gl.shaded_at(shadow, h)[target].mean()) for h in hours}
        if route_target.any():
            r["route_shade_15"] = float(gl.shaded_at(shadow, 15)[route_target].mean())
        r["tmrt_15"] = float(np.nanmean(tm[target]))
        r["pet_afternoon"] = float(np.nanmean(pet[target]))
        r["pet_extreme_share"] = float(np.mean(pet[target] > 41))
        res[label] = (r, tm, pet)
    before, after = res["before"][0], res["after"][0]
    d_tm = res["after"][1] - res["before"][1]
    d_pet = res["after"][2] - res["before"][2]
    changed = target & (d_tm < -1)
    after["tmrt_15_drop_where_shaded"] = float(-np.nanmean(d_tm[changed])) if changed.any() else 0.0
    after["pet_drop_where_shaded"] = float(-np.nanmean(d_pet[changed])) if changed.any() else 0.0
    after["pavement_m2_cooled"] = int(changed.sum())
    summary["solweig"] = {"before": before, "after": after, "tiles": list(names.values())}
    (plan / "summary.json").write_text(json.dumps(summary, indent=1))

    pct = lambda v: f"{100 * v:.0f}%"
    rows = [("Pavement shade at 11:00", "pavement_shade_11", pct), ("Pavement shade at 15:00", "pavement_shade_15", pct),
            ("Pavement shade at 17:00", "pavement_shade_17", pct)]
    if "route_shade_15" in before:
        rows.append(("Main route pavement shade at 15:00", "route_shade_15", pct))
    rows += [("Mean Tmrt on pavements at 15:00", "tmrt_15", lambda v: f"{v:.1f} C"),
             ("Mean afternoon PET on pavements", "pet_afternoon", lambda v: f"{v:.1f} C"),
             ("Pavement above 41 C PET", "pet_extreme_share", pct)]
    geo = summary
    lines = [
        f"# New trees for {summary['buurten']}", "",
        (f"{summary['trees']} new trees, each {tree.height:g} m tall with an {2 * tree.crown_radius:g} m crown, "
         f"chosen one at a time where they add the most shade on {summary['pavement_m2']} m2 of pavement "
         f"({summary['route_m2']} m2 along the main walking routes), from {summary['candidates']} possible spots on public "
         "pavement and green at least 4 m from facades and 5 m from existing crowns. Cables and pipes are "
         "not in open data, so every spot needs the city's check. The full model (SOLWEIG and PET, "
         "1 July 2015) is then run with and without the trees."), "",
        "| On the neighbourhood's pavements | Now | With the trees | Search estimate |", "|---|---|---|---|",
        *[f"| {t} | {f(before[k])} | {f(after[k])} | "
          f"{pct(geo[k.replace('pavement_shade_15', 'pavement_shade_15_after').replace('route_shade_15', 'route_shade_15_after')]) if k in ('pavement_shade_15', 'route_shade_15') else ''} |"
          for t, k, f in rows], "",
        (f"Where the new crowns shade the pavement ({after['pavement_m2_cooled']} m2), Tmrt at 15:00 drops by "
         f"{after['tmrt_15_drop_where_shaded']:.0f} C and afternoon PET by {after['pet_drop_where_shaded']:.1f} C on average."), "",
        f"![Tree plan](../figures/trees_{args.name}.png)",
    ]
    (ROOT / "docs" / f"trees_{args.name}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
