"""MILP-Optimierungsengine fuer EMOS Light.

Thermische Topologie:
    WP --+-- FBH --> Estrich (therm. Speicher) --> Raum
         +-- WW-Speicher --> Frischwasserstation --> Brauchwasser

Entscheidungsvariablen (thermisch):
    hp_power[t]:         Elektrische WP-Leistung gesamt
    hp_power_floor[t]:   Anteil fuer FBH-Pfad (nur bei Mehrfach-Senken)
    hp_power_ww[t]:      Anteil fuer WW-Pfad  (nur bei Mehrfach-Senken)
    ufh_floor_energy[t]: Thermische Energie im Estrich
    ufh_q_floor_in[t]:   Q_in der FBH (= Senkeneingang)
    ww_energy_kwh[t]:    Thermische Energie im WW-Speicher
    ww_q_in[t]:          Q_in des WW-Speichers
    ww_q_demand[t]:      Q_out des WW-Speichers (an Frischwasserstation)
    hp_sg1[t]:           SG-Ready Zustand 1 (Lastabwurf)
    hp_sg3[t]:           SG-Ready Zustand 3 (Verstaerkt)

Bilanzgleichungen entstehen generisch ueber MILPComponent.heat_supply()
und MILPComponent.heat_demand() pro aktiver Senke.
"""

import time
from typing import Optional

import numpy as np
import pulp

from emos_light.components.pv import PVSystem
from emos_light.components.battery import Battery
from emos_light.components.heat_pump import HeatPump
from emos_light.components.thermal_storage import ThermalStorage
from emos_light.components.fresh_water_station import FreshWaterStation
from emos_light.components.underfloor_heating import UnderfloorHeating
from emos_light.components.wallbox import Wallbox
from emos_light.core.types import TimeSeriesInput, OptimizationResult


UNMET_HEAT_PENALTY_CT = 500.0


