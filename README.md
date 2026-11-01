# SwarmShield

SwarmShield is a simulation-only coordination game and research prototype for studying UAV navigation, local sensing, peer information sharing, and spatial reconnaissance tasks. Its Python engine owns the deterministic fixed-tick world, task behavior, communication, mission outcomes, and metrics; Godot 4 provides the live top-down map, agent/task inspection, rendering filters, and validated player interventions. It does not connect to physical platforms or provide operational response-time guarantees.

For the original baseline and current gaps, see [Baseline and Gaps](docs/BASELINE_AND_GAPS.md). For game controls, missions, and model rules, see [Game Design](docs/GAME_DESIGN.md), the [Simulation Model](docs/SIMULATION_MODEL.md), and the [Mission and Task Model](docs/MISSION_AND_TASK_MODEL.md). Integration, research, and implementation details are in [Architecture](docs/ARCHITECTURE.md), [Protocol](docs/PROTOCOL.md), [Research Workflow](docs/RESEARCH_WORKFLOW.md), [Research Methodology and Metric Definitions](docs/RESEARCH_METHODOLOGY.md), and [Implementation Status](docs/GAME_IMPLEMENTATION_STATUS.md).

## Requirements

- Python 3.10 or newer for the standard-library simulation and tests.
- Godot 4.4 or newer for the interactive game; the bridge uses [non-blocking redirected process I/O](https://docs.godotengine.org/en/4.4/classes/class_os.html#class-os-method-execute-with-pipe). The engine and research workflows do not require Godot.
- Streamlit and Plotly only for the optional dashboard.
- Matplotlib only for research-result plots (install with `requirements-analysis.txt`).

The core engine has no third-party dependencies.

## Run one scenario

```bash
cd /home/usualguy/SwarmShield
python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative
```

Run an independent baseline or choose a scheduling policy:

```bash
python3 -m swarmshield.runner --config configs/baseline.json --mode independent
python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative --policy edf
```

Write the event log, including task lifecycle and per-step engine snapshots:

```bash
python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative --events output/events.csv
```

The command prints a JSON summary. Event CSV parent directories are created automatically.

## Play the Godot game

From the repository root, launch the project with Godot 4.4 or newer:

```bash
godot --path game
```

Choose a mission, cooperative or independent team policy, scheduler, and seed, then start the run. Each bundled mission assigns four survey sectors to four UAVs, which fly engine-planned routes beyond their starting sensor ranges. Pause, resume, reset, and tick rate control logical tick requests. The map has independent rendering-only toggles for UAVs, task/routes, terrain, local observations, shared reports, stale tracks, communication links, selected-UAV sensor range, entity labels, and the coordinate grid. Repeated agent reports of one entity appear as one map marker; selecting a UAV shows its own track view. Links default off and show only recent event-backed or pending routes. Click a quadcopter or choose an observer in the Agent tab to inspect it. Queue pressure and near deadlines use amber/red cues; mission objectives show engine values and explain unmet targets. **Apply scheduler** changes future scheduling order. To request a free UAV destination, select an idle UAV, enable **Set destination**, and click an empty map position. To reassign an active mission task, use the task and available-UAV selectors in the Mission tab. Python validates every command and records accepted and rejected interventions. In Results, switch between individual runs and matched comparisons. Scheduler comparisons hold team mode constant; sharing comparisons hold the scheduler constant, and both treatments run the actual mission tasks with every seed matched across treatments. Reports include per-seed differences and descriptive 95% t intervals; they do not claim statistical significance. Each treatment is saved as a normal run artifact; paired summaries live under `runs/comparisons/`. The game launches Python automatically; set `SWARMSHIELD_PYTHON` if the interpreter is not available as `python3` (or `python` on Windows).

Completed or explicitly ended game runs are saved beneath `runs/<run_id>/` with a manifest, scenario/configuration, event CSV, raw summary metrics, scoring result, and intervention log. Running Godot is not required to use the research workflows.

The local versioned adapter can also be launched without Godot for integration work:

```bash
python3 -u -m swarmshield.protocol
```

It reads one JSON command per standard-input line and writes one structured response per standard-output line. See [Protocol](docs/PROTOCOL.md).

## Run matched batch experiments

By default, the batch runner compares independent/cooperative modes and fixed-priority/EDF policies across ten consecutive seeds, starting at the seed in the config:

```bash
python3 experiments/run_batch.py --config configs/baseline.json --seeds 10
```

This writes `experiments/results/batch_summary.csv`. Narrow the comparison or retain per-run event logs with:

```bash
python3 experiments/run_batch.py \
  --config configs/baseline.json \
  --seeds 5 \
  --start-seed 100 \
  --modes cooperative \
  --policies fixed-priority edf \
  --events-dir experiments/results/events
```

Runs sharing a seed start from the same deterministic world, observation, and network random streams. Task generation uses its own seeded stream, but changes in the number or order of submitted tasks can shift later task draws across modes. Wall-clock runtime is measured separately and naturally varies between runs.

## Reproduce the verification experiments

The full 30-seed primary comparison, overload sweeps, communication sweeps, analysis tables, and plots are documented in [the experimental results report](experiments/results/SwarmShield_Experimental_Results.md). To regenerate the matrix and figures from the repository root:

```bash
python3 -m pip install -r requirements-analysis.txt
python3 experiments/run_research.py \
  --config configs/baseline.json \
  --output-dir experiments/results/my_run/matrix \
  --primary-seeds 30 \
  --sweep-seeds 10 \
  --start-seed 42
python3 experiments/analyze_research.py \
  --run-dir experiments/results/my_run/matrix
```

The output directory must not already exist. Each run record stores its effective configuration and summary; a representative event CSV is saved for each condition and sweep level.

To regenerate statistics and figures from an existing matrix, add `--overwrite` to the analysis command. This replaces only analyzer-generated files and preserves `runs.jsonl`, `runs.csv`, and `sample_events/`.

## Dashboard

Install the optional UI dependencies and launch the local dashboard:

```bash
python3 -m pip install -r requirements-dashboard.txt
streamlit run app.py
```

The dashboard runs the engine for the selected scenario and displays its per-step world/agent state, track reports, message/task event timeline, measured metrics, and a matched fixed-priority/EDF comparison. It can download the event CSV and run-summary JSON.

## Tests

Run the standard-library unit and integration suite:

```bash
python3 -m unittest discover -s tests -v
```

The suite covers configuration validation, deterministic and incremental runs, protocol parsing and lifecycle, seeded interventions, mission objectives and scoring, artifact output, stale/duplicate reports, network delivery and duplication, scheduling policies and deadlines, queue overload, capacity enforcement, event export, and batch CSV output.

Run the Godot map-rendering state checks with:

```bash
godot --headless --path game --script res://tests/test_world_view.gd
godot --headless --path game --script res://tests/test_mission_view.gd
godot --headless --path game --script res://tests/test_results_view.gd
godot --headless --path game --script res://tests/test_game_flow.gd
```

Map display toggles filter drawing only. The default map shows fresh local observations; shared and stale tracks remain available on demand. Communication links are hidden by default and, when enabled, collapse repeated events by agent pair, show only recent or pending backend records, and cap the visible routes.

The terrain texture and lightweight artwork are visual aids, while obstacle polygons, roads, restricted areas and sensor line-of-sight are provided by the Python world model. The sensor-range halo is only a range cue; actual detection also follows configured FOV, probability, and LOS. The optional coordinate grid and sensor-range overlay are hidden by default. Agent yaw is live presentation state supplied by Python and does not affect outcomes or archived trace snapshots.

## Model rules

- Each run records its seed and configuration. Independent RNG streams keep world movement, observations, network faults, and task workloads reproducible.
- Agents receive only range-limited synthetic observations and reports delivered by the simulated network. The world and evaluator own exact entity state.
- Decision tasks represent track reconciliation. Each has a synthetic priority, processing cost, deadline, and status. Larger priority values win under fixed-priority scheduling; EDF chooses the earliest deadline first. Processing cost is logical work per virtual step.
- The decision queue is bounded. New tasks are dropped on overload. Tasks that do not finish by their deadline expire; tasks with deadlines beyond the simulation horizon are reported as pending. Deadline-miss rate uses tasks whose deadlines fall within the run as its denominator.
- The coordination layer creates one generic review task the first time an entity is tracked. Centralized mode chooses an available resource with the least load. Decentralized mode creates deterministic per-agent proposals, counts conflicting proposals, and resolves them with a stable tie-break. Resource capacity is enforced.
- Spatial mission tasks are assigned centrally and routed by the autonomous Python behavior policy. They complete only from actual movement, observation evidence, or sensor-footprint coverage, not estimated duration alone.
- Decentralized assignment is an experimental proposal/reconciliation model inside one simulator. It does not implement a distributed consensus protocol or claim fault-tolerant deployment behavior.
- The optional network partition is a global outage between one-third and two-thirds of the run. Messages due during the outage are dropped.
- Dashboard snapshots include evaluator ground truth for visualization. That state is not passed to agent decision code.

## Metrics

The JSON summary and batch CSV report:

- awareness coverage, mean per-agent track coverage, track age, first-detection delay, and never-detected entity count;
- message sent, delivered, dropped, duplicate, pending, latency, and duplicate-rejection results;
- decision-task completion, deadline misses, latency percentiles, information age, backlog, and wall-clock runtime;
- abstract coordination-task completion, assignment conflicts per 100 task requests, assignment wait, maximum resource load, and capacity violations;
- recovery time after a configured partition, defined as the first step after restoration when every agent has the same non-empty set of fresh entity IDs. It is `null` when there is no partition or the criterion is not reached before the run ends.

These are software simulation findings under the selected synthetic assumptions. They are not measurements of real sensors, radios, defensive effectiveness, or hard real-time performance.

## Layout

```text
SwarmShield/
├── app.py
├── configs/
│   ├── baseline.json
│   ├── maps/
│   │   └── reconnaissance_training_range.json
│   └── missions/
│       ├── deadline_pressure.json
│       ├── network_recovery.json
│       └── shared_awareness.json
├── game/
│   ├── project.godot
│   ├── assets/
│   ├── scripts/
│   └── tests/
├── experiments/
│   ├── analyze_research.py
│   ├── run_batch.py
│   └── run_research.py
├── requirements-analysis.txt
├── requirements-dashboard.txt
├── swarmshield/
│   ├── agents.py
│   ├── behaviors.py
│   ├── comparisons.py
│   ├── config.py
│   ├── coordination.py
│   ├── geometry.py
│   ├── metrics.py
│   ├── missions.py
│   ├── navigation.py
│   ├── network.py
│   ├── observations.py
│   ├── protocol.py
│   ├── runner.py
│   ├── scheduler.py
│   ├── session.py
│   ├── tasking.py
│   ├── task_lifecycle.py
│   ├── tasks.py
│   ├── vehicles.py
│   └── world.py
└── tests/
```
