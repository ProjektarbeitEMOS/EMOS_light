"""Batteriespeicher Komponentenmodell fuer EMOS.

MILP-Modell mit Lade-/Entladevariablen, SOC-Tracking und
Binaervariablen zur Vermeidung gleichzeitigen Ladens und Entladens.
"""

from typing import Any

import pulp

from emos_light.components.base import Component


class Battery(Component):
    """Batteriespeicher mit SOC-Tracking und Lade-/Entladebegrenzung.

    Config-Parameter:
        capacity_kwh (float): Speicherkapazitaet in kWh.
        max_charge_power_kw (float): Maximale Ladeleistung in kW.
        max_discharge_power_kw (float): Maximale Entladeleistung in kW.
        charge_efficiency (float): Ladewirkungsgrad (0-1).
        discharge_efficiency (float): Entladewirkungsgrad (0-1).
        min_soc (float): Minimaler Ladezustand (0-1).
        max_soc (float): Maximaler Ladezustand (0-1).
        initial_soc (float): Anfangsladezustand (0-1).
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.capacity_kwh = config.get("capacity_kwh", 10.0)
        self.max_charge_kw = config.get("max_charge_power_kw", 5.0)
        self.max_discharge_kw = config.get("max_discharge_power_kw", 5.0)
        self.charge_eff = config.get("charge_efficiency", 0.95)
        self.discharge_eff = config.get("discharge_efficiency", 0.95)
        self.min_soc = config.get("min_soc", 0.1)
        self.max_soc = config.get("max_soc", 0.9)
        self.initial_soc = config.get("initial_soc", 0.5)

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Lade-, Entlade-, SOC- und Binaervariablen.

        Variablen:
            bat_charge[t]: Ladeleistung in kW (>= 0)
            bat_discharge[t]: Entladeleistung in kW (>= 0)
            bat_soc[t]: Ladezustand in kWh
            bat_b_charge[t]: Binaer - Laden aktiv
            bat_b_discharge[t]: Binaer - Entladen aktiv
        """
        prefix = f"bat_{self.name}"

        soc_min_kwh = self.min_soc * self.capacity_kwh
        soc_max_kwh = self.max_soc * self.capacity_kwh

        charge = [
            pulp.LpVariable(f"{prefix}_charge_{t}", lowBound=0, upBound=self.max_charge_kw)
            for t in range(num_steps)
        ]
        discharge = [
            pulp.LpVariable(f"{prefix}_discharge_{t}", lowBound=0, upBound=self.max_discharge_kw)
            for t in range(num_steps)
        ]
        soc = [
            pulp.LpVariable(f"{prefix}_soc_{t}", lowBound=soc_min_kwh, upBound=soc_max_kwh)
            for t in range(num_steps)
        ]
        b_charge = [
            pulp.LpVariable(f"{prefix}_b_charge_{t}", cat=pulp.LpBinary)
            for t in range(num_steps)
        ]
        b_discharge = [
            pulp.LpVariable(f"{prefix}_b_discharge_{t}", cat=pulp.LpBinary)
            for t in range(num_steps)
        ]

        return {
            "batt_charge": charge,
            "batt_discharge": discharge,
            "batt_soc": soc,
            "batt_b_charge": b_charge,
            "batt_b_discharge": b_discharge,
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Batterie-Constraints zum Modell hinzu.

        Constraints:
            1. Kein gleichzeitiges Laden und Entladen (b_charge + b_discharge <= 1)
            2. Ladeleistung nur wenn Laden aktiv (charge <= max * b_charge)
            3. Entladeleistung nur wenn Entladen aktiv (discharge <= max * b_discharge)
            4. SOC-Bilanz: soc[t] = soc[t-1] + charge*eff*dt - discharge/eff*dt
            5. Initialer SOC
        """
        prefix = f"bat_{self.name}"
        dt_h = step_minutes / 60.0  # Zeitschritt in Stunden

        charge = variables["batt_charge"]
        discharge = variables["batt_discharge"]
        soc = variables["batt_soc"]
        b_charge = variables["batt_b_charge"]
        b_discharge = variables["batt_b_discharge"]

        num_steps = len(charge)
        initial_soc_kwh = self.initial_soc * self.capacity_kwh

        for t in range(num_steps):
            # Constraint 1: Kein gleichzeitiges Laden und Entladen
            model += (
                b_charge[t] + b_discharge[t] <= 1,
                f"{prefix}_no_simul_{t}",
            )

            # Constraint 2: Ladeleistung nur bei aktivem Laden
            model += (
                charge[t] <= self.max_charge_kw * b_charge[t],
                f"{prefix}_charge_link_{t}",
            )

            # Constraint 3: Entladeleistung nur bei aktivem Entladen
            model += (
                discharge[t] <= self.max_discharge_kw * b_discharge[t],
                f"{prefix}_discharge_link_{t}",
            )

            # Constraint 4/5: SOC-Bilanzgleichung
            if t == 0:
                model += (
                    soc[t]
                    == initial_soc_kwh
                    + charge[t] * self.charge_eff * dt_h
                    - discharge[t] / self.discharge_eff * dt_h,
                    f"{prefix}_soc_balance_{t}",
                )
            else:
                model += (
                    soc[t]
                    == soc[t - 1]
                    + charge[t] * self.charge_eff * dt_h
                    - discharge[t] / self.discharge_eff * dt_h,
                    f"{prefix}_soc_balance_{t}",
                )
