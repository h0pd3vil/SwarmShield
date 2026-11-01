"""Run matched primary, processing-load, and communication experiments."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from swarmshield.config import load_config
from swarmshield.runner import run_simulation, write_events


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _primary_conditions() -> list[tuple[str, str]]:
    return [
        (mode, policy)
        for mode in ("independent", "cooperative")
        for policy in ("fixed-priority", "edf")
    ]


def _overload_designs() -> list[tuple[str, int, dict[str, Any]]]:
    return [
        ("processing_capacity_per_step", value, {"processing_capacity_per_step": value})
        for value in (16, 24, 32, 48, 64, 96)
    ] + [
        ("queue_capacity", value, {"queue_capacity": value})
        for value in (32, 64, 128, 500)
    ] + [
        ("entity_count", value, {"entity_count": value})
        for value in (6, 12, 24, 36)
    ] + [
        ("max_task_processing_cost", value, {"max_task_processing_cost": value})
        for value in (1, 3, 6)
    ] + [
        ("max_task_deadline_steps", value, {"max_task_deadline_steps": value})
        for value in (4, 8, 12, 24)
    ]


def _communication_designs() -> list[tuple[str, Any, dict[str, Any]]]:
    return [
        ("delivery_probability", value, {"delivery_probability": value})
        for value in (0.5, 0.7, 0.9, 1.0)
    ] + [
        ("max_latency_steps", value, {"max_latency_steps": value})
        for value in (0, 4, 8, 12)
    ] + [
        ("duplicate_probability", value, {"duplicate_probability": value})
        for value in (0.0, 0.02, 0.1, 0.25)
    ] + [
        ("partition_enabled", value, {"partition_enabled": value})
        for value in (False, True)
    ]


def run_research(
    output_dir: str | Path,
    primary_seed_count: int = 30,
    sweep_seed_count: int = 10,
    start_seed: int = 42,
    config_path: str | Path = "configs/baseline.json",
) -> dict[str, Any]:
    if primary_seed_count < 2 or sweep_seed_count < 2:
        raise ValueError("primary and sweep seed counts must each be at least two")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    sample_event_dir = output / "sample_events"
    sample_event_dir.mkdir()
    base_config = load_config(config_path)
    primary_seeds = list(range(start_seed, start_seed + primary_seed_count))
    sweep_seeds = list(range(start_seed, start_seed + sweep_seed_count))
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    run_started = perf_counter()

    plan = {
        "config_path": str(config_path),
        "base_configuration": base_config.to_dict(),
        "start_seed": start_seed,
        "primary_seeds": primary_seeds,
        "sweep_seeds": sweep_seeds,
        "primary_conditions": [
            {"mode": mode, "policy": policy} for mode, policy in _primary_conditions()
        ],
        "overload_factors": [
            {"factor": factor, "level": level, "overrides": overrides}
            for factor, level, overrides in _overload_designs()
        ],
        "communication_factors": [
            {"factor": factor, "level": level, "overrides": overrides}
            for factor, level, overrides in _communication_designs()
        ],
        "sweep_mode_policy": {"mode": "cooperative", "policy": base_config.scheduler_policy},
        "communication_modes": ["independent", "cooperative"],
        "sample_event_seed": start_seed,
    }
    (output / "run_plan.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8"
    )

    raw_path = output / "runs.jsonl"
    with raw_path.open("x", encoding="utf-8") as raw_file:
        def execute(
            group: str,
            factor: str,
            level: Any,
            overrides: dict[str, Any],
            mode: str,
            policy: str,
            seed: int,
            save_sample_events: bool = False,
        ) -> None:
            config = replace(base_config, seed=seed, **overrides)
            config.validate()
            try:
                summary, events = run_simulation(config, mode, policy)
            except Exception as error:
                failure = {
                    "group": group,
                    "factor": factor,
                    "level": str(level),
                    "mode": mode,
                    "policy": policy,
                    "seed": str(seed),
                    "error": f"{type(error).__name__}: {error}",
                }
                failures.append(failure)
                raise

            delivery_outcomes = Counter(
                str(event["details"])
                for event in events
                if event["event_type"] == "message_delivered"
            )
            event_metrics = {
                "original_messages_queued_for_decision": delivery_outcomes["queued"],
                "original_messages_rejected_by_decision_queue": delivery_outcomes["queue_overload"],
                "original_messages_with_unknown_recipient": delivery_outcomes["unknown_recipient"],
            }
            row = {
                "experiment_group": group,
                "factor": factor,
                "level": level,
                "seed": seed,
                "mode": mode,
                "policy": policy,
                "steps": config.steps,
                "event_count": len(events),
                "scenario_overrides": dict(overrides),
                "derived_event_metrics": event_metrics,
                "summary": summary,
            }
            raw_file.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            raw_file.flush()
            rows.append(row)

            if save_sample_events:
                level_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(level)).strip("_")
                filename = f"seed-{seed}_{group}_{factor}_{level_slug}_{mode}_{policy}.csv"
                write_events(sample_event_dir / filename, events)

        for seed in primary_seeds:
            for mode, policy in _primary_conditions():
                execute(
                    "primary",
                    "condition",
                    f"{mode}|{policy}",
                    {},
                    mode,
                    policy,
                    seed,
                    save_sample_events=(seed == start_seed),
                )

        for factor, level, overrides in _overload_designs():
            for seed in sweep_seeds:
                execute(
                    "processing_overload",
                    factor,
                    level,
                    overrides,
                    "cooperative",
                    base_config.scheduler_policy,
                    seed,
                    save_sample_events=(seed == start_seed),
                )

        for factor, level, overrides in _communication_designs():
            for mode in ("independent", "cooperative"):
                for seed in sweep_seeds:
                    execute(
                        "communication",
                        factor,
                        level,
                        overrides,
                        mode,
                        base_config.scheduler_policy,
                        seed,
                        save_sample_events=(seed == start_seed),
                    )

    metric_names = sorted(rows[0]["summary"]["metrics"])
    csv_fields = [
        "experiment_group",
        "factor",
        "level",
        "seed",
        "mode",
        "policy",
        "steps",
        "event_count",
        "scenario_overrides",
        "effective_configuration",
        "original_messages_queued_for_decision",
        "original_messages_rejected_by_decision_queue",
        "original_messages_with_unknown_recipient",
        *metric_names,
    ]
    with (output / "runs.csv").open("x", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{key: row[key] for key in csv_fields[:8]},
                    "scenario_overrides": json.dumps(row["scenario_overrides"], sort_keys=True),
                    "effective_configuration": json.dumps(
                        row["summary"]["configuration"], sort_keys=True
                    ),
                    **row["derived_event_metrics"],
                    **row["summary"]["metrics"],
                }
            )

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": _git_commit(),
        "primary_run_count": primary_seed_count * len(_primary_conditions()),
        "sweep_run_count": len(rows) - primary_seed_count * len(_primary_conditions()),
        "total_run_count": len(rows),
        "failed_run_count": len(failures),
        "elapsed_seconds": perf_counter() - run_started,
        "output_files": [
            "run_plan.json",
            "runs.jsonl",
            "runs.csv",
            "sample_events/",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    if failures:
        (output / "failures.json").write_text(
            json.dumps(failures, indent=2, sort_keys=True), encoding="utf-8"
        )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run reproducible SwarmShield research experiments")
    parser.add_argument("--config", default="configs/baseline.json")
    parser.add_argument("--output-dir", required=True, help="New directory; existing paths are not overwritten")
    parser.add_argument("--primary-seeds", type=int, default=30)
    parser.add_argument("--sweep-seeds", type=int, default=10)
    parser.add_argument("--start-seed", type=int, default=42)
    args = parser.parse_args(argv)

    try:
        manifest = run_research(
            output_dir=args.output_dir,
            primary_seed_count=args.primary_seeds,
            sweep_seed_count=args.sweep_seeds,
            start_seed=args.start_seed,
            config_path=args.config,
        )
    except (OSError, ValueError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
