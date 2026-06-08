"""Szenario-Builder fuer EMOS Light.

Erstellt Komponenten und Eingabedaten aus der Konfiguration.
"""

import datetime

import numpy as np

from emos_light.components.pv import PVSystem
from emos_light.components.battery import Battery
from emos_light.components.heat_pump import HeatPump
from emos_light.components.building import Building
from emos_light.components.thermal_storage import ThermalStorage
from emos_light.components.fresh_water_station import FreshWaterStation
from emos_light.components.underfloor_heating import UnderfloorHeating
from emos_light.components.wallbox import Wallbox
from emos_light.components.electric_vehicle import ElectricVehicle
from emos_light.core.types import TimeSeriesInput
from emos_light.data.prices import (
    fetch_day_ahead_prices,
    generate_synthetic_prices,
    calculate_consumer_price,
    is_day_ahead_published,
)
from emos_light.data.weather import fetch_weather_forecast, generate_synthetic_weather
from emos_light.data.profiles import (
    generate_load_profile,
    generate_heat_demand_profile,
    generate_hot_water_profile,
    load_csv_profile,
    parse_csv_load_profile,
    forecast_load_profile,
    get_csv_info,
)
from emos_light.optimization.optimizer import EMOSLightOptimizer


def build_components(config: dict) -> dict:
    """Erstellt alle Komponenten aus der Konfiguration."""
    pv = (
        PVSystem("pv", config["pv"])
        if config["pv"].get("enabled") else None
    )
    battery = (
        Battery("battery", config["battery"])
        if config["battery"].get("enabled") else None
    )
    heat_pump = (
        HeatPump("heat_pump", config["heat_pump"])
        if config["heat_pump"].get("enabled") else None
    )
    hot_water_storage = (
        ThermalStorage("hot_water_storage", config["hot_water_storage"], prefix="ww")
        if config["hot_water_storage"].get("enabled") else None
    )
    fresh_water_station = (
        FreshWaterStation("fws", config["fresh_water_station"])
        if config["fresh_water_station"].get("enabled") else None
    )
    # Building vor UFH erstellen, damit shell_capacity an UFH weitergereicht werden kann
    building = (
        Building("building", config.get("building", {}))
        if config.get("building", {}).get("enabled") else None
    )
    if config["underfloor_heating"].get("enabled"):
        ufh_config = dict(config["underfloor_heating"])
        # Modell EMOS Light (Mai 2026): nur Estrich als Waermespeicher;
        # Wand/Luft werden bewusst vernachlaessigt (vgl. Building-Doku).
        # additional_capacity_kwh_per_k bleibt damit auf Default 0.
        # Initialwert T_innen vom Building durchreichen, damit UFH bei t=0
        # q_floor_to_room aus konsistenten Anfangsbedingungen rechnet.
        if building is not None and "initial_indoor_temp_c" not in ufh_config:
            ufh_config["initial_indoor_temp_c"] = building.indoor_temp
        underfloor_heating = UnderfloorHeating("ufh", ufh_config)
    else:
        underfloor_heating = None
    wallboxes = [
        Wallbox(wb.get("name", f"wb_{i}"), wb)
        for i, wb in enumerate(config.get("wallboxes", []))
        if wb.get("enabled")
    ]
    electric_vehicles = [
        ElectricVehicle(ev.get("name", f"ev_{i}"), ev)
        for i, ev in enumerate(config.get("electric_vehicles", []))
        if ev.get("enabled")
    ]

    return {
        "pv": pv,
        "battery": battery,
        "heat_pump": heat_pump,
        "hot_water_storage": hot_water_storage,
        "fresh_water_station": fresh_water_station,
        "underfloor_heating": underfloor_heating,
        "building": building,
        "wallboxes": wallboxes,
        "electric_vehicles": electric_vehicles,
    }


def build_optimizer(components: dict) -> EMOSLightOptimizer:
    """Erstellt den Optimizer aus den Komponenten."""
    return EMOSLightOptimizer(**components)


