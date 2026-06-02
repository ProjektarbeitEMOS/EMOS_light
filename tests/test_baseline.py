"""Tests fuer den Baseline-Modus (regelbasiert).

Pruefen, dass run_baseline ein vollstaendiges OptimizationResult liefert
und dass die Baseline (regelbasiert) immer schlechter (oder gleich) ist
als die MILP-Optimierung — sonst stimmt etwas nicht mit dem Optimizer.
"""

import copy
import datetime

import numpy as np
import pytest

from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)
from emos_light.optimization.baseline import (
    calculate_baseline_cost,
    run_baseline,
)

from .conftest import (
    cfg_battery_only,
    cfg_full_house,
    cfg_hp_ufh,
    cfg_hp_ww,
    cfg_wallbox_only,
    TEST_DATE,
)


def _cfg_room_winter() -> dict:
    """WP + FBH + Building bei kaltem Winter — pruefen, dass das Raumluft-
    Modell der Baseline laeuft (analog zu tests/test_milp_room.py)."""
    cfg = cfg_hp_ufh()
    cfg["building"]["enabled"] = True
    cfg["building"]["indoor_temp_c"] = 21.0
    cfg["building"]["comfort_temp_min_c"] = 20.0
    cfg["building"]["comfort_temp_max_c"] = 24.0
    return cfg


def _input_for(cfg):
    data = load_input_data(cfg, TEST_DATE)
    return build_time_series_input(cfg, data)


# ---------------------------------------------------------------------------
# Result-Schema: alle wichtigen Felder muessen befuellt sein
# ---------------------------------------------------------------------------

def test_run_baseline_full_house_returns_complete_result():
    cfg = cfg_full_house()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)

    assert res.success is True
    assert res.solver_status == "Baseline"
    assert res.solve_time_s >= 0
    assert res.total_cost_eur is not None

    # Alle Zeitreihen muessen vorhanden sein und die richtige Laenge haben
    n = len(res.timestamps)
    assert n > 0
    for arr_name in (
        "grid_buy_kw", "grid_sell_kw",
        "batt_charge_kw", "batt_discharge_kw", "batt_soc_kwh",
        "hp_power_kw",
    ):
        arr = getattr(res, arr_name)
        assert arr is not None and len(arr) == n, f"{arr_name} hat falsche Laenge"

    # KPIs
    assert 0 <= res.eigenverbrauch_pct <= 100
    assert 0 <= res.autarkie_pct <= 100


def test_run_baseline_battery_only():
    cfg = cfg_battery_only()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)
    assert res.solver_status == "Baseline"
    assert res.success is True
    # Wenn keine WP da ist, hp_power_kw sollte ueberall 0 sein
    assert (res.hp_power_kw == 0).all()


def test_run_baseline_with_wallbox():
    cfg = cfg_wallbox_only()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)
    # Wallbox laedt sofort bei Ankunft → mind. ein Schritt mit Power > 0
    assert "wb1" in res.wallbox_power_kw
    assert res.wallbox_power_kw["wb1"].sum() > 0


# ---------------------------------------------------------------------------
# Konsistenz mit calculate_baseline_cost (gleiche Strategie, gleiche Kosten)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", [cfg_battery_only, cfg_hp_ww, cfg_full_house])
def test_run_baseline_matches_calculate_baseline_cost(scenario):
    cfg = scenario()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)
    cost_via_function = calculate_baseline_cost(inp, cfg)
    # Beide Implementierungen sollen denselben Wert liefern (1 ct Toleranz
    # fuer Rundung)
    assert res.total_cost_eur == pytest.approx(cost_via_function, abs=0.01)


# ---------------------------------------------------------------------------
# MILP soll besser oder gleich gut sein wie die Baseline
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", [cfg_full_house, cfg_hp_ww])
def test_milp_no_worse_than_baseline(scenario):
    cfg = scenario()
    inp = _input_for(cfg)
    base = run_baseline(inp, cfg)
    milp = build_optimizer(build_components(cfg)).optimize(inp)

    # MILP optimiert Kosten — darf nie schlechter sein als die Baseline
    # (kleine numerische Toleranz fuer Solver-Rauschen)
    assert milp.total_cost_eur <= base.total_cost_eur + 0.01, (
        f"{scenario.__name__}: MILP={milp.total_cost_eur:.4f} > "
        f"Baseline={base.total_cost_eur:.4f}"
    )


# ---------------------------------------------------------------------------
# Raumluftmodell (Mai 2026) — Baseline mit Building als aktiver Komponente
# ---------------------------------------------------------------------------

