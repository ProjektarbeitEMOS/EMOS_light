"""Gemeinsame Datentypen fuer EMOS Light."""

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class TimeSeriesInput:
    """Alle Eingabe-Zeitreihen fuer die Optimierung."""

    prices_ct_kwh: np.ndarray
    pv_generation_kw: np.ndarray
    household_load_kw: np.ndarray
    heating_demand_kw: np.ndarray
    hot_water_demand_kw: np.ndarray
    outside_temp_c: np.ndarray
    timestamps: list

    step_minutes: int = 15
    feed_in_tariff_ct_kwh: float = 8.2
    max_grid_power_kw: float = 30.0

    par14a_enabled: bool = False
    par14a_curtailment_kw: float = 4.2
    par14a_curtailed_steps: list = field(default_factory=list)


@dataclass
class OptimizationResult:
    """Ergebnis der Optimierung mit allen Fahrplaenen und KPIs."""

    success: bool
    total_cost_eur: float = 0.0
    solver_status: str = ""
    solve_time_s: float = 0.0

    # Elektrische Fahrplaene
    grid_buy_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    grid_sell_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    batt_charge_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    batt_discharge_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    batt_soc_kwh: np.ndarray = field(default_factory=lambda: np.array([]))
    hp_power_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    hp_on: np.ndarray = field(default_factory=lambda: np.array([]))
    # Maximale el. WP-Leistung pro Zeitschritt — dynamisch aus T_aussen
    # und Vorlauftemperatur ueber das Kennfeld berechnet. Wird als
    # Obergrenze fuer hp_power_kw vom Solver eingehalten und dient als
    # Hilfslinie im Dashboard-Plot (Mai 2026).
    hp_max_power_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    # WP-Modus pro Zeitschritt (Entweder-Oder zwischen FBH und WW —
    # Projektgruppe Leistungsaufteilung, Mai 2026):
    #   0 = FBH-Modus (W35-Vorlauf, hoher COP)
    #   1 = WW-Modus  (W55-Vorlauf, niedriger COP)
    # Wenn nur eine Senke aktiv ist (z.B. nur Heizung), bleibt das Feld leer.
    hp_mode_ww: np.ndarray = field(default_factory=lambda: np.array([]))
    wallbox_power_kw: dict = field(default_factory=dict)
    # EV-SOC-Trajektorie pro Wallbox in kWh. Wird vom MILP-Optimizer als
    # explizite Zustandsvariable gefuehrt (Verlust 5 %/h waehrend Abwesen-
    # heit beruecksichtigt) und im Dashboard direkt geplottet.
    ev_soc_kwh: dict = field(default_factory=dict)
    timestamps: list = field(default_factory=list)

    # Thermische Fahrplaene — Estrich (Fussbodenheizung)
    floor_temp_c: np.ndarray = field(default_factory=lambda: np.array([]))
    floor_energy_kwh: np.ndarray = field(default_factory=lambda: np.array([]))
    q_floor_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    # Waermestrom Estrich -> Raum (kW). Positiv wenn Boden waermer als Raum.
    q_floor_to_room_kw: np.ndarray = field(default_factory=lambda: np.array([]))

    # Thermische Fahrplaene — Raum (Innentemperatur, MILP-Zustandsvariable)
    indoor_temp_c: np.ndarray = field(default_factory=lambda: np.array([]))
    # Gesamter Waermeverlust des Raumes an die Aussenluft [kW]:
    # direkter Pfad (Fenster+Dach+Lueftung) + Wandpfad (ueber T_W).
    heat_loss_kw: np.ndarray = field(default_factory=lambda: np.array([]))
    # Wandtemperatur T_W (3-Speicher-Modell ETH, Juni 2026) [°C]
    wall_temp_c: np.ndarray = field(default_factory=lambda: np.array([]))

    # Thermische Fahrplaene — Warmwasserspeicher
    ww_storage_temp_c: np.ndarray = field(default_factory=lambda: np.array([]))
    ww_storage_energy_kwh: np.ndarray = field(default_factory=lambda: np.array([]))
    q_ww_kw: np.ndarray = field(default_factory=lambda: np.array([]))

    # SG-Ready Zustand BWP v1.1 (1=Lastabwurf, 2=Normal, 3=Verstaerkt)
    sg_ready_state: np.ndarray = field(default_factory=lambda: np.array([]))

    # Einschaltvorgaenge (OFF -> ON) der Waermepumpe. Nur das Anschalten
    # belastet den Verdichter — Umschalten zwischen FBH und WW zaehlt nicht.
    # ``hp_starts_per_day`` ist ein dict[date -> int], ``hp_starts_count`` die
    # Gesamtsumme ueber den Horizont.
    hp_starts_per_day: dict = field(default_factory=dict)
    hp_starts_count: int = 0

    # Kosten-Details
    grid_buy_cost_eur: float = 0.0
    feed_in_revenue_eur: float = 0.0
    battery_aging_cost_eur: float = 0.0
    battery_throughput_kwh: float = 0.0
    battery_equivalent_cycles: float = 0.0

    # KPIs
    eigenverbrauch_pct: float = 0.0
    autarkie_pct: float = 0.0
    pv_total_kwh: float = 0.0
    load_total_kwh: float = 0.0
    grid_buy_total_kwh: float = 0.0
    grid_sell_total_kwh: float = 0.0
    hp_total_kwh: float = 0.0

    # Vergleich mit Baseline
    baseline_cost_eur: Optional[float] = None
    savings_eur: Optional[float] = None
    savings_pct: Optional[float] = None

    # Roher MILP-Objective-Wert in EUR, INKLUSIVE aller fiktiven Slack-
    # Strafkosten und der Alterungskosten. Reine Solver-Steuerungsgroesse
    # — fuer Debugging und Modell-Diagnose. ``total_cost_eur`` ist davon
    # bewusst getrennt: dort stehen nur die echten Geldfluesse
    # (grid_buy_cost - feed_in_revenue), keine virtuellen Strafen.
    objective_value_eur: Optional[float] = None

    # Planungsfenster fuer die Dashboard-Visualisierung:
    # Pro MPC-Iteration (oder einmalig bei Day-Ahead/Baseline) drei Step-
    # Indizes — Anfang des Fensters, Ende des Ausfuehrungsteils, Ende des
    # gesamten Planungshorizonts. Damit kann das Dashboard zeigen, wie weit
    # die Optimierung in die Zukunft schaut und welcher Teil tatsaechlich
    # umgesetzt wird.
    #   start_step      : Index, ab dem die Iteration plant (umgesetzt)
    #   exec_end_step   : Index (exklusiv), bis zu dem umgesetzt wird
    #   horizon_end_step: Index (exklusiv), bis zu dem geplant wird
    planning_windows: list = field(default_factory=list)