def load_input_data(
    config: dict,
    date: datetime.date,
    use_api: bool = False,
    csv_load_profile: object = None,
    csv_includes_hp: bool = False,
) -> dict:
    """Laedt alle Eingabedaten (Preise, Wetter, Profile)."""
    general = config.get("general", {})
    step_minutes = general.get("time_step_minutes", 15)
    configured_horizon_hours = general.get("optimization_horizon_hours", 48)
    lat = general.get("latitude", 49.33)
    lon = general.get("longitude", 12.11)
    # Anzahl Tage, die der Horizont (inkl. Startttag) abdeckt — wird
    # benoetigt, damit die API-Fetcher den vollen Day-Ahead-Bereich
    # holen (sonst wuerde der zweite Tag mit dem letzten Wert gepaddet).
    num_days = max(1, int(np.ceil(configured_horizon_hours / 24.0)))

    # Dynamische Anpassung an die Day-Ahead-Verfuegbarkeit:
    # Wenn echte Daten genutzt werden und der konfigurierte Horizont
    # ueber Tag 1 hinaus reicht, probieren wir, ob die Day-Ahead-Preise
    # fuer den letzten benoetigten Tag schon publiziert sind. Falls
    # nicht (typisch vor 13 Uhr Ortszeit, wenn die EPEX-SPOT-Auktion
    # fuer morgen noch laeuft), schrumpfen wir num_days/horizon_hours
    # auf den tatsaechlich verfuegbaren Bereich. So wird nie ueber einen
    # Zeitraum optimiert, fuer den keine echten Marktpreise vorliegen.
    horizon_shrunk = False
    if use_api and num_days > 1:
        last_day = date + datetime.timedelta(days=num_days - 1)
        while num_days > 1 and not is_day_ahead_published(last_day):
            num_days -= 1
            last_day = date + datetime.timedelta(days=num_days - 1)
            horizon_shrunk = True

    horizon_hours = min(configured_horizon_hours, num_days * 24)
    num_steps = int(horizon_hours * 60 / step_minutes)

    # Preise
    if use_api:
        try:
            prices_df = fetch_day_ahead_prices(date, num_days=num_days)
        except Exception:
            prices_df = generate_synthetic_prices(
                date, num_steps=num_steps, step_minutes=step_minutes,
            )
    else:
        prices_df = generate_synthetic_prices(
            date, num_steps=num_steps, step_minutes=step_minutes,
        )

    # Wetter
    if use_api:
        try:
            weather_df = fetch_weather_forecast(lat, lon, date, num_steps, step_minutes)
        except Exception:
            weather_df = generate_synthetic_weather(
                date, num_steps=num_steps, step_minutes=step_minutes,
            )
    else:
        weather_df = generate_synthetic_weather(
            date, num_steps=num_steps, step_minutes=step_minutes,
        )

    # Preise auf step_minutes resamplen (Day-Ahead-API liefert stuendlich;
    # die internen Schritte sind 15-min) — block-konstant per ffill.
    if (
        "timestamp" in prices_df.columns
        and len(prices_df) > 0
        and len(prices_df) < num_steps
    ):
        prices_df = (
            prices_df.set_index("timestamp")
            .resample(f"{step_minutes}min")
            .ffill()
            .reset_index()
        )

    spot_prices = _pad_array(prices_df["price_ct_kwh"].values, num_steps)
    tariff = config.get("tariff", {})
    prices = calculate_consumer_price(spot_prices, tariff)
    temp = _pad_array(weather_df["temperature_c"].values, num_steps)
    ghi = _pad_array(weather_df["ghi_w_m2"].values, num_steps)
    dni = _pad_array(
        weather_df["dni_w_m2"].values if "dni_w_m2" in weather_df.columns
        else np.zeros(num_steps), num_steps
    )
    dhi = _pad_array(
        weather_df["dhi_w_m2"].values if "dhi_w_m2" in weather_df.columns
        else np.zeros(num_steps), num_steps
    )
    wind_speed = _pad_array(
        weather_df["wind_speed_m_s"].values if "wind_speed_m_s" in weather_df.columns
        else np.zeros(num_steps), num_steps
    )

    timestamps = [
        datetime.datetime.combine(date, datetime.time())
        + datetime.timedelta(minutes=i * step_minutes)
        for i in range(num_steps)
    ]

    # PV-Erzeugung
    pv_config = config.get("pv", {})
    surfaces = pv_config.get("surfaces", [])
    if pv_config.get("enabled") and surfaces:
        pv_generation = np.zeros(num_steps)
        for surf in surfaces:
            surf_config = {
                "enabled": True,
                "peak_power_kwp": surf.get("kwp", 5.0),
                "azimuth_deg": surf.get("azimuth_deg", 180),
                "tilt_deg": surf.get("tilt_deg", 30),
                "system_efficiency": pv_config.get("system_efficiency", pv_config.get("efficiency", 0.85)),
                "age_years": pv_config.get("age_years", 0),
                "degradation_pct_per_year": pv_config.get("degradation_pct_per_year", 0.5),
                "transposition_model": pv_config.get("transposition_model", "perez"),
                # Datenbasierte Kalibrierung + AC-Limit pro Surface aus
                # dem PV-Block durchreichen, damit das Multi-Surface-
                # Layout dieselben Korrekturen wie eine Einzel-Anlage
                # bekommt. AC-Limit wird hier proportional aufgeteilt.
                "k_calibration": pv_config.get("k_calibration", 1.0),
                "ac_limit_kw": _split_ac_limit(
                    pv_config.get("ac_limit_kw"),
                    surf.get("kwp", 5.0),
                    sum(s.get("kwp", 0.0) for s in surfaces) or 1.0,
                ),
            }
            pv_surf = PVSystem(surf.get("name", "pv"), surf_config)
            pv_generation += pv_surf.estimate_generation(
                ghi, timestamps=timestamps, latitude=lat, longitude=lon,
                ambient_temp_c=temp, wind_speed_m_s=wind_speed,
                dni_series=dni, dhi_series=dhi,
            )
    elif pv_config.get("enabled"):
        pv_single = PVSystem("pv", pv_config)
        pv_generation = pv_single.estimate_generation(
            ghi, timestamps=timestamps, latitude=lat, longitude=lon,
            ambient_temp_c=temp, wind_speed_m_s=wind_speed,
            dni_series=dni, dhi_series=dhi,
        )
    else:
        pv_generation = np.zeros(num_steps)

    # Lastprofile
    if csv_load_profile is not None:
        hp_annual_kwh = 0.0
        if csv_includes_hp and config.get("heat_pump", {}).get("enabled"):
            # Mittlerer COP bei 7 C Aussentemperatur, Heizkreis-VL
            from emos_light.components.heat_pump import HeatPump
            _hp = HeatPump("est", config["heat_pump"])
            hp_cop_avg = float(_hp.calculate_cop_heating(np.array([7.0]))[0])
            hp_annual_kwh = (
                config["heat_demand"].get("annual_heating_kwh", 0)
                + config["heat_demand"].get("annual_hot_water_kwh", 0)
            ) / hp_cop_avg

        household_load = load_csv_profile(
            csv_data=csv_load_profile,
            target_date=date,
            num_steps=num_steps,
            includes_heat_pump=csv_includes_hp,
            hp_annual_kwh=hp_annual_kwh,
            outside_temp=temp,
        )
    else:
        household_cfg = config.get("household", {})
        annual_kwh = household_cfg.get("annual_consumption_kwh", 4500)
        profile_id = household_cfg.get("load_profile_id", "")

        if profile_id:
            # Vermessenes Profil + lineare Skalierung auf den gewuenschten
            # Jahresverbrauch (Profile sind ohne Waermepumpenanteil).
            from emos_light.data.household_profiles import (
                load_household_profile, HOUSEHOLD_PROFILES,
            )
            if profile_id in HOUSEHOLD_PROFILES:
                household_load = load_household_profile(
                    profile_id=profile_id,
                    target_date=date,
                    num_steps=num_steps,
                    target_annual_kwh=annual_kwh,
                )
            else:
                household_load = generate_load_profile(annual_kwh, date, num_steps)
        else:
            household_load = generate_load_profile(annual_kwh, date, num_steps)

    heating_demand = generate_heat_demand_profile(
        config["heat_demand"]["annual_heating_kwh"], date, num_steps, temp
    )
    hw_demand = generate_hot_water_profile(
        config["heat_demand"]["annual_hot_water_kwh"], date, num_steps
    )

    return {
        "prices": prices,
        "spot_prices": spot_prices,
        "temp": temp,
        "ghi": ghi,
        "dni": dni,
        "wind_speed": wind_speed,
        "pv_generation": pv_generation,
        "household_load": household_load,
        "heating_demand": heating_demand,
        "hw_demand": hw_demand,
        "timestamps": timestamps,
        "num_steps": num_steps,
        "step_minutes": step_minutes,
        "lat": lat,
        "lon": lon,
        # Effektiver Horizont (nach evtl. Day-Ahead-Shrink), damit das
        # Dashboard und nachgelagerte Routinen die tatsaechliche
        # Fensterlaenge kennen — nicht den konfigurierten Wunsch.
        "horizon_hours": horizon_hours,
        "configured_horizon_hours": configured_horizon_hours,
        "horizon_shrunk": horizon_shrunk,
    }


