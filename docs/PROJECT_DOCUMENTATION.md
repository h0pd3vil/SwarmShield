# SwarmShield Project Documentation

Status: technical reference with a mix of current architecture and historical audit snapshots. For current verified feature status and test results, use [Game Implementation Status](GAME_IMPLEMENTATION_STATUS.md) and [Implementation Progress](IMPLEMENTATION_PROGRESS.md). Historical values and prototype-era statements later in this document are labeled below.

## 1. Project overview

SwarmShield is a simulation-only Python and Godot 4 application for examining multi-UAV navigation, sensing, information sharing, and spatial reconnaissance task coordination. Python owns fixed-tick world state, motion, geometry, observations, message delivery, task execution, objectives, and metrics; Godot presents that state and sends validated player commands.

The project currently includes:

- A standard-library simulation engine and command-line runner.
- Independent and cooperative information-sharing modes.
- Fixed-priority and earliest-deadline-first (EDF) decision scheduling.
- Separate abstract review tasks and spatial mission tasks with distinct lifecycles.
- JSON run summaries and detailed CSV event logs with per-step visualization snapshots.
- A matched-seed batch runner that writes a metrics CSV.
- A 30-seed research runner, one-factor overload/communication sweeps, and reproducible analysis plots.
- An optional Streamlit and Plotly dashboard.
- An incremental fixed-tick session used by both the headless runner and a versioned JSON-lines adapter.
- A Godot 4 real-time presentation with mission/task inspection, rendering-only map filters, validated scheduler/destination/task reassignment interventions, scoring, matched comparisons, and per-run artifacts.
- Unit and integration tests.

See [Game Implementation Status](GAME_IMPLEMENTATION_STATUS.md) for tested versus unverified game features and platform limitations.

Sections describing the original audit, baseline counts, and early mission prototype are historical snapshots; they do not override the current module status or verification record linked above.

This software does not connect to physical sensors, devices, or networks. It does not provide real-world accuracy, safety, operational response-time, or deployment guarantees. All model results depend on the synthetic assumptions and parameter values selected by the user.

## 2. Repository layout

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
    ├── docs/
    ├── game/
    │   ├── project.godot
    │   ├── assets/
    │   ├── scripts/
    │   └── tests/
    ├── experiments/
    │   ├── analyze_research.py
    │   ├── run_batch.py
    │   └── run_research.py
    ├── output/
    │   └── events.csv
    ├── requirements-dashboard.txt
    ├── requirements-analysis.txt
    ├── swarmshield/
    │   ├── __init__.py
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
        ├── test_agents.py
        ├── test_batch.py
        ├── test_behaviors.py
        ├── test_comparisons.py
        ├── test_config.py
        ├── test_coordination.py
        ├── test_geometry.py
        ├── test_metrics.py
        ├── test_mission_coordination.py
        ├── test_navigation.py
        ├── test_network.py
        ├── test_observations.py
        ├── test_realtime.py
        ├── test_runner.py
        ├── test_scheduler.py
        ├── test_task_lifecycle.py
        ├── test_tasks.py
        ├── test_vehicles.py
        └── test_world.py

The output/events.csv file is a generated baseline cooperative run log, not source code. Commands can overwrite it if that path is supplied as the event output.

## 3. Architecture and runtime flow

### Components

| Component | Responsibility |
|---|---|
| swarmshield/config.py | Immutable configuration model, JSON loading, validation, and stable seed derivation. |
| swarmshield/world.py | Synthetic 2D world, static geometry queries, entity motion, observer placement, and evaluator-only ground truth. |
| swarmshield/geometry.py | Validated polygon/POI data and deterministic point, segment, safe-area, and line-of-sight predicates. |
| swarmshield/observations.py | Range/FOV/LOS-limited detection and noisy position reports. |
| swarmshield/agents.py | Agent-local tracks, message-ID deduplication, stale-report rejection, and track freshness. |
| swarmshield/network.py | In-process message queue with range, bounded pending capacity, loss, latency, duplication, optional TTL expiry/retries, and partition behavior. |
| swarmshield/scheduler.py | Bounded global decision queue, task priority/deadlines/costs, and lifecycle events. |
| swarmshield/coordination.py | Separate bounded queue for generic review tasks and abstract resource assignment. |
| swarmshield/runner.py | Scenario lifecycle, interactions among components, metrics, JSON summary, and event CSV output. |
| swarmshield/metrics.py | Nearest-rank percentile calculation. |
| experiments/run_batch.py | Cross-product of modes and scheduler policies over consecutive seeds. |
| experiments/run_research.py | Saves matched primary conditions and one-factor overload/communication experiment records. |
| experiments/analyze_research.py | Computes aggregate/paired statistics and exports comparison plots. |
| app.py | Optional dashboard over output generated by the same simulation engine. |