class EMOSLightOptimizer:
    """MILP-basierter Energieoptimizer fuer Neubau."""

    def __init__(
        self,
        pv: Optional[PVSystem] = None,
        battery: Optional[Battery] = None,
        heat_pump: Optional[HeatPump] = None,
        hot_water_storage: Optional[ThermalStorage] = None,
        fresh_water_station: Optional[FreshWaterStation] = None,
        underfloor_heating: Optional[UnderfloorHeating] = None,
        wallboxes: Optional[list[Wallbox]] = None,
        **kwargs,
    ):
        self.pv = pv
        self.battery = battery
        self.heat_pump = heat_pump
        self.hot_water_storage = hot_water_storage
        self.fresh_water_station = fresh_water_station
        self.underfloor_heating = underfloor_heating
        self.wallboxes = wallboxes or []

    def optimize(self, inp: TimeSeriesInput) -> OptimizationResult:
        """Fuehrt die MILP-Optimierung durch."""
        t_start = time.time()
        num_steps = len(inp.prices_ct_kwh)
        dt_h = inp.step_minutes / 60.0

        model = pulp.LpProblem("EMOS_Light", pulp.LpMinimize)

        # ============================================================
        # Netz-Variablen
        # ============================================================
        grid_buy = [
            pulp.LpVariable(f"grid_buy_{t}", 0, inp.max_grid_power_kw)
            for t in range(num_steps)
        ]
        grid_sell = [
            pulp.LpVariable(f"grid_sell_{t}", 0, inp.max_grid_power_kw)
            for t in range(num_steps)
        ]
        grid_buy_on = [
            pulp.LpVariable(f"grid_buy_on_{t}", cat=pulp.LpBinary)
            for t in range(num_steps)
        ]
        for t in range(num_steps):
            model += grid_buy[t] <= inp.max_grid_power_kw * grid_buy_on[t], f"grid_buy_link_{t}"
            model += grid_sell[t] <= inp.max_grid_power_kw * (1 - grid_buy_on[t]), f"grid_sell_link_{t}"

        variables: dict = {"grid_buy": grid_buy, "grid_sell": grid_sell}

        # ============================================================
        # Phase A — Komponentenliste aufbauen (nur Referenzen sammeln)
        # ============================================================
        # Heizsenken (UFH, WW-Speicher) sind nur sinnvoll, wenn ueberhaupt
        # ein Waermeerzeuger existiert (siehe is_heat_supplier). Sonst
        # waeren sie abgekoppelte Knoten.
        has_fws = bool(self.fresh_water_station and self.fresh_water_station.enabled)

        # Erst alle potenziellen MILP-Komponenten sammeln
        candidates: list = []
        if self.battery and self.battery.enabled:
            candidates.append(self.battery)
        if self.heat_pump and self.heat_pump.enabled:
            candidates.append(self.heat_pump)
        if self.underfloor_heating and self.underfloor_heating.enabled:
            candidates.append(self.underfloor_heating)
        if self.hot_water_storage and self.hot_water_storage.enabled:
            candidates.append(self.hot_water_storage)
        for wb in self.wallboxes:
            if wb.enabled:
                candidates.append(wb)

        # Wenn keine Waermeerzeuger existieren, Senken rausfiltern
        has_supplier = any(c.is_heat_supplier for c in candidates)
        milp_components: list = [
            c for c in candidates
            if has_supplier or c.heat_sink_id is None
        ]
        active_wallboxes = [c for c in milp_components if isinstance(c, Wallbox)]
        has_hp = any(c.is_heat_supplier for c in milp_components)

        # ============================================================
        # Phase B — Vorbereitung mit Eingangsdaten (z.B. WP berechnet COP)
        # ============================================================
        for c in milp_components:
            c.prepare(inp)

        # ============================================================
        # Phase C — Aktive Waermesenken ermitteln und propagieren
        # ============================================================
        active_sinks = {
            c.heat_sink_id for c in milp_components
            if c.heat_sink_id is not None
        }
        for c in milp_components:
            c.set_active_heat_sinks(active_sinks)

        # ============================================================
        # Phase D — Variablen + Constraints jeder Komponente
        # ============================================================
        for c in milp_components:
            comp_vars = c.get_optimization_variables(num_steps, model)
            variables.update(comp_vars)
            c.add_constraints(model, variables, inp.step_minutes)

        # Fallback: hp_power-Variable existiert immer (auch ohne aktive WP),
        # weil es an mehreren Stellen unten in der Auswertung gelesen wird.
        if "hp_power" not in variables:
            variables["hp_power"] = [
                pulp.LpVariable(f"hp_power_{t}", 0, 0) for t in range(num_steps)
            ]

        # ============================================================
        # Phase E — Generische Waermebilanz pro Senke
        #     Fuer jede aktive Senke s gilt: Σ heat_supply(s) == Σ heat_demand(s)
        # ============================================================
        for sink in active_sinks:
            for t in range(num_steps):
                supply = pulp.lpSum(
                    c.heat_supply(variables, t, sink) for c in milp_components
                )
                demand = pulp.lpSum(
                    c.heat_demand(variables, t, sink) for c in milp_components
                )
                model += supply == demand, f"heat_balance_{sink}_{t}"

        # ============================================================
        # Phase F — Senken-spezifische Komfort-/SG-Constraints, Slacks
        #     Diese koppeln die Senken an externe Bedarfe oder erlauben
        #     dem Solver, Komfort weich zu verletzen.
        # ============================================================
        heating_slack = None
        ww_slack = None
        has_ww = self.hot_water_storage and self.hot_water_storage.enabled and has_hp
        has_ufh = self.underfloor_heating and self.underfloor_heating.enabled and has_hp

        if has_ww:
            prefix = self.hot_water_storage.prefix

            ww_slack = [
                pulp.LpVariable(f"ww_slack_{t}", 0) for t in range(num_steps)
            ]

            # Brauchwasserbedarf als Entnahme aus WW-Speicher
            if has_fws:
                fw_demand_kw = self.fresh_water_station.calculate_storage_demand(
                    inp.hot_water_demand_kw
                )
            else:
                fw_demand_kw = inp.hot_water_demand_kw

            for t in range(num_steps):
                model += (
                    variables[f"{prefix}_q_demand"][t] + ww_slack[t]
                    == float(fw_demand_kw[t]),
                    f"ww_demand_fix_{t}",
                )

            # Zeit-abhaengige Mindesttemperatur (Komfort-Perioden)
            min_energy_schedule = self.hot_water_storage.get_min_energy_schedule(
                inp.timestamps
            )
            for t in range(num_steps):
                model += (
                    variables[f"{prefix}_energy_kwh"][t] >= min_energy_schedule[t],
                    f"ww_min_energy_schedule_{t}",
                )

            # SG-Ready: Dynamische WW-Speicher Obergrenze (BWP v1.1)
            if self.heat_pump.sg_ready and "hp_sg3" in variables:
                sg3 = variables["hp_sg3"]
                delta_cap_3 = (
                    self.hot_water_storage.volume_liters
                    * ThermalStorage.SPECIFIC_HEAT_WH_PER_L_K
                    * self.heat_pump.sg_temp_raise_3
                    / 1000.0
                )
                for t in range(num_steps):
                    model += (
                        variables[f"{prefix}_energy_kwh"][t]
                        <= self.hot_water_storage.capacity_kwh
                        + delta_cap_3 * sg3[t],
                        f"ww_sg_ready_cap_{t}",
                    )

        if has_ufh:
            heating_slack = [
                pulp.LpVariable(f"heating_slack_{t}", 0) for t in range(num_steps)
            ]

        # ============================================================
        # Elektrische Energiebilanz — generisch ueber milp_components
        # ============================================================
        for t in range(num_steps):
            supply = float(inp.pv_generation_kw[t]) + grid_buy[t]
            demand = float(inp.household_load_kw[t]) + grid_sell[t]

            for c in milp_components:
                supply = supply + c.electrical_supply(variables, t)
                demand = demand + c.electrical_demand(variables, t)

            model += supply == demand, f"energy_balance_{t}"

        # Einspeisung nur PV
        for t in range(num_steps):
            model += (
                grid_sell[t] <= float(inp.pv_generation_kw[t]),
                f"feed_in_pv_limit_{t}",
            )

        # §14a Drosselung — Summe aller is_par14a_curtailable Lasten
        if inp.par14a_enabled and inp.par14a_curtailed_steps:
            curtailable = [c for c in milp_components if c.is_par14a_curtailable]
            for t in inp.par14a_curtailed_steps:
                if 0 <= t < num_steps:
                    controllable = pulp.lpSum(
                        c.electrical_demand(variables, t) for c in curtailable
                    )
                    model += (
                        controllable <= inp.par14a_curtailment_kw,
                        f"par14a_curtail_{t}",
                    )

        # ============================================================
        # Zielfunktion
        # ============================================================
        cost = pulp.lpSum(
            grid_buy[t] * float(inp.prices_ct_kwh[t]) * dt_h
            - grid_sell[t] * float(inp.feed_in_tariff_ct_kwh) * dt_h
            for t in range(num_steps)
        )

        if heating_slack is not None:
            cost += pulp.lpSum(
                heating_slack[t] * UNMET_HEAT_PENALTY_CT * dt_h
                for t in range(num_steps)
            )
        if ww_slack is not None:
            cost += pulp.lpSum(
                ww_slack[t] * UNMET_HEAT_PENALTY_CT * dt_h
                for t in range(num_steps)
            )

        # Batterie-Alterungskosten (PDF Speichergruppe, Kap. 3+4)
        # Durchsatz (charge + discharge) wird mit c_aging/2 gewichtet,
        # weil ein Aequivalent-Vollzyklus = 1x laden + 1x entladen.
        if (
            self.battery
            and self.battery.enabled
            and self.battery.aging_cost_enabled
        ):
            c_aging_half_ct = self.battery.aging_cost_ct_per_kwh / 2.0
            if c_aging_half_ct > 0:
                cost += pulp.lpSum(
                    (variables["bat_charge"][t] + variables["bat_discharge"][t])
                    * c_aging_half_ct * dt_h
                    for t in range(num_steps)
                )

        model += cost

        # ============================================================
        # Loesen
        # ============================================================
        try:
            solver = pulp.HiGHS_CMD(msg=0, timeLimit=120)
            model.solve(solver)
        except Exception:
            solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=120)
            model.solve(solver)
        solve_time = time.time() - t_start

        status = pulp.LpStatus[model.status]
        if model.status != pulp.constants.LpStatusOptimal:
            diag = []
            if self.battery and self.battery.enabled:
                diag.append("Batterie")
            if has_hp:
                diag.append("WP")
            if has_ufh:
                diag.append("FBH")
            if has_ww:
                diag.append("WW-Speicher")
            active_wbs = [wb.name for wb in self.wallboxes if wb.enabled]
            if active_wbs:
                diag.append(f"Wallbox({','.join(active_wbs)})")

            return OptimizationResult(
                success=False,
                solver_status=f"{status} | Aktive Komp.: {', '.join(diag) or 'keine'} | "
                f"Schritte: {num_steps}",
                solve_time_s=solve_time,
            )

        # ============================================================
        # Ergebnisse extrahieren
        # ============================================================
        result = OptimizationResult(
            success=True,
            solver_status=status,
            solve_time_s=solve_time,
            total_cost_eur=pulp.value(model.objective) / 100.0,
            grid_buy_kw=np.array([v.varValue or 0.0 for v in grid_buy]),
            grid_sell_kw=np.array([v.varValue or 0.0 for v in grid_sell]),
            timestamps=inp.timestamps,
            # Default SG-Ready: Normalbetrieb, wird ggf. von HP.extract_result ueberschrieben
            sg_ready_state=np.full(num_steps, 2),
        )

        # Generischer Extraktions-Loop — jede Komponente schreibt ihre
        # Felder selbst ins Result.
        for c in milp_components:
            c.extract_result(result, variables, num_steps, dt_h)

        # Cross-cutting Anpassung: Alterungskosten werden separat als
        # battery_aging_cost_eur gefuehrt; total_cost_eur enthaelt nur
        # die reinen Netzkosten (fairer Vergleich mit der Baseline).
        if result.battery_aging_cost_eur > 0:
            result.total_cost_eur -= result.battery_aging_cost_eur

        # KPIs
        from emos_light.utils.kpi import calculate_kpis
        result = calculate_kpis(result, inp)

        return result
