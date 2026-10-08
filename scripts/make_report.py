"""Short Dutch report on Nieuw-West for the Gemeente, as a self-contained web page.

    uv run python scripts/make_report.py

Every number is read from the result files (district statistics, guideline check,
tree plans with their SOLWEIG checks, validation tables), so the report follows the
model when it is rerun. Writes data/processed/districts/nieuw-west_2015-07-01/report/index.html.
"""

import base64
import io
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "processed" / "districts" / "nieuw-west_2015-07-01"
TREES = ROOT / "data" / "processed" / "trees"
TEMPLATE = ROOT / "scripts" / "templates" / "report_nl.html"
MAP_URL = "https://claude.ai/artifact/ENZAUucxeiSTUpQnSqDzDf"
REPO_URL = "https://github.com/iadicarlo/amsterdam_heat"


def nl(v, d=1):
    """Dutch number: decimal comma, thin space for thousands."""
    s = f"{v:,.{d}f}".replace(",", " ").replace(".", ",")
    return s.replace(" ", " ")


def pct(v):
    return f"{100 * v:.0f}%"


def image(path: Path, width: int = 1500) -> str:
    img = Image.open(path).convert("RGB")
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    stats = pd.read_csv(RUN / "buurt_stats.csv")
    routes = pd.read_csv(RUN / "route_shade.csv")
    homes = pd.read_csv(RUN / "homes_cool_spots.csv")
    lived = stats[stats["residents"] >= 100]
    walk = stats.dropna(subset=["walk_shade_15h"])
    route_ok = routes["meets_40pct_at_15"]

    plans = {}
    for name in ("osdorpplein", "de-aker"):
        plans[name] = json.loads((TREES / name / "summary.json").read_text())

    def plan_rows(name):
        p = plans[name]
        rows = []
        for key, label in (("solweig", "1 juli 2015 (referentiedag)"), ("solweig_2019-07-25", "25 juli 2019 (hittegolf)")):
            if key not in p:
                continue
            b, a = p[key]["before"], p[key]["after"]
            route = (f"{pct(b['route_shade_15'])} → {pct(a['route_shade_15'])}" if "route_shade_15" in b else "geen hoofdroute")
            rows.append(f"<tr><td>{label}</td><td class='n'>{pct(b['pavement_shade_15'])} → {pct(a['pavement_shade_15'])}</td>"
                        f"<td class='n'>{route}</td><td class='n'>{nl(b['pet_afternoon'])} → {nl(a['pet_afternoon'])} &deg;C</td>"
                        f"<td class='n'>&minus;{nl(a['pet_drop_where_shaded'])} &deg;C</td></tr>")
        return "\n".join(rows)

    hva = pd.read_csv(ROOT / "data" / "processed" / "validation_hva.csv").dropna(subset=["pet_model"])
    hva_rmse = float(np.sqrt(((hva["pet_model"] - hva["pet"]) ** 2).mean()))
    trees_h = hva[hva["situation"] == "shade of trees"]
    hva_tree = float(np.sqrt(((trees_h["pet_model"] - trees_h["pet"]) ** 2).mean()))

    o, a = plans["osdorpplein"], plans["de-aker"]
    o15, a15 = o["solweig"], a["solweig"]
    worst = routes[routes["area_m2"] >= 500].nsmallest(5, "shade_15")
    values = {
        "PET_MEAN": nl(float(np.nanmean(stats["pet_mean"] * stats["outdoor_ha"]) / np.nanmean(stats["outdoor_ha"]))),
        "ROUTES_OK": str(int(route_ok.sum())), "ROUTES_N": str(len(routes)),
        "ROUTE_AREA_OK": pct(routes.loc[route_ok, "area_m2"].sum() / routes["area_m2"].sum()),
        "BUURT_MISS": str(int((walk["walk_shade_15h"] < 0.3).sum())), "BUURT_N": str(len(walk)),
        "HOMES_N": nl(len(homes), 0),
        "HOMES_COOL": pct((homes["distance_m"] <= 300).mean()),
        "HOMES_PARK": pct((homes["park_m"] <= 300).mean()),
        "PARK_MEDIAN": nl(homes["park_m"].median(), 0),
        "WORST_ROUTES": ", ".join(f"{r.street.title()} ({pct(r.shade_15)})" for r in worst.itertuples()),
        "HOT_BUURTEN": str(int((lived["extreme_share"] > 0.5).sum())), "BUURTEN_N": str(len(lived)),
        "O_TREES": str(o["trees"]), "A_TREES": str(a["trees"]),
        "O_ROUTE": f"{pct(o15['before']['route_shade_15'])} naar {pct(o15['after']['route_shade_15'])}",
        "A_PAVE": f"{pct(a15['before']['pavement_shade_15'])} naar {pct(a15['after']['pavement_shade_15'])}",
        "PET_DROP": f"{nl(o15['after']['pet_drop_where_shaded'])} tot {nl(a15['after']['pet_drop_where_shaded'])}",
        "O_ROWS": plan_rows("osdorpplein"), "A_ROWS": plan_rows("de-aker"),
        "HVA_RMSE": nl(hva_rmse), "HVA_TREE": nl(hva_tree), "HVA_N": str(len(hva)),
        "FIG_O": image(ROOT / "figures" / "trees_osdorpplein.png"),
        "FIG_A": image(ROOT / "figures" / "trees_de-aker.png"),
        "MAP_URL": MAP_URL, "REPO_URL": REPO_URL,
    }
    html = TEMPLATE.read_text()
    for k, v in values.items():
        html = html.replace(f"__{k}__", v)
    out = RUN / "report"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text(html)
    print(f"wrote {(out / 'index.html').relative_to(ROOT)} ({(out / 'index.html').stat().st_size / 1e6:.1f} MB)")
    left = sorted(set(re.findall(r"__[A-Z_]+__", html)))
    if left:
        print("placeholders left:", left)


if __name__ == "__main__":
    main()
