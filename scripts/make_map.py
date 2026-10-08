"""Stitch a district's tiles and make a static figure and an interactive web map.

    uv run python scripts/make_map.py --district nieuw-west --date 2015-07-01

Takes the 500 m core of every finished tile and writes, in
data/processed/districts/<district>_<date>/:
  pet_afternoon.tif   mean PET 12:00 to 18:00 (C), 1 m
  shade_15h.tif       1 where shaded at 15:00, 1 m
  map/index.html      leafmap web map with both layers, the pedestrian main
                      routes and the neighbourhoods
and figures/<district>_<date>.png.
"""

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.warp import transform as warp_points

from amsterdam_heat import sources
from amsterdam_heat.guidelines import AFTERNOON, read_vector, shaded_at
from amsterdam_heat.paths import output_dir

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
TILE = 500
BUFFER = 100
CREDIT = ("Model: SOLWEIG-GPU. Data: AHN4, BAG, BGT (PDOK), Gemeente Amsterdam "
          "(infrarood2023, bomen, plus- en hoofdnetten, gebieden), KNMI")
PET_RANGE = (25, 45)


def stitch(tiles, device, date, res=1.0):
    done = [(x, y) for x, y in tiles if (output_dir(f"{x}_{y}", device, date) / "PET_0_0.tif").exists()]
    xs, ys = [t[0] for t in done], [t[1] for t in done]
    x0, y1 = min(xs), max(ys) + TILE
    w, h = round((max(xs) + TILE - x0) / res), round((y1 - min(ys)) / res)
    pet = np.full((h, w), np.nan, "float32")
    shade = np.full((h, w), np.nan, "float32")
    b, n = round(BUFFER / res), round(TILE / res)
    for x, y in done:
        out = output_dir(f"{x}_{y}", device, date)
        p = rasterio.open(out / "PET_0_0.tif").read()
        s = rasterio.open(out / "Shadow_0_0.tif").read()
        r, c = round((y1 - y - TILE) / res), round((x - x0) / res)
        pet[r:r + n, c:c + n] = np.nanmean(p[list(AFTERNOON)], axis=0)[b:b + n, b:b + n]
        shade[r:r + n, c:c + n] = shaded_at(s, 15)[b:b + n, b:b + n]
    return pet, shade, from_origin(x0, y1, res, res), len(done)


def write(path, arr, transform):
    with rasterio.open(path, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs="EPSG:28992", transform=transform, nodata=np.nan,
                       compress="deflate", tiled=True) as dst:
        dst.write(arr, 1)


