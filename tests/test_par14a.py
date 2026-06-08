"""Tests fuer die §14a-EnWG-Netzdrosselung (Testszenario).

Prueft sowohl die Fensterberechnung (_par14a_curtailed_steps) als auch,
dass der Drossel-Constraint im Optimizer im Fenster bindet.
"""

import copy
import datetime

import numpy as np
import pytest

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    _par14a_curtailed_steps,
    build_components,
    build_optimizer,
    build_time_series_input,
    load_input_data,
)


TEST_DATE = datetime.date(2026, 1, 15)


def _ts(n: int, step_min: int = 15) -> list:
    base = datetime.datetime.combine(TEST_DATE, datetime.time())
    return [base + datetime.timedelta(minutes=i * step_min) for i in range(n)]


# ---------------------------------------------------------------------------
# Fensterberechnung
# ---------------------------------------------------------------------------

def test_curtailed_steps_disabled_is_empty():
    cfg = {"par14a": {"enabled": False, "curtail_start_hour": 8,
                      "curtail_end_hour": 16}}
    assert _par14a_curtailed_steps(cfg, _ts(96)) == []


def test_curtailed_steps_equal_hours_is_empty():
    cfg = {"par14a": {"enabled": True, "curtail_start_hour": 10,
                      "curtail_end_hour": 10}}
    assert _par14a_curtailed_steps(cfg, _ts(96)) == []


def test_curtailed_steps_normal_window():
    # 8:00-16:00 bei 15-min-Schritten = Schritte 32..63 (32 Stueck)
    cfg = {"par14a": {"enabled": True, "curtail_start_hour": 8,
                      "curtail_end_hour": 16}}
    steps = _par14a_curtailed_steps(cfg, _ts(96))
    assert steps[0] == 32
    assert steps[-1] == 63
    assert len(steps) == 32


def test_curtailed_steps_overnight_wrap():
    # 22:00-6:00 ueber Mitternacht
    cfg = {"par14a": {"enabled": True, "curtail_start_hour": 22,
                      "curtail_end_hour": 6}}
    steps = set(_par14a_curtailed_steps(cfg, _ts(96)))
    assert 88 in steps and 95 in steps        # 22:00, 23:45
    assert 0 in steps and 23 in steps         # 00:00, 05:45
    assert 24 not in steps and 87 not in steps  # 06:00, 21:45 ausserhalb


# ---------------------------------------------------------------------------
# Constraint im Optimizer
# ---------------------------------------------------------------------------

def _winter_cfg() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    for k in ("battery", "pv", "hot_water_storage", "fresh_water_station"):
        cfg.setdefault(k, {})["enabled"] = False
    cfg["heat_pump"]["enabled"] = True
    cfg["underfloor_heating"]["enabled"] = True
    cfg["building"]["enabled"] = True
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    cfg["household"]["annual_consumption_kwh"] = 1000
    cfg["household"]["load_profile_id"] = ""
    # Gewinne aus, damit die WP-Last hoch genug bleibt, dass der §14a-Cap
    # im Fenster wirklich bindet (sonst senken die Gewinne die WP-Last).
    cfg["building"]["solar_gains_enabled"] = False
    cfg["building"]["internal_gains_w_per_m2"] = 0.0
    return cfg


def test_curtailment_binds_during_window():
    """Gedrosselt: WP-Leistung <= cap im Fenster; ungedrosselt zog die WP
    im selben Fenster mehr -> der Constraint ist also wirklich restriktiv."""
    # Gemeinsame Wetterdaten (-5 °C konstant, damit die WP heizen muss).
    base = _winter_cfg()
    data = load_input_data(base, TEST_DATE)
    data["temp"] = np.full_like(data["temp"], -5.0, dtype=float)

    # Referenz ohne Drosselung
    inp_free = build_time_series_input(base, data)
    res_free = build_optimizer(build_components(base)).optimize(inp_free)
    assert res_free.success
    assert inp_free.par14a_curtailed_steps == []

    # Mit Drosselung auf 2 kW zwischen 8 und 16 Uhr
    cfg = _winter_cfg()
    cfg["par14a"] = {"enabled": True, "curtailment_kw": 2.0,
                     "curtail_start_hour": 8, "curtail_end_hour": 16}
    inp = build_time_series_input(cfg, data)
    res = build_optimizer(build_components(cfg)).optimize(inp)
    assert res.success

    steps = inp.par14a_curtailed_steps
    assert len(steps) == 32

    hp = np.array(res.hp_power_kw)
    hp_free = np.array(res_free.hp_power_kw)
    # Im Fenster auf den Cap begrenzt (kleine Toleranz fuer MIP-Gap).
    assert hp[steps].max() <= 2.0 + 1e-4, (
        f"WP zieht {hp[steps].max():.3f} kW > cap 2.0 kW im Drosselfenster"
    )
    # Ungedrosselt wollte die WP im selben Fenster mehr -> Cap ist bindend.
    assert hp_free[steps].max() > 2.0 + 0.1, (
        "Referenzlauf zog im Fenster nicht mehr als den Cap — Test waere "
        "sonst trivial erfuellt."
    )
