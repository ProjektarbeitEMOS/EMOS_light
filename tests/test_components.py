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


# Building ist seit Mai 2026 MILPComponent (Raum als Zustandsvariable).
MILP_CLASSES = (Battery, Building, HeatPump, ThermalStorage,
                UnderfloorHeating, Wallbox)
PASSIVE_CLASSES = (PVSystem, FreshWaterStation, ElectricVehicle)


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

def _stub_inp(prices, step_minutes=15):
    """Hilfsfunktion: minimaler TimeSeriesInput-Stub fuer Wallbox.prepare."""
    import types
    import numpy as np
    return types.SimpleNamespace(
        prices_ct_kwh=np.asarray(prices, dtype=float),
        step_minutes=step_minutes,
    )


def _wb_always_present(extra_cfg):
    """Wallbox mit 24h-Anwesenheit (arrival=0, departure=23+1) fuer Tests."""
    # arrival > departure -> "ueber Nacht" → anwesend [arr, 24) ∪ [0, dep)
    # Mit arrival=0, departure=23 wuerde Stunde 23 fehlen.
    # Wir setzen arrival=1, departure=0 → anwesend hour>=1 oder hour<0 → 1..23
    # Einfacher: konstruiere Tests so, dass alle Slots in die Anwesenheit fallen.
    cfg = {**WALLBOX_DEFAULT, "arrival_hour": 17, "departure_hour": 7, **extra_cfg}
    return Wallbox("wb1", cfg)


def test_wallbox_no_price_filter_when_pct_is_100():
    """pct=100 → kein Filter, _allowed_charging_steps bleibt None."""
    wb = _wb_always_present({"charge_only_below_percentile_pct": 100.0})
    wb.prepare(_stub_inp([10.0, 20.0, 30.0, 40.0]))
    assert wb._allowed_charging_steps is None


def test_wallbox_price_filter_picks_cheapest():
    """pct=25 → nur die guenstigsten 25 % der Anwesenheitsstunden erlaubt."""
    # 8 Slots × 15min = 2h → Stunden 0,0,0,0,1,1,1,1. Beide < 7 -> Anwesenheit
    # (Default arrival=17, departure=7 → Nachts anwesend).
    wb = _wb_always_present({"charge_only_below_percentile_pct": 25.0})
    wb.prepare(_stub_inp([10., 12., 14., 16., 18., 20., 22., 24.]))
    # 25. Perzentil von [10..24] = 13.5 → erlaubt sind {0, 1}
    assert wb._allowed_charging_steps == {0, 1}


def test_wallbox_price_filter_50_percent():
    """pct=50 → erlaubt nur untere Haelfte der Anwesenheitsstunden."""
    wb = _wb_always_present({"charge_only_below_percentile_pct": 50.0})
    wb.prepare(_stub_inp([10., 20., 30., 40., 50., 60.]))
    # Median = 35 → erlaubt {0, 1, 2}
    assert wb._allowed_charging_steps == {0, 1, 2}


def test_wallbox_percentile_is_over_presence_not_full_day():
    """Schluesseltest: Perzentil bezieht sich auf Anwesenheits-, nicht Tagespreise.

    Szenario: Auto nur 0-2 Uhr (sehr teuer) anwesend, von 2-24 Uhr abwesend
    (billig). Bei Tages-Perzentil 50 % wuerden gar keine Anwesenheitsslots
    erlaubt sein. Bei Anwesenheits-Perzentil 50 % muss es trotzdem 2 von 4
    Slots geben.
    """
    import numpy as np
    # 4 Slots × 30 min = 2h Anwesenheit ab 0 Uhr.
    # arrival=0, departure=2 → Anwesenheit hour ∈ {0, 1}
    wb = Wallbox("wb1", {
        **WALLBOX_DEFAULT,
        "arrival_hour": 0,
        "departure_hour": 2,
        "charge_only_below_percentile_pct": 50.0,
    })
    # Slot 0,1 (h=0): teuer 50, 60.  Slot 2,3 (h=1): teurer 70, 80.
    # Alle restlichen Stunden des Tages waeren billig 10–40, aber das EV
    # ist da nicht anwesend → muessen ignoriert werden.
    prices = [50., 60., 70., 80.]
    # Werden hier nur 4 Slots eingespeist (=2h), also der "Tag" hat nur 4 Slots.
    # step_minutes=30 → 2 Slots/Stunde → Stunden = [0, 0, 1, 1]
    wb.prepare(_stub_inp(prices, step_minutes=30))
    # 50. Perzentil von [50, 60, 70, 80] = 65 → erlaubt {0, 1}
    assert wb._allowed_charging_steps == {0, 1}


# ---------------------------------------------------------------------------
# Wallbox: min_range_enabled — Mindestreichweite an/aus
# ---------------------------------------------------------------------------

