"""Write a UMEP style hourly forcing file from KNMI station data.

KNMI reports hour HH as the hour ending at HH UT. SOLWEIG-GPU expects local
clock time (it looks up the time zone from the raster location), so hours are
shifted to Europe/Amsterdam and labelled by the end of the hour, as UMEP does.
SOLWEIG-GPU wants hours 0 to 23 within one date, so the file holds the hours
ending at 00:00 up to 23:00 local time on that date.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

UMEP_HEADER = (
    "%iy id it imin qn qh qe qs qf U RH Tair pres rain kdown snow ldown fcld wuh xsmd lai "
    "kdiff kdir wdir"
)
TZ = ZoneInfo("Europe/Amsterdam")


def knmi_to_umep(knmi_json: Path, local_date: str, out: Path) -> Path:
    """Keep the 24 hours of ``local_date`` (YYYY-MM-DD) and write them in UMEP format."""
    rows = []
    for rec in json.loads(knmi_json.read_text()):
        end_utc = datetime.fromisoformat(rec["date"]) + timedelta(hours=rec["hour"])
        label = end_utc.astimezone(TZ)
        if label.date().isoformat() != local_date:
            continue
        hour = label.hour
        doy = label.timetuple().tm_yday
        rows.append(
            [
                label.year, doy, hour, 0,
                -999, -999, -999, -999, -999,
                max(rec["FH"] / 10.0, 0.5),  # wind (m/s), floor avoids a calm singularity
                rec["U"],                    # relative humidity (%)
                rec["T"] / 10.0,             # air temperature (C)
                rec["P"] / 100.0,            # pressure (kPa)
                0,
                rec["Q"] * 1e4 / 3600.0,     # global radiation J/cm2 per hour to W/m2
                -999, -999, -999, -999, -999, -999,
                -999, -999,
                rec["DD"] if 0 < rec["DD"] <= 360 else -999,
            ]
        )
    if len(rows) != 24:
        raise ValueError(f"expected 24 hours for {local_date}, got {len(rows)}")
    rows.sort(key=lambda r: r[2])
    fmt = ["%d", "%d", "%d", "%d"] + ["%.2f"] * 20
    np.savetxt(out, np.array(rows, dtype=float), fmt=fmt, header=UMEP_HEADER[1:], comments="%")
    return out
