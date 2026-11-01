"""Run-owned entity protection designations and evidence task construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .geometry import Point
from .tasks import MissionTask, MissionTaskDefinition


@dataclass
class EntityProtection:
    entity_id: str
    radius: float
    zone_type: str
    mission_id: str | None
    task_id: str
    designated_at: int
    last_known_position: Point
    last_observed_at: int
    status: str = "caution"
    assigned_agent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "x": self.last_known_position[0],
            "y": self.last_known_position[1],
            "last_observed_at": self.last_observed_at,
            "radius": self.radius,
            "zone_type": self.zone_type,
            "mission_id": self.mission_id,
            "task_id": self.task_id,
            "assigned_agent_id": self.assigned_agent_id,
            "status": self.status,
            "designated_at": self.designated_at,
        }


def create_monitoring_task(
    entity_id: str,
    position: Point,
    radius: float,
    deadline_step: int,
    zone_type: str = "monitoring",
) -> MissionTask:
    """Require two local observations while the UAV is inside the perimeter."""
    task_id = f"protection-{entity_id}"
    definition = MissionTaskDefinition(
        task_id=task_id,
        task_type="search",
        location=position,
        region=None,
        prerequisites=(),
        priority=100 if zone_type == "protection" else 5,
        deadline_step=deadline_step,
        estimated_duration_steps=2,
        required_capabilities=("visual_sensor",),
        completion_criteria={
            "kind": "monitor_entity",
            "entity_id": entity_id,
            "radius": radius,
            "minimum_observations": 2,
        },
    )
    return MissionTask(definition)
