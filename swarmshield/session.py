"""Incremental fixed-tick simulation session used by the CLI and game adapter."""

from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import replace
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from .agents import Agent, AgentSensorConfig
from .behaviors import AssignedMissionBehavior, MissionBehaviorPolicy
from .config import SimulationConfig, derive_seed
from .coordination import CoordinationManager
from .metrics import nearest_rank_percentile
from .network import MESSAGE_PROTOCOL_VERSION, Envelope, NetworkSimulator
from .navigation import GridPathPlanner
from .observations import Observation, ObservationModel
from .protection import EntityProtection, create_monitoring_task
from .scheduler import DecisionScheduler
from .tasks import MissionTask, MissionTaskDefinition
from .tasking import (
    CentralizedTaskAllocator,
    _estimate_travel_steps as _estimate_task_travel_steps,
    _recovery_distance as _mission_recovery_distance,
    _task_destination as _mission_task_destination,
)
from .task_lifecycle import ACTIVE_TASK_STATUSES, MissionTaskStateMachine, region_sample_points, sensor_covers
from .world import World


SENSOR_COVERAGE_CELL_SIZE = 2.5


class SimulationSession:
    """Owns a run and advances it only when explicitly asked for logical ticks."""

    def __init__(
        self,
        config: SimulationConfig,
        mode: str,
        policy: str | None = None,
        mission_tasks: tuple[MissionTaskDefinition, ...] = (),
        behavior_policy: MissionBehaviorPolicy | None = None,
        mission_id: str | None = None,
        enable_presentation_coverage: bool = False,
    ) -> None:
        if mode not in {"independent", "cooperative"}:
            raise ValueError("mode must be 'independent' or 'cooperative'")
        selected_policy = policy or config.scheduler_policy
        if selected_policy not in {"fixed-priority", "edf"}:
            raise ValueError("policy must be 'fixed-priority' or 'edf'")
        config.validate()

        self.config = config
        self.mode = mode
        self.policy = selected_policy
        self.mission_id = mission_id
        self.enable_presentation_coverage = bool(enable_presentation_coverage)
        self.runtime_started = perf_counter()
        self.started_at_utc = datetime.now(timezone.utc).isoformat()
        self.world = World(config, derive_seed(config.seed, "world"))
        self.path_planner = GridPathPlanner()
        self.agents = {
            observer.agent_id: Agent(
                observer,
                config.uav,
                AgentSensorConfig(
                    config.detection_range,
                    config.detection_probability,
                    config.position_noise_std,
                    config.field_of_view_degrees,
                    config.require_line_of_sight,
                    config.max_track_age_steps,
                ),
            )
            for observer in self.world.observers
        }
        self.observer_by_id = {observer.agent_id: observer for observer in self.world.observers}
        self.agent_ids = tuple(self.agents)
        self.observation_model = ObservationModel(
            rng=random.Random(derive_seed(config.seed, "observations")),
            detection_range=config.detection_range,
            detection_probability=config.detection_probability,
            position_noise_std=config.position_noise_std,
            world_width=config.world_width,
            world_height=config.world_height,
            field_of_view_degrees=config.field_of_view_degrees,
            require_line_of_sight=config.require_line_of_sight,
        )
        self.network = NetworkSimulator(
            rng=random.Random(derive_seed(config.seed, "network")),
            delivery_probability=config.delivery_probability,
            max_latency_steps=config.max_latency_steps,
            duplicate_probability=config.duplicate_probability,
            partition_enabled=config.partition_enabled,
            total_steps=config.steps,
            communication_range=config.communication_range,
            queue_capacity=config.message_queue_capacity,
            message_ttl_steps=config.message_ttl_steps,
            max_retries=config.max_message_retries,
        )
        self.scheduler = DecisionScheduler(
            rng=random.Random(derive_seed(config.seed, "scheduler-workload")),
            policy=selected_policy,
            processing_capacity_per_step=config.processing_capacity_per_step,
            queue_capacity=config.queue_capacity,
            min_deadline_steps=config.min_task_deadline_steps,
            max_deadline_steps=config.max_task_deadline_steps,
            max_processing_cost=config.max_task_processing_cost,
            max_priority=config.max_task_priority,
        )
        self.coordination = CoordinationManager(
            resource_ids=tuple(self.agents),
            mode=config.coordination_mode,
            capacity_per_resource=config.task_capacity_per_resource,
            task_duration_steps=config.coordination_task_duration_steps,
            task_deadline_steps=config.coordination_task_deadline_steps,
            queue_capacity=config.coordination_queue_capacity,
        )
        self.mission_tasks = {
            task.task_id: MissionTask(task)
            for task in mission_tasks
        }
        if len(self.mission_tasks) != len(mission_tasks):
            raise ValueError("mission task identifiers must be unique")
        self.protection_designations: dict[str, EntityProtection] = {}
        self.protection_task_ids: list[str] = []
        self._protection_terminal_events: set[str] = set()
        # These maps are presentation knowledge only. They never enter task
        # assignment, objective metrics, or the canonical trace snapshots.
        self.local_sensor_coverage: dict[str, dict[tuple[int, int], int]] = {
            agent_id: {} for agent_id in self.agent_ids
        }
        self.shared_sensor_coverage: dict[str, dict[tuple[int, int], int]] = {
            agent_id: {} for agent_id in self.agent_ids
        }
        self.task_allocator = CentralizedTaskAllocator()
        self.task_state_machine = MissionTaskStateMachine()
        self.behavior_policy = behavior_policy or AssignedMissionBehavior()
        self.step = 0
        self._next_task_number = 1
        self.actions: dict[str, Callable[[], str]] = {}
        self.observation_events: list[dict[str, object]] = []
        self.trace_events: list[dict[str, object]] = []
        # UI feedback is kept separate from canonical research events so adding
        # presentation detail does not rewrite existing CSV artifacts.
        self.presentation_events: list[dict[str, object]] = []
        self.interventions: list[dict[str, Any]] = []
        self.first_detection_step: dict[str, int] = {}
        self.observation_to_shared_application_delays_steps: list[int] = []
        self.mission_area_points_by_task = {
            task_id: region_sample_points(task.definition.region)
            for task_id, task in self.mission_tasks.items()
            if task.definition.region is not None
        }
        self.mission_area_covered_indices_by_task = {
            task_id: set() for task_id in self.mission_area_points_by_task
        }
        for agent in self.agents.values():
            for initial_pose in agent.pose_history:
                self._record_mission_area_pose(agent, initial_pose)
        self.partition_team_coverage_samples: list[float] = []
        self.partition_agent_coverage_samples: list[float] = []
        self.recovery_time_steps: int | None = None
        self.partition_restore_step = max(config.steps // 3 + 1, (2 * config.steps) // 3)
        self.finished = False
        self.summary: dict[str, Any] | None = None
        self.events: list[dict[str, object]] = []

    @property
    def current_step(self) -> int:
        return self.step

    def _event(self, **kwargs: Any) -> dict[str, object]:
        from .runner import _event

        return _event(**kwargs)

    def _enqueue_decision(
        self,
        task_type: str,
        step: int,
        information_time: int,
        action: Callable[[], str],
    ) -> bool:
        task_id = f"task-{self._next_task_number:08d}"
        self._next_task_number += 1
        accepted = self.scheduler.submit(task_id, task_type, step, information_time)
        if accepted:
            self.actions[task_id] = action
        return accepted

    def _apply_report(self, agent: Agent, observation: Observation) -> str:
        outcome = agent.apply_observation(observation)
        if observation.source_agent_id != agent.agent_id and outcome in {"updated", "unchanged"}:
            if outcome == "updated":
                self.observation_to_shared_application_delays_steps.append(
                    max(0, self.step - observation.observed_at)
                )
            shared_cells = self.shared_sensor_coverage[agent.agent_id]
            for cell in observation.sensor_coverage_cells:
                shared_cells[cell] = max(
                    shared_cells.get(cell, -1), observation.observed_at,
                )
        if outcome == "updated":
            self.coordination.request_review(observation.entity_id, self.step)
            self.presentation_events.append(self._event(
                step=self.step,
                event_type="track_updated",
                sender_id=observation.source_agent_id,
                recipient_id=agent.agent_id,
                entity_id=observation.entity_id,
                details=json.dumps({
                    "provenance": "local" if observation.source_agent_id == agent.agent_id else "shared",
                    "observed_at": observation.observed_at,
                    "applied_at": self.step,
                    "age_steps": self.step - observation.observed_at,
                }, sort_keys=True, separators=(",", ":")),
            ))
            if len(self.presentation_events) > 120:
                del self.presentation_events[:-120]
        return outcome

    def _record_mission_area_pose(self, agent: Agent, pose: tuple[int, float, float, float]) -> None:
        """Record sampled mission-area cells actually within any UAV footprint."""
        for task_id, points in self.mission_area_points_by_task.items():
            covered = self.mission_area_covered_indices_by_task[task_id]
            for index, point in enumerate(points):
                if index in covered:
                    continue
                if sensor_covers(agent, self.world, pose, point):
                    covered.add(index)

    def _sensor_coverage_for_pose(self, agent: Agent, pose: tuple[int, float, float, float]) -> tuple[tuple[int, int], ...]:
        """Sample the actual configured sensor footprint for display/fog state."""
        if agent.sensor_config.detection_range <= 0.0 or agent.sensor_config.detection_probability <= 0.0:
            return ()
        columns = math.ceil(self.config.world_width / SENSOR_COVERAGE_CELL_SIZE)
        rows = math.ceil(self.config.world_height / SENSOR_COVERAGE_CELL_SIZE)
        visible: list[tuple[int, int]] = []
        for column in range(columns):
            left = column * SENSOR_COVERAGE_CELL_SIZE
            x = (left + min(left + SENSOR_COVERAGE_CELL_SIZE, self.config.world_width)) * 0.5
            for row in range(rows):
                top = row * SENSOR_COVERAGE_CELL_SIZE
                y = (top + min(top + SENSOR_COVERAGE_CELL_SIZE, self.config.world_height)) * 0.5
                if sensor_covers(agent, self.world, pose, (x, y)):
                    visible.append((column, row))
        return tuple(visible)

    def _sensor_coverage_snapshot(self) -> list[dict[str, Any]]:
        coverage: list[dict[str, Any]] = []
        for agent_id in self.agent_ids:
            local = self.local_sensor_coverage[agent_id]
            shared = self.shared_sensor_coverage[agent_id]
            for column, row in sorted(local.keys() | shared.keys()):
                coverage.append({
                    "agent_id": agent_id,
                    "cell": [column, row],
                    "local_observed_at": local.get((column, row)),
                    "shared_observed_at": shared.get((column, row)),
                })
        return coverage

    def _refresh_protection_designations(self) -> None:
        """Update only from run-owned tracks and the protection task lifecycle."""
        for entity_id, designation in self.protection_designations.items():
            known_tracks = [
                (track.observed_at, agent_id, track)
                for agent_id, agent in self.agents.items()
                if (track := agent.tracks.get(entity_id)) is not None
            ]
            if known_tracks:
                observed_at, _, newest = max(known_tracks, key=lambda item: (item[0], item[1]))
                if observed_at >= designation.last_observed_at:
                    designation.last_known_position = (newest.x, newest.y)
                    designation.last_observed_at = observed_at

            task = self.mission_tasks.get(designation.task_id)
            designation.assigned_agent_id = task.assigned_agent_id if task is not None else None
            if task is None or task.status in {"failed", "expired", "cancelled"}:
                designation.status = "inactive"
                if task is not None and task.status in {"failed", "expired"} and task.definition.task_id not in self._protection_terminal_events:
                    self._protection_terminal_events.add(task.definition.task_id)
                    self.observation_events.append(self._event(
                        step=self.step,
                        event_type="entity_protection_monitoring_missed",
                        entity_id=entity_id,
                        details=json.dumps({
                            "task_id": task.definition.task_id,
                            "reason": task.failure_reason or task.status,
                        }, sort_keys=True, separators=(",", ":")),
                    ))
                continue
            owner = self.agents.get(task.assigned_agent_id or "")
            local_track = owner.tracks.get(entity_id) if owner is not None else None
            actively_observed = (
                owner is not None
                and local_track is not None
                and local_track.source_agent_id == owner.agent_id
                and self.step - local_track.observed_at <= self.config.max_track_age_steps
                and math.dist(owner.vehicle.position, (local_track.x, local_track.y)) <= designation.radius
            )
            designation.status = "monitored" if actively_observed else "caution"

    def _designate_entity_protection(
        self,
        entity_id: str,
        radius: float,
        zone_type: str,
    ) -> tuple[EntityProtection, str]:
        valid_entities = {entity.entity_id for entity in self.world.evaluator_snapshot()}
        if entity_id not in valid_entities:
            raise ValueError("unknown_entity")
        if zone_type not in {"monitoring", "protection"}:
            raise ValueError("zone_type_must_be_monitoring_or_protection")
        if not math.isfinite(radius) or radius <= 0.0 or radius > max(self.world.width, self.world.height):
            raise ValueError("radius_must_be_positive_and_within_world_scale")
        known_tracks = [
            (track.observed_at, agent_id, track)
            for agent_id, agent in self.agents.items()
            if (track := agent.tracks.get(entity_id)) is not None
            and self.step - track.observed_at <= self.config.max_track_age_steps
        ]
        if not known_tracks:
            raise ValueError("entity_must_have_a_fresh_known_track")
        observed_at, _, newest = max(known_tracks, key=lambda item: (item[0], item[1]))
        position = (newest.x, newest.y)

        existing = self.protection_designations.get(entity_id)
        existing_task = self.mission_tasks.get(existing.task_id) if existing else None
        if existing_task is not None and existing_task.status in {"unassigned", "assigned", "navigating", "executing", "reassigned"}:
            existing_task.definition = replace(
                existing_task.definition,
                location=position,
                priority=100 if zone_type == "protection" else 5,
                completion_criteria={
                    **existing_task.definition.completion_criteria,
                    "radius": radius,
                },
            )
            task_id = existing_task.definition.task_id
            event_kind = "updated"
        else:
            base_task_id = f"protection-{entity_id}"
            task_id = base_task_id
            suffix = 2
            while task_id in self.mission_tasks:
                task_id = f"{base_task_id}-{suffix}"
                suffix += 1
            task = create_monitoring_task(entity_id, position, radius, self.config.steps, zone_type)
            if task_id != base_task_id:
                task.definition = replace(task.definition, task_id=task_id)
            self.mission_tasks[task_id] = task
            self.protection_task_ids.append(task_id)
            event_kind = "created" if existing is None else "updated"

        designation = EntityProtection(
            entity_id=entity_id,
            radius=radius,
            zone_type=zone_type,
            mission_id=self.mission_id,
            task_id=task_id,
            designated_at=self.step,
            last_known_position=position,
            last_observed_at=observed_at,
        )
        self.protection_designations[entity_id] = designation
        self.observation_events.append(self._event(
            step=self.step,
            event_type=f"entity_protection_zone_{event_kind}",
            entity_id=entity_id,
            details=json.dumps(designation.to_dict(), sort_keys=True, separators=(",", ":")),
        ))
        self.assign_pending_mission_tasks()
        self.run_autonomous_behaviors()
        self._refresh_protection_designations()
        return designation, event_kind

    def assign_destination(
        self,
        agent_id: str,
        destination: tuple[float, float],
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Plan and assign a validated route through the authoritative world."""
        agent = self.agents.get(agent_id)
        if agent is None:
            raise ValueError(f"unknown agent '{agent_id}'")
        mission_task = self.mission_tasks.get(task_id or "")
        if mission_task is not None:
            if mission_task.assigned_agent_id != agent_id:
                raise ValueError(f"mission task '{task_id}' is assigned to a different agent")
            if mission_task.status not in {"assigned", "navigating"}:
                raise ValueError(f"mission task '{task_id}' cannot navigate from status '{mission_task.status}'")
        path = agent.set_destination(destination, self.world, task_id, self.path_planner)
        if path is None:
            outcome: dict[str, Any] = {
                "agent_id": agent_id,
                "destination": list(destination),
                "status": "unreachable",
                "task_id": task_id,
            }
            self.observation_events.append(self._event(
                step=self.step,
                event_type="uav_destination_unreachable",
                sender_id=agent_id,
                details=json.dumps(outcome, sort_keys=True, separators=(",", ":")),
            ))
            if mission_task is not None:
                self.observation_events.append(self.task_state_machine.transition(
                    mission_task,
                    "failed",
                    self.step,
                    agent_id=agent_id,
                    details={"reason": "route_unreachable"},
                ))
                self._release_task_vehicle(task_id or "", agent_id, stop_route=False)
            return outcome
        if mission_task is not None and mission_task.status == "assigned":
            self.observation_events.append(self.task_state_machine.transition(
                mission_task,
                "navigating",
                self.step,
                agent_id=agent_id,
                details={"reason": "route_planned", "destination": list(destination)},
            ))
        outcome = {
            "agent_id": agent_id,
            "destination": list(destination),
            "status": "navigating",
            "task_id": task_id,
            "waypoints": [list(point) for point in path.waypoints],
            "planned_distance": path.total_distance,
            "expanded_nodes": path.expanded_nodes,
        }
        self.observation_events.append(self._event(
            step=self.step,
            event_type="uav_route_planned",
            sender_id=agent_id,
            details=json.dumps(outcome, sort_keys=True, separators=(",", ":")),
        ))
        return outcome

    def cancel_mission_task(self, task_id: str) -> dict[str, Any]:
        """Cancel an open task and release its UAV route, if any."""
        if self.finished:
            raise ValueError("run is already finalized")
        task = self.mission_tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown mission task '{task_id}'")
        event = self.task_state_machine.transition(
            task, "cancelled", self.step, details={"reason": "cancelled_by_commander"},
        )
        self._release_task_vehicle(task_id, task.assigned_agent_id, stop_route=True)
        self.observation_events.append(event)
        return event

    def reassign_mission_task(self, task_id: str, new_agent_id: str) -> list[dict[str, Any]]:
        """Move an active assignment to a validated, available UAV."""
        if self.finished:
            raise ValueError("run is already finalized")
        task = self.mission_tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown mission task '{task_id}'")
        if task.status not in ACTIVE_TASK_STATUSES:
            raise ValueError(f"mission task '{task_id}' is not active")
        if self.network.communication_state(self.step) == "partitioned":
            raise ValueError("mission task reassignment is unavailable during a communication partition")
        new_agent = self.agents.get(new_agent_id)
        if new_agent is None:
            raise ValueError(f"unknown agent '{new_agent_id}'")
        if new_agent_id == task.assigned_agent_id:
            raise ValueError("mission task is already assigned to that agent")
        if new_agent.vehicle.status not in {"available", "arrived"} or new_agent.vehicle.current_task_id is not None:
            raise ValueError(f"agent '{new_agent_id}' is busy or unavailable")
        if not set(task.definition.required_capabilities).issubset(new_agent.capabilities):
            raise ValueError(f"agent '{new_agent_id}' lacks a required task capability")

        destination = _mission_task_destination(task.definition.location, task.definition.region)
        route = self.path_planner.plan(new_agent.vehicle.position, destination, self.world, new_agent_id)
        if route is None:
            raise ValueError(f"agent '{new_agent_id}' cannot reach mission task '{task_id}'")
        travel_steps = _estimate_task_travel_steps(new_agent, route)
        if self.step + travel_steps + task.definition.estimated_duration_steps > task.definition.deadline_step:
            raise ValueError(f"agent '{new_agent_id}' cannot meet mission task '{task_id}' deadline")
        recovery_distance = _mission_recovery_distance(destination, self.world, self.path_planner)
        required_energy = (
            route.total_distance + recovery_distance
        ) * new_agent.vehicle.motion_config.energy_per_distance
        if float(new_agent.vehicle.battery_remaining or 0.0) + 1e-9 < required_energy:
            raise ValueError(f"agent '{new_agent_id}' lacks energy reserve for mission task '{task_id}'")

        old_agent_id = task.assigned_agent_id
        events = [self.task_state_machine.transition(
            task,
            "reassigned",
            self.step,
            details={"reason": "commander_reassignment", "previous_agent_id": old_agent_id, "new_agent_id": new_agent_id},
        )]
        self._release_task_vehicle(task_id, old_agent_id, stop_route=True)
        new_agent.vehicle.current_task_id = task_id
        events.append(self.task_state_machine.transition(
            task,
            "assigned",
            self.step,
            agent_id=new_agent_id,
            details={
                "reason": "reassigned",
                "previous_agent_id": old_agent_id,
                "estimated_completion_step": self.step + travel_steps + task.definition.estimated_duration_steps,
                "estimated_travel_steps": travel_steps,
                "energy_budget_required": required_energy,
                "destination": list(destination),
            },
        ))
        self.observation_events.extend(events)
        return events

    def _release_task_vehicle(
        self,
        task_id: str,
        agent_id: str | None,
        *,
        stop_route: bool,
    ) -> None:
        agent = self.agents.get(agent_id or "")
        if agent is None or agent.vehicle.current_task_id != task_id:
            return
        vehicle = agent.vehicle
        vehicle.current_task_id = None
        if stop_route:
            vehicle.destination = None
            vehicle.final_destination = None
            vehicle.route_waypoints.clear()
            vehicle.speed = 0.0
            if vehicle.status not in {"unavailable", "unreachable"}:
                vehicle.status = "available"

    def run_autonomous_behaviors(self) -> list[dict[str, Any]]:
        """Apply policy commands at the current logical tick without advancing time."""
        if self.finished or self.step >= self.config.steps:
            return []
        communication_available = self.network.communication_state(self.step) != "partitioned"
        self.behavior_policy.reassign_unavailable(self, communication_available)
        outcomes: list[dict[str, Any]] = []
        for command in self.behavior_policy.plan(self):
            if command.action == "navigate_to_task":
                outcomes.append(self.assign_destination(
                    command.agent_id,
                    command.destination,
                    command.task_id,
                ))
            elif command.action == "return_to_recovery":
                outcome = self.assign_destination(command.agent_id, command.destination)
                if outcome.get("status") == "navigating":
                    agent = self.agents[command.agent_id]
                    agent.recovery_target = command.destination
                    self.observation_events.append(self._event(
                        step=self.step,
                        event_type="uav_recovery_started",
                        sender_id=command.agent_id,
                        details=json.dumps({
                            "destination": list(command.destination),
                            **(command.details or {}),
                        }, sort_keys=True, separators=(",", ":")),
                    ))
                outcomes.append(outcome)
        return outcomes

    def assign_pending_mission_tasks(self) -> list[dict[str, object]]:
        """Run the centralized nearest-feasible-agent mission allocator once."""
        assignments = self.task_allocator.assign_pending(
            self.mission_tasks,
            self.agents,
            self.world,
            self.path_planner,
            self.step,
            communication_available=self.network.communication_state(self.step) != "partitioned",
        )
        for assignment in assignments:
            event = self._event(
                step=int(assignment["step"]),
                event_type=str(assignment["event_type"]),
                details=str(assignment["details"]),
                resource_id=str(assignment["resource_id"]),
            )
            event.update({
                "task_id": assignment["task_id"],
                "task_type": assignment["task_type"],
                "deadline": assignment["deadline"],
                "priority": assignment["priority"],
            })
            self.observation_events.append(event)
        return assignments

    def _apply_local_report(
        self,
        agent: Agent,
        observation: Observation,
        recipient_ids: tuple[str, ...],
    ) -> str:
        outcome = self._apply_report(agent, observation)
        if self.mode == "cooperative":
            self.network.publish(
                agent.agent_id,
                recipient_ids,
                observation,
                self.step,
                sender_position=agent.vehicle.position,
                recipient_positions={
                    recipient_id: self.agents[recipient_id].vehicle.position
                    for recipient_id in recipient_ids
                    if recipient_id in self.agents
                },
            )
        return outcome

    def _receive_message(self, envelope: Envelope) -> str:
        if envelope.protocol_version != MESSAGE_PROTOCOL_VERSION:
            return "unsupported_message_version"
        if envelope.message_type != "observation":
            return "unsupported_message_type"
        recipient = self.agents.get(envelope.recipient_id)
        if recipient is None:
            return "unknown_recipient"
        if not recipient.reserve_message_id(envelope.message_id):
            return "duplicate"
        accepted = self._enqueue_decision(
            task_type="received-report",
            step=self.step,
            information_time=envelope.observation.observed_at,
            action=lambda target=recipient, report=envelope.observation: self._apply_report(target, report),
        )
        return "queued" if accepted else "queue_overload"

    def advance_tick(self) -> dict[str, object]:
        """Advance exactly one authoritative engine tick and return its snapshot."""
        if self.finished:
            raise RuntimeError("run is already finalized")
        if self.step >= self.config.steps:
            self.finalize()
            raise RuntimeError("configured simulation horizon has been reached")

        from .runner import _simulation_snapshot

        step = self.step + 1
        self.step = step
        self.scheduler.expire_before(step)
        self.world.advance()
        coverage_this_step: dict[str, tuple[tuple[int, int], ...]] = {}
        for agent_id, agent in self.agents.items():
            motion = agent.advance_motion(self.world)
            agent.pose_history.append((step, agent.x, agent.y, agent.heading_rad))
            pose = agent.pose_history[-1]
            self._record_mission_area_pose(agent, pose)
            if self.enable_presentation_coverage:
                coverage_cells = self._sensor_coverage_for_pose(agent, pose)
                coverage_this_step[agent_id] = coverage_cells
                for cell in coverage_cells:
                    self.local_sensor_coverage[agent_id][cell] = step
            if motion is not None:
                event_type = {
                    "arrived": "uav_arrived",
                    "blocked": "uav_navigation_blocked",
                    "unavailable": "uav_energy_depleted",
                }.get(motion.status, "uav_moved")
                self.observation_events.append(self._event(
                    step=step,
                    event_type=event_type,
                    sender_id=agent_id,
                    details=json.dumps(motion.to_dict(), separators=(",", ":")),
                ))
                if motion.distance_moved > 0.0:
                    for zone_id, transition, behavior, authorized in self.world.geometry.restricted_zone_transitions(
                        motion.previous_position, motion.position, agent_id,
                    ):
                        warning = behavior == "warn" and transition == "entry"
                        self.observation_events.append(self._event(
                            step=step,
                            event_type=(
                                "restricted_zone_violation" if warning else
                                "restricted_zone_entered" if transition == "entry" else
                                "restricted_zone_exited"
                            ),
                            sender_id=agent_id,
                            details=json.dumps({
                                "zone_id": zone_id,
                                "transition": transition,
                                "policy": behavior,
                                "authorized": authorized,
                                "from": list(motion.previous_position),
                                "to": list(motion.position),
                            }, sort_keys=True, separators=(",", ":")),
                        ))
                for zone_id in motion.denied_zone_ids:
                    self.observation_events.append(self._event(
                        step=step,
                        event_type="restricted_zone_entry_denied",
                        sender_id=agent_id,
                        details=json.dumps({
                            "zone_id": zone_id,
                            "policy": "deny_entry",
                            "attempted_from": list(motion.previous_position),
                            "attempted_to": list(motion.attempted_position or motion.position),
                        }, sort_keys=True, separators=(",", ":")),
                    ))
                if (
                    motion.status == "arrived"
                    and agent.recovery_target is not None
                    and self.world.is_in_safe_area(agent.vehicle.position)
                ):
                    recovery_target = agent.recovery_target
                    agent.recovery_target = None
                    self.observation_events.append(self._event(
                        step=step,
                        event_type="uav_recovered",
                        sender_id=agent_id,
                        details=json.dumps({"destination": list(recovery_target)}, separators=(",", ":")),
                    ))
                if motion.status == "blocked" and motion.final_destination is not None:
                    path = self.path_planner.plan(agent.vehicle.position, motion.final_destination, self.world, agent_id)
                    if path is None:
                        agent.vehicle.mark_unreachable(motion.final_destination)
                        replan_type = "uav_destination_unreachable"
                        replan_details = {
                            "agent_id": agent_id,
                            "destination": list(motion.final_destination),
                            "reason": "blocked_route_has_no_alternative",
                        }
                    else:
                        agent.vehicle.set_route(path.waypoints, motion.final_destination, self.world)
                        replan_type = "uav_route_replanned"
                        replan_details = {
                            "agent_id": agent_id,
                            "destination": list(motion.final_destination),
                            "waypoints": [list(point) for point in path.waypoints],
                            "planned_distance": path.total_distance,
                            "expanded_nodes": path.expanded_nodes,
                            "reason": "route_blocked",
                        }
                    self.observation_events.append(self._event(
                        step=step,
                        event_type=replan_type,
                        sender_id=agent_id,
                        details=json.dumps(replan_details, sort_keys=True, separators=(",", ":")),
                    ))
        network_state = self.network.communication_state(step)
        previous_network_state = self.network.communication_state(step - 1)
        if network_state != previous_network_state:
            event_type = "communication_partition_started" if network_state == "partitioned" else "communication_restored"
            self.observation_events.append(
                self._event(
                    step=step,
                    event_type=event_type,
                    details="global_simulated_partition",
                )
            )
        for agent_id, agent in self.agents.items():
            observations = self.world.observations_for(
                self.observer_by_id[agent_id],
                self.observation_model,
                step,
                observer_position=(agent.x, agent.y),
                observer_heading_rad=agent.heading_rad,
                field_of_view_degrees=agent.sensor_config.field_of_view_degrees,
                require_line_of_sight=agent.sensor_config.require_line_of_sight,
            )
            for observation in observations:
                observation = replace(
                    observation,
                    sensor_coverage_cells=coverage_this_step.get(agent_id, ()),
                )
                self.first_detection_step.setdefault(observation.entity_id, step)
                self.observation_events.append(
                    self._event(
                        step=step,
                        event_type="observation_created",
                        sender_id=agent_id,
                        recipient_id=agent_id,
                        entity_id=observation.entity_id,
                        details="queued_for_reconciliation",
                    )
                )
                recipients = tuple(other for other in self.agent_ids if other != agent_id)
                self._enqueue_decision(
                    task_type="local-observation",
                    step=step,
                    information_time=observation.observed_at,
                    action=lambda target=agent, report=observation, peers=recipients: self._apply_local_report(
                        target, report, peers
                    ),
                )

        self.network.deliver_due(step, self._receive_message)
        completed = self.scheduler.tick(step)
        for task in completed:
            action = self.actions.pop(task.task_id, None)
            result = action() if action is not None else "missing_decision_action"
            self.scheduler.record_decision_result(task, result)
        self.coordination.tick(step)
        self.network.deliver_due(step, self._receive_message)
        if self.config.partition_enabled and step >= self.partition_restore_step and self.recovery_time_steps is None:
            current_track_sets = [
                {track.entity_id for track in agent.active_tracks(step, self.config.max_track_age_steps)}
                for agent in self.agents.values()
            ]
            if current_track_sets and current_track_sets[0] and all(
                track_set == current_track_sets[0] for track_set in current_track_sets[1:]
            ):
                self.recovery_time_steps = step - self.partition_restore_step
        if self.network.communication_state(step) == "partitioned":
            partition_tracks = {
                agent_id: agent.active_tracks(step, self.config.max_track_age_steps)
                for agent_id, agent in self.agents.items()
            }
            known_during_partition = {
                track.entity_id for tracks in partition_tracks.values() for track in tracks
            }
            self.partition_team_coverage_samples.append(len(known_during_partition) / self.config.entity_count)
            self.partition_agent_coverage_samples.append(
                statistics.fmean(len(tracks) / self.config.entity_count for tracks in partition_tracks.values())
            )

        communication_available = self.network.communication_state(step) != "partitioned"
        self.behavior_policy.reassign_unavailable(self, communication_available)
        lifecycle_events = self.task_state_machine.advance(
            self.mission_tasks,
            self.agents,
            self.world,
            step,
            communication_available=communication_available,
        )
        self.observation_events.extend(lifecycle_events)
        for event in lifecycle_events:
            if str(event["event_type"]) in {
                "mission_task_completed", "mission_task_failed", "mission_task_expired", "mission_task_cancelled",
            }:
                self._release_task_vehicle(str(event["task_id"]), event.get("resource_id"), stop_route=str(event["event_type"]) != "mission_task_completed")

        if any(task.status == "unassigned" for task in self.mission_tasks.values()) and any(
            agent.vehicle.status in {"available", "arrived"} and agent.vehicle.current_task_id is None
            for agent in self.agents.values()
        ):
            self.assign_pending_mission_tasks()
        self.run_autonomous_behaviors()
        self._refresh_protection_designations()

        snapshot = _simulation_snapshot(self.world, self.agents)
        if self.protection_designations:
            snapshot["protection_zones"] = [
                designation.to_dict()
                for designation in self.protection_designations.values()
            ]
        presentation_snapshot = _simulation_snapshot(
            self.world,
            self.agents,
            include_presentation_state=True,
        )
        if self.enable_presentation_coverage:
            presentation_snapshot["sensor_coverage_cell_size"] = SENSOR_COVERAGE_CELL_SIZE
            presentation_snapshot["sensor_coverage_cells"] = self._sensor_coverage_snapshot()
        if self.protection_designations:
            presentation_snapshot["protection_zones"] = [
                designation.to_dict()
                for designation in self.protection_designations.values()
            ]
        self.trace_events.append(
            self._event(
                step=step,
                event_type="simulation_snapshot",
                details=json.dumps(snapshot, separators=(",", ":")),
            )
        )
        if step >= self.config.steps:
            self.finalize()
        return presentation_snapshot

    def apply_intervention(self, action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Validate and record a small engine-supported coordination intervention."""
        entry: dict[str, Any] = {
            "step": self.step,
            "action": action,
            "parameters": parameters,
            "accepted": False,
            "outcome": "",
        }
        if self.finished:
            entry["outcome"] = "run_already_finalized"
        elif (
            action == "set_scheduler_policy"
            and set(parameters) == {"policy"}
            and isinstance(parameters.get("policy"), str)
            and parameters.get("policy") in {"fixed-priority", "edf"}
        ):
            self.policy = str(parameters["policy"])
            self.scheduler.policy = self.policy
            entry["accepted"] = True
            entry["outcome"] = f"scheduler_policy_changed_to_{self.policy}"
        elif action == "set_scheduler_policy":
            entry["outcome"] = "policy_must_be_fixed-priority_or_edf"
        elif action == "set_uav_destination":
            if set(parameters) != {"agent_id", "destination"}:
                entry["outcome"] = "agent_id_and_destination_are_required"
            else:
                agent_id = parameters.get("agent_id")
                raw_destination = parameters.get("destination")
                agent = self.agents.get(agent_id) if isinstance(agent_id, str) else None
                if agent is None:
                    entry["outcome"] = "unknown_agent"
                elif not isinstance(raw_destination, (list, tuple)) or len(raw_destination) != 2:
                    entry["outcome"] = "destination_must_contain_finite_x_and_y"
                elif any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw_destination):
                    entry["outcome"] = "destination_must_contain_finite_x_and_y"
                else:
                    destination = (float(raw_destination[0]), float(raw_destination[1]))
                    if not all(math.isfinite(value) for value in destination):
                        entry["outcome"] = "destination_must_contain_finite_x_and_y"
                    elif agent.vehicle.current_task_id is not None or agent.recovery_target is not None:
                        entry["outcome"] = "uav_has_an_active_mission_assignment"
                    elif agent.vehicle.status not in {"available", "arrived"}:
                        entry["outcome"] = f"uav_status_{agent.vehicle.status}_cannot_accept_destination"
                    elif not self.world.is_navigable(destination, agent_id):
                        entry["outcome"] = "destination_is_out_of_bounds_or_blocked"
                    elif self.path_planner.plan(agent.vehicle.position, destination, self.world, agent_id) is None:
                        entry["outcome"] = "destination_is_unreachable"
                    else:
                        command_result = self.assign_destination(agent_id, destination)
                        entry["accepted"] = command_result.get("status") == "navigating"
                        entry["outcome"] = "destination_route_planned" if entry["accepted"] else "destination_is_unreachable"
                        entry["result"] = command_result
        elif action == "reassign_mission_task":
            if set(parameters) != {"task_id", "agent_id"}:
                entry["outcome"] = "task_id_and_agent_id_are_required"
            elif not all(isinstance(parameters.get(key), str) and parameters[key] for key in ("task_id", "agent_id")):
                entry["outcome"] = "task_id_and_agent_id_must_be_non_empty_strings"
            else:
                try:
                    transitions = self.reassign_mission_task(
                        str(parameters["task_id"]), str(parameters["agent_id"]),
                    )
                except ValueError as error:
                    entry["outcome"] = str(error)
                else:
                    self.run_autonomous_behaviors()
                    entry["accepted"] = True
                    entry["outcome"] = "mission_task_reassigned_and_route_dispatched"
                    entry["result"] = transitions
        elif action == "designate_entity_protection":
            if set(parameters) != {"entity_id", "radius", "zone_type"}:
                entry["outcome"] = "entity_id_radius_and_zone_type_are_required"
            elif not isinstance(parameters.get("entity_id"), str) or not parameters["entity_id"]:
                entry["outcome"] = "entity_id_must_be_a_non_empty_string"
            elif isinstance(parameters.get("radius"), bool) or not isinstance(parameters.get("radius"), (int, float)):
                entry["outcome"] = "radius_must_be_positive_and_finite"
            elif not math.isfinite(float(parameters["radius"])):
                entry["outcome"] = "radius_must_be_positive_and_finite"
            elif not isinstance(parameters.get("zone_type"), str):
                entry["outcome"] = "zone_type_must_be_monitoring_or_protection"
            else:
                try:
                    designation, event_kind = self._designate_entity_protection(
                        str(parameters["entity_id"]),
                        float(parameters["radius"]),
                        str(parameters["zone_type"]),
                    )
                except ValueError as error:
                    entry["outcome"] = str(error)
                else:
                    entry["accepted"] = True
                    entry["outcome"] = f"entity_protection_zone_{event_kind}"
                    entry["result"] = designation.to_dict()
        elif action == "remove_entity_protection":
            if set(parameters) != {"entity_id"}:
                entry["outcome"] = "entity_id_is_required"
            elif not isinstance(parameters.get("entity_id"), str) or not parameters["entity_id"]:
                entry["outcome"] = "entity_id_must_be_a_non_empty_string"
            else:
                entity_id = str(parameters["entity_id"])
                designation = self.protection_designations.pop(entity_id, None)
                if designation is None:
                    entry["outcome"] = "entity_has_no_active_protection_designation"
                else:
                    task = self.mission_tasks.get(designation.task_id)
                    if task is not None and task.status in {"unassigned", "assigned", "navigating", "executing", "reassigned"}:
                        event = self.task_state_machine.transition(
                            task,
                            "cancelled",
                            self.step,
                            details={"reason": "protection_designation_removed"},
                        )
                        self.observation_events.append(event)
                        self._release_task_vehicle(designation.task_id, task.assigned_agent_id, stop_route=True)
                    self.observation_events.append(self._event(
                        step=self.step,
                        event_type="entity_protection_zone_removed",
                        entity_id=entity_id,
                        details=json.dumps(designation.to_dict(), sort_keys=True, separators=(",", ":")),
                    ))
                    entry["accepted"] = True
                    entry["outcome"] = "entity_protection_zone_removed"
                    entry["result"] = designation.to_dict()
        else:
            entry["outcome"] = "unsupported_intervention"
        self.interventions.append(entry)
        self.observation_events.append(
            self._event(
                step=self.step,
                event_type="player_intervention_accepted" if entry["accepted"] else "player_intervention_rejected",
                details=json.dumps(entry, sort_keys=True, separators=(",", ":")),
            )
        )
        return entry

    def live_metrics(self) -> dict[str, Any]:
        horizon = self.config.steps
        active_by_agent = {
            agent_id: agent.active_tracks(self.step, self.config.max_track_age_steps)
            for agent_id, agent in self.agents.items()
        }
        all_known = {track.entity_id for tracks in active_by_agent.values() for track in tracks}
        entity_count = self.config.entity_count
        statuses = [task.status for task in self.scheduler.tasks]
        active_deadline_tasks = [
            task for task in self.scheduler.tasks if task.status in {"queued", "running"}
        ]
        deadline_slacks = [task.deadline - self.step for task in active_deadline_tasks]
        metrics = {
            "any_agent_awareness_coverage": len(all_known) / entity_count if entity_count else 0.0,
            "mean_agent_track_coverage": (
                statistics.fmean(len(tracks) / entity_count for tracks in active_by_agent.values())
                if active_by_agent and entity_count else 0.0
            ),
            "agent_track_coverage": {
                agent_id: len(tracks) / entity_count if entity_count else 0.0
                for agent_id, tracks in active_by_agent.items()
            },
            "mean_fresh_track_age_steps": (
                statistics.fmean(self.step - track.observed_at for tracks in active_by_agent.values() for track in tracks)
                if any(active_by_agent.values()) else None
            ),
            "messages_sent": self.network.sent_originals,
            "messages_delivered": self.network.delivered_originals,
            "messages_dropped": self.network.dropped_originals,
            "pending_messages": self.network.pending_messages,
            "communication_status": (
                "peer_sharing_disabled"
                if self.mode == "independent"
                else self.network.communication_state(self.step)
            ),
            "queue_backlog_tasks": self.scheduler.active_task_count,
            "queue_capacity": self.scheduler.queue_capacity,
            "urgent_deadline_tasks": sum(0 <= slack <= 2 for slack in deadline_slacks),
            "next_deadline_slack_steps": min(deadline_slacks) if deadline_slacks else None,
            "decision_tasks_created": len(self.scheduler.tasks),
            "decision_tasks_completed": statuses.count("completed"),
            "decision_tasks_expired": statuses.count("expired"),
            "decision_tasks_dropped": statuses.count("dropped"),
            "eligible_tasks": self.scheduler.eligible_task_count(self.step),
            "deadline_misses": self.scheduler.deadline_miss_count(self.step),
            "deadline_miss_rate": (
                self.scheduler.deadline_miss_count(self.step) / self.scheduler.eligible_task_count(self.step)
                if self.scheduler.eligible_task_count(self.step) else None
            ),
            "coordination": self.coordination.metrics(),
            "recovery_time_steps": self.recovery_time_steps,
            "configured_horizon_steps": horizon,
            **self._network_behavior_metrics(),
            **self._partition_metrics(),
        }
        metrics.update(self._mission_metrics(self.step))
        return metrics

    def _mission_metrics(self, current_step: int) -> dict[str, Any]:
        """Metrics for spatial mission tasks and physical UAV behavior.

        Legacy decision-queue task metrics remain separate and retain their
        existing names and definitions.
        """
        if not self.mission_tasks:
            return {}
        tasks = list(self.mission_tasks.values())
        completed = [task for task in tasks if task.status == "completed"]
        due_tasks = [task for task in tasks if task.definition.deadline_step < current_step]
        missed_deadlines = [
            task for task in due_tasks
            if task.completed_at is None or task.completed_at > task.definition.deadline_step
        ]
        sampled_area = sum(len(points) for points in self.mission_area_points_by_task.values())
        covered_area = sum(len(indices) for indices in self.mission_area_covered_indices_by_task.values())
        observations_by_entity_step: dict[tuple[str, int], int] = {}
        observation_report_count = 0
        for event in self.observation_events:
            if event.get("event_type") != "observation_created":
                continue
            key = (str(event.get("entity_id", "")), int(event.get("step", 0)))
            observations_by_entity_step[key] = observations_by_entity_step.get(key, 0) + 1
            observation_report_count += 1
        overlapping_reports = sum(max(0, count - 1) for count in observations_by_entity_step.values())
        distance_by_agent = {
            agent_id: agent.vehicle.distance_travelled
            for agent_id, agent in self.agents.items()
        }
        energy_by_agent = {
            agent_id: max(
                0.0,
                agent.vehicle.motion_config.battery_capacity - float(agent.vehicle.battery_remaining or 0.0),
            )
            for agent_id, agent in self.agents.items()
        }
        all_tasks_completed = bool(tasks) and len(completed) == len(tasks)
        assignment_events = sum(
            1 for task in tasks for event in task.event_history
            if event.get("event_type") == "mission_task_assigned"
        )
        reassignment_events = sum(
            1 for task in tasks for event in task.event_history
            if event.get("event_type") == "mission_task_reassigned"
        )
        completed_durations = [
            task.completed_at - (task.assigned_at if task.assigned_at is not None else 0)
            for task in completed if task.completed_at is not None
        ]
        return {
            "mission_task_count": len(tasks),
            "mission_tasks_completed": len(completed),
            "mission_tasks_failed": sum(task.status == "failed" for task in tasks),
            "mission_tasks_expired": sum(task.status == "expired" for task in tasks),
            "mission_tasks_cancelled": sum(task.status == "cancelled" for task in tasks),
            "mission_task_completion_rate": len(completed) / len(tasks),
            "mission_deadline_eligible_tasks": len(due_tasks),
            "mission_task_deadline_misses": len(missed_deadlines),
            "mission_task_deadline_miss_rate": (
                len(missed_deadlines) / len(due_tasks) if due_tasks else None
            ),
            "mission_completion_time_steps": (
                max(int(task.completed_at) for task in tasks if task.completed_at is not None)
                if all_tasks_completed else None
            ),
            "mission_mean_task_completion_time_steps": (
                statistics.fmean(completed_durations) if completed_durations else None
            ),
            "time_to_first_observation_steps": min(self.first_detection_step.values()) if self.first_detection_step else None,
            "unique_entities_observed": len(self.first_detection_step),
            "mission_area_covered_sample_points": covered_area,
            "mission_area_sample_points": sampled_area,
            "mission_area_coverage_fraction": covered_area / sampled_area if sampled_area else None,
            "total_uav_distance_travelled": sum(distance_by_agent.values()),
            "uav_distance_by_agent": distance_by_agent,
            "uav_energy_consumed": sum(energy_by_agent.values()),
            "uav_energy_consumed_by_agent": energy_by_agent,
            "observation_reports_total": observation_report_count,
            "overlapping_observation_reports": overlapping_reports,
            "overlapping_observation_report_rate": (
                overlapping_reports / observation_report_count if observation_report_count else None
            ),
            "shared_track_applications": len(self.observation_to_shared_application_delays_steps),
            "mean_observation_to_shared_application_delay_steps": (
                statistics.fmean(self.observation_to_shared_application_delays_steps)
                if self.observation_to_shared_application_delays_steps else None
            ),
            "mission_task_assignment_events": assignment_events,
            "mission_task_reassignment_events": reassignment_events,
            "mission_assignment_actions_per_task": (assignment_events + reassignment_events) / len(tasks),
            "entity_protection_designations": len(self.protection_task_ids),
            "entity_protection_tasks_completed": sum(
                self.mission_tasks[task_id].status == "completed"
                for task_id in self.protection_task_ids if task_id in self.mission_tasks
            ),
            "entity_protection_task_completion_rate": (
                sum(self.mission_tasks[task_id].status == "completed"
                    for task_id in self.protection_task_ids if task_id in self.mission_tasks)
                / len(self.protection_task_ids)
                if self.protection_task_ids else None
            ),
            "entity_protection_currently_monitored": sum(
                zone.status == "monitored" for zone in self.protection_designations.values()
            ),
            "entity_protection_monitoring_missed": sum(
                self.mission_tasks[task_id].status in {"failed", "expired"}
                for task_id in self.protection_task_ids if task_id in self.mission_tasks
            ),
        }

    def pending_message_details(self) -> list[dict[str, Any]]:
        """Return actual queued message routes for presentation without exposing envelopes."""
        return [
            {
                "message_id": envelope.message_id,
                "sender_id": envelope.sender_id,
                "recipient_id": envelope.recipient_id,
                "entity_id": envelope.observation.entity_id,
                "sent_step": envelope.sent_step,
                "delivery_step": envelope.delivery_step,
                "copy_index": envelope.copy_index,
                "attempt": envelope.attempt,
                "protocol_version": envelope.protocol_version,
                "message_type": envelope.message_type,
                "valid_until_step": envelope.valid_until_step,
                "provenance": envelope.provenance,
            }
            for envelope in sorted(
                self.network._queue,
                key=lambda item: (item.sent_step, item.message_id, item.copy_index),
            )
        ]

    def snapshot(self) -> dict[str, Any]:
        from .runner import _simulation_snapshot

        world_snapshot = _simulation_snapshot(self.world, self.agents, include_presentation_state=True)
        if self.enable_presentation_coverage:
            world_snapshot["sensor_coverage_cell_size"] = SENSOR_COVERAGE_CELL_SIZE
            world_snapshot["sensor_coverage_cells"] = self._sensor_coverage_snapshot()
        if self.protection_designations:
            world_snapshot["protection_zones"] = [
                designation.to_dict()
                for designation in self.protection_designations.values()
            ]
        return {
            "tick": self.step,
            "status": "completed" if self.finished else "running",
            "scenario": self.config.to_dict(),
            "world": world_snapshot,
            "metrics": self.live_metrics(),
            "recent_events": self.sorted_events()[-120:],
            "presentation_events": list(self.presentation_events),
            "mission_tasks": [task.to_dict() for task in self.mission_tasks.values()],
        }

    def inspect_agent(self, agent_id: str) -> dict[str, Any] | None:
        agent = self.agents.get(agent_id)
        if agent is None:
            return None
        tracks = [
            {
                "entity_id": track.entity_id,
                "x": track.x,
                "y": track.y,
                "observed_at": track.observed_at,
                "age_steps": self.step - track.observed_at,
                "fresh": self.step - track.observed_at <= self.config.max_track_age_steps,
                "source_agent_id": track.source_agent_id,
                "confidence": track.confidence,
            }
            for track in sorted(agent.tracks.values(), key=lambda item: item.entity_id)
        ]
        pending = [
            {
                "message_id": envelope.message_id,
                "protocol_version": envelope.protocol_version,
                "message_type": envelope.message_type,
                "entity_id": envelope.observation.entity_id,
                "created_step": envelope.created_step,
                "delivery_step": envelope.delivery_step,
                "valid_until_step": envelope.valid_until_step,
                "provenance": envelope.provenance,
                "copy_index": envelope.copy_index,
                "attempt": envelope.attempt,
            }
            for envelope in self.network._queue
            if envelope.recipient_id == agent_id
        ]
        work = [
            {
                "task_id": task.task_id,
                "entity_id": task.entity_id,
                "status": task.status,
                "deadline": task.deadline,
                "deadline_slack_steps": task.deadline - self.step,
                "completes_at": task.completes_at,
            }
            for task in self.coordination.tasks
            if task.resource_id == agent_id and task.status in {"assigned", "queued"}
        ]
        mission_work: list[dict[str, object]] = []
        for mission_task in self.mission_tasks.values():
            if mission_task.assigned_agent_id != agent_id:
                continue
            task_record = mission_task.to_dict()
            task_record["deadline_slack_steps"] = mission_task.definition.deadline_step - self.step
            mission_work.append(task_record)
        return {
            "agent_id": agent.agent_id,
            "state": agent.vehicle.status,
            "position": {"x": agent.x, "y": agent.y, "heading_rad": agent.heading_rad},
            "motion": {
                "speed": agent.vehicle.speed,
                "max_speed": agent.vehicle.motion_config.max_speed,
                "battery_remaining": agent.vehicle.battery_remaining,
                "battery_capacity": agent.vehicle.motion_config.battery_capacity,
                "distance_travelled": agent.vehicle.distance_travelled,
                "destination": (
                    {"x": agent.vehicle.destination[0], "y": agent.vehicle.destination[1]}
                    if agent.vehicle.destination is not None else None
                ),
                "final_destination": (
                    {"x": agent.vehicle.final_destination[0], "y": agent.vehicle.final_destination[1]}
                    if agent.vehicle.final_destination is not None else None
                ),
                "route_waypoints": [
                    {"x": point[0], "y": point[1]} for point in agent.vehicle.route_waypoints
                ],
                "current_task_id": agent.vehicle.current_task_id,
                "recovery_target": (
                    {"x": agent.recovery_target[0], "y": agent.recovery_target[1]}
                    if agent.recovery_target is not None else None
                ),
            },
            "sensor_config": {
                "detection_range": agent.sensor_config.detection_range,
                "detection_probability": agent.sensor_config.detection_probability,
                "position_noise_std": agent.sensor_config.position_noise_std,
                "field_of_view_degrees": agent.sensor_config.field_of_view_degrees,
                "require_line_of_sight": agent.sensor_config.require_line_of_sight,
                "max_track_age_steps": agent.sensor_config.max_track_age_steps,
            },
            "locally_known_tracks": tracks,
            "track_count": len(tracks),
            "communication": {
                "mode": self.mode,
                "status": (
                    "peer_sharing_disabled"
                    if self.mode == "independent"
                    else self.network.communication_state(self.step)
                ),
                "pending_inbound_messages": len(pending),
                "pending_messages": pending,
                "last_sent_step": self._last_agent_event_step(agent_id, "message_sent"),
                "last_received_step": self._last_agent_event_step(agent_id, "message_delivered"),
            },
            "pending_work": work,
            "mission_tasks": mission_work,
            "global_decision_queue_backlog_tasks": self.scheduler.active_task_count,
            "active_task": next((task for task in work if task["status"] == "assigned"), None),
        }

    def _last_agent_event_step(self, agent_id: str, event_type: str) -> int | None:
        candidates = [
            int(event["step"])
            for event in self.network.events
            if event["event_type"] == event_type
            and agent_id in (event.get("sender_id"), event.get("recipient_id"))
        ]
        return max(candidates) if candidates else None

    def sorted_events(self) -> list[dict[str, object]]:
        events = (
            self.observation_events
            + self.network.events
            + self.scheduler.events
            + self.coordination.events
            + self.trace_events
        )
        return sorted(events, key=lambda event: int(event["step"]))

    def finalize(self, actual_steps: int | None = None) -> dict[str, Any]:
        if self.finished:
            assert self.summary is not None
            return self.summary
        horizon = self.step if actual_steps is None else actual_steps
        self.network.record_pending(horizon)
        self.scheduler.record_pending(horizon)

        truth = self.world.evaluator_snapshot()
        entity_count = len(truth)
        active_by_agent = {
            agent_id: agent.active_tracks(horizon, self.config.max_track_age_steps)
            for agent_id, agent in self.agents.items()
        }
        known_entities = {
            track.entity_id for tracks in active_by_agent.values() for track in tracks
        }
        known_entities.intersection_update({entity.entity_id for entity in truth})
        coverage_by_agent = [len(tracks) / entity_count for tracks in active_by_agent.values()]
        track_ages = [
            horizon - track.observed_at
            for tracks in active_by_agent.values()
            for track in tracks
        ]
        completed_tasks = [task for task in self.scheduler.tasks if task.status == "completed"]
        decision_latencies = [
            task.completed_at - task.created_at
            for task in completed_tasks if task.completed_at is not None
        ]
        information_ages = [
            task.completed_at - task.information_time
            for task in completed_tasks if task.completed_at is not None
        ]
        eligible_tasks = self.scheduler.eligible_task_count(horizon)
        deadline_misses = self.scheduler.deadline_miss_count(horizon)
        effective_config = self.config.to_dict()
        effective_config["scheduler_policy"] = self.policy
        summary: dict[str, Any] = {
            "project": "SwarmShield",
            "mode": self.mode,
            "scheduler_policy": self.policy,
            "seed": self.config.seed,
            "steps": horizon,
            "configuration": effective_config,
            "metrics": {
                "any_agent_awareness_coverage": len(known_entities) / entity_count,
                "mean_agent_track_coverage": statistics.fmean(coverage_by_agent) if coverage_by_agent else 0.0,
                "mean_track_age_steps": statistics.fmean(track_ages) if track_ages else None,
                "mean_first_detection_delay_steps": statistics.fmean(self.first_detection_step.values()) if self.first_detection_step else None,
                "entities_never_detected": entity_count - len(self.first_detection_step),
                "entities_in_protected_zone": self.world.evaluator_zone_count(),
                "messages_sent": self.network.sent_originals,
                "messages_delivered": self.network.delivered_originals,
                "messages_dropped": self.network.dropped_originals,
                "message_delivery_ratio": self.network.delivered_originals / self.network.sent_originals if self.network.sent_originals else None,
                "duplicate_copies_scheduled": self.network.duplicate_copies_scheduled,
                "duplicate_copies_delivered": self.network.duplicate_copies_delivered,
                "duplicates_rejected": self.network.duplicates_rejected,
                "duplicate_rejection_rate": self.network.duplicates_rejected / self.network.duplicate_copies_delivered if self.network.duplicate_copies_delivered else None,
                "dropped_duplicate_copies": self.network.dropped_duplicate_copies,
                "pending_messages": self.network.pending_messages,
                "pending_original_messages": self.network.pending_original_messages,
                "pending_duplicate_copies": self.network.pending_duplicate_copies,
                "mean_message_latency_steps": statistics.fmean(self.network.delivered_latencies) if self.network.delivered_latencies else None,
                "decision_tasks_created": len(self.scheduler.tasks),
                "decision_tasks_completed": len(completed_tasks),
                "decision_tasks_expired": sum(task.status == "expired" for task in self.scheduler.tasks),
                "decision_tasks_dropped_overload": sum(task.status == "dropped" for task in self.scheduler.tasks),
                "decision_tasks_pending": sum(task.status == "pending_at_horizon" for task in self.scheduler.tasks),
                "eligible_tasks": eligible_tasks,
                "deadline_miss_rate": deadline_misses / eligible_tasks if eligible_tasks else None,
                "task_completion_rate": len(completed_tasks) / len(self.scheduler.tasks) if self.scheduler.tasks else None,
                "decision_latency_p50_steps": nearest_rank_percentile(decision_latencies, 50),
                "decision_latency_p95_steps": nearest_rank_percentile(decision_latencies, 95),
                "decision_latency_p99_steps": nearest_rank_percentile(decision_latencies, 99),
                "decision_latency_sample_count": len(decision_latencies),
                "mean_information_age_at_decision_steps": statistics.fmean(information_ages) if information_ages else None,
                "mean_queue_backlog_tasks": statistics.fmean(self.scheduler.backlog_by_step) if self.scheduler.backlog_by_step else 0.0,
                "max_queue_backlog_tasks": self.scheduler.max_backlog,
                "recovery_time_steps": self.recovery_time_steps,
                **self._network_behavior_metrics(),
                **self._partition_metrics(),
                **self.coordination.metrics(),
            },
        }
        summary["metrics"].update(self._mission_metrics(horizon))
        summary["metrics"]["wall_clock_runtime_seconds"] = perf_counter() - self.runtime_started
        self.summary = summary
        self.events = self.sorted_events()
        self.finished = True
        return summary

    def _partition_metrics(self) -> dict[str, float | int | None]:
        if not self.config.partition_enabled:
            return {}
        return {
            "partition_ticks_observed": len(self.partition_team_coverage_samples),
            "partition_mean_team_awareness_coverage": (
                statistics.fmean(self.partition_team_coverage_samples)
                if self.partition_team_coverage_samples else None
            ),
            "partition_mean_agent_coverage": (
                statistics.fmean(self.partition_agent_coverage_samples)
                if self.partition_agent_coverage_samples else None
            ),
        }

    def _network_behavior_metrics(self) -> dict[str, float | int | None]:
        if not any((
            self.config.communication_range is not None,
            self.config.message_queue_capacity != 10000,
            self.config.message_ttl_steps is not None,
            self.config.max_message_retries != 0,
        )):
            return {}
        return {
            "communication_range": self.config.communication_range,
            "message_queue_capacity": self.config.message_queue_capacity,
            "message_ttl_steps": self.config.message_ttl_steps,
            "max_message_retries": self.config.max_message_retries,
            "message_retry_attempts": self.network.message_retries,
            "messages_expired": self.network.expired_originals,
            "duplicate_copies_expired": self.network.expired_duplicate_copies,
        }
