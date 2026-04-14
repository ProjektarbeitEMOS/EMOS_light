"""Wetter- und Strahlungsprognosen abrufen."""

import datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests


def fetch_weather_forecast(
    lat: float,
    lon: float,
    date: Optional[datetime.date] = None,
    num_steps: int = 96,
    step_minutes: int = 15,
) -> pd.DataFrame:
    """Ruft Wetterprognose von Open-Meteo ab (kostenlos, kein API-Key noetig).

    Die Daten werden auf die gewuenschte Zeitaufloesung interpoliert.

    Args:
        lat: Breitengrad.
        lon: Laengengrad.
        date: Startdatum (Standard: heute).
        num_steps: Anzahl gewuenschter Zeitschritte.
        step_minutes: Zeitschrittlaenge in Minuten.

    Returns:
        DataFrame mit Spalten ['timestamp', 'temperature_c', 'ghi_w_m2',
                               'cloud_cover_pct', 'wind_speed_m_s'].
    """
    if date is None:
        date = datetime.date.today()

    try:
        return _fetch_from_open_meteo(lat, lon, date, num_steps, step_minutes)
    except Exception:
        return generate_synthetic_weather(date, num_steps)


def _fetch_from_open_meteo(
    lat: float, lon: float, date: datetime.date,
    num_steps: int = 96, step_minutes: int = 15,
) -> pd.DataFrame:
    """Holt Wetterdaten von der Open-Meteo API."""
    end_date = date + datetime.timedelta(days=1)
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={date.isoformat()}&end_date={end_date.isoformat()}"
        f"&hourly=temperature_2m,shortwave_radiation,direct_normal_irradiance,"
        f"diffuse_radiation,cloud_cover,wind_speed_10m"
        f"&timezone=Europe/Berlin"
    )

    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    hourly = data["hourly"]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(hourly["time"]),
        "temperature_c": hourly["temperature_2m"],
        "ghi_w_m2": hourly["shortwave_radiation"],
        "dni_w_m2": hourly.get("direct_normal_irradiance", [0.0] * len(hourly["time"])),
        "dhi_w_m2": hourly.get("diffuse_radiation", [0.0] * len(hourly["time"])),
        "cloud_cover_pct": hourly["cloud_cover"],
        "wind_speed_m_s": hourly["wind_speed_10m"],
    })

    # Auf gewuenschte Zeitaufloesung interpolieren
    resample_freq = f"{step_minutes}min"
    df = df.set_index("timestamp")
    df = df.resample(resample_freq).interpolate(method="linear")
    df = df.reset_index()

    # Auf gewuenschte Schrittzahl begrenzen
    df = df.head(num_steps)
    return df


def generate_synthetic_weather(
    date: datetime.date, num_steps: int = 96
) -> pd.DataFrame:
    """Generiert synthetische Wetterdaten fuer Tests.

    Erstellt jahreszeitabhaengige Profile fuer Temperatur, Globalstrahlung,
    Bewoelkung und Windgeschwindigkeit.

    Args:
        date: Datum (wird als Seed fuer Reproduzierbarkeit verwendet).
        num_steps: Anzahl Zeitschritte (Standard: 96 = 15-min fuer 24h).

    Returns:
        DataFrame mit synthetischen Wetterdaten.
    """
    hours = np.linspace(0, 24, num_steps, endpoint=False)
    rng = np.random.default_rng(seed=int(date.strftime("%Y%m%d")))

    # Jahreszeitbestimmung
    month = date.month
    is_summer = month in (5, 6, 7, 8, 9)
    is_winter = month in (11, 12, 1, 2)

    # --- Temperaturprofil (Sinuskurve mit Tagesgang) ---
    if is_summer:
        temp_base, temp_amp = 18, 8
    elif is_winter:
        temp_base, temp_amp = 2, 5
    else:  # Uebergang
        temp_base, temp_amp = 10, 6

    temperature = temp_base + temp_amp * np.sin((hours - 6) * np.pi / 12)
    temperature += rng.normal(0, 1, num_steps)

    # --- Globalstrahlung (GHI) – Glockenkurve waehrend Tageslicht ---
    sunrise = 7 if is_winter else (5 if is_summer else 6)
    sunset = 17 if is_winter else (21 if is_summer else 19)
    day_center = (sunrise + sunset) / 2
    day_width = (sunset - sunrise) / 4

    max_ghi = 400 if is_winter else (900 if is_summer else 650)
    ghi = max_ghi * np.exp(-0.5 * ((hours - day_center) / day_width) ** 2)
    ghi = np.where((hours >= sunrise) & (hours <= sunset), ghi, 0)

    # Bewoelkungsreduktion
    cloud_cover = rng.uniform(10, 60, num_steps)
    ghi *= (1 - cloud_cover / 200)  # Teilweise Reduktion
    ghi = np.clip(ghi, 0, 1200)

    # --- Windgeschwindigkeit ---
    wind_speed = rng.uniform(1, 8, num_steps)

    # Zeitstempel erzeugen
    timestamps = [
        datetime.datetime.combine(date, datetime.time())
        + datetime.timedelta(minutes=int(i * 1440 / num_steps))
        for i in range(num_steps)
    ]

    return pd.DataFrame({
        "timestamp": timestamps,
        "temperature_c": np.round(temperature, 1),
        "ghi_w_m2": np.round(ghi, 1),
        "dni_w_m2": np.zeros(num_steps),
        "dhi_w_m2": np.zeros(num_steps),
        "cloud_cover_pct": np.round(cloud_cover, 1),
        "wind_speed_m_s": np.round(wind_speed, 1),
    })
