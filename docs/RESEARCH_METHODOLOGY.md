# Research Methodology and Metric Definitions

## Reproducibility

The Python `SimulationSession` is the only simulation engine used by Godot, the CLI, and batch experiments. A run is determined by engine version, scenario/configuration, seed, sharing mode, scheduler policy, and ordered interventions. Logical time advances only through integer engine ticks. UI display filters do not alter engine inputs or metric calculations.

Matched comparisons use the same configured seeds for both treatments and hold the other selected factors constant. Reports compute a two-sided 95% Student-t interval over the per-seed paired differences (right minus left), plus the sample standard deviation and standard error. The interval assumes seed-level paired differences are independent and reasonably represented by a t-based mean interval. With 2–30 seeds, bounded or skewed metrics, and multiple comparisons, the interval is descriptive rather than a significance test; it can extend beyond a metric's valid range. Record scenario/configuration, seed set, treatment factors, engine revision when available, and artifact identifiers with every result.

## Metric definitions

Metrics from the abstract decision scheduler and spatial mission tasks are separate. `task_completion_rate` and `deadline_miss_rate` continue to describe synthetic review/decision work. Spatial UAV task performance uses names prefixed with `mission_`.

| Metric | Numerator / denominator | Units and edge behavior |
|---|---|---|
| `any_agent_awareness_coverage` | Distinct configured entities with at least one current track within the freshness window / configured entity count | Fraction `[0,1]`; zero when no entities are configured. |
| `mean_agent_track_coverage` | Mean, over agents, of each agent's distinct current fresh entity tracks / configured entity count | Fraction `[0,1]`; zero when there are no agents or entities. |
| `mean_track_age_steps` | Mean current fresh-track age at run horizon | Logical ticks; `null` when no current tracks exist. |
| `mean_first_detection_delay_steps` | Mean first local sensor-report tick for each detected entity | Logical ticks from run start; `null` when no entity was observed. |
| `time_to_first_observation_steps` | Earliest tick containing any generated local sensor report | Logical ticks from run start; `null` when no report was generated. This is detection generation, not later scheduler application. |
| `messages_sent`, `messages_delivered`, `messages_dropped` | Original peer messages by final network outcome; duplicate copies are excluded | Message counts. Pending-at-horizon originals are reported separately. |
| `message_delivery_ratio` | Delivered original messages / sent original messages | Fraction; `null` when no original message was sent. |
| `mean_message_latency_steps` | Mean sent-to-delivery delay over delivered original messages | Logical ticks; `null` when no originals were delivered. |
| `deadline_miss_rate` | Missed eligible abstract decision tasks / eligible abstract decision tasks | Fraction; `null` with no eligible decision tasks. This is not the mission-task deadline rate. |
| `task_completion_rate` | Completed abstract decision tasks / all created abstract decision tasks | Fraction; `null` when no decision task was created. |
| `mission_task_completion_rate` | Spatial mission tasks in `completed` state / all configured spatial mission tasks | Fraction; `null` when a session has no spatial tasks. Failed, expired, cancelled, unassigned, and active tasks remain in the denominator. |
| `mission_task_deadline_miss_rate` | Spatial tasks whose deadline passed without completion / spatial task deadlines strictly earlier than the current tick | Fraction; `null` when no mission deadline has passed. Deadlines are inclusive, so a task may complete on its deadline tick. |
| `mission_completion_time_steps` | The latest task completion tick, when every configured mission task completed | Logical ticks from run start; `null` if the mission has no tasks or any task remains incomplete. |
| `mission_mean_task_completion_time_steps` | Mean of completion tick minus first assignment tick over completed spatial tasks | Logical ticks; `null` when no spatial task completed. |
| `mission_area_coverage_fraction` | Sampled points in all configured mission task regions reached by at least one recorded UAV sensor footprint / all sampled points in those regions | Fraction; `null` without spatial regions. Samples are spaced at 2 world units, include region bounds, and use actual pose, configured range/FOV and configured LOS. This geometric measure does not model detection probability. Overlapping task regions contribute once per task region. |
| `total_uav_distance_travelled` | Sum of actual movement distance over all UAVs | World-coordinate units; zero when no UAV moved. Per-agent totals are included in `uav_distance_by_agent`. |
| `uav_energy_consumed` | Sum of configured battery capacity minus remaining battery for each UAV | Configured battery-energy units; zero when no battery was spent. Per-agent totals are included in `uav_energy_consumed_by_agent`. |
| `overlapping_observation_reports` | Generated local sensor reports beyond the first for each `(entity, tick)` group | Count. This measures overlapping reports, which may be useful corroboration and are not automatically wasted work. |
| `overlapping_observation_report_rate` | Overlapping reports / all generated local observation reports | Fraction; `null` when no local report was generated. |
| `shared_track_applications` | Shared reports that actually updated a recipient's reconciled local track | Count; duplicate, stale, and unchanged reports are excluded. |
| `mean_observation_to_shared_application_delay_steps` | Mean recipient application tick minus source observation tick for shared reports that updated tracks | Logical ticks; `null` when no shared report updated a track. |
| `mission_task_assignment_events`, `mission_task_reassignment_events` | Actual accepted spatial-task lifecycle transitions | Event counts. |
| `mission_assignment_actions_per_task` | Assignment plus reassignment events / configured spatial tasks | Actions per task; `null` without spatial tasks. |
| `recovery_time_steps` | Existing engine-defined fresh-track convergence time after communication restoration | Logical ticks; `null` when recovery was not measured or no configured recovery event occurred. |

The additional spatial metrics are emitted only for runs configured with mission tasks. Legacy task-free run summaries therefore retain their existing metric keys and archived baseline values. Wall-clock runtime is a diagnostic and is not deterministic or a research outcome.

## Game score

The optional 0–100 game score normalizes and combines the configured awareness, timeliness, reliability, and decision-work efficiency dimensions. The default weights are 0.30, 0.30, 0.25, and 0.15 respectively; unavailable dimensions are omitted and remaining weights are renormalized. These are explicitly provisional gameplay weights, not research-derived preferences. Keep the component raw values, normalized values, configured/effective weights, and total score separate in artifacts. Research comparisons should use raw engine metrics rather than infer a scientific conclusion from this composite score.

## Interpretation limits

The simulator uses a centralized task allocator and behavior policy, a global decision queue, a global communication partition, synthetic entity observations, and geometric coverage checks. The current metrics do not establish real-world UAV performance, probabilistic area detection, distributed coordination, or statistical significance. See [coordination and communication architecture](COORDINATION_AND_COMMUNICATION_ARCHITECTURE.md) for model boundaries.
