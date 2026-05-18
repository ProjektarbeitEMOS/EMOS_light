"""Regression: Optimierungsergebnisse Battery+WP+Wallbox vor/nach Refactoring.

Wird vom Bash-Aufruf 2x ausgefuehrt — einmal auf main, einmal auf refactoring.
"""
import datetime
import copy
import json
import sys

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components, build_optimizer,
    load_input_data, build_time_series_input,
)


def run(scenario_name: str, mods):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.setdefault("hot_water_storage", {})["enabled"] = False
    cfg.setdefault("underfloor_heating", {})["enabled"] = False
    cfg.setdefault("fresh_water_station", {})["enabled"] = False
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    mods(cfg)

    date = datetime.date(2026, 4, 15)
    data = load_input_data(cfg, date)
    inp = build_time_series_input(cfg, data)
    comps = build_components(cfg)
    opt = build_optimizer(comps)
    res = opt.optimize(inp)
    return {
        "scenario": scenario_name,
        "status": res.solver_status,
        "cost": round(res.total_cost_eur, 6),
        "hp_sum": round(float(res.hp_power_kw.sum()), 4) if res.hp_power_kw is not None else None,
        "batt_ch": round(float(res.batt_charge_kw.sum()), 4) if res.batt_charge_kw is not None else None,
        "batt_dis": round(float(res.batt_discharge_kw.sum()), 4) if res.batt_discharge_kw is not None else None,
    }


SCENARIOS = [
    ("battery_only", lambda c: (
        c.update({"battery": {**c["battery"], "enabled": True}}),
        c["heat_pump"].update({"enabled": False}),
        c["pv"].update({"enabled": False}),
    )),
    ("hp_only", lambda c: (
        c["battery"].update({"enabled": False}),
        c["heat_pump"].update({"enabled": True}),
        c["pv"].update({"enabled": False}),
    )),
    ("wallbox_only", lambda c: (
        c["battery"].update({"enabled": False}),
        c["heat_pump"].update({"enabled": False}),
        c["pv"].update({"enabled": False}),
        c.update({"wallboxes": [{
            "name": "wb1", "enabled": True, "max_power_kw": 11.0,
            "min_power_kw": 4.2, "phases": 3,
            "ev_battery_capacity_kwh": 60.0,
            "current_soc": 0.3, "target_soc": 0.8,
            "departure_hour": 7, "arrival_hour": 17,
            "charging_efficiency": 0.92,
        }]}),
    )),
    ("battery_plus_hp", lambda c: (
        c["battery"].update({"enabled": True}),
        c["heat_pump"].update({"enabled": True}),
        c["pv"].update({"enabled": True}),
    )),
]


if __name__ == "__main__":
    out = [run(name, mods) for name, mods in SCENARIOS]
    print(json.dumps(out, indent=2))
