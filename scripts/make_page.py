"""Self-contained web page for a district run: map, neighbourhood table, notes.

    uv run python scripts/make_page.py --district nieuw-west --date 2015-07-01

Needs make_map.py and district_stats.py to have run. The page loads Leaflet from
cdnjs and carries everything else inline (overlays as PNG data, outlines as
GeoJSON), so it can be published as is. Writes
data/processed/districts/<district>_<date>/page/index.html.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from matplotlib import colormaps

from amsterdam_heat.guidelines import read_vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from make_map import PET_RANGE, to_png

TEMPLATE = ROOT / "scripts" / "templates" / "district_page.html"
LEAFLET_CSS = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--district", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--title", default="Nieuw-West Heat Map")
    args = ap.parse_args()

    d = ROOT / "data" / "processed" / "districts" / f"{args.district}_{args.date}"
    city = ROOT / "data" / "raw" / "city"
    page = d / "page"
    page.mkdir(exist_ok=True)

    with rasterio.open(d / "pet_afternoon.tif") as src:
        pet, transform = src.read(1), src.transform
    shade = rasterio.open(d / "shade_15h.tif").read(1)
    shade = np.where(np.isnan(pet), np.nan, shade)
    b_pet = to_png(pet, transform, page / "pet.png", "magma", *PET_RANGE)
    b_shade = to_png(shade, transform, page / "shade.png", "Greys", -0.3, 1.3)

    stats = pd.read_csv(d / "buurt_stats.csv")
    district = read_vector(city / "stadsdelen.geojson")
    area = district[district["naam"].str.lower() == args.district].union_all()
    buurten = read_vector(city / f"buurten_{args.district}.geojson")
    buurten = buurten[buurten.representative_point().within(area)][["code", "geometry"]]
    buurten = buurten.merge(stats, on="code")
    buurten["geometry"] = buurten.geometry.simplify(4)
    cols = ["code", "naam", "residents", "aged_65_plus", "pet_mean", "extreme_share", "shade_15h",
            "walk_shade_15h", "homes_near_cool", "homes_near_park"]
    gj = json.loads(buurten[[*cols, "geometry"]].to_crs(4326).round(4).to_json())
    routes = read_vector(city / "ams_plushoofdnetten.geojson")
    routes = routes[routes["VOET"].isin(["PLUS", "HOOFD"])].clip(area)
    routes["geometry"] = routes.geometry.simplify(3)
    rj = json.loads(routes[["VOET", "geometry"]].to_crs(4326).to_json())

    lived = stats[stats["residents"] >= 100]
    hot = lived[lived["extreme_share"] > 0.5]
    summary = {
        "pet_mean": float(np.nanmean(pet)),
        "hot_buurten": len(hot), "hot_residents": int(hot["residents"].sum()),
        "hot_aged": int(hot["aged_65_plus"].sum()),
        "buurten": len(lived), "residents": int(lived["residents"].sum()),
    }
    ramp = [colormaps["magma"](x) for x in np.linspace(0, 1, 9)]
    gradient = ", ".join(f"rgb({r * 255:.0f} {g * 255:.0f} {b * 255:.0f})" for r, g, b, _ in ramp)

    import requests

    html = TEMPLATE.read_text()
    for key, value in {
        "__TITLE__": args.title,
        "__LEAFLET_CSS__": requests.get(LEAFLET_CSS, timeout=60).text,
        "__DATA__": json.dumps({
            "date": args.date, "summary": summary, "range": PET_RANGE, "buurten": gj, "routes": rj,
            "overlays": {"pet": {"src": data_uri(page / "pet.png"), "bounds": b_pet},
                         "shade": {"src": data_uri(page / "shade.png"), "bounds": b_shade}},
        }),
        "__GRADIENT__": gradient,
    }.items():
        html = html.replace(key, value)
    (page / "index.html").write_text(html)
    size = (page / "index.html").stat().st_size / 1e6
    print(f"wrote {(page / 'index.html').relative_to(ROOT)} ({size:.1f} MB)")
    print(summary)


if __name__ == "__main__":
    main()
