"""Gebaeude-Modell fuer EMOS Light — optimiert fuer Neubau (KfW55/KfW40).

Berechnet temperaturabhaengigen Heizwaermebedarf und Warmwasserbedarf
und stellt seit der MILP-Erweiterung Mai 2026 die Raumlufttemperatur
T_innen als eigene Zustandsvariable im Solver bereit.

3-Speicher-Modell (ETH Zuerich, Gebaeudegruppe Juni 2026)
=========================================================

Neustrukturierung der Waermebilanz nach der Schweizer Studie. Statt
einem Raumknoten mit pauschalem UA-Verlust werden drei thermische
Speicher gefuehrt:

    1. Estrich/Fussboden  T_B   (Komponente UnderfloorHeating)
    2. Raumluft           T_R = t_innen   (diese Komponente)
    3. Aussenwand         T_W = t_wand    (diese Komponente, NEU)

Das Heizwasser (urspruenglich Speicher 1 der ETH-Studie) wird gemaess
Korrektur **K2** quasistationaer eliminiert (dT_RL/dt = 0, Zeitkonstante
≪ 15 min) — uebrig bleibt, dass die WP-Waermeleistung direkt in den
Estrich fliesst (Korrektur **K1**: ``Q_WP`` ist Entscheidungsvariable,
nicht das bilineare ``V_WP·T_RL``). Das entspricht exakt dem bisherigen
``q_floor_in`` von EMOS Light.

Raum-Energiebilanz (Speicher 3, Korrektur **K3**):

    C_R · (T_R[t] − T_R[t-1]) / dt = q_floor_to_room[t]
        − k_RW·A_W · (T_R[t] − T_W[t-1])      (Verlust ueber traege Wand)
        − UA_direkt · (T_R[t] − T_A[t])       (Fenster + Dach + Lueftung,
                                               OHNE Traegheit)
        + Q_g,R[t]                            (interne + solare Gewinne)

Wand-Energiebilanz (Speicher 4):

    C_W · (T_W[t] − T_W[t-1]) / dt =
          k_RW·A_W · (T_R[t] − T_W[t-1])      (Raum -> Wand)
        − k_WA·A_W · (T_W[t-1] − T_A[t])      (Wand -> Aussen)

mit:

    C_R       = air_capacity_kwh_per_k          (nur Luft! die Wandmasse
                sitzt jetzt im T_W-Knoten — kein Doppelzaehlen)
    C_W       = wall_capacity_kwh_per_k         (DIN EN ISO 13786)
    UA_direkt = ua_direct_w_per_k               (total_ua − Wandtransmission)
    k_RW,k_WA = Wand-Uebergangszahlen, an u_value_wall verankert

Diskretisierung: Die langsamen Knoten (Estrich τ≈3-4 h, Wand τ≈2-3 h)
laufen mit **explizitem Euler** (Fluesse aus t-1), der schnelle Raum-
luftknoten (reine Luft, τ≈Minuten) wird **implizit** gefuehrt
(Verlust- und Estrich->Raum-Term auf T_R[t]). Implizit-fuer-den-
schnellen-Knoten ist unbedingt stabil und bleibt linear/LP-kompatibel
— ohne das wuerde explizites Euler bei dt=15 min oszillieren, weil
dt > τ_Luft. Der Raum->Wand-Fluss nutzt in beiden Bilanzen denselben
Ausdruck k_RW·A_W·(T_R[t]−T_W[t-1]) -> energetisch konserviert.

Anmerkung zu den k-Werten: die Gebaeudegruppe gibt k_RW=2.5 und
k_WA=25 W/(m²·K) an — das sind Oberflaechen-Filmkoeffizienten, deren
Reihenschaltung U_eff≈2.27 W/(m²·K) ergaebe (Daemmung fehlt, ~10x zu
leck fuer ein KfW-Haus). Default ``wall_anchor_to_u_value=True`` koppelt
daher die Reihen-U der Wand an ``u_value_wall`` (physikalisch konsistent
zu Fenster/Dach) und nutzt nur das *Verhaeltnis* k_RW:k_WA als
Aufteilung der Wandkapazitaet. Mit ``wall_anchor_to_u_value=False``
werden die rohen Werte verwendet (Vergleichsrechnungen).

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
        # 3-Speicher-Modell (ETH Zuerich, Gebaeudegruppe Juni 2026):
        # Wand als eigener Zustand T_W zwischen Raum und Aussenluft.
        # ------------------------------------------------------------------
        # Wand-Uebergangszahlen k (Oberflaechen-Filmkoeffizienten der
        # Gebaeudegruppe). k_RW raumseitig, k_WA aussenseitig.
        self.wall_k_rw_w_m2_k = float(config.get("wall_k_rw_w_m2_k", 2.5))
        self.wall_k_wa_w_m2_k = float(config.get("wall_k_wa_w_m2_k", 25.0))
        # True: Reihen-U der Wand an u_value_wall ankern (siehe Modul-Doku),
        # k_RW:k_WA nur als Aufteilungsverhaeltnis. False: rohe k-Werte.
        self.wall_anchor_to_u_value = bool(
            config.get("wall_anchor_to_u_value", True)
        )
        # Anfangstemperatur der Wandmasse (None -> indoor_temp).
        _iwt = config.get("initial_wall_temp_c")
        self.initial_wall_temp_c = (
            float(_iwt) if _iwt is not None else self.indoor_temp
        )
        # Solare + interne Raumgewinne Q_g,R (Gebaeudegruppe Juni 2026):
        #   Q_g,R = g·A_Fenster·DNI·cos(theta) + q_int·A_Wohn   (Q_g,B = 0).
        # Der solare Anteil wird in :meth:`compute_room_gain_w` aus dem
        # Sonnenstand berechnet; hier nur die Parameter + der konstante
        # interne Anteil.
        self.solar_gains_enabled = bool(config.get("solar_gains_enabled", True))
        self.window_g_value = float(config.get("window_g_value", 0.7))
        self.window_azimuth_deg = float(config.get("window_azimuth_deg", 180.0))
        self.internal_gains_w_per_m2 = float(
            config.get("internal_gains_w_per_m2", 5.0)
        )
        # Zusaetzlicher absoluter Offset [W] (Default 0).
        self.internal_gains_w = float(config.get("internal_gains_w", 0.0))
        # Konstanter interner Gewinn (DIN V 4108: q_int·A_Wohn + Offset) [W].
        self.internal_gain_w_const = (
            self.internal_gains_w_per_m2 * self.heated_area_m2
            + self.internal_gains_w
        )
        # Vorberechnete Q_g,R-Zeitreihe [W] — von prepare() aus inp gefuellt.
        self._q_g_r_w: np.ndarray | None = None

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
    # 3-Speicher-Modell: Wandknoten T_W (ETH Zuerich, Juni 2026)
    # ========================================================================

    @property
    def wall_node_area_m2(self) -> float:
        """Wirksame Wandflaeche fuer den T_W-Knoten (Netto-Aussenwand)."""
        return self.wall_area_net_m2

    @property
    def room_capacity_kwh_per_k(self) -> float:
        """Waermekapazitaet des Raumknotens C_R im 3-Speicher-Modell.

        Nur die **Raumluft** — die Wandmasse sitzt jetzt im eigenen
        T_W-Knoten (:attr:`wall_capacity_kwh_per_k`). Wuerde man hier die
        Huellkapazitaet (Wand+Luft) nehmen, waere die Wandmasse doppelt
        gezaehlt.
        """
        return self.air_capacity_kwh_per_k

    @property
    def wall_conductance_rw_w_per_k(self) -> float:
        """Leitwert Raum -> Wandkern k_RW·A_W [W/K].

        Mit ``wall_anchor_to_u_value`` wird die Reihenschaltung
        (k_RW, k_WA) so skaliert, dass ihr effektives U dem physikalischen
        Wand-U-Wert (``u_value_wall``) entspricht — die rohen k-Werte der
        Gebaeudegruppe sind Oberflaechen-Filme und wuerden die Wand sonst
        ~10x zu leck machen. Das Verhaeltnis k_RW:k_WA bleibt erhalten.
        """
        return self._wall_conductances_w_per_k()[0]

    @property
    def wall_conductance_wa_w_per_k(self) -> float:
        """Leitwert Wandkern -> Aussenluft k_WA·A_W [W/K]."""
        return self._wall_conductances_w_per_k()[1]

    def _wall_conductances_w_per_k(self) -> tuple[float, float]:
        """(G_RW, G_WA) in W/K fuer die beiden Wand-Halbpfade."""
        a_w = self.wall_node_area_m2
        k_rw, k_wa = self.wall_k_rw_w_m2_k, self.wall_k_wa_w_m2_k
        if k_rw <= 0 or k_wa <= 0 or a_w <= 0:
            return 0.0, 0.0
        if self.wall_anchor_to_u_value:
            # Reihen-U auf u_value_wall ankern, Verhaeltnis k_RW:k_WA als
            # Aufteilung der Gesamt-Widerstaende beibehalten.
            r_rw, r_wa = 1.0 / k_rw, 1.0 / k_wa
            r_total_target = 1.0 / self.u_value_wall  # physikalische Wand
            scale = r_total_target / (r_rw + r_wa)
            k_rw_eff = 1.0 / (r_rw * scale)
            k_wa_eff = 1.0 / (r_wa * scale)
        else:
            k_rw_eff, k_wa_eff = k_rw, k_wa
        return k_rw_eff * a_w, k_wa_eff * a_w

    @property
    def ua_direct_w_per_k(self) -> float:
        """Direkter (traegheitsfreier) Verlustleitwert Raum -> Aussen [W/K].

        Alles ausser der opaken Aussenwand: Fenster + Dach/Bodenplatte +
        Lueftung. Die Wand laeuft im 3-Speicher-Modell ueber den traegen
        T_W-Knoten und ist hier daher herausgerechnet (Korrektur K3).
        """
        wall_transmission = self.wall_area_net_m2 * self.u_value_wall
        return max(0.0, self.total_ua_w_per_k - wall_transmission)

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
        """Aussentemperatur und Raumgewinne Q_g,R fuer den Solver puffern."""
        self._t_aus = np.asarray(inp.outside_temp_c, dtype=float)
        n = len(self._t_aus)
        # Q_g,R: bevorzugt die in scenario.build_time_series_input vorbe-
        # rechnete Zeitreihe (enthaelt den Sonnenstand-abhaengigen Solar-
        # anteil). Fehlt sie (z.B. Optimizer ohne Wetterkontext), nur den
        # konstanten internen Anteil ansetzen.
        rg = getattr(inp, "room_gain_w", None)
        if rg is not None and len(rg) >= n and n > 0:
            self._q_g_r_w = np.asarray(rg[:n], dtype=float)
        else:
            self._q_g_r_w = np.full(n, self.internal_gain_w_const, dtype=float)

    def compute_room_gain_w(
        self,
        timestamps: list,
        ghi_w_m2: np.ndarray | None,
        dni_w_m2: np.ndarray | None,
        latitude: float | None,
        longitude: float | None,
    ) -> np.ndarray:
        """Berechnet Q_g,R (solar + intern) als Zeitreihe in W.

        Solarer Fenstergewinn nach der Gebaeudegruppe (Juni 2026):

            Q_solar = g · A_Fenster · DNI · cos(theta)
            cos(theta) = max(0, cos(gamma_S) · cos(alpha_S − alpha_E))

        mit gamma_S = Sonnenhoehe, alpha_S = Sonnenazimut, alpha_E =
        Fensterazimut (beide in EMOS-Konvention 0=N, 90=O, 180=S, 270=W —
        gleiche Konvention fuer beide, daher ohne das Minus aus dem
        Gebaeudegruppen-Dokument, das nur deren Azimut-Offset ausglich).
        Modelliert den **direkten** Strahleinfall (Beam); der Diffusanteil
        wird vernachlaessigt. DNI kommt aus den Wetterdaten, sonst aus der
        DISC-Zerlegung der GHI. Dazu der konstante interne Anteil
        (DIN V 4108).
        """
        import math

        n = len(timestamps)
        internal = float(self.internal_gain_w_const)
        gains = np.full(n, internal, dtype=float)
        if (
            not self.solar_gains_enabled
            or ghi_w_m2 is None
            or latitude is None
            or longitude is None
            or n == 0
            or len(ghi_w_m2) < n
        ):
            return gains

        from emos_light.data.solar import (
            solar_position,
            detect_timezone_offset,
            _disc_decomposition,
        )

        ghi = np.asarray(ghi_w_m2, dtype=float)
        dni_in = (
            np.asarray(dni_w_m2, dtype=float) if dni_w_m2 is not None else None
        )
        tz = detect_timezone_offset(timestamps[0].date())
        elevation, azimuth = solar_position(timestamps, latitude, longitude, tz)
        doy = timestamps[0].timetuple().tm_yday
        g = self.window_g_value
        a_win = self.window_area_m2
        az_e = self.window_azimuth_deg

        for i in range(n):
            elev = float(elevation[i])
            if elev <= 0.0:
                continue
            cos_inc = math.cos(math.radians(elev)) * math.cos(
                math.radians(float(azimuth[i]) - az_e)
            )
            if cos_inc <= 0.0:
                continue
            if dni_in is not None and i < len(dni_in) and dni_in[i] > 0:
                dni = float(dni_in[i])
            else:
                cos_zenith = math.sin(math.radians(elev))
                dni, _ = _disc_decomposition(float(ghi[i]), cos_zenith, doy)
            gains[i] += g * a_win * dni * cos_inc
        return gains

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
            # Wandtemperatur T_W (3-Speicher-Modell). Generoes bebounded —
            # die Wand kann bis nahe Aussenluft auskuehlen.
            "t_wand": make_var_array(
                "t_wand", num_steps,
                low=self.design_temp - 10.0,
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
            # Freie Lueftung / Fensteroeffnen [kW]: laesst den Raum ueber-
            # schuessige Waerme kostenfrei abgeben. Noetig, wenn ein starker
            # Solargewinn (Q_g,R kann an grossen Suedfenstern zweistellige
            # kW erreichen) die Verluste deutlich uebersteigt — sonst wuerde
            # T_innen ueber jede Schranke steigen und das Modell infeasible.
            # Physikalisch: Bewohner oeffnet die Fenster, wenn es zu warm
            # wird. Unbestraft (Lueften kostet nichts); der Solver lueftet
            # daher nur den Ueberschuss oberhalb des Komfortbands weg.
            "room_heat_dump": make_var_array(
                "room_heat_dump", num_steps, low=0.0,
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

        # ------------------------------------------------------------------
        # Wand-Energiebilanz (Speicher 4), explizites Euler fuer die traege
        # Wandmasse; der Raum->Wand-Fluss nutzt T_R[t] (gleicher Ausdruck
        # wie in heat_demand -> energetisch konserviert).
        #   C_W·(T_W[t]−T_W_prev)/dt = G_RW·(T_R[t]−T_W_prev)
        #                              − G_WA·(T_W_prev−T_A[t])
        # ------------------------------------------------------------------
        t_wand = variables.get("t_wand")
        if t_wand is not None and self._t_aus is not None:
            c_w = self.wall_capacity_kwh_per_k             # [kWh/K]
            g_rw_kw = self.wall_conductance_rw_w_per_k / 1000.0   # [kW/K]
            g_wa_kw = self.wall_conductance_wa_w_per_k / 1000.0   # [kW/K]
            dt_h = step_hours(step_minutes)
            if c_w > 0:
                for t in range(len(t_wand)):
                    tw_prev = (
                        self.initial_wall_temp_c if t == 0 else t_wand[t - 1]
                    )
                    t_aus_t = float(self._t_aus[t])
                    model += (
                        c_w * (t_wand[t] - tw_prev) / dt_h
                        == g_rw_kw * (t_innen[t] - tw_prev)
                        - g_wa_kw * (tw_prev - t_aus_t),
                        f"t_wand_balance_{t}",
                    )

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

    def _room_gain_w_at(self, t: int) -> float:
        """Q_g,R [W] im Schritt t (aus prepare; Fallback: interner Anteil)."""
        if self._q_g_r_w is not None and t < len(self._q_g_r_w):
            return float(self._q_g_r_w[t])
        return float(self.internal_gain_w_const)

    def heat_demand(self, variables: dict, t: int, sink: str) -> Any:
        """Demand-Seite der Raum-Energiebilanz fuer Phase E.

        3-Speicher-Modell (Wandknoten vorhanden): Raum implizit gefuehrt,
            C_R·(T_R[t]−T_R_prev)/dt + G_RW·(T_R[t]−T_W_prev)
                + UA_direkt·(T_R[t]−T_A[t]) − Q_g,R
        zusammen mit ``heat_supply("room") = q_floor_to_room[t]`` (aus UFH).

        Fallback (kein Wandknoten): altes 1-Knoten-Modell mit
        Huellkapazitaet und pauschalem UA-Verlust (explizit).
        """
        if sink != "room" or self._t_aus is None:
            return 0.0

        t_innen = variables["t_innen"]
        t_wand = variables.get("t_wand")
        dt_h = step_hours(self._step_minutes_cached)
        t_in_prev = self.indoor_temp if t == 0 else t_innen[t - 1]
        t_aus_t = float(self._t_aus[t])

        if t_wand is None:
            # Fallback: pauschaler UA-Verlust, Huellkapazitaet, explizit.
            c_room = self.shell_capacity_kwh_per_k
            ua_kw_per_k = self.ua_w_per_k / 1000.0
            return (
                c_room * (t_innen[t] - t_in_prev) / dt_h
                + ua_kw_per_k * (t_in_prev - t_aus_t)
            )

        # 3-Speicher-Modell: Raum implizit (Verluste auf T_R[t]),
        # Wand explizit (T_W_prev).
        c_room = self.room_capacity_kwh_per_k                 # nur Luft [kWh/K]
        g_rw_kw = self.wall_conductance_rw_w_per_k / 1000.0   # [kW/K]
        ua_direct_kw = self.ua_direct_w_per_k / 1000.0        # [kW/K]
        q_g_r_kw = self._room_gain_w_at(t) / 1000.0           # [kW]
        tw_prev = self.initial_wall_temp_c if t == 0 else t_wand[t - 1]
        # Freie Lueftung gibt ueberschuessige Waerme ab (room_heat_dump >= 0).
        dump = variables.get("room_heat_dump")
        dump_t = dump[t] if dump is not None else 0.0
        return (
            c_room * (t_innen[t] - t_in_prev) / dt_h
            + g_rw_kw * (t_innen[t] - tw_prev)
            + ua_direct_kw * (t_innen[t] - t_aus_t)
            - q_g_r_kw
            + dump_t
        )

    # add_constraints wird vom Optimizer aufgerufen — wir nutzen den
    # Aufruf, um step_minutes zwischenzuspeichern (heat_demand braucht es).
    _step_minutes_cached: int = 15

    def extract_result(
        self, result: Any, variables: dict, num_steps: int, dt_h: float,
    ) -> None:
        """Innen-/Wandtemperatur und Verlustleistung in das Ergebnis schreiben."""
        t_innen_vals = np.array(
            [v.varValue or 0.0 for v in variables["t_innen"]]
        )
        result.indoor_temp_c = t_innen_vals

        t_wand_var = variables.get("t_wand")
        t_aus = self._t_aus[:num_steps] if self._t_aus is not None else None

        if t_wand_var is not None:
            t_wand_vals = np.array([v.varValue or 0.0 for v in t_wand_var])
            result.wall_temp_c = t_wand_vals
            if t_aus is not None:
                # Gesamter Verlust an die Aussenluft = direkter Pfad
                # (Fenster+Dach+Lueftung, auf T_R[t]) + Wandpfad (Wand ->
                # Aussen, auf T_W[t-1] konsistent zur Wandbilanz).
                tw_prev = np.concatenate(
                    ([self.initial_wall_temp_c], t_wand_vals[:-1])
                )
                ua_direct_kw = self.ua_direct_w_per_k / 1000.0
                g_wa_kw = self.wall_conductance_wa_w_per_k / 1000.0
                result.heat_loss_kw = (
                    ua_direct_kw * (t_innen_vals - t_aus)
                    + g_wa_kw * (tw_prev - t_aus)
                )
        elif t_aus is not None:
            # Fallback (kein Wandknoten): pauschaler UA-Verlust, prev-Wert
            # konsistent zum 1-Knoten-Modell.
            prev = np.concatenate(([self.indoor_temp], t_innen_vals[:-1]))
            ua_kw_per_k = self.ua_w_per_k / 1000.0
            result.heat_loss_kw = ua_kw_per_k * (prev - t_aus)

        # Q_g,R (solar + intern) als Diagnose-Fahrplan [kW].
        if self._q_g_r_w is not None:
            result.room_gain_kw = self._q_g_r_w[:num_steps] / 1000.0

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
