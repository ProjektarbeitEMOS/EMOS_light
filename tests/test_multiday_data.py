"""Tests fuer Multi-Day-Datenladung (Mai 2026).

Damit der 48h-Day-Ahead-Horizont (vor 13 Uhr heute + ganzer morgen) fuer
beliebige Daten — auch in der Vergangenheit — mit echten Werten arbeiten
kann, muessen Preis- und Wetter-Fetcher den Zeitraum ueber mehrere Tage
liefern statt nur einen Tag zu fetchen und den Rest zu padden.
"""

import copy
import datetime

import numpy as np

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import load_input_data
from emos_light.data.prices import generate_synthetic_prices
from emos_light.data.weather import generate_synthetic_weather


def _cfg_with_horizon(hours: int) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = hours
    return cfg


# ---------------------------------------------------------------------------
# Synthetische Generatoren: pro Tag eigenes Profil, gleiches Muster modulo 24h
# ---------------------------------------------------------------------------

def test_synthetic_prices_48h_is_two_distinct_days():
    """Bei 48h Horizont (num_steps=192) muss der Generator zwei
    erkennbar verschiedene Tagesprofile liefern — vorher hat
    np.linspace(0,24,192) den 24h-Verlauf auf 48h gestaucht."""
    df = generate_synthetic_prices(
        datetime.date(2026, 1, 15), num_steps=192, step_minutes=15,
    )
    assert len(df) == 192
    p = df["price_ct_kwh"].values
    day1, day2 = p[:96], p[96:]
    # Profil pro Tag deckt einen realistischen Bereich ab (Min/Max-Span > 2 ct).
    assert day1.max() - day1.min() > 2.0
    assert day2.max() - day2.min() > 2.0
    # Tage haben unterschiedliche Rauschspuren, aber aehnliches Tagesprofil:
    # Mittelwert sollte sich um max. 2 ct unterscheiden.
    assert abs(day1.mean() - day2.mean()) < 2.0
    # Aber Stichproben sind nicht identisch (sonst war es nur Padding).
    assert not np.allclose(day1, day2)


def test_synthetic_weather_48h_is_two_distinct_days():
    df = generate_synthetic_weather(
        datetime.date(2026, 1, 15), num_steps=192, step_minutes=15,
    )
    assert len(df) == 192
    t = df["temperature_c"].values
    g = df["ghi_w_m2"].values
    # Tagesgang der Strahlung muss in beiden Haelften vorkommen (Glockenkurve).
    assert g[:96].max() > 50, "GHI-Peak fehlt in Tag 1"
    assert g[96:].max() > 50, "GHI-Peak fehlt in Tag 2"
    # Nicht identisch (sonst war es Padding).
    assert not np.allclose(t[:96], t[96:])


def test_synthetic_prices_step_minutes_aware_timestamps():
    """Zeitstempel muessen step_minutes-konsistent sein, nicht aus
    1440/num_steps abgeleitet (alter Bug bei num_steps != 96)."""
    df = generate_synthetic_prices(
        datetime.date(2026, 1, 15), num_steps=192, step_minutes=15,
    )
    ts = df["timestamp"].tolist()
    deltas = [(ts[i + 1] - ts[i]).total_seconds() / 60.0 for i in range(5)]
    assert all(d == 15.0 for d in deltas), f"Erwartet 15-min-Schritte, got {deltas}"
    # Erster Zeitstempel am Anfang des Datums
    assert ts[0] == datetime.datetime(2026, 1, 15, 0, 0)
    # Nach 96 Schritten = Anfang des Folgetags
    assert ts[96] == datetime.datetime(2026, 1, 16, 0, 0)


# ---------------------------------------------------------------------------
# Pipeline: load_input_data deckt den vollen Horizont mit Profilen ab
# ---------------------------------------------------------------------------

def test_load_input_data_48h_no_padded_constant_tail():
    """Nach load_input_data fuer 48h darf die zweite Tageshaelfte nicht
    konstant sein (sonst war es Padding mit dem letzten Wert)."""
    cfg = _cfg_with_horizon(48)
    data = load_input_data(cfg, datetime.date(2025, 11, 1), use_api=False)
    assert data["num_steps"] == 192
    p = data["spot_prices"]
    day2 = p[96:]
    assert not np.all(day2 == day2[0]), (
        "Tag-2-Preise sind alle identisch — das war der Padding-Bug"
    )
    # Realistischer Tagesgang
    assert day2.max() - day2.min() > 1.5


def test_load_input_data_24h_unaffected():
    """24h-Horizont (Regression-Default) muss weiterhin sauber durchlaufen."""
    cfg = _cfg_with_horizon(24)
    data = load_input_data(cfg, datetime.date(2025, 11, 1), use_api=False)
    assert data["num_steps"] == 96
    assert len(data["spot_prices"]) == 96
    assert len(data["temp"]) == 96
