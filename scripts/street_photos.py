"""Street-level photos of every planned tree spot from the city's panoramas.

    uv run python scripts/street_photos.py osdorpplein de-aker

For each tree the nearest panorama within 40 m (80 m if none) is chosen, the
latest summer one (May to September) if there is one, else the latest. The city's
thumbnail service cuts a 640 px view facing the spot. Writes
data/raw/panorama/<plan>/<rank>.jpg, index.csv, a copy of the plan, and
figures/panorama_<plan>.png. The red mark is where the trunk would stand, assuming
flat ground and a camera 2.5 m up.

Panoramabeelden, Gemeente Amsterdam, CC BY 4.0 (api.data.amsterdam.nl/panorama).
"""

import argparse
import io
import json
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import requests
from PIL import Image, ImageDraw
from pyproj import Transformer

from amsterdam_heat.guidelines import read_vector

API = "https://api.data.amsterdam.nl/panorama"
LICENCE = "Panoramabeelden, Gemeente Amsterdam, CC BY 4.0"
WIDTH, FOV, ASPECT, HORIZON = 640, 80, 1.5, 0.4  # horizon: fraction of the height below it
CAMERA = 2.5  # m above the street
TO_RD = Transformer.from_crs(4326, 28992, always_xy=True)


def nearby(x: float, y: float, radius: int) -> list[dict]:
    url = f"{API}/panoramas/"
    params = {"near": f"{x},{y}", "srid": 28992, "radius": radius, "page_size": 200}
    out = []
    while url:
        r = requests.get(url, params=params, timeout=120)
        r.raise_for_status()
        d = r.json()
        out += d["_embedded"]["panoramas"]
        url, params = d["_links"]["next"]["href"], None
    return [p for p in out if p.get("surface_type") != "W"]


def choose(x: float, y: float) -> dict | None:
    for radius in (40, 80):
        panos = nearby(x, y, radius)
        if panos:
            break
    else:
        return None
    for p in panos:
        lon, lat = p["geometry"]["coordinates"][:2]
        px, py = TO_RD.transform(lon, lat)
        p["dist"] = math.hypot(x - px, y - py)
        p["heading_to_tree"] = math.degrees(math.atan2(x - px, y - py)) % 360
        p["date"] = p["timestamp"][:10]
        p["summer"] = 5 <= int(p["date"][5:7]) <= 9
    summer = [p for p in panos if p["summer"]]
    pool = summer or panos
    year = max(p["date"][:4] for p in pool)
    return min((p for p in pool if p["date"][:4] == year), key=lambda p: p["dist"])


def thumbnail_url(pano_id: str, heading: float) -> str:
    return (f"{API}/thumbnail/{pano_id}/?width={WIDTH}&heading={heading:.0f}&fov={FOV}"
            f"&aspect={ASPECT}&horizon={HORIZON}")


def marked(img: Image.Image, dist: float) -> Image.Image:
    """Copy with a red mark at the trunk base, from distance and camera height."""
    img = img.copy()
    w, h = img.size
    below = math.degrees(math.atan2(CAMERA, max(dist, 1.0)))
    yb = min(h - 4, (1 - HORIZON) * h + below * w / FOV)  # horizon is measured from the bottom
    draw = ImageDraw.Draw(img)
    r = max(4, w // 80)
    draw.line([(w / 2, yb - 6 * r), (w / 2, yb)], fill=(230, 20, 20), width=max(2, r // 2))
    draw.ellipse([w / 2 - r, yb - r, w / 2 + r, yb + r], outline=(230, 20, 20), width=max(2, r // 2))
    return img


def contact_sheet(folder: Path, index: pd.DataFrame, name: str, out: Path) -> None:
    n = len(index)
    cols = 5 if n <= 40 else 10
    rows = math.ceil(n / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.35), squeeze=False)
    for ax in axes.flat:
        ax.axis("off")
    for ax, row in zip(axes.flat, index.itertuples()):
        f = folder / f"{row.rank}.jpg"
        if not f.exists():
            continue
        ax.imshow(marked(Image.open(f), row.distance))
        ax.set_title(f"{row.rank}  ({row.date[:7]}, {row.distance:.0f} m)", fontsize=11, loc="left")
    fig.suptitle(f"Planned trees, {name}: view from the nearest city panorama toward each spot "
                 "(red mark). Panoramabeelden Gemeente Amsterdam, CC BY 4.0", fontsize=13, y=0.999)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, dpi=72)
    plt.close(fig)
    # a 256 colour palette keeps the sheet a few MB, fine for street photos
    Image.open(buf).convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT).save(out, optimize=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--sheets-only", action="store_true", help="redraw the contact sheets")
    args = ap.parse_args()
    for name in args.names:
        if args.sheets_only:
            folder = Path("data/raw/panorama") / name
            index = pd.read_csv(folder / "index.csv", dtype={"date": str})
            contact_sheet(folder, index, name, Path("figures") / f"panorama_{name}.png")
            continue
        plan = Path("data/processed/trees") / name / "trees.geojson"
        folder = Path("data/raw/panorama") / name
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(plan, folder / "trees_snapshot.geojson")
        trees = read_vector(plan)
        rows = []
        for t in trees.itertuples():
            p = choose(t.geometry.x, t.geometry.y)
            if p is None:
                rows.append({"rank": t.rank, "pano_id": "", "date": "", "distance": float("nan"),
                             "heading": float("nan"), "url": ""})
                continue
            url = thumbnail_url(p["pano_id"], p["heading_to_tree"])
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            (folder / f"{t.rank}.jpg").write_bytes(r.content)
            rows.append({"rank": t.rank, "pano_id": p["pano_id"], "date": p["date"],
                         "distance": round(p["dist"], 1), "heading": round(p["heading_to_tree"], 1),
                         "url": url})
        index = pd.DataFrame(rows)
        index.to_csv(folder / "index.csv", index=False)
        (folder / "SOURCE.json").write_text(json.dumps({
            "url": f"{API}/", "licence": LICENCE, "plan": str(plan),
            "fetched_utc": datetime.now(UTC).isoformat(timespec="seconds")}, indent=2))
        contact_sheet(folder, index, name, Path("figures") / f"panorama_{name}.png")
        print(f"{name}: {index.pano_id.ne('').sum()} of {len(index)} spots have a panorama, "
              f"dates {index.date.min()} to {index.date.max()}, "
              f"median distance {index.distance.median():.0f} m")


if __name__ == "__main__":
    main()
