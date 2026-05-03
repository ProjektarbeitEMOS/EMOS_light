"""Wallbox Komponentenmodell fuer EMOS.

MILP-Modell mit Ladeleistungsoptimierung, Mindestleistung,
EV-Anwesenheits-Constraint und Paragraph-14a-Bewusstsein.
"""

from typing import Any

import pulp

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_on_off_power_link,
    make_binary_array,
    make_var_array,
    step_hours,
)


class Wallbox(MILPComponent):
    """Wallbox mit Paragraph-14a-Bewusstsein und Phasenumschaltung.

    Phasenumschaltung:
        1-phasig: 1.4 - 3.7 kW (6A - 16A bei 230V)
        3-phasig: 4.2 - 11.0 kW (6A - 16A bei 3x230V)

    Config-Parameter:
        max_power_kw (float): Maximale Ladeleistung in kW.
        min_power_kw (float): Minimale Ladeleistung wenn aktiv (kW).
        phases (int): Anzahl Phasen (1 oder 3).
        ev_battery_capacity_kwh (float): EV-Batteriekapazitaet in kWh.
        target_soc (float): Ziel-SOC (0-1).
        current_soc (float): Aktueller SOC (0-1).
        departure_hour (int): Abfahrtsstunde (0-23).
        arrival_hour (int): Ankunftsstunde (0-23).
        charging_efficiency (float): Ladewirkungsgrad (0-1).
    """

    # Typische Leistungsbereiche pro Phase
    PHASE_LIMITS = {
        1: {"min_kw": 1.4, "max_kw": 3.7},
        3: {"min_kw": 4.2, "max_kw": 11.0},
    }

    def __init__(self, name: str, config: dict):
        # Name normalisieren (keine Leerzeichen/Sonderzeichen fuer Variablennamen)
        safe_name = name.replace(" ", "_").replace("-", "_")
        super().__init__(safe_name, config)
        self.max_power_kw = config.get("max_power_kw", 11.0)
        self.min_power_kw = config.get("min_power_kw", 4.2)
        self.phases = config.get("phases", 3)
        self.ev_capacity_kwh = config.get("ev_battery_capacity_kwh", 60.0)
        self.target_soc = config.get("target_soc", 0.8)
        self.current_soc = config.get("current_soc", 0.3)
        self.departure_hour = config.get("departure_hour", 7)
        self.arrival_hour = config.get("arrival_hour", 17)
        self.charging_efficiency = config.get("charging_efficiency", 0.92)

        # Leistungsgrenzen basierend auf Phasenkonfiguration anpassen
        phase_limits = self.PHASE_LIMITS.get(self.phases, self.PHASE_LIMITS[3])
        self.max_power_kw = min(self.max_power_kw, phase_limits["max_kw"])
        self.min_power_kw = max(self.min_power_kw, phase_limits["min_kw"])

    @property
    def energy_needed_kwh(self) -> float:
        """Berechnet die benoetigte Ladeenergie in kWh (AC-seitig).

        energy_needed = (target_soc - current_soc) * capacity / efficiency
        """
        delta_soc = max(0.0, self.target_soc - self.current_soc)
        return delta_soc * self.ev_capacity_kwh / self.charging_efficiency

    # ------------------------------------------------------------------
    # Anwesenheitslogik
    # ------------------------------------------------------------------

    def _is_ev_present(self, hour: int) -> bool:
        """Prueft, ob das EV in der gegebenen Stunde am Stecker ist.

        Tagsszenario  (arrival <= departure): anwesend [arrival, departure)
        Nachtszenario (arrival >  departure): anwesend [arrival, 24) ∪ [0, departure)
        """
        if self.arrival_hour <= self.departure_hour:
            return self.arrival_hour <= hour < self.departure_hour
        return hour >= self.arrival_hour or hour < self.departure_hour

    # ------------------------------------------------------------------
    # MILP-Schnittstelle
    # ------------------------------------------------------------------

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Wallbox-Variablen.

        Variablen:
            wb_<name>_power[t]: Ladeleistung in kW (>= 0)
            wb_<name>_on[t]:    Binaer - Wallbox aktiv (fuer Mindestleistung)
        """
        prefix = f"wb_{self.name}"
        return {
            f"wb_{self.name}_power": make_var_array(
                f"{prefix}_power", num_steps, low=0, high=self.max_power_kw,
            ),
            f"wb_{self.name}_on": make_binary_array(
                f"{prefix}_on", num_steps,
            ),
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Wallbox-Constraints zum Modell hinzu.

        Constraints:
            1. Ladeleistung an on/off-Variable gekoppelt (Min und Max)
            2. EV-Anwesenheit: power = 0 ausserhalb Anwesenheitszeit
            3. Mindestlademenge: sum(power * dt) >= energy_needed
        """
        prefix = f"wb_{self.name}"
        dt_h = step_hours(step_minutes)

        power = variables[f"wb_{self.name}_power"]
        on = variables[f"wb_{self.name}_on"]
        num_steps = len(power)

        # 1) Modulationsbereich (Min/Max gekoppelt an on/off)
        add_on_off_power_link(
            model, power, on,
            max_power=self.max_power_kw,
            min_power=self.min_power_kw,
            name=prefix,
        )

        # 2) EV-Anwesenheit: ausserhalb der Anwesenheit hart auf 0
        steps_per_hour = 60 // step_minutes
        for t in range(num_steps):
            hour = (t // steps_per_hour) % 24
            if not self._is_ev_present(hour):
                model += (power[t] == 0, f"{prefix}_ev_absent_{t}")

        # 3) Mindestlademenge bis Abfahrt
        total_energy = pulp.lpSum(power[t] * dt_h for t in range(num_steps))
        model += (
            total_energy >= self.energy_needed_kwh,
            f"{prefix}_min_energy",
        )
