"""Waermepumpe mit SG-Ready Schnittstelle (BWP v1.1) fuer EMOS Light.

COP-Modell basiert auf realen Kennlinien der Vaillant aroTHERM plus
VWL 105/8.1 A (EN 14511). 2D-Interpolation ueber Aussentemperatur
und Vorlauftemperatur.

Zwei thermische Ausgaenge mit unterschiedlichem COP:
  1. Fussbodenheizung (Estrich) — niedrige VL-Temp ~35 C → hoher COP
  2. Warmwasserspeicher — hohe VL-Temp ~55 C → niedrigerer COP

SG-Ready Zustaende nach BWP v1.1:
  Zustand 1 (Lastabwurf): EVU-Sperre / Leistungsbegrenzung
  Zustand 2 (Normalbetrieb): Standard
  Zustand 3 (Verstaerkter Betrieb): Erhoehte WW-Speicher-Maximaltemp
"""

from typing import Any

import numpy as np
import pulp

from emos_light.components.base import Component


# ============================================================
# Kennlinien: Vaillant aroTHERM plus VWL 105/8.1 A (EN 14511)
# ============================================================

# Stuetzstellen
_OUTDOOR_TEMPS = np.array([-7.0, 2.0, 7.0])
_FLOW_TEMPS = np.array([35.0, 45.0, 55.0, 65.0])

# COP-Matrix [outdoor x flow]
_COP_TABLE = np.array([
    # W35   W45   W55   W65
    [3.01, 2.28, 2.03, 1.74],   # A-7
    [4.40, 3.37, 2.76, 2.26],   # A2  (W65 interpoliert)
    [5.29, 4.03, 3.19, 2.51],   # A7
])

# Heizleistung thermisch [kW] — fuer Kapazitaetsgrenzen
_CAPACITY_TABLE = np.array([
    # W35    W45    W55    W65
    [10.58, 10.69, 10.96, 11.06],  # A-7
    [ 5.82,  7.32,  7.27,  7.50],  # A2  (W65 interpoliert)
    [ 5.69,  6.08,  5.57,  6.88],  # A7
])

# Heizleistung min/max bei A2/W35 (Modulationsbereich)
# A2/W35: 4.76 … 12.48 kW, A7/W35: 4.61 … 14.40 kW
# A-7/W35: max 11.25 kW

# COP-Grenzen fuer Extrapolation
_COP_MIN = 1.2
_COP_MAX = 7.0


def _interp_2d(
    x: np.ndarray,
    y: float,
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    z_grid: np.ndarray,
) -> np.ndarray:
    """Bilineare 2D-Interpolation mit Clamp an Raendern.

    Args:
        x: Array von x-Werten (Aussentemperatur).
        y: Skalarer y-Wert (Vorlauftemperatur).
        x_grid: Stuetzstellen x-Achse (sortiert, aufsteigend).
        y_grid: Stuetzstellen y-Achse (sortiert, aufsteigend).
        z_grid: 2D-Matrix der Werte [len(x_grid) x len(y_grid)].

    Returns:
        Interpolierte Werte als numpy-Array.
    """
    x = np.atleast_1d(np.asarray(x, dtype=float))
    x_c = np.clip(x, x_grid[0], x_grid[-1])
    y_c = np.clip(y, y_grid[0], y_grid[-1])

    # x-Indizes
    ix = np.searchsorted(x_grid, x_c) - 1
    ix = np.clip(ix, 0, len(x_grid) - 2)

    # y-Indizes (skalar)
    iy = int(np.clip(np.searchsorted(y_grid, y_c) - 1, 0, len(y_grid) - 2))

    dx = x_grid[ix + 1] - x_grid[ix]
    dy = y_grid[iy + 1] - y_grid[iy]
    wx = np.where(dx > 0, (x_c - x_grid[ix]) / dx, 0.0)
    wy = (y_c - y_grid[iy]) / dy if dy > 0 else 0.0

    z = (
        z_grid[ix, iy] * (1 - wx) * (1 - wy)
        + z_grid[ix + 1, iy] * wx * (1 - wy)
        + z_grid[ix, iy + 1] * (1 - wx) * wy
        + z_grid[ix + 1, iy + 1] * wx * wy
    )
    return z


