"""Regression-Test: Config-Import muss fehlende Sektionen mit Defaults
fuellen, sonst crasht das Sidebar-Rendering spaeter mit ``KeyError``.

User-Report 2026-05-19: Beim Upload einer Config-YAML verschwindet die
Datei sofort wieder und die Config-Werte werden nicht in die UI
uebernommen. Ursache: die Pending-Datei (bzw. die hochgeladene YAML)
konnte einzelne Top-Level-Sektionen weglassen, die dann beim
Rendering der Sidebar (z.B. ``config["hot_water_storage"]["enabled"]``)
einen unbehandelten KeyError ausgeloest haben.

Loesung: ``_merge_with_defaults`` in app.py mergt jede importierte
YAML rekursiv mit DEFAULT_CONFIG, sodass alle Sektionen garantiert
vorhanden sind.
"""

import copy
import tempfile
import yaml
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


PENDING_PATH = Path(tempfile.gettempdir()) / "emos_light_pending_import.yaml"


@pytest.fixture(autouse=True)
def _cleanup_pending():
    """Stellt sicher, dass die Pending-Datei vor und nach jedem Test
    weg ist (Tests beeinflussen sich sonst gegenseitig)."""
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()
    yield
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()


def _write_pending(cfg: dict) -> None:
    PENDING_PATH.write_text(yaml.safe_dump(cfg), encoding="utf-8")


def test_partial_pending_does_not_crash_app():
    """Pending-Datei ohne ``hot_water_storage`` darf NICHT crashen —
    war der Fehler vom 2026-05-19."""
    _write_pending({
        "general": {"optimization_horizon_hours": 24, "latitude": 52.5},
        "pv": {"enabled": False},
    })

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception, (
        f"App crasht bei partieller Pending-Datei: {at.exception}"
    )


def test_partial_pending_keeps_user_values():
    """Vorhandene Felder aus der Pending-Datei muessen ueberleben."""
    _write_pending({
        "general": {"optimization_horizon_hours": 24, "latitude": 52.5},
        "pv": {"enabled": False},
        "heat_pump": {"max_electrical_power_kw": 6.0},
    })

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    cfg = at.session_state["config"]
    assert cfg["general"]["latitude"] == 52.5
    assert cfg["general"]["optimization_horizon_hours"] == 24
    assert cfg["pv"]["enabled"] is False
    assert cfg["heat_pump"]["max_electrical_power_kw"] == 6.0


def test_partial_pending_fills_missing_sections_with_defaults():
    """Fehlende Sektionen muessen mit DEFAULT_CONFIG aufgefuellt werden."""
    _write_pending({
        "general": {"optimization_horizon_hours": 24},
        "pv": {"enabled": False},
    })

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    cfg = at.session_state["config"]
    # Sektionen, die im YAML fehlten, muessen aus DEFAULT_CONFIG da sein.
    for missing in ("hot_water_storage", "building", "underfloor_heating",
                    "heat_pump", "battery", "tariff"):
        assert missing in cfg, f"Sektion {missing} fehlt nach Merge"


def test_pending_file_is_consumed_and_deleted():
    """Nach erfolgreichem Laden muss die Pending-Datei verschwunden sein,
    damit der naechste App-Start nicht erneut darueber stolpert."""
    _write_pending({"general": {"latitude": 52.5}})
    assert PENDING_PATH.exists()

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not PENDING_PATH.exists(), "Pending-Datei wurde nicht aufgeraeumt"


def test_empty_pending_yaml_falls_back_to_defaults():
    """Eine leere YAML (yaml.safe_load -> None) darf nicht crashen —
    es muss auf DEFAULT_CONFIG zurueckgefallen werden."""
    PENDING_PATH.write_text("", encoding="utf-8")

    at = AppTest.from_file("app.py", default_timeout=60)
    at.run()
    assert not at.exception
    cfg = at.session_state["config"]
    assert "general" in cfg
    assert "heat_pump" in cfg
