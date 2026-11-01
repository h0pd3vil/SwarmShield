"""Small, deterministic metric helpers shared by the CLI and batch runner."""

from __future__ import annotations

import math
import statistics


def nearest_rank_percentile(values: list[int], percentile: int) -> int | None:
    """Return the nearest-rank percentile, or None when there are no samples."""
    if not 1 <= percentile <= 100:
        raise ValueError("percentile must be between 1 and 100")
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered) / 100))
    return ordered[rank - 1]


def summarize_paired_differences(values: list[int | float]) -> dict[str, object]:
    """Describe matched-seed mean differences with a two-sided 95% t interval."""
    samples = [float(value) for value in values if math.isfinite(float(value))]
    count = len(samples)
    if not samples:
        return {
            "n": 0,
            "mean_difference": None,
            "standard_deviation": None,
            "standard_error": None,
            "ci95_low": None,
            "ci95_high": None,
            "interval_method": "two-sided Student-t interval over paired seed differences",
        }
    mean = statistics.fmean(samples)
    standard_deviation = statistics.stdev(samples) if count > 1 else None
    critical = _student_t_critical_95(count - 1) if count > 1 else None
    standard_error = standard_deviation / math.sqrt(count) if standard_deviation is not None else None
    margin = critical * standard_error if critical is not None and standard_error is not None else None
    return {
        "n": count,
        "mean_difference": mean,
        "standard_deviation": standard_deviation,
        "standard_error": standard_error,
        "ci95_low": mean - margin if margin is not None else None,
        "ci95_high": mean + margin if margin is not None else None,
        "interval_method": "two-sided Student-t interval over paired seed differences",
    }


def _student_t_critical_95(degrees_of_freedom: int) -> float:
    """Critical value for a two-sided 95% Student-t interval."""
    exact = (
        12.706205, 4.302653, 3.182446, 2.776445, 2.570582,
        2.446912, 2.364624, 2.306004, 2.262157, 2.228139,
        2.200985, 2.178813, 2.160369, 2.144787, 2.131450,
        2.119905, 2.109816, 2.100922, 2.093024, 2.085963,
        2.079614, 2.073873, 2.068658, 2.063899, 2.059539,
        2.055529, 2.051831, 2.048407, 2.045230,
    )
    if 1 <= degrees_of_freedom <= len(exact):
        return exact[degrees_of_freedom - 1]
    # Cornish-Fisher expansion for larger samples.
    z = 1.959963984540054
    v = float(degrees_of_freedom)
    return (
        z
        + (z**3 + z) / (4.0 * v)
        + (5.0 * z**5 + 16.0 * z**3 + 3.0 * z) / (96.0 * v**2)
        + (3.0 * z**7 + 19.0 * z**5 + 17.0 * z**3 - 15.0 * z) / (384.0 * v**3)
        + (79.0 * z**9 + 776.0 * z**7 + 1482.0 * z**5 - 1920.0 * z**3 - 945.0 * z)
        / (92160.0 * v**4)
    )
