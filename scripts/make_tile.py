"""Download open data for one 500 m tile and build the SOLWEIG inputs.

Example (De Pijp, around Sarphatipark), heatwave day 25 July 2019:

    uv run python scripts/make_tile.py --x 121500 --y 485000 --date 2019-07-25
"""

import argparse
from datetime import date, timedelta
from pathlib import Path

from amsterdam_heat import sources
from amsterdam_heat.metfile import knmi_to_umep
from amsterdam_heat.tile_inputs import TileSpec, build

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--x", type=float, required=True, help="tile lower left x, RD New (m)")
    ap.add_argument("--y", type=float, required=True, help="tile lower left y, RD New (m)")
    ap.add_argument("--date", required=True, help="local date YYYY-MM-DD")
    ap.add_argument("--res", type=float, default=1.0)
    ap.add_argument(
        "--cir-layer", default="infrarood2023",
        help="Gemeente Amsterdam infrared layer; infrarood2023 is the leaf-on summer flight",
    )
    ap.add_argument("--station", type=int, default=240, help="KNMI station, 240 = Schiphol")
    args = ap.parse_args()

    spec = TileSpec(args.x, args.y, res=args.res)
    raw = ROOT / "data" / "raw" / spec.corner
    raw.mkdir(parents=True, exist_ok=True)

    def fetch(path: Path, fn, *a):
        if path.exists():
            print(f"have {path.name}")
        else:
            print(f"downloading {path.name}")
            fn(*a, path)
        return path

    dsm = fetch(raw / "ahn4_dsm_05m.tif", sources.ahn_geotiff, "dsm_05m", spec.bbox)
    dtm = fetch(raw / "ahn4_dtm_05m.tif", sources.ahn_geotiff, "dtm_05m", spec.bbox)
    bag = fetch(raw / "bag_pand.geojson", sources.bag_footprints, spec.bbox)
    cir = fetch(
        raw / f"ams_{args.cir_layer}_025m.tif", sources.amsterdam_aerial, spec.bbox, 0.25,
        args.cir_layer,
    )
    register = fetch(raw / "ams_bomen.geojson", sources.amsterdam_trees, spec.bbox)

    d = date.fromisoformat(args.date)
    start = (d - timedelta(days=1)).strftime("%Y%m%d") + "20"
    end = d.strftime("%Y%m%d") + "24"
    knmi = fetch(raw / f"knmi_{args.station}_{args.date}.json", sources.knmi_hourly,
                 args.station, start, end)

    out = ROOT / "data" / "interim" / spec.name
    paths = build(spec, dsm, dtm, bag, cir, out, register_path=register)
    met = knmi_to_umep(knmi, args.date, out / f"met_{args.date}.txt")
    for p in [*paths.values(), met]:
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
