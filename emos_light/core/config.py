"""Konfigurationsmanagement fuer EMOS Light (Neubau)."""

import copy
from pathlib import Path
from typing import Any

import yaml


# Standard-Konfiguration fuer Neubau
DEFAULT_CONFIG = {
    "general": {
        "time_step_minutes": 15,
        # 48 h, damit der Day-Ahead-MPC nach 13 Uhr Ortszeit den
        # Horizont bis Tagesende morgen wirklich nutzen kann
        # (EPEX-Day-Ahead-Publikation, siehe MPCController._horizon_end_step).
        "optimization_horizon_hours": 48,
        "latitude": 49.33,
        "longitude": 12.11,
        "feed_in_tariff_ct_kwh": 8.2,
        "max_grid_power_kw": 30.0,
    },
    "tariff": {
        "provider_markup_ct_kwh": 2.15,
        "grid_fee_ct_kwh": 9.26,
        "concession_fee_ct_kwh": 1.66,
        "electricity_tax_ct_kwh": 2.05,
        "kwkg_surcharge_ct_kwh": 0.446,
        "stromnev_surcharge_ct_kwh": 1.559,
        "offshore_surcharge_ct_kwh": 0.941,
        "vat_pct": 19.0,
        "monthly_base_fee_eur": 5.99,
        "monthly_grid_fee_eur": 10.0,
    },
    "par14a": {
        "enabled": False,
        "curtailment_kw": 4.2,
        "num_devices": 1,
    },
    "household": {
        "annual_consumption_kwh": 4500,
        # Vermessenes Lastprofil (siehe emos_light/data/household_profiles.py).
        # Leerer String -> synthetisches Profil als Fallback.
        "load_profile_id": "2person_2kinder",
    },
    "pv": {
        "enabled": True,
        "peak_power_kwp": 12.0,
        "azimuth_deg": 180,
        "tilt_deg": 30,
        # System-Effizienz (Wechselrichter, Kabel, Verschmutzung, Mismatch)
        # — typischerweise 80-90 %. NICHT zu verwechseln mit dem Modul-
        # Wirkungsgrad (typ. 18-22 %), der bereits in peak_power_kwp steckt.
        "efficiency": 0.85,
        "degradation_pct_per_year": 0.5,
        "age_years": 0,
        "surfaces": [],
        # Transpositionsmodell GHI -> POA. "perez" (1990) ist das
        # produktiv gesetzte Modell — Sieger im internen Vergleich
        # gegen Liu&Jordan, EMOS_iso und HTW PVprog (siehe
        # "PV Prognose Tool angepasst/FORECASTS.md"). UI bietet keinen
        # Wechsel mehr; "isotropic" kann per YAML noch erzwungen werden,
        # wenn jemand eine Vergleichsrechnung machen will.
        "transposition_model": "perez",
        # Datenbasierte Kalibrierung (Mai 2026, Standalone-Tool
        # "PV Prognose Tool angepasst/"). 1.0 = unkalibriert.
        # Bei realen Anlagendaten ueblicherweise 0.7..1.0.
        "k_calibration": 1.0,
        # AC-Wechselrichter-Limit (kW). None = kein Clipping.
        "ac_limit_kw": None,
    },
    "battery": {
        "enabled": True,
        "capacity_kwh": 10.0,
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "charge_efficiency": 0.95,
        "discharge_efficiency": 0.95,
        "min_soc": 0.10,
        "max_soc": 0.90,
        "initial_soc": 0.50,
        # Alterungskosten (PDF Speichergruppe) — LFP-Defaults
        "aging_cost_enabled": True,
        "replacement_cost_eur_per_kwh": 500.0,
        "residual_value_pct": 0.0,
        "equivalent_full_cycles": 6000,
    },
    "heat_pump": {
        "enabled": True,
        "model": "Vaillant aroTHERM plus VWL 105/8.1 A",
        "max_electrical_power_kw": 8.0,
        "min_electrical_power_kw": 1.0,
        "flow_temp_heating_c": 35.0,
        "flow_temp_dhw_c": 55.0,
        "operating_min_temp_c": -25.0,
        "operating_max_temp_c": 43.0,
        # Mindestlaufzeit der WP in Minuten nach jedem Einschalten.
        # Die WP soll mindestens 60 min am Stueck laufen — Hinweis vom
        # Prof (Mai 2026): kuerzere Phasen sind technisch ungeschickt
        # (Einschwingzeit Verdichter + Verdampfer, Effizienzeinbussen,
        # Verdichter-Verschleiss). Innerhalb dieser Laufphase darf der
        # Solver allerdings ueber ``hp_mode_ww[t]`` zwischen FBH und WW
        # umschalten — die Restriktion bezieht sich auf hp_on, nicht
        # auf den Modus.
        "min_run_time_minutes": 60,
        "min_pause_time_minutes": 15,
        # Maximale Anzahl Einschaltvorgaenge (OFF -> ON) pro Kalendertag.
        # Schont den Verdichter — laeuft die WP einmal, darf sie beliebig
        # lang laufen und auch zwischen Heizen/WW umschalten, nur das
        # OFF -> ON-Anschalten zaehlt. Default 8/Tag.
        "max_starts_per_day": 8,
        "sg_ready": True,
        # Sollwert-Ueberhoehung im SG-Ready-Zustand 3 (Einschaltempfehlung).
        # Laut BWP v1.1: einmalige Speicherladung WW + Sollwert-Ueberhoehung.
        # Estrich (Pufferspeicher) bekommt bei sg3 KEINEN Boost — PDF:
        # "Wenn keine Waermeanforderung vorliegt und Schaltzustand 3 anliegt,
        # findet keine Speicherladung im Heizbetrieb statt."
        "sg_ready_temp_raise_state3_c": 5.0,
        # Sollwert-Ueberhoehung im SG-Ready-Zustand 4 (Zwangseinschaltung).
        # PDF: WW erst, danach Pufferspeicher mit erhoehter Temperatur
        # (Sollwert + variabler Offset 0..20 K). Muss > state3-Wert sein.
        "sg_ready_temp_raise_state4_c": 10.0,
        # Mindesthaltezeit fuer jeden SG-Ready-Zustand. Verhindert kurze
        # Schaltspiele und entspricht typischen BWP-Mindesthaltzeiten.
        "sg_ready_min_hold_minutes": 10,
    },
    "hot_water_storage": {
        "enabled": True,
        "volume_liters": 300,
        "min_temperature_c": 40.0,
        "max_temperature_c": 60.0,
        "comfort_temperature_c": 55.0,
        "comfort_periods": [
            {"start_hour": 5, "end_hour": 9},
            {"start_hour": 17, "end_hour": 22},
        ],
        "initial_temperature_c": 55.0,
        "ambient_temperature_c": 20.0,
        "height_diameter_ratio": 2.5,
        "insulation_thickness_m": 0.05,
        "insulation_conductivity_w_m_k": 0.035,
    },
    "fresh_water_station": {
        "enabled": True,
        "target_hot_water_temp_c": 50.0,
        "cold_water_inlet_temp_c": 10.0,
        "heat_exchanger_efficiency": 0.90,
        "min_storage_temp_for_dhw_c": 55.0,
    },
    "underfloor_heating": {
        "enabled": True,
        "heated_area_m2": 150.0,
        "screed_thickness_m": 0.065,
        "screed_density_kg_m3": 2000.0,
        "screed_specific_heat_j_kg_k": 1000.0,
        "floor_surface_coefficient_w_m2_k": 10.0,
        "supply_temp_max_c": 35.0,
        "floor_temp_min_c": 20.0,
        "floor_temp_max_c": 26.0,
        "initial_floor_temp_c": 22.0,
    },
    "building": {
        "enabled": True,
        "heated_area_m2": 150,
        "specific_heat_demand_kwh_m2a": 35,
        "annual_heating_kwh": 5250,
        "annual_hot_water_kwh": 2500,
        "heating_limit_temp_c": 16.0,
        "design_temp_c": -14.0,
        "indoor_temp_c": 21.0,
        "num_occupants": 4,
        "night_setback_c": 0.0,
        "night_start_hour": 22,
        "night_end_hour": 6,
        "building_type": "kfw55",
        # Gebaeudespeicher (Wand+Luft) — DIN EN ISO 13786 mittelschwere Bauweise
        "wall_capacity_wh_per_m2_k": 50.0,
        "volume_factor": 3.1,
        "heat_loss_coefficient_w_per_k": None,
        # ------------------------------------------------------------------
        # Direkte Geometrie + U-Werte (Gebaeudegruppe, EMOS-Light Mai 2026)
        # Wenn gesetzt, werden diese Werte benutzt — sonst fallback auf
        # die Heuristik aus Heizlast / heated_area.
        # ------------------------------------------------------------------
        "length_m": 15.0,                  # l
        "width_m": 10.0,                   # b
        "height_m": 2.5,                   # h (Standardgeschoss)
        "window_area_m2": None,            # A_F — None = ~15% Wandflaeche
        "u_value_wall_w_m2_k": 0.2,        # Aussenwand
        "u_value_window_w_m2_k": 0.9,      # Fenster
        "u_value_roof_floor_w_m2_k": 0.4,  # Dach + Bodenplatte (kombiniert)
        "ventilation_loss_w_m3_k": 0.17,   # spezifischer Lueftungsverlust
        "screed_thickness_m": 0.06,        # d_Estrich
        "screed_density_kg_m3": 2000.0,    # ϱ_Estrich
        "screed_specific_heat_j_kg_k": 1070.0,  # c_Estrich
        "reference_temp_c": 22.0,          # T_ref fuer Q_Gebaeude
        "comfort_min_temp_c": 21.0,        # T_min fuer t_aus-Berechnung
    },
    "heat_demand": {
        "annual_heating_kwh": 5250,
        "annual_hot_water_kwh": 2500,
    },
    "wallboxes": [],
    "electric_vehicles": [],
}