def build_time_series_input(config: dict, data: dict) -> TimeSeriesInput:
    """Erstellt TimeSeriesInput aus Config und geladenen Daten."""
    general = config.get("general", {})

    # Q_g,R (solare + interne Raumgewinne, Gebaeudegruppe Juni 2026)
    # vorberechnen, solange das Gebaeudemodell aktiv ist. Die Berechnung
    # liegt im Building (kennt Fensterflaeche/g-Wert/Azimut); hier wird sie
    # nur mit den Wetterdaten (Sonnenstand via lat/lon/timestamps, DNI/GHI)
    # gefuettert und als Zeitreihe durchgereicht.
    room_gain_w = np.array([])
    bcfg = config.get("building", {})
    if bcfg.get("enabled", False):
        _gain_building = Building("gain_calc", bcfg)
        room_gain_w = _gain_building.compute_room_gain_w(
            data["timestamps"], data.get("ghi"), data.get("dni"),
            data.get("lat"), data.get("lon"),
        )

    return TimeSeriesInput(
        prices_ct_kwh=data["prices"],
        pv_generation_kw=data["pv_generation"],
        household_load_kw=data["household_load"],
        heating_demand_kw=data["heating_demand"],
        hot_water_demand_kw=data["hw_demand"],
        outside_temp_c=data["temp"],
        timestamps=data["timestamps"],
        step_minutes=data["step_minutes"],
        feed_in_tariff_ct_kwh=general.get("feed_in_tariff_ct_kwh", 8.2),
        max_grid_power_kw=general.get("max_grid_power_kw", 30.0),
        par14a_enabled=config.get("par14a", {}).get("enabled", False),
        par14a_curtailment_kw=config.get("par14a", {}).get("curtailment_kw", 4.2),
        par14a_curtailed_steps=_par14a_curtailed_steps(config, data["timestamps"]),
        room_gain_w=room_gain_w,
    )