### One simulation step

For each integer step from 1 through world.steps, the runner:

1. Expires decision tasks that are already past their deadline.
2. Advances the world by one step.
3. Advances commanded UAV routes once and replans blocked routes where possible.
4. Records network partition transitions, then generates local observations from each current UAV pose using range, field of view, and configured line of sight.
5. Delivers or expires network envelopes due at this tick. A delivered report callback can create a received-report decision task.
6. Lets the decision scheduler consume its configured logical work capacity. Completed tasks apply their report to the receiving agent's local track.
7. In cooperative mode, a completed local observation is published to reachable peers. Independent mode does not publish peer messages.
8. Advances abstract coordination tasks, runs the second network delivery pass, then records the recovery check and visualization snapshot.

The scheduler is run before the second network delivery pass. Therefore, a newly delivered zero-latency report can enter the queue during that pass but is not processed by the scheduler until its next run.

### Information sharing

The CLI's mode option selects one of two behaviors:

- independent: agents use their own local observations; no peer reports are sent.
- cooperative: once a local-observation task completes, the observation is published to all other agents. The sender may classify it as updated, unchanged, or stale; the publish still happens when the task completes.

A received message is checked against the recipient's set of message IDs before it is queued. Repeated copies with the same ID are rejected. When a report is applied, the agent accepts a newer observation time and ignores an older one. A same-time report with no higher confidence is unchanged. The current observation model gives reports a fixed default confidence of 1.0.

The world and evaluator own exact entity positions. Agent logic receives generated observations or messages only. The dashboard snapshots include ground truth for visualization and are not inputs to agent behavior.

Mission metadata contains validated spatial reconnaissance task definitions and each live game session owns a separate runtime record per task. A centralized baseline allocator assigns feasible work at run start using route/time, battery reserve, capability, prerequisite, and deadline checks. The Python session autonomously routes assigned UAVs and advances guarded, evidence-based task states; route, sensing, reports, deadlines, and resources are evaluated from engine state. Mission tasks remain distinct from scheduler processing tasks and abstract coordination review tasks; see [Mission and Task Model](MISSION_AND_TASK_MODEL.md).

## 4. Simulation model

### World

- The world is a rectangle from x=0 to world.width and y=0 to world.height.
- Mission configs may name a polygon map preset. Static geometry contains obstacles, roads, vegetation, safe/restricted/mission regions, and points of interest; polygons are validated as finite, in-bounds, unique-ID, non-self-intersecting shapes. Positive Y points down, matching Godot.
- `World.is_navigable`, `World.segment_is_navigable`, `World.has_line_of_sight`, and `World.is_in_safe_area` expose deterministic geometry checks. Destination-driven UAV motion consumes bounds and collision queries; configured sensing consumes line-of-sight checks when enabled.
- The protected zone is a circle centered in the world.
- Entities begin at seeded random positions with seeded x/y velocities between -1 and 1 world units per step.
- Entities move once per simulation step and reflect from world boundaries.
- UAVs start at configured observer positions. The autonomous mission behavior or a validated player command can assign a destination; UAVs then move once per logical tick under configured acceleration, speed, turn-rate, battery, bounds, and collision limits. Bundled spatial missions assign and execute tasks.
- The protected-zone count is an evaluator metric; it does not affect agent decisions or entity motion.

A step has no conversion to seconds. Entity velocity, message delay, scheduler deadlines, track age, and task duration are all expressed in simulated steps.

### Observations and tracks

For each entity, an observer checks Euclidean distance against `observation.range`, heading-relative `observation.field_of_view_degrees`, and (when enabled) line of sight through the configured world geometry. An eligible entity is detected with `observation.detection_probability`. If detected, independent Gaussian noise is added to x and y using `observation.position_noise_std` as the standard deviation, and the reported position is clipped to the world bounds. Reports keep a fixed confidence of 1.0; the model does not yet convert measurement noise into uncertainty.

