"""Vergleich der beiden EMOS-Prognosealgorithmen mit echten Anlagendaten.

Anlagenkonfiguration:
  - beliebig viele Dachflaechen aus data/surfaces.json oder PV_SURFACES_JSON

Algorithmen:
  A) EMOS (alt):       Liu & Jordan (1963)  isotrop, DISC -> DNI/DHI
  B) EMOS_light (neu): Perez (1990)        anisotrop, direkte API-DNI/DHI

Metriken pro Algorithmus:
  MAE, RMSE, nRMSE (bezogen auf 18.5 kWp), Bias, R2, MAPE (>0.5 kW),
  Tagesenergie-MAE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from algorithms import emos_light_solar_perez as perez
from algorithms import emos_solar_isotropic as iso
from config import LATITUDE, LONGITUDE, load_surface_configs

SURFACES = [
    {
        "name": cfg["name"],
        "kwp": cfg["kwp"],
        "azimuth": cfg["azimuth_deg"],
        "tilt": cfg["tilt_deg"],
    }
    for cfg in load_surface_configs()
]

SYSTEM_EFF = 0.85   # Systemwirkungsgrad (typisch)
NOCT = 45.0
ALBEDO = 0.2
TEMP_COEFF = -0.004
AGE_YEARS = 0.0
DEG_RATE = 0.005
P_PEAK_KWP = sum(s["kwp"] for s in SURFACES)


def run_algo(df: pd.DataFrame, algo: str) -> np.ndarray:
    """Berechnet Prognose in kW fuer jede Flaeche und summiert.

    algo: 'iso' (EMOS Liu&Jordan) oder 'perez' (EMOS_light Perez).
    """
    # Zeitstempel als lokale naive datetimes (solar_position erwartet Lokalzeit)
    ts_utc = df.index.to_pydatetime()
    total_kw = np.zeros(len(df))

    for s in SURFACES:
        if algo == "iso":
            mod = iso
            # Timestamps in Lokalzeit fuer solar_position mit tz_offset
            # Wir uebergeben UTC und tz_offset=0, dann passt die Rechnung
            local_ts = [ts.replace(tzinfo=None) for ts in ts_utc]
            elev, az = mod.solar_position(local_ts, LATITUDE, LONGITUDE, timezone_offset_h=0.0)
            # POA je Tag bedeutet doy pro Tag - uebergib ersten doy,
            # Funktion nutzt doy nur fuer Exzentrizitaet (gleitend ueber 30d akzeptabel)
            doy_arr = np.array([ts.timetuple().tm_yday for ts in local_ts])
            # Batched: wir rufen ghi_to_poa je einzelnem doy? Funktion akzeptiert einen scalar doy.
            # Da Exzentrizitaet ueber 30d nur ~+-2% variiert: ok, aber wir machen es tagweise.
            poa = np.zeros(len(df))
            ghi = df["ghi"].to_numpy()
            for d in np.unique(doy_arr):
                mask = doy_arr == d
                poa[mask] = mod.ghi_to_poa(
                    ghi[mask], elev[mask], az[mask],
                    s["tilt"], s["azimuth"], ALBEDO, int(d),
                )
            t_cell = mod.estimate_cell_temperature(
                df["t_amb"].to_numpy(), poa, df["wind_ms"].to_numpy(), NOCT,
            )
            p = mod.estimate_pv_power(
                poa, s["kwp"],
                temp_coefficient=TEMP_COEFF,
                cell_temperature_c=t_cell,
                system_losses=1.0 - SYSTEM_EFF,
            )
        elif algo == "perez":
            mod = perez
            local_ts = [ts.replace(tzinfo=None) for ts in ts_utc]
            elev, az = mod.solar_position(local_ts, LATITUDE, LONGITUDE, timezone_offset_h=0.0)
            doy_arr = np.array([ts.timetuple().tm_yday for ts in local_ts])
            poa = np.zeros(len(df))
            ghi = df["ghi"].to_numpy()
            dni = df["dni"].to_numpy()
            dhi = df["dhi"].to_numpy()
            for d in np.unique(doy_arr):
                mask = doy_arr == d
                poa[mask] = mod.ghi_to_poa(
                    ghi[mask], elev[mask], az[mask],
                    s["tilt"], s["azimuth"], ALBEDO, int(d),
                    dni_override=dni[mask], dhi_override=dhi[mask],
                )
            t_cell = mod.estimate_cell_temperature(
                df["t_amb"].to_numpy(), poa, df["wind_ms"].to_numpy(), NOCT,
            )
            p = mod.estimate_pv_power(
                poa, s["kwp"],
                temp_coefficient=TEMP_COEFF,
                cell_temperature_c=t_cell,
                system_losses=1.0 - SYSTEM_EFF,
            )
        else:
            raise ValueError(algo)

        # Degradation (age_years=0 -> Faktor 1)
        p *= (1.0 - DEG_RATE) ** AGE_YEARS
        total_kw += np.maximum(p, 0.0)
    return total_kw


def metrics(y_true_w: np.ndarray, y_pred_w: np.ndarray, name: str) -> dict:
    """Berechnet Fehlermasse. Eingabe in Watt."""
    y = y_true_w.astype(float)
    p = y_pred_w.astype(float)
    mask = ~np.isnan(y) & ~np.isnan(p)
    y, p = y[mask], p[mask]
    err = p - y

    mae = np.mean(np.abs(err))
    rmse = np.sqrt(np.mean(err**2))
    bias = np.mean(err)
    # R2
    ss_res = np.sum(err**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    # nRMSE bezogen auf Nennleistung
    p_peak_w = P_PEAK_KWP * 1000.0
    nrmse = rmse / p_peak_w * 100.0
    # MAPE nur fuer echte Erzeugung > 500 W (sonst Division-Blaehung)
    m2 = y > 500.0
    mape = np.mean(np.abs(err[m2] / y[m2])) * 100.0 if m2.any() else float("nan")

    return {
        "algo": name, "MAE_W": mae, "RMSE_W": rmse, "nRMSE_%": nrmse,
        "Bias_W": bias, "R2": r2, "MAPE_%": mape, "n": len(y),
    }


if __name__ == "__main__":
    csv = ROOT / "data" / "merged_hourly.csv"
    df = pd.read_csv(csv, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)

    # Optional: nur Tagesstunden betrachten (GHI > 0)
    print(f"Gesamt-Stunden: {len(df)}")
    print(f"Stunden mit GHI > 0: {(df['ghi'] > 0).sum()}")
    print(f"Mittlere reale Erzeugung: {df['p_real_w'].mean():.0f} W\n")

    print("Running EMOS (isotropic Liu&Jordan) ...")
    p_iso = run_algo(df, "iso") * 1000.0   # kW -> W
    print("Running EMOS_light (Perez anisotropic) ...")
    p_per = run_algo(df, "perez") * 1000.0

    df["p_iso_w"] = p_iso
    df["p_perez_w"] = p_per
    df.to_csv(ROOT / "data" / "compare_hourly.csv")

    # --- Metriken (alle Stunden) ---
    print("\n=== Metriken (alle 744 Stunden) ===")
    m_iso = metrics(df["p_real_w"].values, p_iso, "EMOS (Liu&Jordan isotrop)")
    m_per = metrics(df["p_real_w"].values, p_per, "EMOS_light (Perez anisotrop)")
    for m in [m_iso, m_per]:
        print(f"  {m['algo']:40s}  MAE={m['MAE_W']:6.0f} W  "
              f"RMSE={m['RMSE_W']:6.0f} W  nRMSE={m['nRMSE_%']:5.2f}%  "
              f"Bias={m['Bias_W']:+6.0f} W  R2={m['R2']:.3f}  MAPE={m['MAPE_%']:.1f}%")

    # --- Metriken nur Tagesstunden (GHI > 50) ---
    day = df[df["ghi"] > 50].copy()
    print(f"\n=== Metriken (Tagesstunden, GHI>50, n={len(day)}) ===")
    m_iso = metrics(day["p_real_w"].values, day["p_iso_w"].values, "EMOS (Liu&Jordan isotrop)")
    m_per = metrics(day["p_real_w"].values, day["p_perez_w"].values, "EMOS_light (Perez anisotrop)")
    for m in [m_iso, m_per]:
        print(f"  {m['algo']:40s}  MAE={m['MAE_W']:6.0f} W  "
              f"RMSE={m['RMSE_W']:6.0f} W  nRMSE={m['nRMSE_%']:5.2f}%  "
              f"Bias={m['Bias_W']:+6.0f} W  R2={m['R2']:.3f}  MAPE={m['MAPE_%']:.1f}%")

    # --- Tagesenergie ---
    daily = df[["p_real_w", "p_iso_w", "p_perez_w"]].resample("1D").sum() / 1000.0  # Wh -> kWh (da 1h samples)
    daily["err_iso"] = daily["p_iso_w"] - daily["p_real_w"]
    daily["err_perez"] = daily["p_perez_w"] - daily["p_real_w"]
    print(f"\n=== Tages-Energie (kWh, n={len(daily)} Tage) ===")
    print(f"  Real Mittel:        {daily['p_real_w'].mean():.1f}  (min {daily['p_real_w'].min():.1f}, max {daily['p_real_w'].max():.1f})")
    print(f"  EMOS iso Mittel:    {daily['p_iso_w'].mean():.1f}   MAE-Tag={daily['err_iso'].abs().mean():.2f} kWh, Bias={daily['err_iso'].mean():+.2f}")
    print(f"  EMOS Perez Mittel:  {daily['p_perez_w'].mean():.1f}   MAE-Tag={daily['err_perez'].abs().mean():.2f} kWh, Bias={daily['err_perez'].mean():+.2f}")

    print("\nPer-Tag (kWh):")
    print(f"  {'Tag':10s}  {'real':>6s}  {'iso':>6s} ({'err':>6s})  {'perez':>6s} ({'err':>6s})")
    for d, row in daily.iterrows():
        print(f"  {d.date()}  {row['p_real_w']:6.1f}  "
              f"{row['p_iso_w']:6.1f} ({row['err_iso']:+6.1f})  "
              f"{row['p_perez_w']:6.1f} ({row['err_perez']:+6.1f})")

    # Speichern
    daily.to_csv(ROOT / "data" / "daily_compare.csv")
    print(f"\nErgebnisse: data/compare_hourly.csv, data/daily_compare.csv")
