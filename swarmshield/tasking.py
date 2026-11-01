"""Deterministic centralized assignment for spatial mission tasks."""

from __future__ import annotations

import math

from .agents import Agent
from .navigation import GridPathPlanner, PathResult
from .task_lifecycle import MissionTaskStateMachine
from .tasks import MissionTask
from .world import World


class CentralizedTaskAllocator:
    """Assign each pending task to its nearest feasible capable UAV.

    Mission task assignment is distinct from the abstract coordination review
    manager. This baseline reads the authoritative run state and assigns at most
    one active mission task per UAV.
    """

    ACTIVE_STATUSES = frozenset({"assigned", "navigating", "executing"})

    def __init__(self) -> None:
        self.state_machine = MissionTaskStateMachine()

    def assign_pending(
        self,
        tasks: dict[str, MissionTask],
        agents: dict[str, Agent],
        world: World,
        planner: GridPathPlanner,
        step: int,
        *,
        communication_available: bool = True,
    ) -> list[dict[str, object]]:
        """Assign currently feasible, prerequisite-ready unassigned tasks."""
        pending = [task for task in tasks.values() if task.status == "unassigned"]
        if not communication_available:
            for task in pending:
                task.assignment_reason = "communication_unavailable"
            return []

        pending.sort(key=lambda task: (
            -task.definition.priority,
            task.definition.deadline_step,
            task.definition.task_id,
        ))
        events: list[dict[str, object]] = []
        recovery_distance_cache: dict[tuple[tuple[float, float], tuple[str, ...]], float] = {}
        for task in pending:
            definition = task.definition
            if any(tasks[prerequisite].status != "completed" for prerequisite in definition.prerequisites):
                task.assignment_reason = "prerequisites_incomplete"
                continue

            estimates: list[tuple[int, float, str, Agent, tuple[float, float], int]] = []
            rejection_reasons: list[str] = []
            destination = _task_destination(definition.location, definition.region)
            candidates: list[tuple[int, float, str, Agent]] = []
            for agent_id in sorted(agents):
                agent = agents[agent_id]
                if not set(definition.required_capabilities).issubset(agent.capabilities):
                    rejection_reasons.append("capability_mismatch")
                    continue
                if agent.vehicle.status not in {"available", "arrived"} or agent.vehicle.current_task_id is not None:
                    rejection_reasons.append("agent_busy_or_unavailable")
                    continue
                direct_distance = math.dist(agent.vehicle.position, destination)
                lower_bound = step + math.ceil(direct_distance / agent.vehicle.motion_config.max_speed) + definition.estimated_duration_steps
                if lower_bound > definition.deadline_step:
                    rejection_reasons.append("deadline_infeasible")
                    continue
                candidates.append((lower_bound, direct_distance, agent_id, agent))

            candidates.sort(key=lambda item: (item[0], item[1], item[2]))
            for lower_bound, _, agent_id, agent in candidates:
                if estimates and lower_bound > min(item[0] for item in estimates):
                    break
                route = planner.plan(agent.vehicle.position, destination, world, agent_id)
                if route is None:
                    rejection_reasons.append("route_unreachable")
                    continue
                travel_steps = _estimate_travel_steps(agent, route)
                completion_step = step + travel_steps + definition.estimated_duration_steps
                if completion_step > definition.deadline_step:
                    rejection_reasons.append("deadline_infeasible")
                    continue

                recovery_key = (destination, world.geometry.authorized_restricted_zone_ids(agent_id))
                if recovery_key not in recovery_distance_cache:
                    recovery_distance_cache[recovery_key] = _recovery_distance(destination, world, planner, agent_id)
                required_energy = (
                    route.total_distance + recovery_distance_cache[recovery_key]
                ) * agent.vehicle.motion_config.energy_per_distance
                if float(agent.vehicle.battery_remaining or 0.0) + 1e-9 < required_energy:
                    rejection_reasons.append("insufficient_energy_reserve")
                    continue
                estimates.append((
                    completion_step,
                    required_energy,
                    agent_id,
                    agent,
                    destination,
                    travel_steps,
                ))

            if not estimates:
                task.assignment_reason = _assignment_failure_reason(rejection_reasons)
                continue

            completion_step, energy, agent_id, agent, destination, travel_steps = min(
                estimates, key=lambda item: (item[0], item[1], item[2]),
            )
            event = self.state_machine.transition(
                task,
                "assigned",
                step,
                agent_id=agent_id,
                details={
                    "estimated_completion_step": completion_step,
                    "estimated_travel_steps": travel_steps,
                    "energy_budget_required": energy,
                    "destination": list(destination),
                },
            )
            agent.vehicle.current_task_id = definition.task_id
            events.append(event)
        return events


def _task_destination(location: tuple[float, float] | None, region: tuple[tuple[float, float], ...] | None) -> tuple[float, float]:
    if location is not None:
        return location
    assert region is not None
    return (
        sum(point[0] for point in region) / len(region),
        sum(point[1] for point in region) / len(region),
    )


def _estimate_travel_steps(agent: Agent, route: PathResult) -> int:
    """Estimate travel time from acceleration and speed, plus turn overhead.

    The estimate integrates acceleration up to the configured speed cap and
    adds route-corner turn overhead. It does not model deceleration or claim to
    be an exact future trajectory.
    """
    config = agent.vehicle.motion_config
    remaining = route.total_distance
    speed = agent.vehicle.speed
    ticks = 0
    while remaining > 1e-9 and ticks < 100000:
        speed = min(config.max_speed, speed + config.acceleration)
        remaining -= min(speed, remaining)
        ticks += 1

    previous = agent.vehicle.position
    previous_heading = agent.vehicle.heading_rad
    turn_ticks = 0
    for waypoint in route.waypoints:
        dx, dy = waypoint[0] - previous[0], waypoint[1] - previous[1]
        if math.hypot(dx, dy) <= 1e-9:
            continue
        desired = math.atan2(dy, dx)
        delta = math.atan2(math.sin(desired - previous_heading), math.cos(desired - previous_heading))
        turn_ticks += math.ceil(abs(delta) / config.max_turn_rate_rad)
        previous_heading = desired
        previous = waypoint
    return ticks + turn_ticks


def _recovery_distance(
    destination: tuple[float, float],
    world: World,
    planner: GridPathPlanner,
    agent_id: str | None = None,
) -> float:
    """Estimate the shortest navigable route from a task to a recovery area."""
    return_distance = 0.0
    if world.geometry.safe_areas:
        recovery_distances = []
        for area in world.geometry.safe_areas:
            target = (
                sum(point[0] for point in area.vertices) / len(area.vertices),
                sum(point[1] for point in area.vertices) / len(area.vertices),
            )
            if world.segment_is_navigable(destination, target, agent_id):
                recovery_distances.append(math.dist(destination, target))
            else:
                route = planner.plan(destination, target, world, agent_id)
                if route is not None:
                    recovery_distances.append(route.total_distance)
        if not recovery_distances:
            return math.inf
        return_distance = min(recovery_distances)
    return return_distance


def _assignment_failure_reason(reasons: list[str]) -> str:
    if not reasons:
        return "no_eligible_agent"
    if all(reason == "capability_mismatch" for reason in reasons):
        return "capability_mismatch"
    for reason in (
        "agent_busy_or_unavailable",
        "route_unreachable",
        "insufficient_energy_reserve",
        "deadline_infeasible",
        "capability_mismatch",
    ):
        if reason in reasons:
            return reason
    return "no_eligible_agent"
