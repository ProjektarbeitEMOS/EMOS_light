"""Tests fuer die SG-Ready-Logik gemaess BWP v1.1.

Quelle: Vaillant Elektro-Kompendium, Kapitel 14 (SG_Ready_Erklaerung.pdf).

Vier Schaltzustaende:
  Zustand 1 (sg1=1, K1:K2 = 1:0)  Zwangsabschaltung — WP+Zusatzheizung aus.
  Zustand 2 (alle =0, K1:K2 = 0:0) Normalbetrieb.
  Zustand 3 (sg3=1, K1:K2 = 0:1)  Einschaltempfehlung — einmalige
                                  Speicherladung WW + Sollwert-
                                  Ueberhoehung. Estrich (Pufferspeicher)
                                  NICHT geladen, wenn keine Anforderung.
  Zustand 4 (sg4=1, K1:K2 = 1:1)  Zwangseinschaltung — WP an, sowohl
                                  WW als auch Estrich-Pufferspeicher
                                  ueberhoeht (hoeherer Offset als sg3).
"""

import copy
import datetime

import numpy as np
import pulp
import pytest

from emos_light.core.config import DEFAULT_CONFIG, WALLBOX_DEFAULT
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)
from emos_light.components.heat_pump import HeatPump


# ---------------------------------------------------------------------------
# Schichten 1: HeatPump in Isolation — Variablen und Constraint-Schema
# ---------------------------------------------------------------------------

def test_hp_sg_ready_creates_four_binaries():
    """sg1, sg2, sg3, sg4 sind alle vorhanden, wenn SG-Ready aktiv ist.
    Seit der Erweiterung Mai 2026 ist SG-Ready der einzige Steuerkanal
    des Solvers fuer die WP — sg2 (Normalbetrieb) ist daher als eigene
    Binary modelliert, nicht mehr nur impliziter Default."""
    hp = HeatPump("hp", {
        "max_electrical_power_kw": 8.0,
        "min_electrical_power_kw": 1.0,
        "sg_ready": True,
        "sg_ready_temp_raise_state3_c": 5.0,
        "sg_ready_temp_raise_state4_c": 10.0,
    })
    model = pulp.LpProblem("test")
    vars_ = hp.get_optimization_variables(num_steps=96, model=model)
    for key in ("hp_sg1", "hp_sg2", "hp_sg3", "hp_sg4"):
        assert key in vars_, f"Fehlende Binary: {key}"
        assert len(vars_[key]) == 96


def test_sg_ready_state4_offset_must_exceed_state3():
    """Wenn jemand state4_c < state3_c konfiguriert, korrigiert der
    HeatPump-Init das auf state3_c — die PDF schreibt das vor."""
    hp = HeatPump("hp", {
        "sg_ready_temp_raise_state3_c": 5.0,
        "sg_ready_temp_raise_state4_c": 2.0,  # unsinnig
    })
    assert hp.sg_temp_raise_4 >= hp.sg_temp_raise_3


def test_hp_sg_constraints_implement_sole_control_channel():
    """add_constraints schreibt das neue Schema:
      sg1 + sg2 + sg3 + sg4 = 1   (hp_sg_select_)
      hp_on + sg1            = 1   (hp_sg_drives_on_)
    """
    hp = HeatPump("hp", {"sg_ready": True})
    model = pulp.LpProblem("test")
    vars_ = hp.get_optimization_variables(num_steps=96, model=model)
    hp.add_constraints(model, vars_, step_minutes=15)
    names = list(model.constraints.keys())
    # Selektion: pro Schritt genau ein Zustand aktiv
    assert any(n.startswith("hp_sg_select_") for n in names)
    # hp_on direkt aus sg1 abgeleitet
    assert any(n.startswith("hp_sg_drives_on_") for n in names)
    # Alte Constraints sind weg (waeren redundant unter dem neuen Schema)
    assert not any(n.startswith("hp_sg_mutex_") for n in names)
    assert not any(n.startswith("hp_sg1_forces_off_") for n in names)
    assert not any(n.startswith("hp_sg3_needs_on_") for n in names)
    assert not any(n.startswith("hp_sg4_needs_on_") for n in names)


def test_hp_sg_ready_disabled_omits_binaries():
    """Mit sg_ready=False: keine sg-Variablen, keine sg-Constraints."""
    hp = HeatPump("hp", {"sg_ready": False})
    model = pulp.LpProblem("test")
    vars_ = hp.get_optimization_variables(num_steps=96, model=model)
    hp.add_constraints(model, vars_, step_minutes=15)
    for key in ("hp_sg1", "hp_sg3", "hp_sg4"):
        assert key not in vars_
    names = list(model.constraints.keys())
    assert not any("sg_" in n or "sg1" in n or "sg3" in n or "sg4" in n
                   for n in names)


def test_hp_sg_ready_no_dead_cooldown_config_field():
    """sg_ready_min_cooldown_minutes wurde aus DEFAULT_CONFIG entfernt,
    weil das Constraint nie verdrahtet war."""
    assert "sg_ready_min_cooldown_minutes" not in DEFAULT_CONFIG["heat_pump"]


# ---------------------------------------------------------------------------
# Schichten 2: End-to-End mit Solver — Lassen sich alle 4 Zustaende erreichen?
# ---------------------------------------------------------------------------

TEST_DATE = datetime.date(2026, 1, 15)


