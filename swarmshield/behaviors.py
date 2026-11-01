"""Modular autonomous mission behaviors driven by authoritative session state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from .geometry import Point, point_in_polygon
from .task_lifecycle import ACTIVE_TASK_STATUSES
from .tasks import MissionTask

if TYPE_CHECKING:
    from .session import SimulationSession


@dataclass(frozen=True)
class BehaviorCommand:
    action: str
    agent_id: str
    destination: Point
    task_id: str | None = None
    details: dict[str, Any] | None = None


class MissionBehaviorPolicy(Protocol):
    """Policy contract; policies read session state and return engine commands."""

    policy_id: str

    def reassign_unavailable(self, session: "SimulationSession", communication_available: bool) -> None: ...

    def plan(self, session: "SimulationSession") -> tuple[BehaviorCommand, ...]: ...


class AssignedMissionBehavior:
    """Follow centrally assigned work, then return low-battery free UAVs safely."""

    policy_id = "assigned_mission_behavior"
    recovery_threshold = 0.20

    def reassign_unavailable(self, session: "SimulationSession", communication_available: bool) -> None:
        if not communication_available:
            return
        for task in sorted(session.mission_tasks.values(), key=lambda item: item.definition.task_id):
            if task.status not in ACTIVE_TASK_STATUSES or task.assigned_agent_id not in session.agents:
                continue
            failed_agent = session.agents[task.assigned_agent_id]
            if failed_agent.vehicle.status not in {"unavailable", "unreachable"}:
                continue
            for candidate_id in sorted(session.agents):
                if candidate_id == task.assigned_agent_id:
                    continue
                try:
                    session.reassign_mission_task(task.definition.task_id, candidate_id)
                    break
                except ValueError:
                    continue

    def plan(self, session: "SimulationSession") -> tuple[BehaviorCommand, ...]:
        commands: list[BehaviorCommand] = []
        owned_tasks = {
            task.definition.task_id: task
            for task in session.mission_tasks.values()
            if task.status in ACTIVE_TASK_STATUSES
        }
        for agent_id in sorted(session.agents):
            agent = session.agents[agent_id]
            vehicle = agent.vehicle
            if vehicle.status == "unavailable" or agent.recovery_target is not None:
                continue
            task_id = vehicle.current_task_id
            task = owned_tasks.get(task_id or "")
            if task is not None and task.assigned_agent_id == agent_id and task.status == "assigned":
                destination = _task_destination(task, agent.vehicle.position, session.world, session.path_planner, agent_id)
                if destination is not None:
                    commands.append(BehaviorCommand(
                        "navigate_to_task", agent_id, destination, task_id,
                        {"task_status": task.status, "task_priority": task.definition.priority},
                    ))
                continue
            if task_id is not None or vehicle.status not in {"available", "arrived"}:
                continue
            recovery = _recovery_destination(agent, session.world, session.path_planner)
            if recovery is not None:
                destination, route_distance, reserve_energy = recovery
                commands.append(BehaviorCommand(
                    "return_to_recovery", agent_id, destination, None,
                    {"planned_distance": route_distance, "energy_reserve": reserve_energy},
                ))
        return tuple(commands)


def _task_destination(task: MissionTask, start: Point, world: Any, planner: Any, agent_id: str | None = None) -> Point | None:
    definition = task.definition
    candidates: set[Point] = set()
    if definition.location is not None and (
        definition.region is None or point_in_polygon(definition.location, definition.region)
    ):
        candidates.add(definition.location)
    if definition.region is not None:
        region = definition.region
        min_x, max_x = min(p[0] for p in region), max(p[0] for p in region)
        min_y, max_y = min(p[1] for p in region), max(p[1] for p in region)
        x = min_x
        while x <= max_x + 1e-9:
            y = min_y
            while y <= max_y + 1e-9:
                point = (x, y)
                if point_in_polygon(point, region):
                    candidates.add(point)
                y += 2.0
            x += 2.0
        candidates.update(region)
        center = (sum(p[0] for p in region) / len(region), sum(p[1] for p in region) / len(region))
        if point_in_polygon(center, region):
            candidates.add(center)
    if not candidates and definition.location is not None:
        candidates.add(definition.location)
    routes = []
    for destination in candidates:
        route = planner.plan(start, destination, world, agent_id)
        if route is not None:
            routes.append((route.total_distance, destination[0], destination[1], destination))
    return min(routes)[-1] if routes else None


def _recovery_destination(agent: Any, world: Any, planner: Any) -> tuple[Point, float, float] | None:
    capacity = agent.vehicle.motion_config.battery_capacity
    remaining = float(agent.vehicle.battery_remaining or 0.0)
    if capacity <= 0.0 or remaining > capacity * AssignedMissionBehavior.recovery_threshold:
        return None
    if not world.geometry.safe_areas:
        return None
    candidates: set[Point] = set()
    for area in world.geometry.safe_areas:
        center = (sum(p[0] for p in area.vertices) / len(area.vertices), sum(p[1] for p in area.vertices) / len(area.vertices))
        if world.is_in_safe_area(center) and world.is_navigable(center, agent.agent_id):
            candidates.add(center)
        candidates.update(point for point in area.vertices if world.is_navigable(point, agent.agent_id))
    options = []
    for destination in candidates:
        route = planner.plan(agent.vehicle.position, destination, world, agent.agent_id)
        if route is None:
            continue
        energy = route.total_distance * agent.vehicle.motion_config.energy_per_distance
        options.append((route.total_distance, destination[0], destination[1], destination, energy))
    if not options:
        return None
    distance, _, _, destination, energy = min(options)
    if remaining + 1e-9 < energy:
        return None
    if world.is_in_safe_area(agent.vehicle.position):
        return None
    return destination, distance, energy
