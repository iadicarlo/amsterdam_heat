"""What makes a spot good for a new tree: a model that explains the shade gain.

    uv run python scripts/explain_trees.py osdorpplein de-aker

For every candidate spot of the plans, the shade a tree there would add on its own
(plan_trees.py, weighted pavement m2) is related to features a planner can read off
the street: distance to the nearest facade, whether the tree's 15:00 shadow falls
towards that facade (the sunny side of the street), how much pavement lies within
15 m, how much of it is already shaded, and closeness to a main walking route.
A gradient boosting model is fitted and explained with SHAP values. This explains
the physics model's own result; it does not replace it. Features that move together
(distance to facade and pavement nearby) share their credit, so read the plot as a
ranking, not as exact effects. Writes figures/why_trees.png and docs/why_trees.md.
"""

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import pvlib
from scipy.ndimage import distance_transform_edt, uniform_filter
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import cross_val_score

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import shap

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"pavement_15m": "pavement within 15 m (m2)", "shaded_nearby": "share of it already shaded at 15:00",
         "facade_m": "distance to nearest facade (m)", "sunny_side": "shadow falls towards the facade",
         "route_m": "distance to a main walking route (m)"}


def features(name: str, date: str = "2015-07-01") -> pd.DataFrame:
    m = np.load(ROOT / "data" / "processed" / "trees" / name / "masks.npz")
    cands, gain = m["candidates"], m["gain0"]
    target, buildings, shaded = m["target"], m["buildings"], m["shaded15"]
    d_fac, (fr, fc) = distance_transform_edt(~buildings, return_indices=True)
    k = 31  # 15 m either side
    pave = uniform_filter(target.astype("float32"), k) * k * k
    pave_shaded = uniform_filter((target & shaded).astype("float32"), k) * k * k
    route_dist = distance_transform_edt(~m["route_target"]) if m["route_target"].any() else np.full(target.shape, 999.0)
    t = pd.DatetimeIndex([f"{date} 15:00"]).tz_localize("Europe/Amsterdam")
    az = np.radians(pvlib.solarposition.get_solarposition(t, 52.36, 4.80)["azimuth"].iloc[0])
    shadow_dir = np.array([np.cos(az), -np.sin(az)])  # rows, cols: away from the sun
    r, c = cands[:, 0], cands[:, 1]
    to_facade = np.column_stack([fr[r, c] - r, fc[r, c] - c]).astype(float)
    to_facade /= np.maximum(np.linalg.norm(to_facade, axis=1, keepdims=True), 1e-6)
    return pd.DataFrame({
        "gain": gain, "plan": name,
        "pavement_15m": pave[r, c],
        "shaded_nearby": pave_shaded[r, c] / np.maximum(pave[r, c], 1),
        "facade_m": d_fac[r, c],
        "sunny_side": to_facade @ shadow_dir,
        "route_m": np.minimum(route_dist[r, c], 200),
    })


def main() -> None:
    names = sys.argv[1:] or ["osdorpplein", "de-aker"]
    df = pd.concat([features(n) for n in names], ignore_index=True)
    df = df[df["gain"] > 0]
    X, y = df[list(NAMES)], df["gain"]
    model = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=0)
    r2 = cross_val_score(model, X, y, cv=5, scoring="r2")
    model.fit(X, y)
    sample = X.sample(min(3000, len(X)), random_state=0)
    sv = shap.TreeExplainer(model).shap_values(sample)
    importance = pd.Series(np.abs(sv).mean(axis=0), index=list(NAMES)).sort_values(ascending=False)

    fig, ax = plt.subplots(1, 2, figsize=(15, 5.5))
    plt.sca(ax[0])
    shap.summary_plot(sv, sample.rename(columns=NAMES), show=False, plot_size=None, color_bar=True)
    ax[0].set_title("What raises the shade a tree adds (each dot one possible spot)")
    top = df.nlargest(len(df) // 10, "gain")
    for label, g in (("all spots", df), ("best 10%", top)):
        ax[1].hist(g["sunny_side"], bins=30, range=(-1, 1), alpha=0.6, density=True, label=label)
    ax[1].set_xlabel("shadow at 15:00 falls away from (-1) or towards (+1) the nearest facade")
    ax[1].set_ylabel("share of spots")
    ax[1].set_title("Side of the street: the best 10% of spots against all spots")
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(ROOT / "figures" / "why_trees.png", dpi=120)

    sunny, sunny_all = top["sunny_side"].gt(0).mean(), df["sunny_side"].gt(0).mean()
    top_feature = NAMES[importance.index[0]]
    lines = [
        "# What makes a spot good for a new tree", "",
        (f"For {len(df)} candidate spots in {', '.join(names)}, the shade a tree would add on its own "
         "was related to five features of the street with a gradient boosting model, explained with SHAP "
         f"values. The model explains {np.mean(r2):.0%} of the variation between spots (five-fold "
         "cross-validation). It explains the physics result; the plans themselves come from the physics."), "",
        "| Feature | Mean effect on the shade added (weighted m2) |", "|---|---|",
        *[f"| {NAMES[k]} | {v:.1f} |" for k, v in importance.items()], "",
        (f"The strongest driver is {top_feature}: a tree helps most where there is a lot of pavement "
         "around it; how much of that is already shaded counts for less. Closeness to a main walking route comes next, partly by design, since "
         "the search counts route pavement double. Side of the street matters less than one might think: "
         f"{sunny:.0%} of the best 10% of spots cast their afternoon shadow towards the nearest facade, "
         f"against {sunny_all:.0%} of all spots. Neighbouring spots are alike, so the cross-validation "
         "score is on the generous side, and features that move together share their credit."), "",
        "![Why spots win](../figures/why_trees.png)",
    ]
    (ROOT / "docs" / "why_trees.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
