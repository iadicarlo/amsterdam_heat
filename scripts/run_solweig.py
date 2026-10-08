"""Run SOLWEIG-GPU on one prepared tile.

    uv run python scripts/run_solweig.py --tile 121500_485000 --date 2019-07-25 --device mps

Outputs go to data/processed/<tile>/<device>/ so CPU and GPU runs never share a cache.
"""

import argparse
import json
import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--device", choices=["mps", "cpu", "cuda"], default="mps")
    ap.add_argument("--fresh", action="store_true", help="delete earlier output, including SVF cache")
    args = ap.parse_args()

    # must be set before solweig_gpu picks its device
    os.environ["SOLWEIG_DEVICE"] = args.device
    from solweig_gpu import thermal_comfort

    inputs = ROOT / "data" / "interim" / args.tile
    out = ROOT / "data" / "processed" / args.tile / args.device
    if args.fresh and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    thermal_comfort(
        base_path=str(out),
        selected_date_str=args.date,
        building_dsm_filename=str(inputs / "Building_DSM.tif"),
        dem_filename=str(inputs / "DEM.tif"),
        trees_filename=str(inputs / "Trees.tif"),
        landcover_filename=str(inputs / "Landcover.tif"),
        ERA_5_z0_find=False,
        tile_size=2000,
        overlap=20,
        use_own_met=True,
        own_met_file=str(inputs / f"met_{args.date}.txt"),
        use_uhi=False,
        save_tmrt=True,
        save_svf=True,
        save_shadow=True,
    )
    seconds = time.perf_counter() - t0
    (out / "timing.json").write_text(json.dumps({"device": args.device, "seconds": seconds}))
    print(f"{args.device}: {seconds:.1f} s")


if __name__ == "__main__":
    main()
