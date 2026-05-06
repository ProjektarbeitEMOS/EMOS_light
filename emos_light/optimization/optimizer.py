"""MILP-Optimierungsengine fuer EMOS Light.

Thermische Topologie:
    WP --+-- FBH --> Estrich (therm. Speicher) --> Raum
         +-- WW-Speicher --> Frischwasserstation --> Brauchwasser

Entscheidungsvariablen (thermisch):
    hp_power_el[t]:     Elektrische WP-Leistung gesamt
    q_floor[t]:         Thermische Leistung an FBH/Estrich
    q_ww[t]:            Thermische Leistung an WW-Speicher
    ufh_floor_energy[t]: Thermische Energie im Estrich
    ww_energy_kwh[t]:   Thermische Energie im WW-Speicher
    hp_power_floor[t]:  Elektr. WP-Leistung fuer FBH (COP @ W35)
    hp_power_ww[t]:     Elektr. WP-Leistung fuer WW (COP @ W55)
    hp_sg1[t]:          SG-Ready Zustand 1 (Lastabwurf)
    hp_sg3[t]:          SG-Ready Zustand 3 (Verstaerkt)
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

        # Sammelliste aller aktiven MILP-Komponenten — nach dem Setup
        # iteriert die Bilanzschleife generisch ueber diese.
        milp_components: list = []

        # ============================================================
        # Batterie
        # ============================================================
        if self.battery and self.battery.enabled:
            batt_vars = self.battery.get_optimization_variables(num_steps, model)
            variables.update(batt_vars)
            self.battery.add_constraints(model, variables, inp.step_minutes)
            milp_components.append(self.battery)

        # ============================================================
        # Waermepumpe
        # ============================================================
        hp_active = False
        if self.heat_pump and self.heat_pump.enabled:
            hp_vars = self.heat_pump.get_optimization_variables(num_steps, model)
            variables.update(hp_vars)
            self.heat_pump.add_constraints(model, variables, inp.step_minutes)
            milp_components.append(self.heat_pump)
            hp_active = True

        if "hp_power" not in variables:
            variables["hp_power"] = [
                pulp.LpVariable(f"hp_power_{t}", 0, 0) for t in range(num_steps)
            ]

        # ============================================================
        # Thermisches Modell: Estrich + WW-Speicher
        # Getrennte COP-Berechnung fuer FBH (W35) und WW (W55)
        # basierend auf Kennfeld aroTHERM plus
        # ============================================================
        has_ufh = self.underfloor_heating and self.underfloor_heating.enabled
        has_ww = self.hot_water_storage and self.hot_water_storage.enabled
        has_fws = self.fresh_water_station and self.fresh_water_station.enabled
        has_hp = hp_active

        if not has_hp:
            has_ufh = False
            has_ww = False

        # COP-Zeitreihen fuer beide thermische Pfade
        cop_heating = None
        cop_dhw = None
        if has_hp:
            cop_heating = self.heat_pump.calculate_cop_heating(inp.outside_temp_c)
            cop_dhw = self.heat_pump.calculate_cop_dhw(inp.outside_temp_c)

        # WP-Waermesplit mit getrennten COPs
        if has_hp and (has_ufh or has_ww):
            max_cop = float(max(
                np.max(cop_heating) if cop_heating is not None else 1,
                np.max(cop_dhw) if cop_dhw is not None else 1,
            ))
            max_thermal = self.heat_pump.max_power_kw * max_cop

            if has_ufh:
                ufh_vars = self.underfloor_heating.get_optimization_variables(num_steps, model)
                variables.update(ufh_vars)
                self.underfloor_heating.add_constraints(model, variables, inp.step_minutes)

            q_ww = None
            if has_ww:
                q_ww = [
                    pulp.LpVariable(f"q_ww_{t}", 0, max_thermal)
                    for t in range(num_steps)
                ]
                variables["q_ww"] = q_ww

            # Beide Pfade aktiv → elektr. Leistung aufteilen
            if has_ufh and has_ww:
                hp_power_floor = [
                    pulp.LpVariable(f"hp_power_floor_{t}", 0, self.heat_pump.max_power_kw)
                    for t in range(num_steps)
                ]
                hp_power_ww = [
                    pulp.LpVariable(f"hp_power_ww_{t}", 0, self.heat_pump.max_power_kw)
                    for t in range(num_steps)
                ]
                variables["hp_power_floor"] = hp_power_floor
                variables["hp_power_ww"] = hp_power_ww

                for t in range(num_steps):
                    # Elektr. Leistungsaufteilung
                    model += (
                        variables["hp_power"][t] == hp_power_floor[t] + hp_power_ww[t],
                        f"hp_power_split_{t}",
                    )
                    # Thermische Leistung je Pfad mit eigenem COP
                    model += (
                        variables["ufh_q_floor_in"][t] == hp_power_floor[t] * float(cop_heating[t]),
                        f"heat_to_floor_{t}",
                    )
                    model += (
                        q_ww[t] == hp_power_ww[t] * float(cop_dhw[t]),
                        f"heat_to_ww_{t}",
                    )

            elif has_ufh:
                for t in range(num_steps):
                    model += (
                        variables["ufh_q_floor_in"][t]
                        == variables["hp_power"][t] * float(cop_heating[t]),
                        f"heat_to_floor_{t}",
                    )

            elif has_ww:
                for t in range(num_steps):
                    model += (
                        q_ww[t]
                        == variables["hp_power"][t] * float(cop_dhw[t]),
                        f"heat_to_ww_{t}",
                    )

        # ============================================================
        # Warmwasserspeicher
        # ============================================================
        heating_slack = None
        ww_slack = None

        if has_ww:
            ww_vars = self.hot_water_storage.get_optimization_variables(num_steps, model)
            variables.update(ww_vars)

            prefix = self.hot_water_storage.prefix

            ww_slack = [
                pulp.LpVariable(f"ww_slack_{t}", 0) for t in range(num_steps)
            ]

            # Waermezufuhr von WP
            for t in range(num_steps):
                model += (
                    variables[f"{prefix}_q_in"][t] == variables["q_ww"][t],
                    f"ww_q_in_link_{t}",
                )

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

            self.hot_water_storage.add_constraints(model, variables, inp.step_minutes)

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
            if (
                has_hp
                and self.heat_pump.sg_ready
                and "hp_sg3" in variables
            ):
                sg3 = variables["hp_sg3"]

                # Zusaetzliche Kapazitaet durch Temperaturerhoehung in State 3
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

        # Slack fuer Heizung (Estrich)
        if has_ufh:
            heating_slack = [
                pulp.LpVariable(f"heating_slack_{t}", 0) for t in range(num_steps)
            ]

        # ============================================================
        # Wallboxen
        # ============================================================
        active_wallboxes = [wb for wb in self.wallboxes if wb.enabled]
        for wb in active_wallboxes:
            wb_vars = wb.get_optimization_variables(num_steps, model)
            variables.update(wb_vars)
            wb.add_constraints(model, variables, inp.step_minutes)
            milp_components.append(wb)

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

        # §14a Drosselung — Summe der drosselbaren Verbraucher
        # (aktuell hartcodiert: WP + Wallboxen; in Phase 6 ggf. ueber
        # ein Komponenten-Property "is_par14a_curtailable" generalisieren)
        if inp.par14a_enabled and inp.par14a_curtailed_steps:
            for t in inp.par14a_curtailed_steps:
                if 0 <= t < num_steps:
                    controllable = variables["hp_power"][t]
                    for wb in active_wallboxes:
                        controllable = controllable + variables[f"wb_{wb.name}_power"][t]
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
        )

        # Batterie
        if self.battery and self.battery.enabled:
            result.batt_charge_kw = np.array(
                [v.varValue or 0.0 for v in variables["bat_charge"]]
            )
            result.batt_discharge_kw = np.array(
                [v.varValue or 0.0 for v in variables["bat_discharge"]]
            )
            result.batt_soc_kwh = np.array(
                [v.varValue or 0.0 for v in variables["bat_soc"]]
            )
            # Alterungskosten-KPIs (PDF Speichergruppe)
            throughput_kwh = float(
                (result.batt_charge_kw.sum() + result.batt_discharge_kw.sum()) * dt_h
            )
            result.battery_throughput_kwh = throughput_kwh
            c_aging_ct = self.battery.aging_cost_ct_per_kwh
            result.battery_aging_cost_eur = (
                throughput_kwh / 2.0 * c_aging_ct / 100.0
            )
            usable = self.battery.usable_capacity_kwh
            if usable > 0:
                result.battery_equivalent_cycles = throughput_kwh / (2.0 * usable)
            # total_cost_eur soll nur die reinen Netzkosten enthalten
            # (fairer Vergleich mit Baseline, die keine Alterung beruecksichtigt).
            # Alterungskosten werden separat als battery_aging_cost_eur ausgewiesen.
            result.total_cost_eur -= result.battery_aging_cost_eur

        # Waermepumpe
        result.hp_power_kw = np.array(
            [v.varValue or 0.0 for v in variables["hp_power"]]
        )

        # Estrich / Fussbodenheizung
        if has_ufh and "ufh_floor_energy" in variables:
            result.floor_energy_kwh = np.array(
                [v.varValue or 0.0 for v in variables["ufh_floor_energy"]]
            )
            result.floor_temp_c = np.array([
                self.underfloor_heating.energy_to_temp(e)
                for e in result.floor_energy_kwh
            ])
            result.q_floor_kw = np.array(
                [v.varValue or 0.0 for v in variables["ufh_q_floor_in"]]
            )

        # WW-Speicher
        if has_ww:
            prefix = self.hot_water_storage.prefix
            key = f"{prefix}_energy_kwh"
            if key in variables:
                result.ww_storage_energy_kwh = np.array(
                    [v.varValue or 0.0 for v in variables[key]]
                )
                result.ww_storage_temp_c = np.array([
                    self.hot_water_storage.energy_to_temp(e)
                    for e in result.ww_storage_energy_kwh
                ])
            if "q_ww" in variables:
                result.q_ww_kw = np.array(
                    [v.varValue or 0.0 for v in variables["q_ww"]]
                )

        # SG-Ready Zustand (BWP v1.1: 1=Lastabwurf, 2=Normal, 3=Verstaerkt)
        if has_hp and self.heat_pump.sg_ready and "hp_sg3" in variables:
            sg1_vals = np.array([v.varValue or 0.0 for v in variables["hp_sg1"]])
            sg3_vals = np.array([v.varValue or 0.0 for v in variables["hp_sg3"]])
            result.sg_ready_state = np.where(
                sg1_vals > 0.5, 1, np.where(sg3_vals > 0.5, 3, 2)
            )
        else:
            result.sg_ready_state = np.full(num_steps, 2)

        # Wallboxen
        for wb in self.wallboxes:
            if wb.enabled:
                wb_key = f"wb_{wb.name}_power"
                result.wallbox_power_kw[wb.name] = np.array(
                    [v.varValue or 0.0 for v in variables[wb_key]]
                )

        # KPIs
        from emos_light.utils.kpi import calculate_kpis
        result = calculate_kpis(result, inp)

        return result
