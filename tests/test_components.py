"""Smoketests fuer die Komponenten — Hierarchie und API-Vertrag.

Diese Tests laufen ohne Solver — sie pruefen nur, dass alle
Komponenten-Klassen das verlangen, was die Stufe-2-Architektur erwartet
(richtige Basisklasse, korrekte Signaturen, sinnvolle Defaults).
"""

import pulp
import pytest

from emos_light.components import (
    Battery,
    Building,
    Component,
    ElectricVehicle,
    FreshWaterStation,
    HeatPump,
    MILPComponent,
    PVSystem,
    ThermalStorage,
    UnderfloorHeating,
    Wallbox,
)
from emos_light.core.config import (
    DEFAULT_CONFIG,
    EV_DEFAULT,
    PV_SURFACE_DEFAULT,
    WALLBOX_DEFAULT,
)


MILP_CLASSES = (Battery, HeatPump, ThermalStorage, UnderfloorHeating, Wallbox)
PASSIVE_CLASSES = (PVSystem, Building, FreshWaterStation, ElectricVehicle)


# ---------------------------------------------------------------------------
# Klassenhierarchie
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", MILP_CLASSES)
def test_milp_components_inherit_milpcomponent(cls):
    assert issubclass(cls, MILPComponent), f"{cls.__name__} muss von MILPComponent erben"


@pytest.mark.parametrize("cls", PASSIVE_CLASSES)
def test_passive_components_are_only_component(cls):
    assert issubclass(cls, Component)
    assert not issubclass(cls, MILPComponent), (
        f"{cls.__name__} ist passiv und sollte NICHT von MILPComponent erben"
    )


# ---------------------------------------------------------------------------
# Heat-Sink-Discovery
# ---------------------------------------------------------------------------

def test_underfloor_heating_is_floor_sink():
    ufh = UnderfloorHeating("ufh", DEFAULT_CONFIG["underfloor_heating"])
    assert ufh.heat_sink_id == "floor"


def test_thermal_storage_sink_id_matches_prefix():
    ts = ThermalStorage(
        "ww_storage", DEFAULT_CONFIG["hot_water_storage"], prefix="ww",
    )
    assert ts.heat_sink_id == "ww"


def test_battery_is_not_a_heat_sink():
    bat = Battery("bat", DEFAULT_CONFIG["battery"])
    assert bat.heat_sink_id is None


def test_heat_pump_is_not_a_heat_sink():
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    assert hp.heat_sink_id is None


# ---------------------------------------------------------------------------
# Bilanz-API: Defaults sind 0 und das LP-System macht damit nichts kaputt
# ---------------------------------------------------------------------------

def test_default_balance_methods_return_zero():
    """Eine MILPComponent ohne Override liefert 0 fuer alle Bilanzbeitraege."""
    bat = Battery("bat", DEFAULT_CONFIG["battery"])
    # Battery override electrical_supply/demand, aber heat_supply/heat_demand
    # nimmt den Default
    vars_ = {}
    assert bat.heat_supply(vars_, 0, "floor") == 0.0
    assert bat.heat_demand(vars_, 0, "floor") == 0.0


def test_battery_balance_contributions():
    bat = Battery("bat", DEFAULT_CONFIG["battery"])
    model = pulp.LpProblem("test")
    vars_ = bat.get_optimization_variables(num_steps=4, model=model)
    bat.add_constraints(model, vars_, step_minutes=15)

    # Charge ist Demand, Discharge ist Supply
    assert bat.electrical_supply(vars_, 2) is vars_["bat_discharge"][2]
    assert bat.electrical_demand(vars_, 2) is vars_["bat_charge"][2]


def test_wallbox_demand_only():
    wb = Wallbox("wb1", WALLBOX_DEFAULT)
    model = pulp.LpProblem("test")
    vars_ = wb.get_optimization_variables(num_steps=4, model=model)
    wb.add_constraints(model, vars_, step_minutes=15)

    # Wallbox liefert nur Demand
    assert wb.electrical_supply(vars_, 0) == 0.0
    assert wb.electrical_demand(vars_, 0) is vars_[f"wb_{wb.name}_power"][0]


# ---------------------------------------------------------------------------
# Variablen-Naming-Convention (Phase 3b)
# ---------------------------------------------------------------------------

def test_battery_uses_bat_prefix():
    bat = Battery("bat", DEFAULT_CONFIG["battery"])
    model = pulp.LpProblem("test")
    keys = set(bat.get_optimization_variables(num_steps=2, model=model).keys())
    assert keys == {"bat_charge", "bat_discharge", "bat_soc",
                    "bat_b_charge", "bat_b_discharge"}


def test_heat_pump_uses_hp_prefix():
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    model = pulp.LpProblem("test")
    keys = set(hp.get_optimization_variables(num_steps=2, model=model).keys())
    # hp_on, hp_power immer; sg1/sg3 wenn sg_ready aktiv
    assert "hp_on" in keys and "hp_power" in keys
    if hp.sg_ready:
        assert "hp_sg1" in keys and "hp_sg3" in keys


