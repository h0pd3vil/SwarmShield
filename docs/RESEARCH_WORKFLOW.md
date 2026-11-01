# Research Workflow

## Headless engine and matched experiments

Godot is not needed for simulation or research. Use the existing CLI and matched-seed batch workflow:

```bash
python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative --policy edf --events output/events.csv
python3 experiments/run_batch.py --config configs/baseline.json --seeds 10 --start-seed 42 --modes independent cooperative --policies fixed-priority edf
```

For the larger design, see the existing `experiments/run_research.py` and `experiments/analyze_research.py` documentation in the README and experiment report. Matched seeds initialize stable independent random streams; task work has its own seeded stream. Policy changes/interventions are part of the treatment sequence and must be held constant or recorded for comparisons.

Mission configurations are editable JSON files in `configs/missions/`. They contain the normal engine configuration plus a `_mission` object with name, objectives, provisional scoring weights, and labels. Python validates the engine sections when a run starts.

## Completed game-run artifacts

Every completed mission and every explicitly ended active mission creates `runs/<run_id>/`:

| File | Schema / contents |
|---|---|
| `manifest.json` | Schema version 1, run/scenario ID, seed, engine/protocol versions, UTC start/end, configured/actual ticks, Python version, config SHA-256, and source revision availability. |
| `scenario.json` | Schema version implicit in manifest; mission definition and effective engine configuration. |
| `events.csv` | Stable event columns matching the headless runner: tick, event type, message/sender/recipient/entity, details, task lifecycle values, and resource. |
| `summary.json` | Raw engine metrics under `metrics`, effective configuration, interventions, plus game objective outcome and score under `game_result`. |
| `interventions.json` | Schema version 1 and ordered accepted/rejected intervention records. |

The workspace currently has no Git metadata, so manifests use a null `source_revision` and explain why. The SHA-256 is over sorted compact JSON for the effective configuration; scenario metadata and intervention history are stored alongside it. No run artifact changes raw engine metrics to improve the game score.

Runs can be parsed using Python's `json` module and CSV reader. Compare the `metrics` objects for research outcomes; use `game_result` only for the provisional gameplay scoring layer. Run IDs and timestamps identify artifacts, but are not simulation inputs.

## In-game matched comparisons

The Results tab can run a small matched experiment for the selected mission and displayed seed range. Each treatment now constructs the mission's actual spatial task definitions, assigns them, dispatches the autonomous Python behavior, and records their movement, sensing, communication, and task outcomes. Scheduler comparisons hold team mode constant and compare fixed-priority with EDF. Sharing comparisons hold the scheduler constant and compare independent with cooperative runs. Each treatment pair receives the same seed; there are 2–30 seeds per request.

Each treatment is saved as a normal `runs/<run_id>/` artifact with a comparison ID and treatment metadata in its manifest. The paired report is saved as `runs/comparisons/<comparison_id>.json` and includes the held-constant factors, treatment run IDs, raw metric values, per-seed right-minus-left differences, descriptive means/medians/ranges, paired standard deviation/error, a two-sided 95% Student-t interval for each mean difference, and the selected seed set. It includes both legacy scheduler/network metrics and mission-task/area/resource metrics. Unavailable metric pairs are omitted from that metric's aggregate. The interval is descriptive, not a significance test; small seed counts and non-normal/bounded outcomes limit inference. Use the larger `experiments/run_research.py` workflow and its analysis for broader evaluation.

`experiments/run_research.py` remains a configuration-driven headless design over the baseline engine configuration. It compares independent/cooperative and fixed-priority/EDF conditions, sweeps processing/workload settings, and sweeps message delivery, latency, duplication, and partition settings. Its `run_plan.json`, `runs.jsonl`, sample event CSVs, and aggregate reports retain seed and effective-configuration provenance. Those broad stress sweeps do not instantiate the spatial mission-task behavior; use the mission-backed matched comparison for that treatment.

## Replay and reproducibility

Record engine revision (when available), scenario/config, seed, sharing mode, initial scheduling policy, and ordered intervention records. The deterministic contract is conditional on the same engine revision/configuration/seed/intervention sequence. `SimulationSession.advance_tick()` is the same engine path used by the batch CLI. Tests compare incremental and whole-run output and replay an intervention sequence. Wall-clock runtime and artifact timestamps are intentionally not deterministic metrics.
