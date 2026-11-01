# Local JSON-lines Protocol

## Transport and envelope

Run the adapter with `python3 -u -m swarmshield.protocol`. Each UTF-8 input line is one JSON request; each accepted line produces one JSON response line. Protocol version is integer `1`. A request must include:

```json
{"version":1,"request_id":"req-1","command":"list_scenarios","payload":{}}
```

Responses echo `request_id` and contain `version`, `ok`, and either `result` or a structured `error`:

```json
{"version":1,"request_id":"req-1","ok":false,"error":{"code":"unknown_command","message":"unsupported command 'bad'"}}
```

Malformed JSON has a null request identifier because one could not be decoded. Unknown fields in a payload are ignored unless the command validates them. The adapter keeps stdout protocol-only and writes unexpected diagnostics to stderr.

## Commands

All commands use `payload` as a JSON object.

| Command | Payload | Result / effect |
|---|---|---|
| `list_scenarios` | `{}` | Returns configured mission identifiers. |
| `list_saved_comparisons` | `{}` | Lists saved matched comparisons under `runs/comparisons/`. |
| `load_saved_comparison` | `{"comparison_id":"matched-scheduler-…"}` | Loads one saved paired comparison by its generated ID. |
| `run_matched_comparison` | `{"scenario":"deadline_pressure","start_seed":42,"seed_count":5,"dimension":"scheduler","mode":"cooperative","policy":"fixed-priority"}` | Runs a matched seed set (2–30 seeds), saves every treatment run with the normal artifact writer, and saves a paired comparison. |
| `start_run` | `{"scenario":"shared_awareness","seed":42,"mode":"cooperative","policy":"fixed-priority"}` | Starts a clean session, assigns spatial tasks, and dispatches autonomous routes at logical tick 0. `seed`, `mode`, and `policy` are optional; only bundled mission IDs are accepted. |
| `pause_run` | `{}` | Prevents `advance_ticks` until resumed. |
| `resume_run` | `{}` | Allows logical tick advancement. |
| `reset_run` | `{}` | Recreates the current scenario with the same selected seed and initial mode/policy, then repeats task assignment and initial route dispatch at tick 0. |
| `set_simulation_speed` | `{"speed":2}` | Stores one of `0.25`, `0.5`, `1`, `2`, `4`; the presentation layer uses this for its fixed tick request interval. |
| `advance_ticks` | `{"count":1}` | Advances an integer from 1 to 500 ticks unless paused or already complete. Returns the resulting render snapshot, metrics, recent events, and, at the horizon, summary and artifact path. |
| `get_snapshot` | `{}` | Returns current tick, status, configuration, renderable world, engine-derived live metrics, and recent events. |
| `inspect_agent` | `{"agent_id":"agent-001"}` | Returns local tracks/freshness, simulated communication status and pending inbound messages, assigned review work, and the global decision backlog. |
| `apply_intervention` | `{"action":"set_scheduler_policy","parameters":{"policy":"edf"}}` | Applies one supported, Python-validated intervention. Actions include scheduler policy changes, a route for a free UAV (`set_uav_destination` with `agent_id` and `[x,y]` destination), and mission-task reassignment (`reassign_mission_task` with `task_id` and `agent_id`). Unsupported or invalid choices are recorded as rejected. |
| `end_run` | `{}` | Finalizes the current run at the current tick, saves artifacts, and marks it incomplete if ended before the configured horizon. |
| `shutdown` | `{}` | Finalizes and saves an active run before cleanly exiting the child process. |

Supported in-run interventions are `set_scheduler_policy` (`fixed-priority` or `edf`), `set_uav_destination`, and `reassign_mission_task`. Destination commands require a known free UAV, finite in-bounds navigable coordinates, and a feasible planned route; a UAV that owns an active task or is recovering cannot be manually redirected. Reassignment uses the mission task state machine and allocator checks, and dispatches the accepted task through the autonomous behavior policy. Accepted and rejected attempts include tick, action, parameters, and outcome in the event stream and `interventions.json`. Scheduler changes apply to later ticks; completed work and earlier tick history are not re-run. Map display toggles do not change engine state or metrics.

For `run_matched_comparison`, `dimension="scheduler"` compares fixed-priority with EDF while holding `mode` constant. `dimension="sharing"` compares independent with cooperative while holding `policy` constant. Both treatments receive each identical seed and mission configuration; the result stores per-seed metrics and right-minus-left differences. The comparison and all treatment run artifacts are saved independently. The UI caps requests at 30 seeds; reported means and paired differences are descriptive, not a significance claim.

## Errors and lifecycle

Error codes include `malformed_json`, `invalid_request`, `protocol_version_required`, `unsupported_protocol_version`, `invalid_payload`, `unknown_command`, `no_run`, `run_active`, `run_paused`, `invalid_scenario`, `invalid_seed`, `invalid_speed`, `invalid_tick_count`, `invalid_agent`, `unknown_agent`, `invalid_intervention`, `invalid_comparison`, and `unknown_comparison`. Errors do not terminate the protocol loop. Unexpected backend exceptions return `internal_error` and log a traceback summary only to standard error.

