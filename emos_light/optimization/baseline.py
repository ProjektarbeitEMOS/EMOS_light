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
        * Bei **aktivem Gebaeudemodell** (``building.enabled = True``,
          seit Mai 2026): Hysterese auf der **Raumlufttemperatur**
          T_innen — startet, wenn T_innen unter (comfort_min + 1 K)
          faellt, stoppt bei (comfort_max - 1 K). Estrichbilanz wird
          dann mit dem expliziten Waermestrom Estrich->Raum gefuehrt
          (MILP-Modell):
              q_floor_to_room = h*A/1000 * (T_floor[t-1] - T_innen[t-1])
              C_room * dT_innen/dt = q_floor_to_room - UA/1000 * (T_innen[t-1] - T_aus[t])
        * **Ohne Gebaeudemodell** (Fallback, kompatibel zu pre-Mai-2026):
          Hysterese auf der **Estrich-Energie** — 25 % unterhalb T_max
          startet, 95 % stoppt. Estrichbilanz mit linearer Verlustrate.
        * Warmwasserspeicher: Hysterese auf der WW-Energie unverändert.
        * Priorisierung: Warmwasser hat Vorrang vor Estrich
          (Brauchwasser ist zeitkritischer als Raumheizung, die
          mehrere Stunden Reserve im Estrich hat).
        * Fallback ohne Speicher: WP deckt heating+hw 1:1 mit
          gewichtetem COP (alte Logik).
    - **Wallboxen** laden sofort bei Ankunft mit voller Leistung, bis
      das EV abfaehrt — KEIN Preis- oder Perzentil-Filter. Der Perzentil-
      Slider und das Mindestreichweite-Constraint sind reine Optimierungs-
      features (MILP/MPC). In der Baseline-Referenz waeren sie unfair,
      weil dann schon ein Teil der Optimierung in der Vergleichsstrategie
      drin waere.
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
    # Pro Zeitschritt eine separate Untergrenze (Komfort-Perioden anheben):
    # in Komfortzeit Mindestenergie = comfort_temperature_c-Aequivalent,
    # ausserhalb = min_temperature_c-Aequivalent.
    ww_low_schedule_kwh: list[float] | None = None

    if ww_active:
        from emos_light.components.thermal_storage import ThermalStorage
        ts_obj = ThermalStorage("baseline_ww", ww_cfg, prefix="ww")
        ww_e = ts_obj.initial_energy_kwh
        ww_cap = ts_obj.capacity_kwh
        # Komfort-aware Untergrenze:
        # 1. Basis-Sicherheitspuffer: max(T_min + 10 K, T_komfort - 5 K)
        # 2. ZUSAETZLICH pro Zeitschritt aus get_min_energy_schedule —
        #    haebt die Grenze waehrend Komfortzeit auf comfort_temp_c.
        # Effektiv low_e[t] = max(static_base, schedule[t]).
        static_low_temp = max(
            ts_obj.min_temp_c + 10.0,
            (ts_obj.comfort_temp_c or 0) - 5.0,
        )
        static_low_e = ts_obj.temp_to_energy(static_low_temp)
        schedule = ts_obj.get_min_energy_schedule(inp.timestamps)
        ww_low_schedule_kwh = [max(static_low_e, s) for s in schedule]
        # ww_low_e wird in der Hauptschleife je Zeitschritt gelesen;
        # halte den statischen Wert als Fallback (z.B. wenn das Schedule
        # leer ist).
        ww_low_e = static_low_e
        ww_high_e = ww_cap  # bis T_max nachladen
        if fws_cfg.get("enabled", False):
            from emos_light.components.fresh_water_station import FreshWaterStation
            _fws = FreshWaterStation("baseline_fws", fws_cfg)
            fws_efficiency = _fws.efficiency if _fws.efficiency > 0 else 1.0

    # --- Gebaeude-Raumluftmodell (Mai 2026 — analog zum MILP-Optimizer) ---
    # Wenn Building aktiv ist (und WP+FBH ebenfalls), wird die Hysterese
    # nicht mehr auf der Estrich-Energie ausgewertet, sondern auf der
    # Raumlufttemperatur T_innen. Estrichbilanz und Raumbilanz werden
    # explizit gekoppelt (gleiches Modell wie in Building.heat_demand).
    building_cfg = config.get("building", {})
    building_active = (
        building_cfg.get("enabled", False) and hp_enabled and ufh_active
    )
    building_obj = None
    t_innen = 0.0
    c_room_kwh_per_k = 0.0
    ua_kw_per_k = 0.0
    t_innen_low = 0.0
    t_innen_high = 0.0
    indoor_temp_all = None
    heat_loss_all = None
    q_floor_to_room_all = None
    if building_active:
        from emos_light.components.building import Building
        building_obj = Building("baseline_building", building_cfg)
        t_innen = building_obj.indoor_temp
        c_room_kwh_per_k = building_obj.shell_capacity_kwh_per_k
        ua_kw_per_k = building_obj.ua_w_per_k / 1000.0
        # Hysterese-Schwellen auf T_innen: 1 K Sicherheitsband innerhalb
        # des Komfortbands, damit der traege Estrich nicht ueber-/
        # unterschiesst (in einem Schritt fliesst nur wenig Waerme in
        # den Raum, aber dafuer auch nach dem WP-Ausschalten noch lange).
        t_innen_low = building_obj.comfort_temp_min_c + 1.0
        t_innen_high = building_obj.comfort_temp_max_c - 1.0
        indoor_temp_all = np.zeros(num_steps)
        heat_loss_all = np.zeros(num_steps)
        q_floor_to_room_all = np.zeros(num_steps)

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
    # Wallbox-Result-Keys vorbereiten + EV-SOC-State pro Wallbox.
    # Hinweis: Der Strompreis-Perzentil-Filter wird in der BASELINE bewusst
    # nicht angewendet — die Baseline ist die naive Referenzstrategie
    # ("plug in & charge until full"), gegen die MILP/MPC ihre Einsparung
    # messen. Wuerde sie den Filter mit anwenden, waere der Vergleich
    # unfair: schon ein Teil der Optimierung waere in der Referenz drin.
    # Was die Baseline aber sehr wohl modelliert: die physische Akku-
    # Obergrenze (max_soc) — sobald das Auto voll ist, hoert die
    # Wallbox auf zu laden.
    ev_soc_kwh: dict = {}   # safe_name -> aktueller SOC (kWh, DC-seitig)
    ev_max_kwh: dict = {}   # safe_name -> max_soc * capacity (Obergrenze)
    for wb_cfg in wallboxes_cfg:
        if wb_cfg.get("enabled", False):
            name = _safe_wb_name(
                wb_cfg.get("name", f"wb_{len(wallbox_power_all)}")
            )
            wallbox_power_all[name] = np.zeros(num_steps)
            cap = float(wb_cfg.get("ev_battery_capacity_kwh", 60.0))
            current = float(wb_cfg.get("current_soc", 0.3))
            max_soc = float(wb_cfg.get("max_soc", 1.0))
            ev_soc_kwh[name] = current * cap
            ev_max_kwh[name] = max_soc * cap

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
            # Verluste/Bedarf pro Speicher vorab.
            # Floor->Raum-Waermestrom:
            #  - Bei aktivem Building (Mai 2026): explizit aus T_floor und
            #    T_innen nach MILP-Modell. Floor-Verlust ist hier nicht
            #    mehr ``loss_rate*E``, sondern der physikalische Strom in
            #    den Raum (kann auch negativ werden, dann fliesst Waerme
            #    vom Raum in den Estrich).
            #  - Sonst Fallback auf das lineare Verlustratenmodell, das
            #    den Verlust direkt auf die Estrich-Energie bezieht.
            if building_active:
                t_floor_prev = ufh_obj.energy_to_temp(floor_e)
                q_floor_to_room = (
                    ufh_obj.h_surface * ufh_obj.area_m2 / 1000.0
                    * (t_floor_prev - t_innen)
                )
            else:
                q_floor_to_room = (
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

            # WW-Untergrenze ZEITABHAENGIG: in Komfortzeit angehoben
            # auf comfort_temperature_c (ueber get_min_energy_schedule).
            ww_low_e_t = (
                ww_low_schedule_kwh[t]
                if ww_active and ww_low_schedule_kwh is not None
                else ww_low_e
            )

            # Hysterese-Logik: Statemaschine.
            # Priorisierung: WW vor FBH (Brauchwasser zeitkritischer).
            # FBH-Kriterium:
            #  - building_active: auf T_innen (MILP-konsistente Regelgroesse)
            #  - sonst: auf Estrich-Energie (alte Logik)
            if hp_state == "WW" and (not ww_active or ww_e >= ww_high_e):
                hp_state = "OFF"
            elif hp_state == "FLOOR":
                if building_active:
                    if t_innen >= t_innen_high or floor_e >= floor_cap:
                        hp_state = "OFF"
                elif not ufh_active or floor_e >= floor_high_e:
                    hp_state = "OFF"

            if hp_state == "OFF":
                if ww_active and ww_e < ww_low_e_t:
                    hp_state = "WW"
                elif ufh_active:
                    if building_active:
                        if t_innen < t_innen_low:
                            hp_state = "FLOOR"
                    elif floor_e < floor_low_e:
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
                floor_e = floor_e + (q_to_floor - q_floor_to_room) * dt_h
                floor_e = max(0.0, min(floor_e, floor_cap))
                floor_energy_all[t] = floor_e
            if ww_active:
                ww_e = ww_e + (q_to_ww - ww_demand_kw - ww_standby_loss_kw) * dt_h
                ww_e = max(0.0, min(ww_e, ww_cap))
                ww_energy_all[t] = ww_e

            # Raumluft-Bilanz (nur bei aktivem Building) — explizites Euler,
            # identisches Modell wie der MILP-Optimizer in Building.heat_demand.
            if building_active:
                q_loss = ua_kw_per_k * (
                    t_innen - float(inp.outside_temp_c[t])
                )
                t_innen = t_innen + (
                    q_floor_to_room - q_loss
                ) * dt_h / c_room_kwh_per_k
                indoor_temp_all[t] = t_innen
                heat_loss_all[t] = q_loss
                q_floor_to_room_all[t] = q_floor_to_room

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

        # Wallboxen — sofort laden, wenn EV anwesend UND der Akku noch
        # nicht voll ist (kein Preisfilter in der Baseline).
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
            eff = float(wb_cfg.get("charging_efficiency", 0.92))
            max_kw = float(wb_cfg.get("max_power_kw", 0.0))

            wb_power = 0.0
            if ev_present:
                # Headroom bis max_soc (DC-Seite)
                headroom_dc = max(0.0, ev_max_kwh[name] - ev_soc_kwh[name])
                if headroom_dc > 1e-6:
                    # Wallbox liefert AC, Akku nimmt AC*eff auf.
                    # Maximale AC-Leistung, damit der Akku in diesem
                    # Schritt nicht ueber max_soc geht:
                    max_ac_kw = headroom_dc / (dt_h * eff)
                    wb_power = min(max_kw, max_ac_kw)
                    # SOC nachfuehren (DC-seitig)
                    ev_soc_kwh[name] += wb_power * dt_h * eff
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
    # Raumluftmodell (Mai 2026) — gleiche Result-Felder wie MILP, damit
    # die Dashboard-Plots ohne Sonderbehandlung beide Modi rendern.
    if building_active:
        result.indoor_temp_c = indoor_temp_all
        result.heat_loss_kw = heat_loss_all
        result.q_floor_to_room_kw = q_floor_to_room_all

    # Baseline plant nicht in die Zukunft — der gesamte simulierte Bereich
    # wird ohne Lookahead Schritt fuer Schritt abgefahren. Damit das
    # Dashboard fuer alle Modi dasselbe Planungs-Layout zeichnen kann,
    # geben wir ein einziges, deckungsgleiches Fenster zurueck.
    result.planning_windows = [{
        "start_step": 0,
        "exec_end_step": num_steps,
        "horizon_end_step": num_steps,
    }]

    # KPIs anwenden (Eigenverbrauch, Autarkie etc.)
    from emos_light.utils.kpi import calculate_kpis
    result = calculate_kpis(result, inp)
    result.solver_status = "Baseline"
    return result
