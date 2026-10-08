"""Is the sun bias against the HvA globes a sphere versus standing person effect?

    uv run python scripts/posture_test.py

Reruns the hourly part of SOLWEIG for every HvA validation tile and day with the
angular factors of a sphere-like body (1/6 for each of the six directions, 0.2 for
the direct beam on the cylinder, UMEP's sitting values, at the standing height of
1.1 m) and compares sunlit Tmrt with the globe for both bodies, against sun
altitude. A gap that grows with sun height and closes with the sphere points at
the reference, not the model. Writes docs/posture_test.md and
figures/posture_test.png. Needs validate_hva.py to have run.
"""

import math
import os
import sys

import matplotlib
import numpy as np
import pandas as pd

from amsterdam_heat.paths import ROOT, run_dir

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DEVICE = "mps"
SPHERE = {"Fside": 1 / 6, "Fup": 1 / 6, "Fcyl": 0.2}


def sun_altitude(date: str, hour_end: int, lat=52.37, lon=4.89) -> float:
    """Sun altitude (degrees) at the middle of the local hour ending at hour_end (CEST)."""
    t = pd.Timestamp(f"{date} 00:00") + pd.Timedelta(hours=hour_end - 0.5 - 2)
    g = 2 * math.pi / 365 * (t.dayofyear - 1 + (t.hour + t.minute / 60 - 12) / 24)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
           + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    ha = math.radians(((t.hour * 60 + t.minute) + eq + 4 * lon) / 4 - 180)
    la = math.radians(lat)
    return math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))


def run_sphere(tile: str, date: str) -> None:
    from solweig_gpu import utci_process
    from solweig_gpu.solweig_gpu import run_utci_tiles

    out = run_dir(tile, DEVICE, f"{date}_sphere")
    if (out / "output_folder" / "0_0" / "TMRT_0_0.tif").exists():
        return
    for k, v in SPHERE.items():
        setattr(utci_process, k, v)
    std = run_dir(tile, DEVICE, date)
    out.mkdir(parents=True, exist_ok=True)
    run_utci_tiles(base_path=str(out), preprocess_dir=str(std / "processed_inputs"),
                   selected_date_str=date, tile_keys=None, save_tmrt=True, save_shadow=True)
    pet = out / "output_folder" / "0_0" / "PET_0_0.tif"
    if not pet.exists():
        pet.symlink_to(std / "output_folder" / "0_0" / "PET_0_0.tif")


def main() -> None:
    os.environ["SOLWEIG_DEVICE"] = DEVICE
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_hva import model_at_site

    obs = pd.read_csv(ROOT / "data" / "processed" / "validation_hva.csv")
    obs = obs.dropna(subset=["tmrt_model"])
    for tile, date in obs[["tile", "date"]].drop_duplicates().itertuples(index=False):
        run_sphere(tile, date)
    obs["tmrt_sphere"] = [model_at_site(r.tile, f"{r.date}_sphere", r.x, r.y, int(r.hour), r.situation)[0]
                          for r in obs.itertuples()]
    obs["sun_alt"] = [sun_altitude(r.date, int(r.hour)) for r in obs.itertuples()]
    obs.to_csv(ROOT / "data" / "processed" / "posture_test.csv", index=False)

    lines = ["# Sphere or standing person", "",
             ("Model Tmrt minus globe Tmrt (K) for the HvA site-hours, with SOLWEIG's standing "
              "person and with a sphere-like body (equal weights in all six directions)."), "",
             "| Situation | n | Standing bias | Sphere bias | Standing RMSE | Sphere RMSE |",
             "|---|---|---|---|---|---|"]
    for sit, g in obs.groupby("situation"):
        d0, d1 = g.tmrt_model - g.tmrt, g.tmrt_sphere - g.tmrt
        lines.append(f"| {sit} | {len(g)} | {d0.mean():+.1f} | {d1.mean():+.1f} | "
                     f"{np.sqrt((d0**2).mean()):.1f} | {np.sqrt((d1**2).mean()):.1f} |")
    sun = obs[obs.situation == "sun"]
    lines += ["", "Sunlit hours by sun altitude:", "",
              "| Sun altitude | n | Standing bias | Sphere bias |", "|---|---|---|---|"]
    for lo, hi in ((0, 45), (45, 55), (55, 70)):
        g = sun[(sun.sun_alt >= lo) & (sun.sun_alt < hi)]
        if len(g):
            lines.append(f"| {lo} to {hi} degrees | {len(g)} | {(g.tmrt_model - g.tmrt).mean():+.1f} | "
                         f"{(g.tmrt_sphere - g.tmrt).mean():+.1f} |")
    (ROOT / "docs" / "posture_test.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)
    ax.scatter(sun.sun_alt, sun.tmrt_model - sun.tmrt, label="standing person", s=18)
    ax.scatter(sun.sun_alt, sun.tmrt_sphere - sun.tmrt, label="sphere", s=18, marker="^")
    ax.axhline(0, color="0.5", lw=0.8)
    ax.set_xlabel("sun altitude (degrees)")
    ax.set_ylabel("model minus globe Tmrt (K)")
    ax.set_title("Sunlit HvA site-hours")
    ax.legend()
    fig.savefig(ROOT / "figures" / "posture_test.png", dpi=130)


if __name__ == "__main__":
    main()
