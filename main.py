"""EMOS Light — CLI Entry Point.

Nutzung:
    python main.py                        # Morgen, synthetische Daten
    python main.py --date 2026-04-15      # Bestimmtes Datum
    python main.py --api                  # Echte API-Daten
    python main.py --mpc                  # MPC-Modus
    python main.py --config meine.yaml    # Eigene Konfiguration
    python main.py --dashboard            # Streamlit Dashboard starten
"""

import argparse
import datetime
import sys

from emos_light.core.config import load_config
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    load_input_data,
    build_time_series_input,
)
from emos_light.optimization.baseline import calculate_baseline_cost
from emos_light.optimization.mpc import MPCController


def main():
    parser = argparse.ArgumentParser(description="EMOS Light — Energieoptimierung Neubau")
    parser.add_argument("--config", type=str, default=None, help="Pfad zur YAML-Konfiguration")
    parser.add_argument("--date", type=str, default=None, help="Optimierungsdatum (YYYY-MM-DD)")
    parser.add_argument("--api", action="store_true", help="Echte API-Daten verwenden")
    parser.add_argument("--mpc", action="store_true", help="MPC-Modus statt Day-Ahead")
    parser.add_argument("--dashboard", action="store_true", help="Streamlit Dashboard starten")
    args = parser.parse_args()

    if args.dashboard:
        import subprocess
        subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py"])
        return

    # Konfiguration laden
    config = load_config(args.config or "config/default_config.yaml")

    # Datum
    if args.date:
        opt_date = datetime.date.fromisoformat(args.date)
    else:
        opt_date = datetime.date.today() + datetime.timedelta(days=1)

    print(f"EMOS Light — Optimierung fuer {opt_date}")
    print(f"Modus: {'MPC' if args.mpc else 'Day-Ahead (MILP)'}")
    print(f"Datenquelle: {'API' if args.api else 'Synthetisch'}")
    print()

    # Daten laden
    data = load_input_data(config, opt_date, args.api)
    inp = build_time_series_input(config, data)

    print(f"Zeitschritte: {data['num_steps']} ({data['step_minutes']} min)")
    print(f"PV-Tagesertrag: {sum(data['pv_generation']) * data['step_minutes']/60:.1f} kWh")
    print(f"Haushaltslast: {sum(data['household_load']) * data['step_minutes']/60:.1f} kWh")
    print(f"Heizwaerme: {sum(data['heating_demand']) * data['step_minutes']/60:.1f} kWh")
    print(f"Warmwasser: {sum(data['hw_demand']) * data['step_minutes']/60:.1f} kWh")
    print()

    # Komponenten erstellen
    components = build_components(config)
    optimizer = build_optimizer(components)

    # Optimierung
    if args.mpc:
        mpc = MPCController(optimizer, horizon_hours=6, execute_hours=1)
        result = mpc.run_mpc(inp)
    else:
        result = optimizer.optimize(inp)

    if not result.success:
        print(f"Optimierung fehlgeschlagen: {result.solver_status}")
        sys.exit(1)

    # Baseline
    baseline = calculate_baseline_cost(inp, config)
    savings = baseline - result.total_cost_eur

    print("=== Ergebnis ===")
    print(f"Gesamtkosten (optimiert): {result.total_cost_eur:.2f} EUR")
    print(f"Baseline-Kosten:          {baseline:.2f} EUR")
    print(f"Einsparung:               {savings:.2f} EUR ({savings/baseline*100:.0f}%)" if baseline > 0 else "")
    print()
    print(f"Eigenverbrauch:  {result.eigenverbrauch_pct:.1f}%")
    print(f"Autarkie:        {result.autarkie_pct:.1f}%")
    print(f"PV-Ertrag:       {result.pv_total_kwh:.1f} kWh")
    print(f"Netzbezug:       {result.grid_buy_total_kwh:.1f} kWh")
    print(f"Einspeisung:     {result.grid_sell_total_kwh:.1f} kWh")
    print(f"WP-Verbrauch:    {result.hp_total_kwh:.1f} kWh (el.)")
    print(f"Loesungszeit:    {result.solve_time_s:.1f}s")


if __name__ == "__main__":
    main()
