"""Immutable scenario geometry shared by navigation, sensing, and rendering."""

from __future__ import annotations

from dataclasses import dataclass
import math
from functools import lru_cache
from typing import Any


Point = tuple[float, float]


@dataclass(frozen=True)
class PolygonFeature:
    """A polygonal map feature in world coordinates; vertices close implicitly."""

    feature_id: str
    kind: str
    vertices: tuple[Point, ...]
    blocks_line_of_sight: bool = False
    behavior: str = "deny_entry"
    authorized_agent_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.feature_id,
            "kind": self.kind,
            "vertices": [[x, y] for x, y in self.vertices],
            "blocks_line_of_sight": self.blocks_line_of_sight,
        }
        if self.behavior != "deny_entry" or self.authorized_agent_ids:
            value["behavior"] = self.behavior
            value["authorized_agent_ids"] = list(self.authorized_agent_ids)
        return value


@dataclass(frozen=True)
class PointFeature:
    """A point of interest or other named world location."""

    feature_id: str
    kind: str
    x: float
    y: float

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.feature_id, "kind": self.kind, "x": self.x, "y": self.y}


@dataclass(frozen=True)
class WorldGeometry:
    """Static world geometry. Dynamic entities and UAV state remain in ``World``."""

    obstacles: tuple[PolygonFeature, ...] = ()
    buildings: tuple[PolygonFeature, ...] = ()
    roads: tuple[PolygonFeature, ...] = ()
    paths: tuple[PolygonFeature, ...] = ()
    parking_areas: tuple[PolygonFeature, ...] = ()
    water_bodies: tuple[PolygonFeature, ...] = ()
    vegetation: tuple[PolygonFeature, ...] = ()
    safe_areas: tuple[PolygonFeature, ...] = ()
    restricted_regions: tuple[PolygonFeature, ...] = ()
    caution_zones: tuple[PolygonFeature, ...] = ()
    mission_areas: tuple[PolygonFeature, ...] = ()
    points_of_interest: tuple[PointFeature, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any((
            self.obstacles,
            self.buildings,
            self.roads,
            self.paths,
            self.parking_areas,
            self.water_bodies,
            self.vegetation,
            self.safe_areas,
            self.restricted_regions,
            self.caution_zones,
            self.mission_areas,
            self.points_of_interest,
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "obstacles": [item.to_dict() for item in self.obstacles],
            "buildings": [item.to_dict() for item in self.buildings],
            "roads": [item.to_dict() for item in self.roads],
            "paths": [item.to_dict() for item in self.paths],
            "parking_areas": [item.to_dict() for item in self.parking_areas],
            "water_bodies": [item.to_dict() for item in self.water_bodies],
            "vegetation": [item.to_dict() for item in self.vegetation],
            "safe_areas": [item.to_dict() for item in self.safe_areas],
            "restricted_regions": [item.to_dict() for item in self.restricted_regions],
            "caution_zones": [item.to_dict() for item in self.caution_zones],
            "mission_areas": [item.to_dict() for item in self.mission_areas],
            "points_of_interest": [item.to_dict() for item in self.points_of_interest],
        }

    def validate(self, width: float, height: float) -> None:
        seen_ids: set[str] = set()
        polygon_groups = (
            ("geometry.obstacles", self.obstacles),
            ("geometry.buildings", self.buildings),
            ("geometry.roads", self.roads),
            ("geometry.paths", self.paths),
            ("geometry.parking_areas", self.parking_areas),
            ("geometry.water_bodies", self.water_bodies),
            ("geometry.vegetation", self.vegetation),
            ("geometry.safe_areas", self.safe_areas),
            ("geometry.restricted_regions", self.restricted_regions),
            ("geometry.caution_zones", self.caution_zones),
            ("geometry.mission_areas", self.mission_areas),
        )
        for path, features in polygon_groups:
            for feature in features:
                if not feature.feature_id or not feature.kind:
                    raise ValueError(f"{path} feature id and kind must be non-empty")
                if feature.feature_id in seen_ids:
                    raise ValueError(f"geometry feature id '{feature.feature_id}' must be unique")
                seen_ids.add(feature.feature_id)
                if len(feature.vertices) < 3 or len(set(feature.vertices)) < 3:
                    raise ValueError(f"{path}.{feature.feature_id} must have at least three distinct vertices")
                if not isinstance(feature.blocks_line_of_sight, bool):
                    raise ValueError(f"{path}.{feature.feature_id}.blocks_line_of_sight must be boolean")
                if path == "geometry.restricted_regions":
                    if feature.behavior not in {"deny_entry", "monitor", "warn", "inactive"}:
                        raise ValueError(f"{path}.{feature.feature_id}.behavior is unsupported")
                    if any(not agent_id for agent_id in feature.authorized_agent_ids):
                        raise ValueError(f"{path}.{feature.feature_id}.authorized_agent_ids must contain non-empty IDs")
                    if len(feature.authorized_agent_ids) != len(set(feature.authorized_agent_ids)):
                        raise ValueError(f"{path}.{feature.feature_id}.authorized_agent_ids must not contain duplicates")
                for x, y in feature.vertices:
                    _validate_point(x, y, width, height, f"{path}.{feature.feature_id}")
                if not _is_simple_polygon(feature.vertices):
                    raise ValueError(f"{path}.{feature.feature_id} must not self-intersect")
                wrapped_vertices = feature.vertices[1:] + feature.vertices[:1]
                twice_area = sum(
                    x1 * y2 - x2 * y1
                    for (x1, y1), (x2, y2) in zip(feature.vertices, wrapped_vertices)
                )
                if math.isclose(twice_area, 0.0, abs_tol=1e-9):
                    raise ValueError(f"{path}.{feature.feature_id} must enclose non-zero area")

        for feature in self.points_of_interest:
            if not feature.feature_id or not feature.kind:
                raise ValueError("geometry.points_of_interest id and kind must be non-empty")
            if feature.feature_id in seen_ids:
                raise ValueError(f"geometry feature id '{feature.feature_id}' must be unique")
            seen_ids.add(feature.feature_id)
            _validate_point(feature.x, feature.y, width, height, f"geometry.points_of_interest.{feature.feature_id}")

    def is_blocked_for_navigation(self, point: Point, agent_id: str | None = None) -> bool:
        """Return true when a point lies in or on solid/restricted geometry."""
        if any(point_in_polygon(point, feature.vertices) for feature in self.obstacles):
            return True
        return any(
            feature.behavior == "deny_entry"
            and agent_id not in feature.authorized_agent_ids
            and point_in_polygon(point, feature.vertices)
            for feature in self.restricted_regions
        )

    def segment_is_blocked_for_navigation(
        self, start: Point, end: Point, agent_id: str | None = None,
    ) -> bool:
        """Return true when a straight route touches solid/restricted geometry."""
        if any(segment_intersects_polygon(start, end, feature.vertices) for feature in self.obstacles):
            return True
        return any(
            feature.behavior == "deny_entry"
            and agent_id not in feature.authorized_agent_ids
            and not _strictly_inside_polygon(start, feature.vertices)
            and not (
                _point_on_polygon_boundary(start, feature.vertices)
                and not point_in_polygon(end, feature.vertices)
            )
            and segment_intersects_polygon(start, end, feature.vertices)
            for feature in self.restricted_regions
        )

    def denied_zone_ids_intersecting_segment(self, start: Point, end: Point, agent_id: str) -> tuple[str, ...]:
        """Return denied zones a UAV attempted to enter on this movement step."""
        return tuple(
            feature.feature_id
            for feature in self.restricted_regions
            if feature.behavior == "deny_entry"
            and agent_id not in feature.authorized_agent_ids
            and not _strictly_inside_polygon(start, feature.vertices)
            and not (
                _point_on_polygon_boundary(start, feature.vertices)
                and not point_in_polygon(end, feature.vertices)
            )
            and segment_intersects_polygon(start, end, feature.vertices)
        )

    def restricted_zone_transitions(
        self, start: Point, end: Point, agent_id: str,
    ) -> tuple[tuple[str, str, str, bool], ...]:
        """Return actual boundary transitions as (zone, transition, policy, authorized)."""
        transitions: list[tuple[str, str, str, bool]] = []
        for feature in self.restricted_regions:
            if feature.behavior == "inactive":
                continue
            before = point_in_polygon(start, feature.vertices)
            after = point_in_polygon(end, feature.vertices)
            authorized = agent_id in feature.authorized_agent_ids
            if not before and after:
                transitions.append((feature.feature_id, "entry", feature.behavior, authorized))
            elif before and not after:
                transitions.append((feature.feature_id, "exit", feature.behavior, authorized))
            elif not before and not after and segment_intersects_polygon(start, end, feature.vertices):
                transitions.append((feature.feature_id, "entry", feature.behavior, authorized))
                transitions.append((feature.feature_id, "exit", feature.behavior, authorized))
        return tuple(transitions)

    def line_of_sight_is_clear(self, start: Point, end: Point) -> bool:
        """Check solid features and vegetation explicitly configured to occlude."""
        occluders = (
            *(feature for feature in self.obstacles if feature.blocks_line_of_sight),
            *(feature for feature in self.buildings if feature.blocks_line_of_sight),
            *(feature for feature in self.vegetation if feature.blocks_line_of_sight),
        )
        return not any(
            segment_intersects_polygon(start, end, feature.vertices)
            for feature in occluders
        )

    def is_in_safe_area(self, point: Point) -> bool:
        return any(point_in_polygon(point, feature.vertices) for feature in self.safe_areas)

    def authorized_restricted_zone_ids(self, agent_id: str | None) -> tuple[str, ...]:
        if agent_id is None:
            return ()
        return tuple(
            feature.feature_id
            for feature in self.restricted_regions
            if feature.behavior == "deny_entry" and agent_id in feature.authorized_agent_ids
        )


def world_geometry_from_dict(data: dict[str, Any] | None) -> WorldGeometry:
    """Parse the optional top-level ``geometry`` config object."""
    if data is None:
        return WorldGeometry()
    if not isinstance(data, dict):
        raise ValueError("geometry must be a JSON object")

    polygon_groups: dict[str, tuple[PolygonFeature, ...]] = {}
    for group_name in (
        "obstacles",
        "buildings",
        "roads",
        "paths",
        "parking_areas",
        "water_bodies",
        "vegetation",
        "safe_areas",
        "restricted_regions",
        "caution_zones",
        "mission_areas",
    ):
        raw_group = data.get(group_name, [])
        if not isinstance(raw_group, list):
            raise ValueError(f"geometry.{group_name} must be an array")
        features: list[PolygonFeature] = []
        for index, raw in enumerate(raw_group):
            path = f"geometry.{group_name}[{index}]"
            if not isinstance(raw, dict):
                raise ValueError(f"{path} must be an object")
            raw_vertices = raw.get("vertices")
            if not isinstance(raw_vertices, list):
                raise ValueError(f"{path}.vertices must be an array")
            vertices: list[Point] = []
            for vertex_index, raw_vertex in enumerate(raw_vertices):
                if not isinstance(raw_vertex, (list, tuple)) or len(raw_vertex) != 2:
                    raise ValueError(f"{path}.vertices[{vertex_index}] must contain x and y")
                vertices.append((
                    _finite_float(raw_vertex[0], f"{path}.vertices[{vertex_index}][0]"),
                    _finite_float(raw_vertex[1], f"{path}.vertices[{vertex_index}][1]"),
                ))
            feature_id = raw.get("id")
            kind = raw.get("kind")
            if not isinstance(feature_id, str) or not isinstance(kind, str):
                raise ValueError(f"{path} requires string id and kind")
            blocks_los = raw.get("blocks_line_of_sight", group_name == "obstacles")
            if not isinstance(blocks_los, bool):
                raise ValueError(f"{path}.blocks_line_of_sight must be boolean")
            behavior = raw.get("behavior", "deny_entry")
            if not isinstance(behavior, str):
                raise ValueError(f"{path}.behavior must be a string")
            raw_authorized_ids = raw.get("authorized_agent_ids", [])
            if not isinstance(raw_authorized_ids, list) or any(not isinstance(value, str) for value in raw_authorized_ids):
                raise ValueError(f"{path}.authorized_agent_ids must be an array of strings")
            features.append(PolygonFeature(
                feature_id, kind, tuple(vertices), blocks_los, behavior, tuple(raw_authorized_ids),
            ))
        polygon_groups[group_name] = tuple(features)

    raw_pois = data.get("points_of_interest", [])
    if not isinstance(raw_pois, list):
        raise ValueError("geometry.points_of_interest must be an array")
    points: list[PointFeature] = []
    for index, raw in enumerate(raw_pois):
        path = f"geometry.points_of_interest[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{path} must be an object")
        feature_id = raw.get("id")
        kind = raw.get("kind")
        if not isinstance(feature_id, str) or not isinstance(kind, str):
            raise ValueError(f"{path} requires string id and kind")
        points.append(PointFeature(
            feature_id,
            kind,
            _finite_float(raw.get("x"), f"{path}.x"),
            _finite_float(raw.get("y"), f"{path}.y"),
        ))

    return WorldGeometry(**polygon_groups, points_of_interest=tuple(points))


def _finite_float(value: Any, path: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{path} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{path} must be a finite number") from error
    if not math.isfinite(result):
        raise ValueError(f"{path} must be a finite number")
    return result


def _validate_point(x: float, y: float, width: float, height: float, path: str) -> None:
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError(f"{path} coordinates must be finite")
    if not 0.0 <= x <= width or not 0.0 <= y <= height:
        raise ValueError(f"{path} coordinates must be within the world bounds")


def _point_on_polygon_boundary(point: Point, vertices: tuple[Point, ...]) -> bool:
    return any(
        _point_on_segment(point, start, end)
        for start, end in zip(vertices, vertices[1:] + vertices[:1])
    )


def _strictly_inside_polygon(point: Point, vertices: tuple[Point, ...]) -> bool:
    return point_in_polygon(point, vertices) and not _point_on_polygon_boundary(point, vertices)


def point_in_polygon(point: Point, vertices: tuple[Point, ...]) -> bool:
    """Ray-cast containment where polygon edges count as inside."""
    x, y = point
    min_x, min_y, max_x, max_y = _polygon_bounds(vertices)
    if x < min_x or x > max_x or y < min_y or y > max_y:
        return False
    inside = False
    for (x1, y1), (x2, y2) in zip(vertices, vertices[1:] + vertices[:1]):
        if _point_on_segment(point, (x1, y1), (x2, y2)):
            return True
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < crossing_x:
                inside = not inside
    return inside


def segment_intersects_polygon(start: Point, end: Point, vertices: tuple[Point, ...]) -> bool:
    """Return true for an edge touch, crossing, or segment contained by a polygon."""
    min_x, min_y, max_x, max_y = _polygon_bounds(vertices)
    if (
        max(start[0], end[0]) < min_x
        or min(start[0], end[0]) > max_x
        or max(start[1], end[1]) < min_y
        or min(start[1], end[1]) > max_y
    ):
        return False
    if point_in_polygon(start, vertices) or point_in_polygon(end, vertices):
        return True
    return any(
        _segments_intersect(start, end, edge_start, edge_end)
        for edge_start, edge_end in zip(vertices, vertices[1:] + vertices[:1])
    )


@lru_cache(maxsize=4096)
def _polygon_bounds(vertices: tuple[Point, ...]) -> tuple[float, float, float, float]:
    return (
        min(point[0] for point in vertices),
        min(point[1] for point in vertices),
        max(point[0] for point in vertices),
        max(point[1] for point in vertices),
    )


def _is_simple_polygon(vertices: tuple[Point, ...]) -> bool:
    edge_count = len(vertices)
    for first_index in range(edge_count):
        first_start = vertices[first_index]
        first_end = vertices[(first_index + 1) % edge_count]
        for second_index in range(first_index + 1, edge_count):
            if second_index == first_index + 1 or (first_index == 0 and second_index == edge_count - 1):
                continue
            second_start = vertices[second_index]
            second_end = vertices[(second_index + 1) % edge_count]
            if _segments_intersect(first_start, first_end, second_start, second_end):
                return False
    return True


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    epsilon = 1e-9

    def orientation(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def sign(value: float) -> int:
        return 0 if abs(value) <= epsilon else (1 if value > 0.0 else -1)

    def on_segment(p: Point, q: Point, r: Point) -> bool:
        return (
            min(p[0], r[0]) - epsilon <= q[0] <= max(p[0], r[0]) + epsilon
            and min(p[1], r[1]) - epsilon <= q[1] <= max(p[1], r[1]) + epsilon
        )

    o1 = orientation(a, b, c)
    o2 = orientation(a, b, d)
    o3 = orientation(c, d, a)
    o4 = orientation(c, d, b)
    if sign(o1) * sign(o2) < 0 and sign(o3) * sign(o4) < 0:
        return True
    return (
        (sign(o1) == 0 and on_segment(a, c, b))
        or (sign(o2) == 0 and on_segment(a, d, b))
        or (sign(o3) == 0 and on_segment(c, a, d))
        or (sign(o4) == 0 and on_segment(c, b, d))
    )


def _point_on_segment(point: Point, start: Point, end: Point) -> bool:
    px, py = point
    sx, sy = start
    ex, ey = end
    cross = (px - sx) * (ey - sy) - (py - sy) * (ex - sx)
    if not math.isclose(cross, 0.0, abs_tol=1e-9):
        return False
    return (
        min(sx, ex) - 1e-9 <= px <= max(sx, ex) + 1e-9
        and min(sy, ey) - 1e-9 <= py <= max(sy, ey) + 1e-9
    )
