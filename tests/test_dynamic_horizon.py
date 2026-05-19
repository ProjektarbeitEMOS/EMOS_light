"""Tests fuer die dynamische Horizont-Anpassung an die Day-Ahead-Verfuegbarkeit.

Konzept (siehe :func:`emos_light.core.scenario.load_input_data`):
Wenn bei ``use_api=True`` die morgigen Day-Ahead-Preise an der EPEX SPOT
noch nicht publiziert sind (typ. vor 13 Uhr Ortszeit), wird der
Optimierungshorizont von 48 h auf 24 h verkuerzt — es wird nie ueber
einen Zeitraum optimiert, fuer den keine echten Marktpreise vorliegen.
"""

import copy
import datetime
from unittest.mock import patch

import numpy as np

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import load_input_data


def _cfg_48h() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 48
    return cfg


def test_synthetic_path_keeps_full_horizon():
    """Ohne ``use_api`` bleibt der Horizont auf 48 h — die synthetischen
    Preise sind immer ueber alle Tage verfuegbar."""
    cfg = _cfg_48h()
    data = load_input_data(
        cfg, datetime.date(2025, 11, 1), use_api=False,
    )
    assert data["num_steps"] == 192
    assert data["horizon_hours"] == 48
    assert data["configured_horizon_hours"] == 48
    assert data["horizon_shrunk"] is False


def test_api_shrinks_when_day_ahead_not_published():
    """Wenn ``is_day_ahead_published`` False zurueckgibt, muss der
    Horizont auf 24 h schrumpfen."""
    cfg = _cfg_48h()
    with patch(
        "emos_light.core.scenario.is_day_ahead_published",
        return_value=False,
    ):
        data = load_input_data(
            cfg, datetime.date(2026, 5, 19), use_api=True,
        )
    assert data["num_steps"] == 96
    assert data["horizon_hours"] == 24
    assert data["configured_horizon_hours"] == 48
    assert data["horizon_shrunk"] is True


def test_api_keeps_full_horizon_when_day_ahead_available():
    """Wenn die morgigen Preise publiziert sind, bleibt der Horizont 48 h."""
    cfg = _cfg_48h()
    with patch(
        "emos_light.core.scenario.is_day_ahead_published",
        return_value=True,
    ):
        data = load_input_data(
            cfg, datetime.date(2026, 5, 19), use_api=True,
        )
    assert data["num_steps"] == 192
    assert data["horizon_hours"] == 48
    assert data["horizon_shrunk"] is False


def test_shrink_respects_configured_24h_horizon():
    """24 h-Konfiguration darf nie geschrumpft werden (es gibt nichts zu
    schrumpfen) — auch nicht bei nicht-publizierten Folgetag-Preisen."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    with patch(
        "emos_light.core.scenario.is_day_ahead_published",
        return_value=False,
    ):
        data = load_input_data(
            cfg, datetime.date(2026, 5, 19), use_api=True,
        )
    assert data["num_steps"] == 96
    assert data["horizon_hours"] == 24
    assert data["horizon_shrunk"] is False


def test_timestamps_match_shrunk_horizon():
    """Nach dem Shrink muessen Timestamps und Datenfelder konsistent
    laenger als 0 und exakt so lang wie num_steps sein."""
    cfg = _cfg_48h()
    with patch(
        "emos_light.core.scenario.is_day_ahead_published",
        return_value=False,
    ):
        data = load_input_data(
            cfg, datetime.date(2026, 5, 19), use_api=True,
        )
    n = data["num_steps"]
    assert len(data["timestamps"]) == n
    assert len(data["spot_prices"]) == n
    assert len(data["temp"]) == n
    assert len(data["pv_generation"]) == n
