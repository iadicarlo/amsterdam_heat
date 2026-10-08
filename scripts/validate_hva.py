"""Compare the model with the HvA thermal comfort measurements (2015 and 2016).

    uv run python scripts/validate_hva.py            # builds tiles and runs what is missing
    uv run python scripts/validate_hva.py --compare-only

For every measurement day and site the matching 500 m tile is built (once) and run
with KNMI Schiphol weather and GLIDE-SOL wind. Observed hourly Tmrt (from the globe)
and PET are compared with the median of model pixels within RADIUS metres of the
site that are in the same situation that hour: sunlit, in tree shade, or in building
shade. Writes docs/validation_hva.md and figures/validation_hva.png.

Buildings and trees come from 2020 to 2023 data, the measurements from 2015 and
2016, so places that changed in between add to the scatter.
"""

import argparse
import json
import subprocess
import sys

import matplotlib
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import binary_dilation

from amsterdam_heat import sources
from amsterdam_heat.metfile import knmi_to_umep
from amsterdam_heat.paths import ROOT, inputs_dir, output_dir
from amsterdam_heat.validation import geocode, hourly, read_hva

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RADIUS = 40.0  # m
DEVICE = "mps"
HVA = ROOT / "data" / "raw" / "validation" / "hva_thermal_comfort" / "meteorological_data.xlsx"
MAP_SITES = ROOT / "data" / "interim" / "validation_hva_sites_from_map.json"
# sheet site name -> key in the georeferenced site map, or a PDOK query for squares
SITE_SOURCE = {
    "Dam": ("pdok", "Dam"), "Leidseplein": ("pdok", "Leidseplein"),
    "Mahlerplein": ("pdok", "Gustav Mahlerplein"), "Frederiksplein": ("pdok", "Frederiksplein"),
    "IJ promenade": ("map", "Q IJ promenade"), "Stationsplein": ("map", "L Stationsplein"),
    "Vondelpark": ("map", "O Vondelpark"), "Museumplein": ("map", "N Museumplein"),
    "Magere Brug": ("map", "R Magere Brug"), "Oosterdokskade": ("map", "I Oosterdokskade"),
    "AMG Schmidtstraat": ("map", "A AMG Schmidtstraat"), "Rembrandtplein": ("map", "J Rembrandtplein"),
    "Thorbeckeplein": ("map", "M Thorbeckeplein"), "Spui": ("map", "K Spui"),
    "Weesperzijde": ("map", "U Weesperzijde"), "Amstelplein": ("map", "B Amstelplein"),
    "Reguliersgracht": ("map", "T Reguliersgracht"), "Museumplein pond": ("map", "S Museumplein pond"),
    "Museumstraat": ("map", "G Museumstraat"), "Frederiksplein pond": ("map", "P Frederiksplein fountain"),
}
SKIP = {"Oosterdok-roof"}  # on a roof, the model is at street level


def run(script: str, *args: str) -> None:
    print(script, *args, flush=True)
    subprocess.run([sys.executable, script, *args], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)


def site_xy(site: str, map_sites: dict) -> tuple[float, float]:
    kind, key = SITE_SOURCE[site]
    return geocode(key) if kind == "pdok" else tuple(map_sites[key])


def prepare(tile: str, x0: float, y0: float, date: str) -> None:
    """Inputs once per tile, met per date, model run and PET per tile and date."""
    inp = inputs_dir(tile)
    if not (inp / "Building_DSM.tif").exists():
        run("scripts/make_tile.py", "--x", str(x0), "--y", str(y0), "--date", date)
    met = inp / f"met_{date}.txt"
    if not met.exists():
        d = pd.Timestamp(date)
        raw = ROOT / "data" / "raw" / tile
        knmi = raw / f"knmi_240_{date}.json"
        if not knmi.exists():
            start = (d - pd.Timedelta(days=1)).strftime("%Y%m%d") + "20"
            sources.knmi_hourly(240, start, d.strftime("%Y%m%d") + "24", knmi)
        knmi_to_umep(knmi, date, met)
    out = output_dir(tile, DEVICE, date)
    if not (out / "TMRT_0_0.tif").exists():
        run("scripts/run_solweig.py", "--tile", tile, "--date", date, "--device", DEVICE, "--fresh")
    if not (out / "PET_0_0.tif").exists():
        run("scripts/compute_pet.py", "--tile", tile, "--date", date, "--device", DEVICE)


