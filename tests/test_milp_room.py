"""End-to-End-Test fuer die MILP-Erweiterung Mai 2026 (Raum als Variable).

Szenario:
    24 h, konstante Aussentemperatur -5 °C, kein PV, kein Haushaltsstrom.
    WP + FBH + Building aktiv. Komfortband 20–24 °C.

Wir pruefen:
1. Solver findet ein Optimum.
2. Mittlerer Waermestrom Estrich -> Raum entspricht der mittleren
   Verlustleistung an die Aussenluft: q ≈ UA·(T_innen - T_aus)/1000.
3. Mittlere WP-Leistung deckt q_floor_to_room geteilt durch den
   COP — Toleranz bewusst grosszuegig, weil COP zeitvariabel ist und
   die Estrich-Speicherung Lastverschiebung ueber den Tag macht.
4. T_innen bleibt nahezu komplett im Komfortband [20, 24] °C.
"""

import copy
import datetime

import numpy as np
import pytest

from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    build_time_series_input,
    load_input_data,
)


TEST_DATE = datetime.date(2026, 1, 15)


def _winter_cfg() -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    # Test-Doku spricht von 24 h: Horizont explizit pinnen, unabhaengig
    # vom Produkt-Default (48 h fuer Day-Ahead-MPC nach 13 Uhr).
    cfg["general"]["optimization_horizon_hours"] = 24
    # Nur WP+FBH+Building aktiv — andere Komponenten ausschalten.
    for key in ("battery", "pv", "hot_water_storage",
                "fresh_water_station"):
        cfg.setdefault(key, {})["enabled"] = False
    cfg["heat_pump"]["enabled"] = True
    cfg["underfloor_heating"]["enabled"] = True
    cfg["building"]["enabled"] = True
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    # Schmales Komfortband, damit T_innen wirklich im Band landen muss.
    cfg["building"]["comfort_temp_min_c"] = 20.0
    cfg["building"]["comfort_temp_max_c"] = 24.0
    cfg["building"]["indoor_temp_c"] = 21.0
    # Solare/interne Gewinne aus -> reine Heizbilanz (q_to_room ≈ UA·ΔT).
    cfg["building"]["solar_gains_enabled"] = False
    cfg["building"]["internal_gains_w_per_m2"] = 0.0
    # Haushalt klein — wir wollen die Heizenergie isoliert sehen.
    cfg["household"]["annual_consumption_kwh"] = 1000
    cfg["household"]["load_profile_id"] = ""
    return cfg


@pytest.fixture
def winter_run():
    cfg = _winter_cfg()
    data = load_input_data(cfg, TEST_DATE)
    # Aussentemperatur auf konstant -5 °C ueberschreiben.
    data["temp"] = np.full_like(data["temp"], -5.0, dtype=float)
    inp = build_time_series_input(cfg, data)
    comps = build_components(cfg)
    opt = build_optimizer(comps)
    res = opt.optimize(inp)
    return cfg, inp, comps, res


def test_solver_finds_optimum(winter_run):
    _, _, _, res = winter_run
    assert res.success, f"Solver erfolglos: {res.solver_status}"


def test_room_balance_matches_loss(winter_run):
    """Im stationaeren Mittel: q_floor_to_room ≈ UA·(T_innen - T_aus)/1000."""
    cfg, inp, comps, res = winter_run
    assert res.success

    # Die ersten paar Schritte sind Einschwingen — wir mitteln ueber
    # die zweite Tageshaelfte (12-24 h).
    n = len(res.indoor_temp_c)
    start = n // 2
    q_to_room_mean = float(np.mean(res.q_floor_to_room_kw[start:]))
    t_in_mean = float(np.mean(res.indoor_temp_c[start:]))
    t_out_mean = float(np.mean(inp.outside_temp_c[start:]))

    ua_kw_per_k = comps["building"].ua_w_per_k / 1000.0
    expected_q = ua_kw_per_k * (t_in_mean - t_out_mean)

    # Toleranz: 25 % oder 0.2 kW absolut — was groesser ist.
    tol = max(0.25 * abs(expected_q), 0.2)
    assert abs(q_to_room_mean - expected_q) < tol, (
        f"q_to_room_mean={q_to_room_mean:.3f} kW, "
        f"expected≈{expected_q:.3f} kW "
        f"(UA={ua_kw_per_k*1000:.1f} W/K, ΔT={t_in_mean-t_out_mean:.2f} K)"
    )


