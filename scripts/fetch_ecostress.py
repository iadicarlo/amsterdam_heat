"""Find and download ECOSTRESS land surface temperature over Amsterdam on hot days.

    uv run python scripts/fetch_ecostress.py --list       # search only, no login needed
    EARTHDATA_TOKEN=... uv run python scripts/fetch_ecostress.py   # download

The download needs an Earthdata login: a token in EARTHDATA_TOKEN, or ~/.netrc.

Hot days are summer days (June to August) with a maximum of at least --tmax at KNMI
Schiphol, from 2018 on. Only overpasses between --from-hour and --to-hour local time
are kept. Product: ECO_L2T_LSTE v002 (70 m, tiled, with a cloud mask), NASA LP DAAC.
Files go to data/raw/satellite/ecostress/.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import earthaccess
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "satellite" / "ecostress"
BBOX = (4.73, 52.28, 5.07, 52.43)  # lon min, lat min, lon max, lat max: Amsterdam
TILES = ("31UFU", "31UFT")  # the two 70 m MGRS tiles that cover Amsterdam
TZ = ZoneInfo("Europe/Amsterdam")


def hot_days(tmax: float) -> list[str]:
    r = requests.post(
        "https://www.daggegevens.knmi.nl/klimatologie/daggegevens",
        data={"start": "20180601", "end": datetime.now(TZ).strftime("%Y%m%d"), "vars": "TX",
              "stns": "240", "fmt": "json"},
        timeout=120,
    )
    r.raise_for_status()
    return sorted(d["date"][:10] for d in r.json()
                  if d.get("TX") is not None and d["TX"] >= tmax * 10 and d["date"][5:7] in ("06", "07", "08"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="only list what would be downloaded")
    ap.add_argument("--tmax", type=float, default=27.0)
    ap.add_argument("--from-hour", type=int, default=11)
    ap.add_argument("--to-hour", type=int, default=19)
    args = ap.parse_args()

    days = hot_days(args.tmax)
    print(f"{len(days)} hot days at Schiphol (Tmax >= {args.tmax:g} C)")
    found = []
    for day in days:
        results = earthaccess.search_data(
            short_name="ECO_L2T_LSTE", version="002", bounding_box=BBOX,
            temporal=(f"{day}T00:00:00", f"{day}T23:59:59"),
        )
        for g in results:
            t = datetime.fromisoformat(
                g["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"]
            ).astimezone(TZ)
            in_city = any(tile in g["meta"]["native-id"] for tile in TILES)
            if in_city and args.from_hour <= t.hour < args.to_hour:
                found.append((day, t.strftime("%H:%M"), g))
    print(f"{len(found)} overpasses between {args.from_hour}:00 and {args.to_hour}:00 local time")
    for day, hhmm, g in found:
        print(f"  {day} {hhmm}  {g['meta']['native-id']}")
    (ROOT / "data" / "interim").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "interim" / "ecostress_hot_overpasses.json").write_text(
        json.dumps([{"day": d, "local_time": h, "id": g["meta"]["native-id"]} for d, h, g in found], indent=1)
    )
    if args.list or not found:
        return

    import os

    earthaccess.login(strategy="environment" if os.environ.get("EARTHDATA_TOKEN") else "netrc")
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = ("_LST.tif", "_cloud.tif", "_QC.tif")
    granules = [g for _, _, g in found]
    links = [u for g in granules for u in g.data_links() if u.endswith(wanted)]
    earthaccess.download(links, local_path=str(OUT))
    (OUT / "SOURCE.json").write_text(json.dumps({
        "product": "ECOSTRESS ECO_L2T_LSTE v002, NASA LP DAAC",
        "doi": "10.5067/ECOSTRESS/ECO_L2T_LSTE.002",
        "licence": "NASA open data, no restrictions",
        "selection": f"summer days with Tmax >= {args.tmax:g} C at Schiphol, overpasses "
                     f"{args.from_hour}:00 to {args.to_hour}:00 local",
    }, indent=2))
    print(f"downloaded {len(links)} files to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
