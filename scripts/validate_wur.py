"""Compare the model with the WUR street stations (MAQ Amsterdam Distributed Network).

    uv run python scripts/validate_wur.py            # builds tiles and runs what is missing
    uv run python scripts/validate_wur.py --compare-only

Hot clear days: Schiphol Tmax >= 27 C in June to August 2025 and 2026, afternoon
(11 to 18 h local) global radiation at least 98% of clear sky, all six globes
reporting; the hottest MAX_DAYS of those. For each globe station the 500 m tile is
built and run with Schiphol weather and GLIDE-SOL wind.

Samples are averaged to hours labelled by the end of the local hour, as in the
model output. Observed Tmrt comes from the hourly black globe, air and wind with the
ISO 7726 formula (the larger of forced and free convection, emissivity 0.95). The
globe diameter is not documented, so it is bracketed with 40 mm and 150 mm.

Model values are the median of non-building, non-water pixels within RADIUS of the
station. An hour counts as sun when at least 75% of those pixels are sunlit, shade
when at most 25% are. Writes data/processed/validation_wur.csv and
figures/validation_wur.png and prints the tables for docs/validation_wur.md.

Data: Steeneveld et al. (2024), MAQ-Observations v1.0: Amsterdam, WUR, CC BY-NC 4.0.
"""

import argparse
import json
import subprocess
import sys

import matplotlib
import numpy as np
import pandas as pd
import pvlib
import rasterio
import requests
from pyproj import Transformer

from amsterdam_heat import sources
from amsterdam_heat.metfile import knmi_to_umep
from amsterdam_heat.paths import ROOT, inputs_dir, output_dir
from amsterdam_heat.pet import pet_point_local

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DEVICE = "mps"
RADIUS = 7.0  # m, station coordinates are given to 4 or 5 decimals (about 10 m)
MAX_DAYS = 8
CLEAR = 0.98
DIAMETERS = {"40": 0.040, "150": 0.150}  # m, bracket for the undocumented globe
EMISSIVITY = 0.95
SIGMA = 5.67e-8
YEARS = (2025, 2026)
HOURS = range(8, 21)  # hour labels (end of local hour) with the sun well up
AFTERNOON = range(13, 19)  # 12:00 to 18:00 local
NIGHT = (23, 24, 1, 2, 3, 4, 5, 6)  # 22:00 to 06:00 local, both nights of the day
DN = ROOT / "data" / "raw" / "validation" / "maq_amsterdam"
KNMI_DIR = ROOT / "data" / "raw" / "knmi"
TZ = "Europe/Amsterdam"
SCHIPHOL = (52.318, 4.790)


def run(script: str, *args: str) -> None:
    print(script, *args, flush=True)
    subprocess.run([sys.executable, script, *args], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)


def tmrt_from_globe(tg, ta, v, d: float) -> np.ndarray:
    """ISO 7726 black globe: larger of forced and free convection coefficients."""
    tg, ta, v = (np.asarray(a, dtype=float) for a in (tg, ta, v))
    forced = 6.3 * np.maximum(v, 0.1) ** 0.6 / d**0.4
    free = 1.4 * (np.abs(tg - ta) / d) ** 0.25
    h = np.maximum(forced, free)
    return ((tg + 273.15) ** 4 + h / (EMISSIVITY * SIGMA) * (tg - ta)) ** 0.25 - 273.15


def read_dn() -> pd.DataFrame:
    """All stations on a common 5 minute grid, one row per station and time.

    Each variable is logged on its own minutes, so every series is interpolated in
    time (gaps up to 20 min, 60 min for wind) before they are combined.
    """
    frames = []
    for year in YEARS:
        df = pd.read_csv(DN / f"distributed_network_{year}.csv", skiprows=[1], na_values=["NaN"])
        df.index = pd.to_datetime(df["Timestamp"].str.removesuffix(" UTC")).dt.tz_localize("UTC")
        for s in range(1, 24):
            cols = {}
            for v in ("TA", "RH", "WS", "TG"):
                c = f"DN_{v}_{s}_1_1"
                if c in df and df[c].notna().any():
                    limit = 12 if v == "WS" else 4  # wind is logged every 10 to 50 min
                    cols[v.lower()] = (df[c].dropna().resample("5min").mean()
                                       .interpolate(limit=limit, limit_area="inside"))
            if "ta" in cols:
                frames.append(pd.DataFrame(cols).assign(station=s))
    df = pd.concat(frames).rename_axis("t").reset_index()
    for c in ("rh", "ws", "tg"):
        if c not in df:
            df[c] = np.nan
    loc = (df["t"] + pd.Timedelta(seconds=1)).dt.tz_convert(TZ)
    end = loc.dt.floor("h") + pd.Timedelta(hours=1)
    df["date"] = loc.dt.date.astype(str)
    df["hour"] = end.dt.hour.where(end.dt.hour > 0, 24)
    return df


