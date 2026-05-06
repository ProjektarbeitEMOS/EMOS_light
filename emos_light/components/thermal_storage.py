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

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_state_balance,
    make_binary_array,
    make_var_array,
    step_hours,
)


class ThermalStorage(MILPComponent):
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
        self.comfort_temp_c = config.get("comfort_temperature_c", 0.0)
        self.comfort_periods = config.get("comfort_periods", [])
        self.initial_temp_c = config.get("initial_temperature_c", 45.0)
        self.ambient_temp_c = config.get("ambient_temperature_c", 20.0)
        self.legionella_temp_c = config.get("legionella_temp_c", 0.0)

        # Kaltwasser-Zulauftemperatur (nur relevant fuer Warmwasserpuffer)
        self.cold_water_inlet_temp_c = config.get("cold_water_inlet_temp_c", None)

        # Geometrie + abgeleitete Groessen
        self._init_geometry(config)
        self._init_capacities()
        self._init_loss_model()
        self._init_cold_water_factor()

    # ------------------------------------------------------------------
    # Initialisierungs-Helfer (privat, nur einmal aufgerufen)
    # ------------------------------------------------------------------

    def _init_geometry(self, config: dict) -> None:
        """Berechnet Zylinder-Geometrie aus Volumen + H/D-Verhaeltnis."""
        self.height_diameter_ratio = config.get("height_diameter_ratio", 2.5)
        volume_m3 = self.volume_liters / 1000.0

        # V = pi * r^2 * h und h = ratio * 2r
        # → r = (V / (2 * pi * ratio))^(1/3)
        self.radius_m = (
            volume_m3 / (2.0 * math.pi * self.height_diameter_ratio)
        ) ** (1.0 / 3.0)
        self.diameter_m = 2.0 * self.radius_m
        self.height_m = self.height_diameter_ratio * self.diameter_m

        self.area_top_m2 = math.pi * self.radius_m ** 2
        self.area_bottom_m2 = self.area_top_m2
        self.area_lateral_m2 = 2.0 * math.pi * self.radius_m * self.height_m
        self.area_total_m2 = (
            self.area_top_m2 + self.area_bottom_m2 + self.area_lateral_m2
        )

        self.u_value_w_m2_k = self._calculate_u_value(config)

    def _init_capacities(self) -> None:
        """Berechnet Kapazitaet, Anfangsenergie und Legionellenenergie."""
        delta_t = self.max_temp_c - self.min_temp_c
        self.capacity_kwh = (
            self.volume_liters * self.SPECIFIC_HEAT_WH_PER_L_K * delta_t / 1000.0
        )

        initial_delta = max(0, self.initial_temp_c - self.min_temp_c)
        self.initial_energy_kwh = (
            self.volume_liters * self.SPECIFIC_HEAT_WH_PER_L_K * initial_delta / 1000.0
        )

        if self.legionella_temp_c > self.min_temp_c:
            legionella_delta = self.legionella_temp_c - self.min_temp_c
            self.legionella_energy_kwh = (
                self.volume_liters * self.SPECIFIC_HEAT_WH_PER_L_K * legionella_delta / 1000.0
            )
        else:
            self.legionella_energy_kwh = 0.0

    def _init_loss_model(self) -> None:
        """Zerlegt die Verluste in einen festen + einen SOC-proportionalen Anteil."""
        u = self.u_value_w_m2_k
        t_hot = self.max_temp_c
        t_cold = self.min_temp_c
        t_amb = self.ambient_temp_c

        # Feste Verluste: Deckel (heiss) + Boden (kalt) + Mantel bei T_min
        self.fixed_loss_kw = (
            u * self.area_top_m2 * max(0, t_hot - t_amb)
            + u * self.area_bottom_m2 * max(0, t_cold - t_amb)
            + u * self.area_lateral_m2 * max(0, t_cold - t_amb)
        ) / 1000.0  # W -> kW

        # Variable Verluste (proportional zu SOC): Mantel-Aufschlag heisse Zone
        if self.capacity_kwh > 0:
            self.relative_loss_per_h = (
                u * self.area_lateral_m2 * (t_hot - t_cold)
            ) / 1000.0 / self.capacity_kwh
        else:
            self.relative_loss_per_h = 0.0

    def _init_cold_water_factor(self) -> None:
        """Aufschlag fuer Kaltwasser-Nachheizung (Frischwasserstation-Pfad)."""
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
        if "u_value_w_m2_k" in config:
            return config["u_value_w_m2_k"]

        if "insulation_thickness_m" in config:
            thickness = config["insulation_thickness_m"]
            conductivity = config.get("insulation_conductivity_w_m_k", 0.035)
            if thickness > 0:
                return conductivity / thickness

        if "heat_loss_coefficient_w_per_k" in config:
            ua = config["heat_loss_coefficient_w_per_k"]
            if self.area_total_m2 > 0:
                return ua / self.area_total_m2

        # Default: 5 cm PU-Schaum (lambda=0.035 W/(m*K))
        return 0.035 / 0.05  # = 0.7 W/(m^2*K)

    # ------------------------------------------------------------------
    # Konversionen Energie <-> Temperatur und Verlust-Kennwerte
    # ------------------------------------------------------------------

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
        return (
            self.fixed_loss_kw
            + self.relative_loss_per_h * self.capacity_kwh * 0.5
        ) * 1000.0

    # ------------------------------------------------------------------
    # Komfort-Mindestenergie aus Zeitperioden
    # ------------------------------------------------------------------

    def get_min_energy_schedule(self, timestamps: list) -> list[float]:
        """Gibt zeit-abhaengige Mindestenergie zurueck.

        Waehrend Komfort-Perioden gilt comfort_temperature_c,
        ausserhalb gilt min_temperature_c.
        """
        min_energy = self.temp_to_energy(self.min_temp_c)

        if not self.comfort_periods or self.comfort_temp_c <= self.min_temp_c:
            return [min_energy] * len(timestamps)

        comfort_energy = self.temp_to_energy(self.comfort_temp_c)
        schedule = []

        for ts in timestamps:
            hour = ts.hour + ts.minute / 60.0 if hasattr(ts, "hour") else 0
            in_comfort = False
            for period in self.comfort_periods:
                start = period.get("start_hour", 0)
                end = period.get("end_hour", 24)
                if start <= end:
                    in_comfort = in_comfort or (start <= hour < end)
                else:
                    # Ueber Mitternacht (z.B. 22-6)
                    in_comfort = in_comfort or (hour >= start or hour < end)
            schedule.append(comfort_energy if in_comfort else min_energy)

        return schedule

    # ------------------------------------------------------------------
    # MILP-Schnittstelle
    # ------------------------------------------------------------------

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Energie- und Waermestrom-Variablen auf kWh-Basis.

        Variablen (Keys mit ``self.prefix`` aus dem Konstruktor):
            <prefix>_energy_kwh[t]: Gespeicherte Energie in kWh
                (0 = T_min, capacity = T_max)
            <prefix>_q_in[t]:       Zugefuehrte Waermeleistung in kW
            <prefix>_q_demand[t]:   Waermeentnahme in kW
        """
        var_prefix = f"{self.prefix}_{self.name}"
        return {
            f"{self.prefix}_energy_kwh": make_var_array(
                f"{var_prefix}_energy", num_steps,
                low=0.0, high=self.capacity_kwh,
            ),
            f"{self.prefix}_q_in": make_var_array(
                f"{var_prefix}_q_in", num_steps, low=0,
            ),
            f"{self.prefix}_q_demand": make_var_array(
                f"{var_prefix}_q_demand", num_steps, low=0,
            ),
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Energiebilanz mit festem + SOC-proportionalem Verlust.

            E(t) = E(t-1) + (Q_in - Q_demand)*dt
                   - fixed_loss_kw * dt
                   - relative_loss_per_h * E(t-1) * dt
        """
        dt_h = step_hours(step_minutes)

        energy = variables[f"{self.prefix}_energy_kwh"]
        q_in = variables[f"{self.prefix}_q_in"]
        q_demand = variables[f"{self.prefix}_q_demand"]

        add_state_balance(
            model, energy,
            initial=self.initial_energy_kwh,
            rhs_fn=lambda prev, t: (
                prev
                + (q_in[t] - q_demand[t]) * dt_h
                - self.fixed_loss_kw * dt_h
                - self.relative_loss_per_h * dt_h * prev
            ),
            name=f"{self.prefix}_{self.name}_energy",
        )

    # ------------------------------------------------------------------
    # Bilanz-Beitraege als Waermesenke
    # ------------------------------------------------------------------

    @property
    def heat_sink_id(self) -> str:
        """Bezeichner als Waermesenke entspricht dem Praefix (z.B. 'ww')."""
        return self.prefix

    def heat_demand(self, variables: dict, t: int, sink: str) -> Any:
        """Q_in des Speichers = vom Heizer eingespeiste Leistung."""
        if sink == self.heat_sink_id:
            return variables[f"{self.prefix}_q_in"][t]
        return 0.0

    # ------------------------------------------------------------------
    # Optionale Constraints
    # ------------------------------------------------------------------

    def add_legionella_constraint(
        self, model: Any, variables: dict, num_steps: int,
    ) -> None:
        """Legionellenschutz: Speicher muss mind. 1x/Tag die Legionellentemp erreichen.

        Modellierung: binaere Hilfsvariable pro Zeitschritt, die nur dann
        gesetzt sein darf, wenn die Energie ueber dem Legionellen-Threshold
        liegt; mind. eine davon muss aktiv sein.
        """
        if self.legionella_energy_kwh <= 0:
            return

        energy = variables[f"{self.prefix}_energy_kwh"]
        var_prefix = f"{self.prefix}_{self.name}"

        legionella_reached = make_binary_array(
            f"{var_prefix}_legionella", num_steps,
        )

        for t in range(num_steps):
            model += (
                energy[t] >= self.legionella_energy_kwh
                - self.capacity_kwh * (1 - legionella_reached[t])
            ), f"{var_prefix}_legionella_link_{t}"

        model += (
            pulp.lpSum(legionella_reached) >= 1
        ), f"{var_prefix}_legionella_min_once"
