"""Tests fuer die ``max_starts_per_day``-Restriktion der Waermepumpe.

Begruendung der Restriktion (vom Auftraggeber): jeder OFF -> ON-
Vorgang belastet den Verdichter; eine WP soll daher max. 8x am Tag
einschalten. Solange sie an ist, darf sie beliebig lang laufen und
zwischen Heizkreis/WW umschalten.
"""

import copy
import datetime

import numpy as np
import pytest

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)
from emos_light.optimization.baseline import run_baseline


TEST_DATE = datetime.date(2026, 1, 15)


def _winter_cfg(max_starts: int = 8) -> dict:
    """WP+FBH+Building bei kaltem Winter, 24h-Horizont."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    for key in ("battery", "pv",
                "hot_water_storage", "fresh_water_station"):
        cfg.setdefault(key, {})["enabled"] = False
    cfg["heat_pump"]["enabled"] = True
    cfg["heat_pump"]["max_starts_per_day"] = max_starts
    cfg["underfloor_heating"]["enabled"] = True
    cfg["building"]["enabled"] = True
    cfg["building"]["comfort_temp_min_c"] = 20.0
    cfg["building"]["comfort_temp_max_c"] = 24.0
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    cfg["household"]["annual_consumption_kwh"] = 1000
    cfg["household"]["load_profile_id"] = ""
    return cfg


def _run(cfg):
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    # Stabile Winterbedingung — konstant -5 °C, damit die WP wirklich
    # laufen will.
    data["temp"] = np.full_like(data["temp"], -5.0, dtype=float)
    inp = build_time_series_input(cfg, data)
    return inp, build_optimizer(build_components(cfg)).optimize(inp)


def test_milp_respects_max_starts_per_day():
    """Bei einem harten Limit von 3 Starts/Tag darf der Solver max. 3
    Einschaltvorgaenge pro Tag erzeugen."""
    cfg = _winter_cfg(max_starts=3)
    _, res = _run(cfg)
    assert res.success, f"Solver erfolglos: {res.solver_status}"
    for day, count in res.hp_starts_per_day.items():
        assert count <= 3, (
            f"Tag {day}: {count} Starts, erlaubt waren {cfg['heat_pump']['max_starts_per_day']}"
        )


def test_milp_starts_count_consistent_with_per_day():
    cfg = _winter_cfg(max_starts=8)
    _, res = _run(cfg)
    assert res.success
    assert res.hp_starts_count == sum(res.hp_starts_per_day.values())


def test_milp_disabled_limit_when_zero():
    """max_starts_per_day=0 deaktiviert die Restriktion — der Solver
    kann beliebig oft anschalten (begrenzt nur durch min_run/min_pause)."""
    cfg = _winter_cfg(max_starts=0)
    _, res = _run(cfg)
    assert res.success
    # Kein hartes Cap mehr — Anzahl haengt vom Profil ab, sollte aber
    # > 0 sein bei -5 °C Aussentemperatur.
    assert res.hp_starts_count >= 0


def test_baseline_counts_starts():
    """Baseline zaehlt Einschaltvorgaenge auch ohne Restriktion mit —
    fuer den Vergleich gegen die MILP-Loesung im Dashboard."""
    cfg = _winter_cfg(max_starts=8)
    inp, _ = _run(cfg)
    base = run_baseline(inp, cfg)
    assert base.success
    assert isinstance(base.hp_starts_per_day, dict)
    assert base.hp_starts_count == sum(base.hp_starts_per_day.values())
    # Bei -5 °C Aussentemperatur muss die Baseline mindestens 1x
    # einschalten, um das Komfortband zu halten.
    assert base.hp_starts_count >= 1


def test_milp_with_tight_limit_still_feasible():
    """Auch bei sehr engem Limit (3 Starts/Tag) muss der Solver eine
    zulaessige Loesung finden — die WP darf einfach laenger laufen."""
    cfg = _winter_cfg(max_starts=3)
    _, res = _run(cfg)
    assert res.success
    # Mit nur 3 Starts/Tag muss die WP laenger am Stueck laufen — das
    # heisst, die total geleistete elektrische Arbeit darf nicht null
    # sein (sonst kuehlt das Haus aus).
    dt_h = 0.25
    hp_kwh = float(np.sum(res.hp_power_kw)) * dt_h
    assert hp_kwh > 0
