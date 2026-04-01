"""Thermischer Pufferspeicher — Zwei-Zonen-Schichtenspeicher fuer EMOS.

Modelliert einen zylindrischen Warmwasserspeicher mit idealer
thermischer Schichtung (oemof-thermal Ansatz):

  - Heisse Zone (oben): Temperatur = T_max (konstant)
  - Kalte Zone (unten): Temperatur = T_min (konstant)
  - Thermokline wandert mit Be-/Entladung

Verluste werden geometriebasiert berechnet:
  - Feste Verluste: Deckel (heiss) + Boden (kalt) + Mantel (kalt)
  - Variable Verluste: Mantel (heiss), proportional zum Fuellstand

Alle Relationen bleiben linear → MILP-kompatibel.

Quellen:
  - oemof-thermal: Zwei-Zonen-Modell mit idealer Schichtung
  - Muschick et al. (2022): Multi-Layer MILP-Modell
  - Fraunhofer UMSICHT: Linearer Zusammenhang Temperatur-Fuellstand
"""

import math
from typing import Any

import pulp

from emos_light.components.base import Component


class ThermalStorage(Component):
    """Thermischer Pufferspeicher (Heizwasser oder Warmwasser).

    Zwei-Zonen-Schichtenspeicher mit geometriebasierter Verlustberechnung.

    Energiebilanz:
        E(t) = E(t-1) + (Q_in - Q_demand) * dt
               - fixed_loss_kw * dt
               - relative_loss_per_h * E(t-1) * dt

    Dabei:
        E = 0 kWh  →  gesamter Speicher bei T_min ("leer")
        E = capacity_kwh  →  gesamter Speicher bei T_max ("voll")

    Geometrie (Zylinder):
        Volumen, Hoehe/Durchmesser-Verhaeltnis → Oberflaechen
        U-Wert aus Isolierungsdicke und Waermeleitfaehigkeit

    Verlustmodell (Zwei-Zonen):
        Q_loss = U * [A_top*(T_max-T_amb) + (A_bottom+A_lateral)*(T_min-T_amb)]
               + U * A_lateral * (T_max-T_min) * SOC

    Config-Parameter:
        volume_liters (float): Speichervolumen in Litern.
        min_temperature_c (float): Minimale Speichertemperatur (T_min).
        max_temperature_c (float): Maximale Speichertemperatur (T_max).
        initial_temperature_c (float): Anfangstemperatur.
        ambient_temperature_c (float): Umgebungstemperatur.
        height_diameter_ratio (float): Hoehe/Durchmesser (Default 2.5).
        insulation_thickness_m (float): Isolierungsdicke in m (Default 0.05).
        insulation_conductivity_w_m_k (float): Waermeleitfaehigkeit in W/(m*K) (Default 0.035).
        u_value_w_m2_k (float): Alternativ: U-Wert direkt angeben.
        heat_loss_coefficient_w_per_k (float): Fallback: alter UA-Wert in W/K.
        legionella_temp_c (float): Legionellenschutztemperatur (nur Warmwasser).
        cold_water_inlet_temp_c (float): Kaltwasser-Zulauftemperatur.
    """

    # Thermische Kapazitaet von Wasser: 1.163 Wh/(kg*K) = 1.163 Wh/(L*K)
    SPECIFIC_HEAT_WH_PER_L_K = 1.163

    def __init__(self, name: str, config: dict, prefix: str = "ts"):
        super().__init__(name, config)
        self.prefix = prefix

        # Grundparameter
        self.volume_liters = config.get("volume_liters", 500.0)
        self.min_temp_c = config.get("min_temperature_c", 30.0)
        self.max_temp_c = config.get("max_temperature_c", 65.0)
        self.initial_temp_c = config.get("initial_temperature_c", 45.0)
        self.ambient_temp_c = config.get("ambient_temperature_c", 20.0)
        self.legionella_temp_c = config.get("legionella_temp_c", 0.0)

        # Kaltwasser-Zulauftemperatur (nur relevant fuer Warmwasserpuffer)
        self.cold_water_inlet_temp_c = config.get("cold_water_inlet_temp_c", None)

        # --- Geometrie (Zylinder) ---
        self.height_diameter_ratio = config.get("height_diameter_ratio", 2.5)
        volume_m3 = self.volume_liters / 1000.0

        # Aus V = pi * r^2 * h und h = ratio * 2r:
        #   V = pi * r^2 * ratio * 2r = 2 * pi * ratio * r^3
        #   r = (V / (2 * pi * ratio))^(1/3)
        self.radius_m = (volume_m3 / (2.0 * math.pi * self.height_diameter_ratio)) ** (1.0 / 3.0)
        self.diameter_m = 2.0 * self.radius_m
        self.height_m = self.height_diameter_ratio * self.diameter_m

        # Oberflaechen in m^2
        self.area_top_m2 = math.pi * self.radius_m ** 2
        self.area_bottom_m2 = self.area_top_m2
        self.area_lateral_m2 = 2.0 * math.pi * self.radius_m * self.height_m
        self.area_total_m2 = self.area_top_m2 + self.area_bottom_m2 + self.area_lateral_m2

        # --- U-Wert ---
        self.u_value_w_m2_k = self._calculate_u_value(config)

        # --- Kapazitaet ---
        delta_t = self.max_temp_c - self.min_temp_c
        self.capacity_kwh = (
            self.volume_liters * self.SPECIFIC_HEAT_WH_PER_L_K * delta_t / 1000.0
        )

        # --- Anfangsenergie ---
        initial_delta = max(0, self.initial_temp_c - self.min_temp_c)
        self.initial_energy_kwh = (
            self.volume_liters * self.SPECIFIC_HEAT_WH_PER_L_K * initial_delta / 1000.0
        )

        # --- Legionellenschutz ---
        if self.legionella_temp_c > self.min_temp_c:
            legionella_delta = self.legionella_temp_c - self.min_temp_c
            self.legionella_energy_kwh = (
                self.volume_liters * self.SPECIFIC_HEAT_WH_PER_L_K * legionella_delta / 1000.0
            )
        else:
            self.legionella_energy_kwh = 0.0

        # --- Zwei-Zonen Verlustberechnung ---
        u = self.u_value_w_m2_k
        t_hot = self.max_temp_c
        t_cold = self.min_temp_c
        t_amb = self.ambient_temp_c

        # Feste Verluste (unabhaengig vom Fuellstand):
        #   Deckel (oben, immer heiss) + Boden (unten, immer kalt)
        #   + gesamter Mantel bei T_min (Grundlast)
        self.fixed_loss_kw = (
            u * self.area_top_m2 * max(0, t_hot - t_amb)
            + u * self.area_bottom_m2 * max(0, t_cold - t_amb)
            + u * self.area_lateral_m2 * max(0, t_cold - t_amb)
        ) / 1000.0  # W -> kW

        # Variable Verluste (proportional zum Fuellstand SOC = E/capacity):
        #   Zusaetzlicher Mantel-Verlust wenn heisse Zone waechst
        #   Q_var = U * A_lateral * (T_hot - T_cold) * SOC
        if self.capacity_kwh > 0:
            self.relative_loss_per_h = (
                u * self.area_lateral_m2 * (t_hot - t_cold)
            ) / 1000.0 / self.capacity_kwh  # W -> kW, pro kWh gespeichert
        else:
            self.relative_loss_per_h = 0.0

        # --- Kaltwasser-Nachheizfaktor ---
        self.cold_water_reheat_factor = 1.0
        if self.cold_water_inlet_temp_c is not None:
            t_inlet = self.cold_water_inlet_temp_c
            t_avg = (self.min_temp_c + self.max_temp_c) / 2.0
            if t_avg > t_inlet and self.min_temp_c > t_inlet:
                self.cold_water_reheat_factor = 1.0 + (
                    (self.min_temp_c - t_inlet) / (t_avg - t_inlet)
                )

    def _calculate_u_value(self, config: dict) -> float:
        """Berechnet den U-Wert der Speicherisolierung.

        Prioritaet:
        1. u_value_w_m2_k direkt angegeben
        2. Berechnung aus insulation_thickness + conductivity
        3. Rueckrechnung aus heat_loss_coefficient_w_per_k (Fallback)
        4. Default: 0.7 W/(m^2*K) (5cm PU-Schaum)
        """
        # Prioritaet 1: Direkt angegeben
        if "u_value_w_m2_k" in config:
            return config["u_value_w_m2_k"]

        # Prioritaet 2: Aus Isolierungseigenschaften
        if "insulation_thickness_m" in config:
            thickness = config["insulation_thickness_m"]
            conductivity = config.get("insulation_conductivity_w_m_k", 0.035)
            if thickness > 0:
                return conductivity / thickness

        # Prioritaet 3: Aus altem heat_loss_coefficient (Gesamt-UA in W/K)
        if "heat_loss_coefficient_w_per_k" in config:
            ua = config["heat_loss_coefficient_w_per_k"]
            if self.area_total_m2 > 0:
                return ua / self.area_total_m2

        # Default: 5 cm PU-Schaum (lambda=0.035 W/(m*K))
        return 0.035 / 0.05  # = 0.7 W/(m^2*K)

    def energy_to_temp(self, energy_kwh: float) -> float:
        """Rechnet gespeicherte Energie in Temperatur um."""
        if self.capacity_kwh <= 0:
            return self.min_temp_c
        fraction = energy_kwh / self.capacity_kwh
        return self.min_temp_c + fraction * (self.max_temp_c - self.min_temp_c)

    def temp_to_energy(self, temp_c: float) -> float:
        """Rechnet Temperatur in gespeicherte Energie um."""
        delta = max(0, temp_c - self.min_temp_c)
        return self.volume_liters * self.SPECIFIC_HEAT_WH_PER_L_K * delta / 1000.0

    @property
    def standby_loss_kw_at_full(self) -> float:
        """Verlustleistung bei vollem Speicher (SOC=1) in kW."""
        return self.fixed_loss_kw + self.relative_loss_per_h * self.capacity_kwh

    @property
    def standby_loss_kw_at_empty(self) -> float:
        """Verlustleistung bei leerem Speicher (SOC=0) in kW."""
        return self.fixed_loss_kw

    @property
    def standby_loss_w_at_mean(self) -> float:
        """Verlustleistung bei mittlerem Fuellstand (SOC=0.5) in W."""
        return (self.fixed_loss_kw + self.relative_loss_per_h * self.capacity_kwh * 0.5) * 1000.0

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Energie- und Waermestrom-Variablen auf kWh-Basis.

        Variablen:
            ts_energy_kwh[t]: Gespeicherte Energie in kWh (0 = T_min, capacity = T_max)
            ts_q_in[t]: Zugefuehrte Waermeleistung in kW
            ts_q_demand[t]: Waermeentnahme in kW
        """
        var_prefix = f"{self.prefix}_{self.name}"

        energy = [
            pulp.LpVariable(
                f"{var_prefix}_energy_{t}",
                lowBound=0.0,
                upBound=self.capacity_kwh,
            )
            for t in range(num_steps)
        ]

        q_in = [
            pulp.LpVariable(f"{var_prefix}_q_in_{t}", lowBound=0)
            for t in range(num_steps)
        ]
        q_demand = [
            pulp.LpVariable(f"{var_prefix}_q_demand_{t}", lowBound=0)
            for t in range(num_steps)
        ]

        return {
            f"{self.prefix}_energy_kwh": energy,
            f"{self.prefix}_q_in": q_in,
            f"{self.prefix}_q_demand": q_demand,
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Energie-Bilanz-Constraints zum Modell hinzu.

        Zwei-Zonen Energiebilanz pro Zeitschritt:
            E(t) = E(t-1) + (Q_in - Q_demand) * dt
                   - fixed_loss_kw * dt
                   - relative_loss_per_h * E(t-1) * dt

        fixed_loss_kw: Verluste durch Deckel, Boden und kalte Mantelflaeche
        relative_loss_per_h * E: Zusaetzliche Verluste durch heisse Mantelflaeche
        """
        dt_h = step_minutes / 60.0

        energy = variables[f"{self.prefix}_energy_kwh"]
        q_in = variables[f"{self.prefix}_q_in"]
        q_demand = variables[f"{self.prefix}_q_demand"]

        num_steps = len(energy)

        for t in range(num_steps):
            if t == 0:
                e_prev = self.initial_energy_kwh
            else:
                e_prev = energy[t - 1]

            # Zwei-Zonen Energiebilanz:
            # E(t) = E(t-1) + netto_zufuhr - feste_verluste - variable_verluste
            model += (
                energy[t]
                == e_prev
                + (q_in[t] - q_demand[t]) * dt_h
                - self.fixed_loss_kw * dt_h
                - self.relative_loss_per_h * dt_h * e_prev,
                f"{self.prefix}_{self.name}_energy_balance_{t}",
            )

    def add_legionella_constraint(self, model: Any, variables: dict, num_steps: int) -> None:
        """Legionellenschutz: Warmwasser muss mind. 1x/Tag die Legionellentemperatur erreichen.

        In kWh-Basis: E(t) >= legionella_energy_kwh fuer mindestens einen Zeitschritt.
        """
        if self.legionella_energy_kwh <= 0:
            return

        energy = variables[f"{self.prefix}_energy_kwh"]
        var_prefix = f"{self.prefix}_{self.name}"

        legionella_reached = [
            pulp.LpVariable(f"{var_prefix}_legionella_{t}", cat=pulp.LpBinary)
            for t in range(num_steps)
        ]
        for t in range(num_steps):
            model += (
                energy[t] >= self.legionella_energy_kwh
                - self.capacity_kwh * (1 - legionella_reached[t])
            ), f"{var_prefix}_legionella_link_{t}"

        model += (
            pulp.lpSum(legionella_reached) >= 1
        ), f"{var_prefix}_legionella_min_once"
