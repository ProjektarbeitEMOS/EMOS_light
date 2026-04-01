"""Naive Baseline-Strategie ohne Optimierung fuer EMOS Light.

Berechnet Kosten bei einfacher Strategie:
- PV-Eigenverbrauch
- Batterie: Laden bei PV-Ueberschuss, Entladen bei Bedarf
- WP: Laeuft nach Bedarf (keine Preisoptimierung)
- Wallbox: Laedt sofort bei Ankunft
"""

import numpy as np

from emos_light.core.types import TimeSeriesInput


def calculate_baseline_cost(inp: TimeSeriesInput, config: dict) -> float:
    """Berechnet die Energiekosten einer naiven Baseline-Strategie."""
    num_steps = len(inp.prices_ct_kwh)
    dt_h = inp.step_minutes / 60.0

    batt_cfg = config.get("battery", {})
    batt_enabled = batt_cfg.get("enabled", False)
    batt_capacity = batt_cfg.get("capacity_kwh", 0.0)
    batt_max_charge = batt_cfg.get("max_charge_power_kw", 0.0)
    batt_max_discharge = batt_cfg.get("max_discharge_power_kw", 0.0)
    batt_charge_eff = batt_cfg.get("charge_efficiency", 0.95)
    batt_discharge_eff = batt_cfg.get("discharge_efficiency", 0.95)
    batt_min_soc = batt_cfg.get("min_soc", 0.1)
    batt_max_soc = batt_cfg.get("max_soc", 0.9)
    batt_soc = batt_cfg.get("initial_soc", 0.5) * batt_capacity if batt_enabled else 0.0

    hp_cfg = config.get("heat_pump", {})
    hp_enabled = hp_cfg.get("enabled", False)
    hp_max_power = hp_cfg.get("max_electrical_power_kw", 0.0)
    hp_cop_nominal = hp_cfg.get("cop_nominal", 4.0)
    hp_ref_temp = hp_cfg.get("cop_reference_temp_c", 7.0)

    wallboxes_cfg = config.get("wallboxes", [])

    total_cost_ct = 0.0
    feed_in_tariff = inp.feed_in_tariff_ct_kwh

    for t in range(num_steps):
        pv = float(inp.pv_generation_kw[t])
        load = float(inp.household_load_kw[t])
        price = float(inp.prices_ct_kwh[t])

        # WP: laeuft nach Bedarf
        hp_el = 0.0
        if hp_enabled:
            heat_demand = float(inp.heating_demand_kw[t]) + float(inp.hot_water_demand_kw[t])
            delta_t = float(inp.outside_temp_c[t]) - hp_ref_temp
            cop = hp_cop_nominal * (1 + 0.025 * delta_t)
            cop = max(1.5, min(6.0, cop))
            if heat_demand > 0 and cop > 0:
                hp_el = min(heat_demand / cop, hp_max_power)

        # Wallboxen
        wb_total = 0.0
        for wb_cfg in wallboxes_cfg:
            if not wb_cfg.get("enabled", False):
                continue
            hour = (t * inp.step_minutes) // 60
            arrival = wb_cfg.get("arrival_hour", 18)
            departure = wb_cfg.get("departure_hour", 7)
            ev_present = hour >= arrival or hour < departure
            if ev_present:
                wb_total += wb_cfg.get("max_power_kw", 0.0)

        total_demand = load + hp_el + wb_total
        pv_self_use = min(pv, total_demand)
        residual_demand = total_demand - pv_self_use
        pv_surplus = pv - pv_self_use

        # Batterie
        batt_charge = 0.0
        batt_discharge = 0.0

        if batt_enabled and pv_surplus > 0:
            max_charge = min(
                batt_max_charge,
                pv_surplus,
                (batt_max_soc * batt_capacity - batt_soc) / (batt_charge_eff * dt_h),
            )
            batt_charge = max(0.0, max_charge)
            pv_surplus -= batt_charge
            batt_soc += batt_charge * batt_charge_eff * dt_h

        if batt_enabled and residual_demand > 0:
            max_discharge = min(
                batt_max_discharge,
                residual_demand,
                (batt_soc - batt_min_soc * batt_capacity) * batt_discharge_eff / dt_h,
            )
            batt_discharge = max(0.0, max_discharge)
            residual_demand -= batt_discharge
            batt_soc -= batt_discharge / batt_discharge_eff * dt_h

        grid_buy = max(0.0, residual_demand)
        grid_sell = max(0.0, pv_surplus)

        total_cost_ct += grid_buy * price * dt_h - grid_sell * feed_in_tariff * dt_h

    return total_cost_ct / 100.0
