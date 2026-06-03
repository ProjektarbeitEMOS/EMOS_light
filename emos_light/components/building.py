"""Gebaeude-Modell fuer EMOS Light — optimiert fuer Neubau (KfW55/KfW40).

Berechnet temperaturabhaengigen Heizwaermebedarf und Warmwasserbedarf
und stellt seit der MILP-Erweiterung Mai 2026 die Raumlufttemperatur
T_innen als eigene Zustandsvariable im Solver bereit.

MILP-Erweiterung Mai 2026 — Raum als Zustandsvariable
=====================================================

Bis April 2026 wurde die Innentemperatur nicht modelliert; der
Heizwaermebedarf kam aus :meth:`calculate_heating_demand` als feste
Zeitreihe in den Solver. Damit "sah" der Solver nur den Estrich, nicht
aber das eigentliche Komfortziel (T_innen im Band) und nicht die
Verluste an die Aussenluft.

Mit der MILP-Erweiterung uebernimmt der Solver die Raum-Energiebilanz
explizit:

    C_room · (T_innen[t] − T_innen[t-1]) = (q_floor_to_room[t]
        − q_loss_outside[t]) · dt

mit:

    q_floor_to_room[t] = h_surface · A_floor / 1000
                         · (T_floor[t-1] − T_innen[t-1])       [kW]
    q_loss_outside[t]  = UA · (T_innen[t-1] − T_aussen[t])
                         / 1000                                 [kW]
    C_room             = building.shell_capacity_kwh_per_k     [kWh/K]
    UA                 = building.ua_w_per_k                   [W/K]

Diskretisierung: **explizites Euler** — alle Fluesse zum Zeitpunkt t
werden aus Zustaenden bei t-1 berechnet. Begruendung: bei dt=15 min
und thermischen Zeitkonstanten τ ≈ 10–100 h (Gebaeudehuelle) gilt
dt ≪ τ; das explizite Verfahren ist hier numerisch stabil und haelt
alle Constraints rein affin in den Entscheidungsvariablen
(LP-Kompatibilitaet). Der "prev"-Wert bei t=0 ist der Initialwert
:attr:`indoor_temp` (Raumtemperatur *vor* dem ersten Step) — t_innen[0]
wird **nicht** an indoor_temp festgeklammert, sondern aus der
Bilanz bei t=0 dynamisch berechnet (vermeidet ueberbestimmten Solver).

Komfort wird als Soft-Constraint mit Slack umgesetzt:
    T_min_comfort ≤ T_innen[t] + slack_low[t]
    T_innen[t] − slack_high[t] ≤ T_max_comfort
Die Slacks werden mit UNMET_HEAT_PENALTY_CT bestraft (siehe Optimizer).
"""

import datetime
from typing import Any

import numpy as np

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import make_var_array, step_hours


