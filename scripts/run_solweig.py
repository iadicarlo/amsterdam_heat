"""Run SOLWEIG-GPU on one prepared tile.

    uv run python scripts/run_solweig.py --tile 121500_485000 --date 2019-07-25 --device mps

Outputs go to data/processed/<tile>/<device>/<date>/ so runs never share a cache.

Wind is reduced to street level with GLIDE-SOL's directional coefficients
(amsterdam_heat.windcoeff), after carrying the Schiphol wind to the city's mean
roughness. The met file actually used, with that wind, is kept in the run folder.
Use --station-wind to run with the raw station wind everywhere instead.
"""

import argparse
import json
import os
import shutil
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--device", choices=["mps", "cpu", "cuda"], default="mps")
    ap.add_argument("--fresh", action="store_true", help="delete earlier output, including SVF cache")
    ap.add_argument("--station-wind", action="store_true", help="no street-level wind reduction")
    args = ap.parse_args()

    # must be set before solweig_gpu picks its device
    os.environ["SOLWEIG_DEVICE"] = args.device
    from solweig_gpu.solweig_gpu import calculate_svf, preprocess, run_utci_tiles, run_walls_aspect

    from amsterdam_heat.paths import inputs_dir, run_dir
    from amsterdam_heat.windcoeff import UMEP_HEADER, build_coefficients, station_to_city

    inputs = inputs_dir(args.tile)
    out = run_dir(args.tile, args.device, args.date)
    if args.fresh and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    met = np.loadtxt(inputs / f"met_{args.date}.txt", skiprows=1)
    windcoeff_folder = None
    info = {"device": args.device, "wind": "station"}
    if not args.station_wind:
        z0_city, _ = build_coefficients(inputs, inputs / "windcoeff")
        met[:, 9] = station_to_city(met[:, 9], z0_city)
        windcoeff_folder = str(inputs / "windcoeff")
        info.update(wind="GLIDE-SOL coefficients", z0_city=round(z0_city, 3))
    met_used = out / f"met_{args.date}_used.txt"
    fmt = ["%d", "%d", "%d", "%d"] + ["%.3f"] * (met.shape[1] - 4)
    np.savetxt(met_used, met, fmt=fmt, header=UMEP_HEADER, comments="%")

    t0 = time.perf_counter()
    preprocess_dir = preprocess(
        base_path=str(out),
        selected_date_str=args.date,
        building_dsm_filename=str(inputs / "Building_DSM.tif"),
        dem_filename=str(inputs / "DEM.tif"),
        trees_filename=str(inputs / "Trees.tif"),
        landcover_filename=str(inputs / "Landcover.tif"),
        windcoeff_folder=windcoeff_folder,
        tile_size=2000,
        overlap=20,
        use_own_met=True,
        own_met_file=str(met_used),
        use_uhi=False,
    )
    run_walls_aspect(preprocess_dir)
    calculate_svf(preprocess_dir, patch_option=2, overwrite=False)
    run_utci_tiles(
        base_path=str(out),
        preprocess_dir=preprocess_dir,
        selected_date_str=args.date,
        tile_keys=None,
        save_tmrt=True,
        save_svf=True,
        save_shadow=True,
        save_wind=True,
    )
    info["seconds"] = time.perf_counter() - t0
    (out / "timing.json").write_text(json.dumps(info))
    print(f"{args.device}: {info['seconds']:.1f} s ({info['wind']})")


if __name__ == "__main__":
    main()