PV_SURFACE_DEFAULT = {
    "name": "Dachflaeche 1",
    "kwp": 6.0,
    "azimuth_deg": 180,
    "tilt_deg": 30,
}

WALLBOX_DEFAULT = {
    "name": "Wallbox 1",
    "enabled": False,
    "max_power_kw": 11.0,
    "min_power_kw": 1.4,
    "phases": 3,
    "ev_battery_capacity_kwh": 60.0,
    "target_soc": 0.80,
    "current_soc": 0.30,
    "departure_hour": 7,
    "arrival_hour": 18,
    "charging_efficiency": 0.92,
    # SOC-Verlust pro Stunde Abwesenheit (Pendelverbrauch), in Prozent
    # der EV-Kapazitaet. Bei Default 5 %/h und 60 kWh ergibt das 3 kWh/h,
    # was einem moderaten Verbrauch von ~15 kWh/100km bei 60 km/h
    # entspricht — eine pragmatische Naeherung fuer den taeglichen
    # Pendeleinsatz.
    "driving_loss_pct_per_hour": 5.0,
}

EV_DEFAULT = {
    "name": "E-Auto 1",
    "enabled": False,
    "vehicle_class": "kompakt",
    "battery_capacity_kwh": 58.0,
    "current_soc": 0.30,
    "target_soc": 0.80,
    "min_soc": 0.10,
    "max_soc": 1.0,
    "arrival_hour": 17,
    "departure_hour": 7,
    "daily_distance_km": 40.0,
    "consumption_kwh_per_100km": 16.0,
    "min_range_km": 150.0,
    "onboard_charger_kw": 11.0,
    "v2h_capable": False,
    "v2h_min_soc": 0.30,
    "linked_wallbox": "Wallbox 1",
    # Garantierte Mindestreichweite (Constraint: erreiche bis Abfahrt
    # mindestens diese Reichweite). Setzt voraus, dass Auto und Wallbox
    # den aktuellen SOC kommunizieren. Default an.
    "min_range_enabled": True,
    # Wenn das EV/die Wallbox kein bidirektionales Laden (V2H) unterstuetzt,
    # kann stattdessen eine preisgesteuerte Ladestrategie genutzt werden:
    # nur in den guenstigsten X % der Tagesstunden (Day-Ahead) laden.
    # 100 % = keine Beschraenkung (Default = wie bisher).
    "charge_only_below_percentile_pct": 100.0,
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merged override-Werte in base-Dict (rekursiv)."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict:
    """Laedt Konfiguration aus YAML und fuellt fehlende Werte mit Defaults."""
    if path is None:
        return copy.deepcopy(DEFAULT_CONFIG)

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {path}")

    with open(path, "r", encoding="utf-8") as f:
        user_config = yaml.safe_load(f) or {}

    config = _deep_merge(DEFAULT_CONFIG, user_config)

    if "wallboxes" in user_config:
        config["wallboxes"] = [
            _deep_merge(WALLBOX_DEFAULT, wb) for wb in user_config["wallboxes"]
        ]

    return validate_config(config)


def validate_config(config: dict) -> dict:
    """Validiert die Konfiguration."""
    errors = []

    gen = config.get("general", {})
    if gen.get("time_step_minutes", 15) not in (5, 10, 15, 30, 60):
        errors.append("time_step_minutes muss 5, 10, 15, 30 oder 60 sein")

    batt = config.get("battery", {})
    if batt.get("enabled"):
        if batt.get("min_soc", 0) >= batt.get("max_soc", 1):
            errors.append("battery.min_soc muss kleiner als max_soc sein")
        if batt.get("capacity_kwh", 0) <= 0:
            errors.append("battery.capacity_kwh muss positiv sein")
        if batt.get("equivalent_full_cycles", 1) <= 0:
            errors.append("battery.equivalent_full_cycles muss positiv sein")
        if not 0.0 <= batt.get("residual_value_pct", 0.0) < 1.0:
            errors.append("battery.residual_value_pct muss in [0, 1) liegen")
        if batt.get("replacement_cost_eur_per_kwh", 1.0) < 0:
            errors.append("battery.replacement_cost_eur_per_kwh darf nicht negativ sein")

    hp = config.get("heat_pump", {})
    if hp.get("enabled"):
        if hp.get("max_electrical_power_kw", 0) <= 0:
            errors.append("heat_pump.max_electrical_power_kw muss positiv sein")

    fws = config.get("fresh_water_station", {})
    hws = config.get("hot_water_storage", {})
    if fws.get("enabled") and hws.get("enabled"):
        if fws.get("min_storage_temp_for_dhw_c", 55) > hws.get("max_temperature_c", 60):
            errors.append("fresh_water_station.min_storage_temp_for_dhw_c darf nicht "
                          "groesser als hot_water_storage.max_temperature_c sein")

    ufh = config.get("underfloor_heating", {})
    if ufh.get("enabled"):
        if ufh.get("floor_temp_min_c", 20) >= ufh.get("floor_temp_max_c", 26):
            errors.append("underfloor_heating: floor_temp_min_c muss < floor_temp_max_c sein")

    for wb in config.get("wallboxes", []):
        if wb.get("enabled"):
            if wb.get("current_soc", 0) >= wb.get("target_soc", 1):
                errors.append(
                    f"Wallbox '{wb.get('name')}': current_soc >= target_soc"
                )

    if errors:
        raise ValueError("Konfigurationsfehler:\n" + "\n".join(f"  - {e}" for e in errors))

    return config


def save_config(config: dict, path: str | Path) -> None:
    """Speichert Konfiguration als YAML."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
