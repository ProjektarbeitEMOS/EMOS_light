"""Gesamtvergleich: EMOS (iso) vs. EMOS_light (Perez) vs. HTW-PVprog vs. pvprog-best.

Wichtig: EMOS und HTW loesen unterschiedliche Probleme:
  - EMOS/EMOS_light: wetterbasierte Day-Ahead-Prognose (Open-Meteo GHI/DNI/DHI)
  - HTW PVprog:      messwertbasierte Kurzfrist-Prognose (Persistenz, tf_prog h)

Damit der Vergleich fair ist, bewerten wir alle Algorithmen auf denselben
Test-Zeitstempeln, aber bei HTW pruefen wir nur die Prognoseschritte
innerhalb des HTW-Horizonts (tf_prog_h).
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
from algorithms.htw_prog4pv import prog4pv
from config import AC_LIMIT_W, LATITUDE, LONGITUDE, load_surface_configs

SURFACES = [Surface(**cfg) for cfg in load_surface_configs()]
SYSTEM_EFF = 0.85
P_PEAK_KWP = sum(s.kwp for s in SURFACES)
P_PEAK_W = P_PEAK_KWP * 1000.0
STEP_MIN = 15
STEPS_PER_DAY = 96


def latest_htw_source_before_day(index: pd.DatetimeIndex, p_pvf: np.ndarray, day) -> int | None:
    """Letzter HTW-Prognosezeitpunkt mit Tagesinformation vor Tagesbeginn."""
    day_start = pd.Timestamp(day, tz="UTC")
    positions = np.where(index < day_start)[0]
    for pos in positions[::-1]:
        if np.nansum(p_pvf[pos]) > 0:
            return int(pos)
    return None


def run_physical(df: pd.DataFrame, module, use_dni_dhi: bool) -> np.ndarray:
    """Faehrt EMOS/EMOS_light auf 15-min-Raster."""
    ts = df.index.to_pydatetime()
    local_ts = [t.replace(tzinfo=None) for t in ts]
    ghi = df["ghi"].to_numpy()
    dni = df["dni"].to_numpy()
    dhi = df["dhi"].to_numpy()
    t_amb = df["t_amb"].to_numpy()
    wind = df["wind_ms"].to_numpy()

    total = np.zeros(len(df))
    for s in SURFACES:
        elev, az = module.solar_position(local_ts, LATITUDE, LONGITUDE, 0.0)
        doy_arr = np.array([t.timetuple().tm_yday for t in local_ts])
        poa = np.zeros(len(df))
        for d in np.unique(doy_arr):
            m = doy_arr == d
            kwargs = {}
            if use_dni_dhi:
                kwargs = {"dni_override": dni[m], "dhi_override": dhi[m]}
            poa[m] = module.ghi_to_poa(
                ghi[m], elev[m], az[m], s.tilt_deg, s.azimuth_deg, 0.2, int(d),
                **kwargs,
            )
        t_cell = module.estimate_cell_temperature(t_amb, poa, wind, 45.0)
        p = module.estimate_pv_power(
            poa, s.kwp,
            temp_coefficient=-0.004,
            cell_temperature_c=t_cell,
            system_losses=1.0 - SYSTEM_EFF,
        )
        total += np.maximum(p, 0.0)
    return total * 1000.0  # kW -> W


def metrics(y: np.ndarray, p: np.ndarray, label: str) -> dict:
    mask = ~np.isnan(y) & ~np.isnan(p)
    y, p = y[mask], p[mask]
    err = p - y
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return {
        "label": label,
        "MAE": np.mean(np.abs(err)),
        "RMSE": np.sqrt(np.mean(err ** 2)),
        "nRMSE_%": np.sqrt(np.mean(err ** 2)) / P_PEAK_W * 100,
        "Bias": np.mean(err),
        "R2": 1.0 - np.sum(err ** 2) / ss_tot if ss_tot > 0 else float("nan"),
        "n": len(y),
    }


if __name__ == "__main__":
    df = pd.read_csv(ROOT / "data" / "merged_15min.csv", index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index, utc=True)
    df["p_real_w"] = df["p_real_w"].interpolate(limit=2).fillna(0.0)

    # Spezifische PV-Leistung (kW/kWp), 0..1
    p_pv_spec = (df["p_real_w"] / P_PEAK_W).clip(lower=0.0).to_numpy()

    # Train/Test-Split auf Tagesbasis
    unique_days = sorted(set(df.index.date))
    split = int(len(unique_days) * 2 / 3)
    train_days = set(unique_days[:split])
    test_days = set(unique_days[split:])
    train_mask = np.array([d in train_days for d in df.index.date])
    test_mask = np.array([d in test_days for d in df.index.date])

    print(f"Train: {len(train_days)} Tage   Test: {len(test_days)} Tage")
    print(f"Samples: train={train_mask.sum()}, test={test_mask.sum()}")

    train_df = df[train_mask]
    test_df = df[test_mask]

    # --- Kalibrierung fuer pvprog-best auf Trainingsdaten ---
    print("\n>>> Kalibriere pvprog-best ...")
    cal = calibrate_best_from_history(
        train_df.index.to_pydatetime(),
        ghi_w_m2=train_df["ghi"].to_numpy(),
        real_generation_w=train_df["p_real_w"].to_numpy(),
        surfaces=SURFACES,
        latitude=LATITUDE, longitude=LONGITUDE,
        dni_w_m2=train_df["dni"].to_numpy(),
        dhi_w_m2=train_df["dhi"].to_numpy(),
        ambient_temp_c=train_df["t_amb"].to_numpy(),
        wind_speed_m_s=train_df["wind_ms"].to_numpy(),
        ac_limit_w=AC_LIMIT_W, tz_offset_h=0.0,
    )
    print(f"  methode={cal.method}  k={cal.k:.4f}  n={cal.n_samples}")
    if cal.clearness_k is not None:
        print("  Wetterklassen-k: " + ", ".join(f"{v:.3f}" for v in cal.clearness_k))

    # --- Prognosen auf Test-Set ---
    p_iso = run_physical(test_df, iso, use_dni_dhi=False)
    p_per = run_physical(test_df, perez, use_dni_dhi=True)
    p_best_kw = pv_forecast(
        test_df.index.to_pydatetime(),
        test_df["ghi"].to_numpy(), SURFACES,
        latitude=LATITUDE, longitude=LONGITUDE,
        dni_w_m2=test_df["dni"].to_numpy(), dhi_w_m2=test_df["dhi"].to_numpy(),
        ambient_temp_c=test_df["t_amb"].to_numpy(),
        wind_speed_m_s=test_df["wind_ms"].to_numpy(),
        system_efficiency=SYSTEM_EFF, calibration=cal, ac_limit_w=AC_LIMIT_W, tz_offset_h=0.0,
    )
    p_best = p_best_kw * 1000.0

    y_test = test_df["p_real_w"].to_numpy()

    print("\n" + "=" * 78)
    print("A) WETTERBASIERTE DAY-AHEAD-PROGNOSE")
    print(f"   (dauerhafte Prognose aus Open-Meteo-Archiv, Test = {len(test_days)} Tage)")
    print("=" * 78)
    for p, label in [
        (p_iso,  "EMOS        (Liu&Jordan iso, 85% eff)"),
        (p_per,  "EMOS_light  (Perez, API-DNI/DHI, 85% eff)"),
        (p_best, f"pvprog-best (Perez + Auto-Kalib.: {cal.method})"),
    ]:
        m = metrics(y_test, p, label)
        print(f"  {m['label']:50s}  MAE={m['MAE']:5.0f}W  RMSE={m['RMSE']:5.0f}W  "
              f"nRMSE={m['nRMSE_%']:5.2f}%  Bias={m['Bias']:+5.0f}W  R2={m['R2']:+.3f}")

    # --- HTW PVprog ---
    # Laeuft auf ALLEN Tagen (braucht Historie), wir evaluieren nur Test-Zeitraum
    # Wir rollieren ueber die ganze Zeitreihe und extrahieren fuer jeden
    # Test-Zeitpunkt t die Prognose, die zum Zeitpunkt t-h erstellt wurde.
    # Das entspricht einer "h Stunden voraus"-Prognose.
    p_pvf = prog4pv(
        p_pv_spec, step_min=STEP_MIN,
        tf_past_min=30.0, tf_prog_h=30.0, lookback_days=10,
    )
    # p_pvf[t, k] = Prognose zum Zeitpunkt t fuer t + (k+1)*15min

    print("\n" + "=" * 78)
    print("B) MESSWERTBASIERTE KURZFRIST-PROGNOSE (HTW PVprog)")
    print(f"   ({cal.n_samples}-Tage-Historie als Aufbau, Prognose aus aktuellen Messwerten)")
    print("=" * 78)
    # Evaluiere mehrere Prognosehorizonte
    n_all = len(df)
    p_real_all = df["p_real_w"].to_numpy()
    for horizon_h in [0.25, 1.0, 4.0, 8.0, 24.0]:
        k = int(round(horizon_h * 60 / STEP_MIN)) - 1  # Spaltenindex im p_pvf
        # fuer jeden Zeitpunkt t_target im Test-Bereich: benutze p_pvf[t_target - (k+1), k]
        shift = k + 1
        y_list, pred_list = [], []
        for t_target in np.where(test_mask)[0]:
            src = t_target - shift
            if src < 0:
                continue
            pred = p_pvf[src, k] * P_PEAK_W  # spez. -> W
            y_list.append(p_real_all[t_target])
            pred_list.append(pred)
        y_arr = np.array(y_list)
        pred_arr = np.array(pred_list)
        m = metrics(y_arr, pred_arr, f"HTW PVprog (Horizont {horizon_h:.2f}h)")
        print(f"  {m['label']:50s}  MAE={m['MAE']:5.0f}W  RMSE={m['RMSE']:5.0f}W  "
              f"nRMSE={m['nRMSE_%']:5.2f}%  Bias={m['Bias']:+5.0f}W  R2={m['R2']:+.3f}")

    # --- Hybrid: HTW fuer kurze Horizonte, pvprog-best fuer laengere Horizonte ---
    p_best_all_kw = pv_forecast(
        df.index.to_pydatetime(),
        df["ghi"].to_numpy(), SURFACES,
        latitude=LATITUDE, longitude=LONGITUDE,
        dni_w_m2=df["dni"].to_numpy(), dhi_w_m2=df["dhi"].to_numpy(),
        ambient_temp_c=df["t_amb"].to_numpy(),
        wind_speed_m_s=df["wind_ms"].to_numpy(),
        system_efficiency=SYSTEM_EFF, calibration=cal, ac_limit_w=AC_LIMIT_W, tz_offset_h=0.0,
    )
    p_best_all = p_best_all_kw * 1000.0

    best_h0, best_rmse = 2.0, float("inf")
    for h0 in [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
        y_train, p_train = [], []
        for horizon_h in [0.25, 1.0, 2.0, 4.0]:
            k = int(round(horizon_h * 60 / STEP_MIN)) - 1
            shift = k + 1
            w = float(np.exp(-horizon_h / h0))
            for t_target in np.where(train_mask)[0]:
                src = t_target - shift
                if src < 0:
                    continue
                htw = p_pvf[src, k] * P_PEAK_W
                pred = w * htw + (1.0 - w) * p_best_all[t_target]
                y_train.append(p_real_all[t_target])
                p_train.append(pred)
        rmse = metrics(np.array(y_train), np.array(p_train), "hybrid")["RMSE"]
        if rmse < best_rmse:
            best_h0, best_rmse = h0, rmse

    print("\n" + "=" * 78)
    print("B2) HYBRID-PROGNOSE (HTW + pvprog-best)")
    print(f"   (h0 auf Trainingsdaten optimiert: {best_h0:.1f} h)")
    print("=" * 78)
    for horizon_h in [0.25, 1.0, 2.0, 4.0, 8.0]:
        k = int(round(horizon_h * 60 / STEP_MIN)) - 1
        shift = k + 1
        w = float(np.exp(-horizon_h / best_h0))
        y_list, pred_list = [], []
        for t_target in np.where(test_mask)[0]:
            src = t_target - shift
            if src < 0:
                continue
            htw = p_pvf[src, k] * P_PEAK_W
            pred = w * htw + (1.0 - w) * p_best_all[t_target]
            y_list.append(p_real_all[t_target])
            pred_list.append(pred)
        m = metrics(np.array(y_list), np.array(pred_list), f"Hybrid (Horizont {horizon_h:.2f}h)")
        print(f"  {m['label']:50s}  MAE={m['MAE']:5.0f}W  RMSE={m['RMSE']:5.0f}W  "
              f"nRMSE={m['nRMSE_%']:5.2f}%  Bias={m['Bias']:+5.0f}W  R2={m['R2']:+.3f}")

    # --- Tagesenergie-Vergleich ---
    out = pd.DataFrame({
        "real_w": y_test, "iso": p_iso, "perez": p_per, "best": p_best,
    }, index=test_df.index)
    # HTW: Tagesprognose aus dem letzten sinnvollen Messzeitpunkt vor Tagesbeginn.
    # Um Mitternacht ist k_TF nachts 0; deshalb ist der Vortag-Abend die
    # korrekte Quelle und braucht einen Horizont > 24h bis 23:45.
    htw_day_ahead = np.full(len(test_df), np.nan)
    test_idx_arr = np.where(test_mask)[0]
    src_by_day = {
        day: latest_htw_source_before_day(df.index, p_pvf, day)
        for day in sorted(test_days)
    }
    for t_target in test_idx_arr:
        target_day = df.index[t_target].date()
        src = src_by_day.get(target_day)
        if src is None:
            continue
        k = t_target - src - 1
        if k >= p_pvf.shape[1]:
            continue
        # local index in test_df
        out_idx = np.searchsorted(test_idx_arr, t_target)
        htw_day_ahead[out_idx] = p_pvf[src, k] * P_PEAK_W
    out["htw_day_ahead"] = htw_day_ahead

    # Integration 15min -> kWh (mal 0.25h / 1000)
    daily = out.resample("1D").sum() * (STEP_MIN / 60.0) / 1000.0
    print("\n" + "=" * 78)
    print("C) TAGESENERGIE (kWh, Test-Set)")
    print("=" * 78)
    print(f"  Real Mittel:         {daily['real_w'].mean():5.1f} kWh  "
          f"(min {daily['real_w'].min():.1f}, max {daily['real_w'].max():.1f})")
    for col, lbl in [("iso", "EMOS iso   "), ("perez", "EMOS Perez "),
                     ("best", "pvprog-best"), ("htw_day_ahead", "HTW 24h-DA ")]:
        err = daily[col] - daily["real_w"]
        print(f"  {lbl}:        Mittel={daily[col].mean():5.1f}  "
              f"Tages-MAE={err.abs().mean():5.2f} kWh  Bias={err.mean():+5.2f} kWh")

    out.to_csv(ROOT / "data" / "eval_all_15min.csv")
    daily.to_csv(ROOT / "data" / "eval_all_daily.csv")
    print(f"\nGespeichert: data/eval_all_*.csv")