A track is fresh when current_step minus observed_at is at most observation.max_track_age_steps. Old tracks remain stored in the agent but are excluded from active-track coverage. The simulation has no false-positive generator: observations always refer to an entity in the synthetic world.

### Network

The network is in-process and models each sender-recipient message separately:

- delivery_probability is the probability an original message passes the random loss check.
- max_latency_steps selects a random delay from 0 through that maximum, inclusive.
- duplicate_probability is checked for each message that passed the loss check. A duplicate copy uses the same message ID and delivery step.
- communication_range optionally drops sends whose current UAV positions exceed the configured Euclidean distance.
- message_queue_capacity bounds pending original and duplicate envelopes together.
- message_ttl_steps optionally expires an envelope after its inclusive validity tick; max_message_retries retries only immediate random loss at publication.
- When partition_enabled is true, a global outage runs from approximately one-third to two-thirds of the configured horizon. Messages sent during it are dropped; messages due during it are also dropped.
- Network messages still pending at the simulation horizon are recorded as pending, not as delivered.

This model is not a radio or socket network. Range uses distance only, with no obstacle attenuation, routing, acknowledgement, or retries after queue, range, or partition drops.

## 5. Decision scheduler

The decision scheduler is a single global logical work queue for local observations and received reports. It does not model processor time or make wall-clock guarantees.

When a decision task is created, the scheduler draws:

- A processing cost from 1 through scheduler.max_processing_cost.
- A priority from 1 through scheduler.max_priority.
- A deadline offset from scheduler.min_deadline_steps through scheduler.max_deadline_steps, inclusive.

A task's deadline is its creation step plus that offset. A task can complete on its deadline step; it expires after the deadline has passed. If the simulation horizon ends before a future deadline, the task is marked pending at horizon. Tasks are recorded for metrics and event logging throughout the run.

Policies:

- fixed-priority sorts by higher numeric priority first, then earlier deadline, earlier creation, and task ID.
- edf sorts by earlier deadline first, then higher priority, earlier creation, and task ID.

processing_capacity_per_step is logical processing cost units available each step. It is not a count of tasks and not a real-time/CPU budget. queue_capacity limits the number of simultaneously active queued/running decision tasks. If full, a new task is recorded as dropped. Increasing queue capacity creates room for more backlog but does not increase service throughput.

The scheduler's deadline-miss rate denominator includes tasks whose deadline is within the simulation horizon. Dropped or expired eligible tasks count as misses.

## 6. Abstract task coordination

The coordination manager is separate from the decision scheduler. On the first successful track update for an entity, it creates one generic abstract-review task for that entity. Later updates to the same entity do not create additional review tasks.

Each virtual agent is also treated as an abstract resource:

- centralized assigns work to an available resource with the least current load, using resource ID for ties.
- decentralized computes deterministic per-resource proposals, counts cases with multiple proposals as conflicts, and resolves them with a stable resource-ID tie-break.
- task_capacity_per_resource limits simultaneous assigned reviews per resource.
- task_duration_steps is the number of steps from assignment to completion.
- task_deadline_steps is added to the review task's creation step.
- coordination.queue_capacity bounds queued review work; work that cannot be assigned can wait until assignment or expiration.

The decentralized implementation is a deterministic proposal/reconciliation simulation. It does not implement networked consensus or independent peer failures.

## 7. Configuration reference

The baseline values below are read from configs/baseline.json. Basic configuration validation runs when a JSON file is loaded.

### Top-level and world

| JSON path | Baseline | Meaning |
|---|---:|---|
| seed | 42 | Master seed for repeatable random streams. |
| world.width | 100 | World width in arbitrary coordinate units. |
| world.height | 100 | World height in arbitrary coordinate units. |
| world.steps | 100 | Number of simulation steps. Must be greater than zero. |

### Scenario

| JSON path | Baseline | Meaning |
|---|---:|---|
| scenario.observer_count | 4 | Number of UAV agents/resources. They stay at their initial positions until Python assigns destinations. Must be greater than zero. |
| scenario.entity_count | 12 | Number of synthetic moving entities. Must be greater than zero. |
| scenario.protected_zone_radius | 10 | Radius of the centered evaluator/visualization zone. Cannot be negative. |

### Observation

