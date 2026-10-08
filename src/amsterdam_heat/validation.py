"""Measurements to check the model against.

HvA "Thermal comfort Amsterdam" (doi:10.21943/auas.7359206, CC BY 4.0): one-minute
air temperature, humidity, wind, global radiation and globe temperature at 21
places in central Amsterdam on 12 summer afternoons in 2015 and 2016, each record
marked sun or shade. The globe is a 38 mm grey table tennis ball, the type
Thorsson et al. (2007) calibrated, so Tmrt follows their forced-convection formula.

The exact instrument spot on each square is not given, only the square and whether
it stood in sun or shade. The model is therefore compared with the median of the
pixels near the square that are in the same situation at that hour.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .pet import pet_point_local

GLOBE_D = 0.038  # m
GLOBE_EMISSIVITY = 0.97

# name used in the sheets -> search string for PDOK's locatieserver
SITE_QUERIES = {
    "Dam": "Dam", "IJ promenade": "De Ruijterkade", "Stationsplein": "Stationsplein",
    "Leidseplein": "Leidseplein", "Vondelpark": "Vondelpark", "Mahlerplein": "Gustav Mahlerplein",
    "Museumplein": "Museumplein", "Magere Brug": "Amstel", "Oosterdok-roof": "Oosterdok",
    "Oosterdokskade-AMG": "Oosterdokskade", "Rembrandt-Thorbeck": "Rembrandtplein",
    "Spui": "Spui", "Weesperzijde": "Weesperzijde", "Amstelplein": "Amstelplein",
    "Reguliersgracht": "Reguliersgracht", "Rembrandtplein": "Rembrandtplein",
    "Museumplein pond": "Museumplein", "Museumstraat": "Museumstraat",
    "Frederiksplein": "Frederiksplein", "Frederiksplein pond": "Frederiksplein",
    "Oosterdokskade": "Oosterdokskade", "AMG Schmidtstraat": "Oosterdokskade",
    "Thorbeckeplein": "Thorbeckeplein",
}


def tmrt_from_globe(tg: np.ndarray, ta: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Thorsson et al. (2007) for a 38 mm grey globe (C, C, m/s)."""
    v = np.maximum(v, 0.1)
    k = 1.335e8 * v**0.71 / (GLOBE_EMISSIVITY * GLOBE_D**0.4)
    return ((tg + 273.15) ** 4 + k * (tg - ta)) ** 0.25 - 273.15


def read_hva(xlsx: Path) -> pd.DataFrame:
    """All sheets as one table, one row per minute."""
    frames = []
    for sheet, df in pd.read_excel(xlsx, sheet_name=None).items():
        df = df.iloc[:, :9]
        df.columns = ["site", "date", "time", "situation", "ta", "rh", "wind", "global", "tg"]
        df["sheet"] = sheet
        frames.append(df)
    df = pd.concat(frames, ignore_index=True).dropna(subset=["ta", "tg"])
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["time"] = pd.to_datetime(df["time"].astype(str), format="%H:%M:%S").dt.time
    df["situation"] = df["situation"].astype(str).str.strip().str.lower()
    df["site"] = df["site"].astype(str).str.strip()
    for c in ["ta", "rh", "wind", "global", "tg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["tmrt"] = tmrt_from_globe(df["tg"].to_numpy(), df["ta"].to_numpy(), df["wind"].to_numpy())
    return df


def hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Hourly means labelled by the end of the hour (the model's convention), keeping
    only hours with at least 40 minutes at one site in one situation."""
    hour_end = pd.Series([t.hour + 1 for t in df["time"]], index=df.index)
    g = df.assign(hour=hour_end).groupby(["sheet", "site", "date", "hour", "situation"])
    out = g[["ta", "rh", "wind", "global", "tg", "tmrt"]].mean()
    out["minutes"] = g.size()
    out = out[(out["minutes"] >= 40) & out["tmrt"].notna()].reset_index()
    out["pet"] = [pet_point_local(r.ta, r.rh, r.tmrt, max(r.wind, 0.5)) for r in out.itertuples()]
    return out


def geocode(name: str) -> tuple[float, float]:
    """RD New centroid of a public space in Amsterdam (PDOK locatieserver)."""
    r = requests.get(
        "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
        params={"q": f"{name} Amsterdam", "fq": "type:weg", "rows": 1, "fl": "centroide_rd"},
        timeout=30,
    )
    r.raise_for_status()
    pt = r.json()["response"]["docs"][0]["centroide_rd"]
    x, y = pt.removeprefix("POINT(").removesuffix(")").split()
    return float(x), float(y)
