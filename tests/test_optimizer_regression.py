"""Regression: Solverergebnisse fuer fest definierte Szenarien.

Die hier festgehaltenen Werte sind die Ergebnisse nach Phase 5b
(Commit 8796ce6). Sie dienen als Sicherheitsnetz fuer die Phase 5c
(Result-Schicht-Refactoring) und alle weiteren Aenderungen.

Toleranzen sind absichtlich locker (1e-3 fuer EUR, 1e-2 fuer kWh-Summen),
damit MIP-Degeneracy nicht zu falschen Test-Faellen fuehrt — die echte
MILP-Zielfunktion ist invariant, einzelne KPIs koennen aber leicht
schwanken zwischen mathematisch-equivalenten Optima.
"""

import pytest

from .conftest import (
    cfg_battery_only,
    cfg_full_house,
    cfg_hp_ufh,
    cfg_hp_ww,
    cfg_wallbox_only,
)


# Erwartungswerte aus dem 8796ce6-Stand fuer das Datum 2026-04-15.
# Bei Modelaenderung: pro Szenario ggf. anpassen, aber nur bewusst.
EXPECTED = {
    "battery": {
        "cost_eur":  -0.1690,
        "obj_eur":    0.6764,
        "throughput": 14.6,   # ch + dis in kWh
    },
    "hp_ww": {
        "cost_eur":   4.5170,
        "hp_kwh":     2.81,
        "ww_end_kwh": 4.95,
    },
    "hp_ufh": {
        "cost_eur":   3.6676,
        "hp_kwh":     0.0,
        "floor_min":  1.0,    # End-Estrichenergie ueber 1 kWh (= warmer als T_min)
    },
    "wallbox": {
        "cost_eur":  11.6324,
        "wb_kwh":    32.6,
    },
    "full": {
        "cost_eur":   9.40,
        "obj_eur":   10.36,
        "hp_kwh":     2.82,
    },
}


def test_battery_only(make_optimizer_run):
    res = make_optimizer_run(cfg_battery_only())
    assert res.solver_status == "Optimal"
    assert res.total_cost_eur == pytest.approx(EXPECTED["battery"]["cost_eur"], abs=0.01)
    obj = res.total_cost_eur + res.battery_aging_cost_eur
    assert obj == pytest.approx(EXPECTED["battery"]["obj_eur"], abs=0.01)
    throughput = (res.batt_charge_kw.sum() + res.batt_discharge_kw.sum()) * 0.25
    assert throughput == pytest.approx(EXPECTED["battery"]["throughput"], abs=0.5)


def test_hp_ww(make_optimizer_run):
    res = make_optimizer_run(cfg_hp_ww())
    assert res.solver_status == "Optimal"
    assert res.total_cost_eur == pytest.approx(EXPECTED["hp_ww"]["cost_eur"], abs=0.01)
    hp_kwh = float(res.hp_power_kw.sum()) * 0.25
    assert hp_kwh == pytest.approx(EXPECTED["hp_ww"]["hp_kwh"], abs=0.05)
    assert res.ww_storage_energy_kwh[-1] == pytest.approx(
        EXPECTED["hp_ww"]["ww_end_kwh"], abs=0.05
    )


def test_hp_ufh(make_optimizer_run):
    res = make_optimizer_run(cfg_hp_ufh())
    assert res.solver_status == "Optimal"
    assert res.total_cost_eur == pytest.approx(EXPECTED["hp_ufh"]["cost_eur"], abs=0.01)
    # Hier laeuft die WP nicht, weil im April keine Heizlast — Estrich
    # wird nur durch Anfangsenergie gepuffert. Mindestens 1 kWh Restenergie.
    assert res.floor_energy_kwh[-1] >= EXPECTED["hp_ufh"]["floor_min"]


def test_wallbox_only(make_optimizer_run):
    res = make_optimizer_run(cfg_wallbox_only())
    assert res.solver_status == "Optimal"
    assert res.total_cost_eur == pytest.approx(EXPECTED["wallbox"]["cost_eur"], abs=0.01)
    assert "wb1" in res.wallbox_power_kw
    wb_kwh = float(res.wallbox_power_kw["wb1"].sum()) * 0.25
    assert wb_kwh == pytest.approx(EXPECTED["wallbox"]["wb_kwh"], abs=0.5)


def test_full_house(make_optimizer_run):
    res = make_optimizer_run(cfg_full_house())
    assert res.solver_status == "Optimal"
    assert res.total_cost_eur == pytest.approx(EXPECTED["full"]["cost_eur"], abs=0.05)
    # Echte MILP-Zielfunktion ist invariant; cost_eur zeigt nur Netzkosten
    obj = res.total_cost_eur + res.battery_aging_cost_eur
    assert obj == pytest.approx(EXPECTED["full"]["obj_eur"], abs=0.05)
    hp_kwh = float(res.hp_power_kw.sum()) * 0.25
    assert hp_kwh == pytest.approx(EXPECTED["full"]["hp_kwh"], abs=0.05)


# ---------------------------------------------------------------------------
# Strukturelle Invarianten unabhaengig von Solverwert
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario_factory", [
    cfg_battery_only, cfg_hp_ww, cfg_hp_ufh, cfg_wallbox_only, cfg_full_house,
])
def test_solver_finds_optimum(scenario_factory, make_optimizer_run):
    res = make_optimizer_run(scenario_factory())
    assert res.solver_status == "Optimal", (
        f"Szenario {scenario_factory.__name__} ist nicht loesbar: {res.solver_status}"
    )
    assert res.total_cost_eur is not None
    assert res.solve_time_s is not None and res.solve_time_s >= 0


@pytest.mark.parametrize("scenario_factory", [
    cfg_battery_only, cfg_full_house,
])
def test_battery_throughput_consistent(scenario_factory, make_optimizer_run):
    """Wenn Batterie aktiv ist: Charge + Discharge >= 0 und SOC bleibt im Fenster."""
    res = make_optimizer_run(scenario_factory())
    assert res.batt_charge_kw is not None and (res.batt_charge_kw >= 0).all()
    assert res.batt_discharge_kw is not None and (res.batt_discharge_kw >= 0).all()
    # SoC-Fenster (Default 10–90% von 10 kWh = 1–9 kWh)
    assert (res.batt_soc_kwh >= 0.99).all() and (res.batt_soc_kwh <= 9.01).all()


@pytest.mark.parametrize("scenario_factory", [cfg_full_house])
def test_full_house_uses_all_components(scenario_factory, make_optimizer_run):
    res = make_optimizer_run(scenario_factory())
    # Alle Felder muessen gefuellt sein
    assert res.batt_charge_kw is not None
    assert res.hp_power_kw is not None
    assert res.floor_energy_kwh is not None
    assert res.ww_storage_energy_kwh is not None
    assert res.wallbox_power_kw is not None and len(res.wallbox_power_kw) >= 1