| JSON path | Baseline | Meaning |
|---|---:|---|
| observation.range | 25 | Maximum Euclidean observation distance. Cannot be negative. |
| observation.detection_probability | 0.8 | Per-step probability of detecting an in-range entity; valid range is 0 to 1. |
| observation.position_noise_std | 1.0 | Gaussian coordinate noise standard deviation; cannot be negative. |
| observation.field_of_view_degrees | 360 | Heading-relative sensor field of view; must be greater than 0 and at most 360 degrees. |
| observation.require_line_of_sight | true | When true, configured obstacles and marked vegetation block observations. |
| observation.max_track_age_steps | 10 | Maximum age for a track to count as fresh; cannot be negative. |

### Network

| JSON path | Baseline | Meaning |
|---|---:|---|
| network.delivery_probability | 0.9 | Per-original-message delivery probability; valid range is 0 to 1. |
| network.max_latency_steps | 4 | Maximum random message delay, inclusive; cannot be negative. |
| network.duplicate_probability | 0.02 | Chance to schedule one duplicate copy after an original passes the loss check; valid range is 0 to 1. |
| network.partition_enabled | false | Enables or disables the global one-third-to-two-thirds outage. |
| network.communication_range | null | Optional positive Euclidean range between current UAV positions; null disables distance filtering. |
| network.message_queue_capacity | 10000 | Maximum pending originals and duplicate envelopes together. |
| network.message_ttl_steps | null | Optional inclusive validity duration; expired envelopes do not reach the receive callback. |
| network.max_message_retries | 0 | Immediate retries after random loss only; queue, range, and partition drops are not retried. |

### Decision scheduler

| JSON path | Baseline | Meaning |
|---|---:|---|
| scheduler.policy | fixed-priority | fixed-priority or edf. |
| scheduler.processing_capacity_per_step | 48 | Logical cost units available per step; must be positive. |
| scheduler.queue_capacity | 500 | Maximum active decision tasks; must be positive. |
| scheduler.min_deadline_steps | 4 | Minimum random task deadline offset; cannot be negative. |
| scheduler.max_deadline_steps | 12 | Maximum random task deadline offset; must be at least the minimum. |
| scheduler.max_processing_cost | 3 | Upper bound for random task cost; must be positive. |
| scheduler.max_priority | 3 | Upper bound for random task priority; must be positive. |

### Coordination

| JSON path | Baseline | Meaning |
|---|---:|---|
| coordination.mode | centralized | centralized or decentralized abstract assignment mode. |
| coordination.task_capacity_per_resource | 2 | Simultaneous assigned reviews allowed per virtual resource; must be positive. |
| coordination.task_duration_steps | 3 | Abstract review processing duration; must be positive. |
| coordination.task_deadline_steps | 12 | Deadline offset from review creation; cannot be negative. |
| coordination.queue_capacity | 100 | Maximum queued review tasks; must be positive. |

The config parser converts values to declared Python types and validates the supported probability ranges, policy names, coordination mode, positive capacities/durations, and related basic bounds. It does not model physical units or validate whether a combination of settings can meet a real-world requirement.

## 8. Command-line interface

Run the default cooperative scenario:

    cd /home/usualguy/SwarmShield
    python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative

Run without information sharing:

    python3 -m swarmshield.runner --config configs/baseline.json --mode independent

Override the scheduler policy for one run:

    python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative --policy edf

Save the event log:

    python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative --events output/events.csv

Runner options:

| Option | Required | Meaning |
|---|---|---|
| --config PATH | Yes | JSON scenario configuration. |
| --mode independent or cooperative | No | Sharing mode; defaults to cooperative. |
| --policy fixed-priority or edf | No | Overrides scheduler.policy for this run. |
| --events PATH | No | Writes event CSV and creates parent directories if needed. |

The runner prints a JSON summary containing project/mode/policy/seed/steps, effective configuration, and metrics. Invalid configuration or unsupported mode/policy exits with an error.

## 9. Matched batch experiments

The batch tool crosses selected sharing modes and scheduler policies over consecutive seeds. Its default is ten seeds, both modes, and both policies, which produces 40 runs. Runs sharing a seed start from the same deterministic world, observation, and network random streams. The scheduler workload has a separate seeded stream, but changes in the number or order of submitted tasks can shift later task draws across modes. Runtime naturally varies.

Default command:

    python3 experiments/run_batch.py --config configs/baseline.json --seeds 10

This writes experiments/results/batch_summary.csv. A narrower comparison with per-run event logs:

    python3 experiments/run_batch.py \
      --config configs/baseline.json \
      --seeds 5 \
      --start-seed 100 \
      --modes cooperative \
      --policies fixed-priority edf \
      --events-dir experiments/results/events

