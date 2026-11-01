# SwarmShield Initial Baseline and Capability Gaps

> Historical audit recorded before Modules 1–27. The capability gaps below describe the initial workspace, not the current implementation. For present-day verified capabilities and limitations, see [Game Implementation Status](GAME_IMPLEMENTATION_STATUS.md), [Implementation Progress](IMPLEMENTATION_PROGRESS.md), and [Simulation Model](SIMULATION_MODEL.md).

## Audit scope

Audit performed against the current workspace before adding movement or geometry behavior. The repository contains a standard-library Python engine, a JSON-lines adapter, a Godot 4 presentation, an optional Streamlit dashboard, mission JSON, CLI/batch/research tools, tests, and saved experiment output. The workspace has no Git metadata, so a source commit cannot be recorded in run manifests.

Primary references: [README](../README.md), [Architecture](ARCHITECTURE.md), [Protocol](PROTOCOL.md), [Project Documentation](PROJECT_DOCUMENTATION.md), [Game Design](GAME_DESIGN.md), [Research Workflow](RESEARCH_WORKFLOW.md), and [Coordination and Communication Architecture](COORDINATION_AND_COMMUNICATION_ARCHITECTURE.md).

## Verified baseline

| Check | Command | Observed result |
|---|---|---|
| Python unit/integration tests | `python3 -m unittest discover -s tests -v` | **45 tests passed**. Coverage includes deterministic/incremental sessions, protocol lifecycle, missions/scoring, artifacts, agent tracks, network, scheduler, abstract coordination, batch and matched comparisons. |
| Python compilation | `python3 -m compileall -q swarmshield app.py experiments tests game/python_bridge.py` | Exit code 0; no syntax errors. |
| Godot project import | `godot --headless --editor --path ./game --quit` | Godot 4.7.2 completed the initial filesystem scan and editor startup with exit code 0. |
| Godot map-state test | `godot --headless --path ./game --script res://tests/test_world_view.gd` | `WorldView tests passed`. |
| CLI simulation | `python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative --events /tmp/swarmshield-phase0-baseline-events.csv` | Completed seed 42 for 100 logical ticks and emitted a JSON summary plus a valid event CSV with **12,461 event records** and 100 per-tick snapshots. |

Representative seed-42 baseline metrics from that CLI run: team fresh-track coverage `0.6667`; mean per-agent coverage `0.6667`; 1,713 original messages sent, 1,496 callback deliveries, 184 drops, and 35 message envelopes pending at the horizon; 2,066 of 2,067 decision tasks completed; deadline miss rate `0.0`; abstract coordination tasks `11/11` completed; no queue-overload task drops. The wall-clock runtime is intentionally excluded because it varies by machine/run.

The generated baseline CSV was written to `/tmp/swarmshield-phase0-baseline-events.csv`; it is verification output, not a committed artifact. The repository also contains earlier research outputs under `experiments/results/verification_20261025_0915/`.

## Authoritative engine and interfaces

- `swarmshield.session.SimulationSession` owns state and advances one fixed logical tick in `advance_tick()`.
- `swarmshield.runner.run_simulation()` repeatedly invokes that session; CLI and batch work therefore use the same engine as the interactive adapter.
- `swarmshield.protocol` exposes a synchronous, version-1 JSON-lines interface. Godot's `PythonBridge` sends requests and displays returned snapshots/events; it does not advance simulation independently.
- `game/scripts/world_view.gd` renders backend positions, tracks and communication events, plus static local art constants. UI display toggles filter drawing only.
- `app.py` is an optional analysis dashboard. It calls the same `run_simulation()` engine, but its visualization is a separate Plotly view.
- `experiments/run_batch.py` and `experiments/run_research.py` run headless matched-seed configurations and write machine-readable output.

## Existing and verified capabilities

1. Fixed logical ticks, deterministic named RNG streams, reproducible CLI runs, and incremental/full-run consistency.
2. Bounded rectangular world, fixed observer positions, heading presentation state, moving synthetic entities with boundary reflection, protected reference zone.
3. Probabilistic range-limited observations with Gaussian position noise and clamping.
4. Agent-local latest-track storage, observation timestamps/provenance, stale timestamp rejection, freshness cutoff, message-ID deduplication.
5. Cooperative peer report publication or independent local-only mode; in-process delivery probability, sampled integer latency, optional duplicate copy, and a deterministic global outage interval.
6. One bounded global logical-work queue with fixed-priority/EDF policies, synthetic processing costs, priorities, deadlines, overload drops, expiration, and pending-at-horizon accounting.
7. One abstract review assignment per first-updated entity, centralized load balancing, and deterministic proposal/conflict accounting under the `decentralized` option.
8. Engine-derived final metrics, mission objective checks, provisional weighted score, event CSV, run artifacts, supported scheduler-policy intervention logging, and matched-seed comparisons.
9. Godot selection/inspection, SVG quadcopter/contact sprites, illustrative terrain and obstacle assets, optional observation/shared/stale/communication layers, bounded recent communication routes, mission/results panels, and fixed-tick controls.

## Existing capabilities that need improvement

