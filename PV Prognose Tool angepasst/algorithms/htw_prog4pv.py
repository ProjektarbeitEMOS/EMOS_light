"""Python-Port der HTW-Berlin-PV-Prognose `prog4pv` (Bergner et al. 2016, v1.1).

Original (MATLAB): pvprog.m, Funktion prog4pv(time, p_pv, tf_past, tf_prog).
Quelle: J. Bergner, J. Weniger, T. Tjaden, V. Quaschning (2015/2016), HTW Berlin.

Funktionsweise (messwertbasierte Persistenz-Prognose, OHNE Wetterdaten):

  1. Aus den letzten `d` Tagen (max. 10) wird die Tages-Maximal-Leistungskurve
     `p_pvmax(t)` elementweise bestimmt (Klarhimmel-Huellkurve, spezifisch in
     kW/kWp).
  2. Im Rueckblick-Zeitfenster `tf_past` wird das Verhaeltnis der tatsaechlich
     erzeugten PV-Energie zur maximal moeglichen (k_TF, Wetterlage-Index) gebildet.
  3. Die Prognose fuer jeden Schritt im Horizont `tf_prog` ist:
         p_pvf(t+h) = k_TF(t) * p_pvmax(t+h)

Anpassung: Original arbeitet auf 1-min-Daten, intern auf 15-min-Mittel.
Hier auf beliebiges regulaeres Raster (`step_min`) verallgemeinert.
"""
from __future__ import annotations

import numpy as np


def prog4pv(
    p_pv_spec: np.ndarray,
    *,
    step_min: int = 15,
    tf_past_min: float = 30.0,
    tf_prog_h: float = 4.0,
    lookback_days: int = 10,
) -> np.ndarray:
    """Rollende messwertbasierte PV-Prognose (HTW Berlin).

    Args:
        p_pv_spec: Spezifische PV-Leistung (kW/kWp, 0..1), aequidistantes Raster.
        step_min:  Schrittweite der Zeitreihe in Minuten (Default 15).
        tf_past_min: Rueckblickzeitfenster in Minuten (Default 30).
        tf_prog_h:  Prognosehorizont in Stunden (Default 4).
        lookback_days: Anzahl Tage fuer p_pvmax (Default 10).

    Returns:
        p_pvf: 2D-Array [n_steps, horizon_steps]. p_pvf[t, h] ist die zum
               Zeitpunkt t abgegebene Prognose fuer Zeitpunkt t + (h+1)*step_min.
               Nachtstellen / Startphase sind 0.
    """
    p = np.asarray(p_pv_spec, dtype=float).copy()
    p = np.clip(p, 0.0, None)

    n = len(p)
    steps_per_day = int(round(1440 / step_min))
    horizon_steps = int(round(tf_prog_h * 60 / step_min))
    past_steps = max(1, int(round(tf_past_min / step_min)))

    # --- 1) p_pvmax: Tages-Huellkurve der letzten `lookback_days` Tage ---
    p_pvmax = np.zeros(n)
    for day_start in range(0, n - steps_per_day, steps_per_day):
        d = min(day_start // steps_per_day, lookback_days)
        if d < 1:
            # Am Anfang: noch keine Historie; p_pvmax bleibt 0
            continue
        past_start = day_start - d * steps_per_day
        past = p[past_start:day_start].reshape(d, steps_per_day)
        # Envelope: maximaler Tageswert je Tageszeitschritt ueber die letzten d Tage
        envelope = np.max(past, axis=0)
        p_pvmax[day_start:day_start + steps_per_day] = envelope

    # --- 2) k_TF (Wetterlage-Index) nur ueber Tag-Stellen (p_pv > 0) ---
    night = p <= 0
    day_idx = np.where(~night)[0]
    p_day = p[day_idx]
    pmax_day = p_pvmax[day_idx]

    k_TF = np.zeros(n)
    if len(p_day) > past_steps:
        E_past = np.zeros(len(p_day))
        E_max = np.zeros(len(p_day))
        for t in range(past_steps, len(p_day)):
            E_past[t] = p_day[t - past_steps:t].sum()
            E_max[t] = pmax_day[t - past_steps:t].sum()
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(E_max > 0, E_past / E_max, 0.0)
        ratio = np.clip(ratio, 0.0, 1.0)
        k_TF[day_idx] = ratio

    # --- 3) Prognose: p_pvmax zweimal verketten (Wrap-around am Jahresende) ---
    p_pvmax_rep = np.concatenate([p_pvmax, p_pvmax])
    p_pvf = np.zeros((n, horizon_steps))
    for t in range(n):
        if k_TF[t] <= 0:
            continue  # Nacht oder Aufbauphase -> Prognose bleibt 0
        # Prognose fuer t+1 .. t+horizon_steps
        env = p_pvmax_rep[t + 1:t + 1 + horizon_steps]
        p_pvf[t, :] = np.clip(k_TF[t] * env, 0.0, 1.0)

    # NaN-Sicherung
    p_pvf = np.nan_to_num(p_pvf, nan=0.0)
    return p_pvf
