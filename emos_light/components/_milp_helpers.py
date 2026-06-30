"""Wiederverwendbare MILP-Bausteine fuer die Komponenten.

Hier landet alles, was sich beim Aufsetzen der Optimierungsvariablen und
-Constraints zwischen mehreren Komponenten dupliziert. Die Funktionen
selbst aendern *kein* Modellverhalten — sie bauen exakt die gleichen
Constraints, wie wir sie bisher von Hand pro Komponente geschrieben haben.

Konventionen:
    - num_steps: Anzahl Zeitschritte des Horizonts.
    - step_minutes: Zeitschrittlaenge in Minuten.
    - dt_h: Zeitschrittlaenge in Stunden (= step_minutes / 60).
    - prefix: String, wird allen Variablen- und Constraint-Namen vorangestellt,
      um Kollisionen bei mehreren gleichartigen Komponenten zu vermeiden.
"""

from typing import Any, Optional, Sequence

import pulp


# ---------------------------------------------------------------------------
# Zeit-Hilfsfunktionen
# ---------------------------------------------------------------------------

def step_hours(step_minutes: int) -> float:
    """Zeitschrittlaenge in Stunden (z.B. 15 -> 0.25)."""
    return step_minutes / 60.0


def steps_for_minutes(minutes: int, step_minutes: int) -> int:
    """Anzahl Zeitschritte fuer eine gegebene Zeitspanne (mind. 1)."""
    return max(1, minutes // step_minutes)


# ---------------------------------------------------------------------------
# Variablen-Konstruktoren
# ---------------------------------------------------------------------------

def make_var_array(
    name: str,
    num_steps: int,
    *,
    low: Optional[float] = 0.0,
    high: Optional[float] = None,
    cat: str = pulp.LpContinuous,
) -> list[pulp.LpVariable]:
    """Erstellt ein Array von LpVariablen mit einheitlich benannten Indizes.

    Equivalent zu:
        [LpVariable(f"{name}_{t}", lowBound=low, upBound=high, cat=cat)
         for t in range(num_steps)]
    """
    return [
        pulp.LpVariable(f"{name}_{t}", lowBound=low, upBound=high, cat=cat)
        for t in range(num_steps)
    ]


def make_binary_array(name: str, num_steps: int) -> list[pulp.LpVariable]:
    """Bequemer Wrapper fuer ein Array binaerer Variablen."""
    return [
        pulp.LpVariable(f"{name}_{t}", cat=pulp.LpBinary)
        for t in range(num_steps)
    ]


# ---------------------------------------------------------------------------
# Standard-Constraint-Muster
# ---------------------------------------------------------------------------

def add_on_off_power_link(
    model: pulp.LpProblem,
    power: Sequence[pulp.LpVariable],
    on: Sequence[pulp.LpVariable],
    *,
    max_power: float,
    min_power: float = 0.0,
    name: str = "onoff",
) -> None:
    """Koppelt eine kontinuierliche Leistungsvariable an eine binaere on/off-Variable.

    Erzeugt fuer jeden Zeitschritt:
        power[t] <= max_power * on[t]
        power[t] >= min_power * on[t]   (falls min_power > 0)

    Damit ist die Leistung null, wenn on=0, und liegt im
    Modulationsbereich [min_power, max_power], wenn on=1.
    """
    for t in range(len(power)):
        model += (
            power[t] <= max_power * on[t],
            f"{name}_max_{t}",
        )
        if min_power > 0:
            model += (
                power[t] >= min_power * on[t],
                f"{name}_min_{t}",
            )


def add_mutual_exclusion(
    model: pulp.LpProblem,
    a: Sequence[pulp.LpVariable],
    b: Sequence[pulp.LpVariable],
    *,
    name: str,
) -> None:
    """a[t] + b[t] <= 1 — schliesst zwei binaere Zustaende gegenseitig aus."""
    for t in range(len(a)):
        model += a[t] + b[t] <= 1, f"{name}_excl_{t}"


def add_min_run_time(
    model: pulp.LpProblem,
    on: Sequence[pulp.LpVariable],
    *,
    min_run_steps: int,
    name: str,
) -> None:
    """Erzwingt eine Mindestlaufzeit nach jedem Einschaltvorgang.

    Logik (siehe Doku): wenn on[t] - on[t-1] = 1 (Einschalten),
    muss on[t+k] = 1 fuer k = 1..min_run_steps-1.

    Randfall t=0 (Fix Juni 2026): die Anlage gilt vor dem Horizont als AUS
    (konsistent mit der hp_start-Konvention). Ein Einschalten direkt im
    ersten Schritt ist damit ebenfalls ein Einschaltvorgang und muss die
    Mindestlaufzeit halten — sonst entsteht am Horizontanfang ein einzelner
    15-min-Lauf, der die Mindestlaufzeit unterlaeuft.
    """
    if min_run_steps <= 1:
        return
    n = len(on)
    # Einschalten bei t=0 (Vorzustand AUS angenommen): on[0] erzwingt on[k]=1.
    for k in range(1, min_run_steps):
        if k < n:
            model += (on[0] <= on[k], f"{name}_minrun_0_{k}")
    for t in range(1, n):
        for k in range(1, min_run_steps):
            if t + k < n:
                model += (
                    on[t] - on[t - 1] <= on[t + k],
                    f"{name}_minrun_{t}_{k}",
                )


def add_min_pause_time(
    model: pulp.LpProblem,
    on: Sequence[pulp.LpVariable],
    *,
    min_pause_steps: int,
    name: str,
) -> None:
    """Erzwingt eine Mindestpausenzeit nach jedem Ausschaltvorgang.

    Logik: wenn on[t-1] - on[t] = 1 (Ausschalten),
    muss on[t+k] = 0 fuer k = 1..min_pause_steps-1.
    """
    if min_pause_steps <= 1:
        return
    n = len(on)
    for t in range(1, n):
        for k in range(1, min_pause_steps):
            if t + k < n:
                model += (
                    on[t - 1] - on[t] <= 1 - on[t + k],
                    f"{name}_minpause_{t}_{k}",
                )


def add_min_hold_time(
    model: pulp.LpProblem,
    state: Sequence[pulp.LpVariable],
    *,
    min_hold_steps: int,
    name: str,
) -> None:
    """Mindesthaltezeit fuer einen binaeren Zustand (z.B. SG-Ready 1/3).

    Identische Mechanik wie add_min_run_time, aber semantisch fuer
    'beim Wechsel auf 1 mindestens N Schritte halten'.
    """
    add_min_run_time(model, state, min_run_steps=min_hold_steps, name=name)


def add_state_balance(
    model: pulp.LpProblem,
    state: Sequence[pulp.LpVariable],
    *,
    initial: float,
    rhs_fn,
    name: str,
) -> None:
    """Energiebilanz state[t] = f(state[t-1], t) mit Sonderfall t=0.

    Args:
        state: Liste von Zustandsvariablen (z.B. SoC, Energie).
        initial: Anfangswert fuer state[-1].
        rhs_fn: Callable rhs_fn(prev_value, t) -> Ausdruck. Wird pro
            Zeitschritt aufgerufen, mit prev_value = initial bei t=0
            und = state[t-1] sonst.
        name: Constraint-Praefix.
    """
    for t in range(len(state)):
        prev = initial if t == 0 else state[t - 1]
        model += (state[t] == rhs_fn(prev, t), f"{name}_balance_{t}")
