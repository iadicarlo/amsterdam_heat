"""Heat and shade per neighbourhood (buurt) for a stitched district run, with CBS figures.

    uv run python scripts/district_stats.py --district nieuw-west --date 2015-07-01

Needs make_map.py to have stitched the district. For each buurt, over outdoor land
(not buildings, not water): mean afternoon PET, the share above 41 C (extreme heat
stress), the share in shade at 15:00, and the shade at 15:00 along the pedestrian
PLUS and HOOFD routes (a 5 m wide band). Residents and the share aged 65 and over
come from CBS Kerncijfers wijken en buurten 2024 (table 85984NED). Writes
buurt_stats.csv next to the stitched rasters.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from rasterio.features import rasterize

from amsterdam_heat.guidelines import read_vector

ROOT = Path(__file__).resolve().parents[1]
CBS_TABLE = "85984NED"
EXTREME_PET = 41.0  # C, lower bound of extreme heat stress (Matzarakis and Mayer 1996)


def cbs_buurten(out: Path) -> pd.DataFrame:
    if not out.exists():
        url = f"https://opendata.cbs.nl/ODataApi/odata/{CBS_TABLE}/TypedDataSet"
        params = {"$filter": "startswith(WijkenEnBuurten,'BU0363')",
                  "$select": "WijkenEnBuurten,AantalInwoners_5,k_65JaarOfOuder_12"}
        r = requests.get(url, params=params, timeout=120)
        r.raise_for_status()
        out.write_text(json.dumps({"source": url, "table": CBS_TABLE, "licence": "CC BY 4.0",
                                   "value": r.json()["value"]}))
    df = pd.DataFrame(json.loads(out.read_text())["value"])
    df["cbs_code"] = df["WijkenEnBuurten"].str.strip()
    return df.rename(columns={"AantalInwoners_5": "residents", "k_65JaarOfOuder_12": "aged_65_plus"})[
        ["cbs_code", "residents", "aged_65_plus"]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--district", required=True)
    ap.add_argument("--date", required=True)
    args = ap.parse_args()

    d = ROOT / "data" / "processed" / "districts" / f"{args.district}_{args.date}"
    city = ROOT / "data" / "raw" / "city"
    with rasterio.open(d / "pet_afternoon.tif") as src:
        pet = src.read(1)
        transform, shape = src.transform, src.shape
    shade = rasterio.open(d / "shade_15h.tif").read(1)
    outdoor = ~np.isnan(pet)

    district = read_vector(city / "stadsdelen.geojson")
    area = district[district["naam"].str.lower() == args.district].union_all()
    buurten = read_vector(city / f"buurten_{args.district}.geojson")
    buurten = buurten[buurten.representative_point().within(area)].reset_index(drop=True)
    ids = rasterize(((g, i + 1) for i, g in enumerate(buurten.geometry)), out_shape=shape,
                    transform=transform, fill=0, dtype="int32")
    routes = read_vector(city / "ams_plushoofdnetten.geojson")
    routes = routes[routes["VOET"].isin(["PLUS", "HOOFD"])]
    on_route = rasterize(((g, 1) for g in routes.buffer(2.5).geometry), out_shape=shape,
                         transform=transform, fill=0, dtype="uint8").astype(bool) & outdoor

    rows = []
    for i, b in buurten.iterrows():
        m = (ids == i + 1) & outdoor
        r = (ids == i + 1) & on_route
        rows.append({
            "code": b["code"], "naam": b["naam"], "cbs_code": b["cbs_code"],
            "outdoor_ha": m.sum() / 1e4,
            "pet_mean": float(np.mean(pet[m])) if m.any() else np.nan,
            "extreme_share": float(np.mean(pet[m] > EXTREME_PET)) if m.any() else np.nan,
            "shade_15h": float(np.mean(shade[m])) if m.any() else np.nan,
            "route_m2": int(r.sum()),
            "route_shade_15h": float(np.mean(shade[r])) if r.sum() > 200 else np.nan,
        })
    stats = pd.DataFrame(rows).merge(cbs_buurten(city / "cbs_kwb2024_amsterdam.json"), on="cbs_code", how="left")
    stats.to_csv(d / "buurt_stats.csv", index=False)
    lived = stats[stats["residents"].fillna(0) >= 100].sort_values("pet_mean", ascending=False)
    print(lived[["code", "naam", "residents", "aged_65_plus", "pet_mean", "extreme_share", "shade_15h",
                 "route_shade_15h"]].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
