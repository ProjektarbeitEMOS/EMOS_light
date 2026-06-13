"""Bester PV-Prognosealgorithmus fuer das EMOS-System.

Basis: Perez (1990) anisotropes Transpositionsmodell aus EMOS_light
       (Sieger im Vergleich gegen Liu&Jordan aus EMOS).

Erweiterungen gegenueber EMOS_light:
  1. Multi-Flaechen-Aggregation (Ost + West je mit eigenen kWp/Tilt/Azimut).
  2. Datenbasierte Kalibrierung: ein globaler Skalierungsfaktor `k` gleicht
     systematische Verluste aus, die das physikalische Modell ueberschaetzt
     (Verschmutzung, Reflexion, Modul-Missmatch, Teilverschattung, DC/AC-Verluste).
     k wird aus historischen Anlagendaten per OLS geschaetzt.
  3. Zenith-Gewichtung bei kt-Clipping (stabiler bei tiefem Sonnenstand).
  4. Bewoelkungs-Residualkorrektur optional (cloud_cover Feintuning).

Schnittstelle:
  pv_forecast(timestamps, weather_df, surfaces, latitude, longitude,
              calibration=None) -> np.ndarray  (kW je Zeitschritt)

Kalibrierung:
  calibrate_from_history(historical_df, surfaces, latitude, longitude)
              -> dict{"k": float, "bias_w": float}
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from algorithms.emos_light_solar_perez import (
    solar_position,
    ghi_to_poa,
    estimate_pv_power,
    estimate_cell_temperature,
    detect_timezone_offset,
)


@dataclass
class Surface:
    """Eine PV-Teilflaeche (z.B. ein Dachbereich)."""
    name: str
    kwp: float
    tilt_deg: float
    azimuth_deg: float   # 0=N, 90=O, 180=S, 270=W


@dataclass
class Calibration:
    """Datenbasierte Kalibrierungsparameter."""
    k: float           # Leistungs-Skalierungsfaktor (typ. 0.7-1.0)
    bias_w: float      # additiver Offset in W (selten noetig)
    n_samples: int     # Anzahl Stichproben bei der Kalibrierung
    rmse_w: float      # RMSE nach Kalibrierung
    clearness_edges: tuple[float, ...] | None = None
    clearness_k: tuple[float, ...] | None = None
    method: str = "energy_ratio"

    def apply(self, p_w: np.ndarray, clearness_index: np.ndarray | None = None) -> np.ndarray:
        factor = np.full_like(p_w, self.k, dtype=float)
        if (
            clearness_index is not None
            and self.clearness_edges is not None
            and self.clearness_k is not None
        ):
            edges = np.asarray(self.clearness_edges, dtype=float)
            factors = np.asarray(self.clearness_k, dtype=float)
            bin_idx = np.digitize(clearness_index, edges[1:-1], right=False)
            valid = (bin_idx >= 0) & (bin_idx < len(factors)) & np.isfinite(clearness_index)
            factor[valid] = factors[bin_idx[valid]]
        return np.maximum(p_w * factor + self.bias_w, 0.0)


def clearness_index(
    timestamps: Sequence[dt.datetime],
    ghi_w_m2: np.ndarray,
    latitude: float,
    longitude: float,
    tz_offset_h: float,
) -> np.ndarray:
    """Schaetzt kt = GHI / extraterrestrische Horizontalstrahlung."""
    local_ts = [ts.replace(tzinfo=None) if ts.tzinfo else ts for ts in timestamps]
    elev, _ = solar_position(local_ts, latitude, longitude, tz_offset_h)
    doy = np.array([ts.timetuple().tm_yday for ts in local_ts], dtype=float)
    ghi = np.asarray(ghi_w_m2, dtype=float)
    extra_normal = 1367.0 * (1.0 + 0.033 * np.cos(2.0 * math.pi * doy / 365.0))
    sin_elev = np.sin(np.radians(np.maximum(elev, 0.0)))
    extra_horizontal = extra_normal * sin_elev
    with np.errstate(divide="ignore", invalid="ignore"):
        kt = np.where(extra_horizontal > 50.0, ghi / extra_horizontal, np.nan)
    return np.clip(kt, 0.0, 1.5)


def _poa_for_surface(
    ghi: np.ndarray,
    dni: np.ndarray | None,
    dhi: np.ndarray | None,
    timestamps: Sequence[dt.datetime],
    latitude: float,
    longitude: float,
    surface: Surface,
    tz_offset_h: float,
    albedo: float,
) -> np.ndarray:
    """POA-Einstrahlung fuer eine einzelne Flaeche, Perez (1990)."""
    # Lokalzeit-Objekte (tzinfo entfernen) fuer solar_position
    local_ts = [ts.replace(tzinfo=None) if ts.tzinfo else ts for ts in timestamps]
    elev, az = solar_position(local_ts, latitude, longitude, tz_offset_h)

    doy_arr = np.array([ts.timetuple().tm_yday for ts in local_ts])
    poa = np.zeros(len(ghi))
    for d in np.unique(doy_arr):
        mask = doy_arr == d
        poa[mask] = ghi_to_poa(
            ghi[mask], elev[mask], az[mask],
            surface.tilt_deg, surface.azimuth_deg, albedo, int(d),
            dni_override=None if dni is None else dni[mask],
            dhi_override=None if dhi is None else dhi[mask],
        )
    return poa


def pv_forecast(
    timestamps: Sequence[dt.datetime],
    ghi_w_m2: np.ndarray,
    surfaces: Sequence[Surface],
    *,
    latitude: float,
    longitude: float,
    dni_w_m2: np.ndarray | None = None,
    dhi_w_m2: np.ndarray | None = None,
    ambient_temp_c: np.ndarray | None = None,
    wind_speed_m_s: np.ndarray | None = None,
    system_efficiency: float = 0.85,
    noct_c: float = 45.0,
    albedo: float = 0.2,
    temp_coefficient: float = -0.004,
    age_years: float = 0.0,
    degradation_rate_per_year: float = 0.005,
    calibration: Calibration | None = None,
    ac_limit_w: float | None = None,
    tz_offset_h: float | None = None,
) -> np.ndarray:
    """Prognostiziert die Gesamt-PV-Erzeugung (alle Flaechen summiert) in kW.

    Eingangsgroessen als stuendliche oder 15-Min-Reihen (beliebiges gleiches Raster).

    Args:
        timestamps: Zeitpunkte (UTC oder Lokalzeit; bei UTC tz_offset_h=0).
        ghi_w_m2: Globalstrahlung horizontal [W/m^2].
        surfaces: Liste der PV-Flaechen (mindestens eine).
        latitude, longitude: Anlagenstandort in Grad.
        dni_w_m2, dhi_w_m2: Direkte / diffuse Strahlung, wenn verfuegbar.
                            Sonst Fallback auf DISC-Dekomposition.
        ambient_temp_c, wind_speed_m_s: Umgebung (optional, verbessert Temperaturmodell).
        system_efficiency: Anfaengliche Annahme ueber Systemwirkungsgrad.
                           Mit Kalibrierung verliert dieser Parameter an Bedeutung.
        calibration: Optionales Calibration-Objekt. Wenn vorhanden, wird die
                     Prognose mit k und bias korrigiert.
        tz_offset_h: Zeitzonen-Offset. Default: automatisch MEZ/MESZ fuer DE.
                     Fuer UTC-timestamps: 0 setzen.

    Returns:
        Gesamtleistung in kW, Laenge = len(timestamps).
    """
    ghi = np.asarray(ghi_w_m2, dtype=float)
    n = len(ghi)
    dni = np.asarray(dni_w_m2, dtype=float) if dni_w_m2 is not None else None
    dhi = np.asarray(dhi_w_m2, dtype=float) if dhi_w_m2 is not None else None
    t_amb = np.asarray(ambient_temp_c, dtype=float) if ambient_temp_c is not None else None
    wind = np.asarray(wind_speed_m_s, dtype=float) if wind_speed_m_s is not None else None

    if tz_offset_h is None:
        first = timestamps[0]
        d = first.date() if hasattr(first, "date") else first
        tz_offset_h = detect_timezone_offset(d)

    total_kw = np.zeros(n)
    system_losses = 1.0 - system_efficiency
    degradation = (1.0 - degradation_rate_per_year) ** age_years

    for s in surfaces:
        poa = _poa_for_surface(
            ghi, dni, dhi, timestamps, latitude, longitude, s, tz_offset_h, albedo,
        )
        t_cell = None
        if t_amb is not None:
            t_cell = estimate_cell_temperature(t_amb, poa, wind, noct_c)
        p_kw = estimate_pv_power(
            poa, s.kwp,
            temp_coefficient=temp_coefficient,
            cell_temperature_c=t_cell,
            system_losses=system_losses,
        )
        total_kw += np.maximum(p_kw, 0.0) * degradation

    p_w = total_kw * 1000.0
    if calibration is not None:
        kt = None
        if calibration.clearness_edges is not None and calibration.clearness_k is not None:
            kt = clearness_index(timestamps, ghi, latitude, longitude, tz_offset_h)
        p_w = calibration.apply(p_w, kt)
    if ac_limit_w is not None and ac_limit_w > 0:
        p_w = np.minimum(p_w, ac_limit_w)
    return p_w / 1000.0


def calibrate_from_history(
    timestamps: Sequence[dt.datetime],
    ghi_w_m2: np.ndarray,
    real_generation_w: np.ndarray,
    surfaces: Sequence[Surface],
    *,
    latitude: float,
    longitude: float,
    dni_w_m2: np.ndarray | None = None,
    dhi_w_m2: np.ndarray | None = None,
    ambient_temp_c: np.ndarray | None = None,
    wind_speed_m_s: np.ndarray | None = None,
    method: str = "energy_ratio",
    min_power_w: float = 200.0,
    clearness_edges: Sequence[float] = (0.0, 0.35, 0.65, 0.9, 1.5),
    min_bin_samples: int = 40,
    **forecast_kwargs,
) -> Calibration:
    """Schaetzt Kalibrierungsparameter (k, bias) aus historischen Daten.

    Die physikalische Prognose ueberschaetzt systematisch (Verschmutzung,
    Modul-Missmatch, Teilverschattung, Wechselrichter-Clipping, DC-Verluste).
    Kalibrierung gleicht diese gebuendelten Verluste durch einen einzigen
    Faktor k aus.

    method:
      "energy_ratio" (robust, empfohlen):
           k = sum(p_real) / sum(p_pred) ueber Tagesstunden.
           Minimiert Tagesenergie-Bias, unempfindlich gegen Wolken-
           Ausreisser der Wetterprognose.
      "ols_through_origin":
           k = <x,y> / <x,x> (KQ ohne Offset). Minimiert Stunden-RMSE.
      "ols":
           p_real ≈ k * p_pred + bias  (nur wenn gross Offset begruendet).

    Returns:
        Calibration mit k, bias_w=0 (ausser method='ols'), RMSE-nach-Kalib.
    """
    p_phys_kw = pv_forecast(
        timestamps, ghi_w_m2, surfaces,
        latitude=latitude, longitude=longitude,
        dni_w_m2=dni_w_m2, dhi_w_m2=dhi_w_m2,
        ambient_temp_c=ambient_temp_c, wind_speed_m_s=wind_speed_m_s,
        calibration=None,
        **forecast_kwargs,
    )
    p_phys_w = p_phys_kw * 1000.0
    y = np.asarray(real_generation_w, dtype=float)
    mask = (~np.isnan(y)) & (~np.isnan(p_phys_w)) & (y > min_power_w)
    x = p_phys_w[mask]
    yy = y[mask]
    if len(x) < 30:
        raise ValueError(f"Zu wenige Kalibrierpunkte: {len(x)}")

    bias = 0.0
    kt = clearness_index(
        timestamps,
        ghi_w_m2,
        latitude,
        longitude,
        forecast_kwargs.get("tz_offset_h", 0.0),
    )
    kt_masked = kt[mask]
    clearness_tuple = None
    clearness_k_tuple = None
    if method == "energy_ratio":
        k = float(yy.sum() / x.sum()) if x.sum() > 0 else 1.0
    elif method == "ols_through_origin":
        k = float(np.dot(x, yy) / np.dot(x, x))
    elif method == "ols":
        A = np.column_stack([x, np.ones_like(x)])
        coef, *_ = np.linalg.lstsq(A, yy, rcond=None)
        k, bias = float(coef[0]), float(coef[1])
    elif method == "clearness_bins":
        k = float(yy.sum() / x.sum()) if x.sum() > 0 else 1.0
        edges = np.asarray(clearness_edges, dtype=float)
        bin_factors = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            b = (kt_masked >= lo) & (kt_masked < hi)
            if b.sum() >= min_bin_samples and x[b].sum() > 0:
                kb = float(yy[b].sum() / x[b].sum())
                bin_factors.append(float(np.clip(kb, 0.45, 1.25)))
            else:
                bin_factors.append(k)
        clearness_tuple = tuple(float(v) for v in edges)
        clearness_k_tuple = tuple(bin_factors)
    else:
        raise ValueError(f"Unknown method: {method}")

    if clearness_k_tuple is not None:
        tmp = Calibration(
            k=k, bias_w=bias, n_samples=int(mask.sum()), rmse_w=0.0,
            clearness_edges=clearness_tuple, clearness_k=clearness_k_tuple,
        )
        p_cal = tmp.apply(x, kt_masked)
    else:
        p_cal = k * x + bias
    rmse = float(np.sqrt(np.mean((p_cal - yy) ** 2)))
    return Calibration(
        k=k, bias_w=bias, n_samples=int(mask.sum()), rmse_w=rmse,
        clearness_edges=clearness_tuple, clearness_k=clearness_k_tuple,
        method=method,
    )


def _calibration_score(y_w: np.ndarray, pred_w: np.ndarray) -> float:
    mask = np.isfinite(y_w) & np.isfinite(pred_w) & (y_w > 200.0)
    if mask.sum() == 0:
        return float("inf")
    err = pred_w[mask] - y_w[mask]
    mae = float(np.mean(np.abs(err)))
    bias = abs(float(np.mean(err)))
    return mae + 0.15 * bias


def calibrate_best_from_history(
    timestamps: Sequence[dt.datetime],
    ghi_w_m2: np.ndarray,
    real_generation_w: np.ndarray,
    surfaces: Sequence[Surface],
    *,
    latitude: float,
    longitude: float,
    dni_w_m2: np.ndarray | None = None,
    dhi_w_m2: np.ndarray | None = None,
    ambient_temp_c: np.ndarray | None = None,
    wind_speed_m_s: np.ndarray | None = None,
    candidate_methods: Sequence[str] = ("energy_ratio", "clearness_bins"),
    min_complex_improvement: float = 0.08,
    **forecast_kwargs,
) -> Calibration:
    """Waehlt die beste Kalibrierart auf einem Validierungsfenster aus.

    Danach wird die gewaehlte Methode auf der kompletten Historie neu kalibriert.
    Das verhindert, dass eine komplexere Kalibrierung aktiviert wird, obwohl sie
    fuer die konkrete Anlage / Datenlage schlechter ist.
    """
    dates = np.array([ts.date() if hasattr(ts, "date") else ts for ts in timestamps])
    unique_days = np.array(sorted(set(dates)))
    if len(unique_days) < 6:
        return calibrate_from_history(
            timestamps, ghi_w_m2, real_generation_w, surfaces,
            latitude=latitude, longitude=longitude,
            dni_w_m2=dni_w_m2, dhi_w_m2=dhi_w_m2,
            ambient_temp_c=ambient_temp_c, wind_speed_m_s=wind_speed_m_s,
            method=candidate_methods[0], **forecast_kwargs,
        )

    split = max(1, int(len(unique_days) * 0.75))
    train_days = set(unique_days[:split])
    val_mask = np.array([d not in train_days for d in dates])
    train_mask = ~val_mask

    arrays = {
        "ghi_w_m2": np.asarray(ghi_w_m2),
        "real_generation_w": np.asarray(real_generation_w),
        "dni_w_m2": None if dni_w_m2 is None else np.asarray(dni_w_m2),
        "dhi_w_m2": None if dhi_w_m2 is None else np.asarray(dhi_w_m2),
        "ambient_temp_c": None if ambient_temp_c is None else np.asarray(ambient_temp_c),
        "wind_speed_m_s": None if wind_speed_m_s is None else np.asarray(wind_speed_m_s),
    }
    ts_arr = np.asarray(list(timestamps), dtype=object)

    base_method = candidate_methods[0]
    base_score = None
    best_method = base_method
    best_score = float("inf")
    for method in candidate_methods:
        cal = calibrate_from_history(
            ts_arr[train_mask].tolist(),
            arrays["ghi_w_m2"][train_mask],
            arrays["real_generation_w"][train_mask],
            surfaces,
            latitude=latitude, longitude=longitude,
            dni_w_m2=None if arrays["dni_w_m2"] is None else arrays["dni_w_m2"][train_mask],
            dhi_w_m2=None if arrays["dhi_w_m2"] is None else arrays["dhi_w_m2"][train_mask],
            ambient_temp_c=None if arrays["ambient_temp_c"] is None else arrays["ambient_temp_c"][train_mask],
            wind_speed_m_s=None if arrays["wind_speed_m_s"] is None else arrays["wind_speed_m_s"][train_mask],
            method=method,
            **forecast_kwargs,
        )
        pred = pv_forecast(
            ts_arr[val_mask].tolist(),
            arrays["ghi_w_m2"][val_mask],
            surfaces,
            latitude=latitude, longitude=longitude,
            dni_w_m2=None if arrays["dni_w_m2"] is None else arrays["dni_w_m2"][val_mask],
            dhi_w_m2=None if arrays["dhi_w_m2"] is None else arrays["dhi_w_m2"][val_mask],
            ambient_temp_c=None if arrays["ambient_temp_c"] is None else arrays["ambient_temp_c"][val_mask],
            wind_speed_m_s=None if arrays["wind_speed_m_s"] is None else arrays["wind_speed_m_s"][val_mask],
            calibration=cal,
            **forecast_kwargs,
        ) * 1000.0
        score = _calibration_score(arrays["real_generation_w"][val_mask], pred)
        if method == base_method:
            base_score = score
        if score < best_score:
            best_method = method
            best_score = score

    if best_method != base_method and base_score is not None:
        required_score = base_score * (1.0 - min_complex_improvement)
        if best_score > required_score:
            best_method = base_method

    return calibrate_from_history(
        timestamps, ghi_w_m2, real_generation_w, surfaces,
        latitude=latitude, longitude=longitude,
        dni_w_m2=dni_w_m2, dhi_w_m2=dhi_w_m2,
        ambient_temp_c=ambient_temp_c, wind_speed_m_s=wind_speed_m_s,
        method=best_method, **forecast_kwargs,
    )
