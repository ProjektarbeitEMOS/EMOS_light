"""Naive Baseline-Strategie ohne Optimierung fuer EMOS Light.

Berechnet Kosten bei einfacher Strategie:
- PV-Eigenverbrauch
- Batterie: Laden bei PV-Ueberschuss, Entladen bei Bedarf
- WP: Laeuft nach Bedarf (keine Preisoptimierung)
- Wallbox: Laedt sofort bei Ankunft

Zwei Funktionen:
- :func:`calculate_baseline_cost` — nur die Kosten (fuer Vergleich
  gegen den optimierten Plan)
- :func:`run_baseline` — vollstaendiges OptimizationResult mit allen
  Zeitreihen, damit die Baseline auch im Dashboard angezeigt werden
  kann wie ein Optimierungsergebnis
"""

import time

import numpy as np

from emos_light.core.types import OptimizationResult, TimeSeriesInput


def _is_hour_present(hour: int, arrival: int, departure: int) -> bool:
    """Ist das EV zur gegebenen Stunde anwesend? Identische Konvention wie
    in Wallbox._is_ev_present (Tag- vs. Nachtszenario je nach arrival/dep)."""
    if arrival <= departure:
        return arrival <= hour < departure
    return hour >= arrival or hour < departure


def _safe_wb_name(name: str) -> str:
    """Identisch zu Wallbox.__init__ — sorgt fuer konsistente Result-Keys
    zwischen MILP- und Baseline-Pfad (Dashboard-Plots lookupen darueber)."""
    return name.replace(" ", "_").replace("-", "_")


def calculate_baseline_cost(inp: TimeSeriesInput, config: dict) -> float:
    """Berechnet die Energiekosten der Baseline-Strategie.

    Delegiert an :func:`run_baseline`, damit es nur **eine** Quelle der
    Wahrheit gibt — frueher waren das zwei parallele Implementierungen,
    die bei jeder Aenderung am Regler synchron gehalten werden mussten.
    """
    return run_baseline(inp, config).total_cost_eur


