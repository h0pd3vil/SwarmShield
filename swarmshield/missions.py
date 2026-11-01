"""Mission definitions, objective checks, provisional score, and run artifacts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import uuid
from typing import Any

from .config import SimulationConfig, config_from_dict
from .runner import write_events
from .tasks import parse_task_definitions


ROOT = Path(__file__).resolve().parent.parent
MISSION_DIR = ROOT / "configs" / "missions"
RUNS_DIR = ROOT / "runs"
ENGINE_VERSION = "0.2.0"
DEFAULT_WEIGHTS = {
    "awareness": 0.30,
    "timeliness": 0.30,
    "reliability": 0.25,
    "efficiency": 0.15,
}


def mission_ids() -> list[str]:
    return sorted(path.stem for path in MISSION_DIR.glob("*.json"))


def load_mission(scenario_id: str, seed: int | None = None) -> tuple[SimulationConfig, dict[str, Any]]:
    if not scenario_id or Path(scenario_id).name != scenario_id:
        raise ValueError("scenario must be a mission identifier")
    path = MISSION_DIR / f"{scenario_id}.json"
    if not path.is_file():
        raise ValueError(f"unknown scenario '{scenario_id}'")
    data = json.loads(path.read_text(encoding="utf-8"))
    mission = data.get("_mission")
    if not isinstance(mission, dict):
        raise ValueError(f"scenario '{scenario_id}' has no mission metadata")
    config = config_from_dict(data)
    mission["tasks"] = [
        task.to_dict()
        for task in parse_task_definitions(
            mission.get("tasks", []),
            config.world_width,
            config.world_height,
            config.steps,
        )
    ]
    if seed is not None:
        config = replace(config, seed=seed)
        config.validate()
    return config, mission


def _objective_guidance(metric: str, actual: Any, target: Any, operator: str, passed: bool) -> str:
    if passed:
        return "Target met; it must still hold when the run reaches its horizon."
    if actual is None:
        if metric == "recovery_time_steps":
            return "No recovery time has been measured yet. It becomes available only after fresh-track recovery is observed following restoration."
        return "The engine has no measurement for this objective yet; unavailable values do not count as a pass."
    if operator == ">=":
        gap = max(0.0, float(target) - float(actual))
        if metric == "entity_protection_task_completion_rate":
            return "Needs %.1f percentage points more completed protection tasks. Each task requires two fresh local observations within its configured radius; check its UAV assignment and deadline." % (gap * 100.0)
        if metric.endswith("coverage"):
            return "Needs %.1f percentage points to reach the target. Coverage changes through simulated observations and sharing; there is no direct coverage intervention." % (gap * 100.0)
        if metric == "task_completion_rate":
            return "Needs %.1f percentage points to reach the target. Apply scheduler can change the ordering of future work; completed tasks are not replayed." % (gap * 100.0)
        if metric.endswith("rate"):
            return "Needs %.1f percentage points to reach the target. Only future engine ticks can change this rate." % (gap * 100.0)
        return "Needs %.3g more to reach the target. Only future engine ticks can change this measurement." % gap
    if operator == "<=":
        gap = max(0.0, float(actual) - float(target))
        if metric == "deadline_miss_rate":
            return "Needs %.1f percentage points fewer deadline misses. Apply scheduler can change how future queued work is ordered." % (gap * 100.0)
        if metric == "recovery_time_steps":
            return "Recovery is %.3g ticks over target. Recovery depends on fresh-track convergence after the simulated network is restored." % gap
        return "Needs a reduction of %.3g to reach the target. Only future engine ticks can change this measurement." % gap
    return "This objective is not met; see the engine value and configured target."


def evaluate_mission(
    mission: dict[str, Any], metrics: dict[str, Any], completed: bool
) -> dict[str, Any]:
    results = []
    for objective in mission.get("objectives", []):
        name = str(objective["metric"])
        actual = metrics.get(name)
        target = objective["target"]
        operator = objective.get("operator", ">=")
        passed = False
        if actual is not None:
            if operator == ">=":
                passed = actual >= target
            elif operator == "<=":
                passed = actual <= target
            else:
                raise ValueError(f"unsupported mission objective operator: {operator}")
        passed = bool(passed)
        results.append({
            "id": objective.get("id", name),
            "label": objective.get("label", name),
            "metric": name,
            "operator": operator,
            "target": target,
            "actual": actual,
            "passed": passed,
            "guidance": _objective_guidance(name, actual, target, operator, passed),
        })
    success = bool(results) and all(row["passed"] for row in results)
    status = "incomplete" if not completed else ("success" if success else "failure")
    return {
        "status": status,
        "objectives": results,
    }


def calculate_score(metrics: dict[str, Any], weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Return separate normalized dimensions and a transparent weighted score."""
    selected_weights = dict(weights or DEFAULT_WEIGHTS)
    if set(selected_weights) != set(DEFAULT_WEIGHTS) or any(value < 0 for value in selected_weights.values()):
        raise ValueError("scoring weights must define non-negative awareness, timeliness, reliability, efficiency")
    weight_sum = sum(selected_weights.values())
    if weight_sum <= 0:
        raise ValueError("at least one scoring weight must be positive")

    raw = {
        "awareness": metrics.get("any_agent_awareness_coverage"),
        "timeliness": None if metrics.get("deadline_miss_rate") is None else 1.0 - metrics["deadline_miss_rate"],
        "reliability": metrics.get("message_delivery_ratio"),
        "efficiency": metrics.get("task_completion_rate"),
    }
    definitions = {
        "awareness": "Fraction of synthetic entities held as a fresh track by at least one agent; higher is better.",
        "timeliness": "One minus the engine's eligible-task deadline-miss rate; higher is better.",
        "reliability": "Delivered original peer messages divided by sent originals; unavailable when no messages were sent.",
        "efficiency": "Completed decision tasks divided by created decision tasks; higher is better.",
    }
    available_weight = sum(selected_weights[key] for key, value in raw.items() if value is not None)
    components = {}
    weighted_sum = 0.0
    for key, value in raw.items():
        weight = selected_weights[key]
        normalized = None if value is None else max(0.0, min(1.0, float(value)))
        contribution = (normalized * weight / available_weight) if normalized is not None and available_weight else None
        if contribution is not None:
            weighted_sum += contribution
        components[key] = {
            "raw_value": value,
            "normalized_value": normalized,
            "configured_weight": weight,
            "effective_weight": weight / available_weight if normalized is not None and available_weight else None,
            "weighted_contribution": contribution,
            "definition": definitions[key],
        }
    return {
        "total_score": round(weighted_sum * 100.0, 2) if available_weight else None,
        "scale": "0-100",
        "weights": selected_weights,
        "components": components,
        "weight_note": "Unavailable dimensions are omitted and remaining weights are renormalized; these provisional weights need playtesting and research validation.",
    }


