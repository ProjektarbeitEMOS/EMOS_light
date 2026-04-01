"""KPI-Berechnungen fuer EMOS Light."""

import numpy as np

from emos_light.core.types import OptimizationResult, TimeSeriesInput


def calculate_kpis(
    result: OptimizationResult, inp: TimeSeriesInput
) -> OptimizationResult:
    """Berechnet alle KPIs und fuegt sie zum Result hinzu."""
    dt_h = inp.step_minutes / 60.0
    num_steps = len(inp.prices_ct_kwh)

    result.pv_total_kwh = float(np.sum(inp.pv_generation_kw) * dt_h)

    hp_power = result.hp_power_kw if len(result.hp_power_kw) > 0 else np.zeros(num_steps)

    wb_power_total = np.zeros(num_steps)
    for _wb_name, wb_arr in result.wallbox_power_kw.items():
        if len(wb_arr) == num_steps:
            wb_power_total += wb_arr

    total_load = inp.household_load_kw + hp_power + wb_power_total
    result.load_total_kwh = float(np.sum(total_load) * dt_h)

    result.grid_buy_total_kwh = float(np.sum(result.grid_buy_kw) * dt_h)
    result.grid_sell_total_kwh = float(np.sum(result.grid_sell_kw) * dt_h)
    result.hp_total_kwh = float(np.sum(hp_power) * dt_h)

    # Eigenverbrauchsquote
    if result.pv_total_kwh > 0:
        pv_feed_in = min(result.grid_sell_total_kwh, result.pv_total_kwh)
        pv_self_consumed = result.pv_total_kwh - pv_feed_in
        result.eigenverbrauch_pct = max(0.0, min(100.0,
            (pv_self_consumed / result.pv_total_kwh) * 100.0))
    else:
        result.eigenverbrauch_pct = 0.0

    # Autarkiegrad
    if result.load_total_kwh > 0:
        self_supplied = max(0.0, result.load_total_kwh - result.grid_buy_total_kwh)
        result.autarkie_pct = max(0.0, min(100.0,
            (self_supplied / result.load_total_kwh) * 100.0))
    else:
        result.autarkie_pct = 0.0

    # Kosten
    result.grid_buy_cost_eur = float(
        np.sum(result.grid_buy_kw * inp.prices_ct_kwh * dt_h) / 100.0
    )
    result.feed_in_revenue_eur = float(
        np.sum(result.grid_sell_kw * inp.feed_in_tariff_ct_kwh * dt_h) / 100.0
    )
    result.total_cost_eur = result.grid_buy_cost_eur - result.feed_in_revenue_eur

    return result
