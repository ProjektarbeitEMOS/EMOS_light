"""Daten beschaffen: echte PV-Erzeugung (InfluxDB) + Wetterdaten (Open-Meteo).

Aggregiert beides auf stuendliche Aufloesung und speichert als CSV.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import requests
from influxdb_client import InfluxDBClient

from config import (
    ARCHIVE_END_DATE as END_DATE,
    ARCHIVE_START_DATE as START_DATE,
    INFLUX_BUCKET,
    INFLUX_ORG,
    INFLUX_URL,
    LATITUDE,
    LONGITUDE,
    require_influx_token,
)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def fetch_pv_real() -> pd.DataFrame:
    """Holt reale PV-Erzeugung aus InfluxDB, aggregiert auf Stundenmittel."""
    print(f"Fetching real PV data {START_DATE} .. {END_DATE} ...")
    client = InfluxDBClient(url=INFLUX_URL, token=require_influx_token(), org=INFLUX_ORG, timeout=120_000)
    qapi = client.query_api()

    q = f'''from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {START_DATE}T00:00:00Z, stop: {END_DATE + dt.timedelta(days=1)}T00:00:00Z)
      |> filter(fn: (r) => r._measurement == "Gesamterzeugung" and r._field == "value")
      |> aggregateWindow(every: 1h, fn: mean, createEmpty: true)'''
    rows = []
    for tbl in qapi.query(q):
        for rec in tbl.records:
            rows.append({"time": rec.get_time(), "p_real_w": rec.get_value()})
    client.close()

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    # aggregateWindow labelt am ENDE -> auf Fensterstart umlabeln (0..59 min)
    df.index = df.index - pd.Timedelta(hours=1)
    df["p_real_w"] = pd.to_numeric(df["p_real_w"], errors="coerce")
    print(f"  got {len(df)} hourly samples  (NaN: {df['p_real_w'].isna().sum()})")
    return df


def fetch_weather() -> pd.DataFrame:
    """Holt Wetterdaten aus Open-Meteo-Archiv (ERA5)."""
    print(f"Fetching weather {START_DATE} .. {END_DATE} ...")
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": str(START_DATE),
        "end_date": str(END_DATE),
        "hourly": ",".join([
            "shortwave_radiation",          # GHI [W/m2]
            "direct_normal_irradiance",     # DNI [W/m2]
            "diffuse_radiation",            # DHI [W/m2]
            "temperature_2m",               # [deg C]
            "wind_speed_10m",               # [km/h]
            "cloud_cover",                  # [%]
        ]),
        "timezone": "UTC",
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    df = pd.DataFrame({
        "time": pd.to_datetime(h["time"], utc=True),
        "ghi":  h["shortwave_radiation"],
        "dni":  h["direct_normal_irradiance"],
        "dhi":  h["diffuse_radiation"],
        "t_amb": h["temperature_2m"],
        "wind_kmh": h["wind_speed_10m"],
        "cloud_cover": h["cloud_cover"],
    })
    df = df.set_index("time").sort_index()
    df["wind_ms"] = df["wind_kmh"] / 3.6
    print(f"  got {len(df)} hourly samples")
    return df


if __name__ == "__main__":
    pv = fetch_pv_real()
    wx = fetch_weather()
    merged = pv.join(wx, how="outer").sort_index()
    out = DATA_DIR / "merged_hourly.csv"
    merged.to_csv(out)
    print(f"\nSaved -> {out}")
    print(f"Shape: {merged.shape}")
    print(f"Real PV coverage: {merged['p_real_w'].notna().sum()} / {len(merged)}")
    # schnelle Plausi: taegliche Energie
    daily = merged["p_real_w"].resample("1D").mean() * 24 / 1000.0
    print("\nTaegliche Energie (kWh) aus Mittelwert * 24:")
    for d, v in daily.items():
        print(f"  {d.date()}  {v:.1f} kWh")