- Agents are stationary observers. The heading value only affects sprite orientation; movement, turning, speed, acceleration, battery, navigation state, and flight constraints do not exist.
- World geometry is only width/height and a protected circle. Godot hard-codes static terrain landmarks; those positions are not supplied by Python or scenario config.
- Synthetic entities move, but there are no mission POIs/regions, patrol areas, safe routes, restricted polygons, or obstacle collision queries.
- Sensing has no field of view or obstacle occlusion. All in-range targets use exact Euclidean distance and the same noise/confidence model.
- The live visualization receives exact entity truth for drawing. Although agent decision code receives observations, the player map currently renders all evaluator contacts, so hidden truth is not visually separated from agent-known tracks.
- The network has no spatial connectivity, explicit message queue capacity, message expiration, retry, acknowledgement, or message types beyond observation reports. A report ID is reserved before recipient scheduler admission; overload cannot be repaired by a later duplicate.
- The scheduler is a global synthetic computation queue, not per-agent execution capacity. Coordination tasks do not make agents move or perform an observable task.
- “Decentralized” coordination computes deterministic proposals inside one manager with a shared resource-load view. It is not a distributed protocol with local knowledge or communication-dependent proposals.
- Metrics cover awareness, synthetic scheduler load/deadlines, message callback delivery, abstract assignment, and partition convergence, but not movement, area traversal, actual task completion, energy, duplicate physical work, or observation-to-application delay as a dedicated metric.
- The dashboard makes a one-seed scheduler comparison; research scripts provide matched seed sets. Interpretation of common random numbers should remain cautious because treatment branches consume a shared named stream a different number of times.

## Documented/presented capabilities that are not implemented in simulation

- Terrain textures, trees, hangars, and towers are presentation-only. There are no backend obstacle objects, collision, path planning, or line-of-sight effects.
- UAV sprites and their rotors are artwork; current positions are fixed world observers rather than a simulated aircraft trajectory.
- The “detection range” display is a visualization around a stationary observer and does not model heading/FOV or occlusion.
- Abstract review completion is a scheduled timer outcome. It does not require reaching a location, sensing a target, satisfying task criteria, or returning to base.
- The player can choose the initial sharing/scheduler configuration and change scheduler policy during a run. There are no validated movement, destination, task assignment, or reassignment commands.
- The map's synthetic evaluator contacts represent global truth, not an individual UAV's local knowledge. Track overlays represent local/shared knowledge separately, but the contact rendering itself is currently omniscient.
- There is no battery/energy model, failure/unavailable agent state, task capability model, multi-step mission state machine, or autonomous squad policy.

## New capabilities required for the target game

1. Backend geometry data types and scenario-backed static map definition: solid buildings/walls/rocks, non-solid terrain zones/roads, safe areas, restricted regions, mission locations and POIs.
2. Tested geometry queries: bounds, point occupancy, segment collision, and line-of-sight. A navigation grid or equivalent must derive from the same geometry.
3. Moving UAV state and deterministic kinematics, path planning/following, collision-safe motion, route replanning and unreachable-target handling.
4. FOV and occlusion-aware sensing using the moving UAV pose; local maps and tracks that remain separate from truth and are changed only by local sensing or delivered/applied reports.
5. Explicit typed messages with creation/delivery/application events, configurable connectivity/queue/expiry and documented duplicate/retry semantics.
6. Real mission tasks, assignment and state transitions whose completion criteria are simulation conditions, not elapsed timer alone.
7. Autonomous policies that navigate, observe, share, avoid unnecessary duplicate assignments, handle communication changes, and complete a multi-UAV reconnaissance mission.
8. Godot rendering of scenario-supplied geometry and actual UAV trajectories; no omniscient contact rendering presented as agent knowledge; validated command interface for any manual intervention.
9. Metrics for mission progress, travel/resource use and actual operational coordination, with documented denominators/edge cases and matched experiments.
10. Module status, model, mission/task, research-methodology, and launch/test documentation updated as capabilities become real.

## Architectural risks to manage

- Preserve the single authoritative `SimulationSession`; do not implement movement or task rules in GDScript or Plotly callbacks.
- Keep configuration and snapshot changes backward-compatible or version the protocol/artifact schema when necessary.
- Separate world truth, each agent's knowledge, mission task state, and render-only map assets.
- Make tick order explicit when adding movement, sensing, messages, task assignment and execution; event timestamps must agree with that order.
- Retain existing reproducibility guarantees while introducing RNG draws for movement/task policies. Use named streams so unrelated features do not silently perturb one another.
- Do not call the current abstract coordinator distributed; use “centralized” only for the current shared manager and introduce a genuine local-view/message protocol before claiming decentralization.
- Preserve CLI, batch workflows, existing artifact formats and saved baseline comparisons as regression checks.

## Phase 0 exit decision

Phase 0 is complete: code ownership and interfaces are identified, baseline tests and runtime checks pass, and the verified seed-42 output is recorded above. The next dependency is Module 1 (backend world model/geometry representation), followed by Module 2 (geometry queries and obstacle semantics). UAV motion must wait until those geometry queries are tested.
