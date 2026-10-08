"""Street-level wind with the GLIDE-SOL scheme (Zonato et al. 2026, GMD).

GLIDE-SOL reduces the reference wind with direction-dependent coefficients
built from building and tree heights (upwind deceleration, leeward wakes,
exponential decay inside tree crowns) and is implemented in SOLWEIG-GPU
(``solweig_gpu.wind_ext_coeff``). Against 25 stations in Dortmund it cut the
wind RMSE from 2.6 to 0.8 m/s and the UTCI RMSE from 8.1 to 2.8 C.

GLIDE-SOL takes its reference wind from ERA5, whose roughness already reflects
the city. Our reference is the KNMI station at Schiphol (open terrain, z0 about
0.03 m), so as in the paper we first carry it to the city's mean roughness:
z0_city = f_b * 0.1 H_b + f_t * 0.1 H_t + f_o * 0.03, with the plan fractions
and mean heights of buildings, trees and open ground in the tile, through a
neutral log profile that matches at a 60 m blending height.
"""

import math
from pathlib import Path

import numpy as np
import rasterio

Z0_STATION = 0.03  # m, open grass
Z0_OPEN = 0.03  # m, open ground inside the city (GLIDE-SOL)
Z_REF = 10.0  # m
Z_BLEND = 60.0  # m


def write_building_heights(inputs: Path) -> Path:
    """Buildings.tif: building height above ground, 0 elsewhere (what GLIDE-SOL reads)."""
    with rasterio.open(inputs / "Building_DSM.tif") as src:
        dsm = src.read(1)
        profile = src.profile
    dem = rasterio.open(inputs / "DEM.tif").read(1)
    lc = rasterio.open(inputs / "Landcover.tif").read(1)
    heights = np.where(lc == 2, np.clip(dsm - dem, 0, None), 0.0).astype("float32")
    out = inputs / "Buildings.tif"
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(heights, 1)
    return out


def city_roughness(building_heights: np.ndarray, tree_heights: np.ndarray) -> float:
    bld = building_heights > 1.0
    tree = (tree_heights > 1.0) & ~bld
    fb, ft = bld.mean(), tree.mean()
    fo = 1.0 - fb - ft
    hb = building_heights[bld].mean() if bld.any() else 0.0
    ht = tree_heights[tree].mean() if tree.any() else 0.0
    return float(fb * 0.1 * hb + ft * 0.1 * ht + fo * Z0_OPEN)


def station_to_city(u10: np.ndarray, z0_city: float) -> np.ndarray:
    """10 m wind over open terrain to 10 m wind over the city's mean roughness."""
    up = math.log(Z_BLEND / Z0_STATION) / math.log(Z_REF / Z0_STATION)
    down = math.log(Z_REF / z0_city) / math.log(Z_BLEND / z0_city)
    return np.asarray(u10) * up * down


def build_coefficients(inputs: Path, out_dir: Path) -> tuple[float, list[Path]]:
    """Directional wind coefficient rasters (WindCoeff_dir000.tif ...) for a tile."""
    from solweig_gpu.wind_ext_coeff import _compute_wind_full_domain

    buildings = write_building_heights(inputs)
    hb = rasterio.open(buildings).read(1)
    ht = rasterio.open(inputs / "Trees.tif").read(1)
    z0 = city_roughness(hb, ht)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = _compute_wind_full_domain(
        building_fp=buildings, tree_fp=inputs / "Trees.tif", output_dir=out_dir, z0_ref=z0
    )
    return z0, paths

UMEP_HEADER = (
    "iy id it imin qn qh qe qs qf U RH Tair pres rain kdown snow ldown fcld wuh xsmd lai "
    "kdiff kdir wdir"
)
