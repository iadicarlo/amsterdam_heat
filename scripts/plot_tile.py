"""Quick look at shadow, Tmrt and UTCI for one hour of a SOLWEIG run.

    uv run python scripts/plot_tile.py --tile 121500_485000 --device mps --hour 15
"""

import argparse
from pathlib import Path

import matplotlib
import numpy as np
import rasterio

from amsterdam_heat.paths import output_dir

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
CREDIT = "AHN4, BAG (PDOK), KNMI Schiphol. Model: SOLWEIG-GPU"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--hour", type=int, default=15)
    ap.add_argument("--date", default="2019-07-25")
    ap.add_argument("--label", default=None, help="date as printed on the figure")
    ap.add_argument("--buffer", type=int, default=100, help="pixels cropped from each side")
    args = ap.parse_args()

    out = output_dir(args.tile, args.device, args.date)
    lc = rasterio.open(ROOT / "data" / "interim" / args.tile / "Landcover.tif").read(1)
    band = args.hour + 1  # band 1 is hour 0
    shadow = rasterio.open(out / "Shadow_0_0.tif").read(band)
    tmrt = rasterio.open(out / "TMRT_0_0.tif").read(band)
    utci = rasterio.open(out / "UTCI_0_0.tif").read(band)
    for a in (tmrt, utci):
        a[lc == 2] = np.nan

    b = slice(args.buffer, -args.buffer)
    panels = [
        (shadow, "Sunlit (1) or shaded (0)", "gray", (0, 1)),
        (tmrt, "Mean radiant temperature (°C)", "inferno", (20, 75)),
        (utci, "UTCI felt temperature (°C)", "RdYlBu_r", (26, 46)),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.2))
    for ax, (arr, title, cmap, (lo, hi)) in zip(axes, panels, strict=True):
        im = ax.imshow(arr[b, b], cmap=cmap, vmin=lo, vmax=hi)
        ax.set_title(title)
        ax.axis("off")
        fig.colorbar(im, ax=ax, shrink=0.75)
    fig.suptitle(f"Tile {args.tile}, {args.label or args.date} {args.hour:02d}:00 local time")
    fig.text(0.01, 0.01, CREDIT, fontsize=8, color="0.4")
    fig.tight_layout()
    path = ROOT / "figures" / f"{args.tile}_{args.device}_{args.date}_h{args.hour:02d}.png"
    fig.savefig(path, dpi=100)
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
