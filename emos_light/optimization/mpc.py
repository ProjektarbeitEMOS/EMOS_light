"""Model Predictive Control (MPC) fuer EMOS Light.

Rollierender Optimierungshorizont mit Zustandsuebertragung
fuer Batterie-SOC, Estrich-Temperatur und WW-Speicher-Energie.

Day-Ahead-konformer Horizont: An Strommaerkten (EPEX SPOT) werden die
Preise fuer den naechsten Tag i.d.R. um ~13 Uhr CET veroeffentlicht.
Daher passt sich der Horizont an die aktuelle Uhrzeit an:

  vor 13 Uhr Ortszeit → Horizont bis Tagesende heute
                        (morgige Preise noch nicht verfuegbar)
  ab 13 Uhr Ortszeit  → Horizont bis Tagesende morgen
                        (Day-Ahead fuer morgen ist gerade publiziert)

Hard cap: nie ueber das Ende der bereitgestellten Eingangsdaten hinaus.
"""

import datetime

import numpy as np

from emos_light.core.types import TimeSeriesInput, OptimizationResult
from emos_light.optimization.optimizer import EMOSLightOptimizer


# Stunde (Ortszeit), ab der die morgigen Day-Ahead-Preise verfuegbar sind.
DAY_AHEAD_PUBLISH_HOUR = 13


