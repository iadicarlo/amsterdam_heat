"""Physiological Equivalent Temperature (PET) on SOLWEIG grids.

PET is what Amsterdam's heat guidelines and the Klimaateffectatlas use, so we
report it next to UTCI. The solver is UMEP's (``umep_pet._PET``), one point at a
time. Within one hour air temperature, humidity and wind are the same over the
whole tile (station forcing), so PET depends only on Tmrt. For each hour we
therefore solve PET on a fine Tmrt grid and interpolate, which is exact to well
below 0.05 K (see ``tests/test_pet.py``) and takes about a second per hour.

With a street-level wind field (GLIDE-SOL coefficients, see ``windcoeff.py``) PET
depends on Tmrt and wind, so the lookup is two-dimensional, with log-spaced wind nodes.
With a local air temperature offset (the afternoon heat island, ``fit_uhi.py``) a
third axis is added; the vapour pressure is kept, so humidity drops where the air
is warmer.

Person and wind height follow UMEP's SOLWEIG defaults.
"""

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from .umep_pet import _PET


@dataclass(frozen=True)
class Person:
    mbody: float = 75.0  # kg
    age: float = 35.0  # years
    height: float = 1.80  # m
    activity: float = 80.0  # W
    clo: float = 0.9
    sex: int = 1  # 1 male, 2 female


WIND_SENSOR_HEIGHT = 10.0  # m, KNMI standard
PEDESTRIAN_HEIGHT = 1.1  # m, as in SOLWEIG
MIN_WIND = 0.5  # m/s at 1.1 m, as GLIDE-SOL and the national PET map


def wind_at_pedestrian_height(ws10: float) -> float:
    """Power law used by UMEP SOLWEIG for PET."""
    return (PEDESTRIAN_HEIGHT / WIND_SENSOR_HEIGHT) ** 0.2 * ws10


DEFAULT_PERSON = Person()


def pet_point(
    ta: float, rh: float, tmrt: float, ws10: float, person: Person = DEFAULT_PERSON
) -> float:
    p = person
    return float(
        _PET(
            ta,
            rh,
            tmrt,
            wind_at_pedestrian_height(ws10),
            p.mbody,
            p.age,
            p.height,
            p.activity,
            p.clo,
            p.sex,
        )
    )


def pet_hour(
    tmrt: np.ndarray,
    ta: float,
    rh: float,
    ws10: float,
    person: Person = DEFAULT_PERSON,
    step: float = 0.5,
) -> np.ndarray:
    """PET for one hour on a Tmrt grid (NaN stays NaN)."""
    finite = np.isfinite(tmrt)
    out = np.full(tmrt.shape, np.nan, dtype="float32")
    if not finite.any():
        return out
    lo = np.floor(np.nanmin(tmrt)) - step
    hi = np.ceil(np.nanmax(tmrt)) + step
    nodes = np.arange(lo, hi + step / 2, step)
    values = np.array([pet_point(ta, rh, t, ws10, person) for t in nodes])
    out[finite] = np.interp(tmrt[finite], nodes, values)
    return out


def pet_point_local(
    ta: float, rh: float, tmrt: float, v: float, person: Person = DEFAULT_PERSON
) -> float:
    """PET with the wind already at pedestrian height."""
    p = person
    return float(_PET(ta, rh, tmrt, v, p.mbody, p.age, p.height, p.activity, p.clo, p.sex))


def saturation_vapour_pressure(ta: float) -> float:
    """hPa, Magnus formula over water."""
    return 6.112 * np.exp(17.62 * ta / (243.12 + ta))


