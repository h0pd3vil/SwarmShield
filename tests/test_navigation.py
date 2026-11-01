import unittest

from swarmshield.config import SimulationConfig, UAVConfig
from swarmshield.geometry import world_geometry_from_dict
from swarmshield.navigation import GridPathPlanner
from swarmshield.session import SimulationSession
from swarmshield.world import World


def wall_geometry():
    return world_geometry_from_dict({
        "obstacles": [{
            "id": "wall",
            "kind": "building",
            "vertices": [[8, 5], [10, 5], [10, 15], [8, 15]],
        }],
    })


def multiple_obstacle_geometry():
    return world_geometry_from_dict({
        "obstacles": [
            {
                "id": "west-hangar",
                "kind": "building",
                "vertices": [[7, 3], [9, 3], [9, 15], [7, 15]],
            },
            {
                "id": "east-hangar",
                "kind": "building",
                "vertices": [[12, 5], [14, 5], [14, 17], [12, 17]],
            },
        ],
    })


def make_config(**overrides):
    values = {
        "seed": 29,
        "steps": 40,
        "world_width": 20,
        "world_height": 20,
        "observer_count": 1,
        "entity_count": 1,
        "detection_probability": 0.0,
        "geometry": wall_geometry(),
        "uav": UAVConfig(max_speed=1.0, acceleration=0.5, max_turn_rate_rad=0.5235987756),
    }
    values.update(overrides)
    return SimulationConfig(**values)


