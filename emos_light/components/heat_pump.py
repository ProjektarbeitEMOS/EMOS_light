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

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_min_hold_time,
    add_min_pause_time,
    add_min_run_time,
    add_mutual_exclusion,
    add_on_off_power_link,
    make_binary_array,
    make_var_array,
    steps_for_minutes,
)
from emos_light.utils.interpolation import interp_2d


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


class HeatPump(MILPComponent):
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
        # Maximale Anzahl Einschaltvorgaenge (OFF -> ON) pro Kalendertag.
        # Setz auf 0 oder negative Werte, um die Restriktion zu deaktivieren.
        self.max_starts_per_day = int(config.get("max_starts_per_day", 8))
        self.sg_ready = config.get("sg_ready", True)
        # SG-Ready-Konfiguration (BWP v1.1, siehe heat_pump.add_constraints).
        # Bei Zustand 3 (Einschaltempfehlung) wird der WW-Sollwert um diese
        # Temperaturspanne angehoben; Estrich (Pufferspeicher) bleibt
        # unveraendert (PDF: ohne Waermeanforderung keine Speicherladung
        # im Heizbetrieb bei sg3).
        self.sg_temp_raise_3 = float(
            config.get("sg_ready_temp_raise_state3_c", 5.0)
        )
        # Bei Zustand 4 (Zwangseinschaltung) wird sowohl WW als auch der
        # Estrich-Pufferspeicher angehoben — Wert muss > sg3-Wert sein.
        self.sg_temp_raise_4 = float(
            config.get("sg_ready_temp_raise_state4_c", 10.0)
        )
        if self.sg_temp_raise_4 < self.sg_temp_raise_3:
            # Sicherheits-Korrektur (PDF: "Der Temperaturwert liegt
            # ueber dem fuer Schaltzustand 3 eingestellten Wert.")
            self.sg_temp_raise_4 = self.sg_temp_raise_3
        self.sg_min_hold_minutes = config.get("sg_ready_min_hold_minutes", 10)

        # Werden in prepare() / set_active_heat_sinks() vom Optimizer gesetzt.
        self._cop_heating: np.ndarray | None = None
        self._cop_dhw: np.ndarray | None = None
        self._timestamps: list | None = None
        self._active_sinks: set = set()

    # Vorlauftemperatur je Senken-Bezeichner (Konvention)
    _SINK_FLOW_TEMP = {
        "floor": "flow_temp_heating",
        "ww": "flow_temp_dhw",
    }

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
        cop = interp_2d(outside_temp_c, flow_temp_c,
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
        cap = interp_2d(outside_temp_c, flow_temp_c,
                         _OUTDOOR_TEMPS, _FLOW_TEMPS, _CAPACITY_TABLE)
        return np.clip(cap, 0.0, 20.0)

    # ============================================================
    # Setup-Hooks (vom Optimizer aufgerufen)
    # ============================================================

    def prepare(self, inp: Any) -> None:
        """Vorberechnung der COP-Zeitreihen aus der Aussentemperatur."""
        self._cop_heating = self.calculate_cop_heating(inp.outside_temp_c)
        self._cop_dhw = self.calculate_cop_dhw(inp.outside_temp_c)
        # Zeitstempel puffern — werden in add_constraints fuer die
        # Tagesgruppierung der max_starts_per_day-Restriktion gebraucht.
        self._timestamps = list(inp.timestamps)

    def set_active_heat_sinks(self, sinks: set) -> None:
        """Welche Senken sind aktiv? Bestimmt, ob ein WP-Split noetig ist."""
        # Nur Senken merken, die wir auch bedienen koennen
        self._active_sinks = set(sinks) & set(self._SINK_FLOW_TEMP.keys())

    # ============================================================
    # MILP-Variablen und Constraints
    # ============================================================

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt WP-Variablen inkl. SG-Ready und ggf. Senken-Split.

        Variablen:
            hp_on[t]: Binaer — WP an/aus
            hp_power[t]: Elektrische Leistung gesamt [kW]
            hp_start[t]: Binaer — Einschaltvorgang OFF -> ON bei t
                (gekoppelt an hp_on, wird mit max_starts_per_day begrenzt).
                Umschalten zwischen FBH und WW zaehlt **nicht** als Start,
                solange die WP an bleibt — nur das OFF->ON-Anschalten
                belastet den Verdichter.
            hp_sg1[t]: Binaer — SG-Ready Zustand 1 (Zwangsabschaltung, WP aus)
            hp_sg2[t]: Binaer — SG-Ready Zustand 2 (Normalbetrieb, WP an, kein Boost)
            hp_sg3[t]: Binaer — SG-Ready Zustand 3 (Einschaltempfehlung, WP an + WW-Boost)
            hp_sg4[t]: Binaer — SG-Ready Zustand 4 (Zwangseinschaltung, WP an + WW + Estrich-Boost)

            SG-Ready steuert in diesem Modell DIE EINZIGE Schaltentscheidung
            der WP: der Solver hat ausser ueber den gewaehlten SG-Zustand
            keinen direkten Zugriff auf ``hp_on``. Genau ein SG-Zustand ist
            pro Schritt aktiv (``sg1+sg2+sg3+sg4 = 1``), und ``hp_on = 1 - sg1``
            — die WP ist nur abschaltbar, indem der Solver Zustand 1 waehlt.

        Wenn mehrere Waermesenken aktiv sind, werden zusaetzlich
        Aufteilungs-Variablen pro Senke erzeugt:
            hp_power_floor[t]: Anteil der el. Leistung an FBH-Pfad
            hp_power_ww[t]:    Anteil der el. Leistung an WW-Pfad
        """
        result = {
            "hp_on": make_binary_array("hp_on", num_steps),
            "hp_power": make_var_array(
                "hp_power", num_steps, low=0, high=self.max_power_kw,
            ),
            "hp_start": make_binary_array("hp_start", num_steps),
        }
        if self.sg_ready:
            result["hp_sg1"] = make_binary_array("hp_sg1", num_steps)
            result["hp_sg2"] = make_binary_array("hp_sg2", num_steps)
            result["hp_sg3"] = make_binary_array("hp_sg3", num_steps)
            result["hp_sg4"] = make_binary_array("hp_sg4", num_steps)

        # Senken-Split nur wenn mehr als eine Senke aktiv
        if len(self._active_sinks) > 1:
            if "floor" in self._active_sinks:
                result["hp_power_floor"] = make_var_array(
                    "hp_power_floor", num_steps, low=0, high=self.max_power_kw,
                )
            if "ww" in self._active_sinks:
                result["hp_power_ww"] = make_var_array(
                    "hp_power_ww", num_steps, low=0, high=self.max_power_kw,
                )
        return result

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt WP-Constraints inkl. SG-Ready (BWP v1.1) hinzu."""
        hp_on = variables["hp_on"]
        hp_power = variables["hp_power"]
        num_steps = len(hp_on)

        min_run_steps = steps_for_minutes(self.min_run_minutes, step_minutes)
        min_pause_steps = steps_for_minutes(self.min_pause_minutes, step_minutes)

        # Modulationsbereich (Min/Max Leistung gekoppelt an on/off)
        add_on_off_power_link(
            model, hp_power, hp_on,
            max_power=self.max_power_kw,
            min_power=self.min_power_kw,
            name="hp",
        )

        add_min_run_time(model, hp_on, min_run_steps=min_run_steps, name="hp")
        add_min_pause_time(model, hp_on, min_pause_steps=min_pause_steps, name="hp")

        # Einschalt-Zaehler-Indikator: hp_start[t] muss 1 sein, wenn
        # zwischen t-1 und t von OFF auf ON gewechselt wird. Da hp_start in
        # die Tagessumme eingeht und diese eine Obergrenze hat, wird der
        # Solver hp_start nur dann anheben, wenn er muss — die untere
        # Schranke (start >= on[t]-on[t-1]) erzwingt das. Bei t=0 nehmen
        # wir an, dass die WP vorher AUS war (konservativ; fuer MPC-
        # Folgewindows liefert dies u.U. einen unnoetigen Zaehl-Start).
        hp_start = variables["hp_start"]
        for t in range(num_steps):
            prev = 0 if t == 0 else hp_on[t - 1]
            model += (
                hp_start[t] >= hp_on[t] - prev,
                f"hp_start_link_{t}",
            )

        # Tageslimit fuer Einschaltvorgaenge. Gruppiert nach Kalenderdatum
        # aus den vom Optimizer (via prepare) durchgereichten Timestamps.
        # max_starts_per_day <= 0 schaltet die Restriktion aus.
        if self.max_starts_per_day > 0 and self._timestamps is not None:
            by_day: dict = {}
            for t, ts in enumerate(self._timestamps[:num_steps]):
                by_day.setdefault(ts.date(), []).append(t)
            for day, idxs in by_day.items():
                model += (
                    pulp.lpSum(hp_start[t] for t in idxs)
                    <= self.max_starts_per_day,
                    f"hp_max_starts_{day.isoformat()}",
                )

        # SG-Ready Constraints (BWP v1.1) — SG-Ready ist der EINZIGE
        # Steuerkanal des Solvers fuer die WP:
        #
        #   sg1 + sg2 + sg3 + sg4 = 1   (pro Schritt genau ein Zustand)
        #   hp_on + sg1            = 1   (WP nur per sg1 abschaltbar)
        #
        # Damit ist:
        #   sg1 = 1 → hp_on = 0  (Zwangsabschaltung)
        #   sg2 = 1 → hp_on = 1  (Normalbetrieb, kein Speicher-Boost)
        #   sg3 = 1 → hp_on = 1  (Einschaltempf., WW-Boost erlaubt)
        #   sg4 = 1 → hp_on = 1  (Zwangseinsch., WW + Estrich-Boost erlaubt)
        #
        # Die Speicher-Cap-Erweiterungen liegen im Optimizer (siehe
        # ww_sg_ready_cap_t und ufh_sg_ready_cap_t).
        if self.sg_ready and "hp_sg1" in variables:
            sg1 = variables["hp_sg1"]
            sg2 = variables["hp_sg2"]
            sg3 = variables["hp_sg3"]
            sg4 = variables["hp_sg4"]
            min_hold_steps = steps_for_minutes(self.sg_min_hold_minutes, step_minutes)

            for t in range(num_steps):
                # Genau ein SG-Zustand pro Schritt
                model += (
                    sg1[t] + sg2[t] + sg3[t] + sg4[t] == 1,
                    f"hp_sg_select_{t}",
                )
                # hp_on ist die direkte Konsequenz: AUS gdw. sg1.
                model += (
                    hp_on[t] + sg1[t] == 1,
                    f"hp_sg_drives_on_{t}",
                )

            # Mindesthaltezeiten fuer alle nicht-trivialen Zustaende (gegen
            # Pendeln). sg2 ist der "Default" — keine eigene Haltezeit
            # noetig, weil WP-Lauf-/Pausenzeit ueber hp_on bereits durch
            # min_run_/min_pause_time erzwungen wird.
            add_min_hold_time(model, sg1, min_hold_steps=min_hold_steps, name="hp_sg1")
            add_min_hold_time(model, sg3, min_hold_steps=min_hold_steps, name="hp_sg3")
            add_min_hold_time(model, sg4, min_hold_steps=min_hold_steps, name="hp_sg4")

        # Senken-Split-Constraint: hp_power = sum(hp_power_<sink>)
        # Nur wenn mehrere Senken aktiv sind, sonst speist hp_power direkt
        # die einzige Senke (siehe heat_supply).
        if len(self._active_sinks) > 1:
            split_vars = []
            if "hp_power_floor" in variables:
                split_vars.append(variables["hp_power_floor"])
            if "hp_power_ww" in variables:
                split_vars.append(variables["hp_power_ww"])
            for t in range(num_steps):
                model += (
                    hp_power[t] == sum(v[t] for v in split_vars),
                    f"hp_power_split_{t}",
                )

    # ------------------------------------------------------------------
    # Bilanz-Beitraege
    # ------------------------------------------------------------------

    def electrical_demand(self, variables: dict, t: int) -> Any:
        """Gesamte WP-Wirkleistung als Last am AC-Knoten."""
        return variables["hp_power"][t]

    @property
    def is_heat_supplier(self) -> bool:
        return True

    @property
    def is_par14a_curtailable(self) -> bool:
        return True

    def extract_result(
        self, result: Any, variables: dict, num_steps: int, dt_h: float,
    ) -> None:
        """WP-Leistung, SG-Ready-Zustand und Einschalt-Zaehler ins Result."""
        result.hp_power_kw = np.array(
            [v.varValue or 0.0 for v in variables["hp_power"]]
        )
        if self.sg_ready and "hp_sg3" in variables:
            sg1_vals = np.array([v.varValue or 0.0 for v in variables["hp_sg1"]])
            sg2_vals = np.array(
                [v.varValue or 0.0 for v in variables.get("hp_sg2", [])]
            )
            sg3_vals = np.array([v.varValue or 0.0 for v in variables["hp_sg3"]])
            sg4_vals = np.array(
                [v.varValue or 0.0 for v in variables.get("hp_sg4", [])]
            )
            # Genau eine Variable ist 1, alle anderen 0 (Selektions-Constraint).
            # Wir starten konservativ bei 2 (Normal) und ueberschreiben mit den
            # anderen Zustaenden, falls dort > 0.5.
            state = np.full(num_steps, 2, dtype=int)
            if len(sg2_vals) == num_steps:
                state = np.where(sg2_vals > 0.5, 2, state)
            if len(sg4_vals) == num_steps:
                state = np.where(sg4_vals > 0.5, 4, state)
            state = np.where(sg3_vals > 0.5, 3, state)
            state = np.where(sg1_vals > 0.5, 1, state)
            result.sg_ready_state = state
        # Einschaltvorgaenge zaehlen (aus hp_start). Pro Kalendertag und
        # in Summe — gleiches Schema wie das max_starts_per_day-Constraint.
        if "hp_start" in variables and self._timestamps is not None:
            start_vals = np.array(
                [v.varValue or 0.0 for v in variables["hp_start"]]
            )
            starts_bool = start_vals > 0.5
            per_day: dict = {}
            for t, is_start in enumerate(starts_bool):
                if t >= num_steps:
                    break
                if is_start:
                    day = self._timestamps[t].date()
                    per_day[day] = per_day.get(day, 0) + 1
            result.hp_starts_per_day = per_day
            result.hp_starts_count = int(starts_bool[:num_steps].sum())

    def heat_supply(self, variables: dict, t: int, sink: str) -> Any:
        """Thermische Leistung an die jeweilige Senke (kW).

        - Bei aktivem Split (mehrere Senken): hp_power_<sink> * COP_<sink>
        - Bei nur einer Senke: hp_power * COP_<sink>
        - Bei nicht-bedienter Senke: 0
        """
        if sink not in self._active_sinks:
            return 0.0

        cop_arr = self._cop_heating if sink == "floor" else self._cop_dhw
        if cop_arr is None:
            return 0.0
        cop_t = float(cop_arr[t])

        split_key = f"hp_power_{sink}"
        if split_key in variables:
            return variables[split_key][t] * cop_t
        # Single-sink-Fall: hp_power speist direkt diese Senke
        return variables["hp_power"][t] * cop_t
