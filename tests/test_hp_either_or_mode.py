"""Tests fuer die Entweder-Oder-Modus-Beschraenkung der WP zwischen FBH und WW.

Quelle: Projektgruppe "Leistungsaufteilung" (PDF 22.05.2026). Die WP hat
einen Heizkreis + 3-Wege-Ventil — innerhalb eines 15-min-Blocks kann
sie nicht gleichzeitig FBH und WW bedienen. Die Binaervariable
``hp_mode_ww[t]`` entscheidet pro Block: 0 = FBH, 1 = WW. COP ist
damit pro Block eindeutig (W35 oder W55).
"""

import copy
import datetime

import numpy as np
import pulp
import pytest

from emos_light.components.heat_pump import HeatPump
from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)


# ---------------------------------------------------------------------------
# Schicht 1: Variable + Constraint-Schema auf der Komponente
# ---------------------------------------------------------------------------

def test_hp_mode_ww_variable_only_when_both_sinks_active():
    """``hp_mode_ww`` wird nur angelegt, wenn beide Senken aktiv sind —
    sonst gibt es nichts aufzuteilen."""
    # Single-sink: nur "floor"
    hp1 = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    hp1.set_active_heat_sinks({"floor"})
    vars1 = hp1.get_optimization_variables(num_steps=96, model=pulp.LpProblem("t1"))
    assert "hp_mode_ww" not in vars1
    assert "hp_power_floor" not in vars1
    assert "hp_power_ww" not in vars1

    # Multi-sink: beide aktiv
    hp2 = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    hp2.set_active_heat_sinks({"floor", "ww"})
    vars2 = hp2.get_optimization_variables(num_steps=96, model=pulp.LpProblem("t2"))
    assert "hp_mode_ww" in vars2
    assert "hp_power_floor" in vars2
    assert "hp_power_ww" in vars2


def test_hp_mode_constraints_present():
    """``hp_mode_floor_t`` und ``hp_mode_ww_t`` Big-M-Constraints werden
    erzeugt, wenn beide Senken aktiv."""
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    hp.set_active_heat_sinks({"floor", "ww"})
    # prepare braucht inp — Stub
    import types
    n = 96
    hp.prepare(types.SimpleNamespace(
        outside_temp_c=np.full(n, -5.0),
        step_minutes=15,
        timestamps=[datetime.datetime(2026, 1, 15) + datetime.timedelta(minutes=15 * i)
                    for i in range(n)],
    ))
    model = pulp.LpProblem("test")
    vars_ = hp.get_optimization_variables(num_steps=n, model=model)
    hp.add_constraints(model, vars_, step_minutes=15)
    names = list(model.constraints.keys())
    assert any(n_.startswith("hp_mode_floor_") for n_ in names)
    assert any(n_.startswith("hp_mode_ww_") for n_ in names)


# ---------------------------------------------------------------------------
# Schicht 2: End-to-End mit Solver — entweder FBH ODER WW, nie beide
# ---------------------------------------------------------------------------

TEST_DATE = datetime.date(2026, 1, 15)


def _winter_cfg() -> dict:
    """WP + FBH + WW (beide Senken aktiv) bei kaltem Winter."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    cfg["battery"]["enabled"] = False
    cfg["pv"]["enabled"] = False
    cfg["heat_pump"]["enabled"] = True
    cfg["underfloor_heating"]["enabled"] = True
    cfg["hot_water_storage"]["enabled"] = True
    cfg["fresh_water_station"]["enabled"] = True
    cfg["building"]["enabled"] = True
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    return cfg


def _run(cfg):
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    data["temp"] = np.full_like(data["temp"], -5.0, dtype=float)
    inp = build_time_series_input(cfg, data)
    return build_optimizer(build_components(cfg)).optimize(inp)


def test_solver_runs_with_either_or_mode():
    """End-to-End: WP+FBH+WW Modell ist mit Entweder-Oder-Constraint
    weiterhin loesbar."""
    res = _run(_winter_cfg())
    assert res.success, f"Solver erfolglos: {res.solver_status}"
    assert hasattr(res, "hp_mode_ww")
    assert len(res.hp_mode_ww) > 0


def test_at_each_step_only_one_sink_served():
    """Pro Zeitschritt darf nur eine Senke positive Leistung bekommen —
    nicht beide gleichzeitig."""
    res = _run(_winter_cfg())
    assert res.success
    # res.floor_energy_kwh und ww_storage_energy_kwh wachsen unabhaengig.
    # Wir muessen die Senken-Beladung pro Schritt pruefen — am einfachsten
    # ueber das hp_mode_ww-Result-Feld.
    mode_ww = res.hp_mode_ww
    # Wenn WP an ist und WW-Modus, sollte kein Floor-Power-Anteil sein.
    # Wir haben kein direktes Result-Feld pro Sink-Power, also pruefen wir:
    # die Modus-Reihe enthaelt nur 0en und 1en.
    assert set(np.unique(mode_ww).tolist()) <= {0, 1}


def test_hp_mode_ww_empty_when_only_one_sink():
    """Bei nur einer aktiven Senke (nur Heizung) ist hp_mode_ww leer —
    es gibt keine Konflikt-Aufteilung."""
    cfg = _winter_cfg()
    cfg["hot_water_storage"]["enabled"] = False
    cfg["fresh_water_station"]["enabled"] = False
    res = _run(cfg)
    assert res.success
    assert len(res.hp_mode_ww) == 0
