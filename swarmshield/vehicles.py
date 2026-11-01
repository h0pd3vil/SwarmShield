"""Deterministic UAV kinematics on the simulation's logical clock."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from .config import UAVConfig
from .geometry import Point
from .world import World


@dataclass(frozen=True)
class MotionResult:
    previous_position: Point
    position: Point
    distance_moved: float
    heading_rad: float
    speed: float
    battery_remaining: float
    status: str
    destination: Point | None
    waypoint_reached: bool = False
    final_destination: Point | None = None
    denied_zone_ids: tuple[str, ...] = ()
    attempted_position: Point | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "from": list(self.previous_position),
            "to": list(self.position),
            "distance_moved": self.distance_moved,
            "heading_rad": self.heading_rad,
            "speed": self.speed,
            "battery_remaining": self.battery_remaining,
            "status": self.status,
            "destination": list(self.destination) if self.destination is not None else None,
            "waypoint_reached": self.waypoint_reached,
            "final_destination": list(self.final_destination) if self.final_destination is not None else None,
        }
        if self.denied_zone_ids:
            value["denied_zone_ids"] = list(self.denied_zone_ids)
            value["attempted_position"] = list(self.attempted_position) if self.attempted_position is not None else None
        return value


@dataclass
class UAVState:
    agent_id: str
    x: float
    y: float
    heading_rad: float
    motion_config: UAVConfig
    speed: float = 0.0
    battery_remaining: float | None = None
    destination: Point | None = None
    final_destination: Point | None = None
    route_waypoints: list[Point] = field(default_factory=list)
    current_task_id: str | None = None
    status: str = "available"
    distance_travelled: float = 0.0
    has_motion_history: bool = False

    def __post_init__(self) -> None:
        if self.battery_remaining is None:
            self.battery_remaining = self.motion_config.battery_capacity

    @property
    def position(self) -> Point:
        return self.x, self.y

    def set_destination(self, destination: Point, world: World) -> None:
        if self.status == "unavailable":
            raise ValueError(f"{self.agent_id} is unavailable")
        if not isinstance(destination, (tuple, list)) or len(destination) != 2:
            raise ValueError("destination must contain finite x and y coordinates")
        if any(isinstance(value, bool) for value in destination):
            raise ValueError("destination must contain finite x and y coordinates")
        try:
            x, y = (float(value) for value in destination)
        except (TypeError, ValueError) as error:
            raise ValueError("destination must contain finite x and y coordinates") from error
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("destination must contain finite x and y coordinates")
        if not world.in_bounds((x, y)):
            raise ValueError("destination must be within world bounds")
        self.destination = (x, y)
        self.final_destination = (x, y)
        self.route_waypoints.clear()
        self.status = "navigating"
        self.has_motion_history = True

    def set_route(self, waypoints: tuple[Point, ...], final_destination: Point, world: World) -> None:
        if self.status == "unavailable":
            raise ValueError(f"{self.agent_id} is unavailable")
        if not waypoints or not world.is_navigable(final_destination, self.agent_id):
            raise ValueError("route must end at a navigable destination")
        route = list(waypoints)
        if math.dist(route[-1], final_destination) > 1e-9:
            route.append(final_destination)
        previous = self.position
        for point in route:
            if not world.is_navigable(point, self.agent_id) or not world.segment_is_navigable(previous, point, self.agent_id):
                raise ValueError("route contains a blocked or out-of-bounds segment")
            previous = point
        self.destination = route.pop(0)
        self.route_waypoints = route
        self.final_destination = (float(final_destination[0]), float(final_destination[1]))
        self.status = "navigating"
        self.has_motion_history = True

    def mark_unreachable(self, destination: Point) -> None:
        self.speed = 0.0
        self.destination = None
        self.final_destination = destination
        self.route_waypoints.clear()
        self.status = "unreachable"
        self.has_motion_history = True

    def advance(self, world: World) -> MotionResult | None:
        destination = self.destination
        if destination is None or self.status in {"unavailable", "blocked", "unreachable"}:
            return None

        previous = self.position
        dx = destination[0] - self.x
        dy = destination[1] - self.y
        distance_to_target = math.hypot(dx, dy)
        if distance_to_target <= 1e-9:
            self.x, self.y = destination
            self.destination = None
            self.speed = 0.0
            self.status = "arrived"
            return self._result(previous, 0.0)

        desired_heading = math.atan2(dy, dx)
        heading_error = _shortest_angle(self.heading_rad, desired_heading)
        turn = max(
            -self.motion_config.max_turn_rate_rad,
            min(self.motion_config.max_turn_rate_rad, heading_error),
        )
        self.heading_rad = _normalize_angle(self.heading_rad + turn)

        desired_speed = min(self.motion_config.max_speed, distance_to_target)
        speed_delta = max(
            -self.motion_config.acceleration,
            min(self.motion_config.acceleration, desired_speed - self.speed),
        )
        self.speed = max(0.0, min(self.motion_config.max_speed, self.speed + speed_delta))
        travel_distance = min(self.speed, distance_to_target)

        energy_rate = self.motion_config.energy_per_distance
        battery = float(self.battery_remaining or 0.0)
        if energy_rate > 0.0:
            travel_distance = min(travel_distance, battery / energy_rate)

        candidate = (
            self.x + math.cos(self.heading_rad) * travel_distance,
            self.y + math.sin(self.heading_rad) * travel_distance,
        )
        if not world.segment_is_navigable(previous, candidate, self.agent_id):
            self.speed = 0.0
            self.status = "blocked"
            denied_zone_ids = world.geometry.denied_zone_ids_intersecting_segment(previous, candidate, self.agent_id)
            return self._result(
                previous, 0.0, denied_zone_ids=denied_zone_ids, attempted_position=candidate,
            )

        moved_distance = math.dist(previous, candidate)
        self.x, self.y = candidate
        self.distance_travelled += moved_distance
        if energy_rate > 0.0:
            self.battery_remaining = max(0.0, battery - moved_distance * energy_rate)

        remaining_turn = _shortest_angle(self.heading_rad, desired_heading)
        reached = (
            abs(remaining_turn) <= 1e-9
            and math.dist(self.position, destination) <= 1e-9
        )
        waypoint_reached = False
        if reached:
            self.x, self.y = destination
            self.speed = 0.0
            waypoint_reached = True
            if self.route_waypoints:
                self.destination = self.route_waypoints.pop(0)
                self.status = "navigating"
            else:
                self.destination = None
                self.final_destination = None
                self.status = "arrived"
        elif self.motion_config.energy_per_distance > 0.0 and self.battery_remaining <= 1e-9:
            self.speed = 0.0
            self.status = "unavailable"
        else:
            self.status = "navigating"
        return self._result(previous, moved_distance, waypoint_reached)

    def _result(
        self,
        previous: Point,
        distance_moved: float,
        waypoint_reached: bool = False,
        denied_zone_ids: tuple[str, ...] = (),
        attempted_position: Point | None = None,
    ) -> MotionResult:
        return MotionResult(
            previous_position=previous,
            position=self.position,
            distance_moved=distance_moved,
            heading_rad=self.heading_rad,
            speed=self.speed,
            battery_remaining=float(self.battery_remaining or 0.0),
            status=self.status,
            destination=self.destination,
            waypoint_reached=waypoint_reached,
            final_destination=self.final_destination,
            denied_zone_ids=denied_zone_ids,
            attempted_position=attempted_position,
        )


def _shortest_angle(current: float, target: float) -> float:
    return math.atan2(math.sin(target - current), math.cos(target - current))


def _normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))
