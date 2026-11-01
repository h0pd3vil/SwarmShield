"""Agent-local track storage and freshness reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from .config import UAVConfig
from .navigation import GridPathPlanner, PathResult
from .observations import Observation
from .world import Observer, World
from .vehicles import MotionResult, UAVState


@dataclass(frozen=True)
class Track:
    entity_id: str
    x: float
    y: float
    observed_at: int
    source_agent_id: str
    confidence: float


@dataclass(frozen=True)
class AgentSensorConfig:
    detection_range: float
    detection_probability: float
    position_noise_std: float
    field_of_view_degrees: float
    require_line_of_sight: bool
    max_track_age_steps: int


class Agent:
    def __init__(
        self,
        observer: Observer,
        uav_config: UAVConfig | None = None,
        sensor_config: AgentSensorConfig | None = None,
    ) -> None:
        self.agent_id = observer.agent_id
        self.vehicle = UAVState(
            observer.agent_id,
            observer.x,
            observer.y,
            observer.heading_rad,
            uav_config or UAVConfig(),
        )
        self.sensor_config = sensor_config or AgentSensorConfig(25.0, 0.8, 1.0, 360.0, True, 10)
        self.tracks: dict[str, Track] = {}
        # Per-recipient record of unique source reports, retained separately
        # from the latest reconciled track for evidence-based task criteria.
        self.track_history: list[Track] = []
        self._observation_keys: set[tuple[str, int, str]] = set()
        self.recovery_target: tuple[float, float] | None = None
        self.pose_history: list[tuple[int, float, float, float]] = [
            (0, self.x, self.y, self.heading_rad),
        ]
        self._received_message_ids: set[str] = set()

    @property
    def x(self) -> float:
        return self.vehicle.x

    @property
    def y(self) -> float:
        return self.vehicle.y

    @property
    def heading_rad(self) -> float:
        return self.vehicle.heading_rad

    @property
    def capabilities(self) -> frozenset[str]:
        """Capabilities supported by the configured onboard sensor model."""
        if self.sensor_config.detection_range > 0.0 and self.sensor_config.detection_probability > 0.0:
            return frozenset({"visual_sensor"})
        return frozenset()

    def set_destination(
        self,
        destination: tuple[float, float],
        world: World,
        task_id: str | None = None,
        planner: GridPathPlanner | None = None,
    ) -> PathResult | None:
        # Reuse UAVState's coordinate validation before asking the planner to
        # route. A valid but enclosed destination is reported as unreachable.
        self.vehicle.set_destination(destination, world)
        self.vehicle.current_task_id = task_id
        path = (planner or GridPathPlanner()).plan(self.vehicle.position, destination, world, self.agent_id)
        if path is None:
            self.vehicle.mark_unreachable(destination)
            return None
        self.vehicle.set_route(path.waypoints, destination, world)
        return path

    def advance_motion(self, world: World) -> MotionResult | None:
        return self.vehicle.advance(world)

    def observe_locally(self, observation: Observation) -> str:
        return self._update_track(observation)

    def reserve_message_id(self, message_id: str) -> bool:
        if message_id in self._received_message_ids:
            return False
        self._received_message_ids.add(message_id)
        return True

    def apply_observation(self, observation: Observation) -> str:
        return self._update_track(observation)

    def receive(self, message_id: str, observation: Observation) -> str:
        if not self.reserve_message_id(message_id):
            return "duplicate"
        return self.apply_observation(observation)

    def _update_track(self, observation: Observation) -> str:
        key = (observation.entity_id, observation.observed_at, observation.source_agent_id)
        if key not in self._observation_keys:
            self._observation_keys.add(key)
            self.track_history.append(Track(
                entity_id=observation.entity_id,
                x=observation.x,
                y=observation.y,
                observed_at=observation.observed_at,
                source_agent_id=observation.source_agent_id,
                confidence=observation.confidence,
            ))
        current = self.tracks.get(observation.entity_id)
        if current is not None:
            if observation.observed_at < current.observed_at:
                return "stale"
            if observation.observed_at == current.observed_at and observation.confidence <= current.confidence:
                return "unchanged"
        updated = Track(
            entity_id=observation.entity_id,
            x=observation.x,
            y=observation.y,
            observed_at=observation.observed_at,
            source_agent_id=observation.source_agent_id,
            confidence=observation.confidence,
        )
        self.tracks[observation.entity_id] = updated
        return "updated"

    def active_tracks(self, current_step: int, max_age_steps: int) -> tuple[Track, ...]:
        return tuple(
            track
            for track in self.tracks.values()
            if current_step - track.observed_at <= max_age_steps
        )
