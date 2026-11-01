"""Run matched mode/policy scenarios over a deterministic seed range."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from swarmshield.config import load_config
from swarmshield.runner import run_simulation, write_events


def run_batch(
    config_path: str | Path,
    seed_count: int,
    start_seed: int | None,
    modes: list[str],
    policies: list[str],
    output_path: str | Path,
    events_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    if seed_count <= 0:
        raise ValueError("seed_count must be greater than zero")
    if not modes or not policies:
        raise ValueError("at least one mode and one policy are required")

    base_config = load_config(config_path)
    first_seed = base_config.seed if start_seed is None else start_seed
    rows: list[dict[str, Any]] = []
    event_directory = Path(events_dir) if events_dir else None

    for seed in range(first_seed, first_seed + seed_count):
        seeded_config = replace(base_config, seed=seed)
        for mode in modes:
            for policy in policies:
                summary, events = run_simulation(seeded_config, mode, policy)
                rows.append(
                    {
                        "seed": seed,
                        "mode": mode,
                        "policy": policy,
                        "steps": seeded_config.steps,
                        "configuration": json.dumps(summary["configuration"], sort_keys=True),
                        **summary["metrics"],
                    }
                )
                if event_directory is not None:
                    event_name = f"seed-{seed}_{mode}_{policy}.csv"
                    write_events(event_directory / event_name, events)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    metric_fields = sorted({key for row in rows for key in row} - {"seed", "mode", "policy", "steps", "configuration"})
    fields = ["seed", "mode", "policy", "steps", "configuration", *metric_fields]
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run matched SwarmShield batch experiments")
    parser.add_argument("--config", default="configs/baseline.json")
    parser.add_argument("--seeds", type=int, default=10, help="Number of consecutive seeds to run")
    parser.add_argument("--start-seed", type=int, help="First seed; defaults to the config seed")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("independent", "cooperative"),
        default=("independent", "cooperative"),
    )
    parser.add_argument(
        "--policies",
        nargs="+",
        choices=("fixed-priority", "edf"),
        default=("fixed-priority", "edf"),
    )
    parser.add_argument("--output", default="experiments/results/batch_summary.csv")
    parser.add_argument("--events-dir", help="Optional directory for per-run event CSV files")
    args = parser.parse_args(argv)

    try:
        rows = run_batch(
            config_path=args.config,
            seed_count=args.seeds,
            start_seed=args.start_seed,
            modes=list(args.modes),
            policies=list(args.policies),
            output_path=args.output,
            events_dir=args.events_dir,
        )
    except (OSError, ValueError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "runs": len(rows),
                "output": str(Path(args.output)),
                "event_directory": args.events_dir,
                "first_seed": args.start_seed,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
