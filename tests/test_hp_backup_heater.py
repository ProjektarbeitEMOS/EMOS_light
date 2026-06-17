"""Tests fuer den eingebauten Heizstab (Backup-Heater) der Waermepumpe.

Auftraggeber-Hinweis (Juni 2026): Bei Extremszenarien (sehr kalt) haengt die
WP an ihrer Kennfeld-Kapazitaet und kann das Komfortband nicht halten. Der
eingebaute elektrische Heizstab (modulierbar, COP 1, max. 8,5 kW) soll dann
einspringen — im Normalbetrieb aber aus bleiben, weil WP-Waerme pro kWh
guenstiger ist.
"""

import copy
import datetime

import numpy as np

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)


TEST_DATE = datetime.date(2026, 1, 15)


def _cfg(outside_c: float, *, rod: bool = True, rod_max: float = 8.5) -> dict:
    """WP + FBH + Gebaeude, kein PV/Batterie/WW; konstante Aussentemp."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    for key in ("battery", "pv", "hot_water_storage", "fresh_water_station"):
        cfg.setdefault(key, {})["enabled"] = False
    cfg["heat_pump"]["enabled"] = True
    cfg["heat_pump"]["backup_heater_enabled"] = rod
    cfg["heat_pump"]["backup_heater_max_power_kw"] = rod_max
    cfg["underfloor_heating"]["enabled"] = True
    cfg["building"]["enabled"] = True
    cfg["building"]["comfort_temp_min_c"] = 21.0
    cfg["building"]["comfort_temp_max_c"] = 24.0
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    cfg["household"]["annual_consumption_kwh"] = 1000
    cfg["household"]["load_profile_id"] = ""
    cfg["_outside_c"] = outside_c
    return cfg


def _run(cfg):
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    data["temp"] = np.full_like(data["temp"], cfg["_outside_c"], dtype=float)
    inp = build_time_series_input(cfg, data)
    res = build_optimizer(build_components(cfg)).optimize(inp)
    return inp, res


def test_rod_off_in_normal_operation():
    """Bei milder Witterung (+8 °C) reicht die WP locker — der Heizstab muss
    komplett aus bleiben (WP-Waerme ist pro kWh guenstiger)."""
    _, res = _run(_cfg(8.0))
    assert res.success
    rod = np.asarray(res.hp_rod_power_kw)
    assert rod.size > 0
    assert float(rod.max()) <= 1e-6, (
        f"Heizstab lief im Normalbetrieb (max {rod.max():.3f} kW)"
    )


def test_rod_activates_in_extreme_cold():
    """Bei -15 °C haengt die WP an der Kennfeld-Kapazitaet — der Heizstab
    muss einspringen."""
    _, res = _run(_cfg(-15.0))
    assert res.success
    rod = np.asarray(res.hp_rod_power_kw)
    assert float(rod.max()) > 0.1, "Heizstab haette bei -15 °C anspringen muessen"


def test_rod_respects_max_power():
    """Heizstab-Leistung bleibt in der Box [0, max]."""
    rod_max = 8.5
    _, res = _run(_cfg(-15.0, rod_max=rod_max))
    rod = np.asarray(res.hp_rod_power_kw)
    assert float(rod.min()) >= -1e-6
    assert float(rod.max()) <= rod_max + 1e-6


def test_rod_improves_comfort_in_extreme_cold():
    """Mit Heizstab darf der Raum nicht kaelter werden als ohne, und es darf
    nicht mehr Komfort-Unterschreitungen geben — der Stab ist eine zusaetzliche
    Waermequelle, kann die Loesung also nur verbessern."""
    _, res_on = _run(_cfg(-15.0, rod=True))
    _, res_off = _run(_cfg(-15.0, rod=False))
    assert res_on.success and res_off.success

    cmin = 21.0
    tin_on = np.asarray(res_on.indoor_temp_c)
    tin_off = np.asarray(res_off.indoor_temp_c)
    viol_on = int(np.sum(tin_on < cmin - 1e-6))
    viol_off = int(np.sum(tin_off < cmin - 1e-6))

    # Ohne Stab muss er wirklich 0 sein (Regression der Abschaltlogik).
    assert float(np.asarray(res_off.hp_rod_power_kw).max()) <= 1e-6
    # Der Stab lief im On-Fall.
    assert float(np.asarray(res_on.hp_rod_power_kw).max()) > 0.1
    # Komfort wird nicht schlechter: weniger (oder gleich viele) Verletzungen
    # und der Tiefpunkt liegt nicht unter dem Ohne-Stab-Fall.
    assert viol_on <= viol_off
    assert tin_on.min() >= tin_off.min() - 1e-6
