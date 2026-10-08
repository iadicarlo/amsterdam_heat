"""Download the open cables and pipes data for Nieuw-West into data/raw/utilities/.

    uv run python scripts/get_utilities.py [--only liander_ls ...]

One folder per dataset, each with a SOURCE.json (url, licence, date, citation) next
to the per-file .source.json that amsterdam_heat.sources writes.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from amsterdam_heat import sources as src

BBOX = (111500, 482000, 118500, 490500)  # Nieuw-West, RD New
ROOT = Path("data/raw/utilities")

LIANDER = {
    "url": "https://www.liander.nl/over-ons/open-data",
    "licence": "CC BY 4.0",
    "citation": "Liander N.V., Liander Open Data, liggingsgegevens elektriciteit en gas",
}
CITY = {
    "url": "https://api.data.amsterdam.nl/v1/leidingeninfrastructuur/",
    "licence": "CC BY (Creative Commons, Naamsvermelding)",
    "citation": "Gemeente Amsterdam, Kabels en leidingen ondergrond, data.amsterdam.nl",
}

def _stations(out: Path) -> Path:
    """Liander HS, MS and LS stations as one point file with column ``layer``."""
    features = []
    for layer in ("station_hs", "station_ms", "station_ls"):
        tmp = src.liander_network(layer, BBOX, out.with_name(f"{layer}.geojson"))
        for f in json.loads(tmp.read_text())["features"]:
            f["properties"]["layer"] = layer
            features.append(f)
        tmp.unlink()
        tmp.with_suffix(tmp.suffix + ".source.json").rename(out.with_suffix(f".{layer}.source.json"))
    out.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return out


DATASETS = {
    "liander_ls": (lambda p: src.liander_network("ls", BBOX, p), LIANDER),
    "liander_ms": (lambda p: src.liander_network("ms", BBOX, p), LIANDER),
    "liander_hs": (lambda p: src.liander_network("hs", BBOX, p), LIANDER),
    "liander_gas": (lambda p: src.liander_network("gas", BBOX, p), LIANDER),
    "waternet_sewers": (lambda p: src.amsterdam_underground("waternet_rioolleidingen", p, bbox=BBOX),
                        {**CITY, "citation": "Waternet, Rioolnetwerk, via Gemeente Amsterdam data.amsterdam.nl"}),
    "street_lighting": (lambda p: src.amsterdam_underground("amsterdam_ovl_ondergrondse_kabels", p,
                                                            bbox=BBOX, near=None), CITY),
    "gas_transmission": (lambda p: src.amsterdam_underground("aardgasleidingen", p, dataset="risicozones",
                                                             bbox=BBOX, near=None),
                         {"url": "https://api.data.amsterdam.nl/v1/risicozones/", "licence": "public",
                          "citation": "Gemeente Amsterdam, Risicozones, aardgasleidingen"}),
    "liander_stations": (lambda p: _stations(p), {**LIANDER, "citation": LIANDER["citation"]
                                                  + ", stations en LS kasten"}),
    "street_lighting_ducts": (lambda p: src.amsterdam_underground("amsterdam_ovl_mantelbuizen", p,
                                                                  bbox=BBOX, near=None), CITY),
    "bgt_points": (lambda p: src.bgt_utility_points(BBOX, p),
                   {"url": "https://api.pdok.nl/lv/bgt/ogc/v1/collections/put",
                    "licence": "CC0 1.0",
                    "citation": "Basisregistratie Grootschalige Topografie (BGT), plus objects put "
                                "(brandkraan) and kast, Gemeente Amsterdam via PDOK"}),
    "district_heating": (src.amsterdam_heat_network,
                         {"url": "https://maps.amsterdam.nl/open_geodata/?k=224",
                          "licence": "Maps Amsterdam open geodata terms (any lawful use)",
                          "citation": "Vattenfall Warmte, Stadswarmte en -koude, via Maps Amsterdam, May 2025"}),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=list(DATASETS))
    args = ap.parse_args()
    for name in args.only:
        fetch, meta = DATASETS[name]
        folder = ROOT / name
        folder.mkdir(parents=True, exist_ok=True)
        out = fetch(folder / f"{name}.geojson")
        n = len(json.loads(out.read_text())["features"])
        (folder / "SOURCE.json").write_text(json.dumps(
            {**meta, "date": datetime.now(UTC).date().isoformat(), "bbox_rd": BBOX, "features": n}, indent=2))
        print(f"{name}: {n} features")


if __name__ == "__main__":
    main()