Important options:

| Option | Default | Meaning |
|---|---|---|
| --config | configs/baseline.json | Base scenario configuration. |
| --seeds | 10 | Number of consecutive seeds; must be positive. |
| --start-seed | Config seed | First seed in the range. |
| --modes | independent cooperative | One or both sharing modes. |
| --policies | fixed-priority edf | One or both scheduler policies. |
| --output | experiments/results/batch_summary.csv | Output summary CSV path. |
| --events-dir | None | Optional output directory for a CSV event file per run. |

Each row includes seed, mode, policy, steps, serialized effective config, and every metric from the runner. The batch tool is sequential and intended for repeatable comparisons, not distributed load generation.

### Expanded research experiment runner

The research runner performs a matched four-condition primary matrix and controlled one-factor overload and communication sweeps. It records an effective configuration and full summary for every run in `runs.jsonl` and `runs.csv`, and saves representative event logs under `sample_events/`. The analysis script produces run-group statistics, paired-seed differences, and PNG/SVG plots. Install the optional plotting dependency with `python3 -m pip install -r requirements-analysis.txt`.

    python3 experiments/run_research.py \
      --config configs/baseline.json \
      --output-dir experiments/results/my_run/matrix \
      --primary-seeds 30 \
      --sweep-seeds 10 \
      --start-seed 42
    python3 experiments/analyze_research.py \
      --run-dir experiments/results/my_run/matrix

The output directory must be new. The completed run and its findings are in [the experimental results report](../experiments/results/SwarmShield_Experimental_Results.md). The matrix pairs runs by seed; it does not guarantee identical task-level random values across information-sharing modes because those modes can submit different task counts.

To regenerate analysis files in the same matrix directory, add `--overwrite` to the analysis command. It replaces only the analyzer's statistics and known plot files; raw run records and sample event logs are kept.

## 10. Dashboard

The UI is an optional Streamlit application using Plotly. Core simulation and tests do not require these packages.

Install dashboard dependencies and start it from the project root:

    python3 -m pip install -r requirements-dashboard.txt
    streamlit run app.py

The dashboard controls:

- Information sharing: independent or cooperative.
- Decision scheduler: fixed-priority or EDF.
- Task coordination: centralized or decentralized.
- Random seed.
- Number of simulation steps, from 1 through 5000.
- Run selected scenario or compare both scheduler policies.

Other scenario parameters are loaded from configs/baseline.json and are not individually editable in the current UI. The page displays a selectable world snapshot, synthetic entities, virtual observers, fresh agent tracks, event counts over time, selected metrics, recent events, and expandable full metrics. It can download the current event CSV and summary JSON.

requirements-dashboard.txt lists Streamlit and Plotly. These are optional UI dependencies; they are not simulation input parameters.

## 11. Output formats

### JSON summary

The summary identifies the project, sharing mode, selected scheduler policy, seed, horizon, effective configuration, and the metrics listed below. wall_clock_runtime_seconds measures local elapsed runtime for one invocation; it is not simulated time and varies by machine and system load.

### Event CSV

The runner writes the following columns:

| Column | Meaning |
|---|---|
| step | Simulation step associated with the event. |
| event_type | Event name, such as observation_created, message_delivered, task_expired, or simulation_snapshot. |
| message_id | Network message identity when applicable. |
| sender_id / recipient_id | Agent IDs for messages or observations when applicable. |
| entity_id | Synthetic entity identity associated with the event. |
| details | Event outcome or, for snapshots, compact JSON state. |
| copy_index | 0 for original messages; 1 for a scheduled duplicate. |
| task_id / task_type | Decision or abstract coordination task identity/type. |
| deadline | Task deadline in simulation steps. |
| priority | Decision-task priority. |
| processing_cost / remaining_cost | Logical work cost and remaining work. |
| information_time | Step at which the underlying observation was made. |
| resource_id | Abstract resource assigned to a coordination task. |

Common event types include:

- observation_created.
- message_sent, message_delivered, message_dropped, message_expired, message_retry_attempted, message_pending.
- duplicate_scheduled, duplicate_delivered.
- task_created, task_started, task_completed, task_expired, task_dropped, task_pending, decision_applied.
- coordination_task_created, coordination_task_assigned, coordination_task_started, coordination_task_completed, coordination_task_expired, coordination_task_dropped, assignment_conflict, capacity_violation.
- simulation_snapshot.

