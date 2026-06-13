"""Prognose fuer einen beliebigen Tag mit allen Algorithmen.

Aufruf:
    python forecast_today.py                # heute
    python forecast_today.py 2026-04-14     # Vergangenheit (nutzt archive-api)

- Wetterbasiert: Open-Meteo Forecast- oder Archive-API (automatisch).
- HTW:           Messwertbasiert, rollierend aus Influx-Daten.
- Vergleich mit realer Erzeugung aus Influx.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from influxdb_client import InfluxDBClient

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from pv_forecast import Surface, pv_forecast, calibrate_best_from_history
from algorithms import emos_solar_isotropic as iso
from algorithms import emos_light_solar_perez as perez
from algorithms.htw_prog4pv import prog4pv
from config import (
    INFLUX_BUCKET,
    INFLUX_ORG,
    INFLUX_URL,
    AC_LIMIT_W,
    LATITUDE,
    LONGITUDE,
    load_surface_configs,
    require_influx_token,
)

SURFACES = [Surface(**cfg) for cfg in load_surface_configs()]
SYSTEM_EFF = 0.85
P_PEAK_KWP = sum(s.kwp for s in SURFACES)
P_PEAK_W = P_PEAK_KWP * 1000.0

TARGET_DEFAULT = dt.date.today()


def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", default=str(TARGET_DEFAULT),
                    help="Zieldatum YYYY-MM-DD (Default: heute bzw. 2026-04-20)")
    return ap.parse_args()


TARGET = dt.date.fromisoformat(_parse_args().date)


def fetch_day_weather(target: dt.date) -> pd.DataFrame:
    """Holt Wetterdaten fuer target. Archive-API wenn Vergangenheit, sonst Forecast-API."""
    today = dt.date.today()
    use_archive = (today - target).days >= 2
    url = ("https://archive-api.open-meteo.com/v1/archive" if use_archive
           else "https://api.open-meteo.com/v1/forecast")
    src = "archive-api (ERA5)" if use_archive else "forecast-api"
    print(f"  -> {src}")
    r = requests.get(url, params={
        "latitude": LATITUDE, "longitude": LONGITUDE,
        "hourly": "shortwave_radiation,direct_normal_irradiance,diffuse_radiation,temperature_2m,wind_speed_10m",
        "start_date": str(target), "end_date": str(target),
        "timezone": "UTC",
    }, timeout=30)
    r.raise_for_status()
    h = r.json()["hourly"]
    df = pd.DataFrame({
        "time": pd.to_datetime(h["time"], utc=True),
        "ghi": h["shortwave_radiation"], "dni": h["direct_normal_irradiance"],
        "dhi": h["diffuse_radiation"], "t_amb": h["temperature_2m"],
        "wind_kmh": h["wind_speed_10m"],
    }).set_index("time").sort_index()
    df["wind_ms"] = df["wind_kmh"] / 3.6
    # Auf 15-min resamplen (linear interpolieren)
    df15 = df.resample("15min").interpolate("linear")
    # Bis 23:45 auffuellen
    end_ts = pd.Timestamp(f"{target} 23:45:00", tz="UTC")
    df15 = df15.reindex(pd.date_range(df15.index.min(), end_ts, freq="15min"))
    df15 = df15.interpolate("linear").ffill()
    return df15


def fetch_real_today() -> pd.DataFrame:
    """Reale 15-min PV-Daten von heute aus Influx."""
    client = InfluxDBClient(url=INFLUX_URL, token=require_influx_token(), org=INFLUX_ORG, timeout=60_000)
    q = f'''from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {TARGET}T00:00:00Z, stop: {TARGET + dt.timedelta(days=1)}T00:00:00Z)
      |> filter(fn: (r) => r._measurement == "Gesamterzeugung" and r._field == "value")
      |> aggregateWindow(every: 15m, fn: mean, createEmpty: true)'''
    rows = []
    for tbl in client.query_api().query(q):
        for rec in tbl.records:
            rows.append({"time": rec.get_time(), "p_real_w": rec.get_value()})
    client.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame({"p_real_w": []}, index=pd.DatetimeIndex([], tz="UTC", name="time"))
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df.index = df.index - pd.Timedelta(minutes=15)
    return df


def fetch_real_lastdays(n_days: int = 15) -> pd.Series:
    """15-min Daten der letzten n Tage + heute fuer HTW-Historie."""
    start = TARGET - dt.timedelta(days=n_days)
    client = InfluxDBClient(url=INFLUX_URL, token=require_influx_token(), org=INFLUX_ORG, timeout=60_000)
    q = f'''from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {start}T00:00:00Z, stop: {TARGET + dt.timedelta(days=1)}T00:00:00Z)
      |> filter(fn: (r) => r._measurement == "Gesamterzeugung" and r._field == "value")
      |> aggregateWindow(every: 15m, fn: mean, createEmpty: true)'''
    rows = []
    for tbl in client.query_api().query(q):
        for rec in tbl.records:
            rows.append({"time": rec.get_time(), "p_real_w": rec.get_value()})
    client.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC", name="time"), name="p_real_w")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    df.index = df.index - pd.Timedelta(minutes=15)
    return df["p_real_w"]


def latest_htw_source_before_day(
    p_hist: pd.Series,
    p_pvf: np.ndarray,
    target: dt.date,
) -> int | None:
    """Findet den letzten sinnvollen HTW-Prognosezeitpunkt vor Tagesbeginn."""
    day_start = pd.Timestamp(f"{target} 00:00", tz="UTC")
    if p_hist.empty:
        return None
    positions = np.where(p_hist.index < day_start)[0]
    for pos in positions[::-1]:
        if pos < len(p_pvf) and np.nansum(p_pvf[pos]) > 0:
            return int(pos)
    return None


def hybrid_intraday_forecast(
    p_best_w: np.ndarray,
    htw_intraday_w: np.ndarray,
    real_w: np.ndarray,
    last_real_idx: int,
    *,
    h0_h: float = 1.0,
) -> np.ndarray:
    """Mischt Istwerte, HTW-Kurzfrist und pvprog-best fuer einen Tageslauf."""
    out = np.asarray(p_best_w, dtype=float).copy()
    if last_real_idx >= 0:
        known = ~np.isnan(real_w[:last_real_idx + 1])
        known_idx = np.where(known)[0]
        out[known_idx] = real_w[known_idx]
    for i in range(max(last_real_idx + 1, 0), len(out)):
        h = (i - last_real_idx) * 0.25 if last_real_idx >= 0 else float("inf")
        htw = htw_intraday_w[i]
        if htw > 0 and np.isfinite(h):
            w = math.exp(-h / h0_h)
            out[i] = w * htw + (1.0 - w) * out[i]
    return np.maximum(out, 0.0)


def rolling_live_bias(
    real_w: np.ndarray,
    forecast_w: np.ndarray,
    last_real_idx: int,
    *,
    lookback_slots: int = 8,
) -> float:
    """Mittlere aktuelle Abweichung real - Prognose aus den letzten Tages-Slots."""
    if last_real_idx < 0:
        return 0.0
    start = max(0, last_real_idx - lookback_slots + 1)
    real = np.asarray(real_w[start:last_real_idx + 1], dtype=float)
    forecast = np.asarray(forecast_w[start:last_real_idx + 1], dtype=float)
    mask = np.isfinite(real) & np.isfinite(forecast) & (real > 50.0) & (forecast > 50.0)
    if mask.sum() < 2:
        return 0.0
    return float(np.clip(np.mean(real[mask] - forecast[mask]), -0.25 * P_PEAK_W, 0.25 * P_PEAK_W))


def apply_decaying_bias(
    forecast_w: np.ndarray,
    bias_w: float,
    last_real_idx: int,
    *,
    decay_h: float = 2.0,
) -> np.ndarray:
    """Traegt einen aktuellen Bias mit exponentiellem Abklingen in die Zukunft."""
    out = np.asarray(forecast_w, dtype=float).copy()
    if last_real_idx < 0 or abs(bias_w) < 1.0:
        return np.maximum(out, 0.0)
    for i in range(last_real_idx + 1, len(out)):
        h = (i - last_real_idx) * 0.25
        out[i] += bias_w * math.exp(-h / decay_h)
    return np.maximum(out, 0.0)


if __name__ == "__main__":
    # Kalibrierung aus den Trainingsdaten wiederverwenden
    print("Lade Kalibrierung aus vorherigem Run (20-Tage-Training) ...")
    train = pd.read_csv(ROOT / "data" / "merged_15min.csv", index_col=0, parse_dates=True)
    train.index = pd.to_datetime(train.index, utc=True)
    train["p_real_w"] = train["p_real_w"].interpolate(limit=2).fillna(0.0)
    unique_days = sorted(set(train.index.date))
    split = int(len(unique_days) * 2 / 3)
    train_days = set(unique_days[:split])
    train_df = train[[d in train_days for d in train.index.date]]
    cal = calibrate_best_from_history(
        train_df.index.to_pydatetime(),
        ghi_w_m2=train_df["ghi"].to_numpy(),
        real_generation_w=train_df["p_real_w"].to_numpy(),
        surfaces=SURFACES, latitude=LATITUDE, longitude=LONGITUDE,
        dni_w_m2=train_df["dni"].to_numpy(), dhi_w_m2=train_df["dhi"].to_numpy(),
        ambient_temp_c=train_df["t_amb"].to_numpy(),
        wind_speed_m_s=train_df["wind_ms"].to_numpy(),
        ac_limit_w=AC_LIMIT_W, tz_offset_h=0.0,
    )
    print(f"  Methode = {cal.method}   k = {cal.k:.4f}")
    if cal.clearness_k is not None:
        print("  Wetterklassen-k = " + ", ".join(f"{v:.3f}" for v in cal.clearness_k))

    # --- Wetter fuer heute ---
    print("\nHole Wetterprognose Open-Meteo fuer heute ...")
    wx = fetch_day_weather(TARGET)
    print(f"  {len(wx)} Slots  ({wx.index.min()} .. {wx.index.max()})")

    # --- Echte Daten ---
    real_today = fetch_real_today()
    print(f"Reale Erzeugung heute: {len(real_today)} Slots, Summe={real_today['p_real_w'].sum()*0.25/1000:.1f} kWh bis jetzt")

    # --- Zeitstempel fuer den ganzen Tag (96 Slots) ---
    t_idx = pd.date_range(f"{TARGET} 00:00", f"{TARGET} 23:45", freq="15min", tz="UTC")
    wx = wx.reindex(t_idx).interpolate("linear").ffill().bfill()

    ts = t_idx.to_pydatetime()

    # --- A) WETTERBASIERTE PROGNOSEN ---
    # EMOS iso
    local_ts = [t.replace(tzinfo=None) for t in ts]
    total_iso = np.zeros(96)
    total_per = np.zeros(96)
    for s in SURFACES:
        elev, az = iso.solar_position(local_ts, LATITUDE, LONGITUDE, 0.0)
        doy = local_ts[0].timetuple().tm_yday
        poa_i = iso.ghi_to_poa(wx["ghi"].to_numpy(), elev, az, s.tilt_deg, s.azimuth_deg, 0.2, doy)
        poa_p = perez.ghi_to_poa(
            wx["ghi"].to_numpy(), elev, az, s.tilt_deg, s.azimuth_deg, 0.2, doy,
            dni_override=wx["dni"].to_numpy(), dhi_override=wx["dhi"].to_numpy(),
        )
        tc_i = iso.estimate_cell_temperature(wx["t_amb"].to_numpy(), poa_i, wx["wind_ms"].to_numpy(), 45.0)
        tc_p = perez.estimate_cell_temperature(wx["t_amb"].to_numpy(), poa_p, wx["wind_ms"].to_numpy(), 45.0)
        total_iso += iso.estimate_pv_power(poa_i, s.kwp, temp_coefficient=-0.004,
                                           cell_temperature_c=tc_i, system_losses=1-SYSTEM_EFF)
        total_per += perez.estimate_pv_power(poa_p, s.kwp, temp_coefficient=-0.004,
                                             cell_temperature_c=tc_p, system_losses=1-SYSTEM_EFF)
    p_iso_kw = total_iso
    p_per_kw = total_per

    # pvprog-best
    p_best_kw = pv_forecast(
        ts, wx["ghi"].to_numpy(), SURFACES,
        latitude=LATITUDE, longitude=LONGITUDE,
        dni_w_m2=wx["dni"].to_numpy(), dhi_w_m2=wx["dhi"].to_numpy(),
        ambient_temp_c=wx["t_amb"].to_numpy(), wind_speed_m_s=wx["wind_ms"].to_numpy(),
        system_efficiency=SYSTEM_EFF, calibration=cal, ac_limit_w=AC_LIMIT_W, tz_offset_h=0.0,
    )

    # --- B) HTW-PROGNOSE ---
    # Um Day-Ahead-Prognose fuer heute zu bauen: Prognose wird zum Zeitpunkt
    # "gestern 23:45" erstellt. Also brauchen wir Historie BIS gestern 23:45.
    print("\nHole Historie fuer HTW (letzte 15 Tage) ...")
    p_hist = fetch_real_lastdays(15)
    p_spec = (p_hist.clip(lower=0) / P_PEAK_W).to_numpy()
    p_htw_w = np.zeros(96)
    if len(p_hist) > 0:
        # tf_prog_h=30, damit ein spaeter Tages-Slot des Vortags bis heute 23:45 reicht.
        p_pvf = prog4pv(p_spec, step_min=15, tf_past_min=30, tf_prog_h=30, lookback_days=10)
        src_idx = latest_htw_source_before_day(p_hist, p_pvf, TARGET)
        if src_idx is not None:
            for i, target_ts in enumerate(t_idx):
                k = p_hist.index.get_indexer([target_ts])[0] - src_idx - 1
                if 0 <= k < p_pvf.shape[1]:
                    p_htw_w[i] = p_pvf[src_idx, k] * P_PEAK_W
    else:
        p_pvf = np.zeros((0, 0))

    # --- HTW INTRADAY: rolle bis "jetzt", nutze aktuellen k_TF fuer Rest-Tag ---
    # Suche letzten Tagesslot heute mit k_TF > 0
    htw_intraday_w = np.zeros(96)
    # Uebernehme echte Messwerte bis "jetzt"
    real_today_vals = real_today["p_real_w"].reindex(t_idx).to_numpy()
    now_mask = ~np.isnan(real_today_vals) & (real_today_vals > 0)
    last_real_idx = np.where(now_mask)[0].max() if now_mask.any() else -1
    # Letzter Tages-Slot in der Historie, wo k_TF berechnet ist
    # p_hist enthaelt auch heute; suche letzte Position in p_hist, die Tag-Slot ist
    today_now_ts = pd.Timestamp(f"{TARGET} {t_idx[last_real_idx].strftime('%H:%M')}", tz="UTC") if last_real_idx >= 0 else None
    if today_now_ts is not None and today_now_ts in p_hist.index and len(p_pvf) > 0:
        src2 = p_hist.index.get_loc(today_now_ts)
        # Slots ab jetzt bis Tagesende
        for i in range(last_real_idx + 1, 96):
            k = i - last_real_idx - 1   # Prognose-Schritt (0 = naechster Slot)
            if k < p_pvf.shape[1]:
                htw_intraday_w[i] = p_pvf[src2, k] * P_PEAK_W
        # Vor "jetzt" uebernehmen wir die Ist-Werte (fuer Tagesintegral)
        htw_intraday_w[:last_real_idx + 1] = real_today_vals[:last_real_idx + 1]

    p_best_w = p_best_kw * 1000.0
    bias_now_w = rolling_live_bias(real_today_vals, p_best_w, last_real_idx)
    p_best_live_w = apply_decaying_bias(p_best_w, bias_now_w, last_real_idx)
    hybrid_w = hybrid_intraday_forecast(
        p_best_live_w, htw_intraday_w, real_today_vals, last_real_idx,
    )

    # --- Kombinierte Uebersicht ---
    out = pd.DataFrame({
        "real_w": real_today["p_real_w"].reindex(t_idx).to_numpy(),
        "emos_iso_w": p_iso_kw * 1000.0,
        "emos_perez_w": p_per_kw * 1000.0,
        "pvprog_best_w": p_best_w,
        "pvprog_best_live_w": p_best_live_w,
        "htw_w": p_htw_w,
        "htw_intraday_w": htw_intraday_w,
        "hybrid_w": hybrid_w,
    }, index=t_idx)

    # Tagesenergie (15 min -> kWh: *0.25/1000)
    daily_kwh = out.sum() * 0.25 / 1000.0
    # Bis-jetzt-Energie (nur Slots mit Realwert)
    now_mask = out["real_w"].notna()
    until_now_kwh = (out.loc[now_mask].sum() * 0.25 / 1000.0)

    print("\n" + "=" * 78)
    print(f"PROGNOSE FUER {TARGET}  ({len(SURFACES)} Dachflaechen, {P_PEAK_KWP:.1f} kWp, {LATITUDE:.2f}N/{LONGITUDE:.2f}E)")
    print("=" * 78)
    last_real_ts = out[out["real_w"].notna()].index.max()
    print(f"Aktueller Stand: {last_real_ts} UTC  "
          f"(~{(last_real_ts + pd.Timedelta(hours=2)).strftime('%H:%M')} Lokal MESZ)\n")

    print(f"{'Algorithmus':30s}  {'Tagesenergie':>14s}  {'bis jetzt':>11s}  {'Abweichung':>11s}")
    print("-" * 78)
    real_now = until_now_kwh["real_w"]
    print(f"{'REAL (aus Influx)':30s}  {'—':>14s}  {real_now:>8.1f} kWh  {'':>11s}")
    for col, label in [
        ("emos_iso_w",    "EMOS (Liu&Jordan iso)        "),
        ("emos_perez_w",  "EMOS_light (Perez)           "),
        ("pvprog_best_w", "pvprog-best (Perez+Kalib)    "),
        ("pvprog_best_live_w", "pvprog-best (+Live-Bias)  "),
        ("htw_w",          "HTW PVprog (24h Day-Ahead)   "),
        ("htw_intraday_w", "HTW PVprog (Intraday + Ist)  "),
        ("hybrid_w",       "Hybrid (Ist+HTW+pvprog-best) "),
    ]:
        full = daily_kwh[col]
        nowp = until_now_kwh[col]
        delta = nowp - real_now
        print(f"{label:30s}  {full:>10.1f} kWh  {nowp:>8.1f} kWh  {delta:+8.1f} kWh")

    print("\nHinweis: Real-Wert ist die integrierte 15-min-Leistung bis zum letzten")
    print("         vorhandenen Sample; Influx-Mittelwert-basiert, nicht Zaehler.")

    # Stuendliche Profile ausgeben (verdichtet)
    hourly = out.resample("1H").mean()  # mittlere Leistung je Stunde (W)
    print("\nStuendliche Leistungsprognose (W, Mittel je Stunde):")
    print(f"  {'UTC':5s}  {'real':>5s}  {'iso':>5s}  {'perez':>5s}  {'best':>5s}  {'htw':>5s}")
    for t, row in hourly.iterrows():
        r = row["real_w"]
        rs = f"{r:5.0f}" if not np.isnan(r) else "   — "
        print(f"  {t.strftime('%H:%M'):5s}  {rs}  "
              f"{row['emos_iso_w']:5.0f}  {row['emos_perez_w']:5.0f}  "
              f"{row['pvprog_best_w']:5.0f}  {row['htw_w']:5.0f}")

    out.to_csv(ROOT / "data" / f"forecast_{TARGET}.csv")
    print(f"\nDetailprognose: data/forecast_{TARGET}.csv")