class HeatPump(Component):
    """Waermepumpe mit realem COP-Kennfeld und SG-Ready (BWP v1.1).

    Config-Parameter:
        max_electrical_power_kw (float): Max. elektr. Leistung [kW].
        min_electrical_power_kw (float): Min. elektr. Leistung wenn an [kW].
        flow_temp_heating_c (float): Vorlauftemperatur Heizkreis (FBH) [C].
        flow_temp_dhw_c (float): Vorlauftemperatur Warmwasser [C].
        operating_min_temp_c (float): Min. Aussentemp fuer Betrieb [C].
        operating_max_temp_c (float): Max. Aussentemp fuer Betrieb [C].
        min_run_time_minutes (int): Mindestlaufzeit [min].
        min_pause_time_minutes (int): Mindestpausenzeit [min].
        sg_ready (bool): SG-Ready-Schnittstelle vorhanden.
        sg_ready_temp_raise_state3_c (float): Temp-Erhoehung WW State 3.
        sg_ready_state1_power_limit_kw (float): Leistungslimit State 1.
        sg_ready_min_hold_minutes (int): Mindesthaltezeit SG-Zustand.
        sg_ready_min_cooldown_minutes (int): Mindest-Cooldown.
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        self.max_power_kw = config.get("max_electrical_power_kw", 8.0)
        self.min_power_kw = config.get("min_electrical_power_kw", 1.0)
        self.flow_temp_heating = config.get("flow_temp_heating_c", 35.0)
        self.flow_temp_dhw = config.get("flow_temp_dhw_c", 55.0)
        self.operating_min_temp = config.get("operating_min_temp_c", -25.0)
        self.operating_max_temp = config.get("operating_max_temp_c", 43.0)
        self.min_run_minutes = config.get("min_run_time_minutes", 15)
        self.min_pause_minutes = config.get("min_pause_time_minutes", 15)
        self.sg_ready = config.get("sg_ready", True)
        self.sg_temp_raise_3 = config.get("sg_ready_temp_raise_state3_c", 5.0)
        self.sg_state1_power_limit = config.get("sg_ready_state1_power_limit_kw", 0.0)
        self.sg_min_hold_minutes = config.get("sg_ready_min_hold_minutes", 10)
        self.sg_min_cooldown_minutes = config.get("sg_ready_min_cooldown_minutes", 10)

    # ============================================================
    # COP-Berechnung (2D-Kennfeld aroTHERM plus)
    # ============================================================

    def calculate_cop(
        self, outside_temp_c: np.ndarray, flow_temp_c: float
    ) -> np.ndarray:
        """Berechnet COP per 2D-Interpolation aus Kennfeld.

        Args:
            outside_temp_c: Aussentemperatur-Zeitreihe [C].
            flow_temp_c: Vorlauftemperatur [C] (z.B. 35 fuer FBH, 55 fuer WW).

        Returns:
            COP-Array gleicher Laenge wie outside_temp_c.
        """
        cop = _interp_2d(outside_temp_c, flow_temp_c,
                         _OUTDOOR_TEMPS, _FLOW_TEMPS, _COP_TABLE)
        return np.clip(cop, _COP_MIN, _COP_MAX)

    def calculate_cop_heating(self, outside_temp_c: np.ndarray) -> np.ndarray:
        """COP fuer Heizkreis (FBH) bei konfigurierter Vorlauftemperatur."""
        return self.calculate_cop(outside_temp_c, self.flow_temp_heating)

    def calculate_cop_dhw(self, outside_temp_c: np.ndarray) -> np.ndarray:
        """COP fuer Warmwasserbereitung bei konfigurierter Vorlauftemperatur."""
        return self.calculate_cop(outside_temp_c, self.flow_temp_dhw)

    def calculate_max_thermal_capacity(
        self, outside_temp_c: np.ndarray, flow_temp_c: float
    ) -> np.ndarray:
        """Max. thermische Leistung [kW] aus Kennfeld."""
        cap = _interp_2d(outside_temp_c, flow_temp_c,
                         _OUTDOOR_TEMPS, _FLOW_TEMPS, _CAPACITY_TABLE)
        return np.clip(cap, 0.0, 20.0)

    # ============================================================
    # MILP-Variablen und Constraints
    # ============================================================

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt WP-Variablen inkl. SG-Ready Zustaende (BWP v1.1).

        Variablen:
            hp_on[t]: Binaer — WP an/aus
            hp_power[t]: Elektrische Leistung gesamt [kW]
            sg_state_1[t]: Binaer — Zustand 1 (Lastabwurf)
            sg_state_3[t]: Binaer — Zustand 3 (Verstaerkt)
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
            sg_state_1 = [
                pulp.LpVariable(f"sg_state_1_{t}", cat=pulp.LpBinary)
                for t in range(num_steps)
            ]
            sg_state_3 = [
                pulp.LpVariable(f"sg_state_3_{t}", cat=pulp.LpBinary)
                for t in range(num_steps)
            ]
            result["sg_state_1"] = sg_state_1
            result["sg_state_3"] = sg_state_3

        return result

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt WP-Constraints inkl. SG-Ready (BWP v1.1) hinzu."""
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

        # SG-Ready Constraints (BWP v1.1)
        if self.sg_ready and "sg_state_1" in variables:
            sg1 = variables["sg_state_1"]
            sg3 = variables["sg_state_3"]

            min_hold_steps = max(1, self.sg_min_hold_minutes // step_minutes)

            for t in range(num_steps):
                model += sg1[t] + sg3[t] <= 1, f"sg_exclusive_{t}"

                model += (
                    hp_power[t] <= self.max_power_kw * (1 - sg1[t])
                    + self.sg_state1_power_limit * sg1[t],
                    f"sg1_power_limit_{t}",
                )

                model += sg3[t] <= hp_on[t], f"sg3_needs_on_{t}"

            # Mindesthaltezeiten
            for t in range(1, num_steps):
                for k in range(1, min_hold_steps):
                    if t + k < num_steps:
                        model += (
                            sg1[t] - sg1[t - 1] <= sg1[t + k],
                            f"sg1_hold_{t}_{k}",
                        )
                        model += (
                            sg3[t] - sg3[t - 1] <= sg3[t + k],
                            f"sg3_hold_{t}_{k}",
                        )
