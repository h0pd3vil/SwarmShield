"""Synthetic 2D world and observer placement."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random

from .config import SimulationConfig
from .geometry import Point
from .observations import EntityView, Observation, ObservationModel


@dataclass(frozen=True)
class Observer:
    agent_id: str
    x: float
    y: float
    # Fixed initial yaw in world screen coordinates (positive Y points down).
    heading_rad: float = 0.0


@dataclass(frozen=True)
class ProtectedZone:
    x: float
    y: float
    radius: float


@dataclass
class _Entity:
    entity_id: str
    x: float
    y: float
    vx: float
    vy: float


class World:
    """Owns exact simulated state; agents receive only generated observations."""

    def __init__(self, config: SimulationConfig, seed: int) -> None:
        self._config = config
        self.geometry = config.geometry
        rng = random.Random(seed)
        self._step = 0
        self.protected_zone = ProtectedZone(
            x=config.world_width / 2.0,
            y=config.world_height / 2.0,
            radius=config.protected_zone_radius,
        )
        self._entities = [
            _Entity(
                entity_id=f"entity-{index + 1:03d}",
                x=rng.uniform(0.0, config.world_width),
                y=rng.uniform(0.0, config.world_height),
                vx=rng.uniform(-1.0, 1.0),
                vy=rng.uniform(-1.0, 1.0),
            )
            for index in range(config.entity_count)
        ]
        self.observers = self._place_observers(config)

    @property
    def width(self) -> float:
        return self._config.world_width

    @property
    def height(self) -> float:
        return self._config.world_height

    @staticmethod
    def _place_observers(config: SimulationConfig) -> tuple[Observer, ...]:
        center_x = config.world_width / 2.0
        center_y = config.world_height / 2.0
        radius_x = config.world_width * 0.4
        radius_y = config.world_height * 0.4
        result = []
        for index in range(config.observer_count):
            angle = 2.0 * math.pi * index / config.observer_count
            x = min(max(center_x + math.cos(angle) * radius_x, 0.0), config.world_width)
            y = min(max(center_y + math.sin(angle) * radius_y, 0.0), config.world_height)
            result.append(
                Observer(
                    agent_id=f"agent-{index + 1:03d}",
                    x=x,
                    y=y,
                    heading_rad=math.atan2(center_y - y, center_x - x),
                )
            )
        return tuple(result)

    def advance(self) -> None:
        self._step += 1
        for entity in self._entities:
            entity.x, entity.vx = self._advance_axis(entity.x, entity.vx, self._config.world_width)
            entity.y, entity.vy = self._advance_axis(entity.y, entity.vy, self._config.world_height)

    @staticmethod
    def _advance_axis(position: float, velocity: float, limit: float) -> tuple[float, float]:
        next_position = position + velocity
        if next_position < 0.0:
            return -next_position, abs(velocity)
        if next_position > limit:
            return 2.0 * limit - next_position, -abs(velocity)
        return next_position, velocity

    def observations_for(
        self,
        observer: Observer,
        model: ObservationModel,
        step: int,
        *,
        observer_position: Point | None = None,
        observer_heading_rad: float | None = None,
        field_of_view_degrees: float | None = None,
        require_line_of_sight: bool | None = None,
    ) -> list[Observation]:
        """Generate reports without returning exact entity state to the observer."""
        views = tuple(EntityView(entity.entity_id, entity.x, entity.y) for entity in self._entities)
        observer_x, observer_y = observer_position or (observer.x, observer.y)
        return model.observe(
            observer.agent_id,
            observer_x,
            observer_y,
            views,
            step,
            observer_heading_rad=(
                observer.heading_rad if observer_heading_rad is None else observer_heading_rad
            ),
            line_of_sight_test=self.has_line_of_sight,
            field_of_view_degrees=field_of_view_degrees,
            require_line_of_sight=require_line_of_sight,
        )

    def evaluator_snapshot(self) -> tuple[EntityView, ...]:
        """Return exact state for evaluator calculations, never passed to agents."""
        return tuple(EntityView(entity.entity_id, entity.x, entity.y) for entity in self._entities)

    def evaluator_zone_count(self) -> int:
        """Count entities in the protected zone for synthetic scenario reporting."""
        zone = self.protected_zone
        return sum(
            (entity.x - zone.x) ** 2 + (entity.y - zone.y) ** 2 <= zone.radius**2
            for entity in self._entities
        )

    def in_bounds(self, point: Point) -> bool:
        x, y = point
        return 0.0 <= x <= self._config.world_width and 0.0 <= y <= self._config.world_height

    def is_navigable(
        self,
        point: Point,
        agent_id: str | None = None,
        *,
        allow_restricted_start: bool = False,
    ) -> bool:
        """Check world bounds, solid obstacles, and restricted areas."""
        if not self.in_bounds(point):
            return False
        if allow_restricted_start:
            # An unauthorized aircraft already inside a denied zone must be
            # able to leave; this exception is used only for the route origin.
            from .geometry import point_in_polygon

            blocked = any(point_in_polygon(point, feature.vertices) for feature in self.geometry.obstacles)
            return not blocked
        return not self.geometry.is_blocked_for_navigation(point, agent_id)

    def segment_is_navigable(self, start: Point, end: Point, agent_id: str | None = None) -> bool:
        """Check a direct route against bounds and solid/restricted polygons."""
        return (
            self.is_navigable(start, agent_id, allow_restricted_start=True)
            and self.is_navigable(end, agent_id)
            and not self.geometry.segment_is_blocked_for_navigation(start, end, agent_id)
        )

    def has_line_of_sight(self, start: Point, end: Point) -> bool:
        """Return whether configured occluders leave the segment unobstructed."""
        return self.geometry.line_of_sight_is_clear(start, end)

    def is_in_safe_area(self, point: Point) -> bool:
        return self.geometry.is_in_safe_area(point)
