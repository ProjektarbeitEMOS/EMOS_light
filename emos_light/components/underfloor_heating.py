"""Fussbodenheizung mit Estrich-Thermische-Masse-Modell fuer EMOS Light.

Der Betonestrich ist der einzige thermische Speicher fuer die Raumheizung.
Kein separater Heizungspuffer-Tank.

Physik:
    Thermische Kapazitaet: C = Flaeche * Dicke * Dichte * spez. Waerme
    Fuer 150 m2, 65 mm, 2000 kg/m3, 1000 J/(kg*K): C = 19.5 MJ = 5.42 kWh/K
    Nutzbare Kapazitaet ueber 6K Komfortband (20-26 C): ~32 kWh

Energiebilanz:
    E(t) = E(t-1) + q_floor_in(t)*dt - q_loss_to_room(t)*dt

    q_loss_to_room = h * A * (T_floor - T_room_setpoint)
    In Energieform: proportional zu floor_energy (linearisiert).

Alle Relationen bleiben linear → MILP-kompatibel.
"""

from typing import Any

import numpy as np
import pulp

from emos_light.components.base import Component


class UnderfloorHeating(Component):
    """Fussbodenheizung mit Estrich als thermischem Speicher.

    Config-Parameter:
        heated_area_m2 (float): Beheizte Flaeche in m2.
        screed_thickness_m (float): Estrichdicke in m.
        screed_density_kg_m3 (float): Estrichdichte in kg/m3.
        screed_specific_heat_j_kg_k (float): Spez. Waermekapazitaet in J/(kg*K).
        floor_surface_coefficient_w_m2_k (float): Waermeuebergangskoeff. Boden->Raum.
        supply_temp_max_c (float): Max. Vorlauftemperatur FBH.
        floor_temp_min_c (float): Min. Bodentemperatur (Komfort-Untergrenze).
        floor_temp_max_c (float): Max. Bodentemperatur (Komfort-Obergrenze).
        initial_floor_temp_c (float): Anfangs-Bodentemperatur.
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.area_m2 = config.get("heated_area_m2", 150.0)
        self.thickness_m = config.get("screed_thickness_m", 0.065)
        self.density = config.get("screed_density_kg_m3", 2000.0)
        self.specific_heat = config.get("screed_specific_heat_j_kg_k", 1000.0)
        self.h_surface = config.get("floor_surface_coefficient_w_m2_k", 10.0)
        self.supply_temp_max = config.get("supply_temp_max_c", 35.0)
        self.temp_min = config.get("floor_temp_min_c", 20.0)
        self.temp_max = config.get("floor_temp_max_c", 26.0)
        self.initial_temp = config.get("initial_floor_temp_c", 22.0)
        # Optional: Zusatzkapazitaet aus Gebaeudehuelle (Wand+Luft).
        # Wird von scenario.build_components() aus Building.shell_capacity_kwh_per_k
        # uebergeben. Lumped-Capacitance-Modell: der Estrich repraesentiert dann
        # die gesamte thermische Gebaeudemasse.
        self.additional_capacity_kwh_per_k = config.get(
            "additional_capacity_kwh_per_k", 0.0
        )

        # Thermische Kapazitaet in kWh/K (Estrich + optional Gebaeudehuelle)
        mass_kg = self.area_m2 * self.thickness_m * self.density
        self.estrich_only_capacity_kwh_per_k = (
            mass_kg * self.specific_heat / 3_600_000.0
        )
        self.capacity_kwh_per_k = (
            self.estrich_only_capacity_kwh_per_k
            + self.additional_capacity_kwh_per_k
        )

        # Nutzbare Kapazitaet ueber Komfortband
        self.temp_range_k = self.temp_max - self.temp_min
        self.total_capacity_kwh = self.capacity_kwh_per_k * self.temp_range_k

        # Anfangsenergie (0 = temp_min, total_capacity = temp_max)
        initial_delta = max(0, min(self.initial_temp - self.temp_min, self.temp_range_k))
        self.initial_energy_kwh = self.capacity_kwh_per_k * initial_delta

        # Verlustrate: Waermeabgabe an Raum pro Stunde pro kWh gespeichert
        # q_loss = h * A * (T_floor - T_room) [W]
        # T_floor - T_room = E / (C_kwh_per_k) (da E in kWh relativ zu temp_min)
        # q_loss = h * A / C_kwh_per_k * E [W] = loss_rate * E
        if self.capacity_kwh_per_k > 0:
            self.loss_rate_per_h = (
                self.h_surface * self.area_m2
                / (self.capacity_kwh_per_k * 1000.0)
            )  # [1/h]
        else:
            self.loss_rate_per_h = 0.0

        # Maximale thermische Leistung an den Estrich (von WP via FBH-Kreis)
        # Begrenzt durch Vorlauftemperatur und Flaeche
        self.max_thermal_input_kw = (
            self.h_surface * self.area_m2
            * (self.supply_temp_max - self.temp_min) / 1000.0
        )

    def energy_to_temp(self, energy_kwh: float) -> float:
        """Rechnet Estrich-Energie in Temperatur um."""
        if self.capacity_kwh_per_k <= 0:
            return self.temp_min
        return self.temp_min + energy_kwh / self.capacity_kwh_per_k

    def temp_to_energy(self, temp_c: float) -> float:
        """Rechnet Temperatur in Estrich-Energie um."""
        delta = max(0, min(temp_c - self.temp_min, self.temp_range_k))
        return self.capacity_kwh_per_k * delta

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Estrich-Energie- und Waermezufuhr-Variablen.

        Variablen:
            floor_energy[t]: Thermische Energie im Estrich in kWh
                (0 = temp_min, total_capacity = temp_max)
            q_floor_in[t]: Thermische Leistung von WP an Estrich in kW
        """
        floor_energy = [
            pulp.LpVariable(
                f"floor_energy_{t}",
                lowBound=0.0,
                upBound=self.total_capacity_kwh,
            )
            for t in range(num_steps)
        ]
        q_floor_in = [
            pulp.LpVariable(
                f"q_floor_in_{t}",
                lowBound=0.0,
                upBound=self.max_thermal_input_kw,
            )
            for t in range(num_steps)
        ]

        return {
            "floor_energy": floor_energy,
            "q_floor_in": q_floor_in,
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Estrich-Energiebilanz-Constraints zum Modell hinzu.

        E(t) = E(t-1) + q_floor_in(t)*dt - loss_rate * E(t-1) * dt

        Die Verlustrate repraesentiert die Waermeabgabe des Bodens an den Raum.
        Diese Abgabe IST die Raumheizung — wenn der Estrich warm genug bleibt,
        ist der Raum beheizt.
        """
        dt_h = step_minutes / 60.0
        floor_energy = variables["floor_energy"]
        q_floor_in = variables["q_floor_in"]
        num_steps = len(floor_energy)

        for t in range(num_steps):
            if t == 0:
                e_prev = self.initial_energy_kwh
            else:
                e_prev = floor_energy[t - 1]

            model += (
                floor_energy[t]
                == e_prev
                + q_floor_in[t] * dt_h
                - self.loss_rate_per_h * dt_h * e_prev,
                f"floor_energy_balance_{t}",
            )
