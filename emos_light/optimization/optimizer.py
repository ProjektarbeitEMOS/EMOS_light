"""MILP-Optimierungsengine fuer EMOS Light.

Thermische Topologie (Mai 2026):
    WP --+-- FBH --> Estrich (therm. Speicher) --> Raum (T_innen) --> Aussenluft
         +-- WW-Speicher --> Frischwasserstation --> Brauchwasser

Senken-Bilanzknoten:
    "floor": Estrich-Energiebilanz       (Komponente: UnderfloorHeating)
    "room":  Raumluft-Energiebilanz      (Komponente: Building)
    "ww":    WW-Speicher-Energiebilanz   (Komponente: ThermalStorage)

Entscheidungsvariablen (thermisch):
    hp_power[t]:            Elektrische WP-Leistung gesamt
    hp_power_floor[t]:      Anteil fuer FBH-Pfad (nur bei Mehrfach-Senken)
    hp_power_ww[t]:         Anteil fuer WW-Pfad  (nur bei Mehrfach-Senken)
    ufh_floor_energy[t]:    Thermische Energie im Estrich
    ufh_q_floor_in[t]:      Q_in der FBH (= Senkeneingang Estrich)
    ufh_q_floor_to_room[t]: Waermestrom Estrich -> Raum (nur mit Building)
    t_innen[t]:             Raumlufttemperatur (Building, MILP-Erweiterung Mai 2026)
    ww_energy_kwh[t]:       Thermische Energie im WW-Speicher
    ww_q_in[t]:             Q_in des WW-Speichers
    ww_q_demand[t]:         Q_out des WW-Speichers (an Frischwasserstation)
    hp_sg1[t]:              SG-Ready Zustand 1 (Lastabwurf)
    hp_sg3[t]:              SG-Ready Zustand 3 (Verstaerkt)

Bilanzgleichungen entstehen generisch ueber MILPComponent.heat_supply()
und MILPComponent.heat_demand() pro aktiver Senke.
"""

import time
from typing import Optional

import numpy as np
import pulp

from emos_light.components.pv import PVSystem
from emos_light.components.battery import Battery
from emos_light.components.building import Building
from emos_light.components.heat_pump import HeatPump
from emos_light.components.thermal_storage import ThermalStorage
from emos_light.components.fresh_water_station import FreshWaterStation
from emos_light.components.underfloor_heating import UnderfloorHeating
from emos_light.components.wallbox import Wallbox
from emos_light.core.types import TimeSeriesInput, OptimizationResult


UNMET_HEAT_PENALTY_CT = 500.0
# Strafkosten in ct/kWh fuer ungedeckten Warmwasserbedarf (Slack hat
# Einheit kW; multipliziert mit dt_h ergibt kWh, mit P_WW ergibt ct).
# Begruendung "Projektgruppe Penalty Slacks": WW ist Energie, nicht
# Temperatur — eigener Tarif, getrennt vom Raumkomfort.
P_WW = 150.0
# Strafkosten in ct/kWh fuer T_innen-Unterschreitungen, getrennt nach
# Komfortzone (bis 0.5 K unter Soll) und Notfallzone (darueber). Beide
# werden ueber die thermische Kapazitaet C_th in ct/K umgerechnet,
# damit die K-basierten Slacks auf einer mit ww_slack vergleichbaren
# Geldeinheit landen.
P_COMFORT = 100.0
P_CRITICAL = 300.0
# EV-Strafkosten fuer Laden in teuren Stunden (Soft-Preisfilter).
# Hoch genug, dass der Solver teure Stunden nur in echten Engpaessen
# anrechnet — sonst greift natuerlich der Cost-Minimizer.
PENALTY_EV_EXPENSIVE = 500.0


