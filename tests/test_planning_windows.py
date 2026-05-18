"""Tests fuer die ``planning_windows``-Result-Felder.

Damit das Dashboard fuer alle drei Optimierungsmodi (Day-Ahead, MPC,
Baseline) dieselbe Visualisierung des Planungshorizonts zeichnen kann,
fuellen alle drei Pfade ein gemeinsames Schema:

    [{"start_step": int, "exec_end_step": int, "horizon_end_step": int}, ...]
"""

import copy
import datetime

import numpy as np
import pytest

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    build_time_series_input,
    load_input_data,
)
from emos_light.optimization.baseline import run_baseline
from emos_light.optimization.mpc import MPCController

from .conftest import cfg_battery_only, cfg_full_house, TEST_DATE


def _input_for(cfg):
    data = load_input_data(cfg, TEST_DATE)
    return build_time_series_input(cfg, data)


# ---------------------------------------------------------------------------
# Day-Ahead (MILP): ein einziges Fenster ueber den gesamten Horizont
# ---------------------------------------------------------------------------

def test_day_ahead_returns_single_full_window():
    cfg = cfg_battery_only()
    inp = _input_for(cfg)
    res = build_optimizer(build_components(cfg)).optimize(inp)
    assert res.success
    assert len(res.planning_windows) == 1
    w = res.planning_windows[0]
    n = len(inp.prices_ct_kwh)
    assert w["start_step"] == 0
    assert w["exec_end_step"] == n
    assert w["horizon_end_step"] == n


# ---------------------------------------------------------------------------
# Baseline: ebenfalls ein einziges Fenster, deckungsgleich
# ---------------------------------------------------------------------------

def test_baseline_returns_single_full_window():
    cfg = cfg_full_house()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)
    assert res.success
    assert len(res.planning_windows) == 1
    w = res.planning_windows[0]
    n = len(inp.prices_ct_kwh)
    assert w["start_step"] == 0
    assert w["exec_end_step"] == n
    assert w["horizon_end_step"] == n


# ---------------------------------------------------------------------------
# MPC: ein Fenster pro Iteration, mit Lookahead ueber das Ausfuehrungsfenster
# ---------------------------------------------------------------------------

def _mpc_cfg() -> dict:
    """48h-Horizont + WP/PV/Batterie, damit der MPC mehrere Iterationen macht."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 48
    for key in ("battery", "heat_pump", "pv",
                "hot_water_storage", "fresh_water_station",
                "underfloor_heating"):
        cfg.setdefault(key, {})["enabled"] = True
    cfg["building"]["enabled"] = False
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    return cfg


def test_mpc_populates_planning_windows():
    cfg = _mpc_cfg()
    inp = _input_for(cfg)
    optimizer = build_optimizer(build_components(cfg))
    mpc = MPCController(optimizer, horizon_hours=None, execute_hours=6)
    res = mpc.run_mpc(inp)
    assert res.success
    assert len(res.planning_windows) >= 2  # mehrere Iterationen bei 48h/6h

    n = len(inp.prices_ct_kwh)
    for w in res.planning_windows:
        assert 0 <= w["start_step"] < w["exec_end_step"]
        assert w["exec_end_step"] <= w["horizon_end_step"] <= n


def test_mpc_windows_cover_full_input_contiguously():
    """Aufeinanderfolgende Fenster muessen ohne Luecke aneinanderhaengen
    (exec_end[i] == start[i+1]) und am Ende den ganzen Input abdecken."""
    cfg = _mpc_cfg()
    inp = _input_for(cfg)
    optimizer = build_optimizer(build_components(cfg))
    mpc = MPCController(optimizer, horizon_hours=None, execute_hours=6)
    res = mpc.run_mpc(inp)
    assert res.success

    windows = res.planning_windows
    assert windows[0]["start_step"] == 0
    for w_a, w_b in zip(windows, windows[1:]):
        assert w_a["exec_end_step"] == w_b["start_step"], (
            "Ausfuehrungsfenster muessen ohne Luecke aneinander stossen"
        )
    assert windows[-1]["exec_end_step"] == len(inp.prices_ct_kwh)


def test_mpc_lookahead_extends_beyond_exec():
    """Mindestens das erste Fenster soll einen echten Lookahead haben —
    sonst waere der MPC ein klassischer rollierender Solver ohne Vorausschau."""
    cfg = _mpc_cfg()
    inp = _input_for(cfg)
    optimizer = build_optimizer(build_components(cfg))
    mpc = MPCController(optimizer, horizon_hours=None, execute_hours=1)
    res = mpc.run_mpc(inp)
    assert res.success

    # Erstes Fenster sollte deutlich ueber das 1h-Ausfuehrungsfenster
    # hinausschauen (mindestens "bis Tagesende" — also ein paar Stunden).
    w0 = res.planning_windows[0]
    lookahead_steps = w0["horizon_end_step"] - w0["exec_end_step"]
    assert lookahead_steps > 0, (
        "Erstes MPC-Fenster muss einen Planungs-Lookahead haben"
    )
