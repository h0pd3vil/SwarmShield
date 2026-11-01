"""Range-limited synthetic observation generation."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
from typing import Callable

from .geometry import Point


@dataclass(frozen=True)
class EntityView:
    entity_id: str
    x: float
    y: float


@dataclass(frozen=True)
class Observation:
    entity_id: str
    x: float
    y: float
    observed_at: int
    source_agent_id: str
    confidence: float = 1.0
    # Optional display-only footprint carried with a real report. It does not
    # affect track reconciliation, task evidence, or deterministic outcomes.
    sensor_coverage_cells: tuple[tuple[int, int], ...] = field(default=(), compare=False, repr=False)


class ObservationModel:
    def __init__(
        self,
        rng: random.Random,
        detection_range: float,
        detection_probability: float,
        position_noise_std: float,
        world_width: float,
        world_height: float,
        field_of_view_degrees: float = 360.0,
        require_line_of_sight: bool = False,
    ) -> None:
        self._rng = rng
        self._detection_range = detection_range
        self._detection_probability = detection_probability
        self._position_noise_std = position_noise_std
        self._world_width = world_width
        self._world_height = world_height
        self._field_of_view_degrees = field_of_view_degrees
        self._require_line_of_sight = require_line_of_sight

    def observe(
        self,
        agent_id: str,
        observer_x: float,
        observer_y: float,
        entities: tuple[EntityView, ...],
        step: int,
        *,
        observer_heading_rad: float = 0.0,
        line_of_sight_test: Callable[[Point, Point], bool] | None = None,
        field_of_view_degrees: float | None = None,
        require_line_of_sight: bool | None = None,
    ) -> list[Observation]:
        reports: list[Observation] = []
        fov = self._field_of_view_degrees if field_of_view_degrees is None else field_of_view_degrees
        use_line_of_sight = (
            self._require_line_of_sight
            if require_line_of_sight is None
            else require_line_of_sight
        )
        if use_line_of_sight and line_of_sight_test is None:
            raise ValueError("line_of_sight_test is required when observation LOS is enabled")
        half_fov_rad = math.radians(fov / 2.0)
        for entity in entities:
            dx = entity.x - observer_x
            dy = entity.y - observer_y
            distance = math.hypot(dx, dy)
            if distance > self._detection_range:
                continue
            if fov < 360.0:
                bearing = math.atan2(dy, dx)
                angle_error = math.atan2(
                    math.sin(bearing - observer_heading_rad),
                    math.cos(bearing - observer_heading_rad),
                )
                if abs(angle_error) > half_fov_rad:
                    continue
            if (
                use_line_of_sight
                and line_of_sight_test is not None
                and not line_of_sight_test((observer_x, observer_y), (entity.x, entity.y))
            ):
                continue
            if self._rng.random() >= self._detection_probability:
                continue

            x = entity.x + self._rng.gauss(0.0, self._position_noise_std)
            y = entity.y + self._rng.gauss(0.0, self._position_noise_std)
            reports.append(
                Observation(
                    entity_id=entity.entity_id,
                    x=min(max(x, 0.0), self._world_width),
                    y=min(max(y, 0.0), self._world_height),
                    observed_at=step,
                    source_agent_id=agent_id,
                )
            )
        return reports