def finalize_game_result(session: Any, mission: dict[str, Any]) -> dict[str, Any]:
    assert session.summary is not None
    metrics = session.summary["metrics"]
    mission_result = evaluate_mission(mission, metrics, completed=session.step >= session.config.steps)
    score = calculate_score(metrics, mission.get("scoring_weights"))
    return {"mission": mission_result, "score": score}


def save_run_artifacts(
    session: Any,
    mission: dict[str, Any],
    run_id: str | None = None,
    artifact_metadata: dict[str, Any] | None = None,
) -> Path:
    """Persist a completed or explicitly-ended run using stable JSON/CSV files."""
    if not session.finished:
        session.finalize()
    assert session.summary is not None
    game_result = finalize_game_result(session, mission)
    session.summary["game_result"] = game_result
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    started = session.started_at_utc
    ended = datetime.now(timezone.utc).isoformat()
    identifier = run_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    output = RUNS_DIR / identifier
    output.mkdir(parents=False, exist_ok=False)
    config_data = session.config.to_dict()
    config_bytes = json.dumps(config_data, sort_keys=True, separators=(",", ":")).encode()
    manifest = {
        "schema_version": 1,
        "run_id": identifier,
        "scenario_id": mission.get("id"),
        "scenario_name": mission.get("name"),
        "seed": session.config.seed,
        "engine_version": ENGINE_VERSION,
        "protocol_version": 1,
        "source_revision": None,
        "source_revision_note": "unavailable: workspace has no Git metadata",
        "configuration_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "started_at_utc": started,
        "ended_at_utc": ended,
        "configured_steps": session.config.steps,
        "actual_steps": session.step,
        "python_version": platform.python_version(),
        "event_schema_version": 1,
        "summary_schema_version": 1,
    }
    if artifact_metadata:
        manifest["comparison"] = artifact_metadata
    (output / "scenario.json").write_text(json.dumps({"mission": mission, "configuration": config_data}, indent=2, sort_keys=True), encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(session.summary, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    (output / "interventions.json").write_text(json.dumps({"schema_version": 1, "interventions": session.interventions}, indent=2, sort_keys=True), encoding="utf-8")
    write_events(output / "events.csv", session.events)
    return output
