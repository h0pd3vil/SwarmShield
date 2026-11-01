"""Summarize saved SwarmShield research runs and generate comparison figures."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter


CONDITIONS = (
    ("independent", "fixed-priority"),
    ("independent", "edf"),
    ("cooperative", "fixed-priority"),
    ("cooperative", "edf"),
)
CONDITION_LABELS = {
    ("independent", "fixed-priority"): "Independent / fixed priority",
    ("independent", "edf"): "Independent / EDF",
    ("cooperative", "fixed-priority"): "Cooperative / fixed priority",
    ("cooperative", "edf"): "Cooperative / EDF",
}
FIGURE_STEMS = (
    "awareness_sharing_comparison",
    "communication_sensitivity",
    "deadline_miss_policy_comparison",
    "partition_recovery",
    "p95_latency_boxplot",
    "primary_conditions",
    "processing_capacity_sweep",
    "queue_capacity_sweep",
)


def _metrics_for_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row["summary"]["metrics"],
        **row.get("derived_event_metrics", {}),
    }


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _t_critical_95(sample_count: int) -> float | None:
    if sample_count < 2:
        return None
    degrees = sample_count - 1
    exact = {9: 2.262157, 29: 2.045230}
    if degrees in exact:
        return exact[degrees]

    # Cornish-Fisher expansion of the two-sided 95% Student-t quantile.
    z = 1.959963984540054
    v = float(degrees)
    return (
        z
        + (z**3 + z) / (4.0 * v)
        + (5.0 * z**5 + 16.0 * z**3 + 3.0 * z) / (96.0 * v**2)
        + (3.0 * z**7 + 19.0 * z**5 + 17.0 * z**3 - 15.0 * z) / (384.0 * v**3)
        + (79.0 * z**9 + 776.0 * z**7 + 1482.0 * z**5 - 1920.0 * z**3 - 945.0 * z)
        / (92160.0 * v**4)
    )


def summarize(values: Iterable[int | float]) -> dict[str, float | int | None]:
    samples = [float(value) for value in values if math.isfinite(float(value))]
    count = len(samples)
    if not samples:
        return {
            "n": 0,
            "mean": None,
            "standard_deviation": None,
            "median": None,
            "q1": None,
            "q3": None,
            "iqr": None,
            "minimum": None,
            "maximum": None,
            "ci95_low": None,
            "ci95_high": None,
        }

    mean = statistics.fmean(samples)
    standard_deviation = statistics.stdev(samples) if count > 1 else None
    critical = _t_critical_95(count)
    margin = critical * standard_deviation / math.sqrt(count) if critical and standard_deviation is not None else None
    q1 = _quantile(samples, 0.25)
    q3 = _quantile(samples, 0.75)
    return {
        "n": count,
        "mean": mean,
        "standard_deviation": standard_deviation,
        "median": statistics.median(samples),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
        "minimum": min(samples),
        "maximum": max(samples),
        "ci95_low": mean - margin if margin is not None else None,
        "ci95_high": mean + margin if margin is not None else None,
    }


def _read_runs(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as run_file:
        for line_number, line in enumerate(run_file, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON at {path}:{line_number}: {error}") from error
            rows.append(row)
    if not rows:
        raise ValueError(f"No run records found in {path}")
    return rows


def _level_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _group_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            row["experiment_group"],
            row["factor"],
            _level_key(row["level"]),
            row["mode"],
            row["policy"],
        )
        grouped.setdefault(key, []).append(row)
    return grouped


def _write_statistics(rows: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    numeric_metrics = sorted(
        {
            metric
            for row in rows
            for metric, value in _metrics_for_row(row).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    )
    statistics_rows = []
    for key, group in sorted(_group_rows(rows).items()):
        group_name, factor, level, mode, policy = key
        for metric in numeric_metrics:
            values = [
                _metrics_for_row(row).get(metric)
                for row in group
                if isinstance(_metrics_for_row(row).get(metric), (int, float))
                and not isinstance(_metrics_for_row(row).get(metric), bool)
            ]
            stats = summarize(values)
            statistics_rows.append(
                {
                    "experiment_group": group_name,
                    "factor": factor,
                    "level": level,
                    "mode": mode,
                    "policy": policy,
                    "metric": metric,
                    **stats,
                }
            )

    fields = [
        "experiment_group", "factor", "level", "mode", "policy", "metric", "n",
        "mean", "standard_deviation", "median", "q1", "q3", "iqr", "minimum", "maximum",
        "ci95_low", "ci95_high",
    ]
    with output.open("x", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(statistics_rows)
    return statistics_rows


def _paired_comparisons(rows: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    primary = [row for row in rows if row["experiment_group"] == "primary"]
    by_seed = {
        (row["seed"], row["mode"], row["policy"]): _metrics_for_row(row)
        for row in primary
    }
    numeric_metrics = sorted(
        {
            metric
            for row in primary
            for metric, value in _metrics_for_row(row).items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    )
    comparisons: list[tuple[str, str, str, str, str]] = []
    for policy in ("fixed-priority", "edf"):
        comparisons.append(("cooperative_minus_independent", "mode", "cooperative", "independent", policy))
    for mode in ("independent", "cooperative"):
        comparisons.append(("edf_minus_fixed_priority", "policy", "edf", "fixed-priority", mode))

    result = []
    for comparison, dimension, left, right, control in comparisons:
        for metric in numeric_metrics:
            differences = []
            for seed in sorted({row["seed"] for row in primary}):
                if dimension == "mode":
                    left_values = by_seed.get((seed, left, control), {})
                    right_values = by_seed.get((seed, right, control), {})
                else:
                    left_values = by_seed.get((seed, control, left), {})
                    right_values = by_seed.get((seed, control, right), {})
                a = left_values.get(metric)
                b = right_values.get(metric)
                if (
                    isinstance(a, (int, float))
                    and not isinstance(a, bool)
                    and isinstance(b, (int, float))
                    and not isinstance(b, bool)
                ):
                    differences.append(float(a) - float(b))
            if differences:
                result.append(
                    {
                        "comparison": comparison,
                        "control": control,
                        "metric": metric,
                        "difference_direction": "left condition minus right condition",
                        **summarize(differences),
                    }
                )

    fields = [
        "comparison", "control", "metric", "difference_direction", "n", "mean",
        "standard_deviation", "median", "q1", "q3", "iqr", "minimum", "maximum",
        "ci95_low", "ci95_high",
    ]
    with output.open("x", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result)
    return result


def _selected(rows: list[dict[str, Any]], **filters: Any) -> list[dict[str, Any]]:
    return [row for row in rows if all(row.get(key) == value for key, value in filters.items())]


def _metric_values(rows: list[dict[str, Any]], metric: str) -> list[float]:
    return [
        float(value)
        for row in rows
        if isinstance((value := _metrics_for_row(row).get(metric)), (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    ]


def _mean_and_error(rows: list[dict[str, Any]], metric: str) -> tuple[float | None, float | None, int]:
    stats = summarize(_metric_values(rows, metric))
    if stats["mean"] is None:
        return None, None, 0
    low = stats["ci95_low"]
    high = stats["ci95_high"]
    error = max(float(stats["mean"]) - float(low), float(high) - float(stats["mean"])) if low is not None and high is not None else 0.0
    return float(stats["mean"]), error, int(stats["n"])


def _bar_with_ci(axis: Any, x: float, selected: list[dict[str, Any]], metric: str, label: str, **kwargs: Any) -> None:
    mean, error, count = _mean_and_error(selected, metric)
    if mean is None:
        return
    axis.bar(x, mean, label=label, yerr=error, capsize=4, **kwargs)
    axis.annotate(f"n={count}", (x, mean), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)


def _save_figure(figure: Any, directory: Path, stem: str) -> None:
    figure.tight_layout()
    figure.savefig(directory / f"{stem}.png", dpi=180, bbox_inches="tight")
    figure.savefig(directory / f"{stem}.svg", bbox_inches="tight")
    plt.close(figure)


def _primary_figures(rows: list[dict[str, Any]], directory: Path) -> None:
    primary = [row for row in rows if row["experiment_group"] == "primary"]
    metric_specs = (
        ("any_agent_awareness_coverage", "Any-agent awareness", True),
        ("deadline_miss_rate", "Decision deadline misses", True),
        ("task_completion_rate", "Decision task completion", True),
        ("decision_latency_p95_steps", "Decision P95 latency (steps)", False),
    )
    figure, axes = plt.subplots(2, 2, figsize=(13, 9))
    labels = [CONDITION_LABELS[item] for item in CONDITIONS]
    colors = ("#4c78a8", "#f58518", "#54a24b", "#e45756")
    for axis, (metric, title, percent) in zip(axes.flat, metric_specs):
        for index, ((mode, policy), label, color) in enumerate(zip(CONDITIONS, labels, colors)):
            selected = [
                row for row in primary
                if row["mode"] == mode and row["policy"] == policy
            ]
            _bar_with_ci(axis, index, selected, metric, label, color=color)
        axis.set_title(title)
        axis.set_xticks(range(len(labels)), labels, rotation=18, ha="right")
        if percent:
            axis.yaxis.set_major_formatter(PercentFormatter(1.0))
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("Primary matched-seed conditions (mean and 95% t interval)")
    _save_figure(figure, directory, "primary_conditions")

    figure, axis = plt.subplots(figsize=(8, 5))
    width = 0.34
    for offset, policy, color in ((-width / 2, "fixed-priority", "#4c78a8"), (width / 2, "edf", "#f58518")):
        for mode_index, mode in enumerate(("independent", "cooperative")):
            selected = [row for row in primary if row["mode"] == mode and row["policy"] == policy]
            mean, error, count = _mean_and_error(selected, "deadline_miss_rate")
            if mean is None:
                continue
            x_position = mode_index + offset
            axis.bar(x_position, mean, width=width * 0.85, color=color)
            axis.errorbar(x_position, mean, yerr=error or 0.0, fmt="none", ecolor="black", capsize=4)
            axis.annotate(
                f"{mean:.2%}",
                (x_position, mean + (error or 0.0)),
                xytext=(0, 5),
                textcoords="offset points",
                ha="center",
                fontsize=8,
            )
            axis.annotate(f"n={count}", (x_position, 0), xytext=(0, -14), textcoords="offset points", ha="center", fontsize=7)
    axis.set_xticks((0, 1), ("Independent", "Cooperative"))
    axis.yaxis.set_major_formatter(PercentFormatter(1.0))
    axis.set_ylabel("Deadline-miss rate")
    axis.set_title("Deadline misses by sharing mode and policy (95% CI)")
    axis.set_ylim(bottom=0)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(handles=(
        Patch(facecolor="#4c78a8", label="Fixed priority"),
        Patch(facecolor="#f58518", label="EDF"),
    ))
    _save_figure(figure, directory, "deadline_miss_policy_comparison")

    figure, axis = plt.subplots(figsize=(8, 5))
    for offset, policy, color in ((-width / 2, "fixed-priority", "#4c78a8"), (width / 2, "edf", "#f58518")):
        for mode_index, mode in enumerate(("independent", "cooperative")):
            selected = [row for row in primary if row["mode"] == mode and row["policy"] == policy]
            mean, error, count = _mean_and_error(selected, "mean_agent_track_coverage")
            if mean is None:
                continue
            x_position = mode_index + offset
            axis.bar(x_position, mean, width=width * 0.85, color=color)
            axis.errorbar(x_position, mean, yerr=error or 0.0, fmt="none", ecolor="black", capsize=4)
            axis.annotate(f"{mean:.1%}", (x_position, mean + (error or 0.0)), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8)
            axis.annotate(f"n={count}", (x_position, 0), xytext=(0, -14), textcoords="offset points", ha="center", fontsize=7)
    axis.set_xticks((0, 1), ("Independent", "Cooperative"))
    axis.yaxis.set_major_formatter(PercentFormatter(1.0))
    axis.set_ylabel("Mean per-agent track coverage")
    axis.set_title("Per-agent awareness by sharing mode and policy (95% CI)")
    axis.set_ylim(0, 1)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(handles=(
        Patch(facecolor="#4c78a8", label="Fixed priority"),
        Patch(facecolor="#f58518", label="EDF"),
    ))
    _save_figure(figure, directory, "awareness_sharing_comparison")

    figure, axis = plt.subplots(figsize=(9, 5))
    box_data = []
    box_labels = []
    for mode, policy in CONDITIONS:
        selected = [row for row in primary if row["mode"] == mode and row["policy"] == policy]
        values = _metric_values(selected, "decision_latency_p95_steps")
        if values:
            box_data.append(values)
            box_labels.append(CONDITION_LABELS[(mode, policy)])
    axis.boxplot(box_data, tick_labels=box_labels, showmeans=True)
    axis.set_ylabel("Per-run P95 decision latency (steps)")
    axis.set_title("Distribution of per-run P95 latency across matched seeds")
    axis.tick_params(axis="x", labelrotation=18)
    axis.grid(axis="y", alpha=0.25)
    _save_figure(figure, directory, "p95_latency_boxplot")


def _factor_runs(rows: list[dict[str, Any]], group: str, factor: str, level: Any, mode: str | None = None) -> list[dict[str, Any]]:
    selected = [row for row in rows if row["experiment_group"] == group and row["factor"] == factor and row["level"] == level]
    if mode is not None:
        selected = [row for row in selected if row["mode"] == mode]
    return selected


def _overload_figures(rows: list[dict[str, Any]], directory: Path) -> None:
    capacity_rows = [
        row for row in rows
        if row["experiment_group"] == "processing_overload" and row["factor"] == "processing_capacity_per_step"
    ]
    capacities = sorted({int(row["level"]) for row in capacity_rows})
    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    for axis, metric, title, percentage in (
        (axes[0], "deadline_miss_rate", "Deadline-miss rate", True),
        (axes[1], "mean_queue_backlog_tasks", "Mean queue backlog", False),
    ):
        means, errors, counts = [], [], []
        for capacity in capacities:
            mean, error, count = _mean_and_error(
                _factor_runs(capacity_rows, "processing_overload", "processing_capacity_per_step", capacity),
                metric,
            )
            means.append(mean)
            errors.append(error or 0.0)
            counts.append(count)
        axis.errorbar(capacities, means, yerr=errors, marker="o", capsize=4)
        for x, y, count in zip(capacities, means, counts):
            if y is not None:
                axis.annotate(f"n={count}", (x, y), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=8)
        axis.set_xlabel("Logical processing capacity per step")
        axis.set_title(title)
        if percentage:
            axis.yaxis.set_major_formatter(PercentFormatter(1.0))
        axis.grid(alpha=0.25)
    figure.suptitle("Processing-capacity sweep (mean and 95% t interval)")
    _save_figure(figure, directory, "processing_capacity_sweep")

    queue_rows = [
        row for row in rows
        if row["experiment_group"] == "processing_overload" and row["factor"] == "queue_capacity"
    ]
    capacities = sorted({int(row["level"]) for row in queue_rows})
    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    for axis, metric, title, percentage in (
        (axes[0], "decision_tasks_dropped_overload", "Tasks dropped at queue limit", False),
        (axes[1], "deadline_miss_rate", "Deadline-miss rate", True),
    ):
        means, errors = [], []
        for capacity in capacities:
            mean, error, _ = _mean_and_error(
                _factor_runs(queue_rows, "processing_overload", "queue_capacity", capacity), metric
            )
            means.append(mean)
            errors.append(error or 0.0)
        axis.errorbar(capacities, means, yerr=errors, marker="o", capsize=4)
        axis.set_xlabel("Decision queue capacity")
        axis.set_title(title)
        if percentage:
            axis.yaxis.set_major_formatter(PercentFormatter(1.0))
        axis.grid(alpha=0.25)
    figure.suptitle("Queue-size sweep at fixed processing capacity")
    _save_figure(figure, directory, "queue_capacity_sweep")


def _communication_figures(rows: list[dict[str, Any]], directory: Path) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(13, 9))
    specs = (
        ("delivery_probability", "Message delivery probability", "message_delivery_ratio", "Delivered original-message ratio"),
        ("max_latency_steps", "Maximum network latency (steps)", "mean_message_latency_steps", "Mean delivered-message latency (steps)"),
        ("duplicate_probability", "Duplicate probability", "duplicate_rejection_rate", "Delivered duplicate rejection rate"),
        ("partition_enabled", "Global partition enabled", "recovery_time_steps", "Recovery time after restoration (steps)"),
    )
    for axis, (factor, title, second_metric, second_label) in zip(axes.flat, specs):
        matching = [row for row in rows if row["experiment_group"] == "communication" and row["factor"] == factor]
        levels = sorted({row["level"] for row in matching}, key=lambda value: (isinstance(value, bool), value))
        twin = axis.twinx()
        for mode, color, marker in (("independent", "#4c78a8", "o"), ("cooperative", "#f58518", "s")):
            x_values = list(range(len(levels)))
            means, errors = [], []
            for level in levels:
                mean, error, _ = _mean_and_error(
                    _factor_runs(matching, "communication", factor, level, mode),
                    "mean_agent_track_coverage",
                )
                means.append(mean)
                errors.append(error or 0.0)
            axis.errorbar(x_values, means, yerr=errors, marker=marker, capsize=3, color=color, label=f"{mode}: per-agent coverage")
        coop_x, coop_means, coop_errors = [], [], []
        for index, level in enumerate(levels):
            mean, error, _ = _mean_and_error(
                _factor_runs(matching, "communication", factor, level, "cooperative"),
                second_metric,
            )
            if mean is not None:
                coop_x.append(index)
                coop_means.append(mean)
                coop_errors.append(error or 0.0)
        if coop_x:
            twin.errorbar(coop_x, coop_means, yerr=coop_errors, marker="^", linestyle="--", color="#54a24b", capsize=3, label=f"cooperative: {second_metric}")
        axis.set_xticks(range(len(levels)), [str(value) for value in levels])
        axis.set_title(title)
        axis.set_ylabel("Mean per-agent track coverage")
        axis.yaxis.set_major_formatter(PercentFormatter(1.0))
        axis.set_xlabel(factor)
        axis.grid(axis="y", alpha=0.2)
        twin.set_ylabel(second_label)
        handles_a, labels_a = axis.get_legend_handles_labels()
        handles_b, labels_b = twin.get_legend_handles_labels()
        axis.legend(handles_a + handles_b, labels_a + labels_b, fontsize=7, loc="best")
    figure.suptitle("Communication sensitivity: mean and 95% t intervals; independent runs send no messages")
    _save_figure(figure, directory, "communication_sensitivity")

    partition_rows = [
        row for row in rows
        if row["experiment_group"] == "communication"
        and row["factor"] == "partition_enabled"
        and row["level"] is True
    ]
    figure, axis = plt.subplots(figsize=(8, 5))
    for index, mode in enumerate(("independent", "cooperative")):
        values = _metric_values([row for row in partition_rows if row["mode"] == mode], "recovery_time_steps")
        if values:
            axis.scatter([index] * len(values), values, alpha=0.75, label=f"{mode} (n={len(values)} recovered)")
            stats = summarize(values)
            axis.errorbar(
                index,
                stats["mean"],
                yerr=[
                    [stats["mean"] - stats["ci95_low"]],
                    [stats["ci95_high"] - stats["mean"]],
                ],
                fmt="D",
                color="black",
                capsize=5,
            )
        else:
            total = sum(row["mode"] == mode for row in partition_rows)
            axis.text(index, 0.25, f"No recovery\n(n={total})", ha="center", va="bottom")
    axis.set_xticks((0, 1), ("Independent", "Cooperative"))
    axis.set_ylabel("Steps from partition restoration to recovery")
    axis.set_title("Per-seed recovery after global partition (enabled runs)")
    axis.set_ylim(bottom=0)
    axis.grid(axis="y", alpha=0.25)
    _save_figure(figure, directory, "partition_recovery")


def analyze(run_dir: str | Path, overwrite: bool = False) -> dict[str, Any]:
    directory = Path(run_dir)
    generated_files = [
        directory / "aggregate_statistics.csv",
        directory / "paired_primary_differences.csv",
        directory / "analysis_summary.json",
    ] + [
        directory / "figures" / f"{stem}.{extension}"
        for stem in FIGURE_STEMS
        for extension in ("png", "svg")
    ]
    existing_outputs = [path for path in generated_files if path.exists()]
    if existing_outputs and not overwrite:
        raise FileExistsError(
            "Analysis output already exists. Pass --overwrite to replace only generated "
            "statistics and figures; raw run records and sample event logs are preserved."
        )
    if overwrite:
        for path in existing_outputs:
            path.unlink()
    figure_dir = directory / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    rows = _read_runs(directory / "runs.jsonl")
    statistics_rows = _write_statistics(rows, directory / "aggregate_statistics.csv")
    paired_rows = _paired_comparisons(rows, directory / "paired_primary_differences.csv")
    _primary_figures(rows, figure_dir)
    _overload_figures(rows, figure_dir)
    _communication_figures(rows, figure_dir)

    primary = [row for row in rows if row["experiment_group"] == "primary"]
    summary = {
        "run_count": len(rows),
        "primary_run_count": len(primary),
        "aggregate_group_metric_rows": len(statistics_rows),
        "paired_comparison_rows": len(paired_rows),
        "primary_condition_summary": [],
        "paired_primary_differences": paired_rows,
        "statistical_method": (
            "Descriptive statistics use sample standard deviation and linear-interpolated quartiles. "
            "Mean 95% intervals use a two-sided Student-t critical value (exact tabulated values for n=10/30; "
            "Cornish-Fisher approximation otherwise). Paired comparisons subtract matched seed outcomes first. "
            "These untransformed intervals can extend outside the valid range for bounded metrics."
        ),
    }
    for mode, policy in CONDITIONS:
        selected = [row for row in primary if row["mode"] == mode and row["policy"] == policy]
        summary["primary_condition_summary"].append(
            {
                "mode": mode,
                "policy": policy,
                "seed_count": len(selected),
                "metrics": {
                    metric: summarize(_metric_values(selected, metric))
                    for metric in (
                        "any_agent_awareness_coverage",
                        "mean_agent_track_coverage",
                        "mean_first_detection_delay_steps",
                        "message_delivery_ratio",
                        "mean_message_latency_steps",
                        "deadline_miss_rate",
                        "task_completion_rate",
                        "decision_latency_p50_steps",
                        "decision_latency_p95_steps",
                        "decision_latency_p99_steps",
                        "mean_queue_backlog_tasks",
                        "max_queue_backlog_tasks",
                        "mean_information_age_at_decision_steps",
                        "original_messages_queued_for_decision",
                        "original_messages_rejected_by_decision_queue",
                        "coordination_task_completion_rate",
                        "assignment_conflict_rate_per_100_tasks",
                        "wall_clock_runtime_seconds",
                    )
                },
            }
        )
    (directory / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a SwarmShield research run directory")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace generated statistics and figures while preserving raw runs and event logs",
    )
    args = parser.parse_args(argv)
    summary = analyze(args.run_dir, overwrite=args.overwrite)
    print(json.dumps({key: summary[key] for key in ("run_count", "primary_run_count", "aggregate_group_metric_rows", "paired_comparison_rows")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