def test_hp_covers_heat_via_cop(winter_run):
    """Mittlere WP-Leistung ≈ Q_floor_in / COP, mit grosszuegiger Toleranz."""
    cfg, inp, comps, res = winter_run
    assert res.success

    # Tagesbilanz (energetisch) statt momentaner Mittelwert — die
    # Estrich-Speicherung verschiebt Last innerhalb des Tages.
    dt_h = inp.step_minutes / 60.0
    q_in_kwh = float(np.sum(res.q_floor_kw)) * dt_h  # Waerme in den Estrich
    hp_el_kwh = float(np.sum(res.hp_power_kw)) * dt_h

    hp = comps["heat_pump"]
    cop_floor_mean = float(np.mean(hp.calculate_cop_heating(inp.outside_temp_c)))
    expected_hp_kwh = q_in_kwh / cop_floor_mean

    assert hp_el_kwh > 0, "WP muesste laufen, sonst kuehlt das Haus aus"
    # 30 % Toleranz: Solver darf takten + Estrich speichert ueber die
    # Tagesgrenze hinaus.
    tol = max(0.3 * expected_hp_kwh, 0.5)
    assert abs(hp_el_kwh - expected_hp_kwh) < tol, (
        f"hp_el_kwh={hp_el_kwh:.2f}, expected≈{expected_hp_kwh:.2f} "
        f"(COP_mean={cop_floor_mean:.2f})"
    )


def test_indoor_temp_stays_in_comfort_band(winter_run):
    """T_innen sollte ueberwiegend im 20–24 °C Band liegen."""
    _, _, _, res = winter_run
    assert res.success

    t_in = res.indoor_temp_c
    # Toleranz: hoechstens 1 K Auskuehlen/Ueberheizen, im Mittel im Band.
    assert t_in.min() >= 19.0, f"T_innen.min={t_in.min():.2f} zu kalt"
    assert t_in.max() <= 25.0, f"T_innen.max={t_in.max():.2f} zu warm"
    in_band = np.sum((t_in >= 19.9) & (t_in <= 24.1)) / len(t_in)
    assert in_band > 0.85, (
        f"Nur {in_band*100:.0f}% der Stunden im Komfortband"
    )


def test_heat_loss_kw_is_populated(winter_run):
    """Diagnose-Feld heat_loss_kw sollte gefuellt sein und plausibel."""
    cfg, inp, comps, res = winter_run
    assert res.success
    assert res.heat_loss_kw.size == len(res.indoor_temp_c)
    # Im Mittel positiv (Haus verliert Waerme bei -5 °C draussen).
    assert res.heat_loss_kw.mean() > 0


def test_wall_temp_between_room_and_outside(winter_run):
    """3-Speicher-Modell: Wandtemperatur T_W liegt zwischen Aussen und Raum.

    Die Wand ist der traege Speicher zwischen Raumluft und Aussenluft —
    im stationaeren Mittel muss ihre Temperatur zwischen beiden liegen.
    """
    cfg, inp, comps, res = winter_run
    assert res.success
    # Wandzustand muss befuellt sein (Wandknoten aktiv).
    assert res.wall_temp_c.size == len(res.indoor_temp_c)

    n = len(res.wall_temp_c)
    start = n // 2  # zweite Tageshaelfte (eingeschwungen)
    t_wall_mean = float(res.wall_temp_c[start:].mean())
    t_in_mean = float(res.indoor_temp_c[start:].mean())
    t_out_mean = float(inp.outside_temp_c[start:].mean())
    assert t_out_mean < t_wall_mean < t_in_mean, (
        f"T_Wand={t_wall_mean:.2f} nicht zwischen "
        f"T_aussen={t_out_mean:.2f} und T_innen={t_in_mean:.2f}"
    )


def test_ufh_falls_back_when_building_disabled():
    """Ohne Building: UFH-Modell laeuft auf altem Verlustpfad ohne Crash."""
    cfg = _winter_cfg()
    cfg["building"]["enabled"] = False
    data = load_input_data(cfg, TEST_DATE)
    inp = build_time_series_input(cfg, data)
    comps = build_components(cfg)
    opt = build_optimizer(comps)
    res = opt.optimize(inp)
    assert res.success, f"Fallback infeasible: {res.solver_status}"
    # Kein T_innen-Ergebnis ohne Building.
    assert res.indoor_temp_c.size == 0
    # q_floor_to_room ebenfalls leer (Variable nicht angelegt).
    assert res.q_floor_to_room_kw.size == 0
