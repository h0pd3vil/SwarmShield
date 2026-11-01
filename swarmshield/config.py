"""Configuration loading and validation for the SwarmShield simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .geometry import WorldGeometry, world_geometry_from_dict


@dataclass(frozen=True)
class UAVConfig:
    """Simple, deterministic motion and abstract energy limits."""

    max_speed: float = 2.0
    acceleration: float = 0.5
    max_turn_rate_rad: float = math.pi / 6.0
    battery_capacity: float = 1000.0
    energy_per_distance: float = 1.0

    def validate(self) -> None:
        if self.max_speed <= 0.0 or not math.isfinite(self.max_speed):
            raise ValueError("uav.max_speed must be a finite number greater than zero")
        if self.acceleration <= 0.0 or not math.isfinite(self.acceleration):
            raise ValueError("uav.acceleration must be a finite number greater than zero")
        if not 0.0 < self.max_turn_rate_rad <= math.pi or not math.isfinite(self.max_turn_rate_rad):
            raise ValueError("uav.max_turn_rate_rad must be in (0, pi]")
        if self.battery_capacity <= 0.0 or not math.isfinite(self.battery_capacity):
            raise ValueError("uav.battery_capacity must be a finite number greater than zero")
        if self.energy_per_distance < 0.0 or not math.isfinite(self.energy_per_distance):
            raise ValueError("uav.energy_per_distance must be a finite non-negative number")


@dataclass(frozen=True)
class SimulationConfig:
    seed: int = 42
    steps: int = 100
    world_width: float = 100.0
    world_height: float = 100.0
    observer_count: int = 4
    entity_count: int = 12
    protected_zone_radius: float = 10.0
    detection_range: float = 25.0
    detection_probability: float = 0.8
    position_noise_std: float = 1.0
    field_of_view_degrees: float = 360.0
    require_line_of_sight: bool = True
    max_track_age_steps: int = 10
    delivery_probability: float = 0.9
    max_latency_steps: int = 4
    duplicate_probability: float = 0.02
    partition_enabled: bool = False
    communication_range: float | None = None
    message_queue_capacity: int = 10000
    message_ttl_steps: int | None = None
    max_message_retries: int = 0
    scheduler_policy: str = "fixed-priority"
    processing_capacity_per_step: int = 48
    queue_capacity: int = 500
    min_task_deadline_steps: int = 4
    max_task_deadline_steps: int = 12
    max_task_processing_cost: int = 3
    max_task_priority: int = 3
    coordination_mode: str = "centralized"
    task_capacity_per_resource: int = 2
    coordination_task_duration_steps: int = 3
    coordination_task_deadline_steps: int = 12
    coordination_queue_capacity: int = 100
    geometry: WorldGeometry = field(default_factory=WorldGeometry)
    uav: UAVConfig = field(default_factory=UAVConfig)

    def validate(self) -> None:
        if self.steps <= 0:
            raise ValueError("world.steps must be greater than zero")
        if self.world_width <= 0 or self.world_height <= 0:
            raise ValueError("world width and height must be greater than zero")
        if self.observer_count <= 0:
            raise ValueError("scenario.observer_count must be greater than zero")
        if self.entity_count <= 0:
            raise ValueError("scenario.entity_count must be greater than zero")
        if self.protected_zone_radius < 0:
            raise ValueError("scenario.protected_zone_radius cannot be negative")
        if self.detection_range < 0:
            raise ValueError("observation.range cannot be negative")
        if self.position_noise_std < 0:
            raise ValueError("observation.position_noise_std cannot be negative")
        if (
            not math.isfinite(self.field_of_view_degrees)
            or not 0.0 < self.field_of_view_degrees <= 360.0
        ):
            raise ValueError("observation.field_of_view_degrees must be in (0, 360]")
        if not isinstance(self.require_line_of_sight, bool):
            raise ValueError("observation.require_line_of_sight must be boolean")
        if self.max_track_age_steps < 0:
            raise ValueError("observation.max_track_age_steps cannot be negative")
        if self.max_latency_steps < 0:
            raise ValueError("network.max_latency_steps cannot be negative")
        if self.communication_range is not None and (
            isinstance(self.communication_range, bool)
            or not isinstance(self.communication_range, (int, float))
            or not math.isfinite(self.communication_range)
            or self.communication_range <= 0.0
        ):
            raise ValueError("network.communication_range must be finite and greater than zero or null")
        if type(self.message_queue_capacity) is not int or self.message_queue_capacity <= 0:
            raise ValueError("network.message_queue_capacity must be greater than zero")
        if self.message_ttl_steps is not None and (
            type(self.message_ttl_steps) is not int or self.message_ttl_steps < 0
        ):
            raise ValueError("network.message_ttl_steps cannot be negative or null")
        if type(self.max_message_retries) is not int or self.max_message_retries < 0:
            raise ValueError("network.max_message_retries cannot be negative")
        if self.scheduler_policy not in {"fixed-priority", "edf"}:
            raise ValueError("scheduler.policy must be 'fixed-priority' or 'edf'")
        if self.processing_capacity_per_step <= 0:
            raise ValueError("scheduler.processing_capacity_per_step must be greater than zero")
        if self.queue_capacity <= 0:
            raise ValueError("scheduler.queue_capacity must be greater than zero")
        if self.min_task_deadline_steps < 0:
            raise ValueError("scheduler.min_deadline_steps cannot be negative")
        if self.max_task_deadline_steps < self.min_task_deadline_steps:
            raise ValueError("scheduler.max_deadline_steps must be >= min_deadline_steps")
        if self.max_task_processing_cost <= 0:
            raise ValueError("scheduler.max_processing_cost must be greater than zero")
        if self.max_task_priority <= 0:
            raise ValueError("scheduler.max_priority must be greater than zero")
        if self.coordination_mode not in {"centralized", "decentralized"}:
            raise ValueError("coordination.mode must be 'centralized' or 'decentralized'")
        if self.task_capacity_per_resource <= 0:
            raise ValueError("coordination.task_capacity_per_resource must be greater than zero")
        if self.coordination_task_duration_steps <= 0:
            raise ValueError("coordination.task_duration_steps must be greater than zero")
        if self.coordination_task_deadline_steps < 0:
            raise ValueError("coordination.task_deadline_steps cannot be negative")
        if self.coordination_queue_capacity <= 0:
            raise ValueError("coordination.queue_capacity must be greater than zero")
        for name, value in (
            ("observation.detection_probability", self.detection_probability),
            ("network.delivery_probability", self.delivery_probability),
            ("network.duplicate_probability", self.duplicate_probability),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        self.geometry.validate(self.world_width, self.world_height)
        self.uav.validate()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.geometry.is_empty:
            # Preserve the established flat baseline config and run-summary schema.
            data.pop("geometry", None)
        else:
            data["geometry"] = self.geometry.to_dict()
        if self.uav == UAVConfig():
            data.pop("uav", None)
        if self.field_of_view_degrees == 360.0:
            data.pop("field_of_view_degrees", None)
        if self.require_line_of_sight:
            data.pop("require_line_of_sight", None)
        if self.communication_range is None:
            data.pop("communication_range", None)
        if self.message_queue_capacity == 10000:
            data.pop("message_queue_capacity", None)
        if self.message_ttl_steps is None:
            data.pop("message_ttl_steps", None)
        if self.max_message_retries == 0:
            data.pop("max_message_retries", None)
        return data


def config_from_dict(data: dict[str, Any]) -> SimulationConfig:
    for section_name in ("world", "scenario", "observation", "network", "scheduler", "coordination", "geometry", "uav"):
        section = data.get(section_name, {})
        if not isinstance(section, dict):
            raise ValueError(f"{section_name} must be a JSON object")

    world = data.get("world", {})
    scenario = data.get("scenario", {})
    observation = data.get("observation", {})
    network = data.get("network", {})
    scheduler = data.get("scheduler", {})
    coordination = data.get("coordination", {})
    uav = data.get("uav", {})
    if "require_line_of_sight" in observation and not isinstance(observation["require_line_of_sight"], bool):
        raise ValueError("observation.require_line_of_sight must be boolean")
    if "communication_range" in network and network["communication_range"] is not None and (
        isinstance(network["communication_range"], bool)
        or not isinstance(network["communication_range"], (int, float))
    ):
        raise ValueError("network.communication_range must be a number or null")
    if "message_queue_capacity" in network and (
        type(network["message_queue_capacity"]) is not int
    ):
        raise ValueError("network.message_queue_capacity must be an integer")
    if "message_ttl_steps" in network and network["message_ttl_steps"] is not None and (
        type(network["message_ttl_steps"]) is not int
    ):
        raise ValueError("network.message_ttl_steps must be an integer or null")
    if "max_message_retries" in network and type(network["max_message_retries"]) is not int:
        raise ValueError("network.max_message_retries must be an integer")

    if "map_preset" in data and "geometry" in data:
        raise ValueError("specify either map_preset or inline geometry, not both")
    if "map_preset" in data:
        preset = data["map_preset"]
        if not isinstance(preset, str) or not preset or Path(preset).name != preset:
            raise ValueError("map_preset must be a map identifier")
        map_path = Path(__file__).resolve().parent.parent / "configs" / "maps" / f"{preset}.json"
        if not map_path.is_file():
            raise ValueError(f"unknown map_preset '{preset}'")
        with map_path.open("r", encoding="utf-8") as map_file:
            geometry_data = json.load(map_file)
        if not isinstance(geometry_data, dict):
            raise ValueError(f"map_preset '{preset}' must contain a JSON object")
    else:
        geometry_data = data.get("geometry")

    config = SimulationConfig(
        seed=int(data.get("seed", 42)),
        steps=int(world.get("steps", 100)),
        world_width=float(world.get("width", 100)),
        world_height=float(world.get("height", 100)),
        observer_count=int(scenario.get("observer_count", 4)),
        entity_count=int(scenario.get("entity_count", 12)),
        protected_zone_radius=float(scenario.get("protected_zone_radius", 10)),
        detection_range=float(observation.get("range", 25)),
        detection_probability=float(observation.get("detection_probability", 0.8)),
        position_noise_std=float(observation.get("position_noise_std", 1.0)),
        field_of_view_degrees=float(observation.get("field_of_view_degrees", 360.0)),
        require_line_of_sight=observation.get("require_line_of_sight", True),
        max_track_age_steps=int(observation.get("max_track_age_steps", 10)),
        delivery_probability=float(network.get("delivery_probability", 0.9)),
        max_latency_steps=int(network.get("max_latency_steps", 4)),
        duplicate_probability=float(network.get("duplicate_probability", 0.02)),
        partition_enabled=bool(network.get("partition_enabled", False)),
        communication_range=(
            float(network["communication_range"])
            if network.get("communication_range") is not None else None
        ),
        message_queue_capacity=int(network.get("message_queue_capacity", 10000)),
        message_ttl_steps=(
            network.get("message_ttl_steps")
            if network.get("message_ttl_steps") is not None else None
        ),
        max_message_retries=int(network.get("max_message_retries", 0)),
        scheduler_policy=str(scheduler.get("policy", "fixed-priority")),
        processing_capacity_per_step=int(scheduler.get("processing_capacity_per_step", 48)),
        queue_capacity=int(scheduler.get("queue_capacity", 500)),
        min_task_deadline_steps=int(scheduler.get("min_deadline_steps", 4)),
        max_task_deadline_steps=int(scheduler.get("max_deadline_steps", 12)),
        max_task_processing_cost=int(scheduler.get("max_processing_cost", 3)),
        max_task_priority=int(scheduler.get("max_priority", 3)),
        coordination_mode=str(coordination.get("mode", "centralized")),
        task_capacity_per_resource=int(coordination.get("task_capacity_per_resource", 2)),
        coordination_task_duration_steps=int(coordination.get("task_duration_steps", 3)),
        coordination_task_deadline_steps=int(coordination.get("task_deadline_steps", 12)),
        coordination_queue_capacity=int(coordination.get("queue_capacity", 100)),
        geometry=world_geometry_from_dict(geometry_data),
        uav=UAVConfig(
            max_speed=float(uav.get("max_speed", 2.0)),
            acceleration=float(uav.get("acceleration", 0.5)),
            max_turn_rate_rad=float(uav.get("max_turn_rate_rad", math.pi / 6.0)),
            battery_capacity=float(uav.get("battery_capacity", 1000.0)),
            energy_per_distance=float(uav.get("energy_per_distance", 1.0)),
        ),
    )
    config.validate()
    return config


def load_config(path: str | Path) -> SimulationConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        data = json.load(config_file)
    if not isinstance(data, dict):
        raise ValueError("The configuration root must be a JSON object")
    return config_from_dict(data)


def derive_seed(master_seed: int, stream_name: str) -> int:
    """Derive stable independent RNG seeds without Python's randomized hash()."""
    material = f"{master_seed}:{stream_name}".encode("utf-8")
    digest = hashlib.blake2b(material, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big")
