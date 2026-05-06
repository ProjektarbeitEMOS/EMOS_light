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
