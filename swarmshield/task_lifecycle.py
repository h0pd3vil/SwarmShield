"""Guarded mission-task transitions evaluated from authoritative engine state."""

from __future__ import annotations

import json
import math
from typing import Any

from .agents import Agent
from .geometry import Point, point_in_polygon
from .tasks import MissionTask
from .world import World


ACTIVE_TASK_STATUSES = frozenset({"assigned", "navigating", "executing"})
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "expired", "cancelled"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "unassigned": frozenset({"assigned", "expired", "cancelled"}),
    "assigned": frozenset({"navigating", "failed", "expired", "cancelled", "reassigned"}),
    "navigating": frozenset({"executing", "failed", "expired", "cancelled", "reassigned"}),
    "executing": frozenset({"completed", "failed", "expired", "cancelled", "reassigned"}),
    "reassigned": frozenset({"assigned", "failed", "expired", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "expired": frozenset(),
    "cancelled": frozenset(),
}


class MissionTaskStateMachine:
    """Transition mission tasks and emit events only for accepted state changes.

    Estimated duration is intentionally not consulted. Tasks expire only after
    their inclusive deadline, and complete only when one of the typed criteria
    is demonstrated by local track or pose history from the run.
    """

    def transition(
        self,
        task: MissionTask,
        target_status: str,
        step: int,
        *,
        agent_id: str | None = None,
        details: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if type(step) is not int or step < 0:
            raise ValueError("task transition step must be a non-negative integer")
        if target_status not in ALLOWED_TRANSITIONS.get(task.status, frozenset()):
            raise ValueError(f"invalid mission task transition {task.status!r} -> {target_status!r}")
        if target_status == "assigned" and not (agent_id or task.assigned_agent_id):
            raise ValueError("assigned mission tasks require an agent")
        if target_status == "completed":
            expected = str(task.definition.completion_criteria["kind"])
            if not evidence or evidence.get("criterion") != expected or evidence.get("satisfied") is not True:
                raise ValueError("task completion requires satisfied engine evidence for its criterion")
            if step > task.definition.deadline_step:
                raise ValueError("a task cannot complete after its deadline")

        previous_status = task.status
        if target_status == "assigned":
            if agent_id is not None:
                task.assigned_agent_id = agent_id
            task.assigned_at = step
            task.assignment_reason = None
        elif target_status == "executing":
            task.started_at = step
        elif target_status == "completed":
            task.completed_at = step
            task.result = dict(evidence or {})
        elif target_status == "failed":
            task.failed_at = step
            task.failure_reason = str((details or {}).get("reason", "execution_failed"))
        elif target_status == "expired":
            task.expired_at = step
        elif target_status == "cancelled":
            task.cancelled_at = step
        elif target_status == "reassigned":
            task.reassigned_at = step
            task.started_at = None

        task.status = target_status
        event_details = dict(details or {})
        event_details.setdefault("from_status", previous_status)
        event_details.setdefault("to_status", target_status)
        if evidence is not None:
            event_details["evidence"] = evidence
        event_type = {
            "assigned": "mission_task_assigned",
            "navigating": "mission_task_navigating",
            "executing": "mission_task_started",
            "completed": "mission_task_completed",
            "failed": "mission_task_failed",
            "expired": "mission_task_expired",
            "cancelled": "mission_task_cancelled",
            "reassigned": "mission_task_reassigned",
        }[target_status]
        event = {
            "step": step,
            "event_type": event_type,
            "task_id": task.definition.task_id,
            "task_type": task.definition.task_type,
            "deadline": task.definition.deadline_step,
            "priority": task.definition.priority,
            "resource_id": agent_id if agent_id is not None else task.assigned_agent_id,
            "details": json.dumps(event_details, sort_keys=True, separators=(",", ":")),
        }
        task.event_history.append(dict(event))
        return event

    def advance(
        self,
        tasks: dict[str, MissionTask],
        agents: dict[str, Agent],
        world: World,
        step: int,
        *,
        communication_available: bool = True,
    ) -> list[dict[str, Any]]:
        """Advance lifecycle states once after each engine tick's observations."""
        if type(step) is not int or step < 0:
            raise ValueError("task lifecycle step must be a non-negative integer")
        events: list[dict[str, Any]] = []
        for task_id in sorted(tasks):
            task = tasks[task_id]
            if task.status in TERMINAL_TASK_STATUSES:
                continue
            if step > task.definition.deadline_step:
                events.append(self.transition(task, "expired", step, details={"reason": "deadline_missed"}))
                continue
            failed_prerequisite = next((
                prerequisite
                for prerequisite in task.definition.prerequisites
                if tasks[prerequisite].status in {"failed", "expired", "cancelled"}
            ), None)
            if failed_prerequisite is not None:
                events.append(self.transition(
                    task, "failed", step,
                    details={"reason": "prerequisite_unavailable", "prerequisite_task_id": failed_prerequisite},
                ))
                continue
            if task.status not in ACTIVE_TASK_STATUSES:
                continue

            agent = agents.get(task.assigned_agent_id or "")
            if agent is None:
                events.append(self.transition(task, "failed", step, details={"reason": "assigned_agent_unavailable"}))
                continue
            vehicle = agent.vehicle
            if vehicle.status in {"unavailable", "unreachable"}:
                if vehicle.status == "unavailable" and not communication_available:
                    continue
                events.append(self.transition(
                    task, "failed", step,
                    details={"reason": "assigned_agent_unavailable", "vehicle_status": vehicle.status},
                ))
                continue
            if vehicle.current_task_id != task_id:
                events.append(self.transition(task, "failed", step, details={"reason": "task_ownership_lost"}))
                continue

            if task.status == "assigned" and vehicle.status == "navigating":
                events.append(self.transition(
                    task, "navigating", step, agent_id=agent.agent_id,
                    details={"reason": "route_active"},
                ))

            if task.status in {"assigned", "navigating"} and self._agent_in_execution_area(task, agent):
                if task.status == "assigned":
                    events.append(self.transition(
                        task, "navigating", step, agent_id=agent.agent_id,
                        details={"reason": "already_in_task_area"},
                    ))
                events.append(self.transition(
                    task, "executing", step, agent_id=agent.agent_id,
                    details={"reason": "entered_task_area"},
                ))

            if task.status == "navigating" and vehicle.status != "navigating":
                events.append(self.transition(
                    task, "failed", step,
                    details={"reason": "navigation_stopped", "vehicle_status": vehicle.status},
                ))
            elif task.status == "executing":
                evidence = self._completion_evidence(task, agent, world, step)
                if evidence is not None:
                    events.append(self.transition(
                        task, "completed", step, agent_id=agent.agent_id, evidence=evidence,
                    ))
        return events

    @staticmethod
    def _agent_in_execution_area(task: MissionTask, agent: Agent) -> bool:
        definition = task.definition
        position = agent.vehicle.position
        if definition.task_type == "return_to_recovery":
            target = definition.location
            assert target is not None
            return math.dist(position, target) <= float(definition.completion_criteria["arrival_radius"])
        if definition.region is not None:
            return point_in_polygon(position, definition.region)
        target = definition.location
        assert target is not None
        return math.dist(position, target) <= agent.sensor_config.detection_range

    def _completion_evidence(
        self,
        task: MissionTask,
        agent: Agent,
        world: World,
        step: int,
    ) -> dict[str, Any] | None:
        criteria = task.definition.completion_criteria
        kind = criteria["kind"]
        start = task.started_at if task.started_at is not None else step
        history = [track for track in agent.track_history if track.observed_at >= start]
        if kind == "arrive":
            target = task.definition.location
            assert target is not None
            distance = math.dist(agent.vehicle.position, target)
            radius = float(criteria["arrival_radius"])
            if distance <= radius:
                return {"criterion": kind, "satisfied": True, "distance": distance, "arrival_radius": radius}
            return None
        if kind == "observe_region":
            region = task.definition.region
            assert region is not None
            observation_ticks_inside_region = {
                pose[0]
                for pose in agent.pose_history
                if pose[0] >= start and point_in_polygon((pose[1], pose[2]), region)
            }
            local_observations = {
                (track.entity_id, track.observed_at)
                for track in history
                if track.source_agent_id == agent.agent_id and track.observed_at in observation_ticks_inside_region
            }
            required = int(criteria["minimum_observations"])
            if len(local_observations) >= required:
                return {
                    "criterion": kind,
                    "satisfied": True,
                    "observation_count": len(local_observations),
                    "required_observations": required,
                    "region_id": task.definition.task_id,
                }
            return None
        if kind == "observe_entity":
            entity_id = str(criteria["entity_id"])
            observed_ticks = {
                track.observed_at
                for track in history
                if track.entity_id == entity_id and track.source_agent_id == agent.agent_id
            }
            required = int(criteria["minimum_observations"])
            if len(observed_ticks) >= required:
                return {
                    "criterion": kind,
                    "satisfied": True,
                    "entity_id": entity_id,
                    "observation_count": len(observed_ticks),
                    "required_observations": required,
                }
            return None
        if kind == "monitor_entity":
            entity_id = str(criteria["entity_id"])
            radius = float(criteria["radius"])
            poses_by_step = {
                pose[0]: (pose[1], pose[2])
                for pose in agent.pose_history
                if pose[0] >= start
            }
            monitored_ticks = {
                track.observed_at
                for track in history
                if track.entity_id == entity_id
                and track.source_agent_id == agent.agent_id
                and track.observed_at in poses_by_step
                and math.dist(poses_by_step[track.observed_at], (track.x, track.y)) <= radius
            }
            required = int(criteria["minimum_observations"])
            if len(monitored_ticks) >= required:
                return {
                    "criterion": kind,
                    "satisfied": True,
                    "entity_id": entity_id,
                    "observation_count": len(monitored_ticks),
                    "required_observations": required,
                    "monitoring_radius": radius,
                }
            return None
        if kind == "confirm_entity":
            entity_id = str(criteria["entity_id"])
            independent_observers = {
                track.source_agent_id for track in history if track.entity_id == entity_id
            }
            required = int(criteria["minimum_observations"])
            if len(independent_observers) >= required:
                return {
                    "criterion": kind,
                    "satisfied": True,
                    "entity_id": entity_id,
                    "independent_observer_count": len(independent_observers),
                    "required_observations": required,
                }
            return None
        if kind == "cover_region":
            region = task.definition.region
            assert region is not None
            sampled_points = region_sample_points(region)
            poses = [pose for pose in agent.pose_history if pose[0] >= start]
            covered = [point for point in sampled_points if any(
                sensor_covers(agent, world, pose, point) for pose in poses
            )]
            fraction = len(covered) / len(sampled_points) if sampled_points else 0.0
            required = float(criteria["coverage_fraction"])
            if fraction + 1e-12 >= required:
                return {
                    "criterion": kind,
                    "satisfied": True,
                    "coverage_fraction": fraction,
                    "required_coverage_fraction": required,
                    "sampled_point_count": len(sampled_points),
                }
            return None
        raise ValueError(f"unsupported completion criterion '{kind}'")


def region_sample_points(region: tuple[Point, ...], spacing: float = 2.0) -> tuple[Point, ...]:
    min_x = min(point[0] for point in region)
    max_x = max(point[0] for point in region)
    min_y = min(point[1] for point in region)
    max_y = max(point[1] for point in region)
    xs = _sample_axis(min_x, max_x, spacing)
    ys = _sample_axis(min_y, max_y, spacing)
    points = tuple((x, y) for x in xs for y in ys if point_in_polygon((x, y), region))
    if points:
        return points
    center = (sum(point[0] for point in region) / len(region), sum(point[1] for point in region) / len(region))
    return (center,) if point_in_polygon(center, region) else (region[0],)


def _sample_axis(start: float, end: float, spacing: float) -> tuple[float, ...]:
    count = int(math.floor((end - start) / spacing))
    values = [start + index * spacing for index in range(count + 1)]
    if not math.isclose(values[-1], end, abs_tol=1e-9):
        values.append(end)
    return tuple(values)


def sensor_covers(agent: Agent, world: World, pose: tuple[int, float, float, float], point: Point) -> bool:
    _, x, y, heading = pose
    dx, dy = point[0] - x, point[1] - y
    distance = math.hypot(dx, dy)
    if distance > agent.sensor_config.detection_range:
        return False
    fov = agent.sensor_config.field_of_view_degrees
    if fov < 360.0:
        bearing = math.atan2(dy, dx)
        delta = math.atan2(math.sin(bearing - heading), math.cos(bearing - heading))
        if abs(delta) > math.radians(fov) / 2.0:
            return False
    if agent.sensor_config.require_line_of_sight and not world.has_line_of_sight((x, y), point):
        return False
    return True
