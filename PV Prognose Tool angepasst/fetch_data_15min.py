"""Hole 15-min-Daten fuer HTW-Vergleich."""
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

OUT = Path(__file__).parent / "data" / "merged_15min.csv"


def fetch_pv_15min() -> pd.DataFrame:
    print(f"Fetching 15-min real PV {START_DATE} .. {END_DATE}")
    client = InfluxDBClient(url=INFLUX_URL, token=require_influx_token(), org=INFLUX_ORG, timeout=120_000)
    q = f'''from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {START_DATE}T00:00:00Z, stop: {END_DATE + dt.timedelta(days=1)}T00:00:00Z)
      |> filter(fn: (r) => r._measurement == "Gesamterzeugung" and r._field == "value")
      |> aggregateWindow(every: 15m, fn: mean, createEmpty: true)'''
    rows = []
    for tbl in client.query_api().query(q):
        for rec in tbl.records:
            rows.append({"time": rec.get_time(), "p_real_w": rec.get_value()})
    client.close()
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df.index = df.index - pd.Timedelta(minutes=15)  # Fenster-Start statt -Ende
    df["p_real_w"] = pd.to_numeric(df["p_real_w"], errors="coerce")
    print(f"  {len(df)} Samples, NaN: {df['p_real_w'].isna().sum()}")
    return df


def fetch_weather_15min() -> pd.DataFrame:
    """Open-Meteo liefert stuendlich; wir interpolieren spaeter."""
    print(f"Fetching weather {START_DATE} .. {END_DATE}")
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": LATITUDE, "longitude": LONGITUDE,
        "start_date": str(START_DATE), "end_date": str(END_DATE),
        "hourly": "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m,wind_speed_10m",
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
    }).set_index("time").sort_index()
    df["wind_ms"] = df["wind_kmh"] / 3.6
    return df


if __name__ == "__main__":
    pv = fetch_pv_15min()
    wx = fetch_weather_15min()
    # Wetter auf 15-min resampeln + linear interpolieren
    wx_15 = wx.resample("15min").interpolate("linear")
    merged = pv.join(wx_15, how="left")
    # Abschneiden auf exakt START_DATE .. END_DATE
    merged = merged.loc[merged.index.date >= START_DATE]
    merged = merged.loc[merged.index.date <= END_DATE]
    merged.to_csv(OUT)
    print(f"\nSaved -> {OUT}  shape={merged.shape}")
    print(f"Real coverage: {merged['p_real_w'].notna().sum()} / {len(merged)}")
