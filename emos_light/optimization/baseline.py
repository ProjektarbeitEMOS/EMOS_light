"""Naive Baseline-Strategie ohne Optimierung fuer EMOS Light.

Berechnet Kosten bei einfacher Strategie:
- PV-Eigenverbrauch
- Batterie: Laden bei PV-Ueberschuss, Entladen bei Bedarf
- WP: Laeuft nach Bedarf (keine Preisoptimierung)
- Wallbox: Laedt sofort bei Ankunft

Zwei Funktionen:
- :func:`calculate_baseline_cost` — nur die Kosten (fuer Vergleich
  gegen den optimierten Plan)
- :func:`run_baseline` — vollstaendiges OptimizationResult mit allen
  Zeitreihen, damit die Baseline auch im Dashboard angezeigt werden
  kann wie ein Optimierungsergebnis
"""

import time

import numpy as np

from emos_light.core.types import OptimizationResult, TimeSeriesInput


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

    # COP-Zeitreihen vorab berechnen (Kennfeld aroTHERM plus)
    cop_heating = None
    cop_dhw = None
    if hp_enabled:
        from emos_light.components.heat_pump import HeatPump
        hp_baseline = HeatPump("baseline_hp", hp_cfg)
        cop_heating = hp_baseline.calculate_cop_heating(inp.outside_temp_c)
        cop_dhw = hp_baseline.calculate_cop_dhw(inp.outside_temp_c)

    wallboxes_cfg = config.get("wallboxes", [])

    total_cost_ct = 0.0
    feed_in_tariff = inp.feed_in_tariff_ct_kwh

    for t in range(num_steps):
        pv = float(inp.pv_generation_kw[t])
        load = float(inp.household_load_kw[t])
        price = float(inp.prices_ct_kwh[t])

        # WP: laeuft nach Bedarf (COP aus Kennfeld)
        hp_el = 0.0
        if hp_enabled and cop_heating is not None:
            heating_kw = float(inp.heating_demand_kw[t])
            hw_kw = float(inp.hot_water_demand_kw[t])
            heat_demand = heating_kw + hw_kw
            if heat_demand > 0:
                cop = (heating_kw * float(cop_heating[t]) + hw_kw * float(cop_dhw[t])) / heat_demand
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


