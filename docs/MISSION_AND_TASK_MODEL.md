# Mission and Task Model

## Current scope

Bundled missions define spatial reconnaissance tasks separately from the decision scheduler and the abstract coordination review queue. Each run receives independent task-state records through the Godot protocol snapshot. The Godot protocol applies the centralized baseline allocator at run start; feasible tasks become `assigned`, while infeasible tasks remain `unassigned` with a reason. A modular Python behavior policy then selects a reachable point in each assigned task area and issues a route through the existing obstacle-aware planner. The engine validates task transitions and evaluates actual movement and sensor evidence after each logical tick. Task outcomes still do not affect mission objectives or score.

The Python model lives in [`swarmshield/tasks.py`](../swarmshield/tasks.py). Mission task definitions are stored under `_mission.tasks` in `configs/missions/*.json`; `load_mission()` validates them before a run can start.

## Definition fields

| Field | Meaning |
|---|---|
| `task_id` | Unique mission task identifier. |
| `task_type` | One of `reconnaissance`, `search`, `confirmation`, `coverage`, or `return_to_recovery`. All are synthetic and non-lethal. |
| `location` | Optional `[x, y]` navigation or recovery point in world coordinates. |
| `region` | Optional polygon whose vertices must form a simple, non-zero-area shape inside world bounds. |
| `prerequisites` | IDs that must be completed first; references must exist and the dependency graph must be acyclic. |
| `priority` | Non-negative integer used by future assignment policies. |
| `deadline_step` | Absolute logical tick, from zero through the configured mission horizon. |
| `estimated_duration_steps` | Positive logical-tick work estimate. |
| `required_capabilities` | Named synthetic capabilities checked by the current allocator (`visual_sensor` is derived from a nonzero configured sensor range and detection probability). |
| `completion_criteria` | Typed condition: `observe_region`, `observe_entity`, `confirm_entity`, `cover_region`, or `arrive`, with the criterion-specific threshold or target. |

Spatial points and regions are validated against configured world dimensions. Criteria must match task type: reconnaissance either counts local reports made while in a region or measures sensor coverage there; search observes a named entity, confirmation confirms a named entity, coverage measures a region, and recovery requires arrival within a configured radius. Bundled surveys use a 60% sensor-footprint coverage threshold because synthetic targets may not occupy every survey region in a given seed.

## Runtime record

Each `SimulationSession` gets its own `MissionTask` instance per definition. A runtime record includes status, assigned agent, assignment/start/completion/failure/expiry/cancellation/reassignment ticks, an assignment explanation, result, failure reason, and event history. Records begin as `unassigned`; the protocol start command invokes assignment, and task states remain independent across runs.

The current assignment policy is centralized, with a single manager reading engine state and assigning at most one active task per UAV. It orders tasks by descending priority, then earliest deadline, then ID. For each task it plans reachable routes, estimates travel time using acceleration and the speed cap plus route-corner turn overhead, reserves enough battery for the outbound route and the nearest configured recovery area, checks prerequisites and required capabilities, and rejects assignments that cannot meet the deadline under its estimate. The ETA estimate does not model deceleration and is not an execution guarantee. Among feasible UAVs it selects earliest estimated completion, then lower required energy, then agent ID. During a configured network partition, new assignments are deferred with `communication_unavailable`. Assignment attempts that cannot proceed expose reasons such as `capability_mismatch`, `agent_busy_or_unavailable`, `route_unreachable`, `insufficient_energy_reserve`, and `deadline_infeasible`.

The `AssignedMissionBehavior` policy in [`swarmshield/behaviors.py`](../swarmshield/behaviors.py) routes each UAV only to its own assigned task, chooses deterministic navigable points within non-convex regions, and never submits the same task route repeatedly. Completed tasks release their UAV; newly prerequisite-ready tasks can then be assigned. If an owner becomes unavailable, the centralized policy tries a validated reassignment when communication is available and waits through a configured partition. Free UAVs below 20% battery return to a reachable configured safe area when their remaining battery can cover the route. Local observations continue to use the existing communication mode: cooperative runs publish actual reports through the modeled network; independent runs do not share them.

### Lifecycle and evidence

`MissionTaskStateMachine` in [`swarmshield/task_lifecycle.py`](../swarmshield/task_lifecycle.py) guards transitions:

```text
unassigned → assigned → navigating → executing → completed
                         ↘ failed / expired / cancelled / reassigned
```

Reassignment is recorded as an active state transition followed by assignment to a validated free UAV. The Godot mission panel exposes reassignment; Python validates ownership, availability, prerequisites, route feasibility, energy reserve, and deadline before dispatching the route. Cancellation remains a session API without a Godot control. The state machine runs after motion, network delivery, and scheduled track application. Estimated duration is only allocator input; it never completes a task. Deadlines are inclusive: a task may complete at its deadline and expires on the first tick after it.

Completion evidence follows these rules:

- `observe_region`: counts distinct `(entity_id, observed_at)` reports sourced by the assigned UAV on ticks when its actual pose was inside the task polygon, after execution began.
- `observe_entity`: requires the configured number of distinct observation ticks for the named entity, sourced by the assigned UAV after execution began.
- `confirm_entity`: requires the configured number of distinct source UAVs to have reported the named entity after execution began. The default is two.
- `cover_region`: samples the polygon on a deterministic 2-world-unit grid and checks actual recorded UAV poses against sensor range, heading-relative field of view, and configured line of sight. This geometric footprint metric does not model probabilistic detection.
- `arrive`: requires the UAV's actual position to be inside the configured arrival radius around the recovery location.

The per-agent observation history is separate from its latest reconciled track. It retains unique reports by entity, observation tick, and source, so simultaneous independent reports can support confirmation without allowing stale or duplicate reports to overwrite or inflate the current track. Only reports actually applied to the assigned agent's knowledge count for its evidence checks.

Accepted transitions emit canonical `mission_task_*` events and are exposed in snapshots and saved run event logs. Failed navigation, unavailable agents, lost task ownership, unavailable prerequisites, cancellation, reassignment, and deadline expiry produce explicit status/reason events. These task states do not yet affect the existing mission score or success result. Each bundled mission defines four spatial surveys in separated map regions, with scenario-specific logical deadlines aligned with the shared map preset. Each task destination is beyond its assigned launch observer's initial sensing range, so all four UAVs must fly to distinct mission sectors.

## Separate task systems

- **Decision scheduler tasks** model bounded abstract information processing and deadline behavior.
- **Coordination review tasks** model abstract work requested after an agent's track changes. The configured `centralized`/`decentralized` policy labels apply to this review manager only.
- **Mission tasks** describe spatial objectives for UAVs. They are assigned by the centralized baseline and have guarded, evidence-based lifecycle transitions. The current autonomous behavior follows those assignments and returns low-battery free UAVs to safe areas. Godot supports validated task reassignment and free-UAV destinations; mission-result integration remains a later module.

Task completion reflects actual movement, local reports, independent report sources, or sampled sensor footprints. The bundled Godot mission assigns the four reconnaissance sectors to four distinct UAVs, which fly obstacle-aware routes and can complete all four tasks autonomously. Spatial task completion, deadline, travel, energy, and sampled-area metrics are reported separately from abstract decision-queue metrics. The centralized assignment and behavior policies are not distributed. Mission success and the provisional score still use the configured objective metrics; task records do not implicitly change the result. Shared/local track copies are deduplicated to one map marker per entity; selecting a UAV shows only that UAV's own track view.
