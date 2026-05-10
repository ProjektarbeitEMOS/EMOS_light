"""Tests fuer den Baseline-Modus (regelbasiert).

Pruefen, dass run_baseline ein vollstaendiges OptimizationResult liefert
und dass die Baseline (regelbasiert) immer schlechter (oder gleich) ist
als die MILP-Optimierung — sonst stimmt etwas nicht mit dem Optimizer.
"""

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
    cfg_hp_ww,
    cfg_wallbox_only,
    TEST_DATE,
)


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
