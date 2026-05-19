"""Tests: EV-Ziel-SOC muss zur Abfahrt erreicht sein, nicht erst am
Horizont-Ende. Pro Stunde Abwesenheit wird ein konstanter Fahrver-
brauch (Default 5 % der EV-Kapazitaet) als SOC-Verlust modelliert.

Bisheriges Verhalten (Bug): die Wallbox-Komponente hat nur eine
Mindest-Gesamtlademenge ueber den Horizont erzwungen — der Solver
konnte daher das Laden bis nach der Abfahrt verschieben. Mit dem
SOC-Tracking pro Zeitschritt (siehe Wallbox.add_constraints) wird
``target_soc`` am letzten Schritt VOR der Abfahrt erzwungen und der
EV-SOC sinkt waehrend Abwesenheit deterministisch.
"""

import copy
import datetime
from typing import Tuple

import numpy as np
import pytest

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)
from emos_light.optimization.baseline import run_baseline


TEST_DATE = datetime.date(2026, 5, 19)


def _wb_cfg(arrival: int = 18, departure: int = 7) -> dict:
    """Wallbox mit 60 kWh EV, 11 kW max, 30% Start-SOC, 80% Ziel,
    Abfahrt morgens um ``departure``, Ankunft abends um ``arrival``."""
    return {
        "name": "wb1", "enabled": True,
        "max_power_kw": 11.0, "min_power_kw": 4.2, "phases": 3,
        "ev_battery_capacity_kwh": 60.0,
        "current_soc": 0.30, "target_soc": 0.80, "max_soc": 1.0,
        "arrival_hour": arrival, "departure_hour": departure,
        "charging_efficiency": 0.92,
        "driving_loss_pct_per_hour": 5.0,
    }


def _cfg_pv_wb(arrival: int = 18, departure: int = 7) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    for key in ("battery", "heat_pump",
                "hot_water_storage", "fresh_water_station",
                "underfloor_heating", "building"):
        cfg.setdefault(key, {})["enabled"] = False
    cfg["pv"]["enabled"] = True
    cfg["wallboxes"] = [_wb_cfg(arrival=arrival, departure=departure)]
    cfg["electric_vehicles"] = []
    return cfg


def _run(cfg) -> Tuple:
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    inp = build_time_series_input(cfg, data)
    res = build_optimizer(build_components(cfg)).optimize(inp)
    return inp, res


# ---------------------------------------------------------------------------
# MILP: Ziel-SOC bei Abfahrt
# ---------------------------------------------------------------------------

def test_milp_reaches_target_soc_by_departure():
    """Bei Abfahrt um 7:00 muss soc[step der Abfahrt] >= target * cap."""
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    inp, res = _run(cfg)
    assert res.success

    soc = res.ev_soc_kwh["wb1"]
    target_kwh = 0.80 * 60.0
    # Abfahrtsstunde 7:00 entspricht Step 7 * 60 / 15 = 28 (15-min steps).
    # An genau diesem Schritt MUSS der SOC mind. target sein.
    dep_step = 7 * 4
    assert soc[dep_step] >= target_kwh - 0.01, (
        f"SOC bei Abfahrt = {soc[dep_step]:.2f} kWh, "
        f"erwartet >= {target_kwh:.2f} kWh"
    )


def test_milp_soc_drops_during_absence():
    """Waehrend der Abwesenheit (7..18) sinkt der SOC um 5 % / h."""
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    _, res = _run(cfg)
    assert res.success

    soc = res.ev_soc_kwh["wb1"]
    # Step 28 = 7:00 (Abfahrt), Step 72 = 18:00 (Ankunft)
    soc_at_dep = soc[28]
    soc_at_arr = soc[72]
    hours_away = 11
    expected_loss = 0.05 * 60.0 * hours_away  # 33 kWh
    actual_loss = soc_at_dep - soc_at_arr
    assert abs(actual_loss - expected_loss) < 0.5, (
        f"Verlust = {actual_loss:.2f} kWh, erwartet {expected_loss:.2f} kWh"
    )


def test_milp_does_not_charge_during_absence():
    """Waehrend Abwesenheit darf Wallbox keine Leistung ziehen."""
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    _, res = _run(cfg)
    assert res.success

    p = res.wallbox_power_kw["wb1"]
    # Steps 28..71 (Abfahrt 7:00 bis Ankunft 18:00 exklusiv)
    assert np.all(p[28:72] == 0), "Wallbox laedt waehrend Abwesenheit"


