"""Build a Landsat land surface temperature series over Amsterdam for hot summer days.

    uv run python scripts/fetch_landsat.py              # search, download windows, figure, table
    uv run python scripts/fetch_landsat.py --list       # search and cloud check only

Hot days are June to August days from 2013 on with a maximum of at least --tmax at KNMI
Schiphol (station 240). Scenes are Landsat 8 and 9 Collection 2 Level-2 from the Microsoft
Planetary Computer STAC. No account is needed: the planetary-computer package signs the
asset links. A scene is kept when cloud, cloud shadow, dilated cloud and cirrus cover less
than --max-cloud of the Amsterdam box, judged from QA_PIXEL.

Only the Amsterdam window is read. Each kept scene is warped to RD New (EPSG:28992) at
30 m on one fixed grid and saved to data/raw/satellite/landsat/landsat_<date>_<platform>.tif
with two bands: LST in deg C (NaN where not clear) and a clear mask (0 cloud, shadow or
fill, 1 clear land, 2 clear water).
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "satellite" / "landsat"
TABLE = ROOT / "data" / "interim" / "landsat_hot_days.csv"
FIGURE = ROOT / "figures" / "landsat_hot_days.png"
BBOX = (4.73, 52.28, 5.07, 52.43)  # lon min, lat min, lon max, lat max: Amsterdam
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
TZ = ZoneInfo("Europe/Amsterdam")
RES = 30.0
CRS = "EPSG:28992"

# QA_PIXEL bits, Collection 2
FILL, DILATED, CIRRUS, CLOUD, SHADOW, WATER = 0, 1, 2, 3, 4, 7


def grid():
    """Fixed 30 m RD New grid that covers the box, snapped to whole 30 m."""
    t = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    lon = np.linspace(BBOX[0], BBOX[2], 50)
    lat = np.linspace(BBOX[1], BBOX[3], 50)
    lo, la = np.meshgrid(lon, lat)
    x, y = t.transform(lo, la)
    x0, x1 = np.floor(x.min() / RES) * RES, np.ceil(x.max() / RES) * RES
    y0, y1 = np.floor(y.min() / RES) * RES, np.ceil(y.max() / RES) * RES
    width, height = int((x1 - x0) / RES), int((y1 - y0) / RES)
    return from_origin(x0, y1, RES, RES), width, height


def box_mask(transform, width, height):
    """True for grid cells inside the lon/lat box (the grid itself is a bit larger)."""
    t = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    cols, rows = np.meshgrid(np.arange(width) + 0.5, np.arange(height) + 0.5)
    x, y = transform * (cols, rows)
    lon, lat = t.transform(x, y)
    return (lon >= BBOX[0]) & (lon <= BBOX[2]) & (lat >= BBOX[1]) & (lat <= BBOX[3])


def hot_days(tmax: float) -> dict[str, float]:
    r = requests.post(
        "https://www.daggegevens.knmi.nl/klimatologie/daggegevens",
        data={"start": "20130101", "end": datetime.now(TZ).strftime("%Y%m%d"), "vars": "TX",
              "stns": "240", "fmt": "json"},
        timeout=120,
    )
    r.raise_for_status()
    return {d["date"][:10]: d["TX"] / 10 for d in r.json()
            if d.get("TX") is not None and d["TX"] >= tmax * 10
            and d["date"][5:7] in ("06", "07", "08")}


def search(days: list[str]) -> list:
    cat = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    items = []
    for year in sorted({d[:4] for d in days}):
        found = cat.search(
            collections=["landsat-c2-l2"], bbox=BBOX,
            datetime=f"{year}-06-01/{year}-08-31",
            query={"platform": {"in": ["landsat-8", "landsat-9"]}},
        ).item_collection()
        items += [it for it in found if it.datetime.strftime("%Y-%m-%d") in days]
    return sorted(items, key=lambda it: it.datetime)


def read(href, transform, width, height, resampling):
    with rasterio.open(href) as src, WarpedVRT(
        src, crs=CRS, transform=transform, width=width, height=height,
        resampling=resampling, nodata=src.nodata,
    ) as vrt:
        return vrt.read(1)


def bit(qa, b):
    return (qa >> b) & 1 == 1


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--tmax", type=float, default=27.0, help="hot day threshold at Schiphol, deg C")
    p.add_argument("--max-cloud", type=float, default=0.2, help="max cloud fraction over the box")
    p.add_argument("--min-cover", type=float, default=0.8,
                   help="min fraction of the box the scene must cover (drops scene edges)")
    p.add_argument("--list", action="store_true", help="search and cloud check only")
    p.add_argument("--panels", type=int, default=12, help="hottest scenes shown in the figure")
    args = p.parse_args()

    days = hot_days(args.tmax)
    items = search(list(days))
    print(f"{len(days)} hot days, {len(items)} Landsat 8/9 scenes on those days")

    transform, width, height = grid()
    inbox = box_mask(transform, width, height)
    OUT.mkdir(parents=True, exist_ok=True)
    env = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_MULTIPLEX": "YES",
               "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif", "VSI_CACHE": "TRUE"}

    rows = []
    with rasterio.Env(**env):
        for it in items:
            date = it.datetime.strftime("%Y-%m-%d")
            plat = it.properties["platform"]
            qa = read(it.assets["qa_pixel"].href, transform, width, height, Resampling.nearest)
            valid = ~bit(qa, FILL) & (qa != 0)
            cloudy = bit(qa, CLOUD) | bit(qa, SHADOW) | bit(qa, DILATED) | bit(qa, CIRRUS)
            cover = (valid & inbox).sum() / inbox.sum()
            cloud = (cloudy & valid & inbox).sum() / max((valid & inbox).sum(), 1)
            keep = cover >= args.min_cover and cloud < args.max_cloud
            local = it.datetime.astimezone(TZ).strftime("%H:%M")
            print(f"{date} {plat} {local}  Tmax {days[date]:.1f}  cover {cover:.2f}  "
                  f"cloud {cloud:.2f}  {'keep' if keep else 'drop'}")
            if not keep or args.list:
                continue

            dn = read(it.assets["lwir11"].href, transform, width, height,
                      Resampling.bilinear).astype("float32")
            lst = dn * 0.00341802 + 149.0 - 273.15
            clear = valid & ~cloudy & (dn > 0)
            mask = np.where(clear, np.where(bit(qa, WATER), 2, 1), 0).astype("float32")
            lst = np.where(clear, lst, np.nan).astype("float32")

            path = OUT / f"landsat_{date}_{plat}.tif"
            with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=2,
                               dtype="float32", crs=CRS, transform=transform, nodata=np.nan,
                               compress="deflate") as dst:
                dst.write(lst, 1)
                dst.write(mask, 2)
                dst.set_band_description(1, "LST (deg C)")
                dst.set_band_description(2, "clear mask: 0 not clear, 1 clear land, 2 clear water")
                dst.update_tags(scene=it.id, datetime=it.datetime.isoformat(), tmax_schiphol=days[date])
            land = clear & inbox & (mask == 1)
            rows.append({"date": date, "platform": plat, "overpass_local": local,
                         "tmax_schiphol": days[date],
                         "clear_fraction": round((clear & inbox).sum() / inbox.sum(), 3),
                         "median_lst": round(float(np.median(lst[land])), 2), "scene": it.id})

    if args.list:
        return

    table = pd.DataFrame(rows)
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    table.drop(columns="scene").to_csv(TABLE, index=False)
    (OUT / "SOURCE.json").write_text(json.dumps({
        "source": "Landsat 8 and 9 Collection 2 Level-2 (USGS), band ST_B10, via the Microsoft "
                  "Planetary Computer STAC, collection landsat-c2-l2",
        "stac": STAC,
        "licence": "USGS Landsat data: public domain, no restrictions",
        "hot_days": f"KNMI daily TX at Schiphol (240), June to August, TX >= {args.tmax} C, 2013 on",
        "selection": f"cloud, cloud shadow, dilated cloud and cirrus from QA_PIXEL under "
                     f"{args.max_cloud:.0%} of the box lon {BBOX[0]} to {BBOX[2]}, lat {BBOX[1]} "
                     f"to {BBOX[3]}; scene covers at least {args.min_cover:.0%} of the box",
        "processing": "ST_B10 * 0.00341802 + 149.0 K, minus 273.15; warped to EPSG:28992 at 30 m "
                      "(bilinear for LST, nearest for QA)",
        "bands": ["LST (deg C), NaN where not clear",
                  "clear mask: 0 cloud, shadow or fill, 1 clear land, 2 clear water"],
        "scenes": table["scene"].tolist() if len(table) else [],
        "fetched": datetime.now(UTC).strftime("%Y-%m-%d"),
    }, indent=2) + "\n")
    print(f"{len(table)} scenes kept, table in {TABLE.relative_to(ROOT)}")
    if len(table):
        plot(table.sort_values("tmax_schiphol", ascending=False).head(args.panels).sort_values("date"))


def plot(table):
    n = len(table)
    ncol = min(4, n)
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.6 * ncol, 2.9 * nrow + 0.6), squeeze=False)
    for ax in axes.flat:
        ax.set_axis_off()
    for ax, r in zip(axes.flat, table.itertuples()):
        with rasterio.open(OUT / f"landsat_{r.date}_{r.platform}.tif") as src:
            lst = src.read(1)
            b = src.bounds
        im = ax.imshow(lst, cmap="inferno", vmin=25, vmax=50,
                       extent=(b.left, b.right, b.bottom, b.top))
        ax.set_title(f"{r.date}, Tmax {r.tmax_schiphol:.1f} C", fontsize=9)
    fig.subplots_adjust(left=0.01, right=0.88, top=0.95, bottom=0.06, wspace=0.03, hspace=0.12)
    cax = fig.add_axes([0.9, 0.2, 0.015, 0.6])
    fig.colorbar(im, cax=cax, label="land surface temperature (C)", extend="both")
    fig.text(0.01, 0.01, "Landsat 8/9 Collection 2 (USGS), KNMI", fontsize=8, color="0.4")
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE, dpi=150)
    print(f"figure in {FIGURE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