def model_at_site(tile: str, date: str, x: float, y: float, hour: int, situation: str):
    inp, out = inputs_dir(tile), output_dir(tile, DEVICE, date)
    with rasterio.open(inp / "Landcover.tif") as src:
        lc = src.read(1)
        transform = src.transform
    trees = rasterio.open(inp / "Trees.tif").read(1)
    band = hour + 1
    shadow = rasterio.open(out / "Shadow_0_0.tif").read(band)
    tmrt = rasterio.open(out / "TMRT_0_0.tif").read(band)
    pet = rasterio.open(out / "PET_0_0.tif").read(band)
    rows, cols = np.indices(lc.shape)
    xs, ys = rasterio.transform.xy(transform, rows.ravel(), cols.ravel())
    near = (np.hypot(np.array(xs) - x, np.array(ys) - y) <= RADIUS).reshape(lc.shape)
    outdoor = near & (lc != 2) & (lc != 7)
    near_tree = binary_dilation(trees > 0, iterations=3)
    if situation == "sun":
        sel = outdoor & (shadow > 0.5)
    elif situation == "shade of trees":
        sel = outdoor & (shadow < 0.5) & near_tree
    else:
        sel = outdoor & (shadow < 0.5) & ~near_tree
    if sel.sum() < 5:
        return np.nan, np.nan, int(sel.sum())
    return float(np.median(tmrt[sel])), float(np.median(pet[sel])), int(sel.sum())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--compare-only", action="store_true")
    args = ap.parse_args()

    obs = hourly(read_hva(HVA))
    obs = obs[~obs["sheet"].str.startswith(tuple(SKIP))]
    map_sites = json.loads(MAP_SITES.read_text())["sites"]
    xy = {s: site_xy(s, map_sites) for s in obs["site"].unique()}
    obs["x"] = [xy[s][0] for s in obs["site"]]
    obs["y"] = [xy[s][1] for s in obs["site"]]
    obs["x0"] = (obs["x"] // 500 * 500).astype(int)
    obs["y0"] = (obs["y"] // 500 * 500).astype(int)
    obs["tile"] = obs["x0"].astype(str) + "_" + obs["y0"].astype(str)

    if not args.compare_only:
        for (tile, x0, y0, date), _ in obs.groupby(["tile", "x0", "y0", "date"]):
            prepare(tile, x0, y0, date)

    rec = [model_at_site(r.tile, r.date, r.x, r.y, int(r.hour), r.situation) for r in obs.itertuples()]
    obs["tmrt_model"], obs["pet_model"], obs["pixels"] = zip(*rec, strict=True)
    obs.to_csv(ROOT / "data" / "processed" / "validation_hva.csv", index=False)
    ok = obs.dropna(subset=["tmrt_model"])

    def stats(o, m):
        d = m - o
        return f"{d.mean():+.1f}", f"{np.sqrt((d**2).mean()):.1f}", f"{np.corrcoef(o, m)[0, 1]:.2f}"

    intro = (
        f"{len(ok)} site-hours with model pixels in the same situation within {RADIUS:.0f} m "
        f"({len(obs) - len(ok)} without). Observed Tmrt from the 38 mm grey globe "
        "(Thorsson et al. 2007); observed PET from the measured air temperature, humidity, "
        "wind and that Tmrt."
    )
    lines = [
        "# Model against HvA measurements, Amsterdam 2015 and 2016", "", intro, "",
        "| Situation | n | Tmrt bias (K) | Tmrt RMSE (K) | Tmrt r | PET bias (K) | PET RMSE (K) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, g in [("all", ok), *ok.groupby("situation")]:
        b, e, r = stats(g["tmrt"], g["tmrt_model"])
        pb, pe, _ = stats(g["pet"], g["pet_model"])
        lines.append(f"| {name} | {len(g)} | {b} | {e} | {r} | {pb} | {pe} |")
    schiphol = []
    for r in ok.itertuples():
        met = np.loadtxt(inputs_dir(r.tile) / f"met_{r.date}.txt", skiprows=1)
        schiphol.append(met[int(r.hour), 11])
    dta = ok["ta"].to_numpy() - np.array(schiphol)
    lines += ["", (f"The model uses Schiphol air temperature; in the measured squares the air was "
                   f"{dta.mean():+.1f} K warmer on average (range {dta.min():+.1f} to {dta.max():+.1f}). "
                   "That part of the PET difference is the urban heat island, not radiation.")]
    (ROOT / "docs" / "validation_hva.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    fig, ax = plt.subplots(1, 2, figsize=(11, 5))
    colours = {"sun": "#d95f02", "shade of trees": "#1b9e77", "shade of buildings": "#7570b3"}
    for a, (o, m, lab) in zip(ax, [("tmrt", "tmrt_model", "Tmrt"), ("pet", "pet_model", "PET")],
                              strict=True):
        for sit, g in ok.groupby("situation"):
            a.scatter(g[o], g[m], s=18, label=sit, color=colours.get(sit, "k"))
        lo, hi = np.nanmin(ok[[o, m]].values) - 2, np.nanmax(ok[[o, m]].values) + 2
        a.plot([lo, hi], [lo, hi], "k--", lw=0.8)
        a.set_xlabel(f"Observed {lab} (C)")
        a.set_ylabel(f"Model {lab} (C)")
        a.set_title(lab)
    ax[0].legend(frameon=False)
    fig.text(0.01, 0.01, "Measurements: HvA, Thermal comfort Amsterdam (CC BY 4.0). Model: SOLWEIG-GPU",
             fontsize=8, color="0.4")
    fig.tight_layout()
    fig.savefig(ROOT / "figures" / "validation_hva.png", dpi=100)


if __name__ == "__main__":
    main()
