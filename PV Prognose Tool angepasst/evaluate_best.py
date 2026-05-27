"""Evaluiert pv_forecast (Perez + Kalibrierung) gegen beide EMOS-Baselines.

Train/Test-Split: erste 2/3 der Tage zur Kalibrierung, letztes 1/3 als Test.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from pv_forecast import Surface, pv_forecast, calibrate_best_from_history
from algorithms import emos_solar_isotropic as iso
from algorithms import emos_light_solar_perez as perez
from config import AC_LIMIT_W, LATITUDE, LONGITUDE, load_surface_configs


SURFACES = [Surface(**cfg) for cfg in load_surface_configs()]
SYSTEM_EFF = 0.85
P_PEAK_W = sum(s.kwp for s in SURFACES) * 1000.0


def run_baseline(df: pd.DataFrame, module, use_dni_dhi: bool) -> np.ndarray:
    """Haendisch Baseline-Algorithmus laufen lassen (aehnlich wie compare.py)."""
    ts = df.index.to_pydatetime()
    local_ts = [t.replace(tzinfo=None) for t in ts]
    total_kw = np.zeros(len(df))
    ghi = df["ghi"].to_numpy()
    dni = df["dni"].to_numpy()
    dhi = df["dhi"].to_numpy()
    t_amb = df["t_amb"].to_numpy()
    wind = df["wind_ms"].to_numpy()

    for s in SURFACES:
        elev, az = module.solar_position(local_ts, LATITUDE, LONGITUDE, timezone_offset_h=0.0)
        doy_arr = np.array([t.timetuple().tm_yday for t in local_ts])
        poa = np.zeros(len(df))
        for d in np.unique(doy_arr):
            m = doy_arr == d
            if use_dni_dhi and hasattr(module, "ghi_to_poa"):
                try:
                    poa[m] = module.ghi_to_poa(
                        ghi[m], elev[m], az[m],
                        s.tilt_deg, s.azimuth_deg, 0.2, int(d),
                        dni_override=dni[m], dhi_override=dhi[m],
                    )
                    continue
                except TypeError:
                    pass
            poa[m] = module.ghi_to_poa(
                ghi[m], elev[m], az[m],
                s.tilt_deg, s.azimuth_deg, 0.2, int(d),
            )
        t_cell = module.estimate_cell_temperature(t_amb, poa, wind, 45.0)
        p = module.estimate_pv_power(
            poa, s.kwp,
            temp_coefficient=-0.004,
            cell_temperature_c=t_cell,
            system_losses=1.0 - SYSTEM_EFF,
        )
        total_kw += np.maximum(p, 0.0)
    return total_kw


def metrics(y: np.ndarray, p: np.ndarray, label: str) -> dict:
    mask = ~np.isnan(y) & ~np.isnan(p)
    y, p = y[mask], p[mask]
    err = p - y
    mae = np.mean(np.abs(err))
    rmse = np.sqrt(np.mean(err ** 2))
    bias = np.mean(err)
    ss_res = np.sum(err ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "label": label, "MAE": mae, "RMSE": rmse, "nRMSE_%": rmse / P_PEAK_W * 100,
        "Bias": bias, "R2": r2, "n": len(y),
    }


if __name__ == "__main__":
    df = pd.read_csv(ROOT / "data" / "merged_hourly.csv", index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)

    # Train/Test-Split nach Datum
    unique_days = sorted(df.index.floor("D").unique())
    split = int(len(unique_days) * 2 / 3)
    train_days = unique_days[:split]
    test_days = unique_days[split:]
    train = df[df.index.floor("D").isin(train_days)].copy()
    test = df[df.index.floor("D").isin(test_days)].copy()
    print(f"Train: {len(train_days)} Tage ({train.index.min().date()} .. {train.index.max().date()})  "
          f"Test: {len(test_days)} Tage ({test.index.min().date()} .. {test.index.max().date()})")

    # === Kalibrierung auf Trainingsset ===
    print("\n>>> Kalibriere auf Trainingsdaten ...")
    cal = calibrate_best_from_history(
        train.index.to_pydatetime(),
        ghi_w_m2=train["ghi"].to_numpy(),
        real_generation_w=train["p_real_w"].to_numpy(),
        surfaces=SURFACES,
        latitude=LATITUDE, longitude=LONGITUDE,
        dni_w_m2=train["dni"].to_numpy(),
        dhi_w_m2=train["dhi"].to_numpy(),
        ambient_temp_c=train["t_amb"].to_numpy(),
        wind_speed_m_s=train["wind_ms"].to_numpy(),
        ac_limit_w=AC_LIMIT_W, tz_offset_h=0.0,
    )
    print(f"  Kalibrierung: methode={cal.method}  k={cal.k:.4f}  bias={cal.bias_w:.1f} W  "
          f"n={cal.n_samples}  train-RMSE={cal.rmse_w:.0f} W")

    # === Auf Test-Set prognostizieren ===
    print("\n>>> Prognosen auf Test-Set ...")

    # 1) EMOS (Liu&Jordan isotrop)
    p_iso = run_baseline(test, iso, use_dni_dhi=False) * 1000.0
    # 2) EMOS_light (Perez anisotrop, API-DNI/DHI, ohne Kalibrierung)
    p_per_raw = run_baseline(test, perez, use_dni_dhi=True) * 1000.0
    # 3) Best: Perez + Kalibrierung
    p_best_kw = pv_forecast(
        test.index.to_pydatetime(),
        test["ghi"].to_numpy(), SURFACES,
        latitude=LATITUDE, longitude=LONGITUDE,
        dni_w_m2=test["dni"].to_numpy(), dhi_w_m2=test["dhi"].to_numpy(),
        ambient_temp_c=test["t_amb"].to_numpy(), wind_speed_m_s=test["wind_ms"].to_numpy(),
        system_efficiency=SYSTEM_EFF, calibration=cal, ac_limit_w=AC_LIMIT_W, tz_offset_h=0.0,
    )
    p_best = p_best_kw * 1000.0

    y = test["p_real_w"].to_numpy()

    # === Metriken ===
    print("\n=== Test-Metriken (Watt) ===")
    for p, label in [
        (p_iso, "EMOS        (Liu&Jordan iso, 85% eff)"),
        (p_per_raw, "EMOS_light  (Perez, API-DNI/DHI, 85% eff)"),
        (p_best, "pvprog      (Perez + Kalibrierung)      "),
    ]:
        m = metrics(y, p, label)
        print(f"  {m['label']:45s}  MAE={m['MAE']:5.0f}  RMSE={m['RMSE']:5.0f}  "
              f"nRMSE={m['nRMSE_%']:4.2f}%  Bias={m['Bias']:+5.0f}  R2={m['R2']:+.3f}")

    # Nur Tagesstunden
    print("\n=== Test-Metriken nur Tagesstunden (GHI>50) ===")
    m_day = test["ghi"] > 50
    for p, label in [
        (p_iso, "EMOS        (Liu&Jordan iso, 85% eff)"),
        (p_per_raw, "EMOS_light  (Perez, API-DNI/DHI, 85% eff)"),
        (p_best, "pvprog      (Perez + Kalibrierung)      "),
    ]:
        m = metrics(y[m_day], p[m_day], label)
        print(f"  {m['label']:45s}  MAE={m['MAE']:5.0f}  RMSE={m['RMSE']:5.0f}  "
              f"nRMSE={m['nRMSE_%']:4.2f}%  Bias={m['Bias']:+5.0f}  R2={m['R2']:+.3f}")

    # Tages-Energie
    out = pd.DataFrame({
        "real_w": y, "iso_w": p_iso, "perez_w": p_per_raw, "best_w": p_best,
    }, index=test.index)
    daily = out.resample("1D").sum() / 1000.0  # Wh->kWh bei 1h-Raster
    daily["err_iso"] = daily["iso_w"] - daily["real_w"]
    daily["err_perez"] = daily["perez_w"] - daily["real_w"]
    daily["err_best"] = daily["best_w"] - daily["real_w"]

    print(f"\n=== Test-Tagesenergie (kWh, {len(daily)} Tage) ===")
    print(f"  Real Mittel:  {daily['real_w'].mean():5.1f}  (min {daily['real_w'].min():.1f}, max {daily['real_w'].max():.1f})")
    for col, label in [("iso_w", "iso  "), ("perez_w", "perez"), ("best_w", "best ")]:
        err = daily[f"err_{label.strip()}"]
        print(f"  {label} Mittel: {daily[col].mean():5.1f}   Tages-MAE={err.abs().mean():5.2f} kWh  Bias={err.mean():+5.2f} kWh")

    print("\nPer-Tag (kWh):")
    print(f"  {'Tag':10s}  {'real':>6s}  {'iso':>6s} ({'err':>5s})  {'perez':>6s} ({'err':>5s})  {'best':>6s} ({'err':>5s})")
    for d, r in daily.iterrows():
        print(f"  {d.date()}  {r['real_w']:6.1f}  "
              f"{r['iso_w']:6.1f} ({r['err_iso']:+5.1f})  "
              f"{r['perez_w']:6.1f} ({r['err_perez']:+5.1f})  "
              f"{r['best_w']:6.1f} ({r['err_best']:+5.1f})")

    daily.to_csv(ROOT / "data" / "eval_best_daily.csv")
    out.to_csv(ROOT / "data" / "eval_best_hourly.csv")
    # Kalibrierung speichern
    import json
    with open(ROOT / "data" / "calibration.json", "w") as f:
        json.dump({
            "k": cal.k, "bias_w": cal.bias_w,
            "n_samples": cal.n_samples, "rmse_w": cal.rmse_w,
            "method": cal.method,
            "clearness_edges": cal.clearness_edges,
            "clearness_k": cal.clearness_k,
            "system_efficiency_effective": SYSTEM_EFF * cal.k,
            "surfaces": [
                {"name": s.name, "kwp": s.kwp, "tilt_deg": s.tilt_deg, "azimuth_deg": s.azimuth_deg}
                for s in SURFACES
            ],
            "latitude": LATITUDE, "longitude": LONGITUDE,
        }, f, indent=2)
    print(f"\nGespeichert: data/calibration.json, data/eval_best_*.csv")
