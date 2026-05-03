"""Gemessene Haushalts-Lastprofile (kWh/15min, ein Jahr).

Vier vermessene Profile fuer typische Haushaltskonstellationen, jeweils
ohne Waermepumpenanteil. Daten liegen unter data/load_profiles/.

Format der CSVs:
    35040 Zeilen, eine Spalte, kein Header, kWh pro 15-min-Slot,
    Komma als Dezimaltrenner. Reihenfolge: 1. Jan 00:00 bis 31. Dez 23:45.

Aufrufer waehlt eine Profil-ID, einen Zieltag und (optional) einen
Ziel-Jahresverbrauch — der Loader liefert das Tagesprofil als kW-Array
in der gewuenschten zeitlichen Aufloesung, linear auf den gewaehlten
Jahresverbrauch skaliert.
"""

import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

# Verzeichnis mit den CSV-Dateien
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "load_profiles"

# Zentrales Verzeichnis: Profile fuer das Dropdown im Dashboard.
# label  = Anzeige im Dashboard
# file   = Dateiname unter data/load_profiles/
# annual = Jahresverbrauch des Originalprofils (kWh) — fuer die Skalierung
HOUSEHOLD_PROFILES = {
    "1person": {
        "label": "1 Person",
        "file": "1person_2287kwh.csv",
        "annual_kwh": 2287.0,
    },
    "2person": {
        "label": "2 Personen",
        "file": "2person_3304kwh.csv",
        "annual_kwh": 3304.0,
    },
    "2person_1kind": {
        "label": "2 Personen + 1 Kind",
        "file": "2person_1kind_3929kwh.csv",
        "annual_kwh": 3929.0,
    },
    "2person_2kinder": {
        "label": "2 Personen + 2 Kinder",
        "file": "2person_2kinder_4308kwh.csv",
        "annual_kwh": 4308.0,
    },
}

# Konstanten
_SLOTS_PER_DAY = 96  # 15-min Aufloesung im Original
_DAYS = 365


@lru_cache(maxsize=8)
def _load_full_year_kwh_per_slot(profile_id: str) -> np.ndarray:
    """Laedt das ganze Jahr (35040 Werte, kWh pro 15-min-Slot)."""
    if profile_id not in HOUSEHOLD_PROFILES:
        raise ValueError(
            f"Unbekanntes Haushaltsprofil '{profile_id}'. "
            f"Verfuegbar: {list(HOUSEHOLD_PROFILES)}"
        )

    fname = HOUSEHOLD_PROFILES[profile_id]["file"]
    path = _DATA_DIR / fname
    if not path.exists():
        raise FileNotFoundError(
            f"Profil-Datei nicht gefunden: {path}. "
            f"Stelle sicher, dass 'data/load_profiles/' existiert."
        )

    values = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            values.append(float(line.replace(",", ".")))

    arr = np.asarray(values, dtype=float)
    if arr.size != _SLOTS_PER_DAY * _DAYS:
        raise ValueError(
            f"Profil '{profile_id}' hat {arr.size} Werte, "
            f"erwartet {_SLOTS_PER_DAY * _DAYS}."
        )
    return arr


def _day_of_year_index(date: datetime.date) -> int:
    """Liefert den Tagesindex 0..364 (29. Februar wird auf 28. Feb. abgebildet)."""
    doy = date.timetuple().tm_yday  # 1..366
    if doy > _DAYS:
        doy = _DAYS  # Schaltjahr-Schutz
    return doy - 1


def _resample_kwh_per_slot(slot_kwh: np.ndarray, target_steps: int) -> np.ndarray:
    """Resamplet ein 96er Tagesprofil (kWh pro 15min) auf target_steps Schritte (kW).

    Nur fuer Schrittweiten gedacht, die ein ganzzahliges Vielfaches/
    Bruchteil von 15 Minuten sind (also 15, 30, 60 min, oder 5/15 min …).
    """
    src_steps = len(slot_kwh)
    src_dt_h = 24.0 / src_steps
    src_kw = slot_kwh / src_dt_h  # kWh pro Slot -> mittlere kW im Slot

    if target_steps == src_steps:
        return src_kw

    if target_steps < src_steps and src_steps % target_steps == 0:
        # Aggregieren: mehrere Quellslots zu einem Zielslot mitteln
        group = src_steps // target_steps
        return src_kw.reshape(target_steps, group).mean(axis=1)

    if target_steps > src_steps and target_steps % src_steps == 0:
        # Hochsamplen: Wert wiederholen (stueckweise konstant)
        repeat = target_steps // src_steps
        return np.repeat(src_kw, repeat)

    # Unsauberer Faktor → linear interpolieren auf den Slot-Mittelpunkten
    src_centers = (np.arange(src_steps) + 0.5) / src_steps
    tgt_centers = (np.arange(target_steps) + 0.5) / target_steps
    return np.interp(tgt_centers, src_centers, src_kw)


def list_profiles() -> list[tuple[str, str, float]]:
    """Liefert die Profile als (id, label, annual_kwh)-Liste fuer das Dashboard."""
    return [
        (pid, p["label"], p["annual_kwh"])
        for pid, p in HOUSEHOLD_PROFILES.items()
    ]


def get_profile_label(profile_id: str) -> str:
    """Anzeigename eines Profils (Fallback: ID selbst)."""
    return HOUSEHOLD_PROFILES.get(profile_id, {}).get("label", profile_id)


def load_household_profile(
    profile_id: str,
    target_date: datetime.date,
    num_steps: int = 96,
    target_annual_kwh: Optional[float] = None,
) -> np.ndarray:
    """Liefert das Tageslastprofil (kW) fuer den gewuenschten Tag.

    Args:
        profile_id: Schluessel aus HOUSEHOLD_PROFILES (z.B. '1person').
        target_date: Zieltag der Optimierung.
        num_steps: Zeitschritte pro Tag (96 fuer 15min, 24 fuer 60min).
        target_annual_kwh: Wenn gesetzt, linear hoch-/runterskaliert auf
            diesen Jahresverbrauch. Default = Original-Jahreswert
            des gewaehlten Profils.

    Returns:
        Numpy-Array mit num_steps Werten in kW.
    """
    full_year = _load_full_year_kwh_per_slot(profile_id)
    base_annual = HOUSEHOLD_PROFILES[profile_id]["annual_kwh"]

    # Tagesausschnitt herausschneiden
    doy_idx = _day_of_year_index(target_date)
    start = doy_idx * _SLOTS_PER_DAY
    day_slot_kwh = full_year[start: start + _SLOTS_PER_DAY]

    # Zeitliche Aufloesung anpassen (96 → num_steps)
    profile_kw = _resample_kwh_per_slot(day_slot_kwh, num_steps)

    # Skalierung auf den gewuenschten Jahresverbrauch
    if target_annual_kwh is not None and target_annual_kwh > 0 and base_annual > 0:
        scale = target_annual_kwh / base_annual
        profile_kw = profile_kw * scale

    return np.round(profile_kw, 4)
