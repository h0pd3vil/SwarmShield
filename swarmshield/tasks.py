"""Spatial mission-task definitions and run-owned task state records.

These records describe operational objectives; assignment and transitions are
implemented by later coordination/task-state modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from .geometry import Point, world_geometry_from_dict


TASK_TYPES = frozenset({
    "reconnaissance",
    "search",
    "confirmation",
    "coverage",
    "return_to_recovery",
})
TASK_STATUSES = frozenset({
    "unassigned",
    "assigned",
    "navigating",
    "executing",
    "completed",
    "failed",
    "expired",
    "cancelled",
    "reassigned",
})


@dataclass(frozen=True)
class MissionTaskDefinition:
    task_id: str
    task_type: str
    location: Point | None
    region: tuple[Point, ...] | None
    prerequisites: tuple[str, ...]
    priority: int
    deadline_step: int
    estimated_duration_steps: int
    required_capabilities: tuple[str, ...]
    completion_criteria: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "location": list(self.location) if self.location is not None else None,
            "region": [list(point) for point in self.region] if self.region is not None else None,
            "prerequisites": list(self.prerequisites),
            "priority": self.priority,
            "deadline_step": self.deadline_step,
            "estimated_duration_steps": self.estimated_duration_steps,
            "required_capabilities": list(self.required_capabilities),
            "completion_criteria": dict(self.completion_criteria),
        }


@dataclass
class MissionTask:
    """Per-run mutable state for one mission task definition."""

    definition: MissionTaskDefinition
    status: str = "unassigned"
    assigned_agent_id: str | None = None
    assigned_at: int | None = None
    started_at: int | None = None
    completed_at: int | None = None
    failed_at: int | None = None
    expired_at: int | None = None
    cancelled_at: int | None = None
    reassigned_at: int | None = None
    assignment_reason: str | None = None
    failure_reason: str | None = None
    result: dict[str, Any] | None = None
    event_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in TASK_STATUSES:
            raise ValueError(f"unsupported mission task status '{self.status}'")

    def to_dict(self) -> dict[str, Any]:
        value = self.definition.to_dict()
        value.update({
            "status": self.status,
            "assigned_agent_id": self.assigned_agent_id,
            "assigned_at": self.assigned_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "failed_at": self.failed_at,
            "expired_at": self.expired_at,
            "cancelled_at": self.cancelled_at,
            "reassigned_at": self.reassigned_at,
            "assignment_reason": self.assignment_reason,
            "failure_reason": self.failure_reason,
            "result": dict(self.result) if self.result is not None else None,
            "event_history": [dict(item) for item in self.event_history],
        })
        return value


def parse_task_definitions(
    raw: Any,
    world_width: float,
    world_height: float,
    horizon_steps: int,
) -> tuple[MissionTaskDefinition, ...]:
    """Parse and validate mission task data against the configured world."""
    if not isinstance(raw, list):
        raise ValueError("mission.tasks must be an array")
    definitions = tuple(
        _parse_task(raw_task, index, world_width, world_height, horizon_steps)
        for index, raw_task in enumerate(raw)
    )
    by_id: dict[str, MissionTaskDefinition] = {}
    for task in definitions:
        if task.task_id in by_id:
            raise ValueError(f"mission.tasks task_id '{task.task_id}' must be unique")
        by_id[task.task_id] = task
    for task in definitions:
        for prerequisite in task.prerequisites:
            if prerequisite not in by_id:
                raise ValueError(
                    f"mission.tasks.{task.task_id} has unknown prerequisite '{prerequisite}'"
                )
    _validate_dependency_acyclic(by_id)
    return definitions


def _parse_task(
    raw: Any,
    index: int,
    world_width: float,
    world_height: float,
    horizon_steps: int,
) -> MissionTaskDefinition:
    path = f"mission.tasks[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    task_id = raw.get("task_id")
    task_type = raw.get("task_type")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"{path}.task_id must be a non-empty string")
    if not isinstance(task_type, str) or task_type not in TASK_TYPES:
        raise ValueError(f"{path}.task_type must be one of {', '.join(sorted(TASK_TYPES))}")

    location = _parse_point(raw.get("location"), f"{path}.location", world_width, world_height)
    region = _parse_region(raw.get("region"), f"{path}.region", task_id, world_width, world_height)
    if location is None and region is None:
        raise ValueError(f"{path} must define a location or region")
    required_geometry = {
        "reconnaissance": "region",
        "search": "either",
        "confirmation": "either",
        "coverage": "region",
        "return_to_recovery": "location",
    }[task_type]
    if required_geometry == "region" and region is None:
        raise ValueError(f"{path}.region is required for {task_type} tasks")
    if required_geometry == "location" and location is None:
        raise ValueError(f"{path}.location is required for {task_type} tasks")

    prerequisites = _parse_string_list(raw.get("prerequisites", []), f"{path}.prerequisites")
    capabilities = _parse_string_list(raw.get("required_capabilities", []), f"{path}.required_capabilities")
    if len(prerequisites) != len(set(prerequisites)):
        raise ValueError(f"{path}.prerequisites must not contain duplicates")
    if task_id in prerequisites:
        raise ValueError(f"{path} cannot depend on itself")

    priority = _parse_integer(raw.get("priority"), f"{path}.priority", minimum=0)
    deadline = _parse_integer(raw.get("deadline_step"), f"{path}.deadline_step", minimum=0)
    if deadline > horizon_steps:
        raise ValueError(f"{path}.deadline_step cannot exceed the mission horizon")
    duration = _parse_integer(raw.get("estimated_duration_steps"), f"{path}.estimated_duration_steps", minimum=1)

    criteria = raw.get("completion_criteria")
    if not isinstance(criteria, dict):
        raise ValueError(f"{path}.completion_criteria must be an object")
    criteria = _validate_completion_criteria(criteria, path)
    accepted_criteria = {
        "reconnaissance": {"observe_region", "cover_region"},
        "search": {"observe_entity", "monitor_entity"},
        "confirmation": {"confirm_entity"},
        "coverage": {"cover_region"},
        "return_to_recovery": {"arrive"},
    }[task_type]
    if criteria["kind"] not in accepted_criteria:
        accepted = " or ".join(f"'{kind}'" for kind in sorted(accepted_criteria))
        raise ValueError(f"{path}.completion_criteria.kind must be {accepted} for {task_type} tasks")

    return MissionTaskDefinition(
        task_id=task_id,
        task_type=task_type,
        location=location,
        region=region,
        prerequisites=prerequisites,
        priority=priority,
        deadline_step=deadline,
        estimated_duration_steps=duration,
        required_capabilities=capabilities,
        completion_criteria=criteria,
    )


def _parse_point(
    raw: Any,
    path: str,
    world_width: float,
    world_height: float,
) -> Point | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError(f"{path} must be [x, y] or null")
    x = _parse_finite_number(raw[0], f"{path}[0]")
    y = _parse_finite_number(raw[1], f"{path}[1]")
    if not 0.0 <= x <= world_width or not 0.0 <= y <= world_height:
        raise ValueError(f"{path} must lie within world bounds")
    return x, y


def _parse_region(
    raw: Any,
    path: str,
    task_id: str,
    world_width: float,
    world_height: float,
) -> tuple[Point, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError(f"{path} must be an array of polygon points or null")
    vertices: list[list[float]] = []
    for index, value in enumerate(raw):
        point = _parse_point(value, f"{path}[{index}]", world_width, world_height)
        assert point is not None
        vertices.append([point[0], point[1]])
    try:
        geometry = world_geometry_from_dict({
            "mission_areas": [{"id": f"task-region-{task_id}", "kind": "task-region", "vertices": vertices}],
        })
        geometry.validate(world_width, world_height)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    return tuple((point[0], point[1]) for point in vertices)


def _validate_completion_criteria(criteria: dict[str, Any], path: str) -> dict[str, Any]:
    result = dict(criteria)
    kind = result.get("kind")
    required_fields = {
        "observe_region": {"minimum_observations"},
        "observe_entity": {"entity_id"},
        "monitor_entity": {"entity_id", "radius"},
        "confirm_entity": {"entity_id"},
        "cover_region": {"coverage_fraction"},
        "arrive": {"arrival_radius"},
    }
    if not isinstance(kind, str) or kind not in required_fields:
        raise ValueError(f"{path}.completion_criteria.kind is unsupported")
    fields = required_fields[kind]
    optional_fields = {"minimum_observations"} if kind in {"observe_entity", "confirm_entity", "monitor_entity"} else set()
    if set(result) - {"kind", *fields} - optional_fields or not {"kind", *fields}.issubset(result):
        raise ValueError(f"{path}.completion_criteria fields do not match kind '{kind}'")
    if kind in {"observe_region", "observe_entity", "confirm_entity", "monitor_entity"}:
        default_minimum = 2 if kind in {"confirm_entity", "monitor_entity"} else 1
        result["minimum_observations"] = _parse_integer(
            result.get("minimum_observations", default_minimum),
            f"{path}.completion_criteria.minimum_observations", minimum=1,
        )
    if "coverage_fraction" in fields:
        fraction = _parse_finite_number(result["coverage_fraction"], f"{path}.completion_criteria.coverage_fraction")
        if not 0.0 < fraction <= 1.0:
            raise ValueError(f"{path}.completion_criteria.coverage_fraction must be in (0, 1]")
        result["coverage_fraction"] = fraction
    if "arrival_radius" in fields:
        radius = _parse_finite_number(result["arrival_radius"], f"{path}.completion_criteria.arrival_radius")
        if radius <= 0.0:
            raise ValueError(f"{path}.completion_criteria.arrival_radius must be positive")
        result["arrival_radius"] = radius
    if "radius" in fields:
        radius = _parse_finite_number(result["radius"], f"{path}.completion_criteria.radius")
        if radius <= 0.0:
            raise ValueError(f"{path}.completion_criteria.radius must be positive")
        result["radius"] = radius
    if "entity_id" in fields:
        if not isinstance(result["entity_id"], str) or not result["entity_id"]:
            raise ValueError(f"{path}.completion_criteria.entity_id must be a non-empty string")
    return result


def _parse_string_list(raw: Any, path: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(value, str) or not value for value in raw):
        raise ValueError(f"{path} must be an array of non-empty strings")
    return tuple(raw)


def _parse_integer(raw: Any, path: str, minimum: int) -> int:
    if type(raw) is not int or raw < minimum:
        raise ValueError(f"{path} must be an integer greater than or equal to {minimum}")
    return raw


def _parse_finite_number(raw: Any, path: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise ValueError(f"{path} must be a finite number")
    return float(raw)


def _validate_dependency_acyclic(tasks: dict[str, MissionTaskDefinition]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise ValueError(f"mission.tasks prerequisites contain a cycle at '{task_id}'")
        visiting.add(task_id)
        for prerequisite in tasks[task_id].prerequisites:
            visit(prerequisite)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks:
        visit(task_id)
