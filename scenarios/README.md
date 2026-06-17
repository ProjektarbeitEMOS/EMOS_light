# EMOS Light Szenario-Tests

Diese Dateien sind Testdaten fuer die YAML-basierte Testschnittstelle.
Sie ueberschreiben gezielt Konfiguration und Eingabe-Zeitreihen und pruefen
danach automatisch, ob das EMOS erwartbar reagiert.

## Ausfuehren

```powershell
python scripts/run_test_scenario.py scenarios/battery_pv_surplus.yaml
python scripts/run_test_scenario.py (Get-ChildItem scenarios\*.yaml).FullName
python scripts/run_test_scenario.py scenarios/battery_pv_surplus.yaml --json
```

## Enthaltene Szenarien

| Datei | Zweck |
|---|---|
| `battery_pv_surplus.yaml` | PV-Ueberschuss mittags, teure Abendstunden: Batterie soll laden/entladen. |
| `battery_negative_prices.yaml` | Negative Nachtpreise: Batterie soll in guenstigen Stunden laden. |
| `pv_ac_clipping.yaml` | Hohe PV-Erzeugung mit begrenzter Anlage: PV/Batterie-Verhalten pruefen. |
| `ev_negative_prices.yaml` | E-Auto mit negativen Nachtpreisen: Wallbox soll guenstig laden. |
| `ev_impossible_departure.yaml` | Bewusst unmoegliches E-Auto-Ziel: System soll Nicht-Loesbarkeit erkennen. |
| `winter_no_pv_heat_pump.yaml` | Kalter Wintertag ohne PV: Waermepumpe, Gebaeude und Warmwasser pruefen. |
| `heat_pump_extreme_cold.yaml` | Extrem kalter Tag: WP-Leistung und Komfort pruefen. |
| `warm_water_morning_evening.yaml` | Warmwasserbedarf morgens/abends: Speicherkomfort pruefen. |
| `grid_limit_full_house.yaml` | Vollhaus mit begrenztem Netzanschluss: Netzlimit und flexible Lasten pruefen. |
| `load_spike_no_battery.yaml` | Abendliche Lastspitze ohne Batterie: Netzbezug plausibilisieren. |
| `no_pv_no_flex_baseline_like.yaml` | Minimalfall ohne Flexibilitaet: reine Haushaltslast pruefen. |
| `mpc_price_shift.yaml` | Rollierender MPC-Modus mit Preisverschiebung: MPC-Smoke-Test. |
| `missing_pv_battery_hp_wb.yaml` | Vollhaus ohne PV: Batterie, WP und Wallbox muessen ohne lokale Erzeugung laufen. |
| `missing_battery_pv_hp_wb.yaml` | Vollhaus ohne Batterie: PV, WP und Wallbox muessen ohne Speicher laufen. |
| `missing_wallbox_pv_battery_hp.yaml` | Haus ohne Wallbox/E-Auto: PV, Batterie und WP muessen allein funktionieren. |
| `missing_heat_pump_pv_battery_wb.yaml` | Haus ohne Waermepumpe: rein elektrischer Betrieb mit PV, Batterie und Wallbox. |
| `missing_pv_battery_wallbox_heatpump.yaml` | Minimalfall ohne PV, Batterie, Wallbox und WP: nur Haushaltslast. |
| `pv_only_no_storage_no_hp_no_wb.yaml` | Nur PV und Haushaltslast: keine Batterie, keine WP, keine Wallbox. |
| `heat_pump_only_no_pv_battery_wb.yaml` | Nur thermischer Betrieb: WP mit Gebaeude/WW, aber ohne PV, Batterie und Wallbox. |

## Aufbau einer Szenario-Datei

```yaml
name: eigener_test
date: 2026-06-15
mode: milp  # milp, baseline oder mpc

components:
  pv: true
  battery: true
  heat_pump: false

config_overrides:
  general:
    optimization_horizon_hours: 24

input_overrides:
  prices_ct_kwh:
    default: 35
    windows:
      - start: "01:00"
        end: "05:00"
        value: -5
  pv_generation_kw:
    default: 0
    windows:
      - start: "10:00"
        end: "15:00"
        value: 8

checks:
  - type: success
    expected: true
  - type: series_max
    field: batt_soc_kwh
    op: "<="
    value: 9.0
```

## Unterstuetzte Eingabe-Zeitreihen

- `prices_ct_kwh`
- `spot_prices_ct_kwh`
- `outside_temp_c`
- `ghi_w_m2`
- `wind_speed_m_s`
- `pv_generation_kw`
- `household_load_kw`
- `heating_demand_kw`
- `hot_water_demand_kw`

Zeitreihen koennen als einzelner Wert, als Liste oder als `default` plus
Zeitfenster angegeben werden.

## Unterstuetzte Checks

- `success`: prueft, ob Solverlauf erfolgreich oder bewusst nicht erfolgreich war.
- `metric`: vergleicht ein einzelnes Ergebnisfeld, z.B. `hp_starts_count`.
- `series_min`: prueft den Minimalwert einer Ergebniszeitreihe.
- `series_max`: prueft den Maximalwert einer Ergebniszeitreihe.
- `window_sum`: summiert eine Leistung in einem Zeitfenster zu kWh.
- `no_simultaneous_battery`: prueft, dass Batterie nicht gleichzeitig laedt und entlaedt.
- `ev_soc_at_departure`: prueft EV-SOC zur Abfahrtszeit.

Felder in Dictionaries werden per Punktnotation angesprochen, z.B.
`wallbox_power_kw.Wallbox 1`.
