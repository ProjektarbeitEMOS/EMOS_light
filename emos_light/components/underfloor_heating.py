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

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_state_balance,
    make_var_array,
    step_hours,
)


class UnderfloorHeating(MILPComponent):
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
        # Komfort-Untergrenze als Anteil der nutzbaren Bandbreite [T_min, T_max].
        # Default 0.25 entspricht ~T_min + 1.5 K (bei 6-K-Band 20-26 °C).
        # Die MILP-Optimierung hat ohne dieses Constraint keinen Pull-Faktor,
        # den Estrich warm zu halten — sie wuerde ihn auf T_min auskuehlen
        # lassen (= Komfortverletzung). Mit dem Constraint zwingt heating_slack
        # eine Strafkostenbelastung auf zu kalte Phasen.
        self.comfort_min_fraction = config.get("comfort_min_fraction", 0.25)
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

    # ------------------------------------------------------------------
    # Konversionen Energie <-> Temperatur
    # ------------------------------------------------------------------

    def energy_to_temp(self, energy_kwh: float) -> float:
        """Rechnet Estrich-Energie in Temperatur um."""
        if self.capacity_kwh_per_k <= 0:
            return self.temp_min
        return self.temp_min + energy_kwh / self.capacity_kwh_per_k

    def temp_to_energy(self, temp_c: float) -> float:
        """Rechnet Temperatur in Estrich-Energie um."""
        delta = max(0, min(temp_c - self.temp_min, self.temp_range_k))
        return self.capacity_kwh_per_k * delta

    @property
    def comfort_min_energy_kwh(self) -> float:
        """Komfort-Mindest-Estrich-Energie als absoluter kWh-Wert.

        = comfort_min_fraction × Komfort-Bandbreite. Wenn der MILP-Estrich
        diese Schwelle unterschreitet, wird heating_slack aktiviert und
        eine Strafkostenbelastung in die Zielfunktion eingebracht — der
        Solver wird darauf reagieren, indem er die WP rechtzeitig
        einschaltet.
        """
        return max(0.0, min(1.0, self.comfort_min_fraction)) * self.total_capacity_kwh

    # ------------------------------------------------------------------
    # MILP-Schnittstelle
    # ------------------------------------------------------------------

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Estrich-Energie- und Waermezufuhr-Variablen.

        Variablen:
            ufh_floor_energy[t]: Thermische Energie im Estrich in kWh
                (0 = temp_min, total_capacity = temp_max)
            ufh_q_floor_in[t]:  Thermische Leistung von WP an Estrich in kW
        """
        return {
            "ufh_floor_energy": make_var_array(
                "ufh_floor_energy", num_steps,
                low=0.0, high=self.total_capacity_kwh,
            ),
            "ufh_q_floor_in": make_var_array(
                "ufh_q_floor_in", num_steps,
                low=0.0, high=self.max_thermal_input_kw,
            ),
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Estrich-Energiebilanz-Constraints zum Modell hinzu.

        E(t) = E(t-1) + q_floor_in(t)*dt - loss_rate * E(t-1) * dt

        Die Verlustrate repraesentiert die Waermeabgabe des Bodens an den Raum.
        Diese Abgabe IST die Raumheizung — wenn der Estrich warm genug bleibt,
        ist der Raum beheizt.
        """
        dt_h = step_hours(step_minutes)
        floor_energy = variables["ufh_floor_energy"]
        q_floor_in = variables["ufh_q_floor_in"]

        add_state_balance(
            model, floor_energy,
            initial=self.initial_energy_kwh,
            rhs_fn=lambda prev, t: (
                prev
                + q_floor_in[t] * dt_h
                - self.loss_rate_per_h * dt_h * prev
            ),
            name="ufh_floor_energy",
        )

    # ------------------------------------------------------------------
    # Bilanz-Beitraege als Waermesenke
    # ------------------------------------------------------------------

    @property
    def heat_sink_id(self) -> str:
        """Bezeichner als Waermesenke fuer den FBH-/Estrich-Pfad."""
        return "floor"

    def heat_demand(self, variables: dict, t: int, sink: str) -> Any:
        """Q_in der FBH = thermische Leistung, die der Estrich aufnimmt."""
        if sink == self.heat_sink_id:
            return variables["ufh_q_floor_in"][t]
        return 0.0

    def extract_result(
        self, result: Any, variables: dict, num_steps: int, dt_h: float,
    ) -> None:
        """Estrichenergie, Bodentemperatur und Waermezufuhr ins Result."""
        import numpy as np
        result.floor_energy_kwh = np.array(
            [v.varValue or 0.0 for v in variables["ufh_floor_energy"]]
        )
        result.floor_temp_c = np.array([
            self.energy_to_temp(e) for e in result.floor_energy_kwh
        ])
        result.q_floor_kw = np.array(
            [v.varValue or 0.0 for v in variables["ufh_q_floor_in"]]
        )
