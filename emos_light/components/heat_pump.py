"""Waermepumpe mit SG-Ready 4-Zustandsmodell fuer EMOS Light.

Zwei thermische Ausgaenge:
  1. Fussbodenheizung (Estrich)
  2. Warmwasserspeicher

SG-Ready Zustaende als Optimierungsvariablen:
  Zustand 2 (Normal): Standard-Betrieb
  Zustand 3 (Empfehlung): Erhoehte WW-Speicher-Maximaltemperatur
  Zustand 4 (Anlaufbefehl): WP auf Max, WW-Speicher-Max stark erhoeht
"""

from typing import Any

import numpy as np
import pulp

from emos_light.components.base import Component


class HeatPump(Component):
    """Waermepumpe mit SG-Ready und Mindestlaufzeiten.

    Config-Parameter:
        max_electrical_power_kw (float): Max. elektr. Leistung in kW.
        min_electrical_power_kw (float): Min. elektr. Leistung wenn an (kW).
        cop_nominal (float): Nominaler COP bei Referenztemperatur.
        cop_reference_temp_c (float): Referenz-Aussentemperatur (Grad C).
        min_run_time_minutes (int): Mindestlaufzeit in Minuten.
        min_pause_time_minutes (int): Mindestpausenzeit in Minuten.
        sg_ready (bool): SG-Ready-Schnittstelle vorhanden.
        sg_ready_temp_raise_state3_c (float): Temperaturerhoehung WW-Speicher State 3.
        sg_ready_temp_raise_state4_c (float): Temperaturerhoehung WW-Speicher State 4.
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.max_power_kw = config.get("max_electrical_power_kw", 5.0)
        self.min_power_kw = config.get("min_electrical_power_kw", 1.0)
        self.cop_nominal = config.get("cop_nominal", 4.0)
        self.cop_ref_temp = config.get("cop_reference_temp_c", 7.0)
        self.min_run_minutes = config.get("min_run_time_minutes", 15)
        self.min_pause_minutes = config.get("min_pause_time_minutes", 15)
        self.sg_ready = config.get("sg_ready", True)
        self.sg_temp_raise_3 = config.get("sg_ready_temp_raise_state3_c", 5.0)
        self.sg_temp_raise_4 = config.get("sg_ready_temp_raise_state4_c", 10.0)

    def calculate_cop(self, outside_temp_c: np.ndarray) -> np.ndarray:
        """Berechnet COP basierend auf Aussentemperatur (Carnot-basiert)."""
        cop = self.cop_nominal * (1.0 + 0.025 * (outside_temp_c - self.cop_ref_temp))
        return np.clip(cop, 1.5, 6.0)

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt WP-Variablen inkl. SG-Ready Zustaende.

        Variablen:
            hp_on[t]: Binaer — WP an/aus
            hp_power[t]: Elektrische Leistung in kW
            sg_state_3[t]: Binaer — SG-Ready Zustand 3 aktiv
            sg_state_4[t]: Binaer — SG-Ready Zustand 4 aktiv
        """
        hp_on = [
            pulp.LpVariable(f"hp_on_{t}", cat=pulp.LpBinary)
            for t in range(num_steps)
        ]
        hp_power = [
            pulp.LpVariable(f"hp_power_{t}", lowBound=0, upBound=self.max_power_kw)
            for t in range(num_steps)
        ]

        result = {"hp_on": hp_on, "hp_power": hp_power}

        if self.sg_ready:
            sg_state_3 = [
                pulp.LpVariable(f"sg_state_3_{t}", cat=pulp.LpBinary)
                for t in range(num_steps)
            ]
            sg_state_4 = [
                pulp.LpVariable(f"sg_state_4_{t}", cat=pulp.LpBinary)
                for t in range(num_steps)
            ]
            result["sg_state_3"] = sg_state_3
            result["sg_state_4"] = sg_state_4

        return result

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt WP-Constraints inkl. SG-Ready hinzu.

        Constraints:
            1. Leistung nur wenn an: hp_power <= max_power * hp_on
            2. Mindestleistung wenn an: hp_power >= min_power * hp_on
            3. Mindestlaufzeit
            4. Mindestpausenzeit
            5. SG-Ready: Zustaende 3 und 4 gegenseitig ausschliessend
            6. SG-Ready State 4: Forcierter Betrieb bei Max-Leistung
        """
        hp_on = variables["hp_on"]
        hp_power = variables["hp_power"]
        num_steps = len(hp_on)

        min_run_steps = max(1, self.min_run_minutes // step_minutes)
        min_pause_steps = max(1, self.min_pause_minutes // step_minutes)

        for t in range(num_steps):
            model += hp_power[t] <= self.max_power_kw * hp_on[t], f"hp_max_power_{t}"
            model += hp_power[t] >= self.min_power_kw * hp_on[t], f"hp_min_power_{t}"

        # Mindestlaufzeit
        for t in range(1, num_steps):
            for k in range(1, min_run_steps):
                if t + k < num_steps:
                    model += (
                        hp_on[t] - hp_on[t - 1] <= hp_on[t + k],
                        f"hp_min_run_{t}_{k}",
                    )

        # Mindestpausenzeit
        for t in range(1, num_steps):
            for k in range(1, min_pause_steps):
                if t + k < num_steps:
                    model += (
                        hp_on[t - 1] - hp_on[t] <= 1 - hp_on[t + k],
                        f"hp_min_pause_{t}_{k}",
                    )

        # SG-Ready Constraints
        if self.sg_ready and "sg_state_3" in variables:
            sg3 = variables["sg_state_3"]
            sg4 = variables["sg_state_4"]

            for t in range(num_steps):
                # Zustaende 3 und 4 gegenseitig ausschliessend
                model += sg3[t] + sg4[t] <= 1, f"sg_exclusive_{t}"

                # SG-Ready nur wenn WP an
                model += sg3[t] <= hp_on[t], f"sg3_needs_on_{t}"
                model += sg4[t] <= hp_on[t], f"sg4_needs_on_{t}"

                # State 4: WP muss auf Max laufen
                model += (
                    hp_power[t] >= self.max_power_kw * sg4[t],
                    f"sg4_force_max_{t}",
                )
