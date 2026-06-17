"""Waermepumpe mit SG-Ready Schnittstelle (BWP v1.1) fuer EMOS Light.

COP-Modell basiert auf realen Kennlinien der Vaillant aroTHERM plus
VWL 105/6 (EN 14511). 2D-Interpolation ueber Aussentemperatur
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

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_min_hold_time,
    add_min_pause_time,
    add_min_run_time,
    make_binary_array,
    make_var_array,
    steps_for_minutes,
)
from emos_light.utils.interpolation import interp_2d


# ============================================================
# Kennlinien: Vaillant aroTHERM plus VWL 105/6 (EN 14511)
# ============================================================

# Stuetzstellen aus den Leistungstabellen des Vaillant-Datenblatts
# "aroTHERM plus (Luft/Wasser) - Leistungstabellen", Seite VWL 105/6
# (Stand 17.06.2024). Feinere Aussentemperatur-Achse (15 Stuetzstellen
# statt frueher nur -7/2/7) und vier Vorlauftemperaturen:
_OUTDOOR_TEMPS = np.array([
    -20.0, -15.0, -10.0, -8.0, -6.0, -4.0, -2.0,
    0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0,
])
_FLOW_TEMPS = np.array([35.0, 45.0, 55.0, 65.0])

# COP-Matrix [outdoor x flow], Spalte = Vorlauftemperatur.
# Werte = COP der **Maximalleistung** (Modulationsmaximum) aus den
# Leistungstabellen — gleicher Betriebspunkt wie _CAPACITY_TABLE, daher
# P_el_max = P_th_max / COP konsistent. Das Datenblatt fuehrt zusaetzlich
# die Minimalleistung mit hoeherem Teillast-COP; fuer das Ein-Wert-Modell
# wird bewusst der (konservative) Volllast-COP genommen.
# Hinweis: 65 C Vorlauf wird unter -10 C Aussen nicht erreicht ("--" im
# Datenblatt); die Zellen A-20/A-15 @ W65 sind vorsichtig extrapoliert
# (knapp unter der W55-Spalte) und im Modell faktisch nie Betriebspunkt
# (WW-Vorlauf default 55 C).
_COP_TABLE = np.array([
    # W35   W45   W55   W65
    [2.3,  1.9,  1.4,  1.3],   # A-20  (W65 extrapoliert)
    [2.5,  2.0,  1.6,  1.4],   # A-15  (W65 extrapoliert)
    [2.8,  2.3,  1.8,  1.5],   # A-10
    [2.9,  2.4,  1.9,  1.5],   # A-8
    [3.1,  2.5,  2.0,  1.6],   # A-6
    [3.3,  2.7,  2.1,  1.7],   # A-4
    [3.4,  2.8,  2.2,  1.8],   # A-2
    [3.6,  3.0,  2.3,  1.9],   # A0
    [3.8,  3.2,  2.5,  1.9],   # A2
    [4.0,  3.3,  2.6,  2.0],   # A4
    [4.2,  3.5,  2.7,  2.2],   # A6
    [4.3,  3.6,  2.8,  2.3],   # A8
    [4.4,  3.6,  2.9,  2.4],   # A10
    [4.5,  3.7,  3.0,  2.6],   # A15
    [4.9,  3.8,  3.1,  2.7],   # A20
])

# Maximale thermische Heizleistung [kW] im **Modulationsmaximum**
# (Spalte "Maximalleistung / Heizleistung kW" der Leistungstabellen).
# Obere Schranke fuer die thermische WP-Leistung; der Solver entscheidet
# anhand Heizlast/Kosten, wieviel genutzt wird. Anders als die fruehere
# (fehlerhafte) Tabelle sinkt die Leistung jetzt korrekt mit steigender
# Vorlauftemperatur. A-20/A-15 @ W65 extrapoliert (s.o.).
_CAPACITY_TABLE = np.array([
    # W35    W45    W55    W65
    [7.3,   6.8,   6.4,   6.2],   # A-20  (W65 extrapoliert)
    [8.0,   7.4,   7.1,   7.0],   # A-15  (W65 extrapoliert)
    [9.1,   8.8,   8.2,   7.8],   # A-10
    [9.5,   9.4,   8.6,   8.2],   # A-8
    [10.1,  9.9,   9.1,   8.5],   # A-6
    [10.9, 10.5,   9.5,   9.3],   # A-4
    [11.7, 11.2,  10.0,   9.8],   # A-2
    [12.5, 12.0,  10.7,  10.0],   # A0
    [13.3, 12.8,  11.4,  10.2],   # A2
    [14.0, 13.5,  11.8,  11.0],   # A4
    [14.6, 14.1,  12.2,  11.8],   # A6
    [15.0, 14.5,  12.7,  12.3],   # A8
    [15.2, 14.7,  13.2,  12.5],   # A10
    [15.4, 14.9,  13.9,  12.8],   # A15
    [14.9, 14.2,  13.5,  12.6],   # A20
])

# Minimale thermische Modulation: laut Leistungstabellen liegt die
# Minimalleistung (Heizleistung kW) ueber den Aussentemperaturen bei
# ~3-6 kW thermisch (z.B. A2/W35: 4.9 kW). Im Modell wird die Untergrenze
# ueber ``min_electrical_power_kw`` (Default 1.0 kW) durchgesetzt — bei
# COP ~4 entspricht das ~4 kW thermisch.

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
        # Mindestlaufzeit nach Einschalten — Default 60 min (Prof-Hinweis
        # Mai 2026). Innerhalb dieser Zeit darf zwischen FBH und WW
        # umgeschaltet werden (siehe hp_mode_ww-Constraint).
        self.min_run_minutes = config.get("min_run_time_minutes", 60)
        self.min_pause_minutes = config.get("min_pause_time_minutes", 15)
        # Eingebauter elektrischer Heizstab (Backup-/Zusatzheizer) im
        # Heizwasserkreis. Elektrisch modulierbar 0..max, COP 1 (resistiv).
        # Er ist im Normalbetrieb aus: WP-Waerme ist pro kWh immer guenstiger
        # (COP > 1), der Solver nutzt den Stab daher nur, wenn die WP an ihrer
        # Kennfeld-Kapazitaet haengt und sonst das Komfortband verletzt wuerde.
        self.backup_heater_enabled = bool(
            config.get("backup_heater_enabled", True)
        )
        self.backup_heater_max_power_kw = float(
            config.get("backup_heater_max_power_kw", 8.5)
        )
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
        self._max_electrical_power_kw_t: np.ndarray | None = None
        # Modus-spezifische el. Maxima (W35 / W55) — bilden die physikalische
        # Kennfeld-Kapazitaet pro Senke ab (siehe add_constraints).
        self._p_el_floor_t: np.ndarray | None = None
        self._p_el_ww_t: np.ndarray | None = None
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

    def calculate_max_electrical_power_per_mode(
        self, outside_temp_c: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Max. elektrische Leistung [kW] je Betriebsmodus (FBH / WW).

        Aus dem Kennfeld: ``P_el_max = P_th_max / COP`` — getrennt fuer den
        Heizkreis-Vorlauf (W35) und den WW-Vorlauf (W55), jeweils geclippt
        an die statische Hardware-Obergrenze ``max_electrical_power_kw``.

        Wichtig: die beiden Werte muessen **modus-spezifisch** angewandt
        werden. Wuerde man (wie frueher) das Maximum beider als gemeinsamen
        Cap nehmen, koennte der Solver im FBH-Modus die hohe W35-COP mit dem
        groesseren WW-Modus-Cap multiplizieren und damit mehr FBH-Waerme
        liefern, als das Kennfeld bei W35 physikalisch hergibt.

        Returns:
            (p_el_floor, p_el_ww), beide gleicher Laenge wie outside_temp_c.
        """
        p_th_h = self.calculate_max_thermal_capacity(
            outside_temp_c, self.flow_temp_heating,
        )
        cop_h = self.calculate_cop(outside_temp_c, self.flow_temp_heating)
        p_el_h = np.divide(
            p_th_h, cop_h, where=cop_h > 0, out=np.zeros_like(p_th_h, dtype=float),
        )

        p_th_w = self.calculate_max_thermal_capacity(
            outside_temp_c, self.flow_temp_dhw,
        )
        cop_w = self.calculate_cop(outside_temp_c, self.flow_temp_dhw)
        p_el_w = np.divide(
            p_th_w, cop_w, where=cop_w > 0, out=np.zeros_like(p_th_w, dtype=float),
        )
        cap = self.max_power_kw
        return np.minimum(p_el_h, cap), np.minimum(p_el_w, cap)

    def calculate_max_electrical_power(
        self, outside_temp_c: np.ndarray
    ) -> np.ndarray:
        """Hardware-Huellkurve der el. Leistung [kW] (Maximum beider Modi).

        Nur als Anzeige-/Hilfslinie (Dashboard) und als loser Gesamt-Cap
        gedacht — die *bindende* Modulationsobergrenze wird in
        :meth:`add_constraints` **modus-spezifisch** gesetzt (siehe
        :meth:`calculate_max_electrical_power_per_mode`).
        """
        p_el_floor, p_el_ww = self.calculate_max_electrical_power_per_mode(
            outside_temp_c,
        )
        return np.maximum(p_el_floor, p_el_ww)

    # ============================================================
    # Setup-Hooks (vom Optimizer aufgerufen)
    # ============================================================

    def prepare(self, inp: Any) -> None:
        """Vorberechnung der COP- und max-Leistungs-Zeitreihen aus der
        Aussentemperatur."""
        self._cop_heating = self.calculate_cop_heating(inp.outside_temp_c)
        self._cop_dhw = self.calculate_cop_dhw(inp.outside_temp_c)
        # Dynamische maximale elektrische Leistung pro Zeitschritt —
        # ersetzt die statische ``max_electrical_power_kw`` als bindende
        # Obergrenze in add_constraints. Cached fuer extract_result.
        self._p_el_floor_t, self._p_el_ww_t = (
            self.calculate_max_electrical_power_per_mode(inp.outside_temp_c)
        )
        self._max_electrical_power_kw_t = np.maximum(
            self._p_el_floor_t, self._p_el_ww_t,
        )
        # Zeitstempel puffern — werden in extract_result fuer die
        # Tagesgruppierung der Einschalt-Zaehlung (Diagnose) gebraucht.
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
            hp_start[t]: Binaer — Einschaltvorgang OFF -> ON bei t. Reine
                Diagnose-/Reporting-Variable (exakt an hp_on gekoppelt, s.u.),
                kein hartes Tageslimit mehr. Die Verdichter-Schonung kommt
                jetzt allein ueber die Mindestlaufzeit (min_run_time_minutes,
                Default 60 min). Umschalten zwischen FBH und WW zaehlt **nicht**
                als Start, solange die WP an bleibt.
            hp_rod_power[t]: Elektrische Leistung des eingebauten Heizstabs
                [kW], modulierbar 0..backup_heater_max_power_kw. Speist als
                Zusatzwaerme (COP 1) in den Floor-Heizkreis. Nur erzeugt, wenn
                der Heizstab aktiviert und die Floor-Senke aktiv ist. Bleibt im
                Normalbetrieb 0 (WP-Waerme ist pro kWh guenstiger) — der Solver
                zieht ihn nur, wenn die WP an ihrer Kennfeld-Kapazitaet haengt.
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
        # Eingebauter Heizstab (Backup-Heater): modulierbare el. Leistung
        # 0..max, speist als Zusatzwaerme (COP 1) in den Heizkreis (Floor).
        # Nur sinnvoll, wenn die Raumheizung (Floor-Senke) aktiv ist.
        if self.backup_heater_enabled and "floor" in self._active_sinks:
            result["hp_rod_power"] = make_var_array(
                "hp_rod_power", num_steps,
                low=0.0, high=self.backup_heater_max_power_kw,
            )
        if self.sg_ready:
            result["hp_sg1"] = make_binary_array("hp_sg1", num_steps)
            result["hp_sg2"] = make_binary_array("hp_sg2", num_steps)
            result["hp_sg3"] = make_binary_array("hp_sg3", num_steps)
            result["hp_sg4"] = make_binary_array("hp_sg4", num_steps)

        # Senken-Split nur wenn mehr als eine Senke aktiv.
        # Wichtig (Projektgruppe Leistungsaufteilung, Mai 2026): die WP hat
        # nur einen Heizkreis + 3-Wege-Ventil, also gibt es eine ECHTE
        # Entweder-Oder-Entscheidung pro Zeitschritt zwischen FBH und WW
        # (kein gemischter Betrieb innerhalb eines 15-min-Blocks, weil
        # die thermische Einschwingzeit bei einem Umschalt-Block schon
        # mehrere Minuten verbraucht). Die Binaervariable ``hp_mode_ww[t]``
        # entscheidet: 0 = FBH-Modus (hp_power_ww=0), 1 = WW-Modus
        # (hp_power_floor=0). COP ist pro Block eindeutig — bei z=0 zaehlt
        # COP_heating (W35), bei z=1 zaehlt COP_dhw (W55).
        if len(self._active_sinks) > 1:
            result["hp_mode_ww"] = make_binary_array(
                "hp_mode_ww", num_steps,
            )
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

        # Modulationsbereich mit T-abhaengiger Obergrenze (Mai 2026):
        # Die maximale elektrische Leistung wird pro Zeitschritt aus dem
        # Kennfeld berechnet (siehe calculate_max_electrical_power und
        # prepare). Bei kalten Tagen kann die WP weniger el. ziehen als
        # die Modulations-Obergrenze ``max_power_kw`` zulaesst, bei sehr
        # warmen Tagen ebenfalls (geringerer Bedarf, geringerer Output).
        # Untergrenze: statisch wie zuvor (Mindestleistung beim Einschalten).
        max_t = (
            self._max_electrical_power_kw_t
            if self._max_electrical_power_kw_t is not None
            else np.full(num_steps, self.max_power_kw)
        )
        p_el_floor = (
            self._p_el_floor_t if self._p_el_floor_t is not None else max_t
        )
        p_el_ww = (
            self._p_el_ww_t if self._p_el_ww_t is not None else max_t
        )
        # Gesamt-Cap modus-spezifisch waehlen: bei GENAU einer aktiven Senke
        # ist der Cap deren Kennfeld-Maximum (W35 fuer FBH, W55 fuer WW).
        # Sonst der lose max(beide); die echte physikalische Grenze pro Pfad
        # setzen dann die Split-Caps weiter unten. Ohne das wuerde die hohe
        # FBH-COP * (groesseren) WW-Cap mehr Waerme liefern als das Kennfeld.
        if self._active_sinks == {"floor"}:
            cap_t = p_el_floor
        elif self._active_sinks == {"ww"}:
            cap_t = p_el_ww
        else:
            cap_t = max_t
        for t in range(num_steps):
            model += (
                hp_power[t] <= float(cap_t[t]) * hp_on[t],
                f"hp_max_t_{t}",
            )
            if self.min_power_kw > 0:
                model += (
                    hp_power[t] >= self.min_power_kw * hp_on[t],
                    f"hp_min_t_{t}",
                )

        add_min_run_time(model, hp_on, min_run_steps=min_run_steps, name="hp")
        add_min_pause_time(model, hp_on, min_pause_steps=min_pause_steps, name="hp")

        # Einschalt-Indikator (reine Diagnose, kein Tageslimit mehr). Die
        # Verdichter-Schonung laeuft jetzt allein ueber die Mindestlaufzeit
        # (add_min_run_time oben). hp_start wird trotzdem mitgefuehrt, damit
        # das Dashboard/die Baseline die Schaltzahl vergleichen koennen —
        # exakt an hp_on gekoppelt (sonst haette der Solver ohne Limit keinen
        # Anreiz, hp_start klein zu halten, und die Zaehlung waere falsch):
        #   hp_start[t] >= hp_on[t] - hp_on[t-1]   (1 beim Einschalten)
        #   hp_start[t] <= hp_on[t]                (0 wenn WP aus)
        #   hp_start[t] <= 1 - hp_on[t-1]          (0 wenn vorher schon an)
        # Bei t=0 nehmen wir an, die WP war vorher AUS (konservativ; im MPC-
        # Folgewindow zaehlt eine durchlaufende WP einmalig als Start). Diese
        # Constraints aendern das Optimum nicht — hp_start kommt sonst nirgends
        # vor (weder Zielfunktion noch andere Restriktion).
        hp_start = variables["hp_start"]
        for t in range(num_steps):
            prev = 0 if t == 0 else hp_on[t - 1]
            model += (
                hp_start[t] >= hp_on[t] - prev,
                f"hp_start_link_{t}",
            )
            model += (
                hp_start[t] <= hp_on[t],
                f"hp_start_ub_on_{t}",
            )
            model += (
                hp_start[t] <= 1 - prev,
                f"hp_start_ub_prev_{t}",
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

        # Senken-Split + Entweder-Oder-Modus (Mai 2026 — Projektgruppe
        # Leistungsaufteilung): hp_power[t] = hp_power_floor[t] + hp_power_ww[t]
        # PLUS Big-M-Constraint, dass pro Zeitschritt genau eine Senke
        # bedient wird:
        #
        #   hp_mode_ww[t] = 0  =>  hp_power_ww[t]    = 0  (FBH-Modus)
        #   hp_mode_ww[t] = 1  =>  hp_power_floor[t] = 0  (WW-Modus)
        #
        # Physikalisch: die WP hat einen Heizkreis + 3-Wege-Ventil. Bei
        # Umschaltung innerhalb eines 15-min-Blocks geht die Einschwing-
        # zeit (FBH->WW ~5-15 min, WW->FBH ~2-5 min) verloren, der Block
        # waere fast nutzlos und der COP unscharf. Mit z_t bleibt der COP
        # pro Block eindeutig (W35 oder W55).
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
            # Physikalische Kennfeld-Kapazitaet je Pfad: W35 fuer FBH, W55
            # fuer WW. Verhindert, dass der lose Gesamt-Cap zusammen mit der
            # hohen FBH-COP mehr FBH-Waerme liefert als das Kennfeld bei W35
            # hergibt (Code-Review Juni 2026).
            if "hp_power_floor" in variables:
                pf = variables["hp_power_floor"]
                for t in range(num_steps):
                    model += (
                        pf[t] <= float(p_el_floor[t]),
                        f"hp_cap_floor_{t}",
                    )
            if "hp_power_ww" in variables:
                pw = variables["hp_power_ww"]
                for t in range(num_steps):
                    model += (
                        pw[t] <= float(p_el_ww[t]),
                        f"hp_cap_ww_{t}",
                    )
            # Entweder-Oder-Mutex via Big-M
            mode_ww = variables.get("hp_mode_ww")
            if (
                mode_ww is not None
                and "hp_power_floor" in variables
                and "hp_power_ww" in variables
            ):
                p_floor = variables["hp_power_floor"]
                p_ww = variables["hp_power_ww"]
                for t in range(num_steps):
                    model += (
                        p_floor[t] <= self.max_power_kw * (1 - mode_ww[t]),
                        f"hp_mode_floor_{t}",
                    )
                    model += (
                        p_ww[t] <= self.max_power_kw * mode_ww[t],
                        f"hp_mode_ww_{t}",
                    )

    # ------------------------------------------------------------------
    # Bilanz-Beitraege
    # ------------------------------------------------------------------

    def electrical_demand(self, variables: dict, t: int) -> Any:
        """Gesamte WP-Wirkleistung als Last am AC-Knoten (inkl. Heizstab)."""
        demand = variables["hp_power"][t]
        rod = variables.get("hp_rod_power")
        if rod is not None:
            demand = demand + rod[t]
        return demand

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
        # Eingebauter Heizstab (Backup-Heater) — 0, wenn deaktiviert/keine
        # Floor-Senke. Dient dem Dashboard als Fahrplan und macht sichtbar,
        # wann die WP-Kennfeld-Kapazitaet nicht reichte.
        if "hp_rod_power" in variables:
            result.hp_rod_power_kw = np.array(
                [v.varValue or 0.0 for v in variables["hp_rod_power"]]
            )
        else:
            result.hp_rod_power_kw = np.zeros(num_steps)
        # Dynamische Max-Leistung pro Zeitschritt (T-abhaengig), damit
        # das Dashboard die Modulations-Obergrenze als Hilfslinie zeichnen
        # kann. Wenn prepare() nicht gelaufen ist, fall back zur statischen
        # Modulationsobergrenze.
        if self._max_electrical_power_kw_t is not None:
            result.hp_max_power_kw = np.asarray(
                self._max_electrical_power_kw_t[:num_steps], dtype=float,
            )
        else:
            result.hp_max_power_kw = np.full(num_steps, self.max_power_kw)
        # Entweder-Oder-Modus: 1 bei WW-Modus, 0 bei FBH-Modus (nur wenn
        # beide Senken aktiv sind, sonst bleibt das Feld leer).
        if "hp_mode_ww" in variables:
            result.hp_mode_ww = np.array(
                [int((v.varValue or 0.0) > 0.5)
                 for v in variables["hp_mode_ww"]]
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
        # in Summe — Diagnose fuer das Dashboard (Verdichter-Schaltzahl).
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
        - Zzgl. eingebautem Heizstab (COP 1) auf dem Floor-Heizkreis.
        """
        if sink not in self._active_sinks:
            return 0.0

        cop_arr = self._cop_heating if sink == "floor" else self._cop_dhw
        if cop_arr is None:
            return 0.0
        cop_t = float(cop_arr[t])

        split_key = f"hp_power_{sink}"
        if split_key in variables:
            heat = variables[split_key][t] * cop_t
        else:
            # Single-sink-Fall: hp_power speist direkt diese Senke
            heat = variables["hp_power"][t] * cop_t

        # Eingebauter Heizstab speist als resistive Zusatzwaerme (COP 1) den
        # Heizkreis (Floor). Liefert die Reserve, wenn die WP bei tiefen
        # Aussentemperaturen an ihrer Kennfeld-Kapazitaet haengt.
        if sink == "floor" and "hp_rod_power" in variables:
            heat = heat + variables["hp_rod_power"][t]
        return heat