class Building(MILPComponent):
    """Gebaeude mit Waerme- und Warmwasserbedarf (Neubau)."""

    BUILDING_STANDARDS = {
        "neubau_enev": 50,
        "kfw55": 35,
        "kfw40": 25,
        "passivhaus": 15,
    }

    HW_PER_PERSON_KWH_DAY = 2.0

    # Physikalische Konstanten Luft (aus Projektgruppe Gebaeude)
    _AIR_DENSITY_KG_M3 = 1.2
    _AIR_SPECIFIC_HEAT_J_KG_K = 1000.0

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

        # Gebaeude-Thermospeicher (Wand + Luft, zusaetzlich zum Estrich)
        # Default aus DIN EN ISO 13786 (mittelschwere Bauweise): 50 Wh/(m²·K)
        self.wall_capacity_wh_per_m2_k = config.get("wall_capacity_wh_per_m2_k", 50.0)
        # Beheiztes Luftvolumen = Wohnflaeche * Faktor (3.1 aus EFH-Referenz)
        self.volume_factor = config.get("volume_factor", 3.1)
        # UA-Wert (W/K): optional explizit, sonst automatisch aus Heizlast
        self._ua_w_per_k_config = config.get("heat_loss_coefficient_w_per_k")

        # ------------------------------------------------------------------
        # Direkte Geometrie + U-Werte (Gebaeudegruppe, Mai 2026)
        # Wenn nicht in der Config angegeben, l/b aus heated_area abgeleitet
        # (annaehernd quadratischer Grundriss) und h auf 2.5 m typisches
        # Stockwerk gesetzt — passt zu vielen Einfamilienhaeusern.
        # ------------------------------------------------------------------
        import math
        side = math.sqrt(self.heated_area_m2)
        self.length_m = config.get("length_m", side)
        self.width_m = config.get("width_m", side)
        self.height_m = config.get("height_m", 2.5)
        # Default Fensterflaeche = 15% der Bruttowandflaeche (typisch EFH)
        wall_gross = 2 * self.height_m * (self.length_m + self.width_m)
        cfg_window = config.get("window_area_m2", None)
        self.window_area_m2 = (
            float(cfg_window) if cfg_window is not None else 0.15 * wall_gross
        )

        self.u_value_wall = config.get("u_value_wall_w_m2_k", 0.2)
        self.u_value_window = config.get("u_value_window_w_m2_k", 0.9)
        self.u_value_roof_floor = config.get("u_value_roof_floor_w_m2_k", 0.4)
        self.ventilation_loss_w_m3_k = config.get("ventilation_loss_w_m3_k", 0.17)

        self.screed_thickness_m = config.get("screed_thickness_m", 0.06)
        self.screed_density_kg_m3 = config.get("screed_density_kg_m3", 2000.0)
        self.screed_specific_heat_j_kg_k = config.get(
            "screed_specific_heat_j_kg_k", 1070.0
        )
        self.t_ref_c = config.get("reference_temp_c", 22.0)
        # Komfort-Untergrenze fuer die t_aus-Berechnung (z.B. 21 °C)
        self.t_min_c = config.get("comfort_min_temp_c", 21.0)

        # MILP-Komfortband fuer T_innen (Slack-Bestraft, siehe add_constraints)
        # Fallbacks: T_min = t_min_c, T_max = indoor_temp + 3 K
        self.comfort_temp_min_c = config.get(
            "comfort_temp_min_c", self.t_min_c
        )
        self.comfort_temp_max_c = config.get(
            "comfort_temp_max_c", self.indoor_temp + 3.0
        )

        # Wird von prepare() vom Optimizer befuellt (Aussentemperatur-Reihe).
        self._t_aus: np.ndarray | None = None

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

    # ========================================================================
    # Thermische Kapazitaet der Gebaeudehuelle (Wand + Luft, ohne Estrich)
    # ========================================================================

    @property
    def wall_capacity_kwh_per_k(self) -> float:
        """Waermekapazitaet der Waende in kWh/K.

        C_Wand = A_Wohn * 50 Wh/(m²·K) (DIN EN ISO 13786, mittelschwere Bauweise)
        """
        return self.heated_area_m2 * self.wall_capacity_wh_per_m2_k / 1000.0

    @property
    def air_volume_m3(self) -> float:
        """Beheiztes Luftvolumen in m³."""
        return self.heated_area_m2 * self.volume_factor

    @property
    def air_capacity_kwh_per_k(self) -> float:
        """Waermekapazitaet der Raumluft in kWh/K.

        C_Luft = V · ρ_Luft · c_p,Luft
        """
        joules_per_k = (
            self.air_volume_m3
            * self._AIR_DENSITY_KG_M3
            * self._AIR_SPECIFIC_HEAT_J_KG_K
        )
        return joules_per_k / 3_600_000.0  # J/K → kWh/K

    @property
    def shell_capacity_kwh_per_k(self) -> float:
        """Gesamte Huellkapazitaet (Wand + Luft, ohne Estrich) in kWh/K."""
        return self.wall_capacity_kwh_per_k + self.air_capacity_kwh_per_k

    # ========================================================================
    # Geometrie und U-Werte (Modell der Gebaeudegruppe, Mai 2026)
    # ========================================================================

    @property
    def wall_area_gross_m2(self) -> float:
        """Brutto-Aussenwandflaeche (mit Fenstern) in m²."""
        return 2.0 * self.height_m * (self.length_m + self.width_m)

    @property
    def wall_area_net_m2(self) -> float:
        """Aussenwandflaeche ohne Fenster (geclamped >= 0)."""
        return max(0.0, self.wall_area_gross_m2 - self.window_area_m2)

    @property
    def floor_plan_area_m2(self) -> float:
        """Grundflaeche l·b in m² (nicht zu verwechseln mit heated_area_m2)."""
        return self.length_m * self.width_m

    @property
    def building_volume_m3(self) -> float:
        """Beheiztes Volumen l·b·h in m³."""
        return self.floor_plan_area_m2 * self.height_m

    @property
    def transmission_ua_w_per_k(self) -> float:
        """UA-Anteil aus Transmission ueber Aussenwand, Fenster, Dach+Boden."""
        return (
            self.wall_area_net_m2 * self.u_value_wall
            + self.window_area_m2 * self.u_value_window
            + self.floor_plan_area_m2 * self.u_value_roof_floor
        )

    @property
    def ventilation_ua_w_per_k(self) -> float:
        """UA-Anteil aus Lueftung."""
        return self.ventilation_loss_w_m3_k * self.building_volume_m3

    @property
    def total_ua_w_per_k(self) -> float:
        """Gesamt-UA = Transmission + Lueftung."""
        return self.transmission_ua_w_per_k + self.ventilation_ua_w_per_k

    @property
    def ua_w_per_k(self) -> float:
        """Effektiver Waermeverlustkoeffizient (UA-Wert) in W/K.

        Prioritaet:
        1. ``heat_loss_coefficient_w_per_k`` aus der Config (manuell gesetzt)
        2. Direkte Berechnung aus U-Werten + Lueftung (Gebaeudegruppe Mai 2026)
        3. Fallback: Heuristik aus Heizlast und Auslegungstemperatur
        """
        if self._ua_w_per_k_config is not None:
            return float(self._ua_w_per_k_config)
        if self.total_ua_w_per_k > 0:
            return self.total_ua_w_per_k
        delta_design = self.indoor_temp - self.design_temp
        if delta_design <= 0:
            return 0.0
        return self.design_heating_load_kw * 1000.0 / delta_design

    # ========================================================================
    # Estrich-Kapazitaet (Schicht ueber l·b mit d_Estrich)
    # ========================================================================

    @property
    def screed_capacity_kwh_per_k(self) -> float:
        """Waermekapazitaet des Estrichs in kWh/K (c·ρ·V_Estrich)."""
        joules_per_k = (
            self.screed_specific_heat_j_kg_k
            * self.screed_density_kg_m3
            * self.floor_plan_area_m2
            * self.screed_thickness_m
        )
        return joules_per_k / 3_600_000.0  # J/K → kWh/K

    @property
    def total_capacity_kwh_per_k(self) -> float:
        """Gesamte thermische Kapazitaet C_Gebaeude in kWh/K.

        Modellentscheidung EMOS Light (Mai 2026): **nur der Estrich
        wird als Speicher gerechnet**. Wand und Luft werden bewusst
        vernachlaessigt — ihre Energie ist im Verhaeltnis zur Estrich-
        masse klein, transient nur langsam abrufbar und weicht zudem
        die Modellgrenzen auf (Was zaehlt zur "Hülle"? Welche Schichten
        haben welche Kapazität?).

        Die Wand-/Luft-Properties (:attr:`wall_capacity_kwh_per_k`,
        :attr:`air_capacity_kwh_per_k`) bleiben verfuegbar, falls
        zukuenftige Modellvarianten sie wieder einbinden moechten.
        """
        return self.screed_capacity_kwh_per_k

    # ========================================================================
    # Verlustleistung, Speicherenergie, Zeitkonstanten (Gebaeudegruppe)
    # ========================================================================

    def transmission_loss_w(self, t_innen_c: float, t_aussen_c: float) -> float:
        """P_Transmission in W bei gegebenen Temperaturen (Vorzeichen mitgefuehrt)."""
        return self.transmission_ua_w_per_k * (t_innen_c - t_aussen_c)

    def ventilation_loss_w(self, t_innen_c: float, t_aussen_c: float) -> float:
        """P_Lueftung in W bei gegebenen Temperaturen."""
        return self.ventilation_ua_w_per_k * (t_innen_c - t_aussen_c)

    def total_loss_w(self, t_innen_c: float, t_aussen_c: float) -> float:
        """Gesamte Verlustleistung in W = P_Transmission + P_Lueftung."""
        return self.total_ua_w_per_k * (t_innen_c - t_aussen_c)

    def stored_energy_kwh(self, t_innen_c: float) -> float:
        """Q_Gebaeude in kWh ueber dem Referenzniveau ``T_ref``.

        Konvention der Gebaeudegruppe (Mai 2026): Q_Gebaeude rechnet
        nur mit der Estrich-Kapazitaet, weil nur der Estrich seine
        Waerme "abrufbar" (kurzfristig an den Raum abgebbar) gespeichert
        hat. Die Wand puffert ueber ``time_constant_h`` mit, gibt ihre
        Energie aber nur sehr langsam ab — sie zaehlt nicht zur
        verfuegbaren Heizreserve.
        """
        return self.screed_capacity_kwh_per_k * (t_innen_c - self.t_ref_c)

    def time_constant_h(self, t_innen_c: float, t_aussen_c: float) -> float:
        """Zeitkonstante τ = C_Gebaeude / P_Verlust in Stunden.

        Folgt der Definition der Gebaeudegruppe (Mai 2026):
            τ(T_innen, T_außen) = C_Gebaeude · 1000 / P_Verlust(T_innen, T_außen)

        Vorzeichen wird durchgereicht — bei positiver Differenz
        (Innen > Außen, also Auskuehlen) ist τ positiv. Returns 0
        wenn das Gebaeude im thermischen Gleichgewicht ist (keine
        Verlustleistung, keine Eigenzeit definiert).
        """
        p_loss_w = self.total_loss_w(t_innen_c, t_aussen_c)
        if p_loss_w == 0:
            return 0.0
        return self.total_capacity_kwh_per_k * 1000.0 / p_loss_w

    def cooldown_time_h(
        self, t_innen_c: float, t_aussen_c: float, t_min_c: float | None = None,
    ) -> float:
        """t_aus in Stunden — Zeit bis das Gebaeude auf ``T_min`` abgekuehlt ist.

        Konvention der Gebaeudegruppe (Mai 2026):

            t_aus = C_Gebaeude · (T_innen − T_min) / P_Verlust(T_innen, T_außen)

        wobei C_Gebaeude die *gesamte* thermische Masse ist (Estrich + Wand).
        T_min ist die Komfort-Untergrenze (z.B. 21 °C), nicht der
        Referenzpunkt T_ref der Q-Berechnung.

        Vereinfachung: konstante P_Verlust waehrend des gesamten
        Auskuehlvorgangs (in Wirklichkeit verringert sich der Verlust,
        wenn die Innentemperatur sinkt — wuerde t_aus etwas verlaengern).

        Negativ wenn Außentemperatur > T_innen (Aufheizen statt Auskuehlen).
        """
        if t_min_c is None:
            t_min_c = self.t_min_c
        p_loss_w = self.total_loss_w(t_innen_c, t_aussen_c)
        if p_loss_w == 0:
            return 0.0
        delta_to_tmin = t_innen_c - t_min_c
        return self.total_capacity_kwh_per_k * delta_to_tmin * 1000.0 / p_loss_w

    # Hinweis: Die frueher hier vorhandene ``thermal_time_constant_h``-Methode
    # mit Wand+Luft-Anteil ist entfallen — die Modellentscheidung Mai 2026
    # vernachlaessigt Wand und Luft als Speicher. Verwende jetzt
    # :meth:`time_constant_h` (rein aus dem Estrich, mit T_innen/T_außen
    # statt einer fixen Δt-Annahme).

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

    # ========================================================================
    # MILP-Schnittstelle (Mai 2026): Raum als Zustandsvariable
    # ========================================================================

    @property
    def heat_sink_id(self) -> str | None:
        """Bezeichner als Waermesenke fuer den Raum-Bilanzknoten."""
        return "room"

    def prepare(self, inp: Any) -> None:
        """Aussentemperatur-Zeitreihe fuer Verlustterm puffern."""
        self._t_aus = np.asarray(inp.outside_temp_c, dtype=float)

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt T_innen-Zustandsvariable plus Komfort-Slacks.

        Variablen:
            t_innen[t]: Raumlufttemperatur in °C. Generoes bebounded um den
                Komfortbereich (Komfort kommt aus den Slacks, nicht aus
                harten Bounds), damit Auskuehlen/Ueberhitzen darstellbar
                bleibt.
            t_innen_slack_low_comfort[t]: Unterschreitung in der Komfortzone
                (bis 0.5 K), milderer Penalty (P_COMFORT).
            t_innen_slack_low_critical[t]: Unterschreitung darueber hinaus,
                schaerferer Penalty (P_CRITICAL). Unbeschraenkt.
            t_innen_slack_high[t]: Ueberschreitung des Komfortbands in K,
                wird im Optimizer mit UNMET_HEAT_PENALTY_CT bestraft.

        Hintergrund (Projektgruppe Penalty Slacks): die Unterschreitung
        wird in zwei Zonen unterteilt, weil eine kleine Komfortabweichung
        (z.B. 0.3 K kuehler als Soll) anders zu bewerten ist als ein
        deutliches Unterkuehlen (z.B. 2 K). Im Objective werden beide
        Slacks mit einem ueber die thermische Masse C_th skalierten
        Penalty multipliziert, damit die K -> ct-Umrechnung physikalisch
        konsistent ist (analog zu ww_slack in kWh).
        """
        return {
            "t_innen": make_var_array(
                "t_innen", num_steps,
                low=self.comfort_temp_min_c - 10.0,
                high=self.comfort_temp_max_c + 10.0,
            ),
            "t_innen_slack_low_comfort": make_var_array(
                "t_innen_slack_low_comfort", num_steps,
                low=0.0, high=0.5,
            ),
            "t_innen_slack_low_critical": make_var_array(
                "t_innen_slack_low_critical", num_steps, low=0.0,
            ),
            "t_innen_slack_high": make_var_array(
                "t_innen_slack_high", num_steps, low=0.0,
            ),
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Komfort-Soft-Constraints fuer T_innen.

        Die eigentliche Raum-Energiebilanz (C_room·ΔT/dt = q_in − q_loss)
        entsteht aus der generischen Phase-E-Heizbilanz des Optimizers:

            heat_supply("room") == heat_demand("room")

        wobei :meth:`heat_demand` den dynamischen Term liefert.
        """
        # step_minutes fuer heat_demand puffern (Phase E ruft heat_demand
        # ohne step_minutes auf — wir brauchen es dort fuer dt_h).
        self._step_minutes_cached = step_minutes
        t_innen = variables["t_innen"]
        slack_low_comfort = variables["t_innen_slack_low_comfort"]
        slack_low_critical = variables["t_innen_slack_low_critical"]
        slack_high = variables["t_innen_slack_high"]
        for t in range(len(t_innen)):
            # Unterschreitung: zwei Zonen — bis 0.5 K Komfortzone,
            # darueber Notfallzone. Die obere Schranke der Komfort-
            # Slack-Variable ist 0.5 K (siehe get_optimization_variables),
            # sodass der Solver bei groesseren Unterschreitungen
            # automatisch in die teurere Critical-Variable ueberlaeuft.
            model += (
                t_innen[t] + slack_low_comfort[t] + slack_low_critical[t]
                >= self.comfort_temp_min_c,
                f"t_innen_comfort_min_{t}",
            )
            model += (
                t_innen[t] - slack_high[t] <= self.comfort_temp_max_c,
                f"t_innen_comfort_max_{t}",
            )

    # ------------------------------------------------------------------
    # Bilanz-Beitraege fuer die Raum-Senke
    # ------------------------------------------------------------------

    def heat_demand(self, variables: dict, t: int, sink: str) -> Any:
        """Demand-Seite der Raum-Energiebilanz fuer Phase E.

        Liefert C_room·(T_innen[t]−T_innen_prev)/dt + UA·(T_innen_prev−T_aus[t])/1000.
        Zusammen mit ``heat_supply("room") = q_floor_to_room[t]`` (aus
        UFH) entsteht die explizite-Euler-Raumbilanz.
        """
        if sink != "room" or self._t_aus is None:
            return 0.0

        t_innen = variables["t_innen"]
        c_room = self.shell_capacity_kwh_per_k        # [kWh/K]
        ua_kw_per_k = self.ua_w_per_k / 1000.0        # [kW/K]
        dt_h = step_hours(self._step_minutes_cached)

        prev = self.indoor_temp if t == 0 else t_innen[t - 1]
        t_aus_t = float(self._t_aus[t])
        return c_room * (t_innen[t] - prev) / dt_h + ua_kw_per_k * (prev - t_aus_t)

    # add_constraints wird vom Optimizer aufgerufen — wir nutzen den
    # Aufruf, um step_minutes zwischenzuspeichern (heat_demand braucht es).
    _step_minutes_cached: int = 15

    def extract_result(
        self, result: Any, variables: dict, num_steps: int, dt_h: float,
    ) -> None:
        """Innentemperatur und Verlustleistung in das Ergebnis schreiben."""
        t_innen_vals = np.array(
            [v.varValue or 0.0 for v in variables["t_innen"]]
        )
        result.indoor_temp_c = t_innen_vals
        if self._t_aus is not None:
            # Verlust mit dem "prev"-Wert konsistent zum Modell: bei t=0
            # ist prev = indoor_temp (initial), sonst t_innen[t-1].
            prev = np.concatenate(([self.indoor_temp], t_innen_vals[:-1]))
            ua_kw_per_k = self.ua_w_per_k / 1000.0
            result.heat_loss_kw = ua_kw_per_k * (prev - self._t_aus[:num_steps])

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