def _par14a_curtailed_steps(config: dict, timestamps: list) -> list[int]:
    """Step-Indizes, in denen der Netzbetreiber nach §14a EnWG drosselt.

    Das Drosselfenster ist ueber die Stunden [start, end) definiert
    (lokale Uhrzeit, taeglich wiederkehrend ueber den Horizont).
    ``start == end`` => kein Fenster; ``start > end`` laeuft ueber
    Mitternacht (z.B. 22 -> 6). Liefert eine leere Liste, wenn §14a
    deaktiviert ist — dann greift der Drossel-Constraint im Optimizer
    gar nicht.
    """
    par14a = config.get("par14a", {})
    if not par14a.get("enabled", False):
        return []
    start_h = float(par14a.get("curtail_start_hour", 17))
    end_h = float(par14a.get("curtail_end_hour", 20))
    if start_h == end_h:
        return []
    steps: list[int] = []
    for i, ts in enumerate(timestamps):
        h = ts.hour + ts.minute / 60.0
        if start_h < end_h:
            in_window = start_h <= h < end_h
        else:  # Fenster ueber Mitternacht
            in_window = h >= start_h or h < end_h
        if in_window:
            steps.append(i)
    return steps


def _pad_array(arr: np.ndarray, target_len: int) -> np.ndarray:
    """Passt Array-Laenge an."""
    arr = arr[:target_len]
    if len(arr) < target_len:
        arr = np.pad(arr, (0, target_len - len(arr)), mode="edge")
    return arr


def _split_ac_limit(
    total_ac_limit_kw: float | None,
    surface_kwp: float,
    total_kwp: float,
) -> float | None:
    """Verteilt ein globales AC-Limit anteilig auf eine Surface.

    Beispiel: 12 kWp Anlage (8 kWp Sued + 4 kWp Ost) mit 10 kW
    Wechselrichter-Limit -> Sued bekommt 6.67 kW, Ost 3.33 kW.
    Vereinfachung: das echte AC-Clipping ist ueber die Summe nicht
    perfekt durch lineare Aufteilung abbildbar, fuer die Optimierung
    aber ausreichend nah.
    """
    if total_ac_limit_kw in (None, 0, 0.0):
        return None
    if total_kwp <= 0:
        return None
    return float(total_ac_limit_kw) * float(surface_kwp) / float(total_kwp)
