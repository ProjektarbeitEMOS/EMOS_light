"""Wallbox Komponentenmodell fuer EMOS.

MILP-Modell mit Ladeleistungsoptimierung, Mindestleistung,
EV-Anwesenheits-Constraint und Paragraph-14a-Bewusstsein.
"""

from typing import Any

import pulp

from emos_light.components.base import MILPComponent
from emos_light.components._milp_helpers import (
    add_on_off_power_link,
    make_binary_array,
    make_var_array,
    step_hours,
)


class Wallbox(MILPComponent):
    """Wallbox mit Paragraph-14a-Bewusstsein und Phasenumschaltung.

    Phasenumschaltung:
        1-phasig: 1.4 - 3.7 kW (6A - 16A bei 230V)
        3-phasig: 4.2 - 11.0 kW (6A - 16A bei 3x230V)

    Config-Parameter:
        max_power_kw (float): Maximale Ladeleistung in kW.
        min_power_kw (float): Minimale Ladeleistung wenn aktiv (kW).
        phases (int): Anzahl Phasen (1 oder 3).
        ev_battery_capacity_kwh (float): EV-Batteriekapazitaet in kWh.
        target_soc (float): Ziel-SOC (0-1).
        current_soc (float): Aktueller SOC (0-1).
        departure_hour (int): Abfahrtsstunde (0-23).
        arrival_hour (int): Ankunftsstunde (0-23).
        charging_efficiency (float): Ladewirkungsgrad (0-1).
    """

    # Typische Leistungsbereiche pro Phase
    PHASE_LIMITS = {
        1: {"min_kw": 1.4, "max_kw": 3.7},
        3: {"min_kw": 4.2, "max_kw": 11.0},
    }

    def __init__(self, name: str, config: dict):
        # Name normalisieren (keine Leerzeichen/Sonderzeichen fuer Variablennamen)
        safe_name = name.replace(" ", "_").replace("-", "_")
        super().__init__(safe_name, config)
        self.max_power_kw = config.get("max_power_kw", 11.0)
        self.min_power_kw = config.get("min_power_kw", 4.2)
        self.phases = config.get("phases", 3)
        self.ev_capacity_kwh = config.get("ev_battery_capacity_kwh", 60.0)
        self.target_soc = config.get("target_soc", 0.8)
        # max_soc ist die physische Obergrenze des Akkus (1.0 = 100 %),
        # ggf. abgesenkt zum Akkuschutz (z.B. 0.8). Der Solver darf
        # niemals ueber diesen Punkt laden.
        self.max_soc = config.get("max_soc", 1.0)
        self.current_soc = config.get("current_soc", 0.3)
        self.departure_hour = config.get("departure_hour", 7)
        self.arrival_hour = config.get("arrival_hour", 17)
        self.charging_efficiency = config.get("charging_efficiency", 0.92)
        # Fahrverbrauch pro Stunde Abwesenheit, in Prozent der EV-Kapazitaet.
        # Default 5 % / h — pragmatische Annahme fuer den taeglichen Pendel-
        # einsatz (siehe Projekt-Doku). Setzt den SOC waehrend der Fahrt
        # linear herab; bei Rueckkehr startet das Auto mit dem reduzierten
        # SOC, daher muss zwischen Ankunft und nachster Abfahrt wieder
        # genug geladen werden, um target_soc zu erreichen.
        self.driving_loss_pct_per_hour = float(
            config.get("driving_loss_pct_per_hour", 5.0)
        )

        # Garantierte Mindestreichweite (Min-Energy-Constraint).
        # Wenn False: kein Energie-Constraint, stattdessen wird in jedem
        # erlaubten Slot (Anwesenheit ∩ Preisperzentil) mit voller Leistung
        # geladen (siehe add_constraints). Nuetzlich, wenn Auto/Wallbox
        # den SOC nicht ausgeben — dann ist eine garantierte Lademenge
        # technisch nicht zuverlaessig erreichbar.
        self.min_range_enabled = bool(config.get("min_range_enabled", True))

        # Preisgesteuerte Ladestrategie (Ersatz fuer fehlendes V2H):
        # Nur in den guenstigsten X % der Tagespreise (Day-Ahead) laden.
        # 100 % = keine Beschraenkung (Default).
        self.charge_only_below_percentile_pct = float(
            config.get("charge_only_below_percentile_pct", 100.0)
        )
        # Wird in prepare(inp) gesetzt — None = keine Beschraenkung.
        self._allowed_charging_steps: set[int] | None = None

        # Leistungsgrenzen basierend auf Phasenkonfiguration anpassen
        phase_limits = self.PHASE_LIMITS.get(self.phases, self.PHASE_LIMITS[3])
        self.max_power_kw = min(self.max_power_kw, phase_limits["max_kw"])
        self.min_power_kw = max(self.min_power_kw, phase_limits["min_kw"])
        # Defensive: bei untypischer Kombination (z.B. 3-phasig mit sehr
        # kleiner max_power_kw) darf min nicht ueber max steigen — sonst
        # koppelt add_on_off_power_link (power<=max*on & power>=min*on)
        # zu on==0, die Wallbox koennte nie laden.
        self.min_power_kw = min(self.min_power_kw, self.max_power_kw)

    # ------------------------------------------------------------------
    # Setup-Hook fuer preisgesteuerte Ladestrategie
    # ------------------------------------------------------------------

    def prepare(self, inp: Any) -> None:
        """Berechnet, in welchen Zeitschritten ueberhaupt geladen werden darf.

        Wenn ``charge_only_below_percentile_pct < 100``, wird das Laden auf
        die guenstigsten X % der Strompreise **innerhalb der Anwesenheits-
        zeit** des Fahrzeugs eingeschraenkt. Das simuliert eine preis-
        sensitive Ladestrategie ohne V2H-Hardware — der Nutzer entscheidet
        sich freiwillig, das Auto nur in den relativ guenstigsten Stunden
        seiner Standzeit zu laden.

        Wichtig: das Perzentil bezieht sich auf die **Anwesenheitsstunden**,
        nicht auf den ganzen Tag. Damit garantiert das System, dass auch
        bei ungluecklicher Anwesenheit (z.B. nur waehrend der Preisspitze)
        immer Ladeslots verfuegbar sind — naemlich die billigsten *dieser*
        teuren Stunden.

        Achtung: Wenn die zulaessigen Zeitschritte zusammen mit
        max_power_kw nicht ausreichen, die Mindestlademenge zu erreichen,
        wird der Solver ein infeasibles Problem melden.
        """
        import numpy as np
        if self.charge_only_below_percentile_pct >= 100.0:
            self._allowed_charging_steps = None
            return

        prices = np.asarray(inp.prices_ct_kwh, dtype=float)
        n = len(prices)
        step_minutes = getattr(inp, "step_minutes", 15)
        steps_per_hour = max(1, 60 // step_minutes)

        # Anwesenheits-Slots ermitteln
        present_steps = [
            t for t in range(n)
            if self._is_ev_present((t // steps_per_hour) % 24)
        ]
        if not present_steps:
            # Kein Anwesenheitsslot — Filter unwirksam (alles geht), denn
            # die EV-Anwesenheits-Constraints unterbinden das Laden bereits.
            self._allowed_charging_steps = None
            return

        # Perzentil ueber die Preise *in den Anwesenheitsstunden*.
        present_prices = prices[present_steps]
        threshold = float(np.percentile(
            present_prices, self.charge_only_below_percentile_pct
        ))
        self._allowed_charging_steps = {
            t for t in present_steps if prices[t] <= threshold
        }

    @property
    def energy_needed_kwh(self) -> float:
        """Berechnet die benoetigte Ladeenergie in kWh (AC-seitig).

        energy_needed = (target_soc - current_soc) * capacity / efficiency
        """
        delta_soc = max(0.0, self.target_soc - self.current_soc)
        return delta_soc * self.ev_capacity_kwh / self.charging_efficiency

    @property
    def max_charge_kwh(self) -> float:
        """Maximal moegliche Ladeenergie in kWh (AC-seitig) bis max_soc.

        Obere Schranke fuer das gesamte Laden ueber den Optimierungs-
        zeitraum — verhindert, dass der Solver das Auto ueber max_soc
        hinaus 'belaedt' (was real durch die Akku-BMS-Begrenzung passiert
        aber im Modell ohne diese Schranke nicht abgebildet ist).
        """
        delta_soc = max(0.0, self.max_soc - self.current_soc)
        return delta_soc * self.ev_capacity_kwh / self.charging_efficiency

    # ------------------------------------------------------------------
    # Anwesenheitslogik
    # ------------------------------------------------------------------

    def _is_ev_present(self, hour: int) -> bool:
        """Prueft, ob das EV in der gegebenen Stunde am Stecker ist.

        Tagsszenario  (arrival <= departure): anwesend [arrival, departure)
        Nachtszenario (arrival >  departure): anwesend [arrival, 24) ∪ [0, departure)
        """
        if self.arrival_hour <= self.departure_hour:
            return self.arrival_hour <= hour < self.departure_hour
        return hour >= self.arrival_hour or hour < self.departure_hour

    def _count_charging_slots(self, num_steps: int, step_minutes: int) -> int:
        """Anzahl der Slots, in denen das Auto laden darf
        (Anwesenheit ∩ Preisfilter)."""
        steps_per_hour = max(1, 60 // step_minutes)
        if self._allowed_charging_steps is not None:
            return len(self._allowed_charging_steps)
        return sum(
            1 for t in range(num_steps)
            if self._is_ev_present((t // steps_per_hour) % 24)
        )

    # ------------------------------------------------------------------
    # MILP-Schnittstelle
    # ------------------------------------------------------------------

    def get_optimization_variables(self, num_steps: int, model: Any) -> dict:
        """Erstellt Wallbox-Variablen.

        Variablen:
            wb_<name>_power[t]: Ladeleistung in kW (>= 0)
            wb_<name>_on[t]:    Binaer - Wallbox aktiv (fuer Mindestleistung)
            wb_<name>_soc[t]:   EV-SOC in kWh am Anfang von Schritt t
                                (0 <= soc <= max_soc * Kapazitaet). Wird
                                pro Schritt nach Anwesenheit/Abwesenheit
                                explizit fortgeschrieben.
        """
        prefix = f"wb_{self.name}"
        soc_max_kwh = self.max_soc * self.ev_capacity_kwh
        return {
            f"wb_{self.name}_power": make_var_array(
                f"{prefix}_power", num_steps, low=0, high=self.max_power_kw,
            ),
            f"wb_{self.name}_on": make_binary_array(
                f"{prefix}_on", num_steps,
            ),
            # SOC pro Zeitschritt — Bound oben durch BMS (max_soc), unten
            # bei 0 (physikalisch). Wenn die Konfiguration den Akku
            # rechnerisch unter 0 druecken wuerde, ist das Setup
            # unrealistisch und der Solver meldet Infeasibility — der
            # User muss dann z.B. den Preisperzentil-Filter lockern oder
            # die Mindestreichweite deaktivieren.
            f"wb_{self.name}_soc": make_var_array(
                f"{prefix}_soc", num_steps, low=0.0, high=soc_max_kwh,
            ),
            # Soft-Preisfilter: Slack-Variable fuer das Laden in den
            # nicht-billigen Stunden. In add_constraints wird:
            #   power[t] <= power_expensive_slack[t]   waehrend teurer Stunden
            #   power_expensive_slack[t] == 0          waehrend billiger Stunden
            # erzwungen — siehe Projektgruppe Penalty Slacks. Im Objective
            # wird der Slack mit PENALTY_EV_EXPENSIVE bestraft. Damit
            # vermeidet der Solver mathematisch teure Stunden, kann sie aber
            # zur Notfall-Ladung (Departure-Target) nutzen, statt direkt
            # in Infeasibility zu laufen.
            f"wb_{self.name}_power_expensive_slack": make_var_array(
                f"{prefix}_power_expensive_slack", num_steps,
                low=0.0, high=self.max_power_kw,
            ),
        }

    def add_constraints(self, model: Any, variables: dict, step_minutes: int) -> None:
        """Fuegt Wallbox-Constraints zum Modell hinzu.

        Constraints:
            1. Ladeleistung an on/off-Variable gekoppelt (Min und Max)
            2. EV-Anwesenheit: power = 0 ausserhalb Anwesenheitszeit
            3. Preisfilter (optional)
            4. SOC-Bilanz: soc[t+1] = soc[t] + present(t)*power[t]*dt*eff
                          - (1 - present(t)) * loss_per_step
               Damit verliert das Auto pro Stunde Abwesenheit
               ``driving_loss_pct_per_hour`` Prozent SOC; bei Rueckkehr
               startet es mit reduziertem SOC und muss neu geladen
               werden, falls vor der naechsten Abfahrt target_soc
               wieder erreicht werden soll.
            5. Ziel-SOC zum Abfahrtszeitpunkt: an jeder Praesenz-zu-
               Absenz-Kante muss ``soc[t_dep] >= target_soc * cap``.
               Loest die alte "Mindestlademenge ueber Horizont"-Logik
               ab — verhindert, dass der Solver das Laden erst nach
               Abfahrt erledigt.
        """
        prefix = f"wb_{self.name}"
        dt_h = step_hours(step_minutes)

        power = variables[f"wb_{self.name}_power"]
        on = variables[f"wb_{self.name}_on"]
        soc = variables[f"wb_{self.name}_soc"]
        num_steps = len(power)

        # 1) Modulationsbereich (Min/Max gekoppelt an on/off)
        add_on_off_power_link(
            model, power, on,
            max_power=self.max_power_kw,
            min_power=self.min_power_kw,
            name=prefix,
        )

        # 2) EV-Anwesenheit: ausserhalb der Anwesenheit hart auf 0
        steps_per_hour = max(1, 60 // step_minutes)
        presence: list[bool] = []
        for t in range(num_steps):
            hour = (t // steps_per_hour) % 24
            present_t = self._is_ev_present(hour)
            presence.append(present_t)
            if not present_t:
                model += (power[t] == 0, f"{prefix}_ev_absent_{t}")

        # 3) Preisfilter als SOFT-Constraint via Slack-Variable
        # (Projektgruppe Penalty Slacks, Mai 2026):
        #   - In billigen Stunden (im Perzentil): power_expensive_slack = 0,
        #     Laden ist "kostenneutral".
        #   - In teuren Stunden: jedes kW Ladeleistung muss durch
        #     ``power_expensive_slack[t]`` geroutet werden. Damit
        #     Laden mathematisch durch PENALTY_EV_EXPENSIVE bestraft wird.
        # Die harte Departure-Target-Garantie (Block 5) bleibt unangetastet
        # — der Solver kann teure Stunden zur Notfall-Versorgung nutzen
        # statt in Infeasibility zu laufen, zahlt aber pro kWh den
        # vollen Slack-Tarif.
        power_expensive_slack = variables[
            f"wb_{self.name}_power_expensive_slack"
        ]
        if self._allowed_charging_steps is not None:
            for t in range(num_steps):
                if t in self._allowed_charging_steps:
                    model += (
                        power_expensive_slack[t] == 0,
                        f"{prefix}_price_slack_zero_{t}",
                    )
                else:
                    model += (
                        power[t] <= power_expensive_slack[t],
                        f"{prefix}_price_slack_route_{t}",
                    )
        else:
            # Kein Filter aktiv -> Slack ueberall auf 0, damit das
            # Objective sauber bleibt.
            for t in range(num_steps):
                model += (
                    power_expensive_slack[t] == 0,
                    f"{prefix}_price_slack_zero_{t}",
                )

        # 4) SOC-Bilanz
        #
        #   soc[0] = initial_soc * capacity
        #   soc[t+1] = soc[t] + present(t)*power[t]*dt*eff
        #             - (1-present(t)) * driving_loss_per_step
        #
        # Driving-Loss in kWh pro Schritt:
        #   loss/step = driving_loss_pct/100 * capacity * dt_h
        # (5 %/h * 60 kWh = 3 kWh/h = 0.75 kWh / 15min-step)
        initial_soc_kwh = self.current_soc * self.ev_capacity_kwh
        loss_per_step_kwh = (
            self.driving_loss_pct_per_hour / 100.0
            * self.ev_capacity_kwh
            * dt_h
        )

        model += (soc[0] == initial_soc_kwh, f"{prefix}_soc_init")
        for t in range(num_steps - 1):
            if presence[t]:
                model += (
                    soc[t + 1]
                    == soc[t] + power[t] * dt_h * self.charging_efficiency,
                    f"{prefix}_soc_step_{t}",
                )
            else:
                model += (
                    soc[t + 1] == soc[t] - loss_per_step_kwh,
                    f"{prefix}_soc_step_{t}",
                )

        # 5) Ziel-SOC zum Abfahrtszeitpunkt — HARTES Constraint: jede
        # 1->0-Kante in presence ist eine Abfahrt, soc[t] muss dort
        # mind. ``target_soc * cap`` betragen. Bei aktiver Mindest-
        # reichweite hat dieses Constraint Prioritaet ueber den
        # Preisperzentil-Filter — d.h. wenn die billigsten X % nicht
        # ausreichen, wird auch ausserhalb des Filters geladen. Der
        # Cost-Minimizer waehlt natuerlich trotzdem die guenstigsten
        # verfuegbaren Stunden.
        if self.min_range_enabled:
            target_soc_kwh = self.target_soc * self.ev_capacity_kwh
            for t in range(num_steps):
                # Bei t=0 gibt es keine "vorherige" Anwesenheit -> mit
                # presence[0] initialisieren, sonst entsteht eine Schein-
                # Abfahrt am Horizontstart: startet das Auto abwesend und
                # unter Ziel-SOC, waere soc[0] >= target sofort infeasible.
                was_present = presence[t - 1] if t > 0 else presence[0]
                if was_present and not presence[t]:
                    model += (
                        soc[t] >= target_soc_kwh,
                        f"{prefix}_target_at_departure_{t}",
                    )

    # ------------------------------------------------------------------
    # Bilanz-Beitraege
    # ------------------------------------------------------------------

    def electrical_demand(self, variables: dict, t: int) -> Any:
        """Wallbox-Ladeleistung als Last am AC-Knoten."""
        return variables[f"wb_{self.name}_power"][t]

    @property
    def is_par14a_curtailable(self) -> bool:
        return True

    def extract_result(
        self, result: Any, variables: dict, num_steps: int, dt_h: float,
    ) -> None:
        """Ladeleistung und EV-SOC-Trajektorie pro Wallbox ins Result."""
        import numpy as np
        result.wallbox_power_kw[self.name] = np.array(
            [v.varValue or 0.0 for v in variables[f"wb_{self.name}_power"]]
        )
        if f"wb_{self.name}_soc" in variables:
            if not hasattr(result, "ev_soc_kwh") or result.ev_soc_kwh is None:
                result.ev_soc_kwh = {}
            result.ev_soc_kwh[self.name] = np.array(
                [v.varValue or 0.0 for v in variables[f"wb_{self.name}_soc"]]
            )
