"""Last- und Waermebedarfsprofile generieren und importieren."""

import datetime
import io
from typing import Optional, Union

import numpy as np
import pandas as pd


def generate_load_profile(
    annual_kwh: float,
    date: datetime.date,
    num_steps: int = 96,
) -> np.ndarray:
    """Generiert ein synthetisches Haushaltslastprofil.

    Erzeugt ein realistisches Tagesprofil mit niedrigem Verbrauch nachts,
    Morgen-Peak (6-9h), Mittagspeak (12-13h) und Abend-Peak (17-21h).
    Am Wochenende sind die Peaks verschoben und die Grundlast hoeher.

    Args:
        annual_kwh: Jahresverbrauch in kWh.
        date: Datum (bestimmt Wochentag/Wochenende und Seed).
        num_steps: Anzahl Zeitschritte (Standard: 96 = 15-min fuer 24h).

    Returns:
        Array mit Lastleistung in kW pro Zeitschritt.
    """
    hours = np.linspace(0, 24, num_steps, endpoint=False)
    rng = np.random.default_rng(seed=int(date.strftime("%Y%m%d")) + 42)

    # Tagesdurchschnittsleistung
    daily_kwh = annual_kwh / 365
    avg_power = daily_kwh / 24  # kW

    is_weekend = date.weekday() >= 5  # Sa=5, So=6

    if is_weekend:
        # Wochenende: spaetere Peaks, hoehere Grundlast
        profile = np.ones(num_steps) * 0.4  # Hoehere Grundlast
        # Spaeterer Morgen-Peak (8-11)
        profile += 1.0 * np.exp(-0.5 * ((hours - 9.5) / 1.5) ** 2)
        # Mittag (12-14)
        profile += 0.8 * np.exp(-0.5 * ((hours - 13) / 1.0) ** 2)
        # Abend-Peak (17-22) – breiter und hoeher
        profile += 1.6 * np.exp(-0.5 * ((hours - 19.5) / 2.0) ** 2)
    else:
        # Werktag: fruehe Peaks, niedrigere Grundlast
        profile = np.ones(num_steps) * 0.3  # Grundlast-Faktor
        # Morgen-Peak (6-9)
        profile += 1.2 * np.exp(-0.5 * ((hours - 7) / 1.0) ** 2)
        # Mittag (12-13)
        profile += 0.6 * np.exp(-0.5 * ((hours - 12.5) / 0.8) ** 2)
        # Abend-Peak (17-21)
        profile += 1.5 * np.exp(-0.5 * ((hours - 19) / 1.5) ** 2)

    # Auf Tagesverbrauch normieren
    step_hours = 24 / num_steps
    total_energy = np.sum(profile) * step_hours
    profile = profile * (daily_kwh / total_energy)

    # Rauschen hinzufuegen
    profile += rng.normal(0, avg_power * 0.05, num_steps)
    profile = np.clip(profile, 0.05, None)

    return np.round(profile, 3)


# ================================================================
# CSV-Import und Lastgang-Prognose
# ================================================================


def _get_day_type(date: datetime.date) -> str:
    """Tagestyp: 'wd' (Werktag), 'sa' (Samstag), 'su' (Sonntag)."""
    wd = date.weekday()
    if wd < 5:
        return "wd"
    elif wd == 5:
        return "sa"
    return "su"


_DAY_TYPE_LABELS = {"wd": "Werktag", "sa": "Samstag", "su": "Sonntag"}


def parse_csv_load_profile(
    csv_data: Union[str, bytes, io.BytesIO],
) -> pd.DataFrame:
    """Parst eine CSV-Datei mit Lastgangdaten.

    Erkennt automatisch Trennzeichen, Dezimalformat und Einheit.

    Returns:
        DataFrame mit Spalten 'timestamp' (tz-aware datetime) und 'power_kw'.
    """
    df = _parse_csv(csv_data)
    power_kw = _extract_power(df)
    timestamps = _extract_timestamps(df)

    if timestamps is None or len(timestamps) != len(power_kw):
        raise ValueError(
            "CSV muss eine Zeitstempel-Spalte enthalten "
            "(z.B. 'Zeitstempel', 'Datum', 'Time')."
        )

    result = pd.DataFrame({"timestamp": timestamps, "power_kw": power_kw})
    result["power_kw"] = result["power_kw"].clip(lower=0.0)
    result = result.sort_values("timestamp").reset_index(drop=True)
    return result


