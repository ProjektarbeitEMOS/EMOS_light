"""Tests fuer die dynamische WP-Max-Leistung (Mai 2026).

Die maximale elektrische Leistung der Waermepumpe haengt von der
Aussentemperatur ab — vorher war ein statischer Wert aus der Config
gebunden, jetzt wird er per Zeitschritt aus dem Kennfeld berechnet
(``calculate_max_electrical_power``).
"""

import copy
import datetime

import numpy as np

from emos_light.components.heat_pump import HeatPump
from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)


def _winter_cfg(t_out: float | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    return cfg


def _run(cfg, t_out: float | None = None):
    data = load_input_data(cfg, datetime.date(2026, 1, 15), use_api=False)
    if t_out is not None:
        data["temp"] = np.full_like(data["temp"], t_out, dtype=float)
    inp = build_time_series_input(cfg, data)
    res = build_optimizer(build_components(cfg)).optimize(inp)
    return res


# ---------------------------------------------------------------------------
# Methodentest: calculate_max_electrical_power
# ---------------------------------------------------------------------------

def test_max_electrical_power_decreases_with_warmer_temps():
    """Bei waermerer Aussentemperatur sinkt die WP-Max-Leistung
    (weil die thermische Leistung sinkt, auch wenn der COP steigt)."""
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    temps = np.array([-7.0, 2.0, 7.0])
    p_max = hp.calculate_max_electrical_power(temps)
    # Monoton fallend von kalt zu warm
    assert p_max[0] > p_max[1] > p_max[2], (
        f"P_el_max nicht monoton fallend: {p_max}"
    )


def test_max_electrical_power_clipped_at_static_max():
    """Die dynamische Max-Leistung darf nie ueber ``max_electrical_power_kw``
    hinausgehen — das ist die Hardware-Modulationsobergrenze."""
    hp = HeatPump("hp", {
        **DEFAULT_CONFIG["heat_pump"],
        "max_electrical_power_kw": 2.0,  # absichtlich niedrig
    })
    temps = np.array([-15.0, -7.0, 2.0, 7.0, 20.0])
    p_max = hp.calculate_max_electrical_power(temps)
    assert (p_max <= 2.0 + 1e-9).all()


def test_max_electrical_power_has_correct_length():
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    temps = np.linspace(-10.0, 20.0, 96)
    p_max = hp.calculate_max_electrical_power(temps)
    assert len(p_max) == 96


# ---------------------------------------------------------------------------
# Solver-Test: das Constraint hp_power[t] <= P_el_max(t) * hp_on[t] greift
# ---------------------------------------------------------------------------

def test_solver_respects_dynamic_max_power():
    """Im optimierten Result ueberschreitet hp_power_kw nie hp_max_power_kw."""
    res = _run(_winter_cfg(), t_out=-5.0)
    assert res.success
    assert len(res.hp_max_power_kw) == len(res.hp_power_kw)
    # WP-Power darf nie groesser als dyn. Max sein
    assert (res.hp_power_kw <= res.hp_max_power_kw + 1e-6).all()


def test_dynamic_max_below_static_config_value():
    """Bei warmem Aussenklima (T_out = +15 C) ist die dyn. Max-Leistung
    deutlich unter dem Config-Wert von 8 kW — Kennfeld-realistisch."""
    res = _run(_winter_cfg(), t_out=15.0)
    assert res.success
    assert res.hp_max_power_kw.max() < 3.0  # statt der 8 kW Config-Default


def test_hp_max_power_result_field_populated():
    """Das Result-Feld muss in jedem Optimierungslauf befuellt sein
    (nicht-leerer Array, gleiche Laenge wie hp_power_kw)."""
    res = _run(_winter_cfg(), t_out=2.0)
    assert res.success
    assert isinstance(res.hp_max_power_kw, np.ndarray)
    assert len(res.hp_max_power_kw) > 0
    assert len(res.hp_max_power_kw) == len(res.hp_power_kw)