def pet_hour_wind(
    tmrt: np.ndarray,
    wind: np.ndarray,
    ta: float,
    rh: float,
    person: Person = DEFAULT_PERSON,
    step: float = 0.5,
    wind_nodes: int = 18,
    dta: np.ndarray | None = None,
) -> np.ndarray:
    """PET for one hour with a pedestrian-level wind field (m/s at 1.1 m), and
    optionally a local air temperature offset ``dta`` (K) on the same grid."""
    if dta is not None:
        return _pet_hour_wind_dta(tmrt, wind, ta, rh, dta, person, step, wind_nodes)
    finite = np.isfinite(tmrt) & np.isfinite(wind)
    out = np.full(tmrt.shape, np.nan, dtype="float32")
    if not finite.any():
        return out
    t_nodes = np.arange(
        np.floor(tmrt[finite].min()) - step, np.ceil(tmrt[finite].max()) + step * 1.5, step
    )
    v_lo, v_hi = max(float(wind[finite].min()), 0.1), max(float(wind[finite].max()), 0.2)
    v_nodes = np.geomspace(v_lo * 0.99, v_hi * 1.01, wind_nodes)
    table = np.array([[pet_point_local(ta, rh, t, v, person) for v in v_nodes] for t in t_nodes])
    interp = RegularGridInterpolator((t_nodes, np.log(v_nodes)), table)
    out[finite] = interp(np.column_stack([tmrt[finite], np.log(wind[finite])]))
    return out


def _pet_hour_wind_dta(tmrt, wind, ta, rh, dta, person, step, wind_nodes, ta_nodes=3):
    finite = np.isfinite(tmrt) & np.isfinite(wind) & np.isfinite(dta)
    out = np.full(tmrt.shape, np.nan, dtype="float32")
    if not finite.any():
        return out
    t_nodes = np.arange(
        np.floor(tmrt[finite].min()) - step, np.ceil(tmrt[finite].max()) + step * 1.5, step
    )
    v_lo, v_hi = max(float(wind[finite].min()), 0.1), max(float(wind[finite].max()), 0.2)
    v_nodes = np.geomspace(v_lo * 0.99, v_hi * 1.01, wind_nodes)
    d_lo, d_hi = float(dta[finite].min()), float(dta[finite].max())
    d_nodes = np.linspace(d_lo - 0.01, d_hi + 0.01, ta_nodes)
    vapour = rh / 100 * saturation_vapour_pressure(ta)
    table = np.array([[[
        pet_point_local(ta + d, min(100.0, 100 * vapour / saturation_vapour_pressure(ta + d)), t, v, person)
        for d in d_nodes] for v in v_nodes] for t in t_nodes])
    interp = RegularGridInterpolator((t_nodes, np.log(v_nodes), d_nodes), table)
    out[finite] = interp(np.column_stack([tmrt[finite], np.log(wind[finite]), dta[finite]]))
    return out


def pet_day(
    tmrt: np.ndarray,
    met: np.ndarray,
    person: Person = DEFAULT_PERSON,
    wind10: np.ndarray | None = None,
    hours: range | None = None,
    dta: np.ndarray | None = None,
    dta_hours: range = range(13, 19),
) -> np.ndarray:
    """PET for every hour. ``tmrt`` is (hours, rows, cols); ``met`` is the UMEP met
    array SOLWEIG was run with (columns: 9 wind at 10 m, 10 RH, 11 air temperature).
    ``wind10`` is SOLWEIG-GPU's own 10 m wind field per hour (saved with save_wind,
    the station wind times the GLIDE-SOL coefficients); it is brought down to 1.1 m
    with UMEP's power law and floored at MIN_WIND. Without it the station wind is
    used everywhere. Hours outside ``hours`` (default all) are left as NaN. ``dta`` is a
    local air temperature offset (K, rows by cols) added in ``dta_hours`` (default the
    afternoon bands 13 to 18, the hours it was fitted for); it needs ``wind10``."""
    if tmrt.shape[0] != met.shape[0]:
        raise ValueError("Tmrt and met file have a different number of hours")
    hours = range(tmrt.shape[0]) if hours is None else hours
    out = np.full(tmrt.shape, np.nan, dtype="float32")
    for h in hours:
        ta, rh, ws = met[h, 11], met[h, 10], met[h, 9]
        if wind10 is None:
            out[h] = pet_hour(tmrt[h], ta, rh, ws, person)
        else:
            v = np.maximum(wind_at_pedestrian_height(1.0) * wind10[h], MIN_WIND)
            local = dta if (dta is not None and h in dta_hours) else None
            out[h] = pet_hour_wind(tmrt[h], v, ta, rh, person, dta=local)
    return out
