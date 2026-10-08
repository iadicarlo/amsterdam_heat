"""Rank a district's neighbourhoods to pick where to plan new trees first.

    uv run python scripts/screen_district.py --district nieuw-west --date 2015-07-01

Needs district_stats.py and check_district.py. Neighbourhoods with at least 1000
residents are ranked on four things, each counting the same: least shade on walking
areas at 15:00, largest share of outdoor space above 41 C PET, fewest homes within
300 m of a cool park, and most residents aged 65 and over. The mean rank orders the
list. Writes docs/screen_<district>_<date>.md.
"""

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--district", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    s = pd.read_csv(ROOT / "data" / "processed" / "districts" / f"{args.district}_{args.date}" / "buurt_stats.csv")
    s = s[(s["residents"] >= 1000) & s["walk_shade_15h"].notna()].copy()
    ranks = pd.DataFrame({
        "shade": s["walk_shade_15h"].rank(),
        "heat": s["extreme_share"].rank(ascending=False),
        "park": s["homes_near_park"].rank(),
        "aged": s["aged_65_plus"].rank(ascending=False),
    })
    s["score"] = ranks.mean(axis=1)
    s = s.sort_values("score")
    pct = lambda v: f"{100 * v:.0f}%"
    lines = [
        f"# Where to start in {args.district.title()}", "",
        (f"{len(s)} neighbourhoods with at least 1000 residents, ranked on pavement shade at 15:00, "
         "outdoor space above 41 C PET, homes within 300 m of a cool park of 1 ha, and residents aged "
         "65 and over, each counting the same. Lower score comes first."), "",
        "| Buurt | Residents | 65+ | Above 41 C | Pavement shade 15:00 | Homes near a cool park | Score |",
        "|---|---|---|---|---|---|---|",
        *[f"| {r['naam']} ({r['code']}) | {r['residents']:.0f} | {r['aged_65_plus']:.0f} | "
          f"{pct(r['extreme_share'])} | {pct(r['walk_shade_15h'])} | {pct(r['homes_near_park'])} | "
          f"{r['score']:.1f} |" for _, r in s.head(args.top).iterrows()],
    ]
    out = ROOT / "docs" / f"screen_{args.district}_{args.date}.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
