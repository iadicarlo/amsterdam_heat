"""Add PET (felt temperature, as in Amsterdam's guidelines) to a SOLWEIG run.

    uv run python scripts/compute_pet.py --tile 121500_485000 --date 2019-07-25 --device mps

Reads TMRT_0_0.tif, the met file the run used and the run's street-level wind
(Wind_0_0.tif, GLIDE-SOL), and writes PET_0_0.tif, one band per hour, next to the
other outputs. Use --station-wind to ignore the wind field.

If the afternoon heat island map exists (data/processed/uhi/dta_afternoon.tif, from
fit_uhi.py), its local air temperature excess over Schiphol is added for the
afternoon hours. Use --no-uhi to leave it out.
"""

import argparse
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from amsterdam_heat.paths import output_dir, run_dir
from amsterdam_heat.pet import pet_day

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--station-wind", action="store_true", help="use the station wind everywhere")
    ap.add_argument("--no-uhi", action="store_true", help="Schiphol air temperature everywhere")
    args = ap.parse_args()

    out_dir = output_dir(args.tile, args.device, args.date)
    met = np.loadtxt(ROOT / "data" / "interim" / args.tile / f"met_{args.date}.txt", skiprows=1)
    with rasterio.open(out_dir / "TMRT_0_0.tif") as src:
        tmrt = src.read().astype("float32")
        profile = src.profile
    t0 = time.perf_counter()
    wind10 = None
    wind_fp = out_dir / "Wind_0_0.tif"
    if wind_fp.exists() and not args.station_wind:
        wind10 = rasterio.open(wind_fp).read().astype("float32")
    met_used = run_dir(args.tile, args.device, args.date) / f"met_{args.date}_used.txt"
    if met_used.exists():
        met = np.loadtxt(met_used, skiprows=1)
    dta, air = None, "Schiphol"
    uhi = ROOT / "data" / "processed" / "uhi" / "dta_afternoon.tif"
    if uhi.exists() and wind10 is not None and not args.no_uhi:
        dta = np.zeros(tmrt.shape[1:], "float32")
        with rasterio.open(uhi) as src:
            reproject(rasterio.band(src, 1), dta, dst_transform=profile["transform"],
                      dst_crs=profile["crs"], resampling=Resampling.bilinear)
        air = "Schiphol plus afternoon heat island (fit_uhi.py)"
    pet = pet_day(tmrt, met, wind10=wind10, dta=dta)
    profile.update(dtype="float32", count=pet.shape[0], compress="deflate")
    with rasterio.open(out_dir / "PET_0_0.tif", "w", **profile) as dst:
        dst.write(pet)
        dst.update_tags(air_temperature=air)
    print(f"PET for {pet.shape[0]} hours in {time.perf_counter() - t0:.1f} s -> "
          f"{(out_dir / 'PET_0_0.tif').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