Event rows are ordered by step. The implementation groups event sources before a stable step sort, so row order among events in the same step should not be treated as a precise causal trace.

A simulation_snapshot row stores JSON in details. It includes evaluator entity positions, protected-zone geometry, observer positions, and all stored agent tracks. Snapshot ground truth is provided for visualization/evaluation only.

## 12. Metrics reference

Metrics are synthetic simulator outputs, not measures of field accuracy.

### Awareness and detection

| Metric | Definition |
|---|---|
| any_agent_awareness_coverage | Fraction of ground-truth entities present in at least one agent's fresh final track set. |
| mean_agent_track_coverage | Mean across agents of each agent's fresh final tracks divided by entity count. |
| mean_track_age_steps | Mean final-horizon age of all fresh final tracks, calculated as horizon minus observation step. |
| mean_first_detection_delay_steps | Mean first observation-created step over entities detected at least once. Entities are present from the beginning, so this is effectively their first-detection step; it counts generated observations even if their decision task is later dropped or expires. |
| entities_never_detected | Number of entities with no observation event during the run. |
| entities_in_protected_zone | Ground-truth entities inside the centered zone at the end of the run. |

### Network

| Metric | Definition |
|---|---|
| messages_sent | Number of original sender-recipient messages. |
| messages_delivered | Number of delivered original messages. |
| messages_dropped | Number of dropped original messages, including random loss and partition drops. |
| message_delivery_ratio | Delivered originals divided by originals sent. Pending messages remain in the denominator. |
| mean_message_latency_steps | Mean simulated delivery step minus send step for delivered originals. |
| duplicate_copies_scheduled | Duplicate copies created after an original passes the loss check. |
| duplicate_copies_delivered | Duplicate copies delivered to a recipient. |
| duplicates_rejected | Delivered duplicate copies rejected because the message ID was already reserved. |
| duplicate_rejection_rate | Rejected duplicates divided by delivered duplicate copies. Dropped and pending copies are not in this denominator. |
| dropped_duplicate_copies | Duplicate copies dropped during a partition. |
| pending_messages | Total originals and duplicate copies still in the network queue at the horizon. |
| pending_original_messages / pending_duplicate_copies | Pending queue counts split by copy type. |

### Decision scheduler

| Metric | Definition |
|---|---|
| decision_tasks_created | All submitted decision tasks, including tasks subsequently dropped for overload. |
| decision_tasks_completed | Tasks whose logical processing finished. |
| decision_tasks_expired | Tasks whose deadlines passed before completion, including eligible pending tasks at the horizon. |
| decision_tasks_dropped_overload | Tasks rejected because the active queue was full. |
| decision_tasks_pending | Tasks whose deadlines are later than the simulation horizon. |
| eligible_tasks | Tasks whose deadlines fall on or before the horizon. |
| deadline_miss_rate | Eligible tasks that expired or were dropped divided by eligible task count. |
| task_completion_rate | Completed tasks divided by all created tasks, including tasks still pending beyond the horizon. |
| decision_latency_p50_steps / p95_steps / p99_steps | Nearest-rank percentiles of completed-task latency, where latency is completion step minus creation step. |
| decision_latency_sample_count | Number of completed tasks used for latency percentiles. |
| mean_information_age_at_decision_steps | Mean completion step minus source observation step for completed tasks. |
| mean_queue_backlog_tasks | Mean active queue size sampled after scheduler processing on each simulation step. |
| max_queue_backlog_tasks | Maximum active queue size observed. |

### Abstract coordination and recovery

| Metric | Definition |
|---|---|
| coordination_tasks_created / completed / expired / dropped / pending | Counts by abstract review-task lifecycle state. Pending includes queued and assigned reviews at the horizon. |
| coordination_task_completion_rate | Completed review tasks divided by created review tasks. |
| assignment_conflicts | Decentralized tasks for which multiple distinct resource proposals were recorded. |
| assignment_conflict_rate_per_100_tasks | 100 times conflicts divided by created coordination tasks. |
| mean_assignment_wait_steps | Mean assignment step minus creation step for tasks that were assigned. |
| max_resource_load | Maximum number of simultaneously assigned review tasks held by one resource. |
| capacity_violations | Number of detected steps/resources above configured coordination capacity. Expected to remain zero under current manager logic. |
| recovery_time_steps | First step after the simulated partition restoration when every agent has the same non-empty set of fresh entity IDs, minus restoration step. Null when partitions are disabled or recovery is not reached. |

