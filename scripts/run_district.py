"""Build and run every tile of a city district for one day, resuming where it stopped.

    uv run python scripts/run_district.py --district nieuw-west --date 2015-07-01

Tiles come from data/raw/city/tiles_<district>.json (500 m grid over the
Gemeente's stadsdeel boundary). Each tile goes through make_tile.py,
run_solweig.py and compute_pet.py; a tile that already has PET is skipped.
Failures are logged and the run moves on. Progress goes to
data/processed/districts/<district>_<date>.log.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(args: list[str], log) -> bool:
    r = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        log.write(f"  failed: {' '.join(args)}\n{r.stderr[-2000:]}\n")
    return r.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--district", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--limit", type=int, help="only the first N tiles, for testing")
    args = ap.parse_args()

    from amsterdam_heat.paths import output_dir

    tiles = json.loads((ROOT / "data" / "raw" / "city" / f"tiles_{args.district}.json").read_text())
    tiles = tiles[: args.limit] if args.limit else tiles
    log_path = ROOT / "data" / "processed" / "districts" / f"{args.district}_{args.date}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", buffering=1) as log:
        for i, (x, y) in enumerate(tiles, 1):
            name = f"{x}_{y}"
            if (output_dir(name, args.device, args.date) / "PET_0_0.tif").exists():
                continue
            t0 = time.perf_counter()
            ok = (
                step(["scripts/make_tile.py", "--x", str(x), "--y", str(y), "--date", args.date], log)
                and step(["scripts/run_solweig.py", "--tile", name, "--date", args.date,
                          "--device", args.device], log)
                and step(["scripts/compute_pet.py", "--tile", name, "--date", args.date], log)
            )
            state = "ok" if ok else "FAILED"
            log.write(f"{i}/{len(tiles)} {name} {state} {time.perf_counter() - t0:.0f} s\n")


if __name__ == "__main__":
    main()
