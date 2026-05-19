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
    """Holt Wetterdaten von der Open-Meteo API.

    Das End-Datum wird so gewaehlt, dass mindestens ``num_steps`` Schritte
    der Aufloesung ``step_minutes`` abgedeckt sind — Open-Meteo liefert
    ``start_date`` und ``end_date`` jeweils inklusive (ein Tag pro Datum).
    """
    total_hours = num_steps * step_minutes / 60.0
    days_needed = max(1, int(np.ceil(total_hours / 24.0)))
    end_date = date + datetime.timedelta(days=days_needed - 1)
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
    date: datetime.date, num_steps: int = 96, step_minutes: int = 15,
) -> pd.DataFrame:
    """Generiert synthetische Wetterdaten fuer Tests.

    Erstellt jahreszeitabhaengige Profile fuer Temperatur, Globalstrahlung,
    Bewoelkung und Windgeschwindigkeit. Funktioniert ueber beliebig viele
    Tage — das Tagesprofil wird modulo 24h wiederholt, jeder Tag bekommt
    sein eigenes deterministisches Rauschen.

    Args:
        date: Startdatum (wird als Seed-Basis verwendet).
        num_steps: Anzahl Zeitschritte insgesamt.
        step_minutes: Zeitschrittlaenge in Minuten (Default 15).

    Returns:
        DataFrame mit synthetischen Wetterdaten.
    """
    step_h = step_minutes / 60.0
    hours_abs = np.arange(num_steps) * step_h
    hours = hours_abs % 24                  # Tagesprofil
    day_idx = (hours_abs // 24).astype(int)  # 0,0,..0,1,1,..

    # Jahreszeitbestimmung — relativ zum jeweiligen Tag (date + day_idx).
    # Beim Tageswechsel kann sich der Monat aendern; wir nehmen die
    # Monatswerte aus dem Startdatum als gute Naeherung fuer 2-3-tagige
    # Horizonte (Day-Ahead-MPC).
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

    # --- Globalstrahlung (GHI) – Glockenkurve waehrend Tageslicht ---
    sunrise = 7 if is_winter else (5 if is_summer else 6)
    sunset = 17 if is_winter else (21 if is_summer else 19)
    day_center = (sunrise + sunset) / 2
    day_width = (sunset - sunrise) / 4

    max_ghi = 400 if is_winter else (900 if is_summer else 650)
    ghi = max_ghi * np.exp(-0.5 * ((hours - day_center) / day_width) ** 2)
    ghi = np.where((hours >= sunrise) & (hours <= sunset), ghi, 0)

    # --- Tagesweise Rausch- und Wolken-Streams (deterministisch) ---
    base_seed = int(date.strftime("%Y%m%d"))
    cloud_cover = np.zeros(num_steps)
    wind_speed = np.zeros(num_steps)
    temp_noise = np.zeros(num_steps)
    for d in np.unique(day_idx):
        mask = day_idx == d
        rng = np.random.default_rng(seed=base_seed + int(d))
        cloud_cover[mask] = rng.uniform(10, 60, mask.sum())
        wind_speed[mask] = rng.uniform(1, 8, mask.sum())
        temp_noise[mask] = rng.normal(0, 1, mask.sum())

    temperature = temperature + temp_noise
    ghi *= (1 - cloud_cover / 200)  # Bewoelkungsreduktion
    ghi = np.clip(ghi, 0, 1200)

    # Zeitstempel erzeugen
    timestamps = [
        datetime.datetime.combine(date, datetime.time())
        + datetime.timedelta(minutes=int(i * step_minutes))
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
