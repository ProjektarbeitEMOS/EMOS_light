"""Tests fuer die GHI->POA-Transpositionsmodelle.

Sicherstellt, dass beide Modelle (Perez und Liu & Jordan/isotropic):
  - lauffaehig sind und ohne Fehler ein Array gleicher Laenge liefern
  - bei Nacht und sehr niedrigem Sonnenstand 0 ausgeben
  - Werte > 0 fuer typische Tagsituationen liefern
  - unterschiedlich sein (Perez ueblicherweise hoeher an klaren Tagen)
"""

import datetime
import numpy as np
import pytest

from emos_light.data.solar import ghi_to_poa, solar_position
from emos_light.components.pv import PVSystem


def _typical_day():
    """Liefert (ghi, sun_elev, sun_az, doy) fuer einen klaren Sommertag."""
    ts = [
        datetime.datetime(2026, 6, 21, h, 0)
        for h in range(24)
    ]
    elev, az = solar_position(ts, latitude=49.33, longitude=12.11, timezone_offset_h=2.0)
    doy = ts[0].timetuple().tm_yday
    # Synthetischer GHI: Glockenkurve mit Peak bei Mittag
    elev_clipped = np.clip(elev, 0, 90)
    ghi = 800 * np.sin(np.radians(elev_clipped))
    ghi[elev_clipped < 1] = 0.0
    return ghi, elev, az, doy


def test_perez_produces_non_negative_poa():
    ghi, elev, az, doy = _typical_day()
    poa = ghi_to_poa(ghi, elev, az, panel_tilt_deg=30, panel_azimuth_deg=180,
                     albedo=0.2, doy=doy, model="perez")
    assert len(poa) == len(ghi)
    assert (poa >= 0).all()
    # Tagsumme muss > 0 sein (klarer Sommertag)
    assert poa.sum() > 0


def test_isotropic_produces_non_negative_poa():
    ghi, elev, az, doy = _typical_day()
    poa = ghi_to_poa(ghi, elev, az, panel_tilt_deg=30, panel_azimuth_deg=180,
                     albedo=0.2, doy=doy, model="isotropic")
    assert len(poa) == len(ghi)
    assert (poa >= 0).all()
    assert poa.sum() > 0


def test_both_models_zero_at_night():
    ghi, elev, az, doy = _typical_day()
    # Mitternacht-Index 0 hat elev ~ negativ → GHI=0
    poa_perez = ghi_to_poa(ghi, elev, az, 30, 180, 0.2, doy, model="perez")
    poa_iso = ghi_to_poa(ghi, elev, az, 30, 180, 0.2, doy, model="isotropic")
    assert poa_perez[0] == 0.0
    assert poa_iso[0] == 0.0


def test_perez_vs_isotropic_differ_at_clear_day():
    """An einem klaren Tag liefern Perez und Liu&Jordan unterschiedliche Werte.

    Die Beam- und Bodenreflexion sind identisch, der Diffus-Anteil
    unterscheidet sich.
    """
    ghi, elev, az, doy = _typical_day()
    poa_perez = ghi_to_poa(ghi, elev, az, 30, 180, 0.2, doy, model="perez")
    poa_iso = ghi_to_poa(ghi, elev, az, 30, 180, 0.2, doy, model="isotropic")
    # Es muss mindestens einen Zeitschritt geben, wo sich die Werte > 1 %
    # unterscheiden — sonst waeren die Modelle effektiv gleich
    safe_denom = np.where(poa_perez > 0, poa_perez, 1.0)
    rel_diff = np.where(poa_perez > 0, np.abs(poa_perez - poa_iso) / safe_denom, 0)
    assert rel_diff.max() > 0.01


def test_invalid_model_raises():
    ghi, elev, az, doy = _typical_day()
    with pytest.raises(ValueError, match="Unbekanntes Transpositionsmodell"):
        ghi_to_poa(ghi, elev, az, 30, 180, 0.2, doy, model="haydavies")


# ---------------------------------------------------------------------------
# PVSystem-Integration
# ---------------------------------------------------------------------------

def test_pv_system_default_is_perez():
    pv = PVSystem("pv", {"peak_power_kwp": 10})
    assert pv.transposition_model == "perez"


def test_pv_system_can_use_isotropic():
    pv = PVSystem("pv", {"peak_power_kwp": 10, "transposition_model": "isotropic"})
    assert pv.transposition_model == "isotropic"


def test_pv_system_end_to_end_with_both_models():
    """Beide Modelle laufen ueber estimate_generation durch."""
    ts = [datetime.datetime(2026, 6, 21, h, 0) for h in range(24)]
    elev, _az = solar_position(ts, latitude=49.33, longitude=12.11, timezone_offset_h=2.0)
    ghi = np.clip(800 * np.sin(np.radians(np.clip(elev, 0, 90))), 0, None)

    for model in ("perez", "isotropic"):
        pv = PVSystem("pv", {
            "peak_power_kwp": 10.0, "tilt_deg": 30, "azimuth_deg": 180,
            "transposition_model": model,
        })
        power = pv.estimate_generation(
            ghi, timestamps=ts, latitude=49.33, longitude=12.11,
        )
        assert len(power) == 24
        assert (power >= 0).all()
        assert power.sum() > 0
