"""Deterministic grid A* and collision-safe waypoint simplification."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

from .geometry import Point
from .world import World


GridNode = tuple[int, int]
NEIGHBORS: tuple[GridNode, ...] = (
    (0, -1),
    (-1, 0),
    (1, 0),
    (0, 1),
    (-1, -1),
    (1, -1),
    (-1, 1),
    (1, 1),
)


@dataclass(frozen=True)
class PathResult:
    waypoints: tuple[Point, ...]
    total_distance: float
    expanded_nodes: int


class GridPathPlanner:
    """Eight-connected A* on a regular world-unit grid.

    Grid points in blocked or restricted geometry are excluded. Edges are checked
    against the same polygon predicates used by direct UAV motion; diagonal moves
    cannot cut between blocked cardinal neighbors.
    """

    def __init__(self, cell_size: float = 1.0, connector_radius_cells: int = 2) -> None:
        if not math.isfinite(cell_size) or cell_size <= 0.0:
            raise ValueError("cell_size must be finite and greater than zero")
        if connector_radius_cells < 0:
            raise ValueError("connector_radius_cells cannot be negative")
        self.cell_size = cell_size
        self.connector_radius_cells = connector_radius_cells

    def plan(
        self, start: Point, destination: Point, world: World, agent_id: str | None = None,
    ) -> PathResult | None:
        if not world.is_navigable(start, agent_id, allow_restricted_start=True) or not world.is_navigable(destination, agent_id):
            return None
        if world.segment_is_navigable(start, destination, agent_id):
            return PathResult((destination,), math.dist(start, destination), 0)

        max_x_index = math.ceil(world.width / self.cell_size)
        max_y_index = math.ceil(world.height / self.cell_size)
        start_node = self._connectable_node(start, world, max_x_index, max_y_index, agent_id)
        goal_node = self._connectable_node(destination, world, max_x_index, max_y_index, agent_id)
        if start_node is None or goal_node is None:
            return None

        frontier: list[tuple[float, float, float, int, int]] = []
        start_h = self._heuristic(start_node, goal_node, world)
        heapq.heappush(frontier, (start_h, 0.0, start_h, start_node[1], start_node[0]))
        came_from: dict[GridNode, GridNode | None] = {start_node: None}
        cost_so_far: dict[GridNode, float] = {start_node: 0.0}
        expanded_nodes = 0

        while frontier:
            _, queued_cost, _, node_y, node_x = heapq.heappop(frontier)
            current = (node_x, node_y)
            if current not in cost_so_far or queued_cost > cost_so_far[current] + 1e-9:
                continue
            expanded_nodes += 1
            if current == goal_node:
                break

            current_point = self._node_point(current, world)
            for dx, dy in NEIGHBORS:
                neighbor = (current[0] + dx, current[1] + dy)
                if not (0 <= neighbor[0] <= max_x_index and 0 <= neighbor[1] <= max_y_index):
                    continue
                neighbor_point = self._node_point(neighbor, world)
                if not world.is_navigable(neighbor_point, agent_id):
                    continue
                if not world.segment_is_navigable(current_point, neighbor_point, agent_id):
                    continue
                if dx and dy:
                    horizontal = self._node_point((current[0] + dx, current[1]), world)
                    vertical = self._node_point((current[0], current[1] + dy), world)
                    if not world.is_navigable(horizontal, agent_id) or not world.is_navigable(vertical, agent_id):
                        continue

                step_cost = math.dist(current_point, neighbor_point)
                candidate_cost = cost_so_far[current] + step_cost
                if candidate_cost + 1e-9 >= cost_so_far.get(neighbor, math.inf):
                    continue
                cost_so_far[neighbor] = candidate_cost
                came_from[neighbor] = current
                heuristic = self._heuristic(neighbor, goal_node, world)
                heapq.heappush(
                    frontier,
                    (candidate_cost + heuristic, candidate_cost, heuristic, neighbor[1], neighbor[0]),
                )

        if goal_node not in came_from:
            return None

        node_path: list[GridNode] = []
        current: GridNode | None = goal_node
        while current is not None:
            node_path.append(current)
            current = came_from[current]
        node_path.reverse()

        raw_points: list[Point] = [start]
        raw_points.extend(self._node_point(node, world) for node in node_path)
        raw_points.append(destination)
        raw_points = _remove_consecutive_duplicates(raw_points)
        waypoints = self._simplify(raw_points, world, agent_id)
        if waypoints is None:
            return None
        distance = sum(
            math.dist(left, right)
            for left, right in zip((start, *waypoints), waypoints)
        )
        return PathResult(tuple(waypoints), distance, expanded_nodes)

    def _connectable_node(
        self,
        point: Point,
        world: World,
        max_x_index: int,
        max_y_index: int,
        agent_id: str | None,
    ) -> GridNode | None:
        center_x = min(max(round(point[0] / self.cell_size), 0), max_x_index)
        center_y = min(max(round(point[1] / self.cell_size), 0), max_y_index)
        candidates: list[tuple[float, int, int, GridNode]] = []
        radius = self.connector_radius_cells
        for node_y in range(max(0, center_y - radius), min(max_y_index, center_y + radius) + 1):
            for node_x in range(max(0, center_x - radius), min(max_x_index, center_x + radius) + 1):
                node = (node_x, node_y)
                node_point = self._node_point(node, world)
                if not world.is_navigable(node_point, agent_id) or not world.segment_is_navigable(point, node_point, agent_id):
                    continue
                candidates.append((math.dist(point, node_point), node_y, node_x, node))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][3]

    def _node_point(self, node: GridNode, world: World) -> Point:
        return (
            min(node[0] * self.cell_size, world.width),
            min(node[1] * self.cell_size, world.height),
        )

    def _heuristic(self, left: GridNode, right: GridNode, world: World) -> float:
        return math.dist(self._node_point(left, world), self._node_point(right, world))

    @staticmethod
    def _simplify(points: list[Point], world: World, agent_id: str | None = None) -> list[Point] | None:
        if len(points) <= 1:
            return []
        simplified: list[Point] = [points[0]]
        anchor = 0
        while anchor < len(points) - 1:
            farthest = None
            for candidate in range(len(points) - 1, anchor, -1):
                if world.segment_is_navigable(points[anchor], points[candidate], agent_id):
                    farthest = candidate
                    break
            if farthest is None:
                return None
            simplified.append(points[farthest])
            anchor = farthest
        return simplified[1:]


def _remove_consecutive_duplicates(points: list[Point]) -> list[Point]:
    result: list[Point] = []
    for point in points:
        if not result or math.dist(result[-1], point) > 1e-9:
            result.append(point)
    return result
