# Simulation Model

## Authority and time

Python `SimulationSession` is authoritative for world state, random streams, UAV motion, sensing, communication, task transitions, metrics, mission outcomes, and artifacts. Godot submits controls and renders snapshots; it does not move agents or advance the simulation independently. Each accepted `advance_tick()` call advances one integer logical tick. Pause and display tick rate do not alter the deterministic engine path.

Coordinate units are map/world units. The origin is at the upper-left, positive X points right, and positive Y points down. A world with width `W` and height `H` spans `[0,W] × [0,H]`. Logical ticks do not imply wall-clock seconds.

## World and geometry

Mission JSON configures world bounds, synthetic entity population and motion, protected/reference zones, mission areas, safe and restricted areas, roads, vegetation, obstacles, and points of interest. `World` owns exact synthetic entity positions. Those positions are available to the evaluator and research snapshots; agent decision code only receives generated observations. The Godot coordination map shows contacts from agent-owned tracks, not raw evaluator truth.

Polygon geometry is shared by UAV collision checks, deterministic grid A* path planning, sensor line-of-sight tests, and the map's fitted terrain/obstacle artwork. Roads and vegetation are visual context unless their geometry is explicitly marked as collision or LOS blocking. The coordinate grid is a rendering-only optional overlay.

## UAV motion and routing

Each agent owns a UAV motion state with position, heading, speed, destination, remaining waypoints, task ownership, battery, and distance travelled. Per-tick movement respects configured acceleration, maximum speed and turn rate, world bounds, collision geometry, and energy per distance. A deterministic 8-connected A* planner supplies obstacle-aware waypoints; blocked routes are replanned when possible and unreachable destinations are recorded.

Mission start uses the centralized nearest-feasible task allocator and `AssignedMissionBehavior` to route assigned agents. Free low-battery agents may return to a reachable configured safe area. A player destination command is available only for a selected free UAV without active mission ownership or recovery routing. Python validates coordinates and route feasibility for this intervention. Generic task-free sessions do not start a mission behavior policy and need an explicit route assignment to move.

## Sensing and local knowledge

At each tick, an agent sensor evaluates current position and heading against synthetic entity truth. Detection eligibility uses configured range, heading-relative field of view, and optional polygon line of sight; a configured probability draw then determines whether an eligible entity is observed. Report coordinates receive configured Gaussian noise and are clamped to world bounds. The current model produces no false positives and uses fixed confidence `1.0`.

Each agent keeps its own latest track per entity plus a history of distinct reports for evidence checks. Newer reports replace older tracks; stale reports and same-tick reports without stronger confidence do not replace the current track. Cooperative sharing sends source reports through the modeled network; independent mode does not send peer reports. A message callback or delivery event is not itself proof that recipient knowledge changed; `track_updated` records confirmed local/shared application.

The map's sensor-range circle is only a visual range cue. It does not encode heading/FOV, LOS, detection probability, or uncertain visibility. Hiding any map layer changes rendering only and does not filter observations, tracks, communication, or metrics.

## Network, queues, and task systems

The peer network is an in-process deterministic model with configurable delivery loss, integer latency, optional duplication, optional Euclidean range, a bounded pending-envelope queue, TTL expiry, immediate retry after random publication loss, and an optional global outage interval. It has no physical radios, routing hops, bandwidth, per-link state, or obstacle-based radio occlusion.

Two task systems remain separate:

- **Decision/review work** uses one global bounded logical-work scheduler with fixed-priority or EDF ordering. It represents synthetic report-processing and abstract review work, not per-agent CPU or real-time duration.
- **Spatial mission tasks** have regions/locations, prerequisites, deadlines, capabilities, and evidence-based completion criteria. A centralized allocator assigns work and the autonomous Python policy follows routes. Task completion requires actual observations, independent reports, sensor-footprint coverage, or arrival, according to the task definition; estimated duration does not complete tasks. Player reassignment is validated by the same Python task model.

## Tick order

Each `advance_tick()` follows this order:

1. Increment the logical tick and expire overdue decision work.
2. Advance moving entities and each UAV once; record route events and current poses, update sampled mission-area coverage, and replan blocked routes.
3. Record communication partition transitions and generate local sensor observations from current UAV poses.
4. Submit local observations and deliver due network envelopes.
5. Process the global decision queue and apply completed report actions to agent knowledge.
6. Advance abstract review coordination and perform the second due-message delivery pass.
7. Evaluate communication recovery and partition coverage samples.
8. Attempt autonomous unavailable-owner reassignment, evaluate spatial mission-task state/evidence/deadlines, release terminal assignments, and assign newly feasible tasks.
9. Dispatch autonomous routes, record the render snapshot, and finalize at the configured horizon.

The CLI runner, JSON-lines protocol, Godot bridge, and matched comparisons call this same engine implementation.

## Metrics and results

Legacy `task_completion_rate` and `deadline_miss_rate` describe decision-queue work. Mission-backed runs additionally report spatial task completion/deadlines, mission completion time, sampled geometric area coverage, unique entity observations, UAV distance/energy, overlapping sensor reports, and confirmed shared-track application delay. New spatial metrics are emitted only for mission-backed runs so the task-free archived baseline metric schema remains stable.

Mission success is computed from the configured mission objective rows at run finalization. Missing (`null`) objective values do not pass. The separate provisional 0–100 score combines the documented awareness, timeliness, reliability, and decision-work efficiency dimensions; those weights are gameplay choices, not research-derived preferences. See [Research Methodology](RESEARCH_METHODOLOGY.md) for exact definitions, denominators, units, and edge cases.

## Limits

The world is synthetic, motion and network behavior are simplified, allocation and autonomous mission behavior are centralized, communication partitions are global, and area coverage is a deterministic geometric sensor-footprint sample rather than probabilistic detection. None of these outputs establish physical UAV performance. See [Coordination and Communication Architecture](COORDINATION_AND_COMMUNICATION_ARCHITECTURE.md) and [Mission and Task Model](MISSION_AND_TASK_MODEL.md) for component-level details.
