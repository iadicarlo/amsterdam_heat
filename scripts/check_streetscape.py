"""Check planned trees against street furniture and street use from open data.

    uv run python scripts/check_streetscape.py --fetch osdorpplein de-aker

``--fetch`` downloads the layers for Nieuw-West to data/raw/streetscape first.
Writes data/processed/trees/<name>/streetscape.csv and prints conflicts per type.
"""

import argparse
from pathlib import Path

from amsterdam_heat import streetscape as ss
from amsterdam_heat.guidelines import read_vector


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    if args.fetch:
        ss.fetch_all()
    layers = ss.load_layers()
    for name, g in layers.items():
        print(f"{name:24s} {len(g):6d} objects")
    for name in args.names:
        folder = Path("data/processed/trees") / name
        res = ss.check_trees(read_vector(folder / "trees.geojson"), layers)
        res.to_csv(folder / "streetscape.csv", index=False)
        print(f"{name}: {len(res)} trees, {res.conflict.sum()} break at least one clearance")
        for k, d in ss.CLEARANCE.items():
            if k not in layers:
                continue
            col = res[f"d_{k}"]
            n = "" if d is None else f"{((col <= 0) if d == 0 else (col < d)).sum():3d}"
            print(f"  {k:24s} clearance {d!s:5s} m: {n:>3s}   median distance {col.median():.1f} m")


if __name__ == "__main__":
    main()
