"""Compare a GPU (MPS, float32) run with the CPU reference run, hour by hour.

    uv run python scripts/compare_devices.py --tile 121500_485000

Only outdoor cells (not buildings) inside the tile, buffer removed, are compared.
Writes docs/validation_<tile>_mps_vs_cpu.md.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio

from amsterdam_heat.paths import output_dir, run_dir

ROOT = Path(__file__).resolve().parents[1]


def load(tile: str, device: str, name: str, date: str) -> np.ndarray:
    path = output_dir(tile, device, date) / f"{name}_0_0.tif"
    with rasterio.open(path) as src:
        return src.read().astype("float64")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--buffer", type=int, default=100)
    ap.add_argument("--date", default="2019-07-25")
    args = ap.parse_args()

    lc = rasterio.open(ROOT / "data" / "interim" / args.tile / "Landcover.tif").read(1)
    b = slice(args.buffer, -args.buffer)
    outdoor = (lc != 2)[b, b]

    lines = [
        f"# GPU (MPS, float32) against CPU reference, tile {args.tile}",
        "",
        "Outdoor cells only, 100 m buffer removed. Daylight hours with sun above the horizon.",
        "",
        (
            "| Hour | Tmrt mean abs diff (K) | Tmrt max abs diff (K) | UTCI mean abs diff (K) "
            "| UTCI max abs diff (K) | Shadow cells that differ (%) |"
        ),
        "|---|---|---|---|---|---|",
    ]
    tm = {d: load(args.tile, d, "TMRT", args.date) for d in ("mps", "cpu")}
    ut = {d: load(args.tile, d, "UTCI", args.date) for d in ("mps", "cpu")}
    sh = {d: load(args.tile, d, "Shadow", args.date) for d in ("mps", "cpu")}
    worst = 0.0
    for h in range(tm["cpu"].shape[0]):
        dt = np.abs(tm["mps"][h] - tm["cpu"][h])[b, b][outdoor]
        du = np.abs(ut["mps"][h] - ut["cpu"][h])[b, b][outdoor]
        ds = np.abs(sh["mps"][h] - sh["cpu"][h])[b, b][outdoor] > 0.01
        if sh["cpu"][h].max() == 0:
            continue
        worst = max(worst, np.nanmax(dt))
        lines.append(
            f"| {h:02d} | {np.nanmean(dt):.4f} | {np.nanmax(dt):.3f} | {np.nanmean(du):.4f} "
            f"| {np.nanmax(du):.3f} | {100 * ds.mean():.3f} |"
        )
    t = {d: json.loads((run_dir(args.tile, d, args.date) / "timing.json").read_text())
         for d in ("mps", "cpu")}
    lines += [
        "",
        (
            "Wall time for a fresh run (sky view factor plus 24 hours): "
            f"MPS {t['mps']['seconds'] / 60:.1f} min, CPU {t['cpu']['seconds'] / 60:.1f} min."
        ),
        f"Largest Tmrt difference in any outdoor cell and hour: {worst:.3f} K.",
    ]
    out = ROOT / "docs" / f"validation_{args.tile}_mps_vs_cpu.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