def schiphol_hourly() -> pd.DataFrame:
    """KNMI Schiphol hourly data for June to August, with clear-sky radiation."""
    KNMI_DIR.mkdir(parents=True, exist_ok=True)
    recs = []
    for year in YEARS:
        path = KNMI_DIR / f"knmi_240_hourly_{year}_jja.json"
        if not path.exists():
            sources.knmi_hourly(240, f"{year}053120", f"{year}083124", path)
        recs += json.loads(path.read_text())
    k = pd.DataFrame(recs)
    k["t"] = (pd.to_datetime(k["date"].str[:10]) + pd.to_timedelta(k["hour"], unit="h")).dt.tz_localize("UTC")
    k["global"] = k["Q"] * 1e4 / 3600
    k["ta_schiphol"] = k["T"] / 10
    mid = pd.DatetimeIndex(k["t"] - pd.Timedelta(minutes=30))
    k["clear"] = pvlib.location.Location(*SCHIPHOL).get_clearsky(mid, model="ineichen")["ghi"].to_numpy()
    loc = k["t"].dt.tz_convert(TZ)
    k["date"] = (loc - pd.Timedelta(minutes=1)).dt.date.astype(str)
    k["hour"] = loc.dt.hour.where(loc.dt.hour > 0, 24)
    return k[["date", "hour", "global", "clear", "ta_schiphol"]]


def pick_days(dn: pd.DataFrame, knmi: pd.DataFrame) -> list[str]:
    r = requests.post(
        "https://www.daggegevens.knmi.nl/klimatologie/daggegevens",
        data={"start": f"{YEARS[0]}0601", "end": f"{YEARS[-1]}0831", "vars": "TX", "stns": "240",
              "fmt": "json"},
        timeout=120,
    )
    r.raise_for_status()
    tx = {d["date"][:10]: d["TX"] / 10 for d in r.json() if d.get("TX") is not None}
    pm = knmi[knmi["hour"].between(12, 18)].groupby("date")[["global", "clear"]].sum()
    clear = (pm["global"] / pm["clear"]).to_dict()
    globes = dn.dropna(subset=["tg"])
    n_globes = globes[globes["hour"].isin(AFTERNOON)].groupby("date")["station"].nunique().to_dict()
    ok = [d for d, t in tx.items() if t >= 27 and d[5:7] in ("06", "07", "08")
          and clear.get(d, 0) >= CLEAR and n_globes.get(d, 0) == 6]
    days = sorted(sorted(ok, key=lambda d: -tx[d])[:MAX_DAYS])
    for d in days:
        print(f"{d}  Tmax {tx[d]:.1f} C  afternoon clear-sky ratio {clear[d]:.2f}")
    return days


def hourly(dn: pd.DataFrame) -> pd.DataFrame:
    """Hourly means; Tmrt from the hourly globe, air and wind. Several anemometers log
    only every 50 min and one not at all, so a missing hour takes the mean wind of
    the street stations that hour (flagged in ws_filled)."""
    g = dn.groupby(["station", "date", "hour"])
    out = g[["ta", "rh", "ws", "tg"]].mean()
    out["samples"] = g["ta"].count()
    out = out[out["samples"] >= 6].reset_index()
    out["ws_filled"] = out["ws"].isna()
    city = out.groupby(["date", "hour"])["ws"].transform("mean")
    out["ws"] = out["ws"].fillna(city)
    for name, d in DIAMETERS.items():
        out[f"tmrt{name}"] = tmrt_from_globe(out["tg"], out["ta"], out["ws"], d)
    return out


def prepare(tile: str, x0: int, y0: int, date: str) -> None:
    """Inputs once per tile, met per date, model run and PET per tile and date."""
    inp = inputs_dir(tile)
    if not (inp / "Building_DSM.tif").exists():
        run("scripts/make_tile.py", "--x", str(x0), "--y", str(y0), "--date", date)
    met = inp / f"met_{date}.txt"
    if not met.exists():
        d = pd.Timestamp(date)
        knmi = ROOT / "data" / "raw" / tile / f"knmi_240_{date}.json"
        if not knmi.exists():
            start = (d - pd.Timedelta(days=1)).strftime("%Y%m%d") + "20"
            sources.knmi_hourly(240, start, d.strftime("%Y%m%d") + "24", knmi)
        knmi_to_umep(knmi, date, met)
    out = output_dir(tile, DEVICE, date)
    if not (out / "TMRT_0_0.tif").exists():
        run("scripts/run_solweig.py", "--tile", tile, "--date", date, "--device", DEVICE)
    if not (out / "PET_0_0.tif").exists():
        run("scripts/compute_pet.py", "--tile", tile, "--date", date, "--device", DEVICE)


