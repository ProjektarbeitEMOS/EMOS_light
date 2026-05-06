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
from emos_light.data.prices import fetch_day_ahead_prices, generate_synthetic_prices, calculate_consumer_price
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
    horizon_hours = general.get("optimization_horizon_hours", 24)
    num_steps = int(horizon_hours * 60 / step_minutes)
    lat = general.get("latitude", 49.33)
    lon = general.get("longitude", 12.11)

    # Preise
    if use_api:
        try:
            prices_df = fetch_day_ahead_prices(date)
        except Exception:
            prices_df = generate_synthetic_prices(date, num_steps)
    else:
        prices_df = generate_synthetic_prices(date, num_steps)

    # Wetter
    if use_api:
        try:
            weather_df = fetch_weather_forecast(lat, lon, date, num_steps, step_minutes)
        except Exception:
            weather_df = generate_synthetic_weather(date, num_steps)
    else:
        weather_df = generate_synthetic_weather(date, num_steps)

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
    }


def build_time_series_input(config: dict, data: dict) -> TimeSeriesInput:
    """Erstellt TimeSeriesInput aus Config und geladenen Daten."""
    general = config.get("general", {})
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
    )


def _pad_array(arr: np.ndarray, target_len: int) -> np.ndarray:
    """Passt Array-Laenge an."""
    arr = arr[:target_len]
    if len(arr) < target_len:
        arr = np.pad(arr, (0, target_len - len(arr)), mode="edge")
    return arr
