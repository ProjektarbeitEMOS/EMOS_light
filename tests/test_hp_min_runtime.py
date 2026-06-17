"""Tests fuer die Mindestlaufzeit der Waermepumpe (Verdichter-Schonung).

Hintergrund (Auftraggeber-Hinweis Juni 2026): Das fruehere harte Tageslimit
der Einschaltvorgaenge (``max_starts_per_day``) wurde durch eine
Mindestlaufzeit von 1 h je Einschaltvorgang ersetzt — jeder OFF->ON-Vorgang
zieht eine Mindestlaufzeit nach sich, kurzes Takten ist damit ausgeschlossen.
Innerhalb dieser Laufphase darf zwischen Heizkreis und WW umgeschaltet werden
(``hp_mode_ww`` ist von ``hp_on`` entkoppelt).

``hp_start`` bleibt als reine Diagnose-Variable erhalten (Schaltzahl-Vergleich
gegen Baseline/MPC im Dashboard) und ist jetzt exakt an ``hp_on`` gekoppelt.
"""

import copy
import datetime

import numpy as np

from emos_light.components.heat_pump import HeatPump
from emos_light.core.config import DEFAULT_CONFIG
from emos_light.core.scenario import (
    build_components, build_optimizer,
    build_time_series_input, load_input_data,
)
from emos_light.optimization.baseline import run_baseline


TEST_DATE = datetime.date(2026, 1, 15)


def _winter_cfg(min_run_minutes: int = 60) -> dict:
    """WP+FBH+Building bei kaltem Winter, 24h-Horizont."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["general"]["optimization_horizon_hours"] = 24
    for key in ("battery", "pv",
                "hot_water_storage", "fresh_water_station"):
        cfg.setdefault(key, {})["enabled"] = False
    cfg["heat_pump"]["enabled"] = True
    cfg["heat_pump"]["min_run_time_minutes"] = min_run_minutes
    cfg["underfloor_heating"]["enabled"] = True
    cfg["building"]["enabled"] = True
    cfg["building"]["comfort_temp_min_c"] = 20.0
    cfg["building"]["comfort_temp_max_c"] = 24.0
    cfg["wallboxes"] = []
    cfg["electric_vehicles"] = []
    cfg["household"]["annual_consumption_kwh"] = 1000
    cfg["household"]["load_profile_id"] = ""
    return cfg


def _run(cfg):
    data = load_input_data(cfg, TEST_DATE, use_api=False)
    # Stabile Winterbedingung — konstant -5 °C, damit die WP wirklich
    # laufen will.
    data["temp"] = np.full_like(data["temp"], -5.0, dtype=float)
    inp = build_time_series_input(cfg, data)
    return inp, build_optimizer(build_components(cfg)).optimize(inp)


def _on_runs(power_kw, tol=1e-6):
    """Liefert (start, end_inkl.)-Indizes aller zusammenhaengenden ON-Laeufe."""
    on = np.asarray(power_kw) > tol
    runs = []
    t = 0
    n = len(on)
    while t < n:
        if on[t]:
            s = t
            while t < n and on[t]:
                t += 1
            runs.append((s, t - 1))
        else:
            t += 1
    return runs


def test_milp_respects_min_run_time():
    """Jeder Einschaltvorgang (Start bei t>=1) zieht die Mindestlaufzeit nach
    sich. Ein Lauf, der ab t=0 schon aktiv ist, oder einer, der vom Horizont
    abgeschnitten wird, ist davon ausgenommen (Constraint greift nur fuer
    OFF->ON-Flanken mit genug Restschritten)."""
    cfg = _winter_cfg(min_run_minutes=60)
    inp, res = _run(cfg)
    assert res.success, f"Solver erfolglos: {res.solver_status}"

    step_min = inp.step_minutes
    min_run_steps = max(1, 60 // step_min)
    n = len(res.hp_power_kw)

    for s, e in _on_runs(res.hp_power_kw):
        if s == 0:
            continue  # bei t=0 keine OFF->ON-Flanke -> keine Mindestlaufzeit
        enforced = min(min_run_steps, n - s)  # Rest-Horizont kann kuerzen
        length = e - s + 1
        assert length >= enforced, (
            f"Lauf {s}..{e} ist {length} Schritte, "
            f"erzwungen waren {enforced} (min_run_steps={min_run_steps})"
        )


def test_start_indicator_is_exact():
    """hp_starts_count muss exakt die Zahl der OFF->ON-Flanken sein. Ohne
    hartes Limit haette der Solver sonst keinen Anreiz, hp_start klein zu
    halten — die exakte Kopplung (drei Ungleichungen) garantiert das."""
    cfg = _winter_cfg()
    _, res = _run(cfg)
    assert res.success

    on = np.asarray(res.hp_power_kw) > 1e-6
    prev = np.concatenate(([False], on[:-1]))  # bei t=0: vorher AUS
    expected_starts = int(np.sum(on & ~prev))
    assert res.hp_starts_count == expected_starts, (
        f"hp_starts_count={res.hp_starts_count}, "
        f"aus Leistung abgeleitet={expected_starts}"
    )


def test_starts_count_consistent_with_per_day():
    cfg = _winter_cfg()
    _, res = _run(cfg)
    assert res.success
    assert res.hp_starts_count == sum(res.hp_starts_per_day.values())


def test_heat_pump_has_no_start_cap():
    """Regressionswaechter: das alte Tageslimit darf nicht zurueckkehren."""
    hp = HeatPump("hp", copy.deepcopy(DEFAULT_CONFIG["heat_pump"]))
    assert not hasattr(hp, "max_starts_per_day")
    assert "max_starts_per_day" not in DEFAULT_CONFIG["heat_pump"]


def test_baseline_counts_starts():
    """Baseline zaehlt Einschaltvorgaenge weiter mit — fuer den Vergleich
    gegen die MILP-Loesung im Dashboard."""
    cfg = _winter_cfg()
    inp, _ = _run(cfg)
    base = run_baseline(inp, cfg)
    assert base.success
    assert isinstance(base.hp_starts_per_day, dict)
    assert base.hp_starts_count == sum(base.hp_starts_per_day.values())
    # Bei -5 °C Aussentemperatur muss die Baseline mindestens 1x
    # einschalten, um das Komfortband zu halten.
    assert base.hp_starts_count >= 1