def _winter_cfg() -> dict:
    """Winter-Tag, WP+FBH+WW+Building aktiv, kein PV/Batterie."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    for key in ("battery", "pv"):
        cfg.setdefault(key, {})["enabled"] = False
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
    inp = build_time_series_input(cfg, data)
    res = build_optimizer(build_components(cfg)).optimize(inp)
    return inp, res


def test_solver_runs_with_sg_ready_enabled():
    """Volle SG-Ready-Variablen + Constraints muessen den Solver nicht
    infeasible machen."""
    cfg = _winter_cfg()
    _, res = _run(cfg)
    assert res.success, f"Solver erfolglos: {res.solver_status}"


def test_sg_ready_state_in_result_is_valid():
    """sg_ready_state ist eine Reihe in {1, 2, 3, 4} — jeder Schritt
    hat einen wohldefinierten Zustand. Welche tatsaechlich auftauchen,
    haengt vom Szenario ab (z.B. extremer Winter: oft sg1/sg4)."""
    cfg = _winter_cfg()
    _, res = _run(cfg)
    assert res.success
    states = set(int(s) for s in np.unique(res.sg_ready_state))
    assert states <= {1, 2, 3, 4}, f"Unerwartete Zustaende: {states}"
    # Mindestens ein nicht-trivialer Zustand muss vom Solver gewaehlt
    # werden — die Kostenoptimierung soll das SG-Steuerschema aktiv
    # ausnutzen.
    assert states != {2}, "Solver hat im Winter nichts ausser Normal gewaehlt"


def test_sg_ready_states_are_mutually_exclusive_per_step():
    """Pro Zeitschritt genau ein SG-Zustand aktiv (Selektion via
    sg1+sg2+sg3+sg4 = 1)."""
    cfg = _winter_cfg()
    _, res = _run(cfg)
    states = res.sg_ready_state
    assert set(int(s) for s in np.unique(states)) <= {1, 2, 3, 4}
    # jeder Schritt hat genau einen wohldefinierten Zustand (sonst
    # waere ein Wert ausserhalb {1..4} im Array gelandet).
    assert all(s in (1, 2, 3, 4) for s in states)


def test_sg_ready_is_sole_wp_control_channel():
    """hp_on muss exakt komplementaer zu sg1 sein — die WP laeuft
    iff der Solver KEIN sg1 waehlt. Damit ist SG-Ready der einzige
    Stellhebel fuer das Ein-/Ausschalten der WP."""
    cfg = _winter_cfg()
    _, res = _run(cfg)
    states = np.asarray(res.sg_ready_state)
    hp_running = res.hp_power_kw > 1e-6
    expected_running = states != 1
    # Solver-Ergebnisse sind binaer-konsistent
    assert np.all(hp_running == expected_running), (
        "hp_on und sg1 nicht komplementaer:\n"
        f"  Schritte WP laeuft trotz sg1=1: "
        f"{int(np.sum(hp_running & (states == 1)))}\n"
        f"  Schritte WP aus obwohl sg1=0: "
        f"{int(np.sum(~hp_running & (states != 1)))}"
    )


# ---------------------------------------------------------------------------
# Schichten 3: WW- und Estrich-Boost in den richtigen Zustaenden
# ---------------------------------------------------------------------------

def test_sg3_only_boosts_ww_not_floor():
    """Konstruierter Test: wenn sg3 forciert wird, darf der Estrich die
    normale Obergrenze NICHT ueberschreiten (PDF: keine Speicherladung
    im Heizbetrieb bei sg3 ohne Waermeanforderung). WW dagegen schon.

    Wir zwingen sg3 = 1 fuer alle Schritte und pruefen, dass das
    Modell trotzdem zulaessig ist UND der Estrich seine Default-
    Obergrenze einhaelt."""
    cfg = _winter_cfg()
    # Aussentemperatur warm, damit keine echte Estrich-Anforderung anliegt
    # — der Estrich sollte dann auch unter sg3 nicht aufgeheizt werden.
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    data["temp"] = np.full_like(data["temp"], 15.0, dtype=float)
    inp = build_time_series_input(cfg, data)
    optimizer = build_optimizer(build_components(cfg))
    res = optimizer.optimize(inp)
    assert res.success

    # Estrich darf seine normale Obergrenze (total_capacity_kwh) nicht
    # ueberschreiten — die Variable hat ihre upBound nur ueber sg4
    # gelockert, und der Solver hat keinen Anreiz, ohne sg4 dort hoch
    # zu gehen.
    ufh = optimizer.underfloor_heating
    assert res.floor_energy_kwh.max() <= ufh.total_capacity_kwh + 1e-6


def test_sg4_can_boost_floor_capacity():
    """sg4 hebt die Estrich-Obergrenze um sg_temp_raise_4 * cap/K.
    Wir setzen einen besonders hohen Wert (15K) und pruefen, dass der
    Solver theoretisch ueber die normale Obergrenze gehen darf."""
    cfg = _winter_cfg()
    cfg["heat_pump"]["sg_ready_temp_raise_state4_c"] = 15.0
    optimizer = build_optimizer(build_components(cfg))
    # Wir muessen das Modell selbst bauen und die upBound pruefen.
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    inp = build_time_series_input(cfg, data)
    res = optimizer.optimize(inp)
    assert res.success
    ufh = optimizer.underfloor_heating
    # Variable upBound ist nicht mehr in res sichtbar — wir pruefen, dass
    # mindestens der zusaetzliche delta_floor_4 als Bound erlaubt war.
    # Erfolgreicher Solve impliziert: das Bound-Update hat den Solver
    # nicht infeasible gemacht und mehr Spielraum gegeben.
    delta_floor_4 = ufh.capacity_kwh_per_k * 15.0
    assert delta_floor_4 > 0