The adapter has no independent simulation thread or wall-clock tick loop. It only advances on an accepted `advance_ticks` request. Godot uses a three-second response timeout for normal commands and a bounded 15-second timeout for matched comparisons, then closes the child process on exit. The Python loop exits on EOF or `shutdown`.

## Snapshot fields

`world.entities` contains synthetic evaluator positions for drawing only; agent decision code receives observations, not exact truth. Live `world.agents` entries contain identity, current position and heading (radians in world coordinates, where positive Y points down), plus UAV status, speed, battery, distance, current task ID, recovery target, current waypoint, final destination, and remaining route waypoints. Initial observers are placed around the protected-zone center. Mission start invokes the Python behavior policy, which assigns destinations through deterministic grid A*. The intervention command supports a Python-validated destination for an eligible free UAV. Archived trace snapshots retain UAV route state once a vehicle has been commanded to move, while no-movement snapshots preserve the earlier trace schema. `world.tracks` contains stored local tracks with agent ID, entity ID, estimated position, and observed tick. The snapshot also includes the protected/reference zone and configured geometry for live rendering.

Live `metrics` include fresh team and per-agent coverage, mean fresh-track age, sent/delivered/dropped/pending messages, decision backlog and task/deadline counts, abstract review task counts, recovery time if reached, and `communication_status` (`available`, `partitioned`, or `peer_sharing_disabled`). Mission-backed runs add distinct spatial mission-task completion/deadline metrics, sampled mission-area sensor coverage, UAV travel and energy totals, overlapping local observation counts, and actual shared-track application delay. These additional metrics appear only when the run has spatial mission tasks, preserving the task-free legacy summary schema. Queue reporting includes configured capacity, active tasks due within two ticks, and the nearest active deadline slack. When non-default network controls are configured, metrics also include communication range, pending-envelope capacity, TTL/retry settings, retry attempts, and expired message counts. For partition scenarios, the session also reports mean team and per-agent coverage during the outage so far. Missing values are JSON `null`; consumers must distinguish `null` from numeric zero. See [research metric definitions](RESEARCH_METHODOLOGY.md) for exact numerators, denominators, units, and edge cases. The inspector exposes basic UAV navigation status, current/final destination, remaining waypoints, and sensor profile fields `detection_range`, `detection_probability`, `position_noise_std`, `field_of_view_degrees`, `require_line_of_sight`, and `max_track_age_steps`. Mission task lifecycle states appear under `mission.tasks`. Route events include `uav_route_planned`, `uav_route_replanned`, and `uav_destination_unreachable` when the Python behavior policy or session API assigns or recovers a route.

Snapshots include `pending_message_links`, taken from the actual network queue with message ID, message protocol version/type, sender, recipient, entity, send tick, due tick, optional validity deadline, provenance, duplicate index, and retry attempt. Recent delivery/loss/expiry routes are taken from `recent_events`. Presentation should not infer links from agent proximity or draw unreported traffic.

Snapshots also include a bounded `presentation_events` feed for successful `track_updated` applications. Each row identifies the reporting source, receiving agent, entity, provenance (`local` or `shared`), observation tick, application tick, and information age. A `message_delivered` row means the network receive callback accepted/queued the payload; only `track_updated` confirms that the receiving agent's knowledge actually changed. Stale or unchanged observations do not emit a success row. This UI feedback feed is separate from canonical CSV research events so existing archived event artifacts remain stable.

The protocol snapshot includes a `mission` object with configured id/name/description, prototype flag, current status, team and scheduler policies, scoring weights, objective rows, and spatial task records. At run start, the centralized allocator assigns tasks that have a feasible route, required sensor capabilities, enough energy including a recovery reserve, and an estimated completion before the deadline. Other tasks remain `unassigned` with an `assignment_reason`. The Python behavior policy dispatches routes, while the session validates task transitions and evaluates completion from actual movement and observation history. Navigation, start, completion, failure, expiry, cancellation, reassignment, and player interventions are recorded in events. Godot exposes validated destination and reassignment actions; task cancellation remains a Python session API rather than a Godot control. Mission evaluation remains based on its configured metrics. Each objective row contains its configured label, metric, operator, target, actual metric value (or `null`), pass state, and guidance derived from the same actual/target check. Renderers may visualize progress but must preserve the engine-evaluated result.

Presentation-only `world.tracks` fields include `source_agent_id` and `confidence`, taken from the agent's actual stored track. The headless runner's existing CSV snapshot schema is unchanged.

## Versioning

The JSON-lines protocol version is independent of engine, artifact schema, and in-simulation message schema versions. Incompatible/missing JSON-lines versions fail before command dispatch. In-simulation `Envelope` records carry `protocol_version=1` and `message_type="observation"`; unsupported envelope versions/types are rejected before a report task is queued. `valid_until_step` is inclusive; expired envelopes are removed before the receive callback. Summaries and manifests currently have schema version `1`.
