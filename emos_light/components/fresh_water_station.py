"""Frischwasserstation fuer EMOS Light.

Reiner Waermetauscher — kein eigener Speicher. Entnimmt Waerme aus dem
Warmwasserspeicher und erwaermt Trinkwasser on-demand.

Brauchwasser-Bedarf wird als thermischer Bedarf am WW-Speicher abgebildet:
    Q_speicher = Q_brauchwasser / eta_waermetauscher

Legionellenschutz ist inhaerent — kein stehendes Warmwasser im Trinkwasserkreis.
"""

import numpy as np

from emos_light.components.base import Component


class FreshWaterStation(Component):
    """Frischwasserstation mit Platten-Waermetauscher.

    Config-Parameter:
        target_hot_water_temp_c (float): Ziel-Warmwassertemperatur (z.B. 50 C).
        cold_water_inlet_temp_c (float): Kaltwasser-Zulauftemperatur (z.B. 10 C).
        heat_exchanger_efficiency (float): Wirkungsgrad Waermetauscher (0-1).
        min_storage_temp_for_dhw_c (float): Mindesttemperatur im WW-Speicher
            fuer Brauchwasserbereitstellung (z.B. 55 C).
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.target_temp_c = config.get("target_hot_water_temp_c", 50.0)
        self.cold_water_inlet_c = config.get("cold_water_inlet_temp_c", 10.0)
        self.efficiency = config.get("heat_exchanger_efficiency", 0.90)
        self.min_storage_temp_c = config.get("min_storage_temp_for_dhw_c", 55.0)

    def calculate_storage_demand(self, hot_water_demand_kw: np.ndarray) -> np.ndarray:
        """Berechnet den thermischen Bedarf am WW-Speicher.

        Der Waermetauscher hat Verluste, daher muss dem Speicher mehr
        Waerme entnommen werden als der Brauchwasserbedarf.

        Args:
            hot_water_demand_kw: Brauchwasser-Waermebedarf in kW.

        Returns:
            Benoetigte Waermeentnahme aus dem WW-Speicher in kW.
        """
        if self.efficiency <= 0:
            return hot_water_demand_kw
        return hot_water_demand_kw / self.efficiency

    def get_min_storage_energy(self, storage) -> float:
        """Berechnet die minimale Speicherenergie fuer Brauchwasserbereitstellung.

        Der Speicher muss mindestens min_storage_temp_for_dhw_c warm sein,
        damit der Waermetauscher die Zieltemperatur erreichen kann.

        Args:
            storage: ThermalStorage-Instanz des WW-Speichers.

        Returns:
            Minimale Speicherenergie in kWh.
        """
        return storage.temp_to_energy(self.min_storage_temp_c)
