import json

import numpy as np

from amsterdam_heat.metfile import knmi_to_umep


def _knmi_record(day: str, hour: int, temp: float) -> dict:
    return {"station_code": 240, "date": f"{day}T00:00:00.000Z", "hour": hour,
            "DD": 90, "FH": 30, "T": int(temp * 10), "Q": 100, "P": 10150, "U": 50}


def test_local_hours_and_units(tmp_path):
    # summer time: local = UT + 2, so local hours 0..23 on 25 July end at
    # 22 UT on the 24th up to 21 UT on the 25th
    recs = [_knmi_record("2019-07-24", h, 20.0) for h in range(20, 25)]
    recs += [_knmi_record("2019-07-25", h, 30.0) for h in range(1, 25)]
    src = tmp_path / "knmi.json"
    src.write_text(json.dumps(recs))
    out = knmi_to_umep(src, "2019-07-25", tmp_path / "met.txt")

    data = np.loadtxt(out, skiprows=1, delimiter=" ")
    assert data.shape == (24, 24)
    assert list(data[:, 2]) == list(range(24))
    # local 00:00, 01:00 and 02:00 are the hours ending 22, 23 and 24 UT on the 24th
    assert list(data[:3, 11]) == [20.0, 20.0, 20.0]
    assert data[3, 11] == 30.0
    np.testing.assert_allclose(data[:, 14], 100 * 1e4 / 3600, atol=0.01)  # J/cm2 per hour to W/m2
    np.testing.assert_allclose(data[:, 12], 101.5)  # kPa
