"""Turn the downloaded ECOSTRESS land surface temperature tiles into a hot-day series.

    uv run python scripts/process_ecostress.py                # all passes, table and figure
    uv run python scripts/process_ecostress.py --min-clear 0.5

Input is ECO_L2T_LSTE v002 (70 m MGRS tiles 31UFU and 31UFT) in data/raw/satellite/ecostress,
fetched by scripts/fetch_ecostress.py. One pass is one ISS orbit: all tiles and scenes of
that orbit are mosaicked. Where a granule was reprocessed, only the latest build is used.

A pixel is clear when LST is finite, the cloud layer is 0 (with a --buffer pixel margin) and QC bits 0 and 1 (mandatory QA)
are 00 (best) or 01 (nominal). Each pass is warped to RD New (EPSG:28992) on one fixed 70 m
grid over lon 4.73 to 5.07, lat 52.28 to 52.43 and kept when at least --min-clear of the box
is clear. Kept passes go to data/processed/satellite/ecostress/ecostress_<date>_<HHMM>.tif
with two bands: LST in deg C (NaN where not clear) and a clear mask (0 not clear, 1 clear
land, 2 clear water).

The ECOSTRESS cloud mask misses thin cloud and cloud shadow. The table column cold_fraction
is the share of clear land more than 3 C below the Schiphol maximum. Above about 0.1 on an
afternoon pass, the scene is likely cloud affected; the figure leaves those passes out.

The L2T product has no water layer in our download, so water is taken
from the Landsat clear masks in data/raw/satellite/landsat (water in most clear scenes).
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject
from scipy.ndimage import binary_dilation

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "satellite" / "ecostress"
LANDSAT = ROOT / "data" / "raw" / "satellite" / "landsat"
OUT = ROOT / "data" / "processed" / "satellite" / "ecostress"
TABLE = ROOT / "data" / "interim" / "ecostress_hot_days.csv"
FIGURE = ROOT / "figures" / "ecostress_hot_days.png"
BBOX = (4.73, 52.28, 5.07, 52.43)  # lon min, lat min, lon max, lat max: Amsterdam
TZ = ZoneInfo("Europe/Amsterdam")
RES = 70.0
CRS = "EPSG:28992"
NAME = re.compile(r"ECOv002_L2T_LSTE_(\d{5})_(\d{3})_(31U\w\w)_(\d{8}T\d{6})_(\d{4})_(\d{2})")


def grid():
    """Fixed 70 m RD New grid that covers the box, snapped to whole 70 m."""
    t = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    lo, la = np.meshgrid(np.linspace(BBOX[0], BBOX[2], 50), np.linspace(BBOX[1], BBOX[3], 50))
    x, y = t.transform(lo, la)
    x0, x1 = np.floor(x.min() / RES) * RES, np.ceil(x.max() / RES) * RES
    y0, y1 = np.floor(y.min() / RES) * RES, np.ceil(y.max() / RES) * RES
    return from_origin(x0, y1, RES, RES), int((x1 - x0) / RES), int((y1 - y0) / RES)


def box_mask(transform, width, height):
    """True for grid cells inside the lon/lat box (the grid itself is a bit larger)."""
    t = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    cols, rows = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
    lon, lat = t.transform(*(transform * (cols, rows)))
    return (lon >= BBOX[0]) & (lon <= BBOX[2]) & (lat >= BBOX[1]) & (lat <= BBOX[3])


def schiphol_tmax(start: str) -> dict[str, float]:
    r = requests.post(
        "https://www.daggegevens.knmi.nl/klimatologie/daggegevens",
        data={"start": start.replace("-", ""), "end": datetime.now(TZ).strftime("%Y%m%d"),
              "vars": "TX", "stns": "240", "fmt": "json"},
        timeout=120,
    )
    r.raise_for_status()
    return {d["date"][:10]: d["TX"] / 10 for d in r.json() if d.get("TX") is not None}


def water_mask(transform, width, height):
    """Water where most clear Landsat scenes flag water, averaged onto the 70 m grid."""
    water, clear = 0, 0
    for f in sorted(LANDSAT.glob("landsat_*.tif")):
        with rasterio.open(f) as src:
            m = src.read(2)
            w = np.zeros((height, width), "float32")
            reproject((m == 2).astype("float32"), w, src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=CRS, resampling=Resampling.average)
            c = np.zeros((height, width), "float32")
            reproject((m > 0).astype("float32"), c, src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=CRS, resampling=Resampling.average)
        water, clear = water + w, clear + c
    return water / np.maximum(clear, 1e-6) > 0.5


def warp(src_path, data, transform, width, height, resampling):
    with rasterio.open(src_path) as src:
        out = np.full((height, width), np.nan, "float32")
        reproject(data.astype("float32"), out, src_transform=src.transform, src_crs=src.crs,
                  src_nodata=np.nan, dst_transform=transform, dst_crs=CRS, dst_nodata=np.nan,
                  resampling=resampling)
    return out


def read_granule(base, transform, width, height, buffer):
    """LST in deg C on the RD grid, NaN where missing, cloudy or not good or nominal QC."""
    paths = {k: RAW / f"{base}_{k}.tif" for k in ("LST", "cloud", "QC")}
    if not all(p.exists() for p in paths.values()):
        return None
    with rasterio.open(paths["LST"]) as src:
        lst = src.read(1).astype("float32") * src.scales[0] + src.offsets[0]
    with rasterio.open(paths["cloud"]) as src:
        cloud = src.read(1)
    with rasterio.open(paths["QC"]) as src:
        qc = src.read(1)
    # QC bits 0 and 1: 00 best, 01 nominal, 10 cloud, 11 not produced
    cloudy = cloud == 1
    if buffer:
        cloudy = binary_dilation(cloudy, iterations=buffer)
    ok = np.isfinite(lst) & (lst > 200) & ~cloudy & ((qc & 0b11) <= 1)
    lst = np.where(ok, lst - 273.15, np.nan)
    out = warp(paths["LST"], lst, transform, width, height, Resampling.bilinear)
    keep = warp(paths["LST"], ok.astype("float32"), transform, width, height, Resampling.nearest)
    return np.where(keep == 1, out, np.nan)


def passes():
    """Group granules by orbit, keeping the latest build of each tile and scene."""
    meta = {d["id"]: d for d in json.loads((ROOT / "data" / "interim" /
                                            "ecostress_hot_overpasses.json").read_text())}
    latest = {}
    for f in sorted(RAW.glob("*_LST.tif")):
        m = NAME.match(f.name)
        orbit, scene, tile, _, _, build = m.groups()
        key = (orbit, scene, tile)
        if key not in latest or build > latest[key][1]:
            latest[key] = (f.name[:-8], build)
    groups = defaultdict(list)
    for (orbit, _, _), (base, _) in sorted(latest.items()):
        groups[orbit].append(base)
    return groups, meta


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--min-clear", type=float, default=0.7, help="min clear fraction of the box")
    p.add_argument("--buffer", type=int, default=2, help="cloud buffer in 70 m pixels")
    p.add_argument("--panels", type=int, default=12, help="passes shown in the figure")
    args = p.parse_args()

    transform, width, height = grid()
    inbox = box_mask(transform, width, height)
    water = water_mask(transform, width, height)
    groups, meta = passes()
    files = sum(len(list(RAW.glob(f"*_{k}.tif"))) for k in ("LST", "cloud", "QC"))
    print(f"{files} files, {len(groups)} passes (orbits)")
    tmax = schiphol_tmax("2018-06-01")
    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    for orbit, bases in sorted(groups.items(), key=lambda kv: NAME.match(kv[1][0]).group(4)):
        lst = np.full((height, width), np.nan, "float32")
        best, best_n = bases[0], -1
        for base in bases:
            g = read_granule(base, transform, width, height, args.buffer)
            if g is None:
                print(f"  missing layer for {base}")
                continue
            n = np.isfinite(g[inbox]).sum()
            if n > best_n:
                best, best_n = base, n
            lst = np.where(np.isnan(lst), g, lst)
        # date and time of the scene that covers most of the box
        date, local = meta[best]["day"], meta[best]["local_time"]
        clear = np.isfinite(lst)
        frac = (clear & inbox).sum() / inbox.sum()
        keep = frac >= args.min_clear
        print(f"{date} {local} orbit {orbit}  Tmax {tmax.get(date, np.nan):.1f}  "
              f"clear {frac:.2f}  {'keep' if keep else 'drop'}")
        if not keep:
            continue

        mask = np.where(clear, np.where(water, 2, 1), 0).astype("float32")
        hhmm = local.replace(":", "")
        path = OUT / f"ecostress_{date}_{hhmm}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=2,
                           dtype="float32", crs=CRS, transform=transform, nodata=np.nan,
                           compress="deflate") as dst:
            dst.write(lst, 1)
            dst.write(mask, 2)
            dst.set_band_description(1, "LST (deg C)")
            dst.set_band_description(2, "clear mask: 0 not clear, 1 clear land, 2 clear water")
            dst.update_tags(granules=",".join(bases), local_time=local, tmax_schiphol=tmax.get(date))
        land = (mask == 1) & inbox
        rows.append({"date": date, "overpass_local": local, "tmax_schiphol": tmax.get(date),
                     "clear_fraction": round(frac, 3),
                     "median_lst": round(float(np.median(lst[land])), 2),
                     "p90_lst": round(float(np.percentile(lst[land], 90)), 2),
                     "cold_fraction": round(float((lst[land] < tmax.get(date, np.nan) - 3).mean()), 3)})

    table = pd.DataFrame(rows)
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(TABLE, index=False)
    print(f"{len(table)} passes kept, table in {TABLE.relative_to(ROOT)}")
    if len(table):
        plot(table, args.panels)


def plot(table, n):
    """Hottest days first, afternoon passes (13 to 18 h) first, at most one pass per day."""
    t = table[(table["clear_fraction"] >= 0.9) & (table["cold_fraction"] < 0.1)]
    t = t.assign(afternoon=t["overpass_local"].between("13:00", "18:00"))
    t = t.sort_values(["afternoon", "clear_fraction"], ascending=False).drop_duplicates("date")
    t = t.sort_values(["afternoon", "tmax_schiphol"], ascending=False).head(n)
    t = t.sort_values(["date", "overpass_local"])
    ncol = min(4, len(t))
    nrow = int(np.ceil(len(t) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.6 * ncol, 2.9 * nrow + 0.6), squeeze=False)
    for ax in axes.flat:
        ax.set_axis_off()
    for ax, r in zip(axes.flat, t.itertuples()):
        with rasterio.open(OUT / f"ecostress_{r.date}_{r.overpass_local.replace(':', '')}.tif") as src:
            lst = src.read(1)
            b = src.bounds
        im = ax.imshow(lst, cmap="inferno", vmin=25, vmax=50,
                       extent=(b.left, b.right, b.bottom, b.top))
        ax.set_title(f"{r.date} {r.overpass_local}, Tmax {r.tmax_schiphol:.1f} C", fontsize=9)
    fig.subplots_adjust(left=0.01, right=0.88, top=0.95, bottom=0.06, wspace=0.03, hspace=0.12)
    cax = fig.add_axes([0.9, 0.2, 0.015, 0.6])
    fig.colorbar(im, cax=cax, label="land surface temperature (C)", extend="both")
    fig.text(0.01, 0.01, "ECOSTRESS LSTE v002 (NASA LP DAAC), KNMI", fontsize=8, color="0.4")
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE, dpi=150)
    print(f"figure in {FIGURE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