class EMOSLightOptimizer:
    """MILP-basierter Energieoptimizer fuer Neubau."""

    def __init__(
        self,
        pv: Optional[PVSystem] = None,
        battery: Optional[Battery] = None,
        heat_pump: Optional[HeatPump] = None,
        hot_water_storage: Optional[ThermalStorage] = None,
        fresh_water_station: Optional[FreshWaterStation] = None,
        underfloor_heating: Optional[UnderfloorHeating] = None,
        building: Optional[Building] = None,
        wallboxes: Optional[list[Wallbox]] = None,
        **kwargs,
    ):
        self.pv = pv
        self.battery = battery
        self.heat_pump = heat_pump
        self.hot_water_storage = hot_water_storage
        self.fresh_water_station = fresh_water_station
        self.underfloor_heating = underfloor_heating
        self.building = building
        self.wallboxes = wallboxes or []

    def optimize(self, inp: TimeSeriesInput) -> OptimizationResult:
        """Fuehrt die MILP-Optimierung durch."""
        t_start = time.time()
        num_steps = len(inp.prices_ct_kwh)
        dt_h = inp.step_minutes / 60.0

        model = pulp.LpProblem("EMOS_Light", pulp.LpMinimize)

        # ============================================================
        # Netz-Variablen
        # ============================================================
        grid_buy = [
            pulp.LpVariable(f"grid_buy_{t}", 0, inp.max_grid_power_kw)
            for t in range(num_steps)
        ]
        grid_sell = [
            pulp.LpVariable(f"grid_sell_{t}", 0, inp.max_grid_power_kw)
            for t in range(num_steps)
        ]
        grid_buy_on = [
            pulp.LpVariable(f"grid_buy_on_{t}", cat=pulp.LpBinary)
            for t in range(num_steps)
        ]
        for t in range(num_steps):
            model += grid_buy[t] <= inp.max_grid_power_kw * grid_buy_on[t], f"grid_buy_link_{t}"
            model += grid_sell[t] <= inp.max_grid_power_kw * (1 - grid_buy_on[t]), f"grid_sell_link_{t}"

        variables: dict = {"grid_buy": grid_buy, "grid_sell": grid_sell}

        # ============================================================
        # Phase A — Komponentenliste aufbauen (nur Referenzen sammeln)
        # ============================================================
        # Heizsenken (UFH, WW-Speicher) sind nur sinnvoll, wenn ueberhaupt
        # ein Waermeerzeuger existiert (siehe is_heat_supplier). Sonst
        # waeren sie abgekoppelte Knoten.
        has_fws = bool(self.fresh_water_station and self.fresh_water_station.enabled)

        # Erst alle potenziellen MILP-Komponenten sammeln
        candidates: list = []
        if self.battery and self.battery.enabled:
            candidates.append(self.battery)
        if self.heat_pump and self.heat_pump.enabled:
            candidates.append(self.heat_pump)
        if self.underfloor_heating and self.underfloor_heating.enabled:
            candidates.append(self.underfloor_heating)
        if self.hot_water_storage and self.hot_water_storage.enabled:
            candidates.append(self.hot_water_storage)
        # Building wirkt nur als Raum-Bilanzknoten (Senke "room"). Sein
        # Versorger ist UFH (Estrich -> Raum). UFH wiederum braucht die WP
        # als Erzeuger. Filter unten erledigt die Kette.
        if self.building and self.building.enabled:
            candidates.append(self.building)
        for wb in self.wallboxes:
            if wb.enabled:
                candidates.append(wb)

        # Wenn keine Waermeerzeuger existieren, Senken rausfiltern.
        # Speziell die Raum-Senke "room" braucht zusaetzlich einen
        # UFH-Versorger; ohne UFH bleibt der Raum-Knoten abgekoppelt.
        has_supplier = any(c.is_heat_supplier for c in candidates)
        has_ufh_active = any(
            isinstance(c, UnderfloorHeating) for c in candidates
        )

        def _keep(c) -> bool:
            if c.heat_sink_id is None:
                return True
            if c.heat_sink_id == "room":
                return has_supplier and has_ufh_active
            return has_supplier

        milp_components: list = [c for c in candidates if _keep(c)]
        active_wallboxes = [c for c in milp_components if isinstance(c, Wallbox)]
        has_hp = any(c.is_heat_supplier for c in milp_components)

        # ============================================================
        # Phase B — Vorbereitung mit Eingangsdaten (z.B. WP berechnet COP)
        # ============================================================
        for c in milp_components:
            c.prepare(inp)

        # ============================================================
        # Phase C — Aktive Waermesenken ermitteln und propagieren
        # ============================================================
        active_sinks = {
            c.heat_sink_id for c in milp_components
            if c.heat_sink_id is not None
        }
        for c in milp_components:
            c.set_active_heat_sinks(active_sinks)

        # ============================================================
        # Phase D — Variablen + Constraints jeder Komponente
        #
        # Aufgesplittet in D1 (alle Variablen) und D2 (alle Constraints),
        # damit cross-component-Referenzen unabhaengig von der
        # Iterationsreihenfolge funktionieren (z.B. UFH-Constraint auf
        # ``t_innen`` aus Building).
        # ============================================================
        for c in milp_components:
            comp_vars = c.get_optimization_variables(num_steps, model)
            variables.update(comp_vars)
        for c in milp_components:
            c.add_constraints(model, variables, inp.step_minutes)

        # Fallback: hp_power-Variable existiert immer (auch ohne aktive WP),
        # weil es an mehreren Stellen unten in der Auswertung gelesen wird.
        if "hp_power" not in variables:
            variables["hp_power"] = [
                pulp.LpVariable(f"hp_power_{t}", 0, 0) for t in range(num_steps)
            ]

        # ============================================================
        # Phase E — Generische Waermebilanz pro Senke
        #     Fuer jede aktive Senke s gilt: Σ heat_supply(s) == Σ heat_demand(s)
        # ============================================================
        for sink in active_sinks:
            for t in range(num_steps):
                supply = pulp.lpSum(
                    c.heat_supply(variables, t, sink) for c in milp_components
                )
                demand = pulp.lpSum(
                    c.heat_demand(variables, t, sink) for c in milp_components
                )
                model += supply == demand, f"heat_balance_{sink}_{t}"

        # ============================================================
        # Phase F — Senken-spezifische Komfort-/SG-Constraints, Slacks
        #     Diese koppeln die Senken an externe Bedarfe oder erlauben
        #     dem Solver, Komfort weich zu verletzen.
        # ============================================================
        ww_slack = None
        has_ww = self.hot_water_storage and self.hot_water_storage.enabled and has_hp
        has_ufh = self.underfloor_heating and self.underfloor_heating.enabled and has_hp

        if has_ww:
            prefix = self.hot_water_storage.prefix

            ww_slack = [
                pulp.LpVariable(f"ww_slack_{t}", 0) for t in range(num_steps)
            ]

            # Brauchwasserbedarf als Entnahme aus WW-Speicher
            if has_fws:
                fw_demand_kw = self.fresh_water_station.calculate_storage_demand(
                    inp.hot_water_demand_kw
                )
            else:
                fw_demand_kw = inp.hot_water_demand_kw

            for t in range(num_steps):
                model += (
                    variables[f"{prefix}_q_demand"][t] + ww_slack[t]
                    == float(fw_demand_kw[t]),
                    f"ww_demand_fix_{t}",
                )

            # Zeit-abhaengige Mindesttemperatur (Komfort-Perioden)
            min_energy_schedule = self.hot_water_storage.get_min_energy_schedule(
                inp.timestamps
            )
            for t in range(num_steps):
                model += (
                    variables[f"{prefix}_energy_kwh"][t] >= min_energy_schedule[t],
                    f"ww_min_energy_schedule_{t}",
                )

            # SG-Ready: Dynamische WW-Speicher-Obergrenze (BWP v1.1).
            # Sowohl sg3 (Einschaltempfehlung) als auch sg4 (Zwangsein-
            # schaltung) erlauben eine Sollwert-Ueberhoehung im
            # Warmwasserspeicher. Bei sg4 ist der Offset hoeher als bei
            # sg3 — typisch Default 10 K vs. 5 K, einstellbar 0..20 K.
            if self.heat_pump.sg_ready and "hp_sg3" in variables:
                sg3 = variables["hp_sg3"]
                sg4 = variables.get("hp_sg4")
                vol_factor = (
                    self.hot_water_storage.volume_liters
                    * ThermalStorage.SPECIFIC_HEAT_WH_PER_L_K
                    / 1000.0
                )
                delta_cap_3 = vol_factor * self.heat_pump.sg_temp_raise_3
                delta_cap_4 = vol_factor * self.heat_pump.sg_temp_raise_4
                # Hard-Bound der Variable lockern, sonst dominiert das
                # ``high=capacity_kwh`` aus ThermalStorage die SG-Constraint
                # und der WW-Boost waere unwirksam (analog zum FBH-Pfad
                # unten). sg3/sg4 sind ein-aus (sg1..sg4 summieren zu 1),
                # daher ist der maximale Offset max(delta_3, delta_4).
                ww_max_extra = (
                    delta_cap_3 if sg4 is None
                    else max(delta_cap_3, delta_cap_4)
                )
                ww_new_high = self.hot_water_storage.capacity_kwh + ww_max_extra
                for v in variables[f"{prefix}_energy_kwh"]:
                    v.upBound = ww_new_high
                for t in range(num_steps):
                    extra = delta_cap_3 * sg3[t]
                    if sg4 is not None:
                        extra = extra + delta_cap_4 * sg4[t]
                    model += (
                        variables[f"{prefix}_energy_kwh"][t]
                        <= self.hot_water_storage.capacity_kwh + extra,
                        f"ww_sg_ready_cap_{t}",
                    )

        if has_ufh:
            # SG-Ready Zustand 4: Pufferspeicher (= Estrich in EMOS Light)
            # ueberhoeht. PDF: "Heizbetrieb-Abweichung: ... kuenstliche
            # Waermeanforderung ... zur Aufladung des Pufferspeichers auf
            # den Sollwert und den variabel einstellbaren Offset 0..20 K."
            # Zustand 3 boostet den Estrich NICHT (PDF: "Wenn keine
            # Waermeanforderung vorliegt und Schaltzustand 3 anliegt,
            # findet keine Speicherladung im Heizbetrieb statt").
            if (
                self.heat_pump
                and self.heat_pump.sg_ready
                and "hp_sg4" in variables
                and "ufh_floor_energy" in variables
            ):
                sg4 = variables["hp_sg4"]
                cap_per_k = self.underfloor_heating.capacity_kwh_per_k
                delta_floor_4 = cap_per_k * self.heat_pump.sg_temp_raise_4
                # Hard-Bound der Variable lockern, damit der Solver das
                # Ueberschreiten ueberhaupt darstellen kann.
                new_high = (
                    self.underfloor_heating.total_capacity_kwh + delta_floor_4
                )
                for v in variables["ufh_floor_energy"]:
                    v.upBound = new_high
                for t in range(num_steps):
                    model += (
                        variables["ufh_floor_energy"][t]
                        <= self.underfloor_heating.total_capacity_kwh
                        + delta_floor_4 * sg4[t],
                        f"ufh_sg_ready_cap_{t}",
                    )

        # ============================================================
        # Elektrische Energiebilanz — generisch ueber milp_components
        # ============================================================
        for t in range(num_steps):
            supply = float(inp.pv_generation_kw[t]) + grid_buy[t]
            demand = float(inp.household_load_kw[t]) + grid_sell[t]

            for c in milp_components:
                supply = supply + c.electrical_supply(variables, t)
                demand = demand + c.electrical_demand(variables, t)

            model += supply == demand, f"energy_balance_{t}"

        # Einspeisung nur PV
        for t in range(num_steps):
            model += (
                grid_sell[t] <= float(inp.pv_generation_kw[t]),
                f"feed_in_pv_limit_{t}",
            )

        # §14a Drosselung — Summe aller is_par14a_curtailable Lasten
        if inp.par14a_enabled and inp.par14a_curtailed_steps:
            curtailable = [c for c in milp_components if c.is_par14a_curtailable]
            for t in inp.par14a_curtailed_steps:
                if 0 <= t < num_steps:
                    controllable = pulp.lpSum(
                        c.electrical_demand(variables, t) for c in curtailable
                    )
                    model += (
                        controllable <= inp.par14a_curtailment_kw,
                        f"par14a_curtail_{t}",
                    )

        # ============================================================
        # Zielfunktion
        # ============================================================
        cost = pulp.lpSum(
            grid_buy[t] * float(inp.prices_ct_kwh[t]) * dt_h
            - grid_sell[t] * float(inp.feed_in_tariff_ct_kwh) * dt_h
            for t in range(num_steps)
        )

        # Thermische Slack-Strafen mit physikalisch konsistenter Einheit:
        # ww_slack ist in kW (multipliziert mit dt_h ergibt kWh, mit P_WW
        # in ct/kWh ergibt ct). T_innen-Slacks sind in K — wir muessen sie
        # ueber die thermische Kapazitaet ``C_th`` (kWh/K) in eine vergleich-
        # bare Geldgroesse umrechnen, sonst dominiert ww_slack das Objective
        # asymmetrisch (Einheitenproblem siehe Projektgruppe Penalty Slacks).
        if ww_slack is not None:
            cost += pulp.lpSum(
                ww_slack[t] * P_WW * dt_h
                for t in range(num_steps)
            )

        # Komfort-Slacks fuer T_innen (Building MILP-Erweiterung Mai 2026)
        if (
            "t_innen_slack_low_comfort" in variables
            and "t_innen_slack_low_critical" in variables
            and "t_innen_slack_high" in variables
        ):
            # C_th: thermische Kapazitaet der Wohnflaeche in kWh/K. Dient
            # als Konvertierungsfaktor K -> kWh -> ct. Greift dynamisch
            # auf die Building-Config zu (nicht hardcoded auf Defaults).
            bcfg = self.building.config if self.building else {}
            heated_area = float(bcfg.get("heated_area_m2", 150.0))
            wall_cap_wh = float(bcfg.get("wall_capacity_wh_per_m2_k", 50.0))
            c_th_kwh_per_k = wall_cap_wh * heated_area / 1000.0
            cost_comfort_ct_per_k = P_COMFORT * c_th_kwh_per_k
            cost_critical_ct_per_k = P_CRITICAL * c_th_kwh_per_k
            cost += pulp.lpSum(
                (
                    variables["t_innen_slack_low_comfort"][t] * cost_comfort_ct_per_k
                    + variables["t_innen_slack_low_critical"][t] * cost_critical_ct_per_k
                    + variables["t_innen_slack_high"][t] * UNMET_HEAT_PENALTY_CT
                ) * dt_h
                for t in range(num_steps)
            )

        # EV-Soft-Preisfilter: power_expensive_slack[t] ist in kW, mal
        # dt_h ergibt kWh, mal PENALTY_EV_EXPENSIVE in ct/kWh ergibt ct.
        # Bei jedem kW Laden in einer teuren Stunde faellt also der
        # volle Slack-Tarif an — der Solver wird das nur tun, wenn es
        # zwingend ist (z.B. Departure-Target nicht anders erfuellbar).
        for wb in self.wallboxes:
            if not wb.enabled:
                continue
            slack_key = f"wb_{wb.name}_power_expensive_slack"
            if slack_key in variables:
                cost += pulp.lpSum(
                    variables[slack_key][t] * dt_h * PENALTY_EV_EXPENSIVE
                    for t in range(num_steps)
                )

        # Batterie-Alterungskosten (PDF Speichergruppe, Kap. 3+4)
        # Durchsatz (charge + discharge) wird mit c_aging/2 gewichtet,
        # weil ein Aequivalent-Vollzyklus = 1x laden + 1x entladen.
        if (
            self.battery
            and self.battery.enabled
            and self.battery.aging_cost_enabled
        ):
            c_aging_half_ct = self.battery.aging_cost_ct_per_kwh / 2.0
            if c_aging_half_ct > 0:
                cost += pulp.lpSum(
                    (variables["bat_charge"][t] + variables["bat_discharge"][t])
                    * c_aging_half_ct * dt_h
                    for t in range(num_steps)
                )

        model += cost

        # ============================================================
        # Loesen — Solver-Reihenfolge:
        #   1. HiGHS (Python-API ueber highspy)  → schnell
        #   2. HiGHS_CMD (CLI, falls highs.exe im PATH)
        #   3. PULP_CBC_CMD (Coin-OR Branch-and-Cut, deutlich langsamer)
        #
        # MIP-Gap auf 0.5 % entspannt:
        # Bei einer Optimierung um 1 EUR/Tag entspricht das 0.5 ct Toleranz
        # — fuer Energieoptimierung absolut ausreichend, spart aber bei
        # vielen binaeren Variablen (HP-Modulation, SG-Ready, Wallbox)
        # erheblich Solver-Zeit. timeLimit=30 s als harte Obergrenze.
        # ============================================================
        solver = None
        for solver_factory in (
            lambda: pulp.HiGHS(msg=0, timeLimit=30, gapRel=0.005),
            lambda: pulp.HiGHS_CMD(msg=0, timeLimit=30, gapRel=0.005),
            lambda: pulp.PULP_CBC_CMD(msg=0, timeLimit=30, gapRel=0.005),
        ):
            try:
                candidate = solver_factory()
                if candidate.available():
                    solver = candidate
                    break
            except Exception:
                continue
        if solver is None:
            solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=30, gapRel=0.005)

        model.solve(solver)
        solve_time = time.time() - t_start

        status = pulp.LpStatus[model.status]
        if model.status != pulp.constants.LpStatusOptimal:
            diag = []
            if self.battery and self.battery.enabled:
                diag.append("Batterie")
            if has_hp:
                diag.append("WP")
            if has_ufh:
                diag.append("FBH")
            if has_ww:
                diag.append("WW-Speicher")
            active_wbs = [wb.name for wb in self.wallboxes if wb.enabled]
            if active_wbs:
                diag.append(f"Wallbox({','.join(active_wbs)})")

            return OptimizationResult(
                success=False,
                solver_status=f"{status} | Aktive Komp.: {', '.join(diag) or 'keine'} | "
                f"Schritte: {num_steps}",
                solve_time_s=solve_time,
            )

        # ============================================================
        # Ergebnisse extrahieren
        # ============================================================
        # Wichtig: ``total_cost_eur`` und ``objective_value_eur`` werden
        # bewusst getrennt gefuehrt.
        #   - ``objective_value_eur``: roher MILP-Objective-Wert mit
        #     ALLEN Slack-Strafen (ww_slack, t_innen-Slacks, EV-Slack)
        #     plus Alterungskosten. Reine Solver-Steuerungsgroesse.
        #   - ``total_cost_eur``: wird WEITER UNTEN ueber ``calculate_kpis``
        #     bottom-up aus ``grid_buy_cost_eur - feed_in_revenue_eur``
        #     berechnet — enthaelt **keine** fiktiven Strafkosten. Das
        #     ist die KPI, die im Dashboard als "echte" Geldgroesse
        #     gezeigt wird (Projektgruppe Penalty Slacks: "man zahlt
        #     ja nix fuer komfort-verletzungen").
        result = OptimizationResult(
            success=True,
            solver_status=status,
            solve_time_s=solve_time,
            objective_value_eur=pulp.value(model.objective) / 100.0,
            grid_buy_kw=np.array([v.varValue or 0.0 for v in grid_buy]),
            grid_sell_kw=np.array([v.varValue or 0.0 for v in grid_sell]),
            timestamps=inp.timestamps,
            # Default SG-Ready: Normalbetrieb, wird ggf. von HP.extract_result ueberschrieben
            sg_ready_state=np.full(num_steps, 2),
        )

        # Generischer Extraktions-Loop — jede Komponente schreibt ihre
        # Felder selbst ins Result.
        for c in milp_components:
            c.extract_result(result, variables, num_steps, dt_h)

        # Day-Ahead-Optimizer plant einmalig ueber den gesamten Horizont —
        # ein einziges Planungsfenster, das den ganzen Eingang abdeckt.
        # Damit kann das Dashboard fuer alle Optimierungsmodi (MILP, MPC,
        # Baseline) dieselbe Visualisierung verwenden.
        result.planning_windows = [{
            "start_step": 0,
            "exec_end_step": num_steps,
            "horizon_end_step": num_steps,
        }]

        # KPIs
        from emos_light.utils.kpi import calculate_kpis
        result = calculate_kpis(result, inp)

        return result