def model_at_station(tile: str, date: str, x: float, y: float) -> pd.DataFrame:
    """Hourly model values around one station on one day."""
    inp, out = inputs_dir(tile), output_dir(tile, DEVICE, date)
    with rasterio.open(inp / "Landcover.tif") as src:
        lc = src.read(1)
        rows, cols = np.indices(lc.shape)
        xs, ys = rasterio.transform.xy(src.transform, rows.ravel(), cols.ravel())
        r0, c0 = src.index(x, y)
    dist = np.hypot(np.array(xs) - x, np.array(ys) - y).reshape(lc.shape)
    sel = (dist <= RADIUS) & (lc != 2) & (lc != 7)
    with rasterio.open(out / "Shadow_0_0.tif") as s, rasterio.open(out / "TMRT_0_0.tif") as t, \
            rasterio.open(out / "PET_0_0.tif") as p:
        shadow, tmrt, pet = s.read(), t.read(), p.read()
    rec = []
    for band in range(1, 24):  # band H is the hour ending at H:00 local
        rec.append({
            "hour": band, "sunlit": float(shadow[band][sel].mean()),
            "sunlit_pixel": float(shadow[band, r0, c0]),
            "tmrt_model": float(np.median(tmrt[band][sel])),
            "tmrt_pixel": float(tmrt[band, r0, c0]),
            "pet_model": float(np.median(pet[band][sel])),
        })
    return pd.DataFrame(rec).assign(pixels=int(sel.sum()))