The first-detection metric is a step number averaged over detected entities, not a calibrated sensor detection delay. Coverage measures awareness only for known synthetic entity IDs and does not test classification or false-positive accuracy.

## 13. Historical baseline validation snapshot

The checks and sample results in this section record an earlier repository audit. They are retained for provenance and are not the current regression gate; current results are in [Game Implementation Status](GAME_IMPLEMENTATION_STATUS.md) and [Implementation Progress](IMPLEMENTATION_PROGRESS.md).

The master seed is separated into stable named random streams for world movement, observations, network faults, and scheduler workload. This keeps one subsystem's random draws from shifting another subsystem's sequence. Coordination proposals use deterministic hashes.

Recorded checks for the current implementation:

- Unit/integration suite at the time of that audit: 24 tests passed.
- Python compile check: compileall completed without errors.
- Cooperative baseline: completed for seed 42 and 100 steps.
- Current output/events.csv: 12,461 event rows, 100 snapshots, expected headers, consistent message/task terminal accounting; byte-for-byte equal to a freshly generated baseline event log.
- Dashboard smoke check: Streamlit health endpoint returned HTTP 200 and Streamlit AppTest reported zero script exceptions in an isolated temporary environment.
- Stress sweep: nine runs across three scenarios and seeds 42, 43, and 44 completed without exceptions or coordination capacity violations.

### Baseline sample results

The seed-42 cooperative baseline reported:

| Result | Value |
|---|---:|
| Any-agent awareness coverage | 66.7% |
| Mean agent track coverage | 66.7% |
| Entities never detected | 1 of 12 |
| Original messages sent / delivered / dropped | 1,713 / 1,496 / 184 |
| Message delivery ratio | 87.3% |
| Decision tasks completed / created | 2,066 / 2,067 |
| Decision deadline-miss rate | 0% |
| Coordination reviews completed / created | 11 / 11 |
| Coordination capacity violations | 0 |
| Event CSV rows | 12,461 |

Wall-clock runtime varies and is intentionally not treated as a simulation metric.

### Recorded stress sweep

These were manual stress configurations constructed from the baseline with parameter overrides, not a named built-in stress-test command. Timing is from the execution environment at the time of the run and should not be compared as a hardware-independent benchmark.

| Scenario | Workload/configuration | Observed results across three seeds |
|---|---|---|
| Scale with decentralized assignment | Cooperative mode; 12 observers, 48 entities, 250 steps; range 12; detection 0.95; delivery 0.95; latency up to 10; duplication 0.10; decision capacity 64; queue 10,000; decentralized review capacity 2/resource, duration 3, deadline 12, queue 250. | Each run completed in about 1.03–1.07 seconds and produced 106k–109k events. Delivery ratio 92.6–93.0%; awareness 22.9–33.3%; deadline misses 71.3–72.6%; no overload drops or capacity violations. |
| Deliberate queue overload | Cooperative mode; 8 observers, 40 entities, 120 steps; detection 1.0; delivery 0.55; latency up to 12; duplication 0.20; decision capacity 8; decision queue 64; decentralized coordination capacity 1, duration 8, deadline 2, queue 8. | Each run completed in about 0.07–0.08 seconds. Decision queue reached 64; 3,866–4,054 tasks dropped and 2,856–2,890 expired; deadline misses 97.1–97.3%. Coordination reviews expired under the deliberately tight deadline. |
| Partition and lossy network | Cooperative mode; 4 observers, 12 entities, 150 steps; delivery 0.70; latency up to 8; duplication 0.10; partition enabled. | Each run completed in about 0.03–0.04 seconds. Delivery ratio 43.9–47.8%; recovery was measured 14–21 steps after restoration; no capacity violations. |

These stress results show that the program handles the tested event volumes without crashing. They also show that low processing capacity and tight deadlines cause substantial queue loss and missed deadlines. Raising queue capacity alone does not resolve insufficient processing throughput.

## 14. Known limitations and interpretation

