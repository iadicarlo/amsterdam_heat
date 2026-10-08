"""Run SOLWEIG-GPU on one prepared tile.

    uv run python scripts/run_solweig.py --tile 121500_485000 --date 2019-07-25 --device mps

Outputs go to data/processed/<tile>/<device>/<date>/ so runs never share a cache.

Wind is reduced to street level with GLIDE-SOL's directional coefficients
(amsterdam_heat.windcoeff), after carrying the Schiphol wind to the city's mean
roughness. The met file actually used, with that wind, is kept in the run folder.
Use --station-wind to run with the raw station wind everywhere instead.

Everything that does not depend on the day (tiled rasters, wind coefficients,
walls, aspect, sky view factors) is built once in data/processed/<tile>/<device>/static/
and linked into each day's run. It is rebuilt when the tile inputs or the
SOLWEIG-GPU commit change, or with --fresh.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FORK = ROOT / "external" / "solweig-gpu"
STATIC_INPUTS = ("Building_DSM.tif", "DEM.tif", "Trees.tif", "Landcover.tif")


def static_key(inputs: Path, station_wind: bool) -> str:
    """Hash of the tile inputs and the fork commit: the static cache is valid while it holds."""
    h = hashlib.sha256()
    for name in STATIC_INPUTS:
        h.update((inputs / name).read_bytes())
    head = subprocess.run(["git", "-C", str(FORK), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    h.update(head.stdout.encode())
    h.update(b"station" if station_wind else b"glide-sol")
    return h.hexdigest()[:16]


def link_static(static_pre: Path, run_pre: Path, met_used: Path) -> None:
    """A day's processed_inputs: links to the static folders plus its own metfiles."""
    if run_pre.exists():
        shutil.rmtree(run_pre)
    run_pre.mkdir(parents=True)
    for sub in static_pre.iterdir():
        if sub.is_dir() and sub.name != "metfiles":
            (run_pre / sub.name).symlink_to(sub.resolve(), target_is_directory=True)
    metfiles = run_pre / "metfiles"
    metfiles.mkdir()
    for dsm in (static_pre / "Building_DSM").glob("Building_DSM_*.tif"):
        shutil.copy(met_used, metfiles / f"metfile_{dsm.stem.removeprefix('Building_DSM_')}.txt")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tile", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--device", choices=["mps", "cpu", "cuda"], default="mps")
    ap.add_argument("--fresh", action="store_true", help="delete earlier output and rebuild the static cache")
    ap.add_argument("--station-wind", action="store_true", help="no street-level wind reduction")
    args = ap.parse_args()

    # must be set before solweig_gpu picks its device
    os.environ["SOLWEIG_DEVICE"] = args.device
    from solweig_gpu.solweig_gpu import calculate_svf, preprocess, run_utci_tiles, run_walls_aspect

    from amsterdam_heat.paths import inputs_dir, run_dir
    from amsterdam_heat.windcoeff import UMEP_HEADER, build_coefficients, station_to_city

    inputs = inputs_dir(args.tile)
    out = run_dir(args.tile, args.device, args.date)
    static = run_dir(args.tile, args.device, "static")
    if args.fresh:
        for d in (out, static):
            if d.exists():
                shutil.rmtree(d)
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    key = static_key(inputs, args.station_wind)
    key_file = static / "key.json"
    cached = key_file.exists() and json.loads(key_file.read_text())["key"] == key

    met = np.loadtxt(inputs / f"met_{args.date}.txt", skiprows=1)
    windcoeff_folder = None
    info = {"device": args.device, "wind": "station"}
    if not args.station_wind:
        if cached:
            z0_city = json.loads(key_file.read_text())["z0_city"]
        else:
            z0_city, _ = build_coefficients(inputs, inputs / "windcoeff")
        met[:, 9] = station_to_city(met[:, 9], z0_city)
        windcoeff_folder = str(inputs / "windcoeff")
        info.update(wind="GLIDE-SOL coefficients", z0_city=round(z0_city, 3))
    met_used = out / f"met_{args.date}_used.txt"
    fmt = ["%d", "%d", "%d", "%d"] + ["%.3f"] * (met.shape[1] - 4)
    np.savetxt(met_used, met, fmt=fmt, header=UMEP_HEADER, comments="%")

    static_pre = static / "processed_inputs"
    if not cached:
        if static.exists():
            shutil.rmtree(static)
        static.mkdir(parents=True)
        preprocess(
            base_path=str(static),
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
            preprocess_dir=str(static_pre),
            use_uhi=False,
        )
        run_walls_aspect(str(static_pre))
        calculate_svf(str(static_pre), patch_option=2, overwrite=False)
        key_file.write_text(json.dumps({"key": key, "z0_city": info.get("z0_city")}))
    info["static_seconds"] = time.perf_counter() - t0
    info["static_cached"] = cached

    preprocess_dir = out / "processed_inputs"
    link_static(static_pre, preprocess_dir, met_used)
    run_utci_tiles(
        base_path=str(out),
        preprocess_dir=str(preprocess_dir),
        selected_date_str=args.date,
        tile_keys=None,
        save_tmrt=True,
        save_svf=True,
        save_shadow=True,
        save_wind=True,
    )
    info["seconds"] = time.perf_counter() - t0
    (out / "timing.json").write_text(json.dumps(info))
    state = "cached" if cached else "built"
    print(f"{args.device}: {info['seconds']:.1f} s, static {state} in {info['static_seconds']:.1f} s ({info['wind']})")


if __name__ == "__main__":
    main()
