"""Check SOLWEIG-GPU geometry against UMEP's own SOLWEIG code (numpy, float64).

Compares the sky view factors and the hourly building and vegetation shadows,
which use the same algorithms in both models. Full Tmrt is not compared here:
UMEP is at SOLWEIG 2025a/2026a and SOLWEIG-GPU at 2022a, so differences there
would mix model versions with implementation errors.

UMEP is used straight from its repository, without QGIS:

    git clone --depth 1 https://github.com/UMEP-dev/UMEP-processing.git ~/src/UMEP-processing
    uv run python scripts/compare_umep.py --tile 121500_485000 --umep ~/src/UMEP-processing

Writes docs/validation_<tile>_umep.md.
"""

import argparse
import shutil
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import rasterio

from amsterdam_heat.paths import run_dir

ROOT = Path(__file__).resolve().parents[1]


class _Feedback:
    """Stand-in for the QGIS feedback object UMEP expects (method names are UMEP's)."""

    def isCanceled(self):
        return False

    def setProgress(self, *_):
        pass

    def setProgressText(self, *_):
        pass

    def pushInfo(self, *_):
        pass


def import_umep(umep_repo: Path):
    """Copy UMEP's numpy code into a cache package with QGIS-free __init__ files."""
    cache = ROOT / "data" / "interim" / "_umepcore"
    if not cache.exists():
        (cache / "umepcore").mkdir(parents=True)
        for sub in ("functions", "util"):
            shutil.copytree(umep_repo / sub, cache / "umepcore" / sub)
        for init in ("__init__.py", "functions/__init__.py", "util/__init__.py"):
            (cache / "umepcore" / init).write_text("")
    sys.path.insert(0, str(cache))
    from umepcore.functions import svf_functions
    from umepcore.util.SEBESOLWEIGCommonFiles.shadowingfunction_wallheight_23 import (
        shadowingfunction_wallheight_23,
    )

    return svf_functions, shadowingfunction_wallheight_23


def read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1).astype("float64")


def stats(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> tuple[float, float, float]:
    d = np.abs(a - b)[mask]
    return float(d.mean()), float(np.percentile(d, 99)), float(d.max())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--umep", type=Path, required=True, help="path to a UMEP-processing clone")
    ap.add_argument("--device", default="mps", help="which SOLWEIG-GPU run to compare")
    ap.add_argument("--buffer", type=int, default=100)
    ap.add_argument("--date", default="2019-07-25", help="which run to take walls and SVF from")
    args = ap.parse_args()

    svf_functions, wallheight_23 = import_umep(args.umep.expanduser())

    inputs = ROOT / "data" / "interim" / args.tile
    run = run_dir(args.tile, args.device, args.date) / "processed_inputs"
    dsm = read(inputs / "Building_DSM.tif")
    trees = read(inputs / "Trees.tif")
    lc = read(inputs / "Landcover.tif")
    walls = read(run / "walls" / "walls_0_0.tif")
    aspect = read(run / "aspect" / "aspect_0_0.tif")
    b = slice(args.buffer, -args.buffer)
    inner = np.zeros_like(dsm, dtype=bool)
    inner[b, b] = True
    ground = inner & (lc != 2)

    lines = [
        f"# SOLWEIG-GPU ({args.device}) against UMEP SOLWEIG code (numpy, float64), tile {args.tile}",
        "",
        "Same inputs, outdoor cells inside the tile, buffer removed.",
        "",
    ]

    # sky view factors
    t0 = time.perf_counter()
    umep_svf = svf_functions.svfForProcessing153(
        dsm, trees.copy(), trees * 0.25, 1.0, 1, 1.0, 0, None, _Feedback()
    )
    t_umep = time.perf_counter() - t0
    with zipfile.ZipFile(run / "SVF" / "svfs_0_0.zip") as z:
        tmp = ROOT / "data" / "interim" / "_svf_unzip"
        z.extractall(tmp)
    lines += [
        "## Sky view factor (153 patches)",
        "",
        f"UMEP numpy run on CPU took {t_umep / 60:.1f} min.",
        "",
        "| Layer | mean abs diff | 99th percentile | max |",
        "|---|---|---|---|",
    ]
    for name in ("svf", "svfveg", "svfaveg", "svfE", "svfS", "svfW", "svfN"):
        ours = read(tmp / f"{name}.tif")
        mean, p99, mx = stats(ours, umep_svf[name], ground)
        lines.append(f"| {name} | {mean:.5f} | {p99:.4f} | {mx:.4f} |")
    shutil.rmtree(tmp)

    # hourly shadows at a few sun positions
    import os

    os.environ["SOLWEIG_DEVICE"] = args.device
    import torch
    from solweig_gpu.solweig import shadowingfunction_wallheight_23 as gpu_wh23

    dev = torch.device(args.device)
    veg = trees + dsm
    veg[veg == dsm] = 0
    veg2 = trees * 0.25 + dsm
    veg2[veg2 == dsm] = 0
    bush = np.logical_not(veg2 * veg) * veg
    amax = max(dsm.max(), veg.max())
    t = {k: torch.tensor(v, dtype=torch.float32, device=dev) for k, v in
         {"a": dsm, "veg": veg, "veg2": veg2, "bush": bush, "walls": walls, "aspect": aspect}.items()}
    lines += [
        "",
        "## Shadows (building and vegetation), sun positions over a July day",
        "",
        (
            "| Azimuth | Altitude | Building shadow cells that differ (%) "
            "| Vegetation shadow mean abs diff |"
        ),
        "|---|---|---|---|",
    ]
    for az, alt in [(80.0, 15.0), (120.0, 40.0), (180.0, 58.0), (240.0, 42.0), (285.0, 12.0)]:
        u_veg, u_sh, *_ = wallheight_23(
            dsm, veg, veg2, az, alt, 1.0, amax, bush, walls, aspect * np.pi / 180.0
        )
        g_veg, g_sh, *_ = gpu_wh23(
            t["a"], t["veg"], t["veg2"], az, alt, 1.0, amax, t["bush"], t["walls"],
            t["aspect"] * np.pi / 180.0,
        )
        g_veg, g_sh = g_veg.cpu().numpy(), g_sh.cpu().numpy()
        differ = 100 * np.mean((np.abs(u_sh - g_sh) > 0.5)[ground])
        vdiff = float(np.mean(np.abs(u_veg - g_veg)[ground]))
        lines.append(f"| {az:.0f} | {alt:.0f} | {differ:.3f} | {vdiff:.4f} |")

    out = ROOT / "docs" / f"validation_{args.tile}_umep.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