def test_wallbox_default_has_min_range_enabled():
    wb = Wallbox("wb1", WALLBOX_DEFAULT)
    assert wb.min_range_enabled is True


def test_wallbox_min_range_disabled():
    wb = Wallbox("wb1", {**WALLBOX_DEFAULT, "min_range_enabled": False})
    assert wb.min_range_enabled is False


def test_wallbox_always_has_soc_variable_with_bounds():
    """SOC-Variable: obere Schranke = max_soc * Kapazitaet (BMS-Obergrenze).
    Untere Schranke bewusst ``None`` — der Akku kann mathematisch unter 0
    fallen, wenn das User-Setup das verlangt (zu enger Preisfilter o.ae.).
    Diese unphysikalischen Werte werden via ``soc_underrun_slack`` mit
    UNMET_EV_PENALTY_CT bestraft, statt direkt in Infeasibility zu fuehren."""
    wb = Wallbox("wb1", {**WALLBOX_DEFAULT, "min_range_enabled": True})
    model = pulp.LpProblem("test")
    vars_ = wb.get_optimization_variables(num_steps=96, model=model)
    wb.add_constraints(model, vars_, step_minutes=15)
    soc_vars = vars_["wb_wb1_soc"]
    assert len(soc_vars) == 96
    for v in soc_vars:
        assert v.lowBound is None  # bewusst unbounded, Slack bestraft Unterlauf
        assert v.upBound == pytest.approx(
            WALLBOX_DEFAULT["ev_battery_capacity_kwh"]
        )
    # Slack-Variable fuer SOC-Unterlauf muss existieren und nichtnegativ sein.
    underrun = vars_["wb_wb1_soc_underrun_slack"]
    assert len(underrun) == 96
    for v in underrun:
        assert v.lowBound == 0.0


def test_wallbox_constraints_use_target_at_departure_when_enabled():
    """Mit ``min_range_enabled=True`` erzeugt das Modell pro Abfahrt
    ein ``_target_at_departure_<step>``-Constraint — der Solver muss
    den Ziel-SOC bis dahin erreicht haben (statt erst am Horizont-Ende)."""
    wb = Wallbox("wb1", {
        **WALLBOX_DEFAULT,
        "min_range_enabled": True,
        "current_soc": 0.30,
        "target_soc": 0.80,
        "max_soc": 1.0,
        "arrival_hour": 17,
        "departure_hour": 7,
    })
    model = pulp.LpProblem("test")
    vars_ = wb.get_optimization_variables(num_steps=96, model=model)
    wb.add_constraints(model, vars_, step_minutes=15)
    names = list(model.constraints.keys())
    # Es muss mindestens ein Departure-Constraint geben (24h Horizont
    # mit Abfahrt 7:00 ergibt genau eine Abfahrt).
    assert any("_target_at_departure_" in n for n in names), (
        f"Kein Departure-Constraint gefunden in: {names[:20]}"
    )
    # Alte Mai-2026-Constraints sind ersetzt — duerfen nicht mehr existieren.
    assert not any(n.endswith("_min_energy") for n in names)
    assert not any(n.endswith("_max_energy") for n in names)
    assert not any("_opportunistic_charge" in n for n in names)


def test_wallbox_without_min_range_has_no_departure_constraint():
    """Ohne aktive Mindestreichweite wird KEIN Ziel-SOC erzwungen —
    der Solver entscheidet rein nach Kosten."""
    wb = Wallbox("wb1", {
        **WALLBOX_DEFAULT,
        "min_range_enabled": False,
        "arrival_hour": 17,
        "departure_hour": 7,
    })
    model = pulp.LpProblem("test")
    vars_ = wb.get_optimization_variables(num_steps=96, model=model)
    wb.add_constraints(model, vars_, step_minutes=15)
    names = list(model.constraints.keys())
    assert not any("_target_at_departure_" in n for n in names)
    # SOC-Bilanz-Constraints muessen aber trotzdem da sein, damit der
    # SOC-Verlauf weiterhin mitgefuehrt wird.
    assert any("_soc_init" in n for n in names)
    assert any("_soc_step_" in n for n in names)


def test_wallbox_max_charge_kwh_property():
    """max_charge_kwh entspricht (max_soc - current_soc) * cap / eff."""
    wb = Wallbox("wb1", {
        **WALLBOX_DEFAULT,
        "current_soc": 0.30,
        "max_soc": 1.0,
        "ev_battery_capacity_kwh": 60.0,
        "charging_efficiency": 0.92,
    })
    expected = (1.0 - 0.30) * 60.0 / 0.92  # ≈ 45.65 kWh AC
    assert abs(wb.max_charge_kwh - expected) < 0.01