def test_milp_zero_driving_loss_means_soc_stays_constant_during_absence():
    """Mit ``driving_loss_pct_per_hour = 0`` muss der SOC waehrend der
    Abwesenheit konstant bleiben."""
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    cfg["wallboxes"][0]["driving_loss_pct_per_hour"] = 0.0
    _, res = _run(cfg)
    assert res.success

    soc = res.ev_soc_kwh["wb1"]
    soc_at_dep = soc[28]
    soc_at_arr = soc[72]
    assert abs(soc_at_dep - soc_at_arr) < 0.01, (
        "Ohne Fahrverbrauch sollte der SOC waehrend der Fahrt konstant sein"
    )


def test_milp_custom_loss_rate_respected():
    """Bei 8 %/h Fahrverbrauch sinkt der SOC fast doppelt so schnell.
    Wichtig: der totale Verlust muss innerhalb der Akkugrenze bleiben,
    sonst meldet der Solver Infeasibility (siehe naechster Test)."""
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    cfg["wallboxes"][0]["driving_loss_pct_per_hour"] = 8.0
    _, res = _run(cfg)
    assert res.success

    soc = res.ev_soc_kwh["wb1"]
    actual_loss = soc[28] - soc[72]  # 11 h Abwesenheit
    expected_loss = 0.08 * 60.0 * 11  # 52.8 kWh — passt noch in 60 kWh
    assert abs(actual_loss - expected_loss) < 0.5, (
        f"Verlust = {actual_loss:.2f} kWh, erwartet {expected_loss:.2f} kWh"
    )


def test_milp_infeasible_when_driving_loss_exceeds_capacity():
    """Bei 10 %/h * 11 h = 110 % Kapazitaetsverlust kann der Akku-Bound
    (soc >= 0) nicht eingehalten werden — der Solver meldet zu Recht
    Infeasibility. Das ist die korrekte Reaktion: das User-Setup ist
    physikalisch unmoeglich (Auto muesste mit negativem Akku zurueck-
    kommen)."""
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    cfg["wallboxes"][0]["driving_loss_pct_per_hour"] = 10.0
    _, res = _run(cfg)
    assert not res.success
    assert "Infeasible" in res.solver_status


# ---------------------------------------------------------------------------
# Baseline: gleiche Modellannahmen
# ---------------------------------------------------------------------------

def test_baseline_tracks_soc_during_absence():
    """Auch die Baseline verliert 5 %/h waehrend der Fahrt — sonst waere
    der Vergleich mit dem MILP-Pfad unfair (Baseline haette ein freies
    'Lunchpaket')."""
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    inp = build_time_series_input(cfg, data)
    res = run_baseline(inp, cfg)

    soc = res.ev_soc_kwh["wb1"]
    soc_at_dep = soc[28]
    soc_at_arr = soc[72]
    hours_away = 11
    expected_loss = 0.05 * 60.0 * hours_away  # 33 kWh
    actual_loss = soc_at_dep - soc_at_arr
    # In der Baseline laedt das Auto ab Ankunft (18:00) sofort mit voller
    # Leistung, daher SOC bei Abfahrt nahe 1.0 * 60 kWh. Der Verlust bis
    # Ankunft passt aber: 5 %/h * 11 h = 55 % von 60 = 33 kWh.
    assert abs(actual_loss - expected_loss) < 0.5, (
        f"Baseline-Verlust = {actual_loss:.2f} kWh, erwartet {expected_loss:.2f} kWh"
    )


def test_baseline_does_not_charge_during_absence():
    cfg = _cfg_pv_wb(arrival=18, departure=7)
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    inp = build_time_series_input(cfg, data)
    res = run_baseline(inp, cfg)
    p = res.wallbox_power_kw["wb1"]
    assert np.all(p[28:72] == 0)


# ---------------------------------------------------------------------------
# Konsistenz Result-Schema
# ---------------------------------------------------------------------------

def test_ev_soc_kwh_has_full_horizon_length():
    cfg = _cfg_pv_wb()
    _, res = _run(cfg)
    assert "wb1" in res.ev_soc_kwh
    assert len(res.ev_soc_kwh["wb1"]) == len(res.timestamps)