def test_baseline_room_mode_populates_result_fields():
    """Mit aktivem Building muss die Baseline T_innen/heat_loss/q_to_room
    in das Result schreiben — analog zum MILP-Pfad."""
    cfg = _cfg_room_winter()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)

    assert res.success is True
    n = len(res.timestamps)

    assert res.indoor_temp_c is not None and len(res.indoor_temp_c) == n
    assert res.heat_loss_kw is not None and len(res.heat_loss_kw) == n
    assert res.q_floor_to_room_kw is not None and len(res.q_floor_to_room_kw) == n

    # T_innen muss in einem plausiblen Bereich um die Komfortgrenzen herum
    # bleiben — die Baseline taktet, also etwas Toleranz erlaubt.
    assert res.indoor_temp_c.min() > 15.0, (
        f"T_innen unrealistisch tief: {res.indoor_temp_c.min():.2f} °C"
    )
    assert res.indoor_temp_c.max() < 30.0, (
        f"T_innen unrealistisch hoch: {res.indoor_temp_c.max():.2f} °C"
    )


def test_baseline_room_mode_balance_consistent():
    """Stationaere Energiebilanz: ueber den ganzen Tag muss die WP genug
    Waerme liefern, dass das Haus im Mittel nicht abkuehlt — d.h.
    sum(q_floor_to_room) ≈ sum(q_loss), beide > 0."""
    cfg = _cfg_room_winter()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)

    dt_h = inp.step_minutes / 60.0
    q_to_room_kwh = float(np.sum(res.q_floor_to_room_kw)) * dt_h
    q_loss_kwh = float(np.sum(res.heat_loss_kw)) * dt_h

    # WP muss Waerme abgeben (Estrich -> Raum), sonst kuehlt das Haus
    # nur ab. Verlust > 0 ohnehin (Aussentemperatur < Innentemperatur).
    assert q_loss_kwh > 0, "Verluste muessten im Winter positiv sein"
    assert q_to_room_kwh > 0, "Estrich muesste Waerme an den Raum abgeben"
    # Bei Hysterese-Regelung sollte der Mittelwert vergleichbar sein —
    # ueber 24 h schwankt T_innen, aber netto deckt die Heizung den
    # Verlust. Toleranz: 50 % (Hysterese ist nicht praezise).
    assert abs(q_to_room_kwh - q_loss_kwh) < 0.5 * q_loss_kwh + 5.0, (
        f"Energiebilanz weit auseinander: "
        f"q_to_room={q_to_room_kwh:.2f} kWh, q_loss={q_loss_kwh:.2f} kWh"
    )


def test_baseline_room_mode_heat_loss_formula():
    """heat_loss_kw[t] = direkter Verlust (Fenster+Dach+Lueftung, auf
    T_innen[t]) + Wandpfad (auf T_W[t-1]) — 3-Speicher-Modell (ETH,
    Juni 2026), konsistent zum MILP-Optimizer (Building.extract_result)."""
    cfg = _cfg_room_winter()
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)

    from emos_light.components.building import Building
    b = Building("test", cfg["building"])
    ua_direct_kw = b.ua_direct_w_per_k / 1000.0
    g_wa_kw = b.wall_conductance_wa_w_per_k / 1000.0

    # Wandpfad mit T_W am Schrittanfang: prev = [T_W_init, T_W[0], ...].
    wall_prev = np.concatenate(([b.initial_wall_temp_c], res.wall_temp_c[:-1]))
    t_aus = inp.outside_temp_c[: len(res.indoor_temp_c)]
    expected = (
        ua_direct_kw * (res.indoor_temp_c - t_aus)
        + g_wa_kw * (wall_prev - t_aus)
    )
    assert np.allclose(res.heat_loss_kw, expected, atol=1e-6), (
        "heat_loss_kw weicht vom 3-Speicher-Verlust (direkt + Wandpfad) ab"
    )


def test_baseline_room_mode_milp_no_worse():
    """MILP darf auch im Raumluftmodus nicht teurer sein als die Baseline."""
    cfg = _cfg_room_winter()
    inp = _input_for(cfg)
    base = run_baseline(inp, cfg)
    milp = build_optimizer(build_components(cfg)).optimize(inp)

    assert milp.total_cost_eur <= base.total_cost_eur + 0.01, (
        f"MILP={milp.total_cost_eur:.4f} > Baseline={base.total_cost_eur:.4f}"
    )


def test_baseline_without_building_keeps_old_fallback():
    """Ohne Building muss die Baseline ohne T_innen-Felder durchlaufen
    (alte Verlustraten-Hysterese, kompatibel zu pre-Mai-2026)."""
    cfg = cfg_hp_ufh()
    cfg["building"]["enabled"] = False
    inp = _input_for(cfg)
    res = run_baseline(inp, cfg)
    assert res.success
    # indoor_temp_c bleibt leer (Default field aus dataclass = leere Reihe)
    assert len(res.indoor_temp_c) == 0
    assert len(res.heat_loss_kw) == 0
    assert len(res.q_floor_to_room_kw) == 0
    # Aber Estrich-Trajektorie wird wie gehabt gefuellt
    assert len(res.floor_energy_kwh) == len(res.timestamps)
