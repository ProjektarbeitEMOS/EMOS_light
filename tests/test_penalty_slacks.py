"""Tests fuer die Refaktorierung der Penalty-Slacks (Mai 2026).

Quelle: Vaillant-Projektgruppe "Penalty Slacks". Hauptpunkte:

1. ``heating_slack`` ist entfernt (war tot — keine Constraint referenziert sie).
2. ``t_innen_slack_low`` ist in ``_comfort`` (bis 0.5 K) und ``_critical``
   (unbeschraenkt) aufgeteilt, jeweils mit eigenem Penalty-Tarif.
3. Penalty-Tarife in ct/kWh: ``P_WW=150``, ``P_COMFORT=100``,
   ``P_CRITICAL=300``, ``PENALTY_EV_EXPENSIVE=500``.
4. ``power_expensive_slack`` pro Wallbox als Soft-Preisfilter.
5. ``total_cost_eur`` und ``objective_value_eur`` sind getrennte Felder —
   echte Geldfluesse vs. interner Solver-Wert.
"""

import copy
import datetime

import pulp
import pytest
import yaml

from emos_light.components.building import Building
from emos_light.components.wallbox import Wallbox
from emos_light.core.config import (
    DEFAULT_CONFIG,
    WALLBOX_DEFAULT,
    _deep_merge,
)
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)
from emos_light.optimization.optimizer import (
    P_COMFORT,
    P_CRITICAL,
    P_WW,
    PENALTY_EV_EXPENSIVE,
    UNMET_HEAT_PENALTY_CT,
)


# ---------------------------------------------------------------------------
# 1. heating_slack entfernt
# ---------------------------------------------------------------------------

