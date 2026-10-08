"""Check planned trees against open cables and pipes data.

    uv run python scripts/check_utilities.py osdorpplein de-aker

Writes data/processed/trees/<name>/utilities.csv and prints conflicts per type, at
the default clearances and at 2.5 m for every type (Stedin advice).
"""

import argparse
from pathlib import Path

from amsterdam_heat import utilities as ut
from amsterdam_heat.guidelines import read_vector


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    args = ap.parse_args()
    layers = ut.load_layers()
    strict = {k: 2.5 for k in ut.CLEARANCE} | {"gas_transmission": 5.0}
    for name in args.names:
        folder = Path("data/processed/trees") / name
        trees = read_vector(folder / "trees.geojson")
        res = ut.check_trees(trees, layers)
        res.to_csv(folder / "utilities.csv", index=False)
        hard = ut.check_trees(trees, layers, strict)
        print(f"{name}: {len(res)} trees, {res.conflict.sum()} within default clearance, "
              f"{hard.conflict.sum()} within 2.5 m")
        for k, d in ut.CLEARANCE.items():
            col = res[f"d_{k}"]
            print(f"  {k:19s} clearance {d:.1f} m: {(col < d).sum():3d}   "
                  f"within 2.5 m: {(col < 2.5).sum():3d}   median distance {col.median():.1f} m")


if __name__ == "__main__":
    main()