def to_png(arr, transform, path, cmap, vmin, vmax, res=2.0):
    """Reproject to Web Mercator, colour it and save a PNG; returns the lat/lon bounds."""
    src_crs = "EPSG:28992"
    h, w = arr.shape
    left, top = transform.c, transform.f
    right, bottom = left + w * transform.a, top + h * transform.e
    dst_t, dw, dh = calculate_default_transform(src_crs, "EPSG:3857", w, h, left, bottom, right, top,
                                                resolution=res * 1.6)
    out = np.full((dh, dw), np.nan, "float32")
    reproject(arr, out, src_transform=transform, src_crs=src_crs, dst_transform=dst_t,
              dst_crs="EPSG:3857", resampling=Resampling.average, src_nodata=np.nan, dst_nodata=np.nan)
    rgba = plt.get_cmap(cmap)(np.clip((out - vmin) / (vmax - vmin), 0, 1))
    rgba[..., 3] = np.where(np.isnan(out), 0, 0.75)
    plt.imsave(path, rgba)
    lons, lats = warp_points(
        "EPSG:3857", "EPSG:4326",
        [dst_t.c, dst_t.c + dw * dst_t.a], [dst_t.f + dh * dst_t.e, dst_t.f])
    return [[lats[0], lons[0]], [lats[1], lons[1]]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--district", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--device", default="mps")
    args = ap.parse_args()

    tiles = json.loads((ROOT / "data" / "raw" / "city" / f"tiles_{args.district}.json").read_text())
    pet, shade, transform, n = stitch(tiles, args.device, args.date)
    out = ROOT / "data" / "processed" / "districts" / f"{args.district}_{args.date}"
    (out / "map").mkdir(parents=True, exist_ok=True)
    write(out / "pet_afternoon.tif", pet, transform)
    write(out / "shade_15h.tif", shade, transform)
    print(f"{n} of {len(tiles)} tiles stitched")

    city = ROOT / "data" / "raw" / "city"
    routes_path = city / "ams_plushoofdnetten.geojson"
    if not routes_path.exists():
        sources.amsterdam_walking_network(routes_path)
    h, w = pet.shape
    bbox = (transform.c, transform.f - h, transform.c + w, transform.f)
    buurt_path = city / f"buurten_{args.district}.geojson"
    if not buurt_path.exists():
        sources.amsterdam_buurten(bbox, buurt_path)
    district = read_vector(city / "stadsdelen.geojson")
    district = district[district["naam"].str.lower() == args.district]
    routes = read_vector(routes_path)
    routes = routes[routes["VOET"].isin(["PLUS", "HOOFD"])].clip(district.union_all())
    buurten = read_vector(buurt_path)
    buurten = buurten[buurten.representative_point().within(district.union_all())]

    # static figure
    fig, axes = plt.subplots(1, 2, figsize=(14, 7.5), constrained_layout=True)
    ext = (bbox[0], bbox[2], bbox[1], bbox[3])
    im = axes[0].imshow(pet, extent=ext, cmap="magma", vmin=PET_RANGE[0], vmax=PET_RANGE[1])
    fig.colorbar(im, ax=axes[0], shrink=0.7, label="mean PET 12:00 to 18:00 (C)")
    axes[0].set_title(f"Felt temperature, {args.date}")
    axes[1].imshow(np.where(np.isnan(shade), np.nan, shade), extent=ext, cmap="Greys", vmin=-0.3, vmax=1.3)
    axes[1].set_title("Shade at 15:00 (dark), pedestrian main routes")
    routes.plot(ax=axes[1], color="tab:orange", linewidth=1.2)
    for ax in axes:
        buurten.boundary.plot(ax=ax, color="tab:cyan", linewidth=0.4)
        ax.set_axis_off()
    fig.text(0.01, 0.005, CREDIT, fontsize=7, color="0.4")
    fig_path = ROOT / "figures" / f"{args.district}_{args.date}.png"
    fig.savefig(fig_path, dpi=130)
    print(f"wrote {fig_path.relative_to(ROOT)}")

    # web map
    import folium
    import leafmap.foliumap as leafmap

    m = leafmap.Map(center=[52.365, 4.81], zoom=13, draw_control=False, measure_control=False)
    m.add_basemap("nlmaps.grijs")
    m.add_basemap("nlmaps.luchtfoto", show=False)
    for name, arr, cmap, lo, hi, show in (
        ("Felt temperature (PET), afternoon", pet, "magma", *PET_RANGE, True),
        ("Shade at 15:00", np.where(shade > 0, 1.0, np.where(np.isnan(shade), np.nan, 0.0)),
         "Greys", -0.3, 1.3, False),
    ):
        png = f"{name.split()[0].lower()}.png"
        bounds = to_png(arr, transform, out / "map" / png, cmap, lo, hi)
        folium.raster_layers.ImageOverlay(str(out / "map" / png), bounds=bounds, name=name, show=show,
                                          attr=CREDIT).add_to(m)
    folium.GeoJson(buurten.to_crs(4326)[["naam", "geometry"]], name="Neighbourhoods",
                   style_function=lambda f: {"color": "#2a9db5", "weight": 1, "fill": False},
                   tooltip=folium.GeoJsonTooltip(["naam"])).add_to(m)
    folium.GeoJson(routes.to_crs(4326)[["VOET", "geometry"]], name="Pedestrian main routes",
                   style_function=lambda f: {"color": "#e8871e", "weight": 2}).add_to(m)
    m.add_colormap(cmap="magma", vmin=PET_RANGE[0], vmax=PET_RANGE[1],
                   label="PET 12:00 to 18:00 (C)")
    folium.LayerControl(collapsed=False).add_to(m)
    m.to_html(str(out / "map" / "index.html"), title=f"Heat in {args.district}, {args.date}")
    print(f"wrote {(out / 'map' / 'index.html').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