- Entities, motion, observations, uncertainty, networking, task costs, and deadlines are synthetic and not empirically calibrated.
- Mission-backed runs autonomously route UAVs over deterministic obstacle-aware paths; the live player commands can also set destinations for eligible free UAVs. The network remains a single in-process simulator rather than a distributed or spatial radio network.
- There is no false-positive sensing model, sensor fusion estimator, entity classification, adversary model, or physical actuator.
- Position noise is a basic independent Gaussian perturbation. There is no sensor bias, correlated error, variable confidence estimate, or environmental attenuation model. Configured map polygons can block line of sight.
- Decision tasks use randomized logical costs. This is useful for comparing scheduling policies under matched seeds, but it is not a processor benchmark.
- Decentralized coordination is proposal generation and deterministic reconciliation in one process. It does not simulate networked consensus, concurrency races, or peer failure.
- Snapshots expose evaluator ground truth for display. Agent decision functions do not receive that ground truth.
- Batch experiment conclusions are conditional on the selected parameters and seeds. Use multiple seeds and report distributions for serious comparisons.
- A successful test suite or a high coverage metric does not establish real-world accuracy or reliability.

## 15. Troubleshooting and common adjustments

- If the dashboard says dependencies are missing, install requirements-dashboard.txt in the Python environment used to launch Streamlit.
- If the decision queue fills, inspect decision_tasks_dropped_overload, max_queue_backlog_tasks, and deadline_miss_rate. Increase processing_capacity_per_step to raise logical throughput; increase queue_capacity only if more waiting work is intentionally allowed.
- If work expires, compare task arrival volume, processing costs, and deadline ranges. Increasing max_deadline_steps gives the scheduler more simulated time, but changes the experiment assumptions.
- If cooperative awareness is low, inspect local detection settings, message delivery/latency, and scheduler load. Reports are shared only after their local decision tasks complete.
- If output/events.csv is replaced, rerun the desired scenario with the --events option to recreate it.

For quick CLI help:

    python3 -m swarmshield.runner --help
    python3 experiments/run_batch.py --help
    python3 experiments/run_research.py --help
    python3 experiments/analyze_research.py --help

## 16. Test suite

Run the standard-library suite from the project root:

    python3 -m unittest discover -s tests -v

Coverage by test module:

| Test module | Main checks |
|---|---|
| test_config.py | Nested config parsing, invalid probabilities/policies, invalid section shapes, geometry/vehicle config validation. |
| test_agents.py | Duplicate message rejection, stale-report handling, track freshness. |
| test_network.py | Message version/provenance, range, queue capacity, TTL expiry, retries, loss, latency, and duplicate behavior. |
| test_scheduler.py | Policy order, deadline expiration, queue overload, horizon-pending tasks. |
| test_coordination.py | Capacity enforcement, decentralized conflicts, one review request per entity. |
| test_metrics.py | Nearest-rank percentiles and empty/invalid inputs. |
| test_runner.py | Deterministic output, independent mode, coordinator selection, CSV export. |
| test_batch.py | Matched runs and batch CSV row count. |
| test_geometry.py | Bounds, obstacle/restricted-area collision, safe-area containment, and line-of-sight queries. |
| test_world.py | World heading, geometry presentation state, and observer placement. |
| test_vehicles.py | UAV kinematic limits, boundary/collision stops, energy budget, and reproducible motion. |
| test_navigation.py | A* path planning, waypoint following, obstacle detours, unreachable destinations, blocked-route replanning. |
| test_observations.py | FOV, LOS occlusion, seeded noise, detection probability, track deduplication, and live UAV heading. |
| test_realtime.py | Incremental session lifecycle, protocol commands, network/queue state, presentation feed, and baseline artifact equality. |
| test_tasks.py | Mission task definitions, spatial validation, centralized assignment, capability/deadline/energy checks. |
| test_task_lifecycle.py | State machine transitions, evidence rules, deadlines, cancellation, and reassignment. |
| test_behaviors.py | Autonomous routing, route deduplication, safe-area recovery, and unavailable-owner reassignment. |
| test_mission_coordination.py | End-to-end multi-UAV task completion, deterministic replay, and outage-delayed reassignment. |
| test_comparisons.py | Matched-seed scheduler and sharing comparisons, treatment isolation, and paired-report output. |

## 17. Project dependencies

- Python 3.10 or newer is the documented minimum for the core engine and tests.
- The simulation and test suite use the Python standard library only.
- The dashboard's optional packages are listed in requirements-dashboard.txt: Streamlit and Plotly.
- The research plotting script uses optional Matplotlib, listed in requirements-analysis.txt.
- No database, cloud service, remote API, or external simulator is required.