class MPCController:
    """MPC-Wrapper fuer den EMOS Light Optimizer mit Day-Ahead-Horizont."""

    def __init__(
        self,
        optimizer: EMOSLightOptimizer,
        horizon_hours: int | None = None,
        execute_hours: int = 1,
    ):
        """Args:
            optimizer: konfigurierter EMOSLightOptimizer.
            horizon_hours: Wenn None (Default), wird pro Iteration dynamisch
                der Horizont bis zum heutigen oder morgigen Tagesende
                berechnet (siehe Modul-Doku). Wenn gesetzt, wird der
                klassische rollierende MPC mit festem Fenster ausgefuehrt.
            execute_hours: Wie viele Stunden des Fensters werden umgesetzt,
                bevor neu optimiert wird (Default 1).
        """
        self.optimizer = optimizer
        self.horizon_hours = horizon_hours
        self.execute_hours = execute_hours

    def _horizon_end_step(
        self, full_input: TimeSeriesInput, current_step: int
    ) -> int:
        """Endindex (exklusiv) des aktuellen Optimierungsfensters.

        Day-Ahead-konformes Verhalten: vor 13 Uhr Ortszeit reicht das
        Fenster bis Mitternacht heute, ab 13 Uhr bis Mitternacht morgen.
        Limit: nicht ueber die vorhandenen Eingangsdaten hinaus.
        """
        total_steps = len(full_input.prices_ct_kwh)

        # Wenn ein fester Horizont konfiguriert ist, klassisch rollend
        if self.horizon_hours is not None:
            steps_per_hour = 60 // full_input.step_minutes
            return min(
                current_step + self.horizon_hours * steps_per_hour,
                total_steps,
            )

        # Dynamisch: aktuelle Ortszeit bestimmt das Tagesende-Ziel
        now = full_input.timestamps[current_step]
        midnight_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now.hour < DAY_AHEAD_PUBLISH_HOUR:
            # bis Tagesende heute = Mitternacht am Anfang des naechsten Tages
            target = midnight_today + datetime.timedelta(days=1)
        else:
            # bis Tagesende morgen
            target = midnight_today + datetime.timedelta(days=2)

        t0 = full_input.timestamps[0]
        delta_min = (target - t0).total_seconds() / 60.0
        target_step = int(round(delta_min / full_input.step_minutes))
        return max(current_step + 1, min(target_step, total_steps))

    def run_mpc(self, full_input: TimeSeriesInput) -> OptimizationResult:
        """Fuehrt die MPC-Optimierung durch."""
        steps_per_hour = 60 // full_input.step_minutes
        total_steps = len(full_input.prices_ct_kwh)
        execute_steps = self.execute_hours * steps_per_hour

        # Ergebnis-Arrays
        grid_buy_all = np.zeros(total_steps)
        grid_sell_all = np.zeros(total_steps)
        hp_power_all = np.zeros(total_steps)
        batt_charge_all = np.zeros(total_steps)
        batt_discharge_all = np.zeros(total_steps)
        batt_soc_all = np.zeros(total_steps)
        floor_energy_all = np.zeros(total_steps)
        floor_temp_all = np.zeros(total_steps)
        q_floor_all = np.zeros(total_steps)
        ww_energy_all = np.zeros(total_steps)
        ww_temp_all = np.zeros(total_steps)
        q_ww_all = np.zeros(total_steps)
        sg_ready_all = np.full(total_steps, 2)
        wallbox_power_all: dict[str, np.ndarray] = {}
        for wb in self.optimizer.wallboxes:
            if wb.enabled:
                wallbox_power_all[wb.name] = np.zeros(total_steps)

        total_solve_time = 0.0
        current_step = 0

        while current_step < total_steps:
            window_end = self._horizon_end_step(full_input, current_step)
            exec_end = min(current_step + execute_steps, total_steps)

            window_input = self._slice_input(full_input, current_step, window_end)
            window_result = self.optimizer.optimize(window_input)

            if not window_result.success:
                return OptimizationResult(
                    success=False,
                    solver_status=f"MPC failed at step {current_step}: "
                    f"{window_result.solver_status}",
                    solve_time_s=total_solve_time,
                )

            total_solve_time += window_result.solve_time_s
            n_exec = exec_end - current_step

            grid_buy_all[current_step:exec_end] = window_result.grid_buy_kw[:n_exec]
            grid_sell_all[current_step:exec_end] = window_result.grid_sell_kw[:n_exec]

            if len(window_result.hp_power_kw) > 0:
                hp_power_all[current_step:exec_end] = window_result.hp_power_kw[:n_exec]
            if len(window_result.batt_charge_kw) > 0:
                batt_charge_all[current_step:exec_end] = window_result.batt_charge_kw[:n_exec]
                batt_discharge_all[current_step:exec_end] = window_result.batt_discharge_kw[:n_exec]
                batt_soc_all[current_step:exec_end] = window_result.batt_soc_kwh[:n_exec]
            if len(window_result.floor_energy_kwh) > 0:
                floor_energy_all[current_step:exec_end] = window_result.floor_energy_kwh[:n_exec]
                floor_temp_all[current_step:exec_end] = window_result.floor_temp_c[:n_exec]
            if len(window_result.q_floor_kw) > 0:
                q_floor_all[current_step:exec_end] = window_result.q_floor_kw[:n_exec]
            if len(window_result.ww_storage_energy_kwh) > 0:
                ww_energy_all[current_step:exec_end] = window_result.ww_storage_energy_kwh[:n_exec]
                ww_temp_all[current_step:exec_end] = window_result.ww_storage_temp_c[:n_exec]
            if len(window_result.q_ww_kw) > 0:
                q_ww_all[current_step:exec_end] = window_result.q_ww_kw[:n_exec]
            if len(window_result.sg_ready_state) > 0:
                sg_ready_all[current_step:exec_end] = window_result.sg_ready_state[:n_exec]

            for wb_name, wb_arr in window_result.wallbox_power_kw.items():
                if wb_name in wallbox_power_all:
                    wallbox_power_all[wb_name][current_step:exec_end] = wb_arr[:n_exec]

            self._update_initial_conditions(window_result, n_exec - 1)
            current_step = exec_end

        result = OptimizationResult(
            success=True,
            solver_status="MPC_Optimal",
            solve_time_s=total_solve_time,
            grid_buy_kw=grid_buy_all,
            grid_sell_kw=grid_sell_all,
            hp_power_kw=hp_power_all,
            batt_charge_kw=batt_charge_all,
            batt_discharge_kw=batt_discharge_all,
            batt_soc_kwh=batt_soc_all,
            floor_energy_kwh=floor_energy_all,
            floor_temp_c=floor_temp_all,
            q_floor_kw=q_floor_all,
            ww_storage_energy_kwh=ww_energy_all,
            ww_storage_temp_c=ww_temp_all,
            q_ww_kw=q_ww_all,
            sg_ready_state=sg_ready_all,
            wallbox_power_kw=wallbox_power_all,
            timestamps=full_input.timestamps,
        )

        from emos_light.utils.kpi import calculate_kpis
        result = calculate_kpis(result, full_input)

        return result

    def _slice_input(
        self, full_input: TimeSeriesInput, start: int, end: int
    ) -> TimeSeriesInput:
        """Schneidet ein Zeitfenster aus."""
        return TimeSeriesInput(
            prices_ct_kwh=full_input.prices_ct_kwh[start:end],
            pv_generation_kw=full_input.pv_generation_kw[start:end],
            household_load_kw=full_input.household_load_kw[start:end],
            heating_demand_kw=full_input.heating_demand_kw[start:end],
            hot_water_demand_kw=full_input.hot_water_demand_kw[start:end],
            outside_temp_c=full_input.outside_temp_c[start:end],
            timestamps=full_input.timestamps[start:end],
            step_minutes=full_input.step_minutes,
            feed_in_tariff_ct_kwh=full_input.feed_in_tariff_ct_kwh,
            max_grid_power_kw=full_input.max_grid_power_kw,
            par14a_enabled=full_input.par14a_enabled,
            par14a_curtailment_kw=full_input.par14a_curtailment_kw,
            par14a_curtailed_steps=[
                s - start for s in full_input.par14a_curtailed_steps
                if start <= s < end
            ],
        )

    def _update_initial_conditions(
        self, result: OptimizationResult, last_exec_idx: int
    ) -> None:
        """Aktualisiert Anfangsbedingungen fuer naechstes MPC-Fenster."""
        # Batterie-SOC
        if (
            self.optimizer.battery
            and self.optimizer.battery.enabled
            and len(result.batt_soc_kwh) > last_exec_idx
        ):
            new_soc_kwh = result.batt_soc_kwh[last_exec_idx]
            self.optimizer.battery.initial_soc = (
                new_soc_kwh / self.optimizer.battery.capacity_kwh
            )

        # Estrich-Temperatur
        if (
            self.optimizer.underfloor_heating
            and self.optimizer.underfloor_heating.enabled
            and len(result.floor_energy_kwh) > last_exec_idx
        ):
            new_energy = result.floor_energy_kwh[last_exec_idx]
            self.optimizer.underfloor_heating.initial_energy_kwh = new_energy
            self.optimizer.underfloor_heating.initial_temp = (
                self.optimizer.underfloor_heating.energy_to_temp(new_energy)
            )

        # WW-Speicher
        if (
            self.optimizer.hot_water_storage
            and self.optimizer.hot_water_storage.enabled
            and len(result.ww_storage_energy_kwh) > last_exec_idx
        ):
            new_energy = result.ww_storage_energy_kwh[last_exec_idx]
            self.optimizer.hot_water_storage.initial_energy_kwh = new_energy
            self.optimizer.hot_water_storage.initial_temp_c = (
                self.optimizer.hot_water_storage.energy_to_temp(new_energy)
            )

        # Wallbox-SOC
        dt_h = (self.optimizer.wallboxes[0].config.get("step_minutes", 15) / 60.0
                if self.optimizer.wallboxes else 0.25)
        for wb in self.optimizer.wallboxes:
            if wb.enabled and wb.name in result.wallbox_power_kw:
                wb_power = result.wallbox_power_kw[wb.name]
                if len(wb_power) > last_exec_idx:
                    energy_charged = float(sum(wb_power[:last_exec_idx + 1]) * dt_h)
                    soc_delta = energy_charged * wb.charging_efficiency / wb.ev_capacity_kwh
                    wb.current_soc = min(wb.target_soc, wb.current_soc + soc_delta)