class GridPathPlannerTests(unittest.TestCase):
    def test_astar_routes_around_obstacle_deterministically(self):
        world = World(make_config(), seed=1)
        planner = GridPathPlanner(cell_size=1.0)

        first = planner.plan((6.0, 10.0), (14.0, 10.0), world)
        second = planner.plan((6.0, 10.0), (14.0, 10.0), world)

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertGreater(first.expanded_nodes, 0)
        self.assertGreater(first.total_distance, 8.0)
        self.assertTrue(first.waypoints)
        previous = (6.0, 10.0)
        for waypoint in first.waypoints:
            self.assertTrue(world.segment_is_navigable(previous, waypoint))
            previous = waypoint
        self.assertEqual(first.waypoints[-1], (14.0, 10.0))

    def test_direct_clear_route_does_not_expand_grid(self):
        world = World(make_config(geometry=world_geometry_from_dict({})), seed=1)

        path = GridPathPlanner().plan((2.0, 2.0), (5.0, 6.0), world)

        self.assertEqual(path.waypoints, ((5.0, 6.0),))
        self.assertEqual(path.total_distance, 5.0)
        self.assertEqual(path.expanded_nodes, 0)

    def test_unreachable_destination_is_reported_by_session(self):
        full_wall = world_geometry_from_dict({
            "obstacles": [{
                "id": "full-wall",
                "kind": "wall",
                "vertices": [[9, 0], [11, 0], [11, 20], [9, 20]],
            }],
        })
        session = SimulationSession(make_config(geometry=full_wall), "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 5.0, 10.0

        outcome = session.assign_destination(agent.agent_id, (15.0, 10.0), task_id="search-1")

        self.assertEqual(outcome["status"], "unreachable")
        self.assertEqual(agent.vehicle.status, "unreachable")
        self.assertEqual(session.observation_events[-1]["event_type"], "uav_destination_unreachable")

    def test_assigned_route_follows_waypoints_without_crossing_obstacle(self):
        session = SimulationSession(make_config(), "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 6.0, 10.0
        agent.vehicle.heading_rad = 0.0

        outcome = session.assign_destination(agent.agent_id, (14.0, 10.0), task_id="search-1")
        positions = [agent.vehicle.position]
        for _ in range(30):
            session.advance_tick()
            positions.append(agent.vehicle.position)
            self.assertTrue(session.world.segment_is_navigable(positions[-2], positions[-1]))
            if agent.vehicle.status == "arrived":
                break

        self.assertEqual(outcome["status"], "navigating")
        self.assertEqual(agent.vehicle.status, "arrived")
        self.assertEqual(agent.vehicle.position, (14.0, 10.0))
        self.assertTrue(any(event["event_type"] == "uav_route_planned" for event in session.observation_events))

    def test_motion_block_replans_around_newly_obstructed_route(self):
        session = SimulationSession(make_config(geometry=world_geometry_from_dict({})), "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 6.0, 10.0
        agent.vehicle.heading_rad = 0.0
        session.assign_destination(agent.agent_id, (14.0, 10.0))
        session.world.geometry = wall_geometry()

        for _ in range(12):
            session.advance_tick()
            if any(event["event_type"] == "uav_route_replanned" for event in session.observation_events):
                break

        event_types = [event["event_type"] for event in session.observation_events]
        self.assertIn("uav_navigation_blocked", event_types)
        self.assertIn("uav_route_replanned", event_types)
        self.assertEqual(agent.vehicle.status, "navigating")
        self.assertNotEqual(agent.vehicle.destination, (14.0, 10.0))

    def test_reproducible_trajectory_navigates_two_obstacles_within_limits(self):
        config = make_config(
            steps=40,
            observer_count=1,
            geometry=multiple_obstacle_geometry(),
            uav=UAVConfig(max_speed=1.0, acceleration=0.5, max_turn_rate_rad=0.5235987756),
        )
        trajectories = []
        for _ in range(2):
            session = SimulationSession(config, "independent")
            agent = session.agents["agent-001"]
            agent.vehicle.x, agent.vehicle.y = 3.0, 10.0
            agent.vehicle.heading_rad = 0.0
            session.assign_destination(agent.agent_id, (17.0, 10.0), task_id="search-2")
            trajectory = [agent.vehicle.position]
            previous_heading = agent.heading_rad
            for _ in range(config.steps):
                previous = agent.vehicle.position
                session.advance_tick()
                trajectory.append(agent.vehicle.position)
                self.assertTrue(session.world.in_bounds(agent.vehicle.position))
                self.assertTrue(session.world.segment_is_navigable(previous, agent.vehicle.position))
                self.assertLessEqual(agent.vehicle.speed, agent.vehicle.motion_config.max_speed)
                heading_change = abs(
                    (agent.heading_rad - previous_heading + 3.141592653589793)
                    % (2.0 * 3.141592653589793)
                    - 3.141592653589793
                )
                self.assertLessEqual(heading_change, agent.vehicle.motion_config.max_turn_rate_rad + 1e-9)
                previous_heading = agent.heading_rad
                if agent.vehicle.status == "arrived":
                    break
            self.assertEqual(agent.vehicle.status, "arrived")
            self.assertEqual(agent.vehicle.position, (17.0, 10.0))
            trajectories.append(trajectory)
        self.assertEqual(trajectories[0], trajectories[1])

    def test_uavs_do_not_share_mutable_waypoint_lists(self):
        session = SimulationSession(make_config(observer_count=2), "independent")
        first = session.agents["agent-001"]
        second = session.agents["agent-002"]
        first.vehicle.x, first.vehicle.y = 6.0, 10.0
        second.vehicle.x, second.vehicle.y = 14.0, 10.0
        first.vehicle.heading_rad = 0.0
        second.vehicle.heading_rad = 3.141592653589793

        session.assign_destination(first.agent_id, (14.0, 10.0))
        session.assign_destination(second.agent_id, (6.0, 10.0))
        second_route_before = list(second.vehicle.route_waypoints)
        first.vehicle.route_waypoints.clear()

        self.assertIsNot(first.vehicle.route_waypoints, second.vehicle.route_waypoints)
        self.assertEqual(second.vehicle.route_waypoints, second_route_before)

    def test_destination_on_world_boundary_stays_inside_world(self):
        session = SimulationSession(make_config(geometry=world_geometry_from_dict({})), "independent")
        agent = session.agents["agent-001"]
        agent.vehicle.x, agent.vehicle.y = 1.0, 1.0
        agent.vehicle.heading_rad = 3.141592653589793
        session.assign_destination(agent.agent_id, (0.0, 1.0))

        for _ in range(5):
            session.advance_tick()
            self.assertTrue(session.world.in_bounds(agent.vehicle.position))
            if agent.vehicle.status == "arrived":
                break

        self.assertEqual(agent.vehicle.status, "arrived")
        self.assertEqual(agent.vehicle.position, (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