def test_underfloor_heating_uses_ufh_prefix():
    ufh = UnderfloorHeating("ufh", DEFAULT_CONFIG["underfloor_heating"])
    model = pulp.LpProblem("test")
    keys = set(ufh.get_optimization_variables(num_steps=2, model=model).keys())
    assert keys == {"ufh_floor_energy", "ufh_q_floor_in"}


# ---------------------------------------------------------------------------
# WP-Senken-Split: Variablen entstehen nur, wenn mehrere Senken aktiv sind
# ---------------------------------------------------------------------------

def test_heat_pump_no_split_with_single_sink():
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    hp.set_active_heat_sinks({"floor"})
    model = pulp.LpProblem("test")
    keys = hp.get_optimization_variables(num_steps=2, model=model).keys()
    assert "hp_power_floor" not in keys
    assert "hp_power_ww" not in keys


def test_heat_pump_splits_with_two_sinks():
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    hp.set_active_heat_sinks({"floor", "ww"})
    model = pulp.LpProblem("test")
    keys = hp.get_optimization_variables(num_steps=2, model=model).keys()
    assert "hp_power_floor" in keys
    assert "hp_power_ww" in keys


# ---------------------------------------------------------------------------
# Predicates: is_heat_supplier, is_par14a_curtailable
# ---------------------------------------------------------------------------

def test_heat_pump_is_supplier():
    hp = HeatPump("hp", DEFAULT_CONFIG["heat_pump"])
    assert hp.is_heat_supplier is True


def test_battery_not_supplier():
    bat = Battery("bat", DEFAULT_CONFIG["battery"])
    assert bat.is_heat_supplier is False


def test_storage_and_ufh_not_suppliers():
    ufh = UnderfloorHeating("ufh", DEFAULT_CONFIG["underfloor_heating"])
    ts = ThermalStorage("ww", DEFAULT_CONFIG["hot_water_storage"], prefix="ww")
    assert ufh.is_heat_supplier is False
    assert ts.is_heat_supplier is False


@pytest.mark.parametrize("cls,cfg_key,curtailable", [
    (HeatPump, "heat_pump", True),
    (Wallbox, None, True),  # Wallbox uses WALLBOX_DEFAULT
    (Battery, "battery", False),
    (UnderfloorHeating, "underfloor_heating", False),
])
def test_par14a_curtailable_predicate(cls, cfg_key, curtailable):
    if cls is Wallbox:
        c = cls("wb1", WALLBOX_DEFAULT)
    elif cls is ThermalStorage:
        c = cls("x", DEFAULT_CONFIG[cfg_key], prefix="x")
    else:
        c = cls("x", DEFAULT_CONFIG[cfg_key])
    assert c.is_par14a_curtailable is curtailable


# ---------------------------------------------------------------------------
# Wallbox: preisgesteuerte Ladestrategie (Ersatz fuer V2H)
# ---------------------------------------------------------------------------

def test_wallbox_no_price_filter_when_pct_is_100():
    """pct=100 → kein Filter, _allowed_charging_steps bleibt None."""
    import types
    import numpy as np
    wb = Wallbox("wb1", {**WALLBOX_DEFAULT, "charge_only_below_percentile_pct": 100.0})
    inp = types.SimpleNamespace(prices_ct_kwh=np.array([10.0, 20.0, 30.0, 40.0]))
    wb.prepare(inp)
    assert wb._allowed_charging_steps is None


def test_wallbox_price_filter_picks_cheapest():
    """pct=25 → nur die guenstigsten 25 % erlaubt."""
    import types
    import numpy as np
    wb = Wallbox("wb1", {**WALLBOX_DEFAULT, "charge_only_below_percentile_pct": 25.0})
    # 8 Schritte mit aufsteigenden Preisen → unterstes Viertel = Index 0,1
    inp = types.SimpleNamespace(
        prices_ct_kwh=np.array([10., 12., 14., 16., 18., 20., 22., 24.])
    )
    wb.prepare(inp)
    # 25. Perzentil von [10..24] ist 13.5 → erlaubt sind alle mit price <= 13.5
    assert wb._allowed_charging_steps == {0, 1}


def test_wallbox_price_filter_50_percent():
    """pct=50 → erlaubt nur untere Haelfte."""
    import types
    import numpy as np
    wb = Wallbox("wb1", {**WALLBOX_DEFAULT, "charge_only_below_percentile_pct": 50.0})
    inp = types.SimpleNamespace(
        prices_ct_kwh=np.array([10., 20., 30., 40., 50., 60.])
    )
    wb.prepare(inp)
    # Median = 35 → erlaubt 10/20/30
    assert wb._allowed_charging_steps == {0, 1, 2}