def run_baseline(inp: TimeSeriesInput, config: dict) -> OptimizationResult:
    """Simuliert die Baseline-Strategie und liefert ein vollstaendiges
    :class:`OptimizationResult` (analog zum MILP-Optimizer).

    Wird vom Dashboard genutzt, wenn der Nutzer "Baseline (regelbasiert)"
    auswaehlt — dann werden dieselben Plots und KPIs angezeigt wie bei
    MILP/MPC, aber auf Basis von einfachen Regeln:

    - **WP mit Hysterese-Regelung** auf die thermischen Speicher:
        * Normalerweise aus.
        * Startet, sobald ein Speicher (Estrich oder Warmwasser) die
          untere Hysterese-Schwelle (25 % der nutzbaren Bandbreite)
          unterschreitet — d.h. droht, die Komfort-Untergrenze zu
          verletzen.
        * Laeuft dann mit voller Leistung, bis die obere Schwelle
          (95 %) erreicht ist.
        * Priorisierung: Warmwasser hat Vorrang vor Estrich
          (Brauchwasser ist zeitkritischer als Raumheizung, die
          mehrere Stunden Reserve im Estrich hat).
        * Fallback ohne Speicher: WP deckt heating+hw 1:1 mit
          gewichtetem COP (alte Logik).
    - **Wallboxen** laden sofort bei Ankunft mit voller Leistung,
      gefiltert ueber den Strompreis-Perzentil (preisgesteuerte
      Strategie aus Punkt 2 der Aufgabenliste).
    - **Batterie** laedt mit PV-Ueberschuss, entlaedt bei Restbedarf.
    - Restenergie geht ins/aus dem Netz.
    """
    t_start = time.time()
    num_steps = len(inp.prices_ct_kwh)
    dt_h = inp.step_minutes / 60.0

    # Batterie-Parameter
    batt_cfg = config.get("battery", {})
    batt_enabled = batt_cfg.get("enabled", False)
    batt_capacity = batt_cfg.get("capacity_kwh", 0.0)
    batt_max_charge = batt_cfg.get("max_charge_power_kw", 0.0)
    batt_max_discharge = batt_cfg.get("max_discharge_power_kw", 0.0)
    batt_charge_eff = batt_cfg.get("charge_efficiency", 0.95)
    batt_discharge_eff = batt_cfg.get("discharge_efficiency", 0.95)
    batt_min_soc = batt_cfg.get("min_soc", 0.1)
    batt_max_soc = batt_cfg.get("max_soc", 0.9)
    batt_soc = (
        batt_cfg.get("initial_soc", 0.5) * batt_capacity if batt_enabled else 0.0
    )

    # WP-Parameter
    hp_cfg = config.get("heat_pump", {})
    hp_enabled = hp_cfg.get("enabled", False)
    hp_max_power = hp_cfg.get("max_electrical_power_kw", 0.0)

    cop_heating = None
    cop_dhw = None
    if hp_enabled:
        from emos_light.components.heat_pump import HeatPump
        hp_baseline = HeatPump("baseline_hp", hp_cfg)
        cop_heating = hp_baseline.calculate_cop_heating(inp.outside_temp_c)
        cop_dhw = hp_baseline.calculate_cop_dhw(inp.outside_temp_c)

    wallboxes_cfg = config.get("wallboxes", [])

    # --- Thermische Speicher fuer Hysterese-Regelung ---
    # FBH (Estrich) und WW-Pufferspeicher koennen die WP-Schaltung steuern.
    # Beide sind nur aktiv, wenn die WP aktiviert ist.
    ufh_cfg = config.get("underfloor_heating", {})
    ufh_active = ufh_cfg.get("enabled", False) and hp_enabled
    ufh_obj = None
    floor_e = 0.0
    floor_cap = 0.0
    floor_low_e = 0.0
    floor_high_e = 0.0
    if ufh_active:
        from emos_light.components.underfloor_heating import UnderfloorHeating
        ufh_obj = UnderfloorHeating("baseline_ufh", ufh_cfg)
        floor_e = ufh_obj.initial_energy_kwh
        floor_cap = ufh_obj.total_capacity_kwh
        # Hysterese: 25 % unterhalb T_max startet, 95 % stoppt
        floor_low_e = floor_cap * 0.25
        floor_high_e = floor_cap * 0.95

    ww_cfg = config.get("hot_water_storage", {})
    fws_cfg = config.get("fresh_water_station", {})
    ww_active = ww_cfg.get("enabled", False) and hp_enabled
    ts_obj = None
    fws_efficiency = 1.0
    ww_e = 0.0
    ww_cap = 0.0
    ww_low_e = 0.0
    ww_high_e = 0.0
    if ww_active:
        from emos_light.components.thermal_storage import ThermalStorage
        ts_obj = ThermalStorage("baseline_ww", ww_cfg, prefix="ww")
        ww_e = ts_obj.initial_energy_kwh
        ww_cap = ts_obj.capacity_kwh
        # Hysterese-Schwellen physikalisch sinnvoll waehlen, damit der
        # Speicher nicht unter die Komfort-/Hygienegrenze faellt:
        # Untergrenze = max(T_min + 10 K, T_komfort - 5 K)
        ww_low_temp = max(
            ts_obj.min_temp_c + 10.0,
            (ts_obj.comfort_temp_c or 0) - 5.0,
        )
        ww_low_e = ts_obj.temp_to_energy(ww_low_temp)
        ww_high_e = ww_cap  # bis T_max nachladen
        if fws_cfg.get("enabled", False):
            from emos_light.components.fresh_water_station import FreshWaterStation
            _fws = FreshWaterStation("baseline_fws", fws_cfg)
            fws_efficiency = _fws.efficiency if _fws.efficiency > 0 else 1.0

    # Hysterese-Zustand: "OFF" | "FLOOR" | "WW"
    hp_state = "OFF"

    # Zeitreihen vorbereiten
    grid_buy_all = np.zeros(num_steps)
    grid_sell_all = np.zeros(num_steps)
    hp_power_all = np.zeros(num_steps)
    batt_charge_all = np.zeros(num_steps)
    batt_discharge_all = np.zeros(num_steps)
    batt_soc_all = np.zeros(num_steps)
    floor_energy_all = np.zeros(num_steps) if ufh_active else None
    ww_energy_all = np.zeros(num_steps) if ww_active else None
    q_floor_all = np.zeros(num_steps)
    q_ww_all = np.zeros(num_steps)
    wallbox_power_all: dict = {}
    # Pro Wallbox die Preis-Schwelle fuer die preisgesteuerte Ladestrategie:
    # Nur in den guenstigsten X % der Strompreise **innerhalb der
    # Anwesenheit** des Fahrzeugs laden (analog zur MILP-Implementierung
    # in Wallbox.prepare). Dadurch gibt es immer Lade-Slots — auch wenn
    # die Anwesenheit in eine objektiv teure Tageszeit faellt.
    wallbox_price_threshold: dict = {}
    steps_per_hour_baseline = max(1, 60 // inp.step_minutes)
    for wb_cfg in wallboxes_cfg:
        if wb_cfg.get("enabled", False):
            # Result-Key mit gleichem safe_name wie die MILP-Wallbox-Komponente
            # (Wallbox.__init__ normalisiert Leerzeichen/Bindestriche zu '_').
            # Wichtig fuer Dashboard-Plots, die den Wallbox-Cfg via safe-Name
            # zurueckmappen — wuerde sonst nur fuer MILP-Results funktionieren.
            name = _safe_wb_name(
                wb_cfg.get("name", f"wb_{len(wallbox_power_all)}")
            )
            wallbox_power_all[name] = np.zeros(num_steps)
            pct = float(wb_cfg.get("charge_only_below_percentile_pct", 100.0))
            if pct < 100.0:
                # Preise nur fuer Anwesenheits-Slots sammeln
                arrival = wb_cfg.get("arrival_hour", 17)
                departure = wb_cfg.get("departure_hour", 7)
                present_prices = [
                    float(inp.prices_ct_kwh[t])
                    for t in range(num_steps)
                    if _is_hour_present(
                        (t // steps_per_hour_baseline) % 24,
                        arrival, departure,
                    )
                ]
                if present_prices:
                    wallbox_price_threshold[name] = float(
                        np.percentile(present_prices, pct)
                    )
                else:
                    wallbox_price_threshold[name] = float("-inf")
            else:
                wallbox_price_threshold[name] = float("inf")

    total_cost_ct = 0.0
    feed_in_tariff = inp.feed_in_tariff_ct_kwh

    for t in range(num_steps):
        pv = float(inp.pv_generation_kw[t])
        load = float(inp.household_load_kw[t])
        price = float(inp.prices_ct_kwh[t])

        # WP-Steuerung
        hp_el = 0.0
        q_to_floor = 0.0
        q_to_ww = 0.0

        if hp_enabled and cop_heating is not None and (ufh_active or ww_active):
            # ---- Hysterese-Modus auf den thermischen Speichern ----
            # Verluste/Bedarf pro Speicher vorab
            floor_loss_kw = (
                ufh_obj.loss_rate_per_h * floor_e if ufh_active else 0.0
            )
            ww_demand_kw = 0.0
            ww_standby_loss_kw = 0.0
            if ww_active:
                ww_demand_kw = float(inp.hot_water_demand_kw[t]) / fws_efficiency
                ww_standby_loss_kw = (
                    ts_obj.fixed_loss_kw
                    + ts_obj.relative_loss_per_h * ww_e
                )

            # Hysterese-Logik: Statemaschine
            # Priorisierung: WW vor FBH (Brauchwasser zeitkritischer)
            if hp_state == "WW" and (not ww_active or ww_e >= ww_high_e):
                hp_state = "OFF"
            elif hp_state == "FLOOR" and (
                not ufh_active or floor_e >= floor_high_e
            ):
                hp_state = "OFF"

            if hp_state == "OFF":
                if ww_active and ww_e < ww_low_e:
                    hp_state = "WW"
                elif ufh_active and floor_e < floor_low_e:
                    hp_state = "FLOOR"

            # Leistung gemaess State
            if hp_state == "WW":
                hp_el = hp_max_power
                q_to_ww = hp_el * float(cop_dhw[t])
            elif hp_state == "FLOOR":
                hp_el = hp_max_power
                q_to_floor = hp_el * float(cop_heating[t])

            # Speicher updaten
            if ufh_active:
                floor_e = floor_e + (q_to_floor - floor_loss_kw) * dt_h
                floor_e = max(0.0, min(floor_e, floor_cap))
                floor_energy_all[t] = floor_e
            if ww_active:
                ww_e = ww_e + (q_to_ww - ww_demand_kw - ww_standby_loss_kw) * dt_h
                ww_e = max(0.0, min(ww_e, ww_cap))
                ww_energy_all[t] = ww_e

        elif hp_enabled and cop_heating is not None:
            # ---- Fallback ohne Speicher: WP deckt heating + hw direkt ----
            heating_kw = float(inp.heating_demand_kw[t])
            hw_kw = float(inp.hot_water_demand_kw[t])
            heat_demand = heating_kw + hw_kw
            if heat_demand > 0:
                cop = (
                    heating_kw * float(cop_heating[t])
                    + hw_kw * float(cop_dhw[t])
                ) / heat_demand
                hp_el = min(heat_demand / cop, hp_max_power)

        hp_power_all[t] = hp_el
        q_floor_all[t] = q_to_floor
        q_ww_all[t] = q_to_ww

        # Wallboxen — sofort laden, wenn EV anwesend UND Preisfilter okay
        wb_total = 0.0
        for wb_cfg in wallboxes_cfg:
            if not wb_cfg.get("enabled", False):
                continue
            hour = (t * inp.step_minutes) // 60
            arrival = wb_cfg.get("arrival_hour", 18)
            departure = wb_cfg.get("departure_hour", 7)
            ev_present = (
                hour >= arrival or hour < departure
                if arrival > departure
                else arrival <= hour < departure
            )
            name = _safe_wb_name(
                wb_cfg.get("name", f"wb_{len(wallbox_power_all)}")
            )
            # Preisfilter: nur laden, wenn Preis unter der Tages-Schwelle
            price_ok = price <= wallbox_price_threshold.get(name, float("inf"))
            wb_power = (
                wb_cfg.get("max_power_kw", 0.0)
                if (ev_present and price_ok) else 0.0
            )
            wallbox_power_all[name][t] = wb_power
            wb_total += wb_power

        # Bilanz
        total_demand = load + hp_el + wb_total
        pv_self_use = min(pv, total_demand)
        residual_demand = total_demand - pv_self_use
        pv_surplus = pv - pv_self_use

        batt_charge = 0.0
        batt_discharge = 0.0

        if batt_enabled and pv_surplus > 0:
            max_charge = min(
                batt_max_charge,
                pv_surplus,
                (batt_max_soc * batt_capacity - batt_soc) / (batt_charge_eff * dt_h),
            )
            batt_charge = max(0.0, max_charge)
            pv_surplus -= batt_charge
            batt_soc += batt_charge * batt_charge_eff * dt_h

        if batt_enabled and residual_demand > 0:
            max_discharge = min(
                batt_max_discharge,
                residual_demand,
                (batt_soc - batt_min_soc * batt_capacity) * batt_discharge_eff / dt_h,
            )
            batt_discharge = max(0.0, max_discharge)
            residual_demand -= batt_discharge
            batt_soc -= batt_discharge / batt_discharge_eff * dt_h

        batt_charge_all[t] = batt_charge
        batt_discharge_all[t] = batt_discharge
        batt_soc_all[t] = batt_soc

        grid_buy = max(0.0, residual_demand)
        grid_sell = max(0.0, pv_surplus)
        grid_buy_all[t] = grid_buy
        grid_sell_all[t] = grid_sell

        total_cost_ct += grid_buy * price * dt_h - grid_sell * feed_in_tariff * dt_h

    result = OptimizationResult(
        success=True,
        solver_status="Baseline",
        solve_time_s=time.time() - t_start,
        total_cost_eur=total_cost_ct / 100.0,
        grid_buy_kw=grid_buy_all,
        grid_sell_kw=grid_sell_all,
        batt_charge_kw=batt_charge_all,
        batt_discharge_kw=batt_discharge_all,
        batt_soc_kwh=batt_soc_all,
        hp_power_kw=hp_power_all,
        wallbox_power_kw=wallbox_power_all,
        timestamps=inp.timestamps,
    )

    # Thermische Trajektorien — analog zum MILP-Result, damit das Dashboard
    # die gleichen Plots zeichnen kann.
    if ufh_active and floor_energy_all is not None:
        result.floor_energy_kwh = floor_energy_all
        result.floor_temp_c = np.array(
            [ufh_obj.energy_to_temp(e) for e in floor_energy_all]
        )
        result.q_floor_kw = q_floor_all
    if ww_active and ww_energy_all is not None:
        result.ww_storage_energy_kwh = ww_energy_all
        result.ww_storage_temp_c = np.array(
            [ts_obj.energy_to_temp(e) for e in ww_energy_all]
        )
        result.q_ww_kw = q_ww_all

    # KPIs anwenden (Eigenverbrauch, Autarkie etc.)
    from emos_light.utils.kpi import calculate_kpis
    result = calculate_kpis(result, inp)
    result.solver_status = "Baseline"
    return result
