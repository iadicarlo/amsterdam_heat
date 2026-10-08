import numpy as np

from amsterdam_heat.pet import pet_hour, pet_hour_wind, pet_point, pet_point_local


def test_reference_room_gives_air_temperature():
    # PET is defined against a room with Tmrt = Ta and still air
    assert abs(pet_point(20.0, 50.0, 20.0, 0.1 / (1.1 / 10.0) ** 0.2) - 20.0) < 0.1


def test_more_radiation_feels_hotter():
    assert pet_point(30.0, 40.0, 65.0, 2.0) > pet_point(30.0, 40.0, 35.0, 2.0) + 5


def test_interpolation_matches_direct_solver():
    rng = np.random.default_rng(1)
    tmrt = rng.uniform(25, 70, size=(40, 40)).astype("float32")
    tmrt[0, 0] = np.nan
    ta, rh, ws = 33.0, 42.0, 3.0
    grid = pet_hour(tmrt, ta, rh, ws)
    assert np.isnan(grid[0, 0])
    idx = rng.integers(1, 40, size=(25, 2))
    direct = np.array([pet_point(ta, rh, float(tmrt[i, j]), ws) for i, j in idx])
    assert np.max(np.abs(grid[idx[:, 0], idx[:, 1]] - direct)) < 0.05


def test_wind_field_interpolation_matches_direct_solver():
    rng = np.random.default_rng(2)
    tmrt = rng.uniform(25, 70, size=(30, 30)).astype("float32")
    wind = rng.uniform(0.5, 4.0, size=(30, 30)).astype("float32")
    ta, rh = 32.0, 35.0
    grid = pet_hour_wind(tmrt, wind, ta, rh)
    idx = rng.integers(0, 30, size=(25, 2))
    direct = np.array([pet_point_local(ta, rh, float(tmrt[i, j]), float(wind[i, j])) for i, j in idx])
    assert np.max(np.abs(grid[idx[:, 0], idx[:, 1]] - direct)) < 0.15


def test_less_wind_feels_hotter():
    assert pet_point_local(32.0, 35.0, 60.0, 0.5) > pet_point_local(32.0, 35.0, 60.0, 3.0) + 2
