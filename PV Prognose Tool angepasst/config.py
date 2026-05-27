"""Gemeinsame Projektkonfiguration.

Werte koennen per Umgebungsvariable ueberschrieben werden. Dadurch bleiben
Skripte portabel und Zugangsdaten muessen nicht im Code stehen.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw in (None, "") else float(raw)


def _date_env(name: str, default: dt.date) -> dt.date:
    raw = os.getenv(name)
    return default if raw in (None, "") else dt.date.fromisoformat(raw)


INFLUX_URL = os.getenv("PV_INFLUX_URL", "http://192.168.178.36:8086")
INFLUX_TOKEN = os.getenv("PV_INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("PV_INFLUX_ORG", "private")
INFLUX_BUCKET = os.getenv("PV_INFLUX_BUCKET", "pvdaten")

LATITUDE = _float_env("PV_LATITUDE", 48.52)
LONGITUDE = _float_env("PV_LONGITUDE", 13.30)
AC_LIMIT_W = _float_env("PV_AC_LIMIT_W", 0.0) or None

# Open-Meteo Archive hat typischerweise 1-2 Tage Verzug.
ARCHIVE_END_DATE = _date_env(
    "PV_ARCHIVE_END_DATE",
    dt.date.today() - dt.timedelta(days=2),
)
ARCHIVE_DAYS = int(os.getenv("PV_ARCHIVE_DAYS", "30"))
ARCHIVE_START_DATE = _date_env(
    "PV_ARCHIVE_START_DATE",
    ARCHIVE_END_DATE - dt.timedelta(days=ARCHIVE_DAYS),
)

PROJECT_ROOT = Path(__file__).parent
SURFACES_FILE = Path(os.getenv("PV_SURFACES_FILE", PROJECT_ROOT / "data" / "surfaces.json"))

DEFAULT_SURFACES = [
    {"name": "Ost", "kwp": 9.0, "tilt_deg": 30.0, "azimuth_deg": 90.0},
    {"name": "West", "kwp": 9.5, "tilt_deg": 30.0, "azimuth_deg": 270.0},
]


def load_surface_configs() -> list[dict[str, float | str]]:
    """Laedt beliebig viele Dachflaechen aus Schnittstelle, JSON-Datei oder Default.

    Prioritaet:
      1. PV_SURFACES_JSON: JSON-Liste direkt aus einer Schnittstelle/Automation
      2. PV_SURFACES_FILE: Pfad zu einer JSON-Datei
      3. data/surfaces.json
      4. DEFAULT_SURFACES als lauffaehiger Beispiel-Fallback
    """
    raw = os.getenv("PV_SURFACES_JSON")
    if raw:
        data = json.loads(raw)
    elif SURFACES_FILE.exists():
        data = json.loads(SURFACES_FILE.read_text(encoding="utf-8"))
    else:
        data = DEFAULT_SURFACES

    if not isinstance(data, list) or not data:
        raise ValueError("Dachflaechen-Konfiguration muss eine nicht-leere JSON-Liste sein.")

    required = {"name", "kwp", "tilt_deg", "azimuth_deg"}
    surfaces: list[dict[str, float | str]] = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Dachflaeche {i} ist kein Objekt.")
        missing = required - set(item)
        if missing:
            raise ValueError(f"Dachflaeche {i} hat fehlende Felder: {sorted(missing)}")
        surfaces.append({
            "name": str(item["name"]),
            "kwp": float(item["kwp"]),
            "tilt_deg": float(item["tilt_deg"]),
            "azimuth_deg": float(item["azimuth_deg"]),
        })
    return surfaces


def require_influx_token() -> str:
    """Gibt den Influx-Token zurueck oder bricht mit hilfreicher Meldung ab."""
    if not INFLUX_TOKEN:
        raise RuntimeError(
            "PV_INFLUX_TOKEN ist nicht gesetzt. Bitte als Umgebungsvariable "
            "setzen, statt Zugangsdaten im Code zu speichern."
        )
    return INFLUX_TOKEN
