"""Score one tile and day against Amsterdam's heat design guidelines.

    uv run python scripts/check_guidelines.py --tile 121500_485000 --date 2015-07-01

Needs a SOLWEIG run with shadow output and PET (scripts/run_solweig.py, then
scripts/compute_pet.py). Writes docs/guidelines_<tile>_<date>.md and a figure.
"""

import argparse
from pathlib import Path

import matplotlib
import numpy as np
import rasterio

from amsterdam_heat import guidelines as gl
from amsterdam_heat.paths import ROOT, inputs_dir, output_dir
from amsterdam_heat.tile_inputs import TileSpec

matplotlib.use("Agg")
import matplotlib.pyplot as plt

CREDIT = ("AHN4, BAG, BGT (PDOK); luchtfoto infrarood 2023, bomen, hoofdnetten, buurten "
          "(Gemeente Amsterdam); KNMI. Model: SOLWEIG-GPU")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--device", default="mps")
    args = ap.parse_args()

    x, y = (float(v) for v in args.tile.split("_")[:2])
    spec = TileSpec(x, y)
    raw = ROOT / "data" / "raw" / spec.corner
    out = output_dir(args.tile, args.device, args.date)
    layers = gl.TileLayers(
        spec=spec,
        landcover=rasterio.open(inputs_dir(args.tile) / "Landcover.tif").read(1),
        trees=rasterio.open(inputs_dir(args.tile) / "Trees.tif").read(1),
        shadow=rasterio.open(out / "Shadow_0_0.tif").read(),
        pet=rasterio.open(out / "PET_0_0.tif").read(),
    )
    walk = gl.walking_areas(gl.read_vector(raw / "bgt_wegdeel.geojson"), spec)
    routes = gl.route_shade(layers, gl.read_vector(raw / "ams_plushoofdnetten.geojson"), walk)
    buurten = gl.neighbourhood_shade(layers, gl.read_vector(raw / "ams_buurten.geojson"), walk)
    parks = gl.green_areas(gl.read_vector(raw / "bgt_begroeidterreindeel.geojson"), spec)
    cool, pet_pm = gl.cool_spots(layers, parks)
    dist = gl.walking_distance(layers, cool)
    homes = gl.homes_near_cool_spots(layers, gl.read_vector(raw / "bag_pand.geojson"), dist)

    pct = lambda v: f"{100 * v:.0f}%"
    lines = [
        f"# Heat guideline check, tile {args.tile}, {args.date}",
        "",
        (
            "Shade at sun positions of 11:00, 15:00 and 17:00 local time. Cool spots use the "
            "PET averaged over 12:00 to 18:00. Only the 500 m core of the tile is scored."
        ),
        "",
        "## Important walking routes (target 40% shade)",
        "",
        "| Street | Network | Walking area (m2) | 11:00 | 15:00 | 17:00 | 40% at 15:00 |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in routes.iterrows():
        lines.append(f"| {r['street']} | {r['network']} | {r['area_m2']:.0f} | {pct(r['shade_11'])} "
                     f"| {pct(r['shade_15'])} | {pct(r['shade_17'])} | "
                     f"{'yes' if r['meets_40pct_at_15'] else 'no'} |")
    lines += ["", "## Neighbourhood walking areas (target 30% shade)", "",
              "| Buurt | Walking area (m2) | 11:00 | 15:00 | 17:00 | 30% at 15:00 |",
              "|---|---|---|---|---|---|"]
    for _, r in buurten.iterrows():
        lines.append(f"| {r['buurt']} | {r['walking_area_m2']:.0f} | {pct(r['shade_11'])} "
                     f"| {pct(r['shade_15'])} | {pct(r['shade_17'])} | "
                     f"{'yes' if r['meets_30pct_at_15'] else 'no'} |")
    within = (homes["distance_m"] <= gl.COOL_DISTANCE).mean() if len(homes) else float("nan")
    lines += ["", "## Cool spots (PET 35 C or lower, 200 m2, in green of 1000 m2, within 300 m walking)",
              "",
              f"Cool spot area in the tile core: {cool[layers.core].sum() * spec.res**2:.0f} m2.",
              (f"Residential buildings in the core: {len(homes)}; within 300 m walking of a cool "
               f"spot: {pct(within)}."),
              f"Afternoon PET on walkable ground in the core: median {np.nanmedian(pet_pm[layers.core & layers.walkable]):.1f} C."]
    report = ROOT / "docs" / f"guidelines_{args.tile}_{args.date}.md"
    report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    b = slice(round(spec.buffer / spec.res), -round(spec.buffer / spec.res))
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.6))
    sh15 = gl.shaded_at(layers.shadow, 15).astype(float)
    shade_show = np.where(walk, sh15, np.nan)
    ax[0].imshow(layers.landcover[b, b] == 2, cmap="Greys", vmin=0, vmax=3)
    ax[0].imshow(shade_show[b, b], cmap="RdYlBu", vmin=0, vmax=1)
    ax[0].set_title("Walking areas at 15:00 (blue shade, red sun)")
    pet_show = np.where(layers.walkable, pet_pm, np.nan)
    im = ax[1].imshow(pet_show[b, b], cmap="RdYlBu_r", vmin=28, vmax=48)
    ax[1].contour(cool[b, b], levels=[0.5], colors="k", linewidths=0.8)
    ax[1].set_title("Afternoon PET (C), cool spots outlined")
    fig.colorbar(im, ax=ax[1], shrink=0.75)
    d_show = np.where(layers.walkable, dist, np.nan)
    im = ax[2].imshow(np.clip(d_show[b, b], 0, 600), cmap="magma_r", vmin=0, vmax=600)
    ax[2].contour((d_show[b, b] <= gl.COOL_DISTANCE).astype(float), levels=[0.5], colors="c")
    ax[2].set_title("Walking distance to a cool spot (m), 300 m line")
    fig.colorbar(im, ax=ax[2], shrink=0.75)
    for a in ax:
        a.axis("off")
    fig.suptitle(f"Heat guideline check, tile {args.tile}, {args.date}")
    fig.text(0.01, 0.01, CREDIT, fontsize=8, color="0.4")
    fig.tight_layout()
    path = ROOT / "figures" / f"guidelines_{args.tile}_{args.date}.png"
    fig.savefig(path, dpi=100)
    print(Path(path).relative_to(ROOT))


if __name__ == "__main__":
    main()
