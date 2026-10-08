"""Afternoon urban heat island over Amsterdam from street stations, as a map.

    uv run python scripts/fit_uhi.py

The model takes its air temperature from KNMI Schiphol. City stations are warmer
in the afternoon, and how much depends on what surrounds them. For every station of
the AAMS network of 2015 (PANGAEA) and the WUR Distributed Network of 2025 and 2026,
this takes the mean excess over Schiphol on hot afternoons (Schiphol maximum of
27 C or more, local hours 12:00 to 18:00), and fits it to the built-up and water
fractions around the station (ESA WorldCover 2021, 10 m), choosing the radius by
leave-one-out error. The fitted map is written to data/processed/uhi/dta_afternoon.tif
(EPSG:28992, 10 m), with docs/uhi.md and figures/uhi.png.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.warp import Resampling, reproject
from scipy.signal import fftconvolve

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed" / "uhi"
TZ = ZoneInfo("Europe/Amsterdam")
HOT = 27.0
AFTERNOON = range(13, 19)  # local hours ending 13 to 18
RADII = (100, 250, 500, 1000)
RES = 10.0
GRID = (108000.0, 476000.0, 132000.0, 494000.0)  # RD New box around Amsterdam
MIN_HOURS = 20
TO_RD = Transformer.from_crs(4326, 28992, always_xy=True)


def schiphol() -> pd.Series:
    rows = {}
    for f in sorted((RAW / "uhi").glob("knmi_240_*_jja.json")):
        for r in json.loads(f.read_text()):
            end = datetime.fromisoformat(r["date"]) + timedelta(hours=r["hour"])
            rows[pd.Timestamp(end)] = r["T"] / 10.0
    return pd.Series(rows).sort_index()


def pangaea() -> tuple[pd.DataFrame, pd.DataFrame]:
    series, meta = {}, []
    for f in sorted((RAW / "validation" / "pangaea_aams_2015" / "datasets").glob("*.tab")):
        text = f.read_text()
        lat, lon = map(float, re.search(r"LATITUDE: ([\d.]+) \* LONGITUDE: ([\d.]+)", text).groups())
        street = re.search(r"street name: ([^\n*]+)", text)
        body = text.split("*/\n", 1)[1]
        df = pd.read_csv(pd.io.common.StringIO(body), sep="\t")
        t = pd.to_datetime(df["Date/Time"]).dt.tz_localize("UTC")
        sid = "P" + f.stem.split("_")[1]
        series[sid] = pd.Series(df["TTT [°C]"].to_numpy(), index=t)
        meta.append({"station": sid, "name": street.group(1).strip() if street else sid,
                     "lat": lat, "lon": lon, "network": "AAMS 2015"})
    return pd.DataFrame(series), pd.DataFrame(meta)


def wur() -> tuple[pd.DataFrame, pd.DataFrame]:
    d = RAW / "validation" / "maq_amsterdam"
    st = pd.read_csv(d / "distributed_network_stations.csv")
    frames = []
    for y in (2025, 2026):
        df = pd.read_csv(d / f"distributed_network_{y}.csv", skiprows=[1], na_values="NaN")
        df.index = pd.to_datetime(df.pop("Timestamp")).dt.tz_localize("UTC")
        ta = df[[c for c in df if c.startswith("DN_TA_")]]
        # KNMI hourly temperature is a reading at the full hour, so take the station
        # readings within 10 minutes of each full hour rather than an hourly mean
        near = ta.index.round("1h")
        close = (ta.index - near).to_series().abs().to_numpy() <= pd.Timedelta(minutes=10)
        frames.append(ta[close].groupby(near[close]).mean())
    ta = pd.concat(frames)
    ta.columns = ["W" + c.split("_")[2] for c in ta.columns]
    meta = st.assign(station="W" + st["station"].astype(str), network="WUR 2025 to 2026")
    return ta, meta[["station", "name", "lat", "lon", "network"]]


def best_lag(obs: pd.DataFrame, ref: pd.Series) -> int:
    """Shift (hours) that best lines the stations up with Schiphol, from day-to-day swings."""
    scores = {}
    for lag in range(-2, 3):
        shifted = obs.shift(lag, freq="h").mean(axis=1)
        both = pd.concat([shifted.diff(), ref.diff()], axis=1, sort=True).dropna()
        scores[lag] = both.corr().iloc[0, 1]
    return max(scores, key=scores.get)


def excess(obs: pd.DataFrame, ref: pd.Series) -> pd.Series:
    local = ref.index.tz_convert(TZ)
    daily_max = ref.groupby(local.date).max()
    hot_days = set(daily_max[daily_max >= HOT].index)
    keep = [(t.date() in hot_days) and (t.hour in AFTERNOON) for t in local]
    hours = ref.index[keep]
    diff = obs.reindex(hours).sub(ref.reindex(hours), axis=0)
    n = diff.notna().sum()
    return diff.mean().where(n >= MIN_HOURS), n


def fraction_maps() -> tuple[dict, rasterio.Affine]:
    xmin, ymin, xmax, ymax = GRID
    w, h = int((xmax - xmin) / RES), int((ymax - ymin) / RES)
    transform = rasterio.transform.from_origin(xmin, ymax, RES, RES)
    lc = np.zeros((h, w), "uint8")
    with rasterio.open(RAW / "uhi" / "worldcover_2021_amsterdam.tif") as src:
        reproject(rasterio.band(src, 1), lc, dst_transform=transform, dst_crs="EPSG:28992",
                  resampling=Resampling.nearest)
    maps = {}
    for r in RADII:
        k = int(r / RES)
        yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
        disk = (xx**2 + yy**2 <= k**2).astype("float32")
        disk /= disk.sum()
        for name, cls in (("built", 50), ("water", 80)):
            maps[(name, r)] = np.clip(fftconvolve((lc == cls).astype("float32"), disk, mode="same"), 0, 1)
    return maps, transform


def sample(maps, transform, x, y):
    col, row = ~transform * (x, y)
    return {k: float(v[int(row), int(col)]) for k, v in maps.items()}


def fit(df: pd.DataFrame, r: int) -> tuple[np.ndarray, float]:
    X = np.column_stack([np.ones(len(df)), df[f"built_{r}"], df[f"water_{r}"]])
    y = df["dta"].to_numpy()
    coef = np.linalg.lstsq(X, y, rcond=None)[0]
    loo = []
    for i in range(len(df)):
        m = np.arange(len(df)) != i
        c = np.linalg.lstsq(X[m], y[m], rcond=None)[0]
        loo.append(y[i] - X[i] @ c)
    return coef, float(np.sqrt(np.mean(np.square(loo))))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ref = schiphol()
    rows = []
    for obs, meta in (pangaea(), wur()):
        lag = best_lag(obs, ref)
        obs = obs.shift(lag, freq="h")
        dta, n = excess(obs, ref)
        meta = meta.assign(dta=meta["station"].map(dta), hours=meta["station"].map(n), lag_h=lag)
        rows.append(meta)
        print(f"{meta['network'].iloc[0]}: shifted {lag:+d} h to match Schiphol")
    st = pd.concat(rows, ignore_index=True)
    st["x"], st["y"] = TO_RD.transform(st["lon"].to_numpy(), st["lat"].to_numpy())

    maps, transform = fraction_maps()
    fr = pd.DataFrame([sample(maps, transform, x, y) for x, y in zip(st["x"], st["y"], strict=True)])
    fr.columns = [f"{a}_{r}" for a, r in fr.columns]
    st = pd.concat([st, fr], axis=1)
    used = st.dropna(subset=["dta"]).reset_index(drop=True)

    base_loo = float(np.sqrt(np.mean([(used["dta"][i] - used["dta"].drop(i).mean()) ** 2
                                       for i in range(len(used))])))
    fits = {r: fit(used, r) for r in RADII}
    r_best = min(fits, key=lambda r: fits[r][1])
    coef, loo = fits[r_best]
    used["pred"] = coef[0] + coef[1] * used[f"built_{r_best}"] + coef[2] * used[f"water_{r_best}"]
    st.to_csv(OUT / "stations.csv", index=False)
    land = used[used[f"water_{r_best}"] < 0.1]
    pairs = used.assign(key=used["lat"].round(3).astype(str) + used["lon"].round(3).astype(str))
    pairs = pairs.groupby(["key", "network"])["dta"].mean().unstack().dropna()
    same_site = float((pairs.iloc[:, 0] - pairs.iloc[:, 1]).abs().mean())

    dta = (coef[0] + coef[1] * maps[("built", r_best)] + coef[2] * maps[("water", r_best)]).astype("float32")
    with rasterio.open(OUT / "dta_afternoon.tif", "w", driver="GTiff", height=dta.shape[0],
                       width=dta.shape[1], count=1, dtype="float32", crs="EPSG:28992",
                       transform=transform, compress="deflate") as d:
        d.write(dta, 1)
        d.update_tags(radius_m=r_best, intercept=coef[0], built=coef[1], water=coef[2], loo_rmse=loo)

    lines = [
        "# Afternoon heat island from street stations", "",
        ("The model uses air temperature from Schiphol. On hot afternoons (Schiphol maximum "
         f"{HOT:g} C or more, 12:00 to 18:00) city stations are warmer, and how much depends on "
         "what is around them. We fit each station's mean excess over Schiphol to the built-up "
         "and water fractions within a radius (ESA WorldCover 2021) and pick the radius with the "
         "smallest leave-one-out error."), "",
        (f"{len(used)} stations: {(used.network == 'AAMS 2015').sum()} from the 2015 AAMS network "
         f"(PANGAEA) and {(used.network != 'AAMS 2015').sum()} from the WUR Distributed Network "
         "(2025 and 2026)."), "",
        "| Radius | Leave-one-out RMSE (K) |", "|---|---|",
        *[f"| {r} m | {fits[r][1]:.2f} |" for r in RADII],
        f"| none (city mean) | {base_loo:.2f} |", "",
        (f"Chosen: {r_best} m. Excess = {coef[0]:+.2f} {coef[1]:+.2f} x built {coef[2]:+.2f} x water "
         f"(K, fractions 0 to 1). Station mean excess {used['dta'].mean():+.2f} K, range "
         f"{used['dta'].min():+.1f} to {used['dta'].max():+.1f} K."), "",
        "| Station | Network | Excess (K) | Fitted (K) | Built | Water |", "|---|---|---|---|---|---|",
        *[f"| {r['name']} | {r['network']} | {r['dta']:+.1f} | {r['pred']:+.1f} | "
          f"{r[f'built_{r_best}']:.2f} | {r[f'water_{r_best}']:.2f} |"
          for _, r in used.sort_values("dta", ascending=False).iterrows()], "",
        "![Afternoon heat island](../figures/uhi.png)", "",
        (f"On land (less than 10% water within {r_best} m) the fit is close to a constant "
         f"{land['pred'].mean():+.1f} K, while the stations spread by {land['dta'].std():.1f} K; "
         "land cover at this scale does not explain that spread, so street to street differences "
         "in air temperature stay unknown. Most of the fit's skill comes from water, which cools "
         "its surroundings by up to "
         f"{-coef[2]:.1f} K. The same street measured in 2015 and in 2025 to 2026 differs by "
         f"{same_site:.1f} K on average, a measure of how much sensors and summers matter."), "",
        ("Data: AAMS stations 2015, Ronda et al. 2017, PANGAEA, CC BY 3.0; MAQ Amsterdam "
         "Distributed Network, WUR, CC BY-NC 4.0; ESA WorldCover 2021, CC BY 4.0; KNMI."),
    ]
    (ROOT / "docs" / "uhi.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))

    fig, ax = plt.subplots(1, 2, figsize=(13, 5.2), constrained_layout=True)
    xmin, ymin, xmax, ymax = GRID
    im = ax[0].imshow(dta, extent=(xmin, xmax, ymin, ymax), cmap="RdBu_r", vmin=-2, vmax=2)
    ax[0].scatter(used["x"], used["y"], c=used["dta"], cmap="RdBu_r", vmin=-2, vmax=2,
                  edgecolor="k", s=40)
    fig.colorbar(im, ax=ax[0], shrink=0.8, label="afternoon excess over Schiphol (K)")
    ax[0].set_title(f"Fitted heat island, {r_best} m radius")
    ax[0].set_axis_off()
    for net, m in (("AAMS 2015", "o"), ("WUR 2025 to 2026", "s")):
        g = used[used.network == net]
        ax[1].scatter(g["pred"], g["dta"], marker=m, label=net)
    lim = [used[["pred", "dta"]].min().min() - 0.3, used[["pred", "dta"]].max().max() + 0.3]
    ax[1].plot(lim, lim, color="0.5", lw=0.8)
    ax[1].set_xlabel("fitted (K)")
    ax[1].set_ylabel("observed (K)")
    ax[1].set_title(f"Stations, leave-one-out RMSE {loo:.2f} K")
    ax[1].legend()
    fig.savefig(ROOT / "figures" / "uhi.png", dpi=120)


if __name__ == "__main__":
    main()
