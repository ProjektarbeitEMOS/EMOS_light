"""Batteriespeicher Komponentenmodell fuer EMOS.

MILP-Modell mit Lade-/Entladevariablen, SOC-Tracking und
Binaervariablen zur Vermeidung gleichzeitigen Ladens und Entladens.
"""

from typing import Any

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_mutual_exclusion,
    add_on_off_power_link,
    add_state_balance,
    make_binary_array,
    make_var_array,
    step_hours,
)


class Battery(MILPComponent):
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
        replacement_cost_eur_per_kwh (float): Wiederbeschaffungswert in EUR/kWh.
        residual_value_pct (float): Restwert am Lebensende (Anteil 0-1).
        equivalent_full_cycles (int): Anzahl Aequivalent-Vollzyklen bis EOL.
        aging_cost_enabled (bool): Alterungskosten in Zielfunktion beruecksichtigen.
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

        # Alterungskosten-Parameter (PDF Speichergruppe, Kap. 3)
        self.replacement_cost_eur_per_kwh = config.get(
            "replacement_cost_eur_per_kwh", 500.0
        )
        self.residual_value_pct = config.get("residual_value_pct", 0.0)
        self.equivalent_full_cycles = config.get("equivalent_full_cycles", 6000)
        self.aging_cost_enabled = config.get("aging_cost_enabled", True)

    # ========================================================================
    # Alterungskosten-Kennzahlen (PDF Speichergruppe)
    # ========================================================================

    @property
    def usable_capacity_kwh(self) -> float:
        """Nutzkapazitaet innerhalb des erlaubten SoC-Fensters."""
        return self.capacity_kwh * (self.max_soc - self.min_soc)

    @property
    def roundtrip_efficiency(self) -> float:
        """Roundtrip-Wirkungsgrad eta_rt = eta_charge * eta_discharge."""
        return self.charge_eff * self.discharge_eff

    @property
    def aging_cost_ct_per_kwh(self) -> float:
        """Zyklische Alterungskosten pro durchgesetzter kWh in ct/kWh.

        Formel nach PDF Speichergruppe, Kap. 3:
            c_aging = (C_Ersatz - R_EOL) / (N_EFC * E_nutzbar * eta_rt)

        Der Durchsatz bezieht sich auf den Energiefluss in einer Richtung
        (Laden ODER Entladen). Ein Aequivalent-Vollzyklus besteht aus
        einmal laden + einmal entladen, daher wird der Kostenterm in der
        Zielfunktion je zur Haelfte auf charge und discharge verteilt.
        """
        if not self.aging_cost_enabled:
            return 0.0
        replacement = self.replacement_cost_eur_per_kwh * self.capacity_kwh
        residual = replacement * self.residual_value_pct
        depreciable = replacement - residual
        throughput_kwh = (
            self.equivalent_full_cycles
            * self.usable_capacity_kwh
            * self.roundtrip_efficiency
        )
        if throughput_kwh <= 0:
            return 0.0
        return depreciable / throughput_kwh * 100.0  # EUR/kWh -> ct/kWh

    # ========================================================================
    # MILP-Variablen und Constraints
    # ========================================================================

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

        return {
            "bat_charge": make_var_array(
                f"{prefix}_charge", num_steps,
                low=0, high=self.max_charge_kw,
            ),
            "bat_discharge": make_var_array(
                f"{prefix}_discharge", num_steps,
                low=0, high=self.max_discharge_kw,
            ),
            "bat_soc": make_var_array(
                f"{prefix}_soc", num_steps,
                low=soc_min_kwh, high=soc_max_kwh,
            ),
            "bat_b_charge": make_binary_array(f"{prefix}_b_charge", num_steps),
            "bat_b_discharge": make_binary_array(f"{prefix}_b_discharge", num_steps),
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Batterie-Constraints zum Modell hinzu.

        Constraints:
            1. Kein gleichzeitiges Laden und Entladen (b_charge + b_discharge <= 1)
            2. Ladeleistung nur wenn Laden aktiv (charge <= max * b_charge)
            3. Entladeleistung nur wenn Entladen aktiv (discharge <= max * b_discharge)
            4. SOC-Bilanz: soc[t] = soc[t-1] + charge*eff*dt - discharge/eff*dt
        """
        prefix = f"bat_{self.name}"
        dt_h = step_hours(step_minutes)

        charge = variables["bat_charge"]
        discharge = variables["bat_discharge"]
        soc = variables["bat_soc"]
        b_charge = variables["bat_b_charge"]
        b_discharge = variables["bat_b_discharge"]

        # 1) Gegenseitiger Ausschluss Laden/Entladen
        add_mutual_exclusion(model, b_charge, b_discharge, name=f"{prefix}_no_simul")

        # 2+3) Leistung nur wenn Binaer-Variable aktiv
        add_on_off_power_link(
            model, charge, b_charge,
            max_power=self.max_charge_kw,
            name=f"{prefix}_charge_link",
        )
        add_on_off_power_link(
            model, discharge, b_discharge,
            max_power=self.max_discharge_kw,
            name=f"{prefix}_discharge_link",
        )

        # 4) SOC-Bilanzgleichung
        initial_soc_kwh = self.initial_soc * self.capacity_kwh
        add_state_balance(
            model, soc,
            initial=initial_soc_kwh,
            rhs_fn=lambda prev, t: (
                prev
                + charge[t] * self.charge_eff * dt_h
                - discharge[t] / self.discharge_eff * dt_h
            ),
            name=f"{prefix}_soc",
        )

    # ------------------------------------------------------------------
    # Bilanz-Beitraege
    # ------------------------------------------------------------------

    def electrical_supply(self, variables: dict, t: int) -> Any:
        """Entladung speist den AC-Knoten."""
        return variables["bat_discharge"][t]

    def electrical_demand(self, variables: dict, t: int) -> Any:
        """Laden zieht aus dem AC-Knoten."""
        return variables["bat_charge"][t]

    def extract_result(
        self, result: Any, variables: dict, num_steps: int, dt_h: float,
    ) -> None:
        """Schreibt Lade-, Entlade-, SOC- und Alterungs-KPIs ins Result."""
        import numpy as np

        result.batt_charge_kw = np.array(
            [v.varValue or 0.0 for v in variables["bat_charge"]]
        )
        result.batt_discharge_kw = np.array(
            [v.varValue or 0.0 for v in variables["bat_discharge"]]
        )
        result.batt_soc_kwh = np.array(
            [v.varValue or 0.0 for v in variables["bat_soc"]]
        )
        # Alterungskosten-KPIs (PDF Speichergruppe)
        throughput_kwh = float(
            (result.batt_charge_kw.sum() + result.batt_discharge_kw.sum()) * dt_h
        )
        result.battery_throughput_kwh = throughput_kwh
        c_aging_ct = self.aging_cost_ct_per_kwh
        result.battery_aging_cost_eur = throughput_kwh / 2.0 * c_aging_ct / 100.0
        if self.usable_capacity_kwh > 0:
            result.battery_equivalent_cycles = (
                throughput_kwh / (2.0 * self.usable_capacity_kwh)
            )
