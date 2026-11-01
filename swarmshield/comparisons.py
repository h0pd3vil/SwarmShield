"""Matched-seed comparison runs and saved comparison artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import uuid
from typing import Any

from . import missions
from .missions import load_mission, save_run_artifacts
from .metrics import summarize_paired_differences
from .session import SimulationSession
from .tasks import parse_task_definitions


COMPARISON_METRICS: dict[str, dict[str, str]] = {
    "game_score": {"label": "Provisional game score", "direction": "higher"},
    "any_agent_awareness_coverage": {"label": "Fresh team coverage", "direction": "higher"},
    "mean_agent_track_coverage": {"label": "Mean local coverage", "direction": "higher"},
    "message_delivery_ratio": {"label": "Original message delivery", "direction": "higher"},
    "deadline_miss_rate": {"label": "Deadline miss rate", "direction": "lower"},
    "decision_latency_p95_steps": {"label": "95th percentile decision latency", "direction": "lower"},
    "mean_queue_backlog_tasks": {"label": "Mean queue backlog", "direction": "lower"},
    "task_completion_rate": {"label": "Decision task completion", "direction": "higher"},
    "recovery_time_steps": {"label": "Network recovery time", "direction": "lower"},
    "mission_task_completion_rate": {"label": "Mission task completion", "direction": "higher"},
    "mission_task_deadline_miss_rate": {"label": "Mission task deadline misses", "direction": "lower"},
    "mission_area_coverage_fraction": {"label": "Mission area sensor coverage", "direction": "higher"},
    "mission_completion_time_steps": {"label": "Mission completion time", "direction": "lower"},
    "total_uav_distance_travelled": {"label": "UAV distance travelled (world units)", "direction": "lower"},
    "uav_energy_consumed": {"label": "UAV energy consumed", "direction": "lower"},
    "mean_observation_to_shared_application_delay_steps": {"label": "Shared report application delay", "direction": "lower"},
}


def run_matched_comparison(
    scenario_id: str,
    start_seed: int,
    seed_count: int,
    dimension: str,
    mode: str,
    policy: str,
) -> dict[str, Any]:
    """Run both treatments at every same seed, saving each run and the paired result."""
    if dimension not in {"scheduler", "sharing"}:
        raise ValueError("dimension must be 'scheduler' or 'sharing'")
    if not isinstance(start_seed, int) or isinstance(start_seed, bool) or start_seed < 0:
        raise ValueError("start_seed must be a non-negative integer")
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or not 2 <= seed_count <= 30:
        raise ValueError("seed_count must be from 2 to 30 for a matched comparison")
    if mode not in {"independent", "cooperative"}:
        raise ValueError("mode must be 'independent' or 'cooperative'")
    if policy not in {"fixed-priority", "edf"}:
        raise ValueError("policy must be 'fixed-priority' or 'edf'")
    # Validate the mission before creating any output directories.
    base_config, mission = load_mission(scenario_id, start_seed)

    if dimension == "scheduler":
        left = {"label": "Fixed priority", "mode": mode, "policy": "fixed-priority"}
        right = {"label": "EDF", "mode": mode, "policy": "edf"}
        held_constant = {"team_mode": mode}
        difference_label = "EDF minus fixed priority"
    else:
        left = {"label": "Independent", "mode": "independent", "policy": policy}
        right = {"label": "Cooperative", "mode": "cooperative", "policy": policy}
        held_constant = {"scheduler_policy": policy}
        difference_label = "Cooperative minus independent"

    comparison_id = "matched-%s-%s-%s" % (
        dimension,
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:8],
    )
    run_records: list[dict[str, Any]] = []
    runs_by_seed: dict[int, dict[str, dict[str, Any]]] = {}

    for seed in range(start_seed, start_seed + seed_count):
        runs_by_seed[seed] = {}
        for side, treatment in (("left", left), ("right", right)):
            config, run_mission = load_mission(scenario_id, seed)
            task_definitions = parse_task_definitions(
                run_mission.get("tasks", []), config.world_width, config.world_height, config.steps,
            )
            session = SimulationSession(
                config, treatment["mode"], treatment["policy"], mission_tasks=task_definitions,
            )
            session.assign_pending_mission_tasks()
            session.run_autonomous_behaviors()
            while not session.finished:
                session.advance_tick()
            if session.summary is None:
                raise RuntimeError("completed comparison run has no summary")
            artifact_path = save_run_artifacts(
                session,
                run_mission,
                artifact_metadata={
                    "comparison_id": comparison_id,
                    "dimension": dimension,
                    "seed": seed,
                    "treatment": side,
                    "mode": treatment["mode"],
                    "scheduler_policy": treatment["policy"],
                },
            )
            summary = session.summary
            score = summary["game_result"]["score"]["total_score"]
            metrics: dict[str, Any] = dict(summary["metrics"])
            metrics["game_score"] = score
            record = {
                "run_id": artifact_path.name,
                "artifact_path": str(artifact_path.resolve()),
                "seed": seed,
                "treatment": side,
                "treatment_label": treatment["label"],
                "mode": treatment["mode"],
                "scheduler_policy": treatment["policy"],
                "mission_status": summary["game_result"]["mission"]["status"],
                "metrics": {key: metrics.get(key) for key in COMPARISON_METRICS},
                "objectives": summary["game_result"]["mission"]["objectives"],
            }
            run_records.append(record)
            runs_by_seed[seed][side] = record

    paired: list[dict[str, Any]] = []
    for seed in sorted(runs_by_seed):
        left_run = runs_by_seed[seed]["left"]
        right_run = runs_by_seed[seed]["right"]
        differences: dict[str, float | None] = {}
        values: dict[str, dict[str, Any]] = {}
        for metric in COMPARISON_METRICS:
            left_value = left_run["metrics"].get(metric)
            right_value = right_run["metrics"].get(metric)
            numeric = all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in (left_value, right_value)
            )
            difference = float(right_value) - float(left_value) if numeric else None
            values[metric] = {"left": left_value, "right": right_value}
            differences[metric] = difference
        paired.append({"seed": seed, "values": values, "differences": differences})

    aggregates: dict[str, dict[str, Any]] = {}
    for metric in COMPARISON_METRICS:
        left_values: list[float] = []
        right_values: list[float] = []
        deltas: list[float] = []
        for pair in paired:
            left_value = pair["values"][metric]["left"]
            right_value = pair["values"][metric]["right"]
            delta = pair["differences"][metric]
            if delta is None:
                continue
            left_values.append(float(left_value))
            right_values.append(float(right_value))
            deltas.append(float(delta))
        aggregates[metric] = {
            "left_mean": statistics.fmean(left_values) if left_values else None,
            "right_mean": statistics.fmean(right_values) if right_values else None,
            "median_difference": statistics.median(deltas) if deltas else None,
            "min_difference": min(deltas) if deltas else None,
            "max_difference": max(deltas) if deltas else None,
            **summarize_paired_differences(deltas),
        }

    created_at = datetime.now(timezone.utc).isoformat()
    comparison = {
        "schema_version": 1,
        "comparison_id": comparison_id,
        "created_at_utc": created_at,
        "design": "matched_seed",
        "dimension": dimension,
        "scenario_id": scenario_id,
        "scenario_name": str(mission.get("name", scenario_id)),
        "configured_steps": base_config.steps,
        "start_seed": start_seed,
        "seed_count": seed_count,
        "seeds": list(range(start_seed, start_seed + seed_count)),
        "left_treatment": left,
        "right_treatment": right,
        "held_constant": held_constant,
        "difference_label": difference_label,
        "difference_definition": "right treatment minus left treatment at the same seed",
        "interpretation_note": "Paired descriptive results with two-sided 95% Student-t intervals over seed-level differences. Small samples and distribution assumptions limit inference; intervals are not a significance test.",
        "metric_definitions": COMPARISON_METRICS,
        "runs": run_records,
        "paired_results": paired,
        "aggregates": aggregates,
    }
    comparison_directory = missions.RUNS_DIR / "comparisons"
    comparison_directory.mkdir(parents=True, exist_ok=True)
    comparison_path = comparison_directory / f"{comparison_id}.json"
    comparison["artifact_path"] = str(comparison_path.resolve())
    comparison_path.write_text(json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    return comparison


def list_saved_comparisons() -> list[dict[str, Any]]:
    directory = missions.RUNS_DIR / "comparisons"
    if not directory.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for path in sorted(directory.glob("matched-*.json"), reverse=True):
        try:
            comparison = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        summaries.append({
            "comparison_id": str(comparison.get("comparison_id", path.stem)),
            "scenario_name": str(comparison.get("scenario_name", comparison.get("scenario_id", "Mission"))),
            "dimension": str(comparison.get("dimension", "scheduler")),
            "seed_count": int(comparison.get("seed_count", 0)),
            "start_seed": int(comparison.get("start_seed", 0)),
            "created_at_utc": str(comparison.get("created_at_utc", "")),
            "artifact_path": str(path.resolve()),
        })
    return sorted(summaries, key=lambda row: str(row.get("created_at_utc", "")), reverse=True)


def load_saved_comparison(comparison_id: str) -> dict[str, Any] | None:
    if not comparison_id or Path(comparison_id).name != comparison_id:
        return None
    path = missions.RUNS_DIR / "comparisons" / f"{comparison_id}.json"
    if not path.is_file():
        return None
    comparison = json.loads(path.read_text(encoding="utf-8"))
    if comparison.get("comparison_id") != comparison_id:
        return None
    return comparison
