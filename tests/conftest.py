"""Gemeinsame Fixtures fuer EMOS Light Tests.

Stellt vier wiederverwendbare Szenarien bereit, die wir fuer Regression
und Smoketests gleichermassen brauchen. Wenn Tests neue Eingaben oder
Konfigurationen brauchen, gehoeren die hier rein — nicht in die einzelnen
Tests.
"""

import copy
import datetime
from typing import Callable

import pytest

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    build_time_series_input,
    load_input_data,
)


TEST_DATE = datetime.date(2026, 4, 15)


def _base_cfg() -> dict:
    """Liefert ein minimales DEFAULT_CONFIG-Derivat ohne Wallboxen/EVs."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    return cfg


def _enable_only(cfg: dict, *names: str) -> dict:
    """Schaltet alle Komponenten aus und nur die genannten ein."""
    for key in ("battery", "heat_pump", "pv", "hot_water_storage",
                "fresh_water_station", "underfloor_heating"):
        cfg.setdefault(key, {})["enabled"] = key in names
    return cfg


def _wallbox_config(name: str = "wb1") -> dict:
    return {
        "name": name, "enabled": True,
        "max_power_kw": 11.0, "min_power_kw": 4.2, "phases": 3,
        "ev_battery_capacity_kwh": 60.0,
        "current_soc": 0.3, "target_soc": 0.8,
        "departure_hour": 7, "arrival_hour": 17,
        "charging_efficiency": 0.92,
    }


# ---------------------------------------------------------------------------
# Szenario-Fabriken — jeweils eine Funktion, die ein fertiges cfg-Dict liefert
# ---------------------------------------------------------------------------

def cfg_battery_only() -> dict:
    cfg = _enable_only(_base_cfg(), "battery", "pv")
    cfg["heat_pump"]["enabled"] = False
    cfg["pv"]["enabled"] = True
    return cfg


def cfg_hp_ww() -> dict:
    cfg = _enable_only(_base_cfg(), "heat_pump", "hot_water_storage",
                       "fresh_water_station")
    return cfg


def cfg_hp_ufh() -> dict:
    cfg = _enable_only(_base_cfg(), "heat_pump", "underfloor_heating")
    return cfg


def cfg_wallbox_only() -> dict:
    cfg = _enable_only(_base_cfg(), "pv")
    cfg["wallboxes"] = [_wallbox_config()]
    return cfg


def cfg_full_house() -> dict:
    cfg = _enable_only(
        _base_cfg(),
        "battery", "heat_pump", "pv",
        "hot_water_storage", "fresh_water_station", "underfloor_heating",
    )
    cfg["wallboxes"] = [_wallbox_config()]
    return cfg


# ---------------------------------------------------------------------------
# Pytest-Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_date() -> datetime.date:
    return TEST_DATE


@pytest.fixture
def make_optimizer_run() -> Callable:
    """Liefert eine Helper-Funktion, die ein cfg in ein OptimizationResult dreht."""
    def _run(cfg: dict, date: datetime.date = TEST_DATE):
        data = load_input_data(cfg, date)
        inp = build_time_series_input(cfg, data)
        comps = build_components(cfg)
        opt = build_optimizer(comps)
        return opt.optimize(inp)
    return _run