def run_baseline(inp: TimeSeriesInput, config: dict) -> OptimizationResult:
    """Simuliert die Baseline-Strategie und liefert ein vollstaendiges
    :class:`OptimizationResult` (analog zum MILP-Optimizer).

    Wird vom Dashboard genutzt, wenn der Nutzer "Baseline (regelbasiert)"
    auswaehlt — dann werden dieselben Plots und KPIs angezeigt wie bei
    MILP/MPC, aber auf Basis der naiven Regel:

    - WP laeuft jeden Schritt mit der Leistung, die genau den
      Heizungs- + Warmwasserbedarf deckt (gewichteter COP).
    - Wallboxen laden sofort bei Ankunft mit voller Leistung,
      bis das Fahrzeug abfaehrt.
    - Batterie laedt mit PV-Ueberschuss, entlaedt bei Restbedarf.
    - Restenergie geht ins/aus dem Netz.
    """
    t_start = time.time()
    num_steps = len(inp.prices_ct_kwh)
    dt_h = inp.step_minutes / 60.0

    # Batterie-Parameter
    batt_cfg = config.get("battery", {})
    batt_enabled = batt_cfg.get("enabled", False)
    batt_capacity = batt_cfg.get("capacity_kwh", 0.0)
    batt_max_charge = batt_cfg.get("max_charge_power_kw", 0.0)
    batt_max_discharge = batt_cfg.get("max_discharge_power_kw", 0.0)
    batt_charge_eff = batt_cfg.get("charge_efficiency", 0.95)
    batt_discharge_eff = batt_cfg.get("discharge_efficiency", 0.95)
    batt_min_soc = batt_cfg.get("min_soc", 0.1)
    batt_max_soc = batt_cfg.get("max_soc", 0.9)
    batt_soc = (
        batt_cfg.get("initial_soc", 0.5) * batt_capacity if batt_enabled else 0.0
    )

    # WP-Parameter
    hp_cfg = config.get("heat_pump", {})
    hp_enabled = hp_cfg.get("enabled", False)
    hp_max_power = hp_cfg.get("max_electrical_power_kw", 0.0)

    cop_heating = None
    cop_dhw = None
    if hp_enabled:
        from emos_light.components.heat_pump import HeatPump
        hp_baseline = HeatPump("baseline_hp", hp_cfg)
        cop_heating = hp_baseline.calculate_cop_heating(inp.outside_temp_c)
        cop_dhw = hp_baseline.calculate_cop_dhw(inp.outside_temp_c)

    wallboxes_cfg = config.get("wallboxes", [])

    # Zeitreihen vorbereiten
    grid_buy_all = np.zeros(num_steps)
    grid_sell_all = np.zeros(num_steps)
    hp_power_all = np.zeros(num_steps)
    batt_charge_all = np.zeros(num_steps)
    batt_discharge_all = np.zeros(num_steps)
    batt_soc_all = np.zeros(num_steps)
    wallbox_power_all: dict = {}
    for wb_cfg in wallboxes_cfg:
        if wb_cfg.get("enabled", False):
            name = wb_cfg.get("name", f"wb_{len(wallbox_power_all)}")
            wallbox_power_all[name] = np.zeros(num_steps)

    total_cost_ct = 0.0
    feed_in_tariff = inp.feed_in_tariff_ct_kwh

    for t in range(num_steps):
        pv = float(inp.pv_generation_kw[t])
        load = float(inp.household_load_kw[t])
        price = float(inp.prices_ct_kwh[t])

        # WP nach Bedarf (gewichteter COP aus Heizungs- vs. WW-Anteil)
        hp_el = 0.0
        if hp_enabled and cop_heating is not None:
            heating_kw = float(inp.heating_demand_kw[t])
            hw_kw = float(inp.hot_water_demand_kw[t])
            heat_demand = heating_kw + hw_kw
            if heat_demand > 0:
                cop = (
                    heating_kw * float(cop_heating[t])
                    + hw_kw * float(cop_dhw[t])
                ) / heat_demand
                hp_el = min(heat_demand / cop, hp_max_power)
        hp_power_all[t] = hp_el

        # Wallboxen — sofort laden, wenn EV anwesend
        wb_total = 0.0
        for wb_cfg in wallboxes_cfg:
            if not wb_cfg.get("enabled", False):
                continue
            hour = (t * inp.step_minutes) // 60
            arrival = wb_cfg.get("arrival_hour", 18)
            departure = wb_cfg.get("departure_hour", 7)
            ev_present = (
                hour >= arrival or hour < departure
                if arrival > departure
                else arrival <= hour < departure
            )
            wb_power = wb_cfg.get("max_power_kw", 0.0) if ev_present else 0.0
            name = wb_cfg.get("name", f"wb_{len(wallbox_power_all)}")
            wallbox_power_all[name][t] = wb_power
            wb_total += wb_power

        # Bilanz
        total_demand = load + hp_el + wb_total
        pv_self_use = min(pv, total_demand)
        residual_demand = total_demand - pv_self_use
        pv_surplus = pv - pv_self_use

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

        batt_charge_all[t] = batt_charge
        batt_discharge_all[t] = batt_discharge
        batt_soc_all[t] = batt_soc

        grid_buy = max(0.0, residual_demand)
        grid_sell = max(0.0, pv_surplus)
        grid_buy_all[t] = grid_buy
        grid_sell_all[t] = grid_sell

        total_cost_ct += grid_buy * price * dt_h - grid_sell * feed_in_tariff * dt_h

    result = OptimizationResult(
        success=True,
        solver_status="Baseline",
        solve_time_s=time.time() - t_start,
        total_cost_eur=total_cost_ct / 100.0,
        grid_buy_kw=grid_buy_all,
        grid_sell_kw=grid_sell_all,
        batt_charge_kw=batt_charge_all,
        batt_discharge_kw=batt_discharge_all,
        batt_soc_kwh=batt_soc_all,
        hp_power_kw=hp_power_all,
        wallbox_power_kw=wallbox_power_all,
        timestamps=inp.timestamps,
    )

    # KPIs anwenden (Eigenverbrauch, Autarkie etc.)
    from emos_light.utils.kpi import calculate_kpis
    result = calculate_kpis(result, inp)
    result.solver_status = "Baseline"
    return result
