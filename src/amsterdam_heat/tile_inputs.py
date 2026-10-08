"""Turn AHN4, BAG footprints and the CIR aerial photo into SOLWEIG input rasters.

Outputs on one common 1 m grid in EPSG:28992:

- Building_DSM.tif  terrain plus buildings (m above NAP + ELEVATION_OFFSET)
- DEM.tif           bare terrain (m above NAP + ELEVATION_OFFSET)
- Trees.tif         vegetation height above ground (m), 0 where no tree
- Landcover.tif     UMEP classes: 1 paved, 2 building, 5 grass, 7 water

Trees are taken from the AHN surface height outside building footprints. Thin
objects (lamp posts, signs) and slivers along facades are removed with a size
filter and a one pixel buffer around footprints.

The national aerial photos are flown in early spring, when deciduous trees are
bare, so NDVI from them misses most street trees. NDVI is only used here to mark
grass. Summer canopy needs another source (tree register, summer imagery or a
canopy height model).

Elevations are lifted by ELEVATION_OFFSET. SOLWEIG, like UMEP, uses 0 in the
vegetation surface to mean "no tree", so ground below 0 m (most of Amsterdam
is below NAP) sees phantom vegetation above it and is wrongly shaded. A
constant offset leaves shadows and radiation unchanged and removes the problem.
"""

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.fill import fillnodata
from rasterio.transform import from_origin
from scipy.ndimage import binary_dilation, label

CRS = "EPSG:28992"
ELEVATION_OFFSET = 20.0  # m, keeps every surface above 0


@dataclass
class TileSpec:
    xmin: float
    ymin: float
    size: float = 500.0
    buffer: float = 100.0
    res: float = 1.0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        b = self.buffer
        return (self.xmin - b, self.ymin - b, self.xmin + self.size + b, self.ymin + self.size + b)

    @property
    def shape(self) -> tuple[int, int]:
        n = round((self.size + 2 * self.buffer) / self.res)
        return n, n

    @property
    def transform(self):
        xmin, _, _, ymax = self.bbox
        return from_origin(xmin, ymax, self.res, self.res)

    @property
    def name(self) -> str:
        return f"{int(self.xmin)}_{int(self.ymin)}"


def _block(a: np.ndarray, k: int, how: str) -> np.ndarray:
    """Aggregate k x k blocks, ignoring NaN."""
    h, w = a.shape[0] // k * k, a.shape[1] // k * k
    b = a[:h, :w].reshape(h // k, k, w // k, k)
    return getattr(np, f"nan{how}")(b, axis=(1, 3))


def _read(path: Path, spec: TileSpec, band: int | None = 1) -> np.ndarray:
    with rasterio.open(path) as src:
        a = src.read(band).astype("float32") if band else src.read().astype("float32")
        if src.nodata is not None:
            a[a == src.nodata] = np.nan
        a[np.abs(a) > 1e30] = np.nan
    return a


def build(
    spec: TileSpec,
    dsm_path: Path,
    dtm_path: Path,
    bag_path: Path,
    cir_path: Path,
    out_dir: Path,
    min_tree_height: float = 2.5,
    min_ndvi: float = 0.15,
    min_tree_area: float = 4.0,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    src_res = 0.5
    k = round(spec.res / src_res)

    dsm05 = _read(dsm_path, spec)
    dtm05 = _read(dtm_path, spec)
    water05 = np.isnan(dsm05) & np.isnan(dtm05)  # AHN leaves open water empty

    # bare earth: AHN4 DTM has holes under buildings and water, fill them
    dtm05 = fillnodata(dtm05, mask=~np.isnan(dtm05), max_search_distance=200)
    dsm05 = np.where(np.isnan(dsm05), dtm05, dsm05)

    dsm = _block(dsm05, k, "max")
    dtm = _block(dtm05, k, "mean")
    water = _block(water05.astype("float32"), k, "mean") > 0.5

    cir = _read(cir_path, spec, band=None)  # NIR, red, green
    nir, red = cir[0], cir[1]
    ndvi_full = (nir - red) / np.maximum(nir + red, 1.0)
    kc = round(ndvi_full.shape[0] / spec.shape[0])
    ndvi = _block(ndvi_full, kc, "mean") if kc > 1 else ndvi_full

    # the WFS writes RD coordinates without a crs member, so GeoJSON readers assume WGS84
    bag = gpd.read_file(bag_path).set_crs(CRS, allow_override=True)
    bmask = rasterize(
        ((g, 1) for g in bag.geometry if g is not None and not g.is_empty),
        out_shape=spec.shape,
        transform=spec.transform,
        fill=0,
        dtype="uint8",
    ).astype(bool)

    height = np.clip(dsm - dtm, 0, None)
    building_dsm = np.where(bmask, np.maximum(dsm, dtm), dtm)
    near_building = binary_dilation(bmask, iterations=1)
    tall = ~near_building & ~water & (height >= min_tree_height)
    labels, n = label(tall)
    sizes = np.bincount(labels.ravel(), minlength=n + 1) * spec.res**2
    keep = sizes >= min_tree_area
    keep[0] = False
    trees = np.where(keep[labels], height, 0.0)

    landcover = np.ones(spec.shape, dtype="float32")  # paved by default
    landcover[(ndvi >= min_ndvi + 0.1) & (height < min_tree_height) & ~bmask] = 5
    landcover[water] = 7
    landcover[bmask] = 2

    if min(building_dsm.min(), dtm.min()) + ELEVATION_OFFSET <= 0:
        raise ValueError("ELEVATION_OFFSET too small for this tile")
    layers = {
        "Building_DSM": building_dsm + ELEVATION_OFFSET,
        "DEM": dtm + ELEVATION_OFFSET,
        "Trees": trees,
        "Landcover": landcover,
        "NDVI": ndvi,
    }
    profile = {
        "driver": "GTiff",
        "height": spec.shape[0],
        "width": spec.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": CRS,
        "transform": spec.transform,
        "compress": "deflate",
    }
    paths = {}
    for name, arr in layers.items():
        p = out_dir / f"{name}.tif"
        with rasterio.open(p, "w", **profile) as dst:
            dst.write(arr.astype("float32"), 1)
        paths[name] = p
    return paths