def stats(o, m) -> tuple[str, str, str]:
    d = np.asarray(m) - np.asarray(o)
    r = np.corrcoef(o, m)[0, 1] if len(d) > 2 else np.nan
    return f"{d.mean():+.1f}", f"{np.sqrt((d**2).mean()):.1f}", f"{r:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--compare-only", action="store_true")
    args = ap.parse_args()

    stations = pd.read_csv(DN / "distributed_network_stations.csv")
    to_rd = Transformer.from_crs(4326, 28992, always_xy=True)
    stations["x"], stations["y"] = to_rd.transform(stations["lon"].to_numpy(), stations["lat"].to_numpy())
    stations["x0"] = (stations["x"] // 500 * 500).astype(int)
    stations["y0"] = (stations["y"] // 500 * 500).astype(int)
    stations["tile"] = stations["x0"].astype(str) + "_" + stations["y0"].astype(str)
    globes = stations[stations["globe"]]

    dn = read_dn()
    knmi = schiphol_hourly()
    days = pick_days(dn, knmi)
    obs = hourly(dn[dn["date"].isin(days)])
    obs = obs.merge(knmi, on=["date", "hour"], how="left")

    # air temperature excess over Schiphol, all stations, on the chosen days
    obs["dta"] = obs["ta"] - obs["ta_schiphol"]
    uhi = pd.DataFrame({
        "mean": obs[obs["hour"].isin(AFTERNOON)].groupby("station")["dta"].mean(),
        "std": obs[obs["hour"].isin(AFTERNOON)].groupby("station")["dta"].std(),
        "night": obs[obs["hour"].isin(NIGHT)].groupby("station")["dta"].mean(),
    }).join(stations.set_index("station")["name"])
    print("\n| Station | Name | 12 to 18 h (K) | sd | 22 to 6 h (K) |\n|---|---|---|---|---|")
    for s, r in uhi.iterrows():
        print(f"| {s} | {r['name']} | {r['mean']:+.1f} | {r['std']:.1f} | {r['night']:+.1f} |")

    if not args.compare_only:
        for g in globes.itertuples():
            for d in days:
                prepare(g.tile, g.x0, g.y0, d)

    model = []
    for g in globes.itertuples():
        for d in days:
            model.append(model_at_station(g.tile, d, g.x, g.y).assign(station=g.station, date=d))
    model = pd.concat(model, ignore_index=True)
    obs = obs[obs["station"].isin(globes["station"])].dropna(subset=["tg"])
    obs = obs[obs["hour"].isin(HOURS)].merge(model, on=["station", "date", "hour"])

    # clock check: shift the observed hours and see which lag matches the model best
    print("\nClock check, r of observed Tg - Ta with model Tmrt - Ta:")
    for lag in (-2, -1, 0, 1, 2):
        o = obs[["station", "date", "hour", "tg", "ta"]].assign(hour=obs["hour"] + lag)
        m = o.merge(model, on=["station", "date", "hour"]).merge(knmi, on=["date", "hour"])
        r = np.corrcoef(m["tg"] - m["ta"], m["tmrt_model"] - m["ta_schiphol"])[0, 1]
        print(f"  observed hour + {lag:+d}: r = {r:.3f}  (n = {len(m)})")

    obs["situation"] = np.select([obs["sunlit"] >= 0.75, obs["sunlit"] <= 0.25], ["sun", "shade"], "mixed")
    obs["tg_minus_ta"] = obs["tg"] - obs["ta"]
    for n in DIAMETERS:
        obs[f"pet{n}"] = [pet_point_local(r.ta, r.rh, getattr(r, f"tmrt{n}"), max(r.ws, 0.5))
                          for r in obs.itertuples()]
    obs.to_csv(ROOT / "data" / "processed" / "validation_wur.csv", index=False)

    print("\n| Situation | n | Globe | Tmrt bias (K) | Tmrt RMSE (K) | Tmrt r | PET bias (K) | PET RMSE (K) |")
    print("|---|---|---|---|---|---|---|---|")
    for name, g in [("all", obs), *obs.groupby("situation")]:
        for n in DIAMETERS:
            b, e, r = stats(g[f"tmrt{n}"], g["tmrt_model"])
            pb, pe, _ = stats(g[f"pet{n}"], g["pet_model"])
            print(f"| {name} | {len(g)} | {n} mm | {b} | {e} | {r} | {pb} | {pe} |")

    print("\nPer station, sun hours (40 mm / 150 mm bias, K), wind, observed Tg - Ta:")
    for s, g in obs[obs["situation"] == "sun"].groupby("station"):
        b40, _, _ = stats(g["tmrt40"], g["tmrt_model"])
        b150, _, _ = stats(g["tmrt150"], g["tmrt_model"])
        print(f"  {s}: n={len(g)} bias {b40} / {b150}  wind {g['ws'].mean():.1f}  "
              f"Tg-Ta {g['tg_minus_ta'].mean():.1f}  model Tmrt-Ta {(g['tmrt_model'] - g['ta_schiphol']).mean():.1f}")
    sun = obs[obs["situation"] == "sun"]
    for n in DIAMETERS:
        r = np.corrcoef(sun["tmrt_model"] - sun[f"tmrt{n}"], sun["ws"])[0, 1]
        print(f"  r(sun bias {n} mm, measured wind) = {r:.2f}")
    agree = ((obs["sunlit_pixel"] > 0.5) == (obs["sunlit"] > 0.5)).mean()
    print(f"  station pixel and neighbourhood agree on sun or shade in {agree:.0%} of hours")

    fig, ax = plt.subplots(1, 3, figsize=(15, 4.8))
    colours = {"sun": "#d95f02", "mixed": "#999999", "shade": "#1b9e77"}
    for a, n in zip(ax[:2], DIAMETERS, strict=True):
        for sit, g in obs.groupby("situation"):
            a.scatter(g[f"tmrt{n}"], g["tmrt_model"], s=12, color=colours[sit], label=sit, alpha=0.7)
        lo, hi = 15, 70
        a.plot([lo, hi], [lo, hi], "k--", lw=0.8)
        a.set_xlim(lo, hi)
        a.set_ylim(lo, hi)
        a.set_xlabel(f"Globe Tmrt, {n} mm assumed (C)")
        a.set_ylabel("Model Tmrt (C)")
        a.set_title(f"Tmrt, {n} mm globe")
    ax[0].legend(frameon=False)
    u = uhi.sort_values("night")
    pos = np.arange(len(u))
    ax[2].barh(pos + 0.2, u["mean"], height=0.4, color="#d95f02", label="12 to 18 h")
    ax[2].barh(pos - 0.2, u["night"], height=0.4, color="#7570b3", label="22 to 6 h")
    ax[2].set_yticks(pos, [f"{s} {nm}" for s, nm in zip(u.index, u["name"], strict=True)])
    ax[2].axvline(0, color="k", lw=0.8)
    ax[2].set_xlabel("Air temperature minus Schiphol (K)")
    ax[2].set_title("Street air against Schiphol")
    ax[2].tick_params(axis="y", labelsize=7)
    ax[2].legend(frameon=False, fontsize=8, loc="lower left")
    fig.text(0.01, 0.01, f"Measurements: WUR MAQ-Observations Amsterdam, Steeneveld et al. 2024 (CC BY-NC 4.0). "
             f"Weather: KNMI Schiphol. Model: SOLWEIG-GPU, 1 m, {len(days)} days in 2025 and 2026",
             fontsize=8, color="0.4")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(ROOT / "figures" / "validation_wur.png", dpi=100)


if __name__ == "__main__":
    main()
