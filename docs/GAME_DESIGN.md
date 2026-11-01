# SwarmShield Game Design

## Play loop

Choose a mission, team sharing policy, scheduler, and seed. Watch the synthetic world advance in fixed engine ticks, inspect an agent's local tracks, and change the scheduler when deadline pressure warrants it. The Python engine owns simulation state and time; the presentation only draws backend snapshots.

The map gets most of the play area. Team metrics sit below it. The right panel uses Mission, Agent, Events, and Results tabs so one sidebar scroll area can show long content without stacked scrollbars. The top header shows mission, state, logical tick, elapsed ticks, and run controls.

## Controls

- **Start mission** begins the selected scenario with the displayed seed.
- **Team policy** chooses cooperative message sharing or independent local views for the new run.
- **Scheduler** chooses fixed-priority or earliest-deadline-first (EDF) scheduling for a new run.
- **Pause / Resume** stop or continue requests for engine ticks. Pausing does not advance virtual time.
- **Reset** creates a fresh engine session with the same scenario, seed, sharing mode, and initial policy.
- **Tick rate** changes how often Godot requests an engine tick. It does not modify simulation rules.
- **Apply scheduler** submits a validated `set_scheduler_policy` intervention (`fixed-priority` or `edf`) to Python. Accepted and rejected requests are recorded with the current logical tick.
- **Set destination** is enabled only for a selected idle UAV with no active mission task or recovery route. Enable it and click an empty map position; Python validates coordinates and obstacle-aware route feasibility before accepting the command.
- **Reassign** in the Mission tab submits an active task and available UAV to the Python task allocator/state machine. Capability, ownership, route, energy reserve, deadline, and communication constraints are checked by the engine.
- Hover over agents, entities, or track markers for concise details. Click a quadcopter or select an observer in the Agent tab. The inspector shows navigation, battery, distance, assigned mission tasks, local/shared track provenance and freshness, pending inbound messages, last send/receive ticks, assigned abstract review work, deadline slack, and the global decision queue size.
- Mission objectives and their current values come from the backend's mission definition and metrics. Unmet objectives show the actual gap or why a metric is unavailable. Guidance only points to controls the simulation actually supports; there is no direct intervention for coverage or network recovery.
- The Events tab groups real backend events by logical tick and category. Warnings, discoveries, task changes, communication changes, and player interventions use severity text/symbols as well as color.
- Map controls independently show/hide UAVs, task/route overlays, backend terrain geometry, local observations, shared reports, optional fog, stale tracks, recent communication links, selected-UAV sensor range, labels and grid. Mission areas and caution zones start hidden, and unselected task regions are subdued. These filters affect drawing only. Links default off and use only recent backend events or actual pending envelopes: green for delivered, amber for pending/delayed, red for lost. Track outlines distinguish fresh and stale state.
- Queue pressure is shown against the actual queue capacity; active tasks due within two ticks and their nearest deadline receive warning colors.
- The Results tab separates provisional game scoring from raw research metrics. Individual results display the selected run's saved summary. Matched comparisons can hold sharing mode constant while comparing fixed-priority with EDF, or hold the scheduler constant while comparing independent with cooperative sharing. Both treatments receive the same seed set; each run and comparison is saved independently.
- The matched-comparison controls use the selected mission and displayed seed as the first of 2–30 seeds. Each treatment runs the selected spatial mission tasks. The report shows treatment means, per-seed values, right-minus-left differences, and descriptive paired 95% t intervals; it does not claim statistical significance.

The coordination map uses original top-down quadcopter and unclassified-contact sprites over synthetic satellite-inspired ground texture. It is not georeferenced imagery. Agent labels appear on hover or selection. Initial headings face the protected-zone center; after a destination is assigned, sprite yaw follows Python's simulated heading. Mission configs load backend polygon geometry; the map places roads, buildings, vegetation, and tactical areas from that geometry, and Python uses the same geometry for collision, path planning, and LOS. The four bundled task destinations lie beyond the assigned UAVs' initial sensing ranges, so all four UAVs fly separate routes to dispersed regions. Track markers preserve source and freshness styling but collapse repeated reports into one marker per entity; selecting an agent shows that UAV's track view. Communication routes use event sender/recipient IDs and current engine positions; no route is drawn without a backend event or queued message. Protection rings use an entity's last-known agent track and evidence-based backend status; there is no global evaluator reference ring on the map.

## Missions

All thresholds are configurable in `configs/missions/*.json`. They are provisional gameplay thresholds, not validated scientific standards.

| Mission | Engine mechanics | Objectives |
|---|---|---|
| Shared Awareness | Range-limited observations, local tracks, delayed/lost cooperative reports | Fresh team coverage at least 50%; mean per-agent fresh-track coverage at least 40%. |
| Deadline Pressure | Bounded decision queue, randomized task costs/deadlines, fixed-priority and EDF scheduling | At least 70% of decision tasks complete; eligible-task deadline miss rate no more than 40%. |
| Network Recovery | Existing global simulated partition from about one-third to two-thirds of the run, local observations, delayed reports after restoration | Mean team coverage during the outage at least 30%; identical non-empty fresh track sets across agents recover within 20 ticks after restoration. |

The engine's recovery metric is unavailable (`null`) if the recovery condition is not reached. An unavailable value does not pass an objective.

The optional fog layer samples actual UAV sensor footprints at 2.5-world-unit cells using range, heading/FOV, and LOS. It distinguishes unexplored cells, current and past local coverage, and coverage received through an applied observation report. This render-only coverage state does not change mission metrics or task decisions; probabilistic entity detection remains separate.

## Mission result and score

Mission status is **success** when all configured objectives pass, **failure** when a run reaches its configured horizon and at least one objective fails, and **incomplete** when a run is ended before that horizon. Objective values come from engine metrics.

The provisional 0–100 score starts with Awareness 30%, Timeliness 30%, Reliability 25%, and Efficiency 15%. Each dimension is clamped to `[0, 1]`:

- Awareness: fraction of synthetic entities with a fresh track known by at least one agent.
- Timeliness: one minus the engine deadline-miss rate. Eligible tasks are those whose deadline is within the run horizon; dropped and expired eligible tasks count as misses.
- Reliability: delivered original peer messages divided by sent originals. It is unavailable when the run sends no messages.
- Efficiency: completed decision tasks divided by created decision tasks.

Unavailable dimensions are excluded and the remaining configured weights are renormalized. Raw metrics remain under `summary.json`'s `metrics`; game score and objective results are in `game_result`. Weights and definitions are included in each scored summary. These weights are initial design choices that need playtesting and research validation.

The event timeline reports observations, message sends/delivery/loss/duplicates, task lifecycle events, abstract assignments, and player interventions. Accepted and rejected scheduler, destination, and reassignment commands include their tick and outcome in the event stream and `interventions.json`. The selected-agent inspector shows UAV navigation, battery, distance, mission tasks, local knowledge and communication state. Values labelled `n/a` are not available from the current engine, rather than zero.

Matched comparisons are descriptive paired results. The report displays per-treatment means and right-minus-left differences for each matched seed; it does not label small samples statistically significant. See [Research Workflow](RESEARCH_WORKFLOW.md) for comparison artifacts and reproducibility details.
