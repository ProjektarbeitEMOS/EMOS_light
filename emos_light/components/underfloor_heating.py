"""Fussbodenheizung mit Estrich-Thermische-Masse-Modell fuer EMOS Light.

Der Betonestrich ist der einzige thermische Speicher fuer die Raumheizung.
Kein separater Heizungspuffer-Tank.

Physik:
    Thermische Kapazitaet: C = Flaeche * Dicke * Dichte * spez. Waerme
    Fuer 150 m2, 65 mm, 2000 kg/m3, 1000 J/(kg*K): C = 19.5 MJ = 5.42 kWh/K
    Nutzbare Kapazitaet ueber 6K Komfortband (20-26 C): ~32 kWh

Energiebilanz:
    E(t) = E(t-1) + q_floor_in(t)*dt - q_floor_to_room(t)*dt

    q_floor_to_room = h_surface * A_floor / 1000 * (T_floor[t-1] − T_innen[t-1])

Seit der MILP-Erweiterung Mai 2026 (siehe Building) ist T_innen eine
eigene Zustandsvariable des Solvers. Das frueher hier benutzte
linearisierte Verlustmodell (``loss_rate · E_floor[t-1]``) entfaellt
damit — die Waerme, die der Boden abgibt, fliesst nun explizit in den
Raum-Bilanzknoten ("room"-Senke). Existiert keine aktive Raum-Senke
(z.B. weil Building deaktiviert ist), faellt das Modul auf das alte
Verlustmodell zurueck.

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
        # Initialwert der Raumlufttemperatur (vor t=0) — wird benoetigt, um
        # q_floor_to_room[0] aus den Initialzustaenden zu berechnen, ohne dass
        # t_innen[0] schon "Vorgaenger" hat. Default 21 °C; scenario.py
        # ueberschreibt mit dem Building-Wert.
        self.initial_indoor_temp_c = config.get("initial_indoor_temp_c", 21.0)
        # DEPRECATED (Mai 2026): mit Building als MILPComponent wird die
        # Gebaeudehuelle nun direkt im Raum-Bilanzknoten gerechnet — der
        # Estrich-Lumped-Capacitance-Hack ist nicht mehr noetig. Wert bleibt
        # aus Rueckwaertskompatibilitaet (Default 0) bestehen.
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

        # Vom Optimizer ueber set_active_heat_sinks() befuellt — entscheidet,
        # ob das neue Raum-Modell aktiv ist ("room" in sinks) oder ob das
        # alte Verlustraten-Modell als Fallback laeuft.
        self._active_sinks: set = set()

    def set_active_heat_sinks(self, sinks: set) -> None:
        self._active_sinks = set(sinks)

    @property
    def _room_sink_active(self) -> bool:
        return "room" in self._active_sinks

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

    # ------------------------------------------------------------------
    # MILP-Schnittstelle
    # ------------------------------------------------------------------

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Estrich-Energie- und Waermezufuhr-Variablen.

        Variablen:
            ufh_floor_energy[t]:    Thermische Energie im Estrich in kWh
                (0 = temp_min, total_capacity = temp_max)
            ufh_q_floor_in[t]:      Thermische Leistung von WP an Estrich [kW]
            ufh_q_floor_to_room[t]: Waermestrom Estrich -> Raum [kW], wird
                aus T_floor[t-1] und T_innen[t-1] berechnet. Darf negativ
                werden (Boden kaelter als Raum -> Waermestrom umgekehrt).
                Nur erzeugt, wenn die Raum-Senke aktiv ist.
        """
        result = {
            "ufh_floor_energy": make_var_array(
                "ufh_floor_energy", num_steps,
                low=0.0, high=self.total_capacity_kwh,
            ),
            "ufh_q_floor_in": make_var_array(
                "ufh_q_floor_in", num_steps,
                low=0.0, high=self.max_thermal_input_kw,
            ),
        }
        if self._room_sink_active:
            # Waermestrom Estrich -> Raum kann theoretisch negativ werden
            # (kalter Boden, warmer Raum) — ``low=None`` macht die Variable
            # frei (PuLP-Konvention: kein lowBound).
            result["ufh_q_floor_to_room"] = make_var_array(
                "ufh_q_floor_to_room", num_steps,
                low=None, high=None,
            )
        return result

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Estrich-Energiebilanz-Constraints zum Modell hinzu.

        Zwei Modi:

        1. Raum-Senke aktiv (Building als MILPComponent, "room" in sinks):

               E(t) = E(t-1) + q_floor_in(t)*dt - q_floor_to_room(t)*dt
               q_floor_to_room(t) = h_surface · A / 1000
                                    · (T_floor[t-1] − T_innen[t-1])

           Damit fliesst die abgegebene Waerme explizit in den
           Raum-Bilanzknoten (siehe Building.heat_demand).

        2. Fallback (keine "room"-Senke): klassisches linearisiertes
           Verlustmodell mit ``loss_rate · E(t-1) · dt`` — die Waerme
           verschwindet bilanziell, das Modul ist dann autark vom
           Raum-Knoten.
        """
        dt_h = step_hours(step_minutes)
        floor_energy = variables["ufh_floor_energy"]
        q_floor_in = variables["ufh_q_floor_in"]

        if self._room_sink_active and "ufh_q_floor_to_room" in variables:
            q_to_room = variables["ufh_q_floor_to_room"]
            t_innen = variables.get("t_innen")
            # Kopplung: T_floor[t-1] linear in E_floor[t-1]
            #   T_floor_prev = floor_temp_min + E_floor[t-1] / C_floor_per_k
            # q_floor_to_room[t] = h*A/1000 * (T_floor_prev - T_innen_prev)
            h_a_per_kw_per_k = self.h_surface * self.area_m2 / 1000.0
            for t in range(len(floor_energy)):
                if t == 0:
                    t_floor_prev = self.initial_temp
                    t_innen_prev = self.initial_indoor_temp_c
                else:
                    # T_floor = temp_min + E/C ; ausgedrueckt ueber Variablen
                    t_floor_prev = (
                        self.temp_min
                        + floor_energy[t - 1] / self.capacity_kwh_per_k
                    )
                    t_innen_prev = (
                        t_innen[t - 1] if t_innen is not None
                        else self.initial_indoor_temp_c
                    )
                model += (
                    q_to_room[t]
                    == h_a_per_kw_per_k * (t_floor_prev - t_innen_prev),
                    f"ufh_q_to_room_link_{t}",
                )

            add_state_balance(
                model, floor_energy,
                initial=self.initial_energy_kwh,
                rhs_fn=lambda prev, t: (
                    prev + q_floor_in[t] * dt_h - q_to_room[t] * dt_h
                ),
                name="ufh_floor_energy",
            )
        else:
            # Fallback: altes linearisiertes Verlustmodell
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

    def heat_supply(self, variables: dict, t: int, sink: str) -> Any:
        """Q_out des Estrichs an den Raum (nur wenn Raum-Senke aktiv)."""
        if sink == "room" and "ufh_q_floor_to_room" in variables:
            return variables["ufh_q_floor_to_room"][t]
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
        if "ufh_q_floor_to_room" in variables:
            result.q_floor_to_room_kw = np.array(
                [v.varValue or 0.0 for v in variables["ufh_q_floor_to_room"]]
            )