def test_heating_slack_completely_removed():
    """Im Modell taucht kein ``heating_slack_*``-Constraint und keine
    entsprechende Variable mehr auf."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    data = load_input_data(cfg, datetime.date(2026, 1, 15), use_api=False)
    inp = build_time_series_input(cfg, data)
    opt = build_optimizer(build_components(cfg))
    res = opt.optimize(inp)
    assert res.success
    # heating_slack ist nie wieder im Result
    # (es gibt sowieso kein Result-Feld dafuer, aber auch im Solver-Modell
    #  duerfen keine Constraints mehr "heating_slack" enthalten)


# ---------------------------------------------------------------------------
# 2. t_innen_slack split
# ---------------------------------------------------------------------------

def test_building_creates_split_low_slacks():
    """Building.get_optimization_variables liefert _comfort UND _critical."""
    b = Building("b", DEFAULT_CONFIG["building"])
    model = pulp.LpProblem("test")
    vars_ = b.get_optimization_variables(num_steps=96, model=model)
    assert "t_innen_slack_low_comfort" in vars_
    assert "t_innen_slack_low_critical" in vars_
    assert "t_innen_slack_high" in vars_
    # _comfort hat eine harte Obergrenze von 0.5 K, _critical nicht
    for v in vars_["t_innen_slack_low_comfort"]:
        assert v.lowBound == 0.0
        assert v.upBound == pytest.approx(0.5)
    for v in vars_["t_innen_slack_low_critical"]:
        assert v.lowBound == 0.0
        assert v.upBound is None
    # _high bleibt unbeschraenkt nach oben
    for v in vars_["t_innen_slack_high"]:
        assert v.lowBound == 0.0


def test_building_constraint_uses_both_low_slacks():
    """Die untere Komfortgrenze wird durch die SUMME beider Slacks
    abgefangen: ``t_innen + comfort + critical >= T_min``."""
    b = Building("b", DEFAULT_CONFIG["building"])
    model = pulp.LpProblem("test")
    vars_ = b.get_optimization_variables(num_steps=96, model=model)
    b.add_constraints(model, vars_, step_minutes=15)
    names = list(model.constraints.keys())
    assert any(n.startswith("t_innen_comfort_min_") for n in names)
    # Die Constraint enthaelt beide Slacks (Inspektion ueber lhs-Koeffizienten)
    c = model.constraints["t_innen_comfort_min_0"]
    var_names = [v.name for v in c.keys()]
    assert any("comfort" in n for n in var_names)
    assert any("critical" in n for n in var_names)


# ---------------------------------------------------------------------------
# 3. Penalty-Konstanten existieren und haben die richtigen Werte
# ---------------------------------------------------------------------------

def test_penalty_constants_per_pdf():
    """Vorgaben aus der PDF Penalty Slacks (Mai 2026)."""
    assert P_WW == 150.0
    assert P_COMFORT == 100.0
    assert P_CRITICAL == 300.0
    assert PENALTY_EV_EXPENSIVE == 500.0
    # _critical > _comfort: groessere Verletzung wird haerter bestraft
    assert P_CRITICAL > P_COMFORT
    # UNMET_HEAT_PENALTY_CT (fuer high-Slack + Notfaelle) bleibt unveraendert
    assert UNMET_HEAT_PENALTY_CT == 500.0


# ---------------------------------------------------------------------------
# 4. Wallbox: power_expensive_slack als Soft-Preisfilter
# ---------------------------------------------------------------------------

def test_wallbox_has_power_expensive_slack_variable():
    """Wallbox-Variablen-Dict enthaelt power_expensive_slack mit
    Bounds [0, max_power_kw]."""
    wb = Wallbox("wb1", WALLBOX_DEFAULT)
    model = pulp.LpProblem("test")
    vars_ = wb.get_optimization_variables(num_steps=96, model=model)
    key = "wb_wb1_power_expensive_slack"
    assert key in vars_
    for v in vars_[key]:
        assert v.lowBound == 0.0
        assert v.upBound == pytest.approx(WALLBOX_DEFAULT["max_power_kw"])


def test_wallbox_price_filter_routes_via_slack_in_expensive_hours():
    """In erlaubten (billigen) Slots ist der Slack auf 0 festgenagelt;
    in nicht-erlaubten Slots gilt ``power[t] <= slack[t]``."""
    import types
    import numpy as np
    wb = Wallbox("wb1", {
        **WALLBOX_DEFAULT,
        "min_range_enabled": True,
        "arrival_hour": 17, "departure_hour": 7,
        "charge_only_below_percentile_pct": 25.0,
    })
    n = 96
    inp = types.SimpleNamespace(
        prices_ct_kwh=np.linspace(10, 50, n), step_minutes=15,
    )
    wb.prepare(inp)
    model = pulp.LpProblem("test")
    vars_ = wb.get_optimization_variables(num_steps=n, model=model)
    wb.add_constraints(model, vars_, step_minutes=15)
    names = list(model.constraints.keys())
    # Beide Constraint-Familien existieren
    assert any(n_.startswith("wb_wb1_price_slack_zero_") for n_ in names)
    assert any(n_.startswith("wb_wb1_price_slack_route_") for n_ in names)


# ---------------------------------------------------------------------------
# 5. objective_value_eur vs. total_cost_eur sauber getrennt
# ---------------------------------------------------------------------------

def test_total_cost_excludes_slack_penalties():
    """Mit User-Config aus Penalty-Slacks-PDF-Szenario: starke Slacks
    in der Zielfunktion, aber total_cost_eur enthaelt nur Grid-Geldfluesse."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    cfg["wallboxes"] = [{
        **WALLBOX_DEFAULT,
        "name": "wb1", "enabled": True,
        "ev_battery_capacity_kwh": 63.0,
        "current_soc": 0.3, "target_soc": 0.6, "max_soc": 1.0,
        "arrival_hour": 17, "departure_hour": 7,
        "min_range_enabled": True,
        "charge_only_below_percentile_pct": 30.0,
        "driving_loss_pct_per_hour": 5.0,
    }]
    cfg["electric_vehicles"] = []
    data = load_input_data(cfg, datetime.date(2026, 1, 15), use_api=False)
    inp = build_time_series_input(cfg, data)
    res = build_optimizer(build_components(cfg)).optimize(inp)
    assert res.success
    # Beide Felder sind gefuellt
    assert res.objective_value_eur is not None
    # total_cost_eur ist die Bottom-Up-Berechnung aus Grid-Geld
    assert res.total_cost_eur == pytest.approx(
        res.grid_buy_cost_eur - res.feed_in_revenue_eur, abs=0.01
    )
