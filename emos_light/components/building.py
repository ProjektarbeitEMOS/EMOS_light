"""Gebaeude-Modell fuer EMOS Light — optimiert fuer Neubau (KfW55/KfW40).

Berechnet temperaturabhaengigen Heizwaermebedarf und Warmwasserbedarf.
Fuer Neubau: keine Nachtabsenkung (FBH mit hoher therm. Masse laeuft kontinuierlich).
"""

import datetime

import numpy as np

from emos_light.components.base import Component


class Building(Component):
    """Gebaeude mit Waerme- und Warmwasserbedarf (Neubau)."""

    BUILDING_STANDARDS = {
        "neubau_enev": 50,
        "kfw55": 35,
        "kfw40": 25,
        "passivhaus": 15,
    }

    HW_PER_PERSON_KWH_DAY = 2.0

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.heated_area_m2 = config.get("heated_area_m2", 150.0)
        self.specific_heat = config.get("specific_heat_demand_kwh_m2a", 35.0)
        self.heating_limit_temp = config.get("heating_limit_temp_c", 16.0)
        self.design_temp = config.get("design_temp_c", -14.0)
        self.indoor_temp = config.get("indoor_temp_c", 21.0)
        self.num_occupants = config.get("num_occupants", 4)
        self.night_setback_c = config.get("night_setback_c", 0.0)
        self.night_start = config.get("night_start_hour", 22)
        self.night_end = config.get("night_end_hour", 6)
        self.building_type = config.get("building_type", "kfw55")

        self.annual_heating_kwh = config.get(
            "annual_heating_kwh",
            self.heated_area_m2 * self.specific_heat,
        )
        self.annual_hot_water_kwh = config.get(
            "annual_hot_water_kwh",
            self.num_occupants * self.HW_PER_PERSON_KWH_DAY * 365,
        )

        self.design_heating_load_kw = config.get(
            "design_heating_load_kw",
            self._estimate_design_load(),
        )

    def _estimate_design_load(self) -> float:
        """Schaetzt die Norm-Heizlast aus Jahresverbrauch."""
        full_load_hours = {
            "neubau_enev": 1800,
            "kfw55": 1600,
            "kfw40": 1500,
            "passivhaus": 1400,
        }
        hours = full_load_hours.get(self.building_type, 1600)
        return self.annual_heating_kwh / hours if hours > 0 else 5.0

    def calculate_heating_demand(
        self,
        outside_temp_c: np.ndarray,
        date: datetime.date,
        step_minutes: int = 15,
    ) -> np.ndarray:
        """Berechnet temperaturabhaengigen Heizwaermebedarf."""
        num_steps = len(outside_temp_c)
        hours = np.linspace(0, 24, num_steps, endpoint=False)

        target_temp = np.full(num_steps, self.indoor_temp)
        if self.night_setback_c > 0:
            for i, h in enumerate(hours):
                hour = h % 24
                if self.night_start > self.night_end:
                    if hour >= self.night_start or hour < self.night_end:
                        target_temp[i] -= self.night_setback_c
                elif self.night_start <= hour < self.night_end:
                    target_temp[i] -= self.night_setback_c

        delta_design = self.indoor_temp - self.design_temp
        delta_t = np.clip(target_temp - outside_temp_c, 0, None)

        if delta_design > 0:
            heating_kw = self.design_heating_load_kw * delta_t / delta_design
        else:
            heating_kw = np.zeros(num_steps)

        heating_kw[outside_temp_c >= self.heating_limit_temp] = 0.0
        return np.round(np.clip(heating_kw, 0, None), 3)

    def calculate_hot_water_demand(
        self, date: datetime.date, num_steps: int = 96,
    ) -> np.ndarray:
        """Berechnet Warmwasserbedarf mit typischem Tagesprofil."""
        hours = np.linspace(0, 24, num_steps, endpoint=False)

        seasonal = {
            1: 1.10, 2: 1.08, 3: 1.04, 4: 1.00, 5: 0.96, 6: 0.92,
            7: 0.90, 8: 0.90, 9: 0.94, 10: 1.00, 11: 1.06, 12: 1.10,
        }
        factor = seasonal.get(date.month, 1.0)
        daily_kwh = self.annual_hot_water_kwh / 365 * factor

        if daily_kwh < 0.01:
            return np.zeros(num_steps)

        profile = np.ones(num_steps) * 0.1
        profile += 1.5 * np.exp(-0.5 * ((hours - 7) / 1.0) ** 2)
        profile += 0.3 * np.exp(-0.5 * ((hours - 12.5) / 0.8) ** 2)
        profile += 1.2 * np.exp(-0.5 * ((hours - 19) / 1.0) ** 2)

        step_hours = 24 / num_steps
        total = np.sum(profile) * step_hours
        if total > 0:
            profile = profile * (daily_kwh / total)

        return np.round(np.clip(profile, 0, None), 3)

    def get_optimization_variables(self, num_steps: int, model=None) -> dict:
        return {}

    def add_constraints(self, model=None, variables=None, step_minutes: int = 15) -> None:
        pass
