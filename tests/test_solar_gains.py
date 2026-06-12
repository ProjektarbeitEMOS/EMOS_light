"""Tests fuer die solaren + internen Raumgewinne Q_g,R (Gebaeudegruppe, FINAL).

    Q_g,R = SUM_i g * A_Fenster,i * (I*cos(theta_i) + 0.5*D) + q_int * A_Wohn
    cos(theta_i) = max(0, cos(Sonnenhoehe) * cos(Sonnenazimut - Fassadenazimut))

ueber die vier Fassaden i in {N, O, S, W}; I = DNI, D = DHI.
Q_g,B (Estrich) = 0 (mit Prof. Brueckl bestaetigt) — wird hier nicht gesetzt.
"""

import copy
import datetime

import numpy as np
import pytest

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.components.building import Building
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    build_time_series_input,
    load_input_data,
)


DATE = datetime.date(2026, 4, 15)


def _april_cfg() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    for k in ("battery", "pv", "hot_water_storage", "fresh_water_station"):
        cfg.setdefault(k, {})["enabled"] = False
    cfg["heat_pump"]["enabled"] = True
    cfg["underfloor_heating"]["enabled"] = True
    cfg["building"]["enabled"] = True
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    cfg["household"]["annual_consumption_kwh"] = 1000
    cfg["household"]["load_profile_id"] = ""
    return cfg


@pytest.fixture(scope="module")
def weather():
    return load_input_data(_april_cfg(), DATE)


def _gain(building_cfg: dict, data: dict) -> np.ndarray:
    b = Building("b", building_cfg)
    return b.compute_room_gain_w(
        data["timestamps"], data["ghi"], data["dni"],
        data["lat"], data["lon"], data["dhi"],
    )


# ---------------------------------------------------------------------------
# Q_g,R-Berechnung (compute_room_gain_w)
# ---------------------------------------------------------------------------

def test_internal_gain_at_night(weather):
    """Nachts (keine Sonne) bleibt nur der konstante interne Anteil."""
    cfg = _april_cfg()["building"]
    gain = _gain(cfg, weather)
    internal = 5.0 * 150.0  # 5 W/m² * 150 m² = 750 W
    assert gain[8] == pytest.approx(internal, abs=1.0)   # Schritt 8 = 02:00


def test_south_beats_north_and_diffuse_on_north(weather):
    """Sued (Beam + Diffus) > Nord (nur Diffus) > rein intern.

    Im FINALEN Modell bekommt JEDE Fassade den Diffusanteil 0.5*D — auch
    das Nordfenster (das praktisch keinen direkten Strahl sieht)."""
    bcfg = _april_cfg()["building"]
    gs = _gain({**bcfg, "window_orientation_split": {"south": 1.0}}, weather)
    gn = _gain({**bcfg, "window_orientation_split": {"north": 1.0}}, weather)
    internal = 5.0 * 150.0
    # Sued klar hoeher (zusaetzlicher Beam-Anteil)
    assert gs.max() > gn.max() + 500.0
    # Nord liegt trotzdem ueber dem reinen internen Anteil -> Diffusgewinn
    assert gn.max() > internal + 50.0


def test_diffuse_present_when_solar_on(weather):
    """Der Diffusanteil 0.5*D ist tagsueber wirksam (nicht nur Beam)."""
    bcfg = _april_cfg()["building"]
    # Reines Nordfenster: praktisch kein Beam -> jeder Gewinn ueber dem
    # internen Anteil ist Diffusstrahlung.
    gn = _gain({**bcfg, "window_orientation_split": {"north": 1.0}}, weather)
    internal = 5.0 * 150.0
    assert (gn - internal).max() > 30.0   # mittags messbarer Diffusgewinn


def test_solar_disabled_only_internal(weather):
    """solar_gains_enabled=False -> ueberall nur der interne Anteil."""
    bcfg = {**_april_cfg()["building"], "solar_gains_enabled": False}
    gain = _gain(bcfg, weather)
    assert np.allclose(gain, 5.0 * 150.0)


def test_internal_per_m2_scales_with_area(weather):
    """Interner Anteil skaliert mit q_int und Wohnflaeche."""
    bcfg = {**_april_cfg()["building"], "solar_gains_enabled": False,
            "internal_gains_w_per_m2": 4.0, "heated_area_m2": 200}
    gain = _gain(bcfg, weather)
    assert np.allclose(gain, 4.0 * 200.0)   # 800 W


# ---------------------------------------------------------------------------
# Wirkung im Optimizer
# ---------------------------------------------------------------------------

def test_gains_reduce_hp_energy():
    """Mit Gewinnen braucht die WP weniger Energie als ohne."""
    def run(solar_on: bool):
        cfg = _april_cfg()
        cfg["building"]["solar_gains_enabled"] = solar_on
        cfg["building"]["internal_gains_w_per_m2"] = 5.0 if solar_on else 0.0
        data = load_input_data(cfg, DATE)
        data["temp"] = np.full_like(data["temp"], -2.0, dtype=float)  # heizen
        inp = build_time_series_input(cfg, data)
        return build_optimizer(build_components(cfg)).optimize(inp)

    res_on = run(True)
    res_off = run(False)
    assert res_on.success and res_off.success

    hp_on = float(res_on.hp_power_kw.sum())
    hp_off = float(res_off.hp_power_kw.sum())
    assert hp_off > 0.0, "Referenz ohne Gewinne sollte die WP heizen lassen"
    assert hp_on < hp_off, (
        f"Gewinne sollten die WP-Energie senken: mit={hp_on:.2f} "
        f"ohne={hp_off:.2f}"
    )
    # Diagnose-Fahrplan Q_g,R ist befuellt und hat einen Tagesgang.
    assert res_on.room_gain_kw.size == len(res_on.indoor_temp_c)
    assert res_on.room_gain_kw.max() > 0.75   # >750 W (intern) + Solar mittags
    assert np.allclose(res_off.room_gain_kw, 0.0)
