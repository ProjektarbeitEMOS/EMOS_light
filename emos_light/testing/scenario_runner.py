"""YAML driven scenario tests for EMOS Light.

The runner lets us feed synthetic edge-case time series into the normal
scenario builder and then check the optimization result against explicit
expectations. This is intentionally small and boring: scenario files should
be readable by non-developers.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from emos_light.core.config import DEFAULT_CONFIG, load_config
from emos_light.core.scenario import (
    build_components,
    build_optimizer,
    build_time_series_input,
    load_input_data,
)
from emos_light.optimization.baseline import calculate_baseline_cost, run_baseline
from emos_light.optimization.mpc import MPCController


SERIES_KEYS = {
    "prices_ct_kwh": "prices",
    "spot_prices_ct_kwh": "spot_prices",
    "outside_temp_c": "temp",
    "ghi_w_m2": "ghi",
    "wind_speed_m_s": "wind_speed",
    "pv_generation_kw": "pv_generation",
    "household_load_kw": "household_load",
    "heating_demand_kw": "heating_demand",
    "hot_water_demand_kw": "hw_demand",
}


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    actual: Any = None
    expected: Any = None


@dataclass
class ScenarioRunResult:
    name: str
    mode: str
    success: bool
    solver_status: str
    summary: dict[str, Any]
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks) if self.checks else self.success


def load_scenario(path: str | Path) -> dict[str, Any]:
    """Load a YAML scenario file."""
    with Path(path).open("r", encoding="utf-8") as f:
        scenario = yaml.safe_load(f) or {}
    if not isinstance(scenario, dict):
        raise ValueError("Scenario YAML must contain a mapping at the top level.")
    return scenario


def run_scenario_file(path: str | Path) -> ScenarioRunResult:
    return run_scenario(load_scenario(path), scenario_path=Path(path))


def run_scenario(scenario: dict[str, Any], scenario_path: Path | None = None) -> ScenarioRunResult:
    """Run one YAML scenario and evaluate its checks."""
    name = scenario.get("name") or (scenario_path.stem if scenario_path else "unnamed")
    mode = str(scenario.get("mode", "milp")).lower()
    date = _parse_date(scenario.get("date", dt.date.today().isoformat()))

    config = _load_base_config(scenario, scenario_path)
    _deep_update(config, scenario.get("config_overrides", {}))
    _apply_component_switches(config, scenario.get("components", {}))

    data = load_input_data(config, date, use_api=bool(scenario.get("use_api", False)))
    _apply_input_overrides(data, scenario.get("input_overrides", {}))
    inp = build_time_series_input(config, data)

    if mode == "baseline":
        result = run_baseline(inp, config)
    else:
        components = build_components(config)
        optimizer = build_optimizer(components)
        if mode == "mpc":
            mpc_cfg = scenario.get("mpc", {})
            result = MPCController(
                optimizer,
                horizon_hours=mpc_cfg.get("horizon_hours", 6),
                execute_hours=mpc_cfg.get("execute_hours", 1),
            ).run_mpc(inp)
        elif mode == "milp":
            result = optimizer.optimize(inp)
        else:
            raise ValueError(f"Unsupported scenario mode: {mode}")

    baseline_cost = None
    if scenario.get("calculate_baseline", True):
        try:
            baseline_cost = calculate_baseline_cost(inp, config)
            result.baseline_cost_eur = baseline_cost
            result.savings_eur = baseline_cost - result.total_cost_eur
            result.savings_pct = (
                100.0 * result.savings_eur / baseline_cost
                if baseline_cost and baseline_cost > 0 else None
            )
        except Exception:
            baseline_cost = None

    checks = evaluate_checks(result, inp, config, scenario.get("checks", []))
    return ScenarioRunResult(
        name=name,
        mode=mode,
        success=bool(result.success),
        solver_status=result.solver_status,
        summary=_summarize_result(result, baseline_cost),
        checks=checks,
    )


def evaluate_checks(result: Any, inp: Any, config: dict[str, Any], checks: list[dict[str, Any]]) -> list[CheckResult]:
    evaluated: list[CheckResult] = []
    for i, check in enumerate(checks):
        kind = check.get("type", "metric")
        name = check.get("name", f"{kind}_{i + 1}")
        try:
            evaluated.append(_evaluate_check(name, kind, check, result, inp, config))
        except Exception as exc:
            evaluated.append(CheckResult(name=name, passed=False, detail=f"check error: {exc}"))
    return evaluated


def _evaluate_check(name: str, kind: str, check: dict[str, Any], result: Any, inp: Any, config: dict[str, Any]) -> CheckResult:
    if kind == "success":
        expected = bool(check.get("expected", True))
        actual = bool(result.success)
        return CheckResult(name, actual == expected, f"success is {actual}", actual, expected)

    if kind == "metric":
        actual = _resolve_path(result, check["metric"])
        expected = check["value"]
        passed = _compare(float(actual), check.get("op", "=="), float(expected), check.get("tolerance", 1e-6))
        return CheckResult(name, passed, _format_compare(actual, check.get("op", "=="), expected), actual, expected)

    if kind == "series_min":
        series = np.asarray(_resolve_path(result, check["field"]), dtype=float)
        actual = float(np.min(series)) if len(series) else None
        expected = float(check["value"])
        passed = actual is not None and _compare(actual, check.get("op", ">="), expected, check.get("tolerance", 1e-6))
        return CheckResult(name, passed, _format_compare(actual, check.get("op", ">="), expected), actual, expected)

    if kind == "series_max":
        series = np.asarray(_resolve_path(result, check["field"]), dtype=float)
        actual = float(np.max(series)) if len(series) else None
        expected = float(check["value"])
        passed = actual is not None and _compare(actual, check.get("op", "<="), expected, check.get("tolerance", 1e-6))
        return CheckResult(name, passed, _format_compare(actual, check.get("op", "<="), expected), actual, expected)

    if kind == "window_sum":
        series = np.asarray(_resolve_path(result, check["field"]), dtype=float)
        mask = _time_window_mask(inp.timestamps, check["start"], check["end"])
        actual = float(np.sum(series[mask]) * inp.step_minutes / 60.0)
        expected = float(check["value"])
        passed = _compare(actual, check.get("op", ">="), expected, check.get("tolerance", 1e-6))
        return CheckResult(name, passed, _format_compare(actual, check.get("op", ">="), expected), actual, expected)

    if kind == "no_simultaneous_battery":
        charge = np.asarray(result.batt_charge_kw, dtype=float)
        discharge = np.asarray(result.batt_discharge_kw, dtype=float)
        if len(charge) == 0 and len(discharge) == 0:
            return CheckResult(name, True, "battery inactive")
        overlap = np.minimum(charge, discharge)
        actual = float(np.max(overlap)) if len(overlap) else 0.0
        tolerance = float(check.get("tolerance", 1e-5))
        return CheckResult(name, actual <= tolerance, f"max simultaneous power {actual:.6g} kW", actual, tolerance)

    if kind == "ev_soc_at_departure":
        wallbox = check.get("wallbox") or _first_key(result.ev_soc_kwh)
        series = np.asarray(_dict_get_fuzzy(result.ev_soc_kwh, wallbox), dtype=float)
        departure_hour = int(check.get("departure_hour", _wallbox_departure_hour(config, wallbox)))
        idx = _first_index_at_hour(inp.timestamps, departure_hour)
        actual = float(series[idx])
        if check.get("unit", "soc") == "kwh":
            expected = float(check["value"])
        else:
            capacity = _wallbox_capacity(config, wallbox)
            expected = float(check["value"]) * capacity
        passed = _compare(actual, check.get("op", ">="), expected, check.get("tolerance", 1e-6))
        return CheckResult(name, passed, _format_compare(actual, check.get("op", ">="), expected), actual, expected)

    raise ValueError(f"Unsupported check type: {kind}")


def _apply_input_overrides(data: dict[str, Any], overrides: dict[str, Any]) -> None:
    if not overrides:
        return
    timestamps = data["timestamps"]
    num_steps = data["num_steps"]
    for external_key, spec in overrides.items():
        if external_key not in SERIES_KEYS:
            raise ValueError(f"Unknown input override: {external_key}")
        data[SERIES_KEYS[external_key]] = _build_series(spec, timestamps, num_steps)


def _build_series(spec: Any, timestamps: list[dt.datetime], num_steps: int) -> np.ndarray:
    if isinstance(spec, (int, float)):
        return np.full(num_steps, float(spec))
    if isinstance(spec, list):
        arr = np.asarray(spec, dtype=float)
        return _fit_array(arr, num_steps)
    if not isinstance(spec, dict):
        raise ValueError(f"Unsupported series spec: {spec!r}")

    if "values" in spec:
        arr = np.asarray(spec["values"], dtype=float)
        base = _fit_array(arr, num_steps)
    else:
        base = np.full(num_steps, float(spec.get("default", 0.0)))

    for window in spec.get("windows", []):
        value = float(window["value"])
        mask = _time_window_mask(timestamps, window["start"], window["end"])
        base[mask] = value
    return base


def _fit_array(arr: np.ndarray, num_steps: int) -> np.ndarray:
    if len(arr) == num_steps:
        return arr
    if len(arr) == 0:
        return np.zeros(num_steps)
    if len(arr) > num_steps:
        return arr[:num_steps]
    return np.pad(arr, (0, num_steps - len(arr)), mode="edge")


def _time_window_mask(timestamps: list[dt.datetime], start: str, end: str) -> np.ndarray:
    start_t = _parse_time(start)
    end_t = _parse_time(end)
    mask = []
    wraps = end_t <= start_t
    for ts in timestamps:
        t = ts.time()
        if wraps:
            mask.append(t >= start_t or t < end_t)
        else:
            mask.append(start_t <= t < end_t)
    return np.asarray(mask, dtype=bool)


def _parse_time(value: str) -> dt.time:
    hour, minute = value.split(":", 1)
    return dt.time(int(hour), int(minute))


def _parse_date(value: str | dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _load_base_config(scenario: dict[str, Any], scenario_path: Path | None) -> dict[str, Any]:
    base_config = scenario.get("base_config")
    if base_config:
        path = Path(base_config)
        if not path.is_absolute() and scenario_path:
            path = scenario_path.parent / path
        return load_config(str(path))
    return copy.deepcopy(DEFAULT_CONFIG)


def _apply_component_switches(config: dict[str, Any], components: dict[str, Any]) -> None:
    for key, enabled in components.items():
        if key in ("wallboxes", "electric_vehicles"):
            for item in config.get(key, []):
                item["enabled"] = bool(enabled)
        else:
            config.setdefault(key, {})["enabled"] = bool(enabled)


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def _resolve_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = _dict_get_fuzzy(cur, part)
        else:
            cur = getattr(cur, part)
    return cur


def _dict_get_fuzzy(mapping: dict[str, Any], key: str) -> Any:
    """Return a dict value while tolerating UI names sanitized by components."""
    if key in mapping:
        return mapping[key]
    normalized = key.replace(" ", "_")
    if normalized in mapping:
        return mapping[normalized]
    for existing_key, value in mapping.items():
        if str(existing_key).replace(" ", "_") == normalized:
            return value
    raise KeyError(key)


def _compare(actual: float, op: str, expected: float, tolerance: float) -> bool:
    if op == "==":
        return abs(actual - expected) <= tolerance
    if op == "!=":
        return abs(actual - expected) > tolerance
    if op == "<":
        return actual < expected + tolerance
    if op == "<=":
        return actual <= expected + tolerance
    if op == ">":
        return actual > expected - tolerance
    if op == ">=":
        return actual >= expected - tolerance
    raise ValueError(f"Unsupported operator: {op}")


def _format_compare(actual: Any, op: str, expected: Any) -> str:
    return f"{actual} {op} {expected}"


def _first_key(mapping: dict[str, Any]) -> str:
    if not mapping:
        raise ValueError("No EV SOC series found in result.")
    return next(iter(mapping.keys()))


def _first_index_at_hour(timestamps: list[dt.datetime], hour: int) -> int:
    for i, ts in enumerate(timestamps):
        if ts.hour == hour and ts.minute == 0:
            return i
    raise ValueError(f"No timestamp found for departure hour {hour}:00.")


def _wallbox_departure_hour(config: dict[str, Any], wallbox: str) -> int:
    for wb in config.get("wallboxes", []):
        if wb.get("name") == wallbox:
            return int(wb.get("departure_hour", 7))
    return 7


def _wallbox_capacity(config: dict[str, Any], wallbox: str) -> float:
    for wb in config.get("wallboxes", []):
        if wb.get("name") == wallbox:
            return float(wb.get("ev_battery_capacity_kwh", 60.0))
    return 60.0


def _summarize_result(result: Any, baseline_cost: float | None) -> dict[str, Any]:
    return {
        "total_cost_eur": _round(result.total_cost_eur),
        "baseline_cost_eur": _round(baseline_cost),
        "savings_eur": _round(result.savings_eur),
        "pv_total_kwh": _round(result.pv_total_kwh),
        "load_total_kwh": _round(result.load_total_kwh),
        "grid_buy_total_kwh": _round(result.grid_buy_total_kwh),
        "grid_sell_total_kwh": _round(result.grid_sell_total_kwh),
        "eigenverbrauch_pct": _round(result.eigenverbrauch_pct),
        "autarkie_pct": _round(result.autarkie_pct),
        "hp_total_kwh": _round(result.hp_total_kwh),
        "hp_starts_count": result.hp_starts_count,
        "battery_throughput_kwh": _round(result.battery_throughput_kwh),
        "solve_time_s": _round(result.solve_time_s),
    }


def _round(value: Any) -> Any:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except Exception:
        return value


def _to_jsonable(run: ScenarioRunResult) -> dict[str, Any]:
    return {
        "name": run.name,
        "mode": run.mode,
        "passed": run.passed,
        "success": run.success,
        "solver_status": run.solver_status,
        "summary": run.summary,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "detail": c.detail,
                "actual": _json_value(c.actual),
                "expected": _json_value(c.expected),
            }
            for c in run.checks
        ],
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run EMOS Light YAML test scenarios.")
    parser.add_argument("scenarios", nargs="+", help="Scenario YAML file(s)")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)

    runs = [run_scenario_file(path) for path in args.scenarios]
    if args.json:
        print(json.dumps([_to_jsonable(run) for run in runs], indent=2, ensure_ascii=False))
    else:
        for run in runs:
            status = "PASS" if run.passed else "FAIL"
            print(f"[{status}] {run.name} ({run.mode}) - {run.solver_status}")
            for key, value in run.summary.items():
                print(f"  {key}: {value}")
            for check in run.checks:
                mark = "OK" if check.passed else "FAIL"
                print(f"  [{mark}] {check.name}: {check.detail}")
            print()

    return 0 if all(run.passed for run in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