def get_csv_info(csv_df: pd.DataFrame) -> dict:
    """Gibt Metadaten ueber den importierten Lastgang zurueck.

    Returns:
        Dict mit: start_date, end_date, num_days, num_rows,
        complete_days (list[date]), day_type_counts.
    """
    csv_df = csv_df.copy()
    csv_df["date"] = csv_df["timestamp"].dt.date
    day_counts = csv_df.groupby("date").size()
    complete_days = sorted(day_counts[day_counts >= 80].index.tolist())

    type_counts = {"wd": 0, "sa": 0, "su": 0}
    for d in complete_days:
        type_counts[_get_day_type(d)] += 1

    return {
        "start_date": csv_df["timestamp"].min().date(),
        "end_date": csv_df["timestamp"].max().date(),
        "num_rows": len(csv_df),
        "num_days": len(complete_days),
        "complete_days": complete_days,
        "day_type_counts": type_counts,
    }


def forecast_load_profile(
    csv_df: pd.DataFrame,
    target_date: datetime.date,
    num_steps: int = 96,
) -> tuple[np.ndarray, dict]:
    """Prognostiziert ein 15-min-Lastprofil fuer den Zieltag.

    Strategie mit Fallback-Kette:
    1. Gleicher Tagestyp (wd/sa/su) + gleicher Monat
    2. Gleicher Tagestyp + benachbarter Monat (+/- 1)
    3. Gleicher Tagestyp beliebiger Monat
    4. Alle vollstaendigen Tage

    Pro 15-min-Slot wird der Durchschnitt aller passenden Tage gebildet.

    Args:
        csv_df: DataFrame von parse_csv_load_profile().
        target_date: Zieltag fuer die Prognose.
        num_steps: Anzahl Zeitschritte (Standard: 96).

    Returns:
        Tuple aus:
        - Array mit prognostizierter Last in kW (Laenge = num_steps)
        - Info-Dict mit: used_days (int), match_level (str), day_type (str)
    """
    csv_df = csv_df.copy()
    csv_df["date"] = csv_df["timestamp"].dt.date
    csv_df["slot"] = (
        csv_df["timestamp"].dt.hour * (num_steps // 24)
        + csv_df["timestamp"].dt.minute // (1440 // num_steps)
    ).clip(upper=num_steps - 1)

    target_type = _get_day_type(target_date)
    target_month = target_date.month

    # Vollstaendige Tage identifizieren (mind. 80 von 96 Slots)
    day_counts = csv_df.groupby("date").size()
    complete_dates = set(day_counts[day_counts >= 80].index)
    df = csv_df[csv_df["date"].isin(complete_dates)].copy()
    df["day_type"] = df["date"].apply(_get_day_type)
    df["month"] = df["date"].apply(lambda d: d.month)

    # Fallback-Kette
    match_level = ""
    for level, mask_fn in [
        ("Typ+Monat", lambda r: (r["day_type"] == target_type) & (r["month"] == target_month)),
        ("Typ+Nachbarmonat", lambda r: (r["day_type"] == target_type) & (r["month"].isin([
            target_month, (target_month % 12) + 1, ((target_month - 2) % 12) + 1
        ]))),
        ("Typ", lambda r: r["day_type"] == target_type),
        ("Alle Tage", lambda r: pd.Series(True, index=r.index)),
    ]:
        mask = mask_fn(df)
        subset = df[mask]
        if not subset.empty:
            match_level = level
            break

    if subset.empty:
        # Kein einziger vollstaendiger Tag: Nullprofil
        return np.zeros(num_steps), {
            "used_days": 0, "match_level": "Keine Daten", "day_type": target_type,
        }

    # Pro Slot mitteln
    slot_means = subset.groupby("slot")["power_kw"].mean()
    profile = np.zeros(num_steps)
    for slot_idx, mean_val in slot_means.items():
        if 0 <= slot_idx < num_steps:
            profile[slot_idx] = mean_val

    # Luecken interpolieren
    filled = np.array([s in slot_means.index for s in range(num_steps)])
    if not filled.all() and filled.any():
        x_known = np.where(filled)[0]
        x_all = np.arange(num_steps)
        profile = np.interp(x_all, x_known, profile[x_known])

    used_days = subset["date"].nunique()

    info = {
        "used_days": used_days,
        "match_level": match_level,
        "day_type": _DAY_TYPE_LABELS.get(target_type, target_type),
    }
    return np.clip(np.round(profile, 3), 0.0, None), info


def load_csv_profile(
    csv_data: Union[str, bytes, io.BytesIO],
    target_date: datetime.date,
    num_steps: int = 96,
    includes_heat_pump: bool = False,
    hp_annual_kwh: float = 0.0,
    outside_temp: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Importiert einen Lastgang aus CSV und prognostiziert den Zieltag.

    Args:
        csv_data: CSV-Inhalt als String, Bytes oder BytesIO.
        target_date: Zieltag fuer die Optimierung.
        num_steps: Gewuenschte Anzahl Zeitschritte (Standard: 96).
        includes_heat_pump: Ob der Lastgang den WP-Verbrauch enthaelt.
        hp_annual_kwh: Geschaetzter Jahres-WP-Verbrauch.
        outside_temp: Aussentemperatur am Zieltag (fuer WP-Subtraktion).

    Returns:
        Array mit Lastleistung in kW, Laenge = num_steps.
    """
    csv_df = parse_csv_load_profile(csv_data)
    power_kw, _ = forecast_load_profile(csv_df, target_date, num_steps)

    # WP-Anteil herausrechnen falls noetig
    if includes_heat_pump and hp_annual_kwh > 0:
        hp_profile = _estimate_hp_profile(hp_annual_kwh, target_date, num_steps, outside_temp)
        power_kw = np.clip(power_kw - hp_profile, 0.05, None)

    return np.round(power_kw, 3)


# ================================================================
# CSV-Parsing Hilfsfunktionen
# ================================================================


def _parse_csv(csv_data: Union[str, bytes, io.BytesIO]) -> pd.DataFrame:
    """Parst CSV mit automatischer Erkennung von Trennzeichen und Dezimalformat."""
    if isinstance(csv_data, bytes):
        csv_data = io.BytesIO(csv_data)
    elif isinstance(csv_data, str):
        csv_data = io.StringIO(csv_data)

    raw = csv_data.read() if hasattr(csv_data, "read") else csv_data
    if isinstance(raw, bytes):
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                raw_str = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raw_str = raw.decode("utf-8", errors="replace")
    else:
        raw_str = raw

    first_lines = raw_str[:2000]
    sep = ";" if first_lines.count(";") > first_lines.count(",") else ","
    decimal = "," if sep == ";" else "."

    try:
        df = pd.read_csv(io.StringIO(raw_str), sep=sep, decimal=decimal)
    except Exception:
        alt_decimal = "." if decimal == "," else ","
        df = pd.read_csv(io.StringIO(raw_str), sep=sep, decimal=alt_decimal)

    return df


def _extract_power(df: pd.DataFrame) -> np.ndarray:
    """Extrahiert Leistungswerte (kW) aus DataFrame."""
    power_col = None
    for col in df.columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in ["leistung", "power", "kw", "verbrauch", "load", "last", "watt"]):
            power_col = col
            break

    if power_col is None:
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                power_col = col
                break

    if power_col is None:
        raise ValueError("Keine Leistungsspalte in CSV gefunden.")

    values = pd.to_numeric(df[power_col], errors="coerce").fillna(0).values

    col_lower = power_col.lower()
    if "kwh" in col_lower or "energy" in col_lower or "energie" in col_lower:
        step_h = 24.0 / len(values) if len(values) > 0 else 0.25
        values = values / step_h

    if "kw" not in col_lower:
        if ("watt" in col_lower
            or col_lower.endswith("_w")
            or col_lower.endswith("(w)")
            or col_lower.endswith("[w]")
            or col_lower.endswith(" w")):
            values = values / 1000.0

    return values.astype(float)


def _extract_timestamps(df: pd.DataFrame) -> Optional[pd.DatetimeIndex]:
    """Versucht Zeitstempel aus der CSV zu extrahieren."""
    for col in df.columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in ["zeit", "time", "datum", "date", "timestamp"]):
            try:
                return pd.to_datetime(df[col], dayfirst=True, format="mixed", utc=True)
            except Exception:
                try:
                    return pd.to_datetime(df[col], dayfirst=True, format="mixed")
                except Exception:
                    continue
    return None


def _estimate_hp_profile(
    hp_annual_kwh: float,
    date: datetime.date,
    num_steps: int,
    outside_temp: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Schaetzt ein Waermepumpen-Lastprofil fuer die Subtraktion."""
    hours = np.linspace(0, 24, num_steps, endpoint=False)
    month = date.month

    heating_factors = {
        1: 1.4, 2: 1.3, 3: 1.0, 4: 0.6, 5: 0.2, 6: 0.05,
        7: 0.0, 8: 0.0, 9: 0.1, 10: 0.5, 11: 1.0, 12: 1.3,
    }
    factor = heating_factors.get(month, 0.5)
    factor_sum = sum(heating_factors.values())
    daily_kwh = hp_annual_kwh / 365 * factor * 12 / factor_sum

    if daily_kwh < 0.01:
        return np.zeros(num_steps)

    profile = np.ones(num_steps) * 0.3
    profile += 0.8 * np.exp(-0.5 * ((hours - 7) / 2.0) ** 2)
    profile += 1.0 * np.exp(-0.5 * ((hours - 19) / 2.5) ** 2)

    if outside_temp is not None:
        temp_factor = np.clip((18 - outside_temp) / 18, 0, 2)
        profile *= temp_factor

    step_hours = 24 / num_steps
    total = np.sum(profile) * step_hours
    if total > 0:
        profile = profile * (daily_kwh / total)

    return np.clip(profile, 0, None)


def generate_heat_demand_profile(
    annual_kwh: float,
    date: datetime.date,
    num_steps: int = 96,
    outside_temp: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Generiert ein Heizwaermebedarf-Profil basierend auf Heizgradtagen.

    Verwendet monatliche Heizgradtag-Faktoren zur saisonalen Verteilung.
    Optional kann die Aussentemperatur den Bedarf modulieren.

    Args:
        annual_kwh: Jahresheizwaermebedarf in kWh.
        date: Datum (bestimmt Monat/Saison und Seed).
        num_steps: Anzahl Zeitschritte (Standard: 96 = 15-min fuer 24h).
        outside_temp: Aussentemperatur-Array in Grad C (optional).
                      Falls angegeben, wird der Bedarf temperaturabhaengig skaliert.

    Returns:
        Array mit thermischer Leistung in kW pro Zeitschritt.
    """
    hours = np.linspace(0, 24, num_steps, endpoint=False)
    month = date.month

    # Monatliche Heizgradtag-Faktoren (typisch fuer Deutschland)
    heating_factors = {
        1: 1.4, 2: 1.3, 3: 1.0, 4: 0.6, 5: 0.2, 6: 0.05,
        7: 0.0, 8: 0.0, 9: 0.1, 10: 0.5, 11: 1.0, 12: 1.3,
    }
    seasonal_factor = heating_factors.get(month, 0.5)
    factor_sum = sum(heating_factors.values())

    # Tagesverbrauch unter Beruecksichtigung der saisonalen Verteilung
    daily_kwh = annual_kwh / 365 * seasonal_factor * 12 / factor_sum

    if daily_kwh < 0.01:
        return np.zeros(num_steps)

    # Tagesprofil: Morgen- und Abend-Peaks
    profile = np.ones(num_steps) * 0.2
    # Morgen-Peak (6-9h): Aufheizen nach Nachtabsenkung
    profile += 0.8 * np.exp(-0.5 * ((hours - 7) / 2.0) ** 2)
    # Abend-Peak (17-21h): Erhoehter Bedarf abends
    profile += 1.0 * np.exp(-0.5 * ((hours - 19) / 2.5) ** 2)

    # Temperaturabhaengige Modulation
    if outside_temp is not None:
        # Heizgrenztemperatur 18 Grad C
        temp_factor = np.clip((18 - outside_temp) / 18, 0, 2)
        profile *= temp_factor

    # Auf Tagesverbrauch normieren
    step_hours = 24 / num_steps
    total = np.sum(profile) * step_hours
    if total > 0:
        profile = profile * (daily_kwh / total)

    return np.round(np.clip(profile, 0, None), 3)


def generate_hot_water_profile(
    annual_kwh: float,
    date: datetime.date,
    num_steps: int = 96,
) -> np.ndarray:
    """Generiert ein Warmwasserbedarf-Profil.

    Warmwasserbedarf ist relativ gleichmaessig ueber das Jahr verteilt
    mit leicht erhoehtem Bedarf im Winter. Das Tagesprofil zeigt
    Morgen-Peak (6-8h, Duschen) und Abend-Peak (18-20h).

    Args:
        annual_kwh: Jahreswarmwasserbedarf in kWh.
        date: Datum (bestimmt Saison und Seed).
        num_steps: Anzahl Zeitschritte (Standard: 96 = 15-min fuer 24h).

    Returns:
        Array mit thermischer Leistung in kW pro Zeitschritt.
    """
    hours = np.linspace(0, 24, num_steps, endpoint=False)
    rng = np.random.default_rng(seed=int(date.strftime("%Y%m%d")) + 99)

    month = date.month

    # Leichte saisonale Variation: Winter etwas mehr, Sommer etwas weniger
    seasonal_factors = {
        1: 1.10, 2: 1.08, 3: 1.04, 4: 1.00, 5: 0.96, 6: 0.92,
        7: 0.90, 8: 0.90, 9: 0.94, 10: 1.00, 11: 1.06, 12: 1.10,
    }
    seasonal_factor = seasonal_factors.get(month, 1.0)

    # Tagesverbrauch
    daily_kwh = annual_kwh / 365 * seasonal_factor

    if daily_kwh < 0.01:
        return np.zeros(num_steps)

    # Tagesprofil mit Morgen- und Abend-Peaks
    profile = np.ones(num_steps) * 0.1  # Niedrige Grundlast (Zirkulation)
    # Morgen-Peak (6-8h): Duschen, Waschen
    profile += 1.5 * np.exp(-0.5 * ((hours - 7) / 1.0) ** 2)
    # Abend-Peak (18-20h): Duschen, Abwasch
    profile += 1.2 * np.exp(-0.5 * ((hours - 19) / 1.0) ** 2)
    # Kleiner Mittags-Peak (12-13h)
    profile += 0.3 * np.exp(-0.5 * ((hours - 12.5) / 0.8) ** 2)

    # Auf Tagesverbrauch normieren
    step_hours = 24 / num_steps
    total_energy = np.sum(profile) * step_hours
    if total_energy > 0:
        profile = profile * (daily_kwh / total_energy)

    # Leichtes Rauschen
    avg_power = daily_kwh / 24
    profile += rng.normal(0, avg_power * 0.03, num_steps)
    profile = np.clip(profile, 0, None)

    return np.round(profile, 3)
