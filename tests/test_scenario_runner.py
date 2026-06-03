import datetime as dt
from types import SimpleNamespace

import numpy as np

from emos_light.testing.scenario_runner import _build_series, evaluate_checks


def _timestamps():
    start = dt.datetime(2026, 1, 1)
    return [start + dt.timedelta(minutes=15 * i) for i in range(96)]


def test_build_series_applies_time_windows():
    series = _build_series(
        {
            "default": 10,
            "windows": [
                {"start": "02:00", "end": "04:00", "value": -5},
            ],
        },
        _timestamps(),
        96,
    )

    assert series[0] == 10
    assert np.all(series[8:16] == -5)
    assert series[16] == 10


def test_build_series_supports_wrapping_time_window():
    series = _build_series(
        {
            "default": 1,
            "windows": [
                {"start": "22:00", "end": "02:00", "value": 7},
            ],
        },
        _timestamps(),
        96,
    )

    assert np.all(series[:8] == 7)
    assert np.all(series[88:] == 7)
    assert series[40] == 1


def test_evaluate_checks_resolves_dict_fields_and_window_sum():
    result = SimpleNamespace(
        success=True,
        wallbox_power_kw={"Wallbox 1": np.ones(96) * 2.0},
        batt_charge_kw=np.zeros(96),
        batt_discharge_kw=np.zeros(96),
    )
    inp = SimpleNamespace(timestamps=_timestamps(), step_minutes=15)

    checks = evaluate_checks(
        result,
        inp,
        {},
        [
            {"type": "success", "expected": True},
            {
                "type": "window_sum",
                "field": "wallbox_power_kw.Wallbox 1",
                "start": "01:00",
                "end": "03:00",
                "op": "==",
                "value": 4.0,
                "tolerance": 1e-9,
            },
            {"type": "no_simultaneous_battery"},
        ],
    )

    assert all(check.passed for check in checks)
